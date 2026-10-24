"""
Tests for the level checker, the mod package export, the undo history jump and the
updater's tag parsing. Builds synthetic course files in both byte orders; no game
files are needed.

Run from anywhere:   python tests/studio_tools_test.py
"""
import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import json
import os
import struct
import sys
import tempfile
import types
import zipfile

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PyQt5 import QtWidgets
app = QtWidgets.QApplication([])

from miyamoto import globals
from miyamoto import levelcheck, modexport, updater
from miyamoto.undomanager import Command, UndoManager

results = []


def check(label, ok, detail=''):
    results.append((label, bool(ok)))
    print(('PASS ' if ok else 'FAIL ') + label + ((' -- ' + str(detail)) if (detail and not ok) else ''))


# ---------------------------------------------------------------- synthetic course files

def course(endian, sprites=(), entrances=(), zones=(), locations=(), paths=(), start=0):
    """A course file with the given records (block layout as in area.py)."""
    blocks = [b''] * 15
    blocks[0] = b'\0' * 128
    blocks[1] = struct.pack(endian + 'IIHHxBBBBxxBHH', 0, 0, 0, 300, 0, 0, 0, start, 0, 0, 0)
    blocks[6] = b''.join(struct.pack(endian + 'HHhhBBBBBBxBHBBBBBx', x, y, 0, 0, eid, darea, dent, etype,
                                     0, 0, 0, settings, 0, 0, 0, 0, 0)
                         for eid, x, y, darea, dent, etype, settings in entrances)
    blocks[7] = b''.join(struct.pack(endian + 'HHHHIIBB2sBxxx', t, x, y,
                                     int.from_bytes(d[0:2], 'big'), int.from_bytes(d[2:6], 'big'),
                                     int.from_bytes(d[6:10], 'big'), 0, 0, d[10:12], 0)
                         for t, x, y, d in sprites)
    blocks[9] = b''.join(struct.pack(endian + 'HHHHHHBBBBBBBBBBBBBBxx', x, y, w, h, 0, 0, zid, 0,
                                     0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
                         for zid, x, y, w, h in zones)
    blocks[10] = b''.join(struct.pack(endian + 'HHHHBxxx', x, y, w, h, lid) for lid, x, y, w, h in locations)
    node_count = 0
    pathblock = b''
    for pid, nodes in paths:
        pathblock += struct.pack(endian + 'BbHHHxxxx', pid, 0, node_count, nodes, 0)
        node_count += nodes
    blocks[13] = pathblock
    blocks[14] = struct.pack(endian + 'HHffhHBBBx', 0, 0, 0, 0, 0, 0, 0, 0, 0) * node_count

    head = b''
    body = b''
    offset = 15 * 8
    for block in blocks:
        head += struct.pack(endian + 'II', offset if block else 0, len(block))
        body += block
        offset += len(block)
    return head + body


def layer(endian, rects):
    return b''.join(struct.pack(endian + 'HhhHHBxxxxx', 0, x, y, w, h, 0) for x, y, w, h in rects) + b'\xff\xff'


def data(**nybbles):
    """12 bytes of sprite data with single nybbles set: data(n3=1)."""
    raw = bytearray(12)
    for key, value in nybbles.items():
        n = int(key[1:]) - 1
        raw[n // 2] |= value << (4 if n % 2 == 0 else 0)
    return bytes(raw)


# A path ID field on nybble 3-4 for sprite 100, like spritedata.xml would give
FIELDS = {100: [(2, 'Path ID', (9, 17), 256, None, 'path', None, None)],
          101: [(2, 'Movement ID', (9, 17), 256, None, 'movement', None, None)]}

with open(levelcheck.default_rules_path(), encoding='utf-8') as f:
    RULES = json.load(f)
RULES['checks']['location_unused']['enabled'] = True

for endian in ('<', '>'):
    order = 'little' if endian == '<' else 'big'
    zone = (0, 0, 0, 16 * 50, 16 * 20)
    area1 = course(endian, start=5,
                   sprites=[(45, 32, 32, data(n10=0)), (45, 48, 32, data(n10=0)),     # two "Star Coin 1"
                            (0, 16 * 10, 16 * 2, bytes(12)),                          # goomba over a pit
                            (0, 16 * 30, 16 * 2, bytes(12)),                          # goomba with ground
                            (100, 64, 64, data(n3=0, n4=7)),                          # path 7 does not exist
                            (101, 64, 80, data(n3=0, n4=3)),                          # movement 3 used once
                            (19, 16 * 80, 16 * 2, bytes(12)),                         # outside the zone
                            (25, 96, 96, bytes(12)), (25, 112, 96, bytes(12))],       # two checkpoints
                   entrances=[(0, 16, 16, 0, 0, 0, 0),                                # start entrance 0
                              (1, 32, 16, 2, 9, 3, 0),                                # pipe to area 2 entrance 9
                              (1, 48, 16, 0, 0, 0, 0)],                               # duplicate ID 1
                   zones=[zone, (1, 16 * 40, 0, 16 * 20, 16 * 20)],                   # overlapping zones
                   locations=[(4, 0, 0, 16, 16)],
                   paths=[(2, 1)])
    area2 = course(endian, entrances=[(0, 16, 16, 0, 0, 0, 0)], zones=[(0, 0, 0, 16 * 30, 16 * 20)])

    snaps = [levelcheck.parse_area(1, area1, (None, layer(endian, [(0, 18, 4, 2), (60, 5, 3, 1), (25, 5, 10, 2)]), None), endian == '<'),
             levelcheck.parse_area(2, area2, (None, None, None), endian == '<')]

    check('%s: sprites, entrances and zones parse' % order,
          len(snaps[0].sprites) == 9 and len(snaps[0].entrances) == 3 and len(snaps[0].zones) == 2
          and snaps[0].startEntrance == 5 and snaps[0].objcount == 3
          and snaps[0].objects[2] == levelcheck.Rect(25, 5, 10, 2))
    check('%s: sprite data survives the round trip' % order, snaps[0].sprites[4].data == data(n3=0, n4=7))

    findings = levelcheck.check_level(snaps, RULES, fields_for=lambda t: FIELDS.get(t, ()),
                                      sprite_name=lambda t: 'Sprite')
    rules_hit = {f.rule for f in findings}
    expected = {'start_entrance_missing', 'duplicate_entrance_id', 'warp_destination_missing',
                'sprite_outside_zone', 'zone_overlap', 'star_coin_count', 'star_coin_duplicate_number',
                'checkpoint_count', 'id_reference_missing', 'id_used_once', 'path_too_short',
                'enemy_over_pit', 'location_unused', 'no_goal'}
    check('%s: every planted problem is found' % order, expected <= rules_hit, expected - rules_hit)

    pits = [f for f in findings if f.rule == 'enemy_over_pit']
    check('%s: only the goomba over the pit is flagged' % order,
          len(pits) == 1 and pits[0].target == ('sprite', 2), pits)
    check('%s: errors are listed first' % order, findings[0].severity == 'error')

    clean = levelcheck.check_level([snaps[1]], RULES, fields_for=lambda t: (), sprite_name=lambda t: 'Sprite')
    check('%s: a plain area only gets the "no goal" note' % order,
          [f.rule for f in clean] == ['no_goal'], clean)

    m = levelcheck.compute_metrics(snaps, RULES, enemy_ids={0, 19}, coin_ids=set())
    check('%s: metrics' % order, m['Enemies'] == 3 and m['Star Coins'] == 2 and m['Zone width (tiles)'] == 100
          and m['Checkpoints'] == 2 and m['Enemies per 100 tiles'] == 3.0, m)

disabled = json.loads(json.dumps(RULES))
disabled['checks']['enemy_over_pit']['enabled'] = False
findings = levelcheck.check_level(snaps, disabled, fields_for=lambda t: (), sprite_name=lambda t: 'Sprite')
check('a disabled check does not run', not any(f.rule == 'enemy_over_pit' for f in findings))

check('percentile', levelcheck.percentile(5, [1, 2, 3, 10]) == 75 and levelcheck.percentile(1, []) is None)

# user rules file overrides the bundled one key by key
tmp = tempfile.mkdtemp()
globals.user_data_path = tmp
with open(os.path.join(tmp, levelcheck.RULES_FILE), 'w') as f:
    json.dump({'checks': {'zone_overlap': {'severity': 'error'}}}, f)
rules, error = levelcheck.load_rules()
check('user rules are merged over the defaults',
      error is None and rules['checks']['zone_overlap']['severity'] == 'error'
      and rules['checks']['duplicate_sprite']['severity'] == 'warning')
with open(os.path.join(tmp, levelcheck.RULES_FILE), 'w') as f:
    f.write('{broken')
rules, error = levelcheck.load_rules()
check('a broken user rules file falls back to the defaults', error and 'checks' in rules)


# ---------------------------------------------------------------- mod package

game = os.path.join(tmp, 'mod')
base = os.path.join(tmp, 'base')
for folder in ('Course', 'Unit'):
    os.makedirs(os.path.join(game, folder))
    os.makedirs(os.path.join(base, folder))
level_path = os.path.join(game, 'Course', '1-1.sarc')
open(level_path, 'wb').write(b'SARC level')
units = [os.path.join(game, 'Unit'), os.path.join(base, 'Unit')]
tiles = {
    'Pa0_jyotyu': (b'same', b'same'),                # unchanged original
    'Pa1_nohara': (b'edited', b'original'),          # changed in the mod
    'Pa2_0123456789ABCDEF': (b'made here', None),    # saved by Yaz0moto
}
for name, (mod, orig) in tiles.items():
    open(os.path.join(units[0], name + '.szs'), 'wb').write(mod)
    if orig is not None:
        open(os.path.join(units[1], name + '.szs'), 'wb').write(orig)
find = lambda n: os.path.join(units[0], n + '.szs') if os.path.isfile(os.path.join(units[0], n + '.szs')) else None

files, missing = modexport.plan_files(level_path, True, sorted(tiles) + ['Pa3_missing'], find, units)
names = [a for a, _ in files]
check('only changed tilesets go into the package',
      names == ['romfs/Course/1-1.sarc', 'romfs/Unit/Pa1_nohara.szs', 'romfs/Unit/Pa2_0123456789ABCDEF.szs'], names)
check('missing tilesets are reported', missing == ['Pa3_missing'])
files_all, _ = modexport.plan_files(level_path, True, sorted(tiles), find, units, all_tilesets=True)
check('"all tilesets" includes the unchanged one', len(files_all) == 4)
wiiu, _ = modexport.plan_files(os.path.join(game, 'Course', '1-1.szs'), False)
check('Wii U levels go into course_res_pack', wiiu[0][0] == 'content/Common/course_res_pack/1-1.szs')

out = os.path.join(tmp, 'pkg.zip')
manifest = modexport.write_package(out, files, 'New Super Mario Bros. U Deluxe', '1-1.sarc')
with zipfile.ZipFile(out) as zf:
    stored = json.loads(zf.read(modexport.MANIFEST_NAME))
    check('package contents and manifest agree',
          sorted(zf.namelist()) == sorted(names + [modexport.MANIFEST_NAME])
          and stored['files'] == manifest['files'] and zf.read('romfs/Course/1-1.sarc') == b'SARC level')
check('no temporary file is left behind', not os.path.exists(out + '.tmp'))


# ---------------------------------------------------------------- undo history jump

class Step(Command):
    def __init__(self, log, n):
        super().__init__('step %d' % n)
        self.log, self.n = log, n

    def redo(self):
        self.log.append(self.n)

    def undo(self):
        self.log.remove(self.n)


globals.mainWindow = None
um = globals.UndoManager = UndoManager()
log = []
for n in range(5):
    um.push(Step(log, n))
um.jump_to(2)
check('jumping back undoes the later steps', log == [0, 1] and len(um.redo_stack) == 3)
um.jump_to(4)
check('jumping forward redoes them', log == [0, 1, 2, 3] and len(um.redo_stack) == 1)
um.jump_to(99)
check('jumping past the end stops at the last step', log == [0, 1, 2, 3, 4])


# ---------------------------------------------------------------- updater tags

tags = {'v1.2.3': '1.2.3', 'V2.0.0': '2.0.0', 'release-1.4.0': '1.4.0', 'Yaz0moto-v3.1': '3.1',
        ' v1.0.0 ': '1.0.0', 'nightly-20260101-abcdef1': 'nightly-20260101-abcdef1'}
check('release tags are reduced to their version',
      all(updater.version_from_tag(t) == v for t, v in tags.items()),
      {t: updater.version_from_tag(t) for t in tags})
release = updater._release_from_json({'tag_name': 'release-9.0.0', 'assets': []}, updater.CHANNEL_RELEASE)
check('a "release-" tag is seen as a newer version', release.version == '9.0.0' and updater._is_newer(release))



# ---------------------------------------------------------------- movement preview

import math as _math
from xml.etree import ElementTree as _etree
from PyQt5 import QtCore
from miyamoto import movementpreview as MP
from miyamoto.misc import SpriteDefinition

# The real sprite definitions, so the settings the preview reads are the ones in spritedata.xml
_defs = {}
for _elem in _etree.parse('miyamotodata/games/NSMBU/spritedata.xml').getroot():
    if _elem.tag == 'sprite' and int(_elem.attrib['id']) in (47, 48, 68, 69, 70, 100, 116, 118, 214, 238, 239, 297):
        _d = SpriteDefinition()
        _d.loadFrom(_elem)
        _defs[int(_elem.attrib['id'])] = _d
MP._fields = lambda t: _defs[t].fields if t in _defs else ()


def _titles(t):
    out = set()
    for f in _defs[t].fields:
        out.update((f[1], f[2]) if f[0] == 5 else (f[1],))
    return out


READS = {  # every setting the preview reads, by sprite
    70: ['Direction', 'Distance', 'Speed', 'Begin Delay', 'Return Delay', 'Add return delay to begin delay',
         'Slower Acceleration', 'Do nothing', 'Movement ID'],
    100: ['Path ID', 'Starting node', 'When the last node is reached', 'Loop starting node', 'Move strictly',
          'Smooth movement', 'Sine effect type', 'Initial sine angle', 'Sine effect strength', 'Sine effect speed',
          'Event activated', 'Movement ID'],
    214: ['Controller Spin Arc', 'Speed', 'Delay', 'Clockwise', 'Movement ID'],
    238: ['Distance', 'Return Delay', 'Bolt ID'],
    47: ['Direction', 'Distance Multiplier', 'Bolt ID'],
    239: ['Direction', 'Speed', 'Bolt ID'],
}
missing = {t: [n for n in names if n not in _titles(t)] for t, names in READS.items()}
check('every setting the preview reads exists in spritedata.xml', not any(missing.values()), missing)


def _put(data, bits, value):
    if isinstance(bits, int):
        bits = (bits, bits + 1)
    width = bits[1] - bits[0]
    for i in range(width):
        n = bits[0] - 1 + i
        bit = (value >> (width - 1 - i)) & 1
        data[n >> 3] = (data[n >> 3] & ~(0x80 >> (n & 7))) | (bit << (7 - (n & 7)))


def spr(t, x=0, y=0, raw=None, **values):
    """A sprite of type t with settings given by their spritedata.xml titles (spaces as _)."""
    data = bytearray(raw or bytes(12))
    for key, value in values.items():
        title = key.replace('_', ' ')
        f = next(f for f in _defs[t].fields if f[1] == title or (f[0] == 5 and title in (f[1], f[2])))
        if f[0] == 0:
            _put(data, f[2], f[3] if value else 0)
        elif f[0] == 5:
            _put(data, f[3], value)
        else:
            _put(data, f[2], value)
    return types.SimpleNamespace(type=t, objx=x, objy=y, spritedata=bytes(data))


zone = lambda i, x, w: types.SimpleNamespace(id=i, ZoneRect=QtCore.QRectF(x, 0, w, 1000))
area = types.SimpleNamespace(sprites=[], pathdata=[], zones=[zone(0, 0, 1000), zone(1, 2000, 1000)])

# Grouping: same Movement ID and same zone; ID 0 counts, like the editor's rotation preview
ctrl = spr(70, 100, 100, Movement_ID=0, Direction=1, Distance=4, Speed=2)
coin = spr(48, 120, 100, Movement_ID=0)
far = spr(48, 2100, 100, Movement_ID=0)
area.sprites = [ctrl, coin, far]
c, moved, message = MP.find_group(area, coin)
check('Movement ID 0 links, and only within the same zone', c is ctrl and moved == [coin], message)
check('a sprite in another zone finds no controller', MP.find_group(area, far)[0] is None)

# Two-way: the listed speed is the top speed, it goes the distance and comes back
m = MP.TwoWayMotion(ctrl, area)
positions = [m.at(f)[0] for f in range(0, 400)]
steps = [abs(b - a) for a, b in zip(positions, positions[1:])]
check('two-way goes 4 tiles left at up to 1.0 per frame and returns',
      abs(min(positions) + 64) < 0.1 and max(steps) <= 1.0001 and positions[-1] > -64, (min(positions), max(steps)))
still = MP.TwoWayMotion(spr(70, Movement_ID=0, Distance=4, Do_nothing=1), area)
check('"Do nothing" keeps it still', still.at(50)[:2] == (0, 0) and still.notes)

# Paths: strictly straight, or curly through the same nodes
area.pathdata = [{'id': 3, 'loops': False, 'nodes': [
    {'x': 0, 'y': 0, 'speed': 2.0, 'delay': 0}, {'x': 64, 'y': 0, 'speed': 1.0, 'delay': 10},
    {'x': 64, 'y': 64, 'speed': 1.0, 'delay': 0}]}]
strict = MP.PathMotion(spr(100, Path_ID=3, Move_strictly=1), area)
curly = MP.PathMotion(spr(100, Path_ID=3), area)
near = lambda a, b: abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6
check('strict paths move in straight lines between nodes',
      near(strict.at(16), (32, 0)) and near(strict.at(40), (64, 0)) and near(strict.at(74), (64, 32)),
      [strict.at(f) for f in (16, 40, 74)])
route = [curly.at(f)[:2] for f in range(0, 160)]
check('curly paths still reach every node, but bend between them',
      any(near(p, (64, 0)) for p in route) and any(near(p, (64, 64)) for p in route)
      and any(abs(y) > 0.5 for x, y in route if 32 < x < 63.9))
sine = MP.PathMotion(spr(100, Path_ID=3, Move_strictly=1, Sine_effect_strength=2, Sine_effect_speed=8), area)
check('the sine effect wobbles vertically by its strength', 0 < max(abs(sine.at(f)[1]) for f in range(0, 30)) <= 8.0001)

# Rotation: the same formulas as the editor's own pivotal rotation preview
sway = spr(68, raw=bytes([0, 0, 0x03, 0, 0x02, 0, 0, 0x45, 0, 0, 0, 0]))
m = MP.SwayMotion(sway, area)
expected = lambda f: -45 + _math.cos(_math.radians(0x3 * 22.5 + 90 - f * (5 / 0x800) * 360)) * (4 * 22.5) * 0.5
check('swaying matches the editor formula', all(abs(m.at(f)[2] - expected(f)) < 1e-9 for f in (0, 17, 300)))
spin = spr(69, raw=bytes([0, 0, 0x20, 0x01, 0, 0, 0, 0x03, 0, 0, 0, 0]))  # start 45 deg, mode 1, speed index 3
m = MP.SpinMotion(spin, area)
check('spinning matches the game speed table',
      abs(m.at(60)[2] - (-45 - 60 * 0x1000000 / 0x100000000 * 360)) < 1e-9 and m.continuous)

# Path-controlled pivot: rotates and its pivot rides the linked path controller
pivot = spr(118, raw=bytes([0, 0, 0, 0x01, 0, 0, 0, 0x03, 0, 0, 0x09, 0x0B]))
mover = spr(100, Path_ID=3, Move_strictly=1, Movement_ID=0x0B)
area.sprites = [pivot, mover]
m = MP.PathPivot(pivot, area)
check('path-controlled pivots rotate while following their path', near(m.at(16), (32, 0)) and m.at(16)[2] != 0)

# Bolt: each object uses its own direction and distance multiplier
bolt = spr(238, Distance=2, Bolt_ID=4)
down = spr(47, Direction=3, Distance_Multiplier=2, Bolt_ID=4)
right = spr(239, Direction=0, Speed=2, Bolt_ID=4)
m = MP.BoltMotion(bolt, area)
check('bolt objects move their own way and distance',
      near(m.at(64, down), (0, 64)) and near(m.at(16, right), (32, 0)), (m.at(64, down), m.at(16, right)))
area.sprites = [spr(297, Movement_ID=1), spr(48, Movement_ID=1)]
check('undocumented controllers say why they cannot be previewed',
      'Mushroom' in (MP.find_group(area, area.sprites[1])[2] or ''))

failed = [label for label, ok in results if not ok]
print('\n%d/%d passed' % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
