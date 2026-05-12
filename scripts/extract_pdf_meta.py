#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pypdf>=5.0"]
# ///
"""Best-guess metadata extraction for a PDF that has no DOI/arXiv.

Used by the viewer's manual-BibTeX entry form: when the user opens
the form for a fresh PDF (typically a draft, preprint, or report),
we pre-fill the fields from the PDF's own metadata instead of asking
them to type everything from scratch.

Strategy (in order; each fills only fields not already set):
  1. XMP metadata — DC.title, DC.creator, DC.date, DC.publisher.
     Most reliable for properly-tagged academic PDFs.
  2. /Info dict — Title, Author, Subject, Keywords, CreationDate.
     LaTeX-generated PDFs typically have these.
  3. First-page text heuristics — title is the longest line near the
     top; authors are the line(s) directly under it; year is any
     20XX number in the first 200 chars (copyright / date stamps).

Output: JSON object on stdout. Empty/null when no metadata could be
extracted at all. The viewer renders a pre-filled BibTeX template
using these fields; the user reviews and edits before saving.

Usage:
    extract_pdf_meta.py <pdf-path>
    extract_pdf_meta.py --format bibtex <pdf-path>    # also returns
                                                       # a synthesized
                                                       # @misc{...} entry
"""

import argparse
import json
import re
import sys
from pathlib import Path

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
ARXIV_NEW = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})", re.IGNORECASE)
ARXIV_OLD = re.compile(r"arXiv:\s*([a-z\-]+/\d{7})", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _trim(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _split_authors(raw: str) -> list[dict]:
    """Split a free-form author string into [{family, given}, …].

    Handles: "Smith, J. and Doe, J.", "J. Smith, J. Doe", "Smith J,
    Doe J", "Jane Smith; John Doe". Best-effort; the user will edit."""
    if not raw:
        return []
    # Normalise separators.
    raw = re.sub(r"\s+and\s+", ";", raw, flags=re.IGNORECASE)
    # Heuristic: if there are commas AND no semicolons, the commas
    # likely separate author last/first within a single entry — but
    # only if it's a single author (no commas alongside "and"). To
    # disambiguate, count: more commas than alpha-only "words" ÷ 2
    # suggests "Last, First" style, otherwise comma is a separator.
    if ";" not in raw and "," in raw:
        # If pattern looks like "Last, First, Last, First", treat
        # comma pairs as authors. Heuristic: even number of commas
        # roughly equal to 2N → N authors.
        commas = raw.count(",")
        words = len(re.findall(r"[A-Za-zÀ-ÿ]+", raw))
        if commas >= 2 and words / max(1, commas + 1) <= 3:
            # Treat as "Last, First, Last, First" → pair them.
            parts = [p.strip() for p in raw.split(",")]
            out: list[dict] = []
            for i in range(0, len(parts) - 1, 2):
                family = parts[i]
                given = parts[i + 1] if i + 1 < len(parts) else ""
                if family or given:
                    out.append({"family": family, "given": given})
            return out
        # Fall through: comma is "Family, Given" within one entry.
        if "," in raw:
            family, given = raw.split(",", 1)
            return [{"family": _trim(family), "given": _trim(given)}]
    parts = [p for p in re.split(r";|\band\b", raw, flags=re.IGNORECASE) if p.strip()]
    out: list[dict] = []
    for p in parts:
        p = p.strip()
        if "," in p:
            family, given = p.split(",", 1)
            out.append({"family": _trim(family), "given": _trim(given)})
        else:
            toks = p.split()
            if len(toks) == 1:
                out.append({"family": toks[0]})
            elif toks:
                out.append({"family": toks[-1], "given": " ".join(toks[:-1])})
    return out


def _xmp(reader) -> dict:
    """Pull title/creator/date/publisher from XMP metadata if present."""
    out: dict = {}
    try:
        xmp = reader.xmp_metadata
    except Exception:
        return out
    if xmp is None:
        return out
    # pypdf exposes these as properties.
    try:
        if xmp.dc_title:
            # dc_title is a dict {lang: title}; take the first value.
            vals = list(xmp.dc_title.values()) if isinstance(xmp.dc_title, dict) else [xmp.dc_title]
            if vals and vals[0]:
                out["title"] = _trim(str(vals[0]))
    except Exception:
        pass
    try:
        creators = xmp.dc_creator or []
        if creators:
            joined = "; ".join(str(c) for c in creators if c)
            authors = _split_authors(joined)
            if authors:
                out["authors"] = authors
    except Exception:
        pass
    try:
        if xmp.dc_date:
            dates = xmp.dc_date if isinstance(xmp.dc_date, list) else [xmp.dc_date]
            for d in dates:
                m = YEAR_RE.search(str(d))
                if m:
                    out["year"] = int(m.group(0))
                    break
    except Exception:
        pass
    try:
        pub = xmp.dc_publisher or []
        if pub:
            out["publisher"] = _trim(str(pub[0]))
    except Exception:
        pass
    return out


def _info(reader) -> dict:
    """Pull Title/Author/Keywords/CreationDate from the /Info dict."""
    out: dict = {}
    info = getattr(reader, "metadata", None)
    if not info:
        return out
    title = info.get("/Title")
    if title:
        out["title"] = _trim(str(title))
    author = info.get("/Author")
    if author:
        authors = _split_authors(str(author))
        if authors:
            out["authors"] = authors
    keywords = info.get("/Keywords")
    if keywords:
        kw = str(keywords)
        # Many publishers stash the DOI in /Keywords.
        m = DOI_RE.search(kw)
        if m:
            out["doi"] = m.group(0).rstrip(".,;)>")
    created = info.get("/CreationDate") or info.get("/ModDate")
    if created:
        m = YEAR_RE.search(str(created))
        if m:
            out["year"] = int(m.group(0))
    return out


def _first_pages_text(reader, n: int = 2) -> str:
    chunks: list[str] = []
    for i in range(min(n, len(reader.pages))):
        try:
            chunks.append(reader.pages[i].extract_text() or "")
        except Exception:
            continue
    return "\n".join(chunks)


def _heuristics_from_text(text: str) -> dict:
    """Title from longest line near the top; authors from the line
    after; year from the first 4-digit 19xx/20xx; DOI/arXiv from the
    full text."""
    out: dict = {}
    if not text:
        return out
    # DOI / arXiv.
    m = DOI_RE.search(text)
    if m:
        out["doi"] = m.group(0).rstrip(".,;)>")
    m = ARXIV_NEW.search(text) or ARXIV_OLD.search(text)
    if m:
        out["arxiv"] = m.group(1)

    # Year from the top of the page (copyright lines, date stamps).
    m = YEAR_RE.search(text[:600])
    if m:
        out["year"] = int(m.group(0))

    # Title: the longest non-trivial line among the first 12 lines.
    # Skip lines that look like page headers / metadata.
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    candidates: list[tuple[int, str]] = []
    for idx, ln in enumerate(lines[:12]):
        if len(ln) < 12 or len(ln) > 240:
            continue
        # Skip obvious non-title lines.
        if re.match(r"^(doi|arxiv|published|received|accepted|copyright|©|the journal|nature|science)\b", ln, re.IGNORECASE):
            continue
        # Drop all-caps short headers.
        if ln.isupper() and len(ln) < 40:
            continue
        candidates.append((len(ln), ln))
    if candidates:
        # Prefer the earliest long line over the absolute longest, but
        # weight by length to avoid picking a one-word heading.
        candidates.sort(key=lambda t: -t[0])
        out.setdefault("title", _trim(candidates[0][1]))
    return out


def extract(path: Path) -> dict:
    from pypdf import PdfReader
    reader = PdfReader(str(path))

    result: dict = {
        "title": "",
        "authors": [],
        "year": None,
        "journal": "",
        "publisher": "",
        "doi": "",
        "arxiv": "",
        "abstract": "",
        "_sources": {},
    }

    def fill(source: str, fields: dict) -> None:
        for k, v in fields.items():
            if not v:
                continue
            if k == "authors":
                if not result["authors"]:
                    result["authors"] = v
                    result["_sources"]["authors"] = source
                continue
            if not result.get(k):
                result[k] = v
                result["_sources"][k] = source

    fill("xmp", _xmp(reader))
    fill("info", _info(reader))
    fill("text", _heuristics_from_text(_first_pages_text(reader)))

    return result


def to_bibtex(meta: dict) -> str:
    """Render the extracted metadata as a `@misc{…}` entry suitable for
    the viewer's manual-entry textarea. Keys are filled with the
    extracted values; everything else stays as a sensible placeholder
    so the user knows what to type."""
    title = (meta.get("title") or "Title").replace("{", "").replace("}", "")
    year = meta.get("year") or 2026
    authors_list = meta.get("authors") or []
    author_strs = []
    for a in authors_list:
        fam = a.get("family", "")
        giv = a.get("given", "")
        if fam and giv:
            author_strs.append(f"{fam}, {giv}")
        elif fam or giv:
            author_strs.append(fam or giv)
    if not author_strs:
        author_strs = ["Lastname, Firstname"]
    authors_field = " and ".join(author_strs)
    doi = meta.get("doi") or ""
    arxiv = meta.get("arxiv") or ""
    journal = meta.get("journal") or meta.get("publisher") or ""

    entry_type = "article" if journal else "misc"
    lines = [f"@{entry_type}{{CITEKEY_AUTO_FROM_FIELDS,"]
    lines.append(f"  author = {{{authors_field}}},")
    lines.append(f"  title  = {{{{{title}}}}},")
    if journal:
        lines.append(f"  journal = {{{journal}}},")
    lines.append(f"  year   = {{{year}}},")
    if doi:
        lines.append(f"  doi    = {{{doi}}},")
    if arxiv:
        lines.append(f"  eprint = {{{arxiv}}},")
        lines.append(f"  archivePrefix = {{arXiv}},")
    lines.append("  % citekey above is ignored — minted from author + year + title/DOI on save")
    lines.append("  % fields auto-filled from PDF — review and edit before saving")
    lines.append("}")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("pdf", type=Path)
    p.add_argument("--format", choices=("json", "bibtex"), default="json",
                   help="Output format (default: json with metadata fields).")
    args = p.parse_args()
    if not args.pdf.is_file():
        print(f"not a file: {args.pdf}", file=sys.stderr)
        return 1
    try:
        meta = extract(args.pdf)
    except Exception as e:
        print(f"extract failed: {e}", file=sys.stderr)
        return 1
    if args.format == "bibtex":
        print(to_bibtex(meta))
    else:
        print(json.dumps(meta, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
