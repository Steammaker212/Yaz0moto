#!/usr/bin/env python3
"""
Makes every Mach-O file of the macOS app universal (arm64 + x86_64), so it runs natively on
Apple Silicon and Intel Macs.

The app is built with python.org's universal2 Python, so Python itself, its standard library,
cx_Freeze's files and Yaz0moto's Cython extensions are universal already. A few packages only
publish wheels for one architecture at a time (PyQt5 and the Qt libraries in PyQt5-Qt5), and
pip installs the build machine's. This supplies the other half from that architecture's wheels.

    python buildtools/make_universal.py packages
        prints "name==version" for each installed distribution with single-architecture
        files (what to download for the other architecture)
    python buildtools/make_universal.py merge <app bundle> <other_arch_dir>
        <other_arch_dir>: those wheels unpacked into one folder (laid out like site-packages).
        Merges each single-architecture file of the bundle with its counterpart there, then
        checks every Mach-O file in the bundle has both architectures (exit code 1 if not).
"""

import os
import subprocess
import sys

ARCHS = {'arm64', 'x86_64'}

MACHO_MAGICS = {
    b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf',  # big-endian 32/64-bit
    b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe',  # little-endian 32/64-bit
    b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf',  # fat (universal) 32/64-bit
}


def is_macho(path):
    try:
        with open(path, 'rb') as f:
            return f.read(4) in MACHO_MAGICS
    except OSError:
        return False


def archs(path):
    try:
        r = subprocess.run(['lipo', '-archs', path], capture_output=True, text=True)
    except OSError:  # no lipo (not macOS): nothing can be told
        return set()
    return set(r.stdout.split()) if r.returncode == 0 else set()


def macho_files(root):
    """Every Mach-O file under root (symlinks are left alone: they point at files listed anyway)."""
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if not os.path.islink(path) and is_macho(path):
                yield path


def single_arch_packages(get_archs=archs):
    """The installed distributions that have Mach-O files missing an architecture, as 'name==version'."""
    from importlib import metadata
    found = set()
    for dist in metadata.distributions():
        for f in dist.files or ():
            path = str(f.locate())
            if path.endswith(('.so', '.dylib')) or '.framework/' in path.replace(os.sep, '/'):
                if os.path.isfile(path) and not os.path.islink(path) and is_macho(path) \
                        and not ARCHS <= get_archs(path):
                    found.add('%s==%s' % (dist.metadata['Name'], dist.version))
                    break
    return sorted(found)


def index_by_name(root):
    """{file name: [paths]} for the Mach-O files under root."""
    index = {}
    for path in macho_files(root):
        index.setdefault(os.path.basename(path), []).append(path)
    return index


def counterpart(path, other_root, by_name):
    """
    The file in other_root that is the same file as path in the bundle: the same path after
    some folder (Contents/Resources/lib/PyQt5/Qt5/lib/QtCore.framework/... matches
    PyQt5/Qt5/lib/QtCore.framework/... in the unpacked wheels), else the only file there with
    its name. None if there's none.
    """
    parts = os.path.normpath(path).split(os.sep)
    for i in range(1, len(parts)):
        candidate = os.path.join(other_root, *parts[i:])
        if os.path.isfile(candidate):
            return candidate
    same = by_name.get(parts[-1], [])
    return same[0] if len(same) == 1 else None


def lipo_merge(path, other, missing):
    """Adds the `missing` architecture slice of `other` to the file at path."""
    src = other
    thin = None
    if len(archs(other)) > 1:
        thin = path + '._slice'
        subprocess.run(['lipo', other, '-thin', missing, '-output', thin], check=True)
        src = thin
    out = path + '._lipo'
    subprocess.run(['lipo', '-create', path, src, '-output', out], check=True)
    os.chmod(out, os.stat(path).st_mode & 0o777)
    os.replace(out, path)
    if thin:
        os.remove(thin)


def merge(bundle, other_root, get_archs=archs, do_merge=lipo_merge, log=print):
    """Merges the bundle's single-architecture files; returns the files still missing an architecture."""
    by_name = index_by_name(other_root) if os.path.isdir(other_root) else {}
    merged = 0
    for path in macho_files(bundle):
        have = get_archs(path)
        missing = ARCHS - have
        if not missing or not have:
            continue
        other = counterpart(path, other_root, by_name)
        if other is None or not missing <= get_archs(other):
            continue
        for arch in sorted(missing):
            do_merge(path, other, arch)
        merged += 1
        log('  merged  %s  (+%s)' % (os.path.relpath(path, bundle), ', '.join(sorted(missing))))
    not_universal = [p for p in macho_files(bundle) if not ARCHS <= get_archs(p)]
    log('Merged %d file(s). Not universal: %d' % (merged, len(not_universal)))
    for p in not_universal:
        log('  NOT UNIVERSAL  %s  (%s)' % (os.path.relpath(p, bundle), ', '.join(sorted(get_archs(p))) or '?'))
    return not_universal


def main(argv):
    if len(argv) >= 2 and argv[1] == 'packages':
        print('\n'.join(single_arch_packages()))
        return 0
    if len(argv) == 4 and argv[1] == 'merge':
        return 1 if merge(argv[2], argv[3]) else 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
