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
    """每 N 轮对话从对话中提取逝者新事实，更新 soul 维度文件。

    与旧版区别：
        - 旧版写入 ChromaDB → 现在追加到 soul MD 文件
        - 严格提示词：只提取明确的新信息，宁可漏过不要误加
        - 提取后自动刷新 SoulContextModule 缓存

    依赖注入:
        set_deps(llm_client, message_manager, soul_loader)
    """

    EXTRACT_EVERY_N_TURNS = 10

    _llm = None          # LLMClient
    _messages = None     # MessageManager
    _loader = None       # SoulLoader
    _last_extracted_turn: int = 0
    _extracting: bool = False

    @classmethod
    def set_deps(cls, llm_client, message_manager, soul_loader):
        cls._llm = llm_client
        cls._messages = message_manager
        cls._loader = soul_loader

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        turns = self._messages.conversation_turns

        if turns - self._last_extracted_turn < self.EXTRACT_EVERY_N_TURNS:
            return ctx

        if self._extracting:
            return ctx

        soul_name = ctx.soul_profile.name if ctx.soul_profile else "未知"
        # 取最近 8 轮对话
        recent = self._messages.conversation[-16:]

        log.info("触发人物信息提取, soul=%s, turns=%d, recent_msgs=%d",
                 soul_name, turns, len(recent))

        asyncio.create_task(self._do_extract(soul_name, recent, turns))
        return ctx

    async def _do_extract(self, soul_name: str, recent: list[dict],
                          current_turn: int):
        self.__class__._extracting = True
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
            updated_dims: set[str] = set()
            for fact in facts:
                dim = fact.get("dimension", "")
                content = fact.get("content", "")
                if dim not in _PERSON_DIMENSIONS or not content:
                    continue
                self._append_to_dimension(dim, content)
                updated_dims.add(dim)

            if updated_dims:
                self.__class__._last_extracted_turn = current_turn
                log.info("人物信息提取完成, soul=%s, turns=%d, updated_dims=%s",
                         soul_name, current_turn, updated_dims)
                # 刷新 soul 缓存，让下次对话使用最新内容
                from ..prellm.soul_context import SoulContextModule
                SoulContextModule.invalidate()
            else:
                log.debug("人物信息提取: 无新的明确信息")

        except Exception as e:
            log.error("人物信息提取失败: %s", e)
        finally:
            self.__class__._extracting = False

    def _build_prompt(self, soul_name: str, history: list[dict]) -> str:
        dim_desc = "\n".join(
            f"- {key}（{label}）"
            for key, label in _PERSON_DIMENSIONS.items()
        )

        conv_lines = []
        for msg in history:
            label = soul_name if msg["role"] == "assistant" else "对方"
            conv_lines.append(f"{label}: {msg['content']}")
        conv_text = "\n".join(conv_lines)

        return f"""你是{soul_name}的记忆管家。请仔细阅读以下对话，提取{soul_name}在对话中**新透露的、之前未知的**个人信息。

可更新的维度：
{dim_desc}

对话内容：
{conv_text}

**重要：只提取明确的新信息。** 以下情况不提取：
- 已经在之前对话中出现过的信息
- 寒暄、问候、日常闲聊中的非信息性内容
- 模糊、不确定、推测性的内容
- 对方提到而不是逝者本人确认的信息
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
