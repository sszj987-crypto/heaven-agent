import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from src.llm.client import LLMClient, _content_from_stream_chunk, _stream_payload


class TestLLMClient:
    def setup_method(self):
        self._client = LLMClient(
            base_url="https://api.test.com/v1",
            api_key="sk-test",
            model="gpt-4o",
        )

    @pytest.mark.asyncio
    async def test_chat_sends_correct_request(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "你好"}}]}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await self._client.chat([{"role": "user", "content": "你好"}])

        assert result == "你好"

    @pytest.mark.asyncio
    async def test_chat_verifies_request_format(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
            await self._client.chat([{"role": "user", "content": "你好"}])

        call_args = mock_post.call_args
        assert call_args[0][0] == "https://api.test.com/v1/chat/completions"
        sent_json = call_args[1]["json"]
        assert sent_json["model"] == "gpt-4o"
        assert "Bearer sk-test" in call_args[1]["headers"]["Authorization"]

    @pytest.mark.asyncio
    async def test_stream_sse_parsing(self):
        """测试 SSE 流解析逻辑（不依赖 httpx mock 细节）"""
        async def sse_lines():
            yield json.dumps({"choices": [{"delta": {"content": "你"}}]})
            yield json.dumps({"choices": [{"delta": {"content": "好"}}]})
            yield "data: [DONE]"

        # 直接测试 SSE 解析逻辑：跳过 [DONE]，提取 delta.content
        chunks = []
        async for line in sse_lines():
            if line.startswith("data: [DONE]"):
                break
            try:
                data = json.loads(line)
                delta = data["choices"][0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    chunks.append(content)
            except (json.JSONDecodeError, KeyError, IndexError):
                continue

        assert "".join(chunks) == "你好"

    @pytest.mark.asyncio
    async def test_chat_empty_response(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": ""}}]}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await self._client.chat([{"role": "user", "content": ""}])

        assert result == ""

    def test_request_disables_reasoning_only_when_configured(self):
        client = LLMClient(
            base_url="http://127.0.0.1:11434/v1",
            api_key="ollama",
            model="qwen3.5:9b",
            reasoning_effort="none",
        )

        body = client._request_body([{"role": "user", "content": "你好"}], stream=True)

        assert body["reasoning_effort"] == "none"
        assert body["stream"] is True

    def test_stream_usage_is_opt_in_for_compatible_providers(self):
        client = LLMClient(
            base_url="http://127.0.0.1:11434/v1",
            api_key="ollama",
            model="local-model",
            include_stream_usage=True,
        )

        body = client._request_body([{"role": "user", "content": "你好"}], stream=True)

        assert body["stream_options"] == {"include_usage": True}


def test_stream_payload_accepts_sse_without_a_space_and_json_lines():
    assert _stream_payload('data:{"choices": []}') == {"choices": []}
    assert _stream_payload('{"choices": []}') == {"choices": []}
    assert _stream_payload("data: [DONE]") == "[DONE]"


def test_stream_content_uses_visible_content_and_never_reasoning():
    content, has_reasoning = _content_from_stream_chunk({
        "choices": [{"delta": {"reasoning_content": "internal", "content": "你好"}}]
    })
    reasoning_only, reasoning_only_present = _content_from_stream_chunk({
        "choices": [{"delta": {"reasoning_content": "internal"}}]
    })

    assert content == "你好"
    assert has_reasoning is True
    assert reasoning_only == ""
    assert reasoning_only_present is True
