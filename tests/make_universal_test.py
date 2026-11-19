"""
Tests for buildtools/make_universal.py (making every binary of the macOS app universal):
finding each single-architecture file's counterpart in the other architecture's wheels,
merging them, and reporting what is still not universal. lipo is replaced by fake slices,
so this runs on any system.

Run from anywhere:   python tests/make_universal_test.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'buildtools'))

import make_universal as mu  # noqa: E402

results = []


def check(label, ok):
    results.append((label, bool(ok)))
    print(('  OK  ' if ok else 'FAIL  ') + label)


MACHO = b'\xcf\xfa\xed\xfe' + bytes(28)
tmp = tempfile.mkdtemp(prefix='y0mu')
app = os.path.join(tmp, 'Yaz0moto.app')
other = os.path.join(tmp, 'other')
slices = {}


def put(path, arch_set, data=MACHO):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    slices[os.path.normcase(os.path.abspath(path))] = set(arch_set)
    return path


def get_archs(path):
    return set(slices.get(os.path.normcase(os.path.abspath(path)), ()))


def fake_merge(path, src, arch):
    assert arch in get_archs(src), (src, arch)
    slices[os.path.normcase(os.path.abspath(path))].add(arch)


lib = os.path.join(app, 'Contents', 'Resources', 'lib')
# Built on an Intel runner: Python, cx_Freeze and the Cython extensions are universal already
put(os.path.join(app, 'Contents', 'MacOS', 'Yaz0moto'), {'x86_64', 'arm64'})
put(os.path.join(lib, 'fastyz.cpython-39-darwin.so'), {'x86_64', 'arm64'})
# ...PyQt5 and Qt came from x86_64-only wheels
qtcore_so = put(os.path.join(lib, 'PyQt5', 'QtCore.abi3.so'), {'x86_64'})
qtcore_fw = put(os.path.join(lib, 'PyQt5', 'Qt5', 'lib', 'QtCore.framework', 'Versions', '5', 'QtCore'), {'x86_64'})
plugin = put(os.path.join(lib, 'PyQt5', 'Qt5', 'plugins', 'platforms', 'libqcocoa.dylib'), {'x86_64'})
copied = put(os.path.join(app, 'Contents', 'Frameworks', 'QtGui'), {'x86_64'})  # copied elsewhere by name
lonely = put(os.path.join(lib, 'mystery.so'), {'x86_64'})  # nothing to merge it with
with open(os.path.join(lib, 'readme.txt'), 'w') as f:
    f.write('not a binary')

# The arm64 wheels, unpacked like site-packages (one of them universal2)
put(os.path.join(other, 'PyQt5', 'QtCore.abi3.so'), {'arm64'})
put(os.path.join(other, 'PyQt5', 'Qt5', 'lib', 'QtCore.framework', 'Versions', '5', 'QtCore'), {'arm64'})
put(os.path.join(other, 'PyQt5', 'Qt5', 'plugins', 'platforms', 'libqcocoa.dylib'), {'arm64', 'x86_64'})
put(os.path.join(other, 'PyQt5', 'Qt5', 'lib', 'QtGui.framework', 'Versions', '5', 'QtGui'), {'arm64'})

found = sorted(os.path.relpath(p, app) for p in mu.macho_files(app))
check('only Mach-O files are looked at (%d)' % len(found), len(found) == 7 and not any(p.endswith('.txt') for p in found))
by_name = mu.index_by_name(other)
check('a file is matched by its path inside the package',
      mu.counterpart(qtcore_fw, other, by_name).endswith(os.path.join('QtCore.framework', 'Versions', '5', 'QtCore')))
check('...or, if it was copied somewhere else, by its name',
      mu.counterpart(copied, other, by_name).endswith(os.path.join('QtGui.framework', 'Versions', '5', 'QtGui')))
check('a file with no counterpart has none', mu.counterpart(lonely, other, by_name) is None)

log = []
left = mu.merge(app, other, get_archs=get_archs, do_merge=fake_merge, log=log.append)
check('every single-architecture file with a counterpart gets the other half',
      all(get_archs(p) == {'x86_64', 'arm64'} for p in (qtcore_so, qtcore_fw, plugin, copied)))
check('a universal2 counterpart works too (its arm64 slice is taken)', get_archs(plugin) == {'x86_64', 'arm64'})
check('what is still not universal is reported (so the build fails)', left == [lonely]
      and any('NOT UNIVERSAL' in line and 'mystery.so' in line for line in log))
check('without lipo (not macOS) the command line fails rather than pass blindly', mu.main(['x', 'merge', app, other]) == 1)

# Nothing left to do: a clean run
os.remove(lonely)
del slices[os.path.normcase(os.path.abspath(lonely))]
check('with everything universal nothing is reported', mu.merge(app, other, get_archs=get_archs, do_merge=fake_merge,
                                                                log=lambda *a: None) == [])

failed = [label for label, ok in results if not ok]
print('\n%d/%d passed' % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
