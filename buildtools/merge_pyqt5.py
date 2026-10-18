#!/usr/bin/env python3
"""
Merge x86_64 PyQt5 binaries into an arm64 Yaz0moto.app bundle in-place,
producing a universal (arm64 + x86_64) app ready for DMG packaging.

Usage:
    python buildtools/merge_pyqt5.py <app_bundle> <x86_pyqt5_dir>

<app_bundle>   — path to the arm64 .app (modified in-place)
<x86_pyqt5_dir> — directory whose PyQt5/ subtree contains x86_64 wheels
                   extracted by: python3 -m zipfile -e *.whl <x86_pyqt5_dir>
"""

import os, sys, subprocess

MACHO_MAGICS = {
    b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf',  # big-endian 32/64-bit
    b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe',  # little-endian 32/64-bit
    b'\xca\xfe\xba\xbe',                         # fat (universal)
}

def is_macho(path):
    try:
        with open(path, 'rb') as f:
            return f.read(4) in MACHO_MAGICS
    except OSError:
        return False

def get_archs(path):
    r = subprocess.run(['lipo', '-archs', path], capture_output=True, text=True)
    return set(r.stdout.strip().split())

def find_pyqt5_root(app_bundle):
    for dirpath, _, _ in os.walk(app_bundle):
        if os.path.basename(dirpath) == 'PyQt5':
            return dirpath
    return None

def main():
    if len(sys.argv) != 3:
        print(f'Usage: {sys.argv[0]} <app_bundle> <x86_pyqt5_dir>')
        sys.exit(1)

    app_bundle = sys.argv[1]
    x86_root   = sys.argv[2]

    x86_pyqt5 = os.path.join(x86_root, 'PyQt5')
    if not os.path.isdir(x86_pyqt5):
        print(f'ERROR: PyQt5 not found inside {x86_root}')
        sys.exit(1)

    arm64_pyqt5 = find_pyqt5_root(app_bundle)
    if not arm64_pyqt5:
        print(f'ERROR: No PyQt5 directory found in {app_bundle}')
        sys.exit(1)

    print(f'arm64 PyQt5 : {arm64_pyqt5}')
    print(f'x86_64 PyQt5: {x86_pyqt5}')

    merged = already = missing = 0

    for dirpath, _, filenames in os.walk(arm64_pyqt5):
        for fname in filenames:
            arm_path = os.path.join(dirpath, fname)
            if os.path.islink(arm_path) or not is_macho(arm_path):
                continue

            rel      = os.path.relpath(arm_path, arm64_pyqt5)
            x86_path = os.path.join(x86_pyqt5, rel)

            if not os.path.isfile(x86_path):
                missing += 1
                continue

            arm_archs = get_archs(arm_path)
            if 'x86_64' in arm_archs:
                already += 1
                continue

            x86_archs = get_archs(x86_path)
            if 'x86_64' not in x86_archs:
                missing += 1
                continue

            # If the downloaded wheel is universal2, thin it to x86_64 first
            # so lipo -create doesn't complain about duplicate arm64 slices.
            tmp_thin = None
            src_x86  = x86_path
            if len(x86_archs) > 1:
                tmp_thin = x86_path + '._x86slice'
                subprocess.run(
                    ['lipo', x86_path, '-thin', 'x86_64', '-output', tmp_thin],
                    check=True
                )
                src_x86 = tmp_thin

            tmp_out = arm_path + '._lipo'
            subprocess.run(
                ['lipo', '-create', arm_path, src_x86, '-output', tmp_out],
                check=True
            )
            os.replace(tmp_out, arm_path)

            if tmp_thin:
                os.remove(tmp_thin)

            print(f'  merged  {rel}')
            merged += 1

    print(f'\nDone: {merged} merged | {already} already universal | {missing} x86_64 not found')

if __name__ == '__main__':
    main()
