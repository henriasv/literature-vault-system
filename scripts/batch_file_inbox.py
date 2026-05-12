#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pypdf>=5.0",
# ]
# ///
"""Batch-file all PDFs found under a directory (default: Inbox/).

For each PDF:
  1. Extract DOI from page 0 text.
  2. Run file_paper.py logic (CrossRef lookup, filing).

Output: summary of results.
"""

import re
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from file_paper import file_paper, sha256_file, load_index  # noqa: E402

VAULT_ROOT = Path(__file__).resolve().parent.parent
_DOI_RE = re.compile(r'10\.\d{4,}/[^\s\]}>"\',;]+', re.IGNORECASE)


def extract_doi_from_pdf(pdf_path: Path) -> str | None:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        for page in reader.pages[:2]:
            text = page.extract_text() or ""
            m = _DOI_RE.search(text)
            if m:
                doi = m.group(0).rstrip(".")
                return doi
    except Exception:
        pass
    return None


def main():
    inbox = VAULT_ROOT / "Inbox"
    pdfs = sorted(inbox.rglob("*.pdf"))
    print(f"Found {len(pdfs)} PDFs\n")

    results = {"filed": [], "duplicate": [], "no_doi": [], "error": []}

    for pdf in pdfs:
        rel = pdf.relative_to(VAULT_ROOT)
        doi = extract_doi_from_pdf(pdf)
        if not doi:
            print(f"[NO DOI] {rel}")
            results["no_doi"].append(str(rel))
            continue

        try:
            result = file_paper(pdf, doi, arxiv_id=None, in_place=False)
        except SystemExit as e:
            msg = str(e)
            if "duplicate" in msg.lower():
                print(f"[DUP   ] {rel}  ({doi})")
                results["duplicate"].append(str(rel))
            else:
                print(f"[ERROR ] {rel}  ({doi})  {msg}")
                results["error"].append(f"{rel}: {msg}")
            continue

        if result.get("duplicate"):
            print(f"[DUP   ] {rel}  → {result['existing_citekey']}")
            results["duplicate"].append(str(rel))
        else:
            print(f"[OK    ] {rel}  → {result['citekey']}")
            results["filed"].append(result["citekey"])

    print(f"\n=== Summary ===")
    print(f"  Filed:      {len(results['filed'])}")
    print(f"  Duplicates: {len(results['duplicate'])}")
    print(f"  No DOI:     {len(results['no_doi'])}")
    print(f"  Errors:     {len(results['error'])}")

    if results["no_doi"]:
        print(f"\nNo DOI found:")
        for p in results["no_doi"]:
            print(f"  {p}")

    if results["error"]:
        print(f"\nErrors:")
        for e in results["error"]:
            print(f"  {e}")

    return results


if __name__ == "__main__":
    main()
