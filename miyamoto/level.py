#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Pyamoto Level Editor
# Copyright (C) 2009-2026 Pyamoto contributors
# This file is part of Pyamoto.

# See LICENSE.txt for more information.


################################################################
################################################################

############ Imports ############

import os
from . import misc
from xml.etree import ElementTree as etree

from . import globals
from .bytes import bytes_to_string
import SarcLib
from . import spritelib as SLib
from .tileset import CreateTilesets, SaveTileset
from .id_manager import SpriteIDManager, get_course_sprite_types, remap_course_sprite_types

#################################


class AbstractLevel:
    """
    Class for an abstract level from any game. Defines the API.
    """

    def __init__(self):
        """
        Initializes the level with default settings
        """
        self.filepath = None
        self.name = 'untitled'

        self.areas = []

    def load(self, data, areaNum, progress=None):
        """
        Loads a level from bytes data. You MUST reimplement this in subclasses!
        """
        pass

    def save(self):
        """
        Returns the level as a bytes object. You MUST reimplement this in subclasses!
        """
        return b''

    def deleteArea(self, number):
        """
        Removes the area specified. Number is a 1-based value, not 0-based;
        so you would pass a 1 if you wanted to delete the first area.
        """
        del self.areas[number - 1]
        return True


class Level_NSMBU(AbstractLevel):
    """
    Class for a level from New Super Mario Bros. U
    """

    def __init__(self):
        """
        Initializes the level with default settings
        """
        super().__init__()
        CreateTilesets()
        self.id_manager = SpriteIDManager()
        self.spritemap_load_error = None

        from . import area
        self.areas.append(area.Area_NSMBU())
        globals.Area = self.areas[0]

    @staticmethod
    def _sarcEndianness():
        """
        Byte order of the level archive: Switch (Deluxe) levels are little-endian. Retail
        Deluxe levels use a big-endian SARC header, but the game reads either.
        """
        return '<' if globals.IsNSMBUDX else '>'

    @staticmethod
    def _usesOuterSarc(innerfilename):
        """
        Whether to wrap the level in an outer SARC with a "levelname" file.
        That is a Wii U-era convention; Deluxe levels are always a flat archive.
        """
        return bool(globals.UseOuterSarcFormat and innerfilename and not globals.IsNSMBUDX)

    def new(self):
        """
        Creates a completely new level
        """
        self.id_manager.clear_runtime_bindings()
        self.id_manager.reset()
        self.spritemap_load_error = None

        # Create area objects
        self.areas = []
        from . import area
        newarea = area.Area_NSMBU()
        globals.Area = newarea
        SLib.Area = globals.Area
        self.areas.append(newarea)

    def load(self, data, areaNum, progress=None):
        """
        Loads a NSMBU level from bytes data.
        """
        super().load(data, areaNum, progress)

        arc = SarcLib.SARC_Archive()
        arc.load(data)

        try:
            courseFolder = arc['course']
        except:
            return False

        # Load the level-local named actor map before constructing SpriteItems.
        # spritemap entry i is exactly map actor 0xF000+i; do not migrate or
        # reallocate it according to actor traversal order.
        self.id_manager.clear_runtime_bindings()
        self.id_manager.reset()
        self.spritemap_load_error = None
        try:
            spritemap_data = arc['course/spritemap.bin'].data
        except KeyError:
            spritemap_data = None

        if spritemap_data is not None:
            try:
                self.id_manager.load_from_binary(spritemap_data)
            except ValueError as e:
                self.id_manager.reset()
                self.spritemap_load_error = str(e)
                print(f"Warning: Could not load spritemap.bin. Reason: {e}")

        # Sort the area data
        areaData = {}
        areaMusicTxt = {}
        for file in courseFolder.contents:
            name, val = file.name, file.data

            if val is None: continue

            if not name.startswith('course'): continue
            if not name.endswith('.bin'):
                # Custom music track name extension: course{N}.{Y}.music.txt,
                # where N = 1-based area number and Y = 0-based zone index
                if name.endswith('.music.txt'):
                    stem = name[:-len('.music.txt')]
                    parts = stem[len('course'):].split('.')
                    if len(parts) == 2:
                        try:
                            thisArea, zoneIdx = int(parts[0]), int(parts[1])
                        except ValueError:
                            thisArea = zoneIdx = None
                        if thisArea is not None and 0 < thisArea < 5 and zoneIdx >= 0:
                            if thisArea not in areaMusicTxt: areaMusicTxt[thisArea] = {}
                            areaMusicTxt[thisArea][zoneIdx] = val
                continue
            if '_bgdatL' in name:
                # It's a layer file
                if len(name) != 19: continue
                try:
                    thisArea = int(name[6])
                    laynum = int(name[14])
                except ValueError:
                    continue
                if not (0 < thisArea < 5): continue

                if thisArea not in areaData: areaData[thisArea] = [None] * 4
                areaData[thisArea][laynum + 1] = val
            else:
                # It's the course file
                if len(name) != 11: continue
                try:
                    thisArea = int(name[6])
                except ValueError:
                    continue
                if not (0 < thisArea < 5): continue

                if thisArea not in areaData: areaData[thisArea] = [None] * 4
                areaData[thisArea][0] = val

        # Create area objects
        self.areas = []
        thisArea = 1
        while thisArea in areaData:
            course = areaData[thisArea][0]
            L0 = areaData[thisArea][1]
            L1 = areaData[thisArea][2]
            L2 = areaData[thisArea][3]

            # Decode the custom music track names, if present (null-terminated)
            musicTxt = {}
            for zoneIdx, txt in areaMusicTxt.get(thisArea, {}).items():
                if txt:
                    musicTxt[zoneIdx] = bytes_to_string(txt)

            from . import area
            if thisArea == areaNum:
                newarea = area.Area_NSMBU()
                globals.Area = newarea
                SLib.Area = globals.Area
            else:
                newarea = area.AbstractArea()

            newarea.areanum = thisArea
            newarea.load(course, L0, L1, L2, progress, musicTxt=musicTxt)
            self.areas.append(newarea)

            thisArea += 1
        
        return True

    def _buildSpritemapSaveProjection(self, extra_courses=()):
        """Build the one compact named-actor mapping used by every save output."""
        if self.spritemap_load_error:
            raise ValueError(
                "Cannot safely save because spritemap.bin failed to load: "
                + self.spritemap_load_error
            )

        used_types = []
        for area in self.areas:
            used_types.extend(sprite.type for sprite in area.sprites)

        for course in extra_courses:
            if course is not None:
                used_types.extend(get_course_sprite_types(course))

        return self.id_manager.build_save_projection(used_types)

    def save(self, innerfilename=None, saveTilesets=True):
        """
        Save the level back to a file. saveTilesets=False leaves edited tilesets alone
        (autosave uses it: for Deluxe, saving a tileset writes into the game's Unit folder).
        """

        # Save all the tilesets before anything
        if saveTilesets and (globals.TilesetEdited or misc.setting('OverrideTilesetSaving', False)):
            if globals.Area.tileset1:
                tilesetData = SaveTileset(1)
                if tilesetData:
                    globals.szsData[globals.Area.tileset1] = tilesetData

            if globals.Area.tileset2:
                tilesetData = SaveTileset(2)
                if tilesetData:
                    globals.szsData[globals.Area.tileset2] = tilesetData

            if globals.Area.tileset3:
                tilesetData = SaveTileset(3)
                if tilesetData:
                    globals.szsData[globals.Area.tileset3] = tilesetData

        spritemap_strings, sprite_type_remap = self._buildSpritemapSaveProjection()

        # Make a new archive
        newArchive = SarcLib.SARC_Archive(endianness=self._sarcEndianness())

        # Create a folder within the archive
        courseFolder = SarcLib.Folder('course')
        newArchive.addFolder(courseFolder)

        # Go through the areas, save them and add them back to the archive
        for areanum, area in enumerate(self.areas):
            course, L0, L1, L2 = area.save(sprite_type_remap=sprite_type_remap)

            if course is not None:
                courseFolder.addFile(SarcLib.File('course%d.bin' % (areanum + 1), course))
            if L0 is not None:
                courseFolder.addFile(SarcLib.File('course%d_bgdatL0.bin' % (areanum + 1), L0))
            if L1 is not None:
                courseFolder.addFile(SarcLib.File('course%d_bgdatL1.bin' % (areanum + 1), L1))
            if L2 is not None:
                courseFolder.addFile(SarcLib.File('course%d_bgdatL2.bin' % (areanum + 1), L2))

            # Emit per-zone custom music track names, if any. Derived from
            # live state, so zones switched back to numeric IDs simply stop
            # emitting their file (no stale entries).
            for zoneIdx, musicData in sorted(area.getCustomMusicData().items()):
                courseFolder.addFile(SarcLib.File('course%d.%d.music.txt' % (areanum + 1, zoneIdx), musicData))

        # The projection is compact GC: only placed named actors are emitted,
        # and every course above was serialized through this exact same map.
        spritemap_data = self.id_manager.get_save_data_binary(spritemap_strings)
        if spritemap_data:
            newArchive.addFile(SarcLib.File('course/spritemap.bin', spritemap_data))

        # Outer SARC format (Miyamoto-style wrapping)
        if self._usesOuterSarc(innerfilename):
            innersarc = newArchive.save()[0]
            globals.szsData[innerfilename] = innersarc

            outerArchive = SarcLib.SARC_Archive(endianness=self._sarcEndianness())
            outerArchive.addFile(SarcLib.File(innerfilename, innersarc))
            outerArchive.addFile(SarcLib.File('levelname', innerfilename.encode('utf-8')))
            globals.szsData['levelname'] = innerfilename.encode('utf-8')

            self._add_files_to_archive(outerArchive, (innerfilename, 'levelname'))

            return outerArchive.save()[0]

        # Default flat format: add sprites/tilesets to the same archive.
        # Deluxe levels only contain course data: the game loads sprite resources
        # and tilesets from its own Model/Unit folders.
        if not globals.IsNSMBUDX:
            self._add_files_to_archive(newArchive)

        return newArchive.save()[0]

    def saveNewArea(self, course_new, L0_new, L1_new, L2_new, innerfilename=None):
        """
        Save the level back to a file (when adding a new or deleting an existing Area)
        """

        spritemap_strings, sprite_type_remap = self._buildSpritemapSaveProjection(
            (course_new,) if course_new is not None else ()
        )

        # Make a new archive (inner SARC)
        newArchive = SarcLib.SARC_Archive(endianness=self._sarcEndianness())

        # Create a folder within the archive
        courseFolder = SarcLib.Folder('course')
        newArchive.addFolder(courseFolder)

        # Go through the areas, save them and add them back to the archive
        for areanum, area in enumerate(self.areas):
            course, L0, L1, L2 = area.save(True, sprite_type_remap=sprite_type_remap)

            if course is not None:
                courseFolder.addFile(SarcLib.File('course%d.bin' % (areanum + 1), course))
            if L0 is not None:
                courseFolder.addFile(SarcLib.File('course%d_bgdatL0.bin' % (areanum + 1), L0))
            if L1 is not None:
                courseFolder.addFile(SarcLib.File('course%d_bgdatL1.bin' % (areanum + 1), L1))
            if L2 is not None:
                courseFolder.addFile(SarcLib.File('course%d_bgdatL2.bin' % (areanum + 1), L2))

            for zoneIdx, musicData in sorted(area.getCustomMusicData().items()):
                courseFolder.addFile(SarcLib.File('course%d.%d.music.txt' % (areanum + 1, zoneIdx), musicData))

        if course_new is not None:
            course_new = remap_course_sprite_types(course_new, sprite_type_remap)
            courseFolder.addFile(SarcLib.File('course%d.bin' % (len(self.areas) + 1), course_new))
        if L0_new is not None:
            courseFolder.addFile(SarcLib.File('course%d_bgdatL0.bin' % (len(self.areas) + 1), L0_new))
        if L1_new is not None:
            courseFolder.addFile(SarcLib.File('course%d_bgdatL1.bin' % (len(self.areas) + 1), L1_new))
        if L2_new is not None:
            courseFolder.addFile(SarcLib.File('course%d_bgdatL2.bin' % (len(self.areas) + 1), L2_new))

        # Save the same compact mapping used to serialize every area above.
        spritemap_data = self.id_manager.get_save_data_binary(spritemap_strings)
        if spritemap_data:
            newArchive.addFile(SarcLib.File('course/spritemap.bin', spritemap_data))

        # Outer SARC format (Miyamoto-style wrapping)
        if self._usesOuterSarc(innerfilename):
            innersarc = newArchive.save()[0]
            globals.szsData[innerfilename] = innersarc

            outerArchive = SarcLib.SARC_Archive(endianness=self._sarcEndianness())
            outerArchive.addFile(SarcLib.File(innerfilename, innersarc))
            outerArchive.addFile(SarcLib.File('levelname', innerfilename.encode('utf-8')))
            globals.szsData['levelname'] = innerfilename.encode('utf-8')

            for szsThingName in globals.szsData:
                if szsThingName in (innerfilename, 'levelname'):
                    continue
                outerArchive.addFile(SarcLib.File(szsThingName, globals.szsData[szsThingName]))

            return outerArchive.save()[0]

        # Default flat format (Deluxe levels carry no embedded resources)
        if not globals.IsNSMBUDX:
            for szsThingName in globals.szsData:
                newArchive.addFile(SarcLib.File(szsThingName, globals.szsData[szsThingName]))

        return newArchive.save()[0]

    def _add_files_to_archive(self, archive, skip=None):
        """Resolve sprite and tileset files and add them to *archive*.

        When *skip* is given, any key in that iterable is omitted from the
        fallback copy (used for the outer-SARC format where the inner SARC
        and levelname live directly in *archive* already).
        """
        skip = skip or ()

        if os.path.isdir(globals.actor_data_path):
            szsNewData = {}

            paths = globals.gamedef.recursiveFiles('spriteresources')

            sprites_xml = {}
            for path in paths:
                # Read the sprites resources xml
                tree = etree.parse(path)
                root = tree.getroot()

                # Get all sprites' filenames and add them to a list
                for sprite in root.iter('sprite'):
                    id = int(sprite.get('id'))

                    name = []
                    for id2 in sprite:
                        name.append(id2.get('name'))

                    sprites_xml[id] = list(name)

            # Look up every sprite and tileset used in each area
            sprites_SARC = []
            tilesets_names = []
            for area_SARC in globals.Level.areas:
                for sprite in area_SARC.sprites:
                    sprites_SARC.append(sprite.type)

                if area_SARC.tileset0 not in ('', None):
                    tilesets_names.append(area_SARC.tileset0)

                if area_SARC.tileset1 not in ('', None):
                    tilesets_names.append(area_SARC.tileset1)

                if area_SARC.tileset2 not in ('', None):
                    tilesets_names.append(area_SARC.tileset2)

                if area_SARC.tileset3 not in ('', None):
                    tilesets_names.append(area_SARC.tileset3)

            sprites_SARC = list(set(sprites_SARC))
            tilesets_names = list(set(tilesets_names))

            # Sort the filenames for each "used" sprite
            sprites_names = []
            for sprite in sprites_SARC:
                if sprite in sprites_xml:
                    for sprite_name in sprites_xml[sprite]:
                        sprites_names.append(sprite_name)

            sprites_names = list(set(sprites_names))

            # Resolve patch data folders for sprite resource lookup
            data_folders = globals.gamedef.recursiveFiles('data', False, True) if globals.gamedef else []

            # Look up each needed file and add it to our archive
            for sprite_name in sprites_names:
                # Get it from inside the original archive
                if not globals.OverwriteSprite and sprite_name in globals.szsData:
                    archive.addFile(SarcLib.File(sprite_name, globals.szsData[sprite_name]))
                    szsNewData[sprite_name] = globals.szsData[sprite_name]

                # Get it from patch data folders (most specific first)
                elif any(os.path.isfile(os.path.join(f, sprite_name)) for f in reversed(data_folders)):
                    for folder in reversed(data_folders):
                        fpath = os.path.join(folder, sprite_name)
                        if os.path.isfile(fpath):
                            with open(fpath, 'rb') as f:
                                f1 = f.read()
                            archive.addFile(SarcLib.File(sprite_name, f1))
                            szsNewData[sprite_name] = f1
                            break

                # Get it from the "custom" data folder
                elif os.path.isfile(os.path.join(globals.actor_data_path, 'custom', sprite_name)):
                    with open(os.path.join(globals.actor_data_path, 'custom', sprite_name), 'rb') as f:
                        f1 = f.read()

                    archive.addFile(SarcLib.File(sprite_name, f1))
                    szsNewData[sprite_name] = f1

                # Get it from the data folder
                elif os.path.isfile(os.path.join(globals.actor_data_path, sprite_name)):
                    with open(os.path.join(globals.actor_data_path, sprite_name), 'rb') as f:
                        f1 = f.read()

                    archive.addFile(SarcLib.File(sprite_name, f1))
                    szsNewData[sprite_name] = f1

                # Throw a warning because the file was not found...
                else:
                    print("WARNING: Could not find the file: %s" % sprite_name)
                    print("Expect the level to crash ingame...")

            # Add each tileset to our archive
            for tileset_name in tilesets_names:
                if tileset_name in globals.szsData:
                    archive.addFile(SarcLib.File(tileset_name, globals.szsData[tileset_name]))
                    szsNewData[tileset_name] = globals.szsData[tileset_name]

            # Add the other default Pa0 tilesets to our new dict
            for def_tileset in globals.Pa0Tilesets:
                if def_tileset not in szsNewData and def_tileset in globals.szsData:
                    szsNewData[def_tileset] = globals.szsData[def_tileset]

            globals.szsData = szsNewData

        else:
            for szsThingName in globals.szsData:
                if szsThingName in skip:
                    continue
                archive.addFile(SarcLib.File(szsThingName, globals.szsData[szsThingName]))
