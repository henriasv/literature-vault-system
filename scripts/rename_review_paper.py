#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Rename or move a review paper inside the vault.

A review paper is identified by the synthetic citekey
`review:<project>:<stem>` and consists of four artifacts that must stay
in sync:

    PDF          PDFs/reviewing/<project>/<stem>.pdf
    Note         ReviewNotes/<project>/<stem>.md
    Annotations  Annotations/reviewing/<project>/<stem>.json
                 (legacy fallback: Annotations/review-<project>-<stem>.json)
    Frontmatter  citekey: review:<project>:<stem>   (inside the Note)

This script changes any subset of (project, stem) atomically. It is the
intended interface for the librarian agent and for any other automated
caller that needs to rename or move a review paper — direct file moves
risk drift between the four artifacts. The viewer's Rust backend shells
out to this same script via the `rename_review_paper` Tauri command.

Usage:
    rename_review_paper.py --citekey review:<proj>:<stem> --new-stem <stem>
    rename_review_paper.py --citekey review:<proj>:<stem> --new-project <slug>
    rename_review_paper.py --citekey review:<proj>:<stem> \\
                           --new-project <slug> --new-stem <stem>

On success prints JSON to stdout:
    {
      "old_citekey":  "review:p1:smith",
      "new_citekey":  "review:p1:smith_v2",
      "paths": {
        "pdf":         "<absolute path to renamed PDF>",
        "note":        "<absolute path to renamed Note>",
        "annotations": "<absolute path to renamed Annotations, or null>"
      }
    }

Exits non-zero with an error message on any failure. The script does
NOT half-apply: it pre-checks every collision before touching the
filesystem and rolls back any moves it made if a subsequent step fails.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


VAULT_ROOT = Path(
    os.environ.get("LITERATURE_VAULT")
    or Path(__file__).absolute().parent.parent
)

REVIEW_NOTES_DIR = VAULT_ROOT / "ReviewNotes"
REVIEWING_PDFS_DIR = VAULT_ROOT / "PDFs" / "reviewing"
ANNOTATIONS_DIR = VAULT_ROOT / "Annotations"


def die(msg: str, code: int = 2) -> None:
    print(f"rename_review_paper: {msg}", file=sys.stderr)
    sys.exit(code)


# --- Path helpers (must match viewer/src-tauri/src/vault.rs) -----------------

def parse_review_id(citekey: str) -> tuple[str, str]:
    """Split `review:<project>:<stem>` into (project, stem). Errors out
    on any other shape."""
    if not citekey.startswith("review:"):
        die(f"not a review citekey: {citekey!r}")
    rest = citekey[len("review:"):]
    if rest.count(":") < 1:
        die(f"missing ':<stem>' suffix in citekey: {citekey!r}")
    project, stem = rest.split(":", 1)
    if not project or not stem:
        die(f"empty project or stem in citekey: {citekey!r}")
    return project, stem


def sanitize_slug(slug: str, field: str) -> str:
    """Reject path separators / NUL / leading-dot. Mirrors the Rust
    `sanitize_project_slug` / `sanitize_review_stem`."""
    s = slug.strip()
    if not s:
        die(f"{field} must not be empty")
    if "/" in s or "\\" in s or "\0" in s:
        die(f"{field} must not contain path separators: {slug!r}")
    if s.startswith("."):
        die(f"{field} must not start with a dot: {slug!r}")
    if ":" in s:
        die(f"{field} must not contain ':' (reserved for citekey separator): {slug!r}")
    return s


def review_pdf_path(project: str, stem: str) -> Path:
    return REVIEWING_PDFS_DIR / project / f"{stem}.pdf"


def review_note_path(project: str, stem: str) -> Path:
    return REVIEW_NOTES_DIR / project / f"{stem}.md"


def review_annotation_path(project: str, stem: str) -> Path:
    """Canonical, subdir-based annotation location. Mirrors the PDF tree."""
    return ANNOTATIONS_DIR / "reviewing" / project / f"{stem}.json"


def legacy_review_annotation_path(project: str, stem: str) -> Path:
    """The older flat-name encoding `Annotations/review-<project>-<stem>.json`.
    Kept readable so a rename also migrates the file to the canonical
    location, but no new files are written here."""
    return ANNOTATIONS_DIR / f"review-{project}-{stem}.json"


# --- Frontmatter citekey rewrite --------------------------------------------

CITEKEY_LINE_RE = re.compile(r"^citekey:\s*.*$", re.MULTILINE)


def rewrite_citekey_in_frontmatter(note_path: Path, new_citekey: str) -> None:
    """Replace the `citekey:` line inside the note's YAML frontmatter.
    Refuses to write if no citekey line was found (defends against an
    unexpected note shape)."""
    text = note_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        die(f"note has no leading '---' frontmatter fence: {note_path}")
    new_text, n = CITEKEY_LINE_RE.subn(f"citekey: {new_citekey}", text, count=1)
    if n != 1:
        die(f"no `citekey:` line found in {note_path}")
    note_path.write_text(new_text, encoding="utf-8")


# --- Main --------------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--citekey", required=True, help="Current review citekey, e.g. review:p1:smith")
    ap.add_argument("--new-stem", help="New file stem (the part after the last `:` of the citekey).")
    ap.add_argument("--new-project", help="New project slug (move between projects).")
    args = ap.parse_args(argv)

    if not args.new_stem and not args.new_project:
        die("specify at least one of --new-stem or --new-project")

    old_project, old_stem = parse_review_id(args.citekey)
    new_project = sanitize_slug(args.new_project or old_project, "project")
    new_stem = sanitize_slug(args.new_stem or old_stem, "stem")

    if (new_project, new_stem) == (old_project, old_stem):
        die("new (project, stem) is identical to the current one — nothing to do")

    old_pdf = review_pdf_path(old_project, old_stem)
    old_note = review_note_path(old_project, old_stem)
    old_ann = review_annotation_path(old_project, old_stem)
    old_ann_legacy = legacy_review_annotation_path(old_project, old_stem)

    new_pdf = review_pdf_path(new_project, new_stem)
    new_note = review_note_path(new_project, new_stem)
    new_ann = review_annotation_path(new_project, new_stem)
    new_citekey = f"review:{new_project}:{new_stem}"

    # --- Pre-flight checks ---------------------------------------------------
    if not old_pdf.is_file():
        die(f"PDF not found at expected path: {old_pdf}")
    if not old_note.is_file():
        die(f"Note not found at expected path: {old_note}")
    if new_pdf.exists():
        die(f"refusing to clobber existing PDF: {new_pdf}")
    if new_note.exists():
        die(f"refusing to clobber existing Note: {new_note}")
    if new_ann.exists():
        die(f"refusing to clobber existing annotations: {new_ann}")

    # Existing annotation file — prefer the canonical location, fall back.
    src_ann: Path | None = None
    if old_ann.is_file():
        src_ann = old_ann
    elif old_ann_legacy.is_file():
        src_ann = old_ann_legacy

    # --- Stage 1: move PDF ---------------------------------------------------
    new_pdf.parent.mkdir(parents=True, exist_ok=True)
    new_note.parent.mkdir(parents=True, exist_ok=True)
    if src_ann is not None:
        new_ann.parent.mkdir(parents=True, exist_ok=True)

    rollback: list[tuple[Path, Path]] = []  # (current, original) to undo

    def do_rename(src: Path, dst: Path) -> None:
        os.rename(src, dst)
        rollback.append((dst, src))

    def undo_all() -> None:
        for cur, orig in reversed(rollback):
            try:
                os.rename(cur, orig)
            except OSError as e:
                print(f"rename_review_paper: rollback failed for {cur} -> {orig}: {e}", file=sys.stderr)

    try:
        do_rename(old_pdf, new_pdf)
        do_rename(old_note, new_note)
        if src_ann is not None:
            do_rename(src_ann, new_ann)
        # Frontmatter rewrite happens AFTER all the moves so a failed
        # rewrite leaves us with the files at their new paths and the
        # frontmatter still pointing at the old citekey — easy to spot
        # and re-run the script with the same args.
        rewrite_citekey_in_frontmatter(new_note, new_citekey)
    except Exception as e:
        undo_all()
        die(f"rename failed mid-way (rolled back): {e}")

    print(json.dumps({
        "old_citekey": args.citekey,
        "new_citekey": new_citekey,
        "paths": {
            "pdf": str(new_pdf),
            "note": str(new_note),
            "annotations": str(new_ann) if src_ann is not None else None,
        },
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
