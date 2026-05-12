# Back up the vault

The vault is just a folder. There is no database to dump.

## What to back up

The user-authored content:

- `PaperNotes/` — your notes
- `Bibfiles/` — BibTeX, one per paper
- `PDFs/` — the actual papers (often a symlink to cloud storage)
- `Collections/` — your curated groupings
- `Projects/` — topic notes
- `SI/` — supplementary information PDFs
- `Annotations/` — Viewer highlights
- `index.json` — the dedup index
- `library.bib` — aggregated BibTeX

## What you can skip

These are derived or machine-local and rebuild themselves:

- `embeddings.db` — regenerable with `uv run scripts/embed_corpus.py`
- `.embedding_models/` — re-downloadable from HuggingFace
- `.bin/`, `.uv-cache/`, `.uv-pythons/` — re-bootstrapped on first agent run
- `scripts/` — symlink into the literature-vault-system repo

The default `.gitignore` written by `init-vault.sh` already excludes those.

## Backup strategies

- **git.** The vault is small (notes + bib) once PDFs are excluded. `git init` inside it and push to a private remote. The Librarian agent already auto-commits after every edit when `.git/` exists.
- **PDFs to cloud storage.** Symlink `PDFs/` to Google Drive / Dropbox / iCloud at vault-init time (`init-vault.sh --pdfs <path>`). Restoring is just relinking.
- **Time Machine.** Works fine; nothing special required.

`embeddings.db` is SQLite — keep it on a local volume, not on cloud-synced storage (synced SQLite corrupts).
