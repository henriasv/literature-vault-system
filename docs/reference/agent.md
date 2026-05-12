# Librarian agent

The Librarian is a nanoclaw group. Its behavior is fully specified by `agent/CLAUDE.local.md` in this repo — that file is the contract.

## Template files

| File | Role |
|---|---|
| `agent/CLAUDE.local.md` | System prompt. Generic — no per-user content. Add a `## Personal context` section at the bottom after install. |
| `agent/container.json.template` | Mount + group-name template. Rendered by `setup/install-agent.sh`. |

`setup/install-agent.sh` copies these into `~/repos/nanoclaw/groups/<group-name>/` (default `librarian`) and fills the placeholders.

## Container.json placeholders

| Placeholder | Replacement |
|---|---|
| `{{VAULT_PATH}}` | Host path of the user's literature vault (e.g. `~/literature-vault`). |
| `{{SYSTEM_PATH}}` | Host path of the literature-vault-system repo. |
| `{{GROUP_NAME}}` | nanoclaw group name (default `librarian`). |
| `{{PDFS_MOUNT}}` | Either empty (no separate PDFs mount) or a `,` + a third `additionalMounts` entry pointing at the user's cloud-PDFs dir, mounted at `containerPath: "vault/PDFs"`. |

## What the agent sees inside the container

```
/workspace/extra/vault/      ← user's notes, BibTeX, index, library.bib (rw)
/workspace/extra/system/     ← scripts, docs from this repo (ro)
/workspace/extra/vault/PDFs/ ← either local or cloud-storage mount
```

## Triggers (summary)

The full prose is in `agent/CLAUDE.local.md`. Briefly:

| Trigger | Flow |
|---|---|
| **PDF arrives** | `Inbox/` → `extract_ids.py` → (CrossRef search if no DOI) → `file_paper.py` → reply with citekey, BibTeX, TL;DR, tag suggestions. |
| **Reply to a paper message** | Disambiguate paper → `append_note.py` for body → rewrite `## Cleaned Notes`. |
| **Reply to "why this paper?"** | Edit `## Why` directly. |
| **Topic / citation question** | `find_similar.py "<query>" --top 8` → read top notes → ranked reply. |

The agent commits to the vault's git repo (if one exists) after every edit; it never pushes.

## Hard rules

These come straight from `CLAUDE.local.md` and should not drift:

- Never modify a note's body **except** to insert into `## Why`, rewrite `## Cleaned Notes`, or append to `## Notes` (the last via `append_note.py`).
- Never delete files. Move to `/workspace/extra/vault/.trash/` and confirm with the user before doing so.
- Surface script stderr verbatim rather than guessing a workaround.
- Don't reimplement what scripts do (sha256, dedup, citekey, bib formatting, library aggregation). Always call the script.

## Python toolchain inside the container

Containers have no system Python by default. The agent uses `uv` from the vault:

- Binary: `/workspace/extra/vault/.bin/uv`
- Python interpreters: `/workspace/extra/vault/.uv-pythons/`
- Package cache: `/workspace/extra/vault/.uv-cache/`

This makes the toolchain persist across container rebuilds (it's per-user, not per-repo). On first run the agent bootstraps `uv` via `curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/workspace/extra/vault/.bin sh`. Takes ~30 s once.

Never `pip install`; never call `python3` directly. Always:

```bash
uv run /workspace/extra/system/scripts/<name>.py [args]
```

PEP-723 inline metadata in each script resolves and caches deps automatically.

## Embedding server reachability

The embed server runs on the **host** at `127.0.0.1:5817`. The container reaches it via `host.docker.internal:5817`. The thin client (`scripts/_embed_client.py`) auto-detects whether it's running on host or in container and routes accordingly — no manual configuration.

If the server is unreachable, the agent surfaces stderr verbatim rather than silently falling back to keyword grep.

## Where to change agent behavior

Edit `~/repos/nanoclaw/groups/<group-name>/CLAUDE.local.md` after install (or `agent/CLAUDE.local.md` in this repo, then re-run `setup/install-agent.sh`). The next container spawn picks up the changes; force a fresh container if needed:

```bash
docker ps | grep nano
docker rm -f <id>
```

The sibling `CLAUDE.md` in the group directory is auto-composed by nanoclaw from its module fragments — **never edit it**.
