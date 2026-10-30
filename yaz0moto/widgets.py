#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Pyamoto Level Editor
# Copyright (C) 2009-2026 Pyamoto contributors
# This file is part of Pyamoto.

# See LICENSE.txt for more information.


################################################################
################################################################

############ Imports ############

import json
from math import sqrt
import os
import re
import struct
import sys

from PyQt5 import QtCore, QtGui, QtWidgets
Qt = QtCore.Qt

from . import globals
from . import movementpreview
from . import partsbar
from . import undomanager

from .items import ObjectItem, ZoneItem, LocationItem, SpriteItem
from .items import EntranceItem, PathItem, NabbitPathItem
from .items import PathEditorLineItem, NabbitPathEditorLineItem
from .items import CommentItem

# from loading import LoadSpriteData, LoadSpriteListData
# from loading import LoadSpriteCategories, LoadEntranceNames

from .misc import clipStr, setting, setSetting, drawForegroundGrid
from .misc import extract_field_value, extract_mask_value, insert_mask_value, mask_shift, mask_max_value
from .misc import LargeSpinBox
from .strybble import strybble_encode, strybble_decode, StrybbleEncodeError
from .clips import Clip, load_clips, save_clips

from .tileset import TilesetTile, ObjectDef, objFitsInTileset
from .tileset import addObjToTilesetImpl, addObjToTileset, exportObject
from .tileset import HandleTilesetEdited, DeleteObject, RenderObject
from .tileset import RenderObjectAll, ProcessOverrides, SimpleTilesetNames, HasTileset

from .ui import createHorzLine, createVertLine, GetIcon
from .verifications import SetDirty

#################################


class UndoHistoryWidget(QtWidgets.QListWidget):
    """
    Lists the undo history, oldest first, with undone steps greyed out.
    Clicking a step undoes or redoes everything up to it.
    """

    def __init__(self):
        super().__init__()
        self.setToolTip('Click a step to go back (or forward) to it')
        globals.UndoManager.stackChanged.connect(self.refresh)
        self.itemClicked.connect(self.jump)
        self.refresh()

    def refresh(self):
        um = globals.UndoManager
        self.blockSignals(True)
        self.clear()

        self.addItem('Earliest kept state' if len(um.undo_stack) + len(um.redo_stack) >= um.max_history else 'Start')
        for cmd in um.undo_stack:
            self.addItem(cmd.description or 'Edit')

        undone = self.palette().color(QtGui.QPalette.Disabled, QtGui.QPalette.Text)
        for cmd in reversed(um.redo_stack):
            item = QtWidgets.QListWidgetItem(cmd.description or 'Edit')
            item.setForeground(undone)
            self.addItem(item)

        self.setCurrentRow(len(um.undo_stack))
        self.blockSignals(False)

    def jump(self, item):
        globals.UndoManager.jump_to(self.row(item))


class LevelOverviewWidget(QtWidgets.QWidget):
    """
    Widget that shows an overview of the level and can be clicked to move the view
    """
    moveIt = QtCore.pyqtSignal(int, int)

    def __init__(self):
        """
        Constructor for the level overview widget
        """
        super().__init__()
        self.setSizePolicy(
            QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.MinimumExpanding))

        self.bgbrush = QtGui.QBrush(globals.theme.color('bg'))
        self.objbrush = QtGui.QBrush(globals.theme.color('overview_object'))
        self.viewbrush = QtGui.QBrush(globals.theme.color('overview_zone_fill'))
        self.view = QtCore.QRectF(0, 0, 0, 0)
        self.spritebrush = QtGui.QBrush(globals.theme.color('overview_sprite'))
        self.entrancebrush = QtGui.QBrush(globals.theme.color('overview_entrance'))
        self.locationbrush = QtGui.QBrush(globals.theme.color('overview_location_fill'))

        self.Reset()

        self.Xposlocator = 0
        self.Yposlocator = 0
        self.Hlocator = 50
        self.Wlocator = 80
        self.mainWindowScale = 1

    def Reset(self):
        """
        Resets the max and scale variables
        """
        self.CalcSize()
        self.Rescale()

    def mouseMoveEvent(self, event):
        """
        Handles mouse movement over the widget
        """
        QtWidgets.QWidget.mouseMoveEvent(self, event)

        if event.buttons() == Qt.LeftButton:
            self.moveIt.emit(int(event.pos().x() * self.posmult), int(event.pos().y() * self.posmult))

    def mousePressEvent(self, event):
        """
        Handles mouse pressing events over the widget
        """
        QtWidgets.QWidget.mousePressEvent(self, event)

        if event.button() == Qt.LeftButton:
            ex, ey = event.pos().x(), event.pos().y()
            sx = int(ex * self.posmult)
            sy = int(ey * self.posmult)
            self.moveIt.emit(sx, sy)

    def paintEvent(self, event):
        """
        Paints the level overview widget
        """
        if not hasattr(globals.Area, 'layers'):
            # fixes race condition where this widget is painted after
            # the level is created, but before it's loaded
            return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        self.Reset()
        painter.scale(self.scale, self.scale)
        painter.fillRect(0, 0, 1024, 512, self.bgbrush)

        dr = painter.drawRect
        fr = painter.fillRect
        transform = QtGui.QTransform() / globals.TileWidth

        b = self.viewbrush
        painter.setPen(QtGui.QPen(globals.theme.color('overview_zone_lines'), 1))

        for zone in globals.Area.zones:
            r = transform.mapRect(zone.sceneBoundingRect())
            fr(r, b)
            dr(r)

        b = self.objbrush

        for layer in globals.Area.layers:
            for obj in layer:
                fr(obj.LevelRect, b)

        b = self.spritebrush

        for sprite in globals.Area.sprites:
            fr(sprite.LevelRect, b)

        b = self.entrancebrush

        for ent in globals.Area.entrances:
            fr(ent.LevelRect, b)

        b = self.locationbrush
        painter.setPen(QtGui.QPen(globals.theme.color('overview_location_lines'), 1))

        for location in globals.Area.locations:
            r = transform.mapRect(location.sceneBoundingRect())
            fr(r, b)
            dr(r)

        painter.setPen(QtGui.QPen(globals.theme.color('overview_viewbox'), 1))
        painter.drawRect(QtCore.QRectF(
            self.Xposlocator / globals.TileWidth / self.mainWindowScale,
            self.Yposlocator / globals.TileWidth / self.mainWindowScale,
            self.Wlocator / globals.TileWidth / self.mainWindowScale,
            self.Hlocator / globals.TileWidth / self.mainWindowScale
        ))

    def CalcSize(self):
        """
        Calculates all the required sizes for this scale
        """
        if not globals.Area:
            self.maxX = 0
            self.maxY = 0
            return

        transform = QtGui.QTransform() / globals.TileWidth
        rect = QtCore.QRectF()

        for zone in globals.Area.zones:
            rect |= transform.mapRect(zone.sceneBoundingRect())

        for layer in globals.Area.layers:
            for obj in layer:
                rect |= obj.LevelRect

        for sprite in globals.Area.sprites:
            rect |= sprite.LevelRect

        for ent in globals.Area.entrances:
            rect |= ent.LevelRect

        for location in globals.Area.locations:
            rect |= transform.mapRect(location.sceneBoundingRect())

        self.maxX = rect.right()
        self.maxY = rect.bottom()

    def Rescale(self):
        """
        Calculates self.scale and self.posmult
        """
        self.scale = max(0.002, min(self.width() / (self.maxX + 45), self.height() / (self.maxY + 25)))
        self.posmult = globals.TileWidth / self.scale

class ObjectPickerWidget(QtWidgets.QListView):
    """
    Widget that shows a list of available objects
    """

    def __init__(self):
        """
        Initializes the widget
        """

        super().__init__()
        self.setFlow(QtWidgets.QListView.LeftToRight)
        self.setLayoutMode(QtWidgets.QListView.SinglePass)
        self.setMovement(QtWidgets.QListView.Static)
        self.setResizeMode(QtWidgets.QListView.Adjust)
        self.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.setWrapping(True)

        self.objTS123Tab = globals.mainWindow.objTS123Tab

        self.m0 = self.ObjectListModel()
        self.mall = self.ObjectListModel()
        self.m123 = self.objTS123Tab.getModels()
        self.setModel(self.m0)

        self.setItemDelegate(self.ObjectItemDelegate())

        self.clicked.connect(self.HandleObjReplace)
        self.clicked.connect(self.PutDownIfClickedAgain)
        self.clickedPicked = False

    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        # Remember whether this click is on the object that is already picked
        self.clickedPicked = (event.button() == Qt.LeftButton and index.isValid()
                              and index == self.currentIndex() and partsbar.isArmed())
        super().mousePressEvent(event)

    def PutDownIfClickedAgain(self, index):
        """Clicking the picked object again puts it down."""
        if self.clickedPicked:
            self.clickedPicked = False
            partsbar.disarm()

    def contextMenuEvent(self, event):
        """
        Creates and shows the right-click menu
        """
        if globals.CurrentPaintType in [0, 10]:
            return QtWidgets.QListView.contextMenuEvent(self, event)

        self.menu = QtWidgets.QMenu(self)

        export = QtWidgets.QAction('Export', self)
        export.triggered.connect(self.HandleObjExport)

        replace = QtWidgets.QAction('Replace', self)
        replace.triggered.connect(self.HandleObjImportReplace)

        delete = QtWidgets.QAction('Delete', self)
        delete.triggered.connect(self.HandleObjDelete)

        delIns = QtWidgets.QAction('Delete instances', self)
        delIns.triggered.connect(self.HandleObjDeleteInstances)

        self.menu.addAction(export)
        self.menu.addAction(replace)
        self.menu.addAction(delete)
        self.menu.addAction(delIns)

        if globals.mainWindow.objAllTab.currentIndex() == 1:
            self.menu.addSeparator()
            deleteUnused = QtWidgets.QAction('Delete Unused', self)
            deleteUnused.triggered.connect(self.HandleDeleteUnused)
            self.menu.addAction(deleteUnused)

        self.menu.popup(QtGui.QCursor.pos())

    def LoadFromTilesets(self):
        """Renders all the object previews"""
        new_m0 = self.ObjectListModel()
        new_m0.LoadFromTileset(0)
        self.m0 = new_m0
        self.objTS123Tab.LoadFromTilesets()

        # Model refreshes must not change which palette the visible tab shows.
        # In particular, Local refreshes used to display m0 until another tab
        # switch corrected the model.
        if globals.mainWindow.objAllTab.currentIndex() == 0:
            self.setModel(self.m0)
        else:
            self.setModel(self.objTS123Tab.getActiveModel())
        self.viewport().update()

        # The parts bar shows these previews too
        bar = getattr(globals.mainWindow, 'partsBar', None)
        if bar is not None:
            bar.refresh()

    def ShowTileset(self, id):
        """
        Shows a specific tileset in the picker
        """
        sel = self.currentIndex().row()
        if id == 0: self.setModel(self.m0)
        elif id == 1: self.setModel(self.mall)
        else: self.setModel(self.objTS123Tab.getActiveModel())

        globals.CurrentObject = -1
        self.clearSelection()

    def currentChanged(self, current, previous):
        """
        Throws a signal when the selected object changed
        """
        self.ObjChanged.emit(current.row())

    def HandleObjReplace(self, index):
        """
        Throws a signal when the selected object is used as a replacement
        """
        if QtWidgets.QApplication.keyboardModifiers() == Qt.AltModifier:
            self.ObjReplace.emit(index.row())

    def HandleObjExport(self, index):
        """
        Exports an object from the tileset
        """
        file = QtWidgets.QFileDialog.getSaveFileName(None, "Save Objects", "", "Object files (*.json)")[0]
        if not file:
            return

        name = os.path.splitext(file)[0]
        baseName = os.path.basename(name)

        idx = globals.CurrentPaintType
        objNum = globals.CurrentObject

        exportObject(name, baseName, idx, objNum)

    def HandleObjImportReplace(self, index):
        """
        Imports a replacement for the selected object
        """
        idx = globals.CurrentPaintType
        objNum = globals.CurrentObject

        if objNum == -1: return

        # Get the json file
        file = QtWidgets.QFileDialog.getOpenFileName(self, "Open Object", '',
                    "Object files (*.json)")[0]

        if not file: return

        with open(file) as inf:
            jsonData = json.load(inf)

        dir = os.path.dirname(file)

        # Read the other files
        with open(dir + "/" + jsonData["meta"], "rb") as inf:
            indexfile = inf.read()

        with open(dir + "/" + jsonData["objlyt"], "rb") as inf:
            deffile = inf.read()

        with open(dir + "/" + jsonData["colls"], "rb") as inf:
            colls = inf.read()

        # Get the object's definition
        indexstruct = struct.Struct('>HBBH')

        data = indexstruct.unpack_from(indexfile, 0)
        obj = ObjectDef()
        obj.width = data[1]
        obj.height = data[2]

        if "randLen" in jsonData:
            obj.randByte = data[3]

        else:
            obj.randByte = 0

        obj.load(deffile, 0)

        # Get the image and normal map
        img = QtGui.QPixmap(dir + "/" + jsonData["img"])
        nml = QtGui.QPixmap(dir + "/" + jsonData["nml"])

        # Temporarily remove the selected object
        oObj = globals.ObjectDefinitions[idx].pop(objNum)
        globals.ObjectDefinitions[idx].append(None)

        # Check if the replacement fits
        fits = objFitsInTileset(obj, idx)

        # Restore the selected object
        del globals.ObjectDefinitions[idx][-1]
        globals.ObjectDefinitions[idx][objNum:objNum] = [oObj]

        # Throw warning and return if the replacement doesn't fit
        if not fits:
            QtWidgets.QMessageBox.critical(self, 'Cannot Delete', 'Replacement doesn\'t fit ' \
                                                                  'in the tileset')
            return

        # Build undo command with old + new definition
        old_obj_def = globals.ObjectDefinitions[idx][objNum]

        # Delete the selected object (using soft deletion)
        DeleteObject(idx, objNum, True)

        # Add the replacement in place of the previously deleted object
        new_obj = addObjToTilesetImpl(obj, colls, img, nml, idx, fits)
        globals.ObjectDefinitions[idx][objNum] = new_obj

        globals.UndoManager.push(
            undomanager.ReplaceTilesetObjectCommand(idx, objNum, old_obj_def, new_obj))

        # Update all instances of the replaced object in the scene
        for obj in globals.mainWindow.scene.items():
            if isinstance(obj, ObjectItem) and obj.tileset == idx and obj.type == objNum:
                obj.update()

        # Set related flags
        HandleTilesetEdited()
        SetDirty()

        # Clear selection in the palette to avoid a bug
        globals.CurrentObject = -1
        self.clearSelection()

    def HandleObjDelete(self, index):
        """
        Deletes an object from the tileset
        """
        idx = globals.CurrentPaintType
        objNum = globals.CurrentObject

        if objNum == -1: return

        # ── Collect info (no mutation) ────────────────────────────────────

        ## Instances in scene
        matchingObjs = []
        for layer in globals.Area.layers:
            for obj in layer:
                if obj.tileset == idx and obj.type == objNum:
                    matchingObjs.append(obj)

        ## Clipboard
        inClipboard = False
        cb = globals.mainWindow.clipboard
        if cb is not None and cb.startswith('MiyamotoClip|') and cb.endswith('|%'):
            try:
                layers, sprites, entrances, locations, paths, nabbitPaths, comments = \
                    globals.mainWindow.getEncodedObjects(cb, False)
                for layer in layers:
                    for obj in layer:
                        if obj.tileset == idx and obj.type == objNum:
                            inClipboard = True
                            break
                    if inClipboard:
                        break
            except Exception:
                pass

        ## Saved clips
        matchingClips = []
        for clip in globals.mainWindow.clipChooser._clips:
            try:
                layers, sprites, entrances, locations, paths, nabbitPaths, comments = \
                    globals.mainWindow.getEncodedObjects(clip.miyamoto_clip, False)
            except Exception:
                continue
            for layer in layers:
                found = False
                for obj in layer:
                    if obj.tileset == idx and obj.type == objNum:
                        matchingClips.append(clip.name)
                        found = True
                        break
                if found:
                    break

        # ── Prompt user (no mutation) ──────────────────────────────────────

        ## Instances warning
        if matchingObjs:
            where = [('(%d, %d)' % (obj.objx, obj.objy)) for obj in matchingObjs]
            dlgTxt = "This object has instances at the following coordinates:\n"
            dlgTxt += ', '.join(where)
            dlgTxt += '\n\nDo you want to delete all instances and proceed?'

            result = QtWidgets.QMessageBox.warning(self, 'Delete Object', dlgTxt,
                                                   QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)
            if result != QtWidgets.QMessageBox.Yes:
                return

        ## Clipboard warning
        if inClipboard:
            dlgTxt = "This object is in the clipboard.\n\nDo you want to empty the clipboard and proceed?"
            result = QtWidgets.QMessageBox.warning(self, 'Delete Object', dlgTxt,
                                                   QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)
            if result != QtWidgets.QMessageBox.Yes:
                return

        ## Saved clips warning
        if matchingClips:
            dlgTxt = "This object is referenced by the following saved clips:\n"
            dlgTxt += ', '.join(matchingClips)
            dlgTxt += '\n\nDeleting it may break these clips. Do you want to proceed?'

            result = QtWidgets.QMessageBox.warning(self, 'Delete Object', dlgTxt,
                                                   QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)
            if result != QtWidgets.QMessageBox.Yes:
                return

        # ── Execute with undo support ──────────────────────────────────────

        globals.UndoManager.begin_compound("Delete Object from Tileset")

        if matchingObjs:
            obj_info = []
            for obj in matchingObjs:
                l_idx = -1
                for i, layer in enumerate(globals.Area.layers):
                    if obj in layer:
                        l_idx = i
                        break
                if l_idx != -1:
                    obj_info.append((obj, l_idx, globals.Area.layers[l_idx].index(obj), obj.zValue()))
            globals.UndoManager.push(undomanager.DeleteObjectsCommand(obj_info))

        if inClipboard:
            globals.mainWindow.clipboard = None
            globals.mainWindow.actions['paste'].setEnabled(False)

        globals.UndoManager.push(undomanager.DeleteTilesetObjectCommand(idx, objNum))
        globals.UndoManager.end_compound()

        # ── Post-cleanup ───────────────────────────────────────────────────
        HandleTilesetEdited()

        if not (globals.Area.tileset1 or globals.Area.tileset2 or globals.Area.tileset3):
            globals.CurrentObject = -1

        globals.mainWindow.scene.update()
        SetDirty()

    def HandleObjDeleteInstances(self, index):
        """
        Deletes all instances of an object from the level scene
        """
        idx = globals.CurrentPaintType
        objNum = globals.CurrentObject

        if objNum == -1: return

        # Check if the object is in the scene
        matchingObjs = []
        for i, layer in enumerate(globals.Area.layers):
            for j, obj in enumerate(layer):
                if obj.tileset == idx and obj.type == objNum:
                    matchingObjs.append(obj)

        if not matchingObjs:
            return

        dlgTxt = "Are you sure you want to remove all instances of this object from the scene?"

        result = QtWidgets.QMessageBox.warning(self, 'Confirm', dlgTxt,
                                               QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)

        if result != QtWidgets.QMessageBox.Yes:
            return

        obj_info = []
        for obj in matchingObjs:
            l_idx = -1
            for i, layer in enumerate(globals.Area.layers):
                if obj in layer:
                    l_idx = i
                    break
            if l_idx != -1:
                obj_info.append((obj, l_idx, globals.Area.layers[l_idx].index(obj), obj.zValue()))

        globals.UndoManager.push(undomanager.DeleteObjectsCommand(obj_info))

        globals.mainWindow.scene.update()
        SetDirty()
        globals.mainWindow.SelectionUpdateFlag = False
        globals.mainWindow.ChangeSelectionHandler()

    def HandleDeleteUnused(self):
        """Delete Local objects unused by the level, clipboard, or saved stamps."""
        used = {
            (obj.tileset, obj.type)
            for layer in globals.Area.layers
            for obj in layer
            if obj.tileset in (1, 2, 3)
        }

        # Clipboard and saved stamps must keep their object definitions. The
        # tileset deletion path reindexes references, but cannot preserve a
        # reference to the definition being deleted.
        encoded_sources = [
            clip.miyamoto_clip for clip in globals.mainWindow.clipChooser._clips
        ]
        clipboard = globals.mainWindow.clipboard
        if clipboard is not None:
            encoded_sources.append(clipboard)

        for encoded in encoded_sources:
            if not isinstance(encoded, str) or not (
                    encoded.startswith('MiyamotoClip|') and encoded.endswith('|%')):
                continue
            try:
                layers, _, _, _, _, _, _ = globals.mainWindow.getEncodedObjects(
                    encoded, False)
            except Exception:
                continue
            used.update(
                (obj.tileset, obj.type)
                for layer in layers
                for obj in layer
                if obj.tileset in (1, 2, 3)
            )

        unused = []
        for tileset in (1, 2, 3):
            definitions = globals.ObjectDefinitions[tileset]
            if definitions is None:
                continue
            unused.extend(
                (tileset, obj_num)
                for obj_num, definition in enumerate(definitions)
                if definition is not None and (tileset, obj_num) not in used
            )

        if not unused:
            QtWidgets.QMessageBox.information(
                self, 'Delete Unused', 'No unused Local objects were found.')
            return

        count = len(unused)
        message = (
            f'Delete {count} unused Local object{"s" if count != 1 else ""}?\n\n'
            'Objects placed in the level, copied to the clipboard, or used by '
            'saved stamps will be kept. This action can be undone.'
        )
        result = QtWidgets.QMessageBox.question(
            self, 'Delete Unused', message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if result != QtWidgets.QMessageBox.Yes:
            return

        globals.UndoManager.begin_compound('Delete Unused Local Objects')
        try:
            for tileset, obj_num in sorted(unused, reverse=True):
                globals.UndoManager.push(
                    undomanager.DeleteTilesetObjectCommand(tileset, obj_num))
        finally:
            globals.UndoManager.end_compound()

        HandleTilesetEdited()
        globals.mainWindow.scene.update()

    ObjChanged = QtCore.pyqtSignal(int)
    ObjReplace = QtCore.pyqtSignal(int)

    class ObjectItemDelegate(QtWidgets.QAbstractItemDelegate):
        """
        Handles tileset objects and their rendering
        """

        def paint(self, painter, option, index):
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
            if option.state & QtWidgets.QStyle.State_Selected:
                painter.fillRect(option.rect, option.palette.highlight())

            p = index.model().data(index, Qt.DecorationRole)
            if p is None or p.isNull():
                painter.drawText(option.rect, str(index.row()))
            else:
                painter.drawPixmap(option.rect.x() + 2, option.rect.y() + 2, p)
            # painter.drawText(option.rect, str(index.row()))

        def sizeHint(self, option, index):
            """
            Returns the size for the object
            """
            p = index.model().data(index, Qt.UserRole)
            return p or QtCore.QSize(globals.TileWidth, globals.TileWidth)
            # return QtCore.QSize(76,76)

    class ObjectListModel(QtCore.QAbstractListModel):
        """
        Model containing all the objects in a tileset
        """

        def __init__(self):
            """
            Initializes the model
            """
            super().__init__()
            self.items = []
            self.ritems = []
            self.itemsize = []

            for i in range(256):
                self.items.append(None)
                self.ritems.append(None)

        def rowCount(self, parent=None):
            """
            Required by Qt
            """
            return len(self.items)

        def data(self, index, role=Qt.DisplayRole):
            """
            Get what we have for a specific row
            """
            if not index.isValid(): return None
            n = index.row()
            if n < 0: return None
            if n >= len(self.items): return None

            if role == Qt.DecorationRole and n < len(self.ritems):
                return self.ritems[n]

            if role == Qt.BackgroundRole:
                return QtWidgets.qApp.palette().base()

            if role == Qt.UserRole and n < len(self.itemsize):
                return self.itemsize[n]

            if role == Qt.ToolTipRole and n < len(self.tooltips):
                return self.tooltips[n]

            return None

        def LoadFromTileset(self, idx):
            """
            Renders all the object previews for the model
            """
            self.items = []
            self.ritems = []
            self.itemsize = []
            self.tooltips = []

            self.beginResetModel()

            globals.numObj = []

            z = 0

            if idx == 4:
                numTileset = range(1, 4)
            else:
                numTileset = [idx]

            for idx in numTileset:
                if globals.ObjectDefinitions[idx] is None:
                    globals.numObj.append(z)
                    continue

                defs = globals.ObjectDefinitions[idx]

                for i in range(256):
                    if defs[i] is None:
                        break

                    obj = RenderObject(idx, i, defs[i].width, defs[i].height, True)
                    self.items.append(obj)

                    pm = QtGui.QPixmap(defs[i].width * globals.TileWidth, defs[i].height * globals.TileWidth)
                    pm.fill(Qt.transparent)
                    p = QtGui.QPainter()
                    p.begin(pm)
                    y = 0
                    isAnim = False

                    for row in obj:
                        x = 0
                        for tile in row:
                            if tile != -1:
                                try:
                                    if isinstance(globals.Tiles[tile].main, QtGui.QImage):
                                        p.drawImage(x, y, globals.Tiles[tile].main)
                                    else:
                                        p.drawPixmap(x, y, globals.Tiles[tile].main)
                                except AttributeError:
                                    break
                                if isinstance(globals.Tiles[tile], TilesetTile) and globals.Tiles[tile].isAnimated: isAnim = True
                            x += globals.TileWidth
                        y += globals.TileWidth
                    p.end()

                    dpr = globals.TileWidth / 32
                    if pm.width() > 256 * dpr:
                        pm = pm.scaledToWidth(round(256 * dpr), Qt.SmoothTransformation)
                    if pm.height() > 256 * dpr:
                        pm = pm.scaledToHeight(round(256 * dpr), Qt.SmoothTransformation)
                    pm.setDevicePixelRatio(dpr)

                    self.ritems.append(pm)
                    self.itemsize.append(QtCore.QSize(round(pm.width() / dpr) + 4, round(pm.height() / dpr) + 4))
                    if (idx == 0) and (i in globals.ObjDesc) and isAnim:
                        self.tooltips.append('<b>Tileset [tileset], object [id]:</b><br>[desc]<br><i>This object is animated</i>'.replace('[tileset]', str(idx + 1)).replace('[id]', str(i)).replace('[desc]', str(globals.ObjDesc[i])))
                    elif (idx == 0) and (i in globals.ObjDesc):
                        self.tooltips.append('<b>Tileset [tileset], object [id]:</b><br>[desc]'.replace('[tileset]', str(idx + 1)).replace('[id]', str(i)).replace('[desc]', str(globals.ObjDesc[i])))
                    elif isAnim:
                        self.tooltips.append('Tileset [tileset], object [id]<br><i>This object is animated</i>'.replace('[tileset]', str(idx + 1)).replace('[id]', str(i)))
                    else:
                        self.tooltips.append('Tileset [tileset], object [id]'.replace('[tileset]', str(idx + 1)).replace('[id]', str(i)))

                    z += 1

                globals.numObj.append(z)

            self.endResetModel()


        def LoadFromFolder(self):
            """
            Renders all the object previews for the model from a folder
            """
            globals.ObjectAllDefinitions = []
            globals.ObjectAllCollisions = []
            globals.ObjectAllImages = []

            self.items = []
            self.ritems = []
            self.itemsize = []
            self.tooltips = []

            self.beginResetModel()

            # Fixes issues if the user selects the wrong Objects Folder
            if not globals.mainWindow.folderPicker.currentText():
                self.endResetModel()
                return

            z = 0
            top_folder = os.path.join(setting('ObjPath'), globals.mainWindow.folderPicker.currentText())

            # Get the list of files in the folder
            files = os.listdir(top_folder)
            ## Sort the files through "Natural sorting" (opposite of "Lexicographic sorting")
            files.sort(key=lambda s: [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)])

            # Discard files not enging with ".json" from the list
            files_ = [file for file in files if file[-5:] == ".json"]
            del files

            for file in files_:
                dir = top_folder + "/"

                with open(dir + file) as inf:
                    jsonData = json.load(inf)

                if not ("colls" in jsonData and "meta" in jsonData and "objlyt" in jsonData
                        and "img" in jsonData and "nml" in jsonData):

                    # Invalid object JSON
                    continue

                # Check for the required files
                found = True
                for f in ["colls", "meta", "objlyt", "img", "nml"]:
                    if not os.path.isfile(dir + jsonData[f]):
                        print("%s not found!" % (dir + jsonData[f]))
                        found = False
                        break

                if not found:
                    # One of the required files is missing
                    continue

                with open(dir + jsonData["colls"], "rb") as inf:
                    globals.ObjectAllCollisions.append(inf.read())

                with open(dir + jsonData["meta"], "rb") as inf:
                    indexfile = inf.read()

                with open(dir + jsonData["objlyt"], "rb") as inf:
                    deffile = inf.read()

                # Read the object definition file into Object instances
                indexstruct = struct.Struct('>HBBH')

                data = indexstruct.unpack_from(indexfile, 0)
                def_ = ObjectDef()
                def_.width = data[1]
                def_.height = data[2]
                def_.folderIndex = globals.mainWindow.folderPicker.currentIndex()
                def_.objAllIndex = z

                if "randLen" in jsonData:
                    def_.randByte = data[3]

                else:
                    def_.randByte = 0

                def_.load(deffile, 0)

                globals.ObjectAllDefinitions.append(def_)

                # Get the properly rendered object definition
                obj = RenderObjectAll(def_, def_.width, def_.height, True)
                self.items.append(obj)

                globals.ObjectAllImages.append([QtGui.QPixmap(dir + jsonData["img"]),
                                        QtGui.QPixmap(dir + jsonData["nml"])])

                img, nml = globals.ObjectAllImages[-1]

                # Render said object definition for the preview
                tilesUsed = {}
                tiles = [None] * def_.width * def_.height

                # Load the tiles of the object for the preview
                ## Start by creating a TilesetTile instance for each tile
                if def_.reversed:
                    for crow, row in enumerate(def_.rows):
                        if def_.subPartAt != -1:
                            if crow >= def_.subPartAt:
                                crow -= def_.subPartAt

                            else:
                                crow += def_.height - def_.subPartAt

                        x = 0
                        y = crow

                        for tile in row:
                            if len(tile) == 3:
                                if tile != [0, 0, 0]:
                                    tilesUsed[tile[1] & 0x3FF] = y * def_.width + x
                                    tiles[y * def_.width + x] = TilesetTile(img.copy(x * 60, y * 60, 60, 60), nml.copy(x * 60, y * 60, 60, 60))

                                x += 1

                else:
                    for crow, row in enumerate(def_.rows):
                        x = 0
                        y = crow

                        for tile in row:
                            if len(tile) == 3:
                                if tile != [0, 0, 0]:
                                    tilesUsed[tile[1] & 0x3FF] = y * def_.width + x
                                    tiles[y * def_.width + x] = TilesetTile(img.copy(x * 60, y * 60, 60, 60), nml.copy(x * 60, y * 60, 60, 60))

                                x += 1

                # Start painting the preview
                pm = QtGui.QPixmap(def_.width * 60, def_.height * 60)
                pm.fill(Qt.transparent)
                p = QtGui.QPainter()
                p.begin(pm)
                y = 0

                for row in obj:
                    x = 0
                    for tile in row:
                        if tile != -1:
                            if tile in tilesUsed:
                                p.drawPixmap(x, y, tiles[tilesUsed[tile]].main)
                            else:
                                try:
                                    if isinstance(globals.Tiles[tile].main, QtGui.QImage):
                                        p.drawImage(x, y, globals.Tiles[tile].main)
                                    else:
                                        p.drawPixmap(x, y, globals.Tiles[tile].main)
                                except AttributeError:
                                    break
                        x += 60
                    y += 60
                p.end()

                # Resize the preview for a good looking layout
                pm = pm.scaledToWidth(round(pm.width() * 32 / globals.TileWidth), Qt.SmoothTransformation)
                if pm.width() > 256:
                    pm = pm.scaledToWidth(256, Qt.SmoothTransformation)
                if pm.height() > 256:
                    pm = pm.scaledToHeight(256, Qt.SmoothTransformation)

                self.ritems.append(pm)
                self.itemsize.append(QtCore.QSize(pm.width() + 4, pm.height() + 4))
                self.tooltips.append('Object [id]'.replace('[id]', str(z)))

                z += 1

            self.endResetModel()


class _PasteClipDialog(QtWidgets.QDialog):
    """Fallback dialog shown when the clipboard doesn't contain a valid MiyamotoClip."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Paste Clip')
        self.setMinimumWidth(440)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        label = QtWidgets.QLabel('Paste a copied clip below:')
        self.editor = QtWidgets.QPlainTextEdit()
        self.editor.setPlaceholderText('Copied clip text')
        self.editor.setFixedHeight(96)
        mono = QtGui.QFont('Courier')
        mono.setStyleHint(QtGui.QFont.Monospace)
        self.editor.setFont(mono)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(label)
        layout.addWidget(self.editor)
        layout.addWidget(buttons)

    def get_text(self):
        return self.editor.toPlainText().strip()


class _ClipItemDelegate(QtWidgets.QStyledItemDelegate):
    """Renders each clip row: bordered thumbnail on the left, bold name on the right."""

    THUMB = 56
    PAD = 8

    def paint(self, painter, option, index):
        clip = index.data(Qt.UserRole)
        if clip is None:
            return

        clip.ensure_preview()

        painter.save()
        rect = option.rect
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)

        if selected:
            painter.fillRect(rect, option.palette.highlight())
            text_color = option.palette.highlightedText().color()
            border_color = option.palette.highlightedText().color()
            border_color.setAlpha(80)
        else:
            text_color = option.palette.text().color()
            border_color = option.palette.mid().color()

        pad = self.PAD
        thumb = self.THUMB
        thumb_rect = QtCore.QRect(rect.x() + pad, rect.y() + pad, thumb, thumb)

        painter.setPen(QtGui.QPen(border_color, 1))
        painter.drawRect(thumb_rect)

        preview = clip.preview
        if preview and not preview.isNull():
            inner = thumb - 4
            scaled = preview.scaled(inner, inner, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            dx = thumb_rect.x() + 2 + (inner - scaled.width()) // 2
            dy = thumb_rect.y() + 2 + (inner - scaled.height()) // 2
            painter.drawPixmap(dx, dy, scaled)

        text_x = rect.x() + pad + thumb + pad
        text_rect = QtCore.QRect(text_x, rect.y(), rect.right() - text_x - pad, rect.height())
        painter.setPen(text_color)
        bold_font = QtGui.QFont(option.font)
        bold_font.setBold(True)
        painter.setFont(bold_font)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.TextWordWrap, clip.name)

        painter.restore()

    def sizeHint(self, option, index):
        return QtCore.QSize(0, self.THUMB + self.PAD * 2)


class ClipChooserWidget(QtWidgets.QWidget):
    """
    Palette tab widget for saving, browsing, and placing Clips (MiyamotoClip snippets).
    """

    selectionChanged = QtCore.pyqtSignal()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def __init__(self):
        super().__init__()
        self._clips = []
        self._setup_ui()
        self._load_initial()

    def _setup_ui(self):
        info = QtWidgets.QLabel(
            'Saved clips let you reuse selections of objects and actors.<br>'
            'Select a clip below, then click in the level to place it.')
        info.setWordWrap(True)

        self.newBtn = QtWidgets.QToolButton()
        self.newBtn.setText('New')
        self.newBtn.setIcon(GetIcon('add'))
        self.newBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.newBtn.setToolTip('Save selected level objects as a new clip')
        self.newBtn.setEnabled(False)
        self.newBtn.clicked.connect(self._on_new)

        import_menu = QtWidgets.QMenu(self)
        import_menu.addAction(
            GetIcon('openfromfile'), 'Import from File…', self._on_import_file)
        import_menu.addAction(
            GetIcon('paste'), 'Paste from Clipboard', self._on_import_clipboard)

        self.importBtn = QtWidgets.QToolButton()
        self.importBtn.setText('Import')
        self.importBtn.setIcon(GetIcon('import'))
        self.importBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.importBtn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.importBtn.setMenu(import_menu)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(4)
        toolbar.addWidget(self.newBtn)
        toolbar.addWidget(self.importBtn)
        toolbar.addStretch()

        self.listWidget = QtWidgets.QListWidget()
        self.listWidget.setItemDelegate(_ClipItemDelegate(self.listWidget))
        self.listWidget.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.listWidget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.listWidget.customContextMenuRequested.connect(self._on_context_menu)
        self.listWidget.itemSelectionChanged.connect(self.selectionChanged)
        self.listWidget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.listWidget.setUniformItemSizes(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        layout.addWidget(info)
        layout.addLayout(toolbar)
        layout.addWidget(self.listWidget)

    # ── Data management ───────────────────────────────────────────────────────

    def _load_initial(self):
        for clip in load_clips():
            self._append_clip(clip, save=False)

    def _save(self):
        save_clips(self._clips)

    def _append_clip(self, clip, save=True):
        self._clips.append(clip)
        item = QtWidgets.QListWidgetItem()
        item.setData(Qt.UserRole, clip)
        item.setSizeHint(QtCore.QSize(0, _ClipItemDelegate.THUMB + _ClipItemDelegate.PAD * 2))
        self.listWidget.addItem(item)
        if save:
            self._save()

    def _remove_at(self, row):
        if 0 <= row < len(self._clips):
            self._clips.pop(row)
            self.listWidget.takeItem(row)
            self._save()

    # ── Public API ────────────────────────────────────────────────────────────

    def current_clip(self):
        row = self.listWidget.currentRow()
        if 0 <= row < len(self._clips):
            return self._clips[row]
        return None

    def set_new_enabled(self, enabled):
        self.newBtn.setEnabled(enabled)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _prompt_name(self, default=''):
        name, ok = QtWidgets.QInputDialog.getText(
            self, 'Name Your Clip', 'Enter a name for this clip:',
            QtWidgets.QLineEdit.Normal, default)
        if ok:
            name = name.strip()
            if name:
                return name
        return None

    @staticmethod
    def _sanitize(text):
        return text.replace(' ', '').replace('\n', '').replace('\r', '').replace('\t', '')

    @staticmethod
    def _is_valid(text):
        return isinstance(text, str) and text.startswith('MiyamotoClip|') and text.endswith('|%')

    def _import_clip_string(self, raw, default_name='Imported Clip'):
        clean = self._sanitize(raw)
        if not self._is_valid(clean):
            QtWidgets.QMessageBox.warning(
                self, 'Invalid Clip',
                'The provided text is not a valid clip.\n\n'
                'Copy a selection in the level editor, or open an exported clip file.')
            return
        name = self._prompt_name(default_name)
        if name is None:
            return
        clip = Clip(name=name, miyamoto_clip=clean)
        clip.ensure_preview()
        self._append_clip(clip)
        self.listWidget.setCurrentRow(len(self._clips) - 1)

    # ── Button / menu handlers ────────────────────────────────────────────────

    def _on_new(self):
        mw = globals.mainWindow
        selitems = mw.scene.selectedItems()
        from .items import ObjectItem, SpriteItem, EntranceItem, LocationItem, PathItem, NabbitPathItem, CommentItem
        objs = [o for o in selitems if isinstance(o, ObjectItem)]
        sprs = [o for o in selitems if isinstance(o, SpriteItem)]
        ents = [o for o in selitems if isinstance(o, EntranceItem)]
        locs = [o for o in selitems if isinstance(o, LocationItem)]
        paths = [o for o in selitems if isinstance(o, PathItem)]
        nPaths = [o for o in selitems if isinstance(o, NabbitPathItem)]
        coms = [o for o in selitems if isinstance(o, CommentItem)]
        if not objs and not sprs and not ents and not locs and not paths and not nPaths and not coms:
            return
        clip_str = mw.encodeObjects(objs, sprs, ents, locs, paths, nPaths, coms)
        if not clip_str:
            return
        name = self._prompt_name('New Clip')
        if name is None:
            return
        clip = Clip(name=name, miyamoto_clip=clip_str)
        clip.ensure_preview()
        self._append_clip(clip)
        self.listWidget.setCurrentRow(len(self._clips) - 1)

    def _on_import_file(self):
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Import Clip', '',
            # .miyaclip: clips exported by older versions and other Miyamoto-based editors
            'Clip files (*.yaz0clip *.miyaclip);;Text files (*.txt);;All files (*)')
        if not fn:
            return
        try:
            with open(fn, 'r', encoding='utf-8') as f:
                text = f.read().strip()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, 'Import Failed', f'Could not read file:\n{e}')
            return
        default = os.path.splitext(os.path.basename(fn))[0] or 'Imported Clip'
        self._import_clip_string(text, default)

    def _on_import_clipboard(self):
        text = QtWidgets.QApplication.clipboard().text().strip()
        if self._is_valid(self._sanitize(text)):
            self._import_clip_string(text)
        else:
            dlg = _PasteClipDialog(self)
            if dlg.exec_() == QtWidgets.QDialog.Accepted:
                self._import_clip_string(dlg.get_text())

    def _on_context_menu(self, pos):
        item = self.listWidget.itemAt(pos)
        if item is None:
            return
        row = self.listWidget.row(item)
        if not (0 <= row < len(self._clips)):
            return
        clip = self._clips[row]

        menu = QtWidgets.QMenu(self)
        rename_act = menu.addAction(GetIcon('note'), 'Rename…')
        menu.addSeparator()
        export_act = menu.addAction(GetIcon('save'), 'Export…')
        copy_act   = menu.addAction(GetIcon('copy'), 'Copy to Clipboard')
        menu.addSeparator()
        delete_act = menu.addAction(GetIcon('delete'), 'Delete')

        chosen = menu.exec_(self.listWidget.viewport().mapToGlobal(pos))
        if chosen == rename_act:
            self._rename(row, clip)
        elif chosen == export_act:
            self._export(clip)
        elif chosen == copy_act:
            QtWidgets.QApplication.clipboard().setText(clip.miyamoto_clip)
        elif chosen == delete_act:
            self._remove_at(row)

    def _rename(self, row, clip):
        name = self._prompt_name(clip.name)
        if name is None:
            return
        clip.name = name
        self.listWidget.item(row).setData(Qt.UserRole, clip)
        self.listWidget.update()
        self._save()

    def _export(self, clip):
        safe = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in clip.name)
        fn, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Export Clip', safe + '.yaz0clip',
            'Clip files (*.yaz0clip);;Text files (*.txt)')
        if not fn:
            return
        try:
            with open(fn, 'w', encoding='utf-8') as f:
                f.write(clip.miyamoto_clip)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, 'Export Failed', f'Could not write file:\n{e}')


class _SpriteTypeProxy(QtWidgets.QGraphicsItem):
    """
    Minimal QGraphicsItem stand-in for SpriteItem, passed to SpriteImage
    constructors when rendering type-level previews.  Inheriting from
    QGraphicsItem is essential: aux items call setParentItem(parent), which
    requires parent to be a real QGraphicsItem.  This proxy is never added
    to any scene.
    """

    def __init__(self, type_id):
        super().__init__()
        self.type = type_id
        self.objx = 0
        self.objy = 0
        self.spritedata = bytearray(8)
        self.initialState = 0
        self.aux = []
        self.font = globals.NumberFont
        self.listitem = None
        self.zoneID = -1
        self.layer = 0
        self.ChangingPos = False

    # Required QGraphicsItem abstract methods
    def boundingRect(self):
        return QtCore.QRectF(0, 0, globals.TileWidth, globals.TileWidth)

    def paint(self, painter, option, widget=None):
        pass

    # SpriteItem-compatible stubs
    def UpdateDynamicSizing(self): pass
    def updateScene(self): pass
    def nearestZone(self, *a): return None
    def getFullRect(self): return self.boundingRect()

    def __getattr__(self, name):
        return 0


class SpritePickerItemDelegate(QtWidgets.QStyledItemDelegate):
    """
    Delegate for SpritePickerWidget that optionally renders a sprite-type thumbnail
    beside each leaf row.  Category header rows always use the default style.

    Thumbnails are rendered *outside* Qt paint events via a zero-delay timer so
    that image loading (which can pump the macOS Cocoa event loop) never happens
    while a QPainter is active on a widget — the pattern that causes the
    "recursive repaint" segfault on ARM Mac.
    """

    _PAD = 4

    # class-level shared state
    _type_preview_cache = {}   # (type_id, size) -> QPixmap
    _pending            = {}   # (type_id, size) -> [(view, QPersistentModelIndex), ...]
    _flush_scheduled    = False

    # ── sizeHint ──────────────────────────────────────────────────────────────

    def sizeHint(self, option, index):
        sz = super().sizeHint(option, index)
        type_id = index.data(Qt.UserRole)
        if type_id == -3:
            return QtCore.QSize(0, 0)
        size = globals.SpriteListPreviewSize
        if size > 0 and type_id not in (-1, -2) and type_id is not None:
            sz.setHeight(max(sz.height(), size + self._PAD * 2))
        return sz

    # ── paint ─────────────────────────────────────────────────────────────────

    def paint(self, painter, option, index):
        type_id = index.data(Qt.UserRole)

        if type_id == -3:
            return

        size = globals.SpriteListPreviewSize
        if size == 0 or type_id in (-1, -2) or type_id is None:
            return super().paint(painter, option, index)

        # Draw background / selection / focus via the style (no text or icon).
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ''
        opt.icon = QtGui.QIcon()
        style = opt.widget.style() if opt.widget else QtWidgets.QApplication.style()
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        rect     = option.rect
        pad      = self._PAD
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)

        # Look up the cached pixmap.  If missing, schedule a deferred render —
        # never do any image work here (inside a paint event).
        high_detail = globals.SpriteListPreviewHighDetail
        key = (type_id, size, high_detail)
        pix = self._type_preview_cache.get(key)
        if pix is None:
            pmi = QtCore.QPersistentModelIndex(index)
            SpritePickerItemDelegate._pending.setdefault(key, []).append(
                (option.widget, pmi))
            SpritePickerItemDelegate._schedule_flush()

        thumb_y    = rect.y() + (rect.height() - size) // 2
        thumb_rect = QtCore.QRect(rect.x() + pad, thumb_y, size, size)
        if pix is not None and not pix.isNull():
            painter.save()
            if high_detail:
                painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
            painter.drawPixmap(thumb_rect, pix)
            painter.restore()

        text_color = (option.palette.highlightedText().color() if selected
                      else option.palette.text().color())
        painter.setPen(text_color)
        text_x    = rect.x() + pad + size + pad
        text_rect = QtCore.QRect(text_x, rect.y(), rect.right() - text_x - pad, rect.height())
        text   = index.data(Qt.DisplayRole) or ''
        elided = option.fontMetrics.elidedText(text, Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignVCenter, elided)

    # ── deferred batch renderer ───────────────────────────────────────────────

    @classmethod
    def _schedule_flush(cls):
        """Schedule one deferred flush if not already pending."""
        if not cls._flush_scheduled:
            cls._flush_scheduled = True
            QtCore.QTimer.singleShot(0, cls._flush_pending)

    @classmethod
    def _flush_pending(cls):
        """
        Render all queued sprite-type previews and update affected viewports.
        Fires after the current event (and all paint events) have completed,
        so it is safe to load images and create QPixmaps here.
        """
        cls._flush_scheduled = False
        pending = dict(cls._pending)
        cls._pending.clear()

        for (type_id, size, high_detail), entries in pending.items():
            key = (type_id, size, high_detail)
            if key not in cls._type_preview_cache:
                cls._type_preview_cache[key] = cls._render_type_preview(type_id, size, high_detail)
            # Use QAbstractItemView.update(QModelIndex) for each item that had a
            # cache miss.  This calls viewport()->update(visualRect(index)) which
            # maps to [NSView setNeedsDisplayInRect:] — Cocoa always honours that
            # call regardless of the blit-scroll "clean" state, unlike a blanket
            # viewport().update() / repaint() which macOS can ignore for regions
            # it considers already clean after a scroll.
            for view, pmi in entries:
                try:
                    if pmi.isValid():
                        view.update(QtCore.QModelIndex(pmi))
                except Exception:
                    pass

    # ── preview rendering (safe outside paint events) ─────────────────────────

    @classmethod
    def _render_type_preview(cls, type_id, thumb_size, high_detail=False):
        """
        Build a (thumb_size × thumb_size) QPixmap for *type_id*.

        When *high_detail* is True the sprite is painted at its native pixel
        resolution then smoothly downscaled, yielding maximum-quality
        thumbnails on high-DPI displays.

        For sprites with a custom SpriteImage class the image is painted;
        for sprites without one (or where the image class raises) the plain
        spritebox (blue rounded rect + ID number) is drawn instead, matching
        exactly what the level editor shows for those sprites.
        """
        try:
            bg = globals.theme.color('bg')
        except Exception:
            bg = QtGui.QColor(119, 136, 153)

        from . import spritelib as SLib
        tw    = globals.TileWidth
        scale = tw / 16

        proxy = _SpriteTypeProxy(type_id)
        pix = None
        try:
            # ── build image object ─────────────────────────────────────────
            # Failures fall back to the bare SpriteImage so we always have
            # at least a spritebox to draw.
            image_obj = None
            if isinstance(type_id, (int, str)):
                try:
                    imgs      = globals.gamedef.getImageClasses()
                    img_class = imgs.get(type_id)
                    if img_class is not None:
                        img_class.loadImages()
                        image_obj = img_class(proxy)
                        image_obj.dataChanged()
                except Exception:
                    image_obj = None

            if image_obj is None:
                image_obj = SLib.SpriteImage(proxy)

            # ── layout ────────────────────────────────────────────────────
            box_br = image_obj.spritebox.BoundingRect
            img_br = QtCore.QRectF(0, 0,
                                   image_obj.width  * scale,
                                   image_obj.height * scale)
            br = box_br | img_br

            w, h = br.width(), br.height()
            if w <= 0 or h <= 0:
                w = h = float(tw)
                br = QtCore.QRectF(0, 0, float(tw), float(tw))

            render_size = int(max(w, h)) if high_detail else thumb_size
            pix = QtGui.QPixmap(render_size, render_size)
            pix.fill(bg)

            margin = 0.85
            s  = min(render_size / w, render_size / h) * margin
            ox = (render_size - w * s) / 2 - br.x() * s
            oy = (render_size - h * s) / 2 - br.y() * s

            # ── paint ─────────────────────────────────────────────────────
            painter = QtGui.QPainter(pix)
            if high_detail:
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
                painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
            painter.save()
            painter.translate(ox, oy)
            painter.scale(s, s)

            try:
                image_obj.paint(painter)
            except Exception:
                pass

            # Spritebox: drawn for sprites whose image class sets shown=True
            # (typically sprites with no real sprite image).
            if image_obj.spritebox.shown:
                sbr = image_obj.spritebox.RoundedRect
                painter.setBrush(QtGui.QBrush(globals.theme.color('spritebox_fill')))
                painter.setPen(QtGui.QPen(globals.theme.color('spritebox_lines'),
                                          tw / 24))
                painter.drawRoundedRect(sbr, 4, 4)
                if globals.NumberFont:
                    painter.setFont(globals.NumberFont)
                painter.drawText(sbr, Qt.AlignCenter, str(type_id))

            painter.restore()
            painter.end()

        except Exception:
            pass

        finally:
            # Always detach aux QGraphicsItems before the proxy goes out of
            # scope to avoid Qt C++ ownership confusion.
            for aux in proxy.aux[:]:
                try:
                    aux.setParentItem(None)
                except Exception:
                    pass
            proxy.aux.clear()

        if pix is None:
            pix = QtGui.QPixmap(thumb_size, thumb_size)
        return pix

    @classmethod
    def clear_cache(cls):
        cls._type_preview_cache.clear()


class SpriteListItemDelegate(QtWidgets.QStyledItemDelegate):
    """
    Delegate for the current-actors list that optionally renders a small sprite
    thumbnail on the left of each row.  When SpriteListPreviewSize is DISABLED
    the delegate falls back to the default QStyledItemDelegate behaviour so the
    list looks exactly as it did before.
    """

    SMALL  = globals.SPRITE_PREVIEW_SMALL
    MEDIUM = globals.SPRITE_PREVIEW_MEDIUM
    LARGE  = globals.SPRITE_PREVIEW_LARGE

    _PAD = 4

    # ── sizeHint ──────────────────────────────────────────────────────────────

    def sizeHint(self, option, index):
        sz = super().sizeHint(option, index)
        size = globals.SpriteListPreviewSize
        if size > 0:
            sz.setHeight(max(sz.height(), size + self._PAD * 2))
        return sz

    # ── paint ─────────────────────────────────────────────────────────────────

    def paint(self, painter, option, index):
        size = globals.SpriteListPreviewSize
        if size == 0:
            return super().paint(painter, option, index)

        lw = option.widget
        item = lw.item(index.row()) if lw is not None else None
        spr  = getattr(item, 'reference', None) if item is not None else None

        painter.save()

        # Draw background + selection highlight + focus ring via the style
        # (pass an empty-text copy so the style doesn't draw the label itself)
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ''
        opt.icon = QtGui.QIcon()
        style = opt.widget.style() if opt.widget else QtWidgets.QApplication.style()
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        rect = option.rect
        pad  = self._PAD
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)

        # Thumbnail
        thumb_x = rect.x() + pad
        thumb_y = rect.y() + (rect.height() - size) // 2
        thumb_rect = QtCore.QRect(thumb_x, thumb_y, size, size)

        if spr is not None:
            pix = self._get_preview(spr, size)
            if pix and not pix.isNull():
                painter.save()
                if globals.SpriteListPreviewHighDetail:
                    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
                painter.drawPixmap(thumb_rect, pix)
                painter.restore()

        # Text
        text_color = (option.palette.highlightedText().color()
                      if selected else option.palette.text().color())
        painter.setPen(text_color)

        text_x    = thumb_x + size + pad
        text_rect = QtCore.QRect(text_x, rect.y(), rect.right() - text_x - pad, rect.height())
        text      = index.data(Qt.DisplayRole) or ''
        elided    = option.fontMetrics.elidedText(text, Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignVCenter, elided)

        painter.restore()

    # ── preview helpers ───────────────────────────────────────────────────────

    def _get_preview(self, spr, thumb_size):
        """Return a cached QPixmap for *spr* at *thumb_size*, rendering on miss."""
        high_detail = globals.SpriteListPreviewHighDetail
        key    = (thumb_size, id(spr.ImageObj), high_detail)
        cached = getattr(spr, '_list_preview_cache', None)
        if cached is not None and cached[0] == key:
            return cached[1]
        pix = self._render_preview(spr, thumb_size, high_detail)
        spr._list_preview_cache = (key, pix)
        return pix

    def _render_preview(self, spr, thumb_size, high_detail=False):
        """Render the sprite image centred on the canvas background colour."""
        try:
            bg = globals.theme.color('bg')
        except Exception:
            bg = QtGui.QColor(119, 136, 153)

        br = spr.BoundingRect
        w, h = br.width(), br.height()
        if w <= 0 or h <= 0:
            return QtGui.QPixmap(thumb_size, thumb_size)

        render_size = int(max(w, h)) if high_detail else thumb_size
        pix = QtGui.QPixmap(render_size, render_size)
        pix.fill(bg)

        margin = 0.85
        s  = min(render_size / w, render_size / h) * margin
        ox = (render_size - w * s) / 2 - br.x() * s
        oy = (render_size - h * s) / 2 - br.y() * s

        painter = QtGui.QPainter(pix)
        if high_detail:
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.save()
        painter.translate(ox, oy)
        painter.scale(s, s)
        try:
            spr.paint(painter, None, None, True)
        except Exception:
            pass
        painter.restore()
        painter.end()

        return pix


class SpritePickerWidget(QtWidgets.QTreeWidget):
    """
    Widget that shows a list of available sprites
    """

    def __init__(self):
        """
        Initializes the widget
        """
        super().__init__()
        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setIndentation(16)
        self.setItemDelegate(SpritePickerItemDelegate(self))
        self.currentItemChanged.connect(self.HandleItemChange)
        self.itemClicked.connect(self.PutDownIfClickedAgain)
        self.clickedPicked = False
        self.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)

        from . import loading
        loading.LoadSpriteData()
        loading.LoadSpriteListData()
        loading.LoadSpriteCategories()
        del loading

        self.LoadItems()

    def LoadItems(self):
        """
        Loads tree widget items
        """
        self.clear()

        for viewname, view, nodelist in globals.SpriteCategories:
            for n in nodelist: nodelist.remove(n)
            isCustomView = (viewname == 'Custom')
            for catname, category in view:
                cnode = QtWidgets.QTreeWidgetItem()
                cnode.setText(0, catname)
                # Single-category views use -3 so the header is rendered
                # at 0 height and children appear as a flat list.
                header_role = -3 if len(view) == 1 else -1
                cnode.setData(0, Qt.UserRole, header_role)

                isSearch = (catname == 'All Actors')
                if isSearch:
                    self.SearchResultsCategory = cnode
                    SearchableItems = []

                for id in category:
                    snode = QtWidgets.QTreeWidgetItem()
                    if id == 9999:
                        snode.setText(0, 'No actors found')
                        snode.setData(0, Qt.UserRole, -2)
                        self.NoSpritesFound = snode
                    else:
                        sdef = globals.Sprites[id] if 0 <= id < globals.NumSprites else None
                        if sdef is None:
                            continue
                        snode.setText(0, '[id]: [name]'.replace('[id]', str(id)).replace('[name]', str(sdef.name)))
                        snode.setData(0, Qt.UserRole, id)

                    if isSearch:
                        SearchableItems.append(snode)

                    cnode.addChild(snode)

                # Custom-ID actors only appear in the All view and the Custom view
                if isSearch or isCustomView:
                    for str_id, sdef in sorted(globals.CustomSpriteDefinitions.items()):
                        snode = QtWidgets.QTreeWidgetItem()
                        snode.setText(0, f"[S] {sdef.name} ({str_id})")
                        snode.setData(0, Qt.UserRole, str_id)
                        cnode.addChild(snode)
                        if isSearch:
                            SearchableItems.append(snode)

                self.addTopLevelItem(cnode)
                cnode.setHidden(True)
                nodelist.append(cnode)

        self.ShownSearchResults = SearchableItems
        self._allSearchItems = [item for item in SearchableItems if item.data(0, Qt.UserRole) != -2]
        self.NoSpritesFound.setHidden(True)

        self.itemClicked.connect(self.HandleSprReplace)

        self.SwitchView(globals.SpriteCategories[0])
        self.ContentChanged.emit()

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        # Remember whether this click is on the actor that is already picked
        self.clickedPicked = (event.button() == Qt.LeftButton and item is not None
                              and item is self.currentItem() and partsbar.isArmed())
        super().mousePressEvent(event)

    def PutDownIfClickedAgain(self, item, column=0):
        """Clicking the picked actor again puts it down."""
        if self.clickedPicked:
            self.clickedPicked = False
            partsbar.disarm()

    # ── scroll override ────────────────────────────────────────────────────────

    def scrollContentsBy(self, dx, dy):
        """
        Disable the backing-store blit before scrolling so macOS doesn't cache
        the pre-scroll pixels, then force a full synchronous repaint so every
        visible item is redrawn from the model rather than from a stale buffer.
        """
        vp = self.viewport()
        vp.setUpdatesEnabled(False)
        super().scrollContentsBy(dx, dy)
        vp.setUpdatesEnabled(True)
        vp.repaint()

    # ── view switch ────────────────────────────────────────────────────────────

    def SwitchView(self, view):
        """
        Changes the selected sprite view
        """

        for i in range(0, self.topLevelItemCount()):
            self.topLevelItem(i).setHidden(True)

        for node in view[2]:
            node.setHidden(False)
            if node.data(0, Qt.UserRole) == -3:
                node.setExpanded(True)
            for j in range(node.childCount()):
                child = node.child(j)
                child.setHidden(child.data(0, Qt.UserRole) == -2)

        # Remove indentation for single-category views so children appear flush.
        is_flat = len(view[2]) == 1 and view[2][0].data(0, Qt.UserRole) == -3
        self.setIndentation(0 if is_flat else 16)

        self._currentViewNodes = list(view[2])

        # Force layout to apply immediately so item positions are correct
        # before the first scroll event arrives.
        self.scheduleDelayedItemsLayout()
        self.executeDelayedItemsLayout()
        self.ContentChanged.emit()

    def HandleItemChange(self, current, previous):
        """
        Throws a signal when the selected object changed
        """
        if current is None: return
        data = current.data(0, Qt.UserRole)

        if data == -1:
            return

        if isinstance(data, str):
            # Selection is not a persistence event. Keep the stable string ID
            # until a placement/replacement actually commits it to the level.
            self.SpriteChanged.emit(data)

        elif isinstance(data, int) and data >= 0:
            # It's a standard sprite with an integer ID
            self.SpriteChanged.emit(data)


    def SetSearchString(self, searchfor):
        """
        Filters the currently visible view by the search string
        """
        import re

        def normalize(s):
            return re.sub(r'[-–—_\s]+', ' ', s).replace("'", '').strip().lower()

        terms = [t for t in normalize(searchfor).split() if t]
        current_nodes = getattr(self, '_currentViewNodes', [])
        in_all_view = hasattr(self, 'SearchResultsCategory') and self.SearchResultsCategory in current_nodes

        for node in current_nodes:
            node_has_visible = False
            for j in range(node.childCount()):
                item = node.child(j)
                if item.data(0, Qt.UserRole) == -2:
                    continue  # NoSpritesFound placeholder — handled below
                item_text = normalize(item.text(0))
                visible = not terms or all(term in item_text for term in terms)
                item.setHidden(not visible)
                if visible:
                    node_has_visible = True

            if in_all_view and node is self.SearchResultsCategory:
                node.setHidden(False)
                self.NoSpritesFound.setHidden(node_has_visible or not terms)
            else:
                node.setHidden(bool(terms) and not node_has_visible)

        if current_nodes:
            current_nodes[0].setExpanded(True)
        self.ContentChanged.emit()

    def HandleSprReplace(self, item, column):
        """
        Throws a signal when the selected sprite is used as a replacement
        """
        if QtWidgets.QApplication.keyboardModifiers() == Qt.AltModifier:
            id = item.data(0, Qt.UserRole)
            if id != -1:
                self.SpriteReplace.emit(id)

    SpriteChanged = QtCore.pyqtSignal(object)
    SpriteReplace = QtCore.pyqtSignal(object)
    ContentChanged = QtCore.pyqtSignal()  # the shown actors changed (view, search or reload)


class SpriteEditorWidget(QtWidgets.QWidget):
    """
    Widget for editing sprite data
    """
    DataUpdate = QtCore.pyqtSignal('PyQt_PyObject')

    def __init__(self, defaultmode=False):
        """
        Constructor
        """
        super().__init__()
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed))

        # create the raw editor
        font = QtGui.QFont()
        font.setPointSize(8)
        editbox = QtWidgets.QLabel('Edit Raw Data:')
        editbox.setFont(font)
        edit = QtWidgets.QLineEdit()
        edit.setFocusPolicy(Qt.ClickFocus)
        edit.textEdited.connect(self.HandleRawDataEdited)
        self.raweditor = edit

        editboxlayout = QtWidgets.QHBoxLayout()
        editboxlayout.addWidget(editbox)
        editboxlayout.addWidget(edit)
        editboxlayout.setStretch(1, 1)

        # 'Editing Sprite #' label
        self.spriteLabel = QtWidgets.QLabel('-')
        self.spriteLabel.setWordWrap(True)

        self.relatedObjFilesButton = QtWidgets.QToolButton()
        self.relatedObjFilesButton.setIcon(GetIcon('data'))
        self.relatedObjFilesButton.setText('Object Files')
        self.relatedObjFilesButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.relatedObjFilesButton.setAutoRaise(True)
        self.relatedObjFilesButton.clicked.connect(self.ShowRelatedObjFilesTooltip)

        self.noteButton = QtWidgets.QToolButton()
        self.noteButton.setIcon(GetIcon('note'))
        self.noteButton.setText('Notes')
        self.noteButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.noteButton.setAutoRaise(True)
        self.noteButton.clicked.connect(self.ShowNoteTooltip)
        self.noteButton.setVisible(False)

        self.previewMovementButton = QtWidgets.QToolButton()
        self.previewMovementButton.setIcon(GetIcon('animation'))
        self.previewMovementButton.setText('Preview Movement')
        self.previewMovementButton.setToolTip('Play a preview of how the actors with this Movement ID move.<br>'
                                              'Nothing in the level is changed.')
        self.previewMovementButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.previewMovementButton.setAutoRaise(True)
        self.previewMovementButton.setCheckable(True)
        self.previewMovementButton.toggled.connect(self.HandlePreviewMovement)
        self.previewMovementButton.setVisible(False)

        self.previewSpeedBox = QtWidgets.QComboBox()
        self.previewSpeedBox.setToolTip('Preview speed (1x is the speed of the game)')
        self.previewSpeedBox.setFocusPolicy(Qt.ClickFocus)
        for value in movementpreview.SPEEDS:
            self.previewSpeedBox.addItem(('%gx' % value) + (' (game)' if value == 1 else ''), value)
        self.previewSpeedBox.setCurrentIndex(movementpreview.SPEEDS.index(movementpreview.speed()))
        self.previewSpeedBox.currentIndexChanged.connect(
            lambda i: movementpreview.set_speed(self.previewSpeedBox.itemData(i)))
        self.previewSpeedBox.setVisible(False)
        movementpreview.listeners.append(self._syncPreviewButton)

        self.previewOptionsButton = QtWidgets.QToolButton()
        self.previewOptionsButton.setText('Options')
        self.previewOptionsButton.setToolTip('Play once, and show where the movement starts and ends')
        self.previewOptionsButton.setAutoRaise(True)
        self.previewOptionsButton.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.previewOptionsButton.setMenu(movementpreview.options_menu(self.previewOptionsButton))
        self.previewOptionsButton.setVisible(False)

        toplayout = QtWidgets.QHBoxLayout()
        toplayout.addWidget(self.spriteLabel)
        toplayout.addStretch(1)
        toplayout.addWidget(self.previewMovementButton)
        toplayout.addWidget(self.previewSpeedBox)
        toplayout.addWidget(self.previewOptionsButton)
        toplayout.addWidget(self.relatedObjFilesButton)
        toplayout.addWidget(self.noteButton)

        subLayout = QtWidgets.QVBoxLayout()
        subLayout.setContentsMargins(0, 0, 0, 0)

        # create a layout
        mainLayout = QtWidgets.QVBoxLayout()
        mainLayout.addLayout(toplayout)
        mainLayout.addLayout(subLayout)

        self.noteBox = QtWidgets.QGroupBox()
        self.notesDisplay = QtWidgets.QTextEdit()
        self.notesDisplay.setReadOnly(True)
        self.notesDisplay.setMaximumHeight(100)
        L = QtWidgets.QVBoxLayout()
        L.setContentsMargins(4, 4, 4, 4)
        L.addWidget(self.notesDisplay)
        self.noteBox.setLayout(L)
        self.noteBox.setVisible(False)

        layout = QtWidgets.QGridLayout()
        self.editorlayout = layout
        subLayout.addLayout(layout)
        subLayout.addWidget(self.noteBox)
        subLayout.addLayout(editboxlayout)

        self.setLayout(mainLayout)

        self.activeLayer = QtWidgets.QComboBox()
        self.activeLayer.setFocusPolicy(Qt.ClickFocus)
        self.activeLayer.addItems(('Layer 1', 'Layer 2', 'Layer 0'))
        self.activeLayer.setToolTip('<b>Layer:</b><br>Allows you to change the layer which this actor is active on. This field is not read in-game by some actors - for almost all normal cases, you will want to use layer 1.')
        self.activeLayer.activated.connect(globals.mainWindow.SpriteLayerUpdated)

        self.initialState = QtWidgets.QSpinBox()
        self.initialState.setFocusPolicy(Qt.ClickFocus)
        self.initialState.setRange(0, 255)
        self.initialState.setToolTip('<b>Initial State:</b><br>Used by some actors to initiate in a different state depending on the value of this field.')
        self.initialState.valueChanged.connect(globals.mainWindow.SpriteInitialStateUpdated)

        self.spritetype = -1
        self.data = b'\0' * 12
        self.fields = []
        self.UpdateFlag = False
        self.DefaultMode = defaultmode

        self.notes = None
        self.relatedObjFiles = None
        self._tabWidget = None
        self._behaviorGrid = None
        self._layerWidgets = []
        self._initialStateWidget = None

        # Multi-select state
        self._multiMode = False       # True when >1 actor is selected
        self._mixedTypeMode = False   # True when selected actors have different types
        self._multiItems = []         # list of SpriteItem references
        self._multiBaseline = ''      # 24-char hex string displayed when multi-mode was set up

    def sizeHint(self):
        if self._tabWidget is not None and globals.CategorizedSpriteData:
            tab_py = self._tabWidget.sizeHint()
            tab_cpp = QtWidgets.QTabWidget.sizeHint(self._tabWidget)
            hint = self.layout().sizeHint()
            return QtCore.QSize(
                hint.width(),
                hint.height() - tab_cpp.height() + tab_py.height()
            )
        return super().sizeHint()

    class PropertyDecoder(QtCore.QObject):
        """
        Base class for all the sprite data decoder/encoders
        """
        updateData = QtCore.pyqtSignal('PyQt_PyObject')

        def retrieve(self, data):
            """
            Extracts the value from the specified bit(s). Delegates to the
            module-level extract_field_value() so the logic is not duplicated.
            """
            return extract_field_value(data, self.bit)

        def checkReq(self, data):
            """
            Checks whether this field's requirement (requirednybble/requiredval)
            is met by the current data. Hides the field row if not.
            """
            required = getattr(self, 'required', None)
            if required is None:
                return

            show = True
            for bit_range, val_range in required:
                value = extract_field_value(data, bit_range)
                show = show and val_range[0] <= value < val_range[1]

            layout = getattr(self, 'layout', None)
            row = getattr(self, 'row', None)
            if layout is None or row is None:
                return

            for i in range(layout.columnCount()):
                w = layout.itemAtPosition(row, i)
                if w is not None:
                    w.widget().setVisible(show)

        def insertvalue(self, data, value):
            """
            Assigns a value to the specified bit(s)
            """
            bit = self.bit
            sdata = list(data)

            if isinstance(bit, tuple):
                if bit[1] == bit[0] + 7 and bit[0] & 1 == 1:
                    # just one byte, this is easier
                    sdata[(bit[0] - 1) >> 3] = value & 0xFF

                else:
                    # complicated stuff
                    for n in reversed(range(bit[0], bit[1])):
                        off = 1 << (7 - ((n - 1) & 7))

                        if value & 1:
                            # set the bit
                            sdata[(n - 1) >> 3] |= off

                        else:
                            # mask the bit out
                            sdata[(n - 1) >> 3] &= 0xFF ^ off

                        value >>= 1

            else:
                # only overwrite one bit
                byte = (bit - 1) >> 3
                if byte >= len(data):
                    return 0

                off = 1 << (7 - ((bit - 1) & 7))

                if value & 1:
                    # set the bit
                    sdata[byte] |= off

                else:
                    # mask the bit out
                    sdata[byte] &= 0xFF ^ off

            return bytes(sdata)

    class CheckboxPropertyDecoder(PropertyDecoder):
        """
        Class that decodes/encodes sprite data to/from a checkbox
        """

        def __init__(self, title, bit, mask, comment, layout, row, editor=None):
            """
            Creates the widget
            """
            super().__init__()

            # Label in column 0 (right-aligned), bare indicator in column 1 —
            # consistent with List, Value, and Bitfield decoders.
            self.label = QtWidgets.QLabel(title + ':')
            self.widget = QtWidgets.QCheckBox()
            self.widget.setFocusPolicy(Qt.ClickFocus)

            if comment is not None:
                self.label.setToolTip(comment)
                self.widget.setToolTip(comment)

            self.widget.clicked.connect(self.HandleClick)

            if isinstance(bit, tuple):
                length = bit[1] - bit[0] + 1

            else:
                length = 1

            xormask = 0
            for i in range(length):
                xormask |= 1 << i

            self.bit = bit
            self.mask = mask
            self.xormask = xormask
            layout.addWidget(self.label, row, 0, Qt.AlignRight)
            layout.addWidget(self.widget, row, 1)

        def update(self, data):
            """
            Updates the value shown by the widget
            """
            self.checkReq(data)
            self.widget.setTristate(False)
            value = ((self.retrieve(data) & self.mask) == self.mask)
            self.widget.setChecked(value)

        def setMixed(self, mixed):
            self.widget.blockSignals(True)
            self.widget.setTristate(mixed)
            if mixed:
                self.widget.setCheckState(Qt.PartiallyChecked)
            self.widget.blockSignals(False)

        def assign(self, data):
            """
            Assigns the selected value to the data
            """
            value = self.retrieve(data) & (self.mask ^ self.xormask)

            if self.widget.isChecked():
                value |= self.mask

            return self.insertvalue(data, value)

        def HandleClick(self, clicked=False):
            """
            Handles clicks on the checkbox — resolve mixed state on first click.
            """
            state = self.widget.checkState()
            if state == Qt.PartiallyChecked:
                return  # still mid-cycle; wait for a definitive state
            self.widget.setTristate(False)
            self.updateData.emit(self)

    class ListPropertyDecoder(PropertyDecoder):
        """
        Class that decodes/encodes sprite data to/from a combobox
        """

        def __init__(self, title, bit, model, comment, layout, row, editor=None):
            """
            Creates the widget
            """
            super().__init__()

            self.model = model
            self.widget = QtWidgets.QComboBox()
            self.widget.setFocusPolicy(Qt.ClickFocus)
            self.widget.setModel(model)

            if comment is not None:
                self.widget.setToolTip(comment)

            self.widget.currentIndexChanged.connect(self.HandleIndexChanged)

            self.bit = bit
            layout.addWidget(QtWidgets.QLabel(title + ':'), row, 0, Qt.AlignRight)
            layout.addWidget(self.widget, row, 1)

        def update(self, data):
            """
            Updates the value shown by the widget
            """
            self.checkReq(data)
            value = self.retrieve(data)
            if not self.model.existingLookup[value]:
                self.widget.setCurrentIndex(-1)
                return

            for i, x in enumerate(self.model.entries):
                if x[0] == value:
                    self.widget.setCurrentIndex(i)
                    break

        def setMixed(self, mixed):
            if mixed:
                self.widget.blockSignals(True)
                self.widget.setCurrentIndex(-1)
                self.widget.blockSignals(False)

        def assign(self, data):
            """
            Assigns the selected value to the data
            """
            idx = self.widget.currentIndex()
            if idx < 0:
                return data  # mixed / unset — leave data unchanged
            return self.insertvalue(data, self.model.entries[idx][0])

        def HandleIndexChanged(self, index):
            """
            Handle the current index changing in the combobox
            """
            if index < 0:
                return

            self.updateData.emit(self)

    class ValuePropertyDecoder(PropertyDecoder):
        """
        Class that decodes/encodes sprite data to/from a spinbox
        """

        def __init__(self, title, bit, max, comment, layout, row, editor=None):
            """
            Creates the widget
            """
            super().__init__()

            # QSpinBox is limited to signed 32-bit ints, so fields wider
            # than 31 bits need a spinbox that can hold larger values
            if max - 1 > 0x7FFFFFFF:
                self.widget = LargeSpinBox()
            else:
                self.widget = QtWidgets.QSpinBox()
            self.widget.setFocusPolicy(Qt.ClickFocus)
            self.widget.setRange(0, max - 1)

            if comment is not None:
                self.widget.setToolTip(comment)

            self.widget.valueChanged.connect(self.HandleValueChanged)

            self.bit = bit
            layout.addWidget(QtWidgets.QLabel(title + ':'), row, 0, Qt.AlignRight)
            layout.addWidget(self.widget, row, 1)

        def update(self, data):
            """
            Updates the value shown by the widget
            """
            self.checkReq(data)
            self.widget.setMinimum(0)
            self.widget.setSpecialValueText('')
            value = self.retrieve(data)
            self.widget.setValue(value)

        def setMixed(self, mixed):
            self.widget.blockSignals(True)
            if mixed:
                self.widget.setMinimum(-1)
                self.widget.setSpecialValueText('—')
                self.widget.setValue(-1)
            else:
                self.widget.setMinimum(0)
                self.widget.setSpecialValueText('')
            self.widget.blockSignals(False)

        def assign(self, data):
            """
            Assigns the selected value to the data
            """
            v = self.widget.value()
            if v < 0:
                return data  # mixed sentinel — leave data unchanged
            return self.insertvalue(data, v)

        def HandleValueChanged(self, value):
            """
            Handle the value changing in the spinbox
            """
            if value < 0:
                return  # mixed sentinel — ignore
            self.updateData.emit(self)

    class BitfieldPropertyDecoder(PropertyDecoder):
        """
        Class that decodes/encodes sprite data to/from a bitfield
        """

        def __init__(self, title, startbit, bitnum, comment, layout, row, editor=None):
            """
            Creates the widget
            """
            super().__init__()

            self.startbit = startbit
            self.bitnum = bitnum

            self.widgets = []

            CheckboxLayout = QtWidgets.QGridLayout()
            CheckboxLayout.setContentsMargins(0, 0, 0, 0)

            for i in range(bitnum):
                c = QtWidgets.QCheckBox()
                c.setFocusPolicy(Qt.ClickFocus)
                self.widgets.append(c)
                CheckboxLayout.addWidget(c, 0, i)

                if comment is not None:
                    c.setToolTip(comment)

                c.toggled.connect(self.HandleValueChanged)

                L = QtWidgets.QLabel(str(i + 1))
                CheckboxLayout.addWidget(L, 1, i)
                CheckboxLayout.setAlignment(L, Qt.AlignHCenter)

            w = QtWidgets.QWidget()
            w.setLayout(CheckboxLayout)

            layout.addWidget(QtWidgets.QLabel(title + ':'), row, 0, Qt.AlignRight)
            layout.addWidget(w, row, 1)

        def update(self, data):
            """
            Updates the value shown by the widget
            """
            self.checkReq(data)
            for bitIdx in range(self.bitnum):
                checkbox = self.widgets[bitIdx]
                checkbox.setTristate(False)
                adjustedIdx = bitIdx + self.startbit
                byteNum = adjustedIdx // 8
                bitNum = adjustedIdx % 8
                checkbox.setChecked((data[byteNum] >> (7 - bitNum) & 1))

        def assign(self, data):
            """
            Assigns the checkbox states to the data
            """
            data = bytearray(data)

            for idx in range(self.bitnum):
                checkbox = self.widgets[idx]

                adjustedIdx = idx + self.startbit
                byteIdx = adjustedIdx // 8
                bitIdx = adjustedIdx % 8

                origByte = data[byteIdx]
                origBit = (origByte >> (7 - bitIdx)) & 1
                newBit = 1 if checkbox.isChecked() else 0

                if origBit == newBit:
                    continue

                if origBit == 0 and newBit == 1:
                    # Turn the byte on by OR-ing it in
                    newByte = (origByte | (1 << (7 - bitIdx))) & 0xFF

                else:
                    # Turn it off by:
                    # inverting it
                    # OR-ing in the new byte
                    # inverting it back
                    newByte = ~origByte & 0xFF
                    newByte = newByte | (1 << (7 - bitIdx))
                    newByte = ~newByte & 0xFF

                data[byteIdx] = newByte

            return bytes(data)

        def setMixed(self, mixed):
            for cb in self.widgets:
                cb.blockSignals(True)
                cb.setTristate(mixed)
                if mixed:
                    cb.setCheckState(Qt.PartiallyChecked)
                cb.blockSignals(False)

        def setMixedFromDiffMask(self, diff_mask):
            diff = bytearray(diff_mask)
            for i, cb in enumerate(self.widgets):
                adjustedIdx = i + self.startbit
                byteNum = adjustedIdx // 8
                bitNum = adjustedIdx % 8
                is_mixed = byteNum < len(diff) and bool((diff[byteNum] >> (7 - bitNum)) & 1)
                cb.blockSignals(True)
                cb.setTristate(is_mixed)
                if is_mixed:
                    cb.setCheckState(Qt.PartiallyChecked)
                else:
                    cb.setTristate(False)
                cb.blockSignals(False)

        def HandleValueChanged(self, value):
            """
            Handle any checkbox being changed — resolve mixed state on first interaction.
            """
            sender = self.sender()
            if isinstance(sender, QtWidgets.QCheckBox):
                state = sender.checkState()
                if state == Qt.PartiallyChecked:
                    return
                sender.setTristate(False)
            self.updateData.emit(self)

    class IDValuePropertyDecoder(ValuePropertyDecoder):
        """
        A ValuePropertyDecoder for ID-type fields (movement ID, event ID, etc.).
        Adds a compact "Next Free" button that scans all sprites in the current
        level to find the lowest unused ID of the same id_type.
        """

        def __init__(self, title, bit, max, comment, id_type, layout, row, editor=None):
            super().__init__(title, bit, max, comment, layout, row, editor)
            self.id_type = id_type

            # Wrap the spinbox and button in a container so both fit in column 1.
            #btn = QtWidgets.QPushButton('Next Free')
            # btn.setFocusPolicy(Qt.ClickFocus)
            # btn.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            # btn.clicked.connect(self.HandleNextFree)
            # self.nextFreeBtn = btn

            # Remove the bare spinbox from the layout and replace it with
            # [spinbox | Next Free] in a horizontal container.
            layout.removeWidget(self.widget)
            container = QtWidgets.QWidget()
            hbox = QtWidgets.QHBoxLayout(container)
            hbox.setContentsMargins(0, 0, 0, 0)
            hbox.setSpacing(4)
            hbox.addWidget(self.widget)
            #hbox.addWidget(btn)
            layout.addWidget(container, row, 1)

        def HandleNextFree(self):
            used = self.collect_used_ids()
            for i in range(1, self.widget.maximum() + 2):
                if i not in used:
                    self.widget.setValue(i)
                    break

        def collect_used_ids(self):
            used = set()
            if globals.Area is None:
                return used
            for sprite in globals.Area.sprites:
                if not (0 <= sprite.type < len(globals.Sprites)):
                    continue
                sdef = globals.Sprites[sprite.type]
                if sdef is None:
                    continue
                for f in sdef.fields:
                    if f[0] == 2 and len(f) > 5 and f[5] == self.id_type:
                        val = extract_field_value(sprite.spritedata, f[2])
                        if val > 0:
                            used.add(val)
            return used

    class StrybblePropertyDecoder(PropertyDecoder):
        def __init__(self, title, bit, comment, layout, row, editor=None):
            super().__init__()
            self._base_comment = comment
            self.bit = bit
            num_bits = bit[1] - bit[0]
            self.num_chars = num_bits // 6

            self.label = QtWidgets.QLabel(title + ':')
            self.widget = QtWidgets.QLineEdit()
            self.widget.setFocusPolicy(Qt.ClickFocus)

            if self.num_chars < 1:
                self.widget.setEnabled(False)
                self.widget.setPlaceholderText('field too small')
                self.label.setEnabled(False)
            else:
                self._placeholder = 'Write up to {} character{}'.format(
                    self.num_chars, '' if self.num_chars == 1 else 's')
                self.widget.setMaxLength(self.num_chars)
                self.widget.setPlaceholderText(self._placeholder)

            if comment is not None:
                self.label.setToolTip(comment)
                self.widget.setToolTip(comment)

            self.widget.textChanged.connect(self.HandleTextChanged)

            layout.addWidget(self.label, row, 0, Qt.AlignRight)
            layout.addWidget(self.widget, row, 1)

        def _show_error(self, message):
            self.widget.setStyleSheet(
                'QLineEdit { border: 2px solid red; }')
            self.widget.setToolTip(message)
            if self._base_comment is not None:
                self.label.setToolTip(
                    '<b>[name]</b>: [note]'.replace('[name]', self.label.text()[:-1]).replace('[note]', message))

        def _clear_error(self):
            self.widget.setStyleSheet('')
            if self._base_comment is not None:
                self.widget.setToolTip(self._base_comment)
                self.label.setToolTip(self._base_comment)
            else:
                self.widget.setToolTip('')
                self.label.setToolTip('')

        def _validate_text(self, text):
            if self.num_chars < 1:
                return False
            if not text:
                self._clear_error()
                return True
            try:
                strybble_encode(text, self.num_chars)
            except StrybbleEncodeError as e:
                self._show_error(str(e))
                return False
            self._clear_error()
            return True

        def update(self, data):
            self.checkReq(data)
            if self.num_chars < 1:
                return
            value = self.retrieve(data)
            hex_len = self.num_chars * 6 // 4
            hex_str = format(value, '0{}x'.format(hex_len))
            try:
                text = strybble_decode(hex_str, self.num_chars)
            except Exception:
                text = ''
            self.widget.blockSignals(True)
            self.widget.setText(text)
            self.widget.blockSignals(False)

        def setMixed(self, mixed):
            if self.num_chars < 1:
                return
            self.widget.blockSignals(True)
            if mixed:
                self.widget.setPlaceholderText('—')
                self.widget.clear()
            else:
                self.widget.setPlaceholderText(self._placeholder)
                self._clear_error()
            self.widget.blockSignals(False)

        def assign(self, data):
            if self.num_chars < 1:
                return data
            text = self.widget.text()
            if not text and self.widget.placeholderText():
                return data
            if not self._validate_text(text):
                return data
            hex_str = strybble_encode(text, self.num_chars)
            value = int(hex_str, 16)
            return self.insertvalue(data, value)

        def HandleTextChanged(self, text):
            if self.num_chars < 1:
                return
            if self._validate_text(text):
                self.updateData.emit(self)

    class DualboxPropertyDecoder(PropertyDecoder):
        """
        Class that decodes/encodes sprite data to/from a dualbox (two radio buttons)
        """

        def __init__(self, title1, title2, bit, comment, layout, row, editor=None):
            """
            Creates the widget
            """
            super().__init__()

            self.bit = bit
            self.layout = layout
            self.row = row

            self.buttons = [QtWidgets.QRadioButton(), QtWidgets.QRadioButton()]

            for button in self.buttons:
                button.clicked.connect(self.HandleClick)

            label1 = QtWidgets.QLabel(title1)
            label2 = QtWidgets.QLabel(title2)

            L = QtWidgets.QHBoxLayout()
            L.addStretch(1)
            L.addWidget(label1)
            L.addWidget(self.buttons[0])
            L.addWidget(QtWidgets.QLabel("|"))
            L.addWidget(self.buttons[1])
            L.addWidget(label2)
            L.addStretch(1)
            L.setContentsMargins(0, 0, 0, 0)

            widget = QtWidgets.QWidget()
            widget.setLayout(L)

            layout.addWidget(widget, row, 0, 1, 3)

        def update(self, data):
            """
            Updates the value shown by the widget
            """
            self.checkReq(data)
            value = self.retrieve(data) & 1

            self.buttons[value].setChecked(True)
            self.buttons[not value].setChecked(False)

        def assign(self, data):
            """
            Assigns the selected value to the data
            """
            value = self.buttons[1].isChecked()
            return self.insertvalue(data, value)

        def HandleClick(self, clicked=False):
            """
            Handles clicks on the radio buttons
            """
            self.updateData.emit(self)

    class MultiDualboxPropertyDecoder(PropertyDecoder):
        """
        Class that decodes/encodes sprite data to/from a row of dualboxes
        """

        def __init__(self, title1, title2, bit, comment, layout, row, editor=None):
            """
            Creates the widget
            """
            super().__init__()

            self.bit = bit
            self.layout = layout
            self.row = row
            self.startbit = bit[0] if isinstance(bit, tuple) else bit
            self.bitnum = bit[1] - bit[0] if isinstance(bit, tuple) else 1

            self.widgets = []
            DualboxLayout = QtWidgets.QGridLayout()
            DualboxLayout.setContentsMargins(0, 0, 0, 0)

            for i in range(self.bitnum):
                buttons = [QtWidgets.QRadioButton(), QtWidgets.QRadioButton()]
                buttons[0].clicked.connect(self.HandleClicked)
                buttons[0].setAutoExclusive(False)
                buttons[1].clicked.connect(self.HandleClicked)
                buttons[1].setAutoExclusive(False)

                buttons[0].setChecked(True)

                button_group = QtWidgets.QButtonGroup()
                button_group.addButton(buttons[0], 1)
                button_group.addButton(buttons[1], 2)

                self.widgets.append(button_group)

                DualboxLayout.addWidget(buttons[0], 0, i)
                DualboxLayout.addWidget(buttons[1], 1, i)

            label1 = QtWidgets.QLabel(title1)
            label2 = QtWidgets.QLabel(title2)

            labels = QtWidgets.QGridLayout()
            labels.addWidget(label1, 0, 0, Qt.AlignRight)
            labels.addWidget(label2, 1, 0, Qt.AlignRight)

            labels_widget = QtWidgets.QWidget()
            labels_widget.setLayout(labels)

            dualbox_widget = QtWidgets.QWidget()
            dualbox_widget.setLayout(DualboxLayout)

            layout.addWidget(labels_widget, row, 0, Qt.AlignRight)
            layout.addWidget(dualbox_widget, row, 1, 1, 2)

        def HandleClicked(self, _):
            """
            Handles clicks on the radiobutton
            """
            self.updateData.emit(self)

        def update(self, data):
            """
            Updates the value shown by the widget
            """
            self.checkReq(data)
            value = self.retrieve(data)

            for i in range(self.bitnum - 1, -1, -1):
                self.widgets[i].button(2).setChecked(value & 1)
                value >>= 1

        def assign(self, data):
            """
            Assigns the checkbox states to the data
            """
            value = 0

            for i in range(self.bitnum):
                value = (value << 1) | (self.widgets[i].checkedId() - 1)

            return self.insertvalue(data, value)

    def _make_field_decoder(self, f, layout, row):
        """
        Instantiate the appropriate PropertyDecoder subclass for field tuple f,
        adding its widget(s) to layout at the given row. Returns the decoder, or
        None if the field type is unrecognised.
        """
        required = f[7] if len(f) > 7 else None
        if f[0] == 0:
            nf = SpriteEditorWidget.CheckboxPropertyDecoder(
                f[1], f[2], f[3], f[4], layout, row, editor=self)
        elif f[0] == 1:
            nf = SpriteEditorWidget.ListPropertyDecoder(
                f[1], f[2], f[3], f[4], layout, row, editor=self)
        elif f[0] == 2:
            id_type = f[5] if len(f) > 5 else None
            if id_type is not None:
                nf = SpriteEditorWidget.IDValuePropertyDecoder(
                    f[1], f[2], f[3], f[4], id_type, layout, row, editor=self)
            else:
                nf = SpriteEditorWidget.ValuePropertyDecoder(
                    f[1], f[2], f[3], f[4], layout, row, editor=self)
        elif f[0] == 3:
            nf = SpriteEditorWidget.BitfieldPropertyDecoder(
                f[1], f[2], f[3], f[4], layout, row, editor=self)
        elif f[0] == 4:
            nf = SpriteEditorWidget.StrybblePropertyDecoder(
                f[1], f[2], f[3], layout, row, editor=self)
        elif f[0] == 5:
            nf = SpriteEditorWidget.DualboxPropertyDecoder(
                f[1], f[2], f[3], f[4], layout, row, editor=self)
        elif f[0] == 7:
            nf = SpriteEditorWidget.MultiDualboxPropertyDecoder(
                f[1], f[2], f[3], f[4], layout, row, editor=self)
        else:
            return None
        nf.required = required
        nf.layout = layout
        nf.row = row

        # Place a native OS info icon next to the label for fields with
        # comments, and ensure the label itself also shows the tooltip
        comment = f[3] if f[0] == 4 else (f[4] if len(f) > 4 else None)
        if comment is not None and f[0] not in (5, 7) and setting('ShowInfoIcons', True):
            item = layout.itemAtPosition(row, 0)
            if item is not None:
                label = item.widget()
                if isinstance(label, QtWidgets.QLabel):
                    label.setToolTip(comment)
                    layout.removeWidget(label)
                    container = QtWidgets.QWidget()
                    hbox = QtWidgets.QHBoxLayout(container)
                    hbox.setContentsMargins(0, 0, 0, 0)
                    hbox.setSpacing(3)
                    hbox.addStretch()
                    hbox.addWidget(label)
                    icon = QtWidgets.QLabel()
                    screen = QtWidgets.QApplication.primaryScreen()
                    dpr = screen.devicePixelRatio() if screen else 1
                    sz = max(1, int(14 * dpr))
                    pixmap = QtWidgets.QApplication.style().standardIcon(
                        QtWidgets.QStyle.SP_MessageBoxInformation).pixmap(sz, sz)
                    pixmap.setDevicePixelRatio(dpr)
                    icon.setPixmap(pixmap)
                    icon.setFixedSize(14, 14)
                    icon.setToolTip(comment)
                    hbox.addWidget(icon)
                    layout.addWidget(container, row, 0, Qt.AlignRight)
        return nf

    # ------------------------------------------------------------------
    # Multi-select helpers
    # ------------------------------------------------------------------

    def _computeMergedData(self, data_list):
        """
        Merge a list of 12-byte spritedata arrays.
        Returns (merged, diff) where bits that differ across items are 1 in diff
        and 0 in merged; bits that agree keep their value in merged.
        """
        if not data_list:
            return bytes(12), bytes(12)
        first = bytearray(data_list[0])
        diff = bytearray(12)
        for data in data_list[1:]:
            for i in range(12):
                diff[i] |= first[i] ^ data[i]
        for i in range(12):
            first[i] &= ~diff[i]
        return bytes(first), bytes(diff)

    def _fieldHasDiff(self, decoder, diff):
        """True if any bit covered by decoder is set in diff (bytes-like)."""
        diff = bytearray(diff)
        if isinstance(decoder, SpriteEditorWidget.BitfieldPropertyDecoder):
            for i in range(decoder.bitnum):
                idx = i + decoder.startbit
                bn, bi = idx // 8, idx % 8
                if bn < len(diff) and (diff[bn] >> (7 - bi)) & 1:
                    return True
        elif hasattr(decoder, 'bit'):
            bit = decoder.bit
            pairs = range(bit[0], bit[1] + 1) if isinstance(bit, tuple) else [bit]
            for n in pairs:
                bn = (n - 1) >> 3
                bo = 7 - ((n - 1) & 7)
                if bn < len(diff) and (diff[bn] >> bo) & 1:
                    return True
        return False

    def _applyMixedStates(self, diff):
        """Apply mixed/non-mixed state to all field decoders based on diff mask."""
        for decoder in self.fields:
            if isinstance(decoder, SpriteEditorWidget.BitfieldPropertyDecoder):
                decoder.setMixedFromDiffMask(diff)
            elif hasattr(decoder, 'setMixed'):
                decoder.setMixed(self._fieldHasDiff(decoder, diff))

    def _updateRawDisplay(self, data):
        self.raweditor.setText('%02x%02x %02x%02x %02x%02x %02x%02x %02x%02x %02x%02x' % (
            data[0], data[1], data[2], data[3],
            data[4], data[5], data[6], data[7],
            data[8], data[9], data[10], data[11],
        ))
        self.raweditor.setStyleSheet('')

    def setMultipleSprites(self, items):
        """Set up the editor for multiple actors of the SAME type."""
        self.setSprite(items[0].type, reset=True)
        # setSprite cleared multi-mode; set it up now
        self._multiMode = True
        self._mixedTypeMode = False
        self._multiItems = list(items)
        self._setPreviewControlsVisible(False)

        merged, diff = self._computeMergedData([it.spritedata for it in items])
        self.data = merged
        self._multiBaseline = merged.hex()

        self.UpdateFlag = True
        self._updateRawDisplay(merged)
        for f in self.fields:
            f.update(merged)
        self.UpdateFlag = False

        self._applyMixedStates(diff)

        layers = set(it.layer for it in items)
        self._set_layer_value_multi(layers)

        states = set(it.initialState for it in items)
        self._set_initialstate_value_multi(states)

    def setMixedActors(self, items):
        """Set up the editor for multiple actors of DIFFERENT types (raw only)."""
        # Clear the layout without triggering setSprite's type-equality guard
        self._multiMode = True
        self._mixedTypeMode = True
        self._multiItems = list(items)
        self.spritetype = -1

        layout = self.editorlayout
        if self._tabWidget is not None:
            for w in (self.initialState, self.activeLayer):
                w.setParent(self)
                w.setVisible(False)
            
            layout.removeWidget(self._tabWidget)
            self._tabWidget.hide()
            self._tabWidget.deleteLater()
            self._tabWidget = None
        for r in range(2, layout.rowCount()):
            for c in range(layout.columnCount()):
                item = layout.itemAtPosition(r, c)
                if item is not None:
                    w = item.widget()
                    layout.removeWidget(w)
                    w.setParent(None)
        self.fields = []

        self.spriteLabel.setText(f'<b>Editing {len(items)} actors</b>')
        self.noteBox.setVisible(False)
        self.noteButton.setVisible(False)
        self.relatedObjFilesButton.setVisible(False)
        self._setPreviewControlsVisible(False)

        merged, _ = self._computeMergedData([it.spritedata for it in items])
        self.data = merged
        self._multiBaseline = merged.hex()
        self._updateRawDisplay(merged)

    # ------------------------------------------------------------------

    def setSprite(self, type, reset=False):
        """
        Change the sprite type used by the data editor
        """
        # Entering single-select mode: clear multi-mode and restore widget state.
        self._multiMode = False
        self._mixedTypeMode = False
        self._multiItems = []
        self.initialState.blockSignals(True)
        self.initialState.setMinimum(0)
        self.initialState.setSpecialValueText('')
        self.initialState.blockSignals(False)
        self._setPreviewControlsVisible(movementpreview.has_movement_field(type))

        if (self.spritetype == type) and not reset: return

        self.spritetype = type
        if isinstance(type, str):
            sprite = globals.CustomSpriteDefinitions.get(type)
        elif isinstance(type, int) and 0 <= type < len(globals.Sprites) and globals.Sprites[type] is not None:
            sprite = globals.Sprites[type]
        else:
            sprite = None

        layout = self.editorlayout
        self._behaviorGrid = None

        # Explicitly clean up any categorized tab widget from a previous call
        # before the general cleanup loop, to prevent it from briefly appearing
        # as a floating top-level window.
        if self._tabWidget is not None:
            # Reparent shared widgets out of the tab so they survive deletion
            for w in (self.initialState, self.activeLayer):
                w.setParent(self)
                w.setVisible(False)
            layout.removeWidget(self._tabWidget)
            self._tabWidget.hide()
            self._tabWidget.deleteLater()
            self._tabWidget = None

        # Remove all widgets from rows 2+ of the flat grid layout
        for r in range(2, layout.rowCount()):
            for c in range(0, layout.columnCount()):
                item = layout.itemAtPosition(r, c)
                if item is not None:
                    widget = item.widget()
                    layout.removeWidget(widget)
                    widget.setParent(None)

        if sprite is None:
            self.spriteLabel.setText('<b>Unidentified/Unknown Actor ([id])</b>'.replace('[id]', str(type)))
            self.noteBox.setVisible(False)
            self.noteButton.setVisible(False)

            self.raweditor.setVisible(True)
            if len(self.fields) > 0:
                self.fields = []

        else:
            display_id = str(type)
            if isinstance(type, int) and type >= 1000:
                string_id = globals.Level.id_manager.int_to_string.get(type)
                if string_id:
                    display_id = string_id

            self.spriteLabel.setText('<b>Actor [id]:<br>[name]</b>'.replace('[id]', str(display_id)).replace('[name]', str(sprite.name)))

            self.notes = sprite.notes

            if sprite.notes is not None:
                if setting('ShowActorNotes', True):
                    self.notesDisplay.setHtml(sprite.notes)
                    self.noteBox.setVisible(True)
                    self.noteButton.setVisible(False)
                else:
                    self.noteButton.setVisible(True)
                    self.noteBox.setVisible(False)
            else:
                self.noteBox.setVisible(False)
                self.noteButton.setVisible(False)

            self.relatedObjFilesButton.setVisible(sprite.relatedObjFiles is not None)
            self.relatedObjFiles = sprite.relatedObjFiles

            fields = []

            if globals.CategorizedSpriteData and sprite.fields:
                # --- Categorized (tabbed) mode ---
                # Group fields by their XML-defined category (f[6]).  Builtin categories
                # appear first in a fixed order; any custom mod categories follow
                # alphabetically; uncategorized fields (no category attribute) come last.

                # Collect categories needed by layer/initialstate overrides
                override_cats = set()
                if sprite.layer_defs:
                    for ld in sprite.layer_defs:
                        cat = ld.get('category')
                        override_cats.add(cat if cat else 'uncategorized')
                if sprite.initialstate_def:
                    cat = sprite.initialstate_def.get('category')
                    override_cats.add(cat if cat else 'uncategorized')

                _BUILTIN = [('behavior', 'Behavior'), ('movement', 'Movement'), ('events', 'Events')]
                _BUILTIN_KEYS = {k for k, _ in _BUILTIN}

                seen: dict = {}
                for f in sprite.fields:
                    cat = f[6] if len(f) > 6 and f[6] else 'uncategorized'
                    seen.setdefault(cat, None)
                for cat in override_cats:
                    seen.setdefault(cat, None)

                CATEGORY_ORDER = []
                for key, label in _BUILTIN:
                    if key in seen:
                        CATEGORY_ORDER.append((key, label))
                for key in seen:
                    if key not in _BUILTIN_KEYS and key != 'uncategorized':
                        CATEGORY_ORDER.append((key, key.capitalize()))
                if 'uncategorized' in seen:
                    CATEGORY_ORDER.append(('uncategorized', 'Uncategorized'))

                grouped: dict = {key: [] for key, _ in CATEGORY_ORDER}
                for f in sprite.fields:
                    cat = f[6] if len(f) > 6 and f[6] else 'uncategorized'
                    grouped[cat].append(f)

                class _CurrentTabSizedTabWidget(QtWidgets.QTabWidget):
                    def sizeHint(self):
                        w = self.currentWidget()
                        if w is None:
                            return super().sizeHint()
                        page = w.sizeHint()
                        bar = self.tabBar().sizeHint()
                        return QtCore.QSize(
                            max(page.width(), bar.width()),
                            page.height() + bar.height()
                        )

                tabWidget = _CurrentTabSizedTabWidget()
                tabWidget.setTabBarAutoHide(True)
                self._tabWidget = tabWidget
                self._categoryGrids = {}

                for cat_key, cat_label in CATEGORY_ORDER:
                    cat_fields = grouped[cat_key]
                    if not cat_fields and cat_key not in override_cats:
                        continue
                    tab = QtWidgets.QWidget()
                    grid = QtWidgets.QGridLayout(tab)
                    grid.setContentsMargins(4, 4, 4, 4)
                    if cat_key == 'behavior':
                        self._behaviorGrid = grid
                    self._categoryGrids[cat_key] = grid
                    tab_row = 0
                    for f in cat_fields:
                        nf = self._make_field_decoder(f, grid, tab_row)
                        if nf is None:
                            continue
                        nf.updateData.connect(self.HandleFieldUpdate)
                        fields.append(nf)
                        tab_row += 1
                    tabWidget.addTab(tab, cat_label)

                # Normalize column widths across all categorized tabs so labels
                # and input widgets don't jump horizontally when switching tabs.
                _tab_grids = [
                    tabWidget.widget(i).layout()
                    for i in range(tabWidget.count())
                    if isinstance(tabWidget.widget(i).layout(), QtWidgets.QGridLayout)
                ]
                _max_c0 = 0
                _max_c1 = 0
                for g in _tab_grids:
                    for r in range(g.rowCount()):
                        i0 = g.itemAtPosition(r, 0)
                        i1 = g.itemAtPosition(r, 1)
                        if i0 is not None and i0 is i1:
                            continue
                        if i0 is not None and i0.widget() is not None:
                            _max_c0 = max(_max_c0, i0.widget().sizeHint().width())
                        if i1 is not None and i1.widget() is not None:
                            _max_c1 = max(_max_c1, i1.widget().sizeHint().width())
                for g in _tab_grids:
                    g.setColumnMinimumWidth(0, _max_c0)
                    g.setColumnMinimumWidth(1, _max_c1)
                    g.setColumnStretch(1, 1)

                def _on_tab_changed():
                    QtCore.QTimer.singleShot(0, globals.mainWindow._lockFloatingHeight)
                tabWidget.currentChanged.connect(_on_tab_changed)

                self.fields = fields
                layout.addWidget(tabWidget, 2, 0, 1, 2)
                row = 3

            else:
                # --- Flat mode (default, identical to original behaviour) ---
                row = 2
                for f in sprite.fields:
                    nf = self._make_field_decoder(f, layout, row)
                    if nf is None:
                        continue
                    nf.updateData.connect(self.HandleFieldUpdate)
                    fields.append(nf)
                    row += 1
                self.fields = fields

            # Determine which grid each override section belongs in.
            # In categorized mode the override's category attribute selects
            # the tab; otherwise everything goes to the default grid.
            def _grid_for_override(defn):
                if defn is not None and globals.CategorizedSpriteData and hasattr(self, '_categoryGrids'):
                    cat = defn.get('category')
                    key = cat if cat else 'uncategorized'
                    if key in self._categoryGrids:
                        return self._categoryGrids[key]
                return self._behaviorGrid if self._behaviorGrid is not None else layout

            layer_defn = sprite.layer_defs[0] if sprite.layer_defs else None
            is_defn = sprite.initialstate_def

            layer_is_custom = bool(sprite.layer_defs)
            initialstate_is_custom = sprite.initialstate_def is not None

            # Customised sections go in their category-specific grid
            if layer_is_custom:
                target = _grid_for_override(layer_defn)
                trow = target.rowCount()
                self._make_layer_section(target, trow, sprite)

            if initialstate_is_custom:
                target = _grid_for_override(is_defn)
                trow = target.rowCount()
                self._make_initialstate_section(target, trow, sprite)

            # Default sections always go to the behaviour/default grid
            default_grid = self._behaviorGrid if self._behaviorGrid is not None else layout
            trow = default_grid.rowCount()

            if not (layer_is_custom and initialstate_is_custom):
                default_grid.addWidget(createHorzLine(), trow, 0, 1, 2); trow += 1

            if not layer_is_custom:
                trow = self._make_layer_section(default_grid, trow, sprite)
            if not initialstate_is_custom:
                self._make_initialstate_section(default_grid, trow, sprite)

    # ------------------------------------------------------------------
    # Layer / Initial State override helpers
    # ------------------------------------------------------------------

    def _build_override_widget(self, defn, layout, row, default_label, default_range):
        comment = defn.get('comment')
        widget_type = defn.get('type', 'value')

        if widget_type == 'dualbox':
            title1 = defn.get('title1', '')
            title2 = defn.get('title2', '')

            label1 = QtWidgets.QLabel(title1 + ':')
            label2 = QtWidgets.QLabel(title2 + ':')

            buttons = [QtWidgets.QRadioButton(), QtWidgets.QRadioButton()]
            buttons[0].setChecked(True)

            L = QtWidgets.QHBoxLayout()
            L.setContentsMargins(0, 0, 0, 0)
            L.addWidget(label1)
            L.addWidget(buttons[0])
            L.addWidget(QtWidgets.QLabel("|"))
            L.addWidget(buttons[1])
            L.addWidget(label2)
            L.addStretch(1)

            widget = QtWidgets.QWidget()
            widget.setLayout(L)
            widget._buttons = buttons

            if comment:
                widget.setToolTip(comment)

            layout.addWidget(widget, row, 0, 1, 2)
            return widget

        title = (defn.get('title') or default_label).rstrip(':')
        label = QtWidgets.QLabel(title + ':')
        if comment:
            label.setToolTip(comment)

        if widget_type == 'list':
            widget = QtWidgets.QComboBox()
            widget.setFocusPolicy(Qt.ClickFocus)
            for val, text in (defn.get('entries') or []):
                widget.addItem(text, val)
            if comment:
                widget.setToolTip(comment)
        elif widget_type == 'checkbox':
            widget = QtWidgets.QCheckBox()
            widget.setFocusPolicy(Qt.ClickFocus)
            if comment:
                widget.setToolTip(comment)
        else:
            widget = QtWidgets.QSpinBox()
            widget.setFocusPolicy(Qt.ClickFocus)
            widget.setRange(*default_range)
            if comment:
                widget.setToolTip(comment)

        layout.addWidget(label, row, 0, Qt.AlignRight)
        layout.addWidget(widget, row, 1)
        return widget

    def _override_set_value(self, widget, value):
        if hasattr(widget, '_buttons'):
            widget._buttons[bool(value) & 1].setChecked(True)
        elif isinstance(widget, QtWidgets.QComboBox):
            idx = widget.findData(value)
            if idx >= 0:
                widget.setCurrentIndex(idx)
            else:
                # Value doesn't match any entry; default to first entry
                widget.setCurrentIndex(0)
        elif isinstance(widget, QtWidgets.QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QtWidgets.QSpinBox):
            widget.setValue(value)

    def _override_get_value(self, widget):
        if hasattr(widget, '_buttons'):
            return 1 if widget._buttons[1].isChecked() else 0
        elif isinstance(widget, QtWidgets.QComboBox):
            val = widget.currentData()
            return val if val is not None else 0
        elif isinstance(widget, QtWidgets.QCheckBox):
            return 1 if widget.isChecked() else 0
        elif isinstance(widget, QtWidgets.QSpinBox):
            return widget.value()
        return 0

    def _make_layer_section(self, layout, row, sprite):
        layer_defs = sprite.layer_defs if sprite else []
        if layer_defs:
            self._layerWidgets = []
            for defn in layer_defs:
                # Each layer definition may target a different category tab
                target = layout
                if globals.CategorizedSpriteData and hasattr(self, '_categoryGrids'):
                    cat = defn.get('category')
                    key = cat if cat else 'uncategorized'
                    if key in self._categoryGrids:
                        target = self._categoryGrids[key]
                trow = target.rowCount()
                mask = defn.get('mask')
                if mask is not None:
                    max_val = mask_max_value(mask)
                    default_range = (0, max_val)
                else:
                    default_range = (0, 255)
                widget = self._build_override_widget(defn, target, trow, 'Layer', default_range)
                self._layerWidgets.append((widget, mask))
                if hasattr(widget, '_buttons'):
                    for b in widget._buttons:
                        b.clicked.connect(self._on_layer_changed)
                elif isinstance(widget, QtWidgets.QComboBox):
                    widget.activated.connect(self._on_layer_changed)
                elif isinstance(widget, QtWidgets.QCheckBox):
                    widget.toggled.connect(self._on_layer_changed)
                elif isinstance(widget, QtWidgets.QSpinBox):
                    widget.valueChanged.connect(self._on_layer_changed)
        else:
            self._layerWidgets = []
            layout.addWidget(QtWidgets.QLabel('Layer:'), row, 0, Qt.AlignRight)
            layout.addWidget(self.activeLayer, row, 1)
            self.activeLayer.setVisible(True)
            row += 1
        return row

    def _make_initialstate_section(self, layout, row, sprite):
        defn = sprite.initialstate_def if sprite else None
        if defn is not None:
            self._initialStateWidget = self._build_override_widget(defn, layout, row, 'Initial State', (0, 255))
            if hasattr(self._initialStateWidget, '_buttons'):
                for b in self._initialStateWidget._buttons:
                    b.clicked.connect(lambda: self._on_initialstate_changed(self._override_get_value(self._initialStateWidget)))
            elif isinstance(self._initialStateWidget, QtWidgets.QComboBox):
                self._initialStateWidget.activated.connect(
                    lambda idx: self._on_initialstate_changed(self._initialStateWidget.itemData(idx)))
            elif isinstance(self._initialStateWidget, QtWidgets.QCheckBox):
                self._initialStateWidget.toggled.connect(
                    lambda chk: self._on_initialstate_changed(1 if chk else 0))
            elif isinstance(self._initialStateWidget, QtWidgets.QSpinBox):
                self._initialStateWidget.valueChanged.connect(self._on_initialstate_changed)
        else:
            self._initialStateWidget = None
            layout.addWidget(QtWidgets.QLabel('Initial State:'), row, 0, Qt.AlignRight)
            layout.addWidget(self.initialState, row, 1)
            self.initialState.setVisible(True)

    def setLayerOverrideValue(self, layer_byte):
        if self._layerWidgets:
            for widget, mask in self._layerWidgets:
                widget.blockSignals(True)
                if mask is not None:
                    val = extract_mask_value(layer_byte, mask)
                else:
                    val = layer_byte
                self._override_set_value(widget, val)
                widget.blockSignals(False)
        else:
            self.activeLayer.blockSignals(True)
            self.activeLayer.setCurrentIndex(layer_byte if 0 <= layer_byte <= 2 else -1)
            self.activeLayer.blockSignals(False)

    def setInitialStateOverrideValue(self, value):
        if self._initialStateWidget is not None:
            self._override_set_value(self._initialStateWidget, value)
        else:
            self.initialState.blockSignals(True)
            self.initialState.setValue(value)
            self.initialState.blockSignals(False)

    def _on_layer_changed(self, *_args):
        layer_byte = self._get_layer_byte_from_widgets()
        if layer_byte < 0:
            return
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.SpriteLayerUpdated(layer_byte)

    def _get_layer_byte_from_widgets(self):
        if not self._layerWidgets:
            return -1
        layer_byte = 0
        for widget, mask in self._layerWidgets:
            val = self._override_get_value(widget)
            if mask is not None:
                layer_byte = insert_mask_value(layer_byte, mask, val)
            else:
                layer_byte = val
        return layer_byte

    def _on_initialstate_changed(self, value):
        if value < 0:
            return
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.SpriteInitialStateUpdated(value)

    def _set_layer_value_multi(self, values):
        if self._layerWidgets:
            for widget, mask in self._layerWidgets:
                widget.blockSignals(True)
                if mask is not None:
                    sub_vals = {extract_mask_value(v, mask) for v in values}
                else:
                    sub_vals = values
                is_mixed = len(sub_vals) != 1
                if is_mixed:
                    if isinstance(widget, QtWidgets.QComboBox):
                        widget.setCurrentIndex(-1)
                    elif isinstance(widget, QtWidgets.QCheckBox):
                        widget.setTristate(True)
                        widget.setCheckState(Qt.PartiallyChecked)
                else:
                    if isinstance(widget, QtWidgets.QCheckBox):
                        widget.setTristate(False)
                    self._override_set_value(widget, next(iter(sub_vals)))
                widget.blockSignals(False)
        else:
            self.activeLayer.blockSignals(True)
            self.activeLayer.setCurrentIndex(next(iter(values)) if len(values) == 1 else -1)
            self.activeLayer.blockSignals(False)

    def _set_initialstate_value_multi(self, values):
        if self._initialStateWidget is not None:
            is_mixed = len(values) != 1
            widget = self._initialStateWidget
            widget.blockSignals(True)
            if is_mixed:
                if isinstance(widget, QtWidgets.QComboBox):
                    widget.setCurrentIndex(-1)
                elif isinstance(widget, QtWidgets.QCheckBox):
                    widget.setTristate(True)
                    widget.setCheckState(Qt.PartiallyChecked)
            else:
                if isinstance(widget, QtWidgets.QCheckBox):
                    widget.setTristate(False)
                self._override_set_value(widget, next(iter(values)))
            widget.blockSignals(False)
        else:
            self.initialState.blockSignals(True)
            if len(values) == 1:
                self.initialState.setMinimum(0)
                self.initialState.setSpecialValueText('')
                self.initialState.setValue(next(iter(values)))
            else:
                self.initialState.setMinimum(-1)
                self.initialState.setSpecialValueText('—')
                self.initialState.setValue(-1)
            self.initialState.blockSignals(False)

    def update(self):
        """
        Updates all the fields to display the appropriate info
        """
        self.UpdateFlag = True

        data = self.data

        self.raweditor.setText('%02x%02x %02x%02x %02x%02x %02x%02x %02x%02x %02x%02x' % (
            data[0], data[1], data[2], data[3],
            data[4], data[5], data[6], data[7],
            data[8], data[9], data[10], data[11],
        ))

        self.raweditor.setStyleSheet('')

        # Go through all the data
        for f in self.fields:
            f.update(data)

        self.UpdateFlag = False

    def ShowNoteTooltip(self):
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), self.notes, self)

    def HandlePreviewMovement(self, checked):
        if not checked:
            movementpreview.stop('single')
            return

        sprite = globals.mainWindow.selObj
        error = movementpreview.start(sprite) if isinstance(sprite, SpriteItem) else 'Select a single actor first.'
        if error:
            self.stopMovementPreview()
            QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), error, self.previewMovementButton)

    def stopMovementPreview(self):
        """Stops a running single-actor preview (a "preview all" keeps going)."""
        movementpreview.stop('single')
        self._syncPreviewButton()

    def _syncPreviewButton(self):
        self.previewMovementButton.blockSignals(True)
        self.previewMovementButton.setChecked(movementpreview.is_running('single'))
        self.previewMovementButton.blockSignals(False)

    def _setPreviewControlsVisible(self, visible):
        self.previewMovementButton.setVisible(visible)
        self.previewSpeedBox.setVisible(visible)
        self.previewOptionsButton.setVisible(visible)

    def ShowRelatedObjFilesTooltip(self):
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), self.relatedObjFiles, self)

    def HandleFieldUpdate(self, field):
        """
        Triggered when a field's data is updated
        """
        if self.UpdateFlag: return

        if self._multiMode:
            # Apply the field's new widget value to each actor's individual spritedata,
            # leaving all other bits in each actor untouched.
            globals.UndoManager.begin_compound('Change Actor Properties')
            for item in self._multiItems:
                new_data = field.assign(item.spritedata)
                if new_data != item.spritedata:
                    globals.UndoManager.push(
                        undomanager.SpriteDataChangedCommand(item, item.spritedata, new_data))
                    # UpdateListItem/UpdateDynamicSizing handled by command.redo()
            globals.UndoManager.end_compound()
            # Recompute merged display
            merged, diff = self._computeMergedData([it.spritedata for it in self._multiItems])
            self.data = merged
            self._multiBaseline = merged.hex()
            self.UpdateFlag = True
            self._updateRawDisplay(merged)
            for f in self.fields:
                if f != field:
                    f.update(merged)
            self.UpdateFlag = False
            self._applyMixedStates(diff)
            return

        data = field.assign(self.data)
        self.data = data

        self.raweditor.setText('%02x%02x %02x%02x %02x%02x %02x%02x %02x%02x %02x%02x' % (
            data[0], data[1], data[2], data[3],
            data[4], data[5], data[6], data[7],
            data[8], data[9], data[10], data[11],
        ))

        self.raweditor.setStyleSheet('')

        for f in self.fields:
            if f != field:
                f.update(data)

        self.DataUpdate.emit(data)

    def HandleRawDataEdited(self, text):
        """
        Triggered when the raw data textbox is edited
        """
        raw = text.replace(' ', '')
        if len(raw) != 24:
            self.raweditor.setStyleSheet('QLineEdit { background-color: #ffd2d2; color: #1b1b1e; }')
            return
        try:
            data = bytes.fromhex(raw)
        except ValueError:
            self.raweditor.setStyleSheet('QLineEdit { background-color: #ffd2d2; color: #1b1b1e; }')
            return

        self.raweditor.setStyleSheet('')

        if self._multiMode:
            # Partial-nybble edit: only apply the specific character positions that
            # the user changed (relative to the baseline) to each actor's spritedata.
            new_hex = raw.lower()
            old_hex = self._multiBaseline
            changed = [(i, int(new_hex[i], 16))
                       for i in range(24) if new_hex[i] != old_hex[i]]
            if not changed:
                return
            globals.UndoManager.begin_compound('Change Actor Raw Data')
            for item in self._multiItems:
                buf = bytearray(item.spritedata)
                for pos, nv in changed:
                    bi = pos // 2
                    if pos % 2 == 0:
                        buf[bi] = (nv << 4) | (buf[bi] & 0x0F)
                    else:
                        buf[bi] = (buf[bi] & 0xF0) | nv
                new_data = bytes(buf)
                if new_data != item.spritedata:
                    globals.UndoManager.push(
                        undomanager.SpriteDataChangedCommand(item, item.spritedata, new_data))
                    # UpdateListItem/UpdateDynamicSizing handled by command.redo()
            globals.UndoManager.end_compound()
            # Recompute merged display so differing bits show 0
            merged, diff = self._computeMergedData([it.spritedata for it in self._multiItems])
            self.data = merged
            self._multiBaseline = merged.hex()
            self.UpdateFlag = True
            self._updateRawDisplay(merged)
            if not self._mixedTypeMode:
                for f in self.fields:
                    f.update(merged)
                self.UpdateFlag = False
                self._applyMixedStates(diff)
            else:
                self.UpdateFlag = False
            return

        self.data = data
        self.UpdateFlag = True
        for f in self.fields:
            f.update(data)
        self.UpdateFlag = False

        # Emit DataUpdate so SpriteDataUpdated can handle special cases (e.g. sprite 564).
        self.DataUpdate.emit(data)

        # Direct fallback: if the DataUpdate path did not save (dock hidden,
        # selObj was None, etc.), write the change through the undo manager now.
        # SpriteDataChangedCommand.redo() is idempotent with respect to old_data —
        # if SpriteDataUpdated already ran we'll see obj.spritedata == data and skip.
        if not self.DefaultMode and globals.UndoManager is not None:
            mw = globals.mainWindow
            if mw is not None:
                obj = getattr(mw, 'selObj', None)
                if obj is not None and hasattr(obj, 'spritedata') and obj.spritedata != data:
                    globals.UndoManager.push(
                        undomanager.SpriteDataChangedCommand(obj, obj.spritedata, data))

class EntranceEditorWidget(QtWidgets.QWidget):
    """
    Widget for editing entrance properties
    """

    def __init__(self, defaultmode=False):
        """
        Constructor
        """
        super().__init__()
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed))

        # create widgets
        self.cameraX = QtWidgets.QSpinBox()
        self.cameraX.setFocusPolicy(Qt.ClickFocus)
        self.cameraX.setRange(-32768, 32767)
        self.cameraX.setToolTip("<b>Camera X Position:</b><br>Used to offset the point the camera will center on. Position relative to the entrance's.<br>16 = 1 block.")
        self.cameraX.valueChanged.connect(self.HandleCameraXChanged)

        self.cameraY = QtWidgets.QSpinBox()
        self.cameraY.setFocusPolicy(Qt.ClickFocus)
        self.cameraY.setRange(-32768, 32767)
        self.cameraY.setToolTip("<b>Camera Y Position:</b><br>Used to offset the point the camera will center on. Position relative to the entrance's.<br>16 = 1 block.")
        self.cameraY.valueChanged.connect(self.HandleCameraYChanged)

        self.entranceID = QtWidgets.QSpinBox()
        self.entranceID.setFocusPolicy(Qt.ClickFocus)
        self.entranceID.setRange(0, 255)
        self.entranceID.setToolTip('<b>ID:</b><br>Must be different from all other IDs')
        self.entranceID.valueChanged.connect(self.HandleEntranceIDChanged)

        self.entranceType = QtWidgets.QComboBox()
        self.entranceType.setFocusPolicy(Qt.ClickFocus)

        from . import loading
        loading.LoadEntranceNames()
        del loading

        self.entranceType.addItems(globals.EntranceTypeNames)
        self.entranceType.setToolTip('<b>Type:</b><br>Sets how the entrance behaves')
        self.entranceType.activated.connect(self.HandleEntranceTypeChanged)

        self.destArea = QtWidgets.QSpinBox()
        self.destArea.setFocusPolicy(Qt.ClickFocus)
        self.destArea.setRange(0, 4)
        self.destArea.setToolTip('<b>Dest. Area:</b><br>If this entrance leads nowhere, set this to 0.')
        self.destArea.valueChanged.connect(self.HandleDestAreaChanged)

        self.destEntrance = QtWidgets.QSpinBox()
        self.destEntrance.setFocusPolicy(Qt.ClickFocus)
        self.destEntrance.setRange(0, 255)
        self.destEntrance.setToolTip('<b>Dest. ID:</b><br>If this entrance leads nowhere or the destination is in this area, set this to 0.')
        self.destEntrance.valueChanged.connect(self.HandleDestEntranceChanged)

        self.allowEntryCheckbox = QtWidgets.QCheckBox('Enterable')
        self.allowEntryCheckbox.setFocusPolicy(Qt.ClickFocus)
        self.allowEntryCheckbox.setToolTip("<b>Enterable:</b><br>If this box is checked on a pipe or door entrance, Mario will be able to enter the pipe/door. If it's not checked, he won't be able to enter it. Behaviour on other types of entrances is unknown/undefined.")
        self.allowEntryCheckbox.clicked.connect(self.HandleAllowEntryClicked)

        self.unkFlagCheckbox = QtWidgets.QCheckBox("Connected Pipe")
        self.unkFlagCheckbox.setFocusPolicy(Qt.ClickFocus)
        self.unkFlagCheckbox.setToolTip("Enables pipe entrances to be connected using a path. This setting is broken and causes a softlock in the vanilla game.")
        self.unkFlagCheckbox.clicked.connect(self.HandleUnknownFlagClicked)

        self.faceLeftCheckbox = QtWidgets.QCheckBox("Face Left")
        self.faceLeftCheckbox.setFocusPolicy(Qt.ClickFocus)
        self.faceLeftCheckbox.setToolTip("Makes the player face left when spawning.")
        self.faceLeftCheckbox.clicked.connect(self.HandleFaceLeftClicked)

        self.player1Checkbox = QtWidgets.QCheckBox("Player 1")
        self.player1Checkbox.setFocusPolicy(Qt.ClickFocus)
        self.player1Checkbox.setToolTip('<b>Players to spawn:</b><br>Players to spawn at this entrance. Only works with entrance types 25 and 34.')
        self.player1Checkbox.clicked.connect(self.HandlePlayer1Clicked)

        self.player2Checkbox = QtWidgets.QCheckBox("Player 2")
        self.player2Checkbox.setFocusPolicy(Qt.ClickFocus)
        self.player2Checkbox.setToolTip('<b>Players to spawn:</b><br>Players to spawn at this entrance. Only works with entrance types 25 and 34.')
        self.player2Checkbox.clicked.connect(self.HandlePlayer2Clicked)

        self.player3Checkbox = QtWidgets.QCheckBox("Player 3")
        self.player3Checkbox.setFocusPolicy(Qt.ClickFocus)
        self.player3Checkbox.setToolTip('<b>Players to spawn:</b><br>Players to spawn at this entrance. Only works with entrance types 25 and 34.')
        self.player3Checkbox.clicked.connect(self.HandlePlayer3Clicked)

        self.player4Checkbox = QtWidgets.QCheckBox("Player 4")
        self.player4Checkbox.setFocusPolicy(Qt.ClickFocus)
        self.player4Checkbox.setToolTip('<b>Players to spawn:</b><br>Players to spawn at this entrance. Only works with entrance types 25 and 34.')
        self.player4Checkbox.clicked.connect(self.HandlePlayer4Clicked)

        self.playerDistance = QtWidgets.QComboBox()
        self.playerDistance.setFocusPolicy(Qt.ClickFocus)
        self.playerDistance.addItems(["1 block", "1.5 blocks", "2 blocks"])
        self.playerDistance.setToolTip('Distance between players. Only works with entrance types 25 and 34.')
        self.playerDistance.activated.connect(self.HandlePlayerDistanceChanged)

        self.otherID = QtWidgets.QSpinBox()
        self.otherID.setFocusPolicy(Qt.ClickFocus)
        self.otherID.setRange(0, 255)
        self.otherID.setToolTip('The ID of the entrance where Baby Yoshis spawn when entering the level (or area?).\nValue of 0 makes the Baby Yoshis spawn at the same entrance.')
        self.otherID.valueChanged.connect(self.HandleOtherID)

        self.goto = QtWidgets.QPushButton("Goto")
        self.goto.setFocusPolicy(Qt.ClickFocus)
        self.goto.clicked.connect(self.GotoOtherEntrance)

        self.coinOrder = QtWidgets.QSpinBox()
        self.coinOrder.setFocusPolicy(Qt.ClickFocus)
        self.coinOrder.setRange(0, 255)
        self.coinOrder.setToolTip('Used in coin edit to determine the order of entrances.\nIf there are multiple entrances with the same order, the game picks the first one it finds.')
        self.coinOrder.valueChanged.connect(self.HandleCoinOrder)

        self.scrollPathID = QtWidgets.QSpinBox()
        self.scrollPathID.setFocusPolicy(Qt.ClickFocus)
        self.scrollPathID.setRange(0, 255)
        self.scrollPathID.setToolTip('The Path ID, for autoscroll purposes.')
        self.scrollPathID.valueChanged.connect(self.HandleScrollPathID)

        self.pathnodeindex = QtWidgets.QSpinBox()
        self.pathnodeindex.setFocusPolicy(Qt.ClickFocus)
        self.pathnodeindex.setRange(0, 255)
        self.pathnodeindex.setToolTip('The Path Node Index, for autoscroll purposes.')
        self.pathnodeindex.valueChanged.connect(self.HandlePathNodeIndex)

        self.transition = QtWidgets.QComboBox()
        self.transition.setFocusPolicy(Qt.ClickFocus)
        self.transition.addItems(["Default", "Fade", "Mario face", "Circle towards center", "Bowser face", "Circle towards entrance", "Waves (always down)", "Waves (down on fadeout, up on fadein)", "Waves (up on fadeout, down on fadein)", "Mushroom", "Circle towards entrance", "No transition"])
        self.transition.setToolTip('The screen fades out with the transition mode of the source entrance, and fades in with the transition mode of the destination entrance.')
        self.transition.activated.connect(self.HandleTransitionChanged)

        # create a layout
        layout = QtWidgets.QGridLayout()
        self.setLayout(layout)

        # 'Editing Entrance #' label
        self.editingLabel = QtWidgets.QLabel('-')
        layout.addWidget(self.editingLabel, 0, 0, 1, 6, Qt.AlignTop)

        # add labels
        layout.addWidget(QtWidgets.QLabel('Type:'), 1, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('ID:'), 3, 0, 1, 1, Qt.AlignRight)

        layout.addWidget(createHorzLine(), 2, 0, 1, 6)

        layout.addWidget(QtWidgets.QLabel('Dest. ID:'), 3, 3, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Dest. Area:'), 5, 3, 1, 1, Qt.AlignRight)

        # add the widgets
        layout.addWidget(self.entranceType, 1, 1, 1, 5)
        layout.addWidget(self.entranceID, 3, 1, 1, 2)
        layout.addWidget(self.destEntrance, 3, 4, 1, 2)
        layout.addWidget(self.destArea, 5, 4, 1, 2)

        layout.addWidget(createHorzLine(), 6, 0, 1, 6)

        layout.addWidget(self.allowEntryCheckbox, 7, 1, 1, 2)
        layout.addWidget(self.unkFlagCheckbox, 7, 2, 1, 2)
        layout.addWidget(self.faceLeftCheckbox, 7, 4, 1, 2)

        layout.addWidget(createHorzLine(), 8, 0, 1, 6)

        layout.addWidget(QtWidgets.QLabel('Players to spawn:'), 9, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(self.player1Checkbox, 9, 1)
        layout.addWidget(self.player2Checkbox, 9, 2)
        layout.addWidget(self.player3Checkbox, 9, 3)
        layout.addWidget(self.player4Checkbox, 9, 4)
        layout.addWidget(QtWidgets.QLabel('Players Distance:'), 10, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(self.playerDistance, 10, 1, 1, 5)

        layout.addWidget(createHorzLine(), 11, 0, 1, 6)

        layout.addWidget(QtWidgets.QLabel('Baby Yoshi Entrance ID:'), 12, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(self.otherID, 12, 1, 1, 2)
        layout.addWidget(self.goto, 13, 1, 1, 2)

        layout.addWidget(createHorzLine(), 14, 0, 1, 6)

        layout.addWidget(QtWidgets.QLabel('Entrance Order:'), 12, 3, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Path ID:'), 16, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Path Node Index:'), 16, 3, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Transition:'), 18, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(self.coinOrder, 12, 4, 1, 2)
        layout.addWidget(self.scrollPathID, 16, 1, 1, 2)
        layout.addWidget(self.pathnodeindex, 16, 4, 1, 2)
        layout.addWidget(self.transition, 18, 1, 1, 5)

        layout.addWidget(createHorzLine(), 19, 0, 1, 6)

        layout.addWidget(QtWidgets.QLabel('Camera X:'), 20, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Camera Y:'), 20, 3, 1, 1, Qt.AlignRight)
        layout.addWidget(self.cameraX, 20, 1, 1, 2)
        layout.addWidget(self.cameraY, 20, 4, 1, 2)

        self.ent = None
        self.UpdateFlag = False
        self._multiMode = False
        self._multiItems = []

    def _commitAttr(self, attr, new_val, cmd_class=None):
        """Apply a simple attribute change to all targets (or single target)."""
        if self.UpdateFlag: return
        targets = self._multiItems if self._multiMode else ([self.ent] if self.ent else [])
        for ent in targets:
            old_val = getattr(ent, attr)
            if old_val != new_val:
                globals.UndoManager.push(
                    undomanager.EntrancePropertyChangedCommand(ent, {attr: old_val}, {attr: new_val}))

    def _commitBits(self, attr, mask, set_when_true, checked):
        """Toggle bits in a bitfield attribute for all targets."""
        if self.UpdateFlag: return
        targets = self._multiItems if self._multiMode else ([self.ent] if self.ent else [])
        for ent in targets:
            old_val = getattr(ent, attr)
            new_val = (old_val | mask) if (checked == set_when_true) else (old_val & ~mask)
            if old_val != new_val:
                globals.UndoManager.push(
                    undomanager.EntrancePropertyChangedCommand(ent, {attr: old_val}, {attr: new_val}))

    @staticmethod
    def _spinMixed(widget, values, orig_min):
        vs = set(values)
        if len(vs) == 1:
            widget.setMinimum(orig_min)
            widget.setSpecialValueText('')
            widget.setValue(next(iter(vs)))
        else:
            widget.setMinimum(orig_min - 1)
            widget.setSpecialValueText('—')
            widget.setValue(orig_min - 1)

    @staticmethod
    def _comboMixed(widget, values):
        vs = set(values)
        if len(vs) == 1:
            widget.setCurrentIndex(next(iter(vs)))
        else:
            widget.setCurrentIndex(-1)

    @staticmethod
    def _checkMixed(widget, values):
        vs = set(values)
        if len(vs) == 1:
            widget.setTristate(False)
            widget.setChecked(next(iter(vs)))
        else:
            widget.setTristate(True)
            widget.setCheckState(Qt.PartiallyChecked)

    def setMultipleEntrances(self, items):
        """Populate the editor for multiple selected entrances."""
        self._multiMode = True
        self._multiItems = list(items)
        self.ent = None
        self.UpdateFlag = True

        n = len(items)
        self.editingLabel.setText(f'<b>Editing {n} Entrance{"s" if n != 1 else ""}</b>')
        self.entranceID.setEnabled(False)  # IDs must be unique; cannot batch-assign

        self._spinMixed(self.cameraX,       [e.camerax for e in items],        -32768)
        self._spinMixed(self.cameraY,       [e.cameray for e in items],        -32768)
        self._spinMixed(self.destArea,      [e.destarea for e in items],       0)
        self._spinMixed(self.destEntrance,  [e.destentrance for e in items],   0)
        self._spinMixed(self.otherID,       [e.otherID for e in items],        0)
        self._spinMixed(self.coinOrder,     [e.coinOrder for e in items],      0)
        self._spinMixed(self.scrollPathID,  [e.pathID for e in items],         0)
        self._spinMixed(self.pathnodeindex, [e.pathnodeindex for e in items],  0)

        self._comboMixed(self.entranceType,   [e.enttype for e in items])
        self._comboMixed(self.playerDistance, [e.playerDistance for e in items])
        self._comboMixed(self.transition,     [e.transition for e in items])

        self._checkMixed(self.allowEntryCheckbox, [(e.entsettings & 0x80) == 0 for e in items])
        self._checkMixed(self.unkFlagCheckbox,    [(e.entsettings & 2) != 0  for e in items])
        self._checkMixed(self.faceLeftCheckbox,   [(e.entsettings & 1) != 0  for e in items])
        self._checkMixed(self.player1Checkbox,    [(e.players & 1) != 0 for e in items])
        self._checkMixed(self.player2Checkbox,    [(e.players & 2) != 0 for e in items])
        self._checkMixed(self.player3Checkbox,    [(e.players & 4) != 0 for e in items])
        self._checkMixed(self.player4Checkbox,    [(e.players & 8) != 0 for e in items])

        self.UpdateFlag = False

    def setEntrance(self, ent):
        """
        Change the entrance being edited by the editor, update all fields
        """
        if self.ent == ent and not self._multiMode: return

        self._multiMode = False
        self._multiItems = []
        self.editingLabel.setText('<b>Entrance [id]:</b>'.replace('[id]', str(ent.entid)))
        self.ent = ent
        self.UpdateFlag = True

        self.entranceID.setEnabled(True)
        # Restore any spinbox minimums that may have been lowered for mixed state
        for w, orig_min in [(self.cameraX, -32768), (self.cameraY, -32768),
                            (self.destArea, 0), (self.destEntrance, 0),
                            (self.otherID, 0), (self.coinOrder, 0),
                            (self.scrollPathID, 0), (self.pathnodeindex, 0)]:
            w.setMinimum(orig_min)
            w.setSpecialValueText('')

        self.cameraX.setValue(ent.camerax)
        self.cameraY.setValue(ent.cameray)
        self.entranceID.setValue(ent.entid)
        self.entranceType.setCurrentIndex(ent.enttype)
        self.destArea.setValue(ent.destarea)
        self.destEntrance.setValue(ent.destentrance)
        self.playerDistance.setCurrentIndex(ent.playerDistance)
        self.otherID.setValue(ent.otherID)
        self.coinOrder.setValue(ent.coinOrder)
        self.scrollPathID.setValue(ent.pathID)
        self.pathnodeindex.setValue(ent.pathnodeindex)
        self.transition.setCurrentIndex(ent.transition)

        for cb in (self.allowEntryCheckbox, self.unkFlagCheckbox, self.faceLeftCheckbox,
                   self.player1Checkbox, self.player2Checkbox,
                   self.player3Checkbox, self.player4Checkbox):
            cb.setTristate(False)

        self.allowEntryCheckbox.setChecked(((ent.entsettings & 0x80) == 0))
        self.unkFlagCheckbox.setChecked(((ent.entsettings & 2) != 0))
        self.faceLeftCheckbox.setChecked(((ent.entsettings & 1) != 0))
        self.player1Checkbox.setChecked(((ent.players & 1) != 0))
        self.player2Checkbox.setChecked(((ent.players & 2) != 0))
        self.player3Checkbox.setChecked(((ent.players & 4) != 0))
        self.player4Checkbox.setChecked(((ent.players & 8) != 0))

        self.UpdateFlag = False

    def _checkState(self, widget):
        """Return (is_partial, checked) for a checkbox widget."""
        state = widget.checkState()
        return state == Qt.PartiallyChecked, state == Qt.Checked

    def HandleCameraXChanged(self, i):
        if i < -32768: return
        self._commitAttr('camerax', i)

    def HandleCameraYChanged(self, i):
        if i < -32768: return
        self._commitAttr('cameray', i)

    def HandleEntranceIDChanged(self, i):
        if self.UpdateFlag: return
        old_val = self.ent.entid
        if old_val != i:
            globals.UndoManager.push(undomanager.EntrancePropertyChangedCommand(
                self.ent, {'entid': old_val}, {'entid': i}))
            self.editingLabel.setText('<b>Entrance [id]:</b>'.replace('[id]', str(i)))

    def HandleEntranceTypeChanged(self, i):
        if i < 0: return
        self._commitAttr('enttype', i)

    def HandleDestAreaChanged(self, i):
        if i < 0: return
        self._commitAttr('destarea', i)

    def HandleDestEntranceChanged(self, i):
        if i < 0: return
        self._commitAttr('destentrance', i)

    def HandlePlayerDistanceChanged(self, i):
        if i < 0: return
        self._commitAttr('playerDistance', i)

    def HandleOtherID(self, i):
        if i < 0: return
        self._commitAttr('otherID', i)

    def GotoOtherEntrance(self):
        otherID = self.ent.otherID
        otherEnt = None
        for ent in globals.Area.entrances:
            if ent.entid == otherID:
                otherEnt = ent
                break
        if otherEnt:
            globals.mainWindow.view.centerOn(
                otherEnt.objx * (globals.TileWidth / 16),
                otherEnt.objy * (globals.TileWidth / 16))

    def HandleCoinOrder(self, i):
        if i < 0: return
        self._commitAttr('coinOrder', i)

    def HandleScrollPathID(self, i):
        if i < 0: return
        self._commitAttr('pathID', i)

    def HandlePathNodeIndex(self, i):
        if i < 0: return
        self._commitAttr('pathnodeindex', i)

    def HandleTransitionChanged(self, i):
        if i < 0: return
        self._commitAttr('transition', i)

    def HandleAllowEntryClicked(self, checked):
        partial, checked_val = self._checkState(self.allowEntryCheckbox)
        if partial: return
        self.allowEntryCheckbox.setTristate(False)
        self._commitBits('entsettings', 0x80, False, checked_val)  # bit set = deny entry

    def HandleUnknownFlagClicked(self, checked):
        partial, checked_val = self._checkState(self.unkFlagCheckbox)
        if partial: return
        self.unkFlagCheckbox.setTristate(False)
        self._commitBits('entsettings', 0x2, True, checked_val)

    def HandleFaceLeftClicked(self, checked):
        partial, checked_val = self._checkState(self.faceLeftCheckbox)
        if partial: return
        self.faceLeftCheckbox.setTristate(False)
        self._commitBits('entsettings', 0x1, True, checked_val)

    def HandlePlayer1Clicked(self, checked):
        partial, checked_val = self._checkState(self.player1Checkbox)
        if partial: return
        self.player1Checkbox.setTristate(False)
        self._commitBits('players', 0x1, True, checked_val)

    def HandlePlayer2Clicked(self, checked):
        partial, checked_val = self._checkState(self.player2Checkbox)
        if partial: return
        self.player2Checkbox.setTristate(False)
        self._commitBits('players', 0x2, True, checked_val)

    def HandlePlayer3Clicked(self, checked):
        partial, checked_val = self._checkState(self.player3Checkbox)
        if partial: return
        self.player3Checkbox.setTristate(False)
        self._commitBits('players', 0x4, True, checked_val)

    def HandlePlayer4Clicked(self, checked):
        partial, checked_val = self._checkState(self.player4Checkbox)
        if partial: return
        self.player4Checkbox.setTristate(False)
        self._commitBits('players', 0x8, True, checked_val)


class PathNodeEditorWidget(QtWidgets.QWidget):
    """
    Widget for editing path node properties
    """

    def __init__(self, defaultmode=False):
        """
        Constructor
        """
        super().__init__()
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed))

        # create widgets
        # [20:52:41]  [Angel-SL] 1. (readonly) pathid 2. (readonly) nodeid 3. x 4. y 5. speed (float spinner) 6. accel (float spinner)
        # not doing [20:52:58]  [Angel-SL] and 2 buttons - 7. 'Move Up' 8. 'Move Down'
        self.speed = QtWidgets.QDoubleSpinBox()
        self.speed.setFocusPolicy(Qt.ClickFocus)
        self.speed.setRange(min(sys.float_info), max(sys.float_info))
        self.speed.setToolTip('<b>Speed:</b><br>Unknown unit. Mess around and report your findings!')
        self.speed.setDecimals(int(sys.float_info.__getattribute__('dig')))
        self.speed.valueChanged.connect(self.HandleSpeedChanged)
        self.speed.setMaximumWidth(256)

        self.accel = QtWidgets.QDoubleSpinBox()
        self.accel.setFocusPolicy(Qt.ClickFocus)
        self.accel.setRange(min(sys.float_info), max(sys.float_info))
        self.accel.setToolTip('<b>Accel:</b><br>Unknown unit. Mess around and report your findings!')
        self.accel.setDecimals(int(sys.float_info.__getattribute__('dig')))
        self.accel.valueChanged.connect(self.HandleAccelChanged)
        self.accel.setMaximumWidth(256)

        self.delay = QtWidgets.QSpinBox()
        self.delay.setFocusPolicy(Qt.ClickFocus)
        self.delay.setRange(0, 65535)
        self.delay.setToolTip('<b>Delay:</b><br>Amount of time to stop here (at this node) before continuing to next node. Unit is 1/60 of a second (60 for 1 second)')
        self.delay.valueChanged.connect(self.HandleDelayChanged)
        self.delay.setMaximumWidth(256)

        self.loops = QtWidgets.QCheckBox()
        self.loops.setFocusPolicy(Qt.ClickFocus)
        self.loops.setToolTip('<b>Loops:</b><br>Anything following this path will wait for any delay set at the last node and then proceed back in a straight line to the first node, and continue.')
        self.loops.stateChanged.connect(self.HandleLoopsChanged)

        self.unk1 = QtWidgets.QSpinBox()
        self.unk1.setFocusPolicy(Qt.ClickFocus)
        self.unk1.setRange(-128, 127)
        self.unk1.setToolTip('<b>Unknown 0x01:</b><br>No idea what this is')
        self.unk1.valueChanged.connect(self.Handleunk1Changed)
        self.unk1.setMaximumWidth(256)

        # create a layout
        layout = QtWidgets.QGridLayout()
        self.setLayout(layout)

        # 'Editing Path #' label
        self.editingLabel = QtWidgets.QLabel('-')
        self.editingPathLabel = QtWidgets.QLabel('-')
        layout.addWidget(self.editingLabel, 4, 0, 1, 2, Qt.AlignTop)
        layout.addWidget(self.editingPathLabel, 0, 0, 1, 2, Qt.AlignTop)
        # add labels
        layout.addWidget(QtWidgets.QLabel('Unknown 0x01:'), 1, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Loops:'), 2, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Speed:'), 5, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Accel:'), 6, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Delay:'), 7, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(createHorzLine(), 3, 0, 1, 2)

        # add the widgets
        layout.addWidget(self.unk1, 1, 1)
        layout.addWidget(self.loops, 2, 1)
        layout.addWidget(self.speed, 5, 1)
        layout.addWidget(self.accel, 6, 1)
        layout.addWidget(self.delay, 7, 1)

        self.path = None
        self.UpdateFlag = False
        self._multiMode = False
        self._multiItems = []

    def setMultiplePaths(self, items):
        """Populate the editor for multiple selected path nodes."""
        self._multiMode = True
        self._multiItems = list(items)
        self.path = items[0]
        self.UpdateFlag = True

        n = len(items)
        self.editingPathLabel.setText(f'<b>Editing {n} Path Node{"s" if n != 1 else ""}</b>')
        self.editingLabel.setText('')

        ref = items[0]
        self.speed.setValue(ref.nodeinfo['speed'])
        self.accel.setValue(ref.nodeinfo['accel'])
        self.delay.setValue(ref.nodeinfo['delay'])
        self.loops.setChecked(ref.pathinfo['loops'])
        self.unk1.setValue(ref.pathinfo['unk1'])

        self.UpdateFlag = False

    def setPath(self, path):
        """
        Change the path being edited by the editor, update all fields
        """
        if self.path == path and not self._multiMode: return
        self._multiMode = False
        self._multiItems = []
        self.editingPathLabel.setText('<b>Path [id]</b>'.replace('[id]', str(path.pathid)))
        self.editingLabel.setText('<b>Node [id]</b>'.replace('[id]', str(path.nodeid)))
        self.path = path
        self.UpdateFlag = True

        self.speed.setValue(path.nodeinfo['speed'])
        self.accel.setValue(path.nodeinfo['accel'])
        self.delay.setValue(path.nodeinfo['delay'])
        self.loops.setChecked(path.pathinfo['loops'])
        self.unk1.setValue(path.pathinfo['unk1'])

        self.UpdateFlag = False

    def HandleSpeedChanged(self, i):
        if self.UpdateFlag: return
        targets = self._multiItems if self._multiMode else ([self.path] if self.path else [])
        for p in targets:
            p.nodeinfo['speed'] = i
        SetDirty()

    def HandleAccelChanged(self, i):
        if self.UpdateFlag: return
        targets = self._multiItems if self._multiMode else ([self.path] if self.path else [])
        for p in targets:
            old_val = p.nodeinfo['accel']
            if old_val != i:
                globals.UndoManager.push(undomanager.DictPropertyChangedCommand(p.nodeinfo, 'accel', old_val, i))

    def HandleDelayChanged(self, i):
        if self.UpdateFlag: return
        targets = self._multiItems if self._multiMode else ([self.path] if self.path else [])
        for p in targets:
            old_val = p.nodeinfo['delay']
            if old_val != i:
                globals.UndoManager.push(undomanager.DictPropertyChangedCommand(p.nodeinfo, 'delay', old_val, i))

    def Handleunk1Changed(self, i):
        if self.UpdateFlag: return
        targets = self._multiItems if self._multiMode else ([self.path] if self.path else [])
        for p in targets:
            old_val = p.pathinfo['unk1']
            if old_val != i:
                globals.UndoManager.push(undomanager.DictPropertyChangedCommand(p.pathinfo, 'unk1', old_val, i))

    def HandleLoopsChanged(self, i):
        if self.UpdateFlag: return
        new_val = (i == Qt.Checked)
        targets = self._multiItems if self._multiMode else ([self.path] if self.path else [])
        for p in targets:
            old_val = p.pathinfo['loops']
            if old_val != new_val:
                globals.UndoManager.push(undomanager.DictPropertyChangedCommand(
                    p.pathinfo, 'loops', old_val, new_val,
                    sync_func=lambda path=p: self._sync_loops_for(path)))

    def _sync_loops(self):
        self._sync_loops_for(self.path)

    def _sync_loops_for(self, path):
        path.pathinfo['peline'].loops = path.pathinfo['loops']
        path.pathinfo['peline'].update()
        globals.mainWindow.scene.update()
        SetDirty()


class NabbitPathNodeEditorWidget(QtWidgets.QWidget):
    """
    Widget for editing path node properties
    """

    def __init__(self, defaultmode=False):
        """
        Constructor
        """
        super().__init__()
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed))

        # create widgets
        self.unk1 = QtWidgets.QSpinBox()
        self.unk1.setFocusPolicy(Qt.ClickFocus)
        self.unk1.setRange(0, 0xFFFF)
        self.unk1.valueChanged.connect(self.HandleUnk1Changed)

        self.unk2 = QtWidgets.QSpinBox()
        self.unk2.setFocusPolicy(Qt.ClickFocus)
        self.unk2.setRange(0, 0xFF)
        self.unk2.valueChanged.connect(self.HandleUnk2Changed)

        self.unk3 = QtWidgets.QSpinBox()
        self.unk3.setFocusPolicy(Qt.ClickFocus)
        self.unk3.setRange(0, 0xFF)
        self.unk3.valueChanged.connect(self.HandleUnk3Changed)

        self.unk4 = QtWidgets.QSpinBox()
        self.unk4.setFocusPolicy(Qt.ClickFocus)
        self.unk4.setRange(0, 0xFF)
        self.unk4.valueChanged.connect(self.HandleUnk4Changed)

        self.action = QtWidgets.QComboBox()
        self.action.setFocusPolicy(Qt.ClickFocus)
        self.action.addItems(['0: Run to the right',
                              '1: Jump to the next node',
                              '6: Unknown, probably the same as 0',
                              '7: Unknown',
                              '8: Same as 0 and look behind?',
                              '11: Same as 0?',
                              '20: Same as 0 except don\'t look behind?',
                              '23: Wait, then slide',
                              '24: Stop at the next node',
                              '25: Same as 0?',
                              '26: Same as 0?'])

        self.action.setToolTip('<b>Action:</b><br>The action Nabbit will do when he is on this node')
        self.action.currentIndexChanged.connect(self.HandleActionChanged)
        self.action.setMaximumWidth(256)

        # create a layout
        layout = QtWidgets.QGridLayout()
        self.setLayout(layout)

        # 'Editing Path #' label
        self.editingLabel = QtWidgets.QLabel('-')
        layout.addWidget(self.editingLabel, 0, 0, 1, 2, Qt.AlignTop)
        # add labels
        layout.addWidget(QtWidgets.QLabel('Unknown value 1:'), 1, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Unknown value 2:'), 2, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Unknown value 3:'), 3, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Unknown value 4:'), 4, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Action:'), 6, 0, 1, 1, Qt.AlignRight)

        # add the widgets
        layout.addWidget(self.unk1, 1, 1)
        layout.addWidget(self.unk2, 2, 1)
        layout.addWidget(self.unk3, 3, 1)
        layout.addWidget(self.unk4, 4, 1)
        layout.addWidget(createHorzLine(), 5, 0, 1, 2)
        layout.addWidget(self.action, 6, 1)

        self.path = None
        self.UpdateFlag = False
        self._multiMode = False
        self._multiItems = []

        self.indecies = {
            0: 0,
            1: 1,
            6: 2,
            7: 3,
            8: 4,
            11: 5,
            20: 6,
            23: 7,
            24: 8,
            25: 9,
            26: 10,
        }

        self.rIndecies = {
            0: 0,
            1: 1,
            2: 6,
            3: 7,
            4: 8,
            5: 11,
            6: 20,
            7: 23,
            8: 24,
            9: 25,
            10: 26,
        }

    def setMultiplePaths(self, items):
        """Populate the editor for multiple selected Nabbit path nodes."""
        self._multiMode = True
        self._multiItems = list(items)
        self.path = items[0]
        self.UpdateFlag = True

        n = len(items)
        self.editingLabel.setText(f'<b>Editing {n} Nabbit Path Node{"s" if n != 1 else ""}</b>')

        ref = items[0]
        self.unk1.setValue(ref.nodeinfo['unk1'])
        self.unk2.setValue(ref.nodeinfo['unk2'])
        self.unk3.setValue(ref.nodeinfo['unk3'])
        self.unk4.setValue(ref.nodeinfo['unk4'])
        action = ref.nodeinfo['action']
        self.action.setCurrentIndex(self.indecies.get(action, 0))

        self.UpdateFlag = False

    def setPath(self, path):
        """
        Change the path node being edited by the editor, update the action field
        """
        if self.path == path and not self._multiMode: return
        self._multiMode = False
        self._multiItems = []
        self.editingLabel.setText('<b>Nabbit Path Node [id]</b>'.replace('[id]', str(path.nodeid)))
        self.path = path
        self.UpdateFlag = True

        self.unk1.setValue(path.nodeinfo['unk1'])
        self.unk2.setValue(path.nodeinfo['unk2'])
        self.unk3.setValue(path.nodeinfo['unk3'])
        self.unk4.setValue(path.nodeinfo['unk4'])

        if path.nodeinfo['action'] in self.indecies:
            self.action.setCurrentIndex(self.indecies[path.nodeinfo['action']])
        else:
            print("Unknown nabbit path node action found: %d" % path.nodeinfo['action'])
            self.action.setCurrentIndex(0)

        self.UpdateFlag = False

    def _targets(self):
        return self._multiItems if self._multiMode else ([self.path] if self.path else [])

    def HandleUnk1Changed(self, v):
        if self.UpdateFlag: return
        for p in self._targets():
            old_val = p.nodeinfo['unk1']
            if old_val != v:
                globals.UndoManager.push(undomanager.DictPropertyChangedCommand(p.nodeinfo, 'unk1', old_val, v))

    def HandleUnk2Changed(self, v):
        if self.UpdateFlag: return
        for p in self._targets():
            old_val = p.nodeinfo['unk2']
            if old_val != v:
                globals.UndoManager.push(undomanager.DictPropertyChangedCommand(p.nodeinfo, 'unk2', old_val, v))

    def HandleUnk3Changed(self, v):
        if self.UpdateFlag: return
        for p in self._targets():
            old_val = p.nodeinfo['unk3']
            if old_val != v:
                globals.UndoManager.push(undomanager.DictPropertyChangedCommand(p.nodeinfo, 'unk3', old_val, v))

    def HandleUnk4Changed(self, v):
        if self.UpdateFlag: return
        for p in self._targets():
            old_val = p.nodeinfo['unk4']
            if old_val != v:
                globals.UndoManager.push(undomanager.DictPropertyChangedCommand(p.nodeinfo, 'unk4', old_val, v))

    def HandleActionChanged(self, i):
        if self.UpdateFlag: return
        new_val = self.rIndecies[i]
        for p in self._targets():
            old_val = p.nodeinfo['action']
            if old_val != new_val:
                globals.UndoManager.push(undomanager.DictPropertyChangedCommand(p.nodeinfo, 'action', old_val, new_val))


class LocationEditorWidget(QtWidgets.QWidget):
    """
    Widget for editing location properties
    """

    def __init__(self, defaultmode=False):
        """
        Constructor
        """
        super().__init__()
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed))

        # create widgets
        self.locationID = QtWidgets.QSpinBox()
        self.locationID.setFocusPolicy(Qt.ClickFocus)
        self.locationID.setToolTip('<b>ID:</b><br>Must be different from all other IDs')
        self.locationID.setRange(0, 255)
        self.locationID.valueChanged.connect(self.HandleLocationIDChanged)

        self.locationX = QtWidgets.QSpinBox()
        self.locationX.setFocusPolicy(Qt.ClickFocus)
        self.locationX.setToolTip('<b>X Pos:</b><br>Specifies the X position of the location')
        self.locationX.setRange(16, 65535)
        self.locationX.valueChanged.connect(self.HandleLocationXChanged)

        self.locationY = QtWidgets.QSpinBox()
        self.locationY.setFocusPolicy(Qt.ClickFocus)
        self.locationY.setToolTip('<b>Y Pos:</b><br>Specifies the Y position of the location')
        self.locationY.setRange(16, 65535)
        self.locationY.valueChanged.connect(self.HandleLocationYChanged)

        self.locationWidth = QtWidgets.QSpinBox()
        self.locationWidth.setFocusPolicy(Qt.ClickFocus)
        self.locationWidth.setToolTip('<b>Width:</b><br>Specifies the width of the location')
        self.locationWidth.setRange(8, 65535)
        self.locationWidth.valueChanged.connect(self.HandleLocationWidthChanged)

        self.locationHeight = QtWidgets.QSpinBox()
        self.locationHeight.setFocusPolicy(Qt.ClickFocus)
        self.locationHeight.setToolTip('<b>Height:</b><br>Specifies the height of the location')
        self.locationHeight.setRange(8, 65535)
        self.locationHeight.valueChanged.connect(self.HandleLocationHeightChanged)

        self.snapButton = QtWidgets.QPushButton('Snap to Grid')
        self.snapButton.setFocusPolicy(Qt.ClickFocus)
        self.snapButton.clicked.connect(self.HandleSnapToGrid)

        # create a layout
        layout = QtWidgets.QGridLayout()
        self.setLayout(layout)

        # 'Editing Location #' label
        self.editingLabel = QtWidgets.QLabel('-')
        layout.addWidget(self.editingLabel, 0, 0, 1, 4, Qt.AlignTop)

        # add labels
        layout.addWidget(QtWidgets.QLabel('ID:'), 1, 0, 1, 1, Qt.AlignRight)

        layout.addWidget(createHorzLine(), 2, 0, 1, 4)

        layout.addWidget(QtWidgets.QLabel('X Pos:'), 3, 0, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Y Pos:'), 4, 0, 1, 1, Qt.AlignRight)

        layout.addWidget(QtWidgets.QLabel('Width:'), 3, 2, 1, 1, Qt.AlignRight)
        layout.addWidget(QtWidgets.QLabel('Height:'), 4, 2, 1, 1, Qt.AlignRight)

        # add the widgets
        layout.addWidget(self.locationID, 1, 1, 1, 1)
        layout.addWidget(self.snapButton, 1, 3, 1, 1)

        layout.addWidget(self.locationX, 3, 1, 1, 1)
        layout.addWidget(self.locationY, 4, 1, 1, 1)

        layout.addWidget(self.locationWidth, 3, 3, 1, 1)
        layout.addWidget(self.locationHeight, 4, 3, 1, 1)

        self.loc = None
        self.UpdateFlag = False
        self._multiMode = False
        self._multiItems = []

    def setMultipleLocations(self, items):
        """Populate the editor for multiple selected locations."""
        self._multiMode = True
        self._multiItems = list(items)
        self.loc = items[0]
        self.UpdateFlag = True

        n = len(items)
        self.editingLabel.setText(f'<b>Editing {n} Location{"s" if n != 1 else ""}</b>')
        self.locationID.setEnabled(False)  # IDs must be unique

        ref = items[0]
        self.locationX.setValue(ref.objx)
        self.locationY.setValue(ref.objy)
        self.locationWidth.setValue(ref.width)
        self.locationHeight.setValue(ref.height)

        self.UpdateFlag = False

    def setLocation(self, loc):
        """
        Change the location being edited by the editor, update all fields
        """
        self._multiMode = False
        self._multiItems = []
        self.loc = loc
        self.UpdateFlag = True

        self.locationID.setEnabled(True)
        self.FixTitle()
        self.locationID.setValue(loc.id)
        self.locationX.setValue(loc.objx)
        self.locationY.setValue(loc.objy)
        self.locationWidth.setValue(loc.width)
        self.locationHeight.setValue(loc.height)

        self.UpdateFlag = False

    def FixTitle(self):
        self.editingLabel.setText('<b>Location [id]</b>'.replace('[id]', str(self.loc.id)))

    def _locTargets(self):
        return self._multiItems if self._multiMode else ([self.loc] if self.loc else [])

    def HandleLocationIDChanged(self, i):
        if self.UpdateFlag: return
        old_val = self.loc.id
        if old_val != i:
            globals.UndoManager.push(undomanager.PropertyChangedCommand(
                self.loc, 'id', old_val, i, sync_func=self._sync_loc_id))

    def _sync_loc_id(self):
        self.loc.update()
        self.loc.UpdateTitle()
        self.FixTitle()
        SetDirty()

    def HandleLocationXChanged(self, i):
        if self.UpdateFlag: return
        for loc in self._locTargets():
            old_val = loc.objx
            if old_val != i:
                globals.UndoManager.push(undomanager.PropertyChangedCommand(loc, 'objx', old_val, i))

    def HandleLocationYChanged(self, i):
        if self.UpdateFlag: return
        for loc in self._locTargets():
            old_val = loc.objy
            if old_val != i:
                globals.UndoManager.push(undomanager.PropertyChangedCommand(loc, 'objy', old_val, i))

    def HandleLocationWidthChanged(self, i):
        if self.UpdateFlag: return
        for loc in self._locTargets():
            old_val = loc.width
            if old_val != i:
                globals.UndoManager.push(undomanager.PropertyChangedCommand(loc, 'width', old_val, i))

    def HandleLocationHeightChanged(self, i):
        if self.UpdateFlag: return
        for loc in self._locTargets():
            old_val = loc.height
            if old_val != i:
                globals.UndoManager.push(undomanager.PropertyChangedCommand(loc, 'height', old_val, i))

    def HandleSnapToGrid(self):
        """
        Snaps the current location to an 8x8 grid
        """
        SetDirty()

        loc = self.loc
        left = loc.objx
        top = loc.objy
        right = left + loc.width
        bottom = top + loc.height

        if left % 8 < 4:
            left -= (left % 8)
        else:
            left += 8 - (left % 8)

        if top % 8 < 4:
            top -= (top % 8)
        else:
            top += 8 - (top % 8)

        if right % 8 < 4:
            right -= (right % 8)
        else:
            right += 8 - (right % 8)

        if bottom % 8 < 4:
            bottom -= (bottom % 8)
        else:
            bottom += 8 - (bottom % 8)

        if right <= left: right += 8
        if bottom <= top: bottom += 8

        loc.objx = left
        loc.objy = top
        loc.width = right - left
        loc.height = bottom - top

        loc.setPos(int(left * globals.TileWidth / 16), int(top * globals.TileWidth / 16))
        loc.UpdateRects()
        loc.update()
        self.setLocation(loc)  # updates the fields


class LoadingTab(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.entrance = QtWidgets.QSpinBox()
        self.entrance.setRange(0, 255)
        self.entrance.setToolTip('<b>Entrance ID:</b><br>Sets the entrance ID to load into when loading from the World Map')
        self.entrance.setValue(globals.Area.startEntrance)

        self.entranceCoinBoost = QtWidgets.QSpinBox()
        self.entranceCoinBoost.setRange(0, 255)
        self.entranceCoinBoost.setToolTip('<b>Entrance ID 2:</b><br>Sets the entrance ID to load into when loading from the Coin Battle or Boost Rush menu')
        self.entranceCoinBoost.setValue(globals.Area.startEntranceCoinBoost)

        self.wrap = QtWidgets.QCheckBox('Wrap across Edges')
        self.wrap.setToolTip('<b>Wrap across Edges:</b><br>Makes the stage edges wrap<br>Warning: Wrapping only works correctly where the area is set up in the right way.')
        self.wrap.setChecked(globals.Area.wrapFlag)

        self.unk1 = QtWidgets.QCheckBox('Unknown Option 1')
        self.unk1.setToolTip("<b>Unknown Option 1:</b> We haven't managed to figure out what this does, or if it does anything. This option is turned off in most levels.")
        self.unk1.setChecked(globals.Area.unkFlag1)

        self.unk2 = QtWidgets.QCheckBox('Unknown Option 2')
        self.unk2.setToolTip("<b>Unknown Option 2:</b> We haven't managed to figure out what this does, or if it does anything. This option is turned on in most levels.")
        self.unk2.setChecked(globals.Area.unkFlag2)

        self.unk3 = QtWidgets.QCheckBox('Unknown Option 3')
        self.unk3.setToolTip("<b>Unknown Option 3:</b> We haven't managed to figure out what this does, or if it does anything. This option is turned on in most levels.")
        self.unk3.setChecked(globals.Area.unkFlag3)

        self.unk4 = QtWidgets.QCheckBox('Unknown Option 4')
        self.unk4.setToolTip("<b>Unknown Option 4:</b> We haven't managed to figure out what this does, or if it does anything. This option is turned on in most levels.")
        self.unk4.setChecked(globals.Area.unkFlag4)

        self.timer = QtWidgets.QSpinBox()
        self.timer.setRange(0, 999)
        self.timer.setToolTip('<b>Timer:</b><br>The default Timer. Sets the time limit, in "Mario seconds," for the level.<br><b>Midway Timer Info:</b> The midway timer is calculated by subtracting 100 from this value.')
        self.timer.setValue(globals.Area.timelimit)

        self.timelimit2 = QtWidgets.QSpinBox()
        self.timelimit2.setRange(0, 999)
        self.timelimit2.setToolTip('<b>Timer 2 & 3:</b>This time limit is chosen by the nybble 12 on actor 25, Checkpoint Flag. See actor for details.')
        self.timelimit2.setValue(globals.Area.timelimit2)

        self.timelimit3 = QtWidgets.QSpinBox()
        self.timelimit3.setRange(0, 999)
        self.timelimit3.setToolTip('<b>Timer 2 & 3:</b>This time limit is chosen by the nybble 12 on actor 25, Checkpoint Flag. See actor for details.')
        self.timelimit3.setValue(globals.Area.timelimit3)

        settingsLayout = QtWidgets.QFormLayout()
        settingsLayout.addRow('Timer:', self.timer)
        settingsLayout.addRow('Timer 2:', self.timelimit2)
        settingsLayout.addRow('Timer 3:', self.timelimit3)
        settingsLayout.addRow('Entrance ID:', self.entrance)
        settingsLayout.addRow('Entrance ID 2:', self.entranceCoinBoost)
        settingsLayout.addRow(self.wrap)
        settingsLayout.addRow(self.unk1)
        settingsLayout.addRow(self.unk2)
        settingsLayout.addRow(self.unk3)
        settingsLayout.addRow(self.unk4)

        Layout = QtWidgets.QVBoxLayout()
        Layout.addLayout(settingsLayout)
        Layout.addStretch(1)
        self.setLayout(Layout)


class TilesetsTab(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.tile0 = QtWidgets.QComboBox()

        name = globals.Area.tileset0
        slot = self.HandleTileset0Choice

        self.currentChoice = None

        data = SimpleTilesetNames()

        # First, find the current index and custom-tileset strings
        if name == '':  # No tileset selected, the current index should be None
            ts_index = 'None'  # None
            custom = ''
            custom_fname = '[CUSTOM]'  # [CUSTOM]
        else:  # Tileset selected
            ts_index = 'Custom filename... [name]'.replace('[name]', str(name))  # Custom filename... [name]
            custom = name
            custom_fname = '[CUSTOM] [name]'.replace('[name]', str(name))  # [CUSTOM] [name]

        # Add items to the widget:
        # - None
        self.tile0.addItem('None', '')  # None
        # - Retail Tilesets
        for tfile, tname in data:
            if HasTileset(tfile):
                text = '[name] ([file])'.replace('[name]', str(tname)).replace('[file]', str(tfile))  # [name] ([file])
                self.tile0.addItem(text, tfile)
                if name == tfile:
                    ts_index = text
                    custom = ''
        # - Custom Tileset
        self.tile0.addItem('Custom filename... [name]'.replace('[name]', str(custom)), custom_fname)  # Custom filename... [name]

        # Set the current index
        item_idx = self.tile0.findText(ts_index)
        self.currentChoice = item_idx
        self.tile0.setCurrentIndex(item_idx)

        # Handle combobox changes
        self.tile0.activated.connect(slot)

        ## don't allow ts0 to be removable
        #self.tile0.removeItem(0)

        mainLayout = QtWidgets.QVBoxLayout()
        tile0Box = QtWidgets.QGroupBox('Standard Suite')

        t0 = QtWidgets.QVBoxLayout()
        t0.addWidget(self.tile0)

        tile0Box.setLayout(t0)

        mainLayout.addWidget(tile0Box)
        mainLayout.addStretch(1)
        self.setLayout(mainLayout)

    def HandleTileset0Choice(self, index):
        w = self.tile0

        if index == (w.count() - 1):
            fname = str(w.itemData(index))
            fname = fname[len('[CUSTOM] [name]'.replace('[name]', str(''))):]

            from . import dialogs
            dbox = dialogs.InputBox()
            del dialogs

            dbox.setWindowTitle('Enter a Filename')
            dbox.setWindowFlags(dbox.windowFlags() & ~Qt.WindowContextHelpButtonHint)
            dbox.label.setText('Enter the name of a custom tileset file to use. It must already be inside the level archive in order for Yaz0moto to recognize it.')
            dbox.textbox.setMaxLength(31)
            dbox.textbox.setText(fname)
            result = dbox.exec_()

            if result == QtWidgets.QDialog.Accepted:
                fname = str(dbox.textbox.text())
                if fname.endswith('.szs'): fname = fname[:-4]
                elif fname.endswith('.sarc'): fname = fname[:-5]

                w.setItemText(index, 'Custom filename... [name]'.replace('[name]', str(fname)))
                w.setItemData(index, '[CUSTOM] [name]'.replace('[name]', str(fname)))
            else:
                w.setCurrentIndex(self.currentChoice)
                return

        self.currentChoice = index

    def value(self):
        """
        Returns the main tileset choice
        """
        idx = self.tile0.currentIndex()
        name = str(self.tile0.itemData(idx))
        return name


class LevelViewWidget(QtWidgets.QGraphicsView):
    """
    QGraphicsView subclass for the level view
    """
    PositionHover = QtCore.pyqtSignal(int, int)
    FrameSize = QtCore.pyqtSignal(int, int)
    repaint = QtCore.pyqtSignal()
    dragstamp = False

    def __init__(self, scene, parent):
        """
        Constructor
        """
        super().__init__(scene, parent)

        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor(119,136,153)))
        self.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)
        # self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setMouseTracking(True)
        # self.setOptimizationFlags(QtWidgets.QGraphicsView.IndirectPainting)
        self.YScrollBar = QtWidgets.QScrollBar(Qt.Vertical, parent)
        self.XScrollBar = QtWidgets.QScrollBar(Qt.Horizontal, parent)
        self.setVerticalScrollBar(self.YScrollBar)
        self.setHorizontalScrollBar(self.XScrollBar)
        # Always visible (with a visible track, see style.qss) so the level can be scrolled with them
        self.YScrollBar.setObjectName('levelViewScrollBar')
        self.XScrollBar.setObjectName('levelViewScrollBar')
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        self.currentobj = None
        self.selectionFix = False  # Fixes Qt selection bug
        self.drag_snapshot = {}

        try:
            dpr = self.devicePixelRatioF()
        except AttributeError:
            dpr = self.devicePixelRatio()
        hints = QtGui.QPainter.Antialiasing
        if float(dpr).is_integer():
            hints |= QtGui.QPainter.SmoothPixmapTransform
        self.setRenderHints(hints)

        # Parts dragged from the parts bar or the palettes can be dropped on the level
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)

        # A left press held still on empty space scrolls the view instead of drawing a selection box
        self.longPress = QtCore.QTimer(self)
        self.longPress.setSingleShot(True)
        self.longPress.timeout.connect(self.startLongPressPan)

    def dragEnterEvent(self, event):
        if partsbar.keyFromMime(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if partsbar.keyFromMime(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        key = partsbar.keyFromMime(event.mimeData())
        if key is None:
            return super().dropEvent(event)
        event.acceptProposedAction()
        partsbar.placeAt(self, key, event.pos())
        bar = getattr(globals.mainWindow, 'partsBar', None)
        if bar is not None:
            bar.addRecent(key)

    # ---------------------------------------------------------------- mouse controls
    #
    # Left click on a thing selects it (or, if it was selected, deselects it, putting down the
    # picked part if there is one), and dragging moves the selection around, whether or not
    # a part is picked. Selecting a thing with
    # settings shows them in the properties panel (the right sidebar).
    # Left click on empty space with a part picked (in the palette, the actor icons or the
    # parts bar) or the entrance, path, location, comment or Nabbit path tool: place it,
    # dragging to size it. Alt + left click places on top of things too.
    # On empty space with nothing picked: a click deselects everything, a drag draws a
    # selection box, and a press held still (or a double click) deselects everything and
    # scrolls the view while dragging.
    # Right click: select a thing and show what it is, with its actions (Settings..., Info...
    # for actors, Delete...).
    # Ctrl + right click: the zone menu. Middle drag: scroll.
    #
    # Legacy mouse controls (Preferences > Editor, globals.LegacyMouseControls) are the
    # original ones instead: right click places the picked part or tool anywhere (dragging
    # to size it), and with nothing picked deselects what's under the cursor (or everything);
    # left click only selects and drags (on empty space: the same box and scrolling as
    # above); Shift + right click shows a thing's menu; Ctrl + right click the zone menu.
    #
    # The classicMouse* handlers below are the original ones (right click painted); these
    # translate to them, so placing, sizing and undo work exactly as before.

    LEVEL_ITEMS = (ObjectItem, SpriteItem, EntranceItem, LocationItem, PathItem, NabbitPathItem, CommentItem, ZoneItem)
    TOOL_ITEMS = {5: EntranceItem, 6: PathItem, 7: LocationItem, 9: CommentItem, 12: NabbitPathItem}

    placing = False
    crossCursor = False
    LONG_PRESS_MS = 400
    clickToggle = None  # (thing, was selected, press position, selection before) for a left click on a thing
    panning = False
    panFrom = None
    pressPos = lastPos = None

    def levelItemOf(self, item):
        """The level thing an item belongs to (sprite images etc. count as their sprite), or None."""
        while item is not None and not isinstance(item, self.LEVEL_ITEMS):
            item = item.parentItem()
        return item

    def levelItems(self, pos):
        """The level things under a point of the view, topmost first (sprite images etc. count as their sprite)."""
        out = []
        for item in self.items(pos):
            item = self.levelItemOf(item)
            if item is not None and item not in out:
                out.append(item)
        return out

    def grabbableAt(self, pos):
        """Whether there's a thing at pos that a left click selects or drags (not just a zone's inside)."""
        flags = QtWidgets.QGraphicsItem.ItemIsSelectable | QtWidgets.QGraphicsItem.ItemIsMovable
        return any(item.isVisible() and int(item.flags()) & int(flags) for item in self.levelItems(pos))

    @classmethod
    def canPlace(cls):
        """Whether a part (or a placing tool) is picked, so a click can place something."""
        return partsbar.isArmed() or globals.CurrentPaintType in cls.TOOL_ITEMS

    def wouldPlace(self, pos):
        """
        Whether a left click at pos places something (rather than selecting): with a part
        picked or a placing tool, on space with nothing a click selects. With Alt held it
        places on top of things too. Never with the legacy controls (right click places).
        """
        if globals.LegacyMouseControls or not self.canPlace():
            return False
        if QtWidgets.QApplication.keyboardModifiers() == Qt.AltModifier:
            return True
        return not self.grabbableAt(pos)

    @staticmethod
    def withButton(event, type_, button, buttons):
        return QtGui.QMouseEvent(type_, event.localPos(), event.windowPos(), event.screenPos(),
                                 button, buttons, Qt.NoModifier)

    def mousePressEvent(self, event):
        button = event.button()
        modifiers = QtWidgets.QApplication.keyboardModifiers()

        mw = globals.mainWindow
        legacy = globals.LegacyMouseControls
        plainLeft = button == Qt.LeftButton and event.buttons() == Qt.LeftButton and modifiers == Qt.NoModifier
        altLeft = button == Qt.LeftButton and event.buttons() == Qt.LeftButton and modifiers == Qt.AltModifier
        onlyRight = button == Qt.RightButton and event.buttons() == Qt.RightButton

        if (plainLeft or altLeft) and self.wouldPlace(event.pos()):
            self.placing = True
            # A placed thing is selected without opening the properties panel
            mw.panelStaysShut = True
            try:
                self.classicMousePressEvent(self.withButton(event, QtCore.QEvent.MouseButtonPress, Qt.RightButton, Qt.RightButton))
            finally:
                mw.panelStaysShut = False
            return

        if legacy and onlyRight and modifiers == Qt.ShiftModifier:
            event.accept()
            self.showItemMenu(event)
            return

        if legacy and onlyRight and modifiers != Qt.ControlModifier:
            event.accept()
            if self.canPlace():
                # The original right-click placing (classicMouseMoveEvent sizes it as it's dragged)
                mw.panelStaysShut = True
                try:
                    self.classicMousePressEvent(self.withButton(event, QtCore.QEvent.MouseButtonPress, Qt.RightButton, Qt.RightButton))
                finally:
                    mw.panelStaysShut = False
            else:
                self.deselectAt(event.pos())
            return

        if not legacy and onlyRight and modifiers != Qt.ControlModifier:
            event.accept()
            self.showItemMenu(event)
            return

        before = set(self.scene().selectedItems()) if plainLeft else None
        self.classicMousePressEvent(event)
        if button != Qt.LeftButton or event.buttons() != Qt.LeftButton:
            return

        grabber = self.scene().mouseGrabberItem()
        if grabber is None:
            # Nothing grabbed the press, so this is a rubber-band drag: what it passes over is
            # selected quietly. Held still instead, it scrolls the view (startLongPressPan).
            self.rubberBanding = True
            globals.mainWindow.quietSelection = True
            if plainLeft:
                self.pressPos = self.lastPos = event.pos()
                self.longPress.start(self.LONG_PRESS_MS)
        elif plainLeft and not legacy:  # the legacy controls deselect with right click instead
            item = self.levelItemOf(grabber)
            if item is not None and int(item.flags()) & int(QtWidgets.QGraphicsItem.ItemIsSelectable):
                self.clickToggle = (item, item in before, event.pos(), before)

    rubberBanding = False

    def mouseDoubleClickEvent(self, event):
        if (event.button() == Qt.LeftButton and QtWidgets.QApplication.keyboardModifiers() == Qt.NoModifier
                and not self.wouldPlace(event.pos()) and not self.grabbableAt(event.pos())):
            # A double click on empty space deselects everything; dragging on from it scrolls
            event.accept()
            self.scene().clearSelection()
            self.beginPan(event.pos())
            return
        super().mouseDoubleClickEvent(event)

    def startLongPressPan(self):
        """A left press held still on empty space: the selection box goes and dragging scrolls the view."""
        if not self.rubberBanding or not QtWidgets.QApplication.mouseButtons() & Qt.LeftButton:
            return
        # End the (still empty) selection box; the press already deselected everything
        QtWidgets.QGraphicsView.mouseReleaseEvent(self, QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonRelease, QtCore.QPointF(self.pressPos), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        self.rubberBanding = False
        globals.mainWindow.quietSelection = False
        self.beginPan(self.lastPos)

    def beginPan(self, pos):
        self.panning = True
        self.panFrom = pos
        self.viewport().setCursor(Qt.ClosedHandCursor)
        self.crossCursor = False

    def endPan(self):
        self.panning = False
        self.viewport().unsetCursor()

    def dragChanged(self):
        """Whether the things grabbed by the current left press were moved or resized."""
        for item, old in self.drag_snapshot.items():
            try:
                if isinstance(item, (ObjectItem, ZoneItem, LocationItem)):
                    new = (item.objx, item.objy, item.width, item.height)
                else:
                    new = (item.objx, item.objy)
            except (RuntimeError, AttributeError):
                continue
            if new != old:
                return True
        return False

    def deselectAt(self, pos):
        """
        The legacy controls' right click with nothing picked: deselects the thing under the
        cursor if it's selected, otherwise everything.
        """
        selected = [item for item in self.levelItems(pos) if item.isSelected()]
        if selected:
            self.setSelection(set(self.scene().selectedItems()) - {selected[0]})
        else:
            self.scene().clearSelection()

    def setSelection(self, items):
        """Selects exactly these things, updating the panels once."""
        mw = globals.mainWindow
        mw.SelectionUpdateFlag = True
        try:
            for item in self.scene().selectedItems():
                if item not in items:
                    item.setSelected(False)
            for item in items:
                try:
                    item.setSelected(True)
                except RuntimeError:
                    pass  # deleted in the meantime
        finally:
            mw.SelectionUpdateFlag = False
        mw.ChangeSelectionHandler()

    def viewportEvent(self, event):
        # No tooltips about the things passed over while a button is held (dragging)
        if event.type() == QtCore.QEvent.ToolTip and QtWidgets.QApplication.mouseButtons() != Qt.NoButton:
            return True
        return super().viewportEvent(event)

    def mouseMoveEvent(self, event):
        if self.panning:
            offset = self.panFrom - event.pos()
            self.panFrom = event.pos()
            self.YScrollBar.setValue(self.YScrollBar.value() + offset.y())
            self.XScrollBar.setValue(self.XScrollBar.value() + (-offset.x() if self.isRightToLeft() else offset.x()))
            return

        # Moving soon after the press makes it a selection box, not a scroll
        if self.longPress.isActive():
            self.lastPos = event.pos()
            if (event.pos() - self.pressPos).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                self.longPress.stop()

        if self.placing and event.buttons() & Qt.LeftButton:
            self.classicMouseMoveEvent(self.withButton(event, QtCore.QEvent.MouseMove, Qt.NoButton, Qt.RightButton))
            return

        # A crosshair where clicking places the picked part (not over things, which a click
        # selects; with the legacy controls, right click places anywhere)
        if event.buttons() == Qt.NoButton:
            places = partsbar.isArmed() and (globals.LegacyMouseControls or self.wouldPlace(event.pos()))
            if places and not self.crossCursor:
                self.viewport().setCursor(Qt.CrossCursor)
            elif not places and self.crossCursor:
                self.viewport().unsetCursor()
            self.crossCursor = places

        self.classicMouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.longPress.stop()
            if self.panning:
                self.endPan()
                return

        if self.placing and event.button() == Qt.LeftButton:
            self.placing = False
            self.classicMouseReleaseEvent(self.withButton(event, QtCore.QEvent.MouseButtonRelease, Qt.RightButton, Qt.NoButton))
            return

        toggle = None
        if event.button() == Qt.LeftButton:
            toggle, self.clickToggle = self.clickToggle, None
        changed = toggle is not None and self.dragChanged()  # before the release forgets the drag

        self.classicMouseReleaseEvent(event)

        # A click (no drag) on a thing that was already selected deselects it, keeping the rest.
        # With a part picked (e.g. the thing just placed), that puts the part down too, so
        # it's deselected everywhere: the palette, the parts bar and the level
        if toggle is not None:
            item, wasSelected, pos, before = toggle
            if (wasSelected and not changed
                    and (event.pos() - pos).manhattanLength() < QtWidgets.QApplication.startDragDistance()):
                self.setSelection(before - {item})
                if partsbar.isArmed():
                    partsbar.disarm()

        if self.rubberBanding and event.button() == Qt.LeftButton:
            self.rubberBanding = False
            mw = globals.mainWindow
            mw.quietSelection = False
            # The properties panel (if it's open) and the parts bar catch up with what the box selected
            mw.panelStaysShut = True
            try:
                mw.ChangeSelectionHandler()
            finally:
                mw.panelStaysShut = False

    def placeAt(self, pos):
        """Places the picked part at a point of the view (used for drag and drop)."""
        point = QtCore.QPointF(pos)
        mw = globals.mainWindow
        mw.panelStaysShut = True
        try:
            self.classicMousePressEvent(QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, point, Qt.RightButton,
                                                          Qt.RightButton, Qt.NoModifier))
        finally:
            mw.panelStaysShut = False
        self.classicMouseReleaseEvent(QtGui.QMouseEvent(QtCore.QEvent.MouseButtonRelease, point, Qt.RightButton,
                                                        Qt.NoButton, Qt.NoModifier))

    @staticmethod
    def describe(item):
        """A short description of a level thing, for its right-click menu."""
        if isinstance(item, SpriteItem):
            from . import spriteicons
            return '%s (actor %s)' % (spriteicons.spriteName(item.type), item.type)
        if isinstance(item, ObjectItem):
            return 'Tileset %d, object %d - %dx%d tiles, layer %d' % (item.tileset + 1, item.type, item.width,
                                                                     item.height, item.layer)
        if isinstance(item, EntranceItem):
            names = getattr(globals, 'EntranceTypeNames', None) or []
            kind = names[item.enttype] if 0 <= item.enttype < len(names) else 'type (%d)' % item.enttype
            return 'Entrance %d - %s' % (item.entid, kind)
        if isinstance(item, LocationItem):
            return 'Location %d' % item.id
        if isinstance(item, NabbitPathItem):
            return 'Nabbit path node'
        if isinstance(item, PathItem):
            return 'Path %d, node %d' % (item.pathid, item.nodeid)
        if isinstance(item, CommentItem):
            text = item.text.replace('\n', ' ')
            return 'Comment: ' + (text[:40] + '...' if len(text) > 40 else text)
        if isinstance(item, ZoneItem):
            return 'Zone %d' % (item.id + 1)
        return 'Item'

    def showActorInfo(self, sprite):
        """The right-click menu's Info: what an actor is and where, with its notes."""
        from html import escape
        from . import spriteicons
        if isinstance(sprite.type, str):
            sdef = globals.CustomSpriteDefinitions.get(sprite.type)
        elif 0 <= sprite.type < len(globals.Sprites or ()):
            sdef = globals.Sprites[sprite.type]
        else:
            sdef = None

        zone = sprite.nearestZone(True)
        data = bytes(sprite.spritedata)
        raw = ' '.join(data[i:i + 2].hex() for i in range(0, len(data), 2))
        rows = [
            ('Actor', '%s (ID %s)' % (escape(spriteicons.spriteName(sprite.type)), escape(str(sprite.type)))),
            ('Position', '%d, %d (tile %d, %d)' % (sprite.objx, sprite.objy, sprite.objx // 16, sprite.objy // 16)),
            ('Zone', escape(zone.title) if zone is not None else 'None (outside every zone)'),
            ('Layer', str(sprite.layer)),
            ('Initial state', str(sprite.initialState)),
            ('Raw data', '<code>%s</code>' % raw),
            # A patch icon for just this setting of the actor (see spriteicons)
            ('Icon for this data', '<code>icons/%s-%s.png</code>' % (escape(str(sprite.type)), spriteicons.rawDataName(data))),
        ]
        if sdef is None:
            rows.append(('Definition', 'Unknown actor: it has no definition in this game or its patches'))
        text = '<table cellspacing="4">%s</table>' % ''.join(
            '<tr><td><b>%s:</b></td><td>%s</td></tr>' % row for row in rows)
        if sdef is not None and sdef.notes:
            text += '<p><b>Notes:</b><br>%s</p>' % sdef.notes
        if sdef is not None and sdef.relatedObjFiles:
            text += '<p><b>Object files:</b><br>%s</p>' % sdef.relatedObjFiles

        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, 'Actor Info', text,
                                    QtWidgets.QMessageBox.Close, self)
        box.setTextFormat(Qt.RichText)
        box.setTextInteractionFlags(Qt.TextSelectableByMouse)  # so the raw data and icon name can be copied
        box.exec_()

    def showItemMenu(self, event):
        """
        Right click: select the thing under the cursor and show what it is, with its actions
        (Settings... opens its properties panel). On empty space, a picked part is put down.
        """
        items = self.levelItems(event.pos())
        # A zone lies over everything in it, so it only counts when nothing else is there
        items.sort(key=lambda i: isinstance(i, ZoneItem))
        mw = globals.mainWindow
        if not items:
            if partsbar.isArmed():
                partsbar.disarm()
            return

        item = items[0]
        if not item.isSelected():
            self.setSelection({item})

        menu = QtWidgets.QMenu(self)
        title = menu.addAction(self.describe(item))
        title.setEnabled(False)
        menu.addSeparator()
        if isinstance(item, ZoneItem):
            menu.addAction(mw.actions['zones'])
        else:
            # Settings open in the properties panel (the right sidebar), for things that have them
            if isinstance(item, (SpriteItem, EntranceItem, LocationItem, PathItem, NabbitPathItem)):
                settings = menu.addAction(GetIcon('settings'), 'Settings...', mw.ShowPropertiesPanel)
                menu.setDefaultAction(settings)
            if isinstance(item, SpriteItem):
                menu.addAction(GetIcon('info'), 'Info...', lambda: self.showActorInfo(item))
            menu.addSeparator()
            for name in ('copy', 'cut', 'duplicate', 'raise', 'lower'):
                action = mw.actions.get(name)
                if action is not None and action.isEnabled():
                    menu.addAction(action)
            menu.addSeparator()
            delete = menu.addAction(GetIcon('delete'), 'Delete')
            delete.triggered.connect(lambda: QtWidgets.QApplication.sendEvent(
                mw, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)))
        menu.exec_(event.globalPos())

    def showZoneMenu(self, event):
        """
        Ctrl + right click on a zone: background preview options.
        Returns False if there's no zone under the cursor.
        """
        pos = self.mapToScene(event.pos())
        mult = globals.TileWidth / 16
        zones = [z for z in getattr(globals.Area, 'zones', ())
                 if QtCore.QRectF(z.objx * mult, z.objy * mult, z.width * mult, z.height * mult).contains(pos)]
        if not zones:
            return False

        # The smallest zone is the one most likely meant when they overlap
        zone = min(zones, key=lambda z: z.width * z.height)
        mw = globals.mainWindow

        menu = QtWidgets.QMenu(self)
        menu.addSection(zone.title)
        render = menu.addAction('Render Background Preview')
        render.setEnabled(globals.IsNSMBUDX)
        if not globals.IsNSMBUDX:
            render.setToolTip('Only available for New Super Mario Bros. U Deluxe')
        clear = menu.addAction('Clear Background Preview')
        clear.setEnabled(zone.bgPreview is not None)

        chosen = menu.exec_(event.globalPos())
        if chosen is render:
            mw.RenderZoneBackground(zone)
        elif chosen is clear:
            mw.ClearZoneBackground(zone)

        return True

    def classicMousePressEvent(self, event):
        """
        Overrides mouse pressing events if needed
        """
        # The button that triggered this event
        eventButton = event.button()

        # Currently held buttons
        eventButtons = event.buttons()

        # Do not allow processing more than one held button at a time
        # It triggers many bugs in Qt
        if eventButton != eventButtons:
            if eventButton == Qt.LeftButton and not self.currentobj:
                # Left button has been pressed as another button is already being held
                # This causes an interesting bug where any selected object jumps to the cursor
                self.selectionFix = True
                globals.app.restoreOverrideCursor()
                self.scene().clearSelection()

            event.accept()
            return

        if eventButton == Qt.MidButton:
            self.__prevMousePos = event.pos()
            event.accept()

        elif (eventButton == Qt.RightButton
              and QtWidgets.QApplication.keyboardModifiers() == Qt.ControlModifier
              and self.showZoneMenu(event)):
            event.accept()

        elif eventButton == Qt.RightButton:
            if globals.CurrentPaintType in (0, 1, 2, 3) and globals.CurrentObject != -1:
                # return if the Embedded tab is empty
                if (globals.CurrentPaintType in (1, 2, 3)
                    and not len(globals.mainWindow.objPicker.objTS123Tab.getActiveModel().items)):
                    globals.CurrentObject = -1
                    return

                # paint an object
                clicked = self.mapToScene(event.x(), event.y())
                if clicked.x() < 0: clicked.setX(0)
                if clicked.y() < 0: clicked.setY(0)
                clickedx = int(clicked.x() / globals.TileWidth)
                clickedy = int(clicked.y() / globals.TileWidth)

                ln = globals.CurrentLayer
                layer = globals.Area.layers[globals.CurrentLayer]
                if len(layer) == 0:
                    z = (2 - ln) * 8192
                else:
                    z = layer[-1].zValue() + 1

                if globals.PlaceObjectFullSize:
                    defs = globals.ObjectDefinitions[globals.CurrentPaintType]
                    if defs is not None and defs[globals.CurrentObject] is not None:
                        ow = defs[globals.CurrentObject].width
                        oh = defs[globals.CurrentObject].height
                    else:
                        ow, oh = 1, 1
                else:
                    ow, oh = 1, 1
                obj = ObjectItem(globals.CurrentPaintType, globals.CurrentObject, ln, clickedx, clickedy, ow, oh, z, 0)
                mw = globals.mainWindow
                obj.positionChanged = mw.HandleObjPosChange
                globals.UndoManager.push(undomanager.AddObjectCommand(obj, ln, z))

                self.dragstamp = False
                self.currentobj = obj
                self.dragstartx = clickedx
                self.dragstarty = clickedy

                self.scene().clearSelection()
                obj.setSelected(True)
                
                SetDirty()

            elif globals.CurrentPaintType == 10 and globals.CurrentObject != -1:
                assert globals.CurrentObject == globals.ObjectAllDefinitions[globals.CurrentObject].objAllIndex
                type_ = globals.CurrentObject

                # Check if the object is already in one of the tilesets
                if globals.CurrentObject in globals.ObjectAddedtoEmbedded[globals.CurrentArea][globals.mainWindow.folderPicker.currentIndex()]:
                    (globals.CurrentPaintType,
                     globals.CurrentObject) = globals.ObjectAddedtoEmbedded[globals.CurrentArea][globals.mainWindow.folderPicker.currentIndex()][
                         globals.CurrentObject]

                # Try to add the object to one of the tilesets
                else:
                    # Get the object definition, collision data, image and normal map
                    obj = globals.ObjectAllDefinitions[globals.CurrentObject]
                    colldata = globals.ObjectAllCollisions[globals.CurrentObject]
                    img, nml = globals.ObjectAllImages[globals.CurrentObject]

                    # Add the object to one of the tilesets and set CurrentPaintType and CurrentObject
                    (globals.CurrentPaintType,
                     globals.CurrentObject) = addObjToTileset(obj, colldata, img, nml, True)

                    # Checks if the object fit in one of the tilesets
                    if globals.CurrentPaintType == 10:
                        # Revert CurrentObject back to what it was
                        globals.CurrentObject = type_

                        # Throw a messagebox because the object didn't fit
                        QtWidgets.QMessageBox.critical(None, 'Cannot Paint', "There isn't enough room left for this object!")
                        return

                    # Add the object to ObjectAddedtoEmbedded
                    globals.ObjectAddedtoEmbedded[globals.CurrentArea][obj.folderIndex][type_] = (globals.CurrentPaintType, globals.CurrentObject)

                # paint an object
                clicked = self.mapToScene(event.x(), event.y())
                if clicked.x() < 0: clicked.setX(0)
                if clicked.y() < 0: clicked.setY(0)
                clickedx = int(clicked.x() / globals.TileWidth)
                clickedy = int(clicked.y() / globals.TileWidth)

                ln = globals.CurrentLayer
                layer = globals.Area.layers[globals.CurrentLayer]
                if len(layer) == 0:
                    z = (2 - ln) * 8192
                else:
                    z = layer[-1].zValue() + 1

                obj = ObjectItem(globals.CurrentPaintType, globals.CurrentObject, ln, clickedx, clickedy, 1, 1, z, 0)
                mw = globals.mainWindow
                obj.positionChanged = mw.HandleObjPosChange
                globals.UndoManager.push(undomanager.AddObjectCommand(obj, ln, z))

                self.dragstamp = False
                self.currentobj = obj
                self.dragstartx = clickedx
                self.dragstarty = clickedy

                self.scene().clearSelection()
                obj.setSelected(True)

                SetDirty()

                globals.CurrentPaintType = 10
                globals.CurrentObject = type_

            elif globals.CurrentPaintType == 4 and globals.CurrentSprite != -1:
                # paint a sprite
                clicked = self.mapToScene(event.x(), event.y())
                if clicked.x() < 0: clicked.setX(0)
                if clicked.y() < 0: clicked.setY(0)

                selected_type = globals.CurrentSprite
                if isinstance(selected_type, str):
                    try:
                        selected_type = globals.Level.id_manager.get_id_for_string(selected_type)
                    except ValueError as e:
                        QtWidgets.QMessageBox.warning(self, 'Cannot Place Actor', str(e))
                        return

                if isinstance(selected_type, int) and selected_type >= 0:  # fixes a bug -Treeki
                    # [18:15:36]  Angel-SL: I found a bug in Reggie
                    # [18:15:42]  Angel-SL: you can paint a 'No sprites found'
                    # [18:15:47]  Angel-SL: results in a sprite -2

                    if selected_type == 564:
                        # Get the previous flower/grass type
                        oldGrassType = 5
                        for sprite in globals.Area.sprites:
                            if sprite.type == 564:
                                oldGrassType = min(sprite.spritedata[5] & 0xf, 5)
                                if oldGrassType < 2:
                                    oldGrassType = 0

                                elif oldGrassType in [3, 4]:
                                    oldGrassType = 3

                    # paint a sprite
                    clickedx = int((clicked.x() - globals.TileWidth / 2) / globals.TileWidth * 16)
                    clickedy = int((clicked.y() - globals.TileWidth / 2) / globals.TileWidth * 16)

                    if clickedx % 8 < 4:
                        clickedx -= (clickedx % 8)
                    else:
                        clickedx += 8 - (clickedx % 8)
                    if clickedy % 8 < 4:
                        clickedy -= (clickedy % 8)
                    else:
                        clickedy += 8 - (clickedy % 8)

                    data = globals.mainWindow.defaultDataEditor.data
                    spr = SpriteItem(selected_type, clickedx, clickedy, data)

                    mw = globals.mainWindow
                    spr.positionChanged = mw.HandleSprPosChange
                    spr.listitem = ListWidgetItem_SortsByOther(spr)
                    
                    globals.UndoManager.push(undomanager.AddSpriteCommand(spr))

                    if selected_type == 564:
                        # Get the current flower/grass type
                        grassType = 5
                        for sprite in globals.Area.sprites:
                            if sprite.type == 564:
                                grassType = min(sprite.spritedata[5] & 0xf, 5)
                                if grassType < 2:
                                    grassType = 0

                                elif grassType in [3, 4]:
                                    grassType = 3

                        # If the current type is not the previous type, reprocess the Overrides
                        # update the objects and flower sprite instances and update the scene
                        if grassType != oldGrassType and globals.Area.tileset0:
                            ProcessOverrides(globals.Area.tileset0)
                            mw.objPicker.LoadFromTilesets()
                            for layer in globals.Area.layers:
                                for tObj in layer:
                                    tObj.updateObjCache()

                            for sprite in globals.Area.sprites:
                                if sprite.type == 546:
                                    sprite.UpdateDynamicSizing()

                            mw.scene.update()

                    self.dragstamp = False
                    self.currentobj = spr
                    self.dragstartx = clickedx
                    self.dragstarty = clickedy

                    self.scene().update()

                    spr.UpdateDynamicSizing()
                    spr.UpdateListItem()

                    self.scene().clearSelection()
                    spr.setSelected(True)

                SetDirty()

            elif globals.CurrentPaintType == 5:
                # paint an entrance
                clicked = self.mapToScene(event.x(), event.y())
                if clicked.x() < 0: clicked.setX(0)
                if clicked.y() < 0: clicked.setY(0)
                clickedx = int((clicked.x() - globals.TileWidth / 2) / globals.TileWidth * 16)
                clickedy = int((clicked.y() - globals.TileWidth / 2) / globals.TileWidth * 16)

                if clickedx % 8 < 4:
                    clickedx -= (clickedx % 8)
                else:
                    clickedx += 8 - (clickedx % 8)
                if clickedy % 8 < 4:
                    clickedy -= (clickedy % 8)
                else:
                    clickedy += 8 - (clickedy % 8)

                getids = [False for x in range(256)]
                for ent in globals.Area.entrances: getids[ent.entid] = True
                minimumID = getids.index(False)

                ent = EntranceItem(clickedx, clickedy, 0, 0, minimumID, 0, 0, 0, 0, 0, 0, 0x80, 0, 0, 0, 0, 0)
                mw = globals.mainWindow
                ent.positionChanged = mw.HandleEntPosChange

                ent.listitem = ListWidgetItem_SortsByOther(ent)

                globals.UndoManager.push(undomanager.AddEntranceCommand(ent))
                ent.UpdateListItem()

                self.scene().clearSelection()
                ent.setSelected(True)

            elif globals.CurrentPaintType == 6:
                # paint a path node
                clicked = self.mapToScene(event.x(), event.y())
                if clicked.x() < 0: clicked.setX(0)
                if clicked.y() < 0: clicked.setY(0)
                clickedx = int((clicked.x() - globals.TileWidth / 2) / globals.TileWidth * 16)
                clickedy = int((clicked.y() - globals.TileWidth / 2) / globals.TileWidth * 16)
                if clickedx % 8 < 4:
                    clickedx -= (clickedx % 8)
                else:
                    clickedx += 8 - (clickedx % 8)
                if clickedy % 8 < 4:
                    clickedy -= (clickedy % 8)
                else:
                    clickedy += 8 - (clickedy % 8)
                mw = globals.mainWindow
                plist = mw.pathList
                selectedpn = None if len(plist.selectedItems()) < 1 else plist.selectedItems()[0]
                # if selectedpn is None:
                #    QtWidgets.QMessageBox.warning(None, 'Error', 'No pathnode selected. Select a pathnode of the path you want to create a new node in.')
                if selectedpn is None:
                    getids = [False for x in range(256)]
                    getids[90] = True  # Skip Nabbit path
                    for pathdatax in globals.Area.pathdata:
                        # if(len(pathdatax['nodes']) > 0):
                        getids[int(pathdatax['id'])] = True

                    newpathid = getids.index(False)
                    newpathdata = {'id': newpathid,
                                   'unk1': 0,
                                   'nodes': [
                                       {'x': clickedx, 'y': clickedy, 'speed': 1.0, 'accel': 1.0, 'delay': 0}],
                                   'loops': False
                                   }
                    newnode = PathItem(clickedx, clickedy, newpathdata, newpathdata['nodes'][0], 0, 0, 0, 0)
                    newnode.positionChanged = mw.HandlePathPosChange
                    newnode.listitem = ListWidgetItem_SortsByOther(newnode)

                    globals.UndoManager.push(undomanager.AddPathNodeCommand(newpathdata, newpathdata['nodes'][0], newnode, False))

                    self.dragstamp = False
                    self.currentobj = newnode
                    self.dragstartx = clickedx
                    self.dragstarty = clickedy

                    newnode.UpdateListItem()

                    self.scene().clearSelection()
                    newnode.setSelected(True)
                else:
                    pathd = None
                    for pathnode in globals.Area.paths:
                        if pathnode.listitem == selectedpn:
                            pathd = pathnode.pathinfo

                    if not pathd: return  # shouldn't happen

                    # Insert after selected node and copy its properties
                    insert_idx = -1
                    copy_data = {'speed': 1.0, 'accel': 1.0, 'delay': 0}
                    if selectedpn:
                        for idx, n in enumerate(pathd['nodes']):
                            if n['graphicsitem'].listitem == selectedpn:
                                insert_idx = idx + 1
                                for key in ['speed', 'accel', 'delay']:
                                    copy_data[key] = n.get(key, 0)
                                break
                    
                    if insert_idx == -1:
                        insert_idx = len(pathd['nodes'])
                        if len(pathd['nodes']) > 0:
                            last_n = pathd['nodes'][-1]
                            for key in ['speed', 'accel', 'delay']:
                                copy_data[key] = last_n.get(key, 0)

                    newnodedata = {'x': clickedx, 'y': clickedy}
                    newnodedata.update(copy_data)

                    pathd['nodes'].insert(insert_idx, newnodedata)

                    newnode = PathItem(clickedx, clickedy, pathd, newnodedata, 0, 0, 0, 0)

                    newnode.positionChanged = mw.HandlePathPosChange
                    newnode.listitem = ListWidgetItem_SortsByOther(newnode)

                    globals.UndoManager.push(undomanager.AddPathNodeCommand(pathd, newnodedata, newnode, False, insert_idx))

                    self.dragstamp = False
                    self.currentobj = newnode
                    self.dragstartx = clickedx
                    self.dragstarty = clickedy

                    newnode.UpdateListItem()

                    self.scene().clearSelection()
                    newnode.setSelected(True)

            elif globals.CurrentPaintType == 7:
                # paint a location
                clicked = self.mapToScene(event.x(), event.y())
                if clicked.x() < 0: clicked.setX(0)
                if clicked.y() < 0: clicked.setY(0)

                clickedx = int(clicked.x() // globals.TileWidth) * 16
                clickedy = int(clicked.y() // globals.TileWidth) * 16

                allID = set()  # faster 'x in y' lookups for sets
                newID = 1
                for i in globals.Area.locations:
                    allID.add(i.id)

                while newID <= 255:
                    if newID not in allID:
                        break
                    newID += 1

                loc = LocationItem(clickedx, clickedy, 16, 16, newID)

                mw = globals.mainWindow
                loc.positionChanged = mw.HandleLocPosChange
                loc.sizeChanged = mw.HandleLocSizeChange
                loc.listitem = ListWidgetItem_SortsByOther(loc)
                
                globals.UndoManager.push(undomanager.AddLocationCommand(loc))

                self.dragstamp = False
                self.currentobj = loc
                self.dragstartx = clickedx
                self.dragstarty = clickedy

                self.scene().update()
                loc.UpdateListItem()

                self.scene().clearSelection()
                loc.setSelected(True)

            elif globals.CurrentPaintType == 8:
                # paint a clip
                clicked = self.mapToScene(event.x(), event.y())
                if clicked.x() < 0: clicked.setX(0)
                if clicked.y() < 0: clicked.setY(0)

                clickedx = int(clicked.x() / globals.TileWidth * 16)
                clickedy = int(clicked.y() / globals.TileWidth * 16)

                clip = globals.mainWindow.clipChooser.current_clip()
                if clip is not None:
                    # Get the previous flower/grass type
                    oldGrassType = 5
                    for sprite in globals.Area.sprites:
                        if sprite.type == 564:
                            oldGrassType = min(sprite.spritedata[5] & 0xf, 5)
                            if oldGrassType < 2:
                                oldGrassType = 0

                            elif oldGrassType in [3, 4]:
                                oldGrassType = 3

                    objs = globals.mainWindow.placeEncodedObjects(clip.miyamoto_clip, True, clickedx, clickedy)

                    # Get the current flower/grass type
                    grassType = 5
                    for sprite in globals.Area.sprites:
                        if sprite.type == 564:
                            grassType = min(sprite.spritedata[5] & 0xf, 5)
                            if grassType < 2:
                                grassType = 0

                            elif grassType in [3, 4]:
                                grassType = 3

                    # If the current type is not the previous type, reprocess the Overrides
                    # update the objects and flower sprite instances and update the scene
                    if grassType != oldGrassType and globals.Area.tileset0:
                        ProcessOverrides(globals.Area.tileset0)
                        globals.mainWindow.objPicker.LoadFromTilesets()
                        for layer in globals.Area.layers:
                            for tObj in layer:
                                tObj.updateObjCache()

                        for sprite in globals.Area.sprites:
                            if sprite.type == 546:
                                sprite.UpdateDynamicSizing()

                    for obj in objs:
                        obj.dragstartx = obj.objx
                        obj.dragstarty = obj.objy
                        obj.update()

                    globals.mainWindow.scene.update()

                    self.dragstamp = True
                    self.dragstartx = clickedx
                    self.dragstarty = clickedy
                    self.currentobj = objs

            elif globals.CurrentPaintType == 9:
                # paint a comment

                clicked = self.mapToScene(event.x(), event.y())
                if clicked.x() < 0: clicked.setX(0)
                if clicked.y() < 0: clicked.setY(0)
                clickedx = int((clicked.x() - globals.TileWidth / 2) / globals.TileWidth * 16)
                clickedy = int((clicked.y() - globals.TileWidth / 2) / globals.TileWidth * 16)

                if clickedx % 8 < 4:
                    clickedx -= (clickedx % 8)
                else:
                    clickedx += 8 - (clickedx % 8)
                if clickedy % 8 < 4:
                    clickedy -= (clickedy % 8)
                else:
                    clickedy += 8 - (clickedy % 8)

                com = CommentItem(clickedx, clickedy, '')
                mw = globals.mainWindow
                com.positionChanged = mw.HandleComPosChange
                com.textChanged = mw.HandleComTxtChange
                com.listitem = QtWidgets.QListWidgetItem()

                globals.UndoManager.push(undomanager.AddCommentCommand(com))
                com.UpdateListItem()

                self.scene().clearSelection()
                com.setSelected(True)

                SetDirty()


            elif globals.CurrentPaintType == 12:
                if globals.Area.areanum == 1:
                    # paint a nabbit path node
                    clicked = self.mapToScene(event.x(), event.y())
                    if clicked.x() < 0: clicked.setX(0)
                    if clicked.y() < 0: clicked.setY(0)
                    clickedx = int((clicked.x() - globals.TileWidth / 2) / globals.TileWidth * 16) + 8
                    clickedy = int((clicked.y() - globals.TileWidth / 2) / globals.TileWidth * 16) + 8
                    if clickedx % 8 < 4:
                        clickedx -= (clickedx % 8)
                    else:
                        clickedx += 8 - (clickedx % 8)
                    if clickedy % 8 < 4:
                        clickedy -= (clickedy % 8)
                    else:
                        clickedy += 8 - (clickedy % 8)
                    mw = globals.mainWindow
                    plist = mw.nabbitPathList
                    selectedpn = None if len(plist.selectedItems()) < 1 else plist.selectedItems()[0]
                    if not globals.Area.nPathdata:
                        newpathdata = {'nodes': [
                                           {'x': clickedx, 'y': clickedy, 'action': 0,
                                            'unk1': 0, 'unk2': 0, 'unk3': 0, 'unk4': 0}],
                                       }
                        newnode = NabbitPathItem(clickedx, clickedy, newpathdata, newpathdata['nodes'][0], 0, 0, 0, 0)
                        newnode.positionChanged = mw.HandlePathPosChange

                        peline = NabbitPathEditorLineItem(newpathdata['nodes'])
                        newpathdata['peline'] = peline

                        newnode.listitem = ListWidgetItem_SortsByOther(newnode)
                        
                        globals.UndoManager.push(undomanager.AddPathNodeCommand(newpathdata, newpathdata['nodes'][0], newnode, True))

                        self.dragstamp = False
                        self.currentobj = newnode
                        self.dragstartx = clickedx
                        self.dragstarty = clickedy

                        newnode.UpdateListItem()

                        self.scene().clearSelection()
                        newnode.setSelected(True)
                    else:
                        pathd = None
                        for pathnode in globals.Area.nPaths:
                            if selectedpn and pathnode.listitem == selectedpn:
                                pathd = pathnode.pathinfo

                        if not pathd:
                            pathd = globals.Area.nPaths[-1].pathinfo

                        # Insert after selected node and copy its properties
                        insert_idx = -1
                        copy_data = {'action': 0, 'unk1': 0, 'unk2': 0, 'unk3': 0, 'unk4': 0}
                        if selectedpn:
                            for idx, n in enumerate(pathd['nodes']):
                                if n['graphicsitem'].listitem == selectedpn:
                                    insert_idx = idx + 1
                                    for key in ['action', 'unk1', 'unk2', 'unk3', 'unk4']:
                                        copy_data[key] = n.get(key, 0)
                                    break
                        
                        if insert_idx == -1:
                            insert_idx = len(pathd['nodes'])
                            if len(pathd['nodes']) > 0:
                                last_n = pathd['nodes'][-1]
                                for key in ['action', 'unk1', 'unk2', 'unk3', 'unk4']:
                                    copy_data[key] = last_n.get(key, 0)

                        newnodedata = {'x': clickedx, 'y': clickedy}
                        newnodedata.update(copy_data)

                        pathd['nodes'].insert(insert_idx, newnodedata)

                        newnode = NabbitPathItem(clickedx, clickedy, pathd, newnodedata, 0, 0, 0, 0)

                        newnode.positionChanged = mw.HandlePathPosChange
                        newnode.listitem = ListWidgetItem_SortsByOther(newnode)

                        globals.UndoManager.push(undomanager.AddPathNodeCommand(pathd, newnodedata, newnode, True, insert_idx))

                        self.dragstamp = False
                        self.currentobj = newnode
                        self.dragstartx = clickedx
                        self.dragstarty = clickedy

                        newnode.UpdateListItem()

                        self.scene().clearSelection()
                        newnode.setSelected(True)

                else:
                    dlg = QtWidgets.QMessageBox()
                    dlg.setText('Sorry!<br>You can only paint Nabbit path nodes in Area 1.')
                    dlg.exec_()

            event.accept()

        elif eventButton == Qt.LeftButton and QtWidgets.QApplication.keyboardModifiers() == Qt.ShiftModifier:
            pos = self.mapToScene(event.x(), event.y())
            addsel = self.scene().items(pos)
            for i in addsel:
                if (int(i.flags()) & i.ItemIsSelectable) != 0:
                    i.setSelected(not i.isSelected())
                    break

        else:
            QtWidgets.QGraphicsView.mousePressEvent(self, event)
            
            # Snapshot state for undo
            if eventButton == Qt.LeftButton:
                self.drag_snapshot = {}
                items_to_snapshot = list(self.scene().selectedItems())
                
                # Also include the item being dragged (mouse grabber)
                grabber = self.scene().mouseGrabberItem()
                if grabber and grabber not in items_to_snapshot:
                    items_to_snapshot.append(grabber)
                    
                for item in items_to_snapshot:
                    if hasattr(item, 'objx') and hasattr(item, 'objy'):
                        if isinstance(item, (ObjectItem, ZoneItem, LocationItem)):
                            self.drag_snapshot[item] = (item.objx, item.objy, item.width, item.height)
                        else:
                            self.drag_snapshot[item] = (item.objx, item.objy)

        globals.mainWindow.levelOverview.update()

    def resizeEvent(self, event):
        """
        Catches resize events
        """
        self.FrameSize.emit(event.size().width(), event.size().height())
        event.accept()
        QtWidgets.QGraphicsView.resizeEvent(self, event)

    @staticmethod
    def translateRect(rect, x, y):
        """
        Returns a translated copy of the rect
        """
        return rect.translated(x*globals.TileWidth, y*globals.TileWidth)

    @staticmethod
    def setOverrideCursor(cursor):
        """
        Safe way to override the cursor
        """
        if globals.app.overrideCursor() is None:
            globals.app.setOverrideCursor(cursor)

        else:
            globals.app.changeOverrideCursor(cursor)

    def classicMouseMoveEvent(self, event):
        """
        Overrides mouse movement events if needed
        """

        pos = self.mapToScene(event.x(), event.y())
        if pos.x() < 0: pos.setX(0)
        if pos.y() < 0: pos.setY(0)
        self.PositionHover.emit(int(pos.x()), int(pos.y()))

        if event.buttons() == Qt.MidButton:
            offset = self.__prevMousePos - event.pos()
            self.__prevMousePos = event.pos()

            self.YScrollBar.setValue(self.YScrollBar.value() + offset.y())
            self.XScrollBar.setValue(self.XScrollBar.value() + (-offset.x() if self.isRightToLeft() else offset.x()))


        elif event.buttons() & Qt.RightButton and self.currentobj is not None and not self.dragstamp:

            # possibly a small optimization
            type_obj = ObjectItem
            type_spr = SpriteItem
            type_ent = EntranceItem
            type_loc = LocationItem
            type_path = PathItem
            type_nPath = NabbitPathItem
            type_com = CommentItem

            # iterate through the objects if there's more than one
            if isinstance(self.currentobj, list) or isinstance(self.currentobj, tuple):
                objlist = self.currentobj
            else:
                objlist = (self.currentobj,)

            for obj in objlist:

                if isinstance(obj, type_obj):
                    # resize/move the current object
                    cx = obj.objx
                    cy = obj.objy
                    cwidth = obj.width
                    cheight = obj.height

                    dsx = self.dragstartx
                    dsy = self.dragstarty
                    clicked = self.mapToScene(event.x(), event.y())
                    if clicked.x() < 0: clicked.setX(0)
                    if clicked.y() < 0: clicked.setY(0)
                    clickx = int(clicked.x() / globals.TileWidth)
                    clicky = int(clicked.y() / globals.TileWidth)

                    # allow negative width/height and treat it properly :D
                    if clickx >= dsx:
                        x = dsx
                        width = clickx - dsx + 1
                    else:
                        x = clickx
                        width = dsx - clickx + 1

                    if clicky >= dsy:
                        y = dsy
                        height = clicky - dsy + 1
                    else:
                        y = clicky
                        height = dsy - clicky + 1

                    # if the position changed, set the new one
                    if cx != x or cy != y:
                        obj.objx = x
                        obj.objy = y
                        obj.setPos(x * globals.TileWidth, y * globals.TileWidth)
                        globals.mainWindow.levelOverview.update()

                    # if the size changed, recache it and update the area
                    if cwidth != width or cheight != height:
                        obj.updateObjCacheWH(width, height)
                        obj.width = width
                        obj.height = height

                        oldrect = obj.BoundingRect
                        oldrect.translate(cx * globals.TileWidth, cy * globals.TileWidth)
                        newrect = QtCore.QRectF(obj.x(), obj.y(), obj.width * globals.TileWidth, obj.height * globals.TileWidth)
                        updaterect = oldrect.united(newrect)

                        obj.UpdateRects()
                        obj.scene().update(updaterect)
                        globals.mainWindow.levelOverview.update()

                elif isinstance(obj, type_loc):
                    # resize/move the current location
                    cx = obj.objx
                    cy = obj.objy
                    cwidth = obj.width
                    cheight = obj.height

                    dsx = self.dragstartx
                    dsy = self.dragstarty
                    clicked = self.mapToScene(event.x(), event.y())
                    if clicked.x() < 0: clicked.setX(0)
                    if clicked.y() < 0: clicked.setY(0)
                    clickx = int(clicked.x() / globals.TileWidth * 2) * 8
                    clicky = int(clicked.y() / globals.TileWidth * 2) * 8

                    # allow negative width/height and treat it properly :D
                    if clickx >= dsx:
                        x = dsx
                        width = clickx - dsx + 8
                    else:
                        x = clickx
                        width = dsx - clickx + 16

                    if clicky >= dsy:
                        y = dsy
                        height = clicky - dsy + 8
                    else:
                        y = clicky
                        height = dsy - clicky + 16

                    width = max(width, 16)
                    height = max(height, 16)

                    # if the position changed, set the new one
                    if cx != x or cy != y:
                        obj.objx = x
                        obj.objy = y

                        globals.OverrideSnapping = True
                        obj.setPos(x * (globals.TileWidth / 16), y * (globals.TileWidth / 16))
                        globals.OverrideSnapping = False
                        obj.UpdateListItem()
                        globals.mainWindow.levelOverview.update()

                    # if the size changed, recache it and update the area
                    if cwidth != width or cheight != height:
                        obj.width = width
                        obj.height = height
                        #                    obj.updateObjCache()

                        delta = globals.TileWidth / 2

                        oldrect = obj.BoundingRect
                        oldrect.translate(cx * globals.TileWidth / 16, cy * globals.TileWidth / 16)
                        newrect = QtCore.QRectF(obj.x() - delta, obj.y() - delta, obj.width * globals.TileWidth / 16 + globals.TileWidth,
                                                obj.height * globals.TileWidth / 16 + globals.TileWidth)
                        updaterect = oldrect.united(newrect)

                        obj.UpdateRects()
                        obj.scene().update(updaterect)
                        globals.mainWindow.levelOverview.update()

                elif isinstance(obj, type_spr):
                    # move the created sprite
                    clicked = self.mapToScene(event.x(), event.y())
                    if clicked.x() < 0: clicked.setX(0)
                    if clicked.y() < 0: clicked.setY(0)
                    clickedx = int((clicked.x() - globals.TileWidth / 2) / globals.TileWidth * 16)
                    clickedy = int((clicked.y() - globals.TileWidth / 2) / globals.TileWidth * 16)

                    if clickedx % 8 < 4:
                        clickedx -= (clickedx % 8)
                    else:
                        clickedx += 8 - (clickedx % 8)
                    if clickedy % 8 < 4:
                        clickedy -= (clickedy % 8)
                    else:
                        clickedy += 8 - (clickedy % 8)

                    if obj.objx != clickedx or obj.objy != clickedy:
                        obj.objx = clickedx
                        obj.objy = clickedy
                        obj.setPos(int((clickedx + obj.ImageObj.xOffset) * globals.TileWidth / 16),
                                   int((clickedy + obj.ImageObj.yOffset) * globals.TileWidth / 16))
                        obj.ImageObj.positionChanged()
                        obj.UpdateListItem()
                        globals.mainWindow.levelOverview.update()

                elif isinstance(obj, type_ent) or isinstance(obj, type_path) or isinstance(obj, type_nPath) or isinstance(obj, type_com):
                    # move the created entrance/path/comment
                    clicked = self.mapToScene(event.x(), event.y())
                    if clicked.x() < 0: clicked.setX(0)
                    if clicked.y() < 0: clicked.setY(0)
                    clickedx = int((clicked.x() - globals.TileWidth / 2) / globals.TileWidth * 16)
                    clickedy = int((clicked.y() - globals.TileWidth / 2) / globals.TileWidth * 16)

                    if clickedx % 8 < 4:
                        clickedx -= (clickedx % 8)
                    else:
                        clickedx += 8 - (clickedx % 8)
                    if clickedy % 8 < 4:
                        clickedy -= (clickedy % 8)
                    else:
                        clickedy += 8 - (clickedy % 8)

                    if obj.objx != clickedx or obj.objy != clickedy:
                        oldx = obj.objx
                        oldy = obj.objy

                        obj.objx = clickedx
                        obj.objy = clickedy

                        obj.setPos(int(clickedx * globals.TileWidth / 16), int(clickedy * globals.TileWidth / 16))

                        if isinstance(obj, type_path) or isinstance(obj, type_nPath):
                            obj.updatePos()
                            obj.pathinfo['peline'].nodePosChanged()

                        elif isinstance(obj, type_com):
                            obj.UpdateTooltip()
                            obj.handlePosChange(oldx, oldy)

                        obj.UpdateListItem()
                        globals.mainWindow.levelOverview.update()

            event.accept()

        elif event.buttons() & Qt.RightButton and self.currentobj is not None and self.dragstamp:
            # The user is dragging a stamp - many objects.

            # possibly a small optimization
            type_obj = ObjectItem
            type_spr = SpriteItem

            # iterate through the objects if there's more than one
            if isinstance(self.currentobj, list) or isinstance(self.currentobj, tuple):
                objlist = self.currentobj
            else:
                objlist = (self.currentobj,)

            for obj in objlist:

                clicked = self.mapToScene(event.x(), event.y())
                if clicked.x() < 0: clicked.setX(0)
                if clicked.y() < 0: clicked.setY(0)

                changex = clicked.x() - (self.dragstartx * globals.TileWidth / 16)
                changey = clicked.y() - (self.dragstarty * globals.TileWidth / 16)
                changexobj = int(changex / globals.TileWidth)
                changeyobj = int(changey / globals.TileWidth)
                changexspr = changex * 2 / 3
                changeyspr = changey * 2 / 3

                if isinstance(obj, type_obj):
                    # move the current object
                    newx = int(obj.dragstartx + changexobj)
                    newy = int(obj.dragstarty + changeyobj)

                    if obj.objx != newx or obj.objy != newy:
                        obj.objx = newx
                        obj.objy = newy
                        obj.setPos(newx * globals.TileWidth, newy * globals.TileWidth)

                elif isinstance(obj, type_spr):
                    # move the created sprite

                    newx = int(obj.dragstartx + changexspr)
                    newy = int(obj.dragstarty + changeyspr)

                    if obj.objx != newx or obj.objy != newy:
                        obj.objx = newx
                        obj.objy = newy
                        obj.setPos(int((newx + obj.ImageObj.xOffset) * globals.TileWidth / 16),
                                   int((newy + obj.ImageObj.yOffset) * globals.TileWidth / 16))

            self.scene().update()

        elif not self.selectionFix:
            type_obj = ObjectItem
            type_loc = LocationItem
            type_zone = ZoneItem

            objlist = [obj for obj in self.scene().selectedItems() if isinstance(obj, type_obj)]
            loclist = [loc for loc in self.scene().selectedItems() if isinstance(loc, type_loc)]
            zonelist = [zone for zone in self.scene().items() if isinstance(zone, type_zone)]

            dragging = any(thing.dragging for sel in (objlist, loclist, zonelist) for thing in sel)
            if not dragging:
                objCursorOverriden = True
                locCursorOverriden = True
                zoneCursorOverriden = True

                if objlist:
                    for obj in objlist:
                        if self.translateRect(obj.SelectionRect, obj.objx, obj.objy).contains(pos):
                            if self.translateRect(obj.GrabberRectTL, obj.objx, obj.objy).contains(pos):
                                self.setOverrideCursor(Qt.SizeFDiagCursor); objCursorOverriden = True
                                break

                            elif self.translateRect(obj.GrabberRectTR, obj.objx, obj.objy).contains(pos):
                                self.setOverrideCursor(Qt.SizeBDiagCursor); objCursorOverriden = True
                                break

                            elif self.translateRect(obj.GrabberRectBL, obj.objx, obj.objy).contains(pos):
                                self.setOverrideCursor(Qt.SizeBDiagCursor); objCursorOverriden = True
                                break

                            elif self.translateRect(obj.GrabberRectBR, obj.objx, obj.objy).contains(pos):
                                self.setOverrideCursor(Qt.SizeFDiagCursor); objCursorOverriden = True
                                break

                            elif (self.translateRect(obj.GrabberRectMT, obj.objx, obj.objy).contains(pos)
                                  or self.translateRect(obj.GrabberRectMB, obj.objx, obj.objy).contains(pos)):
                                self.setOverrideCursor(Qt.SizeVerCursor); objCursorOverriden = True
                                break

                            elif (self.translateRect(obj.GrabberRectML, obj.objx, obj.objy).contains(pos)
                                  or self.translateRect(obj.GrabberRectMR, obj.objx, obj.objy).contains(pos)):
                                self.setOverrideCursor(Qt.SizeHorCursor); objCursorOverriden = True
                                break

                            else:
                                self.setOverrideCursor(Qt.SizeAllCursor); objCursorOverriden = True
                                break

                        else:
                            objCursorOverriden = False

                else:
                    objCursorOverriden = False

                if loclist:
                    for loc in loclist:
                        if loc.SelectionRect.contains(pos.x(), pos.y()):
                            if self.translateRect(loc.GrabberRectTL, loc.objx/16, loc.objy/16).contains(pos):
                                self.setOverrideCursor(Qt.SizeFDiagCursor); locCursorOverriden = True
                                break

                            elif self.translateRect(loc.GrabberRectTR, loc.objx/16, loc.objy/16).contains(pos):
                                self.setOverrideCursor(Qt.SizeBDiagCursor); locCursorOverriden = True
                                break

                            elif self.translateRect(loc.GrabberRectBL, loc.objx/16, loc.objy/16).contains(pos):
                                self.setOverrideCursor(Qt.SizeBDiagCursor); locCursorOverriden = True
                                break

                            elif self.translateRect(loc.GrabberRectBR, loc.objx/16, loc.objy/16).contains(pos):
                                self.setOverrideCursor(Qt.SizeFDiagCursor); locCursorOverriden = True
                                break

                            elif (self.translateRect(loc.GrabberRectMT, loc.objx/16, loc.objy/16).contains(pos)
                                  or self.translateRect(loc.GrabberRectMB, loc.objx/16, loc.objy/16).contains(pos)):
                                self.setOverrideCursor(Qt.SizeVerCursor); locCursorOverriden = True
                                break

                            elif (self.translateRect(loc.GrabberRectML, loc.objx/16, loc.objy/16).contains(pos)
                                  or self.translateRect(loc.GrabberRectMR, loc.objx/16, loc.objy/16).contains(pos)):
                                self.setOverrideCursor(Qt.SizeHorCursor); locCursorOverriden = True
                                break

                            else:
                                self.setOverrideCursor(Qt.SizeAllCursor); locCursorOverriden = True
                                break

                        else:
                            locCursorOverriden = False

                else:
                    locCursorOverriden = False

                if zonelist:
                    for zone in zonelist:
                        if zone.sceneBoundingRect().contains(pos.x(), pos.y()):
                            if self.translateRect(zone.GrabberRectTL, zone.objx/16, zone.objy/16).contains(pos):
                                self.setOverrideCursor(Qt.SizeFDiagCursor); zoneCursorOverriden = True
                                break

                            elif self.translateRect(zone.GrabberRectTR, zone.objx/16, zone.objy/16).contains(pos):
                                self.setOverrideCursor(Qt.SizeBDiagCursor); zoneCursorOverriden = True
                                break

                            elif self.translateRect(zone.GrabberRectBL, zone.objx/16, zone.objy/16).contains(pos):
                                self.setOverrideCursor(Qt.SizeBDiagCursor); zoneCursorOverriden = True
                                break

                            elif self.translateRect(zone.GrabberRectBR, zone.objx/16, zone.objy/16).contains(pos):
                                self.setOverrideCursor(Qt.SizeFDiagCursor); zoneCursorOverriden = True
                                break

                            elif (self.translateRect(zone.GrabberRectMT, zone.objx/16, zone.objy/16).contains(pos)
                                  or self.translateRect(zone.GrabberRectMB, zone.objx/16, zone.objy/16).contains(pos)):
                                self.setOverrideCursor(Qt.SizeVerCursor); zoneCursorOverriden = True
                                break

                            elif (self.translateRect(zone.GrabberRectML, zone.objx/16, zone.objy/16).contains(pos)
                                  or self.translateRect(zone.GrabberRectMR, zone.objx/16, zone.objy/16).contains(pos)):
                                self.setOverrideCursor(Qt.SizeHorCursor); zoneCursorOverriden = True
                                break

                            else:
                                zoneCursorOverriden = False
                                break

                        else:
                            zoneCursorOverriden = False

                else:
                    zoneCursorOverriden = False

                if (not (objlist or loclist or zonelist) or not (objCursorOverriden or locCursorOverriden or zoneCursorOverriden)) and globals.app.overrideCursor():
                    globals.app.restoreOverrideCursor()

        QtWidgets.QGraphicsView.mouseMoveEvent(self, event)

    def classicMouseReleaseEvent(self, event):
        """
        Overrides mouse release events if needed
        """
        if event.button() == Qt.RightButton:
            self.currentobj = None

        elif event.button() == Qt.LeftButton:
            self.selectionFix = False
            
            # Check for movement/resizing
            if self.drag_snapshot:
                moved_items = []
                resized_items = []
                
                for item, old_geom in self.drag_snapshot.items():
                    try:
                        if isinstance(item, (ObjectItem, ZoneItem, LocationItem)):
                            new_geom = (item.objx, item.objy, item.width, item.height)
                            if new_geom != old_geom:
                                # If size changed, it's a resize (which can also include position change)
                                if new_geom[2:] != old_geom[2:]:
                                    resized_items.append((item, old_geom, new_geom))
                                else:
                                    moved_items.append((item, old_geom[:2], new_geom[:2]))
                        else:
                            new_pos = (item.objx, item.objy)
                            if new_pos != old_geom:
                                moved_items.append((item, old_geom, new_pos))
                    except (RuntimeError, AttributeError):
                        # Item might have been deleted during drag?
                        continue
                
                if moved_items or resized_items:
                    # We only want to push to undo if there's an actual change
                    if len(moved_items) + len(resized_items) > 1:
                        globals.UndoManager.begin_compound("Move/Resize Items")
                    
                    if moved_items:
                        globals.UndoManager.push(undomanager.MoveObjectsCommand(moved_items))
                    
                    for item, old, new in resized_items:
                        globals.UndoManager.push(undomanager.ResizeItemCommand(item, old, new))
                        
                    if len(moved_items) + len(resized_items) > 1:
                        globals.UndoManager.end_compound()

                    # A zone moved or resized: its background moves with it
                    if any(isinstance(item, ZoneItem) for item, _, _ in moved_items + resized_items):
                        globals.mainWindow.QueueLiveBackground()

                self.drag_snapshot = {}

        QtWidgets.QGraphicsView.mouseReleaseEvent(self, event)

    def paintEvent(self, e):
        """
        Handles paint events and fires a signal
        """
        self.repaint.emit()
        QtWidgets.QGraphicsView.paintEvent(self, e)

    def wheelEvent(self, event):
        """
        Handles wheel events for zooming in/out
        """
        if QtWidgets.QApplication.keyboardModifiers() == Qt.ControlModifier:
            numDegrees = event.angleDelta() / 8
            if not numDegrees.isNull():
                numSteps = numDegrees / 15
                numStepsY = numSteps.y()
                globals.mainWindow.ZoomWidget.slider.setSliderPosition(globals.mainWindow.ZoomWidget.slider.value() + numStepsY)

        elif QtWidgets.QApplication.keyboardModifiers() == Qt.ShiftModifier:
            numDegrees = event.angleDelta() / 8
            if not numDegrees.isNull():
                numSteps = numDegrees / 15
                numStepsY = numSteps.y()
                self.XScrollBar.setSliderPosition(self.XScrollBar.value() - numStepsY * 24 * 8)

        else:
            QtWidgets.QGraphicsView.wheelEvent(self, event)

    def drawForeground(self, painter, rect):
        """
        Draws a foreground grid and other stuff
        """


        # Draw the grid
        drawForegroundGrid(painter, rect)


class InfoPreviewWidget(QtWidgets.QWidget):
    """
    Widget that shows a preview of the level metadata info - available in vertical & horizontal flavors
    """

    def __init__(self, direction):
        """
        Creates and initializes the widget
        """
        super().__init__()
        self.direction = direction

        self.Label1 = QtWidgets.QLabel('')
        if self.direction == Qt.Horizontal: self.Label2 = QtWidgets.QLabel('')
        self.updateLabels()

        self.mainLayout = QtWidgets.QHBoxLayout()
        self.mainLayout.addWidget(self.Label1)
        if self.direction == Qt.Horizontal: self.mainLayout.addWidget(self.Label2)
        self.setLayout(self.mainLayout)

        if self.direction == Qt.Horizontal: self.setMinimumWidth(256)

    def updateLabels(self):
        """
        Updates the widget labels
        """
        if ('Area' not in globals.globals()) or not hasattr(globals.Area, 'filename'):  # can't get level metadata if there's no level
            self.Label1.setText('')
            if self.direction == Qt.Horizontal: self.Label2.setText('')
            return

        a = [  # MUST be a list, not a tuple
            globals.mainWindow.fileTitle,
            globals.Area.Title,
            'Created with [name]'.replace('[name]', str(globals.Area.Creator)),
            'Author:' + ' ' + globals.Area.Author,
            'Group:' + ' ' + globals.Area.Group,
            'Website:' + ' ' + globals.Area.Webpage,
        ]

        for b, section in enumerate(a):  # cut off excessively long strings
            if self.direction == Qt.Vertical:
                short = clipStr(section, 128)
            else:
                short = clipStr(section, 184)
            if short is not None: a[b] = short + '...'

        if self.direction == Qt.Vertical:
            str1 = a[0] + '<br>' + a[1] + '<br>' + a[2] + '<br>' + a[3] + '<br>' + a[4] + '<br>' + a[5]
            self.Label1.setText(str1)
        else:
            str1 = a[0] + '<br>' + a[1] + '<br>' + a[2]
            str2 = a[3] + '<br>' + a[4] + '<br>' + a[5]
            self.Label1.setText(str1)
            self.Label2.setText(str2)

        self.update()


class GameDefViewer(QtWidgets.QWidget):
    """
    Widget which displays basic info about the current game definition
    """

    def __init__(self):
        """
        Initializes the widget
        """
        QtWidgets.QWidget.__init__(self)
        self.imgLabel = QtWidgets.QLabel()
        self.imgLabel.setToolTip('This game has custom actor images')
        self.imgLabel.setPixmap(GetIcon('sprites', False).pixmap(16, 16))
        self.versionLabel = QtWidgets.QLabel()
        self.titleLabel = QtWidgets.QLabel()
        self.descLabel = QtWidgets.QLabel()
        self.descLabel.setWordWrap(True)
        self.descLabel.setMinimumHeight(40)

        # Make layouts
        left = QtWidgets.QVBoxLayout()
        left.addWidget(self.imgLabel)
        left.addWidget(self.versionLabel)
        left.addStretch(1)
        right = QtWidgets.QVBoxLayout()
        right.addWidget(self.titleLabel)
        right.addWidget(self.descLabel)
        right.addStretch(1)
        main = QtWidgets.QHBoxLayout()
        main.addLayout(left)
        main.addWidget(createVertLine())
        main.addLayout(right)
        main.setStretch(2, 1)
        self.setLayout(main)
        self.setMaximumWidth(256 + 64)

        self.updateLabels()

    def updateLabels(self):
        """
        Updates all labels
        """
        empty = QtGui.QPixmap(16, 16)
        empty.fill(QtGui.QColor(0, 0, 0, 0))
        img = GetIcon('sprites', False).pixmap(16, 16) if (
        (globals.gamedef.recursiveFiles('sprites', False, True) != []) or (not globals.gamedef.custom)) else empty
        ver = '' if globals.gamedef.version is None else '<i><p style="font-size:10px;">v' + str(globals.gamedef.version) + '</p></i>'
        title = '<b>' + str(globals.gamedef.name) + '</b>'
        desc = str(globals.gamedef.description)

        self.imgLabel.setPixmap(img)
        self.versionLabel.setText(ver)
        self.titleLabel.setText(title)
        self.descLabel.setText(desc)


class GameDefSelector(QtWidgets.QWidget):
    """
    Widget which lets you pick a new game definition
    """
    gameChanged = QtCore.pyqtSignal()

    def __init__(self):
        """
        Initializes the widget
        """
        QtWidgets.QWidget.__init__(self)

        # Populate a list of gamedefs
        from . import gamedefs
        self.GameDefs = gamedefs.getAvailableGameDefs()

        # Add them to the main layout
        self.group = QtWidgets.QButtonGroup()
        self.group.setExclusive(True)
        L = QtWidgets.QGridLayout()
        row = 0
        col = 0
        current = setting('LastGameDef')
        id = 0
        for folder in self.GameDefs:
            def_ = gamedefs.MiyamotoGameDefinition(folder)
            btn = QtWidgets.QRadioButton()
            if folder == current: btn.setChecked(True)
            btn.toggled.connect(self.HandleRadioButtonClick)
            self.group.addButton(btn, id)
            btn.setToolTip(def_.description)
            id += 1
            L.addWidget(btn, row, col)

            name = QtWidgets.QLabel(def_.name)
            name.setToolTip(def_.description)
            L.addWidget(name, row, col + 1)

            row += 1
            if row > 2:
                row = 0
                col += 2

        del gamedefs

        self.setLayout(L)

    def HandleRadioButtonClick(self, checked):
        """
        Handles radio button clicks
        """
        if not checked: return  # this is called twice; one button is checked, another is unchecked

        from . import gamedefs
        gamedefs.loadNewGameDef(self.GameDefs[self.group.checkedId()])
        del gamedefs

        self.gameChanged.emit()


class GameAndModsMenu(QtWidgets.QMenu):
    """
    Quick-access menu: radio-select one base game, checkbox-select any mods, unload-all mods.
    Changes are applied immediately on toggle.
    """
    gameChanged = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        QtWidgets.QMenu.__init__(self, parent)
        self._building = False
        self._rebuild()

    def _rebuild(self):
        self._building = True
        self.clear()

        from . import gamedefs as _gd
        current_base = setting('LastBaseGame', 'NSMBU')
        current_mods = setting('LastMods') or []
        if isinstance(current_mods, str):
            current_mods = [current_mods]

        # ── Base games (exclusive) ──────────────────────────────────────────
        base_games = _gd.getAvailableBaseGames()
        self._gameGroup = QtWidgets.QActionGroup(self)
        self._gameGroup.setExclusive(True)
        for def_, folder in base_games:
            act = QtWidgets.QAction(def_.name, self)
            act.setToolTip(def_.description)
            act.setCheckable(True)
            act.setChecked(folder == current_base)
            act.setData(('game', folder))
            self._gameGroup.addAction(act)
            self.addAction(act)
        self._gameGroup.triggered.connect(self._onGameTriggered)

        self.addSeparator()

        # ── Mods (independent checkboxes) ──────────────────────────────────
        mods = _gd.getAvailableMods()
        self._hasMods = bool(mods)
        for def_, folder in mods:
            is_broken = bool(getattr(def_, 'error', None))
            act = QtWidgets.QAction(def_.name, self)
            act.setData(('mod', folder))
            if is_broken:
                act.setEnabled(False)
                act.setToolTip(f'⚠ {def_.error}')
            else:
                act.setToolTip(def_.description)
                act.setCheckable(True)
                act.setChecked(folder in current_mods)
                act.toggled.connect(self._onModToggled)
            self.addAction(act)

        if mods:
            self.addSeparator()
            unload_act = QtWidgets.QAction("Unload All Mods", self)
            unload_act.setData(('unload', None))
            unload_act.triggered.connect(self._unloadAllMods)
            self.addAction(unload_act)

        del _gd
        self._building = False

    def rebuild(self):
        self._rebuild()

    def _onGameTriggered(self, action):
        if not self._building:
            self._apply()

    def _onModToggled(self, checked):
        if not self._building:
            self._apply()

    def _unloadAllMods(self):
        self._building = True
        for act in self.actions():
            data = act.data()
            if data and data[0] == 'mod':
                act.setChecked(False)
        self._building = False
        self._apply()

    def _apply(self):
        selected_game = 'NSMBU'
        checked_mods = []
        for act in self.actions():
            data = act.data()
            if not data:
                continue
            kind, folder = data
            if kind == 'game' and act.isChecked():
                selected_game = folder
            elif kind == 'mod' and act.isChecked():
                checked_mods.append(folder)

        # Preserve explicit patch precedence. The menu itself is alphabetized,
        # so rebuilding the stack in QAction order would silently reorder mods.
        previous_mods = setting('LastMods') or []
        if isinstance(previous_mods, str):
            previous_mods = [previous_mods]

        checked_set = set(checked_mods)
        selected_mods = [mod for mod in previous_mods if mod in checked_set]
        selected_mods.extend(mod for mod in checked_mods if mod not in selected_mods)

        from . import gamedefs as _gd
        _gd.loadNewGameDef(selected_game, selected_mods)
        del _gd
        self.gameChanged.emit()


# Keep the old name available so any remaining references don't break at import time.
GameDefMenu = GameAndModsMenu


class RecentFilesMenu(QtWidgets.QMenu):
    """
    A menu which displays recently opened files.
    Each entry is stored as {"path": str, "label": str}.
    """
    MAX_RECENT = 16

    def __init__(self):
        QtWidgets.QMenu.__init__(self)
        self.setMinimumWidth(220)
        self._load()
        self.updateActionList()

    def _load(self):
        raw = str(setting('RecentFiles')) if globals.settings.contains('RecentFiles') else None
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    self.FileList = [
                        e for e in data
                        if isinstance(e, dict) and e.get('path') and e.get('label')
                    ]
                    return
            except (ValueError, TypeError):
                pass
            # Migrate old pipe-separated format
            paths = [p for p in raw.split('|') if p.lower() not in ('', 'none', 'false', 'true')]
            self.FileList = [{'path': p, 'label': os.path.basename(p)} for p in paths]
        else:
            self.FileList = []

    def writeSettings(self):
        setSetting('RecentFiles', json.dumps(self.FileList))

    def getEntries(self):
        """Returns list of (label, path) tuples for external widgets."""
        return [(e['label'], e['path']) for e in self.FileList]

    def updateActionList(self):
        self.clear()
        ico = GetIcon('recent')

        for i, entry in enumerate(self.FileList):
            act = QtWidgets.QAction(ico, entry['label'], self)
            if i <= 9:
                act.setShortcut(QtGui.QKeySequence('Ctrl+Alt+%d' % i))
            act.setToolTip(entry['path'])
            act.triggered.connect(lambda checked, x=i: self.HandleOpenRecentFile(x))
            self.addAction(act)

        if self.FileList:
            self.addSeparator()
            clear_act = QtWidgets.QAction(GetIcon('delete'), 'Clear Recent Files', self)
            clear_act.triggered.connect(self.clearAll)
            self.addAction(clear_act)

    def AddToList(self, path, label=None):
        if path in ('None', 'True', 'False', None, True, False):
            return
        path = os.path.normpath(str(path))
        if label is None:
            label = os.path.basename(path)

        new = [{'path': path, 'label': label}]
        for entry in self.FileList:
            if entry['path'] != path:
                new.append(entry)
        self.FileList = new[:self.MAX_RECENT]

        self.writeSettings()
        self.updateActionList()

    def RemoveFromList(self, index):
        del self.FileList[index]
        self.writeSettings()
        self.updateActionList()

    def clearAll(self):
        self.FileList = []
        self.writeSettings()
        self.updateActionList()

    def HandleOpenRecentFile(self, number):
        if number < len(self.FileList):
            globals.mainWindow.LoadLevelWithWindowPrompt(self.FileList[number]['path'])


class ZoomWidget(QtWidgets.QWidget):
    """
    Widget that allows easy zoom level control
    """

    def __init__(self):
        """
        Creates and initializes the widget
        """
        super().__init__()
        maxwidth = 512 - 128
        maxheight = 20

        self.slider = QtWidgets.QSlider(Qt.Horizontal)
        self.minLabel = QtWidgets.QPushButton()
        self.minusLabel = QtWidgets.QPushButton()
        self.plusLabel = QtWidgets.QPushButton()
        self.maxLabel = QtWidgets.QPushButton()

        self.slider.setMaximumHeight(maxheight)
        self.slider.setMinimum(0)
        self.slider.setMaximum(len(globals.mainWindow.ZoomLevels) - 1)
        self.slider.setTickInterval(2)
        self.slider.setTickPosition(self.slider.TicksAbove)
        self.slider.setPageStep(1)
        self.slider.setTracking(True)
        self.slider.setSliderPosition(self.findIndexOfLevel(100))
        self.slider.valueChanged.connect(self.sliderMoved)

        self.minLabel.setIcon(GetIcon('zoommin'))
        self.minusLabel.setIcon(GetIcon('zoomout'))
        self.plusLabel.setIcon(GetIcon('zoomin'))
        self.maxLabel.setIcon(GetIcon('zoommax'))
        self.minLabel.setFlat(True)
        self.minusLabel.setFlat(True)
        self.plusLabel.setFlat(True)
        self.maxLabel.setFlat(True)
        self.minLabel.clicked.connect(globals.mainWindow.HandleZoomMin)
        self.minusLabel.clicked.connect(globals.mainWindow.HandleZoomOut)
        self.plusLabel.clicked.connect(globals.mainWindow.HandleZoomIn)
        self.maxLabel.clicked.connect(globals.mainWindow.HandleZoomMax)

        self.layout = QtWidgets.QGridLayout()
        self.layout.addWidget(self.minLabel, 0, 0)
        self.layout.addWidget(self.minusLabel, 0, 1)
        self.layout.addWidget(self.slider, 0, 2)
        self.layout.addWidget(self.plusLabel, 0, 3)
        self.layout.addWidget(self.maxLabel, 0, 4)
        self.layout.setVerticalSpacing(0)
        self.layout.setHorizontalSpacing(0)
        self.layout.setContentsMargins(0, 0, 4, 0)

        self.setLayout(self.layout)
        self.setMinimumWidth(maxwidth)
        self.setMaximumWidth(maxwidth)
        self.setMaximumHeight(maxheight)

    def sliderMoved(self):
        """
        Handle the slider being moved
        """
        globals.mainWindow.ZoomTo(globals.mainWindow.ZoomLevels[self.slider.value()])

    def setZoomLevel(self, newLevel):
        """
        Moves the slider to the zoom level given
        """
        self.slider.setSliderPosition(self.findIndexOfLevel(newLevel))

    def findIndexOfLevel(self, level):
        for i, mainlevel in enumerate(globals.mainWindow.ZoomLevels):
            if float(mainlevel) == float(level): return i


class ZoomStatusWidget(QtWidgets.QWidget):
    """
    Shows the current zoom level, in percent
    """

    def __init__(self):
        """
        Creates and initializes the widget
        """
        super().__init__()
        self.label = QtWidgets.QPushButton('100%')
        self.label.setFlat(True)
        self.label.clicked.connect(globals.mainWindow.HandleZoomActual)

        self.layout = QtWidgets.QHBoxLayout()
        self.layout.addWidget(self.label)
        self.layout.setContentsMargins(4, 0, 8, 0)
        self.setMaximumWidth(56)

        self.setLayout(self.layout)

    def setZoomLevel(self, zoomLevel):
        """
        Updates the widget
        """
        if float(int(zoomLevel)) == float(zoomLevel):
            self.label.setText(str(int(zoomLevel)) + '%')
        else:
            self.label.setText(str(float(zoomLevel)) + '%')


class EmbeddedTab(QtWidgets.QTabWidget):
    """Embedded tileset browser: All (combined Pa1-Pa3), then individual slots 2/3/4."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.currentChanged.connect(self.tabChanged)

        self.objTSAllTab = QtWidgets.QWidget()
        self.objTS1Tab = QtWidgets.QWidget()
        self.objTS2Tab = QtWidgets.QWidget()
        self.objTS3Tab = QtWidgets.QWidget()

        tsicon = GetIcon('objects')
        self.addTab(self.objTSAllTab, tsicon, 'All')
        self.addTab(self.objTS1Tab, tsicon, '2')
        self.addTab(self.objTS2Tab, tsicon, '3')
        self.addTab(self.objTS3Tab, tsicon, '4')

        self.mAll = ObjectPickerWidget.ObjectListModel()
        self.m1 = ObjectPickerWidget.ObjectListModel()
        self.m2 = ObjectPickerWidget.ObjectListModel()
        self.m3 = ObjectPickerWidget.ObjectListModel()
        self._allBoundaries = []  # snapshot of globals.numObj after combined load

    def tabChanged(self, nt, layout=None):
        if 0 <= nt <= 3:
            mw = globals.mainWindow

            # Updating tab enabled states can emit currentChanged even while
            # Local is hidden. A hidden subtab must never steal the shared
            # object-picker layout (or change its model) from Main.
            if (mw is None or not hasattr(mw, 'objAllTab')
                    or mw.objAllTab.currentIndex() != 1):
                return

            if not layout and hasattr(globals.mainWindow, 'createObjectLayout'):
                layout = globals.mainWindow.createObjectLayout

            if layout:
                sub_tabs = [self.objTSAllTab, self.objTS1Tab, self.objTS2Tab, self.objTS3Tab]
                mw.objPicker.ShowTileset(2)
                sub_tabs[nt].setLayout(layout)

    def setLayout(self, layout):
        self.tabChanged(self.currentIndex(), layout)

    def getObjectAndPaintType(self, type):
        if self.currentIndex() == 0:  # All combined: decode using our captured boundaries
            bounds = self._allBoundaries
            type += 1
            paintType = 1
            if len(bounds) > 1 and type > bounds[1]:
                paintType = 3
                type -= bounds[1]
            elif len(bounds) > 0 and type > bounds[0]:
                paintType = 2
                type -= bounds[0]
            return type - 1, paintType
        else:
            return type, self.currentIndex()  # 1=Pa1, 2=Pa2, 3=Pa3

    def getModels(self):
        return self.mAll, self.m1, self.m2, self.m3

    def getActiveModel(self):
        return self.getModels()[self.currentIndex()]

    def LoadFromTilesets(self):
        self.mAll.LoadFromTileset(4)
        self._allBoundaries = list(globals.numObj)
        self.m1.LoadFromTileset(1)
        self.m2.LoadFromTileset(2)
        self.m3.LoadFromTileset(3)
        self._updateTabStates()

    def _updateTabStates(self):
        e1 = self.m1.rowCount() > 0
        e2 = self.m2.rowCount() > 0
        e3 = self.m3.rowCount() > 0
        any_embedded = e1 or e2 or e3

        self.setTabEnabled(0, any_embedded)
        self.setTabEnabled(1, e1)
        self.setTabEnabled(2, e2)
        self.setTabEnabled(3, e3)

        if not self.isTabEnabled(self.currentIndex()):
            for i in range(self.count()):
                if self.isTabEnabled(i):
                    self.setCurrentIndex(i)
                    break

        mw = globals.mainWindow
        if mw is not None and hasattr(mw, 'objAllTab'):
            mw.objAllTab.setTabEnabled(1, any_embedded)
            if not mw.objAllTab.isTabEnabled(mw.objAllTab.currentIndex()):
                for i in range(mw.objAllTab.count()):
                    if mw.objAllTab.isTabEnabled(i):
                        mw.objAllTab.setCurrentIndex(i)
                        break


class ListWidgetWithToolTipSignal(QtWidgets.QListWidget):
    """
    A QtWidgets.QListWidget that includes a signal that
    is emitted when a tooltip is about to be shown. Useful
    for making tooltips that update every time you show
    them.
    """
    toolTipAboutToShow = QtCore.pyqtSignal(QtWidgets.QListWidgetItem)

    def viewportEvent(self, e):
        """
        Handles viewport events
        """
        if e.type() == e.ToolTip:
            item = self.itemFromIndex(self.indexAt(e.pos()))
            if item is not None:
                self.toolTipAboutToShow.emit(item)

        return super().viewportEvent(e)


class ListWidgetItem_SortsByOther(QtWidgets.QListWidgetItem):
    """
    A ListWidgetItem that defers sorting to another object.
    """

    def __init__(self, reference, text=''):
        super().__init__(text)
        self.reference = reference

    def __lt__(self, other):
        return self.reference < other.reference


class IconsOnlyTabBar(QtWidgets.QTabBar):
    """
    A QTabBar subclass that is designed to only display icons.
    From "Reggie-Updated".

    On macOS Mojave (and probably other versions around there),
    QTabWidget tabs are way too wide when only displaying icons.
    This ultimately causes the Miyamoto palette itself to have a really
    high minimum width.

    This subclass limits tab widths to fix the problem.
    """
    def tabSizeHint(self, index):
        res = super().tabSizeHint(index)
        if globals.app.style().metaObject().className() == 'QMacStyle':
            res.setWidth(res.height() * 2)

        return res


class ToastPopup(QtWidgets.QLabel):
    """
    A short message that fades in at the bottom left of a main window (above the
    status bar), stays a few seconds and fades out. It never takes focus or clicks.
    """
    MARGIN = 12
    FADE_MS = 200

    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        # Theme colours: a tooltip-like box that works in light and dark themes
        self.setStyleSheet(
            'QLabel { background-color: palette(window-text); color: palette(window);'
            ' border-radius: 6px; padding: 7px 14px; }')

        self.opacity = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        self.fade = QtCore.QPropertyAnimation(self.opacity, b'opacity', self)
        self.fade.setDuration(self.FADE_MS)
        self.fade.finished.connect(self._fadeFinished)
        self.hideTimer = QtCore.QTimer(self)
        self.hideTimer.setSingleShot(True)
        self.hideTimer.timeout.connect(lambda: self._fadeTo(0.0))

        window.installEventFilter(self)
        self.hide()

    def showMessage(self, text, msecs=3000):
        self.setText(text)
        self.adjustSize()
        self._place()
        self.raise_()
        if not self.isVisible():
            self.opacity.setOpacity(0.0)
            self.show()
        self._fadeTo(0.92)
        self.hideTimer.start(msecs)

    def _fadeTo(self, value):
        self.fade.stop()
        self.fade.setStartValue(self.opacity.opacity())
        self.fade.setEndValue(value)
        self.fade.start()

    def _fadeFinished(self):
        if self.opacity.opacity() == 0.0:
            self.hide()

    def _place(self):
        bottom = self.window_.height() - self.MARGIN
        statusBar = self.window_.statusBar()
        if statusBar.isVisible():
            bottom -= statusBar.height()
        self.move(self.MARGIN, bottom - self.height())

    def eventFilter(self, obj, event):
        if obj is self.window_ and event.type() == QtCore.QEvent.Resize and self.isVisible():
            self._place()
        return False
