"""
Regression tests for bugs fixed after the v1.0.0 review: lost paths after the Nabbit
path, empty path records, text that could not be saved, silent save failures,
half-written files, level detection, and symlinks in macOS update packages.

Run from anywhere:   python tests/regression_test.py
Needs PyQt5 and the compiled fastyz extension (a stand-in is used if it isn't built,
which only affects the compression test).
"""
import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import io
import os
import stat
import struct
import sys
import tempfile
import types
import zipfile
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

from PyQt5 import QtCore, QtGui, QtWidgets
app = QtWidgets.QApplication([])

from yaz0moto import globals
globals.mainWindow = mock.MagicMock()
globals.NumberFont = QtGui.QFont()

from yaz0moto import area as A, updater, yaz0
from yaz0moto.misc import Metadata, encodeMetadataText, decodeMetadataText
from yaz0moto.verifications import IsNSMBLevel

results = []


def check(label, ok, detail=''):
    results.append((label, bool(ok)))
    print(('PASS ' if ok else 'FAIL ') + label + ((' -- ' + str(detail)) if (detail and not ok) else ''))


tmp = tempfile.mkdtemp()

# ---------------------------------------------------------------- paths

def node(x, y):
    return {'x': x, 'y': y, 'speed': 1.0, 'accel': 0.0, 'delay': 0}


for little in (False, True):
    globals.IsNSMBUDX = little
    order = 'little' if little else 'big'

    src = A.Area_NSMBU()
    src.pathdata = [{'id': 1, 'unk1': 0, 'loops': False, 'nodes': [node(0, 0), node(16, 0)]},
                    {'id': 2, 'unk1': 0, 'loops': False, 'nodes': []},
                    {'id': 95, 'unk1': 0, 'loops': True, 'nodes': [node(32, 32)]},
                    {'id': 120, 'unk1': 0, 'loops': False, 'nodes': [node(48, 48), node(64, 48)]}]
    src.nPathdata = {'nodes': [dict(node(5, 5), action=0, unk1=0, unk2=0, unk3=0, unk4=0)]}
    src.SavePaths()
    check('%s: paths with no nodes leave no empty record' % order, len(src.blocks[13]) == 4 * 12,
          len(src.blocks[13]))

    dst = A.Area_NSMBU()
    dst.blocks = list(src.blocks)
    dst.LoadPaths()
    check('%s: paths after the Nabbit path survive a save and load' % order,
          [p['id'] for p in dst.pathdata] == [1, 95, 120] and len(dst.pathdata[2]['nodes']) == 2
          and dst.pathdata[1]['loops'] and len(dst.nPathdata['nodes']) == 1,
          [(p['id'], len(p['nodes'])) for p in dst.pathdata])

globals.IsNSMBUDX = False

# ---------------------------------------------------------------- text in level metadata

samples = ['My Level', 'Mario’s Level — W1', 'Café', 'マリオ', 'emoji \U0001F344']
m = Metadata()
for i, s in enumerate(samples):
    m.setStrData('Title%d' % i, s)
saved = bytes(bytearray(m.save()))
m2 = Metadata(saved)
check('level information keeps any text through a save',
      [m2.strData('Title%d' % i) for i in range(len(samples))] == samples)

legacy = Metadata()
legacy.setOtherData('Author', 1, [ord(c) for c in 'Jérôme'])   # how older versions stored it
check('level information saved by older versions still reads correctly',
      Metadata(bytes(bytearray(legacy.save()))).strData('Author') == 'Jérôme')

text = 'Pipe → secret — ★'
encoded = encodeMetadataText(text)
comment = list(struct.pack('>III', 32, 48, len(encoded))) + encoded
area = A.Area_NSMBU()
area.areanum = 1
area.Metadata.setBinData('InLevelComments_A1', comment)
area.LoadComments()
check('comments with any text load back', [c.text for c in area.comments] == [text],
      [c.text for c in area.comments])

# ---------------------------------------------------------------- saving files

target = os.path.join(tmp, 'level.sarc')
yaz0.writeFile(target, b'first')
yaz0.writeFile(target, b'second')
check('files are replaced in one step', open(target, 'rb').read() == b'second')

folder_target = os.path.join(tmp, 'a_folder')
os.makedirs(folder_target)
try:
    yaz0.writeFile(folder_target, b'data')
    raised = False
except OSError:
    raised = True
check('a failed write raises and leaves no temporary file',
      raised and not any(n.endswith('.tmp') for n in os.listdir(tmp)), os.listdir(tmp))

with mock.patch.object(yaz0.fastyz, 'compress', side_effect=RuntimeError('boom')):
    ok = yaz0.compressFASTYZ(b'data', target)
check('a failed compression is reported and the old file kept',
      ok is False and open(target, 'rb').read() == b'second')

# ---------------------------------------------------------------- level detection

import SarcLib
arc = SarcLib.SARC_Archive(endianness='<')
folder = SarcLib.Folder('course'); arc.addFolder(folder)
folder.addFile(SarcLib.File('course1.bin', b'\0' * 16))
level = os.path.join(tmp, '1-1.sarc'); open(level, 'wb').write(arc.save()[0])
szs = os.path.join(tmp, '1-1.szs'); open(szs, 'wb').write(b'Yaz0' + bytes(12))
junk = os.path.join(tmp, 'notes.sarc'); open(junk, 'wb').write(b'not a level')
check('level files are recognised and other files are not',
      IsNSMBLevel(level) and IsNSMBLevel(szs) and not IsNSMBLevel(junk) and not IsNSMBLevel(junk + 'x'))

# ---------------------------------------------------------------- update packages with symlinks

def make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data, link in entries:
            info = zipfile.ZipInfo(name)
            info.external_attr = ((stat.S_IFLNK | 0o777) if link else (stat.S_IFREG | 0o644)) << 16
            zf.writestr(info, data)
    path = os.path.join(tmp, 'pkg%d.zip' % len(os.listdir(tmp)))
    open(path, 'wb').write(buf.getvalue())
    return path


def refused(entries):
    try:
        updater._safe_extract(make_zip(entries), tempfile.mkdtemp())
    except updater.UpdateError:
        return True
    return False


fw = 'Yaz0moto.app/Contents/Frameworks/QtCore.framework/'
bundle = [(fw + 'Versions/5/QtCore', b'binary', False),
          (fw + 'Versions/Current', b'5', True),
          (fw + 'QtCore', b'Versions/Current/QtCore', True)]
check('links pointing outside the package are refused',
      refused([('app/evil', b'../../outside', True)]) and refused([('app/evil', b'/etc/passwd', True)]))
check('files written through a link are refused',
      refused([('app/lib', b'.', True), ('app/lib/x', b'data', False)]))
check('climbing out after following another link is refused',
      refused([('a/b/top', b'../..', True), ('a/b/escape', b'top/../..', True)])
      or refused([('a/b/top', b'..', True), ('a/b/escape', b'top/..', True)]))

if os.name == 'nt':
    print('SKIP symlinks in macOS bundles are recreated (needs symlink rights on Windows)')
else:
    out = tempfile.mkdtemp()
    updater._safe_extract(make_zip(bundle), out)
    link = os.path.join(out, fw, 'QtCore')
    check('symlinks in macOS bundles are recreated',
          os.path.islink(link) and os.readlink(link) == 'Versions/Current/QtCore' and open(link, 'rb').read() == b'binary')

# ---------------------------------------------------------------- the Yaz0moto theme

import re
from yaz0moto.misc import JsonSettings, setSetting, setting
from yaz0moto import loading
from yaz0moto.ui import SetAppStyle, GetIcon

globals.app = app
globals.user_data_path = tempfile.mkdtemp()
globals.settings = JsonSettings(os.path.join(globals.user_data_path, 'settings.json'))
loading.LoadTheme()
SetAppStyle('Fusion')
theme = globals.theme
check('the Yaz0moto theme is the default', theme.themeName == 'Yaz0moto')

used = set()
for name in os.listdir(os.path.join(ROOT, 'yaz0moto')):
    if name.endswith('.py'):
        used.update(re.findall(r"GetIcon\(['\"]([a-z0-9_]+)['\"]", open(os.path.join(ROOT, 'yaz0moto', name), encoding='utf-8').read()))
svgs = {f[5:-4] for f in os.listdir(os.path.join(ROOT, 'yaz0data', 'themes', 'Yaz0moto', 'icons'))}
check('every icon the editor uses has a theme icon', used <= svgs, sorted(used - svgs))
icon = GetIcon('realview')
check('theme icons are drawn sharp at several sizes', len(icon.availableSizes()) >= 4 and not icon.pixmap(24, 24).isNull())

images = re.findall(r'url\(([^)]+)\)', theme.styleSheet)
check('the style sheet images exist', images and '{theme}' not in theme.styleSheet and all(os.path.isfile(i) for i in images),
      [i for i in images if not os.path.isfile(i)])
check('selection uses the orange accent', app.palette().color(QtGui.QPalette.Highlight).name().lower() == '#f7941d')

setSetting('Theme', 'NoSuchTheme')
loading.LoadTheme()
check('a missing theme falls back to Classic', globals.theme.themeName == 'Classic')
SetAppStyle('Fusion')
check('switching to a theme without a style sheet clears the old one', app.styleSheet() == '')

# ---------------------------------------------------------------- themes built on the Yaz0moto theme

from yaz0moto import themevars
from yaz0moto.ui import MiyamotoTheme, availableThemes, _LazySvgIcon

dark = themevars.derive({'accent': '#F7941D', 'background': '#1C1C1F', 'text': '#ECECEF'})
light = themevars.derive({'accent': '#3F7BFF', 'background': '#EAF1FF', 'text': '#1E2A44'})
check('dark themes get darker fields, light themes lighter ones',
      themevars.luminance(dark['field']) < themevars.luminance(dark['background'])
      and themevars.luminance(light['field']) > themevars.luminance(light['background']))
check('text on the accent stays readable', dark['on_accent'] == '#1B1B1E' and themevars.derive({'accent': '#2040A0'})['on_accent'] == '#FFFFFF')
check('control corners stop at fully round', themevars.derive({'roundness': '20'})['radius'] == '13')
check('icons are recoloured for a theme', '#3F7BFF' in themevars.recolor_svg('<path fill="#F7941D"/>', light))

bad = []
classic = []
for name in availableThemes():
    t = MiyamotoTheme(name)
    if t.isClassic:
        classic.append(name)
        continue  # checked below
    if name != 'Yaz0moto' and not t.variables:
        bad.append('%s: not built on Yaz0moto' % name)
    if '${' in re.sub(r'/\*.*?\*/', '', t.styleSheet, flags=re.S):
        bad.append('%s: unfilled placeholder' % name)
    if t.variables and t.color('palette_highlight').name().upper() != t.variables['accent']:
        bad.append('%s: highlight is not the accent' % name)
    if not t.iconCacheSm.get('realview'):
        bad.append('%s: no icons' % name)
check('every bundled modern theme is built on the Yaz0moto theme and fills in completely', not bad, bad)

# ---------------------------------------------------------------- classic themes, built on the Legacy theme

pngs = set()
for folder in (os.path.join(ROOT, 'yaz0data', 'ico', 'sm'), os.path.join(ROOT, 'yaz0data', 'themes', 'Legacy', 'icosm')):
    pngs.update(f[5:-4] for f in os.listdir(folder) if f.startswith('icon-') and f.endswith('.png'))
check('every icon the editor uses has an original-style icon for the classic themes', used <= pngs, sorted(used - pngs))


def classicProblems(name):
    t = MiyamotoTheme(name)
    out = []
    if t.styleSheet:
        out.append('%s: has a style sheet' % name)
    if not t.variables:
        out.append('%s: not built on Legacy' % name)
    elif t.color('palette_highlight').name().upper() != t.variables['accent']:
        out.append('%s: highlight is not the accent' % name)
    if t.toolbarIconSize != 16:
        out.append('%s: toolbar icons are not 16 px' % name)
    # Legacy's own PNGs, and no modern (SVG) icons: the rest come from the original set
    if 'parts' not in t.iconCacheSm or any(isinstance(i, _LazySvgIcon) for i in t.iconCacheSm.values()):
        out.append('%s: not the original-style icons' % name)
    if any(c is None for c in (t.color('ui'), t.color('bg'), t.color('zone_lines'))):
        out.append('%s: missing colours' % name)
    return out


bad = [p for name in classic for p in classicProblems(name)]
check('there are bundled classic themes besides Legacy', 'Legacy' in classic and len(classic) >= 5, classic)
check('every classic theme has the original look in its own colours (no style sheet, accent highlight, 16 px icons)',
      not bad, bad)
legacy = MiyamotoTheme('Legacy')
check('the Legacy theme keeps the original Neon level colours',
      legacy.color('bg').name().upper() == '#080808' and legacy.color('ui').name().upper() == '#181818'
      and legacy.color('zone_lines').name().upper() == '#6EC0FF')

folder = os.path.join(globals.user_data_path, 'themes', 'Mine')
themevars.write_theme(folder, 'Mine', {'accent': '#B04CFF', 'background': '#101418', 'text': '#EEEEEE', 'roundness': '6'})
mine = MiyamotoTheme('Mine')
check('a theme made in the theme editor loads back',
      mine.themeName == 'Mine' and mine.variables['accent'] == '#B04CFF' and mine.variables['radius'] == '6'
      and 'Mine' in availableThemes() and not mine.isClassic)

folder = os.path.join(globals.user_data_path, 'themes', 'MineClassic')
themevars.write_theme(folder, 'Mine Classic', {'accent': '#22AA44', 'background': '#D8E0E8', 'text': '#101010',
                                               'level': '#405060', 'roundness': '6'}, base=themevars.CLASSIC_BASE)
mineClassic = MiyamotoTheme('MineClassic')
check('a classic theme made in the theme editor loads back, in its own colours',
      mineClassic.isClassic and not classicProblems('MineClassic') and mineClassic.color('bg').name().upper() == '#405060'
      and mineClassic.color('zone_lines').name().upper() == '#22AA44'
      and 'roundness' not in open(os.path.join(folder, 'main.xml'), encoding='utf-8').read())

# ---------------------------------------------------------------- actor icons

from yaz0moto import spriteicons
globals.Sprites = [None] * 10
globals.NumSprites = 10
from yaz0moto.gamedefs import MiyamotoGameDefinition
patch = os.path.join(globals.user_data_path, 'patches', 'MyPatch')
os.makedirs(os.path.join(patch, 'icons'))
open(os.path.join(patch, 'main.xml'), 'w').write('<game name="My Patch" />')
png = QtGui.QPixmap(20, 20)
png.fill(QtGui.QColor('#FF0000'))
png.save(os.path.join(patch, 'icons', '7.png'))
mod = MiyamotoGameDefinition('MyPatch', source='mod', base_instance=MiyamotoGameDefinition())
check('actor icons are looked for in the icons folder of the active patch',
      [os.path.normpath(f) for f in mod.patchFolders()] == [os.path.normpath(patch)])
mod.getImageClasses = lambda: {}
globals.gamedef = mod
icon7 = spriteicons.spriteIcon(7, 48)
check('patches/<patch>/icons/<id>.png is used when an actor has no sprite image',
      QtGui.QColor(icon7.toImage().pixel(24, 24)).name() == '#ff0000')
icon8 = spriteicons.spriteIcon(8, 48)
check('otherwise the Bowser face is drawn', not icon8.isNull() and QtGui.QColor(icon8.toImage().pixel(24, 20)).alpha() > 0)

data7 = bytes.fromhex('0000 0010 0000 0000 0000 0001')
blue = QtGui.QPixmap(20, 20)
blue.fill(QtGui.QColor('#0000FF'))
blue.save(os.path.join(patch, 'icons', '7-%s.png' % spriteicons.rawDataName(data7)))
green = QtGui.QPixmap(20, 20)
green.fill(QtGui.QColor('#00FF00'))
green.save(os.path.join(patch, 'icons', '9_00000000000000000000ABCD.png'))
spriteicons.clearCache()

def levelColor(type_id, data):
    pix = spriteicons.levelIcon(type_id, 40, data)
    return QtGui.QColor(pix.toImage().pixel(20, 20)).name() if pix is not None else None

check('raw data is written in icon names as Info... shows it',
      spriteicons.rawDataName(data7) == '0000-0010-0000-0000-0000-0001')
check('an icon named <id>-<raw data>.png is used for an actor with that data',
      levelColor(7, data7) == '#0000ff')
check('the <id>.png icon is used for other data', levelColor(7, bytes(12)) == '#ff0000')
check('the raw data can also follow an underscore, without dashes, in any case',
      levelColor(9, bytes.fromhex('00000000000000000000abcd')) == '#00ff00' and levelColor(9, bytes(12)) is None)
check('only an icon for the exact data replaces a sprite image (not <id>.png)',
      spriteicons.levelIcon(7, 40, data7, exactOnly=True) is not None
      and spriteicons.levelIcon(7, 40, bytes(12), exactOnly=True) is None)
check('a square or not-exact-multiple icon covers 1 tile',
      spriteicons.tileSpan(20, 20) == (1, 1) and spriteicons.tileSpan(301, 100) == (1, 1)
      and spriteicons.tileSpan(150, 100) == (1, 1))
check('an icon N times wider or taller covers N tiles across or down',
      spriteicons.tileSpan(300, 100) == (3, 1) and spriteicons.tileSpan(16, 64) == (1, 4))
wide = QtGui.QPixmap(60, 20)
wide.fill(QtGui.QColor('#FFFF00'))
wide.save(os.path.join(patch, 'icons', '6.png'))
spriteicons.clearCache()
check('a 3:1 level icon spans 3 tiles and is loaded at that size',
      spriteicons.levelIconSpan(6) == (3, 1)
      and spriteicons.levelIcon(6, 40, tiled=True).size() == QtCore.QSize(120, 40))
from yaz0moto.items import SpriteItem
tw = globals.TileWidth
box = types.SimpleNamespace(BoundingRect=QtCore.QRectF(0, 0, tw, tw))
def placed(span, replaces=False, offset=(0, 0), anchor=None):
    fake = types.SimpleNamespace(iconSpan=span, iconReplacesImage=replaces, iconAnchor=anchor,
                                 ImageObj=types.SimpleNamespace(spritebox=box, xOffset=offset[0], yOffset=offset[1]))
    return SpriteItem.iconRect(fake)
check('an icon over 900px on a side covers twice the tiles each way',
      spriteicons.tileSpan(1000, 1000) == (2, 2) and spriteicons.tileSpan(320, 960) == (2, 6)
      and spriteicons.tileSpan(901, 300) == (2, 2) and spriteicons.tileSpan(900, 300) == (3, 1))
check('a big icon grows to each side and up from the actor\'s tile',
      placed((2, 2)) == QtCore.QRectF(-tw / 2, -tw, 2 * tw, 2 * tw))
check('a 1 tile icon covers just the actor\'s tile', placed((1, 1)) == QtCore.QRectF(0, 0, tw, tw))
check('a wide icon is centred on the actor\'s tile', placed((3, 1)) == QtCore.QRectF(-tw, 0, 3 * tw, tw))
check('a tall icon goes up from the actor\'s tile', placed((1, 4)) == QtCore.QRectF(0, -3 * tw, tw, 4 * tw))
check('an icon replacing a sprite image sits on the actor\'s tile, not the image\'s corner',
      placed((1, 2), True, (-8, -16)) == QtCore.QRectF(tw / 2, 0, tw, 2 * tw))

# Y0MI_<WWWWHHHH ABCDEEEE EEEEEEEE>[_<raw data>].png
check('a Y0MI_ name holds the size in tiles, the placement and the actor ID',
      spriteicons._y0miLayout('12905B') == (0x5B, (2, 3, (True, False, False, True)))
      and spriteicons._y0miLayout('F0000A') == (10, (16, 1, (False, False, False, False))))
check('a Y0MI_ icon goes up or down, right or left of the actor\'s tile',
      placed((2, 3), anchor=(True, True, False, False)) == QtCore.QRectF(0, -2 * tw, 2 * tw, 3 * tw)
      and placed((2, 3), anchor=(False, False, False, False)) == QtCore.QRectF(-tw, 0, 2 * tw, 3 * tw))
check('a centred Y0MI_ icon is centred on the actor\'s tile, by half tiles if need be',
      placed((2, 3), anchor=(True, True, True, True)) == QtCore.QRectF(-tw / 2, -tw, 2 * tw, 3 * tw))
square = QtGui.QPixmap(20, 20)
square.fill(QtGui.QColor('#FF00FF'))
square.save(os.path.join(patch, 'icons', 'Y0MI_216006.png'))  # 3 x 2 tiles, to the right, centred vertically, actor 6
cyan = QtGui.QPixmap(20, 20)
cyan.fill(QtGui.QColor('#00FFFF'))
cyan.save(os.path.join(patch, 'icons', 'yomi_000006_%s.png' % spriteicons.rawDataName(data7)))
spriteicons.clearCache()
check('a Y0MI_ icon comes before the old name for the same actor, and is stretched to its tiles',
      spriteicons.levelIconLayout(6) == (3, 2, (False, True, True, False))
      and spriteicons.levelIcon(6, 40, tiled=True).size() == QtCore.QSize(120, 80) and levelColor(6, None) == '#ff00ff')
check('a Y0MI_ icon with raw data is used for that data first (YOMI_ works too)',
      levelColor(6, data7) == '#00ffff' and spriteicons.levelIconLayout(6, data7)[:2] == (1, 1))
check('the palette keeps the <id>.png icon',QtGui.QColor(spriteicons.spriteIcon(7, 48).toImage().pixel(24, 24)).name() == '#ff0000')

# ---------------------------------------------------------------- parts bar

from yaz0moto import partsbar
check('parts round-trip through their text form',
      all(partsbar.decode(partsbar.encode(k)) == k for k in (('obj', 2, 17), ('spr', 45), ('spr', 'MyActor'))))
globals.mainWindow = mock.MagicMock()
globals.mainWindow.objPicker.m0 = types.SimpleNamespace(ritems=[QtGui.QPixmap(24, 24)] * 4)
bar = partsbar.PartsBar()
bar.keys = []
for n in range(partsbar.MAX_PARTS + 3):
    bar.addRecent(('spr', n % 9))
bar.addRecent(('obj', 0, 2))
check('the parts bar keeps the latest parts first, without repeats, up to its size',
      bar.keys[0] == ('obj', 0, 2) and len(bar.keys) == len(set(bar.keys)) <= partsbar.MAX_PARTS)
check('the parts bar is remembered', [partsbar.decode(k) for k in setting('PartsBar')] == bar.keys)
check('parts of tilesets that are not loaded are left off the bar',
      partsbar.partIcon(('obj', 3, 0), 40) is None and partsbar.partIcon(('obj', 0, 1), 40) is not None)

order = list(bar.keys)
bar.showSelected(('spr', 3))
check('a part selected in the level that is on the bar is marked, without moving it',
      bar.keys == order and bar.current == ('spr', 3) and [b.key for b in bar.buttons if b.isChecked()] == [('spr', 3)])
bar.showSelected(('obj', 0, 3))
check('a part selected in the level that is not on the bar is added to it, marked',
      bar.keys[0] == ('obj', 0, 3) and bar.current == ('obj', 0, 3))
bar.showSelected(None)
check('deselecting unmarks the bar', bar.current is None and not any(b.isChecked() for b in bar.buttons))

# ---------------------------------------------------------------- welcome star

from yaz0moto.welcomestar import splitStar
image = QtGui.QImage(os.path.join(ROOT, 'yaz0data', 'app_icons', 'yaz0moto1024.png')).scaled(216, 216)
split = splitStar(image)
check('the star is found in the app icon', split is not None and 90 < split[2].x() < 126)

failed = [label for label, ok in results if not ok]
print('\n%d/%d passed' % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
