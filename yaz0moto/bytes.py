#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Pyamoto Level Editor
# Copyright (C) 2009-2026 Pyamoto contributors
# This file is part of Pyamoto.

# See LICENSE.txt for more information.


################################################################
################################################################

def bytes_to_string(data, offset=0, charWidth=1, encoding='utf-8'):
    # Thanks RoadrunnerWMC
    end = data.find(b'\0' * charWidth, offset)
    if end == -1:
        return data[offset:].decode(encoding)

    return data[offset:end].decode(encoding)


def to_bytes(inp, length=1, endianness='big'):
    if isinstance(inp, bytearray):
        return bytes(inp)

    elif isinstance(inp, int):
        return inp.to_bytes(length, endianness)

    elif isinstance(inp, str):
        return inp.encode('utf-8').ljust(length, b'\0')
