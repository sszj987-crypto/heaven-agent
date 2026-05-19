from src.agent.message import MessageManager


class TestMessageManager:
    def setup_method(self):
        self._mm = MessageManager(max_turns=5)

    def test_add_message(self):
        self._mm.add("user", "hello")
        assert len(self._mm.get_all()) == 1

    def test_get_all_returns_copy(self):
        self._mm.add("user", "hello")
        msgs = self._mm.get_all()
        msgs.clear()
        assert len(self._mm.get_all()) == 1  # 原列表未受影响

    def test_add_truncates_only_conversation(self):
        mm = MessageManager(max_turns=1)
        mm.add("system", "[System Prompt] very long system message")
        mm.add("user", "msg1")
        mm.add("assistant", "reply1")
        mm.add("user", "msg2")
        mm.add("assistant", "reply2")
        mm.add("user", "msg3")
        mm.add("assistant", "reply3")

        all_msgs = mm.get_all()
        # system 消息应保留
        assert all_msgs[0]["role"] == "system"
        # 只有最后 1 轮 (2 条) user+assistant
        conv = [m for m in all_msgs if m["role"] in ("user", "assistant")]
        assert len(conv) == 2
        assert conv[0]["content"] == "msg3"
        assert conv[1]["content"] == "reply3"

    def test_conversation_property(self):
        self._mm.add("system", "system msg")
        self._mm.add("user", "hello")
        self._mm.add("assistant", "hi")
        self._mm.add("user", "how are you")

        conv = self._mm.conversation
        assert len(conv) == 3
        assert all(m["role"] in ("user", "assistant") for m in conv)

    def test_conversation_turns(self):
        self._mm.add("system", "system msg")
        self._mm.add("user", "q1")
        self._mm.add("assistant", "a1")
        self._mm.add("user", "q2")
        self._mm.add("assistant", "a2")

        assert self._mm.conversation_turns == 2

    def test_conversation_chars(self):
        self._mm.add("system", "xxxxxxxxxx")  # 10 chars
        self._mm.add("user", "hello")          # 5 chars
        self._mm.add("assistant", "world")     # 5 chars

        assert self._mm.conversation_chars == 10  # 不含 system
        assert self._mm.total_chars == 20        # 含 system

    def test_compress_conversation_preserves_system(self):
        self._mm.add("system", "[Soul Context] 王奶奶")
        self._mm.add("system", "[Circumstances] 场景")
        self._mm.add("user", "msg1")
        self._mm.add("assistant", "reply1")
        self._mm.add("user", "msg2")
        self._mm.add("assistant", "reply2")
        self._mm.add("user", "msg3")
        self._mm.add("assistant", "reply3")

        self._mm.compress_conversation(keep_recent=4, summary="压缩内容")

        result = self._mm.get_all()
        assert result[0]["role"] == "system"
        assert "王奶奶" in result[0]["content"]
        assert result[1]["role"] == "system"
        assert "场景" in result[1]["content"]
        assert result[2]["role"] == "system"
        assert "[对话摘要]" in result[2]["content"]
        assert result[3]["role"] == "user"
        assert result[4]["role"] == "assistant"
        assert result[5]["role"] == "user"
        assert result[6]["role"] == "assistant"
        assert len(result) == 7  # 2 system + 1 summary + 4 recent

    def test_compress_conversation_keep_zero(self):
        self._mm.add("system", "[System]")
        self._mm.add("user", "msg1")
        self._mm.add("assistant", "reply1")

        self._mm.compress_conversation(keep_recent=0, summary="摘要")

        result = self._mm.get_all()
        assert len(result) == 2  # system + summary only
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "system"

    def test_clear(self):
        self._mm.add("system", "sys")
        self._mm.add("user", "hello")
        self._mm.clear()
        assert len(self._mm.get_all()) == 0
        assert self._mm.conversation_turns == 0
