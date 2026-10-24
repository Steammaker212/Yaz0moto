# Yaz0moto Deluxe - Setup Guide

A simple guide to running Yaz0moto with **New Super Mario Bros. U Deluxe**.

## Easiest way: download a release

1. Download the build for your system from the [releases page](https://github.com/Steammaker212/Yaz0moto/releases/latest) and unzip it (Windows: `Yaz0moto.exe`).
2. Start it and follow the setup wizard, then skip to [Configure Deluxe](#configure-new-super-mario-bros-u-deluxe).

No Python or compiler is needed for this route. If there is no release for your system yet, use the source route below.

## Running from source (Windows)

### Requirements

Install the following, then close and reopen PowerShell:

- **Git for Windows**
- **Python 3** - make sure "Add Python to PATH" is checked during installation.
- **Visual Studio Build Tools 2022** - select the **Desktop development with C++** workload.

### Step 1: Download Yaz0moto

```powershell
git clone --recurse-submodules https://github.com/Steammaker212/Yaz0moto.git
cd Yaz0moto
```

### Step 2: Install dependencies

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m pip install --upgrade setuptools
```

### Step 3: Build the required extension

Copy and run this entire command in PowerShell and wait for it to finish:

```powershell
py -3 -c "from setuptools import setup, Extension; from Cython.Build import cythonize; setup(ext_modules=cythonize([Extension('fastyz', sources=['fastyz.pyx', 'FastYZ/fastyz.c'], include_dirs=['.', 'FastYZ'], extra_compile_args=['/FImsvc_compat.h'])], language_level=3), script_args=['build_ext', '--inplace'])"
```

### Step 4: Launch Yaz0moto

```powershell
py -3 main.py
```

The setup wizard should open.

## Configure New Super Mario Bros. U Deluxe

1. Select **New Super Mario Bros. U Deluxe** in the setup wizard (or **Preferences > Game Setup**).
2. Locate your game's extracted `romfs` files.
3. Select the `Course` folder.
4. Make sure the `Unit` folder (tilesets) is located beside the `Course` folder.
5. Open a level with **File > Open Level by Name** and start editing.

Saving a level writes the `.sarc` file. Tilesets you edit are written into `Unit`, so keep a backup of that folder, especially before changing a main tileset (these are shared by many levels).

## Troubleshooting

- **Python is not recognized:** Reinstall Python with "Add Python to PATH" enabled, then reopen PowerShell.
- **Git is not recognized:** Install Git for Windows and reopen PowerShell.
- **"Cython is not available" or `No module named 'fastyz'`:** the extension in Step 3 did not build. Make sure Visual Studio Build Tools 2022 is installed with the **Desktop development with C++** workload, then repeat Step 3. If it fails on a very new Python version, try Python 3.12 or 3.13.
- **Missing files or folders:** Confirm that you cloned the repository with `--recurse-submodules`.
- **Settings from Pyamoto:** they are copied to the Yaz0moto data folder on first launch; the original Pyamoto folder is not modified.

## Repository

https://github.com/Steammaker212/Yaz0moto

**Note:** This guide covers setup only. You must provide your own legally obtained game files.
