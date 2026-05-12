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

~/Library/Application Support/literature-vault/settings.json
                                                  points the viewer at the vault

(if you install the agent — nanoclaw must already be running)
~/repos/nanoclaw/groups/librarian/                a new agent group
```

## Prerequisites

Target platform is **Apple Silicon Mac** (M1 or newer) on a recent macOS.
Intel Macs aren't supported — Homebrew lives at `/usr/local/` there and a
few paths in the install scripts (Homebrew's `uv`) assume `/opt/homebrew/`.

1. **Xcode Command Line Tools**:
   ```bash
   xcode-select --install
   ```
2. **Homebrew** ([brew.sh](https://brew.sh)) at the standard
   `/opt/homebrew/` prefix. Most everything below is installed through it.
3. **Rust toolchain** (for the viewer build):
   ```bash
   brew install rustup-init && rustup-init -y
   ```
4. **Node.js ≥ 18** with `npm` (for the viewer build):
   ```bash
   brew install node
   ```
5. **uv** — Python toolchain manager used by every script in `scripts/`.
   The launchd plist for the embed-server resolves uv via your PATH at
   install time, so the canonical Homebrew location (`/opt/homebrew/bin/uv`)
   is what gets baked in:
   ```bash
   brew install uv
   ```
6. **(Optional) nanoclaw** — only needed for the LiteratureAssistant
   agent. Install separately from
   [github.com/.../nanoclaw](https://github.com).

### Optional: a CrossRef contact email

The filing scripts (`doi2bib.py`, `crossref_search.py`) hit CrossRef,
DataCite, and OpenAlex. CrossRef's "polite pool" gives higher rate
limits to clients that advertise a real contact email. To opt in,
export your email before running the scripts (or stash it in your
shell rc):

```bash
export CROSSREF_MAILTO="you@example.com"
```

Without this, the scripts fall through to CrossRef's public pool —
they still work, just with stricter throttling. The variable is read
fresh on each script invocation; no rebuild needed.

### A note on the per-machine setup state

The setup scripts (`init-vault.sh`, `configure-viewer.sh`,
`install-agent.sh`, `install-embed-server.sh`) all share a tiny
gitignored file at `setup/.local.conf` that remembers your `vault`,
`nanoclaw`, and `pdfs` paths. The first script you run with `--vault X`
writes that path; the rest pick it up automatically. CLI flags always
override, so you can ignore the file's existence if you prefer to be
explicit.

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

### 3a — Fresh vault

```bash
./setup/init-vault.sh                     # default: ~/literature-vault
# or
./setup/init-vault.sh ~/my-other-vault
```

Creates the canonical directory layout (`PaperNotes/`, `PDFs/`,
`Bibfiles/`, `Inbox/`, `Collections/`, `Projects/`, `Annotations/`,
`SI/`), seeds an empty `index.json` and `library.bib`, writes a
sensible `.gitignore`, and symlinks `scripts` into the vault so the
host-side viewer can find the Python pipeline.

If you keep your PDFs on cloud storage (Google Drive, Dropbox,
iCloud), pass `--pdfs`:

```bash
./setup/init-vault.sh ~/literature-vault --pdfs ~/Library/CloudStorage/...
```

The vault's `PDFs/` becomes a symlink to that location instead of a
plain directory. The agent install in step 5 will pick this up too if
you tell it the same `--pdfs` path.

### 3b — Adopting an existing collection of papers and notes

If you already have a folder of papers and notes (e.g. from an earlier
Obsidian-based workflow), use `--adopt` to fill in scaffolding around
what you've got instead of starting fresh.

**Required starting layout.** The script expects your directory to
already look roughly like this:

```
<your-dir>/
├── PaperNotes/{citekey}.md     # one note per paper
├── PDFs/{citekey}.pdf          # matching PDF per note
└── Bibfiles/{citekey}.bib      # optional but recommended
```

The filename **must** be the citekey — i.e. each note, PDF, and bibfile
for the same paper share the same base name. See
[`docs/CITATION_KEYS.md`](docs/CITATION_KEYS.md) for the citekey format
(`{firstauthor}{year}-{journal-abbrev}-{doi-suffix}`).

Notes also need YAML frontmatter with at least: `citekey`, `title`,
`authors`, `year`, `journal`, `doi`, `arxiv_id`, `added`, `sha256_pdf`,
and ideally `abstract`. See [`docs/DESIGN.md`](docs/DESIGN.md) §
*Conventions*. If your notes are missing this, you'll need to refile
each paper through `scripts/file_paper.py` or `scripts/manual_file.py`
before the viewer can use them.

**What to do before running the script.**

1. Move (or create a directory and move) your `PaperNotes/`,
   `PDFs/`, and (optional) `Bibfiles/` into a single parent dir, e.g.
   `~/literature-vault`.
2. Verify that for every `PaperNotes/{citekey}.md` you also have
   `PDFs/{citekey}.pdf`:
   ```bash
   cd ~/literature-vault
   comm -23 \
     <(ls PaperNotes | sed 's/\.md$//' | sort) \
     <(ls PDFs       | sed 's/\.pdf$//' | sort)
   # any output = notes with no matching PDF
   ```
3. If you have a previous `scripts/` directory in there (real files,
   from an earlier system), the adopt step will move it to
   `scripts.old/` and replace it with a symlink to this repo. Verify
   you haven't customised anything in there first.

**Then run:**

```bash
./setup/init-vault.sh ~/literature-vault --adopt
```

The script will:
- Create any missing dirs (`Inbox/`, `Collections/`, `Projects/`,
  `Annotations/`, `SI/`, and `Bibfiles/`/`PDFs/` if you didn't have
  them).
- Replace `scripts/` with a symlink to `literature-vault-system/scripts`
  (backing up an existing directory to `scripts.old/`).
- Skip `index.json`, `library.bib`, and `.gitignore` if they already
  exist (it never clobbers your existing files in adopt mode).

**After:**

```bash
# rebuild library.bib from your Bibfiles/
uv run scripts/build_library_bib.py

# if your existing notes don't already have one, populate the dedup index
# by running file_paper.py --in-place per PDF (TODO: a bulk-rebuild helper)
```

You should now be able to open the vault in the viewer.

## Step 4 — Point the viewer at the vault

```bash
./setup/configure-viewer.sh --vault ~/literature-vault
```

Writes `~/Library/Application Support/literature-vault/settings.json`
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

**Heads-up on first run**: the agent bootstraps `uv` and a Python
interpreter into the vault's `.bin/` and `.uv-pythons/` on the first
script invocation. Takes ~30 s and can look like a hang — it isn't.
Subsequent runs are instant.

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

Optional but recommended. A small HTTP server runs locally on port
5817 and stores embeddings in `embeddings.db` inside the vault. The
viewer's SEM toggle calls it; the agent calls it via
`scripts/find_similar.py`.

### 1. Download at least one embedding model

Models live under `<vault>/.embedding_models/<name>/` (gitignored;
re-downloadable). Two recommended choices:

| Model                              | Dim  | Size    | Speed         |
|------------------------------------|------|---------|---------------|
| `google/embeddinggemma-300m`       | 768  | ~1.2 GB | fast          |
| `nvidia/llama-embed-nemotron-8b`   | 4096 | ~14 GB  | slow, stronger |

Download via `huggingface_hub`:

```bash
cd ~/literature-vault
uv run --with huggingface_hub python3 -c '
from huggingface_hub import snapshot_download
snapshot_download(repo_id="google/embeddinggemma-300m",
                  local_dir=".embedding_models/embeddinggemma-300m")'
```

For gated repos, run `huggingface-cli login` first.

### 2. Register the model

The registry is `scripts/embed_models.json` (lives in this repo, reached
via the vault's `scripts` symlink). It already ships with `gemma` and
`nemotron-8b` entries — if you used different local dir names, edit the
`path:` fields. If you want a different default, change the `default:`
key.

### 3. Index your existing notes

```bash
uv run scripts/embed_corpus.py
```

Incremental + content-hashed, so re-running is cheap.

### 4. Run the server

For one-off testing, run it interactively:

```bash
uv run scripts/embed_server.py
curl http://127.0.0.1:5817/health   # should return JSON
```

For unattended operation (recommended), install the launchd agent:

```bash
./setup/install-embed-server.sh --vault ~/literature-vault
```

This renders `setup/launchd/com.literature-vault.embed-server.plist.template`
with your vault path, installs it to `~/Library/LaunchAgents/`, and
loads it via `launchctl bootstrap`. The server then starts automatically
at login, restarts on crash, and self-exits after 30 min of full idle
(launchd respawns on the next request).

Re-run the install script after moving the vault — it idempotently
re-renders and reloads.

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
