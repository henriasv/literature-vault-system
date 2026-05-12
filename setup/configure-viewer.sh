#!/usr/bin/env bash
# Point the installed viewer at a vault directory without launching the app.
# Writes ~/Library/Application Support/com.literature-vault-viewer/active-vault.json
# (the same file the viewer's File > Open Vault menu writes).
#
#   ./setup/configure-viewer.sh --vault ~/literature-vault
#
# Equivalent to launching the app and using its first-run picker.

set -euo pipefail

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

if [[ -z "$VAULT_DIR" ]]; then
  echo "error: --vault is required" >&2
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

# The viewer reads its active vault from Tauri's app-data dir on macOS.
# The bundle identifier from tauri.conf.json determines the directory name.
SETTINGS_DIR="$HOME/Library/Application Support/com.literature-vault-viewer"
mkdir -p "$SETTINGS_DIR"
cat > "$SETTINGS_DIR/settings.json" <<JSON
{
  "active_vault": "$VAULT_DIR"
}
JSON

echo "Configured viewer to use vault: $VAULT_DIR"
echo "Settings file: $SETTINGS_DIR/settings.json"
echo ""
echo "Launch the viewer to verify."
