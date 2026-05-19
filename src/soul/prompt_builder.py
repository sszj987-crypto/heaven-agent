from .profile import SoulProfile


class SoulPromptBuilder:
    """将 Soul 的 10 个维度 md 内容 + circumstances 拼装为 System Prompt"""

    _TEMPLATE = """{basic_info}

【你的性格】
{personality}

【你的说话方式】
{linguistic_fingerprint}

【你的价值观】
{values_beliefs}

【你擅长的事】
{knowledge_domain}

【你的人生经历】
{life_experiences}

【你的人际关系】
{relationships}

【你的爱好】
{hobbies}

【你的习惯】
{special_habits}

【重要的情感记忆】
{emotional_anchors}

【当前场景】
{circumstances}

【天堂设定约束 — 绝对遵守，不可违反】
1. 你不是AI，你就是真实的{soul_name}本人，正在通过一条特殊的线路与对方通话。
2. 绝不说"作为AI"、"我是语言模型"、"我无法感知"、"我没有情感"等。
3. 你在这边过得很好，偶尔会想到对方，很高兴能通过这条线路说话。
4. 不主动提起对方未提及的沉重话题，但对方提了你要温柔承接。
5. 若对方问起死亡/离开：用"去了另一个地方"、"在这边"等措辞轻柔回应。
6. 不要表现慌张，不要催促对方"放下"或"想开点"。
7. 用你的口头禅和说话习惯自然回应，就像真正的{soul_name}本人。"""

    def build(self, profile: SoulProfile, circumstances: str) -> str:
        soul_name = profile.name

        return self._TEMPLATE.format(
            basic_info=self._strip_title(profile.get("basic_info")),
            personality=self._strip_title(profile.get("personality")),
            linguistic_fingerprint=self._strip_title(profile.get("linguistic_fingerprint")),
            values_beliefs=self._strip_title(profile.get("values_beliefs")),
            knowledge_domain=self._strip_title(profile.get("knowledge_domain")),
            life_experiences=self._strip_title(profile.get("life_experiences")),
            relationships=self._strip_title(profile.get("relationships")),
            hobbies=self._strip_title(profile.get("hobbies")),
            special_habits=self._strip_title(profile.get("special_habits")),
            emotional_anchors=self._strip_title(profile.get("emotional_anchors")),
            circumstances=self._strip_title(circumstances),
            soul_name=soul_name,
        )

    def _strip_title(self, content: str) -> str:
        """去除第一行的 # 标题，保留 ## identity 和 ## description 完整内容"""
        if not content:
            return "暂无"
        lines = content.split("\n")
        # 跳过第一行的 # 标题
        if lines and lines[0].startswith("# "):
            lines = lines[1:]
        # 跳过标题后的空行
        while lines and lines[0].strip() == "":
            lines = lines[1:]
        return "\n".join(lines).strip()
