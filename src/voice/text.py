"""Text normalization shared by text-to-speech providers."""

import re


# Chat platforms commonly encode emoji as short bracketed names, for example
# ``[旺柴]`` or ``[doge]``. They are display-only markers, not speech content.
_BRACKETED_EMOJI = re.compile(r"\[(?:[\u4e00-\u9fffA-Za-z0-9_]){1,16}\]")


def text_for_speech(text: str) -> str:
    """Remove display-only bracketed emoji markers before synthesis."""
    return _BRACKETED_EMOJI.sub("", text)
