"""Stage-2 trained encoder: a distilled static embedding table (ATL-TDD-001 s.10).

model2vec makes a *pretrained* sentence encoder usable as a plain numpy matrix
lookup: CPU-only, no torch, 256 dims. That matters because the Embedder seam was
built so this swap touches one configuration value, not the pipeline.

Offline-first is preserved (C-3, NFR-17): the hashed stand-in stays the default,
this class is opt-in, and every embedded text is cached on disk, so a re-run after
the first fetch needs no network at all. `ATLAS_EMBEDDER_OFFLINE=1` asserts that.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from ..config import SETTINGS, Settings
from ..interfaces import ConfigurationError

OFFLINE_ENV = "ATLAS_EMBEDDER_OFFLINE"


class TrainedEmbedder:
    """Implements the Embedder Protocol with pretrained static vectors, cached on disk."""

    name: str
    dim: int

    def __init__(self, *, settings: Settings = SETTINGS) -> None:
        self.name = settings.trained_model
        self.dim = settings.trained_dim
        self._settings = settings
        self._model = None
        self._cache = _VectorCache(Path(settings.embedder_cache_dir), self.name, self.dim)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """(n, dim) float32, L2-normalised rows so cosine is a dot product (FR-12)."""
        texts = list(texts)
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        keys = [_text_key(text) for text in texts]
        blank = [idx for idx, text in enumerate(texts) if not text.strip()]
        missing = [
            idx for idx, key in enumerate(keys) if key not in self._cache and idx not in blank
        ]
        if missing:
            self._fill([texts[idx] for idx in missing], [keys[idx] for idx in missing])
        matrix = np.zeros((len(texts), self.dim), dtype=np.float32)
        for idx, key in enumerate(keys):
            if idx not in blank:
                matrix[idx] = self._cache[key]
        return _unit(matrix)

    def _fill(self, texts: list[str], keys: list[str]) -> None:
        """One batched encode for every cache miss, then persist; offline if all cached."""
        model = self._model_for_inference()
        encoded = np.asarray(model.encode(texts), dtype=np.float32).reshape(len(texts), self.dim)
        for key, vector in zip(keys, _unit(encoded), strict=True):
            self._cache.put(key, vector)
        self._cache.flush()

    def _model_for_inference(self):
        """Load lazily: a warm disk cache never needs the model, so a test can forbid it."""
        if self._model is not None:
            return self._model
        if os.environ.get(OFFLINE_ENV):
            raise ConfigurationError(
                f"{OFFLINE_ENV}=1 forbids loading {self.name!r} with a cold vector cache"
            )
        try:
            from model2vec import StaticModel  # noqa: PLC0415 - optional dependency
        except ImportError as error:  # pragma: no cover - exercised by design review
            raise ConfigurationError(
                "model2vec is not installed: pip install 'atlas[trained]' "
                "(or keep ATLAS_EMBEDDER unset for the offline hashed embedder)"
            ) from error
        self._model = StaticModel.from_pretrained(self.name)
        return self._model


class _VectorCache:
    """text-hash -> vector, persisted as one .npz per (model, dim).

    Keyed by content, not by position, so re-ingesting or reordering the corpus
    reuses everything unchanged and the cache can never mislabel a chunk.
    """

    def __init__(self, directory: Path, model: str, dim: int) -> None:
        self._path = directory / f"{_slug(model)}-d{dim}.npz"
        self._vectors: dict[str, np.ndarray] = {}
        self._dirty = False
        if self._path.exists():
            with np.load(self._path) as data:
                self._vectors = {key: data[key].astype(np.float32) for key in data.files}

    def __contains__(self, key: str) -> bool:
        return key in self._vectors

    def __getitem__(self, key: str) -> np.ndarray:
        return self._vectors[key]

    def put(self, key: str, vector: np.ndarray) -> None:
        self._vectors[key] = vector.astype(np.float32)
        self._dirty = True

    def flush(self) -> None:
        """Write once per batch; a missing cache directory is created, never assumed."""
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(self._path, **self._vectors)
        self._dirty = False


def _unit(matrix: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalisation; a zero row stays zero instead of dividing by zero."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms > 0, norms, 1.0)


def _text_key(text: str) -> str:
    """BLAKE2b over UTF-8: stable across runs and processes (ATL-TDD-001 s.11)."""
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


def _slug(model: str) -> str:
    """Filesystem-safe model name: minishlab/potion-base-8M -> minishlab__potion-base-8M."""
    return model.replace("/", "__").replace(":", "_")
