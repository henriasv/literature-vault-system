# Literature Vault — Handoff for Viewer App Design

You're being handed a personal scientific-paper library system. The user is considering a **custom viewer app** to replace the current Obsidian-based reading workflow (one-click side-by-side PDF + note view felt clunky in Obsidian). This document describes what already exists, so your design can build on the existing data model rather than reinvent it.

The user has separate context about what they want from the app; this doc is just background on what's there.

---

## What the system is

A personal literature librarian. Workflow today:
1. User sends a PDF via Telegram → an agent (nanoclaw + Claude in a Docker container) files it: DOI extraction, CrossRef metadata, dedup, writes a markdown note + .bib entry, moves the PDF to a Drive-backed folder, updates an index, refreshes embeddings.
2. User reads + takes notes + searches by topic — currently in Obsidian. **This is the part the viewer replaces.**

The agent and the viewer **don't need to interact**. They share the vault filesystem; that's the entire contract.

---

## Vault on disk

Root: `~/repos/librarian_assistant_vault/` (a git repo).

```
PaperNotes/{citekey}.md       Literature note. YAML frontmatter + Markdown sections.
Bibfiles/{citekey}.bib        BibTeX entry, one per paper. Canonical metadata.
PDFs/{citekey}.pdf            The PDF (symlinked to a Google Drive folder).
Projects/*.md                 User-authored project notes (free-form Markdown).
index.json                    Dedup index: by_hash / by_doi / by_arxiv → citekey.
library.bib                   Aggregated bib for LaTeX use (auto-generated).
embeddings.db                 sqlite-vec; per-model vector tables.
Models/                       Embedding model weights (gitignored).
scripts/                      Python helpers (PEP 723 + uv).
launchd/                      Launch agent plist for the embed-server.
DESIGN.md                     The system spec for human implementers.
```

`PDFs/`, `Inbox/`, `Models/`, `embeddings.db` are gitignored.

**Filename = citekey** for `.md`, `.bib`, `.pdf`. The viewer builds paths trivially:
```
PaperNotes/{citekey}.md
Bibfiles/{citekey}.bib
PDFs/{citekey}.pdf
```

---

## Citekey

Permanent, never changes once assigned:
```
{firstauthor}{year}-{journal-abbrev}-{doi-suffix}
```
Examples:
- `juel2025-pnas-2501728122`
- `aczel2026-nature-s41586-025-09844-9`
- `haeffel2022-rsos-220099`

Spec: `scripts/CITATION_KEYS.md`. Generator: `scripts/doi2bib.py`. **Treat as opaque** — don't parse or pretty-print the citekey for users; show title + author + year instead.

---

## Note format (the data the viewer reads/writes)

YAML frontmatter, required fields:
```yaml
---
citekey: foo2025-jcp-1234
title: "..."
authors:
  - "Last, First"
year: 2025
journal: "Journal Name"
doi: 10.xxx/yyy
arxiv_id: null
added: 2026-05-07
tags: []
sha256_pdf: "abc..."
abstract: |
  ...
---
```

Optional: `author_count` (present when authors list was truncated for very-many-author papers; first 5 + a sentinel string `"…and N others"`).

Body has three canonical sections:
- `## Why` — why the paper matters / why the user sent it. Short.
- `## Cleaned Notes` — synthesized summary, fully rewritten by the agent each time new raw notes arrive.
- `## Notes` — raw timestamped log: `### 2026-05-07T14:23:00+02:00\n<entry>`.

Plus: free-form additions below `## Notes` are allowed but not currently used.

Standard YAML + standard Markdown. No proprietary syntax. The viewer can use any off-the-shelf parser.

---

## Tags + collections

- **Topic tags**: lowercase snake_case — `chemfrac`, `ice_friction`, `mlip`.
- **Citation-prep tags**: prefix with `cite:` — `cite:thesis-ch3`, `cite:helfo-rebuttal`. One per manuscript-in-progress; removed when the manuscript is submitted.
- The viewer should let the user filter by tag and ideally treat `cite:*` as a first-class browsing axis ("papers I'm citing in X").

---

## Scripts the viewer can subprocess-call

All in `scripts/`, mostly stdlib (some use `pypdf`, `sqlite-vec`, `sentence-transformers`). All run via `uv run scripts/X.py …`. PEP 723 inline metadata = uv resolves deps automatically.

| Script | Purpose |
|---|---|
| `file_paper.py` | **Atomic** "file this PDF" transaction. `--pdf <path> --doi <doi>` (or `--arxiv`); `--in-place` if PDF is already at `PDFs/{citekey}.pdf`. Writes bib/note/index/library.bib, moves PDF, refreshes embeddings. |
| `extract_ids.py` | Extract DOI + arXiv ID from a PDF. Returns `{doi, arxiv_id, source}` (source ∈ "metadata"/"text"/"bytes"/"none"). |
| `crossref_search.py` | Title/author/year → ranked DOI candidates from CrossRef. Use when DOI extraction returned null. |
| `doi2bib.py` | DOI → canonical citekey + BibTeX entry. |
| `check_dup.py` | Lookup `index.json` by sha256 / doi / arxiv / citekey. Read-only. |
| `pdf_hash.py` | sha256 of a file. |
| `pdf_page_text.py` | Plain text of one PDF page (for ad-hoc extraction). |
| `append_note.py` | Append timestamped `### {iso}\n<body>` to a note's `## Notes` section. |
| `build_library_bib.py` | Concat `Bibfiles/*.bib` (sorted) → `library.bib`. Idempotent. |
| `embed_corpus.py` | Refresh `embeddings.db` (incremental, content-hashed). |
| `find_similar.py` | Text query → top-N citekeys via embeddings. |
| `embed_server.py` | The long-running embed server (run by launchd). |

For the viewer specifically, the most useful ones are probably `find_similar.py` (semantic search), `append_note.py` (note edits), `file_paper.py` (if you want in-app filing), and direct file edits for the rest.

---

## Embedding server

- HTTP on `127.0.0.1:5817`, **always running**, supervised by launchd (`launchd/com.henriasv.literature-embed.plist`, KeepAlive=true). Restarts on crash or self-exit.
- Per-model idle TTL: a model unused for 30 min is unloaded; the process itself exits when fully idle and is relaunched by launchd on the next request.

Endpoints:
- `GET /health` → `{ok, default, registered, loaded, uptime_sec, idle_sec}`
- `POST /embed {texts: [str], prompt: "document"|"query", model?: str}` → `{vectors: [[float, …], …], model}`
- `POST /shutdown` → graceful exit

Multi-model. Registry is `scripts/embed_models.json`:
```json
{
  "default": "nemotron-8b",
  "models": {
    "gemma": {"path": "Models/embeddinggemma-300m", "dim": 768, …},
    "nemotron-8b": {"path": "Models/llama-embed-nemotron-8b", "dim": 4096, "trust_remote_code": true, …}
  }
}
```

`embeddings.db` schema (sqlite-vec):
- `papers (citekey, model, content_hash, embedded_at)` PK `(citekey, model)`
- `vec_papers__<safe_model_id> (citekey TEXT PRIMARY KEY, embedding FLOAT[dim])` — one virtual table per model

The corpus content embedded per paper = `Title: {title}\n\nAbstract: {abstract}\n\nWhy: {why}\n\nNotes: {cleaned_notes}`. Re-embeds incrementally when the content hash changes.

---

## Architecture context

```
macOS host
├─ Vault filesystem (~/repos/librarian_assistant_vault)
├─ embed-server (port 5817, launchd-managed, multi-model)
├─ Docker container (per Telegram session) — runs the agent
└─ [your viewer] — reads/writes the vault, queries the embed-server
```

The viewer runs on the host. It shares the vault filesystem with the agent.

**Concurrency**: in practice, only one editor at a time. Watch for races on `index.json`, `library.bib`, and the same note's frontmatter — the existing scripts all use atomic write (write tmp + rename). If the viewer writes the same files, follow the same pattern.

---

## What's free for the viewer (no API needed)

- Reading any file. Filename → citekey is trivial.
- Listing papers: `glob("PaperNotes/*.md")` or query `index.json`.
- Filtering by tag: parse the `tags:` frontmatter list.
- Editing `## Why` / `## Cleaned Notes` / extending `## Notes`: direct file write, atomic. Agent reads the same file next time it touches it.
- Aggregating: `library.bib` is already concatenated.

---

## What needs HTTP (the embed server)

- Semantic search: `POST /embed` to embed the query, then look up nearest neighbors in `vec_papers__<model>` via sqlite-vec.
- Or just call `find_similar.py` as a subprocess — same result, simpler.

---

## Constraints to keep in mind

- **PDFs are on Google Drive** via a symlink under the vault. Reading is fine; the Drive folder is local-cached. Don't write into it carelessly — it round-trips to the cloud.
- **`embeddings.db` must stay local**. Cloud-synced SQLite files corrupt.
- The **vault is git-tracked**. Notes, bib, project notes, scripts are committed. PDFs / Inbox / Models / embeddings are not.
- The **citekey is permanent**. Renaming would break the link between `.md`, `.bib`, `.pdf`, the index, and embeddings.

---

## Don't touch

- Citekey format and naming.
- Frontmatter required fields (the agent and embedding pipeline depend on them).
- The Telegram-side filing flow (lives in `~/repos/nanoclaw/groups/dm-with-henrik/CLAUDE.local.md`, separate concern).
- The atomic-write convention for shared state files.

---

## Suggested viewer-app responsibilities

(The user will tell you their actual requirements; these are inferred from the friction they hit with Obsidian.)

1. **Side-by-side PDF + note** as the default reading mode, no modifier-click dance.
2. **Browse**: list view filterable by tag, year, journal; collection-style views for `cite:*` tags.
3. **Search**: semantic (embed server) + metadata (year/journal/author).
4. **Edit notes**: `## Why`, `## Cleaned Notes`, `## Notes`. Frontmatter editing for tags. Direct file writes are fine.
5. **PDF annotations**: ideally stored back in the PDF (xfdf or PDF annotation streams) so they're portable.
6. (Optional) **File new PDFs from in-app**: call `file_paper.py` as a subprocess.

---

## Where to look in this repo for more

- `DESIGN.md` — full system spec, architecture, "how to extend" recipes.
- `scripts/CITATION_KEYS.md` — citekey grammar.
- `scripts/embed_models.json` — embedding model registry.
- `scripts/*.py` — actual implementations of each operation.
- `nanoclaw/groups/dm-with-henrik/CLAUDE.local.md` (separate repo) — the agent's instructions; only relevant if you want to understand the filing-side behavior.
