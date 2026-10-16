#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Pyamoto Level Editor
# Copyright (C) 2009-2026 Pyamoto contributors
# This file is part of Pyamoto.

# See LICENSE.txt for more information.


################################################################
################################################################

############ Imports ############

import os

from PyQt5 import QtGui, QtWidgets
import struct
from xml.etree import ElementTree as etree

from . import globals
from . import spritelib as SLib
from . import yaz0
from .gamedefs import MiyamotoGameDefinition
from .misc import SpriteDefinition, BGName, setting, setSetting
import SarcLib

from .tileset import TilesetTile, ObjectDef
from .tileset import loadGTX, loadBNTXFromBFRES, loadTexFromBNTX, ProcessOverrides
from .tileset import CascadeTilesetNames_Category
from .tileset import SortTilesetNames_Category

from .ui import MiyamotoTheme

#################################


def LoadTheme():
    """
    Loads the theme
    """
    id = setting('Theme')
    if id is None: id = 'Classic'
    print('THEME ID: ' + str(id))
    globals.theme = MiyamotoTheme(id)


def LoadBGNames():
    """
    Loads the BG names and their translations
    """
    globals.names_bg = []

    paths = globals.gamedef.recursiveFiles('bg')
    for path in paths:
        try:
            tree = etree.parse(path)
        except Exception:
            continue
        root = tree.getroot()
        for bg_node in root:
            if bg_node.tag.lower() != 'bg':
                continue
            name = bg_node.attrib['name']
            trans = bg_node.text.strip() if bg_node.text else ''
            if name and trans:
                globals.names_bg.append(BGName(name, trans))

    globals.names_bg.append(BGName.Custom())


def LoadLevelNames():
    """
    Ensures that the level name info is loaded
    """
    paths = globals.gamedef.recursiveFiles('levelnames')

    globals.LevelNames = []

    for path in paths:
        # Parse the file
        tree = etree.parse( path )
        root = tree.getroot()

        # Parse the nodes (root acts like a large category)
        patchLevelNames = LoadLevelNames_Category(root)
        LoadLevelNames_ReplaceCategory(globals.LevelNames, patchLevelNames)
        LoadLevelNames_AddMissingCategories(globals.LevelNames, patchLevelNames)


def LoadLevelNames_ReplaceCategory(node, node_patch):
    for child in node:
        for child_patch in node_patch:
            if isinstance(child[1], list) and isinstance(child_patch[1], list) and child[0] == child_patch[0]:
                LoadLevelNames_ReplaceCategory(child[1], child_patch[1])
                break
            elif isinstance(child[1], str) and isinstance(child_patch[1], str) and child[1] == child_patch[1]:
                child[0] = child_patch[0]
                break


def LoadLevelNames_AddMissingCategories(node, node_patch):
    for child_patch in node_patch:
        if isinstance(child_patch[1], list):
            found = False
            for child in node:
                if isinstance(child[1], list) and child[0] == child_patch[0]:
                    found = True
                    break
            if found:
                LoadLevelNames_AddMissingCategories(child[1], child_patch[1])
            else:
                node += [child_patch]

        else:
            for child in node:
                if isinstance(child[1], str) and child[1] == child_patch[1]:
                    break
            else:
                node += [child_patch]


def LoadLevelNames_Category(node):
    """
    Loads a LevelNames XML category
    """
    cat = []
    for child in node:
        if child.tag.lower() == 'category':
            cat.append([str(child.attrib['name']), LoadLevelNames_Category(child)])
        elif child.tag.lower() == 'level':
            cat.append([str(child.attrib['name']), str(child.attrib['file'])])
    return cat


def LoadTilesetNames(reload_=False):
    """
    Ensures that the tileset name info is loaded
    """
    if (globals.TilesetNames is not None) and (not reload_): return

    # Get paths
    paths = globals.gamedef.recursiveFiles('tilesets')

    # Read each file
    globals.TilesetNames = [[[], False], [[], False], [[], False], [[], False]]
    for path in paths:
        tree = etree.parse(path)
        root = tree.getroot()

        # Go through each slot
        for node in root:
            if node.tag.lower() != 'slot': continue
            try:
                slot = int(node.attrib['num'])
            except ValueError:
                continue
            if slot > 3: continue

            # Parse the category data into a list
            newlist = [LoadTilesetNames_Category(node), ]
            if 'sorted' in node.attrib:
                newlist.append(node.attrib['sorted'].lower() == 'true')
            else:
                newlist.append(globals.TilesetNames[slot][1])  # inherit

            # Apply it as a patch over the current entry
            newlist[0] = CascadeTilesetNames_Category(globals.TilesetNames[slot][0], newlist[0])

            # Sort it
            if not newlist[1]:
                newlist[0] = SortTilesetNames_Category(newlist[0])

            globals.TilesetNames[slot] = newlist


def LoadTilesetNames_Category(node):
    """
    Loads a TilesetNames XML category
    """
    cat = []
    for child in node:
        if child.tag.lower() == 'category':
            new = [
                str(child.attrib['name']),
                LoadTilesetNames_Category(child),
            ]
            if 'sorted' in child.attrib:
                new.append(str(child.attrib['sorted'].lower()) == 'true')
            else:
                new.append(False)
            cat.append(new)
        elif child.tag.lower() == 'tileset':
            cat.append((str(child.attrib['filename']), str(child.attrib['name'])))
    return list(cat)


def LoadObjDescriptions(reload_=False):
    """
    Ensures that the object description is loaded
    """
    if (globals.ObjDesc is not None) and not reload_: return

    paths = globals.gamedef.recursiveFiles('tileset1')

    globals.ObjDesc = {}
    for path in paths:
        tree = etree.parse(path)
        root = tree.getroot()
        for tile in root:
            if tile.tag.lower() != 'tile':
                continue
            globals.ObjDesc[int(tile.attrib['id'])] = tile.attrib['name']


def LoadSpriteData():
    """
    Ensures that the sprite data info is loaded
    """
    errors = []
    errortext = []

    spriteIds = [-1]

    # Game data loads first (NSMBU base), mods load after and overwrite via the chain.
    paths = list(globals.gamedef.multipleRecursiveFiles('spritedata', 'spritenames'))

    for sdpath, snpath in paths:

        # Add XML sprite data, if there is any
        if sdpath not in (None, ''):
            path = sdpath if isinstance(sdpath, str) else sdpath.path
            tree = etree.parse(path)
            root = tree.getroot()

            for sprite in root:
                if sprite.tag.lower() != 'sprite':
                    continue

                if 'id' in sprite.attrib:
                    try:
                        spriteIds.append(int(sprite.attrib['id']))
                    except ValueError:
                        continue

    globals.NumSprites = max(spriteIds) + 1
    globals.CustomSpriteDefinitions = {}
    globals.Sprites = [None] * globals.NumSprites

    for sdpath, snpath in paths:

        # Add XML sprite data, if there is any
        if sdpath not in (None, ''):
            path = sdpath if isinstance(sdpath, str) else sdpath.path
            tree = etree.parse(path)
            root = tree.getroot()

            for sprite in root:
                if sprite.tag.lower() != 'sprite':
                    continue

                spritename = sprite.attrib['name']
                notes = None
                relatedObjFiles = None

                if 'notes' in sprite.attrib:
                    notes = '<b>Actor Notes:</b> [notes]'.replace('[notes]', str(sprite.attrib['notes']))

                if 'files' in sprite.attrib:
                    relatedObjFiles = '<b>This actor uses:</b><br>[list]'.replace('[list]', str(sprite.attrib['files'].replace(';', '<br>')))

                sdef = SpriteDefinition()
                sdef.name = spritename
                sdef.notes = notes
                sdef.relatedObjFiles = relatedObjFiles

                try:
                    sdef.loadFrom(sprite)
                except Exception as e:
                    if 'id' in sprite.attrib:
                        errors.append(sprite.attrib['id'])
                    elif 'string_id' in sprite.attrib:
                        errors.append(sprite.attrib['string_id'])
                    errortext.append(str(e))

                if 'id' in sprite.attrib:
                    try:
                        spriteid = int(sprite.attrib['id'])
                        sdef.id = spriteid
                        globals.Sprites[spriteid] = sdef
                    except ValueError:
                        continue
                
                elif 'string_id' in sprite.attrib:
                    sdef.string_id = sprite.attrib['string_id']
                    globals.CustomSpriteDefinitions[sdef.string_id] = sdef

        # Add TXT sprite names, if there are any
        # This code is only ever run when a custom
        # gamedef is loaded, because spritenames.txt
        # is a file only ever used by custom gamedefs.
        if (snpath is not None) and (snpath.path is not None):
            with open(snpath.path) as snfile:
                data = snfile.read()

            # Split the data
            data = data.split('\n')
            for i, line in enumerate(data):
                data[i] = line.split(':')

            # Apply it
            for spriteid, name in data:
                try:
                    globals.Sprites[int(spriteid)].name = name
                except Exception as e:
                    errors.append(spriteid)
                    errortext.append(str(e))

    # Re-sync every level-local numeric alias after globals.Sprites is rebuilt.
    # int_to_string is authoritative here because a loaded file can contain
    # duplicate string entries at distinct positional IDs.
    if hasattr(globals, 'Level') and globals.Level is not None:
        id_mgr = getattr(globals.Level, 'id_manager', None)
        if id_mgr is not None:
            for int_id, str_id in id_mgr.int_to_string.items():
                definition = globals.CustomSpriteDefinitions.get(str_id)
                if definition is None:
                    continue
                while len(globals.Sprites) <= int_id:
                    globals.Sprites.append(None)
                globals.Sprites[int_id] = definition

    # Warn the user if errors occurred
    if len(errors) > 0:
        QtWidgets.QMessageBox.warning(None, 'Warning',
                                      "The actor data file didn't load correctly. The following actors have incorrect and/or broken data in them, and may not be editable correctly in the editor: [sprites]".replace('[sprites]', str(', '.join(errors))),
                                      QtWidgets.QMessageBox.Ok)
        QtWidgets.QMessageBox.warning(None, 'Errors', repr(errortext))


def LoadSpriteCategories(reload_=False):
    """
    Ensures that the sprite category info is loaded
    """
    if (globals.SpriteCategories is not None) and not reload_: return

    paths = globals.gamedef.recursiveFiles('spritecategories')

    globals.SpriteCategories = []

    # Add a Search category
    globals.SpriteCategories.append(('All', [('All Actors', list(range(globals.NumSprites)))], []))
    globals.SpriteCategories[-1][1][0][1].append(9999)  # 'no results' special case

    for path in paths:
        tree = etree.parse(path)
        root = tree.getroot()

        CurrentView = None
        for view in root:
            if view.tag.lower() != 'view': continue

            viewname = view.attrib['name']

            # See if it's in there already
            CurrentView = []
            for potentialview in globals.SpriteCategories:
                if potentialview[0] == viewname: CurrentView = potentialview[1]
            if CurrentView == []: globals.SpriteCategories.append((viewname, CurrentView, []))

            CurrentCategory = None
            for category in view:
                if category.tag.lower() != 'category': continue

                catname = category.attrib['name']

                # See if it's in there already
                CurrentCategory = []
                for potentialcat in CurrentView:
                    if potentialcat[0] == catname: CurrentCategory = potentialcat[1]
                if CurrentCategory == []: CurrentView.append((catname, CurrentCategory))

                for attach in category:
                    if attach.tag.lower() != 'attach': continue

                    sprite = attach.attrib['sprite']
                    if '-' not in sprite:
                        if int(sprite) not in CurrentCategory:
                            CurrentCategory.append(int(sprite))
                    else:
                        x = sprite.split('-')
                        for i in range(int(x[0]), int(x[1]) + 1):
                            if i not in CurrentCategory:
                                CurrentCategory.append(i)

    # Add a Custom view for string-ID actors, if any exist
    if globals.CustomSpriteDefinitions:
        globals.SpriteCategories.append(('Custom', [('Custom Actors', [])], []))


def LoadSpriteListData(reload_=False):
    """
    Ensures that the sprite list modifier data is loaded
    """
    if (globals.SpriteListData is not None) and not reload_: return

    paths = globals.gamedef.recursiveFiles('spritelistdata')

    globals.SpriteListData = []
    for i in range(24): globals.SpriteListData.append([])
    for path in paths:
        f = open(path)
        data = f.read()
        f.close()

        split = data.replace('\n', '').split(';')
        for lineidx in range(24):
            line = split[lineidx]
            splitline = line.split(',')

            # Add them
            for item in splitline:
                try:
                    newitem = int(item)
                except ValueError:
                    continue
                if newitem in globals.SpriteListData[lineidx]: continue
                globals.SpriteListData[lineidx].append(newitem)
            globals.SpriteListData[lineidx].sort()


def LoadEntranceNames(reload_=False):
    """
    Ensures that the entrance names are loaded
    """
    if (globals.EntranceTypeNames is not None) and not reload_: return

    paths = globals.gamedef.recursiveFiles('entrancetypes')

    NameList = {}
    for path in paths:
        tree = etree.parse(path)
        root = tree.getroot()
        for entrance in root:
            if entrance.tag.lower() != 'entrance':
                continue
            NameList[int(entrance.attrib['id'])] = entrance.attrib['name']

    globals.EntranceTypeNames = []
    idx = 0
    while idx in NameList:
        globals.EntranceTypeNames.append('([id]) [name]'.replace('[id]', str(idx)).replace('[name]', str(NameList[idx])))
        idx += 1


def _OpenTilesetWiiU(name):
    """
    Wii U: the tileset archive was embedded in the level (or loaded from miyamotoextras).
    Returns (sarc, img, nml, colldata, loadAnimation, indexFormat), None if missing, or False on error.
    """
    # if this file's not found, return
    if name not in globals.szsData:
        print(f'[DEBUG _LoadTileset] FAIL: name={name!r} not found in szsData')
        return

    sarcdata = globals.szsData[name]
    sarc = SarcLib.SARC_Archive()
    sarc.load(sarcdata)

    # Decompress the textures
    try:
        comptiledata = sarc['BG_tex/%s.gtx' % name].data
        nmldata = sarc['BG_tex/%s_nml.gtx' % name].data
        colldata = sarc['BG_chk/d_bgchk_%s.bin' % name].data

    except KeyError:
        QtWidgets.QMessageBox.warning(
            None, 'Error',
            'Cannot find the required texture within the tileset file [file], so it will not be loaded. Keep in mind that the tileset file cannot be renamed without changing the names of the texture/object files within the archive as well!'.replace('[file]', str(name)),
        )

        return False

    # load in the textures
    img = loadGTX(comptiledata)
    nml = loadGTX(nmldata)

    def loadAnimation(texname, useAddrLib=False):
        try:
            return loadGTX(sarc['BG_tex/%s.gtx' % texname].data, useAddrLib)

        except Exception:
            return None

    return sarc, img, nml, colldata, loadAnimation, '>HBBH'


def _OpenTilesetDX(name):
    """
    Deluxe: tilesets are standalone Yaz0-compressed archives in the game's Unit folder,
    holding a BFRES with the tile textures as BNTX.
    Returns (sarc, img, nml, colldata, loadAnimation, indexFormat), or False on error.
    """
    path = globals.gamedef.FindTilesetFile(name)
    if path is None:
        QtWidgets.QMessageBox.warning(
            None, 'Missing tileset',
            'Cannot find the tileset "[file]" in the Unit folder next to your Deluxe Course folder, so it will not be loaded.\n\nCheck the game path under Preferences > Game Setup.'.replace('[file]', str(name)))
        return False

    try:
        with open(path, 'rb') as fileobj:
            sarcdata = fileobj.read()

        if sarcdata[:4] == b'Yaz0':
            sarcdata = yaz0.decompressFASTYZ(sarcdata)

        if not sarcdata or sarcdata[:4] != b'SARC':
            raise ValueError('not a SARC archive')

        sarc = SarcLib.SARC_Archive()
        sarc.load(sarcdata)

        bfresdata = sarc['output.bfres'].data
        colldata = sarc['BG_chk/d_bgchk_%s.bin' % name].data

        # load in the textures
        bntx = loadBNTXFromBFRES(bfresdata)
        img = loadTexFromBNTX(bntx, name)
        nml = loadTexFromBNTX(bntx, name + '_nml')

    except Exception as e:
        QtWidgets.QMessageBox.warning(
            None, 'Corrupted tileset',
            'The tileset file [file] could not be read, so it will not be loaded.\n\n[err]'.replace('[file]', str(name)).replace('[err]', str(e)))
        return False

    def loadAnimation(texname, useAddrLib=False):
        try:
            return loadTexFromBNTX(bntx, texname)

        except Exception:
            return None

    return sarc, img, nml, colldata, loadAnimation, '<HBBH'


def _LoadTileset(idx, name):
    """
    Load in a tileset into a specific slot
    """

    if globals.IsNSMBUDX:
        source = _OpenTilesetDX(name)
    else:
        source = _OpenTilesetWiiU(name)

    if not source:
        return source

    sarc, img, nml, colldata, loadAnimation, indexFormat = source

    # Divide it into individual tiles and
    # add collisions at the same time
    def getTileFromImage(tilemap, xtilenum, ytilenum):
        return tilemap.copy((xtilenum * 64) + 2, (ytilenum * 64) + 2, 60, 60)

    dest = QtGui.QPixmap.fromImage(img)
    dest2 = QtGui.QPixmap.fromImage(nml)
    sourcex = 0
    sourcey = 0
    tileoffset = idx * 256
    for i in range(tileoffset, tileoffset + 256):
        T = TilesetTile(getTileFromImage(dest, sourcex, sourcey), getTileFromImage(dest2, sourcex, sourcey))
        T.setCollisions(struct.unpack_from('<Q', colldata, (i - tileoffset) * 8)[0])
        globals.Tiles[i] = T
        sourcex += 1
        if sourcex >= 32:
            sourcex = 0
            sourcey += 1

    # Load the tileset animations, if there are any
    if idx == 0:
        hatena_anime = None
        block_anime = None
        tuka_coin_anime = None
        belt_conveyor_anime = None

        hatena_anime = loadAnimation('hatena_anime')
        block_anime = loadAnimation('block_anime')
        tuka_coin_anime = loadAnimation('tuka_coin_anime')
        belt_conveyor_anime = loadAnimation('belt_conveyor_anime', True)

        for i in range(256):
            if globals.Tiles[i].coreType == 7:
                if hatena_anime:
                    globals.Tiles[i].addAnimationData(hatena_anime)

            elif globals.Tiles[i].coreType == 6:
                if block_anime:
                    globals.Tiles[i].addAnimationData(block_anime)

            elif globals.Tiles[i].coreType == 2:
                if tuka_coin_anime:
                    globals.Tiles[i].addAnimationData(tuka_coin_anime)

            elif globals.Tiles[i].coreType == 17:
                if belt_conveyor_anime:
                    for x in range(2):
                        if i == 144 + x * 16:
                            globals.Tiles[i].addConveyorAnimationData(belt_conveyor_anime, 0, True)

                        elif i == 145 + x * 16:
                            globals.Tiles[i].addConveyorAnimationData(belt_conveyor_anime, 1, True)

                        elif i == 146 + x * 16:
                            globals.Tiles[i].addConveyorAnimationData(belt_conveyor_anime, 2, True)

                        elif i == 147 + x * 16:
                            globals.Tiles[i].addConveyorAnimationData(belt_conveyor_anime, 0)

                        elif i == 148 + x * 16:
                            globals.Tiles[i].addConveyorAnimationData(belt_conveyor_anime, 1)

                        elif i == 149 + x * 16:
                            globals.Tiles[i].addConveyorAnimationData(belt_conveyor_anime, 2)

        for tile in globals.Overrides:
            if tile.coreType == 7:
                if hatena_anime:
                    tile.addAnimationData(hatena_anime)

            elif tile.coreType == 6:
                if block_anime:
                    tile.addAnimationData(block_anime)

    # Load the object definitions
    defs = [None] * 256

    indexfile = sarc['BG_unt/%s_hd.bin' % name].data
    deffile = sarc['BG_unt/%s.bin' % name].data
    objcount = len(indexfile) // 6
    indexstruct = struct.Struct(indexFormat)

    for i in range(objcount):
        data = indexstruct.unpack_from(indexfile, i * 6)
        obj = ObjectDef()
        obj.width = data[1]
        obj.height = data[2]
        obj.randByte = data[3]
        obj.load(deffile, data[0])
        defs[i] = obj

    globals.ObjectDefinitions[idx] = defs
    obj_count = sum(1 for d in defs if d is not None)

    ProcessOverrides(name)


def LoadTileset(idx, name, reload=False):
    return _LoadTileset(idx, name)


def LoadOverrides():
    """
    Load overrides
    """
    path = globals.gamedef.file('overrides')
    OverrideBitmap = QtGui.QPixmap(path)
    idx = 0
    xcount = OverrideBitmap.width() // globals.TileWidth
    ycount = OverrideBitmap.height() // globals.TileWidth
    globals.Overrides = [None] * (xcount * ycount)
    sourcex = 0
    sourcey = 0

    for y in range(ycount):
        for x in range(xcount):
            bmp = OverrideBitmap.copy(sourcex, sourcey, globals.TileWidth, globals.TileWidth)
            globals.Overrides[idx] = TilesetTile(bmp)

            # Set collisions if it's a brick or question
            if (x < 11 or x == 14) and y == 2: globals.Overrides[idx].setQuestionCollisions()
            elif x < 12 and y == 1: globals.Overrides[idx].setBrickCollisions()

            idx += 1
            sourcex += globals.TileWidth
        sourcex = 0
        sourcey += globals.TileWidth
        if idx % 16 != 0:
            idx -= (idx % 16)
            idx += 16

    # ? Block for Sprite 59
    bmp = OverrideBitmap.copy(14 * globals.TileWidth, 2 * globals.TileWidth, globals.TileWidth, globals.TileWidth)
    globals.Overrides.append(TilesetTile(bmp))


def LoadLevelNamesForDef(gamedef):
    """
    Load levelnames independently for a single MiyamotoGameDefinition layer (no merging).
    Returns a category list as produced by LoadLevelNames_Category, or [] if none.
    """
    lnfile = gamedef.files.get('levelnames')
    if lnfile is None or lnfile.path is None:
        return []
    try:
        tree = etree.parse(lnfile.path)
        return LoadLevelNames_Category(tree.getroot())
    except Exception:
        return []


def ApplyGamePlatform(gamedef):
    """
    Switches the editor between the Wii U (big-endian, .szs/.sarc) and Switch
    "Deluxe" (little-endian, .sarc) level formats, based on the game definition.
    """
    isDX = bool(getattr(gamedef, 'isDX', False))
    globals.IsNSMBUDX = isDX
    globals.FileExtentions = globals.FileExtensions_NSMBUDX if isDX else globals.FileExtensions_NSMBU


def LoadGameDef(base_game=None, mods=None, dlg=None):
    """
    Loads a game + mods chain.
    base_game: folder name in miyamotodata/games/ (default 'NSMBU')
    mods: ordered list of mod folder names (applied on top of base game)
    """
    if mods is None:
        mods = []

    try:
        # Build the chain: base game first, mods stacked on top
        current_def = MiyamotoGameDefinition(base_game or 'NSMBU', source='game')

        for mod_name in mods:
            if mod_name in (None, 'None', ''):
                continue
            new_def = MiyamotoGameDefinition(mod_name, source='mod', base_instance=current_def)
            if getattr(new_def, 'error', None):
                continue
            current_def = new_def

        globals.gamedef = current_def
        ApplyGamePlatform(current_def)

        # Load BG names
        LoadBGNames()

        # Load spritedata.xml and spritecategories.xml
        LoadSpriteData()
        LoadSpriteListData(True)
        LoadSpriteCategories(True)
        if globals.mainWindow:
            globals.mainWindow.spriteViewPicker.clear()
            for cat in globals.SpriteCategories:
                globals.mainWindow.spriteViewPicker.addItem(cat[0])
            globals.mainWindow.sprPicker.LoadItems()  # Reloads the sprite picker list items
            globals.mainWindow.spriteViewPicker.setCurrentIndex(0)  # Sets the sprite picker to category 0 (enemies)
            globals.mainWindow.spriteDataEditor.setSprite(globals.mainWindow.spriteDataEditor.spritetype,
                                                  True)  # Reloads the sprite data editor fields
            globals.mainWindow.spriteDataEditor.update()

        # Reload tilesets
        LoadObjDescriptions(True)  # reloads tileset1 descriptions
        LoadTilesetNames(True)  # reloads tileset names

        # Load sprites.py
        SLib.SpritesFolders = globals.gamedef.recursiveFiles('sprites', False, True)

        SLib.ImageCache.clear()
        SLib.SpriteImagesLoaded.clear()
        SLib.loadVines()

        if globals.Area is not None:
            spriteClasses = globals.gamedef.getImageClasses()

            for s in globals.Area.sprites:
                if s.type in SLib.SpriteImagesLoaded: continue
                if s.type not in spriteClasses: continue

                spriteClasses[s.type].loadImages()

                SLib.SpriteImagesLoaded.add(s.type)

            for s in globals.Area.sprites:
                # Re-resolve both definition/name and image class against the
                # new patch stack without changing the level-local numeric ID.
                s.InitializeSprite()
                if s.type not in spriteClasses:
                    s.setImageObj(SLib.SpriteImage)

        # Load entrance names
        LoadEntranceNames(True)

    except Exception as e:
        raise
    #    # Something went wrong.
    #    QtWidgets.QMessageBox.information(None, 'Error', "An error occurred while attempting to load this game patch. It will now be unloaded. Here's the specific error:<br>[error]".replace('[error]', str(str(e))))
    #    if name is not None: LoadGameDef(None)
    #    return False


    # Success!
    if dlg:
        setSetting('LastBaseGame', base_game or 'NSMBU')
        setSetting('LastMods', list(mods))
    return True


def LoadActionsLists():
    # Define the menu items, their default settings and their globals.mainWindow.actions keys
    # These are used both in the Preferences Dialog and when init'ing the toolbar.
    globals.FileActions = (
        ('New Level', True, 'newlevel'),
        ('Open Level by Name...', True, 'openfromname'),
        ('Open Level by File...', False, 'openfromfile'),
        ('Recent Files', False, 'openrecent'),
        ('Save Level', True, 'save'),
        ('Export Level As...', False, 'saveas'),
        ('Level Information...', False, 'metainfo'),
        ('Level Screenshot...', True, 'screenshot'),
        ('Pyamoto Preferences...', False, 'preferences'),
        ('Exit Pyamoto', False, 'exit'),
    )
    globals.EditActions = (
        ('Undo', True, 'undo'),
        ('Redo', True, 'redo'),
        ('Select All', False, 'selectall'),
        ('Deselect', False, 'deselect'),
        ('Cut', True, 'cut'),
        ('Copy', True, 'copy'),
        ('Paste', True, 'paste'),
        ('Duplicate', True, 'duplicate'),
        ('Raise to Top', True, 'raise'),
        ('Lower to Bottom', True, 'lower'),
        ('Shift Items...', False, 'shiftitems'),
        ('Merge Locations', False, 'mergelocations'),
        ('Freeze\nObjects', False, 'freezeobjects'),
        ('Freeze\nActors', False, 'freezesprites'),
        ('Freeze Entrances', False, 'freezeentrances'),
        ('Freeze\nLocations', False, 'freezelocations'),
        ('Freeze Paths', False, 'freezepaths'),
    )
    globals.ViewActions = (
        ('Layer 0', True, 'showlay0'),
        ('Layer 1', True, 'showlay1'),
        ('Layer 2', True, 'showlay2'),
        ('Show Actors', True, 'showsprites'),
        ('Show Actor Images', False, 'showspriteimages'),
        ('Preview Pivotal Rotation', True, 'showrotation'),
        ('Show Locations', True, 'showlocations'),
        ('Show Paths', True, 'showpaths'),
        ('Switch\nGrid', True, 'grid'),
        ('Zoom to Maximum', True, 'zoommax'),
        ('Zoom In', True, 'zoomin'),
        ('Zoom 100%', True, 'zoomactual'),
        ('Zoom Out', True, 'zoomout'),
        ('Zoom to Minimum', True, 'zoommin'),
    )
    globals.SettingsActions = (
        ('Area\nSettings...', True, 'areaoptions'),
        ('Zone\nSettings...', True, 'zones'),
        ('Add New Area', True, 'addarea'),
        ('Import Area from Level...', False, 'importarea'),
        ('Delete Current Area...', True, 'deletearea'),
    )
    globals.SpritedataActions = (
        ('Reload Actor Data', False, 'reloaddata'),
        ('View Sprite Map', False, 'viewspritemap'),
    )
    globals.HelpActions = (
        ('About Pyamoto', False, 'infobox'),
        ('Wiki', False, 'wiki'),
        ('About PyQt...', False, 'aboutqt'),
    )
