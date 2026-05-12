#!/usr/bin/env bash
# Scaffold a literature vault at the requested path.
#
#   ./setup/init-vault.sh [VAULT_DIR]            # default: ~/literature-vault
#   ./setup/init-vault.sh ~/my-vault
#   ./setup/init-vault.sh ~/my-vault --pdfs ~/CloudDrive/papers/PDFs
#   ./setup/init-vault.sh ~/my-vault --adopt     # fill in around existing PaperNotes/PDFs
#
# Default mode: create a fresh, empty vault. Refuses if PaperNotes/ already
# exists (use --adopt instead).
#
# Creates the canonical subdirectories (PaperNotes, Bibfiles, Inbox,
# Collections, Projects, Annotations, SI, optionally PDFs as a symlink),
# an empty index.json, an empty library.bib, a .gitignore, and a symlink
# scripts → the literature-vault-system scripts/ so the host-side viewer
# can find the pipeline.
#
# --adopt mode: VAULT_DIR already has data (typically PaperNotes/ +
# PDFs/). Only creates dirs/files that don't exist yet; never overwrites
# .gitignore, index.json, or library.bib. Replaces a pre-existing
# scripts/ directory or file with the symlink (after warning).

set -euo pipefail

SYSTEM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$SYSTEM_DIR/setup/_lib.sh"
conf_load

VAULT_DIR=""
PDFS_TARGET="$CONF_PDFS"
ADOPT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pdfs)
      PDFS_TARGET="$2"
      shift 2
      ;;
    --adopt)
      ADOPT=1
      shift
      ;;
    --help|-h)
      sed -n '2,22p' "$0"
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

VAULT_DIR="${VAULT_DIR:-${CONF_VAULT:-$HOME/literature-vault}}"
VAULT_DIR="${VAULT_DIR/#\~/$HOME}"

if [[ $ADOPT -eq 0 && -d "$VAULT_DIR/PaperNotes" ]]; then
  echo "error: $VAULT_DIR/PaperNotes already exists — refusing to clobber" >&2
  echo "       to fill in scaffolding around existing data, re-run with --adopt" >&2
  exit 1
fi

if [[ $ADOPT -eq 1 ]]; then
  if [[ ! -d "$VAULT_DIR" ]]; then
    echo "error: --adopt requires an existing directory at $VAULT_DIR" >&2
    exit 1
  fi
  echo "Adopting existing vault at: $VAULT_DIR"
else
  echo "Scaffolding vault at: $VAULT_DIR"
  mkdir -p "$VAULT_DIR"
fi

cd "$VAULT_DIR"

# Create only the dirs that are missing — safe in both fresh and --adopt modes.
for d in PaperNotes Bibfiles Inbox Collections Projects Annotations SI; do
  if [[ -d "$d" ]]; then
    [[ $ADOPT -eq 1 ]] && echo "  $d/ exists, leaving alone"
  else
    mkdir -p "$d"
    echo "  created $d/"
  fi
done

# PDFs: either a symlink to external storage, or a plain directory.
if [[ -e PDFs || -L PDFs ]]; then
  [[ $ADOPT -eq 1 ]] && echo "  PDFs already exists, leaving alone"
  if [[ -n "$PDFS_TARGET" ]]; then
    echo "  warning: --pdfs ignored because PDFs already exists" >&2
  fi
else
  if [[ -n "$PDFS_TARGET" ]]; then
    PDFS_TARGET="${PDFS_TARGET/#\~/$HOME}"
    [[ ! -d "$PDFS_TARGET" ]] && { echo "  creating PDFs target: $PDFS_TARGET"; mkdir -p "$PDFS_TARGET"; }
    ln -s "$PDFS_TARGET" PDFs
    echo "  PDFs/ symlinked to $PDFS_TARGET"
  else
    mkdir -p PDFs
    echo "  created PDFs/"
  fi
fi

# scripts/ must be a symlink to the system repo. In --adopt mode this often
# means replacing a pre-existing directory of stale script copies; we warn
# and back it up to scripts.old (only when it's a directory, not already a
# symlink to somewhere else).
if [[ -L scripts ]]; then
  current_target=$(readlink scripts)
  if [[ "$current_target" != "$SYSTEM_DIR/scripts" ]]; then
    echo "  scripts → $current_target (replacing with → $SYSTEM_DIR/scripts)"
    rm scripts
    ln -s "$SYSTEM_DIR/scripts" scripts
  else
    [[ $ADOPT -eq 1 ]] && echo "  scripts symlink already correct"
  fi
elif [[ -d scripts ]]; then
  if [[ -e scripts.old ]]; then
    echo "error: scripts.old already exists — remove or rename it before re-running" >&2
    exit 1
  fi
  echo "  scripts/ is a real directory — backing up to scripts.old/"
  mv scripts scripts.old
  ln -s "$SYSTEM_DIR/scripts" scripts
elif [[ -e scripts ]]; then
  if [[ -e scripts.old ]]; then
    echo "error: scripts.old already exists — remove or rename it before re-running" >&2
    exit 1
  fi
  echo "  scripts exists as a non-directory file — backing up to scripts.old"
  mv scripts scripts.old
  ln -s "$SYSTEM_DIR/scripts" scripts
else
  ln -s "$SYSTEM_DIR/scripts" scripts
  echo "  scripts symlinked to $SYSTEM_DIR/scripts"
fi

# Seed index.json and library.bib only if missing.
if [[ ! -f index.json ]]; then
  cat > index.json <<'JSON'
{
  "by_doi": {},
  "by_arxiv": {},
  "by_hash": {}
}
JSON
  echo "  wrote index.json"
elif [[ $ADOPT -eq 1 ]]; then
  echo "  index.json exists, leaving alone (run scripts/check_dup.py to verify it's consistent)"
fi

if [[ ! -f library.bib ]]; then
  touch library.bib
  echo "  created empty library.bib (run scripts/build_library_bib.py to aggregate Bibfiles/)"
elif [[ $ADOPT -eq 1 ]]; then
  echo "  library.bib exists, leaving alone"
fi

# .gitignore is only written on fresh installs — adopting users may have
# their own .gitignore we shouldn't clobber.
if [[ ! -f .gitignore ]]; then
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

# ML model weights — large, regenerable from HuggingFace
.embedding_models/

# embed-server log (launchd writes here)
embed-server.log

# The scripts symlink is per-machine; users may install the system at
# different paths
scripts
GITIGNORE
  echo "  wrote .gitignore"
elif [[ $ADOPT -eq 1 ]]; then
  echo "  .gitignore exists, leaving alone (verify it covers: scripts, .embedding_models/, embed-server.log, embeddings.db)"
fi

conf_set vault "$VAULT_DIR"
[[ -L PDFs ]] && conf_set pdfs "$(readlink PDFs)"

echo ""
echo "Done. Next steps:"
echo "  1. Point the viewer at this vault:"
echo "       $SYSTEM_DIR/setup/configure-viewer.sh --vault $VAULT_DIR"
echo "  2. (Optional) install the LiteratureAssistant agent:"
echo "       $SYSTEM_DIR/setup/install-agent.sh \\"
echo "         --vault    $VAULT_DIR \\"
echo "         --nanoclaw \$HOME/repos/nanoclaw \\"
[[ -n "$PDFS_TARGET" ]] && echo "         --pdfs     $PDFS_TARGET"
if [[ $ADOPT -eq 1 ]]; then
  echo ""
  echo "  3. Adoption sanity checks:"
  echo "       - Every PaperNotes/{citekey}.md should have a matching PDFs/{citekey}.pdf"
  echo "       - Build library.bib:  uv run $SYSTEM_DIR/scripts/build_library_bib.py"
  echo "       - Rebuild dedup index from existing notes (TODO: script not yet written)"
fi
