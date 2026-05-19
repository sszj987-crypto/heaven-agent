import httpx
from .client import LLMClient
from ..config.loader import LLMConfig


class LLMManager:
    """根据配置创建 LLMClient 实例"""

    @staticmethod
    def get_client(config: LLMConfig) -> LLMClient:
        """工厂方法，创建 LLM 客户端（允许空 API Key，实际请求时校验）"""
        if not config.base_url:
            raise ValueError("API Base URL is not configured.")
        return LLMClient(
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
        )

    @staticmethod
    async def test_connection(config: LLMConfig) -> bool:
        """测试 LLM 连接是否可用"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{config.base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {config.api_key}"},
                )
                return response.status_code == 200
        except Exception:
            return False
