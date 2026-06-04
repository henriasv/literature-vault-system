# Note frontmatter

Every `PaperNotes/{citekey}.md` opens with a YAML frontmatter block. The canonical generator is `scripts/file_paper.py:make_note_skeleton`.

## Required fields

| Field | Type | Notes |
|---|---|---|
| `citekey` | string | Matches the filename's base. Stable forever; see [citation keys](citation-keys.md). |
| `title` | string | From CrossRef; matches the BibTeX entry. |
| `authors` | list of strings | `[Family, Given]` per entry, in publication order. |
| `year` | int | First non-null of CrossRef `published`, `published-print`, `published-online`, `issued`. |
| `journal` | string \| null | Container title; null for arXiv-only entries. |
| `doi` | string \| null | DOI without URL prefix. Null when manually filed or arXiv-only. |
| `arxiv_id` | string \| null | e.g. `2305.10141`. Null when DOI-only. |
| `added` | ISO date string | Set on filing, never rewritten. |
| `sha256_pdf` | hex string | sha256 of the PDF as filed. Used for dedup. |

## Optional but encouraged

| Field | Type | Notes |
|---|---|---|
| `abstract` | string | Either from CrossRef or extracted from PDF page 0 by the filing pipeline. The Librarian audits and cleans this field. |
| `tags` | list of strings | Topic tags (`chemfrac`, `ice_friction`) — lowercase, snake_case. Citation tags prefixed `cite:` (`cite:thesis-ch3`) surface under the Viewer's **Manuscripts** section. |

You can add other fields freely. The Viewer preserves them.

## Review-mode fields

Notes under `ReviewNotes/<project>/<stem>.md` use the same required fields as library notes (so the same parser works), with these conventions on top.

The `citekey` is synthetic: `review:<project>:<stem>` — e.g. `review:hon2200_v26_project2:smith`.

`sha256_pdf` is the empty string (`""`) — there's no dedup namespace for student PDFs.

Additional optional fields:

| Field | Type | Notes |
|---|---|---|
| `review_project` | string | Project slug. Matches the parent directory under `ReviewNotes/`. |
| `bibtex_type` | string | `studentwork` for review papers — drives the manual-entry template (`viewer/src/lib/bibtex-templates.ts`). |
| `done` | bool | `true` when the user has marked the paper as graded (Reviewing rail's **✓ Done reviewing** button). New filings start at `false`. |
| `course`, `assignmentid`, `studentid`, `group` | string | Free-form metadata from the `@studentwork` BibTeX template. Set by the user during the post-drop metadata sheet or edited later. |

Library-only fields (`journal`, `doi`, `arxiv_id`) are typically `null` or absent in review notes.

## Body sections

The note body has three canonical sections; all writers preserve everything outside them byte-for-byte.

| Section | Owner | Behavior |
|---|---|---|
| `## Why` | Librarian (on user answer to "why this paper?") | Inserted into. |
| `## Cleaned Notes` | Librarian | Rewritten in full whenever new raw notes arrive — a synthesis of `## Notes`. |
| `## Notes` | Librarian (via `append_note.py`) | Append-only, timestamped. `### {ISO timestamp}` per entry. |

You may add additional sections (e.g. `## TL;DR`, `## Key figures`) — neither the Viewer nor the Librarian touches them.

## Example

```yaml
---
citekey: livne2008-prl-physrevlett-101-264301
title: Breakdown of linear elastic fracture mechanics at the tip of a rapid crack
authors:
  - [Livne, Ariel]
  - [Bouchbinder, Eran]
  - [Fineberg, Jay]
year: 2008
journal: Physical Review Letters
doi: 10.1103/PhysRevLett.101.264301
arxiv_id: null
added: 2026-05-12
sha256_pdf: 9a7e3f...
abstract: We show experimentally that the strain field surrounding a rapidly propagating crack...
tags:
  - fracture
  - cite:chemfrac
---

# Breakdown of linear elastic fracture mechanics at the tip of a rapid crack

## Why

## Cleaned Notes

## Notes
```
