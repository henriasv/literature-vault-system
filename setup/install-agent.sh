#!/usr/bin/env bash
# Install a LiteratureAssistant agent into an existing nanoclaw setup.
# Creates a new group under nanoclaw/groups/<group>/ from the
# agent/ template and patches nanoclaw's mount allowlist.
#
#   ./setup/install-agent.sh \
#     --vault     ~/literature-vault \
#     --nanoclaw  ~/repos/nanoclaw \
#     [--system   <path>]          \  # defaults to this repo (the parent of setup/)
#     [--group    librarian]       \
#     [--pdfs     /Volumes/CloudPDFs]
#
# The agent will see the vault at /workspace/extra/vault, the system
# repo (read-only) at /workspace/extra/system, and the optional PDFs
# mount layered at /workspace/extra/vault/PDFs (so paths like
# /workspace/extra/vault/PDFs/{citekey}.pdf resolve regardless of
# where the PDFs physically live).

set -euo pipefail

SYSTEM_DEFAULT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$SYSTEM_DEFAULT/setup/_lib.sh"
conf_load

VAULT_DIR=""
NANOCLAW_DIR=""
SYSTEM_DIR="$SYSTEM_DEFAULT"
GROUP_NAME="librarian"
PDFS_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --vault)    VAULT_DIR="$2"; shift 2 ;;
    --nanoclaw) NANOCLAW_DIR="$2"; shift 2 ;;
    --system)   SYSTEM_DIR="$2"; shift 2 ;;
    --group)    GROUP_NAME="$2"; shift 2 ;;
    --pdfs)     PDFS_DIR="$2"; shift 2 ;;
    --help|-h)
      sed -n '2,18p' "$0"
      exit 0
      ;;
    *) echo "unexpected: $1" >&2; exit 2 ;;
  esac
done

VAULT_DIR="${VAULT_DIR:-$CONF_VAULT}"
NANOCLAW_DIR="${NANOCLAW_DIR:-$CONF_NANOCLAW}"
PDFS_DIR="${PDFS_DIR:-$CONF_PDFS}"

[[ -z "$VAULT_DIR"    ]] && { echo "error: --vault is required (and no vault in setup/.local.conf yet)" >&2; exit 2; }
[[ -z "$NANOCLAW_DIR" ]] && { echo "error: --nanoclaw is required (and no nanoclaw in setup/.local.conf yet)" >&2; exit 2; }

# Normalise paths (expand ~, resolve).
expand() {
  local p="${1/#\~/$HOME}"
  echo "$p"
}
VAULT_DIR=$(expand "$VAULT_DIR")
NANOCLAW_DIR=$(expand "$NANOCLAW_DIR")
SYSTEM_DIR=$(expand "$SYSTEM_DIR")
PDFS_DIR=${PDFS_DIR:+$(expand "$PDFS_DIR")}

[[ -d "$VAULT_DIR/PaperNotes" ]] || {
  echo "error: $VAULT_DIR doesn't look like a vault (no PaperNotes/)" >&2
  echo "       run setup/init-vault.sh first." >&2
  exit 1
}
[[ -d "$NANOCLAW_DIR/groups"  ]] || {
  echo "error: $NANOCLAW_DIR doesn't look like a nanoclaw install (no groups/)" >&2
  exit 1
}
[[ -d "$SYSTEM_DIR/scripts"   ]] || {
  echo "error: $SYSTEM_DIR doesn't have scripts/ — wrong --system path?" >&2
  exit 1
}
[[ -n "$PDFS_DIR" && ! -d "$PDFS_DIR" ]] && {
  echo "error: $PDFS_DIR (--pdfs) doesn't exist" >&2; exit 1;
}

GROUP_DIR="$NANOCLAW_DIR/groups/$GROUP_NAME"
if [[ -e "$GROUP_DIR" ]]; then
  echo "error: $GROUP_DIR already exists — pick a different --group" >&2
  exit 1
fi

echo "Installing LiteratureAssistant agent:"
echo "  group:    $GROUP_NAME"
echo "  vault:    $VAULT_DIR"
echo "  system:   $SYSTEM_DIR"
[[ -n "$PDFS_DIR" ]] && echo "  pdfs:     $PDFS_DIR"
echo "  target:   $GROUP_DIR"
echo ""

mkdir -p "$GROUP_DIR"
cp "$SYSTEM_DIR/agent/CLAUDE.local.md" "$GROUP_DIR/CLAUDE.local.md"

# Render container.json from the template.
PDFS_MOUNT_BLOCK=""
if [[ -n "$PDFS_DIR" ]]; then
  # Note the leading comma — needed because we're appending to a JSON array.
  PDFS_MOUNT_BLOCK=",
    {
      \"hostPath\": \"$PDFS_DIR\",
      \"containerPath\": \"vault/PDFs\",
      \"readonly\": false
    }"
fi

sed \
  -e "s|{{VAULT_PATH}}|$VAULT_DIR|g" \
  -e "s|{{SYSTEM_PATH}}|$SYSTEM_DIR|g" \
  -e "s|{{GROUP_NAME}}|$GROUP_NAME|g" \
  "$SYSTEM_DIR/agent/container.json.template" \
  | awk -v block="$PDFS_MOUNT_BLOCK" '{ gsub(/\{\{PDFS_MOUNT\}\}/, block); print }' \
  > "$GROUP_DIR/container.json"

# Patch nanoclaw's mount allowlist so the new mounts are permitted.
# The allowlist is global (per-machine), not per-group.
ALLOWLIST="$HOME/.config/nanoclaw/mount-allowlist.json"
mkdir -p "$(dirname "$ALLOWLIST")"

if [[ ! -f "$ALLOWLIST" ]]; then
  cat > "$ALLOWLIST" <<JSON
{
  "allowedRoots": [],
  "blockedPatterns": [],
  "nonMainReadOnly": true
}
JSON
fi

# Use Python to merge — keeps existing entries, idempotent on re-runs.
python3 - "$ALLOWLIST" "$VAULT_DIR" "$SYSTEM_DIR" "${PDFS_DIR:-}" <<'PY'
import json, sys
path, vault, system, pdfs = sys.argv[1:5]
with open(path) as f: cfg = json.load(f)
cfg.setdefault("allowedRoots", [])
have = {r["path"] for r in cfg["allowedRoots"]}
def add(p, rw, desc):
    if p and p not in have:
        cfg["allowedRoots"].append({
            "path": p, "allowReadWrite": rw, "description": desc,
        })
add(vault,  True,  "Literature vault (notes, BibTeX, index)")
add(system, False, "literature-vault-system repo (scripts, docs, agent template)")
if pdfs:
    add(pdfs, True, "Literature vault PDFs (separate storage)")
with open(path, "w") as f: json.dump(cfg, f, indent=2)
print(f"  patched {path}: {len(cfg['allowedRoots'])} allowed roots")
PY

conf_set vault    "$VAULT_DIR"
conf_set nanoclaw "$NANOCLAW_DIR"
conf_set pdfs     "$PDFS_DIR"

echo ""
echo "Done. The agent is registered as nanoclaw group: $GROUP_NAME"
echo ""
echo "Start it via nanoclaw's normal workflow:"
echo "  cd $NANOCLAW_DIR && ./nanoclaw.sh ..."
echo ""
echo "Inside the container, the agent will see:"
echo "  /workspace/extra/vault     ← $VAULT_DIR"
echo "  /workspace/extra/system    ← $SYSTEM_DIR  (read-only)"
[[ -n "$PDFS_DIR" ]] && \
  echo "  /workspace/extra/vault/PDFs ← $PDFS_DIR"
