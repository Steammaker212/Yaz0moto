#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Update checks and the update dialogs of packaged Yaz0moto builds.

Yaz0moto finds the newest release and asks the user; the downloading and installing is done
by the separate updater program (yaz0moto_updater.py, built as Yaz0moto-Updater in the
`updater` folder of each package):

1. `Yaz0moto-Updater prepare` downloads, verifies and unpacks the update while a progress
   box shows here (it reports on stdout).
2. Yaz0moto closes (after the unsaved-work prompt) and starts `Yaz0moto-Updater install`,
   which waits for it to exit, swaps the new files in and starts the new version.
3. The updater can't overwrite itself while it runs, so it leaves the new updater as
   `updater.new`; at its next start Yaz0moto puts that in place (finish_previous_update).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import json
from dataclasses import dataclass
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

import yaz0moto_updater as core
from yaz0moto_updater import (  # noqa: F401  (re-exported for the rest of the editor and the tests)
    CHANNEL_NIGHTLY, CHANNEL_OFF, CHANNEL_RELEASE, ReleaseInfo, UpdateError, version_from_tag,
)

from . import globals
from .misc import setting, setSetting


GITHUB_REPO = core.GITHUB_REPO
_RELEASES_URL = core.RELEASES_URL

# Kept as an alias so existing callers and old settings continue to work.
CHANNEL_STABLE = CHANNEL_RELEASE

_CHANNEL_LABELS = ['Release (Latest)', 'Nightly (Pre-release)', 'Off']
_CHANNEL_VALUES = [CHANNEL_RELEASE, CHANNEL_NIGHTLY, CHANNEL_OFF]

_safe_extract = core.safe_extract
_release_from_json = core.release_from_json


@dataclass(frozen=True)
class InstallLocation:
    kind: str
    target: Path
    executable: Path


def _user_agent():
    return f'Yaz0moto/{globals.MiyamotoVersion} updater'


def _default_channel():
    # A nightly build follows the nightlies: the latest release is usually older than it
    return CHANNEL_NIGHTLY if globals.MiyamotoReleaseType == 'nightly' else CHANNEL_RELEASE


def _setting(name, default=None):
    try:
        return setting(name, default)
    except Exception:  # no settings loaded (tests)
        return default


def _current_channel():
    value = _setting('UpdateChannel', None)
    if value == 'stable':
        return CHANNEL_RELEASE
    if value in _CHANNEL_VALUES:
        return value
    return _default_channel()


def _is_skipped(tag):
    skipped = _setting('SkippedUpdates', [])
    return isinstance(skipped, list) and tag in skipped


def _skip_release(tag):
    skipped = _setting('SkippedUpdates', [])
    if not isinstance(skipped, list):
        skipped = []
    if tag not in skipped:
        skipped.append(tag)
        setSetting('SkippedUpdates', skipped[-20:])


def _latest_release(channel):
    return core.latest_release(channel, _user_agent())


def _installed_tag():
    """The release the updater installed, while this is still the version it installed."""
    if _setting('InstalledUpdateVersion') == globals.MiyamotoVersion:
        return _setting('InstalledUpdateTag')
    return None


def _is_newer(release):
    return core.is_newer(release, globals.MiyamotoVersion, globals.MiyamotoReleaseType, _installed_tag(),
                         getattr(globals, 'MiyamotoBuildDate', None))


def _asset_for_platform(release, system=None, machine=None, appimage=None):
    return core.asset_for_platform(release, system, machine, appimage)


def _install_location():
    appimage = os.environ.get('APPIMAGE')
    if sys.platform.startswith('linux') and appimage:
        target = Path(appimage).expanduser().resolve()
        return InstallLocation(core.KIND_APPIMAGE, target, target)

    if not getattr(sys, 'frozen', False):
        return None

    executable = Path(sys.executable).resolve()
    if sys.platform == 'darwin':
        app = next((parent for parent in (executable, *executable.parents)
                    if parent.name.endswith('.app')), None)
        if app is None:
            raise UpdateError('Could not locate the installed Yaz0moto app bundle.')
        return InstallLocation(core.KIND_BUNDLE, app, app / 'Contents' / 'MacOS' / 'Yaz0moto')

    return InstallLocation(core.KIND_DIRECTORY, executable.parent, executable)


def _bundled_updater(location):
    """Where the updater program is in this installation."""
    name = core.updater_executable_name()
    if location.kind == core.KIND_BUNDLE:
        return location.target / 'Contents' / 'Resources' / core.UPDATER_DIR / name
    if location.kind == core.KIND_APPIMAGE:
        appdir = os.environ.get('APPDIR') or str(Path(sys.executable).resolve().parent)
        return Path(appdir) / core.UPDATER_DIR / name
    return location.target / core.UPDATER_DIR / name


def _check_location(location):
    if location is None:
        raise UpdateError('Automatic updates are available only in packaged Yaz0moto builds.')
    if not location.target.exists():
        raise UpdateError('Current Yaz0moto installation could not be found.')
    if '/AppTranslocation/' in str(location.target):
        raise UpdateError('macOS is running Yaz0moto from a temporary read-only copy, so it can\'t be '
                          'updated. Move Yaz0moto.app to the Applications folder (or any other folder), '
                          'open it from there and try again.')
    folder = location.target if location.kind == core.KIND_DIRECTORY else location.target.parent
    if not os.access(str(folder), os.W_OK):
        raise UpdateError('Yaz0moto does not have permission to update this installation '
                          f'({folder}). Move it to a folder you can write to, or update it by hand.')


def _prepare_work(location):
    """
    The folder the update is downloaded and unpacked in: on the installation's drive, since
    the new files are moved (not copied) into place. A folder installation keeps it inside
    itself; a bundle or AppImage, which is swapped as a whole, next to itself.
    """
    try:
        if location.kind == core.KIND_DIRECTORY:
            work = location.target / core.WORK_DIR
            if work.exists():
                shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True, exist_ok=True)
            return work
        return Path(tempfile.mkdtemp(prefix='.yaz0moto-update-', dir=str(location.target.parent)))
    except OSError as exc:
        raise UpdateError('Yaz0moto does not have permission to update this installation '
                          f'({exc}). Move it to a folder you can write to, or update it by hand.') from exc


def _updater_for(location, work):
    """
    The updater program to run. A bundle or AppImage is replaced as a whole (and an
    AppImage's files disappear when Yaz0moto exits), so its updater runs from a copy.
    """
    program = _bundled_updater(location)
    if not program.is_file():
        raise UpdateError('The updater program is missing from this installation '
                          f'({program}).\n\nDownload the new version from {_RELEASES_URL}')
    if location.kind == core.KIND_DIRECTORY:
        return program
    copy = work / 'updater-run'
    shutil.copytree(str(program.parent), str(copy), symlinks=True)
    return copy / program.name


def _error_file():
    return Path(globals.user_data_path) / 'update-error.txt'


def _log_file():
    return Path(globals.user_data_path) / 'update.log'


def _hidden_window_flags():
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform == 'win32' else 0


class _UpdateChecker(QtCore.QObject):
    update_found = QtCore.pyqtSignal(object)
    up_to_date = QtCore.pyqtSignal()
    failed = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def start(self, channel):
        self._channel = channel
        threading.Thread(target=self._run, name='Yaz0moto update check', daemon=True).start()

    def _run(self):
        try:
            release = _latest_release(self._channel)
            if release is not None and _is_newer(release) and not _is_skipped(release.tag):
                self.update_found.emit(release)
            else:
                self.up_to_date.emit()
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit('Unexpected error while checking for updates.')
        finally:
            self.finished.emit()


class _UpdateWorker(QtCore.QObject):
    """Runs `Yaz0moto-Updater prepare` and relays its progress."""
    progress = QtCore.pyqtSignal(int)
    status = QtCore.pyqtSignal(str)
    ready = QtCore.pyqtSignal(object, object, object, object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._process = None
        self._cancelled = False

    def start(self, release):
        self._release = release
        threading.Thread(target=self._run, name='Yaz0moto update download', daemon=True).start()

    def cancel(self):
        self._cancelled = True
        process = self._process
        if process is not None and process.poll() is None:
            process.kill()

    def _run(self):
        work = None
        try:
            location = _install_location()
            _check_location(location)
            asset = _asset_for_platform(self._release, appimage=location.kind == core.KIND_APPIMAGE)
            if asset is None:
                raise UpdateError('This release has no update package for the current platform.')

            work = _prepare_work(location)
            program = _updater_for(location, work)
            command = [str(program), 'prepare', '--url', asset['browser_download_url'],
                       '--name', asset['name'], '--kind', location.kind, '--work', str(work)]
            if asset.get('size') is not None:
                command += ['--size', str(asset['size'])]
            if isinstance(asset.get('digest'), str):
                command += ['--digest', asset['digest']]

            staged, error, other = self._prepare(command, work)
            if self._cancelled:
                raise UpdateError('cancelled')
            if staged is None:
                raise UpdateError(error or 'The updater stopped without preparing the update.'
                                  + ('\n\n' + '\n'.join(other[-8:]) if other else ''))
            self.progress.emit(100)
            self.ready.emit(location, Path(staged), work, program)
        except UpdateError as exc:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
            self.failed.emit('' if self._cancelled else str(exc))
        except Exception as exc:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
            self.failed.emit(f'Unexpected error while preparing the update: {exc}')

    def _prepare(self, command, work):
        staged = error = None
        other = []
        try:
            self._process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=str(work), creationflags=_hidden_window_flags(),
                universal_newlines=True, encoding='utf-8', errors='replace')
        except OSError as exc:
            raise UpdateError(f'Could not start the updater: {exc}') from exc

        for line in self._process.stdout:
            line = line.strip()
            try:
                message = json.loads(line)
            except ValueError:
                if line:
                    other.append(line)
                continue
            if not isinstance(message, dict):
                continue
            event = message.get('event')
            if event == 'progress':
                total = message.get('total') or 0
                self.progress.emit(min(99, int(message.get('received', 0) * 100 / total)) if total else 0)
            elif event == 'status':
                self.status.emit(str(message.get('message', '')))
            elif event == 'ready':
                staged = message.get('staged')
            elif event == 'error':
                error = str(message.get('message', ''))
        self._process.wait()
        return staged, error, other


class _UpdateDialog(QtWidgets.QDialog):
    def __init__(self, release, parent=None):
        super().__init__(parent)
        self._release = release
        channel = 'Nightly' if release.channel == CHANNEL_NIGHTLY else 'Release'
        self.setWindowTitle(f'Yaz0moto {channel} Update Available')
        self.setWindowFlag(QtCore.Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(480)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 22, 24, 20)

        headline = QtWidgets.QLabel(f'{release.title} is available')
        font = headline.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        headline.setFont(font)
        layout.addWidget(headline)

        current = QtWidgets.QLabel(
            f'Installed: {globals.MiyamotoVersion} ({globals.MiyamotoReleaseType})\n'
            f'Available: {release.version} ({channel.lower()})'
        )
        layout.addWidget(current)

        if release.body.strip():
            notes = QtWidgets.QPlainTextEdit(release.body.strip())
            notes.setReadOnly(True)
            notes.setMaximumHeight(150)
            layout.addWidget(notes)

        buttons = QtWidgets.QDialogButtonBox()
        skip = buttons.addButton('Skip this version', QtWidgets.QDialogButtonBox.DestructiveRole)
        skip.clicked.connect(self._skip)
        page = buttons.addButton('View release', QtWidgets.QDialogButtonBox.ActionRole)
        page.clicked.connect(self._open_page)
        later = buttons.addButton('Later', QtWidgets.QDialogButtonBox.RejectRole)
        later.clicked.connect(self.reject)
        install = buttons.addButton('Install update', QtWidgets.QDialogButtonBox.AcceptRole)
        install.setDefault(True)
        install.clicked.connect(self._install)
        layout.addWidget(buttons)

    def _skip(self):
        _skip_release(self._release.tag)
        self.reject()

    def _open_page(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(self._release.page_url))

    def _install(self):
        self.accept()
        # Let this nested dialog unwind before closing any dialog underneath it.
        QtCore.QTimer.singleShot(0, lambda: _start_install(self._release))


_checker = None
_worker = None
_progress = None
_restore_unsaved_state = False
_installing_release = None


def check_for_updates():
    finish_previous_update()
    channel = _current_channel()
    if channel != CHANNEL_OFF:
        _start_check(channel, manual=False)


def check_for_updates_now(channel):
    if channel == 'stable':
        channel = CHANNEL_RELEASE
    if channel == CHANNEL_OFF:
        _show_info('Update checks are disabled.')
        return
    _start_check(channel, manual=True)


def _start_check(channel, manual=False):
    global _checker
    if _checker is not None:
        if manual:
            _show_info('An update check is already running.')
        return
    _checker = _UpdateChecker()
    _checker.update_found.connect(_on_update_found)
    if manual:
        _checker.up_to_date.connect(lambda: _show_info('Yaz0moto is up to date.'))
        _checker.failed.connect(_show_error)
    else:
        # Don't interrupt startup with a dialog, but don't fail silently either
        _checker.failed.connect(_show_status)
    _checker.finished.connect(_check_finished)
    _checker.start(channel)


def _check_finished():
    global _checker
    _checker = None


def _on_update_found(release):
    _UpdateDialog(release, globals.mainWindow).exec_()


def _start_install(release):
    """Close an originating modal dialog before prompting and downloading."""
    modal = QtWidgets.QApplication.activeModalWidget()
    if isinstance(modal, QtWidgets.QDialog) and modal is not globals.mainWindow:
        modal.reject()
        QtCore.QTimer.singleShot(0, lambda: _confirm_install(release))
        return
    _confirm_install(release)


def _confirm_install(release):
    """Resolve unsaved work before any update download begins."""
    global _restore_unsaved_state
    if _worker is not None:
        return
    _restore_unsaved_state = False
    window = globals.mainWindow
    was_dirty = bool(globals.Dirty)
    if window is not None and window.CheckDirty():
        return

    # CheckDirty leaves Dirty set when Discard is chosen. Clear it temporarily
    # so closing after a successful download does not prompt a second time.
    # Restore it if update preparation fails and editor remains open.
    _restore_unsaved_state = was_dirty and bool(globals.Dirty)
    if _restore_unsaved_state:
        globals.Dirty = False
        if window is not None:
            window.UpdateTitle()

    _begin_download(release)


def _begin_download(release):
    global _worker, _progress, _installing_release
    if _worker is not None:
        return
    _installing_release = release
    _progress = QtWidgets.QProgressDialog(
        'Downloading and verifying update...', 'Cancel', 0, 100, globals.mainWindow
    )
    _progress.setWindowTitle('Yaz0moto Update')
    _progress.setWindowModality(QtCore.Qt.ApplicationModal)
    _progress.setAutoClose(False)
    _progress.setAutoReset(False)
    _progress.setMinimumDuration(0)
    _progress.setValue(0)
    _progress.show()
    _progress.raise_()
    _progress.activateWindow()

    _worker = _UpdateWorker()
    _worker.progress.connect(_progress.setValue)
    _worker.status.connect(_progress.setLabelText)
    _worker.failed.connect(_install_failed)
    _worker.ready.connect(_install_ready)
    _progress.canceled.connect(_worker.cancel)
    _worker.start(release)


def _close_progress():
    global _worker, _progress
    if _progress is not None:
        try:
            _progress.canceled.disconnect()
        except TypeError:
            pass
        _progress.close()
    _worker = None
    _progress = None


def _install_failed(message):
    _close_progress()
    _restore_dirty_state()
    if message:  # empty when cancelled
        _show_error(message)


def _install_ready(location, staged, work, program):
    _close_progress()

    window = globals.mainWindow
    if window is not None and not window.close():
        shutil.rmtree(work, ignore_errors=True)
        _restore_dirty_state()
        return

    command = [str(program), 'install', '--kind', location.kind, '--target', str(location.target),
               '--staged', str(staged), '--work', str(work), '--pid', str(os.getpid()),
               '--log', str(_log_file()), '--error-file', str(_error_file())]
    try:
        _error_file().unlink()
    except OSError:
        pass
    try:
        _launch_installer(command, location)
    except (OSError, subprocess.SubprocessError) as exc:
        shutil.rmtree(work, ignore_errors=True)
        if window is not None:
            window.show()
        _restore_dirty_state()
        _show_error(f'Could not start the updater: {exc}')
        return

    if _installing_release is not None:
        setSetting('PendingUpdateTag', _installing_release.tag)
    _clear_dirty_restore()
    # The updater waits for Yaz0moto to exit, so make sure it does (the window is
    # closed and the level saved by now), even if something keeps it running
    QtWidgets.QApplication.quit()
    timer = threading.Timer(15, os._exit, (0,))
    timer.daemon = True
    timer.start()


def _launch_installer(command, location):
    """Starts the updater detached, so it outlives Yaz0moto."""
    cwd = str(location.target.parent)
    if sys.platform == 'win32':
        flags = _hidden_window_flags() | 0x00000200  # CREATE_NEW_PROCESS_GROUP
        # Out of Yaz0moto's job (if a launcher put it in one), so the updater isn't killed when
        # Yaz0moto exits; a job that doesn't allow that refuses, then it's started as before
        try:
            subprocess.Popen(command, cwd=cwd, close_fds=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=flags | 0x01000000)  # CREATE_BREAKAWAY_FROM_JOB
        except OSError:
            subprocess.Popen(command, cwd=cwd, close_fds=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    else:
        subprocess.Popen(command, cwd=cwd, close_fds=True, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- after an update

def finish_previous_update():
    """
    At startup: says why the last update failed (once), remembers which release was
    installed, and puts the new updater the last update left (updater.new) in place.
    """
    failed = _report_failed_install()

    pending = _setting('PendingUpdateTag')
    if pending:
        setSetting('PendingUpdateTag', None)
        if not failed:
            setSetting('InstalledUpdateTag', pending)
            setSetting('InstalledUpdateVersion', globals.MiyamotoVersion)

    try:
        location = _install_location()
    except UpdateError:
        return
    if location is None or location.kind != core.KIND_DIRECTORY:
        return  # bundles and AppImages bring their new updater with them

    # The updater that started this instance may still be closing: wait a little
    QtCore.QTimer.singleShot(5000, lambda: install_staged_updater(location.target))


def install_staged_updater(target):
    """Replaces the updater folder with updater.new (left by the last update), if there is one."""
    target = Path(target)
    current = target / core.UPDATER_DIR
    staged = target / core.UPDATER_STAGED_DIR
    old = target / (core.UPDATER_DIR + '.old')

    for leftover in (old, target / core.BACKUP_DIR, target / core.WORK_DIR):
        if leftover.exists() and _worker is None:
            shutil.rmtree(leftover, ignore_errors=True)
    if not staged.is_dir():
        return False
    if not (staged / core.updater_executable_name()).is_file():
        shutil.rmtree(staged, ignore_errors=True)  # incomplete: keep the working one
        return False
    try:
        if current.exists():
            current.rename(old)
        staged.rename(current)
    except OSError:
        if not current.exists() and old.exists():
            try:
                old.rename(current)
            except OSError:
                pass
        return False  # tried again at the next start
    shutil.rmtree(old, ignore_errors=True)
    return True


def _report_failed_install():
    """Shows why the last update couldn't be installed, once. Returns whether it failed."""
    paths = [_error_file()]
    try:
        location = _install_location()
    except UpdateError:
        location = None
    if location is not None:
        # Where the install script of older versions wrote it
        paths.append(location.target.parent / 'Yaz0moto-update-error.txt')

    for path in paths:
        if not path.is_file():
            continue
        try:
            details = path.read_text(encoding='utf-8', errors='replace').strip()
            path.unlink()
        except OSError:
            continue
        _show_error('The last update could not be installed, so this version was kept.\n\n'
                    + details[:1500] + f'\n\nDetails: {_log_file()}')
        return True
    return False


def _restore_dirty_state():
    global _restore_unsaved_state
    if _restore_unsaved_state:
        globals.Dirty = True
        window = globals.mainWindow
        if window is not None:
            window.UpdateTitle()
    _restore_unsaved_state = False


def _clear_dirty_restore():
    global _restore_unsaved_state
    _restore_unsaved_state = False


def _show_info(text):
    QtWidgets.QMessageBox.information(globals.mainWindow, 'Yaz0moto Update', text)


def _show_error(text):
    QtWidgets.QMessageBox.warning(globals.mainWindow, 'Yaz0moto Update', text)


def _show_status(text):
    if globals.mainWindow is not None:
        globals.mainWindow.statusBar().showMessage('Update check failed: ' + text, 15000)
