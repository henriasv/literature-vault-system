#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Fetch the full CrossRef record for a DOI and print it as JSON.

Used by the viewer's "Details" expander on each CrossRef search
candidate — `crossref_search.py` returns trimmed summaries (title,
first author, year, score) and this script returns the full record
so the user can inspect everything CrossRef has on the paper before
committing to file it.

Falls back to DataCite via `doi2bib.fetch_metadata` so preprint DOIs
that miss CrossRef still produce a record.

Output: JSON object on stdout. Empty object `{}` on miss. Exit 0 on
success (with or without data), 1 only on invocation errors.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from doi2bib import fetch_metadata  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--doi", required=True)
    args = p.parse_args()
    msg = fetch_metadata(args.doi)
    print(json.dumps(msg or {}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
