"""Fail when any file under src/ exceeds 200 lines (policy: ATL-EDD-001 s.5).

This is the mechanical enforcement of the project's size ceiling: if a file goes
over 200 lines, the fix is splitting a responsibility, never compressing logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

LIMIT = 200
SRC = Path(__file__).resolve().parents[1] / "src"


def main() -> int:
    if not SRC.exists():
        print("src/ not present yet - nothing to check (M1)")
        return 0

    files = sorted(SRC.rglob("*.py"))
    over: list[tuple[Path, int]] = []
    print(f"{'file':40} {'lines':>6} {'policy':>7}")
    for path in files:
        n = len(path.read_text(encoding="utf-8").splitlines())
        print(f"{str(path.relative_to(SRC.parent)):40} {n:>6} {'ok' if n <= LIMIT else 'OVER'}")
        if n > LIMIT:
            over.append((path, n))

    if over:
        print("\nFAILED - files above the 200-line ceiling; split the responsibility:")
        for path, n in over:
            print(f"  - {path.relative_to(SRC.parent)}: {n} lines")
        return 1
    if not files:
        print("no source files yet")
        return 0
    print(f"\n{len(files)} files ok ({LIMIT}-line ceiling)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
