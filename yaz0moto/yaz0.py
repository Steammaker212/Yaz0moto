#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Pyamoto Level Editor
# Copyright (C) 2009-2026 Pyamoto contributors
# This file is part of Pyamoto.

# See LICENSE.txt for more information.

# yaz0.py
# Multiple methods for Yaz0 (de)compression


################################################################
################################################################

import os

import fastyz


def writeFile(path, data):
    """
    Writes data to path without ever leaving a half-written file behind: the data
    goes to a temporary file next to it, which then replaces the original in one
    step. Raises OSError if that fails; the original file is then untouched.
    """
    tmp = '%s.%d.tmp' % (path, os.getpid())
    try:
        with open(tmp, 'wb') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def compressFASTYZ(inb, outf):
    """
    Compress the file using fastYZ. Returns False if compressing or writing failed
    (the original file is then untouched).
    """
    try:
        data = fastyz.compress(inb)
        writeFile(outf, data)

    except Exception as e:
        print(f"DEBUG - Compression failed because: {repr(e)}")
        return False

    else:
        return True


def decompressFASTYZ(inb):
    """
    Decompress the file using fastYZ
    """
    try:
        data = fastyz.decompress(inb)

    except Exception as e:
        print(f"DEBUG - Decompression failed because: {repr(e)}")
        return None

    else:
        return data
