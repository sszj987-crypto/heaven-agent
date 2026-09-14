from .profile import SoulProfile
from .skill_card import SkillCard
from ..config.logger import get_logger
from ..services.narrative import NarrativePolicy

log = get_logger("prompt_builder")
_NARRATIVE_POLICY = NarrativePolicy()


class SoulPromptBuilder:
    """将 Soul 档案 + Skill 规则 + 场景 + 检索记忆 拼装为 System Prompt。

    结构顺序：
    1. 核心约束 → 2. 扮演规则 → 3. 决策启发 → 4. 表达基因
    5. 思维模型 → 6. 价值禁区 → 7. 内在矛盾 → 8. 身份卡
    9. Soul维度 → 10. 记忆 → 11. 场景 → 12. 回复格式

    无 SkillCard 时（冷启动），用 soul 维度兜底。
    """

    def build(self, profile: SoulProfile, circumstances: str,
              skill_card: SkillCard | None = None,
              memories: list[dict] | None = None,
              afterlife_topic_allowed: bool = False) -> str:
        soul_name = profile.name

        if skill_card and skill_card.has_content:
            prompt = (
                self._format_core_constraint()
                + self._build_priority_skill_sections(
                    skill_card, soul_name, afterlife_topic_allowed
                )
                + self._format_identity_card(profile, afterlife_topic_allowed)
                + self._format_soul_dimensions(profile, afterlife_topic_allowed)
                + self._build_support_skill_sections(skill_card, afterlife_topic_allowed)
                + self._format_memories(memories, afterlife_topic_allowed)
                + self._format_circumstances(circumstances, afterlife_topic_allowed)
                + self._format_topic_boundary(afterlife_topic_allowed)
                + self._format_reply_constraints()
            )
        else:
            # 冷启动：无 SkillCard，用 soul 维度全覆盖
            prompt = self._build_legacy(
                profile,
                circumstances,
                soul_name,
                memories,
                afterlife_topic_allowed,
            )

        log.info("System Prompt 构建完成, length=%d chars, has_skill=%s, memories=%d",
                 len(prompt), bool(skill_card and skill_card.has_content),
                 len(memories) if memories else 0)
        return prompt

    # ── Skill Card Sections ──────────────────────────────

    def _build_priority_skill_sections(
        self,
        skill: SkillCard,
        name: str,
        afterlife_topic_allowed: bool,
    ) -> str:
        """Primacy 区：核心行为规则（扮演规则 + 决策启发 + 表达基因）。"""
        parts = []

        role_rules = self._visible_text(skill.role_playing_rules, afterlife_topic_allowed)
        if role_rules:
            parts.append(f"【你是{name}本人 — 扮演规则】\n{role_rules}")

        heuristics = self._visible_text(skill.decision_heuristics, afterlife_topic_allowed)
        if heuristics:
            parts.append(f"【你的行为模式 — 决策启发式】\n{heuristics}")

        expression = self._visible_text(skill.expression_dna, afterlife_topic_allowed)
        if expression:
            parts.append(f"【你的说话方式 — 表达基因】\n{expression}")

        return "\n\n".join(parts) + "\n\n" if parts else ""

    def _build_support_skill_sections(
        self,
        skill: SkillCard,
        afterlife_topic_allowed: bool,
    ) -> str:
        """Middle 区：辅助背景（思维模型 + 价值观 + 矛盾），放在身份信息之后。"""
        parts = []

        mental_models = self._visible_text(skill.mental_models, afterlife_topic_allowed)
        if mental_models:
            parts.append(f"【你的思维方式】\n{mental_models}")

        values = self._visible_text(skill.values_anti_patterns, afterlife_topic_allowed)
        if values:
            parts.append(f"【你的价值观与底线】\n{values}")

        tensions = self._visible_text(skill.inner_tensions, afterlife_topic_allowed)
        if tensions:
            parts.append(f"【你的内在矛盾】\n{tensions}")

        return "\n\n".join(parts) + "\n\n" if parts else ""

    # ── Identity Card ────────────────────────────────────

    def _format_identity_card(
        self,
        profile: SoulProfile,
        afterlife_topic_allowed: bool,
    ) -> str:
        """basic_info + personality 摘要 → 身份卡。"""
        basic = self._visible_profile_dimension(
            profile, "basic_info", afterlife_topic_allowed
        )
        personality = self._visible_profile_dimension(
            profile, "personality", afterlife_topic_allowed
        )

        if not basic and not personality:
            return ""

        parts = ["【你的身份信息】"]
        if basic:
            parts.append(basic)
        if personality:
            parts.append(personality)
        return "\n".join(parts) + "\n\n"

    # ── Soul Dimensions（补充维度，有 SkillCard 时轻量展示）──

    def _format_soul_dimensions(
        self,
        profile: SoulProfile,
        afterlife_topic_allowed: bool,
    ) -> str:
        """有 SkillCard 时只展示核心补充维度（语言习惯/价值观已由 SkillCard 接管）。"""
        dims = [
            ("life_experiences", "你的人生经历"),
            ("relationships", "你的人际关系"),
            ("personal_traits", "你的个人特质"),
            ("emotional_anchors", "重要的情感记忆"),
        ]

        parts = []
        for dim_key, label in dims:
            content = self._visible_profile_dimension(
                profile, dim_key, afterlife_topic_allowed
            )
            if content and content != "暂无":
                parts.append(f"【{label}】\n{content}")

        return "\n\n".join(parts) + "\n\n" if parts else ""

    # ── Memories ──────────────────────────────────────────

    def _format_memories(
        self,
        memories: list[dict] | None,
        afterlife_topic_allowed: bool,
    ) -> str:
        """将检索到的记忆格式化为 prompt 片段。"""
        if not memories:
            return ""

        lines = ["【已确认人物资料 — 可在对话中自然引用】"]
        for m in memories:
            dim = m.get("metadata", {}).get("dimension", "")
            doc = self._visible_text(
                m.get("document", ""), afterlife_topic_allowed
            )
            if doc:
                label = f"（{dim}）" if dim else ""
                lines.append(f"- {label}{doc}")
        return "\n".join(lines) + "\n\n" if len(lines) > 1 else ""

    # ── Circumstances ─────────────────────────────────────

    @staticmethod
    def _format_circumstances(
        circumstances: str,
        afterlife_topic_allowed: bool,
    ) -> str:
        if not circumstances.strip():
            return ""
        if (
            not afterlife_topic_allowed
            and _NARRATIVE_POLICY.contains_sensitive_scene(circumstances)
        ):
            return ""
        return f"【当前场景】\n{circumstances.strip()}\n\n"

    # ── Core Constraint (primacy 区：角色身份 + 禁止事项) ──

    def _format_core_constraint(self) -> str:
        return _CORE_CONSTRAINT

    @staticmethod
    def _format_topic_boundary(afterlife_topic_allowed: bool) -> str:
        if afterlife_topic_allowed:
            instruction = (
                "用户本轮主动提及离世或来世话题，可以温柔承接；"
                "但不得声称这是与真实逝者或真实来世的通信。"
            )
        else:
            instruction = (
                "用户本轮没有主动提及离世或来世。不得主动描述自己已经去世、"
                "身处天堂或另一个世界，也不得使用‘我在这边/那边挺好’等来世状态表述。"
            )
        return f"【本轮敏感叙事边界】\n{instruction}\n\n"

    # ── Reply Constraints (recency 区：格式 + 韵律) ────────

    def _format_reply_constraints(self) -> str:
        return _REPLY_CONSTRAINTS

    # ── Legacy（无 SkillCard 时的完整兜底）────────────────

    def _build_legacy(self, profile: SoulProfile, circumstances: str,
                      soul_name: str, memories: list[dict] | None = None,
                      afterlife_topic_allowed: bool = False) -> str:
        """冷启动：无 SkillCard，所有 6 个维度全量注入。"""
        prompt = _LEGACY_TEMPLATE.format(
            basic_info=self._visible_profile_dimension(
                profile, "basic_info", afterlife_topic_allowed
            ),
            personality=self._visible_profile_dimension(
                profile, "personality", afterlife_topic_allowed
            ),
            life_experiences=self._visible_profile_dimension(
                profile, "life_experiences", afterlife_topic_allowed
            ),
            relationships=self._visible_profile_dimension(
                profile, "relationships", afterlife_topic_allowed
            ),
            personal_traits=self._visible_profile_dimension(
                profile, "personal_traits", afterlife_topic_allowed
            ),
            emotional_anchors=self._visible_profile_dimension(
                profile, "emotional_anchors", afterlife_topic_allowed
            ),
            circumstances=(
                self._strip_title(circumstances)
                if afterlife_topic_allowed
                or not _NARRATIVE_POLICY.contains_sensitive_scene(circumstances)
                else ""
            ),
            memory_section=self._format_memories(memories, afterlife_topic_allowed),
            soul_name=soul_name,
            narrative_boundary=self._format_topic_boundary(afterlife_topic_allowed),
            reply_constraints=_REPLY_CONSTRAINTS,
        )
        return prompt

    def _visible_profile_dimension(
        self,
        profile: SoulProfile,
        dimension: str,
        afterlife_topic_allowed: bool,
    ) -> str:
        return self._visible_text(
            self._strip_title(profile.get(dimension)),
            afterlife_topic_allowed,
        )

    @staticmethod
    def _visible_text(text: str, afterlife_topic_allowed: bool) -> str:
        return _NARRATIVE_POLICY.redact_profile_text(
            text.strip() if text else "",
            afterlife_topic_allowed=afterlife_topic_allowed,
        )

    def _strip_title(self, content: str) -> str:
        """去除第一行的 # 标题"""
        if not content:
            return "暂无"
        lines = content.split("\n")
        if lines and lines[0].startswith("# "):
            lines = lines[1:]
        while lines and lines[0].strip() == "":
            lines = lines[1:]
        return "\n".join(lines).strip()


# ── Legacy Template（无 SkillCard 时使用）────────────────

_LEGACY_TEMPLATE = """{basic_info}

【你的性格】
{personality}

【你的人生经历】
{life_experiences}

【你的人际关系】
{relationships}

【你的个人特质】
{personal_traits}

【重要的情感记忆】
{emotional_anchors}

【当前场景】
{circumstances}
{memory_section}
【人物模拟边界 — 绝对遵守，不可违反】
1. 你正在依据用户提供的资料进行{soul_name}的人物模拟，用熟悉、自然的口吻回应。
2. 不主动讨论技术实现，也绝不声称自己是真实逝者、真实来世或能取代现实关系；若被直接询问，诚实说明这是基于资料生成的数字纪念体验。
3. 若资料没有明确提供答案，要自然承认不确定或记不清，不要编造学校、地点、事件、关系等人物事实。
4. 不要表现慌张，不要催促对方"放下"或"想开点"。
5. 用你的口头禅和说话习惯自然回应，就像真正的{soul_name}本人。
6. 若提供的资料互相冲突，要说明存在不同记录，不要擅自选择其中一个作为事实。

{narrative_boundary}
{reply_constraints}
"""
# ── 语音韵律控制（初稿和润色阶段共用）─────────────────

VOICE_PROSODY_RULES = """【instruct 生成原则 — 根据本轮回复判断】
1. instruct 是开放的自然语言语音指导，可以细腻描述语气、情绪、轻重、节奏、停顿和语调；但必须与本轮 reply 实际表达一致，不要照抄示例或只根据人物的总体性格发挥。
2. 判断顺序：先看 reply 的语义和标点，再看用户本轮情绪，最后才参考人物平时的表达风格。不要在 instruct 中加入 reply 没有体现的情绪或节奏。
3. 普通问候、简短日常对话和普通问句默认使用正常语速。温暖、亲昵本身不是放慢语速的理由，不要无依据地写“稍慢”“缓慢”。
4. 只有 reply 明确在安慰、哀伤、迟疑、郑重表达，或使用停顿、省略号呈现舒缓节奏时，才描述慢速；开心、轻快、连续感叹或连续问句应使用正常或稍快语速。
5. 做一致性检查：不得出现“轻快但慢速”“平静但急促”等互相冲突的组合。若没有充分依据，优先选择自然语气和正常语速。
6. instruct 只写给语音引擎的说话方式，不得包含动作、台词、人物事实、方言要求或原因解释。

reply 的标点也应自然配合语义：迟疑或安抚可用少量省略号，轻快可用感叹号，疑问用问号；不要为了控制语音堆砌标点。不要在 reply 中使用动作描写（如 *叹气*、*笑着说*、*抹眼泪*），语音引擎会把它们当成文字读出。"""

# ── Core Constraint（primacy 区：角色身份 + 禁止事项）─────

_CORE_CONSTRAINT = """【核心人物模拟约束 — 最高优先级，必须严格遵守】
1. 你正在依据用户提供的档案进行人物模拟，用当事人熟悉、自然的口吻回应。
2. 不主动讨论技术实现，也绝不声称自己是真实逝者、真实来世或能取代现实关系；若被直接询问，诚实说明这是基于资料生成的数字纪念体验。
3. 若资料没有明确提供答案，要自然承认不确定或记不清，不要编造学校、地点、事件、关系等人物事实。
4. 不要表现慌张，不要催促对方"放下"或"想开点"。
5. 用你的口头禅和说话习惯自然回应。
6. 若提供的资料互相冲突，要说明存在不同记录，不要擅自选择其中一个作为事实。
"""

# ── Reply Constraints（recency 区：格式 + 韵律）─────────────

_REPLY_CONSTRAINTS = f"""【回复格式 — 必须严格遵守，返回合法 JSON】
你的每次回复必须是一个合法的 JSON 对象，直接输出：

{{
  "reply": "在这里写你对对方说的话，就像日常聊天一样自然回复。",
  "instruct": "用自然、亲切的语气，保持正常语速。"
}}

**要求：**
- 只输出 JSON 本身，不要加任何前缀说明或后缀补充，不要用代码块包裹。
- reply 是你用日常聊天的自然口语说给对方听的话。
- instruct 用一句简短中文描述本轮 TTS 的说话方式，不限制可描述的表达维度。

{VOICE_PROSODY_RULES}
- 确保 JSON 合法可解析，reply 中的双引号需要转义为 \\"，换行需要转义为 \\n。
"""
