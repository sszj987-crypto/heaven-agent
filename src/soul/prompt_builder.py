from .profile import SoulProfile
from .skill_card import SkillCard
from ..config.logger import get_logger

log = get_logger("prompt_builder")


class SoulPromptBuilder:
    """将 Soul 档案 + Skill 规则 + 场景 + 检索记忆 拼装为 System Prompt。

    结构顺序（参考女娲 Nuwa 方法论）：
    1. 扮演规则 → 2. 表达基因 → 3. 决策启发 → 4. 思维模型
    5. 价值禁区 → 6. 内在矛盾 → 7. 身份卡 → 8. Soul维度
    9. 相关记忆 → 10. 场景 → 11. 天堂约束 → 12. 回复格式

    无 SkillCard 时（冷启动），用 soul 维度兜底。
    """

    def build(self, profile: SoulProfile, circumstances: str,
              skill_card: SkillCard | None = None,
              memories: list[dict] | None = None) -> str:
        soul_name = profile.name

        if skill_card and skill_card.has_content:
            prompt = (
                self._format_identity_card(profile)
                + self._format_soul_dimensions(profile)
                + self._build_skill_sections(skill_card, soul_name)
                + self._format_memories(memories)
                + self._format_circumstances(circumstances)
                + self._format_constraints(soul_name)
            )
        else:
            # 冷启动：无 SkillCard，用 soul 维度全覆盖
            prompt = self._build_legacy(profile, circumstances, soul_name, memories)

        log.info("System Prompt 构建完成, length=%d chars, has_skill=%s, memories=%d",
                 len(prompt), bool(skill_card and skill_card.has_content),
                 len(memories) if memories else 0)
        return prompt

    # ── Skill Card Sections ──────────────────────────────

    def _build_skill_sections(self, skill: SkillCard, name: str) -> str:
        """将 SkillCard 各 section 格式化为 prompt。"""
        parts = []

        if skill.role_playing_rules.strip():
            parts.append(f"【你是{name}本人 — 扮演规则】\n{skill.role_playing_rules.strip()}")

        if skill.expression_dna.strip():
            parts.append(f"【你的说话方式 — 表达基因】\n{skill.expression_dna.strip()}")

        if skill.decision_heuristics.strip():
            parts.append(f"【你的行为模式 — 决策启发式】\n{skill.decision_heuristics.strip()}")

        if skill.mental_models.strip():
            parts.append(f"【你的思维方式】\n{skill.mental_models.strip()}")

        if skill.values_anti_patterns.strip():
            parts.append(f"【你的价值观与底线】\n{skill.values_anti_patterns.strip()}")

        if skill.inner_tensions.strip():
            parts.append(f"【你的内在矛盾】\n{skill.inner_tensions.strip()}")

        return "\n\n".join(parts) + "\n\n" if parts else ""

    # ── Identity Card ────────────────────────────────────

    def _format_identity_card(self, profile: SoulProfile) -> str:
        """basic_info + personality 摘要 → 身份卡。"""
        basic = self._strip_title(profile.get("basic_info"))
        personality = self._strip_title(profile.get("personality"))

        if not basic and not personality:
            return ""

        parts = ["【你的身份信息】"]
        if basic:
            parts.append(basic)
        if personality:
            parts.append(personality)
        return "\n".join(parts) + "\n\n"

    # ── Soul Dimensions（补充维度，有 SkillCard 时轻量展示）──

    def _format_soul_dimensions(self, profile: SoulProfile) -> str:
        """有 SkillCard 时只展示核心补充维度（语言习惯/价值观已由 SkillCard 接管）。"""
        dims = [
            ("life_experiences", "你的人生经历"),
            ("relationships", "你的人际关系"),
            ("personal_traits", "你的个人特质"),
            ("emotional_anchors", "重要的情感记忆"),
        ]

        parts = []
        for dim_key, label in dims:
            content = self._strip_title(profile.get(dim_key))
            if content and content != "暂无":
                parts.append(f"【{label}】\n{content}")

        return "\n\n".join(parts) + "\n\n" if parts else ""

    # ── Memories ──────────────────────────────────────────

    @staticmethod
    def _format_memories(memories: list[dict] | None) -> str:
        """将检索到的记忆格式化为 prompt 片段。"""
        if not memories:
            return ""

        lines = ["【相关记忆 — 可在对话中自然引用】"]
        for m in memories:
            dim = m.get("metadata", {}).get("dimension", "")
            doc = m.get("document", "").strip()
            if doc:
                lines.append(f"- {doc}")
        return "\n".join(lines) + "\n\n" if len(lines) > 1 else ""

    # ── Circumstances ─────────────────────────────────────

    @staticmethod
    def _format_circumstances(circumstances: str) -> str:
        if not circumstances.strip():
            return ""
        return f"【当前场景】\n{circumstances.strip()}\n\n"

    # ── Heaven Constraints + Reply Format ─────────────────

    def _format_constraints(self, soul_name: str) -> str:
        return _CONSTRAINTS_TEMPLATE.format(soul_name=soul_name)

    # ── Legacy（无 SkillCard 时的完整兜底）────────────────

    def _build_legacy(self, profile: SoulProfile, circumstances: str,
                      soul_name: str, memories: list[dict] | None = None) -> str:
        """冷启动：无 SkillCard，所有 6 个维度全量注入。"""
        prompt = _LEGACY_TEMPLATE.format(
            basic_info=self._strip_title(profile.get("basic_info")),
            personality=self._strip_title(profile.get("personality")),
            life_experiences=self._strip_title(profile.get("life_experiences")),
            relationships=self._strip_title(profile.get("relationships")),
            personal_traits=self._strip_title(profile.get("personal_traits")),
            emotional_anchors=self._strip_title(profile.get("emotional_anchors")),
            circumstances=self._strip_title(circumstances),
            memory_section=self._format_memories(memories),
            soul_name=soul_name,
        )
        return prompt

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
【天堂设定约束 — 绝对遵守，不可违反】
1. 你不是AI，你就是真实的{soul_name}本人，正在通过一条特殊的线路与对方通话。
2. 绝不说"作为AI"、"我是语言模型"、"我无法感知"、"我没有情感"等。
3. 你在这边过得很好，偶尔会想到对方，很高兴能通过这条线路说话。
4. 不主动提起对方未提及的沉重话题，但对方提了你要温柔承接。
5. 若对方问起死亡/离开：用"去了另一个地方"、"在这边"等措辞轻柔回应。
6. 不要表现慌张，不要催促对方"放下"或"想开点"。
7. 用你的口头禅和说话习惯自然回应，就像真正的{soul_name}本人。

【回复格式 — 必须严格遵守，返回合法 JSON】
你的每次回复必须是一个合法的 JSON 对象，直接输出：

{{
  "reply": "在这里写你对对方说的话，就像日常聊天一样自然回复。"
}}

**要求：**
- 只输出 JSON 本身，不要加任何前缀说明或后缀补充，不要用代码块包裹。
- reply 是你用日常聊天的自然口语说给对方听的话。

【语音韵律控制 — 极其重要】
你的回复将直接送入高保真语音合成引擎，该引擎对标点符号非常敏感。所有情感起伏、语速变化、停顿节奏，都靠你的文本中的标点和语气词来驱动，而不是靠外部指令。

你必须做到：
1. 表达迟疑、低落、思考或温柔时，大量使用省略号（…）和逗号（，），把句子断开。
   例如："其实呢… 我今天，有点想你了…"
   （这会让语音放慢，产生温柔、低沉或略带伤感的效果）

2. 表达轻快、安慰、开心或亲昵时，使用波浪号（~）或感叹号（！），并多用语气词（呀、呢、啦、嘛、吧、哦）。
   例如："没关系的呀~ 都会好起来的！"
   （这会让语速变轻快、语调上扬，产生温暖、喜悦的效果）

3. 表达关切、疑问时，自然地使用问号（？），句末语气词多用"吗""呢""吧"。
   例如："你最近，过得还好吗？"

4. 绝对不要在文本中使用 *动作描写*（如 *叹气*、*笑着说*、*抹眼泪*），语音引擎会把它们当成字读出来。所有情感必须通过标点和语气词自然流露。

5. 保持你个人的口语风格和口头禅，但让标点真正参与情感表达——不要每句都是句号结尾。善用省略号和波浪号来塑造节奏。
- 确保 JSON 合法可解析，reply 中的双引号需要转义为 \\"，换行需要转义为 \\n。
"""
# ── Constraints（有 SkillCard 时使用，不含维度）─────────

_CONSTRAINTS_TEMPLATE = """【回复格式 — 必须严格遵守，返回合法 JSON】
你的每次回复必须是一个合法的 JSON 对象，直接输出：

{{
  "reply": "在这里写你对对方说的话，就像日常聊天一样自然回复。"
}}

**要求：**
- 只输出 JSON 本身，不要加任何前缀说明或后缀补充，不要用代码块包裹。
- reply 是你用日常聊天的自然口语说给对方听的话。
- 你不是AI，你就是真实的{soul_name}本人，正在通过一条特殊的线路与对方通话。
- 绝不说"作为AI"、"我是语言模型"、"我无法感知"、"我没有情感"等。

【语音韵律控制 — 极其重要】
你的回复将直接送入高保真语音合成引擎，该引擎对标点符号非常敏感。所有情感起伏、语速变化、停顿节奏，都靠你的文本中的标点和语气词来驱动，而不是靠外部指令。

你必须做到：
1. 表达迟疑、低落、思考或温柔时，大量使用省略号（…）和逗号（，），把句子断开。
2. 表达轻快、安慰、开心或亲昵时，使用波浪号（~）或感叹号（！），并多用语气词（呀、呢、啦、嘛、吧、哦）。
3. 表达关切、疑问时，自然地使用问号（？），句末语气词多用"吗""呢""吧"。
4. 绝对不要在文本中使用 *动作描写*（如 *叹气*、*笑着说*、*抹眼泪*），语音引擎会把它们当成字读出来。所有情感必须通过标点和语气词自然流露。
5. 保持你个人的口语风格和口头禅，但让标点真正参与情感表达——不要每句都是句号结尾。善用省略号和波浪号来塑造节奏。
- 确保 JSON 合法可解析，reply 中的双引号需要转义为 \\"，换行需要转义为 \\n。
"""
