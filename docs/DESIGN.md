# Literature Librarian — Design

A personal AI assistant for managing scientific papers. Send a PDF via Telegram → it lands in the archive, deduplicated, with a markdown note and a `.bib`. Reply to the bot's message to add notes. Ask `/cite` later to find relevant papers when drafting. Built on nanoclaw + Claude Agent SDK.

This doc is the spec. Implementers (Henrik, Claude Code, the bot) make their own choices on details not covered here.

---

## State

Working:
- nanoclaw group "LiteratureAssistant" + Telegram + container mounts + uv toolchain
- Full deterministic filing pipeline (`extract_ids.py` → `file_paper.py`): DOI/arXiv extraction, sha256 dedup, CrossRef metadata, atomic write of bib/note/PDF/index/library.bib, abstract fallback from PDF page 0 when CrossRef omits one
- Reply-to-add-notes via `append_note.py` + agent-side description matching (no `[citekey]` required)
- Multi-model semantic search: launchd-managed `embed_server.py` on host, host-vs-container auto-routing, lazy-loaded models with per-model idle TTL. Default model: `nemotron-8b`; alternative: `gemma`.
- Obsidian Bases for browsing (`Bases/papers.base`, `Bases/collections.base`)

Next: nothing critical. (CrossRef no-DOI fallback is now `crossref_search.py`.)

Later: weekly review, sync to other machines.

Feature requests (not yet designed):
- **SI sub-view / open-SI button**: When a paper has a corresponding `SI/{citekey}-SI.pdf` file, surface a one-tap action (Telegram button or Obsidian action) to open it. Convention: `SI/{citekey}-SI.pdf` (one SI per citekey; no multi-part for now). Agent should move SI files to `SI/` with the citekey prefix when received. Obsidian could show a "📎 SI available" badge or action in the paper note template. Telegram reply could include a button inline.

---

## Where things live

| Thing | Path |
|---|---|
| Vault (this repo) | `~/repos/literature-vault/` |
| nanoclaw fork | `~/repos/nanoclaw/` |
| Agent's instructions | `~/repos/nanoclaw/groups/dm-with-henrik/CLAUDE.local.md` (the sibling `CLAUDE.md` is auto-composed from nanoclaw fragments — never edit) |
| Per-group case context | `~/repos/nanoclaw/groups/dm-with-henrik/projects.md` |
| Container config | `~/repos/nanoclaw/groups/dm-with-henrik/container.json` (mounts, group name) |
| PDFs | Google Drive: `…/My Drive/librarian_assistant_storage/pdfs/` (symlinked from `vault/PDFs`) |
| Mount allowlist | `~/.config/nanoclaw/mount-allowlist.json` |
| Launchd service | `com.nanoclaw-v2-94718d05` |

Container path prefix: `/workspace/extra/vault/`. Vault and PDFs both mount under there. Prefix is enforced by nanoclaw's mount-security; don't try to remove it.

---

## Navigation map (for a new implementer)

If you're touching X, look here:

| You want to… | Look at |
|---|---|
| Change PDF-arrival flow | `nanoclaw/groups/dm-with-henrik/CLAUDE.local.md` (agent steps) and/or `scripts/file_paper.py` (the atomic transaction it calls) |
| Change how a `## Notes` reply is appended | `scripts/append_note.py` |
| Change the citekey format | `scripts/CITATION_KEYS.md` (spec) + `scripts/doi2bib.py` (`make_canonical_key`) |
| Change the note skeleton (frontmatter, sections) | `scripts/file_paper.py:make_note_skeleton`. Update §Conventions in this doc. Backfill old notes if needed. |
| Change abstract extraction | `scripts/file_paper.py:extract_abstract_from_pdf` |
| Add or swap an embedding model | `scripts/embed_models.json` (registry). See "How to extend" below. |
| Tune embedding-server lifecycle | `launchd/com.literature-vault.embed-server.plist` + `scripts/embed_server.py` (idle TTL constants near top) |
| Change Obsidian view of papers | `Bases/papers.base`, `Bases/collections.base` |
| Add a new project/topic collection | New view in `Bases/collections.base` filtering by tag |
| Change agent triggers / replies | `nanoclaw/groups/dm-with-henrik/CLAUDE.local.md` (only) |

`CLAUDE.local.md` is **self-contained** for what's implemented — never tell the agent to "see DESIGN.md". This file is for humans / future-you.

---

## Architecture sketch

```
┌─ macOS host ─────────────────────────────────────────────────────────────┐
│                                                                          │
│  Telegram ─────► nanoclaw orchestrator ─────► Docker container          │
│                  (~/repos/nanoclaw)            (per-session, ephemeral) │
│                                                       │                  │
│                                                       │ mounts:          │
│                                                       │   vault rw       │
│                                                       │   PDFs rw        │
│                                                       ▼                  │
│                                            /workspace/extra/vault        │
│                                            (= ~/repos/librarian_…)       │
│                                                       │                  │
│                                                       │ uv run scripts/* │
│                                                       │                  │
│  embed-server (launchd-managed, KeepAlive=true) ◄────┘                  │
│   127.0.0.1:5817                                      via                │
│   loads models from vault/.embedding_models/          host.docker.internal│
│   per-model idle TTL                                                     │
│                                                                          │
│  vault/.embedding_models/  vault/PaperNotes/  vault/Bibfiles/  vault/PDFs/ →Drive │
│  vault/embeddings.db (sqlite-vec, gitignored, regenerable)               │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

Important asymmetry: the **agent runs in the container** (Linux ARM64, no system Python — uses `vault/.bin/uv`). The **embed-server runs on the host** (macOS, uses `/opt/homebrew/bin/uv`). They share the vault filesystem but not processes; the container reaches the embed-server over the loopback bridge (`host.docker.internal`). Both find vault root via `Path(__file__).resolve().parent.parent` because `scripts/*` lives at the same relative path in both views.

---

## Vault layout (target)

```
PaperNotes/{citekey}.md       literature note (frontmatter + sections)
Bibfiles/{citekey}.bib        BibTeX, one per paper
PDFs/{citekey}.pdf            on Google Drive (symlinked)
SI/{citekey}-SI.pdf           supplementary information PDFs (see SI surfacing note below)
Annotations/{citekey}.json    viewer highlights/annotations (EmbedPDF sidecar JSON, one per paper)
Inbox/                        incoming PDFs; filed (moved to PDFs/) as soon as bib info is resolved
Projects/                     curated topic notes (you-authored)
Collections/{name}.md         user-curated paper groupings (frontmatter + ## Papers list)
Bases/                        Obsidian Bases (later)
scripts/                      symlink → literature-vault-system/scripts (Python helpers, uv + PEP 723)
index.json                    dedup index (by sha256 / DOI / arXiv)
library.bib                   auto-aggregated from Bibfiles/*.bib
embeddings.db                 sqlite-vec, gitignored, regenerable
.embedding_models/{name}/     machine-local model cache; gitignored; regenerable from HuggingFace
```

**SI surfacing — TBD**: convention is one SI PDF per paper at `SI/{citekey}-SI.pdf`.
The agent already moves SI files there with the citekey prefix. How the viewer
surfaces them (sidebar badge? toggle in the PDF pane? separate tab opened from
the paper note?) is still an open design question.

`.gitignore`: `PDFs`, `Inbox/`, `embeddings.db`, `.bin/`, `.uv-cache/`, `.uv-pythons/`, `.DS_Store`, `__pycache__/`.

---

## Core flows

**New PDF arrives** → save to `Inbox/{original-filename}` → extract DOI (scan raw PDF bytes for `10.\d{4,9}/...`; fall back to CrossRef search by author + title from filename) → run `doi2bib.py` to get citekey + BibTeX → check for duplicate (by sha256, citekey, DOI, or arXiv ID against `index.json`). If dup, reply with existing note's title and recent notes. If new: file PDF as `PDFs/{citekey}.pdf`, write `PaperNotes/{citekey}.md` and `Bibfiles/{citekey}.bib`, update `index.json`, regenerate `library.bib`, reply with bib info and TL;DR. And if i didn't already say, ask why this paper was sent (optional for me to answer; if i do, put it in the `## Why` section).

**Reply to bot's message** about a paper → agent identifies which paper (explicit `[{citekey}]`, or default-from-context if replying to a paper-arrival message, or grep `PaperNotes/` for free-text descriptions like "the kirigami paper"); confirms when ambiguous; appends body to `## Notes` via `append_note.py`; rewrites `## Cleaned Notes` as a coherent synthesis.

**Topic / citation question** ("what should I cite for X", "papers on Y", a draft sentence) → agent runs `find_similar.py "<text>" --top 8` (uses default model from `embed_models.json`; pass `--model gemma` for the small model), reads the top notes, replies with a reasoned ranked list.

---

## Collections

User-curated groupings of papers. Distinct from frontmatter `tags:` — a paper does not get tagged "thesis-3" to belong to a thesis-3 collection; instead its citekey is listed in the `index.md` of that collection's directory. This separates organisation (a paper belongs to a manuscript-in-progress, a reading group, a review-in-prep) from classification (this paper is about chemistry of fracture).

Collections **nest**. A collection like `For my drafts` can contain sub-collections `thesis-3`, `helfo-rebuttal`, etc. — each their own collection, possibly with their own children.

### Layout

Every collection is a **directory** under `Collections/`. The directory's name is its slug; the relative path from `Collections/` is the collection's full identifier (e.g. `drafts/thesis-3`). Directly inside the directory:

- `index.md` — required. Frontmatter + free-form prose + `## Papers` list. (See "File format" below.)
- subdirectories — each is a sub-collection. Same shape, recursively.

```
Collections/
├── drafts/
│   ├── index.md                  ← the "Drafts" collection itself; usually empty papers list, just description
│   ├── thesis-3/
│   │   └── index.md              ← thesis-3 sub-collection (papers + prose)
│   └── helfo-rebuttal/
│       └── index.md
├── reading-group-2026/
│   └── index.md
└── topics/
    ├── index.md                  ← optional umbrella description
    └── confined-water/
        └── index.md
```

Slugs are filesystem-safe (`[A-Za-z0-9_-]+`). A directory without an `index.md` is **not** a collection — it's just an unrecognised directory and should be ignored by tools (don't auto-create one; let the user be intentional).

A parent collection (one with sub-directories) can still have its own papers in its `index.md`'s `## Papers` list — useful when the umbrella has a few "shared" entries that don't belong to any single child.

### File format

```markdown
---
name: thesis-3
slug: drafts/thesis-3
description: Confined water in clay layers — references for chapter 3.
created: 2026-04-22T10:00:00+02:00
updated: 2026-05-07T14:33:21+02:00
---

# Confined water in clay layers

Free-form prose about the collection: scope, what's missing, anything the
user wants to remember about it. Untouched by automated tools.

## Papers

- marry2018-jpcc-...
- guren2021-geca-... — table 3 has the diffusion data
- claverie2022-cacr-...
```

**Frontmatter** (required):
- `name` — display name (human-readable; can have spaces).
- `slug` — relative path from `Collections/`, no leading or trailing slash. Must match the directory's actual path.
- `description` — one-line summary (optional but encouraged).
- `created` — ISO datetime, set on creation, never rewritten.
- `updated` — ISO datetime, refreshed on every membership change.

**Body**:
- The first H1 and any free-form prose **before** `## Papers` are user-only and **never rewritten** by automated tools. Treat them as opaque markdown.
- The `## Papers` section is the canonical list of members. One bullet `- {citekey}` per paper. An optional inline annotation may follow an em-dash: `- {citekey} — annotation`.
- Anything **after** `## Papers` (e.g. a `## Notes` section, more prose) is also user-only and preserved.

A paper's membership in the parent does **not** imply membership in any child, nor vice-versa. Each collection's `## Papers` list is independent. (Tools that want to compute "all papers transitively under `drafts/`" do that by union over the subtree.)

### Operations (atomic)

- **List collections**: walk `Collections/` recursively, find every `index.md`, parse frontmatter. Return the tree (or a flat list with parent slugs derived from the path).
- **Add paper**: append `- {citekey}` to `## Papers` if not already present; bump `updated`. Write `Collections/{slug}/index.md` atomically (tempfile in same dir + rename).
- **Remove paper**: delete the matching bullet line; bump `updated`.
- **Create collection**: `mkdir -p Collections/{slug}` and write `index.md` with frontmatter + empty `## Papers`. If the parent path doesn't yet have its own `index.md`, **don't** auto-create one; sub-collections can exist under a directory that isn't itself a collection (the directory is just a grouping container until the user makes it explicit).
- **Delete collection**: remove `Collections/{slug}/index.md`. If the directory still has child collections, the directory itself stays (now an unnamed grouping container). If the directory is empty after the delete, remove it too.
- **Rename / move**: `mv Collections/{old-slug} Collections/{new-slug}` and rewrite the `slug:` and `name:` fields in the moved `index.md`. Children come along automatically since slugs are derived from path.

All writers (the agent, the viewer, ad-hoc scripts) must:
1. Read the entire `index.md` before mutating.
2. Replace **only** the `## Papers` block (and the `updated:` field) when changing membership.
3. Preserve all other bytes byte-for-byte (prose, frontmatter ordering, blank lines).
4. Atomic-write via tempfile + `os.replace` / `fs::rename` in the same directory.

### Conventions

- Manuscript-style collections (papers being cited in a draft) are valid first-class collections — there is no separate `Manuscripts/` concept. By convention they live under `Collections/drafts/{manuscript-slug}/`, but a flat top-level collection works too.
- Reading groups, courses, "to-read" lists, topic surveys, etc. are also collections. The format is intentionally generic.
- Membership is **explicit**: a paper is in a collection iff its citekey appears in that collection's own `## Papers` bullets. There is no inferred / tag-based / transitive membership.

---

## Scripts (deterministic helpers)

Anything that's a pure function of inputs lives in `scripts/`, not in the agent's head. The agent calls these; it doesn't reimplement them turn-by-turn. All scripts: PEP 723 header, find vault root via `Path(__file__).resolve().parent.parent`, atomic writes for shared state.

| Script | Status | Purpose |
|---|---|---|
| `doi2bib.py` | ✅ done | DOI → canonical citekey + BibTeX entry (CrossRef-backed). |
| `extract_ids.py` | ✅ done | Extract DOI + arXiv ID from a PDF: pypdf metadata → first-page text → raw bytes (cheap-to-expensive). Output: JSON `{doi, arxiv_id, source}` (either id may be null). |
| `crossref_search.py` | ✅ done | Title/author/year → top-N candidate DOIs from CrossRef. Used when `extract_ids.py` returns null/null. Output: JSON list of `{doi, title, first_author, year, score}`. |
| `pdf_page_text.py` | ✅ done | Extract text of one PDF page (default 0). Used by the agent's abstract-audit step to compare against the deterministic abstract extracted by `file_paper.py`. |
| `pdf_hash.py` | ✅ done | sha256 of a file (primary dedup key). |
| `check_dup.py` | ✅ done | Given any of `{sha256, citekey, doi, arxiv_id}`, look up in `index.json`. Output: matching citekey + which field matched, or `{citekey: null}`. Read-only. |
| `file_paper.py` | ✅ done | Atomic "file this paper" transaction. Input: `--pdf <path>` + `--doi <doi>` (`--arxiv` optional, `--in-place` for backfilling a PDF that's already at `PDFs/{citekey}.pdf`). Calls `doi2bib`, computes sha256, refuses on dup, writes `Bibfiles/{citekey}.bib` + `PaperNotes/{citekey}.md` skeleton, moves PDF, updates `index.json`, regens `library.bib`. Rolls back writes on partial failure. |
| `build_library_bib.py` | ✅ done | Concatenate `Bibfiles/*.bib` sorted by filename → `library.bib` (atomic write). Idempotent. |
| `append_note.py` | ✅ done | Append `### {ISO timestamp}\n{body}` under the `## Notes` section of `PaperNotes/{citekey}.md`. Input: `--citekey` + body via stdin or `--body`. |
| `embed_corpus.py` | ✅ done | (Re)build `embeddings.db` from PaperNotes (title + abstract + `## Why` + `## Cleaned Notes`). Incremental via content-hash. Talks to `embed_server.py`. Auto-migrates `vec_papers` when `MODEL_NAME` changes. |
| `find_similar.py` | ✅ done | Text query → top-N `{citekey, distance}` via `embeddings.db`. Talks to `embed_server.py`. |
| `embed_server.py` | ✅ done | Long-running embed server on host. **Multi-model**: reads `scripts/embed_models.json` for the registry + default; lazy-loads each model on first request; per-model idle TTL so cold models unload while hot ones stay warm. HTTP on 127.0.0.1:5817. Process exits when nothing has been used for 30 min. Started by launchd socket activation (`launchd/com.literature-vault.embed-server.plist`); agent in container reaches it via `host.docker.internal:5817`. |
| `embed_models.json` | ✅ done | Model registry. `default` is what the agent uses when no model is requested. Add a model: drop weights in `.embedding_models/<dir>/`, append a registry entry, optionally flip `default`. |
| `_embed_client.py` | ✅ done | Thin client. Auto-detects host vs container; fork-starts the server on host if not responding; surfaces server JSON errors verbatim. |

What stays with the agent (genuinely LLM-shaped):
- Deciding whether an attachment is a paper at all.
- CrossRef **search** fallback when no DOI is in the PDF (fuzzy author/title matching from the filename).
- Composing the Telegram reply (TL;DR, what arrived, "why" placement).
- Resolving ambiguity: multiple DOI candidates, conflicting metadata, malformed inputs.

So the happy-path agent flow per PDF is roughly: save to Inbox → `extract_ids.py` → `file_paper.py --pdf … --doi …` → reply. Four steps, three of them deterministic.

---

## Conventions

- **Citekey**: spec in `scripts/CITATION_KEYS.md`; canonical generator is `scripts/doi2bib.py`.
- **Note frontmatter** must include at minimum: `citekey`, `title`, `authors`, `year`, `journal`, `doi`, `arxiv_id`, `added` (ISO date), `sha256_pdf`. Add other fields freely. Add abstract if possible.
- **Tags** live in the `tags:` frontmatter list. Conventions:
  - Topic / project tags: lowercase, snake_case — `chemfrac`, `ice_friction`, `mlip`.
  - Citation-prep tags: prefix with `cite:` — `cite:thesis-ch3`, `cite:helfo-rebuttal`. One per manuscript-in-progress; remove once the paper is submitted.
  - Bases under `Bases/collections.base` filter by tag — add a new view there when you start a new collection.
- **Note body** has three canonical sections: `## Why` (why Henrik sent it; agent inserts on answer), `## Cleaned Notes` (synthesized summary the agent rewrites in full whenever new raw notes arrive), `## Notes` (raw timestamped log appended by `append_note.py`). TL;DR / key results are nice to add but optional.
- **Index** has whatever shape the implementer wants, as long as it supports O(1) lookup by SHA-256, DOI, and arXiv ID. JSON is fine for the scale we're at (thousands of papers).
- **One `.bib` per paper**, plus an aggregated `library.bib` at vault root for LaTeX use. Aggregation is just concatenation, sorted for stable diffs.

---

## Python toolchain

Containers have no system Python. Everything runs via `uv` from inside the vault: `.bin/uv`, `.uv-cache/`, `.uv-pythons/`. Scripts use PEP 723 inline metadata so deps travel with the code. Never `pip install` or call `python3` directly.

If `uv` is missing, bootstrap with the install script piped to `UV_INSTALL_DIR=/workspace/extra/vault/.bin sh`.

---

## What the agent does (in the nanoclaw repo)

The agent's per-group instructions live in `~/repos/nanoclaw/groups/dm-with-henrik/CLAUDE.local.md`. The sibling `CLAUDE.md` is auto-composed from nanoclaw fragments at spawn (shared, agents, core, interactive, scheduling, self-mod) — never edit it. Per-group case context lives in `projects.md` next to it.

`CLAUDE.local.md` should describe the flows above, reference scripts in this repo by absolute container path (`/workspace/extra/vault/scripts/...`), and include hard rules: never modify a note's body except to append to `## Notes`; never delete files (move to `.trash/` and confirm); surface script stderr rather than inventing workarounds.

**`CLAUDE.local.md` is self-contained for what's implemented.** It must not point the agent at this DESIGN.md to "fill in the gaps" — runtime behavior is fully specified in `CLAUDE.local.md`. DESIGN.md is the architectural spec (what the system *is* and what's *not yet* built); `CLAUDE.local.md` is the operational manual for what currently works. When implementation catches up to a piece of the design, fold the relevant rules into `CLAUDE.local.md` directly.

The `self-mod` nanoclaw module is loaded → the agent self-modifies `CLAUDE.local.md` via Telegram. Prefer that over editing nanoclaw source when evolving agent behavior.

---

## Working in this repo

This repo (`literature-vault`) is for: scripts, notes, the index, this design doc, and Obsidian configuration. Not for: agent behavior (separate repo), nanoclaw internals (separate repo), system services.

Conventions:
- Scripts in `scripts/`, PEP 723 headers, runnable both on Mac (host) and inside the container.
- Find vault root via `Path(__file__).resolve().parent.parent`, never hard-code absolute paths.
- Atomic writes for `index.json` and `library.bib`.
- Commit messages: imperative, short, prefixed by area. `scripts: add check_dup.py`.

---

## First-time setup (fresh machine)

1. Clone this vault into `~/repos/literature-vault/` and the nanoclaw fork into `~/repos/nanoclaw/`.
2. Install `uv` on the host (`brew install uv`).
3. Bootstrap the embed-server via launchd:
   ```bash
   ln -s ~/repos/literature-vault/launchd/com.literature-vault.embed-server.plist \
         ~/Library/LaunchAgents/com.literature-vault.embed-server.plist
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.literature-vault.embed-server.plist
   curl http://127.0.0.1:5817/health   # should return JSON
   ```
4. Download embedding models. The default model is set in `scripts/embed_models.json`. Each registered model needs weights at `.embedding_models/<dir>/`. E.g.:
   ```bash
   uv run --with huggingface_hub python3 -c '
   from huggingface_hub import snapshot_download
   snapshot_download(repo_id="google/embeddinggemma-300m",
                     local_dir=".embedding_models/embeddinggemma-300m")'
   ```
   For gated repos: `huggingface-cli login` first.
5. Embed the corpus: `uv run scripts/embed_corpus.py` (uses default model from the JSON).
6. Sanity check: `uv run scripts/find_similar.py "your test query" --top 3`.
7. Open the vault in Obsidian (`File → Open vault → ~/repos/literature-vault`). Bases views appear under `Bases/`.

The container (Telegram side) takes care of itself — nanoclaw spawns it on the next message, and `vault/.bin/` already has the Linux-ARM uv.

## How to extend

**Add a new embedding model**
1. Download weights to `.embedding_models/<short-id>/` (or whatever path you like under the vault).
2. Append an entry to `scripts/embed_models.json`:
   ```json
   "<short-id>": {
     "path": ".embedding_models/<short-id>",
     "dim": <embedding dim from config.json:hidden_size or model card>,
     "doc_prompt": "document",   // or omit if model has no prompts
     "query_prompt": "query",
     "trust_remote_code": true   // only if the repo ships custom modeling code
   }
   ```
3. `launchctl kickstart -k gui/$(id -u)/com.literature-vault.embed-server` to pick up the new config.
4. `uv run scripts/embed_corpus.py --model <short-id>` to populate `vec_papers__<safe_id>`.
5. Optional: flip `default` in `embed_models.json` if this should be the new default.

**Add a new deterministic script**
1. PEP 723 header (deps inline). 2. `Path(__file__).resolve().parent.parent` for vault root. 3. Atomic writes for any shared state (`index.json`, `library.bib`, `embeddings.db`). 4. Add it to the table in §Scripts. 5. If the agent should call it, document the trigger in `CLAUDE.local.md`.

**Add a new note section beyond `## Why` / `## Cleaned Notes` / `## Notes`**
1. Update `make_note_skeleton()` in `scripts/file_paper.py`. 2. Backfill existing notes (small ad-hoc script). 3. Decide if it should feed embeddings — if yes, edit `make_content()` in `scripts/embed_corpus.py` and run `embed_corpus.py --force` to refresh. 4. Update §Conventions in this doc and the §Hard rules in `CLAUDE.local.md` if direct edits are allowed.

**Change agent behavior**
Edit `~/repos/nanoclaw/groups/dm-with-henrik/CLAUDE.local.md`. The next container spawn picks up the changes; for the current container, `docker ps | grep nano` then `docker rm -f <id>`. Don't edit the sibling `CLAUDE.md` (auto-composed at spawn).

---

## Operations

```bash
# Restart embed-server (after embed_server.py or embed_models.json changes)
launchctl kickstart -k gui/$(id -u)/com.literature-vault.embed-server
tail -f embed-server.log

# Restart nanoclaw orchestrator (after mount/source changes)
launchctl kickstart -k gui/$(id -u)/com.nanoclaw-v2-94718d05

# Force fresh container (after CLAUDE.local.md changes that don't take effect)
docker ps | grep nano       # find container
docker rm -f <id>            # next message spawns fresh

# Verify mounts from inside container — ask the bot:
# "Run `ls -la /workspace/extra/vault` and paste."

# Check what the embed-server is doing
curl http://127.0.0.1:5817/health
```

---

## Known constraints

- `embeddings.db` (SQLite) must stay local — cloud sync corrupts SQLite.
- `My Drive` path contains a space; safe in Docker mount config but be careful in shell composition.
- Containers are ephemeral; only mounted paths survive rebuilds.

---

## Open decisions

- Auto-push from agent: agent auto-commits to the vault; pushes are still gated to Henrik (no OneCLI git creds wired yet).
- ~~Embedding model: Voyage API vs local sentence-transformers~~ → resolved: sentence-transformers, multi-model registry in `scripts/embed_models.json`. Default = `nemotron-8b` (4096-dim, ~14 GB), with `gemma` (768-dim, ~1.2 GB) as a faster alternative. Models live under `.embedding_models/` (gitignored).
- Sync to other machines: not needed yet (single machine).