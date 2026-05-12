#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Re-identify an already-filed paper.

Two entry points:

  reassign.py --old-citekey <old> --new-doi <doi>
  reassign.py --old-citekey <old> --new-bibtex-file <path>

Both rename PDFs/{old}.pdf → PDFs/{new}.pdf, rewrite the note's frontmatter
(preserving the body's prose — `## Why`, `## Cleaned Notes`, `## Notes`,
timestamps, anything after the YAML), rewrite Bibfiles/, update index.json,
regenerate library.bib, and replace `old` with `new` in every
Collections/**/index.md `## Papers` list.

User-curated fields preserved across reassignment: `tags`, `added`,
`sha256_pdf` (the PDF byte stream is the same).

Output (stdout): JSON `{status: "reassigned", old_citekey, new_citekey,
note_path, bib_path, pdf_path}`. Exits 0 on success, non-zero on error
(stderr carries the reason).
"""

import os
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

# Local imports (sibling scripts)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from doi2bib import fetch_crossref, make_bibtex  # noqa: E402
from file_paper import (  # noqa: E402
    AUTHOR_DISPLAY_KEEP,
    AUTHOR_DISPLAY_THRESHOLD,
    atomic_write,
    extract_meta,
    load_index,
    write_index,
    yaml_block,
    yaml_quote,
)
from build_library_bib import build as build_library_bib  # noqa: E402

VAULT_ROOT = Path(
    os.environ.get("LITERATURE_VAULT")
    or Path(__file__).absolute().parent.parent
)
PAPERNOTES = VAULT_ROOT / "PaperNotes"
BIBFILES = VAULT_ROOT / "Bibfiles"
PDFS = VAULT_ROOT / "PDFs"
COLLECTIONS = VAULT_ROOT / "Collections"


# ---------- frontmatter / body split ----------

_FRONTMATTER_SPLIT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_yaml, body) for a markdown note. Body includes
    everything after the closing `---` (including the first `# title` line
    and all sections). Raises on a missing frontmatter block."""
    m = _FRONTMATTER_SPLIT.match(text)
    if not m:
        raise SystemExit("note has no YAML frontmatter (couldn't find `---` fence)")
    return m.group(1), text[m.end():]


def parse_old_frontmatter(yaml_text: str) -> dict:
    """Very small YAML reader for the fields we care about — `tags`, `added`,
    `sha256_pdf`. Not a general YAML parser; the canonical write path is the
    one we use here, so this only has to round-trip what we ourselves wrote."""
    out: dict = {}
    lines = yaml_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # tags: [a, b, c]   OR   tags:\n  - a\n  - b
        if line.startswith("tags:"):
            rest = line[len("tags:"):].strip()
            if rest.startswith("[") and rest.endswith("]"):
                out["tags"] = [
                    t.strip().strip('"').strip("'")
                    for t in rest[1:-1].split(",")
                    if t.strip()
                ]
            else:
                tags = []
                j = i + 1
                while j < len(lines) and lines[j].lstrip().startswith("-"):
                    tags.append(lines[j].lstrip()[1:].strip().strip('"').strip("'"))
                    j += 1
                out["tags"] = tags
            i += 1
            continue
        for key in ("added", "sha256_pdf"):
            if line.startswith(f"{key}:"):
                out[key] = line[len(key) + 1:].strip().strip('"').strip("'")
                break
        i += 1
    out.setdefault("tags", [])
    return out


# ---------- frontmatter writer ----------


def render_frontmatter(meta: dict, tags: list[str]) -> str:
    """Build the YAML frontmatter (between the `---` fences, exclusive) from
    a meta dict produced by `extract_meta` or `meta_from_bibtex_fields`."""
    fm: list[str] = []
    fm.append(f"citekey: {meta['citekey']}")
    fm.append(f"title: {yaml_quote(meta['title'])}")
    authors = meta.get("authors", [])
    fm.append("authors:")
    if len(authors) > AUTHOR_DISPLAY_THRESHOLD:
        for a in authors[:AUTHOR_DISPLAY_KEEP]:
            fm.append(f"  - {yaml_quote(a)}")
        fm.append(f"  - {yaml_quote(f'…and {len(authors) - AUTHOR_DISPLAY_KEEP} others')}")
        fm.append(f"author_count: {len(authors)}")
    else:
        for a in authors:
            fm.append(f"  - {yaml_quote(a)}")
    fm.append(f"year: {meta.get('year') or 'XXXX'}")
    if meta.get("journal"):
        fm.append(f"journal: {yaml_quote(meta['journal'])}")
    fm.append(f"doi: {meta.get('doi') or 'null'}")
    fm.append(f"arxiv_id: {meta.get('arxiv_id') or 'null'}")
    fm.append(f"added: {meta['added']}")
    if tags:
        fm.append("tags:")
        for t in tags:
            fm.append(f"  - {yaml_quote(t)}")
    else:
        fm.append("tags: []")
    fm.append(f"sha256_pdf: {meta['sha256_pdf']}")
    if meta.get("abstract"):
        fm.append(f"abstract: {yaml_block(meta['abstract'])}")
    return "\n".join(fm) + "\n"


# ---------- BibTeX parsing (for the manual path) ----------

_HEADER_RE = re.compile(r"@(\w+)\s*\{\s*([^\s,]+)\s*,", re.DOTALL)


def parse_bibtex_entry(text: str) -> tuple[str, str, dict[str, str]]:
    """Parse a user-supplied BibTeX entry into (entry_type, citekey, fields).
    Handles nested braces by counting depth. Comments (`%`) are stripped at
    line granularity since BibTeX itself doesn't grok them everywhere, but
    our templates use them as markers."""
    cleaned_lines = []
    for ln in text.splitlines():
        ix = ln.find("%")
        if ix >= 0:
            ln = ln[:ix]
        cleaned_lines.append(ln)
    cleaned = "\n".join(cleaned_lines).strip()

    m = _HEADER_RE.match(cleaned)
    if not m:
        raise SystemExit("can't parse BibTeX header — expected `@type{key, …}`")
    entry_type = m.group(1).lower()
    citekey = m.group(2)
    body_start = m.end()

    # Find the matching closing brace for the whole entry.
    depth = 1
    i = body_start
    while i < len(cleaned) and depth > 0:
        c = cleaned[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    if depth != 0:
        raise SystemExit("unbalanced braces in BibTeX entry")
    body = cleaned[body_start:i - 1]

    # Walk fields: `name = { value }` (depth-aware).
    fields: dict[str, str] = {}
    pos = 0
    while pos < len(body):
        m = re.search(r"(\w+)\s*=\s*\{", body[pos:])
        if not m:
            break
        name = m.group(1).lower()
        vstart = pos + m.end()
        d = 1
        j = vstart
        while j < len(body) and d > 0:
            if body[j] == "{":
                d += 1
            elif body[j] == "}":
                d -= 1
            j += 1
        value = body[vstart:j - 1].strip()
        # Strip outer `{}` if the user double-braced the value.
        if value.startswith("{") and value.endswith("}"):
            value = value[1:-1].strip()
        fields[name] = value
        pos = j

    return entry_type, citekey, fields


def meta_from_bibtex_fields(
    citekey: str, fields: dict[str, str], sha256_pdf: str, added: str,
) -> dict:
    """Build a meta dict (matching extract_meta's shape) from parsed BibTeX
    fields. Handles `Lastname, Firstname and Lastname, Firstname` author
    lists. Year falls back to "XXXX"; journal/abstract default to empty."""
    raw_authors = fields.get("author", "")
    authors = [a.strip() for a in re.split(r"\s+and\s+", raw_authors) if a.strip()]
    year_raw = fields.get("year", "")
    year_m = re.search(r"\d{4}", year_raw)
    year = year_m.group(0) if year_m else "XXXX"
    journal = (
        fields.get("journal")
        or fields.get("booktitle")
        or fields.get("school")
        or fields.get("institution")
        or fields.get("organization")
        or ""
    )
    return {
        "citekey": citekey,
        "title": fields.get("title", "").strip().strip("{}"),
        "authors": authors,
        "year": year,
        "journal": journal,
        "doi": fields.get("doi") or None,
        "arxiv_id": fields.get("eprint") or None,
        "added": added,
        "sha256_pdf": sha256_pdf,
        "abstract": fields.get("abstract", ""),
    }


# ---------- Collections refs ----------

_BULLET_LIST_HEADER = re.compile(r"^##\s+Papers\s*$", re.MULTILINE)


def update_collections_refs(old: str, new: str) -> list[Path]:
    """Replace whole-citekey occurrences of `old` with `new` inside every
    Collections/**/index.md. Whole-citekey = bounded by word boundary so we
    don't accidentally hit substrings (e.g. `bore2026-arxiv-2603-11539` vs
    `bore2026-arxiv-2603-11539-supplementary`)."""
    changed: list[Path] = []
    if not COLLECTIONS.is_dir():
        return changed
    pattern = re.compile(rf"\b{re.escape(old)}\b")
    for md in COLLECTIONS.rglob("index.md"):
        text = md.read_text()
        new_text = pattern.sub(new, text)
        if new_text != text:
            atomic_write(md, new_text)
            changed.append(md)
    return changed


# ---------- main transaction ----------


def reassign(
    old_citekey: str,
    new_doi: str | None,
    new_bibtex_text: str | None,
) -> dict:
    if not (bool(new_doi) ^ bool(new_bibtex_text)):
        raise SystemExit("provide exactly one of --new-doi / --new-bibtex-file")

    old_note = PAPERNOTES / f"{old_citekey}.md"
    old_bib = BIBFILES / f"{old_citekey}.bib"
    old_pdf = PDFS / f"{old_citekey}.pdf"
    if not old_note.is_file():
        raise SystemExit(f"note not found: {old_note}")

    raw = old_note.read_text()
    old_fm_text, body = split_frontmatter(raw)
    preserved = parse_old_frontmatter(old_fm_text)
    sha256_pdf = preserved.get("sha256_pdf") or ""
    added = preserved.get("added") or ""
    if not sha256_pdf:
        raise SystemExit(
            f"existing note has no `sha256_pdf` — refusing to reassign without it"
        )

    # ----- compute new citekey + bibtex + meta -----
    if new_doi:
        new_doi = new_doi.strip()
        msg = fetch_crossref(new_doi)
        if not msg:
            raise SystemExit(f"CrossRef lookup failed for {new_doi}")
        new_citekey, bibtex = make_bibtex(msg)
        meta = extract_meta(
            msg, new_doi, None, sha256_pdf, new_citekey,
            pdf_path=old_pdf if old_pdf.is_file() else None,
        )
        # Preserve original `added`; extract_meta always sets it to "now".
        if added:
            meta["added"] = added
    else:
        # Manual BibTeX path: parse the user's entry, derive citekey + meta.
        assert new_bibtex_text is not None
        bibtex = new_bibtex_text.strip()
        _, new_citekey, fields = parse_bibtex_entry(bibtex)
        meta = meta_from_bibtex_fields(
            new_citekey, fields, sha256_pdf, added or "",
        )

    if new_citekey == old_citekey:
        raise SystemExit(f"new citekey == old ({new_citekey}) — no-op")

    # Refuse if anything already exists for the new citekey.
    new_note = PAPERNOTES / f"{new_citekey}.md"
    new_bib = BIBFILES / f"{new_citekey}.bib"
    new_pdf = PDFS / f"{new_citekey}.pdf"
    for p in (new_note, new_bib, new_pdf):
        if p.exists():
            raise SystemExit(f"target exists, refusing to overwrite: {p}")

    # Index collision check.
    idx = load_index()
    all_keys = (
        set(idx.get("by_hash", {}).values())
        | set(idx.get("by_doi", {}).values())
        | set(idx.get("by_arxiv", {}).values())
    )
    if new_citekey in all_keys:
        raise SystemExit(
            f"new citekey {new_citekey} already exists in index.json"
        )

    # ----- atomic transaction -----
    written: list[Path] = []
    moved_pdf: tuple[Path, Path] | None = None
    deleted_old_note_text: str | None = None
    deleted_old_bib_text: str | None = None
    try:
        # Write new files.
        new_note_text = f"---\n{render_frontmatter(meta, preserved.get('tags', []))}---\n{body}"
        atomic_write(new_note, new_note_text)
        written.append(new_note)

        atomic_write(new_bib, bibtex.rstrip() + "\n")
        written.append(new_bib)

        # Move PDF (if it exists — manual entries for, e.g., books may not have one).
        if old_pdf.is_file():
            shutil.move(str(old_pdf), str(new_pdf))
            moved_pdf = (old_pdf, new_pdf)

        # Delete old note + bib (after the new ones are written so rollback works).
        if old_note.is_file():
            deleted_old_note_text = old_note.read_text()
            old_note.unlink()
        if old_bib.is_file():
            deleted_old_bib_text = old_bib.read_text()
            old_bib.unlink()

        # Update index.json: drop every entry pointing at old, add new.
        for table in ("by_hash", "by_doi", "by_arxiv"):
            idx.setdefault(table, {})
            idx[table] = {k: v for k, v in idx[table].items() if v != old_citekey}
        idx["by_hash"][sha256_pdf] = new_citekey
        if meta.get("doi"):
            idx["by_doi"][meta["doi"].lower()] = new_citekey
        if meta.get("arxiv_id"):
            idx["by_arxiv"][str(meta["arxiv_id"]).lower()] = new_citekey
        write_index(idx)

        build_library_bib()

        # Update Collections refs (best-effort; failures don't block the rename
        # since the renames have already committed and rolling back at this
        # point would leave the vault in a worse state).
        changed_colls = update_collections_refs(old_citekey, new_citekey)

    except Exception as e:
        # Roll back what we can.
        for p in written:
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        if moved_pdf is not None:
            try:
                shutil.move(str(moved_pdf[1]), str(moved_pdf[0]))
            except Exception:
                pass
        if deleted_old_note_text is not None and not old_note.exists():
            try:
                atomic_write(old_note, deleted_old_note_text)
            except Exception:
                pass
        if deleted_old_bib_text is not None and not old_bib.exists():
            try:
                atomic_write(old_bib, deleted_old_bib_text)
            except Exception:
                pass
        raise SystemExit(f"reassign failed, rolled back: {e}")

    return {
        "status": "reassigned",
        "old_citekey": old_citekey,
        "new_citekey": new_citekey,
        "note_path": str(new_note.relative_to(VAULT_ROOT)),
        "bib_path": str(new_bib.relative_to(VAULT_ROOT)),
        "pdf_path": (
            str(new_pdf.relative_to(VAULT_ROOT)) if new_pdf.is_file() else None
        ),
        "collections_updated": [
            str(p.relative_to(VAULT_ROOT)) for p in changed_colls
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Re-identify an already-filed paper.")
    p.add_argument("--old-citekey", required=True)
    p.add_argument("--new-doi", help="CrossRef DOI for the correct paper.")
    p.add_argument(
        "--new-bibtex-file",
        type=Path,
        help="Path to a file containing a single BibTeX entry "
        "(used when the source isn't in CrossRef).",
    )
    args = p.parse_args()

    new_bibtex_text: str | None = None
    if args.new_bibtex_file:
        new_bibtex_text = args.new_bibtex_file.read_text()

    result = reassign(args.old_citekey, args.new_doi, new_bibtex_text)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
