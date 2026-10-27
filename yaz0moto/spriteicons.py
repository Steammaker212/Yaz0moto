#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Yaz0moto Level Editor
# This file is part of Yaz0moto, a fork of Pyamoto.

# See LICENSE.txt for more information.

"""
Icons for actors (sprites), for the Add Actors palette and the parts bar. For each actor:
  1. its own image from the sprite images (the one drawn in the level), if it has one;
  2. otherwise a PNG named after the actor's ID in an "icons" folder of the active patch:
     patches/<patch name>/icons/<actor id>.png (e.g. icons/45.png);
  3. otherwise yaz0data/sprites/no-image-sprite.png (Bowser) with the actor's name under it.

In the level, an actor can also have an icon for one setting of it: <actor id>-<raw
data>.png (or <actor id>_<raw data>.png), the raw data as Info... shows it, e.g.
icons/59_0000-0000-0000-1000-0005-0000.png. When both the ID and the raw data match, it's
drawn instead of the actor's sprite image (or instead of <actor id>.png, for an actor with
no sprite image). <actor id>.png alone only replaces the ID box of actors with no image.

Rendering loads images, so call these outside paint events (the grids queue them).
"""

import os
import re

from PyQt5 import QtCore, QtGui
Qt = QtCore.Qt

from . import globals

_cache = {}  # (type, size) -> QPixmap

# The picture for actors with no icon (shown with the actor's name under it)
NO_IMAGE = ('yaz0data', 'sprites', 'no-image-sprite.png')
_noImage = None


def spriteName(type_id):
    if isinstance(type_id, str):
        sdef = globals.CustomSpriteDefinitions.get(type_id)
        return sdef.name if sdef is not None else type_id
    sprites = getattr(globals, 'Sprites', None)
    if sprites is not None and 0 <= type_id < len(sprites) and sprites[type_id] is not None:
        return sprites[type_id].name
    return 'Actor %s' % type_id


def iconFolders():
    """Where to look for "<id>.png" icons: patches/<patch>/icons, most specific patch first."""
    gamedef = getattr(globals, 'gamedef', None)
    patches = gamedef.patchFolders() if hasattr(gamedef, 'patchFolders') else []
    return [os.path.join(folder, 'icons') for folder in patches]


def _spriteImage(type_id, size):
    """The actor's own sprite image, fitted into size x size, or None if it only has a box."""
    from .widgets import _SpriteTypeProxy

    try:
        img_class = globals.gamedef.getImageClasses().get(type_id)
    except Exception:
        return None
    if img_class is None:
        return None

    proxy = _SpriteTypeProxy(type_id)
    try:
        img_class.loadImages()
        image_obj = img_class(proxy)
        image_obj.dataChanged()
        if image_obj.spritebox.shown:
            return None

        # Images paint from (0, 0) of the sprite item (its offset is part of the item's position)
        scale = globals.TileWidth / 16
        rect = QtCore.QRectF(0, 0, image_obj.width * scale, image_obj.height * scale)
        if rect.width() <= 0 or rect.height() <= 0:
            return None

        # Paint at full size, then scale down smoothly
        full = max(rect.width(), rect.height())
        canvas = QtGui.QImage(int(full) + 2, int(full) + 2, QtGui.QImage.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.transparent)
        painter = QtGui.QPainter(canvas)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.translate((full - rect.width()) / 2 - rect.x() + 1, (full - rect.height()) / 2 - rect.y() + 1)
        image_obj.paint(painter)
        painter.end()

        if _isBlank(canvas):
            return None
        return QtGui.QPixmap.fromImage(canvas.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    except Exception:
        return None
    finally:
        for aux in proxy.aux[:]:
            try:
                aux.setParentItem(None)
            except Exception:
                pass
        proxy.aux.clear()


def _isBlank(image):
    """True if nothing visible was painted (a few sample points are checked)."""
    w, h = image.width(), image.height()
    for i in range(1, 16):
        for j in range(1, 16):
            if QtGui.qAlpha(image.pixel(w * i // 16, h * j // 16)) > 16:
                return False
    return True


# "<id>-<raw data>": the raw data as groups of 4 hex digits, joined by - or _ (or not at all)
_RAW_NAME = re.compile(r'(?P<id>.+?)[-_](?P<raw>[0-9A-Fa-f]{4}(?:[-_]?[0-9A-Fa-f]{4})+)')
_index = None  # (folders, [(folder's {id: path}, folder's {(id, raw data): path})]), most specific patch first


def rawDataName(data):
    """Sprite data as it's written in an icon's file name: 0000-0000-0000-0000-0000-0000."""
    data = bytes(data)
    return '-'.join(data[i:i + 2].hex().upper() for i in range(0, len(data), 2))


def _iconIndex():
    """The PNGs in the icon folders (read again when the active patch changes)."""
    global _index
    folders = iconFolders()
    if _index is None or _index[0] != folders:
        _index = (folders, [])
        for folder in folders:
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            plain, exact = {}, {}
            for name in names:
                stem, ext = os.path.splitext(name)
                if ext.lower() != '.png':
                    continue
                path = os.path.join(folder, name)
                plain[stem] = path
                match = _RAW_NAME.fullmatch(stem)
                if match:
                    raw = re.sub(r'[-_]', '', match.group('raw'))
                    exact[(match.group('id'), bytes.fromhex(raw))] = path
            _index[1].append((plain, exact))
    return _index[1]


def iconPath(type_id, data=None, exactOnly=False):
    """
    The patch icon file for an actor: one named after its ID and this raw data if there's
    one (in any patch), otherwise (unless exactOnly) the one named after its ID; None if
    there isn't one.
    """
    index = _iconIndex()
    if data is not None:
        key = (str(type_id), bytes(data))
        for plain, exact in index:
            if key in exact:
                return exact[key]
    if exactOnly:
        return None
    for plain, exact in index:
        if str(type_id) in plain:
            return plain[str(type_id)]
    return None


def _pngIcon(type_id, size, data=None):
    path = iconPath(type_id, data)
    if path is not None:
        pix = QtGui.QPixmap(path)
        if not pix.isNull():
            return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return None


def noImagePicture():
    """yaz0data/sprites/no-image-sprite.png, loaded once (None if it's missing)."""
    global _noImage
    if _noImage is None:
        image = QtGui.QImage(os.path.join(globals.miyamoto_path, *NO_IMAGE))
        _noImage = image if not image.isNull() else False
    return _noImage or None


def bowserIcon(size, name=None):
    """The no-image picture (Bowser), with a name under it if one is given."""
    canvas = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.transparent)
    painter = QtGui.QPainter(canvas)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    painter.setRenderHint(QtGui.QPainter.TextAntialiasing)

    face = size * (0.66 if name else 0.94)
    target = QtCore.QRectF((size - face) / 2, size * 0.02, face, face)
    picture = noImagePicture()
    if picture is not None:
        scaled = picture.scaled(int(face), int(face), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawImage(QtCore.QPointF(target.x() + (face - scaled.width()) / 2,
                                         target.y() + (face - scaled.height()) / 2), scaled)
    else:
        painter.setBrush(QtGui.QColor('#8E8E96'))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(target)

    if name:
        font = QtGui.QFont()
        font.setPixelSize(max(8, int(size * 0.15)))
        painter.setFont(font)
        painter.setPen(QtGui.QGuiApplication.palette().color(QtGui.QPalette.Text))
        text_rect = QtCore.QRectF(1, target.bottom() + 1, size - 2, size - target.bottom() - 1)
        elided = QtGui.QFontMetrics(font).elidedText(name, Qt.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignTop, elided)

    painter.end()
    return QtGui.QPixmap.fromImage(canvas)


def spriteIcon(type_id, size=48):
    """The icon for an actor (see the module notes for where it comes from)."""
    key = (type_id, size)
    if key not in _cache:
        pix = None
        if isinstance(type_id, int):
            pix = _spriteImage(type_id, size)
        pix = pix or _pngIcon(type_id, size)
        _cache[key] = pix or bowserIcon(size, spriteName(type_id))
    return _cache[key]


_levelCache = {}  # (icon path, size, tiled) -> QPixmap or None
_spanCache = {}  # icon path -> (columns, rows)
BIG_ICON = 900  # level icons with a side over this many pixels cover twice the tiles each way


def tileSpan(width, height):
    """
    How many tiles an icon width x height pixels covers: N x 1 (or 1 x N) when one side is
    exactly N times the other, otherwise (a square, or not an exact multiple) 1 x 1. A big
    image (either side over BIG_ICON pixels) covers twice that each way: 2 x 2, 2N x 2, ...
    """
    if width <= 0 or height <= 0:
        return (1, 1)
    if width > height and width % height == 0:
        span = (width // height, 1)
    elif height > width and height % width == 0:
        span = (1, height // width)
    else:
        span = (1, 1)
    if max(width, height) > BIG_ICON:
        span = (span[0] * 2, span[1] * 2)
    return span


def levelIconSpan(type_id, data=None, exactOnly=False):
    """The tiles (columns, rows) the level icon covers, from the PNG's own size (see tileSpan)."""
    path = iconPath(type_id, data, exactOnly)
    if path is None:
        return (1, 1)
    if path not in _spanCache:
        size = QtGui.QImageReader(path).size()
        _spanCache[path] = tileSpan(size.width(), size.height())
    return _spanCache[path]


def levelIcon(type_id, size, data=None, exactOnly=False, tiled=False):
    """
    The patch's icon for an actor drawn in the level ("<id>-<raw data>.png" for this data,
    or, unless exactOnly, "<id>.png"), or None if there isn't one (the box or sprite image
    stays then, rather than the Bowser picture). size is per tile when tiled (the icon then
    fits the tiles levelIconSpan gives), otherwise the whole icon fits size x size.
    """
    path = iconPath(type_id, data, exactOnly)
    if path is None:
        return None
    key = (path, size, tiled)
    if key not in _levelCache:
        pix = QtGui.QPixmap(path)
        if pix.isNull():
            _levelCache[key] = None
        else:
            cols, rows = levelIconSpan(type_id, data, exactOnly) if tiled else (1, 1)
            _levelCache[key] = pix.scaled(size * cols, size * rows, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return _levelCache[key]


def isCached(type_id, size=48):
    return (type_id, size) in _cache


def clearCache():
    global _index
    _cache.clear()
    _levelCache.clear()
    _spanCache.clear()
    _index = None
