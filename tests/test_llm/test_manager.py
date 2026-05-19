import pytest
from unittest.mock import MagicMock, patch
from src.llm.manager import LLMManager
from src.config.loader import LLMConfig


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
