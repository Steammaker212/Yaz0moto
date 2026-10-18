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
from .misc import setting

#################################


def themeDirectories():
    """Return theme roots in load-precedence order."""
    return (
        os.path.join(globals.user_data_path, 'themes'),
        os.path.join(globals.miyamoto_path, 'miyamotodata', 'themes'),
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
        Initializes the theme from the folder
        """
        folder = resolveThemeFolder(folder)

        fileList = os.listdir(folder)

        # Create a XML ElementTree
        maintree = etree.parse(os.path.join(folder, 'main.xml'))
        root = maintree.getroot()

        # Parse the attributes of the <theme> tag
        if not self.parseMainXMLHead(root):
            # The attributes are messed up
            return

        # Parse the other nodes
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

                # Load the icons
                for iconfilename in fileList:
                    iconname = iconfilename
                    if not iconname.startswith(foldername + '/'): continue
                    iconname = iconname[len(foldername) + 1:]
                    if len(iconname) <= len('icon-.png'): continue
                    if not iconname.startswith('icon-') or not iconname.endswith('.png'): continue
                    iconname = iconname[len('icon-'): -len('.png')]

                    with open(os.path.join(folder, iconfilename), "rb") as inf:
                        icodata = inf.read()
                    pix = QtGui.QPixmap()
                    if not pix.loadFromData(icodata): continue
                    ico = QtGui.QIcon(pix)

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
            tree = etree.parse(file)
        except Exception:
            return

        root = tree.getroot()
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
        with open(file) as inf:
            style = inf.read()

        self.styleSheet = style

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

        if name not in cache:
            ico_dir = os.path.join(globals.miyamoto_path, 'miyamotodata', 'ico', 'lg' if big else 'sm')
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

    globals.app.setPalette(palette)

    # Apply the style sheet, if exists
    if globals.theme.styleSheet:
        globals.app.setStyleSheet(globals.theme.styleSheet)

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


def GetIcon(name, big=False):
    """
    Helper function to grab a specific icon
    """
    return globals.theme.GetIcon(name, big)
