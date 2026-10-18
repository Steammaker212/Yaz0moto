#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Yaz0moto Level Editor — entry point
# Run this file directly: python yaz0moto.py

import os
import sys

# Ensure the project root (this file's directory) is on sys.path so that the
# miyamoto package and all root-level libraries (addrlib, bc3, fastyz, etc.) resolve.
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

# xcb platform avoids software rendering fallback and related performance issues on Linux
if sys.platform.startswith('linux') and 'QT_QPA_PLATFORM' not in os.environ:
    os.environ['QT_QPA_PLATFORM'] = 'xcb'

from miyamoto.app import main

if __name__ == '__main__':
    main()
