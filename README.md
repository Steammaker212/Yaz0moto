<img alt="banner" src="https://github.com/user-attachments/assets/763f3aaa-f340-4f33-b853-546d213f2c3d" />
<div align="center">
    <img alt="switch" height="56" src="https://github.com/user-attachments/assets/f339e2a9-146c-42be-85f8-31a32af5999a">
    <a href="https://discord.gg/RGcRsVkP8z">
    <img alt="discord" height="56" src="https://github.com/user-attachments/assets/ce08f78a-d435-4dd5-9e4a-a47659f57b5b">
</a>
    <a href="https://zenith.nsmbu.net/wiki/Pyamoto_Level_Editor">
        <img alt="docs" height="56" src="https://github.com/user-attachments/assets/425696ef-be66-42cd-9f3f-67dfbd36487d">
    </a>
</div>

## Overview
**Yaz0moto** is a dedicated fork of [Pyamoto](https://github.com/Zenith-Team/Pyamoto), specifically designed to prioritize, stabilize, and expand support for **New Super Mario Bros. U Deluxe** on the Nintendo Switch. 

While Pyamoto serves as the incredible upstream foundation for Wii U editing, Yaz0moto aims to be the definitive tool for Switch modders. Pyamoto's changes are merged in over time (see [docs/RELEASING.md](./docs/RELEASING.md)), while Yaz0moto adds what Deluxe needs on top: its little-endian `.sarc` levels, the `Unit` tileset folder and BNTX textures (code taken from Miyamoto! DX).

## Features
- **Deluxe First:** Native support for Switch `.sarc` levels and Deluxe background naming (`dv_Mori.Nin_NX_NVN.szs`).
- **Crash Fixes:** Resolved the background save crash caused by out-of-range parallax values, and sprite crashes on Python 3.10 or newer.
- **Uncategorized Levels:** Properly displays and allows opening of the 101 unnamed levels in Deluxe (worlds 40-50).
- **Windows Ready:** Includes an MSVC compatibility shim to compile the FastYZ C library natively on Windows.
- **Full tileset editing for Deluxe:** *Edit Tilesets* opens the exact files the open level uses from `Unit`, saves them back, and exports or imports standalone `.szs` tilesets, including the block, `?` block, coin and conveyor animations.
- **Safe switching between games:** opening a Wii U level while Deluxe is selected (or the reverse) offers to switch games instead of corrupting the level.
- **Wii U support kept:** everything Pyamoto does for the Wii U game still works, and the tests cover Wii U tileset round trips.
- **Ready-made builds:** Windows, macOS and Linux releases with a built-in updater (release and nightly channels).
- **Easy to move over:** your Pyamoto settings and data are copied across on first launch, and Miyamoto! DX settings are recognised.

The full list is in the [Deluxe changelog](./Deluxe-Changelog.md) and the [general changelog](./CHANGELOG.md).

## Usage
### New Super Mario Bros. U Deluxe
Pick *New Super Mario Bros. U Deluxe* in the setup wizard (or **Preferences > Game Setup**) and select the `Course` folder from your dumped game's `romfs`. The `Unit` folder, where Deluxe keeps its tilesets, must sit right next to it. See [Deluxe-Setup.md](./Deluxe-Setup.md) for the full walkthrough.

- Levels are saved as plain little-endian `.sarc` files.
- **Edit Tilesets** opens the exact tileset files the open level uses, and saves them back into `Unit`. *Export Tileset* writes a standalone `.szs`, and *Import Tileset from file* reads one.
- In the zone Background tab, the file name shown is the real Deluxe one (`dv_<name>.Nin_NX_NVN.szs`, in `romfs/Model`), which is where a custom background model goes.
- Opening a level from the other game offers to switch games; switching game in Preferences starts a new level.

You must provide your own legally obtained game files.

## Installation

### Download (recommended)
Get the latest build for your system from the [releases page](https://github.com/Steammaker212/Yaz0moto/releases/latest). No Python or compiler is needed.

| System | File |
|---|---|
| Windows (x64) | `Yaz0moto-v<version>-Windows-x64.zip` - unzip and run `Yaz0moto.exe` |
| macOS (universal) | `Yaz0moto-v<version>-macOS-universal.zip` - unzip and open `Yaz0moto.app` |
| Linux (x86_64) | `Yaz0moto-v<version>-Linux-x86_64.AppImage` (or the `.zip`) |

The builds are not code-signed, so Windows SmartScreen or macOS Gatekeeper may warn you the first time; on macOS, right-click the app and choose *Open*.

### Run from source
To build and run Yaz0moto yourself, install the following prerequisites first:
- **[Git for Windows](https://git-scm.com/download/win)**
- **[Python 3](https://www.python.org/downloads/)** — make sure “Add Python to PATH” is checked during installation.
- **[Visual Studio Build Tools 2022](https://visualstudio.microsoft.com/visual-cpp-build-tools/)** — select the **Desktop development with C++** workload.

*After installing these tools, close and reopen PowerShell.*

Windows (PowerShell):
```powershell
git clone --recurse-submodules https://github.com/Steammaker212/Yaz0moto
cd Yaz0moto
```
Then follow **[Deluxe-Setup](./Deluxe-Setup.md)** for installing dependencies and building the FastYZ extension.

macOS and Linux:
```bash
git clone --recurse-submodules https://github.com/Steammaker212/Yaz0moto
cd Yaz0moto
bash setup_venv.sh
.venv/bin/python3 main.py
```
A C compiler is needed for the Cython extensions.

## Changelog
Read the [changelog](./CHANGELOG.md) for a full list of changes and additions.

Deluxe-specific details, a Wii U/Deluxe comparison and known limitations are in the [Deluxe changelog](./Deluxe-Changelog.md).

## Contributing
Bug reports and feature requests go in the [Issues tab](https://github.com/Steammaker212/Yaz0moto/issues). Pull requests are welcome; see [Deluxe-Setup.md](./Deluxe-Setup.md) to set up a development environment. Maintainers: see [docs/RELEASING.md](./docs/RELEASING.md). `tests/deluxe_smoke_test.py` and `tests/branding_test.py` are quick checks to run before sending a change.

## Credits
Yaz0moto builds on Pyamoto, Miyamoto! and Miyamoto! DX. **[See the full credits](./CREDITS.md)**.

## Disclaimer
AI tools are used in the development of this program.
