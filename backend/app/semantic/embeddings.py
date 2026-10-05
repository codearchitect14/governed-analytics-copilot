"""Local text embeddings with BAAI/bge-small-en-v1.5 (384 dimensions, MIT licence).

The model runs on CPU through fastembed (ONNX Runtime). It is downloaded once into a cache
directory and loaded lazily, so importing this module does not download anything.
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import Any

from fastembed import TextEmbedding

MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIMENSIONS = 384
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
DEFAULT_CACHE_DIR = Path(os.environ.get("EMBEDDING_CACHE_DIR", ".cache/embeddings"))


class Embedder:
    """Thread safe lazy wrapper around the fastembed text embedding model."""

    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR, model_name: str = MODEL_NAME) -> None:
        self._cache_dir = cache_dir
        self._model_name = model_name
        self._model: Any = None
        self._lock = Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                self._model = TextEmbedding(
                    model_name=self._model_name,
                    cache_dir=str(self._cache_dir),
                )
            return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load().embed(texts)
        return [_to_list(vector) for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        vectors = self._load().embed([QUERY_PREFIX + text])
        return _to_list(next(iter(vectors)))


def _to_list(vector: Any) -> list[float]:
    values = [float(value) for value in vector.tolist()]
    if len(values) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"expected {EMBEDDING_DIMENSIONS} dimensions, got {len(values)}")
    return values
