#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "sentence-transformers>=4.1",
# ]
# ///
"""Long-running embedding server for the literature vault.

Listens on 127.0.0.1:5817. Reads `scripts/embed_models.json` for the
registered models and their default. Loads each model lazily on first
request, holds them in a dict, and applies a per-model idle TTL so a
rarely-used model is unloaded while a hot model stays warm.

The whole process exits when nothing has been used for IDLE_EXIT_TTL;
launchd (KeepAlive=true) restarts it on demand.

Endpoints:
  GET  /health
  POST /embed   {texts: [str], prompt: "document"|"query", model?: str}
                → {vectors: [[float, ...], ...], model: str}
  POST /shutdown
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sentence_transformers import SentenceTransformer

VAULT_ROOT = Path(
    os.environ.get("LITERATURE_VAULT")
    or Path(__file__).absolute().parent.parent
)
CONFIG_PATH = Path(__file__).resolve().parent / "embed_models.json"

PORT = 5817
MODEL_IDLE_TTL_SEC = 30 * 60       # unload a model unused for 30 min
IDLE_EXIT_TTL_SEC = 30 * 60        # exit process if nothing used for 30 min


# Module-level state -----------------------------------------------------------

_config: dict = {}
_models: dict[str, SentenceTransformer] = {}
_model_last_used: dict[str, float] = {}
_load_locks: dict[str, threading.Lock] = {}
_state_lock = threading.Lock()
_last_activity = time.monotonic()
_started_at = time.monotonic()


def _now() -> float:
    return time.monotonic()


def _load_config() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text())
    if "default" not in cfg or "models" not in cfg:
        raise SystemExit(f"{CONFIG_PATH} must have 'default' and 'models'")
    if cfg["default"] not in cfg["models"]:
        raise SystemExit(
            f"default '{cfg['default']}' not present in models: {list(cfg['models'])}"
        )
    return cfg


def _resolve_model_id(requested: str | None) -> str:
    if requested is None:
        return _config["default"]
    if requested not in _config["models"]:
        raise ValueError(
            f"unknown model {requested!r}. registered: {list(_config['models'])}"
        )
    return requested


def _ensure_loaded(model_id: str) -> SentenceTransformer:
    if model_id in _models:
        _model_last_used[model_id] = _now()
        return _models[model_id]
    # Per-model lock so two concurrent requests don't double-load.
    with _state_lock:
        lock = _load_locks.setdefault(model_id, threading.Lock())
    with lock:
        if model_id in _models:
            _model_last_used[model_id] = _now()
            return _models[model_id]
        spec = _config["models"][model_id]
        path = str(VAULT_ROOT / spec["path"])
        kwargs: dict = {}
        if spec.get("trust_remote_code"):
            kwargs["trust_remote_code"] = True
        sys.stderr.write(f"loading {model_id} from {path}…\n")
        t0 = time.monotonic()
        model = SentenceTransformer(path, **kwargs)
        sys.stderr.write(
            f"loaded {model_id} in {time.monotonic() - t0:.1f}s\n"
        )
        _models[model_id] = model
        _model_last_used[model_id] = _now()
    return model


def _unload(model_id: str) -> None:
    with _state_lock:
        if model_id in _models:
            sys.stderr.write(f"unloading {model_id} (idle)\n")
            _models.pop(model_id, None)
            _model_last_used.pop(model_id, None)


def _embed(texts: list[str], prompt: str, model_id: str) -> list[list[float]]:
    if prompt not in ("document", "query"):
        raise ValueError(f"prompt must be 'document' or 'query', got {prompt!r}")
    spec = _config["models"][model_id]
    # Optional per-model prompt names. If the config sets {prompt}_prompt to a
    # string, use it; if missing or null, encode without a prompt (some models
    # don't define one).
    prompt_name = spec.get(f"{prompt}_prompt")
    model = _ensure_loaded(model_id)
    enc_kwargs: dict = {"convert_to_numpy": True}
    if prompt_name:
        enc_kwargs["prompt_name"] = prompt_name
    vecs = model.encode(texts, **enc_kwargs)
    return [v.astype("float32").tolist() for v in vecs]


# HTTP -------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        sys.stderr.write(
            f"[{time.strftime('%H:%M:%S')}] {self.address_string()} {format % args}\n"
        )

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _touch(self) -> None:
        global _last_activity
        _last_activity = _now()

    def do_GET(self) -> None:
        self._touch()
        if self.path == "/health":
            self._send_json(200, {
                "ok": True,
                "default": _config["default"],
                "registered": list(_config["models"]),
                "loaded": list(_models),
                "uptime_sec": round(_now() - _started_at, 1),
                "idle_sec": round(_now() - _last_activity, 1),
            })
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        self._touch()
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"bad JSON: {e}"})
            return

        if self.path == "/embed":
            try:
                texts = payload["texts"]
                if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
                    raise ValueError("texts must be a list of strings")
                prompt = payload.get("prompt", "document")
                model_id = _resolve_model_id(payload.get("model"))
                vectors = _embed(texts, prompt, model_id)
                self._send_json(200, {"vectors": vectors, "model": model_id})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path == "/shutdown":
            self._send_json(200, {"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.1), os._exit(0)),
                             daemon=True).start()
            return

        self._send_json(404, {"error": "not found"})


def _idle_watcher() -> None:
    """Unload idle models; exit the process when fully idle."""
    while True:
        time.sleep(30)
        now = _now()
        for mid, last in list(_model_last_used.items()):
            if now - last > MODEL_IDLE_TTL_SEC:
                _unload(mid)
        if now - _last_activity > IDLE_EXIT_TTL_SEC and not _models:
            sys.stderr.write(
                f"idle > {IDLE_EXIT_TTL_SEC}s and no models loaded — exiting\n"
            )
            os._exit(0)


def main() -> int:
    global _config
    _config = _load_config()
    threading.Thread(target=_idle_watcher, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    sys.stderr.write(
        f"embed-server ready on 127.0.0.1:{PORT} "
        f"(default: {_config['default']}, "
        f"registered: {list(_config['models'])})\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
