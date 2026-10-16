#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Pyamoto Level Editor
# Copyright (C) 2009-2026 Pyamoto contributors
# This file is part of Pyamoto.

# See LICENSE.txt for more information.

################################################################
################################################################

# Python version: sanity check
minimum = 3.5
import sys

currentRunningVersion = sys.version_info.major + (.1 * sys.version_info.minor)
if currentRunningVersion < minimum:
    errormsg = 'Please update your copy of Python to ' + str(minimum) + \
               ' or greater. Currently running on: ' + sys.version[:5]

    raise Exception(errormsg)

# Stdlib imports
from collections import Counter
import json
import os
import platform
import signal
import struct
import subprocess
import time
import traceback
from urllib.parse import quote, unquote

# PyQt5: import
if currentRunningVersion >= 3.10:
    pqt_min = map(int, "5.15.6".split('.'))
    pqt_min_str = '5.15.6'
else:
    pqt_min = map(int, "5.12.2".split('.'))
    pqt_min_str = '5.12.2'

from PyQt5 import QtCore, QtGui, QtWidgets
Qt = QtCore.Qt

version = map(int, QtCore.QT_VERSION_STR.split('.'))
for v, c in zip(version, pqt_min):
    if c > v:
        # lower version
        errormsg = 'Please update your copy of PyQt to ' + str(pqt_min_str) + \
                   ' or greater. Currently running on: ' + QtCore.QT_VERSION_STR

        raise Exception(errormsg) from None
    else:
        # higher version
        break

if not hasattr(QtWidgets.QGraphicsItem, 'ItemSendsGeometryChanges'):
    # enables itemChange being called on QGraphicsItem
    QtWidgets.QGraphicsItem.ItemSendsGeometryChanges = QtWidgets.QGraphicsItem.GraphicsItemFlag(0x800)

# Check if Miyamoto is being run on a supported platform
if platform.system() not in ['Windows', 'Linux', 'Darwin']:
    raise NotImplementedError("Unsupported platform: Not a supported platform, sadly...")

# Import the "globals" module
from . import globals

# Check if Cython is available
try:
    import pyximport
    pyximport.install()

    import cython_available

except:
    print("Cython is not available!")
    print("Expect Miyamoto to be very slow!\n")

else:
    del cython_available
    globals.cython_available = True

# Local imports
from .area import *
from .bytes import *
from .dialogs import *
#from firstRunWizard import Wizard <- is executed later
from .gamedefs import *
from .items import *
from .level import *
from .id_manager import CUSTOM_ID_BASE, remap_imported_course
from .loading import *
from .misc import *
from .puzzle import MainWindow as PuzzleWindow
import SarcLib
from . import spritelib as SLib
from . import sprites
from .tileset import *
from .ui import *
from . import undomanager
from .undomanager import UndoManager
from .verifications import *
from .widgets import *

from . import yaz0


# Save the original exception handler
_excepthook_original = sys.excepthook


def _excepthook(*exc_info):
    """
    Custom unhandled exceptions handler
    """
    if globals.app is None:
        return _excepthook_original(*exc_info)

    if exc_info[0] is KeyboardInterrupt:
        sys.exit(1)

    separator = '-' * 80
    logFile = "log.txt"
    notice = \
        """An unhandled exception occurred. Please report the problem """\
        """in the Zenith Discord server: https://go.nsmbu.net/discord\n"""\
        """A log will be written to "%s".\n\nIt is recommended that you restart Pyamoto immediately!"""\
        """\n\nError information:\n""" % logFile

    timeString = time.strftime("%Y-%m-%d, %H:%M:%S")

    e = "".join(traceback.format_exception(*exc_info))
    sections = [separator, timeString, separator, e]
    msg = '\n'.join(sections)

    globals.err_msg += msg

    try:
        with open(logFile, "w") as f:
            f.write(globals.err_msg)

    except IOError:
        pass

    errorbox = QtWidgets.QMessageBox()
    errorbox.setText(notice + msg)
    errorbox.exec_()

    globals.DirtyOverride = 0


# Override the exception handler with ours
sys.excepthook = _excepthook


class PropEditorStack(QtWidgets.QStackedWidget):
    """
    A QStackedWidget used inside the shared properties dock.
    Reports the active page's size hints so the dock resizes correctly when switching editors.
    """
    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w else super().sizeHint()

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w else super().minimumSizeHint()


def levelFileFilters(forSave=False):
    """
    File dialog filters for level archives. Deluxe levels are always uncompressed
    little-endian .sarc files; the Wii U game also uses Yaz0-compressed .szs.
    """
    if globals.IsNSMBUDX:
        filters = 'Level Archives (*.sarc)'
        return filters if forSave else filters + ';;All Files (*)'

    if forSave:
        return 'Compressed Level Archives (*.szs);;Uncompressed Level Archives (*.sarc)'

    return ('Level Archives (*.szs *.sarc);;Compressed Level Archives (*.szs);;'
            'Uncompressed Level Archives (*.sarc);;All Files (*)')


class MiyamotoWindow(QtWidgets.QMainWindow):
    """
    Miyamoto main level editor window
    """
    ZoomLevel = 100

    def CreateAction(self, shortname, function, icon, text, statustext, shortcut, toggle=False):
        """
        Helper function to create an action
        """

        if icon is not None:
            act = QtWidgets.QAction(icon, text, self)
        else:
            act = QtWidgets.QAction(text, self)

        if shortcut is not None:
            if isinstance(shortcut, list):
                act.setShortcuts(shortcut)
            else:
                act.setShortcut(shortcut)
        if statustext is not None: act.setStatusTip(statustext)
        if toggle: act.setCheckable(True)
        if function is not None: act.triggered.connect(function)

        self.actions[shortname] = act

    def __init__(self):
        """
        Editor window constructor
        """
        globals.Initializing = True

        globals.ObjectAddedtoEmbedded = {1: {}}
        globals.UndoManager = UndoManager()
        globals.UndoManager.stackChanged.connect(self.UpdateUndoRedoActions)

        # Miyamoto Version number goes below here. 64 char max (32 if non-ascii).
        self.MiyamotoInfo = globals.MiyamotoID

        self.ZoomLevels = [7.5, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0, 65.0, 70.0, 75.0,
                           85.0, 90.0, 95.0, 100.0, 125.0, 150.0, 175.0, 200.0, 250.0, 300.0, 350.0, 400.0]

        # required variables
        self.UpdateFlag = False
        self.SelectionUpdateFlag = False
        self.selObj = None
        self.selObjs = None
        self.CurrentSelection = []

        # set up the window
        super().__init__(None)
        _base_title = 'Pyamoto Nightly' if globals.MiyamotoReleaseType == 'nightly' else 'Pyamoto'
        self.setWindowTitle(_base_title)
        _icon_name = 'pyamoto1024mac.png' if platform.system() == 'Darwin' else 'pyamoto1024.png'
        self.setWindowIcon(QtGui.QIcon(os.path.join(globals.miyamoto_path, 'miyamotodata', 'app_icons', _icon_name)))
        self.setIconSize(QtCore.QSize(16, 16))
        self.setUnifiedTitleAndToolBarOnMac(True)

        # create the level view
        self.scene = LevelScene(0, 0, 1024 * globals.TileWidth, 512 * globals.TileWidth, self)
        self.scene.setItemIndexMethod(QtWidgets.QGraphicsScene.NoIndex)
        self.scene.selectionChanged.connect(self.ChangeSelectionHandler)

        self.view = LevelViewWidget(self.scene, self)
        self.view.centerOn(0, 0)  # this scrolls to the top left
        self.view.PositionHover.connect(self.PositionHovered)
        self.view.XScrollBar.valueChanged.connect(self.XScrollChange)
        self.view.YScrollBar.valueChanged.connect(self.YScrollChange)
        self.view.FrameSize.connect(self.HandleWindowSizeChange)

        # done creating the window!
        self.setCentralWidget(self.view)

        # set up the clipboard stuff
        self.clipboard = None
        self.systemClipboard = QtWidgets.QApplication.clipboard()
        self.systemClipboard.dataChanged.connect(self.TrackClipboardUpdates)

        # we might have something there already, activate Paste if so
        self.TrackClipboardUpdates()

        self.setAcceptDrops(True)

    def __init2__(self):
        """
        Finishes initialization. (fixes bugs with some widgets calling globals.mainWindow.something before it's fully init'ed)
        """

        try:
            self.AutosaveTimer = QtCore.QTimer()
            self.AutosaveTimer.timeout.connect(self.Autosave)
            self.AutosaveTimer.start(20000)

        except TypeError:
            pass

        # set up actions and menus
        self.SetupActionsAndMenus()

        # set up the status bar
        self.posLabel = QtWidgets.QLabel()
        self.numUsedTilesLabel = QtWidgets.QLabel()
        self.selectionLabel = QtWidgets.QLabel()
        self.hoverLabel = QtWidgets.QLabel()
        self.statusBar().addWidget(self.posLabel)
        self.statusBar().addWidget(self.numUsedTilesLabel)
        self.statusBar().addWidget(self.selectionLabel)
        self.statusBar().addWidget(self.hoverLabel)
        self.ZoomWidget = ZoomWidget()
        self.ZoomStatusWidget = ZoomStatusWidget()
        self.statusBar().addPermanentWidget(self.ZoomWidget)
        self.statusBar().addPermanentWidget(self.ZoomStatusWidget)

        # create the various panels
        self.SetupDocksAndPanels()

        # Load the most recently used game + mods (already done at startup; this is a no-op reload)
        _b = setting('LastBaseGame', 'NSMBU')
        _m = setting('LastMods') or []
        if isinstance(_m, str):
            _m = [_m]
        LoadGameDef(_b, _m)

        # Reflect whether Open Level by Name has any usable sources
        self.updateOpenByNameState()

        # now get stuff ready
        loaded = False
        _from_welcome = False

        try:
            if '-level' in sys.argv:
                index = sys.argv.index('-level')
                try:
                    fn = sys.argv[index + 1]
                    loaded = self.LoadLevel(None, fn, True, 1, True)
                except Exception:
                    pass

            elif '-newLevel' in sys.argv:
                loaded = self.LoadLevel(None, None, False, 1, True)

            elif setting('LaunchBehavior', 0) == 1 and globals.settings.contains(('LastLevel_' + globals.gamedef.name) if globals.gamedef.custom else 'LastLevel'):
                lastlevel = str(globals.gamedef.GetLastLevel())
                if os.path.isfile(lastlevel):
                    loaded = self.LoadLevel(None, lastlevel, True, 1, True)

            else:
                _from_welcome = True
                dlg = WelcomeDialog()
                dlg.exec_()
                if dlg.action is None:
                    sys.exit(0)
                elif dlg.action == WelcomeDialog.ACTION_OPEN_FILE:
                    filetypes = levelFileFilters()
                    fn = QtWidgets.QFileDialog.getOpenFileName(self, 'Choose a level archive', '', filetypes)[0]
                    if fn:
                        loaded = self.LoadLevel(None, fn, True, 1, True)
                elif dlg.action == WelcomeDialog.ACTION_OPEN_NAME:
                    nameDlg = ChooseLevelNameDialog()
                    if nameDlg.exec_() == QtWidgets.QDialog.Accepted and nameDlg.currentlevel:
                        level_name = nameDlg.currentlevel
                        game_path = (nameDlg.current_game_path or '').strip()
                        display_name = nameDlg.current_display_name or level_name
                        tab_name = nameDlg.current_tab_name or ''
                        recent_label = f'{display_name} ({tab_name})' if tab_name else display_name
                        if game_path:
                            for ext in globals.FileExtentions:
                                full = os.path.join(game_path, level_name + ext)
                                if os.path.isfile(full):
                                    loaded = self.LoadLevel(None, full, True, 1, True)
                                    self.RecentMenu.AddToList(full, recent_label)
                                    break
                        else:
                            loaded = self.LoadLevel(None, level_name, False, 1, True)
                            self.RecentMenu.AddToList(level_name, recent_label)
                elif dlg.action == WelcomeDialog.ACTION_NEW_LEVEL:
                    loaded = self.LoadLevel(None, None, False, 1, True)
                elif dlg.action == WelcomeDialog.ACTION_OPEN_RECENT:
                    if dlg.recent_path:
                        loaded = self.LoadLevel(None, dlg.recent_path, True, 1, True)

            if not loaded:
                if _from_welcome:
                    sys.exit(0)
                else:
                    self.LoadLevel(None, None, False, 1, True)

        except Exception:
            globals.DirtyOverride = 0
            self.LoadLevel(None, None, False, 1, True)

        QtCore.QTimer.singleShot(100, self.levelOverview.update)

        toggleHandlers = {
            self.HandleSpritesVisibility: globals.SpritesShown,
            self.HandleSpriteImages: globals.SpriteImagesShown,
            self.HandleRotationPreview: globals.RotationShown,
            self.HandleLocationsVisibility: globals.LocationsShown,
            self.HandleCommentsVisibility: globals.CommentsShown,
            self.HandlePathsVisibility: globals.PathsShown,
        }
        for handler in toggleHandlers:
            handler(
                toggleHandlers[handler])  # call each toggle-button handler to set each feature correctly upon startup

        globals.Initializing = False

        # Restore geometry after show() so macOS window manager doesn't override it.
        QtCore.QTimer.singleShot(0, self._restoreWindowState)

    def _restoreWindowState(self):
        if globals.settings.contains('MainWindowGeometry'):
            self.restoreGeometry(setting('MainWindowGeometry'))
        if globals.settings.contains('MainWindowState'):
            self.restoreState(setting('MainWindowState'), 0)

    def SetupActionsAndMenus(self):
        """
        Sets up Miyamoto's actions, menus and toolbars
        """
        self.RecentMenu = RecentFilesMenu()

        self.createMenubar()

    actions = {}

    def createMenubar(self):
        """
        Create actions, a menubar and a toolbar
        """

        # File
        self.CreateAction(
            'newlevel', self.HandleNewLevel, GetIcon('new'),
            'New Level',
            'Create a new, blank level',
            QtGui.QKeySequence.New,
        )

        self.CreateAction(
            'openfromname', self.HandleOpenFromName, GetIcon('open'),
            'Open Level by Name...',
            'Open a level based on its in-game world/number',
            QtGui.QKeySequence.Open,
        )

        self.CreateAction(
            'openfromfile', self.HandleOpenFromFile, GetIcon('openfromfile'),
            'Open Level by File...',
            'Open a level based on its filename',
            QtGui.QKeySequence('Ctrl+Shift+O'),
        )

        self.CreateAction(
            'openrecent', None, GetIcon('recent'),
            'Recent Files',
            'Open a level from a list of recently opened levels',
            None,
        )

        self.CreateAction(
            'save', self.HandleSave, GetIcon('save'),
            'Save Level',
            'Save the level back to the archive file',
            QtGui.QKeySequence.Save,
        )

        self.CreateAction(
            'saveas', self.HandleSaveAs, GetIcon('saveas'),
            'Export Level As...',
            'Export the level with a new filename',
            QtGui.QKeySequence.SaveAs,
        )

        self.CreateAction(
            'metainfo', self.HandleInfo, GetIcon('info'),
            'Level Information...',
            "Add title and author information to the level's metadata",
            QtGui.QKeySequence('Ctrl+Alt+I'),
        )

        self.CreateAction(
            'screenshot', self.HandleScreenshot, GetIcon('screenshot'),
            'Level Screenshot...',
            'Take a full size screenshot of your level for you to share',
            QtGui.QKeySequence('Ctrl+Alt+S'),
        )

        self.CreateAction(
            'showdatafolder', self.HandleShowDataFolder, GetIcon('open'),
            "Show Pyamoto Data Folder",
            "Opens the Pyamoto user data folder in the system file manager.",
            None,
        )

        self.CreateAction(
            'interactivesetup', self.HandleInteractiveSetup, GetIcon('animation'),
            "Interactive Setup…",
            "Re-run the interactive setup wizard to download resources, set game path, or change theme.",
            None,
        )

        self.CreateAction(
            'preferences', self.HandlePreferences, GetIcon('settings'),
            'Pyamoto Preferences...',
            'Change important Pyamoto settings',
            QtGui.QKeySequence('Ctrl+Alt+P'),
        )

        self.CreateAction(
            'exit', self.HandleExit, GetIcon('delete'),
            'Exit Pyamoto',
            'Exit the editor',
            QtGui.QKeySequence.Quit,
        )

        # Edit
        self.CreateAction(
            'selectall', self.SelectAll, GetIcon('select'),
            'Select All',
            'Select all items in this area',
            QtGui.QKeySequence.SelectAll,
        )

        self.CreateAction(
            'deselect', self.Deselect, GetIcon('deselect'),
            'Deselect',
            'Deselect all currently selected items',
            QtGui.QKeySequence('Esc'),
        )

        self.CreateAction(
            'undo', self.HandleUndo, GetIcon('undo'),
            'Undo',
            'Undo the last action',
            QtGui.QKeySequence.Undo,
        )

        self.CreateAction(
            'redo', self.HandleRedo, GetIcon('redo'),
            'Redo',
            'Redo the last undone action',
            [QtGui.QKeySequence.Redo, QtGui.QKeySequence('Ctrl+Shift+Z')],
        )

        self.CreateAction(
            'cut', self.Cut, GetIcon('cut'),
            'Cut',
            'Cut out the current selection to the clipboard',
            QtGui.QKeySequence.Cut,
        )

        self.CreateAction(
            'copy', self.Copy, GetIcon('copy'),
            'Copy',
            'Copy the current selection to the clipboard',
            QtGui.QKeySequence.Copy,
        )

        self.CreateAction(
            'paste', self.Paste, GetIcon('paste'),
            'Paste',
            'Paste items from the clipboard',
            QtGui.QKeySequence.Paste,
        )

        self.CreateAction(
            'duplicate', self.HandleDuplicate, GetIcon('copy'),
            'Duplicate',
            'Duplicate the selected items in place',
            QtGui.QKeySequence('Ctrl+D'),
        )

        self.CreateAction(
            'raise', self.HandleRaiseObjects, GetIcon('raise'),
            'Raise to Top',
            'Raise selected objects to the front of all other objects in the scene.',
            None,
        )

        self.CreateAction(
            'lower', self.HandleLowerObjects, GetIcon('lower'),
            'Lower to Bottom',
            'Lower selected objects behind all other objects in the scene.',
            None,
        )

        self.CreateAction(
            'shiftitems', self.ShiftItems, GetIcon('move'),
            'Shift Items...',
            'Move all selected items by an offset',
            QtGui.QKeySequence('Ctrl+Shift+S'),
        )

        self.CreateAction(
            'mergelocations', self.MergeLocations, GetIcon('merge'),
            'Merge Locations',
            'Merge selected locations into a single large location',
            QtGui.QKeySequence('Ctrl+Shift+E'),
        )

        self.CreateAction(
            'swapobjectstilesets', self.SwapObjectsTilesets, GetIcon('swap'),
            "Swap Objects' Tileset",
            'Swaps the tileset of objects using a certain tileset',
            QtGui.QKeySequence('Ctrl+Shift+L'),
        )

        self.CreateAction(
            'swapobjectstypes', self.SwapObjectsTypes, GetIcon('swap'),
            "Swap Objects' Type",
            'Swaps the type of objects of a certain type',
            QtGui.QKeySequence('Ctrl+Shift+Y'),
        )

        self.CreateAction(
            'freezeobjects', self.HandleObjectsFreeze, GetIcon('objectsfreeze'),
            'Freeze\nObjects',
            'Make objects non-selectable',
            QtGui.QKeySequence('Ctrl+Shift+1'), True,
        )

        self.CreateAction(
            'freezesprites', self.HandleSpritesFreeze, GetIcon('spritesfreeze'),
            'Freeze\nActors',
            'Make actors non-selectable',
            QtGui.QKeySequence('Ctrl+Shift+2'), True,
        )

        self.CreateAction(
            'freezeentrances', self.HandleEntrancesFreeze, GetIcon('entrancesfreeze'),
            'Freeze Entrances',
            'Make entrances non-selectable',
            QtGui.QKeySequence('Ctrl+Shift+3'), True,
        )

        self.CreateAction(
            'freezelocations', self.HandleLocationsFreeze, GetIcon('locationsfreeze'),
            'Freeze\nLocations',
            'Make locations non-selectable',
            QtGui.QKeySequence('Ctrl+Shift+4'), True,
        )

        self.CreateAction(
            'freezepaths', self.HandlePathsFreeze, GetIcon('pathsfreeze'),
            'Freeze Paths',
            'Make paths non-selectable',
            QtGui.QKeySequence('Ctrl+Shift+5'), True,
        )

        self.CreateAction(
            'freezecomments', self.HandleCommentsFreeze, GetIcon('commentsfreeze'),
            'Freeze Comments',
            'Make comments non-selectable',
            QtGui.QKeySequence('Ctrl+Shift+9'), True,
        )

        # View
        self.CreateAction(
            'showlay0', self.HandleUpdateLayer0, GetIcon('layer0'),
            'Layer 0',
            'Toggle viewing of object layer 0',
            QtGui.QKeySequence('Ctrl+1'), True,
        )

        self.CreateAction(
            'showlay1', self.HandleUpdateLayer1, GetIcon('layer1'),
            'Layer 1',
            'Toggle viewing of object layer 1',
            QtGui.QKeySequence('Ctrl+2'), True,
        )

        self.CreateAction(
            'showlay2', self.HandleUpdateLayer2, GetIcon('layer2'),
            'Layer 2',
            'Toggle viewing of object layer 2',
            QtGui.QKeySequence('Ctrl+3'), True,
        )

        self.CreateAction(
            'tileanim', self.HandleTilesetAnimToggle, GetIcon('animation'),
            'Tileset Animations',
            'Play tileset animations if they exist (may cause a slowdown)',
            QtGui.QKeySequence('Ctrl+7'), True,
        )

        self.CreateAction(
            'collisions', self.HandleCollisionsToggle, GetIcon('collisions'),
            'Tileset Collisions',
            'View tileset collisions for existing objects',
            QtGui.QKeySequence('Ctrl+8'), True,
        )

        self.CreateAction(
            'realview', self.HandleRealViewToggle, GetIcon('realview'),
            'Real View',
            'Show special effects present in the level',
            QtGui.QKeySequence('Ctrl+9'), True,
        )

        self.CreateAction(
            'showsprites', self.HandleSpritesVisibility, GetIcon('sprites'),
            'Show Actors',
            'Toggle viewing of actors',
            QtGui.QKeySequence('Ctrl+4'), True,
        )

        self.CreateAction(
            'showspriteimages', self.HandleSpriteImages, GetIcon('sprites'),
            'Show Actor Images',
            'Toggle viewing of actor images',
            QtGui.QKeySequence('Ctrl+6'), True,
        )

        self.CreateAction(
            'showrotation', self.HandleRotationPreview, GetIcon('rotation'),
            'Preview Pivotal Rotation',
            'Toggle previewing of pivotal rotation with actor images',
            QtGui.QKeySequence('Ctrl+R'), True,
        )

        self.CreateAction(
            'showlocations', self.HandleLocationsVisibility, GetIcon('locations'),
            'Show Locations',
            'Toggle viewing of locations',
            QtGui.QKeySequence('Ctrl+5'), True,
        )

        self.CreateAction(
            'showcomments', self.HandleCommentsVisibility, GetIcon('comments'),
            'Show Comments',
            'Toggle viewing of comments',
            QtGui.QKeySequence('Ctrl+0'), True,
        )

        self.CreateAction(
            'showpaths', self.HandlePathsVisibility, GetIcon('paths'),
            'Show Paths',
            'Toggle viewing of paths',
            QtGui.QKeySequence('Ctrl+*'), True,
        )

        self.CreateAction(
            'fullscreen', self.HandleFullscreen, GetIcon('fullscreen'),
            'Show Fullscreen',
            'Display the main window with all available screen space',
            QtGui.QKeySequence('Ctrl+U'), True,
        )

        self.CreateAction(
            'grid', self.HandleSwitchGrid, GetIcon('grid'),
            'Switch\nGrid',
            'Cycle through available grid views',
            QtGui.QKeySequence('Ctrl+G'),
        )

        self.CreateAction(
            'zoommax', self.HandleZoomMax, GetIcon('zoommax'),
            'Zoom to Maximum',
            'Zoom in all the way',
            QtGui.QKeySequence('Ctrl+PgDown'),
        )

        self.CreateAction(
            'zoomin', self.HandleZoomIn, GetIcon('zoomin'),
            'Zoom In',
            'Zoom into the main level view',
            QtGui.QKeySequence.ZoomIn,
        )

        self.CreateAction(
            'zoomactual', self.HandleZoomActual, GetIcon('zoomactual'),
            'Zoom 100%',
            'Show the level at the default zoom',
            QtGui.QKeySequence('Ctrl+0'),
        )

        self.CreateAction(
            'zoomout', self.HandleZoomOut, GetIcon('zoomout'),
            'Zoom Out',
            'Zoom out of the main level view',
            QtGui.QKeySequence.ZoomOut,
        )

        self.CreateAction(
            'zoommin', self.HandleZoomMin, GetIcon('zoommin'),
            'Zoom to Minimum',
            'Zoom out all the way',
            QtGui.QKeySequence('Ctrl+PgUp'),
        )

        # Show Overview and Show Palette are added later

        # Settings
        self.CreateAction(
            'areaoptions', self.HandleAreaOptions, GetIcon('area'),
            'Area\nSettings...',
            'Control tileset swapping, stage timer, entrance on load, and stage wrap',
            QtGui.QKeySequence('Ctrl+Alt+A'),
        )

        self.CreateAction(
            'zones', self.HandleZones, GetIcon('zones'),
            'Zone\nSettings...',
            'Zone creation, deletion, and preference editing',
            QtGui.QKeySequence('Ctrl+Alt+Z'),
        )

        self.CreateAction(
            'addarea', self.HandleAddNewArea, GetIcon('add'),
            'Add New Area',
            'Add a new area (sublevel) to this level',
            QtGui.QKeySequence('Ctrl+Alt+N'),
        )

        self.CreateAction(
            'importarea', self.HandleImportArea, GetIcon('import'),
            'Import Area from Level...',
            'Import an area (sublevel) from another level file',
            QtGui.QKeySequence('Ctrl+Alt+O'),
        )

        self.CreateAction(
            'deletearea', self.HandleDeleteArea, GetIcon('delete'),
            'Delete Current Area...',
            'Delete the area (sublevel) currently open from the level',
            QtGui.QKeySequence('Ctrl+Alt+D'),
        )

        self.CreateAction(
            'reloaddata', self.ReloadSpriteData, GetIcon('reload'),
            'Reload Actor Data',
            'Reload the actor data without restarting the editor',
            QtGui.QKeySequence('Ctrl+Shift+R'),
        )


        self.CreateAction(
            'viewspritemap', self.HandleViewSpritemap, GetIcon('folderpath'),
            "View Spritemap", "NBYTE",
            None
        )

        self.CreateAction(
            'edittilesets', self.EditTilesets, GetIcon('animation'),
            "Edit Tilesets",
            "Opens the merged tileset editor for all slots.",
            None,
        )

        # Help actions are created later

        # Help actions are created later

        # Configure them
        self.actions['openrecent'].setMenu(self.RecentMenu)

        self.actions['collisions'].setChecked(globals.CollisionsShown)
        self.actions['realview'].setChecked(globals.RealViewEnabled)

        self.actions['showsprites'].setChecked(globals.SpritesShown)
        self.actions['showspriteimages'].setChecked(globals.SpriteImagesShown)
        self.actions['showrotation'].setChecked(globals.RotationShown)
        self.actions['showlocations'].setChecked(globals.LocationsShown)
        self.actions['showcomments'].setChecked(globals.CommentsShown)
        self.actions['showpaths'].setChecked(globals.PathsShown)

        self.actions['freezeobjects'].setChecked(globals.ObjectsFrozen)
        self.actions['freezesprites'].setChecked(globals.SpritesFrozen)
        self.actions['freezeentrances'].setChecked(globals.EntrancesFrozen)
        self.actions['freezelocations'].setChecked(globals.LocationsFrozen)
        self.actions['freezepaths'].setChecked(globals.PathsFrozen)
        self.actions['freezecomments'].setChecked(globals.CommentsFrozen)

        self.actions['undo'].setEnabled(False)
        self.actions['redo'].setEnabled(False)
        self.actions['cut'].setEnabled(False)
        self.actions['copy'].setEnabled(False)
        self.actions['paste'].setEnabled(False)
        self.actions['shiftitems'].setEnabled(False)
        self.actions['mergelocations'].setEnabled(False)
        self.actions['deselect'].setEnabled(False)

        menubar = QtWidgets.QMenuBar()
        self.setMenuBar(menubar)

        fmenu = menubar.addMenu('&File')
        fmenu.addAction(self.actions['newlevel'])
        fmenu.addAction(self.actions['openfromname'])
        fmenu.addAction(self.actions['openfromfile'])
        fmenu.addAction(self.actions['openrecent'])
        fmenu.addSeparator()
        fmenu.addAction(self.actions['save'])
        fmenu.addAction(self.actions['saveas'])
        fmenu.addAction(self.actions['metainfo'])
        fmenu.addSeparator()
        fmenu.addAction(self.actions['screenshot'])
        fmenu.addAction(self.actions['showdatafolder'])
        fmenu.addAction(self.actions['interactivesetup'])
        fmenu.addAction(self.actions['preferences'])
        fmenu.addSeparator()
        fmenu.addAction(self.actions['exit'])

        emenu = menubar.addMenu('&Edit')
        emenu.addAction(self.actions['undo'])
        emenu.addAction(self.actions['redo'])
        emenu.addSeparator()
        emenu.addAction(self.actions['selectall'])
        emenu.addAction(self.actions['deselect'])
        emenu.addSeparator()
        emenu.addAction(self.actions['cut'])
        emenu.addAction(self.actions['copy'])
        emenu.addAction(self.actions['paste'])
        emenu.addAction(self.actions['duplicate'])
        emenu.addSeparator()
        emenu.addAction(self.actions['raise'])
        emenu.addAction(self.actions['lower'])
        emenu.addSeparator()
        emenu.addAction(self.actions['shiftitems'])
        emenu.addAction(self.actions['mergelocations'])
        emenu.addAction(self.actions['swapobjectstilesets'])
        emenu.addAction(self.actions['swapobjectstypes'])
        emenu.addSeparator()
        emenu.addAction(self.actions['freezeobjects'])
        emenu.addAction(self.actions['freezesprites'])
        emenu.addAction(self.actions['freezeentrances'])
        emenu.addAction(self.actions['freezelocations'])
        emenu.addAction(self.actions['freezepaths'])
        emenu.addAction(self.actions['freezecomments'])

        vmenu = menubar.addMenu('&View')
        vmenu.addAction(self.actions['showlay0'])
        vmenu.addAction(self.actions['showlay1'])
        vmenu.addAction(self.actions['showlay2'])
        vmenu.addAction(self.actions['tileanim'])
        vmenu.addAction(self.actions['collisions'])
        vmenu.addAction(self.actions['realview'])
        vmenu.addSeparator()
        vmenu.addAction(self.actions['showsprites'])
        vmenu.addAction(self.actions['showspriteimages'])
        vmenu.addAction(self.actions['showrotation'])
        vmenu.addAction(self.actions['showlocations'])
        vmenu.addAction(self.actions['showcomments'])
        vmenu.addAction(self.actions['showpaths'])
        vmenu.addSeparator()
        vmenu.addAction(self.actions['fullscreen'])
        vmenu.addAction(self.actions['grid'])
        vmenu.addSeparator()
        vmenu.addAction(self.actions['zoommax'])
        vmenu.addAction(self.actions['zoomin'])
        vmenu.addAction(self.actions['zoomactual'])
        vmenu.addAction(self.actions['zoomout'])
        vmenu.addAction(self.actions['zoommin'])
        vmenu.addSeparator()
        # self.levelOverviewDock.toggleViewAction() is added here later
        # so we assign it to self.vmenu
        self.vmenu = vmenu

        lmenu = menubar.addMenu('&Area')
        lmenu.addAction(self.actions['areaoptions'])
        lmenu.addAction(self.actions['zones'])
        lmenu.addSeparator()
        lmenu.addAction(self.actions['addarea'])
        lmenu.addAction(self.actions['importarea'])
        lmenu.addAction(self.actions['deletearea'])
        lmenu.addSeparator()
        lmenu.addAction(self.actions['reloaddata'])
        lmenu.addAction(self.actions['viewspritemap'])
        lmenu.addAction(self.actions['edittilesets'])

        hmenu = menubar.addMenu('&Help')
        self.SetupHelpMenu(hmenu)

        # create a toolbar
        self.toolbar = self.addToolBar('Editor Toolbar')
        self.toolbar.setObjectName('MainToolbar')

        # Add buttons to the toolbar
        self.addToolbarButtons()

        # Add the area combo box
        self.areaComboBox = QtWidgets.QComboBox()
        self.areaComboBox.activated.connect(self.HandleSwitchArea)
        self.toolbar.addWidget(self.areaComboBox)

    def SetupHelpMenu(self, menu=None):
        """
        Creates the help menu. This is separate because both the menubar uses this
        """
        self.CreateAction('infobox', self.AboutBox, GetIcon('help'), 'About Pyamoto',
                          'Info about the program, and the team behind it', QtGui.QKeySequence('Ctrl+Shift+I'))
        self.CreateAction('wiki', self.OpenWiki, GetIcon('contents'), 'Wiki',
                          'Open the Zenith wiki in your browser', QtGui.QKeySequence('Ctrl+Shift+H'))
        self.CreateAction('aboutqt', QtWidgets.qApp.aboutQt, GetIcon('qt'), 'About PyQt...',
                          'About the Qt library Pyamoto is based on', QtGui.QKeySequence('Ctrl+Shift+Q'))

        # On macOS, Qt auto-moves actions with "About" in their text to the Application menu.
        self.actions['infobox'].setMenuRole(QtWidgets.QAction.NoRole)
        self.actions['aboutqt'].setMenuRole(QtWidgets.QAction.NoRole)

        if menu is None:
            menu = QtWidgets.QMenu('&Help')
        menu.addAction(self.actions['infobox'])
        menu.addAction(self.actions['wiki'])
        menu.addSeparator()
        menu.addAction(self.actions['aboutqt'])
        return menu

    def addToolbarButtons(self):
        """
        Reads from the Preferences file and adds the appropriate options to the toolbar
        """
        # First, define groups. Each group is isolated by separators.
        Groups = (
            (
                'newlevel',
                'openfromname',
                'openfromfile',
                'openrecent',
                'save',
                'saveas',
                'metainfo',
                'screenshot',
                'interactivesetup',
                'preferences',
                'exit',
            ), (
                'undo',
                'redo',
            ), (
                'selectall',
                'deselect',
            ), (
                'cut',
                'copy',
                'paste',
            ), (
                'raise',
                'lower',
            ), (
                'shiftitems',
                'mergelocations',
            ), (
                'freezeobjects',
                'freezesprites',
                'freezeentrances',
                'freezelocations',
                'freezepaths',
            ), (
                'zoommax',
                'zoomin',
                'zoomactual',
                'zoomout',
                'zoommin',
            ), (
                'grid',
            ), (
                'showlay0',
                'showlay1',
                'showlay2',
            ), (
                'showsprites',
                'showspriteimages',
                'showrotation',
                'showlocations',
                'showpaths',
            ), (
                'areaoptions',
                'zones',
            ), (
                'addarea',
                'importarea',
                'deletearea',
            ), (
                'reloaddata',
            ), (
                'infobox',
                'wiki',
                'aboutqt',
            ),
        )

        # Determine which keys are activated
        if setting('ToolbarActs') is None:
            # Get the default settings
            toggled = {}
            for List in (globals.FileActions, globals.EditActions, globals.ViewActions, globals.SettingsActions, globals.SpritedataActions, globals.HelpActions):
                for name, activated, key in List:
                    toggled[key] = activated
        else:  # Get the registry settings
            toggled = setting('ToolbarActs')
            newToggled = {}  # here, I'm replacing QStrings w/ python strings
            for key in toggled:
                newToggled[str(key)] = toggled[key]
            toggled = newToggled

        # Add each to the toolbar if toggled[key]
        for group in Groups:
            addedButtons = False
            for key in group:
                if key in toggled and toggled[key]:
                    act = self.actions[key]
                    self.toolbar.addAction(act)
                    addedButtons = True
            if addedButtons:
                self.toolbar.addSeparator()


    def SetupDocksAndPanels(self):
        """
        Sets up the dock widgets and panels
        """
        # level overview
        dock = QtWidgets.QDockWidget('Level Overview', self)
        dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFloatable | QtWidgets.QDockWidget.DockWidgetClosable)
        # dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        dock.setObjectName('leveloverview')  # needed for the state to save/restore correctly

        self.levelOverview = LevelOverviewWidget()
        self.levelOverview.moveIt.connect(self.HandleOverviewClick)
        self.levelOverviewDock = dock
        dock.setWidget(self.levelOverview)

        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        dock.setVisible(True)
        act = dock.toggleViewAction()
        act.setShortcut(QtGui.QKeySequence('Ctrl+M'))
        act.setIcon(GetIcon('overview'))
        act.setStatusTip('Show or hide the Level Overview window')
        self.vmenu.addAction(act)


        # All "Selected X Properties" editors share a single dock so they remember
        # one position. PropEditorStack swaps the active editor; the dock title
        # updates to match the current type.
        self.propEditorStack = PropEditorStack()

        self.spriteDataEditor = SpriteEditorWidget()
        self.spriteDataEditor.DataUpdate.connect(self.SpriteDataUpdated)
        self.propEditorStack.addWidget(self.spriteDataEditor)

        self.entranceEditor = EntranceEditorWidget()
        self.propEditorStack.addWidget(self.entranceEditor)

        self.pathEditor = PathNodeEditorWidget()
        self.propEditorStack.addWidget(self.pathEditor)

        self.nabbitPathEditor = NabbitPathNodeEditorWidget()
        self.propEditorStack.addWidget(self.nabbitPathEditor)

        self.locationEditor = LocationEditorWidget()
        self.propEditorStack.addWidget(self.locationEditor)

        dock = QtWidgets.QDockWidget('Selected Actor Properties', self)
        dock.setFocusPolicy(Qt.NoFocus)
        dock.setAttribute(Qt.WA_ShowWithoutActivating)
        dock.setVisible(False)
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFloatable)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        dock.setObjectName('propeditor')  # needed for the state to save/restore correctly
        dock.setWidget(self.propEditorStack)
        self.propEditorDock = dock
        self._propEditorWidth = 400
        self._propEditorPos = None  # remembered top-left (content area) of floating dock
        dock.setMinimumWidth(200)
        dock.setMinimumHeight(0)
        dock.topLevelChanged.connect(self._onPropEditorTopLevelChanged)
        dock.installEventFilter(self)

        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        dock.setFloating(True)

        # create the palette
        dock = QtWidgets.QDockWidget('Palette', self)
        dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFloatable | QtWidgets.QDockWidget.DockWidgetClosable)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        dock.setObjectName('palette')  # needed for the state to save/restore correctly

        self.creationDock = dock
        act = dock.toggleViewAction()
        act.setShortcut(QtGui.QKeySequence('Ctrl+P'))
        act.setIcon(GetIcon('palette'))
        act.setStatusTip('Show or hide the Palette window')
        self.vmenu.addAction(act)

        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        dock.setVisible(True)

        # add tabs to it
        tabs = QtWidgets.QTabWidget()
        tabs.setTabBar(IconsOnlyTabBar())
        tabs.setIconSize(QtCore.QSize(16, 16))
        tabs.currentChanged.connect(self.CreationTabChanged)
        dock.setWidget(tabs)
        self.creationTabs = tabs

        # object choosing tabs
        tsicon = GetIcon('objects')

        self.objAllTab = QtWidgets.QTabWidget()
        self.objAllTab.currentChanged.connect(self.ObjTabChanged)

        tilesContainer = QtWidgets.QWidget()
        tilesLayout = QtWidgets.QVBoxLayout(tilesContainer)
        tilesLayout.setContentsMargins(0, 0, 0, 0)
        tilesLayout.setSpacing(2)

        self.objUseLayer0 = QtWidgets.QRadioButton('0')
        self.objUseLayer0.setToolTip('<b>Layer 0:</b><br>This layer is mostly used for hidden caves, but can also be used to overlay tiles to create effects. The flashlight effect will occur if Mario walks behind a tile on layer 0 and the zone has it enabled.<br><b>Note:</b> To switch objects on other layers to this layer, select them and then click this button while holding down the <i>Alt</i> key.')
        self.objUseLayer1 = QtWidgets.QRadioButton('1')
        self.objUseLayer1.setToolTip('<b>Layer 1:</b><br>All or most of your normal level objects should be placed on this layer. This is the only layer where tile interactions (solids, slopes, etc) will work.<br><b>Note:</b> To switch objects on other layers to this layer, select them and then click this button while holding down the <i>Alt</i> key.')
        self.objUseLayer2 = QtWidgets.QRadioButton('2')
        self.objUseLayer2.setToolTip('<b>Layer 2:</b><br>Background/wall tiles (such as those in the hidden caves) should be placed on this layer. Tiles on layer 2 have no effect on collisions.<br><b>Note:</b> To switch objects on other layers to this layer, select them and then click this button while holding down the <i>Alt</i> key.')
        setLayerBtn = QtWidgets.QPushButton('Set to Layer')
        setLayerBtn.setToolTip('Move all selected objects to the current paint layer.')
        setLayerBtn.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        setLayerBtn.clicked.connect(lambda: self.MoveSelectedToLayer(globals.CurrentLayer))

        topRow = QtWidgets.QHBoxLayout()
        topRow.setContentsMargins(6, 4, 6, 4)
        topRow.addWidget(QtWidgets.QLabel('Paint on Layer:'))
        topRow.addWidget(self.objUseLayer0)
        topRow.addWidget(self.objUseLayer1)
        topRow.addWidget(self.objUseLayer2)
        topRow.addStretch(1)
        topRow.addWidget(setLayerBtn)
        tilesLayout.addLayout(topRow)
        tilesLayout.addWidget(self.objAllTab)

        _btn_w = 140
        self.editTilesetsBtn = QtWidgets.QPushButton('Edit Tilesets')
        self.editTilesetsBtn.setFixedWidth(_btn_w)
        self.editTilesetsBtn.clicked.connect(self.actions['edittilesets'].trigger)

        self.importObjectsBtn = QtWidgets.QPushButton('Import Objects')
        self.importObjectsBtn.setFixedWidth(_btn_w)
        self.importObjectsBtn.clicked.connect(self.HandleImportObjects)

        objBtnRow = QtWidgets.QHBoxLayout()
        objBtnRow.setContentsMargins(6, 2, 6, 4)
        objBtnRow.addStretch(1)
        objBtnRow.addWidget(self.editTilesetsBtn)
        objBtnRow.addWidget(self.importObjectsBtn)
        objBtnRow.addStretch(1)
        tilesLayout.addLayout(objBtnRow)

        tabs.addTab(tilesContainer, tsicon, '')
        tabs.setTabToolTip(0, 'Objects')

        self.objTS0Tab = QtWidgets.QWidget()
        self.objTS123Tab = EmbeddedTab()
        self.objAllTab.addTab(self.objTS0Tab, tsicon, 'Main')
        self.objAllTab.addTab(self.objTS123Tab, tsicon, 'Local')

        oel = QtWidgets.QVBoxLayout(self.objTS0Tab)
        self.createObjectLayout = oel

        lbg = QtWidgets.QButtonGroup(self)
        lbg.addButton(self.objUseLayer0, 0)
        lbg.addButton(self.objUseLayer1, 1)
        lbg.addButton(self.objUseLayer2, 2)
        lbg.buttonClicked[int].connect(self.LayerChoiceChanged)
        self.LayerButtonGroup = lbg

        self.objPicker = ObjectPickerWidget()
        self.objPicker.ObjChanged.connect(self.ObjectChoiceChanged)
        self.objPicker.ObjReplace.connect(self.ObjectReplace)
        oel.addWidget(self.objPicker, 1)

        # sprite tab
        self.sprAllTab = QtWidgets.QTabWidget()
        self.sprAllTab.currentChanged.connect(self.SprTabChanged)
        tabs.addTab(self.sprAllTab, GetIcon('sprites'), '')
        tabs.setTabToolTip(1, 'Actors')

        # sprite tab: add
        self.sprPickerTab = QtWidgets.QWidget()
        self.sprAllTab.addTab(self.sprPickerTab, GetIcon('spritesadd'), 'Add')

        spl = QtWidgets.QVBoxLayout(self.sprPickerTab)
        self.sprPickerLayout = spl

        addLabel = QtWidgets.QLabel('Add new actors to this area')
        addLabel.setWordWrap(True)
        spl.addWidget(addLabel)

        svpl = QtWidgets.QHBoxLayout()
        svpl.addWidget(QtWidgets.QLabel('View:'))

        sspl = QtWidgets.QHBoxLayout()
        sspl.addWidget(QtWidgets.QLabel('Search:'))

        LoadSpriteCategories()
        viewpicker = QtWidgets.QComboBox()
        for view in globals.SpriteCategories:
            viewpicker.addItem(view[0])
        viewpicker.currentIndexChanged.connect(self.SelectNewSpriteView)

        self.spriteViewPicker = viewpicker
        svpl.addWidget(viewpicker, 1)

        self.spriteSearchTerm = QtWidgets.QLineEdit()
        self.spriteSearchTerm.textChanged.connect(self.NewSearchTerm)
        sspl.addWidget(self.spriteSearchTerm, 1)

        spl.addLayout(svpl)
        spl.addLayout(sspl)

        self.spriteSearchLayout = sspl

        self.sprPicker = SpritePickerWidget()
        self.sprPicker.SpriteChanged.connect(self.SpriteChoiceChanged)
        self.sprPicker.SpriteReplace.connect(self.SpriteReplace)
        self.sprPicker.SwitchView(globals.SpriteCategories[0])
        spl.addWidget(self.sprPicker, 1)

        self.defaultPropButton = QtWidgets.QPushButton('Set Default Properties')
        self.defaultPropButton.setEnabled(False)
        self.defaultPropButton.clicked.connect(self.ShowDefaultProps)

        sdpl = QtWidgets.QHBoxLayout()
        sdpl.addStretch(1)
        sdpl.addWidget(self.defaultPropButton)
        sdpl.addStretch(1)
        spl.addLayout(sdpl)

        # default sprite data editor
        ddock = QtWidgets.QDockWidget('Default Properties', self)
        ddock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFloatable | QtWidgets.QDockWidget.DockWidgetClosable)
        ddock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        ddock.setObjectName('defaultprops')  # needed for the state to save/restore correctly

        self.defaultDataEditor = SpriteEditorWidget(True)
        self.defaultDataEditor.setVisible(False)
        ddock.setWidget(self.defaultDataEditor)

        self.addDockWidget(Qt.RightDockWidgetArea, ddock)
        ddock.setVisible(False)
        ddock.setFloating(True)
        self.defaultPropDock = ddock

        # sprite tab: current
        self.sprEditorTab = QtWidgets.QWidget()
        self.sprAllTab.addTab(self.sprEditorTab, GetIcon('spritelist'), 'Current')

        spel = QtWidgets.QVBoxLayout(self.sprEditorTab)
        self.sprEditorLayout = spel

        slabel = QtWidgets.QLabel('Actors currently in this area<br>(Double-click one to jump to it instantly, hover for preview)')
        slabel.setWordWrap(True)
        self.spriteList = ListWidgetWithToolTipSignal()
        self.spriteList.setItemDelegate(SpriteListItemDelegate(self.spriteList))
        self.spriteList.itemActivated.connect(self.HandleSpriteSelectByList)
        self.spriteList.toolTipAboutToShow.connect(self.HandleSpriteToolTipAboutToShow)
        self.spriteList.setSortingEnabled(True)

        scurrentSearchLayout = QtWidgets.QHBoxLayout()
        scurrentSearchLayout.addWidget(QtWidgets.QLabel('Search:'))
        self.sprCurrentSearch = QtWidgets.QLineEdit()
        self.sprCurrentSearch.textChanged.connect(self.NewCurrentSearchTerm)
        scurrentSearchLayout.addWidget(self.sprCurrentSearch, 1)

        spel.addWidget(slabel)
        spel.addLayout(scurrentSearchLayout)
        spel.addWidget(self.spriteList)

        # entrance tab
        self.entEditorTab = QtWidgets.QWidget()
        tabs.addTab(self.entEditorTab, GetIcon('entrances'), '')
        tabs.setTabToolTip(2, 'Entrances')

        eel = QtWidgets.QVBoxLayout(self.entEditorTab)
        self.entEditorLayout = eel

        elabel = QtWidgets.QLabel('Entrances currently in this area<br>(Double-click one to jump to it instantly, hover for preview)')
        elabel.setWordWrap(True)
        self.entranceList = ListWidgetWithToolTipSignal()
        self.entranceList.itemActivated.connect(self.HandleEntranceSelectByList)
        self.entranceList.toolTipAboutToShow.connect(self.HandleEntranceToolTipAboutToShow)
        self.entranceList.setSortingEnabled(True)

        eel.addWidget(elabel)
        eel.addWidget(self.entranceList)

        # locations tab
        self.locEditorTab = QtWidgets.QWidget()
        tabs.addTab(self.locEditorTab, GetIcon('locations'), '')
        tabs.setTabToolTip(3, 'Locations')

        locL = QtWidgets.QVBoxLayout(self.locEditorTab)
        self.locEditorLayout = locL

        Llabel = QtWidgets.QLabel('Locations currently in this area<br>(Double-click one to jump to it instantly, hover for preview)')
        Llabel.setWordWrap(True)
        self.locationList = ListWidgetWithToolTipSignal()
        self.locationList.itemActivated.connect(self.HandleLocationSelectByList)
        self.locationList.toolTipAboutToShow.connect(self.HandleLocationToolTipAboutToShow)
        self.locationList.setSortingEnabled(True)

        locL.addWidget(Llabel)
        locL.addWidget(self.locationList)

        # paths tab
        self.pathEditorTab = QtWidgets.QWidget()
        tabs.addTab(self.pathEditorTab, GetIcon('paths'), '')
        tabs.setTabToolTip(4, 'Paths')

        pathel = QtWidgets.QVBoxLayout(self.pathEditorTab)
        self.pathEditorLayout = pathel

        pathlabel = QtWidgets.QLabel('Path nodes currently in this area<br>(Double-click one to jump to it instantly)<br>To delete a path, remove all its nodes one by one.')
        pathlabel.setWordWrap(True)
        self.pathList = ListWidgetWithToolTipSignal()
        self.pathList.itemActivated.connect(self.HandlePathSelectByList)
        self.pathList.toolTipAboutToShow.connect(self.HandlePathToolTipAboutToShow)
        self.pathList.setSortingEnabled(True)

        pathel.addWidget(pathlabel)
        pathel.addWidget(self.pathList)

        # nabbit path tab
        self.nabbitPathEditorTab = QtWidgets.QWidget()
        tabs.addTab(self.nabbitPathEditorTab, GetIcon('nabbitpath'), '')
        tabs.setTabToolTip(5, 'Nabbit Path')

        nabbitPathel = QtWidgets.QVBoxLayout(self.nabbitPathEditorTab)
        self.nabbitPathEditorLayout = nabbitPathel

        nabbitPathlabel = QtWidgets.QLabel('Nabbit Path nodes currently in this area<br>(Double-click one to jump to it instantly, hover for preview)')
        nabbitPathlabel.setWordWrap(True)
        self.nabbitPathList = ListWidgetWithToolTipSignal()
        self.nabbitPathList.itemActivated.connect(self.HandleNabbitPathSelectByList)
        self.nabbitPathList.toolTipAboutToShow.connect(self.HandleNabbitPathToolTipAboutToShow)
        self.nabbitPathList.setSortingEnabled(True)

        nabbitPathel.addWidget(nabbitPathlabel)
        nabbitPathel.addWidget(self.nabbitPathList)

        # events tab
        self.eventEditorTab = QtWidgets.QWidget()
        tabs.addTab(self.eventEditorTab, GetIcon('events'), '')
        tabs.setTabToolTip(6, 'Events')

        eventel = QtWidgets.QGridLayout(self.eventEditorTab)
        self.eventEditorLayout = eventel

        eventlabel = QtWidgets.QLabel('Event states upon level launch (1-32) or zone entering (33-64):<br>(Click on one to add a note)')
        eventNotesLabel = QtWidgets.QLabel('Note:')
        self.eventNotesEditor = QtWidgets.QLineEdit()
        self.eventNotesEditor.textEdited.connect(self.handleEventNotesEdit)

        self.eventChooser = QtWidgets.QTreeWidget()
        self.eventChooser.setColumnCount(2)
        self.eventChooser.setHeaderLabels(('State', 'Notes'))
        self.eventChooser.itemClicked.connect(self.handleEventTabItemClick)
        self.eventChooserItems = []
        flags = Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
        for id in range(64):
            itm = QtWidgets.QTreeWidgetItem()
            itm.setFlags(flags)
            itm.setCheckState(0, Qt.Unchecked)
            itm.setText(0, 'Event [id]'.replace('[id]', str(str(id + 1))))
            itm.setText(1, '')
            self.eventChooser.addTopLevelItem(itm)
            self.eventChooserItems.append(itm)
            if id == 0: itm.setSelected(True)

        eventel.addWidget(eventlabel, 0, 0, 1, 2)
        eventel.addWidget(eventNotesLabel, 1, 0)
        eventel.addWidget(self.eventNotesEditor, 1, 1)
        eventel.addWidget(self.eventChooser, 2, 0, 1, 2)

        # clips tab
        self.clipsTab = QtWidgets.QWidget()
        tabs.addTab(self.clipsTab, GetIcon('cut'), '')
        tabs.setTabToolTip(7, 'Clips')

        self.clipChooser = ClipChooserWidget()

        clipsLayout = QtWidgets.QVBoxLayout()
        clipsLayout.setContentsMargins(0, 0, 0, 0)
        clipsLayout.addWidget(self.clipChooser)
        self.clipsTab.setLayout(clipsLayout)

        # comments tab
        self.commentsTab = QtWidgets.QWidget()
        tabs.addTab(self.commentsTab, GetIcon('comments'), '')
        tabs.setTabToolTip(8, 'Comments')

        cel = QtWidgets.QVBoxLayout()
        self.commentsTab.setLayout(cel)
        self.entEditorLayout = cel

        clabel = QtWidgets.QLabel('Comments currently in this area<br>(Double-click one to jump to it instantly, hover for preview)')
        clabel.setWordWrap(True)

        self.commentList = ListWidgetWithToolTipSignal()
        self.commentList.itemActivated.connect(self.HandleCommentSelectByList)
        self.commentList.toolTipAboutToShow.connect(self.HandleCommentToolTipAboutToShow)
        self.commentList.setSortingEnabled(True)

        cel.addWidget(clabel)
        cel.addWidget(self.commentList)

        # Set the current tab to the Object tab
        self.CreationTabChanged(0)

    def Autosave(self):
        """
        Auto saves the level
        """
        return
#        if not globals.AutoSaveDirty: return
#
#        data = globals.Level.save()
#        setSetting('AutoSaveFilePath', self.fileSavePath)
#        setSetting('AutoSaveFileData', QtCore.QByteArray(data))
#        globals.AutoSaveDirty = False

    def TrackClipboardUpdates(self):
        """
        Catches systemwide clipboard updates
        """
        if globals.Initializing: return
        clip = self.systemClipboard.text()
        if clip is not None and clip != '':
            clip = str(clip).strip()

            if clip.startswith('MiyamotoClip|') and clip.endswith('|%'):
                self.clipboard = clip.replace(' ', '').replace('\n', '').replace('\r', '').replace('\t', '')

                self.actions['paste'].setEnabled(True)
            else:
                self.clipboard = None
                self.actions['paste'].setEnabled(False)

    def XScrollChange(self, pos):
        """
        Moves the Overview current position box based on X scroll bar value
        """
        self.levelOverview.Xposlocator = pos
        self.levelOverview.update()

    def YScrollChange(self, pos):
        """
        Moves the Overview current position box based on Y scroll bar value
        """
        self.levelOverview.Yposlocator = pos
        self.levelOverview.update()

    def HandleWindowSizeChange(self, w, h):
        self.levelOverview.Hlocator = h
        self.levelOverview.Wlocator = w
        self.levelOverview.update()

    def UpdateTitle(self):
        """
        Sets the window title accordingly
        """
        self.setWindowTitle('%s%s%s' % (
        self.fileTitle, (' ' + '[unsaved]') if globals.Dirty else '',
        ' [Deluxe]' if globals.IsNSMBUDX else ''))

    def CheckDirty(self):
        """
        Checks if the level is unsaved and asks for a confirmation if so - if it returns True, Cancel was picked
        """
        if not globals.Dirty: return False

        msg = QtWidgets.QMessageBox()
        msg.setText('Warning')
        msg.setInformativeText('You have unsaved changes.')
        msg.setStandardButtons(
            QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel)
        msg.setDefaultButton(QtWidgets.QMessageBox.Save)
        ret = msg.exec_()

        if ret == QtWidgets.QMessageBox.Save:
            return not self.HandleSave()
        elif ret == QtWidgets.QMessageBox.Discard:
            return False
        elif ret == QtWidgets.QMessageBox.Cancel:
            return True

    def LoadEventTabFromLevel(self):
        """
        Configures the Events tab from the data in Area.eventBits
        """
        defEvents = (globals.Area.eventBits64 << 32) | globals.Area.eventBits32
        checked = Qt.Checked
        unchecked = Qt.Unchecked

        data = globals.Area.Metadata.binData('EventNotes_A%d' % globals.Area.areanum)
        eventTexts = {}
        if data is not None:
            # Iterate through the data
            idx = 0
            while idx < len(data):
                eventId = data[idx]
                idx += 1
                rawStrLen = data[idx:idx + 4]
                idx += 4
                strLen = (rawStrLen[0] << 24) | (rawStrLen[1] << 16) | (rawStrLen[2] << 8) | rawStrLen[3]
                rawStr = data[idx:idx + strLen]
                idx += strLen
                newStr = ''
                for char in rawStr: newStr += chr(char)
                eventTexts[eventId] = newStr

        for id in range(64):
            item = self.eventChooserItems[id]
            value = 1 << id
            item.setCheckState(0, checked if (defEvents & value) != 0 else unchecked)
            if id in eventTexts:
                item.setText(1, eventTexts[id])
            else:
                item.setText(1, '')
            item.setSelected(False)

        self.eventChooserItems[0].setSelected(True)
        txt0 = ''
        if 0 in eventTexts: txt0 = eventTexts[0]
        self.eventNotesEditor.setText(txt0)

    def handleEventTabItemClick(self, item):
        """
        Handles an item being clicked in the Events tab
        """
        noteText = item.text(1)
        self.eventNotesEditor.setText(noteText)

        selIdx = self.eventChooserItems.index(item)
        if selIdx > 31:
            _selIdx = selIdx - 32
            isOn = (globals.Area.eventBits64 & 1 << _selIdx) == 1 << _selIdx

        else:
            isOn = (globals.Area.eventBits32 & 1 << selIdx) == 1 << selIdx

        if item.checkState(0) == Qt.Checked and not isOn:
            # Turn a bit on
            if selIdx > 31:
                selIdx -= 32
                globals.Area.eventBits64 |= 1 << selIdx

            else:
                globals.Area.eventBits32 |= 1 << selIdx
            SetDirty()
        elif item.checkState(0) == Qt.Unchecked and isOn:
            # Turn a bit off (invert, turn on, invert)
            if selIdx > 31:
                selIdx -= 32
                globals.Area.eventBits64 = ~globals.Area.eventBits64
                globals.Area.eventBits64 |= 1 << selIdx
                globals.Area.eventBits64 = ~globals.Area.eventBits64

            else:
                globals.Area.eventBits32 = ~globals.Area.eventBits32
                globals.Area.eventBits32 |= 1 << selIdx
                globals.Area.eventBits32 = ~globals.Area.eventBits32
            SetDirty()

    def handleEventNotesEdit(self):
        """
        Handles the text within self.eventNotesEditor changing
        """
        newText = self.eventNotesEditor.text()

        # Set the text to the event chooser
        currentItem = self.eventChooser.selectedItems()[0]
        currentItem.setText(1, newText)

        # Save all the events to the metadata
        data = []
        for id in range(32):
            idtext = str(self.eventChooserItems[id].text(1))
            if idtext == '': continue

            # Add the ID
            data.append(id)

            # Add the string length
            strlen = len(idtext)
            data.append(strlen >> 24)
            data.append((strlen >> 16) & 0xFF)
            data.append((strlen >> 8) & 0xFF)
            data.append(strlen & 0xFF)

            # Add the string
            for char in idtext: data.append(ord(char))

        globals.Area.Metadata.setBinData('EventNotes_A%d' % globals.Area.areanum, data)
        SetDirty()

    def AboutBox(self):
        """
        Shows the about box
        """
        AboutDialog().exec_()

    def HandleInfo(self):
        """
        Records the Level Meta Information
        """
        if globals.Area.areanum == 1:
            dlg = MetaInfoDialog()
            if dlg.exec_() == QtWidgets.QDialog.Accepted:
                globals.Area.Metadata.setStrData('Title', dlg.levelName.text())
                globals.Area.Metadata.setStrData('Author', dlg.Author.text())
                globals.Area.Metadata.setStrData('Group', dlg.Group.text())
                globals.Area.Metadata.setStrData('Website', dlg.Website.text())

                SetDirty()
                return
        else:
            dlg = QtWidgets.QMessageBox()
            dlg.setText('Sorry!<br><br>You can only view or edit Level Information in Area 1.')
            dlg.exec_()

    def OpenWiki(self):
        """
        Opens the Zenith wiki in the user's default browser
        """
        QtGui.QDesktopServices.openUrl(QtCore.QUrl('https://zenith.nsmbu.net/wiki/Main_Page'))

    def SelectAll(self):
        """
        Select all objects in the current area, filtered by the current selection type.
        If tiles are selected, selects all tiles. If sprites are selected, selects all sprites, etc.
        If nothing is selected, selects everything.
        """
        selitems = self.scene.selectedItems()

        if not selitems:
            paintRect = QtGui.QPainterPath()
            paintRect.addRect(float(0), float(0), float(1024 * globals.TileWidth), float(512 * globals.TileWidth))
            self.scene.setSelectionArea(paintRect)
            return

        has_objects = any(isinstance(item, ObjectItem) for item in selitems)
        has_sprites = any(isinstance(item, SpriteItem) for item in selitems)
        has_entrances = any(isinstance(item, EntranceItem) for item in selitems)
        has_locations = any(isinstance(item, LocationItem) for item in selitems)
        has_paths = any(isinstance(item, PathItem) for item in selitems)
        has_nabbit_paths = any(isinstance(item, NabbitPathItem) for item in selitems)
        has_comments = any(isinstance(item, CommentItem) for item in selitems)

        layer_shown = (globals.Layer0Shown, globals.Layer1Shown, globals.Layer2Shown)

        self.SelectionUpdateFlag = True
        self.scene.clearSelection()

        if has_objects:
            for layer_idx, layer in enumerate(globals.Area.layers):
                if layer_shown[layer_idx]:
                    for obj in layer:
                        obj.setSelected(True)

        if has_sprites:
            for sprite in globals.Area.sprites:
                if layer_shown[sprite.layer]:
                    sprite.setSelected(True)

        if has_entrances:
            for ent in globals.Area.entrances:
                ent.setSelected(True)

        if has_locations:
            for loc in globals.Area.locations:
                loc.setSelected(True)

        if has_paths:
            for path in globals.Area.paths:
                path.setSelected(True)

        if has_nabbit_paths:
            for npath in globals.Area.nPaths:
                npath.setSelected(True)

        if has_comments:
            for comment in globals.Area.comments:
                comment.setSelected(True)

        self.SelectionUpdateFlag = False
        self.ChangeSelectionHandler()

    def HandleUndo(self):
        """
        Undo the last action
        """
        if globals.UndoManager:
            globals.UndoManager.undo()

    def HandleRedo(self):
        """
        Redo the last undone action
        """
        if globals.UndoManager:
            globals.UndoManager.redo()

    def UpdateUndoRedoActions(self):
        """Updates the Undo/Redo actions' enabled state and text."""
        undo_base = 'Undo'
        redo_base = 'Redo'

        if 'undo' in self.actions:
            self.actions['undo'].setEnabled(globals.UndoManager.canUndo())
            undo_text = globals.UndoManager.undoText()
            self.actions['undo'].setText(f"{undo_base} {undo_text}" if undo_text else undo_base)

        if 'redo' in self.actions:
            self.actions['redo'].setEnabled(globals.UndoManager.canRedo())
            redo_text = globals.UndoManager.redoText()
            self.actions['redo'].setText(f"{redo_base} {redo_text}" if redo_text else redo_base)

    def Deselect(self):
        """
        Deselect all currently selected items
        """
        items = self.scene.selectedItems()
        for obj in items:
            obj.setSelected(False)

    def Cut(self):
        """
        Cut the selected items
        """
        self.SelectionUpdateFlag = True
        selitems = self.scene.selectedItems()
        self.scene.clearSelection()

        if len(selitems) > 0:
            # Get the previous flower/grass type
            oldGrassType = 5
            for sprite in globals.Area.sprites:
                if sprite.type == 564:
                    oldGrassType = min(sprite.spritedata[5] & 0xf, 5)
                    if oldGrassType < 2:
                        oldGrassType = 0
                    elif oldGrassType in [3, 4]:
                        oldGrassType = 3

            clipboard_o = []
            clipboard_s = []
            clipboard_e = []
            clipboard_l = []
            clipboard_p = []
            clipboard_n = []
            clipboard_c = []
            
            objs_to_delete = []
            sprs_to_delete = []
            ents_to_delete = []
            locs_to_delete = []
            paths_to_delete = []
            nPaths_to_delete = []
            coms_to_delete = []

            # Count selected nodes per path to correctly handle path removal
            nodes_to_delete_per_path = {}
            for item in selitems:
                if isinstance(item, (PathItem, NabbitPathItem)):
                    p_id = id(item.pathinfo)
                    nodes_to_delete_per_path[p_id] = nodes_to_delete_per_path.get(p_id, 0) + 1
            
            handled_path_removals = set()
            
            for obj in selitems:
                if isinstance(obj, ObjectItem):
                    l_idx = -1
                    for i, layer in enumerate(globals.Area.layers):
                        if obj in layer:
                            l_idx = i
                            break
                    if l_idx != -1:
                        objs_to_delete.append((obj, l_idx, globals.Area.layers[l_idx].index(obj), obj.zValue()))
                        clipboard_o.append(obj)
                elif isinstance(obj, SpriteItem):
                    if obj in globals.Area.sprites:
                        sprs_to_delete.append((obj, globals.Area.sprites.index(obj)))
                        clipboard_s.append(obj)
                elif isinstance(obj, EntranceItem):
                    if obj in globals.Area.entrances:
                        ents_to_delete.append((obj, globals.Area.entrances.index(obj)))
                        clipboard_e.append(obj)
                elif isinstance(obj, LocationItem):
                    if obj in globals.Area.locations:
                        locs_to_delete.append((obj, globals.Area.locations.index(obj)))
                        clipboard_l.append(obj)
                elif isinstance(obj, PathItem):
                    try:
                        idx = obj.pathinfo['nodes'].index(obj.nodeinfo)
                        p_id = id(obj.pathinfo)
                        path_was_removed = False
                        if len(obj.pathinfo['nodes']) == nodes_to_delete_per_path[p_id]:
                            if p_id not in handled_path_removals:
                                path_was_removed = True
                                handled_path_removals.add(p_id)
                        paths_to_delete.append((obj, obj.pathinfo, obj.nodeinfo, idx, path_was_removed, False))
                        clipboard_p.append(obj)
                    except ValueError:
                        continue
                elif isinstance(obj, NabbitPathItem):
                    try:
                        idx = obj.pathinfo['nodes'].index(obj.nodeinfo)
                        p_id = id(obj.pathinfo)
                        path_was_removed = False
                        if len(obj.pathinfo['nodes']) == nodes_to_delete_per_path[p_id]:
                            if p_id not in handled_path_removals:
                                path_was_removed = True
                                handled_path_removals.add(p_id)
                        nPaths_to_delete.append((obj, obj.pathinfo, obj.nodeinfo, idx, path_was_removed, True))
                        clipboard_n.append(obj)
                    except ValueError:
                        continue
                elif isinstance(obj, CommentItem):
                    if obj in globals.Area.comments:
                        coms_to_delete.append((obj, globals.Area.comments.index(obj)))
                        clipboard_c.append(obj)

            if objs_to_delete or sprs_to_delete or ents_to_delete or locs_to_delete or paths_to_delete or nPaths_to_delete or coms_to_delete:
                self.actions['cut'].setEnabled(False)
                self.actions['paste'].setEnabled(True)
                self.clipboard = self.encodeObjects(clipboard_o, clipboard_s, clipboard_e, clipboard_l, clipboard_p, clipboard_n, clipboard_c)
                self.systemClipboard.setText(self.clipboard)

                globals.UndoManager.begin_compound("Cut Selection")
                if objs_to_delete:
                    globals.UndoManager.push(undomanager.DeleteObjectsCommand(objs_to_delete))
                if sprs_to_delete:
                    globals.UndoManager.push(undomanager.DeleteSpritesCommand(sprs_to_delete))
                if ents_to_delete:
                    globals.UndoManager.push(undomanager.DeleteEntrancesCommand(ents_to_delete))
                if locs_to_delete:
                    globals.UndoManager.push(undomanager.DeleteLocationsCommand(locs_to_delete))
                if paths_to_delete:
                    globals.UndoManager.push(undomanager.DeletePathNodeCommand(paths_to_delete, False))
                if nPaths_to_delete:
                    globals.UndoManager.push(undomanager.DeletePathNodeCommand(nPaths_to_delete, True))
                if coms_to_delete:
                    globals.UndoManager.push(undomanager.DeleteCommentsCommand(coms_to_delete))
                globals.UndoManager.end_compound()

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
                    self.objPicker.LoadFromTilesets()
                    for layer in globals.Area.layers:
                        for tObj in layer:
                            tObj.updateObjCache()

                    for sprite in globals.Area.sprites:
                        if sprite.type == 546:
                            sprite.UpdateDynamicSizing()

                    self.scene.update()

        self.levelOverview.update()
        self.SelectionUpdateFlag = False
        self.ChangeSelectionHandler()

    def Copy(self):
        """
        Copy the selected items
        """
        selitems = self.scene.selectedItems()
        if len(selitems) > 0:
            clipboard_o = []
            clipboard_s = []
            clipboard_e = []
            clipboard_l = []
            clipboard_p = []
            clipboard_n = []
            clipboard_c = []
            ii = isinstance
            type_obj = ObjectItem
            type_spr = SpriteItem
            type_ent = EntranceItem
            type_loc = LocationItem
            type_path = PathItem
            type_nPath = NabbitPathItem
            type_com = CommentItem

            for obj in selitems:
                if ii(obj, type_obj):
                    clipboard_o.append(obj)
                elif ii(obj, type_spr):
                    clipboard_s.append(obj)
                elif ii(obj, type_ent):
                    clipboard_e.append(obj)
                elif ii(obj, type_loc):
                    clipboard_l.append(obj)
                elif ii(obj, type_path):
                    clipboard_p.append(obj)
                elif ii(obj, type_nPath):
                    clipboard_n.append(obj)
                elif ii(obj, type_com):
                    clipboard_c.append(obj)

            if len(clipboard_o) > 0 or len(clipboard_s) > 0 or len(clipboard_e) > 0 or len(clipboard_l) > 0 or len(clipboard_p) > 0 or len(clipboard_n) > 0 or len(clipboard_c) > 0:
                self.actions['paste'].setEnabled(True)
                self.clipboard = self.encodeObjects(clipboard_o, clipboard_s, clipboard_e, clipboard_l, clipboard_p, clipboard_n, clipboard_c)
                self.systemClipboard.setText(self.clipboard)

    def Paste(self):
        """
        Paste the selected items
        """
        if self.clipboard is not None:
            # Get the previous flower/grass type
            oldGrassType = 5
            for sprite in globals.Area.sprites:
                if sprite.type == 564:
                    oldGrassType = min(sprite.spritedata[5] & 0xf, 5)
                    if oldGrassType < 2:
                        oldGrassType = 0

                    elif oldGrassType in [3, 4]:
                        oldGrassType = 3

            self.placeEncodedObjects(self.clipboard)

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
                self.objPicker.LoadFromTilesets()
                for layer in globals.Area.layers:
                    for tObj in layer:
                        tObj.updateObjCache()

                for sprite in globals.Area.sprites:
                    if sprite.type == 546:
                        sprite.UpdateDynamicSizing()

                self.scene.update()

    def HandleDuplicate(self):
        selitems = self.scene.selectedItems()
        if len(selitems) == 0:
            return

        func_ii = isinstance
        clipboard = self.encodeObjects(
            [o for o in selitems if func_ii(o, ObjectItem)],
            [s for s in selitems if func_ii(s, SpriteItem)],
            [e for e in selitems if func_ii(e, EntranceItem)],
            [l for l in selitems if func_ii(l, LocationItem)],
            [p for p in selitems if func_ii(p, PathItem)],
            [n for n in selitems if func_ii(n, NabbitPathItem)],
            [c for c in selitems if func_ii(c, CommentItem)],
        )
        self.placeEncodedObjects(clipboard)
        SetDirty()

    def encodeObjects(self, clipboard_o, clipboard_s, clipboard_e, clipboard_l, clipboard_p, clipboard_n, clipboard_c):
        """
        Encode a set of objects into a string
        """
        convclip = ['MiyamotoClip']

        # get objects
        clipboard_o.sort(key=lambda x: x.zValue())

        for item in clipboard_o:
            convclip.append('0:%d:%d:%d:%d:%d:%d:%d:%d' % (
            item.tileset, item.type, item.layer, item.objx, item.objy, item.width, item.height, item.data))

        # get sprites
        for item in clipboard_s:
            data = item.spritedata
            if isinstance(item.type, str):
                type_token = 'S' + quote(item.type, safe='')
            else:
                type_token = str(item.type)
                if item.type >= CUSTOM_ID_BASE:
                    string_id = globals.Level.id_manager.get_string_for_id(item.type)
                    if string_id:
                        type_token = 'S' + quote(string_id, safe='')

            convclip.append('1:%s:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d' % (
            type_token, item.objx, item.objy, data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7],
            data[8], data[9], data[10], data[11], item.layer, item.initialState))

        # get entrances
        clipboard_e.sort(key=lambda x: x.entid)

        for item in clipboard_e:
            convclip.append('2:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d' % (
            item.objx, item.objy, item.camerax, item.cameray, item.entid, item.destarea, item.destentrance, item.enttype, item.players,
            item.entzone, item.playerDistance, item.entsettings, item.otherID, item.coinOrder, item.pathID, item.pathnodeindex, item.transition))

        # get locations
        clipboard_l.sort(key=lambda x: x.id)

        for item in clipboard_l:
            convclip.append('3:%d:%d:%d:%d:%d' % (
            item.objx, item.objy, item.width, item.height, item.id))

        # get path nodes
        clipboard_p.sort(key=lambda x: (x.pathid, x.nodeid))

        pathID = -1
        for item in clipboard_p:
            if item.pathid != pathID:
                pathID = item.pathid

                convclip.append('4:%d:%d:%d' % (
                item.pathid, item.pathinfo['unk1'], item.pathinfo['loops']))

            convclip[-1] += (':%d:%d:%g:%g:%d' % (
            item.objx, item.objy, item.nodeinfo['speed'], item.nodeinfo['accel'], item.nodeinfo['delay']))

        # get nabbit path nodes
        clipboard_n.sort(key=lambda x: x.nodeid)

        for item in clipboard_n:
            convclip.append('5:%d:%d:%d:%d:%d:%d:%d' % (
            item.objx, item.objy, item.nodeinfo['action'], item.nodeinfo['unk1'], item.nodeinfo['unk2'], item.nodeinfo['unk3'], item.nodeinfo['unk4']))

        # get comments
        for item in clipboard_c:
            from base64 import b64encode
            text = item.text.encode("ascii")
            b64text = b64encode(text)

            convclip.append('8:%d:%d:%s' % (
            item.objx, item.objy, b64text.decode("ascii")))

        convclip.append('%')
        return '|'.join(convclip)

    def placeEncodedObjects(self, encoded, select=True, xOverride=None, yOverride=None):
        """
        Decode and place a set of objects
        """
        from math import floor, ceil

        self.SelectionUpdateFlag = True
        self.scene.clearSelection()
        added = []

        x1 = 1024
        x2 = 0
        y1 = 512
        y2 = 0

        globals.OverrideSnapping = True

        if not (encoded.startswith('MiyamotoClip|') and encoded.endswith('|%')): return

        clip = encoded.split('|')[1:-1]

        if len(clip) > 300:
            result = QtWidgets.QMessageBox.warning(self, 'Pyamoto', "You're trying to paste over 300 items at once.<br>This may take a while (depending on your computer speed), are you sure you want to continue?",
                                                   QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)
            if result != QtWidgets.QMessageBox.Yes: return

        layers, sprites, entrances, locations, paths, nabbitPaths, comments = self.getEncodedObjects(encoded)

        globals.UndoManager.begin_compound("Paste")

        # Go through the objects
        for layer_idx, layer in enumerate(layers):
            if len(layer) > 0:
                AreaLayer = globals.Area.layers[layer_idx]
                if len(AreaLayer) > 0:
                    z = AreaLayer[-1].zValue() + 1
                else:
                    # Layer 0: 16384, Layer 1: 8192, Layer 2: 0
                    z = [16384, 8192, 0][layer_idx]
                
                for obj in layer:
                    xs = obj.objx
                    xe = obj.objx + obj.width - 1
                    ys = obj.objy
                    ye = obj.objy + obj.height - 1
                    if xs < x1: x1 = xs
                    if xe > x2: x2 = xe
                    if ys < y1: y1 = ys
                    if ye > y2: y2 = ye

                    globals.UndoManager.push(undomanager.AddObjectCommand(obj, layer_idx, z))
                    added.append(obj)
                    z += 1

        # Go through the sprites
        for spr in sprites:
            x = spr.objx / 16
            y = spr.objy / 16
            if x < x1: x1 = x
            if x > x2: x2 = x
            if y < y1: y1 = y
            if y > y2: y2 = y

            globals.UndoManager.push(undomanager.AddSpriteCommand(spr))
            added.append(spr)

        # Go through the entrances
        for ent in entrances:
            x = ent.objx / 16
            y = ent.objy / 16
            if x < x1: x1 = x
            if x > x2: x2 = x
            if y < y1: y1 = y
            if y > y2: y2 = y

            globals.UndoManager.push(undomanager.AddEntranceCommand(ent))
            added.append(ent)

        # Go through the locations
        for loc in locations:
            xs = loc.objx / 16
            xe = (loc.objx + loc.width) / 16 - 1
            ys = loc.objy / 16
            ye = (loc.objy + loc.height) / 16 - 1
            if xs < x1: x1 = xs
            if xe > x2: x2 = xe
            if ys < y1: y1 = ys
            if ye > y2: y2 = ye

            globals.UndoManager.push(undomanager.AddLocationCommand(loc))
            added.append(loc)

        # Go through the path nodes
        for node in paths:
            x = node.objx / 16
            y = node.objy / 16
            if x < x1: x1 = x
            if x > x2: x2 = x
            if y < y1: y1 = y
            if y > y2: y2 = y

            globals.UndoManager.push(undomanager.AddPathNodeCommand(node.pathinfo, node.nodeinfo, node, False))
            added.append(node)

        # Go through the nabbit path nodes
        for node in nabbitPaths:
            x = node.objx / 16
            y = node.objy / 16
            if x < x1: x1 = x
            if x > x2: x2 = x
            if y < y1: y1 = y
            if y > y2: y2 = y

            globals.UndoManager.push(undomanager.AddPathNodeCommand(node.pathinfo, node.nodeinfo, node, True))
            added.append(node)

        # Go through the comments
        for com in comments:
            x = com.objx / 16
            y = com.objy / 16
            if x < x1: x1 = x
            if x > x2: x2 = x
            if y < y1: y1 = y
            if y > y2: y2 = y

            globals.UndoManager.push(undomanager.AddCommentCommand(com))
            added.append(com)

        globals.UndoManager.end_compound()

        if len(added) == 0:
            globals.OverrideSnapping = False
            return added

        # now center everything
        zoomscaler = ((self.ZoomLevel / globals.TileWidth * 24) / 100.0)
        width = x2 - x1 + 1
        height = y2 - y1 + 1
        viewportx = (self.view.XScrollBar.value() / zoomscaler) / globals.TileWidth
        viewporty = (self.view.YScrollBar.value() / zoomscaler) / globals.TileWidth
        viewportwidth = (self.view.width() / zoomscaler) / globals.TileWidth
        viewportheight = (self.view.height() / zoomscaler) / globals.TileWidth
        scene_pos = self.view.mapToScene(self.view.viewport().mapFromGlobal(QtGui.QCursor.pos()))
        mousex = scene_pos.x() / globals.TileWidth
        mousey = scene_pos.y() / globals.TileWidth
        centerx = max(min(mousex, floor(viewportx + viewportwidth) - (width / 2)), min(ceil(viewportx) + (width / 2), 1024 - (width / 2)))
        centery = max(min(mousey, floor(viewporty + viewportheight) - (height / 2)), min(ceil(viewporty) + (height / 2), 512 - (height / 2)))

        # tiles
        if xOverride is None:
            xoffset = round(0 - x1 + centerx - (width / 2))
            xpixeloffset = xoffset * 16
        else:
            xoffset = round(0 - x1 + (xOverride / 16) - (width / 2))
            xpixeloffset = xoffset * 16
        if yOverride is None:
            yoffset = round(0 - y1 + centery - (height / 2))
            ypixeloffset = yoffset * 16
        else:
            yoffset = round(0 - y1 + (yOverride / 16) - (height / 2))
            ypixeloffset = yoffset * 16

        for item in added:
            if isinstance(item, ObjectItem):
                item.setPos((item.objx + xoffset) * globals.TileWidth, (item.objy + yoffset) * globals.TileWidth)
            elif isinstance(item, SpriteItem) and globals.SpriteImagesShown:
                item.setPos(
                    (item.objx + xpixeloffset + item.ImageObj.xOffset) * globals.TileWidth / 16,
                    (item.objy + ypixeloffset + item.ImageObj.yOffset) * globals.TileWidth / 16,
                )
            elif isinstance(item, (SpriteItem, EntranceItem, LocationItem, PathItem, NabbitPathItem, CommentItem)):
                item.setPos(
                    (item.objx + xpixeloffset) * globals.TileWidth / 16,
                    (item.objy + ypixeloffset) * globals.TileWidth / 16,
                )
            if select: item.setSelected(True)

        globals.OverrideSnapping = False

        self.levelOverview.update()
        SetDirty()
        self.SelectionUpdateFlag = False
        self.ChangeSelectionHandler()

        return added

    def getEncodedObjects(self, encoded, placeObjects = True):
        """
        Create the objects from a MiyamotoClip
        """

        layers = ([], [], [])
        sprites = []
        entrances = []
        locations = []
        paths = []
        nabbitPaths = []
        comments = []

        try:
            if not (encoded.startswith('MiyamotoClip|') and encoded.endswith('|%')):
                return layers, sprites, entrances, locations, paths, nabbitPaths, comments

            clip = encoded[13:-2].split('|')

            if placeObjects and len(clip) > 300:
                result = QtWidgets.QMessageBox.warning(self, 'Pyamoto', "You're trying to paste over 300 items at once.<br>This may take a while (depending on your computer speed), are you sure you want to continue?",
                                                       QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)
                if result == QtWidgets.QMessageBox.No:
                    return layers, sprites, entrances, locations, paths, nabbitPaths, comments

            for item in clip:
                # Check to see what type of item it is
                # and add it to the correct stack
                split = item.split(':')

                # get object
                if split[0] == '0':
                    if len(split) != 9: continue

                    tileset = int(split[1])
                    type = int(split[2])
                    layer = int(split[3])
                    objx = int(split[4])
                    objy = int(split[5])
                    width = int(split[6])
                    height = int(split[7])
                    data = int(split[8])

                    # basic sanity checks
                    if tileset < 0 or tileset > 3: continue
                    if type < 0 or type > 255: continue
                    if layer < 0 or layer > 2: continue
                    if objx < 0 or objx > 1023: continue
                    if objy < 0 or objy > 511: continue
                    if width < 1 or width > 1023: continue
                    if height < 1 or height > 511: continue
                    if data < 0 or data > 24: continue

                    obj = ObjectItem(tileset, type, layer, objx, objy, width, height, 1, data)

                    layers[layer].append(obj)

                # get sprite
                elif split[0] == '1':
                    if len(split) != 18: continue

                    type_token = split[1]
                    if type_token.startswith('S'):
                        string_id = unquote(type_token[1:])
                        if not string_id:
                            continue
                        type = (
                            globals.Level.id_manager.get_id_for_string(string_id)
                            if placeObjects else string_id
                        )
                    else:
                        type = int(type_token)

                    objx = int(split[2])
                    objy = int(split[3])
                    data = bytes(map(int,
                                     [split[4], split[5], split[6], split[7], split[8], split[9],
                                      split[10], split[11], split[12], split[13], split[14], split[15]]))
                    layer = int(split[16])
                    initialState = int(split[17])

                    spr = SpriteItem(type, objx, objy, data, layer, initialState)

                    mw = globals.mainWindow
                    spr.positionChanged = mw.HandleSprPosChange
                    spr.listitem = ListWidgetItem_SortsByOther(spr)

                    spr.UpdateListItem()
                    sprites.append(spr)

                # get entrance
                elif split[0] == '2':
                    if len(split) != 18: continue

                    objx = int(split[1])
                    objy = int(split[2])
                    camerax = int(split[3])
                    cameray = int(split[4])
                    destarea = int(split[6])
                    destentrance = int(split[7])
                    enttype = int(split[8])
                    players = int(split[9])
                    entzone = int(split[10])
                    playerDistance = int(split[11])
                    entsettings = int(split[12])
                    otherID = int(split[13])
                    coinOrder = int(split[14])
                    pathID = int(split[15])
                    pathnodeindex = int(split[16])
                    transition = int(split[17])
                    
                    allID = set()  # faster 'x in y' lookups for sets
                    newID = int(split[5])
                    for i in globals.Area.entrances:
                        allID.add(i.entid)
                    for i in entrances:
                        allID.add(i.entid)

                    while newID <= 255:
                        if newID not in allID:
                            break
                        newID += 1

                    ent = EntranceItem(objx, objy, camerax, cameray, newID, destarea, destentrance, enttype, players,
                    entzone, playerDistance, entsettings, otherID, coinOrder, pathID, pathnodeindex, transition)

                    mw = globals.mainWindow
                    ent.positionChanged = mw.HandleEntPosChange
                    ent.listitem = ListWidgetItem_SortsByOther(ent)

                    ent.UpdateListItem()
                    entrances.append(ent)

                # get location
                elif split[0] == '3':
                    if len(split) != 6: continue

                    objx = int(split[1])
                    objy = int(split[2])
                    width = int(split[3])
                    height = int(split[4])
                    
                    allID = set()  # faster 'x in y' lookups for sets
                    newID = int(split[5])
                    for i in globals.Area.locations:
                        allID.add(i.id)
                    for i in locations:
                        allID.add(i.id)

                    while newID <= 255:
                        if newID not in allID:
                            break
                        newID += 1

                    loc = LocationItem(objx, objy, width, height, newID)

                    mw = globals.mainWindow
                    loc.positionChanged = mw.HandleLocPosChange
                    loc.sizeChanged = mw.HandleLocSizeChange
                    loc.listitem = ListWidgetItem_SortsByOther(loc)

                    loc.UpdateListItem()
                    locations.append(loc)

                # get path
                elif split[0] == '4':
                    if len(split) % 5 != 4 or len(split) < 9: continue

                    unk1 = int(split[2])
                    loops = int(split[3])

                    getids = [False for x in range(256)]
                    getids[90] = True  # Skip Nabbit path
                    for pathdatax in globals.Area.pathdata:
                        getids[int(pathdatax['id'])] = True
                    for i in paths:
                        getids[int(i.pathid)] = True

                    newpathid = getids.index(False, int(split[1]))
                    pathinfo = {'id': newpathid,
                                   'unk1': unk1,
                                   'nodes': [],
                                   'loops': loops
                                   }

                    for x in range(4, len(split), 5):
                        objx = int(split[x])
                        objy = int(split[x + 1])
                        speed = float(split[x + 2])
                        accel = float(split[x + 3])
                        delay = int(split[x + 4])

                        nodeinfo = {'x': objx, 'y': objy, 'speed': speed, 'accel': accel, 'delay': delay}
                        pathinfo['nodes'].append(nodeinfo)

                        node = PathItem(objx, objy, pathinfo, nodeinfo, 0, 0, 0, 0)

                        mw = globals.mainWindow
                        node.positionChanged = mw.HandlePathPosChange
                        node.listitem = ListWidgetItem_SortsByOther(node)

                        node.UpdateListItem()
                        paths.append(node)

                # get nabbit path node
                elif split[0] == '5':
                    if len(split) != 8 or globals.Area.areanum != 1: continue

                    objx = int(split[1])
                    objy = int(split[2])
                    action = int(split[3])
                    unk1 = int(split[4])
                    unk2 = int(split[5])
                    unk3 = int(split[6])
                    unk4 = int(split[7])

                    if globals.Area.nPathdata and placeObjects:
                        pathinfo = globals.Area.nPaths[-1].pathinfo
                    elif nabbitPaths:
                        pathinfo = nabbitPaths[-1].pathinfo
                    else:
                        pathinfo = {'nodes': []}

                    nodeinfo = {'x': objx, 'y': objy, 'action': action, 'unk1': unk1, 'unk2': unk2, 'unk3': unk3, 'unk4': unk4}
                    pathinfo['nodes'].append(nodeinfo)
                    
                    node = NabbitPathItem(objx, objy, pathinfo, nodeinfo, 0, 0, 0, 0)

                    mw = globals.mainWindow
                    node.positionChanged = mw.HandlePathPosChange
                    node.listitem = ListWidgetItem_SortsByOther(node)
                    
                    node.UpdateListItem()
                    nabbitPaths.append(node)

                # get comment
                elif split[0] == '8':
                    if len(split) != 4: continue
                    from base64 import b64decode

                    objx = int(split[1])
                    objy = int(split[2])
                    b64text = str(split[3]).encode("ascii")
                    text = b64decode(b64text)

                    com = CommentItem(objx, objy, text.decode("ascii"))

                    mw = globals.mainWindow
                    com.positionChanged = mw.HandleComPosChange
                    com.textChanged = mw.HandleComTxtChange
                    com.listitem = QtWidgets.QListWidgetItem()

                    com.UpdateListItem()
                    comments.append(com)

        except ValueError:
            # an int() probably failed somewhere
            pass

        return layers, sprites, entrances, locations, paths, nabbitPaths, comments

    def HandleRaiseObjects(self):
        objlist = [obj for obj in self.scene.selectedItems() if isinstance(obj, ObjectItem)]
        if not objlist: return
        objlist.sort(key=lambda obj: obj.zValue())
        numObjs = len(objlist)

        z_changes = []
        for obj in self.scene.items():
            if isinstance(obj, ObjectItem):
                z_changes.append((obj, obj.zValue()))

        for i, obj in enumerate(objlist):
            layer = globals.Area.layers[obj.layer]
            layer.sort(key=lambda obj: obj.zValue())
            if layer[i-numObjs] == obj:
                continue

            layer.remove(obj)
            newZ = layer[-1].zValue() + 1
            obj.setZValue(newZ)
            layer.append(obj)

        if numObjs:
            final_changes = []
            for obj, old_z in z_changes:
                if obj.zValue() != old_z:
                    final_changes.append((obj, old_z, obj.zValue()))
            
            if final_changes:
                globals.UndoManager.push(undomanager.RaiseLowerObjectsCommand("Raise Objects", final_changes))
            
            self.scene.update()

    def HandleLowerObjects(self):
        objlist = [obj for obj in self.scene.selectedItems() if isinstance(obj, ObjectItem)]
        if not objlist: return
        objlist.sort(key=lambda obj: -obj.zValue())
        numObjs = len(objlist)

        z_changes = []
        for obj in self.scene.items():
            if isinstance(obj, ObjectItem):
                z_changes.append((obj, obj.zValue()))

        for i, obj in enumerate(objlist):
            layer = globals.Area.layers[obj.layer]
            layer.sort(key=lambda obj: obj.zValue())
            if layer[numObjs-i-1] == obj:
                continue

            layer.remove(obj)
            newZ = (2 - obj.layer) * 8192
            obj.setZValue(newZ)
            for oObj in layer:
                oObj.setZValue(oObj.zValue() + 1)
            layer.insert(0, obj)

        if numObjs:
            final_changes = []
            for obj, old_z in z_changes:
                if obj.zValue() != old_z:
                    final_changes.append((obj, old_z, obj.zValue()))
            
            if final_changes:
                globals.UndoManager.push(undomanager.RaiseLowerObjectsCommand("Lower Objects", final_changes))
            
            self.scene.update()

    def ShiftItems(self):
        """
        Shifts the selected object(s)
        """
        items = self.scene.selectedItems()
        if len(items) == 0: return

        dlg = ObjectShiftDialog()
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            xoffset = dlg.XOffset.value()
            yoffset = dlg.YOffset.value()
            if xoffset == 0 and yoffset == 0: return

            type_obj = ObjectItem
            type_spr = SpriteItem
            type_ent = EntranceItem

            if ((xoffset % 16) != 0) or ((yoffset % 16) != 0):
                # warn if any objects exist
                objectsExist = False
                spritesExist = False
                for obj in items:
                    if isinstance(obj, type_obj):
                        objectsExist = True
                    elif isinstance(obj, type_spr) or isinstance(obj, type_ent):
                        spritesExist = True

                if objectsExist and spritesExist:
                    # no point in warning them if there are only objects
                    # since then, it will just silently reduce the offset and it won't be noticed
                    result = QtWidgets.QMessageBox.information(None, 'Warning',
                                                               "You are trying to move object(s) by an offset which isn't a multiple of 16. It will work, but the objects will not be able to move exactly the same amount as the actors. Are you sure you want to do this?", QtWidgets.QMessageBox.Yes,
                                                               QtWidgets.QMessageBox.No)
                    if result == QtWidgets.QMessageBox.No:
                        return

            xpoffset = xoffset * globals.TileWidth / 16
            ypoffset = yoffset * globals.TileWidth / 16

            globals.OverrideSnapping = True

            item_moves = []
            for obj in items:
                old_x, old_y = obj.objx, obj.objy
                obj.setPos(obj.x() + xpoffset, obj.y() + ypoffset)
                item_moves.append((obj, old_x, old_y, obj.objx, obj.objy))

            globals.OverrideSnapping = False
            
            if item_moves:
                globals.UndoManager.push(undomanager.ShiftItemsCommand(item_moves))
            
            # SetDirty()  # Handled by command sync (indirectly)

    def SwapObjectsTilesets(self):
        """
        Swaps objects' tilesets
        """
        dlg = ObjectTilesetSwapDialog()
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            globals.UndoManager.begin_compound("Swap Objects Tilesets")
            from_ts = dlg.FromTS.value() - 1
            to_ts = dlg.ToTS.value() - 1
            do_exchange = (dlg.DoExchange.checkState() == Qt.Checked)
            
            for layer in globals.Area.layers:
                for nsmbobj in layer:
                    if nsmbobj.tileset == from_ts:
                        globals.UndoManager.push(undomanager.SetObjectTypeCommand(nsmbobj, from_ts, nsmbobj.type, to_ts, nsmbobj.type))
                    elif nsmbobj.tileset == to_ts and do_exchange:
                        globals.UndoManager.push(undomanager.SetObjectTypeCommand(nsmbobj, to_ts, nsmbobj.type, from_ts, nsmbobj.type))

            globals.UndoManager.end_compound()
            # SetDirty()  # Handled by command

    def SwapObjectsTypes(self):
        """
        Swaps objects' types
        """
        dlg = ObjectTypeSwapDialog()
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            globals.UndoManager.begin_compound("Swap Objects Types")
            from_type = dlg.FromType.value()
            from_ts = dlg.FromTileset.value() - 1
            to_type = dlg.ToType.value()
            to_ts = dlg.ToTileset.value() - 1
            do_exchange = (dlg.DoExchange.checkState() == Qt.Checked)

            for layer in globals.Area.layers:
                for nsmbobj in layer:
                    if nsmbobj.type == from_type and nsmbobj.tileset == from_ts:
                        globals.UndoManager.push(undomanager.SetObjectTypeCommand(nsmbobj, from_ts, from_type, to_ts, to_type))
                    elif nsmbobj.type == to_type and nsmbobj.tileset == to_ts and do_exchange:
                        globals.UndoManager.push(undomanager.SetObjectTypeCommand(nsmbobj, to_ts, to_type, from_ts, from_type))

            globals.UndoManager.end_compound()
            # SetDirty()  # Handled by command

    def MergeLocations(self):
        """
        Merges selected sprite locations
        """
        items = self.scene.selectedItems()
        if len(items) == 0: return

        newx = 999999
        newy = 999999
        neww = 0
        newh = 0

        type_loc = LocationItem
        to_delete = []
        for obj in items:
            if isinstance(obj, type_loc):
                if obj.objx < newx:
                    newx = obj.objx
                if obj.objy < newy:
                    newy = obj.objy
                if obj.width + obj.objx > neww:
                    neww = obj.width + obj.objx
                if obj.height + obj.objy > newh:
                    newh = obj.height + obj.objy
                to_delete.append(obj)

        if to_delete and newx != 999999 and newy != 999999:
            globals.UndoManager.begin_compound("Merge Locations")
            
            # Delete old ones
            for obj in to_delete:
                obj.setSelected(False)
            globals.UndoManager.push(undomanager.DeleteLocationsCommand(to_delete))

            # Find new ID
            allID = set()
            for i in globals.Area.locations:
                allID.add(i.id)
            newID = 1
            while newID <= 255:
                if newID not in allID:
                    break
                newID += 1

            loc = LocationItem(newx, newy, neww - newx, newh - newy, newID)
            mw = self
            loc.positionChanged = mw.HandleObjPosChange
            
            globals.UndoManager.push(undomanager.AddLocationCommand(loc))
            loc.setSelected(True)
            
            globals.UndoManager.end_compound()
            self.levelOverview.update()

    def HandleAddNewArea(self):
        """
        Adds a new area to the level
        """
        if len(globals.Level.areas) >= 4:
            QtWidgets.QMessageBox.warning(self, 'Pyamoto', "You have reached the maximum amount of areas in this level.<br>Due to the game's limitations, Pyamoto only allows you to add up to 4 areas to a level.")
            return

        if self.CheckDirty():
            return

        newID = len(globals.Level.areas) + 1

        with open(globals.gamedef.file('blankcourse'), 'rb') as blank:
            course = blank.read()

        L0 = None
        L1 = None
        L2 = None

        if not self.HandleSaveNewArea(course, L0, L1, L2): return
        self.LoadLevel(None, self.fileSavePath, True, newID)

    def HandleImportArea(self):
        """
        Imports an area from another level
        """
        if len(globals.Level.areas) >= 4:
            QtWidgets.QMessageBox.warning(self, 'Pyamoto', "You have reached the maximum amount of areas in this level.<br>Due to the game's limitations, Pyamoto only allows you to add up to 4 areas to a level.")
            return

        if globals.Dirty:
            con_msg = "You need to save this level before importing/deleting Areas.\nDo you want to save now?"
            reply = QtWidgets.QMessageBox.question(self, 'Message',
                                                   con_msg, QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)

            if reply != QtWidgets.QMessageBox.Yes or not self.HandleSave():
                return

        filetypes = levelFileFilters()
        fn = QtWidgets.QFileDialog.getOpenFileName(self, 'Choose a level archive', '', filetypes)[0]
        if fn == '': return
        fn = str(fn)

        with open(fn, 'rb') as fileobj:
            data = fileobj.read()

        # Decompress, if needed (Yaz0)
        if data.startswith(b'Yaz0'):
            print('Beginning Yaz0 decompression...')
            data = yaz0.decompressFASTYZ(data)
            print('Decompression finished.')

        elif data.startswith(b'SARC'):
            print('Yaz0 decompression skipped.')

        else:
            return False  # keep it from crashing by loading things it shouldn't

        arc = SarcLib.SARC_Archive()
        arc.load(data)

        def exists(fn):
            nonlocal arc

            try:
                arc[fn]

            except KeyError:
                return False

            return True

        def guessInnerName():
            nonlocal fn

            possibilities = []
            possibilities.append(os.path.basename(fn))
            possibilities.append(
                os.path.basename(fn).split(' ')[-1])  # for names like "NSMBU 1-1.szs"
            possibilities.append(
                os.path.basename(fn).split(' ')[0])  # for names like "1-1 test.szs"
            possibilities.append(os.path.basename(fn).split('.')[0])
            possibilities.append(os.path.basename(fn).split('_')[0])

            for fn in possibilities:
                if exists(fn):
                    arcdata = arc[fn].data
                    break

            else:
                return ''

            return arcdata

        if exists('levelname'):
            fn = bytes_to_string(arc['levelname'].data)
            if exists(fn):
                arcdata = arc[fn].data

            else:
                arcdata = guessInnerName()

        else:
            arcdata = guessInnerName()

        if arcdata:
            arc_ = SarcLib.SARC_Archive()
            arc_.load(arcdata)

        else:
            if exists('course'):
                arc_ = arc

            else:
                warningBox = QtWidgets.QMessageBox(QtWidgets.QMessageBox.NoIcon, 'OH NO',
                                                   'Couldn\'t find the inner level file. Aborting.')
                warningBox.exec_()

                return False

        # Wii U and Deluxe areas aren't interchangeable (different byte order)
        if (getattr(arc_, 'endianness', '>') == '<') != bool(globals.IsNSMBUDX):
            QtWidgets.QMessageBox.warning(
                self, 'Cannot Import Area',
                'That level is from the %s version of the game, but the %s version is selected.' % (
                    ('Deluxe', 'Wii U') if not globals.IsNSMBUDX else ('Wii U', 'Deluxe')))
            return False

        # get the area count
        areacount = 0

        try:
            courseFolder = arc_['course']
        except:
            return False

        try:
            source_spritemap_data = arc_['course/spritemap.bin'].data
        except KeyError:
            source_spritemap_data = None

        for file in courseFolder.contents:
            fname, val = file.name, file.data
            if val is not None:
                # it's a file
                if fname.startswith('course'):
                    maxarea = int(fname[6])
                    if maxarea > areacount: areacount = maxarea

        # choose one
        dlg = AreaChoiceDialog(areacount)
        if dlg.exec_() == QtWidgets.QDialog.Rejected:
            return

        area = dlg.areaCombo.currentIndex() + 1

        # get the required files
        reqcourse = 'course%d.bin' % area
        reqL0 = 'course%d_bgdatL0.bin' % area
        reqL1 = 'course%d_bgdatL1.bin' % area
        reqL2 = 'course%d_bgdatL2.bin' % area

        course = None
        L0 = None
        L1 = None
        L2 = None

        for file in courseFolder.contents:
            fname, val = file.name, file.data
            if val is not None:
                if fname == reqcourse:
                    course = val
                elif fname == reqL0:
                    L0 = val
                elif fname == reqL1:
                    L1 = val
                elif fname == reqL2:
                    L2 = val

        assert course is not None

        try:
            course = remap_imported_course(
                course, source_spritemap_data, globals.Level.id_manager
            )
        except ValueError as e:
            QtWidgets.QMessageBox.warning(
                self, 'Cannot Import Area',
                'The area could not be imported safely:\n\n' + str(e)
            )
            return False

        # import the tilesets with the area
        getblock = struct.Struct('<II' if globals.IsNSMBUDX else '>II')
        data = getblock.unpack_from(course, 0)
        if data[1] and not globals.IsNSMBUDX:  # Deluxe tilesets aren't embedded: they stay in Unit
            block = course[data[0]:data[0] + data[1]]
            tilesetNames = list(map(bytes_to_string, struct.unpack_from('32s32s32s32s', block)))
            for name in tilesetNames:
                if name not in globals.szsData:
                    try:
                        globals.szsData[name] = arc[name].data

                    except:
                        pass

        # add them to our level
        newID = len(globals.Level.areas) + 1

        if not self.HandleSaveNewArea(course, L0, L1, L2): return
        self.LoadLevel(None, self.fileSavePath, True, newID)

    def HandleDeleteArea(self):
        """
        Deletes the current area
        """
        result = QtWidgets.QMessageBox.warning(self, 'Pyamoto', 'Are you <b>sure</b> you want to delete this area?<br><br>The level will automatically save afterwards - there is no way<br>you can undo the deletion or get it back afterwards!',
                                               QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                               QtWidgets.QMessageBox.No)
        if result == QtWidgets.QMessageBox.No: return

        if globals.Dirty:
            con_msg = "You need to save this level before importing/deleting Areas.\nDo you want to save now?"
            reply = QtWidgets.QMessageBox.question(self, 'Message',
                                                   con_msg, QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)

            if reply != QtWidgets.QMessageBox.Yes or not self.HandleSave():
                return

        globals.Level.deleteArea(globals.Area.areanum)

        # no error checking. if it saved last time, it will probably work now

        name = None
        if self._usesOuterSarc():
            name = self.getInnerSarcName()
            if name == '':
                return

        if self.fileSavePath.endswith('.szs') and not globals.IsNSMBUDX:
            yaz0.compressFASTYZ(
                globals.Level.saveNewArea(None, None, None, None, name),
                self.fileSavePath,
            )

        else:
            with open(self.fileSavePath, 'wb+') as f:
                f.write(globals.Level.saveNewArea(None, None, None, None, name))

        if globals.CurrentArea in globals.ObjectAddedtoEmbedded:  # Should always be true
            del globals.ObjectAddedtoEmbedded[globals.CurrentArea]

        self.LoadLevel(None, self.fileSavePath, True, 1)

    def HandleShowDataFolder(self):
        """
        Open the Pyamoto user data folder in the system file manager
        """
        path = globals.user_data_path
        os.makedirs(path, exist_ok=True)
        from PyQt5.QtGui import QDesktopServices
        from PyQt5.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def HandleInteractiveSetup(self):
        """
        Re-run the Interactive Setup wizard from the menu
        """
        from .firstRunWizard import InteractiveSetupDialog
        dlg = InteractiveSetupDialog(first_run=False, parent=self)
        dlg.exec_()
        if dlg.result() == QtWidgets.QDialog.Accepted:
            dlg.applySettings()
            LoadTheme()
            SetAppStyle()
            self.updateOpenByNameState()

    def HandlePreferences(self):
        """
        Edit Miyamoto preferences
        """

        # Show the dialog
        dlg = PreferencesDialog()
        if dlg.exec_() == QtWidgets.QDialog.Rejected:
            return

        # Get the Menubar setting
        setSetting('Menu', 'Menubar')

        # Determine the pivotal rotation animation FPS
        SLib.RotationFPS = dlg.generalTab.rotationFPS.value()
        setSetting('RotationFPS', SLib.RotationFPS)
        if SLib.RotationTimer.isActive():
            SLib.RotationTimer.setInterval(round(1000 / SLib.RotationFPS))

        # Determine if the inner sarc name should be modifiable
        globals.UseOuterSarcFormat = dlg.generalTab.useOuterSarcFormat.isChecked()
        setSetting('UseOuterSarcFormat', globals.UseOuterSarcFormat)

        # (the checkbox doesn't exist when the dialog was opened under Deluxe)
        if hasattr(dlg.generalTab, 'modifyInnerName'):
            globals.ModifyInnerName = dlg.generalTab.modifyInnerName.isChecked()
            setSetting('ModifyInnerName', globals.ModifyInnerName)

        # Get the File Opening Behavior setting
        setSetting('OpenMethodMode', dlg.generalTab.openMethod.currentIndex())

        # Get the Launch Behavior setting
        setSetting('LaunchBehavior', dlg.generalTab.launchBehavior.currentIndex())

        # Updates
        from .updater import _CHANNEL_VALUES
        idx = dlg.generalTab.updateChannel.currentIndex()
        setSetting('UpdateChannel', _CHANNEL_VALUES[idx] if 0 <= idx < len(_CHANNEL_VALUES) else 'release')

        # Get the Editor preferences
        setSetting('ShowActorNotes', dlg.editorTab.showActorNotes.isChecked())
        setSetting('ShowInfoIcons', dlg.editorTab.showInfoIcons.isChecked())

        globals.CategorizedSpriteData = dlg.editorTab.categorizedSpriteData.isChecked()
        setSetting('CategorizedSpriteData', globals.CategorizedSpriteData)

        globals.OverwriteSprite = not dlg.editorTab.overwriteActors.isChecked()
        setSetting('OverwriteSprite', globals.OverwriteSprite)

        globals.PlaceObjectFullSize = dlg.editorTab.placeFullSize.isChecked()
        setSetting('PlaceObjectFullSize', globals.PlaceObjectFullSize)

        globals.SpriteListPreviewSize = dlg.editorTab.spriteListPreview.currentData()
        setSetting('SpriteListPreviewSize', globals.SpriteListPreviewSize)

        globals.SpriteListPreviewHighDetail = dlg.editorTab.spriteListPreviewHighDetail.isChecked()
        setSetting('SpriteListPreviewHighDetail', globals.SpriteListPreviewHighDetail)
        self.spriteList.scheduleDelayedItemsLayout()
        self.spriteList.viewport().update()
        self.sprPicker.scheduleDelayedItemsLayout()
        self.sprPicker.viewport().update()

        # Get the Toolbar tab settings
        boxes = (
        dlg.toolbarTab.FileBoxes, dlg.toolbarTab.EditBoxes, dlg.toolbarTab.ViewBoxes, dlg.toolbarTab.SettingsBoxes,
        dlg.toolbarTab.SpritedataBoxes, dlg.toolbarTab.HelpBoxes)
        ToolbarSettings = {}
        for boxList in boxes:
            for box in boxList:
                ToolbarSettings[box.InternalName] = box.isChecked()
        setSetting('ToolbarActs', ToolbarSettings)

        # Get the theme settings
        setSetting('Theme', dlg.themesTab.themeBox.currentText())
        setSetting('uiStyle', dlg.themesTab.NonWinStyle.currentText())

        # Get the UI scale setting (stored as a fractional multiplier)
        setSetting('UIScale', round(dlg.themesTab.uiScale.value()) / 100.0)

        # Save install paths from the Resources tab
        new_data_path = dlg.resourcesTab.dataPathEdit.text().strip()
        if new_data_path:
            setSetting('DataPath', new_data_path)
            globals.actor_data_path = new_data_path.replace("\\", "/")
        new_obj_path = dlg.resourcesTab.objPathEdit.text().strip()
        if new_obj_path:
            setSetting('ObjPath', new_obj_path)

        # Save game paths from the Game Setup tab
        for folder, path_edit in dlg.gameSetupTab._path_edits.items():
            p = path_edit.text().strip()
            setSetting('GamePath_' + folder, p)
            if folder == 'NSMBU':
                setSetting('GamePath', p)  # backward compat

        # Save per-mod game paths
        for folder, path in dlg.gameSetupTab.getModPaths().items():
            if path:
                setSetting('GamePath_mod_' + folder, path)

        # Save base game + active mods; reload if either changed
        new_base = dlg.gameSetupTab.getSelectedBaseGame()
        old_base = setting('LastBaseGame', 'NSMBU')
        new_mods = dlg.gameSetupTab.getActiveMods()
        old_mods = setting('LastMods') or []
        if isinstance(old_mods, str):
            old_mods = [old_mods]
        if new_base != old_base or new_mods != old_mods:
            from . import loading as _loading
            from .gamedefs import IsBaseGameDX
            platformChanges = IsBaseGameDX(new_base) != globals.IsNSMBUDX

            # Wii U and Deluxe levels use different byte orders and tileset storage, so
            # the open level can't be carried over: confirm, then start a new level.
            if platformChanges and self.CheckDirty():
                pass  # cancelled: stay on the current game

            else:
                _loading.LoadGameDef(new_base, new_mods, dlg=True)
                if platformChanges:
                    self.updateOpenByNameState()
                    self.LoadLevel(None, None, False, 1, True)

            del _loading

        # Get the tileset settings
        globals.UseRGBA8 = dlg.tilesetsTab.useRGBA8.isChecked()
        setSetting('UseRGBA8', globals.UseRGBA8)
        
        setSetting('OverrideTilesetSaving', dlg.tilesetsTab.alwaysRepack.isChecked())
        setSetting('AutoSaveTilesets', dlg.tilesetsTab.autoSave.isChecked())

        # Warn the user only if they changed a setting that requires a restart (theme or toolbar)
        if dlg.needsRestart():
            QtWidgets.QMessageBox.warning(None, 'Pyamoto Preferences', 'You may need to restart Pyamoto for changes to take effect.')

    def updateOpenByNameState(self):
        """Enable or disable Open Level by Name based on whether any game path exists."""
        from .misc import hasLevelNameSources
        enabled = hasLevelNameSources()
        if 'openfromname' in self.actions:
            self.actions['openfromname'].setEnabled(enabled)

    def HandleNewLevel(self):
        """
        Create a new level
        """
        if self.CheckDirty(): return

        self.LoadLevel(None, None, False, 1, True)

    def HandleOpenFromName(self):
        """
        Open a level using the tabbed level picker.
        Each tab has its own levelnames and associated game path.
        """
        if self.CheckDirty(): return

        dlg = ChooseLevelNameDialog()
        if dlg.exec_() != QtWidgets.QDialog.Accepted or not dlg.currentlevel:
            return

        level_name = dlg.currentlevel
        game_path = (dlg.current_game_path or '').strip()
        display_name = dlg.current_display_name or level_name
        tab_name = dlg.current_tab_name or ''
        recent_label = f'{display_name} ({tab_name})' if tab_name else display_name

        if game_path:
            # Try to resolve the full path using the tab's specific game path
            for ext in globals.FileExtentions:
                full = os.path.join(game_path, level_name + ext)
                if os.path.isfile(full):
                    self.LoadLevelWithWindowPrompt(full)
                    self.RecentMenu.AddToList(full, recent_label)
                    return
            # File not found in that game path — warn but don't fall through silently
            QtWidgets.QMessageBox.warning(
                self, 'Pyamoto',
                f'Could not find "{level_name}" in:\n{game_path}\n\n'
                'Check the game path for this game in Preferences → Game Setup.',
                QtWidgets.QMessageBox.Ok)
        else:
            # No game path set — resolve against the default game path
            full = None
            for ext in globals.FileExtentions:
                candidate = os.path.join(globals.gamedef.GetGamePath(), level_name + ext)
                if os.path.isfile(candidate):
                    full = candidate
                    break
            if full:
                self.LoadLevelWithWindowPrompt(full)
                self.RecentMenu.AddToList(full, recent_label)
            else:
                self.LoadLevel(None, level_name, False, 1, True)
                self.RecentMenu.AddToList(level_name, recent_label)

    def HandleOpenFromFile(self):
        """
        Open a level using the filename
        """
        if self.CheckDirty(): return

        filetypes = levelFileFilters()
        
        last_dir = str(setting('LastFilePath')) if globals.settings.contains('LastFilePath') else ''
        fn = QtWidgets.QFileDialog.getOpenFileName(self, 'Choose a level archive', last_dir, filetypes)[0]
        if fn == '': return
        
        filepath = str(fn)
        setSetting('LastFilePath', os.path.dirname(filepath))

        self.LoadLevelWithWindowPrompt(filepath)

    def LoadLevelWithWindowPrompt(self, filepath):
        """
        Asks the user if they want to open the level in the current window or a new instance
        """
        if not globals.Area:
            # First file being opened, just open it
            self.LoadLevel(None, filepath, True, 1, True)
            return

        mode = setting('OpenMethodMode', 0)
        if mode == 1: # Same Window
            if self.CheckDirty(): return
            self.LoadLevel(None, filepath, True, 1, True)
            return
        elif mode == 2: # New Window
            self.LaunchNewInstance(filepath)
            return

        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle('Choose a level archive')
        msg.setText(f"How would you like to open this file?\n\n{os.path.basename(filepath)}")
        
        btn_current = msg.addButton("Current Window", QtWidgets.QMessageBox.AcceptRole)
        btn_new = msg.addButton("New Window", QtWidgets.QMessageBox.AcceptRole)
        btn_cancel = msg.addButton(QtWidgets.QMessageBox.Cancel)
        
        msg.setDefaultButton(btn_current)
        msg.exec_()
        
        if msg.clickedButton() == btn_current:
            if self.CheckDirty(): return
            self.LoadLevel(None, filepath, True, 1, True)
        elif msg.clickedButton() == btn_new:
            self.LaunchNewInstance(filepath)

    def LaunchNewInstance(self, filepath):
        """
        Launches a new instance of Miyamoto with the given file
        """
        python_exe = sys.executable
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'pyamoto.py',
        )
        try:
            subprocess.Popen([python_exe, script_path, '-level', filepath])
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Could not launch new window: {str(e)}")
        
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            fn = url.toLocalFile()
            if fn.lower().endswith(('.szs', '.sarc')):
                filepath = str(fn)
                setSetting('LastFilePath', os.path.dirname(filepath))
                self.LoadLevelWithWindowPrompt(filepath)
                break

    def HandleSave(self):
        """
        Save a level back to the archive
        """
        if not self.fileSavePath:
            return self.HandleSaveAs()

        name = None
        if self._usesOuterSarc():
            name = self.getInnerSarcName()
            if name == '':
                return False

        try:
            data = globals.Level.save(name)
        except ValueError as e:
            QtWidgets.QMessageBox.warning(None, 'Save Error', str(e))
            return False

        if len(data) > 73295462 and not globals.IsNSMBUDX:
            QtWidgets.QMessageBox.warning(None, 'Warning',
                                          "This level's uncompressed size has exceeded 70 MB, which is the maximum capacity NSMBU can handle.<br>It's recommended to make this level smaller to prevent the game from crashing.<br>This can be done by doing some of the following:<br>- Deleting all instances of some actors with a high filesize.<br>- Having less areas.<br>- Having less used tiles or objects per area.<br>- Disabling lossless compression (RGBA8) for tilesets.<br>")

        try:
            if self.fileSavePath.endswith('.szs') and not globals.IsNSMBUDX:
                yaz0.compressFASTYZ(data, self.fileSavePath)

            else:
                with open(self.fileSavePath, 'wb+') as f:
                    f.write(data)

        except IOError as e:
            QtWidgets.QMessageBox.warning(None, 'Error',
                                          'Error while Pyamoto was trying to save the level:<br>(#[err1]) [err2]<br><br>(Your work has not been saved! Try saving it under a different filename or in a different folder.)'.replace('[err1]', str(e.args[0])).replace('[err2]', str(e.args[1])))
            return False

        globals.Dirty = False
        globals.AutoSaveDirty = False
        globals.TilesetEdited = False
        self.UpdateTitle()

        # setSetting('AutoSaveFilePath', self.fileSavePath)
        # setSetting('AutoSaveFileData', 'x')
        return True

    def HandleSaveNewArea(self, course, L0, L1, L2):
        """
        Save a level back to the archive
        """
        if not self.fileSavePath:
            return self.HandleSaveAs()

        name = None
        if self._usesOuterSarc():
            name = self.getInnerSarcName()
            if name == '':
                return False

        try:
            data = globals.Level.saveNewArea(course, L0, L1, L2, name)
        except ValueError as e:
            QtWidgets.QMessageBox.warning(None, 'Save Error', str(e))
            return False

        if len(data) > 73295462 and not globals.IsNSMBUDX:
            QtWidgets.QMessageBox.warning(None, 'Warning',
                                          "This level's uncompressed size has exceeded 70 MB, which is the maximum capacity NSMBU can handle.<br>It's recommended to make this level smaller to prevent the game from crashing.<br>This can be done by doing some of the following:<br>- Deleting all instances of some actors with a high filesize.<br>- Having less areas.<br>- Having less used tiles or objects per area.<br>- Disabling lossless compression (RGBA8) for tilesets.<br>")

        try:
            if self.fileSavePath.endswith('.szs') and not globals.IsNSMBUDX:
                yaz0.compressFASTYZ(data, self.fileSavePath)

            else:
                with open(self.fileSavePath, 'wb+') as f:
                    f.write(data)

        except IOError as e:
            QtWidgets.QMessageBox.warning(None, 'Error',
                                          'Error while Pyamoto was trying to save the level:<br>(#[err1]) [err2]<br><br>(Your work has not been saved! Try saving it under a different filename or in a different folder.)'.replace('[err1]', str(e.args[0])).replace('[err2]', str(e.args[1])))
            return False

        globals.Dirty = False
        globals.AutoSaveDirty = False
        globals.TilesetEdited = False
        self.UpdateTitle()

        # setSetting('AutoSaveFilePath', self.fileSavePath)
        # setSetting('AutoSaveFileData', 'x')
        return True

    def HandleSaveAs(self):
        """
        Save a level back to the archive, with a new filename
        """
        filetypes = levelFileFilters(forSave=True)
        
        last_dir = str(setting('LastFilePath')) if globals.settings.contains('LastFilePath') else ''
        fn = QtWidgets.QFileDialog.getSaveFileName(self, 'Choose a level archive', last_dir, filetypes)[0]
        if fn == '': return False
        fn = str(fn)
        if globals.IsNSMBUDX and not fn.lower().endswith('.sarc'):
            fn = (os.path.splitext(fn)[0] if fn.lower().endswith('.szs') else fn) + '.sarc'
        setSetting('LastFilePath', os.path.dirname(fn))

        self.fileSavePath = fn
        self.fileTitle = os.path.basename(fn)

        name = None
        if self._usesOuterSarc():
            name = self.getInnerSarcName()
            if name == '':
                return False
            if "-" not in name:
                warningBox = QtWidgets.QMessageBox(QtWidgets.QMessageBox.NoIcon, 'Name warning',
                                                   'The input name does not include a -, which is what retail levels use. \nThis may crash, because it does not fit the proper format.')
                warningBox.exec_()

        try:
            data = globals.Level.save(name)
        except ValueError as e:
            QtWidgets.QMessageBox.warning(None, 'Save Error', str(e))
            return False

        if len(data) > 73295462 and not globals.IsNSMBUDX:
            QtWidgets.QMessageBox.warning(None, 'Warning',
                                          "This level's uncompressed size has exceeded 70 MB, which is the maximum capacity NSMBU can handle.<br>It's recommended to make this level smaller to prevent the game from crashing.<br>This can be done by doing some of the following:<br>- Deleting all instances of some actors with a high filesize.<br>- Having less areas.<br>- Having less used tiles or objects per area.<br>- Disabling lossless compression (RGBA8) for tilesets.<br>")

        try:
            if self.fileSavePath.endswith('.szs') and not globals.IsNSMBUDX:
                yaz0.compressFASTYZ(data, self.fileSavePath)

            else:
                with open(self.fileSavePath, 'wb+') as f:
                    f.write(data)

        except IOError as e:
            QtWidgets.QMessageBox.warning(None, 'Error',
                                          'Error while Pyamoto was trying to save the level:<br>(#[err1]) [err2]<br><br>(Your work has not been saved! Try saving it under a different filename or in a different folder.)'.replace('[err1]', str(e.args[0])).replace('[err2]', str(e.args[1])))
            return False

        globals.Dirty = False
        globals.AutoSaveDirty = False
        globals.TilesetEdited = False
        self.UpdateTitle()

        self.RecentMenu.AddToList(self.fileSavePath)

        return True

    def HandleExit(self):
        """
        Exit the editor. Why would you want to do this anyway?
        """
        self.close()

    def _levelMatchesGame(self, levelData):
        """
        Wii U levels are big-endian SARCs and Deluxe levels are little-endian. Opening one
        with the other game selected would misread (and then corrupt) it, so offer to
        switch games instead. Returns False if the level should not be loaded.
        """
        if not levelData or len(levelData) < 8 or levelData[:4] != b'SARC':
            return True

        isDeluxeLevel = levelData[6:8] == b'\xff\xfe'
        if isDeluxeLevel == bool(globals.IsNSMBUDX):
            return True

        wanted, current, target = (
            ('Deluxe', 'Wii U', 'NSMBUDX') if isDeluxeLevel else ('Wii U', 'Deluxe', 'NSMBU'))

        reply = QtWidgets.QMessageBox.question(
            self, 'Pyamoto',
            'This looks like a New Super Mario Bros. U %s level, but the %s version is selected.\n\n'
            'Switch to the %s version? (Active mods will be turned off.)' % (wanted, current, wanted),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)

        if reply != QtWidgets.QMessageBox.Yes:
            return False

        # (Unsaved changes were already confirmed by whoever asked to open this level.)
        from . import loading as _loading
        _loading.LoadGameDef(target, [], dlg=True)
        self.updateOpenByNameState()
        return True

    @staticmethod
    def _usesOuterSarc():
        """The outer-SARC level wrapper is Wii U-only; Deluxe levels are flat archives."""
        return bool(globals.UseOuterSarcFormat and not globals.IsNSMBUDX)

    def getInnerSarcName(self):
        name = os.path.splitext(self.fileTitle)[0]
        if not name or "/" in name or "\\" in name or globals.ModifyInnerName:
            name = QtWidgets.QInputDialog.getText(self, "Choose Internal Name",
                                                  "Choose an internal filename for this level (do not add a .sarc/.szs extension) (example: 1-1):"
                                                  "\n(To make Miyamoto automatically set the internal filename to the filename of the level file,"
                                                  "\nGo to Preferences and uncheck \"Modify Internal Name\".)",
                                                  QtWidgets.QLineEdit.Normal)[0]

            if "/" in name or "\\" in name:
                warningBox = QtWidgets.QMessageBox(QtWidgets.QMessageBox.NoIcon, 'Name warning', r'The input name included "/" or "\", aborting...')
                warningBox.exec_()
                return ''

        return name

    def HandleSwitchArea(self, idx):
        """
        Handle activated signals for areaComboBox
        """
        prevIdx = globals.Area.areanum - 1
        if idx == prevIdx:
            return

        if self.CheckDirty() or not self.LoadLevel(None, self.fileSavePath, True, idx + 1):
            globals.Area.areanum = prevIdx + 1
            self.areaComboBox.setCurrentIndex(prevIdx)

    def HandleUpdateLayer0(self, checked):
        """
        Handle toggling of layer 0 being shown
        """
        globals.Layer0Shown = checked

        if globals.Area is not None:
            for obj in globals.Area.layers[0]:
                obj.setVisible(globals.Layer0Shown)

        self.scene.update()

    def HandleUpdateLayer1(self, checked):
        """
        Handle toggling of layer 1 being shown
        """
        globals.Layer1Shown = checked

        if globals.Area is not None:
            for obj in globals.Area.layers[1]:
                obj.setVisible(globals.Layer1Shown)

        self.scene.update()

    def HandleUpdateLayer2(self, checked):
        """
        Handle toggling of layer 2 being shown
        """
        globals.Layer2Shown = checked

        if globals.Area is not None:
            for obj in globals.Area.layers[2]:
                obj.setVisible(globals.Layer2Shown)

        self.scene.update()

    def HandleTilesetAnimToggle(self, checked):
        """
        Handle toggling of tileset animations
        """
        globals.TilesetsAnimating = checked
        for tile in globals.Tiles:
            if tile is not None: tile.resetAnimation()

        self.scene.update()

    def HandleCollisionsToggle(self, checked):
        """
        Handle toggling of tileset collisions viewing
        """
        globals.CollisionsShown = checked

        setSetting('ShowCollisions', globals.CollisionsShown)
        self.scene.update()

    def HandleRealViewToggle(self, checked):
        """
        Handle toggling of Real View
        """
        globals.RealViewEnabled = checked
        SLib.RealViewEnabled = globals.RealViewEnabled

        setSetting('RealViewEnabled', globals.RealViewEnabled)
        self.scene.update()

    def HandleSpritesVisibility(self, checked):
        """
        Handle toggling of sprite visibility
        """
        globals.SpritesShown = checked

        if globals.Area is not None:
            for spr in globals.Area.sprites:
                spr.setVisible(globals.SpritesShown)

        setSetting('ShowSprites', globals.SpritesShown)
        self.scene.update()

    def HandleSpriteImages(self, checked):
        """
        Handle toggling of sprite images
        """
        globals.SpriteImagesShown = checked
        setSetting('ShowSpriteImages', globals.SpriteImagesShown)

        if globals.Area is not None:
            globals.OverrideSnapping = True
            globals.DirtyOverride += 1
            for spr in globals.Area.sprites:
                spr.UpdateRects()
                if globals.SpriteImagesShown and not globals.Initializing:
                    spr.setPos(
                        (spr.objx + spr.ImageObj.xOffset) * (globals.TileWidth / 16),
                        (spr.objy + spr.ImageObj.yOffset) * (globals.TileWidth / 16),
                    )
                elif not globals.Initializing:
                    spr.setPos(
                        spr.objx * (globals.TileWidth / 16),
                        spr.objy * (globals.TileWidth / 16),
                    )
                spr.UpdateDynamicSizing()
            globals.DirtyOverride -= 1
            globals.OverrideSnapping = False

        self.scene.update()
        self.levelOverview.update()

    def HandleRotationPreview(self, checked):
        """
        Handle toggling of sprite images
        """
        globals.RotationShown = checked
        setSetting('RotationShown', globals.RotationShown)

        SLib.RotationFrame = 0

        globals.OverrideSnapping = True
        globals.DirtyOverride += 1
        if globals.Area is not None:
            for spr in globals.Area.sprites:
                if isinstance(spr.ImageObj, SLib.SpriteImage_MovementControlled) and spr.ImageObj.controller:
                    spr.UpdateDynamicSizing()
        globals.DirtyOverride -= 1
        globals.OverrideSnapping = False

        if globals.Area is not None and globals.RotationShown:
            SLib.RotationTimer.start(round(1000 / SLib.RotationFPS))

        else:
            SLib.RotationTimer.stop()

        self.scene.update()
        self.levelOverview.update()

    def HandleLocationsVisibility(self, checked):
        """
        Handle toggling of location visibility
        """
        globals.LocationsShown = checked

        if globals.Area is not None:
            for loc in globals.Area.locations:
                loc.setVisible(globals.LocationsShown)

        setSetting('ShowLocations', globals.LocationsShown)
        self.scene.update()

    def HandleCommentsVisibility(self, checked):
        """
        Handle toggling of comment visibility
        """
        globals.CommentsShown = checked

        if globals.Area is not None:
            for com in globals.Area.comments:
                com.setVisible(globals.CommentsShown)

            if not globals.CommentsShown:
                for com in globals.Area.comments:
                    com.TextEdit.setVisible(False)

        setSetting('ShowComments', globals.CommentsShown)
        self.scene.update()

    def HandlePathsVisibility(self, checked):
        """
        Handle toggling of path visibility
        """
        globals.PathsShown = checked

        if globals.Area is not None:
            for node in globals.Area.paths:
                node.setVisible(globals.PathsShown)

            for node in globals.Area.nPaths:
                node.setVisible(globals.PathsShown)

            for path in globals.Area.pathdata:
                path['peline'].setVisible(globals.PathsShown)

            if globals.Area.nPathdata:
                globals.Area.nPathdata['peline'].setVisible(globals.PathsShown)

        setSetting('ShowPaths', globals.PathsShown)
        self.scene.update()

    def HandleObjectsFreeze(self, checked):
        """
        Handle toggling of objects being frozen
        """
        globals.ObjectsFrozen = checked
        flag1 = QtWidgets.QGraphicsItem.ItemIsSelectable
        flag2 = QtWidgets.QGraphicsItem.ItemIsMovable

        if globals.Area is not None:
            for layer in globals.Area.layers:
                for obj in layer:
                    obj.setFlag(flag1, not globals.ObjectsFrozen)
                    obj.setFlag(flag2, not globals.ObjectsFrozen)

        setSetting('FreezeObjects', globals.ObjectsFrozen)
        self.scene.update()

    def HandleSpritesFreeze(self, checked):
        """
        Handle toggling of sprites being frozen
        """
        globals.SpritesFrozen = checked
        flag1 = QtWidgets.QGraphicsItem.ItemIsSelectable
        flag2 = QtWidgets.QGraphicsItem.ItemIsMovable

        if globals.Area is not None:
            for spr in globals.Area.sprites:
                spr.setFlag(flag1, not globals.SpritesFrozen)
                spr.setFlag(flag2, not globals.SpritesFrozen)

        setSetting('FreezeSprites', globals.SpritesFrozen)
        self.scene.update()

    def HandleEntrancesFreeze(self, checked):
        """
        Handle toggling of entrances being frozen
        """
        globals.EntrancesFrozen = checked
        flag1 = QtWidgets.QGraphicsItem.ItemIsSelectable
        flag2 = QtWidgets.QGraphicsItem.ItemIsMovable

        if globals.Area is not None:
            for ent in globals.Area.entrances:
                ent.setFlag(flag1, not globals.EntrancesFrozen)
                ent.setFlag(flag2, not globals.EntrancesFrozen)

        setSetting('FreezeEntrances', globals.EntrancesFrozen)
        self.scene.update()

    def HandleLocationsFreeze(self, checked):
        """
        Handle toggling of locations being frozen
        """
        globals.LocationsFrozen = checked
        flag1 = QtWidgets.QGraphicsItem.ItemIsSelectable
        flag2 = QtWidgets.QGraphicsItem.ItemIsMovable

        if globals.Area is not None:
            for loc in globals.Area.locations:
                loc.setFlag(flag1, not globals.LocationsFrozen)
                loc.setFlag(flag2, not globals.LocationsFrozen)

        setSetting('FreezeLocations', globals.LocationsFrozen)
        self.scene.update()

    def HandlePathsFreeze(self, checked):
        """
        Handle toggling of paths being frozen
        """
        globals.PathsFrozen = checked
        flag1 = QtWidgets.QGraphicsItem.ItemIsSelectable
        flag2 = QtWidgets.QGraphicsItem.ItemIsMovable

        if globals.Area is not None:
            for node in globals.Area.paths:
                node.setFlag(flag1, not globals.PathsFrozen)
                node.setFlag(flag2, not globals.PathsFrozen)

            for node in globals.Area.nPaths:
                node.setFlag(flag1, not globals.PathsFrozen)
                node.setFlag(flag2, not globals.PathsFrozen)

        setSetting('FreezePaths', globals.PathsFrozen)
        self.scene.update()

    def HandleCommentsFreeze(self, checked):
        """
        Handle toggling of comments being frozen
        """
        globals.CommentsFrozen = checked
        flag1 = QtWidgets.QGraphicsItem.ItemIsSelectable
        flag2 = QtWidgets.QGraphicsItem.ItemIsMovable

        if globals.Area is not None:
            for com in globals.Area.comments:
                com.setFlag(flag1, not globals.CommentsFrozen)
                com.setFlag(flag2, not globals.CommentsFrozen)

        setSetting('FreezeComments', globals.CommentsFrozen)
        self.scene.update()

    def HandleViewSpritemap(self, checked):
        """
        Handle viewing the spritemap popup
        """
        from .dialogs import SpritemapDialog
        dlg = SpritemapDialog(self)
        dlg.exec_()

    def EditTilesets(self, slot):
        """
        Handle editing a specific tileset slot
        """
        pass

    def HandleFullscreen(self, checked):
        """
        Handle fullscreen mode
        """
        if checked:
            self.showFullScreen()
        else:
            self.showMaximized()

    def HandleSwitchGrid(self):
        """
        Handle switching of the grid view
        """
        if globals.GridType is None:
            globals.GridType = 'grid'
        elif globals.GridType == 'grid':
            globals.GridType = 'checker'
        else:
            globals.GridType = None

        setSetting('GridType', globals.GridType)
        self.scene.update()

    def HandleZoomIn(self):
        """
        Handle zooming in
        """
        z = self.ZoomLevel
        zi = self.ZoomLevels.index(z)
        zi += 1
        if zi < len(self.ZoomLevels):
            self.ZoomTo(self.ZoomLevels[zi])

    def HandleZoomOut(self):
        """
        Handle zooming out
        """
        z = self.ZoomLevel
        zi = self.ZoomLevels.index(z)
        zi -= 1
        if zi >= 0:
            self.ZoomTo(self.ZoomLevels[zi])

    def HandleZoomActual(self):
        """
        Handle zooming to the actual size
        """
        self.ZoomTo(100.0)

    def HandleZoomMin(self):
        """
        Handle zooming to the minimum size
        """
        self.ZoomTo(self.ZoomLevels[0])

    def HandleZoomMax(self):
        """
        Handle zooming to the maximum size
        """
        self.ZoomTo(self.ZoomLevels[len(self.ZoomLevels) - 1])

    def ZoomTo(self, z):
        """
        Zoom to a specific level
        """
        zEffective = z / globals.TileWidth * 24  # "100%" zoom level produces 24x24 level view
        tr = QtGui.QTransform()
        tr.scale(zEffective / 100.0, zEffective / 100.0)
        self.ZoomLevel = z
        self.view.setTransform(tr)
        self.levelOverview.mainWindowScale = zEffective / 100.0

        zi = self.ZoomLevels.index(z)
        self.actions['zoommax'].setEnabled(zi < len(self.ZoomLevels) - 1)
        self.actions['zoomin'].setEnabled(zi < len(self.ZoomLevels) - 1)
        self.actions['zoomactual'].setEnabled(z != 100.0)
        self.actions['zoomout'].setEnabled(zi > 0)
        self.actions['zoommin'].setEnabled(zi > 0)

        self.ZoomWidget.setZoomLevel(z)
        self.ZoomStatusWidget.setZoomLevel(z)

        # Update the zone grabber rects, to resize for the new zoom level
        for z in globals.Area.zones:
            z.UpdateRects()

        self.scene.update()

    def HandleOverviewClick(self, x, y):
        """
        Handle position changes from the level overview
        """
        self.view.centerOn(x, y)
        self.levelOverview.update()

    def SaveComments(self):
        """
        Saves the comments data back to self.Metadata
        """
        b = []
        for com in globals.Area.comments:
            xpos, ypos, tlen = com.objx, com.objy, len(com.text)
            b.append(xpos >> 24)
            b.append((xpos >> 16) & 0xFF)
            b.append((xpos >> 8) & 0xFF)
            b.append(xpos & 0xFF)
            b.append(ypos >> 24)
            b.append((ypos >> 16) & 0xFF)
            b.append((ypos >> 8) & 0xFF)
            b.append(ypos & 0xFF)
            b.append(tlen >> 24)
            b.append((tlen >> 16) & 0xFF)
            b.append((tlen >> 8) & 0xFF)
            b.append(tlen & 0xFF)
            for char in com.text: b.append(ord(char))
        globals.Area.Metadata.setBinData('InLevelComments_A%d' % globals.Area.areanum, b)

    def closeEvent(self, event):
        """
        Handler for the main window close event
        """

        if self.CheckDirty():
            event.ignore()
        else:
            # save our state
            self.propEditorDock.setVisible(False)
            self.defaultPropDock.setVisible(False)

            SLib.RotationTimer.stop()

            # state: determines positions of docks
            # geometry: determines the main window position
            setSetting('MainWindowState', self.saveState(0))
            setSetting('MainWindowGeometry', self.saveGeometry())

            if hasattr(self, 'HelpBoxInstance'):
                self.HelpBoxInstance.close()

            if hasattr(self, 'TipsBoxInstance'):
                self.TipsBoxInstance.close()

            globals.gamedef.SetLastLevel(str(self.fileSavePath))

            setSetting('AutoSaveFilePath', 'none')
            setSetting('AutoSaveFileData', 'x')

            event.accept()

    def LoadDefaultTileset(self, name, silent=False, dirty=False):
        path = globals.miyamoto_path + "/miyamotoextras/%s.szs" % name
        if not os.path.isfile(path):
            if not silent:
                QtWidgets.QMessageBox.warning(self, 'Warning', '"%s.szs" not found in miyamotoextras!' \
                                                               '\nDid you download the main tilesets pack?' % name,
                                              QtWidgets.QMessageBox.Ok)

            return False

        with open(path, "rb") as inf:
            inb = inf.read()

        # Decompress, if needed (Yaz0)
        if inb.startswith(b'Yaz0'):
            print(f'Decompressing {name}...')
            data = yaz0.decompressFASTYZ(inb)
        else:
            data = inb
        globals.szsData[name] = data

        self.tilesets[0].append(name)

        if dirty:
            dirtyOverride = globals.DirtyOverride
            globals.DirtyOverride = 0
            SetDirty()
            globals.DirtyOverride = dirtyOverride

        return True

    def LoadLevel(self, game, name, isFullPath, areaNum, loadLevel=False):
        """
        Load a level from any game into the editor
        """
        new = name is None

        if new:
            # Preserve the current szsData and tilesets in case something goes wrong
            szsData = globals.szsData
            tilesets = self.tilesets if hasattr(self, 'tilesets') else [[], [], [], []]

            del globals.szsData
            if hasattr(self, 'tilesets'):
                del self.tilesets
            globals.szsData = {}
            self.tilesets = [[], [], [], []]

            for tileset_name in globals.Pa0Tilesets:
                ret = self.LoadDefaultTileset(tileset_name)
                if not ret:
                    # Something went wrong, restore szsData and tilesets
                    del globals.szsData
                    del self.tilesets
                    globals.szsData = szsData
                    self.tilesets = tilesets

                    return False

            # Nothing went wrong, delete szsData and tilesets backups
            del szsData
            del tilesets

            # Set the filepath variables
            self.fileSavePath = False
            self.fileTitle = 'untitled'

        else:
            globals.levName = os.path.basename(name)

            checknames = []
            if isFullPath:
                checknames = [name, ]
            else:
                for ext in globals.FileExtentions:
                    checknames.append(os.path.join(globals.gamedef.GetGamePath(), name + ext))

            for checkname in checknames:
                if os.path.isfile(checkname):
                    break
            else:
                QtWidgets.QMessageBox.warning(self, 'Pyamoto',
                                              'Could not find file:<br>[name]'.replace('[name]', str(checkname)),
                                              QtWidgets.QMessageBox.Ok)
                return False
            if not IsNSMBLevel(checkname):
                QtWidgets.QMessageBox.warning(self, 'Pyamoto', "This file doesn't seem to be a valid level.",
                                              QtWidgets.QMessageBox.Ok)
                return False

            name = checkname

            # Get the data
            if not globals.RestoredFromAutoSave:

                # Check if there is a file by this name
                if not os.path.isfile(name):
                    QtWidgets.QMessageBox.warning(None, 'Error',
                                                  'Cannot find the required level file [file].szs. Check your "course_res_pack" folder and make sure it exists.'.replace('[file]', str(name)))
                    return False

                # Set the filepath variables
                self.fileSavePath = name
                self.fileTitle = os.path.basename(self.fileSavePath)

                # Open the file
                with open(self.fileSavePath, 'rb') as fileobj:
                    levelData = fileobj.read()

                # Decompress, if needed (Yaz0)
                if levelData.startswith(b'Yaz0'):
                    print('Beginning Yaz0 decompression...')
                    levelData = yaz0.decompressFASTYZ(levelData)
                    print('Decompression finished.')

                elif levelData.startswith(b'SARC'):
                    print('Yaz0 decompression skipped.')

                else:
                    return False  # keep it from crashing by loading things it shouldn't

                if not self._levelMatchesGame(levelData):
                    return False

                arc = SarcLib.SARC_Archive()
                arc.load(levelData)

                def exists(fn):
                    nonlocal arc

                    try:
                        arc[fn]

                    except KeyError:
                        return False

                    return True

                def guessInnerName():
                    possibilities = []
                    possibilities.append(os.path.basename(self.fileSavePath))
                    possibilities.append(
                        os.path.basename(self.fileSavePath).split(' ')[-1])  # for names like "NSMBU 1-1.szs"
                    possibilities.append(
                        os.path.basename(self.fileSavePath).split(' ')[0])  # for names like "1-1 test.szs"
                    possibilities.append(os.path.basename(self.fileSavePath).split('.')[0])
                    possibilities.append(os.path.basename(self.fileSavePath).split('_')[0])

                    for fn in possibilities:
                        if exists(fn):
                            return arc[fn].data, fn

                    return None, ''

                levelname = ''

                if exists('levelname'):
                    fn = bytes_to_string(arc['levelname'].data)
                    if exists(fn):
                        levelFileData = arc[fn].data
                        levelname = fn
                    else:
                        levelFileData, levelname = guessInnerName()

                else:
                    levelFileData, levelname = guessInnerName()

                if not levelFileData:
                    if exists('course'):
                        levelFileData = levelData

                    else:
                        warningBox = QtWidgets.QMessageBox(QtWidgets.QMessageBox.NoIcon, 'OH NO',
                                                           'Couldn\'t find the inner level file. Aborting.')
                        warningBox.exec_()

                        return False

                # Sort the szs data
                globals.szsData = {}
                for file in arc.contents:
                    if isinstance(file, SarcLib.File) and (not levelname or file.name != levelname):
                        globals.szsData[file.name] = file.data

                # Get all tilesets in the level
                self.tilesets = [[], [], [], []]
                for fname in globals.szsData:
                    data = globals.szsData[fname]
                    if data[:4] != b'SARC':
                        continue

                    arc = SarcLib.SARC_Archive(data)

                    try:
                        arc['BG_tex/%s.gtx' % fname]
                        arc['BG_tex/%s_nml.gtx' % fname]
                        arc['BG_chk/d_bgchk_%s.bin' % fname]
                        indexfile = arc['BG_unt/%s_hd.bin' % fname].data
                        deffile = arc['BG_unt/%s.bin' % fname].data

                    except KeyError:
                        continue

                    objs = []
                    slots = []
                    objcount = len(indexfile) // 6
                    indexstruct = struct.Struct('>HBBH')

                    for i in range(objcount):
                        data = indexstruct.unpack_from(indexfile, i * 6)
                        obj = ObjectDef()
                        obj.load(deffile, data[0])

                        for row in obj.rows:
                            for tile in row:
                                if len(tile) == 3:
                                    slot = (tile[1] >> 8) & 3
                                    if slot:
                                        slots.append(slot)
                    if slots:
                        data = Counter(slots)
                        slot = max(slots, key=data.get)

                    else:
                        slot = 0

                    self.tilesets[slot].append(fname)

                print(self.tilesets)
                levelData = levelFileData

            else:
                # Auto-saved level. Check if there's a path associated with it:

                if globals.AutoSavePath == 'None':
                    self.fileSavePath = None
                    self.fileTitle = 'Untitled'
                else:
                    self.fileSavePath = globals.AutoSavePath
                    self.fileTitle = os.path.basename(name)

                # Get the level data
                levelData = globals.AutoSaveData
                SetDirty(noautosave=True)

                # Turn off the autosave flag
                globals.RestoredFromAutoSave = False

        # Turn the dirty flag off, and keep it that way
        globals.Dirty = False
        globals.DirtyOverride += 1

        # Here's how progress is tracked. (After the major refactor, it may be a bit messed up now.)
        # - 0: Loading level data
        # [Area.__init__ is entered here]
        # - 1: Loading tilesets [1/2/3/4 allocated for each tileset]
        # - 5: Loading layers
        # [Control is returned to LoadLevel_NSMBU]
        # - 6: Loading objects
        # - 7: Preparing editor

        # First, clear out the existing level.
        self.scene.clearSelection()
        self.CurrentSelection = []
        self.scene.clear()

        # Clear out all level-thing lists
        for thingList in (self.spriteList, self.entranceList, self.locationList, self.pathList, self.nabbitPathList, self.commentList):
            thingList.clear()
            thingList.selectionModel().setCurrentIndex(QtCore.QModelIndex(), QtCore.QItemSelectionModel.Clear)

        # Reset these here, because if they are set after
        # creating the objects, they use the old values.
        globals.CurrentLayer = 1
        globals.Layer0Shown = True
        globals.Layer1Shown = True
        globals.Layer2Shown = True
        globals.CurrentArea = areaNum
        globals.TilesetEdited = False

        if loadLevel:
            globals.ObjectAddedtoEmbedded = {}

        if globals.CurrentArea not in globals.ObjectAddedtoEmbedded:
            globals.ObjectAddedtoEmbedded[globals.CurrentArea] = {}

        # Prevent things from snapping when they're created
        globals.OverrideSnapping = True

        # Load the actual level
        if name is None:
            self.newLevel()

        else:
            self.LoadLevel_NSMBU(levelData, areaNum)

        # Refresh object layouts
        HandleTilesetEdited(True)
        for layer in globals.Area.layers:
            for obj in layer:
                obj.updateObjCache()
        for sprite in globals.Area.sprites:
            sprite.UpdateDynamicSizing()
            sprite.ImageObj.positionChanged()
        self.scene.update()


        # Set the level overview settings
        self.levelOverview.maxX = 100
        self.levelOverview.maxY = 40

        # Fill up the area list
        self.areaComboBox.clear()
        for i in range(1, len(globals.Level.areas) + 1):
            self.areaComboBox.addItem('Area [num]'.replace('[num]', str(i)))
        self.areaComboBox.setCurrentIndex(areaNum - 1)

        self.levelOverview.update()

        # Scroll to the initial entrance
        startEntID = globals.Area.startEntrance
        startEnt = None
        for ent in globals.Area.entrances:
            if ent.entid == startEntID: startEnt = ent

        if not startEnt:
            startEntID = globals.Area.startEntranceCoinBoost
            for ent in globals.Area.entrances:
                if ent.entid == startEntID: startEnt = ent

        self.view.centerOn(0, 0)
        if startEnt is not None: self.view.centerOn(startEnt.objx * (globals.TileWidth / 16), startEnt.objy * (globals.TileWidth / 16))
        self.ZoomTo(100.0)

        # Reset some editor things
        self.actions['showlay0'].setChecked(True)
        self.actions['showlay1'].setChecked(True)
        self.actions['showlay2'].setChecked(True)
        self.actions['addarea'].setEnabled(len(globals.Level.areas) < 4)
        self.actions['importarea'].setEnabled(len(globals.Level.areas) < 4)
        self.actions['deletearea'].setEnabled(len(globals.Level.areas) > 1)

        # Turn snapping back on
        globals.OverrideSnapping = False

        # Turn the dirty flag off
        globals.DirtyOverride -= 1
        self.UpdateTitle()

        # Update UI things
        self.scene.update(0, 0, self.scene.width(), self.scene.height())

        self.levelOverview.Reset()
        self.levelOverview.update()
        QtCore.QTimer.singleShot(20, self.levelOverview.update)
        self.updateNumUsedTilesLabel()

        if globals.UndoManager:
            globals.UndoManager.clear()

        if name is not None:
            # Add the path to Recent Files
            self.RecentMenu.AddToList(self.fileSavePath)

        # If we got this far, everything worked! Return True.
        return True

    def newLevel(self):
        globals.Level = Level_NSMBU()

        globals.Level.new()

        self.objUseLayer1.setChecked(True)

        self.ReloadTilesets()

        self.objTS0Tab.setLayout(self.createObjectLayout)
        self.objAllTab.setCurrentIndex(0)
        self.objAllTab.setTabEnabled(0, True)

        self.objPicker.LoadFromTilesets()

        if globals.UndoManager:
            globals.UndoManager.clear()

    def LoadLevel_NSMBU(self, levelData, areaNum):
        """
        Performs all level-loading tasks specific to New Super Mario Bros. U levels.
        Do not call this directly - use LoadLevel(NewSuperMarioBrosU, ...) instead!
        """

        # Create the new level object
        globals.Level = Level_NSMBU()

        # Load it
        if not globals.Level.load(levelData, areaNum):
            raise Exception

        self.objUseLayer1.setChecked(True)

        self.objPicker.LoadFromTilesets()

        if globals.Area.tileset0 != '':
            self.objAllTab.setCurrentIndex(0)
            self.objAllTab.setTabEnabled(0, True)

        else:
            self.objAllTab.setCurrentIndex(1)
            self.objAllTab.setTabEnabled(0, False)

        # Load events
        self.LoadEventTabFromLevel()

        # Add all things to the scene
        pcEvent = self.HandleObjPosChange
        for layer in reversed(globals.Area.layers):
            for obj in layer:
                obj.positionChanged = pcEvent
                self.scene.addItem(obj)

        pcEvent = self.HandleSprPosChange
        for spr in globals.Area.sprites:
            spr.positionChanged = pcEvent
            spr.listitem = ListWidgetItem_SortsByOther(spr)
            self.spriteList.addItem(spr.listitem)
            self.scene.addItem(spr)
            spr.UpdateListItem()

        pcEvent = self.HandleEntPosChange
        for ent in globals.Area.entrances:
            ent.positionChanged = pcEvent
            ent.listitem = ListWidgetItem_SortsByOther(ent)
            ent.listitem.entid = ent.entid
            self.entranceList.addItem(ent.listitem)
            self.scene.addItem(ent)
            ent.UpdateListItem()

        for zone in globals.Area.zones:
            self.scene.addItem(zone)

        pcEvent = self.HandleLocPosChange
        scEvent = self.HandleLocSizeChange
        for location in globals.Area.locations:
            location.positionChanged = pcEvent
            location.sizeChanged = scEvent
            location.listitem = ListWidgetItem_SortsByOther(location)
            self.locationList.addItem(location.listitem)
            self.scene.addItem(location)
            location.UpdateListItem()

        for path in globals.Area.pathdata:
            peline = PathEditorLineItem(path['nodes'])
            path['peline'] = peline
            self.scene.addItem(peline)
            peline.loops = path['loops']

        nPath = globals.Area.nPathdata
        if nPath:
            peline = NabbitPathEditorLineItem(nPath['nodes'])
            nPath['peline'] = peline
            self.scene.addItem(peline)

        for path in globals.Area.paths:
            path.positionChanged = self.HandlePathPosChange
            path.listitem = ListWidgetItem_SortsByOther(path)
            self.pathList.addItem(path.listitem)
            self.scene.addItem(path)
            path.UpdateListItem()

        for path in globals.Area.nPaths:
            path.positionChanged = self.HandlePathPosChange
            path.listitem = ListWidgetItem_SortsByOther(path)
            self.nabbitPathList.addItem(path.listitem)
            self.scene.addItem(path)
            path.UpdateListItem()

        for com in globals.Area.comments:
            com.positionChanged = self.HandleComPosChange
            com.textChanged = self.HandleComTxtChange
            com.listitem = QtWidgets.QListWidgetItem()
            self.commentList.addItem(com.listitem)
            self.scene.addItem(com)
            com.UpdateListItem()

        # Deluxe loads its tilesets from the game's Unit folder; there are no
        # bundled Wii U defaults to fall back to.
        if not globals.IsNSMBUDX:
            for tileset_name in globals.Pa0Tilesets:
                if tileset_name not in globals.szsData:
                    self.LoadDefaultTileset(tileset_name, True)

    def ReloadTilesets(self, soft=False):
        tilesets = [globals.Area.tileset0, globals.Area.tileset1, globals.Area.tileset2, globals.Area.tileset3]
        for idx, name in enumerate(tilesets):
            if (name is not None) and (name != ''):
                LoadTileset(idx, name, not soft)

        HandleTilesetEdited(True)

        for layer in globals.Area.layers:
            for obj in layer:
                obj.updateObjCache()

        self.scene.update()

    def ReloadSpriteData(self):
        LoadSpriteData()
        LoadSpriteListData(True)
        LoadSpriteCategories(True)

        self.spriteViewPicker.clear()
        for cat in globals.SpriteCategories:
            self.spriteViewPicker.addItem(cat[0])

        self.sprPicker.LoadItems()
        self.spriteViewPicker.setCurrentIndex(0)
        self.spriteDataEditor.setSprite(self.spriteDataEditor.spritetype, True)
        self.spriteDataEditor.update()

        self.NewSearchTerm(self.spriteSearchTerm.text())

        for sprite in globals.Area.sprites:
            sprite.InitializeSprite()

        self.scene.update()

    def ChangeSelectionHandler(self):
        """
        Update the visible panels whenever the selection changes
        """
        if self.SelectionUpdateFlag: return

        try:
            selitems = self.scene.selectedItems()
        except RuntimeError:
            # must catch this error: if you close the app while something is selected,
            # you get a RuntimeError about the 'underlying C++ object being deleted'
            return

        # do this to avoid flicker
        showSpritePanel = False
        showEntrancePanel = False
        showLocationPanel = False
        showPathPanel = False
        showNabbitPathPanel = False
        updateModeInfo = False

        # clear our variables
        self.selObj = None
        self.selObjs = None

        self.spriteList.setCurrentItem(None)
        self.entranceList.setCurrentItem(None)
        self.locationList.setCurrentItem(None)
        self.pathList.setCurrentItem(None)
        self.nabbitPathList.setCurrentItem(None)
        self.commentList.setCurrentItem(None)

        # possibly a small optimization
        func_ii = isinstance
        type_obj = ObjectItem
        type_spr = SpriteItem
        type_ent = EntranceItem
        type_loc = LocationItem
        type_path = PathItem
        type_nPath = NabbitPathItem
        type_com = CommentItem

        if len(selitems) == 0:
            # nothing is selected
            self.actions['cut'].setEnabled(False)
            self.actions['copy'].setEnabled(False)
            self.actions['duplicate'].setEnabled(False)
            self.actions['shiftitems'].setEnabled(False)
            self.actions['mergelocations'].setEnabled(False)

        elif len(selitems) == 1:
            # only one item, check the type
            self.actions['cut'].setEnabled(True)
            self.actions['copy'].setEnabled(True)
            self.actions['duplicate'].setEnabled(True)
            self.actions['shiftitems'].setEnabled(True)
            self.actions['mergelocations'].setEnabled(False)

            item = selitems[0]
            self.selObj = item
            if func_ii(item, type_spr):
                showSpritePanel = True
                updateModeInfo = True
            elif func_ii(item, type_ent):
                self.creationTabs.setCurrentIndex(2)
                self.UpdateFlag = True
                self.entranceList.setCurrentItem(item.listitem)
                self.UpdateFlag = False
                showEntrancePanel = True
                updateModeInfo = True
            elif func_ii(item, type_loc):
                self.creationTabs.setCurrentIndex(3)
                self.UpdateFlag = True
                self.locationList.setCurrentItem(item.listitem)
                self.UpdateFlag = False
                showLocationPanel = True
                updateModeInfo = True
            elif func_ii(item, type_path):
                self.creationTabs.setCurrentIndex(4)
                self.UpdateFlag = True
                self.pathList.setCurrentItem(item.listitem)
                self.UpdateFlag = False
                showPathPanel = True
                updateModeInfo = True
            elif func_ii(item, type_nPath):
                self.creationTabs.setCurrentIndex(5)
                self.UpdateFlag = True
                self.nabbitPathList.setCurrentItem(item.listitem)
                self.UpdateFlag = False
                showNabbitPathPanel = True
                updateModeInfo = True
            elif func_ii(item, type_com):
                self.creationTabs.setCurrentIndex(8)
                self.UpdateFlag = True
                self.commentList.setCurrentItem(item.listitem)
                self.UpdateFlag = False
                updateModeInfo = True

        else:
            updateModeInfo = True

            # more than one item
            self.actions['cut'].setEnabled(True)
            self.actions['copy'].setEnabled(True)
            self.actions['duplicate'].setEnabled(True)
            self.actions['shiftitems'].setEnabled(True)

            # Determine if selection is a single homogeneous type that supports a property panel
            sprites   = [i for i in selitems if func_ii(i, type_spr)]
            entrances = [i for i in selitems if func_ii(i, type_ent)]
            locations = [i for i in selitems if func_ii(i, type_loc)]
            paths     = [i for i in selitems if func_ii(i, type_path)]
            npaths    = [i for i in selitems if func_ii(i, type_nPath)]

            total_typed = len(sprites) + len(entrances) + len(locations) + len(paths) + len(npaths)

            if total_typed == len(selitems) and total_typed > 0:
                if len(sprites) == len(selitems):
                    self.selObjs = sprites
                    showSpritePanel = True
                elif len(entrances) == len(selitems):
                    self.selObjs = entrances
                    showEntrancePanel = True
                elif len(locations) == len(selitems):
                    self.selObjs = locations
                    showLocationPanel = True
                elif len(paths) == len(selitems):
                    self.selObjs = paths
                    showPathPanel = True
                elif len(npaths) == len(selitems):
                    self.selObjs = npaths
                    showNabbitPathPanel = True

        # enable the Clips "New" button when something is selected
        self.clipChooser.set_new_enabled(len(selitems) > 0)

        # count the # of each type, for the statusbar label
        spr = 0
        ent = 0
        obj = 0
        loc = 0
        path = 0
        nPath = 0
        com = 0
        for item in selitems:
            if func_ii(item, type_spr):
                spr += 1
            elif func_ii(item, type_ent):
                ent += 1
            elif func_ii(item, type_obj):
                obj += 1
            elif func_ii(item, type_loc):
                loc += 1
            elif func_ii(item, type_path):
                path += 1
            elif func_ii(item, type_nPath):
                nPath += 1
            elif func_ii(item, type_com):
                com += 1

        if loc > 2:
            self.actions['mergelocations'].setEnabled(True)

        # write the statusbar label text
        text = ''
        if len(selitems) > 0:
            singleitem = len(selitems) == 1
            if singleitem:
                if obj:
                    text = '- 1 object selected'  # 1 object selected
                elif spr:
                    text = '- 1 actor selected'  # 1 sprite selected
                elif ent:
                    text = '- 1 entrance selected'  # 1 entrance selected
                elif loc:
                    text = '- 1 location selected'  # 1 location selected
                elif path:
                    text = '- 1 path node selected'  # 1 path node selected
                elif nPath:
                    text = '- 1 Nabbit path node selected'  # 1 nabbit path node selected
                else:
                    text = '- 1 comment selected'  # 1 comment selected
            else:  # multiple things selected; see if they're all the same type
                if not any((spr, ent, loc, path, nPath, com)):
                    text = '- [x] objects selected'.replace('[x]', str(obj))  # x objects selected
                elif not any((obj, ent, loc, path, nPath, com)):
                    text = '- [x] actors selected'.replace('[x]', str(spr))  # x sprites selected
                elif not any((obj, spr, loc, path, nPath, com)):
                    text = '- [x] entrances selected'.replace('[x]', str(ent))  # x entrances selected
                elif not any((obj, spr, ent, path, nPath, com)):
                    text = '- [x] locations selected'.replace('[x]', str(loc))  # x locations selected
                elif not any((obj, spr, ent, nPath, loc, com)):
                    text = '- [x] path nodes selected'.replace('[x]', str(path))  # x path nodes selected
                elif not any((obj, spr, ent, path, loc, com)):
                    text = '- [x] Nabbit path nodes selected'.replace('[x]', str(nPath))  # x nabbit path nodes selected
                elif not any((obj, spr, ent, path, nPath, loc)):
                    text = '- [x] comments selected'.replace('[x]', str(com))  # x comments selected
                else:  # different types
                    text = '- [x] items selected ('.replace('[x]', str(len(selitems)))  # x items selected
                    types = (
                        (obj, 12, 13),  # variable, translation string ID if var == 1, translation string ID if var > 1
                        (spr, 14, 15),
                        (ent, 16, 17),
                        (loc, 18, 19),
                        (path, 20, 21),
                        (nPath, 36, 37),
                        (com, 31, 32),
                    )
                    first = True
                    for var, singleCode, multiCode in types:
                        if var > 0:
                            if not first: text += ', '
                            first = False
                            _sb = {12: '1 object', 13: '[x] objects', 14: '1 actor', 15: '[x] actors', 16: '1 entrance', 17: '[x] entrances', 18: '1 location', 19: '[x] locations', 20: '1 path node', 21: '[x] path nodes', 36: '1 Nabbit path node', 37: '[x] Nabbit path nodes', 31: '1 comment', 32: '[x] comments'}
                            text += _sb[singleCode if var == 1 else multiCode].replace('[x]', str(var))

                    text += ')'  # ')'
        self.selectionLabel.setText(text)

        self.CurrentSelection = selitems

        n = len(self.selObjs) if self.selObjs else 0
        if showSpritePanel:
            title = 'Selected Actor Properties'
            self._switchPropEditor(self.spriteDataEditor, title)
        elif showEntrancePanel:
            title = 'Selected Entrance Properties'
            self._switchPropEditor(self.entranceEditor, title)
        elif showLocationPanel:
            title = 'Selected Location Properties'
            self._switchPropEditor(self.locationEditor, title)
        elif showPathPanel:
            title = 'Selected Path Node Properties'
            self._switchPropEditor(self.pathEditor, title)
        elif showNabbitPathPanel:
            title = 'Selected Nabbit Path Node Properties'
            self._switchPropEditor(self.nabbitPathEditor, title)
        else:
            self.propEditorDock.setVisible(False)

        self.actions['deselect'].setEnabled(len(self.CurrentSelection) > 0)

        if updateModeInfo:
            globals.DirtyOverride += 1
            self.UpdateModeInfo()
            globals.DirtyOverride -= 1

        # Delay one event-loop pass so Qt can process QEvent::Polish for all the
        # newly-added field widgets inside setSprite().  Without the delay, sizeHint()
        # returns stale or wrong values (unpolished widgets report minimal sizes).
        QtCore.QTimer.singleShot(0, self._lockFloatingHeight)

    def HandleObjPosChange(self, obj, oldx, oldy, x, y):
        """
        Handle the object being dragged
        """
        if obj == self.selObj:
            if oldx == x and oldy == y: return
            SetDirty()
        self.levelOverview.update()

    def CreationTabChanged(self, idx):
        """
        Handles the selected palette tab changing
        """
        CPT = -1
        if idx == 0:  # objects
            CPT = self.objAllTab.currentIndex()
        elif idx == 1 and self.sprAllTab.currentIndex() != 1:  # sprites
            CPT = 4
        elif idx == 2:
            CPT = 5  # entrances
        elif idx == 3:
            CPT = 7  # locations
        elif idx == 4:
            CPT = 6  # paths
        elif idx == 5:
            CPT = 12  # nabbit path
        elif idx == 7:
            CPT = 8  # stamp pad
        elif idx == 8:
            CPT = 9  # comment

        type = -1
        if CPT in (0, 1):
            index = self.objPicker.currentIndex()
            if index.isValid():
                if CPT == 1:  # Embedded tab: resolve to slot + paint type
                    type, CPT = self.objTS123Tab.getObjectAndPaintType(index.row())
                else:
                    type = index.row()

        globals.CurrentPaintType = CPT
        globals.CurrentObject = type

    def ObjTabChanged(self, nt):
        """
        Handles the selected slot tab in the object palette changing.
        Tab indices: 0=Main, 1=Embedded
        """
        if hasattr(self, 'objPicker'):
            if nt == 0:
                self.objPicker.ShowTileset(0)
                self.objTS0Tab.setLayout(self.createObjectLayout)
            elif nt == 1:
                self.objPicker.ShowTileset(2)
                self.objTS123Tab.setLayout(self.createObjectLayout)
            self.defaultPropDock.setVisible(False)
        globals.CurrentPaintType = nt

    def SprTabChanged(self, nt):
        """
        Handles the selected tab in the sprite palette changing
        """
        if nt == 0:
            cpt = 4
        else:
            cpt = -1
        globals.CurrentPaintType = cpt

    def LayerChoiceChanged(self, nl):
        """
        Handles the selected layer changing
        """
        globals.CurrentLayer = nl

        # should we replace?
        if QtWidgets.QApplication.keyboardModifiers() == Qt.AltModifier:
            self.MoveSelectedToLayer(nl)

    def MoveSelectedToLayer(self, nl):
        """
        Moves all selected ObjectItems to the specified layer.
        """
        items = self.scene.selectedItems()
        type_obj = ObjectItem
        area = globals.Area
        change = []

        if nl == 0:
            newLayer = area.layers[0]
        elif nl == 1:
            newLayer = area.layers[1]
        else:
            newLayer = area.layers[2]

        for x in items:
            if isinstance(x, type_obj) and x.layer != nl:
                change.append(x)

        if len(change) > 0:
            change.sort(key=lambda x: x.zValue())

            if len(newLayer) == 0:
                z = (2 - nl) * 8192
            else:
                z = newLayer[-1].zValue() + 1

            if nl == 0:
                newVisibility = globals.Layer0Shown
            elif nl == 1:
                newVisibility = globals.Layer1Shown
            else:
                newVisibility = globals.Layer2Shown

            for item in change:
                area.RemoveFromLayer(item)
                item.layer = nl
                newLayer.append(item)
                item.setZValue(z)
                item.setVisible(newVisibility)
                item.update()
                item.UpdateTooltip()
                z += 1

        self.scene.update()
        SetDirty()

    def ImportObjFromFile(self):
        """
        Handles importing an object
        """
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

        # Add the object to one of the tilesets
        paintType, objNum = addObjToTileset(obj, colls, img, nml)
        SetDirty()

        # Checks if the object fit in one of the tilesets
        if paintType == 11:
            # Throw a message that the object didn't fit
            QtWidgets.QMessageBox.critical(None, 'Cannot Import', "There isn't enough room left for this object!")

    def HandleExportAllObj(self):
        """
        Handles exporting all the objects
        """
        save_path = QtWidgets.QFileDialog.getExistingDirectory(None, "Choose where to save the Object folder")
        if not save_path:
            return

        for idx in [1, 2, 3]:
            if globals.ObjectDefinitions[idx] is None:
                continue

            for objNum in range(256):
                if globals.ObjectDefinitions[idx][objNum] is None:
                    break

                baseName = "tileset_%d_object_%d" % (idx + 1, objNum)
                name = os.path.join(save_path, baseName)

                exportObject(name, baseName, idx, objNum)

    def HandleDeleteAllObj(self):
        """
        Handles deleting all objects
        """
        dlgTxt = "Do you really want to delete all the objects?\nThis can't be undone!"
        reply = QtWidgets.QMessageBox.question(self, 'Warning',
                                               dlgTxt, QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)

        if reply == QtWidgets.QMessageBox.Yes:
            instancesFound = False
            noneRemoved = True

            for idx in [1, 2, 3]:
                if globals.ObjectDefinitions[idx] is None:
                    continue

                objNum = 0
                while objNum < 256:
                    if globals.ObjectDefinitions[idx][objNum] is None:
                        break

                    # Check if the object is deletable
                    instanceFound = False

                    ## Check if the object is in the scene
                    for layer in globals.Area.layers:
                        for obj in layer:
                            if obj.tileset == idx and obj.type == objNum:
                                if not instanceFound:
                                    instanceFound = True

                                if not instancesFound:
                                    instancesFound = True

                    ## Check if the object is referenced by a saved clip
                    for clip in self.clipChooser._clips:
                        try:
                            layers, sprites , entrances, locations, paths, nabbitPaths, comments = self.getEncodedObjects(clip.miyamoto_clip, False)
                        except Exception:
                            continue
                        for layer in layers:
                            for obj in layer:
                                if obj.tileset == idx and obj.type == objNum:
                                    if not instanceFound:
                                        instanceFound = True

                                    if not instancesFound:
                                        instancesFound = True

                    ## Check if the object is in the clipboard
                    if self.clipboard is not None:
                        if self.clipboard.startswith('MiyamotoClip|') and self.clipboard.endswith('|%'):
                            layers, sprites , entrances, locations, paths, nabbitPaths, comments = self.getEncodedObjects(self.clipboard, False)
                            for layer in layers:
                                for obj in layer:
                                    if obj.tileset == idx and obj.type == objNum:
                                        if not instanceFound:
                                            instanceFound = True

                                        if not instancesFound:
                                            instancesFound = True

                    if instanceFound:
                        objNum += 1
                        continue

                    DeleteObject(idx, objNum)

                    if noneRemoved:
                        noneRemoved = False

            if not noneRemoved:
                HandleTilesetEdited()

                if not (globals.Area.tileset1 or globals.Area.tileset2 or globals.Area.tileset3):
                    globals.CurrentObject = -1

                self.scene.update()
                SetDirty()

            if instancesFound:
                dlgTxt = "Some objects couldn't be deleted because either there are instances of them in the level scene, they are used as stamps or they are in the clipboard."

                QtWidgets.QMessageBox.critical(self, 'Cannot Delete', dlgTxt)

    def ObjectChoiceChanged(self, type):
        """
        Handles a new object being chosen
        """
        if globals.CurrentPaintType not in (0, 10):
            globals.CurrentObject, globals.CurrentPaintType = self.objTS123Tab.getObjectAndPaintType(type)

        else:
            globals.CurrentObject = type

    def ObjectReplace(self, type):
        """
        Handles a new object being chosen to replace the selected objects
        """
        if globals.CurrentPaintType == 10: return

        items = self.scene.selectedItems()
        type_obj = ObjectItem
        tileset = globals.CurrentPaintType
        changed = False
        data = 0

        if globals.CurrentPaintType != 0:
            type, _ = self.objTS123Tab.getObjectAndPaintType(type)

        else:
            oItems = {16: 1, 17: 2, 18: 3, 19: 4, 20: 5, 21: 6, 22: 7, 23: 8,
                     24: 9, 25: 10, 26: 11, 27: 12, 28: data, 29: 14, 30: 15,
                     31: 16, 32: 17, 33: 18, 34: 19, 35: 20, 36: 21, 37: 22, 38: 23, 39: 24}

            if type in oItems:
                data = oItems[type]
                type = 28
                if data == 0: data = 13

        for x in items:
            if isinstance(x, type_obj) and (x.tileset != tileset or x.type != type or x.data != data):
                x.SetType(tileset, type)
                x.data = data
                x.update()
                changed = True

        if changed:
            SetDirty()

    def SpriteChoiceChanged(self, type):
        """
        Handles a new sprite being chosen
        """
        globals.CurrentSprite = type
        valid_type = (
            isinstance(type, str)
            or (isinstance(type, int) and type != 1000 and type >= 0)
        )
        if valid_type:
            self.defaultDataEditor.setSprite(type)
            self.defaultDataEditor.data = to_bytes(0, 12)
            self.defaultDataEditor.update()
            self.defaultPropButton.setEnabled(True)
        else:
            self.defaultPropButton.setEnabled(False)
            self.defaultPropDock.setVisible(False)
            self.defaultDataEditor.update()

    def SpriteReplace(self, type):
        """
        Handles a new sprite type being chosen to replace the selected sprites
        """
        type_spr = SpriteItem
        items = [x for x in self.scene.selectedItems() if isinstance(x, type_spr)]
        if not items:
            return

        if isinstance(type, str):
            try:
                type = globals.Level.id_manager.get_id_for_string(type)
            except ValueError as e:
                QtWidgets.QMessageBox.warning(self, 'Cannot Replace Actor', str(e))
                return

        changed = False

        for x in items:
            x.spritedata = self.defaultDataEditor.data  # change this first or else images get messed up
            x.SetType(type)
            x.update()
            changed = True

        if changed:
            SetDirty()

        self.ChangeSelectionHandler()

    def SelectNewSpriteView(self, type):
        """
        Handles a new sprite view being chosen
        """
        cat = globals.SpriteCategories[type]
        self.sprPicker.SwitchView(cat)
        self.sprPicker.SetSearchString(self.spriteSearchTerm.text())

    def NewSearchTerm(self, text):
        """
        Handles a new sprite search term being entered
        """
        self.sprPicker.SetSearchString(text)

    def NewCurrentSearchTerm(self, text):
        """
        Filters the current-actors list by the search term
        """
        import re

        def normalize(s):
            return re.sub(r'[-–—_\s]+', ' ', s).replace("'", '').strip().lower()

        terms = [t for t in normalize(text).split() if t]
        for i in range(self.spriteList.count()):
            item = self.spriteList.item(i)
            if not terms:
                item.setHidden(False)
            else:
                item.setHidden(not all(term in normalize(item.text()) for term in terms))

    def ShowDefaultProps(self):
        """
        Handles the Show Default Properties button being clicked
        """
        self.defaultPropDock.setVisible(True)

    def HandleSprPosChange(self, obj, oldx, oldy, x, y):
        """
        Handle the sprite being dragged
        """
        if obj == self.selObj:
            if oldx == x and oldy == y: return
            obj.UpdateListItem()
            SetDirty()
        self.levelOverview.update()

    def SpriteDataUpdated(self, data):
        """
        Handle the current sprite's data being updated
        """
        if self.propEditorDock.isVisible() and self.propEditorStack.currentWidget() is self.spriteDataEditor:
            if self.selObj is None:
                return
            obj = self.selObj

            # If the sprite with updated spritedata is the Flower/Grass Type Setter
            if obj.type == 564:
                # Get the previous type
                oldGrassType = 5
                for sprite in globals.Area.sprites:
                    if sprite.type == 564:
                        oldGrassType = min(sprite.spritedata[5] & 0xf, 5)
                        if oldGrassType < 2:
                            oldGrassType = 0

                        elif oldGrassType in [3, 4]:
                            oldGrassType = 3

                # Get the current type
                grassType = min(data[5] & 0xf, 5)
                if grassType < 2:
                    grassType = 0

                elif grassType in [3, 4]:
                    grassType = 3

                # If the current type is not the previous type, reprocess the Overrides
                # update the objects and flower sprite instances and update the scene
                if grassType != oldGrassType and globals.Area.tileset0:
                    obj.spritedata = data
                    ProcessOverrides(globals.Area.tileset0)
                    self.objPicker.LoadFromTilesets()
                    for layer in globals.Area.layers:
                        for tObj in layer:
                            tObj.updateObjCache()

                    for sprite in globals.Area.sprites:
                        if sprite.type == 546:
                            sprite.UpdateDynamicSizing()

                    self.scene.update()

            old_data = obj.spritedata
            if old_data != data:
                globals.UndoManager.push(undomanager.SpriteDataChangedCommand(obj, old_data, data))
                # UpdateListItem and UpdateDynamicSizing are handled inside the command's redo().

    def SpriteLayerUpdated(self, layer):
        """
        Handle the current sprite's layer being updated
        """
        if layer < 0:
            return
        if self.propEditorDock.isVisible() and self.propEditorStack.currentWidget() is self.spriteDataEditor:
            targets = self.selObjs if (self.selObjs and len(self.selObjs) > 1) else ([self.selObj] if self.selObj else [])
            for obj in targets:
                old_layer = obj.layer
                if old_layer != layer:
                    globals.UndoManager.push(undomanager.SpritePropertyChangedCommand(obj, 'layer', old_layer, layer))
                    # UpdateListItem/UpdateDynamicSizing handled by command._sync()

    def SpriteInitialStateUpdated(self, initialState):
        """
        Handle the current sprite's initial state being updated
        """
        if initialState < 0:
            return
        if self.propEditorDock.isVisible() and self.propEditorStack.currentWidget() is self.spriteDataEditor:
            targets = self.selObjs if (self.selObjs and len(self.selObjs) > 1) else ([self.selObj] if self.selObj else [])
            for obj in targets:
                old_state = obj.initialState
                if old_state != initialState:
                    globals.UndoManager.push(undomanager.SpritePropertyChangedCommand(obj, 'initialState', old_state, initialState))
                    # UpdateListItem/UpdateDynamicSizing handled by command._sync()

    def HandleEntPosChange(self, obj, oldx, oldy, x, y):
        """
        Handle the entrance being dragged
        """
        if oldx == x and oldy == y: return
        obj.UpdateListItem()
        if obj == self.selObj:
            SetDirty()
        self.levelOverview.update()

    def HandlePathPosChange(self, obj, oldx, oldy, x, y):
        """
        Handle the path being dragged
        """
        if oldx == x and oldy == y: return
        obj.updatePos()
        if 'peline' in obj.pathinfo:
            obj.pathinfo['peline'].nodePosChanged()
        obj.UpdateListItem()
        if obj == self.selObj:
            SetDirty()
        self.levelOverview.update()

    def HandleComPosChange(self, obj, oldx, oldy, x, y):
        """
        Handle the comment being dragged
        """
        if oldx == x and oldy == y: return
        obj.UpdateTooltip()
        obj.handlePosChange(oldx, oldy)
        obj.UpdateListItem()
        if obj == self.selObj:
            self.SaveComments()
            SetDirty()
        self.levelOverview.update()

    def HandleComTxtChange(self, obj):
        """
        Handle the comment's text being changed
        """
        obj.UpdateListItem()
        obj.UpdateTooltip()
        self.SaveComments()
        SetDirty()

    def HandleEntranceSelectByList(self, item):
        """
        Handle an entrance being selected from the list
        """
        if self.UpdateFlag: return

        # can't really think of any other way to do this
        # item = self.entranceList.item(row)
        ent = None
        for check in globals.Area.entrances:
            if check.listitem == item:
                ent = check
                break
        if ent is None: return

        ent.ensureVisible(QtCore.QRectF(), 192, 192)
        self.scene.clearSelection()
        ent.setSelected(True)

    def HandleEntranceToolTipAboutToShow(self, item):
        """
        Handle an entrance being hovered in the list
        """
        ent = None
        for check in globals.Area.entrances:
            if check.listitem == item:
                ent = check
                break
        if ent is None: return

        ent.UpdateListItem(True)

    def HandleLocationSelectByList(self, item):
        """
        Handle a location being selected from the list
        """
        if self.UpdateFlag: return

        # can't really think of any other way to do this
        # item = self.locationList.item(row)
        loc = None
        for check in globals.Area.locations:
            if check.listitem == item:
                loc = check
                break
        if loc is None: return

        loc.ensureVisible(QtCore.QRectF(), 192, 192)
        self.scene.clearSelection()
        loc.setSelected(True)

    def HandleLocationToolTipAboutToShow(self, item):
        """
        Handle a location being hovered in the list
        """
        loc = None
        for check in globals.Area.locations:
            if check.listitem == item:
                loc = check
                break
        if loc is None: return

        loc.UpdateListItem(True)

    def HandleSpriteSelectByList(self, item):
        """
        Handle a sprite being selected from the list
        """
        if self.UpdateFlag: return

        # can't really think of any other way to do this
        # item = self.spriteList.item(row)
        spr = None
        for check in globals.Area.sprites:
            if check.listitem == item:
                spr = check
                break
        if spr is None: return

        spr.ensureVisible(QtCore.QRectF(), 192, 192)
        self.scene.clearSelection()
        spr.setSelected(True)

    def HandleSpriteToolTipAboutToShow(self, item):
        """
        Handle a sprite being hovered in the list
        """
        spr = None
        for check in globals.Area.sprites:
            if check.listitem == item:
                spr = check
                break
        if spr is None: return

        spr.UpdateListItem(True)

    def HandlePathSelectByList(self, item):
        """
        Handle a path node being selected
        """
        # if self.UpdateFlag: return

        # can't really think of any other way to do this
        # item = self.pathlist.item(row)
        path = None
        for check in globals.Area.paths:
            if check.listitem == item:
                path = check
                break
        if path is None: return

        path.ensureVisible(QtCore.QRectF(), 192, 192)
        self.scene.clearSelection()
        path.setSelected(True)

    def HandlePathToolTipAboutToShow(self, item):
        """
        Handle a path node being hovered in the list
        """
        path = None
        for check in globals.Area.paths:
            if check.listitem == item:
                path = check
                break
        if path is None: return

        path.UpdateListItem(True)

    def HandleNabbitPathSelectByList(self, item):
        """
        Handle a path node being selected
        """
        nPath = None
        for check in globals.Area.nPaths:
            if check.listitem == item:
                nPath = check
                break
        if nPath is None: return

        nPath.ensureVisible(QtCore.QRectF(), 192, 192)
        self.scene.clearSelection()
        nPath.setSelected(True)

    def HandleNabbitPathToolTipAboutToShow(self, item):
        """
        Handle a path node being hovered in the list
        """
        nPath = None
        for check in globals.Area.nPaths:
            if check.listitem == item:
                nPath = check
                break
        if nPath is None: return

        nPath.UpdateListItem(True)

    def HandleCommentSelectByList(self, item):
        """
        Handle a comment being selected
        """
        comment = None
        for check in globals.Area.comments:
            if check.listitem == item:
                comment = check
                break
        if comment is None: return

        comment.ensureVisible(QtCore.QRectF(), 192, 192)
        self.scene.clearSelection()
        comment.setSelected(True)

    def HandleCommentToolTipAboutToShow(self, item):
        """
        Handle a comment being hovered in the list
        """
        comment = None
        for check in globals.Area.comments:
            if check.listitem == item:
                comment = check
                break
        if comment is None: return

        comment.UpdateListItem(True)

    def HandleLocPosChange(self, loc, oldx, oldy, x, y):
        """
        Handle the location being dragged
        """
        if loc == self.selObj:
            if oldx == x and oldy == y: return
            self.locationEditor.setLocation(loc)
            SetDirty()
        loc.UpdateListItem()
        self.levelOverview.update()

    def HandleLocSizeChange(self, loc, w, h):
        """
        Handle the location being resized
        """
        if loc == self.selObj:
            self.locationEditor.setLocation(loc)
            SetDirty()
        loc.UpdateListItem()
        self.levelOverview.update()

    def eventFilter(self, obj, event):
        """Track position and width changes on the floating prop-editor dock."""
        if obj is self.propEditorDock and self.propEditorDock.isFloating():
            t = event.type()
            if t == QtCore.QEvent.Move:
                self._propEditorPos = obj.pos()
            elif t == QtCore.QEvent.Resize:
                w = obj.width()
                if w > 0:
                    self._propEditorWidth = w
        return super().eventFilter(obj, event)

    def _switchPropEditor(self, widget, title):
        """Switch the shared prop-editor dock to a different editor page."""
        dock = self.propEditorDock

        # Do NOT release the height lock here — keeping the old lock in place
        # prevents macOS from collapsing the window to a small size during the
        # native window event processing that occurs inside setVisible(True).
        # The lock is released inside _lockFloatingHeight() just before resize,
        # at which point setSprite() has fully populated the editor.

        self.propEditorStack.setCurrentWidget(widget)
        dock.setWindowTitle(title)
        dock.setVisible(True)

    def _lockFloatingHeight(self):
        """
        Lock the dock's height to its content, capped to the screen.

        Works for both floating and docked modes.

        Must be called *after* the editor's content has been fully populated
        (i.e. after UpdateModeInfo / setSprite / setEntrance etc.) so that
        the layout's sizeHint is accurate.
        """
        dock = self.propEditorDock
        if not dock.isVisible():
            return

        current = self.propEditorStack.currentWidget()
        if current is None:
            return

        TITLEBAR = 28

        target_h = current.sizeHint().height()
        if target_h <= 0:
            return

        # Cap to the usable screen area so the dock never overflows off-screen.
        ref_pos = self._propEditorPos if self._propEditorPos is not None else dock.pos()
        screen = QtWidgets.QApplication.screenAt(ref_pos)
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen()
        avail = screen.availableGeometry()

        max_h = avail.height() - TITLEBAR - 16
        target_h = max(80, min(target_h, max_h))

        # Release the old lock first so the resize below isn't clamped to the
        # previous content's height, then immediately re-lock to the new height.
        dock.setMinimumHeight(0)
        dock.setMaximumHeight(16777215)

        if dock.isFloating():
            # Floating: account for the OS window title bar so the content
            # area matches sizeHint rather than the window frame.
            total_h = target_h + TITLEBAR

            # Clamp the saved position so the dock stays fully on-screen after resize.
            if self._propEditorPos is not None:
                px = max(avail.left(), min(self._propEditorPos.x(),
                                           avail.right() - self._propEditorWidth))
                py = max(avail.top(), min(self._propEditorPos.y(),
                                           avail.bottom() - total_h))
                dock.move(px, py)

            dock.setMinimumHeight(total_h)
            dock.setMaximumHeight(total_h)
            dock.resize(self._propEditorWidth, total_h)
            # resize() can activate the floating window on macOS; return focus to main window.
            QtCore.QTimer.singleShot(0, self.activateWindow)
        else:
            # Docked: constrain height to content (+ title bar within the main window).
            dock.setMinimumHeight(target_h + TITLEBAR)
            dock.setMaximumHeight(target_h + TITLEBAR)

    def _onPropEditorTopLevelChanged(self, floating):
        """Adjust height constraints when the dock is docked/undocked."""
        if floating:
            # macOS creates the native window asynchronously; give it one event-loop
            # pass before computing the content height.
            QtCore.QTimer.singleShot(0, self._lockFloatingHeight)
        else:
            # Docked: delay one pass so the layout settles before locking height.
            QtCore.QTimer.singleShot(0, self._lockFloatingHeight)

    def UpdateModeInfo(self):
        """
        Change the info in the currently visible panel
        """
        self.UpdateFlag = True

        current = self.propEditorStack.currentWidget()
        if current is self.spriteDataEditor and self.propEditorDock.isVisible():
            if self.selObjs is not None and len(self.selObjs) > 1:
                items = self.selObjs
                first_type = items[0].type
                if all(i.type == first_type for i in items):
                    self.spriteDataEditor.setMultipleSprites(items)
                else:
                    self.spriteDataEditor.setMixedActors(items)
            else:
                obj = self.selObj
                self.spriteDataEditor.setSprite(obj.type)
                self.spriteDataEditor.setLayerOverrideValue(obj.layer)
                self.spriteDataEditor.setInitialStateOverrideValue(obj.initialState)
                self.spriteDataEditor.data = obj.spritedata
                self.spriteDataEditor.update()
        elif current is self.entranceEditor and self.propEditorDock.isVisible():
            if self.selObjs is not None and len(self.selObjs) > 1:
                self.entranceEditor.setMultipleEntrances(self.selObjs)
            else:
                self.entranceEditor.setEntrance(self.selObj)
        elif current is self.pathEditor and self.propEditorDock.isVisible():
            if self.selObjs is not None and len(self.selObjs) > 1:
                self.pathEditor.setMultiplePaths(self.selObjs)
            else:
                self.pathEditor.setPath(self.selObj)
        elif current is self.nabbitPathEditor and self.propEditorDock.isVisible():
            if self.selObjs is not None and len(self.selObjs) > 1:
                self.nabbitPathEditor.setMultiplePaths(self.selObjs)
            else:
                self.nabbitPathEditor.setPath(self.selObj)
        elif current is self.locationEditor and self.propEditorDock.isVisible():
            if self.selObjs is not None and len(self.selObjs) > 1:
                self.locationEditor.setMultipleLocations(self.selObjs)
            else:
                self.locationEditor.setLocation(self.selObj)

        self.UpdateFlag = False

    def PositionHovered(self, x, y):
        """
        Handle a position being hovered in the view
        """
        info = ''
        hovereditems = self.scene.items(QtCore.QPointF(x, y))
        hovered = None
        type_zone = ZoneItem
        type_peline = PathEditorLineItem
        for item in hovereditems:
            hover = item.hover if hasattr(item, 'hover') else True
            if (not isinstance(item, type_zone)) and (not isinstance(item, type_peline)) and hover:
                hovered = item
                break

        if hovered is not None:
            if isinstance(hovered, ObjectItem):  # Object
                info = '- Object under mouse: size [width]x[height] at ([xpos], [ypos]) on layer [layer]; type [type] from tileset [tileset]'.replace('[width]', str(hovered.width)).replace('[height]', str(hovered.height)).replace('[xpos]', str(hovered.objx)).replace('[ypos]', str(hovered.objy)).replace('[layer]', str(hovered.layer)).replace('[type]', str(hovered.type)).replace('[tileset]', str(hovered.tileset + 1)) + (
                       '' if hovered.data == 0 else '; contents value of %d' % hovered.data)
            elif isinstance(hovered, SpriteItem):  # Sprite
                info = '- Actor under mouse: [name] at [xpos], [ypos]'.replace('[name]', str(hovered.name)).replace('[xpos]', str(hovered.objx)).replace('[ypos]', str(hovered.objy))
            elif isinstance(hovered, SLib.AuxiliaryItem):  # Sprite (auxiliary thing) (treat it like the actual sprite)
                info = '- Actor under mouse: [name] at [xpos], [ypos]'.replace('[name]', str(hovered.parentItem().name)).replace('[xpos]', str(hovered.parentItem().objx)).replace('[ypos]', str(hovered.parentItem().objy))
            elif isinstance(hovered, EntranceItem):  # Entrance
                info = '- Entrance under mouse: [name] at [xpos], [ypos] [dest]'.replace('[name]', str(hovered.name)).replace('[xpos]', str(hovered.objx)).replace('[ypos]', str(hovered.objy)).replace('[dest]', str(hovered.destination))
            elif isinstance(hovered, LocationItem):  # Location
                info = '- Location under mouse: Location ID [id] at [xpos], [ypos]; width [width], height [height]'.replace('[id]', str(int(hovered.id))).replace('[xpos]', str(int(hovered.objx))).replace('[ypos]', str(int(hovered.objy))).replace('[width]', str(int(hovered.width))).replace('[height]', str(int(hovered.height)))
            elif isinstance(hovered, PathItem):  # Path
                info = '- Path node under mouse: Path [path], Node [node] at [xpos], [ypos]'.replace('[path]', str(hovered.pathid)).replace('[node]', str(hovered.nodeid)).replace('[xpos]', str(hovered.objx)).replace('[ypos]', str(hovered.objy))
            elif isinstance(hovered, NabbitPathItem):  # Nabbit Path
                info = '- Nabbit Path node under mouse: Node [node] at [xpos], [ypos]'.replace('[node]', str(hovered.nodeid)).replace('[xpos]', str(hovered.objx)).replace('[ypos]', str(hovered.objy))
            elif isinstance(hovered, CommentItem):  # Comment
                info = '- Comment under mouse: [xpos], [ypos]; "[text]"'.replace('[xpos]', str(hovered.objx)).replace('[ypos]', str(hovered.objy)).replace('[text]', str(hovered.OneLineText()))

        self.posLabel.setText(
            '([objx], [objy]) - ([sprx], [spry])'.replace('[objx]', str(int(x / globals.TileWidth))).replace('[objy]', str(int(y / globals.TileWidth))).replace('[sprx]', str(int(x / globals.TileWidth * 16))).replace('[spry]', str(int(y / globals.TileWidth * 16))))
        self.hoverLabel.setText(info)

    def updateNumUsedTilesLabel(self):
        """
        Updates the label for number of used tiles
        Based on a similar function from Satoru
        """
        usedTiles = getUsedTiles()

        numUsedTiles = 0

        for idx in range(1, 4):
            numUsedTiles += len(usedTiles[idx])

        text = str(numUsedTiles) + '/768 tiles (' + str(numUsedTiles / 768 * 100)[:5] + '%)'

        if numUsedTiles > 768:
            text = '<span style="color:red;font-weight:bold;">' + text + '</span>'

        self.numUsedTilesLabel.setText(text)

    def keyPressEvent(self, event):
        """
        Handles key press events for the main window if needed
        """
        if event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
            sel = self.scene.selectedItems()
            if len(sel) > 0:
                self.SelectionUpdateFlag = True
                
                # Get the previous flower/grass type
                oldGrassType = 5
                for sprite in globals.Area.sprites:
                    if sprite.type == 564:
                        oldGrassType = min(sprite.spritedata[5] & 0xf, 5)
                        if oldGrassType < 2:
                            oldGrassType = 0
                        elif oldGrassType in [3, 4]:
                            oldGrassType = 3

                # Sort selection by type to create commands
                objs = []
                sprs = []
                ents = []
                locs = []
                nodes = []
                nabbit_nodes = []
                coms = []
                
                # Count selected nodes per path to correctly handle path removal
                nodes_to_delete_per_path = {}
                for item in sel:
                    if isinstance(item, (PathItem, NabbitPathItem)):
                        p_id = id(item.pathinfo)
                        nodes_to_delete_per_path[p_id] = nodes_to_delete_per_path.get(p_id, 0) + 1
                
                handled_path_removals = set()

                for item in sel:
                    if isinstance(item, ObjectItem):
                        # Find layer
                        l_idx = -1
                        for i, layer in enumerate(globals.Area.layers):
                            if item in layer:
                                l_idx = i
                                break
                        if l_idx != -1:
                            objs.append((item, l_idx, globals.Area.layers[l_idx].index(item), item.zValue()))
                    elif isinstance(item, SpriteItem):
                        if item in globals.Area.sprites:
                            sprs.append((item, globals.Area.sprites.index(item)))
                    elif isinstance(item, EntranceItem):
                        if item in globals.Area.entrances:
                            ents.append((item, globals.Area.entrances.index(item)))
                    elif isinstance(item, LocationItem):
                        if item in globals.Area.locations:
                            locs.append((item, globals.Area.locations.index(item)))
                    elif isinstance(item, PathItem):
                        try:
                            idx = item.pathinfo['nodes'].index(item.nodeinfo)
                            p_id = id(item.pathinfo)
                            path_was_removed = False
                            if len(item.pathinfo['nodes']) == nodes_to_delete_per_path[p_id]:
                                if p_id not in handled_path_removals:
                                    path_was_removed = True
                                    handled_path_removals.add(p_id)
                            nodes.append((item, item.pathinfo, item.nodeinfo, idx, path_was_removed, False))
                        except ValueError:
                            continue
                    elif isinstance(item, NabbitPathItem):
                        try:
                            idx = item.pathinfo['nodes'].index(item.nodeinfo)
                            p_id = id(item.pathinfo)
                            path_was_removed = False
                            if len(item.pathinfo['nodes']) == nodes_to_delete_per_path[p_id]:
                                if p_id not in handled_path_removals:
                                    path_was_removed = True
                                    handled_path_removals.add(p_id)
                            nabbit_nodes.append((item, item.pathinfo, item.nodeinfo, idx, path_was_removed, True))
                        except ValueError:
                            continue
                    elif isinstance(item, CommentItem):
                        if item in globals.Area.comments:
                            coms.append((item, globals.Area.comments.index(item)))

                if any([objs, sprs, ents, locs, nodes, nabbit_nodes, coms]):
                    globals.UndoManager.begin_compound("Delete Selection")
                    if objs:
                        globals.UndoManager.push(undomanager.DeleteObjectsCommand(objs))
                    if sprs:
                        globals.UndoManager.push(undomanager.DeleteSpritesCommand(sprs))
                    if ents:
                        globals.UndoManager.push(undomanager.DeleteEntrancesCommand(ents))
                    if locs:
                        globals.UndoManager.push(undomanager.DeleteLocationsCommand(locs))
                    if nodes:
                        globals.UndoManager.push(undomanager.DeletePathNodeCommand(nodes, False))
                    if nabbit_nodes:
                        globals.UndoManager.push(undomanager.DeletePathNodeCommand(nabbit_nodes, True))
                    if coms:
                        globals.UndoManager.push(undomanager.DeleteCommentsCommand(coms))
                    globals.UndoManager.end_compound()

                event.accept()
                self.SelectionUpdateFlag = False
                self.ChangeSelectionHandler()

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
                    self.objPicker.LoadFromTilesets()
                    for layer in globals.Area.layers:
                        for tObj in layer:
                            tObj.updateObjCache()

                    for sprite in globals.Area.sprites:
                        if sprite.type == 546:
                            sprite.UpdateDynamicSizing()

                    self.scene.update()

        else:
            QtWidgets.QMainWindow.keyPressEvent(self, event)

        self.levelOverview.update()

    def HandleAreaOptions(self):
        """
        Pops up the options for Area Dialogue
        """
        dlg = AreaOptionsDialog()
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            SetDirty()
            globals.Area.wrapFlag = dlg.LoadingTab.wrap.isChecked()
            globals.Area.unkFlag1 = dlg.LoadingTab.unk1.isChecked()
            globals.Area.timelimit = dlg.LoadingTab.timer.value()
            globals.Area.unkFlag2 = dlg.LoadingTab.unk2.isChecked()
            globals.Area.unkFlag3 = dlg.LoadingTab.unk3.isChecked()
            globals.Area.unkFlag4 = dlg.LoadingTab.unk4.isChecked()
            globals.Area.startEntrance = dlg.LoadingTab.entrance.value()
            globals.Area.startEntranceCoinBoost = dlg.LoadingTab.entranceCoinBoost.value()
            globals.Area.timelimit2 = dlg.LoadingTab.timelimit2.value()
            globals.Area.timelimit3 = dlg.LoadingTab.timelimit3.value()

            fname = dlg.TilesetsTab.value()

            toUnload = False

            if fname in ('', None):
                toUnload = True
            else:
                if fname.startswith('[CUSTOM]'):
                    fname = fname[len('[CUSTOM] [name]'.replace('[name]', str(''))):]

                if fname not in ('', None):
                    if not HasTileset(fname):
                        toUnload = True
                    else:
                        globals.Area.tileset0 = fname
                        LoadTileset(0, fname)

            if toUnload:
                globals.Area.tileset0 = ''
                UnloadTileset(0)

            HandleTilesetEdited(True)

            if globals.Area.tileset0 != '':
                self.objAllTab.setCurrentIndex(0)
                self.objAllTab.setTabEnabled(0, True)

            else:
                self.objAllTab.setCurrentIndex(1)
                self.objAllTab.setTabEnabled(0, False)

            for layer in globals.Area.layers:
                for obj in layer:
                    obj.updateObjCache()

            self.scene.update()

    def HandleZones(self):
        """
        Pops up the options for Zone dialog
        """
        dlg = ZonesDialog()
        
        # Capture old state
        old_zones = list(globals.Area.zones)
        old_states = [undomanager.get_zone_state(z) for z in old_zones]
        
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            # Reconstruct zones as before
            items = self.scene.items()
            func_ii = isinstance
            type_zone = ZoneItem
            for item in items:
                if func_ii(item, type_zone):
                    self.scene.removeItem(item)

            new_zones = []
            ygn2Used = False
            for id, (tab, bgTab) in enumerate(zip(dlg.zoneTabs, dlg.BGTabs)):
                z = tab.zoneObj
                z.id = id
                z.UpdateTitle()
                
                # Apply properties from tab to z
                if tab.Zone_xpos.value() < 16: z.objx = 16
                elif tab.Zone_xpos.value() > 24560: z.objx = 24560
                else: z.objx = tab.Zone_xpos.value()
                
                if tab.Zone_ypos.value() < 16: z.objy = 16
                elif tab.Zone_ypos.value() > 12272: z.objy = 12272
                else: z.objy = tab.Zone_ypos.value()
                
                if (tab.Zone_width.value() + z.objx) > 24560: z.width = 24560 - z.objx
                else: z.width = tab.Zone_width.value()
                
                if (tab.Zone_height.value() + z.objy) > 12272: z.height = 12272 - z.objy
                else: z.height = tab.Zone_height.value()
                
                z.prepareGeometryChange()
                z.UpdateRects()
                z.setPos(z.objx * (globals.TileWidth / 16), z.objy * (globals.TileWidth / 16))
                
                z.cammode = tab.Zone_cammodebuttongroup.checkedId()
                z.camzoom = tab.Zone_screenheights.currentIndex()
                z.unk1 = tab.Zone_camunk1.value()
                z.visibility = tab.Zone_visibility.currentIndex()
                if tab.Zone_vspotlight.isChecked(): z.visibility |= 0x10
                if tab.Zone_vfulldark.isChecked(): z.visibility |= 0x20
                z.unk2 = tab.Zone_camunk2.value()
                z.camtrack = tab.Zone_directionmode.currentIndex()
                z.unk3 = tab.Zone_camunk3.value()
                z.yupperbound = tab.Zone_yboundup.value() - 80
                z.ylowerbound = -tab.Zone_ybounddown.value() + 72
                z.yupperbound2 = tab.Zone_yboundup2.value() - 88
                z.ylowerbound2 = -tab.Zone_ybounddown2.value() + 88
                z.yupperbound3 = tab.Zone_yboundup3.value()
                z.ylowerbound3 = -tab.Zone_ybounddown3.value()
                z.mpcamzoomadjust = 0xF if tab.Zone_boundflg.isChecked() else tab.Zone_mpzoomadjust.value()
                if tab.Zone_custommusic.isChecked() and tab.Zone_musicname.text().strip():
                    # Extension: custom track stored as string; ID 0 is the sentinel
                    z.music = 0
                    z.customMusicName = tab.Zone_musicname.text()
                else:
                    z.music = tab.Zone_musicid.value()
                    z.customMusicName = ''
                z.sfxmod = (tab.Zone_sfx.currentIndex() & 0x0F) << 4
                if tab.Zone_boss.isChecked(): z.sfxmod |= 1
                z.type = 0
                for i in range(8):
                    if tab.Zone_settings[i].isChecked(): z.type |= 1 << i
                
                name = bgTab.bgFname.text()
                z.background = (z.id, bgTab.xPos.value(), bgTab.yPos.value(), bgTab.zPos.value(), to_bytes(name, 16), bgTab.parallaxMode.currentIndex())
                if not ygn2Used: ygn2Used = (name == "Yougan_2")
                
                new_zones.append(z)

            # Capture new state
            new_states = [undomanager.get_zone_state(z) for z in new_zones]
            
            # Push command
            globals.UndoManager.push(undomanager.ChangeZonesCommand(old_zones, old_states, new_zones, new_states))
            
            if ygn2Used:
                QtWidgets.QMessageBox.information(None, 'Warning', '"Lava 2" BG requires actors: 473, 477, 487, 497.<br>Of course, you have to set up those actors correctly in order for the game to not crash.<br>Go take a look at 8-43 Area 3.')

            for spr in globals.Area.sprites:
                if isinstance(spr.ImageObj, SLib.SpriteImage_MovementControlled):
                    if spr.ImageObj.controller: spr.ImageObj.controller = None
                    spr.UpdateDynamicSizing()
                else:
                    spr.ImageObj.positionChanged()

        self.levelOverview.update()

    def HandleScreenshot(self):
        """
        Takes a screenshot of the entire level and saves it
        """

        dlg = ScreenCapChoiceDialog()
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return

        sType = dlg.zoneCombo.currentIndex()
        hideBackground = dlg.hideBackground.isChecked()
        saveImage = dlg.saveImage.isChecked()
        saveClip = dlg.saveClip.isChecked()

        if saveImage:
            fn = QtWidgets.QFileDialog.getSaveFileName(self, 'Choose a new filename', '/untitled.png',
                                                       'Portable Network Graphics' + ' (*.png)')[0]
            if fn == '' and not saveClip:
                return

        if sType == 0:
            source = QtCore.QRect(QtCore.QPoint(), self.view.size())
            widget = self.view

        else:
            if sType == 1:
                source = QtCore.QRectF()
                for z in globals.Area.zones:
                    source |= z.sceneBoundingRect()
            else:
                source = globals.Area.zones[sType - 2].sceneBoundingRect()

            pad = round(5 * globals.TileWidth / 3)
            source += QtCore.QMarginsF(pad, pad, pad, pad)
            source &= QtCore.QRectF(0, 0, 1024 * globals.TileWidth, 512 * globals.TileWidth)
            widget = self.scene

            if globals.RotationShown:
                sceneRect = (QtGui.QTransform() / globals.TileWidth).mapRect(source)
                movementControlledType = SLib.SpriteImage_MovementControlled

                globals.OverrideSnapping = True
                globals.DirtyOverride += 1
                for spr in globals.Area.sprites:
                    imageObj = spr.ImageObj
                    if isinstance(imageObj, movementControlledType):
                        controller = spr.ImageObj.controller
                        if controller and controller.active() and sceneRect.intersects(controller.parent.LevelRect | spr.LevelRect):
                            spr.UpdateDynamicSizing()
                globals.DirtyOverride -= 1
                globals.OverrideSnapping = False

                self.levelOverview.update()

        screenshot = QtGui.QImage(source.size().toSize() if isinstance(source, QtCore.QRectF) else source.size(), QtGui.QImage.Format_ARGB32)
        screenshot.fill(Qt.transparent)

        painter = QtGui.QPainter(screenshot)

        if hideBackground:
            # Remove the background
            brush = self.scene.backgroundBrush()
            style = brush.style()
            brush.setStyle(Qt.NoBrush)
            self.scene.setBackgroundBrush(brush)

            # Render
            widget.render(painter, source=source)

            # Restore the background
            brush.setStyle(style)
            self.scene.setBackgroundBrush(brush)

        else:
            # Render with background
            widget.render(painter, source=source)

        painter.end()

        if saveImage:
            screenshot.save(fn, 'PNG')

        if saveClip:
            globals.app.clipboard().setImage(screenshot)

    def _tilesetEditorUnavailable(self):
        """
        The tileset editor still reads and writes the Wii U tileset format only.
        Returns True (after telling the user) when it can't be used with the current game.
        """
        if not globals.IsNSMBUDX:
            return False

        QtWidgets.QMessageBox.information(
            self, 'Pyamoto',
            'The tileset editor does not support New Super Mario Bros. U Deluxe yet.\n\n'
            'You can still place existing tilesets and objects in levels; '
            'creating or editing tilesets requires the Wii U version for now.')
        return True

    def EditTilesets(self):
        """
        Edits all tilesets in a merged window, opening to the slot active in the palette.
        """
        if self._tilesetEditorUnavailable():
            return

        # Determine which slot to open to based on active palette tab
        active_tab = self.objAllTab.currentIndex()
        if active_tab == 1:  # Embedded tab: use the active embedded sub-tab
            initial_slot = self.objTS123Tab.currentIndex()
        else:  # Main tab
            initial_slot = 0

        # Build slot descriptors: (name, bytes_or_None, is_placeholder)
        # TilesetEditor accepts bytes directly — no temp files needed.
        slots_data = []
        for slot in range(4):
            ts_name = getattr(globals.Area, f'tileset{slot}')
            if ts_name and ts_name in globals.szsData:
                slots_data.append((ts_name, globals.szsData[ts_name], False))
            else:
                slots_data.append((f'Pa{slot}_MIYAMOTO_TEMP', None, True))

        self.showPuzzleWindow(slots_data, initial_slot)

    def HandleImportObjects(self):
        """Open tileset editor and trigger Import Objects — user can save/discard."""
        if self._tilesetEditorUnavailable():
            return

        slots_data = []
        for slot in range(4):
            ts_name = getattr(globals.Area, f'tileset{slot}')
            if ts_name and ts_name in globals.szsData:
                slots_data.append((ts_name, globals.szsData[ts_name], False))
            else:
                slots_data.append((f'Pa{slot}_MIYAMOTO_TEMP', None, True))

        pw = PuzzleWindow(slots_data, Qt.Dialog)
        if pw.forceClose:
            del pw
            return
        pw.setWindowModality(Qt.ApplicationModal)
        pw.setAttribute(Qt.WA_DeleteOnClose)
        pw.show()
        pw.importObjectsFromFolder()

    def showPuzzleWindow(self, slots_data, initial_slot=0):
        pw = PuzzleWindow(slots_data, Qt.Dialog)
        if pw.forceClose:
            del pw
        else:
            pw.setWindowModality(Qt.ApplicationModal)
            pw.setAttribute(Qt.WA_DeleteOnClose)
            if initial_slot > 0:
                pw.tabs.setCurrentIndex(initial_slot)
            pw.show()


def _migrate_games_settings():
    """One-time migration from old LastGameDef / GamePath to the new Games+Mods system."""
    # Migrate GamePath → GamePath_NSMBU
    if setting('GamePath') and not setting('GamePath_NSMBU'):
        setSetting('GamePath_NSMBU', setting('GamePath'))

    # Migrate LastGameDef → LastBaseGame + LastMods
    if setting('LastGameDef') is not None and setting('LastBaseGame') is None:
        old = setting('LastGameDef')
        if isinstance(old, str):
            old = [old] if old else []
        old = [x for x in old if x not in (None, 'None', '')]
        # Heuristic: if 'NSLU' is in the old list, that was the base game; rest are mods
        if 'NSLU' in old:
            setSetting('LastBaseGame', 'NSLU')
            remaining = [x for x in old if x != 'NSLU']
        else:
            setSetting('LastBaseGame', 'NSMBU')
            remaining = old
        setSetting('LastMods', remaining)
        setSetting('LastGameDef', None)


def _migrate_dx_settings():
    """
    Settings carried over from Miyamoto! DX (flagged "isDX") describe a New Super Mario
    Bros. U Deluxe setup: move its game path into the Deluxe game slot and select Deluxe.
    """
    if not setting('isDX'):
        return

    legacy = setting('GamePath')
    if legacy and not setting('GamePath_NSMBUDX'):
        setSetting('GamePath_NSMBUDX', legacy)

    # The old single "GamePath" held the Deluxe Course folder, not a Wii U one
    setSetting('GamePath', None)

    if setting('LastBaseGame') in (None, 'NSMBU'):
        setSetting('LastBaseGame', 'NSMBUDX')

    if not setting('SetupComplete', False) and isValidGamePath(setting('GamePath_NSMBUDX', ''), 'NSMBUDX'):
        setSetting('SetupComplete', True)

    setSetting('isDX', False)
    globals.settings.sync()


def _migrate_old_settings(new_path):
    """One-time migration: copy readable values from a legacy settings.ini in the
    project root into the new JSON settings file (if it doesn't exist yet)."""
    if os.path.exists(new_path):
        return
    old_ini = os.path.join(globals.miyamoto_path, 'settings.ini')
    if not os.path.exists(old_ini):
        return
    try:
        import configparser
        cfg = configparser.ConfigParser()
        cfg.read(old_ini, encoding='utf-8')
        if 'General' not in cfg:
            return
        g = cfg['General']
        data = {}
        str_keys = ['GamePath', 'LastLevel', 'LastFilePath', 'Theme', 'Translation',
                    'GridType', 'uiStyle', 'AutoSaveFilePath', 'AutoSaveFileData']
        bool_keys = ['UseRGBA8', 'RealViewEnabled', 'ShowSprites', 'ShowSpriteImages',
                     'ShowLocations', 'ShowComments', 'ShowPaths',
                     'RotationShown', 'FreezeObjects', 'FreezeSprites',
                     'FreezeEntrances', 'FreezeLocations', 'FreezePaths', 'FreezeComments',
                     'PlaceObjectFullSize', 'CategorizedSpriteData', 'OverwriteSprite',
                     'AutoSaveTilesets', 'isDX', 'OverrideTilesetSaving']
        int_keys = ['SpriteListPreviewSize', 'RotationFPS', 'OpenMethodMode', 'LaunchBehavior']
        for k in str_keys:
            if k.lower() in g:
                data[k] = g[k.lower()]
        for k in bool_keys:
            if k.lower() in g:
                data[k] = g[k.lower()].lower() == 'true'
        for k in int_keys:
            if k.lower() in g:
                try:
                    data[k] = int(float(g[k.lower()]))
                except ValueError:
                    pass
        if data:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            with open(new_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
    except Exception:
        pass


def main():
    """
    Main startup function for Miyamoto
    """

    # Set High-DPI-Displays-related attributes before creating an application
    QtGui.QGuiApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    if hasattr(QtGui.QGuiApplication, 'setHighDpiScaleFactorRoundingPolicy'):
        QtGui.QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Round)

    # Apply the saved UI scale before creating the application, since
    # QT_SCALE_FACTOR only takes effect at application startup.
    try:
        _settings_path = os.path.join(globals.user_data_path, 'settings.json')
        _ui_scale = 1.0
        if os.path.isfile(_settings_path):
            with open(_settings_path, 'r', encoding='utf-8') as _f:
                _ui_scale = float(json.load(_f).get('UIScale', 1.0))
        if 0.5 <= _ui_scale <= 3.0 and _ui_scale != 1.0:
            os.environ['QT_SCALE_FACTOR'] = str(_ui_scale)
    except Exception:
        pass

    # Create an application
    globals.app = QtWidgets.QApplication(sys.argv)

    # Restore default SIGINT handling so Ctrl+C instantly kills the process
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Go to the script path
    path = globals.miyamoto_path
    if path is not None:
        os.chdir(path)

    print(f'[Pyamoto] v{globals.MiyamotoVersion} ({globals.MiyamotoReleaseType})  |  data: {globals.miyamoto_path}  |  user data: {globals.user_data_path}')

    # Load settings from platform user-data directory (never in the repo root)
    settings_path = os.path.join(globals.user_data_path, 'settings.json')
    _settings_existed = os.path.exists(settings_path)  # check BEFORE migration may create the file
    _migrate_old_settings(settings_path)
    globals.settings = JsonSettings(settings_path)

    # If user relocated the data folder via Preferences > Resources, honor that path.
    _saved_data_path = globals.settings.value('DataPath', '')
    if _saved_data_path and os.path.isdir(_saved_data_path):
        globals.actor_data_path = str(_saved_data_path).replace("\\", "/")

    # Apply project default preferences on first launch (no existing settings.json)
    if not _settings_existed:
        _defaults_path = os.path.join(globals.miyamoto_path, 'miyamotodata', 'default_settings.json')
        if os.path.isfile(_defaults_path):
            try:
                with open(_defaults_path, 'r', encoding='utf-8') as _df:
                    _defaults = json.load(_df)
                for _k, _v in _defaults.items():
                    if not globals.settings.contains(_k):
                        globals.settings.setValue(_k, _v)
            except Exception:
                pass

    # First-run defaults
    if setting("MiyamotoVersion") is None:
        setSetting("isDX", False)
        setSetting("MiyamotoVersion", globals.MiyamotoVersion)
        setSetting('uiStyle', "Fusion")
        globals.settings.sync()

    # Settings that came from Miyamoto! DX are a Deluxe setup
    _migrate_dx_settings()

    # Existing users upgrading from builds that predate the interactive setup:
    # if they already have a valid game path, skip the wizard automatically.
    # Pass the path explicitly so this works before LoadGameDef() is called.
    if not setting('SetupComplete', False) and isValidGamePath(setting('GamePath', '')):
        setSetting('SetupComplete', True)

    # Load theme and style from settings (respects defaults from default_settings.json)
    LoadTheme()
    SetAppStyle()

    # First launch: show the Interactive Setup wizard so the user can download
    # required data before we check for missing files.
    if not setting('SetupComplete', False):
        from .firstRunWizard import InteractiveSetupDialog
        _wizard = InteractiveSetupDialog(first_run=True)
        _wizard.setWindowModality(Qt.ApplicationModal)
        _wizard.exec_()

        if _wizard.result() != QtWidgets.QDialog.Accepted:
            # applySettings() may have already been called when the All Set page
            # was reached (SetupComplete=True written to disk). If so, let the app
            # continue to the welcome page. If not, the user bailed early — exit.
            if not setting('SetupComplete', False):
                sys.exit(0)
        else:
            _wizard.applySettings()
        del _wizard

    # Check if required files are missing (after possible wizard download)
    if FilesAreMissing():
        sys.exit(1)

    # Migrate legacy settings (one-time, idempotent)
    _migrate_games_settings()

    # Load required stuff
    globals.Sprites = None
    globals.SpriteListData = None
    _base = setting('LastBaseGame', 'NSMBU')
    _mods = setting('LastMods') or []
    if isinstance(_mods, str):
        _mods = [_mods]
    LoadGameDef(_base, _mods)
    LoadActionsLists()
    LoadTilesetNames()
    LoadObjDescriptions()
    LoadSpriteData()
    LoadSpriteListData()
    LoadEntranceNames()
    LoadNumberFont()
    LoadOverrides()
    SLib.OutlineColor = globals.theme.color('smi')
    SLib.main()

    # Set the default window icon (used for random popups and stuff)
    _icon_name = 'pyamoto1024mac.png' if platform.system() == 'Darwin' else 'pyamoto1024.png'
    globals.app.setWindowIcon(QtGui.QIcon(os.path.join(globals.miyamoto_path, 'miyamotodata', 'app_icons', _icon_name)))
    globals.app.setApplicationDisplayName('Pyamoto')

    gt = setting('GridType')
    if gt == 'checker':
        globals.GridType = 'checker'

    elif gt == 'grid':
        globals.GridType = 'grid'

    else:
        globals.GridType = None

    globals.CollisionsShown = setting('ShowCollisions', False)
    globals.ObjectsFrozen = setting('FreezeObjects', False)
    globals.SpritesFrozen = setting('FreezeSprites', False)
    globals.EntrancesFrozen = setting('FreezeEntrances', False)
    globals.LocationsFrozen = setting('FreezeLocations', False)
    globals.PathsFrozen = setting('FreezePaths', False)
    globals.CommentsFrozen = setting('FreezeComments', False)
    globals.OverwriteSprite = setting('OverwriteSprite', False)
    globals.PlaceObjectFullSize = setting('PlaceObjectFullSize', False)
    globals.CategorizedSpriteData = setting('CategorizedSpriteData', False)
    globals.SpriteListPreviewSize = setting('SpriteListPreviewSize', globals.SPRITE_PREVIEW_DISABLED)
    globals.SpriteListPreviewHighDetail = setting('SpriteListPreviewHighDetail', False)
    globals.UseRGBA8 = setting('UseRGBA8', False)
    globals.RealViewEnabled = setting('RealViewEnabled', True)
    globals.SpritesShown = setting('ShowSprites', True)
    globals.SpriteImagesShown = setting('ShowSpriteImages', True)
    globals.LocationsShown = setting('ShowLocations', True)
    globals.CommentsShown = setting('ShowComments', True)
    globals.PathsShown = setting('ShowPaths', True)
    globals.RotationShown = setting('RotationShown', False)

    SLib.RotationFPS = setting('RotationFPS', 30)
    globals.UseOuterSarcFormat = setting('UseOuterSarcFormat', False)
    globals.ModifyInnerName = setting('ModifyInnerName', False)

    SLib.RealViewEnabled = globals.RealViewEnabled

    if not isValidObjectsPath():
        setSetting('ObjPath', None)

    LoadTheme()
    SetAppStyle()

    # Create and show the main window
    globals.mainWindow = MiyamotoWindow()
    globals.mainWindow.__init2__()  # fixes bugs
    globals.mainWindow.show()

    from .updater import check_for_updates
    check_for_updates()

    exitcodesys = globals.app.exec_()
    globals.app.deleteLater()
    sys.exit(exitcodesys)


if __name__ == '__main__': main()
