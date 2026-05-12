#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pypdf>=5.0"]
# ///
"""Extract the first DOI and arXiv ID from a PDF.

Strategy (cheap → expensive):
  1. PDF /Info and XMP metadata (some publishers put the DOI there).
  2. Text from the first few pages via pypdf.
  3. Raw-bytes regex (catches DOIs in uncompressed streams).

Output: JSON {"doi": "...", "arxiv_id": "...", "source": "metadata|text|bytes|none"}.
Either id may be null. The caller falls back to a CrossRef title/author
search when both are null.
"""

import json
import re
import sys
from pathlib import Path

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
ARXIV_NEW = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})", re.IGNORECASE)
ARXIV_OLD = re.compile(r"arXiv:\s*([a-z\-]+/\d{7})", re.IGNORECASE)

# Trim trailing punctuation that the DOI regex commonly absorbs.
DOI_TRAILING = ".,;)>]}'\""


def _find_doi(text: str) -> str | None:
    m = DOI_RE.search(text)
    if not m:
        return None
    return m.group(0).rstrip(DOI_TRAILING)


def _find_arxiv(text: str) -> str | None:
    m = ARXIV_NEW.search(text) or ARXIV_OLD.search(text)
    return m.group(1) if m else None


def _scan_metadata(reader) -> tuple[str | None, str | None]:
    """Look at /Info dict and XMP metadata for embedded identifiers."""
    blob_parts: list[str] = []
    info = getattr(reader, "metadata", None)
    if info:
        for v in info.values():
            if isinstance(v, str):
                blob_parts.append(v)
    try:
        xmp = reader.xmp_metadata
        if xmp is not None:
            raw = getattr(xmp, "rdf_root", None)
            if raw is not None:
                blob_parts.append(raw.toxml())
    except Exception:
        pass
    blob = " ".join(blob_parts)
    return _find_doi(blob), _find_arxiv(blob)


def _scan_text(reader, max_pages: int = 3) -> tuple[str | None, str | None]:
    """Pull text from the first few pages and scan."""
    pages = reader.pages
    chunks: list[str] = []
    for i in range(min(max_pages, len(pages))):
        try:
            chunks.append(pages[i].extract_text() or "")
        except Exception:
            continue
    text = "\n".join(chunks)
    return _find_doi(text), _find_arxiv(text)


def _scan_bytes(path: Path) -> tuple[str | None, str | None]:
    data = path.read_bytes().decode("latin-1", errors="replace")
    return _find_doi(data), _find_arxiv(data)


def extract(path: Path) -> dict:
    from pypdf import PdfReader

    reader = PdfReader(str(path))

    doi, arxiv = _scan_metadata(reader)
    if doi or arxiv:
        return {"doi": doi, "arxiv_id": arxiv, "source": "metadata"}

    doi, arxiv = _scan_text(reader)
    if doi or arxiv:
        return {"doi": doi, "arxiv_id": arxiv, "source": "text"}

    doi, arxiv = _scan_bytes(path)
    if doi or arxiv:
        return {"doi": doi, "arxiv_id": arxiv, "source": "bytes"}

    return {"doi": None, "arxiv_id": None, "source": "none"}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: extract_ids.py <pdf>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 1
    print(json.dumps(extract(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
