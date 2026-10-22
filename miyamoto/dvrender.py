#!/usr/bin/python
# -*- coding: latin-1 -*-

# Miyamoto! Level Editor - New Super Mario Bros. U Level Editor
# Copyright (C) 2009-2021 Treeki, Tempus, angelsl, JasonP27, Kinnay,
# MalStar1000, RoadrunnerWMC, MrRean, Grop, AboodXD, Gota7, John10v10,
# mrbengtsson

# This file is part of Miyamoto!.

# Miyamoto! is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Miyamoto! is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with Miyamoto!.  If not, see <http://www.gnu.org/licenses/>.

"""
Rough preview renders of Deluxe background ("distant view") models.

A background is a 3D scene (Model/dv_<name>.Nin_NX_NVN.szs, holding output.bfres). This
reads the meshes and their main texture out of the BFRES and draws them with QPainter:
each triangle is filled with its texture, back to front, unlit. No shaders, lighting,
fog or animations, so it only gives an idea of what the zone's background looks like.

The BFRES layout follows Switch Toolbox's BfresLibrary (Switch, version 8).
"""

import math
import os
import re
import struct
import zlib

from PyQt5 import QtCore, QtGui
from PyQt5.QtCore import Qt

import SarcLib

from . import yaz0
from .tileset import loadBNTXFromBFRES, loadTexFromBNTX


class DistantViewMaterial:
    """
    What a mesh's material says about drawing it
    """

    def __init__(self, name, textures, renderInfo, params):
        self.name = name
        self.textures = textures      # [(sampler name, texture name)]
        self.renderInfo = renderInfo  # {name: [values]}, e.g. blend settings and priority
        self.params = params          # {shader parameter name: (floats)}
        self.anim = None              # MaterialAnim or None

    def info(self, name, default=None):
        """
        The first value of a render info entry
        """
        values = self.renderInfo.get(name)
        return values[0] if values else default

    def texture(self, prefix):
        """
        The first texture whose name starts with prefix (case-insensitive), or None
        """
        for _, texture in self.textures:
            if texture.lower().startswith(prefix):
                return texture
        return None


class DistantViewMesh:
    """
    One drawable piece of the model: its vertices, triangles and colour texture name
    """

    def __init__(self, name, positions, uvs, triangles, texture, normals=None, colors=None, material=None):
        self.name = name
        self.positions = positions  # [(x, y, z)]
        self.uvs = uvs              # [(u, v)] or None
        self.triangles = triangles  # [(a, b, c)]
        self.texture = texture      # texture name or None
        self.normals = normals      # [(x, y, z)] or None
        self.colors = colors        # [(r, g, b, a)] or None
        self.material = material    # DistantViewMaterial or None
        self.skeleton = None        # Skeleton the mesh's bone belongs to
        self.boneIndex = 0          # the bone the whole mesh is attached to


# Sizes of the array entries (version 8 layout)
_FMDL_SIZE = 0x78
_FSHP_SIZE = 0x70
_FMAT_SIZE = 0xB8


def _offset(b, off):
    return struct.unpack_from('<q', b, off)[0]


def _string(b, off):
    if not off:
        return ''
    n = struct.unpack_from('<H', b, off)[0]
    return b[off + 2:off + 2 + n].decode('utf-8', 'replace')


def _dictNames(b, off):
    """
    The keys of a ResDic, in order
    """
    if not off:
        return []

    count = struct.unpack_from('<i', b, off + 4)[0]
    return [_string(b, _offset(b, off + 8 + i * 16 + 8)) for i in range(1, count + 1)]


# Switch vertex attribute formats: high byte = number type, low byte = component layout
_LAYOUTS = {
    0x02: (1, 1), 0x09: (2, 1), 0x0B: (4, 1),
    0x0A: (1, 2), 0x12: (2, 2), 0x15: (4, 2),
    0x16: (1, 4), 0x17: (2, 4), 0x18: (3, 4), 0x19: (4, 4),
}
_STRUCT_CHARS = {
    (1, 1): 'B', (1, 2): 'H', (1, 3): 'I',  # unorm
    (2, 1): 'b', (2, 2): 'h', (2, 3): 'i',  # snorm
    (3, 1): 'B', (3, 2): 'H', (3, 3): 'I',  # uint
    (4, 1): 'b', (4, 2): 'h', (4, 3): 'i',  # sint
    (5, 2): 'e', (5, 3): 'f',               # float
}


def _readAttribute(data, stride, offset, fmt, count):
    """
    Decodes one vertex attribute into a list of float tuples, or None if the format
    isn't supported
    """
    kind, layout = fmt >> 8, fmt & 0xFF

    # 10_10_10_2 signed (normals): three signed 10-bit values in one 32-bit word
    if fmt == 0x020E:
        out = []
        for i in range(count):
            word = struct.unpack_from('<I', data, i * stride + offset)[0]
            values = []
            for shift in (0, 10, 20):
                v = (word >> shift) & 0x3FF
                if v & 0x200:
                    v -= 0x400
                values.append(max(-1.0, v / 511))
            out.append(tuple(values))
        return out

    if layout not in _LAYOUTS:
        return None

    comps, size = _LAYOUTS[layout]
    char = _STRUCT_CHARS.get((kind, {1: 1, 2: 2, 4: 3}[size]))
    if char is None:
        return None

    unpacker = struct.Struct('<' + char * comps)
    if kind == 1:
        scale = 1 / ((1 << (size * 8)) - 1)
    elif kind == 2:
        scale = 1 / ((1 << (size * 8 - 1)) - 1)
    else:
        scale = None

    out = []
    for i in range(count):
        values = unpacker.unpack_from(data, i * stride + offset)
        if scale is not None:
            values = tuple(max(-1.0, v * scale) for v in values)
        out.append(values)

    return out


def _readVertexBuffer(b, fvtx, bufferBase):
    """
    The named attributes of an FVTX, decoded
    """
    attribArray = _offset(b, fvtx + 0x10)
    sizeArray = _offset(b, fvtx + 0x38)
    strideArray = _offset(b, fvtx + 0x40)
    dataOffset, numAttrib, numBuffer = struct.unpack_from('<iBB', b, fvtx + 0x50)
    vertexCount = struct.unpack_from('<I', b, fvtx + 0x58)[0]

    # The buffers follow each other, each aligned to 8 bytes
    buffers = []
    pos = bufferBase + dataOffset
    for i in range(numBuffer):
        pos = (pos + 7) & ~7
        size = struct.unpack_from('<I', b, sizeArray + i * 16)[0]
        stride = struct.unpack_from('<I', b, strideArray + i * 16)[0]
        buffers.append((b[pos:pos + size], stride))
        pos += size

    attributes = {}
    for i in range(numAttrib):
        attrib = attribArray + i * 0x10
        name = _string(b, _offset(b, attrib))
        fmt = struct.unpack_from('>H', b, attrib + 8)[0]
        offset, bufferIndex = struct.unpack_from('<HH', b, attrib + 0xC)
        if bufferIndex >= len(buffers):
            continue

        data, stride = buffers[bufferIndex]
        values = _readAttribute(data, stride, offset, fmt, vertexCount)
        if values is not None:
            attributes[name] = values

    return attributes


def _readTriangles(b, mesh, bufferBase):
    """
    The triangles of the first (most detailed) mesh of a shape
    """
    faceOffset, primitive, indexFormat, indexCount, firstVertex = struct.unpack_from('<IIIII', b, mesh + 0x20)
    char = {0: 'B', 1: 'H', 2: 'I'}.get(indexFormat)
    if char is None or primitive not in (3, 4):
        return []

    indices = struct.unpack_from('<%d%s' % (indexCount, char), b, bufferBase + faceOffset)
    indices = [i + firstVertex for i in indices]

    if primitive == 3:  # triangle list
        return [tuple(indices[i:i + 3]) for i in range(0, indexCount - 2, 3)]

    # triangle strip
    tris = []
    for i in range(indexCount - 2):
        a, c, d = indices[i:i + 3]
        tris.append((a, c, d) if i % 2 == 0 else (c, a, d))
    return tris


def _colorTexture(b, fmat):
    """
    The name of the texture that most likely holds a material's colours
    """
    numTextures = b[fmat + 0xA8]
    if not numTextures:
        return None

    nameArray = _offset(b, fmat + 0x38)
    textures = [_string(b, _offset(b, nameArray + i * 8)) for i in range(numTextures)]
    samplers = _dictNames(b, _offset(b, fmat + 0x50))

    # The first "_aN" sampler that isn't a helper texture (light map, distortion map...)
    helpers = ('lm_', 'ind', 'dof')
    for sampler, texture in zip(samplers, textures):
        if sampler.startswith('_a') and not texture.lower().startswith(helpers) \
                and '_ind' not in texture.lower():
            return texture

    for texture in textures:
        if not texture.lower().startswith(helpers + ('hikari',)) and '_ind' not in texture.lower():
            return texture

    return textures[0]


def _readMaterial(b, fmat):
    """
    A material's textures, render info and shader parameters
    """
    name = _string(b, _offset(b, fmat + 0x10))

    numTextures = b[fmat + 0xA8]
    nameArray = _offset(b, fmat + 0x38)
    textures = [_string(b, _offset(b, nameArray + i * 8)) for i in range(numTextures)]
    samplers = _dictNames(b, _offset(b, fmat + 0x50))

    # Render info entries: name, data offset, count, type (0 int, 1 float, 2 string)
    renderInfo = {}
    infoArray = _offset(b, fmat + 0x18)
    for i in range(struct.unpack_from('<H', b, fmat + 0xA6)[0]):
        entry = infoArray + i * 0x18
        dataOffset = _offset(b, entry + 8)
        count, kind = struct.unpack_from('<HB', b, entry + 0x10)
        if kind == 2:
            values = [_string(b, _offset(b, dataOffset + j * 8)) for j in range(count)]
        else:
            values = list(struct.unpack_from('<%d%s' % (count, 'f' if kind == 1 else 'i'), b, dataOffset))
        renderInfo[_string(b, _offset(b, entry))] = values

    # Shader parameters: their values are in one data block, read as floats
    params = {}
    paramArray = _offset(b, fmat + 0x58)
    source = _offset(b, fmat + 0x68)
    for i in range(struct.unpack_from('<H', b, fmat + 0xAA)[0]):
        entry = paramArray + i * 0x20
        size, dataOffset = struct.unpack_from('<BH', b, entry + 0x11)
        if size and size % 4 == 0:
            params[_string(b, _offset(b, entry + 8))] = struct.unpack_from('<%df' % (size // 4), b, source + dataOffset)

    return DistantViewMaterial(name, list(zip(samplers, textures)), renderInfo, params)


class AnimCurve:
    """
    One animated value over time (BFRES AnimCurve)
    """

    def __init__(self, b, curve):
        frameArray, keyArray = _offset(b, curve), _offset(b, curve + 8)
        flags, numKeys, self.target = struct.unpack_from('<HHI', b, curve + 0x10)
        self.start, self.end, self.scale, self.offset, self.delta = struct.unpack_from('<5f', b, curve + 0x18)

        frameType, keyType, self.curveType = flags & 3, (flags >> 2) & 3, (flags >> 4) & 7
        if frameType == 0:
            self.frames = list(struct.unpack_from('<%df' % numKeys, b, frameArray))
        elif frameType == 1:  # fixed point, 5 fraction bits
            self.frames = [f / 32 for f in struct.unpack_from('<%dh' % numKeys, b, frameArray)]
        else:
            self.frames = list(struct.unpack_from('<%dB' % numKeys, b, frameArray))

        # Values per key: cubic 4 coefficients, linear 2, the rest 1
        per = {0: 4, 1: 2}.get(self.curveType, 1)
        stepInt = self.curveType in (4, 6)
        char = ('I' if stepInt else 'f', 'h', 'b')[keyType]
        flat = struct.unpack_from('<%d%s' % (numKeys * per, char), b, keyArray)
        self.keys = [flat[i * per:(i + 1) * per] for i in range(numKeys)]

    def value(self, frame):
        frames, keys = self.frames, self.keys
        if not keys:
            return self.offset

        if self.curveType in (2, 5, 7):  # baked: one key per frame
            index = int(min(max(frame - self.start, 0), len(keys) - 1))
            return keys[index][0] * self.scale + self.offset

        # The segment holding the frame, and how far into it the frame is
        index = 0
        while index + 1 < len(frames) and frames[index + 1] <= frame:
            index += 1
        key = keys[index]
        if self.curveType >= 4:  # step
            return key[0] * self.scale + self.offset

        # The last key's segment runs to the curve's end frame
        segmentEnd = frames[index + 1] if index + 1 < len(frames) else self.end
        span = segmentEnd - frames[index]
        t = min(max((frame - frames[index]) / span, 0.0), 1.0) if span > 0 else 0.0

        if self.curveType == 0:  # cubic
            v = ((key[3] * t + key[2]) * t + key[1]) * t + key[0]
        else:  # linear
            v = key[0] + key[1] * t
        return v * self.scale + self.offset


class MaterialAnim:
    """
    A material's animated shader parameters: per parameter, values (constants) and
    curves keyed by their byte offset in the parameter
    """

    def __init__(self, frameCount, loop):
        self.frameCount = frameCount
        self.loop = loop
        self.params = {}  # {name: [(byte offset, constant float or AnimCurve)]}

    def apply(self, params, frame):
        """
        The material's shader parameters at a frame
        """
        if self.loop and self.frameCount > 0:
            frame %= self.frameCount
        else:
            frame = min(frame, self.frameCount)

        out = dict(params)
        for name, targets in self.params.items():
            values = list(out.get(name, ()))
            for offset, source in targets:
                index = offset // 4
                if index < len(values):
                    values[index] = source if isinstance(source, float) else source.value(frame)
            out[name] = tuple(values)
        return out


def _readMaterialAnims(b):
    """
    The shader parameter animations of every material, by material name (the first
    animation that animates it)
    """
    anims = {}
    animArray = _offset(b, 0x48)
    for a in range(len(_dictNames(b, _offset(b, 0x50)))):
        fmaa = animArray + a * 0x78
        if b[fmaa:fmaa + 4] != b'FMAA':
            continue

        flags, _, numMaterials, _, frameCount = struct.unpack_from('<HHHHi', b, fmaa + 0x60)
        materialArray = _offset(b, fmaa + 0x30)
        for m in range(numMaterials):
            data = materialArray + m * 0x40
            name = _string(b, _offset(b, data))
            infoArray, _, curveArray, constArray = (_offset(b, data + 8 + i * 8) for i in range(4))
            numInfos = struct.unpack_from('<H', b, data + 0x32)[0]
            if name in anims or not numInfos:
                continue

            anim = MaterialAnim(frameCount, bool(flags & 4))
            for i in range(numInfos):
                info = infoArray + i * 0x18
                param = _string(b, _offset(b, info))
                beginCurve, numFloatCurves, numIntCurves, beginConst, numConsts = struct.unpack_from('<5H', b, info + 8)

                targets = []
                for c in range(beginConst, beginConst + numConsts):
                    offset, value = struct.unpack_from('<If', b, constArray + c * 8)
                    targets.append((offset, value))
                for c in range(beginCurve, beginCurve + numFloatCurves + numIntCurves):
                    curve = AnimCurve(b, curveArray + c * 0x30)
                    targets.append((curve.target, curve))
                anim.params[param] = targets

            anims[name] = anim

    return anims


class Skeleton:
    """
    A model's bones (rest pose) and its skeletal animation, if any. Meshes here are
    each attached whole to one bone (no skinning), so a bone's world matrix places its
    meshes.
    """

    def __init__(self, bones):
        self.bones = bones  # [(name, parent index, scale, rotation quaternion xyzw, translation)]
        self.anim = None    # SkeletalAnim or None

    def matrices(self, frame=0.0):
        """
        Every bone's world matrix (QMatrix4x4) at an animation frame (60 per second)
        """
        animated = self.anim.pose(frame) if self.anim is not None else {}
        world = []
        for name, parent, scale, rotation, translation in self.bones:
            local = QtGui.QMatrix4x4()
            if name in animated:
                scale, euler, translation = animated[name]
                local.translate(*translation)
                local.rotate(math.degrees(euler[2]), 0, 0, 1)
                local.rotate(math.degrees(euler[1]), 0, 1, 0)
                local.rotate(math.degrees(euler[0]), 1, 0, 0)
            else:
                local.translate(*translation)
                x, y, z, w = rotation
                local.rotate(QtGui.QQuaternion(w, x, y, z))
            local.scale(*scale)

            world.append(world[parent] * local if 0 <= parent < len(world) else local)
        return world


class SkeletalAnim:
    """
    Bones' scale, rotation (Euler XYZ, radians) and translation over time
    """

    def __init__(self, frameCount, loop):
        self.frameCount = frameCount
        self.loop = loop
        self.bones = {}  # {bone name: (base values [11 floats], [(byte offset, AnimCurve)])}

    def pose(self, frame):
        """
        {bone name: (scale, euler rotation, translation)} at a frame
        """
        if self.loop and self.frameCount > 0:
            frame %= self.frameCount
        else:
            frame = min(frame, self.frameCount)

        out = {}
        for name, (base, curves) in self.bones.items():
            # Values in BoneAnimData order: scale (0x04), translation (0x10), rotation (0x20)
            values = list(base)
            for offset, curve in curves:
                index = {0x04: 0, 0x08: 1, 0x0C: 2, 0x10: 3, 0x14: 4, 0x18: 5,
                         0x20: 6, 0x24: 7, 0x28: 8, 0x2C: 9}.get(offset)
                if index is not None:
                    values[index] = curve.value(frame)
            out[name] = (values[0:3], values[6:9], values[3:6])
        return out


def _readSkeleton(b, fskl):
    """
    The bones of an FSKL (version 8 layout)
    """
    bones = []
    boneArray = _offset(b, fskl + 0x18)
    for i in range(struct.unpack_from('<H', b, fskl + 0x4C)[0]):
        bone = boneArray + i * 0x60
        parent = struct.unpack_from('<h', b, bone + 0x2A)[0]
        bones.append((
            _string(b, _offset(b, bone)), parent,
            struct.unpack_from('<3f', b, bone + 0x38),
            struct.unpack_from('<4f', b, bone + 0x44),
            struct.unpack_from('<3f', b, bone + 0x54),
        ))
    return Skeleton(bones)


def _readSkeletalAnim(b, skeleton):
    """
    The first skeletal animation (FSKA) of the file, for the skeleton's bones
    """
    if not _dictNames(b, _offset(b, 0x40)):
        return None

    fska = _offset(b, 0x38)
    if b[fska:fska + 4] != b'FSKA':
        return None

    flags, frameCount = struct.unpack_from('<Ii', b, fska + 0x48)
    numBoneAnims = struct.unpack_from('<H', b, fska + 0x58)[0]
    if not flags & 0x1000:
        return None  # Quaternion rotation curves: not used by these models

    rest = {name: (scale, translation) for name, _, scale, _, translation in skeleton.bones}
    anim = SkeletalAnim(frameCount, bool(flags & 4))
    boneAnimArray = _offset(b, fska + 0x30)
    for i in range(numBoneAnims):
        entry = boneAnimArray + i * 0x28
        name = _string(b, _offset(b, entry))
        curveArray, baseData = _offset(b, entry + 8), _offset(b, entry + 0x10)
        animFlags, _, _, numCurves = struct.unpack_from('<IBBB', b, entry + 0x18)
        if name not in rest:
            continue

        # The base pose: whatever's stored, else the bone's rest scale/translation
        scale, translation = rest[name]
        base = list(scale) + list(translation) + [0.0, 0.0, 0.0, 0.0]
        pos = baseData
        if animFlags & 0x08:
            base[0:3] = struct.unpack_from('<3f', b, pos)
            pos += 12
        if animFlags & 0x10:
            base[6:10] = struct.unpack_from('<4f', b, pos)
            pos += 16
        if animFlags & 0x20:
            base[3:6] = struct.unpack_from('<3f', b, pos)

        curves = [AnimCurve(b, curveArray + c * 0x30) for c in range(numCurves)]
        anim.bones[name] = (base, [(curve.target, curve) for curve in curves])

    return anim


def parseBFRES(b):
    """
    Reads the meshes of every model in a Switch BFRES
    """
    if b[:4] != b'FRES':
        raise ValueError('Not a BFRES file')

    bufferInfo = _offset(b, 0x90)
    bufferBase = _offset(b, bufferInfo + 8) if bufferInfo else 0

    modelArray = _offset(b, 0x28)
    numModels = len(_dictNames(b, _offset(b, 0x30)))

    meshes = []
    for m in range(numModels):
        fmdl = modelArray + m * _FMDL_SIZE
        shapeArray = _offset(b, fmdl + 0x30)
        materialArray = _offset(b, fmdl + 0x40)
        numShapes, numMaterials = struct.unpack_from('<HH', b, fmdl + 0x6A)

        textures = [_colorTexture(b, materialArray + i * _FMAT_SIZE) for i in range(numMaterials)]
        materials = [_readMaterial(b, materialArray + i * _FMAT_SIZE) for i in range(numMaterials)]
        anims = _readMaterialAnims(b)
        for material in materials:
            material.anim = anims.get(material.name)

        skeleton = _readSkeleton(b, _offset(b, fmdl + 0x20))
        skeleton.anim = _readSkeletalAnim(b, skeleton)

        vertexCache = {}
        for s in range(numShapes):
            fshp = shapeArray + s * _FSHP_SIZE
            name = _string(b, _offset(b, fshp + 0x10))
            fvtx = _offset(b, fshp + 0x18)
            meshArray = _offset(b, fshp + 0x20)
            materialIndex, boneIndex = struct.unpack_from('<HH', b, fshp + 0x5E)
            numMesh = b[fshp + 0x67]
            if not numMesh:
                continue

            if fvtx not in vertexCache:
                vertexCache[fvtx] = _readVertexBuffer(b, fvtx, bufferBase)
            attributes = vertexCache[fvtx]

            positions = attributes.get('_p0')
            if not positions:
                continue

            meshes.append(DistantViewMesh(
                name,
                [p[:3] for p in positions],
                attributes.get('_u0'),
                _readTriangles(b, meshArray, bufferBase),
                textures[materialIndex] if materialIndex < len(textures) else None,
                attributes.get('_n0'),
                attributes.get('_c0'),
                materials[materialIndex] if materialIndex < len(materials) else None,
            ))
            meshes[-1].skeleton = skeleton
            meshes[-1].boneIndex = boneIndex if boneIndex < len(skeleton.bones) else 0

    return meshes


def parseCameraParams(data):
    """
    Reads a dv_*.camera file: a list of (u32 name length, name, u32 value size, value)
    """
    params = {}
    pos = 0
    while pos + 4 <= len(data):
        length = struct.unpack_from('<I', data, pos)[0]
        name = data[pos + 4:pos + 4 + length].decode('ascii', 'replace')
        pos += 4 + length
        size = struct.unpack_from('<I', data, pos)[0]
        value = data[pos + 4:pos + 4 + size]
        pos += 4 + size

        if name == 'mTypeDirY':
            params[name] = struct.unpack('<I', value)[0]
        elif size % 4 == 0 and size:
            floats = struct.unpack('<%df' % (size // 4), value)
            params[name] = floats if len(floats) > 1 else floats[0]

    return params


def _crc(name):
    return zlib.crc32(name.encode())


def _parseAAMP(d):
    """
    An AAMP parameter archive (little endian, version 2) as nested dicts keyed by the
    names' CRC32: {'objs': {crc: {crc: value}}, 'lists': {crc: list}}
    """
    def value(pos, kind):
        if kind == 0:
            return bool(struct.unpack_from('<I', d, pos)[0])
        if kind == 1:
            return struct.unpack_from('<f', d, pos)[0]
        if kind == 2:
            return struct.unpack_from('<i', d, pos)[0]
        if kind in (3, 4, 5, 6):
            return struct.unpack_from('<%df' % {3: 2, 4: 3, 5: 4, 6: 4}[kind], d, pos)
        if kind in (7, 8, 13, 14, 20):
            return d[pos:d.index(b'\0', pos)].decode('utf-8', 'replace')
        return None

    def readList(pos):
        _, listsOffset, numLists, objsOffset, numObjs = struct.unpack_from('<IHHHH', d, pos)
        objs = {}
        for i in range(numObjs):
            obj = pos + objsOffset * 4 + i * 8
            crc, paramsOffset, numParams = struct.unpack_from('<IHH', d, obj)
            params = {}
            for j in range(numParams):
                param = obj + paramsOffset * 4 + j * 8
                paramCrc, word = struct.unpack_from('<II', d, param)
                params[paramCrc] = value(param + (word & 0xFFFFFF) * 4, word >> 24)
            objs[crc] = params
        lists = {}
        for i in range(numLists):
            child = pos + listsOffset * 4 + i * 12
            lists[struct.unpack_from('<I', d, child)[0]] = readList(child)
        return {'objs': objs, 'lists': lists}

    return readList(0x30 + struct.unpack_from('<I', d, 0x14)[0])


# Environment packs, by path: {file name: bytes}
_envPacks = {}

# Light map size (the models' own placeholders are 16 or 32 pixels)
_LIGHTMAP_SIZE = 32


def _envPack(path):
    if path not in _envPacks:
        data = open(path, 'rb').read()
        if data[:4] == b'Yaz0':
            data = yaz0.decompressFASTYZ(data)
        arc = SarcLib.SARC_Archive()
        arc.load(data)
        _envPacks[path] = {c.name: bytes(c.data) for c in arc.contents if isinstance(c, SarcLib.File)}
    return _envPacks[path]


def loadEnvironmentLightmaps(romfs, name):
    """
    The light maps (lm_01m, lm_02m...) the game generates for a background from its
    lighting environment, as QImages by name. The game doesn't use the placeholder
    light maps stored in the models; it builds them from the environment's lights:
    each pixel is a surface direction (a sphere map), lit by the lights listed in the
    background's .bagllmap with the colours and directions from its .baglenv.
    Returns {} if the files aren't found.
    """
    envset = os.path.join(romfs, 'DistantView', 'dv_%s.envset' % name)
    packPath = os.path.join(romfs, 'Env', 'env_pack.szs')
    if not os.path.isfile(envset) or not os.path.isfile(packPath):
        return {}

    with open(envset, encoding='utf-8', errors='replace') as f:
        names = re.findall(r'"([^"]*)"', f.read())
    if len(names) < 8:
        return {}

    pack = _envPack(packPath)
    envData, mapData = pack.get(names[5] + '.baglenv'), pack.get(names[7] + '.bagllmap')
    if envData is None or mapData is None:
        return {}

    env, maps = _parseAAMP(envData), _parseAAMP(mapData)

    # The environment's lights by name
    lights = {}
    for kind in ('DirectionalLight', 'AmbientLight', 'HemisphereLight'):
        for obj in env['lists'].get(_crc(kind), {'objs': {}})['objs'].values():
            if obj.get(_crc('enable'), True) and obj.get(_crc('name')):
                lights[obj[_crc('name')]] = (kind, obj)

    out = {}
    for lightmap in maps['lists'].values():
        header = next(iter(lightmap['objs'].values()), {})
        mapName = header.get(_crc('name'))
        entries = next(iter(lightmap['lists'].values()), {'objs': {}})['objs'].values()
        if mapName:
            out[mapName] = _bakeLightmap(entries, lights)
    return out


def _bakeLightmap(entries, lights):
    """
    Renders a light map: a sphere map of the summed light for every surface direction
    """
    contributions = []
    for entry in entries:
        light = lights.get(entry.get(_crc('name')))
        effect = entry.get(_crc('effect'), 1.0) or 0.0
        if light is None or not effect:
            continue

        kind, obj = light
        intensity = obj.get(_crc('Intensity'), 1.0)
        color = obj.get(_crc('DiffuseColor')) or obj.get(_crc('Color')) or (1.0, 1.0, 1.0, 1.0)
        color = tuple(c * intensity * effect for c in color[:3])
        backside = obj.get(0xC19C6FD4)  # the colour of the unlit side
        backside = tuple(c * effect for c in backside[:3]) if backside else (0.0, 0.0, 0.0)
        direction = obj.get(_crc('Direction'), (0.0, -1.0, 0.0))
        length = math.sqrt(sum(c * c for c in direction)) or 1.0
        toLight = tuple(-c / length for c in direction)
        lut = entry.get(_crc('lut_name'), 'Lambert')
        power = entry.get(_crc('pow'), 1.0) or 1.0
        contributions.append((kind, color, backside, toLight, lut, power))

    size = _LIGHTMAP_SIZE
    image = QtGui.QImage(size, size, QtGui.QImage.Format_RGBA8888)
    for py in range(size):
        for px in range(size):
            # The direction this pixel stands for (as the shader looks it up)
            nx = (px + 0.5) / size * 2 - 1
            ny = 1 - (py + 0.5) / size * 2
            nz = math.sqrt(max(0.0, 1 - nx * nx - ny * ny))

            rgb = [0.0, 0.0, 0.0]
            for kind, color, backside, toLight, lut, power in contributions:
                if kind == 'AmbientLight':
                    f = 1.0
                else:
                    t = nx * toLight[0] + ny * toLight[1] + nz * toLight[2]
                    f = t * 0.5 + 0.5 if lut == 'Half-Lambert' else max(t, 0.0)
                    f **= power
                for i in range(3):
                    rgb[i] += color[i] * f + (backside[i] * (1 - f) if lut == 'Half-Lambert' else 0.0)

            image.setPixelColor(px, py, QtGui.QColor(*(min(255, int(c * 255)) for c in rgb), 255))
    return image


def loadDistantView(path):
    """
    Reads a dv_*.szs: returns (meshes, {texture name: QImage}, camera parameters)
    """
    with open(path, 'rb') as f:
        data = f.read()

    if data[:4] == b'Yaz0':
        data = yaz0.decompressFASTYZ(data)

    arc = SarcLib.SARC_Archive()
    arc.load(data)

    bfres = None
    camera = {}
    for item in arc.contents:
        if not isinstance(item, SarcLib.File):
            continue
        if item.name.endswith('.bfres') and bfres is None:
            bfres = bytes(item.data)
        elif item.name.endswith('.camera'):
            camera = parseCameraParams(bytes(item.data))

    if bfres is None:
        raise ValueError('No BFRES found in %s' % path)

    meshes = parseBFRES(bfres)

    # Only decode the textures the meshes use: decoding is slow without the Cython extensions
    textures = {}
    bntx = loadBNTXFromBFRES(bfres)
    used = {m.texture for m in meshes if m.texture}
    for m in meshes:
        if m.material is not None:
            used.update(texture for _, texture in m.material.textures if texture)

    for name in used:
        try:
            textures[name] = loadTexFromBNTX(bntx, name)
        except Exception:
            pass

    # Replace the models' placeholder light maps with the ones the game would generate
    # (the background's files live in <romfs>/Model, its lighting in <romfs>/Env)
    base = os.path.basename(path)
    if base.startswith('dv_'):
        romfs = os.path.dirname(os.path.dirname(os.path.abspath(path)))
        try:
            lightmaps = loadEnvironmentLightmaps(romfs, base[3:].split('.')[0])
        except Exception:
            lightmaps = {}
        for name, image in lightmaps.items():
            if name in textures:
                textures[name] = image

    return meshes, textures, camera


# The game's distant view camera, as reimplemented by Miyamoto-Next
# (ModelStuff-next: DistantViewMgr / DVCameraParam, Miyamoto-Next: AreaItem):
# a 20 degree perspective camera that follows the level screen, with the model fixed
# in the zone. At zoom 1 a screen is 398.22 x 224 level units.
_FOV_Y = math.radians(20)
_NEAR = 100.0
_SCREEN_W = 398.22222222222222
_SCREEN_H = 224.0

# Zone zoom multipliers by camera mode and zoom level
_ZOOM_A = (1.0, 1.0, 1.0, 1.4285715, 1.3571428, 1.2142857, 1.2142857, 1.2142857, 0.5, 1.2142857, 1.2142857, 1.4285715)
_ZOOM_B = (1.0, 1.0, 1.0, 1.3571428, 1.3571428, 1.3571428, 1.2142857, 1.2142857, 1.2142857)
_ZOOM_C = (1.0, 1.3571428, 1.7142857, 2.0, 1.2142857, 1.4285715, 1.1428572, 2.0, 0.5, 0.75)


def zoneBgZoom(zoneWidth, zoneHeight, camMode, camZoom):
    """
    How far the background is zoomed out for a zone (1 = one normal screen)
    """
    if camMode in (0, 1, 6, 7):
        table = _ZOOM_A
    elif camMode == 2:
        table = _ZOOM_B
    else:
        table = _ZOOM_C

    mult = table[camZoom] if 0 <= camZoom < len(table) else 1.0
    return min(zoneWidth / _SCREEN_W, zoneHeight / _SCREEN_H, 2.0, mult)


def _opacity(image):
    """
    How much of a texture is opaque, 0 to 1 (cut-out leaves count for less)
    """
    small = image.scaled(16, 16, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    total = sum(QtGui.qAlpha(small.pixel(x, y)) for y in range(16) for x in range(16))
    return total / (255 * 256)


# Grid used to find which scenery is actually visible on a screen
_DEPTH_GRID_W, _DEPTH_GRID_H = 64, 36

# Textures less opaque than this (mostly cut-out) don't hide what's behind them
_MIN_OPACITY = 0.3


def _mainDepth(meshes, triangles, fills, textures, cameraZ, modelZ, screenW, screenH):
    """
    The distance from the camera of the scenery you mostly see on a screen centred on
    the model: a coarse grid over the screen takes the depth of the nearest (mostly
    opaque, not glowing) triangle covering each cell, and this is the median of those
    """
    opacity = {name: _opacity(tex) for name, tex in textures.items()}
    cellW, cellH = screenW / _DEPTH_GRID_W, screenH / _DEPTH_GRID_H
    grid = {}

    for _, index, a, b, c in reversed(triangles):  # nearest first
        mesh = meshes[index]
        if fills[index][3] or opacity.get(mesh.texture, 1.0) < _MIN_OPACITY:
            continue

        corners = []
        for i in (a, b, c):
            x, y, z = mesh.positions[i]
            depth = cameraZ - (z + modelZ)
            if depth < _NEAR:
                break
            # Grid coordinates: (0, 0) at the screen's top left
            corners.append((x * cameraZ / depth / cellW + _DEPTH_GRID_W / 2,
                            _DEPTH_GRID_H / 2 - y * cameraZ / depth / cellH, depth))
        else:
            (ax, ay, ad), (bx, by, bd), (cx, cy, cd) = corners
            area = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)
            if not area:
                continue

            left = max(0, math.ceil(min(ax, bx, cx) - 0.5))
            right = min(_DEPTH_GRID_W - 1, math.floor(max(ax, bx, cx) - 0.5))
            top = max(0, math.ceil(min(ay, by, cy) - 0.5))
            bottom = min(_DEPTH_GRID_H - 1, math.floor(max(ay, by, cy) - 0.5))
            depth = (ad + bd + cd) / 3

            for gy in range(top, bottom + 1):
                py = gy + 0.5
                for gx in range(left, right + 1):
                    if (gx, gy) in grid:
                        continue

                    # Inside the triangle when on the same side of all three edges
                    px = gx + 0.5
                    w0 = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
                    w1 = (cx - bx) * (py - by) - (cy - by) * (px - bx)
                    w2 = (ax - cx) * (py - cy) - (ay - cy) * (px - cx)
                    if (w0 >= 0 and w1 >= 0 and w2 >= 0) or (w0 <= 0 and w1 <= 0 and w2 <= 0):
                        grid[gx, gy] = depth

    if not grid:
        return cameraZ

    depths = sorted(grid.values())
    return max(depths[len(depths) // 2], cameraZ)


def _repeatWidth(meshes, mainZ):
    """
    How far apart to repeat the model: the narrowest of the wide layers at or behind
    the main depth (model Z), so those layers always touch their neighbouring copy
    instead of leaving a gap. None if there are no such layers.
    """
    widths = []
    for mesh in meshes:
        if not mesh.positions:
            continue

        xs = [p[0] for p in mesh.positions]
        meanZ = sum(p[2] for p in mesh.positions) / len(mesh.positions)
        if meanZ <= mainZ:
            widths.append(max(xs) - min(xs))

    if not widths:
        return None

    widest = max(widths)
    return min(w for w in widths if w >= widest / 2) or None


def _sortedTriangles(meshes):
    """
    Every triangle as (depth key, mesh index, a, b, c), farthest first
    """
    triangles = []
    for index, mesh in enumerate(meshes):
        pos = mesh.positions
        count = len(pos)
        for a, b, c in mesh.triangles:
            if a < count and b < count and c < count:
                triangles.append((pos[a][2] + pos[b][2] + pos[c][2], index, a, b, c))
    triangles.sort()
    return triangles


def _makeFills(meshes, textures):
    """
    How each mesh gets filled: (brush, texture width, texture height, additive).
    Each render makes its own, since drawing changes the brushes' transforms.
    """
    fills = []
    for mesh in meshes:
        tex = textures.get(mesh.texture)
        if tex is not None and mesh.uvs:
            additive = mesh.texture.lower().startswith('hikari')
            fills.append((QtGui.QBrush(tex), tex.width(), tex.height(), additive))
        else:
            fills.append((QtGui.QBrush(QtGui.QColor(128, 128, 128)), 0, 0, False))
    return fills


class _ZoneCamera:
    """
    The game's background camera for one zone. Coordinates are relative to the zone's
    top left, in level units, with Y going up.
    """

    def __init__(self, camera, zoneWidth, zoneHeight, camMode, camZoom):
        self.zoneWidth, self.zoneHeight = zoneWidth, zoneHeight
        self.projOffsetX, self.projOffsetY = camera.get('mProjOffset', (0.0, 0.0))
        self.typeDirY = camera.get('mTypeDirY', 0)
        self.magnifProjOffsetY = camera.get('mMagnifProjOffsetY', 0.3)
        self.magnifCameraPosY = camera.get('mMagnifCameraPosY', 0.0)

        self.zoom = zoneBgZoom(zoneWidth, zoneHeight, camMode, camZoom)
        self.screenW, self.screenH = _SCREEN_W * self.zoom, _SCREEN_H * self.zoom
        self.cameraZ = (_SCREEN_H / 2 / math.tan(_FOV_Y / 2)) * self.zoom

        # The model sits at the zone's horizontal middle, half a screen above its bottom
        self.modelX = zoneWidth / 2 + camera.get('mModelOffsetX', 0.0)
        self.modelY = -zoneHeight + self.screenH / 2 + camera.get('mModelOffsetY', 0.0)
        self.modelZ = camera.get('mModelOffsetZ', 0.0)

    def cameraFor(self, screenX, screenY):
        """
        The game's camera with the screen centred at (screenX, screenY): returns
        (camera X, camera Y, projection offset X, projection offset Y). The camera is
        at self.cameraZ, looking down -Z; the offsets shift the view by that fraction
        of its size.
        """
        aboveBottom = min(max(screenY - self.screenH / 2 + self.zoneHeight, 0.0), self.zoneHeight)

        camX = screenX - self.screenH * self.projOffsetX
        camY = screenY - self.screenH * self.projOffsetY
        offsetY = self.projOffsetY
        if self.typeDirY == 1:
            camY += self.magnifCameraPosY * aboveBottom
        else:
            # Shifts the picture as the screen rises, so the far scenery scrolls too
            offsetY += self.magnifProjOffsetY * aboveBottom / 720

        return camX, camY, self.projOffsetX, offsetY

    def project(self, meshes, screenX, screenY, pixelX, pixelY, scale, camX=None, copies=((0.0,)),
                aspect=None):
        """
        Screen positions of the model's vertices with the screen centred at (screenX,
        screenY); camX overrides the game's camera X. Each entry of copies is an X shift
        of a copy of the model. Returns one list of per-mesh points per copy, mapped so
        the screen's middle is at pixel (pixelX, pixelY), scale pixels per level unit.
        """
        gameCamX, camY, offsetX, offsetY = self.cameraFor(screenX, screenY)
        if camX is None:
            camX = gameCamX

        # Perspective projection with the frustum shifted by the projection offset (a
        # fraction of the view's size); the zone's plane (z = 0) maps 1:1
        viewW = self.screenH * aspect if aspect else self.screenW
        shiftX = offsetX * viewW
        shiftY = offsetY * self.screenH
        cameraZ, modelZ, modelY = self.cameraZ, self.modelZ, self.modelY

        projected = []
        for copyShift in copies:
            copyX = self.modelX + copyShift
            meshPoints = []
            for mesh in meshes:
                points = []
                for x, y, z in mesh.positions:
                    depth = cameraZ - (z + modelZ)
                    if depth < _NEAR:
                        points.append(None)
                    else:
                        f = cameraZ / depth
                        sx = (x + copyX - camX) * f - shiftX
                        sy = (y + modelY - camY) * f - shiftY
                        points.append((pixelX + sx * scale, pixelY - sy * scale))
                meshPoints.append(points)
            projected.append(meshPoints)

        return projected


def renderZoneBackground(meshes, textures, zoneWidth, zoneHeight, camera=None, camMode=0, camZoom=0,
                         maxSize=4096, progress=None):
    """
    Renders a background model to fill a zone of the given size (in level units). The
    zone is split into screen-sized pieces, each seen through the game's camera, with
    the camera moved so the main layer of scenery joins up between pieces.
    Returns a QImage.
    """
    view = _ZoneCamera(camera or {}, zoneWidth, zoneHeight, camMode, camZoom)
    scale = min(2.0, maxSize / max(zoneWidth, 1), maxSize / max(zoneHeight, 1))
    width, height = max(1, round(zoneWidth * scale)), max(1, round(zoneHeight * scale))

    image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    triangles = _sortedTriangles(meshes)
    if not triangles:
        return image

    fills = _makeFills(meshes, textures)
    cols = max(1, round(zoneWidth / view.screenW))
    rows = max(1, round(zoneHeight / view.screenH))

    # In the game the camera follows the screen 1:1, so scenery far behind the level
    # barely moves from one screen to the next and neighbouring pieces show nearly the
    # same thing. Move the camera faster instead, so the scenery at the depth that fills
    # most of the screen lines up from one piece to the next. When that takes the camera
    # past the model's sides, the model is repeated side by side.
    cameraZ, modelZ = view.cameraZ, view.modelZ
    mainDepth = _mainDepth(meshes, triangles, fills, textures, cameraZ, modelZ, view.screenW, view.screenH)
    step = mainDepth / cameraZ
    xs = [p[0] for mesh in meshes for p in mesh.positions]
    modelLeft, modelRight = min(xs), max(xs)
    period = _repeatWidth(meshes, cameraZ - modelZ - mainDepth) or max(modelRight - modelLeft, 1.0)
    farthest = max(cameraZ - (p[2] + modelZ) for mesh in meshes for p in mesh.positions)

    painter = QtGui.QPainter(image)
    painter.setPen(Qt.NoPen)
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)

    transform = QtGui.QTransform()
    for row in range(rows):
        for col in range(cols):
            x0, x1 = width * col // cols, width * (col + 1) // cols
            y0, y1 = height * row // rows, height * (row + 1) // rows
            pixelX, pixelY = (x0 + x1) / 2, (y0 + y1) / 2
            screenX, screenY = pixelX / scale, -pixelY / scale
            camX = screenX + (screenX - zoneWidth / 2) * (step - 1) - view.screenH * view.projOffsetX

            # The copies of the model this piece can see (at the farthest depth the view
            # is widest)
            reach = ((x1 - x0) / scale / 2 + abs(view.projOffsetX * view.screenW)) * farthest / cameraZ
            first = math.ceil((camX - reach - view.modelX - modelRight) / period)
            last = math.floor((camX + reach - view.modelX - modelLeft) / period)
            copies = [copy * period for copy in range(first, last + 1)]

            projected = view.project(meshes, screenX, screenY, pixelX, pixelY, scale, camX, copies)
            painter.setClipRect(x0, y0, x1 - x0, y1 - y0)
            _drawTriangles(painter, triangles, meshes, projected, fills, transform, (x0, y0, x1, y1))

            if progress is not None:
                progress((row * cols + col + 1) / (rows * cols))

    painter.end()
    return image


def renderLiveView(meshes, textures, camera, zoneRect, camMode, camZoom, viewRect, width, height):
    """
    What the game shows of a zone's background with the screen centred on the editor's
    view, like Miyamoto-Next does: the camera follows the view's middle (kept inside the
    zone), and the picture fills the view whatever the editor's zoom.
    zoneRect and viewRect are (x, y, width, height) in level units, Y going down.
    Returns a width x height QImage of the whole view, transparent outside the zone.
    """
    zoneX, zoneY, zoneW, zoneH = zoneRect
    viewX, viewY, viewW, viewH = viewRect
    view = _ZoneCamera(camera or {}, zoneW, zoneH, camMode, camZoom)

    image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    triangles = _sortedTriangles(meshes)
    if not triangles:
        return image

    # The view's middle, kept inside the zone, in zone coordinates with Y going up
    screenX = min(max(viewX + viewW / 2, zoneX), zoneX + zoneW) - zoneX
    screenY = -(min(max(viewY + viewH / 2, zoneY), zoneY + zoneH) - zoneY)

    # The game's screen height fills the image's height
    scale = height / view.screenH

    # Only the part of the view inside the zone gets drawn
    left = max(0.0, (zoneX - viewX) / viewW * width)
    right = min(float(width), (zoneX + zoneW - viewX) / viewW * width)
    top = max(0.0, (zoneY - viewY) / viewH * height)
    bottom = min(float(height), (zoneY + zoneH - viewY) / viewH * height)
    if right <= left or bottom <= top:
        return image

    projected = view.project(meshes, screenX, screenY, width / 2, height / 2, scale, aspect=width / height)

    painter = QtGui.QPainter(image)
    painter.setPen(Qt.NoPen)
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    painter.setClipRect(QtCore.QRectF(left, top, right - left, bottom - top))
    _drawTriangles(painter, triangles, meshes, projected, _makeFills(meshes, textures),
                   QtGui.QTransform(), (left, top, right, bottom))
    painter.end()
    return image


def _drawTriangles(painter, triangles, meshes, projected, fills, transform, bounds):
    """
    Fills the triangles that are in view, each with its texture mapped onto it.
    projected holds the screen positions of one or more copies of the model; each
    triangle is drawn for all copies before the next one, to keep the depth order.
    """
    left, top, right, bottom = bounds
    normal = QtGui.QPainter.CompositionMode_SourceOver
    plus = QtGui.QPainter.CompositionMode_Plus
    additiveOn = False

    for _, index, a, b, c in triangles:
        for copy in projected:
            points = copy[index]
            pa, pb, pc = points[a], points[b], points[c]
            if pa is None or pb is None or pc is None:
                continue

            if (max(pa[0], pb[0], pc[0]) < left or min(pa[0], pb[0], pc[0]) > right
                    or max(pa[1], pb[1], pc[1]) < top or min(pa[1], pb[1], pc[1]) > bottom):
                continue

            additiveOn = _drawTriangle(painter, meshes[index], fills[index], a, b, c, pa, pb, pc,
                                       transform, additiveOn, normal, plus)

    if additiveOn:
        painter.setCompositionMode(normal)


def _drawTriangle(painter, mesh, fill, a, b, c, pa, pb, pc, transform, additiveOn, normal, plus):
    """
    Fills one screen triangle with its texture; returns whether additive drawing is on
    """
    QPointF, QPolygonF = QtCore.QPointF, QtGui.QPolygonF

    brush, texW, texH, additive = fill
    if texW:
        # Map the texture's UV triangle onto the screen triangle (completed to
        # parallelograms, so the transform is the exact affine one)
        ua, ub, uc = mesh.uvs[a], mesh.uvs[b], mesh.uvs[c]
        src = QPolygonF([
            QPointF(ua[0] * texW, ua[1] * texH), QPointF(ub[0] * texW, ub[1] * texH),
            QPointF(uc[0] * texW, uc[1] * texH),
            QPointF((ub[0] + uc[0] - ua[0]) * texW, (ub[1] + uc[1] - ua[1]) * texH),
        ])
        dst = QPolygonF([
            QPointF(*pa), QPointF(*pb), QPointF(*pc),
            QPointF(pb[0] + pc[0] - pa[0], pb[1] + pc[1] - pa[1]),
        ])
        if not QtGui.QTransform.quadToQuad(src, dst, transform):
            return additiveOn
        brush.setTransform(transform)

    if additive != additiveOn:
        painter.setCompositionMode(plus if additive else normal)
        additiveOn = additive

    painter.setBrush(brush)
    painter.drawPolygon(QPolygonF([QPointF(*pa), QPointF(*pb), QPointF(*pc)]))
    return additiveOn


# Loaded models by (path, modification time); decoding the textures is the slow part
_loaded = {}


def getDistantView(path):
    """
    A dv_*.szs's (meshes, textures, camera parameters), loaded once
    """
    key = (path, os.path.getmtime(path))
    if key not in _loaded:
        _loaded[key] = loadDistantView(path)

    return _loaded[key]


def isDistantViewLoaded(path):
    """
    Whether getDistantView(path) would return right away
    """
    return (path, os.path.getmtime(path)) in _loaded


def renderDistantViewFile(path, zoneWidth, zoneHeight, camMode=0, camZoom=0, progress=None):
    """
    Loads a dv_*.szs and renders it for a zone of the given size (in level units) and
    camera settings
    """
    meshes, textures, camera = getDistantView(path)
    return renderZoneBackground(meshes, textures, zoneWidth, zoneHeight, camera, camMode, camZoom,
                                progress=progress)


class LiveViewRenderThread(QtCore.QThread):
    """
    Renders the live background of the zones in the editor's view off the GUI thread
    """
    status = QtCore.pyqtSignal(str)
    rendered = QtCore.pyqtSignal(object)    # [QImage], one per zone, each the whole view
    failed = QtCore.pyqtSignal(str)

    def __init__(self, jobs, viewRect, width, height, parent=None):
        """
        jobs: [(dv path, zone rect, camera mode, camera zoom)], rects in level units
        """
        super().__init__(parent)
        self.jobs = jobs
        self.viewRect = viewRect
        self.width = width
        self.height = height

    def run(self):
        images = []
        try:
            for path, zoneRect, camMode, camZoom in self.jobs:
                if not isDistantViewLoaded(path):
                    self.status.emit('Loading background %s...' % os.path.basename(path))

                meshes, textures, camera = getDistantView(path)
                images.append(renderLiveView(meshes, textures, camera, zoneRect, camMode, camZoom,
                                             self.viewRect, self.width, self.height))
        except Exception as e:
            self.failed.emit(str(e) or type(e).__name__)
            return

        self.rendered.emit(images)


class DistantViewRenderThread(QtCore.QThread):
    """
    Renders a zone's background preview off the GUI thread
    """
    progress = QtCore.pyqtSignal(object, int)       # zone, percentage
    rendered = QtCore.pyqtSignal(object, object)    # zone, QImage
    failed = QtCore.pyqtSignal(object, str)         # zone, error message

    def __init__(self, zone, path, parent=None):
        super().__init__(parent)
        self.zone = zone
        self.path = path
        self.zoneWidth = zone.width
        self.zoneHeight = zone.height
        self.camMode = zone.cammode
        self.camZoom = zone.camzoom

    def run(self):
        try:
            image = renderDistantViewFile(
                self.path, self.zoneWidth, self.zoneHeight, self.camMode, self.camZoom,
                progress=lambda done: self.progress.emit(self.zone, int(done * 100)),
            )
        except Exception as e:
            self.failed.emit(self.zone, str(e) or type(e).__name__)
            return

        self.rendered.emit(self.zone, image)
