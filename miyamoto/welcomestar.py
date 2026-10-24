#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Yaz0moto Level Editor
# This file is part of Yaz0moto, a fork of Pyamoto.

# See LICENSE.txt for more information.

"""
The welcome page logo, whose star jumps, spins and sparkles when clicked.

The star is lifted out of the app icon itself: inside the icon's inner square the
background is one flat navy, so flood-filling that navy leaves exactly the star (with its
eyes and glow). The star is then drawn on its own, over the icon with that spot filled.
"""

import math
import random
from collections import deque

from PyQt5 import QtCore, QtGui, QtWidgets
Qt = QtCore.Qt

# Where the flat inner square is, as a share of the icon's size
INNER = (0.16, 0.84)
NAVY_TOLERANCE = 40


def splitStar(image):
    """
    (background without the star, the star alone, the star's centre) from the icon.
    Returns None if the star can't be found.
    """
    image = image.convertToFormat(QtGui.QImage.Format_ARGB32)
    w, h = image.width(), image.height()
    x0, x1 = int(w * INNER[0]), int(w * INNER[1])
    y0, y1 = int(h * INNER[0]), int(h * INNER[1])
    seed = (w // 2, y0 + 2)
    navy = QtGui.QColor(image.pixel(*seed))

    def isNavy(x, y):
        c = image.pixel(x, y)
        return (abs(QtGui.qRed(c) - navy.red()) + abs(QtGui.qGreen(c) - navy.green())
                + abs(QtGui.qBlue(c) - navy.blue())) < NAVY_TOLERANCE

    # Flood the navy from the top of the inner square; what it can't reach is the star
    reached = bytearray(w * h)
    queue = deque([seed])
    reached[seed[1] * w + seed[0]] = 1
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if x0 <= nx < x1 and y0 <= ny < y1 and not reached[ny * w + nx] and isNavy(nx, ny):
                reached[ny * w + nx] = 1
                queue.append((nx, ny))

    star = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)
    star.fill(Qt.transparent)
    background = QtGui.QImage(image)
    grow = max(1, w // 120)  # include the anti-aliased edge
    count = sx = sy = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            if reached[y * w + x]:
                continue
            # Near the star: take the pixel and paint navy behind it
            for yy in range(max(y0, y - grow), min(y1, y + grow + 1)):
                for xx in range(max(x0, x - grow), min(x1, x + grow + 1)):
                    star.setPixel(xx, yy, image.pixel(xx, yy))
                    background.setPixel(xx, yy, navy.rgba())
            count += 1
            sx += x
            sy += y
    if count < (w * h) // 50:
        return None
    return background, star, QtCore.QPointF(sx / count, sy / count)


class AnimatedStarLogo(QtWidgets.QWidget):
    """The app icon; click it and its star hops, spins and sparkles."""

    DURATION = 1100

    def __init__(self, path, size=108, parent=None):
        super().__init__(parent)
        self.logoSize = size
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Hi!')

        dpr = QtWidgets.QApplication.instance().devicePixelRatio()
        px = int(size * dpr)
        icon = QtGui.QImage(path).scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.icon = QtGui.QPixmap.fromImage(icon)
        self.icon.setDevicePixelRatio(dpr)

        self.parts = None
        split = splitStar(icon)
        if split is not None:
            background, star, centre = split
            self.background = QtGui.QPixmap.fromImage(background)
            self.background.setDevicePixelRatio(dpr)
            self.star = QtGui.QPixmap.fromImage(star)
            self.star.setDevicePixelRatio(dpr)
            self.centre = QtCore.QPointF(centre.x() / dpr, centre.y() / dpr)
            self.parts = True

        self.t = None  # animation progress, or None when still
        self.sparkles = []
        self.animation = QtCore.QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(self.DURATION)
        self.animation.valueChanged.connect(self.step)
        self.animation.finished.connect(self.stop)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.play()

    def play(self):
        if self.parts is None:
            return
        self.sparkles = [(random.uniform(0, 2 * math.pi), random.uniform(0.32, 0.5), random.uniform(0.5, 1.0))
                         for _ in range(8)]
        self.animation.stop()
        self.animation.start()

    def step(self, value):
        self.t = float(value)
        self.update()

    def stop(self):
        self.t = None
        self.update()

    def pose(self, t):
        """(lift, angle, x scale, y scale) of the star at time t (0-1)."""
        def ease(u):
            return u * u * (3 - 2 * u)
        size = self.logoSize
        if t < 0.14:                      # crouch
            u = ease(t / 0.14)
            return 0, 0, 1 + 0.12 * u, 1 - 0.14 * u
        if t < 0.55:                      # jump and spin
            u = (t - 0.14) / 0.41
            lift = math.sin(u * math.pi / 2) * size * 0.16
            return lift, 360 * ease(u), 0.95, 1.08
        if t < 0.76:                      # fall
            u = (t - 0.55) / 0.21
            return math.cos(u * math.pi / 2) * size * 0.16, 360, 1.0, 1.04
        if t < 0.88:                      # land with a squash
            u = math.sin((t - 0.76) / 0.12 * math.pi)
            return 0, 360, 1 + 0.16 * u, 1 - 0.18 * u
        u = (t - 0.88) / 0.12             # settle
        return 0, 360, 1 + 0.03 * math.sin(u * math.pi * 2) * (1 - u), 1.0

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        if self.t is None or self.parts is None:
            painter.drawPixmap(0, 0, self.icon)
            return

        size = self.logoSize
        painter.drawPixmap(0, 0, self.background)

        # The star stays inside the icon's inner square
        lo, hi = INNER[0] * size, INNER[1] * size
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(QtCore.QRectF(lo - size * 0.03, lo - size * 0.03, hi - lo + size * 0.06, hi - lo + size * 0.06),
                            size * 0.09, size * 0.09)
        painter.setClipPath(clip)

        lift, angle, sx, sy = self.pose(self.t)
        c = self.centre
        bottom = c.y() + size * 0.3  # squash from the star's feet
        painter.save()
        painter.translate(c.x(), bottom - lift)
        painter.scale(sx, sy)
        painter.translate(0, -(bottom - c.y()))
        painter.rotate(angle)
        painter.translate(-c.x(), -c.y())
        painter.drawPixmap(0, 0, self.star)
        painter.restore()

        # Sparkles flying out while it is in the air
        if 0.15 < self.t < 0.9:
            u = (self.t - 0.15) / 0.75
            painter.setPen(Qt.NoPen)
            for direction, reach, scale in self.sparkles:
                d = reach * size * (0.4 + 0.6 * u)
                x = c.x() + math.cos(direction) * d
                y = c.y() - lift + math.sin(direction) * d
                r = size * 0.035 * scale * (1 - u)
                color = QtGui.QColor(255, 236, 120)
                color.setAlphaF(max(0.0, 1 - u))
                painter.setBrush(color)
                painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, y - 2.4 * r), QtCore.QPointF(x + r, y - r),
                                                     QtCore.QPointF(x + 2.4 * r, y), QtCore.QPointF(x + r, y + r),
                                                     QtCore.QPointF(x, y + 2.4 * r), QtCore.QPointF(x - r, y + r),
                                                     QtCore.QPointF(x - 2.4 * r, y), QtCore.QPointF(x - r, y - r)]))
