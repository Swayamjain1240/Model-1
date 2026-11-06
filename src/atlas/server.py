"""M5 HTTP JSON API (ATL-SwDD; SRS FR-19, NFR-01, NFR-09, NFR-14): stdlib only.

Routes:
    GET /                     one-page demo (web/demo.html), no auth
    GET /v1/healthz           liveness, no auth
    GET /v1/ask?q=...         the product: cited answer or refusal (JSON)
Headers:
    Authorization: Bearer <token>   required when ATLAS_API_TOKEN is set in the env
    X-Tenant: <tenant>              defaults to the configured default tenant

Contract details the tests pin: empty/stopword-only query -> 400 with a
machine-readable error code (FR-19); wrong token -> 401 AUTH_REQUIRED; unknown
tenant -> a deliberate refusal JSON (never leaks another tenant's data, NFR-09);
every answer response exposes four stage timings (NFR-14).
"""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .answer import answer_query
from .config import SETTINGS, Settings
from .interfaces import AtlasError, InputError
from .obs import redact
from .retrieval import HybridIndex
from .store import Store

ROOT = Path(__file__).resolve().parents[2]  # src/atlas/server.py -> model 1/
DEMO_PAGE = ROOT / "web" / "demo.html"

_ERROR_CODES = {
    InputError: ("INPUT_INVALID", 400),
}


class ServerState:
    """One shared read store + one shared hybrid index; per-tenant views cache inside."""

    def __init__(self, db_path: str, settings: Settings = SETTINGS) -> None:
        self.settings = settings
        self.store = Store(db_path, settings=settings)
        self.index = HybridIndex(self.store, settings=settings)


def make_handler(state: ServerState) -> type:
    """Binds the shared state once; the handler class itself stays stateless."""

    class AtlasHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        disable_nagle_algorithm = True  # M5 load-test finding: kills the ~40ms tail stalls

        def do_GET(self) -> None:
            started = time.perf_counter()
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._demo()
            elif parsed.path == "/v1/healthz":
                self._health()
            elif parsed.path == "/v1/ask":
                self._ask(parsed, started)
            else:
                self._error("NOT_FOUND", 404, "unknown route; see /v1/healthz")

        def _ask(self, parsed, started: float) -> None:
            token = self.headers.get("Authorization", "")
            if state.settings.api_token and token != f"Bearer {state.settings.api_token}":
                self._error("AUTH_REQUIRED", 401, "missing or wrong bearer token")
                return
            params = parse_qs(parsed.query)
            query = (params.get("q", [""])[0]).strip()
            tenant = self.headers.get("X-Tenant", state.settings.default_tenant)
            try:
                answer = answer_query(
                    state.index, query, tenant_id=tenant, settings=state.settings
                )
            except InputError as error:
                self._error("INPUT_INVALID", 400, str(error))
                return
            except AtlasError as error:  # never leak internals, always a code
                self._error("SERVER_ERROR", 500, error.__class__.__name__)
                return
            payload = {
                "query": answer.query,
                "text": answer.text,
                "refused": answer.refused,
                "confidence": answer.confidence,
                "citations": [
                    {
                        "doc_id": c.doc_id,
                        "chunk_id": c.chunk_id,
                        "title": c.title,
                        "section": c.section,
                        "snippet": c.snippet,
                    }
                    for c in answer.citations
                ],
                "mode": answer.mode,
                "degraded": answer.degraded,
                "trace_id": answer.trace_id,
                "timings": {
                    **answer.timings_ms,
                    "serialize_ms": round((time.perf_counter() - started) * 1000.0, 3)
                    - sum(answer.timings_ms.values()),
                    "total_ms": round((time.perf_counter() - started) * 1000.0, 3),
                },
            }
            self._json(200, payload)

        def _health(self) -> None:
            self._json(200, {"status": "ok", "tenants_served": len(state.index._views)})

        def _demo(self) -> None:
            if not DEMO_PAGE.exists():
                self._error("NOT_FOUND", 404, "demo page missing from web/demo.html")
                return
            body = DEMO_PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, code: str, status: int, message: str) -> None:
            self._json(status, {"error": {"code": code, "message": message}})

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            # NFR-11: the request line carries the user's question, so it is redacted here
            print(redact(f"[atlas] {self.client_address[0]} {fmt % args}"))

    return AtlasHandler


# The stdlib default listen backlog is 5, which drops a burst of connections outright.
# The M10 load curve measured that as 7 failures at 50 users, so the queue is sized for
# the operating point the project claims instead of leaving a socket default in charge.
LISTEN_BACKLOG = 128


def make_server(address: tuple[str, int], state: ServerState) -> ThreadingHTTPServer:
    """One constructor for the production server and the bench harness, so they match."""
    server = ThreadingHTTPServer(address, make_handler(state))
    server.request_queue_size = LISTEN_BACKLOG
    return server


def serve(db: str | None = None, host: str | None = None, port: int | None = None) -> int:
    """Blocking serve loop; SIGINT/interrupt stops it (single-node ops, no daemon)."""
    db_path = db or os.environ.get("ATLAS_DB", SETTINGS.default_db_path)
    state = ServerState(db_path)
    address = (host or SETTINGS.serve_host, port or SETTINGS.serve_port)
    server = make_server(address, state)
    print(f"[atlas] serving {db_path} on http://{address[0]}:{address[1]} "
          f"(auth {'on' if state.settings.api_token else 'off: set ATLAS_API_TOKEN'})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[atlas] shutting down")
    finally:
        state.store.close()
        server.server_close()
    return 0
