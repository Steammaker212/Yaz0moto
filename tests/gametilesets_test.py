"""
Tests for the object palette's Game tab (yaz0moto/gametilesets.py): finding every tileset and
object pack, filing them by world and level, turning a tileset's objects into standalone
objects, reading object packs, and copying an object into the level's tilesets.

Run from anywhere:   python tests/gametilesets_test.py
"""
import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import json
import os
import struct
import sys
import tempfile
import types
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

try:
    import fastyz  # noqa: F401
except ImportError:
    sys.modules['fastyz'] = types.SimpleNamespace(compress=lambda d: b'Yaz0' + bytes(12) + d,
                                                  decompress=lambda d: d[16:])

from PyQt5 import QtGui, QtWidgets  # noqa: E402
app = QtWidgets.QApplication([])

import SarcLib  # noqa: E402
from yaz0moto import globals  # noqa: E402
from yaz0moto import gametilesets as gt  # noqa: E402
from yaz0moto import tileset  # noqa: E402
from yaz0moto.tileset import ObjectDef  # noqa: E402

results = []


def check(label, ok):
    results.append((label, bool(ok)))
    print(('  OK  ' if ok else 'FAIL  ') + label)


def touch(path, data=b''):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)


def labels(nodes):
    return [n.label for n in nodes]


def find(nodes, label):
    return next(n for n in nodes if n.label == label)


tmp = tempfile.mkdtemp(prefix='y0gt')

# ---------------------------------------------------------------- Deluxe: Unit folders
print('Finding and filing Deluxe tilesets')
game_unit = os.path.join(tmp, 'game', 'Unit')
mod_unit = os.path.join(tmp, 'mod', 'Unit')
for name in ('Pa0_jyotyu', 'Pa0_jyotyu_chika', 'Pa1_1-1_1', 'Pa1_1-1_2', 'Pa2_1-1_2', 'Pa1_1-2_1',
             'Pa1_40-1_1', 'Pa1_30-1_1', 'Pa1_BD7694AD00800DD4'):
    touch(os.path.join(game_unit, name + '.szs'))
touch(os.path.join(game_unit, 'readme.txt'))
touch(os.path.join(mod_unit, 'Pa1_1-1_1.szs'))
touch(os.path.join(mod_unit, 'Pa3_MyTiles.szs'))

units = gt.unit_sources([mod_unit, game_unit])
check('every .szs in the Unit folders is found (%d)' % len(units), len(units) == 10 and 'readme' not in str(units))
check("a mod's copy of a tileset wins", units['Pa1_1-1_1'].path.startswith(mod_unit)
      and 'mod' in units['Pa1_1-1_1'].tooltip)
check('slots come from the names', (units['Pa2_1-1_2'].slot, units['Pa0_jyotyu'].slot, units['Pa3_MyTiles'].slot) == (2, 0, 3))

names = [['W1: Acorn Plains', [['1-1: Waddlewing Warning!', '1-1'], ['1-3: Rolling Yoshi Hills', '1-3'],
                               ['Ambushes', [['Goomba Ambush', '1-32']]]]],
         ['Challenge Mode', [['Acorn Plains Speed Run [1-1]', '1-1']]]]
packdir = os.path.join(tmp, 'Objects')
for folder in ('1 - Acorn Plains - Main', '1 - Acorn Plains - Garden', 'Airship', 'Airship - Utilities', '8-Bit Luigi'):
    os.makedirs(os.path.join(packdir, folder))
packs = gt.pack_sources(packdir)
tree = gt.build_tree_dx(units, packs, names, {'Pa0_jyotyu': 'Overworld'}, courses={'1-1', '1-2', '40-1'})
print('   ', labels(tree))
check('categories: packs, shared, worlds from levelnames.xml, other levels, unused, custom',
      labels(tree) == ['Object packs', 'Shared (Pa0)', 'W1: Acorn Plains', 'Challenge Mode', 'Other levels',
                       'Unused tilesets', 'Custom tilesets'])
w1 = find(tree, 'W1: Acorn Plains')
check('a world lists only levels that have tilesets', labels(w1.children) == ['1-1: Waddlewing Warning!'])
check("a level lists its areas' tilesets in order",
      labels(w1.children[0].children) == ['Area 1: Pa1_1-1_1', 'Area 2: Pa1_1-1_2', 'Area 2: Pa2_1-1_2'])
check('a level named twice is listed in both places',
      find(tree, 'Challenge Mode').children[0].sources()[0] is units['Pa1_1-1_1'])
check('the shared tilesets use their names', labels(find(tree, 'Shared (Pa0)').children)
      == ['Overworld (Pa0_jyotyu)', 'Pa0_jyotyu_chika'])
other = find(tree, 'Other levels')
check('unnamed levels go under World <n>', labels(other.children) == ['World 1', 'World 40']
      and labels(other.children[0].children) == ['1-2'])
check('tilesets of levels the game lacks are "unused"', labels(find(tree, 'Unused tilesets').children) == ['World 30'])
check('other names are custom tilesets', labels(find(tree, 'Custom tilesets').children)
      == ['Pa1_BD7694AD00800DD4', 'Pa3_MyTiles'])
packnodes = find(tree, 'Object packs').children
check('object packs are grouped by name', labels(packnodes) == ['1 - Acorn Plains', '8-Bit Luigi', 'Airship']
      and labels(packnodes[0].children) == ['Garden', 'Main'] and labels(packnodes[2].children) == ['Airship', 'Utilities'])
listed = {s.key for n in tree for s in n.sources()}
check('every tileset and pack is listed somewhere', listed == {s.key for s in units.values()} | {s.key for s in packs})
check('without a course list nothing is called unused',
      'Unused tilesets' not in labels(gt.build_tree_dx(units, [], names, {})))
check('ids stay the same for a tileset', gt.source_id('unit:a') == gt.source_id('unit:a') != gt.source_id('unit:b'))

# ---------------------------------------------------------------- Wii U: level archives
print('Wii U level archives')
course = os.path.join(tmp, 'Course')
inner = SarcLib.SARC_Archive()
inner.addFile(SarcLib.File('dummy', b'1'))
inner_data = inner.save()[0]
level = SarcLib.SARC_Archive()
level.addFile(SarcLib.File('Pa1_nohara', inner_data))
level.addFile(SarcLib.File('Pa0_jyotyu', inner_data))
level.addFile(SarcLib.File('course1.bin', b'\0' * 16))
level.addFile(SarcLib.File('levelname', b'course1.bin'))
touch(os.path.join(course, '1-1.szs'), level.save()[0])
touch(os.path.join(course, '9-9.szs'), level.save()[0])
srcs = gt.level_sources(os.path.join(course, '1-1.szs'))
check('the tilesets inside a level are found', [(s.name, s.slot) for s in srcs] == [('Pa0_jyotyu', 0), ('Pa1_nohara', 1)])
wtree = gt.build_tree_wiiu([course], packs, names)
check('Wii U categories', labels(wtree) == ['Object packs', 'W1: Acorn Plains', 'Challenge Mode', 'Other levels'])
check('levels open later (their tilesets are read when expanded)', find(wtree, 'W1: Acorn Plains').children[0].level[1] == '1-1'
      and find(wtree, 'Other levels').children[0].label == '9-9')

# ---------------------------------------------------------------- objects of a tileset
print('Objects of a tileset')
sheet = QtGui.QImage(2048, 512, QtGui.QImage.Format_ARGB32)
for i in range(256):
    p = QtGui.QPainter(sheet)
    p.fillRect((i % 32) * 64, (i // 32) * 64, 64, 64, QtGui.QColor(i, 255 - i, 7))
    p.end()
colldata = b''.join(bytes([i]) * 8 for i in range(256))
tile = gt._tileset_tiles(sheet, sheet, colldata, 1)


def objdef(data, w, h, rand=0):
    o = ObjectDef()
    o.width, o.height, o.randByte = w, h, rand
    o.load(data, 0)
    return o


def colour(img, x, y):
    img = img.toImage() if isinstance(img, QtGui.QPixmap) else img
    return img.pixelColor(x, y).red()


# 2x2: tiles 5 6 / 7 5 of slot 1
square = objdef(bytes([0, 5, 1, 0, 6, 1, 0xFE, 0, 7, 1, 0, 5, 1, 0xFE, 0xFF]), 2, 2)
e = gt.object_entry(square, tile, 'square')
check('the image holds the object\'s tiles in order', (e.img.width(), e.img.height()) == (120, 120)
      and [colour(e.img, x, y) for x, y in ((5, 5), (65, 5), (5, 65), (65, 65))] == [5, 6, 7, 5])
check('the collisions follow the same order', e.colldata == bytes([5] * 8 + [6] * 8 + [7] * 8 + [5] * 8))
check('the definition is a copy', e.obj is not square and e.obj.rows == square.rows)

# random 1x1 over tiles 9, 10, 11
rnd = objdef(bytes([0, 9, 1, 0xFE, 0xFF]), 1, 1, 0x03)
e = gt.object_entry(rnd, tile)
check('a random object keeps all its tiles', e.img.width() == 180 and e.obj.randByte == 3
      and [colour(e.img, x, 5) for x in (5, 65, 125)] == [9, 10, 11] and e.colldata == bytes([9] * 8 + [10] * 8 + [11] * 8))
wide = objdef(bytes([0, 9, 1, 0, 9, 1, 0xFE, 0xFF]), 2, 1, 0x03)
check('only 1x1 objects are random', gt.object_entry(wide, tile).obj.randByte == 0)

# ---------------------------------------------------------------- object packs
print('Object packs')
pack = os.path.join(packdir, 'Airship')
img = QtGui.QPixmap(120, 60)
img.fill(QtGui.QColor(200, 10, 10))
for base, rand in (('obj_0', None), ('obj_1', 3), ('obj_10', None)):
    img.save(os.path.join(pack, base + '.png'))
    img.save(os.path.join(pack, base + '_nml.png'))
    touch(os.path.join(pack, base + '.colls'), b'\1' * 16)
    touch(os.path.join(pack, base + '.objlyt'), bytes([0, 0, 0, 0, 1, 0, 0xFE, 0xFF]))
    touch(os.path.join(pack, base + '.meta'), struct.pack('>HBBH', 0, 2, 1, 0x13))
    data = {k: base + ext for k, ext in (('img', '.png'), ('nml', '_nml.png'), ('colls', '.colls'),
                                          ('objlyt', '.objlyt'), ('meta', '.meta'))}
    if rand:
        data['randLen'] = rand
    with open(os.path.join(pack, base + '.json'), 'w') as f:
        json.dump(data, f)
with open(os.path.join(pack, 'broken.json'), 'w') as f:
    f.write('{"img": "missing.png"}')
entries = gt.pack_entries(pack)
check('a pack\'s objects load in name order, skipping broken ones',
      [e.label.split(', ')[1].split(' ')[0] for e in entries] == ['obj_0', 'obj_1', 'obj_10'])
check('their size and rows come from the files', (entries[0].obj.width, entries[0].obj.height) == (2, 1)
      and len(entries[0].obj.rows[0]) == 2 and entries[0].colldata == b'\1' * 16)
check('randomness only when the pack says so', [e.obj.randByte for e in entries] == [0, 0x13, 0])

src = gt.Source(gt.KIND_PACK, 'pack:test', 'Airship', pack)
loaded = gt.load_entries(src)
check('loading numbers the objects and tags their source', [e.obj.objAllIndex for e in loaded] == [0, 1, 2]
      and all(e.obj.folderIndex == gt.source_id('pack:test') for e in loaded))
check('loads are cached', gt.load_entries(src) is loaded)

# ---------------------------------------------------------------- copying into the level
print('Copying into the level')
globals.Tiles = [None] * 1024
existing = objdef(bytes([0, 0, 1, 0, 1, 1, 0xFE, 0, 2, 1, 0, 3, 1, 0xFE, 0xFF]), 2, 2)
globals.ObjectDefinitions = [None, [existing] + [None] * 255, None, None]
globals.Area = types.SimpleNamespace(tileset0='Pa0_jyotyu', tileset1='Pa1_1-1_1', tileset2='', tileset3='')
globals.CurrentArea = 1
globals.ObjectAddedtoEmbedded = {1: {}}
globals.mainWindow = types.SimpleNamespace()

e = gt.object_entry(square, tile)
e.obj.folderIndex, e.obj.objAllIndex = 7, 0
globals.ObjectAllDefinitions = [e.obj]
globals.ObjectAllCollisions = [e.colldata]
globals.ObjectAllImages = [[e.img, e.nml]]
before = [list(t) for t in e.obj.rows[0]]

with mock.patch.object(tileset, 'HandleTilesetEdited'):
    first = gt.copy_into_level(0)
    copy_ = globals.ObjectDefinitions[1][1]
    check('the object is copied into a free spot of slot 1', first == (1, 1) and copy_ is not None)
    check('its tiles go to free tiles of slot 1 (repeats share one)',
          [t[1] for row in copy_.rows for t in row] == [0x104, 0x105, 0x106, 0x104])
    check('the tiles get the graphics and collisions',
          colour(globals.Tiles[256 + 5].main, 5, 5) == 6 and globals.Tiles[256 + 6].coreType == 0x0707)
    check('the Game tab\'s object is left alone', [list(t) for t in e.obj.rows[0]] == before)
    check('painting it again reuses the copy', gt.copy_into_level(0) == (1, 1)
          and sum(1 for d in globals.ObjectDefinitions[1] if d is not None) == 2)

    globals.ObjectDefinitions[1][1] = existing  # the copy was replaced (e.g. tilesets changed)
    globals.ObjectDefinitions[1][2] = None
    again = gt.copy_into_level(0)
    check('a copy that is gone is made again', again == (1, 2) and globals.ObjectDefinitions[1][2] is not existing)

    # a full slot 1: the copy goes to slot 2, which gets a name
    full = ObjectDef()
    full.width, full.height = 16, 16
    full.rows = [[[0, (y * 16 + x) | 0x100, 0] for x in range(16)] for y in range(16)]
    globals.ObjectDefinitions[1] = [full] + [None] * 255
    globals.ObjectAddedtoEmbedded = {1: {}}
    check('when slot 1 is full it goes to slot 2', gt.copy_into_level(0) == (2, 0)
          and globals.Area.tileset2 == 'Pa2_MIYAMOTO_TEMP')

    def filled(slot):
        o = ObjectDef()
        o.width, o.height = 16, 16
        o.rows = [[[0, (y * 16 + x) | (slot << 8), 0] for x in range(16)] for y in range(16)]
        return [o] + [None] * 255

    globals.ObjectDefinitions = [None, filled(1), filled(2), filled(3)]
    globals.ObjectAddedtoEmbedded = {1: {}}
    check("an object that doesn't fit anywhere is refused", gt.copy_into_level(0) is None)

print()
failed = [label for label, ok in results if not ok]
print('%d checks, %d failed' % (len(results), len(failed)))
sys.stdout.flush()
os._exit(1 if failed else 0)
