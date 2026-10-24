#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Yaz0moto Level Editor
# This file is part of Yaz0moto, a fork of Pyamoto.

# See LICENSE.txt for more information.

"""
The parts bar, after Super Mario Maker's: a row of the parts (tileset objects and actors)
you used last, under the main toolbar. Click a part to paint with it, or drag it onto the
level to place it there. The menu button at its left shows every part.

Parts are keys: ('obj', tileset slot, object number) or ('spr', actor type).
"""

from PyQt5 import QtCore, QtGui, QtWidgets
Qt = QtCore.Qt

from . import globals
from . import spriteicons
from .misc import setting, setSetting
from .ui import GetIcon

MIME = 'application/x-yaz0moto-part'
MAX_PARTS = 12
BAR_ICON = 40
DEFAULT_PARTS = ['obj:0:0', 'obj:0:1', 'obj:0:2', 'obj:0:3', 'obj:0:4', 'obj:0:5',
                 'spr:0', 'spr:19', 'spr:45', 'spr:25', 'spr:31']


################################################################
# Parts
################################################################

def encode(key):
    return ':'.join(str(part) for part in key)


def decode(text):
    parts = str(text).split(':')
    try:
        if parts[0] == 'obj' and len(parts) == 3:
            return ('obj', int(parts[1]), int(parts[2]))
        if parts[0] == 'spr' and len(parts) >= 2:
            value = ':'.join(parts[1:])
            return ('spr', int(value) if value.lstrip('-').isdigit() else value)
    except ValueError:
        pass
    return None


def objectModel(slot):
    """The palette's rendered previews for a tileset slot, or None."""
    mw = globals.mainWindow
    try:
        if slot == 0:
            return mw.objPicker.m0
        return mw.objTS123Tab.getModels()[slot]
    except (AttributeError, IndexError):
        return None


def objectCount(slot):
    model = objectModel(slot)
    return len(model.ritems) if model is not None else 0


def _fit(pixmap, size):
    """A pixmap scaled to fit a size x size square, centred on a transparent background."""
    if pixmap is None or pixmap.isNull():
        return None
    scaled = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    scaled.setDevicePixelRatio(1)
    out = QtGui.QPixmap(size, size)
    out.fill(Qt.transparent)
    painter = QtGui.QPainter(out)
    painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    return out


def partIcon(key, size):
    """The picture for a part, or None if it doesn't exist (e.g. a tileset that isn't loaded)."""
    if key[0] == 'obj':
        model = objectModel(key[1])
        if model is None or not 0 <= key[2] < len(model.ritems):
            return None
        return _fit(model.ritems[key[2]], size)
    return spriteicons.spriteIcon(key[1], size)


def partName(key):
    if key[0] == 'obj':
        name = 'Tileset %d, object %d' % (key[1] + 1, key[2])
        descriptions = getattr(globals, 'ObjDesc', None) or {}
        if key[1] == 0 and key[2] in descriptions:
            name += ': ' + str(descriptions[key[2]])
        return name
    return '%s (actor %s)' % (spriteicons.spriteName(key[1]), key[1])


def isArmed():
    """True while a part (object, actor or stamp) is picked, so clicking the level places it."""
    paint = globals.CurrentPaintType
    if paint in (0, 1, 2, 3, 10):
        return globals.CurrentObject not in (-1, None)
    if paint == 4:
        return globals.CurrentSprite not in (-1, None)
    if paint == 8:
        chooser = getattr(globals.mainWindow, 'clipChooser', None)
        return chooser is not None and chooser.current_clip() is not None
    return False


def disarm():
    """Un-picks the current part, so clicking the level selects and drags again."""
    mw = globals.mainWindow
    globals.CurrentObject = -1
    globals.CurrentSprite = -1
    for name, call in (('objPicker', lambda w: (w.clearSelection(), w.setCurrentIndex(QtCore.QModelIndex()))),
                       ('sprPicker', lambda w: (w.blockSignals(True), w.setCurrentItem(None), w.clearSelection(),
                                                w.blockSignals(False))),
                       ('sprIconGrid', lambda w: w.setSelected(None)),
                       ('partsBar', lambda w: w.markCurrent(None))):
        widget = getattr(mw, name, None)
        if widget is not None:
            try:
                call(widget)
            except RuntimeError:
                pass
    mw.statusBar().showMessage('Nothing picked: click things in the level to select and drag them.', 4000)


def selectPart(key):
    """Makes a part the one that clicking (or dropping) in the level places."""
    mw = globals.mainWindow
    if key[0] == 'obj':
        globals.CurrentPaintType = key[1]
        globals.CurrentObject = key[2]
    else:
        globals.CurrentPaintType = 4
        mw.SpriteChoiceChanged(key[1])
    mw.statusBar().showMessage('%s - click in the level to place it (click it again, or press Esc, to put it down).'
                               % partName(key), 6000)


def mimeFor(key):
    data = QtCore.QMimeData()
    data.setData(MIME, encode(key).encode())
    return data


def keyFromMime(mime):
    if mime is not None and mime.hasFormat(MIME):
        return decode(bytes(mime.data(MIME)).decode())
    return None


################################################################
# A grid of part tiles (used by the parts menu and the Add Actors palette)
################################################################

class PartGrid(QtWidgets.QWidget):
    """
    Wrapping rows of tiles, in titled sections. Icons are drawn a few at a time
    between paints, so long lists stay responsive. Click a tile to pick it (Alt-click
    for the alternative action), or drag it onto the level.
    """
    picked = QtCore.pyqtSignal(object)
    altPicked = QtCore.pyqtSignal(object)
    unpicked = QtCore.pyqtSignal(object)  # the selected tile was clicked again
    dragStarted = QtCore.pyqtSignal()

    def __init__(self, iconFn, tooltipFn, iconSize=48):
        super().__init__()
        self.iconFn, self.tooltipFn = iconFn, tooltipFn
        self.iconSize = iconSize
        self.cell = iconSize + 14
        self.sections = []
        self.entries = []      # ('header', rect, title) or ('item', rect, key)
        self.icons = {}
        self.pending = []
        self.renderScheduled = False
        self.hover = self.selected = None
        self.pressKey = self.pressPos = None
        self.setMouseTracking(True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)

    def setSections(self, sections):
        """sections: [(title or None, [keys])]"""
        self.sections = [(title, list(keys)) for title, keys in sections if keys]
        self.relayout()
        self.update()

    def setSelected(self, key):
        self.selected = key
        self.update()

    def relayout(self):
        width = max(self.cell, self.width())
        perRow = max(1, (width - 8) // self.cell)
        header = self.fontMetrics().height() + 10
        self.entries = []
        y = 4
        for title, keys in self.sections:
            if title:
                self.entries.append(('header', QtCore.QRect(6, y, width - 12, header), title))
                y += header
            for i, key in enumerate(keys):
                row, col = divmod(i, perRow)
                rect = QtCore.QRect(4 + col * self.cell, y + row * self.cell, self.cell - 4, self.cell - 4)
                self.entries.append(('item', rect, key))
            y += ((len(keys) + perRow - 1) // perRow) * self.cell + 6
        self.setMinimumHeight(y + 4)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()

    def keyAt(self, pos):
        for kind, rect, value in self.entries:
            if kind == 'item' and rect.contains(pos):
                return value
        return None

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pal = self.palette()
        tile = pal.color(QtGui.QPalette.Button)
        accent = pal.color(QtGui.QPalette.Highlight)
        exposed = event.rect()

        for kind, rect, value in self.entries:
            if not rect.intersects(exposed):
                continue
            if kind == 'header':
                font = painter.font()
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(pal.color(QtGui.QPalette.Mid))
                painter.drawText(rect, Qt.AlignLeft | Qt.AlignBottom, value)
                font.setBold(False)
                painter.setFont(font)
                continue

            r = QtCore.QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
            fill = QtGui.QColor(tile)
            if value == self.hover:
                fill = QtGui.QColor(accent)
                fill.setAlpha(60)
            painter.setPen(QtGui.QPen(accent, 2) if value == self.selected else Qt.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(r, 10, 10)

            icon = self.icons.get(value)
            if icon is None:
                if value not in self.pending:
                    self.pending.append(value)
                    self.scheduleRender()
                continue
            painter.drawPixmap(rect.x() + (rect.width() - icon.width()) // 2,
                               rect.y() + (rect.height() - icon.height()) // 2, icon)

    def scheduleRender(self):
        if not self.renderScheduled:
            self.renderScheduled = True
            QtCore.QTimer.singleShot(0, self.renderPending)

    def renderPending(self):
        """Draws some of the queued icons (outside paint events), then asks for a repaint."""
        self.renderScheduled = False
        for key in self.pending[:16]:
            try:
                icon = self.iconFn(key, self.iconSize)
            except Exception:
                icon = None
            self.icons[key] = icon if icon is not None else QtGui.QPixmap()
        del self.pending[:16]
        self.update()
        if self.pending:
            self.scheduleRender()

    def mouseMoveEvent(self, event):
        key = self.keyAt(event.pos())
        if key != self.hover:
            self.hover = key
            self.update()
        if (self.pressKey is not None and event.buttons() & Qt.LeftButton
                and (event.pos() - self.pressPos).manhattanLength() >= QtWidgets.QApplication.startDragDistance()):
            key, self.pressKey = self.pressKey, None
            self.startDrag(key)

    def startDrag(self, key):
        drag = QtGui.QDrag(self)
        drag.setMimeData(mimeFor(key))
        icon = self.icons.get(key)
        if icon is not None and not icon.isNull():
            drag.setPixmap(icon)
            drag.setHotSpot(QtCore.QPoint(icon.width() // 2, icon.height() // 2))
        self.dragStarted.emit()
        drag.exec_(Qt.CopyAction)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.pressKey = self.keyAt(event.pos())
            self.pressPos = event.pos()

    def mouseReleaseEvent(self, event):
        key = self.keyAt(event.pos())
        if event.button() == Qt.LeftButton and key is not None and key == self.pressKey:
            if event.modifiers() & Qt.AltModifier:
                self.selected = key
                self.altPicked.emit(key)
            elif key == self.selected:
                self.selected = None
                self.unpicked.emit(key)
            else:
                self.selected = key
                self.picked.emit(key)
            self.update()
        self.pressKey = None

    def leaveEvent(self, event):
        self.hover = None
        self.update()

    def event(self, event):
        if event.type() == QtCore.QEvent.ToolTip:
            key = self.keyAt(event.pos())
            if key is not None:
                QtWidgets.QToolTip.showText(event.globalPos(), self.tooltipFn(key), self)
            else:
                QtWidgets.QToolTip.hideText()
            return True
        return super().event(event)


def scrolling(widget):
    area = QtWidgets.QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QtWidgets.QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area


################################################################
# The bar
################################################################

class PartButton(QtWidgets.QToolButton):
    """A part on the bar: click to pick it (again to put it down), drag it onto the level, right-click to remove it."""

    def __init__(self, bar, key, icon):
        super().__init__()
        self.bar, self.key = bar, key
        self.setCheckable(True)
        self.setIcon(QtGui.QIcon(icon))
        self.setIconSize(QtCore.QSize(BAR_ICON, BAR_ICON))
        self.setToolTip(partName(key) + '<br><i>Click to pick it (again to put it down), or drag it onto the level.</i>')
        self.pressPos = None
        self.clicked.connect(lambda: bar.pick(key))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.pressPos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self.pressPos is not None and event.buttons() & Qt.LeftButton
                and (event.pos() - self.pressPos).manhattanLength() >= QtWidgets.QApplication.startDragDistance()):
            self.pressPos = None
            self.setDown(False)
            drag = QtGui.QDrag(self)
            drag.setMimeData(mimeFor(self.key))
            pix = self.icon().pixmap(BAR_ICON, BAR_ICON)
            drag.setPixmap(pix)
            drag.setHotSpot(QtCore.QPoint(pix.width() // 2, pix.height() // 2))
            drag.exec_(Qt.CopyAction)
            return
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event):
        menu = QtWidgets.QMenu(self)
        menu.addAction('Remove from the parts bar', lambda: self.bar.remove(self.key))
        menu.exec_(event.globalPos())


class PartsBar(QtWidgets.QToolBar):
    """The row of recent parts, with the menu of all parts at its left."""

    def __init__(self, parent=None):
        super().__init__('Parts Bar', parent)
        self.setObjectName('PartsBar')
        self.setIconSize(QtCore.QSize(BAR_ICON, BAR_ICON))
        # It stays on its own row under the main toolbar (the window puts it back there)
        self.setMovable(False)
        self.setAllowedAreas(Qt.TopToolBarArea)

        self.menuButton = QtWidgets.QToolButton()
        self.menuButton.setObjectName('PartsMenuButton')
        self.menuButton.setIcon(GetIcon('parts'))
        self.menuButton.setIconSize(QtCore.QSize(BAR_ICON - 8, BAR_ICON - 8))
        self.menuButton.setToolTip('All parts')
        self.menuButton.clicked.connect(self.openMenu)
        self.addWidget(self.menuButton)
        self.addSeparator()

        saved = setting('PartsBar', None)
        keys = [decode(k) for k in (saved if isinstance(saved, list) else DEFAULT_PARTS)]
        self.keys = [k for k in keys if k is not None][:MAX_PARTS]
        self.current = None
        self.buttons = []
        self.menu = None

    def save(self):
        setSetting('PartsBar', [encode(k) for k in self.keys])

    def refresh(self):
        """Rebuilds the buttons (after a level or its tilesets load)."""
        for button in self.buttons:
            self.removeAction(button.action)
            button.deleteLater()
        self.buttons = []
        for key in self.keys:
            icon = partIcon(key, BAR_ICON)
            if icon is None:
                continue  # e.g. an object of a tileset this level doesn't use
            button = PartButton(self, key, icon)
            button.action = self.addWidget(button)
            button.setChecked(key == self.current)
            self.buttons.append(button)

    def pick(self, key):
        # Clicking the picked part again puts it down
        if key == self.current and isArmed():
            disarm()
            return
        selectPart(key)
        self.markCurrent(key)

    def markCurrent(self, key):
        self.current = key
        for button in self.buttons:
            button.setChecked(button.key == key)

    def addRecent(self, key):
        """Puts a part at the front of the bar (Mario Maker style)."""
        if key is None:
            return
        if key in self.keys:
            self.keys.remove(key)
        self.keys.insert(0, key)
        del self.keys[MAX_PARTS:]
        self.save()
        self.current = key
        self.refresh()

    def remove(self, key):
        if key in self.keys:
            self.keys.remove(key)
            self.save()
            self.refresh()

    def openMenu(self):
        self.menu = PartsMenu(self)
        pos = self.menuButton.mapToGlobal(QtCore.QPoint(0, self.menuButton.height() + 4))
        self.menu.move(pos)
        self.menu.show()


class PartsMenu(QtWidgets.QFrame):
    """Every part: a tab per loaded tileset, and the actors with a search box."""

    def __init__(self, bar):
        super().__init__(None, Qt.Popup)
        self.bar = bar
        self.setObjectName('PartsMenu')
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.resize(660, 460)

        tabs = QtWidgets.QTabWidget()
        self.grids = []
        for slot in range(4):
            count = objectCount(slot)
            if not count:
                continue
            grid = self.makeGrid(56)
            grid.setSections([(None, [('obj', slot, i) for i in range(count)])])
            tabs.addTab(scrolling(grid), GetIcon('objects'), 'Tileset %d' % (slot + 1))

        actors = QtWidgets.QWidget()
        al = QtWidgets.QVBoxLayout(actors)
        al.setContentsMargins(4, 6, 4, 4)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText('Search actors...')
        self.search.textChanged.connect(self.filterActors)
        al.addWidget(self.search)
        self.actorGrid = self.makeGrid(56)
        al.addWidget(scrolling(self.actorGrid), 1)
        tabs.addTab(actors, GetIcon('sprites'), 'Actors')
        self.filterActors('')

        hint = QtWidgets.QLabel('Click a part to pick it, then click in the level to place it. You can also drag it onto the level.')
        hint.setStyleSheet('color: palette(mid);')

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.addWidget(tabs, 1)
        layout.addWidget(hint)

    def mousePressEvent(self, event):
        # A click on the menu button while the menu is open only closes it: without this,
        # Qt passes the click on to the button, which opens the menu again
        button = self.bar.menuButton
        if (not self.rect().contains(event.pos())
                and button.rect().contains(button.mapFromGlobal(event.globalPos()))):
            self.setAttribute(Qt.WA_NoMouseReplay)
        super().mousePressEvent(event)

    def makeGrid(self, size):
        grid = PartGrid(partIcon, partName, size)
        grid.picked.connect(self.picked)
        grid.dragStarted.connect(self.hide)  # get out of the way of the level
        self.grids.append(grid)
        return grid

    def filterActors(self, text):
        terms = text.lower().split()
        sections = []
        for viewname, view, _ in getattr(globals, 'SpriteCategories', None) or ():
            if viewname in ('All', 'Useless / Crashing Sprites'):
                continue
            for catname, ids in view:
                keys = [('spr', i) for i in ids if isinstance(i, int) and 0 <= i < globals.NumSprites
                        and globals.Sprites[i] is not None
                        and all(t in globals.Sprites[i].name.lower() or t == str(i) for t in terms)]
                sections.append(('%s - %s' % (viewname, catname), keys))
        self.actorGrid.setSections(sections)

    def picked(self, key):
        self.bar.addRecent(key)
        selectPart(key)
        self.close()


################################################################
# Dropping parts on the level
################################################################

def placeAt(view, key, pos):
    """
    Places a part at a point of the level view, exactly as clicking there with it picked
    would (same sizing, defaults and undo step).
    """
    selectPart(key)
    view.placeAt(pos)
