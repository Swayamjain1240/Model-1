"""The one place an Embedder implementation is named (ATL-SwDD-001 s.1).

Pipeline code receives an Embedder through a constructor; only this factory maps
a configuration value onto a class, which is what keeps the stage-2 swap a config
change. Adding a third encoder means adding a line here and nothing else.
"""

from __future__ import annotations

from ..config import SETTINGS, Settings
from ..interfaces import ConfigurationError
from .dense import HashedTFIDFEmbedder
from .trained import TrainedEmbedder

HASHED_KINDS = ("hashed", "hashed-tfidf-d1024")


def build_embedder(kind: str, idf: dict[str, float], *, settings: Settings = SETTINGS):
    """Hashed stand-in (offline default) or the trained static encoder (stage 2)."""
    selected = (kind or "").strip()
    if not selected:
        raise ConfigurationError("embedder kind is empty; use 'hashed' or a model id")
    if selected in HASHED_KINDS or selected == settings.embedder_name:
        return HashedTFIDFEmbedder(idf, settings=settings)
    return TrainedEmbedder(settings=settings)
