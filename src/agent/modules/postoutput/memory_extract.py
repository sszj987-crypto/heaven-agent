"""对话 → 记忆自动提取模块。

每 N 轮对话触发一次，后台异步调用 LLM 从最近对话中提取新事实，
写入 ChromaDB 记忆库，实现记忆系统的读写闭环。
"""

import json
import asyncio

from ..base import PipelineModule
from ...context import PipelineContext
from ....config.logger import get_logger

log = get_logger("memory_extract")

# 记忆维度及中文标签（与 MemorySynchronizer.MEMORY_DIMENSIONS 保持一致）
_MEMORY_DIMENSION_LABELS: dict[str, str] = {
    "life_experiences": "人生经历",
    "emotional_anchors": "情感记忆",
    "relationships": "人际关系",
    "hobbies": "爱好",
    "special_habits": "习惯",
    "knowledge_domain": "擅长的事",
}


class MemoryExtractModule(PipelineModule):
    """每 N 轮对话自动从对话历史中提取新事实，写入 ChromaDB。

    依赖注入（由 AgentLoop 初始化）:
        set_deps(store, llm_client, message_manager)

    触发策略:
        - 每 EXTRACT_EVERY_N_TURNS 轮对话触发一次
        - 后台 asyncio.create_task 执行，不阻塞用户
        - 防重入：上一次提取未完成时跳过
    """

    EXTRACT_EVERY_N_TURNS = 10

    _store = None          # MemoryStore
    _llm = None            # LLMClient
    _messages = None       # MessageManager
    _last_extracted_turn: int = 0
    _extracting: bool = False

    @classmethod
    def set_deps(cls, store, llm_client, message_manager):
        cls._store = store
        cls._llm = llm_client
        cls._messages = message_manager

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        turns = self._messages.conversation_turns

        # 轮数阈值检查
        if turns - self._last_extracted_turn < self.EXTRACT_EVERY_N_TURNS:
            log.debug("轮数未达阈值, turns=%d, last=%d, skip",
                      turns, self._last_extracted_turn)
            return ctx

        # 防重入
        if self._extracting:
            log.debug("上一次提取未完成，跳过本轮")
            return ctx

        soul_name = ctx.soul_profile.name if ctx.soul_profile else "未知"
        # 取最近 5 轮对话（10 条 user/assistant 消息）
        recent = self._messages.conversation[-10:]

        log.info("触发记忆提取, soul=%s, turns=%d, recent_msgs=%d",
                 soul_name, turns, len(recent))

        asyncio.create_task(self._do_extract(soul_name, recent, turns))
        return ctx

    async def _do_extract(self, soul_name: str, recent: list[dict],
                          current_turn: int):
        """后台执行：构建 prompt → 调用 LLM → 解析 → 写入 ChromaDB。"""
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
            count = 0
            for fact in facts:
                dim = fact.get("dimension", "")
                content = fact.get("content", "")
                if dim not in _MEMORY_DIMENSION_LABELS or not content:
                    continue
                keywords = fact.get("keywords", [])
                self._store.add(dim, content, {"keywords": keywords})
                count += 1

            self.__class__._last_extracted_turn = current_turn
            log.info("记忆提取完成, soul=%s, turns=%d, extracted=%d",
                     soul_name, current_turn, count)

        except Exception as e:
            log.error("记忆提取失败: %s", e)
        finally:
            self.__class__._extracting = False

    def _build_prompt(self, soul_name: str, history: list[dict]) -> str:
        """构建提取 prompt。"""
        dim_desc = "\n".join(
            f"- {key}（{label}）"
            for key, label in _MEMORY_DIMENSION_LABELS.items()
        )

        conv_lines = []
        for msg in history:
            label = soul_name if msg["role"] == "assistant" else "对方"
            conv_lines.append(f"{label}: {msg['content']}")
        conv_text = "\n".join(conv_lines)

        return f"""你是{soul_name}的记忆管家。请从以下对话中提取关于{soul_name}的**新事实**，归类到对应维度。

可用的记忆维度：
{dim_desc}

对话内容：
{conv_text}

请提取对话中{soul_name}提到的关于自己的信息（新增的、之前未记录过的），输出为 JSON 数组：
[
  {{"dimension": "维度key", "content": "简洁的事实描述", "keywords": ["关键词1", "关键词2"]}}
]

要求：
- 只提取{soul_name}相关的信息（不提取对方的信息）
- 每条事实用一句话概括，清晰简洁
- 如果对话中没有值得记录的新信息，返回空数组 []
- 忽略日常寒暄、问候等无信息量的对话"""

    def _parse_result(self, raw: str) -> list[dict]:
        """解析 LLM 返回的 JSON。"""
        text = raw.strip()

        # 去除可能的 markdown 代码块
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
            # 兼容 {"facts": [...]} / {"extractions": [...]} 等包裹
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        return v
            log.warning("提取结果格式不符合预期: %s", text[:200])
            return []
        except json.JSONDecodeError:
            log.warning("提取结果 JSON 解析失败: %s", text[:200])
            return []
