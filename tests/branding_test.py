"""
Branding and release-plumbing checks for Yaz0moto.

Yaz0moto is a fork of Pyamoto. Renaming it is more than changing window titles: the updater, the
build script, the Linux/macOS packaging and the CI workflows all have to agree on names, or the
built-in updater would offer to "update" Yaz0moto into upstream Pyamoto. These tests guard that.

Run from anywhere:   python tests/branding_test.py
"""
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

REPO = 'Steammaker212/Yaz0moto'
results = []


def check(label, ok, detail=''):
    results.append((label, bool(ok)))
    print(('PASS ' if ok else 'FAIL ') + label + ((' -- ' + detail) if (detail and not ok) else ''))


def read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as f:
        return f.read()


# ---------------------------------------------------------------- no leftover Pyamoto branding
# Anything listed here may keep the word, and why.
ALLOWED = [
    # (file, text that may appear, reason)
    ('miyamoto/puzzle.py', '__pyamoto_props__', 'key inside exported object files; renaming would break files made with Pyamoto'),
    ('miyamoto/tileset.py', '_pyamoto_bntx', 'internal attribute name'),
    ('miyamoto/dialogs.py', 'Based on <b>Pyamoto</b>', 'About box credits the project this is forked from'),
    ('miyamoto/dialogs.py', 'A fork of Pyamoto.', 'About box credits the project this is forked from'),
    ('miyamoto/globals.py', 'Pyamoto', 'old user-data folder name, only used to migrate settings'),
]
SCAN_SUFFIXES = ('.py', '.yml', '.yaml', '.sh', '.desktop', '.json', '.txt', '.xml', '.pyx', '.pyxbld')
SCAN_NAMES = ('AppRun', '.gitignore')
SKIP_DIRS = {'.git', 'build', 'distrib', '__pycache__', 'FastYZ', '.venv', 'tools', 'docs', 'miyamotoextras'}
SKIP_FILES = {'tests/branding_test.py', 'license.txt', 'log.txt'}
HEADER_LINES = 12   # the licence block at the top of every source file credits upstream; it must stay


def is_header(rel, lineno):
    return rel.endswith(('.py', '.pyx')) and lineno <= HEADER_LINES


leftovers = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
    for fn in filenames:
        if not (fn.endswith(SCAN_SUFFIXES) or fn in SCAN_NAMES):
            continue
        rel = os.path.relpath(os.path.join(dirpath, fn), ROOT).replace('\\', '/')
        if rel in SKIP_FILES:
            continue
        try:
            lines = read(rel).split('\n')
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(lines, 1):
            if re.search(r'pyamoto', line, re.I) and not is_header(rel, i):
                if any(rel == f and text in line for f, text, _ in ALLOWED):
                    continue
                leftovers.append('%s:%d: %s' % (rel, i, line.strip()[:90]))
check('no user-facing "Pyamoto" left in code, build files, CI or data (outside licence headers)',
      not leftovers, '\n      ' + '\n      '.join(leftovers[:12]))

# ---------------------------------------------------------------- files and names agree
check('entry point yaz0moto.py exists and pyamoto.py is gone',
      os.path.isfile('yaz0moto.py') and not os.path.exists('pyamoto.py'))
build = read('build.py')
check('build.py freezes yaz0moto.py as "Yaz0moto"', "'yaz0moto.py'" in build and "target_name = 'Yaz0moto'" in build)
check('build.py macOS bundle is Yaz0moto.app with the new icon',
      "'bundle_name': 'Yaz0moto'" in build and 'yaz0moto.icns' in build and "'build/Yaz0moto.app'" in build)
for icon in ('yaz0moto1024.png', 'yaz0moto1024mac.png', 'yaz0moto.icns', 'win_icon.ico'):
    check('icon file exists: ' + icon, os.path.isfile('miyamotodata/app_icons/' + icon))
check('old icon files are gone', not any(os.path.exists('miyamotodata/app_icons/' + f)
                                         for f in ('pyamoto.icns', 'pyamoto1024.png', 'pyamoto1024mac.png')))
desktop = read('buildtools/Yaz0moto.desktop')
check('Linux .desktop entry launches the Yaz0moto executable',
      'Name=Yaz0moto' in desktop and 'Exec=Yaz0moto' in desktop and 'Icon=Yaz0moto' in desktop)
check('AppRun starts the Yaz0moto executable', '/Yaz0moto"' in read('buildtools/AppRun'))
check('project.json id is Yaz0moto', 'Yaz0moto' in read('project.json'))

# ---------------------------------------------------------------- updater and CI agree
updater_src = read('miyamoto/updater.py')
check('updater checks THIS project\'s releases', ("GITHUB_REPO = '%s'" % REPO) in updater_src
      and 'Zenith-Team' not in updater_src)
check('updater expects the executables the build produces',
      all(name in updater_src for name in ("'Yaz0moto.exe'", "Yaz0moto.app", "'Yaz0moto.AppImage'", "'Contents' / 'MacOS' / 'Yaz0moto'")))

workflows = {f: read('.github/workflows/' + f) for f in os.listdir('.github/workflows') if f.endswith('.yml')}
artifacts = workflows['build-artifacts.yml']
CI_NAMES = ['Yaz0moto-v${V}-macOS-universal.zip', 'Yaz0moto-v${V}-Linux-x86_64.AppImage', 'Yaz0moto-v${V}-Linux-x86_64.zip']
check('CI names the release files Yaz0moto-v<version>-<platform>',
      all(n in artifacts for n in CI_NAMES) and 'Yaz0moto-v$v-Windows-x64.zip' in artifacts)
check('CI uploads Yaz0moto-* artifacts only', 'path: Pyamoto' not in artifacts and artifacts.count('Yaz0moto-') >= 4)
check('CI packages the new desktop file and icon',
      'buildtools/Yaz0moto.desktop' in artifacts and 'yaz0moto1024.png' in artifacts and 'chmod +x "${APPDIR}/AppRun" "${APPDIR}/Yaz0moto"' in artifacts)
check('workflows build from deluxe-support, not master', all('master' not in text for text in workflows.values())
      and 'branches: [deluxe-support]' in workflows['nightly.yml'])
check('nightly rebuilds when bntxlib changes', "'bntxlib/**'" in workflows['nightly.yml'])
check('release/nightly preflight checks the renamed entry point',
      all('yaz0moto.py' in workflows[f] and 'pyamoto.py' not in workflows[f] for f in ('release.yml', 'nightly.yml')))

# the updater must pick the right asset out of a release named the way CI names things
from miyamoto import updater  # noqa: E402  (imports Qt; fine headless)
assets = [{'name': n} for n in ('Yaz0moto-v1.0.0-Windows-x64.zip', 'Yaz0moto-v1.0.0-macOS-universal.zip',
                                'Yaz0moto-v1.0.0-Linux-x86_64.zip', 'Yaz0moto-v1.0.0-Linux-x86_64.AppImage')]
release = types.SimpleNamespace(assets=assets)
pick = lambda **kw: (updater._asset_for_platform(release, **kw) or {}).get('name')
check('updater picks the Windows asset', pick(system='Windows', machine='x86_64') == 'Yaz0moto-v1.0.0-Windows-x64.zip')
check('updater picks the macOS asset (arm64 and Intel)',
      pick(system='Darwin', machine='arm64') == pick(system='Darwin', machine='x86_64') == 'Yaz0moto-v1.0.0-macOS-universal.zip')
check('updater picks the Linux AppImage / zip',
      pick(system='Linux', machine='x86_64', appimage=True) == 'Yaz0moto-v1.0.0-Linux-x86_64.AppImage'
      and pick(system='Linux', machine='x86_64', appimage=False) == 'Yaz0moto-v1.0.0-Linux-x86_64.zip')

# version handling: releases are tagged v<major>.<minor>.<patch> and compared numerically
from unittest import mock  # noqa: E402
with mock.patch.object(updater.globals, 'MiyamotoVersion', '1.0.0'), mock.patch.object(updater.globals, 'MiyamotoReleaseType', 'release'):
    newer = lambda v: updater._is_newer(types.SimpleNamespace(channel='release', version=v, tag='v' + v))
    check('an installed 1.0.0 is up to date against release v1.0.0', not newer('1.0.0'))
    check('an installed 1.0.0 is offered v1.0.1 and v1.1.0', newer('1.0.1') and newer('1.1.0'))
    check('an installed 1.0.0 is not offered an older release', not newer('0.9.9'))

# ---------------------------------------------------------------- user-data migration from Pyamoto
def data_parent(home, xdg, appdata):
    if platform.system() == 'Darwin':
        return os.path.join(home, 'Library', 'Application Support')
    if platform.system() == 'Windows':
        return appdata
    return xdg


def run_globals(env_dirs, extra=''):
    home, xdg, appdata = env_dirs
    env = dict(os.environ, HOME=home, USERPROFILE=home, XDG_CONFIG_HOME=xdg, APPDATA=appdata, QT_QPA_PLATFORM='offscreen')
    code = extra + 'import miyamoto.globals as g; print("USERDATA=" + g.user_data_path)'
    out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    m = re.search(r'USERDATA=(.*)', out.stdout)
    return (m.group(1).strip() if m else None), out


tmp = tempfile.mkdtemp()
try:
    def fresh(name):
        base = os.path.join(tmp, name)
        dirs = tuple(os.path.join(base, d) for d in ('home', 'xdg', 'appdata'))
        for d in dirs:
            os.makedirs(d)
        return dirs, data_parent(*dirs)

    # old Pyamoto data, no Yaz0moto data -> copied
    dirs, parent = fresh('migrate')
    old = os.path.join(parent, 'Pyamoto'); os.makedirs(os.path.join(old, 'mods', 'mymod'))
    open(os.path.join(old, 'settings.json'), 'w').write('{"GamePath_NSMBUDX": "X:/game/Course"}')
    open(os.path.join(old, 'mods', 'mymod', 'main.xml'), 'w').write('<mod/>')
    path, out = run_globals(dirs)
    check('user data lives in a "Yaz0moto" folder', path == os.path.join(parent, 'Yaz0moto'), out.stderr[-300:])
    check('first launch copies Pyamoto settings and mods across',
          os.path.isfile(os.path.join(parent, 'Yaz0moto', 'settings.json'))
          and open(os.path.join(parent, 'Yaz0moto', 'settings.json')).read() == '{"GamePath_NSMBUDX": "X:/game/Course"}'
          and os.path.isfile(os.path.join(parent, 'Yaz0moto', 'mods', 'mymod', 'main.xml')))
    check('the original Pyamoto folder is left untouched',
          open(os.path.join(old, 'settings.json')).read() == '{"GamePath_NSMBUDX": "X:/game/Course"}')

    # running again never overwrites newer Yaz0moto data
    open(os.path.join(parent, 'Yaz0moto', 'settings.json'), 'w').write('{"changed": true}')
    run_globals(dirs)
    check('later launches do not overwrite Yaz0moto data', open(os.path.join(parent, 'Yaz0moto', 'settings.json')).read() == '{"changed": true}')

    # fresh install: nothing is created just by importing
    dirs, parent = fresh('fresh')
    path, _ = run_globals(dirs)
    check('fresh install: no Pyamoto data means nothing is copied', not os.path.exists(os.path.join(parent, 'Yaz0moto')))

    # a failed copy must not leave a half-copied folder that would be mistaken for complete next time
    dirs, parent = fresh('broken')
    os.makedirs(os.path.join(parent, 'Pyamoto')); open(os.path.join(parent, 'Pyamoto', 'settings.json'), 'w').write('{}')
    _, out = run_globals(dirs, extra='import shutil\n'
                                     'def _boom(src, dst, *a, **k):\n'
                                     '    import os; os.makedirs(dst); open(os.path.join(dst, "partial"), "w").write("x"); raise OSError("disk full")\n'
                                     'shutil.copytree = _boom\n')
    check('a failed copy is cleaned up and does not crash startup',
          out.returncode == 0 and not os.path.exists(os.path.join(parent, 'Yaz0moto')), out.stderr[-300:])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---------------------------------------------------------------- what the user sees
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5 import QtWidgets  # noqa: E402
qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
import miyamoto.app  # noqa: E402,F401  (installs the Cython import hook and loads the UI modules)
from miyamoto.dialogs import AboutDialog  # noqa: E402

about = AboutDialog()
texts = [w.text() for w in about.findChildren(QtWidgets.QLabel)]
joined = ' | '.join(texts)
check('About box title and heading say Yaz0moto', about.windowTitle() == 'About Yaz0moto' and 'Yaz0moto Level Editor' in texts)
check('About box links to this project, not upstream', ('github.com/%s"' % REPO) in joined and 'Zenith-Team/Pyamoto' not in joined)
check('About box names the maintainer and credits upstream', 'Steammaker212' in joined and 'Pyamoto' in joined and 'Miyamoto' in joined)
check('About box no longer sends users to the Zenith Discord', 'discord' not in joined.lower())

app_src = read('miyamoto/app.py')
check('main window title is Yaz0moto (and Yaz0moto Nightly)', "'Yaz0moto Nightly' if globals.MiyamotoReleaseType == 'nightly' else 'Yaz0moto'" in app_src)
check('crash dialog points to this project\'s issues', ('https://github.com/%s/issues' % REPO) in app_src and 'go.nsmbu.net/discord' not in app_src)
check('relaunching (new window) starts yaz0moto.py', "'yaz0moto.py'" in app_src and "'pyamoto.py'" not in app_src)
check('exported-object files from Pyamoto are still readable', "'__pyamoto_props__'" in read('miyamoto/puzzle.py'))

# ---------------------------------------------------------------- documentation links
def slug(heading):
    heading = re.sub(r'[^\w\- ]', '', heading.strip().lower())
    return heading.replace(' ', '-')


DOCS = ['README.md', 'CHANGELOG.md', 'CREDITS.md', 'Deluxe-Setup.md', 'Deluxe-Changelog.md', 'docs/RELEASING.md']
broken = []
for doc in DOCS:
    if not os.path.isfile(doc):
        broken.append('%s is missing' % doc)
        continue
    base = os.path.dirname(doc)
    for target in re.findall(r'\]\(([^)\s]+)\)', read(doc)):
        if target.startswith(('http://', 'https://', 'mailto:')):
            continue
        path, _, anchor = target.partition('#')
        file = os.path.normpath(os.path.join(base, path)) if path else doc
        if not os.path.exists(os.path.join(ROOT, file)):
            broken.append('%s -> %s (file not found)' % (doc, target))
        elif anchor and file.endswith('.md'):
            anchors = {slug(h) for h in re.findall(r'(?m)^#{1,6} +(.+?)\s*$', read(file))}
            if anchor not in anchors:
                broken.append('%s -> %s (no such heading)' % (doc, target))
check('every link between the docs resolves (files and #anchors)', not broken, '\n      ' + '\n      '.join(broken))
readme = read('README.md')
check('README links the Deluxe changelog and the credits', '(./Deluxe-Changelog.md)' in readme and '(./CREDITS.md)' in readme)
stale = [d for d in DOCS if 'Steammaker212/Pyamoto' in read(d) or 'Zenith-Team/Yaz0moto' in read(d)]
check('docs use the Yaz0moto repository name', not stale, ', '.join(stale))
check('docs name the branch the workflows actually use',
      'deluxe-support' in read('docs/RELEASING.md') and 'deluxe-support' in workflows['nightly.yml'])

print('\n%d/%d passed' % (sum(ok for _, ok in results), len(results)))
sys.exit(0 if all(ok for _, ok in results) else 1)
