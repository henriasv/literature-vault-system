# Install the Librarian agent

The Librarian is an optional Telegram bot that handles the asynchronous parts: filing PDFs you send by phone, suggesting tags, appending notes, answering "what should I cite for X?" questions. It runs as a [nanoclaw](https://github.com/henriasv/nanoclaw) group, not as part of the Viewer.

You only need this if you want phone-based intake. The Viewer works fine without it.

## Prerequisites

- The Viewer is already installed and pointed at a vault (see the [tutorial](../tutorial/getting-started.md)).
- [nanoclaw](https://github.com/henriasv/nanoclaw) is installed and configured. nanoclaw itself needs Docker and an Anthropic API key — follow its README.
- A Telegram bot. See [connect a Telegram bot](connect-telegram.md).

## Install

From the literature-vault-system repo:

```bash
./setup/install-agent.sh \
  --vault    ~/literature-vault \
  --nanoclaw ~/repos/nanoclaw \
  --group    librarian \
  --pdfs     "/path/to/cloud/PDFs"   # optional, only if your PDFs live elsewhere
```

This creates `~/repos/nanoclaw/groups/librarian/` with:

- `CLAUDE.local.md` — the agent's system prompt (generic; you can add a `## Personal context` section at the bottom after install).
- `container.json` — rendered from `agent/container.json.template` with your host paths. Mounts the vault at `/workspace/extra/vault`, the system repo at `/workspace/extra/system` (read-only), and the optional cloud PDFs at `/workspace/extra/vault/PDFs`.

It also patches `~/.config/nanoclaw/mount-allowlist.json` to permit those host paths.

Start the group through nanoclaw as you would any other.

## First run

On the first script invocation inside the container, the agent bootstraps `uv` and a Python interpreter into the vault's `.bin/` and `.uv-pythons/`. Takes ~30 seconds and can look like a hang — it isn't. Subsequent runs are instant.

## What the agent can do

See [reference: Librarian agent](../reference/agent.md) for the full contract. The short version:

- **Phone intake** — send a PDF or an arXiv/DOI link; it files the paper and replies with the citekey, BibTeX, TL;DR, and suggested tags.
- **Reply-to-add-notes** — reply to one of the agent's messages and the text is appended to the note's `## Notes` (or `## Why` if it's answering "why this paper?").
- **Library queries** — "What do I have on rate-and-state friction?" runs an embedding search and returns ranked citekeys.
- **Auto-commit** — if the vault is a git repo, the agent commits after each edit (it never pushes).

## Troubleshooting

- **"Scripts not found"** — re-run `setup/install-agent.sh`. This usually means the group's `container.json` is missing the `system` mount, or its `mount-allowlist.json` entry was lost.
- **Semantic search fails** — the agent reaches the embedding server on the host via `host.docker.internal:5817`. Make sure [the embedding server](install-the-embedding-server.md) is running.
- **Slow first response** — see "First run" above. After that, watch [Troubleshoot](troubleshoot.md).
