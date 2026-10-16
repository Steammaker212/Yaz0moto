#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Pyamoto Level Editor
# Copyright (C) 2009-2026 Pyamoto contributors
# This file is part of Pyamoto.

# See LICENSE.txt for more information.

# firstRunWizard.py
# Interactive Setup — a five-page wizard shown on first launch or from the File menu.

import os
import platform
import zipfile

import requests

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QThread, pyqtSignal

from . import globals
from .misc import setting, setSetting
from .ui import SetAppStyle
from .verifications import isValidGamePath, isValidObjectsPath


DATA_DOWNLOAD_URL = "https://github.com/nsmbu/editor-assets/releases/download/1.0/data.zip"
OBJECTS_DOWNLOAD_URL = "https://github.com/nsmbu/editor-assets/releases/download/1.0/Objects.zip"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _icon_path():
    name = 'pyamoto1024mac.png' if platform.system() == 'Darwin' else 'pyamoto1024.png'
    if globals.miyamoto_path:
        p = os.path.join(globals.miyamoto_path, 'miyamotodata', 'app_icons', name)
        if os.path.isfile(p):
            return p
    return None


def _data_present():
    p = globals.actor_data_path
    return os.path.isdir(p) and bool(os.listdir(p))


def _objects_present():
    # Check saved setting first, then the default download location.
    path = setting('ObjPath', '')
    if bool(path) and isValidObjectsPath(path):
        return True
    default = os.path.join(globals.user_data_path, 'Objects')
    return isValidObjectsPath(default)


def _make_logo_pixmap(logical_size):
    """Return a sharp pixmap at the given logical size, handling HiDPI correctly."""
    icon_p = _icon_path()
    if not icon_p:
        return None
    dpr = QtWidgets.QApplication.instance().devicePixelRatio()
    physical = int(logical_size * dpr)
    pix = QtGui.QPixmap(icon_p).scaled(
        physical, physical, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    pix.setDevicePixelRatio(dpr)
    return pix


# ---------------------------------------------------------------------------
# Background download worker
# ---------------------------------------------------------------------------

class _DownloadWorker(QThread):
    progress = pyqtSignal(int)      # 0-100; -1 = indeterminate (extracting)
    statusMsg = pyqtSignal(str)
    finished = pyqtSignal(bool, str)  # success, error_message

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
            self.statusMsg.emit("Connecting…")
            with requests.get(
                self.url,
                stream=True,
                timeout=30,
            ) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get('Content-Length', 0))
                done = 0
                self.statusMsg.emit("Downloading…")
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
                self.finished.emit(False, "Cancelled")
                return

            self.statusMsg.emit("Extracting…")
            self.progress.emit(-1)
            os.makedirs(self.extract_dir, exist_ok=True)
            with zipfile.ZipFile(self.tmp_path, 'r') as zf:
                zf.extractall(self.extract_dir)
            _safe_remove(self.tmp_path)
            self.finished.emit(True, "")

        except Exception as e:
            _safe_remove(self.tmp_path)
            self.finished.emit(False, str(e))


def _safe_remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Step indicator widget
# ---------------------------------------------------------------------------

class _StepDots(QtWidgets.QWidget):
    _DOT_R = 5
    _GAP = 18

    def __init__(self, count, parent=None):
        super().__init__(parent)
        self._count = count
        self._current = 0
        self.setFixedHeight(self._DOT_R * 2 + 6)

    def setCurrent(self, idx):
        self._current = idx
        self.update()

    def sizeHint(self):
        w = self._count * self._GAP
        return QtCore.QSize(w, self._DOT_R * 2 + 6)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        total_w = self._count * self._GAP
        x0 = (self.width() - total_w) // 2 + self._GAP // 2
        cy = self.height() // 2
        palette = self.palette()
        active_color = palette.color(QtGui.QPalette.Highlight)
        done_color = active_color.lighter(140)
        done_color.setAlpha(180)
        inactive_color = palette.color(QtGui.QPalette.Mid)

        for i in range(self._count):
            cx = x0 + i * self._GAP
            if i < self._current:
                color = done_color
                r = self._DOT_R - 1
            elif i == self._current:
                color = active_color
                r = self._DOT_R
            else:
                color = inactive_color
                r = self._DOT_R - 2
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QtCore.QPoint(cx, cy), r, r)


# ---------------------------------------------------------------------------
# Individual pages
# ---------------------------------------------------------------------------

class _WelcomePage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 40, 16)
        layout.setSpacing(0)

        # Logo
        logo_label = QtWidgets.QLabel()
        logo_label.setAlignment(Qt.AlignHCenter)
        pix = _make_logo_pixmap(160)
        if pix:
            logo_label.setPixmap(pix)
            logo_label.setFixedHeight(160)
        else:
            logo_label.setText("🎮")
            logo_label.setStyleSheet("font-size: 80px;")
            logo_label.setFixedHeight(160)
        layout.addWidget(logo_label)
        layout.addSpacing(20)

        # Title
        title = QtWidgets.QLabel("Welcome to Pyamoto")
        title.setAlignment(Qt.AlignHCenter)
        font = title.font()
        font.setPointSize(font.pointSize() + 10)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        layout.addSpacing(8)

        # Subtitle
        sub = QtWidgets.QLabel(
            "The New Super Mario Bros. U level editor")
        sub.setAlignment(Qt.AlignHCenter)
        sub_font = sub.font()
        sub_font.setPointSize(sub_font.pointSize() + 1)
        sub.setFont(sub_font)
        sub.setStyleSheet("color: palette(mid);")
        layout.addWidget(sub)
        layout.addSpacing(20)

        # Description
        desc = QtWidgets.QLabel(
            "This setup will guide you through required steps to start making levels.<br><hr>"
            "<h2>Resources</h2>Join our <a href=\"https://go.nsmbu.net/discord\">Discord</a> and visit the <a href=\"https://zenith.nsmbu.net/\">Wiki</a>")
        desc.setAlignment(Qt.AlignHCenter)
        desc.setWordWrap(True)
        desc.setTextFormat(Qt.RichText)
        desc.setOpenExternalLinks(True)
        layout.addWidget(desc)

        layout.addStretch(1)


# ---------------------------------------------------------------------------

class _DownloadRow(QtWidgets.QFrame):
    """One download item: icon + text + progress/button area."""

    def __init__(self, title, description, url, tmp_name, extract_dir, required, parent=None):
        super().__init__(parent)
        self.url = url
        self.tmp_name = tmp_name
        self.extract_dir = extract_dir
        self.required = required
        self._worker = None
        self.downloaded = False
        self._onFinishedExtra = None   # optional callback after successful download

        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setFrameShadow(QtWidgets.QFrame.Raised)

        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(14)

        # Left: text column
        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(3)

        header_row = QtWidgets.QHBoxLayout()
        self.titleLabel = QtWidgets.QLabel(title)
        tf = self.titleLabel.font()
        tf.setBold(True)
        tf.setPointSize(tf.pointSize() + 1)
        self.titleLabel.setFont(tf)
        header_row.addWidget(self.titleLabel)

        badge_text = "Required" if required else "Optional"
        badge_color = "#c0392b" if required else "#2980b9"
        self.badge = QtWidgets.QLabel(badge_text)
        self.badge.setStyleSheet(
            f"background:{badge_color}; color:white; border-radius:3px;"
            "padding: 1px 6px; font-size: 10px;")
        self.badge.setFixedHeight(16)
        header_row.addWidget(self.badge)
        header_row.addStretch(1)
        text_col.addLayout(header_row)

        self.descLabel = QtWidgets.QLabel(description)
        self.descLabel.setWordWrap(True)
        self.descLabel.setStyleSheet("color: palette(mid);")
        text_col.addWidget(self.descLabel)

        self.statusLabel = QtWidgets.QLabel("")
        self.statusLabel.setStyleSheet("color: palette(mid); font-size: 11px;")
        text_col.addWidget(self.statusLabel)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.hide()
        text_col.addWidget(self.progress)

        outer.addLayout(text_col, 1)

        # Right: action button
        self.btn = QtWidgets.QPushButton("Download")
        self.btn.setFixedWidth(110)
        self.btn.clicked.connect(self._onBtn)
        outer.addWidget(self.btn, 0, Qt.AlignVCenter)

    def setAlreadyPresent(self):
        self.downloaded = True
        self.statusLabel.setText("✓ Already installed")
        self.statusLabel.setStyleSheet("color: #27ae60; font-size: 11px;")
        self.btn.setText("Re-download")
        self.btn.setEnabled(bool(self.url))

    def _onBtn(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self.btn.setText("Download")
            self.btn.setEnabled(True)
            self.progress.hide()
            self.statusLabel.setText("Cancelled")
            return

        if not self.url:
            QtWidgets.QMessageBox.information(
                self, "Not available",
                "The download URL is not configured for this build.\n"
                "Please install the files manually.")
            return

        tmp = os.path.join(globals.user_data_path, self.tmp_name)
        self._worker = _DownloadWorker(self.url, tmp, self.extract_dir)
        self._worker.progress.connect(self._onProgress)
        self._worker.statusMsg.connect(self._onStatus)
        self._worker.finished.connect(self._onFinished)

        self.btn.setText("Cancel")
        self.progress.setValue(0)
        self.progress.setRange(0, 100)
        self.progress.show()
        self.statusLabel.setText("Starting…")
        self._worker.start()

    def _onProgress(self, pct):
        if pct == -1:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(pct)

    def _onStatus(self, msg):
        self.statusLabel.setText(msg)

    def _onFinished(self, ok, err):
        self.progress.hide()
        self.progress.setRange(0, 100)
        self.btn.setText("Download")
        self.btn.setEnabled(True)

        if ok:
            self.downloaded = True
            self.statusLabel.setText("✓ Installed successfully")
            self.statusLabel.setStyleSheet("color: #27ae60; font-size: 11px;")
            # Run any post-download hook (e.g. update globals.miyamoto_path)
            if self._onFinishedExtra:
                self._onFinishedExtra()
            # Notify parent page so it can re-check Next availability
            parent = self.parent()
            while parent and not hasattr(parent, '_onDownloadComplete'):
                parent = parent.parent()
            if parent:
                parent._onDownloadComplete()
        else:
            self.downloaded = False
            self.statusLabel.setText(f"✗ {err}")
            self.statusLabel.setStyleSheet("color: #c0392b; font-size: 11px;")


class _DownloadPage(QtWidgets.QWidget):
    readyChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(32, 16, 32, 16)
        layout.setSpacing(14)

        heading = QtWidgets.QLabel("Download Resources")
        hf = heading.font()
        hf.setPointSize(hf.pointSize() + 6)
        hf.setBold(True)
        heading.setFont(hf)
        layout.addWidget(heading)

        sub = QtWidgets.QLabel(
            "Get the files needed to run Pyamoto. ")
        sub.setWordWrap(True)
        sub.setStyleSheet("color: palette(mid);")
        layout.addWidget(sub)
        layout.addSpacing(4)

        # Data row — extract to user_data_path/data so it persists
        # across app updates and is never bundled inside the app.
        self.dataRow = _DownloadRow(
            title="Game Data",
            description="Core resources required by Pyamoto to create levels.",
            url=DATA_DOWNLOAD_URL,
            tmp_name="_data_download.zip",
            extract_dir=os.path.join(globals.user_data_path, 'data'),
            required=True,
        )
        self.dataRow._onFinishedExtra = self._onDataDownloaded
        layout.addWidget(self.dataRow)

        # Objects row — user_data_path/Objects/
        self.objRow = _DownloadRow(
            title="Object Library",
            description=(
                "Add individual objects from the game's tilesets to your level. "
                "You can always download this later from Preferences > Resources."),
            url=OBJECTS_DOWNLOAD_URL,
            tmp_name="_objects_download.zip",
            extract_dir=os.path.join(globals.user_data_path, 'Objects'),
            required=False,
        )
        layout.addWidget(self.objRow)

        layout.addStretch(1)

        # Seed initial state
        if _data_present():
            self.dataRow.setAlreadyPresent()
        if _objects_present():
            self.objRow.setAlreadyPresent()

    def _onDataDownloaded(self):
        globals.actor_data_path = os.path.join(globals.user_data_path, 'data').replace("\\", "/")

    def _onDownloadComplete(self):
        self.readyChanged.emit(self.isReady())

    def isReady(self):
        return _data_present() or self.dataRow.downloaded

    def objectsDownloaded(self):
        return self.objRow.downloaded


# ---------------------------------------------------------------------------

class _GamePathPage(QtWidgets.QWidget):
    pathValidityChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path_edits = {}  # folder → QLineEdit

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(32, 16, 32, 16)
        layout.setSpacing(12)

        heading = QtWidgets.QLabel("Set Game Path")
        hf = heading.font()
        hf.setPointSize(hf.pointSize() + 6)
        hf.setBold(True)
        heading.setFont(hf)
        layout.addWidget(heading)

        sub = QtWidgets.QLabel(
            "Point Pyamoto to your game files to load levels properly.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color: palette(mid);")
        layout.addWidget(sub)
        layout.addSpacing(8)

        from . import gamedefs as _gd

        games_group = QtWidgets.QGroupBox("Game Paths")
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
                "Select the Course folder (with the Unit folder next to it)…" if def_.isDX
                else "Select the course_res_pack folder…")
            existing = setting('GamePath_' + folder, setting('GamePath', '') if folder == 'NSMBU' else '')
            if existing:
                path_edit.setText(str(existing))
            self._path_edits[folder] = path_edit

            valid_lbl = QtWidgets.QLabel()
            valid_lbl.setStyleSheet('font-size: 11px;')

            def _make_validator(edit, lbl, folder=folder, isDX=def_.isDX):
                def _v():
                    p = edit.text().strip()
                    ok = isValidGamePath(p, folder) if p else False
                    badMsg = ('✗ Needs 1-1.sarc in this folder and a Unit folder next to it' if isDX
                              else '✗ No valid game files found in this folder')
                    lbl.setText('✓ Valid game path' if ok else (badMsg if p else ''))
                    lbl.setStyleSheet('color: #27ae60; font-size: 11px;' if ok
                                      else 'color: #c0392b; font-size: 11px;' if p
                                      else 'font-size: 11px;')
                    self.pathValidityChanged.emit(self.isPathValid())
                edit.textChanged.connect(_v)
                _v()

            _make_validator(path_edit, valid_lbl)

            def _make_browser(edit):
                def _b():
                    d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Game Folder", edit.text())
                    if d:
                        edit.setText(d)
                return _b

            browse_btn = QtWidgets.QPushButton("Browse…")
            browse_btn.setFixedWidth(90)
            browse_btn.clicked.connect(_make_browser(path_edit))

            path_row.addWidget(path_edit)
            path_row.addWidget(browse_btn)
            indent_lay.addLayout(path_row)
            indent_lay.addWidget(valid_lbl)
            games_vbox.addWidget(indent_w)

            if idx_g < len(base_games) - 1:
                games_vbox.addSpacing(4)

        layout.addWidget(games_group)
        layout.addStretch(1)

    def isPathValid(self):
        return any(isValidGamePath(e.text().strip(), folder) for folder, e in self._path_edits.items())


# ---------------------------------------------------------------------------

class _ThemePage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(32, 16, 32, 16)
        layout.setSpacing(12)

        heading = QtWidgets.QLabel("Choose a Theme")
        hf = heading.font()
        hf.setPointSize(hf.pointSize() + 6)
        hf.setBold(True)
        heading.setFont(hf)
        layout.addWidget(heading)

        sub = QtWidgets.QLabel(
            "Customize the look of Pyamoto. You can change this later in Preferences.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color: palette(mid);")
        layout.addWidget(sub)
        layout.addSpacing(8)

        from .dialogs import PreferencesDialog

        # Embed the themes tab widget inline
        ThemesTabCls = PreferencesDialog.getThemesTab(QtWidgets.QWidget)
        self.themesWidget = ThemesTabCls()
        self.themesWidget.NonWinStyle.currentIndexChanged.connect(self._applyStyle)
        layout.addWidget(self.themesWidget)
        layout.addStretch(1)

    def _applyStyle(self):
        SetAppStyle(self.themesWidget.NonWinStyle.currentText())

    def themeBox(self):
        return self.themesWidget.themeBox

    def nonWinStyle(self):
        return self.themesWidget.NonWinStyle


# ---------------------------------------------------------------------------

class _AllSetPage(QtWidgets.QWidget):

    def __init__(self, first_run=True, parent=None):
        super().__init__(parent)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.setSpacing(0)

        logo_label = QtWidgets.QLabel()
        logo_label.setAlignment(Qt.AlignHCenter)
        pix = _make_logo_pixmap(90)
        if pix:
            logo_label.setPixmap(pix)
        logo_label.setFixedHeight(90)
        layout.addWidget(logo_label)
        layout.addSpacing(16)

        title = QtWidgets.QLabel("You're all set!")
        title.setAlignment(Qt.AlignHCenter)
        tf = title.font()
        tf.setPointSize(tf.pointSize() + 8)
        tf.setBold(True)
        title.setFont(tf)
        layout.addWidget(title)
        layout.addSpacing(8)

        if first_run:
            msg = "Pyamoto is configured and ready to use.\nHave fun making levels!"
        else:
            msg = "Your configuration has been updated successfully."

        desc = QtWidgets.QLabel(msg)
        desc.setAlignment(Qt.AlignHCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: palette(mid);")
        layout.addWidget(desc)

        layout.addStretch(1)


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------

# Page indices
_PAGE_WELCOME = 0
_PAGE_DOWNLOAD = 1
_PAGE_GAMEPATH = 2
_PAGE_THEME = 3
_PAGE_ALLSET = 4
_NUM_PAGES = 5


class InteractiveSetupDialog(QtWidgets.QDialog):
    """
    Five-page interactive setup wizard.
    """

    def __init__(self, first_run=True, parent=None):
        super().__init__(parent)
        self._first_run = first_run

        self.setWindowTitle("Pyamoto Setup")
        self.setMinimumSize(640, 500)
        self.setFixedSize(680, 520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        icon_p = _icon_path()
        if icon_p:
            self.setWindowIcon(QtGui.QIcon(icon_p))

        # ── Root layout ──────────────────────────────────────────────────
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Step dots
        dots_bar = QtWidgets.QWidget()
        dots_bar.setFixedHeight(32)
        dots_layout = QtWidgets.QHBoxLayout(dots_bar)
        dots_layout.setContentsMargins(0, 4, 0, 4)
        self._dots = _StepDots(_NUM_PAGES)
        dots_layout.addStretch(1)
        dots_layout.addWidget(self._dots)
        dots_layout.addStretch(1)
        root.addWidget(dots_bar)

        # Separator
        sep_top = QtWidgets.QFrame()
        sep_top.setFrameShape(QtWidgets.QFrame.HLine)
        sep_top.setFrameShadow(QtWidgets.QFrame.Sunken)
        root.addWidget(sep_top)

        # Pages
        self._stack = QtWidgets.QStackedWidget()
        root.addWidget(self._stack, 1)

        self._welcomePage = _WelcomePage()
        self._downloadPage = _DownloadPage()
        self._gamePathPage = _GamePathPage()
        self._themePage = _ThemePage()
        self._allSetPage = _AllSetPage(first_run=first_run)

        self._stack.addWidget(self._welcomePage)
        self._stack.addWidget(self._downloadPage)
        self._stack.addWidget(self._gamePathPage)
        self._stack.addWidget(self._themePage)
        self._stack.addWidget(self._allSetPage)

        # Separator
        sep_bot = QtWidgets.QFrame()
        sep_bot.setFrameShape(QtWidgets.QFrame.HLine)
        sep_bot.setFrameShadow(QtWidgets.QFrame.Sunken)
        root.addWidget(sep_bot)

        # Navigation bar
        nav = QtWidgets.QWidget()
        nav.setFixedHeight(56)
        nav_layout = QtWidgets.QHBoxLayout(nav)
        nav_layout.setContentsMargins(20, 8, 20, 8)
        nav_layout.setSpacing(8)

        self._backBtn = QtWidgets.QPushButton("← Back")
        self._backBtn.setFixedWidth(100)
        self._backBtn.clicked.connect(self._goBack)
        nav_layout.addWidget(self._backBtn)

        nav_layout.addStretch(1)

        self._skipBtn = QtWidgets.QPushButton("Skip")
        self._skipBtn.setFixedWidth(80)
        self._skipBtn.clicked.connect(self._skip)
        nav_layout.addWidget(self._skipBtn)

        self._nextBtn = QtWidgets.QPushButton("Next →")
        self._nextBtn.setFixedWidth(120)
        self._nextBtn.setDefault(True)
        self._nextBtn.clicked.connect(self._goNext)
        nav_layout.addWidget(self._nextBtn)

        root.addWidget(nav)

        # Wire up signals
        self._downloadPage.readyChanged.connect(self._refreshNav)
        self._gamePathPage.pathValidityChanged.connect(self._refreshNav)

        self._goToPage(_PAGE_WELCOME)

    # ── Navigation ───────────────────────────────────────────────────────

    def _currentIndex(self):
        return self._stack.currentIndex()

    def _goToPage(self, idx):
        self._stack.setCurrentIndex(idx)
        self._dots.setCurrent(idx)
        self._refreshNav()
        # Persist all settings (including SetupComplete=True) as soon as the
        # All Set page is reached. This way, closing the window here still
        # means the wizard won't re-run on next launch.
        if idx == _PAGE_ALLSET and self._first_run:
            self.applySettings()

    def _goNext(self):
        cur = self._currentIndex()
        if cur == _PAGE_ALLSET:
            self.accept()
            return
        self._goToPage(cur + 1)

    def _goBack(self):
        cur = self._currentIndex()
        if cur > 0:
            self._goToPage(cur - 1)

    def _skip(self):
        cur = self._currentIndex()
        if cur == _PAGE_GAMEPATH:
            msg = QtWidgets.QMessageBox(self)
            msg.setWindowTitle("Skip Game Path?")
            msg.setIcon(QtWidgets.QMessageBox.Warning)
            msg.setText(
                "Without a game path, Pyamoto cannot open levels from the original game.\n\n"
                "You can set the game path later in Preferences > Game Setup.")
            msg.setStandardButtons(
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
            msg.button(QtWidgets.QMessageBox.Yes).setText("Skip Anyway")
            msg.button(QtWidgets.QMessageBox.Cancel).setText("Set Path")
            if msg.exec_() == QtWidgets.QMessageBox.Yes:
                for edit in self._gamePathPage._path_edits.values():
                    edit.clear()
                self._goToPage(cur + 1)
        else:
            self._goToPage(cur + 1)

    def _refreshNav(self):
        cur = self._currentIndex()

        # Back button
        self._backBtn.setVisible(cur > _PAGE_WELCOME)

        # Skip button — only on game path page
        self._skipBtn.setVisible(cur == _PAGE_GAMEPATH)

        # Next/Finish/hidden depending on page
        if cur == _PAGE_WELCOME:
            self._nextBtn.setText("Get Started →")
            self._nextBtn.setVisible(True)
            self._nextBtn.setEnabled(True)

        elif cur == _PAGE_DOWNLOAD:
            self._nextBtn.setText("Next →")
            self._nextBtn.setVisible(True)
            self._nextBtn.setEnabled(self._downloadPage.isReady())

        elif cur == _PAGE_GAMEPATH:
            self._nextBtn.setText("Next →")
            self._nextBtn.setVisible(True)
            self._nextBtn.setEnabled(self._gamePathPage.isPathValid())

        elif cur == _PAGE_THEME:
            self._nextBtn.setText("Next →")
            self._nextBtn.setVisible(True)
            self._nextBtn.setEnabled(True)

        elif cur == _PAGE_ALLSET:
            self._nextBtn.setText("Finish")
            self._nextBtn.setVisible(True)
            self._nextBtn.setEnabled(True)
            self._backBtn.setVisible(False)
            self._skipBtn.setVisible(False)

    # ── Settings application ─────────────────────────────────────────────

    def applySettings(self):
        from .misc import SetGamePath

        # Game paths — save all per-game paths
        first_valid_folder = None
        for folder, edit in self._gamePathPage._path_edits.items():
            path = edit.text().strip()
            setSetting('GamePath_' + folder, path)
            if folder == 'NSMBU':
                setSetting('GamePath', path)  # backward compat
            if path and isValidGamePath(path, folder) and first_valid_folder is None:
                first_valid_folder = folder
                # (the per-game path was saved just above; only mirror it onto the
                # loaded game definition if that is the same game)
                if globals.gamedef is not None and getattr(globals.gamedef, 'gamepath', None) == folder:
                    SetGamePath(path)

        setSetting('LastBaseGame', first_valid_folder or next(iter(self._gamePathPage._path_edits), 'NSMBU'))

        # Objects — set ObjPath if downloaded
        if self._downloadPage.objectsDownloaded():
            obj_path = os.path.join(globals.user_data_path, 'Objects')
            if isValidObjectsPath(obj_path):
                setSetting('ObjPath', obj_path)

        # Theme
        setSetting('Theme', self._themePage.themeBox().currentText())
        setSetting('uiStyle', self._themePage.nonWinStyle().currentText())

        # Mark setup complete
        setSetting('SetupComplete', True)


# ---------------------------------------------------------------------------
# Backward-compatible Wizard alias (used by app.py during first run)
# ---------------------------------------------------------------------------

class Wizard(InteractiveSetupDialog):
    """Legacy alias so existing app.py import still works."""

    def __init__(self):
        super().__init__(first_run=True)
        self.finished_ok = False

    def exec_(self):
        result = super().exec_()
        self.finished_ok = (result == QtWidgets.QDialog.Accepted)
        return result
