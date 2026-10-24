#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Yaz0moto Level Editor
# This file is part of Yaz0moto, a fork of Pyamoto.

# See LICENSE.txt for more information.

"""
Level checker: design warnings and level metrics.

Nothing here blocks saving or changes the level. The checks read a snapshot of every
area (the open area from the editor items, the other areas from their raw course
data), so the same code also measures the original courses for comparison.

The rules live in yaz0data/levelcheck_rules.json. A copy in the user data folder
overrides it key by key, so users can turn checks off, change their severity or
extend the sprite lists without editing the bundled file.
"""

import json
import os
import struct
from collections import Counter, namedtuple

from . import globals
from .bytes import to_bytes
from .misc import extract_field_value

RULES_FILE = 'levelcheck_rules.json'

SEVERITIES = ('error', 'warning', 'info')

Sprite = namedtuple('Sprite', 'type x y data layer')
Entrance = namedtuple('Entrance', 'id x y destarea destentrance type settings')
Zone = namedtuple('Zone', 'id x y width height')
Location = namedtuple('Location', 'id x y width height')
Path = namedtuple('Path', 'id nodes loops')
Rect = namedtuple('Rect', 'x y width height')

# One area of a level, in plain data. Sprite, entrance, zone and location positions
# are in level units (16 per tile); object rectangles (layer 1) are in tiles.
AreaSnapshot = namedtuple('AreaSnapshot',
                          'num sprites entrances zones locations paths objects objcount startEntrance')

# target is (kind, index into that list of the area) or None
Finding = namedtuple('Finding', 'severity rule area message target')

NABBIT_PATH_ID = 90
OPTIONS_FORMAT = 'IIHHxBBBBxxBHH'


################################################################
# Snapshots
################################################################

def _blocks(course, endian):
    head = struct.Struct(endian + 'II')
    blocks = []
    for i in range(15):
        offset, size = head.unpack_from(course, i * 8)
        blocks.append(course[offset:offset + size] if size else b'')
    return blocks


def _records(data, fmt, size=None):
    st = struct.Struct(fmt)
    size = size or st.size
    return [st.unpack_from(data, i * size) for i in range(len(data) // size)]


def parse_area(num, course, layers, little_endian):
    """
    Snapshot of an area from its raw course file and its three layer files
    (any of which may be None).
    """
    endian = '<' if little_endian else '>'
    blocks = _blocks(course, endian)

    start = 0
    if len(blocks[1]) >= struct.calcsize(endian + OPTIONS_FORMAT):
        start = struct.unpack_from(endian + OPTIONS_FORMAT, blocks[1])[7]

    sprites = []
    for d in _records(blocks[7], endian + 'HHHHIIBB2sBxxx'):
        data = to_bytes(d[3], 2) + to_bytes(d[4], 4) + to_bytes(d[5], 4) + d[8]
        sprites.append(Sprite(d[0], d[1], d[2], data, d[7]))

    entrances = [Entrance(d[4], d[0], d[1], d[5], d[6], d[7], d[11])
                 for d in _records(blocks[6], endian + 'HHhhBBBBBBxBHBBBBBx')]

    zones = [Zone(d[6], d[0], d[1], d[2], d[3])
             for d in _records(blocks[9], endian + 'HHHHHHBBBBBBBBBBBBBBxx')]

    locations = [Location(d[4], d[0], d[1], d[2], d[3])
                 for d in _records(blocks[10], endian + 'HHHHBxxx')]

    paths = []
    for d in _records(blocks[13], endian + 'BbHHHxxxx'):
        if d[0] != NABBIT_PATH_ID:
            paths.append(Path(d[0], d[3], d[4] == 2))

    objects = []
    objcount = 0
    for idx, layer in enumerate(layers):
        if not layer:
            continue
        # Layer objects take 16 bytes; the last 5 are padding
        for d in _records(layer, endian + 'HhhHHB', 16):
            if d[0] == 0xFFFF:
                break
            objcount += 1
            if idx == 1:
                objects.append(Rect(d[1], d[2], d[3], d[4]))

    return AreaSnapshot(num, sprites, entrances, zones, locations, paths, objects, objcount, start)


def snapshot_live_area(area):
    """
    Snapshot of the area open in the editor, from its items. The lists keep the
    order of the area's own lists so findings can point at the items.
    """
    sprites = [Sprite(s.type, s.objx, s.objy, bytes(s.spritedata), s.layer) for s in area.sprites]
    entrances = [Entrance(e.entid, e.objx, e.objy, e.destarea, e.destentrance, e.enttype, e.entsettings)
                 for e in area.entrances]
    zones = [Zone(z.id, z.objx, z.objy, z.width, z.height) for z in area.zones]
    locations = [Location(l.id, l.objx, l.objy, l.width, l.height) for l in area.locations]
    paths = [Path(p['id'], len(p['nodes']), p['loops']) for p in area.pathdata]
    objects = [Rect(o.objx, o.objy, o.width, o.height) for o in area.layers[1]]
    objcount = sum(len(layer) for layer in area.layers)

    return AreaSnapshot(area.areanum, sprites, entrances, zones, locations, paths, objects, objcount,
                        getattr(area, 'startEntrance', 0))


def snapshot_level(level, little_endian=None):
    """
    Snapshots of every area of a loaded level: the open area from its items, the
    others from the course data they were loaded from.
    """
    if little_endian is None:
        little_endian = bool(globals.IsNSMBUDX)

    snaps = []
    for area in level.areas:
        if area is globals.Area and hasattr(area, 'layers'):
            snaps.append(snapshot_live_area(area))
        else:
            snaps.append(parse_area(area.areanum, area.course, (area.L0, area.L1, area.L2), little_endian))
    return snaps


def snapshot_archive(data, little_endian):
    """
    Snapshots of every area in a level archive (uncompressed SARC bytes).
    """
    import SarcLib

    arc = SarcLib.SARC_Archive()
    arc.load(data)

    files = {}
    for f in arc['course'].contents:
        if f.data is not None:
            files[f.name] = f.data

    snaps = []
    num = 1
    while 'course%d.bin' % num in files:
        layers = tuple(files.get('course%d_bgdatL%d.bin' % (num, i)) for i in range(3))
        snaps.append(parse_area(num, files['course%d.bin' % num], layers, little_endian))
        num += 1
    return snaps


################################################################
# Rules
################################################################

def _deep_update(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def default_rules_path():
    return os.path.join(globals.miyamoto_path, 'yaz0data', RULES_FILE)


def user_rules_path():
    return os.path.join(globals.user_data_path, RULES_FILE)


def load_rules():
    """
    The bundled rules, with the user's rules file (if any) merged on top.
    Returns (rules, error message or None).
    """
    with open(default_rules_path(), encoding='utf-8') as f:
        rules = json.load(f)

    path = user_rules_path()
    if not os.path.isfile(path):
        return rules, None

    try:
        with open(path, encoding='utf-8') as f:
            _deep_update(rules, json.load(f))
    except (OSError, ValueError) as e:
        return rules, 'Your rules file could not be read, so the default rules were used:\n%s\n\n%s' % (path, e)
    return rules, None


################################################################
# Checks
################################################################

class _Checker:
    def __init__(self, areas, rules, fields_for, sprite_name):
        self.areas = areas
        self.rules = rules
        self.fields_for = fields_for
        self.sprite_name = sprite_name
        self.findings = []

    def _rule(self, name):
        rule = self.rules.get('checks', {}).get(name, {})
        return rule if rule.get('enabled', True) else None

    def add(self, name, area, message, target=None):
        rule = self.rules.get('checks', {}).get(name, {})
        severity = rule.get('severity', 'warning')
        if severity not in SEVERITIES:
            severity = 'warning'
        self.findings.append(Finding(severity, name, area, message, target))

    def ids(self, key):
        return set(self.rules.get('sprites', {}).get(key, []))

    def spr(self, sprite):
        return '%s (sprite %s)' % (self.sprite_name(sprite.type), sprite.type)

    @staticmethod
    def at(item):
        return 'at (%d, %d)' % (item.x // 16, item.y // 16)

    def run(self):
        for name in sorted(self.rules.get('checks', {})):
            if self._rule(name) is None:
                continue
            check = getattr(self, 'check_' + name, None)
            if check is not None:
                check(self._rule(name))
        order = {s: i for i, s in enumerate(SEVERITIES)}
        self.findings.sort(key=lambda f: (order[f.severity], f.area, f.rule))
        return self.findings

    # ---- helpers

    @staticmethod
    def _in_zone(x, y, zones, margin=0):
        for z in zones:
            if z.x - margin <= x < z.x + z.width + margin and z.y - margin <= y < z.y + z.height + margin:
                return z
        return None

    def _id_fields(self, sprite):
        """(title, id_type, value) of the active ID fields of a sprite."""
        for f in self.fields_for(sprite.type) or ():
            if f[0] != 2 or len(f) < 6 or not f[5]:
                continue
            required = f[7] if len(f) > 7 else None
            if required and not all(lo <= extract_field_value(sprite.data, bits) < hi
                                    for bits, (lo, hi) in required):
                continue
            yield f[1], f[5], extract_field_value(sprite.data, f[2])

    def _area(self, num):
        for a in self.areas:
            if a.num == num:
                return a
        return None

    # ---- the checks; each one is named in the rules file

    def check_start_entrance_missing(self, rule):
        if not self.areas:
            return
        first = self.areas[0]
        if not any(e.id == first.startEntrance for e in first.entrances):
            self.add('start_entrance_missing', first.num,
                     'The level starts at entrance %d, which does not exist in area %d.' % (first.startEntrance, first.num))

    def check_duplicate_entrance_id(self, rule):
        for a in self.areas:
            for eid, count in Counter(e.id for e in a.entrances).items():
                if count > 1:
                    idx = next(i for i, e in enumerate(a.entrances) if e.id == eid)
                    self.add('duplicate_entrance_id', a.num,
                             '%d entrances share the ID %d.' % (count, eid), ('entrance', idx))

    def check_warp_destination_missing(self, rule):
        enterable = set(rule.get('entrance_types', []))
        for a in self.areas:
            for i, e in enumerate(a.entrances):
                if e.type not in enterable or e.settings & 0x80:
                    continue
                destnum = e.destarea or a.num
                dest = self._area(destnum)
                if dest is None:
                    self.add('warp_destination_missing', a.num,
                             'Entrance %d leads to area %d, which does not exist.' % (e.id, destnum), ('entrance', i))
                elif not any(d.id == e.destentrance for d in dest.entrances):
                    self.add('warp_destination_missing', a.num,
                             'Entrance %d leads to entrance %d in area %d, which does not exist.'
                             % (e.id, e.destentrance, destnum), ('entrance', i))
                elif destnum == a.num and e.destentrance == e.id:
                    self.add('warp_destination_missing', a.num,
                             'Entrance %d leads to itself.' % e.id, ('entrance', i))

    def check_entrance_outside_zone(self, rule):
        for a in self.areas:
            if not a.zones:
                continue
            for i, e in enumerate(a.entrances):
                if self._in_zone(e.x, e.y, a.zones) is None:
                    self.add('entrance_outside_zone', a.num,
                             'Entrance %d %s is outside every zone.' % (e.id, self.at(e)), ('entrance', i))

    def check_sprite_outside_zone(self, rule):
        margin = rule.get('margin', 0)
        ignore = self.ids('ignore_outside_zone')
        for a in self.areas:
            if not a.zones:
                continue
            for i, s in enumerate(a.sprites):
                if s.type in ignore:
                    continue
                if self._in_zone(s.x, s.y, a.zones, margin) is None:
                    self.add('sprite_outside_zone', a.num,
                             '%s %s is outside every zone, so it may never appear in the game.'
                             % (self.spr(s), self.at(s)), ('sprite', i))

    def check_zone_overlap(self, rule):
        for a in self.areas:
            zones = a.zones
            for i in range(len(zones)):
                for j in range(i + 1, len(zones)):
                    p, q = zones[i], zones[j]
                    if p.x < q.x + q.width and q.x < p.x + p.width and p.y < q.y + q.height and q.y < p.y + p.height:
                        self.add('zone_overlap', a.num, 'Zones %d and %d overlap.' % (p.id, q.id), ('zone', i))

    def check_star_coin_count(self, rule):
        ids = self.ids('star_coins')
        total = sum(1 for a in self.areas for s in a.sprites if s.type in ids)
        expected = rule.get('expected', 3)
        if total and total != expected:
            self.add('star_coin_count', self.areas[0].num,
                     'The level has %d Star Coins; levels normally have %d.' % (total, expected))
        elif not total and rule.get('warn_if_none', False):
            self.add('star_coin_count', self.areas[0].num, 'The level has no Star Coins.')

    def check_star_coin_duplicate_number(self, rule):
        ids = self.ids('numbered_star_coins')
        seen = {}
        for a in self.areas:
            for i, s in enumerate(a.sprites):
                if s.type not in ids:
                    continue
                number = (s.data[4] & 15) + 1
                if number in seen:
                    self.add('star_coin_duplicate_number', a.num,
                             'More than one Star Coin is set as Star Coin %d.' % number, ('sprite', i))
                seen[number] = True

    def check_checkpoint_count(self, rule):
        ids = self.ids('checkpoints')
        found = [(a, i) for a in self.areas for i, s in enumerate(a.sprites) if s.type in ids]
        limit = rule.get('max', 1)
        if len(found) > limit:
            a, i = found[limit]
            self.add('checkpoint_count', a.num,
                     'The level has %d checkpoint flags; the game supports %d.' % (len(found), limit), ('sprite', i))

    def check_no_goal(self, rule):
        ids = self.ids('level_ends')
        if self.areas and not any(s.type in ids for a in self.areas for s in a.sprites):
            self.add('no_goal', self.areas[0].num,
                     'No Goal Pole or boss was found. Make sure the level can be finished '
                     '(for example through an exit to the world map).')

    def check_id_reference_missing(self, rule):
        types = rule.get('id_types', {})
        for a in self.areas:
            existing = {
                'path': {p.id for p in a.paths},
                'location': {l.id for l in a.locations},
                'entrance': {e.id for e in a.entrances},
            }
            for i, s in enumerate(a.sprites):
                for title, id_type, value in self._id_fields(s):
                    if id_type not in types or id_type not in existing:
                        continue
                    if value == 0 and types[id_type].get('zero_is_unset', True):
                        continue
                    if value not in existing[id_type]:
                        self.add('id_reference_missing', a.num,
                                 '%s %s uses %s %d, but there is no %s %d in this area.'
                                 % (self.spr(s), self.at(s), title, value, id_type, value), ('sprite', i))

    def check_id_used_once(self, rule):
        types = set(rule.get('id_types', []))
        for a in self.areas:
            uses = {}
            for i, s in enumerate(a.sprites):
                for title, id_type, value in self._id_fields(s):
                    if id_type in types and value != 0:
                        uses.setdefault((id_type, value), []).append((i, s, title))
            for (id_type, value), users in sorted(uses.items()):
                if len(users) == 1:
                    i, s, title = users[0]
                    self.add('id_used_once', a.num,
                             '%s %s is the only sprite with %s %d, so nothing is linked to it.'
                             % (self.spr(s), self.at(s), title, value), ('sprite', i))

    def check_path_too_short(self, rule):
        minimum = rule.get('min_nodes', 2)
        for a in self.areas:
            for i, p in enumerate(a.paths):
                if p.nodes < minimum:
                    self.add('path_too_short', a.num, 'Path %d has only %d node(s).' % (p.id, p.nodes))

    def check_duplicate_sprite(self, rule):
        for a in self.areas:
            seen = set()
            for i, s in enumerate(a.sprites):
                key = (s.type, s.x, s.y, s.data, s.layer)
                if key in seen:
                    self.add('duplicate_sprite', a.num,
                             '%s %s is placed twice in the same spot with the same settings.'
                             % (self.spr(s), self.at(s)), ('sprite', i))
                seen.add(key)

    def check_enemy_over_pit(self, rule):
        ids = self.ids('ground_enemies')
        for a in self.areas:
            if not a.zones or not a.objects:
                continue
            for i, s in enumerate(a.sprites):
                if s.type not in ids:
                    continue
                zone = self._in_zone(s.x, s.y, a.zones)
                if zone is None:
                    continue
                tx, ty = s.x // 16, s.y // 16
                bottom = (zone.y + zone.height) // 16
                if not any(o.x <= tx < o.x + o.width and o.y + o.height > ty and o.y < bottom for o in a.objects):
                    self.add('enemy_over_pit', a.num,
                             '%s %s has no ground below it and will fall out of the zone.'
                             % (self.spr(s), self.at(s)), ('sprite', i))

    def check_location_unused(self, rule):
        for a in self.areas:
            used = {v for s in a.sprites for _, t, v in self._id_fields(s) if t == 'location'}
            for i, l in enumerate(a.locations):
                if l.id not in used:
                    self.add('location_unused', a.num, 'No sprite uses location %d.' % l.id, ('location', i))

    def check_empty_area(self, rule):
        for a in self.areas:
            if not a.zones:
                self.add('empty_area', a.num, 'Area %d has no zones.' % a.num)
            if not a.entrances:
                self.add('empty_area', a.num, 'Area %d has no entrances, so it cannot be reached.' % a.num)


def check_level(areas, rules, fields_for=None, sprite_name=None):
    """
    Runs every enabled check over the area snapshots and returns the findings,
    errors first.
    """
    return _Checker(areas, rules, fields_for or sprite_fields, sprite_name or sprite_display_name).run()


def sprite_fields(type):
    """The editor's field definitions for a sprite type, or ()."""
    sprites = getattr(globals, 'Sprites', None)
    if isinstance(type, str):
        sdef = globals.CustomSpriteDefinitions.get(type)
    elif sprites is not None and 0 <= type < len(sprites):
        sdef = sprites[type]
    else:
        sdef = None
    return sdef.fields if sdef is not None else ()


def sprite_display_name(type):
    sprites = getattr(globals, 'Sprites', None)
    if isinstance(type, str):
        return type
    if sprites is not None and 0 <= type < len(sprites) and sprites[type] is not None:
        return sprites[type].name
    return 'Sprite'


################################################################
# Metrics
################################################################

METRICS = (
    'Areas',
    'Zones',
    'Zone width (tiles)',
    'Sprites',
    'Enemies',
    'Enemies per 100 tiles',
    'Coin sprites',
    'Star Coins',
    'Checkpoints',
    'Entrances',
    'Paths',
    'Objects',
)


def compute_metrics(areas, rules, enemy_ids, coin_ids):
    sprites = [s for a in areas for s in a.sprites]
    width = sum(z.width for a in areas for z in a.zones) / 16
    enemies = sum(1 for s in sprites if s.type in enemy_ids)
    star_coins = set(rules.get('sprites', {}).get('star_coins', []))
    checkpoints = set(rules.get('sprites', {}).get('checkpoints', []))

    return {
        'Areas': len(areas),
        'Zones': sum(len(a.zones) for a in areas),
        'Zone width (tiles)': round(width),
        'Sprites': len(sprites),
        'Enemies': enemies,
        'Enemies per 100 tiles': round(enemies * 100 / width, 1) if width else 0,
        'Coin sprites': sum(1 for s in sprites if s.type in coin_ids and s.type not in star_coins),
        'Star Coins': sum(1 for s in sprites if s.type in star_coins),
        'Checkpoints': sum(1 for s in sprites if s.type in checkpoints),
        'Entrances': sum(len(a.entrances) for a in areas),
        'Paths': sum(len(a.paths) for a in areas),
        'Objects': sum(a.objcount for a in areas),
    }


def category_sprite_ids(view=None, category=None):
    """
    Sprite IDs listed under a sprite picker view and/or category name
    (from spritecategories.xml).
    """
    from .loading import LoadSpriteCategories
    LoadSpriteCategories()

    ids = set()
    for viewname, cats, _ in globals.SpriteCategories:
        if viewname == 'All' or (view is not None and viewname != view):
            continue
        for catname, sprites in cats:
            if category is None or catname == category:
                ids.update(sprites)
    return ids


def percentile(value, values):
    """Share of values (0-100) that are below value, counting ties as half."""
    if not values:
        return None
    below = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return round((below + equal / 2) * 100 / len(values))


def scan_courses(folder, little_endian, rules, enemy_ids, coin_ids, progress=None):
    """
    Metrics of every level archive in a game's course folder, as {name: metrics}.
    Files that cannot be read are skipped. progress(done, total) may return True
    to cancel.
    """
    from . import yaz0

    names = sorted(n for n in os.listdir(folder) if n.lower().endswith(('.sarc', '.szs')))
    results = {}
    for done, name in enumerate(names):
        if progress is not None and progress(done, len(names)):
            break
        try:
            with open(os.path.join(folder, name), 'rb') as f:
                data = f.read()
            if data[:4] == b'Yaz0':
                data = yaz0.decompressFASTYZ(data)
            areas = snapshot_archive(data, little_endian)
        except Exception:
            continue
        if areas:
            results[os.path.splitext(name)[0]] = compute_metrics(areas, rules, enemy_ids, coin_ids)
    return results
