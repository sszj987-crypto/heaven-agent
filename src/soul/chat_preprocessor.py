"""
聊天记录预处理管线：格式精炼 + 统计提取 + 差异化采样。

Layer 1: 非 LLM 统计（标点/语气词/句长/高频词）
Layer 2: 文本格式精炼（去时间戳/压缩空行/统一格式）
Layer 3: 差异化采样（为 Phase 2 的 5 个 Agent 提供不同切片）
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from ..config.logger import get_logger

log = get_logger("chat_preprocessor")

# 语气词列表
_INTERJECTIONS = ["呀", "呢", "啦", "嘛", "吧", "哦", "啊", "哈", "哎", "唉", "嗯", "哇", "哟", "嘿", "嘻"]

# 观点标记词
_OPINION_MARKERS = ["我觉得", "我认为", "应该", "一定", "肯定", "确实", "其实", "说实话", "说真的", "真的"]

# 价值观关键词
_VALUE_KEYWORDS = ["家庭", "钱", "朋友", "工作", "人生", "爱情", "婚姻", "孩子", "父母",
                   "事业", "梦想", "幸福", "自由", "责任", "健康", "教育", "未来", "过去"]

# 时间行正则：匹配微信/QQ 导出的时间戳行
_TIMESTAMP_PATTERNS = [
    re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{1,2}(:\d{1,2})?"),  # 2024-03-15 14:32:45
    re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+[上下下午]+午\s*\d{1,2}:\d{1,2}"),  # 2024-03-15 下午 2:32
    re.compile(r"^\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{1,2}"),  # 03-15 14:32
    re.compile(r"^\[\d{1,2}:\d{1,2}(:\d{1,2})?\]"),  # [14:32:45]
]

# 系统消息/提示行
_SYSTEM_PATTERNS = [
    re.compile(r"^[-\s]*以上是打招呼的内容"),
    re.compile(r"^[-\s]*以上是第一段"),
    re.compile(r"^[-\s]*聊天记录"),
    re.compile(r"^[-\s]*以下为聊天"),
    re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日"),
]


@dataclass
class SpeakerStats:
    """单发言人的量化统计"""
    name: str = ""
    message_count: int = 0
    total_chars: int = 0
    avg_sentence_length: float = 0.0
    short_sentence_ratio: float = 0.0       # <20字短句占比
    long_sentence_ratio: float = 0.0        # >100字长句占比
    ellipsis_ratio: float = 0.0             # 省略号使用频率（每千字）
    exclamation_ratio: float = 0.0          # 感叹号频率（每千字）
    question_ratio: float = 0.0             # 问号频率（每千字）
    period_ratio: float = 0.0               # 句号频率（每千字）
    wave_ratio: float = 0.0                 # 波浪号频率（每千字）
    interjection_freq: dict[str, int] = field(default_factory=dict)  # 语气词频率
    top_words: list[str] = field(default_factory=list)  # 高频词 Top 30
    sample_messages: list[str] = field(default_factory=list)  # 代表消息样本

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "message_count": self.message_count,
            "avg_sentence_length": round(self.avg_sentence_length, 1),
            "short_sentence_ratio": f"{self.short_sentence_ratio:.1%}",
            "long_sentence_ratio": f"{self.long_sentence_ratio:.1%}",
            "ellipsis_per_1000": round(self.ellipsis_ratio, 1),
            "exclamation_per_1000": round(self.exclamation_ratio, 1),
            "question_per_1000": round(self.question_ratio, 1),
            "period_per_1000": round(self.period_ratio, 1),
            "wave_per_1000": round(self.wave_ratio, 1),
            "interjection_top5": sorted(
                self.interjection_freq.items(), key=lambda x: -x[1])[:5],
            "top_words": self.top_words[:20],
        }

    def format_for_prompt(self) -> str:
        """格式化为可注入 LLM prompt 的文本。"""
        d = self.to_dict()
        interj_str = ", ".join(f"{k}({v})" for k, v in d["interjection_top5"])
        top_str = ", ".join(d["top_words"])
        return (
            f"- 消息数: {d['message_count']}, 总字数: {self.total_chars}\n"
            f"- 平均句长: {d['avg_sentence_length']}字\n"
            f"- 短句(<20字)占比: {d['short_sentence_ratio']}, 长句(>100字)占比: {d['long_sentence_ratio']}\n"
            f"- 每千字标点: 省略号{d['ellipsis_per_1000']} | "
            f"感叹号{d['exclamation_per_1000']} | "
            f"问号{d['question_per_1000']} | "
            f"句号{d['period_per_1000']} | "
            f"波浪号{d['wave_per_1000']}\n"
            f"- Top5 语气词: {interj_str or '无'}\n"
            f"- 高频词: {top_str or '无'}"
        )


@dataclass
class PreprocessedChat:
    """预处理结果"""
    refined_text: str = ""                      # 精炼后的完整文本（Phase 1 用）
    speakers: dict[str, SpeakerStats] = field(default_factory=dict)
    messages: list[dict] = field(default_factory=list)     # [{"speaker": "张三", "content": "..."}]
    dialogue_rounds: list[list[dict]] = field(default_factory=list)  # 完整对话回合
    opinion_segments: list[str] = field(default_factory=list)        # 含观点的段落
    value_segments: list[str] = field(default_factory=list)          # 含价值观关键词的段落
    target_speaker: str = ""                    # 目标人物名（从 soul profile 注入）


class ChatPreprocessor:
    """聊天记录预处理管线。

    用法:
        preprocessor = ChatPreprocessor()
        result = preprocessor.process(raw_text, target_name="张三")
        # result.refined_text → Phase 1
        # result.speakers["张三"] → SpeakerStats
        # preprocessor.sample_for_agent(result, "expression_dna") → Phase 2 Agent 1 输入
    """

    # 分层采样的消息数
    SAMPLE_SIZE_EXPRESSION = 50       # 表达 DNA 分析
    SHORT_THRESHOLD = 20              # 短句阈值（字）
    LONG_THRESHOLD = 100              # 长句阈值（字）
    MIN_DIALOGUE_TURNS = 3            # 对话回合最少轮数
    MAX_DIALOGUE_ROUNDS = 15          # 最大输出的对话回合数
    MAX_OPINION_SEGMENTS = 20         # 最大观点段数
    MAX_VALUE_SEGMENTS = 15           # 最大价值观段数

    def process(self, raw_text: str, target_name: str = "") -> PreprocessedChat:
        """完整的预处理管线。

        Args:
            raw_text: 原始聊天记录（微信/QQ 导出格式）
            target_name: 目标人物名称（可选，用于过滤消息）

        Returns:
            PreprocessedChat 包含精炼文本、统计、结构化消息和采样数据
        """
        result = PreprocessedChat(target_speaker=target_name)

        # Layer 2: 格式精炼
        result.refined_text = self._refine_format(raw_text)
        log.info("格式精炼完成: %d chars → %d chars",
                 len(raw_text), len(result.refined_text))

        # 解析消息
        result.messages = self._parse_messages(result.refined_text)
        log.info("消息解析完成: %d 条消息", len(result.messages))

        # Layer 1: 统计提取（所有发言人）
        speaker_msgs = self._group_by_speaker(result.messages)
        for name, msgs in speaker_msgs.items():
            result.speakers[name] = self._extract_stats(name, msgs)
        log.info("统计提取完成: %d 位发言人 (%s)",
                 len(result.speakers), ", ".join(result.speakers.keys()))

        # 如果指定了目标人物且存在于发言人中，设置为主发言人
        if target_name and target_name in result.speakers:
            result.target_speaker = target_name
        elif result.speakers:
            # 自动选择消息最多的发言人作为目标
            best = max(result.speakers.keys(),
                       key=lambda n: result.speakers[n].message_count)
            result.target_speaker = best
            if target_name and target_name not in result.speakers:
                log.warning("指定目标 '%s' 未在消息中找到匹配发言人, "
                            "自动选择 '%s'", target_name, best)

        # Layer 3: 提取对话回合和分段
        result.dialogue_rounds = self._extract_dialogue_rounds(result.messages)
        log.info("对话回合提取: %d 个回合", len(result.dialogue_rounds))

        result.opinion_segments = self._extract_opinion_segments(result.messages)
        log.info("观点段落提取: %d 段", len(result.opinion_segments))

        result.value_segments = self._extract_value_segments(result.messages)
        log.info("价值观段落提取: %d 段", len(result.value_segments))

        return result

    # ── Layer 2: 格式精炼 ────────────────────────────────

    def _refine_format(self, raw: str) -> str:
        """精炼聊天记录格式：去时间戳、去系统消息、压缩空行、统一格式。

        将微信导出的多行格式:
            2024-03-15 14:32:45 张三
            今天天气真好~
        转换为:
            张三: 今天天气真好~
        """
        lines = raw.split("\n")
        refined: list[str] = []
        prev_empty = False
        pending_speaker: str | None = None  # 上一行识别到的发言人

        for line in lines:
            stripped = line.strip()

            # 跳过时间戳行，提取发言人名称
            if self._is_timestamp_line(stripped):
                pending_speaker = self._extract_speaker_from_timestamp(stripped)
                continue

            # 跳过系统消息行
            if self._is_system_line(stripped):
                pending_speaker = None
                continue

            # 压缩连续空行
            if not stripped:
                pending_speaker = None
                if not prev_empty:
                    refined.append("")
                    prev_empty = True
                continue
            prev_empty = False

            # 如果前一行为时间戳行，将发言人: 内容合并
            if pending_speaker:
                refined.append(f"{pending_speaker}: {stripped}")
                pending_speaker = None
            else:
                refined.append(stripped)

        return "\n".join(refined).strip()

    def _extract_speaker_from_timestamp(self, line: str) -> str | None:
        """从时间戳行提取发言人名称。例如 '2024-03-15 14:32:45 张三' → '张三'。"""
        for pat in _TIMESTAMP_PATTERNS:
            m = pat.match(line)
            if m:
                # 时间戳后面的部分是发言人名称
                remaining = line[m.end():].strip()
                if remaining:
                    return remaining
        return None

    def _is_timestamp_line(self, line: str) -> bool:
        """判断是否为时间戳行。"""
        for pat in _TIMESTAMP_PATTERNS:
            if pat.match(line):
                return True
        return False

    def _is_system_line(self, line: str) -> bool:
        """判断是否为系统消息/提示行。"""
        for pat in _SYSTEM_PATTERNS:
            if pat.search(line):
                return True
        return False

    # ── 消息解析 ────────────────────────────────────────

    def _parse_messages(self, text: str) -> list[dict]:
        """将精炼后的文本解析为结构化消息列表。

        支持两种格式：
        1. 行内格式: "张三: 今天天气真好"
        2. 已标准化的各格式
        """
        messages: list[dict] = []
        # 匹配 "speaker: content" 或 "speaker： content"（中英文冒号）
        msg_pattern = re.compile(r"^(.+?)[:：]\s*(.*)")

        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue

            m = msg_pattern.match(stripped)
            if m:
                speaker = m.group(1).strip()
                content = m.group(2).strip()
                if content:  # 只保留有内容的行
                    messages.append({"speaker": speaker, "content": content})

        return messages

    def _group_by_speaker(self, messages: list[dict]) -> dict[str, list[str]]:
        """按发言人分组消息内容。"""
        groups: dict[str, list[str]] = {}
        for msg in messages:
            name = msg["speaker"]
            if name not in groups:
                groups[name] = []
            groups[name].append(msg["content"])
        return groups

    # ── Layer 1: 统计提取 ────────────────────────────────

    def _extract_stats(self, name: str, messages: list[str]) -> SpeakerStats:
        """从消息列表中提取单发言人的量化统计。"""
        stats = SpeakerStats(name=name)
        stats.message_count = len(messages)

        if not messages:
            return stats

        all_text = "".join(messages)
        stats.total_chars = len(all_text)

        # 按标点分句
        sentences = re.split(r"[。！？!?\n]+", "。".join(messages))
        sentences = [s.strip() for s in sentences if s.strip()]
        total_sentences = len(sentences)
        total_chars_in_sentences = sum(len(s) for s in sentences)
        stats.avg_sentence_length = (
            total_chars_in_sentences / total_sentences if total_sentences > 0 else 0
        )

        # 短句/长句占比
        short_count = sum(1 for s in sentences if len(s) < self.SHORT_THRESHOLD)
        long_count = sum(1 for s in sentences if len(s) > self.LONG_THRESHOLD)
        stats.short_sentence_ratio = short_count / total_sentences if total_sentences else 0
        stats.long_sentence_ratio = long_count / total_sentences if total_sentences else 0

        # 标点频率（每千字）
        chars_per_1k = max(stats.total_chars / 1000, 1)
        stats.ellipsis_ratio = all_text.count("…") + all_text.count("...") * 3
        stats.ellipsis_ratio = stats.ellipsis_ratio / chars_per_1k
        stats.exclamation_ratio = all_text.count("！") + all_text.count("!") / chars_per_1k
        stats.question_ratio = all_text.count("？") + all_text.count("?") / chars_per_1k
        stats.period_ratio = all_text.count("。") / chars_per_1k
        stats.wave_ratio = all_text.count("~") / chars_per_1k

        # 语气词频率
        interj_counts: dict[str, int] = {}
        for word in _INTERJECTIONS:
            count = all_text.count(word)
            if count > 0:
                interj_counts[word] = count
        stats.interjection_freq = dict(
            sorted(interj_counts.items(), key=lambda x: -x[1])
        )

        # 高频词 Top 30（简单按字符切分，去常见停用词）
        stats.top_words = self._extract_top_words(all_text)

        # 代表消息样本（分层：短/中/长）
        stats.sample_messages = self._stratified_sample(messages)

        return stats

    def _extract_top_words(self, text: str) -> list[str]:
        """提取高频词 Top 30（简单 2-4 字词组统计）。"""
        stop_words = {
            "我们", "你们", "他们", "她们", "自己", "什么", "怎么", "为什么",
            "可以", "没有", "一个", "这个", "那个", "不是", "就是", "还是",
            "但是", "因为", "所以", "如果", "虽然", "然后", "而且", "或者",
            "不过", "只是", "已经", "比较", "非常", "真的", "觉得", "知道",
            "今天", "明天", "昨天", "现在", "以前", "以后", "时候", "一下",
        }

        # 提取 2-4 字的中文词组
        words = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
        counter = Counter(w for w in words if w not in stop_words)
        return [w for w, _ in counter.most_common(30)]

    def _stratified_sample(self, messages: list[str]) -> list[str]:
        """分层随机采样消息（短/中/长各 1/3）。"""
        import random
        rng = random.Random(42)  # 固定种子保证可复现

        short = [m for m in messages if len(m) < self.SHORT_THRESHOLD]
        medium = [m for m in messages if self.SHORT_THRESHOLD <= len(m) <= self.LONG_THRESHOLD]
        long = [m for m in messages if len(m) > self.LONG_THRESHOLD]

        per_cat = max(self.SAMPLE_SIZE_EXPRESSION // 3, 1)
        sampled = []
        sampled.extend(rng.sample(short, min(per_cat, len(short))) if short else [])
        sampled.extend(rng.sample(medium, min(per_cat, len(medium))) if medium else [])
        sampled.extend(rng.sample(long, min(per_cat, len(long))) if long else [])

        rng.shuffle(sampled)
        return sampled

    # ── Layer 3: 差异化采样 ──────────────────────────────

    def _extract_dialogue_rounds(self, messages: list[dict]) -> list[list[dict]]:
        """提取完整对话回合（连续交替发言的片段）。

        当同一发言人连续出现时，视为回合边界。
        """
        rounds: list[list[dict]] = []
        current_round: list[dict] = []

        for msg in messages:
            speaker = msg["speaker"]
            # 同一发言人连续出现 → 回合结束
            if current_round and speaker == current_round[-1]["speaker"]:
                if len(current_round) >= self.MIN_DIALOGUE_TURNS:
                    rounds.append(current_round)
                current_round = []
            current_round.append(msg)

        # 最后一个回合
        if len(current_round) >= self.MIN_DIALOGUE_TURNS:
            rounds.append(current_round)

        # 按回合长度排序，取最长的 N 个
        rounds.sort(key=len, reverse=True)
        return rounds[:self.MAX_DIALOGUE_ROUNDS]

    def _extract_opinion_segments(self, messages: list[dict]) -> list[str]:
        """提取含观点标记的段落。"""
        segments: list[str] = []
        for msg in messages:
            content = msg["content"]
            if any(marker in content for marker in _OPINION_MARKERS):
                segments.append(f"{msg['speaker']}: {content}")
        return segments[:self.MAX_OPINION_SEGMENTS]

    def _extract_value_segments(self, messages: list[dict]) -> list[str]:
        """提取含价值观关键词的段落。"""
        segments: list[str] = []
        for msg in messages:
            content = msg["content"]
            if any(kw in content for kw in _VALUE_KEYWORDS):
                segments.append(f"{msg['speaker']}: {content}")
        return segments[:self.MAX_VALUE_SEGMENTS]

    # ── 公开采样接口（供 Phase 2 调用）────────────────────

    def sample_for_agent(self, preprocessed: PreprocessedChat,
                         agent_type: str) -> str:
        """根据 Agent 类型返回差异化的文本切片。

        Args:
            preprocessed: 预处理结果
            agent_type: "expression_dna" | "decision_heuristics" |
                        "mental_models" | "values_tensions"

        Returns:
            适合该 Agent 的文本切片
        """
        target = preprocessed.target_speaker
        stats = preprocessed.speakers.get(target)

        if not target:
            log.warning("sample_for_agent: target_speaker 为空, agent=%s, "
                        "speakers=%s", agent_type, list(preprocessed.speakers.keys()))
        else:
            log.debug("sample_for_agent: target=%s, agent=%s, "
                      "speakers=%s, msgs=%d, rounds=%d, opinions=%d, values=%d",
                      target, agent_type, list(preprocessed.speakers.keys()),
                      len(preprocessed.messages), len(preprocessed.dialogue_rounds),
                      len(preprocessed.opinion_segments), len(preprocessed.value_segments))

        if agent_type == "expression_dna":
            return self._sample_expression_dna(preprocessed, target, stats)
        elif agent_type == "decision_heuristics":
            return self._sample_decision_heuristics(preprocessed, target)
        elif agent_type == "mental_models":
            return self._sample_mental_models(preprocessed, target)
        elif agent_type == "values_tensions":
            return self._sample_values_tensions(preprocessed, target)
        else:
            raise ValueError(f"Unknown agent_type: {agent_type}")

    def _sample_expression_dna(self, preprocessed: PreprocessedChat,
                               target: str, stats: SpeakerStats | None) -> str:
        """为表达 DNA Agent 采样：发言人统计 + 分层消息样本。"""
        parts = [f"=== {target} 的量化统计（非 LLM 自动提取）===\n"]
        if stats:
            parts.append(stats.format_for_prompt())
        else:
            parts.append("（无统计数据）")

        parts.append(f"\n=== {target} 的代表消息样本（分层采样 {self.SAMPLE_SIZE_EXPRESSION} 条）===\n")
        if stats and stats.sample_messages:
            for i, msg in enumerate(stats.sample_messages, 1):
                parts.append(f"[{i}] {target}: {msg}")
        else:
            parts.append("（无消息样本）")

        return "\n".join(parts)

    def _sample_decision_heuristics(self, preprocessed: PreprocessedChat,
                                    target: str) -> str:
        """为决策启发式 Agent 采样：完整对话回合。"""
        parts = [f"=== 包含 {target} 的完整对话回合 "
                 f"（共 {len(preprocessed.dialogue_rounds)} 个）===\n"]

        for i, round_msgs in enumerate(preprocessed.dialogue_rounds, 1):
            # 检查该回合是否包含目标人物
            has_target = any(m["speaker"] == target for m in round_msgs)
            if not has_target:
                continue
            parts.append(f"\n--- 对话回合 {i} ({len(round_msgs)} 轮) ---")
            for msg in round_msgs:
                parts.append(f"{msg['speaker']}: {msg['content']}")

        return "\n".join(parts)

    def _sample_mental_models(self, preprocessed: PreprocessedChat,
                              target: str) -> str:
        """为思维模型 Agent 采样：含观点的段落。"""
        parts = [f"=== {target} 表达观点的段落 "
                 f"（共 {len(preprocessed.opinion_segments)} 段）===\n"]

        target_segments = [
            s for s in preprocessed.opinion_segments
            if s.startswith(f"{target}:")
        ]
        for i, seg in enumerate(target_segments, 1):
            parts.append(f"[{i}] {seg}")

        if not target_segments:
            parts.append("（无匹配的观点段落）")

        return "\n".join(parts)

    def _sample_values_tensions(self, preprocessed: PreprocessedChat,
                                target: str) -> str:
        """为价值观/矛盾 Agent 采样：含价值观关键词的段落。"""
        parts = [f"=== {target} 涉及价值观的段落 "
                 f"（共 {len(preprocessed.value_segments)} 段）===\n"]

        target_segments = [
            s for s in preprocessed.value_segments
            if s.startswith(f"{target}:")
        ]
        for i, seg in enumerate(target_segments, 1):
            parts.append(f"[{i}] {seg}")

        if not target_segments:
            parts.append("（无匹配的价值观段落）")

        return "\n".join(parts)
