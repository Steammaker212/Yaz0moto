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

While Pyamoto serves as the incredible upstream foundation for Wii U editing, Yaz0moto aims to be the definitive tool for Switch modders. We track upstream updates while maintaining the custom C-extensions and logic required to parse Deluxe's little-endian `.sarc` formats, `Unit` folder structure, and Yaz0 compression.

### New Super Mario Bros. U Deluxe
Pick *New Super Mario Bros. U Deluxe* in the setup wizard (or **Preferences > Game Setup**) and select the `Course` folder from your dumped game's `romfs`. The `Unit` folder, where Deluxe keeps its tilesets, must sit right next to it. See [Deluxe-Setup.md](./Deluxe-Setup.md) for the full walkthrough.

- Levels are saved as plain little-endian `.sarc` files.
- **Edit Tilesets** opens the exact tileset files the open level uses, and saves them back into `Unit`. *Export Tileset* writes a standalone `.szs`, and *Import Tileset from file* reads one.
- In the zone Background tab, the file name shown is the real Deluxe one (`dv_<name>.Nin_NX_NVN.szs`, in `romfs/Model`), which is where a custom background model goes.
- Opening a level from the other game offers to switch games; switching game in Preferences starts a new level.

You must provide your own legally obtained game files.

## Changelog
Read the [changelog](./CHANGELOG.md) for a full list of changes and additions.

## Contributing
Bug reports and feature requests go in the [Issues tab](https://github.com/Steammaker212/Yaz0moto/issues). Pull requests are welcome; see [Running from Source](#running-from-source) to set up a development environment. Maintainers: see [docs/RELEASING.md](./docs/RELEASING.md). `tests/deluxe_smoke_test.py` and `tests/branding_test.py` are quick checks to run before sending a change.

## Features
- **Deluxe First:** Native support for Switch `.sarc` levels and Deluxe background naming (`dv_Mori.Nin_NX_NVN.szs`).
- **Crash Fixes:** Resolved the background save crash caused by out-of-range parallax values.
- **Uncategorized Levels:** Properly displays and allows opening of the 101 unnamed levels in Deluxe.
- **Windows Ready:** Includes an MSVC compatibility shim to compile the FastYZ C library natively on Windows.

## Installation & Setup (Windows)
Before you begin, install the following prerequisites:
- **[Git for Windows](https://git-scm.com/download/win)**
- **[Python 3](https://www.python.org/downloads/)** — make sure “Add Python to PATH” is checked during installation.
- **[Visual Studio Build Tools 2022](https://visualstudio.microsoft.com/visual-cpp-build-tools/)** — select the **Desktop development with C++** workload.

*After installing these tools, close and reopen PowerShell.*

### Download Yaz0moto
Open PowerShell and run:
```bash
git clone --recurse-submodules https://github.com/Steammaker212/Yaz0moto
cd Yaz0moto
bash setup_venv.sh

# macOS/Linux
.venv/bin/python3 yaz0moto.py

# or on Windows:
.venv\Scripts\python yaz0moto.py
```
For detailed step‑by‑step instructions, please see the **[Deluxe-Setup](./Deluxe-Setup.md)**.
### Credits
**[Checkout Credits](./CREDITS.md)**

### Disclaimer
AI tools are used in the development of this program.
