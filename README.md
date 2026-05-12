# literature-vault-system

A self-hosted reading + organising system for academic papers. Two pieces
that share one repo:

- **Viewer** — a macOS desktop app (Tauri + Svelte) that reads PDFs and
  edits Markdown notes side-by-side. Drop a PDF in and it's auto-filed
  by DOI; drag rows into collections; semantic search across your notes.
- **Librarian agent** — a NanoClaw-based Claude agent that handles the
  asynchronous bits (filing PDFs you send by Telegram/Slack, suggesting
  tags, appending notes, answering "what should I cite for X?"). Optional.

Both operate on the same on-disk vault layout: PDFs, BibTeX entries, and
one Markdown note per paper, plus a folder of "collections" pointing at
citekeys. The vault is just files; there's no database. The repo ships
the deterministic Python pipeline (extraction, CrossRef + DataCite
lookup, citekey minting, BibTeX writing, embedding refresh) that the
viewer and agent both invoke — so a paper filed via either path ends up
identical on disk.

## Status

Pre-1.0. Built as a personal tool; sharing-friendly but not a polished
product. macOS only for now (the viewer uses macOS overlay title bars
and a few AppKit shortcuts; Linux/Windows ports possible later). No
signed `.dmg` yet — you build from source.

## Quick start

```bash
git clone https://github.com/<you>/literature-vault-system ~/repos/literature-vault-system
cd ~/repos/literature-vault-system

# 1. Build & install the viewer (.app → /Applications)
./setup/install-viewer.sh

# 2. Scaffold a fresh vault
./setup/init-vault.sh ~/literature-vault

# 3. Point the viewer at it
./setup/configure-viewer.sh --vault ~/literature-vault

# 4. (Optional) install the librarian agent into your existing nanoclaw
./setup/install-agent.sh --vault ~/literature-vault --nanoclaw ~/repos/nanoclaw
```

See [GETTING_STARTED.md](GETTING_STARTED.md) for the unhurried version
with prerequisites and troubleshooting.

## What's in this repo

```
viewer/      Tauri + Svelte desktop app (the reader)
scripts/    Deterministic Python pipeline (filing, citekey scheme, …)
agent/      Nanoclaw group template (CLAUDE.local.md + container.json)
docs/       DESIGN.md (vault layout), CITATION_KEYS.md (key algorithm)
setup/      install-viewer.sh, init-vault.sh, install-agent.sh, …
```

## What's NOT in this repo

Your actual papers and notes. Those live in a separate **vault**
directory (default `~/literature-vault/`) that you create with
`setup/init-vault.sh`. The vault is per-user; this repo is the system
that operates on it.

## License

See [LICENSE](LICENSE).
