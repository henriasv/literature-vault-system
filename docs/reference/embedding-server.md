# Embedding server

A small HTTP server on `127.0.0.1:5817` that loads sentence-transformer models on demand and answers embedding requests. The Viewer's `SEM` toggle and the Librarian's `find_similar.py` both call it.

## Architecture

- **Runs on the host.** Always — even when the Librarian is in a container, it reaches the server via `host.docker.internal:5817`. The host has fast access to the model cache (and a GPU if available).
- **Multi-model.** Reads the model registry from `scripts/embed_models.json`. Loads each model on first request and keeps it warm.
- **Lazy-loaded.** A cold model takes ~15 s on first call after idle.
- **Per-model idle TTL.** Cold models unload while hot ones stay warm.
- **Full-idle exit.** Process exits after 30 minutes with no requests. launchd respawns on the next call.
- **launchd-supervised.** Started at login via `~/Library/LaunchAgents/com.literature-vault.embed-server.plist` (installed by `setup/install-embed-server.sh`).

## Model registry

`scripts/embed_models.json`:

```json
{
  "default": "nemotron-8b",
  "models": {
    "nemotron-8b": {
      "path": ".embedding_models/llama-embed-nemotron-8b",
      "dim": 4096,
      "doc_prompt": "document",
      "query_prompt": "query",
      "trust_remote_code": true
    },
    "gemma": {
      "path": ".embedding_models/embeddinggemma-300m",
      "dim": 768
    }
  }
}
```

- `default` — model used when no `--model` flag is passed.
- `path` — relative to the vault root.
- `dim` — embedding dimension. Read from the model's `config.json` `hidden_size` (or model card).
- `doc_prompt` / `query_prompt` — optional prompts the model expects.
- `trust_remote_code` — only set true if the HuggingFace repo ships custom modeling code (the Nemotron model does).

## HTTP API

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | — | `{"status": "ok", "loaded_models": [...]}` |
| POST | `/embed` | `{"texts": [...], "model": "...", "kind": "document\|query"}` | `{"embeddings": [[...], ...]}` |

The `kind` parameter controls which prompt (if any) the model prepends.

The thin client (`scripts/_embed_client.py`) abstracts both endpoints and handles the host-vs-container loopback routing.

## Operations

```bash
# Pick up changes to embed_server.py or embed_models.json
launchctl kickstart -k gui/$(id -u)/com.literature-vault.embed-server

# Tail the log
tail -f embed-server.log

# Health check
curl http://127.0.0.1:5817/health
```

## Adding a new model

1. Download weights to `.embedding_models/<short-id>/` inside the vault.
2. Append a registry entry to `scripts/embed_models.json` with `path`, `dim`, and any prompt / trust-remote-code flags the model needs.
3. `launchctl kickstart -k gui/$(id -u)/com.literature-vault.embed-server` to pick up the new config.
4. `uv run scripts/embed_corpus.py --model <short-id>` to populate `vec_papers__<safe_id>`.
5. Optional: flip `default` in `embed_models.json` if this should be the new default.

## Known constraint

`embeddings.db` is SQLite (with the `sqlite-vec` extension). Keep it on a local volume, not on cloud-synced storage — synced SQLite databases corrupt.
