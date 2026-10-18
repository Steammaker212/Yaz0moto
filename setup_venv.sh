#!/usr/bin/env bash
# Sets up the Python virtual environment for running or building Yaz0moto

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt

echo ""
echo "Done. Run Yaz0moto with:"
echo "  .venv/bin/python3 yaz0moto.py"
