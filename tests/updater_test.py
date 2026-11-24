"""
Tests for the updater program (yaz0moto_updater.py) and how Yaz0moto hands over to it:
choosing the release file, not offering the same release again, downloading and unpacking
a package (`prepare`), installing it into a folder installation (`install`) while keeping
the user's files and putting everything back if a step fails, and Yaz0moto swapping in the
new updater the update left behind.

Run from anywhere:   python tests/updater_test.py
Needs PyQt5 only for the last part (yaz0moto/updater.py).
"""
import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import zipfile
from pathlib import Path
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import yaz0moto_updater as core  # noqa: E402

results = []


def check(label, ok):
    results.append((label, bool(ok)))
    print(('  OK  ' if ok else 'FAIL  ') + label)


EXE = core.executable_name()
UPD = core.updater_executable_name()
tmp = Path(tempfile.mkdtemp(prefix='yaz0moto-updater-test-'))


def make_package(files, name='Yaz0moto-v9.9.9-Windows-x64.zip'):
    path = tmp / name
    with zipfile.ZipFile(path, 'w') as zf:
        for rel, data in files.items():
            zf.writestr(rel, data)
    return path


def make_install(files):
    folder = Path(tempfile.mkdtemp(prefix='install-', dir=str(tmp))) / 'Yaz0moto'
    for rel, data in files.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(data)
    return folder


def read(folder, rel):
    path = Path(folder) / rel
    return path.read_bytes() if path.is_file() else None


log = core.Log()

# ---------------------------------------------------------------- release files and versions

release = types.SimpleNamespace(version='1.0.1', assets=[
    {'name': 'Yaz0moto-v6617073-Windows-x64.zip'}, {'name': 'Yaz0moto-v1.0.1-Windows-x64.zip'}])
check('a release with two Windows files picks the one named after its version',
      core.asset_for_platform(release, 'Windows', 'x86_64')['name'] == 'Yaz0moto-v1.0.1-Windows-x64.zip')
release = types.SimpleNamespace(version='1.2.0', assets=[{'name': 'Yaz0moto-v0a872f4-Windows-x64.zip'}])
check('a release whose only file has another build\'s name still has a Windows file',
      core.asset_for_platform(release, 'Windows', 'x86_64')['name'] == 'Yaz0moto-v0a872f4-Windows-x64.zip')

tagged = lambda tag: types.SimpleNamespace(channel='release', version=core.version_from_tag(tag), tag=tag)
check('a nightly build is offered a release', core.is_newer(tagged('v1.2.0'), '0a872f4', 'nightly'))
check('...but not the release it was installed from again (no endless update)',
      not core.is_newer(tagged('v1.2.0'), '0a872f4', 'nightly', installed_tag='v1.2.0'))
check('...and is offered the next release after it', core.is_newer(tagged('v1.3.0'), '0a872f4', 'nightly', 'v1.2.0'))
dated = core.ReleaseInfo('release', 'v1.2.0', '1.2.0', 'v1.2.0', '', '', (), '2026-10-24T17:20:22Z')
check('a nightly built after a release is not offered that older release (no downgrade)',
      not core.is_newer(dated, 'f70a4d9', 'nightly', build_date='2026-11-19T09:43:54Z'))
check('...but is offered a release published after it was built',
      core.is_newer(dated, 'f70a4d9', 'nightly', build_date='2026-10-01T00:00:00Z'))
check('the published date comes from GitHub', core.release_from_json(
    {'tag_name': 'v1.2.0', 'assets': [], 'published_at': '2026-10-24T17:20:22Z'}, core.CHANNEL_RELEASE).published
      == '2026-10-24T17:20:22Z')
check('release versions compare as numbers', core.is_newer(tagged('v1.10.0'), '1.9.0')
      and not core.is_newer(tagged('v1.2.0'), '1.2') and not core.is_newer(tagged('v1.0.9'), '1.1.0'))

# ---------------------------------------------------------------- prepare (download + unpack)

package = make_package({EXE: b'new exe', 'lib/new.pyd': b'new', 'yaz0data/shipped.txt': b'new data',
                        'yaz0data/themes/Default/main.xml': b'<new/>', 'project.json': b'{"version": "9.9.9"}',
                        'updater/' + UPD: b'new updater', 'updater/lib/x': b'x'})
work = tmp / 'work1'
proc = subprocess.run([sys.executable, 'yaz0moto_updater.py', 'prepare', '--url', package.as_uri(),
                       '--name', package.name, '--size', str(package.stat().st_size), '--kind', 'directory',
                       '--work', str(work)], capture_output=True, text=True)
events = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith('{')]
ready = [e for e in events if e['event'] == 'ready']
check('prepare downloads and unpacks the package, reporting progress and where it is',
      proc.returncode == 0 and any(e['event'] == 'progress' for e in events) and ready
      and (Path(ready[0]['staged']) / EXE).is_file())

bad = subprocess.run([sys.executable, 'yaz0moto_updater.py', 'prepare', '--url', package.as_uri(),
                      '--name', package.name, '--digest', 'sha256:' + '0' * 64, '--kind', 'directory',
                      '--work', str(tmp / 'work-bad')], capture_output=True, text=True)
errors = [json.loads(line) for line in bad.stdout.splitlines() if line.startswith('{"event": "error"')]
check('prepare refuses a package whose SHA-256 is wrong', bad.returncode == 1 and errors
      and 'SHA-256' in errors[0]['message'])

wrong = make_package({'readme.txt': b'not Yaz0moto'}, 'other.zip')
check('a package without the Yaz0moto executable is refused',
      subprocess.run([sys.executable, 'yaz0moto_updater.py', 'prepare', '--url', wrong.as_uri(), '--name', wrong.name,
                      '--kind', 'directory', '--work', str(tmp / 'work-wrong')], capture_output=True).returncode == 1)

# ---------------------------------------------------------------- install into a folder

install = make_install({EXE: b'old exe', 'lib/old.pyd': b'old', 'yaz0data/shipped.txt': b'old data',
                        'yaz0data/my-sprite.png': b'mine', 'yaz0data/themes/Mine/main.xml': b'<mine/>',
                        'settings.ini': b'user settings', 'updater/' + UPD: b'old updater'})
proc = subprocess.run([sys.executable, 'yaz0moto_updater.py', 'install', '--kind', 'directory',
                       '--target', str(install), '--staged', ready[0]['staged'], '--work', str(work),
                       '--no-launch', '--log', str(tmp / 'update.log'), '--error-file', str(tmp / 'error.txt')],
                      capture_output=True, text=True)
check('install succeeds and removes its work folder', proc.returncode == 0 and not work.exists()
      and not (tmp / 'error.txt').exists())
check('the new program files replace the old ones (no stale lib/ files)',
      read(install, EXE) == b'new exe' and read(install, 'lib/new.pyd') == b'new' and read(install, 'lib/old.pyd') is None)
check('shipped data files are updated', read(install, 'yaz0data/shipped.txt') == b'new data'
      and read(install, 'yaz0data/themes/Default/main.xml') == b'<new/>')
check('files the user added to yaz0data are kept', read(install, 'yaz0data/my-sprite.png') == b'mine'
      and read(install, 'yaz0data/themes/Mine/main.xml') == b'<mine/>')
check('files next to Yaz0moto that the package doesn\'t have are left alone', read(install, 'settings.ini') == b'user settings')
check('an updater not running from the installation is replaced directly',
      read(install, 'updater/' + UPD) == b'new updater' and not (install / core.UPDATER_STAGED_DIR).exists())
manifest = json.loads(read(install, core.MANIFEST))
check('the installed files are listed for the next update',
      'yaz0data/shipped.txt' in manifest['files'] and not any(f.startswith('updater/') for f in manifest['files']))
check('no backup is left behind', not (install / core.BACKUP_DIR).exists())

# Next update: a file the release dropped goes, the user's files stay (the list tells them apart)
staged = tmp / 'staged2'
for rel, data in {EXE: b'newer exe', 'lib/new.pyd': b'newer', 'yaz0data/themes/Default/main.xml': b'<newer/>'}.items():
    (staged / rel).parent.mkdir(parents=True, exist_ok=True)
    (staged / rel).write_bytes(data)
core.install(core.KIND_DIRECTORY, install, staged, log)
check('a data file a release no longer ships is removed, the user\'s stay',
      read(install, 'yaz0data/shipped.txt') is None and read(install, 'yaz0data/my-sprite.png') == b'mine'
      and read(install, EXE) == b'newer exe')

# ---------------------------------------------------------------- a failed install puts everything back

install = make_install({EXE: b'old exe', 'lib/old.pyd': b'old', 'yaz0data/a.txt': b'old'})
staged = tmp / 'staged3'
for rel, data in {EXE: b'new exe', 'lib/new.pyd': b'new', 'yaz0data/a.txt': b'new'}.items():
    (staged / rel).parent.mkdir(parents=True, exist_ok=True)
    (staged / rel).write_bytes(data)

real_rename = Path.rename


def failing_rename(self, target):
    if self.name == 'yaz0data' and str(self).startswith(str(staged)):
        raise OSError('simulated: file in use')
    return real_rename(self, target)


with mock.patch.object(Path, 'rename', failing_rename), mock.patch.object(core.time, 'sleep', lambda s: None):
    try:
        core.install(core.KIND_DIRECTORY, install, staged, log)
        failed = False
    except OSError:
        failed = True
check('a failed install raises and restores the old version exactly',
      failed and read(install, EXE) == b'old exe' and read(install, 'lib/old.pyd') == b'old'
      and read(install, 'lib/new.pyd') is None and read(install, 'yaz0data/a.txt') == b'old')

# The updater running from <install>/updater can't replace itself: it leaves updater.new
install = make_install({EXE: b'old', 'updater/' + UPD: b'running updater'})
staged = tmp / 'staged4'
for rel, data in {EXE: b'new', 'updater/' + UPD: b'next updater'}.items():
    (staged / rel).parent.mkdir(parents=True, exist_ok=True)
    (staged / rel).write_bytes(data)
with mock.patch.object(core, '_running_from', lambda path: Path(path).name == core.UPDATER_DIR):
    core.install(core.KIND_DIRECTORY, install, staged, log)
check('the running updater is left alone and the new one waits in updater.new',
      read(install, 'updater/' + UPD) == b'running updater'
      and read(install, core.UPDATER_STAGED_DIR + '/' + UPD) == b'next updater' and read(install, EXE) == b'new')

# ---------------------------------------------------------------- Yaz0moto installs the new updater

from PyQt5 import QtWidgets  # noqa: E402
app = QtWidgets.QApplication([])
from yaz0moto import updater  # noqa: E402

check('Yaz0moto swaps updater.new in at its next start', updater.install_staged_updater(install)
      and read(install, 'updater/' + UPD) == b'next updater' and not (install / core.UPDATER_STAGED_DIR).exists()
      and not (install / 'updater.old').exists())
(install / core.UPDATER_STAGED_DIR).mkdir()
(install / core.UPDATER_STAGED_DIR / 'half-copied').write_bytes(b'')
check('an incomplete updater.new is thrown away, keeping the working updater',
      not updater.install_staged_updater(install) and read(install, 'updater/' + UPD) == b'next updater'
      and not (install / core.UPDATER_STAGED_DIR).exists())

with mock.patch.object(updater.globals, 'MiyamotoVersion', '0a872f4'), \
        mock.patch.object(updater.globals, 'MiyamotoReleaseType', 'nightly'), \
        mock.patch.object(updater, '_setting', lambda name, default=None: {
            'InstalledUpdateTag': 'v1.2.0', 'InstalledUpdateVersion': '0a872f4'}.get(name, default)):
    check('Yaz0moto does not offer the release it was just updated to again', not updater._is_newer(tagged('v1.2.0')))

failed = [label for label, ok in results if not ok]
print('\n%d/%d passed' % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
