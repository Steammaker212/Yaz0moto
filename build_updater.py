#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# build_updater.py
# Freezes the Yaz0moto updater (yaz0moto_updater.py) into a folder of its own, which
# build.py puts in the package's `updater` folder. It has its own Python runtime, so it
# can replace every file of Yaz0moto while it runs.
#
#   python build_updater.py <output folder>

import os
import sys

from cx_Freeze import Executable, setup

if len(sys.argv) < 2:
    sys.exit('usage: build_updater.py <output folder>')

target = os.path.abspath(sys.argv[1])
sys.argv[1:] = ['build_exe']

from yaz0moto_updater import UPDATER_VERSION  # noqa: E402

# Only what the updater imports: the standard library, ssl for HTTPS, certifi for its CAs
excludes = ['tkinter', 'unittest', 'pydoc', 'doctest', 'pdb', 'difflib', 'multiprocessing',
            'asyncio', 'sqlite3', 'xmlrpc', 'lib2to3', 'distutils', 'setuptools', 'pip',
            'PyQt5', 'Cython', 'pyximport', 'requests', 'numpy', 'yaz0moto']
packages = ['encodings', 'ssl', 'urllib', 'http', 'json', 'zipfile', 'hashlib', 'ctypes']
try:
    import certifi  # noqa: F401
    packages.append('certifi')
except ImportError:
    pass

setup(
    name='Yaz0moto-Updater',
    version=UPDATER_VERSION,
    description='Yaz0moto updater',
    options={
        'build_exe': {
            'build_exe': target,
            'excludes': excludes,
            'packages': packages,
            'optimize': 2,
            'silent': True,
            'include_msvcr': sys.platform == 'win32',
        },
    },
    executables=[
        # A console program: run by hand it prints its progress; Yaz0moto starts it with
        # no window
        Executable('yaz0moto_updater.py', target_name='Yaz0moto-Updater',
                   icon='yaz0data/app_icons/win_icon.ico' if sys.platform == 'win32' else None),
    ],
)
print('>> Built the updater in %s' % target)
