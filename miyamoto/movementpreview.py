#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Yaz0moto Level Editor
# This file is part of Yaz0moto, a fork of Pyamoto.

# See LICENSE.txt for more information.

"""
Movement preview: animates the sprites hooked to a movement controller (they share a
Movement ID with it, in the same zone) so you can see how they will move in the game.

The preview draws copies ("ghosts") on top of the level and hides the real sprites
while it runs; it never moves, edits or dirties them. Options (shared by the single and
"preview all" previews): play once instead of looping, and keep markers at the start
and end positions.

How exact each motion is:
- Swaying and spinning rotation (68, 69, 116, 118) use the same formulas and speed
  tables as the editor's own "Preview Pivotal Rotation", which come from the game.
- Paths (100), two-way (70, 642), bolts (238) and stepped rotation (214, 484) follow
  every setting that describes the movement (direction, distance, nodes, speeds as
  listed in spritedata.xml...), but some units are not documented: delays, path
  smoothing, acceleration and the sine effect use the estimates below.
"""

import math

from PyQt5 import QtCore, QtGui, QtWidgets
Qt = QtCore.Qt

from . import globals
from .misc import extract_field_value, setting, setSetting

FPS = 60
FULL_TURN = 0x100000000  # the game's angle unit: a full turn
LINK_BITS = (81, 89)     # nybbles 21-22, where sprites keep the Movement ID that links them

# The game's spin speeds (angle units per frame), as used by the editor's rotation preview
SPIN_SPEEDS = (0x400000, 0x800000, 0xc00000, 0x1000000, 0x200000, 0x2000000, 0x4000000, 0x100000)

# Estimates: the game's units for these are not documented
DELAY_FRAMES = 15                 # frames per point of a delay setting
DEFAULT_PATH_SPEED = 1.0          # level units per frame when a path node's speed is 0
PATH_CURVE_SAMPLES = 16           # points per segment of a "curly" (default) path
SINE_UNITS_PER_STRENGTH = 4       # level units of sine movement per point of strength
SINE_DEGREES_PER_SPEED = 1.40625  # degrees of sine phase per frame per point of speed
STEP_SPIN_SPEEDS = {4: 0.5, 0: 1.0, 1: 1.5, 2: 2.0, 3: 3.0, 5: 4.0, 6: 6.0, 7: 8.0, 8: 12.0, 9: 20.0, 10: 360.0}
BOLT_TURN_SPEED = 1.0             # level units per frame while a player turns a bolt
ACCELERATION = 0.15               # share of a two-way trip spent speeding up (and slowing down)
SLOW_ACCELERATION = 0.35          # the same with "Slower Acceleration"
REST_FRAMES = FPS                 # pause before a non-looping motion plays again

START_COLOR = QtGui.QColor(40, 170, 70)  # "Show Start Position" markers
END_COLOR = QtGui.QColor(215, 50, 50)    # "Show End Position" markers

# Preview speed choices (1 = game speed) and the default
SPEEDS = (0.5, 1, 2, 4, 8)
DEFAULT_SPEED = 2

TWO_WAY = (70, 642)
PATH = 100
SWAY = (68, 116)
SPIN = (69, 118)
PATH_PIVOTS = (116, 118)
STEP_SPIN = (214, 484)
BOLT = 238

# Every sprite that moves others through a Movement ID, previewable or not
CONTROLLERS = {68, 69, 70, 100, 116, 118, 214, 238, 297, 299, 484, 642, 672}
NOT_PREVIEWABLE = {
    297: 'The Mushroom Platform controller\'s movement depends on the platform and isn\'t documented, so it can\'t be previewed.',
    299: 'The tilt-controlled girder moves with the players\' weight, so it can\'t be previewed.',
    672: 'The NSLU brick block controller has no documented settings, so it can\'t be previewed.',
}


################################################################
# Reading sprite settings
################################################################

def _fields(type):
    sprites = getattr(globals, 'Sprites', None)
    if isinstance(type, str):
        sdef = globals.CustomSpriteDefinitions.get(type)
    elif sprites is not None and 0 <= type < len(sprites):
        sdef = sprites[type]
    else:
        sdef = None
    return sdef.fields if sdef is not None else ()


def setting_value(sprite, title, default=0):
    """Value of the sprite's field with this title (a dualbox matches either title)."""
    for f in _fields(sprite.type):
        if f[0] == 5 and title in (f[1], f[2]):
            return extract_field_value(sprite.spritedata, f[3])
        if f[1] != title:
            continue
        if f[0] == 0:  # checkbox
            return int(extract_field_value(sprite.spritedata, f[2]) & f[3] != 0)
        if f[0] in (1, 2):  # list, value
            return extract_field_value(sprite.spritedata, f[2])
    return default


def setting_label(sprite, title):
    """The text of the chosen entry of a list field, or None."""
    for f in _fields(sprite.type):
        if f[0] == 1 and f[1] == title:
            value = extract_field_value(sprite.spritedata, f[2])
            for entry_value, text in getattr(f[3], 'entries', ()):
                if entry_value == value:
                    return text
    return None


def _label_number(sprite, title, default):
    """A list field whose entries are numbers ("0.5", "1.0"...), as a number."""
    try:
        return float(setting_label(sprite, title))
    except (TypeError, ValueError):
        return default


def movement_id(sprite):
    """
    The Movement ID that links the sprite to a controller: nybbles 21-22, as the editor's
    rotation preview reads it (some sprites have other movement IDs, such as the Path
    Movement ID of path pivots, or the Mushroom Platform's spinning controller ID).
    """
    found = None
    for f in _fields(sprite.type):
        if f[0] == 2 and len(f) > 5 and f[5] == 'movement':
            if f[2] == LINK_BITS:
                return extract_field_value(sprite.spritedata, f[2])
            if found is None and 'Path' not in f[1]:
                found = extract_field_value(sprite.spritedata, f[2])
    return found


def has_movement_field(type):
    return any(f[0] == 2 and len(f) > 5 and f[5] == 'movement' for f in _fields(type))


def _zone(sprite, area):
    """The zone the game puts the sprite in (the nearest one), as the editor does."""
    if hasattr(sprite, 'nearestZone'):
        return sprite.nearestZone()
    if not getattr(area, 'zones', None):
        return -1
    from .spritelib import MapPositionToZoneID
    return MapPositionToZoneID(area.zones, sprite.objx, sprite.objy, True)


def find_group(area, sprite):
    """
    (controller, moved sprites, message) for the selected sprite. controller is None
    when there is nothing to preview, and message says why.
    """
    mid = movement_id(sprite)
    if mid is None:
        return None, [], 'This actor has no Movement ID.'

    zone = _zone(sprite, area)
    same = [s for s in area.sprites if movement_id(s) == mid and _zone(s, area) == zone]
    controllers = [s for s in same if s.type in CONTROLLERS]
    moved = [s for s in same if s.type not in CONTROLLERS]

    if not controllers:
        return None, moved, 'No movement controller in this zone uses Movement ID %d.' % mid
    controller = sprite if sprite in controllers else controllers[0]
    if controller.type in NOT_PREVIEWABLE:
        return None, moved, NOT_PREVIEWABLE[controller.type]
    if not moved:
        return None, moved, 'Nothing else in this zone uses Movement ID %d, so there is nothing to move.' % mid
    return controller, moved, None


def name_of(sprite):
    sprites = getattr(globals, 'Sprites', None)
    if (isinstance(sprite.type, int) and sprites is not None and 0 <= sprite.type < len(sprites)
            and sprites[sprite.type] is not None):
        return sprites[sprite.type].name
    return 'Sprite %s' % sprite.type


################################################################
# Motions
#
# Each motion gives, for a frame number and a moved sprite, the offset (dx, dy, in
# level units) and the rotation (degrees, Qt's direction, around the motion's pivot,
# which moves with the offset) to apply to that sprite.
################################################################

def _ease(t, accel):
    """Distance share covered at time share t when speeding up and slowing down over accel of the time."""
    if accel <= 0:
        return t
    peak = 1 / (1 - accel)
    if t < accel:
        return peak * t * t / (2 * accel)
    if t > 1 - accel:
        u = 1 - t
        return 1 - peak * u * u / (2 * accel)
    return peak * (t - accel / 2)


class Motion:
    def __init__(self, controller, area):
        self.pivot = (controller.objx + 8, controller.objy + 8)  # middle of the controller's tile
        self.notes = []

    def at(self, frame, sprite=None):
        return 0, 0, 0

    def duration(self, sprite=None):
        """Frames the motion takes to play once (for "Play Once")."""
        return 0

    def end_frame(self, sprite=None):
        """The frame of the motion's end position: where it stops, or turns back when it returns."""
        return self.duration(sprite)


class Timeline:
    """Straight pieces and pauses: an intro that plays once, then a part that repeats."""

    def __init__(self):
        self.intro = []      # (frames, (x0, y0), (x1, y1))
        self.loop = []
        self.segments = self.loop

    def add(self, frames, start, end):
        if frames > 0:
            self.segments.append((frames, start, end))

    def add_path(self, points, frames, accel=0.0, steps=24):
        """Moves along the polyline points in frames, speeding up/slowing down over accel."""
        lengths = [0.0]
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            lengths.append(lengths[-1] + math.hypot(bx - ax, by - ay))
        total = lengths[-1]
        if total == 0 or frames <= 0:
            return

        def point_at(distance):
            for i in range(1, len(points)):
                if distance <= lengths[i] or i == len(points) - 1:
                    piece = lengths[i] - lengths[i - 1]
                    t = (distance - lengths[i - 1]) / piece if piece else 0
                    (ax, ay), (bx, by) = points[i - 1], points[i]
                    return ax + (bx - ax) * t, ay + (by - ay) * t

        steps = max(steps, len(points))
        previous = points[0]
        for k in range(1, steps + 1):
            current = point_at(total * _ease(k / steps, accel))
            self.add(frames / steps, previous, current)
            previous = current

    def end(self):
        segments = self.loop or self.intro
        return segments[-1][2] if segments else (0, 0)

    def length(self):
        return sum(s[0] for s in self.intro) + sum(s[0] for s in self.loop)

    @staticmethod
    def _play(segments, frame):
        for frames, (x0, y0), (x1, y1) in segments:
            if frame < frames:
                t = frame / frames
                return x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            frame -= frames
        return segments[-1][2]

    def at(self, frame):
        introLength = sum(s[0] for s in self.intro)
        if frame < introLength:
            return self._play(self.intro, frame)
        loopLength = sum(s[0] for s in self.loop)
        if loopLength:
            return self._play(self.loop, (frame - introLength) % loopLength)
        return self.end()


class TwoWayMotion(Motion):
    """Movement Controller - Two-Way (70) and its event-activated NSLU version (642)."""

    DIRECTIONS = {'Right': (1, 0), 'Left': (-1, 0), 'Up': (0, -1), 'Down': (0, 1)}

    def __init__(self, controller, area):
        super().__init__(controller, area)
        self.timeline = Timeline()
        self.endFrame = 0

        if setting_value(controller, 'Do nothing'):
            self.notes.append('"Do nothing" is set, so it doesn\'t move.')
            return

        dx, dy = self.DIRECTIONS.get(setting_label(controller, 'Direction'), (1, 0))
        distance = setting_value(controller, 'Distance') * 16
        speed = _label_number(controller, 'Speed', 1.0)
        begin = setting_value(controller, 'Begin Delay') * DELAY_FRAMES
        back = setting_value(controller, 'Return Delay') * DELAY_FRAMES
        if setting_value(controller, 'Add return delay to begin delay'):
            begin += back
        accel = SLOW_ACCELERATION if setting_value(controller, 'Slower Acceleration') else ACCELERATION

        if not distance:
            self.notes.append('Distance is 0, so it doesn\'t move.')
            return

        home, away = (0, 0), (dx * distance, dy * distance)
        travel = distance / speed / (1 - accel)  # top speed stays at the listed speed
        self.timeline.add(begin, home, home)
        self.timeline.add_path([home, away], travel, accel)
        self.timeline.add(back, away, away)
        self.timeline.add_path([away, home], travel, accel)
        self.endFrame = begin + travel
        if controller.type == 642:
            self.notes.append('In the game it waits for its event; the preview runs as if the event is on.')

    def at(self, frame, sprite=None):
        x, y = self.timeline.at(frame)
        return x, y, 0

    def duration(self, sprite=None):
        return self.timeline.length()

    def end_frame(self, sprite=None):
        return self.endFrame


def _catmull_rom(p0, p1, p2, p3, t):
    t2, t3 = t * t, t * t * t
    return tuple(0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3)
                 for a, b, c, d in zip(p0, p1, p2, p3))


class PathMotion(Motion):
    """Movement Controller - Path (100)."""

    def __init__(self, controller, area):
        super().__init__(controller, area)
        self.timeline = Timeline()
        self.sine = None
        self.arrivals = {}  # node -> frame it is first reached
        self.playFrames = 0

        pid = setting_value(controller, 'Path ID')
        path = next((p for p in area.pathdata if p['id'] == pid), None)
        if path is None or len(path['nodes']) < 2:
            self.notes.append('Path %d does not exist or has fewer than two nodes.' % pid)
            return

        nodes = path['nodes']
        start = min(setting_value(controller, 'Starting node'), len(nodes) - 1)
        end_mode = setting_label(controller, 'When the last node is reached') or 'Stop'
        loop_from = min(setting_value(controller, 'Loop starting node'), len(nodes) - 1)
        self.curly = not setting_value(controller, 'Move strictly')
        self.smooth = bool(setting_value(controller, 'Smooth movement'))
        x0, y0 = nodes[start]['x'], nodes[start]['y']
        points = [(n['x'] - x0, n['y'] - y0) for n in nodes]

        def walk(order, closed):
            for k, (a, b) in enumerate(zip(order, order[1:])):
                self.timeline.add(nodes[a]['delay'], points[a], points[a])
                if self.curly:
                    # Before/after neighbours shape the curve; the ends of an open path repeat
                    before = order[k - 1] if k > 0 else (order[-2] if closed else a)
                    after = order[k + 2] if k + 2 < len(order) else (order[1] if closed else b)
                    pts = [_catmull_rom(points[before], points[a], points[b], points[after], i / PATH_CURVE_SAMPLES)
                           for i in range(PATH_CURVE_SAMPLES + 1)]
                else:
                    pts = [points[a], points[b]]
                length = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts, pts[1:]))
                speed = abs(nodes[a]['speed']) or DEFAULT_PATH_SPEED
                accel = 0.5 if self.smooth else 0.0
                self.timeline.add_path(pts, length / speed / (1 - accel), accel)
                self.arrivals.setdefault(b, self.timeline.length())

        order = list(range(start, len(nodes)))
        if path['loops']:
            walk(order + list(range(0, start + 1)) if start else order + [0], True)
            self.playFrames = self.timeline.length()
        elif end_mode.startswith('Go to loop start'):
            self.timeline.segments = self.timeline.intro
            walk(order, False)
            self.timeline.segments = self.timeline.loop
            walk(list(range(loop_from, len(nodes))) + [loop_from], True)
            self.playFrames = self.timeline.length()
        else:
            walk(order, False)
            last = self.timeline.end()
            if end_mode.startswith('Fall'):
                self.timeline.add(FPS, last, (last[0], last[1] + 16 * 20))
                self.notes.append('It falls away at the end, then the preview starts again.')
            self.playFrames = self.timeline.length()
            self.timeline.add(REST_FRAMES, self.timeline.end(), self.timeline.end())
        self.endFrame = self.arrivals.get(len(nodes) - 1, self.playFrames)

        strength = setting_value(controller, 'Sine effect strength')
        if strength:
            vertical = (setting_label(controller, 'Sine effect type') or 'Vertical') == 'Vertical'
            self.sine = (vertical, strength * SINE_UNITS_PER_STRENGTH,
                         setting_value(controller, 'Initial sine angle') * 22.5,
                         setting_value(controller, 'Sine effect speed') * SINE_DEGREES_PER_SPEED)

        if setting_value(controller, 'Event activated'):
            self.notes.append('In the game it waits for its event; the preview runs as if the event is on.')

    def at(self, frame, sprite=None):
        x, y = self.timeline.at(frame)
        if self.sine:
            vertical, amplitude, phase, speed = self.sine
            wobble = amplitude * math.sin(math.radians(phase + frame * speed))
            x, y = (x, y + wobble) if vertical else (x + wobble, y)
        return x, y, 0

    def duration(self, sprite=None):
        return self.playFrames

    def end_frame(self, sprite=None):
        return getattr(self, 'endFrame', 0)


class SwayMotion(Motion):
    """Pivotal Rotation, Swaying (68) - the editor's formula (SpriteImage_ControllerSwaying)."""

    def __init__(self, controller, area):
        super().__init__(controller, area)
        d = controller.spritedata
        self.startOffset = (d[2] & 0xF) * 22.5 + 90
        if (d[4] >> 4) & 1:  # Reversed Movement
            self.startOffset += 180
        self.middle = (d[4] & 0xF) * 22.5
        self.arc = (d[7] >> 4) * 22.5
        self.speed = ((d[7] & 0xF) / 0x800) * 360  # degrees of the swing's phase per frame
        if d[4] & 0x40:
            self.notes.append('Event-activated: the preview shows it swaying as if the event is on.')
        if not self.speed or not self.arc:
            self.notes.append('Its swaying speed or arc is 0, so it doesn\'t sway.')

    def at(self, frame, sprite=None):
        return 0, 0, -self.middle + math.cos(math.radians(self.startOffset - frame * self.speed)) * self.arc * 0.5

    def duration(self, sprite=None):
        # One full swing there and back
        return 360 / self.speed if self.speed and self.arc else 0

    def end_frame(self, sprite=None):
        return self.duration() / 2


class SpinMotion(Motion):
    """Pivotal Rotation, Spinning (69) - the editor's formula (SpriteImage_ControllerSpinning)."""

    RETURN_SPEED = {0: 1.0, 4: 0.5, 8: 0.25}  # "Rotates Back" modes: Fastest/Slow/Slowest (estimates)

    def __init__(self, controller, area):
        super().__init__(controller, area)
        self.read(controller.spritedata)
        mode = controller.spritedata[3] & 0xF
        self.continuous = mode & 3 in (1, 2)
        self.returnSpeed = self.RETURN_SPEED.get(mode, 1.0)
        if mode & 3 == 2:
            self.notes.append('It spins while its event is on; the preview shows it spinning.')
        elif not self.continuous:
            self.notes.append('Event-triggered: the preview turns it through its arc and back, as when the event goes on and off.')

    def read(self, d):
        self.rotation = (d[2] >> 4) * 22.5
        self.arc = (d[2] & 0xF) * 22.5
        reversed_ = (d[4] >> 4) & 1
        value = d[7] & 0xF
        self.speed = SPIN_SPEEDS[value if value <= 7 else 4] / FULL_TURN * 360
        if reversed_:
            self.rotation, self.speed = -self.rotation, -self.speed

    def at(self, frame, sprite=None):
        if self.continuous:
            return 0, 0, -self.rotation - frame * self.speed
        step = abs(self.speed) or 1
        out = self.arc / step
        back = out / self.returnSpeed
        cycle = frame % (out + FPS + back + FPS)
        if cycle < out:
            turned = cycle * step
        elif cycle < out + FPS:
            turned = self.arc
        elif cycle < out + FPS + back:
            turned = self.arc - (cycle - out - FPS) * step * self.returnSpeed
        else:
            turned = 0
        return 0, 0, -self.rotation - math.copysign(turned, self.speed or 1)

    def _timing(self):
        step = abs(self.speed) or 1
        out = self.arc / step
        return out, out / self.returnSpeed

    def duration(self, sprite=None):
        if self.continuous:
            return 360 / abs(self.speed) if self.speed else 0  # one full turn
        out, back = self._timing()
        return out + FPS + back

    def end_frame(self, sprite=None):
        if self.continuous:
            return self.duration() / 2  # half a turn: a full one ends where it started
        return self._timing()[0]


class PathSpinMotion(SpinMotion):
    """Spinning, Path-controlled (118): settings in other places (SpriteImage_ControllerSpinning_Path)."""

    def read(self, d):
        self.rotation = (d[2] >> 4) * 22.5
        self.arc = (d[7] >> 4) * 22.5
        value = d[7] & 0xF
        reversed_ = value > 7
        self.speed = SPIN_SPEEDS[value - 8 if value > 7 else value] / FULL_TURN * 360
        if reversed_:
            self.rotation, self.speed = -self.rotation, -self.speed


class PathPivot(Motion):
    """Path-controlled pivots (116, 118): they rotate, and their pivot follows a path controller."""

    def __init__(self, controller, area):
        super().__init__(controller, area)
        self.rotation = (SwayMotion if controller.type == 116 else PathSpinMotion)(controller, area)
        self.notes = self.rotation.notes
        self.path = None

        path_id = controller.spritedata[11]  # Path Movement ID
        zone = _zone(controller, area)
        mover = next((s for s in area.sprites
                      if s.type == PATH and movement_id(s) == path_id and _zone(s, area) == zone), None)
        if mover is None:
            self.notes.append('No path controller (100) in this zone has Movement ID %d, so only the rotation is shown.' % path_id)
        else:
            self.path = PathMotion(mover, area)
            self.notes += self.path.notes

    def at(self, frame, sprite=None):
        angle = self.rotation.at(frame)[2]
        if self.path is None:
            return 0, 0, angle
        x, y, _ = self.path.at(frame)
        return x, y, angle

    def duration(self, sprite=None):
        return (self.path or self.rotation).duration()

    def end_frame(self, sprite=None):
        return (self.path or self.rotation).end_frame()


class StepSpinMotion(Motion):
    """Rotation, Spinning (214) and its location-triggered version (484)."""

    def __init__(self, controller, area):
        super().__init__(controller, area)
        self.arc = setting_value(controller, 'Controller Spin Arc') * 22.5 or 90
        self.speed = STEP_SPIN_SPEEDS.get(setting_value(controller, 'Speed'), 2.0)
        self.delay = max(FPS // 2, setting_value(controller, 'Delay') * DELAY_FRAMES)
        self.sign = 1 if setting_value(controller, 'Clockwise') else -1
        self.notes.append('It turns when triggered; the preview repeats the turn.')

    def at(self, frame, sprite=None):
        turn = max(1, self.arc / self.speed)
        steps, rest = divmod(frame, turn + self.delay)
        return 0, 0, self.sign * (steps * self.arc + min(rest, turn) / turn * self.arc)

    def duration(self, sprite=None):
        return max(1, self.arc / self.speed)  # one turn


class BoltMotion(Motion):
    """
    Movement Controller - Bolt (238). Each linked object has its own direction, speed
    and distance multiplier; the preview turns the bolt all the way, then lets go.
    """

    def __init__(self, controller, area):
        super().__init__(controller, area)
        self.distance = setting_value(controller, 'Distance') * 16
        self.back = setting_value(controller, 'Return Delay') * DELAY_FRAMES
        self.timelines = {}
        self.notes.append('A player turns the bolt in the game; the preview turns it all the way, then lets go.')

    def timeline(self, sprite):
        key = id(sprite)
        if key not in self.timelines:
            dx, dy = TwoWayMotion.DIRECTIONS.get(setting_label(sprite, 'Direction'), (0, -1))
            distance = self.distance * max(1, setting_value(sprite, 'Distance Multiplier'))
            speed = _label_number(sprite, 'Speed', BOLT_TURN_SPEED)
            timeline = Timeline()
            home, away = (0, 0), (dx * distance, dy * distance)
            travel = distance / speed if distance else 0
            timeline.add(travel, home, away)
            timeline.add(self.back + FPS // 2, away, away)
            timeline.add(travel, away, home)
            timeline.travel = travel
            timeline.played = timeline.length()
            timeline.add(REST_FRAMES, home, home)
            self.timelines[key] = timeline
        return self.timelines[key]

    def at(self, frame, sprite=None):
        if sprite is None or not self.distance:
            return 0, 0, 0
        x, y = self.timeline(sprite).at(frame)
        return x, y, 0

    def duration(self, sprite=None):
        if sprite is None or not self.distance:
            return 0
        return self.timeline(sprite).played

    def end_frame(self, sprite=None):
        if sprite is None or not self.distance:
            return 0
        return self.timeline(sprite).travel


MOTIONS = {PATH: PathMotion, BOLT: BoltMotion, 68: SwayMotion, 69: SpinMotion, 116: PathPivot, 118: PathPivot}
MOTIONS.update({t: TwoWayMotion for t in TWO_WAY})
MOTIONS.update({t: StepSpinMotion for t in STEP_SPIN})


################################################################
# Drawing
################################################################

class _Ghost(QtWidgets.QGraphicsItem):
    """A copy of a sprite's image that the preview moves around."""

    def __init__(self, sprite):
        super().__init__()
        self.sprite = sprite
        self.setZValue(sprite.zValue() + 1)
        self.setFlag(self.ItemIsSelectable, False)
        self.setAcceptedMouseButtons(QtCore.Qt.NoButton)

    def boundingRect(self):
        return self.sprite.boundingRect()

    def paint(self, painter, option, widget=None):
        self.sprite.paint(painter, None, None, True)


class _Marker(_Ghost):
    """A faint copy that stays where the movement starts or ends, outlined and labelled."""

    def __init__(self, sprite, label, color):
        super().__init__(sprite)
        self.label, self.color = label, color
        self.setZValue(sprite.zValue() + 0.5)
        self.setOpacity(0.45)

    def paint(self, painter, option, widget=None):
        painter.save()
        super().paint(painter, option, widget)
        painter.restore()
        rect = self.boundingRect()
        painter.setOpacity(1)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QtGui.QPen(self.color, 2, Qt.DashLine))
        painter.drawRect(rect.adjusted(1, 1, -1, -1))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self.color)
        painter.drawText(rect.adjusted(3, 2, 0, 0), Qt.AlignLeft | Qt.AlignTop, self.label)


def _rotate(x, y, cx, cy, degrees):
    r = math.radians(degrees)
    c, s = math.cos(r), math.sin(r)
    return cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c


class MovementPreview(QtCore.QObject):
    """Runs the preview of one or more groups; stop() removes everything it added."""

    finished = QtCore.pyqtSignal()  # with "Play Once", when every group has played

    def __init__(self, scene, groups, once=False, markers=()):
        super().__init__()
        self.scene = scene
        self.frame = 0.0
        self.once = once
        self.groups = []    # (motion, [(ghost, sprite, origin)], frames to play once)
        self.trails = []
        self.markers = []
        self.faded = []
        scale = globals.TileWidth / 16

        for motion, moved in groups:
            ghosts = []
            for sprite in moved:
                ghost = self._place(_Ghost(sprite), motion, sprite, 0, scale)
                ghosts.append((ghost, sprite, sprite.pos()))
                if 'start' in markers:
                    self.markers.append(self._place(_Marker(sprite, 'Start', START_COLOR), motion, sprite, 0, scale))
                if 'end' in markers:
                    self.markers.append(self._place(_Marker(sprite, 'End', END_COLOR), motion, sprite,
                                                    motion.end_frame(sprite), scale))
                # Opacity 0 rather than hiding, so the sprite stays selected and clickable
                sprite.setOpacity(0)
                self.faded.append(sprite)
            length = max(motion.duration(s) for s in moved)
            self.groups.append((motion, ghosts, length))
            self._addTrail(motion, ghosts[0], scale)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000 // FPS)
        self.timer.timeout.connect(self.step)
        self.timer.start()
        self.step()

    def _place(self, item, motion, sprite, frame, scale):
        """Adds a copy of the sprite to the scene, posed as at a frame of the motion."""
        px, py = motion.pivot
        item.setTransformOriginPoint(px * scale - sprite.x(), py * scale - sprite.y())
        self._pose(item, motion, sprite, sprite.pos(), frame, scale)
        self.scene.addItem(item)
        return item

    @staticmethod
    def _pose(item, motion, sprite, origin, frame, scale):
        dx, dy, angle = motion.at(frame, sprite)
        item.setPos(origin.x() + dx * scale, origin.y() + dy * scale)
        item.setRotation(angle)

    def _addTrail(self, motion, ghost_info, scale):
        """Where the first moved sprite of a group goes, to show the route at a glance."""
        ghost, sprite, origin = ghost_info
        anchor = sprite.mapToScene(sprite.boundingRect().center())  # the ghost may already be turned
        px, py = motion.pivot
        path = QtGui.QPainterPath()
        for frame in range(0, FPS * 20, 2):
            dx, dy, angle = motion.at(frame, sprite)
            x, y = _rotate(anchor.x(), anchor.y(), px * scale, py * scale, angle)
            point = QtCore.QPointF(x + dx * scale, y + dy * scale)
            path.moveTo(point) if frame == 0 else path.lineTo(point)
        trail = QtWidgets.QGraphicsPathItem(path)
        trail.setPen(QtGui.QPen(QtGui.QColor(255, 140, 0, 160), 2, QtCore.Qt.DashLine))
        trail.setZValue(30000)
        self.scene.addItem(trail)
        self.trails.append(trail)

    def step(self):
        scale = globals.TileWidth / 16
        for motion, ghosts, length in self.groups:
            # Played once, a group stays at its last pose until the others finish
            frame = min(self.frame, length) if self.once else self.frame
            for ghost, sprite, origin in ghosts:
                self._pose(ghost, motion, sprite, origin, frame, scale)
        if self.once and self.frame >= max(length for _, _, length in self.groups):
            self.timer.stop()
            # Later, so this works from the first step too (before anyone could connect)
            QtCore.QTimer.singleShot(0, self.finished.emit)
            return
        self.frame += speed()

    def stop(self):
        self.timer.stop()
        items = [g for _, ghosts, _ in self.groups for g, _, _ in ghosts] + self.trails + self.markers
        for item in items:
            try:
                if item.scene() is not None:
                    self.scene.removeItem(item)
            except RuntimeError:
                pass  # already deleted along with the scene's contents
        for sprite in self.faded:
            try:
                sprite.setOpacity(1)
            except RuntimeError:
                pass
        self.groups, self.trails, self.markers, self.faded = [], [], [], []


################################################################
# Starting and stopping
################################################################

_current = None
_kind = None            # 'single' or 'all'
listeners = []          # called with no arguments whenever a preview starts or stops


def _changed():
    for listener in list(listeners):
        listener()


def speed():
    try:
        value = float(setting('MovementPreviewSpeed', DEFAULT_SPEED))
    except (TypeError, ValueError):
        value = DEFAULT_SPEED
    return value if value in SPEEDS else DEFAULT_SPEED


def set_speed(value):
    """Preview speed (1 = game speed); a running preview changes at once."""
    setSetting('MovementPreviewSpeed', value)


def is_running(kind=None):
    return _current is not None and (kind is None or kind == _kind)


# (name, setting, menu text, description)
OPTIONS = (
    ('once', 'MovementPreviewOnce', 'Play Once',
     'Play the movement one time instead of looping; the preview ends when every actor has finished'),
    ('start', 'MovementPreviewShowStart', 'Show Start Position',
     'Keep a faint copy, outlined in green, where each actor starts'),
    ('end', 'MovementPreviewShowEnd', 'Show End Position',
     'Keep a faint copy, outlined in red, where each actor ends (or turns back, for movements that return)'),
)


def option(name):
    key = next(o[1] for o in OPTIONS if o[0] == name)
    return str(setting(key, False)).lower() in ('true', '1')


def set_option(name, value):
    """Changes a preview option; a running preview starts again with it."""
    key = next(o[1] for o in OPTIONS if o[0] == name)
    setSetting(key, bool(value))
    if _current is not None and _restart is not None:
        _restart()


def options_menu(parent, title='Preview Options'):
    """A menu of the preview options (the same settings wherever it is shown)."""
    menu = QtWidgets.QMenu(title, parent)
    menu.setToolTipsVisible(True)
    actions = {}
    for name, _, text, tip in OPTIONS:
        act = menu.addAction(text)
        act.setCheckable(True)
        act.setToolTip(tip)
        act.setStatusTip(tip)
        act.toggled.connect(lambda checked, n=name: set_option(n, checked))
        actions[name] = act

    def sync():
        for name, act in actions.items():
            act.blockSignals(True)
            act.setChecked(option(name))
            act.blockSignals(False)

    menu.aboutToShow.connect(sync)
    sync()
    return menu


_restart = None  # starts the running preview again (after an option changes)


def _show(groups, label, kind, restart):
    global _current, _kind, _restart
    markers = [name for name in ('start', 'end') if option(name)]
    preview = MovementPreview(globals.mainWindow.scene, groups, option('once'), markers)
    preview.finished.connect(lambda: _finished(preview))
    _current, _kind, _restart = preview, kind, restart
    _changed()
    notes = sorted(set(n for motion, _ in groups for n in motion.notes))
    message = label + ' ' + ' '.join(notes) if notes else label
    globals.mainWindow.statusBar().showMessage(message, 15000)


def _finished(preview):
    """A "Play Once" preview has played: it ends, and the real actors show again."""
    if preview is _current:
        stop()
        globals.mainWindow.statusBar().showMessage('Movement preview finished.', 5000)


def start(sprite):
    """
    Starts previewing the group the sprite belongs to. Returns an error message,
    or None when the preview started.
    """
    stop()
    area = globals.Area
    controller, moved, message = find_group(area, sprite)
    if controller is None:
        return message

    motion = MOTIONS[controller.type](controller, area)
    _show([(motion, moved)], 'Previewing %d actor(s) moved by %s.' % (len(moved), name_of(controller)), 'single',
          lambda: start(sprite))
    return None


def start_all():
    """
    Previews every movement controller in the open area at once. Returns an error
    message, or None when the preview started.
    """
    stop()
    area = globals.Area
    groups = []
    for controller in area.sprites:
        if controller.type not in MOTIONS:
            continue
        found, moved, _ = find_group(area, controller)
        if found is controller:
            groups.append((MOTIONS[controller.type](controller, area), moved))
    if not groups:
        return 'No movement controller in this area has actors attached to it.'

    _show(groups, 'Previewing %d movement controller(s).' % len(groups), 'all', start_all)
    return None


def stop(kind=None):
    """Stops the running preview (only if it is of this kind, when one is given)."""
    global _current, _kind, _restart
    if _current is not None and (kind is None or kind == _kind):
        preview, _current, _kind, _restart = _current, None, None, None
        preview.stop()
        _changed()
