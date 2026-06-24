"""向量化编码器：文本 → embedding vector"""

from sentence_transformers import SentenceTransformer

from ..config.logger import get_logger

log = get_logger("memory")

# 中文支持好、体积小的多语言模型
_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


class MemoryEmbedder:
    """文本向量化，单例延迟加载。模型仅在首次 encode() 时加载。"""

    _instance: "MemoryEmbedder | None" = None

    def __init__(self):
        self._model = None
        self._model_name = _MODEL_NAME
        log.debug("MemoryEmbedder 已创建，模型将在首次使用时加载")

    @classmethod
    def get(cls) -> "MemoryEmbedder":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_loaded(self):
        if self._model is not None:
            return
        log.info("加载 embedding 模型: %s", self._model_name)
        self._model = SentenceTransformer(self._model_name)
        log.info("embedding 模型加载完成, dim=%d", self._model.get_embedding_dimension())

    @property
    def dim(self) -> int:
        self._ensure_loaded()
        return self._model.get_embedding_dimension()

    def encode(self, texts: list[str]) -> list[list[float]]:
        """将文本列表编码为向量列表"""
        self._ensure_loaded()
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    def encode_single(self, text: str) -> list[float]:
        """将单条文本编码为向量"""
        return self.encode([text])[0]
