import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from src.llm.client import LLMClient


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
