"""Embedder seam tests (FR-07, FR-12, NFR-17): no network, no model download.

The trained-encoder tests inject a stub model, so the suite proves the cache and
the offline path without ever fetching weights; the real fetch is measured by
`python -m eval.embeddings` and recorded in results/embeddings.md.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from atlas.config import SETTINGS
from atlas.interfaces import ConfigurationError
from atlas.retrieval.embedder import build_embedder
from atlas.retrieval.trained import OFFLINE_ENV, TrainedEmbedder

IDF = {"attendance": 1.2, "hostel": 1.1, "curfew": 0.9, "grade": 1.0}


class StubModel:
    """Deterministic stand-in for StaticModel: dim 8, term-count bag of words."""

    def __init__(self) -> None:
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        out = np.zeros((len(texts), 8), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in text.lower().split():
                out[row, len(token) % 8] += 1.0
        return out


@pytest.fixture
def trained_settings(tmp_path):
    return dataclasses.replace(
        SETTINGS, embedder_cache_dir=str(tmp_path / "cache"), trained_dim=8
    )


def test_factory_defaults_to_the_offline_hashed_encoder():
    embedder = build_embedder("hashed", IDF)
    assert embedder.name == SETTINGS.embedder_name
    assert embedder.dim == SETTINGS.dense_dim


def test_factory_rejects_an_empty_kind():
    with pytest.raises(ConfigurationError):
        build_embedder("  ", IDF)


def test_hashed_vectors_are_unit_norm_and_deterministic():
    embedder = build_embedder("hashed", IDF)
    first = embedder.embed(["hostel curfew rules", "hostel curfew rules"])
    second = embedder.embed(["hostel curfew rules", "hostel curfew rules"])
    np.testing.assert_allclose(np.linalg.norm(first[0]), 1.0, rtol=1e-6)
    np.testing.assert_array_equal(first, second)  # FR-12 determinism


def test_trained_embedder_caches_and_then_runs_offline(trained_settings, monkeypatch):
    monkeypatch.delenv(OFFLINE_ENV, raising=False)
    embedder = TrainedEmbedder(settings=trained_settings)
    embedder._model = StubModel()  # no download in the test suite
    vectors = embedder.embed(["hostel curfew", "grade scales"])
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1.0, rtol=1e-6)

    # a second process-equivalent instance reads the disk cache: no model needed
    monkeypatch.setenv(OFFLINE_ENV, "1")
    replay = TrainedEmbedder(settings=trained_settings)
    np.testing.assert_array_equal(replay.embed(["hostel curfew", "grade scales"]), vectors)


def test_cold_cache_with_offline_flag_is_a_configuration_error(trained_settings, monkeypatch):
    monkeypatch.setenv(OFFLINE_ENV, "1")
    embedder = TrainedEmbedder(settings=trained_settings)
    with pytest.raises(ConfigurationError):
        embedder.embed(["never embedded before"])


def test_theta_follows_the_selected_encoder_scale():
    """The gate threshold is a property of the score scale, not a global constant."""
    hashed = dataclasses.replace(SETTINGS, embedder_kind=SETTINGS.embedder_name)
    trained = dataclasses.replace(SETTINGS, embedder_kind=SETTINGS.trained_model)
    assert hashed.trained is False
    assert hashed.theta == SETTINGS.confidence_theta
    assert trained.trained is True
    assert trained.theta == SETTINGS.confidence_theta_trained
    assert trained.theta_grid == SETTINGS.theta_candidates_trained


def test_blank_text_embeds_to_a_zero_row(trained_settings, monkeypatch):
    monkeypatch.delenv(OFFLINE_ENV, raising=False)
    embedder = TrainedEmbedder(settings=trained_settings)
    embedder._model = StubModel()
    matrix = embedder.embed(["   "])
    assert matrix.shape == (1, 8)
    assert float(np.linalg.norm(matrix[0])) == 0.0
