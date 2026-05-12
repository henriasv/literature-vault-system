#!/usr/bin/env bash
# Build the Tauri viewer and install the resulting .app into /Applications.
#
# Prereqs (one-time):
#   - Rust toolchain (rustup, stable)
#   - Node ≥ 18 + npm
#   - macOS: Xcode Command Line Tools (`xcode-select --install`)
#
# Run from anywhere; the script `cd`s into viewer/ relative to itself.

set -euo pipefail

SYSTEM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SYSTEM_DIR/viewer"

echo "→ npm ci (installing JS deps)"
npm ci

echo "→ npm run tauri build"
npm run tauri build

BUNDLE_DIR="src-tauri/target/release/bundle/macos"
APP_PATH=$(find "$BUNDLE_DIR" -maxdepth 1 -name '*.app' -print -quit 2>/dev/null || true)

if [[ -z "$APP_PATH" ]]; then
  echo ""
  echo "Build finished but no .app found under $BUNDLE_DIR." >&2
  echo "Check the build output above for errors." >&2
  exit 1
fi

APP_NAME=$(basename "$APP_PATH")
DEST="/Applications/$APP_NAME"

if [[ -d "$DEST" ]]; then
  echo "→ Existing $DEST will be replaced."
  rm -rf "$DEST"
fi

cp -R "$APP_PATH" /Applications/
echo ""
echo "Installed: $DEST"
echo "Launch it from /Applications or Spotlight."
echo ""
echo "First run: the viewer will prompt for a vault directory."
echo "Already have one? Use $SYSTEM_DIR/setup/configure-viewer.sh"
