#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Yaz0moto Level Editor
# This file is part of Yaz0moto, a fork of Pyamoto.

# See LICENSE.txt for more information.

"""
Export Mod Package: a .zip with the saved level (and, for Deluxe, its tilesets) laid
out the way the game's file system expects, ready to be copied into a mod folder
(for LayeredFS, atmosphere/contents/<title id>/), plus a manifest
with the size and SHA-256 of every file.
"""

import datetime
import hashlib
import json
import os
import re
import zipfile

from PyQt5 import QtCore, QtWidgets
Qt = QtCore.Qt

from . import globals

MANIFEST_NAME = 'yaz0moto-mod.json'
DX_TITLE_ID = '0100EA80032EA000'

# Name Yaz0moto gives tilesets it writes (see tileset.py): Pa<slot>_<crc><size>
_GENERATED_TILESET = re.compile(r'^Pa[0-3]_[0-9A-F]{16}$')


def level_tilesets(level):
    """Names of the tilesets used by any area of the level, sorted."""
    names = set()
    for area in level.areas:
        for slot in range(4):
            name = getattr(area, 'tileset%d' % slot, '')
            if name:
                names.add(name)
    return sorted(names)


def _same_file(a, b):
    if os.path.getsize(a) != os.path.getsize(b):
        return False
    with open(a, 'rb') as fa, open(b, 'rb') as fb:
        return fa.read() == fb.read()


def is_custom_tileset(name, path, unit_paths):
    """
    True if the tileset was made with Yaz0moto, or it differs from (or is missing
    in) the base game's Unit folder when the game setup has more than one.
    """
    if _GENERATED_TILESET.match(name):
        return True
    if len(unit_paths) < 2:
        return False
    base = os.path.join(unit_paths[-1], name + '.szs')
    return not os.path.isfile(base) or not _same_file(path, base)


def plan_files(level_path, is_dx, tilesets=(), find_tileset=None, unit_paths=(), all_tilesets=False):
    """
    Returns (files, missing): files is a list of (path inside the package, source
    path); missing lists the tilesets the level uses that were not found.
    """
    name = os.path.basename(level_path)
    if is_dx:
        files = [('romfs/Course/' + name, level_path)]
    else:
        files = [('content/Common/course_res_pack/' + name, level_path)]

    missing = []
    if is_dx:
        for tileset in tilesets:
            path = find_tileset(tileset) if find_tileset else None
            if path is None:
                missing.append(tileset)
            elif all_tilesets or is_custom_tileset(tileset, path, list(unit_paths)):
                files.append(('romfs/Unit/%s.szs' % tileset, path))

    return files, missing


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def write_package(out_path, files, game, level_name):
    """
    Writes the package and returns its manifest. The zip is written next to the
    destination first, so a failed export never leaves a broken file behind.
    """
    manifest = {
        'format': 1,
        'tool': 'Yaz0moto %s' % globals.MiyamotoVersion,
        'game': game,
        'level': level_name,
        'created': datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        'files': [{'path': arcname, 'size': os.path.getsize(src), 'sha256': _sha256(src)}
                  for arcname, src in files],
    }

    tmp = out_path + '.tmp'
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zf:
            for arcname, src in files:
                zf.write(src, arcname)
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    return manifest


class ExportModDialog(QtWidgets.QDialog):
    """
    Picks where the package goes and which tilesets go in it, then writes it.
    The level must already be saved.
    """

    def __init__(self, level_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Export Mod Package')
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(560)

        self.levelPath = level_path
        self.isDX = bool(globals.IsNSMBUDX)
        self.tilesets = level_tilesets(globals.Level) if self.isDX else []
        self.unitPaths = globals.gamedef.GetUnitPaths() if self.isDX else []

        base = os.path.splitext(os.path.basename(level_path))[0]
        self.outEdit = QtWidgets.QLineEdit(os.path.join(os.path.dirname(level_path), base + '-mod.zip'))
        browse = QtWidgets.QPushButton('Browse...')
        browse.clicked.connect(self.browse)
        outRow = QtWidgets.QHBoxLayout()
        outRow.addWidget(self.outEdit)
        outRow.addWidget(browse)

        self.customOnly = QtWidgets.QRadioButton('Only tilesets made or changed with Yaz0moto')
        self.customOnly.setToolTip('Tilesets saved by Yaz0moto, and tilesets that differ from your base game\'s Unit folder.\n'
                                   'If you overwrote an original tileset in place, choose "All tilesets".')
        self.allTilesets = QtWidgets.QRadioButton('All tilesets the level uses')
        self.customOnly.setChecked(True)
        self.customOnly.toggled.connect(self.updatePreview)

        tilesetBox = QtWidgets.QGroupBox('Tilesets')
        tl = QtWidgets.QVBoxLayout(tilesetBox)
        tl.addWidget(self.customOnly)
        tl.addWidget(self.allTilesets)
        tilesetBox.setVisible(self.isDX)

        self.preview = QtWidgets.QListWidget()
        self.missingLabel = QtWidgets.QLabel()
        self.missingLabel.setWordWrap(True)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
        export = buttons.addButton('Export', QtWidgets.QDialogButtonBox.AcceptRole)
        export.setDefault(True)
        buttons.accepted.connect(self.export)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        form.addRow('Save as:', outRow)
        layout.addLayout(form)
        layout.addWidget(tilesetBox)
        layout.addWidget(QtWidgets.QLabel('Files in the package:'))
        layout.addWidget(self.preview)
        layout.addWidget(self.missingLabel)
        layout.addWidget(buttons)

        self.updatePreview()

    def plan(self):
        return plan_files(self.levelPath, self.isDX, self.tilesets, globals.gamedef.FindTilesetFile,
                          self.unitPaths, self.allTilesets.isChecked())

    def updatePreview(self):
        files, missing = self.plan()
        self.preview.clear()
        for arcname, src in files:
            item = QtWidgets.QListWidgetItem(arcname)
            item.setToolTip(src)
            self.preview.addItem(item)
        self.preview.addItem(MANIFEST_NAME)

        if missing:
            self.missingLabel.setText('Not found in any Unit folder, so not included: ' + ', '.join(missing))
        self.missingLabel.setVisible(bool(missing))

    def browse(self):
        fn = QtWidgets.QFileDialog.getSaveFileName(self, 'Export Mod Package', self.outEdit.text(), 'Zip archive (*.zip)')[0]
        if fn:
            self.outEdit.setText(fn)

    def export(self):
        out = self.outEdit.text().strip()
        if not out:
            return
        if not out.lower().endswith('.zip'):
            out += '.zip'

        files, _ = self.plan()
        game = 'New Super Mario Bros. U Deluxe' if self.isDX else 'New Super Mario Bros. U'
        try:
            write_package(out, files, game, os.path.basename(self.levelPath))
        except OSError as e:
            QtWidgets.QMessageBox.warning(self, 'Export Mod Package', 'Could not write the package:\n%s\n\n%s' % (out, e))
            return

        if self.isDX:
            where = 'Copy its "romfs" folder into your mod folder (for LayeredFS: atmosphere/contents/%s/).' % DX_TITLE_ID
        else:
            where = 'Copy its "content" folder into your mod folder.'
        QtWidgets.QMessageBox.information(self, 'Export Mod Package',
                                          'Exported %d file(s) to:\n%s\n\n%s' % (len(files), out, where))
        self.accept()
