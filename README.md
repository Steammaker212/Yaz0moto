<img alt="banner" src="https://github.com/user-attachments/assets/ab7c7183-2f5c-4e8b-8f54-1283ba3ddfb3" />
<div align="center">
    <img alt="wiiu" height="56" src="https://github.com/user-attachments/assets/c22393cf-f619-4a1c-bc99-de68d5d903fa">
    <a href="https://go.nsmbu.net/discord">
        <img alt="discord" height="56" src="https://github.com/user-attachments/assets/f43b9deb-376a-48cd-bc09-8117cde071bb">
    </a>
    <a href="https://zenith.nsmbu.net/wiki/Pyamoto_Level_Editor">
        <img alt="docs" height="56" src="https://github.com/user-attachments/assets/f492ac70-08e4-4894-a4f8-a8a829d9e4e4">
    </a>
</div>

## Overview
Pyamoto is an advanced fork of the original Miyamoto editor with the purpose of improving functionality and usability.

## Installation
Download the latest automated release from the [releases page](https://github.com/Zenith-Team/Pyamoto/releases/latest).

**macOS** users can also install via [Homebrew](https://brew.sh/):
```sh
brew tap zenith-team/tap
brew trust zenith-team/tap
brew install pyamoto
```

## Usage
Follow the guide on the [wiki](https://zenith.nsmbu.net/wiki/Miyamoto_Level_Editor).

### New Super Mario Bros. U Deluxe
Pyamoto can edit the Switch version too. In the setup wizard (or **Preferences → Game Setup**) pick *New Super Mario Bros. U Deluxe* and select the `Course` folder from your dumped game's `romfs`; the `Unit` folder must sit right next to it, since Deluxe keeps its tilesets there. Levels are saved as plain little-endian `.sarc` files. The tileset editor does not support Deluxe yet.

## Changelog
Read the [changelog](./CHANGELOG.md) for a full list of changes and additions.

## Interested in contributing?
Dev discussions are in the `#nsmbu` channel in the [Zenith Discord](https://go.nsmbu.net/discord). 

External contributions and fixes are welcome through Pull Requests and the Issues tab. Check [Running From Source](#running-from-source) to setup a local development env.

## Running from Source

**Prerequisites:** [Python 3](https://www.python.org/downloads/) (Windows: check "Add Python to PATH" during install), Git.

```bash
git clone https://github.com/Zenith-Team/Pyamoto
cd Pyamoto
bash setup_venv.sh

# macOS/Linux
.venv/bin/python3 pyamoto.py

# or on Windows:
.venv\Scripts\python pyamoto.py
```

### Disclaimer
AI tools are used in the development of this program.
