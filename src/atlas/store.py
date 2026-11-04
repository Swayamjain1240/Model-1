"""SQLite persistence and tenancy (ATL-SwDD-001 s.2).

The store owns rows, not ranking opinions: it hashes content with BLAKE2b
(never Python's salted hash()), replaces changed documents wholesale, and
physically scopes every read by tenant_id (FR-01..FR-03, FR-06, FR-08).
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import SETTINGS, Settings
from .interfaces import TenantError
from .text.chunk import chunk_document

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    tenant_id    TEXT    NOT NULL,
    doc_id       TEXT    NOT NULL,
    title        TEXT    NOT NULL,
    content_hash TEXT    NOT NULL,
    PRIMARY KEY (tenant_id, title)
);
CREATE TABLE IF NOT EXISTS chunks (
    tenant_id TEXT NOT NULL,
    chunk_id  TEXT NOT NULL,
    doc_id    TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    title     TEXT NOT NULL,
    section   TEXT NOT NULL,
    text      TEXT NOT NULL,
    PRIMARY KEY (tenant_id, chunk_id)
);
CREATE INDEX IF NOT EXISTS idx_chunks_tenant ON chunks (tenant_id);
"""


def blake2b_hex(value: str, *, length: int = 12) -> str:
    """Stable content hash: identical runs produce identical ids (ATL-TDD-001 s.11)."""
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=16).hexdigest()
    return digest[:length]


@dataclass(frozen=True)
class StoredChunk:
    """A chunk as persisted: identity, provenance, and citable text."""

    chunk_id: str
    doc_id: str
    title: str
    section: str
    text: str
    seq: int


class Store:
    """The only module that touches SQLite; every method is tenant-scoped by hand."""

    def __init__(self, path: str | Path, *, settings: Settings = SETTINGS) -> None:
        self._settings = settings
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def upsert_document(self, *, tenant_id: str, path: Path) -> int:
        """Ingest one markdown file; unchanged content no-ops, changed replaces (FR-02, FR-03)."""
        if not tenant_id:
            raise TenantError("empty tenant_id")
        raw = path.read_text(encoding="utf-8")
        content_hash = blake2b_hex(raw, length=32)
        title, _ = _title_of(raw, path.stem)
        prior = self._conn.execute(
            "SELECT doc_id, content_hash FROM documents WHERE tenant_id = ? AND title = ?",
            (tenant_id, title),
        ).fetchone()
        if prior is not None and prior[1] == content_hash:
            return 0
        # the document id is the readable file stem: stable, and exactly what the
        # frozen golden set labels reference; chunk ids below stay BLAKE2b-derived
        doc_id = prior[0] if prior is not None else path.stem
        self._conn.execute(
            "DELETE FROM chunks WHERE tenant_id = ? AND doc_id = ?", (tenant_id, doc_id)
        )
        chunks = chunk_document(raw, settings=self._settings)
        for seq, chunk in enumerate(chunks):
            self._conn.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    tenant_id,
                    _chunk_id(tenant_id, doc_id, seq),
                    doc_id,
                    seq,
                    title,
                    chunk.section,
                    chunk.text,
                ),
            )
        self._conn.execute(
            "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?)",
            (tenant_id, doc_id, title, content_hash),
        )
        self._conn.commit()
        return len(chunks)

    def list_chunks(self, *, tenant_id: str) -> list[StoredChunk]:
        """Every chunk of one tenant in stable order; other tenants are unreachable here."""
        if not tenant_id:
            raise TenantError("empty tenant_id")
        rows = self._conn.execute(
            "SELECT chunk_id, doc_id, title, section, text, seq FROM chunks "
            "WHERE tenant_id = ? ORDER BY seq, chunk_id",
            (tenant_id,),
        ).fetchall()
        return [StoredChunk(*row) for row in rows]

    def stats(self, *, tenant_id: str) -> dict[str, int]:
        """{documents: n, chunks: n}; the ingest acceptance check (FR-01) reads this."""
        if not tenant_id:
            raise TenantError("empty tenant_id")
        documents = self._conn.execute(
            "SELECT COUNT(*) FROM documents WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()[0]
        chunks = self._conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()[0]
        return {"documents": documents, "chunks": chunks}


def _chunk_id(tenant_id: str, doc_id: str, seq: int) -> str:
    """Id is derived from immutable identity, so a rebuild cannot renumber a citation."""
    return blake2b_hex(f"{tenant_id}\0{doc_id}\0{seq}", length=16)


def _title_of(raw: str, fallback: str) -> tuple[str, str]:
    """Title = first H1 heading, else the file stem with dashes for spaces."""
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip(), fallback
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip(), fallback
    return fallback.replace("-", " ").replace("_", " ").strip(), fallback
