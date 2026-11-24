"""
Tests for zone backgrounds (distant views): where the game's camera puts them
(yaz0moto/dvrender.py), the OpenGL frustum matching the CPU projection (yaz0moto/dvgl.py),
finding the models for Wii U, NSLU and Deluxe (yaz0moto/gamedefs.py), and reading the Wii U
formats. The camera is checked against the formulas of the game's DistantViewMgr::calcView_
(sub_60232B58), BgCam (sub_607FBEB4) and the background position (sub_607FC9FC) as decompiled
from Deluxe v1.0.0, which match Miyamoto-Next's Wii U reimplementation.

If the game dumps named below exist, real Wii U and Deluxe models are loaded too.

Run from anywhere:   python tests/bgposition_test.py
"""
import faulthandler; faulthandler.dump_traceback_later(240, exit=True)
import math
import os
import random
import struct
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

from PyQt5 import QtGui, QtWidgets  # noqa: E402
app = QtWidgets.QApplication([])

from yaz0moto import globals  # noqa: E402
from yaz0moto.misc import JsonSettings  # noqa: E402
globals.settings = JsonSettings(os.path.join(tempfile.mkdtemp(), 'settings.json'))
from yaz0moto import dvrender  # noqa: E402
from yaz0moto import gamedefs  # noqa: E402

results = []


def check(label, ok):
    results.append((label, bool(ok)))
    print(('PASS ' if ok else 'FAIL ') + label)


def near(a, b, eps=1e-3):
    return abs(a - b) <= eps * max(1.0, abs(a), abs(b))


# ---------- the game's own formulas (decompiled), for reference

def gameCalcView(camParams, screenCenterX, screenCenterY, screenBottom, areaBottom, zoom):
    """DistantViewMgr::calcView_: camera position and projection offset"""
    tanHalf = math.tan(math.radians(20 * 0.5))
    baseZ = (112.0 / tanHalf) * zoom
    visH = baseZ * tanHalf * 2
    po = camParams.get('mProjOffset', (0.0, 0.0))
    diff = screenBottom - areaBottom
    camX = screenCenterX - visH * po[0]
    camY = screenCenterY - visH * po[1]
    if camParams.get('mTypeDirY', 0) == 1:
        camY += camParams.get('mMagnifCameraPosY', 0.0) * diff
    offY = po[1]
    if camParams.get('mTypeDirY', 0) == 0:
        offY += camParams.get('mMagnifProjOffsetY', 0.3) * diff * 0.0013889
    return camX, camY, baseZ, po[0], offY


def gameScreen(centerX, centerY, zoneX, zoneTop, zoneW, zoneH, zoom):
    """BgCam: the level camera's screen, kept inside the zone"""
    halfW, halfH = 398.22 * zoom / 2, 224.0 * zoom / 2
    x = min(max(centerX, zoneX + halfW), zoneX + zoneW - halfW)
    y = min(max(centerY, zoneTop - zoneH + halfH), zoneTop - halfH)
    return x, y, y - halfH


# ---------- camera placement

random.seed(5)
camPresets = [
    {},
    {'mProjOffset': (0.0, 0.0), 'mTypeDirY': 0, 'mMagnifProjOffsetY': 0.0},
    {'mProjOffset': (0.05, -0.12), 'mTypeDirY': 0, 'mMagnifProjOffsetY': 0.35, 'mModelOffsetY': 40.0},
    {'mProjOffset': (0.0, 0.2), 'mTypeDirY': 1, 'mMagnifCameraPosY': 0.6, 'mModelOffsetX': -100.0},
]

ok_cam = ok_model = ok_clamp = True
for i in range(200):
    params = random.choice(camPresets)
    zoneW, zoneH = random.choice([(1600, 448), (4096, 640), (512, 224), (800, 1600), (2000, 240)])
    camMode, camZoom = random.choice([(0, 0), (0, 3), (3, 2), (2, 4), (5, 1)])
    cam = dvrender._ZoneCamera(params, zoneW, zoneH, camMode, camZoom)
    zoom = cam.zoom
    vx, vy = random.uniform(-300, zoneW + 300), random.uniform(-zoneH - 300, 300)

    frame = cam.frameFor(vx, vy, 224.0, dvrender.ViewOptions())
    sx, sy, sb = gameScreen(vx, vy, 0.0, 0.0, zoneW, zoneH, zoom)
    gx, gy, gz, gox, goy = gameCalcView(params, sx, sy, sb, -zoneH, zoom)
    ok_cam &= near(frame.camX, gx) and near(frame.camY, gy) and near(cam.cameraZ, gz) \
        and near(frame.offsetX, gox) and near(frame.offsetY, goy, 1e-4)
    ok_clamp &= near(frame.anchorX, sx, 1e-2) and near(frame.anchorY, sy, 1e-2) and frame.scale == 1.0

    # Background position: area bottom + 0.5 * zoom * 224, area middle, plus the model offsets
    ok_model &= near(cam.modelY, -zoneH + 112 * zoom + params.get('mModelOffsetY', 0.0)) \
        and near(cam.modelX, zoneW / 2 + params.get('mModelOffsetX', 0.0))

check('camera and projection offset match calcView_ with the game screen', ok_cam)
check('the screen is kept inside the zone like BgCam (never below its bottom)', ok_clamp)
check('model placed at the area bottom + half a background screen', ok_model)

cam = dvrender._ZoneCamera({}, 1600, 640, 0, 0)
low = cam.frameFor(300, -640 + 20, 224.0, dvrender.ViewOptions())
check('view at the zone bottom: screen centre half a screen above the bottom', near(low.anchorY, -640 + 112))
free = cam.frameFor(300, -640 + 20, 224.0, dvrender.ViewOptions(gameCamera=False))
check('free camera follows the view inside the zone', near(free.anchorY, -620) and near(free.camY, -620))
check('free camera sits lower than the game\'s at the bottom (background drawn higher)', free.camY < low.camY)
outside = cam.frameFor(-500, 900, 224.0, dvrender.ViewOptions(gameCamera=False))
check('free camera still kept inside the zone', near(outside.anchorX, 0) and near(outside.anchorY, 0))
check('_clampCenter centres a span that does not fit', dvrender._clampCenter(5, 100, 0, 150) == 75)

# ---------- projection: the zone's plane lines up 1:1 with the level, far layers scroll less

mesh = dvrender.DistantViewMesh('m', [(0.0, 0.0, 0.0), (37.0, -12.0, 0.0), (37.0, -12.0, -5000.0)], None, [], None)
for params in camPresets:
    cam = dvrender._ZoneCamera(params, 2400, 640, 0, 0)
    base = []
    for viewX in (250.0, 900.0, 1700.0):
        frame = cam.frameFor(viewX, -400.0, 224.0, dvrender.ViewOptions(gameCamera=False))
        pts = cam.project([mesh], frame, (0.0, 0.0, 1.0, -1.0))[0][0]  # mapping to zone coordinates
        base.append(pts)
    shiftNear = base[1][1][0] - base[0][1][0]
    shiftFar = base[1][2][0] - base[0][2][0]
    if tuple(params.get('mProjOffset', (0.0, 0.0))) == (0.0, 0.0) and params.get('mMagnifProjOffsetY', 0.3) == 0:
        check('zone-plane point stays put as the camera moves (%s)' % sorted(params),
              near(base[0][1][0], cam.modelX + 37.0, 1e-6) and near(shiftNear, 0.0, 1e-6))
    check('far scenery scrolls with the camera (parallax) (%s)' % sorted(params), shiftFar > 1.0)

cam = dvrender._ZoneCamera({}, 2400, 640, 0, 0)
frame = cam.frameFor(1000.0, -300.0, 448.0, dvrender.ViewOptions(fillView=True))
check('fill mode: one game screen fills the view height', near(frame.scale, 2.0) and near(frame.anchorY, -300.0))
opt = dvrender.ViewOptions(offsetX=24.0, offsetY=16.0)
f0, f1 = cam.frameFor(1000.0, -300.0, 224.0), cam.frameFor(1000.0, -300.0, 224.0, opt)
check('extra offsets move the picture right and down', near(f1.anchorX - f0.anchorX, 24.0) and near(f1.anchorY - f0.anchorY, -16.0))

# The OpenGL frustum shows each point where the CPU projection puts it
ok = True
for params in camPresets:
    for fill in (False, True):
        cam = dvrender._ZoneCamera(params, 1800, 900, 0, 3)
        options = dvrender.ViewOptions(fillView=fill, offsetY=8.0)
        frame = cam.frameFor(700.0, -500.0, 300.0, options)
        left, right, bottom, top = 100.0, 900.0, -800.0, -300.0
        l, r, b, t = cam.frustum(frame, left, right, bottom, top, dvrender._NEAR)
        for p in [(10.0, 20.0, 0.0), (-300.0, 150.0, -2000.0), (500.0, -80.0, 300.0)]:
            m = dvrender.DistantViewMesh('p', [p], None, [], None)
            ex, ey = cam.project([m], frame, (0.0, 0.0, 1.0, -1.0))[0][0][0]
            depth = cam.cameraZ - (p[2] + cam.modelZ)
            nx = (p[0] + cam.modelX - frame.camX) * dvrender._NEAR / depth
            ny = (p[1] + cam.modelY - frame.camY) * dvrender._NEAR / depth
            gx = left + (nx - l) / (r - l) * (right - left)
            gy = bottom + (ny - b) / (t - b) * (top - bottom)
            ok &= near(gx, ex, 1e-6) and near(gy, ey, 1e-6)
check('GL frustum agrees with the CPU projection (both framings)', ok)

# ---------- settings

store = {'BgPreviewGameCamera': 'false', 'BgPreviewFillView': True, 'BgPreviewOffsetX': '12', 'BgPreviewOffsetY': None}
o = dvrender.viewOptionsFromSettings(lambda name, default=None: store.get(name, default))
check('view options read from settings', o.key() == (False, True, 12.0, 0.0))
o = dvrender.viewOptionsFromSettings(lambda name, default=None: default)
check('view option defaults are the game camera at level scale', o.key() == (True, False, 0.0, 0.0))

# ---------- finding the models (Wii U, NSLU, Deluxe, mods)

tmp = tempfile.mkdtemp()


def touch(*parts):
    path = os.path.join(tmp, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').close()
    return path


def gamedef(isDX, paths):
    g = gamedefs.MiyamotoGameDefinition()
    g.isDX = isDX
    g.GetGamePaths = lambda: list(paths)
    return g


wiiDV = touch('wiiu', 'content', 'Common', 'distant_view', 'dv_Kougen.szs')
os.makedirs(os.path.join(tmp, 'wiiu', 'content', 'Common', 'course_res_pack'))
os.makedirs(os.path.join(tmp, 'wiiu', 'content', '0010', 'course_res_pack'))
dxDV = touch('dx', 'romfs', 'Model', 'dv_Kougen.Nin_NX_NVN.szs')
os.makedirs(os.path.join(tmp, 'dx', 'romfs', 'Course'))
modDV = touch('mod', 'romfs', 'Model', 'dv_Kougen.Nin_NX_NVN.szs')
os.makedirs(os.path.join(tmp, 'mod', 'romfs', 'Course'))

nsmbu = gamedef(False, [os.path.join(tmp, 'wiiu', 'content', 'Common', 'course_res_pack')])
nslu = gamedef(False, [os.path.join(tmp, 'wiiu', 'content', 'Common', 'course_res_pack'),
                       os.path.join(tmp, 'wiiu', 'content', '0010', 'course_res_pack')])
nsluAlone = gamedef(False, [os.path.join(tmp, 'wiiu', 'content', '0010', 'course_res_pack') + os.sep])
dx = gamedef(True, [os.path.join(tmp, 'dx', 'romfs', 'Course')])
dxMod = gamedef(True, [os.path.join(tmp, 'dx', 'romfs', 'Course'), os.path.join(tmp, 'mod', 'romfs', 'Course')])

check('Wii U model found next to course_res_pack', nsmbu.FindDistantViewFile('Kougen') == wiiDV)
check('NSLU uses content/Common/distant_view', nslu.FindDistantViewFile('Kougen') == wiiDV
      and nsluAlone.FindDistantViewFile('Kougen') == wiiDV)
check('Deluxe model found in romfs/Model', dx.FindDistantViewFile('Kougen') == dxDV)
check('a mod\'s model wins over the game\'s', dxMod.FindDistantViewFile('Kougen') == modDV)
check('no cross-platform matches', gamedef(True, nsmbu.GetGamePaths()).FindDistantViewFile('Kougen') is None
      and gamedef(False, dx.GetGamePaths()).FindDistantViewFile('Kougen') is None)
check('missing names give None', nsmbu.FindDistantViewFile('Nope') is None and dx.FindDistantViewFile('') is None)

# A mod only ships the backgrounds it changed: the rest come from the base game folder set in
# Preferences (any folder around the models is accepted)
from yaz0moto.misc import setSetting  # noqa: E402
baseWiiU = touch('base', 'content', 'Common', 'distant_view', 'dv_Isiyama_3.szs')
touch('base', 'content', 'Common', 'distant_view', 'dv_Kougen.szs')
baseDX = touch('basedx', 'romfs', 'Model', 'dv_Isiyama_3.Nin_NX_NVN.szs')
resolve = gamedefs.ResolveDistantViewFolder
wiiFolder, dxFolder = os.path.dirname(baseWiiU), os.path.dirname(baseDX)
check('base Wii U folder found from content, Common, distant_view or a course folder',
      all(resolve(os.path.join(tmp, 'base', *parts), False) == wiiFolder for parts in
          [('content',), ('content', 'Common'), ('content', 'Common', 'distant_view'), ()]))
check('base Deluxe folder found from romfs, romfs/Model or romfs/Course',
      all(resolve(os.path.join(tmp, 'basedx', *parts), True) == dxFolder for parts in
          [('romfs',), ('romfs', 'Model'), ('romfs', 'Course'), ()]))
check('a folder of the other platform is not taken', resolve(os.path.join(tmp, 'basedx', 'romfs'), False) is None
      and resolve(os.path.join(tmp, 'base', 'content'), True) is None)
mod = gamedef(False, [os.path.join(tmp, 'wiiu', 'content', 'Common', 'course_res_pack')])
check('without the base folder, backgrounds the mod lacks are missing', mod.FindDistantViewFile('Isiyama_3') is None)
setSetting('BgFallbackFolder_NSMBU', os.path.join(tmp, 'base', 'content'))
setSetting('BgFallbackFolder_NSMBUDX', os.path.join(tmp, 'basedx', 'romfs'))
check('with it, they come from the base game', mod.FindDistantViewFile('Isiyama_3') == baseWiiU)
check("the mod's own backgrounds still win", mod.FindDistantViewFile('Kougen') == wiiDV)
check('Deluxe uses its own base folder', dx.FindDistantViewFile('Isiyama_3') == baseDX
      and dx.FindDistantViewFile('Kougen') == dxDV)
setSetting('BgFallbackFolder_NSMBU', '')
setSetting('BgFallbackFolder_NSMBUDX', '')

# ---------- Wii U formats

check('Wii U / Switch BFRES told apart', dvrender.isWiiUBFRES(b'FRES\x03\x00\x00\x01\xfe\xff\x00\x10')
      and not dvrender.isWiiUBFRES(b'FRES    \x08\x00\x05\x00\xff\xfe'))


def aampV1(root):
    """A Wii U AAMP v1 file from (crc, lists, objs) where objs = [(crc, [(crc, type, payload)])]"""
    def param(crc, kind, payload):
        return struct.pack('<III', 12 + len(payload), kind, crc) + payload

    def obj(crc, params):
        body = b''.join(param(*p) for p in params)
        return struct.pack('<IIII', 16 + len(body), len(params), crc, 0x16D4A9BF) + body

    def plist(crc, lists, objs):
        body = b''.join(plist(*l) for l in lists) + b''.join(obj(*o) for o in objs)
        return struct.pack('<IIII', 16 + len(body), crc, len(lists), len(objs)) + body

    kind = b'aglenv\0'
    data = plist(*root)
    return b'AAMP' + struct.pack('<IIIII', 1, 1, 0x18 + len(kind) + len(data), 0, len(kind)) + kind + data


crc = dvrender._crc
light = [(crc('enable'), 0, b'\x01'), (crc('name'), 7, b'Main'.ljust(32, b'\0')),
         (crc('Intensity'), 1, struct.pack('<f', 0.5)), (crc('Direction'), 4, struct.pack('<3f', 0, -1, 0)),
         (crc('DiffuseColor'), 6, struct.pack('<4f', 1, 0.5, 0.25, 1))]
data = aampV1((crc('param_root'), [(crc('DirectionalLight'), [], [(crc('Light0'), light)])], []))
parsed = dvrender._parseAAMP(data)
objs = parsed['lists'][crc('DirectionalLight')]['objs']
values = objs.get(crc('Light0'), {})
check('AAMP v1 parsed', values.get(crc('name')) == 'Main' and values.get(crc('enable')) is True
      and near(values.get(crc('Intensity'), 0), 0.5) and values.get(crc('Direction')) == (0.0, -1.0, 0.0))

# ---------- real models, when the dumps are around (not in CI)

WIIU = os.environ.get('NSMBU_CONTENT', r'C:\Users\Saif Khan\Downloads\NSMB-U-USA-LOADIINE-ZIPERTO'
                      r'\New SUPER MARIO BROS. U [ARPE01]\content')
DELUXE = os.environ.get('NSMBUDX_ROMFS', r'C:\Users\Saif Khan\Documents\Switch Modding Project'
                        r'\New Super Mario Bros U Deluxe (NSP)(Base Game)\Base\romfs')
wiiuModel = os.path.join(WIIU, 'Common', 'distant_view', 'dv_Mori.szs')
dxModel = os.path.join(DELUXE, 'Model', 'dv_Mori.Nin_NX_NVN.szs')
if os.path.isfile(wiiuModel) and os.path.isfile(dxModel):
    wMeshes, wTex, wCam = dvrender.loadDistantView(wiiuModel)
    dMeshes, dTex, dCam = dvrender.loadDistantView(dxModel)
    check('Wii U model: same meshes as Deluxe', sorted(m.name for m in wMeshes) == sorted(m.name for m in dMeshes))
    check('Wii U model: every colour texture decoded', all(m.texture in wTex for m in wMeshes if m.texture))
    check('Wii U model: same camera parameters as Deluxe', wCam == dCam)
    wv = {m.name: len(m.positions) for m in wMeshes}
    check('Wii U model: same vertex counts', wv == {m.name: len(m.positions) for m in dMeshes})
    wBox = [min(p[1] for m in wMeshes for p in m.positions), max(p[1] for m in wMeshes for p in m.positions)]
    dBox = [min(p[1] for m in dMeshes for p in m.positions), max(p[1] for m in dMeshes for p in m.positions)]
    check('Wii U model: same extent', near(wBox[0], dBox[0], 1e-3) and near(wBox[1], dBox[1], 1e-3))
    check('Wii U model: skeletal animation read', wMeshes[0].skeleton.anim is not None)
    check('Wii U model: material animation read', any(m.material and m.material.anim for m in wMeshes))
    tex = wTex.get('DV_mori_tree')
    check('Wii U texture looks like the Deluxe one', tex is not None and tex.size() == dTex['DV_mori_tree'].size())
    image = dvrender.renderZoneBackground(wMeshes, wTex, 800, 448, wCam)
    opaque = sum(1 for y in range(0, image.height(), 16) for x in range(0, image.width(), 16)
                 if QtGui.qAlpha(image.pixel(x, y)) > 0)
    check('Wii U zone render covers the zone', opaque > 0.9 * (image.width() // 16) * (image.height() // 16))
else:
    print('SKIP real models (dumps not found)')

failed = [label for label, ok in results if not ok]
print('\n%d/%d passed' % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
