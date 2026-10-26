#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Yaz0moto Level Editor
# This file is part of Yaz0moto, a fork of Pyamoto.

# See LICENSE.txt for more information.

"""
Draws the icons the Legacy theme needs that the original icon set (yaz0data/ico) never
had, in that set's flat grey (#888888) style, into yaz0data/themes/Legacy/icosm and
icolg. Icons that only changed name are copied from the original set.

Run from the repository root: python tools/legacy_theme_icons.py
"""

import os
import shutil
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5 import QtCore, QtGui, QtWidgets
Qt = QtCore.Qt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICO = os.path.join(ROOT, 'yaz0data', 'ico')
THEME = os.path.join(ROOT, 'yaz0data', 'themes', 'Legacy')
SIZES = {'sm': 16, 'lg': 48}

GREY = QtGui.QColor('#888888')
RED = QtGui.QColor('#ff4444')
GREEN = QtGui.QColor('#44ff44')
BLUE = QtGui.QColor('#4444ff')

# New name: name in the original set
RENAMED = {'select': 'selectall', 'areas': 'area'}


def drawParts(painter, size):
    """The parts bar's menu button: a 2x2 grid of parts, like the objects icon's blocks."""
    gap = max(2, size // 12)
    cell = (size - gap) // 2
    off = (size - (2 * cell + gap)) // 2
    for i, color in enumerate((RED, GREEN, BLUE, GREY)):
        row, col = divmod(i, 2)
        painter.fillRect(off + col * (cell + gap), off + row * (cell + gap), cell, cell, color)


def drawFullscreen(painter, size):
    """Four corner brackets pointing out."""
    width = max(2, size // 8)
    length = size * 3 // 8
    margin = max(1, size // 12)
    far = size - margin
    for x, y, dx, dy in ((margin, margin, 1, 1), (far, margin, -1, 1),
                         (margin, far, 1, -1), (far, far, -1, -1)):
        # A horizontal and a vertical bar from each corner, inside the icon
        hx = x if dx > 0 else x - length
        vy = y if dy > 0 else y - length
        painter.fillRect(hx, y if dy > 0 else y - width, length, width, GREY)
        painter.fillRect(x if dx > 0 else x - width, vy, width, length, GREY)


DRAWN = {'parts': drawParts, 'fullscreen': drawFullscreen}


def main():
    app = QtWidgets.QApplication(sys.argv)
    for kind, size in SIZES.items():
        folder = os.path.join(THEME, 'ico' + kind)
        os.makedirs(folder, exist_ok=True)

        for name, draw in DRAWN.items():
            image = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
            image.fill(Qt.transparent)
            painter = QtGui.QPainter(image)
            draw(painter, size)
            painter.end()
            image.save(os.path.join(folder, 'icon-%s.png' % name))

        for name, original in RENAMED.items():
            shutil.copyfile(os.path.join(ICO, kind, 'icon-%s.png' % original),
                            os.path.join(folder, 'icon-%s.png' % name))
    del app


if __name__ == '__main__':
    main()
