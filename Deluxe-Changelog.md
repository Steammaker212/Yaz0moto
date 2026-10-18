# Deluxe Changelog

Everything specific to **New Super Mario Bros. U Deluxe** (Switch) support in Yaz0moto. Changes that apply to both games are in [CHANGELOG.md](./CHANGELOG.md); who made what possible is in [CREDITS.md](./CREDITS.md); setup is in [Deluxe-Setup.md](./Deluxe-Setup.md).

## v1.0.0 - First release with Deluxe support

### Added

**The game**
- *New Super Mario Bros. U Deluxe* is a selectable game in the setup wizard and **Preferences > Game Setup**, with its own game path. It shares sprites, backgrounds, tileset names, music and entrance data with the Wii U game, and has its own blank course, level list and tileset template.
- Game path validation for Deluxe: the `Course` folder must contain `1-1.sarc` and have a `Unit` folder next to it. The message says what is missing.
- Opening a level from the other game (detected from the file's byte order) offers to switch games. Switching game in Preferences starts a new level, and importing an area from a level of the other game is refused.
- The window title shows `[Deluxe]` while Deluxe is selected; the "level not found" message names `.sarc` and the `Course` folder.
- Settings from Miyamoto! DX (`isDX`) are moved into the Deluxe game slot instead of being rejected.

**Levels**
- Levels are read and written as flat, uncompressed, little-endian `.sarc` archives. Nothing is embedded in them: no tilesets, no sprite resources. The Wii U "outer SARC" option is disabled, and the Wii U 70 MB size warning does not apply.
- The Choose Level window lists level files that exist in the game folder but have no name. In the base game, `Course` has 281 levels and 180 have names, so the other 101 (worlds 40, 41 and 43-50) appear under *Uncategorized*.

**Tilesets**
- Tilesets load from `Unit/<name>.szs`: a Yaz0-compressed little-endian SARC holding `output.bfres` (the tile textures as BNTX), `BG_chk` (collision) and `BG_unt` (objects). Texture reading supports the compressed formats the game uses (code from Miyamoto! DX).
- Edited tilesets are saved back into `Unit` as `Pa<slot>_<hash>.szs` (the name is derived from the content, as on Wii U). Saving a level after editing tilesets uses the same writer, so the level and the files in `Unit` stay consistent.
- Saved textures are uncompressed 2048x512 RGBA8, for the tiles and the normal map.

**Tileset editor**
- *Edit Tilesets* opens the exact tileset files the open level uses, one tab per slot; each tab's tooltip shows the file path. Empty slots start as new blank tilesets.
- Save writes into `Unit`. The shared main tileset (`Pa0`) asks before overwriting its file, once per session. A failed write is reported and the slot keeps its previous name.
- *Export Tileset* writes a standalone `.szs` and *Import Tileset from file* reads one (Yaz0-compressed files are decompressed automatically, for both games).
- Animations are read from and written to the BNTX: `block_anime`, `block_anime_L`, `hatena_anime`, `hatena_anime_L`, `tuka_coin_anime` and `belt_conveyor_anime`.
- The tileset object index is little-endian inside tileset files; exported object files keep their shared big-endian format.

**Backgrounds**
- The zone Background tab shows the real Deluxe file name, `dv_<name>.Nin_NX_NVN.szs`, with a tooltip for the folder (`romfs/Model`). The custom-filename box uses the same suffix. All 107 backgrounds in the list exist in Deluxe.

### Fixed
- **Saving a level crashed** with `'H' format requires 0 <= number <= 65535` when a zone's parallax mode was a value the dropdown has no name for (the box was blank and read back as -1). Unlisted values are now kept and shown as "Unknown (n)".
- **Opening some levels crashed on Python 3.10 or newer** (`QPixmap` received a float size) in sprites with a float-sized image.
- The setup wizard could write a Deluxe path into the Wii U game slot, and Game Setup always picked the first game with a valid path, so Deluxe could not be chosen when both were set up.
- Changing from Deluxe to Wii U in Preferences raised an error.

## How Deluxe differs from Wii U

| | Wii U | Deluxe |
|---|---|---|
| Levels | `content/Common/course_res_pack/*.szs` (Yaz0) | `romfs/Course/*.sarc` (uncompressed) |
| Byte order | big-endian | little-endian |
| Tilesets | embedded in the level archive | separate files in `romfs/Unit` |
| Tile textures | GTX | BNTX inside a BFRES |
| Background models | `content/Common/distant_view/dv_<name>.szs` | `romfs/Model/dv_<name>.Nin_NX_NVN.szs` |
| Background `.envset` | next to the model, in `distant_view` | `romfs/DistantView/dv_<name>.envset` |

## Known limitations and things not yet verified
- The Deluxe code has been tested with generated test files and with a real Wii U tileset converted to the Deluxe format (tiles, normal maps, collision, all 156 objects and every animation came back identical). It has not been checked against a full set of vanilla Deluxe tilesets, which use compressed textures. If you find a tileset that fails to open or looks wrong, please [open an issue](https://github.com/Steammaker212/Yaz0moto/issues).
- Saved tilesets use uncompressed pixel data (compressed vanilla textures are decoded, not re-encoded), so edited tileset files can be larger than the originals.
- Boost Rush levels (`romfs/RDashRes/Course`, 130 files) cannot be opened from the level picker, because they are in a different folder from `Course`.
- Sprite data and images are shared with the Wii U game; differences specific to Deluxe have not been catalogued.
- The zone's parallax mode and X/Y/Z offsets come from New Super Mario Bros. 2, and what they do in Deluxe is unconfirmed.
- Yaz0moto only stores a background's *name* (up to 16 characters). A custom background needs its model file at `romfs/Model/dv_<name>.Nin_NX_NVN.szs`; vanilla backgrounds also have a `.envset` in `romfs/DistantView`, and whether a custom one needs it has not been tested.
- Six backgrounds (`R_Siro_Yoko`, `R_Obake_hune`, `R_Kumo_Luigi`, `R_Picture_2`, `R_Setugen`, `R_Suityu`) exist only in Deluxe. They are offered with the Wii U game too, where there is no model for them.
