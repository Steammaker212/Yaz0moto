#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generates the SVG icons of the "Yaz0moto" theme (miyamotodata/themes/Yaz0moto/icons)
and the small PNG images its style sheet uses (check marks, arrows...).

The look follows the Yaz0moto logo: flat, minimal shapes in a light neutral with
orange accents, on dark charcoal. Qt's SVG renderer has no blur filter, so the soft
shadow under each icon is made of a few faint, slightly offset copies of the shapes.

Edit the colours or shapes below, then run from the repository root:
    python tools/theme_icons.py
"""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME = os.path.join(ROOT, 'miyamotodata', 'themes', 'Yaz0moto')
ICONS = os.path.join(THEME, 'icons')
IMAGES = os.path.join(THEME, 'images')

LIGHT = '#E9E9EC'
ACCENT = '#F7941D'
ACCENT_LIGHT = '#FFB54D'
DARK = '#1B1B1E'
MUTED = '#8E8E96'

# (dy, opacity) of the stacked copies that make the soft drop shadow
SHADOW = ((0.9, 0.30), (1.7, 0.14), (2.5, 0.06))

W = 2.1  # stroke width on the 24-unit grid


################################################################
# Shapes. Each returns SVG markup with {L} {A} {B} {D} {M} colour placeholders,
# so the same shapes can be drawn again in black for the shadow.
################################################################

def stroke(d, color='{L}', width=W, extra=''):
    return ('<path d="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linecap="round" '
            'stroke-linejoin="round"%s/>' % (d, color, width, extra))


def fill(d, color='{L}'):
    return '<path d="%s" fill="%s"/>' % (d, color)


def circle(cx, cy, r, color='{L}', filled=False, width=W):
    if filled:
        return '<circle cx="%g" cy="%g" r="%g" fill="%s"/>' % (cx, cy, r, color)
    return '<circle cx="%g" cy="%g" r="%g" fill="none" stroke="%s" stroke-width="%s"/>' % (cx, cy, r, color, width)


def rect(x, y, w, h, r=2, color='{L}', filled=False, width=W, dash=None):
    style = ('fill="%s"' % color) if filled else (
        'fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round"' % (color, width))
    if dash:
        style += ' stroke-dasharray="%s" stroke-linecap="round"' % dash
    return '<rect x="%g" y="%g" width="%g" height="%g" rx="%g" %s/>' % (x, y, w, h, r, style)


def polygon(points, color='{L}', filled=True, width=W):
    pts = ' '.join('%g,%g' % p for p in points)
    if filled:
        return '<polygon points="%s" fill="%s"/>' % (pts, color)
    return ('<polygon points="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round"/>'
            % (pts, color, width))


def star(cx, cy, r, color='{A}', inner=0.5, rotation=-90):
    pts = []
    for i in range(10):
        a = math.radians(rotation + i * 36)
        rr = r if i % 2 == 0 else r * inner
        pts.append((round(cx + rr * math.cos(a), 2), round(cy + rr * math.sin(a), 2)))
    return polygon(pts, color)


def gear(cx, cy, r, teeth=8, color='{L}'):
    """A gear outline made of trapezoid teeth."""
    pts = []
    for i in range(teeth):
        base = 360 / teeth * i
        for da, rr in ((-14, r * 0.78), (-8, r), (8, r), (14, r * 0.78)):
            a = math.radians(base + da)
            pts.append((round(cx + rr * math.cos(a), 2), round(cy + rr * math.sin(a), 2)))
    return polygon(pts, color, filled=False, width=W * 0.95)


def arrow(x1, y1, x2, y2, color='{A}', head=3.6, width=W):
    """A line with a V head at (x2, y2)."""
    a = math.atan2(y2 - y1, x2 - x1)
    hx1 = x2 - head * math.cos(a - math.radians(40))
    hy1 = y2 - head * math.sin(a - math.radians(40))
    hx2 = x2 - head * math.cos(a + math.radians(40))
    hy2 = y2 - head * math.sin(a + math.radians(40))
    return stroke('M%g %g L%g %g M%.2f %.2f L%g %g L%.2f %.2f' % (x1, y1, x2, y2, hx1, hy1, x2, y2, hx2, hy2),
                  color, width)


# Small badges in the lower right corner (they cut a dark ring into what is under them)

def _badge(cx=17.5, cy=17.5, r=5.2):
    return circle(cx, cy, r + 1.3, '{D}', filled=True) + circle(cx, cy, r, '{A}', filled=True)


def badge_plus(cx=17.5, cy=17.5):
    return _badge(cx, cy) + stroke('M%g %gh5M%g %gv5' % (cx - 2.5, cy, cx, cy - 2.5), '{D}', 1.9)


def badge_minus(cx=17.5, cy=17.5):
    return _badge(cx, cy) + stroke('M%g %gh5' % (cx - 2.5, cy), '{D}', 1.9)


def badge_x(cx=17.5, cy=17.5):
    return _badge(cx, cy) + stroke('M%g %gl4 4M%g %gl-4 4' % (cx - 2, cy - 2, cx + 2, cy - 2), '{D}', 1.9)


def badge_play(cx=17.5, cy=17.5):
    return _badge(cx, cy) + polygon([(cx - 1.6, cy - 2.6), (cx - 1.6, cy + 2.6), (cx + 2.8, cy)], '{D}')


def badge_lock(cx=17.5, cy=17.5):
    return (circle(cx, cy, 6.6, '{D}', filled=True)
            + rect(cx - 4, cy - 0.8, 8, 6, 1.4, '{A}', filled=True)
            + stroke('M%g %gv-2a2.4 2.4 0 0 1 4.8 0v2' % (cx - 2.4, cy - 0.6), '{A}', 1.7))


def badge_arrow_down(cx=17.5, cy=17.5):
    return _badge(cx, cy) + arrow(cx, cy - 2.8, cx, cy + 2.6, '{D}', 2.6, 1.9)


def badge_arrow_up(cx=17.5, cy=17.5):
    return _badge(cx, cy) + arrow(cx, cy + 2.8, cx, cy - 2.6, '{D}', 2.6, 1.9)


def badge_pencil(cx=17.5, cy=17.5):
    return _badge(cx, cy) + stroke('M%g %gl4.4 -4.4' % (cx - 2.4, cy + 2.4), '{D}', 2.2)


def badge_check(cx=17.5, cy=17.5):
    return _badge(cx, cy) + stroke('M%g %gl1.8 1.8l3.4 -3.6' % (cx - 2.6, cy + 0.2), '{D}', 1.9)


# Reusable pictures

def doc(right_cut=False):
    body = 'M6 3h7.5L18 7.5V20a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1z'
    return stroke(body) + stroke('M13.5 3v4.5H18')


def folder(front=True):
    out = stroke('M3 8V6a1.5 1.5 0 0 1 1.5-1.5h4l2 2.2h8A1.5 1.5 0 0 1 20 8.2V18a1.5 1.5 0 0 1-1.5 1.5h-14A1.5 1.5 0 0 1 3 18z')
    if front:
        out += fill('M3.6 10.2h17a.9.9 0 0 1 .9 1.1l-1.4 7a1.5 1.5 0 0 1-1.5 1.2H4.5A1.5 1.5 0 0 1 3 18v-6.9a.9.9 0 0 1 .6-.9z', '{A}')
    return out


def magnifier(inner=''):
    return circle(10.5, 10.5, 6.2) + stroke('M15.2 15.2L20.5 20.5', '{L}', 2.6) + inner


def layers(highlight=None):
    """Three stacked diamonds; highlight 0/1/2 (bottom/middle/top) is drawn orange."""
    out = ''
    for level, y in ((0, 15.5), (1, 11.5), (2, 7.5)):
        color = '{A}' if highlight == level else '{L}'
        if highlight == level:
            out += polygon([(12, y - 4.2), (20, y), (12, y + 4.2), (4, y)], '{A}')
        else:
            out += polygon([(12, y - 4.2), (20, y), (12, y + 4.2), (4, y)], color, filled=False, width=1.8)
    return out


def landscape():
    return (rect(3, 5, 18, 14, 2.4)
            + stroke('M3.8 16.5l5-5 4 4 2.4-2.4 4.6 4.6')
            + circle(15.5, 9.5, 1.9, '{A}', filled=True))


def paths_glyph(square=False):
    out = stroke('M5 18L10 8L15 15L19.5 6', '{L}', 1.9)
    for x, y in ((5, 18), (10, 8), (15, 15), (19.5, 6)):
        if square:
            out += rect(x - 2.2, y - 2.2, 4.4, 4.4, 1, '{A}', filled=True)
        else:
            out += circle(x, y, 2.4, '{A}', filled=True)
    return out


def block():
    return (rect(4, 4, 16, 16, 3.2)
            + rect(8, 8, 8, 8, 1.6, '{A}', filled=True))


def door():
    return (stroke('M6.5 21V8.5a5.5 5.5 0 0 1 11 0V21')
            + stroke('M4 21h16')
            + circle(14.6, 14, 1.4, '{A}', filled=True))


def location_glyph():
    return (rect(4, 6, 16, 12, 1.5, '{L}', dash='3 3')
            + rect(2.6, 4.6, 3, 3, 0.8, '{A}', filled=True) + rect(18.4, 16.4, 3, 3, 0.8, '{A}', filled=True))


def bubble():
    return (stroke('M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 4v-4A2.5 2.5 0 0 1 4 13.5z')
            + circle(8.6, 10, 1.3, '{A}', filled=True) + circle(12, 10, 1.3, '{A}', filled=True)
            + circle(15.4, 10, 1.3, '{A}', filled=True))


def floppy():
    return (stroke('M5 3.5h11.5L20.5 7.5V19a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 19V5A1.5 1.5 0 0 1 5 3.5z')
            + stroke('M7.5 3.8v4.4h7V3.8')
            + rect(7, 13, 10, 7.2, 1.2, '{A}', filled=True))


def corners():
    return stroke('M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4')


################################################################
# The icons
################################################################

ICON_SHAPES = {
    'new': lambda: doc() + badge_plus(),
    'open': lambda: folder(),
    'openfromfile': lambda: doc() + badge_arrow_up(),
    'recent': lambda: circle(12, 12, 8.5) + stroke('M12 7.2V12l3.4 2.2', '{A}', 2.3),
    'save': floppy,
    'saveas': lambda: floppy() + badge_pencil(),
    'info': lambda: circle(12, 12, 8.5) + stroke('M12 11v5.2', '{A}', 2.5) + circle(12, 7.8, 1.5, '{A}', filled=True),
    'screenshot': lambda: (stroke('M4 8.5A1.5 1.5 0 0 1 5.5 7h2.3l1.6-2.2h5.2L16.2 7h2.3A1.5 1.5 0 0 1 20 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5z')
                           + circle(12, 12.8, 3.6, '{A}', filled=True)),
    'folderpath': lambda: folder(front=False) + arrow(10, 15.5, 15.5, 10, '{A}', 3.2, 2.2),
    'animation': lambda: rect(3.5, 5, 17, 14, 3) + polygon([(10, 8.6), (10, 15.4), (15.6, 12)], '{A}'),
    'settings': lambda: gear(12, 12, 9) + circle(12, 12, 3, '{A}', filled=True),
    'delete': lambda: (stroke('M5 7h14M9.5 7V5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v2')
                       + stroke('M6.8 7l.9 12.2a1.5 1.5 0 0 0 1.5 1.3h5.6a1.5 1.5 0 0 0 1.5-1.3L17.2 7')
                       + stroke('M10.3 11v5.5M13.7 11v5.5', '{A}', 2)),
    'select': lambda: rect(3.5, 3.5, 13, 13, 1.5, '{L}', dash='2.6 2.6') + polygon([(12, 11), (21, 15), (17, 16.4), (19.6, 20.4), (17.9, 21.4), (15.4, 17.5), (12.6, 20.3)], '{A}'),
    'selectall': lambda: rect(3.5, 3.5, 17, 17, 2, '{L}', dash='2.6 2.6') + rect(8, 8, 8, 8, 1.6, '{A}', filled=True),
    'deselect': lambda: rect(3.5, 3.5, 14, 14, 1.5, '{L}', dash='2.6 2.6') + badge_x(),
    'undo': lambda: stroke('M8 9h7.5a4.5 4.5 0 0 1 0 9H10') + arrow(12.2, 9, 7, 9, '{A}', 4.2, 2.4),
    'redo': lambda: stroke('M16 9H8.5a4.5 4.5 0 0 0 0 9H14') + arrow(11.8, 9, 17, 9, '{A}', 4.2, 2.4),
    'cut': lambda: (stroke('M8.6 8.6L18.5 19.5M15.4 8.6L5.5 19.5')
                    + circle(7, 6, 2.7, '{A}', width=2.2) + circle(17, 6, 2.7, '{A}', width=2.2)),
    'copy': lambda: rect(8.5, 8.5, 12, 12, 2.4, '{A}', filled=True) + stroke('M15.5 5.5V5a1.5 1.5 0 0 0-1.5-1.5H5A1.5 1.5 0 0 0 3.5 5v9A1.5 1.5 0 0 0 5 15.5h.5'),
    'paste': lambda: (stroke('M8.5 5H6.5A1.5 1.5 0 0 0 5 6.5v13A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5v-13A1.5 1.5 0 0 0 17.5 5h-2')
                      + rect(8.5, 3, 7, 4, 1.3) + rect(8.5, 10.5, 7, 7, 1.2, '{A}', filled=True)),
    'raise': lambda: layers() + badge_arrow_up(17.5, 6.5),
    'lower': lambda: layers() + badge_arrow_down(17.5, 17.5),
    'move': lambda: (stroke('M12 3.5v17M3.5 12h17')
                     + stroke('M9.5 6L12 3.5 14.5 6M9.5 18L12 20.5 14.5 18M6 9.5L3.5 12 6 14.5M18 9.5L20.5 12 18 14.5')
                     + circle(12, 12, 2.6, '{A}', filled=True)),
    'merge': lambda: stroke('M5 4.5c0 6 7 6 7 11v4.5M19 4.5c0 6-7 6-7 11') + arrow(12, 15, 12, 20.5, '{A}', 3.6, 2.4),
    'swap': lambda: arrow(4, 8.5, 19, 8.5, '{L}', 3.8) + arrow(20, 15.5, 5, 15.5, '{A}', 3.8, 2.4),
    'objects': block,
    'objectsfreeze': lambda: block() + badge_lock(),
    'sprites': lambda: star(12, 12.6, 9.2, '{A}', 0.48) + circle(10.2, 11.6, 1.05, '{D}', filled=True) + circle(13.8, 11.6, 1.05, '{D}', filled=True),
    'spritesfreeze': lambda: star(11, 11.5, 8.4, '{A}', 0.48) + badge_lock(),
    'spritesadd': lambda: star(11, 11.5, 8.4, '{A}', 0.48) + badge_plus(),
    'spritelist': lambda: star(6.5, 6.5, 3.6, '{A}') + star(6.5, 13.5, 3.6, '{A}') + stroke('M12 6.5h8.5M12 13.5h8.5M5 20h15.5', '{L}', 2),
    'entrances': door,
    'entrancesfreeze': lambda: door() + badge_lock(),
    'locations': location_glyph,
    'locationsfreeze': lambda: location_glyph() + badge_lock(),
    'paths': paths_glyph,
    'pathsfreeze': lambda: paths_glyph() + badge_lock(),
    'nabbitpath': lambda: paths_glyph(square=True),
    'progresspaths': lambda: stroke('M4 18c4 0 4-10 8-10s4 6 8 6', '{L}', 2) + circle(4, 18, 2.4, '{A}', filled=True) + arrow(17, 14, 20.5, 14, '{A}', 3.4, 2.3),
    'progresspathsfreeze': lambda: stroke('M4 16c3 0 3-8 6.5-8s3 5 6 5', '{L}', 2) + circle(4, 16, 2.4, '{A}', filled=True) + badge_lock(),
    'comments': bubble,
    'commentsfreeze': lambda: bubble() + badge_lock(),
    'zones': lambda: corners() + rect(8, 8, 8, 8, 1.8, '{A}', filled=True),
    'area': lambda: rect(4, 4, 16, 16, 3) + stroke('M4 12h16M12 4v16', '{L}', 1.6) + rect(12.8, 12.8, 6.4, 6.4, 1.6, '{A}', filled=True),
    'areas': lambda: rect(7.5, 3.5, 13, 13, 2.6) + rect(3.5, 7.5, 13, 13, 2.6, '{A}', filled=True),
    'add': lambda: circle(12, 12, 8.8, '{A}', filled=True) + stroke('M12 7.5v9M7.5 12h9', '{D}', 2.4),
    'import': lambda: stroke('M4 14v4.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V14') + arrow(12, 3.5, 12, 15, '{A}', 4, 2.4),
    'download': lambda: stroke('M5 20h14') + arrow(12, 3.5, 12, 16, '{A}', 4.6, 2.5),
    'reload': lambda: stroke('M19.5 12a7.5 7.5 0 1 1-2.6-5.7') + polygon([(20.6, 3.6), (20.6, 9.4), (14.8, 9.4)], '{A}'),
    'help': lambda: circle(12, 12, 8.5) + stroke('M9.4 9.6a2.7 2.7 0 1 1 3.6 2.5c-.8.3-1 .9-1 1.6v.6', '{A}', 2.3) + circle(12, 17.2, 1.4, '{A}', filled=True),
    'contents': lambda: (stroke('M12 6.5C10 5 7 4.5 4 5v13c3-.5 6 0 8 1.5 2-1.5 5-2 8-1.5V5c-3-.5-6 0-8 1.5z')
                         + stroke('M12 6.5v13', '{A}', 2.2)),
    'qt': lambda: rect(3.5, 3.5, 17, 17, 4.5) + circle(11.5, 11.5, 3.8, '{A}', width=2.3) + stroke('M13.8 13.8l3 3', '{A}', 2.4),
    'overview': lambda: rect(3, 5, 18, 14, 2.4) + rect(6.5, 8.5, 6.5, 5, 1.2, '{A}', filled=True),
    'palette': lambda: (stroke('M12 3.5a8.5 8.5 0 1 0 0 17c1.4 0 2-.8 2-1.8 0-1.5-1.2-1.7-1.2-3 0-1 .8-1.7 1.8-1.7h2.2a3.7 3.7 0 0 0 3.7-3.7C20.5 6.8 16.7 3.5 12 3.5z')
                        + circle(8, 10.5, 1.5, '{A}', filled=True) + circle(11.5, 7.5, 1.5, '{A}', filled=True)
                        + circle(15.5, 8.5, 1.5, '{A}', filled=True)),
    'diagnostics': lambda: rect(3.5, 4, 17, 16, 3) + stroke('M6 12.5h3l1.8-4 2.6 8 1.8-4H18', '{A}', 2.1),
    'check': lambda: circle(12, 12, 8.8, '{A}', filled=True) + stroke('M8 12.3l2.7 2.7 5.4-5.6', '{D}', 2.4),
    'warning': lambda: polygon([(12, 3.5), (21, 19.5), (3, 19.5)], '{L}', filled=False) + stroke('M12 9.5v4.8', '{A}', 2.5) + circle(12, 16.9, 1.4, '{A}', filled=True),
    'tips': lambda: (stroke('M9 17.5h6M10 20.5h4')
                     + fill('M12 3a6.3 6.3 0 0 1 3.8 11.3c-.6.5-.9 1.1-.9 1.8H9.1c0-.7-.3-1.3-.9-1.8A6.3 6.3 0 0 1 12 3z', '{A}')),
    'note': lambda: fill('M5 4h14a1 1 0 0 1 1 1v9.5L14.5 20H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z', '{A}') + fill('M14.5 20v-4.5a1 1 0 0 1 1-1H20z', '{D}') + stroke('M7.5 8.5h9M7.5 11.5h6', '{D}', 1.8),
    'data': lambda: (stroke('M5 6.5c0-1.7 3.1-3 7-3s7 1.3 7 3v11c0 1.7-3.1 3-7 3s-7-1.3-7-3z')
                     + stroke('M5 6.5c0 1.7 3.1 3 7 3s7-1.3 7-3', '{A}', 2.1) + stroke('M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3', '{L}', 1.8)),
    'depth': lambda: layers(0) + arrow(20.5, 4, 20.5, 10, '{L}', 2.6, 1.8),
    'layer': lambda: layers(1),
    'layer0': lambda: layers(0),
    'layer1': lambda: layers(1),
    'layer2': lambda: layers(2),
    'collisions': lambda: rect(4, 4, 16, 16, 3) + stroke('M8 20L20 8M4 16L16 4M13 20.2L20.2 13', '{A}', 1.9),
    'realview': lambda: (stroke('M2.8 12C5 7.8 8.3 5.5 12 5.5s7 2.3 9.2 6.5c-2.2 4.2-5.5 6.5-9.2 6.5S5 16.2 2.8 12z')
                         + circle(12, 12, 3.6, '{A}', filled=True)),
    'background': landscape,
    'livebganim': lambda: landscape() + badge_play(),
    'liquids': lambda: fill('M12 3.2c3.2 4.4 6 7.6 6 11a6 6 0 0 1-12 0c0-3.4 2.8-6.6 6-11z', '{A}') + stroke('M9.4 14.6a2.7 2.7 0 0 0 2.6 2.6', '{D}', 1.6),
    'islandgen': lambda: stroke('M3 18.5c3-4 15-4 18 0') + stroke('M3 21h18', '{L}', 1.6) + circle(15.5, 7.5, 3, '{A}', filled=True),
    'events': lambda: polygon([(13.5, 2.8), (5.5, 13.4), (11.2, 13.4), (10, 21.2), (18.5, 10.2), (12.6, 10.2)], '{A}'),
    'stamp': lambda: stroke('M9 10.5c0-1.6-1.5-2.5-1.5-4.5a4.5 4.5 0 0 1 9 0c0 2-1.5 2.9-1.5 4.5v1.5') + rect(4, 12.5, 16, 4.5, 1.6, '{A}', filled=True) + stroke('M6 20.5h12'),
    'rotation': lambda: stroke('M19.5 12a7.5 7.5 0 1 1-7.5-7.5') + polygon([(12, 1.2), (12, 7.8), (16.4, 4.5)], '{A}') + circle(12, 12, 2.2, '{A}', filled=True),
    'grid': lambda: rect(4, 4, 16, 16, 2.6) + stroke('M9.33 4.5v15M14.67 4.5v15M4.5 9.33h15M4.5 14.67h15', '{L}', 1.4) + rect(9.33, 9.33, 5.34, 5.34, 0.6, '{A}', filled=True),
    'fullscreen': lambda: (arrow(9.5, 9.5, 4.5, 4.5, '{L}', 3.6) + arrow(14.5, 9.5, 19.5, 4.5, '{L}', 3.6)
                           + arrow(9.5, 14.5, 4.5, 19.5, '{L}', 3.6) + arrow(14.5, 14.5, 19.5, 19.5, '{L}', 3.6)
                           + circle(12, 12, 1.9, '{A}', filled=True)),
    'zoomin': lambda: magnifier(stroke('M10.5 7.8v5.4M7.8 10.5h5.4', '{A}', 2.3)),
    'zoomout': lambda: magnifier(stroke('M7.8 10.5h5.4', '{A}', 2.3)),
    'zoomactual': lambda: magnifier(stroke('M9.6 8.4l1.4-1v6.6', '{A}', 2.1)),
    'zoommax': lambda: magnifier(stroke('M8 8h5v5', '{A}', 2.1) + stroke('M8 13l5-5', '{A}', 2.1)),
    'zoommin': lambda: magnifier(rect(8.4, 8.4, 4.2, 4.2, 1, '{A}', filled=True)),
    'parts': lambda: (rect(3.5, 3.5, 7.5, 7.5, 2.2, '{L}', filled=True) + rect(13, 3.5, 7.5, 7.5, 2.2, '{A}', filled=True)
                      + rect(3.5, 13, 7.5, 7.5, 2.2, '{L}', filled=True) + rect(13, 13, 7.5, 7.5, 2.2, '{L}', filled=True)),
    'miyamoto': lambda: (rect(2.5, 2.5, 19, 19, 5.5, '{D}', filled=True)
                         + polygon([(6.5, 6), (10, 6), (12, 9.6), (14, 6), (17.5, 6), (13.6, 12.6), (13.6, 18), (10.4, 18), (10.4, 12.6)], '{A}')),
}


################################################################
# Writing
################################################################

def colours(markup, shadow_opacity=None):
    if shadow_opacity is None:
        return markup.format(L=LIGHT, A=ACCENT, B=ACCENT_LIGHT, D=DARK, M=MUTED)
    black = markup.format(L='#000', A='#000', B='#000', D='#000', M='#000')
    return (black.replace('fill="#000"', 'fill="#000" fill-opacity="%g"' % shadow_opacity)
                 .replace('stroke="#000"', 'stroke="#000" stroke-opacity="%g"' % shadow_opacity))


def svg(markup):
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">']
    for dy, opacity in SHADOW:
        parts.append('<g transform="translate(0,%g)">%s</g>' % (dy, colours(markup, opacity)))
    parts.append(colours(markup))
    parts.append('</svg>')
    return '\n'.join(parts) + '\n'


def write_images():
    """
    The style sheet's small images in the default colours, as PNG (1x and @2x). They are
    only a fallback: Yaz0moto draws them in each theme's own colours when it loads.
    """
    sys.path.insert(0, ROOT)
    from miyamoto import themevars
    from PyQt5 import QtCore, QtGui, QtSvg, QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    variables = themevars.derive()
    os.makedirs(IMAGES, exist_ok=True)
    for name in themevars.IMAGE_SVGS:
        renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(themevars.image_svg(name, variables).encode()))
        for scale, suffix in ((1, ''), (2, '@2x')):
            image = QtGui.QImage(16 * scale, 16 * scale, QtGui.QImage.Format_ARGB32_Premultiplied)
            image.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(image)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            renderer.render(painter)
            painter.end()
            image.save(os.path.join(IMAGES, '%s%s.png' % (name, suffix)))
    del app
    return len(themevars.IMAGE_SVGS)


def main():
    os.makedirs(ICONS, exist_ok=True)
    for name, shapes in sorted(ICON_SHAPES.items()):
        with open(os.path.join(ICONS, 'icon-%s.svg' % name), 'w', encoding='utf-8', newline='\n') as f:
            f.write(svg(shapes()))
    print('Wrote %d icons to %s' % (len(ICON_SHAPES), ICONS))
    if '--no-images' not in sys.argv:
        count = write_images()
        print('Wrote %d style sheet images to %s' % (count, IMAGES))


if __name__ == '__main__':
    main()
