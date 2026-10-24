from PyQt5 import QtCore, QtWidgets
from . import globals
from .verifications import SetDirty

class Command:
    """Base class for all undoable commands."""
    def __init__(self, description=""):
        self.description = description

    def undo(self):
        raise NotImplementedError

    def redo(self):
        raise NotImplementedError

    def _is_initial_push(self):
        """True when called from UndoManager.push(), False during undo/redo."""
        return getattr(globals.UndoManager, '_in_initial_push', False)

    @staticmethod
    def _set_item_pos(item, x, y):
        """Helper to set item position correctly across different item types."""
        globals.OverrideSnapping = True

        if hasattr(item, 'setNewObjPos'):
            item.setNewObjPos(x, y)
        else:
            item.objx, item.objy = x, y
            # ObjectItem/LocationItem use different scaling
            from .items import ObjectItem, LocationItem
            if isinstance(item, ObjectItem):
                item.setPos(x * globals.TileWidth, y * globals.TileWidth)
            else:
                # LocationItem/SpriteItem-like (locations/paths use pixel-based objx/objy)
                item.setPos(x * (globals.TileWidth / 16), y * (globals.TileWidth / 16))

        globals.OverrideSnapping = False


class CompoundCommand(Command):
    """Executes a sequence of commands."""
    def __init__(self, description=""):
        super().__init__(description)
        self.commands = []

    def add_command(self, command):
        self.commands.append(command)

    def undo(self):
        for cmd in reversed(self.commands):
            cmd.undo()

    def redo(self):
        for cmd in self.commands:
            cmd.redo()


class UndoManager(QtCore.QObject):
    """Manages the undo and redo stacks."""
    stackChanged = QtCore.pyqtSignal()

    def __init__(self, max_history=100):
        super().__init__()
        self.max_history = max_history
        self.undo_stack = []
        self.redo_stack = []
        self._current_compound = None
        self._in_initial_push = False  # True while push() is executing command.redo()

    def push(self, command):
        """Executes a command and adds it to the undo stack."""
        self._in_initial_push = True
        command.redo()
        self._in_initial_push = False

        if self._current_compound is not None:
            self._current_compound.add_command(command)
        else:
            self.undo_stack.append(command)
            if len(self.undo_stack) > self.max_history:
                self.undo_stack.pop(0)
            self.redo_stack.clear()
            self._update_ui()
            self._on_action_completed(initial_push=True)

    def begin_compound(self, description):
        """Starts grouping commands into a CompoundCommand."""
        if self._current_compound is None:
            self._current_compound = CompoundCommand(description)

    def end_compound(self):
        """Ends grouping and pushes the CompoundCommand if it has sub-commands."""
        if self._current_compound is not None:
            cmd = self._current_compound
            self._current_compound = None
            if cmd.commands:
                self.undo_stack.append(cmd)
                if len(self.undo_stack) > self.max_history:
                    self.undo_stack.pop(0)
                self.redo_stack.clear()
                self._update_ui()
                self._on_action_completed(initial_push=True)

    def undo(self):
        if self.canUndo():
            cmd = self.undo_stack.pop()
            cmd.undo()
            self.redo_stack.append(cmd)
            self._update_ui()
            self._on_action_completed(initial_push=False)

    def redo(self):
        if self.canRedo():
            cmd = self.redo_stack.pop()
            cmd.redo()
            self.undo_stack.append(cmd)
            self._update_ui()
            self._on_action_completed(initial_push=False)

    def jump_to(self, count):
        """Undoes or redoes until `count` commands are on the undo stack."""
        while len(self.undo_stack) > count and self.canUndo():
            self.undo()
        while len(self.undo_stack) < count and self.canRedo():
            self.redo()

    def _on_action_completed(self, initial_push=False):
        """Handles post-action cleanup and UI refreshes."""
        if not hasattr(globals, 'mainWindow') or not globals.mainWindow:
            return

        mw = globals.mainWindow

        # Full scene repaint on undo/redo — individual commands already do targeted
        # updates during the initial push, so skip the extra full repaint there.
        if not initial_push:
            if hasattr(mw, 'scene') and mw.scene:
                mw.scene.update()

        # Level Overview always needs updating.
        if hasattr(mw, 'levelOverview') and mw.levelOverview:
            mw.levelOverview.update()

        # Zone auxiliary items only need refreshing after zone-move commands;
        # those commands call zoneRepositioned() directly, so no sweep needed here.

        SetDirty()

    def canUndo(self):
        return len(self.undo_stack) > 0

    def canRedo(self):
        return len(self.redo_stack) > 0

    def undoText(self):
        return self.undo_stack[-1].description if self.canUndo() else ""

    def redoText(self):
        return self.redo_stack[-1].description if self.canRedo() else ""

    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._current_compound = None
        self._update_ui()

    def _update_ui(self):
        """Emits signal to update UI."""
        self.stackChanged.emit()


# -----------------------------------------------------------------------------
# Specific Commands
# -----------------------------------------------------------------------------

# Object Commands
class MoveObjectsCommand(Command):
    def __init__(self, moves):
        super().__init__("Move Objects")
        # moves is a list of tuples: (obj, old_pos, new_pos)
        self.moves = moves

    def undo(self):
        from .items import CommentItem
        has_comments = False
        for obj, old_pos, new_pos in self.moves:
            self._set_item_pos(obj, old_pos[0], old_pos[1])
            if isinstance(obj, CommentItem):
                obj.handlePosChange(new_pos[0], new_pos[1])
                obj.UpdateListItem()
                has_comments = True
        if has_comments and hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.SaveComments()
            globals.mainWindow.scene.update()

    def redo(self):
        from .items import CommentItem
        has_comments = False
        for obj, old_pos, new_pos in self.moves:
            self._set_item_pos(obj, new_pos[0], new_pos[1])
            if isinstance(obj, CommentItem):
                obj.handlePosChange(old_pos[0], old_pos[1])
                obj.UpdateListItem()
                has_comments = True
        if has_comments and hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.SaveComments()
            globals.mainWindow.scene.update()


class ResizeItemCommand(Command):
    def __init__(self, item, old_geom, new_geom):
        # old_geom/new_geom is (x, y, w, h)
        from .items import ObjectItem, ZoneItem, LocationItem
        if isinstance(item, ObjectItem):
            desc = "Resize Object"
        elif isinstance(item, ZoneItem):
            desc = "Resize Zone"
        elif isinstance(item, LocationItem):
            desc = "Resize Location"
        else:
            desc = "Resize Item"
            
        super().__init__(desc)
        self.item = item
        self.old_geom = old_geom
        self.new_geom = new_geom

    def undo(self):
        self._apply_geom(self.old_geom)

    def redo(self):
        self._apply_geom(self.new_geom)

    def _apply_geom(self, geom):
        x, y, w, h = geom
        self._set_item_pos(self.item, x, y)
        self.item.width, self.item.height = w, h
        if hasattr(self.item, 'updateObjCache'):
            self.item.updateObjCache()
        if hasattr(self.item, 'UpdateRects'):
            self.item.UpdateRects()
        if hasattr(self.item, 'prepareGeometryChange'):
            self.item.prepareGeometryChange()


class AddObjectCommand(Command):
    def __init__(self, obj, layer_idx, z_value=None):
        super().__init__("Add Object")
        self.obj = obj
        self.layer_idx = layer_idx
        self.z_value = z_value

    def undo(self):
        self.obj.delete()
        if self.obj.scene():
            self.obj.scene().removeItem(self.obj)
            
    def redo(self):
        layer = globals.Area.layers[self.layer_idx]
        layer.append(self.obj)
        self.obj.layer = self.layer_idx
        if self.z_value is not None:
            self.obj.setZValue(self.z_value)
        else:
            self.obj.setZValue(len(layer) - 1 + (self.layer_idx * 10000))
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            if self.obj.scene() != globals.mainWindow.scene:
                globals.mainWindow.scene.addItem(self.obj)


class DeleteObjectsCommand(Command):
    def __init__(self, obj_info_list):
        super().__init__("Delete Objects")
        # obj_info_list contains (obj, layer_idx, list_idx, z_value)
        self.obj_info_list = obj_info_list

    def undo(self):
        # Restore in reverse order to maintain indices
        for obj, layer_idx, list_idx, z_value in reversed(self.obj_info_list):
            layer = globals.Area.layers[layer_idx]
            layer.insert(list_idx, obj)
            obj.layer = layer_idx
            obj.setZValue(z_value)
            
            # Shift Z-values of items after it up
            for i in range(list_idx + 1, len(layer)):
                upd = layer[i]
                upd.setZValue(upd.zValue() + 1)
                
            if hasattr(globals, 'mainWindow') and globals.mainWindow:
                globals.mainWindow.scene.addItem(obj)

    def redo(self):
        for obj, _, _, _ in self.obj_info_list:
            obj.delete()
            if obj.scene():
                obj.scene().removeItem(obj)


# Sprite Commands
class MoveSpriteCommand(Command):
    def __init__(self, moves):
        super().__init__("Move Sprites")
        # moves: list of (spr, old_x, old_y, new_x, new_y)
        self.moves = moves

    def undo(self):
        for spr, old_x, old_y, _, _ in self.moves:
            self._set_item_pos(spr, old_x, old_y)
            spr.UpdateListItem()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()

    def redo(self):
        for spr, _, _, new_x, new_y in self.moves:
            self._set_item_pos(spr, new_x, new_y)
            spr.UpdateListItem()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()


class AddSpriteCommand(Command):
    def __init__(self, spr):
        super().__init__("Add Sprite")
        self.spr = spr
        self.list_idx = -1

    def undo(self):
        if self.spr in globals.Area.sprites:
            self.list_idx = globals.Area.sprites.index(self.spr)
            globals.Area.sprites.remove(self.spr)
            
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            sprlist = globals.mainWindow.spriteList
            globals.mainWindow.UpdateFlag = True
            if self.spr.listitem is not None:
                sprlist.takeItem(sprlist.row(self.spr.listitem))
            globals.mainWindow.UpdateFlag = False
            if self.spr.ImageObj:
                for aux in self.spr.ImageObj.aux:
                    if aux.scene():
                        aux.scene().removeItem(aux)
            if self.spr.scene():
                self.spr.scene().removeItem(self.spr)
            self.spr.delete()
            globals.mainWindow.scene.update()

    def redo(self):
        if self.list_idx != -1 and self.list_idx <= len(globals.Area.sprites):
            globals.Area.sprites.insert(self.list_idx, self.spr)
        else:
            globals.Area.sprites.append(self.spr)
        
        self.spr.InitializeSprite()
            
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            mw = globals.mainWindow
            mw.scene.addItem(self.spr)
            if self.spr.ImageObj:
                for aux in self.spr.ImageObj.aux:
                    mw.scene.addItem(aux)
                
            mw.UpdateFlag = True
            if self.spr.listitem is not None:
                if self.list_idx != -1 and self.list_idx <= mw.spriteList.count():
                    mw.spriteList.insertItem(self.list_idx, self.spr.listitem)
                else:
                    mw.spriteList.addItem(self.spr.listitem)
            mw.UpdateFlag = False
            mw.scene.update()
            SetDirty()


class DeleteSpritesCommand(Command):
    def __init__(self, spr_info_list):
        super().__init__("Delete Sprites")
        # spr_info_list: list of (spr, list_idx)
        self.spr_info_list = spr_info_list

    def undo(self):
        for spr, list_idx in reversed(self.spr_info_list):
            globals.Area.sprites.insert(list_idx, spr)
            spr.InitializeSprite()
            if hasattr(globals, 'mainWindow') and globals.mainWindow:
                mw = globals.mainWindow
                mw.scene.addItem(spr)
                if spr.ImageObj:
                    for aux in spr.ImageObj.aux:
                        mw.scene.addItem(aux)
                mw.UpdateFlag = True
                if spr.listitem is not None:
                    mw.spriteList.insertItem(list_idx, spr.listitem)
                mw.UpdateFlag = False
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()

    def redo(self):
        for spr, _ in self.spr_info_list:
            if spr in globals.Area.sprites:
                globals.Area.sprites.remove(spr)
            if hasattr(globals, 'mainWindow') and globals.mainWindow:
                mw = globals.mainWindow
                mw.UpdateFlag = True
                if spr.listitem is not None:
                    mw.spriteList.takeItem(mw.spriteList.row(spr.listitem))
                mw.UpdateFlag = False
                if spr.ImageObj:
                    for aux in spr.ImageObj.aux:
                        if aux.scene():
                            aux.scene().removeItem(aux)
                spr.delete()
                if spr.scene():
                    spr.scene().removeItem(spr)
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()


class SpriteDataChangedCommand(Command):
    def __init__(self, spr, old_data, new_data):
        super().__init__("Change Sprite Data")
        self.spr = spr
        self.old_data = old_data
        self.new_data = new_data

    def undo(self):
        self.spr.spritedata = self.old_data
        self.spr.UpdateListItem()
        self.spr.UpdateDynamicSizing()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.UpdateModeInfo()

    def redo(self):
        self.spr.spritedata = self.new_data
        self.spr.UpdateListItem()
        self.spr.UpdateDynamicSizing()
        # Skip UpdateModeInfo during the initial push — the field handler already
        # has the UI up-to-date. Only refresh on explicit undo/redo.
        if not self._is_initial_push() and hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.UpdateModeInfo()

# Entrance Commands
class MoveEntranceCommand(Command):
    def __init__(self, moves):
        super().__init__("Move Entrances")
        self.moves = moves

    def undo(self):
        for ent, old_x, old_y, _, _ in self.moves:
            self._set_item_pos(ent, old_x, old_y)
            ent.UpdateListItem()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()

    def redo(self):
        for ent, _, _, new_x, new_y in self.moves:
            self._set_item_pos(ent, new_x, new_y)
            ent.UpdateListItem()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()


class AddEntranceCommand(Command):
    def __init__(self, ent):
        super().__init__("Add Entrance")
        self.ent = ent
        self.list_idx = -1

    def undo(self):
        if self.ent in globals.Area.entrances:
            self.list_idx = globals.Area.entrances.index(self.ent)
            globals.Area.entrances.remove(self.ent)
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            mw = globals.mainWindow
            mw.UpdateFlag = True
            if self.ent.listitem is not None:
                mw.entranceList.takeItem(mw.entranceList.row(self.ent.listitem))
            mw.UpdateFlag = False
            self.ent.delete()
            if self.ent.scene():
                self.ent.scene().removeItem(self.ent)
            if self.ent.aux.scene():
                self.ent.aux.scene().removeItem(self.ent.aux)
            mw.scene.update()
            SetDirty()

    def redo(self):
        if self.ent not in globals.Area.entrances:
            if self.list_idx != -1 and self.list_idx <= len(globals.Area.entrances):
                globals.Area.entrances.insert(self.list_idx, self.ent)
            else:
                globals.Area.entrances.append(self.ent)

        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            mw = globals.mainWindow
            if not self.ent.scene():
                mw.scene.addItem(self.ent)
            if not self.ent.aux.scene():
                mw.scene.addItem(self.ent.aux)
            
            mw.UpdateFlag = True
            if self.ent.listitem is not None:
                # If it's already in the list, don't add it again
                if mw.entranceList.row(self.ent.listitem) == -1:
                    if self.list_idx != -1 and self.list_idx <= mw.entranceList.count():
                        mw.entranceList.insertItem(self.list_idx, self.ent.listitem)
                    else:
                        mw.entranceList.addItem(self.ent.listitem)
            mw.UpdateFlag = False
            mw.scene.update()


class DeleteEntrancesCommand(Command):
    def __init__(self, ent_info_list):
        super().__init__("Delete Entrances")
        # ent_info_list: list of (ent, list_idx)
        self.ent_info_list = ent_info_list

    def undo(self):
        for ent, list_idx in reversed(self.ent_info_list):
            globals.Area.entrances.insert(list_idx, ent)
            if hasattr(globals, 'mainWindow') and globals.mainWindow:
                mw = globals.mainWindow
                mw.scene.addItem(ent)
                mw.scene.addItem(ent.aux)
                mw.UpdateFlag = True
                if ent.listitem is not None:
                    mw.entranceList.insertItem(list_idx, ent.listitem)
                mw.UpdateFlag = False
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()

    def redo(self):
        for ent, _ in self.ent_info_list:
            if ent in globals.Area.entrances:
                globals.Area.entrances.remove(ent)
            if hasattr(globals, 'mainWindow') and globals.mainWindow:
                mw = globals.mainWindow
                mw.UpdateFlag = True
                if ent.listitem is not None:
                    mw.entranceList.takeItem(mw.entranceList.row(ent.listitem))
                mw.UpdateFlag = False
                if ent.scene():
                    ent.scene().removeItem(ent)
                if ent.aux.scene():
                    ent.aux.scene().removeItem(ent.aux)
                ent.delete()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()
            SetDirty()


class EntrancePropertyChangedCommand(Command):
    def __init__(self, ent, old_props, new_props):
        super().__init__("Change Entrance Properties")
        self.ent = ent
        self.old_props = old_props
        self.new_props = new_props

    def undo(self):
        self._apply_props(self.old_props)
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            SetDirty()

    def redo(self):
        self._apply_props(self.new_props)
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            SetDirty()

    def _apply_props(self, props):
        for k, v in props.items():
            setattr(self.ent, k, v)
        if 'enttype' in props:
            self.ent.TypeChange()
        self.ent.update()
        self.ent.UpdateTooltip()
        self.ent.UpdateListItem()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()
            globals.mainWindow.UpdateModeInfo()


# Location Commands
class MoveLocationCommand(Command):
    def __init__(self, moves):
        super().__init__("Move Locations")
        self.moves = moves

    def undo(self):
        for loc, old_x, old_y, _, _ in self.moves:
            self._set_item_pos(loc, old_x, old_y)
            loc.UpdateListItem()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()

    def redo(self):
        for loc, _, _, new_x, new_y in self.moves:
            self._set_item_pos(loc, new_x, new_y)
            loc.UpdateListItem()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()


class ResizeLocationCommand(Command):
    def __init__(self, loc, old_geom, new_geom):
        super().__init__("Resize Location")
        self.loc = loc
        self.old_geom = old_geom
        self.new_geom = new_geom

    def undo(self):
        self._apply_geom(self.old_geom)

    def redo(self):
        self._apply_geom(self.new_geom)

    def _apply_geom(self, geom):
        x, y, w, h = geom
        self._set_item_pos(self.loc, x, y)
        self.loc.width = w
        self.loc.height = h
        self.loc.UpdateRects()
        self.loc.prepareGeometryChange()
        self.loc.UpdateListItem()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()
            globals.mainWindow.UpdateModeInfo()
            SetDirty()


class AddLocationCommand(Command):
    def __init__(self, loc):
        super().__init__("Add Location")
        self.loc = loc
        self.list_idx = -1

    def undo(self):
        if self.loc in globals.Area.locations:
            self.list_idx = globals.Area.locations.index(self.loc)
            globals.Area.locations.remove(self.loc)
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            mw = globals.mainWindow
            mw.UpdateFlag = True
            if self.loc.listitem is not None:
                mw.locationList.takeItem(mw.locationList.row(self.loc.listitem))
            mw.UpdateFlag = False
            self.loc.delete()
            if self.loc.scene():
                self.loc.scene().removeItem(self.loc)
            mw.scene.update()
            SetDirty()

    def redo(self):
        if self.list_idx != -1 and self.list_idx <= len(globals.Area.locations):
            globals.Area.locations.insert(self.list_idx, self.loc)
        else:
            globals.Area.locations.append(self.loc)
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            mw = globals.mainWindow
            mw.scene.addItem(self.loc)
            mw.UpdateFlag = True
            if self.loc.listitem is not None:
                if self.list_idx != -1 and self.list_idx <= mw.locationList.count():
                    mw.locationList.insertItem(self.list_idx, self.loc.listitem)
                else:
                    mw.locationList.addItem(self.loc.listitem)
            mw.UpdateFlag = False
            mw.scene.update()


class DeleteLocationsCommand(Command):
    def __init__(self, loc_info_list):
        super().__init__("Delete Locations")
        self.loc_info_list = loc_info_list

    def undo(self):
        for loc, list_idx in reversed(self.loc_info_list):
            globals.Area.locations.insert(list_idx, loc)
            if hasattr(globals, 'mainWindow') and globals.mainWindow:
                mw = globals.mainWindow
                mw.scene.addItem(loc)
                mw.UpdateFlag = True
                if loc.listitem is not None:
                    mw.locationList.insertItem(list_idx, loc.listitem)
                mw.UpdateFlag = False
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()

    def redo(self):
        for loc, _ in self.loc_info_list:
            if loc in globals.Area.locations:
                globals.Area.locations.remove(loc)
            if hasattr(globals, 'mainWindow') and globals.mainWindow:
                mw = globals.mainWindow
                mw.UpdateFlag = True
                if loc.listitem is not None:
                    mw.locationList.takeItem(mw.locationList.row(loc.listitem))
                mw.UpdateFlag = False
                if loc.scene():
                    loc.scene().removeItem(loc)
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()
            SetDirty()


# Path Commands
class MovePathNodeCommand(Command):
    def __init__(self, moves, is_nabbit=False):
        super().__init__("Move Path Nodes")
        self.moves = moves
        self.is_nabbit = is_nabbit

    def undo(self):
        for node, old_x, old_y, _, _ in self.moves:
            self._set_item_pos(node, old_x, old_y)
            node.updatePos()
            if not self.is_nabbit:
                node.pathinfo['peline'].nodePosChanged()
            node.UpdateListItem()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()

    def redo(self):
        for node, _, _, new_x, new_y in self.moves:
            self._set_item_pos(node, new_x, new_y)
            node.updatePos()
            if not self.is_nabbit:
                node.pathinfo['peline'].nodePosChanged()
            node.UpdateListItem()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()


class AddPathNodeCommand(Command):
    def __init__(self, pathinfo, nodeinfo, node, is_nabbit=False, index=-1):
        super().__init__("Add Path Node")
        self.pathinfo = pathinfo
        self.nodeinfo = nodeinfo
        self.node = node
        self.is_nabbit = is_nabbit
        self.is_new_path = index == -1
        self.index = index

    def undo(self):
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            mw = globals.mainWindow
            plist = mw.nabbitPathList if self.is_nabbit else mw.pathList
            paths = globals.Area.nPaths if self.is_nabbit else globals.Area.paths
            
            mw.UpdateFlag = True
            if self.node.listitem is not None:
                plist.takeItem(plist.row(self.node.listitem))
            mw.UpdateFlag = False
            
            if self.node in paths:
                paths.remove(self.node)
            if self.nodeinfo in self.pathinfo['nodes']:
                self.index = self.pathinfo['nodes'].index(self.nodeinfo)
                self.pathinfo['nodes'].remove(self.nodeinfo)
                
            if len(self.pathinfo['nodes']) == 0:
                if self.is_nabbit:
                    globals.Area.nPathdata = []
                else:
                    if self.pathinfo in globals.Area.pathdata:
                        globals.Area.pathdata.remove(self.pathinfo)
                if 'peline' in self.pathinfo and self.pathinfo['peline'].scene():
                    self.pathinfo['peline'].scene().removeItem(self.pathinfo['peline'])
            else:
                for pathnode in self.pathinfo['nodes']:
                    pathnode['graphicsitem'].updateId()
                if 'peline' in self.pathinfo:
                    self.pathinfo['peline'].nodePosChanged()

            if self.node.scene():
                self.node.scene().removeItem(self.node)
            mw.scene.update()

    def redo(self):
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            mw = globals.mainWindow
            plist = mw.nabbitPathList if self.is_nabbit else mw.pathList
            paths = globals.Area.nPaths if self.is_nabbit else globals.Area.paths
            
            if self.is_new_path:
                if self.is_nabbit:
                    if not globals.Area.nPathdata:
                        globals.Area.nPathdata = self.pathinfo
                else:
                    if self.pathinfo not in globals.Area.pathdata:
                        globals.Area.pathdata.append(self.pathinfo)
                        globals.Area.pathdata.sort(key=lambda p: int(p['id']))
                
                if 'peline' not in self.pathinfo:
                    from .items import PathEditorLineItem, NabbitPathEditorLineItem
                    if self.is_nabbit:
                        self.pathinfo['peline'] = NabbitPathEditorLineItem(self.pathinfo['nodes'])
                    else:
                        self.pathinfo['peline'] = PathEditorLineItem(self.pathinfo['nodes'])
                
                if self.pathinfo['peline'].scene() is None:
                    mw.scene.addItem(self.pathinfo['peline'])
            
            if self.nodeinfo not in self.pathinfo['nodes']:
                if self.index == -1:
                    self.pathinfo['nodes'].append(self.nodeinfo)
                else:
                    self.pathinfo['nodes'].insert(self.index, self.nodeinfo)
            if self.node not in paths:
                paths.append(self.node)
                
            if not self.node.scene():
                mw.scene.addItem(self.node)
            
            # Rebuild list
            mw.UpdateFlag = True
            if not self.is_nabbit:
                while plist.count() > 0:
                    plist.takeItem(0)

                for fpath in globals.Area.pathdata:
                    for fpnode in fpath['nodes']:
                        plist.addItem(fpnode['graphicsitem'].listitem)
                        fpnode['graphicsitem'].updateId()
            else:
                while plist.count() > 0:
                    plist.takeItem(0)
                if globals.Area.nPathdata:
                    for fpnode in globals.Area.nPathdata['nodes']:
                        plist.addItem(fpnode['graphicsitem'].listitem)
                        fpnode['graphicsitem'].updateId()
                        
            mw.UpdateFlag = False
            
            if 'peline' in self.pathinfo and self.pathinfo['peline'].scene():
                self.pathinfo['peline'].nodePosChanged()
            mw.scene.update()
            SetDirty()


class DeletePathNodeCommand(Command):
    def __init__(self, node_info_list, is_nabbit=False):
        super().__init__("Delete Path Nodes")
        # node_info_list: list of (node, pathinfo, nodeinfo, node_idx, path_was_removed, is_nabbit)
        self.node_info_list = node_info_list
        self.is_nabbit = is_nabbit

    def undo(self):
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            mw = globals.mainWindow
            plist = mw.nabbitPathList if self.is_nabbit else mw.pathList
            paths = globals.Area.nPaths if self.is_nabbit else globals.Area.paths

            # First pass: restore any path data structures that were fully removed
            for node, pathinfo, nodeinfo, node_idx, path_was_removed, _ in self.node_info_list:
                if path_was_removed:
                    if self.is_nabbit:
                        globals.Area.nPathdata = pathinfo
                    else:
                        globals.Area.pathdata.append(pathinfo)
                        globals.Area.pathdata.sort(key=lambda p: int(p['id']))
                    if 'peline' in pathinfo:
                        mw.scene.addItem(pathinfo['peline'])

            # Second pass: insert nodes in ascending index order per path so positions are correct
            for node, pathinfo, nodeinfo, node_idx, path_was_removed, _ in sorted(self.node_info_list, key=lambda x: (id(x[1]), x[3])):
                pathinfo['nodes'].insert(node_idx, nodeinfo)
                paths.append(node)
                mw.scene.addItem(node)
            
            # Rebuild list to ensure correct order
            mw.UpdateFlag = True
            if not self.is_nabbit:
                while plist.count() > 0:
                    plist.takeItem(0)

                for fpath in globals.Area.pathdata:
                    for fpnode in fpath['nodes']:
                        plist.addItem(fpnode['graphicsitem'].listitem)
                        fpnode['graphicsitem'].updateId()
            else:
                while plist.count() > 0:
                    plist.takeItem(0)
                if globals.Area.nPathdata:
                    for fpnode in globals.Area.nPathdata['nodes']:
                        plist.addItem(fpnode['graphicsitem'].listitem)
                        fpnode['graphicsitem'].updateId()
            mw.UpdateFlag = False
            
            # Update polylines
            for _, pathinfo, _, _, _, _ in self.node_info_list:
                if 'peline' in pathinfo:
                    pathinfo['peline'].nodePosChanged()
            
            mw.scene.update()

    def redo(self):
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            mw = globals.mainWindow
            plist = mw.nabbitPathList if self.is_nabbit else mw.pathList
            paths = globals.Area.nPaths if self.is_nabbit else globals.Area.paths
            
            for node, pathinfo, nodeinfo, _, path_was_removed, _ in self.node_info_list:
                if node in paths:
                    paths.remove(node)
                if nodeinfo in pathinfo['nodes']:
                    pathinfo['nodes'].remove(nodeinfo)
                
                if path_was_removed:
                    if self.is_nabbit:
                        globals.Area.nPathdata = []
                    else:
                        if pathinfo in globals.Area.pathdata:
                            globals.Area.pathdata.remove(pathinfo)
                    if 'peline' in pathinfo and pathinfo['peline'].scene():
                        pathinfo['peline'].scene().removeItem(pathinfo['peline'])
                else:
                    for pathnode in pathinfo['nodes']:
                        pathnode['graphicsitem'].updateId()
                    if 'peline' in pathinfo and pathinfo['peline'].scene():
                        pathinfo['peline'].nodePosChanged()
                
                if node.scene():
                    node.scene().removeItem(node)
                
            # Rebuild list
            mw.UpdateFlag = True
            if not self.is_nabbit:
                while plist.count() > 0:
                    plist.takeItem(0)

                for fpath in globals.Area.pathdata:
                    for fpnode in fpath['nodes']:
                        plist.addItem(fpnode['graphicsitem'].listitem)
                        fpnode['graphicsitem'].updateId()
            else:
                while plist.count() > 0:
                    plist.takeItem(0)
                if globals.Area.nPathdata:
                    for fpnode in globals.Area.nPathdata['nodes']:
                        plist.addItem(fpnode['graphicsitem'].listitem)
                        fpnode['graphicsitem'].updateId()
            mw.UpdateFlag = False
            mw.scene.update()


# Comment Commands
class MoveCommentCommand(Command):
    def __init__(self, moves):
        super().__init__("Move Comments")
        self.moves = moves

    def undo(self):
        for com, old_x, old_y, _, _ in self.moves:
            self._set_item_pos(com, old_x, old_y)
            com.handlePosChange(old_x, old_y)
            com.UpdateListItem()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.SaveComments()
            globals.mainWindow.scene.update()

    def redo(self):
        for com, _, _, new_x, new_y in self.moves:
            self._set_item_pos(com, new_x, new_y)
            com.handlePosChange(new_x, new_y)
            com.UpdateListItem()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.SaveComments()
            globals.mainWindow.scene.update()


class AddCommentCommand(Command):
    def __init__(self, com):
        super().__init__("Add Comment")
        self.com = com
        self.list_idx = -1

    def undo(self):
        if self.com in globals.Area.comments:
            self.list_idx = globals.Area.comments.index(self.com)
            globals.Area.comments.remove(self.com)
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            mw = globals.mainWindow
            mw.UpdateFlag = True
            if self.com.listitem is not None:
                mw.commentList.takeItem(mw.commentList.row(self.com.listitem))
            mw.UpdateFlag = False
            
            p = self.com.TextEditProxy
            if p and p.scene():
                p.scene().removeItem(p)
            if self.com.scene():
                self.com.scene().removeItem(self.com)
            mw.SaveComments()
            mw.scene.update()

    def redo(self):
        if self.list_idx != -1 and self.list_idx <= len(globals.Area.comments):
            globals.Area.comments.insert(self.list_idx, self.com)
        else:
            globals.Area.comments.append(self.com)
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            mw = globals.mainWindow
            mw.scene.addItem(self.com)
            mw.scene.addItem(self.com.TextEditProxy)
            mw.UpdateFlag = True
            if self.com.listitem is not None:
                if self.list_idx != -1 and self.list_idx <= mw.commentList.count():
                    mw.commentList.insertItem(self.list_idx, self.com.listitem)
                else:
                    mw.commentList.addItem(self.com.listitem)
            mw.UpdateFlag = False
            mw.SaveComments()
            mw.scene.update()


class DeleteCommentsCommand(Command):
    def __init__(self, com_info_list):
        super().__init__("Delete Comments")
        self.com_info_list = com_info_list

    def undo(self):
        for com, list_idx in reversed(self.com_info_list):
            globals.Area.comments.insert(list_idx, com)
            if hasattr(globals, 'mainWindow') and globals.mainWindow:
                mw = globals.mainWindow
                mw.scene.addItem(com)
                mw.scene.addItem(com.TextEditProxy)
                mw.UpdateFlag = True
                if com.listitem is not None:
                    mw.commentList.insertItem(list_idx, com.listitem)
                mw.UpdateFlag = False
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.SaveComments()
            globals.mainWindow.scene.update()

    def redo(self):
        for com, _ in self.com_info_list:
            if com in globals.Area.comments:
                globals.Area.comments.remove(com)
            if hasattr(globals, 'mainWindow') and globals.mainWindow:
                mw = globals.mainWindow
                mw.UpdateFlag = True
                if com.listitem is not None:
                    mw.commentList.takeItem(mw.commentList.row(com.listitem))
                mw.UpdateFlag = False
                
                p = com.TextEditProxy
                if p and p.scene():
                    p.scene().removeItem(p)
                if com.scene():
                    com.scene().removeItem(com)
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.SaveComments()
            globals.mainWindow.scene.update()


# Other Commands
class ZonePropertyChangedCommand(Command):
    def __init__(self, zone, old_props, new_props):
        super().__init__("Change Zone Properties")
        self.zone = zone
        self.old_props = old_props
        self.new_props = new_props

    def undo(self):
        self._apply_props(self.old_props)

    def redo(self):
        self._apply_props(self.new_props)

    def _apply_props(self, props):
        self.zone.objx = props['x']
        self.zone.objy = props['y']
        self.zone.width = props['w']
        self.zone.height = props['h']
        self.zone.cammode = props.get('cammode', 0)
        self.zone.zoom = props.get('zoom', 0)
        self.zone.colorbg = props.get('colorbg', 0)
        
        self.zone.prepareGeometryChange()
        self.zone.UpdateRects()
        self.zone.setPos(self.zone.objx * (globals.TileWidth / 16), self.zone.objy * (globals.TileWidth / 16))


class RaiseLowerObjectsCommand(Command):
    def __init__(self, desc, obj_info_list):
        super().__init__(desc)
        # list of (obj, old_z, new_z)
        self.obj_info_list = obj_info_list

    def undo(self):
        for obj, old_z, _ in self.obj_info_list:
            obj.setZValue(old_z)
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            self._sort_layers(globals.mainWindow)

    def redo(self):
        for obj, _, new_z in self.obj_info_list:
            obj.setZValue(new_z)
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            self._sort_layers(globals.mainWindow)
            
    def _sort_layers(self, mw):
        for layer in globals.Area.layers:
            layer.sort(key=lambda obj: obj.zValue())
        mw.scene.update()


class ShiftItemsCommand(Command):
    def __init__(self, item_moves):
        super().__init__("Shift Items")
        # item_moves: list of (item, old_x, old_y, new_x, new_y)
        self.item_moves = item_moves

    def undo(self):
        for item, old_x, old_y, _, _ in self.item_moves:
            self._set_item_pos(item, old_x, old_y)
            if hasattr(item, 'updatePos'):
                item.updatePos()
            if hasattr(item, 'handlePosChange'):
                item.handlePosChange(old_x, old_y)
            if hasattr(item, 'UpdateListItem'):
                item.UpdateListItem()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()

    def redo(self):
        for item, _, _, new_x, new_y in self.item_moves:
            self._set_item_pos(item, new_x, new_y)
            if hasattr(item, 'updatePos'):
                item.updatePos()
            if hasattr(item, 'handlePosChange'):
                item.handlePosChange(new_x, new_y)
            if hasattr(item, 'UpdateListItem'):
                item.UpdateListItem()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()


class ObjectTypeChangedCommand(Command):
    def __init__(self, changes):
        super().__init__("Change Object Type")
        # changes: list of (obj, old_ts, old_type, old_data, new_ts, new_type, new_data)
        self.changes = changes

    def undo(self):
        for obj, old_ts, old_type, old_data, _, _, _ in self.changes:
            obj.SetType(old_ts, old_type)
            obj.data = old_data
            obj.update()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()

    def redo(self):
        for obj, _, _, _, new_ts, new_type, new_data in self.changes:
            obj.SetType(new_ts, new_type)
            obj.data = new_data
            obj.update()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.scene.update()


class SpriteTypeChangedCommand(Command):
    def __init__(self, changes):
        super().__init__("Change Sprite Type")
        # changes: list of (spr, old_type, old_data, new_type, new_data)
        self.changes = changes

    def undo(self):
        for spr, old_type, old_data, _, _ in self.changes:
            spr.spritedata = old_data
            spr.SetType(old_type)
            spr.update()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.ChangeSelectionHandler()
            globals.mainWindow.scene.update()

    def redo(self):
        for spr, _, _, new_type, new_data in self.changes:
            spr.spritedata = new_data
            spr.SetType(new_type)
            spr.update()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.ChangeSelectionHandler()
            globals.mainWindow.scene.update()


class SpritePropertyChangedCommand(Command):
    def __init__(self, spr, property_name, old_value, new_value):
        super().__init__("Change Sprite %s" % property_name)
        self.spr = spr
        self.property_name = property_name
        self.old_value = old_value
        self.new_value = new_value

    def undo(self):
        setattr(self.spr, self.property_name, self.old_value)
        self._sync()

    def redo(self):
        setattr(self.spr, self.property_name, self.new_value)
        self._sync()

    def _sync(self):
        self.spr.UpdateListItem()
        self.spr.UpdateDynamicSizing()
        # UpdateDynamicSizing already does targeted rect updates; full repaint
        # only needed on undo/redo where the UI may be out of sync.
        if not self._is_initial_push():
            if hasattr(globals, 'mainWindow') and globals.mainWindow:
                globals.mainWindow.scene.update()
        SetDirty()


class CommentTextChangedCommand(Command):
    def __init__(self, com, old_text, new_text):
        super().__init__("Change Comment Text")
        self.com = com
        self.old_text = old_text
        self.new_text = new_text

    def undo(self):
        self.com.text = self.old_text
        self._sync()

    def redo(self):
        self.com.text = self.new_text
        self._sync()

    def _sync(self):
        text = self.com.text
        te = self.com.TextEdit
        if te.toPlainText() != text:
            te.blockSignals(True)
            te.setPlainText(text)
            te.blockSignals(False)
        self.com.UpdateListItem()
        self.com.UpdateTooltip()
        if hasattr(globals, 'mainWindow') and globals.mainWindow:
            globals.mainWindow.SaveComments()
            globals.mainWindow.scene.update()
            SetDirty()


class PropertyChangedCommand(Command):
    def __init__(self, obj, property_name, old_value, new_value, description=None, sync_func=None):
        if description is None:
            description = "Change %s" % property_name
        super().__init__(description)
        self.obj = obj
        self.property_name = property_name
        self.old_value = old_value
        self.new_value = new_value
        self.sync_func = sync_func

    def undo(self):
        setattr(self.obj, self.property_name, self.old_value)
        if self.sync_func: self.sync_func()
        else: self._default_sync()

    def redo(self):
        setattr(self.obj, self.property_name, self.new_value)
        if self.sync_func: self.sync_func()
        else: self._default_sync()

    def _default_sync(self):
        if hasattr(self.obj, 'update'): self.obj.update()
        if hasattr(self.obj, 'UpdateListItem'): self.obj.UpdateListItem()
        if hasattr(self.obj, 'UpdateTooltip'): self.obj.UpdateTooltip()
        if hasattr(self.obj, 'UpdateRects'): self.obj.UpdateRects()
        if hasattr(self.obj, 'prepareGeometryChange'): self.obj.prepareGeometryChange()
        if hasattr(self.obj, 'objx') and hasattr(self.obj, 'objy'):
            Command._set_item_pos(self.obj, self.obj.objx, self.obj.objy)


class DictPropertyChangedCommand(Command):
    def __init__(self, dct, key, old_value, new_value, description=None, sync_func=None):
        if description is None:
            description = "Change %s" % key
        super().__init__(description)
        self.dct = dct
        self.key = key
        self.old_value = old_value
        self.new_value = new_value
        self.sync_func = sync_func

    def undo(self):
        self.dct[self.key] = self.old_value
        if self.sync_func: self.sync_func()

    def redo(self):
        self.dct[self.key] = self.new_value
        if self.sync_func: self.sync_func()


def get_zone_state(zone):
    return {
        'objx': zone.objx,
        'objy': zone.objy,
        'width': zone.width,
        'height': zone.height,
        'cammode': zone.cammode,
        'camzoom': zone.camzoom,
        'unk1': zone.unk1,
        'visibility': zone.visibility,
        'unk2': zone.unk2,
        'camtrack': zone.camtrack,
        'unk3': zone.unk3,
        'yupperbound': zone.yupperbound,
        'ylowerbound': zone.ylowerbound,
        'yupperbound2': zone.yupperbound2,
        'ylowerbound2': zone.ylowerbound2,
        'yupperbound3': zone.yupperbound3,
        'ylowerbound3': zone.ylowerbound3,
        'mpcamzoomadjust': zone.mpcamzoomadjust,
        'music': zone.music,
        'customMusicName': getattr(zone, 'customMusicName', ''),
        'sfxmod': zone.sfxmod,
        'type': zone.type,
        'background': zone.background,
        'id': zone.id
    }

class ChangeZonesCommand(Command):
    def __init__(self, old_zones, old_states, new_zones, new_states):
        super().__init__("Change Zones")
        self.old_zones = list(old_zones)
        self.old_states = list(old_states)
        self.new_zones = list(new_zones)
        self.new_states = list(new_states)

    def _apply_state(self, zone, state):
        for k, v in state.items():
            setattr(zone, k, v)
        if hasattr(zone, 'UpdateTitle'):
            zone.UpdateTitle()
        if hasattr(zone, 'UpdateRects'):
            zone.UpdateRects()
        if hasattr(zone, 'prepareGeometryChange'):
            zone.prepareGeometryChange()
        zone.setPos(zone.objx * (globals.TileWidth / 16), zone.objy * (globals.TileWidth / 16))

    def undo(self):
        self._apply(self.old_zones, self.old_states)

    def redo(self):
        self._apply(self.new_zones, self.new_states)

    def _apply(self, zones, states):
        from .items import ZoneItem
        mw = globals.mainWindow
        # Remove current zones from scene
        for item in mw.scene.items():
            if isinstance(item, ZoneItem):
                mw.scene.removeItem(item)
        
        globals.Area.zones = list(zones)
        for zone, state in zip(zones, states):
            self._apply_state(zone, state)
            mw.scene.addItem(zone)


class ReplaceTilesetObjectCommand(Command):
    """Swap object definition at a tileset index. Tiles stay in place —
    both old and new defs reference valid tile ranges."""
    def __init__(self, idx, objNum, old_obj_def, new_obj_def):
        super().__init__("Replace Object in Tileset")
        self.idx = idx
        self.objNum = objNum
        self.old_obj_def = old_obj_def
        self.new_obj_def = new_obj_def

    def undo(self):
        globals.ObjectDefinitions[self.idx][self.objNum] = self.old_obj_def
        self._sync_instances()

    def redo(self):
        globals.ObjectDefinitions[self.idx][self.objNum] = self.new_obj_def
        self._sync_instances()

    def _sync_instances(self):
        from .items import ObjectItem
        mw = globals.mainWindow
        for obj in mw.scene.items():
            if isinstance(obj, ObjectItem) and obj.tileset == self.idx and obj.type == self.objNum:
                obj.update()
        from .tileset import HandleTilesetEdited
        HandleTilesetEdited()
        SetDirty()
        mw.scene.update()


class DeleteTilesetObjectCommand(Command):
    """Full tileset-object deletion: removes definition, reindexes types,
    replaces orphaned tiles, cleans up ObjectAddedtoEmbedded, clips, and
    clipboard. Undo fully restores every change."""
    def __init__(self, idx, objNum):
        super().__init__("Delete Object from Tileset")
        self.idx = idx
        self.objNum = objNum

        # Save old definition BEFORE DeleteObject removes it
        obj = globals.ObjectDefinitions[idx][objNum]
        self.old_obj_def = obj
        self.folderIndex = obj.folderIndex
        self.objAllIndex = obj.objAllIndex

        # Save every tile this object references
        self._used_tile_indices = []
        for row in obj.rows:
            for tile in row:
                if len(tile) != 3:
                    continue
                if tile == [0, 0, 0]:
                    continue
                if idx != (tile[1] >> 8) & 3:
                    continue
                tileNum = tile[1] & 0xFF
                randLen = obj.randByte & 0xF
                if randLen:
                    for z in range(randLen):
                        gi = tileNum + z + idx * 256
                        if gi not in self._used_tile_indices:
                            self._used_tile_indices.append(gi)
                else:
                    gi = tileNum + idx * 256
                    if gi not in self._used_tile_indices:
                        self._used_tile_indices.append(gi)

        # Snapshot tiles at those indices
        self.replaced_tiles = {}
        for gi in self._used_tile_indices:
            self.replaced_tiles[gi] = globals.Tiles[gi]

        # Save tileset load state (in case tileset gets unloaded)
        tstr = "tileset%d" % idx
        self._old_tileset_load = getattr(globals.Area, tstr, '')

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _do_clips(idx, objNum, increment):
        """Reindex clip types: increment=True → type+1, else type-1."""
        mw = globals.mainWindow
        for clip in mw.clipChooser._clips:
            try:
                layers, sprites, entrances, locations, paths, nabbitPaths, comments = \
                    mw.getEncodedObjects(clip.miyamoto_clip, False)
            except Exception:
                continue
            objects = []
            for layer in layers:
                for obj in layer:
                    if obj.tileset == idx:
                        if increment and obj.type >= objNum:
                            obj.SetType(idx, obj.type + 1)
                        elif not increment and obj.type > objNum:
                            obj.SetType(idx, obj.type - 1)
                    objects.append(obj)
            clip.miyamoto_clip = mw.encodeObjects(
                objects, sprites, entrances, locations, paths, nabbitPaths, comments)

    @staticmethod
    def _do_clipboard(idx, objNum, increment):
        """Reindex clipboard types. Same direction as _do_clips."""
        mw = globals.mainWindow
        cb = mw.clipboard
        if cb is None or not (cb.startswith('MiyamotoClip|') and cb.endswith('|%')):
            return
        try:
            layers, sprites, entrances, locations, paths, nabbitPaths, comments = \
                mw.getEncodedObjects(cb, False)
        except Exception:
            return
        objects = []
        for layer in layers:
            for obj in layer:
                if obj.tileset == idx:
                    if increment and obj.type >= objNum:
                        obj.SetType(idx, obj.type + 1)
                    elif not increment and obj.type > objNum:
                        obj.SetType(idx, obj.type - 1)
                objects.append(obj)
        mw.clipboard = mw.encodeObjects(
            objects, sprites, entrances, locations, paths, nabbitPaths, comments)

    # ── execution ─────────────────────────────────────────────────────────

    def redo(self):
        from .tileset import DeleteObject as _deleteObj
        _deleteObj(self.idx, self.objNum)

    def undo(self):
        idx, objNum = self.idx, self.objNum

        # 1. Restore object definition at original position
        globals.ObjectDefinitions[idx].insert(objNum, self.old_obj_def)
        globals.ObjectDefinitions[idx].pop()  # remove trailing None from del+append

        # 2. Restore tiles
        for gi, tile in self.replaced_tiles.items():
            globals.Tiles[gi] = tile

        # 3. Restore tileset load state if it was unloaded
        tstr = "tileset%d" % idx
        if not getattr(globals.Area, tstr, ''):
            setattr(globals.Area, tstr, self._old_tileset_load)

        # 4. Reverse ObjectAddedtoEmbedded removal + reindex
        area_key = globals.CurrentArea
        if area_key in globals.ObjectAddedtoEmbedded:
            for folder in globals.ObjectAddedtoEmbedded[area_key]:
                for key in list(globals.ObjectAddedtoEmbedded[area_key][folder].keys()):
                    ts, tn = globals.ObjectAddedtoEmbedded[area_key][folder][key]
                    if ts == idx and tn >= objNum:
                        globals.ObjectAddedtoEmbedded[area_key][folder][key] = (ts, tn + 1)
            if self.folderIndex > -1 and self.folderIndex in globals.ObjectAddedtoEmbedded[area_key]:
                globals.ObjectAddedtoEmbedded[area_key][self.folderIndex][self.objAllIndex] = (idx, objNum)

        # 5. Reverse scene-layer type reindexing
        for layer in globals.Area.layers:
            for obj in layer:
                if obj.tileset == idx and obj.type >= objNum:
                    obj.SetType(idx, obj.type + 1)

        # 6. Reverse clip reindexing
        self._do_clips(idx, objNum, increment=True)

        # 7. Reverse clipboard reindexing
        self._do_clipboard(idx, objNum, increment=True)

        # 8. Refresh UI
        from .tileset import HandleTilesetEdited
        HandleTilesetEdited()
        SetDirty()
        if globals.mainWindow:
            globals.mainWindow.scene.update()



