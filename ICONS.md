# Y0MI icon names for Yaz0moto

Put the PNGs in your patch's icons folder: `patches/<patch name>/icons/`.

**Set/Modify Custom Icon...** in the properties panel of a selected actor does this for you: pick the patch, the image, the size and the position, and Save writes the PNG there with the right name. It replaces the icon that patch already has for this actor and raw data, even if the new size or position changes the name. The button is greyed out if no mod is enabled, and for actors with an ID over 4095.

## The name

```
Y0MI_XXXXXX.png
Y0MI_XXXXXX_<raw data>.png
```

- The prefix can be `Y0MI_` (zero) or `YOMI_` (letter O), in upper or lower case.
- `XXXXXX` is exactly **6 hex digits**. They say how big the icon is, where it goes and which actor it's for.
- `<raw data>` is optional. Copy it from **Info...** in the actor's right-click menu, e.g. `0000-0000-0000-1000-0003-0000`. A `0` in it matches any digit (see below).
- Files that don't start with `Y0MI_` or `YOMI_` use the old naming (`<id>.png`, `<id>_<raw data>.png`).

## The 6 digits

Written in binary, the 6 digits are 24 bits:

```
WWWW HHHH   A B C D EEEE   EEEE EEEE
 digit1 digit2   digit3 digit4  digit5 digit6
```

| Bits | Meaning |
|---|---|
| `WWWW` (digit 1) | Width in tiles, minus 1 (`0` = 1 tile … `F` = 16 tiles) |
| `HHHH` (digit 2) | Height in tiles, minus 1 (`0` = 1 tile … `F` = 16 tiles) |
| `A` | 1 = draw **upward** from the actor's tile, 0 = downward |
| `B` | 1 = draw to the **right** of the actor's tile, 0 = to the left |
| `C` | 1 = **centre vertically** on the actor's tile (ignores A) |
| `D` | 1 = **centre horizontally** on the actor's tile (ignores B) |
| `EEEE EEEE EEEE` (digits 4–6) | Actor ID **in hex** (000–FFF) |

Digit 3 is the four flags `ABCD` read as one hex digit:

| Digit 3 | Flags set |
|---|---|
| `0` | none (down + left) |
| `1` | D |
| `2` | C |
| `3` | C + D (centred both ways) |
| `4` | B |
| `5` | B + D |
| `6` | B + C |
| `7` | B + C + D |
| `8` | A |
| `9` | A + D |
| `A` | A + C |
| `B` | A + C + D |
| `C` | A + B (up + right) |
| `D` | A + B + D |
| `E` | A + B + C |
| `F` | A + B + C + D |

**Watch out:** the actor ID here is in **hex**, but Yaz0moto and the old names show it in decimal. Actor 91 is `05B`, and actor 300 is `12C`.

## Examples

**Actor 91, 2 tiles wide × 3 tall, drawn upward, centred horizontally:**
- Width 2 → `1`, height 3 → `2`
- Flags A + D → `9`
- ID 91 = `05B`
- → `Y0MI_12905B.png`

**Actor 300, 1×1, centred both ways:**
- `0`, `0`, flags C + D = `3`, ID `12C`
- → `Y0MI_00312C.png`

**The same 1×1 icon, but only when the actor has specific settings:**
- → `Y0MI_00312C_0000-0000-0000-1000-0003-0000.png`

## How it behaves

- **Size:** the image is **stretched** to the size in the name, so its own pixel size and shape don't matter.
- **Centring:** an even size is centred with half tiles. For example, a 2-wide icon sticks out half a tile on each side.
- **Zeroes in the raw data:** in a `Y0MI_` name, each `0` digit of the raw data matches any digit, and the other digits must be the same as the actor's. So `0000-0000-0000-1000-0000-0000` is used for `0000-0000-0000-1000-0007-0000`, and for anything else with that `1`. Old-style names must match exactly.
- **Which icon wins:**
  1. A name with raw data wins over one without, when the actor's settings match.
  2. Among names with raw data, the one with the same data wins, then the `Y0MI_` one with the most non-zero digits. If that's a tie, the most specific patch wins, then the lowest raw data.
  3. For the same actor, a `Y0MI_` icon wins over an old-style one.
- **Raw data that is all zeroes:** it matches every setting of the actor, as the last choice among names with raw data.
- **Actors with their own sprite image:** only an icon **with raw data** replaces the image, and only for the settings it matches. An icon without raw data replaces only the plain ID box of actors that have no image.
- **Palette:** the Add Actors palette also uses the icon for actors with no image. There it's shrunk to fit and keeps its shape.
