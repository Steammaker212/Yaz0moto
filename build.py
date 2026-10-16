#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Pyamoto Level Editor
# Copyright (C) 2009-2026 Pyamoto contributors
# This file is part of Pyamoto.

# See LICENSE.txt for more information.

# build.py
# Builds Miyamoto! to a binary
# Use the values below to configure the release:

from miyamoto.globals import MiyamotoVersion
import os, os.path, platform, shutil, sys

# Set architectures for universal build on macOS.
# CI overrides ARCHFLAGS per-runner (arm64 or x86_64) then lipo-merges.
# Local builds without ARCHFLAGS set default to universal.
if sys.platform == 'darwin':
    if 'ARCHFLAGS' not in os.environ:
        os.environ["ARCHFLAGS"] = "-arch x86_64 -arch arm64"

Version = MiyamotoVersion
PackageName = 'miyamoto_v%s' % Version

# setuptools requires a PEP 440 version string; nightly builds use a commit
# SHA which isn't valid, so fall back to '0.0' for the setup() call only.
import re as _re
_SetupVersion = Version if _re.match(r'^\d+\.\d+(\.\d+)*$', Version) else '0.0'


################################################################
################################################################

# Imports
import os, os.path, platform, shutil, sys
from cx_Freeze import setup, Executable

from setuptools import Extension
from Cython.Build import cythonize
from setuptools.command.build_ext import build_ext

cmdclass_dict = {}

if sys.platform == 'win32':
    os.environ["CC"] = "clang-cl"
    os.environ["CXX"] = "clang-cl"

    class ClangBuildExt(build_ext):
        def build_extensions(self):
            original_spawn = self.compiler.spawn
            def hijacked_spawn(cmd, **kwargs):
                if 'cl.exe' in cmd[0].lower():
                    cmd[0] = 'clang-cl'
                elif 'link.exe' in cmd[0].lower():
                    cmd[0] = 'lld-link'
                original_spawn(cmd, **kwargs)

            self.compiler.spawn = hijacked_spawn
            super().build_extensions()
            
    cmdclass_dict = {'build_ext': ClangBuildExt}

# Pick a build directory
dir_ = 'distrib/' + PackageName

# Print some stuff
print('[[ Freezing Miyamoto! ]]')
print('>> Destination directory: %s' % dir_)

# Add the "build" parameter to the system argument list
if len(sys.argv) == 1:
    sys.argv.extend(['build_ext', '--inplace', 'build_exe'])

# Clear the directory
if os.path.isdir(dir_): shutil.rmtree(dir_)
os.makedirs(dir_)

# exclude QtWebChannel, QtWebSockets and QtNetwork to save space, plus Python stuff we don't use
excludes = ['doctest', 'pdb', 'unittest', 'difflib',
    'multiprocessing', 'ssl',
    'PyQt5.QtWebChannel', 'PyQt5.QtWebSockets', 'PyQt5.QtNetwork']

# Extension flags — derived from ARCHFLAGS (already set above for macOS)
extra_args = []
if sys.platform == 'darwin':
    extra_args = os.environ.get("ARCHFLAGS", "").split()

fastyz_ext = Extension(
    name="fastyz",
    sources=["fastyz.pyx", "FastYZ/fastyz.c"],
    include_dirs=["."],
    extra_compile_args=extra_args,
    extra_link_args=extra_args
)

addrlib_ext = Extension(
    name="addrlib.addrlib_cy",
    sources=["addrlib/addrlib_cy.pyx"],
    extra_compile_args=extra_args,
    extra_link_args=extra_args
)

bc3_compress_ext = Extension(
    name="bc3.compress_cy",
    sources=["bc3/compress_cy.pyx"],
    extra_compile_args=extra_args,
    extra_link_args=extra_args
)
        
bc3_decompress_ext = Extension(
    name="bc3.decompress_cy",
    sources=["bc3/decompress_cy.pyx"],
    extra_compile_args=extra_args,
    extra_link_args=extra_args
)

bntx_swizzle_ext = Extension(
    name="bntxlib.swizzle_cy",
    sources=["bntxlib/swizzle_cy.pyx"],
    extra_compile_args=extra_args,
    extra_link_args=extra_args
)

bntx_formconv_ext = Extension(
    name="bntxlib.formConv_cy",
    sources=["bntxlib/formConv_cy.pyx"],
    extra_compile_args=extra_args,
    extra_link_args=extra_args
)

bntx_bcn_decompress_ext = Extension(
    name="bntxlib.bcn.decompress_cy",
    sources=["bntxlib/bcn/decompress_cy.pyx"],
    extra_compile_args=extra_args,
    extra_link_args=extra_args
)

# Platform-specific include_files
include_files = [
    'miyamotodata',
    'miyamotoextras',
    'project.json',
    'license.txt',
    'README.md'
]
if sys.platform == 'darwin':
    include_files.append('tools/mac')
elif sys.platform == 'win32':
    include_files.append('tools/win')
else:
    include_files.append('tools/linux')

# Set it up
base = 'gui' if sys.platform == 'win32' else None
setup(
    name = 'Pyamoto',
    version = _SetupVersion,
    description = 'New Super Mario Bros. U Level Editor',
    options={
        'build_exe': {
            'excludes': excludes,
            'packages': ['encodings', 'encodings.hex_codec', 'encodings.utf_8', 'addrlib', 'bc3', 'bntxlib', 'bntxlib.bcn', 'miyamoto', 'requests', 'certifi'],
            'includes': ['fastyz', 'addrlib', 'bc3', 'bntxlib', 'ssl'],
            'build_exe': dir_,
            'optimize': 2,
            'silent': True,
            'include_files': include_files
            },
        'bdist_mac': {
            'bundle_name': 'Pyamoto',
            'iconfile': 'miyamotodata/app_icons/pyamoto.icns',
        }
        },
    cmdclass = cmdclass_dict,
    ext_modules = cythonize([fastyz_ext, addrlib_ext, bc3_compress_ext, bc3_decompress_ext,
                            bntx_swizzle_ext, bntx_formconv_ext, bntx_bcn_decompress_ext], language_level=3),
    executables = [
        Executable(
            'pyamoto.py',
            target_name = 'Pyamoto',
            icon = 'miyamotodata/app_icons/win_icon.ico',
            base = base,
            ),
        ],
    )
print('>> Built frozen executable!')



# Post-build finalization
if 'bdist_mac' in sys.argv:
    print('>> Performing macOS specific finalization...')
    app_path = 'build/Pyamoto.app'
    if os.path.isdir(app_path):
        settings_path = os.path.join(app_path, 'Contents/MacOS/settings.ini')
        if os.path.isfile(settings_path):
            os.remove(settings_path)
            print('>> Removed local settings.ini from bundle.')
elif platform.system() == 'Windows':
    try: os.unlink(dir_ + '/w9xpopen.exe')
    except: pass

print('>> Miyamoto! has been frozen !')
