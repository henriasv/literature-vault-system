#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Look up an identifier in index.json. Read-only.

Usage:
    check_dup.py --sha256 <hex>
    check_dup.py --doi <doi>
    check_dup.py --citekey <key>
    check_dup.py --arxiv <id>

Multiple flags can be combined; first match wins (sha256 > doi > arxiv > citekey).

Output: JSON {"citekey": "...", "matched_field": "..."} on hit,
        {"citekey": null} on miss. Always exits 0.
"""

import argparse
import json
import sys
from pathlib import Path


VAULT_ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = VAULT_ROOT / "index.json"


def load_index() -> dict:
    if not INDEX_PATH.is_file():
        return {"by_hash": {}, "by_doi": {}, "by_arxiv": {}}
    idx = json.loads(INDEX_PATH.read_text())
    idx.setdefault("by_hash", {})
    idx.setdefault("by_doi", {})
    idx.setdefault("by_arxiv", {})
    return idx


def lookup(sha256: str | None, doi: str | None, arxiv: str | None,
           citekey: str | None) -> dict:
    idx = load_index()
    if sha256:
        ck = idx["by_hash"].get(sha256.lower())
        if ck:
            return {"citekey": ck, "matched_field": "sha256"}
    if doi:
        ck = idx["by_doi"].get(doi.lower())
        if ck:
            return {"citekey": ck, "matched_field": "doi"}
    if arxiv:
        ck = idx["by_arxiv"].get(arxiv.lower())
        if ck:
            return {"citekey": ck, "matched_field": "arxiv"}
    if citekey:
        all_citekeys = (
            set(idx["by_hash"].values())
            | set(idx["by_doi"].values())
            | set(idx["by_arxiv"].values())
        )
        if citekey in all_citekeys:
            return {"citekey": citekey, "matched_field": "citekey"}
    return {"citekey": None}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sha256")
    p.add_argument("--doi")
    p.add_argument("--citekey")
    p.add_argument("--arxiv")
    args = p.parse_args()
    if not any([args.sha256, args.doi, args.citekey, args.arxiv]):
        p.print_help(sys.stderr)
        return 2
    print(json.dumps(lookup(args.sha256, args.doi, args.arxiv, args.citekey)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
