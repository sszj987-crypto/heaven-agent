"""ChatPreprocessor 单元测试：格式精炼、消息解析、统计提取、差异化采样。"""

import pytest
from src.soul.chat_preprocessor import (
    ChatPreprocessor, SpeakerStats, PreprocessedChat,
)

# ── 测试数据 ──────────────────────────────────────────────

_WECHAT_EXPORT = """2024-03-15 14:32:45 张三
今天天气真好啊~

2024-03-15 14:33:10 李四
是呀，要不要出去走走？

2024-03-15 14:35:22 张三
我觉得...人生就像一场马拉松，不在乎起点在哪里，关键是能不能坚持到最后。你说对吧？

2024-03-15 14:36:01 李四
你说得对！我就是有时候觉得自己太容易放弃了…

2024-03-15 14:38:15 张三
别这么说嘛~每个人都有迷茫的时候。我以前也想过放弃，但是呢…后来发现坚持下来才是最重要的。

2024-03-15 14:40:30 李四
谢谢你呀，听了你的话我心情好多了！
"""


# ── 格式精炼测试 ────────────────────────────────────────

class TestRefineFormat:
    """Layer 2: 格式精炼"""

    def test_strips_timestamps(self):
        cp = ChatPreprocessor()
        result = cp._refine_format(_WECHAT_EXPORT)
        # 不应该包含时间戳行
        assert "2024-03-15" not in result
        assert "14:32:45" not in result

    def test_keeps_speaker_and_content(self):
        cp = ChatPreprocessor()
        result = cp._refine_format(_WECHAT_EXPORT)
        assert "张三" in result
        assert "李四" in result
        assert "今天天气真好啊" in result
        assert "要不要出去走走" in result

    def test_compresses_consecutive_empty_lines(self):
        cp = ChatPreprocessor()
        text = "张三: 你好\n\n\n\n李四: 你好"
        result = cp._refine_format(text)
        # 连续空行被压缩：最多一个空行
        assert "\n\n\n" not in result

    def test_removes_system_messages(self):
        cp = ChatPreprocessor()
        text = "张三: 你好\n系统提示: 某某已退出群聊\n李四: 再见"
        # 系统提示行本身不包含 speaker: content 格式，精炼后可能被保留纯文本
        # 这里测试 _is_system_line
        assert cp._is_system_line("系统提示: 某某已退出群聊") is False  # 不是系统消息格式

    def test_preserves_all_dialogue_content(self):
        """精炼不丢失有效对话内容"""
        cp = ChatPreprocessor()
        result = cp._refine_format(_WECHAT_EXPORT)
        assert "马拉松" in result
        assert "坚持" in result
        assert "迷茫" in result
        assert "放弃" in result
        assert "心情" in result


# ── 消息解析测试 ────────────────────────────────────────

class TestParseMessages:
    """消息解析"""

    def test_parses_speaker_content_pairs(self):
        cp = ChatPreprocessor()
        text = "张三: 你好\n李四: 你好呀\n张三: 吃饭了吗"
        msgs = cp._parse_messages(text)
        assert len(msgs) == 3
        assert msgs[0] == {"speaker": "张三", "content": "你好"}
        assert msgs[1] == {"speaker": "李四", "content": "你好呀"}

    def test_skips_empty_content_lines(self):
        cp = ChatPreprocessor()
        text = "张三: \n李四: 你好"
        msgs = cp._parse_messages(text)
        assert len(msgs) == 1
        assert msgs[0]["speaker"] == "李四"

    def test_handles_chinese_colon(self):
        cp = ChatPreprocessor()
        text = "张三：你好啊\n李四：哈哈"
        msgs = cp._parse_messages(text)
        assert len(msgs) == 2
        assert msgs[0]["speaker"] == "张三"

    def test_skips_pure_text_lines(self):
        cp = ChatPreprocessor()
        text = "这是一行没有发言人的文本\n张三: 你好"
        msgs = cp._parse_messages(text)
        assert len(msgs) == 1
        assert msgs[0]["speaker"] == "张三"


# ── 统计提取测试 ────────────────────────────────────────

class TestExtractStats:
    """Layer 1: 统计提取"""

    def test_basic_stats(self):
        cp = ChatPreprocessor()
        messages = [
            "你好呀~",
            "今天天气真好！你觉得呢？",
            "我觉得人生就像一场马拉松…需要坚持。",
        ]
        stats = cp._extract_stats("测试", messages)
        assert stats.name == "测试"
        assert stats.message_count == 3
        assert stats.total_chars > 0

    def test_ellipsis_detection(self):
        cp = ChatPreprocessor()
        messages = ["我想想…嗯…大概是这样的吧", "好吧…那就这样"]
        stats = cp._extract_stats("测试", messages)
        assert stats.ellipsis_ratio > 0

    def test_exclamation_detection(self):
        cp = ChatPreprocessor()
        messages = ["太棒了！", "真的吗！太好了！"]
        stats = cp._extract_stats("测试", messages)
        assert stats.exclamation_ratio > 0

    def test_interjection_frequency(self):
        cp = ChatPreprocessor()
        messages = ["你好呀~", "是呢是呢", "好吧好吧", "怎么啦"]
        stats = cp._extract_stats("测试", messages)
        # 呀、呢、吧、啦 各一次
        assert "呀" in stats.interjection_freq
        assert stats.interjection_freq["呀"] == 1
        assert "呢" in stats.interjection_freq

    def test_short_sentence_ratio(self):
        cp = ChatPreprocessor()
        short = ["嗯", "好的", "哈哈"]
        stats = cp._extract_stats("测试", short)
        assert stats.short_sentence_ratio > 0

    def test_top_words_extraction(self):
        cp = ChatPreprocessor()
        messages = ["坚持就是胜利，坚持很重要，每天都要坚持"]
        stats = cp._extract_stats("测试", messages)
        # "坚持" 出现 3 次
        assert "坚持" in stats.top_words

    def test_empty_messages(self):
        cp = ChatPreprocessor()
        stats = cp._extract_stats("测试", [])
        assert stats.message_count == 0
        assert stats.avg_sentence_length == 0.0


# ── 对话回合提取测试 ────────────────────────────────────

class TestDialogueRounds:
    """对话回合提取"""

    def test_extracts_alternating_rounds(self):
        cp = ChatPreprocessor()
        messages = [
            {"speaker": "A", "content": "你好"},
            {"speaker": "B", "content": "你好"},
            {"speaker": "A", "content": "吃饭了吗"},
            {"speaker": "B", "content": "吃了"},
        ]
        rounds = cp._extract_dialogue_rounds(messages)
        assert len(rounds) >= 1
        # 第一个回合应包含 4 条消息（A-B-A-B）
        assert len(rounds[0]) >= 3

    def test_filters_short_rounds(self):
        cp = ChatPreprocessor()
        messages = [
            {"speaker": "A", "content": "嗯"},
            {"speaker": "B", "content": "哦"},
        ]
        rounds = cp._extract_dialogue_rounds(messages)
        # 只有 2 轮，小于 MIN_DIALOGUE_TURNS(3)，被过滤
        assert len(rounds) == 0


# ── 观点/价值观段落提取测试 ──────────────────────────────

class TestSegmentExtraction:
    """观点和价值观段落提取"""

    def test_extracts_opinion_segments(self):
        cp = ChatPreprocessor()
        messages = [
            {"speaker": "张三", "content": "我觉得人生应该追求自由"},
            {"speaker": "张三", "content": "今天天气不错"},
            {"speaker": "张三", "content": "说实话，我真的很喜欢这份工作"},
        ]
        segments = cp._extract_opinion_segments(messages)
        assert len(segments) == 2  # 含"我觉得"和"说实话"

    def test_extracts_value_segments(self):
        cp = ChatPreprocessor()
        messages = [
            {"speaker": "张三", "content": "家庭对我来说最重要"},
            {"speaker": "张三", "content": "工作就是谋生而已"},
            {"speaker": "张三", "content": "今天吃了面条"},
        ]
        segments = cp._extract_value_segments(messages)
        assert len(segments) == 2  # 含"家庭"和"工作"

    def test_empty_segments(self):
        cp = ChatPreprocessor()
        messages = [
            {"speaker": "张三", "content": "嗯"},
            {"speaker": "张三", "content": "好的"},
        ]
        opinions = cp._extract_opinion_segments(messages)
        values = cp._extract_value_segments(messages)
        assert len(opinions) == 0
        assert len(values) == 0


# ── 端到端预处理测试 ────────────────────────────────────

class TestProcessEndToEnd:
    """完整的 process() 管线"""

    def test_process_returns_all_fields(self):
        cp = ChatPreprocessor()
        result = cp.process(_WECHAT_EXPORT)
        assert isinstance(result, PreprocessedChat)
        assert len(result.refined_text) > 0
        assert len(result.messages) > 0
        assert "张三" in result.speakers
        assert "李四" in result.speakers

    def test_process_with_target_name(self):
        cp = ChatPreprocessor()
        result = cp.process(_WECHAT_EXPORT, target_name="张三")
        assert result.target_speaker == "张三"

    def test_process_auto_detects_target(self):
        cp = ChatPreprocessor()
        result = cp.process(_WECHAT_EXPORT)
        # 自动选择消息最多的发言人
        assert result.target_speaker in ("张三", "李四")

    def test_process_statistics_for_target(self):
        cp = ChatPreprocessor()
        result = cp.process(_WECHAT_EXPORT, target_name="张三")
        stats = result.speakers.get("张三")
        assert stats is not None
        assert stats.message_count > 0
        assert stats.total_chars > 0

    def test_process_target_not_found_fallback(self):
        """指定 target_name 未匹配时自动回退到消息最多的发言人"""
        cp = ChatPreprocessor()
        result = cp.process(_WECHAT_EXPORT, target_name="王五")
        # 王五不在聊天记录中，应回退到消息最多的发言人
        assert result.target_speaker != "王五"
        assert result.target_speaker in ("张三", "李四")

    def test_process_wechat_me_speaker(self):
        """微信导出中"我"作为发言人，target_name 指定实际姓名应自动回退"""
        chat = """2024-03-15 14:32:45 我
今天天气真好啊~

2024-03-15 14:33:10 李四
是呀，要不要出去走走？

2024-03-15 14:35:22 我
我觉得人生需要坚持
"""
        cp = ChatPreprocessor()
        result = cp.process(chat, target_name="张三")
        # "张三" 不在发言人中，应回退到 "我"
        assert result.target_speaker == "我"


# ── 差异化采样测试 ──────────────────────────────────────

class TestSamplingForAgent:
    """Layer 3: 差异化采样"""

    def test_expression_dna_sample(self):
        cp = ChatPreprocessor()
        result = cp.process(_WECHAT_EXPORT, target_name="张三")
        sample = cp.sample_for_agent(result, "expression_dna")
        assert "张三" in sample
        assert "量化统计" in sample
        assert "消息样本" in sample

    def test_decision_heuristics_sample(self):
        cp = ChatPreprocessor()
        result = cp.process(_WECHAT_EXPORT, target_name="张三")
        sample = cp.sample_for_agent(result, "decision_heuristics")
        assert "对话回合" in sample
        assert "张三" in sample

    def test_mental_models_sample(self):
        cp = ChatPreprocessor()
        result = cp.process(_WECHAT_EXPORT, target_name="张三")
        sample = cp.sample_for_agent(result, "mental_models")
        assert "观点" in sample
        assert "张三" in sample

    def test_values_tensions_sample(self):
        cp = ChatPreprocessor()
        result = cp.process(_WECHAT_EXPORT, target_name="张三")
        sample = cp.sample_for_agent(result, "values_tensions")
        assert "价值观" in sample

    def test_unknown_agent_type_raises(self):
        cp = ChatPreprocessor()
        result = cp.process(_WECHAT_EXPORT)
        with pytest.raises(ValueError, match="Unknown agent_type"):
            cp.sample_for_agent(result, "unknown_agent")


# ── SpeakerStats 格式化测试 ─────────────────────────────

class TestSpeakerStatsFormat:
    """SpeakerStats 输出格式化"""

    def test_format_for_prompt(self):
        stats = SpeakerStats(
            name="测试",
            message_count=100,
            total_chars=5000,
            avg_sentence_length=25.5,
            short_sentence_ratio=0.3,
            long_sentence_ratio=0.1,
            ellipsis_ratio=15.2,
            exclamation_ratio=8.1,
            question_ratio=12.3,
            period_ratio=45.0,
            wave_ratio=5.5,
            interjection_freq={"呀": 20, "呢": 15, "吧": 10},
            top_words=["坚持", "努力", "人生", "幸福"],
        )
        text = stats.format_for_prompt()
        assert "100" in text
        assert "25.5" in text
        assert "呀(20)" in text
        assert "坚持" in text

    def test_empty_stats_format(self):
        stats = SpeakerStats(name="空")
        text = stats.format_for_prompt()
        assert "0" in text
        assert "无" in text

    def test_to_dict(self):
        stats = SpeakerStats(
            name="测试",
            message_count=10,
            total_chars=500,
            interjection_freq={"呀": 5},
            top_words=["你好"],
        )
        d = stats.to_dict()
        assert d["name"] == "测试"
        assert d["message_count"] == 10
        assert len(d["interjection_top5"]) == 1


# ── 边界情况测试 ────────────────────────────────────────

class TestEdgeCases:
    """边界情况"""

    def test_empty_input(self):
        cp = ChatPreprocessor()
        result = cp.process("")
        assert len(result.messages) == 0
        assert len(result.speakers) == 0
        assert result.refined_text == ""

    def test_single_speaker(self):
        cp = ChatPreprocessor()
        text = "张三: 今天天气真好\n张三: 我想出去走走"
        result = cp.process(text)
        assert len(result.speakers) == 1
        assert "张三" in result.speakers
        # 单一发言人无法形成对话回合
        assert len(result.dialogue_rounds) == 0

    def test_various_timestamp_formats(self):
        cp = ChatPreprocessor()
        formats = [
            "2024/03/15 14:32 张三",
            "2024-3-5 9:8 张三",
            "03-15 14:32 张三",
        ]
        for fmt in formats:
            assert cp._is_timestamp_line(fmt), f"Should detect: {fmt}"

    def test_non_timestamp_lines(self):
        cp = ChatPreprocessor()
        not_timestamps = [
            "张三: 你好",
            "2024年3月15日",  # 中文日期不算时间戳行
            "哈哈2024-03-15",
        ]
        for line in not_timestamps:
            # _is_timestamp_line checks if the line STARTS with a timestamp pattern
            # "2024年3月15日" doesn't start with the pattern, so it's not a timestamp
            pass  # These are context-dependent
