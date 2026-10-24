#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Yaz0moto Level Editor
# This file is part of Yaz0moto, a fork of Pyamoto.

# See LICENSE.txt for more information.

"""The Check Level window: design warnings and metrics for the open level."""

import os
import shutil
import statistics

from PyQt5 import QtCore, QtGui, QtWidgets
Qt = QtCore.Qt

from . import globals
from . import levelcheck

# Metrics of the original courses, per course folder, kept for the session
_courseMetricsCache = {}


class LevelCheckDialog(QtWidgets.QDialog):
    """
    Lists possible mistakes in the open level (nothing is changed or blocked) and
    compares its metrics with the game's original courses.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Check Level')
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.resize(820, 520)

        self.findings = []
        self.metrics = {}
        self.courseMetrics = None

        style = self.style()
        self.severityIcons = {
            'error': style.standardIcon(QtWidgets.QStyle.SP_MessageBoxCritical),
            'warning': style.standardIcon(QtWidgets.QStyle.SP_MessageBoxWarning),
            'info': style.standardIcon(QtWidgets.QStyle.SP_MessageBoxInformation),
        }

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._problemsTab(), 'Problems')
        tabs.addTab(self._metricsTab(), 'Metrics')

        buttons = QtWidgets.QDialogButtonBox()
        recheck = buttons.addButton('Check again', QtWidgets.QDialogButtonBox.ActionRole)
        recheck.clicked.connect(self.runChecks)
        rules = buttons.addButton('Edit rules...', QtWidgets.QDialogButtonBox.ActionRole)
        rules.setToolTip('Opens your own copy of the rules file. Run the check again after saving it.')
        rules.clicked.connect(self.editRules)
        buttons.addButton(QtWidgets.QDialogButtonBox.Close).clicked.connect(self.close)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

        self.runChecks()

    # ---- Problems

    def _problemsTab(self):
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(['Severity', 'Area', 'Check', 'Problem'])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.itemActivated.connect(self.jumpTo)
        header = self.tree.header()
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        header.setStretchLastSection(True)

        hint = QtWidgets.QLabel('Double-click a problem in the open area to select it in the level. '
                                'These are warnings only: nothing stops you from saving.')
        hint.setWordWrap(True)

        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.addWidget(self.summary)
        layout.addWidget(self.tree)
        layout.addWidget(hint)
        return widget

    def runChecks(self):
        if globals.Level is None:
            return

        rules, error = levelcheck.load_rules()
        if error:
            QtWidgets.QMessageBox.warning(self, 'Check Level', error)
        self.rules = rules

        areas = levelcheck.snapshot_level(globals.Level)
        self.findings = levelcheck.check_level(areas, rules)
        self.metrics = levelcheck.compute_metrics(areas, rules, *self._metricSprites())

        self.tree.setSortingEnabled(False)
        self.tree.clear()
        current = globals.Area.areanum
        for f in self.findings:
            item = QtWidgets.QTreeWidgetItem(['', str(f.area), f.rule.replace('_', ' '), f.message])
            item.setIcon(0, self.severityIcons[f.severity])
            item.setText(0, f.severity.capitalize())
            # Keep the level item itself: saving re-sorts the area's lists, so the
            # finding's list position would point at something else afterwards
            item.setData(0, Qt.UserRole, (f, self._levelItem(f) if f.area == current else None))
            item.setToolTip(3, f.message if f.target is None or f.area == current
                            else f.message + '\n(Open area %d to select it.)' % f.area)
            self.tree.addTopLevelItem(item)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(-1, Qt.AscendingOrder)
        for col in range(3):
            self.tree.resizeColumnToContents(col)

        counts = {s: sum(1 for f in self.findings if f.severity == s) for s in levelcheck.SEVERITIES}
        if not self.findings:
            self.summary.setText('No problems found.')
        else:
            self.summary.setText('%d error(s), %d warning(s), %d note(s).'
                                 % (counts['error'], counts['warning'], counts['info']))

        self.updateMetrics()

    @staticmethod
    def _areaList(kind):
        return {
            'sprite': globals.Area.sprites,
            'entrance': globals.Area.entrances,
            'zone': globals.Area.zones,
            'location': globals.Area.locations,
        }.get(kind, [])

    def _levelItem(self, f):
        """The open area's item a finding points at, or None."""
        if f.target is None:
            return None
        kind, index = f.target
        items = self._areaList(kind)
        return items[index] if 0 <= index < len(items) else None

    def jumpTo(self, item, column=0):
        data = item.data(0, Qt.UserRole)
        if data is None or data[0].target is None:
            return
        f, target = data
        if f.area != globals.Area.areanum:
            QtWidgets.QMessageBox.information(self, 'Check Level',
                                              'This is in area %d. Open that area to select it.' % f.area)
            return

        if target is None or target not in self._areaList(f.target[0]):
            QtWidgets.QMessageBox.information(self, 'Check Level',
                                              'That item is no longer in the level. Click "Check again".')
            return

        mw = globals.mainWindow
        mw.scene.clearSelection()
        target.setSelected(True)
        mw.view.centerOn(target)

    def editRules(self):
        path = levelcheck.user_rules_path()
        if not os.path.isfile(path):
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                shutil.copyfile(levelcheck.default_rules_path(), path)
            except OSError as e:
                QtWidgets.QMessageBox.warning(self, 'Check Level', 'Could not create your rules file:\n%s\n\n%s' % (path, e))
                return

        if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path)):
            QtWidgets.QMessageBox.information(self, 'Check Level', 'Your rules file is here:\n%s' % path)

    # ---- Metrics

    def _metricsTab(self):
        self.metricsTable = QtWidgets.QTableWidget(len(levelcheck.METRICS), 4)
        self.metricsTable.setHorizontalHeaderLabels(['This level', 'Original median', 'Higher than', 'Compared course'])
        self.metricsTable.setVerticalHeaderLabels(list(levelcheck.METRICS))
        self.metricsTable.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.metricsTable.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        self.compareButton = QtWidgets.QPushButton('Compare with the original courses')
        self.compareButton.setToolTip('Reads every level in your game\'s course folder (this can take a moment).')
        self.compareButton.clicked.connect(self.loadCourseMetrics)

        self.courseBox = QtWidgets.QComboBox()
        self.courseBox.setEnabled(False)
        self.courseBox.setMinimumContentsLength(12)
        self.courseBox.currentIndexChanged.connect(self.updateMetrics)

        self.metricsNote = QtWidgets.QLabel('Coins made of tiles are not counted, only coin sprites.')
        self.metricsNote.setWordWrap(True)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.compareButton)
        row.addStretch()
        row.addWidget(QtWidgets.QLabel('Compare with:'))
        row.addWidget(self.courseBox)

        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.addLayout(row)
        layout.addWidget(self.metricsTable)
        layout.addWidget(self.metricsNote)
        return widget

    def _metricSprites(self):
        config = self.rules.get('metrics', {})
        groups = []
        for key in ('enemies', 'coins'):
            spec = config.get(key, {})
            groups.append(levelcheck.category_sprite_ids(spec.get('view'), spec.get('category')))
        return groups

    def loadCourseMetrics(self):
        folder = _originalCourseFolder()
        if not folder or not os.path.isdir(folder):
            QtWidgets.QMessageBox.warning(self, 'Check Level', 'Set up your game\'s course folder first (Preferences > Game Setup).')
            return

        key = (os.path.normpath(folder), bool(globals.IsNSMBUDX))
        if key not in _courseMetricsCache:
            progress = QtWidgets.QProgressDialog('Reading the original courses...', 'Cancel', 0, 1, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(300)

            def report(done, total):
                progress.setMaximum(total)
                progress.setValue(done)
                QtWidgets.QApplication.processEvents()
                return progress.wasCanceled()

            results = levelcheck.scan_courses(folder, bool(globals.IsNSMBUDX), self.rules,
                                              *self._metricSprites(), progress=report)
            cancelled = progress.wasCanceled()
            progress.close()
            if cancelled:
                return
            _courseMetricsCache[key] = results

        # Don't compare the level with itself
        own = os.path.splitext(os.path.basename(globals.Level.filepath or ''))[0]
        self.courseMetrics = {name: m for name, m in _courseMetricsCache[key].items() if name != own}
        if not self.courseMetrics:
            QtWidgets.QMessageBox.warning(self, 'Check Level', 'No levels could be read from:\n%s' % folder)
            return

        self.courseBox.blockSignals(True)
        self.courseBox.clear()
        self.courseBox.addItem('(none)')
        self.courseBox.addItems(sorted(self.courseMetrics, key=_courseSortKey))
        self.courseBox.setEnabled(True)
        self.courseBox.blockSignals(False)
        self.compareButton.setText('Compared with %d original courses' % len(self.courseMetrics))
        self.compareButton.setEnabled(False)
        self.updateMetrics()

    def updateMetrics(self):
        others = list(self.courseMetrics.values()) if self.courseMetrics else []
        chosen = self.courseBox.currentText() if self.courseBox.currentIndex() > 0 else None
        self.metricsTable.setHorizontalHeaderItem(3, QtWidgets.QTableWidgetItem(chosen or 'Compared course'))

        for row, name in enumerate(levelcheck.METRICS):
            value = self.metrics.get(name, 0)
            cells = [str(value), '', '', '']
            if others:
                values = [m[name] for m in others]
                cells[1] = _fmt(statistics.median(values))
                cells[2] = '%d%% of them' % levelcheck.percentile(value, values)
            if chosen:
                cells[3] = _fmt(self.courseMetrics[chosen][name])
            for col, text in enumerate(cells):
                cell = QtWidgets.QTableWidgetItem(text)
                cell.setTextAlignment(Qt.AlignCenter)
                self.metricsTable.setItem(row, col, cell)


def _originalCourseFolder():
    """
    The base game's course folder. Patches are skipped: their folder (often not set up)
    holds modded levels, not the originals. Actors that only exist in a patch still
    count as actors in this level's metrics.
    """
    gamedef = globals.gamedef
    while gamedef is not None and getattr(gamedef, 'custom', False) and getattr(gamedef, 'source', None) == 'mod':
        gamedef = gamedef.base
    if gamedef is None:
        gamedef = globals.gamedef
    folder = gamedef.GetGamePath()
    if not folder or not os.path.isdir(folder):
        # A patch whose base can't be found: fall back to any game folder that exists
        folder = next((p for p in globals.gamedef.GetGamePaths() if p and os.path.isdir(p)), '')
    return folder


def _fmt(value):
    return ('%.1f' % value).rstrip('0').rstrip('.') if isinstance(value, float) else str(value)


def _courseSortKey(name):
    """Sorts '1-2' before '1-10'."""
    parts = name.replace('_', '-').split('-')
    return [(0, int(p), '') if p.isdigit() else (1, 0, p) for p in parts]
