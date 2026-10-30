#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""GitHub release checker and self-updater for packaged Yaz0moto builds."""

import hashlib
import os
import platform
import posixpath
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import requests
from PyQt5 import QtCore, QtGui, QtWidgets

from . import globals
from .misc import setting, setSetting


GITHUB_REPO = 'Steammaker212/Yaz0moto'
_API_BASE = f'https://api.github.com/repos/{GITHUB_REPO}/releases'
_API_LATEST = f'{_API_BASE}/latest'
_API_RECENT = f'{_API_BASE}?per_page=30'
_RELEASES_URL = f'https://github.com/{GITHUB_REPO}/releases'
_MAX_EXTRACTED_SIZE = 4 * 1024 * 1024 * 1024

_HEADERS = {
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': f'Yaz0moto/{globals.MiyamotoVersion} updater',
}

CHANNEL_RELEASE = 'release'
CHANNEL_NIGHTLY = 'nightly'
CHANNEL_OFF = 'off'

# Kept as an alias so existing callers and old settings continue to work.
CHANNEL_STABLE = CHANNEL_RELEASE

_CHANNEL_LABELS = ['Release (Latest)', 'Nightly (Pre-release)', 'Off']
_CHANNEL_VALUES = [CHANNEL_RELEASE, CHANNEL_NIGHTLY, CHANNEL_OFF]


class UpdateError(RuntimeError):
    """An expected update failure suitable for display to the user."""


@dataclass(frozen=True)
class ReleaseInfo:
    channel: str
    tag: str
    version: str
    title: str
    page_url: str
    body: str
    assets: tuple


@dataclass(frozen=True)
class InstallLocation:
    kind: str
    target: Path
    executable: Path


def _default_channel():
    return CHANNEL_RELEASE


def _current_channel():
    value = setting('UpdateChannel', None)
    if value == 'stable':
        return CHANNEL_RELEASE
    if value in _CHANNEL_VALUES:
        return value
    return _default_channel()


def _is_skipped(tag):
    skipped = setting('SkippedUpdates', [])
    return isinstance(skipped, list) and tag in skipped


def _skip_release(tag):
    skipped = setting('SkippedUpdates', [])
    if not isinstance(skipped, list):
        skipped = []
    if tag not in skipped:
        skipped.append(tag)
        setSetting('SkippedUpdates', skipped[-20:])


def _fetch_json(url):
    try:
        response = requests.get(url, headers=_HEADERS, timeout=15)
        if response.status_code == 403:
            raise UpdateError('GitHub refused the update check. Please try again later.')
        if response.status_code == 404 and url == _API_LATEST:
            raise UpdateError('No GitHub Latest release has been published yet.')
        if not response.ok:
            raise UpdateError(f'GitHub update check failed (HTTP {response.status_code}).')
        response.raise_for_status()
    except UpdateError:
        raise
    except requests.RequestException as exc:
        raise UpdateError(f'Could not connect to GitHub: {exc}') from exc

    try:
        return response.json()
    except ValueError as exc:
        raise UpdateError('GitHub returned an invalid update response.') from exc


def version_from_tag(tag):
    """
    The version number in a release tag: 'v1.2.0', 'release-1.2.0' and
    'Yaz0moto-v1.2.0' all give '1.2.0'. Other tags are returned stripped.
    """
    tag = tag.strip()
    match = re.fullmatch(r'(?:yaz0moto[-_ ]?)?(?:release[-_ ]?)?v?(\d+(?:\.\d+)*)', tag, re.IGNORECASE)
    return match.group(1) if match else tag


def _release_from_json(data, channel):
    if not isinstance(data, dict):
        raise UpdateError('GitHub returned an invalid release record.')

    tag = data.get('tag_name')
    assets = data.get('assets')
    if not isinstance(tag, str) or not tag or not isinstance(assets, list):
        raise UpdateError('GitHub release metadata is incomplete.')

    valid_assets = tuple(asset for asset in assets if (
        isinstance(asset, dict)
        and isinstance(asset.get('name'), str)
        and isinstance(asset.get('browser_download_url'), str)
    ))
    version = version_from_tag(tag) if channel == CHANNEL_RELEASE else tag
    if channel == CHANNEL_NIGHTLY:
        match = re.search(r'-([0-9a-fA-F]{7,40})$', tag)
        if match:
            version = match.group(1)

    return ReleaseInfo(
        channel=channel,
        tag=tag,
        version=version,
        title=str(data.get('name') or tag),
        page_url=str(data.get('html_url') or f'{_RELEASES_URL}/tag/{tag}'),
        body=str(data.get('body') or ''),
        assets=valid_assets,
    )


def _latest_release(channel):
    if channel == CHANNEL_RELEASE:
        data = _fetch_json(_API_LATEST)
        if data.get('draft') or data.get('prerelease'):
            raise UpdateError('GitHub Latest does not point to a release build.')
        return _release_from_json(data, channel)

    if channel == CHANNEL_NIGHTLY:
        releases = _fetch_json(_API_RECENT)
        if not isinstance(releases, list):
            raise UpdateError('GitHub returned an invalid releases list.')
        prereleases = [release for release in releases if (
            isinstance(release, dict)
            and release.get('prerelease') is True
            and not release.get('draft')
        )]
        if not prereleases:
            return None
        prereleases.sort(
            key=lambda release: release.get('published_at') or release.get('created_at') or '',
            reverse=True,
        )
        return _release_from_json(prereleases[0], channel)

    return None


def _numeric_version(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+(?:\.\d+)*', value.strip()):
        return None
    return tuple(int(part) for part in value.strip().lstrip('vV').split('.'))


def _is_newer(release):
    current = str(globals.MiyamotoVersion)
    if release.channel == CHANNEL_NIGHTLY:
        return release.version.lower() != current.lower() and release.tag.lower() != current.lower()

    if globals.MiyamotoReleaseType == 'nightly':
        return True
    latest_version = _numeric_version(release.version)
    current_version = _numeric_version(current)
    if latest_version is not None and current_version is not None:
        length = max(len(latest_version), len(current_version))
        latest_version += (0,) * (length - len(latest_version))
        current_version += (0,) * (length - len(current_version))
        return latest_version > current_version
    return release.version.lstrip('vV') != current.lstrip('vV')


def _machine():
    value = platform.machine().lower()
    if value in ('amd64', 'x64'):
        return 'x86_64'
    if value == 'aarch64':
        return 'arm64'
    return value


def _asset_for_platform(release, system=None, machine=None, appimage=None):
    system = system or platform.system()
    machine = machine or _machine()
    appimage = bool(os.environ.get('APPIMAGE')) if appimage is None else appimage

    if system == 'Windows' and machine == 'x86_64':
        suffix = '-Windows-x64.zip'
    elif system == 'Darwin' and machine in ('x86_64', 'arm64'):
        suffix = '-macOS-universal.zip'
    elif system == 'Linux' and machine == 'x86_64':
        suffix = '-Linux-x86_64.AppImage' if appimage else '-Linux-x86_64.zip'
    else:
        return None

    matches = [asset for asset in release.assets if asset['name'].endswith(suffix)]
    return matches[0] if len(matches) == 1 else None


def _install_location():
    appimage = os.environ.get('APPIMAGE')
    if sys.platform.startswith('linux') and appimage:
        target = Path(appimage).expanduser().resolve()
        return InstallLocation('appimage', target, target)

    if not getattr(sys, 'frozen', False):
        return None

    executable = Path(sys.executable).resolve()
    if sys.platform == 'darwin':
        app = next((parent for parent in (executable, *executable.parents)
                    if parent.name.endswith('.app')), None)
        if app is None:
            raise UpdateError('Could not locate the installed Yaz0moto app bundle.')
        return InstallLocation('bundle', app, app / 'Contents' / 'MacOS' / 'Yaz0moto')

    return InstallLocation('directory', executable.parent, executable)


def _safe_extract(zip_path, destination):
    destination = Path(destination).resolve()
    total = 0
    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError('Downloaded update is not a valid ZIP file.') from exc

    with archive:
        links = {}
        for info in archive.infolist():
            name = info.filename.replace('\\', '/')
            parts = PurePosixPath(name).parts
            mode = info.external_attr >> 16
            if (not name or name.startswith('/') or '..' in parts
                    or (parts and ':' in parts[0])):
                raise UpdateError('Downloaded update contains an unsafe file path.')
            if stat.S_ISLNK(mode):
                links[name.rstrip('/')] = _safe_link_target(name, archive.read(info))
            total += info.file_size
            if total > _MAX_EXTRACTED_SIZE:
                raise UpdateError('Downloaded update is unexpectedly large.')

        # Nothing may be written through a symlink (a link to a folder followed by
        # entries "inside" it could otherwise place files anywhere)
        for info in archive.infolist():
            parents = PurePosixPath(info.filename.replace('\\', '/')).parents
            if any(str(parent) in links for parent in parents):
                raise UpdateError('Downloaded update contains an unsafe file path.')

        # Links may go through other links (frameworks do: Versions/Current), but not
        # climb out with ".." after one, which could leave the folder once followed
        for name, link_target in links.items():
            path, through_link = posixpath.dirname(name), False
            for part in link_target.split('/'):
                if part == '..' and through_link:
                    raise UpdateError('Downloaded update contains an unsafe file path.')
                if part not in ('', '.'):
                    path = posixpath.normpath(posixpath.join(path, part))
                through_link = through_link or path in links

        for info in archive.infolist():
            name = info.filename.replace('\\', '/')
            target = destination.joinpath(*PurePosixPath(name).parts)
            if name.rstrip('/') in links:
                continue
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, 'wb') as output:
                shutil.copyfileobj(source, output)
            mode = (info.external_attr >> 16) & 0o777
            if mode and os.name != 'nt':
                target.chmod(mode)

        # macOS app bundles need their symlinks (frameworks use them, and the
        # signature covers them), so recreate them last
        for name, link_target in links.items():
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(link_target, target)


def _safe_link_target(name, raw):
    """
    The target of a symlink entry, if it is relative and stays inside the archive;
    otherwise the update is refused.
    """
    try:
        link_target = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise UpdateError('Downloaded update contains an unsafe file path.')
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name.rstrip('/')), link_target))
    if (not link_target or link_target.startswith('/') or '\\' in link_target or ':' in link_target
            or resolved == '..' or resolved.startswith('../')):
        raise UpdateError('Downloaded update contains an unsafe file path.')
    return link_target


def _download_asset(asset, output_path, progress=None):
    expected = asset.get('size')
    try:
        expected = int(expected) if expected is not None else None
    except (TypeError, ValueError):
        expected = None

    digest = asset.get('digest')
    hasher = hashlib.sha256() if isinstance(digest, str) and digest.startswith('sha256:') else None
    received = 0
    try:
        with requests.get(
                asset['browser_download_url'], headers=_HEADERS,
                stream=True, timeout=30) as response:
            response.raise_for_status()
            with open(output_path, 'wb') as output:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    output.write(chunk)
                    received += len(chunk)
                    if hasher:
                        hasher.update(chunk)
                    if progress:
                        progress(received, expected or 0)
    except (requests.RequestException, OSError) as exc:
        raise UpdateError(f'Could not download the update: {exc}') from exc

    if expected is not None and received != expected:
        raise UpdateError('Downloaded update has the wrong file size.')
    if hasher and hasher.hexdigest().lower() != digest.split(':', 1)[1].lower():
        raise UpdateError('Downloaded update failed its SHA-256 check.')


def _prepare_update(release, progress=None):
    location = _install_location()
    if location is None:
        raise UpdateError('Automatic updates are available only in packaged Yaz0moto builds.')
    if not location.target.exists():
        raise UpdateError('Current Yaz0moto installation could not be found.')
    if not os.access(str(location.target.parent), os.W_OK):
        raise UpdateError('Yaz0moto does not have permission to update this installation.')

    asset = _asset_for_platform(release, appimage=location.kind == 'appimage')
    if asset is None:
        raise UpdateError('This release has no update package for the current platform.')

    # Staged next to the installation, not in the temp folder: the helper renames the new
    # folder into place, which can't be done across drives (Yaz0moto on D:, %TEMP% on C:)
    work = Path(tempfile.mkdtemp(prefix='.yaz0moto-update-', dir=str(location.target.parent)))
    download = work / asset['name']
    try:
        _download_asset(asset, download, progress)
        if location.kind == 'appimage':
            staged = work / 'Yaz0moto.AppImage'
            download.replace(staged)
            staged.chmod(staged.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        else:
            extracted = work / 'extracted'
            extracted.mkdir()
            _safe_extract(download, extracted)
            download.unlink()
            if location.kind == 'bundle':
                staged = extracted / 'Yaz0moto.app'
                if not staged.is_dir():
                    raise UpdateError('macOS update does not contain Yaz0moto.app.')
                if not (staged / 'Contents' / 'MacOS' / 'Yaz0moto').is_file():
                    raise UpdateError('macOS update does not contain the Yaz0moto executable.')
            else:
                staged = extracted
                expected_name = 'Yaz0moto.exe' if sys.platform == 'win32' else 'Yaz0moto'
                # The files may be in a folder of their own inside the ZIP
                folders = [child for child in staged.iterdir() if child.is_dir()]
                if not (staged / expected_name).exists() and len(folders) == 1:
                    staged = folders[0]
                if not (staged / expected_name).is_file():
                    raise UpdateError(f'Update does not contain {expected_name}.')
        return location, staged, work
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _error_file(location):
    """Where the install helper writes why an update failed, shown at the next start."""
    return location.target.parent / 'Yaz0moto-update-error.txt'


def _write_windows_helper(location, staged, work):
    """
    Waits for Yaz0moto to exit, then swaps the installation folder for the new one (or, if
    the folder can't be renamed, e.g. it's open in Explorer or a terminal, copies the new
    files over it) and starts Yaz0moto again. If that fails, the old version is started
    and the error is written to _error_file.
    """
    script = work / 'install-update.ps1'
    backup = location.target.with_name(location.target.name + '.update-backup')
    new_executable = location.target / location.executable.name
    content = f"""$ErrorActionPreference = 'Stop'
$target = {_ps_quote(location.target)}
$staged = {_ps_quote(staged)}
$backup = {_ps_quote(backup)}
$work = {_ps_quote(work)}
$executable = {_ps_quote(new_executable)}
$errorFile = {_ps_quote(_error_file(location))}
Set-Location -LiteralPath (Split-Path -Parent $target)

# Files can stay locked for a moment after Yaz0moto exits (antivirus scans, the indexer)
function Retry([scriptblock]$action) {{
    for ($i = 0; $i -lt 20; $i++) {{
        try {{ & $action; return }} catch {{ $last = $_; Start-Sleep -Milliseconds 500 }}
    }}
    throw $last
}}

Wait-Process -Id {os.getpid()} -Timeout 60 -ErrorAction SilentlyContinue
Stop-Process -Id {os.getpid()} -Force -ErrorAction SilentlyContinue
try {{
    if (Test-Path -LiteralPath $backup) {{ Remove-Item -LiteralPath $backup -Recurse -Force }}
    $swapped = $false
    $movedOut = $false
    try {{ Retry {{ Move-Item -LiteralPath $target -Destination $backup }}; $movedOut = $true }} catch {{ }}
    if ($movedOut) {{
        try {{
            Retry {{ Move-Item -LiteralPath $staged -Destination $target }}
            $swapped = $true
        }} catch {{
            Move-Item -LiteralPath $backup -Destination $target  # put the old version back
        }}
    }}
    if (-not $swapped) {{
        & robocopy.exe $staged $target /E /R:10 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) {{ throw "Could not copy the new files into $target (robocopy error $LASTEXITCODE)." }}
    }}
    Start-Process -FilePath $executable -WorkingDirectory $target
    Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}} catch {{
    $_ | Out-String | Set-Content -LiteralPath $errorFile
    if (Test-Path -LiteralPath $executable) {{ Start-Process -FilePath $executable -WorkingDirectory $target }}
}}
"""
    script.write_text(content, encoding='utf-8')
    return script


def _write_posix_helper(location, staged, work):
    script = work / 'install-update.sh'
    backup = location.target.with_name(location.target.name + '.update-backup')
    target = shlex.quote(str(location.target))
    staged_path = shlex.quote(str(staged))
    backup_path = shlex.quote(str(backup))
    if location.kind == 'bundle':
        launch = f'open {target}'
    else:
        launch = shlex.quote(str(location.target))
    content = f"""#!/bin/sh
while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.2; done
rm -rf {backup_path}
if mv {target} {backup_path}; then
    if mv {staged_path} {target}; then
        chmod +x {shlex.quote(str(location.executable))} 2>/dev/null || true
        ({launch} >/dev/null 2>&1 &)
        rm -rf {backup_path}
        rm -rf {shlex.quote(str(work))}
        exit 0
    fi
    mv {backup_path} {target}
fi
echo {shlex.quote(f'Could not replace {location.target} with the new version.')} >{shlex.quote(str(_error_file(location)))}
({launch} >/dev/null 2>&1 &)
exit 1
"""
    script.write_text(content, encoding='utf-8')
    script.chmod(0o700)
    return script


def _launch_helper(location, staged, work):
    if sys.platform == 'win32':
        script = _write_windows_helper(location, staged, work)
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'DETACHED_PROCESS', 0)
        command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)]
        # Out of Yaz0moto's job (if a launcher put it in one), so the helper isn't killed when
        # Yaz0moto exits; a job that doesn't allow that refuses, then it's started as before
        try:
            subprocess.Popen(command, creationflags=flags | 0x01000000,  # CREATE_BREAKAWAY_FROM_JOB
                             close_fds=True, cwd=str(location.target.parent))
        except OSError:
            subprocess.Popen(command, creationflags=flags, close_fds=True, cwd=str(location.target.parent))
    else:
        script = _write_posix_helper(location, staged, work)
        subprocess.Popen(
            ['/bin/sh', str(script)],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            cwd=str(location.target.parent),
        )


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
    progress = QtCore.pyqtSignal(int)
    ready = QtCore.pyqtSignal(object, object, object)
    failed = QtCore.pyqtSignal(str)

    def start(self, release):
        self._release = release
        threading.Thread(target=self._run, name='Yaz0moto update download', daemon=True).start()

    def _run(self):
        try:
            def report(received, total):
                self.progress.emit(min(99, int(received * 100 / total)) if total else 0)

            location, staged, work = _prepare_update(self._release, report)
            self.progress.emit(100)
            self.ready.emit(location, staged, work)
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit('Unexpected error while preparing the update.')


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


def check_for_updates():
    _report_failed_install()
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
    global _worker, _progress
    if _worker is not None:
        return
    _progress = QtWidgets.QProgressDialog(
        'Downloading and verifying update...', '', 0, 100, globals.mainWindow
    )
    _progress.setWindowTitle('Yaz0moto Update')
    _progress.setWindowModality(QtCore.Qt.ApplicationModal)
    _progress.setCancelButton(None)
    _progress.setMinimumDuration(0)
    _progress.setValue(0)
    _progress.show()
    _progress.raise_()
    _progress.activateWindow()

    _worker = _UpdateWorker()
    _worker.progress.connect(_progress.setValue)
    _worker.failed.connect(_install_failed)
    _worker.ready.connect(_install_ready)
    _worker.start(release)


def _install_failed(message):
    global _worker, _progress
    if _progress is not None:
        _progress.close()
    _worker = None
    _progress = None
    _restore_dirty_state()
    _show_error(message)


def _install_ready(location, staged, work):
    global _worker, _progress
    if _progress is not None:
        _progress.close()
    _worker = None
    _progress = None

    window = globals.mainWindow
    if window is not None and not window.close():
        shutil.rmtree(work, ignore_errors=True)
        _restore_dirty_state()
        return
    try:
        _launch_helper(location, staged, work)
    except (OSError, subprocess.SubprocessError) as exc:
        shutil.rmtree(work, ignore_errors=True)
        if window is not None:
            window.show()
        _restore_dirty_state()
        _show_error(f'Could not start the update installer: {exc}')
    else:
        _clear_dirty_restore()
        # The installer waits for Yaz0moto to exit, so make sure it does (the window is
        # closed and the level saved by now), even if something keeps it running
        QtWidgets.QApplication.quit()
        timer = threading.Timer(15, os._exit, (0,))
        timer.daemon = True
        timer.start()


def _report_failed_install():
    """Shows why the last update couldn't be installed (see _error_file), once."""
    try:
        location = _install_location()
    except UpdateError:
        return
    if location is None:
        return
    path = _error_file(location)
    if not path.is_file():
        return
    try:
        details = path.read_text(encoding='utf-8', errors='replace').strip()
        path.unlink()
    except OSError:
        return
    _show_error('The last update could not be installed, so this version was kept.\n\n' + details[:1500])


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
