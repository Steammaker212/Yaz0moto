#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Yaz0moto Level Editor
# This file is part of Yaz0moto, a fork of Pyamoto.

# See LICENSE.txt for more information.

"""
The theme editor: make a theme of your own by choosing an accent colour, a background,
a text colour, a level background and how round things are. A modern theme is built on
the Yaz0moto theme (same shapes and icons, in your colours); a classic one on the Legacy
theme (the original controls and icons, in your colours). It's saved in the user data folder.
"""

import os
import re

from PyQt5 import QtCore, QtGui, QtWidgets
Qt = QtCore.Qt

from . import globals
from . import themevars
from .ui import MiyamotoTheme, availableThemes, resolveThemeFolder, svgIcon, themeImages


def userThemesFolder():
    return os.path.join(globals.user_data_path, 'themes')


def folderName(name):
    """A safe folder name for a theme name."""
    return re.sub(r'[^A-Za-z0-9 _-]+', '', name).strip().replace(' ', '_') or 'MyTheme'


class ColorButton(QtWidgets.QPushButton):
    """A button that shows a colour and opens a colour picker."""
    changed = QtCore.pyqtSignal()

    def __init__(self, color, allowEmpty=False, emptyText='Automatic'):
        super().__init__()
        self.allowEmpty = allowEmpty
        self.emptyText = emptyText
        self.setMinimumWidth(140)
        self.clicked.connect(self.pick)
        self.setColor(color)

    def setColor(self, color):
        self.color = color if themevars.is_color(color or '') else ''
        if self.color:
            text = '#000000' if themevars.luminance(self.color) > 0.4 else '#FFFFFF'
            self.setText(self.color.upper())
            self.setStyleSheet('QPushButton { background: %s; color: %s; border: 1px solid rgba(0,0,0,0.35); }'
                               % (self.color, text))
        else:
            self.setText(self.emptyText)
            self.setStyleSheet('')
        self.changed.emit()

    def pick(self):
        start = QtGui.QColor(self.color or '#808080')
        color = QtWidgets.QColorDialog.getColor(start, self, 'Choose a colour')
        if color.isValid():
            self.setColor(color.name())

    def contextMenuEvent(self, event):
        if self.allowEmpty:
            menu = QtWidgets.QMenu(self)
            menu.addAction(self.emptyText, lambda: self.setColor(''))
            menu.exec_(event.globalPos())


# The classic themes have no style sheet: their plain controls take the window colours. The
# app's style sheet (a modern theme's) would still reach the preview, so the preview draws
# classic-looking controls with this one instead.
CLASSIC_PREVIEW = """
QFrame#ThemePreview { background: ${window}; border: 1px solid ${edge_dark}; border-radius: 0; }
QFrame#ThemePreview QWidget { background: ${window}; color: ${text}; border-radius: 0; }
QFrame#ThemePreview QToolBar { border: none; border-bottom: 1px solid ${edge_dark}; spacing: 1px; padding: 1px; }
QFrame#ThemePreview QToolButton { background: transparent; border: 1px solid transparent; padding: 2px; }
QFrame#ThemePreview QToolButton:checked { background: ${pressed}; border: 1px solid ${edge_dark}; }
QFrame#ThemePreview QLineEdit, QFrame#ThemePreview QListWidget, QFrame#ThemePreview QSpinBox,
QFrame#ThemePreview QComboBox { background: ${field}; border: 1px solid ${edge_dark}; padding: 2px;
    selection-background-color: ${accent}; selection-color: ${on_accent}; }
QFrame#ThemePreview QListWidget::item:selected { background: ${accent}; color: ${on_accent}; }
QFrame#ThemePreview QPushButton { background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 ${edge_light}, stop: 1 ${window});
    border: 1px solid ${edge_dark}; padding: 3px 14px; }
QFrame#ThemePreview QPushButton:default { border: 1px solid ${accent}; }
QFrame#ThemePreview QTabWidget::pane { border: 1px solid ${edge_dark}; }
QFrame#ThemePreview QTabBar::tab { background: ${panel}; border: 1px solid ${edge_dark}; padding: 3px 10px; margin-right: -1px; }
QFrame#ThemePreview QTabBar::tab:selected { background: ${window}; border-bottom-color: ${window}; }
QFrame#ThemePreview QCheckBox::indicator { width: 11px; height: 11px; border: 1px solid ${edge_dark}; background: ${field}; image: none; }
QFrame#ThemePreview QCheckBox::indicator:checked { background: ${accent}; }
"""


class ThemePreview(QtWidgets.QFrame):
    """A few sample controls drawn with the theme being edited."""

    ICONS = ('new', 'open', 'save', 'undo', 'redo', 'grid', 'realview', 'sprites', 'paths', 'zones')

    def __init__(self):
        super().__init__()
        self.setObjectName('ThemePreview')
        self.setMinimumSize(420, 300)

        self.toolbar = QtWidgets.QToolBar()
        self.toolbar.setIconSize(QtCore.QSize(22, 22))
        self.actions = []
        for name in self.ICONS:
            act = self.toolbar.addAction(name)
            act.setCheckable(name in ('grid', 'realview'))
            act.setChecked(name == 'realview')
            self.actions.append((name, act))

        tabs = QtWidgets.QTabWidget()
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        search = QtWidgets.QLineEdit()
        search.setPlaceholderText('Search actors...')
        form.addRow(search)
        self.list = QtWidgets.QListWidget()
        for text in ('Goomba', 'Star Coin', 'Checkpoint Flag'):
            self.list.addItem(text)
        self.list.setCurrentRow(1)
        self.list.setMaximumHeight(90)
        form.addRow(self.list)
        combo = QtWidgets.QComboBox()
        combo.addItems(['Right', 'Left', 'Up', 'Down'])
        form.addRow('Direction', combo)
        spin = QtWidgets.QSpinBox()
        spin.setValue(3)
        form.addRow('Movement ID', spin)
        check = QtWidgets.QCheckBox('Event activated')
        check.setChecked(True)
        form.addRow(check)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(QtWidgets.QPushButton('Cancel'))
        apply = QtWidgets.QPushButton('Apply')
        apply.setDefault(True)
        buttons.addWidget(apply)
        form.addRow(buttons)
        tabs.addTab(page, 'Actors')
        tabs.addTab(QtWidgets.QWidget(), 'Objects')

        self.level = QtWidgets.QLabel()
        self.level.setMinimumWidth(110)

        body = QtWidgets.QHBoxLayout()
        body.addWidget(self.level, 1)
        body.addWidget(tabs, 2)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.toolbar)
        layout.addLayout(body)

    def apply(self, variables, template, iconFolder, classic=False):
        """Draws the preview in a theme's colours: modern (the style sheet template and SVG icons) or classic."""
        if classic:
            qss = themevars.substitute(CLASSIC_PREVIEW, variables)
        else:
            qss = themevars.substitute(template, variables)
            images = themeImages(variables) or os.path.join(os.path.dirname(iconFolder), 'images')
            qss = qss.replace('{images}', images.replace('\\', '/'))
            # QMainWindow/QDialog rules don't reach a frame, so give the frame the window colour
            qss += '\nQFrame#ThemePreview { background: %s; border-radius: %spx; }' % (variables['window'], variables['radius_l'])
        self.setStyleSheet(qss)
        # Qt keeps the old look on children that were already styled; restyle them
        for widget in [self] + self.findChildren(QtWidgets.QWidget):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        self.toolbar.setIconSize(QtCore.QSize(16, 16) if classic else QtCore.QSize(22, 22))
        for name, act in self.actions:
            if classic:
                icon = QtGui.QIcon(os.path.join(globals.miyamoto_path, 'yaz0data', 'ico', 'sm', 'icon-%s.png' % name))
            else:
                icon = svgIcon(os.path.join(iconFolder, 'icon-%s.svg' % name), False, variables)
            if icon is not None:
                act.setIcon(icon)
        self.level.setStyleSheet('QLabel { background: %s; border: %dpx solid %s; border-radius: %spx; }'
                                 % (variables['level'], 1 if classic else 2, variables['accent'],
                                    0 if classic else variables['radius']))


class ThemeEditorDialog(QtWidgets.QDialog):
    """Create (or change) a theme of your own, built on the Yaz0moto theme or (classic) the Legacy theme."""

    def __init__(self, startTheme=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Theme Editor')
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.savedName = None

        baseFolder = resolveThemeFolder(themevars.BASE_THEME)
        with open(os.path.join(baseFolder, 'style.qss'), encoding='utf-8') as f:
            self.template = f.read()
        self.iconFolder = os.path.join(baseFolder, 'icons')

        self.startBox = QtWidgets.QComboBox()
        self.startBox.addItems([themevars.BASE_THEME] + [t for t in availableThemes() if t != themevars.BASE_THEME])
        if startTheme and self.startBox.findText(startTheme) >= 0:
            self.startBox.setCurrentText(startTheme)
        self.startBox.currentTextChanged.connect(self.loadStart)

        self.styleBox = QtWidgets.QComboBox()
        self.styleBox.addItem('Modern (rounded controls, Yaz0moto icons)', themevars.BASE_THEME)
        self.styleBox.addItem('Classic (plain controls, original icons)', themevars.CLASSIC_BASE)
        self.styleBox.setToolTip('Modern themes are built on the Yaz0moto theme, classic ones on the Legacy theme. '
                                 'Both are drawn in the colours you choose here.')
        self.styleBox.currentIndexChanged.connect(self.updatePreview)

        self.nameEdit = QtWidgets.QLineEdit('My Theme')
        self.accent = ColorButton(themevars.DEFAULTS['accent'])
        self.background = ColorButton(themevars.DEFAULTS['background'])
        self.text = ColorButton(themevars.DEFAULTS['text'])
        self.level = ColorButton('', allowEmpty=True)
        self.level.setToolTip('The level view background. Right-click to go back to Automatic.')
        self.roundness = QtWidgets.QSlider(Qt.Horizontal)
        self.roundness.setRange(0, 20)
        self.roundnessLabel = QtWidgets.QLabel()
        for w in (self.accent, self.background, self.text, self.level):
            w.changed.connect(self.updatePreview)
        self.roundness.valueChanged.connect(self.updatePreview)

        roundRow = QtWidgets.QHBoxLayout()
        roundRow.addWidget(self.roundness, 1)
        roundRow.addWidget(self.roundnessLabel)

        form = QtWidgets.QFormLayout()
        form.addRow('Start from:', self.startBox)
        form.addRow('Style:', self.styleBox)
        form.addRow('Name:', self.nameEdit)
        form.addRow('Accent:', self.accent)
        form.addRow('Background:', self.background)
        form.addRow('Text:', self.text)
        form.addRow('Level background:', self.level)
        self.roundnessRow = QtWidgets.QLabel('Roundness:')
        form.addRow(self.roundnessRow, roundRow)

        note = QtWidgets.QLabel('Every other shade is worked out from these colours, for light and dark themes. '
                                'The theme is saved in your user data folder; restart Yaz0moto after choosing it.')
        note.setWordWrap(True)

        self.preview = ThemePreview()

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
        save = buttons.addButton('Save Theme', QtWidgets.QDialogButtonBox.AcceptRole)
        save.setDefault(True)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        left = QtWidgets.QVBoxLayout()
        left.addLayout(form)
        left.addWidget(note)
        left.addStretch(1)

        body = QtWidgets.QHBoxLayout()
        body.addLayout(left, 2)
        body.addWidget(self.preview, 3)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(body)
        layout.addWidget(buttons)

        self.loadStart(self.startBox.currentText())

    def base(self):
        """The theme the one being made is built on: Yaz0moto (modern) or Legacy (classic)."""
        return self.styleBox.currentData()

    def inputs(self):
        return {
            'accent': self.accent.color or themevars.DEFAULTS['accent'],
            'background': self.background.color or themevars.DEFAULTS['background'],
            'text': self.text.color or themevars.DEFAULTS['text'],
            'level': self.level.color,
            'roundness': str(self.roundness.value()),
        }

    def loadStart(self, name):
        try:
            theme = MiyamotoTheme(name)
        except Exception:
            theme = MiyamotoTheme(themevars.BASE_THEME)
        values = dict(themevars.DEFAULTS)
        values.update(theme.variableInputs or {})
        for button, key in ((self.accent, 'accent'), (self.background, 'background'), (self.text, 'text'),
                            (self.level, 'level')):
            button.blockSignals(True)
            button.setColor(values.get(key, ''))
            button.blockSignals(False)
        self.roundness.blockSignals(True)
        try:
            self.roundness.setValue(int(float(values.get('roundness', 10))))
        except (TypeError, ValueError):
            self.roundness.setValue(10)
        self.roundness.blockSignals(False)
        # Starting from a classic theme makes a classic one
        self.styleBox.blockSignals(True)
        self.styleBox.setCurrentIndex(self.styleBox.findData(themevars.CLASSIC_BASE if theme.isClassic
                                                             else themevars.BASE_THEME))
        self.styleBox.blockSignals(False)
        if (name not in (themevars.BASE_THEME, themevars.CLASSIC_BASE)
                and os.path.dirname(theme.folder or '') == userThemesFolder()):
            self.nameEdit.setText(theme.themeName)  # editing one of your own themes
        self.updatePreview()

    def updatePreview(self):
        classic = self.base() == themevars.CLASSIC_BASE
        self.roundnessLabel.setText('%d px' % self.roundness.value())
        # Classic controls aren't rounded
        for widget in (self.roundnessRow, self.roundness, self.roundnessLabel):
            widget.setEnabled(not classic)
        self.preview.apply(themevars.derive(self.inputs()), self.template, self.iconFolder, classic)

    def save(self):
        name = self.nameEdit.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, 'Theme Editor', 'Give the theme a name.')
            return
        folder = os.path.join(userThemesFolder(), folderName(name))
        if folderName(name) in (themevars.BASE_THEME, themevars.CLASSIC_BASE, 'Classic'):
            QtWidgets.QMessageBox.warning(self, 'Theme Editor', 'That name is taken by a built-in theme.')
            return
        if os.path.isfile(os.path.join(folder, 'main.xml')):
            reply = QtWidgets.QMessageBox.question(self, 'Theme Editor', 'Replace your theme "%s"?' % name)
            if reply != QtWidgets.QMessageBox.Yes:
                return
        try:
            themevars.write_theme(folder, name, self.inputs(), base=self.base())
        except OSError as e:
            QtWidgets.QMessageBox.warning(self, 'Theme Editor', 'Could not save the theme:\n%s' % e)
            return
        self.savedName = os.path.basename(folder)
        self.accept()
