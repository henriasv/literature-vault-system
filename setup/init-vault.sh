#!/usr/bin/env bash
# Scaffold a fresh empty literature vault at the requested path.
#
#   ./setup/init-vault.sh [VAULT_DIR]            # default: ~/literature-vault
#   ./setup/init-vault.sh ~/my-vault
#   ./setup/init-vault.sh ~/my-vault --pdfs ~/CloudDrive/papers/PDFs
#
# Creates the canonical subdirectories (PaperNotes, Bibfiles, Inbox,
# Collections, Projects, optionally PDFs as a symlink), an empty
# index.json, an empty library.bib, and a symlink scripts → the
# literature-vault-system scripts/ so the host-side viewer can find the
# pipeline. Refuses to clobber if PaperNotes/ already exists.

set -euo pipefail

SYSTEM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VAULT_DIR=""
PDFS_TARGET=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pdfs)
      PDFS_TARGET="$2"
      shift 2
      ;;
    --help|-h)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      if [[ -z "$VAULT_DIR" ]]; then
        VAULT_DIR="$1"
      else
        echo "unexpected argument: $1" >&2
        exit 2
      fi
      shift
      ;;
  esac
done

VAULT_DIR="${VAULT_DIR:-$HOME/literature-vault}"
# Expand ~/ if present
VAULT_DIR="${VAULT_DIR/#\~/$HOME}"

if [[ -d "$VAULT_DIR/PaperNotes" ]]; then
  echo "error: $VAULT_DIR/PaperNotes already exists — refusing to clobber" >&2
  echo "       (point install-agent.sh at this existing vault instead)" >&2
  exit 1
fi

echo "Scaffolding vault at: $VAULT_DIR"
mkdir -p "$VAULT_DIR"
cd "$VAULT_DIR"

mkdir -p PaperNotes Bibfiles Inbox Collections Projects

if [[ -n "$PDFS_TARGET" ]]; then
  PDFS_TARGET="${PDFS_TARGET/#\~/$HOME}"
  if [[ ! -d "$PDFS_TARGET" ]]; then
    echo "  creating PDFs target: $PDFS_TARGET"
    mkdir -p "$PDFS_TARGET"
  fi
  ln -s "$PDFS_TARGET" PDFs
  echo "  PDFs/ symlinked to $PDFS_TARGET"
else
  mkdir -p PDFs
fi

# Symlink scripts/ from the system repo so the viewer (which expects
# scripts at <vault>/scripts/) finds the pipeline without duplicating
# files. The agent reads scripts via its OWN separate mount in the
# container, not via this symlink — symlinks across mount boundaries
# don't resolve inside Docker.
ln -s "$SYSTEM_DIR/scripts" scripts

# Seed the dedup index + an empty bib.
cat > index.json <<'JSON'
{
  "by_doi": {},
  "by_arxiv": {},
  "by_hash": {}
}
JSON
touch library.bib

# A sensible .gitignore for users who want to git-track their vault.
cat > .gitignore <<'GITIGNORE'
# uv state — per-machine, shouldn't be committed
.bin/
.uv-pythons/
.uv-cache/

# Embedding DB regenerates from PaperNotes/ — don't bother committing
embeddings.db
embeddings.db-journal

# Inbox is transient — files there haven't been filed yet
Inbox/*

# The scripts symlink is per-machine; users may install the system at
# different paths
scripts
GITIGNORE

echo ""
echo "Done. Next steps:"
echo "  1. Point the viewer at this vault:"
echo "       $SYSTEM_DIR/setup/configure-viewer.sh --vault $VAULT_DIR"
echo "  2. (Optional) install the LiteratureAssistant agent:"
echo "       $SYSTEM_DIR/setup/install-agent.sh \\"
echo "         --vault   $VAULT_DIR \\"
echo "         --system  $SYSTEM_DIR \\"
echo "         --nanoclaw \$HOME/repos/nanoclaw \\"
[[ -n "$PDFS_TARGET" ]] && echo "         --pdfs    $PDFS_TARGET"
