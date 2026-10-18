#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Pyamoto Level Editor
# Copyright (C) 2009-2026 Pyamoto contributors
# This file is part of Pyamoto.

# See LICENSE.txt for more information.


################################################################
################################################################

############ Imports ############

import json
import os
from PyQt5 import QtWidgets

from . import globals
from .misc import setting

#################################


def checkContent(data):
    if not data.startswith(b'SARC'):
        return False

    required = (b'course/', b'course1.bin')
    for r in required:
        if r not in data:
            return False

    return True


def IsNSMBLevel(filename):
    """
    Does some basic checks to confirm a file is a NSMB level
    """
    return True
    if not os.path.isfile(filename): return False

    f = open(filename, 'rb')
    data = f.read()
    f.close()
    del f

    if checkContent(data):
        return True


def SetDirty(noautosave=False):
    if globals.DirtyOverride > 0: return

    if not noautosave: globals.AutoSaveDirty = True
    if globals.Dirty: return

    globals.Dirty = True
    try:
        globals.mainWindow.UpdateTitle()
    except Exception:
        pass


def FilesAreMissing():
    """
    Checks to see if any of the required files for Miyamoto are missing
    """

    data_dir = os.path.join(globals.miyamoto_path, 'miyamotodata')
    if not os.path.isdir(data_dir):
        QtWidgets.QMessageBox.warning(None, 'Error', 'Sorry, you seem to be missing the required data files for Yaz0moto to work. Please redownload your copy of the editor.')
        return True

    nsmbu_required = ['main.xml', 'spritedata.xml', 'spritecategories.xml', 'bg.xml',
                      'blankcourse.bin', 'entrances.png', 'entrancetypes.xml',
                      'levelnames.xml', 'music.xml', 'overrides.png',
                      'tilesets.xml', 'tileset1.xml']

    missing = []

    nsmbu_dir = os.path.join(data_dir, 'games', 'NSMBU')
    for check in nsmbu_required:
        if not os.path.isfile(os.path.join(nsmbu_dir, check)):
            missing.append(check)

    if len(missing) > 0:
        QtWidgets.QMessageBox.warning(None, 'Error',
                                      'Sorry, you seem to be missing some of the required data files for Yaz0moto to work. Please redownload your copy of the editor. These are the files you are missing: [files]'.replace('[files]', str(', '.join(missing))))
        return True

    return False


def isValidGamePath(check='ug', game=None):
    """
    Checks to see if the path contains a valid game's levels.
    game: folder name of the base game the path is for (e.g. 'NSMBUDX'); when None,
    the currently loaded game decides how strictly to check.
    """
    if check == 'ug': check = globals.gamedef.GetGamePath()

    if check is None or check == '': return False
    if not os.path.isdir(check): return False

    isDX = (game == 'NSMBUDX') if game is not None else bool(globals.IsNSMBUDX)

    if isDX:
        # Deluxe: little-endian .sarc levels in "Course", with the tilesets in a
        # "Unit" folder right next to it.
        return (os.path.isfile(os.path.join(check, '1-1.sarc')) and
                os.path.isdir(os.path.join(os.path.dirname(os.path.normpath(check)), 'Unit')))

    if not (
        os.path.isfile(os.path.join(check, '1-1.szs')) or os.path.isfile(os.path.join(check, '1-1.sarc'))): return False

    return True


def isValidObjectsPath(path='ug'):
    if path == 'ug': path = setting('ObjPath')
    if not (path and os.path.isdir(path)):
        return False

    folders = os.listdir(path)
    for folder in folders:
        folderPath = os.path.join(path, folder)
        if not os.path.isdir(folderPath):
            continue

        files = [file for file in os.listdir(folderPath) if file[-5:] == ".json"]

        for file in files:
            filePath = os.path.join(folderPath, file)
            if not os.path.isfile(filePath):
                continue

            with open(filePath) as inf:
                jsonData = json.load(inf)

            if not ("colls" in jsonData and "meta" in jsonData and "objlyt" in jsonData
                    and "img" in jsonData and "nml" in jsonData):
                continue
            
            found = True
            for f in ["colls", "meta", "objlyt", "img", "nml"]:
                if not os.path.isfile(os.path.join(folderPath, jsonData[f])):
                    found = False
                    break

            if found:
                return True

    return False
