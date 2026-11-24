#!/usr/bin/python
# -*- coding: utf-8 -*-

# Yaz0moto - a Mario level editor
# This file is part of Yaz0moto, licensed under the GNU General Public License v3.

"""
Quick Paint's Shape mode: terrain drawn as an outline of points, like the ground "rails" of
Fushigi (the Super Mario Bros. Wonder editor), made for the tile grid of NSMBU / Deluxe.

Click points around the shape (each side runs flat, straight up or down, or along a slope
angle the preset has) and click the first point again to close it. The inside is filled with
the preset's terrain, with its edges and corners, and every sloped side gets the slope object
(a floor slope on top, a ceiling slope underneath). The shape stays editable: drag a point to
move it, drag inside it to move the whole shape, double-click a side to add a point there,
Shift + click (or right click) a point to remove it. Each change is one Undo.

The game has no shapes, only the objects they make. The outlines are kept by Yaz0moto next to
its settings (shapes/<level>.json), so they can be edited again after reopening the level;
the level file itself is exactly what it would be with hand-placed objects.
"""

import copy
import hashlib
import json
import math
import os

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt

from . import globals
from . import quickpaint as qp

REACH = 0.6       # tiles: how close a click must be to a node to grab it
CLOSE_REACH = 1.2  # ...and to the first node of a new shape to close it
EDGE_REACH = 0.4  # ...and to a side to add a node on it
SNAP_REACH = 0.75  # a node placed this close to an exact slope angle (or flat/straight) goes there
STEP_UNITS = {'Steep': (1, 2), 1: (1, 1), 2: (2, 1), 4: (4, 1)}  # tiles across, tiles up


# ------------------------------------------------------------------------------- geometry

def diagonal_units(roles, get_def=None):
    """The (across, up) steps sides can take besides flat and straight up: the slope angles the preset has."""
    get_def = get_def or qp.global_def
    units = []
    for kind in qp.SLOPE_STEPS:
        for orient in qp.SLOPE_ORIENTATIONS:
            key = roles.get('slope%s_%s' % (kind, orient))
            if key and qp.is_diagonal(get_def(tuple(key))):
                units.append(STEP_UNITS[kind])
                break
    return units


def valid_side(a, b, units):
    """Whether a side from a to b runs flat, straight up/down, or along one of the slope angles in whole steps."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if (dx == 0) != (dy == 0):
        return True
    if dx == 0:
        return False
    for sw, sh in units:
        if abs(dx) % sw == 0 and abs(dy) == abs(dx) // sw * sh:
            return True
    return False


def snap(prev, raw, units):
    """The grid corner for a point placed at raw (tiles, floats) after prev: on the closest allowed direction."""
    px, py = prev
    tx, ty = raw
    candidates = [(int(round(tx)), py), (px, int(round(ty)))]
    for sw, sh in units:
        for sx in (1, -1):
            for sy in (1, -1):
                dx, dy = sx * sw, sy * sh
                n = int(round(((tx - px) * dx + (ty - py) * dy) / float(dx * dx + dy * dy)))
                if n >= 1:
                    candidates.append((px + n * dx, py + n * dy))
    candidates = [c for c in candidates if c[0] >= 0 and c[1] >= 0 and c != tuple(prev)]
    if not candidates:
        return None
    return min(candidates, key=lambda c: (c[0] - tx) ** 2 + (c[1] - ty) ** 2)


def _directions(units):
    dirs = {(1, 0), (-1, 0), (0, 1), (0, -1)}
    for sw, sh in units:
        for sx in (1, -1):
            for sy in (1, -1):
                dirs.add((sx * sw, sy * sh))
    return dirs


def snap_between(prev, nxt, raw, units):
    """
    The grid corner nearest raw where both sides (from prev and on to nxt) are allowed, or None:
    the corners where an allowed direction from prev meets an allowed direction from nxt.
    """
    candidates = set()
    dirs = _directions(units)
    for d1 in dirs:
        for d2 in dirs:
            # prev + a * d1 == nxt + b * d2, with whole steps a, b >= 1
            det = d1[0] * (-d2[1]) - d1[1] * (-d2[0])
            if det == 0:
                continue
            rx, ry = nxt[0] - prev[0], nxt[1] - prev[1]
            a_num = rx * (-d2[1]) - ry * (-d2[0])
            b_num = d1[0] * ry - d1[1] * rx
            if a_num % det or b_num % det:
                continue
            a, b = a_num // det, b_num // det
            if a >= 1 and b >= 1:
                candidates.add((prev[0] + a * d1[0], prev[1] + a * d1[1]))
    good = [c for c in candidates if c[0] >= 0 and c[1] >= 0 and c != tuple(prev) and c != tuple(nxt)
            and valid_side(prev, c, units) and valid_side(c, nxt, units)]
    if not good:
        return None
    return min(good, key=lambda c: (c[0] - raw[0]) ** 2 + (c[1] - raw[1]) ** 2)


def _split(a, b, units, before=None, after=None, depth=0):
    """
    The corners after a, ending with b, that make the side a-b out of allowed sides: as
    much of it as fits at the closest slope angle, with the rest flat or straight up/down
    (or a step, if no slope angle fits). The straight rest goes where it carries on the side
    before a or after b (so a drop at the foot of a slope runs into the wall below it, not
    as a notch under its top), else in two halves around the slope.
    """
    if valid_side(a, b, units) or depth > 12:
        return [tuple(b)]
    dx, dy = b[0] - a[0], b[1] - a[1]
    sx, sy = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
    best = None
    for sw, sh in units:
        n = min(abs(dx) // sw, abs(dy) // sh)
        if n >= 1:
            err = abs(math.log((abs(dx) / float(abs(dy))) / (sw / float(sh))))
            if best is None or err < best[0]:
                best = (err, n, sw, sh)
    if best is None:
        corner = (a[0], b[1]) if abs(dy) >= abs(dx) else (b[0], a[1])
        return [corner, tuple(b)]
    _, n, sw, sh = best
    rx, ry = dx - n * sw * sx, dy - n * sh * sy

    def same_way(p, q):
        """Whether the side p-q runs the way the rest does (both straight up/down, or both flat)."""
        if p is None or q is None:
            return False
        return (rx == 0 and p[0] == q[0] and (q[1] - p[1]) * ry > 0) or (ry == 0 and p[1] == q[1] and (q[0] - p[0]) * rx > 0)

    if (rx == 0 or ry == 0) and same_way(b, after):
        p1 = tuple(a)  # slope first, the rest carries on into the next side
    elif (rx == 0 or ry == 0) and same_way(before, a):
        p1 = (a[0] + rx, a[1] + ry)  # the rest carries on from the side before, then the slope
    elif rx == 0 and before is not None and after is not None:
        p1 = tuple(a) if (dy > 0) else (a[0], a[1] + ry)  # a drop at the slope's low end
    else:
        p1 = (a[0] + int(rx / 2.0), a[1] + int(ry / 2.0))
    p2 = (p1[0] + n * sw * sx, p1[1] + n * sh * sy)
    out = []
    if p1 != tuple(a):
        out += _split(a, p1, units, before, p2, depth + 1)
    out.append(p2)
    if p2 != tuple(b):
        out += _split(p2, b, units, p1, after, depth + 1)
    return out


def _slope_unit(a, b, units):
    """The step (across, up) a diagonal side a-b is made of, pointing from a to b, or None."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    for sw, sh in units:
        if dx and dy and abs(dx) % sw == 0 and abs(dy) == abs(dx) // sw * sh:
            return (sw if dx > 0 else -sw, sh if dy > 0 else -sh)
    return None


def _flat_before_drops(pts, units):
    """
    Where a slope meets a straight drop at an outside corner, the slope ends a step early with
    flat ground before the drop, as in Nintendo's levels: slope tiles have no edge of their
    own, so a slope running straight into a cliff would show a cut-off end.
    """
    pts = list(pts)
    for _ in range(4 * len(pts)):
        n = len(pts)
        area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
        changed = False
        for i in range(n):
            prev, p, nxt = pts[i - 1], pts[i], pts[(i + 1) % n]
            cross = (p[0] - prev[0]) * (nxt[1] - p[1]) - (p[1] - prev[1]) * (nxt[0] - p[0])
            if cross == 0 or (cross > 0) != (area > 0):
                continue  # not an outside corner
            for diag_end, straight_end in ((prev, nxt), (nxt, prev)):
                if straight_end[0] != p[0] or straight_end[1] == p[1]:
                    continue  # the other side isn't a straight drop
                unit = _slope_unit(p, diag_end, units)
                if unit is None or abs(diag_end[0] - p[0]) < 2 * abs(unit[0]):
                    continue  # not a slope, or too short to lose a step
                q = (p[0] + unit[0], p[1] + unit[1])  # a step back along the slope
                r = (p[0], q[1])                      # flat over to the drop
                pts[i:i + 1] = [q, r] if diag_end is prev else [r, q]
                changed = True
                break
            if changed:
                break
        if not changed:
            break
        pts = cleaned(pts)
    return pts


def refine(points, units):
    """The outline with every side made of allowed sides (see _split): what the terrain follows."""
    pts = cleaned(points)
    out = []
    n = len(pts)
    for i in range(n):
        out += _split(pts[i], pts[(i + 1) % n], units, pts[i - 1], pts[(i + 2) % n])
    return _flat_before_drops(cleaned(out[-1:] + out[:-1]), units)


def snap_free(prev, raw, units):
    """A node placed at raw after prev: onto an exact slope angle (or flat/straight) when near one, else the nearest corner."""
    near = snap(prev, raw, units)
    if near is not None and math.hypot(near[0] - raw[0], near[1] - raw[1]) <= SNAP_REACH:
        return near
    corner = (max(0, int(round(raw[0]))), max(0, int(round(raw[1]))))
    return corner if corner != tuple(prev) else near


def snap_node(prev, nxt, raw, units):
    """A node dragged to raw between prev and nxt: where exact sides meet when near, else the nearest corner."""
    near = snap_between(prev, nxt, raw, units)
    if near is not None and math.hypot(near[0] - raw[0], near[1] - raw[1]) <= SNAP_REACH:
        return near
    corner = (max(0, int(round(raw[0]))), max(0, int(round(raw[1]))))
    return None if corner in (tuple(prev), tuple(nxt)) else corner


def cleaned(points):
    """
    The points without repeats and without spikes (a side going straight back over the one
    before). Points in the middle of a straight side stay: they were added to be dragged.
    """
    pts = [(int(p[0]), int(p[1])) for p in points]
    changed = True
    while changed:
        changed = False
        for i in range(len(pts)):
            if len(pts) > 1 and pts[i] == pts[i - 1]:
                del pts[i if i else -1]  # the first point stays first
                changed = True
                break
        if changed or len(pts) < 3:
            continue
        for i in range(len(pts)):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
            ux, uy, vx, vy = b[0] - a[0], b[1] - a[1], c[0] - b[0], c[1] - b[1]
            if ux * vy == uy * vx and ux * vx + uy * vy < 0:  # straight back: a spike
                del pts[i]
                changed = True
                break
    return pts


def inside(x, y, pts):
    """Whether the point (x, y) is inside the outline (even-odd rule)."""
    result = False
    n = len(pts)
    for i in range(n):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) * (x2 - x1) / float(y2 - y1):
                result = not result
    return result


def _segments_cross(a, b, c, d):
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (v > 0) - (v < 0)

    def on(p, q, r):
        return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    return ((o1 == 0 and on(a, c, b)) or (o2 == 0 and on(a, d, b))
            or (o3 == 0 and on(c, a, d)) or (o4 == 0 and on(c, b, d)))


def simple(pts):
    """Whether the outline is a proper shape: at least 3 points, no sides crossing or touching."""
    n = len(pts)
    if n < 3:
        return False
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    if area == 0:
        return False
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if _segments_cross(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                return False
    return True


def interior(pts):
    """The tiles inside the outline (those whose middle is inside it)."""
    if len(pts) < 3:
        return set()
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {(x, y) for y in range(min(ys), max(ys)) for x in range(min(xs), max(xs))
            if inside(x + 0.5, y + 0.5, pts)}


def slope_kind_for(dx, dy):
    ratio = abs(dx) / float(abs(dy))
    return min(qp.SLOPE_STEPS, key=lambda k: abs(math.log(ratio / qp.SLOPE_RATIO[k])))


def parts(pts, roles, get_def=None):
    """
    (tiles, slopes) of a shape: the tiles inside it, and the slope object for each sloped side,
    [(x, y, w, h, key)]: a floor slope where the inside is under the side, a ceiling slope where
    it's above. A side whose slope the preset doesn't have (or can't fit exactly) stays a staircase.
    """
    get_def = get_def or qp.global_def
    pts = refine(pts, diagonal_units(roles, get_def))
    cells = interior(pts)
    slopes = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        if dx == 0 or dy == 0:
            continue
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        ceiling = not inside(mid[0], mid[1] + 0.25, pts)
        segment = qp.slope_segment(roles, get_def, a, b, slope_kind_for(dx, dy), ceiling)
        if segment is not None and tuple(segment[1]) == tuple(b):
            slopes.append(segment[0])
    return cells, slopes


KIND_NAMES = {'Steep': 'steep', 1: '45°', 2: 'gentle', 4: 'very gentle'}


def unbuilt(pts, roles, get_def=None):
    """
    The sides of a shape the preset has no slope for as drawn: [(side index, what's missing)].
    They're built from the slopes it has instead (the dashed outline).
    """
    get_def = get_def or qp.global_def
    pts = cleaned(pts)
    units = diagonal_units(roles, get_def)
    out = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        if dx == 0 or dy == 0:
            continue
        kind = slope_kind_for(dx, dy)
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        ceiling = not inside(mid[0], mid[1] + 0.25, pts)
        rising = (dx > 0) == (dy < 0)
        orient = ('ceilUp' if rising else 'ceilDown') if ceiling else ('floorUp' if rising else 'floorDown')
        if not valid_side(a, b, units) or kind not in qp.slope_kinds(roles, get_def, orient):
            out.append((i, '%s %s slope going %s' % (KIND_NAMES.get(kind, kind), 'ceiling' if ceiling else 'floor',
                                                  'up' if rising else 'down')))
    return out


def unbuilt_note(pts, roles, get_def=None):
    """What to tell the user about unbuilt() sides, or ''."""
    missing = sorted(set(m for _, m in unbuilt(pts, roles, get_def)))
    if not missing:
        return ''
    return ('the tileset has no %s, so the red side%s %s built from the slopes it has (the dashed line). '
            'You can add slope parts from the Game tab to the preset.'
            % (', '.join(missing), '' if len(missing) == 1 else 's', 'is' if len(missing) == 1 else 'are'))


def plan(objects, roles, pts, old=None, keep=(), get_def=None):
    """
    The change that makes the shape pts on a layer of objects, replacing the shape old (a stored
    shape: its points and slopes) if it's an edit. keep: tiles of other shapes that are left alone.
    Returns (remove, add, slopes) as TerrainPlanner.plan does, slopes being the shape's slope objects.
    """
    get_def = get_def or qp.global_def
    old_slopes = []
    old_cells = set()
    old_slope_cells = set()
    if old is not None:
        wanted = {tuple(r[:4]) for r in old.get('slopes', ())}
        old_slopes = [o for o in objects if (o.objx, o.objy, o.width, o.height) in wanted
                      and qp.is_diagonal(get_def(qp.obj_key(o)))]
        old_cells = interior(refine(old['points'], diagonal_units(roles, get_def)))
    planner = qp.TerrainPlanner([o for o in objects if o not in old_slopes], roles, get_def)
    for o in old_slopes:
        old_slope_cells |= qp.TerrainPlanner([], roles, get_def).slopeCells(o.objx, o.objy, o.width, o.height, qp.obj_key(o))
    cells, slopes = parts(pts, roles, get_def) if pts else (set(), [])
    slope_cells = set()
    for r in slopes:
        slope_cells |= planner.slopeCells(*r)
    erase = (old_cells | old_slope_cells) - cells - set(keep)
    remove, add = planner.plan(paint=cells - slope_cells, erase=erase, regions=old_slope_cells, new_slopes=slopes)
    return old_slopes + [o for o in remove if o not in old_slopes], add, slopes


# ------------------------------------------------------------------------------- the stored shapes

_store = {}    # (level key, area) -> [shape]
_loaded = set()


def shapes_folder():
    return os.path.join(globals.user_data_path, 'shapes')


def level_key():
    mw = globals.mainWindow
    path = getattr(mw, 'fileSavePath', None)
    if path and path != getattr(globals, 'AutoSavePath', None):
        return os.path.normcase(os.path.abspath(path))
    return 'unsaved:%x' % id(globals.Level)


def _file_for(key):
    return os.path.join(shapes_folder(), hashlib.sha1(key.encode('utf-8')).hexdigest()[:16] + '.json')


def _load(key):
    if key in _loaded:
        return
    _loaded.add(key)
    if key.startswith('unsaved:'):
        return
    try:
        with open(_file_for(key), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict) or os.path.normcase(str(data.get('path', ''))) != key:
        return
    for area, shapes in (data.get('areas') or {}).items():
        try:
            _store[(key, int(area))] = [s for s in shapes if isinstance(s, dict) and len(s.get('points', ())) >= 3]
        except (TypeError, ValueError):
            pass


def area_shapes(create=True):
    """The shapes of the open area (a list kept here; changes go through ShapesCommand)."""
    key = level_key()
    _load(key)
    k = (key, globals.CurrentArea)
    if k not in _store and create:
        _store[k] = []
    return _store.get(k, [])


def level_saved(path):
    """The level was saved to path: keep its shapes there (from where they were while unsaved)."""
    key = os.path.normcase(os.path.abspath(path))
    for (lk, area) in list(_store):
        if lk.startswith('unsaved:') and lk == 'unsaved:%x' % id(globals.Level):
            _store[(key, area)] = _store.pop((lk, area))
    _loaded.add(key)
    areas = {str(area): shapes for (lk, area), shapes in _store.items() if lk == key and shapes}
    target = _file_for(key)
    try:
        if not areas:
            if os.path.isfile(target):
                os.remove(target)
            return
        os.makedirs(shapes_folder(), exist_ok=True)
        tmp = target + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'path': os.path.abspath(path), 'areas': areas}, f)
        os.replace(tmp, target)
    except OSError as e:
        print('Quick Paint: could not save the shapes of %s: %s' % (path, e))


class ShapesCommand:
    """Undo step for a change to the open area's shapes (with the objects' change beside it)."""

    def __init__(self, key, before, after, description='Quick Paint Shape'):
        self.key = key
        self.before = copy.deepcopy(before)
        self.after = copy.deepcopy(after)
        self.description = description

    def redo(self):
        _store[self.key] = copy.deepcopy(self.after)

    def undo(self):
        _store[self.key] = copy.deepcopy(self.before)


def _make_command(key, before, after, description):
    from . import undomanager

    class Command(ShapesCommand, undomanager.Command):
        def __init__(self):
            undomanager.Command.__init__(self, description)
            ShapesCommand.__init__(self, key, before, after, description)

    return Command()


def commit(layer_idx, remove, add, after, description):
    """Applies an object change and the new list of shapes as one Undo step. Returns whether it was done."""
    key = (level_key(), globals.CurrentArea)
    before = area_shapes()
    manager = globals.UndoManager
    manager.begin_compound(description)
    try:
        if remove or add:
            if not qp.apply_plan(layer_idx, remove, add, description):
                return False  # nothing placed (e.g. no room for its objects in the level's tilesets)
        manager.push(_make_command(key, before, after, description))
    finally:
        manager.end_compound()
    try:
        from .verifications import SetDirty
        SetDirty()
    except Exception:
        pass
    return True


# ------------------------------------------------------------------------------- editing in the level

class _State:
    def __init__(self):
        self.draft = None       # [corner] of the shape being drawn
        self.hover = None       # (raw point, corner)
        self.ghost = None       # where a click would put the next point
        self.drag = None        # {'kind': 'point'|'move', 'index', 'point', 'start', 'points'}
        self.selected = None    # index of the selected shape
        self.node = None        # index of its selected node (Delete removes it)
        self.preview_slopes = []


_s = _State()


def _sync():
    """Forgets a shape being drawn or dragged in another level or area."""
    key = (id(globals.Area), globals.CurrentLayer)
    if getattr(_s, 'where', None) != key:
        if _s.draft is not None or _s.drag is not None:
            qp._preview.clear()
        _s.draft = _s.drag = _s.ghost = None
        _s.selected = _s.node = None
        _s.where = key


def _raw(view, pos):
    p = view.mapToScene(pos)
    return p.x() / float(globals.TileWidth), p.y() / float(globals.TileWidth)


def _roles():
    return qp.planning_roles(qp.panel().roles())


def _layer_shapes():
    return [(i, s) for i, s in enumerate(area_shapes()) if s.get('layer', 1) == globals.CurrentLayer]


def _mid_handle(a, b):
    """Where a side's + handle is (its middle), or None for a side too short for another node."""
    if max(abs(b[0] - a[0]), abs(b[1] - a[1])) < 2:
        return None
    return (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0


def _hit(raw):
    """
    What is at raw, the nearest first: (shape index, node index, None, False) for a node,
    (index, None, side, True) for a side's + handle, (index, None, side, False) for a side,
    (index, None, None, False) for the inside; or None.
    """
    best = None
    for i, s in _layer_shapes():
        pts = s['points']
        for j, p in enumerate(pts):
            d = math.hypot(p[0] - raw[0], p[1] - raw[1])
            if d <= REACH and (best is None or d < best[0]):
                best = (d, (i, j, None, False))
        for j in range(len(pts)):
            m = _mid_handle(pts[j], pts[(j + 1) % len(pts)])
            if m is not None:
                d = math.hypot(m[0] - raw[0], m[1] - raw[1])
                if d <= REACH * 0.8 and (best is None or d < best[0]):
                    best = (d, (i, None, j, True))
    if best:
        return best[1]
    for i, s in _layer_shapes():
        pts = s['points']
        for j in range(len(pts)):
            a, b = pts[j], pts[(j + 1) % len(pts)]
            if _dist_to_side(raw, a, b) <= EDGE_REACH:
                return i, None, j, False
    for i, s in _layer_shapes():
        if inside(raw[0], raw[1], s['points']):
            return i, None, None, False
    return None


def _remove_node(index, node):
    shape = area_shapes()[index]
    pts = [tuple(p) for k, p in enumerate(shape['points']) if k != node]
    if len(cleaned(pts)) < 3:
        qp.panel().say('a shape needs at least three nodes (Delete in the panel removes the whole shape).')
        return False
    return _apply(pts, index, 'Quick Paint Shape: Remove Node')


def _dist_to_side(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / float(dx * dx + dy * dy or 1)))
    return math.hypot(ax + t * dx - p[0], ay + t * dy - p[1])


def _other_cells(index):
    cells = set()
    for i, s in _layer_shapes():
        if i != index:
            cells |= interior(refine(s['points'], diagonal_units(qp.planning_roles(s.get('roles') or {}))))
    return cells


def _preview(pts, index=None):
    """Shows what the shape pts would look like (replacing shape index, if editing)."""
    view = globals.mainWindow.view
    if pts is None or len(pts) < 3 or not simple(refine(pts, diagonal_units(_roles()))):
        qp._preview.clear()
        _s.preview_slopes = []
        view.viewport().update()
        return
    shapes = area_shapes()
    old = shapes[index] if index is not None else None
    roles = qp.planning_roles(old['roles']) if old is not None and old.get('roles') else _roles()
    try:
        remove, add, slopes = plan(globals.Area.layers[globals.CurrentLayer], roles, cleaned(pts), old,
                                   _other_cells(index))
    except Exception:
        import traceback
        traceback.print_exc()
        remove, add, slopes = [], [], []
    _s.preview_slopes = slopes
    qp._preview.show(remove, add)
    view.viewport().update()


def _apply(pts, index, description, raw_roles=None):
    """
    Places shape pts (replacing shape index if editing; None pts deletes it), with the parts
    the shape was made with (or raw_roles). Returns whether it was done.
    """
    shapes = area_shapes()
    old = shapes[index] if index is not None else None
    if raw_roles is None:
        raw_roles = dict(old['roles']) if old is not None and old.get('roles') else dict(qp.panel().roles())
    roles = qp.planning_roles(raw_roles)
    layer_idx = old.get('layer', globals.CurrentLayer) if old is not None else globals.CurrentLayer
    if pts is not None:
        pts = cleaned(pts)
        if len(pts) < 3 or not simple(refine(pts, diagonal_units(roles))):
            qp.panel().say('the outline crosses itself: move the point somewhere else.')
            return False
    remove, add, slopes = plan(globals.Area.layers[layer_idx], roles, pts or [], old, _other_cells(index))
    if pts is not None and old is None and not add:
        qp.panel().say("nothing to place there with this preset (is its Fill part in this level's tilesets?): "
                       "the shape wasn't made.")
        qp._preview.clear()
        return False
    after = copy.deepcopy(shapes)
    if pts is None:
        del after[index]
    else:
        shape = {'points': [list(p) for p in pts], 'layer': layer_idx, 'roles': raw_roles,
                 'slopes': [list(r[:4]) for r in slopes]}
        if index is None:
            after.append(shape)
        else:
            after[index] = shape
    qp._preview.clear()
    done = commit(layer_idx, remove, add, after, description)
    _s.node = None
    if done and pts is not None:
        _s.selected = index if index is not None else len(after) - 1
        note = unbuilt_note(pts, roles)
        if note:
            qp.panel().say(note)
    elif done:
        _s.selected = None
    return done


def is_drawing():
    return _s.draft is not None or _s.drag is not None


HINT = 'click the first node (or double-click, or press Enter or Esc) to finish the shape; Backspace takes back the last node.'


def finish():
    """Places the shape being drawn, if it has three nodes or more. Returns whether there was one."""
    if _s.draft is None:
        return False
    pts, _s.draft, _s.ghost = cleaned(_s.draft), None, None
    if len(pts) >= 3:
        if _apply(pts, None, 'Quick Paint Shape') and not unbuilt(pts, qp.planning_roles(qp.panel().roles())):
            qp.panel().say('shape placed: drag its nodes to change it, the + on a side to add one.')
    else:
        qp._preview.clear()
        qp.panel().say('')
    view = getattr(globals.mainWindow, 'view', None)
    if view is not None:
        view.viewport().update()
    return True


def undo_node():
    """Backspace while drawing: takes back the last node. Returns whether there was one."""
    if _s.draft is None:
        return False
    _s.draft.pop()
    if not _s.draft:
        _s.draft = None
        qp._preview.clear()
    else:
        _preview(_s.draft + [_s.ghost] if _s.ghost else _s.draft)
    view = getattr(globals.mainWindow, 'view', None)
    if view is not None:
        view.viewport().update()
    return True


def cancel(finish_draft=True):
    """
    Esc: a shape being drawn is finished (placed, if it has three nodes or more); a drag stops.
    Returns whether there was one.
    """
    if finish_draft and _s.draft is not None:
        finish()
        return True
    had = _s.draft is not None or _s.drag is not None
    _s.draft = None
    _s.drag = None
    _s.ghost = None
    qp._preview.clear()
    view = getattr(globals.mainWindow, 'view', None)
    if view is not None:
        view.viewport().update()
    return had


def deselect():
    _s.selected = _s.node = None


def delete_key():
    """
    Delete/Backspace in Shape mode: takes back the last node of a shape being drawn, removes the
    selected node, or else deletes the selected shape. Returns whether it did something.
    """
    if _s.draft is not None:
        return undo_node()
    shapes = area_shapes()
    if _s.selected is None or not 0 <= _s.selected < len(shapes):
        return False
    if _s.node is not None and 0 <= _s.node < len(shapes[_s.selected]['points']):
        done = _remove_node(_s.selected, _s.node)
        _s.node = None
    else:
        done = delete_selected()
        if done:
            qp.panel().say('shape deleted (Ctrl+Z brings it back).')
    view = getattr(globals.mainWindow, 'view', None)
    if view is not None:
        view.viewport().update()
    return True


def delete_selected():
    """Deletes the selected shape and its terrain."""
    shapes = area_shapes()
    if _s.selected is None or not 0 <= _s.selected < len(shapes):
        qp.panel().say('click inside a shape to select it first.')
        return False
    done = _apply(None, _s.selected, 'Quick Paint Delete Shape')
    _s.selected = _s.node = None
    return done


def forget_selected():
    """Stops keeping the selected shape's outline: its objects stay as ordinary objects."""
    shapes = area_shapes()
    if _s.selected is None or not 0 <= _s.selected < len(shapes):
        qp.panel().say('click inside a shape to select it first.')
        return False
    after = copy.deepcopy(shapes)
    del after[_s.selected]
    _s.selected = None
    return commit(globals.CurrentLayer, [], [], after, 'Quick Paint Forget Shape')


def retile_selected():
    """Places the selected shape again with the preset open in Quick Paint."""
    shapes = area_shapes()
    if _s.selected is None or not 0 <= _s.selected < len(shapes):
        qp.panel().say('click inside a shape to select it first.')
        return False
    return _apply(shapes[_s.selected]['points'], _s.selected, 'Quick Paint Re-tile Shape', dict(qp.panel().roles()))


def _secondary(event):
    """Shift + click, or right click with the new mouse controls: removes a point."""
    if QtWidgets.QApplication.keyboardModifiers() & Qt.ShiftModifier:
        return True
    return event.button() == Qt.RightButton and not globals.LegacyMouseControls


def claims(view, event):
    """
    Whether a click is for Shape mode even where that button isn't Quick Paint's (left click
    with Legacy mouse controls): one on a shape, or while one is drawn or dragged.
    """
    _sync()
    return _s.draft is not None or _s.drag is not None or _hit(_raw(view, event.pos())) is not None


def press(view, event):
    event.accept()
    _sync()
    raw = _raw(view, event.pos())
    units = diagonal_units(_roles())
    corner = (max(0, int(round(raw[0]))), max(0, int(round(raw[1]))))

    if _s.draft is not None:
        if _secondary(event):
            _s.draft.pop()  # takes the last point back
            if not _s.draft:
                _s.draft = None
            _preview(_s.draft + [_s.ghost] if _s.draft and _s.ghost else _s.draft)
            return True
        first = _s.draft[0]
        if len(_s.draft) >= 3 and math.hypot(first[0] - raw[0], first[1] - raw[1]) <= CLOSE_REACH:
            finish()
            return True
        point = snap_free(_s.draft[-1], raw, units)
        if point is not None:
            _s.draft.append(point)
        _preview(_s.draft)
        return True

    hit = _hit(raw)
    if hit is not None:
        index, point_index, side, handle = hit
        shape = area_shapes()[index]
        original = [tuple(p) for p in shape['points']]
        _s.selected = index
        _s.node = point_index
        if point_index is not None:
            if _secondary(event):
                _remove_node(index, point_index)
                return True
            _s.drag = {'kind': 'point', 'index': index, 'point': point_index, 'start': raw,
                       'points': list(original), 'original': original}
        elif handle and not _secondary(event):
            # A side's + handle: a new node there, which follows the mouse until it's let go
            a, b = original[side], original[(side + 1) % len(original)]
            m = (int(round((a[0] + b[0]) / 2.0)), int(round((a[1] + b[1]) / 2.0)))
            pts = list(original)
            pts.insert(side + 1, m)
            _s.drag = {'kind': 'point', 'index': index, 'point': side + 1, 'start': raw,
                       'points': pts, 'original': original, 'current': pts, 'added': True}
        elif not _secondary(event):
            _s.drag = {'kind': 'move', 'index': index, 'start': raw, 'points': list(original),
                       'original': original, 'delta': (0, 0)}
        view.viewport().update()
        return True

    if _secondary(event):
        return True
    if _s.selected is not None:
        _s.node = None
        # The first click away from a shape only lets go of it; the next one starts a new shape
        _s.selected = None
        qp.panel().say('click on an empty spot to start a new shape, or on a shape to edit it.')
        view.viewport().update()
        return True
    _s.draft = [corner]
    _s.ghost = None
    qp.panel().say(HINT)
    view.viewport().update()
    return True


def move(view, event):
    _sync()
    raw = _raw(view, event.pos())
    units = diagonal_units(_roles())
    corner = (max(0, int(round(raw[0]))), max(0, int(round(raw[1]))))
    changed = _s.hover is None or _s.hover[1] != corner
    _s.hover = (raw, corner)
    view.viewport().setCursor(Qt.CrossCursor)

    if _s.drag is not None:
        d = _s.drag
        pts = list(d['points'])
        if d['kind'] == 'point':
            j = d['point']
            p = snap_node(pts[j - 1], pts[(j + 1) % len(pts)], raw, units)
            if p is None or p == d.get('last'):
                return True
            d['last'] = p
            pts[j] = p
        else:
            delta = (int(round(raw[0] - d['start'][0])), int(round(raw[1] - d['start'][1])))
            delta = (max(delta[0], -min(p[0] for p in pts)), max(delta[1], -min(p[1] for p in pts)))
            if delta == d.get('delta'):
                return True
            d['delta'] = delta
            pts = [(p[0] + delta[0], p[1] + delta[1]) for p in pts]
        d['current'] = pts
        _preview(pts, d['index'])
        return True

    if _s.draft is not None and changed:
        first = _s.draft[0]
        if len(_s.draft) >= 3 and math.hypot(first[0] - raw[0], first[1] - raw[1]) <= CLOSE_REACH:
            _s.ghost = tuple(first)  # a click here closes the shape
        else:
            _s.ghost = snap_free(_s.draft[-1], raw, units)
        _preview(_s.draft + [_s.ghost] if _s.ghost else _s.draft)
        return True
    if changed:
        view.viewport().update()
    return _s.draft is not None


def release(view, event):
    event.accept()
    d, _s.drag = _s.drag, None
    if d is not None and d.get('current') and [tuple(p) for p in d['current']] != d['original']:
        if d.get('added'):
            description = 'Quick Paint Shape: Add Node'
        else:
            description = 'Quick Paint Shape: Move Node' if d['kind'] == 'point' else 'Quick Paint Shape: Move'
        if not _apply(d['current'], d['index'], description):
            qp._preview.clear()
        elif d['kind'] == 'point':
            _s.node = d['point']  # the node just moved stays selected (Delete removes it)
    elif d is not None:
        qp._preview.clear()
    view.viewport().update()
    return True


def double_click(view, event):
    """Closes the shape being drawn; on a placed shape removes the node double-clicked, or adds one on the side."""
    event.accept()
    raw = _raw(view, event.pos())
    if _s.draft is not None:
        if len(cleaned(_s.draft)) < 3:
            qp.panel().say('a shape needs at least three nodes.')
            return True
        finish()
        return True
    _s.drag = None
    qp._preview.clear()
    hit = _hit(raw)
    if hit is None:
        return True
    index, node, side, handle = hit
    if node is not None:
        _remove_node(index, node)
        return True
    if side is None:
        return True
    if handle:
        return True  # the first click already added a node there
    shape = area_shapes()[index]
    pts = [tuple(p) for p in shape['points']]
    a, b = pts[side], pts[(side + 1) % len(pts)]
    corner = (int(round(raw[0])), int(round(raw[1])))
    if corner in (a, b):
        qp.panel().say('that side is too short for another node.')
        return True
    pts.insert(side + 1, corner)
    _apply(pts, index, 'Quick Paint Shape: Add Node')
    view.viewport().update()
    return True


def leave(view):
    _s.hover = None


# ------------------------------------------------------------------------------- drawing

def _dot(painter, p, tile, color, radius):
    painter.setBrush(color)
    painter.drawEllipse(QtCore.QPointF(p[0] * tile, p[1] * tile), radius, radius)


def draw(painter, rect, tile, draw_tiles):
    """The outlines and points of the layer's shapes, the shape being drawn, and the preview's tiles."""
    _sync()
    draw_tiles(qp._preview.add)
    white = QtGui.QColor(255, 255, 255)
    accent = QtGui.QColor(255, 140, 0)
    radius = max(5.0, tile * 0.28)

    def outline(pts, color, width, closed=True, dashed=False):
        pen = QtGui.QPen(color, width, Qt.DashLine if dashed else Qt.SolidLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        poly = QtGui.QPolygonF([QtCore.QPointF(p[0] * tile, p[1] * tile) for p in pts])
        if closed:
            painter.drawPolygon(poly)
        else:
            painter.drawPolyline(poly)

    edge_pen = QtGui.QPen(QtGui.QColor(60, 60, 60), 1.5)
    edge_pen.setCosmetic(True)
    drag = _s.drag
    for i, s in _layer_shapes():
        pts = [tuple(p) for p in s['points']]
        if drag is not None and drag['index'] == i and drag.get('current'):
            pts = drag['current']
        selected = i == _s.selected
        built = refine(pts, diagonal_units(qp.planning_roles(s.get('roles') or {})))
        if built != cleaned(pts):  # where sides at other angles really go (slopes and straight bits)
            outline(built, QtGui.QColor(255, 255, 255, 150), 1, dashed=True)
        outline(pts, accent if selected else white, 3 if selected else 2)
        for j, _ in unbuilt(pts, qp.planning_roles(s.get('roles') or {})):  # sides it has no slope for
            outline([pts[j], pts[(j + 1) % len(pts)]], QtGui.QColor(235, 60, 60), 3 if selected else 2, closed=False)
        if drag is None or drag['index'] != i:
            for j in range(len(pts)):  # the + handles that add a node
                m = _mid_handle(pts[j], pts[(j + 1) % len(pts)])
                if m is None:
                    continue
                c = QtCore.QPointF(m[0] * tile, m[1] * tile)
                r = radius * 0.7
                painter.setPen(edge_pen)
                painter.setBrush(QtGui.QColor(255, 255, 255, 170))
                painter.drawEllipse(c, r, r)
                plus = QtGui.QPen(QtGui.QColor(40, 40, 40), 1.6)
                plus.setCosmetic(True)
                painter.setPen(plus)
                painter.drawLine(QtCore.QPointF(c.x() - r * 0.55, c.y()), QtCore.QPointF(c.x() + r * 0.55, c.y()))
                painter.drawLine(QtCore.QPointF(c.x(), c.y() - r * 0.55), QtCore.QPointF(c.x(), c.y() + r * 0.55))
        painter.setPen(edge_pen)
        for k, p in enumerate(pts):
            picked = selected and k == _s.node  # the selected node: bigger and orange
            _dot(painter, p, tile, accent if picked else white, radius * (1.3 if picked else 1))
    if _s.draft is not None:
        pts = list(_s.draft)
        outline(pts + ([_s.ghost] if _s.ghost else []), white, 2, closed=False)
        if _s.ghost and len(pts) >= 2:
            outline([_s.ghost, pts[0]], white, 1.5, closed=False, dashed=True)
        painter.setPen(edge_pen)
        for k, p in enumerate(pts):
            _dot(painter, p, tile, accent if k == 0 else white, radius * (1.25 if k == 0 else 1))
        if _s.ghost:
            painter.setBrush(Qt.NoBrush)
            pen = QtGui.QPen(white, 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawEllipse(QtCore.QPointF(_s.ghost[0] * tile, _s.ghost[1] * tile), radius, radius)
    elif drag is None and _s.hover is not None:
        pen = QtGui.QPen(white, 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        c = _s.hover[1]
        painter.drawEllipse(QtCore.QPointF(c[0] * tile, c[1] * tile), radius * 0.7, radius * 0.7)
