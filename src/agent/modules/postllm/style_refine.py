"""风格润色模块：将 LLM 初稿按 SkillCard 表达规则润色，保持语义不变。"""

import json

from ..base import PipelineModule
from ...context import PipelineContext
from ....config.logger import get_logger
from ....soul.prompt_builder import VOICE_PROSODY_RULES

log = get_logger("style_refine")


class StyleRefineModule(PipelineModule):
    """PostLLM 第二阶段：用 SkillCard.expression_dna 润色回复风格。

    在 QualityCheck 通过后执行，仅调整表达方式（句长、语气词、口头禅），
    不改变语义内容。无 SkillCard 或 expression_dna 为空时跳过。
    """

    _llm = None     # LLMClient
    _loader = None  # SoulLoader

    @classmethod
    def set_deps(cls, llm_client, soul_loader):
        cls._llm = llm_client
        cls._loader = soul_loader

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        # QualityCheck 已触发重生成，跳过
        if ctx.need_regenerate:
            return ctx

        if not ctx.response:
            return ctx

        # 加载 SkillCard
        if not self._loader.has_skill():
            return ctx

        skill = self._loader.load_skill()
        if not skill or not skill.expression_dna.strip():
            return ctx

        draft = ctx.response
        log.info("风格润色开始, draft_len=%d", len(draft))

        try:
            prompt = self._build_prompt(draft, skill.expression_dna.strip())
            log.debug("润色 prompt (len=%d):\n%s", len(prompt), prompt)
            chunks: list[str] = []
            async for token in self._llm.stream(
                [{"role": "user", "content": prompt}],
                max_tokens=2048,
                json_mode=True,
            ):
                chunks.append(token)
            raw = "".join(chunks)
            log.info("润色原始响应, len=%d, repr=%s", len(raw), repr(raw[:500]))
            polished = self._parse_result(raw)
            if polished and polished != draft:
                ctx.response = polished
                log.info("风格润色完成, polished_len=%d", len(polished))
            else:
                log.debug("风格润色: 无变化")
        except Exception as e:
            log.warning("风格润色失败，保留初稿: %s", e)

        return ctx

    def _build_prompt(self, draft: str, expression_rules: str) -> str:
        return f"""你是文本风格润色助手。将下面的回复按照表达规则润色。

规则优先级：表达规则决定用词和句式，语音韵律规则决定标点和语气词，两者不冲突。

【表达规则 — 决定用词和句式】
{expression_rules}

{VOICE_PROSODY_RULES}

【输出格式】
只输出一个 JSON 对象：{{"reply": "润色后的回复"}}

【待润色回复】
{draft}"""
    def _parse_result(self, raw: str) -> str:
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
            return str(data.get("reply", "")).strip()
        except json.JSONDecodeError:
            log.warning("润色结果 JSON 解析失败: %s", text[:200])
            return ""
