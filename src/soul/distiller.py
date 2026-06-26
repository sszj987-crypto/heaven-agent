"""
灵魂档案蒸馏器：从聊天记录中提取人格特征 + 行为规则，智能合并到灵魂档案。

两阶段蒸馏：
  Phase 1: 事实提取（更新 10 个 soul 维度）
  Phase 2: 女娲式多维度并行行为规则提取（生成 Skill Card）

用法:
    distiller = SoulDistiller(llm_client, soul_loader)
    result = await distiller.distill(raw_chat_text)
    # result.changes → 有变化的维度名列表
    # result.profile → 更新后的全部维度内容
    # result.skill_card → 行为规则卡（Phase 2 产出）
    # result.summary → LLM 分析摘要
"""

import json
from dataclasses import dataclass, field

from ..llm.client import LLMClient
from ..soul.loader import SoulLoader
from ..soul.profile import DIMENSION_NAMES
from ..soul.skill_card import SkillCard
from ..soul.chat_preprocessor import ChatPreprocessor, PreprocessedChat
from ..soul.phase2_agents import Phase2Agents
from ..config.logger import get_logger

log = get_logger("distiller")

# 维度中文名
DIMENSION_LABELS: dict[str, str] = {
    "basic_info": "基本信息",
    "personality": "性格",
    "life_experiences": "人生经历",
    "relationships": "人际关系",
    "personal_traits": "个人特质",
    "emotional_anchors": "情感锚点",
}


@dataclass
class DistillResult:
    """蒸馏结果"""
    changes: list[str] = field(default_factory=list)    # 有变化的维度名
    profile: dict[str, str] = field(default_factory=dict)  # 更新后的全维度
    skill_card: SkillCard | None = None                    # Phase 2 产出的行为规则卡
    summary: str = ""                                     # 分析摘要


class SoulDistiller:
    """从聊天记录批量提取人格特征，智能合并到灵魂档案。"""

    def __init__(self, llm_client: LLMClient, soul_loader: SoulLoader,
                 max_retries: int = 2):
        self._llm = llm_client
        self._loader = soul_loader
        self._max_retries = max_retries
        log.info("SoulDistiller 初始化, max_retries=%d", max_retries)

    # ── 公开接口 ──────────────────────────────────────────

    async def distill(self, raw_chat_text: str, chat_name: str = "") -> DistillResult:
        """
        分析聊天记录、更新灵魂档案 + 提取行为规则。

        Args:
            raw_chat_text: 原始聊天记录（微信/QQ 导出格式）
            chat_name: 目标人物在聊天记录中显示的名字（为空时使用档案姓名自动匹配）

        Raises:
            ValueError: 聊天记录为空
            RuntimeError: LLM 调用/解析失败
        """
        raw_chat_text = raw_chat_text.strip()
        if not raw_chat_text:
            raise ValueError("聊天记录为空")

        profile = self._loader.load()

        # 预处理：格式精炼 + 统计提取 + 结构化（Layer 1+2+3）
        cp = ChatPreprocessor()
        preprocessed = cp.process(raw_chat_text, target_name=chat_name or profile.name)
        refined_text = preprocessed.refined_text
        log.info("预处理完成: raw=%d chars → refined=%d chars, speakers=%d, "
                 "rounds=%d, opinions=%d, values=%d",
                 len(raw_chat_text), len(refined_text),
                 len(preprocessed.speakers), len(preprocessed.dialogue_rounds),
                 len(preprocessed.opinion_segments), len(preprocessed.value_segments))

        log.info("蒸馏开始, refined_size=%d chars, soul=%s",
                 len(refined_text), profile.name)

        # Phase 1: 事实提取（使用精炼文本）
        new_dimensions, summary = await self._call_llm_phase1(profile, refined_text)
        changes = self._save_changes(profile, new_dimensions)

        # Phase 2: 女娲式多维度并行行为规则提取（使用差异化采样）
        existing_skill = self._loader.load_skill()
        agents = Phase2Agents(self._llm, max_retries=self._max_retries)
        skill_card = await agents.run_all(
            preprocessed, existing_skill, soul_name=profile.name)

        # 保存 Skill Card
        if skill_card and skill_card.has_content:
            self._loader.save_skill(skill_card)

        if skill_card and skill_card.has_content:
            filled = [k for k, v in skill_card.to_dict().items() if v.strip()]
            summary += f" | 行为规则已提取 ({', '.join(filled)})"

        log.info("蒸馏完成, changes=%s, has_skill=%s",
                 changes, bool(skill_card and skill_card.has_content))
        return DistillResult(
            changes=changes,
            profile=self._merge_profile(profile, new_dimensions),
            skill_card=skill_card,
            summary=summary,
        )

    # ── LLM 调用 ──────────────────────────────────────────

    _DISTILL_TIMEOUT = 300

    async def _call_llm_phase1(self, profile, chat_text: str) -> tuple[dict[str, str], str]:
        """Phase 1: 调用 LLM 分析聊天记录，返回 (new_dimensions, summary)。含重试逻辑。"""
        messages = self._build_messages(profile, chat_text)

        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                if attempt > 0:
                    log.warning("蒸馏 LLM 重试 %d/%d", attempt, self._max_retries)
                raw_response = await self._llm.chat(
                    messages, timeout=self._DISTILL_TIMEOUT, max_tokens=8192,
                    json_mode=True)
                break
            except Exception as e:
                last_error = e
                log.error("蒸馏 LLM 调用失败 (attempt %d/%d): %s",
                          attempt + 1, self._max_retries + 1, e)
                if attempt < self._max_retries:
                    import asyncio
                    await asyncio.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(
                f"LLM 调用失败（已重试 {self._max_retries} 次）: {last_error}"
            ) from last_error

        log.debug("LLM 原始响应 (%d chars): %s",
                  len(raw_response), raw_response[:500])

        try:
            return self._parse_response(raw_response)
        except Exception as e:
            log.error("蒸馏响应解析失败: %s\nraw=%s", e, raw_response[:1000])
            raise RuntimeError(f"LLM 响应解析失败: {e}") from e

    # ── 保存变更 ──────────────────────────────────────────

    def _save_changes(self, profile, new_dimensions: dict[str, str]) -> list[str]:
        """对比新旧维度，保存有变化的维度。返回变化维度列表。"""
        changes = []
        for dim in DIMENSION_NAMES:
            old_content = profile.dimensions.get(dim, "").strip()
            new_content = new_dimensions.get(dim, "").strip()
            if new_content and new_content != old_content:
                try:
                    self._loader.save_dimension(dim, new_content)
                    changes.append(dim)
                    log.info("维度已更新: %s, old_len=%d, new_len=%d",
                             dim, len(old_content), len(new_content))
                except Exception as e:
                    log.error("保存维度 %s 失败: %s", dim, e)
        return changes

    @staticmethod
    def _merge_profile(profile, new_dimensions: dict[str, str]) -> dict[str, str]:
        """合并档案，新内容覆盖旧内容。"""
        return {
            dim: new_dimensions.get(dim, profile.dimensions.get(dim, ""))
            for dim in DIMENSION_NAMES
        }

    # ── Prompt 构建 ───────────────────────────────────────

    def _build_messages(self, profile, chat_text: str) -> list[dict]:
        """构建 LLM 请求的 messages"""
        dimensions_md = self._format_current_profile(profile)

        return [
            {"role": "system", "content": _DISTILL_SYSTEM_PROMPT},
            {"role": "user", "content": _DISTILL_USER_TEMPLATE.format(
                dimensions_md=dimensions_md,
                chat_text=chat_text,
            )},
        ]

    def _format_current_profile(self, profile) -> str:
        """格式化当前档案为 prompt 文本"""
        parts = []
        for dim in DIMENSION_NAMES:
            content = profile.dimensions.get(dim, "").strip()
            label = DIMENSION_LABELS.get(dim, dim)
            if content:
                parts.append(f"### {label} ({dim})\n{content}")
            else:
                parts.append(f"### {label} ({dim})\n（暂无内容）")
        return "\n\n".join(parts)

    def _parse_response(self, raw: str) -> tuple[dict[str, str], str]:
        """解析 LLM 响应，提取维度内容和摘要。"""
        text = raw.strip()
        text = _strip_markdown_fence(text)
        data = self._try_parse_json(text)

        dimensions = data.get("dimensions", {})
        summary = data.get("summary", "")

        filtered = {}
        for dim in DIMENSION_NAMES:
            val = dimensions.get(dim, "UNCHANGED")
            if val and val != "UNCHANGED":
                filtered[dim] = str(val)

        return filtered, str(summary)

    @staticmethod
    def _try_parse_json(text: str) -> dict:
        """尝试解析 JSON，截断时自动修复。"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        fixes = [
            '"}',
            '"}}',
            '"\n}\n}',
            '"}]}',
            '",\n"summary": "分析完成"}}',
        ]
        for suffix in fixes:
            try:
                return json.loads(text + suffix)
            except json.JSONDecodeError:
                continue

        raise RuntimeError(
            f"JSON 解析失败且无法自动修复, text_len={len(text)}, "
            f"tail={repr(text[-100:])}"
        )


# ── helpers ────────────────────────────────────────────────

def _strip_markdown_fence(text: str) -> str:
    """去除 ```json ... ``` 包裹"""
    if text.startswith("```"):
        lines = text.split("\n")
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip().startswith("```"):
                end_idx = i
                break
        if end_idx is not None:
            return "\n".join(lines[1:end_idx]).strip()
        elif len(lines) > 1:
            return "\n".join(lines[1:]).strip()
    return text


# ── Prompt 模板 ──────────────────────────────────────────────

_DISTILL_SYSTEM_PROMPT = """你是一个灵魂档案分析师。你的任务是从聊天记录中提取关于**目标人物（逝者/灵魂本人）**的信息，更新其灵魂档案。

**关键原则：只分析档案主人的特征！**
- 聊天记录中有多个人发言，你必须只提取档案主人（在"当前灵魂档案"的 basic_info 中能找到姓名）的信息
- 对方的说话内容、性格、习惯等都不应被提取到档案中
- 从档案主人的发言中提取他的口头禅、性格、情感等
- 从对方的发言中提取关于档案主人的描述（如对方说"你就是爱逞强"→提取为档案主人的性格特征）
- 如果一段内容描述的是聊天对方的特征，忽略它

## 灵魂档案的 6 个维度

1. **basic_info** — 基本信息：姓名、性别、年龄、籍贯、职业、生卒年份等。格式：`字段: 值`
2. **personality** — 性格特征：性格标签（列表）、性格类型参考（如 MBTI）
3. **life_experiences** — 人生经历：按年份排列的重要事件（出生、求学、工作、婚姻、退休等）
4. **relationships** — 人际关系：重要的人，格式为 `- 姓名: 关系, 称呼, 备注`
5. **personal_traits** — 个人特质：爱好、习惯、擅长的事。格式为列表 `- 描述`
6. **emotional_anchors** — 情感锚点：重要的情感记忆，格式为 `- 事件简述: 情绪类型（如自豪/温暖/遗憾），描述`

## 合并规则（严格遵守）

1. **追加**：新信息与现有内容不矛盾时，追加到对应段落末尾
2. **保留**：新证据印证了已有内容时，保留原有内容不变
3. **替换**：新证据与现有内容明确矛盾时，用新内容替换旧条目
4. **创建**：发现了现有档案中完全没有的新信息，创建新的条目
5. **绝不删除**：除非存在明确矛盾，否则不删除任何已有描述
6. **证据优先**：只提取聊天记录中明确体现的信息，不要凭空推测

## 需要特别关注的信息

- 说话风格：口头禅、语气词使用频率、句子长短、标点符号习惯
- 情感表达：开心时怎么说、难过时怎么说、安慰人时怎么说
- 对人的称呼：怎么称呼配偶、孩子、朋友、同事
- 生活细节：吃什么、玩什么、日常习惯、特殊癖好
- 价值观线索：对金钱、家庭、工作、朋友的态度
"""

_DISTILL_USER_TEMPLATE = """## 当前灵魂档案

{dimensions_md}

## 聊天记录

{chat_text}

---

请分析以上聊天记录，对每个维度输出更新后的完整 markdown 内容。
如果某个维度根据聊天记录没有新发现、不需要更新，该维度的值设置为字符串 "UNCHANGED"。

输出格式为严格的 JSON 对象（不要用代码块包裹）：
{{
  "dimensions": {{
    "personality": "更新后的完整 markdown...",
    "personal_traits": "更新后的完整 markdown...",
    "basic_info": "UNCHANGED"
  }},
  "summary": "用一句话总结从聊天记录中发现的关键人格线索"
}}"""
