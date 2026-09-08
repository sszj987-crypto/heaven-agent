"""人物信息提取模块：从对话中谨慎提取逝者新事实，更新 soul 维度文件。

与 ChatCompressModule 分工：
- ChatCompressModule → 压缩对话摘要 → ChromaDB（检索用）
- MemoryExtractModule → 提取人物信息 → soul MD 文件（身份更新）
"""

import json
import asyncio

from ..base import PipelineModule
from ...context import PipelineContext
from ....config.logger import get_logger

log = get_logger("person_extract")

# 可更新的 soul 维度
_PERSON_DIMENSIONS: dict[str, str] = {
    "life_experiences": "人生经历（重要事件、转折点、成就等）",
    "emotional_anchors": "情感记忆（深刻的情感体验、与重要的人相关的回忆）",
    "relationships": "人际关系（与家人、朋友、同事等的关系描述）",
    "personal_traits": "个人特质（爱好、习惯、擅长/不擅长、性格特点）",
}


class MemoryExtractModule(PipelineModule):
    """每 crunch_interval 轮对话从对话中提取逝者新事实，更新 soul 维度文件。

    与旧版区别：
        - 旧版写入 ChromaDB → 现在追加到 soul MD 文件
        - 严格提示词：只提取明确的新信息，宁可漏过不要误加
        - 提取后自动刷新 SoulContextModule 缓存

    依赖注入:
        set_deps(llm_client, message_manager, soul_loader)
    """

    _llm = None          # LLMClient
    _messages = None     # MessageManager
    _loader = None       # SoulLoader
    _candidates = None   # CandidateStore
    _extracting: bool = False
    _crunch_interval: int = 10
    _job_manager = None

    @classmethod
    def set_deps(cls, llm_client, message_manager, soul_loader, candidates=None):
        cls._llm = llm_client
        cls._messages = message_manager
        cls._loader = soul_loader
        cls._candidates = candidates

    @classmethod
    def configure(cls, crunch_interval: int = 10):
        cls._crunch_interval = crunch_interval

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        turns = self._messages.conversation_turns
        interval = self._crunch_interval

        if turns <= 0 or turns % interval != 0:
            log.debug("人物信息提取跳过: turns=%d, 间隔=%d, 还需%d轮触发",
                      turns, interval, interval - (turns % interval))
            return ctx

        if self._extracting:
            log.debug("人物信息提取跳过: 上一轮提取仍在进行中")
            return ctx

        soul_name = ctx.soul_profile.name if ctx.soul_profile else "未知"
        # 取最近 8 轮对话
        recent = self._messages.conversation[-16:]

        log.info("触发人物信息提取, soul=%s, turns=%d, recent_msgs=%d",
                 soul_name, turns, len(recent))

        if self._job_manager is not None:
            self._job_manager.submit(
                "memory_extract", self._do_extract(soul_name, recent)
            )
        else:
            asyncio.create_task(self._do_extract(soul_name, recent))
        return ctx

    async def _do_extract(self, soul_name: str, recent: list[dict]):
        self._extracting = True
        try:
            prompt = self._build_prompt(soul_name, recent)
            messages = [{"role": "user", "content": prompt}]

            raw = await self._llm.chat(
                messages,
                timeout=120,
                max_tokens=1024,
                json_mode=True,
            )

            facts = self._parse_result(raw)
            source_excerpt = "\n".join(
                msg["content"] for msg in recent if msg.get("role") == "user"
            )[-1000:]
            queued = self._persist_candidates(facts, source_excerpt=source_excerpt)

            if queued:
                log.info("人物候选事实提取完成, soul=%s, turns=%d, queued=%d",
                         soul_name, self._messages.conversation_turns, queued)
            else:
                log.debug("人物信息提取: 无新的明确信息")

        except Exception as e:
            log.error("人物信息提取失败: %s", e)
        finally:
            self._extracting = False

    def _build_prompt(self, soul_name: str, history: list[dict]) -> str:
        dim_desc = "\n".join(
            f"- {key}（{label}）"
            for key, label in _PERSON_DIMENSIONS.items()
        )

        # 只使用用户提供的原始陈述。assistant 内容由模型生成，若将其作为
        # 人物事实来源会把幻觉永久写回 Soul 档案。
        conv_lines = []
        for msg in history:
            if msg["role"] == "user":
                conv_lines.append(f"对方提供的资料: {msg['content']}")
        conv_text = "\n".join(conv_lines)

        return f"""你是{soul_name}的记忆管家。请仔细阅读以下对话，提取{soul_name}在对话中**新透露的、之前未知的**个人信息。

可更新的维度：
{dim_desc}

对话内容：
{conv_text}

**重要：只提取明确的新信息。** 以下情况不提取：
- 模型回复不能作为人物事实来源；这里只能依据“对方提供的资料”
- 已经在之前对话中出现过的信息
- 寒暄、问候、日常闲聊中的非信息性内容
- 模糊、不确定、推测性的内容
- 无法从对方原话明确归属于{soul_name}的信息
- 不够具体、无法形成事实条目的一句话

如果发现值得记录的新事实，输出 JSON 数组：
[
  {{"dimension": "维度key", "content": "用逝者口吻描述的简洁事实，如'我曾在XX公司工作过3年'"}}
]

如果对话中没有值得记录的新信息，返回空数组 []。宁可漏过，不要误加。"""

    def _append_to_dimension(self, dim: str, content: str):
        """将新事实追加到 soul 维度文件末尾。"""
        current = self._loader.load_dimension(dim)
        # 在末尾追加新条目
        new_entry = f"\n- {content}"
        updated = (current.rstrip() if current else "") + new_entry + "\n"
        self._loader.save_dimension(dim, updated)
        log.info("维度已更新, dim=%s, entry=%s", dim, content[:80])

    def _persist_candidates(self, facts: list[dict], source_excerpt: str) -> int:
        """Queue facts for human review; never write generated facts directly."""
        if self._candidates is None:
            log.warning("候选事实存储未配置，跳过 %d 条提取结果", len(facts))
            return 0
        count = 0
        for fact in facts:
            dimension = fact.get("dimension", "")
            content = str(fact.get("content", "")).strip()
            if dimension not in _PERSON_DIMENSIONS or not content:
                continue
            confidence = fact.get("confidence", 0.7)
            try:
                confidence = max(0.0, min(1.0, float(confidence)))
            except (TypeError, ValueError):
                confidence = 0.7
            self._candidates.add(
                dimension=dimension,
                content=content,
                source_type="conversation",
                source_excerpt=source_excerpt,
                confidence=confidence,
            )
            count += 1
        return count

    def _parse_result(self, raw: str) -> list[dict]:
        text = raw.strip()

        if text.startswith("```"):
            lines = text.split("\n")
            end_idx = None
            for i in range(1, len(lines)):
                if lines[i].strip().startswith("```"):
                    end_idx = i
                    break
            if end_idx is not None:
                text = "\n".join(lines[1:end_idx]).strip()
            elif len(lines) > 1:
                text = "\n".join(lines[1:]).strip()

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        return v
            log.warning("提取结果格式不符合预期: %s", text[:200])
            return []
        except json.JSONDecodeError:
            log.warning("提取结果 JSON 解析失败: %s", text[:200])
            return []
