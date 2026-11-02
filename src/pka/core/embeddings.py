"""嵌入提供者（PRD 4.1：BGE-m3，中文友好）。

- ``ollama``：调用本地 Ollama 的嵌入模型（默认 bge-m3，可换 nomic-embed-text）。
- ``hash``：内置确定性向量（256 维，n-gram 哈希 + L2 归一化）。
  相同文本永远得到相同向量，**仅用于单元测试 / 离线演示**，无语义质量。

注意：更换嵌入模型 = 更换向量空间。vectorstore 的集合名带模型标识
（``pka_<embedding_model>``），避免新旧向量混用污染检索结果。
"""

from __future__ import annotations

import hashlib
import math

from ..config import Settings, get_settings


class HashEmbeddings:
    """确定性 n-gram 哈希嵌入（测试/演示用，无需任何模型服务）。"""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        t = (text or "").lower()
        grams: list[str] = list(t)  # unigram
        grams += [t[i : i + 2] for i in range(len(t) - 1)]  # bigram
        for g in grams:
            h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 1.0 if (h >> 8) % 2 == 0 else -1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def get_embeddings(settings: Settings | None = None):
    """按配置返回嵌入对象。

    返回对象满足 LangChain Embeddings 协议（embed_documents / embed_query）。
    ollama 提供者依赖 langchain-ollama，因此采用惰性导入，
    保证 hash 模式在依赖缺失时仍可用。
    """
    s = settings or get_settings()
    if s.embedding_provider == "hash":
        return HashEmbeddings()
    if s.embedding_provider == "ollama":
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            model=s.embedding_model,
            base_url=s.ollama_base_url,
            client_kwargs={"timeout": s.request_timeout},
        )
    raise ValueError(f"不支持的嵌入提供者: {s.embedding_provider}")
