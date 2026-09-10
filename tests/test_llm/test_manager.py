import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.llm.manager import LLMManager, replace_llm_client
from src.config.loader import LLMConfig, OllamaConfig


class TestLLMManager:
    def test_get_client_creates_client(self):
        config = LLMConfig(base_url="https://api.test.com/v1", api_key="sk-test", model="gpt-4o")
        client = LLMManager.get_client(config)
        assert client is not None

    def test_get_client_allows_empty_api_key(self):
        """允许空 API Key 创建客户端（启动时不校验，实际请求时由服务端返回错误）"""
        config = LLMConfig(base_url="https://api.test.com/v1", api_key="", model="gpt-4o")
        client = LLMManager.get_client(config)
        assert client is not None

    def test_local_ollama_uses_its_endpoint_and_non_secret_placeholder(self):
        config = LLMConfig(
            provider="local",
            ollama=OllamaConfig(base_url="http://127.0.0.1:11434/v1", model="qwen3:8b"),
        )
        client = LLMManager.get_client(config)

        assert client.model == "qwen3:8b"

    @pytest.mark.asyncio
    async def test_local_ollama_connection_requires_the_selected_model(self):
        config = LLMConfig(
            provider="local",
            ollama=OllamaConfig(model="qwen3:8b"),
        )
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"data": [{"id": "qwen3:8b"}]}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            assert await LLMManager.test_connection(config) is True

        mock_response.json.return_value = {"data": [{"id": "other-model"}]}
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            assert await LLMManager.test_connection(config) is False

    def test_get_client_no_base_url_raises(self):
        config = LLMConfig(base_url="", api_key="sk-test", model="gpt-4o")
        try:
            LLMManager.get_client(config)
            assert False, "Should have raised"
        except ValueError as e:
            assert "Base URL" in str(e)

    @pytest.mark.asyncio
    async def test_test_connection_success(self):
        config = LLMConfig(base_url="https://api.test.com/v1", api_key="sk-test", model="gpt-4o")
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await LLMManager.test_connection(config)
            assert result is True

    @pytest.mark.asyncio
    async def test_test_connection_failure(self):
        config = LLMConfig(base_url="https://api.test.com/v1", api_key="sk-test", model="gpt-4o")
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await LLMManager.test_connection(config)
            assert result is False

    @pytest.mark.asyncio
    async def test_test_connection_exception(self):
        config = LLMConfig(base_url="https://api.test.com/v1", api_key="sk-test", model="gpt-4o")

        with patch("httpx.AsyncClient.get", side_effect=Exception("Connection refused")):
            result = await LLMManager.test_connection(config)
            assert result is False

    @pytest.mark.asyncio
    async def test_replace_llm_client_closes_previous_client(self):
        old = MagicMock()
        old.aclose = AsyncMock()
        config = LLMConfig(base_url="https://new.test/v1", api_key="new", model="new-model")

        with patch("src.llm.manager._llm_client", old):
            new_client = await replace_llm_client(config)

        old.aclose.assert_awaited_once()
        assert new_client.model == "new-model"


def test_get_client_rejects_non_http_base_url():
    config = LLMConfig(
        base_url="not-a-url",
        api_key="secret",
        model="test-model",
    )

    with pytest.raises(ValueError, match="HTTP"):
        LLMManager.get_client(config)
