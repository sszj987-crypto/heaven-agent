"""向量化编码器：文本 → embedding vector"""

from sentence_transformers import SentenceTransformer

from ..config.logger import get_logger

log = get_logger("memory")

# 中文支持好、体积小的多语言模型
_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


class MemoryEmbedder:
    """文本向量化，单例延迟加载"""

    _instance: "MemoryEmbedder | None" = None

    def __init__(self):
        log.info("加载 embedding 模型: %s", _MODEL_NAME)
        self._model = SentenceTransformer(_MODEL_NAME)
        log.info("embedding 模型加载完成, dim=%d", self._model.get_embedding_dimension())

    @classmethod
    def get(cls) -> "MemoryEmbedder":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def dim(self) -> int:
        return self._model.get_embedding_dimension()

    def encode(self, texts: list[str]) -> list[list[float]]:
        """将文本列表编码为向量列表"""
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    def encode_single(self, text: str) -> list[float]:
        """将单条文本编码为向量"""
        return self.encode([text])[0]
