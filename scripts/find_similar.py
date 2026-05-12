#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "sqlite-vec>=0.1.6",
# ]
# ///
"""Find papers similar to a text query via the embed-server.

Usage:
    find_similar.py "query text" [--top 10] [--model gemma]
    echo "query text" | find_similar.py [--top 10]

Output: JSON list of {citekey, distance} sorted ascending.
The model defaults to the server's default model. Pass --model to use
a different registered model — the corpus must already be embedded
under that model (run `embed_corpus.py --model X` first).
"""

import argparse
import array
import json
import re
import sqlite3
import sys
from pathlib import Path

import sqlite_vec

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _embed_client import embed as embed_remote  # noqa: E402

VAULT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = VAULT_ROOT / "embeddings.db"
CONFIG_PATH = Path(__file__).resolve().parent / "embed_models.json"


def _safe(model_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", model_id)


def _vec_table(model_id: str) -> str:
    return f"vec_papers__{_safe(model_id)}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("query", nargs="?")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--model", help="registered model id; default = server's default")
    args = p.parse_args()

    query = (args.query if args.query is not None else sys.stdin.read()).strip()
    if not query:
        print("empty query", file=sys.stderr)
        return 1
    if not DB_PATH.is_file():
        print("embeddings.db missing — run embed_corpus.py first", file=sys.stderr)
        return 1

    vectors, used_model = embed_remote([query], prompt="query", model=args.model)
    qvec = array.array("f", vectors[0]).tobytes()

    con = sqlite3.connect(DB_PATH)
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.enable_load_extension(False)

    table = _vec_table(used_model)
    exists = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    if exists is None:
        sys.exit(
            f"corpus not yet embedded for model={used_model!r}. "
            f"Run: uv run scripts/embed_corpus.py --model {used_model}"
        )

    rows = con.execute(f"""
        SELECT citekey, distance
        FROM {table}
        WHERE embedding MATCH ?
        ORDER BY distance
        LIMIT ?
    """, (qvec, args.top)).fetchall()

    print(json.dumps(
        {"model": used_model,
         "results": [{"citekey": ck, "distance": float(d)} for ck, d in rows]},
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
