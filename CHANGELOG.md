# Yaz0moto v1.0.0

Yaz0moto is a fork of Pyamoto by Steammaker212 that adds full support for New Super Mario Bros. U Deluxe (Switch).

## Features
- Added New Super Mario Bros. U Deluxe as a base game. Pick it in the setup wizard or under Preferences > Game Setup, and point it at the `Course` folder of your dumped game; the `Unit` folder must be next to it
- Deluxe levels are read and written as little-endian `.sarc` files; opening a level from the other game offers to switch games, and changing game in Preferences starts a new level
- Deluxe tilesets are loaded from `Unit` (Yaz0 SARC with BNTX textures) and saved back there when edited
- The tileset editor works with Deluxe: it opens the exact tileset files the level uses, saves them into `Unit` (the shared main tileset asks before overwriting), exports and imports standalone `.szs` tilesets, and handles the block, `?` block, coin and conveyor animations
- In Deluxe mode the zone Background tab shows the real Deluxe file name (`dv_<name>.Nin_NX_NVN.szs`, in `romfs/Model`)
- The Choose Level window also lists level files that have no name (Deluxe ships over 100 of them, worlds 40-50)
- Miyamoto! DX settings are migrated into the Deluxe game slot

## Changes
- Renamed from Pyamoto to Yaz0moto: new name, icon and executable
- Your settings, mods and downloaded data are copied from the `Pyamoto` user data folder to a new `Yaz0moto` folder on first launch (the original is left untouched)
- The built-in updater now checks this project's releases instead of Pyamoto's
- Crash reports and the About box point to this project's GitHub instead of the Zenith Discord
- Builds and releases now run from the `main` branch

## Fixes
- Fixed a crash when saving a level whose zone background has a parallax mode the dropdown doesn't list: the value is now kept and shown as "Unknown (n)"
- Fixed crashes on Python 3.10+ in sprites whose image size was a float
- Fixed the setup wizard writing a Deluxe path into the Wii U game slot, and the Game Setup tab always picking the first game with a valid path
- Fixed an error when switching from Deluxe to Wii U in Preferences

# Pyamoto v1.0 (upstream history)

## Features
- Added a welcome page
- Added Undo/Redo functionality
- Added a interactive setup wizard which reduces friction for acquiring necessary data and setting paths
- Added automated nightly builds for Windows, MacOS and Linux, and the app now notifies when a new build is available
- Added a categorized view option for sprite settings
- Added image preview in the actors list
- Implement FastYZ compression algorithm for instant saving
- You can now select multiple actors and edit their spritedata (includes an algorithm which only updates data that changes)
- Allow loading multiple patches and introduce mod manager
- Improved path nodes functionality: starts at ID 0, new nodes now inherit the previous properties, place in-between nodes, etc.
- Added the option to open levels in a new window or the same window
- Puzzle: added visual tile properties seletion, enhance objects view and mode selection, clean and improve menubar actions, update tileset canvas view with right-click actions, unsaved changes warning on close
- Improved icons for Main tileset objects
- Add improved search algorithm for the actor list
- Replaced Stamps with Clips which is a new system based on the existing MiyamotoClip format
- Added an option to place objects at their full size
- The app now uses a global userdata folder rather than the project path for preferences (survives updates) and you can open that path using `File`->`Show Pyamoto Userdata Folder`
- Zone edit UI: updated layout to fit vertically on smaller screens, added BG name preview, updated workflow for choosing custom filename
- Add a new visual window for importing downloaded objects (replaces the "all" tab)
- Open Level By Name: select levels from game or mod paths, add functionality for editing the associated world and names of levels in mods, add a shortcut for copying game levels to a mod project, add searchbar for filtering levels
- Added new setting types: dualbox, strybble
- Added an option to show a notes box in the actor properties window
- Added the ability to make spritedata options conditional on another value
- Patches may now provide their own `data` folder which can be referenced to bundle custom assets in a level archive
- Added a new "Dark Red" default theme
- Added the ability to use the "Outer SARC Format" when saving levels to preserve compatibility with legacy editors
- Allow pressing `esc` to deselect objects
- Added "set to layer" shortcut button in palette tileset objects tab
- Add menu bar option for duplicating objects in the level

## Fixes
- Community spritedata and image fixes (ongoing)
- Pasting is now centered on cursor position
- Allowed moving large sprites near the edge of the screen, which previously was restricted by boundaries
- No longer deselects objects when using middle-click to pan
- Displays an error if loading a patch failed instead of silently failing
- Updated unclear strings and notes
- Fix crashes on newer Python versions
- Don't display nonexistent sprites when there is a gap in IDs
- Improved performance on Wayland Linux environments
- Actor properties window shrinks to fit when switching actors
- Fixed SIGINT when running the app through CLI 
- Refactored old .txt data files into standardized .xml which can be edited by patches
- Fixed level overview dragging on MacOS and Linux
- Remove old quick paint system
- Removed outdated "help" pages
- Removed old incomplete translation feature
