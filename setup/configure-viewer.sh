#!/usr/bin/env bash
# Point the installed viewer at a vault directory without launching the app.
# Writes ~/Library/Application Support/literature-vault/settings.json
# with {"activeVault": "<path>"} — the same file the viewer's
# File > Open Vault menu writes (see viewer/src-tauri/src/settings.rs).
#
#   ./setup/configure-viewer.sh --vault ~/literature-vault
#
# Equivalent to launching the app and using its first-run picker.

set -euo pipefail

SYSTEM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$SYSTEM_DIR/setup/_lib.sh"
conf_load

VAULT_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --vault) VAULT_DIR="$2"; shift 2 ;;
    --help|-h)
      sed -n '2,9p' "$0"
      exit 0
      ;;
    *) echo "unexpected: $1" >&2; exit 2 ;;
  esac
done

VAULT_DIR="${VAULT_DIR:-$CONF_VAULT}"
if [[ -z "$VAULT_DIR" ]]; then
  echo "error: --vault is required (no vault in setup/.local.conf yet)" >&2
  exit 2
fi

VAULT_DIR="${VAULT_DIR/#\~/$HOME}"
VAULT_DIR=$(cd "$VAULT_DIR" 2>/dev/null && pwd || true)
if [[ -z "$VAULT_DIR" ]]; then
  echo "error: vault directory does not exist or is not accessible" >&2
  exit 1
fi
if [[ ! -d "$VAULT_DIR/PaperNotes" ]]; then
  echo "error: $VAULT_DIR does not look like a vault — no PaperNotes/ subfolder" >&2
  echo "       run setup/init-vault.sh to scaffold one first." >&2
  exit 1
fi

# The viewer (settings.rs) loads from dirs::config_dir()/literature-vault/
# — NOT Tauri's per-identifier app_data_dir. Keep this path in sync with
# DIR_NAME in viewer/src-tauri/src/settings.rs.
SETTINGS_DIR="$HOME/Library/Application Support/literature-vault"
mkdir -p "$SETTINGS_DIR"
cat > "$SETTINGS_DIR/settings.json" <<JSON
{
  "activeVault": "$VAULT_DIR"
}
JSON

conf_set vault "$VAULT_DIR"

echo "Configured viewer to use vault: $VAULT_DIR"
echo "Settings file: $SETTINGS_DIR/settings.json"
echo ""
echo "Launch the viewer to verify."
