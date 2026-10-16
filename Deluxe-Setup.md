# Pyamoto Deluxe — Setup Guide

A simple guide to installing and running Pyamoto with **New Super Mario Bros. U Deluxe**.

## Requirements

Before you begin, install the following:

- **Git for Windows**
- **Python 3** — make sure “Add Python to PATH” is checked during installation.
- **Visual Studio Build Tools 2022** — select the **Desktop development with C++** workload.

After installing these tools, close and reopen PowerShell.

## Step 1: Download Pyamoto

Open PowerShell and run:

```powershell
git clone --recurse-submodules https://github.com/Steammaker212/Pyamoto.git
cd Pyamoto
git checkout deluxe-support
```

## Step 2: Install Dependencies

Run these commands in PowerShell:

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m pip install --upgrade setuptools
```

## Step 3: Build the Required Extension

Copy and run this entire command in PowerShell:

```powershell
py -3 -c "from setuptools import setup, Extension; from Cython.Build import cythonize; setup(ext_modules=cythonize([Extension('fastyz', sources=['fastyz.pyx', 'FastYZ/fastyz.c'], include_dirs=['.', 'FastYZ'], extra_compile_args=['/FImsvc_compat.h'])], language_level=3), script_args=['build_ext', '--inplace'])"
```

Wait for the build process to finish before continuing.

## Step 4: Launch Pyamoto

Run:

```powershell
py -3 pyamoto.py
```

The setup wizard should open.

## Step 5: Configure New Super Mario Bros. U Deluxe

1. Select **New Super Mario Bros. U Deluxe** in the setup wizard.
2. Locate your game's extracted files.
3. Select the `Course` folder.
4. Make sure the `Unit` folder is located beside the `Course` folder.
5. Open a level and start using Pyamoto!

## Troubleshooting

- **Python is not recognized:** Reinstall Python with “Add Python to PATH” enabled, then reopen PowerShell.
- **Git is not recognized:** Install Git for Windows and reopen PowerShell.
- **C++ compiler errors:** Ensure Visual Studio Build Tools 2022 is installed with the **Desktop development with C++** workload.
- **Missing files or folders:** Confirm that you cloned the repository with `--recurse-submodules` and checked out the `deluxe-support` branch.

## Repository

https://github.com/Steammaker212/Pyamoto

**Note:** This guide covers setup only. You must provide your own legally obtained game files.
