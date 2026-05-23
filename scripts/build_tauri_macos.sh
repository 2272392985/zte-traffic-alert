#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This script must be run on macOS to build the Tauri .app/.dmg targets."
  exit 1
fi

cd "$PROJECT_DIR"

if ! command -v cargo >/dev/null 2>&1; then
  echo "Rust/Cargo was not found. Install Rust first: https://www.rust-lang.org/tools/install"
  exit 1
fi

npm install
npm run tauri:build

echo "Tauri macOS artifacts are under: $PROJECT_DIR/src-tauri/target/release/bundle"
