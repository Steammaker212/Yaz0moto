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
import re
import json
import shutil
import weakref
import zipfile
from urllib.parse import unquote, urlparse

import requests

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QThread, pyqtSignal
Qt = QtCore.Qt

from .bytes import bytes_to_string, to_bytes
from . import globals
from . import spriteicons
from .items import ZoneItem
from .misc import HexSpinBox, BGName, setting, setSetting, hasLevelNameSources
from .updater import _CHANNEL_LABELS, _CHANNEL_VALUES, _default_channel, check_for_updates_now
from .ui import MiyamotoTheme, availableThemes, toQColor, GetIcon, createHorzLine, TOOLBAR_ICON_SIZES, toolbarIconSize
from .widgets import LoadingTab, TilesetsTab
from .verifications import SetDirty

#################################


class InputBox(QtWidgets.QDialog):
    Type_TextBox = 1
    Type_SpinBox = 2
    Type_HexSpinBox = 3

    def __init__(self, type=Type_TextBox):
        super().__init__()

        self.label = QtWidgets.QLabel('-')
        self.label.setWordWrap(True)

        if type == InputBox.Type_TextBox:
            self.textbox = QtWidgets.QLineEdit()
            widget = self.textbox
        elif type == InputBox.Type_SpinBox:
            self.spinbox = QtWidgets.QSpinBox()
            widget = self.spinbox
        elif type == InputBox.Type_HexSpinBox:
            self.spinbox = HexSpinBox()
            widget = self.spinbox

        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        self.layout = QtWidgets.QVBoxLayout()
        self.layout.addWidget(self.label)
        self.layout.addWidget(widget)
        self.layout.addWidget(self.buttons)
        self.setLayout(self.layout)


class AboutDialog(QtWidgets.QDialog):
    """
    The About info for Yaz0moto
    """

    def __init__(self):
        """
        Creates and initializes the dialog
        """
        super().__init__()
        self.setWindowTitle('About Yaz0moto')
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        import platform as _platform
        icon_name = 'yaz0moto1024mac.png' if _platform.system() == 'Darwin' else 'yaz0moto1024.png'
        icon_path = os.path.join(globals.miyamoto_path, 'yaz0data', 'app_icons', icon_name)
        if os.path.isfile(icon_path):
            self.setWindowIcon(QtGui.QIcon(icon_path))
        else:
            self.setWindowIcon(GetIcon('help'))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 20)
        layout.setSpacing(0)

        # Logo (click the star!)
        if os.path.isfile(icon_path):
            from .welcomestar import AnimatedStarLogo
            self.logo = AnimatedStarLogo(icon_path, 108)
            layout.addWidget(self.logo, 0, Qt.AlignHCenter)
            layout.addSpacing(14)

        # Heading
        heading = QtWidgets.QLabel('Yaz0moto Level Editor')
        heading.setAlignment(Qt.AlignHCenter)
        hf = heading.font()
        hf.setPointSize(hf.pointSize() + 5)
        hf.setBold(True)
        heading.setFont(hf)
        layout.addWidget(heading)
        layout.addSpacing(4)

        # Version
        ver = QtWidgets.QLabel('v' + globals.MiyamotoVersion)
        ver.setAlignment(Qt.AlignHCenter)
        ver.setStyleSheet('color: palette(mid);')
        layout.addWidget(ver)
        layout.addSpacing(16)

        # Description
        desc = QtWidgets.QLabel(
            'A level editor for New Super Mario Bros. U and New Super Mario Bros. U Deluxe, '
            'with tileset editing for both games. A fork of Pyamoto.')
        desc.setAlignment(Qt.AlignHCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet('color: palette(text);')
        layout.addWidget(desc)
        layout.addSpacing(16)

        # Separator
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Sunken)
        layout.addWidget(sep)
        layout.addSpacing(12)

        # Resources heading
        res_hdr = QtWidgets.QLabel('Resources')
        hdr_font = res_hdr.font()
        hdr_font.setPointSize(hdr_font.pointSize() - 1)
        hdr_font.setBold(True)
        res_hdr.setFont(hdr_font)
        res_hdr.setStyleSheet('color: palette(mid);')
        res_hdr.setAlignment(Qt.AlignHCenter)
        layout.addWidget(res_hdr)
        layout.addSpacing(8)

        # Links
        links = QtWidgets.QLabel(
            '<html><body style="text-align:center;">'
            '&#x1F30D; <a href="https://github.com/Steammaker212/Yaz0moto">GitHub</a>'
            ' &nbsp;&middot;&nbsp; '
            '&#x1F41B; <a href="https://github.com/Steammaker212/Yaz0moto/issues">Report a bug</a>'
            ' &nbsp;&middot;&nbsp; '
            '&#x1F4D6; <a href="https://zenith.nsmbu.net/">NSMBU Wiki</a>'
            '</body></html>')
        links.setTextFormat(Qt.RichText)
        links.setOpenExternalLinks(True)
        links.setAlignment(Qt.AlignHCenter)
        links.setWordWrap(True)
        layout.addWidget(links)
        layout.addSpacing(16)

        # Credits
        credits = QtWidgets.QLabel(
            '<html><body style="text-align:center;">'
            'Yaz0moto is maintained by <b>Steammaker212</b>.<br>'
            'Based on <b>Pyamoto</b> by Zenith Team and <b>Miyamoto!</b> by AboodXD, Gota7 and contributors.<br>'
            'Deluxe support uses code from Miyamoto! DX.<br>'
            '</body></html>')
        credits.setAlignment(Qt.AlignHCenter)
        credits.setWordWrap(True)
        credits.setStyleSheet('color: palette(mid); font-size: 11px;')
        layout.addWidget(credits)
        layout.addSpacing(20)

        # OK button
        btn = QtWidgets.QPushButton('OK')
        btn.setFixedHeight(36)
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)

        # Wrapped labels only know their height once the width is fixed
        self.setFixedWidth(440)
        height = layout.totalHeightForWidth(440)
        self.setFixedSize(440, height if height > 0 else self.sizeHint().height())


class ObjectShiftDialog(QtWidgets.QDialog):
    """
    Lets you pick an amount to shift selected items by
    """

    def __init__(self):
        """
        Creates and initializes the dialog
        """
        super().__init__()
        self.setWindowTitle('Shift Items')
        self.setWindowIcon(GetIcon('move'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.XOffset = QtWidgets.QSpinBox()
        self.XOffset.setRange(-16384, 16383)

        self.YOffset = QtWidgets.QSpinBox()
        self.YOffset.setRange(-8192, 8191)

        buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

        moveLayout = QtWidgets.QFormLayout()
        offsetlabel = QtWidgets.QLabel("Enter an offset in pixels - each block is 16 pixels in size. Note that normal objects can only be placed on 16x16 boundaries, so if the offset you enter isn't a multiple of 16, they won't be moved correctly.")
        offsetlabel.setWordWrap(True)
        moveLayout.addWidget(offsetlabel)
        moveLayout.addRow('X:', self.XOffset)
        moveLayout.addRow('Y:', self.YOffset)

        moveGroupBox = QtWidgets.QGroupBox('Move objects by:')
        moveGroupBox.setLayout(moveLayout)

        mainLayout = QtWidgets.QVBoxLayout()
        mainLayout.addWidget(moveGroupBox)
        mainLayout.addWidget(buttonBox)
        self.setLayout(mainLayout)


class ObjectTilesetSwapDialog(QtWidgets.QDialog):
    """
    Lets you pick tilesets to swap objects to
    """

    def __init__(self):
        """
        Creates and initializes the dialog
        """
        super().__init__()
        self.setWindowTitle('Swap Objects\' Tilesets')
        self.setWindowIcon(GetIcon('swap'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # Create widgets
        self.FromTS = QtWidgets.QSpinBox()
        self.FromTS.setRange(1, 4)

        self.ToTS = QtWidgets.QSpinBox()
        self.ToTS.setRange(1, 4)

        # Swap layouts
        swapLayout = QtWidgets.QFormLayout()

        swapLayout.addRow('From tileset:', self.FromTS)
        swapLayout.addRow('To tileset:', self.ToTS)

        self.DoExchange = QtWidgets.QCheckBox('Exchange (perform 2-way conversion)')

        # Buttonbox
        buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

        # Main layout
        mainLayout = QtWidgets.QVBoxLayout()
        mainLayout.addLayout(swapLayout)
        mainLayout.addWidget(self.DoExchange)
        mainLayout.addWidget(buttonBox)
        self.setLayout(mainLayout)


class ObjectTypeSwapDialog(QtWidgets.QDialog):
    """
    Lets you pick object types to swap objects to
    """

    def __init__(self):
        """
        Creates and initializes the dialog
        """
        super().__init__()
        self.setWindowTitle('Swap Objects\' Types')
        self.setWindowIcon(GetIcon('swap'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # Create widgets
        self.FromType = QtWidgets.QSpinBox()
        self.FromType.setRange(0, 255)

        self.ToType = QtWidgets.QSpinBox()
        self.ToType.setRange(0, 255)

        self.FromTileset = QtWidgets.QSpinBox()
        self.FromTileset.setRange(1, 4)

        self.ToTileset = QtWidgets.QSpinBox()
        self.ToTileset.setRange(1, 4)

        self.DoExchange = QtWidgets.QCheckBox('Exchange (perform 2-way conversion)')

        # Swap layout
        swapLayout = QtWidgets.QGridLayout()

        swapLayout.addWidget(QtWidgets.QLabel('From tile type:'), 0, 0)
        swapLayout.addWidget(self.FromType, 0, 1)

        swapLayout.addWidget(QtWidgets.QLabel('From tileset:'), 1, 0)
        swapLayout.addWidget(self.FromTileset, 1, 1)

        swapLayout.addWidget(QtWidgets.QLabel('To tile type:'), 0, 2)
        swapLayout.addWidget(self.ToType, 0, 3)

        swapLayout.addWidget(QtWidgets.QLabel('To tileset:'), 1, 2)
        swapLayout.addWidget(self.ToTileset, 1, 3)

        # Buttonbox
        buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

        # Main layout
        mainLayout = QtWidgets.QVBoxLayout()
        mainLayout.addLayout(swapLayout)
        mainLayout.addWidget(self.DoExchange)
        mainLayout.addWidget(buttonBox)
        self.setLayout(mainLayout)


class MetaInfoDialog(QtWidgets.QDialog):
    """
    Allows the user to enter in various meta-info to be kept in the level for display
    """

    def __init__(self):
        """
        Creates and initializes the dialog
        """
        super().__init__()
        self.setWindowTitle('Level Information')
        self.setWindowIcon(GetIcon('info'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        title = globals.Area.Metadata.strData('Title')
        author = globals.Area.Metadata.strData('Author')
        group = globals.Area.Metadata.strData('Group')
        website = globals.Area.Metadata.strData('Website')
        creator = globals.Area.Metadata.strData('Creator')
        password = globals.Area.Metadata.strData('Password')
        if title is None: title = '-'
        if author is None: author = '-'
        if group is None: group = '-'
        if website is None: website = '-'
        if creator is None: creator = '(unknown)'
        if password is None: password = ''

        self.levelName = QtWidgets.QLineEdit()
        self.levelName.setMaxLength(128)
        self.levelName.setReadOnly(True)
        self.levelName.setMinimumWidth(320)
        self.levelName.setText(title)

        self.Author = QtWidgets.QLineEdit()
        self.Author.setMaxLength(128)
        self.Author.setReadOnly(True)
        self.Author.setMinimumWidth(320)
        self.Author.setText(author)

        self.Group = QtWidgets.QLineEdit()
        self.Group.setMaxLength(128)
        self.Group.setReadOnly(True)
        self.Group.setMinimumWidth(320)
        self.Group.setText(group)

        self.Website = QtWidgets.QLineEdit()
        self.Website.setMaxLength(128)
        self.Website.setReadOnly(True)
        self.Website.setMinimumWidth(320)
        self.Website.setText(website)

        self.Password = QtWidgets.QLineEdit()
        self.Password.setMaxLength(128)
        self.Password.textChanged.connect(self.PasswordEntry)
        self.Password.setMinimumWidth(320)

        self.changepw = QtWidgets.QPushButton('Add/Change Password')

        if password != '':
            self.levelName.setReadOnly(False)
            self.Author.setReadOnly(False)
            self.Group.setReadOnly(False)
            self.Website.setReadOnly(False)
            self.changepw.setDisabled(False)

        buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttonBox.addButton(self.changepw, buttonBox.ActionRole)
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)
        self.changepw.clicked.connect(self.ChangeButton)
        self.changepw.setDisabled(True)

        self.lockedLabel = QtWidgets.QLabel("This level's information is locked.<br>Please enter the password below in order to modify it.")

        infoLayout = QtWidgets.QFormLayout()
        infoLayout.addWidget(self.lockedLabel)
        infoLayout.addRow('Password:', self.Password)
        infoLayout.addRow('Title:', self.levelName)
        infoLayout.addRow('Author:', self.Author)
        infoLayout.addRow('Group:', self.Group)
        infoLayout.addRow('Website:', self.Website)

        self.PasswordLabel = infoLayout.labelForField(self.Password)

        levelIsLocked = password != ''
        self.lockedLabel.setVisible(levelIsLocked)
        self.PasswordLabel.setVisible(levelIsLocked)
        self.Password.setVisible(levelIsLocked)

        infoGroupBox = QtWidgets.QGroupBox('Created with [name]'.replace('[name]', str(creator)))
        infoGroupBox.setLayout(infoLayout)

        mainLayout = QtWidgets.QVBoxLayout()
        mainLayout.addWidget(infoGroupBox)
        mainLayout.addWidget(buttonBox)
        self.setLayout(mainLayout)

        self.PasswordEntry('')

    def PasswordEntry(self, text):
        pswd = globals.Area.Metadata.strData('Password')
        if pswd is None: pswd = ''
        if text == pswd:
            self.levelName.setReadOnly(False)
            self.Author.setReadOnly(False)
            self.Group.setReadOnly(False)
            self.Website.setReadOnly(False)
            self.changepw.setDisabled(False)
        else:
            self.levelName.setReadOnly(True)
            self.Author.setReadOnly(True)
            self.Group.setReadOnly(True)
            self.Website.setReadOnly(True)
            self.changepw.setDisabled(True)

    # To all would be crackers who are smart enough to reach here:
    #
    #   Make your own levels.
    #
    #
    #
    #       - The management
    #


    def ChangeButton(self):
        """
        Allows the changing of a given password
        """

        class ChangePWDialog(QtWidgets.QDialog):
            """
            Dialog
            """

            def __init__(self):
                super().__init__()
                self.setWindowTitle('Change Password')
                self.setWindowIcon(GetIcon('info'))
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

                self.New = QtWidgets.QLineEdit()
                self.New.setMaxLength(64)
                self.New.textChanged.connect(self.PasswordMatch)
                self.New.setMinimumWidth(320)

                self.Verify = QtWidgets.QLineEdit()
                self.Verify.setMaxLength(64)
                self.Verify.textChanged.connect(self.PasswordMatch)
                self.Verify.setMinimumWidth(320)

                self.Ok = QtWidgets.QPushButton('OK')
                self.Cancel = QtWidgets.QDialogButtonBox.Cancel

                buttonBox = QtWidgets.QDialogButtonBox()
                buttonBox.addButton(self.Ok, buttonBox.AcceptRole)
                buttonBox.addButton(self.Cancel)

                buttonBox.accepted.connect(self.accept)
                buttonBox.rejected.connect(self.reject)
                self.Ok.setDisabled(True)

                infoLayout = QtWidgets.QFormLayout()
                infoLayout.addRow('New Password:', self.New)
                infoLayout.addRow('Verify Password:', self.Verify)

                infoGroupBox = QtWidgets.QGroupBox('Level Information')

                infoLabel = QtWidgets.QVBoxLayout()
                infoLabel.addWidget(QtWidgets.QLabel('Password may be composed of any ASCII character,<br>and up to 64 characters long.<br>'), 0, Qt.AlignCenter)
                infoLabel.addLayout(infoLayout)
                infoGroupBox.setLayout(infoLabel)

                mainLayout = QtWidgets.QVBoxLayout()
                mainLayout.addWidget(infoGroupBox)
                mainLayout.addWidget(buttonBox)
                self.setLayout(mainLayout)

            def PasswordMatch(self, text):
                self.Ok.setDisabled(self.New.text() != self.Verify.text() and self.New.text() != '')

        dlg = ChangePWDialog()
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.lockedLabel.setVisible(True)
            self.Password.setVisible(True)
            self.PasswordLabel.setVisible(True)
            pswd = str(dlg.Verify.text())
            globals.Area.Metadata.setStrData('Password', pswd)
            self.Password.setText(pswd)
            SetDirty()

            self.levelName.setReadOnly(False)
            self.Author.setReadOnly(False)
            self.Group.setReadOnly(False)
            self.Website.setReadOnly(False)
            self.changepw.setDisabled(False)


class AreaOptionsDialog(QtWidgets.QDialog):
    """
    Dialog which lets you choose among various area options from tabs
    """

    def __init__(self):
        """
        Creates and initializes the tab dialog
        """
        super().__init__()
        self.setWindowTitle('Area Options')
        self.setWindowIcon(GetIcon('area'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.tabWidget = QtWidgets.QTabWidget()
        self.LoadingTab = LoadingTab()
        self.TilesetsTab = TilesetsTab()
        self.tabWidget.addTab(self.TilesetsTab, 'Tilesets')
        self.tabWidget.addTab(self.LoadingTab, 'Settings')

        buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)

        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

        mainLayout = QtWidgets.QVBoxLayout()
        mainLayout.addWidget(self.tabWidget)
        mainLayout.addWidget(buttonBox)
        self.setLayout(mainLayout)


class ZonesDialog(QtWidgets.QDialog):
    """
    Dialog for editing zone properties.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Edit Zones')
        self.setWindowIcon(GetIcon('zones'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._dirtyTabs = set()  # set of ZoneTab objects with unsaved changes
        self._newButtons = []    # one per zone tab, for _updateButtonStates
        self._cloneButtons = []  # one per zone tab, for _updateButtonStates

        self.tabWidget = QtWidgets.QTabWidget()
        self.zoneTabs = []
        self.BGTabs = []

        self.tabWidget.tabBarClicked.connect(self.NewButtonTab)
        self.tabWidget.setTabBarAutoHide(True)

        for i, z in enumerate(globals.Area.zones):
            self._addZoneTab(z, i)
        self._addNewButtonTab()

        self._updateButtonStates()

        saveBtn = QtWidgets.QPushButton("OK")
        saveBtn.setDefault(True)
        dontSaveBtn = QtWidgets.QPushButton("Cancel")
        saveBtn.clicked.connect(self.accept)
        dontSaveBtn.clicked.connect(self._forceReject)

        btnRow = QtWidgets.QHBoxLayout()
        btnRow.addStretch()
        btnRow.addWidget(saveBtn)
        btnRow.addWidget(dontSaveBtn)

        mainLayout = QtWidgets.QVBoxLayout()
        mainLayout.setSpacing(6)
        mainLayout.addWidget(self.tabWidget)
        mainLayout.addLayout(btnRow)
        self.setLayout(mainLayout)

    def _addNewButtonTab(self):
        newBtn = QtWidgets.QPushButton('New')
        cloneBtn = QtWidgets.QPushButton('Duplicate')
        deleteBtn = QtWidgets.QPushButton('Delete')
        newBtn.clicked.connect(self.NewZone)
        cloneBtn.setEnabled(False)
        deleteBtn.setEnabled(False)

        zoneBtnRow = QtWidgets.QHBoxLayout()
        zoneBtnRow.setContentsMargins(0, 0, 0, 0)
        zoneBtnRow.addWidget(newBtn)
        zoneBtnRow.addWidget(cloneBtn)
        zoneBtnRow.addWidget(deleteBtn)

        container = QtWidgets.QWidget()
        cLayout = QtWidgets.QVBoxLayout(container)
        cLayout.setContentsMargins(6, 6, 6, 6)
        cLayout.setSpacing(5)
        cLayout.addLayout(zoneBtnRow)
        cLayout.setAlignment(Qt.AlignBottom)

        self.tabWidget.addTab(container, '+')

    def _addZoneTab(self, z, idx):
        zoneTab = ZoneTab(z)
        bgTab = BGTab(z.background)
        self.zoneTabs.append(zoneTab)
        self.BGTabs.append(bgTab)

        # Merged Dimensions + Bounds widget (single tab, separated by a line)
        dimBoundsWidget = QtWidgets.QWidget()
        dbLayout = QtWidgets.QVBoxLayout(dimBoundsWidget)
        dbLayout.setContentsMargins(0, 0, 0, 0)
        dbLayout.setSpacing(4)
        dbLayout.addWidget(zoneTab.dimWidget)
        dbLayout.addWidget(createHorzLine())
        dbLayout.addWidget(zoneTab.boundsWidget)

        # Inner per-zone tab widget: one tab per settings section
        innerTabs = QtWidgets.QTabWidget()
        innerTabs.addTab(dimBoundsWidget,   'Dimensions')
        innerTabs.addTab(zoneTab.camWidget, 'Camera')
        innerTabs.addTab(zoneTab.audioWidget, 'Audio')
        innerTabs.addTab(bgTab,             'Background')

        # New / Duplicate / Delete — 3-wide row below inner tabs
        newBtn = QtWidgets.QPushButton('New')
        cloneBtn = QtWidgets.QPushButton('Duplicate')
        deleteBtn = QtWidgets.QPushButton('Delete')
        newBtn.clicked.connect(self.NewZone)
        cloneBtn.clicked.connect(self.CloneZone)
        deleteBtn.clicked.connect(self.DeleteZone)
        self._newButtons.append(newBtn)
        self._cloneButtons.append(cloneBtn)

        zoneBtnRow = QtWidgets.QHBoxLayout()
        zoneBtnRow.setContentsMargins(0, 0, 0, 0)
        zoneBtnRow.addWidget(newBtn)
        zoneBtnRow.addWidget(cloneBtn)
        zoneBtnRow.addWidget(deleteBtn)

        container = QtWidgets.QWidget()
        cLayout = QtWidgets.QVBoxLayout(container)
        cLayout.setContentsMargins(6, 6, 6, 6)
        cLayout.setSpacing(5)
        cLayout.addWidget(innerTabs)
        cLayout.addLayout(zoneBtnRow)

        label = self._zoneLabel(idx)
        self.tabWidget.insertTab(len(self.zoneTabs) - 1, container, label)

        # Dirty tracking — *args absorbs the signal's emitted value so _zt is never overwritten
        def markDirty(*_, _zt=zoneTab):
            self._markTabDirty(_zt)

        zoneTab.connectChanges(markDirty)
        bgTab.connectChanges(markDirty)

    def _zoneLabel(self, idx):
        return 'Zone [num]'.replace('[num]', str(idx + 1))

    def _markTabDirty(self, zoneTab):
        if zoneTab in self._dirtyTabs:
            return
        self._dirtyTabs.add(zoneTab)
        try:
            idx = self.zoneTabs.index(zoneTab)
        except ValueError:
            return
        text = self.tabWidget.tabText(idx)
        if not text.endswith(' *'):
            self.tabWidget.setTabText(idx, text + ' *')

    def _updateButtonStates(self):
        enabled = len(self.zoneTabs) < 8
        for btn in self._newButtons:
            btn.setEnabled(enabled)
        for btn in self._cloneButtons:
            btn.setEnabled(enabled)

        count = len(self.zoneTabs)
        self.tabWidget.setTabEnabled(self.tabWidget.count() - 1, count < 8)

    def _renormalizeLabels(self):
        count = len(self.zoneTabs)
        for i in range(count):
            label = 'Zone [num]'.replace('[num]', str(i + 1))
            if self.zoneTabs[i] in self._dirtyTabs:
                label += ' *'
            self.tabWidget.setTabText(i, label)

    def reject(self):
        if self._dirtyTabs:
            names = ', '.join(
                self.tabWidget.tabText(self.zoneTabs.index(zt)).rstrip(' *')
                for zt in self._dirtyTabs
                if zt in self.zoneTabs
            )
            msg = QtWidgets.QMessageBox(self)
            msg.setWindowTitle('Unsaved Changes')
            msg.setText(f'You have unsaved changes in: {names}')
            msg.setInformativeText('Do you want to save before closing?')
            saveBtn = msg.addButton('Save', QtWidgets.QMessageBox.AcceptRole)
            msg.addButton("Don't Save", QtWidgets.QMessageBox.DestructiveRole)
            msg.addButton('Cancel', QtWidgets.QMessageBox.RejectRole)
            msg.exec_()
            clicked = msg.clickedButton()
            if clicked == saveBtn:
                self.accept()
            elif msg.buttonRole(clicked) == QtWidgets.QMessageBox.DestructiveRole:
                super().reject()
            # else Cancel — do nothing, keep dialog open
        else:
            super().reject()

    def _forceReject(self):
        super().reject()

    def NewZone(self):
        if len(self.zoneTabs) >= 15:
            result = QtWidgets.QMessageBox.warning(
                self, 'Warning', 'You are trying to add more than 15 zones to a level - keep in mind that without the proper fix to the game, this will cause your level to <b>crash</b> or have other strange issues!<br><br>Are you sure you want to do this?',
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if result == QtWidgets.QMessageBox.No:
                return

        idx = len(self.zoneTabs)
        z = ZoneItem(256, 256, 448, 224, 0, 0, idx, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0,
                     (0, 0, 0, 0, 0, 0xF, 0, 0), (0, 0, 0, 0, to_bytes('Black', 16), 0))
        self._addZoneTab(z, idx)
        self._renormalizeLabels()
        self._updateButtonStates()
        self.tabWidget.setCurrentIndex(len(self.zoneTabs) - 1)

    def DeleteZone(self):
        curindex = self.tabWidget.currentIndex()
        if self.tabWidget.count() == 0:
            return
        deleted_tab = self.zoneTabs[curindex]
        self._dirtyTabs.discard(deleted_tab)
        self.tabWidget.removeTab(curindex)
        self.zoneTabs.pop(curindex)
        self.BGTabs.pop(curindex)
        self._newButtons.pop(curindex)
        self._cloneButtons.pop(curindex)
        self._renormalizeLabels()
        self._updateButtonStates()
        self.tabWidget.setCurrentIndex(curindex - 1)

    def CloneZone(self):
        if len(self.zoneTabs) >= 15:
            result = QtWidgets.QMessageBox.warning(
                self, 'Warning', 'You are trying to add more than 15 zones to a level - keep in mind that without the proper fix to the game, this will cause your level to <b>crash</b> or have other strange issues!<br><br>Are you sure you want to do this?',
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if result == QtWidgets.QMessageBox.No:
                return

        src = self.tabWidget.currentIndex()
        z0 = self.zoneTabs[src].zoneObj
        idx = len(self.zoneTabs)
        z = ZoneItem(
            z0.objx, z0.objy, z0.width, z0.height, z0.modeldark, z0.terraindark, idx, 0,
            z0.cammode, z0.camzoom, z0.unk1, z0.visibility, 0, z0.unk2, z0.camtrack, z0.unk3,
            z0.music, z0.sfxmod, 0, z0.type,
            (z0.yupperbound, z0.ylowerbound, z0.yupperbound2, z0.ylowerbound2, z0.entryid,
             z0.mpcamzoomadjust, z0.yupperbound3, z0.ylowerbound3),
            z0.background,
        )
        z.customMusicName = getattr(z0, 'customMusicName', '')
        self._addZoneTab(z, idx)
        self._renormalizeLabels()
        self._updateButtonStates()
        self.tabWidget.setCurrentIndex(len(self.zoneTabs) - 1)

    def NewButtonTab(self, tabIndex):
        if tabIndex == self.tabWidget.count() - 1:
            self.NewZone()


class ZoneTab:
    """
    Builds all zone-property widgets for one zone. Not a QWidget itself;
    its four sub-widgets (dimWidget, camWidget, boundsWidget, audioWidget)
    are inserted directly into the inner QTabWidget in ZonesDialog.
    All widget attributes preserve the same names used by HandleZones in app.py.
    """

    def __init__(self, z):
        self.zoneObj = z
        self.AutoChangingSize = False
        self.AutoEditMusic = False
        self.zm = -1

        self.dimWidget    = self._buildDimensions(z)
        self.camWidget    = self._buildCamera(z)
        self.boundsWidget = self._buildBounds(z)
        self.audioWidget  = self._buildAudio(z)

    # ── Dimensions ──────────────────────────────────────────────────────────

    def _buildDimensions(self, z):
        self.Zone_xpos = QtWidgets.QSpinBox()
        self.Zone_xpos.setRange(16, 65535)
        self.Zone_xpos.setToolTip('<b>X position:</b><br>Sets the X Position of the upper left corner')
        self.Zone_xpos.setValue(z.objx)

        self.Zone_ypos = QtWidgets.QSpinBox()
        self.Zone_ypos.setRange(16, 65535)
        self.Zone_ypos.setToolTip('<b>Y position:</b><br>Sets the Y Position of the upper left corner')
        self.Zone_ypos.setValue(z.objy)

        self.Zone_width = QtWidgets.QSpinBox()
        self.Zone_width.setRange(80, 65535)
        self.Zone_width.setToolTip('<b>X size:</b><br>Sets the width of the zone')
        self.Zone_width.setValue(z.width)
        self.Zone_width.valueChanged.connect(self.PresetDeselected)

        self.Zone_height = QtWidgets.QSpinBox()
        self.Zone_height.setRange(16, 65535)
        self.Zone_height.setToolTip('<b>Y size:</b><br>Sets the height of the zone')
        self.Zone_height.setValue(z.height)
        self.Zone_height.valueChanged.connect(self.PresetDeselected)

        # Common retail zone presets
        self.Zone_presets_values = (
            '26×14 Tiles', '28×14 Tiles', '32×17 Tiles',
            '35×19 Tiles', '38×20 Tiles', '44×24 Tiles', '59×28 Tiles')
        self.Zone_presets = QtWidgets.QComboBox()
        self.Zone_presets.addItems(self.Zone_presets_values)
        self.Zone_presets.setToolTip('<b>Select Preset:</b><br>Snaps the zone to common sizes.')
        self.Zone_presets.currentIndexChanged.connect(self.PresetSelected)
        self.PresetDeselected()

        self.snapButton8 = QtWidgets.QPushButton('Snap to 8x8 Grid')
        self.snapButton8.clicked.connect(lambda: self.HandleSnapTo8x8Grid(z))
        self.snapButton16 = QtWidgets.QPushButton('Snap to 16x16 Grid')
        self.snapButton16.clicked.connect(lambda: self.HandleSnapTo16x16Grid(z))

        posForm = QtWidgets.QFormLayout()
        posForm.addRow('X position:',  self.Zone_xpos)
        posForm.addRow('Y position:', self.Zone_ypos)

        sizeForm = QtWidgets.QFormLayout()
        sizeForm.addRow('X size:', self.Zone_width)
        sizeForm.addRow('Y size:', self.Zone_height)
        sizeForm.addRow('Select Preset:', self.Zone_presets)

        snapRow = QtWidgets.QHBoxLayout()
        snapRow.addWidget(self.snapButton8)
        snapRow.addWidget(self.snapButton16)

        cols = QtWidgets.QHBoxLayout()
        cols.addLayout(posForm)
        cols.addSpacing(12)
        cols.addLayout(sizeForm)

        w = QtWidgets.QWidget()
        L = QtWidgets.QVBoxLayout(w)
        L.setContentsMargins(8, 8, 8, 8)
        L.addLayout(cols)
        L.addLayout(snapRow)
        L.addStretch()
        return w

    def HandleSnapTo8x8Grid(self, z):
        left  = self.Zone_xpos.value()
        top   = self.Zone_ypos.value()
        right  = left + self.Zone_width.value()
        bottom = top  + self.Zone_height.value()

        def snap8(v):
            return v - (v % 8) if v % 8 < 4 else v + 8 - (v % 8)

        left, top, right, bottom = snap8(left), snap8(top), snap8(right), snap8(bottom)
        if right  <= left:  right  += 8
        if bottom <= top:   bottom += 8
        right -= left;  bottom -= top
        left   = max(16, min(left,   65528))
        top    = max(16, min(top,    65528))
        right  = max(80, min(right,  65528))
        bottom = max(16, min(bottom, 65528))
        self.Zone_xpos.setValue(left);   self.Zone_ypos.setValue(top)
        self.Zone_width.setValue(right); self.Zone_height.setValue(bottom)

    def HandleSnapTo16x16Grid(self, z):
        left  = self.Zone_xpos.value()
        top   = self.Zone_ypos.value()
        right  = left + self.Zone_width.value()
        bottom = top  + self.Zone_height.value()

        def snap16(v):
            return v - (v % 16) if v % 16 < 8 else v + 16 - (v % 16)

        left, top, right, bottom = snap16(left), snap16(top), snap16(right), snap16(bottom)
        if right  <= left:  right  += 16
        if bottom <= top:   bottom += 16
        right -= left;  bottom -= top
        left   = max(16, min(left,   65520))
        top    = max(16, min(top,    65520))
        right  = max(80, min(right,  65520))
        bottom = max(16, min(bottom, 65520))
        self.Zone_xpos.setValue(left);   self.Zone_ypos.setValue(top)
        self.Zone_width.setValue(right); self.Zone_height.setValue(bottom)

    def PresetSelected(self, info=None):
        if self.AutoChangingSize: return
        if self.Zone_presets.currentText() == '(None)': return
        w, h = self.Zone_presets.currentText()[:6].split('×')
        self.AutoChangingSize = True
        self.Zone_width.setValue(int(w) * 16)
        self.Zone_height.setValue(int(h) * 16)
        self.AutoChangingSize = False
        if self.Zone_presets.itemText(0) == '(None)':
            self.Zone_presets.removeItem(0)

    def PresetDeselected(self, info=None):
        if self.AutoChangingSize: return
        self.AutoChangingSize = True
        check = '%g×%g' % (self.Zone_width.value() / 16, self.Zone_height.value() / 16)
        found = next((p for p in self.Zone_presets_values if check == p[:6]), None)
        if found is not None:
            self.Zone_presets.setCurrentIndex(self.Zone_presets.findText(found))
            if self.Zone_presets.itemText(0) == '(None)':
                self.Zone_presets.removeItem(0)
        else:
            if self.Zone_presets.itemText(0) != '(None)':
                self.Zone_presets.insertItem(0, '(None)')
            self.Zone_presets.setCurrentIndex(0)
        self.AutoChangingSize = False

    # ── Camera ──────────────────────────────────────────────────────────────

    def _buildCamera(self, z):
        # Spotlight / full-dark checkboxes
        self.Zone_vspotlight = QtWidgets.QCheckBox('Layer 0 Spotlight')
        self.Zone_vspotlight.setToolTip('<b>Visibility - Layer 0 Spotlight:</b><br>Sets the visibility mode to spotlight. In Spotlight mode,<br>moving behind layer 0 objects enables a spotlight that<br>follows Mario around.')
        self.Zone_vfulldark  = QtWidgets.QCheckBox('Full Darkness')
        self.Zone_vfulldark.setToolTip('<b>Visibility - Full Darkness:</b><br>Sets the visibility mode to full darkness. In full dark mode,<br>the screen is completely black and visibility is only provided<br>by the available spotlight effect. Stars and some actors<br>can enhance the default visibility.')

        self.Zone_visibility = QtWidgets.QComboBox()
        self.zv = z.visibility
        if self.zv & 0x10: self.Zone_vspotlight.setChecked(True)
        if self.zv & 0x20: self.Zone_vfulldark.setChecked(True)
        self.ChangeVisibilityList()
        self.Zone_vspotlight.clicked.connect(self.ChangeVisibilityList)
        self.Zone_vfulldark.clicked.connect(self.ChangeVisibilityList)

        # Camera mode radios
        cammode = z.cammode if z.cammode <= 7 else 3
        camzoom = z.camzoom
        if cammode == 2:
            if camzoom > 8:  camzoom = 0
        elif 1 < cammode < 6:
            if camzoom > 9:  camzoom = 0
        else:
            if camzoom > 11: camzoom = 0

        self.Zone_cammodebuttongroup = QtWidgets.QButtonGroup()
        cammodebuttons = []
        for btnId, name, tooltip in [
            (0, 'Normal',                     'The standard camera mode, appropriate for most situations.'),
            (3, 'Static Zoom',                'The camera will not zoom out during multiplayer.'),
            (4, 'Static Zoom, Y Track Only',  'No multiplayer zoom-out; camera centered horizontally.'),
            (5, 'Static Zoom, Event-Ctrl*',   'No multiplayer zoom-out; event-controlled camera (*removed in NSMBU).'),
            (6, 'X Tracking Only',            'Camera only moves horizontally, aligned to bottom edge.'),
            (7, 'X Expanding Only',           'Camera zooms out in multiplayer only if players are far apart horizontally.'),
            (1, 'Y Tracking Only',            'Camera only moves vertically, centered horizontally.'),
            (2, 'Y Expanding Only',           'Camera zooms out in multiplayer if players are far apart vertically.'),
        ]:
            rb = QtWidgets.QRadioButton('%d: %s' % (btnId, name))
            rb.setToolTip('<b>%s:</b><br>%s' % (name, tooltip))
            self.Zone_cammodebuttongroup.addButton(rb, btnId)
            cammodebuttons.append(rb)
            if btnId == cammode: rb.setChecked(True)
            rb.clicked.connect(self.ChangeCamModeList)

        camModeGrid = QtWidgets.QGridLayout()
        camModeGrid.setSpacing(2)
        for i, b in enumerate(cammodebuttons):
            camModeGrid.addWidget(b, i % 4, i // 4)

        self.Zone_screenheights = QtWidgets.QComboBox()
        self.Zone_screenheights.setToolTip(
            "<b>Screen Heights:</b><br>Screen heights (in blocks) the camera can use during multiplayer. "
            "Only the smallest height is used in single-player.<br>"
            "* or ** = glitchy when zone bounds are 0; ** = also unplayably glitchy in multiplayer.")
        self.ChangeCamModeList()
        self.Zone_screenheights.setCurrentIndex(camzoom)

        directionmodeValues = ('Right and Down', 'Right and Up', 'Left and Down', 'Left and Up', 'Down and Right', 'Down and Left', 'Up and Right', 'Up and Left', 'Right and Right')
        self.Zone_directionmode = QtWidgets.QComboBox()
        self.Zone_directionmode.addItems(directionmodeValues)
        self.Zone_directionmode.setToolTip("<b>Camera Tracking:</b><br>This setting makes changes to camera tracking during multiplayer mode.<br>It prioritizes these directions when players goes in the wrong direction.<br>For example if you are making a tower level where the primary objective is going up<br>and you don't want the screen going back down if just one player falls,<br>then set the tracking to any value containing 'Up' and that will prevent that from happening.<br>The order of the directions is unique. Priority is most given to the first direction and the second direction is less strict.")
        self.Zone_directionmode.setCurrentIndex(z.camtrack if z.camtrack < 9 else 0)

        self.Zone_camunk1 = QtWidgets.QSpinBox()
        self.Zone_camunk1.setRange(0, 255)
        self.Zone_camunk1.setToolTip("It is unknown what this value does.")
        self.Zone_camunk1.setValue(z.unk1)

        self.Zone_camunk2 = QtWidgets.QSpinBox()
        self.Zone_camunk2.setRange(0, 255)
        self.Zone_camunk2.setToolTip("Value looks to be unused in the game code.")
        self.Zone_camunk2.setValue(z.unk2)

        self.Zone_camunk3 = QtWidgets.QSpinBox()
        self.Zone_camunk3.setRange(0, 255)
        self.Zone_camunk3.setToolTip("Used as \"Progress Path ID\" in NSMB2.")
        self.Zone_camunk3.setValue(z.unk3)

        # Zone settings checkboxes (8 flags)
        self.Zone_settings = []
        settingsNames = ('Start Zoom as Screen Height:<br>(No initial zoom out/in)', 'Center Camera X-pos On Load:', 'Camera Follows on Y-axis:', 'Camera Stops At Zone End:', 'Unused 1:', 'Toad House Related 1:', 'Unused 2:', 'Toad House Related 2:')
        flagsLeft  = QtWidgets.QFormLayout()
        flagsRight = QtWidgets.QFormLayout()
        for i in range(8):
            cb = QtWidgets.QCheckBox()
            cb.setChecked(bool(z.type & (1 << i)))
            cb.setStyleSheet("margin-left:100%;")
            self.Zone_settings.append(cb)
            (flagsLeft if i < 4 else flagsRight).addRow(settingsNames[i], cb)

        flagsRow = QtWidgets.QHBoxLayout()
        flagsRow.addLayout(flagsLeft)
        flagsRow.addStretch()
        flagsRow.addLayout(flagsRight)

        # Camera form
        camForm = QtWidgets.QFormLayout()
        camForm.addRow('Camera Mode:', camModeGrid)
        camForm.addRow('Screen Heights:', self.Zone_screenheights)
        camForm.addRow('Camera Tracking:', self.Zone_directionmode)

        # Lighting row
        lightRow = QtWidgets.QHBoxLayout()
        lightRow.addWidget(self.Zone_vspotlight)
        lightRow.addWidget(self.Zone_vfulldark)
        lightRow.addStretch()

        visForm = QtWidgets.QFormLayout()
        visForm.addRow('Lighting:', lightRow)
        visForm.addRow('Visibility Effect:', self.Zone_visibility)

        # Unknowns
        unkForm = QtWidgets.QFormLayout()
        unkForm.addRow('Unknown 1:', self.Zone_camunk1)
        unkForm.addRow('Unknown 2:', self.Zone_camunk2)
        unkForm.addRow('Unknown 3:', self.Zone_camunk3)

        w = QtWidgets.QWidget()
        L = QtWidgets.QVBoxLayout(w)
        L.setContentsMargins(8, 8, 8, 8)
        L.setSpacing(6)
        L.addLayout(camForm)
        L.addWidget(createHorzLine())
        L.addLayout(visForm)
        L.addWidget(createHorzLine())
        L.addLayout(unkForm)
        L.addWidget(createHorzLine())
        L.addLayout(flagsRow)
        L.addStretch()
        return w

    def ChangeVisibilityList(self):
        SelectedIndex = self.zv & 0x0F
        self.Zone_visibility.clear()

        if not self.Zone_vspotlight.isChecked() and not self.Zone_vfulldark.isChecked():
            self.Zone_visibility.addItem('Hidden')
            self.Zone_visibility.setToolTip('<b>Visibility:</b><br>Hidden - Mario is hidden when moving behind objects on Layer 0.<br><br>Note: Entities behind layer 0 other than Mario are never visible.')
            SelectedIndex = 0
        elif self.Zone_vspotlight.isChecked() and self.Zone_vfulldark.isChecked():
            self.Zone_visibility.addItem('Small / Small Focus Light')
            self.Zone_visibility.setToolTip('<b>Visibility:</b><br>Small - A small, centered spotlight affords visibility through layer 0.<br>Small Focuslight - A small spotlight which changes size based on player movement.')
            SelectedIndex = 0
        elif self.Zone_vspotlight.isChecked():
            self.Zone_visibility.addItems(('Small', 'Large', 'Full Screen'))
            self.Zone_visibility.setToolTip('<b>Visibility:</b><br>Small - A small, centered spotlight affords visibility through layer 0.<br>Large - A large, centered spotlight affords visibility through layer 0<br>Full Screen - the entire screen is revealed whenever Mario walks behind layer 0')
            if SelectedIndex > 2: SelectedIndex = 0
        elif self.Zone_vfulldark.isChecked():
            self.Zone_visibility.addItems(('Large Foglight', 'Lightbeam', 'Large Focus Light', 'Small Foglight', 'Small Focus Light', 'Absolute Black'))
            self.Zone_visibility.setToolTip('<b>Visibility:</b><br>Large Foglight - A large, organic lightsource surrounds Mario<br>Lightbeam - Mario is able to aim a conical lightbeam through use of the Wiimote<br>Large Focus Light - A large spotlight which changes size based upon player movement<br>Small Foglight - A small, organic lightsource surrounds Mario<br>Small Focuslight - A small spotlight which changes size based on player movement<br>Absolute Black - Visibility is provided only by fireballs, stars, and certain actors')
            if SelectedIndex > 5: SelectedIndex = 5

        self.Zone_visibility.setCurrentIndex(SelectedIndex)

    def ChangeCamModeList(self):
        mode = self.Zone_cammodebuttongroup.checkedId()
        oldListChoice = [1, 1, 2, 3, 3, 3, 1, 1][self.zm] if self.zm != -1 else -1
        newListChoice = [1, 1, 2, 3, 3, 3, 1, 1][mode]

        if self.zm == -1 or oldListChoice != newListChoice:
            if newListChoice == 1:
                heights = [
                    ([14, 19  ],       ''), ([14, 19, 24],    ''), ([14, 19, 28],    ''),
                    ([20, 24  ],       ''), ([19, 24, 28],    ''), ([17, 24  ],      ''),
                    ([17, 24, 28],     ''), ([17, 20  ],      ''), ([ 7, 11, 28],    '**'),
                    ([17, 20.5, 24],   ''), ([17, 20, 28],    ''), ([20,  0,  0],    ''),
                ]
            elif newListChoice == 2:
                heights = [
                    ([14, 19  ],       ''), ([14, 19, 24],    ''), ([14, 19, 28],    ''),
                    ([19, 19, 24],     ''), ([19, 24, 28],    ''), ([19, 24, 28],    ''),
                    ([17, 24, 28],     ''), ([17, 20.5, 24],  ''), ([17,  0,  0],    ''),
                ]
            else:
                heights = [
                    ([14  ], ''), ([19  ], ''), ([24  ], ''), ([28  ], ''),
                    ([17  ], ''), ([20  ], ''), ([16  ], ''), ([28  ], ''),
                    ([ 7  ], '*'), ([10.5], '*'),
                ]

            items = ['%d: ' % i + ' -> '.join('%s blocks' % o for o in opts) + ast
                     for i, (opts, ast) in enumerate(heights)]
            self.Zone_screenheights.clear()
            self.Zone_screenheights.addItems(items)
            self.Zone_screenheights.setCurrentIndex(0)
            self.zm = mode

    # ── Bounds ──────────────────────────────────────────────────────────────

    def _buildBounds(self, z):
        self.Zone_yboundup = QtWidgets.QSpinBox()
        self.Zone_yboundup.setRange(-32688, 32847)
        self.Zone_yboundup.setToolTip('<b>Upper Bounds:</b><br>Controls the maximum distance magnitude the player can be at from the top edge of the screen to move the camera upwards. One block = 16 units.<br><br>Values "0" and less (negative values) make scrolling upwards impossible.<br>Higher positive values mean it is easier to scroll upwards.<br>Lower positive values mean it is harder to scroll upwards.<br><br>Very high values (larger than the screen height) with a low positive "Lower Bounds" value cause instant death.')
        self.Zone_yboundup.setValue(80 + z.yupperbound)

        self.Zone_ybounddown = QtWidgets.QSpinBox()
        self.Zone_ybounddown.setRange(-32695, 32840)
        self.Zone_ybounddown.setToolTip('<b>Lower Bounds:</b><br>Controls the maximum distance magnitude the player can be at from the bottom edge of the screen to move the camera downwards. One block = 16 units.<br><br>Values "0" and less (negative values) do NOT make scrolling downwards impossible.<br>Higher positive values mean it is easier to scroll downwards.<br>Lower positive values mean it is harder to scroll downwards.<br><br>Very high values (larger than the screen height) with a low positive "Upper Bounds" value make scrolling upwards impossible.')
        self.Zone_ybounddown.setValue(72 - z.ylowerbound)

        self.Zone_yboundup2 = QtWidgets.QSpinBox()
        self.Zone_yboundup2.setRange(-32680, 32855)
        self.Zone_yboundup2.setToolTip('<b>Lakitu Upper Bounds:</b><br>Used instead of Upper Bounds when at least one player is riding a Lakitu cloud.')
        self.Zone_yboundup2.setValue(88 + z.yupperbound2)

        self.Zone_ybounddown2 = QtWidgets.QSpinBox()
        self.Zone_ybounddown2.setRange(-32679, 32856)
        self.Zone_ybounddown2.setToolTip('<b>Lakitu Lower Bounds:</b><br>Used instead of Lower Bounds when at least one player is riding a Lakitu cloud.')
        self.Zone_ybounddown2.setValue(88 - z.ylowerbound2)

        self.Zone_yboundup3 = QtWidgets.QSpinBox()
        self.Zone_yboundup3.setRange(-32768, 32767)
        self.Zone_yboundup3.setToolTip(
            '<b>Multiplayer Upper Bounds Adjust:</b><br>Added to the upper bounds value during '
            'multiplayer and after an Auto-Scroll Controller finishes its path.')
        self.Zone_yboundup3.setValue(z.yupperbound3)

        self.Zone_ybounddown3 = QtWidgets.QSpinBox()
        self.Zone_ybounddown3.setRange(-32767, 32768)
        self.Zone_ybounddown3.setToolTip(
            '<b>Multiplayer Lower Bounds Adjust:</b><br>Added to the lower bounds value during '
            'multiplayer and after an Auto-Scroll Controller finishes its path.')
        self.Zone_ybounddown3.setValue(-z.ylowerbound3)

        self.Zone_boundflg = QtWidgets.QCheckBox()
        self.Zone_boundflg.setToolTip('<b>Enable Upward Scrolling:</b><br>If not checked and "Multiplayer Screen Height Adjust" is set to value "0", the screen won\'t scroll upwards unless the player uses a Propeller Suit or Block. Always checked in the retail game.')
        self.Zone_boundflg.setChecked(z.mpcamzoomadjust == 0xF)
        self.Zone_boundflg.stateChanged.connect(
            lambda: self.Zone_mpzoomadjust.setEnabled(not self.Zone_boundflg.isChecked()))

        self.Zone_mpzoomadjust = QtWidgets.QSpinBox()
        self.Zone_mpzoomadjust.setRange(0, 14)
        self.Zone_mpzoomadjust.setToolTip(
            '<b>Multiplayer Screen Height Adjust:</b><br>Increases screen height during multiplayer. '
            'Requires "Enable Upward Scrolling" to be unchecked.')
        self.Zone_mpzoomadjust.setEnabled(not self.Zone_boundflg.isChecked())
        if z.mpcamzoomadjust < 0xF:
            self.Zone_mpzoomadjust.setValue(z.mpcamzoomadjust)

        LA = QtWidgets.QFormLayout()
        LA.addRow('Upper Bounds:', self.Zone_yboundup)
        LA.addRow('Lower Bounds:', self.Zone_ybounddown)
        LA.addRow('Enable Upward Scrolling:', self.Zone_boundflg)
        LA.addRow('MP Screen Height Adjust:', self.Zone_mpzoomadjust)

        LB = QtWidgets.QFormLayout()
        LB.addRow('Lakitu Upper Bounds:', self.Zone_yboundup2)
        LB.addRow('Lakitu Lower Bounds:', self.Zone_ybounddown2)
        LB.addRow('MP Upper Bounds Adjust:', self.Zone_yboundup3)
        LB.addRow('MP Lower Bounds Adjust:', self.Zone_ybounddown3)

        cols = QtWidgets.QHBoxLayout()
        cols.addLayout(LA)
        cols.addSpacing(12)
        cols.addLayout(LB)

        w = QtWidgets.QWidget()
        L = QtWidgets.QVBoxLayout(w)
        L.setContentsMargins(8, 8, 8, 8)
        L.addLayout(cols)
        L.addStretch()
        return w

    # ── Audio ────────────────────────────────────────────────────────────────

    def _buildAudio(self, z):
        from . import gamedefs

        isCustom = bool(getattr(z, 'customMusicName', ''))

        # Page 0: numeric ID selection
        self.Zone_music = QtWidgets.QComboBox()
        self.Zone_music.setToolTip('<b>Background Music:</b><br>Changes the background music')

        for a, b in gamedefs.getMusic():
            self.Zone_music.addItem(b, a)
        del gamedefs

        self.Zone_music.setCurrentIndex(self.Zone_music.findData(z.music))
        self.Zone_music.currentIndexChanged.connect(self.handleMusicListSelect)

        self.Zone_musicid = QtWidgets.QSpinBox()
        self.Zone_musicid.setToolTip('<b>Background Music ID:</b><br>This advanced option allows custom music tracks to be loaded if the proper ASM hacks are in place.')
        self.Zone_musicid.setMaximum(255)
        self.Zone_musicid.setValue(z.music)
        self.Zone_musicid.valueChanged.connect(self.handleMusicIDChange)

        idForm = QtWidgets.QFormLayout()
        idForm.setContentsMargins(0, 0, 0, 0)
        idForm.addRow('Background Music:', self.Zone_music)
        idForm.addRow('Background Music ID:', self.Zone_musicid)
        idPage = QtWidgets.QWidget()
        idPage.setLayout(idForm)

        # Page 1: custom track name input
        self.Zone_musicname = QtWidgets.QLineEdit(z.customMusicName)
        self.Zone_musicname.setPlaceholderText('track name')
        nameForm = QtWidgets.QFormLayout()
        nameForm.setContentsMargins(0, 0, 0, 0)
        nameForm.addRow('Track Name:', self.Zone_musicname)
        namePage = QtWidgets.QWidget()
        namePage.setLayout(nameForm)

        self._musicStack = QtWidgets.QStackedWidget()
        self._musicStack.addWidget(idPage)
        self._musicStack.addWidget(namePage)

        self.Zone_custommusic = QtWidgets.QCheckBox('Use custom track name (RedCore)')
        self.Zone_custommusic.setToolTip('<b>Does not work in Vanilla</b>, requires RedCore.')
        self.Zone_custommusic.setChecked(isCustom)
        self.Zone_custommusic.stateChanged.connect(self._updateMusicMode)

        self.Zone_sfx = QtWidgets.QComboBox()
        self.Zone_sfx.setToolTip('<b>Sound Modulation:</b><br>Changes the sound effect modulation')
        self.Zone_sfx.addItems(('Normal', 'Wall Echo', 'Room Echo', 'Double Echo', 'Cave Echo', 'Underwater Echo', 'Triple Echo', 'High Pitch Echo', 'Tinny Echo', 'Flat', 'Dull', 'Hollow Echo', 'Rich', 'Triple Underwater', 'Ring Echo'))
        self.Zone_sfx.setCurrentIndex(z.sfxmod >> 4)

        self.Zone_boss = QtWidgets.QCheckBox()
        self.Zone_boss.setToolTip('<b>Boss Flag:</b><br>Set for bosses to allow proper music switching by actors')
        self.Zone_boss.setChecked(bool(z.sfxmod & 0x0F))

        audioForm = QtWidgets.QFormLayout()
        audioForm.addRow(self.Zone_custommusic)
        audioForm.addRow(self._musicStack)
        audioForm.addRow('Sound Modulation:', self.Zone_sfx)
        audioForm.addRow('Boss Flag:', self.Zone_boss)

        w = QtWidgets.QWidget()
        L = QtWidgets.QVBoxLayout(w)
        L.setContentsMargins(8, 8, 8, 8)
        L.addLayout(audioForm)
        L.addStretch()

        self._updateMusicMode()
        return w

    def _updateMusicMode(self):
        """Swap between numeric music ID selection and custom track name input."""
        custom = self.Zone_custommusic.isChecked()
        if custom and not self.Zone_musicname.text():
            # Prefill with the currently selected preset song's name
            name = self.Zone_music.currentText()
            if name:
                self.Zone_musicname.setText(name)
        self._musicStack.setCurrentIndex(1 if custom else 0)

    def handleMusicListSelect(self):
        if self.AutoEditMusic: return
        musicId = int(str(self.Zone_music.itemData(self.Zone_music.currentIndex())))
        self.AutoEditMusic = True
        self.Zone_musicid.setValue(musicId)
        self.AutoEditMusic = False

    def handleMusicIDChange(self):
        if self.AutoEditMusic: return
        self.AutoEditMusic = True
        self.Zone_music.setCurrentIndex(self.Zone_music.findData(self.Zone_musicid.value()))
        self.AutoEditMusic = False

    # ── Dirty tracking ───────────────────────────────────────────────────────

    def connectChanges(self, cb):
        for w in (self.Zone_xpos, self.Zone_ypos, self.Zone_width, self.Zone_height,
                  self.Zone_camunk1, self.Zone_camunk2, self.Zone_camunk3,
                  self.Zone_mpzoomadjust, self.Zone_musicid,
                  self.Zone_yboundup, self.Zone_ybounddown,
                  self.Zone_yboundup2, self.Zone_ybounddown2,
                  self.Zone_yboundup3, self.Zone_ybounddown3):
            w.valueChanged.connect(cb)
        for w in (self.Zone_visibility, self.Zone_screenheights,
                  self.Zone_directionmode, self.Zone_sfx, self.Zone_presets):
            w.currentIndexChanged.connect(cb)
        for w in (self.Zone_vspotlight, self.Zone_vfulldark,
                  self.Zone_boundflg, self.Zone_boss, self.Zone_custommusic):
            w.stateChanged.connect(cb)
        self.Zone_musicname.textChanged.connect(cb)
        for rb in self.Zone_cammodebuttongroup.buttons():
            rb.toggled.connect(cb)
        for cb_flag in self.Zone_settings:
            cb_flag.stateChanged.connect(cb)


class BGTab(QtWidgets.QWidget):
    def __init__(self, background):
        super().__init__()

        fname = bytes_to_string(background[4])

        # Determine if the stored name is a known preset or a custom one.
        # BGName.getTransAll() returns all translated preset names plus "Custom filename..."
        # at the end. BGName.index(name) returns that last index when the name is unknown.
        all_names   = BGName.getTransAll()
        _custom_str = 'Custom filename...'
        full_idx    = BGName.index(fname)
        is_custom   = full_idx < len(all_names) and all_names[full_idx] == _custom_str

        # Preset dropdown — no "Custom filename..." entry; that's handled by the checkbox.
        preset_names = [n for n in all_names if n != _custom_str]
        self.bgName = QtWidgets.QComboBox()
        self.bgName.addItems(preset_names)
        if not is_custom:
            self.bgName.setCurrentIndex(full_idx)
        self.bgName.activated.connect(self._handlePresetChanged)

        # Custom filename input with dv_ / .szs decorators
        self.bgFname = QtWidgets.QLineEdit()
        self.bgFname.setText(fname)
        self.bgFname.setPlaceholderText('background name')

        self._dvLabel  = QtWidgets.QLabel('dv_')
        self._szsLabel = QtWidgets.QLabel(self.fileSuffix())
        filenameRow = QtWidgets.QHBoxLayout()
        filenameRow.setContentsMargins(0, 0, 0, 0)
        filenameRow.setSpacing(2)
        filenameRow.addWidget(self._dvLabel)
        filenameRow.addWidget(self.bgFname)
        filenameRow.addWidget(self._szsLabel)

        # Checkbox that switches between preset and custom modes
        self.useCustomFname = QtWidgets.QCheckBox('Use custom filename')
        self.useCustomFname.setChecked(is_custom)
        self.useCustomFname.stateChanged.connect(self._updateCustomMode)

        # Page 0: preset dropdown row
        presetPage = QtWidgets.QWidget()
        presetPageLayout = QtWidgets.QHBoxLayout(presetPage)
        presetPageLayout.setContentsMargins(0, 0, 0, 0)
        presetPageLayout.addWidget(QtWidgets.QLabel('Background:'))
        presetPageLayout.addWidget(self.bgName)

        # Page 1: custom filename row
        filePage = QtWidgets.QWidget()
        filePageLayout = QtWidgets.QHBoxLayout(filePage)
        filePageLayout.setContentsMargins(0, 0, 0, 0)
        filePageLayout.setSpacing(0)
        filePageLayout.addWidget(QtWidgets.QLabel('Filename:'))
        filePageLayout.addSpacing(8)
        filePageLayout.addWidget(self._dvLabel)
        filePageLayout.addWidget(self.bgFname)
        filePageLayout.addWidget(self._szsLabel)

        # Stack — index 0 = preset, index 1 = custom
        self._nameStack = QtWidgets.QStackedWidget()
        self._nameStack.addWidget(presetPage)
        self._nameStack.addWidget(filePage)

        # Offset / parallax controls
        self.xPos = QtWidgets.QSpinBox()
        self.xPos.setRange(-32768, 32767)
        self.xPos.setToolTip("X offset applied to the background center. No longer valid in the original game.")
        self.xPos.setValue(background[1])

        self.yPos = QtWidgets.QSpinBox()
        self.yPos.setRange(-32768, 32767)
        self.yPos.setToolTip("Y offset applied to the background center. No longer valid in the original game.")
        self.yPos.setValue(background[2])

        self.zPos = QtWidgets.QSpinBox()
        self.zPos.setRange(-32768, 32767)
        self.zPos.setToolTip("Z offset applied to the background center. No longer valid in the original game.")
        self.zPos.setValue(background[3])

        # The stored value is a 16-bit number, but only 0-4 have a name. Levels (Deluxe
        # ones in particular) can hold other values; keep those instead of leaving the box
        # blank, because a blank box reads back as -1 and can't be saved.
        self._storedParallax = background[5]
        self.parallaxMode = QtWidgets.QComboBox()
        for value, text in enumerate((
            "Y Offset Off, All Parallax On",
            "Y Offset On, All Parallax On",
            "Y Offset On, All Parallax Off",
            "Y Offset On, Y Parallax Off",
            "Y Offset On, X Parallax Off",
        )):
            self.parallaxMode.addItem(text, value)
        if not 0 <= self._storedParallax <= 4:
            self.parallaxMode.addItem('Unknown (%d)' % self._storedParallax, self._storedParallax)
        self.parallaxMode.setToolTip("Parallax Mode from NSMB2. No longer valid in the original game.")
        self.parallaxMode.setCurrentIndex(self.parallaxMode.findData(self._storedParallax))

        self.preview = QtWidgets.QLabel()
        self.preview.setAlignment(Qt.AlignCenter)

        self._filenameLabel = QtWidgets.QLabel()
        self._filenameLabel.setAlignment(Qt.AlignCenter)
        self._filenameLabel.setStyleSheet('font-size: 10px;')

        settingsForm = QtWidgets.QFormLayout()
        settingsForm.setContentsMargins(0, 0, 0, 0)
        settingsForm.addRow('X Offset:',      self.xPos)
        settingsForm.addRow('Y Offset:',      self.yPos)
        settingsForm.addRow('Z Offset:',      self.zPos)
        settingsForm.addRow('Parallax Mode:', self.parallaxMode)

        mainLayout = QtWidgets.QVBoxLayout(self)
        mainLayout.setContentsMargins(8, 8, 8, 8)
        mainLayout.setSpacing(6)
        mainLayout.addWidget(self.preview)
        mainLayout.addWidget(self._filenameLabel)
        mainLayout.addWidget(self.useCustomFname)
        mainLayout.addWidget(self._nameStack)
        mainLayout.addWidget(createHorzLine())
        mainLayout.addLayout(settingsForm)
        mainLayout.addStretch()

        self.bgFname.textChanged.connect(self.updatePreview)
        self._updateCustomMode()
        self.updatePreview()

    def _updateCustomMode(self):
        """Swap the visible row between preset dropdown and custom filename input."""
        custom = self.useCustomFname.isChecked()
        self._nameStack.setCurrentIndex(1 if custom else 0)
        if not custom:
            self.bgFname.setText(BGName.getNameForTrans(self.bgName.currentText()))
        self.updatePreview()

    def parallaxValue(self):
        """The parallax mode to store (never negative, whatever the box shows)."""
        value = self.parallaxMode.currentData()
        return self._storedParallax if value is None else int(value)

    def connectChanges(self, cb):
        self.bgName.activated.connect(cb)
        self.bgFname.textChanged.connect(cb)
        self.useCustomFname.stateChanged.connect(cb)
        for w in (self.xPos, self.yPos, self.zPos):
            w.valueChanged.connect(cb)
        self.parallaxMode.currentIndexChanged.connect(cb)

    def _handlePresetChanged(self):
        if not self.useCustomFname.isChecked():
            self.bgFname.setText(BGName.getNameForTrans(self.bgName.currentText()))
        self.updatePreview()

    def updatePreview(self):
        if self.useCustomFname.isChecked():
            folders = globals.gamedef.recursiveFiles('bg', False, True)
            filename = None
            for folder in folders:
                candidate = os.path.join(folder, 'no_preview.png')
                if os.path.isfile(candidate):
                    filename = candidate
                    break
            if filename is None:
                filename = os.path.join(globals.miyamoto_path, 'yaz0data', 'bg', 'no_preview.png')
        else:
            folders = globals.gamedef.recursiveFiles('bg', False, True)
            for folder in folders:
                filename = os.path.join(folder, self.bgName.currentText() + '.png')
                if os.path.isfile(filename):
                    break
            else:
                folders = globals.gamedef.recursiveFiles('bg', False, True)
                filename = None
                for folder in folders:
                    candidate = os.path.join(folder, 'no_preview.png')
                    if os.path.isfile(candidate):
                        filename = candidate
                        break
                if filename is None:
                    filename = os.path.join(globals.miyamoto_path, 'yaz0data', 'bg', 'no_preview.png')

        pix = QtGui.QPixmap(filename)
        self.preview.setPixmap(pix)

        name = self.bgFname.text()
        self._filenameLabel.setText(self.fileNameFor(name) if name else '')
        self._filenameLabel.setToolTip(
            ('Located in: ' + self.fileFolder()) if name else '')

    # The background model is looked up by name, but the file name and folder differ per game
    @staticmethod
    def fileSuffix():
        return '.Nin_NX_NVN.szs' if globals.IsNSMBUDX else '.szs'

    @staticmethod
    def fileFolder():
        return 'romfs/Model' if globals.IsNSMBUDX else 'content/Common/distant_view'

    @classmethod
    def fileNameFor(cls, name):
        return 'dv_%s%s' % (name, cls.fileSuffix())


class ScreenCapChoiceDialog(QtWidgets.QDialog):
    """
    Dialog which lets you choose which zone to take a pic of
    """

    def __init__(self):
        """
        Creates and initializes the dialog
        """
        super().__init__()
        self.setWindowTitle('Choose a Screenshot source')
        self.setWindowIcon(GetIcon('screenshot'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.zoneCombo = QtWidgets.QComboBox()
        self.zoneCombo.addItem('Current Screen')

        zonecount = len(globals.Area.zones)
        if zonecount:
            self.zoneCombo.addItem('All Zones')
            for i in range(zonecount):
                self.zoneCombo.addItem('Zone [zone]'.replace('[zone]', str(i + 1)))

        self.hideBackground = QtWidgets.QCheckBox()
        self.hideBackground.setChecked(True)

        self.saveImage = QtWidgets.QCheckBox()
        self.saveImage.setChecked(True)
        self.saveImage.stateChanged.connect(self.saveImageChanged)

        self.saveClip = QtWidgets.QCheckBox()
        self.saveClip.stateChanged.connect(self.saveClipChanged)

        buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

        mainLayout = QtWidgets.QFormLayout()
        mainLayout.setLabelAlignment(QtCore.Qt.AlignRight)
        mainLayout.addRow("Target:", self.zoneCombo)
        mainLayout.addRow("Hide background:", self.hideBackground)
        mainLayout.addRow(createHorzLine())
        mainLayout.addRow("Save image to file:", self.saveImage)
        mainLayout.addRow("Copy image to clipboard:", self.saveClip)
        mainLayout.addRow(buttonBox)
        self.setLayout(mainLayout)

    def saveImageChanged(self, checked):
        if not (checked or self.saveClip.isChecked()):
            self.saveClip.setChecked(True)

    def saveClipChanged(self, checked):
        if not (checked or self.saveImage.isChecked()):
            self.saveImage.setChecked(True)


class AutoSavedInfoDialog(QtWidgets.QDialog):
    """
    Dialog which lets you know that an auto saved level exists
    """

    def __init__(self, filename):
        """
        Creates and initializes the dialog
        """
        super().__init__()
        self.setWindowTitle('Auto-saved backup found')
        self.setWindowIcon(GetIcon('save'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        mainlayout = QtWidgets.QVBoxLayout(self)

        hlayout = QtWidgets.QHBoxLayout()

        icon = QtWidgets.QLabel()
        hlayout.addWidget(icon)

        label = QtWidgets.QLabel("Yaz0moto has found some level data which wasn't saved - possibly due to a crash within the editor or by your computer. Do you want to restore this level?<br><br>If you pick No, the autosaved level data will be deleted and will no longer be accessible.<br><br>Original file path: [path]".replace('[path]', str(filename)))
        label.setWordWrap(True)
        hlayout.addWidget(label)
        hlayout.setStretch(1, 1)

        buttonbox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.No | QtWidgets.QDialogButtonBox.Yes)
        buttonbox.accepted.connect(self.accept)
        buttonbox.rejected.connect(self.reject)

        mainlayout.addLayout(hlayout)
        mainlayout.addWidget(buttonbox)


class AreaChoiceDialog(QtWidgets.QDialog):
    """
    Dialog which lets you choose an area
    """

    def __init__(self, areacount):
        """
        Creates and initializes the dialog
        """
        super().__init__()
        self.setWindowTitle('Choose an Area')
        self.setWindowIcon(GetIcon('areas'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.areaCombo = QtWidgets.QComboBox()
        for i in range(areacount):
            self.areaCombo.addItem('Area [num]'.replace('[num]', str(i + 1)))

        buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)

        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

        mainLayout = QtWidgets.QVBoxLayout()
        mainLayout.addWidget(self.areaCombo)
        mainLayout.addWidget(buttonBox)
        self.setLayout(mainLayout)


# ── Download/Update worker threads ──────────────────────────────────────────

class _DownloadModWorker(QThread):
    progress = pyqtSignal(int)      # 0-100; -1 = extracting
    statusMsg = pyqtSignal(str)
    completed = pyqtSignal(bool, str)  # success, error_message

    def __init__(self, url, tmp_path, extract_dir):
        super().__init__()
        self.url = url
        self.tmp_path = tmp_path
        self.extract_dir = extract_dir
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            self.statusMsg.emit("Connecting\u2026")
            with requests.get(self.url, stream=True, timeout=30) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get('Content-Length', 0))
                done = 0
                self.statusMsg.emit("Downloading\u2026")
                with open(self.tmp_path, 'wb') as f:
                    for chunk in resp.iter_content(65536):
                        if self._cancel:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if total:
                            self.progress.emit(int(done * 100 / total))
            if self._cancel:
                _safe_remove(self.tmp_path)
                self.completed.emit(False, "Cancelled")
                return
            self.statusMsg.emit("Extracting\u2026")
            self.progress.emit(-1)
            os.makedirs(self.extract_dir, exist_ok=True)
            with zipfile.ZipFile(self.tmp_path, 'r') as zf:
                zf.extractall(self.extract_dir)
            _safe_remove(self.tmp_path)
            self.completed.emit(True, "")
        except Exception as e:
            _safe_remove(self.tmp_path)
            self.completed.emit(False, str(e))


class _CheckUpdateWorker(QThread):
    completed = pyqtSignal(object)  # dict or None

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            # Parse GitHub repo from URL
            m = re.match(r'https?://github\.com/([^/]+)/([^/]+)', self.url)
            if not m:
                self.completed.emit(None)
                return
            owner, repo = m.group(1), m.group(2).rstrip('/').replace('.git', '')
            api = f'https://api.github.com/repos/{owner}/{repo}/releases/latest'
            resp = requests.get(api, timeout=10)
            if resp.status_code != 200:
                self.completed.emit(None)
                return
            data = resp.json()
            tag = data.get('tag_name', '')
            # Find patch.zip asset
            download_url = None
            for asset in data.get('assets', []):
                if asset['name'] == 'patch.zip':
                    download_url = asset['browser_download_url']
                    break
            self.completed.emit({
                'version': tag.lstrip('v'),
                'tag': tag,
                'download_url': download_url,
                'name': data.get('name', ''),
            })
        except Exception:
            self.completed.emit(None)


def _safe_remove(path):
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def _start_background_worker(owner, worker):
    """Start a QThread and retain it until Qt reports that it has stopped."""
    workers = getattr(owner, '_background_workers', None)
    if workers is None:
        workers = set()
        owner._background_workers = workers

    workers.add(worker)
    worker_ref = weakref.ref(worker)

    def _release_worker():
        finished_worker = worker_ref()
        if finished_worker is not None:
            workers.discard(finished_worker)

    worker.finished.connect(_release_worker)
    worker.start()


# ── Helpers for GitHub URL resolution ───────────────────────────────────────

def _resolve_github_url(url):
    """Resolve a GitHub URL to (download_url, name, version) or None.
    Tries releases first, then repo archive."""
    m = re.match(r'https?://github\.com/([^/]+)/([^/]+)', url)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2).rstrip('/').replace('.git', '')
    # Try latest release
    try:
        api = f'https://api.github.com/repos/{owner}/{repo}/releases/latest'
        resp = requests.get(api, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            tag = data.get('tag_name', '').lstrip('v')
            for asset in data.get('assets', []):
                if asset['name'] == 'patch.zip':
                    return {
                        'download_url': asset['browser_download_url'],
                        'name': data.get('name', repo),
                        'version': tag,
                    }
    except Exception:
        pass
    # Fallback to repo archive (main branch)
    return {
        'download_url': f'https://github.com/{owner}/{repo}/archive/refs/heads/main.zip',
        'name': repo,
        'version': '0.0',
    }


def _find_main_xml_in_extracted(extract_dir):
    """Walk extract_dir to find a main.xml, return (root_dir, main_xml_dir)."""
    for root, dirs, files in os.walk(extract_dir):
        if 'main.xml' in files:
            return root
    return None


def _patch_slug_from_url(url, fallback='mod'):
    """Build a stable install-folder slug from a patch URL."""
    parsed = urlparse(url)
    path_parts = [unquote(part) for part in parsed.path.split('/') if part]

    if parsed.netloc.lower() in ('github.com', 'www.github.com') and len(path_parts) >= 2:
        owner = path_parts[0]
        repo = path_parts[1]
        if repo.lower().endswith('.git'):
            repo = repo[:-4]
        name = f'{owner}_{repo}'
    elif path_parts:
        name = path_parts[-1]
        if name.lower().endswith('.zip'):
            name = name[:-4]
    else:
        name = fallback

    if not name:
        name = fallback
    return re.sub(r'[^\w\-]', '_', name).strip('_') or 'mod'


class PreferencesDialog(QtWidgets.QDialog):
    """
    Dialog which lets you customize Miyamoto
    """

    def __init__(self):
        """
        Creates and initializes the dialog
        """
        super().__init__()
        self.setWindowTitle('Yaz0moto Preferences')
        self.setWindowIcon(GetIcon('settings'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # Create the tab widget
        self.tabWidget = QtWidgets.QTabWidget()
        self.tabWidget.currentChanged.connect(self.tabChanged)

        # Create tabs
        self.infoLabel = QtWidgets.QLabel()
        self.generalTab = self.getGeneralTab()   # merged General + Editor + Tilesets
        self._initial_showActorNotes = self.generalTab.showActorNotes.isChecked()
        self._initial_showInfoIcons = self.generalTab.showInfoIcons.isChecked()
        self.toolbarTab = self.getToolbarTab()
        self.themesTab = self.getThemesTab(QtWidgets.QWidget)()
        self.resourcesTab = self.getResourcesTab()
        self.gameSetupTab = self.getGameSetupTab()  # merged Games + Mods

        # Backward-compat aliases so app.py attribute access still works
        self.tilesetsTab = self.generalTab
        self.editorTab = self.generalTab
        self.gamesTab = self.gameSetupTab
        self.modsTab = self.gameSetupTab

        self.tabWidget.addTab(self.generalTab, 'General')
        self.tabWidget.addTab(self.gameSetupTab, 'Game Setup')
        self.tabWidget.addTab(self.toolbarTab, 'Toolbar')
        self.tabWidget.addTab(self.themesTab, 'Themes')
        self.tabWidget.addTab(self.resourcesTab, 'Resources')

        # Create the buttonbox
        buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

        # Create a main layout
        mainLayout = QtWidgets.QVBoxLayout()
        mainLayout.addWidget(self.infoLabel)
        mainLayout.addWidget(self.tabWidget)
        mainLayout.addWidget(buttonBox)
        self.setLayout(mainLayout)

        # Update it
        self.tabChanged()

    def needsRestart(self):
        """Returns True if the user changed a setting that requires a restart (theme, toolbar, actor notes, or info icons)."""
        if self.editorTab.showActorNotes.isChecked() != self._initial_showActorNotes:
            return True
        if self.editorTab.showInfoIcons.isChecked() != self._initial_showInfoIcons:
            return True
        if self.themesTab.themeBox.currentText() != self.themesTab._initial_theme:
            return True
        if self.themesTab.NonWinStyle.currentText() != self.themesTab._initial_style:
            return True
        if self.themesTab.uiScale.value() != self.themesTab._initial_ui_scale:
            return True
        initial = self.toolbarTab._initial_toolbar_acts
        for boxList in (self.toolbarTab.FileBoxes, self.toolbarTab.EditBoxes,
                        self.toolbarTab.ViewBoxes, self.toolbarTab.SettingsBoxes,
                        self.toolbarTab.SpritedataBoxes, self.toolbarTab.HelpBoxes):
            for box in boxList:
                if box.isChecked() != initial.get(box.InternalName):
                    return True
        return False

    def tabChanged(self):
        """
        Handles the current tab being changed
        """
        self.infoLabel.setText(self.tabWidget.currentWidget().info)

    def getGeneralTab(self):
        """Returns the General tab — merged General, Editor, and Tilesets sections."""

        class GeneralTab(QtWidgets.QWidget):
            info = '<b>General</b><br>Customize language, file handling, and other general settings.'

            def __init__(self):
                super().__init__()

                vbox = QtWidgets.QVBoxLayout()
                vbox.setSpacing(16)
                vbox.setContentsMargins(4, 4, 4, 4)

                # ── General section ──────────────────────────────────────────
                from .spritelib import RotationFPS
                self.rotationFPS = QtWidgets.QSpinBox()
                self.rotationFPS.setMaximumWidth(256)
                self.rotationFPS.setRange(1, 60)
                self.rotationFPS.setValue(RotationFPS)
                del RotationFPS

                self.openMethod = QtWidgets.QComboBox()
                self.openMethod.addItems(["Always Ask", "Same Window", "New Window"])
                self.openMethod.setCurrentIndex(setting('OpenMethodMode', 0))

                self.launchBehavior = QtWidgets.QComboBox()
                self.launchBehavior.addItems(["Show welcome page", "Open last level"])
                self.launchBehavior.setCurrentIndex(setting('LaunchBehavior', 0))

                self.updateChannel = QtWidgets.QComboBox()
                self.updateChannel.addItems(_CHANNEL_LABELS)
                cur = setting('UpdateChannel', _default_channel())
                idx = _CHANNEL_VALUES.index(cur) if cur in _CHANNEL_VALUES else 0
                self.updateChannel.setCurrentIndex(idx)

                self.checkNowBtn = QtWidgets.QPushButton('Check for updates')
                self.checkNowBtn.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
                self.checkNowBtn.clicked.connect(
                    lambda: check_for_updates_now(
                        _CHANNEL_VALUES[self.updateChannel.currentIndex()]
                    )
                )

                update_row = QtWidgets.QHBoxLayout()
                update_row.setSpacing(8)
                update_row.addWidget(self.updateChannel, 1)
                update_row.addWidget(self.checkNowBtn)

                self.useOuterSarcFormat = QtWidgets.QCheckBox('Use Outer SARC Format')
                self.useOuterSarcFormat.setToolTip(
                    'Allows compatibility with legacy editors. '
                    'When enabled, the level is saved in Miyamoto\'s outer-SARC format '
                    'with a "levelname" file.')
                self.useOuterSarcFormat.setChecked(globals.UseOuterSarcFormat)
                if globals.IsNSMBUDX:
                    # Deluxe levels are always flat archives
                    self.useOuterSarcFormat.setEnabled(False)
                    self.useOuterSarcFormat.setToolTip('Not used by New Super Mario Bros. U Deluxe.')

                if not globals.IsNSMBUDX:
                    self.modifyInnerName = QtWidgets.QCheckBox('Modify Internal Name')
                    self.modifyInnerName.setToolTip(
                        'When enabled, you are prompted for the internal SARC name on save. '
                        'When disabled, the filename (without extension) is used automatically.')
                    self.modifyInnerName.setChecked(globals.ModifyInnerName)
                    self.modifyInnerName.setVisible(globals.UseOuterSarcFormat)
                    self.useOuterSarcFormat.toggled.connect(
                        lambda checked: self.modifyInnerName.setVisible(checked))

                gen_form = QtWidgets.QFormLayout()
                gen_form.addRow('File opening behavior:', self.openMethod)
                gen_form.addRow('Launch behavior:', self.launchBehavior)
                gen_form.addRow(self.useOuterSarcFormat)
                if not globals.IsNSMBUDX:
                    gen_form.addRow(self.modifyInnerName)
                gen_form.addRow('Updates:', update_row)

                gen_lay = QtWidgets.QVBoxLayout()
                gen_lay.addLayout(gen_form)
                gen_group = QtWidgets.QGroupBox('General')
                gen_group.setLayout(gen_lay)
                vbox.addWidget(gen_group)

                # ── Editor section ───────────────────────────────────────────
                self.showActorNotes = QtWidgets.QCheckBox('Show actor notes box')
                self.showActorNotes.setToolTip(
                    'When enabled, actor notes are shown in a text box within the properties panel. '
                    'When disabled, a \"Notes\" button is shown instead which displays notes in a tooltip.')
                self.showActorNotes.setChecked(setting('ShowActorNotes', True))

                self.showInfoIcons = QtWidgets.QCheckBox('Show info icons on sprite data fields')
                self.showInfoIcons.setToolTip(
                    'When enabled, a small info icon is shown next to sprite data field '
                    'labels that have a tooltip comment.')
                self.showInfoIcons.setChecked(setting('ShowInfoIcons', True))

                self.categorizedSpriteData = QtWidgets.QCheckBox('Categorized sprite data')
                self.categorizedSpriteData.setToolTip(
                    'When enabled, actor flags in the sprite data editor are grouped into '
                    'tabbed categories (Behavior, Movement, Events, Uncategorized) for '
                    'easier navigation.')
                self.categorizedSpriteData.setChecked(globals.CategorizedSpriteData)

                self.overwriteActors = QtWidgets.QCheckBox("Don't overwrite actor models in the level archive")
                self.overwriteActors.setToolTip(
                    "When enabled, actors already in the level's archive will not be replaced "
                    'by actors from the game data folder.')
                self.overwriteActors.setChecked(not globals.OverwriteSprite)

                self.placeFullSize = QtWidgets.QCheckBox('Place objects at their full size')
                self.placeFullSize.setToolTip(
                    'When enabled, clicking to place an object in the level canvas places it '
                    'at its full width and height instead of as a 1×1 tile.')
                self.placeFullSize.setChecked(globals.PlaceObjectFullSize)

                self.legacyMouse = QtWidgets.QCheckBox('Legacy mouse controls in the level view (right click places)')
                self.legacyMouse.setToolTip(
                    '<b>Legacy mouse controls</b> (only in the level view; everywhere else left click is used as usual)<br>'
                    'Right click: place the picked part or tool, even over things, dragging to size it<br>'
                    'Right click with nothing picked: deselect what is under the cursor (on empty space, everything)<br>'
                    'Left click: select and drag things; on empty space drag a selection box<br>'
                    'Shift + right click: a thing\'s menu (Settings, Info, Delete...)<br>'
                    'Ctrl + right click: the zone menu. Esc, or clicking the part again, puts it down')
                self.legacyMouse.setChecked(globals.LegacyMouseControls)

                self.spriteListPreview = QtWidgets.QComboBox()
                self.spriteListPreview.addItem('Disabled',       globals.SPRITE_PREVIEW_DISABLED)
                self.spriteListPreview.addItem('Small (24 px)',  globals.SPRITE_PREVIEW_SMALL)
                self.spriteListPreview.addItem('Medium (40 px)', globals.SPRITE_PREVIEW_MEDIUM)
                self.spriteListPreview.addItem('Large (56 px)',  globals.SPRITE_PREVIEW_LARGE)
                cur = globals.SpriteListPreviewSize
                for i in range(self.spriteListPreview.count()):
                    if self.spriteListPreview.itemData(i) == cur:
                        self.spriteListPreview.setCurrentIndex(i)
                        break

                self.spriteListPreviewHighDetail = QtWidgets.QCheckBox('High Detail Mode')
                self.spriteListPreviewHighDetail.setToolTip(
                    'Renders preview thumbnails at the sprite\'s native resolution for '
                    'maximum quality, then scales them down to the chosen preview size.')
                self.spriteListPreviewHighDetail.setChecked(globals.SpriteListPreviewHighDetail)

                preview_row = QtWidgets.QHBoxLayout()
                preview_row.addWidget(QtWidgets.QLabel('Actor list preview size:'))
                preview_row.addWidget(self.spriteListPreview)
                preview_row.addWidget(self.spriteListPreviewHighDetail)
                preview_row.addStretch()

                ed_fps_form = QtWidgets.QFormLayout()
                ed_fps_form.addRow('Pivotal Rotation Preview FPS:', self.rotationFPS)

                ed_lay = QtWidgets.QVBoxLayout()
                ed_lay.addLayout(ed_fps_form)
                ed_lay.addWidget(self.showActorNotes)
                ed_lay.addWidget(self.showInfoIcons)
                ed_lay.addWidget(self.categorizedSpriteData)
                ed_lay.addWidget(self.overwriteActors)
                ed_lay.addWidget(self.placeFullSize)
                ed_lay.addWidget(self.legacyMouse)
                ed_lay.addLayout(preview_row)
                editor_group = QtWidgets.QGroupBox('Editor')
                editor_group.setLayout(ed_lay)
                vbox.addWidget(editor_group)

                # ── Tilesets section ─────────────────────────────────────────
                self.useRGBA8 = QtWidgets.QCheckBox('Use RGBA8 lossless compression')
                self.useRGBA8.setChecked(globals.UseRGBA8)

                self.alwaysRepack = QtWidgets.QCheckBox('Always repack tilesets on level save')
                self.alwaysRepack.setChecked(setting('OverrideTilesetSaving', False))

                self.autoSave = QtWidgets.QCheckBox('Auto-save tilesets')
                self.autoSave.setToolTip('Skips the save confirmation dialog when closing the tileset editor.')
                self.autoSave.setChecked(setting('AutoSaveTilesets', False))

                ts_lay = QtWidgets.QVBoxLayout()
                ts_lay.addWidget(self.useRGBA8)
                ts_lay.addWidget(self.alwaysRepack)
                ts_lay.addWidget(self.autoSave)
                tileset_group = QtWidgets.QGroupBox('Tilesets')
                tileset_group.setLayout(ts_lay)
                vbox.addWidget(tileset_group)

                vbox.addStretch(1)
                self.setLayout(vbox)

        return GeneralTab()

    def getTilesetsTab(self):
        return self.generalTab  # merged into getGeneralTab

    def getEditorTab(self):
        return self.generalTab  # merged into getGeneralTab

    def getToolbarTab(self):
        """
        Returns the Toolbar Tab
        """

        # Action key → icon name mapping (matches app.py CreateAction calls)
        _action_icons = {
            'newlevel': 'new', 'openfromname': 'open', 'openfromfile': 'openfromfile',
            'openrecent': 'recent', 'save': 'save', 'saveas': 'saveas',
            'metainfo': 'info', 'screenshot': 'screenshot', 'preferences': 'settings',
            'exit': 'delete',
            'undo': 'undo', 'redo': 'redo', 'selectall': 'select', 'deselect': 'deselect',
            'cut': 'cut', 'copy': 'copy', 'paste': 'paste', 'duplicate': 'copy',
            'raise': 'raise', 'lower': 'lower', 'shiftitems': 'move',
            'mergelocations': 'merge',
            'freezeobjects': 'objectsfreeze', 'freezesprites': 'spritesfreeze',
            'freezeentrances': 'entrancesfreeze', 'freezelocations': 'locationsfreeze',
            'freezepaths': 'pathsfreeze',
            'showlay0': 'layer0', 'showlay1': 'layer1', 'showlay2': 'layer2',
            'showsprites': 'sprites', 'showspriteimages': 'sprites',
            'showrotation': 'rotation', 'showlocations': 'locations',
            'showpaths': 'paths', 'grid': 'grid',
            'livebg': 'background', 'livebganim': 'livebganim', 'realview': 'realview',
            'previewallmovement': 'animation',
            'zoommax': 'zoommax', 'zoomin': 'zoomin', 'zoomactual': 'zoomactual',
            'zoomout': 'zoomout', 'zoommin': 'zoommin',
            'areaoptions': 'area', 'zones': 'zones',
            'addarea': 'add', 'importarea': 'import', 'deletearea': 'delete',
            'reloaddata': 'reload', 'viewspritemap': 'folderpath',
            'infobox': 'help', 'wiki': 'contents', 'aboutqt': 'qt',
        }

        class ToolbarTab(QtWidgets.QWidget):
            """
            Toolbar Tab
            """
            info = '<b>Toolbar</b><br>Choose which actions appear on the toolbar.'

            def __init__(self):
                """
                Initializes the Toolbar Tab
                """
                super().__init__()

                # Determine which keys are activated
                if setting('ToolbarActs') in (None, 'None', 'none', '', 0):
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

                self._initial_toolbar_acts = dict(toggled)

                # Create some data
                self.FileBoxes = []
                self.EditBoxes = []
                self.ViewBoxes = []
                self.SettingsBoxes = []
                self.SpritedataBoxes = []
                self.HelpBoxes = []
                FL = QtWidgets.QVBoxLayout()
                EL = QtWidgets.QVBoxLayout()
                VL = QtWidgets.QVBoxLayout()
                SL = QtWidgets.QVBoxLayout()
                SDL = QtWidgets.QVBoxLayout()
                HL = QtWidgets.QVBoxLayout()
                FB = QtWidgets.QGroupBox('&File')
                EB = QtWidgets.QGroupBox('&Edit')
                VB = QtWidgets.QGroupBox('&View')
                SB = QtWidgets.QGroupBox('&Area')
                SDB = QtWidgets.QGroupBox('Spritedata')
                HB = QtWidgets.QGroupBox('&Help')

                # Arrange this data so it can be iterated over
                menuItems = (
                    (globals.FileActions, self.FileBoxes, FL, FB),
                    (globals.EditActions, self.EditBoxes, EL, EB),
                    (globals.ViewActions, self.ViewBoxes, VL, VB),
                    (globals.SettingsActions, self.SettingsBoxes, SL, SB),
                    (globals.SpritedataActions, self.SpritedataBoxes, SDL, SDB),
                    (globals.HelpActions, self.HelpBoxes, HL, HB),
                )

                # Set up the menus by iterating over the above data
                for defaults, boxes, layout, group in menuItems:
                    for L, C, I in defaults:
                        box = QtWidgets.QCheckBox(L)
                        icon_name = _action_icons.get(I)
                        if icon_name:
                            box.setIcon(GetIcon(icon_name))
                        boxes.append(box)
                        layout.addWidget(box)
                        # Buttons added after the settings were saved start at their default
                        box.setChecked(toggled.get(I, C))
                        box.InternalName = I  # to save settings later
                    group.setLayout(layout)

                # Create the Reset button
                reset = QtWidgets.QPushButton('Reset')
                reset.clicked.connect(self.reset)

                # Create the main layout
                L = QtWidgets.QGridLayout()
                L.addWidget(reset, 0, 0, 1, 1)
                L.addWidget(FB, 1, 0, 3, 1)
                L.addWidget(EB, 1, 1, 3, 1)
                L.addWidget(VB, 1, 2, 3, 1)
                L.addWidget(SB, 1, 3, 1, 1)
                L.addWidget(SDB, 2, 3, 1, 1)
                L.addWidget(HB, 3, 3, 1, 1)
                self.setLayout(L)

            def reset(self):
                """
                This is called when the Reset button is clicked
                """
                items = (
                    (self.FileBoxes, globals.FileActions),
                    (self.EditBoxes, globals.EditActions),
                    (self.ViewBoxes, globals.ViewActions),
                    (self.SettingsBoxes, globals.SettingsActions),
                    (self.SpritedataBoxes, globals.SpritedataActions),
                    (self.HelpBoxes, globals.HelpActions)
                )

                for boxes, defaults in items:
                    for box, default in zip(boxes, defaults):
                        box.setChecked(default[1])

        return ToolbarTab()

    def getGamesTab(self):
        return self.gameSetupTab  # merged into getGameSetupTab

    def getModsTab(self):
        return self.gameSetupTab  # merged into getGameSetupTab

    def getGameSetupTab(self):
        """Returns the Game Setup tab — game selection + mod management."""
        from . import gamedefs as _gd
        from .verifications import isValidGamePath

        class GameSetupTab(QtWidgets.QWidget):
            info = '<b>Game Setup</b><br>Select your base game, manage mods, and configure game paths.'

            def __init__(self_inner):
                super().__init__()

                vbox = QtWidgets.QVBoxLayout(self_inner)
                vbox.setSpacing(12)
                vbox.setContentsMargins(8, 8, 8, 8)

                # ── Game Paths ───────────────────────────────────────────────
                self_inner._path_edits = {}

                games_group = QtWidgets.QGroupBox('Game Paths')
                games_vbox = QtWidgets.QVBoxLayout(games_group)
                games_vbox.setSpacing(6)

                base_games = _gd.getAvailableBaseGames()
                for idx_g, (def_, folder) in enumerate(base_games):
                    game_lbl = QtWidgets.QLabel(def_.name)
                    game_lbl.setStyleSheet('font-weight: bold;')
                    games_vbox.addWidget(game_lbl)

                    indent_w = QtWidgets.QWidget()
                    indent_lay = QtWidgets.QVBoxLayout(indent_w)
                    indent_lay.setContentsMargins(8, 0, 0, 0)
                    indent_lay.setSpacing(2)

                    path_row = QtWidgets.QHBoxLayout()
                    path_edit = QtWidgets.QLineEdit()
                    path_edit.setPlaceholderText(
                        'Select the Course folder (with the Unit folder next to it)…' if def_.isDX
                        else 'Select the game folder…')
                    existing = setting('GamePath_' + folder,
                                       setting('GamePath', '') if folder == 'NSMBU' else '')
                    if existing:
                        path_edit.setText(str(existing))
                    self_inner._path_edits[folder] = path_edit

                    valid_lbl = QtWidgets.QLabel()
                    valid_lbl.setStyleSheet('font-size: 11px;')

                    def _make_validator(edit, lbl, folder=folder, isDX=def_.isDX):
                        def _v():
                            p = edit.text().strip()
                            ok = isValidGamePath(p, folder) if p else False
                            badMsg = ('✗ Needs 1-1.sarc here and a Unit folder next to it' if isDX
                                      else '✗ Invalid path')
                            lbl.setText('✓ Valid' if ok else ('✗ Not set' if not p else badMsg))
                            lbl.setStyleSheet('color: green; font-size: 11px;' if ok
                                              else 'color: palette(mid); font-size: 11px;' if not p
                                              else 'color: red; font-size: 11px;')
                        edit.textChanged.connect(_v)
                        _v()

                    _make_validator(path_edit, valid_lbl)

                    def _make_browser(edit, fn=folder):
                        def _b():
                            p = QtWidgets.QFileDialog.getExistingDirectory(
                                None, f'Select {fn} game folder', edit.text())
                            if p:
                                edit.setText(p)
                        return _b

                    browse_btn = QtWidgets.QPushButton('Browse…')
                    browse_btn.clicked.connect(_make_browser(path_edit))

                    path_row.addWidget(path_edit)
                    path_row.addWidget(browse_btn)
                    indent_lay.addLayout(path_row)
                    indent_lay.addWidget(valid_lbl)
                    games_vbox.addWidget(indent_w)

                    if idx_g < len(base_games) - 1:
                        games_vbox.addSpacing(4)

                vbox.addWidget(games_group)

                # ── Mod Selection header ──────────────────────────────────────
                mod_header_row = QtWidgets.QHBoxLayout()

                mod_text_col = QtWidgets.QVBoxLayout()
                mod_text_col.setSpacing(1)
                mod_title = QtWidgets.QLabel('<b>Mod Selection</b>')
                mod_sub = QtWidgets.QLabel("Create patches with your Mod's data.")
                mod_sub.setStyleSheet('color: palette(mid); font-size: 11px;')
                mod_text_col.addWidget(mod_title)
                mod_text_col.addWidget(mod_sub)

                add_mod_menu = QtWidgets.QMenu()
                add_mod_menu.setToolTipsVisible(True)
                _act_new = add_mod_menu.addAction(
                    GetIcon('new'), 'New Mod…', lambda: _new_mod())
                _act_new.setToolTip('Create a new empty mod.')
                _act_import = add_mod_menu.addAction(
                    GetIcon('openfromfile'), 'Import Mod Folder…', lambda: _import_mod())
                _act_import.setToolTip('Copy a mod folder to the Yaz0moto user mods.')
                _act_link = add_mod_menu.addAction(
                    GetIcon('folderpath'), 'Link Mod Folder…', lambda: _link_mod())
                _act_link.setToolTip('Symlink an external folder. Any edits will affect the source folder.')
                add_mod_menu.addSeparator()
                _act_dl = add_mod_menu.addAction(
                    GetIcon('download'), 'Download Patch from URL…', lambda: _download_mod_from_url())
                _act_dl.setToolTip('Download a mod from a GitHub repo or direct .zip URL.')

                new_mod_btn = QtWidgets.QToolButton()
                new_mod_btn.setIcon(GetIcon('add'))
                new_mod_btn.setFixedSize(26, 26)
                new_mod_btn.setIconSize(QtCore.QSize(15, 15))
                new_mod_btn.setToolTip('Add Mod')
                new_mod_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
                new_mod_btn.setMenu(add_mod_menu)

                open_folder_btn = QtWidgets.QPushButton(GetIcon('open'), '')
                open_folder_btn.setToolTip('Open Mods Folder')
                open_folder_btn.setFixedSize(26, 26)
                open_folder_btn.setIconSize(QtCore.QSize(15, 15))

                refresh_btn = QtWidgets.QPushButton(GetIcon('reload'), '')
                refresh_btn.setToolTip('Refresh Mods')
                refresh_btn.setFixedSize(26, 26)
                refresh_btn.setIconSize(QtCore.QSize(15, 15))

                util_row = QtWidgets.QHBoxLayout()
                util_row.setSpacing(3)
                util_row.addWidget(new_mod_btn)
                util_row.addWidget(open_folder_btn)
                util_row.addWidget(refresh_btn)

                mod_header_row.addLayout(mod_text_col)
                mod_header_row.addStretch(1)
                mod_header_row.addLayout(util_row)
                mod_header_row.setAlignment(util_row, Qt.AlignVCenter)
                vbox.addLayout(mod_header_row)

                # ── Two-panel mods layout ────────────────────────────────────
                current_mods = setting('LastMods') or []
                if isinstance(current_mods, str):
                    current_mods = [current_mods]
                all_mods = _gd.getAvailableMods()
                all_folders = {f: d for d, f in all_mods}

                splitter = QtWidgets.QSplitter(Qt.Horizontal)

                left_w = QtWidgets.QWidget()
                left_lay = QtWidgets.QVBoxLayout(left_w)
                left_lay.setContentsMargins(0, 0, 4, 0)
                left_lay.setSpacing(4)

                avail_header = QtWidgets.QHBoxLayout()
                avail_lbl = QtWidgets.QLabel('Available')
                add_btn = QtWidgets.QPushButton('Add →')
                add_btn.setStyleSheet('font-size: 11px; padding: 1px 6px;')

                avail_header.addWidget(avail_lbl)
                avail_header.addStretch(1)
                avail_header.addWidget(add_btn)

                avail_list = QtWidgets.QListWidget()
                avail_list.setDragDropMode(QtWidgets.QAbstractItemView.NoDragDrop)
                self_inner.avail_list = avail_list

                left_lay.addLayout(avail_header)
                left_lay.addWidget(avail_list)

                # Right panel: Active + Remove button in header
                right_w = QtWidgets.QWidget()
                right_lay = QtWidgets.QVBoxLayout(right_w)
                right_lay.setContentsMargins(4, 0, 0, 0)
                right_lay.setSpacing(4)

                active_header = QtWidgets.QHBoxLayout()
                active_lbl = QtWidgets.QLabel('Active')
                active_hint = QtWidgets.QLabel('  drag to reorder')
                active_hint.setStyleSheet('color: palette(mid); font-size: 10px;')
                remove_btn = QtWidgets.QPushButton('← Remove')
                remove_btn.setIconSize(QtCore.QSize(13, 13))
                remove_btn.setStyleSheet('font-size: 11px; padding: 1px 6px;')
                active_header.addWidget(active_lbl)
                active_header.addWidget(active_hint)
                active_header.addStretch(1)
                active_header.addWidget(remove_btn)

                active_list = QtWidgets.QListWidget()
                active_list.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
                active_list.setDefaultDropAction(Qt.MoveAction)
                self_inner.active_list = active_list

                right_lay.addLayout(active_header)
                right_lay.addWidget(active_list)

                splitter.addWidget(left_w)
                splitter.addWidget(right_w)
                splitter.setStretchFactor(0, 1)
                splitter.setStretchFactor(1, 1)
                vbox.addWidget(splitter, 1)

                # ── Mod inspector panel ───────────────────────────────────────
                # Shown below the lists whenever any mod is selected in either panel.
                inspector = QtWidgets.QFrame()
                inspector.setFrameShape(QtWidgets.QFrame.StyledPanel)
                inspector.setVisible(False)
                self_inner.inspector = inspector

                insp_lay = QtWidgets.QVBoxLayout(inspector)
                insp_lay.setContentsMargins(10, 8, 10, 8)
                insp_lay.setSpacing(4)

                insp_name = QtWidgets.QLabel()
                insp_name.setStyleSheet('font-size: 13px; font-weight: bold;')
                self_inner.insp_name = insp_name
                insp_lay.addWidget(insp_name)

                insp_sep = QtWidgets.QFrame()
                insp_sep.setFrameShape(QtWidgets.QFrame.HLine)
                insp_sep.setFrameShadow(QtWidgets.QFrame.Sunken)
                insp_lay.addWidget(insp_sep)

                insp_desc = QtWidgets.QLabel()
                insp_desc.setStyleSheet('color: palette(mid); font-size: 11px;')
                insp_desc.setWordWrap(True)
                self_inner.insp_desc = insp_desc
                insp_lay.addWidget(insp_desc)

                insp_btn_row = QtWidgets.QHBoxLayout()
                insp_btn_row.setSpacing(6)
                insp_btn_row.setContentsMargins(0, 4, 0, 0)
                configure_btn = QtWidgets.QPushButton(GetIcon('settings'), 'Configure…')
                configure_btn.setIconSize(QtCore.QSize(14, 14))
                open_mod_folder_btn = QtWidgets.QPushButton(GetIcon('open'), 'Open Folder')
                open_mod_folder_btn.setIconSize(QtCore.QSize(14, 14))
                insp_btn_row.addWidget(configure_btn)
                insp_btn_row.addWidget(open_mod_folder_btn)
                insp_btn_row.addStretch(1)
                insp_lay.addLayout(insp_btn_row)
                vbox.addWidget(inspector)

                # In-memory cache for mod paths (no setSetting until OK)
                self_inner._mod_path_cache = {}
                self_inner._current_mod_folder = None

                # ── Populate lists ────────────────────────────────────────────
                active_set = set(current_mods)
                for def_, folder in all_mods:
                    is_broken = bool(getattr(def_, 'error', None))
                    if not is_broken and folder in active_set:
                        continue
                    item = QtWidgets.QListWidgetItem(def_.name)
                    item.setData(Qt.UserRole, folder)
                    item.setData(Qt.UserRole + 1, def_.description)
                    item.setData(Qt.UserRole + 2, def_.error if is_broken else None)
                    item.setData(Qt.UserRole + 3, getattr(def_, 'patchReleaseUrl', None))
                    item.setData(Qt.UserRole + 4, getattr(def_, 'version', None))
                    if is_broken:
                        item.setForeground(QtGui.QColor('#cc3333'))
                        item.setToolTip(f'⚠ {def_.error}')
                    else:
                        item.setToolTip(def_.description)
                    avail_list.addItem(item)

                for folder in current_mods:
                    if folder in all_folders:
                        def_ = all_folders[folder]
                        if getattr(def_, 'error', None):
                            continue
                        item = QtWidgets.QListWidgetItem(def_.name if hasattr(def_, 'name') else folder)
                        item.setData(Qt.UserRole, folder)
                        item.setData(Qt.UserRole + 1, getattr(def_, 'description', ''))
                        item.setData(Qt.UserRole + 3, getattr(def_, 'patchReleaseUrl', None))
                        item.setData(Qt.UserRole + 4, getattr(def_, 'version', None))
                        active_list.addItem(item)

                # ── Signals ───────────────────────────────────────────────────
                def _show_inspector(display_name, folder):
                    """Show the inspector for the selected mod (either list)."""
                    self_inner._current_mod_folder = folder
                    insp_name.setText(display_name)
                    sel = avail_list.currentItem() or active_list.currentItem()
                    error = sel.data(Qt.UserRole + 2) if sel else None
                    if error:
                        insp_desc.setText(f'Error: {error}')
                        insp_desc.setStyleSheet('color: red; font-size: 11px;')
                    else:
                        insp_desc.setText((sel.data(Qt.UserRole + 1) if sel else '') or '')
                        insp_desc.setStyleSheet('color: palette(mid); font-size: 11px;')
                    inspector.setVisible(True)

                def _on_avail_selection():
                    sel = avail_list.currentItem()
                    if sel is None:
                        return
                    active_list.blockSignals(True)
                    active_list.clearSelection()
                    active_list.setCurrentItem(None)
                    active_list.blockSignals(False)
                    _show_inspector(sel.text(), sel.data(Qt.UserRole))

                def _on_active_selection():
                    sel = active_list.currentItem()
                    if sel is None:
                        return
                    avail_list.blockSignals(True)
                    avail_list.clearSelection()
                    avail_list.setCurrentItem(None)
                    avail_list.blockSignals(False)
                    _show_inspector(sel.text(), sel.data(Qt.UserRole))

                def _add_mod():
                    sel = avail_list.currentItem()
                    if sel is None:
                        return
                    avail_list.takeItem(avail_list.row(sel))
                    active_list.addItem(sel)
                    active_list.setCurrentItem(sel)

                def _remove_mod():
                    sel = active_list.currentItem()
                    if sel is None:
                        return
                    active_list.takeItem(active_list.row(sel))
                    avail_list.addItem(sel)
                    avail_list.setCurrentItem(sel)
                    self_inner._current_mod_folder = None

                def _new_mod():
                    """Show dialog to create a new user-patch folder."""
                    import re as _re
                    dlg_new = QtWidgets.QDialog(self_inner)
                    dlg_new.setWindowTitle('Create a New Mod')
                    dlg_new.setMinimumWidth(380)
                    form_new = QtWidgets.QFormLayout()
                    form_new.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    name_edit_n = QtWidgets.QLineEdit()
                    name_edit_n.setPlaceholderText('Newer U')
                    form_new.addRow('Name:', name_edit_n)
                    desc_edit_n = QtWidgets.QLineEdit()
                    desc_edit_n.setPlaceholderText('Description (optional)')
                    form_new.addRow('Description:', desc_edit_n)
                    btns_new = QtWidgets.QDialogButtonBox(
                        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
                    btns_new.button(QtWidgets.QDialogButtonBox.Ok).setText('Create')
                    btns_new.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
                    name_edit_n.textChanged.connect(
                        lambda t: btns_new.button(
                            QtWidgets.QDialogButtonBox.Ok).setEnabled(bool(t.strip())))
                    btns_new.accepted.connect(dlg_new.accept)
                    btns_new.rejected.connect(dlg_new.reject)
                    lay_new = QtWidgets.QVBoxLayout(dlg_new)
                    lay_new.addLayout(form_new)
                    lay_new.addWidget(btns_new)
                    if dlg_new.exec_() != QtWidgets.QDialog.Accepted:
                        return
                    mod_name_n = name_edit_n.text().strip()
                    mod_desc_n = desc_edit_n.text().strip()
                    # Build a filesystem-safe slug from the name
                    slug = _re.sub(r'[^\w\-]', '_', mod_name_n).strip('_') or 'mod'
                    user_patches = os.path.join(globals.user_data_path, 'patches')
                    base_slug, ctr = slug, 1
                    while os.path.exists(os.path.join(user_patches, slug)):
                        slug = f'{base_slug}_{ctr}'; ctr += 1
                    from .patchxml import PatchXmlEditor
                    PatchXmlEditor.create_mod(user_patches, slug, mod_name_n, mod_desc_n)
                    item_n = QtWidgets.QListWidgetItem(mod_name_n)
                    item_n.setData(Qt.UserRole, slug)
                    item_n.setData(Qt.UserRole + 1, mod_desc_n)
                    item_n.setToolTip(mod_desc_n)
                    avail_list.addItem(item_n)
                    avail_list.setCurrentItem(item_n)

                def _add_folder_entry(slug, user_patches):
                    """Read main.xml from a newly added mod folder and insert it into the list."""
                    import xml.etree.ElementTree as _ET
                    main_xml = os.path.join(user_patches, slug, 'main.xml')
                    try:
                        root_x = _ET.parse(main_xml).getroot()
                        mod_name = root_x.get('name', slug)
                        mod_desc = root_x.get('description', '')
                        mod_url = root_x.get('patchReleaseUrl', '')
                        mod_ver = root_x.get('version', '')
                    except Exception:
                        mod_name = slug
                        mod_desc = ''
                        mod_url = ''
                        mod_ver = ''
                    item_n = QtWidgets.QListWidgetItem(mod_name)
                    item_n.setData(Qt.UserRole, slug)
                    item_n.setData(Qt.UserRole + 1, mod_desc)
                    item_n.setData(Qt.UserRole + 3, mod_url or None)
                    item_n.setData(Qt.UserRole + 4, mod_ver or None)
                    item_n.setToolTip(mod_desc)
                    avail_list.addItem(item_n)
                    avail_list.setCurrentItem(item_n)

                def _import_mod():
                    """Copy an external mod folder into the userdata patches directory."""
                    import re as _re, shutil as _sh
                    src = QtWidgets.QFileDialog.getExistingDirectory(
                        self_inner, 'Select Mod Folder to Import', '')
                    if not src:
                        return
                    src = os.path.normpath(src)
                    if not os.path.isfile(os.path.join(src, 'main.xml')):
                        QtWidgets.QMessageBox.warning(
                            self_inner, 'Import Mod Folder',
                            'The selected folder does not contain a main.xml.\n'
                            'Please select a valid mod folder.')
                        return
                    user_patches = os.path.join(globals.user_data_path, 'patches')
                    slug = _re.sub(r'[^\w\-]', '_', os.path.basename(src)).strip('_') or 'mod'
                    base_slug, ctr = slug, 1
                    while os.path.exists(os.path.join(user_patches, slug)):
                        slug = f'{base_slug}_{ctr}'; ctr += 1
                    try:
                        _sh.copytree(src, os.path.join(user_patches, slug))
                    except Exception as e:
                        QtWidgets.QMessageBox.critical(
                            self_inner, 'Import Mod Folder', f'Copy failed:\n{e}')
                        return
                    _add_folder_entry(slug, user_patches)

                def _link_mod():
                    """Create a symlink in the userdata patches directory pointing to an external mod folder."""
                    import re as _re
                    src = QtWidgets.QFileDialog.getExistingDirectory(
                        self_inner, 'Select Mod Folder to Link', '')
                    if not src:
                        return
                    src = os.path.normpath(src)
                    if not os.path.isfile(os.path.join(src, 'main.xml')):
                        QtWidgets.QMessageBox.warning(
                            self_inner, 'Link Mod Folder',
                            'The selected folder does not contain a main.xml.\n'
                            'Please select a valid mod folder.')
                        return
                    user_patches = os.path.join(globals.user_data_path, 'patches')
                    slug = _re.sub(r'[^\w\-]', '_', os.path.basename(src)).strip('_') or 'mod'
                    base_slug, ctr = slug, 1
                    while os.path.exists(os.path.join(user_patches, slug)):
                        slug = f'{base_slug}_{ctr}'; ctr += 1
                    try:
                        os.symlink(src, os.path.join(user_patches, slug))
                    except Exception as e:
                        QtWidgets.QMessageBox.critical(
                            self_inner, 'Link Mod Folder', f'Symlink failed:\n{e}')
                        return
                    _add_folder_entry(slug, user_patches)

                def _download_mod_from_url():
                    """Show dialog to download a mod from URL and install to user patches."""
                    dlg = QtWidgets.QDialog(self_inner)
                    dlg.setWindowTitle('Download Patch from URL')
                    dlg.setMinimumWidth(500)
                    lay = QtWidgets.QVBoxLayout(dlg)

                    form = QtWidgets.QFormLayout()
                    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    url_edit = QtWidgets.QLineEdit()
                    url_edit.setPlaceholderText('https://github.com/user/repo')
                    form.addRow('URL:', url_edit)
                    lay.addLayout(form)

                    info_label = QtWidgets.QLabel()
                    info_label.setWordWrap(True)
                    info_label.setStyleSheet('color: palette(mid); font-size: 11px;')
                    info_label.hide()
                    lay.addWidget(info_label)

                    btns = QtWidgets.QDialogButtonBox(
                        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
                    btns.button(QtWidgets.QDialogButtonBox.Ok).setText('Download')
                    btns.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
                    btns.accepted.connect(dlg.accept)
                    btns.rejected.connect(dlg.reject)
                    lay.addWidget(btns)

                    resolved_info = {}

                    def _resolve_url():
                        url = url_edit.text().strip()
                        if not url:
                            btns.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
                            info_label.hide()
                            return
                        btns.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(True)
                        info_label.setText('Resolving URL\u2026')
                        info_label.show()
                        QtWidgets.QApplication.processEvents()
                        if 'github.com' in url:
                            result = _resolve_github_url(url)
                        else:
                            result = {'download_url': url, 'name': 'Patch', 'version': '0.0'}
                        if result:
                            resolved_info.clear()
                            resolved_info.update(result)
                            patch_name = result.get('name', 'Unknown')
                            patch_ver = result.get('version', '?')
                            info_label.setText(
                                f'<b>Name:</b> {patch_name}<br>'
                                f'<b>Version:</b> {patch_ver}')
                        else:
                            info_label.setText('<span style="color:red;">Could not resolve URL. Check it and try again.</span>')

                    url_edit.textChanged.connect(_resolve_url)

                    if dlg.exec_() != QtWidgets.QDialog.Accepted:
                        return
                    url = url_edit.text().strip()
                    if not url:
                        return

                    dl_url = resolved_info.get('download_url', url)
                    patch_name = resolved_info.get('name', 'Unknown')
                    patch_ver = resolved_info.get('version', '0.0')

                    # Confirm with user
                    confirm = QtWidgets.QMessageBox(self_inner)
                    confirm.setWindowTitle('Confirm Download')
                    confirm.setText(
                        f'Download and install this mod?\n\n'
                        f'Name: {patch_name}\n'
                        f'Version: {patch_ver}\n'
                        f'URL: {dl_url}')
                    confirm.setInformativeText('The mod will be extracted to your user patches folder.')
                    confirm.setStandardButtons(
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                    confirm.setDefaultButton(QtWidgets.QMessageBox.Yes)
                    if confirm.exec_() != QtWidgets.QMessageBox.Yes:
                        return

                    # Start download
                    user_patches = os.path.join(globals.user_data_path, 'patches')
                    tmp_dir = os.path.join(globals.user_data_path, '.download_tmp')
                    os.makedirs(tmp_dir, exist_ok=True)
                    tmp_zip = os.path.join(tmp_dir, 'patch.zip')

                    download_progress = QtWidgets.QProgressDialog(
                        'Connecting\u2026', 'Cancel', 0, 100, self_inner)
                    download_progress.setWindowTitle('Downloading Patch')
                    download_progress.setWindowModality(Qt.WindowModal)
                    download_progress.setAutoClose(False)
                    download_progress.setAutoReset(False)
                    download_progress.setMinimumDuration(0)
                    download_progress.setValue(0)
                    download_progress.show()

                    worker = _DownloadModWorker(dl_url, tmp_zip, tmp_dir)
                    download_progress.canceled.connect(worker.cancel)

                    def _on_progress(v):
                        if v < 0:
                            download_progress.setRange(0, 0)
                        else:
                            download_progress.setRange(0, 100)
                            download_progress.setValue(v)

                    def _on_status(msg):
                        download_progress.setLabelText(msg)

                    def _on_finished(success, err):
                        download_progress.close()
                        if not success:
                            if err != 'Cancelled':
                                QtWidgets.QMessageBox.critical(
                                    self_inner, 'Download Failed', f'Failed to download patch:\n{err}')
                            shutil.rmtree(tmp_dir, ignore_errors=True)
                            return

                        # Find main.xml in extracted files
                        main_xml_dir = _find_main_xml_in_extracted(tmp_dir)
                        if not main_xml_dir:
                            shutil.rmtree(tmp_dir, ignore_errors=True)
                            QtWidgets.QMessageBox.warning(
                                self_inner, 'Invalid Patch',
                                'Downloaded file does not contain a main.xml.\n'
                                'This is not a valid Yaz0moto mod.')
                            return

                        slug = _patch_slug_from_url(url, patch_name)
                        base_slug, ctr = slug, 1
                        while os.path.exists(os.path.join(user_patches, slug)):
                            slug = f'{base_slug}_{ctr}'
                            ctr += 1

                        target = os.path.join(user_patches, slug)
                        try:
                            shutil.copytree(main_xml_dir, target)
                        except Exception as e:
                            shutil.rmtree(tmp_dir, ignore_errors=True)
                            QtWidgets.QMessageBox.critical(
                                self_inner, 'Install Failed', f'Failed to install patch:\n{e}')
                            return

                        # Write patchReleaseUrl to main.xml if from GitHub
                        if 'github.com' in url:
                            from .patchxml import PatchXmlEditor
                            PatchXmlEditor(target).set_patch_release_url(url)

                        shutil.rmtree(tmp_dir, ignore_errors=True)

                        _add_folder_entry(slug, user_patches)

                    worker.progress.connect(_on_progress)
                    worker.statusMsg.connect(_on_status)
                    worker.completed.connect(_on_finished)
                    _start_background_worker(self_inner, worker)

                def _do_update_mod(item):
                    """Update a single mod from its patchReleaseUrl."""
                    folder = item.data(Qt.UserRole)
                    url = item.data(Qt.UserRole + 3)
                    if not url:
                        return
                    _upd = os.path.join(globals.user_data_path, 'patches')
                    mod_dir = os.path.join(_upd, folder)
                    if not os.path.isdir(mod_dir):
                        QtWidgets.QMessageBox.warning(
                            self_inner, 'Update Failed', f'Mod folder not found:\n{mod_dir}')
                        return

                    # Confirm before update
                    confirm = QtWidgets.QMessageBox(self_inner)
                    confirm.setWindowTitle(f'Update {item.text()}?')
                    confirm.setText(f'Check for updates for "{item.text()}"?')
                    confirm.setInformativeText(f'Release URL: {url}')
                    confirm.setStandardButtons(
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                    confirm.setDefaultButton(QtWidgets.QMessageBox.Yes)
                    if confirm.exec_() != QtWidgets.QMessageBox.Yes:
                        return

                    # Start check
                    dlg_prog = QtWidgets.QProgressDialog(
                        'Checking for updates\u2026', 'Cancel', 0, 0, self_inner)
                    dlg_prog.setWindowTitle('Update Check')
                    dlg_prog.show()
                    QtWidgets.QApplication.processEvents()

                    worker = _CheckUpdateWorker(url)

                    def _on_check_result(result):
                        dlg_prog.close()
                        if not result or not result.get('download_url'):
                            QtWidgets.QMessageBox.information(
                                self_inner, 'No Update',
                                'Could not find a release with patch.zip for this mod.')
                            return
                        new_ver = result['version']
                        current_ver = item.data(Qt.UserRole + 4) or '0.0'
                        if new_ver == current_ver:
                            QtWidgets.QMessageBox.information(
                                self_inner, 'Up to Date',
                                f'"{item.text()}" is already at version {current_ver}.')
                            return
                        # Download and install
                        dlg_dl = QtWidgets.QProgressDialog(
                            'Downloading update\u2026', 'Cancel', 0, 100, self_inner)
                        dlg_dl.setWindowTitle('Updating')
                        dlg_dl.show()
                        tmp_dir = os.path.join(globals.user_data_path, '.update_tmp')
                        os.makedirs(tmp_dir, exist_ok=True)
                        tmp_zip = os.path.join(tmp_dir, 'patch.zip')
                        dl_worker = _DownloadModWorker(
                            result['download_url'], tmp_zip, tmp_dir)

                        def _dl_progress(v):
                            if v >= 0:
                                dlg_dl.setValue(v)
                        dl_worker.progress.connect(_dl_progress)

                        def _dl_finished(success, err):
                            dlg_dl.close()
                            if not success:
                                shutil.rmtree(tmp_dir, ignore_errors=True)
                                if err != 'Cancelled':
                                    QtWidgets.QMessageBox.critical(
                                        self_inner, 'Update Failed',
                                        f'Failed to download update:\n{err}')
                                return
                            main_xml_dir = _find_main_xml_in_extracted(tmp_dir)
                            if not main_xml_dir:
                                shutil.rmtree(tmp_dir, ignore_errors=True)
                                QtWidgets.QMessageBox.warning(
                                    self_inner, 'Invalid Update',
                                    'Update archive does not contain a main.xml.')
                                return
                            # Backup current mod dir
                            backup = mod_dir + '.bak'
                            try:
                                if os.path.exists(backup):
                                    shutil.rmtree(backup, ignore_errors=True)
                                os.rename(mod_dir, backup)
                                shutil.copytree(main_xml_dir, mod_dir)
                                shutil.rmtree(backup, ignore_errors=True)
                            except Exception as e:
                                # Restore from backup
                                if os.path.exists(mod_dir):
                                    shutil.rmtree(mod_dir, ignore_errors=True)
                                if os.path.exists(backup):
                                    os.rename(backup, mod_dir)
                                shutil.rmtree(tmp_dir, ignore_errors=True)
                                QtWidgets.QMessageBox.critical(
                                    self_inner, 'Update Failed',
                                    f'Failed to install update:\n{e}')
                                return
                            # Preserve patchReleaseUrl
                            from .patchxml import PatchXmlEditor
                            editor = PatchXmlEditor(mod_dir)
                            editor.set_patch_release_url(url)
                            editor.set_metadata(version=new_ver)
                            shutil.rmtree(tmp_dir, ignore_errors=True)
                            item.setData(Qt.UserRole + 4, new_ver)
                            QtWidgets.QMessageBox.information(
                                self_inner, 'Updated',
                                f'"{item.text()}" updated to version {new_ver}.')

                        dl_worker.completed.connect(_dl_finished)
                        _start_background_worker(self_inner, dl_worker)

                    worker.completed.connect(_on_check_result)
                    _start_background_worker(self_inner, worker)

                def _user_patch_path(item):
                    """Return an item's user-patch path, or None for bundled mods."""
                    folder = item.data(Qt.UserRole)
                    if not folder or os.path.basename(folder) != folder:
                        return None
                    user_patches = os.path.abspath(
                        os.path.join(globals.user_data_path, 'patches'))
                    mod_path = os.path.abspath(os.path.join(user_patches, folder))
                    if os.path.dirname(mod_path) != user_patches:
                        return None
                    return mod_path if os.path.lexists(mod_path) else None

                def _delete_mod(item, source_list):
                    """Delete a user-owned mod, or remove its symlink."""
                    mod_path = _user_patch_path(item)
                    if mod_path is None:
                        QtWidgets.QMessageBox.warning(
                            self_inner, 'Delete Mod',
                            'This bundled mod cannot be deleted here.')
                        return

                    is_link = os.path.islink(mod_path)
                    confirm = QtWidgets.QMessageBox(self_inner)
                    confirm.setWindowTitle('Delete Mod?')
                    confirm.setIcon(QtWidgets.QMessageBox.Warning)
                    confirm.setText(f'Are you sure you want to delete "{item.text()}"?')
                    if is_link:
                        confirm.setInformativeText(
                            'Only the link will be removed. The linked folder and its files will not be deleted.')
                    else:
                        confirm.setInformativeText(
                            'The mod folder and all files inside it will be permanently deleted.')
                    confirm.setStandardButtons(
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                    confirm.setDefaultButton(QtWidgets.QMessageBox.No)
                    if confirm.exec_() != QtWidgets.QMessageBox.Yes:
                        return

                    try:
                        if is_link:
                            os.unlink(mod_path)
                        else:
                            shutil.rmtree(mod_path)
                    except Exception as e:
                        QtWidgets.QMessageBox.critical(
                            self_inner, 'Delete Failed',
                            f'Failed to delete mod:\n{e}')
                        return

                    folder = item.data(Qt.UserRole)
                    source_list.takeItem(source_list.row(item))
                    self_inner._mod_path_cache.pop(folder, None)
                    if self_inner._current_mod_folder == folder:
                        self_inner._current_mod_folder = None
                        inspector.setVisible(False)

                def _on_context_menu_avail(pos):
                    item = avail_list.itemAt(pos)
                    if not item:
                        return
                    url = item.data(Qt.UserRole + 3)
                    menu = QtWidgets.QMenu()
                    if url:
                        act_update = menu.addAction('Update')
                        act_update.triggered.connect(lambda: _do_update_mod(item))
                    act_show_info = menu.addAction('Properties')
                    act_show_info.triggered.connect(
                        lambda: _show_inspector(item.text(), item.data(Qt.UserRole)))
                    if _user_patch_path(item) is not None:
                        menu.addSeparator()
                        act_delete = menu.addAction(GetIcon('delete'), 'Delete\u2026')
                        act_delete.triggered.connect(
                            lambda: _delete_mod(item, avail_list))
                    menu.exec_(avail_list.viewport().mapToGlobal(pos))

                def _on_context_menu_active(pos):
                    item = active_list.itemAt(pos)
                    if not item:
                        return
                    url = item.data(Qt.UserRole + 3)
                    menu = QtWidgets.QMenu()
                    if url:
                        act_update = menu.addAction('Update')
                        act_update.triggered.connect(lambda: _do_update_mod(item))
                    act_show_info = menu.addAction('Properties')
                    act_show_info.triggered.connect(
                        lambda: _show_inspector(item.text(), item.data(Qt.UserRole)))
                    if _user_patch_path(item) is not None:
                        menu.addSeparator()
                        act_delete = menu.addAction(GetIcon('delete'), 'Delete\u2026')
                        act_delete.triggered.connect(
                            lambda: _delete_mod(item, active_list))
                    menu.exec_(active_list.viewport().mapToGlobal(pos))

                def _check_for_updates():
                    """Check all mods with patchReleaseUrl for available updates."""
                    import re as _re
                    updatable = []
                    for lst in (avail_list, active_list):
                        for i in range(lst.count()):
                            item = lst.item(i)
                            url = item.data(Qt.UserRole + 3)
                            if not url:
                                continue
                            if not _re.match(r'https?://github\.com/', url):
                                continue
                            current_ver = item.data(Qt.UserRole + 4) or '0.0'
                            updatable.append((item, url, current_ver))
                    if not updatable:
                        QtWidgets.QMessageBox.information(
                            self_inner, 'Check for Updates',
                            'No mods with GitHub release URLs found to check.')
                        return
                    # Simple progress dialog while checking
                    dlg = QtWidgets.QProgressDialog(
                        'Checking for updates\u2026', 'Cancel', 0, len(updatable), self_inner)
                    dlg.setWindowTitle('Update Check')
                    results = []
                    for idx, (item, url, cur_ver) in enumerate(updatable):
                        if dlg.wasCanceled():
                            break
                        dlg.setValue(idx)
                        dlg.setLabelText(f'Checking {item.text()}\u2026')
                        QtWidgets.QApplication.processEvents()
                        try:
                            m = _re.match(r'https?://github\.com/([^/]+)/([^/]+)', url)
                            if m:
                                owner, repo = m.group(1), m.group(2).rstrip('/').replace('.git', '')
                                api = f'https://api.github.com/repos/{owner}/{repo}/releases/latest'
                                resp = requests.get(api, timeout=10)
                                if resp.status_code == 200:
                                    data = resp.json()
                                    tag = data.get('tag_name', '').lstrip('v')
                                    if tag and tag != cur_ver:
                                        results.append((item, cur_ver, tag))
                        except Exception:
                            pass
                    dlg.setValue(len(updatable))
                    if not results:
                        QtWidgets.QMessageBox.information(
                            self_inner, 'Check for Updates',
                            'All mods are up to date.')
                        return
                    # Show summary dialog
                    sum_dlg = QtWidgets.QDialog(self_inner)
                    sum_dlg.setWindowTitle('Updates Available')
                    sum_dlg.setMinimumWidth(420)
                    sum_lay = QtWidgets.QVBoxLayout(sum_dlg)
                    sum_lbl = QtWidgets.QLabel(
                        f'<b>Updates available for {len(results)} mod(s):</b>')
                    sum_lay.addWidget(sum_lbl)
                    sum_list = QtWidgets.QListWidget()
                    for item, cur, new in results:
                        li = QtWidgets.QListWidgetItem(f'{item.text()}  ({cur} → {new})')
                        li.setData(Qt.UserRole, item.data(Qt.UserRole))
                        li.setData(Qt.UserRole + 1, new)
                        li.setCheckState(Qt.Checked)
                        sum_list.addItem(li)
                    sum_lay.addWidget(sum_list)
                    sum_btns = QtWidgets.QDialogButtonBox(
                        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
                    sum_btns.button(QtWidgets.QDialogButtonBox.Ok).setText('Update Selected')
                    sum_btns.accepted.connect(sum_dlg.accept)
                    sum_btns.rejected.connect(sum_dlg.reject)
                    sum_lay.addWidget(sum_btns)
                    if sum_dlg.exec_() != QtWidgets.QDialog.Accepted:
                        return
                    # Update selected mods
                    for i in range(sum_list.count()):
                        li = sum_list.item(i)
                        if li.checkState() != Qt.Checked:
                            continue
                        folder = li.data(Qt.UserRole)
                        new_ver = li.data(Qt.UserRole + 1)
                        # Find the item in the lists
                        for lst in (avail_list, active_list):
                            for j in range(lst.count()):
                                item = lst.item(j)
                                if item.data(Qt.UserRole) == folder:
                                    _do_update_mod(item)
                                    break

                def _open_configure():
                    """Show Configure modal for the currently selected mod."""
                    folder = self_inner._current_mod_folder
                    if folder is None:
                        return
                    _upd = os.path.join(globals.user_data_path, 'patches')
                    is_user = os.path.isfile(os.path.join(_upd, folder, 'main.xml'))
                    sel_c = avail_list.currentItem() or active_list.currentItem()
                    cur_name = sel_c.text() if sel_c else folder
                    cur_desc = (sel_c.data(Qt.UserRole + 1) if sel_c else '') or ''
                    cur_path = self_inner._mod_path_cache.get(
                        folder, setting('GamePath_mod_' + folder, '') or '')
                    cur_url = sel_c.data(Qt.UserRole + 3) if sel_c else None
                    if not cur_url:
                        from .patchxml import PatchXmlEditor as _Pxe
                        _pxe = _Pxe(os.path.join(_upd, folder) if is_user else '')
                        cur_url = _pxe.patch_release_url() if is_user else None
                    dlg_cfg = QtWidgets.QDialog(self_inner)
                    dlg_cfg.setWindowTitle(f'Configure — {cur_name}')
                    dlg_cfg.setMinimumWidth(480)
                    form_cfg = QtWidgets.QFormLayout()
                    form_cfg.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if not is_user:
                        note_c = QtWidgets.QLabel('Name and description are read-only for bundled mods.')
                        note_c.setStyleSheet('color: palette(mid); font-size: 11px;')
                        form_cfg.addRow('', note_c)
                    name_edit_c = QtWidgets.QLineEdit(cur_name)
                    name_edit_c.setEnabled(is_user)
                    form_cfg.addRow('Name:', name_edit_c)
                    desc_edit_c = QtWidgets.QLineEdit(cur_desc)
                    desc_edit_c.setEnabled(is_user)
                    form_cfg.addRow('Description:', desc_edit_c)
                    # Remote patch URL
                    url_edit_c = QtWidgets.QLineEdit(cur_url or '')
                    url_edit_c.setPlaceholderText('https://github.com/user/repo')
                    url_edit_c.setEnabled(is_user)
                    form_cfg.addRow('Patch URL:', url_edit_c)
                    # Game path row with Browse
                    path_w_c = QtWidgets.QWidget()
                    ph_c = QtWidgets.QHBoxLayout(path_w_c)
                    ph_c.setContentsMargins(0, 0, 0, 0)
                    path_edit_c = QtWidgets.QLineEdit(cur_path)
                    path_edit_c.setPlaceholderText('Leave blank to use base game path')
                    browse_c = QtWidgets.QPushButton('Browse…')
                    ph_c.addWidget(path_edit_c)
                    ph_c.addWidget(browse_c)
                    form_cfg.addRow('Game path:', path_w_c)
                    valid_c = QtWidgets.QLabel()
                    valid_c.setStyleSheet('color: palette(mid); font-size: 11px;')
                    form_cfg.addRow('', valid_c)
                    def _vc():
                        p = path_edit_c.text().strip()
                        ok = isValidGamePath(p) if p else None
                        if ok is None:
                            valid_c.setText('Uses base game path by default')
                            valid_c.setStyleSheet('color: palette(mid); font-size: 11px;')
                        elif ok:
                            valid_c.setText('✓ Valid')
                            valid_c.setStyleSheet('color: green; font-size: 11px;')
                        else:
                            valid_c.setText('✗ Invalid path')
                            valid_c.setStyleSheet('color: red; font-size: 11px;')
                    path_edit_c.textChanged.connect(_vc)
                    _vc()
                    def _browse_c():
                        p = QtWidgets.QFileDialog.getExistingDirectory(
                            None, 'Select mod game folder', path_edit_c.text())
                        if p:
                            path_edit_c.setText(p)
                    browse_c.clicked.connect(_browse_c)
                    btns_cfg = QtWidgets.QDialogButtonBox(
                        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
                    btns_cfg.accepted.connect(dlg_cfg.accept)
                    btns_cfg.rejected.connect(dlg_cfg.reject)
                    lay_cfg = QtWidgets.QVBoxLayout(dlg_cfg)
                    lay_cfg.addLayout(form_cfg)
                    lay_cfg.addWidget(btns_cfg)
                    if dlg_cfg.exec_() != QtWidgets.QDialog.Accepted:
                        return
                    new_name = name_edit_c.text().strip() or cur_name
                    new_desc = desc_edit_c.text().strip()
                    new_url = url_edit_c.text().strip() or None
                    new_path = path_edit_c.text().strip()
                    self_inner._mod_path_cache[folder] = new_path
                    if is_user:
                        from .patchxml import PatchXmlEditor as _Pxe2
                        _editor = _Pxe2(os.path.join(_upd, folder))
                        meta_dirty = new_name != cur_name or new_desc != cur_desc
                        url_dirty = new_url != (cur_url or None)
                        if meta_dirty or url_dirty:
                            _editor.set_metadata(new_name, new_desc)
                        if url_dirty:
                            _editor.set_patch_release_url(new_url or '')
                    if sel_c:
                        sel_c.setText(new_name)
                        sel_c.setData(Qt.UserRole + 1, new_desc)
                        sel_c.setData(Qt.UserRole + 3, new_url)
                    insp_name.setText(new_name)
                    insp_desc.setText(new_desc)

                def _open_mod_folder():
                    """Open the selected mod's own directory."""
                    folder = self_inner._current_mod_folder
                    if folder is None:
                        return
                    _upd = os.path.join(globals.user_data_path, 'patches')
                    _bpd = os.path.join(globals.miyamoto_path, 'yaz0data', 'patches')
                    mod_dir = (os.path.join(_upd, folder)
                               if os.path.isdir(os.path.join(_upd, folder))
                               else os.path.join(_bpd, folder)
                               if os.path.isdir(os.path.join(_bpd, folder))
                               else None)
                    if mod_dir:
                        QtGui.QDesktopServices.openUrl(
                            QtCore.QUrl.fromLocalFile(mod_dir))

                def _open_mods_folder():
                    user_patches = os.path.join(globals.user_data_path, 'patches')
                    os.makedirs(user_patches, exist_ok=True)
                    QtGui.QDesktopServices.openUrl(
                        QtCore.QUrl.fromLocalFile(user_patches))

                def _refresh_mods():
                    current_active = [
                        active_list.item(i).data(Qt.UserRole)
                        for i in range(active_list.count())
                    ]
                    current_active_set = set(current_active)
                    # Block signals on both lists so clearing/repopulating
                    # doesn't spuriously fire selection handlers mid-rebuild.
                    avail_list.blockSignals(True)
                    active_list.blockSignals(True)
                    avail_list.clear()
                    active_list.clear()
                    # Rebuild active list (dropping any broken mods)
                    all_mods = _gd.getAvailableMods()
                    all_folders = {f: d for d, f in all_mods}
                    for folder in current_active:
                        if folder in all_folders:
                            def_ = all_folders[folder]
                            if getattr(def_, 'error', None):
                                continue
                            item = QtWidgets.QListWidgetItem(def_.name if hasattr(def_, 'name') else folder)
                            item.setData(Qt.UserRole, folder)
                            item.setData(Qt.UserRole + 1, getattr(def_, 'description', ''))
                            item.setData(Qt.UserRole + 3, getattr(def_, 'patchReleaseUrl', None))
                            item.setData(Qt.UserRole + 4, getattr(def_, 'version', None))
                            active_list.addItem(item)
                    # Rebuild available list
                    for def_, folder in all_mods:
                        is_broken = bool(getattr(def_, 'error', None))
                        if not is_broken and folder in current_active_set:
                            continue
                        item = QtWidgets.QListWidgetItem(def_.name)
                        item.setData(Qt.UserRole, folder)
                        item.setData(Qt.UserRole + 1, def_.description)
                        item.setData(Qt.UserRole + 2, def_.error if is_broken else None)
                        item.setData(Qt.UserRole + 3, getattr(def_, 'patchReleaseUrl', None))
                        item.setData(Qt.UserRole + 4, getattr(def_, 'version', None))
                        if is_broken:
                            item.setForeground(QtGui.QColor('#cc3333'))
                            item.setToolTip(f'⚠ {def_.error}')
                        else:
                            item.setToolTip(def_.description)
                        avail_list.addItem(item)
                    avail_list.blockSignals(False)
                    active_list.blockSignals(False)
                    # Reset inspector state cleanly after the rebuild.
                    self_inner._current_mod_folder = None
                    inspector.setVisible(False)
                    # After refresh, check for updates if any mod has patchReleaseUrl
                    has_updatable = any(
                        avail_list.item(i).data(Qt.UserRole + 3) for i in range(avail_list.count())
                    ) or any(
                        active_list.item(i).data(Qt.UserRole + 3) for i in range(active_list.count())
                    )
                    if has_updatable:
                        _check_for_updates()

                avail_list.currentItemChanged.connect(lambda *_: _on_avail_selection())
                active_list.currentItemChanged.connect(lambda *_: _on_active_selection())
                add_btn.clicked.connect(_add_mod)
                remove_btn.clicked.connect(_remove_mod)
                configure_btn.clicked.connect(_open_configure)
                open_mod_folder_btn.clicked.connect(_open_mod_folder)
                open_folder_btn.clicked.connect(_open_mods_folder)
                refresh_btn.clicked.connect(_refresh_mods)

                # Right-click context menus
                avail_list.setContextMenuPolicy(Qt.CustomContextMenu)
                avail_list.customContextMenuRequested.connect(_on_context_menu_avail)
                active_list.setContextMenuPolicy(Qt.CustomContextMenu)
                active_list.customContextMenuRequested.connect(_on_context_menu_active)

            def getSelectedBaseGame(self_inner):
                # Keep the current game if its path is still valid; otherwise fall back to
                # the first game that has a valid path
                current = setting('LastBaseGame', 'NSMBU')
                current_edit = self_inner._path_edits.get(current)
                if current_edit is not None and isValidGamePath(current_edit.text().strip(), current):
                    return current

                for folder, edit in self_inner._path_edits.items():
                    if isValidGamePath(edit.text().strip(), folder):
                        return folder
                return setting('LastBaseGame', 'NSMBU')

            def getActiveMods(self_inner):
                result = []
                for i in range(self_inner.active_list.count()):
                    folder = self_inner.active_list.item(i).data(Qt.UserRole)
                    if folder:
                        result.append(folder)
                return result

            def getModPaths(self_inner):
                """Return in-memory mod path cache (paths are written by the Configure modal)."""
                return self_inner._mod_path_cache

        return GameSetupTab()

    @staticmethod
    def getThemesTab(parent):
        """
        Returns the Themes Tab
        """

        class ThemesTab(parent):
            """
            Themes Tab
            """
            info = "<b>Themes</b><br>Pick a theme to change the application's colors and icons,<br>and adjust the scale of the interface."

            def __init__(self):
                """
                Initializes the Themes Tab
                """
                super().__init__()

                # Get the current and available themes
                self.themeID = globals.theme.themeName
                self.themes = self.getAvailableThemes

                # Create the theme box
                self.themeBox = QtWidgets.QComboBox()
                for name, themeObj in self.themes:
                    self.themeBox.addItem(name)

                index = self.themeBox.findText(setting('Theme'), Qt.MatchFixedString)
                if index >= 0:
                     self.themeBox.setCurrentIndex(index)

                self.themeBox.currentIndexChanged.connect(self.UpdatePreview)

                createButton = QtWidgets.QPushButton('Create Theme...')
                createButton.setToolTip('Make your own theme: choose an accent colour, background, text colour and roundness.')
                createButton.clicked.connect(self.openThemeEditor)

                boxGB = QtWidgets.QGroupBox('Themes')
                L = QtWidgets.QFormLayout()
                L.addRow('Theme:', self.themeBox)
                L.addRow('', createButton)
                L2 = QtWidgets.QGridLayout()
                L2.addLayout(L, 0, 0)
                boxGB.setLayout(L2)

                # Create the preview labels and groupbox
                self.preview = QtWidgets.QLabel()
                self.description = QtWidgets.QLabel()
                L = QtWidgets.QVBoxLayout()
                L.addWidget(self.preview)
                L.addWidget(self.description)
                L.addStretch(1)
                previewGB = QtWidgets.QGroupBox('Preview')
                previewGB.setLayout(L)

                # Create the options box options
                keys = QtWidgets.QStyleFactory().keys()
                self.NonWinStyle = QtWidgets.QComboBox()
                self.NonWinStyle.setToolTip('<b>Use Nonstandard Window Style</b><br>If this is checkable, the selected theme specifies a<br>window style other than the default. In most cases, you<br>should leave this checked. Uncheck this if you dislike<br>the style this theme uses.')
                self.NonWinStyle.addItems(keys)
                uistyle = setting('uiStyle', "Fusion")
                if uistyle is not None:
                    self.NonWinStyle.setCurrentIndex(keys.index(setting('uiStyle', "Fusion")))

                # Create the UI scale option
                self.uiScale = QtWidgets.QDoubleSpinBox()
                self.uiScale.setRange(50.0, 300.0)
                self.uiScale.setSingleStep(5.0)
                self.uiScale.setSuffix('%')
                self.uiScale.setValue(float(setting('UIScale', 1.0)) * 100)
                self.uiScale.setToolTip('<b>UI Scale</b><br>Adjusts the overall size of the interface.<br>Requires a restart to take effect.')

                # Create the toolbar icon size option
                self.toolbarIconSize = QtWidgets.QComboBox()
                for size, label in zip(TOOLBAR_ICON_SIZES, ('Small', 'Compact', 'Normal', 'Large', 'Huge')):
                    self.toolbarIconSize.addItem('%s (%d px)' % (label, size), size)
                self.toolbarIconSize.setCurrentIndex(TOOLBAR_ICON_SIZES.index(toolbarIconSize()))

                # Create the options groupbox
                L = QtWidgets.QFormLayout()
                L.addRow('UI Scale:', self.uiScale)
                L.addRow('Toolbar icons:', self.toolbarIconSize)
                L.addRow(self.NonWinStyle)
                optionsGB = QtWidgets.QGroupBox('Options')
                optionsGB.setLayout(L)

                # Create a main layout
                Layout = QtWidgets.QGridLayout()
                Layout.addWidget(boxGB, 0, 0)
                Layout.addWidget(optionsGB, 0, 1)
                Layout.addWidget(previewGB, 1, 1)
                Layout.setRowStretch(1, 1)
                self.setLayout(Layout)

                # Update the preview things
                self.UpdatePreview()

                self._initial_theme = self.themeBox.currentText()
                self._initial_style = self.NonWinStyle.currentText()
                self._initial_ui_scale = self.uiScale.value()

            def openThemeEditor(self):
                """Create a theme (starting from the selected one) and select it."""
                from .themeeditor import ThemeEditorDialog
                dlg = ThemeEditorDialog(self.themeBox.currentText(), self)
                if dlg.exec_() != QtWidgets.QDialog.Accepted or not dlg.savedName:
                    return
                self.themes = self.getAvailableThemes
                self.themeBox.blockSignals(True)
                self.themeBox.clear()
                for name, themeObj in self.themes:
                    self.themeBox.addItem(name)
                self.themeBox.blockSignals(False)
                index = self.themeBox.findText(dlg.savedName, Qt.MatchFixedString)
                if index >= 0:
                    self.themeBox.setCurrentIndex(index)
                self.UpdatePreview()

            @property
            def getAvailableThemes(self):
                """Searches bundled and user theme folders.
                Automatically adds 'Classic' to the list."""
                themeList = [('Classic', MiyamotoTheme())]
                for themeName in availableThemes():
                    try:
                        theme = MiyamotoTheme(themeName)
                        themeList.append((themeName, theme))
                    except Exception:
                        pass

                return tuple(themeList)

            def UpdatePreview(self):
                """
                Updates the preview and theme box
                """
                theme = self.themeBox.currentText()
                style = self.NonWinStyle.currentText()

                themeObj = MiyamotoTheme(theme)
                keys = QtWidgets.QStyleFactory().keys()

                if themeObj.color('ui') is not None and not themeObj.forceStyleSheet:
                    styles = ["WindowsXP", "WindowsVista"]
                    for _style in styles:
                        for key in _style, _style.lower():
                            if key in keys:
                                keys.remove(key)

                    if style in styles + [_style.lower() for _style in styles]:
                        style = "Fusion"

                self.NonWinStyle.clear()
                self.NonWinStyle.addItems(keys)
                self.NonWinStyle.setCurrentIndex(keys.index(style))

                # Picking a theme drawn for a toolbar icon size (Legacy's 16 px icons) picks that size too
                if (themeObj.toolbarIconSize in TOOLBAR_ICON_SIZES
                        and theme != getattr(self, '_initial_theme', theme)):
                    self.toolbarIconSize.setCurrentIndex(TOOLBAR_ICON_SIZES.index(themeObj.toolbarIconSize))

                for name, themeObj in self.themes:
                    if name == self.themeBox.currentText():
                        t = themeObj
                        self.preview.setPixmap(self.drawPreview(t))
                        text = '<b>[name]</b><br>By [creator]<br>[description]'.replace('[name]', str(t.themeName)).replace('[creator]', str(t.creator)).replace('[description]', str(t.description))
                        self.description.setText(text)

            def drawPreview(self, theme):
                """
                Returns a preview pixmap for the given theme
                """

                tilewidth = 24
                width = int(21.875 * tilewidth)
                height = int(11.5625 * tilewidth)

                # Set up some things
                px = QtGui.QPixmap(width, height)
                px.fill(theme.color('bg'))

                paint = QtGui.QPainter(px)

                font = QtGui.QFont(globals.NumberFont) # need to make a new instance to avoid changing global settings
                font.setPointSize(6)
                paint.setFont(font)

                # Draw the spriteboxes
                paint.setPen(QtGui.QPen(theme.color('spritebox_lines'), 1))
                paint.setBrush(QtGui.QBrush(theme.color('spritebox_fill')))

                paint.drawRoundedRect(11 * tilewidth, 4 * tilewidth, tilewidth, tilewidth, 5, 5)
                paint.drawText(QtCore.QPointF(11.25 * tilewidth, 4.6875 * tilewidth), '38')

                paint.drawRoundedRect(tilewidth, 6 * tilewidth, tilewidth, tilewidth, 5, 5)
                paint.drawText(QtCore.QPointF(1.25 * tilewidth, 6.6875 * tilewidth), '53')

                # Draw the entrance
                paint.setPen(QtGui.QPen(theme.color('entrance_lines'), 1))
                paint.setBrush(QtGui.QBrush(theme.color('entrance_fill')))

                paint.drawRoundedRect(13 * tilewidth, 8 * tilewidth, tilewidth, tilewidth, 5, 5)
                paint.drawText(QtCore.QPointF(13.25 * tilewidth, 8.625 * tilewidth), '0')

                # Draw the location
                paint.setPen(QtGui.QPen(theme.color('location_lines'), 1))
                paint.setBrush(QtGui.QBrush(theme.color('location_fill')))

                paint.drawRect(tilewidth, 9 * tilewidth, 6 * tilewidth, 2 * tilewidth)
                paint.setPen(QtGui.QPen(theme.color('location_text'), 1))
                paint.drawText(QtCore.QPointF(1.25 * tilewidth, 9.625 * tilewidth), '1')

                # Draw the zone
                paint.setPen(QtGui.QPen(theme.color('zone_lines'), 3))
                paint.setBrush(QtGui.QBrush(toQColor(0, 0, 0, 0)))
                paint.drawRect(QtCore.QRectF(8.5 * tilewidth, 3.25 * tilewidth, 16 * tilewidth, 7.5 * tilewidth))
                paint.setPen(QtGui.QPen(theme.color('zone_corner'), 3))
                paint.setBrush(QtGui.QBrush(theme.color('zone_corner'), 3))
                paint.drawRect(QtCore.QRectF(8.4375 * tilewidth, 3.1875 * tilewidth, 0.125 * tilewidth, 0.125 * tilewidth))
                paint.drawRect(QtCore.QRectF(8.4375 * tilewidth, 10.6875 * tilewidth, 0.125 * tilewidth, 0.125 * tilewidth))
                paint.setPen(QtGui.QPen(theme.color('zone_text'), 1))
                font = QtGui.QFont(globals.NumberFont)
                font.setPointSize(round((5 / 16) * tilewidth))
                paint.setFont(font)
                paint.drawText(QtCore.QPointF(8.75 * tilewidth, 3.875 * tilewidth), 'Zone 1')

                # Draw the grid
                paint.setPen(QtGui.QPen(theme.color('grid'), 1, Qt.DotLine))
                gridcoords = [i for i in range(0, width, tilewidth)]
                for i in gridcoords:
                    paint.setPen(QtGui.QPen(theme.color('grid'), 0.75, Qt.DotLine))
                    paint.drawLine(i, 0, i, height)
                    paint.drawLine(0, i, width, i)
                    if not (i / tilewidth) % (tilewidth / 4):
                        paint.setPen(QtGui.QPen(theme.color('grid'), 1.5, Qt.DotLine))
                        paint.drawLine(i, 0, i, height)
                        paint.drawLine(0, i, width, i)

                    if not (i / tilewidth) % (tilewidth / 2):
                        paint.setPen(QtGui.QPen(theme.color('grid'), 2.25, Qt.DotLine))
                        paint.drawLine(i, 0, i, height)
                        paint.drawLine(0, i, width, i)

                # Delete the painter and return the pixmap
                paint.end()
                return px

        return ThemesTab

    def getResourcesTab(self):
        """Returns the Resources tab — download game data and object library with editable install paths."""

        class ResourcesTab(QtWidgets.QWidget):
            info = '<b>Resources</b><br>Download game data and the object library, and manage their install locations.'

            def __init__(self_inner):
                super().__init__()
                from .firstRunWizard import (
                    _DownloadRow, _data_present, _objects_present,
                    DATA_DOWNLOAD_URL, OBJECTS_DOWNLOAD_URL,
                )
                from .verifications import isValidObjectsPath

                cvbox = QtWidgets.QVBoxLayout()
                cvbox.setSpacing(14)
                cvbox.setContentsMargins(4, 4, 4, 4)

                # ── Game Data ────────────────────────────────────────────────
                data_default = os.path.join(globals.user_data_path, 'data')
                data_saved = setting('DataPath', '') or data_default

                self_inner.dataRow = _DownloadRow(
                    title="Game Data",
                    description="Core resources required by Yaz0moto to create levels.",
                    url=DATA_DOWNLOAD_URL,
                    tmp_name="_data_download.zip",
                    extract_dir=data_saved,
                    required=True,
                )
                cvbox.addWidget(self_inner.dataRow)

                data_loc_group = QtWidgets.QGroupBox("Game Data Install Location")
                data_loc_lay = QtWidgets.QVBoxLayout(data_loc_group)
                data_loc_lay.setSpacing(4)

                data_path_row = QtWidgets.QHBoxLayout()
                self_inner.dataPathEdit = QtWidgets.QLineEdit()
                self_inner.dataPathEdit.setText(data_saved)
                data_browse_btn = QtWidgets.QPushButton("Browse…")
                data_browse_btn.setFixedWidth(90)
                data_path_row.addWidget(self_inner.dataPathEdit)
                data_path_row.addWidget(data_browse_btn)
                data_loc_lay.addLayout(data_path_row)

                data_valid_lbl = QtWidgets.QLabel()
                data_valid_lbl.setStyleSheet("font-size: 11px;")
                data_loc_lay.addWidget(data_valid_lbl)
                cvbox.addWidget(data_loc_group)

                def _update_data_status():
                    p = self_inner.dataPathEdit.text().strip()
                    if p and os.path.isdir(p) and os.listdir(p):
                        data_valid_lbl.setText("✓ Data found at this location")
                        data_valid_lbl.setStyleSheet("color: #27ae60; font-size: 11px;")
                    elif p:
                        data_valid_lbl.setText("✗ No data found at this location")
                        data_valid_lbl.setStyleSheet("color: #c0392b; font-size: 11px;")
                    else:
                        data_valid_lbl.setText("")
                    self_inner.dataRow.extract_dir = p or data_default

                self_inner.dataPathEdit.textChanged.connect(_update_data_status)
                _update_data_status()

                def _browse_data():
                    p = QtWidgets.QFileDialog.getExistingDirectory(
                        self_inner, "Select Game Data Folder", self_inner.dataPathEdit.text())
                    if p:
                        self_inner.dataPathEdit.setText(p)
                data_browse_btn.clicked.connect(_browse_data)

                self_inner.dataRow._onFinishedExtra = lambda: (
                    setattr(globals, 'actor_data_path',
                            self_inner.dataPathEdit.text().strip().replace("\\", "/"))
                )

                # ── Object Library ───────────────────────────────────────────
                obj_default = os.path.join(globals.user_data_path, 'Objects')
                obj_saved = setting('ObjPath', '') or obj_default

                self_inner.objRow = _DownloadRow(
                    title="Object Library",
                    description="Add individual objects from the game's tilesets to your level.",
                    url=OBJECTS_DOWNLOAD_URL,
                    tmp_name="_objects_download.zip",
                    extract_dir=obj_saved,
                    required=False,
                )
                cvbox.addWidget(self_inner.objRow)

                obj_loc_group = QtWidgets.QGroupBox("Object Library Install Location")
                obj_loc_lay = QtWidgets.QVBoxLayout(obj_loc_group)
                obj_loc_lay.setSpacing(4)

                obj_path_row = QtWidgets.QHBoxLayout()
                self_inner.objPathEdit = QtWidgets.QLineEdit()
                self_inner.objPathEdit.setText(obj_saved)
                obj_browse_btn = QtWidgets.QPushButton("Browse…")
                obj_browse_btn.setFixedWidth(90)
                obj_path_row.addWidget(self_inner.objPathEdit)
                obj_path_row.addWidget(obj_browse_btn)
                obj_loc_lay.addLayout(obj_path_row)

                obj_valid_lbl = QtWidgets.QLabel()
                obj_valid_lbl.setStyleSheet("font-size: 11px;")
                obj_loc_lay.addWidget(obj_valid_lbl)
                cvbox.addWidget(obj_loc_group)

                def _update_obj_status():
                    p = self_inner.objPathEdit.text().strip()
                    if p and isValidObjectsPath(p):
                        obj_valid_lbl.setText("✓ Objects found at this location")
                        obj_valid_lbl.setStyleSheet("color: #27ae60; font-size: 11px;")
                    elif p:
                        obj_valid_lbl.setText("✗ No valid objects found at this location")
                        obj_valid_lbl.setStyleSheet("color: #c0392b; font-size: 11px;")
                    else:
                        obj_valid_lbl.setText("")
                    self_inner.objRow.extract_dir = p or obj_default

                self_inner.objPathEdit.textChanged.connect(_update_obj_status)
                _update_obj_status()

                def _browse_obj():
                    p = QtWidgets.QFileDialog.getExistingDirectory(
                        self_inner, "Select Object Library Folder", self_inner.objPathEdit.text())
                    if p:
                        self_inner.objPathEdit.setText(p)
                obj_browse_btn.clicked.connect(_browse_obj)

                def _on_obj_downloaded():
                    p = self_inner.objPathEdit.text().strip()
                    if p and isValidObjectsPath(p):
                        setSetting('ObjPath', p)
                self_inner.objRow._onFinishedExtra = _on_obj_downloaded

                cvbox.addStretch(1)
                self_inner.setLayout(cvbox)

                if _data_present():
                    self_inner.dataRow.setAlreadyPresent()
                if _objects_present():
                    self_inner.objRow.setAlreadyPresent()

        return ResourcesTab()


class ClickableLabel(QtWidgets.QLabel):
    """A label that emits clicked() when pressed."""
    clicked = pyqtSignal()

    def __init__(self, text):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ModeSwitch(QtWidgets.QAbstractButton):
    """A sliding on/off toggle switch, drawn with the palette's colors."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(44, 22)

    def sizeHint(self):
        return QtCore.QSize(44, 22)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        pal = self.palette()
        r = self.rect().adjusted(1, 1, -1, -1)
        radius = r.height() / 2

        p.setPen(Qt.NoPen)
        p.setBrush(pal.color(QtGui.QPalette.Highlight) if self.isChecked() else pal.color(QtGui.QPalette.Mid))
        p.drawRoundedRect(QtCore.QRectF(r), radius, radius)

        knob = r.height() - 4
        x = r.right() - knob - 2 if self.isChecked() else r.left() + 2
        p.setBrush(QtGui.QColor(255, 255, 255))
        p.drawEllipse(QtCore.QRectF(x, r.top() + 2, knob, knob))

        if self.hasFocus():
            p.setPen(QtGui.QPen(pal.color(QtGui.QPalette.Highlight), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius + 1, radius + 1)


class WelcomeDialog(QtWidgets.QDialog):
    """
    Shown at startup when no level can be auto-loaded.
    Check .action after exec_(). If ACTION_OPEN_RECENT, .recent_path holds the file.
    """

    ACTION_OPEN_FILE   = 'open_file'
    ACTION_OPEN_NAME   = 'open_name'
    ACTION_NEW_LEVEL   = 'new_level'
    ACTION_OPEN_RECENT = 'open_recent'

    def __init__(self):
        super().__init__()
        self.action = None
        self.recent_path = None

        self.setWindowTitle('Yaz0moto')
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        import platform as _platform
        icon_name = 'yaz0moto1024mac.png' if _platform.system() == 'Darwin' else 'yaz0moto1024.png'
        icon_path = os.path.join(globals.miyamoto_path, 'yaz0data', 'app_icons', icon_name)
        if os.path.isfile(icon_path):
            self.setWindowIcon(QtGui.QIcon(icon_path))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 20)
        layout.setSpacing(0)

        # Logo (click the star!)
        if os.path.isfile(icon_path):
            from .welcomestar import AnimatedStarLogo
            self.logo = AnimatedStarLogo(icon_path, 108)
            layout.addWidget(self.logo, 0, Qt.AlignHCenter)
            layout.addSpacing(14)

        # Heading
        heading = QtWidgets.QLabel('Welcome to Yaz0moto')
        heading.setAlignment(Qt.AlignHCenter)
        hf = heading.font()
        hf.setPointSize(hf.pointSize() + 5)
        hf.setBold(True)
        heading.setFont(hf)
        layout.addWidget(heading)
        layout.addSpacing(6)

        # Subtitle
        sub = QtWidgets.QLabel('Open an existing level or start fresh.')
        sub.setAlignment(Qt.AlignHCenter)
        sub.setStyleSheet('color: palette(mid);')
        layout.addWidget(sub)
        layout.addSpacing(14)

        # Wii U / Deluxe mode switch (off = Wii U, on = Deluxe)
        modeRow = QtWidgets.QHBoxLayout()
        modeRow.setSpacing(10)
        modeRow.addStretch(1)
        self._modeSwitch = ModeSwitch()
        self._modeSwitch.setChecked(bool(globals.IsNSMBUDX))
        self._wiiuLabel = ClickableLabel('Wii U')
        self._wiiuLabel.setToolTip('Edit New Super Mario Bros. U (Wii U) levels.')
        self._wiiuLabel.clicked.connect(lambda: self._modeSwitch.setChecked(False))
        self._deluxeLabel = ClickableLabel('Deluxe')
        self._deluxeLabel.setToolTip('Edit New Super Mario Bros. U Deluxe (Switch) levels.')
        self._deluxeLabel.clicked.connect(lambda: self._modeSwitch.setChecked(True))
        modeRow.addWidget(self._wiiuLabel)
        modeRow.addWidget(self._modeSwitch)
        modeRow.addWidget(self._deluxeLabel)
        modeRow.addStretch(1)
        self._updateModeLabels()
        self._modeSwitch.toggled.connect(self._toggleDeluxe)
        layout.addLayout(modeRow)
        layout.addSpacing(14)

        # Action buttons
        self._openNameBtn = None
        for label, action in (
            ('New Level',           self.ACTION_NEW_LEVEL),
            ('Open Level by Name…', self.ACTION_OPEN_NAME),
            ('Open Level by File…', self.ACTION_OPEN_FILE),
        ):
            btn = QtWidgets.QPushButton(label)
            btn.setFixedHeight(36)
            btn.clicked.connect(lambda _checked, a=action: self._choose(a))
            if action == self.ACTION_OPEN_NAME:
                self._openNameBtn = btn
            layout.addWidget(btn)
            layout.addSpacing(6)
        self._updateOpenNameBtn()

        # Recent files section
        recent_entries = globals.mainWindow.RecentMenu.getEntries() if globals.mainWindow else []
        self._recentList = None
        self._clearBtn = None

        if recent_entries:
            layout.addSpacing(10)

            sep = QtWidgets.QFrame()
            sep.setFrameShape(QtWidgets.QFrame.HLine)
            sep.setFrameShadow(QtWidgets.QFrame.Sunken)
            layout.addWidget(sep)
            layout.addSpacing(10)

            rec_hdr = QtWidgets.QLabel('Recent Files')
            hdr_font = rec_hdr.font()
            hdr_font.setPointSize(hdr_font.pointSize() - 1)
            hdr_font.setBold(True)
            rec_hdr.setFont(hdr_font)
            rec_hdr.setStyleSheet('color: palette(mid);')
            layout.addWidget(rec_hdr)
            layout.addSpacing(6)

            lst = QtWidgets.QListWidget()
            lst.setFrameShape(QtWidgets.QFrame.NoFrame)
            lst.setFocusPolicy(Qt.NoFocus)
            lst.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            lst.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
            lst.setSpacing(1)
            for rec_label, rec_path in recent_entries:
                item = QtWidgets.QListWidgetItem(rec_label)
                item.setToolTip(rec_path)
                item.setData(Qt.UserRole, rec_path)
                lst.addItem(item)
            lst.setMaximumHeight(min(len(recent_entries), 6) * 26 + 4)
            lst.itemActivated.connect(self._openRecent)
            lst.itemClicked.connect(self._openRecent)
            self._recentList = lst
            layout.addWidget(lst)
            layout.addSpacing(6)

            clear_btn = QtWidgets.QPushButton('Clear Recent Files')
            clear_btn.setFixedHeight(28)
            clear_btn.clicked.connect(self._clearRecent)
            self._clearBtn = clear_btn
            layout.addWidget(clear_btn)

        layout.addStretch(1)

        self.adjustSize()
        self.setFixedSize(440, self.sizeHint().height())

    def _choose(self, action):
        self.action = action
        self.accept()

    def _updateOpenNameBtn(self):
        has_sources = hasLevelNameSources()
        self._openNameBtn.setEnabled(has_sources)
        self._openNameBtn.setToolTip('' if has_sources else 'No game path configured. Set one in Interactive Setup first.')

    def _updateModeLabels(self):
        """Bolds the label of the active mode and dims the other one."""
        isDX = self._modeSwitch.isChecked()
        for label, active in ((self._wiiuLabel, not isDX), (self._deluxeLabel, isDX)):
            f = label.font()
            f.setBold(active)
            label.setFont(f)
            label.setStyleSheet('' if active else 'color: palette(mid);')

    def _toggleDeluxe(self, isDX):
        """Switches between the Deluxe and Wii U base games, keeping the active mods."""
        self._updateModeLabels()
        from . import loading
        mods = setting('LastMods') or []
        if isinstance(mods, str):
            mods = [mods]
        base = loading.ResolveBaseGameForDeluxe(isDX)
        setSetting('isDX', bool(isDX))

        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            loading.LoadGameDef(base, mods, dlg=True)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        if globals.mainWindow:
            globals.mainWindow.updateOpenByNameState()
        self._updateOpenNameBtn()

    def _openRecent(self, item):
        path = item.data(Qt.UserRole)
        if path:
            self.recent_path = path
            self.action = self.ACTION_OPEN_RECENT
            self.accept()

    def _clearRecent(self):
        if globals.mainWindow:
            globals.mainWindow.RecentMenu.clearAll()
        if self._recentList:
            self._recentList.clear()
        if self._clearBtn:
            self._clearBtn.setVisible(False)
        # Resize dialog to remove the now-empty recent section
        self.adjustSize()
        self.setFixedSize(440, self.sizeHint().height())


class ChooseLevelNameDialog(QtWidgets.QDialog):
    """
    Dialog to open a level by name.  A dropdown lists all base games with configured paths
    plus active mods that provide level names or have levels in their game path.  Selecting
    a game entry shows a Copy Level to Mod button; selecting a user-patch mod entry shows an
    Edit Level Info button.  The last-used source is persisted across sessions.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Choose Level')
        self.setWindowIcon(GetIcon('open'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.currentlevel = None
        self.current_game_path = None
        self.current_display_name = None
        self.current_tab_name = None

        # Per-source parallel data
        self._source_game_paths = []
        self._source_user_patches = []
        self._source_keys = []
        self._source_is_game = []

        # Source selector dropdown
        self._source_combo = QtWidgets.QComboBox()
        self._source_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        # Stacked content area — one tree widget per source
        self._stack = QtWidgets.QStackedWidget()

        select_idx = self._buildEntries()

        # Level name search bar
        self._search = QtWidgets.QLineEdit()
        self._search.textChanged.connect(self._updateSearch)
        self._search.setPlaceholderText("Search")

        searchLayout = QtWidgets.QHBoxLayout()
        searchLayout.addWidget(self._search)

        # "Ok" and "Cancel" buttons
        self.buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        # "Edit Level Info" icon button — visible only for user-patch mod sources
        self._rename_btn = QtWidgets.QPushButton(GetIcon('info'), '')
        self._rename_btn.setFixedSize(26, 26)
        self._rename_btn.setIconSize(QtCore.QSize(15, 15))
        self._rename_btn.setToolTip('Edit Level Info')
        self._rename_btn.setEnabled(False)
        self._rename_btn.setVisible(False)
        self._rename_btn.clicked.connect(self._doEditLevelInfo)

        # "Edit Worlds" icon button — visible for user-patch mod sources, always enabled
        self._worlds_btn = QtWidgets.QPushButton(GetIcon('layer'), '')
        self._worlds_btn.setFixedSize(26, 26)
        self._worlds_btn.setIconSize(QtCore.QSize(15, 15))
        self._worlds_btn.setToolTip('Edit Worlds')
        self._worlds_btn.setEnabled(False)
        self._worlds_btn.setVisible(False)
        self._worlds_btn.clicked.connect(self._doEditWorlds)

        # "Copy Level to Mod" icon button — visible only for game sources
        self._copy_btn = QtWidgets.QPushButton(GetIcon('copy'), '')
        self._copy_btn.setFixedSize(26, 26)
        self._copy_btn.setIconSize(QtCore.QSize(15, 15))
        self._copy_btn.setToolTip("Copy Level to Mod")
        self._copy_btn.setEnabled(False)
        self._copy_btn.setVisible(False)
        self._copy_btn.clicked.connect(self._doCopyToMod)

        self._source_combo.currentIndexChanged.connect(self._onSourceChanged)

        # Button layout
        buttonLayout = QtWidgets.QHBoxLayout()
        buttonLayout.addWidget(self._rename_btn)
        buttonLayout.addWidget(self._worlds_btn)
        buttonLayout.addWidget(self._copy_btn)
        buttonLayout.addStretch()
        buttonLayout.addWidget(self.buttonBox)

        # Main layout
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self._source_combo)
        layout.addLayout(searchLayout)
        layout.addWidget(self._stack)
        layout.addLayout(buttonLayout)
        self.setLayout(layout)
        self.setMinimumWidth(360)
        self.setMinimumHeight(450)
        self._search.setFocus()

        # Restore last-used source, then sync UI state
        if select_idx != self._source_combo.currentIndex():
            self._source_combo.setCurrentIndex(select_idx)
        self._onSourceChanged(self._source_combo.currentIndex())

    # ── Entry builder ──────────────────────────────────────────────────────
    def _buildEntries(self):
        """Populate source combo + stack from all configured games and active mods.
        Returns the index to pre-select (from LastOpenLevelSource)."""
        from . import gamedefs as _gd
        from .loading import LoadLevelNamesForDef

        active_mods = setting('LastMods') or []
        if isinstance(active_mods, str):
            active_mods = [active_mods]

        # entries: (key, label, names_list, game_path, user_patch_folder_or_None, is_game)
        entries = []

        # ── All base games that have a non-empty game path ──────────────────
        for def_, folder in _gd.getAvailableBaseGames():
            game_path = def_.GetGamePath()
            if not game_path:
                continue
            names = LoadLevelNamesForDef(def_)
            if not names:
                names = self._scanGamePathForLevels(game_path)
            else:
                names = self._supplementUnlisted(names, game_path)
            if names:
                entries.append((folder, def_.name, names, game_path, None, True))

        # ── Active mods with level data ─────────────────────────────────────
        _user_patches_dir = os.path.join(globals.user_data_path, 'patches')
        for mod_folder in active_mods:
            if not mod_folder:
                continue
            mod_def = _gd.MiyamotoGameDefinition(mod_folder, source='mod')
            if not mod_def.custom:
                continue
            mod_gpath = mod_def.GetGamePath()
            mod_names = self._loadNamesForMod(mod_def, mod_gpath)
            if not mod_names:
                continue
            is_user = os.path.isfile(
                os.path.join(_user_patches_dir, mod_folder, 'main.xml'))
            key = 'mod:' + mod_folder
            entries.append((key, mod_def.name, mod_names, mod_gpath,
                            mod_folder if is_user else None, False))

        del _gd

        if not entries:
            gpath = globals.gamedef.GetGamePath() if globals.gamedef else ''
            entries.append(('fallback', 'Levels', globals.LevelNames or [], gpath, None, True))

        # Determine which entry to restore
        last_source = setting('LastOpenLevelSource', '')
        select_idx = 0
        for i, (key, *_rest) in enumerate(entries):
            if key == last_source:
                select_idx = i
                break

        for key, label, names, gpath, user_patch, is_game in entries:
            tree = self._makeTree(names, gpath, user_patch)
            self._stack.addWidget(tree)
            self._source_combo.addItem(label)
            self._source_game_paths.append(gpath)
            self._source_user_patches.append(user_patch)
            self._source_keys.append(key)
            self._source_is_game.append(is_game)

        return select_idx

    # ── Tree builder ───────────────────────────────────────────────────────
    def _makeTree(self, names, game_path='', user_patch_folder=None):
        tree = QtWidgets.QTreeWidget()
        tree.setColumnCount(1)
        tree.setHeaderHidden(True)
        tree.setIndentation(16)
        tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        tree.currentItemChanged.connect(self._onItemChange)
        tree.itemSelectionChanged.connect(self._updateActionBtns)
        tree.itemActivated.connect(self._onItemActivated)
        tree.addTopLevelItems(self._parseCategory(names, game_path))

        return tree

    def _parseCategory(self, items, game_path=''):
        nodes = []
        for item in items:
            node = QtWidgets.QTreeWidgetItem()
            node.setText(0, item[0])
            if isinstance(item[1], str):
                code = item[1]
                # Tooltip shows the full filename, checking which extension exists
                if game_path:
                    ext = next(
                        (e for e in ('.szs', '.sarc')
                         if os.path.isfile(os.path.join(game_path, code + e))),
                        '.szs')
                else:
                    ext = '.szs'
                node.setData(0, Qt.UserRole, code)
                node.setToolTip(0, code + ext)
            else:
                for child in self._parseCategory(item[1], game_path):
                    node.addChild(child)
                node.setToolTip(0, item[0])
            nodes.append(node)
        return tuple(nodes)

    # ── Update search term ─────────────────────────────────────────────────
    def _updateSearch(self, text):
        idx = self._source_combo.currentIndex()
        tree = self._stack.widget(idx)
        tree.setCurrentItem(None)
        
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            self._filterItem(item, text)

        self._onItemChange(tree.currentItem(), None)

    def _filterItem(self, item, text):
        import re

        def normalize(s):
            return re.sub(r'[–—_\s]+', ' ', s).replace("'", '').strip().lower()

        visible = False

        if item.childCount():
            for i in range(item.childCount()):
                child = item.child(i)
                if self._filterItem(child, text):
                    visible = True

            item.setExpanded(visible and normalize(text) != '')
        else:
            terms = [t for t in normalize(text).split() if t]
            item_text = [
                normalize(item.text(0)),
                item.toolTip(0)
            ]

            aliases = {
                "-13": ["-secret", "-blooper", "-cheepcheep"],
                "-14": ["-secret", "-iceblock", "-firepiranhaplant", "-piranhaplant"],
                "-15": ["-secret", "-leaf", "-beanstalkleaf"],
                "-16": ["-secret", "-fliprus"],
                "-17": ["-secret", "-parabeetles", "-para-beetles"],
                "-20": ["-ghosthouse", "-gh"],
                "-21": ["-tower"],
                "-22": ["-tower2", "-t2"],
                "-23": ["-castle"],
                "-42": ["-peachscastle", "-castle"],
                "-43": ["-peachscastle2", "-castle2", "-c2"],
                "11-": ["coin-", "c-"]
            }
            
            for key, value in aliases.items():
                if key in item.data(0, Qt.UserRole):
                    for alias in value:
                        item_text.append(re.sub(key, alias, item.data(0, Qt.UserRole)))

            visible = not terms or all(term in ' '.join(item_text) for term in terms)
            tree = item.treeWidget()

            if visible and normalize(text) != '' and tree.currentItem() is None:
                tree.setCurrentItem(item)

        item.setHidden(not visible)

        return visible

    # ── Unnamed level discovery ────────────────────────────────────────────
    @staticmethod
    def _supplementUnlisted(names, game_path):
        """Return names plus an 'Uncategorized' entry for every level file in game_path that
        no category lists (e.g. Deluxe ships 100+ levels that the name list doesn't cover)."""
        import copy
        names = copy.deepcopy(names)
        if not game_path or not os.path.isdir(game_path):
            return names

        covered = set()
        def _collect(items):
            for it in items:
                if isinstance(it[1], str):
                    covered.add(it[1])
                else:
                    _collect(it[1])
        _collect(names)

        import re
        def _natural(f):
            return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', f)]

        extra = []
        for fname in sorted(os.listdir(game_path), key=_natural):
            for ext in ('.szs', '.sarc'):
                if fname.lower().endswith(ext):
                    code = fname[:-len(ext)]
                    if code not in covered:
                        extra.append([code, code])
                    break

        if extra:
            uncat = next((n for n in names if n[0] == 'Uncategorized'), None)
            if uncat is not None:
                uncat[1] = uncat[1] + extra
            else:
                names.append(['Uncategorized', extra])

        return names

    @staticmethod
    def _scanGamePathForLevels(game_path):
        """Scan a game path directory for .szs/.sarc files, returns synthetic names list."""
        if not game_path or not os.path.isdir(game_path):
            return []
        files = []
        for fname in sorted(os.listdir(game_path)):
            for ext in ('.szs', '.sarc'):
                if fname.lower().endswith(ext):
                    files.append([fname, fname[:-len(ext)]])  # display full filename, code is stem
                    break
        return [['Uncategorized', files]] if files else []

    @staticmethod
    def _loadNamesForMod(mod_def, game_path):
        """Load level names from the mod's levelnames.xml and supplement with any
        game-path files not already listed in a category (shown as 'Uncategorized')."""
        from .loading import LoadLevelNamesForDef, LoadLevelNames_Category
        import xml.etree.ElementTree as _ET

        names = LoadLevelNamesForDef(mod_def)

        # User-created mods don't declare levelnames in main.xml, so fall back to
        # reading levelnames.xml directly from the user patch directory.
        if not names and getattr(mod_def, 'gamepath', None):
            from . import globals as _gl
            direct_ln = os.path.join(
                _gl.user_data_path, 'patches', mod_def.gamepath, 'levelnames.xml')
            if os.path.isfile(direct_ln):
                try:
                    names = LoadLevelNames_Category(_ET.parse(direct_ln).getroot())
                except Exception:
                    pass

        if game_path and os.path.isdir(game_path):
            covered = set()
            def _collect(items):
                for it in items:
                    if isinstance(it[1], str):
                        covered.add(it[1])
                    else:
                        _collect(it[1])
            _collect(names)

            extra = []
            for fname in sorted(os.listdir(game_path)):
                for ext in ('.szs', '.sarc'):
                    if fname.lower().endswith(ext):
                        code = fname[:-len(ext)]
                        if code not in covered:
                            extra.append([fname, code])
                        break
            if extra:
                uncat = next((n for n in names if n[0] == 'Uncategorized'), None)
                if uncat is not None:
                    uncat[1] = uncat[1] + extra
                else:
                    names = names + [['Uncategorized', extra]]

        return names

    # ── Edit Level Info (user patches only) ───────────────────────────────
    def _doEditLevelInfo(self):
        """Show the Edit Level Info dialog for selected level(s)."""
        idx = self._source_combo.currentIndex()
        if idx >= len(self._source_user_patches):
            return
        user_patch_folder = self._source_user_patches[idx]
        if user_patch_folder is None:
            return
        tree = self._stack.widget(idx)
        if not isinstance(tree, QtWidgets.QTreeWidget):
            return

        selected = [it for it in tree.selectedItems()
                    if it.data(0, Qt.UserRole) is not None]
        if not selected:
            return

        from .patchxml import PatchXmlEditor
        user_patch_dir = os.path.join(globals.user_data_path, 'patches', user_patch_folder)
        editor = PatchXmlEditor(user_patch_dir)
        worlds = editor.get_worlds()
        gpath = self._source_game_paths[idx] if idx < len(self._source_game_paths) else ''

        def _world_combo():
            combo = QtWidgets.QComboBox()
            combo.addItem('— Uncategorized —', userData=None)
            for w in worlds:
                combo.addItem(w, userData=w)
            return combo

        def _apply_world(combo, items):
            new_world = combo.currentData()
            for it in items:
                code = it.data(0, Qt.UserRole)
                if new_world is None:
                    editor.remove_level(code)
                else:
                    existing_name = editor.get_level_name(code) or code
                    editor.set_level_info(code, existing_name, new_world)

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle('Edit Level Info')
        dlg.setMinimumWidth(320)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setSpacing(8)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        name_edit = None
        if len(selected) == 1:
            item = selected[0]
            code = item.data(0, Qt.UserRole)
            current_name = editor.get_level_name(code) or ''

            filename = code
            for _ext in ('.szs', '.sarc'):
                if gpath and os.path.isfile(os.path.join(gpath, code + _ext)):
                    filename = code + _ext
                    break

            form.addRow('File:', QtWidgets.QLabel(f'<code>{filename}</code>'))
            name_edit = QtWidgets.QLineEdit(current_name)
            name_edit.setPlaceholderText('Display name…')
            form.addRow('Display name:', name_edit)
        else:
            form.addRow('Levels:', QtWidgets.QLabel(f'<b>{len(selected)}</b> selected'))

        world_combo = _world_combo()
        if len(selected) == 1:
            current_world = editor.get_level_world(code)
            if current_world and current_world in worlds:
                world_combo.setCurrentText(current_world)
        form.addRow('World:', world_combo)

        lay.addLayout(form)

        notice_text = ('The level filename will remain unchanged.'
                       if len(selected) == 1 else 'Level names will not be changed.')
        notice = QtWidgets.QLabel(notice_text)
        notice.setStyleSheet('color: palette(mid); font-size: 11px;')
        lay.addWidget(notice)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return

        if len(selected) == 1:
            new_world = world_combo.currentData()
            if new_world is None:
                editor.remove_level(code)
            else:
                editor.set_level_info(code, name_edit.text().strip() or code, new_world)
        else:
            _apply_world(world_combo, selected)

        self._refreshCurrentSource()

    # ── Selection signals ──────────────────────────────────────────────────
    def _onSourceChanged(self, index):
        self.currentlevel = None
        self.current_display_name = None
        self.current_game_path = (self._source_game_paths[index]
                                  if index < len(self._source_game_paths) else '')
        self.current_tab_name = (self._source_combo.itemText(index)
                                 if index >= 0 else '')
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)
        self._updateSearch(self._search.text())
        self._updateActionBtns()

    def _onItemChange(self, current, _previous):
        if current is None:
            self.currentlevel = None
            self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
            self._updateActionBtns()
            return
        self.currentlevel = current.data(0, Qt.UserRole)
        idx = self._source_combo.currentIndex()
        self.current_game_path = (self._source_game_paths[idx]
                                  if idx < len(self._source_game_paths) else '')
        self.current_tab_name = (self._source_combo.itemText(idx) if idx >= 0 else '')
        self.current_display_name = current.text(0)
        ok = self.currentlevel is not None
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(ok)
        if ok:
            self.currentlevel = str(self.currentlevel)
        self._updateActionBtns()

    def _updateActionBtns(self):
        idx = self._source_combo.currentIndex()
        is_user_patch = (idx < len(self._source_user_patches)
                         and self._source_user_patches[idx] is not None)
        is_game = (idx < len(self._source_is_game) and self._source_is_game[idx])

        # "Edit Level Info" — user-patch mod sources only, requires 1+ levels selected
        self._rename_btn.setVisible(is_user_patch)
        if is_user_patch:
            tree = self._stack.widget(idx)
            if isinstance(tree, QtWidgets.QTreeWidget):
                sel_levels = [it for it in tree.selectedItems()
                              if it.data(0, Qt.UserRole) is not None]
            else:
                sel_levels = []
            self._rename_btn.setEnabled(len(sel_levels) > 0)

        # "Edit Worlds" — user-patch mod sources only, always enabled
        self._worlds_btn.setVisible(is_user_patch)
        self._worlds_btn.setEnabled(is_user_patch)

        # "Copy Level to Mod" — game sources only
        self._copy_btn.setVisible(is_game)
        if is_game:
            self._copy_btn.setEnabled(
                self.currentlevel is not None and bool(self.current_game_path))

    # ── Edit Worlds (user patches only) ───────────────────────────────────
    def _doEditWorlds(self):
        """Show the Edit Worlds dialog for the current user-patch source."""
        idx = self._source_combo.currentIndex()
        if idx >= len(self._source_user_patches):
            return
        user_patch_folder = self._source_user_patches[idx]
        if user_patch_folder is None:
            return

        from .patchxml import PatchXmlEditor
        user_patch_dir = os.path.join(globals.user_data_path, 'patches', user_patch_folder)
        editor = PatchXmlEditor(user_patch_dir)
        original_worlds = editor.get_worlds()

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle('Edit Worlds')
        dlg.setMinimumWidth(360)
        dlg.setMinimumHeight(300)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setSpacing(8)

        hint = QtWidgets.QLabel('Double-click a world to rename it.')
        hint.setStyleSheet('color: palette(mid); font-size: 11px;')
        lay.addWidget(hint)

        _LOCKED = '_locked_uncategorized'

        list_w = QtWidgets.QListWidget()
        list_w.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        list_w.setDefaultDropAction(Qt.MoveAction)
        for name in original_worlds:
            if name == 'Uncategorized':
                continue  # rendered as locked row below
            it = QtWidgets.QListWidgetItem(name)
            it.setData(Qt.UserRole, name)
            it.setFlags(it.flags() | Qt.ItemIsEditable)
            list_w.addItem(it)

        # Locked "Uncategorized" row — always last, never editable/draggable
        uncat_it = QtWidgets.QListWidgetItem('Uncategorized')
        uncat_it.setData(Qt.UserRole, _LOCKED)
        uncat_it.setFlags(
            (uncat_it.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsDragEnabled))
        _font = uncat_it.font()
        _font.setItalic(True)
        uncat_it.setFont(_font)
        uncat_it.setForeground(QtGui.QColor('gray'))
        list_w.addItem(uncat_it)

        lay.addWidget(list_w)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(4)
        add_btn    = QtWidgets.QPushButton(GetIcon('add'), '')
        remove_btn = QtWidgets.QPushButton(GetIcon('delete'), '')
        up_btn     = QtWidgets.QPushButton('▲')
        down_btn   = QtWidgets.QPushButton('▼')
        for b in (add_btn, remove_btn):
            b.setFixedSize(26, 26)
            b.setIconSize(QtCore.QSize(14, 14))
        add_btn.setToolTip('Add World')
        remove_btn.setToolTip('Remove selected world')
        up_btn.setFixedWidth(30)
        down_btn.setFixedWidth(30)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(up_btn)
        btn_row.addWidget(down_btn)
        lay.addLayout(btn_row)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Sunken)
        lay.addWidget(sep)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        def _is_locked(it):
            return it is not None and it.data(Qt.UserRole) == _LOCKED

        def _update_btns():
            it = list_w.currentItem()
            locked = _is_locked(it)
            remove_btn.setEnabled(it is not None and not locked)
            up_btn.setEnabled(it is not None and not locked and list_w.currentRow() > 0)
            down_btn.setEnabled(it is not None and not locked
                                and list_w.currentRow() < list_w.count() - 2)

        list_w.currentItemChanged.connect(lambda *_: _update_btns())
        _update_btns()

        def _add():
            new_name, ok = QtWidgets.QInputDialog.getText(dlg, 'Add World', 'World name:')
            if not ok or not new_name.strip():
                return
            # Insert before the locked Uncategorized row
            it = QtWidgets.QListWidgetItem(new_name.strip())
            it.setData(Qt.UserRole, None)
            it.setFlags(it.flags() | Qt.ItemIsEditable)
            list_w.insertItem(list_w.count() - 1, it)
            list_w.setCurrentItem(it)

        def _remove():
            row = list_w.currentRow()
            it = list_w.item(row)
            if row >= 0 and not _is_locked(it):
                list_w.takeItem(row)

        def _move_up():
            row = list_w.currentRow()
            it = list_w.item(row)
            if row > 0 and not _is_locked(it):
                it = list_w.takeItem(row)
                list_w.insertItem(row - 1, it)
                list_w.setCurrentRow(row - 1)

        def _move_down():
            row = list_w.currentRow()
            it = list_w.item(row)
            # Stop before Uncategorized (always last)
            if 0 <= row < list_w.count() - 2 and not _is_locked(it):
                it = list_w.takeItem(row)
                list_w.insertItem(row + 1, it)
                list_w.setCurrentRow(row + 1)

        add_btn.clicked.connect(_add)
        remove_btn.clicked.connect(_remove)
        up_btn.clicked.connect(_move_up)
        down_btn.clicked.connect(_move_down)

        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return

        edits = []
        for i in range(list_w.count()):
            it = list_w.item(i)
            if _is_locked(it):
                continue
            new_name = it.text().strip()
            if new_name:
                edits.append((it.data(Qt.UserRole), new_name))

        editor.apply_world_edits(edits)
        self._refreshCurrentSource()

    def _refreshCurrentSource(self):
        """Rebuild the tree widget for the currently selected source."""
        from . import gamedefs as _gd

        idx = self._source_combo.currentIndex()
        if not (0 <= idx < len(self._source_keys)):
            return

        key = self._source_keys[idx]
        gpath = self._source_game_paths[idx]
        user_patch = self._source_user_patches[idx]

        if key.startswith('mod:'):
            mod_folder = key[4:]
            def_ = _gd.MiyamotoGameDefinition(mod_folder, source='mod')
            names = self._loadNamesForMod(def_, gpath)
        else:
            from .loading import LoadLevelNamesForDef
            def_ = _gd.MiyamotoGameDefinition(key, source='game')
            names = LoadLevelNamesForDef(def_)
            if not names:
                names = self._scanGamePathForLevels(gpath)

        new_tree = self._makeTree(names or [], gpath, user_patch)
        old_widget = self._stack.widget(idx)
        self._stack.removeWidget(old_widget)
        self._stack.insertWidget(idx, new_tree)
        self._stack.setCurrentIndex(idx)
        if old_widget:
            old_widget.deleteLater()

        self.currentlevel = None
        self.current_display_name = None
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        self._updateActionBtns()

    def _onItemActivated(self, item, _column):
        self.currentlevel = item.data(0, Qt.UserRole)
        if self.currentlevel is not None:
            self.currentlevel = str(self.currentlevel)
            idx = self._source_combo.currentIndex()
            self.current_game_path = (self._source_game_paths[idx]
                                      if idx < len(self._source_game_paths) else '')
            self.accept()

    # ── Copy level to mod ──────────────────────────────────────────────────
    def _doCopyToMod(self):
        """Copy the selected game level file into a mod's configured game path."""
        if not self.currentlevel or not self.current_game_path:
            return

        active_mods = setting('LastMods') or []
        if isinstance(active_mods, str):
            active_mods = [active_mods]

        from . import gamedefs as _gd
        usable = []  # (display_name, folder, dest_dir)
        for folder in active_mods:
            if not folder:
                continue
            mod_def = _gd.MiyamotoGameDefinition(folder, source='mod')
            if not mod_def.custom:
                continue
            mod_path = mod_def.GetGamePath()
            if mod_path and os.path.isdir(mod_path):
                usable.append((mod_def.name, folder, mod_path))
        del _gd

        if not usable:
            has_any_mods = any(m for m in active_mods if m)
            if has_any_mods:
                msg = ('Your active mods do not have a game path configured.\n'
                       'Open Game Setup and set a game path for your mod first.')
            else:
                msg = 'No mods installed! Use Game Setup to create one.'
            QtWidgets.QMessageBox.information(self, 'Copy Level to Mod', msg)
            return

        # Show mod-selection dialog
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle('Copy Level to Mod')
        dlg.setMinimumWidth(340)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setSpacing(10)

        lbl = QtWidgets.QLabel(f'Copy <b>{self.currentlevel}</b> to which mod?')
        lay.addWidget(lbl)

        mod_combo = QtWidgets.QComboBox()
        for name, folder, _ in usable:
            mod_combo.addItem(name, folder)
        lay.addWidget(mod_combo)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
        copy_btn = btns.addButton('Copy', QtWidgets.QDialogButtonBox.AcceptRole)
        copy_btn.setDefault(True)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return

        sel_folder = mod_combo.currentData()
        sel_entry = next((m for m in usable if m[1] == sel_folder), None)
        if not sel_entry:
            return
        dest_dir = sel_entry[2]

        # Find the source file (try .szs then .sarc)
        code = self.currentlevel
        game_path = self.current_game_path
        ext = next(
            (e for e in ('.szs', '.sarc')
             if os.path.isfile(os.path.join(game_path, code + e))),
            None)
        if ext is None:
            QtWidgets.QMessageBox.warning(
                self, 'Copy Level to Mod',
                f'Level file not found in game path:\n{code}')
            return

        src = os.path.join(game_path, code + ext)
        dest = os.path.join(dest_dir, code + ext)

        if os.path.exists(dest):
            conf = QtWidgets.QDialog(self)
            conf.setWindowTitle('Copy Level to Mod')
            conf_lay = QtWidgets.QVBoxLayout(conf)
            conf_lay.setSpacing(12)
            conf_lay.addWidget(QtWidgets.QLabel(
                f'<b>{code + ext}</b> already exists in the mod\'s game path.'))
            conf_btns = QtWidgets.QDialogButtonBox()
            overwrite_btn = conf_btns.addButton('Overwrite', QtWidgets.QDialogButtonBox.AcceptRole)
            keep_btn      = conf_btns.addButton('Keep Both',  QtWidgets.QDialogButtonBox.ActionRole)
            cancel_btn    = conf_btns.addButton('Cancel',     QtWidgets.QDialogButtonBox.RejectRole)
            _choice = [None]
            overwrite_btn.clicked.connect(lambda: (_choice.__setitem__(0, 'overwrite'), conf.accept()))
            keep_btn.clicked.connect(     lambda: (_choice.__setitem__(0, 'keep'),      conf.accept()))
            cancel_btn.clicked.connect(conf.reject)
            conf_lay.addWidget(conf_btns)
            if conf.exec_() != QtWidgets.QDialog.Accepted or _choice[0] is None:
                return
            if _choice[0] == 'keep':
                n = 1
                while True:
                    candidate = os.path.join(dest_dir, f'{code} ({n}){ext}')
                    if not os.path.exists(candidate):
                        dest = candidate
                        break
                    n += 1

        import shutil
        try:
            shutil.copy2(src, dest)
            QtWidgets.QMessageBox.information(
                self, 'Copy Level to Mod',
                f'Copied successfully to:\n{dest}')
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, 'Copy Level to Mod',
                f'Failed to copy level:\n{e}')

    def accept(self):
        idx = self._source_combo.currentIndex()
        if 0 <= idx < len(self._source_keys):
            setSetting('LastOpenLevelSource', self._source_keys[idx])
        super().accept()

    # Legacy aliases
    def ParseCategory(self, items):
        return self._parseCategory(items)

    def HandleItemChange(self, current, previous):
        self._onItemChange(current, previous)

    def HandleItemActivated(self, item, column):
        self._onItemActivated(item, column)


class SpritemapDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Sprite Map Viewer')
        self.setWindowIcon(GetIcon('folderpath'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumSize(480, 360)
        self.resize(560, 480)

        layout = QtWidgets.QVBoxLayout(self)

        self.label = QtWidgets.QLabel()
        layout.addWidget(self.label)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(['#', 'Hex ID', 'String ID'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table)

        self.emptyLabel = QtWidgets.QLabel('No spritemap data available.\nOpen a level to view its sprite map.')
        self.emptyLabel.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.emptyLabel)

        buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close | QtWidgets.QDialogButtonBox.Reset)
        reloadBtn = buttonBox.button(QtWidgets.QDialogButtonBox.Reset)
        reloadBtn.setText('Reload')
        reloadBtn.setIcon(GetIcon('reload'))
        buttonBox.rejected.connect(self.reject)
        buttonBox.clicked.connect(lambda btn: self.refreshTable() if buttonBox.buttonRole(btn) == QtWidgets.QDialogButtonBox.ResetRole else None)
        layout.addWidget(buttonBox)

        self.refreshTable()

    def refreshTable(self):
        id_manager = getattr(globals.Level, 'id_manager', None) if hasattr(globals, 'Level') else None
        has_data = id_manager is not None and bool(id_manager.string_to_int)

        self.table.setVisible(has_data)
        self.label.setVisible(has_data)
        self.emptyLabel.setVisible(not has_data)

        if has_data:
            sorted_items = sorted(id_manager.int_to_string.items(), key=lambda x: x[0])
            self.label.setText(f'Spritemap contains {len(sorted_items)} entries:')
            self.table.setRowCount(len(sorted_items))
            for row, (int_id, str_id) in enumerate(sorted_items):
                self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(row + 1)))
                self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(f'0x{int_id:04X}'))
                self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(str_id))


class CustomIconDialog(QtWidgets.QDialog):
    """
    Set/Modify Custom Icon: saves a Y0MI_ icon (see ICONS.md) for an actor in an enabled
    patch. It starts from the icon the actor has now, if any, so that icon can be changed
    without picking its image again.
    """
    # The Position dots, row by row: what each means, and its (up, right, centreV, centreH)
    POSITIONS = (
        ('Up and to the left', (True, False, False, False)),
        ('Up, centred horizontally', (True, False, False, True)),
        ('Up and to the right', (True, True, False, False)),
        ('To the left, centred vertically', (False, False, True, False)),
        ('Centred on the tile', (False, False, True, True)),
        ('To the right, centred vertically', (False, True, True, False)),
        ('Down and to the left', (False, False, False, False)),
        ('Down, centred horizontally', (False, False, False, True)),
        ('Down and to the right', (False, True, False, False)),
    )

    def __init__(self, type_id, data, parent=None):
        """
        Creates and initializes the dialog
        """
        super().__init__(parent)
        self.setWindowTitle('Set/Modify Custom Icon')
        self.setWindowIcon(GetIcon('sprites'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.type = type_id
        self.data = bytes(data)
        self.source = spriteicons.iconPath(type_id, self.data)  # the PNG that Save copies
        cols, rows, anchor = spriteicons.levelIconLayout(type_id, self.data)
        if anchor is None:
            # Icons without a layout are drawn up from the tile, centred
            anchor = self.POSITIONS[1 if self.source else 4][1]

        self.patchBox = QtWidgets.QComboBox()
        for name, folder in globals.gamedef.patches():
            self.patchBox.addItem(name, folder)
            if self.source and os.path.dirname(os.path.dirname(self.source)) == folder:
                self.patchBox.setCurrentIndex(self.patchBox.count() - 1)

        tip = ('If set, the raw data currently set in the selected actor is included in the file name. '
               'Otherwise it consists of just the magic word and the metadata.')
        rawLabel = QtWidgets.QLabel('Include Raw Data:')
        rawLabel.setToolTip(tip)
        self.rawBox = QtWidgets.QCheckBox()
        self.rawBox.setToolTip(tip)
        self.rawBox.setChecked(self.source is None or spriteicons.iconPath(type_id, self.data, True) is not None)

        tip = 'The image used for the actor.'
        imageLabel = QtWidgets.QLabel('Select Image (PNG):')
        imageLabel.setToolTip(tip)
        self.imageEdit = QtWidgets.QLineEdit()
        self.imageEdit.setReadOnly(True)
        self.imageEdit.setPlaceholderText('No image selected')
        self.imageEdit.setToolTip(tip)
        browse = QtWidgets.QPushButton('Browse File...')
        browse.setAutoDefault(False)
        browse.setToolTip(tip)
        browse.clicked.connect(self.HandleBrowse)
        imageLayout = QtWidgets.QHBoxLayout()
        imageLayout.addWidget(self.imageEdit, 1)
        imageLayout.addWidget(browse)

        self.widthBox = QtWidgets.QSpinBox()
        self.widthBox.setRange(1, 16)
        self.widthBox.setValue(cols)
        self.heightBox = QtWidgets.QSpinBox()
        self.heightBox.setRange(1, 16)
        self.heightBox.setValue(rows)

        self.positions = QtWidgets.QButtonGroup(self)
        dots = QtWidgets.QGridLayout()
        dots.setSpacing(8)
        for i, (text, _) in enumerate(self.POSITIONS):
            dot = QtWidgets.QRadioButton()
            dot.setToolTip(text)
            self.positions.addButton(dot, i)
            dots.addWidget(dot, i // 3, i % 3)
        up, right, centreV, centreH = anchor
        row = 1 if centreV else 0 if up else 2
        col = 1 if centreH else 2 if right else 0
        self.positions.button(row * 3 + col).setChecked(True)
        positionHelp = QtWidgets.QLabel('The middle dot is the actor\'s tile: the icon goes that way from it, '
                                        'starting at the tile.')
        positionHelp.setWordWrap(True)
        positionLayout = QtWidgets.QHBoxLayout()
        positionLayout.addLayout(dots)
        positionLayout.addWidget(positionHelp, 1)

        self.nameLabel = QtWidgets.QLabel()
        self.nameLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.statusLabel = QtWidgets.QLabel()
        self.statusLabel.setWordWrap(True)

        buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Close)
        self.saveButton = buttonBox.button(QtWidgets.QDialogButtonBox.Save)
        buttonBox.accepted.connect(self.HandleSave)
        buttonBox.rejected.connect(self.reject)

        form = QtWidgets.QFormLayout()
        form.addRow('Target Mod Patch:', self.patchBox)
        form.addRow(rawLabel, self.rawBox)
        form.addRow(imageLabel, imageLayout)
        form.addRow('Width in Tiles:', self.widthBox)
        form.addRow('Height in Tiles:', self.heightBox)
        form.addRow('Position:', positionLayout)
        form.addRow('File Name:', self.nameLabel)

        mainLayout = QtWidgets.QVBoxLayout()
        mainLayout.addLayout(form)
        mainLayout.addWidget(self.statusLabel)
        mainLayout.addWidget(buttonBox)
        self.setLayout(mainLayout)
        self.setMinimumWidth(460)

        self.patchBox.currentIndexChanged.connect(self.UpdateName)
        self.rawBox.toggled.connect(self.UpdateName)
        self.widthBox.valueChanged.connect(self.UpdateName)
        self.heightBox.valueChanged.connect(self.UpdateName)
        self.positions.buttonClicked.connect(self.UpdateName)
        self.setSource(self.source)

    def anchor(self):
        """The (up, right, centreV, centreH) of the picked dot."""
        return self.POSITIONS[self.positions.checkedId()][1]

    def rawData(self):
        """The raw data that goes in the file name, or None."""
        return self.data if self.rawBox.isChecked() else None

    def fileName(self):
        return spriteicons.y0miName(self.type, self.widthBox.value(), self.heightBox.value(), self.anchor(),
                                    self.rawData())

    def setSource(self, path):
        """Sets the PNG that Save copies."""
        self.source = path
        self.imageEdit.setText(os.path.basename(path) if path else '')
        self.imageEdit.setCursorPosition(0)  # long names show their start
        self.UpdateName()

    def UpdateName(self, *args):
        """Shows the file name for the settings. What the last Save said doesn't apply to them any more."""
        self.nameLabel.setText(self.fileName())
        self.statusLabel.clear()
        self.saveButton.setEnabled(self.source is not None)

    def HandleBrowse(self):
        path = QtWidgets.QFileDialog.getOpenFileName(self, 'Select Image', os.path.dirname(self.source or ''),
                                                     'PNG images (*.png)')[0]
        if not path:
            return
        if bytes(QtGui.QImageReader(path).format()) != b'png':
            QtWidgets.QMessageBox.warning(self, 'Set/Modify Custom Icon', 'This file is not a PNG image.')
            return
        self.setSource(path)

    def HandleSave(self):
        """Writes the icon right away, over the one this actor and raw data have in the patch."""
        try:
            path = spriteicons.saveY0MI(self.patchBox.currentData(), self.source, self.type, self.widthBox.value(),
                                        self.heightBox.value(), self.anchor(), self.rawData())
        except OSError as error:
            QtWidgets.QMessageBox.warning(self, 'Set/Modify Custom Icon',
                                          'The icon could not be saved:\n\n%s' % error)
            return

        self.setSource(path)  # the old file may be gone, if its name changed
        globals.mainWindow.CustomIconSaved(self.type)

        # Save can work and still change nothing in the level, see ICONS.md
        hasImage = self.type in globals.gamedef.getImageClasses()
        used = spriteicons.iconPath(self.type, self.data, hasImage)
        if used is None:
            status = ('Saved, but this actor has its own sprite image: only an icon with raw data '
                      'replaces it.')
        elif os.path.samefile(used, path):
            status = 'Saved.'
        else:
            status = 'Saved, but this actor uses %s first.' % os.path.basename(used)
        self.statusLabel.setText(status)
