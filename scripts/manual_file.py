#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""File a PDF + user-supplied BibTeX entry into the vault.

Used when CrossRef can't find the paper (preprints without DOI, books,
theses, technical reports, websites). The viewer's manual-entry modal
prompts the user for a complete BibTeX entry; this script parses it,
mints the canonical citekey from the parsed metadata (NEVER trusting
whatever placeholder the user typed in the @type{HERE, ...} header),
and writes the triplet exactly like file_paper.py does for the
CrossRef path.

Usage:
    manual_file.py --pdf <inbox path> --bibtex-file <path/to/entry.bib>
    cat entry.bib | manual_file.py --pdf <inbox path>

Output (stdout): JSON. On dup: {duplicate: true, matched_field, existing_citekey}.
On success: {duplicate: false, citekey, pdf_path, note_path, bib_path, bibtex}.
Exit 0 on success, 1 on duplicate, >1 on error.

Citekey scheme (matches scripts/CITATION_KEYS.md):
    - If DOI present in the BibTeX → {author}{year}-{journal-abbrev}-{doi-suffix}
      (delegates to file_paper.py via the canonical doi2bib helpers)
    - Else if arXiv eprint present → {author}{year}-arxiv-{eprint-slug}
    - Else → {author}{year}-{short-title-slug}    (manual fallback)

The user's BibTeX text is preserved verbatim except for the citekey
header — that's rewritten to the canonical key so the .bib's @type
key always matches the filename and the index.
"""

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

# Local imports (sibling scripts)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from doi2bib import (  # noqa: E402
    first_author_family,
    slugify_doi_suffix,
    journal_abbrev,
    make_canonical_key,
)
from build_library_bib import build as build_library_bib  # noqa: E402

VAULT_ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = VAULT_ROOT / "index.json"
BIBFILES = VAULT_ROOT / "Bibfiles"
PAPERNOTES = VAULT_ROOT / "PaperNotes"
PDFS = VAULT_ROOT / "PDFs"


# ---- atomic write -------------------------------------------------------

def atomic_write(path: Path, content: str | bytes) -> None:
    """Write to a sibling tempfile then rename — survives crashes mid-write."""
    is_text = isinstance(content, str)
    mode = "w" if is_text else "wb"
    suffix = path.suffix + ".tmp"
    tmp = path.with_suffix(suffix)
    with open(tmp, mode, encoding="utf-8" if is_text else None) as f:
        f.write(content)
    tmp.replace(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def load_index() -> dict:
    if not INDEX_PATH.exists():
        return {"by_hash": {}, "by_doi": {}, "by_arxiv": {}}
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    for k in ("by_hash", "by_doi", "by_arxiv"):
        data.setdefault(k, {})
    return data


def save_index(idx: dict) -> None:
    atomic_write(INDEX_PATH, json.dumps(idx, indent=2, ensure_ascii=False))


# ---- bibtex parser ------------------------------------------------------
#
# Small hand-rolled parser. Handles the common forms our templates and
# users produce: `@type{key, field = {value}, field = "value", field =
# 12 }`. Nested braces inside values are matched by depth count. Line
# comments (`% ...`) are stripped before parsing.

_ENTRY_HEADER = re.compile(
    r"@\s*([A-Za-z]+)\s*\{\s*([^,\s]*)\s*,",
)


def _strip_comments(text: str) -> str:
    """Strip BibTeX line comments (`% …` to end of line), but NOT inside
    braced or quoted values. Simple state machine: track brace depth and
    quote state, only respect `%` at depth 0 outside quotes."""
    out: list[str] = []
    depth = 0
    in_quote = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            out.append(ch)
            out.append(text[i + 1])
            i += 2
            continue
        if ch == "{":
            depth += 1
            out.append(ch)
        elif ch == "}":
            depth = max(0, depth - 1)
            out.append(ch)
        elif ch == '"' and depth == 0:
            in_quote = not in_quote
            out.append(ch)
        elif ch == "%" and depth == 0 and not in_quote:
            # skip to end of line
            j = text.find("\n", i)
            if j == -1:
                break
            i = j  # let the loop pick up the \n
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _read_braced_value(text: str, start: int) -> tuple[str, int]:
    """Read a `{...}` value starting at text[start] == '{'. Returns
    (value_without_outer_braces, index_after_closing_brace)."""
    assert text[start] == "{"
    depth = 1
    i = start + 1
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
        i += 1
    raise ValueError("unterminated brace in BibTeX value")


def _read_quoted_value(text: str, start: int) -> tuple[str, int]:
    """Read a `"..."` value starting at text[start] == '"'."""
    assert text[start] == '"'
    i = start + 1
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            i += 2
            continue
        if ch == '"':
            return text[start + 1 : i], i + 1
        i += 1
    raise ValueError("unterminated quoted BibTeX value")


def _read_bare_value(text: str, start: int) -> tuple[str, int]:
    """Read a bareword / number value (terminated by `,` or `}`)."""
    j = start
    while j < len(text) and text[j] not in ",}":
        j += 1
    return text[start:j].strip(), j


def parse_bibtex(text: str) -> dict:
    """Parse a single BibTeX entry. Returns a dict with keys: 'type',
    'fields' (dict of lowercased field-name → string value, outer
    braces / quotes stripped)."""
    text = _strip_comments(text)
    m = _ENTRY_HEADER.search(text)
    if not m:
        raise ValueError("no @type{...} entry header found")
    entry_type = m.group(1).lower()
    i = m.end()
    fields: dict[str, str] = {}
    while i < len(text):
        # Skip whitespace + commas between fields.
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        if i >= len(text) or text[i] == "}":
            break
        # Read field name until '='.
        eq = text.find("=", i)
        if eq == -1:
            break
        name = text[i:eq].strip().lower()
        i = eq + 1
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
        if i >= len(text):
            break
        if text[i] == "{":
            value, i = _read_braced_value(text, i)
        elif text[i] == '"':
            value, i = _read_quoted_value(text, i)
        else:
            value, i = _read_bare_value(text, i)
        # Collapse internal newlines / runs of whitespace within the value.
        value = re.sub(r"\s+", " ", value).strip()
        fields[name] = value
    return {"type": entry_type, "fields": fields}


# ---- field interpretation -----------------------------------------------

def split_authors(s: str) -> list[dict]:
    """BibTeX authors are joined by ` and ` (case-insensitive). Each
    entry is `Family, Given` or `Given Family`. We split into the same
    {family, given} dicts CrossRef returns, so make_canonical_key works."""
    parts = re.split(r"\s+and\s+", s.strip())
    out: list[dict] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if "," in p:
            family, given = p.split(",", 1)
            out.append({"family": family.strip(), "given": given.strip()})
        else:
            toks = p.split()
            if len(toks) == 1:
                out.append({"family": toks[0]})
            else:
                out.append({"family": toks[-1], "given": " ".join(toks[:-1])})
    return out


def strip_outer_braces(s: str) -> str:
    """Templates often double-brace titles to preserve case: `{{Title}}`.
    Strip ONE balanced layer of outer braces if present."""
    if len(s) >= 2 and s[0] == "{" and s[-1] == "}":
        return s[1:-1]
    return s


def short_title_slug(title: str, max_words: int = 4) -> str:
    """First N significant words of the title → kebab-case slug. Used
    as the citekey suffix for manual entries (no DOI / no arXiv).
    See CITATION_KEYS.md → manual fallback."""
    # Strip wrapper braces, then lowercase + collapse non-alnum.
    t = strip_outer_braces(title).lower()
    # Drop common stopwords from the front so the slug carries signal.
    stop = {"a", "an", "the", "on", "of", "for", "and", "or", "to",
            "in", "with", "from"}
    words: list[str] = []
    for raw in re.split(r"[^a-z0-9]+", t):
        if not raw:
            continue
        if not words and raw in stop:
            continue
        words.append(raw)
        if len(words) >= max_words:
            break
    return "-".join(words) if words else "untitled"


def arxiv_slug(eprint: str) -> str:
    """ArXiv id (e.g. 2305.10141 or cond-mat/0501123) → slug (`.` → `-`)."""
    return re.sub(r"[^a-z0-9]+", "-", eprint.lower()).strip("-")


def mint_citekey(fields: dict, doi: str, eprint: str) -> str:
    """Canonical citekey from parsed BibTeX fields. Prefers (DOI →
    arXiv → title-slug) the same way scripts/CITATION_KEYS.md does."""
    authors = split_authors(fields.get("author") or fields.get("editor") or "")
    if not authors:
        authors = [{"family": "unknown"}]
    year = fields.get("year") or "XXXX"
    journal_full = (
        fields.get("journal")
        or fields.get("booktitle")
        or fields.get("publisher")
        or ""
    )
    journal_full = strip_outer_braces(journal_full)
    if doi:
        return make_canonical_key(doi, authors, year, journal_full)
    if eprint:
        author = first_author_family(authors)
        return f"{author}{year}-arxiv-{arxiv_slug(eprint)}"
    # Manual fallback.
    author = first_author_family(authors)
    title = fields.get("title", "")
    return f"{author}{year}-{short_title_slug(title)}"


# ---- bibtex rewrite ------------------------------------------------------

def rewrite_citekey(bibtex: str, new_key: str) -> str:
    """Replace the `@type{OLD_KEY,` header with the new citekey. Keeps
    everything else verbatim — whitespace, field order, comments. The
    original `% manual-key — replace …` comment, if present, is dropped
    since we've now assigned a real key."""
    bibtex = re.sub(
        r"@\s*([A-Za-z]+)\s*\{\s*[^,\s]*\s*,",
        lambda m: f"@{m.group(1)}{{{new_key},",
        bibtex,
        count=1,
    )
    # Drop the `% manual-key …` reminder line.
    bibtex = re.sub(r"^\s*%\s*manual-key[^\n]*\n", "", bibtex, flags=re.M)
    return bibtex


# ---- note skeleton -------------------------------------------------------

AUTHOR_DISPLAY_THRESHOLD = 6
AUTHOR_DISPLAY_KEEP = 5


def yaml_quote(s: str) -> str:
    """Quote a YAML scalar that may contain special chars."""
    s = (s or "").replace('"', '\\"')
    return f'"{s}"'


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
    fm.append("source: manual")
    fm.append("---")
    fm.append("")
    fm.append("## Why")
    fm.append("")
    fm.append("## Cleaned Notes")
    fm.append("")
    fm.append("## Notes")
    fm.append("")
    return "\n".join(fm)


# ---- main -----------------------------------------------------------------

def file_manual(pdf_path: Path, bibtex: str) -> dict:
    if not pdf_path.is_file():
        raise SystemExit(f"PDF not found: {pdf_path}")

    pdf_sha = sha256_file(pdf_path)
    idx = load_index()

    # 1. Parse the BibTeX.
    entry = parse_bibtex(bibtex)
    fields = entry["fields"]

    doi = (fields.get("doi") or "").strip()
    eprint = (fields.get("eprint") or "").strip()

    # 2. Early dup check on inputs we have without further work.
    for field, key, table in [
        ("sha256", pdf_sha, idx["by_hash"]),
        ("doi", doi.lower(), idx["by_doi"]),
        ("arxiv", eprint.lower(), idx["by_arxiv"]),
    ]:
        if key and key in table:
            return {
                "duplicate": True,
                "matched_field": field,
                "existing_citekey": table[key],
            }

    # 3. Mint canonical citekey from parsed fields (NOT from user's
    #    placeholder key in the @type{HERE, ...} header).
    citekey = mint_citekey(fields, doi, eprint)

    # Late dup check by citekey.
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

    # 4. Build the metadata dict for the note skeleton.
    title = strip_outer_braces(fields.get("title", "")).strip()
    authors_split = split_authors(fields.get("author") or "")
    authors_display: list[str] = []
    for a in authors_split:
        family = a.get("family", "")
        given = a.get("given", "")
        if family and given:
            authors_display.append(f"{family}, {given}")
        elif family or given:
            authors_display.append(family or given)
    journal = strip_outer_braces(
        fields.get("journal") or fields.get("booktitle") or fields.get("publisher") or ""
    ).strip()
    year_val: str | int = fields.get("year", "XXXX")
    try:
        year_val = int(year_val)
    except (ValueError, TypeError):
        pass

    meta = {
        "citekey": citekey,
        "title": title,
        "authors": authors_display,
        "year": year_val,
        "journal": journal,
        "doi": doi or None,
        "arxiv_id": eprint or None,
        "added": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sha256_pdf": pdf_sha,
    }

    bib_path = BIBFILES / f"{citekey}.bib"
    note_path = PAPERNOTES / f"{citekey}.md"
    new_pdf_path = PDFS / f"{citekey}.pdf"

    if new_pdf_path.exists():
        raise SystemExit(f"target exists, refusing to overwrite: {new_pdf_path}")
    for p in (bib_path, note_path):
        if p.exists():
            raise SystemExit(f"target exists, refusing to overwrite: {p}")

    BIBFILES.mkdir(exist_ok=True)
    PAPERNOTES.mkdir(exist_ok=True)
    PDFS.mkdir(exist_ok=True)

    # 5. Rewrite the user's BibTeX with the canonical citekey, then
    #    write the triplet.
    final_bibtex = rewrite_citekey(bibtex.strip(), citekey)

    written: list[Path] = []
    moved_to: Path | None = None
    try:
        atomic_write(bib_path, final_bibtex.rstrip() + "\n")
        written.append(bib_path)

        atomic_write(note_path, make_note_skeleton(meta))
        written.append(note_path)

        shutil.move(str(pdf_path), str(new_pdf_path))
        moved_to = new_pdf_path

        idx["by_hash"][pdf_sha] = citekey
        if doi:
            idx["by_doi"][doi.lower()] = citekey
        if eprint:
            idx["by_arxiv"][eprint.lower()] = citekey
        save_index(idx)

        build_library_bib(BIBFILES, VAULT_ROOT / "library.bib")
    except Exception:
        # Best-effort rollback.
        for p in written:
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        if moved_to is not None:
            try:
                shutil.move(str(moved_to), str(pdf_path))
            except FileNotFoundError:
                pass
        raise

    return {
        "duplicate": False,
        "citekey": citekey,
        "pdf_path": str(new_pdf_path),
        "note_path": str(note_path),
        "bib_path": str(bib_path),
        "bibtex": final_bibtex,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pdf", required=True, type=Path)
    src = p.add_mutually_exclusive_group()
    src.add_argument("--bibtex", help="BibTeX entry as a single string argument.")
    src.add_argument("--bibtex-file", type=Path,
                     help="Read BibTeX entry from a file (use `-` for stdin).")
    args = p.parse_args()

    if args.bibtex is not None:
        bibtex = args.bibtex
    elif args.bibtex_file is not None:
        if str(args.bibtex_file) == "-":
            bibtex = sys.stdin.read()
        else:
            bibtex = args.bibtex_file.read_text(encoding="utf-8")
    else:
        # Default: read from stdin.
        bibtex = sys.stdin.read()

    if not bibtex.strip():
        print("BibTeX is empty", file=sys.stderr)
        return 2

    try:
        result = file_manual(args.pdf, bibtex)
    except SystemExit as e:
        print(f"manual_file error: {e}", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result.get("duplicate") else 0


if __name__ == "__main__":
    sys.exit(main())
