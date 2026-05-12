# Getting started

A 10-minute walkthrough from clone to first paper filed.

## What you'll end up with

```
~/repos/literature-vault-system/                  the repo
~/literature-vault/                               your data (created in step 3)
├── PaperNotes/  PDFs/  Bibfiles/  Inbox/  Collections/
├── index.json   library.bib
└── scripts → ~/repos/literature-vault-system/scripts    (symlink)

/Applications/Literature Vault.app                the built viewer

~/Library/Application Support/com.literature-vault-viewer/settings.json
                                                  points the viewer at the vault

(if you install the agent — nanoclaw must already be running)
~/repos/nanoclaw/groups/librarian/                a new agent group
```

## Prerequisites

1. **macOS** with Xcode Command Line Tools (`xcode-select --install`).
2. **Rust toolchain** (`rustup`, stable channel) — needed for the viewer build.
3. **Node.js ≥ 18** with `npm` — needed for the viewer build.
4. **uv** — Python toolchain manager, used to run the scripts.
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
5. **(Optional) nanoclaw** — only needed if you want the LiteratureAssistant
   agent. Install separately from
   [github.com/.../nanoclaw](https://github.com).

## Step 1 — Clone the repo

```bash
git clone https://github.com/<you>/literature-vault-system ~/repos/literature-vault-system
cd ~/repos/literature-vault-system
```

## Step 2 — Build & install the viewer

```bash
./setup/install-viewer.sh
```

This runs `npm ci && npm run tauri build` and copies the resulting
`.app` into `/Applications/`. Takes ~3 minutes on a recent Mac, mostly
Rust compile time. Re-run after `git pull` to update.

Launch it once from Spotlight to confirm the `.app` works — it'll show
a "no vault configured" screen the first time. We fix that in step 4.

## Step 3 — Scaffold a vault

```bash
./setup/init-vault.sh                     # default: ~/literature-vault
# or
./setup/init-vault.sh ~/my-other-vault
```

Creates the canonical directory layout (`PaperNotes/`, `PDFs/`, etc.),
seeds an empty `index.json` and `library.bib`, and symlinks `scripts`
into the vault so the host-side viewer can find the Python pipeline.

If you keep your PDFs on cloud storage (Google Drive, Dropbox,
iCloud), pass `--pdfs`:

```bash
./setup/init-vault.sh ~/literature-vault --pdfs ~/Library/CloudStorage/...
```

The vault's `PDFs/` becomes a symlink to that location instead of a
plain directory. The agent install in step 5 will pick this up too if
you tell it the same `--pdfs` path.

## Step 4 — Point the viewer at the vault

```bash
./setup/configure-viewer.sh --vault ~/literature-vault
```

Writes `~/Library/Application Support/com.literature-vault-viewer/settings.json`
— equivalent to launching the app and using its File > Open Vault
picker. Relaunch the viewer; it should now load the empty library.

## Step 5 — (Optional) install the LiteratureAssistant agent

Only if you want the asynchronous parts (auto-filing PDFs you send by
Telegram/Slack, tag suggestions, semantic search via chat). Requires a
working nanoclaw install.

```bash
./setup/install-agent.sh \
  --vault     ~/literature-vault \
  --nanoclaw  ~/repos/nanoclaw \
  --group     librarian \
  --pdfs      "/path/to/cloud/PDFs"        # optional, matches step 3
```

This creates `~/repos/nanoclaw/groups/librarian/` with:

- `CLAUDE.local.md` — the LiteratureAssistant system prompt (generic;
  add your own "Personal context" section at the bottom if you want
  the agent to know about your group, projects, etc.).
- `container.json` — rendered from `agent/container.json.template` with
  your actual host paths substituted in. Mounts the vault at
  `/workspace/extra/vault`, the system repo at `/workspace/extra/system`
  (read-only), and optional cloud PDFs at `/workspace/extra/vault/PDFs`.

Plus it patches `~/.config/nanoclaw/mount-allowlist.json` to permit
those host paths.

Start the agent through nanoclaw as usual.

## Day-to-day

- **Add a paper**: drop a PDF onto the viewer window OR hit ⌘N. If the
  PDF has a DOI, it's filed automatically (CrossRef metadata → BibTeX →
  triplet of `PaperNotes/{citekey}.md` + `Bibfiles/{citekey}.bib` +
  `PDFs/{citekey}.pdf`). If no DOI, you get the manual-entry path with
  fields pre-filled from the PDF.
- **Organize**: switch to the "Organizing" view (segmented switch top-
  left), drag papers onto collections in the tree on the left.
- **Search**: ⌘T focuses the library search. Toggle SEM in the search
  field for semantic search (needs the embedding server running — see
  the next section).
- **Read & note**: click a paper to open PDF + Markdown notes side by
  side. Edits auto-save on blur and on 2s idle.

## The embedding server (semantic search)

Optional but recommended. A small FastAPI server runs locally on port
5817 and stores embeddings in `embeddings.db` inside the vault. The
viewer's SEM toggle calls it; the agent calls it via
`find_similar.py`.

```bash
# Run once interactively to verify it works:
uv run ~/repos/literature-vault-system/scripts/embed_server.py

# Then index the vault:
uv run ~/repos/literature-vault-system/scripts/embed_corpus.py
```

For unattended operation, run the server under launchd. A starter
plist will land in `setup/launchd/` (TODO).

## Updating

```bash
cd ~/repos/literature-vault-system
git pull
./setup/install-viewer.sh        # rebuilds the .app if viewer changed
```

The scripts update automatically (the vault's `scripts/` symlink points
into the repo; the agent's mount points into the same repo). No manual
sync needed.

## Troubleshooting

**"vault not configured" on launch.** Run
`./setup/configure-viewer.sh --vault <path>` — or use File > Open Vault
inside the app.

**Auto-filing fails with "neither `uv` nor `python3` found on PATH".**
Install `uv` per the prerequisites. The viewer prefers `uv` because it
handles PEP-723 inline dependencies; `python3` works too if `pypdf` is
in the env.

**Agent says scripts not found.** Re-run `setup/install-agent.sh` —
this usually means the nanoclaw group's `container.json` is missing
the `system` mount, or its `mount-allowlist.json` entry was lost.
