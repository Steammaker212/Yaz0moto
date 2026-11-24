"""
Tests for Quick Paint (yaz0moto/quickpaint.py): which part of the terrain each tile is,
merging tiles into few objects, painting next to / over / out of existing terrain, keeping
objects that don't change, learning a preset from terrain, and the undo step.

Run from anywhere:   python tests/quickpaint_test.py
"""
import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import os
import sys
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

from yaz0moto import globals  # noqa: E402
from yaz0moto import quickpaint as qp  # noqa: E402

results = []


def check(label, ok):
    results.append((label, bool(ok)))
    print(('  OK  ' if ok else 'FAIL  ') + label)


# A grass preset: one object per part, all in tileset slot 1
ROLES = {role: [1, i] for i, role in enumerate(qp.ROLES)}
KEY = {role: (1, i) for i, role in enumerate(qp.ROLES)}
PART = {v: k for k, v in KEY.items()}


class Obj:
    def __init__(self, x, y, w, h, key):
        self.objx, self.objy, self.width, self.height = x, y, w, h
        self.tileset, self.original_type = key

    def __repr__(self):
        return 'Obj(%d,%d,%dx%d,%s)' % (self.objx, self.objy, self.width, self.height, PART.get((self.tileset, self.original_type)))


def apply(objects, roles=ROLES, **kw):
    remove, add = qp.plan_terrain(objects, roles, **kw)
    out = [o for o in objects if o not in remove] + [Obj(*rect) for rect in add]
    return out, remove, add


def tiles(objects):
    """{(x, y): part} of every tile of the terrain."""
    out = {}
    for o in objects:
        for cell in qp.obj_cells(o):
            out[cell] = PART.get((o.tileset, o.original_type), 'other')
    return out


def shape(objects):
    return {(o.objx, o.objy, o.width, o.height, o.tileset, o.original_type) for o in objects}


# ---------------------------------------------------------------- parts and merging

filled = qp.rect_cells(0, 0, 5, 4) - {(4, 0)}  # a 5x4 block with its top-right tile missing
f = lambda x, y: (x, y) in filled
check('outer corners, edges and fill', qp.role_for(f, 0, 0) == 'topLeft' and qp.role_for(f, 1, 0) == 'top'
      and qp.role_for(f, 0, 2) == 'left' and qp.role_for(f, 2, 2) == 'center' and qp.role_for(f, 4, 3) == 'bottomRight'
      and qp.role_for(f, 3, 0) == 'topRight' and qp.role_for(f, 4, 1) == 'topRight')
check('an inner corner where the tile diagonally up-right is empty', qp.role_for(f, 3, 1) == 'innerTopRight')
check('a one tile high platform gets top edges', qp.role_for(lambda x, y: y == 0 and 0 <= x < 4, 1, 0) == 'top')
check('missing parts fall back to similar ones, then the fill',
      qp.object_for({'top': [1, 5], 'center': [1, 9]}, 'topLeft') == (1, 5)
      and qp.object_for({'center': [1, 9]}, 'innerTopLeft') == (1, 9) and qp.object_for({}, 'top') is None)

rects = qp.merge_rectangles({(x, y): 'c' for x in range(10) for y in range(6)})
check('a block of one part becomes one object', rects == [(0, 0, 10, 6, 'c')])

# ---------------------------------------------------------------- painting

level, removed, added = apply([], paint=qp.rect_cells(2, 3, 8, 5))
check('painting an 8x5 rectangle gives 9 objects (4 corners, 4 edges, 1 fill)', len(level) == 9)
t = tiles(level)
check('...with the right parts in the right places', t[(2, 3)] == 'topLeft' and t[(9, 7)] == 'bottomRight'
      and t[(5, 3)] == 'top' and t[(2, 5)] == 'left' and t[(5, 5)] == 'center')
check('...and merged rows and columns', any(o.width == 6 and o.height == 1 for o in level)
      and any(o.width == 1 and o.height == 3 for o in level) and any(o.width == 6 and o.height == 3 for o in level))

before = list(level)
level2, removed, added = apply(level, paint=qp.rect_cells(10, 3, 4, 5))
fresh, _, _ = apply([], paint=qp.rect_cells(2, 3, 12, 5))
check('painting next to terrain joins it: same as painting it all at once', tiles(level2) == tiles(fresh))
check('...and the far edge of the old terrain is left alone (only what changed is redone)',
      any(o is before[0] for o in level2) and not any(o.objx == 2 and o.objy == 3 for o in removed))

level3, removed, added = apply(level2, paint=qp.rect_cells(40, 3, 2, 2))
check('painting away from terrain doesn\'t touch it', not removed and len(added) == 4)

level4, removed, added = apply(level3, erase=qp.rect_cells(6, 3, 2, 2))
t = tiles(level4)
check('erasing a notch out of the top re-tiles around it',
      (6, 3) not in t and t[(6, 5)] == 'top' and t[(5, 3)] == 'topRight' and t[(8, 3)] == 'topLeft'
      and t[(5, 5)] == 'innerTopRight' and t[(8, 5)] == 'innerTopLeft')

level5, removed, added = apply(level4, erase=qp.rect_cells(0, 0, 100, 100))
check('erasing everything removes all the terrain', level5 == [])

# Hand-placed overlapping objects of the preset are cleaned up, not doubled
messy = [Obj(0, 0, 4, 3, KEY['center']), Obj(0, 0, 4, 1, KEY['top'])]
level6, _, _ = apply(messy, regions=qp.rect_cells(0, 0, 4, 3))
check('Re-tile fixes hand-placed, overlapping terrain', tiles(level6) == tiles(apply([], paint=qp.rect_cells(0, 0, 4, 3))[0])
      and sum(o.width * o.height for o in level6) == 12)

other = Obj(20, 20, 3, 2, (2, 50))
level7, removed, added = apply([other], convert=[other])
check('Convert turns other objects into terrain', other in removed and tiles(level7) == tiles(apply([], paint=qp.rect_cells(20, 20, 3, 2))[0]))

level8, removed, added = apply(level7 + [Obj(19, 19, 5, 4, (2, 7))], paint={(23, 20)})
check('objects that aren\'t part of the preset are never changed', not any(o.tileset == 2 for o in removed))

check('nothing to do when the terrain is already right', apply(fresh, regions=qp.rect_cells(2, 3, 12, 5))[1:] == ([], []))

learned = qp.learn_roles(level4)
check('Learn from Selection finds the preset\'s parts from placed terrain',
      all(learned.get(role) == ROLES[role] for role in ('topLeft', 'top', 'center', 'innerTopLeft', 'innerTopRight', 'bottomRight')))

# ---------------------------------------------------------------- strokes

stroke = qp._Stroke(qp.MODE_PAINT, 1, (0, 0), False, 3, ROLES)
stroke.extend((10, 0))
check('a fast drag leaves no gaps and the brush is 3x3', all((x, 0) in stroke.cells for x in range(11))
      and (5, 1) in stroke.cells and (5, 2) not in stroke.cells)
stroke = qp._Stroke(qp.MODE_PAINT, 1, (5, 5), True, 1, ROLES)
stroke.extend((2, 8))
check('Shift + drag fills a rectangle', stroke.cells == qp.rect_cells(2, 5, 4, 4))

# ---------------------------------------------------------------- inner corners, as Nintendo uses them

# In Deluxe's 1-2 (tileset Pa1_1-2_1), object 7 (grass tuft at its top-right) is used where
# role_for says innerTopRight, 9 (tuft top-left) at innerTopLeft, 14 at innerBottomRight and
# 16 at innerBottomLeft. A version 1 preset stored them mirrored (the panel showed them so).
old = {'name': 'Grass', 'roles': {'center': [1, 4], 'innerTopLeft': [1, 14], 'innerTopRight': [1, 16],
                                  'innerBottomLeft': [1, 7], 'innerBottomRight': [1, 9]}}
check('a version 1 preset\'s inner corners are put right',
      qp._migrate(old) and old['roles']['innerTopRight'] == [1, 7] and old['roles']['innerTopLeft'] == [1, 9]
      and old['roles']['innerBottomRight'] == [1, 14] and old['roles']['innerBottomLeft'] == [1, 16]
      and old['version'] == qp.PRESET_VERSION and not qp._migrate(old))
check('the panel lays inner corners out as around a hole (top-left button: open down-right)',
      qp.INNER_ROLES == ('innerBottomRight', 'innerBottomLeft', 'innerTopRight', 'innerTopLeft'))

# ---------------------------------------------------------------- slopes (real Deluxe object definitions)

from yaz0moto.tileset import ObjectDef  # noqa: E402


def objdef(w, h, hexdata):
    d = ObjectDef()
    d.width, d.height = w, h
    d.load(bytes.fromhex(hexdata), 0)
    return d


# Pa1_1-2_1: 4 fill, 10 top, 17/12 45-degree floor slopes up/down, 15/26 ceiling slopes;
# 2:1 slopes from a custom cave tileset as 55-58
DEFS = {(1, 4): objdef(1, 1, '031c01feff'), (1, 10): objdef(4, 1, '012b01012c01012d01012e01feff'),
        (1, 12): objdef(1, 2, '91003001fe84043101feff'), (1, 15): objdef(1, 2, '92003701fe84043801feff'),
        (1, 17): objdef(1, 2, '90003a01fe84043b01feff'), (1, 26): objdef(1, 2, '93008801fe84048901feff'),
        (1, 55): objdef(2, 2, '90009901009a01fe84049b01049c01feff'),
        (1, 56): objdef(2, 2, '91009d01009e01fe84049f0104a001feff'),
        (1, 57): objdef(2, 2, '9200a10100a201fe8404a30104a401feff'),
        (1, 58): objdef(2, 2, '9300a50100a601fe8404a70104a801feff')}
get_def = DEFS.get
check('slope objects are recognised by shape', qp.slope_role_for(DEFS[(1, 17)]) == 'slope1_floorUp'
      and qp.slope_role_for(DEFS[(1, 12)]) == 'slope1_floorDown' and qp.slope_role_for(DEFS[(1, 15)]) == 'slope1_ceilDown'
      and qp.slope_role_for(DEFS[(1, 26)]) == 'slope1_ceilUp' and qp.slope_role_for(DEFS[(1, 55)]) == 'slope2_floorUp'
      and qp.slope_role_for(DEFS[(1, 4)]) is None)
found = qp.find_slopes(1, get_def)
check('Find Slopes in Tileset finds all eight', found == {
    'slope1_floorUp': [1, 17], 'slope1_floorDown': [1, 12], 'slope1_ceilDown': [1, 15], 'slope1_ceilUp': [1, 26],
    'slope2_floorUp': [1, 55], 'slope2_floorDown': [1, 56], 'slope2_ceilDown': [1, 57], 'slope2_ceilUp': [1, 58]})

SR = dict({'center': [1, 4], 'top': [1, 10]}, **found)
PARTS = {(1, 4): 'center', (1, 10): 'top'}


def apply_d(objects, **kw):
    remove, add = qp.TerrainPlanner(objects, SR, get_def).plan(**kw)
    return [o for o in objects if o not in remove] + [Obj(*rect) for rect in add], remove, add


ground, _, _ = apply_d([], paint=qp.rect_cells(0, 10, 16, 3))
planner = qp.TerrainPlanner(ground, SR, get_def)
rect = qp.slope_rect(SR, get_def, (5, 10), (9, 6))
check('a drag up-right from the ground gives a 45-degree floor slope whose foot sits on the ground\'s top row',
      rect == (5, 6, 4, 5, (1, 17)))
cells = planner.slopeCells(*rect)
check('...drawing a step and the tile under it per column, rising one tile per column',
      cells == {(5, 9), (5, 10), (6, 8), (6, 9), (7, 7), (7, 8), (8, 6), (8, 7)})
remove, add, _ = planner.planSlope((5, 10), (9, 6), fill=qp.SLOPE_FILL_STEPS)
level = [o for o in ground if o not in remove] + [Obj(*r) for r in add]
check('the slope is placed last, over the ground under it', add[-1] == rect and len([a for a in add if a[4] == (1, 17)]) == 1)
regular = [o for o in level if (o.tileset, o.original_type) != (1, 17)]
under = set()
for o in regular:
    under |= qp.obj_cells(o)
check('no other object covers the slope\'s tiles', not (under & cells))
check('the space under the slope is filled', {(6, 10), (7, 9), (7, 10), (8, 8), (8, 9), (8, 10)} <= under)
t = {}
for o in regular:
    for c in qp.obj_cells(o):
        t[c] = PARTS[(o.tileset, o.original_type)]
check('the ground left of the slope keeps its top edge (the slope counts as ground)', t[(4, 10)] == 'top')
check('the tiles under the steps are fill', t[(7, 10)] == 'center' and t[(6, 10)] == 'center')

rect2 = qp.slope_rect(SR, get_def, (13, 10), (5, 6))
check('a 2:1 drag gives a 2:1 slope (falling to the right, its foot ending at the corner the drag started from)',
      rect2 is not None and rect2[4] == (1, 56) and rect2[2] == 8 and rect2[3] == 5 and rect2[0] + rect2[2] - 1 == 12
      and rect2[1] + rect2[3] - 1 == 10)
check('steepness can be forced, and a missing one draws nothing',
      qp.slope_rect(SR, get_def, (5, 10), (12, 6), steepness=1)[4] == (1, 17)
      and qp.slope_rect({'center': [1, 4], 'slope2_floorUp': [1, 55]}, get_def, (5, 10), (8, 7), steepness=1) is None)
check('a flat drag draws no slope', qp.slope_rect(SR, get_def, (5, 10), (9, 10)) is None)
ceil = qp.slope_rect(SR, get_def, (5, 4), (9, 8), ceiling=True)
check('on a ceiling, the slope hangs from the ceiling\'s underside (its step\'s ground in the ceiling\'s bottom row)',
      ceil == (5, 3, 4, 5, (1, 15))
      and (5, 3) in planner.slopeCells(*ceil) and (5, 4) in planner.slopeCells(*ceil))

with_slope = level
after, removed, _ = apply_d(with_slope, erase={(7, 7)})
check('erasing any tile of a slope removes the slope', any((o.tileset, o.original_type) == (1, 17) for o in removed)
      and not any((o.tileset, o.original_type) == (1, 17) for o in after))
p2 = qp.TerrainPlanner(with_slope, SR, get_def)
r_remove, r_add, _ = p2.planSlope((5, 10), (10, 5))
check('a new slope over an old one replaces it',
      any((o.tileset, o.original_type) == (1, 17) for o in r_remove) and r_add[-1][2] == 5)
floating = qp.TerrainPlanner([], SR, get_def).planSlope((5, 30), (7, 28), fill=qp.SLOPE_FILL_GROUND)
check('in mid-air the slope gets ground under its steps only (nothing below to reach)',
      floating is not None and max(r[1] + r[3] - 1 for r in floating[1]) == 30)

bare = qp.TerrainPlanner([], SR, get_def).planSlope((5, 30), (9, 26))
check('by default a slope is just the slope object, at the angle drawn (nothing filled under it)',
      bare is not None and bare[0] == [] and bare[1] == [bare[2]] and bare[2][4] == (1, 17))
b_remove, b_add, b_rect = planner.planSlope((5, 10), (9, 6))
b_level = [o for o in ground if o not in b_remove] + [Obj(*r) for r in b_add]
b_under = set()
for o in b_level:
    if (o.tileset, o.original_type) != (1, 17):
        b_under |= qp.obj_cells(o)
check('...also on the ground: the space under its steps stays empty, and the ground stays as it was',
      not ({(7, 9), (8, 8), (8, 9)} & b_under) and {(x, 10) for x in range(0, 16)} - planner.slopeCells(*b_rect) <= b_under
      and b_add[-1] == b_rect)
ground_fill = qp.TerrainPlanner([], SR, get_def).planSlope((5, 30), (7, 28), fill=qp.SLOPE_FILL_STEPS)
check('"ground under its steps" fills only inside the slope\'s box',
      ground_fill is not None and max(r[1] + r[3] - 1 for r in ground_fill[1]) == 30 and len(ground_fill[1]) > 1)

# Every angle: steep (1:2) slopes, and 45-degree ones made of 2x2 steps (as in towers)
DEFS2 = dict(DEFS)
DEFS2[(1, 60)] = objdef(1, 3, '9000e000fe00dd00fe8404dc00feff')  # steep, floor up (Pa0_jyotyu_chika 88)
DEFS2[(1, 61)] = objdef(1, 3, '9100e000fe00de00fe8404df00feff')  # steep, floor down (89)
DEFS2[(1, 62)] = objdef(2, 2, '9000000000ce01fe00cf0100d001feff')  # 45 degrees in 2x2 steps (Pa1_4-21_1 44)
check('steep 1:2 slopes and 45-degree slopes of 2x2 steps are recognised',
      qp.slope_role_for(DEFS2[(1, 60)]) == 'slopeSteep_floorUp' and qp.slope_role_for(DEFS2[(1, 61)]) == 'slopeSteep_floorDown'
      and qp.slope_role_for(DEFS2[(1, 62)]) == 'slope1_floorUp')
found2 = qp.find_slopes(1, DEFS2.get)
check('Find Slopes finds the steep ones too, and prefers the usual 45-degree shape',
      found2.get('slopeSteep_floorUp') == [1, 60] and found2.get('slope1_floorUp') == [1, 17])
SR2 = dict(SR, slopeSteep_floorUp=[1, 60], slopeSteep_floorDown=[1, 61])
seg = qp.slope_segment(SR2, DEFS2.get, (5, 10), (6, 8))
check('a steep line gives a steep slope, one tile across per two up',
      seg is not None and seg[0] == (5, 8, 1, 3, (1, 60)) and seg[1] == (6, 8))
check('...drawing its step and the ground under it',
      qp.TerrainPlanner([], SR2, DEFS2.get).slopeCells(*seg[0]) == {(5, 8), (5, 9), (5, 10)})
only45 = {'center': [1, 4], 'slope1_floorUp': [1, 62]}
seg = qp.slope_segment(only45, DEFS2.get, (0, 10), (4, 6))
check('a 45-degree slope of 2x2 steps climbs two tiles per step', seg is not None and seg[0] == (0, 6, 4, 4, (1, 62))
      and seg[1] == (4, 6))

# Lines of slopes: each piece starts at the corner where the one before really ended
chain = qp.TerrainPlanner([], SR, get_def)
c_remove, c_add, corners = chain.planChain((0, 20), [(4, 16), (8, 16), (12, 20)])
check('a line of points becomes joined pieces: slope up, flat top, slope down',
      corners == [(0, 20), (4, 16), (8, 16), (12, 20)] and [a for a in c_add if a[4] == (1, 17)] == [(0, 16, 4, 5, (1, 17))]
      and [a for a in c_add if a[4] == (1, 12)] == [(8, 16, 4, 5, (1, 12))])
top = {}
for a in c_add:
    cells = chain.slopeCells(*a) if a[4] in ((1, 17), (1, 12)) else qp.rect_cells(*a[:4])
    for (x, y) in cells:
        top[x] = min(top.get(x, y), y)
check('...whose surface has no gaps or steps: up, along and down one tile at a time',
      [top[x] for x in range(12)] == [19, 18, 17, 16, 16, 16, 16, 16, 16, 17, 18, 19])
check('...and nothing is filled under the slopes', all(y <= 17 for a in c_add if a[4] in ((1, 4), (1, 10))
                                                       for (_, y) in qp.rect_cells(*a[:4])))
_, r_add, r_corners = chain.planChain((0, 20), [(10, 16)])
check('a line flatter than the slopes gets the slope, then flat ground the rest of the way',
      r_corners == [(0, 20), (8, 16), (10, 16)] and any(a[4] == (1, 55) for a in r_add))
check('a vertical line places nothing', chain.planChain((0, 20), [(0, 10)]) is None)
_, s_add, s_corners = qp.TerrainPlanner([], SR2, DEFS2.get).planChain((0, 20), [(2, 16), (6, 12)])
check('steep and 45-degree pieces join too', s_corners == [(0, 20), (2, 16), (6, 12)]
      and sorted(a[4] for a in s_add) == [(1, 17), (1, 60)])

fake = [types.SimpleNamespace(obj=DEFS[(1, 4)]), types.SimpleNamespace(obj=DEFS2[(1, 62)]), types.SimpleNamespace(obj=DEFS[(1, 17)])]
check('Find Slopes on a game tileset names its slope objects (the usual shape first)',
      qp.find_game_slopes('unit:X', fake) == {'slope1_floorUp': ['game', 'unit:X', 2]})
with mock.patch.object(qp, 'setting', lambda name, default=None: [{'name': 'G', 'version': 2, 'roles': {
        'center': ['game', 'pack:C:/Objects/Main', 4], 'top': [1, 10], 'left': ['bad'], 'nope': [1, 2]}}]
        if name == 'QuickPaintPresets' else default), mock.patch.object(qp, 'setSetting', lambda *a: None):
    loaded = qp.load_presets()
check('presets keep parts from the Game tab when they are loaded again (and drop broken ones)',
      loaded[0]['roles'] == {'center': ['game', 'pack:C:/Objects/Main', 4], 'top': [1, 10]})
check('every part, the steep slopes too, has a picture for its button',
      all(not qp.role_diagram(role, 32).isNull() for role in qp.ROLES))

globals.LegacyMouseControls = False
check('left drag paints and right drag erases with the new mouse controls',
      qp.strokeButtons() == (qp.Qt.LeftButton, qp.Qt.RightButton))
globals.LegacyMouseControls = True
check('with Legacy mouse controls only right drag paints (left click selects), as in Miyamoto',
      qp.strokeButtons() == (qp.Qt.RightButton,))
globals.LegacyMouseControls = False

learned = qp.learn_from_layers([with_slope], 1, get_def)
check('Auto-detect learns the parts and the tileset\'s slopes from a level',
      learned['center'] == [1, 4] and learned['top'] == [1, 10] and learned['slope1_floorUp'] == [1, 17]
      and learned['slope2_ceilUp'] == [1, 58])

# ---------------------------------------------------------------- the undo step, with real objects

from yaz0moto import items, undomanager  # noqa: E402


class FakeArea:
    def __init__(self):
        self.layers = [[], [], []]

    def RemoveFromLayer(self, obj):
        layer = self.layers[obj.layer]
        idx = layer.index(obj)
        del layer[idx]
        for o in layer[idx:]:
            o.setZValue(o.zValue() - 1)


scene = QtWidgets.QGraphicsScene()
globals.Area = FakeArea()
globals.mainWindow = types.SimpleNamespace(scene=scene, HandleObjPosChange=lambda *a: None)
globals.UndoManager = undomanager.UndoManager()
with mock.patch.object(items.ObjectItem, 'updateObjCache', lambda self: None), \
        mock.patch.object(undomanager.UndoManager, '_on_action_completed', lambda self, initial_push=False: None):
    keep = items.ObjectItem(2, 3, 1, 50, 50, 2, 2, 8192, 0)
    globals.Area.layers[1].append(keep)
    scene.addItem(keep)
    qp.apply_terrain(1, ROLES, paint=qp.rect_cells(0, 0, 6, 4))
    layer = globals.Area.layers[1]
    painted = list(layer)
    check('a stroke adds its objects to the layer and the scene as one undo step',
          len(layer) == 10 and all(o.scene() is scene for o in layer) and len(globals.UndoManager.undo_stack) == 1)
    qp.apply_terrain(1, ROLES, erase={(2, 0)})
    after_erase = [(o.objx, o.objy, o.width, o.height, o.original_type) for o in layer]
    globals.UndoManager.undo()
    check('undo puts the terrain back exactly, objects and order', layer == painted
          and all(o.scene() is scene for o in layer))
    globals.UndoManager.undo()
    check('undoing the stroke leaves only what was there before', layer == [keep] and keep.scene() is scene
          and len([i for i in scene.items() if isinstance(i, items.ObjectItem)]) == 1)
    globals.UndoManager.redo()
    globals.UndoManager.redo()
    check('redo paints and erases again', [(o.objx, o.objy, o.width, o.height, o.original_type) for o in layer] == after_erase)
    zs = [o.zValue() for o in layer]
    check('objects keep increasing Z values in layer order', zs == sorted(zs) and len(set(zs)) == len(zs))

    # The live preview hides what a stroke removes and gives it back when the stroke ends
    stroke = qp._Stroke(qp.MODE_ERASE, 1, (1, 1), False, 2, ROLES)
    remove, add = stroke.plan()
    qp._preview.show(remove, add)
    check('while erasing, the objects being redone are hidden and the new ones are ready to draw',
          remove and all(getattr(o, 'previewHidden', False) for o in remove) and qp._preview.add == add)
    qp._preview.clear()
    check('...and shown again when the stroke ends', not any(getattr(o, 'previewHidden', False) for o in remove) and not qp._preview.add)

    # A slope stroke through the real command: placed last (on top), one undo step
    with mock.patch.object(qp, 'global_def', lambda key: DEFS.get(tuple(key))):
        globals.Area.layers[1][:] = []
        for o in [i for i in scene.items() if isinstance(i, items.ObjectItem)]:
            scene.removeItem(o)
        qp.apply_terrain(1, SR, paint=qp.rect_cells(0, 10, 16, 3))
        n = len(globals.UndoManager.undo_stack)
        stroke = qp._Stroke(qp.MODE_SLOPE, 1, (5, 10), False, 1, SR, (0, False, True))
        stroke.extend((8, 7))
        remove, add = stroke.plan()
        qp.apply_plan(1, remove, add, 'Quick Paint Slope')
        layer = globals.Area.layers[1]
        check('a slope stroke is one undo step and the slope is drawn over everything else on the layer',
              len(globals.UndoManager.undo_stack) == n + 1 and layer[-1].original_type == 17
              and layer[-1].zValue() == max(o.zValue() for o in layer))
        globals.UndoManager.undo()
        check('undoing it takes the slope away', not any(o.original_type == 17 for o in layer))

    # Parts from the Game tab: planned as the game objects, copied into the level when placed
    copies = {}

    def fake_copy(ref, create=True):
        k = tuple(ref)
        if k not in copies and create and k[2] != 99:
            copies[k] = (2, 40 + len(copies))
        return copies.get(k)

    with mock.patch.object(qp.gametilesets, 'level_copy', fake_copy):
        game = {'center': ['game', 'unit:Pa1_6-1_1', 0], 'top': ['game', 'unit:Pa1_6-1_1', 1]}
        check('game parts not copied yet are planned as the game objects',
              qp.planning_roles(game)['center'] == ['game', 'unit:Pa1_6-1_1', 0])
        layer = globals.Area.layers[1]
        n0 = len(layer)
        qp.apply_terrain(1, game, paint=qp.rect_cells(30, 30, 3, 2))
        new = layer[n0:]
        check('painting copies them into the level\'s tilesets and places the copies',
              new and set(copies) == {('game', 'unit:Pa1_6-1_1', 0), ('game', 'unit:Pa1_6-1_1', 1)}
              and all((o.tileset, o.original_type) in copies.values() for o in new))
        check('...after which they are planned as the copies (so that terrain is recognised)',
              qp.planning_roles(game)['center'] == list(copies[('game', 'unit:Pa1_6-1_1', 0)]))
        n1 = len(layer)
        steps = len(globals.UndoManager.undo_stack)
        qp.apply_terrain(1, {'center': ['game', 'unit:Pa1_6-1_1', 99]}, paint=qp.rect_cells(40, 30, 2, 2))
        check('if a game object doesn\'t fit in the level\'s tilesets nothing is placed',
              len(layer) == n1 and len(globals.UndoManager.undo_stack) == steps)

print('-- a preset made for another tileset')
globals.Area.tileset1 = 'Pa1_1-1_1'
mixed = {'name': 'Terrain', 'tileset': 'Pa1_1-2_1',
         'roles': {'center': ['game', 'pack:x', 4], 'top': [1, 6], 'left': [1, 9]}}
check('a preset with level-tileset parts is tied to its tileset', qp.tileset_bound(mixed))
check('one with only game parts is not', not qp.tileset_bound({'roles': {'center': ['game', 'pack:x', 4]}}))
check('it is mismatched in an area using another tileset', qp.mismatched(mixed) == 'Pa1_1-2_1')
globals.Area.tileset1 = 'Pa1_1-2_1'
check('...and not in one using its own', qp.mismatched(mixed) is None)
check('game-only presets are never mismatched',
      qp.mismatched({'tileset': 'Pa1_9-9_9', 'roles': {'center': ['game', 'pack:x', 4]}}) is None)
del globals.Area.tileset1

failed = [label for label, ok in results if not ok]
print('\n%d/%d passed' % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
