#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Quick Paint: paint terrain (ground, platforms, slopes...) with a brush, and the right edge,
corner, inner corner, slope and fill objects are picked for every tile.

A *preset* says which tileset object to use for each part of a piece of terrain: the fill
(center), the four edges, the four outer corners, the four inner corners and the slopes
(45, 2:1 and 4:1, on floors and ceilings). Painting, erasing or drawing a slope works out,
for every tile of the terrain, which part it is from its neighbours, then places objects:

* as few, large objects as possible (rows and blocks of the same part are merged), so the
  result is light and easy to select, move and resize like hand-placed objects;
* existing terrain made of the preset's objects is recognised, so painting next to or over
  it, or erasing from it, re-tiles it so it all blends together, and moving or resizing
  terrain objects re-tiles them where they were and where they land (with the Quick Paint
  panel open);
* slope tiles count as ground for the tiles around them (so the flat ground and walls next
  to a slope get the pieces Nintendo uses there), and the ground under a slope is filled;
* each stroke is one step of Undo, and while drawing, the level shows what it will look like.

The part rules match how Nintendo's own levels use their tilesets (checked against the
Deluxe courses), so Auto-detect can build a preset from the terrain already in a level.

This replaces Miyamoto's Quick Paint tool (by John10v10), which split everything into 1x1
objects and merged them back, had no undo or slopes and couldn't touch terrain once placed.
"""

import math
from collections import Counter, defaultdict

from PyQt5 import QtCore, QtGui, QtWidgets
Qt = QtCore.Qt

from . import globals
from . import gametilesets
from .misc import setting, setSetting

MODE_OFF, MODE_PAINT, MODE_SLOPE, MODE_ERASE = 'off', 'paint', 'slope', 'erase'
MODE_SHAPE = 'shape'  # terrain drawn as an editable outline of points (qpshapes.py)

PRESET_VERSION = 2  # 1: inner corners were laid out mirrored in the panel (see load_presets)

# The parts of a piece of terrain
OUTER_ROLES = ('topLeft', 'top', 'topRight',
               'left', 'center', 'right',
               'bottomLeft', 'bottom', 'bottomRight')
# Inner corners are named after the neighbour that is empty (innerTopLeft: everything
# around is ground except the tile up and to the left), and laid out in the panel where
# they go around a hole: the one at a hole's top-left corner has its empty tile below-right
INNER_ROLES = ('innerBottomRight', 'innerBottomLeft',
               'innerTopRight', 'innerTopLeft')

# Slope steepness, as tiles across per tile up: 'Steep' (1 across per 2 up), 45 degrees, 2:1 and
# 4:1, every angle the game's tilesets have. (The game has steep slopes only as invisible ones,
# in the shared Pa0 tilesets; custom tilesets can have visible ones.)
SLOPE_STEPS = ('Steep', 1, 2, 4)
SLOPE_RATIO = {'Steep': 0.5, 1: 1.0, 2: 2.0, 4: 4.0}
SLOPE_ORIENTATIONS = ('floorUp', 'floorDown', 'ceilDown', 'ceilUp')  # = the slope control byte & 3
SLOPE_ROLES = tuple('slope%s_%s' % (s, o) for s in SLOPE_STEPS for o in SLOPE_ORIENTATIONS)
ROLES = OUTER_ROLES + INNER_ROLES + SLOPE_ROLES

ROLE_NAMES = {
    'topLeft': 'Top-left corner', 'top': 'Top edge', 'topRight': 'Top-right corner',
    'left': 'Left edge', 'center': 'Fill (required)', 'right': 'Right edge',
    'bottomLeft': 'Bottom-left corner', 'bottom': 'Bottom edge', 'bottomRight': 'Bottom-right corner',
    'innerBottomRight': 'Inner corner at the top-left of a hole<br>(ground all round except down-right)',
    'innerBottomLeft': 'Inner corner at the top-right of a hole<br>(ground all round except down-left)',
    'innerTopRight': 'Inner corner at the bottom-left of a hole, or where ground meets a wall on its right<br>'
                     '(ground all round except up-right)',
    'innerTopLeft': 'Inner corner at the bottom-right of a hole, or where ground meets a wall on its left<br>'
                    '(ground all round except up-left)',
}
_STEEPNESS = {'Steep': '1:2 steep', 1: '45\N{DEGREE SIGN}', 2: '2:1', 4: '4:1'}
_ORIENT_NAMES = {'floorUp': 'floor, rising to the right', 'floorDown': 'floor, falling to the right',
                 'ceilDown': 'ceiling, going down to the right', 'ceilUp': 'ceiling, going up to the right'}
for _s in SLOPE_STEPS:
    for _o in SLOPE_ORIENTATIONS:
        ROLE_NAMES['slope%s_%s' % (_s, _o)] = '%s slope, %s' % (_STEEPNESS[_s], _ORIENT_NAMES[_o])

# What a part falls back to when the preset has no object for it
FALLBACK = {
    'topLeft': ('top', 'left'), 'topRight': ('top', 'right'),
    'bottomLeft': ('bottom', 'left'), 'bottomRight': ('bottom', 'right'),
}

MAX_BRUSH = 9
FILL_DOWN_LIMIT = 32  # how far the ground under a slope is extended to reach other ground

# What goes under a new slope (above it, for a ceiling slope)
SLOPE_FILL_NONE = 0    # nothing: just the slope object, at the angle drawn
SLOPE_FILL_STEPS = 1   # ground under its steps, inside the slope's box
SLOPE_FILL_GROUND = 2  # that, and on down until it meets other ground
SLOPE_FILL_NAMES = {SLOPE_FILL_NONE: 'Nothing (just the slope)', SLOPE_FILL_STEPS: 'Ground under its steps',
                    SLOPE_FILL_GROUND: 'Ground down to the ground below'}


# ------------------------------------------------------------------------------- terrain rules

def role_for(filled, x, y):
    """
    Which part of the terrain the tile (x, y) is, given filled(x, y) -> bool for its
    neighbours. Tops win over bottoms (a one tile high platform gets its top edge).
    """
    n, s = filled(x, y - 1), filled(x, y + 1)
    w, e = filled(x - 1, y), filled(x + 1, y)
    if not n:
        return 'topLeft' if not w else 'topRight' if not e else 'top'
    if not s:
        return 'bottomLeft' if not w else 'bottomRight' if not e else 'bottom'
    if not w:
        return 'left'
    if not e:
        return 'right'
    if not filled(x - 1, y - 1):
        return 'innerTopLeft'
    if not filled(x + 1, y - 1):
        return 'innerTopRight'
    if not filled(x - 1, y + 1):
        return 'innerBottomLeft'
    if not filled(x + 1, y + 1):
        return 'innerBottomRight'
    return 'center'


def object_for(roles, role):
    """The (tileset, object) for a part, falling back to similar parts and then the fill."""
    for name in (role,) + FALLBACK.get(role, ()) + ('center',):
        value = roles.get(name)
        if value:
            return tuple(value)
    return None


def merge_rectangles(cells):
    """
    Covers {(x, y): key} with as few rectangles of one key as a greedy pass finds: runs
    along each row, extended down while the rows below match. Returns [(x, y, w, h, key)].
    """
    left = dict(cells)
    out = []
    for (x, y) in sorted(cells, key=lambda c: (c[1], c[0])):
        key = left.get((x, y))
        if key is None:
            continue
        w = 1
        while left.get((x + w, y)) == key:
            w += 1
        h = 1
        while all(left.get((x + i, y + h)) == key for i in range(w)):
            h += 1
        for j in range(h):
            for i in range(w):
                del left[(x + i, y + j)]
        out.append((x, y, w, h, key))
    return out


def rect_cells(x, y, w, h):
    return {(x + i, y + j) for j in range(h) for i in range(w)}


def expand(cells, by=1):
    return {(x + dx, y + dy) for (x, y) in cells for dx in range(-by, by + 1) for dy in range(-by, by + 1)}


def obj_key(obj):
    return obj.tileset, obj.original_type


def obj_cells(obj):
    return rect_cells(obj.objx, obj.objy, obj.width, obj.height)


def preset_keys(preset):
    return {tuple(value) for value in preset.get('roles', {}).values() if value}


# ------------------------------------------------------------------------------- slopes

def global_def(key):
    """The tileset's definition of an object (or of a game object a preset part names), or None."""
    if gametilesets.is_ref(key):
        entry = gametilesets.entry_for(key)
        return entry.obj if entry is not None else None
    ts, num = key
    try:
        defs = globals.ObjectDefinitions[ts]
        return defs[num] if defs is not None else None
    except (IndexError, TypeError):
        return None


def is_diagonal(definition):
    """Whether an object definition is a slope (its first byte is a slope control byte)."""
    try:
        return bool(definition is not None and definition.rows and definition.rows[0]
                    and definition.rows[0][0][0] & 0x80)
    except (AttributeError, IndexError, TypeError):
        return False


def slope_shape(definition):
    """(control byte, step width, step height, height of the part under each step) of a slope."""
    from .tileset import GetSlopeSections
    main, sub = GetSlopeSections(definition)
    return definition.rows[0][0][0], len(main[0]), len(main), len(sub) if sub else 0


def slope_kind(definition):
    """
    (steepness, rank) of a slope object: its steepness in SLOPE_STEPS, and 0 for the usual
    shape of it or 1 for another (45-degree slopes made of 2x2 steps, as in towers), or
    (None, None) if it's no slope Quick Paint knows.
    """
    if not is_diagonal(definition):
        return None, None
    _, step_w, step_h, _ = slope_shape(definition)
    if step_h == 1 and step_w in (1, 2, 4):
        return step_w, 0
    if (step_w, step_h) == (1, 2):
        return 'Steep', 0
    if step_w == step_h > 1:
        return 1, 1
    return None, None


def slope_role_for(definition):
    """The preset part a slope object is (e.g. 'slope2_floorUp'), or None."""
    kind, _ = slope_kind(definition)
    if kind is None:
        return None
    return 'slope%s_%s' % (kind, SLOPE_ORIENTATIONS[definition.rows[0][0][0] & 3])


_shape_cache = {}


def _relative_slope_cells(definition, w, h):
    """The tiles a slope object of this size draws (its steps and what's under them)."""
    key = (id(definition), w, h)
    cells = _shape_cache.get(key)
    if cells is None:
        from .tileset import _RenderObject
        cells = frozenset((x, y) for y, row in enumerate(_RenderObject(definition, w, h)) for x, t in enumerate(row)
                          if t != -1)
        if len(_shape_cache) > 4096:
            _shape_cache.clear()
        _shape_cache[key] = cells
    return cells


def slope_kinds(roles, get_def, orient):
    """The steepnesses the preset has a slope object for, going this way."""
    found = []
    for kind in SLOPE_STEPS:
        key = roles.get('slope%s_%s' % (kind, orient))
        if key and is_diagonal(get_def(tuple(key))):
            found.append(kind)
    return found


def slope_segment(roles, get_def, start, target, steepness=0, ceiling=False):
    """
    The slope object for a line from start towards target, where both are corners of the tile
    grid on the ground's surface: the top of the ground for a floor slope, the underside of
    the ceiling for a ceiling slope (so a slope that starts on flat ground starts at the top-
    left corner of its first column there).

    The steepness is the one closest to the line (or `steepness`, if the preset has it), and the
    slope climbs as far as the line goes up or down, rounded to whole steps. Returns
    ((x, y, w, h, key), end): the object, and the corner where it really ends (on the grid,
    where the next slope or flat ground joins it seamlessly); or None.
    """
    dx, dy = target[0] - start[0], target[1] - start[1]
    if dx == 0 or dy == 0:
        return None
    rising = (dx > 0) != (dy > 0)  # its right end is higher
    orient = ('ceilUp' if rising else 'ceilDown') if ceiling else ('floorUp' if rising else 'floorDown')
    kinds = slope_kinds(roles, get_def, orient)
    if steepness:
        kinds = [k for k in kinds if k == steepness]
    if not kinds:
        return None
    ratio = abs(dx) / float(abs(dy))
    kind = min(kinds, key=lambda k: abs(math.log(ratio / SLOPE_RATIO[k])))
    key = tuple(roles['slope%s_%s' % (kind, orient)])
    _, step_w, step_h, sub_h = slope_shape(get_def(key))
    n = max(1, int(round(abs(dy) / float(step_h))))
    w, rise = n * step_w, n * step_h
    end = (start[0] + (w if dx > 0 else -w), start[1] + (rise if dy > 0 else -rise))
    left, right = (start, end) if start[0] < end[0] else (end, start)
    if ceiling:
        y = (right[1] if rising else left[1]) - sub_h  # the ground over its steps is in the ceiling
    else:
        y = left[1] - rise if rising else left[1]  # the ground under its steps is in the floor
    if left[0] < 0 or y < 0:
        return None
    return (left[0], y, w, rise + sub_h, key), end


def slope_rect(roles, get_def, start, end, steepness=0, ceiling=False):
    """The slope object (x, y, w, h, key) for a line from start to end (see slope_segment), or None."""
    segment = slope_segment(roles, get_def, start, end, steepness, ceiling)
    return segment[0] if segment else None


# ------------------------------------------------------------------------------- planning

class TerrainPlanner:
    """
    Works out changes to the terrain of one layer without touching the level: which
    objects to delete and which to place. Made once per stroke, so the preview can be
    worked out again on every mouse move.

    objects: the layer's objects (anything with tileset, original_type, objx, objy, width,
    height); roles: the preset's {part: (tileset, object)}; get_def((tileset, object)) gives
    an object's definition (to recognise slopes and the tiles they draw).
    """

    def __init__(self, objects, roles, get_def=None):
        self.roles = {role: tuple(value) for role, value in roles.items() if value}
        self.get_def = get_def or global_def
        fill_keys = {v for r, v in self.roles.items() if r not in SLOPE_ROLES}
        slope_keys = {v for r, v in self.roles.items() if r in SLOPE_ROLES}
        self.terrain, self.slopes = [], []
        for obj in objects:
            key = obj_key(obj)
            diagonal = is_diagonal(self.get_def(key))
            if diagonal and key in slope_keys:
                self.slopes.append(obj)
            elif not diagonal and key in fill_keys:
                self.terrain.append(obj)
        self.owners = defaultdict(list)
        for obj in self.terrain:
            for cell in obj_cells(obj):
                self.owners[cell].append(obj)
        self.slope_cells = {obj: self.slopeCells(obj.objx, obj.objy, obj.width, obj.height, obj_key(obj))
                            for obj in self.slopes}
        self.slope_owner = {}
        for obj, cells in self.slope_cells.items():
            for cell in cells:
                self.slope_owner[cell] = obj

    def slopeCells(self, x, y, w, h, key):
        definition = self.get_def(key)
        if not is_diagonal(definition):
            return rect_cells(x, y, w, h)
        return {(x + i, y + j) for (i, j) in _relative_slope_cells(definition, w, h)}

    def isFilled(self, cell):
        return cell in self.owners or cell in self.slope_owner

    def plan(self, paint=(), erase=(), regions=(), convert=(), new_slopes=()):
        """
        paint / erase: tiles to add to or take from the terrain (erasing any tile of a slope
        removes the slope); regions: tiles to re-tile; convert: other objects to turn into
        terrain; new_slopes: slope objects to place, [(x, y, w, h, (tileset, object))].

        Returns (remove, add): the objects to delete, and [(x, y, w, h, (tileset, object))]
        to place, slopes last (so they are drawn over the ground under them). Terrain
        objects that come out the same are left alone.
        """
        paint = {c for c in paint if c[0] >= 0 and c[1] >= 0}
        convert = [obj for obj in convert if obj not in self.terrain and obj not in self.slope_cells
                   and not is_diagonal(self.get_def(obj_key(obj)))]
        for obj in convert:
            paint |= obj_cells(obj)
        erase = set(erase) - paint

        new_cells = set()
        for (x, y, w, h, key) in new_slopes:
            new_cells |= self.slopeCells(x, y, w, h, key)
        removed_slopes = [obj for obj, cells in self.slope_cells.items() if cells & erase or cells & new_cells]
        kept_slope_cells = set(new_cells)
        removed_cells = set()
        for obj, cells in self.slope_cells.items():
            if obj in removed_slopes:
                removed_cells |= cells
            else:
                kept_slope_cells |= cells

        filled = ((set(self.owners) | paint) - erase) | kept_slope_cells
        touched = paint | erase | set(regions) | removed_cells | new_cells

        affected = set()
        for cell in expand(touched):
            affected.update(self.owners.get(cell, ()))
        # Objects overlapping the ones being redone go too, or they would be left doubled up
        rebuild = set(paint)
        pending = list(affected)
        while pending:
            obj = pending.pop()
            for cell in obj_cells(obj):
                rebuild.add(cell)
                for other in self.owners.get(cell, ()):
                    if other not in affected:
                        affected.add(other)
                        pending.append(other)
        rebuild = (rebuild & filled) - kept_slope_cells  # slopes draw their own tiles

        is_filled = lambda x, y: (x, y) in filled
        parts = {}
        for (x, y) in rebuild:
            key = object_for(self.roles, role_for(is_filled, x, y))
            if key is not None:
                parts[(x, y)] = key

        existing = {}
        for obj in affected:
            existing.setdefault((obj.objx, obj.objy, obj.width, obj.height, obj_key(obj)), []).append(obj)
        add = []
        for rect in merge_rectangles(parts):
            same = existing.get(rect)
            if same:
                same.pop()  # already there: keep it
            else:
                add.append(rect)
        remove = [obj for objs in existing.values() for obj in objs] + convert + removed_slopes
        add += [(x, y, w, h, tuple(key)) for (x, y, w, h, key) in new_slopes]
        return remove, add

    def _reach(self, cx, r, step):
        """The tiles from row r on (down for step 1, up for -1) to the next ground, if it's near enough."""
        extra = []
        while r >= 0 and len(extra) < FILL_DOWN_LIMIT and not self.isFilled((cx, r)):
            extra.append(r)
            r += step
        return extra if r >= 0 and self.isFilled((cx, r)) else []

    def _support(self, rect, ceiling, fill):
        """The ground to put under a slope's steps (over them, on a ceiling) for this fill setting."""
        if fill not in (SLOPE_FILL_STEPS, SLOPE_FILL_GROUND):
            return set()
        x, y, w, h, key = rect
        cells = self.slopeCells(x, y, w, h, key)
        support = set()
        for cx in range(x, x + w):
            rows = [cy for (px, cy) in cells if px == cx]
            if not rows:
                continue
            if ceiling:
                column = list(range(y, min(rows)))
                if fill == SLOPE_FILL_GROUND:
                    column += self._reach(cx, y - 1, -1)
            else:
                column = list(range(max(rows) + 1, y + h))
                if fill == SLOPE_FILL_GROUND:
                    column += self._reach(cx, y + h, 1)
            support |= {(cx, cy) for cy in column}
        return support

    def flatRows(self, ceiling=False):
        """How thick flat ground between slopes is: as thick as a slope (a step and the ground under it)."""
        for kind in (1, 2, 4, 'Steep'):
            key = self.roles.get('slope%s_%s' % (kind, 'ceilDown' if ceiling else 'floorUp'))
            definition = self.get_def(key) if key else None
            if is_diagonal(definition):
                return 1 + slope_shape(definition)[3]
        return 2

    def planChain(self, start, targets, steepness=0, ceiling=False, fill=SLOPE_FILL_NONE):
        """
        Plans joined-up slopes, drawn as a line through grid corners: from start to each target
        in turn, a slope at the angle closest to that part of the line (see slope_segment), then
        flat ground the rest of the way across if the slope is shorter than the line (a level
        line is all flat ground). Each piece starts exactly where the one before really ended.
        fill is what goes under the slopes (SLOPE_FILL_*); the terrain they touch is re-tiled.

        Returns (remove, add, corners): corners are where each piece really ends, start first.
        None if nothing would be placed.
        """
        current, corners, rects, flat = tuple(start), [tuple(start)], [], set()
        thick = self.flatRows(ceiling)
        for target in targets:
            target = tuple(target)
            begin = current
            segment = None
            if target[1] != current[1]:
                segment = slope_segment(self.roles, self.get_def, current, target, steepness, ceiling)
                if segment is None:
                    continue  # no slope goes that way
                rect, current = segment
                rects.append(rect)
                corners.append(current)
            rest = target[0] - current[0]
            if rest and (target[0] - begin[0]) * rest > 0:  # short of the target, the same way: flat ground
                x0, x1 = sorted((current[0], target[0]))
                rows = range(current[1] - thick, current[1]) if ceiling else range(current[1], current[1] + thick)
                flat |= {(x, y) for x in range(x0, x1) for y in rows if x >= 0 and y >= 0}
                current = (target[0], current[1])
            if current != corners[-1]:
                corners.append(current)
        if not rects and not flat:
            return None
        slope_cells, support = set(), set()
        for rect in rects:
            slope_cells |= self.slopeCells(*rect)
            support |= self._support(rect, ceiling, fill)
        if fill == SLOPE_FILL_GROUND:
            for x in {c[0] for c in flat}:
                column = [c[1] for c in flat if c[0] == x]
                edge = min(column) - 1 if ceiling else max(column) + 1
                support |= {(x, r) for r in self._reach(x, edge, -1 if ceiling else 1)}
        remove, add = self.plan(paint=(support | flat) - slope_cells, new_slopes=rects)
        return remove, add, corners

    def planSlope(self, start, end, steepness=0, ceiling=False, fill=SLOPE_FILL_NONE):
        """
        Plans one slope drawn from start to end (grid corners, see slope_segment), with what fill
        asks for under it, and the re-tiling of the terrain it touches. Returns (remove, add,
        slope rect) or None.
        """
        segment = slope_segment(self.roles, self.get_def, start, end, steepness, ceiling)
        if segment is None:
            return None
        planned = self.planChain(start, [segment[1]], steepness, ceiling, fill)
        return planned[0], planned[1], segment[0]


def plan_terrain(objects, roles, paint=(), erase=(), regions=(), convert=(), get_def=None, new_slopes=()):
    """One-off TerrainPlanner(objects, roles, get_def).plan(...)."""
    return TerrainPlanner(objects, roles, get_def).plan(paint, erase, regions, convert, new_slopes)


def _pick(votes, min_share=0.3):
    """For each part, the object used most for it (and mostly for it)."""
    totals = Counter()
    for counter in votes.values():
        for key, n in counter.items():
            totals[key] += n
    out = {}
    for role, counter in votes.items():
        best = None
        for key, n in counter.items():
            share = n / float(totals[key])
            if share < min_share:
                continue
            score = n * share * share
            if best is None or score > best[0]:
                best = (score, key)
        if best is not None:
            out[role] = list(best[1])
    return out


def _fill_gaps(roles, votes, get_def):
    """
    Parts left without an object get the one used most in their place that no other part
    has, if it's a single tile. Nintendo's levels often cover inner corners with the fill
    object, so their real inner corner pieces are used too rarely to win the vote.
    """
    assigned = {tuple(v) for v in roles.values() if v}
    for role in OUTER_ROLES + INNER_ROLES:
        if roles.get(role):
            continue
        best = None
        for key, n in votes.get(role, {}).items():
            definition = get_def(key)
            if key in assigned or definition is None or is_diagonal(definition):
                continue
            if (definition.width, definition.height) != (1, 1):
                continue
            if best is None or n > best[0]:
                best = (n, key)
        if best is not None:
            roles[role] = list(best[1])
            assigned.add(best[1])
    return roles


def learn_roles(objects, get_def=None, slot=None, min_share=0.0):
    """
    A preset's parts from existing terrain: for each part, the object most used for it.
    Where objects overlap, the one drawn last counts. Slopes are recognised by their shape.
    slot limits it to one tileset.
    """
    get_def = get_def or global_def
    objects = [obj for obj in objects if slot is None or obj.tileset == slot]
    slopes = [obj for obj in objects if is_diagonal(get_def(obj_key(obj)))]
    votes = _layer_votes(objects, None, get_def)
    roles = _fill_gaps(_pick(votes, min_share), votes, get_def)
    slope_votes = defaultdict(Counter)
    for obj in slopes:
        role = slope_role_for(get_def(obj_key(obj)))
        if role:
            slope_votes[role][obj_key(obj)] += 1
    for role, counter in slope_votes.items():
        roles[role] = list(counter.most_common(1)[0][0])
    return roles


def find_slopes(slot, get_def=None, used=None):
    """
    The slope parts of a tileset: {part: [slot, object]} for every slope object it has.
    When a tileset has several (with and without grass, say), the one used most in
    `used` (a Counter of (slot, object)) wins, else the first.
    """
    get_def = get_def or global_def
    found, best = {}, {}
    for num in range(256):
        key = (slot, num)
        definition = get_def(key)
        role = slope_role_for(definition)
        if role is None:
            continue
        score = (-slope_kind(definition)[1], used[key] if used else 0)  # the usual shape first, then the one used most
        if role not in found or score > best[role]:
            found[role], best[role] = [slot, num], score
    return found


def find_game_slopes(key, entries):
    """The slope parts of a game tileset (the Game tab's), as references to its objects."""
    found, best = {}, {}
    for i, entry in enumerate(entries):
        role = slope_role_for(entry.obj)
        if role is None:
            continue
        score = -slope_kind(entry.obj)[1]
        if role not in found or score > best[role]:
            found[role], best[role] = ['game', key, i], score
    return found


def learn_from_layers(layers, slot, get_def=None):
    """
    Auto-detect: a preset for one tileset from how a level already uses it (the parts its
    terrain uses most, the way role_for sees them) plus every slope the tileset has.
    """
    get_def = get_def or global_def
    used = Counter()
    votes = defaultdict(Counter)
    for layer in layers:
        used.update(obj_key(obj) for obj in layer if obj.tileset == slot)
        for role, counter in _layer_votes(layer, slot, get_def).items():
            votes[role].update(counter)
    roles = _fill_gaps(_pick(votes), votes, get_def)
    roles.update(find_slopes(slot, get_def, used))
    return roles


def _layer_votes(layer, slot, get_def):
    """
    Votes {part: Counter((slot, object))} for the visible tiles of one tileset (any, if
    slot is None) on one layer. Slope tiles count as ground but get no votes.
    """
    planner = TerrainPlanner([], {}, get_def)
    filled = set()
    visible = {}
    for obj in layer:  # in drawing order: the last object drawn on a tile is the one seen
        key = obj_key(obj)
        mine = slot is None or obj.tileset == slot
        if is_diagonal(get_def(key)):
            cells = planner.slopeCells(obj.objx, obj.objy, obj.width, obj.height, key)
            for cell in cells:
                visible[cell] = None
        else:
            cells = obj_cells(obj)
            for cell in cells:
                visible[cell] = obj
        if mine:
            filled |= cells
    is_filled = lambda x, y: (x, y) in filled
    votes = defaultdict(Counter)
    for (x, y), obj in visible.items():
        if obj is not None and (slot is None or obj.tileset == slot):
            votes[role_for(is_filled, x, y)][obj_key(obj)] += 1
    return votes


# ------------------------------------------------------------------------------- applying (undoable)

def _object_exists(key):
    return global_def(tuple(key)) is not None


def _make_command():
    from . import undomanager

    class QuickPaintCommand(undomanager.Command):
        """Deletes and places the objects of a Quick Paint change on one layer, as one step."""

        def __init__(self, description, layer_idx, removed, added):
            super().__init__(description)
            self.layer_idx = layer_idx
            self.removed = removed
            self.added = added
            self.before = None

        def redo(self):
            layer = globals.Area.layers[self.layer_idx]
            if self.before is None:
                self.before = [(obj, obj.zValue()) for obj in layer]
            scene = globals.mainWindow.scene
            for obj in self.removed:
                if obj in layer:
                    obj.setSelected(False)
                    obj.delete()
                if obj.scene() is not None:
                    obj.scene().removeItem(obj)
            for obj in self.added:
                z = layer[-1].zValue() + 1 if layer else (2 - self.layer_idx) * 8192
                layer.append(obj)
                obj.layer = self.layer_idx
                obj.setZValue(z)
                if obj.scene() is not scene:
                    scene.addItem(obj)

        def undo(self):
            layer = globals.Area.layers[self.layer_idx]
            scene = globals.mainWindow.scene
            for obj in reversed(self.added):
                obj.setSelected(False)
                if obj in layer:
                    obj.delete()
                if obj.scene() is not None:
                    obj.scene().removeItem(obj)
            layer[:] = [obj for obj, z in self.before]
            for obj, z in self.before:
                obj.setZValue(z)
                if obj.scene() is not scene:
                    scene.addItem(obj)
            scene.update()

    return QuickPaintCommand


def planning_roles(roles):
    """
    A preset's parts for planning: a game object already copied into this area's tilesets is
    planned as that copy (so the terrain painted with it is recognised); one not copied yet stays
    a game object, and is copied when it's placed (apply_plan).
    """
    out = {}
    for role, value in roles.items():
        if value and gametilesets.is_ref(value):
            copied = gametilesets.level_copy(value, create=False)
            out[role] = list(copied) if copied else list(value)
        elif value:
            out[role] = value
    return out


def apply_plan(layer_idx, remove, add, description='Quick Paint'):
    """Applies a planned change (see TerrainPlanner.plan) as one undo step. Returns how many objects changed."""
    from .items import ObjectItem
    if not remove and not add:
        return 0
    mw = globals.mainWindow
    # Game objects (from presets made with the Game tab) are copied into the level's tilesets now
    copies = {}
    refs = {key for (_, _, _, _, key) in add if gametilesets.is_ref(key)}
    if refs:
        with gametilesets.batched_edits():
            for key in refs:
                copies[key] = gametilesets.level_copy(key)
        missing = [gametilesets.ref_label(k) for k, v in copies.items() if v is None]
        if missing:
            if _panel is not None:
                _panel.say("there's no room left in the level's tilesets for " + ', '.join(missing) + '.')
            return 0
    added = []
    for x, y, w, h, key in add:
        ts, num = copies.get(key, key)
        obj = ObjectItem(ts, num, layer_idx, x, y, w, h, 0, 0)
        obj.positionChanged = mw.HandleObjPosChange
        added.append(obj)
    globals.UndoManager.push(_make_command()(description, layer_idx, list(remove), added))
    return len(remove) + len(added)


def apply_terrain(layer_idx, roles, paint=(), erase=(), regions=(), convert=(), description='Quick Paint'):
    """Plans and applies a terrain change as one undo step. Returns how many objects changed."""
    if globals.Area is None or object_for(roles, 'center') is None:
        return 0
    roles = planning_roles(roles)
    remove, add = TerrainPlanner(globals.Area.layers[layer_idx], roles).plan(paint, erase, regions, convert)
    return apply_plan(layer_idx, remove, add, description)


# ------------------------------------------------------------------------------- presets

def _migrate(preset):
    """Version 1 presets had the inner corner buttons mirrored: what was picked for the one
    drawn at the top-left was stored as innerTopLeft, but belongs to innerBottomRight."""
    if preset.get('version', 1) < 2:
        roles = preset['roles']
        swapped = dict(roles)
        for a, b in (('innerTopLeft', 'innerBottomRight'), ('innerTopRight', 'innerBottomLeft')):
            swapped.pop(a, None)
            swapped.pop(b, None)
            if roles.get(a):
                swapped[b] = roles[a]
            if roles.get(b):
                swapped[a] = roles[b]
        preset['roles'] = swapped
        preset['version'] = PRESET_VERSION
        return True
    return False


def load_presets():
    presets = setting('QuickPaintPresets', None)
    if not isinstance(presets, list):
        presets = []
    out, migrated = [], False
    for preset in presets:
        if isinstance(preset, dict) and isinstance(preset.get('name'), str):
            # Parts are (tileset slot, object) or Game tab objects, ['game', tileset key, object]
            roles = {role: list(value) for role, value in (preset.get('roles') or {}).items()
                     if role in ROLES and isinstance(value, (list, tuple))
                     and (len(value) == 2 or gametilesets.is_ref(value))}
            entry = {'name': preset['name'], 'roles': roles, 'version': preset.get('version', 1)}
            if isinstance(preset.get('tileset'), str):
                entry['tileset'] = preset['tileset']
            migrated |= _migrate(entry)
            out.append(entry)
    if migrated:
        save_presets(out)
    return out


def save_presets(presets):
    for preset in presets:
        preset['version'] = PRESET_VERSION
    setSetting('QuickPaintPresets', presets)


def tileset_bound(preset):
    """Whether a preset uses objects of a level tileset (slot 1 to 3), which differ from tileset to tileset."""
    return any(value and not gametilesets.is_ref(value) and len(value) == 2 and value[0] in (1, 2, 3)
               for value in preset.get('roles', {}).values())


def mismatched(preset):
    """The tileset a preset was made for, if the open area doesn't use it (its parts would be other objects there)."""
    if preset is None or globals.Area is None or not tileset_bound(preset):
        return None
    name = preset.get('tileset')
    if name and name not in tuple(area_tileset(slot) for slot in range(1, 4)):
        return name
    return None


def preset_slot(roles):
    """The tileset slot a preset's objects are in (its fill's), or None (also for a game object)."""
    center = object_for(roles, 'center')
    return center[0] if center and isinstance(center[0], int) else None


def area_tileset(slot):
    if globals.Area is None or slot is None:
        return ''
    return getattr(globals.Area, 'tileset%d' % slot, '') or ''


def _draw_tiles(painter, tiles, ox, oy, tile, clip=None):
    """Draws a RenderObject() array with its top-left tile at (ox, oy) tiles."""
    for y, row in enumerate(tiles):
        for x, index in enumerate(row):
            if index == -1:
                continue
            if clip is not None and not clip(ox + x, oy + y):
                continue
            try:
                tile_ = globals.Tiles[index]
                image = tile_.getCurrentTile() if hasattr(tile_, 'getCurrentTile') else tile_.main
            except (AttributeError, IndexError, TypeError):
                continue
            if isinstance(image, QtGui.QImage):
                painter.drawImage((ox + x) * tile, (oy + y) * tile, image)
            elif image is not None:
                painter.drawPixmap((ox + x) * tile, (oy + y) * tile, image)


def object_pixmap(key, size):
    """A picture of a tileset object (up to 4x4 tiles of it; slopes show two steps), size x size pixels."""
    from .tileset import RenderObject
    pm = QtGui.QPixmap(size, size)
    pm.fill(Qt.transparent)
    definition = global_def(key)
    if definition is None:
        return pm
    entry = gametilesets.entry_for(key) if gametilesets.is_ref(key) else None
    if is_diagonal(definition):
        _, step_w, step_h, sub_h = slope_shape(definition)
        w, h = min(2 * step_w, 8), 2 * step_h + sub_h
    else:
        w, h = max(1, min(definition.width, 4)), max(1, min(definition.height, 4))
    tile = globals.TileWidth
    if entry is not None:
        full = gametilesets.entry_pixmap(entry, w, h)
    else:
        full = QtGui.QPixmap(w * tile, h * tile)
        full.fill(Qt.transparent)
        painter = QtGui.QPainter(full)
        try:
            _draw_tiles(painter, RenderObject(key[0], key[1], w, h, True), 0, 0, tile)
        finally:
            painter.end()
    scaled = full.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter = QtGui.QPainter(pm)
    painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    return pm


def role_diagram(role, size):
    """
    A small picture of a part, for parts with no object yet: the tile and its eight
    neighbours, solid where there is terrain, with the tile itself in the accent colour;
    for a slope, its shape.
    """
    pm = QtGui.QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QtGui.QPainter(pm)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    palette = QtWidgets.QApplication.palette()
    solid, empty = palette.color(QtGui.QPalette.Mid), palette.color(QtGui.QPalette.Base)
    accent = QtGui.QColor(255, 140, 0)
    if role in SLOPE_ROLES:
        kind = role[5:].split('_', 1)[0]
        ratio = SLOPE_RATIO['Steep' if kind == 'Steep' else int(kind)]
        orient = role.split('_', 1)[1]
        s = float(size - 4)
        rise = s / max(ratio, 1.0)  # gentle slopes: all the way across, less high
        run = s * min(ratio, 1.0)  # steep ones: all the way up, less wide
        o = 2.0
        points = {
            'floorUp': [(s - run, s), (s, s), (s, s - rise)],
            'floorDown': [(0, s), (run, s), (0, s - rise)],
            'ceilDown': [(s - run, 0), (s, 0), (s, rise)],
            'ceilUp': [(0, 0), (run, 0), (0, rise)],
        }[orient]
        painter.setPen(QtGui.QPen(accent, 1.5))
        painter.setBrush(solid)
        painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(o + px, o + py) for px, py in points]))
        painter.end()
        return pm
    neighbours = {  # which of the 3x3 tiles (row by row) are terrain
        'topLeft': '....##.##', 'top': '...######', 'topRight': '...##.##.',
        'left': '.##.##.##', 'center': '#########', 'right': '##.##.##.',
        'bottomLeft': '.##.##...', 'bottom': '######...', 'bottomRight': '##.##....',
        'innerTopLeft': '.########', 'innerTopRight': '##.######',
        'innerBottomLeft': '######.##', 'innerBottomRight': '########.',
    }[role]
    cell = size / 3.0
    for i, ch in enumerate(neighbours):
        r = QtCore.QRectF((i % 3) * cell + 1, (i // 3) * cell + 1, cell - 2, cell - 2)
        painter.setBrush(accent if i == 4 else solid if ch == '#' else empty)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(r, 2, 2)
    painter.end()
    return pm


# ------------------------------------------------------------------------------- the panel

class _RoleButton(QtWidgets.QToolButton):
    def __init__(self, role, panel, size=46):
        super().__init__()
        self.role = role
        self.panel = panel
        self.setFixedSize(size, size)
        self.setIconSize(QtCore.QSize(size - 8, size - 8))
        self.setAutoRaise(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.showMenu)
        self.clicked.connect(lambda: panel.assignPicked(role))

    def showMenu(self, pos):
        menu = QtWidgets.QMenu(self)
        menu.addAction('Use the picked palette object', lambda: self.panel.assignPicked(self.role))
        menu.addAction('Use the selected level object', lambda: self.panel.assignSelected(self.role))
        menu.addSeparator()
        menu.addAction('Clear', lambda: self.panel.assign(self.role, None))
        menu.exec_(self.mapToGlobal(pos))


class QuickPaintPanel(QtWidgets.QWidget):
    """The Quick Paint panel: mode, brush, preset and its parts, slopes and the re-tile tools."""

    def __init__(self):
        super().__init__()
        global _panel
        _panel = self
        self.mode = MODE_OFF
        # The mode last used comes back when the panel shows (also when Yaz0moto starts with it open)
        last = setting('QuickPaintMode', MODE_PAINT)
        self.pendingMode = last if last in (MODE_PAINT, MODE_SLOPE, MODE_SHAPE, MODE_ERASE) else None
        self.presets = load_presets()
        self._seenTilesets = None

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(8)

        # Mode and brush
        self.modeGroup = QtWidgets.QButtonGroup(self)
        self.modeGroup.setExclusive(True)
        modeRow = QtWidgets.QHBoxLayout()
        self.modeButtons = {}
        for mode, text in ((MODE_OFF, 'Off'), (MODE_PAINT, 'Paint'), (MODE_SLOPE, 'Slope'), (MODE_SHAPE, 'Shape'),
                           (MODE_ERASE, 'Erase')):
            button = QtWidgets.QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            self.modeGroup.addButton(button)
            self.modeButtons[mode] = button
            button.clicked.connect(lambda checked, m=mode: self.setMode(m))
            modeRow.addWidget(button)
        self.modeButtons[MODE_OFF].setChecked(True)
        outer.addLayout(modeRow)
        self.offHint = QtWidgets.QLabel('Quick Paint is <b>off</b>: clicks in the level select as usual. '
                                        'Pick <b>Paint</b>, <b>Slope</b> or <b>Erase</b> to paint.')
        self.offHint.setWordWrap(True)
        self.offHint.setStyleSheet('color: rgb(255, 140, 0); font-size: 11px;')
        outer.addWidget(self.offHint)

        brushRow = QtWidgets.QHBoxLayout()
        brushRow.addWidget(QtWidgets.QLabel('Brush size (tiles):'))
        self.brush = QtWidgets.QSpinBox()
        self.brush.setRange(1, MAX_BRUSH)
        self.brush.setToolTip('Width and height of the brush. Shift + drag fills a rectangle instead.')
        self.brush.setValue(max(1, min(MAX_BRUSH, int(setting('QuickPaintBrush', 1) or 1))))
        self.brush.valueChanged.connect(lambda v: setSetting('QuickPaintBrush', v))
        brushRow.addWidget(self.brush, 1)
        outer.addLayout(brushRow)

        # Presets
        presetRow = QtWidgets.QHBoxLayout()
        self.presetBox = QtWidgets.QComboBox()
        self.presetBox.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.presetBox.currentIndexChanged.connect(self.presetChanged)
        presetRow.addWidget(self.presetBox, 1)
        autoButton = QtWidgets.QToolButton()
        autoButton.setText('Auto-detect')
        autoButton.setToolTip('Make a preset for this area\'s tileset from how the level already uses it: the '
                              'edge, corner and fill objects its terrain uses most, and every slope the tileset has')
        autoButton.clicked.connect(lambda: self.autoDetect())
        presetRow.addWidget(autoButton)
        newButton = QtWidgets.QToolButton()
        newButton.setText('New')
        newButton.setToolTip('Make a new, empty preset')
        newButton.clicked.connect(lambda: self.newPreset())
        presetRow.addWidget(newButton)
        moreButton = QtWidgets.QToolButton()
        moreButton.setText('...')
        moreButton.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        more = QtWidgets.QMenu(moreButton)
        more.addAction('Learn from Selection', self.learnFromSelection).setToolTip(
            'Fill the parts of this preset from terrain selected in the level')
        more.addAction('Find Slopes in Tileset', self.findSlopes)
        more.addAction('Rename...', self.renamePreset)
        more.addAction('Duplicate', self.duplicatePreset)
        more.addSeparator()
        more.addAction('Delete', self.deletePreset)
        moreButton.setMenu(more)
        presetRow.addWidget(moreButton)
        outer.addLayout(presetRow)

        # Parts
        parts = QtWidgets.QGroupBox('Terrain parts')
        partsLayout = QtWidgets.QVBoxLayout(parts)
        hint = QtWidgets.QLabel('Pick an object in the palette, then click a part to use it. '
                                'Right-click a part for more.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: palette(mid); font-size: 11px;')
        partsLayout.addWidget(hint)
        self.roleButtons = {}
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(3)
        for i, role in enumerate(OUTER_ROLES):
            button = _RoleButton(role, self)
            self.roleButtons[role] = button
            grid.addWidget(button, i // 3, i % 3)
        innerGrid = QtWidgets.QGridLayout()
        innerGrid.setSpacing(3)
        for i, role in enumerate(INNER_ROLES):
            button = _RoleButton(role, self)
            self.roleButtons[role] = button
            innerGrid.addWidget(button, i // 2, i % 2)
        gridRow = QtWidgets.QHBoxLayout()
        gridRow.addLayout(grid)
        gridRow.addSpacing(10)
        innerBox = QtWidgets.QVBoxLayout()
        innerLabel = QtWidgets.QLabel('Inner corners\n(as around a hole)')
        innerLabel.setStyleSheet('font-size: 11px;')
        innerBox.addWidget(innerLabel)
        innerBox.addLayout(innerGrid)
        innerBox.addStretch(1)
        gridRow.addLayout(innerBox)
        gridRow.addStretch(1)
        partsLayout.addLayout(gridRow)
        outer.addWidget(parts)

        # Slopes
        slopes = QtWidgets.QGroupBox('Slopes')
        slopesLayout = QtWidgets.QVBoxLayout(slopes)
        slopeGrid = QtWidgets.QGridLayout()
        slopeGrid.setSpacing(3)
        for col, text in enumerate(('Floor\nup', 'Floor\ndown', 'Ceiling\ndown', 'Ceiling\nup')):
            label = QtWidgets.QLabel(text)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet('font-size: 10px;')
            slopeGrid.addWidget(label, 0, col + 1)
        for row, step in enumerate(SLOPE_STEPS):
            label = QtWidgets.QLabel(_STEEPNESS[step])
            label.setStyleSheet('font-size: 11px;')
            slopeGrid.addWidget(label, row + 1, 0)
            for col, orient in enumerate(SLOPE_ORIENTATIONS):
                role = 'slope%s_%s' % (step, orient)
                button = _RoleButton(role, self, 38)
                self.roleButtons[role] = button
                slopeGrid.addWidget(button, row + 1, col + 1)
        slopeRow = QtWidgets.QHBoxLayout()
        slopeRow.addLayout(slopeGrid)
        slopeRow.addStretch(1)
        slopesLayout.addLayout(slopeRow)
        findButton = QtWidgets.QPushButton('Find Slopes in Tileset')
        findButton.setToolTip('Fill the slope parts with the slope objects of the fill\'s tileset')
        findButton.clicked.connect(lambda: self.findSlopes())
        slopesLayout.addWidget(findButton)
        options = QtWidgets.QFormLayout()
        self.steepness = QtWidgets.QComboBox()
        self.steepness.addItem('Follow the drag', 0)
        for step in SLOPE_STEPS:
            self.steepness.addItem(_STEEPNESS[step], step)
        self.steepness.setCurrentIndex(max(0, self.steepness.findData(setting('QuickPaintSteepness', 0))))
        self.steepness.currentIndexChanged.connect(lambda i: setSetting('QuickPaintSteepness', self.steepness.currentData()))
        options.addRow('Steepness:', self.steepness)
        self.surface = QtWidgets.QComboBox()
        self.surface.addItem('Floor (ground below)', False)
        self.surface.addItem('Ceiling (ground above)', True)
        self.surface.setCurrentIndex(1 if setting('QuickPaintCeiling', False) else 0)
        self.surface.currentIndexChanged.connect(lambda i: setSetting('QuickPaintCeiling', bool(self.surface.currentData())))
        options.addRow('Surface:', self.surface)
        slopesLayout.addLayout(options)
        self.slopeFill = QtWidgets.QComboBox()
        for fill in (SLOPE_FILL_NONE, SLOPE_FILL_STEPS, SLOPE_FILL_GROUND):
            self.slopeFill.addItem(SLOPE_FILL_NAMES[fill], fill)
        self.slopeFill.setToolTip('What is placed under a floor slope (above a ceiling slope): nothing, so you get just '
                                  'the slope at the angle you drew; ground filling the space under its steps; or that '
                                  'and on down until it meets other ground (up to %d tiles)' % FILL_DOWN_LIMIT)
        try:
            fill = int(setting('QuickPaintSlopeFill', SLOPE_FILL_NONE))
        except (TypeError, ValueError):
            fill = SLOPE_FILL_NONE
        self.slopeFill.setCurrentIndex(max(0, self.slopeFill.findData(fill)))
        self.slopeFill.currentIndexChanged.connect(lambda i: setSetting('QuickPaintSlopeFill', self.slopeFill.currentData()))
        options.addRow('Under it:', self.slopeFill)
        outer.addWidget(slopes)

        # Shapes (the Shape mode): terrain kept as an outline of points that stays editable
        shapesBox = QtWidgets.QGroupBox('Shapes')
        shapesLayout = QtWidgets.QVBoxLayout(shapesBox)
        shapeButtons = QtWidgets.QHBoxLayout()
        from . import qpshapes
        for text, tip, slot in (
                ('Delete', 'Delete the selected shape and its terrain', qpshapes.delete_selected),
                ('Re-tile', 'Place the selected shape again with this preset', qpshapes.retile_selected),
                ('Unlink', 'Stop keeping the selected shape as a shape: its objects stay as ordinary objects',
                 qpshapes.forget_selected)):
            button = QtWidgets.QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda checked=False, f=slot: f())
            shapeButtons.addWidget(button)
        shapesLayout.addLayout(shapeButtons)
        outer.addWidget(shapesBox)

        # Editing terrain that's already placed
        edit = QtWidgets.QGroupBox('Placed terrain')
        editLayout = QtWidgets.QVBoxLayout(edit)
        buttons = QtWidgets.QHBoxLayout()
        retile = QtWidgets.QPushButton('Re-tile Selection')
        retile.setToolTip('Fix the edges and corners of the selected terrain objects (and what they touch), '
                          'e.g. after moving or resizing them by hand. Ctrl+Shift+T')
        retile.clicked.connect(lambda: retile_selection(False))
        buttons.addWidget(retile)
        convert = QtWidgets.QPushButton('Convert Selection')
        convert.setToolTip('Turn the selected objects, whatever they are, into terrain of this preset')
        convert.clicked.connect(lambda: retile_selection(True))
        buttons.addWidget(convert)
        editLayout.addLayout(buttons)
        self.autoRetile = QtWidgets.QCheckBox('Re-tile terrain after moving or resizing it')
        self.autoRetile.setToolTip('While this panel is open, moving or resizing objects of this preset fixes the '
                                   'terrain where they were and where they are now, in the same undo step')
        self.autoRetile.setChecked(bool(setting('QuickPaintAutoRetile', True)))
        self.autoRetile.toggled.connect(lambda v: setSetting('QuickPaintAutoRetile', v))
        editLayout.addWidget(self.autoRetile)
        outer.addWidget(edit)

        self.help = QtWidgets.QLabel()
        self.help.setWordWrap(True)
        self.help.setStyleSheet('color: palette(mid); font-size: 11px;')
        outer.addWidget(self.help)
        self.updateHelp()

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet('font-size: 11px;')
        outer.addWidget(self.status)
        outer.addStretch(1)

        self.fillPresetBox(setting('QuickPaintPreset', None))

    # ---- presets

    def fillPresetBox(self, select=None):
        self.presetBox.blockSignals(True)
        self.presetBox.clear()
        for preset in self.presets:
            label = preset['name']
            if preset.get('tileset') and preset['tileset'] != preset['name']:
                label += '  (%s)' % preset['tileset']
            self.presetBox.addItem(label)
        index = next((i for i, p in enumerate(self.presets) if p['name'] == select), 0)
        self.presetBox.setCurrentIndex(index if self.presets else -1)
        self.presetBox.blockSignals(False)
        self.presetChanged()

    def preset(self):
        index = self.presetBox.currentIndex()
        return self.presets[index] if 0 <= index < len(self.presets) else None

    def roles(self):
        preset = self.preset()
        return preset['roles'] if preset else {}

    def presetChanged(self, *args):
        preset = self.preset()
        if preset is not None:
            setSetting('QuickPaintPreset', preset['name'])
        self.refresh()

    def _uniqueName(self, base):
        names = {p['name'] for p in self.presets}
        if base not in names:
            return base
        n = 2
        while '%s %d' % (base, n) in names:
            n += 1
        return '%s %d' % (base, n)

    def _save(self, select=None):
        save_presets(self.presets)
        self.fillPresetBox(select if select is not None else (self.preset() or {}).get('name'))

    def newPreset(self, roles=None, name=None, tileset=None):
        if name is None:
            name, ok = QtWidgets.QInputDialog.getText(self, 'New Quick Paint Preset', 'Name:',
                                                      text=self._uniqueName('Terrain'))
            if not ok or not name.strip():
                return None
        preset = {'name': self._uniqueName(name.strip()), 'roles': dict(roles or {})}
        if tileset:
            preset['tileset'] = tileset
        self.presets.append(preset)
        self._save(preset['name'])
        return preset

    def renamePreset(self):
        preset = self.preset()
        if preset is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, 'Rename Preset', 'Name:', text=preset['name'])
        if ok and name.strip() and name.strip() != preset['name']:
            preset['name'] = self._uniqueName(name.strip())
            self._save(preset['name'])

    def duplicatePreset(self):
        preset = self.preset()
        if preset is not None:
            copy = dict(preset, name=self._uniqueName(preset['name']), roles=dict(preset['roles']))
            self.presets.append(copy)
            self._save(copy['name'])

    def deletePreset(self):
        preset = self.preset()
        if preset is None:
            return
        if QtWidgets.QMessageBox.question(self, 'Delete Preset', 'Delete the preset "%s"?' % preset['name'],
                                          QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                          QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return
        self.presets.remove(preset)
        save_presets(self.presets)
        self.fillPresetBox()

    def _ensurePreset(self):
        if self.preset() is None:
            self.newPreset(name='Terrain')
        return self.preset()

    def _noteTileset(self, preset):
        slot = preset_slot(preset['roles'])
        name = area_tileset(slot)
        if name:
            preset['tileset'] = name

    def assign(self, role, key):
        preset = self._ensurePreset()
        if key is None:
            preset['roles'].pop(role, None)
        else:
            definition = global_def(tuple(key))
            if role in SLOPE_ROLES and not is_diagonal(definition):
                self.say('that object isn\'t a slope; pick a slope object for this part.')
                return
            if role not in SLOPE_ROLES and is_diagonal(definition):
                self.say('that object is a slope; put it in the Slopes box.')
                return
            if gametilesets.is_ref(key):
                preset['roles'][role] = list(key)
            else:
                preset['roles'][role] = [int(key[0]), int(key[1])]
            self._noteTileset(preset)
        self._save()

    def assignPicked(self, role):
        picked = globals.CurrentObject is not None and globals.CurrentObject >= 0
        if picked and globals.CurrentPaintType == 10:
            # The Game tab: the part names the game object, which is copied into a level's
            # tilesets when it's painted with (so the preset works in any level)
            ref = gametilesets.ref_for(globals.CurrentObject)
            if ref is not None:
                self.assign(role, ref)
                return
        if picked and globals.CurrentPaintType in (0, 1, 2, 3):
            self.assign(role, (globals.CurrentPaintType, globals.CurrentObject))
        else:
            self.say('Pick an object in the Objects palette (Main, Local or Game) first, then click the part to use it for.')

    def assignSelected(self, role):
        from .items import ObjectItem
        selected = [i for i in globals.mainWindow.scene.selectedItems() if isinstance(i, ObjectItem)]
        if len(selected) != 1:
            self.say('Select one object in the level to use it for this part.')
            return
        self.assign(role, obj_key(selected[0]))

    def learnFromSelection(self):
        from .items import ObjectItem
        selected = [i for i in globals.mainWindow.scene.selectedItems()
                    if isinstance(i, ObjectItem) and i.tileset in (0, 1, 2, 3)]
        if not selected:
            self.say('Select a piece of terrain in the level (all its objects) first.')
            return
        slots = Counter(obj.tileset for obj in selected)
        roles = learn_roles(selected, slot=slots.most_common(1)[0][0])
        preset = self._ensurePreset()
        preset['roles'].update(roles)
        self._noteTileset(preset)
        self._save()
        self.say('learned %d part(s) from the selection.' % len(roles))

    def _detectSlot(self):
        if globals.Area is None:
            return None
        counts = Counter(obj.tileset for layer in globals.Area.layers for obj in layer if obj.tileset in (1, 2, 3))
        picked = globals.CurrentPaintType if globals.CurrentPaintType in (1, 2, 3) else None
        if picked is not None and counts[picked]:
            return picked
        if counts:
            return counts.most_common(1)[0][0]
        return picked or (1 if area_tileset(1) else None)

    def autoDetect(self, slot=None):
        """Auto-detect: makes (or updates) the preset for this area's tileset from the level."""
        slot = slot or self._detectSlot()
        if slot is None or not area_tileset(slot):
            self.say('this area has no tileset in slots 1 to 3 to make a preset for.')
            return None
        roles = learn_from_layers(globals.Area.layers, slot)
        if object_for(roles, 'center') is None:
            self.say('this area has no terrain of tileset %s to learn from; pick the parts by hand, or select terrain '
                     'in another level and use Learn from Selection.' % area_tileset(slot))
            return None
        name = area_tileset(slot)
        preset = next((p for p in self.presets if p.get('tileset') == name and p['name'] == name), None)
        if preset is None:
            preset = self.newPreset(roles, name=name, tileset=name)
        else:
            preset['roles'] = roles
            self._save(preset['name'])
        slopes = sum(1 for r in roles if r in SLOPE_ROLES)
        self.say('made the preset "%s": %d terrain part(s) and %d slope(s).' % (
            preset['name'], len(roles) - slopes, slopes))
        return preset

    def findSlopes(self):
        preset = self._ensurePreset()
        center = object_for(preset['roles'], 'center')
        if center is not None and gametilesets.is_ref(center):
            entries = gametilesets.entries_for_key(center[1]) or []
            found = find_game_slopes(center[1], entries)
            if not found:
                self.say('%s has no slope objects.' % gametilesets.ref_label(center).split(',')[0])
                return
        else:
            slot = preset_slot(preset['roles']) or (globals.CurrentPaintType if globals.CurrentPaintType in (1, 2, 3) else 1)
            found = find_slopes(slot)
            if not found:
                self.say('tileset %s has no slope objects.' % (area_tileset(slot) or 'Pa%d' % slot))
                return
        for role in SLOPE_ROLES:
            preset['roles'].pop(role, None)
        preset['roles'].update(found)
        self._save()
        self.say('found %d slope object(s).' % len(found))

    # ---- state

    def say(self, text):
        self.status.setText(text)
        if globals.mainWindow is not None and text:
            globals.mainWindow.statusBar().showMessage('Quick Paint: ' + text, 6000)

    def tilesetsChanged(self):
        """A level or area with other tilesets was opened: pick the preset made for them, if any."""
        if globals.Area is None:
            return
        names = tuple(area_tileset(slot) for slot in range(4))
        if names == self._seenTilesets:
            return
        self._seenTilesets = names
        current = self.preset()
        if current is not None and not mismatched(current):
            return
        match = next((p for p in self.presets if p.get('tileset') in names[1:] and p.get('tileset')), None)
        if match is not None:
            self.fillPresetBox(match['name'])
            if current is not None:
                self.say('this level uses tileset %s, so Quick Paint switched to its preset "%s" ("%s" is for %s).'
                         % (match['tileset'], match['name'], current['name'], current.get('tileset')))
            return
        if current is None:
            return
        # A preset made for another tileset would paint with whatever objects have its numbers
        # here: learn one for this tileset from the level instead (the old one stays in the list)
        made = self.autoDetect()
        if made is not None:
            self.fillPresetBox(made['name'])
            self.say('this level uses tileset %s, not %s: Quick Paint made the preset "%s" for it from the level '
                     '("%s" is still in the list).' % (made.get('tileset'), current.get('tileset'), made['name'],
                                                       current['name']))

    def refresh(self):
        """Redraws the parts (after a preset or the tilesets change)."""
        roles = self.roles()
        missing = []
        for role, button in self.roleButtons.items():
            key = tuple(roles[role]) if roles.get(role) else None
            if key is None:
                diagram = role_diagram(role, button.iconSize().width())
                faded = QtGui.QPixmap(diagram.size())
                faded.fill(Qt.transparent)
                painter = QtGui.QPainter(faded)
                painter.setOpacity(0.5)
                painter.drawPixmap(0, 0, diagram)
                painter.end()
                button.setIcon(QtGui.QIcon(faded))
                fallback = object_for(roles, role) if role not in SLOPE_ROLES else None
                button.setToolTip('<b>%s</b><br>Not set%s' % (
                    ROLE_NAMES[role], ': uses the fill' if fallback and role != 'center' else ''))
            else:
                button.setIcon(QtGui.QIcon(object_pixmap(key, button.iconSize().width())))
                exists = _object_exists(key)
                if not exists:
                    missing.append(ROLE_NAMES[role].split('<br>')[0])
                if gametilesets.is_ref(key):
                    where = 'Game tileset %s<br>(copied into the level\'s tilesets when you paint with it)' % (
                        gametilesets.ref_label(key))
                else:
                    where = 'Tileset Pa%d, object %d' % (key[0], key[1])
                button.setToolTip('<b>%s</b><br>%s%s' % (
                    ROLE_NAMES[role], where, '' if exists else '<br><b>Not in the current tileset</b>'))
            button.setText('')
            button.setStyleSheet('QToolButton { border: %s; border-radius: 5px; }' % (
                '2px solid rgb(255, 140, 0)' if role == 'center' else '1px solid palette(mid)'))
        preset = self.preset()
        made_for = preset.get('tileset') if preset else None
        slot = preset_slot(roles)
        if object_for(roles, 'center') is None:
            self.status.setText('Set the <b>Fill</b> part (in the middle) to start painting, or press '
                                '<b>Auto-detect</b> to make a preset from this level.')
        elif made_for and slot is not None and area_tileset(slot) and area_tileset(slot) != made_for:
            self.status.setText('This preset was made for %s; this area uses %s in that slot, whose objects may be '
                                'different.' % (made_for, area_tileset(slot)))
        elif missing:
            self.status.setText('These parts use objects the current tilesets don\'t have: ' + ', '.join(missing))
        else:
            self.status.setText('')

    def ready(self, mode=None, quiet=False):
        """Whether painting can start, saying why not (unless quiet)."""
        say = (lambda text: None) if quiet else self.say
        roles = self.roles()
        center = object_for(roles, 'center')
        if center is None:
            say('give the preset a Fill object first (the part in the middle), or press Auto-detect.')
            return False
        if not _object_exists(center):
            say('the Fill object of this preset isn\'t in the current tilesets.')
            return False
        if mode == MODE_SLOPE and not any(roles.get(r) for r in SLOPE_ROLES):
            say('the preset has no slopes yet: press Find Slopes in Tileset.')
            return False
        return True

    def updateHelp(self):
        """The mouse buttons in the tooltips and help follow Preferences > Editor > Legacy mouse controls."""
        if globals.LegacyMouseControls:
            tips = {MODE_OFF: 'Click the level as usual',
                    MODE_PAINT: 'Right drag paints terrain, Shift + right drag fills a rectangle. Left click selects as usual',
                    MODE_SLOPE: 'Right drag a line along the ground\'s surface, or right click points one after another: '
                                'each part of the line becomes a slope at the closest angle, joined at the dots',
                    MODE_ERASE: 'Right drag erases terrain (and slopes), Shift + right drag clears a rectangle',
                    MODE_SHAPE: 'Right click points around a shape (flat, straight up or along a slope) and right click '
                                'the first point to fill it. Drag its points or its inside to change it afterwards'}
            shape = ('<b>Shape</b>: right click nodes around a shape, then the first node again (or Enter, Esc or '
                     'double-click) to fill it with terrain and slopes. Then drag a node (left or right) anywhere to '
                     'reshape it (sides at other angles are built from the nearest slopes), drag inside to move it. '
                     '<b>Add a node</b>: drag the + in the middle of a side, or double-click a side. <b>Remove a node</b>: '
                     'click it and press Delete, double-click it, or Shift + click it. <b>Delete a shape</b>: click inside '
                     'it and press Delete. ')
            text = (shape + '<b>Paint</b>: right drag paints, Shift + right drag fills a rectangle. <b>Erase</b>: right drag '
                    'erases. <b>Slope</b>: right drag a line along the ground\'s surface, or right click point after point: '
                    'each part becomes a slope at the closest angle (with flat ground for level parts), joined at the dots. '
                    'Start on a dot to go on from it; double-click or Esc ends the line. Left click selects and moves '
                    'things as usual (Legacy mouse controls).')
        else:
            tips = {MODE_OFF: 'Click the level as usual',
                    MODE_PAINT: 'Left drag paints terrain, right drag erases it, Shift + drag fills a rectangle',
                    MODE_SLOPE: 'Drag a line along the ground\'s surface, or click points one after another: each part of '
                                'the line becomes a slope at the closest angle, joined at the dots. Right drag erases',
                    MODE_ERASE: 'Left drag erases terrain (and slopes), right drag paints it',
                    MODE_SHAPE: 'Click points around a shape (flat, straight up or along a slope) and click the first point '
                                'to fill it. Drag its points or its inside to change it afterwards'}
            shape = ('<b>Shape</b>: click nodes around a shape, then the first node again (or Enter, Esc or '
                     'double-click) to fill it with terrain and slopes. Then drag a node anywhere to reshape it (sides at '
                     'other angles are built from the nearest slopes), drag inside to move it. <b>Add a node</b>: drag the '
                     '+ in the middle of a side, or double-click a side. <b>Remove a node</b>: click it and press Delete, '
                     'double-click it, or right click it. <b>Delete a shape</b>: click inside it and press Delete. ')
            text = (shape + '<b>Paint</b>: left drag paints, right drag erases, Shift + drag fills or clears a rectangle. '
                    '<b>Slope</b>: drag a line along the ground\'s surface, or click point after point: each part becomes '
                    'a slope at the closest angle (with flat ground for level parts), joined at the dots. Start on a dot '
                    'to go on from it; double-click or Esc ends the line.')
        for mode, button in self.modeButtons.items():
            button.setToolTip(tips[mode])
        self.help.setText(text + ' The level shows the result while you drag; each stroke is one Undo. Esc stops.')

    def showEvent(self, event):
        self.updateHelp()
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self.applyPendingMode)

    def applyPendingMode(self):
        """Goes back to the mode last used, once the panel shows and the preset can paint here."""
        if self.pendingMode and self.isVisible() and self.mode == MODE_OFF and globals.Area is not None \
                and self.ready(self.pendingMode, quiet=True):
            self.setMode(self.pendingMode)

    def slopeOptions(self):
        return self.steepness.currentData() or 0, bool(self.surface.currentData()), self.slopeFill.currentData() or 0

    def setMode(self, mode):
        global _stroke
        self.mode = mode
        self.pendingMode = None
        button = self.modeButtons.get(mode)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self.offHint.setVisible(mode == MODE_OFF)
        dock = getattr(globals.mainWindow, 'quickPaintDock', None)
        if mode != MODE_OFF or dock is None or dock.isVisible():  # (closing the panel isn't choosing Off)
            setSetting('QuickPaintMode', mode)
        _stroke = None
        _preview.clear()
        cancel()
        if mode != MODE_OFF:
            from . import partsbar
            if partsbar.isArmed():
                partsbar.disarm()
            dock = getattr(globals.mainWindow, 'quickPaintDock', None)
            if dock is not None and not dock.isVisible():
                dock.show()
        view = getattr(globals.mainWindow, 'view', None)
        if view is not None:
            if mode == MODE_OFF:
                view.viewport().unsetCursor()
            else:
                view.viewport().setCursor(Qt.CrossCursor)
            view.viewport().update()


_panel = None
_stroke = None
_hover = None  # tile under the mouse while painting is on


def panel():
    return _panel


def isActive():
    return _panel is not None and _panel.mode != MODE_OFF


def setMode(mode):
    if _panel is not None:
        _panel.setMode(mode)


def panelOpened():
    """The panel was opened from the View menu: paint straight away (in the mode last used), if the preset can."""
    if _panel is None or _panel.mode != MODE_OFF:
        return
    mode = _panel.pendingMode or MODE_PAINT
    if _panel.ready(mode, quiet=True):
        _panel.setMode(mode)


def strokeButtons():
    """
    The mouse buttons that draw strokes: left (the mode) and right (the opposite: erase while
    painting); with Legacy mouse controls, where right click places things, right only (as in
    Miyamoto's Quick Paint), so left click still selects.
    """
    return (Qt.RightButton,) if globals.LegacyMouseControls else (Qt.LeftButton, Qt.RightButton)


def shapeButton(view, event):
    """
    Whether a click goes to Shape mode: left or right click; with Legacy mouse controls (where
    left click selects) a left click only on a shape or while one is drawn, so nodes can be dragged.
    """
    from . import qpshapes
    if event.button() in strokeButtons():
        return True
    return event.button() == Qt.LeftButton and qpshapes.claims(view, event)


def refreshPanel():
    if _panel is not None:
        _panel.tilesetsChanged()
        _panel.refresh()
        _panel.applyPendingMode()  # a level is open now, so the mode last used can come back


def autoRetileEnabled():
    return (_panel is not None and _panel.isVisible() and _panel.autoRetile.isChecked()
            and object_for(_panel.roles(), 'center') is not None)


# ------------------------------------------------------------------------------- whole-object tools

def retile_selection(convert=False):
    """
    Re-tile Selection (convert=False): fixes the selected terrain objects and what they touch.
    Convert Selection: turns all selected objects into terrain of the preset.
    """
    from .items import ObjectItem
    if _panel is None or not _panel.ready():
        return
    roles = planning_roles(_panel.roles())
    keys = {tuple(v) for v in roles.values() if v}
    selected = [i for i in globals.mainWindow.scene.selectedItems() if isinstance(i, ObjectItem)]
    if not convert:
        selected = [obj for obj in selected if obj_key(obj) in keys]
    if not selected:
        _panel.say('select some terrain objects of this preset first.' if not convert
                   else 'select the objects to turn into terrain first.')
        return
    changed = 0
    by_layer = defaultdict(list)
    for obj in selected:
        by_layer[obj.layer].append(obj)
    globals.UndoManager.begin_compound('Convert to Terrain' if convert else 'Re-tile Terrain')
    try:
        for layer_idx, objs in by_layer.items():
            regions = set()
            for obj in objs:
                regions |= obj_cells(obj)
            changed += apply_terrain(layer_idx, roles, regions=regions, convert=objs if convert else (),
                                     description='Convert to Terrain' if convert else 'Re-tile Terrain')
    finally:
        globals.UndoManager.end_compound()
    _panel.say('nothing to change: the terrain is already tiled.' if not changed else '')


def retile_after_edit(changes):
    """
    After objects were moved or resized ([(item, old geometry, new geometry)]): re-tiles
    the preset's terrain where they were and where they are. Returns whether anything changed.
    """
    from .items import ObjectItem
    if not autoRetileEnabled():
        return False
    roles = planning_roles(_panel.roles())
    keys = {tuple(v) for v in roles.values() if v}
    by_layer = defaultdict(set)
    for item, old, new in changes:
        if not isinstance(item, ObjectItem) or obj_key(item) not in keys:
            continue
        w, h = (old[2], old[3]) if len(old) >= 4 else (item.width, item.height)
        by_layer[item.layer] |= rect_cells(old[0], old[1], w, h) | obj_cells(item)
    changed = 0
    for layer_idx, cells in by_layer.items():
        changed += apply_terrain(layer_idx, roles, regions=cells, description='Re-tile Terrain')
    return bool(changed)


def wants_retile(changes):
    """Whether retile_after_edit would look at these changes (so they can share one undo step)."""
    from .items import ObjectItem
    if not autoRetileEnabled():
        return False
    keys = {tuple(v) for v in planning_roles(_panel.roles()).values() if v}
    return any(isinstance(item, ObjectItem) and obj_key(item) in keys for item, _, _ in changes)


# ------------------------------------------------------------------------------- the live preview

class _Preview:
    """
    What a stroke will do, shown while it's drawn: the objects it removes are hidden and the
    ones it places are drawn over the level, so it looks as it will once the button is let go.
    """

    def __init__(self):
        self.hidden = set()  # objects the level view leaves out (LevelScene.drawBackground)
        self.add = []
        self.cache = {}

    def show(self, remove, add):
        keep = set(remove)
        changed = [obj for obj in self.hidden if obj not in keep] + [obj for obj in remove if obj not in self.hidden]
        for obj in list(self.hidden):
            if obj not in keep:
                self._restore(obj)
        for obj in remove:
            if obj not in self.hidden:
                obj.previewHidden = True
                self.hidden.add(obj)
        self.add = list(add)
        self._redraw(changed)

    def _restore(self, obj):
        self.hidden.discard(obj)
        obj.previewHidden = False

    def _redraw(self, objects):
        """The level's tiles are drawn as its background: draw those of these objects again."""
        mw = globals.mainWindow
        scene = getattr(mw, 'scene', None)
        if not objects or scene is None or not hasattr(scene, 'invalidate'):
            return
        tile = globals.TileWidth
        area = QtCore.QRectF()
        for obj in objects:
            area = area.united(QtCore.QRectF(obj.objx * tile, obj.objy * tile, obj.width * tile, obj.height * tile))
        scene.invalidate(area, QtWidgets.QGraphicsScene.BackgroundLayer)

    def clear(self):
        hidden = list(self.hidden)
        for obj in hidden:
            self._restore(obj)
        self.add = []
        self.cache.clear()
        self._redraw(hidden)

    def tiles(self, rect):
        from .tileset import RenderObject
        x, y, w, h, (ts, num) = rect
        key = (ts, num, w, h)
        tiles = self.cache.get(key)
        if tiles is None:
            tiles = self.cache[key] = RenderObject(ts, num, w, h)
        return tiles


_preview = _Preview()


# ------------------------------------------------------------------------------- the level view

class _Stroke:
    def __init__(self, mode, layer_idx, start, rect, brush, roles, slope_options=(0, False, SLOPE_FILL_NONE)):
        self.mode = mode
        self.layer_idx = layer_idx
        self.start = self.last = start
        self.rect = rect
        self.brush = brush
        self.cells = set()
        self.roles = roles
        self.slope_options = slope_options
        self.planner = None
        self.result = None  # (remove, add)
        self.corners = [start]  # Slope mode: where the line's pieces really end
        self.pressed = start
        self.onDot = False
        self.dragging = False
        self.extend(start)

    def brushAt(self, cell):
        off = (self.brush - 1) // 2
        return {(cell[0] - off + i, cell[1] - off + j) for i in range(self.brush) for j in range(self.brush)}

    def extend(self, cell):
        if self.mode == MODE_SLOPE:
            self.last = cell
            return
        if self.rect:
            (x0, y0), (x1, y1) = self.start, cell
            self.cells = rect_cells(min(x0, x1), min(y0, y1), abs(x1 - x0) + 1, abs(y1 - y0) + 1)
        else:
            # Every tile between the last position and this one, so fast drags leave no gaps
            (x0, y0), (x1, y1) = self.last, cell
            steps = max(abs(x1 - x0), abs(y1 - y0), 1)
            for i in range(steps + 1):
                point = (round(x0 + (x1 - x0) * i / steps), round(y0 + (y1 - y0) * i / steps))
                self.cells |= self.brushAt(point)
        self.cells = {c for c in self.cells if c[0] >= 0 and c[1] >= 0}
        self.last = cell

    def plan(self, objects=None):
        """(remove, add) for the stroke so far; objects defaults to the stroke's layer."""
        if self.planner is None:
            if objects is None:
                objects = globals.Area.layers[self.layer_idx]
            self.planner = TerrainPlanner(objects, self.roles)
        if self.mode == MODE_SLOPE:
            steepness, ceiling, fill = self.slope_options
            planned = self.planner.planChain(self.start, [self.last], steepness, ceiling, fill)
            self.result = (planned[0], planned[1]) if planned else ([], [])
            self.corners = planned[2] if planned else [self.start]
        elif self.mode == MODE_PAINT:
            self.result = self.planner.plan(paint=self.cells)
        else:
            self.result = self.planner.plan(erase=self.cells)
        return self.result


def _cellAt(view, pos):
    point = view.mapToScene(pos)
    return max(0, int(point.x() // globals.TileWidth)), max(0, int(point.y() // globals.TileWidth))


class _Chain:
    """
    The dots of the line of slopes being drawn in Slope mode: where each piece starts and ends,
    to go on from. A dot goes when the piece that made it is undone.
    """

    REACH = 0.75  # tiles: pressing this close to a dot starts there

    def __init__(self):
        self.dots = []  # [(corner, undo steps when it was made)]
        self.active = None  # the dot a click goes on from
        self.area = None

    @staticmethod
    def undoCount():
        manager = getattr(globals, 'UndoManager', None)
        return len(getattr(manager, 'undo_stack', None) or ())

    def vertices(self):
        return [v for v, _ in self.dots]

    def prune(self):
        if self.area is not globals.Area:
            self.clear()
            self.area = globals.Area
        n = self.undoCount()
        self.dots = [(v, made) for v, made in self.dots if made <= n]
        if self.active not in self.vertices():
            self.active = self.dots[-1][0] if self.dots else None

    def add(self, corner, made=None):
        if corner not in self.vertices():
            self.dots.append((corner, self.undoCount() if made is None else made))
            del self.dots[:-200]
        self.area = globals.Area

    def near(self, point):
        best = None
        for v in self.vertices():
            d = math.hypot(v[0] - point[0], v[1] - point[1])
            if d <= self.REACH and (best is None or d < best[0]):
                best = (d, v)
        return best[1] if best else None

    def clear(self):
        self.dots = []
        self.active = None


_chain = _Chain()
_ghost = None  # Slope mode, between clicks: (corners, add, mouse corner) a click would place
_ghostPlanner = None
_hoverCorner = None


def _cornerAt(view, pos):
    """The tile grid corner nearest a point of the view, or a dot of the line near it: (corner, on a dot)."""
    point = view.mapToScene(pos)
    x, y = point.x() / float(globals.TileWidth), point.y() / float(globals.TileWidth)
    dot = _chain.near((x, y))
    if dot is not None:
        return dot, True
    return (max(0, int(round(x))), max(0, int(round(y)))), False


def _updateGhost(corner):
    """What a click at this corner would add to the line (shown faintly while the mouse moves)."""
    global _ghost, _ghostPlanner
    _ghost = None
    if _panel is None or _panel.mode != MODE_SLOPE or _stroke is not None or globals.Area is None:
        return
    _chain.prune()
    if _chain.active is None or corner is None or corner == _chain.active:
        return
    roles = planning_roles(_panel.roles())
    state = (globals.CurrentLayer, _chain.undoCount(), id(globals.Area))
    if _ghostPlanner is None or _ghostPlanner[0] != state or _ghostPlanner[2] != roles:
        _ghostPlanner = (state, TerrainPlanner(globals.Area.layers[globals.CurrentLayer], roles), roles)
    steepness, ceiling, fill = _panel.slopeOptions()
    try:
        planned = _ghostPlanner[1].planChain(_chain.active, [corner], steepness, ceiling, fill)
    except Exception:
        planned = None
    _ghost = (planned[2], planned[1], corner) if planned else ([_chain.active], [], corner)


def cancel():
    """Esc: ends the line of slopes or the shape being drawn. Returns whether there was one."""
    global _stroke, _ghost
    from . import qpshapes
    had = _stroke is not None or bool(_chain.dots)
    had = qpshapes.cancel() or had
    _stroke = None
    _ghost = None
    _preview.clear()
    _chain.clear()
    view = getattr(globals.mainWindow, 'view', None)
    if had and view is not None:
        view.viewport().update()
    return had


def _updatePreview(view):
    try:
        remove, add = _stroke.plan()
    except Exception:
        import traceback
        traceback.print_exc()
        remove, add = [], []
    _preview.show(remove, add)
    view.viewport().update()


def handlePress(view, event):
    """Starts a stroke if Quick Paint is on. Returns whether the press was used."""
    global _stroke
    if not isActive() or globals.Area is None:
        return False
    button = event.button()
    modifiers = QtWidgets.QApplication.keyboardModifiers()
    if button == Qt.RightButton and modifiers & Qt.ControlModifier:
        return False  # the zone menu
    mode = _panel.mode
    if mode == MODE_SHAPE:
        from . import qpshapes
        if event.buttons() != button or not shapeButton(view, event):
            return False
        event.accept()
        return qpshapes.press(view, event) if _panel.ready(mode) else True
    if button not in strokeButtons() or event.buttons() != button:
        return False
    event.accept()
    if button == Qt.RightButton and not globals.LegacyMouseControls:
        mode = MODE_PAINT if mode == MODE_ERASE else MODE_ERASE
    if not _panel.ready(mode):
        return True
    _preview.clear()
    global _ghost
    _ghost = None
    roles = planning_roles(_panel.roles())
    if mode == MODE_SLOPE:
        _chain.prune()
        corner, onDot = _cornerAt(view, event.pos())
        _stroke = _Stroke(mode, globals.CurrentLayer, corner, False, 1, roles, _panel.slopeOptions())
        _stroke.onDot = onDot
        if not onDot and _chain.active is not None:
            _stroke.start = _chain.active  # a click goes on from the last dot (a drag starts here instead)
    else:
        _stroke = _Stroke(mode, globals.CurrentLayer, _cellAt(view, event.pos()),
                          bool(modifiers & Qt.ShiftModifier), _panel.brush.value(), roles, _panel.slopeOptions())
    _updatePreview(view)
    return True


def handleDoubleClick(view, event):
    """
    A double-click while Quick Paint is on: in Slope mode it ends the line (the first click
    already added its point); otherwise it paints like a press. Returns whether it was used.
    """
    if not isActive() or globals.Area is None:
        return False
    if _panel.mode == MODE_SHAPE:
        from . import qpshapes
        return qpshapes.double_click(view, event) if shapeButton(view, event) else False
    if event.button() not in strokeButtons():
        return False
    if _panel.mode == MODE_SLOPE and not (event.button() == Qt.RightButton and not globals.LegacyMouseControls):
        event.accept()
        cancel()
        return True
    return handlePress(view, event)


def handleMove(view, event):
    """Extends the stroke and moves the brush outline. Returns whether the move was used
    (only while a stroke is drawn: otherwise the view still scrolls, shows positions...)."""
    global _hover
    if not isActive():
        if _hover is not None:
            _hover = None
            view.viewport().update()
        return False
    if _panel.mode == MODE_SHAPE:
        from . import qpshapes
        return qpshapes.move(view, event)
    global _hoverCorner
    if _stroke is not None and _stroke.mode == MODE_SLOPE:
        corner, _ = _cornerAt(view, event.pos())
        if corner != _stroke.last:
            if not _stroke.dragging and corner != _stroke.pressed:
                _stroke.dragging = True
                _stroke.start = _stroke.pressed  # dragging draws a line from where it was pressed
            _stroke.last = corner
            _updatePreview(view)
        _hoverCorner = corner
        return True
    cell = _cellAt(view, event.pos())
    if _stroke is not None and cell != _stroke.last:
        _stroke.extend(cell)
        _updatePreview(view)
    if _panel.mode == MODE_SLOPE and _stroke is None:
        corner, _ = _cornerAt(view, event.pos())
        if corner != _hoverCorner:
            _hoverCorner = corner
            _updateGhost(corner)
            view.viewport().update()
    if cell != _hover:
        _hover = cell
        view.viewport().update()
    view.viewport().setCursor(Qt.CrossCursor)
    return _stroke is not None


def handleRelease(view, event):
    global _stroke
    if isActive() and _panel.mode == MODE_SHAPE:
        from . import qpshapes
        return qpshapes.release(view, event) if (qpshapes._s.drag is not None or shapeButton(view, event)) else False
    if _stroke is None:
        return isActive() and event.button() in strokeButtons()
    stroke, _stroke = _stroke, None
    event.accept()
    remove, add = stroke.result if stroke.result is not None else stroke.plan()
    _preview.clear()
    if stroke.mode == MODE_SLOPE:
        _finishSlope(stroke, remove, add)
        _updateGhost(_hoverCorner)
        view.viewport().update()
        return True
    description = {MODE_PAINT: 'Quick Paint', MODE_ERASE: 'Quick Paint Erase'}
    apply_plan(stroke.layer_idx, remove, add, description[stroke.mode])
    view.viewport().update()
    return True


def _finishSlope(stroke, remove, add):
    """Places a piece of the line of slopes and moves its dots on."""
    before = _chain.undoCount()
    placed = apply_plan(stroke.layer_idx, remove, add, 'Quick Paint Slope') if (remove or add) else 0
    if placed:
        _chain.add(stroke.start, before)
        _chain.add(stroke.corners[-1])
        _chain.active = stroke.corners[-1]
        if stroke.corners[-1] != stroke.last:
            _panel.say('the line ends at the dot: that\'s as far as the nearest slope angle goes.')
        else:
            _panel.say('')
    elif stroke.dragging:
        _panel.say('drag up or down as well as across to draw a slope (the preset needs a slope that goes that way).')
    else:
        # A click that adds nothing: a dot to start a line from (or the dot clicked)
        if stroke.start != stroke.pressed and not stroke.onDot:
            _panel.say('no slope of the preset goes that way from the last dot, so a new line starts here.')
        _chain.add(stroke.pressed)
        _chain.active = stroke.pressed


def handleLeave(view):
    global _hover, _hoverCorner, _ghost
    from . import qpshapes
    qpshapes.leave(view)
    if _hover is not None or _ghost is not None or _hoverCorner is not None:
        _hover = _hoverCorner = _ghost = None
        view.viewport().update()


def _drawPlanned(painter, planned, tile, visible):
    """Draws a planned object (x, y, w, h, key), a level object or a game object not copied yet."""
    x, y, w, h, key = planned[:5]
    if gametilesets.is_ref(key):
        entry = gametilesets.entry_for(key)
        if entry is not None:
            pm = gametilesets.entry_pixmap(entry, w, h, fullslope=False)
            painter.drawPixmap(QtCore.QRectF(x * tile, y * tile, w * tile, h * tile), pm, QtCore.QRectF(pm.rect()))
        return
    _draw_tiles(painter, _preview.tiles(planned), x, y, tile, visible)


def _drawDot(painter, corner, tile, active=False, hollow=False):
    r = max(4.0, tile * (0.2 if active else 0.15))
    center = QtCore.QPointF(corner[0] * tile, corner[1] * tile)
    pen = QtGui.QPen(QtGui.QColor(255, 140, 0) if hollow or active else QtGui.QColor(40, 20, 0), 2)
    pen.setCosmetic(True)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush if hollow else (QtGui.QColor(255, 255, 255) if active else QtGui.QColor(255, 140, 0)))
    painter.drawEllipse(center, r, r)


def drawOverlay(painter, rect):
    """The result of the stroke being drawn (or of a click, faintly, in Slope mode), the line's dots, or the brush."""
    if not isActive():
        return
    tile = globals.TileWidth
    painter.save()
    try:
        left, top = int(rect.left() // tile) - 1, int(rect.top() // tile) - 1
        right, bottom = int(rect.right() // tile) + 1, int(rect.bottom() // tile) + 1
        visible = lambda x, y: left <= x <= right and top <= y <= bottom

        def tiles(add):
            for planned in add:
                x, y, w, h = planned[:4]
                if x > right or y > bottom or x + w < left or y + h < top:
                    continue
                _drawPlanned(painter, planned, tile, visible)

        if _panel.mode == MODE_SHAPE:
            from . import qpshapes
            qpshapes.draw(painter, rect, tile, tiles)
            return

        dashed = QtGui.QPen(QtGui.QColor(255, 140, 0, 220), 2, Qt.DashLine)
        dashed.setCosmetic(True)
        slope_mode = _panel.mode == MODE_SLOPE

        if _stroke is not None:
            tiles(_preview.add)
            if _stroke.mode == MODE_ERASE:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QtGui.QColor(220, 40, 40, 45))
                for (x, y) in _stroke.cells:
                    if visible(x, y):
                        painter.drawRect(QtCore.QRectF(x * tile, y * tile, tile, tile))
            if _stroke.mode == MODE_SLOPE:
                painter.setPen(dashed)
                painter.setBrush(Qt.NoBrush)
                (x0, y0), (x1, y1) = _stroke.start, _stroke.last
                painter.drawLine(QtCore.QPointF(x0 * tile, y0 * tile), QtCore.QPointF(x1 * tile, y1 * tile))
                if _stroke.corners[-1] != _stroke.start:
                    _drawDot(painter, _stroke.corners[-1], tile, hollow=True)
        elif slope_mode and _ghost is not None:
            corners, add, mouse = _ghost
            painter.setOpacity(0.55)
            tiles(add)
            painter.setOpacity(1.0)
            painter.setPen(dashed)
            painter.setBrush(Qt.NoBrush)
            a = _chain.active
            painter.drawLine(QtCore.QPointF(a[0] * tile, a[1] * tile), QtCore.QPointF(mouse[0] * tile, mouse[1] * tile))
            if corners[-1] != a:
                _drawDot(painter, corners[-1], tile, hollow=True)
        elif not slope_mode and _hover is not None:
            n = _panel.brush.value()
            off = (n - 1) // 2
            pen = QtGui.QPen(QtGui.QColor(220, 40, 40) if _panel.mode == MODE_ERASE else QtGui.QColor(255, 140, 0), 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QtCore.QRectF((_hover[0] - off) * tile, (_hover[1] - off) * tile, n * tile, n * tile))

        if slope_mode:
            _chain.prune()
            for corner in _chain.vertices():
                _drawDot(painter, corner, tile, active=corner == _chain.active)
            if _stroke is None and _hoverCorner is not None and _hoverCorner not in _chain.vertices():
                _drawDot(painter, _hoverCorner, tile, hollow=True)
    finally:
        painter.restore()
