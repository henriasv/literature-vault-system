"""Tiny client for the local embed-server (scripts/embed_server.py).

Auto-detects whether we're running on the host (talk to 127.0.0.1) or
inside the nanoclaw container (talk to host.docker.internal). On host,
fork-starts the server if it isn't running yet.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT = 5817
TIMEOUT_FIRST_CALL = 60   # cold load ~15s, give margin
TIMEOUT_WARM_CALL = 30


def _in_container() -> bool:
    return Path("/workspace/extra/vault").exists()


def _base_url() -> str:
    host = "host.docker.internal" if _in_container() else "127.0.0.1"
    return f"http://{host}:{PORT}"


def _health(timeout: float = 1.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"{_base_url()}/health", timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None


def _start_host_server() -> None:
    """Fork-start the server. Host only — container can't reach the host shell."""
    script = Path(__file__).resolve().parent / "embed_server.py"
    subprocess.Popen(
        ["uv", "run", str(script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def _ensure_server_up() -> None:
    if _health() is not None:
        return
    if _in_container():
        raise SystemExit(
            f"embed-server not responding at {_base_url()}.\n"
            "Run on the host: `uv run scripts/embed_server.py`, or install "
            "the launchd agent (setup/install-embed-server.sh --vault <path>)."
        )
    _start_host_server()
    # Wait up to TIMEOUT_FIRST_CALL for the server to come online.
    deadline = time.monotonic() + TIMEOUT_FIRST_CALL
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if _health() is not None:
            return
    raise SystemExit("embed-server failed to start within 60s")


def health() -> dict | None:
    return _health()


def embed(texts: list[str], prompt: str = "document",
          model: str | None = None) -> tuple[list[list[float]], str]:
    """Embed a batch of texts.

    prompt: 'document' or 'query'.
    model:  registered model id, or None for the server's default.
    Returns (vectors, model_id_used).
    """
    _ensure_server_up()
    payload: dict = {"texts": texts, "prompt": prompt}
    if model is not None:
        payload["model"] = model
    req = urllib.request.Request(
        f"{_base_url()}/embed",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_FIRST_CALL) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        # Surface the server's JSON error body instead of a bare HTTP 500.
        try:
            err = json.loads(e.read()).get("error", str(e))
        except Exception:
            err = str(e)
        raise SystemExit(f"embed-server: {err}") from None
    return body["vectors"], body["model"]
