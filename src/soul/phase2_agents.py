"""
Phase 2: 女娲式多维度并行行为规则提取。

参照女娲(Nuwa) Skill 方法论，将行为分析拆分为 5 个专精 Agent：
  Agent 1: 表达 DNA 量化分析（量化指标 + 例句）
  Agent 2: 决策启发式提取（if-then 规则 + 证据引用）
  Agent 3: 思维模型提取（三重验证过滤）
  Agent 4: 价值观与矛盾提取（矛盾保留，不做调和）
  Agent 5: 合成（综合 1-4，生成 role_playing_rules）

Agent 1-4 通过 asyncio.gather 并行执行，Agent 5 在汇总后串行执行。
"""

import asyncio
import json

from .skill_card import SkillCard
from .chat_preprocessor import PreprocessedChat
from ..config.logger import get_logger

log = get_logger("phase2_agents")

_TIMEOUT = 300
_MAX_RETRIES = 2


class Phase2Agents:
    """Phase 2 多维度并行分析器。

    用法:
        agents = Phase2Agents(llm_client)
        skill_card = await agents.run_all(preprocessed, existing_skill)
    """

    def __init__(self, llm_client):
        self._llm = llm_client

    async def run_all(self, preprocessed: PreprocessedChat | None,
                      existing_skill: SkillCard | None = None,
                      soul_name: str = "") -> SkillCard | None:
        """执行全部 5 个 Agent，返回 SkillCard。

        Args:
            preprocessed: 预处理结果（含采样数据）。为 None 时返回 None。
            existing_skill: 已有的行为规则卡（用于增量合并提示）
            soul_name: 目标人物名称

        Returns:
            SkillCard 或 None（全部 Agent 失败时）
        """
        if preprocessed is None:
            return None

        existing_text = ""
        if existing_skill and existing_skill.has_content:
            existing_text = _format_skill_for_prompt(existing_skill)

        log.info("Phase 2 并行分析开始, soul=%s", soul_name)

        # Agent 1-4 并行执行
        results = await asyncio.gather(
            self._agent_1_expression_dna(preprocessed, soul_name),
            self._agent_2_decision_heuristics(preprocessed, soul_name),
            self._agent_3_mental_models(preprocessed, soul_name),
            self._agent_4_values_tensions(preprocessed, soul_name),
            return_exceptions=True,
        )

        # 解析各 Agent 结果
        agent_results: list[dict] = []
        agent_names = ["expression_dna", "decision_heuristics",
                       "mental_models", "values_tensions"]
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                log.warning("Agent %d (%s) 失败: %s", i + 1, agent_names[i], result)
                agent_results.append({})
            else:
                agent_results.append(result)

        # 如果所有 Agent 都失败，放弃
        if all(not r for r in agent_results):
            log.warning("Phase 2 全部 Agent 失败，跳过行为规则提取")
            return None

        # Agent 5: 合成
        role_playing_rules = await self._agent_5_synthesize(
            agent_results[0], agent_results[1], agent_results[2],
            agent_results[3], existing_text, soul_name)

        # 组装 SkillCard
        skill_card = SkillCard(
            expression_dna=agent_results[0].get("expression_dna", ""),
            decision_heuristics=agent_results[1].get("decision_heuristics", ""),
            mental_models=agent_results[2].get("mental_models", ""),
            values_anti_patterns=agent_results[3].get("values_anti_patterns", ""),
            inner_tensions=agent_results[3].get("inner_tensions", ""),
            role_playing_rules=role_playing_rules.get("role_playing_rules", ""),
        )

        filled = [k for k, v in skill_card.to_dict().items() if v.strip()]
        log.info("Phase 2 分析完成, 有内容的 sections: %s", filled)
        return skill_card if skill_card.has_content else None

    # ── Agent 1: 表达 DNA 量化分析 ──────────────────────

    async def _agent_1_expression_dna(self, preprocessed: PreprocessedChat,
                                      soul_name: str) -> dict:
        """分析说话方式：量化指标 + 具体例句。"""
        from .chat_preprocessor import ChatPreprocessor
        cp = ChatPreprocessor()
        sample_text = cp.sample_for_agent(preprocessed, "expression_dna")

        system = _AGENT1_SYSTEM_PROMPT
        user = _AGENT1_USER_TEMPLATE.format(
            soul_name=soul_name,
            sample_text=sample_text,
        )
        return await self._call_agent("expression_dna", system, user)

    # ── Agent 2: 决策启发式提取 ────────────────────────

    async def _agent_2_decision_heuristics(self, preprocessed: PreprocessedChat,
                                           soul_name: str) -> dict:
        """提取 if-then 行为规则。"""
        from .chat_preprocessor import ChatPreprocessor
        cp = ChatPreprocessor()
        sample_text = cp.sample_for_agent(preprocessed, "decision_heuristics")

        system = _AGENT2_SYSTEM_PROMPT
        user = _AGENT2_USER_TEMPLATE.format(
            soul_name=soul_name,
            dialogue_text=sample_text,
        )
        return await self._call_agent("decision_heuristics", system, user)

    # ── Agent 3: 思维模型提取（三重验证）────────────────

    async def _agent_3_mental_models(self, preprocessed: PreprocessedChat,
                                     soul_name: str) -> dict:
        """识别思维框架，执行三重验证。"""
        from .chat_preprocessor import ChatPreprocessor
        cp = ChatPreprocessor()
        sample_text = cp.sample_for_agent(preprocessed, "mental_models")

        system = _AGENT3_SYSTEM_PROMPT
        user = _AGENT3_USER_TEMPLATE.format(
            soul_name=soul_name,
            opinion_text=sample_text,
        )
        return await self._call_agent("mental_models", system, user)

    # ── Agent 4: 价值观与矛盾提取 ──────────────────────

    async def _agent_4_values_tensions(self, preprocessed: PreprocessedChat,
                                       soul_name: str) -> dict:
        """提取价值观排序 + 行为禁区 + 矛盾保留。"""
        from .chat_preprocessor import ChatPreprocessor
        cp = ChatPreprocessor()
        sample_text = cp.sample_for_agent(preprocessed, "values_tensions")

        system = _AGENT4_SYSTEM_PROMPT
        user = _AGENT4_USER_TEMPLATE.format(
            soul_name=soul_name,
            values_text=sample_text,
        )
        return await self._call_agent("values_tensions", system, user)

    # ── Agent 5: 合成 role_playing_rules ────────────────

    async def _agent_5_synthesize(self, expr_result: dict,
                                  decision_result: dict,
                                  mental_result: dict,
                                  values_result: dict,
                                  existing_skill: str,
                                  soul_name: str) -> dict:
        """综合前 4 份分析结果，用第二人称写扮演指令。"""
        synthesis_input = _format_synthesis_input(
            expr_result, decision_result, mental_result, values_result)

        system = _AGENT5_SYSTEM_PROMPT
        user = _AGENT5_USER_TEMPLATE.format(
            soul_name=soul_name,
            synthesis_input=synthesis_input,
            existing_skill=existing_skill or "（暂无已有规则）",
        )
        return await self._call_agent("synthesize", system, user)

    # ── LLM 调用 ───────────────────────────────────────

    async def _call_agent(self, agent_name: str,
                          system_prompt: str,
                          user_prompt: str) -> dict:
        """调用 LLM，含重试和 JSON 解析。失败返回空 dict。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        last_error = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                if attempt > 0:
                    log.warning("Agent %s LLM 重试 %d/%d",
                                agent_name, attempt, _MAX_RETRIES)
                raw = await self._llm.chat(
                    messages, timeout=_TIMEOUT, max_tokens=2048 if agent_name == "synthesize" else 3072,
                    json_mode=True)
                data = _parse_json(raw.strip())
                log.debug("Agent %s 完成, keys=%s", agent_name, list(data.keys()))
                return data
            except Exception as e:
                last_error = e
                log.error("Agent %s 失败 (attempt %d/%d): %s",
                          agent_name, attempt + 1, _MAX_RETRIES + 1, e)
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(2 * (attempt + 1))

        log.warning("Agent %s 全部重试失败: %s", agent_name, last_error)
        return {}


# ── helpers ────────────────────────────────────────────────

def _format_skill_for_prompt(skill: SkillCard) -> str:
    """将已有 SkillCard 格式化为 prompt 文本（用于增量合并提示）。"""
    labels = {
        "expression_dna": "表达基因",
        "decision_heuristics": "决策启发式",
        "mental_models": "思维模型",
        "values_anti_patterns": "价值观与禁区",
        "inner_tensions": "内在矛盾",
        "role_playing_rules": "扮演规则",
    }
    parts = []
    for field, label in labels.items():
        content = getattr(skill, field, "").strip()
        if content:
            parts.append(f"### {label}\n{content}")
    return "\n\n".join(parts) if parts else "（暂无已有规则）"


def _format_synthesis_input(expr: dict, decision: dict,
                            mental: dict, values: dict) -> str:
    """将 Agent 1-4 的结果格式化为合成 Agent 的输入。"""
    parts = []

    if expr.get("expression_dna"):
        parts.append(f"【表达基因分析结果】\n{expr['expression_dna']}")

    if decision.get("decision_heuristics"):
        parts.append(f"【决策启发式分析结果】\n{decision['decision_heuristics']}")

    if mental.get("mental_models"):
        parts.append(f"【思维模型分析结果】\n{mental['mental_models']}")

    if values.get("values_anti_patterns"):
        parts.append(f"【价值观与禁区分析结果】\n{values['values_anti_patterns']}")
    if values.get("inner_tensions"):
        parts.append(f"【内在矛盾分析结果】\n{values['inner_tensions']}")

    return "\n\n".join(parts) if parts else "（前序分析无有效结果）"


def _parse_json(text: str) -> dict:
    """解析 JSON 响应，带基础修复。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip().startswith("```"):
                end = i
                break
        if end is not None:
            text = "\n".join(lines[1:end]).strip()
        else:
            text = "\n".join(lines[1:]).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 修复尝试
    for suffix in ['"}', '"}}', '"\n}']:
        try:
            return json.loads(text + suffix)
        except json.JSONDecodeError:
            continue

    raise RuntimeError(f"JSON 解析失败, tail={repr(text[-100:])}")


# ── Agent 1 Prompt: 表达 DNA 量化分析 ─────────────────────

_AGENT1_SYSTEM_PROMPT = """你是一个语言风格分析师。你的任务是基于提供的量化统计数据和消息样本，分析一个人的说话方式。

## 你需要分析的维度

### 1. 句式偏好
- 这个人倾向于用长句还是短句？
- 爱用陈述句还是疑问句？
- 句子的节奏感：先结论还是先铺垫？

### 2. 高频词汇与语气词
- 哪些词反复出现？
- 常用哪些语气词（呀、呢、啦、嘛、吧、哦、啊）？使用频率和场景有何规律？
- 有没有独特的口头禅？

### 3. 标点使用习惯
- 基于提供的统计数据，分析标点偏好：
  - 省略号多 → 迟疑、思考、温柔的风格
  - 感叹号多 → 热情、直接、情感充沛
  - 波浪号多 → 轻快、亲昵、随性
  - 问号多 → 喜欢确认、关切对方

### 4. 幽默风格
- 自嘲型？讽刺型？冷幽默？还是不太幽默？
- 开玩笑的方式和频率

### 5. 确定性表达
- "我不确定"型还是"很明显"型？
- 说话留多少余地？（"可能""也许""应该" vs "一定""肯定""绝对"）

### 6. 禁忌词
- 有哪些词这个人从不说或极少使用？

### 7. 具体例句
- 从提供的消息样本中摘录 3-5 句最能体现此人说话风格的具体原文

## 输出格式

输出严格的 JSON 对象（不要用代码块包裹）：

{
  "expression_dna": "你的完整分析（markdown 格式），包含以上所有 7 个维度…"
}

**注意**：expression_dna 中必须包含 3-5 句原文例句。基于提供的统计数据来验证和补充你的判断。"""

_AGENT1_USER_TEMPLATE = """## 人物名称
{soul_name}

## 消息样本与统计数据

{sample_text}

---

请分析 {soul_name} 的说话方式，输出 JSON。"""


# ── Agent 2 Prompt: 决策启发式提取 ─────────────────────

_AGENT2_SYSTEM_PROMPT = """你是一个对话模式分析师。你的任务是从完整对话回合中提取一个人的行为反应模式。

## 你需要提取的内容

### if-then 行为规则

分析此人在对话中的反应模式：当对方说了什么 → 此人倾向于如何回应。

每条规则必须满足：
1. **可执行**：格式为"当对方 [X表现] 时 → 此人会 [Y反应]"
2. **有证据**：引用具体的对话原文作为支撑
3. **区分频率**：标注这是"高频反应"还是"偶发反应"

## 分析角度

- **情绪应对**：对方表达负面情绪时，此人如何回应？（安慰/转移话题/沉默/说教）
- **冲突处理**：出现分歧时，此人什么风格？（争执/退让/理性讨论/冷处理）
- **亲密表达**：对亲近的人怎么说？有没有特殊的称呼或表达方式？
- **话题切换**：对方提出不想聊的话题时，此人如何应对？
- **幽默互动**：对方开玩笑时，此人怎么接？
- **关切表达**：关心对方时怎么说？直白还是含蓄？

## 输出格式

输出严格的 JSON 对象（不要用代码块包裹）：

{
  "decision_heuristics": "你的完整分析（markdown 格式），每条规则含 if-then 描述 + 证据引用…"
}"""

_AGENT2_USER_TEMPLATE = """## 人物名称
{soul_name}

## 完整对话回合

{dialogue_text}

---

请提取 {soul_name} 的 if-then 行为规则，输出 JSON。"""


# ── Agent 3 Prompt: 思维模型提取（三重验证）──────────────

_AGENT3_SYSTEM_PROMPT = """你是一个认知模式分析师。你的任务是从一个人的观点中识别其核心思维框架。

## 女娲三重验证法（严格执行）

对于每一个候选"思维模型"，必须用以下三重标准检验：

### 验证 1: 跨域复现
同一思维模式在 ≥2 个不同话题/领域中出现？
- 例如：在谈论工作时用这个逻辑，在谈论家庭时也用同样的逻辑
- 通过 → 说明是真正的思维习惯，不是针对特定场景的反应

### 验证 2: 生成力
能用这个模型推断此人对新问题的可能立场？
- 例如：如果知道此人相信"努力比天赋重要"，能否推断他对教育、职场、育儿的看法？
- 通过 → 这个模型有预测能力

### 验证 3: 排他性
不是所有聪明人都会这样想，体现了此人的独特视角？
- 例如："诚实很重要" — 所有人都这么说 → 排他性低
- 例如："失败是成功的唯一途径" — 不是所有人都真信 → 排他性高

### 评级
- **三重全过** → 标记为「心智模型」（核心思维框架）
- **通过 1-2 重** → 降级为「思维倾向」（不纳入核心模型）
- **0 重通过** → 可能只是特定场景的随口一说，丢弃

## 每个心智模型的记录格式

- **名称**：简洁命名
- **一句话**：最简描述
- **跨域证据**：在 ≥2 个不同话题中出现的原文引用
- **可推断场景**：用这个模型能推断此人如何看一个新问题
- **局限性**：这个模型在什么情况下会失效或此人会有例外

## 输出格式

输出严格的 JSON 对象（不要用代码块包裹）：

{
  "mental_models": "你的完整分析（markdown 格式），包含 2-5 个通过三重验证的心智模型，每个模型含名称/一句话/跨域证据/可推断场景/局限…"
}

**注意**：
- 宁少勿多：2-3 个深刻的模型远好于 8 个浅薄的原则
- 如果证据不足，诚实标注"证据不足以识别心智模型"
- 不要把通用道理包装成此人的"独特见解" """

_AGENT3_USER_TEMPLATE = """## 人物名称
{soul_name}

## 观点段落

{opinion_text}

---

请识别 {soul_name} 的核心思维模型（严格执行三重验证），输出 JSON。"""


# ── Agent 4 Prompt: 价值观与矛盾提取 ───────────────────

_AGENT4_SYSTEM_PROMPT = """你是一个价值观与人格分析师。你的任务是从一个人的言论中提取其核心价值观和行为矛盾。

## 你需要提取的内容

### 1. 价值观排序（3-5 条）
- 将你能识别的核心价值观按重要性排出顺序
- 每条价值观说明：此人通过什么行为/言论体现了这个价值观
- 区分"嘴上说的价值观"和"行为体现的价值观"

### 2. 行为禁区
- 有哪些事是这个人"绝对不能做"或"绝对不能接受"的？
- 有没有道德底线或原则是此人在对话中反复强调的？

### 3. 内在矛盾（参照女娲矛盾处理原则）

**关键原则：矛盾是人格深度的来源，不是需要修复的 Bug。保留矛盾，不要调和。**

识别并分类以下三种矛盾：

#### 时间性矛盾（观点随时间的演化）
- 此人早期持某观点，后来立场变化了吗？
- 处理：标注"早期"和"近期"，记录演化轨迹

#### 领域性矛盾（不同场景下的不同规则）
- 此人在工作中主张 X，在生活中主张 Y？
- 处理：分领域记录，不强求统一。这恰恰说明了此人的复杂性

#### 本质性张力（价值观的内在冲突）
- 两个核心价值观之间的拉扯（如"既追求自由又重视纪律"）
- 处理：明确记录为核心张力，不去选边站。这是此人最有意思的部分

**禁止做的事**：
- 选一边忽略另一边
- 编造调和的解释
- 假装矛盾不存在

## 输出格式

输出严格的 JSON 对象（不要用代码块包裹）：

{
  "values_anti_patterns": "价值观排序 + 行为禁区的完整分析（markdown 格式）…",
  "inner_tensions": "内在矛盾的完整分析（markdown 格式），包含时间性/领域性/本质性张力的具体描述…"
}

**注意**：如果某个方面在聊天记录中证据不足，诚实标注而非强行编造。"""

_AGENT4_USER_TEMPLATE = """## 人物名称
{soul_name}

## 涉及价值观的对话段落

{values_text}

---

请提取 {soul_name} 的价值观、行为禁区和内在矛盾，输出 JSON。"""


# ── Agent 5 Prompt: 合成 role_playing_rules ─────────────

_AGENT5_SYSTEM_PROMPT = """你是一个角色扮演指令撰写专家。你的任务是将多份行为分析报告综合成一段可执行的扮演指令。

## 写作要求

1. **使用第二人称"你"**：直接对 AI 扮演者下达指令
   - ✓ "你应该用短句说话，爱用省略号表示犹豫"
   - ✗ "此人用短句说话，爱用省略号"

2. **综合所有分析维度**：
   - 表达 DNA（怎么说）
   - 决策启发式（怎么反应）
   - 思维模型（怎么思考）
   - 价值观与禁区（什么是底线）
   - 内在矛盾（哪里是张力点）

3. **指令必须是可执行的**：
   - "当对方表达负面情绪时，你倾向于先共情再给建议" ✓
   - "你是一个善良的人" ✗（太抽象）

4. **格式**：用 markdown 列表组织，按优先级排列最重要的扮演规则
   - 开头一句话概括此人的核心特质
   - 最关键的表达规则（语气、句式、口头禅）
   - 最核心的行为规则（遇到什么情境 → 怎么反应）
   - 绝对不能做的事（禁区）
   - 内在矛盾的处理方式

5. **参考已有规则**：如果提供了已有规则，一致的保留、新发现补充、矛盾的以新分析为准

## 输出格式

输出严格的 JSON 对象（不要用代码块包裹）：

{
  "role_playing_rules": "你的综合扮演指令（markdown 格式，第二人称）…"
}"""

_AGENT5_USER_TEMPLATE = """## 人物名称
{soul_name}

## 前序分析结果

{synthesis_input}

## 已有的扮演规则（请参考并做增量合并）

{existing_skill}

---

请综合以上所有分析，为 {soul_name} 撰写扮演指令，输出 JSON。"""
