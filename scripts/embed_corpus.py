#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "sqlite-vec>=0.1.6",
#   "PyYAML>=6.0",
# ]
# ///
"""Embed PaperNotes/*.md into embeddings.db via the embed-server.

Embeds: title + abstract + ## Why + ## Cleaned Notes per paper.
Incremental: skips papers whose (citekey, model, content_hash) match
what's already stored.

Schema (per model, since vector spaces don't cross-compare):
  papers (citekey, model, content_hash, embedded_at)  PK (citekey, model)
  vec_papers__<safe_model_id> (citekey TEXT PK, embedding FLOAT[dim])

Usage:
    embed_corpus.py                  # use server's default model
    embed_corpus.py --model gemma    # specific registered model
    embed_corpus.py --force          # re-embed even if hash matches
"""

import argparse
import array
import datetime as dt
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

import sqlite_vec
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _embed_client import embed as embed_remote, health as server_health  # noqa: E402

VAULT_ROOT = Path(__file__).resolve().parent.parent
PAPERNOTES = VAULT_ROOT / "PaperNotes"
DB_PATH = VAULT_ROOT / "embeddings.db"
CONFIG_PATH = Path(__file__).resolve().parent / "embed_models.json"


def _load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def _safe(model_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", model_id)


def _vec_table(model_id: str) -> str:
    return f"vec_papers__{_safe(model_id)}"


# ── Frontmatter / sections ───────────────────────────────────────────────────

def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    return yaml.safe_load(parts[1]) or {}, parts[2]


def extract_section(body: str, name: str) -> str:
    head_re = re.compile(rf"^##\s+{re.escape(name)}\s*$")
    next_re = re.compile(r"^##\s+")
    out: list[str] = []
    in_section = False
    for ln in body.splitlines():
        if head_re.match(ln):
            in_section = True
            continue
        if in_section and next_re.match(ln):
            break
        if in_section:
            out.append(ln)
    return "\n".join(out).strip()


def make_content(note_path: Path) -> tuple[str, str]:
    text = note_path.read_text()
    fm, body = split_frontmatter(text)
    title = fm.get("title", "") or ""
    authors = "; ".join(fm.get("authors") or [])
    abstract = fm.get("abstract", "") or ""
    why = extract_section(body, "Why")
    cleaned = extract_section(body, "Cleaned Notes")
    parts = [
        f"Title: {title}".strip() if title else "",
        f"Authors: {authors}" if authors else "",
        f"Abstract: {abstract}" if abstract else "",
        f"Why: {why}" if why else "",
        f"Notes: {cleaned}" if cleaned else "",
    ]
    content = "\n\n".join(p for p in parts if p)
    return content, hashlib.sha256(content.encode()).hexdigest()[:16]


# ── DB ───────────────────────────────────────────────────────────────────────

def init_db(con: sqlite3.Connection, model_id: str, dim: int) -> None:
    # If the legacy single-model schema exists, drop it. The old papers
    # table has citekey as the only PK (no model column in PK) and the
    # vec_papers virtual table is single-model.
    cols = con.execute("PRAGMA table_info(papers)").fetchall()
    pk_cols = {c[1] for c in cols if c[5] > 0}
    legacy_papers = bool(cols) and pk_cols != {"citekey", "model"}
    legacy_vec = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_papers'"
    ).fetchone() is not None
    if legacy_papers or legacy_vec:
        sys.stderr.write("dropping legacy single-model schema\n")
        if legacy_papers:
            con.execute("DROP TABLE papers")
        if legacy_vec:
            con.execute("DROP TABLE vec_papers")
        con.commit()
    # New schema: papers has composite PK (citekey, model).
    con.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            citekey TEXT NOT NULL,
            model TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            embedded_at TEXT NOT NULL,
            PRIMARY KEY (citekey, model)
        )
    """)
    # Per-model vec table.
    table = _vec_table(model_id)
    con.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0(
            citekey TEXT PRIMARY KEY,
            embedding FLOAT[{dim}]
        )
    """)
    con.commit()


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", help="registered model id; default = server's default")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    cfg = _load_config()
    model_id = args.model or cfg["default"]
    if model_id not in cfg["models"]:
        sys.exit(f"unknown model {model_id!r}; registered: {list(cfg['models'])}")
    dim = cfg["models"][model_id]["dim"]

    con = sqlite3.connect(DB_PATH)
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.enable_load_extension(False)
    init_db(con, model_id, dim)

    notes = sorted(PAPERNOTES.glob("*.md"))
    if not notes:
        print("no notes in PaperNotes/", file=sys.stderr)
        return 0

    to_embed: list[tuple[str, str, str]] = []
    for note in notes:
        citekey = note.stem
        content, h = make_content(note)
        if not content:
            print(f"skip (empty content): {citekey}", file=sys.stderr)
            continue
        if not args.force:
            row = con.execute(
                "SELECT content_hash FROM papers WHERE citekey = ? AND model = ?",
                (citekey, model_id),
            ).fetchone()
            if row and row[0] == h:
                continue
        to_embed.append((citekey, content, h))

    if not to_embed:
        print(f"all {len(notes)} papers up to date for model={model_id}", file=sys.stderr)
        return 0

    print(f"embedding {len(to_embed)}/{len(notes)} papers via model={model_id}…",
          file=sys.stderr)

    table = _vec_table(model_id)
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    batch_size = 1
    total_done = 0
    for batch_start in range(0, len(to_embed), batch_size):
        batch = to_embed[batch_start:batch_start + batch_size]
        vectors, used_model = embed_remote(
            [c for _, c, _ in batch], prompt="document", model=model_id
        )
        if used_model != model_id:
            sys.exit(f"server used model {used_model!r} but client asked for {model_id!r}")
        for (citekey, _, h), vec in zip(batch, vectors):
            con.execute(f"DELETE FROM {table} WHERE citekey = ?", (citekey,))
            con.execute(
                f"INSERT INTO {table}(citekey, embedding) VALUES (?, ?)",
                (citekey, array.array("f", vec).tobytes()),
            )
            con.execute("""
                INSERT INTO papers(citekey, model, content_hash, embedded_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(citekey, model) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    embedded_at = excluded.embedded_at
            """, (citekey, model_id, h, now))
        con.commit()
        total_done += len(batch)
        print(f"  {total_done}/{len(to_embed)}…", file=sys.stderr)
    print(f"embedded {total_done} paper(s) for model={model_id}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
