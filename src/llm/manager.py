import httpx
from urllib.parse import urlparse
from .client import LLMClient
from ..config.loader import LLMConfig, LLMEndpointConfig

# 全局懒汉单例
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """获取全局 LLMClient 单例（首次调用时自动初始化）"""
    global _llm_client
    if _llm_client is None:
        from ..config.settings import Settings
        _llm_client = LLMManager.get_client(Settings.get().llm)
    return _llm_client


async def replace_llm_client(config: LLMConfig) -> LLMClient:
    """Atomically replace the process-wide client and close the old pool."""
    global _llm_client
    previous = _llm_client
    replacement = LLMManager.get_client(config)
    _llm_client = replacement
    if previous is not None and previous is not replacement:
        await previous.aclose()
    return replacement


class LLMManager:
    """根据配置创建 LLMClient 实例"""

    @staticmethod
    def get_client(config: LLMConfig | LLMEndpointConfig) -> LLMClient:
        """工厂方法，创建 LLM 客户端（允许空 API Key，实际请求时校验）"""
        endpoint = config.active if isinstance(config, LLMConfig) else config
        if not endpoint.base_url:
            raise ValueError("API Base URL is not configured.")
        parsed = urlparse(endpoint.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("API Base URL must be a valid HTTP(S) URL.")
        return LLMClient(
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
            model=endpoint.model,
            temperature=endpoint.temperature,
        )

    @staticmethod
    async def test_connection(config: LLMConfig | LLMEndpointConfig) -> bool:
        """测试 LLM 连接是否可用"""
        endpoint = config.active if isinstance(config, LLMConfig) else config
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{endpoint.base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {endpoint.api_key}"},
                )
                if response.status_code != 200:
                    return False
                if isinstance(config, LLMConfig) and config.provider == "local":
                    models = response.json().get("data", [])
                    return any(item.get("id") == endpoint.model for item in models)
                return True
        except Exception:
            return False
