# Sprite ID Manager for dynamic string<->integer ID mapping
# Handles the allocation of integer IDs for custom sprites identified by strings

from . import globals
import struct

SpritemapVersion = 2

CUSTOM_ID_BASE = 0xF000
INVALID_MAP_ACTOR = 0xFFFF
MAX_CUSTOM_ENTRIES = INVALID_MAP_ACTOR - CUSTOM_ID_BASE

_COURSE_BLOCK_COUNT = 15
_COURSE_HEADER_SIZE = _COURSE_BLOCK_COUNT * 8
_SPRITE_BLOCK_INDEX = 7
_LOADED_SPRITE_BLOCK_INDEX = 8
_SPRITE_RECORD_SIZE = 24


def _course_endian():
    return '<' if globals.IsNSMBUDX else '>'


def _course_blocks(course):
    """Return (endian, metadata, blocks) for a raw course file."""
    if course is None or len(course) < _COURSE_HEADER_SIZE:
        raise ValueError("Course data is too short")

    endian = _course_endian()
    block_struct = struct.Struct(endian + 'II')
    blocks = []
    first_data_offset = len(course)

    for i in range(_COURSE_BLOCK_COUNT):
        offset, size = block_struct.unpack_from(course, i * block_struct.size)

        if size == 0:
            blocks.append(b'')
            continue

        if offset < _COURSE_HEADER_SIZE or offset + size > len(course):
            raise ValueError(
                f"Course block {i + 1} is out of bounds "
                f"(offset=0x{offset:X}, size=0x{size:X})"
            )

        first_data_offset = min(first_data_offset, offset)
        blocks.append(bytes(course[offset:offset + size]))

    if first_data_offset == len(course):
        first_data_offset = _COURSE_HEADER_SIZE

    if first_data_offset < _COURSE_HEADER_SIZE:
        raise ValueError("Course metadata overlaps the block table")

    metadata = bytes(course[_COURSE_HEADER_SIZE:first_data_offset])
    return endian, metadata, blocks


def _rebuild_course(endian, metadata, blocks):
    block_struct = struct.Struct(endian + 'II')
    file_offset = _COURSE_HEADER_SIZE + len(metadata)
    total_size = file_offset + sum(len(block) for block in blocks)
    result = bytearray(total_size)

    result[_COURSE_HEADER_SIZE:file_offset] = metadata

    header_offset = 0
    for block in blocks:
        block_struct.pack_into(result, header_offset, file_offset, len(block))
        if block:
            result[file_offset:file_offset + len(block)] = block
        header_offset += block_struct.size
        file_offset += len(block)

    return bytes(result)


def get_course_sprite_types(course):
    """Read the actor type field from every block-8 sprite in *course*."""
    endian, _metadata, blocks = _course_blocks(course)
    sprite_block = blocks[_SPRITE_BLOCK_INDEX]
    type_struct = struct.Struct(endian + 'H')

    # Block 8 normally ends in a four-byte 0xFFFFFFFF terminator. Integer
    # division intentionally ignores that trailing partial record.
    return [
        type_struct.unpack_from(sprite_block, offset)[0]
        for offset in range(0, len(sprite_block) - (_SPRITE_RECORD_SIZE - 1), _SPRITE_RECORD_SIZE)
    ]


def remap_course_sprite_types(course, type_remap):
    """
    Rewrite block-8 actor IDs in a raw course and regenerate block 9 from the
    rewritten actor set. Other blocks and the metadata payload are preserved.
    """
    if not course:
        return course

    type_remap = type_remap or {}
    endian, metadata, blocks = _course_blocks(course)
    sprite_block = bytearray(blocks[_SPRITE_BLOCK_INDEX])
    type_struct = struct.Struct(endian + 'H')

    changed = False
    remapped_types = []

    for offset in range(0, len(sprite_block) - (_SPRITE_RECORD_SIZE - 1), _SPRITE_RECORD_SIZE):
        old_type = type_struct.unpack_from(sprite_block, offset)[0]
        new_type = type_remap.get(old_type, old_type)
        remapped_types.append(new_type)

        if new_type != old_type:
            type_struct.pack_into(sprite_block, offset, new_type)
            changed = True

    blocks[_SPRITE_BLOCK_INDEX] = bytes(sprite_block)

    loaded_struct = struct.Struct(endian + 'Hxx')
    loaded_types = sorted(set(remapped_types))
    loaded_block = bytearray(len(loaded_types) * loaded_struct.size)
    for i, actor_type in enumerate(loaded_types):
        loaded_struct.pack_into(loaded_block, i * loaded_struct.size, actor_type)

    desired_loaded_block = bytes(loaded_block)
    if desired_loaded_block != blocks[_LOADED_SPRITE_BLOCK_INDEX]:
        blocks[_LOADED_SPRITE_BLOCK_INDEX] = desired_loaded_block
        changed = True

    if not changed:
        return course

    return _rebuild_course(endian, metadata, blocks)


class SpriteIDManager:
    def __init__(self):
        self.reset()

    def reset(self):
        self.string_to_int = {}
        self.int_to_string = {}
        self.next_free_id = CUSTOM_ID_BASE

    @staticmethod
    def clear_runtime_bindings():
        """Drop level-local Fxxx aliases left in globals.Sprites by a prior level."""
        sprites = getattr(globals, 'Sprites', None)
        if not isinstance(sprites, list):
            return

        base_count = getattr(globals, 'NumSprites', len(sprites))
        if len(sprites) > base_count:
            del sprites[base_count:]

    @staticmethod
    def parse_binary(data: bytes):
        """Decode spritemap.bin to its ordered string table."""
        if data is None:
            return []
        if len(data) == 0:
            raise ValueError("spritemap.bin is empty")

        if len(data) < 8:
            raise ValueError("Data too short for spritemap header")

        version, count = struct.unpack_from('>II', data, 0)
        if version != SpritemapVersion:
            raise ValueError(
                f"Spritemap version mismatch: got {version}, "
                f"expected {SpritemapVersion}"
            )

        if count > MAX_CUSTOM_ENTRIES:
            raise ValueError(
                f"Spritemap has {count} entries; maximum is {MAX_CUSTOM_ENTRIES}"
            )

        table_end = 8 + (count * 4)
        if table_end > len(data):
            raise ValueError("Spritemap offset table is truncated")

        strings = []
        for i in range(count):
            str_offset, = struct.unpack_from('>I', data, 8 + (i * 4))

            if str_offset < table_end or str_offset >= len(data):
                raise ValueError(
                    f"Spritemap entry {i} has invalid string offset 0x{str_offset:X}"
                )

            null_index = data.find(b'\x00', str_offset)
            if null_index == -1:
                raise ValueError(f"Spritemap entry {i} is missing its null terminator")

            try:
                string_id = data[str_offset:null_index].decode('utf-8')
            except UnicodeDecodeError as e:
                raise ValueError(f"Spritemap entry {i} is not valid UTF-8") from e

            if not string_id:
                raise ValueError(f"Spritemap entry {i} has an empty identifier")

            strings.append(string_id)

        return strings

    def _bind_definition(self, int_id, str_id):
        sprites = getattr(globals, 'Sprites', None)
        definitions = getattr(globals, 'CustomSpriteDefinitions', None)
        if not isinstance(sprites, list) or not isinstance(definitions, dict):
            return

        definition = definitions.get(str_id)
        if definition is None:
            return

        while len(sprites) <= int_id:  # Existing editor API indexes definitions by numeric type.
            sprites.append(None)
        sprites[int_id] = definition

    def load_from_binary(self, data: bytes):
        """
        Load the file positionally. Entry i is exactly map actor F000+i, matching
        MapActorMgr::mapToProf(); no migration or reallocation is performed.
        """
        strings = self.parse_binary(data)
        self.reset()

        for index, string_id in enumerate(strings):
            int_id = CUSTOM_ID_BASE + index
            self.int_to_string[int_id] = string_id
            # Duplicate strings are malformed but representable by the runtime.
            # New placements use the first occurrence; existing numeric aliases
            # remain recoverable through int_to_string and are deduplicated on save.
            self.string_to_int.setdefault(string_id, int_id)
            self._bind_definition(int_id, string_id)

        self.next_free_id = CUSTOM_ID_BASE + len(strings)

    @staticmethod
    def get_save_data_binary(ordered_strings) -> bytes:
        """Serialize an already-compacted ordered string table."""
        ordered_strings = list(ordered_strings)
        if not ordered_strings:
            return b""

        if len(ordered_strings) > MAX_CUSTOM_ENTRIES:
            raise ValueError(
                f"Spritemap has {len(ordered_strings)} entries; "
                f"maximum is {MAX_CUSTOM_ENTRIES}"
            )

        offset_table_bytes = bytearray()
        string_pool_bytes = bytearray()
        current_offset = 8 + (len(ordered_strings) * 4)

        for name in ordered_strings:
            if not isinstance(name, str) or not name or '\x00' in name:
                raise ValueError(
                    "Spritemap identifiers must be non-empty strings without NUL bytes"
                )

            offset_table_bytes.extend(struct.pack('>I', current_offset))
            encoded_str = name.encode('utf-8') + b'\x00'
            string_pool_bytes.extend(encoded_str)
            current_offset += len(encoded_str)

        return (
            struct.pack('>II', SpritemapVersion, len(ordered_strings))
            + bytes(offset_table_bytes)
            + bytes(string_pool_bytes)
        )

    def get_id_for_string(self, str_id: str) -> int:
        if str_id in self.string_to_int:
            return self.string_to_int[str_id]

        if not isinstance(str_id, str) or not str_id or '\x00' in str_id:
            raise ValueError(
                "String actor ID must be a non-empty string without NUL bytes"
            )

        if self.next_free_id >= INVALID_MAP_ACTOR:
            raise ValueError("No named map actor IDs remain")

        new_id = self.next_free_id
        self.next_free_id += 1

        self.string_to_int[str_id] = new_id
        self.int_to_string[new_id] = str_id
        self._bind_definition(new_id, str_id)
        return new_id

    def get_string_for_id(self, int_id: int) -> str:
        # The level's persisted mapping is authoritative even when the active
        # patch stack cannot currently provide a definition for the string.
        return self.int_to_string.get(int_id, "")

    def build_save_projection(self, used_types):
        """
        Build a compact, deterministic on-disk mapping without mutating the live
        editor mapping. Returns (ordered_strings, live_type_to_save_type).
        """
        used_strings = set()

        for actor_type in used_types:
            actor_type = int(actor_type)
            if actor_type < CUSTOM_ID_BASE:
                continue

            if actor_type == INVALID_MAP_ACTOR:
                raise ValueError("Placed actor has invalid map actor ID 0xFFFF")

            string_id = self.int_to_string.get(actor_type)
            if string_id is None:
                raise ValueError(
                    f"Placed named actor 0x{actor_type:04X} has no spritemap "
                    "string identity; refusing to save a corrupt level"
                )

            used_strings.add(string_id)

        ordered_strings = []
        seen = set()
        for int_id in sorted(self.int_to_string):
            string_id = self.int_to_string[int_id]
            if string_id in used_strings and string_id not in seen:
                ordered_strings.append(string_id)
                seen.add(string_id)

        if len(ordered_strings) != len(used_strings):
            missing = sorted(used_strings.difference(seen))
            raise ValueError(
                "Could not resolve all placed named actors: " + ', '.join(missing)
            )

        if len(ordered_strings) > MAX_CUSTOM_ENTRIES:
            raise ValueError(
                f"Level uses {len(ordered_strings)} named actors; "
                f"maximum is {MAX_CUSTOM_ENTRIES}"
            )

        save_id_for_string = {
            string_id: CUSTOM_ID_BASE + index
            for index, string_id in enumerate(ordered_strings)
        }

        type_remap = {
            int_id: save_id_for_string[string_id]
            for int_id, string_id in self.int_to_string.items()
            if string_id in save_id_for_string
        }

        return ordered_strings, type_remap


def remap_imported_course(course, source_spritemap_data, destination_manager):
    """
    Translate a foreign course's level-local Fxxx IDs through its spritemap
    strings into destination-manager live aliases.
    """
    source_types = get_course_sprite_types(course)
    named_types = sorted({
        actor_type for actor_type in source_types
        if actor_type >= CUSTOM_ID_BASE
    })

    if not named_types:
        return course

    if not source_spritemap_data:
        raise ValueError(
            "The imported area contains named actors but its level has no spritemap.bin"
        )

    source_strings = SpriteIDManager.parse_binary(source_spritemap_data)
    type_remap = {}

    for source_type in named_types:
        if source_type == INVALID_MAP_ACTOR:
            raise ValueError("The imported area contains invalid map actor ID 0xFFFF")

        index = source_type - CUSTOM_ID_BASE
        if index >= len(source_strings):
            raise ValueError(
                f"Imported actor 0x{source_type:04X} refers to missing "
                f"spritemap entry {index}"
            )

        string_id = source_strings[index]
        type_remap[source_type] = destination_manager.get_id_for_string(string_id)

    return remap_course_sprite_types(course, type_remap)
