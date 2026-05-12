#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Concatenate Bibfiles/*.bib into a single library.bib at vault root.

Sorted by filename for stable diffs. Atomic write. Idempotent.
"""

import os
import sys
from pathlib import Path


VAULT_ROOT = Path(
    os.environ.get("LITERATURE_VAULT")
    or Path(__file__).absolute().parent.parent
)


def build() -> int:
    bib_dir = VAULT_ROOT / "Bibfiles"
    out_path = VAULT_ROOT / "library.bib"
    entries = sorted(bib_dir.glob("*.bib"))
    body = "\n\n".join(p.read_text().rstrip() for p in entries)
    if body:
        body += "\n"
    tmp = out_path.with_suffix(".bib.tmp")
    tmp.write_text(body)
    os.replace(tmp, out_path)
    return len(entries)


def main() -> int:
    n = build()
    print(f"library.bib: {n} entries", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
