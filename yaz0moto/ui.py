#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Pyamoto Level Editor
# Copyright (C) 2009-2026 Pyamoto contributors
# This file is part of Pyamoto.

# See LICENSE.txt for more information.


################################################################
################################################################

############ Imports ############

import os
from xml.etree import ElementTree as etree

from PyQt5 import QtCore, QtGui, QtWidgets
Qt = QtCore.Qt

from . import globals
from . import themevars
from .misc import setting

try:
    from PyQt5 import QtSvg
except ImportError:  # SVG icons then fall back to the default ones
    QtSvg = None

# Sizes SVG icons are drawn at (Qt picks the closest for each use)
_SVG_SIZES_SM = (16, 20, 24, 32, 40, 48)
_SVG_SIZES_LG = (32, 48, 64, 96, 128)


def themeImages(variables):
    """
    The folder of the style sheet images (check marks, arrows) drawn in a theme's colours,
    made once per set of colours in the user data folder. None if they can't be drawn.
    """
    if QtSvg is None:
        return None
    import hashlib
    key = hashlib.sha1(repr(sorted(variables.items())).encode()).hexdigest()[:12]
    folder = os.path.join(globals.user_data_path, 'cache', 'theme-images', key)
    if all(os.path.isfile(os.path.join(folder, name + '.png')) for name in themevars.IMAGE_SVGS):
        return folder
    try:
        os.makedirs(folder, exist_ok=True)
        for name in themevars.IMAGE_SVGS:
            renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(themevars.image_svg(name, variables).encode('utf-8')))
            for scale, suffix in ((1, ''), (2, '@2x')):
                image = QtGui.QImage(16 * scale, 16 * scale, QtGui.QImage.Format_ARGB32_Premultiplied)
                image.fill(QtCore.Qt.transparent)
                painter = QtGui.QPainter(image)
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
                renderer.render(painter)
                painter.end()
                image.save(os.path.join(folder, name + suffix + '.png'))
    except OSError:
        return None
    return folder


class _LazySvgIcon:
    """An SVG theme icon that hasn't been drawn yet."""
    def __init__(self, path, big, variables=None):
        self.path, self.big, self.variables = path, big, variables


def svgIcon(path, big=False, variables=None):
    """
    An icon drawn from an SVG file at several sizes, or None if it can't be drawn.
    With a theme's variables, the icon's default colours are swapped for the theme's.
    """
    if QtSvg is None:
        return None
    try:
        with open(path, encoding='utf-8') as f:
            svg = f.read()
    except OSError:
        return None
    if variables:
        svg = themevars.recolor_svg(svg, variables)
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode('utf-8')))
    if not renderer.isValid():
        return None

    icon = QtGui.QIcon()
    for size in (_SVG_SIZES_LG if big else _SVG_SIZES_SM):
        image = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        renderer.render(painter)
        painter.end()
        pixmap = QtGui.QPixmap.fromImage(image)
        # The same picture when selected/hovered, rather than one tinted with the highlight colour
        for mode in (QtGui.QIcon.Normal, QtGui.QIcon.Active, QtGui.QIcon.Selected):
            icon.addPixmap(pixmap, mode)
    return icon

#################################


def themeDirectories():
    """Return theme roots in load-precedence order."""
    return (
        os.path.join(globals.user_data_path, 'themes'),
        os.path.join(globals.miyamoto_path, 'yaz0data', 'themes'),
    )


def resolveThemeFolder(name):
    """Resolve a theme folder name, preferring a user-installed theme."""
    if (not isinstance(name, str) or not name or name in ('.', '..')
            or '/' in name or '\\' in name):
        raise FileNotFoundError(f'Invalid theme folder: {name!r}')

    for root in themeDirectories():
        candidate = os.path.join(root, name)
        if os.path.isdir(candidate):
            return candidate
    raise FileNotFoundError(f'Theme folder not found: {name}')


def availableThemes():
    """Return valid theme folder names from bundled and user theme roots."""
    names = set()
    for root in reversed(themeDirectories()):
        try:
            entries = os.listdir(root)
        except OSError:
            continue
        for name in entries:
            folder = os.path.join(root, name)
            if name != 'Classic' and os.path.isdir(folder) and os.path.isfile(
                    os.path.join(folder, 'main.xml')):
                names.add(name)
    return tuple(sorted(names, key=str.casefold))


class MiyamotoTheme:
    """
    Class that represents a Miyamoto theme
    """

    def __init__(self, folder=None):
        """
        Initializes the theme
        """
        self.initAsClassic()
        if folder and folder != "Classic": self.initFromFolder(folder)

    def initAsClassic(self):
        """
        Initializes the theme as the hardcoded Classic theme
        """
        self.fileName = 'Classic'
        self.styleSheet = ''
        self.formatver = 1.0
        self.version = 1.0
        self.themeName = 'Classic'
        self.creator = 'Treeki, Tempus'
        self.description = 'The default Yaz0moto theme.'
        self.iconCacheSm = {}
        self.iconCacheLg = {}
        self.style = None
        self.forceUiColor = False
        self.forceStyleSheet = False
        self.toolbarIconSize = None
        self.base = None  # the theme this one is built on (its folder name)
        self.folder = None
        self.variableInputs = {}
        self.variables = None

        # Add the colours                                             # Descriptions:
        self.colors = {
            'bg': QtGui.QColor(119, 136, 153),  # Main scene background fill
            'comment_fill': QtGui.QColor(220, 212, 135, 120),  # Unselected comment fill
            'comment_fill_s': QtGui.QColor(254, 240, 240, 240),  # Selected comment fill
            'comment_lines': QtGui.QColor(192, 192, 192, 120),  # Unselected comment lines
            'comment_lines_s': QtGui.QColor(220, 212, 135, 240),  # Selected comment lines
            'entrance_fill': QtGui.QColor(190, 0, 0, 120),  # Unselected entrance fill
            'entrance_fill_s': QtGui.QColor(190, 0, 0, 240),  # Selected entrance fill
            'entrance_lines': QtGui.QColor(0, 0, 0),  # Unselected entrance lines
            'entrance_lines_s': QtGui.QColor(255, 255, 255),  # Selected entrance lines
            'grid': QtGui.QColor(255, 255, 255, 100),  # Grid
            'location_fill': QtGui.QColor(114, 42, 188, 70),  # Unselected location fill
            'location_fill_s': QtGui.QColor(170, 128, 215, 100),  # Selected location fill
            'location_lines': QtGui.QColor(0, 0, 0),  # Unselected location lines
            'location_lines_s': QtGui.QColor(255, 255, 255),  # Selected location lines
            'location_text': QtGui.QColor(255, 255, 255),  # Location text
            'object_fill_s': QtGui.QColor(255, 255, 255, 64),  # Select object fill
            'object_lines_s': QtGui.QColor(255, 255, 255),  # Selected object lines
            'overview_entrance': QtGui.QColor(255, 0, 0),  # Overview entrance fill
            'overview_location_fill': QtGui.QColor(114, 42, 188, 50),  # Overview location fill
            'overview_location_lines': QtGui.QColor(0, 0, 0),  # Overview location lines
            'overview_object': QtGui.QColor(255, 255, 255),  # Overview object fill
            'overview_sprite': QtGui.QColor(0, 92, 196),  # Overview sprite fill
            'overview_viewbox': QtGui.QColor(0, 0, 255),  # Overview background fill
            'overview_zone_fill': QtGui.QColor(47, 79, 79, 120),  # Overview zone fill
            'overview_zone_lines': QtGui.QColor(0, 255, 255),  # Overview zone lines
            'path_connector': QtGui.QColor(6, 249, 20),  # Path node connecting lines
            'nabbit_path_connector': QtGui.QColor(161, 69, 255),  # Nabbit path node connecting lines
            'path_fill': QtGui.QColor(6, 249, 20, 120),  # Unselected path node fill
            'path_fill_s': QtGui.QColor(6, 249, 20, 240),  # Selected path node fill
            'nabbit_path_fill': QtGui.QColor(161, 69, 255, 120),  # Unselected nabbit path node fill
            'nabbit_path_fill_s': QtGui.QColor(161, 69, 255, 240),  # Selected nabbit path node fill
            'path_lines': QtGui.QColor(0, 0, 0),  # Unselected path node lines
            'path_lines_s': QtGui.QColor(255, 255, 255),  # Selected path node lines
            'nabbit_path_lines': QtGui.QColor(0, 0, 0),  # Unselected nabbit path node lines
            'nabbit_path_lines_s': QtGui.QColor(255, 255, 255),  # Selected nabbit path node lines
            'smi': QtGui.QColor(255, 255, 255, 80),  # Sprite movement indicator
            'sprite_fill_s': QtGui.QColor(255, 255, 255, 64),  # Selected sprite w/ image fill
            'sprite_lines_s': QtGui.QColor(255, 255, 255),  # Selected sprite w/ image lines
            'spritebox_fill': QtGui.QColor(0, 92, 196, 120),  # Unselected sprite w/o image fill
            'spritebox_fill_s': QtGui.QColor(0, 92, 196, 240),  # Selected sprite w/o image fill
            'spritebox_lines': QtGui.QColor(0, 0, 0),  # Unselected sprite w/o image fill
            'spritebox_lines_s': QtGui.QColor(255, 255, 255),  # Selected sprite w/o image fill
            'zone_entrance_helper': QtGui.QColor(190, 0, 0, 120),  # Zone entrance-placement left border indicator
            'zone_lines': QtGui.QColor(145, 200, 255, 176),  # Zone lines
            'zone_corner': QtGui.QColor(255, 255, 255),  # Zone grabbers/corners
            'zone_dark_fill': QtGui.QColor(0, 0, 0, 48),  # Zone fill when dark
            'zone_text': QtGui.QColor(44, 64, 84),  # Zone text
        }

    def initFromFolder(self, folder):
        """
        Initializes the theme from the folder. A theme with base="..." in its main.xml
        is built on that theme: the base's files are loaded first, filled in with this
        theme's <variables>, then this theme's own files are applied on top.
        """
        folder = resolveThemeFolder(folder)

        # Create a XML ElementTree
        maintree = etree.parse(os.path.join(folder, 'main.xml'))
        root = maintree.getroot()

        # Parse the attributes of the <theme> tag
        if not self.parseMainXMLHead(root):
            # The attributes are messed up
            return

        layers = []
        inputs = {}
        base = root.attrib.get('base')
        if base and base != os.path.basename(folder):
            baseFolder = resolveThemeFolder(base)
            baseRoot = etree.parse(os.path.join(baseFolder, 'main.xml')).getroot()
            inputs.update(themevars.parse_variables(baseRoot))
            layers.append((baseFolder, baseRoot))
            self.base = base
            # What the base theme is drawn for, unless this theme says otherwise
            if self.style is None:
                self.style = baseRoot.attrib.get('style')
            if self.toolbarIconSize is None and 'toolbarIconSize' in baseRoot.attrib:
                try:
                    self.toolbarIconSize = int(baseRoot.attrib['toolbarIconSize'])
                except ValueError:
                    pass
        inputs.update(themevars.parse_variables(root))
        layers.append((folder, root))

        self.folder = folder
        self.variableInputs = inputs
        self.variables = themevars.derive(inputs) if inputs else None

        for layerFolder, layerRoot in layers:
            self.loadNodes(layerFolder, layerRoot)

    def loadNodes(self, folder, root):
        """
        Loads the colours, style sheet and icons listed in a main.xml
        """
        for node in root:
            if node.tag.lower() == 'colors':
                if 'file' not in node.attrib: continue

                # Load the colors XML
                self.loadColorsXml(os.path.join(folder, node.attrib['file']))

            elif node.tag.lower() == 'qss':
                if 'file' not in node.attrib: continue

                # Load the style sheet
                self.loadStyleSheet(os.path.join(folder, node.attrib['file']))

            elif node.tag.lower() == 'icons':
                if not all(thing in node.attrib for thing in ['size', 'folder']): continue

                foldername = node.attrib['folder']
                big = node.attrib['size'].lower()[:2] == 'lg'
                cache = self.iconCacheLg if big else self.iconCacheSm
                iconFolder = os.path.join(folder, foldername)
                if not os.path.isdir(iconFolder): continue

                # Load the icons: icon-<name>.png, or icon-<name>.svg (drawn sharp at every size)
                for iconfilename in os.listdir(iconFolder):
                    stem, ext = os.path.splitext(iconfilename)
                    if not stem.startswith('icon-') or len(stem) <= len('icon-'): continue
                    iconname = stem[len('icon-'):]
                    path = os.path.join(iconFolder, iconfilename)

                    if ext.lower() == '.svg':
                        if QtSvg is None: continue
                        ico = _LazySvgIcon(path, big, self.variables)  # drawn when first used
                    elif ext.lower() == '.png':
                        pix = QtGui.QPixmap(path)
                        if pix.isNull(): continue
                        ico = QtGui.QIcon(pix)
                    else:
                        continue

                    cache[iconname] = ico

                ##        # Add some overview colors if they weren't specified
                ##        fallbacks = {
                ##            'overview_entrance': 'entrance_fill',
                ##            'overview_location_fill': 'location_fill',
                ##            'overview_location_lines': 'location_lines',
                ##            'overview_sprite': 'sprite_fill',
                ##            'overview_zone_lines': 'zone_lines',
                ##            }
                ##        for index in fallbacks:
                ##            if (index not in colors) and (fallbacks[index] in colors): colors[index] = colors[fallbacks[index]]
                ##
                ##        # Use the new colors dict to overwrite values in self.colors
                ##        for index in colors:
                ##            self.colors[index] = colors[index]

    def parseMainXMLHead(self, root):
        """
        Parses the main attributes of main.xml
        """
        MaxSupportedXMLVersion = 1.0
        self.styleSheet = ''

        # Check for required attributes
        if root.tag.lower() != 'theme': return False
        if 'format' in root.attrib:
            formatver = root.attrib['format']
            try:
                self.formatver = float(formatver)
            except ValueError:
                return False
        else:
            return False

        if self.formatver > MaxSupportedXMLVersion:
            return False

        if 'name' in root.attrib:
            self.themeName = root.attrib['name']
        else:
            return False

        # Check for optional attributes
        self.creator = '<i>(unknown)</i>'
        self.description = '<i>No description</i>'
        self.style = None
        self.forceUiColor = False
        self.forceStyleSheet = False
        self.version = 1.0
        if 'creator' in root.attrib: self.creator = root.attrib['creator']
        if 'description' in root.attrib: self.description = root.attrib['description']
        if 'style' in root.attrib: self.style = root.attrib['style']
        if 'forceUiColor' in root.attrib: self.forceUiColor = True if root.attrib['forceUiColor'] == "true" else False
        if 'forceStyleSheet' in root.attrib: self.forceStyleSheet = True if root.attrib['forceStyleSheet'] == "true" else False
        # The toolbar icon size the theme is drawn for (Preferences picks it with the theme)
        self.toolbarIconSize = None
        if 'toolbarIconSize' in root.attrib:
            try:
                self.toolbarIconSize = int(root.attrib['toolbarIconSize'])
            except ValueError:
                pass
        if 'version' in root.attrib:
            try:
                self.version = float(root.attrib['version'])
            except ValueError:
                pass

        return True

    def loadColorsXml(self, file):
        """
        Loads a colors.xml file
        """
        try:
            with open(file, encoding='utf-8') as f:
                text = f.read()
            if self.variables:
                text = themevars.substitute(text, self.variables)
            root = etree.fromstring(text.encode('utf-8'))
        except Exception:
            return

        if root.tag.lower() != 'colors': return False

        colorDict = {}
        for colorNode in root:
            if colorNode.tag.lower() != 'color': continue
            if not all(thing in colorNode.attrib for thing in ['id', 'value']): continue

            colorval = colorNode.attrib['value']
            if colorval.startswith('#'): colorval = colorval[1:]
            a = 255
            try:
                if len(colorval) == 3:
                    # RGB
                    r = int(colorval[0], 16)
                    g = int(colorval[1], 16)
                    b = int(colorval[2], 16)
                elif len(colorval) == 4:
                    # RGBA
                    r = int(colorval[0], 16)
                    g = int(colorval[1], 16)
                    b = int(colorval[2], 16)
                    a = int(colorval[3], 16)
                elif len(colorval) == 6:
                    # RRGGBB
                    r = int(colorval[0:2], 16)
                    g = int(colorval[2:4], 16)
                    b = int(colorval[4:6], 16)
                elif len(colorval) == 8:
                    # RRGGBBAA
                    r = int(colorval[0:2], 16)
                    g = int(colorval[2:4], 16)
                    b = int(colorval[4:6], 16)
                    a = int(colorval[6:8], 16)
            except ValueError:
                continue
            colorobj = QtGui.QColor(r, g, b, a)
            colorDict[colorNode.attrib['id']] = colorobj

        # Merge dictionaries
        self.colors.update(colorDict)

    def loadStyleSheet(self, file):
        """
        Loads a style.qss file
        """
        with open(file, encoding='utf-8') as inf:
            style = inf.read()

        if self.variables:
            style = themevars.substitute(style, self.variables)

        # Style sheets can point at their own folder ({theme}) and at the check marks and
        # arrows drawn in the theme's colours ({images}); a theme built on another adds its
        # own style sheet after the base's
        folder = os.path.dirname(os.path.abspath(file))
        images = themeImages(self.variables) if self.variables else None
        style = style.replace('{images}', (images or os.path.join(folder, 'images')).replace('\\', '/'))
        style = style.replace('{theme}', folder.replace('\\', '/'))
        self.styleSheet = (self.styleSheet + '\n' + style) if self.styleSheet else style

    @property
    def isClassic(self):
        """True for the Legacy theme and the classic themes built on it."""
        return themevars.CLASSIC_BASE in (self.base, os.path.basename(self.folder or ''))

    def color(self, name):
        """
        Returns a color
        """
        try:
            return self.colors[name]

        except KeyError:
            return None

    def GetIcon(self, name, big=False):
        """
        Returns an icon
        """

        cache = self.iconCacheLg if big else self.iconCacheSm

        if isinstance(cache.get(name), _LazySvgIcon):
            icon = svgIcon(cache[name].path, cache[name].big, cache[name].variables)
            if icon is not None:
                cache[name] = icon
            else:
                del cache[name]

        if name not in cache:
            ico_dir = os.path.join(globals.miyamoto_path, 'yaz0data', 'ico', 'lg' if big else 'sm')
            path = os.path.join(ico_dir, 'icon-' + name)
            cache[name] = QtGui.QIcon(path)

        return cache[name]

    def ui(self):
        """
        Returns the UI style
        """
        return self.uiStyle


def toQColor(*args):
    """
    Usage: toQColor(r, g, b[, a]) OR toQColor((r, g, b[, a]))
    """
    if len(args) == 1: args = args[0]
    r = args[0]
    g = args[1]
    b = args[2]
    a = args[3] if len(args) == 4 else 255
    return QtGui.QColor(r, g, b, a)


def _relative_luminance(color):
    """WCAG relative luminance of a QColor (0 = black, 1 = white)."""
    def linearize(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * linearize(color.red()) + 0.7152 * linearize(color.green()) + 0.0722 * linearize(color.blue())


def SetAppStyle(styleKey=''):
    """
    Set the application window color
    """
    # Set the style first so standardPalette() reflects the right style below.
    if not styleKey: styleKey = setting('uiStyle', "Fusion")
    style = QtWidgets.QStyleFactory.create(styleKey)
    globals.app.setStyle(style)

    # Build the palette.  For themes without a ui color use standardPalette() rather
    # than globals.app.palette(), which may still carry a dark tint from a previous theme.
    if globals.theme.color('ui') is not None and not globals.theme.forceStyleSheet:
        palette = QtGui.QPalette(globals.theme.color('ui'))
    else:
        palette = globals.app.style().standardPalette()

    # QPalette derived from a single dark color (or a system dark-mode palette)
    # produces a Mid role that is darker than the background, making
    # "color: palette(mid)" text invisible.  Fix: if Mid vs Window contrast is
    # insufficient, replace Mid with a readable muted color.
    L_bg = _relative_luminance(palette.color(QtGui.QPalette.Window))
    L_mid = _relative_luminance(palette.color(QtGui.QPalette.Mid))
    hi, lo = max(L_bg, L_mid), min(L_bg, L_mid)
    if (hi + 0.05) / (lo + 0.05) < 3.0:
        mid_fixed = QtGui.QColor(140, 140, 140) if L_bg < 0.5 else QtGui.QColor(100, 100, 100)
        for role in (QtGui.QPalette.Active, QtGui.QPalette.Inactive, QtGui.QPalette.Disabled):
            palette.setColor(role, QtGui.QPalette.Mid, mid_fixed)

    # Ensure button text is readable against the button background.
    L_btn = _relative_luminance(palette.color(QtGui.QPalette.Button))
    L_btn_txt = _relative_luminance(palette.color(QtGui.QPalette.ButtonText))
    hi_b, lo_b = max(L_btn, L_btn_txt), min(L_btn, L_btn_txt)
    if (hi_b + 0.05) / (lo_b + 0.05) < 4.5:
        btn_text_color = QtGui.QColor(255, 255, 255) if L_btn < 0.5 else QtGui.QColor(0, 0, 0)
        for role in (QtGui.QPalette.Active, QtGui.QPalette.Inactive, QtGui.QPalette.Disabled):
            palette.setColor(role, QtGui.QPalette.ButtonText, btn_text_color)

    # Themes can set any palette colour: palette_<role> (e.g. palette_highlight), and
    # palettedisabled_<role> for disabled widgets
    roles = {name.lower(): value for name, value in vars(QtGui.QPalette).items()
             if isinstance(value, QtGui.QPalette.ColorRole)}
    for key, color in globals.theme.colors.items():
        if key.startswith('palette_') and key[8:] in roles:
            for group in (QtGui.QPalette.Active, QtGui.QPalette.Inactive):
                palette.setColor(group, roles[key[8:]], color)
            if 'palettedisabled_' + key[8:] not in globals.theme.colors:
                palette.setColor(QtGui.QPalette.Disabled, roles[key[8:]], color)
        elif key.startswith('palettedisabled_') and key[16:] in roles:
            palette.setColor(QtGui.QPalette.Disabled, roles[key[16:]], color)

    globals.app.setPalette(palette)

    # Apply the theme's style sheet (an empty one clears the previous theme's)
    globals.app.setStyleSheet(globals.theme.styleSheet or '')

    # Manually set the background color
    if globals.theme.forceUiColor and not globals.theme.forceStyleSheet:
        color = globals.theme.color('ui').getRgb()
        bgColor = "#%02x%02x%02x" % tuple(map(lambda x: x // 2, color[:3]))
        globals.app.setStyleSheet("""
            QListView, QTreeWidget, QLineEdit, QDoubleSpinBox, QSpinBox, QTextEdit{
                background-color: %s;
            }""" % bgColor)


def createHorzLine():
    f = QtWidgets.QFrame()
    f.setFrameStyle(QtWidgets.QFrame.HLine | QtWidgets.QFrame.Sunken)
    return f


def createVertLine():
    f = QtWidgets.QFrame()
    f.setFrameStyle(QtWidgets.QFrame.VLine | QtWidgets.QFrame.Sunken)
    return f


def LoadNumberFont():
    """
    Creates a valid font we can use to display the item numbers
    """
    if globals.NumberFont is not None: return

    # this is a really crappy method, but I can't think of any other way
    # normal Qt defines Q_WS_WIN and Q_WS_MAC but we don't have that here
    s = QtCore.QSysInfo()
    if hasattr(s, 'WindowsVersion'):
        globals.NumberFont = QtGui.QFont('Tahoma',        round((7 / 24) * globals.TileWidth))
    elif hasattr(s, 'MacintoshVersion'):
        globals.NumberFont = QtGui.QFont('Lucida Grande', round((9 / 24) * globals.TileWidth))
    else:
        globals.NumberFont = QtGui.QFont('Sans',          round((8 / 24) * globals.TileWidth))


TOOLBAR_ICON_SIZES = (16, 20, 24, 32, 40)


def toolbarIconSize():
    """The size of the main toolbar's icons, in pixels (Preferences > Themes; until it's set, the theme's)."""
    default = getattr(globals.theme, 'toolbarIconSize', None) or 24
    try:
        size = int(setting('ToolbarIconSize', default))
    except (TypeError, ValueError):
        size = 24
    return size if size in TOOLBAR_ICON_SIZES else 24


def GetIcon(name, big=False):
    """
    Helper function to grab a specific icon
    """
    return globals.theme.GetIcon(name, big)
