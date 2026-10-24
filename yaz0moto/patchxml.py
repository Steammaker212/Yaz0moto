#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import xml.etree.ElementTree as ET


class PatchXmlEditor:
    """
    Helper for reading and writing XML files inside a userdata patch directory.
    Designed to be expanded with additional patch-XML manipulation methods.
    """

    def __init__(self, user_patch_dir):
        """user_patch_dir: absolute path to userdata/patches/<mod_folder>/"""
        self.patch_dir = user_patch_dir

    # ── Public paths ──────────────────────────────────────────────────────────

    def levelnames_path(self):
        return os.path.join(self.patch_dir, 'levelnames.xml')

    # ── Levelnames ────────────────────────────────────────────────────────────

    def set_level_info(self, level_code, level_name, world_name=None):
        """
        Set the display name for a level and optionally move it to a world (category).
        Creates levelnames.xml if it doesn't exist.  If world_name is None the level
        stays in its existing category, or falls back to 'Custom Names' for new entries.
        """
        ln_path = self.levelnames_path()

        if os.path.isfile(ln_path):
            root = ET.parse(ln_path).getroot()
        else:
            root = ET.Element('levels')

        # Detach any existing entry and remember its current category
        existing_el = None
        current_cat_name = None
        for cat in list(root):
            if cat.tag != 'category':
                continue
            for lv in list(cat):
                if lv.tag == 'level' and lv.get('file') == level_code:
                    existing_el = lv
                    current_cat_name = cat.get('name', '')
                    cat.remove(lv)
                    break
            if existing_el is not None:
                break

        # Determine target category
        target_name = world_name if world_name is not None else (current_cat_name or 'Uncategorized')
        target_cat = next(
            (c for c in root if c.tag == 'category' and c.get('name') == target_name), None)
        if target_cat is None:
            target_cat = ET.SubElement(root, 'category')
            target_cat.set('name', target_name)

        if existing_el is not None:
            existing_el.set('name', level_name)
            target_cat.append(existing_el)
        else:
            lv = ET.SubElement(target_cat, 'level')
            lv.set('file', level_code)
            lv.set('name', level_name)

        self._save(root, ln_path)

    def remove_level(self, level_code):
        """Remove a level entry from levelnames.xml entirely.
        The level will reappear as 'Uncategorized' via the filesystem scan."""
        ln_path = self.levelnames_path()
        if not os.path.isfile(ln_path):
            return
        root = ET.parse(ln_path).getroot()
        for cat in root:
            if cat.tag != 'category':
                continue
            for lv in list(cat):
                if lv.tag == 'level' and lv.get('file') == level_code:
                    cat.remove(lv)
                    self._save(root, ln_path)
                    return

    # backward-compat alias
    set_level_name = set_level_info

    def get_worlds(self):
        """Return the ordered list of category (world) names from levelnames.xml."""
        ln_path = self.levelnames_path()
        if not os.path.isfile(ln_path):
            return []
        try:
            root = ET.parse(ln_path).getroot()
            return [c.get('name', '') for c in root if c.tag == 'category']
        except Exception:
            return []

    def get_level_name(self, level_code):
        """Return the display name for level_code from levelnames.xml, or None."""
        ln_path = self.levelnames_path()
        if not os.path.isfile(ln_path):
            return None
        try:
            root = ET.parse(ln_path).getroot()
            for cat in root:
                if cat.tag == 'category':
                    for lv in cat:
                        if lv.tag == 'level' and lv.get('file') == level_code:
                            return lv.get('name', '')
        except Exception:
            pass
        return None

    def get_level_world(self, level_code):
        """Return the category name that contains level_code, or None."""
        ln_path = self.levelnames_path()
        if not os.path.isfile(ln_path):
            return None
        try:
            root = ET.parse(ln_path).getroot()
            for cat in root:
                if cat.tag == 'category':
                    for lv in cat:
                        if lv.tag == 'level' and lv.get('file') == level_code:
                            return cat.get('name', '')
        except Exception:
            pass
        return None

    def apply_world_edits(self, world_edits):
        """Rewrite world (category) names and order atomically.
        world_edits: ordered list of (original_name_or_None, new_name).
        Levels from deleted categories are removed from the XML; they remain as
        game files and will appear as 'Uncategorized' via filesystem scan.
        """
        ln_path = self.levelnames_path()

        if os.path.isfile(ln_path):
            root = ET.parse(ln_path).getroot()
        else:
            root = ET.Element('levels')

        # Detach all existing categories, keyed by original name
        orig_cats = {}
        for cat in list(root):
            if cat.tag == 'category':
                orig_cats[cat.get('name', '')] = cat
                root.remove(cat)

        edit_map = {orig: new for orig, new in world_edits if orig is not None}

        # Rebuild in new order
        for orig_name, new_name in world_edits:
            if orig_name is not None and orig_name in orig_cats:
                cat_el = orig_cats[orig_name]
                cat_el.set('name', new_name)
            else:
                cat_el = ET.Element('category')
                cat_el.set('name', new_name)
            root.append(cat_el)

        # Levels from deleted categories are moved to 'Uncategorized' (preserving names)
        orphaned = []
        for name, cat_el in orig_cats.items():
            if name not in edit_map:
                orphaned.extend(list(cat_el))
        if orphaned:
            uncat = next(
                (c for c in root if c.tag == 'category' and c.get('name') == 'Uncategorized'),
                None)
            if uncat is None:
                uncat = ET.SubElement(root, 'category')
                uncat.set('name', 'Uncategorized')
            for lv in orphaned:
                uncat.append(lv)

        self._save(root, ln_path)

    # ── Main XML (metadata) ───────────────────────────────────────────────────

    def main_xml_path(self):
        return os.path.join(self.patch_dir, 'main.xml')

    def patch_release_url(self):
        """Return patchReleaseUrl from main.xml, or None."""
        mx_path = self.main_xml_path()
        if not os.path.isfile(mx_path):
            return None
        try:
            root = ET.parse(mx_path).getroot()
            return root.attrib.get('patchReleaseUrl', None)
        except Exception:
            return None

    def set_patch_release_url(self, url):
        """Set patchReleaseUrl in main.xml."""
        mx_path = self.main_xml_path()
        if os.path.isfile(mx_path):
            tree = ET.parse(mx_path)
            root = tree.getroot()
        else:
            root = ET.Element('game')
        if url:
            root.set('patchReleaseUrl', url)
        elif 'patchReleaseUrl' in root.attrib:
            del root.attrib['patchReleaseUrl']
        self._save(root, mx_path)

    def set_metadata(self, name=None, description=None, version=None):
        """Update name, description, and/or version in this patch's main.xml."""
        mx_path = self.main_xml_path()
        if os.path.isfile(mx_path):
            tree = ET.parse(mx_path)
            root = tree.getroot()
        else:
            root = ET.Element('game')
        if name is not None:
            root.set('name', name)
        if description is not None:
            root.set('description', description)
        if version is not None:
            root.set('version', version)
        if 'version' not in root.attrib:
            root.set('version', '1.0')
        self._save(root, mx_path)

    @classmethod
    def create_mod(cls, user_patches_dir, slug, name, description='', patch_release_url=''):
        """Create a new userdata patch directory with a minimal main.xml."""
        patch_dir = os.path.join(user_patches_dir, slug)
        os.makedirs(patch_dir, exist_ok=True)
        root = ET.Element('game')
        root.set('name', name)
        root.set('version', '1.0')
        if description:
            root.set('description', description)
        if patch_release_url:
            root.set('patchReleaseUrl', patch_release_url)
        editor = cls(patch_dir)
        editor._save(root, os.path.join(patch_dir, 'main.xml'))
        return editor

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _save(self, root, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._indent(root)
        ET.ElementTree(root).write(path, xml_declaration=True, encoding='unicode')

    @staticmethod
    def _indent(elem, level=0):
        """Pretty-print indentation (in-place)."""
        pad = '\n' + '    ' * level
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = pad + '    '
            if not elem.tail or not elem.tail.strip():
                elem.tail = pad
            last = None
            for child in elem:
                PatchXmlEditor._indent(child, level + 1)
                last = child
            if last is not None and (not last.tail or not last.tail.strip()):
                last.tail = pad
        elif level and (not elem.tail or not elem.tail.strip()):
            elem.tail = pad
