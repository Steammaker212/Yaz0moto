#!/usr/bin/python
# -*- coding: utf-8 -*-

# Yaz0moto - a Mario level editor
# This file is part of Yaz0moto, licensed under the GNU General Public License v3.

"""
The object palette's Game tab: every tileset of the game (and every object pack in the Objects
folder), sorted into categories, with their objects ready to paint. Painting one copies it into
one of the level's own tilesets, as Miyamoto's "All" palette did.

Where the tilesets come from:
  Deluxe   every <name>.szs in the Unit folders next to the game's (and the mods') Course folders.
  Wii U    the tilesets inside each level archive (Course/<level>.szs), read when you open a level.
  Both     every folder of exported objects in the Objects folder (Preferences > Game Setup).

Nintendo names Deluxe tilesets Pa<slot>_<level>_<area> (Pa1_1-2_1 is the main tileset of level 1-2,
area 1), so they are filed under the level's name from levelnames.xml.
"""

import contextlib
import copy
import json
import os
import re
import struct
from collections import OrderedDict

from PyQt5 import QtGui
from PyQt5.QtCore import Qt

from . import globals

KIND_UNIT = 'unit'    # Deluxe: a tileset archive in a Unit folder
KIND_LEVEL = 'level'  # Wii U: a tileset inside a level archive
KIND_PACK = 'pack'    # a folder of exported objects

OBJECT_FILES = ('colls', 'meta', 'objlyt', 'img', 'nml')
UNIT_NAME = re.compile(r'^Pa([0-3])_(.+)_(\d+)$')
TILE = 60  # object images hold their tiles at this size, one after another

CACHE_SIZE = 8


class Source:
    """One tileset or object pack the Game tab lists."""

    def __init__(self, kind, key, label, path, name='', slot=1, tooltip=''):
        self.kind = kind
        self.key = key
        self.label = label
        self.path = path
        self.name = name or label
        self.slot = slot
        self.tooltip = tooltip or path

    def __repr__(self):
        return 'Source(%r)' % self.key


class Node:
    """A category (children) or a tileset (source) in the Game tab's list."""

    def __init__(self, label, children=None, source=None, level=None, tooltip=''):
        self.label = label
        self.children = children if children is not None else []
        self.source = source
        self.level = level  # Wii U: (path, name) of a level archive, listed when opened
        self.tooltip = tooltip

    def isCategory(self):
        return self.source is None

    def sources(self):
        """Every tileset in this category (not counting unopened Wii U levels)."""
        if self.source is not None:
            return [self.source]
        found = []
        for child in self.children:
            found.extend(child.sources())
        return found

    def __repr__(self):
        return 'Node(%r, %d children)' % (self.label, len(self.children))


def natural_key(text):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', text)]


# ---------------------------------------------------------------- ids for the tilesets

_ids = {}


def source_id(key):
    """
    A small number for a tileset, the same for the whole session. Objects copied from it into a
    level are remembered by (area, this number, object number), so painting the same object
    again reuses the copy.
    """
    if key not in _ids:
        _ids[key] = len(_ids)
    return _ids[key]


# ---------------------------------------------------------------- finding the tilesets

def objects_folder():
    from .misc import setting
    path = setting('ObjPath', '') or os.path.join(globals.user_data_path, 'Objects')
    return path if path and os.path.isdir(path) else ''


def pack_sources(top=None):
    """Every folder of exported objects in the Objects folder, in name order."""
    top = objects_folder() if top is None else top
    if not top:
        return []
    try:
        names = [n for n in os.listdir(top) if os.path.isdir(os.path.join(top, n))]
    except OSError:
        return []
    names.sort(key=natural_key)
    return [Source(KIND_PACK, 'pack:' + os.path.normpath(os.path.join(top, n)), n, os.path.join(top, n))
            for n in names]


def unit_sources(units=None):
    """
    Deluxe: every tileset archive in the Unit folders, {name: Source}. A mod's copy of a tileset
    wins over the game's, as when the game loads it.
    """
    if units is None:
        gamedef = getattr(globals, 'gamedef', None)
        units = gamedef.GetUnitPaths() if gamedef is not None and hasattr(gamedef, 'GetUnitPaths') else []
    found = {}
    for i, unit in enumerate(units):
        try:
            files = os.listdir(unit)
        except OSError:
            continue
        for f in files:
            if not f.lower().endswith('.szs'):
                continue
            name = f[:-4]
            if name in found:
                continue
            m = UNIT_NAME.match(name)
            slot = int(m.group(1)) if m else (int(name[2]) if re.match(r'^Pa[0-3]_', name) else 1)
            path = os.path.join(unit, f)
            tip = path if i == len(units) - 1 else path + '\n(from a mod)'
            found[name] = Source(KIND_UNIT, 'unit:' + name, name, path, name, slot, tip)
    return found


def level_names():
    """The level names tree from levelnames.xml: [[name, file or [children]], ...]."""
    if not getattr(globals, 'LevelNames', None):
        try:
            from .loading import LoadLevelNames
            LoadLevelNames()
        except Exception:
            globals.LevelNames = []
    return globals.LevelNames or []


def tileset_names():
    """Names for the shared (Pa0) tilesets from tilesets.xml, {filename: name}."""
    names = {}

    def walk(cat):
        for item in cat:
            if isinstance(item, tuple):
                names[item[0]] = item[1]
            elif len(item) > 1 and isinstance(item[1], list):
                walk(item[1])

    for slot in getattr(globals, 'TilesetNames', None) or ():
        if slot and isinstance(slot[0], list):
            walk(slot[0])
    return names


def _pack_nodes(packs):
    """Object packs grouped by name: "1 - Acorn Plains - Main" goes under "1 - Acorn Plains"."""
    groups = OrderedDict()
    for src in packs:
        group, _, rest = src.label.rpartition(' - ')
        groups.setdefault(group or src.label, []).append((rest if group else src.label, src))
    nodes = []
    for group, items in groups.items():
        if len(items) == 1:
            nodes.append(Node(items[0][1].label, source=items[0][1], tooltip=items[0][1].path))
        else:
            nodes.append(Node(group, [Node(label, source=src, tooltip=src.path) for label, src in items]))
    return nodes


def _unit_label(src):
    m = UNIT_NAME.match(src.name)
    if m:
        return 'Area %s: %s' % (m.group(3), src.name)
    return src.name


def build_tree_dx(units, packs, names, pa0_names, courses=None):
    """
    Deluxe: the Game tab's categories. units is {name: Source}, packs a list of Sources, names
    the level names tree, pa0_names {filename: name} and courses the levels the game has
    (None: unknown).
    """
    by_level = {}
    for name, src in units.items():
        m = UNIT_NAME.match(name)
        if m and m.group(1) != '0':
            by_level.setdefault(m.group(2), []).append(src)
    for lst in by_level.values():
        lst.sort(key=lambda s: (natural_key(UNIT_NAME.match(s.name).group(3)), s.slot))

    listed = set()

    def walk(cat):
        nodes = []
        for entry in cat:
            label, value = entry[0], entry[1]
            if isinstance(value, list):
                children = walk(value)
                if children:
                    nodes.append(Node(label, children))
            elif value in by_level:
                listed.add(value)
                nodes.append(Node(label, [Node(_unit_label(s), source=s, tooltip=s.tooltip)
                                          for s in by_level[value]], tooltip='Level ' + value))
        return nodes

    tree = []
    if packs:
        tree.append(Node('Object packs', _pack_nodes(packs), tooltip=os.path.dirname(packs[0].path)))

    shared = sorted((s for n, s in units.items() if re.match(r'^Pa0_', n)), key=lambda s: natural_key(s.name))
    if shared:
        tree.append(Node('Shared (Pa0)', [Node('%s (%s)' % (pa0_names[s.name], s.name) if s.name in pa0_names else s.name,
                                               source=s, tooltip=s.tooltip) for s in shared]))

    tree.extend(walk(names))

    def by_world(levels):
        """Levels without a name, under World <n> (the number before the dash)."""
        worlds = OrderedDict()
        for lvl in sorted(levels, key=natural_key):
            worlds.setdefault(lvl.split('-')[0], []).append(
                Node(lvl, [Node(_unit_label(s), source=s, tooltip=s.tooltip) for s in by_level[lvl]],
                     tooltip='Level ' + lvl))
        return [Node('World ' + w, lvls) for w, lvls in worlds.items()]

    others = [lvl for lvl in by_level if lvl not in listed]
    used = [lvl for lvl in others if courses is None or lvl in courses]
    unused = [lvl for lvl in others if courses is not None and lvl not in courses]
    if used:
        tree.append(Node('Other levels', by_world(used), tooltip='Levels that have no name in levelnames.xml'))
    if unused:
        tree.append(Node('Unused tilesets', by_world(unused),
                         tooltip='Tilesets in the Unit folder for levels the game no longer has'))

    custom = sorted((s for n, s in units.items() if not UNIT_NAME.match(n) and not re.match(r'^Pa0_', n)),
                    key=lambda s: natural_key(s.name))
    if custom:
        tree.append(Node('Custom tilesets', [Node(s.name, source=s, tooltip=s.tooltip) for s in custom]))
    return tree


def course_folders():
    """Wii U: the game's and mods' Course folders, most specific first."""
    gamedef = getattr(globals, 'gamedef', None)
    paths = gamedef.GetGamePaths() if gamedef is not None else []
    return [p for p in reversed(paths) if p and os.path.isdir(p)]


def find_level(file, folders):
    for folder in folders:
        path = os.path.join(folder, file + '.szs')
        if os.path.isfile(path):
            return path
    return None


def build_tree_wiiu(folders, packs, names):
    """
    Wii U: the Game tab's categories. Each level lists the tilesets inside its archive when
    it's opened (Node.level), since reading every level up front would take a while.
    """
    listed = set()

    def walk(cat):
        nodes = []
        for entry in cat:
            label, value = entry[0], entry[1]
            if isinstance(value, list):
                children = walk(value)
                if children:
                    nodes.append(Node(label, children))
            else:
                path = find_level(value, folders)
                if path:
                    listed.add(os.path.normcase(path))
                    nodes.append(Node(label, level=(path, value), tooltip=path))
        return nodes

    tree = []
    if packs:
        tree.append(Node('Object packs', _pack_nodes(packs), tooltip=os.path.dirname(packs[0].path)))
    tree.extend(walk(names))

    others = []
    seen = set()
    for folder in folders:
        try:
            files = sorted(os.listdir(folder), key=natural_key)
        except OSError:
            continue
        for f in files:
            path = os.path.join(folder, f)
            if f.lower().endswith('.szs') and os.path.normcase(path) not in listed and f.lower() not in seen:
                seen.add(f.lower())
                others.append(Node(f[:-4], level=(path, f[:-4]), tooltip=path))
    if others:
        tree.append(Node('Other levels', others))
    return tree


def build_tree():
    """The Game tab's categories for the current game."""
    packs = pack_sources()
    if globals.IsNSMBUDX:
        courses = set()
        for folder in course_folders():
            try:
                courses.update(os.path.splitext(f)[0] for f in os.listdir(folder))
            except OSError:
                pass
        return build_tree_dx(unit_sources(), packs, level_names(), tileset_names(), courses or None)
    return build_tree_wiiu(course_folders(), packs, level_names())


def _read_archive(path):
    """The SARC archive in a file (Yaz0-compressed or not)."""
    import SarcLib
    from . import yaz0
    with open(path, 'rb') as f:
        data = f.read()
    if data[:4] == b'Yaz0':
        data = yaz0.decompressFASTYZ(data)
    if not data or data[:4] != b'SARC':
        raise ValueError('%s is not a SARC archive' % os.path.basename(path))
    arc = SarcLib.SARC_Archive()
    arc.load(data)
    return arc


def _arc_files(arc):
    """{name: bytes} of the files in an archive, folders included."""
    import SarcLib
    files = {}

    def walk(folder, prefix):
        for item in folder.contents:
            if isinstance(item, SarcLib.File):
                files[prefix + item.name] = item.data
            else:
                walk(item, prefix + item.name + '/')

    walk(arc, '')
    return files


def level_sources(path, level=''):
    """Wii U: the tilesets inside a level archive, as Sources (Pa0 first)."""
    found = []
    for name, data in sorted(_arc_files(_read_archive(path)).items(), key=lambda kv: natural_key(kv[0])):
        if data[:4] != b'SARC' or not re.match(r'^Pa[0-3]_', name):
            continue
        found.append(Source(KIND_LEVEL, 'level:%s:%s' % (os.path.normcase(path), name), name, path, name,
                            int(name[2]), '%s\nin %s' % (name, path)))
    return found


# ---------------------------------------------------------------- reading a tileset's objects

class Entry:
    """One object of a tileset, as the palette shows it and as it's copied into a level."""

    def __init__(self, obj, colldata, img, nml, label):
        self.obj = obj            # ObjectDef; its tiles count from 0 in img (row by row)
        self.colldata = colldata  # 8 bytes of collision per tile, in the same order
        self.img = img            # QPixmap of the object's tiles, TILE pixels each
        self.nml = nml
        self.label = label


def is_random(obj):
    return (obj.width, obj.height) == (1, 1) and len(obj.rows) == 1 and bool(obj.randByte & 0xF)


def _tile_rows(obj):
    """(row index in the image, row) for each row of an object, as Yaz0moto lays out exported objects."""
    for crow, row in enumerate(obj.rows):
        if obj.reversed and obj.subPartAt != -1:
            crow = crow - obj.subPartAt if crow >= obj.subPartAt else crow + obj.height - obj.subPartAt
        yield crow, row


def object_entry(obj, tile, label=''):
    """
    An object of a tileset as a standalone Entry (what Export object writes): its own image,
    normal map and collisions, made from tile(n) -> (main pixmap, normal pixmap, 8 collision
    bytes) for the tileset's tile n (with its slot in bits 8-9).
    """
    obj = copy.deepcopy(obj)
    rand = is_random(obj)
    randLen = obj.randByte & 0xF if rand else 0
    if not rand:
        obj.randByte = 0

    w = randLen if rand else obj.width
    img = QtGui.QPixmap(max(w, 1) * TILE, max(obj.height, 1) * TILE)
    nml = QtGui.QPixmap(img.size())
    img.fill(Qt.transparent)
    nml.fill(QtGui.QColor(128, 128, 255))
    p = QtGui.QPainter(img)
    pn = QtGui.QPainter(nml)

    if obj.reversed:
        colls = bytearray(obj.width * obj.height * 8)
    else:
        colls = bytearray()

    def put(x, crow, n):
        main, normal, coll = tile(n)
        if main is not None:
            p.drawPixmap(x * TILE, crow * TILE, main)
        if normal is not None:
            pn.drawPixmap(x * TILE, crow * TILE, normal)
        return coll

    for crow, row in _tile_rows(obj):
        x = 0
        for t in row:
            if len(t) != 3:
                continue
            n = t[1] & 0x3FF
            if rand:
                for z in range(randLen):
                    colls += put(z, 0, n + z)
                break
            coll = put(x, crow, n) if t != [0, 0, 0] else tile(n)[2]
            if obj.reversed:
                pos = (crow * obj.width + x) * 8
                colls[pos:pos + 8] = coll
            else:
                colls += coll
            x += 1

    p.end()
    pn.end()
    return Entry(obj, bytes(colls), img, nml, label)


def _tileset_tiles(img, nml, colldata, slot):
    """tile(n) for a tileset whose textures are img/nml (QImages) and collisions colldata."""
    main = QtGui.QPixmap.fromImage(img)
    normal = QtGui.QPixmap.fromImage(nml) if nml is not None else None
    cache = {}

    def tile(n):
        if n in cache:
            return cache[n]
        s, i = (n >> 8) & 3, n & 0xFF
        if s != slot and s == 0 and globals.Tiles is not None and globals.Tiles[i] is not None:
            # A tile of the level's shared tileset
            t = globals.Tiles[i]
            m = t.main if isinstance(t.main, QtGui.QPixmap) else QtGui.QPixmap.fromImage(t.main)
            result = (m, t.nml, struct.pack('<Q', t.getCollision()))
        else:
            x, y = (i % 32) * 64 + 2, (i // 32) * 64 + 2
            result = (main.copy(x, y, TILE, TILE), normal.copy(x, y, TILE, TILE) if normal is not None else None,
                      bytes(colldata[i * 8:i * 8 + 8]).ljust(8, b'\0'))
        cache[n] = result
        return result

    return tile


def _inner_name(files, name):
    """The name the tileset's files are stored under inside its archive (normally its own name)."""
    if 'BG_unt/%s_hd.bin' % name in files:
        return name
    for f in files:
        if f.startswith('BG_unt/') and f.endswith('_hd.bin'):
            return f[7:-7]
    raise KeyError('no objects (BG_unt/%s_hd.bin) in %s' % (name, name))


def tileset_entries(files, name, slot, isDX):
    """The objects of a tileset archive ({file name: bytes}) as Entries."""
    from .tileset import ObjectDef, loadBNTXFromBFRES, loadTexFromBNTX, loadGTX

    inner = _inner_name(files, name)
    colldata = files.get('BG_chk/d_bgchk_%s.bin' % inner, b'')
    if 'output.bfres' in files:  # Deluxe; a few of its archives are still in the Wii U format (GTX)
        bntx = loadBNTXFromBFRES(files['output.bfres'])
        img = loadTexFromBNTX(bntx, inner)
        try:
            nml = loadTexFromBNTX(bntx, inner + '_nml')
        except Exception:
            nml = None
        fmt = '<HBBH'
    else:
        img = loadGTX(files['BG_tex/%s.gtx' % inner])
        nml = loadGTX(files['BG_tex/%s_nml.gtx' % inner]) if 'BG_tex/%s_nml.gtx' % inner in files else None
        fmt = '>HBBH'

    tile = _tileset_tiles(img, nml, colldata, slot)
    indexfile = files['BG_unt/%s_hd.bin' % inner]
    deffile = files['BG_unt/%s.bin' % inner]
    index = struct.Struct(fmt)
    entries = []
    for i in range(min(len(indexfile) // 6, 256)):
        offset, w, h, rand = index.unpack_from(indexfile, i * 6)
        obj = ObjectDef()
        obj.width, obj.height, obj.randByte = w, h, rand
        try:
            obj.load(deffile, offset)
        except Exception:
            continue
        if not obj.rows or not any(len(t) == 3 for row in obj.rows for t in row):
            continue
        entries.append(object_entry(obj, tile, '%s, object %d (%d×%d)' % (name, i, w, h)))
    return entries


def pack_entries(path):
    """The objects in a folder of exported objects as Entries."""
    from .tileset import ObjectDef
    try:
        files = sorted((f for f in os.listdir(path) if f.lower().endswith('.json')), key=natural_key)
    except OSError:
        return []
    entries = []
    folder = os.path.basename(os.path.normpath(path))
    for f in files:
        try:
            with open(os.path.join(path, f)) as inf:
                data = json.load(inf)
            if not isinstance(data, dict) or not all(k in data for k in OBJECT_FILES):
                continue
            with open(os.path.join(path, data['colls']), 'rb') as inf:
                colls = inf.read()
            with open(os.path.join(path, data['meta']), 'rb') as inf:
                meta = inf.read()
            with open(os.path.join(path, data['objlyt']), 'rb') as inf:
                deffile = inf.read()
            img = QtGui.QPixmap(os.path.join(path, data['img']))
            nml = QtGui.QPixmap(os.path.join(path, data['nml']))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if img.isNull():
            continue
        _, w, h, rand = struct.unpack_from('>HBBH', meta, 0)
        obj = ObjectDef()
        obj.width, obj.height = w, h
        obj.randByte = rand if 'randLen' in data else 0
        try:
            obj.load(deffile, 0)
        except Exception:
            continue
        if not obj.rows:
            continue
        entries.append(Entry(obj, colls, img, nml, '%s, %s (%d×%d)' % (folder, os.path.splitext(f)[0], w, h)))
    return entries


_cache = OrderedDict()


def load_entries(src):
    """The objects of a tileset or object pack (cached), as Entries numbered 0, 1, ..."""
    if src.key in _cache:
        _cache.move_to_end(src.key)
        return _cache[src.key]

    if src.kind == KIND_PACK:
        entries = pack_entries(src.path)
    elif src.kind == KIND_UNIT:
        entries = tileset_entries(_arc_files(_read_archive(src.path)), src.name, src.slot, True)
    else:
        import SarcLib
        files = _arc_files(_read_archive(src.path))
        arc = SarcLib.SARC_Archive()
        arc.load(files[src.name])
        entries = tileset_entries(_arc_files(arc), src.name, src.slot, False)

    folder = source_id(src.key)
    for i, e in enumerate(entries):
        e.obj.folderIndex = folder
        e.obj.objAllIndex = i

    _cache[src.key] = entries
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return entries


def clear_cache():
    _cache.clear()
    _missing.clear()
    _pixmaps.clear()


def entry_pixmap(entry, w, h, fullslope=True):
    """An object of a tileset drawn at w x h tiles (TILE pixels each), from its own image."""
    from .tileset import RenderObjectAll
    key = (id(entry), w, h, fullslope)
    pm = _pixmaps.get(key)
    if pm is not None:
        return pm
    def_ = entry.obj
    spots = {}  # where each of the object's tiles is in its image
    for crow, row in _tile_rows(def_):
        x = 0
        for tile in row:
            if len(tile) == 3:
                if tile != [0, 0, 0]:
                    spots.setdefault(tile[1] & 0x3FF, (x, crow))
                x += 1
    pm = QtGui.QPixmap(max(w, 1) * TILE, max(h, 1) * TILE)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    for y, row in enumerate(RenderObjectAll(def_, w, h, fullslope)):
        for x, tile in enumerate(row):
            if tile in spots:
                sx, sy = spots[tile]
                p.drawPixmap(x * TILE, y * TILE, entry.img, sx * TILE, sy * TILE, TILE, TILE)
    p.end()
    if len(_pixmaps) > 512:
        _pixmaps.clear()
    _pixmaps[key] = pm
    return pm


_pixmaps = {}


# ---------------------------------------------------------------- copying into the level

_copies = {}


@contextlib.contextmanager
def batched_edits():
    """
    Copies made inside refresh the palette and tile counts once, at the end, instead of once
    per object (each copy calls HandleTilesetEdited).
    """
    from . import tileset as ts
    original = ts.HandleTilesetEdited
    if getattr(original, 'batched', False):
        yield
        return
    calls = []

    def later(soft=False):
        calls.append(soft)

    later.batched = True
    ts.HandleTilesetEdited = later
    try:
        yield
    finally:
        ts.HandleTilesetEdited = original
        if calls:
            original(all(calls))


def existing_copy(src):
    """(slot, object number) of the copy of a game object (an ObjectDef from load_entries) in this area, or None."""
    area = globals.CurrentArea
    added = (globals.ObjectAddedtoEmbedded or {}).get(area, {}).get(src.folderIndex, {})
    index = src.objAllIndex
    if index not in added:
        return None
    slot, num = added[index]
    defs = globals.ObjectDefinitions[slot] if 0 <= slot < 4 else None
    if defs is not None and 0 <= num < len(defs) and defs[num] is not None \
            and defs[num] is _copies.get((area, src.folderIndex, index)):
        return slot, num
    del added[index]
    return None


def copy_object(src, colldata, img, nml):
    """
    Copies a game object (an ObjectDef from load_entries, with its source's folderIndex and
    objAllIndex) into one of the level's tilesets, or finds the copy made before in this area.
    Returns (slot, object number), or None if it doesn't fit.
    """
    from . import tileset

    found = existing_copy(src)
    if found is not None:
        return found
    area = globals.CurrentArea
    if globals.ObjectAddedtoEmbedded is None:
        globals.ObjectAddedtoEmbedded = {}
    added = globals.ObjectAddedtoEmbedded.setdefault(area, {}).setdefault(src.folderIndex, {})
    slot, num = tileset.addObjToTileset(copy.deepcopy(src), colldata, img, nml, True)
    if slot == 10:
        return None
    added[src.objAllIndex] = (slot, num)
    _copies[(area, src.folderIndex, src.objAllIndex)] = globals.ObjectDefinitions[slot][num]
    return slot, num


def copy_into_level(index):
    """
    Copies object `index` of the Game tab's tileset into one of the level's tilesets (or finds
    the copy made earlier), returning (slot, object number), or None if it doesn't fit.
    """
    src = globals.ObjectAllDefinitions[index]
    img, nml = globals.ObjectAllImages[index]
    found = copy_object(src, globals.ObjectAllCollisions[index], img, nml)

    # Adding it refreshed the palette, which forgets the pick: keep the object picked
    picker = getattr(globals.mainWindow, 'objPicker', None)
    if found is not None and picker is not None and picker.model() is picker.mall and 0 <= index < picker.mall.rowCount():
        picker.setCurrentIndex(picker.mall.index(index, 0))
    return found


# ---------------------------------------------------------------- game objects in Quick Paint presets

def is_ref(value):
    """Whether a preset part is a game object, ['game', tileset key, object number]."""
    return isinstance(value, (list, tuple)) and len(value) == 3 and value[0] == 'game'


def key_for_id(folder):
    for key, value in _ids.items():
        if value == folder:
            return key
    return None


def ref_for(index):
    """A reference to object `index` of the tileset the Game tab shows, or None."""
    defs = globals.ObjectAllDefinitions or []
    if not 0 <= index < len(defs):
        return None
    key = key_for_id(defs[index].folderIndex)
    return ['game', key, defs[index].objAllIndex] if key else None


def ref_label(ref):
    """'Pa1_6-1_1, object 12' for a reference."""
    key = ref[1]
    if key.startswith('level:'):
        name = key.rpartition(':')[2]
    else:
        name = os.path.basename(key.split(':', 1)[1]) if key.startswith('pack:') else key.split(':', 1)[1]
    return '%s, object %d' % (name, ref[2])


def source_for_key(key):
    """The Source a tileset key (Source.key) stands for, if it can still be found."""
    if key.startswith('unit:'):
        name = key[5:]
        gamedef = getattr(globals, 'gamedef', None)
        path = gamedef.FindTilesetFile(name) if gamedef is not None and hasattr(gamedef, 'FindTilesetFile') else None
        if not path:
            return None
        m = re.match(r'^Pa([0-3])_', name)
        return Source(KIND_UNIT, key, name, path, name, int(m.group(1)) if m else 1)
    if key.startswith('pack:'):
        path = key[5:]
        return Source(KIND_PACK, key, os.path.basename(path), path) if os.path.isdir(path) else None
    if key.startswith('level:'):
        path, _, name = key[6:].rpartition(':')
        if not os.path.isfile(path):
            return None
        return Source(KIND_LEVEL, key, name, path, name, int(name[2]) if re.match(r'^Pa[0-3]_', name) else 1)
    return None


_missing = set()  # tileset keys that couldn't be read (not tried again on every repaint)


def entries_for_key(key):
    """The objects of a tileset by its key (cached), or None."""
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    if key in _missing:
        return None
    src = source_for_key(key)
    try:
        return load_entries(src) if src is not None else None
    except Exception as e:
        print('Quick Paint: could not read %s: %s' % (key, e))
        _missing.add(key)
        return None
    finally:
        if src is None:
            _missing.add(key)


def entry_for(ref):
    """The Entry a reference points at, or None."""
    entries = entries_for_key(ref[1])
    if not entries or not 0 <= ref[2] < len(entries):
        return None
    return entries[ref[2]]


def level_copy(ref, create=True):
    """
    (slot, object number) of the copy of a referenced game object in this area's tilesets,
    copying it there now if create and it isn't yet; None if it can't be found or doesn't fit.
    """
    e = entry_for(ref)
    if e is None:
        return None
    if not create:
        return existing_copy(e.obj)
    return copy_object(e.obj, e.colldata, e.img, e.nml)


# ---------------------------------------------------------------- the Game tab

from PyQt5 import QtWidgets  # noqa: E402

ROLE_NODE = Qt.UserRole + 1


class GameTab(QtWidgets.QWidget):
    """
    The palette's Game tab: a searchable list of every tileset, by category, above the objects
    of the one picked (the shared object picker moves into pickerHost while this tab shows).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.signature = None
        self.current = None  # the Source shown
        self.loading = False

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText('Search tilesets (world, level, Pa1_1-2_1...)')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.applyFilter)

        refresh = QtWidgets.QToolButton()
        refresh.setText('↻')
        refresh.setAutoRaise(True)
        refresh.setToolTip('Look for tilesets again (after adding mods or object packs)')
        refresh.clicked.connect(lambda: self.populate(force=True))

        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.search, 1)
        top.addWidget(refresh)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumHeight(140)
        self.tree.setToolTip('Every tileset of the game, by world and level, and your object packs.\n'
                             'Pick one to see its objects below.')
        self.tree.currentItemChanged.connect(self.itemChanged)
        self.tree.itemExpanded.connect(self.itemExpanded)

        self.pickerHost = QtWidgets.QWidget()

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)

        upper = QtWidgets.QWidget()
        ul = QtWidgets.QVBoxLayout(upper)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.setSpacing(2)
        ul.addLayout(top)
        ul.addWidget(self.tree, 1)

        self.splitter = QtWidgets.QSplitter(Qt.Vertical)
        self.splitter.addWidget(upper)
        self.splitter.addWidget(self.pickerHost)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setChildrenCollapsible(False)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        layout.addWidget(self.splitter, 1)
        layout.addWidget(self.status)

    # ------------------------------------------------------------ listing

    @staticmethod
    def currentSignature():
        if globals.IsNSMBUDX:
            gamedef = getattr(globals, 'gamedef', None)
            where = tuple(gamedef.GetUnitPaths()) if gamedef is not None and hasattr(gamedef, 'GetUnitPaths') else ()
        else:
            where = tuple(course_folders())
        return bool(globals.IsNSMBUDX), where, objects_folder(), id(getattr(globals, 'gamedef', None))

    def activate(self):
        """The tab is showing: list the tilesets (again, if the game or folders changed)."""
        self.populate()
        if self.current is not None:
            self.showSource(self.current)

    def populate(self, force=False):
        sig = self.currentSignature()
        if sig == self.signature and not force:
            return
        self.signature = sig
        if force:
            clear_cache()

        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            tree = build_tree()
        except Exception as e:
            tree = []
            print('Game tab: could not list the tilesets:', e)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self.tree.blockSignals(True)
        self.tree.clear()
        for node in tree:
            self.tree.addTopLevelItem(self.makeItem(node))
        self.tree.blockSignals(False)

        count = sum(len(n.sources()) for n in tree)
        if not tree:
            if globals.IsNSMBUDX:
                self.status.setText("No tilesets found. Set the game's Course folder in Preferences > Game Setup "
                                    "(the tilesets are read from the Unit folder next to it).")
            else:
                self.status.setText('No levels or object packs found. Set the game path and the Objects folder '
                                    'in Preferences > Game Setup.')
        elif count:
            self.status.setText("%d tilesets. Pick one, click an object, then click the level to paint it: it's "
                                "copied into the level's tilesets." % count)
        else:
            self.status.setText("Open a level in the list to see its tilesets.")

        self.applyFilter(self.search.text())
        from .misc import setting
        last = self.current.key if self.current is not None else setting('GameTabTileset', '')
        self.current = None
        if last:
            self.select(last)

    def makeItem(self, node):
        item = QtWidgets.QTreeWidgetItem([node.label])
        item.setData(0, ROLE_NODE, node)
        if node.tooltip:
            item.setToolTip(0, node.tooltip)
        if node.isCategory():
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            if node.level is None:
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
            for child in node.children:
                item.addChild(self.makeItem(child))
            if node.level is not None and not node.children:
                item.setChildIndicatorPolicy(QtWidgets.QTreeWidgetItem.ShowIndicator)
        return item

    def itemExpanded(self, item):
        """Wii U: list a level's tilesets the first time it's opened."""
        node = item.data(0, ROLE_NODE)
        if node is None or node.level is None or node.children:
            return
        path, name = node.level
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            sources = level_sources(path, name)
        except Exception as e:
            sources = []
            self.status.setText('Could not read %s: %s' % (os.path.basename(path), e))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        node.children = [Node(s.name, source=s, tooltip=s.tooltip) for s in sources]
        for child in node.children:
            item.addChild(self.makeItem(child))
        if not sources:
            item.setChildIndicatorPolicy(QtWidgets.QTreeWidgetItem.DontShowIndicatorWhenChildless)

    def applyFilter(self, text):
        words = text.lower().split()

        def visit(item, inherited):
            node = item.data(0, ROLE_NODE)
            hay = inherited + ' ' + item.text(0).lower()
            if node is not None and node.source is not None:
                hay += ' ' + node.source.name.lower()
            if item.childCount() == 0:
                shown = all(w in hay for w in words)
            else:
                shown = False
                for i in range(item.childCount()):
                    shown = visit(item.child(i), hay) or shown
            item.setHidden(not shown)
            if words and item.childCount():
                item.setExpanded(shown)
            return shown

        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i), '')
        if not words:
            self.tree.collapseAll()
            cur = self.tree.currentItem()
            if cur is not None:
                self.tree.scrollToItem(cur)
        self.tree.blockSignals(False)

    def items(self):
        it = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while it.value():
            yield it.value()
            it += 1

    def select(self, key):
        """Shows the tileset with this key, if it's listed."""
        for item in self.items():
            node = item.data(0, ROLE_NODE)
            if node is not None and node.source is not None and node.source.key == key:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return True
        return False

    # ------------------------------------------------------------ showing a tileset's objects

    def itemChanged(self, item, previous=None):
        node = item.data(0, ROLE_NODE) if item is not None else None
        if node is None or node.source is None:
            return
        from .misc import setSetting
        setSetting('GameTabTileset', node.source.key)
        self.showSource(node.source)

    def showSource(self, src):
        mw = globals.mainWindow
        picker = getattr(mw, 'objPicker', None)
        if picker is None or self.loading:
            return
        self.loading = True
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            entries = load_entries(src)
            error = None
        except Exception as e:
            entries, error = [], e
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.loading = False

        shown = globals.ObjectAllDefinitions or []
        if (len(shown) != len(entries) or picker.mall.rowCount() != len(entries)
                or any(a is not b.obj for a, b in zip(shown, entries))):
            picker.mall.LoadFromEntries(entries)
        self.current = src

        if mw.objAllTab.currentWidget() is self:
            if picker.model() is not picker.mall:
                picker.setModel(picker.mall)
            picker.clearSelection()
            globals.CurrentPaintType = 10
            globals.CurrentObject = -1

        if error is not None:
            self.status.setText('Could not read %s: %s' % (src.label, error))
        elif not entries:
            self.status.setText('%s has no objects.' % src.label)
        else:
            self.status.setText("%s: %d objects. Click one, then click the level to paint it; it's copied into the "
                                "level's tilesets (Local tab)." % (src.label, len(entries)))
