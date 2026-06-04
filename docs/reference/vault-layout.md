# Vault layout

The vault is a single directory (default `~/literature-vault/`) containing one folder per file type plus a few index files at the root.

```
PaperNotes/{citekey}.md     literature note (frontmatter + sections)
Bibfiles/{citekey}.bib      BibTeX, one per paper
PDFs/{citekey}.pdf          actual papers (often a symlink to cloud storage)
SI/{citekey}-SI.pdf         supplementary information PDFs (one per paper, optional)
Annotations/{citekey}.json  Viewer highlight sidecars (EmbedPDF JSON, one per paper)
ReviewNotes/<project>/<stem>.md   student-assignment notes (Reviewing mode; see below)
PDFs/reviewing/<project>/<stem>.pdf   student PDFs (Reviewing mode)
Annotations/reviewing/<project>/<stem>.json   Reviewing-mode highlight sidecars
Inbox/                      incoming PDFs; filed (moved out) once bib info resolves
Projects/                   user-authored topic notes
Collections/{slug}/index.md curated paper groupings (see "Collections" below)
scripts/                    symlink → literature-vault-system/scripts
index.json                  dedup index (by sha256 / DOI / arXiv)
library.bib                 auto-aggregated from Bibfiles/*.bib (sorted by filename)
embeddings.db               sqlite-vec, gitignored, regenerable
.embedding_models/{name}/   model cache, gitignored, re-downloadable from HuggingFace
.bin/  .uv-cache/  .uv-pythons/   uv toolchain inside the vault (Librarian agent uses these)
```

## Recommended `.gitignore`

`init-vault.sh` writes this for you:

```
PDFs
Inbox/
embeddings.db
.embedding_models/
.bin/
.uv-cache/
.uv-pythons/
.DS_Store
__pycache__/
```

## Filenames

Every per-paper file (`PaperNotes/`, `Bibfiles/`, `PDFs/`, `Annotations/`, `SI/`) uses the **citekey** as its base name. The citekey is deterministic and never changes once assigned — see [citation keys](citation-keys.md).

## Section ownership

| Surface | Writes |
|---|---|
| Filing scripts | frontmatter (initial write), `Bibfiles/`, `PDFs/`, `index.json`, `library.bib` |
| Librarian agent | `## Why`, `## Notes` (via `append_note.py`), `## Cleaned Notes`, `abstract:` frontmatter field |
| Viewer | YAML frontmatter you edit in the editor, body content you type, `Annotations/{citekey}.json` |
| You (any editor) | everything outside the canonical sections — free-form prose, additional sections |

The Librarian and Viewer both preserve byte-for-byte anything outside their canonical sections.

## Collections

Every collection is a **directory** under `Collections/`. The directory's relative path from `Collections/` is its slug (e.g. `drafts/thesis-3`). Each collection contains:

- `index.md` — required. Frontmatter + free-form prose + `## Papers` list.
- subdirectories — each is a sub-collection, same shape, recursively.

A directory without `index.md` is **not** a collection — just an unrecognised directory; tools ignore it. This lets you have `Collections/topics/` as a grouping container without forcing a description on it.

### `index.md` shape

```markdown
---
name: thesis-3
slug: drafts/thesis-3
description: Confined water in clay layers — references for chapter 3.
created: 2026-04-22T10:00:00+02:00
updated: 2026-05-07T14:33:21+02:00
---

# Confined water in clay layers

Free-form prose. Untouched by automated tools.

## Papers

- marry2018-jpcc-...
- guren2021-geca-... — table 3 has the diffusion data
- claverie2022-cacr-...
```

**Frontmatter:**
- `name` — display name; human-readable, can contain spaces.
- `slug` — relative path from `Collections/`, no leading or trailing slash. Must match the directory's actual path.
- `description` — one-line summary (optional but encouraged).
- `created` — ISO datetime, set on creation, never rewritten.
- `updated` — ISO datetime, refreshed on every membership change.

**Body:**
- First H1 and prose before `## Papers` are user-only and never rewritten by tools.
- `## Papers` is the canonical membership list. One bullet `- {citekey}` per paper. An optional inline annotation may follow an em-dash: `- {citekey} — note`.
- Anything after `## Papers` is also user-only and preserved.

Membership is **explicit**: a paper is in a collection iff its citekey appears in that collection's own `## Papers`. There is no inferred or transitive membership across parents and children.

### Atomic operations

All writers (the agent, the Viewer, any script) must:
1. Read the entire `index.md` before mutating.
2. Replace only the `## Papers` block and the `updated:` field when changing membership.
3. Preserve all other bytes byte-for-byte.
4. Write via a tempfile in the same directory + `os.replace` / `fs::rename`.

## Reviewing-mode subtree

The Viewer's **Reviewing** view (grading student work) keeps its papers in a parallel subtree so they never appear in the main library, never enter `Bibfiles/`, and never pollute `library.bib`.

```
PDFs/reviewing/<project>/<stem>.pdf       student PDFs, grouped by project
ReviewNotes/<project>/<stem>.md           one Markdown note per student paper
Annotations/reviewing/<project>/<stem>.json   Viewer highlight sidecar (per paper)
```

Each "project" is a directory you create in the Viewer (e.g. `hon2200_v26_project2`); the `<stem>` is whatever the dropped PDF was named (`smith.pdf` → stem `smith`).

The paper's identifier in the Viewer (and in the agent script API) is a synthetic citekey of shape `review:<project>:<stem>` — e.g. `review:hon2200_v26_project2:smith`. The `:` separator is illegal in filenames, so review citekeys can never collide with library citekeys.

ReviewNote frontmatter is identical in shape to a library note (so the same parser works) plus a few review-only fields — see [note frontmatter](note-frontmatter.md#review-mode-fields).

Renames and project-moves must touch all four artifacts in lockstep. Use [`rename_review_paper.py`](scripts.md) — direct file moves risk drift.

## Notes on the path

The canonical vault path is `~/literature-vault/`. You can put it anywhere — pass `--vault <path>` to any setup script, or rely on the gitignored `setup/.local.conf` which remembers the path you used last.

PDFs are often kept on cloud storage. Pass `--pdfs <path>` to `init-vault.sh` and `PDFs/` becomes a symlink to that location instead of a plain directory.
