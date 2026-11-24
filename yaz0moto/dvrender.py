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
Rough preview renders of background ("distant view") models, for Wii U and Deluxe.

A background is a 3D scene: on Deluxe Model/dv_<name>.Nin_NX_NVN.szs (holding
output.bfres), on Wii U (NSMBU and NSLU) content/Common/distant_view/dv_<name>.szs
(holding dv_<name>.bfres). This reads the meshes and their main texture out of the BFRES
and draws them with QPainter: each triangle is filled with its texture, back to front,
unlit. No shaders, lighting, fog or animations, so it only gives an idea of what the
zone's background looks like (dvgl draws them closer to the game).

The BFRES layouts follow Switch Toolbox's BfresLibrary (Switch version 8, Wii U 3.0).
"""

import copy
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


def _rel(b, off):
    """
    A Wii U BFRES offset (big endian, relative to its own field), as an absolute
    position; 0 if it's empty
    """
    value = struct.unpack_from('>i', b, off)[0]
    return off + value if value else 0


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
    return _pickColorTexture(samplers, textures)


def _pickColorTexture(samplers, textures):
    """
    Of a material's textures (and their sampler names), the one that most likely holds
    its colours, or None
    """
    if not textures:
        return None

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

    def __init__(self, b, curve, wiiU=False):
        if wiiU:
            # Wii U (version 3.0, big endian): offsets relative to their own field
            flags, numKeys, self.target = struct.unpack_from('>HHI', b, curve)
            self.start, self.end, self.scale, self.offset = struct.unpack_from('>4f', b, curve + 8)
            self.delta = 0.0
            frameArray, keyArray = _rel(b, curve + 0x18), _rel(b, curve + 0x1C)
            endian = '>'
        else:
            frameArray, keyArray = _offset(b, curve), _offset(b, curve + 8)
            flags, numKeys, self.target = struct.unpack_from('<HHI', b, curve + 0x10)
            self.start, self.end, self.scale, self.offset, self.delta = struct.unpack_from('<5f', b, curve + 0x18)
            endian = '<'

        frameType, keyType, self.curveType = flags & 3, (flags >> 2) & 3, (flags >> 4) & 7
        if frameType == 0:
            self.frames = list(struct.unpack_from('%s%df' % (endian, numKeys), b, frameArray))
        elif frameType == 1:  # fixed point, 5 fraction bits
            self.frames = [f / 32 for f in struct.unpack_from('%s%dh' % (endian, numKeys), b, frameArray)]
        else:
            self.frames = list(struct.unpack_from('%dB' % numKeys, b, frameArray))

        # Values per key: cubic 4 coefficients, linear 2, the rest 1
        per = {0: 4, 1: 2}.get(self.curveType, 1)
        stepInt = self.curveType in (4, 6)
        char = ('I' if stepInt else 'f', 'h', 'b')[keyType]
        flat = struct.unpack_from('%s%d%s' % (endian, numKeys * per, char), b, keyArray)
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


def isWiiUBFRES(b):
    """
    Whether a BFRES is the Wii U kind (version 3.x, big endian) rather than the Switch's
    """
    return b[:4] == b'FRES' and b[4:8] != b'    ' and b[8:10] == b'\xFE\xFF'


# The Wii U BFRES (version 3.0, as NSMBU and NSLU ship it) follows BfresLibrary's Wii U
# loader. All offsets are big endian and relative to their own field.

def _wiiuString(b, off):
    if not off:
        return ''
    n = struct.unpack_from('>I', b, off - 4)[0]
    return b[off:off + n].decode('utf-8', 'replace')


def _wiiuDict(b, off):
    """
    A Wii U index group as [(name, data position)], in order
    """
    if not off:
        return []
    count = struct.unpack_from('>i', b, off + 4)[0]
    out = []
    for i in range(1, count + 1):
        entry = off + 8 + i * 16
        out.append((_wiiuString(b, _rel(b, entry + 8)), _rel(b, entry + 12)))
    return out


# GX2 vertex attribute formats by their low byte: (components, bytes per component),
# with 0x09/0x0B packed and 0x03/0x08/0x0F half floats
_GX2_LAYOUTS = {
    0x00: (1, 1), 0x02: (1, 2), 0x03: (1, 2), 0x04: (2, 1), 0x05: (1, 4), 0x06: (1, 4),
    0x07: (2, 2), 0x08: (2, 2), 0x0A: (4, 1), 0x0C: (2, 4), 0x0D: (2, 4), 0x0E: (4, 2),
    0x0F: (4, 2), 0x10: (3, 4), 0x11: (3, 4), 0x12: (4, 4), 0x13: (4, 4),
}
_GX2_HALF = (0x03, 0x08, 0x0F)
_GX2_FLOAT = (0x06, 0x0D, 0x11, 0x13)


def _readAttributeWiiU(data, stride, offset, fmt, count):
    """
    Decodes one big endian GX2 vertex attribute into float tuples, or None if the
    format isn't supported
    """
    base, kind = fmt & 0xFF, (fmt >> 8) & 0xF   # kind: 0 unorm, 1 uint, 2 snorm, 3 sint, 8 float

    if base == 0x0B:  # 10_10_10_2 (normals): x in the low bits
        out = []
        for i in range(count):
            word = struct.unpack_from('>I', data, i * stride + offset)[0]
            values = []
            for shift in (0, 10, 20):
                v = (word >> shift) & 0x3FF
                if kind == 2:
                    if v & 0x200:
                        v -= 0x400
                    values.append(max(-1.0, v / 511))
                else:
                    values.append(v / 1023)
            out.append(tuple(values))
        return out

    if base not in _GX2_LAYOUTS:
        return None

    comps, size = _GX2_LAYOUTS[base]
    if base in _GX2_FLOAT or kind == 8 and size == 4:
        char, scale = 'f', None
    elif base in _GX2_HALF:
        char, scale = 'e', None
    else:
        signed = kind in (2, 3)
        char = {1: 'b', 2: 'h', 4: 'i'}[size] if signed else {1: 'B', 2: 'H', 4: 'I'}[size]
        if kind == 0:
            scale = 1 / ((1 << (size * 8)) - 1)
        elif kind == 2:
            scale = 1 / ((1 << (size * 8 - 1)) - 1)
        else:
            scale = None

    unpacker = struct.Struct('>' + char * comps)
    out = []
    for i in range(count):
        values = unpacker.unpack_from(data, i * stride + offset)
        if scale is not None:
            values = tuple(max(-1.0, v * scale) for v in values)
        out.append(values)
    return out


def _readVertexBufferWiiU(b, fvtx):
    """
    The named attributes of a Wii U FVTX, decoded
    """
    numAttrib, numBuffer = b[fvtx + 4], b[fvtx + 5]
    vertexCount = struct.unpack_from('>I', b, fvtx + 8)[0]
    attribArray, bufferArray = _rel(b, fvtx + 0x10), _rel(b, fvtx + 0x18)

    buffers = []
    for i in range(numBuffer):
        buf = bufferArray + i * 0x18
        size = struct.unpack_from('>I', b, buf + 4)[0]
        stride = struct.unpack_from('>H', b, buf + 0xC)[0]
        start = _rel(b, buf + 0x14)
        buffers.append((b[start:start + size], stride))

    attributes = {}
    for i in range(numAttrib):
        attrib = attribArray + i * 12
        name = _wiiuString(b, _rel(b, attrib))
        bufferIndex, offset, fmt = struct.unpack_from('>BxHI', b, attrib + 4)
        if bufferIndex >= len(buffers):
            continue
        data, stride = buffers[bufferIndex]
        values = _readAttributeWiiU(data, stride, offset, fmt, vertexCount)
        if values is not None:
            attributes[name] = values
    return attributes


def _readTrianglesWiiU(b, mesh):
    """
    The triangles of a Wii U shape's first (most detailed) mesh
    """
    primitive, indexFormat, indexCount = struct.unpack_from('>III', b, mesh)
    indexBuffer = _rel(b, mesh + 0x14)
    firstVertex = struct.unpack_from('>I', b, mesh + 0x18)[0]
    char = {0: '<H', 1: '<I', 4: '>H', 9: '>I'}.get(indexFormat)
    if char is None or primitive not in (4, 6) or not indexBuffer:
        return []

    start = _rel(b, indexBuffer + 0x14)
    indices = struct.unpack_from('%s%d%s' % (char[0], indexCount, char[1]), b, start)
    indices = [i + firstVertex for i in indices]

    if primitive == 4:  # triangle list
        return [tuple(indices[i:i + 3]) for i in range(0, indexCount - 2, 3)]

    tris = []
    for i in range(indexCount - 2):
        a, c, d = indices[i:i + 3]
        tris.append((a, c, d) if i % 2 == 0 else (c, a, d))
    return tris


# Bytes taken by each Wii U shader parameter type (version 3.0 doesn't store the size)
_WIIU_PARAM_SIZES = {
    0: 4, 1: 8, 2: 12, 3: 16, 4: 4, 5: 8, 6: 12, 7: 16, 8: 4, 9: 8, 10: 12, 11: 16,
    12: 4, 13: 8, 14: 12, 15: 16, 17: 16, 18: 24, 19: 32, 21: 24, 22: 36, 23: 48,
    25: 32, 26: 48, 27: 64, 28: 20, 29: 36, 30: 24, 31: 28,
}

# GX2 blend functions and comparisons, as the Switch materials' render info names them
_GX2_BLEND = ('zero', 'one', 'src_color', 'one_minus_src_color', 'src_alpha', 'one_minus_src_alpha',
              'dst_alpha', 'one_minus_dst_alpha', 'dst_color', 'one_minus_dst_color')
_GX2_COMPARE = ('never', 'less', 'equal', 'lequal', 'greater', 'notequal', 'gequal', 'always')


def _readMaterialWiiU(b, fmat):
    """
    A Wii U material's textures, render info and shader parameters. Its GX2 render
    state is translated into the render info names the Switch materials use, so both
    are drawn the same way.
    """
    name = _wiiuString(b, _rel(b, fmat + 4))
    numTextures = b[fmat + 0x11]
    texRefs = _rel(b, fmat + 0x28)
    textures = [_wiiuString(b, _rel(b, texRefs + i * 8)) for i in range(numTextures)]
    samplers = [n for n, _ in _wiiuDict(b, _rel(b, fmat + 0x30))]

    renderInfo = {}
    for infoName, entry in _wiiuDict(b, _rel(b, fmat + 0x1C)):
        count, kind = struct.unpack_from('>HB', b, entry)
        if kind == 2:
            values = [_wiiuString(b, _rel(b, entry + 8 + j * 4)) for j in range(count)]
        else:
            values = list(struct.unpack_from('>%d%s' % (count, 'f' if kind == 1 else 'i'), b, entry + 8))
        renderInfo[infoName] = values

    state = _rel(b, fmat + 0x20)
    if state:
        flags, polygon, depth, alpha, alphaRef, color, _, blend = struct.unpack_from('>IIIIfIII', b, state)
        mode = flags & 3
        blending = bool((color >> 8) & 0xFF)
        if mode == 0:
            mode = 3 if blending else 1
        renderInfo['gsys_render_state_mode'] = [('custom', 'opaque', 'mask', 'translucent')[mode]]
        renderInfo['gsys_render_state_blend_mode'] = ['color' if blending and mode == 3 else 'none']
        src, dst = blend & 0x1F, (blend >> 8) & 0x1F
        renderInfo['gsys_color_blend_rgb_src_func'] = [_GX2_BLEND[src] if src < len(_GX2_BLEND) else 'src_alpha']
        renderInfo['gsys_color_blend_rgb_dst_func'] = [_GX2_BLEND[dst] if dst < len(_GX2_BLEND) else 'one_minus_src_alpha']
        renderInfo['gsys_depth_test_write'] = ['true' if depth & 4 else 'false']
        cullFront, cullBack = polygon & 1, polygon & 2
        renderInfo['gsys_render_state_display_face'] = [
            'none' if cullFront and cullBack else 'back' if cullFront else 'front' if cullBack else 'both']
        renderInfo['gsys_alpha_test_enable'] = ['true' if alpha & 8 else 'false']
        renderInfo['gsys_alpha_test_func'] = [_GX2_COMPARE[alpha & 7]]
        renderInfo['gsys_alpha_test_value'] = [alphaRef]

    params = {}
    source = _rel(b, fmat + 0x3C)
    for paramName, entry in _wiiuDict(b, _rel(b, fmat + 0x38)):
        kind, dataOffset = struct.unpack_from('>BxH', b, entry)
        size = _WIIU_PARAM_SIZES.get(kind)
        if size and source:
            params[paramName] = struct.unpack_from('>%df' % (size // 4), b, source + dataOffset)

    material = DistantViewMaterial(name, list(zip(samplers, textures)), renderInfo, params)
    return material, _pickColorTexture(samplers, textures)


def _eulerQuaternion(x, y, z):
    """
    A rotation given as XYZ Euler angles (radians, X applied first) as a quaternion
    (x, y, z, w)
    """
    q = QtGui.QQuaternion.fromAxisAndAngle(0, 0, 1, math.degrees(z)) \
        * QtGui.QQuaternion.fromAxisAndAngle(0, 1, 0, math.degrees(y)) \
        * QtGui.QQuaternion.fromAxisAndAngle(1, 0, 0, math.degrees(x))
    return q.x(), q.y(), q.z(), q.scalar()


def _readSkeletonWiiU(b, fskl):
    """
    The bones of a Wii U FSKL, in index order
    """
    bones = {}
    for _, bone in _wiiuDict(b, _rel(b, fskl + 0x10)):
        index, parent = struct.unpack_from('>Hh', b, bone + 4)
        flags = struct.unpack_from('>I', b, bone + 0x10)[0]
        scale = struct.unpack_from('>3f', b, bone + 0x14)
        rotation = struct.unpack_from('>4f', b, bone + 0x20)
        if flags & 0x1000:  # Euler angles
            rotation = _eulerQuaternion(*rotation[:3])
        translation = struct.unpack_from('>3f', b, bone + 0x30)
        bones[index] = (_wiiuString(b, _rel(b, bone)), parent, scale, rotation, translation)

    return Skeleton([bones[i] for i in sorted(bones)])


def _readSkeletalAnimWiiU(b, skeleton):
    """
    The first skeletal animation of a Wii U BFRES (Euler rotations only, like the
    Switch's)
    """
    anims = _wiiuDict(b, _rel(b, 0x28))
    if not anims:
        return None

    fska = anims[0][1]
    if b[fska:fska + 4] != b'FSKA':
        return None
    flags = struct.unpack_from('>I', b, fska + 0xC)[0]
    frameCount, numBoneAnims = struct.unpack_from('>HH', b, fska + 0x10)
    if not flags & 0x1000:
        return None

    rest = {name: (scale, translation) for name, _, scale, _, translation in skeleton.bones}
    anim = SkeletalAnim(frameCount, bool(flags & 4))
    boneAnimArray = _rel(b, fska + 0x20)
    for i in range(numBoneAnims):
        entry = boneAnimArray + i * 0x18
        animFlags = struct.unpack_from('>I', b, entry)[0]
        name = _wiiuString(b, _rel(b, entry + 4))
        numCurves = b[entry + 0xA]
        curveArray, baseData = _rel(b, entry + 0x10), _rel(b, entry + 0x14)
        if name not in rest:
            continue

        scale, translation = rest[name]
        base = list(scale) + list(translation) + [0.0, 0.0, 0.0, 0.0]
        pos = baseData
        if pos and animFlags & 0x08:
            base[0:3] = struct.unpack_from('>3f', b, pos)
            pos += 12
        if pos and animFlags & 0x10:
            base[6:10] = struct.unpack_from('>4f', b, pos)
            pos += 16
        if pos and animFlags & 0x20:
            base[3:6] = struct.unpack_from('>3f', b, pos)

        curves = [AnimCurve(b, curveArray + c * 0x20, True) for c in range(numCurves)] if curveArray else []
        anim.bones[name] = (base, [(curve.target, curve) for curve in curves])

    return anim


def _readMaterialAnimsWiiU(b):
    """
    The shader parameter animations (texture SRT, colour, other) of every material in
    a Wii U BFRES, by material name (the first animation that animates it)
    """
    anims = {}
    for group in (0x34, 0x30, 0x2C):  # texture SRT, colour and shader parameter animations
        for _, fshu in _wiiuDict(b, _rel(b, group)):
            if b[fshu:fshu + 4] != b'FSHU':
                continue

            flags = struct.unpack_from('>I', b, fshu + 0xC)[0]
            frameCount, numMaterials = struct.unpack_from('>HH', b, fshu + 0x10)
            materialArray = _rel(b, fshu + 0x2C)
            for m in range(numMaterials):
                data = materialArray + m * 0x20
                numInfos, numCurves, numConsts = struct.unpack_from('>HHH', b, data)
                name = _wiiuString(b, _rel(b, data + 0x10))
                infoArray, curveArray, constArray = (_rel(b, data + 0x14 + i * 4) for i in range(3))
                anim = anims.get(name)
                if anim is None:
                    anim = anims[name] = MaterialAnim(frameCount, bool(flags & 4))
                elif anim.frameCount != frameCount:
                    continue

                for i in range(numInfos):
                    info = infoArray + i * 0x10
                    beginCurve, numFloatCurves, numIntCurves, beginConst, numConstsHere = \
                        struct.unpack_from('>5H', b, info)
                    param = _wiiuString(b, _rel(b, info + 0xC))
                    if param in anim.params:
                        continue

                    targets = []
                    for c in range(beginConst, min(beginConst + numConstsHere, numConsts)):
                        offset, value = struct.unpack_from('>If', b, constArray + c * 8)
                        targets.append((offset, value))
                    for c in range(beginCurve, min(beginCurve + numFloatCurves + numIntCurves, numCurves)):
                        curve = AnimCurve(b, curveArray + c * 0x20, True)
                        targets.append((curve.target, curve))
                    anim.params[param] = targets

    return anims


def parseBFRESWiiU(b):
    """
    Reads the meshes of every model in a Wii U BFRES
    """
    if not isWiiUBFRES(b):
        raise ValueError('Not a Wii U BFRES file')

    anims = _readMaterialAnimsWiiU(b)
    meshes = []
    for _, fmdl in _wiiuDict(b, _rel(b, 0x20)):
        if b[fmdl:fmdl + 4] != b'FMDL':
            continue

        fvtxArray = _rel(b, fmdl + 0x10)
        numVertexBuffers = struct.unpack_from('>H', b, fmdl + 0x20)[0]

        materials = {}
        for _, fmat in _wiiuDict(b, _rel(b, fmdl + 0x18)):
            index = struct.unpack_from('>H', b, fmat + 0xC)[0]
            materials[index] = _readMaterialWiiU(b, fmat)
            materials[index][0].anim = anims.get(materials[index][0].name)

        skeleton = _readSkeletonWiiU(b, _rel(b, fmdl + 0xC))
        skeleton.anim = _readSkeletalAnimWiiU(b, skeleton)

        vertexCache = {}
        shapes = []
        for name, fshp in _wiiuDict(b, _rel(b, fmdl + 0x14)):
            index, materialIndex, boneIndex, vertexIndex = struct.unpack_from('>4H', b, fshp + 0xC)
            shapes.append((index, name, fshp, materialIndex, boneIndex, vertexIndex))

        for _, name, fshp, materialIndex, boneIndex, vertexIndex in sorted(shapes):
            numMesh = b[fshp + 0x17]
            if not numMesh or vertexIndex >= numVertexBuffers:
                continue

            if vertexIndex not in vertexCache:
                vertexCache[vertexIndex] = _readVertexBufferWiiU(b, fvtxArray + vertexIndex * 0x20)
            attributes = vertexCache[vertexIndex]
            positions = attributes.get('_p0')
            if not positions:
                continue

            material, texture = materials.get(materialIndex, (None, None))
            mesh = DistantViewMesh(
                name, [p[:3] for p in positions], attributes.get('_u0'),
                _readTrianglesWiiU(b, _rel(b, fshp + 0x24)), texture,
                attributes.get('_n0'), attributes.get('_c0'), material)
            mesh.skeleton = skeleton
            mesh.boneIndex = boneIndex if boneIndex < len(skeleton.bones) else 0
            meshes.append(mesh)

    return meshes


# GX2 component selectors (0-3 RGBA, 4 zero, 5 one) as bntxlib's (2-5 RGBA, 0 zero, 1 one)
_GX2_TO_BNTX_COMP = {0: 2, 1: 3, 2: 4, 3: 5, 4: 0, 5: 1}


def loadTexturesWiiU(b, names):
    """
    Decodes the named FTEX textures of a Wii U BFRES into QImages (the ones it can)
    """
    from bntxlib import bcn, formConv
    try:
        from bntxlib import formConv_cy as formConvFast
    except ImportError:
        formConvFast = formConv
    import addrlib

    out = {}
    for name, ftex in _wiiuDict(b, _rel(b, 0x24)):
        if name not in names or b[ftex:ftex + 4] != b'FTEX':
            continue

        try:
            (dim, width, height, depth, _, fmt, aa, use, imageSize, _, _, _, tileMode, swizzle, _,
             _) = struct.unpack_from('>16I', b, ftex + 4)
            compSel = [_GX2_TO_BNTX_COMP.get(c, 0) for c in b[ftex + 0x88:ftex + 0x8C]]
            start = _rel(b, ftex + 0xB0)
            if dim != 1 or not start:
                continue

            base = fmt & 0x3F
            surface = addrlib.getSurfaceInfo(fmt, width, height, 1, 1, tileMode, 0, 0)
            data = addrlib.deswizzle(width, height, 1, fmt, aa, use, tileMode, swizzle, surface.pitch,
                                     surface.bpp, 0, 0, b[start:start + imageSize])

            if base == 0x31:
                data, kind, bpp = bcn.decompressDXT1(data, width, height), 'rgba8', 4
            elif base == 0x32:
                data, kind, bpp = bcn.decompressDXT3(data, width, height), 'rgba8', 4
            elif base == 0x33:
                data, kind, bpp = bcn.decompressDXT5(data, width, height), 'rgba8', 4
            elif base == 0x34:
                data, kind, bpp = bcn.decompressBC4(data, width, height, 1 if fmt & 0x200 else 0), 'rgba8', 4
            elif base == 0x35:
                data, kind, bpp = bcn.decompressBC5(data, width, height, 1 if fmt & 0x200 else 0), 'rgba8', 4
            elif base == 0x1A:
                kind, bpp = 'rgba8', 4
            elif base == 0x01:
                kind, bpp = 'l8', 1
            elif base == 0x07:
                kind, bpp = 'la8', 2
            elif base == 0x08:
                kind, bpp = 'rgb565', 2
            else:
                continue

            if kind in ('l8', 'la8'):
                # One or two channels: R (and G), as the component selectors expect
                data = bytes(data)
                pixels = width * height
                red = data[0:pixels * bpp:bpp]
                green = data[1:pixels * bpp:bpp] if bpp == 2 else bytes(pixels)
                channels = [bytes(pixels), b'\xFF' * pixels, red, green, bytes(pixels), b'\xFF' * pixels]
                rgba = bytearray(pixels * 4)
                for i in range(4):
                    rgba[i::4] = channels[compSel[i]]
                data = bytes(rgba)
            else:
                data = formConvFast.torgba8(width, height, bytearray(data), kind, bpp, compSel)

            out[name] = QtGui.QImage(bytes(data), width, height, QtGui.QImage.Format_RGBA8888).copy()
        except Exception:
            continue

    return out


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

    if struct.unpack_from('<I', d, 4)[0] == 1:
        return _parseAAMPv1(d)
    return readList(0x30 + struct.unpack_from('<I', d, 0x14)[0])


def _parseAAMPv1(d):
    """
    A Wii U AAMP parameter archive (little endian, version 1), in _parseAAMP's form.
    Lists, objects and parameters are stored inline, each starting with its size:
    list (size, name CRC, list count, object count), object (size, parameter count,
    name CRC, class CRC), parameter (size, type, name CRC, value).
    """
    def value(pos, kind, size):
        if kind == 0:
            return bool(d[pos])
        if kind == 1:
            return struct.unpack_from('<f', d, pos)[0]
        if kind == 2:
            return struct.unpack_from('<i', d, pos)[0]
        if kind in (3, 4, 5, 6):
            return struct.unpack_from('<%df' % {3: 2, 4: 3, 5: 4, 6: 4}[kind], d, pos)
        if kind in (7, 8, 13, 14, 20):
            end = d.find(b'\0', pos, pos + size)
            return d[pos:end if end >= 0 else pos + size].decode('utf-8', 'replace')
        return None

    def readList(pos):
        _, crc, numLists, numObjs = struct.unpack_from('<4I', d, pos)
        pos += 16
        lists = {}
        for _ in range(numLists):
            size, childCrc = struct.unpack_from('<II', d, pos)
            lists[childCrc] = readList(pos)
            pos += size
        objs = {}
        for _ in range(numObjs):
            size, numParams, objCrc = struct.unpack_from('<III', d, pos)
            params = {}
            param = pos + 16
            for _ in range(numParams):
                paramSize, kind, paramCrc = struct.unpack_from('<III', d, param)
                params[paramCrc] = value(param + 12, kind, paramSize - 12)
                param += paramSize
            objs[objCrc] = params
            pos += size
        return {'objs': objs, 'lists': lists}

    return readList(0x18 + struct.unpack_from('<I', d, 0x14)[0])


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
    romfs is the Deluxe romfs (DistantView, Env) or the Wii U content/Common folder
    (distant_view, env). Returns {} if the files aren't found.
    """
    for envset, packPath in (
            (os.path.join(romfs, 'DistantView', 'dv_%s.envset' % name), os.path.join(romfs, 'Env', 'env_pack.szs')),
            (os.path.join(romfs, 'distant_view', 'dv_%s.envset' % name), os.path.join(romfs, 'env', 'env_pack.szs'))):
        if os.path.isfile(envset) and os.path.isfile(packPath):
            break
    else:
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

    wiiU = isWiiUBFRES(bfres)
    meshes = parseBFRESWiiU(bfres) if wiiU else parseBFRES(bfres)

    # Only decode the textures the meshes use: decoding is slow without the Cython extensions
    used = {m.texture for m in meshes if m.texture}
    for m in meshes:
        if m.material is not None:
            used.update(texture for _, texture in m.material.textures if texture)

    textures = {}
    if wiiU:
        textures = loadTexturesWiiU(bfres, used)
    else:
        bntx = loadBNTXFromBFRES(bfres)
        for name in used:
            try:
                textures[name] = loadTexFromBNTX(bntx, name)
            except Exception:
                pass

    # Replace the models' placeholder light maps with the ones the game would generate
    # (Deluxe: the background's files live in <romfs>/Model, its lighting in <romfs>/Env;
    # Wii U: content/Common/distant_view and content/Common/env)
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


def _posed(meshes):
    """
    The meshes with their vertices placed by their bones (the skeleton's pose at frame
    0, as the OpenGL renderer starts), for the renderers here that draw positions
    directly. Each mesh's posed copy is made once.
    """
    out = []
    poses = {}
    for mesh in meshes:
        posed = getattr(mesh, '_posed', None)
        if posed is None:
            matrix = None
            skeleton = mesh.skeleton
            if skeleton is not None:
                if id(skeleton) not in poses:
                    poses[id(skeleton)] = skeleton.matrices(0.0)
                bones = poses[id(skeleton)]
                matrix = bones[mesh.boneIndex] if mesh.boneIndex < len(bones) else None

            if matrix is None or matrix.isIdentity():
                posed = mesh
            else:
                posed = copy.copy(mesh)
                QVector3D = QtGui.QVector3D
                points = (matrix.map(QVector3D(*p)) for p in mesh.positions)
                posed.positions = [(p.x(), p.y(), p.z()) for p in points]
                posed._posed = posed
            mesh._posed = posed
        out.append(posed)
    return out


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


class ViewOptions:
    """
    How the editor lines a zone's background up with the level (Preferences >
    Background Preview)
    """

    def __init__(self, gameCamera=True, fillView=False, offsetX=0.0, offsetY=0.0):
        self.gameCamera = gameCamera  # keep the screen inside the zone, like the game's camera
        self.fillView = fillView      # one game screen fills the editor's view (Miyamoto-Next)
        self.offsetX = offsetX        # extra shift of the picture in level units, to the right
        self.offsetY = offsetY        # extra shift of the picture in level units, down

    def key(self):
        return (self.gameCamera, self.fillView, self.offsetX, self.offsetY)


def viewOptionsFromSettings(setting):
    """
    The ViewOptions saved in the settings; setting is misc.setting
    """
    def flag(name, default):
        value = setting(name, default)
        if isinstance(value, str):
            return value.strip().lower() in ('true', '1', 'yes')
        return bool(value)

    def number(name):
        try:
            return float(setting(name, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    return ViewOptions(flag('BgPreviewGameCamera', True), flag('BgPreviewFillView', False),
                       number('BgPreviewOffsetX'), number('BgPreviewOffsetY'))


def _clampCenter(center, half, low, high):
    """
    A centre moved so [center - half, center + half] stays within [low, high] (the
    middle if it doesn't fit)
    """
    if high - low <= 2 * half:
        return (low + high) / 2
    return min(max(center, low + half), high - half)


class _Frame:
    """
    One placement of the game's background camera, and where its picture lands in the
    editor: a point the game draws s level units (at the zone's plane) from the
    screen's centre is shown at anchor + scale * s, in zone coordinates (relative to
    the zone's top left, Y going up)
    """

    def __init__(self, camX, camY, offsetX, offsetY, anchorX, anchorY, scale=1.0):
        self.camX, self.camY = camX, camY              # the camera (it's at _ZoneCamera.cameraZ)
        self.offsetX, self.offsetY = offsetX, offsetY  # projection offset, fractions of the screen
        self.anchorX, self.anchorY = anchorX, anchorY
        self.scale = scale


class _ZoneCamera:
    """
    The game's background camera for one zone, as the game's DistantViewMgr::calcView_
    places it (identical on Wii U and Deluxe). Coordinates are relative to the zone's
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

    def screenCenter(self, x, y, gameCamera=True):
        """
        Where the game's screen centre would be for a wanted centre (x, y). The game's
        camera keeps the whole screen inside the zone, so near the zone's edges (most
        of all its bottom, where levels mostly play) it stops short of the editor's
        view centre; without gameCamera, only the centre is kept inside the zone (like
        Miyamoto-Next does).
        """
        if gameCamera:
            return (_clampCenter(x, self.screenW / 2, 0.0, self.zoneWidth),
                    _clampCenter(y, self.screenH / 2, -self.zoneHeight, 0.0))
        return min(max(x, 0.0), self.zoneWidth), min(max(y, -self.zoneHeight), 0.0)

    def cameraFor(self, screenX, screenY):
        """
        The game's camera with the screen centred at (screenX, screenY): returns
        (camera X, camera Y, projection offset X, projection offset Y). The camera is
        at self.cameraZ, looking down -Z; the offsets shift the view by that fraction
        of its size.
        """
        # How far the screen's bottom is above the zone's bottom
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

    def frameFor(self, viewX, viewY, viewH=None, options=None, camX=None):
        """
        The camera for an editor view centred at (viewX, viewY), viewH tall (zone
        coordinates). The screen goes where the game's camera would be, and its
        picture is drawn at the level's scale, so the background lines up with the
        level as in the game; or, with options.fillView, one game screen fills the
        view's height (around the view's centre). camX overrides the camera's X.
        """
        options = options or ViewOptions()
        screenX, screenY = self.screenCenter(viewX, viewY, options.gameCamera)
        gameCamX, camY, offsetX, offsetY = self.cameraFor(screenX, screenY)

        if options.fillView and viewH:
            anchorX, anchorY, scale = viewX, viewY, viewH / self.screenH
        else:
            anchorX, anchorY, scale = screenX, screenY, 1.0

        return _Frame(gameCamX if camX is None else camX, camY, offsetX, offsetY,
                      anchorX + options.offsetX, anchorY - options.offsetY, scale)

    def project(self, meshes, frame, mapping, copies=(0.0,)):
        """
        Pixel positions of the model's vertices seen through a frame. mapping is
        (x0, y0, sx, sy): zone point (x, y) is pixel (x0 + x * sx, y0 - y * sy). Each
        entry of copies is an X shift of a copy of the model. Returns one list of
        per-mesh points per copy.
        """
        x0, y0, sx, sy = mapping

        # Perspective projection with the frustum shifted by the projection offset (a
        # fraction of the game screen's size); the zone's plane (z = 0) maps 1:1
        shiftX = frame.offsetX * self.screenW
        shiftY = frame.offsetY * self.screenH
        cameraZ, modelZ, modelY = self.cameraZ, self.modelZ, self.modelY
        k = frame.scale
        baseX, baseY = x0 + frame.anchorX * sx, y0 - frame.anchorY * sy
        camX, camY = frame.camX, frame.camY

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
                        s = ((x + copyX - camX) * f - shiftX) * k
                        t = ((y + modelY - camY) * f - shiftY) * k
                        points.append((baseX + s * sx, baseY - t * sy))
                meshPoints.append(points)
            projected.append(meshPoints)

        return projected

    def frustum(self, frame, left, right, bottom, top, near):
        """
        The near plane rectangle (left, right, bottom, top) of the perspective frustum
        that shows the zone area [left, right] x [bottom, top] (zone coordinates)
        through a frame
        """
        shiftX = frame.offsetX * self.screenW
        shiftY = frame.offsetY * self.screenH
        f = near / self.cameraZ / frame.scale
        return ((left - frame.anchorX) * f + shiftX * near / self.cameraZ,
                (right - frame.anchorX) * f + shiftX * near / self.cameraZ,
                (bottom - frame.anchorY) * f + shiftY * near / self.cameraZ,
                (top - frame.anchorY) * f + shiftY * near / self.cameraZ)


def renderZoneBackground(meshes, textures, zoneWidth, zoneHeight, camera=None, camMode=0, camZoom=0,
                         maxSize=4096, progress=None, options=None):
    """
    Renders a background model to fill a zone of the given size (in level units). The
    zone is split into screen-sized pieces, each seen through the game's camera, with
    the camera moved so the main layer of scenery joins up between pieces.
    Returns a QImage.
    """
    options = options or ViewOptions()
    meshes = _posed(meshes)
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
    mapping = (0.0, 0.0, scale, scale)
    for row in range(rows):
        for col in range(cols):
            x0, x1 = width * col // cols, width * (col + 1) // cols
            y0, y1 = height * row // rows, height * (row + 1) // rows
            pieceX, pieceY = (x0 + x1) / 2 / scale, -(y0 + y1) / 2 / scale

            # Vertically each piece shows what the game shows with the screen there (the
            # game's camera never goes below the zone's bottom); horizontally the camera
            # moves faster, see above
            screenX = view.screenCenter(pieceX, pieceY, options.gameCamera)[0]
            camX = screenX + (screenX - zoneWidth / 2) * (step - 1) - view.screenH * view.projOffsetX
            frame = view.frameFor(pieceX, pieceY, None, options, camX)

            # The copies of the model this piece can see (at the farthest depth the view
            # is widest)
            reach = ((x1 - x0) / scale / 2 + abs(frame.anchorX - pieceX)
                     + abs(view.projOffsetX * view.screenW)) * farthest / cameraZ
            first = math.ceil((camX - reach - view.modelX - modelRight) / period)
            last = math.floor((camX + reach - view.modelX - modelLeft) / period)
            copies = [copy * period for copy in range(first, last + 1)]

            projected = view.project(meshes, frame, mapping, copies)
            painter.setClipRect(x0, y0, x1 - x0, y1 - y0)
            _drawTriangles(painter, triangles, meshes, projected, fills, transform, (x0, y0, x1, y1))

            if progress is not None:
                progress((row * cols + col + 1) / (rows * cols))

    painter.end()
    return image


def liveFrame(view, zoneRect, viewRect, options=None):
    """
    The camera frame showing a zone's background in an editor view, both rects
    (x, y, width, height) in level units with Y going down
    """
    zoneX, zoneY, zoneW, zoneH = zoneRect
    viewX, viewY, viewW, viewH = viewRect
    return view.frameFor(viewX + viewW / 2 - zoneX, -(viewY + viewH / 2 - zoneY), viewH, options)


def renderLiveView(meshes, textures, camera, zoneRect, camMode, camZoom, viewRect, width, height, options=None):
    """
    What the game shows of a zone's background with the screen centred on the editor's
    view (or as close as the game's camera gets), at the level's scale or filling the
    view (see ViewOptions). zoneRect and viewRect are (x, y, width, height) in level
    units, Y going down. Returns a width x height QImage of the whole view,
    transparent outside the zone.
    """
    zoneX, zoneY, zoneW, zoneH = zoneRect
    viewX, viewY, viewW, viewH = viewRect
    meshes = _posed(meshes)
    view = _ZoneCamera(camera or {}, zoneW, zoneH, camMode, camZoom)

    image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    triangles = _sortedTriangles(meshes)
    if not triangles:
        return image

    # Only the part of the view inside the zone gets drawn
    sx, sy = width / viewW, height / viewH
    left = max(0.0, (zoneX - viewX) * sx)
    right = min(float(width), (zoneX + zoneW - viewX) * sx)
    top = max(0.0, (zoneY - viewY) * sy)
    bottom = min(float(height), (zoneY + zoneH - viewY) * sy)
    if right <= left or bottom <= top:
        return image

    frame = liveFrame(view, zoneRect, viewRect, options)
    projected = view.project(meshes, frame, ((zoneX - viewX) * sx, (zoneY - viewY) * sy, sx, sy))

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


def renderDistantViewFile(path, zoneWidth, zoneHeight, camMode=0, camZoom=0, progress=None, options=None):
    """
    Loads a dv_*.szs and renders it for a zone of the given size (in level units) and
    camera settings
    """
    meshes, textures, camera = getDistantView(path)
    return renderZoneBackground(meshes, textures, zoneWidth, zoneHeight, camera, camMode, camZoom,
                                progress=progress, options=options)


class LiveViewRenderThread(QtCore.QThread):
    """
    Renders the live background of the zones in the editor's view off the GUI thread
    """
    status = QtCore.pyqtSignal(str)
    rendered = QtCore.pyqtSignal(object)    # [QImage], one per zone, each the whole view
    failed = QtCore.pyqtSignal(str)

    def __init__(self, jobs, viewRect, width, height, parent=None, options=None):
        """
        jobs: [(dv path, zone rect, camera mode, camera zoom)], rects in level units
        """
        super().__init__(parent)
        self.jobs = jobs
        self.options = options
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
                                             self.viewRect, self.width, self.height, self.options))
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

    def __init__(self, zone, path, parent=None, options=None):
        super().__init__(parent)
        self.zone = zone
        self.options = options
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
                options=self.options,
            )
        except Exception as e:
            self.failed.emit(self.zone, str(e) or type(e).__name__)
            return

        self.rendered.emit(self.zone, image)
