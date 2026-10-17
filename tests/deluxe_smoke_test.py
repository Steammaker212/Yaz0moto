"""
Smoke test for New Super Mario Bros. U Deluxe support.

Builds a fake Deluxe install (Course/ + Unit/ with a synthetic tileset), then drives
Pyamoto's real game-definition, tileset and level code against it:
  * game definition / platform switching / path validation
  * loading a Yaz0 SARC tileset (BFRES + BNTX) from Unit/
  * saving a tileset back into Unit/ and reloading it pixel-for-pixel
  * saving a level as a flat little-endian SARC and loading it again

Run from anywhere:   python tests/deluxe_smoke_test.py
Needs PyQt5 and the compiled/pyximport extensions Pyamoto already requires.
"""
import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
import sys, os, struct, tempfile, random, shutil
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PyQt5 import QtGui, QtWidgets
app = QtWidgets.QApplication([])
def _no_dialogs(self, *a):
    raise RuntimeError('unexpected dialog: ' + str(self.text()) + ' | ' + str(self.informativeText()))
QtWidgets.QMessageBox.exec_ = _no_dialogs
QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError('unexpected warning: ' + str(a[1:3]))))

import miyamoto.app  # installs pyximport (builds fastyz) and imports everything
from miyamoto import globals
from miyamoto.misc import JsonSettings, setting, setSetting
from miyamoto import tileset as T, loading, yaz0
import SarcLib

tmp = tempfile.mkdtemp()
globals.user_data_path = tmp
globals.settings = JsonSettings(os.path.join(tmp, 'settings.json'))

course = os.path.join(tmp, 'game', 'Course'); unit = os.path.join(tmp, 'game', 'Unit')
os.makedirs(course); os.makedirs(unit)

# ---------- synthetic Deluxe tileset ("Pa0_jyotyu") in Unit/
random.seed(7)
W, H = 2048, 512
def tex():
    return bytes(random.getrandbits(8) for _ in range(W * H * 4))
_pat = bytearray(random.getrandbits(8) for _ in range(256))
for _i in range(3, 256, 4): _pat[_i] = 255            # opaque, so Qt's premultiplication doesn't alter colours
main_tex = bytes(_pat) * (W * H * 4 // 256); nml_tex = bytes(reversed(main_tex[:256])) * (W * H * 4 // 256)
nml_tex = bytes(bytearray(nml_tex[i] if i % 4 != 3 else 255 for i in range(len(nml_tex))))
name = 'Pa0_jyotyu'
globals.IsNSMBUDX = True          # PackTexture/Save paths read this
bntx = T.writeBNTX([(name, main_tex, W, H), (name + '_nml', nml_tex, W, H)])
tpl = open(os.path.join(ROOT, 'miyamotodata', 'games', 'NSMBUDX', 'output.bfres'), 'rb').read()
arc = SarcLib.SARC_Archive(endianness='<')
arc.addFile(SarcLib.File('output.bfres', bytes(T.writeBFRES(tpl, bntx))))
coll = b''.join(struct.pack('<Q', 0) for _ in range(256))
chk = SarcLib.Folder('BG_chk'); arc.addFolder(chk); chk.addFile(SarcLib.File('d_bgchk_%s.bin' % name, coll))
deffile = bytes([5, 0, 0, 0xFE, 0xFF])               # one 1x1 object: tile 5, end of row, end of object
index = struct.pack('<HBBH', 0, 1, 1, 0)               # little-endian index entry
unt = SarcLib.Folder('BG_unt'); arc.addFolder(unt)
unt.addFile(SarcLib.File('%s.bin' % name, deffile)); unt.addFile(SarcLib.File('%s_hd.bin' % name, index))
assert yaz0.compressFASTYZ(arc.save()[0], os.path.join(unit, name + '.szs'))

results = []
def check(label, ok):
    results.append((label, bool(ok))); print(('PASS ' if ok else 'FAIL ') + label)

# ---------- game definition
setSetting('GamePath_NSMBUDX', course)
globals.IsNSMBUDX = False
loading.LoadGameDef('NSMBUDX', [])
check('LoadGameDef sets IsNSMBUDX', globals.IsNSMBUDX is True)
check('file extensions are .sarc only', globals.FileExtentions == ('.sarc',))
check('blankcourse is the Deluxe one', globals.gamedef.file('blankcourse').replace('\\','/').endswith('games/NSMBUDX/blankcourse.bin'))
check('game paths exclude the Wii U base', [p for p in globals.gamedef.GetGamePaths() if p] == [course])
check('Unit folder resolved', globals.gamedef.GetUnitPaths() == [unit])
check('tileset file found', globals.gamedef.FindTilesetFile(name) == os.path.join(unit, name + '.szs'))
check('HasTileset true/false', T.HasTileset(name) and not T.HasTileset('Pa1_nope'))
from miyamoto.verifications import isValidGamePath
open(os.path.join(course, '1-1.sarc'), 'wb').write(b'x')
check('isValidGamePath(DX) needs Course+Unit', isValidGamePath(course, 'NSMBUDX'))
os.rename(unit, unit + '_x'); check('isValidGamePath(DX) fails w/o Unit', not isValidGamePath(course, 'NSMBUDX')); os.rename(unit + '_x', unit)

# ---------- tileset load through the real loader
loading.LoadOverrides()
from miyamoto.level import Level_NSMBU
globals.Level = Level_NSMBU(); globals.Level.new()    # also runs CreateTilesets()
globals.Pa0Tilesets = ['Pa0_jyotyu']
try:
    for slot in range(4):            # the area loader fills all four slots
        loading._LoadTileset(slot, name)
    ok = True
except Exception as e:
    import traceback; traceback.print_exc(); ok = False
check('_LoadTileset (Deluxe) ran', ok)
if ok:
    check('256 tiles loaded', all(globals.Tiles[i] is not None for i in range(256)))
    d = globals.ObjectDefinitions[0][0]
    check('object def parsed (little-endian index)', d is not None and d.width == 1 and d.height == 1)
    # tile 0 image should be the 60x60 crop of the texture at (2,2)
    img = main_tex
    def px(x, y): o = (y * W + x) * 4; return tuple(img[o:o+4])
    t0 = globals.Tiles[0].main.toImage() if hasattr(globals.Tiles[0], 'main') else None
    if t0 is not None:
        c = QtGui.QColor(t0.pixel(0, 0)); got = (c.red(), c.green(), c.blue(), c.alpha())
        check('tile 0 pixels match texture data', got == px(2, 2))


# ---------- saving a tileset into Unit/ (Deluxe) and reading it back
def tile_px(i):
    return globals.Tiles[i].main.toImage().convertToFormat(QtGui.QImage.Format_RGBA8888)
def raw(img):
    pt = img.bits(); pt.setsize(img.byteCount()); return bytes(pt)
before = [raw(tile_px(256 + k)) for k in (0, 1, 17, 100, 255)]
globals.Area.tileset1 = 'Pa1_tmp'
try:
    res = T.SaveTileset(1)
    ok = True
except Exception:
    import traceback; traceback.print_exc(); ok = False; res = 'err'
check('SaveTileset(1) ran and returned nothing to embed', ok and res is None)
newname = globals.Area.tileset1
check('tileset renamed to its hash name', newname.startswith('Pa1_') and newname != 'Pa1_tmp')
saved = os.path.join(unit, newname + '.szs')
check('tileset written into Unit/', os.path.isfile(saved))
data = open(saved, 'rb').read()
check('Unit file is Yaz0 -> little-endian SARC', data[:4] == b'Yaz0' and yaz0.decompressFASTYZ(data)[6:8] == b'\xff\xfe')
loading._LoadTileset(1, newname)
after = [raw(tile_px(256 + k)) for k in (0, 1, 17, 100, 255)]
check('saved tileset reloads with identical tiles', before == after)

# ---------- level save -> flat little-endian SARC -> load
area = globals.Level.areas[0]
lvl_bytes = globals.Level.save()
check('level saves as SARC', lvl_bytes[:4] == b'SARC')
check('level SARC is little-endian', lvl_bytes[6:8] == b'\xff\xfe')
a2 = SarcLib.SARC_Archive(); a2.load(lvl_bytes)
names = [f.name for f in a2['course'].contents]
check('level holds course files only (no embedded tilesets)', 'course1.bin' in names and not any(n.startswith('Pa') for n in names) and len(a2.contents) == 1)
c1 = a2['course/course1.bin'].data
off, size = struct.unpack('<II', c1[:8])
check('course block table is little-endian and sane', 0 < off < len(c1) and 0 < size < len(c1))
check('tileset names in course data match', newname.encode() in c1)

lvl2 = Level_NSMBU(); globals.Level = lvl2
try:
    loaded = lvl2.load(lvl_bytes, 1)
except Exception:
    import traceback; traceback.print_exc(); loaded = False
check('saved Deluxe level loads back', loaded and len(lvl2.areas) == 1)
if loaded:
    A = lvl2.areas[0]
    check('tileset slot 1 name survived the round trip', A.tileset1 == newname)


# ---------- zone background tab: the "ushort format requires 0 <= number <= 0xffff" crash
from miyamoto.dialogs import BGTab, ChooseLevelNameDialog
from miyamoto.bytes import to_bytes
import struct as _struct

def bg_tuple(parallax, name='Mori'):
    return (0, 0, 0, 0, to_bytes(name, 16), parallax)

tab = BGTab(bg_tuple(7))                       # a stored value the 5-entry dropdown has no name for
check('out-of-range parallax is shown, not blank', tab.parallaxMode.currentIndex() >= 0 and 'Unknown (7)' in tab.parallaxMode.currentText())
check('out-of-range parallax round-trips unchanged', tab.parallaxValue() == 7)
check('in-range parallax still maps to its index', BGTab(bg_tuple(3)).parallaxValue() == 3)
tab.parallaxMode.setCurrentIndex(1)
check('user can pick a named mode afterwards', tab.parallaxValue() == 1)
check('parallax value is never negative', all(BGTab(bg_tuple(v)).parallaxValue() >= 0 for v in (0, 4, 5, 9, 65535)))

import types
def pack_zone(parallax):
    area = globals.Area
    saved = area.zones
    area.zones = [types.SimpleNamespace(id=0, background=(0, 0, 0, 0, to_bytes('Mori', 16), parallax))]
    try:
        return area.GetOptimizedBGs(_struct.Struct('<Hhhh16sHxx'))
    finally:
        area.zones = saved

try:
    packed = pack_zone(BGTab(bg_tuple(7)).parallaxValue()); ok = packed[1] == 1 and packed[0][0][5] == 7
except Exception:
    import traceback; traceback.print_exc(); ok = False
check('GetOptimizedBGs packs a zone with an unnamed parallax mode (the crash)', ok)
try:
    pack_zone(-1); crashed = False
except _struct.error:
    crashed = True
check('a negative parallax value really is what crashed before', crashed)

# ---------- Deluxe background file names
check('Deluxe background file name', BGTab.fileNameFor('Mori') == 'dv_Mori.Nin_NX_NVN.szs')
check('Deluxe background folder', BGTab.fileFolder() == 'romfs/Model')
_keep = BGTab(bg_tuple(0))
check('tab label uses the Deluxe name', _keep._filenameLabel.text() == 'dv_Mori.Nin_NX_NVN.szs')
check('tab custom-name suffix uses the Deluxe name', _keep._szsLabel.text() == '.Nin_NX_NVN.szs')
globals.IsNSMBUDX = False
check('Wii U background file name unchanged', BGTab.fileNameFor('Mori') == 'dv_Mori.szs' and BGTab.fileFolder() == 'content/Common/distant_view')
globals.IsNSMBUDX = True

# ---------- level picker lists level files that have no name
lv = os.path.join(tmp, 'lv'); os.makedirs(lv)
for n in ('1-1', '1-2', '40-1', '40-10', '40-2'):
    open(os.path.join(lv, n + '.sarc'), 'wb').write(b'x')
named = [['World 1', [['Level 1', '1-1'], ['Level 2', '1-2']]]]
out = ChooseLevelNameDialog._supplementUnlisted(named, lv)
extra = [c for cat in out if cat[0] == 'Uncategorized' for c in cat[1]]
check('unlisted levels are added, listed ones are not', [c[1] for c in extra] == ['40-1', '40-2', '40-10'])
check('the shared name list is not modified', named == [['World 1', [['Level 1', '1-1'], ['Level 2', '1-2']]]])


# ---------- Deluxe tileset editor (Puzzle): open, edit, save into Unit/, export, re-import
from unittest import mock
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QColor
import miyamoto.app as appmod
from miyamoto import puzzle

def solid(color, w=60, h=60):
    pm = QPixmap(w, h); pm.fill(QColor(*color)); return pm
def px(pm, x=0, y=0):
    c = QColor(pm.toImage().pixel(x, y)); return (c.red(), c.green(), c.blue())

A = globals.Area
A.tileset0, A.tileset1, A.tileset2, A.tileset3 = name, newname, '', ''
globals.app = app
globals.mainWindow = mock.MagicMock()           # the editor reports back to the main window

slots = appmod.MiyamotoWindow._tilesetSlotsData()
check('editor slots come from the Unit folder', slots[0][0] == name and slots[1][0] == newname
      and slots[0][1][:4] == b'SARC' and slots[1][1][:4] == b'SARC' and slots[2][2] and slots[3][2])
check('slot archives are little-endian SARCs', slots[0][1][6:8] == b'\xff\xfe')

win = puzzle.MainWindow(slots, Qt.Dialog)
check('editor window opens every Deluxe slot', not win.forceClose and len(win.editors) == 4)
ed0, ed1 = win.editors[0], win.editors[1]
check('main tileset: 256 tiles decoded from BNTX', len(ed0.tileset.tiles) == 256)
check('main tileset: tile pixels match the texture', px(ed0.tileset.tiles[0].image) == px(QPixmap.fromImage(
      QtGui.QImage(main_tex[: W * 4 * 4 + 0] and main_tex, W, H, QtGui.QImage.Format_RGBA8888)).copy(2, 2, 1, 1)))
check('main tileset: object definitions read (little-endian index)',
      len(ed0.tileset.objects) == 1 and ed0.tileset.objects[0].width == 1 and ed0.tileset.objects[0].height == 1)
check('empty slots become new blank tilesets', len(win.editors[2].tileset.tiles) == 256)

# edit a tile in slot 2 and save: must write a new hash-named file into Unit/
ed1.tileset.tiles[5].image = solid((10, 200, 30))
ed1.setDirty()
oldname = A.tileset1
ed1.saveTileset()
check('saving slot 2 renames it and updates the level', A.tileset1 != oldname and A.tileset1.startswith('Pa1_'))
newfile = globals.gamedef.FindTilesetFile(A.tileset1)
check('saved tileset is in Unit/', newfile is not None and os.path.dirname(newfile) == unit)
check('editor marked clean after saving', not ed1.isDirty)
re1 = puzzle.TilesetEditor(win, A.tileset1, appmod.MiyamotoWindow._tilesetSlotsData()[1][1], 1, False)
check('edited tile survives save -> reload', not re1.forceClose and px(re1.tileset.tiles[5].image, 30, 30) == (10, 200, 30))
check('untouched tile also survives', px(re1.tileset.tiles[17].image) == px(ed1.tileset.tiles[17].image))

# export as a standalone .szs and import it back
exported = os.path.join(tmp, 'export', 'Pa1_exported.szs'); os.makedirs(os.path.dirname(exported))
with mock.patch.object(QtWidgets.QFileDialog, 'getSaveFileName', return_value=(exported, '')):
    ed1.saveTilesetAs()
raw_exp = open(exported, 'rb').read() if os.path.isfile(exported) else b''
check('Export Tileset writes a Yaz0 .szs', raw_exp[:4] == b'Yaz0')
exp_arc = SarcLib.SARC_Archive(); exp_arc.load(yaz0.decompressFASTYZ(raw_exp)) if raw_exp else None
check('exported archive is little-endian with a BFRES and the right internal names',
      raw_exp != b'' and exp_arc.endianness == '<' and exp_arc['output.bfres'].data[:4] == b'FRES'
      and exp_arc['BG_chk/d_bgchk_Pa1_exported.bin'].data is not None)
imp = win.editors[3]                          # an empty slot of the open window
with mock.patch.object(QtWidgets.QFileDialog, 'getOpenFileName', return_value=(exported, '')):
    imp.openTilesetfromFile()
check('Import Tileset from file reads the exported .szs', px(imp.tileset.tiles[5].image, 30, 30) == (10, 200, 30))

# animations (main tileset): frames survive save -> reload through the BNTX
anim = ed0.animWidget.block
frames = [solid((20 * (i + 1), 0, 0), anim.blockWidth * 60, anim.blockHeight * 60) for i in range(4)]
anim.frames = frames; anim.update()
entries = ed0.animWidget.save()
check('animation save yields Deluxe (name, raw, w, h) entries', entries and len(entries[0]) == 4
      and entries[0][0] == anim.name and entries[0][2] == anim.blockWidth * 64)
ed0.setDirty(); globals._dxMainTilesetConfirmed = True    # skip the "overwrite main tileset?" prompt
before_main = os.path.getmtime(os.path.join(unit, name + '.szs'))
ed0.saveTileset()
check('saving the main tileset rewrites its file in Unit/', os.path.getmtime(os.path.join(unit, name + '.szs')) >= before_main)
re0 = puzzle.TilesetEditor(win, name, appmod.MiyamotoWindow._tilesetSlotsData()[0][1], 0, False)
check('animation frames reload', len(re0.animWidget.block.frames) == 4)
check('animation frame colours survive', [px(f, 30, 30) for f in re0.animWidget.block.frames] == [(20 * (i + 1), 0, 0) for i in range(4)])
check('main tileset still has its object after re-saving', len(re0.tileset.objects) == 1)


# ---------- a REAL tileset (the bundled Wii U Pa0_jyotyu) converted to Deluxe must survive intact
import hashlib
def _h(b): return hashlib.sha256(b).hexdigest()[:16]
def _raw(pm):
    i = pm.toImage().convertToFormat(QtGui.QImage.Format_RGBA8888); q = i.bits(); q.setsize(i.byteCount()); return bytes(q)
def _snapshot(e):
    a = e.animWidget
    return dict(tiles=_h(b''.join(_raw(t.image) for t in e.tileset.tiles)),
                normals=_h(b''.join(_raw(t.normalmap) for t in e.tileset.tiles)),
                collision=_h(e.PackTiles()), objects=len(e.tileset.objects), object_data=_h(e.PackObjects()[0]),
                animations=[(len(x.frames), _h(b''.join(_raw(f) for f in x.frames)))
                            for x in (a.block, a.hatena, a.blockL, a.hatenaL, a.tuka, a.belt)])

_wiiu = os.path.join(ROOT, 'miyamotoextras', 'Pa0_jyotyu.szs')
if os.path.isfile(_wiiu):
    _data = open(_wiiu, 'rb').read()
    _data = yaz0.decompressFASTYZ(_data) if _data[:4] == b'Yaz0' else _data
    globals.IsNSMBUDX = False                                   # read it as the Wii U file it is
    real = puzzle.TilesetEditor(win, 'Pa0_jyotyu', _data, 0, False)
    before = _snapshot(real)
    globals.IsNSMBUDX = True                                    # ...and write it as a Deluxe tileset
    dx_archive = real.saving('Pa0_jyotyu')
    again = puzzle.TilesetEditor(win, 'Pa0_jyotyu', dx_archive, 0, False)
    after = _snapshot(again)
    check('real tileset: Deluxe archive is a little-endian SARC', dx_archive[:4] == b'SARC' and dx_archive[6:8] == b'\xff\xfe')
    check('real tileset: 156 objects', before['objects'] == 156)
    for key in before:
        check('real tileset converted to Deluxe keeps its %s' % key, before[key] == after[key])

shutil.rmtree(tmp, ignore_errors=True)
print('\n%d/%d passed' % (sum(ok for _, ok in results), len(results)))
sys.exit(0 if all(ok for _, ok in results) else 1)
