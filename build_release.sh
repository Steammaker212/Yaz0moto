#!/usr/bin/env bash
# build_release.sh — build a release binary for the current platform.
#
# Usage:
#   ./build_release.sh [version]
#
# If version is omitted it is read from project.json.
# The built output goes to build/ (macOS .app) or distrib/miyamoto_v<version>/
# for Windows/Linux, matching the layout cx_Freeze produces.
#
# The script temporarily stamps project.json with release_type=release (and
# the supplied version) before building, then restores the original file.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Read the current version from project.json ──────────────────────────────
CURRENT_VERSION="$(.venv/bin/python3 -c 'import json; print(json.load(open("project.json"))["version"])')"
VERSION="${1:-$CURRENT_VERSION}"

echo "==> Building Yaz0moto release v${VERSION}"

# ── Patch project.json (restore on exit) ────────────────────────────────────
cp project.json project.json.bak
trap 'mv project.json.bak project.json; echo "==> Restored project.json"' EXIT

.venv/bin/python3 -c "import json,sys; d=json.load(open('project.json')); d['version']=sys.argv[1]; d['release_type']='release'; open('project.json','w').write(json.dumps(d,indent=4))" "$VERSION"

echo "==> project.json patched: version=${VERSION}, release_type=release"

# ── Build ────────────────────────────────────────────────────────────────────
if [[ "$(uname)" == "Darwin" ]]; then
    echo "==> macOS: building universal app bundle + updater zip"
    export ARCHFLAGS="${ARCHFLAGS:--arch x86_64 -arch arm64}"
    .venv/bin/python3 build.py build_ext --inplace bdist_mac
    echo "==> Packaging app bundle as zip..."
    ARCH=$(uname -m)
    cd build && zip -r "../Yaz0moto-v${VERSION}-macOS-${ARCH}.zip" Yaz0moto.app && cd ..
    echo "==> Done. Zip: Yaz0moto-v${VERSION}-macOS-${ARCH}.zip"
else
    echo "==> Linux/Windows: building frozen executable"
    .venv/bin/python3 build.py build_ext --inplace build_exe
    echo "==> Done. Output: distrib/miyamoto_v${VERSION}/"
fi
