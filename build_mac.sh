#!/bin/bash
# Build Yaz0moto for macOS
echo "Building for macOS using universal_venv..."
./universal_venv/bin/python build.py bdist_mac
echo "Build complete. Check build/Yaz0moto.app"
