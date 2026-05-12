# Getting started

By the end of this tutorial you will have the Viewer installed, an empty vault on disk, and one paper filed in it.

**Time:** ~10 minutes, mostly waiting for Rust to compile.
**Platform:** Apple Silicon Mac (M1 or newer) on a recent macOS. Intel and other OSes are not supported yet.

This tutorial does only what's required. The Librarian agent (Telegram intake), the embedding server (semantic search), and Obsidian integration are all separate how-to guides — links at the end.

---

## Step 0 — Prerequisites

Install Xcode Command Line Tools and four Homebrew packages.

```bash
xcode-select --install

# Homebrew itself: see https://brew.sh if you don't have it.
brew install rustup-init node uv
rustup-init -y
```

You should now have `cargo --version`, `node --version`, and `uv --version` all working.

## Step 1 — Clone the repo

```bash
git clone https://github.com/henriasv/literature-vault-system ~/repos/literature-vault-system
cd ~/repos/literature-vault-system
```

## Step 2 — Build & install the Viewer

```bash
./setup/install-viewer.sh
```

This runs `npm ci && npm run tauri build` and copies the resulting `Literature Vault.app` into `/Applications/`. About 3 minutes the first time, mostly Rust compile.

Launch it once from Spotlight. You'll see a "no vault configured" screen — that's expected; we configure it in step 4.

## Step 3 — Create the vault

```bash
./setup/init-vault.sh ~/literature-vault
```

This creates the canonical directory layout under `~/literature-vault/` (`PaperNotes/`, `PDFs/`, `Bibfiles/`, `Inbox/`, `Collections/`, `Projects/`, `Annotations/`, `SI/`), seeds an empty `index.json` and `library.bib`, writes a sensible `.gitignore`, and symlinks `scripts/` into the vault so the Viewer can find the Python pipeline. The path is remembered in a gitignored `setup/.local.conf`, so later setup scripts default to it.

See [reference: vault layout](../reference/vault-layout.md) for what each folder is for.

## Step 4 — Point the Viewer at the vault

```bash
./setup/configure-viewer.sh
```

Writes `~/Library/Application Support/literature-vault/settings.json`. Relaunch the Viewer; it should open the empty library.

## Step 5 — File your first paper

Drag any PDF onto the Viewer window (or press ⌘N and pick one). If the PDF has a DOI, the Viewer extracts it, fetches metadata from CrossRef, mints a citekey, writes a Markdown note + a BibTeX entry, and moves the PDF into `PDFs/{citekey}.pdf`. If it doesn't, you'll get a manual-entry form prefilled from the PDF.

Verify the triplet was created:

```bash
ls ~/literature-vault/PaperNotes/  # one .md
ls ~/literature-vault/Bibfiles/    # one .bib
ls ~/literature-vault/PDFs/        # one .pdf
cat ~/literature-vault/library.bib # aggregated bib
```

You should also see the paper appear in the Viewer's library list on the left.

---

## What's next

Optional add-ons, each in its own how-to guide:

- [Install the embedding server](../how-to/install-the-embedding-server.md) — needed if you want semantic search (the `SEM` toggle in the search bar).
- [Install the Librarian agent](../how-to/install-the-librarian-agent.md) — needed if you want to file PDFs by Telegram.
- [Use the vault with Obsidian](../how-to/use-with-obsidian.md) — the vault layout is Obsidian-friendly.
- [Adopt an existing folder of papers](../how-to/adopt-existing-papers.md) — if you came here with notes from a previous workflow.

Day-to-day use:

- **Add a paper:** drop a PDF on the Viewer or hit ⌘N.
- **Organize:** switch to the "Organizing" view (top-left segmented switch), drag papers onto collections.
- **Search:** ⌘T focuses the library search. Toggle `SEM` for semantic search (requires the embedding server).
- **Read & note:** click a paper to open PDF + Markdown notes side by side. Edits auto-save on blur and on 2 s idle. ⌘⇧N inserts a timestamped section.

If something doesn't work, check [Troubleshoot](../how-to/troubleshoot.md).
