#!/bin/bash
# Build Yaz0moto for macOS (Universal Binary)
set -e

echo "Step 1: Building with universal_venv..."
./universal_venv/bin/python build.py bdist_mac

echo "Step 2: Merging architectures and signing..."
./universal_venv/bin/python merge_universal.py

echo "Universal Build complete. Check build/Yaz0moto.app"
