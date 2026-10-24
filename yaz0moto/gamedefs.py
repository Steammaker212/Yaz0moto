#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Pyamoto Level Editor
# Copyright (C) 2009-2026 Pyamoto contributors
# This file is part of Pyamoto.

# See LICENSE.txt for more information.


################################################################
################################################################

############ Imports ############

import types
import os
from PyQt5 import QtWidgets
import sys
from xml.etree import ElementTree as etree

from . import globals
from .misc import setting, setSetting

#################################


def _mod_root(folder_name):
    """Return the directory containing main.xml for a mod, checking userdata first."""
    _user = os.path.join(globals.user_data_path, 'patches', folder_name)
    if os.path.isfile(os.path.join(_user, 'main.xml')):
        return os.path.join(globals.user_data_path, 'patches')
    return os.path.join(globals.miyamoto_path, 'yaz0data', 'patches')


class MiyamotoGameDefinition:
    """
    A class that defines a NSMBU game or mod: songs, tilesets, sprites, etc.
    source='game' → loaded from yaz0data/games/
    source='mod'  → loaded from yaz0data/patches/ or userdata/patches/
    """

    class GameDefinitionFile:
        def __init__(self, path, patch):
            self.path = path
            self.patch = patch

    def __init__(self, name=None, source='mod', base_instance=None):
        self.InitAsEmpty()
        NoneTypes = (None, 'None', 0, '', True, False)
        if name in NoneTypes:
            return
        try:
            self.InitFromName(name, source, base_instance)
            # Validate referenced files exist
            missing = []
            for f in self.files.values():
                if f.path is not None and not os.path.isfile(f.path):
                    missing.append(f.path)
            for f in self.folders.values():
                if f.path is not None and not os.path.isdir(f.path):
                    missing.append(f.path)
            if missing:
                self.error = 'Referenced files missing:\n  ' + '\n  '.join(missing)
        except Exception as e:
            self.InitAsEmpty()
            self.custom = True
            self.gamepath = name
            self.name = str(name) if name else 'Unknown'
            self.base = base_instance
            self.error = str(e)

    def InitAsEmpty(self):
        gdf = self.GameDefinitionFile
        self.custom = False
        self.isDX = False      # True for New Super Mario Bros. U Deluxe (Switch) and anything built on it
        self.source = 'base'   # 'base' | 'game' | 'mod'
        self.base = None
        self.gamepath = None   # folder name within source directory
        self.name = 'New Super Mario Bros. U'
        self.description = 'A new adventure, and in HD!<br>Published by Nintendo in August 2012.'
        self.version = '1.0'
        self.patchReleaseUrl = None
        self.error = None

        from . import sprites as _sprites_mod
        self.sprites = _sprites_mod

        self.files = {
            'bg': gdf(None, False),
            'blankcourse': gdf(None, False),
            'entrances': gdf(None, False),
            'entrancetypes': gdf(None, False),
            'levelnames': gdf(None, False),
            'music': gdf(None, False),
            'overrides': gdf(None, False),
            'spritecategories': gdf(None, False),
            'spritedata': gdf(None, False),
            'spritelistdata': gdf(None, False),
            'spritenames': gdf(None, False),
            'spriteresources': gdf(None, False),
            'tilesets': gdf(None, False),
            'tileset1': gdf(None, False),
        }
        self.folders = {
            'bg': gdf(None, False),
            'sprites': gdf(None, False),
            'data': gdf(None, False),
        }

    def InitFromName(self, name, source='mod', base_instance=None):
        self.custom = True
        self.source = source
        name = str(name)
        self.gamepath = name

        if source == 'game':
            _root = os.path.join(globals.miyamoto_path, 'yaz0data', 'games')
        else:
            _root = _mod_root(name)

        xml_path = os.path.join(_root, name, 'main.xml')
        tree = etree.parse(xml_path)
        root = tree.getroot()

        if 'name' not in root.attrib:
            raise Exception('main.xml missing name attribute')
        self.name = root.attrib['name']

        self.description = '<i>No description</i>'
        if 'description' in root.attrib:
            self.description = root.attrib['description'].replace('[', '<').replace(']', '>')
        self.version = root.attrib.get('version', None)
        self.patchReleaseUrl = root.attrib.get('patchReleaseUrl', None)

        if base_instance is not None:
            self.base = base_instance
        elif 'base' in root.attrib:
            self.base = FindGameDef(root.attrib['base'], name)
        else:
            self.base = MiyamotoGameDefinition()

        # Which console version of the game this definition describes. An explicit
        # platform="nsmbudx" selects Deluxe; otherwise inherit from the base
        # (so mods built on top of Deluxe are Deluxe too).
        platform = root.attrib.get('platform', '').strip().lower()
        if platform:
            self.isDX = platform == 'nsmbudx'
        else:
            self.isDX = bool(getattr(self.base, 'isDX', False))

        addpath = os.path.join(_root, name) + os.sep
        for node in root:
            n = node.tag.lower()
            if n in ('file', 'folder'):
                fpath = addpath + node.attrib['path']
                patch = node.attrib.get('patch', 'true').lower() == 'true'

                if 'game' in node.attrib:
                    game_attr = node.attrib['game']
                    if game_attr != 'New Super Mario Bros. U':
                        ref_def = FindGameDef(game_attr, name)
                        if ref_def is not None:
                            if ref_def.source == 'game':
                                ref_root = os.path.join(globals.miyamoto_path, 'yaz0data', 'games')
                            else:
                                ref_root = _mod_root(ref_def.gamepath)
                            fpath = os.path.join(ref_root, ref_def.gamepath, node.attrib['path'])
                    else:
                        fpath = os.path.join(globals.miyamoto_path, 'yaz0data', 'games', 'NSMBU', node.attrib['path'])

                target = self.files if n == 'file' else self.folders
                target[node.attrib['name']] = self.GameDefinitionFile(fpath, patch)

        del tree, root

        if 'sprites' in self.files and self.files['sprites'].path is not None:
            with open(self.files['sprites'].path, 'r') as f:
                filedata = f.read()
            new_module = types.ModuleType(self.name + '->sprites')
            exec(filedata, new_module.__dict__)
            sys.modules[new_module.__name__] = new_module
            self.sprites = new_module

    def GetGamePath(self):
        if not self.custom:
            return str(setting('GamePath_NSMBU', setting('GamePath', '')))
        if self.source == 'game':
            key = 'GamePath_' + self.gamepath
            # The legacy single "GamePath" setting only ever held the Wii U game
            return str(setting(key, setting('GamePath', '') if self.gamepath == 'NSMBU' else ''))
        else:
            key = 'GamePath_mod_' + self.gamepath
            return str(setting(key, ''))

    def SetGamePath(self, path):
        if not self.custom:
            setSetting('GamePath_NSMBU', path)
            setSetting('GamePath', path)
        elif self.source == 'game':
            key = 'GamePath_' + self.gamepath
            setSetting(key, path)
            if self.gamepath == 'NSMBU':
                setSetting('GamePath', path)
        else:
            key = 'GamePath_mod_' + self.gamepath
            setSetting(key, path)

    def GetGamePaths(self):
        if not self.custom:
            return [str(setting('GamePath_NSMBU', setting('GamePath', '')))]
        if self.source == 'game':
            key = 'GamePath_' + self.gamepath
            path = str(setting(key, setting('GamePath', '') if self.gamepath == 'NSMBU' else ''))
        else:
            key = 'GamePath_mod_' + self.gamepath
            path = str(setting(key, ''))
        paths = self.base.GetGamePaths() if self.base else []

        # A game that only borrows *data* (sprites, tilesets lists, ...) from a base on
        # a different platform must not search that base's game files: Wii U levels and
        # Switch levels are not interchangeable.
        if self.base is not None and self.isDX != getattr(self.base, 'isDX', False):
            paths = []

        paths.append(path)
        return paths

    def GetUnitPaths(self):
        """
        Deluxe only: the existing "Unit" folders (where tilesets live) that sit next to
        each game/mod "Course" folder, most specific (mods) first.
        """
        units = []
        for path in reversed(self.GetGamePaths()):
            if not path:
                continue

            unit = os.path.join(os.path.dirname(os.path.normpath(path)), 'Unit')
            if os.path.isdir(unit) and unit not in units:
                units.append(unit)

        return units

    def FindTilesetFile(self, name):
        """
        Deluxe only: path of the tileset archive "<name>.szs" in the most specific
        Unit folder that has it, or None.
        """
        for unit in self.GetUnitPaths():
            candidate = os.path.join(unit, name + '.szs')
            if os.path.isfile(candidate):
                return candidate

        return None

    def FindDistantViewFile(self, name):
        """
        Deluxe only: path of the background model "dv_<name>.Nin_NX_NVN.szs" in the most
        specific "Model" folder (next to a game/mod "Course" folder) that has it, or None.
        """
        filename = 'dv_%s.Nin_NX_NVN.szs' % name
        for path in reversed(self.GetGamePaths()):
            if not path:
                continue

            candidate = os.path.join(os.path.dirname(os.path.normpath(path)), 'Model', filename)
            if os.path.isfile(candidate):
                return candidate

        return None

    def GetLastLevel(self):
        """
        Returns the last loaded level
        """
        if not self.custom: return setting('LastLevel')
        name = 'LastLevel_' + self.name
        stg = setting(name)

        # Use the default if there are no settings for this yet
        if stg is None:
            return setting('LastLevel')
        else:
            return stg

    def SetLastLevel(self, path):
        """
        Sets the last loaded level
        """
        if path in (None, 'None', 'none', True, 'True', 'true', False, 'False', 'false', 0, 1, ''): return
        print('Last loaded level set to ' + str(path))
        if not self.custom:
            setSetting('LastLevel', path)
        else:
            name = 'LastLevel_' + self.name
            setSetting(name, path)

    def patchFolders(self):
        """
        The folders of the patches (mods) this game is made of, most specific first:
        <patches folder>/<patch name>
        """
        folders = []
        gamedef = self
        while gamedef is not None:
            if gamedef.custom and gamedef.source == 'mod' and gamedef.gamepath:
                folders.append(os.path.join(_mod_root(gamedef.gamepath), gamedef.gamepath))
            gamedef = gamedef.base
        return folders

    def recursiveFiles(self, name, isPatch=False, folder=False):
        """
        Checks each base of this gamedef and returns a list of successive file paths
        """
        ListToCheckIn = self.files if not folder else self.folders

        # This can be handled 4 ways: if we do or don't have a base, and if we do or don't have a copy of the file.
        if self.base is None:
            if ListToCheckIn[name].path is None:  # No base, no file

                if isPatch:
                    return [], True
                else:
                    return []

            else:  # No base, file

                alist = []
                alist.append(ListToCheckIn[name].path)
                if isPatch:
                    return alist, ListToCheckIn[name].patch
                else:
                    return alist

        else:

            if isPatch:
                listUpToNow, wasPatch = self.base.recursiveFiles(name, True, folder)
            else:
                listUpToNow = self.base.recursiveFiles(name, False, folder)

            if ListToCheckIn[name].path is None:  # Base, no file

                if isPatch:
                    return listUpToNow, wasPatch
                else:
                    return listUpToNow

            else:  # Base, file

                # If it's a patch, just add it to the end of the list
                if ListToCheckIn[name].patch:
                    listUpToNow.append(ListToCheckIn[name].path)

                # If it's not (it's free-standing), make a new list and start over
                else:
                    newlist = []
                    newlist.append(ListToCheckIn[name].path)
                    if isPatch:
                        return newlist, False
                    else:
                        return newlist

                # Return
                if isPatch:
                    return listUpToNow, wasPatch
                else:
                    return listUpToNow

    def multipleRecursiveFiles(self, *args):
        """
        Returns multiple recursive files in order of least recent to most recent as a list of tuples, one list per gamedef base
        """

        # This should be very simple
        # Each arg should be a file name
        if self.base is None or self.base.base is None:
            main = []  # start a new level
        else:
            main = self.base.multipleRecursiveFiles(*args)

        # Add the values from this level, and then return it
        result = []
        for name in args:
            try:
                file = self.files[name]
                if file.path is None: raise KeyError
                result.append(self.files[name])
            except KeyError:
                result.append(None)
        main.append(tuple(result))
        return main

    def file(self, name):
        """
        Returns a file by recursively checking successive gamedef bases
        """
        if name not in self.files: return

        if self.files[name].path is not None:
            return self.files[name].path
        else:
            if self.base is None: return
            return self.base.file(name)  # it can recursively check its base, too

    def getImageClasses(self):
        """
        Gets all image classes, bridging string_id entries to their
        allocated integer IDs so level sprites find the right class.
        """
        if not self.custom:
            return self.sprites.ImageClasses

        if self.base is not None:
            images = dict(self.base.getImageClasses())
        else:
            images = {}

        if hasattr(self.sprites, 'ImageClasses'):
            images.update(self.sprites.ImageClasses)

        # Map string_id image classes to every positional alias in the loaded
        # level. int_to_string is authoritative for on-disk Fxxx IDs.
        has_level = hasattr(globals, 'Level') and globals.Level is not None
        id_mgr = getattr(globals.Level, 'id_manager', None) if has_level else None
        if id_mgr is not None:
            for int_id, str_id in id_mgr.int_to_string.items():
                if str_id in images:
                    images[int_id] = images[str_id]

        return images


def getMusic():
    """
    Uses the current gamedef to get the music data, and returns it as a list of tuples
    """

    paths = globals.gamedef.recursiveFiles('music')

    songs = []
    for path in paths:
        tree = etree.parse(path)
        root = tree.getroot()
        for song in root:
            if song.tag.lower() != 'song':
                continue
            sid = song.attrib['id']
            name = song.attrib['name']
            found = False
            for s in songs:
                if s[0] == sid:
                    s[1] = name
                    found = True
            if not found:
                songs.append([sid, name])

    return songs


def FindGameDef(name, skip=None):
    """Find a gamedef by its display name, searching games/ then patches/."""
    # Search base games
    _games = os.path.join(globals.miyamoto_path, 'yaz0data', 'games')
    if os.path.isdir(_games):
        for folder in os.listdir(_games):
            if folder == skip:
                continue
            folder_path = os.path.join(_games, folder)
            main_xml = os.path.join(folder_path, 'main.xml')
            if not os.path.isfile(main_xml):
                if os.path.islink(folder_path) and os.path.exists(os.path.realpath(folder_path)):
                    main_xml = os.path.join(os.path.realpath(folder_path), 'main.xml')
                    if not os.path.isfile(main_xml):
                        continue
                else:
                    continue
            def_ = MiyamotoGameDefinition(folder, source='game')
            if def_.custom and def_.error is None and def_.name == name:
                return def_

    # Search bundled mods
    _patches = os.path.join(globals.miyamoto_path, 'yaz0data', 'patches')
    if os.path.isdir(_patches):
        for folder in os.listdir(_patches):
            if folder == skip:
                continue
            folder_path = os.path.join(_patches, folder)
            main_xml = os.path.join(folder_path, 'main.xml')
            if not os.path.isfile(main_xml):
                if os.path.islink(folder_path) and os.path.exists(os.path.realpath(folder_path)):
                    main_xml = os.path.join(os.path.realpath(folder_path), 'main.xml')
                    if not os.path.isfile(main_xml):
                        continue
                else:
                    continue
            def_ = MiyamotoGameDefinition(folder, source='mod')
            if def_.custom and def_.error is None and def_.name == name:
                return def_

    # Search user mods
    _user = os.path.join(globals.user_data_path, 'patches')
    if os.path.isdir(_user):
        for folder in os.listdir(_user):
            if folder == skip:
                continue
            folder_path = os.path.join(_user, folder)
            main_xml = os.path.join(folder_path, 'main.xml')
            if not os.path.isfile(main_xml):
                if os.path.islink(folder_path) and os.path.exists(os.path.realpath(folder_path)):
                    main_xml = os.path.join(os.path.realpath(folder_path), 'main.xml')
                    if not os.path.isfile(main_xml):
                        continue
                else:
                    continue
            def_ = MiyamotoGameDefinition(folder, source='mod')
            if def_.custom and def_.error is None and def_.name == name:
                return def_

    return None


def IsBaseGameDX(folder):
    """True if the base game in yaz0data/games/<folder> is the Switch (Deluxe) version."""
    try:
        return bool(MiyamotoGameDefinition(folder, source='game').isDX)
    except Exception:
        return False


def getAvailableBaseGames():
    """Return list of (MiyamotoGameDefinition, folder_name) for all base games, sorted by name."""
    games = []
    _dir = os.path.join(globals.miyamoto_path, 'yaz0data', 'games')
    if not os.path.isdir(_dir):
        return games
    for folder in sorted(os.listdir(_dir)):
        folder_path = os.path.join(_dir, folder)
        if not os.path.isdir(folder_path):
            continue
        if not os.path.isfile(os.path.join(folder_path, 'main.xml')):
            continue
        def_ = MiyamotoGameDefinition(folder, source='game')
        if def_.custom:
            games.append((def_, folder))
    # NSMBU always first; everything else alphabetical by display name
    return sorted(games, key=lambda x: (x[1] != 'NSMBU', x[0].name))


def _load_mod_entry(folder, patches_root, source, base_game_names):
    """Try to load a mod; return (def_, folder) on success or (broken_def, folder) with def_.error set."""
    if folder in base_game_names:
        return None

    mod_dir = os.path.join(patches_root, folder)
    main_xml = os.path.join(mod_dir, 'main.xml')
    is_link = os.path.islink(mod_dir)

    # Resolve symlinks explicitly
    if is_link:
        real = os.path.realpath(mod_dir)
        if not os.path.exists(real):
            def_ = MiyamotoGameDefinition()
            def_.custom = True
            def_.name = folder
            def_.gamepath = folder
            def_.error = f'Broken symlink: → {os.readlink(mod_dir)} (target does not exist)'
            return (def_, folder)
        if not os.path.isdir(real):
            def_ = MiyamotoGameDefinition()
            def_.custom = True
            def_.name = folder
            def_.gamepath = folder
            def_.error = f'Symlink target is not a directory: → {os.readlink(mod_dir)}'
            return (def_, folder)
    elif not os.path.isdir(mod_dir):
        return None  # skip regular files

    if not os.path.isfile(main_xml):
        def_ = MiyamotoGameDefinition()
        def_.custom = True
        def_.name = folder
        def_.gamepath = folder
        if is_link:
            def_.error = f'Missing main.xml (resolved: {os.path.realpath(mod_dir)})'
        else:
            def_.error = 'Missing main.xml'
        return (def_, folder)

    def_ = MiyamotoGameDefinition(folder, source=source)
    return (def_, folder)


def getAvailableMods():
    """Return list of (MiyamotoGameDefinition, folder_name) for all mods (user overrides bundled).
    Broken entries (symlink errors, missing main.xml, load failures) are included with def_.error set."""
    mods = {}  # folder_name -> (def_, folder)

    # Collect base game folder names so we can skip them in the mods list
    _base_game_names = set()
    _games_dir = os.path.join(globals.miyamoto_path, 'yaz0data', 'games')
    if os.path.isdir(_games_dir):
        _base_game_names = {f for f in os.listdir(_games_dir)
                            if os.path.isdir(os.path.join(_games_dir, f))}

    # Bundled mods first
    _patches = os.path.join(globals.miyamoto_path, 'yaz0data', 'patches')
    if os.path.isdir(_patches):
        for folder in os.listdir(_patches):
            result = _load_mod_entry(folder, _patches, 'mod', _base_game_names)
            if result is not None:
                mods[folder] = result

    # User mods override bundled with same folder name
    _user = os.path.join(globals.user_data_path, 'patches')
    if os.path.isdir(_user):
        for folder in os.listdir(_user):
            result = _load_mod_entry(folder, _user, 'mod', _base_game_names)
            if result is not None:
                mods[folder] = result

    return sorted(mods.values(), key=lambda x: x[0].name)


def loadNewGameDef(base_game=None, mods=None):
    """Load a game + mods combo with a progress dialog."""
    if mods is None:
        mods = []
    dlg = QtWidgets.QProgressDialog()
    dlg.setAutoClose(True)
    btn = QtWidgets.QPushButton('Cancel')
    btn.setEnabled(False)
    dlg.setCancelButton(btn)
    dlg.show()
    dlg.setValue(0)

    from . import loading
    loading.LoadGameDef(base_game, mods, dlg)
    del loading

    dlg.setValue(100)
    del dlg
