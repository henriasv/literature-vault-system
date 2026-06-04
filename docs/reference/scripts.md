# Scripts

All deterministic helpers live under `scripts/`. They use [PEP 723](https://peps.python.org/pep-0723/) inline metadata so dependencies travel with the source. Run them with `uv run scripts/<name>.py`.

Both the Viewer (via the vault's `scripts` symlink) and the Librarian agent (via the read-only `/workspace/extra/system/scripts` mount) call the same scripts.

| Script | Purpose |
|---|---|
| `extract_ids.py` | Extract DOI + arXiv ID from a PDF: pypdf metadata → first-page text → raw bytes (cheap-to-expensive). Output: JSON `{doi, arxiv_id, source}` (either may be null). |
| `crossref_search.py` | Search CrossRef by title/author/year when `extract_ids.py` returns null. Output: ranked JSON list of `{doi, title, first_author, year, score}`. |
| `crossref_record.py` | Fetch one CrossRef record for an exact DOI. |
| `doi2bib.py` | DOI → canonical citekey + BibTeX entry. Houses `make_canonical_key()` and the journal-abbrev map. |
| `pdf_hash.py` | sha256 of a file (primary dedup key). |
| `pdf_page_text.py` | Extract text from a specific PDF page (default 0). Used to audit abstracts. |
| `extract_pdf_meta.py` | Parse embedded PDF metadata (title, authors, abstract). |
| `check_dup.py` | Look up `{sha256, citekey, doi, arxiv_id}` in `index.json`. Read-only. Output: matching citekey + which field matched, or null. |
| `file_paper.py` | Atomic "file this paper" transaction. Calls `doi2bib`, computes sha256, refuses on dup, writes `Bibfiles/{citekey}.bib` + `PaperNotes/{citekey}.md` skeleton, moves PDF, updates `index.json`, regenerates `library.bib`. Rolls back on partial failure. |
| `manual_file.py` | Manual filing path — user types a BibTeX entry into the Viewer's manual-entry form for items without a DOI. |
| `batch_file_inbox.py` | Process every PDF in `Inbox/` through the filing pipeline. |
| `reassign.py` | Re-file a misfiled paper under a new citekey, preserving user-written `## Why` / `## Notes` / `## Cleaned Notes`. |
| `rename_review_paper.py` | Rename or move a Reviewing-mode paper (`review:<project>:<stem>` citekey). Atomic across PDF + ReviewNote + Annotation sidecar + frontmatter citekey, with rollback on partial failure. Pass `--new-stem` and/or `--new-project`. The librarian agent uses this for review-subtree renames — see [reference: vault layout](vault-layout.md#reviewing-mode-subtree). |
| `append_note.py` | Append `### {ISO timestamp}\n{body}` under `## Notes` in `PaperNotes/{citekey}.md`. Body via stdin or `--body`. |
| `build_library_bib.py` | Concatenate `Bibfiles/*.bib` sorted by filename → `library.bib`. Atomic, idempotent. |
| `embed_corpus.py` | Build/refresh `embeddings.db` from notes (title + abstract + `## Why` + `## Cleaned Notes`). Incremental, content-hashed. Talks to `embed_server.py`. Auto-migrates `vec_papers` when the model name changes. |
| `find_similar.py` | Text query → top-N `{citekey, distance}` over `embeddings.db`. Talks to `embed_server.py`. |
| `embed_server.py` | Long-running embed server on the host (port 5817). Multi-model registry, lazy-load per model, per-model idle TTL, full-idle exit after 30 min. See [embedding server](embedding-server.md). |
| `embed_models.json` | Model registry. `default:` names the model used when no `--model` is given. |
| `_embed_client.py` | Thin client used by `embed_corpus.py` and `find_similar.py`. Auto-detects host vs container; fork-starts the server on host if not responding; surfaces server JSON errors verbatim. |

## Conventions

Every script in this directory:

- Declares its dependencies inline (PEP 723), so `uv run scripts/<name>.py` resolves them automatically.
- Finds the vault root with `Path(__file__).resolve().parent.parent` — never hard-codes an absolute path.
- Uses atomic writes for shared state (`index.json`, `library.bib`, `embeddings.db`): tempfile in the same directory + `os.replace`.
- Prints JSON on stdout for machine consumers; surfaces errors to stderr.

## What stays with the agent (not in `scripts/`)

These are genuinely LLM-shaped tasks the Librarian handles directly:

- Deciding whether an attached file is a paper at all.
- Composing the chat reply (TL;DR, "why" placement, tag suggestions).
- Resolving ambiguity: multiple DOI candidates, conflicting metadata, free-text descriptions like "the kirigami paper".
- Fuzzy CrossRef searches when no DOI is in the PDF — the script (`crossref_search.py`) returns candidates; picking the right one is the agent's job.
