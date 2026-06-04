"""Skill Card（行为规则卡）— 从聊天记录中蒸馏出的动态扮演规则。

参考 女娲(Nuwa) Skill 方法论：
- 不描述"他是谁"，而是定义"如何扮演他"
- 每个 section 都是可执行的指令，不是档案描述
"""

from dataclasses import dataclass, field, asdict


@dataclass
class SkillCard:
    """动态行为规则卡。存储位置: config/souls/{name}/skill.md"""

    # ── 表达 DNA：让 AI 说得像这个人 ──
    expression_dna: str = ""
    # 具体内容：句式偏好（短句/长句）、高频词汇、语气词、幽默风格（自嘲/讽刺/冷幽默）、
    #          确定性表达习惯（"我不确定"型 vs "很明显"型）、禁忌词（从不用的词）

    # ── 决策启发式：if-then 行为规则 ──
    decision_heuristics: str = ""
    # 具体内容：当对方说 X 时→回应 Y；在 Z 场景下→倾向于做 W。
    #          每条规则有聊天记录证据支撑。

    # ── 思维模型：这个人怎么看世界 ──
    mental_models: str = ""
    # 具体内容：反复出现的思考框架、解释问题的方式、独特的归因逻辑。

    # ── 价值观与禁区 ──
    values_anti_patterns: str = ""
    # 具体内容：核心价值观排序、绝不接受的行为、内心真正的底线。

    # ── 内在矛盾 ──
    inner_tensions: str = ""
    # 具体内容：价值观之间的冲突、言行不一致的模式。
    #          矛盾是真实感的来源，不强求调和。

    # ── 综合扮演指令 ──
    role_playing_rules: str = ""
    # 具体内容：所有以上信息的综合应用——AI 拿到这张卡后应该如何扮演此人。
    #          用第二人称"你"写，直接把指令下达给扮演者。

    @property
    def has_content(self) -> bool:
        """是否有任何 section 有内容"""
        return any([
            self.expression_dna.strip(),
            self.decision_heuristics.strip(),
            self.mental_models.strip(),
            self.values_anti_patterns.strip(),
            self.inner_tensions.strip(),
            self.role_playing_rules.strip(),
        ])

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "SkillCard":
        fields = {"expression_dna", "decision_heuristics", "mental_models",
                  "values_anti_patterns", "inner_tensions", "role_playing_rules"}
        return cls(**{k: data.get(k, "") for k in fields})


# Skill card markdown section headers（用于读写 skill.md）
SECTION_HEADERS: dict[str, str] = {
    "role_playing_rules": "扮演规则",
    "expression_dna": "表达基因",
    "decision_heuristics": "决策启发式",
    "mental_models": "思维模型",
    "values_anti_patterns": "价值观与禁区",
    "inner_tensions": "内在矛盾",
}
