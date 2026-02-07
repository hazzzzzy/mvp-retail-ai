from __future__ import annotations

from typing import Any

import anyio
import chromadb
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings

settings = get_settings()


class LocalEmbeddingFunction:
    def __init__(self, model_path: str):
        self.model = SentenceTransformer(model_path)

    def __call__(self, input: list[str]) -> list[list[float]]:
        vectors = self.model.encode(input, normalize_embeddings=True)
        return [v.tolist() for v in vectors]

    def name(self) -> str:
        return "local-bge-base-zh-v1.5"

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self.__call__(input)

    def embed_query(self, input: list[str] | str) -> list[list[float]]:
        texts = input if isinstance(input, list) else [input]
        return self.__call__(texts)


class ChromaStore:
    def __init__(self) -> None:
        self._client = chromadb.PersistentClient(path=settings.chroma_dir_abs)
        self._embedder = LocalEmbeddingFunction(settings.embed_model_abs)

    def _get_collection(self):
        try:
            return self._client.get_or_create_collection(
                name="retail_kb",
                embedding_function=self._embedder,
            )
        except Exception:
            try:
                self._client.delete_collection(name="retail_kb")
            except Exception:
                pass
            return self._client.get_or_create_collection(
                name="retail_kb",
                embedding_function=self._embedder,
            )

    async def upsert_docs(self, docs: list[dict[str, Any]]) -> None:
        def _upsert() -> None:
            collection = self._get_collection()
            collection.upsert(
                ids=[d["id"] for d in docs],
                documents=[d["content"] for d in docs],
                metadatas=[{"title": d["title"], "tags": ",".join(d["tags"])} for d in docs],
            )

        await anyio.to_thread.run_sync(_upsert)

    async def query(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        def _query():
            collection = self._get_collection()
            return collection.query(query_texts=[query], n_results=top_k)

        result = await anyio.to_thread.run_sync(_query)
        docs = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        output: list[dict[str, Any]] = []
        for doc, meta in zip(docs, metadatas):
            output.append(
                {
                    "title": meta.get("title", ""),
                    "content": doc,
                    "tags": (meta.get("tags") or "").split(",") if meta.get("tags") else [],
                }
            )
        return output


chroma_store = ChromaStore()
