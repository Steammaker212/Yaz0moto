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
Draws Deluxe background models with OpenGL into an offscreen framebuffer, fast enough
to follow the editor's view as it scrolls. Uses only Qt's OpenGL classes; the camera
is the game's (see dvrender._ZoneCamera). Unlit, like the QPainter renderer, but with
a depth buffer, perspective-correct and repeating textures, and cut-outs.
"""

import math
from array import array

from PyQt5 import QtCore, QtGui

from . import dvrender


_VERTEX_SHADER = """
attribute vec3 aPos;
attribute vec2 aUV;
attribute vec3 aNormal;
attribute vec4 aColor;
uniform mat4 uMVP;             // includes the mesh's bone
uniform mat4 uBone;            // the mesh's bone alone, to turn the normals
varying vec2 vUV;
varying vec3 vNormal;
varying vec4 vColor;

void main()
{
    vUV = aUV;
    vNormal = (uBone * vec4(aNormal, 0.0)).xyz;
    vColor = aColor;
    gl_Position = uMVP * vec4(aPos, 1.0);
}
"""

# An approximation of the game's per-material shaders (which only exist compiled for
# the Switch): texture, tinted between the material's two TEV colours when it has
# them, times the vertex colour, lit by the baked light maps looked up by the normal
_FRAGMENT_SHADER = """
uniform sampler2D uTex;
uniform sampler2D uLight;
uniform sampler2D uSpec;
uniform float uUseTex;
uniform float uUseTev;
uniform float uUseLight;
uniform float uUseSpec;
uniform float uSpecPower;
uniform float uOpaque;
uniform float uAlphaTest;      // 0 off, 1 keep alpha >= ref, 2 keep alpha <= ref
uniform float uAlphaRef;
uniform vec4 uColor;
uniform vec4 uTev0;
uniform vec4 uTev1;
uniform vec4 uMatColor;
uniform vec3 uTexRow0;         // the colour texture's (animated) UV transform
uniform vec3 uTexRow1;

// Layered textures (clouds): a distortion texture warping the colour's UVs, and a
// second warped colour layer blended in
uniform sampler2D uInd;
uniform sampler2D uTex2;
uniform sampler2D uInd2;
uniform float uUseInd;
uniform float uUseTex2;
uniform float uUseInd2;
uniform vec3 uIndRow0;
uniform vec3 uIndRow1;
uniform vec3 uTex2Row0;
uniform vec3 uTex2Row1;
uniform vec3 uInd2Row0;
uniform vec3 uInd2Row1;
uniform vec2 uIndScale;
uniform vec2 uInd2Scale;

varying vec2 vUV;
varying vec3 vNormal;
varying vec4 vColor;

vec2 transform(vec3 row0, vec3 row1, vec2 uv)
{
    return vec2(dot(row0, vec3(uv, 1.0)), dot(row1, vec3(uv, 1.0)));
}

void main()
{
    // The distortion's strength is a guess: the material's value, toned down
    vec2 uv = transform(uTexRow0, uTexRow1, vUV);
    if (uUseInd > 0.5)
        uv += (texture2D(uInd, transform(uIndRow0, uIndRow1, vUV)).rg - 0.5) * uIndScale * 0.25;
    vec4 color = uUseTex > 0.5 ? texture2D(uTex, uv) : uColor;

    // The second layer blends in, but doesn't thin out what's already solid
    if (uUseTex2 > 0.5)
    {
        vec2 uv2 = transform(uTex2Row0, uTex2Row1, vUV);
        if (uUseInd2 > 0.5)
            uv2 += (texture2D(uInd2, transform(uInd2Row0, uInd2Row1, vUV)).rg - 0.5) * uInd2Scale * 0.25;
        vec4 color2 = texture2D(uTex2, uv2);
        color = vec4(mix(color.rgb, color2.rgb, 0.5), max(color.a, color2.a));
    }
    vec3 n = normalize(vNormal);
    vec2 sphere = vec2(n.x * 0.5 + 0.5, 0.5 - n.y * 0.5);
    vec3 light = uUseLight > 0.5 ? texture2D(uLight, sphere).rgb : vec3(1.0);

    // Tinted materials blend between their two colours by the texture, shaded by the
    // light map (so it picks the colour instead of darkening the result); untextured
    // ones by the light map alone
    if (uUseTev > 0.5)
        color.rgb = mix(uTev1.rgb, uTev0.rgb, (uUseTex > 0.5 ? color.rgb : vec3(1.0)) * light);
    else
        color.rgb *= light;
    color *= uMatColor * vColor;
    if (uUseSpec > 0.5)
        color.rgb += texture2D(uSpec, sphere).rgb * uSpecPower;

    if (uAlphaTest > 1.5 ? color.a > uAlphaRef : (uAlphaTest > 0.5 && color.a < uAlphaRef))
        discard;
    if (uOpaque > 0.5)
        color.a = 1.0;
    else if (color.a < 0.004)
        discard;

    gl_FragColor = color;
}
"""

# OpenGL constants
GL_TRIANGLES = 0x0004
GL_FLOAT = 0x1406
GL_DEPTH_TEST = 0x0B71
GL_BLEND = 0x0BE2
GL_SCISSOR_TEST = 0x0C11
GL_CULL_FACE = 0x0B44
GL_LEQUAL = 0x0203
GL_ZERO = 0
GL_ONE = 1
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_COLOR_BUFFER_BIT = 0x4000
GL_DEPTH_BUFFER_BIT = 0x0100
GL_TEXTURE0 = 0x84C0
GL_BACK = 0x0405
GL_FRONT = 0x0404
GL_SRC_COLOR = 0x0300
GL_ONE_MINUS_SRC_COLOR = 0x0301
GL_DST_ALPHA = 0x0304
GL_ONE_MINUS_DST_ALPHA = 0x0305
GL_DST_COLOR = 0x0306
GL_ONE_MINUS_DST_COLOR = 0x0307

# Blend factors as the materials' render info names them
_BLEND_FACTORS = {
    'zero': GL_ZERO, 'one': GL_ONE,
    'src_color': GL_SRC_COLOR, 'one_minus_src_color': GL_ONE_MINUS_SRC_COLOR,
    'src_alpha': GL_SRC_ALPHA, 'one_minus_src_alpha': GL_ONE_MINUS_SRC_ALPHA,
    'dst_alpha': GL_DST_ALPHA, 'one_minus_dst_alpha': GL_ONE_MINUS_DST_ALPHA,
    'dst_color': GL_DST_COLOR, 'one_minus_dst_color': GL_ONE_MINUS_DST_COLOR,
}

_FAR = 80000.0

# Floats per vertex: position (3), UV (2), normal (3), colour (4)
_VERTEX_FLOATS = 12


def buildArrays(meshes):
    """
    Each mesh's triangles as interleaved float32 vertex data (position, UV, normal,
    colour), plus its mean model Z (to order meshes far to near). Slow-ish in Python,
    so it's done once, preferably off the GUI thread.
    """
    out = []
    for mesh in meshes:
        pos, uvs, normals, colors = mesh.positions, mesh.uvs, mesh.normals, mesh.colors
        count = len(pos)
        if normals is not None and len(normals) < count:
            normals = None
        if colors is not None and len(colors) < count:
            colors = None

        # Some meshes carry all-zero vertex colours their shader doesn't use (like a
        # sky): treat unused colour/alpha as white instead of blacking the mesh out
        if colors:
            unusedRGB = not any(any(c[:3]) for c in colors)
            unusedAlpha = not any(c[3] for c in colors if len(c) > 3)
            if unusedRGB or unusedAlpha:
                colors = [(1.0, 1.0, 1.0, c[3] if len(c) > 3 else 1.0) if unusedRGB and not unusedAlpha
                          else (c[0], c[1], c[2], 1.0) if unusedAlpha and not unusedRGB
                          else (1.0, 1.0, 1.0, 1.0) for c in colors]

        data = array('f')
        for tri in mesh.triangles:
            if max(tri) >= count:
                continue
            for i in tri:
                data.extend(pos[i])
                data.extend(uvs[i][:2] if uvs else (0.0, 0.0))
                data.extend(normals[i][:3] if normals else (0.0, 0.0, 1.0))
                data.extend(colors[i][:4] if colors else (1.0, 1.0, 1.0, 1.0))

        meanZ = sum(p[2] for p in pos) / count if count else 0.0
        out.append((data.tobytes(), len(data) // _VERTEX_FLOATS, meanZ))

    return out


class _DrawState:
    """
    How to draw a mesh, from its material
    """

    def __init__(self, mesh):
        material = mesh.material
        info = material.info if material is not None else (lambda name, default=None: default)
        params = material.params if material is not None else {}

        mode = info('gsys_render_state_mode', 'opaque')
        self.opaque = mode in ('opaque', 'mask')
        self.blend = info('gsys_render_state_blend_mode', 'none') != 'none' and not self.opaque
        self.src = _BLEND_FACTORS.get(info('gsys_color_blend_rgb_src_func'), GL_SRC_ALPHA)
        self.dst = _BLEND_FACTORS.get(info('gsys_color_blend_rgb_dst_func'), GL_ONE_MINUS_SRC_ALPHA)
        self.depthWrite = info('gsys_depth_test_write', 'true') == 'true'
        self.cullBack = info('gsys_render_state_display_face', 'front') == 'front'
        self.cullFront = info('gsys_render_state_display_face') == 'back'
        self.priority = info('priority', 0) or 0

        self.alphaTest = 0.0
        self.alphaRef = info('gsys_alpha_test_value', 0.5) or 0.5
        if info('gsys_alpha_test_enable', 'false') == 'true':
            self.alphaTest = 2.0 if info('gsys_alpha_test_func', 'gequal') in ('less', 'lequal') else 1.0

        self.light = material.texture('lm_01') if material is not None else None
        self.spec = material.texture('lm_02') if material is not None else None

        # The textures layered for the colour: the main one, a distortion ("ind...")
        # texture warping it, and possibly a second colour layer with its own
        # distortion (like the clouds). Sampler "_aN" uses texture matrix N.
        self.texMatrix = 'texmtx0'
        self.ind = self.color2 = self.ind2 = None
        self.indMatrix = self.color2Matrix = self.ind2Matrix = 'texmtx0'
        if material is not None:
            layers = []
            for sampler, texture in material.textures:
                number = sampler[2:] if sampler[2:].isdigit() else '0'
                if not texture.lower().startswith(('lm_', 'dof')):
                    layers.append((texture, 'texmtx' + number))

            start = next((i for i, (texture, _) in enumerate(layers) if texture == mesh.texture), None)
            if start is not None:
                self.texMatrix = layers[start][1]
                before, rest = layers[:start], layers[start + 1:]
                if rest and _isDistortion(rest[0][0]):
                    self.ind, self.indMatrix = rest.pop(0)

                    # Only "colour, distortion, colour, distortion" layering (clouds)
                    # takes a second colour layer
                    if len(rest) >= 2 and _isDistortion(rest[1][0]) and not _isDistortion(rest[0][0]):
                        self.color2, self.color2Matrix = rest.pop(0)
                        self.ind2, self.ind2Matrix = rest.pop(0)
                elif before and _isDistortion(before[-1][0]):
                    # The distortion map can also come first
                    self.ind, self.indMatrix = before[-1]

        # Sky gradients ("sora" materials) blend their two colours the other way round
        # from everything else (the textures run from overhead to the horizon)
        self.reverseTev = self.opaque and material is not None and 'sora' in material.name.lower()

        self.material = material
        self.anim = material.anim if material is not None else None
        self._static = self._values(params)

    def values(self, frame):
        """
        The shader's material values at an animation frame (60 per second)
        """
        if self.anim is None:
            return self._static
        return self._values(self.anim.apply(self.material.params, frame))

    def _values(self, params):
        tev0 = tuple(params.get('tev_color0', (0.0, 0.0, 0.0, 0.0)))[:4]
        tev1 = tuple(params.get('tev_color1', (0.0, 0.0, 0.0, 0.0)))[:4]
        if self.reverseTev:
            tev0, tev1 = tev1, tev0
        return {
            # Tint between the two TEV colours, when the material has them
            'useTev': any(tev0[:3]) or any(tev1[:3]),
            'tev0': tev0,
            'tev1': tev1,
            'matColor': tuple(params.get('mat_color0', (1.0, 1.0, 1.0, 1.0)))[:4],
            'specPower': params.get('spec_power', (0.5,))[0],
            'texMatrix': _texMatrix(params.get(self.texMatrix)),
            'indMatrix': _texMatrix(params.get(self.indMatrix)),
            'color2Matrix': _texMatrix(params.get(self.color2Matrix)),
            'ind2Matrix': _texMatrix(params.get(self.ind2Matrix)),
            # How strongly each distortion texture shifts the colour's UVs
            'indScale': tuple(params.get('ind_texmtx0', (0.0, 0.0))[:2]),
            'ind2Scale': tuple(params.get('ind_texmtx1', (0.0, 0.0))[:2]),
        }


def _isDistortion(texture):
    """
    Whether a texture is a distortion ("indirect") map, by its name
    """
    name = texture.lower()
    return name.startswith('ind') or '_ind' in name


def _texMatrix(srt):
    """
    A texture SRT parameter (mode, scale X/Y, rotation, translation X/Y) as the two
    rows of a 2D affine UV transform
    """
    if not srt or len(srt) < 6:
        return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)

    _, sx, sy, r, tx, ty = srt[:6]
    c, s = math.cos(r), math.sin(r)
    return (sx * c, -sx * s, -tx), (sy * s, sy * c, ty)


class _GLModel:
    """
    A background model uploaded to the GPU
    """

    def __init__(self, meshes, textures, camera, arrays):
        self.camera = camera
        self.meshes = []  # (buffer, vertex count, texture, light map, specular map, _DrawState)
        uploaded = {}

        def upload(name, repeat=True):
            if name not in textures:
                return None
            if name not in uploaded:
                tex = QtGui.QOpenGLTexture(textures[name].convertToFormat(QtGui.QImage.Format_RGBA8888))
                tex.setWrapMode(QtGui.QOpenGLTexture.Repeat if repeat else QtGui.QOpenGLTexture.ClampToEdge)
                tex.setMinMagFilters(QtGui.QOpenGLTexture.LinearMipMapLinear, QtGui.QOpenGLTexture.Linear)
                uploaded[name] = tex
            return uploaded[name]

        entries = []
        for i, mesh in enumerate(meshes):
            data, count, meanZ = arrays[i]
            if not count:
                continue

            buffer = QtGui.QOpenGLBuffer(QtGui.QOpenGLBuffer.VertexBuffer)
            buffer.create()
            buffer.bind()
            buffer.allocate(data, len(data))
            buffer.release()

            state = _DrawState(mesh)
            hasUVs = bool(mesh.uvs)

            # (texture unit, texture or None, the shader flag saying it's used)
            units = [
                (0, upload(mesh.texture) if hasUVs else None, 'uUseTex'),
                (1, upload(state.light, False) if state.light else None, 'uUseLight'),
                (2, upload(state.spec, False) if state.spec else None, 'uUseSpec'),
                (3, upload(state.ind) if hasUVs and state.ind else None, 'uUseInd'),
                (4, upload(state.color2) if hasUVs and state.color2 else None, 'uUseTex2'),
                (5, upload(state.ind2) if hasUVs and state.ind2 else None, 'uUseInd2'),
            ]
            entries.append((not state.opaque, state.priority if not state.opaque else 0, meanZ,
                            (buffer, count, units, state, mesh.boneIndex)))

        # Opaque meshes first, then translucent ones by the materials' priority (far
        # layers have the lowest), far to near within a priority
        entries.sort(key=lambda e: e[:3])
        self.meshes = [e[3] for e in entries]
        self.textures = list(uploaded.values())

        self.skeleton = meshes[0].skeleton if meshes else None
        boneAnim = self.skeleton is not None and self.skeleton.anim is not None and any(
            curves for _, curves in self.skeleton.anim.bones.values())
        self.animated = boneAnim or any(mesh[3].anim is not None for mesh in self.meshes)
        self.backdrop = self._backdrop(meshes, arrays)

    def _backdrop(self, meshes, arrays):
        """
        The model-space box (left, right, bottom, top, Z) of the farthest opaque mesh
        (the sky, usually), in its bone's rest position; None if there's none
        """
        bones = self.skeleton.matrices(0) if self.skeleton is not None else []
        best = None
        for i, mesh in enumerate(meshes):
            if not arrays[i][1] or mesh.material is None \
                    or mesh.material.info('gsys_render_state_mode', 'opaque') != 'opaque':
                continue
            if best is None or arrays[i][2] < arrays[best][2]:
                best = i

        if best is None:
            return None

        mesh = meshes[best]
        bone = bones[mesh.boneIndex] if mesh.boneIndex < len(bones) else QtGui.QMatrix4x4()
        points = [bone.map(QtGui.QVector3D(*p)) for p in mesh.positions]
        xs, ys = [p.x() for p in points], [p.y() for p in points]
        return min(xs), max(xs), min(ys), max(ys), sum(p.z() for p in points) / len(points)

    def boneMatrices(self, frame):
        """
        Every bone's world matrix at a frame (identity if there's no skeleton)
        """
        if self.skeleton is None:
            return []
        return self.skeleton.matrices(frame)

    def destroy(self):
        for mesh in self.meshes:
            mesh[0].destroy()
        for tex in self.textures:
            tex.destroy()


class GLBackgroundRenderer:
    """
    Offscreen OpenGL renderer for zone backgrounds. Check .ok after creating it.
    Must be used from the GUI thread.
    """

    def __init__(self):
        self.ok = False
        self.models = {}
        self.fbo = None

        fmt = QtGui.QSurfaceFormat()
        fmt.setVersion(2, 1)
        self.context = QtGui.QOpenGLContext()
        self.context.setFormat(fmt)
        if not self.context.create():
            return

        self.surface = QtGui.QOffscreenSurface()
        self.surface.setFormat(self.context.format())
        self.surface.create()
        if not self.surface.isValid() or not self.context.makeCurrent(self.surface):
            return

        try:
            profile = QtGui.QOpenGLVersionProfile()
            profile.setVersion(2, 0)
            self.gl = self.context.versionFunctions(profile)
            if self.gl is None:
                return
            self.gl.initializeOpenGLFunctions()

            self.program = QtGui.QOpenGLShaderProgram()
            if not (self.program.addShaderFromSourceCode(QtGui.QOpenGLShader.Vertex, _VERTEX_SHADER)
                    and self.program.addShaderFromSourceCode(QtGui.QOpenGLShader.Fragment, _FRAGMENT_SHADER)
                    and self.program.link()):
                return
        finally:
            self.context.doneCurrent()

        self.ok = True

    def has(self, path):
        return path in self.models

    def upload(self, path, meshes, textures, camera, arrays):
        """
        Puts a loaded model on the GPU
        """
        self.context.makeCurrent(self.surface)
        try:
            if path in self.models:
                self.models[path].destroy()
            self.models[path] = _GLModel(meshes, textures, camera, arrays)
        finally:
            self.context.doneCurrent()

    def isAnimated(self, path):
        """
        Whether an uploaded model has anything that moves
        """
        model = self.models.get(path)
        return model is not None and model.animated

    def render(self, jobs, viewRect, width, height, frame=0.0):
        """
        Renders the zones' backgrounds as the game shows them with the screen centred on
        the view, at an animation frame (60 per second). jobs: [(path, zone rect,
        camera mode, camera zoom)] of uploaded models; rects in level units, Y going
        down. Returns a width x height QImage of the whole view, transparent outside the
        zones.
        """
        self.context.makeCurrent(self.surface)
        try:
            return self._render(jobs, viewRect, width, height, frame)
        finally:
            self.context.doneCurrent()

    def _render(self, jobs, viewRect, width, height, frame):
        gl = self.gl
        if self.fbo is None or self.fbo.width() != width or self.fbo.height() != height:
            fboFormat = QtGui.QOpenGLFramebufferObjectFormat()
            fboFormat.setAttachment(QtGui.QOpenGLFramebufferObject.Depth)
            self.fbo = QtGui.QOpenGLFramebufferObject(width, height, fboFormat)

        self.fbo.bind()
        gl.glViewport(0, 0, width, height)
        gl.glDisable(GL_SCISSOR_TEST)
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        gl.glDisable(GL_CULL_FACE)
        gl.glEnable(GL_DEPTH_TEST)
        gl.glDepthFunc(GL_LEQUAL)
        gl.glEnable(GL_BLEND)
        gl.glEnable(GL_SCISSOR_TEST)

        program = self.program
        program.bind()
        locations = [(program.attributeLocation(name), offset, size)
                     for name, offset, size in (('aPos', 0, 3), ('aUV', 12, 2), ('aNormal', 20, 3), ('aColor', 32, 4))]
        for loc, _, _ in locations:
            program.enableAttributeArray(loc)
        program.setUniformValue('uTex', 0)
        program.setUniformValue('uLight', 1)
        program.setUniformValue('uSpec', 2)
        program.setUniformValue('uInd', 3)
        program.setUniformValue('uTex2', 4)
        program.setUniformValue('uInd2', 5)
        program.setUniformValue('uColor', QtGui.QVector4D(0.5, 0.5, 0.5, 1.0))

        viewX, viewY, viewW, viewH = viewRect
        for path, zoneRect, camMode, camZoom in jobs:
            model = self.models.get(path)
            if model is None:
                continue

            zoneX, zoneY, zoneW, zoneH = zoneRect

            # Only the part of the view inside the zone (scissor Y counts from the bottom)
            left = max(0, math.floor((zoneX - viewX) / viewW * width))
            right = min(width, math.ceil((zoneX + zoneW - viewX) / viewW * width))
            top = max(0, math.floor((zoneY - viewY) / viewH * height))
            bottom = min(height, math.ceil((zoneY + zoneH - viewY) / viewH * height))
            if right <= left or bottom <= top:
                continue

            gl.glScissor(left, height - bottom, right - left, bottom - top)
            gl.glClear(GL_DEPTH_BUFFER_BIT)

            viewMatrix = self._matrix(model, zoneRect, camMode, camZoom, viewRect, width / height)
            bones = model.boneMatrices(frame)

            for buffer, count, units, state, boneIndex in model.meshes:
                bone = bones[boneIndex] if boneIndex < len(bones) else QtGui.QMatrix4x4()
                program.setUniformValue('uMVP', viewMatrix * bone)
                program.setUniformValue('uBone', bone)
                self._applyState(state, frame)

                for unit, tex, flag in units:
                    if tex is not None:
                        tex.bind(unit)
                    program.setUniformValue(flag, 1.0 if tex is not None else 0.0)

                buffer.bind()
                for loc, offset, size in locations:
                    program.setAttributeBuffer(loc, GL_FLOAT, offset, size, _VERTEX_FLOATS * 4)
                gl.glDrawArrays(GL_TRIANGLES, 0, count)
                buffer.release()

                for unit, tex, _ in units:
                    if tex is not None:
                        tex.release(unit)

        gl.glDepthMask(True)
        gl.glDisable(GL_CULL_FACE)
        for loc, _, _ in locations:
            program.disableAttributeArray(loc)
        program.release()
        self.fbo.release()

        return self.fbo.toImage()

    def _applyState(self, state, frame):
        """
        Sets up blending, depth, culling and the shader's material values for a mesh
        """
        gl, program = self.gl, self.program

        # The colour uses the material's blending; the alpha always builds up as
        # "covered", so the image composites correctly over the editor
        if state.blend:
            gl.glBlendFuncSeparate(state.src, state.dst, GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
        else:
            gl.glBlendFuncSeparate(GL_ONE, GL_ZERO, GL_ONE, GL_ZERO)
        gl.glDepthMask(state.depthWrite)

        if state.cullBack or state.cullFront:
            gl.glEnable(GL_CULL_FACE)
            gl.glCullFace(GL_BACK if state.cullBack else GL_FRONT)
        else:
            gl.glDisable(GL_CULL_FACE)

        values = state.values(frame)
        row0, row1 = values['texMatrix']
        program.setUniformValue('uOpaque', 1.0 if state.opaque else 0.0)
        program.setUniformValue('uAlphaTest', state.alphaTest)
        program.setUniformValue('uAlphaRef', float(state.alphaRef))
        program.setUniformValue('uUseTev', 1.0 if values['useTev'] else 0.0)
        program.setUniformValue('uTev0', QtGui.QVector4D(*values['tev0']))
        program.setUniformValue('uTev1', QtGui.QVector4D(*values['tev1']))
        program.setUniformValue('uMatColor', QtGui.QVector4D(*values['matColor']))
        program.setUniformValue('uSpecPower', float(values['specPower']))
        program.setUniformValue('uTexRow0', QtGui.QVector3D(*row0))
        program.setUniformValue('uTexRow1', QtGui.QVector3D(*row1))
        for prefix, key in (('uInd', 'indMatrix'), ('uTex2', 'color2Matrix'), ('uInd2', 'ind2Matrix')):
            row0, row1 = values[key]
            program.setUniformValue(prefix + 'Row0', QtGui.QVector3D(*row0))
            program.setUniformValue(prefix + 'Row1', QtGui.QVector3D(*row1))
        program.setUniformValue('uIndScale', QtGui.QVector2D(*values['indScale']))
        program.setUniformValue('uInd2Scale', QtGui.QVector2D(*values['ind2Scale']))

    @staticmethod
    def _clampView(center, half, low, high):
        """
        A view centre moved so [center - half, center + half] stays within [low, high]
        (centred on it if the view is bigger)
        """
        if high - low <= 2 * half:
            return (low + high) / 2
        return min(max(center, low + half), high - half)

    @staticmethod
    def _matrix(model, zoneRect, camMode, camZoom, viewRect, aspect):
        """
        The game's camera for this zone with the screen centred on the view, as a
        projection * view * model matrix
        """
        zoneX, zoneY, zoneW, zoneH = zoneRect
        viewX, viewY, viewW, viewH = viewRect
        cam = dvrender._ZoneCamera(model.camera, zoneW, zoneH, camMode, camZoom)

        # The view's middle, kept inside the zone, in zone coordinates with Y going up
        screenX = min(max(viewX + viewW / 2, zoneX), zoneX + zoneW) - zoneX
        screenY = -(min(max(viewY + viewH / 2, zoneY), zoneY + zoneH) - zoneY)
        camX, camY, offsetX, offsetY = cam.cameraFor(screenX, screenY)

        # Perspective frustum shifted by the projection offset (a fraction of its size)
        near = dvrender._NEAR
        clipH = 2 * near * math.tan(dvrender._FOV_Y / 2)
        clipW = clipH * aspect
        centerX, centerY = clipW * offsetX, clipH * offsetY

        # Keep the farthest solid layer (the sky) covering the view: in zones taller or
        # wider than the game's levels, the view would otherwise move past its edges.
        # The picture's shift is limited instead (it moves near and far scenery alike),
        # so the background stops scrolling there.
        if model.backdrop is not None:
            left, right, bottom, top, z = model.backdrop
            depth = cam.cameraZ - (z + cam.modelZ)
            if depth > near:
                scale = depth / near
                centerX = (GLBackgroundRenderer._clampView(camX + centerX * scale, clipW / 2 * scale,
                                                           left + cam.modelX, right + cam.modelX) - camX) / scale
                centerY = (GLBackgroundRenderer._clampView(camY + centerY * scale, clipH / 2 * scale,
                                                           bottom + cam.modelY, top + cam.modelY) - camY) / scale

        matrix = QtGui.QMatrix4x4()
        matrix.frustum(centerX - clipW / 2, centerX + clipW / 2, centerY - clipH / 2, centerY + clipH / 2,
                       near, _FAR)
        matrix.translate(-camX, -camY, -cam.cameraZ)
        matrix.translate(cam.modelX, cam.modelY, cam.modelZ)
        return matrix


class GLModelLoadThread(QtCore.QThread):
    """
    Loads a background model and prepares its vertex data off the GUI thread
    """
    loaded = QtCore.pyqtSignal(str, object)   # path, (meshes, textures, camera, arrays)
    failed = QtCore.pyqtSignal(str, str)      # path, error message

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        try:
            meshes, textures, camera = dvrender.getDistantView(self.path)
            arrays = buildArrays(meshes)
        except Exception as e:
            self.failed.emit(self.path, str(e) or type(e).__name__)
            return

        self.loaded.emit(self.path, (meshes, textures, camera, arrays))
