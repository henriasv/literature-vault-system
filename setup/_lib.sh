#!/usr/bin/env bash
# Shared helpers for setup scripts.
#
# Tracks per-machine install state in setup/.local.conf (KEY=value,
# gitignored). The conf is a convenience: each setup script's --vault /
# --nanoclaw / --pdfs flag defaults to whatever was previously stored,
# and any flag value passed in is written back. Flags always take
# precedence, so the conf is invisible to anyone who prefers to be
# explicit.
#
# Source this file from a setup script; do not execute directly.
#
#   source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
#   conf_load
#   VAULT_DIR="${VAULT_DIR:-$CONF_VAULT}"
#   ... after validating $VAULT_DIR ...
#   conf_set vault "$VAULT_DIR"

CONF_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.local.conf"

CONF_VAULT=""
CONF_NANOCLAW=""
CONF_PDFS=""

conf_load() {
  [[ -f "$CONF_FILE" ]] || return 0
  # The file is plain `KEY=value` lines (no shell expansion, no quotes
  # required). Read manually so we don't `source` user-controlled
  # content directly.
  while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    case "$key" in
      vault)    CONF_VAULT="$value" ;;
      nanoclaw) CONF_NANOCLAW="$value" ;;
      pdfs)     CONF_PDFS="$value" ;;
    esac
  done < "$CONF_FILE"
}

conf_set() {
  local key="$1" value="$2"
  [[ -z "$value" ]] && return 0
  mkdir -p "$(dirname "$CONF_FILE")"
  local tmp
  tmp=$(mktemp "${CONF_FILE}.XXXXXX")
  if [[ -f "$CONF_FILE" ]]; then
    grep -v "^${key}=" "$CONF_FILE" > "$tmp" || true
  fi
  echo "${key}=${value}" >> "$tmp"
  mv "$tmp" "$CONF_FILE"
}
