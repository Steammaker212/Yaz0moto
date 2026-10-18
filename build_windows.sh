#!/bin/bash
# Build Yaz0moto for Windows
# Note: This script is intended to be run in an environment where Windows builds are supported (e.g. Windows with MinGW/Clang-cl or cross-compilation setup).
echo "Building for Windows using universal_venv..."
./universal_venv/bin/python build.py build_exe
echo "Build complete. Check the distrib/ directory."
