# Install the embedding server

The embedding server is a small HTTP service running on `localhost:5817`. It stores note embeddings in `embeddings.db` inside the vault. The Viewer's `SEM` toggle and the Librarian's `find_similar.py` both call it.

You only need it for semantic search. Keyword search works without it.

## 1. Download at least one embedding model

Models live under `<vault>/.embedding_models/<name>/` (gitignored, re-downloadable).

| Model | Dim | Size | Speed |
|---|---|---|---|
| `google/embeddinggemma-300m` | 768 | ~1.2 GB | fast |
| `nvidia/llama-embed-nemotron-8b` | 4096 | ~14 GB | slow, stronger |

The default is `nemotron-8b`. If you want the lighter model instead, download it and flip the `default` key in `scripts/embed_models.json` after step 2.

```bash
cd ~/literature-vault

# The Nemotron repo is gated — log in first if you want it.
uv run --with huggingface_hub huggingface-cli login

# Download into .embedding_models/<dir-name-in-embed_models.json>/
uv run --with huggingface_hub python3 -c '
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="nvidia/llama-embed-nemotron-8b",
    local_dir=".embedding_models/llama-embed-nemotron-8b")'
```

For the lighter `gemma` model, swap the `repo_id` and `local_dir` accordingly.

## 2. Register the model

The registry is `scripts/embed_models.json`, reached via the vault's `scripts` symlink. It already ships with entries for `gemma` and `nemotron-8b`. If you used different local directory names, edit the `path:` fields. If you want a different default, change the `default:` key.

See [reference: embedding server](../reference/embedding-server.md) for the registry schema.

## 3. Index your notes

```bash
uv run scripts/embed_corpus.py
```

Incremental and content-hashed, so re-running is cheap. Re-run after filing new papers.

## 4. Run the server

For one-off testing:

```bash
uv run scripts/embed_server.py
curl http://127.0.0.1:5817/health
```

For unattended operation (recommended), install the launchd agent:

```bash
./setup/install-embed-server.sh --vault ~/literature-vault
```

This renders `setup/launchd/com.literature-vault.embed-server.plist.template` with your vault path, installs it to `~/Library/LaunchAgents/`, and loads it via `launchctl bootstrap`. The server starts automatically at login, restarts on crash, and exits after 30 minutes of full idle (launchd respawns on the next request).

Re-run the install script after moving the vault — it idempotently re-renders and reloads.

## Troubleshooting

- **`curl /health` fails.** Check `launchctl print gui/$(id -u)/com.literature-vault.embed-server`. The first request after idle is cold (~15 s).
- **Models don't load.** The server reads `scripts/embed_models.json`; verify the `path:` entries actually exist under `.embedding_models/`.
- **SEM toggle in Viewer doesn't return results.** The Viewer talks to the same `127.0.0.1:5817`. If `find_similar.py` from a shell works but the Viewer doesn't, restart the Viewer.

To pick up changes to `embed_server.py` or the model registry:

```bash
launchctl kickstart -k gui/$(id -u)/com.literature-vault.embed-server
```
