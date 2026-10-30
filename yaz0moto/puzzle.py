#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Puzzle NSMBU
# This is Puzzle 0.6, ported to Python 3 & PyQt5, and then ported to support the New Super Mario Bros. U tileset format.
# Puzzle 0.6 by Tempus; all improvements for Python 3, PyQt5 and NSMBU by RoadrunnerWMC and AboodXD

import json
import os
import os.path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib

from ctypes import create_string_buffer
from PyQt5 import QtCore, QtGui, QtWidgets
Qt = QtCore.Qt

from . import globals
from . import misc
from .gtx import RAWtoGTX
import SarcLib
from .tileset import HandleTilesetEdited, loadGTX, writeGTX
from .tileset import loadTexFromBNTX, getTilesetBNTX, BuildTilesetArchiveDX, WriteTilesetFileDX
from . import yaz0
from .tileset import updateCollisionOverlay

Tileset = None
window = None

# Objects a tileset can have: levels store an object's number in a byte
MAX_OBJECTS = 256


class TilesetEditor(QtWidgets.QWidget):
    def __init__(self, parent_window, name, data, slot, con):
        super().__init__()
        self.window = parent_window
        self.name = name
        self.slot = int(slot)
        self.con = con
        self.data = None
        self.isDirty = False
        self.forceClose = False
        self.overrides = True
        self.normalmap = False
        self.tileImage = QtGui.QPixmap()

        self.tileset = TilesetClass()
        self.tileset.slot = self.slot

        global Tileset, window
        Tileset = self.tileset
        window = self
        self.setupWidgets()

        if data is None:
            self.newTileset()
        else:
            self.data = data
            if not self.openTileset():
                self.forceClose = True

        self.setuptile()

    def setupWidgets(self):
        layout = QtWidgets.QVBoxLayout(self)
        
        # Upper area (Tile display and side tabs)
        upperLayout = QtWidgets.QHBoxLayout()
        
        # Left side: Display and status
        leftSide = QtWidgets.QVBoxLayout()

        # Tile-under-mouse info above the canvas
        tileUnderLabel = QtWidgets.QLabel("Tile under mouse:")
        tileUnderLabel.setStyleSheet('color: #888; font-size: 11px;')
        tileUnderLabel.setEnabled(False)
        leftSide.addWidget(tileUnderLabel)

        self.infoLabel = QtWidgets.QLabel("")
        self.infoLabel.setWordWrap(True)
        self.infoLabel.setFixedHeight(38)
        self.infoLabel.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        leftSide.addWidget(self.infoLabel)

        self.tileDisplay = displayWidget(editor=self)
        self.model = PiecesModel(self)
        self.tileDisplay.setModel(self.model)
        leftSide.addWidget(self.tileDisplay)

        # Status/Checkboxes area
        statusLayout = QtWidgets.QVBoxLayout()
        statusLayout.setSpacing(2)
        statusLayout.setContentsMargins(4, 8, 4, 4)

        checkboxRow = QtWidgets.QVBoxLayout()
        self.showCollisionBtn = QtWidgets.QCheckBox("Show collision")
        self.showCollisionBtn.setChecked(False)
        self.showCollisionBtn.toggled.connect(self.updateCollisionOverlay)

        self.showNormalBtn = QtWidgets.QCheckBox("Show normal map")
        self.showNormalBtn.toggled.connect(self.toggleNormal)

        self.toggleOverridesBtn = QtWidgets.QCheckBox("Show overrides")
        self.toggleOverridesBtn.setChecked(True)
        self.toggleOverridesBtn.setEnabled(self.slot == 0)
        self.toggleOverridesBtn.toggled.connect(self.toggleOverrides)

        checkboxRow.addWidget(self.showCollisionBtn)
        checkboxRow.addWidget(self.showNormalBtn)
        checkboxRow.addWidget(self.toggleOverridesBtn)
        checkboxRow.addStretch(1)

        self.tileCountLabel = QtWidgets.QLabel("Used Tiles: 0 • Free Tiles: 256")

        statusLayout.addLayout(checkboxRow)
        statusLayout.addWidget(self.tileCountLabel)

        leftSide.addLayout(statusLayout)
        upperLayout.addLayout(leftSide, 3)
        
        # Right side: Objects/Behaviours/Animations tabs
        self.sideTabWidget = QtWidgets.QTabWidget()
        self.objectList = objectList(editor=self)
        self.objmodel = QtGui.QStandardItemModel()
        SetupObjectModel(self.objmodel, self, self.tileset.objects, self.tileset.tiles)
        self.objectList.setModel(self.objmodel)
        
        self.tileWidget = tileOverlord(editor=self)
        self.paletteWidget = paletteWidget(editor=self)
        
        self.objContainer = QtWidgets.QWidget()
        objLayout = QtWidgets.QVBoxLayout(self.objContainer)
        objLayout.addWidget(self.objectList)
        objLayout.addWidget(self.tileWidget)
        
        self.animWidget = animWidget(editor=self)
        
        self.sideTabWidget.addTab(self.paletteWidget, 'Properties')
        self.sideTabWidget.addTab(self.objContainer, 'Objects')
        self.sideTabWidget.addTab(self.animWidget, 'Animations')
        self.sideTabWidget.setTabEnabled(2, self.slot == 0)
        self._collisionShownBefore = None
        self.sideTabWidget.currentChanged.connect(self.sideTabChanged)
        self.sideTabChanged(self.sideTabWidget.currentIndex())

        upperLayout.addWidget(self.sideTabWidget, 2)
        layout.addLayout(upperLayout)

        # Connections
        # Painting properties onto tiles is done by tileDisplay's mouse handling
        self._stroke = None
        self._paintUndo = []
        undo = QtWidgets.QShortcut(QtGui.QKeySequence.Undo, self, self.undoPaint)
        undo.setContext(Qt.WidgetWithChildrenShortcut)
        self.tileDisplay.mouseMoved.connect(self.updateInfo)
        self.objectList.clicked.connect(self.tileWidget.setObject)

        self.setMinimumHeight(560)

    def activate(self):
        global Tileset, window
        Tileset = self.tileset
        window = self
        self.updateInfo(0, 0)

    def setDirty(self):
        self.isDirty = True
        self.window.updateTabTitle(self)

    def setuptile(self):
        self.model.clear()
        for i, tile in enumerate(self.tileset.tiles):
            if self.normalmap:
                img = tile.normalmap
            elif self.slot == 0 and self.overrides:
                override = self.tileset.overrides[i]
                img = override if override is not None else tile.image
            else:
                img = tile.image
            self.model.addPieces(img)
        usedTiles = len(self.tileset.getUsedTiles())
        freeTiles = 256 - usedTiles
        self.tileCountLabel.setText(f"Used Tiles: {usedTiles} • Free Tiles: {freeTiles}")

    def newTileset(self):
        pix = QtGui.QPixmap(60, 60)
        pix.fill(Qt.transparent)
        nml = QtGui.QPixmap(60, 60)
        nml.fill(Qt.transparent)
        for _ in range(256):
            self.tileset.addTile(pix, nml, 0)

    # ... (Most methods from MainWindow will move here and be slightly adjusted)
    @staticmethod
    def getData(arc):
        Image = None
        NmlMap = None
        behaviourdata = None
        objstrings = None
        metadata = None

        for folder in arc.contents:
            if folder.name == 'BG_tex':
                for file in folder.contents:
                    if file.name.endswith('_nml.gtx') and len(file.data) in (1421344, 4196384):
                        NmlMap = file.data
                    elif file.name.endswith('.gtx') and len(file.data) in (1421344, 4196384):
                        Image = file.data

            elif folder.name == 'BG_chk':
                for file in folder.contents:
                    if file.name.startswith('d_bgchk_') and file.name.endswith('.bin'):
                        behaviourdata = file.data
            elif folder.name == 'BG_unt':
                for file in folder.contents:
                    if file.name.endswith('_hd.bin'):
                        metadata = file.data
                    elif file.name.endswith('.bin'):
                        objstrings = file.data

        return Image, NmlMap, behaviourdata, objstrings, metadata

    @staticmethod
    def getDataDX(arc):
        """
        Deluxe: the textures are BNTX inside output.bfres, named after the tileset, so decode
        them here. Returns (Image, NmlMap, behaviourdata, objstrings, metadata) like getData,
        but with the two images already decoded (QImage).
        """
        Image = None
        NmlMap = None
        behaviourdata = None
        objstrings = None
        metadata = None

        try:
            hasBfres = arc['output.bfres'].data
        except Exception:
            hasBfres = None

        for folder in arc.contents:
            if folder.name == 'BG_chk':
                for file in folder.contents:
                    if file.name.startswith('d_bgchk_') and file.name.endswith('.bin'):
                        behaviourdata = file.data
                        internalName = file.name[len('d_bgchk_'):-len('.bin')]
            elif folder.name == 'BG_unt':
                for file in folder.contents:
                    if file.name.endswith('_hd.bin'):
                        metadata = file.data
                    elif file.name.endswith('.bin'):
                        objstrings = file.data

        if hasBfres and behaviourdata is not None:
            bntx = getTilesetBNTX(arc)
            try:
                Image = loadTexFromBNTX(bntx, internalName)
                NmlMap = loadTexFromBNTX(bntx, internalName + '_nml')
            except Exception as e:
                print('Failed to decode the tileset textures:', e)

        return Image, NmlMap, behaviourdata, objstrings, metadata

    def openTileset(self):
        '''Opens a Nintendo tileset sarc and parses the heck out of it.'''

        data = self.data

        if not data.startswith(b'SARC'):
            QtWidgets.QMessageBox.warning(None, 'Error',  'Error - this is not a SARC file.\n\nNot a valid tileset, sadly.')
            return False

        arc = SarcLib.SARC_Archive(data)
        if globals.IsNSMBUDX:
            Image, NmlMap, behaviourdata, objstrings, metadata = self.getDataDX(arc)
        else:
            Image, NmlMap, behaviourdata, objstrings, metadata = self.getData(arc)

        if not Image:
            QtWidgets.QMessageBox.warning(None, 'Error',  'Error - Couldn\'t load the image data')
            return False

        elif not NmlMap:
            QtWidgets.QMessageBox.warning(None, 'Error',  'Error - Couldn\'t load the normal map data')
            return False

        elif None in (behaviourdata, objstrings, metadata):
            QtWidgets.QMessageBox.warning(None, 'Error',  'Error - the necessary files were not found.\n\nNot a valid tileset, sadly.')
            return False

        self.tileset.clear()
        self.arc = arc

        # Loads the Image Data.
        if globals.IsNSMBUDX:
            dest, destnml = Image, NmlMap  # already decoded from the BNTX
        else:
            dest = loadGTX(Image)
            destnml = loadGTX(NmlMap)

        self.tileImage = QtGui.QPixmap.fromImage(dest)
        self.nmlImage = QtGui.QPixmap.fromImage(destnml)

        # Loads Tile Behaviours
        behaviours = []
        for entry in range(256):
            behaviours.append(struct.unpack('<Q', behaviourdata[entry*8:entry*8+8])[0])


        # Makes us some nice Tile Classes!
        Xoffset = 2
        Yoffset = 2
        for i in range(256):
            self.tileset.addTile(
                self.tileImage.copy(Xoffset,Yoffset,60,60),
                self.nmlImage.copy(Xoffset,Yoffset,60,60),
                behaviours[i])
            Xoffset += 64
            if Xoffset >= 2048:
                Xoffset = 2
                Yoffset += 64


        # Load Objects
        meta = []
        for i in range(len(metadata) // 6):
            meta.append(struct.unpack_from('<HBBH' if globals.IsNSMBUDX else '>HBBH', metadata, i * 6))

        tilelist = [[]]
        upperslope = [0, 0]
        lowerslope = [0, 0]
        byte = 0

        for entry in meta:
            offset = entry[0]
            byte = struct.unpack_from('>B', objstrings, offset)[0]
            row = 0

            while byte != 0xFF:

                if byte == 0xFE:
                    tilelist.append([])

                    if (upperslope[0] != 0) and (lowerslope[0] == 0):
                        upperslope[1] = upperslope[1] + 1

                    if lowerslope[0] != 0:
                        lowerslope[1] = lowerslope[1] + 1

                    offset += 1
                    byte = struct.unpack_from('>B', objstrings, offset)[0]

                elif (byte & 0x80):

                    if upperslope[0] == 0:
                        upperslope[0] = byte
                    else:
                        lowerslope[0] = byte

                    offset += 1
                    byte = struct.unpack_from('>B', objstrings, offset)[0]

                else:
                    tilelist[-1].append(struct.unpack_from('>3B', objstrings, offset))

                    offset += 3
                    byte = struct.unpack_from('>B', objstrings, offset)[0]

            tilelist.pop()

            if (upperslope[0] & 0x80) and (upperslope[0] & 0x2):
                for i in range(lowerslope[1]):
                    pop = tilelist.pop()
                    tilelist.insert(0, pop)

            self.tileset.addObject(entry[2], entry[1], entry[3], upperslope, lowerslope, tilelist)

            tilelist = [[]]
            upperslope = [0, 0]
            lowerslope = [0, 0]

        self.tileset.slot = self.slot; self.tileset.processOverrides()
        self.animWidget.load()

        cobj = 0
        crow = 0
        ctile = 0
        for object in self.tileset.objects:
            for row in object.tiles:
                for tile in row:
                    if tile[2] & 3 or not self.slot:
                        self.tileset.objects[cobj].tiles[crow][ctile] = (tile[0], tile[1], (tile[2] & 0xFC) | self.slot)
                    ctile += 1
                crow += 1
                ctile = 0
            cobj += 1
            crow = 0
            ctile = 0

        self.setuptile()
        SetupObjectModel(self.objmodel, self, self.tileset.objects, self.tileset.tiles)

        return True

    def openTilesetfromFile(self):
        '''Opens a NSMBU tileset sarc from a file and parses the heck out of it.'''

        path = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open NSMBU Deluxe Tileset" if globals.IsNSMBUDX else "Open NSMBU Tileset", '',
            "Tileset files (*.szs);;All files (*)" if globals.IsNSMBUDX else "All files (*)")[0]

        if not path: return

        with open(path, 'rb') as file:
            self.data = file.read()

        if self.data[:4] == b'Yaz0':
            self.data = yaz0.decompressFASTYZ(self.data)

        imported = self.openTileset()
        if imported: self.setDirty()
        
    def openImage(self, nml=False):
        '''Opens an Image from png, and creates a new tileset from it.'''

        path = QtWidgets.QFileDialog.getOpenFileName(self.window, "Open Image", '',
                    "Image Files (*.png)")[0]

        if not path: return
        newImage = QtGui.QPixmap()
        self.tileImage = newImage

        if not newImage.load(path):
            QtWidgets.QMessageBox.warning(self.window, "Open Image",
                    "The image file could not be loaded.",
                    QtWidgets.QMessageBox.Cancel)
            return

        if ((newImage.width() == 960) & (newImage.height() == 960)):
            x = 0
            y = 0
            for i in range(256):
                if nml:
                    self.tileset.tiles[i].normalmap = self.tileImage.copy(x*60,y*60,60,60)
                else:
                    self.tileset.tiles[i].image = self.tileImage.copy(x*60,y*60,60,60)
                x += 1
                if (x * 60) >= 960:
                    y += 1
                    x = 0

        else:
            QtWidgets.QMessageBox.warning(self.window, "Open Image",
                    "The image was not the proper dimensions.\n"
                    "Please resize the image to 960x960 pixels.",
                    QtWidgets.QMessageBox.Cancel)
            return

        index = self.objectList.currentIndex()
        self.setuptile()
        SetupObjectModel(self.objmodel, self, self.tileset.objects, self.tileset.tiles)
        self.objectList.setCurrentIndex(index)
        self.tileWidget.setObject(index)
        self.objectList.update()
        self.tileWidget.update()
        self.setDirty()


    def saveImage(self, nml=False):
        fn = QtWidgets.QFileDialog.getSaveFileName(self.window, 'Choose a new filename', '', '.png (*.png)')[0]
        if fn == '': return

        tex = QtGui.QPixmap(960, 960)
        tex.fill(Qt.transparent)
        painter = QtGui.QPainter(tex)

        Xoffset = 0
        Yoffset = 0

        for tile in self.tileset.tiles:
            tileimg = tile.image
            if nml:
                tileimg = tile.normalmap
            painter.drawPixmap(Xoffset, Yoffset, tileimg)
            Xoffset += 60
            if Xoffset >= 960:
                Xoffset = 0
                Yoffset += 60

        painter.end()
        tex.save(fn)


    def openNml(self):
        self.openImage(True)


    def saveNml(self):
        self.saveImage(True)


    def saveTileset(self):
        if not self._fitObjectLimit():
            return
        previousName = eval('globals.Area.tileset%d' % self.slot)

        if self.slot == 0:
            filename = globals.Area.tileset0
            assert os.path.basename(self.name) == filename

            if globals.IsNSMBUDX and not self._confirmOverwriteMainTilesetDX(filename):
                return

            outdata = self.saving(filename)

        else:
            filename = eval('globals.Area.tileset%d' % self.slot)
            if True:
                filename, outdata = self.savingHashName()
                exec("globals.Area.tileset%d = filename" % self.slot)

        if globals.IsNSMBUDX:
            # Deluxe tilesets live in the game's Unit folder, not inside the level
            try:
                WriteTilesetFileDX(filename, outdata)
            except ValueError as e:
                QtWidgets.QMessageBox.warning(self.window, 'Save Error', str(e))
                if self.slot:
                    # the new name was assigned above; put the previous one back
                    exec("globals.Area.tileset%d = previousName" % self.slot)
                return
        else:
            globals.szsData[filename] = outdata

        if self.slot == 0:
            from . import loading
            loading.LoadTileset(0, globals.Area.tileset0)
            del loading

            from . import verifications
            verifications.SetDirty()
            del verifications

            HandleTilesetEdited(True)
            globals.mainWindow.objAllTab.setTabEnabled(0, True)
            globals.mainWindow.objAllTab.setCurrentIndex(0)

        else:
            globals.mainWindow.ReloadTilesets()

            from . import verifications
            verifications.SetDirty()
            del verifications

            HandleTilesetEdited(True)

            if globals.ObjectDefinitions[self.slot] == [None] * 256:
                from . import tileset
                tileset.UnloadTileset(self.slot)
                del tileset
                exec("globals.Area.tileset%d = ''" % self.slot)
            else:
                globals.mainWindow.objAllTab.setCurrentIndex(2)

        for layer in globals.Area.layers:
            for obj in layer:
                obj.updateObjCache()

        globals.mainWindow.scene.update()
        
        self.isDirty = False
        self.window.updateTabTitle(self)


    def _confirmOverwriteMainTilesetDX(self, filename):
        """
        The main (Pa0) tileset is shared by every level that uses it, and Deluxe keeps it as a
        file in Unit, so saving replaces that file. Confirm once per session.
        """
        if getattr(globals, '_dxMainTilesetConfirmed', False):
            return True

        path = globals.gamedef.FindTilesetFile(filename) or (filename + '.szs')
        reply = QtWidgets.QMessageBox.question(
            self.window, 'Overwrite main tileset?',
            'The main tileset "%s" is shared by every level that uses it.\n\n'
            'Saving will replace this file:\n%s\n\nContinue?' % (filename, path),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)

        if reply != QtWidgets.QMessageBox.Yes:
            return False

        globals._dxMainTilesetConfirmed = True
        return True

    def saveTilesetAs(self):
        if globals.IsNSMBUDX:
            # Export as a standalone Deluxe tileset: <name>.szs (Yaz0-compressed SARC)
            fn = QtWidgets.QFileDialog.getSaveFileName(
                self.window, 'Export Deluxe tileset', self.name + '.szs', 'NSMBUDX tileset files (*.szs)')[0]
            if fn == '': return

            fn = str(fn)
            if not fn.lower().endswith('.szs'):
                fn += '.szs'

            name = os.path.splitext(os.path.basename(fn))[0]
            try:
                WriteTilesetFileDX(name, self.saving(name), fn)
            except ValueError as e:
                QtWidgets.QMessageBox.warning(self.window, 'Export Error', str(e))
            return

        fn = QtWidgets.QFileDialog.getSaveFileName(self.window, 'Choose a new filename', '', 'All files (*)')[0]
        if fn == '': return

        outdata = self.saving(os.path.basename(str(fn)))

        with open(fn, 'wb') as f:
            f.write(outdata)


    def saveBuffers(self):
        # Prepare tiles, objects, object metadata, and textures and stuff into buffers.
        textureBuffer = self.PackTexture()
        textureBufferNml = self.PackTexture(True)
        tileBuffer = self.PackTiles()
        objectBuffers = self.PackObjects()
        objectBuffer = objectBuffers[0]
        objectMetaBuffer = objectBuffers[1]

        return textureBuffer, textureBufferNml, tileBuffer, objectBuffer, objectMetaBuffer


    def savingWithBuffers(self, name, textureBuffer, textureBufferNml, tileBuffer, objectBuffer, objectMetaBuffer):
        if globals.IsNSMBUDX:
            return BuildTilesetArchiveDX(name, textureBuffer, textureBufferNml, tileBuffer,
                                         objectBuffer, objectMetaBuffer, self.animWidget.save())

        # Make an arc and pack up the files!
        arc = SarcLib.SARC_Archive()

        tex = SarcLib.Folder('BG_tex'); arc.addFolder(tex)
        tex.addFile(SarcLib.File('%s.gtx' % name, textureBuffer))
        tex.addFile(SarcLib.File('%s_nml.gtx' % name, textureBufferNml))

        for (animName, data) in self.animWidget.save():
            tex.addFile(SarcLib.File('%s.gtx' % animName, data))

        chk = SarcLib.Folder('BG_chk'); arc.addFolder(chk)
        chk.addFile(SarcLib.File('d_bgchk_%s.bin' % name, tileBuffer))

        unt = SarcLib.Folder('BG_unt'); arc.addFolder(unt)
        unt.addFile(SarcLib.File('%s.bin' % name, objectBuffer))
        unt.addFile(SarcLib.File('%s_hd.bin' % name, objectMetaBuffer))

        return arc.save()[0]


    def saving(self, name):
        return self.savingWithBuffers(name, *self.saveBuffers())


    def savingHashName(self):
        buffers = self.saveBuffers()
        buffers_data = b''.join(buffers)
        buffers_hash = zlib.crc32(
            buffers_data,
            (self.slot << 24 |
             self.slot << 16 |
             self.slot << 8 |
             self.slot)
        )

        name = 'Pa%d_%08X%08X' % (self.slot, buffers_hash, len(buffers_data))
        return name, self.savingWithBuffers(name, *buffers)

    def PackTexture(self, normalmap=False):
        tex = QtGui.QImage(2048, 512, QtGui.QImage.Format_RGBA8888)
        tex.fill(Qt.transparent)
        painter = QtGui.QPainter(tex)

        Xoffset = 0
        Yoffset = 0

        for tile in self.tileset.tiles:
            minitex = QtGui.QImage(64, 64, QtGui.QImage.Format_RGBA8888)
            minitex.fill(Qt.transparent)
            minipainter = QtGui.QPainter(minitex)

            minipainter.drawPixmap(2, 2, tile.normalmap if normalmap else tile.image)
            minipainter.end()

            # Read colours and DESTROY THEM (or copy them to the edges, w/e)
            for i in range(2, 62):

                # Top Clamp
                colour = minitex.pixel(i, 2)
                for p in range(0,2):
                    minitex.setPixel(i, p, colour)

                # Left Clamp
                colour = minitex.pixel(2, i)
                for p in range(0,2):
                    minitex.setPixel(p, i, colour)

                # Right Clamp
                colour = minitex.pixel(i, 61)
                for p in range(62,64):
                    minitex.setPixel(i, p, colour)

                # Bottom Clamp
                colour = minitex.pixel(61, i)
                for p in range(62,64):
                    minitex.setPixel(p, i, colour)

            # UpperLeft Corner Clamp
            colour = minitex.pixel(2, 2)
            for x in range(0,2):
                for y in range(0,2):
                    minitex.setPixel(x, y, colour)

            # UpperRight Corner Clamp
            colour = minitex.pixel(61, 2)
            for x in range(62,64):
                for y in range(0,2):
                    minitex.setPixel(x, y, colour)

            # LowerLeft Corner Clamp
            colour = minitex.pixel(2, 61)
            for x in range(0,2):
                for y in range(62,64):
                    minitex.setPixel(x, y, colour)

            # LowerRight Corner Clamp
            colour = minitex.pixel(61, 61)
            for x in range(62,64):
                for y in range(62,64):
                    minitex.setPixel(x, y, colour)

            painter.drawImage(Xoffset, Yoffset, minitex)
            Xoffset += 64

            if Xoffset >= 2048:
                Xoffset = 0
                Yoffset += 64

        painter.end()

        if globals.IsNSMBUDX:
            bits = tex.bits()
            bits.setsize(tex.byteCount())
            return bytes(bits)

        return writeGTX(tex, self.slot, normalmap)


    def PackTiles(self):
        offset = 0
        tilespack = struct.Struct('<Q')
        Tilebuffer = create_string_buffer(2048)
        for tile in self.tileset.tiles:
            tilespack.pack_into(Tilebuffer, offset, tile.getCollision())
            offset += 8

        return Tilebuffer.raw


    def PackObjects(self):
        objectStrings = []

        o = 0
        for object in self.tileset.objects:
            # Slopes
            if object.upperslope[0] != 0:

                # Reverse Slopes
                if object.upperslope[0] & 0x2:
                    a = struct.pack('>B', object.upperslope[0])

                    for row in range(object.lowerslope[1], object.height):
                        for tile in object.tiles[row]:
                            a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                        a += b'\xfe'

                    if object.height > 1 and object.lowerslope[1]:
                        a += struct.pack('>B', object.lowerslope[0])

                        for row in range(0, object.lowerslope[1]):
                            for tile in object.tiles[row]:
                                a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                            a += b'\xfe'

                    a += b'\xff'
                    objectStrings.append(a)

                # Regular Slopes
                else:
                    a = struct.pack('>B', object.upperslope[0])

                    for row in range(0, object.upperslope[1]):
                        for tile in object.tiles[row]:
                            a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                        a += b'\xfe'

                    if object.height > 1 and object.lowerslope[1]:
                        a += struct.pack('>B', object.lowerslope[0])

                        for row in range(object.upperslope[1], object.height):
                            for tile in object.tiles[row]:
                                a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                            a += b'\xfe'

                    a += b'\xff'
                    objectStrings.append(a)

            # Not slopes!
            else:
                a = b''
                for tilerow in object.tiles:
                    for tile in tilerow:
                        a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                    a += b'\xfe'
                a += b'\xff'
                objectStrings.append(a)
            o += 1

        Objbuffer = b''
        Metabuffer = b''
        i = 0
        for a in objectStrings:
            Metabuffer += struct.pack('<HBBH' if globals.IsNSMBUDX else '>HBBH', len(Objbuffer), self.tileset.objects[i].width, self.tileset.objects[i].height, self.tileset.objects[i].getRandByte())
            Objbuffer += a
            i += 1

        return (Objbuffer, Metabuffer)

    def toggleNormal(self):
        # Replace regular image with normalmap images in model
        self.normalmap = not self.normalmap

        self.setuptile()

        self.tileWidget.setObject(self.objectList.currentIndex())
        self.tileWidget.update()

    def toggleOverrides(self):
        self.overrides = not self.overrides

        row = self.objectList.currentIndex().row()

        self.setuptile()
        SetupObjectModel(self.objmodel, self, self.tileset.objects, self.tileset.tiles)

        count = self.objmodel.rowCount()
        if count > 0 and 0 <= row < count:
            index = self.objmodel.index(row, 0)
            self.objectList.setCurrentIndex(index)
            self.tileWidget.setObject(index)

        self.objectList.update()
        self.tileWidget.update()

    def showInfo(self):
        usedTiles = len(self.tileset.getUsedTiles())
        freeTiles = 256 - usedTiles
        QtWidgets.QMessageBox.information(self.window, "Tiles info",
                "Used Tiles: " + str(usedTiles) + (" tile.\n" if usedTiles == 1 else " tiles.\n")
                + "Free Tiles: " + str(freeTiles) + (" tile." if freeTiles == 1 else " tiles."),
                QtWidgets.QMessageBox.Ok)

    def importObjFromFile(self):
        usedTiles = self.tileset.getUsedTiles()
        if len(usedTiles) >= 256:  # It can't be more than 256, oh well
            QtWidgets.QMessageBox.warning(self.window, "Open Object",
                    "There isn't enough room in the Tileset.",
                    QtWidgets.QMessageBox.Cancel)
            return

        file = QtWidgets.QFileDialog.getOpenFileName(self.window, "Open Object", '',
                    "Object files (*.json)")[0]

        if not file: return

        with open(file) as inf:
            jsonData = json.load(inf)

        dir = os.path.dirname(file)

        tilelist = [[]]
        upperslope = [0, 0]
        lowerslope = [0, 0]

        metaData = open(dir + "/" + jsonData["meta"], "rb").read()
        objstrings = open(dir + "/" + jsonData["objlyt"], "rb").read()
        colls = open(dir + "/" + jsonData["colls"], "rb").read()

        randLen = 0

        if "randLen" in jsonData:
            randLen = (metaData[5] & 0xF)
            numTiles = randLen

        else:
            tilesUsed = []

            pos = 0
            while objstrings[pos] != 0xFF:
                if objstrings[pos] & 0x80:
                    pos += 1
                    continue

                tile = objstrings[pos:pos+3]
                if tile != b'\0\0\0':
                    if tile[1] not in tilesUsed:
                        tilesUsed.append(tile[1])

                pos += 3

            numTiles = len(tilesUsed)

        if numTiles + len(usedTiles) > 256:
            QtWidgets.QMessageBox.warning(self.window, "Open Object",
                    "There isn't enough room for the object.",
                    QtWidgets.QMessageBox.Cancel)
            return

        freeTiles = [i for i in range(256) if i not in usedTiles]

        if randLen:
            found = False
            for i in freeTiles:
                for z in range(randLen):
                    if i + z not in freeTiles:
                        break

                    if z == randLen - 1:
                        tileNum = i
                        found = True
                        break

                if found:
                    break

            if not found:
                QtWidgets.QMessageBox.warning(self.window, "Open Object",
                        "There isn't enough room for the object.",
                        QtWidgets.QMessageBox.Cancel)
                return

        tilesUsed = {}

        offset = 0
        byte = struct.unpack_from('>B', objstrings, offset)[0]
        i = 0
        row = 0

        while byte != 0xFF:

            if byte == 0xFE:
                tilelist.append([])

                if (upperslope[0] != 0) and (lowerslope[0] == 0):
                    upperslope[1] = upperslope[1] + 1

                if lowerslope[0] != 0:
                    lowerslope[1] = lowerslope[1] + 1

                offset += 1
                byte = struct.unpack_from('>B', objstrings, offset)[0]

            elif (byte & 0x80):

                if upperslope[0] == 0:
                    upperslope[0] = byte
                else:
                    lowerslope[0] = byte

                offset += 1
                byte = struct.unpack_from('>B', objstrings, offset)[0]

            else:
                tileBytes = objstrings[offset:offset + 3]
                if tileBytes == b'\0\0\0':
                    tile = [0, 0, 0]

                else:
                    tile = []
                    tile.append(byte)

                    if randLen:
                        tile.append(tileNum + i)
                        if i < randLen: i += 1

                    else:
                        if tileBytes[1] not in tilesUsed:
                            tilesUsed[tileBytes[1]] = i
                            tile.append(freeTiles[i])
                            i += 1
                        else:
                            tile.append(freeTiles[tilesUsed[tileBytes[1]]])

                    byte2 = (struct.unpack_from('>B', objstrings, offset + 2)[0]) & 0xFC
                    byte2 |= self.slot
                    tile.append(byte2)

                tilelist[-1].append(tile)

                offset += 3
                byte = struct.unpack_from('>B', objstrings, offset)[0]

        tilelist.pop()

        if (upperslope[0] & 0x80) and (upperslope[0] & 0x2):
            for i in range(lowerslope[1]):
                pop = tilelist.pop()
                tilelist.insert(0, pop)

        if randLen:
            self.tileset.addObject(metaData[3], metaData[2], metaData[5], upperslope, lowerslope, tilelist)
        else:
            self.tileset.addObject(metaData[3], metaData[2], 0, upperslope, lowerslope, tilelist)

        count = len(self.tileset.objects)
        object = self.tileset.objects[count-1]

        tileImage = QtGui.QPixmap(dir + "/" + jsonData["img"])
        nmlImage = QtGui.QPixmap(dir + "/" + jsonData["nml"])

        if randLen:
            tex = tileImage.copy(0,0,60,60)

            colls_off = 0
            for z in range(randLen):
                self.tileset.tiles[tileNum + z].image = tileImage.copy(z*60,0,60,60)
                self.tileset.tiles[tileNum + z].normalmap = nmlImage.copy(z*60,0,60,60)
                self.tileset.tiles[tileNum + z].setCollision(struct.unpack_from('<Q', colls, colls_off)[0])
                colls_off += 8

        else:
            tex = QtGui.QPixmap(object.width * 60, object.height * 60)
            tex.fill(Qt.transparent)
            painter = QtGui.QPainter(tex)

            Xoffset = 0
            Yoffset = 0

            colls_off = 0
            tilesReplaced = []

            for row in object.tiles:
                for tile in row:
                    if tile[2] & 3 or not self.slot:
                        if tile[1] not in tilesReplaced:
                            tilesReplaced.append(tile[1])

                            self.tileset.tiles[tile[1]].image = tileImage.copy(Xoffset,Yoffset,60,60)
                            self.tileset.tiles[tile[1]].normalmap = nmlImage.copy(Xoffset,Yoffset,60,60)
                            self.tileset.tiles[tile[1]].setCollision(struct.unpack_from('<Q', colls, colls_off)[0])

                        painter.drawPixmap(Xoffset, Yoffset, self.tileset.tiles[tile[1]].image)

                    Xoffset += 60
                    colls_off += 8

                Xoffset = 0
                Yoffset += 60

            painter.end()

        self.setuptile()

        self.objmodel.appendRow(QtGui.QStandardItem(QtGui.QIcon(tex.scaledToWidth(round(tex.width() / 60 * 24), Qt.SmoothTransformation)), 'Object {0}'.format(count-1)))
        index = self.objectList.currentIndex()
        self.objectList.setCurrentIndex(index)
        self.tileWidget.setObject(index)

        self.objectList.update()
        self.tileWidget.update()
        self.setDirty()

    def _fitObjectLimit(self):
        """
        Levels can only use a tileset's first MAX_OBJECTS objects (they store the object's
        number in a byte), so offers to save just those. False if the save is cancelled.
        """
        extra = len(self.tileset.objects) - MAX_OBJECTS
        if extra <= 0:
            return True
        answer = QtWidgets.QMessageBox.question(
            self.window, "Too Many Objects",
            "This tileset has %d objects, but a tileset can only have %d: levels can't use the "
            "other %d.\n\nSave it with only the first %d objects?"
            % (len(self.tileset.objects), MAX_OBJECTS, extra, MAX_OBJECTS))
        if answer != QtWidgets.QMessageBox.Yes:
            return False
        del self.tileset.objects[MAX_OBJECTS:]
        SetupObjectModel(self.objmodel, self, self.tileset.objects, self.tileset.tiles)
        self.objectList.update()
        self.tileWidget.update()
        self.setuptile()
        return True

    def _importSingleObject(self, jsonData, dirPath):
        """Import one object from (jsonData, dirPath) into this tileset. Returns True on success."""
        if len(self.tileset.objects) >= MAX_OBJECTS:
            return False, "too many objects"
        usedTiles = self.tileset.getUsedTiles()
        if len(usedTiles) >= 256:
            return False, "no room"

        metaData = open(os.path.join(dirPath, jsonData["meta"]), "rb").read()
        objstrings = open(os.path.join(dirPath, jsonData["objlyt"]), "rb").read()
        colls = open(os.path.join(dirPath, jsonData["colls"]), "rb").read()

        randLen = 0
        if "randLen" in jsonData:
            randLen = metaData[5] & 0xF
            numTiles = randLen
        else:
            tilesUsed = []
            pos = 0
            while objstrings[pos] != 0xFF:
                if objstrings[pos] & 0x80:
                    pos += 1
                    continue
                tile = objstrings[pos:pos + 3]
                if tile != b'\0\0\0':
                    if tile[1] not in tilesUsed:
                        tilesUsed.append(tile[1])
                pos += 3
            numTiles = len(tilesUsed)

        if numTiles + len(usedTiles) > 256:
            return False, "no room"

        freeTiles = [i for i in range(256) if i not in usedTiles]

        if randLen:
            found = False
            for i in freeTiles:
                for z in range(randLen):
                    if i + z not in freeTiles:
                        break
                    if z == randLen - 1:
                        tileNum = i
                        found = True
                        break
                if found:
                    break
            if not found:
                return False, "no room"

        tilelist = [[]]
        upperslope = [0, 0]
        lowerslope = [0, 0]
        tilesUsed = {}

        offset = 0
        byte = struct.unpack_from('>B', objstrings, offset)[0]
        i = 0

        while byte != 0xFF:
            if byte == 0xFE:
                tilelist.append([])
                if upperslope[0] != 0 and lowerslope[0] == 0:
                    upperslope[1] += 1
                if lowerslope[0] != 0:
                    lowerslope[1] += 1
                offset += 1
                byte = struct.unpack_from('>B', objstrings, offset)[0]

            elif byte & 0x80:
                if upperslope[0] == 0:
                    upperslope[0] = byte
                else:
                    lowerslope[0] = byte
                offset += 1
                byte = struct.unpack_from('>B', objstrings, offset)[0]

            else:
                tileBytes = objstrings[offset:offset + 3]
                if tileBytes == b'\0\0\0':
                    tile = [0, 0, 0]
                else:
                    tile = []
                    tile.append(byte)
                    if randLen:
                        tile.append(tileNum + i)
                        if i < randLen:
                            i += 1
                    else:
                        if tileBytes[1] not in tilesUsed:
                            tilesUsed[tileBytes[1]] = i
                            tile.append(freeTiles[i])
                            i += 1
                        else:
                            tile.append(freeTiles[tilesUsed[tileBytes[1]]])
                    byte2 = struct.unpack_from('>B', objstrings, offset + 2)[0] & 0xFC
                    byte2 |= self.slot
                    tile.append(byte2)
                tilelist[-1].append(tile)
                offset += 3
                byte = struct.unpack_from('>B', objstrings, offset)[0]

        tilelist.pop()

        if (upperslope[0] & 0x80) and (upperslope[0] & 0x2):
            for _ in range(lowerslope[1]):
                tilelist.insert(0, tilelist.pop())

        if randLen:
            self.tileset.addObject(metaData[3], metaData[2], metaData[5], upperslope, lowerslope, tilelist)
        else:
            self.tileset.addObject(metaData[3], metaData[2], 0, upperslope, lowerslope, tilelist)

        count = len(self.tileset.objects)
        obj = self.tileset.objects[count - 1]

        tileImage = QtGui.QPixmap(os.path.join(dirPath, jsonData["img"]))
        nmlImage = QtGui.QPixmap(os.path.join(dirPath, jsonData["nml"]))

        if randLen:
            tex = tileImage.copy(0, 0, 60, 60)
            colls_off = 0
            for z in range(randLen):
                self.tileset.tiles[tileNum + z].image = tileImage.copy(z * 60, 0, 60, 60)
                self.tileset.tiles[tileNum + z].normalmap = nmlImage.copy(z * 60, 0, 60, 60)
                self.tileset.tiles[tileNum + z].setCollision(struct.unpack_from('<Q', colls, colls_off)[0])
                colls_off += 8
        else:
            tex = QtGui.QPixmap(obj.width * 60, obj.height * 60)
            tex.fill(Qt.transparent)
            painter = QtGui.QPainter(tex)
            Xoffset = 0
            Yoffset = 0
            colls_off = 0
            tilesReplaced = []
            for row in obj.tiles:
                for tile in row:
                    if tile[2] & 3 or not self.slot:
                        if tile[1] not in tilesReplaced:
                            tilesReplaced.append(tile[1])
                            self.tileset.tiles[tile[1]].image = tileImage.copy(Xoffset, Yoffset, 60, 60)
                            self.tileset.tiles[tile[1]].normalmap = nmlImage.copy(Xoffset, Yoffset, 60, 60)
                            self.tileset.tiles[tile[1]].setCollision(struct.unpack_from('<Q', colls, colls_off)[0])
                        painter.drawPixmap(Xoffset, Yoffset, self.tileset.tiles[tile[1]].image)
                    Xoffset += 60
                    colls_off += 8
                Xoffset = 0
                Yoffset += 60
            painter.end()

        self.setuptile()

        scaled = tex.scaledToWidth(round(tex.width() / 60 * 24), Qt.SmoothTransformation)
        self.objmodel.appendRow(QtGui.QStandardItem(QtGui.QIcon(scaled), 'Object {0}'.format(count - 1)))
        self.objectList.update()
        self.tileWidget.update()
        self.setDirty()
        return True, ""

    def exportObject(self, name, baseName, n):
        object = self.tileset.objects[n]
        object.jsonData = {}

        if object.randLen and (object.width, object.height) == (1, 1):
            tex = QtGui.QPixmap(object.randLen * 60, object.height * 60)

        else:
            tex = QtGui.QPixmap(object.width * 60, object.height * 60)

        tex.fill(Qt.transparent)
        painter = QtGui.QPainter(tex)

        Xoffset = 0
        Yoffset = 0

        Tilebuffer = b''

        for i in range(len(object.tiles)):
            for tile in object.tiles[i]:
                if object.randLen and (object.width, object.height) == (1, 1):
                    for z in range(object.randLen):
                        if (self.slot == 0) or ((tile[2] & 3) != 0):
                            painter.drawPixmap(Xoffset, Yoffset, self.tileset.tiles[tile[1] + z].image)
                        Tilebuffer += struct.pack('<Q', self.tileset.tiles[tile[1] + z].getCollision())
                        Xoffset += 60
                    break

                else:
                    if (self.slot == 0) or ((tile[2] & 3) != 0):
                        painter.drawPixmap(Xoffset, Yoffset, self.tileset.tiles[tile[1]].image)
                    Tilebuffer += struct.pack('<Q', self.tileset.tiles[tile[1]].getCollision())
                    Xoffset += 60
            Xoffset = 0
            Yoffset += 60

        painter.end()

        # Slopes
        if object.upperslope[0] != 0:

            # Reverse Slopes
            if object.upperslope[0] & 0x2:
                a = struct.pack('>B', object.upperslope[0])

                for row in range(object.lowerslope[1], object.height):
                    for tile in object.tiles[row]:
                        a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                    a += b'\xfe'

                if object.height > 1 and object.lowerslope[1]:
                    a += struct.pack('>B', object.lowerslope[0])

                    for row in range(0, object.lowerslope[1]):
                        for tile in object.tiles[row]:
                            a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                        a += b'\xfe'

                a += b'\xff'


            # Regular Slopes
            else:
                a = struct.pack('>B', object.upperslope[0])

                for row in range(0, object.upperslope[1]):
                    for tile in object.tiles[row]:
                        a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                    a += b'\xfe'

                if object.height > 1 and object.lowerslope[1]:
                    a += struct.pack('>B', object.lowerslope[0])

                    for row in range(object.upperslope[1], object.height):
                        for tile in object.tiles[row]:
                            a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                        a += b'\xfe'

                a += b'\xff'


        # Not slopes!
        else:
            a = b''

            for tilerow in object.tiles:
                for tile in tilerow:
                    a += struct.pack('>BBB', tile[0], tile[1], tile[2])

                a += b'\xfe'

            a += b'\xff'

        Objbuffer = a
        Metabuffer = struct.pack('>HBBH', (0 if n == 0 else len(Objbuffer)), object.width, object.height, object.getRandByte())

        tex.save(name + ".png", "PNG")

        object.jsonData['img'] = baseName + ".png"

        with open(name + ".colls", "wb+") as colls:
            colls.write(Tilebuffer)

        object.jsonData['colls'] = baseName + ".colls"

        with open(name + ".objlyt", "wb+") as objlyt:
            objlyt.write(Objbuffer)

        object.jsonData['objlyt'] = baseName + ".objlyt"

        with open(name + ".meta", "wb+") as meta:
            meta.write(Metabuffer)

        object.jsonData['meta'] = baseName + ".meta"

        if object.randLen and (object.width, object.height) == (1, 1):
            object.jsonData['randLen'] = object.randLen

        if object.randLen and (object.width, object.height) == (1, 1):
            tex = QtGui.QPixmap(object.randLen * 60, object.height * 60)
        else:
            tex = QtGui.QPixmap(object.width * 60, object.height * 60)
        tex.fill(Qt.transparent)
        painter = QtGui.QPainter(tex)

        Xoffset = 0
        Yoffset = 0

        for i in range(len(object.tiles)):
            for tile in object.tiles[i]:
                if object.randLen and (object.width, object.height) == (1, 1):
                    for z in range(object.randLen):
                        if (self.slot == 0) or ((tile[2] & 3) != 0):
                            painter.drawPixmap(Xoffset, Yoffset, self.tileset.tiles[tile[1] + z].normalmap)
                        Xoffset += 60
                    break

                else:
                    if (self.slot == 0) or ((tile[2] & 3) != 0):
                        painter.drawPixmap(Xoffset, Yoffset, self.tileset.tiles[tile[1]].normalmap)
                    Xoffset += 60
            Xoffset = 0
            Yoffset += 60

        painter.end()

        tex.save(name + "_nml.png", "PNG")

        object.jsonData['nml'] = baseName + "_nml.png"

        with open(name + ".json", 'w+') as outfile:
            json.dump(object.jsonData, outfile)

    def saveAllObjects(self):
        save_path = QtWidgets.QFileDialog.getExistingDirectory(None, "Choose where to save the Object folder")
        if not save_path:
            return

        for n in range(len(self.tileset.objects)):
            baseName = "object_%d" % n
            name = os.path.join(save_path, baseName)

            self.exportObject(name, baseName, n)

    def saveObject(self):
        if len(self.tileset.objects) == 0: return
        dlg = getObjNum(len(self.tileset.objects) - 1)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            n = dlg.objNum.value()

            file = QtWidgets.QFileDialog.getSaveFileName(None, "Save Objects", "", "Object files (*.json)")[0]
            if not file:
                return

            name = os.path.splitext(file)[0]
            baseName = os.path.basename(name)

            self.exportObject(name, baseName, n)

    def clearObjects(self):
        '''Clears the object data'''
        self.tileset.objects = []
        SetupObjectModel(self.objmodel, self, self.tileset.objects, self.tileset.tiles)
        self.objectList.update()
        self.tileWidget.update()
        self.setDirty()

    def clearCollisions(self):
        '''Clears the collisions data'''
        for tile in self.tileset.tiles:
            tile.setCollision(0)

        self.updateInfo(0, 0)
        self.tileDisplay.update()
        self.setDirty()

    def _mergeDuplicateTiles(self, hashes):
        """
        Makes the objects share tiles that are the same (image, normal map and collision),
        freeing the copies: objects exported from one tileset share tiles, and importing
        them one by one gives each its own. Tiles of random objects (a run of tiles) and
        the main tileset's tile 0 and overridden tiles are left as they are.
        hashes caches the pixmaps' hashes between calls.
        """
        def mine(tile):
            return tile[2] & 3 or not self.slot

        def pixHash(pix):
            key = pix.cacheKey()
            if key not in hashes:
                image = pix.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)
                bits = image.constBits()
                bits.setsize(image.byteCount())
                hashes[key] = hash(bytes(bits))
            return hashes[key]

        protected = {0} if self.slot == 0 else set()
        if self.slot == 0:
            protected.update(i for i, tile in enumerate(self.tileset.overrides) if tile is not None)
        for obj in self.tileset.objects:
            if obj.randLen:
                for row in obj.tiles:
                    for tile in row:
                        if mine(tile):
                            protected.update(range(tile[1], tile[1] + obj.randLen))

        used = sorted({tile[1] for obj in self.tileset.objects if not obj.randLen
                       for row in obj.tiles for tile in row if mine(tile)} - protected)
        first, remap = {}, {}
        for idx in used:
            tile = self.tileset.tiles[idx]
            key = (pixHash(tile.image), pixHash(tile.normalmap), tile.getCollision())
            if key in first:
                remap[idx] = first[key]
            else:
                first[key] = idx
        if not remap:
            return

        for obj in self.tileset.objects:
            if obj.randLen:
                continue
            for row in obj.tiles:
                for i, tile in enumerate(row):
                    if mine(tile) and tile[1] in remap:
                        row[i] = type(tile)((tile[0], remap[tile[1]], tile[2]))

        blank = QtGui.QPixmap(60, 60)
        blank.fill(Qt.transparent)
        for idx in remap:
            self.tileset.tiles[idx].image = blank
            self.tileset.tiles[idx].normalmap = blank
            self.tileset.tiles[idx].setCollision(0)

    def importTilesetFromObjects(self):
        """
        Replaces this tileset with objects exported by Export all objects: a folder of them,
        or a ZIP or RAR (or 7z) of the files or of one folder with the files in it. The
        objects are added in name order, so they keep their numbers.
        """
        ask = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, "Import Tileset from Objects",
                                    "Import the objects from a ZIP or RAR file, or from a folder?",
                                    parent=self.window)
        fileButton = ask.addButton("ZIP/RAR File...", QtWidgets.QMessageBox.AcceptRole)
        folderButton = ask.addButton("Folder...", QtWidgets.QMessageBox.AcceptRole)
        ask.addButton(QtWidgets.QMessageBox.Cancel)
        ask.exec_()

        if ask.clickedButton() is fileButton:
            path = QtWidgets.QFileDialog.getOpenFileName(self.window, "Import Tileset from Objects", '',
                                                         "Archives (*.zip *.rar *.7z);;All files (*)")[0]
        elif ask.clickedButton() is folderButton:
            path = QtWidgets.QFileDialog.getExistingDirectory(self.window, "Import Tileset from Objects")
        else:
            return
        if not path:
            return

        with tempfile.TemporaryDirectory(prefix='yaz0moto-objects-') as tmp:
            root = path
            if os.path.isfile(path):
                QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    problem = extractArchive(path, tmp)
                finally:
                    QtWidgets.QApplication.restoreOverrideCursor()
                if problem:
                    QtWidgets.QMessageBox.warning(self.window, "Import Tileset from Objects", problem)
                    return
                root = tmp

            dirPath = findObjectFolder(root)
            if dirPath is None:
                QtWidgets.QMessageBox.warning(
                    self.window, "Import Tileset from Objects",
                    "No objects were found there.\n\nEach object needs its .json file, with the "
                    ".png, _nml.png, .colls, .meta and .objlyt files it names next to it "
                    "(as Objects > Export all objects... writes them).")
                return
            objects = loadObjectFolder(dirPath)

            if self.tileset.objects or self.tileset.getUsedTiles():
                answer = QtWidgets.QMessageBox.question(
                    self.window, "Import Tileset from Objects",
                    "This replaces every tile and object in this tileset with the %d objects found. "
                    "Continue?" % len(objects))
                if answer != QtWidgets.QMessageBox.Yes:
                    return

            # Start from a blank tileset, then add the objects in order (the files are read now)
            self.tileset.clear()
            self.newTileset()
            SetupObjectModel(self.objmodel, self, self.tileset.objects, self.tileset.tiles)

            imported = failed = 0
            hashes = {}
            for name, jsonData in objects:
                if len(self.tileset.objects) >= MAX_OBJECTS:
                    break
                try:
                    ok, _ = self._importSingleObject(jsonData, dirPath)
                except Exception:
                    ok = False
                if ok:
                    imported += 1
                    self._mergeDuplicateTiles(hashes)  # makes room for the next objects
                else:
                    failed += 1
            leftOut = len(objects) - imported - failed

        self.setuptile()
        SetupObjectModel(self.objmodel, self, self.tileset.objects, self.tileset.tiles)
        self.objectList.update()
        self.tileWidget.update()
        self.setDirty()

        message = "%d object%s imported." % (imported, '' if imported == 1 else 's')
        if failed:
            message += ("\n%d could not be imported (there was no room left in the tileset, "
                        "or their files are damaged)." % failed)
        if leftOut:
            message += ("\nThe last %d were left out: a tileset can only have %d objects "
                        "(levels can't use any more)." % (leftOut, MAX_OBJECTS))
        QtWidgets.QMessageBox.information(self.window, "Import Tileset from Objects", message)

    def updateInfo(self, x, y):
        self.showTileInfo(self.tileDisplay.indexAt(QtCore.QPoint(int(x), int(y))).row())

    def showTileInfo(self, index):
        """Shows a tile's properties above the tiles."""
        if index < 0 or index >= len(self.tileset.tiles):
            return

        curTile = self.tileset.tiles[index]
        palette = self.paletteWidget

        propertyList = []
        propertyText = ''

        if curTile.solidity == 0:
            propertyList.append('No Solidity')
        elif curTile.solidity == 1:
            propertyList.append('Solid')
        elif curTile.solidity == 2:
            propertyList.append('Solid-on-Top')
        elif curTile.solidity == 3:
            propertyList.append('Solid-on-Bottom')
        elif curTile.solidity == 4:
            propertyList.append('Solid-on-Top and Bottom')
        else:
            propertyList.append('Unknown Solidity')

        if curTile.slide == 1:
            propertyList.append('Force Slide')
        elif curTile.slide == 2:
            propertyList.append('Disable Slide')
        elif curTile.slide != 0:
            propertyList.append('Unknown Slide')


        if len(propertyList) == 1:
            propertyText = propertyList[0]
        else:
            propertyText = propertyList.pop(0)
            for string in propertyList:
                propertyText = propertyText + ', ' + string

        if palette.ParameterList[curTile.coreType] is not None:
            if curTile.params < len(palette.ParameterList[curTile.coreType]):
                parameter = palette.ParameterList[curTile.coreType][curTile.params]
            else:
                print('Error 1: %d, %d, %d' % (index, curTile.coreType, curTile.params))
                parameter = ['', QtGui.QIcon()]
        else:
            parameter = ['', QtGui.QIcon()]

        hex_data = '{0} {1} {2} | {3} {4} {5}'.format(
                             '%04X' % curTile.coreType, '%02X' % curTile.params, '%02X' % curTile.params2,
                             '%01X' % curTile.solidity, '%01X' % curTile.slide,  '%02X' % curTile.terrain)
        
        self.infoLabel.setText(f"Core: {palette.coreTypes[curTile.coreType][0]} • Param: {parameter[0]} • Collision: {propertyText}\n{hex_data} • Terrain: {palette.terrainTypes[curTile.terrain][0]}")

    # ---- Painting properties onto tiles (the Properties tab) ----
    #
    # With the Properties tab open, clicking a tile (or dragging over tiles) gives it the
    # properties picked there; Alt + click or a middle click picks a tile's properties
    # instead, and Ctrl+Z undoes the last strokes.

    def paintFormat(self, index):
        """Gives one tile the picked properties, as a click does (Properties tab only)."""
        if self.sideTabWidget.currentIndex() != 0:
            return
        self.beginPaintStroke()
        self.paintTile(index.row())
        self.endPaintStroke()

    def beginPaintStroke(self):
        self._stroke = {}  # tile index -> its collision value before the stroke

    def paintTile(self, row):
        if not 0 <= row < len(self.tileset.tiles):
            return
        tile = self.tileset.tiles[row]
        before = tile.getCollision()
        if self._stroke is not None:
            self._stroke.setdefault(row, before)
        self.paletteWidget.applyTo(tile)
        if tile.getCollision() != before:
            self.setDirty()
            self.tileDisplay.update(self.model.index(row, 0))
        self.showTileInfo(row)

    def endPaintStroke(self):
        if self._stroke:
            changed = {row: value for row, value in self._stroke.items()
                       if self.tileset.tiles[row].getCollision() != value}
            if changed:
                self._paintUndo = (self._paintUndo + [changed])[-100:]
        self._stroke = None

    def undoPaint(self):
        """Undoes the last stroke of painted properties."""
        if not self._paintUndo:
            return
        for row, value in self._paintUndo.pop().items():
            self.tileset.tiles[row].setCollision(value)
        self.tileDisplay.update()
        self.setDirty()

    def sideTabChanged(self, index):
        """The Properties tab shows the tiles' collision while it's open, as it's what it changes."""
        if index == 0:
            self._collisionShownBefore = self.showCollisionBtn.isChecked()
            self.showCollisionBtn.setChecked(True)
        elif self._collisionShownBefore is not None:
            self.showCollisionBtn.setChecked(self._collisionShownBefore)
            self._collisionShownBefore = None

    def pickProperties(self, idx):
        """Picks a tile's properties in the Properties tab (to give them to other tiles)."""
        self.paletteWidget.loadFrom(self.tileset.tiles[idx])
        self.sideTabWidget.setCurrentIndex(0)
        self.showTileInfo(idx)

    def updateCollisionOverlay(self, state):
        self.tileDisplay.showCollision = state
        self.tileDisplay.update()

    def updateTabTitle(self):
        self.window.updateTabTitle(self)


#############################################################################################
########################## Tileset Class and Tile/Object Subclasses #########################

class TilesetClass:
    '''Contains Tileset data. Inits itself to a blank tileset.
    Methods: addTile, removeTile, addObject, removeObject, clear'''

    class Tile:
        def __init__(self, image, nml, collision):
            '''Tile Constructor'''

            self.image = image
            self.normalmap = nml
            self.setCollision(collision)


        def setCollision(self, collision):
            self.coreType = (collision >>  0) & 0xFFFF
            self.params   = (collision >> 16) &   0xFF
            self.params2  = (collision >> 24) &   0xFF
            self.solidity = (collision >> 32) &    0xF
            self.slide    = (collision >> 36) &    0xF
            self.terrain  = (collision >> 40) &   0xFF


        def getCollision(self):
            return ((self.coreType <<  0) |
                    (self.params   << 16) |
                    (self.params2  << 24) |
                    (self.solidity << 32) |
                    (self.slide    << 36) |
                    (self.terrain  << 40))


    class Object:
        def __init__(self, height, width, randByte, uslope, lslope, tilelist):
            '''Tile Constructor'''

            self.randX = (randByte >> 4) & 1
            self.randY = (randByte >> 5) & 1
            self.randLen = randByte & 0xF

            self.upperslope = uslope
            self.lowerslope = lslope

            assert (width, height) != 0

            self.height = height
            self.width = width

            self.tiles = tilelist

            self.determineRepetition()

            if self.repeatX or self.repeatY:
                assert self.height == len(self.tiles)
                assert self.width == max(len(self.tiles[y]) for y in range(self.height))

                if self.repeatX:
                    self.determineRepetitionFinalize()

            else:
                # Fix a bug from a previous version of Puzzle
                # where the actual width and height would
                # mismatch with the number of tiles for the object

                self.fillMissingTiles()

            self.tilingMethodIdx = self.determineTilingMethod()


        def determineRepetition(self):
            self.repeatX = []
            self.repeatY = []

            if self.upperslope[0] != 0:
                return

            #### Find X Repetition ####
            # You can have different X repetitions between rows, so we have to account for that

            for y in range(self.height):
                repeatXBn = -1
                repeatXEd = -1

                for x in range(len(self.tiles[y])):
                    if self.tiles[y][x][0] & 1 and repeatXBn == -1:
                        repeatXBn = x

                    elif not self.tiles[y][x][0] & 1 and repeatXBn != -1:
                        repeatXEd = x
                        break

                if repeatXBn != -1:
                    if repeatXEd == -1:
                        repeatXEd = len(self.tiles[y])

                    self.repeatX.append((y, repeatXBn, repeatXEd))

            #### Find Y Repetition ####

            repeatYBn = -1
            repeatYEd = -1

            for y in range(self.height):
                if len(self.tiles[y]) and self.tiles[y][0][0] & 2:
                    if repeatYBn == -1:
                        repeatYBn = y

                elif repeatYBn != -1:
                    repeatYEd = y
                    break

            if repeatYBn != -1:
                if repeatYEd == -1:
                    repeatYEd = self.height

                self.repeatY = [repeatYBn, repeatYEd]


        def determineRepetitionFinalize(self):
            if self.repeatX:
                # If any X repetition is present, fill in rows which didn't have X repetition set
                ## Should never happen, unless the tileset is broken
                ## Additionally, sort the list
                repeatX = []
                for y in range(self.height):
                    for row, start, end in self.repeatX:
                        if y == row:
                            repeatX.append([start, end])
                            break

                    else:
                        # Get the start and end X offsets for the row
                        start = 0
                        end = len(self.tiles[y])

                        repeatX.append([start, end])

                self.repeatX = repeatX


        def fillMissingTiles(self):
            realH = len(self.tiles)
            while realH > self.height:
                del self.tiles[-1]
                realH -= 1

            for row in self.tiles:
                realW = len(row)
                while realW > self.width:
                    del row[-1]
                    realW -= 1

            for row in self.tiles:
                realW = len(row)
                while realW < self.width:
                    row.append((0, 0, 0))
                    realW += 1

            while realH < self.height:
                self.tiles.append([(0, 0, 0) for _ in range(self.width)])
                realH += 1


        def createRepetitionX(self):
            self.repeatX = []

            for y in range(self.height):
                for x in range(len(self.tiles[y])):
                    self.tiles[y][x] = (self.tiles[y][x][0] | 1, self.tiles[y][x][1], self.tiles[y][x][2])

                self.repeatX.append([0, len(self.tiles[y])])


        def createRepetitionY(self, y1, y2):
            self.clearRepetitionY()

            for y in range(y1, y2):
                for x in range(len(self.tiles[y])):
                    self.tiles[y][x] = (self.tiles[y][x][0] | 2, self.tiles[y][x][1], self.tiles[y][x][2])

            self.repeatY = [y1, y2]


        def clearRepetitionX(self):
            self.fillMissingTiles()

            for y in range(self.height):
                for x in range(self.width):
                    self.tiles[y][x] = (self.tiles[y][x][0] & ~1, self.tiles[y][x][1], self.tiles[y][x][2])

            self.repeatX = []


        def clearRepetitionY(self):
            for y in range(self.height):
                for x in range(len(self.tiles[y])):
                    self.tiles[y][x] = (self.tiles[y][x][0] & ~2, self.tiles[y][x][1], self.tiles[y][x][2])

            self.repeatY = []


        def clearRepetitionXY(self):
            self.clearRepetitionX()
            self.clearRepetitionY()


        def determineTilingMethod(self):
            if self.upperslope[0] == 0x93:
                return 7

            elif self.upperslope[0] == 0x92:
                return 6

            elif self.upperslope[0] == 0x91:
                return 5

            elif self.upperslope[0] == 0x90:
                return 4

            elif self.repeatX and self.repeatY:
                return 3

            elif self.repeatY:
                return 2

            elif self.repeatX:
                return 1

            return 0


        def getRandByte(self):
            """
            Builds the Randomization byte.
            """
            if (self.width, self.height) != (1, 1): return 0
            if self.randX + self.randY == 0: return 0
            byte = 0
            if self.randX: byte |= 16
            if self.randY: byte |= 32
            return byte | (self.randLen & 0xF)


    def __init__(self):
        '''Constructor'''

        self.tiles = []
        self.objects = []
        self.overrides = [None] * 256

        self.slot = 0
        self.placeNullChecked = False


    def addTile(self, image, nml, collision=0):
        '''Adds an tile class to the tile list with the passed image or parameters'''

        self.tiles.append(self.Tile(image, nml, collision))


    def addObject(self, height = 1, width = 1, randByte = 0, uslope = [0, 0], lslope = [0, 0], tilelist = None, new = False):
        '''Adds a new object'''

        if new:
            tilelist = [[(0, 0, self.slot)]]

        self.objects.append(self.Object(height, width, randByte, uslope, lslope, tilelist))


    def removeObject(self, index):
        '''Removes an Object by Index number. Don't use this much, because we want objects to preserve their ID.'''

        try:
            self.objects.pop(index)

        except IndexError:
            pass


    def clear(self):
        '''Clears the tileset for a new file'''

        self.tiles = []
        self.objects = []


    def processOverrides(self):
        if self.slot != 0:
            return

        try:
            t = self.overrides
            o = globals.Overrides

            # Invisible, brick and ? blocks
            ## Invisible
            replace = 3
            for i in [3, 4, 5, 6, 7, 8, 9, 10, 13, 29]:
                t[i] = o[replace].main
                replace += 1

            ## Brick
            for i in range(16, 28):
                t[i] = o[i].main

            ## ?
            t[49] = o[46].main
            for i in range(32, 43):
                t[i] = o[i].main

            # Collisions
            ## Full block
            t[1] = o[1].main

            ## Vine stopper
            t[2] = o[2].main

            ## Solid-on-top
            t[11] = o[13].main

            ## Half block
            t[12] = o[14].main

            ## Muncher (hit)
            t[45] = o[45].main

            ## Muncher (hit) 2
            t[209] = o[44].main

            ## Donut lift
            t[53] = o[43].main

            ## Conveyor belts
            ### Left
            #### Fast
            replace = 115
            for i in range(163, 166):
                t[i] = o[replace].main
                replace += 1
            #### Slow
            replace = 99
            for i in range(147, 150):
                t[i] = o[replace].main
                replace += 1

            ### Right
            #### Fast
            replace = 112
            for i in range(160, 163):
                t[i] = o[replace].main
                replace += 1
            #### Slow
            replace = 96
            for i in range(144, 147):
                t[i] = o[replace].main
                replace += 1

            ## Pipes
            ### Green
            #### Vertical
            t[64] = o[48].main
            t[65] = o[49].main
            t[80] = o[64].main
            t[81] = o[65].main
            t[96] = o[80].main
            t[97] = o[81].main
            #### Horizontal
            t[87] = o[71].main
            t[103] = o[87].main
            t[88] = o[72].main
            t[104] = o[88].main
            t[89] = o[73].main
            t[105] = o[89].main
            ### Yellow
            #### Vertical
            t[66] = o[50].main
            t[67] = o[51].main
            t[82] = o[66].main
            t[83] = o[67].main
            t[98] = o[82].main
            t[99] = o[83].main
            #### Horizontal
            t[90] = o[74].main
            t[106] = o[90].main
            t[91] = o[75].main
            t[107] = o[91].main
            t[92] = o[76].main
            t[108] = o[92].main
            ### Red
            #### Vertical
            t[68] = o[52].main
            t[69] = o[53].main
            t[84] = o[68].main
            t[85] = o[69].main
            t[100] = o[84].main
            t[101] = o[85].main
            #### Horizontal
            t[93] = o[77].main
            t[109] = o[93].main
            t[94] = o[78].main
            t[110] = o[94].main
            t[95] = o[79].main
            t[111] = o[95].main
            ### Mini (green)
            #### Vertical
            t[70] = o[54].main
            t[86] = o[70].main
            t[102] = o[86].main
            #### Horizontal
            t[120] = o[104].main
            t[121] = o[105].main
            t[137] = o[121].main
            ### Joints
            #### Normal
            t[118] = o[102].main
            t[119] = o[103].main
            t[134] = o[118].main
            t[135] = o[119].main
            #### Mini
            t[136] = o[120].main

            # Coins
            t[30] = o[30].main
            ## Outline
            t[31] = o[29].main
            ### Multiplayer
            t[28] = o[28].main
            ## Blue
            t[46] = o[47].main

            # Flowers / Grass
            grassType = 5
            for sprite in globals.Area.sprites:
                if sprite.type == 564:
                    grassType = min(sprite.spritedata[5] & 0xf, 5)
                    if grassType < 2:
                        grassType = 0

                    elif grassType in [3, 4]:
                        grassType = 3

            if grassType == 0:  # Forest
                replace_flowers = 160
                replace_grass = 163
                replace_both = 168

            elif grassType == 2:  # Underground
                replace_flowers = 55
                replace_grass = 171
                replace_both = 188

            elif grassType == 3:  # Sky
                replace_flowers = 176
                replace_grass = 179
                replace_both = 184

            else:  # Normal
                replace_flowers = 55
                replace_grass = 58
                replace_both = 106

            ## Flowers
            replace = replace_flowers
            for i in range(210, 213):
                t[i] = o[replace].main
                replace += 1
            ## Grass
            replace = replace_grass
            for i in range(178, 183):
                t[i] = o[replace].main
                replace += 1
            ## Flowers and grass
            replace = replace_both
            for i in range(213, 216):
                t[i] = o[replace].main
                replace += 1

            # Lines
            ## Straight lines
            ### Normal
            t[216] = o[128].main
            t[217] = o[63].main
            ### Corners and diagonals
            replace = 122
            for i in range(218, 231):
                if i != 224:  # random empty tile
                    t[i] = o[replace].main
                replace += 1

            ## Circles and stops
            for i in range(231, 256):
                t[i] = o[replace].main
                replace += 1

        except Exception:
            warningBox = QtWidgets.QMessageBox(QtWidgets.QMessageBox.NoIcon, 'OH NO',
                                               'Whoops, something went wrong while processing the overrides...')
            warningBox.exec_()


    def getUsedTiles(self):
        usedTiles = []

        if self.slot == 0:
            usedTiles.append(0)

            for i, tile in enumerate(self.overrides):
                if tile is not None:
                    usedTiles.append(i)

        for object in self.objects:
            for i in range(len(object.tiles)):
                for tile in object.tiles[i]:
                    if not tile[2] & 3 and self.slot:  # Pa0 tile 0 used in another slot, don't count it
                        continue

                    if object.randLen > 0:
                        for i in range(object.randLen):
                            if tile[1] + i not in usedTiles:
                                usedTiles.append(tile[1] + i)

                    else:
                        if tile[1] not in usedTiles:
                            usedTiles.append(tile[1])

        return usedTiles


#############################################################################################
######################### Palette for painting properties to tiles ##########################


class PropertyIconGrid(QtWidgets.QWidget):
    """Compact icon-button grid selector.  Acts like a read-only QComboBox but renders
    every option as a small checkable QToolButton so all choices are visible at once.
    Names and descriptions are surfaced via tooltips only, keeping the widget compact.
    """

    currentIndexChanged = QtCore.pyqtSignal(int)

    _BTN  = 38   # button pixel size
    _ICON = 24   # icon pixel size

    _STYLE = """
        QToolButton {
            border: 1px solid palette(mid);
            border-radius: 4px;
            background: transparent;
            padding: 2px;
        }
        QToolButton:checked {
            background-color: palette(highlight);
            border: 1px solid palette(highlight);
        }
        QToolButton:hover:!checked {
            background-color: palette(button);
        }
    """

    def __init__(self, items=None, cols=4, parent=None):
        super().__init__(parent)
        self._cols = cols
        self._buttons = []
        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.buttonClicked.connect(self._onClicked)
        self._gridLayout = QtWidgets.QGridLayout(self)
        self._gridLayout.setSpacing(2)
        self._gridLayout.setContentsMargins(2, 2, 2, 2)
        self.setStyleSheet(self._STYLE)
        if items:
            self.populate(items)

    @property
    def buttons(self):
        return list(self._buttons)

    def populate(self, items):
        for btn in list(self._group.buttons()):
            self._group.removeButton(btn)
            # Gone now: a button waiting for deleteLater would still be drawn over the new ones
            btn.hide()
            btn.setParent(None)
            btn.deleteLater()
        while self._gridLayout.count():
            self._gridLayout.takeAt(0)
        self._buttons = []

        for i, item_data in enumerate(items):
            name = item_data[0]
            icon = item_data[1] if len(item_data) > 1 else QtGui.QIcon()
            desc = item_data[2] if len(item_data) > 2 else ''

            btn = QtWidgets.QToolButton()
            btn.setCheckable(True)
            btn.setAutoExclusive(False)
            btn.setFixedSize(self._BTN, self._BTN)

            if not icon.isNull():
                btn.setIcon(icon)
                btn.setIconSize(QtCore.QSize(self._ICON, self._ICON))
                btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
            else:
                short = (name[:5] + '…') if len(name) > 5 else name
                btn.setText(short)
                f = btn.font()
                f.setPointSize(7)
                btn.setFont(f)
                btn.setToolButtonStyle(Qt.ToolButtonTextOnly)

            tip = f'<b>{name}</b>'
            if desc:
                tip += '<br><br>' + desc.replace('\n', '<br>')
            btn.setToolTip(tip)

            self._group.addButton(btn, i)
            self._buttons.append(btn)
            self._gridLayout.addWidget(btn, i // self._cols, i % self._cols)

        if self._buttons:
            self._buttons[0].setChecked(True)

        # The grid's size changed: let the panel make room for it (it was squashed to the
        # size it had before, cutting off the buttons)
        self._gridLayout.invalidate()
        self.updateGeometry()

    def _onClicked(self, btn):
        self.currentIndexChanged.emit(self._group.id(btn))

    def currentIndex(self):
        b = self._group.checkedButton()
        return self._group.id(b) if b is not None else 0

    def setCurrentIndex(self, idx):
        b = self._group.button(idx)
        if b:
            b.setChecked(True)


class paletteWidget(QtWidgets.QWidget):

    def __init__(self, editor=None, parent=None):
        super(paletteWidget, self).__init__(parent)
        self.editor = editor

        path = os.path.join(globals.miyamoto_path, 'yaz0data', 'Icons', '')

        self.coreTypes = [
            ['Default', QtGui.QIcon(path + 'Core/Default.png'), 'The standard type for tiles.\n\nAny regular terrain or backgrounds\nshould be of this generic type.'],
            ['Rails', QtGui.QIcon(path + 'Core/Rails.png'), 'Used for all types of rails.\n\nRails are replaced in-game with\n3D models, so modifying these\ntiles with different graphics\nwill have no effect.'],
            ['Dash Coin', QtGui.QIcon(path + 'Core/DashCoin.png'), 'Creates a dash coin.\n\nDash coins, also known as\n"coin outlines," turn into\na coin a second or so after they\nare touched by the player.'],
            ['Coin', QtGui.QIcon(path + 'Core/Coin.png'), 'Creates a coin.\n\nCoins have no solid collision,\nand when touched will disappear\nand increment the coin counter.\nUnused Blue Coins go in this\ncategory, too.'],
            ['Blue Coin', QtGui.QIcon(path + 'Core/BlueCoin.png'), 'This is used for the blue coin in Pa0_jyotyu\nthat has a black checkerboard outline.'],
            ['Explodable Block', QtGui.QIcon(path + 'Core/UsedWoodStoneRed.png'), 'Defines a used item block, a stone\nblock, a wooden block or a red block.'],
            ['Brick Block', QtGui.QIcon(path + 'Core/Brick.png'), 'Defines a brick block.'],
            ['? Block', QtGui.QIcon(path + 'Core/Qblock.png'), 'Defines a ? block.'],
            ['Red Block Outline(?)', QtGui.QIcon(path + 'Unknown.png'), 'Looking at NSMB2, this is supposedly the core type for Red Block Outline.'],
            ['Partial Block', QtGui.QIcon(path + 'Core/Partial.png'), '<b>DOESN\'T WORK!</b>\n\nUsed for blocks with partial collisions.\n\nVery useful for Mini-Mario secret\nareas, but also for providing a more\naccurate collision map for your tiles.\nUse with the "Solid" setting.'],
            ['Invisible Block', QtGui.QIcon(path + 'Core/Invisible.png'), 'Used for invisible item blocks.'],
            ['Slope', QtGui.QIcon(path + 'Core/Slope.png'), 'Defines a sloped tile.\n\nSloped tiles have sloped collisions,\nwhich Mario can slide on.'],
            ['Reverse Slope', QtGui.QIcon(path + 'Core/RSlope.png'), 'Defines an upside-down slope.\n\nSloped tiles have sloped collisions,\nwhich Mario can hit.'],
            ['Liquid', QtGui.QIcon(path + 'Core/Quicksand.png'), 'Creates a liquid area. All seen to be non-functional, except for Quicksand, which should be used with the "Quicksand" terrain type.'],
            ['Climbable Terrian', QtGui.QIcon(path + 'Core/Climb.png'), 'Creates terrain that can be\nclimbed on.\n\nClimable terrain cannot be walked on.\n\nWhen Mario is on top of a climable\ntile and the player presses up, Mario\nwill enter a climbing state.'],
            ['Damage Tile', QtGui.QIcon(path + 'Core/Skull.png'), 'Various damaging tiles.\n\nIcicle/Spike tiles will damage Mario one hit\nwhen they are touched, whereas lava and poison water will instantly kill Mario and play the corresponding death animation.'],
            ['Pipe/Joint', QtGui.QIcon(path + 'Core/Pipe.png'), 'Denotes a pipe tile, or a pipe joint.\n\nPipe tiles are specified according to\nthe part of the pipe. It\'s important\nto specify the right parts or\nentrances may not function correctly.'],
            ['Conveyor Belt', QtGui.QIcon(path + 'Core/Conveyor.png'), 'Defines moving tiles.\n\nMoving tiles will move Mario in one\ndirection or another.'],
            ['Donut Block', QtGui.QIcon(path + 'Core/Donut.png'), 'Creates a falling donut block.\n\nThese blocks fall after they have been\nstood on for a few seconds, and then\nrespawn later. They are replaced by\nthe game with 3D models, so you can\'t\neasily make your own.'],
            ['Cave Entrance', QtGui.QIcon(path + 'Core/Cave.png'), 'Creates a cave entrance.\n\nCave entrances are used to mark secret\nareas hidden behind Layer 0 tiles.'],
            ['Hanging Ledge', QtGui.QIcon(path + 'Core/Ledge.png'), 'Creates a hanging ledge, or terrain that can be\nclimbed on with a ledge.\n\nYou cannot climb down from the <b>hanging</b> ledge\nif climable terrian is under it,\nand you cannot climb up from the climable terrian\nif the <b>hanging</b> ledge is above it.\n\nFor such behavior, you need the climbable wall with ledge.'],
            ['Rope', QtGui.QIcon(path + 'Core/Rope.png'), 'Unused type that produces a rope you can hang to. If solidity is set to "None," it will have no effect. "Solid on Top" and "Solid on Bottom" produce no useful behavior.'],
            ['Climbable Pole', QtGui.QIcon(path + 'Core/Pole.png'), 'Creates a pole that can be climbed. Use with "No Solidity."'],
        ]

        # ---- No old radio/combo widget construction needed — all replaced below ----


        GenericParams = [
            ['Normal', QtGui.QIcon()],
            ['Beanstalk Stop', QtGui.QIcon(path + '/Generic/Beanstopper.png')],
        ]

        RailParams = [
            ['Upslope', QtGui.QIcon(path + 'Rails/Upslope.png')],
            ['Downslope', QtGui.QIcon(path + 'Rails/Downslope.png')],
            ['Top-Left Corner', QtGui.QIcon(path + 'Rails/Top-Left Corner.png')],
            ['Bottom-Right Corner', QtGui.QIcon(path + 'Rails/Bottom-Right Corner.png')],
            ['Horizontal', QtGui.QIcon(path + 'Rails/Horizontal.png')],
            ['Vertical', QtGui.QIcon(path + 'Rails/Vertical.png')],
            ['Blank', QtGui.QIcon()],
            ['Gentle Upslope 2', QtGui.QIcon(path + 'Rails/Gentle Upslope 2.png')],
            ['Gentle Upslope 1', QtGui.QIcon(path + 'Rails/Gentle Upslope 1.png')],
            ['Gentle Downslope 2', QtGui.QIcon(path + 'Rails/Gentle Downslope 2.png')],
            ['Gentle Downslope 1', QtGui.QIcon(path + 'Rails/Gentle Downslope 1.png')],
            ['Steep Upslope 2', QtGui.QIcon(path + 'Rails/Steep Upslope 2.png')],
            ['Steep Upslope 1', QtGui.QIcon(path + 'Rails/Steep Upslope 1.png')],
            ['Steep Downslope 2', QtGui.QIcon(path + 'Rails/Steep Downslope 2.png')],
            ['Steep Downslope 1', QtGui.QIcon(path + 'Rails/Steep Downslope 1.png')],
            ['1x1 Circle', QtGui.QIcon(path + 'Rails/1x1 Circle.png')],
            ['2x2 Circle Upper Right', QtGui.QIcon(path + 'Rails/2x2 Circle Upper Right.png')],
            ['2x2 Circle Upper Left', QtGui.QIcon(path + 'Rails/2x2 Circle Upper Left.png')],
            ['2x2 Circle Lower Right', QtGui.QIcon(path + 'Rails/2x2 Circle Lower Right.png')],
            ['2x2 Circle Lower Left', QtGui.QIcon(path + 'Rails/2x2 Circle Lower Left.png')],

            ['4x4 Circle Top Left Corner', QtGui.QIcon(path + 'Rails/4x4 Circle Top Left Corner.png')],
            ['4x4 Circle Top Left', QtGui.QIcon(path + 'Rails/4x4 Circle Top Left.png')],
            ['4x4 Circle Top Right', QtGui.QIcon(path + 'Rails/4x4 Circle Top Right.png')],
            ['4x4 Circle Top Right Corner', QtGui.QIcon(path + 'Rails/4x4 Circle Top Right Corner.png')],

            ['4x4 Circle Upper Left Side', QtGui.QIcon(path + 'Rails/4x4 Circle Upper Left Side.png')],
            ['4x4 Circle Upper Right Side', QtGui.QIcon(path + 'Rails/4x4 Circle Upper Right Side.png')],

            ['4x4 Circle Lower Left Side', QtGui.QIcon(path + 'Rails/4x4 Circle Lower Left Side.png')],
            ['4x4 Circle Lower Right Side', QtGui.QIcon(path + 'Rails/4x4 Circle Lower Right Side.png')],

            ['4x4 Circle Bottom Left Corner', QtGui.QIcon(path + 'Rails/4x4 Circle Bottom Left Corner.png')],
            ['4x4 Circle Bottom Left', QtGui.QIcon(path + 'Rails/4x4 Circle Bottom Left.png')],
            ['4x4 Circle Bottom Right', QtGui.QIcon(path + 'Rails/4x4 Circle Bottom Right.png')],
            ['4x4 Circle Bottom Right Corner', QtGui.QIcon(path + 'Rails/4x4 Circle Bottom Right Corner.png')],

            ['End Stop', QtGui.QIcon(path + 'Rails/End Stop.png')],
        ]

        CoinParams = [
            ['Generic Coin', QtGui.QIcon(path + 'Core/Coin.png')],
            ['Nothing', QtGui.QIcon()],
            ['Blue Coin', QtGui.QIcon(path + 'Core/BlueCoin.png')],
        ]

        ExplodableBlockParams = [
            ['Used Item Block', QtGui.QIcon(path + 'ExplodableBlock/Used.png')],
            ['Stone Block', QtGui.QIcon(path + 'ExplodableBlock/Stone.png')],
            ['Wooden Block', QtGui.QIcon(path + 'ExplodableBlock/Wooden.png')],
            ['Red Block', QtGui.QIcon(path + 'ExplodableBlock/Red.png')],
        ]

        PartialParams = [
            ['Upper Left', QtGui.QIcon(path + 'Partial/UpLeft.png')],
            ['Upper Right', QtGui.QIcon(path + 'Partial/UpRight.png')],
            ['Top Half', QtGui.QIcon(path + 'Partial/TopHalf.png')],
            ['Lower Left', QtGui.QIcon(path + 'Partial/LowLeft.png')],
            ['Left Half', QtGui.QIcon(path + 'Partial/LeftHalf.png')],
            ['Diagonal Downwards', QtGui.QIcon(path + 'Partial/DiagDn.png')],
            ['Upper Left 3/4', QtGui.QIcon(path + 'Partial/UpLeft3-4.png')],
            ['Lower Right', QtGui.QIcon(path + 'Partial/LowRight.png')],
            ['Diagonal Downwards', QtGui.QIcon(path + 'Partial/DiagDn.png')],
            ['Right Half', QtGui.QIcon(path + 'Partial/RightHalf.png')],
            ['Upper Right 3/4', QtGui.QIcon(path + 'Partial/UpRig3-4.png')],
            ['Lower Half', QtGui.QIcon(path + 'Partial/LowHalf.png')],
            ['Lower Left 3/4', QtGui.QIcon(path + 'Partial/LowLeft3-4.png')],
            ['Lower Right 3/4', QtGui.QIcon(path + 'Partial/LowRight3-4.png')],
            ['Full Brick', QtGui.QIcon(path + 'Partial/Full.png')],
        ]

        SlopeParams = [
            ['Steep Upslope', QtGui.QIcon(path + 'Slope/steepslopeleft.png')],
            ['Steep Downslope', QtGui.QIcon(path + 'Slope/steepsloperight.png')],
            ['Upslope 1', QtGui.QIcon(path + 'Slope/slopeleft.png')],
            ['Upslope 2', QtGui.QIcon(path + 'Slope/slope3left.png')],
            ['Downslope 1', QtGui.QIcon(path + 'Slope/slope3right.png')],
            ['Downslope 2', QtGui.QIcon(path + 'Slope/sloperight.png')],
            ['Very Steep Upslope 1', QtGui.QIcon(path + 'Slope/vsteepup1.png')],
            ['Very Steep Upslope 2', QtGui.QIcon(path + 'Slope/vsteepup2.png')],
            ['Very Steep Downslope 1', QtGui.QIcon(path + 'Slope/vsteepdown2.png')],
            ['Very Steep Downslope 2', QtGui.QIcon(path + 'Slope/vsteepdown1.png')],
            ['Slope Edge (solid)', QtGui.QIcon(path + 'Slope/edge.png')],
            ['Gentle Upslope 1', QtGui.QIcon(path + 'Slope/gentleupslope1.png')],
            ['Gentle Upslope 2', QtGui.QIcon(path + 'Slope/gentleupslope2.png')],
            ['Gentle Upslope 3', QtGui.QIcon(path + 'Slope/gentleupslope3.png')],
            ['Gentle Upslope 4', QtGui.QIcon(path + 'Slope/gentleupslope4.png')],
            ['Gentle Downslope 1', QtGui.QIcon(path + 'Slope/gentledownslope1.png')],
            ['Gentle Downslope 2', QtGui.QIcon(path + 'Slope/gentledownslope2.png')],
            ['Gentle Downslope 3', QtGui.QIcon(path + 'Slope/gentledownslope3.png')],
            ['Gentle Downslope 4', QtGui.QIcon(path + 'Slope/gentledownslope4.png')],
        ]

        ReverseSlopeParams = [
            ['Steep Downslope', QtGui.QIcon(path + 'Slope/Rsteepslopeleft.png')],
            ['Steep Upslope', QtGui.QIcon(path + 'Slope/Rsteepsloperight.png')],
            ['Downslope 1', QtGui.QIcon(path + 'Slope/Rslopeleft.png')],
            ['Downslope 2', QtGui.QIcon(path + 'Slope/Rslope3left.png')],
            ['Upslope 1', QtGui.QIcon(path + 'Slope/Rslope3right.png')],
            ['Upslope 2', QtGui.QIcon(path + 'Slope/Rsloperight.png')],
            ['Very Steep Downslope 1', QtGui.QIcon(path + 'Slope/Rvsteepdown1.png')],
            ['Very Steep Downslope 2', QtGui.QIcon(path + 'Slope/Rvsteepdown2.png')],
            ['Very Steep Upslope 1', QtGui.QIcon(path + 'Slope/Rvsteepup2.png')],
            ['Very Steep Upslope 2', QtGui.QIcon(path + 'Slope/Rvsteepup1.png')],
            ['Slope Edge (solid)', QtGui.QIcon(path + 'Slope/edge.png')],
            ['Gentle Downslope 1', QtGui.QIcon(path + 'Slope/Rgentledownslope1.png')],
            ['Gentle Downslope 2', QtGui.QIcon(path + 'Slope/Rgentledownslope2.png')],
            ['Gentle Downslope 3', QtGui.QIcon(path + 'Slope/Rgentledownslope3.png')],
            ['Gentle Downslope 4', QtGui.QIcon(path + 'Slope/Rgentledownslope4.png')],
            ['Gentle Upslope 1', QtGui.QIcon(path + 'Slope/Rgentleupslope1.png')],
            ['Gentle Upslope 2', QtGui.QIcon(path + 'Slope/Rgentleupslope2.png')],
            ['Gentle Upslope 3', QtGui.QIcon(path + 'Slope/Rgentleupslope3.png')],
            ['Gentle Upslope 4', QtGui.QIcon(path + 'Slope/Rgentleupslope4.png')],
        ]

        LiquidParams = [
            ['Unknown 0', QtGui.QIcon(path + 'Unknown.png')],
            ['Unknown 1', QtGui.QIcon(path + 'Unknown.png')],
            ['Unknown 2', QtGui.QIcon(path + 'Unknown.png')],
            ['Unknown 3', QtGui.QIcon(path + 'Unknown.png')],
            ['Quicksand', QtGui.QIcon(path + 'Core/Quicksand.png')],
        ]

        ClimbableParams = [
            ['Vine', QtGui.QIcon(path + 'Climbable/Vine.png')],
            ['Climbable Wall', QtGui.QIcon(path + 'Core/Climb.png')],
            ['Climbable Fence', QtGui.QIcon(path + 'Climbable/Fence.png')],
        ]

        DamageTileParams = [
            ['Icicle', QtGui.QIcon(path + 'Damage/Icicle1x1.png')],
            ['Long Icicle 1', QtGui.QIcon(path + 'Damage/Icicle1x2Top.png')],
            ['Long Icicle 2', QtGui.QIcon(path + 'Damage/Icicle1x2Bottom.png')],
            ['Left-Facing Spikes', QtGui.QIcon(path + 'Damage/SpikeLeft.png')],
            ['Right-Facing Spikes', QtGui.QIcon(path + 'Damage/SpikeRight.png')],
            ['Up-Facing Spikes', QtGui.QIcon(path + 'Damage/Spike.png')],
            ['Down-Facing Spikes', QtGui.QIcon(path + 'Damage/SpikeDown.png')],
            ['Instant Death', QtGui.QIcon(path + 'Core/Skull.png')],
            ['Lava', QtGui.QIcon(path + 'Damage/Lava.png')],
            ['Poison Water', QtGui.QIcon(path + 'Damage/Poison.png')],
        ]

        PipeParams = [
            ['Vert. Top Entrance Left', QtGui.QIcon(path + 'Pipes/UpLeft.png')],
            ['Vert. Top Entrance Right', QtGui.QIcon(path + 'Pipes/UpRight.png')],
            ['Vert. Bottom Entrance Left', QtGui.QIcon(path + 'Pipes/DownLeft.png')],
            ['Vert. Bottom Entrance Right', QtGui.QIcon(path + 'Pipes/DownRight.png')],
            ['Horiz. Left Entrance Top', QtGui.QIcon(path + 'Pipes/LeftTop.png')],
            ['Horiz. Left Entrance Bottom', QtGui.QIcon(path + 'Pipes/LeftBottom.png')],
            ['Horiz. Right Entrance Top', QtGui.QIcon(path + 'Pipes/RightTop.png')],
            ['Horiz. Right Entrance Bottom', QtGui.QIcon(path + 'Pipes/RightBottom.png')],
            ['Vert. Mini Pipe Top', QtGui.QIcon(path + 'Pipes/MiniUp.png')],
            ['Vert. Mini Pipe Bottom', QtGui.QIcon(path + 'Pipes/MiniDown.png')],
            ['Horiz. Mini Pipe Left', QtGui.QIcon(path + 'Pipes/MiniLeft.png')],
            ['Horiz. Mini Pipe Right', QtGui.QIcon(path + 'Pipes/MiniRight.png')],
            ['Vert. Center Left', QtGui.QIcon(path + 'Pipes/VertCenterLeft.png')],
            ['Vert. Center Right', QtGui.QIcon(path + 'Pipes/VertCenterRight.png')],
            ['Vert. Intersection Left', QtGui.QIcon(path + 'Pipes/VertIntersectLeft.png')],
            ['Vert. Intersection Right', QtGui.QIcon(path + 'Pipes/VertIntersectRight.png')],
            ['Horiz. Center Top', QtGui.QIcon(path + 'Pipes/HorizCenterTop.png')],
            ['Horiz. Center Bottom', QtGui.QIcon(path + 'Pipes/HorizCenterBottom.png')],
            ['Horiz. Intersection Top', QtGui.QIcon(path + 'Pipes/HorizIntersectTop.png')],
            ['Horiz. Intersection Bottom', QtGui.QIcon(path + 'Pipes/HorizIntersectBottom.png')],
            ['UNUSED', QtGui.QIcon(path + 'Unknown.png')],
            ['UNUSED', QtGui.QIcon(path + 'Unknown.png')],
            ['UNUSED', QtGui.QIcon(path + 'Unknown.png')],
            ['Vert. Mini Pipe Center', QtGui.QIcon(path + 'Pipes/MiniVertCenter.png')],
            ['Horiz. Mini Pipe Center', QtGui.QIcon(path + 'Pipes/MiniHorizCenter.png')],
            ['UNUSED', QtGui.QIcon(path + 'Unknown.png')],
            ['UNUSED', QtGui.QIcon(path + 'Unknown.png')],
            ['UNUSED', QtGui.QIcon(path + 'Unknown.png')],
            ['UNUSED', QtGui.QIcon(path + 'Unknown.png')],
            ['UNUSED', QtGui.QIcon(path + 'Unknown.png')],
            ['UNUSED', QtGui.QIcon(path + 'Unknown.png')],
            ['UNUSED', QtGui.QIcon(path + 'Unknown.png')],
            ['UNUSED', QtGui.QIcon(path + 'Unknown.png')],
            ['UNUSED', QtGui.QIcon(path + 'Unknown.png')],
            ['UNUSED', QtGui.QIcon(path + 'Unknown.png')],
            ['Pipe Joint', QtGui.QIcon(path + 'Pipes/Joint.png')],
            ['Vert. Mini Pipe Intersection', QtGui.QIcon(path + 'Pipes/MiniVertIntersect.png')],
            ['Horiz. Mini Pipe Intersection', QtGui.QIcon(path + 'Pipes/MiniHorizIntersect.png')],
        ]

        ConveyorParams = [
            ['Left', QtGui.QIcon(path + 'Conveyor/Left.png')],
            ['Right', QtGui.QIcon(path + 'Conveyor/Right.png')],
            ['Left Fast', QtGui.QIcon(path + 'Conveyor/LeftFast.png')],
            ['Right Fast', QtGui.QIcon(path + 'Conveyor/RightFast.png')],
        ]

        CaveParams = [
            ['Left', QtGui.QIcon(path + 'Cave/Left.png')],
            ['Right', QtGui.QIcon(path + 'Cave/Right.png')],
        ]

        ClimbLedgeParams = [
            ['Hanging Ledge', QtGui.QIcon(path + 'Core/Ledge.png')],
            ['Climbable Wall with Ledge', QtGui.QIcon(path + 'Core/ClimbLedge.png')],
        ]


        self.ParameterList = [
            GenericParams,          # 0x00
            RailParams,             # 0x01
            None,                   # 0x02
            CoinParams,             # 0x03
            None,                   # 0x04
            ExplodableBlockParams,  # 0x05
            None,                   # 0x06
            None,                   # 0x07
            None,                   # 0x08
            PartialParams,          # 0x09
            None,                   # 0x0A
            SlopeParams,            # 0x0B
            ReverseSlopeParams,     # 0x0C
            LiquidParams,           # 0x0D
            ClimbableParams,        # 0x0E
            DamageTileParams,       # 0x0F
            PipeParams,             # 0x10
            ConveyorParams,         # 0x11
            None,                   # 0x12
            CaveParams,             # 0x13
            ClimbLedgeParams,       # 0x14
            None,                   # 0x15
            None,                   # 0x16
        ]


        DamageTileParams2 = [
            ['Default', QtGui.QIcon()],
            ['Muncher (no visible difference)', QtGui.QIcon(path + 'Damage/Muncher.png')],
        ]

        PipeParams2 = [
            ['Green', QtGui.QIcon(path + 'PipeColors/Green.png')],
            ['Red', QtGui.QIcon(path + 'PipeColors/Red.png')],
            ['Yellow', QtGui.QIcon(path + 'PipeColors/Yellow.png')],
            ['Blue', QtGui.QIcon(path + 'PipeColors/Blue.png')],
        ]

        self.ParameterList2 = [
            None,               # 0x0
            None,               # 0x1
            None,               # 0x2
            None,               # 0x3
            None,               # 0x4
            None,               # 0x5
            None,               # 0x6
            None,               # 0x7
            None,               # 0x8
            None,               # 0x9
            None,               # 0xA
            None,               # 0xB
            None,               # 0xC
            None,               # 0xD
            None,               # 0xE
            DamageTileParams2,  # 0xF
            PipeParams2,        # 0x10
            None,               # 0x11
            None,               # 0x12
            None,               # 0x13
            None,               # 0x14
            None,               # 0x15
            None,               # 0x16
        ]


        self.collsTypes = [
            ['No Solidity',             QtGui.QIcon(path + 'Collisions/NoSolidity.png'),    'The tile cannot be stood on or hit.'],
            ['Solid',                   QtGui.QIcon(path + 'Collisions/Solid.png'),          'The tile can be stood on and hit from all sides.'],
            ['Solid-on-Top',            QtGui.QIcon(path + 'Collisions/SolidOnTop.png'),     'The tile can only be stood on.'],
            ['Solid-on-Bottom',         QtGui.QIcon(path + 'Collisions/SolidOnBottom.png'),  'The tile can only be hit from below.'],
            ['Solid Top+Bottom',        QtGui.QIcon(path + 'Collisions/SolidOnTopBottom.png'), 'Can be stood on and hit from below, but not any other side.'],
            ['Solid Slide',             QtGui.QIcon(path + 'Collisions/Slide.png'),    'Forced players into sliding and disables jumping.'],
            ['Solid-on-Top Slide',      QtGui.QIcon(path + 'Collisions/SlideTop.png'),    'Forced players into sliding and disables jumping.'],
            ['Solid Staircase',         QtGui.QIcon(path + 'Collisions/Staircase.png'), 'Disables sliding on slopes.'],
            ['Solid-on-Top Staircase',  QtGui.QIcon(path + 'Collisions/StaircaseTop.png'), 'Disables sliding on slopes.'],
        ]

        # Quicksand is unused.
        self.terrainTypes = [
            ['Default',        QtGui.QIcon(path + 'Terrain/Default.png'),              'No special terrain properties.'],             # 0x0
            ['Ice',            QtGui.QIcon(path + 'Terrain/Ice.png'),                  'Will be slippery.'],                          # 0x1
            ['Snow',           QtGui.QIcon(path + 'Terrain/Snow.png'),                 'Emits puffs of snow and snow footstep sounds.'], # 0x2
            ['Quicksand',      QtGui.QIcon(path + 'Terrain/Quicksand.png'),            'Emits puffs of sand. Use with Quicksand core type.'], # 0x3
            ['Desert Sand',    QtGui.QIcon(path + 'Terrain/Sand.png'),                 'Creates dark-colored sand tufts around Mario\'s feet.'], # 0x4
            ['Grass',          QtGui.QIcon(path + 'Terrain/Grass.png'),                'Emits grass-like footstep sounds.'],          # 0x5
            ['Cloud',          QtGui.QIcon(path + 'Terrain/Cloud.png'),                'Emits footstep sounds for cloud platforms.'], # 0x6
            ['Beach Sand',     QtGui.QIcon(path + 'Terrain/BeachSand.png'),            'Creates light-colored sand tufts around Mario\'s feet.'], # 0x7
            ['Carpet',         QtGui.QIcon(path + 'Terrain/Carpet.png'),               'Emits carpet footstep sounds.'],              # 0x8
            ['Leaves',         QtGui.QIcon(path + 'Terrain/Leaves.png'),               'Emits palm tree leaf footstep sounds.'],      # 0x9
            ['Wood',           QtGui.QIcon(path + 'Terrain/Wood.png'),                 'Emits wood footstep sounds.'],                # 0xA
            ['Water',          QtGui.QIcon(path + 'Terrain/Water.png'),                'Emits small water splashes around Mario\'s feet.'], # 0xB
            ['Beanstalk Leaf', QtGui.QIcon(path + 'Terrain/BeanstalkLeaf.png'),        'Emits beanstalk leaf footstep sounds.'],      # 0xC
        ]

        # ---- Build the scrollable UI ----
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

        content = QtWidgets.QWidget()
        mainLayout = QtWidgets.QVBoxLayout(content)
        mainLayout.setSpacing(6)
        mainLayout.setContentsMargins(4, 4, 4, 4)

        # Hint text
        hintLabel = QtWidgets.QLabel('Click a tile, or drag over tiles, to give them the properties picked '
                                     'here; the collision is shown on the tiles. Alt + click (or middle-click) '
                                     'a tile to pick its properties. Ctrl+Z undoes.')
        hintLabel.setWordWrap(True)
        hintLabel.setStyleSheet('color: #888; font-style: italic; font-size: 11px;')
        mainLayout.addWidget(hintLabel)

        # What clicking a tile gives it
        self.summaryLabel = QtWidgets.QLabel()
        self.summaryLabel.setWordWrap(True)
        mainLayout.addWidget(self.summaryLabel)

        # Core Type section
        coreGroup = QtWidgets.QGroupBox('Core Type')
        coreGroupLayout = QtWidgets.QVBoxLayout(coreGroup)
        coreGroupLayout.setContentsMargins(4, 6, 4, 4)
        self.coreGrid = PropertyIconGrid(self.coreTypes, cols=8)
        self.coreGrid.currentIndexChanged.connect(self.swapParams)
        coreGroupLayout.addWidget(self.coreGrid)
        mainLayout.addWidget(coreGroup)

        # Parameters section (shown/hidden by swapParams)
        self.params1Group = QtWidgets.QGroupBox('Parameters')
        params1Layout = QtWidgets.QVBoxLayout(self.params1Group)
        params1Layout.setContentsMargins(4, 6, 4, 4)
        self.params1Grid = PropertyIconGrid(cols=6)
        params1Layout.addWidget(self.params1Grid)
        mainLayout.addWidget(self.params1Group)

        self.params2Group = QtWidgets.QGroupBox('Secondary Parameters')
        params2Layout = QtWidgets.QVBoxLayout(self.params2Group)
        params2Layout.setContentsMargins(4, 6, 4, 4)
        self.params2Grid = PropertyIconGrid(cols=4)
        params2Layout.addWidget(self.params2Grid)
        mainLayout.addWidget(self.params2Group)

        # Collision section
        collisionGroup = QtWidgets.QGroupBox('Collision')
        collisionLayout = QtWidgets.QVBoxLayout(collisionGroup)
        collisionLayout.setContentsMargins(4, 6, 4, 4)
        self.collisionGrid = PropertyIconGrid(self.collsTypes, cols=5)
        collisionLayout.addWidget(self.collisionGrid)
        mainLayout.addWidget(collisionGroup)

        # Terrain section
        terrainGroup = QtWidgets.QGroupBox('Terrain')
        terrainLayout = QtWidgets.QVBoxLayout(terrainGroup)
        terrainLayout.setContentsMargins(4, 6, 4, 4)
        self.terrainGrid = PropertyIconGrid(self.terrainTypes, cols=5)
        terrainLayout.addWidget(self.terrainGrid)
        mainLayout.addWidget(terrainGroup)

        mainLayout.addStretch(1)
        scroll.setWidget(content)

        outerLayout = QtWidgets.QVBoxLayout(self)
        outerLayout.setContentsMargins(0, 0, 0, 0)
        outerLayout.addWidget(scroll)

        self.swapParams(0)
        self.coreGrid.currentIndexChanged.connect(self.suggestCollision)
        self.params1Grid.currentIndexChanged.connect(self.suggestCollision)
        for grid in (self.coreGrid, self.params1Grid, self.params2Grid, self.collisionGrid, self.terrainGrid):
            grid.currentIndexChanged.connect(self.updateSummary)
        self.updateSummary()

    def suggestCollision(self, *args):
        """
        Picks the collision some core types need to work (and to show right on the tiles),
        when a core type or parameter is clicked: spikes and conveyor belts are Solid, the
        other damage tiles (icicles, lava, poison...) and cave entrances have No Solidity,
        and slopes and partial blocks need to be solid where they're walked on or hit.
        """
        core = self.coreGrid.currentIndex()
        param = self.params1Grid.currentIndex()
        solidity = self._COLLISIONS[self.collisionGrid.currentIndex()][0]
        if core == 15:                                  # Damage Tile
            self.collisionGrid.setCurrentIndex(1 if param in (3, 4, 5, 6) else 0)
        elif core == 19:                                # Cave Entrance: walked through
            self.collisionGrid.setCurrentIndex(0)
        elif core == 17 and solidity == 0:              # Conveyor Belt: stood on
            self.collisionGrid.setCurrentIndex(1)
        elif core == 11 and solidity in (0, 3) or core == 12 and solidity in (0, 2) or core == 9 and solidity == 0:
            self.collisionGrid.setCurrentIndex(1)       # Solid

    def updateSummary(self, *args):
        """Shows the picked properties in words."""
        core = self.coreGrid.currentIndex()
        text = self.coreTypes[core][0]
        for items, grid in ((self.ParameterList[core], self.params1Grid),
                            (self.ParameterList2[core], self.params2Grid)):
            if items is not None and grid.currentIndex() < len(items):
                text += ' (%s)' % items[grid.currentIndex()][0]
        text += ' • %s • %s' % (self.collsTypes[self.collisionGrid.currentIndex()][0],
                                self.terrainTypes[self.terrainGrid.currentIndex()][0])
        self.summaryLabel.setText('<b>Painting:</b> ' + text)

    def swapParams(self, index=None):
        if index is None:
            index = self.coreGrid.currentIndex()
        if index < 0 or index >= len(self.ParameterList):
            return

        items1 = self.ParameterList[index]
        if items1 is not None:
            self.params1Grid.populate(items1)
            self.params1Group.setVisible(True)
        else:
            self.params1Group.setVisible(False)

        items2 = self.ParameterList2[index]
        if items2 is not None:
            self.params2Grid.populate(items2)
            self.params2Group.setVisible(True)
        else:
            self.params2Group.setVisible(False)

    # The Collision choices are a solidity, with sliding (5, 6) or staircase (7, 8) for some
    _COLLISIONS = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (1, 1), (2, 1), (1, 2), (2, 2)]

    def applyTo(self, tile):
        """Gives a tile the properties picked here."""
        core = self.coreGrid.currentIndex()
        tile.coreType = core
        tile.params = self.params1Grid.currentIndex() if self.ParameterList[core] is not None else 0
        tile.params2 = self.params2Grid.currentIndex() if self.ParameterList2[core] is not None else 0
        tile.solidity, tile.slide = self._COLLISIONS[self.collisionGrid.currentIndex()]
        tile.terrain = self.terrainGrid.currentIndex()

    def loadFrom(self, tile):
        """Picks a tile's properties here (the closest choice, for values with none)."""
        core = tile.coreType if tile.coreType < len(self.coreTypes) else 0
        self.coreGrid.setCurrentIndex(core)
        self.swapParams(core)
        self.params1Grid.setCurrentIndex(tile.params)
        self.params2Grid.setCurrentIndex(tile.params2)
        collision = (tile.solidity, tile.slide)
        if collision not in self._COLLISIONS:
            collision = (tile.solidity, 0)
        self.collisionGrid.setCurrentIndex(self._COLLISIONS.index(collision) if collision in self._COLLISIONS else 0)
        self.terrainGrid.setCurrentIndex(tile.terrain if tile.terrain < len(self.terrainTypes) else 0)
        self.updateSummary()



#############################################################################################
######################### InfoBox Custom Widget to display info to ##########################


class InfoBox(QtWidgets.QWidget):
    def __init__(self, editor=None, parent=None):
        super(InfoBox, self).__init__(parent)
        self.editor = editor

        # InfoBox
        superLayout = QtWidgets.QGridLayout()
        infoLayout = QtWidgets.QFormLayout()

        self.imageBox = QtWidgets.QGroupBox()
        imageLayout = QtWidgets.QHBoxLayout()

        pix = QtGui.QPixmap(24, 24)
        pix.fill(Qt.transparent)

        self.coreImage = QtWidgets.QLabel()
        self.coreImage.setPixmap(pix)
        self.terrainImage = QtWidgets.QLabel()
        self.terrainImage.setPixmap(pix)
        self.parameterImage = QtWidgets.QLabel()
        self.parameterImage.setPixmap(pix)


        self.collisionOverlay = QtWidgets.QCheckBox('Overlay Collision')
        self.collisionOverlay.clicked.connect(InfoBox.updateCollision)


        self.coreInfo = QtWidgets.QLabel()
        self.propertyInfo = QtWidgets.QLabel('             \n\n\n\n\n')
        self.terrainInfo = QtWidgets.QLabel()
        self.paramInfo = QtWidgets.QLabel()

        Font = self.font()
        Font.setPointSize(9)

        self.coreInfo.setFont(Font)
        self.propertyInfo.setFont(Font)
        self.terrainInfo.setFont(Font)
        self.paramInfo.setFont(Font)


        self.LabelB = QtWidgets.QLabel('Properties:')
        self.LabelB.setFont(Font)

        self.hexdata = QtWidgets.QLabel('Hex Data: 0000 00 00\n0 0 00')
        self.hexdata.setFont(Font)


        coreLayout = QtWidgets.QVBoxLayout()
        terrLayout = QtWidgets.QVBoxLayout()
        paramLayout = QtWidgets.QVBoxLayout()

        coreLayout.setGeometry(QtCore.QRect(0,0,40,40))
        terrLayout.setGeometry(QtCore.QRect(0,0,40,40))
        paramLayout.setGeometry(QtCore.QRect(0,0,40,40))


        label = QtWidgets.QLabel('Core')
        label.setFont(Font)
        coreLayout.addWidget(label, 0, Qt.AlignCenter)

        label = QtWidgets.QLabel('Terrain')
        label.setFont(Font)
        terrLayout.addWidget(label, 0, Qt.AlignCenter)

        label = QtWidgets.QLabel('Parameters')
        label.setFont(Font)
        paramLayout.addWidget(label, 0, Qt.AlignCenter)

        coreLayout.addWidget(self.coreImage, 0, Qt.AlignCenter)
        terrLayout.addWidget(self.terrainImage, 0, Qt.AlignCenter)
        paramLayout.addWidget(self.parameterImage, 0, Qt.AlignCenter)

        coreLayout.addWidget(self.coreInfo, 0, Qt.AlignCenter)
        terrLayout.addWidget(self.terrainInfo, 0, Qt.AlignCenter)
        paramLayout.addWidget(self.paramInfo, 0, Qt.AlignCenter)

        imageLayout.setContentsMargins(0,4,4,4)
        imageLayout.addLayout(coreLayout)
        imageLayout.addLayout(terrLayout)
        imageLayout.addLayout(paramLayout)

        self.imageBox.setLayout(imageLayout)


        superLayout.addWidget(self.imageBox, 0, 0)
        superLayout.addWidget(self.collisionOverlay, 1, 0)
        infoLayout.addRow(self.LabelB, self.propertyInfo)
        infoLayout.addRow(self.hexdata)
        superLayout.addLayout(infoLayout, 0, 1, 2, 1)
        self.setLayout(superLayout)

    @staticmethod
    def updateCollision():
        window.setuptile()

        window.tileWidget.setObject(window.objectList.currentIndex())
        window.tileWidget.update()




#############################################################################################
##################### Object List Widget and Model Setup with Painter #######################


class objectList(QtWidgets.QListView):

    def __init__(self, editor=None, parent=None):
        super(objectList, self).__init__(parent)
        self.editor = editor


        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setIconSize(QtCore.QSize(96,96))
        self.setGridSize(QtCore.QSize(114,114))
        self.setMovement(QtWidgets.QListView.Static)
        self.setBackgroundRole(QtGui.QPalette.BrightText)
        self.setWrapping(False)
        self.setMinimumHeight(140)
        self.setMaximumHeight(140)

        self.noneIdx = self.currentIndex()

    def clearCurrentIndex(self):
        self.setCurrentIndex(self.noneIdx)



def SetupObjectModel(self, editor, objects, tiles):
    self.clear()

    count = 0
    for object in objects:
        tex = QtGui.QPixmap(object.width * 24, object.height * 24)
        tex.fill(Qt.transparent)
        painter = QtGui.QPainter(tex)

        Xoffset = 0
        Yoffset = 0

        for i in range(len(object.tiles)):
            for tile in object.tiles[i]:
                if (editor.slot == 0) or ((tile[2] & 3) != 0):
                    image = editor.tileset.overrides[tile[1]] if editor.slot == 0 and editor.overrides else None
                    if not image:
                        image = tiles[tile[1]].image
                    painter.drawPixmap(Xoffset, Yoffset, image.scaledToWidth(24, Qt.SmoothTransformation))
                Xoffset += 24
            Xoffset = 0
            Yoffset += 24

        painter.end()

        item = QtGui.QStandardItem(QtGui.QIcon(tex), 'Object {0}'.format(count))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.appendRow(item)

        count += 1


#############################################################################################
######################## List Widget with custom painter/MouseEvent #########################


class displayWidget(QtWidgets.QListView):

    mouseMoved = QtCore.pyqtSignal(int, int)

    _tileClipboard = None
    _propClipboard = None

    def __init__(self, editor=None, parent=None):
        super(displayWidget, self).__init__(parent)
        self.editor = editor

        self.setMinimumWidth(426)
        self.setMaximumWidth(426)
        self.setMinimumHeight(404)
        self.setDragEnabled(True)
        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setIconSize(QtCore.QSize(24,24))
        self.setGridSize(QtCore.QSize(25,25))
        self.setMovement(QtWidgets.QListView.Static)
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(True)
        self.setResizeMode(QtWidgets.QListView.Adjust)
        self.setUniformItemSizes(True)
        self.setBackgroundRole(QtGui.QPalette.BrightText)
        self.setMouseTracking(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

        self.setItemDelegate(self.TileItemDelegate(self.editor))


    def update(self, *args):
        """update() with no arguments repaints the tiles too (they're drawn in the viewport)."""
        if args:
            return super().update(*args)
        super().update()
        self.viewport().update()

    def _painting(self):
        """True while the Properties tab is open: clicks then paint properties onto tiles."""
        return self.editor is not None and self.editor.sideTabWidget.currentIndex() == 0

    def mousePressEvent(self, event):
        if not self._painting():
            return super().mousePressEvent(event)
        row = self.indexAt(event.pos()).row()
        pick = event.button() == Qt.MidButton or (
            event.button() == Qt.LeftButton and event.modifiers() & Qt.AltModifier)
        if pick:
            if row >= 0:
                self.editor.pickProperties(row)
        elif event.button() == Qt.LeftButton:
            self.editor.beginPaintStroke()
            self.editor.paintTile(row)
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.editor is not None and self.editor._stroke is not None and event.button() == Qt.LeftButton:
            self.editor.endPaintStroke()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        QtWidgets.QWidget.mouseMoveEvent(self, event)

        # Dragging over tiles paints them all
        if self.editor is not None and self.editor._stroke is not None and event.buttons() & Qt.LeftButton:
            self.editor.paintTile(self.indexAt(event.pos()).row())
            return
        self.mouseMoved.emit(event.x(), event.y())

    def contextMenuEvent(self, event):
        index = self.indexAt(event.pos())
        tileIdx = index.row()
        if tileIdx < 0 or tileIdx >= len(self.editor.tileset.tiles):
            return
        clip = QtWidgets.QApplication.clipboard()
        hasImage = not clip.pixmap().isNull() or not clip.image().isNull()
        hasProps = (displayWidget._propClipboard is not None) or self._clipHasProps()
        hasTile  = displayWidget._tileClipboard is not None
        menu = QtWidgets.QMenu(self)
        menu.addAction("Copy image to clipboard",        lambda: self._copyImage(tileIdx))
        act = menu.addAction("Paste image", lambda: self._pasteImage(tileIdx))
        act.setEnabled(hasImage)
        menu.addAction("Import image...",  lambda: self._replaceImage(tileIdx))
        menu.addAction("Export image...",  lambda: self._saveImage(tileIdx))
        menu.addSeparator()
        menu.addAction("Pick these properties", lambda: self.editor.pickProperties(tileIdx))
        menu.addAction("Copy properties to clipboard",   lambda: self._copyProperties(tileIdx))
        act = menu.addAction("Paste properties", lambda: self._pasteProperties(tileIdx))
        act.setEnabled(hasProps)
        menu.addSeparator()
        menu.addAction("Copy tile",         lambda: self._copyTile(tileIdx))
        act = menu.addAction("Paste tile",  lambda: self._pasteTile(tileIdx))
        act.setEnabled(hasTile)
        menu.exec_(event.globalPos())

    def _clipHasProps(self):
        try:
            data = json.loads(QtWidgets.QApplication.clipboard().text())
            return bool(data.get('__pyamoto_props__'))
        except Exception:
            return False

    def _clipPixmap(self):
        clip = QtWidgets.QApplication.clipboard()
        px = clip.pixmap()
        if not px.isNull():
            return px
        img = clip.image()
        if not img.isNull():
            return QtGui.QPixmap.fromImage(img)
        return None

    def _tileSize(self):
        tiles = self.editor.tileset.tiles
        if tiles:
            img = tiles[0].image
            return img.width(), img.height()
        return 60, 60

    def _copyImage(self, idx):
        tile = self.editor.tileset.tiles[idx]
        QtWidgets.QApplication.clipboard().setPixmap(tile.image)

    def _pasteImage(self, idx):
        px = self._clipPixmap()
        if px is None or px.isNull():
            return
        w, h = self._tileSize()
        tile = self.editor.tileset.tiles[idx]
        tile.image = px.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation).copy(0, 0, w, h)
        self.editor.setuptile()
        self.editor.setDirty()

    def _replaceImage(self, idx):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Open Image', '', 'Images (*.png *.jpg *.bmp *.gif *.tga)')
        if not path:
            return
        px = QtGui.QPixmap(path)
        if px.isNull():
            return
        w, h = self._tileSize()
        tile = self.editor.tileset.tiles[idx]
        tile.image = px.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation).copy(0, 0, w, h)
        self.editor.setuptile()
        self.editor.setDirty()

    def _saveImage(self, idx):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Save Image As', 'tile.png', 'PNG Images (*.png)')
        if path:
            self.editor.tileset.tiles[idx].image.save(path)

    def _copyProperties(self, idx):
        tile = self.editor.tileset.tiles[idx]
        col = tile.getCollision()
        displayWidget._propClipboard = col
        QtWidgets.QApplication.clipboard().setText(json.dumps({
            '__pyamoto_props__': True, 'collision': col}))

    def _pasteProperties(self, idx):
        col = None
        if displayWidget._propClipboard is not None:
            col = displayWidget._propClipboard
        else:
            try:
                data = json.loads(QtWidgets.QApplication.clipboard().text())
                if data.get('__pyamoto_props__'):
                    col = data['collision']
            except Exception:
                pass
        if col is None:
            return
        tile = self.editor.tileset.tiles[idx]
        tile.setCollision(col)
        self.editor.updateInfo(0, 0)
        self.editor.tileDisplay.update()
        self.editor.setDirty()

    def _copyTile(self, idx):
        tile = self.editor.tileset.tiles[idx]
        displayWidget._tileClipboard = {
            'image':     tile.image.copy(),
            'normalmap': tile.normalmap.copy(),
            'collision': tile.getCollision(),
        }
        QtWidgets.QApplication.clipboard().setPixmap(tile.image)

    def _pasteTile(self, idx):
        clip = displayWidget._tileClipboard
        if clip is None:
            return
        tile = self.editor.tileset.tiles[idx]
        tile.image     = clip['image'].copy()
        tile.normalmap = clip['normalmap'].copy()
        tile.setCollision(clip['collision'])
        self.editor.setuptile()
        self.editor.updateInfo(0, 0)
        self.editor.setDirty()


    class TileItemDelegate(QtWidgets.QAbstractItemDelegate):
        """Handles tiles and their rendering"""

        def __init__(self, editor):
            """Initialises the delegate"""
            QtWidgets.QAbstractItemDelegate.__init__(self)
            self.editor = editor

        def paint(self, painter, option, index):
            """Paints an object"""

            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
            p = index.model().data(index, Qt.DecorationRole)
            painter.drawPixmap(option.rect.x(), option.rect.y(), p.pixmap(24,24))

            x = option.rect.x()
            y = option.rect.y()


            # Collision Overlays
            if index.row() >= len(self.editor.tileset.tiles): return
            curTile = self.editor.tileset.tiles[index.row()]

            if self.editor.showCollisionBtn.isChecked():
                # Dimmed a little, with bright outlined shapes, so the collision shows on
                # light and dark tiles alike
                painter.fillRect(option.rect, QtGui.QColor(0, 0, 0, 70))
                painter.save()
                updateCollisionOverlay(curTile, x, y, 24, painter,
                                       defaultColor=QtGui.QColor(255, 120, 40, 150),
                                       outline=QtGui.QColor(255, 255, 255, 200))
                painter.restore()


            # Highlight stuff.
            colour = QtGui.QColor(option.palette.highlight())
            colour.setAlpha(80)

            if option.state & QtWidgets.QStyle.State_Selected:
                painter.fillRect(option.rect, colour)


        def sizeHint(self, option, index):
            """Returns the size for the object"""
            return QtCore.QSize(24, 24)



#############################################################################################
############################ Tile widget for drag n'drop Objects ############################


class RepeatXModifiers(QtWidgets.QWidget):
    def __init__(self, editor=None, parent=None):
        super(RepeatXModifiers, self).__init__(parent)
        self.editor = editor

        self.setVisible(False)

        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0,0,0,0)

        self.spinboxes = []
        self.buttons = []

        self.updating = False


    def update(self):
        index = self.editor.objectList.currentIndex().row()
        if index < 0 or index >= len(self.editor.tileset.objects):
            return

        object = self.editor.tileset.objects[index]
        if not object.repeatX:
            return

        self.updating = True

        assert len(self.spinboxes) == len(self.buttons)

        height = object.height
        numRows = len(self.spinboxes)

        if numRows < height:
            for i in range(numRows, height):
                layout = QtWidgets.QHBoxLayout()
                layout.setSpacing(0)
                layout.setContentsMargins(0,0,0,0)

                spinbox1 = QtWidgets.QSpinBox()
                spinbox1.setFixedSize(32, 24)
                spinbox1.valueChanged.connect(lambda val, i=i: self.startValChanged(val, i))
                layout.addWidget(spinbox1)

                spinbox2 = QtWidgets.QSpinBox()
                spinbox2.setFixedSize(32, 24)
                spinbox2.valueChanged.connect(lambda val, i=i: self.endValChanged(val, i))
                layout.addWidget(spinbox2)

                button1 = QtWidgets.QPushButton('+')
                button1.setFixedSize(24, 24)
                button1.released.connect(lambda i=i: self.addTile(i))
                layout.addWidget(button1)

                button2 = QtWidgets.QPushButton('-')
                button2.setFixedSize(24, 24)
                button2.released.connect(lambda i=i: self.removeTile(i))
                layout.addWidget(button2)

                self.layout.addLayout(layout)
                self.spinboxes.append((spinbox1, spinbox2))
                self.buttons.append((button1, button2))

        elif height < numRows:
            for i in reversed(range(height, numRows)):
                layout = self.layout.itemAt(i).layout()
                self.layout.removeItem(layout)

                spinbox1, spinbox2 = self.spinboxes[i]
                layout.removeWidget(spinbox1)
                layout.removeWidget(spinbox2)

                spinbox1.setParent(None)
                spinbox2.setParent(None)

                del self.spinboxes[i]

                button1, button2 = self.buttons[i]
                layout.removeWidget(button1)
                layout.removeWidget(button2)

                button1.setParent(None)
                button2.setParent(None)

                del self.buttons[i]

        for y in range(height):
            spinbox1, spinbox2 = self.spinboxes[y]

            spinbox1.setRange(0, object.repeatX[y][1]-1)
            spinbox2.setRange(object.repeatX[y][0]+1, len(object.tiles[y]))

            spinbox1.setValue(object.repeatX[y][0])
            spinbox2.setValue(object.repeatX[y][1])

        self.updating = False
        self.setFixedHeight(height * 24)


    def startValChanged(self, val, y):
        if self.updating:
            return

        index = self.editor.objectList.currentIndex().row()
        if index < 0 or index >= len(self.editor.tileset.objects):
            return

        object = self.editor.tileset.objects[index]
        object.repeatX[y][0] = val

        for x in range(len(object.tiles[y])):
            if x >= val and x < object.repeatX[y][1]:
                object.tiles[y][x] = (object.tiles[y][x][0] | 1, object.tiles[y][x][1], object.tiles[y][x][2])

            else:
                object.tiles[y][x] = (object.tiles[y][x][0] & ~1, object.tiles[y][x][1], object.tiles[y][x][2])

        spinbox1, spinbox2 = self.spinboxes[y]
        spinbox1.setRange(0, object.repeatX[y][1]-1)
        spinbox2.setRange(val+1, len(object.tiles[y]))

        self.editor.tileWidget.tiles.update()
        self.editor.setDirty()


    def endValChanged(self, val, y):
        if self.updating:
            return

        index = self.editor.objectList.currentIndex().row()
        if index < 0 or index >= len(self.editor.tileset.objects):
            return

        object = self.editor.tileset.objects[index]
        object.repeatX[y][1] = val

        for x in range(len(object.tiles[y])):
            if x >= object.repeatX[y][0] and x < val:
                object.tiles[y][x] = (object.tiles[y][x][0] | 1, object.tiles[y][x][1], object.tiles[y][x][2])

            else:
                object.tiles[y][x] = (object.tiles[y][x][0] & ~1, object.tiles[y][x][1], object.tiles[y][x][2])

        spinbox1, spinbox2 = self.spinboxes[y]
        spinbox1.setRange(0, val-1)
        spinbox2.setRange(object.repeatX[y][0]+1, len(object.tiles[y]))

        self.editor.tileWidget.tiles.update()
        self.editor.setDirty()


    def addTile(self, y):
        if self.updating:
            return

        index = self.editor.objectList.currentIndex().row()
        if index < 0 or index >= len(self.editor.tileset.objects):
            return

        pix = QtGui.QPixmap(24,24)
        pix.fill(QtGui.QColor(0,0,0,0))

        self.editor.tileWidget.tiles.tiles[y].append(pix)

        object = self.editor.tileset.objects[index]
        if object.repeatY and y >= object.repeatY[0] and y < object.repeatY[1]:
            object.tiles[y].append((2, 0, 0))

        else:
            object.tiles[y].append((0, 0, 0))

        object.width = max(len(object.tiles[y]), object.width)

        self.update()

        self.editor.tileWidget.tiles.size[0] = object.width
        self.editor.tileWidget.tiles.setMinimumSize(self.editor.tileWidget.tiles.size[0]*24 + 12, self.editor.tileWidget.tiles.size[1]*24 + 12)

        self.editor.tileWidget.tiles.update()
        self.editor.tileWidget.tiles.updateList()

        self.editor.tileWidget._updateBehaviorAvailability()
        self.editor.setDirty()


    def removeTile(self, y):
        if self.updating:
            return

        if self.editor.tileWidget.tiles.size[0] == 1:
            return

        index = self.editor.objectList.currentIndex().row()
        if index < 0 or index >= len(self.editor.tileset.objects):
            return

        object = self.editor.tileset.objects[index]

        row = self.editor.tileWidget.tiles.tiles[y]
        if len(row) > 1:
            row.pop()
        else:
            return

        row = object.tiles[y]
        if len(row) > 1:
            row.pop()
        else:
            return

        start, end = object.repeatX[y]
        end = min(end, len(row))
        start = min(start, end - 1)

        if [start, end] != object.repeatX[y]:
            object.repeatX[y] = [start, end]
            for x in range(len(row)):
                if x >= start and x < end:
                    row[x] = (row[x][0] | 1, row[x][1], row[x][2])

                else:
                    row[x] = (row[x][0] & ~1, row[x][1], row[x][2])

        object.width = max(len(row) for row in object.tiles)

        self.update()

        self.editor.tileWidget.tiles.size[0] = object.width
        self.editor.tileWidget.tiles.setMinimumSize(self.editor.tileWidget.tiles.size[0]*24 + 12, self.editor.tileWidget.tiles.size[1]*24 + 12)

        self.editor.tileWidget.tiles.update()
        self.editor.tileWidget.tiles.updateList()

        self.editor.tileWidget._updateBehaviorAvailability()
        self.editor.setDirty()


class RepeatYModifiers(QtWidgets.QWidget):
    def __init__(self, editor=None, parent=None):
        super(RepeatYModifiers, self).__init__(parent)
        self.editor = editor

        self.setVisible(False)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0,0,0,0)

        spinbox1 = QtWidgets.QSpinBox()
        spinbox1.setFixedSize(32, 24)
        spinbox1.valueChanged.connect(self.startValChanged)
        layout.addWidget(spinbox1)

        spinbox2 = QtWidgets.QSpinBox()
        spinbox2.setFixedSize(32, 24)
        spinbox2.valueChanged.connect(self.endValChanged)
        layout.addWidget(spinbox2)

        self.spinboxes = (spinbox1, spinbox2)
        self.updating = False

        self.setFixedWidth(64)


    def update(self):
        index = self.editor.objectList.currentIndex().row()
        if index < 0 or index >= len(self.editor.tileset.objects):
            return

        object = self.editor.tileset.objects[index]
        if not object.repeatY:
            return

        self.updating = True

        spinbox1, spinbox2 = self.spinboxes
        spinbox1.setRange(0, object.repeatY[1]-1)
        spinbox2.setRange(object.repeatY[0]+1, object.height)

        spinbox1.setValue(object.repeatY[0])
        spinbox2.setValue(object.repeatY[1])

        self.updating = False


    def startValChanged(self, val):
        if self.updating:
            return

        index = self.editor.objectList.currentIndex().row()
        if index < 0 or index >= len(self.editor.tileset.objects):
            return

        object = self.editor.tileset.objects[index]
        object.createRepetitionY(val, object.repeatY[1])

        spinbox1, spinbox2 = self.spinboxes
        spinbox1.setRange(0, object.repeatY[1]-1)
        spinbox2.setRange(object.repeatY[0]+1, object.height)

        self.editor.tileWidget.tiles.update()
        self.editor.setDirty()


    def endValChanged(self, val):
        if self.updating:
            return

        index = self.editor.objectList.currentIndex().row()
        if index < 0 or index >= len(self.editor.tileset.objects):
            return

        object = self.editor.tileset.objects[index]
        object.createRepetitionY(object.repeatY[0], val)

        spinbox1, spinbox2 = self.spinboxes
        spinbox1.setRange(0, object.repeatY[1]-1)
        spinbox2.setRange(object.repeatY[0]+1, object.height)

        self.editor.tileWidget.tiles.update()
        self.editor.setDirty()


class SlopeLineModifier(QtWidgets.QWidget):
    def __init__(self, editor=None, parent=None):
        super(SlopeLineModifier, self).__init__(parent)
        self.editor = editor

        self.setVisible(False)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0,0,0,0)

        self.spinbox = QtWidgets.QSpinBox()
        self.spinbox.setFixedSize(32, 24)
        self.spinbox.valueChanged.connect(self.valChanged)
        layout.addWidget(self.spinbox)

        self.updating = False

        self.setFixedWidth(32)


    def update(self):
        index = self.editor.objectList.currentIndex().row()
        if index < 0 or index >= len(self.editor.tileset.objects):
            return

        object = self.editor.tileset.objects[index]
        if object.upperslope[0] == 0:
            return

        self.updating = True

        self.spinbox.setRange(1, object.height)
        self.spinbox.setValue(object.upperslope[1])

        self.updating = False


    def valChanged(self, val):
        if self.updating:
            return

        index = self.editor.objectList.currentIndex().row()
        if index < 0 or index >= len(self.editor.tileset.objects):
            return

        object = self.editor.tileset.objects[index]
        if object.height == 1:
            object.upperslope[1] = 1
            object.lowerslope = [0, 0]

        else:
            object.upperslope[1] = val
            object.lowerslope = [0x84, object.height - val]

        tiles = self.editor.tileWidget.tiles

        if object.upperslope[0] & 2:
            tiles.slope = -object.upperslope[1]

        else:
            tiles.slope = object.upperslope[1]

        tiles.update()
        self.editor.setDirty()


class tileOverlord(QtWidgets.QWidget):

    _SLOPE_TO_IDX = [4, 5, 6, 7]
    _IDX_TO_SLOPE = {4: 0, 5: 1, 6: 2, 7: 3}

    def __init__(self, editor=None, parent=None):
        super(tileOverlord, self).__init__(parent)
        self.editor = editor

        # Setup Widgets
        self.tiles = tileWidget(editor=editor)

        self.addObject = QtWidgets.QPushButton('Add')
        self.removeObject = QtWidgets.QPushButton('Remove')

        self.placeNull = QtWidgets.QPushButton('Write null tile')
        self.placeNull.setCheckable(True)
        self.placeNull.setChecked(editor.tileset.placeNullChecked if editor else False)
        self.placeNull.setToolTip(
            '<b>Write null tile:</b><br><br>'
            'A null tile is used for empty spaces within large tileset objects. '
            'When an object is placed, a null tile will leave an empty space '
            'without deleting the tile already beneath it.'
        )

        self.addRow = QtWidgets.QPushButton('+')
        self.removeRow = QtWidgets.QPushButton('-')

        self.addColumn = QtWidgets.QPushButton('+')
        self.removeColumn = QtWidgets.QPushButton('-')

        self.behaviorCombo = QtWidgets.QComboBox()
        self.behaviorCombo.addItems(['Default', 'Randomization', 'Repetition', 'Slope'])
        self.behaviorCombo.setItemData(0, 'The object tiles are placed as-is with no repetition or special behavior.', Qt.ToolTipRole)
        self.behaviorCombo.setItemData(1, 'Only available for 1×1 objects. The game randomly picks from a pool of tiles when placing this object.', Qt.ToolTipRole)
        self.behaviorCombo.setItemData(2, 'A section of the object is repeated to fill the placed area. Use Repeat X, Repeat Y, or both.', Qt.ToolTipRole)
        self.behaviorCombo.setItemData(3, 'The object forms a slope. Choose the slope direction below.', Qt.ToolTipRole)

        self.behaviorStack = QtWidgets.QStackedWidget()
        self.behaviorStack.addWidget(QtWidgets.QWidget())  # Panel 0: No Repetition

        randPanel = QtWidgets.QWidget()
        randPanelLyt = QtWidgets.QGridLayout(randPanel)
        randPanelLyt.setContentsMargins(0, 0, 0, 0)
        self.randX = QtWidgets.QCheckBox('Randomize Horizontally')
        self.randY = QtWidgets.QCheckBox('Randomize Vertically')
        self.randX.setToolTip('<b>Randomize Horizontally:</b><br><br>'
            'Check this if you want to use randomized replacements for '
            'this tile, in the <u>horizontal</u> direction. Examples: '
            'floor tiles and ceiling tiles.')
        self.randY.setToolTip('<b>Randomize Vertically:</b><br><br>'
            'Check this if you want to use randomized replacements for '
            'this tile, in the <u>vertical</u> direction. Example: '
            'edge tiles.')
        self.randLenLbl = QtWidgets.QLabel('Total Randomizable Tiles:')
        self.randLen = QtWidgets.QSpinBox()
        self.randLen.setRange(1, 15)
        self.randLen.setToolTip('<b>Total Randomizable Tiles:</b><br><br>'
            'This specifies the total number of tiles the game may '
            'use for randomized replacements of this tile. This '
            'will be the tile itself, and <i>(n - 1)</i> tiles after it, '
            'where <i>n</i> is the number in this box. Tiles "after" this one '
            'are tiles to the right of it in the tileset image, wrapping '
            'to the next line if the right edge of the image is reached.')
        randPanelLyt.addWidget(self.randX,      0, 0)
        randPanelLyt.addWidget(self.randY,      1, 0)
        randPanelLyt.addWidget(self.randLenLbl, 0, 1)
        randPanelLyt.addWidget(self.randLen,    1, 1)
        self.behaviorStack.addWidget(randPanel)  # Panel 1: Randomization

        repPanel = QtWidgets.QWidget()
        repLyt = QtWidgets.QVBoxLayout(repPanel)
        repLyt.setContentsMargins(0, 0, 0, 0)
        repLyt.setSpacing(2)
        self.repXCheck = QtWidgets.QCheckBox('Repeat X')
        self.repYCheck = QtWidgets.QCheckBox('Repeat Y')
        repLyt.addWidget(self.repXCheck)
        repLyt.addWidget(self.repYCheck)
        repLyt.addStretch(1)
        self.behaviorStack.addWidget(repPanel)  # Panel 2: Repetition

        slopePanel = QtWidgets.QWidget()
        slopePanelLyt = QtWidgets.QVBoxLayout(slopePanel)
        slopePanelLyt.setContentsMargins(0, 0, 0, 0)

        path = os.path.join(globals.miyamoto_path, 'yaz0data', 'Icons', '')
        slopeItems = [
            ['Upward slope',        QtGui.QIcon(path + 'Slope/steepslopeleft.png'), 'Floor rises going left to right'],
            ['Downward slope',      QtGui.QIcon(path + 'Slope/steepsloperight.png'), 'Floor falls going left to right'],
            ['Upward rev. slope',   QtGui.QIcon(path + 'Slope/Rsteepslopeleft.png'), 'Ceiling rises going left to right'],
            ['Downward rev. slope', QtGui.QIcon(path + 'Slope/Rsteepsloperight.png'), 'Ceiling falls going left to right'],
        ]
        self.slopeSelector = PropertyIconGrid(slopeItems, cols=4)
        slopePanelLyt.addWidget(self.slopeSelector)
        self.behaviorStack.addWidget(slopePanel)  # Panel 3: Slope


        # Connections
        self.addObject.released.connect(self.addObj)
        self.removeObject.released.connect(self.removeObj)
        self.placeNull.toggled.connect(self.doPlaceNull)
        self.addRow.released.connect(self.addRowHandler)
        self.removeRow.released.connect(self.removeRowHandler)
        self.addColumn.released.connect(self.addColumnHandler)
        self.removeColumn.released.connect(self.removeColumnHandler)

        self.behaviorCombo.currentIndexChanged.connect(self.setBehavior)
        self.randX.toggled.connect(self.changeRandX)
        self.randY.toggled.connect(self.changeRandY)
        self.randLen.valueChanged.connect(self.changeRandLen)
        self.repXCheck.toggled.connect(self.changeRepX)
        self.repYCheck.toggled.connect(self.changeRepY)
        self.slopeSelector.currentIndexChanged.connect(self.changeSlopeType)


        # Layout
        self.repeatX = RepeatXModifiers(editor=self.editor)
        repeatXLyt = QtWidgets.QVBoxLayout()
        repeatXLyt.addWidget(self.repeatX)

        self.repeatY = RepeatYModifiers(editor=self.editor)
        repeatYLyt = QtWidgets.QHBoxLayout()
        repeatYLyt.addWidget(self.repeatY)

        self.slopeLine = SlopeLineModifier(editor=self.editor)
        slopeLineLyt = QtWidgets.QVBoxLayout()
        slopeLineLyt.addWidget(self.slopeLine)

        tilesLyt = QtWidgets.QGridLayout()
        tilesLyt.setSpacing(0)
        tilesLyt.setContentsMargins(0,0,0,0)

        tilesLyt.addWidget(self.tiles, 0, 0, 3, 4)
        tilesLyt.addLayout(repeatXLyt, 0, 4, 3, 1)
        tilesLyt.addLayout(repeatYLyt, 3, 0, 1, 4)
        tilesLyt.addLayout(slopeLineLyt, 0, 5, 3, 1)

        topSeparator = QtWidgets.QFrame()
        topSeparator.setFrameShape(QtWidgets.QFrame.HLine)
        topSeparator.setFrameShadow(QtWidgets.QFrame.Sunken)

        self.behaviorSeparator = QtWidgets.QFrame()
        self.behaviorSeparator.setFrameShape(QtWidgets.QFrame.HLine)
        self.behaviorSeparator.setFrameShadow(QtWidgets.QFrame.Sunken)

        layout = QtWidgets.QGridLayout()

        layout.addWidget(QtWidgets.QLabel("Select behavior:"), 0, 0, 1, 3)
        layout.addWidget(self.behaviorCombo, 0, 3, 1, 3)
        layout.addWidget(self.addObject, 0, 6, 1, 1)
        layout.addWidget(self.removeObject, 0, 7, 1, 1)

        layout.addWidget(topSeparator, 1, 0, 1, 8)
        layout.addWidget(self.behaviorStack, 2, 0, 1, 8)
        layout.addWidget(self.behaviorSeparator, 3, 0, 1, 8)

        layout.setRowStretch(4, 1)
        layout.setRowStretch(5, 5)
        layout.setRowStretch(8, 5)

        layout.addLayout(tilesLyt, 5, 1, 4, 6)

        layout.addWidget(self.placeNull, 5, 7, 1, 1)

        layout.addWidget(self.addColumn, 6, 7, 1, 1)
        layout.addWidget(self.removeColumn, 7, 7, 1, 1)
        layout.addWidget(self.addRow, 9, 3, 1, 1)
        layout.addWidget(self.removeRow, 9, 4, 1, 1)

        self.setLayout(layout)

        # Start with editing disabled until an object is explicitly selected
        self._setEditingEnabled(False)




    def _setEditingEnabled(self, enabled):
        for w in (self.tiles, self.placeNull, self.addRow, self.removeRow,
                  self.addColumn, self.removeColumn, self.behaviorCombo,
                  self.repXCheck, self.repYCheck, self.randX, self.randY,
                  self.randLen, self.slopeSelector, self.behaviorStack):
            w.setEnabled(enabled)
        if not enabled:
            self.behaviorStack.setVisible(False)
            self.behaviorSeparator.setVisible(False)

    def addObj(self):
        self.editor.tileset.addObject(new=True)

        pix = QtGui.QPixmap(24, 24)
        pix.fill(Qt.transparent)

        painter = QtGui.QPainter(pix)
        painter.drawPixmap(0, 0, self.editor.tileset.tiles[0].image.scaledToWidth(24, Qt.SmoothTransformation))
        painter.end()
        del painter

        count = len(self.editor.tileset.objects)
        item = QtGui.QStandardItem(QtGui.QIcon(pix), 'Object {0}'.format(count-1))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.editor.objmodel.appendRow(item)
        index = self.editor.objectList.currentIndex()
        self.editor.objectList.setCurrentIndex(index)
        self.setObject(index)

        self.editor.objectList.update()
        self.update()
        self.editor.setDirty()


    def removeObj(self):
        index = self.editor.objectList.currentIndex().row()
        if index < 0 or index >= len(self.editor.tileset.objects):
            return

        self.editor.tileset.removeObject(index)
        self.editor.objmodel.removeRow(index)
        self.tiles.clear()

        SetupObjectModel(self.editor.objmodel, self.editor, self.editor.tileset.objects, self.editor.tileset.tiles)

        self.editor.objectList.update()
        self.update()
        self.editor.setDirty()

        if self.editor.tileset.objects:
            newRow = min(index, len(self.editor.tileset.objects) - 1)
            newIdx = self.editor.objmodel.index(newRow, 0)
            self.editor.objectList.setCurrentIndex(newIdx)
            self.setObject(newIdx)
        else:
            self._setEditingEnabled(False)


    def doPlaceNull(self, checked):
        self.editor.tileset.placeNullChecked = checked


    def setObject(self, index):
        self.tiles.object = index.row()
        if self.tiles.object < 0 or self.tiles.object >= len(self.editor.tileset.objects):
            return

        self._setEditingEnabled(True)
        object = self.editor.tileset.objects[index.row()]

        for w in (self.behaviorCombo, self.repXCheck, self.repYCheck,
                  self.randX, self.randY, self.randLen, self.slopeSelector):
            w.blockSignals(True)

        oldIdx = object.determineTilingMethod()
        if oldIdx > 3:
            mode = 3
        elif object.randX or object.randY:
            mode = 1
        elif oldIdx == 0:
            mode = 0
        else:
            mode = 2

        is1x1 = (object.width, object.height) == (1, 1)
        randItem = self.behaviorCombo.model().item(1)
        if is1x1:
            randItem.setFlags(randItem.flags() | Qt.ItemIsEnabled)
        else:
            randItem.setFlags(randItem.flags() & ~Qt.ItemIsEnabled)
            if mode == 1:
                mode = 0

        self.behaviorCombo.setCurrentIndex(mode)
        self.behaviorStack.setCurrentIndex(mode)

        if mode == 1:
            self.randX.setChecked(object.randX == 1)
            self.randY.setChecked(object.randY == 1)
            self.randLen.setValue(object.randLen)
        elif mode == 2:
            self.repXCheck.setChecked(bool(object.repeatX))
            self.repYCheck.setChecked(bool(object.repeatY))
        elif mode == 3:
            self.slopeSelector.setCurrentIndex(self._IDX_TO_SLOPE.get(oldIdx, 0))

        self.repeatX.setVisible(mode == 2 and bool(object.repeatX))
        self.repeatY.setVisible(mode == 2 and bool(object.repeatY))
        self.slopeLine.setVisible(mode == 3)

        showProps = mode != 0
        self.behaviorStack.setVisible(showProps)
        self.behaviorSeparator.setVisible(showProps)

        for w in (self.behaviorCombo, self.repXCheck, self.repYCheck,
                  self.randX, self.randY, self.randLen, self.slopeSelector):
            w.blockSignals(False)

        self.tiles.setObject(object)


    @QtCore.pyqtSlot(int)
    def setBehavior(self, modeIndex):
        self.behaviorStack.setCurrentIndex(modeIndex)
        showProps = modeIndex != 0
        self.behaviorStack.setVisible(showProps)
        self.behaviorSeparator.setVisible(showProps)
        self.repeatX.setVisible(False)
        self.repeatY.setVisible(False)
        self.slopeLine.setVisible(False)

        idx = self.editor.objectList.currentIndex().row()
        if idx < 0 or idx >= len(self.editor.tileset.objects):
            return

        object = self.editor.tileset.objects[idx]

        if modeIndex in (0, 1):
            if modeIndex == 1:
                self.randX.blockSignals(True)
                self.randX.setChecked(True)
                self.randX.blockSignals(False)
                self.randY.blockSignals(True)
                self.randY.setChecked(True)
                self.randY.blockSignals(False)
                self.randLen.setValue(4)

            object.randX = modeIndex
            object.randY = modeIndex
            object.randLen = 4 if modeIndex == 1 else 0
            object.tilingMethodIdx = 0
            object.clearRepetitionXY()
            object.upperslope = [0, 0]
            object.lowerslope = [0, 0]
            self.tiles.slope = 0
            self.tiles.update()
            self.editor.setDirty()

        elif modeIndex == 2:
            self.repXCheck.blockSignals(True)
            self.repXCheck.setChecked(True)
            self.repXCheck.blockSignals(False)
            self.repYCheck.blockSignals(True)
            self.repYCheck.setChecked(False)
            self.repYCheck.blockSignals(False)
            object.randX = 0
            object.randY = 0
            object.randLen = 0
            object.upperslope = [0, 0]
            object.lowerslope = [0, 0]
            if not object.repeatX:
                object.createRepetitionX()
                self.repeatX.update()
            if object.repeatY:
                object.clearRepetitionY()
            object.tilingMethodIdx = 1
            self.repeatX.setVisible(True)
            self.repeatY.setVisible(False)
            self.tiles.slope = 0
            self.tiles.update()
            self.editor.setDirty()

        elif modeIndex == 3:
            slopeIdx = self.slopeSelector.currentIndex()
            tilingIdx = self._SLOPE_TO_IDX[slopeIdx]
            _upper = {4: 0x90, 5: 0x91, 6: 0x92, 7: 0x93}[tilingIdx]
            object.tilingMethodIdx = tilingIdx
            object.randX = 0
            object.randY = 0
            object.randLen = 0
            object.clearRepetitionXY()
            if object.upperslope[0] != _upper:
                object.upperslope = [_upper, 1]
                object.lowerslope = [0, 0] if object.height == 1 else [0x84, object.height - 1]
            self.tiles.slope = object.upperslope[1] if tilingIdx in (4, 5) else -object.upperslope[1]
            self.slopeLine.setVisible(True)
            self.slopeLine.update()
            self.tiles.update()
            self.editor.setDirty()

    def changeRepX(self, checked):
        if not (checked or self.repYCheck.isChecked()):
            self.repYCheck.setChecked(True)

        idx = self.editor.objectList.currentIndex().row()
        if idx < 0 or idx >= len(self.editor.tileset.objects):
            return
        object = self.editor.tileset.objects[idx]
        if checked:
            if not object.repeatX:
                object.createRepetitionX()
                self.repeatX.update()
            object.upperslope = [0, 0]
            object.lowerslope = [0, 0]
        else:
            object.clearRepetitionX()
        repX, repY = checked, self.repYCheck.isChecked()
        object.tilingMethodIdx = 3 if (repX and repY) else (1 if repX else 2)
        self.repeatX.setVisible(repX)
        self.tiles.slope = 0
        self.tiles.update()
        self.editor.setDirty()

    def changeRepY(self, checked):
        if not (checked or self.repXCheck.isChecked()):
            self.repXCheck.setChecked(True)

        idx = self.editor.objectList.currentIndex().row()
        if idx < 0 or idx >= len(self.editor.tileset.objects):
            return
        object = self.editor.tileset.objects[idx]
        if checked:
            if not object.repeatY:
                object.createRepetitionY(0, object.height)
                self.repeatY.update()
            object.upperslope = [0, 0]
            object.lowerslope = [0, 0]
        else:
            object.clearRepetitionY()
        repX, repY = self.repXCheck.isChecked(), checked
        object.tilingMethodIdx = 3 if (repX and repY) else (1 if repX else 2)
        self.repeatY.setVisible(repY)
        self.tiles.update()
        self.editor.setDirty()

    def changeSlopeType(self, slopeIdx):
        if self.behaviorCombo.currentIndex() != 3:
            return
        idx = self.editor.objectList.currentIndex().row()
        if idx < 0 or idx >= len(self.editor.tileset.objects):
            return
        object = self.editor.tileset.objects[idx]
        tilingIdx = self._SLOPE_TO_IDX[slopeIdx]
        _upper = {4: 0x90, 5: 0x91, 6: 0x92, 7: 0x93}[tilingIdx]
        object.tilingMethodIdx = tilingIdx
        object.clearRepetitionXY()
        if object.upperslope[0] != _upper:
            object.upperslope = [_upper, 1]
            object.lowerslope = [0, 0] if object.height == 1 else [0x84, object.height - 1]
        self.tiles.slope = object.upperslope[1] if tilingIdx in (4, 5) else -object.upperslope[1]
        self.slopeLine.update()
        self.tiles.update()
        self.editor.setDirty()

    def _updateBehaviorAvailability(self):
        is1x1 = self.tiles.size == [1, 1]
        randItem = self.behaviorCombo.model().item(1)
        if is1x1:
            randItem.setFlags(randItem.flags() | Qt.ItemIsEnabled)
        else:
            randItem.setFlags(randItem.flags() & ~Qt.ItemIsEnabled)
            if self.behaviorCombo.currentIndex() == 1:
                self.behaviorCombo.setCurrentIndex(0)

    def addRowHandler(self):
        index = self.editor.objectList.currentIndex()
        self.tiles.object = index.row()

        if self.tiles.object < 0 or self.tiles.object >= len(self.editor.tileset.objects):
            return

        self.tiles.addRow()
        self._updateBehaviorAvailability()
        self.editor.setDirty()


    def removeRowHandler(self):
        index = self.editor.objectList.currentIndex()
        self.tiles.object = index.row()

        if self.tiles.object < 0 or self.tiles.object >= len(self.editor.tileset.objects):
            return

        self.tiles.removeRow()
        self._updateBehaviorAvailability()
        self.editor.setDirty()


    def addColumnHandler(self):
        index = self.editor.objectList.currentIndex()
        self.tiles.object = index.row()

        if self.tiles.object < 0 or self.tiles.object >= len(self.editor.tileset.objects):
            return

        self.tiles.addColumn()
        self._updateBehaviorAvailability()
        self.editor.setDirty()


    def removeColumnHandler(self):
        index = self.editor.objectList.currentIndex()
        self.tiles.object = index.row()

        if self.tiles.object < 0 or self.tiles.object >= len(self.editor.tileset.objects):
            return

        self.tiles.removeColumn()
        self._updateBehaviorAvailability()
        self.editor.setDirty()


    def changeRandX(self, toggled):
        if not (toggled or self.randY.isChecked()):
            self.randY.setChecked(True)

        index = self.editor.objectList.currentIndex()
        self.tiles.object = index.row()

        if self.tiles.object < 0 or self.tiles.object >= len(self.editor.tileset.objects):
            return

        object = self.editor.tileset.objects[self.tiles.object]
        object.randX = 1 if toggled else 0
        self.editor.setDirty()


    def changeRandY(self, toggled):
        if not (toggled or self.randX.isChecked()):
            self.randX.setChecked(True)

        index = self.editor.objectList.currentIndex()
        self.tiles.object = index.row()

        if self.tiles.object < 0 or self.tiles.object >= len(self.editor.tileset.objects):
            return

        object = self.editor.tileset.objects[self.tiles.object]
        object.randY = 1 if toggled else 0
        self.editor.setDirty()


    def changeRandLen(self, val):
        index = self.editor.objectList.currentIndex()
        self.tiles.object = index.row()

        if self.tiles.object < 0 or self.tiles.object >= len(self.editor.tileset.objects):
            return

        object = self.editor.tileset.objects[self.tiles.object]
        object.randLen = val
        self.editor.setDirty()


class tileWidget(QtWidgets.QWidget):

    def __init__(self, editor=None, parent=None):
        super(tileWidget, self).__init__(parent)
        self.editor = editor

        self.tiles = []

        self.size = [1, 1]
        self.setMinimumSize(36, 36)  # (24, 24) + padding

        self.slope = 0

        self.highlightedRect = QtCore.QRect()

        self.setAcceptDrops(True)
        self.object = -1


    def clear(self):
        self.tiles = []
        self.size = [1, 1] # [width, height]

        self.slope = 0
        self.highlightedRect = QtCore.QRect()

        self.update()


    def addColumn(self):
        if self.size[0] >= 24:
            return

        if self.object < 0 or self.object >= len(self.editor.tileset.objects):
            return

        self.size[0] += 1
        self.setMinimumSize(self.size[0]*24 + 12, self.size[1]*24 + 12)

        curObj = self.editor.tileset.objects[self.object]
        curObj.width += 1

        pix = QtGui.QPixmap(24,24)
        pix.fill(QtGui.QColor(0,0,0,0))

        for row in self.tiles:
            row.append(pix)

        if curObj.repeatY:
            for y, row in enumerate(curObj.tiles):
                if y >= curObj.repeatY[0] and y < curObj.repeatY[1]:
                    row.append((2, 0, 0))

                else:
                    row.append((0, 0, 0))

        else:
            for row in curObj.tiles:
                row.append((0, 0, 0))

        self.update()
        self.updateList()

        self.editor.tileWidget.repeatX.update()


    def removeColumn(self):
        if self.size[0] <= 1:
            return

        if self.object < 0 or self.object >= len(self.editor.tileset.objects):
            return

        curObj = self.editor.tileset.objects[self.object]
        self.size[0] -= 1
        self.setMinimumSize(self.size[0]*24 + 12, self.size[1]*24 + 12)

        curObj.width -= 1

        for row in self.tiles:
            if len(row) > 1:
                row.pop()

        for row in curObj.tiles:
            if len(row) > 1:
                row.pop()

        if curObj.repeatX:
            for y, row in enumerate(curObj.tiles):
                start, end = curObj.repeatX[y]
                end = min(end, len(row))
                start = min(start, end - 1)

                if [start, end] != curObj.repeatX[y]:
                    curObj.repeatX[y] = [start, end]
                    for x in range(len(row)):
                        if x >= start and x < end:
                            row[x] = (row[x][0] | 1, row[x][1], row[x][2])

                        else:
                            row[x] = (row[x][0] & ~1, row[x][1], row[x][2])

        self.update()
        self.updateList()

        self.editor.tileWidget.repeatX.update()


    def addRow(self):
        if self.size[1] >= 24:
            return

        if self.object < 0 or self.object >= len(self.editor.tileset.objects):
            return

        curObj = self.editor.tileset.objects[self.object]
        self.size[1] += 1
        self.setMinimumSize(self.size[0]*24 + 12, self.size[1]*24 + 12)

        curObj.height += 1

        pix = QtGui.QPixmap(24,24)
        pix.fill(QtGui.QColor(0,0,0,0))

        self.tiles.append([pix for _ in range(curObj.width)])

        if curObj.repeatX:
            curObj.tiles.append([(1, 0, 0) for _ in range(curObj.width)])
            curObj.repeatX.append([0, curObj.width])

        else:
            curObj.tiles.append([(0, 0, 0) for _ in range(curObj.width)])

        if curObj.upperslope[0] != 0:
            curObj.lowerslope = [0x84, curObj.lowerslope[1] + 1]

        self.update()
        self.updateList()

        self.editor.tileWidget.repeatX.update()
        self.editor.tileWidget.repeatY.update()
        self.editor.tileWidget.slopeLine.update()


    def removeRow(self):
        if self.size[1] == 1:
            return

        if self.object < 0 or self.object >= len(self.editor.tileset.objects):
            return

        self.tiles.pop()

        self.size[1] -= 1
        self.setMinimumSize(self.size[0]*24 + 12, self.size[1]*24 + 12)

        curObj = self.editor.tileset.objects[self.object]
        curObj.tiles = list(curObj.tiles)
        curObj.height -= 1

        curObj.tiles.pop()

        if curObj.repeatX:
            curObj.repeatX.pop()

        if curObj.repeatY:
            start, end = curObj.repeatY
            end = min(end, curObj.height)
            start = min(start, end - 1)

            if [start, end] != curObj.repeatY:
                curObj.createRepetitionY(start, end)

        if curObj.upperslope[0] != 0:
            if curObj.upperslope[1] > curObj.height or curObj.height == 1:
                curObj.upperslope[1] = curObj.height
                curObj.lowerslope = [0, 0]

                if curObj.upperslope[0] & 2:
                    self.slope = -curObj.upperslope[1]
                else:
                    self.slope = curObj.upperslope[1]

            else:
                curObj.lowerslope = [0x84, curObj.lowerslope[1] - 1]

        self.update()
        self.updateList()

        self.editor.tileWidget.repeatX.update()
        self.editor.tileWidget.repeatY.update()
        self.editor.tileWidget.slopeLine.update()


    def setObject(self, object):
        self.clear()

        self.size = [object.width, object.height]
        self.setMinimumSize(self.size[0]*24 + 12, self.size[1]*24 + 12)

        if not object.upperslope[1] == 0:
            if object.upperslope[0] & 2:
                self.slope = -object.upperslope[1]
            else:
                self.slope = object.upperslope[1]

        x = 0
        y = 0
        for row in object.tiles:
            self.tiles.append([])
            for tile in row:
                if (self.editor.slot == 0) or ((tile[2] & 3) != 0):
                    image = self.editor.tileset.overrides[tile[1]] if self.editor.slot == 0 and self.editor.overrides else None
                    if not image:
                        image = self.editor.tileset.tiles[tile[1]].image
                    self.tiles[-1].append(image.scaledToWidth(24, Qt.SmoothTransformation))
                else:
                    pix = QtGui.QPixmap(24,24)
                    pix.fill(QtGui.QColor(0,0,0,0))
                    self.tiles[-1].append(pix)
                x += 1
            y += 1
            x = 0


        self.object = self.editor.objectList.currentIndex().row()
        self.update()
        self.updateList()

        self.editor.tileWidget.repeatX.update()
        self.editor.tileWidget.repeatY.update()
        self.editor.tileWidget.slopeLine.update()


    def mousePressEvent(self, event):
        if event.button() == 2:
            return

        index = self.editor.objectList.currentIndex()
        self.object = index.row()

        if self.object < 0 or self.object >= len(self.editor.tileset.objects):
            return

        if self.editor.tileset.placeNullChecked:
            centerPoint = self.contentsRect().center()

            upperLeftX = centerPoint.x() - self.size[0]*12
            upperLeftY = centerPoint.y() - self.size[1]*12

            lowerRightX = centerPoint.x() + self.size[0]*12
            lowerRightY = centerPoint.y() + self.size[1]*12


            x = int((event.x() - upperLeftX)/24)
            y = int((event.y() - upperLeftY)/24)

            if event.x() < upperLeftX or event.y() < upperLeftY or event.x() > lowerRightX or event.y() > lowerRightY:
                return

            if self.editor.slot == 0:
                try:
                    self.tiles[y][x] = self.editor.tileset.tiles[0].image.scaledToWidth(24, Qt.SmoothTransformation)
                    self.editor.tileset.objects[self.object].tiles[y][x] = (self.editor.tileset.objects[self.object].tiles[y][x][0], 0, 0)
                except IndexError:
                    pass

            else:
                pix = QtGui.QPixmap(24,24)
                pix.fill(QtGui.QColor(0,0,0,0))

                try:
                    self.tiles[y][x] = pix
                    self.editor.tileset.objects[self.object].tiles[y][x] = (self.editor.tileset.objects[self.object].tiles[y][x][0], 0, 0)
                except IndexError:
                    pass

        else:
            if self.editor.tileDisplay.selectedIndexes() == []:
                return

            currentSelected = self.editor.tileDisplay.selectedIndexes()

            ix = 0
            iy = 0
            for modelItem in currentSelected:
                # Update yourself!
                centerPoint = self.contentsRect().center()

                tile = modelItem.row()
                upperLeftX = centerPoint.x() - self.size[0]*12
                upperLeftY = centerPoint.y() - self.size[1]*12

                lowerRightX = centerPoint.x() + self.size[0]*12
                lowerRightY = centerPoint.y() + self.size[1]*12


                x = int((event.x() - upperLeftX)/24 + ix)
                y = int((event.y() - upperLeftY)/24 + iy)

                if event.x() < upperLeftX or event.y() < upperLeftY or event.x() > lowerRightX or event.y() > lowerRightY:
                    return

                try:
                    image = self.editor.tileset.overrides[tile] if self.editor.slot == 0 and self.editor.overrides else None
                    if not image:
                        image = self.editor.tileset.tiles[tile].image
                    self.tiles[y][x] = image.scaledToWidth(24, Qt.SmoothTransformation)
                    self.editor.tileset.objects[self.object].tiles[y][x] = (self.editor.tileset.objects[self.object].tiles[y][x][0], tile, self.editor.slot)
                except IndexError:
                    pass

                ix += 1
                if self.size[0]-1 < ix:
                    ix = 0
                    iy += 1
                if iy > self.size[1]-1:
                    break

        self.update()
        self.editor.setDirty()

        self.updateList()


    def updateList(self):
        # Update the list >.>
        object = self.editor.objmodel.itemFromIndex(self.editor.objectList.currentIndex())
        if not object: return


        tex = QtGui.QPixmap(self.size[0] * 24, self.size[1] * 24)
        tex.fill(Qt.transparent)
        painter = QtGui.QPainter(tex)

        Xoffset = 0
        Yoffset = 0

        for y, row in enumerate(self.tiles):
            for x, tile in enumerate(row):
                painter.drawPixmap(x*24, y*24, tile)

        painter.end()

        object.setIcon(QtGui.QIcon(tex))

        self.editor.objectList.update()


    def paintEvent(self, event):
        painter = QtGui.QPainter()
        painter.begin(self)

        centerPoint = self.contentsRect().center()
        upperLeftX = centerPoint.x() - self.size[0]*12
        lowerRightX = centerPoint.x() + self.size[0]*12

        upperLeftY = centerPoint.y() - self.size[1]*12
        lowerRightY = centerPoint.y() + self.size[1]*12

        index = self.editor.objectList.currentIndex()
        self.object = index.row()

        if self.object < 0 or self.object >= len(self.editor.tileset.objects):
            painter.end()
            return

        object = self.editor.tileset.objects[self.object]
        for y, row in enumerate(object.tiles):
            painter.fillRect(upperLeftX, upperLeftY + y * 24, len(row) * 24, 24, QtGui.QColor(205, 205, 255))

        for y, row in enumerate(self.tiles):
            for x, pix in enumerate(row):
                painter.drawPixmap(upperLeftX + (x * 24), upperLeftY + (y * 24), pix)

        if object.upperslope[0] & 0x80:
            pen = QtGui.QPen()
            pen.setStyle(Qt.DashLine)
            pen.setWidth(2)
            pen.setColor(Qt.blue)
            painter.setPen(QtGui.QPen(pen))

            slope = self.slope
            if slope < 0:
                slope += self.size[1]

            painter.drawLine(upperLeftX, upperLeftY + (slope * 24), lowerRightX, upperLeftY + (slope * 24))

            font = painter.font()
            font.setPixelSize(8)
            font.setFamily('Monaco')
            painter.setFont(font)

            if self.slope > 0:
                painter.drawText(upperLeftX+1, upperLeftY+10, 'Main')
                painter.drawText(upperLeftX+1, upperLeftY + (slope * 24) + 9, 'Sub')

            else:
                painter.drawText(upperLeftX+1, upperLeftY + self.size[1]*24 - 4, 'Main')
                painter.drawText(upperLeftX+1, upperLeftY + (slope * 24) - 3, 'Sub')

        if 0 <= self.object < len(self.editor.tileset.objects):
            object = self.editor.tileset.objects[self.object]
            if object.repeatX and not (object.randX or object.randY):
                pen = QtGui.QPen()
                pen.setStyle(Qt.DashLine)
                pen.setWidth(2)
                pen.setColor(Qt.blue)
                painter.setPen(QtGui.QPen(pen))

                for y in range(object.height):
                    startX, endX = object.repeatX[y]
                    painter.drawLine(upperLeftX + startX * 24, upperLeftY + y * 24, upperLeftX + startX * 24, upperLeftY + y * 24 + 24)
                    painter.drawLine(upperLeftX +   endX * 24, upperLeftY + y * 24, upperLeftX +   endX * 24, upperLeftY + y * 24 + 24)

            if object.repeatY and not (object.randX or object.randY):
                pen = QtGui.QPen()
                pen.setStyle(Qt.DashLine)
                pen.setWidth(2)
                pen.setColor(Qt.red)
                painter.setPen(QtGui.QPen(pen))

                painter.drawLine(upperLeftX, upperLeftY + object.repeatY[0] * 24, lowerRightX, upperLeftY + object.repeatY[0] * 24)
                painter.drawLine(upperLeftX, upperLeftY + object.repeatY[1] * 24, lowerRightX, upperLeftY + object.repeatY[1] * 24)

        painter.end()



#############################################################################################
################################## Pa0 Tileset Animation Tab ################################


class frameTileWidget(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    def width(self):
        return 0

    def height(self):
        return 0

    def pixmap(self):
        return None

    def paintEvent(self, event):
        if not self.parent.frames:
            return

        painter = QtGui.QPainter()
        painter.begin(self)

        width = self.width()
        height = self.height()
        pixmap = self.pixmap()

        centerPoint = self.contentsRect().center()
        upperLeftX = centerPoint.x() - width * 30
        upperLeftY = centerPoint.y() - height * 30

        painter.fillRect(upperLeftX, upperLeftY, width * 60, height * 60, QtGui.QColor(205, 205, 255))
        painter.drawPixmap(upperLeftX, upperLeftY, pixmap)


class frameByFrameTab(QtWidgets.QWidget):
    class tileWidget(frameTileWidget):
        def __init__(self, parent):
            super().__init__(parent)
            self.idx = 0

        def width(self):
            return self.parent.blockWidth

        def height(self):
            return self.parent.blockHeight

        def pixmap(self):
            return self.parent.frames[self.idx]

    def __init__(self, parent):
        super().__init__()

        self.parent = parent

        self.importButton = QtWidgets.QPushButton('Import')
        self.importButton.released.connect(self.importFrame)
        self.importButton.setEnabled(False)

        self.exportButton = QtWidgets.QPushButton('Export')
        self.exportButton.released.connect(self.exportFrame)
        self.exportButton.setEnabled(False)

        self.addButton = QtWidgets.QPushButton('Add Frame')
        self.addButton.released.connect(self.addFrame)

        self.deleteButton = QtWidgets.QPushButton('Delete Frame')
        self.deleteButton.released.connect(self.deleteFrame)
        self.deleteButton.setEnabled(False)

        self.playButton = QtWidgets.QPushButton('Play Preview')
        self.playButton.setCheckable(True)
        self.playButton.toggled.connect(self.playPreview)
        self.playButton.setEnabled(False)

        self.tiles = frameByFrameTab.tileWidget(parent)

        self.frameIdx = QtWidgets.QSpinBox()
        self.frameIdx.setRange(0, 0)
        self.frameIdx.valueChanged.connect(self.frameIdxChanged)
        self.frameIdx.setEnabled(False)

        layout = QtWidgets.QGridLayout()

        layout.addWidget(self.tiles, 0, 1, 2, 3)
        layout.addWidget(self.frameIdx, 3, 2, 1, 1)
        layout.addWidget(self.importButton, 3, 0, 1, 1)
        layout.addWidget(self.exportButton, 4, 0, 1, 1)
        layout.addWidget(self.addButton, 3, 4, 1, 1)
        layout.addWidget(self.deleteButton, 4, 4, 1, 1)
        layout.addWidget(self.playButton, 4, 1, 1, 3)

        self.setLayout(layout)

        self.previewTimer = QtCore.QTimer(self)
        self.previewTimer.timeout.connect(lambda: self.frameIdxChanged(self.getNextFrame()))

    def update(self):
        self.tiles.update()

        super().update()

    def frameIdxChanged(self, idx):
        self.tiles.idx = idx
        self.update()

    def importPixmap(self):
        path = QtWidgets.QFileDialog.getOpenFileName(self, "Open Image", '',
                                                     '.png (*.png)')[0]
        if not path:
            return None

        pixmap = QtGui.QPixmap(path)
        width = pixmap.width()
        height = pixmap.height()

        blockWidth = self.parent.blockWidth
        blockHeight = self.parent.blockHeight

        requiredWidth = blockWidth * 60
        requiredHeight = blockHeight * 60

        try:
            assert width == requiredWidth
            assert height == requiredHeight

        except AssertionError:
            requiredWidthPadded = blockWidth * 64
            requiredHeightPadded = blockHeight * 64

            try:
                assert width == requiredWidthPadded
                assert height == requiredHeightPadded

            except AssertionError:
                QtWidgets.QMessageBox.warning(self, "Open Image",
                    "The image was not the proper dimensions.\n"
                    "Please resize the image to %dx%d pixels." % (requiredWidth, requiredHeight),
                    QtWidgets.QMessageBox.Cancel)

                return None

            paddedPixmap = pixmap

            pixmap = QtGui.QPixmap(requiredWidth, requiredHeight)
            pixmap.fill(Qt.transparent)

            for y in range(height // 64):
                for x in range(width // 64):
                    painter = QtGui.QPainter(pixmap)
                    painter.drawPixmap(x * 60, y * 60, paddedPixmap.copy(x*64 + 2, y*64 + 2, 60, 60))
                    painter.end()

            del paddedPixmap

        return pixmap

    def importFrame(self):
        pixmap = self.importPixmap()
        if not pixmap:
            return

        del self.parent.frames[self.tiles.idx]
        self.parent.frames.insert(self.tiles.idx, pixmap)
        self.parent.update()

    def exportFrame(self):
        path = QtWidgets.QFileDialog.getSaveFileName(self, "Save Image", ''
                                                     , '.png (*.png)')[0]
        if not path:
            return

        self.tiles.pixmap().save(path)

    def addFrame(self):
        pixmap = self.importPixmap()
        if not pixmap:
            return

        newIdx = len(self.parent.frames)
        self.parent.frames.append(pixmap)
        self.parent.update()

        self.frameIdx.setValue(newIdx)

    def deleteFrame(self):
        idx = self.tiles.idx
        frames = self.parent.frames
        del frames[idx]

        self.frameIdx.setValue(min(idx, max(len(frames), 1) - 1))
        self.parent.update()

    def getNextFrame(self):
        return (self.tiles.idx + 1) % max(len(self.parent.frames), 1)

    def playPreview(self, checked):
        if checked:
            self.importButton.setEnabled(False)
            self.exportButton.setEnabled(False)
            self.addButton.setEnabled(False)
            self.deleteButton.setEnabled(False)
            self.frameIdx.setEnabled(False)
            self.parent.allFramesTab.importButton.setEnabled(False)

            self.previewTimer.start(63)  # 62.5

        else:
            self.importButton.setEnabled(True)
            self.exportButton.setEnabled(True)
            self.addButton.setEnabled(True)
            self.deleteButton.setEnabled(True)
            self.frameIdx.setEnabled(True)
            self.parent.allFramesTab.importButton.setEnabled(True)

            self.previewTimer.stop()
            self.frameIdx.setValue(self.tiles.idx)


class scrollArea(QtWidgets.QScrollArea):
    def __init__(self, widget):
        super().__init__()

        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(widget)

        self.deltaWidth = globals.app.style().pixelMetric(QtWidgets.QStyle.PM_ScrollBarExtent)
        self.width = widget.sizeHint().width() + self.deltaWidth
        self.height = widget.sizeHint().height() + self.deltaWidth

    def sizeHint(self):
        return QtCore.QSize(self.width, self.height)

    def update(self):
        widget = self.widget()
        self.width = widget.sizeHint().width() + self.deltaWidth
        self.height = widget.sizeHint().height() + self.deltaWidth

        super().update()


class allFramesTab(QtWidgets.QWidget):
    class tileWidget(frameTileWidget):
        def width(self):
            return self.parent.blockWidth

        def height(self):
            return self.parent.blockHeight * len(self.parent.frames)

        def pixmap(self):
            pixmap = QtGui.QPixmap(self.width() * 60, self.height() * 60)
            pixmap.fill(Qt.transparent)

            blockHeight = self.parent.blockHeight

            for i, frame in enumerate(self.parent.frames):
                painter = QtGui.QPainter(pixmap)
                painter.drawPixmap(0, i * blockHeight * 60, frame)
                painter.end()

            return pixmap

    def __init__(self, parent):
        super().__init__()

        self.parent = parent

        self.importButton = QtWidgets.QPushButton('Import')
        self.importButton.released.connect(self.importFrame)

        self.exportButton = QtWidgets.QPushButton('Export')
        self.exportButton.released.connect(self.exportFrame)

        self.tiles = allFramesTab.tileWidget(parent)
        self.tilesScroll = scrollArea(self.tiles)

        layout = QtWidgets.QGridLayout()

        layout.addWidget(self.importButton, 0, 0, 1, 2)
        layout.addWidget(self.exportButton, 0, 2, 1, 2)
        layout.addWidget(self.tilesScroll, 1, 0, 1, 4)

        self.setLayout(layout)

    def update(self):
        self.tiles.update()
        self.tilesScroll.update()

        super().update()

    def importFrame(self):
        path = QtWidgets.QFileDialog.getOpenFileName(self, "Open Image", '',
                                                     '.png (*.png)')[0]
        if not path:
            return

        pixmap = QtGui.QPixmap(path)
        width = pixmap.width()
        height = pixmap.height()

        blockWidth = self.parent.blockWidth
        blockHeight = self.parent.blockHeight

        requiredWidth = blockWidth * 60
        requiredHeight = blockHeight * 60

        padded = False

        try:
            assert width == requiredWidth
            assert height % requiredHeight == 0

        except AssertionError:
            requiredWidthPadded = blockWidth * 64
            requiredHeightPadded = blockHeight * 64

            try:
                assert width == requiredWidthPadded
                assert height % requiredHeightPadded == 0

            except AssertionError:
                QtWidgets.QMessageBox.warning(self, "Open Image",
                    "The image was not the proper dimensions.\n"
                    "Please resize the image to a width of %d and height multiple of %d." % (requiredWidth, requiredHeight),
                    QtWidgets.QMessageBox.Cancel)

                return

            padded = True

        if padded:
            frames = [QtGui.QPixmap(requiredWidth, requiredHeight) for _ in range(height // requiredHeightPadded)]
            for frame in frames:
                frame.fill(Qt.transparent)

            for y in range(height // 64):
                for x in range(width // 64):
                    painter = QtGui.QPainter(frames[y // blockHeight])
                    painter.drawPixmap(x * 60, y % blockHeight * 60, pixmap.copy(x*64 + 2, y*64 + 2, 60, 60))
                    painter.end()

        else:
            frames = [QtGui.QPixmap(requiredWidth, requiredHeight) for _ in range(height // requiredHeight)]
            for frame in frames:
                frame.fill(Qt.transparent)

            for y in range(0, height, requiredHeight):
                painter = QtGui.QPainter(frames[y // requiredHeight])
                painter.drawPixmap(0, 0, pixmap.copy(0, y, requiredWidth, requiredHeight))
                painter.end()

        del pixmap
        del self.parent.frames

        self.parent.frames = frames
        self.parent.update()

    def exportFrame(self):
        path = QtWidgets.QFileDialog.getSaveFileName(self, "Save Image", ''
                                                     , '.png (*.png)')[0]
        if not path:
            return

        self.tiles.pixmap().save(path)


class tileAnime(QtWidgets.QTabWidget):
    def __init__(self, name, blockWidth, blockHeight, tiles):
        super().__init__()

        self.name = name

        self.blockWidth = blockWidth
        self.blockHeight = blockHeight
        self.tiles = tiles  # TODO: Highlight tiles in the palette when this tab is selected

        self.frames = []

        self.frameByFrameTab = frameByFrameTab(self)
        self.allFramesTab = allFramesTab(self)

        self.addTab(self.frameByFrameTab, "Frame-by-frame View")
        self.addTab(self.allFramesTab, "All-Frames View")

        self.setStyleSheet("""
        QTabWidget::tab-bar {
            alignment: center;
        }
        """)

        self.setTabPosition(QtWidgets.QTabWidget.South)

    def allFramesPixmap(self):
        """Return same composite image shown by All-Frames View."""
        return self.allFramesTab.tiles.pixmap()

    def load(self, arc, useAddrLib=False):

        image = None
        if globals.IsNSMBUDX:
            # Deluxe: the animation is a texture inside the tileset's BNTX
            try:
                image = QtGui.QPixmap.fromImage(loadTexFromBNTX(getTilesetBNTX(arc), self.name))
            except Exception:
                print("Failed to acquire %s from the tileset's textures" % self.name)

        else:
            data = b''
            for folder in arc.contents:
                if folder.name == 'BG_tex':
                    for file in folder.contents:
                        if file.name == '%s.gtx' % self.name:
                            data = file.data

            if not data:
                print("Failed to acquire %s.gtx" % self.name)
            else:
                image = QtGui.QPixmap.fromImage(loadGTX(data, useAddrLib))

        if image is None:
            frames = []

        else:
            width = image.width()
            height = image.height()

            blockWidth = self.blockWidth
            blockHeight = self.blockHeight

            try:
                assert width == blockWidth * 64
                assert height % blockHeight * 64 == 0

            except AssertionError:
                print("Invalid dimensions for %s: (%d, %d)" % (self.name, width, height))
                frames = []

            else:
                frames = [QtGui.QPixmap(blockWidth * 60, blockHeight * 60) for _ in range(height // (blockHeight * 64))]
                for frame in frames:
                    frame.fill(Qt.transparent)

                for y in range(height // 64):
                    for x in range(width // 64):
                        painter = QtGui.QPainter(frames[y // blockHeight])
                        painter.drawPixmap(x * 60, y % blockHeight * 60, image.copy(x*64 + 2, y*64 + 2, 60, 60))
                        painter.end()

        del self.frames
        self.frames = frames
        self.update()

    def update(self):
        nFrames = len(self.frames)
        _frameByFrameTab = self.frameByFrameTab
        _frameByFrameTab.tiles.setMinimumSize(_frameByFrameTab.tiles.width() * 60, _frameByFrameTab.tiles.height() * 60)
        _frameByFrameTab.importButton.setEnabled(nFrames)
        _frameByFrameTab.exportButton.setEnabled(nFrames)
        _frameByFrameTab.deleteButton.setEnabled(nFrames)
        _frameByFrameTab.playButton.setEnabled(nFrames)
        _frameByFrameTab.frameIdx.setRange(0, max(nFrames, 1) - 1)
        _frameByFrameTab.frameIdx.setEnabled(nFrames)
        _frameByFrameTab.update()

        _allFramesTab = self.allFramesTab
        _allFramesTab.tiles.setMinimumSize(_allFramesTab.tiles.width() * 60, _allFramesTab.tiles.height() * 60)
        _allFramesTab.exportButton.setEnabled(nFrames)
        _allFramesTab.update()

        super().update()


class animWidget(QtWidgets.QWidget):
    def __init__(self, editor=None):
        super().__init__()
        self.editor = editor

        if editor and editor.slot:
            return

        self.block = tileAnime('block_anime', 1, 1, (48,))
        self.hatena = tileAnime('hatena_anime', 1, 1, (49,))
        self.blockL = tileAnime('block_anime_L', 2, 2, (112, 113, 128, 129))
        self.hatenaL = tileAnime('hatena_anime_L', 2, 2, (114, 115, 130, 131))
        self.tuka = tileAnime('tuka_coin_anime', 1, 1, (31,))
        self.belt = tileAnime('belt_conveyor_anime', 3, 1, (144, 145, 146, 147, 148, 149,
                                                           160, 161, 162, 163, 164, 165))

        self.animations = (self.block, self.hatena, self.blockL, self.hatenaL, self.tuka, self.belt)
        self.tabs = QtWidgets.QTabWidget()

        path = os.path.join(globals.miyamoto_path, 'yaz0data', 'Icons', '')

        self.tabs.addTab(self.block, QtGui.QIcon(path + 'Core/Brick.png'), 'Brick Block')
        self.tabs.addTab(self.hatena, QtGui.QIcon(path + 'Core/Qblock.png'), '? Block')
        self.tabs.addTab(self.blockL, QtGui.QIcon(path + 'Core/Brick.png'), 'Big Brick Block')
        self.tabs.addTab(self.hatenaL, QtGui.QIcon(path + 'Core/Qblock.png'), 'Big ? Block')
        self.tabs.addTab(self.tuka, QtGui.QIcon(path + 'Core/DashCoin.png'), 'Dash Coin')
        self.tabs.addTab(self.belt, QtGui.QIcon(path + 'Core/Conveyor.png'), 'Conveyor Belt')

        self.tabs.setTabToolTip(0, "Brick Block animation.<br><b>Needs to be 16 frames!")
        self.tabs.setTabToolTip(1, "Question Block animation.<br><b>Needs to be 16 frames!")
        self.tabs.setTabToolTip(2, "Big Brick Block animation.<br><b>Needs to be 16 frames!")
        self.tabs.setTabToolTip(3, "Big Question Block animation.<br><b>Needs to be 16 frames!")
        self.tabs.setTabToolTip(4, "Dash Coin animation.<br><b>Needs to be 8 frames!")
        self.tabs.setTabToolTip(5, "Conveyor Belt animation.<br><b>Needs to be 8 frames!")

        #self.tabs.setTabShape(QtWidgets.QTabWidget.Triangular)
        self.tabs.setTabPosition(QtWidgets.QTabWidget.South)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.tabs)

    def load(self):
        if self.editor and self.editor.slot:
            return

        arc = self.editor.arc if self.editor else None
        self.block.load(arc)
        self.hatena.load(arc)
        self.blockL.load(arc)
        self.hatenaL.load(arc)
        self.tuka.load(arc)
        self.belt.load(arc, True)

    def save(self):
        if self.editor and self.editor.slot:
            return []

        def entry(name, pixmap):
            # Wii U: (name, GTX bytes); Deluxe: (name, raw RGBA8, width, height)
            packed = self.packTexture(pixmap)
            return (name, *packed) if isinstance(packed, tuple) else (name, packed)

        anime = []

        if self.block.frames:
            anime.append(entry(self.block.name, self.block.allFramesPixmap()))

        if self.hatena.frames:
            anime.append(entry(self.hatena.name, self.hatena.allFramesPixmap()))

        if self.blockL.frames:
            anime.append(entry(self.blockL.name, self.blockL.allFramesPixmap()))

        if self.hatenaL.frames:
            anime.append(entry(self.hatenaL.name, self.hatenaL.allFramesPixmap()))

        if self.tuka.frames:
            anime.append(entry(self.tuka.name, self.tuka.allFramesPixmap()))

        if self.belt.frames:
            anime.append(entry(self.belt.name, self.belt.allFramesPixmap()))

        return anime

    def exportAll(self):
        loadedAnimations = [animation for animation in self.animations if animation.frames]
        if not loadedAnimations:
            QtWidgets.QMessageBox.information(self, 'Export Animations',
                                              'No animation frames are available to export.')
            return

        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Export Folder')
        if not folder:
            return

        existing = [os.path.join(folder, animation.name + '.png')
                    for animation in loadedAnimations
                    if os.path.exists(os.path.join(folder, animation.name + '.png'))]
        if existing:
            result = QtWidgets.QMessageBox.question(
                self, 'Overwrite Existing Images',
                '%d animation image(s) already exist in this folder. Overwrite them?' % len(existing),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No)
            if result != QtWidgets.QMessageBox.Yes:
                return

        failed = []
        for animation in loadedAnimations:
            path = os.path.join(folder, animation.name + '.png')
            if not animation.allFramesPixmap().save(path, 'PNG'):
                failed.append(animation.name + '.png')

        if failed:
            QtWidgets.QMessageBox.warning(
                self, 'Export Animations',
                'Could not write:\n' + '\n'.join(failed))
        else:
            QtWidgets.QMessageBox.information(
                self, 'Export Animations',
                'Exported %d animation image(s).' % len(loadedAnimations))

    @staticmethod
    def packTexture(pixmap):
        width = pixmap.width() // 60
        height = pixmap.height() // 60

        tex = QtGui.QImage(width * 64, height * 64, QtGui.QImage.Format_RGBA8888)
        tex.fill(Qt.transparent)
        painter = QtGui.QPainter(tex)

        for y in range(height):
            for x in range(width):
                tile = QtGui.QImage(64, 64, QtGui.QImage.Format_RGBA8888)
                tile.fill(Qt.transparent)

                tilePainter = QtGui.QPainter(tile)
                tilePainter.drawPixmap(2, 2, pixmap.copy(x * 60, y * 60, 60, 60))
                tilePainter.end()

                for i in range(2, 62):
                    color = tile.pixel(i, 2)
                    for pix in range(0,2):
                        tile.setPixel(i, pix, color)

                    color = tile.pixel(2, i)
                    for p in range(0,2):
                        tile.setPixel(p, i, color)

                    color = tile.pixel(i, 61)
                    for p in range(62,64):
                        tile.setPixel(i, p, color)

                    color = tile.pixel(61, i)
                    for p in range(62,64):
                        tile.setPixel(p, i, color)

                color = tile.pixel(2, 2)
                for a in range(0, 2):
                    for b in range(0, 2):
                        tile.setPixel(a, b, color)

                color = tile.pixel(61, 2)
                for a in range(62, 64):
                    for b in range(0, 2):
                        tile.setPixel(a, b, color)

                color = tile.pixel(2, 61)
                for a in range(0, 2):
                    for b in range(62, 64):
                        tile.setPixel(a, b, color)

                color = tile.pixel(61, 61)
                for a in range(62, 64):
                    for b in range(62, 64):
                        tile.setPixel(a, b, color)


                painter.drawImage(x * 64, y * 64, tile)

        painter.end()

        bits = tex.bits()
        bits.setsize(tex.byteCount())
        data = bits.asstring()

        if globals.IsNSMBUDX:
            return bytes(data), width * 64, height * 64

        return RAWtoGTX(width * 64, height * 64, 0x1a, bytes(4), len(data), [0, 1, 2, 3], 1, data)



#############################################################################################
############################ Subclassed one dimension Item Model ############################


class PiecesModel(QtCore.QAbstractListModel):
    def __init__(self, parent=None):
        super(PiecesModel, self).__init__(parent)

        self.pixmaps = []

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        if role == Qt.DecorationRole:
            return QtGui.QIcon(self.pixmaps[index.row()])

        if role == Qt.UserRole:
            return self.pixmaps[index.row()]

        return None

    def addPieces(self, pixmap):
        row = len(self.pixmaps)

        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        self.pixmaps.insert(row, pixmap)
        self.endInsertRows()

    def flags(self,index):
        if index.isValid():
            return (Qt.ItemIsEnabled | Qt.ItemIsSelectable |
                    Qt.ItemIsDragEnabled)

    def clear(self):
        row = len(self.pixmaps)

        del self.pixmaps[:]


    def mimeTypes(self):
        return ['image/x-tile-piece']


    def mimeData(self, indexes):
        mimeData = QtCore.QMimeData()
        encodedData = QtCore.QByteArray()

        stream = QtCore.QDataStream(encodedData, QtCore.QIODevice.WriteOnly)

        for index in indexes:
            if index.isValid():
                pixmap = QtGui.QPixmap(self.data(index, Qt.UserRole))
                stream << pixmap

        mimeData.setData('image/x-tile-piece', encodedData)
        return mimeData


    def rowCount(self, parent):
        if parent.isValid():
            return 0
        else:
            return len(self.pixmaps)

    def supportedDragActions(self):
        return Qt.CopyAction | Qt.MoveAction



#############################################################################################
############ Main Window Class. Takes care of menu functions and widget creation ############


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, slots_data, flags, parent=None):
        super().__init__(parent, flags)

        global window
        window = self

        self.forceClose = False
        self.editors = []

        self.setupMenus()

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.currentChanged.connect(self.handleTabChange)
        self.setCentralWidget(self.tabs)

        _TAB_NAMES = ['Main', 'Slot 2', 'Slot 3', 'Slot 4']
        for name, data, con in slots_data:
            slot = len(self.editors)
            editor = TilesetEditor(self, name, data, slot, con)
            self.editors.append(editor)
            label = _TAB_NAMES[slot] if slot < len(_TAB_NAMES) else str(slot)
            tabIndex = self.tabs.addTab(editor, label)

            # Deluxe: show which file in Unit this slot edits (new/empty slots have none yet)
            if globals.IsNSMBUDX and not con:
                path = globals.gamedef.FindTilesetFile(name)
                if path:
                    self.tabs.setTabToolTip(tabIndex, path)

            if editor.forceClose:
                self.forceClose = True

        if not self.editors:
            self.forceClose = True
        else:
            self.handleTabChange(0)

    def handleTabChange(self, index):
        self.exportAnimationsAction.setEnabled(False)
        if 0 <= index < len(self.editors):
            self.editors[index].activate()
            self.setWindowTitle(f'Edit Tilesets — {self.editors[index].name}')
            self.exportAnimationsAction.setEnabled(self.editors[index].slot == 0)

    def exportAllAnimations(self):
        editor = self.tabs.currentWidget()
        if editor and editor.slot == 0:
            editor.animWidget.exportAll()

    _TAB_NAMES = ['Main', 'Slot 2', 'Slot 3', 'Slot 4']

    def updateTabTitle(self, editor):
        index = self.editors.index(editor)
        label = self._TAB_NAMES[editor.slot] if editor.slot < len(self._TAB_NAMES) else str(editor.slot)
        if editor.isDirty:
            label += ' *'
        self.tabs.setTabText(index, label)
        if self.tabs.currentIndex() == index:
            self.setWindowTitle(f'Edit Tilesets — {editor.name}')

    # Proxies for global references in old code
    @property
    def objectList(self): return self.tabs.currentWidget().objectList
    @property
    def objmodel(self): return self.tabs.currentWidget().objmodel
    @property
    def tileWidget(self): return self.tabs.currentWidget().tileWidget
    @property
    def paletteWidget(self): return self.tabs.currentWidget().paletteWidget
    @property
    def tileDisplay(self): return self.tabs.currentWidget().tileDisplay
    @property
    def model(self): return self.tabs.currentWidget().model
    @property
    def animWidget(self): return self.tabs.currentWidget().animWidget
    @property
    def slot(self): return self.tabs.currentWidget().slot
    @property
    def normalmap(self): return self.tabs.currentWidget().normalmap
    @normalmap.setter
    def normalmap(self, val): self.tabs.currentWidget().normalmap = val
    @property
    def overrides(self): return self.tabs.currentWidget().overrides
    @overrides.setter
    def overrides(self, val): self.tabs.currentWidget().overrides = val
    @property
    def con(self): return self.tabs.currentWidget().con

    def setupMenus(self):
        menubar = self.menuBar()
        
        fileMenu = menubar.addMenu("&File")
        fileMenu.addAction("Import Tileset from file...", self.openTilesetfromFile, QtGui.QKeySequence.Open)
        fileMenu.addAction("Import Tileset from Objects...", self.importTilesetFromObjects)
        fileMenu.addAction("Export Tileset...", self.saveTilesetAs, QtGui.QKeySequence.SaveAs)
        fileMenu.addAction("Export All Tilesets...", self.exportAllTilesets)
        fileMenu.addSeparator()
        fileMenu.addAction("Save", self.saveCurrentTileset, QtGui.QKeySequence.Save)
        fileMenu.addAction("Quit", self.close, QtGui.QKeySequence('Ctrl+Q'))

        imageMenu = menubar.addMenu("&Image")
        imageMenu.addAction("Import Image...", self.openImage, QtGui.QKeySequence('Ctrl+I'))
        imageMenu.addAction("Export Image...", self.saveImage, QtGui.QKeySequence('Ctrl+E'))
        self.exportAnimationsAction = imageMenu.addAction(
            "Export all tileset animations...", self.exportAllAnimations)
        self.exportAnimationsAction.setEnabled(False)
        imageMenu.addAction("Import Normal Map...", self.openNml, QtGui.QKeySequence('Ctrl+Shift+I'))
        imageMenu.addAction("Export Normal Map...", self.saveNml, QtGui.QKeySequence('Ctrl+Shift+E'))

        objMenu = menubar.addMenu("&Objects")
        objMenu.addAction("Import object from file...", self.importObjFromFile, '')
        objMenu.addAction("Import Objects...", self.importObjectsFromFolder, '')
        objMenu.addSeparator()
        objMenu.addAction("Export object...", self.saveObject, '')
        objMenu.addAction("Export all objects...", self.saveAllObjects, '')
        objMenu.addSeparator()
        objMenu.addAction("Delete All Objects", self.clearObjects, QtGui.QKeySequence('Ctrl+Alt+Backspace'))
        objMenu.addAction("Clear Collision Data", self.clearCollisions, QtGui.QKeySequence('Ctrl+Shift+Backspace'))

    def exportAllTilesets(self):
        """
        Exports every open tileset (with any unsaved changes) into one folder.
        Empty slots are skipped unless something was added to them.
        """
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, 'Export All Tilesets', str(misc.setting('LastTilesetExportDir', '')))
        if not folder:
            return
        misc.setSetting('LastTilesetExportDir', folder)

        written, failed = [], []
        for editor in self.editors:
            if editor.con and not editor.isDirty:
                continue
            name = 'Pa%d_new' % editor.slot if editor.con else editor.name
            path = os.path.join(folder, name + ('.szs' if globals.IsNSMBUDX else '.sarc'))
            try:
                if globals.IsNSMBUDX:
                    WriteTilesetFileDX(name, editor.saving(name), path)
                else:
                    yaz0.writeFile(path, editor.saving(name))
                written.append(os.path.basename(path))
            except (OSError, ValueError) as e:
                failed.append('%s: %s' % (name, e))

        message = 'Exported %d tileset(s) to:\n%s' % (len(written), folder)
        if written:
            message += '\n\n' + '\n'.join(written)
        if failed:
            QtWidgets.QMessageBox.warning(self, 'Export All Tilesets', message + '\n\nCould not export:\n' + '\n'.join(failed))
        else:
            QtWidgets.QMessageBox.information(self, 'Export All Tilesets', message)

    def saveCurrentTileset(self):
        editor = self.tabs.currentWidget()
        if editor and editor.isDirty:
            editor.saveTileset()

    def saveAllAndQuit(self):
        for editor in self.editors:
            if editor.isDirty:
                editor.saveTileset()
        self.close()

    def closeEvent(self, event):
        dirty_editors = [e for e in self.editors if e.isDirty]
        
        if not dirty_editors:
            event.accept()
            return

        if misc.setting('AutoSaveTilesets', False):
            for e in dirty_editors:
                e.saveTileset()
            event.accept()
            return

        names = ", ".join([e.name for e in dirty_editors])
        msg = f"Unsaved changes in tilesets: {names}.\nDo you want to save before quitting?"
        
        res = QtWidgets.QMessageBox.question(self, "Unsaved Changes", msg,
                                             QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel)
        
        if res == QtWidgets.QMessageBox.Save:
            for e in dirty_editors:
                e.saveTileset()
            event.accept()
        elif res == QtWidgets.QMessageBox.Discard:
            event.accept()
        else:
            event.ignore()

    # The following methods just call the current editor's version

    def openTilesetfromFile(self): self.tabs.currentWidget().openTilesetfromFile()
    def saveTilesetAs(self): self.tabs.currentWidget().saveTilesetAs()
    def openImage(self): self.tabs.currentWidget().openImage()
    def saveImage(self): self.tabs.currentWidget().saveImage()
    def openNml(self): self.tabs.currentWidget().openNml()
    def saveNml(self): self.tabs.currentWidget().saveNml()
    def importObjFromFile(self): self.tabs.currentWidget().importObjFromFile()
    def saveObject(self): self.tabs.currentWidget().saveObject()
    def saveAllObjects(self): self.tabs.currentWidget().saveAllObjects()
    def clearObjects(self): self.tabs.currentWidget().clearObjects()
    def clearCollisions(self): self.tabs.currentWidget().clearCollisions()
    def importTilesetFromObjects(self): self.tabs.currentWidget().importTilesetFromObjects()

    def importObjectsFromFolder(self):
        """Open the folder-import dialog and import selected objects into the chosen slot(s)."""
        top = misc.setting('ObjPath', '') or os.path.join(globals.user_data_path, 'Objects')
        if not top or not os.path.isdir(top):
            QtWidgets.QMessageBox.warning(
                self, "Import Objects",
                "No Objects folder is configured.\n\n"
                "Set the Objects folder path in Preferences → Game Setup first.")
            return

        dlg = ImportObjectsDialog(self.editors, self)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return

        selected = dlg.selectedObjects()
        if not selected:
            return

        startSlot = dlg.targetSlotIndex()  # 1-3 or -1 (first available)

        # Build the ordered list of slot indices to try
        if startSlot == -1:
            slotOrder = [1, 2, 3]
        else:
            slotOrder = [startSlot]

        # Map slot index → TilesetEditor
        editorMap = {e.slot: e for e in self.editors if e.slot in (1, 2, 3)}

        imported = 0
        skipped = 0
        noRoom = 0

        for jsonData, dirPath in selected:
            placed = False
            for slotIdx in slotOrder:
                editor = editorMap.get(slotIdx)
                if editor is None:
                    continue
                ok, reason = editor._importSingleObject(jsonData, dirPath)
                if ok:
                    imported += 1
                    placed = True
                    break
                # If no room and we're in first-available mode, try the next slot

            if not placed:
                noRoom += 1

        # Refresh the main-window object palette if visible
        try:
            from . import globals as _g
            if _g.mainWindow is not None:
                _g.mainWindow.objPicker.LoadFromTilesets()
                _g.mainWindow.objPicker.update()
        except Exception:
            pass

        # Summary feedback
        parts = []
        if imported:
            parts.append(f"{imported} object{'s' if imported != 1 else ''} imported")
        if noRoom:
            parts.append(f"{noRoom} could not fit (no room left in the target slot{'s' if len(slotOrder) > 1 else ''})")
        if parts:
            QtWidgets.QMessageBox.information(self, "Import Complete", "\n".join(parts))




#############################################################################################
############################ Import Objects from Folder Dialog ##############################


_OBJECT_FILES = ("colls", "meta", "objlyt", "img", "nml")


def _naturalKey(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


def loadObjectFolder(dirPath):
    """
    The objects exported to a folder (by Export all objects: <name>.json, .png, _nml.png,
    .colls, .meta and .objlyt each), in name order (object_2 before object_10), as
    [(name, jsonData), ...]. Objects with a file missing are left out.
    """
    try:
        files = sorted([f for f in os.listdir(dirPath) if f.lower().endswith('.json')], key=_naturalKey)
    except OSError:
        return []

    objects = []
    for filename in files:
        try:
            with open(os.path.join(dirPath, filename)) as f:
                jsonData = json.load(f)
        except Exception:
            continue
        if not isinstance(jsonData, dict) or not all(k in jsonData for k in _OBJECT_FILES):
            continue
        if not all(os.path.isfile(os.path.join(dirPath, jsonData[k])) for k in _OBJECT_FILES):
            continue
        objects.append((os.path.splitext(filename)[0], jsonData))
    return objects


def _unpackCommands(path, dest):
    """
    Commands that can unpack a RAR (or 7z) file, in the order they're tried: bsdtar (built
    into Windows 10 and later, and macOS), 7-Zip, unrar and unar.
    """
    commands = []
    if sys.platform == 'win32':
        windir = os.environ.get('SystemRoot', r'C:\Windows')
        commands.append([os.path.join(windir, 'System32', 'tar.exe'), '-xf', path, '-C', dest])
    elif sys.platform == 'darwin':
        commands.append(['/usr/bin/tar', '-xf', path, '-C', dest])
    if shutil.which('bsdtar'):
        commands.append([shutil.which('bsdtar'), '-xf', path, '-C', dest])

    sevenZip = [shutil.which(name) for name in ('7z', '7zz')]
    if sys.platform == 'win32':
        for folder in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
            if folder:
                sevenZip.append(os.path.join(folder, '7-Zip', '7z.exe'))
    commands += [[exe, 'x', '-y', '-o' + dest, path] for exe in sevenZip if exe and os.path.isfile(exe)]

    unrar = [shutil.which('unrar')]
    if sys.platform == 'win32':
        for folder in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
            if folder:
                unrar.append(os.path.join(folder, 'WinRAR', 'UnRAR.exe'))
    commands += [[exe, 'x', '-y', '-o+', path, dest + os.sep] for exe in unrar if exe and os.path.isfile(exe)]

    if shutil.which('unar'):
        commands.append([shutil.which('unar'), '-q', '-f', '-o', dest, path])
    return [c for c in commands if os.path.isfile(c[0])]


def extractArchive(path, dest):
    """
    Unpacks a ZIP file (with Python) or a RAR or 7z file (with a program for it, see
    _unpackCommands) into dest. Returns None, or what went wrong.
    """
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                archive.extractall(dest)  # names with ".." or drive letters are made safe
            return None
        except (OSError, zipfile.BadZipFile) as exc:
            return "The ZIP file could not be read (%s)." % exc

    commands = _unpackCommands(path, dest)
    if not commands:
        return ("No program that can unpack this file was found. Install 7-Zip "
                "(or WinRAR, unrar or unar) and try again.")
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    for command in commands:
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=300, creationflags=flags)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and os.listdir(dest):
            return None
        # A failed attempt may leave half the files: clear them for the next program
        for name in os.listdir(dest):
            target = os.path.join(dest, name)
            if os.path.isdir(target) and not os.path.islink(target):
                shutil.rmtree(target, ignore_errors=True)
            else:
                os.remove(target)
    return "The file could not be unpacked. It may be damaged, password-protected or not an archive."


def findObjectFolder(root):
    """root, or else the first folder inside it, with exported objects in it; None if there's none."""
    for dirPath, dirNames, _ in os.walk(root):
        dirNames[:] = sorted((d for d in dirNames if d != '__MACOSX'), key=_naturalKey)
        if loadObjectFolder(dirPath):
            return dirPath
    return None



class ImportObjectsDialog(QtWidgets.QDialog):
    """Dialog for importing objects from a collection folder into tileset slots 2–4."""

    def __init__(self, editors, parent=None):
        super().__init__(parent)
        self.editors = editors  # list of TilesetEditor, one per slot (index == slot)
        self.setWindowTitle("Import Objects")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(520)
        self.setMinimumHeight(600)
        self._objectData = []  # parallel list of (jsonData, dirPath) for each model row
        self._buildUI()
        self._loadFolders()

    # ── UI construction ──────────────────────────────────────────────────────

    def _buildUI(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 12, 14, 12)

        # Collection picker
        collRow = QtWidgets.QHBoxLayout()
        collRow.addWidget(QtWidgets.QLabel("Collection:"))
        self.folderCombo = QtWidgets.QComboBox()
        self.folderCombo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.folderCombo.currentIndexChanged.connect(self._loadObjects)
        collRow.addWidget(self.folderCombo, 1)
        layout.addLayout(collRow)

        # Object viewport with click-to-toggle multi-select
        self._objectModel = QtGui.QStandardItemModel()
        self.objectView = QtWidgets.QListView()
        self.objectView.setViewMode(QtWidgets.QListView.IconMode)
        self.objectView.setIconSize(QtCore.QSize(64, 64))
        self.objectView.setGridSize(QtCore.QSize(86, 86))
        self.objectView.setMovement(QtWidgets.QListView.Static)
        self.objectView.setResizeMode(QtWidgets.QListView.Adjust)
        self.objectView.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.objectView.setUniformItemSizes(True)
        self.objectView.setWordWrap(True)
        self.objectView.setModel(self._objectModel)
        self.objectView.selectionModel().selectionChanged.connect(self._updateOkButton)
        layout.addWidget(self.objectView, 1)

        # Destination slot radio group
        slotGroup = QtWidgets.QGroupBox("Import to slot")
        slotRow = QtWidgets.QHBoxLayout(slotGroup)
        slotRow.setSpacing(20)
        self._slotRadios = []
        for label in ("Slot 2", "Slot 3", "Slot 4", "First available"):
            rb = QtWidgets.QRadioButton(label)
            self._slotRadios.append(rb)
            slotRow.addWidget(rb)
        slotRow.addStretch(1)
        self._slotRadios[-1].setChecked(True)  # default: First available
        layout.addWidget(slotGroup)

        # OK / Cancel
        self._buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self._buttonBox.accepted.connect(self.accept)
        self._buttonBox.rejected.connect(self.reject)
        self._buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        layout.addWidget(self._buttonBox)

    # ── Data loading ─────────────────────────────────────────────────────────

    def _loadFolders(self):
        self.folderCombo.blockSignals(True)
        self.folderCombo.clear()
        top = misc.setting('ObjPath', '') or os.path.join(globals.user_data_path, 'Objects')
        if not top or not os.path.isdir(top):
            self.folderCombo.setEnabled(False)
            self.folderCombo.blockSignals(False)
            return
        folders = sorted(
            [f for f in os.listdir(top) if os.path.isdir(os.path.join(top, f))],
            key=_naturalKey)
        for f in folders:
            self.folderCombo.addItem(f)
        self.folderCombo.blockSignals(False)
        self._loadObjects()

    def _loadObjects(self):
        self._objectModel.clear()
        self._objectData.clear()

        top = misc.setting('ObjPath', '') or os.path.join(globals.user_data_path, 'Objects')
        folder = self.folderCombo.currentText()
        if not top or not folder:
            self._updateOkButton()
            return

        dirPath = os.path.join(top, folder)
        for label, jsonData in loadObjectFolder(dirPath):
            # Preview: use the full image sheet, scaled to fit a 64×64 icon
            imgPath = os.path.join(dirPath, jsonData["img"])
            src = QtGui.QPixmap(imgPath)
            if not src.isNull():
                scaled = src.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                icon = QtGui.QIcon(scaled)
            else:
                icon = QtGui.QIcon()

            item = QtGui.QStandardItem(icon, label)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setToolTip(label)
            self._objectModel.appendRow(item)
            self._objectData.append((jsonData, dirPath))

        self._updateOkButton()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _updateOkButton(self):
        has_selection = bool(self.objectView.selectedIndexes())
        self._buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(has_selection)

    def selectedObjects(self):
        """Return [(jsonData, dirPath), …] for every selected item, in row order."""
        rows = sorted({idx.row() for idx in self.objectView.selectedIndexes()})
        return [self._objectData[r] for r in rows if r < len(self._objectData)]

    def targetSlotIndex(self):
        """Return the chosen start slot index (1–3), or -1 for 'First available'."""
        for i, rb in enumerate(self._slotRadios[:3]):
            if rb.isChecked():
                return i + 1  # Slot 2→1, Slot 3→2, Slot 4→3
        return -1  # First available


#############################################################################################
######################## Widget for selecting the object to export ##########################

class getObjNum(QtWidgets.QDialog):
    """
    Dialog which lets you choose an object to export
    """
    def __init__(self, count):
        """
        Creates and initializes the dialog
        """
        QtWidgets.QDialog.__init__(self)
        self.setWindowTitle('Choose Object')

        self.objNum = QtWidgets.QSpinBox()
        self.objNum.setRange(0, count)
        self.objNum.setValue(0)

        buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)

        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

        mainLayout = QtWidgets.QVBoxLayout()
        mainLayout.addWidget(self.objNum)
        mainLayout.addWidget(buttonBox)

        self.setLayout(mainLayout)
