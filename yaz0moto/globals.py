#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Pyamoto Level Editor
# Copyright (C) 2009-2026 Pyamoto contributors
# This file is part of Pyamoto.

# See LICENSE.txt for more information.


################################################################
################################################################

import json, os, platform, sys

def _load_project_info():
    if getattr(sys, 'frozen', False):
        # cx_Freeze stores packages under lib/<pkg>/ inside the frozen app.
        # include_files land at lib/'s parent (3 dirname levels up from __file__):
        #   build_exe Win/Linux: distrib/miyamoto_v1.0/lib/yaz0moto/ -> distrib/miyamoto_v1.0/
        #   bdist_mac:           Contents/Resources/lib/yaz0moto/    -> Contents/Resources/
        # Fallbacks cover alternative bundle layouts just in case.
        _mod = os.path.realpath(__file__)
        candidates = [
            os.path.dirname(os.path.dirname(os.path.dirname(_mod))),          # lib/ parent (primary)
            os.path.dirname(sys.executable),                                   # Contents/MacOS/
            os.path.normpath(os.path.join(os.path.dirname(sys.executable),    # Contents/Resources/
                                          '..', 'Resources')),
        ]
        for base in candidates:
            _proj = os.path.join(base, 'project.json')
            if os.path.isfile(_proj):
                with open(_proj, 'r', encoding='utf-8') as _f:
                    return json.load(_f)
        tried = '\n'.join(f'  {os.path.join(b, "project.json")}' for b in candidates)
        raise FileNotFoundError(f'project.json not found in frozen app. Tried:\n{tried}')
    else:
        # Development: project root is two levels up from yaz0moto/globals.py
        base = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        with open(os.path.join(base, 'project.json'), 'r', encoding='utf-8') as _f:
            return json.load(_f)

_project = _load_project_info()
MiyamotoID = _project['id']
MiyamotoVersion = _project['version']
MiyamotoReleaseType = _project.get('release_type', 'release')

app = None
mainWindow = None
settingsArea = None
LevelScene = None
LevelOverview = None
UndoManager = None
settings = None
gamedef = None
theme = None
compressed = False
LevelNames = None
TilesetNames = None
ObjDesc = None
SpriteCategories = None
SpriteListData = None
EntranceTypeNames = None
Tiles = None  # 0x200 tiles per tileset, plus 64 for each type of override
TilesetAnimTimer = None
Overrides = None  # 320 tiles, this is put into Tiles usually
TileBehaviours = None
ObjectDefinitions = None  # 4 tilesets
ObjectAllDefinitions = None
ObjectAllCollisions = None
ObjectAllImages = None
ObjectAddedtoEmbedded = None
TilesetsAnimating = False
Area = None
Dirty = False
DirtyOverride = 0
AutoSaveDirty = False
OverrideSnapping = False
PlaceObjectFullSize = False
LegacyMouseControls = False  # the level view's original controls: right click places
CurrentPaintType = -1
CurrentObject = -1
CurrentSprite = -1
CurrentLayer = 1
CurrentArea = 1
Layer0Shown = True
Layer1Shown = True
Layer2Shown = True
SpritesShown = True
SpriteImagesShown = True
RealViewEnabled = False
LiveBackgroundEnabled = False
LiveBackgroundAnimated = True
LocationsShown = True
CommentsShown = True
PathsShown = True
ObjectsFrozen = False
SpritesFrozen = False
EntrancesFrozen = False
LocationsFrozen = False
PathsFrozen = False
CommentsFrozen = False
OverwriteSprite = False
CategorizedSpriteData = False

SPRITE_PREVIEW_DISABLED = 0
SPRITE_PREVIEW_SMALL = 24
SPRITE_PREVIEW_MEDIUM = 40
SPRITE_PREVIEW_LARGE = 56
SpriteListPreviewSize = SPRITE_PREVIEW_DISABLED
SpriteListPreviewHighDetail = False
PaintingEntrance = None
PaintingEntranceListIndex = None
NumberFont = None
GridType = None
RestoredFromAutoSave = False
AutoSavePath = ''
AutoSaveData = b''
AutoOpenScriptEnabled = False
ExceptionRaised = False
CurrentLevelNameForAutoOpenScript = 'AAAAAAAAAAAAAAAAAAAAAAAAAA'
TileWidth = 60
szsData = {}
UseRGBA8 = False
NumSprites = 0
TilesetEdited = False
IsNSMBUDX = False
UseOuterSarcFormat = False
ModifyInnerName = False

# user_data_path must be resolved before miyamoto_path so it can be included
# in the yaz0data search candidates (downloaded data lives here).
def _user_data_parent():
    if platform.system() == 'Darwin':
        return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    elif platform.system() == 'Windows':
        return os.environ.get('APPDATA', os.path.expanduser('~'))
    else:
        return os.environ.get('XDG_CONFIG_HOME', os.path.join(os.path.expanduser('~'), '.config'))


def _user_data_path():
    new = os.path.join(_user_data_parent(), 'Yaz0moto')
    old = os.path.join(_user_data_parent(), 'Pyamoto')

    # Yaz0moto began as a fork of Pyamoto: on first launch, carry the existing settings,
    # mods and downloaded data over. This is a copy, so Pyamoto keeps working untouched.
    if not os.path.exists(new) and os.path.isdir(old):
        import shutil
        try:
            shutil.copytree(old, new)
            print('[Yaz0moto] Copied your Pyamoto settings and data from %s' % old)
        except (OSError, shutil.Error) as e:
            # A half-finished copy would be mistaken for a complete one next time
            shutil.rmtree(new, ignore_errors=True)
            print('[Yaz0moto] Could not copy Pyamoto data (%s); starting fresh.' % e)

    return new

user_data_path = _user_data_path()

if getattr(sys, 'frozen', False):
    _mod = os.path.realpath(__file__)
    _frozen_candidates = [
        os.path.dirname(os.path.dirname(os.path.dirname(_mod))),                    # lib/ parent
        os.path.dirname(sys.executable),                                             # Contents/MacOS/
        os.path.normpath(os.path.join(os.path.dirname(sys.executable), '..', 'Resources')),  # Contents/Resources/
    ]
    miyamoto_path = next(
        (c.replace("\\", "/") for c in _frozen_candidates
         if os.path.isdir(os.path.join(c, 'yaz0data'))),
        os.path.dirname(sys.executable).replace("\\", "/")
    )
    del _mod, _frozen_candidates
else:
    miyamoto_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__))).replace("\\", "/")

# actor_data_path: the downloadable actor data folder (separate from yaz0data).
# Prefers the user's downloaded copy; falls back to a bundled copy at the repo root.
_actor_data_candidates = [
    os.path.join(user_data_path, 'data'),
    os.path.join(miyamoto_path, 'data'),
]
actor_data_path = next(
    (c.replace("\\", "/") for c in _actor_data_candidates if os.path.isdir(c)),
    os.path.join(user_data_path, 'data').replace("\\", "/")
)
del _actor_data_candidates

cython_available = False
err_msg = ''
names_bg = []
# Game enums
FileExtensions_NSMBU = ('.szs', '.sarc')
FileExtensions_NSMBUDX = ('.sarc',)
FileExtentions = FileExtensions_NSMBU  # switched by loading.ApplyGamePlatform()
Pa0Tilesets = ('Pa0_jyotyu', 'Pa0_jyotyu_chika',
               'Pa0_jyotyu_yougan', 'Pa0_jyotyu_yougan2')
