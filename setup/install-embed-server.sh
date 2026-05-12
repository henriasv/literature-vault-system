#!/usr/bin/env bash
# Install the embed-server launchd agent for unattended operation.
# Renders setup/launchd/com.literature-vault.embed-server.plist.template
# with the vault path baked in, installs it to ~/Library/LaunchAgents,
# and loads it via launchctl bootstrap.
#
#   ./setup/install-embed-server.sh --vault ~/literature-vault
#
# Re-run after moving the vault — re-renders + reloads.

set -euo pipefail

SYSTEM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$SYSTEM_DIR/setup/_lib.sh"
conf_load

TEMPLATE="$SYSTEM_DIR/setup/launchd/com.literature-vault.embed-server.plist.template"
LABEL="com.literature-vault.embed-server"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

VAULT_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --vault) VAULT_DIR="$2"; shift 2 ;;
    --help|-h) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unexpected: $1" >&2; exit 2 ;;
  esac
done

VAULT_DIR="${VAULT_DIR:-$CONF_VAULT}"
[[ -z "$VAULT_DIR" ]] && { echo "error: --vault is required (and no vault in setup/.local.conf yet)" >&2; exit 2; }
VAULT_DIR="${VAULT_DIR/#\~/$HOME}"
VAULT_DIR=$(cd "$VAULT_DIR" 2>/dev/null && pwd) || {
  echo "error: $VAULT_DIR does not exist" >&2; exit 1;
}
[[ -f "$VAULT_DIR/scripts/embed_server.py" ]] || {
  echo "error: $VAULT_DIR/scripts/embed_server.py not found — run setup/init-vault.sh first" >&2
  exit 1
}

UV_PATH=$(command -v uv || true)
[[ -z "$UV_PATH" ]] && { echo "error: 'uv' not on PATH — install via 'brew install uv'" >&2; exit 1; }

# Unload first if already installed (idempotent re-run).
if launchctl list 2>/dev/null | awk '{print $3}' | grep -qx "$LABEL"; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
fi

sed -e "s|{{VAULT_PATH}}|$VAULT_DIR|g" -e "s|{{UV_PATH}}|$UV_PATH|g" "$TEMPLATE" > "$DEST"
launchctl bootstrap "gui/$(id -u)" "$DEST"

conf_set vault "$VAULT_DIR"

echo "Installed: $DEST"
echo "Vault:     $VAULT_DIR"
echo "uv:        $UV_PATH"
echo ""
echo "Verify with:  curl http://127.0.0.1:5817/health"
echo "Tail logs at: $VAULT_DIR/embed-server.log"
