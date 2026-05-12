#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pypdf>=5.0",
# ]
# ///
"""Atomic 'file this paper' transaction.

Inputs: --pdf <inbox path> --doi <doi> [--arxiv <id>] [--in-place]

Steps:
  1. Verify PDF exists, sha256 it.
  2. Dup check against index.json (sha256, doi, arxiv).
  3. Fetch CrossRef metadata, compute citekey + BibTeX.
  4. Late dup check by citekey.
  5. Write Bibfiles/{citekey}.bib + PaperNotes/{citekey}.md skeleton.
  6. Move PDF: Inbox/... → PDFs/{citekey}.pdf
     (with --in-place: PDF must already be at PDFs/{citekey}.pdf; no move).
  7. Update index.json.
  8. Regenerate library.bib.

On any failure after step 5, attempt rollback (delete writes, move PDF back).
--in-place is for backfilling papers whose PDF is already at the target path.

Output (stdout): JSON. On dup: {duplicate: true, matched_field, existing_citekey}.
On success: {duplicate: false, citekey, pdf_path, note_path, bib_path, bibtex}.
Exit 0 on success, 1 on duplicate, >1 on error.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Local imports (sibling scripts)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from doi2bib import fetch_metadata, fetch_openalex_abstract, make_bibtex, strip_html  # noqa: E402
from build_library_bib import build as build_library_bib  # noqa: E402

VAULT_ROOT = Path(
    os.environ.get("LITERATURE_VAULT")
    or Path(__file__).absolute().parent.parent
)
INDEX_PATH = VAULT_ROOT / "index.json"
BIBFILES = VAULT_ROOT / "Bibfiles"
PAPERNOTES = VAULT_ROOT / "PaperNotes"
PDFS = VAULT_ROOT / "PDFs"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def load_index() -> dict:
    if not INDEX_PATH.is_file():
        return {"by_hash": {}, "by_doi": {}, "by_arxiv": {}}
    idx = json.loads(INDEX_PATH.read_text())
    idx.setdefault("by_hash", {})
    idx.setdefault("by_doi", {})
    idx.setdefault("by_arxiv", {})
    return idx


def write_index(idx: dict) -> None:
    tmp = INDEX_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(idx, indent=2, sort_keys=True))
    os.replace(tmp, INDEX_PATH)


def atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


_INTRO_SIGNALS = re.compile(
    r"^(introduction\b|background\b|over the past|in recent (year|decade)|"
    r"during the past|for (decades|many year|several decade)|"
    r"the (study of|field of|past decade)|"
    r"(atomic|molecular|quantum|classical|computational)-scale sim)",
    re.IGNORECASE,
)

_POST_TITLE_NOISE = re.compile(
    r"edited by|received:|accepted:|keywords?:|subject area|"
    r"author for corr|department\b|universit|0000-\d|@|"
    r"\b(open access|research article)\b",
    re.IGNORECASE,
)

# Author name lines: Unicode thin-space used in Nature PDFs between name and
# affiliation superscripts, digit,digit patterns (e.g. "1,4"), "ID" badge,
# or spaced-out letters from PDF kerning artifacts (e.g. "I z a b e l a").
_AUTHOR_LINE = re.compile(
    r" | |﻿|\d\s{0,2},\s{0,2}\d|\bID\b|(?:[A-Za-z] ){3}"
)

_LIGATURES = str.maketrans({"ﬁ": "fi", "ﬀ": "ff", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"})


def _norm_text(s: str) -> str:
    return re.sub(r"\W+", " ", s.translate(_LIGATURES)).lower().strip()


def extract_abstract_from_pdf(pdf_path: Path, title: str = "") -> str:
    """Extract abstract from page 0 as a fallback when CrossRef lacks one.

    Uses the CrossRef title as an anchor: locates it via a sliding-window match
    over joined adjacent lines, skips author/metadata lines that follow, then
    collects the first prose paragraph up to an intro-signal or 1500-char cap.
    Returns "" on failure or implausible result.
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        if not reader.pages:
            return ""
        raw = reader.pages[0].extract_text() or ""
    except Exception:
        return ""

    raw = re.sub(r"-\s*\n\s*", "", raw)
    lines = [ln.strip() for ln in raw.splitlines()]

    # Locate the title via sliding window (handles multi-line titles)
    start_idx = 0
    if title:
        title_pfx = _norm_text(title)[:70]
        for i in range(len(lines)):
            for span in range(1, 9):
                window = _norm_text(" ".join(lines[i:i + span]))
                if title_pfx in window and "cite this article" not in window:
                    start_idx = i + span
                    break
            else:
                continue
            break

    # Skip post-title noise: authors, affiliations, editorial notes, metadata
    i = start_idx
    while i < len(lines):
        line = lines[i]
        if not line or len(line) < 10:
            i += 1
            continue
        if _POST_TITLE_NOISE.search(line) or _AUTHOR_LINE.search(line):
            i += 1
            continue
        # Short line not ending a sentence = still metadata / author block
        if len(line) < 40 and not line.endswith((".", "?", "!")):
            i += 1
            continue
        break
    start_idx = i

    # Collect abstract lines until intro signal, keyword list, or cap
    chunks: list[str] = []
    total = 0
    for line in lines[start_idx:]:
        if not line:
            if chunks:
                break  # paragraph end
            continue
        if _INTRO_SIGNALS.match(line):
            break
        if re.match(r"^[\w\s]+(\|[\w\s]+){2,}$", line):  # pipe-separated keywords
            break
        chunks.append(line)
        total += len(line)
        if total >= 1500:
            break

    text = re.sub(r"\s{2,}", " ", " ".join(chunks)).strip()
    if len(text) < 100 or "." not in text:
        return ""
    return text


def yaml_quote(s: str) -> str:
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def yaml_block(s: str, indent: str = "  ") -> str:
    lines = s.strip().splitlines() or [""]
    return "|\n" + "\n".join(f"{indent}{ln}" for ln in lines)


# Above this many authors, the YAML list becomes unreadable in Obsidian.
# We truncate the frontmatter list (keeping the canonical full list in the
# .bib file). Adjust if needed.
AUTHOR_DISPLAY_THRESHOLD = 15
AUTHOR_DISPLAY_KEEP = 5


def make_note_skeleton(meta: dict) -> str:
    fm = ["---"]
    fm.append(f"citekey: {meta['citekey']}")
    fm.append(f"title: {yaml_quote(meta['title'])}")
    authors = meta["authors"]
    fm.append("authors:")
    if len(authors) > AUTHOR_DISPLAY_THRESHOLD:
        for a in authors[:AUTHOR_DISPLAY_KEEP]:
            fm.append(f"  - {yaml_quote(a)}")
        fm.append(f"  - {yaml_quote(f'…and {len(authors) - AUTHOR_DISPLAY_KEEP} others')}")
        fm.append(f"author_count: {len(authors)}")
    else:
        for a in authors:
            fm.append(f"  - {yaml_quote(a)}")
    fm.append(f"year: {meta['year']}")
    if meta.get("journal"):
        fm.append(f"journal: {yaml_quote(meta['journal'])}")
    fm.append(f"doi: {meta['doi'] or 'null'}")
    fm.append(f"arxiv_id: {meta['arxiv_id'] or 'null'}")
    fm.append(f"added: {meta['added']}")
    fm.append("tags: []")
    fm.append(f"sha256_pdf: {meta['sha256_pdf']}")
    if meta.get("abstract"):
        fm.append(f"abstract: {yaml_block(meta['abstract'])}")
    fm.append("---")
    fm.append("")
    # The title is already in the frontmatter (and the viewer surfaces it
    # prominently in the metadata header). Don't duplicate it as a body H1.
    fm.append("## Why")
    fm.append("")
    fm.append("## Cleaned Notes")
    fm.append("")
    fm.append("## Notes")
    fm.append("")
    return "\n".join(fm)


def extract_meta(msg: dict, doi: str, arxiv_id: str | None,
                 sha256_pdf: str, citekey: str,
                 pdf_path: Path | None = None) -> dict:
    title = msg.get("title", [""])[0]
    subtitles = msg.get("subtitle", [])
    if subtitles and subtitles[0]:
        title = f"{title}: {subtitles[0]}"
    title = strip_html(title)

    authors = []
    for a in msg.get("author", []):
        family = a.get("family", "")
        given = a.get("given", "")
        if family and given:
            authors.append(f"{family}, {given}")
        elif family or given:
            authors.append(family or given)

    year = None
    for date_field in ("published", "published-print", "published-online", "issued"):
        if msg.get(date_field, {}).get("date-parts"):
            year = msg[date_field]["date-parts"][0][0]
            if year:
                break

    abstract = msg.get("abstract", "")
    if abstract:
        abstract = strip_html(abstract).strip()
    if not abstract and doi:
        abstract = fetch_openalex_abstract(doi)
    if not abstract and pdf_path is not None:
        abstract = extract_abstract_from_pdf(pdf_path, title=title)

    journal = (msg.get("container-title") or [""])[0]

    return {
        "citekey": citekey,
        "title": title,
        "authors": authors,
        "year": year or "XXXX",
        "journal": journal,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "added": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sha256_pdf": sha256_pdf,
        "abstract": abstract,
    }


def file_paper(pdf_path: Path, doi: str | None, arxiv_id: str | None,
               in_place: bool = False) -> dict:
    if not pdf_path.is_file():
        raise SystemExit(f"PDF not found: {pdf_path}")
    if not doi:
        raise SystemExit("--doi is required")

    pdf_sha = sha256_file(pdf_path)
    idx = load_index()

    # Early dup check on inputs we have without network.
    for field, key, table in [
        ("sha256", pdf_sha, idx["by_hash"]),
        ("doi", doi.lower(), idx["by_doi"]),
        ("arxiv", (arxiv_id or "").lower(), idx["by_arxiv"]),
    ]:
        if key and key in table:
            return {
                "duplicate": True,
                "matched_field": field,
                "existing_citekey": table[key],
            }

    msg = fetch_metadata(doi)
    if not msg:
        raise SystemExit(
            f"Metadata lookup failed for {doi}: neither CrossRef nor DataCite "
            f"returned a record. Use the viewer's manual-BibTeX form to file."
        )
    citekey, bibtex = make_bibtex(msg)

    # Late dup check by citekey (computed)
    all_keys = (
        set(idx["by_hash"].values())
        | set(idx["by_doi"].values())
        | set(idx["by_arxiv"].values())
    )
    if citekey in all_keys:
        return {
            "duplicate": True,
            "matched_field": "citekey",
            "existing_citekey": citekey,
        }

    meta = extract_meta(msg, doi, arxiv_id, pdf_sha, citekey, pdf_path=pdf_path)

    bib_path = BIBFILES / f"{citekey}.bib"
    note_path = PAPERNOTES / f"{citekey}.md"
    new_pdf_path = PDFS / f"{citekey}.pdf"

    if in_place:
        if pdf_path.resolve() != new_pdf_path.resolve():
            raise SystemExit(
                f"--in-place requires --pdf to be at {new_pdf_path} (got {pdf_path})"
            )
    else:
        if new_pdf_path.exists():
            raise SystemExit(f"target exists, refusing to overwrite: {new_pdf_path}")
    for p in (bib_path, note_path):
        if p.exists():
            raise SystemExit(f"target exists, refusing to overwrite: {p}")

    BIBFILES.mkdir(exist_ok=True)
    PAPERNOTES.mkdir(exist_ok=True)
    PDFS.mkdir(exist_ok=True)

    written: list[Path] = []
    moved_to: Path | None = None
    try:
        atomic_write(bib_path, bibtex.rstrip() + "\n")
        written.append(bib_path)

        atomic_write(note_path, make_note_skeleton(meta))
        written.append(note_path)

        if not in_place:
            shutil.move(str(pdf_path), str(new_pdf_path))
            moved_to = new_pdf_path

        idx["by_hash"][pdf_sha] = citekey
        idx["by_doi"][doi.lower()] = citekey
        if arxiv_id:
            idx["by_arxiv"][arxiv_id.lower()] = citekey
        write_index(idx)

        build_library_bib()

    except Exception as e:
        # Roll back the in-band writes; the post-success embed below is
        # outside this try/except (best-effort, not part of the rollback).
        for p in written:
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        if moved_to is not None:
            try:
                shutil.move(str(moved_to), str(pdf_path))
            except Exception:
                pass
        raise SystemExit(f"filing failed, rolled back: {e}")

    # Best-effort embedding refresh (incremental — content-hashed, so this
    # only embeds the new paper). Doesn't affect filing if it fails: if the
    # embed-server is down or the model can't load, we just print and continue.
    embed_status = "ok"
    try:
        proc = subprocess.run(
            ["uv", "run", str(Path(__file__).resolve().parent / "embed_corpus.py")],
            capture_output=True, text=True, timeout=180,
        )
        if proc.returncode != 0:
            embed_status = f"failed: {proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else 'rc=' + str(proc.returncode)}"
    except Exception as e:
        embed_status = f"failed: {e}"

    return {
        "duplicate": False,
        "citekey": citekey,
        "pdf_path": str(new_pdf_path.relative_to(VAULT_ROOT)),
        "note_path": str(note_path.relative_to(VAULT_ROOT)),
        "bib_path": str(bib_path.relative_to(VAULT_ROOT)),
        "bibtex": bibtex,
        "embed_status": embed_status,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pdf", required=True, type=Path)
    p.add_argument("--doi")
    p.add_argument("--arxiv")
    p.add_argument("--in-place", action="store_true",
                   help="PDF is already at PDFs/{citekey}.pdf; skip the move (backfill)")
    args = p.parse_args()
    result = file_paper(args.pdf.resolve(), args.doi, args.arxiv,
                        in_place=args.in_place)
    print(json.dumps(result, indent=2))
    return 1 if result.get("duplicate") else 0


if __name__ == "__main__":
    sys.exit(main())
