"""Learned reranker tests (FR-11, FR-12): adoption gate, features, determinism.

The gate matters more than the maths: a model that lost on held-out documents stays
in the repo as evidence, and these tests pin that it stays inert.
"""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

from atlas.config import SETTINGS
from atlas.retrieval.learned import FEATURES, LearnedReranker, build_reranker
from atlas.retrieval.rerank import Reranker
from atlas.text.tokenize import bigrams

IDF = {"hostel": 1.1, "curfew": 0.9, "attendance": 1.2}

CANDIDATES = [
    (0, 0.9, "the hostel curfew is half past ten", "Hostel Rules", "Curfew"),
    (1, 0.8, "attendance below the bar leads to detention", "Attendance Policy", "Detention"),
    (2, 0.7, "grades run from AA to F with points", "Grading System", "Scales"),
]
CONTEXT = {"sparse": {0: 3.0, 1: 1.0, 2: 0.5}, "cosine": {0: 0.8, 1: 0.2, 2: 0.1}}


def model(weights: list[float] | None = None, *, adopted: bool = True) -> dict:
    return {
        "name": "unit-test",
        "features": list(FEATURES),
        "weights": weights or [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "adopted": adopted,
    }


def settings_with(tmp_path, *, kind: str, payload: dict | None) -> object:
    path = tmp_path / "rerank.json"
    if payload is not None:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return dataclasses.replace(SETTINGS, rerank_kind=kind, rerank_model_path=str(path))


def test_blend_is_used_when_no_weights_file_exists(tmp_path):
    reranker = build_reranker(IDF, settings=settings_with(tmp_path, kind="learned", payload=None))
    assert isinstance(reranker, Reranker)


def test_an_unadopted_model_is_inert(tmp_path):
    settings = settings_with(tmp_path, kind="learned", payload=model(adopted=False))
    assert isinstance(build_reranker(IDF, settings=settings), Reranker)


def test_an_adopted_model_replaces_the_blend(tmp_path):
    settings = settings_with(tmp_path, kind="learned", payload=model())
    assert isinstance(build_reranker(IDF, settings=settings), LearnedReranker)


def test_explicit_blend_kind_ignores_a_good_model(tmp_path):
    settings = settings_with(tmp_path, kind="blend", payload=model())
    assert isinstance(build_reranker(IDF, settings=settings), Reranker)


def test_features_are_bounded_and_ordered_by_the_learned_score():
    reranker = LearnedReranker(model(), idf=IDF, settings=SETTINGS)
    matrix = reranker.feature_matrix("hostel curfew", CANDIDATES, CONTEXT)
    assert matrix.shape == (3, len(FEATURES))
    assert float(matrix.min()) >= 0.0 and float(matrix.max()) <= 1.0
    ranked = reranker.rerank("hostel curfew", CANDIDATES, k=3, context=CONTEXT)
    assert [idx for idx, _ in ranked] == [0, 1, 2]  # cosine weight only: 0.8 > 0.2 > 0.1


def test_rerank_is_deterministic():
    reranker = LearnedReranker(model(), idf=IDF, settings=SETTINGS)
    first = reranker.rerank("hostel curfew", CANDIDATES, k=3, context=CONTEXT)
    second = reranker.rerank("hostel curfew", CANDIDATES, k=3, context=CONTEXT)
    assert first == second


def test_attached_features_are_used_instead_of_re_tokenising():
    reranker = LearnedReranker(model(), idf=IDF, settings=SETTINGS)
    phrases = set(bigrams(["hostel", "curfew"]))
    cached = {
        0: ({"hostel", "curfew"}, phrases, {"hostel", "rules"}, {"curfew"}),
    }
    reranker.attach_features(cached)
    matrix = reranker.feature_matrix("hostel curfew", CANDIDATES[:1], CONTEXT)
    # bigram/title/section columns come from the cache, not from re-tokenising the text
    assert np.isclose(matrix[0, FEATURES.index("bigram")], 1.0)


def test_a_model_with_the_wrong_feature_list_is_rejected():
    bad = {**model(), "features": ["cosine"]}
    with pytest.raises(ValueError):
        LearnedReranker(bad, idf=IDF, settings=SETTINGS)
