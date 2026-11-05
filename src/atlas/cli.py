"""Operator interface (ATL-SwDD-001 s.2): ingest corpus, ask, report stats.

The only module allowed to print - stdout here is the product, not a debug
channel (ATL-SwDD-001 s.8 forbids prints elsewhere).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .answer import answer_query
from .config import SETTINGS
from .retrieval import HybridIndex
from .store import Store


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "ingest":
        return _ingest(args)
    if args.command == "ask":
        return _ask(args)
    return _stats(args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas", description=__doc__)
    parser.add_argument("--db", default=SETTINGS.default_db_path, help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="ingest markdown files")
    ingest.add_argument("path", type=Path, help="a markdown file or a directory of them")
    ingest.add_argument("--tenant", default=SETTINGS.default_tenant)
    ask = sub.add_parser("ask", help="one cited answer, or a refusal at the gate")
    ask.add_argument("query")
    ask.add_argument("--tenant", default=SETTINGS.default_tenant)
    ask.add_argument("-k", type=int, default=5)
    ask.add_argument("--mode", default="hybrid", choices=("sparse", "dense", "hybrid"))
    ask.add_argument("--raw", action="store_true", help="list retrieved passages instead")
    stats = sub.add_parser("stats", help="document and chunk counts")
    stats.add_argument("--tenant", default=SETTINGS.default_tenant)
    return parser


def _ingest(args: argparse.Namespace) -> int:
    sources = _markdown_files(args.path)
    if not sources:
        print(f"no markdown files found under {args.path}", file=sys.stderr)
        return 1
    store = Store(args.db)
    try:
        written = sum(
            store.upsert_document(tenant_id=args.tenant, path=path) for path in sources
        )
    finally:
        store.close()
    print(f"ingested {written} new chunks from {len(sources)} files "
          f"into tenant {args.tenant!r}")
    return 0


def _markdown_files(path: Path) -> list[Path]:
    files = sorted(path.iterdir()) if path.is_dir() else [path]
    return [item for item in files if item.is_file() and item.suffix in (".md", ".markdown")]


def _ask(args: argparse.Namespace) -> int:
    store = Store(args.db)
    try:
        if args.raw:
            _ask_raw(args, store)
            return 0
        answer = answer_query(
            HybridIndex(store), args.query, tenant_id=args.tenant, mode=args.mode
        )
    finally:
        store.close()
    if answer.refused:
        print("REFUSED - no grounded answer; citations withheld "
              f"(confidence={answer.confidence:.2f}, theta={SETTINGS.confidence_theta:.2f})")
        return 0
    print(answer.text)
    for citation in answer.citations:
        print(f"\n[citation] {citation.title} - {citation.section} ({citation.doc_id})")
    print(f"confidence={answer.confidence:.2f} mode={answer.mode} "
          f"timings={answer.timings_ms}")
    return 0


def _ask_raw(args: argparse.Namespace, store: Store) -> None:
    """Passage listing mode: retrieval debugging, unchanged from M2/M3 behaviour."""
    index = HybridIndex(store)
    passages = index.search(args.query, tenant_id=args.tenant, k=args.k, mode=args.mode)
    if not passages:
        print("no passages")
        return
    print(f"mode={args.mode} k={args.k} tenant={args.tenant!r}\n")
    for passage in passages:
        print(f"[{passage.rank}] score={passage.score:+.4f} "
              f"{passage.title} -- {passage.section}")
        snippet = " ".join(passage.text.split())[:120]
        print(f"      {snippet}{'...' if len(passage.text) > 120 else ''}")


def _stats(args: argparse.Namespace) -> int:
    store = Store(args.db)
    try:
        counts = store.stats(tenant_id=args.tenant)
    finally:
        store.close()
    print(f"tenant={args.tenant!r} documents={counts['documents']} chunks={counts['chunks']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
