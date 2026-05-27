from ..config.logger import get_logger

log = get_logger("message")


class MessageManager:
    """管理对话历史（单会话，无需 session_id）"""

    def __init__(self, max_turns: int = 20):
        self._messages: list[dict] = []
        self._max_turns = max_turns

    def add(self, role: str, content: str):
        """添加消息，仅对 user/assistant 做轮数截断，不触碰 system 消息"""
        self._messages.append({"role": role, "content": content})
        log.debug("添加消息, role=%s, content_len=%d, total=%d", role, len(content), len(self._messages))
        if role in ("user", "assistant"):
            conv_indices = [i for i, m in enumerate(self._messages)
                            if m["role"] in ("user", "assistant")]
            if len(conv_indices) > self._max_turns * 2:
                excess = len(conv_indices) - self._max_turns * 2
                log.debug("对话轮数超限, 截断 %d 条旧消息, 阈值=%d", excess, self._max_turns * 2)
                for idx in reversed(conv_indices[:excess]):
                    self._messages.pop(idx)

    def get_all(self) -> list[dict]:
        """获取所有消息（含 system）"""
        return list(self._messages)

    @property
    def conversation(self) -> list[dict]:
        """只返回 user/assistant 对话消息"""
        return [m for m in self._messages if m["role"] in ("user", "assistant")]

    def compress_conversation(self, keep_recent: int, summary: str):
        """用摘要替换早期的 user/assistant 消息，保留所有 system 消息不变"""
        system_msgs = [m for m in self._messages if m["role"] == "system"]
        conv_msgs = [m for m in self._messages if m["role"] in ("user", "assistant")]
        kept_conv = conv_msgs[-keep_recent:] if keep_recent > 0 else []
        log.info("压缩对话历史, 原始对话=%d条, 保留=%d条, 摘要=%s", len(conv_msgs), keep_recent, summary[:50])
        self._messages = system_msgs + [
            {"role": "system", "content": f"[对话摘要] {summary}"}
        ] + kept_conv
        log.debug("压缩后 messages 结构, system=%d条, kept_conv=%d条, total=%d",
                  len(system_msgs) + 1, len(kept_conv), len(self._messages))

    @property
    def conversation_turns(self) -> int:
        """对话轮数（一对 user+assistant 算一轮）"""
        return len(self.conversation) // 2

    @property
    def conversation_chars(self) -> int:
        """对话消息总字符数（不含 system）"""
        return sum(len(m["content"]) for m in self.conversation)

    @property
    def total_chars(self) -> int:
        """所有消息总字符数"""
        return sum(len(m["content"]) for m in self._messages)

    def clear(self):
        """清除对话历史"""
        log.info("清除对话历史, 清除前共 %d 条消息", len(self._messages))
        self._messages.clear()

    def save_to_file(self, path) -> None:
        """将对话历史保存为 JSON 文件"""
        import json
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(self._messages, ensure_ascii=False, indent=2)
        p.write_text(content)
        log.info("对话历史保存到文件, path=%s, messages=%d, size=%d bytes", p, len(self._messages), len(content))

    def load_from_file(self, path) -> bool:
        """从 JSON 文件加载对话历史，返回是否成功"""
        from pathlib import Path
        p = Path(path)
        if not p.exists():
            log.debug("对话历史文件不存在, path=%s", p)
            return False
        import json
        self._messages = json.loads(p.read_text())
        log.info("对话历史加载完成, path=%s, messages=%d, turns=%d", p, len(self._messages), self.conversation_turns)
        return True
