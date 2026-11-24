#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Yaz0moto Updater: the program that downloads, checks and installs Yaz0moto updates.

It is built as an executable of its own (build_updater.py), shipped in the `updater` folder
of every package, and used in two ways:

* By Yaz0moto (yaz0moto/updater.py), which finds the release and asks the user, then runs
    Yaz0moto-Updater prepare ...   downloads, verifies and unpacks the update while Yaz0moto
                                   shows the progress (JSON lines on stdout)
    Yaz0moto-Updater install ...   started just before Yaz0moto quits: waits for it to exit,
                                   swaps the new files in (putting the old ones back if that
                                   fails), and starts Yaz0moto again
  The updater can't replace its own files while it runs, so a new `updater` folder is left
  next to it as `updater.new`; Yaz0moto swaps it in the next time it starts.

* By hand, when Yaz0moto itself can't start:
    Yaz0moto-Updater update [--channel release|nightly] [--target <install>] [--force]

Standard library only (plus certifi when available), so it freezes to a small program, and
Yaz0moto imports this file for the release, asset, version and extraction rules.
"""

import argparse
import hashlib
import json
import os
import platform
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


UPDATER_VERSION = '2.1.0'
GITHUB_REPO = 'Steammaker212/Yaz0moto'
RELEASES_URL = f'https://github.com/{GITHUB_REPO}/releases'
_API_BASE = f'https://api.github.com/repos/{GITHUB_REPO}/releases'
_API_LATEST = f'{_API_BASE}/latest'
_API_RECENT = f'{_API_BASE}?per_page=30'
_MAX_EXTRACTED_SIZE = 4 * 1024 * 1024 * 1024

CHANNEL_RELEASE = 'release'
CHANNEL_NIGHTLY = 'nightly'
CHANNEL_OFF = 'off'

KIND_DIRECTORY = 'directory'  # Windows / Linux zip: a folder with Yaz0moto(.exe) in it
KIND_BUNDLE = 'bundle'        # macOS: Yaz0moto.app
KIND_APPIMAGE = 'appimage'    # Linux: one Yaz0moto.AppImage file

UPDATER_DIR = 'updater'              # the updater's own folder inside an installation
UPDATER_STAGED_DIR = 'updater.new'   # a newer updater, swapped in by Yaz0moto
UPDATER_NAME = 'Yaz0moto-Updater'
WORK_DIR = '.yaz0moto-update'        # download/unpack folder, inside a folder installation
BACKUP_DIR = '.yaz0moto-update-backup'
MANIFEST = '.yaz0moto-manifest.json'  # the files the last update installed

# Folders users add their own files to (themes, patches, sprite images...): updated file by
# file, keeping the files the user added, instead of being replaced as a whole
MERGE_DIRS = ('yaz0data', 'yaz0extras')


class UpdateError(RuntimeError):
    """An expected update failure, worded for the user."""


@dataclass(frozen=True)
class ReleaseInfo:
    channel: str
    tag: str
    version: str
    title: str
    page_url: str
    body: str
    assets: tuple
    published: str = ''  # when GitHub published it, e.g. 2026-11-01T23:36:10Z


# ------------------------------------------------------------------------------- GitHub

def _headers(user_agent=None):
    return {
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': user_agent or f'Yaz0moto-Updater/{UPDATER_VERSION}',
    }


def _ssl_context():
    """Python.org builds for macOS ship no CA certificates of their own: use certifi's."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        return ssl.create_default_context()


def _open(url, user_agent=None, timeout=20):
    request = urllib.request.Request(url, headers=_headers(user_agent))
    return urllib.request.urlopen(request, timeout=timeout, context=_ssl_context())


def fetch_json(url, user_agent=None):
    try:
        with _open(url, user_agent, timeout=15) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise UpdateError('GitHub refused the update check (too many requests). Please try again later.')
        if exc.code == 404 and url == _API_LATEST:
            raise UpdateError('No GitHub Latest release has been published yet.')
        raise UpdateError(f'GitHub update check failed (HTTP {exc.code}).')
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, 'reason', exc)
        raise UpdateError(f'Could not connect to GitHub: {reason}') from exc
    try:
        return json.loads(raw.decode('utf-8'))
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


def release_from_json(data, channel):
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
        page_url=str(data.get('html_url') or f'{RELEASES_URL}/tag/{tag}'),
        body=str(data.get('body') or ''),
        assets=valid_assets,
        published=str(data.get('published_at') or data.get('created_at') or ''),
    )


def latest_release(channel, user_agent=None):
    """The newest release of a channel, or None if it has none."""
    if channel == CHANNEL_RELEASE:
        data = fetch_json(_API_LATEST, user_agent)
        if data.get('draft') or data.get('prerelease'):
            raise UpdateError('GitHub Latest does not point to a release build.')
        return release_from_json(data, channel)

    if channel == CHANNEL_NIGHTLY:
        releases = fetch_json(_API_RECENT, user_agent)
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
        return release_from_json(prereleases[0], channel)

    return None


def numeric_version(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+(?:\.\d+)*', value.strip()):
        return None
    return tuple(int(part) for part in value.strip().lstrip('vV').split('.'))


def is_newer(release, current_version, current_type='release', installed_tag=None, build_date=None):
    """
    Whether a release should be offered to an installation of current_version.
    installed_tag is the release the updater last installed here: a release can ship a
    build whose own version isn't its tag (a nightly published as v1.2.0, say), which
    would otherwise be offered again after every update.
    build_date is when this build was made (UTC, ISO 8601): a nightly build is only offered
    releases published after it, never an older release (that would be a downgrade).
    """
    current = str(current_version)
    if installed_tag and release.tag.lower() == str(installed_tag).lower():
        return False

    if release.channel == CHANNEL_NIGHTLY:
        return release.version.lower() != current.lower() and release.tag.lower() != current.lower()

    latest = numeric_version(release.version)
    installed = numeric_version(current)
    if latest is not None and installed is not None and current_type != 'nightly':
        length = max(len(latest), len(installed))
        latest += (0,) * (length - len(latest))
        installed += (0,) * (length - len(installed))
        return latest > installed
    if current_type == 'nightly':
        # A nightly build has no version number to compare with: a release published after
        # it was built is newer, an older one is not (when either date is unknown, offer it)
        published = getattr(release, 'published', '') or ''
        if build_date and published:
            return published > str(build_date)
        return True
    return release.version.lstrip('vV') != current.lstrip('vV')


def machine():
    value = platform.machine().lower()
    if value in ('amd64', 'x64'):
        return 'x86_64'
    if value == 'aarch64':
        return 'arm64'
    return value


def asset_for_platform(release, system=None, machine_=None, appimage=None):
    """
    The release file for this platform. If a release has more than one (a re-upload with
    another build's name, say), the one named after the release's version wins.
    """
    system = system or platform.system()
    machine_ = machine_ or machine()
    appimage = bool(os.environ.get('APPIMAGE')) if appimage is None else appimage

    if system == 'Windows' and machine_ == 'x86_64':
        suffix = '-Windows-x64.zip'
    elif system == 'Darwin' and machine_ in ('x86_64', 'arm64'):
        suffix = '-macOS-universal.zip'
    elif system == 'Linux' and machine_ == 'x86_64':
        suffix = '-Linux-x86_64.AppImage' if appimage else '-Linux-x86_64.zip'
    else:
        return None

    matches = [asset for asset in release.assets if asset['name'].endswith(suffix)]
    if len(matches) > 1:
        version = getattr(release, 'version', '') or ''
        named = [asset for asset in matches if version and f'-v{version}-' in asset['name']]
        matches = named or sorted(matches, key=lambda asset: asset['name'])
    return matches[0] if matches else None


# ------------------------------------------------------------------------------- download

def download(url, output_path, size=None, digest=None, progress=None, user_agent=None):
    """Downloads url to output_path, checking its size and SHA-256 when known."""
    try:
        expected = int(size) if size is not None else None
    except (TypeError, ValueError):
        expected = None

    hasher = hashlib.sha256() if isinstance(digest, str) and digest.startswith('sha256:') else None
    received = 0
    try:
        with _open(url, user_agent, timeout=30) as response, open(output_path, 'wb') as output:
            if expected is None:
                length = response.headers.get('Content-Length')
                expected = int(length) if length and length.isdigit() else None
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                if hasher:
                    hasher.update(chunk)
                if progress:
                    progress(received, expected or 0)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f'Could not download the update (HTTP {exc.code}).') from exc
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, 'reason', exc)
        raise UpdateError(f'Could not download the update: {reason}') from exc

    if expected is not None and received != expected:
        raise UpdateError('Downloaded update has the wrong file size.')
    if hasher and hasher.hexdigest().lower() != digest.split(':', 1)[1].lower():
        raise UpdateError('Downloaded update failed its SHA-256 check.')


# ------------------------------------------------------------------------------- unpacking

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


def safe_extract(zip_path, destination):
    """
    Unpacks a ZIP, refusing paths that leave the destination (directly or through a
    symlink). Symlinks are kept: macOS app bundles need them for their signature.
    """
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

        for name, link_target in links.items():
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(link_target, target)


def executable_name():
    return 'Yaz0moto.exe' if sys.platform == 'win32' else 'Yaz0moto'


def updater_executable_name():
    return UPDATER_NAME + ('.exe' if sys.platform == 'win32' else '')


def stage(package, kind, work):
    """
    Unpacks a downloaded package in work and checks it is a Yaz0moto build for this
    kind of installation. Returns what install() puts in place.
    """
    package, work = Path(package), Path(work)
    if kind == KIND_APPIMAGE:
        staged = work / 'Yaz0moto.AppImage'
        package.replace(staged)
        staged.chmod(staged.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return staged

    extracted = work / 'extracted'
    if extracted.exists():
        shutil.rmtree(extracted)
    extracted.mkdir()
    safe_extract(package, extracted)
    package.unlink()

    if kind == KIND_BUNDLE:
        staged = extracted / 'Yaz0moto.app'
        if not staged.is_dir():
            raise UpdateError('macOS update does not contain Yaz0moto.app.')
        if not (staged / 'Contents' / 'MacOS' / 'Yaz0moto').is_file():
            raise UpdateError('macOS update does not contain the Yaz0moto executable.')
        return staged

    staged = extracted
    expected = executable_name()
    # The files may be in a folder of their own inside the ZIP
    folders = [child for child in staged.iterdir() if child.is_dir()]
    if not (staged / expected).exists() and len(folders) == 1:
        staged = folders[0]
    if not (staged / expected).is_file():
        raise UpdateError(f'Update does not contain {expected}.')
    return staged


# ------------------------------------------------------------------------------- installing

class Log:
    def __init__(self, path=None):
        self.path = Path(path) if path else None

    def __call__(self, message):
        line = time.strftime('%Y-%m-%d %H:%M:%S ') + message
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
            except OSError:
                pass
        if sys.stderr is not None:
            try:
                print(line, file=sys.stderr, flush=True)
            except (OSError, ValueError):
                pass


def _retry(action, attempts=40, delay=0.25):
    """Files can stay locked for a moment after a program exits (antivirus, indexing)."""
    for attempt in range(attempts):
        try:
            return action()
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _remove(path):
    path = Path(path)
    if path.is_symlink() or path.is_file():
        _retry(path.unlink)
    elif path.is_dir():
        def onerror(func, name, _):
            os.chmod(name, stat.S_IWRITE)  # read-only files (Windows)
            func(name)
        _retry(lambda: shutil.rmtree(path, onerror=onerror) if path.exists() else None)


def wait_for_exit(pid, timeout=60, log=None):
    """Waits for the process to exit, ending it after timeout seconds."""
    if not pid:
        return
    if sys.platform == 'win32':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000 | 0x0001, False, int(pid))  # SYNCHRONIZE | TERMINATE
        if not handle:
            return  # already gone
        try:
            if kernel32.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                if log:
                    log(f'Yaz0moto (process {pid}) did not exit, ending it')
                kernel32.TerminateProcess(handle, 1)
                kernel32.WaitForSingleObject(handle, 10000)
        finally:
            kernel32.CloseHandle(handle)
        return

    import signal
    deadline = time.time() + timeout
    while True:
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        if time.time() > deadline:
            if log:
                log(f'Yaz0moto (process {pid}) did not exit, ending it')
            try:
                os.kill(int(pid), signal.SIGKILL)
            except OSError:
                pass
            time.sleep(1)
            return
        time.sleep(0.2)


def _running_from(path):
    """Whether this program runs from inside path."""
    if not getattr(sys, 'frozen', False):
        return False
    try:
        Path(sys.executable).resolve().relative_to(Path(path).resolve())
        return True
    except (ValueError, OSError):
        return False


def _relative_files(root):
    root = Path(root)
    out = []
    for folder, dirs, files in os.walk(root):
        for name in files:
            out.append(Path(folder, name).relative_to(root).as_posix())
    return out


def _read_manifest(target):
    try:
        with open(Path(target) / MANIFEST, encoding='utf-8') as f:
            data = json.load(f)
        return set(data.get('files', [])) if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def install_directory(target, staged, log):
    """
    Puts the new files of a folder installation in place. Each top-level file and folder
    of the package replaces the installed one (moved aside first, so everything can be put
    back if a step fails); the folders users add files to (MERGE_DIRS) keep the files the
    package never had. Files the user put next to Yaz0moto are left alone.
    """
    target, staged = Path(target), Path(staged)
    backup = target / BACKUP_DIR
    if backup.exists():
        _remove(backup)
    backup.mkdir()

    old_manifest = _read_manifest(target)
    new_files = [path for path in _relative_files(staged) if not path.startswith(UPDATER_DIR + '/')]
    new_top = {path.split('/', 1)[0] for path in new_files}
    # Files of the old version that this one no longer has go too (they could be loaded
    # instead of the new ones, e.g. a stale module in lib/)
    stale_top = set()
    if old_manifest:
        stale_top = {path.split('/', 1)[0] for path in old_manifest} - new_top - {UPDATER_DIR, MANIFEST}

    updater_in_use = _running_from(target / UPDATER_DIR)
    entries = [entry for entry in sorted(staged.iterdir(), key=lambda p: p.name)
               if not (entry.name == UPDATER_DIR and updater_in_use)]  # the running updater: below
    moved = []   # old top-level files and folders now in the backup
    placed = []  # new ones now in place

    def put_back():
        # A new file goes only where the old one is there to take its place again: a
        # failed step never leaves a file missing
        for name in reversed(placed):
            if name in moved and (backup / name).exists():
                try:
                    _remove(target / name)
                except OSError as exc:
                    log(f'Could not remove the new {name}: {exc}')
        for name in reversed(moved):
            try:
                if not (target / name).exists() and not (target / name).is_symlink():
                    _retry(lambda: (backup / name).rename(target / name))
            except OSError as exc:
                log(f'Could not put {name} back (it is in {backup}): {exc}')

    try:
        # 1. Every old file and folder the update replaces goes aside first. If one is in use
        # (Yaz0moto still open, say) nothing new is in yet, and they all go back.
        for name in sorted(stale_top) + [entry.name for entry in entries]:
            dest = target / name
            if name in moved or not (dest.exists() or dest.is_symlink()):
                continue
            if name in stale_top:
                log(f'Removing {name} (not in the new version)')
            try:
                _retry(lambda: dest.rename(backup / name))
            except OSError as exc:
                raise UpdateError(f'{name} is in use, so nothing was changed. Close every Yaz0moto window '
                                  f'(and any program using its files) and try again. ({exc})') from exc
            moved.append(name)

        # 2. The new ones go in
        for entry in entries:
            name = entry.name
            dest = target / name
            _retry(lambda: entry.rename(dest))
            placed.append(name)

            if name in MERGE_DIRS and name in moved and dest.is_dir() and (backup / name).is_dir():
                # Keep what the user added: files the old package didn't ship
                for rel in _relative_files(backup / name):
                    full = name + '/' + rel
                    if (dest / rel).exists() or (old_manifest is not None and full in old_manifest):
                        continue
                    (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup / name / rel, dest / rel)
                    log(f'Kept your file {full}')

        new_updater = staged / UPDATER_DIR
        if updater_in_use and new_updater.is_dir():
            # This program can't replace itself: Yaz0moto swaps it in at its next start
            pending = target / UPDATER_STAGED_DIR
            if pending.exists():
                _remove(pending)
            _retry(lambda: new_updater.rename(pending))
            log('New updater left in updater.new for Yaz0moto to install')

        try:
            with open(target / MANIFEST, 'w', encoding='utf-8') as f:
                json.dump({'updater': UPDATER_VERSION, 'files': sorted(new_files)}, f, indent=1)
        except OSError as exc:
            log(f'Could not write the file list: {exc}')
    except Exception:
        log('Installing failed, putting the old files back:\n' + traceback.format_exc())
        put_back()
        raise

    try:
        _remove(backup)
    except OSError as exc:
        log(f'Could not remove the backup (Yaz0moto removes it later): {exc}')


def install_bundle(target, staged, log):
    """Swaps Yaz0moto.app for the new one as a whole, which keeps its signature valid."""
    target, staged = Path(target), Path(staged)
    backup = target.with_name(target.name + '.update-backup')
    if backup.exists():
        _remove(backup)
    _retry(lambda: target.rename(backup))
    try:
        _retry(lambda: staged.rename(target))
    except Exception:
        log('Installing failed, putting the old app back')
        if not target.exists():
            backup.rename(target)
        raise
    try:
        _remove(backup)
    except OSError as exc:
        log(f'Could not remove the old app: {exc}')


def install_appimage(target, staged, log):
    _retry(lambda: os.replace(str(staged), str(target)))


def install(kind, target, staged, log):
    log(f'Installing ({kind}) into {target}')
    if kind == KIND_DIRECTORY:
        install_directory(target, staged, log)
    elif kind == KIND_BUNDLE:
        install_bundle(target, staged, log)
    elif kind == KIND_APPIMAGE:
        install_appimage(target, staged, log)
    else:
        raise UpdateError(f'Unknown installation type: {kind}')
    log('Installed')


def launch(kind, target, log):
    """Starts Yaz0moto, detached from this program."""
    target = Path(target)
    env = dict(os.environ)
    for name in ('APPDIR', 'APPIMAGE', 'ARGV0', 'OWD'):  # left over from the old AppImage
        env.pop(name, None)
    try:
        if kind == KIND_BUNDLE:
            subprocess.Popen(['open', str(target)], env=env, close_fds=True)
        elif kind == KIND_APPIMAGE:
            subprocess.Popen([str(target)], cwd=str(target.parent), env=env, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        elif sys.platform == 'win32':
            flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            executable = target / executable_name()
            try:
                subprocess.Popen([str(executable)], cwd=str(target), env=env, close_fds=True,
                                 creationflags=flags | 0x01000000)  # CREATE_BREAKAWAY_FROM_JOB
            except OSError:
                subprocess.Popen([str(executable)], cwd=str(target), env=env, close_fds=True, creationflags=flags)
        else:
            executable = target / executable_name()
            subprocess.Popen([str(executable)], cwd=str(target), env=env, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        log('Started Yaz0moto')
    except OSError as exc:
        log(f'Could not start Yaz0moto: {exc}')


# ------------------------------------------------------------------------------- commands

def _emit(event, **data):
    """A progress line for Yaz0moto (one JSON object per line on stdout)."""
    if sys.stdout is None:
        return
    try:
        print(json.dumps(dict(event=event, **data)), flush=True)
    except (OSError, ValueError):
        pass


def cmd_prepare(args):
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    package = work / Path(args.name).name
    last = [-1]

    def progress(received, total):
        percent = int(received * 100 / total) if total else -1
        if percent != last[0]:
            last[0] = percent
            _emit('progress', received=received, total=total)

    try:
        download(args.url, package, args.size, args.digest, progress)
        _emit('status', message='Unpacking...')
        staged = stage(package, args.kind, work)
    except UpdateError as exc:
        _emit('error', message=str(exc))
        return 1
    except Exception as exc:  # report anything, the user only sees this message
        _emit('error', message=f'Unexpected error while preparing the update: {exc}')
        return 1
    _emit('ready', staged=str(staged))
    return 0


def _write_error(path, text):
    if not path:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding='utf-8')
    except OSError:
        pass


def cmd_install(args):
    log = Log(args.log)
    log(f'Yaz0moto-Updater {UPDATER_VERSION}: waiting for Yaz0moto to exit')
    wait_for_exit(args.pid, log=log)
    ok = True
    try:
        install(args.kind, args.target, args.staged, log)
    except Exception as exc:
        ok = False
        details = str(exc) if isinstance(exc, (UpdateError, OSError)) else traceback.format_exc()
        log('Update failed: ' + details)
        _write_error(args.error_file, details)

    if args.work:
        try:
            _remove(args.work)
        except OSError as exc:
            log(f'Could not remove {args.work}: {exc}')
    if not args.no_launch:
        launch(args.kind, args.target, log)
    return 0 if ok else 1


def detect_installation(start=None):
    """
    (kind, target) for the installation this updater belongs to: <install>/updater/ in a
    folder installation, Yaz0moto.app/Contents/Resources/updater/ on macOS.
    """
    if os.environ.get('APPIMAGE'):
        return KIND_APPIMAGE, Path(os.environ['APPIMAGE']).resolve()
    here = Path(start or (sys.executable if getattr(sys, 'frozen', False) else __file__)).resolve()
    for parent in here.parents:
        if parent.name.endswith('.app') and (parent / 'Contents' / 'MacOS' / 'Yaz0moto').exists():
            return KIND_BUNDLE, parent
        if (parent / executable_name()).is_file():
            return KIND_DIRECTORY, parent
    return None, None


def _installed_version(kind, target):
    candidates = [target / 'project.json']
    if kind == KIND_BUNDLE:
        candidates.insert(0, target / 'Contents' / 'Resources' / 'project.json')
    for path in candidates:
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            return str(data.get('version', '')), str(data.get('release_type', 'release'))
        except (OSError, ValueError):
            continue
    return '', 'release'


def cmd_update(args):
    """Checks GitHub and installs the newest version, without Yaz0moto."""
    log = Log(args.log)
    if args.target:
        target = Path(args.target).resolve()
        if target.suffix == '.app':
            kind = KIND_BUNDLE
        elif target.suffix.lower() == '.appimage':
            kind = KIND_APPIMAGE
        else:
            kind = KIND_DIRECTORY
    else:
        kind, target = detect_installation()
    if kind is None or not target.exists():
        print('Could not find the Yaz0moto installation; pass it with --target.', file=sys.stderr)
        return 2

    try:
        release = latest_release(args.channel)
        if release is None:
            print(f'No {args.channel} release has been published.')
            return 0
        version, release_type = _installed_version(kind, target)
        if not args.force and not is_newer(release, version, release_type):
            print(f'Yaz0moto {version} is up to date ({release.tag}).')
            return 0
        asset = asset_for_platform(release, appimage=kind == KIND_APPIMAGE)
        if asset is None:
            raise UpdateError('This release has no package for this platform.')
        print(f'Updating Yaz0moto {version or "(unknown version)"} to {release.tag}...')

        # Bundles and AppImages are swapped as a whole: run from a copy outside them
        if kind != KIND_DIRECTORY and _running_from(target) and not args.relocated:
            copy = Path(tempfile.mkdtemp(prefix='yaz0moto-updater-')) / UPDATER_DIR
            shutil.copytree(Path(sys.executable).parent, copy, symlinks=True)
            command = [str(copy / Path(sys.executable).name)] + sys.argv[1:] + ['--relocated']
            return subprocess.call(command)

        work = (target / WORK_DIR) if kind == KIND_DIRECTORY else Path(
            tempfile.mkdtemp(prefix='.yaz0moto-update-', dir=str(target.parent)))
        if work.exists() and kind == KIND_DIRECTORY:
            _remove(work)
        work.mkdir(parents=True, exist_ok=True)
        package = work / asset['name']

        def progress(received, total):
            if total:
                print(f'\r  {received * 100 // total:3d}%  ({received // 1048576} of {total // 1048576} MB)', end='', flush=True)

        download(asset['browser_download_url'], package, asset.get('size'), asset.get('digest'), progress)
        print()
        staged = stage(package, kind, work)
        install(kind, target, staged, log)
        _remove(work)
    except UpdateError as exc:
        print(f'Update failed: {exc}', file=sys.stderr)
        return 1
    print(f'Yaz0moto was updated to {release.tag}.')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog=UPDATER_NAME, description='Downloads and installs Yaz0moto updates.')
    sub = parser.add_subparsers(dest='command')

    sub.add_parser('version', help='print the updater version')

    p = sub.add_parser('prepare', help='download and unpack an update (used by Yaz0moto)')
    p.add_argument('--url', required=True)
    p.add_argument('--name', required=True)
    p.add_argument('--size', type=int)
    p.add_argument('--digest')
    p.add_argument('--kind', required=True, choices=(KIND_DIRECTORY, KIND_BUNDLE, KIND_APPIMAGE))
    p.add_argument('--work', required=True)

    p = sub.add_parser('install', help='install a prepared update once Yaz0moto exits (used by Yaz0moto)')
    p.add_argument('--kind', required=True, choices=(KIND_DIRECTORY, KIND_BUNDLE, KIND_APPIMAGE))
    p.add_argument('--target', required=True)
    p.add_argument('--staged', required=True)
    p.add_argument('--work')
    p.add_argument('--pid', type=int)
    p.add_argument('--log')
    p.add_argument('--error-file')
    p.add_argument('--no-launch', action='store_true')

    p = sub.add_parser('update', help='check for and install the newest version')
    p.add_argument('--channel', default=CHANNEL_RELEASE, choices=(CHANNEL_RELEASE, CHANNEL_NIGHTLY))
    p.add_argument('--target', help='the Yaz0moto folder, Yaz0moto.app or AppImage (default: this updater\'s)')
    p.add_argument('--force', action='store_true', help='install even if it is not newer')
    p.add_argument('--log')
    p.add_argument('--relocated', action='store_true', help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    if args.command == 'version':
        print(UPDATER_VERSION)
        return 0
    if args.command == 'prepare':
        return cmd_prepare(args)
    if args.command == 'install':
        return cmd_install(args)
    if args.command == 'update':
        return cmd_update(args)
    parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
