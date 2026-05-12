#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pypdf>=5.0"]
# ///
"""Print the text of one PDF page (default: page 0).

Usage:
    pdf_page_text.py <pdf>           # page 0
    pdf_page_text.py <pdf> 1         # specific page (0-indexed)

Use this when the agent needs the raw first-page text to audit the
abstract that file_paper.py wrote, or to extract one if the
deterministic pass returned empty.
"""

import sys
from pathlib import Path

from pypdf import PdfReader


def main() -> int:
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("usage: pdf_page_text.py <pdf> [page]", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    page = int(sys.argv[2]) if len(sys.argv) == 3 else 0
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 1
    try:
        reader = PdfReader(str(path))
    except Exception as e:
        print(f"failed to open: {e}", file=sys.stderr)
        return 1
    if page < 0 or page >= len(reader.pages):
        print(f"page {page} out of range (0..{len(reader.pages) - 1})", file=sys.stderr)
        return 1
    text = reader.pages[page].extract_text() or ""
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
