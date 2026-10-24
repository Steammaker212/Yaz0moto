#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Pyamoto Level Editor
# Copyright (C) 2009-2026 Pyamoto contributors
# This file is part of Pyamoto.

# See LICENSE.txt for more information.


################################################################x
################################################################


from enum import Enum
from . import globals


class Structures(Enum):
    CourseBlock  = 'II'
    Background   = 'Hhhh16sHxx'
    Sprite       = 'HHHHIIBB2sBxxx'
    Options      = 'IIHHxBBBBxxBHH'
    Entrance     = 'HHhhBBBBBBxBHBBBBBx'
    Boundings    = 'llllHHhhxxxx'
    Zone         = 'HHHHHHBBBBBBBBBBBBBBxx'
    Location     = 'HHHHBxxx'
    LayerObject  = 'HhhHHB'
    Path         = 'BbHHHxxxx'
    PathNode     = 'HHffhHBBBx'
    LoadedSprite = 'Hxx'


def GetFormat(structId):
    assert isinstance(structId, Structures)

    endianness = '<' if globals.IsNSMBUDX else '>'
    formatStr = structId.value

    return endianness + formatStr
