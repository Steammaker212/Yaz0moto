#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Yaz0moto Level Editor
# This file is part of Yaz0moto, a fork of Pyamoto.

# See LICENSE.txt for more information.

"""
Theme variables. The Yaz0moto theme's style sheet, level colours and icons are written
with ${name} placeholders; a theme only chooses a few colours (accent, background,
text, level background) and a roundness, and every other shade is worked out here,
for light themes as well as dark ones. Other themes are built on it by setting
base="Yaz0moto" and their own <variables> in their main.xml.
"""

import os
import re
from xml.sax.saxutils import quoteattr

BASE_THEME = 'Yaz0moto'

# What a theme (or the theme editor) chooses; everything else is derived
INPUTS = ('accent', 'background', 'text', 'level', 'roundness')
DEFAULTS = {
    'accent': '#F7941D',
    'background': '#1C1C1F',
    'text': '#ECECEF',
    'level': '',          # level view background; empty = worked out from the background
    'roundness': '10',    # corner radius of buttons and fields, in pixels
}

# Colours the icon generator (tools/theme_icons.py) uses, and the variable each becomes
ICON_COLORS = {
    '#E9E9EC': 'icon',
    '#F7941D': 'accent',
    '#FFB54D': 'accent_light',
    '#1B1B1E': 'badge',
}

_PLACEHOLDER = re.compile(r'\$\{(\w+)\}')

# The style sheet's small images (check marks, arrows), drawn in each theme's colours
IMAGE_SVGS = {
    'check': '<path d="M3.5 8.4l3 3 6-6.3" fill="none" stroke="${on_accent}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
    'radio': '<circle cx="8" cy="8" r="3.4" fill="${on_accent}"/>',
    'partial': '<path d="M4.5 8h7" fill="none" stroke="${on_accent}" stroke-width="2.2" stroke-linecap="round"/>',
    'down': '<path d="M4.5 6.5L8 10l3.5-3.5" fill="none" stroke="${text}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>',
    'up': '<path d="M4.5 9.5L8 6l3.5 3.5" fill="none" stroke="${text}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>',
    'right': '<path d="M6.5 4.5L10 8l-3.5 3.5" fill="none" stroke="${muted}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>',
}


def image_svg(name, variables):
    """One of the style sheet images as SVG text, in a theme's colours (16x16)."""
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">%s</svg>'
            % substitute(IMAGE_SVGS[name], variables))


def _rgb(color):
    color = color.strip().lstrip('#')
    if len(color) == 3:
        color = ''.join(c * 2 for c in color)
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return '#%02X%02X%02X' % tuple(max(0, min(255, round(c))) for c in rgb)


def mix(a, b, t):
    """Colour a moved t (0-1) of the way towards colour b."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(x + (y - x) * t for x, y in zip(ra, rb))


def luminance(color):
    """Relative luminance (0 = black, 1 = white)."""
    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def is_color(value):
    return isinstance(value, str) and re.fullmatch(r'#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})', value.strip()) is not None


def derive(inputs=None):
    """Every variable the templates use, from a theme's chosen inputs."""
    v = dict(DEFAULTS)
    for key, value in (inputs or {}).items():
        if value not in (None, ''):
            v[key] = value
    for key in ('accent', 'background', 'text'):
        if not is_color(v[key]):
            v[key] = DEFAULTS[key]
        v[key] = _hex(_rgb(v[key]))
    try:
        r = max(0, min(24, int(float(v['roundness']))))
    except (TypeError, ValueError):
        r = int(DEFAULTS['roundness'])

    bg, text, accent = v['background'], v['text'], v['accent']
    dark = luminance(bg) < 0.4
    black, white = '#000000', '#FFFFFF'

    if dark:
        shades = {
            'panel': mix(bg, text, 0.035), 'group': mix(bg, text, 0.02), 'raised': mix(bg, text, 0.07),
            'hover': mix(bg, text, 0.12), 'pressed': mix(bg, text, 0.045), 'line': mix(bg, text, 0.16),
            'edge_light': mix(bg, text, 0.09), 'edge_dark': mix(bg, black, 0.38),
            'field': mix(bg, black, 0.22), 'field_alt': mix(bg, black, 0.12), 'field_disabled': mix(bg, black, 0.08),
            'status': mix(bg, black, 0.12), 'selected_text': white,
        }
    else:
        shades = {
            'panel': mix(bg, black, 0.03), 'group': mix(bg, black, 0.015), 'raised': mix(bg, white, 0.55),
            'hover': mix(bg, black, 0.06), 'pressed': mix(bg, black, 0.09), 'line': mix(bg, black, 0.18),
            'edge_light': mix(bg, white, 0.8), 'edge_dark': mix(bg, black, 0.24),
            'field': mix(bg, white, 0.8), 'field_alt': mix(bg, white, 0.5), 'field_disabled': mix(bg, black, 0.04),
            'status': mix(bg, black, 0.05), 'selected_text': text,
        }

    out = {
        'accent': accent, 'background': bg, 'window': bg, 'text': text,
        'muted': mix(text, bg, 0.35), 'disabled': mix(text, bg, 0.58),
        'accent_light': mix(accent, white, 0.3), 'accent_hover': mix(accent, white, 0.15),
        'accent_dark': mix(accent, black, 0.25),
        'on_accent': '#1B1B1E' if luminance(accent) > 0.3 else white,
        'accent_rgb': '%d, %d, %d' % _rgb(accent),
        'danger': '#E5484D',
        'icon': mix(text, bg, 0.05),
        'level': _hex(_rgb(v['level'])) if is_color(v['level']) else (mix(bg, text, 0.012) if dark else mix(bg, black, 0.6)),
        'roundness': str(r),
        # Qt draws no rounding at all when a radius is over half a control's height, so
        # the radii of small controls stop where they are fully rounded (pill-shaped)
        'radius_s': str(min(7, max(0, round(r * 0.6)))), 'radius': str(min(13, r)),
        'radius_l': str(round(r * 1.3)), 'radius_xl': str(round(r * 1.6)),
        'dark': 'true' if dark else 'false',
    }
    out.update(shades)
    out['badge'] = out['panel']  # the ring cut around icon badges matches the toolbar
    return out


def substitute(text, variables):
    """Replaces ${name} with the variable's value (unknown names are left as they are)."""
    return _PLACEHOLDER.sub(lambda m: variables.get(m.group(1), m.group(0)), text)


def recolor_svg(svg, variables):
    """An icon generated in the default colours, redrawn in a theme's colours."""
    for color, name in ICON_COLORS.items():
        if name in variables:
            svg = re.sub(re.escape(color), variables[name], svg, flags=re.IGNORECASE)
    return svg


def parse_variables(root):
    """The <var name=... value=.../> entries of a theme's <variables> element."""
    out = {}
    for node in root:
        if node.tag.lower() != 'variables':
            continue
        for var in node:
            if var.tag.lower() == 'var' and 'name' in var.attrib and 'value' in var.attrib:
                out[var.attrib['name']] = var.attrib['value']
    return out


def write_theme(folder, name, inputs, creator='', description=''):
    """
    Saves a theme built on the Yaz0moto theme: a folder with a main.xml holding the
    chosen inputs. Returns the folder.
    """
    os.makedirs(folder, exist_ok=True)
    lines = [
        '<?xml version="1.0"?>',
        '<theme format="1.0" name=%s version="1.0" creator=%s description=%s base="%s">'
        % (quoteattr(name), quoteattr(creator or 'You'), quoteattr(description or 'Made with the theme editor.'), BASE_THEME),
        '\t<variables>',
    ]
    for key in INPUTS:
        value = inputs.get(key, DEFAULTS[key])
        if value not in (None, ''):
            lines.append('\t\t<var name="%s" value=%s />' % (key, quoteattr(str(value))))
    lines += ['\t</variables>', '</theme>', '']
    with open(os.path.join(folder, 'main.xml'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))
    return folder
