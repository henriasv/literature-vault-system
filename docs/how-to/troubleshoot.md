# Troubleshoot

## Viewer

**"Vault not configured" on launch.**
Run `./setup/configure-viewer.sh --vault <path>`, or use File → Open Vault inside the app.

**Auto-filing fails with "neither `uv` nor `python3` found on PATH".**
Install `uv` (`brew install uv`). The Viewer prefers `uv` because it handles PEP-723 inline dependencies. `python3` works too if `pypdf` is on the path.

**Drag-drop doesn't file the PDF.**
Make sure the vault's `scripts/` symlink points into this repo. From the vault directory: `ls -l scripts` should show a symlink to `~/repos/literature-vault-system/scripts`.

**Highlights vanish after restart.**
Annotations live in `<vault>/Annotations/{citekey}.json`. If the file is missing or empty, the Viewer started fresh. If it's present and the highlights still don't show, see [reference: viewer architecture](../reference/viewer-architecture.md) — the `<Annotations>` overlay may have failed to mount.

## Embedding server

**`SEM` toggle returns nothing.**
Check the server is up: `curl http://127.0.0.1:5817/health`. First call after 30 min idle is cold (~15 s). If still nothing, `launchctl print gui/$(id -u)/com.literature-vault.embed-server` and inspect stderr.

**Server doesn't restart on login.**
Re-run `./setup/install-embed-server.sh --vault <path>`. The install is idempotent and re-bootstraps the launchd entry.

**Pick up changes to the model registry.**
```bash
launchctl kickstart -k gui/$(id -u)/com.literature-vault.embed-server
```

## Librarian agent

**Agent says "scripts not found".**
Re-run `./setup/install-agent.sh`. This usually means the group's `container.json` is missing the `system` mount, or its `mount-allowlist.json` entry was lost.

**First reply takes ~30 seconds.**
That's `uv` bootstrapping `vault/.bin/` on first script invocation. Subsequent calls are instant.

**Agent edits don't take effect.**
Containers cache. Force a fresh one:
```bash
docker ps | grep nano
docker rm -f <id>
```

## Vault state

**Duplicate filings.**
`index.json` is content-addressed by sha256 / DOI / arXiv. If a duplicate slips through, check that `file_paper.py` actually completed (it's atomic — partial writes roll back). If `index.json` is missing entries for existing PDFs, re-run `file_paper.py --in-place` per affected PDF.

**`library.bib` out of sync.**
```bash
uv run scripts/build_library_bib.py
```
Idempotent.
