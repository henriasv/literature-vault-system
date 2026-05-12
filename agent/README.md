# LiteratureAssistant agent template

This directory contains the bits that install into a nanoclaw group when a
user runs `setup/install-agent.sh`. The script copies them into
`~/repos/nanoclaw/groups/<group-name>/` (default group name: `librarian`)
and fills in the placeholders with the user's actual host paths.

## Files

| File                       | What it is                                                       |
|----------------------------|------------------------------------------------------------------|
| `CLAUDE.local.md`          | The agent's system prompt. Generic LiteratureAssistant — no per- |
|                            | user content. Users can add a "Personal context" section at the  |
|                            | end after install.                                                |
| `container.json.template`  | Mount + group-name template. Placeholders rendered by            |
|                            | `setup/install-agent.sh`.                                        |
| `README.md`                | This file.                                                        |

## Container.json placeholders

| Placeholder      | Replacement                                                         |
|------------------|---------------------------------------------------------------------|
| `{{VAULT_PATH}}` | Host path of the user's literature vault (e.g. `~/literature-vault`) |
| `{{SYSTEM_PATH}}`| Host path of the literature-vault-system repo                       |
| `{{GROUP_NAME}}` | nanoclaw group name (default `librarian`)                           |
| `{{PDFS_MOUNT}}` | Either empty (no separate PDFs mount) OR a `,` + a third            |
|                  | `additionalMounts` entry pointing at the user's cloud-PDFs dir,     |
|                  | mounted at `containerPath: "vault/PDFs"` so the agent sees PDFs at  |
|                  | the conventional `/workspace/extra/vault/PDFs/{citekey}.pdf`        |
|                  | location even when storage is elsewhere.                            |

## What the agent sees inside the container

```
/workspace/extra/vault/        ← user's notes, BibTeX, index, library.bib
/workspace/extra/system/       ← read-only — scripts, docs (this repo)
/workspace/extra/vault/PDFs/   ← either local dir or cloud-storage mount
```

All scripts are invoked via `uv run /workspace/extra/system/scripts/<name>.py`.
`uv` itself plus the Python interpreter cache live under
`/workspace/extra/vault/.bin/` and `.uv-pythons/` / `.uv-cache/` so the
toolchain survives container rebuilds (it's per-user, not per-repo).
