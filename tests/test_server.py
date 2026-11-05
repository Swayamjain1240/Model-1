"""Server contract tests (FR-19, NFR-09, NFR-14): auth, 400 codes, isolation, timings.

The tests boot real server threads on ephemeral ports with a fresh temp DB; no
test touches data/ or a deployed service.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from atlas.config import SETTINGS
from atlas.server import ServerState, make_handler
from atlas.store import Store
from tests.conftest import MINI_CORPUS


def _boot(tmp_path, settings):
    """Boots a real API thread and returns (base_url, server, state) for teardown."""
    db = tmp_path / "atlas-api.db"
    store = Store(str(db), settings=settings)
    for name, content in MINI_CORPUS.items():  # 'other' holds only hostel content
        doc = tmp_path / name
        doc.write_text(content, encoding="utf-8")
        tenant = "other" if name == "hostel-rules.md" else "campus"
        store.upsert_document(tenant_id=tenant, path=doc)
    store.close()
    state = ServerState(str(db), settings=settings)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", server, state


@pytest.fixture
def api(tmp_path):
    """A live Atlas API over the mini corpus, token protected, default gate."""
    settings = dataclasses.replace(SETTINGS, api_token="test-token")
    base_url, server, state = _boot(tmp_path, settings)
    yield base_url
    server.shutdown()
    state.store.close()
    server.server_close()


@pytest.fixture
def api_open(tmp_path):
    """Same server with an open gate: mini-corpus scores sit below theta=0.13, so the
    answer-contract test runs at theta 0.0 (refusal SLA is measured on the real corpus
    in results/calibration.md, never on the mini corpus)."""
    settings = dataclasses.replace(SETTINGS, api_token="test-token", confidence_theta=0.0)
    base_url, server, state = _boot(tmp_path, settings)
    yield base_url
    server.shutdown()
    state.store.close()
    server.server_close()


def _get(url: str, *, token: str | None = "test-token", tenant: str | None = None):
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if tenant:
        request.add_header("X-Tenant", tenant)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_healthz_is_open_and_liveness(api):
    status, payload = _get(f"{api}/v1/healthz", token=None)
    assert status == 200 and payload["status"] == "ok"


def test_wrong_token_is_401_with_code(api):
    status, payload = _get(f"{api}/v1/ask?q=curfew", token="wrong")
    assert status == 401
    assert payload["error"]["code"] == "AUTH_REQUIRED"


def test_stopword_only_query_is_400_fr19(api):
    status, payload = _get(f"{api}/v1/ask?q=the+of+and")
    assert status == 400
    assert payload["error"]["code"] == "INPUT_INVALID"


def test_answer_contract_citations_and_timings(api_open):
    status, answer = _get(f"{api_open}/v1/ask?q=what+time+is+the+hostel+curfew", tenant="other")
    assert status == 200 and not answer["refused"]
    assert answer["text"] and len(answer["citations"]) == 1
    assert len(answer["timings"]) >= 4  # NFR-14: four stage timings on every answer
    assert answer["citations"][0]["doc_id"]  # FR-15: citation references stored evidence


def test_tenant_isolation_no_cross_tenant_leak(api):
    """A campus question against the 'other' tenant must refuse, never leak (NFR-09)."""
    status, payload = _get(f"{api}/v1/ask?q=how+many+grade+points+is+the+DD+grade",
                           tenant="other")
    assert status == 200
    assert payload["refused"]  # the grading doc lives in 'campus', not 'other'
    assert payload["citations"] == []


def test_demo_page_is_served_unauthenticated(api):
    with urllib.request.urlopen(f"{api}/", timeout=5) as response:
        assert response.status == 200
        assert b"refuses to guess" in response.read()
