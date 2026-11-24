"""
Tests for Quick Paint's Shape mode (yaz0moto/qpshapes.py): snapping points to the allowed
directions, the tiles inside an outline, the slope objects for its sloped sides, editing a
placed shape, and keeping the outlines beside the level.

Run from anywhere:   python tests/qpshapes_test.py
"""
import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import os
import sys
import tempfile
import types

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

try:
    import fastyz  # noqa: F401
except ImportError:
    sys.modules['fastyz'] = types.SimpleNamespace(compress=lambda d: b'Yaz0' + bytes(12) + d,
                                                  decompress=lambda d: d[16:])

from PyQt5 import QtWidgets  # noqa: E402
app = QtWidgets.QApplication([])

from yaz0moto import globals  # noqa: E402
from yaz0moto import quickpaint as qp  # noqa: E402
from yaz0moto import qpshapes as sh  # noqa: E402
from yaz0moto.tileset import ObjectDef  # noqa: E402

results = []


def check(label, ok):
    results.append((label, bool(ok)))
    print(('  OK  ' if ok else 'FAIL  ') + label)


def objdef(w, h, hexdata):
    d = ObjectDef()
    d.width, d.height = w, h
    d.load(bytes.fromhex(hexdata), 0)
    return d


# Pa1_1-2_1's terrain (fill 4, top 10, 45-degree slopes 17/12 floor, 15/26 ceiling) and 2:1 floor slopes
DEFS = {(1, 4): objdef(1, 1, '031c01feff'), (1, 10): objdef(4, 1, '012b01012c01012d01012e01feff'),
        (1, 12): objdef(1, 2, '91003001fe84043101feff'), (1, 15): objdef(1, 2, '92003701fe84043801feff'),
        (1, 17): objdef(1, 2, '90003a01fe84043b01feff'), (1, 26): objdef(1, 2, '93008801fe84048901feff'),
        (1, 55): objdef(2, 2, '90009901009a01fe84049b01049c01feff'),
        (1, 56): objdef(2, 2, '91009d01009e01fe84049f0104a001feff')}
get = DEFS.get
ROLES = {'center': [1, 4], 'top': [1, 10], 'slope1_floorUp': [1, 17], 'slope1_floorDown': [1, 12],
         'slope1_ceilDown': [1, 15], 'slope1_ceilUp': [1, 26], 'slope2_floorUp': [1, 55], 'slope2_floorDown': [1, 56]}


class Obj:
    def __init__(self, rect):
        self.objx, self.objy, self.width, self.height, (self.tileset, self.original_type) = rect


units = sh.diagonal_units(ROLES, get)
check('the preset\'s slope angles are the directions sides can take', sorted(units) == [(1, 1), (2, 1)])
check('a point snaps flat, straight up, or along a slope angle in whole steps',
      sh.snap((0, 10), (5.2, 10.4), units) == (5, 10) and sh.snap((0, 10), (0.3, 4.2), units) == (0, 4)
      and sh.snap((0, 10), (3.1, 7.2), units) == (3, 7) and sh.snap((0, 10), (6.3, 6.8), units) == (6, 7))
check('a dragged point goes where an allowed side from each neighbour meets',
      sh.snap_between((8, 2), (17, 6), (13.4, 6.6), [(1, 1)]) == (12, 6)
      and sh.snap_between((8, 2), (17, 6), (12.5, 2.4), [(1, 1)]) == (13, 2)
      and sh.snap_between((8, 2), (17, 6), (15.8, 6.3), [(1, 1), (2, 1)]) == (16, 6))
steep = sh.refine([(0, 10), (2, 6), (6, 6), (6, 10)], [(1, 1)])
check('a side at an angle the tiles cannot make is built from the nearest slope plus straight bits',
      steep == [(0, 10), (0, 7), (1, 7), (2, 6), (6, 6), (6, 10)]
      and all(sh.valid_side(steep[i], steep[(i + 1) % len(steep)], [(1, 1)]) for i in range(len(steep))))
check('...or a step when no slope angle fits', sh.refine([(0, 4), (3, 0), (3, 4)], []) == [(0, 4), (0, 0), (3, 0), (3, 4)])
check('a node placed near an exact angle goes there, elsewhere it stays where it was put',
      sh.snap_free((0, 10), (3.2, 7.1), [(1, 1)]) == (3, 7) and sh.snap_free((0, 10), (2.1, 6.0), [(1, 1)]) == (2, 6))
_, free_slopes = sh.parts([(0, 10), (2, 6), (6, 6), (6, 10)], ROLES, get)
check('...and the shape still gets its slope', len(free_slopes) == 1 and free_slopes[0][4] == (1, 17))
check('a slope running into a cliff ends a step early with flat ground before the drop (slope tiles have no edge)',
      sh.refine([(9, 12), (9, 6), (13, 6), (13, 2), (15, 2), (19, 6), (19, 12)], [(2, 1)])
      == [(9, 12), (9, 6), (13, 6), (13, 2), (15, 2), (17, 3), (19, 3), (19, 6), (19, 12)])
check('...but a slope too short to lose a step keeps it, and slopes meeting flat ground are left alone',
      sh.refine([(0, 10), (2, 9), (2, 14), (0, 14)], [(2, 1)]) == [(0, 10), (2, 9), (2, 14), (0, 14)]
      and sh.refine([(0, 14), (0, 6), (5, 6), (5, 2), (8, 2), (12, 6), (17, 6), (17, 14)], [(1, 1)])
      == [(0, 14), (0, 6), (5, 6), (5, 2), (8, 2), (12, 6), (17, 6), (17, 14)])
check('sides are checked the same way', sh.valid_side((0, 0), (4, 2), units) and not sh.valid_side((0, 0), (3, 2), units)
      and sh.valid_side((0, 0), (0, 5), units) and not sh.valid_side((0, 0), (0, 0), units))
check('outlines lose repeated points and spikes, but keep points added on a side',
      sh.cleaned([(0, 0), (2, 0), (4, 0), (4, 0), (4, 3), (6, 3), (4, 3), (0, 3), (0, 0)])
      == [(0, 0), (2, 0), (4, 0), (4, 3), (0, 3)])
check('crossing outlines are refused', not sh.simple([(0, 0), (4, 4), (4, 0), (0, 4)]) and sh.simple([(0, 0), (4, 0), (4, 4)]))

# A hill like the photos: a step up, a 45-degree slope down and a flat top
hill = [(0, 10), (0, 6), (4, 6), (4, 2), (6, 2), (10, 6), (14, 6), (14, 14), (0, 14)]
cells, slopes = sh.parts(hill, ROLES, get)
check('the tiles inside the outline are filled', (1, 7) in cells and (5, 3) in cells and (13, 13) in cells
      and (2, 5) not in cells and (14, 7) not in cells and (8, 3) not in cells)
check('the sloped side gets the 45-degree floor slope, falling to the right', slopes == [(6, 2, 4, 5, (1, 12))])

remove, add, placed = sh.plan([], ROLES, hill, get_def=get)
level = [Obj(r) for r in add]
check('placing it makes terrain plus the slope, the slope last', placed == slopes and add[-1] == slopes[0] and not remove)
covered = set()
for o in level[:-1]:
    covered |= qp.rect_cells(o.objx, o.objy, o.width, o.height)
slope_cells = qp.TerrainPlanner([], ROLES, get).slopeCells(*slopes[0])
check('the terrain fills the inside around the slope without covering it',
      (cells - slope_cells) <= covered and not (covered & slope_cells))

ceil = [(0, 0), (10, 0), (10, 2), (6, 2), (2, 6), (0, 6)]
_, cslopes = sh.parts(ceil, ROLES, get)
check('a sloped side under the inside gets a ceiling slope', len(cslopes) == 1 and cslopes[0][4] in ((1, 15), (1, 26)))

gentle = [(0, 10), (8, 6), (12, 6), (12, 12), (0, 12)]
_, gslopes = sh.parts(gentle, ROLES, get)
check('a 2:1 side gets the 2:1 slope (a step short of the cliff at its foot)', len(gslopes) == 1 and gslopes[0][4] == (1, 55) and gslopes[0][0] == 2 and gslopes[0][2] == 6)
noslopes = {'center': [1, 4]}
_, none = sh.parts(gentle, noslopes, get)
check('a side whose slope the preset lacks stays a staircase', none == [] and sh.diagonal_units(noslopes, get) == [])

# Editing: move the hill's peak point; the old slope goes, the new one comes, nothing is left behind
shape = {'points': [list(p) for p in hill], 'slopes': [list(r[:4]) for r in slopes]}
moved = [p if p != (6, 2) else (6, 2) for p in hill]
moved[hill.index((10, 6))] = (12, 8)
moved[hill.index((14, 6))] = (14, 8)
r2, a2, s2 = sh.plan(level, ROLES, moved, shape, get_def=get)
after = [o for o in level if o not in r2] + [Obj(r) for r in a2]
check('editing the shape replaces its slope with the new one', any(o.width == 4 and qp.is_diagonal(get((o.tileset, o.original_type)))
                                                                   and (o.objx, o.objy) == (6, 2) for o in r2)
      and s2 == [(6, 2, 6, 7, (1, 12))] or s2 and s2[0][4] == (1, 12))
now = set()
for o in after:
    if not qp.is_diagonal(get((o.tileset, o.original_type))):
        now |= qp.rect_cells(o.objx, o.objy, o.width, o.height)
check('...and the terrain matches the new outline', (sh.interior(moved) - set().union(*[qp.TerrainPlanner([], ROLES, get).slopeCells(*r) for r in s2])) <= now
      and not any(sh.inside(x + 0.5, y + 0.5, moved) is False and (x, y) in now for (x, y) in now))
r3, a3, _ = sh.plan(after, ROLES, [], {'points': moved, 'slopes': [list(r[:4]) for r in s2]}, get_def=get)
left = [o for o in after if o not in r3] + [Obj(r) for r in a3]
check('deleting the shape removes all its terrain and slopes', not left)
keep = sh.interior([(0, 12), (14, 12), (14, 20), (0, 20)])
r4, a4, _ = sh.plan(after, ROLES, [], {'points': moved, 'slopes': [list(r[:4]) for r in s2]}, keep=keep, get_def=get)
rest = set()
for o in [o for o in after if o not in r4] + [Obj(r) for r in a4]:
    rest |= qp.rect_cells(o.objx, o.objy, o.width, o.height)
check('...except where another shape overlaps it', rest and rest <= keep | sh.interior(moved) and (5, 13) in rest)

# Keeping the outlines beside the level, per level and area
tmp = tempfile.mkdtemp(prefix='y0shapes')
globals.user_data_path = tmp
globals.mainWindow = types.SimpleNamespace(fileSavePath=os.path.join(tmp, '1-1.szs'))
globals.CurrentArea = 2
globals.Level = object()
sh._store.clear()
sh._loaded.clear()
sh.area_shapes().append({'points': [[0, 0], [4, 0], [4, 4]], 'layer': 1, 'roles': ROLES, 'slopes': []})
sh.level_saved(globals.mainWindow.fileSavePath)
sh._store.clear()
sh._loaded.clear()
check('the shapes are saved with the level and come back when it is opened again',
      sh.area_shapes() and sh.area_shapes()[0]['points'] == [[0, 0], [4, 0], [4, 4]])
globals.CurrentArea = 1
check('...for their own area only', sh.area_shapes() == [])
globals.mainWindow = types.SimpleNamespace(fileSavePath=None)
unsaved = sh.area_shapes()
unsaved.append({'points': [[1, 1], [3, 1], [3, 3]], 'layer': 1, 'roles': ROLES, 'slopes': []})
newpath = os.path.join(tmp, 'new.szs')
sh.level_saved(newpath)
globals.mainWindow = types.SimpleNamespace(fileSavePath=newpath)
check('a new level\'s shapes go with it when it is first saved', sh.area_shapes() == unsaved)

# sides the preset has no slope for are reported (and built from the slopes it has)
hill45 = [(0, 10), (0, 6), (4, 6), (8, 10)]  # a 45-degree floor going down on the right
check('a side the preset has a slope for is buildable', not sh.unbuilt(hill45, ROLES, get))
no_down = {k: v for k, v in ROLES.items() if k != 'slope1_floorDown'}
check('...one it lacks that slope for is reported %s' % sh.unbuilt(hill45, no_down, get),
      [i for i, _ in sh.unbuilt(hill45, no_down, get)] == [2] and 'floor slope going down' in sh.unbuilt_note(hill45, no_down, get))
check('a flat box has nothing to report', not sh.unbuilt([(0, 0), (4, 0), (4, 4), (0, 4)], no_down, get))

failed = [label for label, ok in results if not ok]
print('\n%d/%d passed' % (len(results) - len(failed), len(results)))
sys.stdout.flush()
os._exit(1 if failed else 0)
