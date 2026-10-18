#!/bin/bash
# Build Yaz0moto for Linux
echo "Building for Linux using universal_venv..."
./universal_venv/bin/python build.py build_exe
echo "Build complete. Check the distrib/ directory."
