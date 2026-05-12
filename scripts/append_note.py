#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Append a timestamped entry under '## Notes' in PaperNotes/{citekey}.md.

Usage:
    echo "body" | append_note.py --citekey foo2024-bar
    append_note.py --citekey foo2024-bar --body "body"
"""

import argparse
import datetime as dt
import os
import sys
from pathlib import Path


VAULT_ROOT = Path(
    os.environ.get("LITERATURE_VAULT")
    or Path(__file__).absolute().parent.parent
)


def append(citekey: str, body: str) -> Path:
    note_path = VAULT_ROOT / "PaperNotes" / f"{citekey}.md"
    if not note_path.is_file():
        raise SystemExit(f"note not found: {note_path}")
    text = note_path.read_text()
    if "## Notes" not in text:
        raise SystemExit(f"no '## Notes' section in {note_path}")
    timestamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    addition = f"\n### {timestamp}\n{body.rstrip()}\n"
    new = text.rstrip() + addition
    tmp = note_path.with_suffix(".md.tmp")
    tmp.write_text(new)
    os.replace(tmp, note_path)
    return note_path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--citekey", required=True)
    p.add_argument("--body", help="body text; if omitted, read stdin")
    args = p.parse_args()
    body = args.body if args.body is not None else sys.stdin.read()
    if not body.strip():
        print("empty body; nothing to append", file=sys.stderr)
        return 1
    out = append(args.citekey, body)
    print(out, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
