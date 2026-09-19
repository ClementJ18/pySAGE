"""The 3D map view: the terrain as a lit mesh seen through an orbiting camera, the placed objects as
their models, and the same markers, outlines and tool feedback as the top-down view drawn over it.

It is the top-down `MapView`'s twin, not a second copy of its state: the document, the chosen
tool, the View options, the scene, the texture colour picture, the footprints and the shown and
hidden filters are read from that view, which forwards every change here. A tool gets this view as
its `ToolView`, with a `CameraProjection` as `transform`, so every tool works in it unchanged.

The terrain is textured as the game textures it (`render.terrain_texturing`) once the window hands
over an atlas of the map's texture cells (`atlas_provider`, `set_atlas`); until then it takes the
top-down view's colour picture, or a height ramp without game data. The shader finds each cell's
tiles and blend masks in a data texture and mixes them per pixel. Objects are drawn as the models
the window loads for their templates (`model_provider`, `set_models`), one instanced draw per mesh
of each model, front faces only as the game draws them, and a mesh that is itself a picture of
light - a flame, a glow, a sky - added in rather than mixed in, undimmed by the map's lights. An
object drawn as its model needs no marker; one with no model to draw keeps its dot, and Show
Object Dots puts a dot back on every object.

Middle-drag or Space-drag pans; with Ctrl, or a right-drag when the tool does not take the right
button, it orbits instead. The wheel zooms about the ground under the cursor.

Needs PyOpenGL (the `worldbuilder` extra) and an OpenGL 3.3 core context; the window imports this
module only when the 3D view is first opened.
"""

from __future__ import annotations

import ctypes
import math
from collections import defaultdict
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER,
    GL_BLEND,
    GL_CLAMP_TO_EDGE,
    GL_COLOR_BUFFER_BIT,
    GL_COMPILE_STATUS,
    GL_CULL_FACE,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_TEST,
    GL_DYNAMIC_DRAW,
    GL_ELEMENT_ARRAY_BUFFER,
    GL_FALSE,
    GL_FILL,
    GL_FLOAT,
    GL_FRAGMENT_SHADER,
    GL_FRONT_AND_BACK,
    GL_LINE,
    GL_LINEAR,
    GL_LINEAR_MIPMAP_LINEAR,
    GL_LINK_STATUS,
    GL_MAX_TEXTURE_SIZE,
    GL_NEAREST,
    GL_ONE,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_REPEAT,
    GL_RGB,
    GL_RGB8,
    GL_RGBA,
    GL_RGBA8,
    GL_RGBA16UI,
    GL_RGBA32F,
    GL_RGBA_INTEGER,
    GL_SCISSOR_TEST,
    GL_SRC_ALPHA,
    GL_STATIC_DRAW,
    GL_TEXTURE0,
    GL_TEXTURE1,
    GL_TEXTURE2,
    GL_TEXTURE3,
    GL_TEXTURE4,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_TRIANGLES,
    GL_TRUE,
    GL_UNPACK_ALIGNMENT,
    GL_UNSIGNED_BYTE,
    GL_UNSIGNED_INT,
    GL_UNSIGNED_SHORT,
    GL_VERTEX_SHADER,
    glActiveTexture,
    glAttachShader,
    glBindBuffer,
    glBindTexture,
    glBindVertexArray,
    glBlendFunc,
    glBufferData,
    glBufferSubData,
    glClear,
    glClearColor,
    glCompileShader,
    glCreateProgram,
    glCreateShader,
    glDeleteBuffers,
    glDeleteShader,
    glDeleteTextures,
    glDeleteVertexArrays,
    glDepthMask,
    glDisable,
    glDrawElements,
    glDrawElementsInstanced,
    glEnable,
    glEnableVertexAttribArray,
    glGenBuffers,
    glGenerateMipmap,
    glGenTextures,
    glGenVertexArrays,
    glGetIntegerv,
    glGetProgramInfoLog,
    glGetProgramiv,
    glGetShaderInfoLog,
    glGetShaderiv,
    glGetUniformLocation,
    glLinkProgram,
    glPixelStorei,
    glPolygonMode,
    glScissor,
    glShaderSource,
    glTexImage2D,
    glTexParameteri,
    glTexSubImage2D,
    glUniform1f,
    glUniform1i,
    glUniform2f,
    glUniform3f,
    glUniform3fv,
    glUniform4f,
    glUniformMatrix4fv,
    glUseProgram,
    glVertexAttribDivisor,
    glVertexAttribPointer,
    glViewport,
)
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygonF,
    QRegion,
    QResizeEvent,
    QSurfaceFormat,
    QWheelEvent,
)
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QWidget

from sage_map.assets.object_list import Object
from sage_map.assets.river_areas import RiverArea
from sage_worldbuilder import camera_edit
from sage_worldbuilder.anchors import shown_position
from sage_worldbuilder.camera import (
    FIELD_OF_VIEW,
    MAX_DISTANCE,
    MAX_PITCH,
    MIN_DISTANCE,
    MIN_PITCH,
    Camera,
    pose_matrix,
)
from sage_worldbuilder.camera_edit import CameraScene
from sage_worldbuilder.cameras import focal_length, pose_axes
from sage_worldbuilder.changes import Change, ChangeKind, Region
from sage_worldbuilder.influences import SOUND_FLAG
from sage_worldbuilder.lighting import LightTarget, scene_lights
from sage_worldbuilder.models import MapConditions, model_conditions, model_key
from sage_worldbuilder.projection import CameraProjection
from sage_worldbuilder.render.art import ArtTextures
from sage_worldbuilder.render.model_mesh import (
    ModelGeometry,
    instance_matrices,
    object_scale,
    ray_hit_instances,
)
from sage_worldbuilder.render.road_surface import RoadSurface, road_surfaces
from sage_worldbuilder.render.terrain_mesh import (
    Box,
    chunk_boxes,
    chunk_vertices,
    chunks_near,
    chunks_touching,
    grid_indices,
)
from sage_worldbuilder.render.terrain_texturing import (
    TerrainAtlas,
    atlas_key,
    blend_secondaries,
    cell_data,
    cliff_cells,
    mask_indices,
)
from sage_worldbuilder.render.water_mesh import (
    WaterLook,
    WaterMesh,
    lake_look,
    lake_mesh,
    river_look,
    river_mesh,
)
from sage_worldbuilder.scene import Marker, MarkerKind, marker_kind
from sage_worldbuilder.terrain import FEET_PER_HEIGHT_UNIT, WORLD_UNITS_PER_CELL
from sage_worldbuilder.terrain.cells import TileLayer
from sage_worldbuilder.terrain.grid import TerrainGrid
from sage_worldbuilder.terrain.surface import ground_heights, ray_hit
from sage_worldbuilder.ui.overlays import (
    BRIDGE_FILL,
    GRID_COLOR,
    ROAD_FILL,
    OverlayPainter,
    arrow_head,
    draw_label,
)
from sage_worldbuilder.ui.overlays import CAMERA_PATH as _CAMERA_PATH
from sage_worldbuilder.ui.tools import Gesture, Tool
from sage_worldbuilder.viewport import letterbox_band, safe_frame

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument
    from sage_worldbuilder.footprints import Footprints
    from sage_worldbuilder.influences import Influences
    from sage_worldbuilder.roads import RoadStyles
    from sage_worldbuilder.scene import MapScene
    from sage_worldbuilder.ui.map_view import MapView
    from sage_worldbuilder.viewport import ViewOptions

__all__ = ["AtlasProvider", "MapView3D", "ModelProvider", "TerrainMode"]

# Asked to make an atlas for a texture table: its `atlas_key`, and the largest texture the GPU
# takes. The answer comes back through `MapView3D.set_atlas`.
AtlasProvider = Callable[[Hashable, int], None]
# Asked to load the models of these object names; the answer comes back through `set_models`.
ModelProvider = Callable[[list[str]], None]
# Asked for the textures and FX materials of the loaded game; None without one.
ArtProvider = Callable[[], ArtTextures | None]

_BACKGROUND = (24 / 255, 26 / 255, 30 / 255)
_ZOOM_STEP = 1.2
_CIRCLE_POINTS = 48
# Grid lines drawn at most along each axis; a finer grid is not drawn.
_MAX_GRID_LINES = 300
# The light comes from the top left, as in the top-down picture.
_LIGHT = np.array([-1.0, 1.0, 1.4]) / np.linalg.norm([-1.0, 1.0, 1.4])
# The first vertex attribute of an instance's world matrix (four columns).
_INSTANCE_LOCATION = 3
# How far past the terrain under a click a model can be hit and still be picked: a model stands
# on the ground, and a click at its foot can meet the ground a little before it.
_GROUND_SLACK = 5.0

# How a surface is lit: by the map's ambient colour and its three lights for its time of day (a
# light's direction points away from the light), or, without a lighting chunk, by the fixed light.
_LIT_BY = """
vec3 lit_by(vec3 n) {
    if (!map_lights) {
        return vec3(0.45 + 0.65 * max(dot(n, light), 0.0));
    }
    vec3 sum = ambient;
    for (int i = 0; i < 3; ++i) {
        sum += light_color[i] * max(dot(n, -light_direction[i]), 0.0);
    }
    return sum;
}
"""


class TerrainMode:
    """What colours the terrain: a height ramp, the top-down picture, or the game's textures."""

    RAMP = 0
    PICTURE = 1
    TEXTURES = 2


_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec3 position;
layout(location = 1) in vec3 normal;
uniform mat4 mvp;
out vec3 v_normal;
out vec3 v_world;
void main() {
    v_normal = normal;
    v_world = position;
    gl_Position = mvp * vec4(position, 1.0);
}
"""

# The blend weight repeats `terrain_texturing.mask_weight`: keep the two in step.
_FRAGMENT_SHADER = (
    """
#version 330 core
in vec3 v_normal;
in vec3 v_world;
uniform int mode;
uniform sampler2D colors;
uniform usampler2D cell_data;
uniform sampler2D atlas;
uniform int atlas_side;
uniform float atlas_cell_pixels;
uniform vec2 cells;
uniform float border;
uniform vec2 height_range;
uniform vec3 light;
uniform bool map_lights;
uniform vec3 ambient;
uniform vec3 light_color[3];
uniform vec3 light_direction[3];
uniform sampler2D feedback;
uniform bool show_feedback;
uniform sampler2D cliff_corners;
out vec4 color;

"""
    + _LIT_BY
    + """
vec3 tile_color(uint tile, vec2 f, float lod) {
    uint side = uint(atlas_side);
    uint cell = tile >> 2u;
    vec2 slot = vec2(float(cell % side), float(cell / side));
    vec2 quarter = vec2(float(tile & 1u), float((tile >> 1u) & 1u)) * 0.5;
    // Half a texel at this mip level, in texture cells: a sample stays inside the tile's quarter,
    // so the atlas slot next to it never bleeds in.
    float inset = 0.5 * pow(2.0, lod) / atlas_cell_pixels;
    vec2 local = clamp(quarter + f * 0.5, quarter + inset, quarter + 0.5 - inset);
    return textureLod(atlas, (slot + local) / float(atlas_side), lod).rgb;
}

// A cliff-mapped cell (`terrain_texturing.cliff_cells`): its corners' places in its texture's
// picture, in texture cells, across the mesh's two triangles (split from (x, y) to (x + 1, y + 1)).
vec2 cliff_place(ivec2 cell, vec2 f) {
    vec4 lower = texelFetch(cliff_corners, ivec2(cell.x * 2, cell.y), 0);
    vec4 upper = texelFetch(cliff_corners, ivec2(cell.x * 2 + 1, cell.y), 0);
    vec2 a = lower.xy;
    vec2 b = lower.zw;
    vec2 c = upper.xy;
    vec2 d = upper.zw;
    return f.x >= f.y ? a + f.x * (b - a) + f.y * (c - b) : a + f.x * (c - d) + f.y * (d - a);
}

vec3 cliff_color(vec2 place, uint start, uint size, float lod) {
    float s = float(size);
    vec2 p = mod(place, s);
    vec2 whole = min(floor(p), vec2(s - 1.0));
    uint cell = start + uint(whole.y) * size + uint(whole.x);
    uint side = uint(atlas_side);
    vec2 slot = vec2(float(cell % side), float(cell / side));
    float inset = 0.5 * pow(2.0, lod) / atlas_cell_pixels;
    vec2 local = clamp(p - whole, inset, 1.0 - inset);
    return textureLod(atlas, (slot + local) / float(atlas_side), lod).rgb;
}

float blend_weight(uint index, vec2 f) {
    bool inverted = index >= 6u;
    uint shape = index % 6u;
    float x = clamp(f.x * 64.0 - 0.5, 0.0, 63.0);
    float y = clamp(f.y * 64.0 - 0.5, 0.0, 63.0);
    float rise = inverted ? y : 63.0 - y;
    float value;
    if (shape == 0u) {
        value = inverted ? x : 63.0 - x;
    } else if (shape == 1u) {
        value = rise;
    } else if (shape == 3u || shape == 5u) {
        value = rise + (63.0 - x) - (shape == 5u ? 64.0 : 0.0);
    } else {
        value = rise + x - (shape == 4u ? 64.0 : 0.0);
    }
    return 1.0 - clamp(value / 63.0, 0.0, 1.0);
}

void main() {
    vec3 base;
    vec2 position = v_world.xy / 10.0 + border;
    if (mode == 2) {
        ivec2 size = textureSize(cell_data, 0);
        ivec2 cell = clamp(ivec2(floor(position)), ivec2(0), size - 1);
        vec2 f = clamp(position - vec2(cell), 0.0, 1.0);
        // The atlas mip level: a map cell spans half a texture cell, and at most one texel of a
        // quarter is taken, beyond which neighbouring slots would blur into the tile.
        float texels = atlas_cell_pixels * 0.5;
        float rho = max(length(dFdx(position)), length(dFdy(position))) * texels;
        float lod = clamp(log2(max(rho, 1e-6)), 0.0, log2(texels));
        uvec4 data = texelFetch(cell_data, cell, 0);
        // Taken for every cell, so its screen derivatives are defined wherever it is used.
        vec2 place = cliff_place(cell, f);
        float cliff_rho = max(length(dFdx(place)), length(dFdy(place))) * atlas_cell_pixels;
        if ((data.a & 256u) != 0u) {
            float cliff_lod = clamp(log2(max(cliff_rho, 1e-6)), 0.0, log2(atlas_cell_pixels));
            base = cliff_color(place, data.g, max(data.b, 1u), cliff_lod);
        } else {
            base = tile_color(data.r, f, lod);
            uint first = data.a & 15u;
            if (first != 0u) {
                base = mix(base, tile_color(data.g, f, lod), blend_weight(first - 1u, f));
                uint second = (data.a >> 4u) & 15u;
                if (second != 0u) {
                    base = mix(base, tile_color(data.b, f, lod), blend_weight(second - 1u, f));
                }
            }
        }
    } else if (mode == 1) {
        base = texture(colors, (position + 0.5) / cells).rgb;
    } else {
        float span = max(height_range.y - height_range.x, 0.001);
        float h = clamp((v_world.z - height_range.x) / span, 0.0, 1.0);
        base = mix(vec3(70.0, 92.0, 52.0) / 255.0, vec3(214.0, 206.0, 184.0) / 255.0, h);
    }
    vec3 shaded = base * lit_by(normalize(v_normal));
    if (show_feedback) {
        // Each sample's tint covers the half cell around it, as in the top-down view.
        vec4 tint = texture(feedback, (position + 0.5) / cells);
        shaded = mix(shaded, tint.rgb, tint.a);
    }
    color = vec4(shaded, 1.0);
}
"""
)

_MODEL_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec3 position;
layout(location = 1) in vec3 normal;
layout(location = 2) in vec2 uv;
layout(location = 3) in mat4 world;
uniform mat4 view_projection;
out vec3 v_normal;
out vec2 v_uv;
void main() {
    v_normal = mat3(world) * normal;
    v_uv = uv;
    gl_Position = view_projection * world * vec4(position, 1.0);
}
"""

_MODEL_FRAGMENT_SHADER = (
    """
#version 330 core
in vec3 v_normal;
in vec2 v_uv;
uniform sampler2D texture_image;
uniform bool textured;
uniform bool alpha_test;
uniform bool translucent;
uniform bool unlit;
uniform vec4 base_color;
uniform vec3 light;
uniform bool map_lights;
uniform vec3 ambient;
uniform vec3 light_color[3];
uniform vec3 light_direction[3];
out vec4 color;
"""
    + _LIT_BY
    + """
void main() {
    vec4 surface = textured ? texture(texture_image, v_uv) : base_color;
    if (alpha_test && surface.a < 0.5) {
        discard;
    }
    // A mesh that is a picture of light - a flame, a glow, a sky - shows its own brightness;
    // dimming it by the map's lights would put a dark map's night into a fire.
    vec3 level = unlit ? vec3(1.0) : lit_by(normalize(v_normal));
    color = vec4(surface.rgb * level, translucent ? surface.a : 1.0);
}
"""
)

_UNIFORMS = (
    "mvp",
    "mode",
    "colors",
    "cell_data",
    "cliff_corners",
    "atlas",
    "atlas_side",
    "atlas_cell_pixels",
    "cells",
    "border",
    "height_range",
    "light",
    "map_lights",
    "ambient",
    "light_color",
    "light_direction",
    "feedback",
    "show_feedback",
)
_MODEL_UNIFORMS = (
    "view_projection",
    "texture_image",
    "textured",
    "alpha_test",
    "translucent",
    "unlit",
    "base_color",
    "light",
    "map_lights",
    "ambient",
    "light_color",
    "light_direction",
)

_WATER_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec3 position;
layout(location = 1) in vec2 uv;
layout(location = 2) in float depth;
uniform mat4 mvp;
out vec2 v_uv;
out float v_depth;
out vec2 v_world;
void main() {
    v_uv = uv;
    v_depth = depth;
    v_world = position.xy;
    gl_Position = mvp * vec4(position, 1.0);
}
"""

# Draws a `render.water_mesh.WaterLook` as the game's water pixel shaders compute it at time zero:
# a lake's texture in its tint mixed toward the texture alone at the reflection strength, made
# opaque with depth up to the map's Max alpha depth, never below its Deep water alpha; a river's
# texture in its tint plus its opacity texture's colour plus sparkles times noise (one repeat every
# 16 world units), its alpha the product of its textures' and its own.
_WATER_FRAGMENT_SHADER = """
#version 330 core
in vec2 v_uv;
in float v_depth;
in vec2 v_world;
uniform sampler2D surface;
uniform bool textured;
uniform sampler2D opacity;
uniform bool faded;
uniform sampler2D sparkles;
uniform sampler2D noise;
uniform bool sparkling;
uniform vec4 tint;
uniform float uv_scale;
uniform bool reflects;
uniform float reflection;
uniform bool depth_fade;
uniform vec2 depth_alpha;
out vec4 color;
void main() {
    vec4 result = tint;
    if (textured) {
        vec4 picture = texture(surface, v_uv * uv_scale);
        if (reflects) {
            result.rgb = mix(tint.rgb * picture.rgb, picture.rgb, reflection);
        } else {
            result *= picture;
        }
    }
    if (faded) {
        vec4 edge = texture(opacity, v_uv);
        result.a *= edge.a;
        if (!reflects) {
            result.rgb += edge.rgb;
        }
    }
    if (sparkling) {
        result.rgb += texture(sparkles, v_uv).rgb * texture(noise, v_world * 0.0625).rgb;
    }
    if (depth_fade) {
        float reach = depth_alpha.x > 0.0 ? clamp(v_depth / depth_alpha.x, 0.0, 1.0) : 1.0;
        result.a = max(depth_alpha.y, reach);
    }
    color = vec4(min(result.rgb, vec3(1.0)), result.a);
}
"""

_ROAD_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec3 position;
layout(location = 1) in vec2 uv;
uniform mat4 mvp;
out vec2 v_uv;
void main() {
    // `render.road_surface` gives the coordinate the game gives, measured down from the texture's
    // top row, and `ArtTextures` hands OpenGL its pixels bottom row first: so v runs the other way.
    v_uv = vec2(uv.x, 1.0 - uv.y);
    gl_Position = mvp * vec4(position, 1.0);
}
"""

# A road lies on the ground, so it is lit as flat ground is, and its texture's clear edges blend
# it into the terrain. A road type with no texture of its own shows `tint` alone.
_ROAD_FRAGMENT_SHADER = (
    """
#version 330 core
in vec2 v_uv;
uniform sampler2D surface;
uniform bool textured;
uniform vec4 tint;
uniform vec3 light;
uniform bool map_lights;
uniform vec3 ambient;
uniform vec3 light_color[3];
uniform vec3 light_direction[3];
out vec4 color;
"""
    + _LIT_BY
    + """
void main() {
    vec4 surface_color = textured ? texture(surface, v_uv) : tint;
    color = vec4(surface_color.rgb * lit_by(vec3(0.0, 0.0, 1.0)), surface_color.a);
}
"""
)

_ROAD_UNIFORMS = (
    "mvp",
    "surface",
    "textured",
    "tint",
    "light",
    "map_lights",
    "ambient",
    "light_color",
    "light_direction",
)

_WATER_UNIFORMS = (
    "mvp",
    "surface",
    "textured",
    "opacity",
    "faded",
    "tint",
    "uv_scale",
    "reflects",
    "reflection",
    "depth_fade",
    "depth_alpha",
    "sparkles",
    "noise",
    "sparkling",
)


@dataclass
class _Chunk:
    vao: int
    vbo: int
    ebo: int
    count: int


@dataclass
class _Part:
    """One mesh of a model on the GPU."""

    vao: int
    buffers: list[int]
    count: int
    texture: str | None
    color: tuple[float, float, float, float]
    translucent: bool
    alpha_test: bool
    two_sided: bool = False
    additive: bool = False
    unlit: bool = False


@dataclass
class _RoadDraw:
    """The roads drawn with one texture, on the GPU."""

    vao: int
    buffers: list[int]
    count: int
    texture: str | None
    color: tuple[float, float, float, float]


@dataclass
class _WaterDraw:
    """A lake's or river's surface on the GPU, and how it looks."""

    vao: int
    buffers: list[int]
    count: int
    look: WaterLook


@dataclass
class _Model:
    """A model's meshes on the GPU, and the world matrices of the objects showing it; the
    geometry and the matrices are kept here as well, for a click to pick an object by its model."""

    parts: list[_Part]
    instances: int
    geometry: ModelGeometry
    count: int = 0
    objects: list[Object] = field(default_factory=list)
    matrices: np.ndarray = field(default_factory=lambda: np.zeros((0, 4, 4), dtype=np.float32))


def _compile_program(vertex: str, fragment: str) -> int:
    program = glCreateProgram()
    for kind, source in ((GL_VERTEX_SHADER, vertex), (GL_FRAGMENT_SHADER, fragment)):
        shader = glCreateShader(kind)
        glShaderSource(shader, source)
        glCompileShader(shader)
        if not glGetShaderiv(shader, GL_COMPILE_STATUS):
            log = glGetShaderInfoLog(shader)
            raise RuntimeError(log.decode(errors="replace") if isinstance(log, bytes) else str(log))
        glAttachShader(program, shader)
        glDeleteShader(shader)
    glLinkProgram(program)
    if not glGetProgramiv(program, GL_LINK_STATUS):
        log = glGetProgramInfoLog(program)
        raise RuntimeError(log.decode(errors="replace") if isinstance(log, bytes) else str(log))
    return int(program)


# The camera objects: a camera key, the one the preview looks from, a look-at point, the paths,
# and the drag handles' three axes.
_CAMERA_GLYPH = QColor(230, 60, 50)
_CAMERA_CURRENT = QColor(255, 255, 255)
_LOOK_AT_POINT = QColor(150, 40, 200)
_LOOK_AT_PATH = QColor(190, 150, 230, 220)
_HANDLE_COLORS = (QColor(255, 90, 90), QColor(110, 230, 110), QColor(110, 160, 255))
_HANDLE_HELD = QColor(255, 230, 120)
_PREVIEW_FRAME = QColor(210, 210, 215)
_PREVIEW_LABEL = QColor(235, 235, 240)
# The outline the overlay draws round a selected road segment's pieces.
_SELECTED_ROAD = QColor(255, 255, 255)
# The preview pane: its share of the view's width, its limits in pixels, its margin and its shape.
_PREVIEW_SHARE = 0.26
_PREVIEW_MIN, _PREVIEW_MAX = 160, 420
_PREVIEW_MARGIN = 10
_PREVIEW_ASPECT = 3 / 4


class MapView3D(QOpenGLWidget, OverlayPainter):
    # (cell or None, height or None) under the cursor.
    cursor_moved = pyqtSignal(object, object)
    # A tool gesture (a click or a drag) ended.
    gesture_finished = pyqtSignal()
    # A camera object was clicked in the view: its `(kind, index)`, or None for empty ground.
    camera_object_picked = pyqtSignal(object)

    def __init__(self, source: MapView, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        surface = QSurfaceFormat()
        surface.setVersion(3, 3)
        surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        surface.setDepthBufferSize(24)
        surface.setSamples(4)
        self.setFormat(surface)
        self.source = source
        self.camera = Camera()
        self.transform = CameraProjection(self.camera)
        # The world position under the cursor while it is over the view, for Paste.
        self.cursor_world: tuple[float, float] | None = None
        self.message = "No map open."
        # Asked for an atlas of the map's texture cells; None draws without the game's textures.
        self.atlas_provider: AtlasProvider | None = None
        # Asked for the models of object names; None draws objects as markers only.
        self.model_provider: ModelProvider | None = None
        # What colours the terrain in the last frame (`TerrainMode`).
        self.mode = TerrainMode.RAMP
        # While Show From Top Down View is on, the pitch to go back to.
        self._pitch_before_top_down: float | None = None
        # Camera editing: who runs the commands a drag makes, and the drag itself.
        self.camera_host: object | None = None
        self.camera_editor = camera_edit.Editor(self._run_camera_command)
        self._panning = False
        self._orbiting = False
        self._space_down = False
        self._last_mouse: QPointF | None = None
        self._gesture_button = Qt.MouseButton.LeftButton
        self._fitted = False
        # GPU state, made in the widget's own context.
        self._program = 0
        self._uniforms: dict[str, int] = {}
        self._model_program = 0
        self._model_uniforms: dict[str, int] = {}
        self.max_texture_size = 4096
        self._boxes: list[Box] = []
        self._chunks: list[_Chunk] = []
        self._rebuild = True
        self._dirty_chunks: set[int] = set()
        self._colors_texture = 0
        self._colors_shape: tuple[int, ...] | None = None
        self._recolor = True
        # Cells whose heights, tiles or blends changed since the last frame.
        self._terrain_regions: list[Region] = []
        self._use_picture = False
        # The tile feedback views' tints: the texture, and whether it must be made again.
        self._feedback_texture = 0
        self._refeedback = True
        self._use_feedback = False
        self._height_range = (0.0, 1.0)
        # The game's textures: the atlas on the GPU and the table it was made for, one waiting to
        # be sent, the table last asked for, and the per-cell data texture.
        self._atlas_texture = 0
        self._atlas_key: Hashable | None = None
        self._atlas_side = 1
        self._atlas_cell_pixels = 64
        self._pending_atlas: tuple[Hashable, TerrainAtlas] | None = None
        self._requested_key: Hashable | None = None
        self._cells_texture = 0
        self._cells_shape: tuple[int, ...] | None = None
        # Each cliff-mapped cell's corners in its texture (`cliff_cells`), two texels a cell.
        self._cliff_texture = 0
        self._recell = True
        # Blend mask and tile per blend number, for the description list they were made from.
        self._blend_tables: tuple[tuple[int, int], np.ndarray, np.ndarray] | None = None
        # Object models: on the GPU by object name (None for one without a model), loads waiting
        # to be sent, names asked for, model textures by lower-case name, and whether the objects'
        # world matrices must be worked out again.
        self._models: dict[str, _Model | None] = {}
        self._pending_models: list[
            tuple[Mapping[str, ModelGeometry | None], Mapping[str, np.ndarray | None]]
        ] = []
        self._requested_models: set[str] = set()
        self._model_textures: dict[str, int] = {}
        self._reinstance = True
        self._visibility: object = None
        # The map's objects by the model they show, as last worked out, and the tool's ghosts
        # drawn with them: what they were, and the models they were drawn with.
        self._groups: dict[str, list[Object]] = {}
        self._ghosts: object = ()
        self._ghost_names: set[str] = set()
        # The game's damage thresholds (`MapConditions.of_game`), which the window sets, and the
        # conditions every object's model was last chosen under.
        self.damage_thresholds = MapConditions()
        self._conditions: MapConditions | None = None
        # Where the water and road textures are read from.
        self.art_provider: ArtProvider | None = None
        # Water surfaces: the program, the areas' meshes on the GPU (and the ids of the areas
        # drawn), textures by lower-case name (0 for one that cannot be read), and whether the
        # meshes must be made again. A terrain edit changes the water's depths, so its meshes are
        # made again once the gesture ends.
        self._water_program = 0
        self._water_uniforms: dict[str, int] = {}
        self._water: list[_WaterDraw] = []
        self._water_drawn: set[int] = set()
        self._water_textures: dict[str, int] = {}
        self._rewater = True
        self._water_depths_stale = False
        self._water_visibility: object = None
        # Roads on the ground: the program, the draped surfaces on the GPU, road textures by
        # lower-case name (0 for one that cannot be read), and what the surfaces were made for
        # (the pieces, the shown items and the terrain), so they are made again when it changes.
        self._road_program = 0
        self._road_uniforms: dict[str, int] = {}
        self._roads: list[_RoadDraw] = []
        self._road_textures: dict[str, int] = {}
        self._road_key: object = None
        self._road_heights_stale = False
        # Why the view cannot draw, once OpenGL has failed.
        self.failure: str | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(200, 150)
        self.set_document(source.document)

    # The state shared with the top-down view.

    @property
    def document(self) -> MapDocument | None:  # type: ignore[override]
        return self.source.document

    @property
    def options(self) -> ViewOptions:  # type: ignore[override]
        return self.source.options

    @property
    def scene(self) -> MapScene | None:  # type: ignore[override]
        return self.source.scene

    @property
    def tool(self) -> Tool:
        return self.source.tool

    @property
    def footprints(self) -> Footprints | None:  # type: ignore[override]
        return self.source.footprints

    @property
    def build_entry(self) -> object:  # type: ignore[override]
        return self.source.build_entry

    @property
    def influences(self) -> Influences | None:  # type: ignore[override]
        return self.source.influences

    @property
    def road_styles(self) -> RoadStyles | None:  # type: ignore[override]
        return self.source.road_styles

    @property
    def camera_path(self) -> object:  # type: ignore[override]
        return self.source.camera_path

    @property
    def camera_scene(self) -> CameraScene | None:
        """What the Cameras panel puts in the world: the chosen animation's keys as objects, its
        paths, and the pose the preview looks from. None when the panel shows nothing."""
        return self.source.camera_scene

    def show_camera(self, view: object) -> None:
        """Look as a `cameras.CameraView` does: its target, yaw, pitch, distance and field of
        view (the pitch kept within the view's own limits)."""
        camera = self.camera
        target = getattr(view, "target")  # noqa: B009 - a CameraView, typed loosely here
        camera.look_at(*target)
        camera.yaw = float(getattr(view, "yaw")) % 360.0  # noqa: B009
        camera.pitch = min(MAX_PITCH, max(MIN_PITCH, float(getattr(view, "pitch"))))  # noqa: B009
        camera.distance = min(MAX_DISTANCE, max(MIN_DISTANCE, float(getattr(view, "distance"))))  # noqa: B009
        camera.fov = float(getattr(view, "fov"))  # noqa: B009
        self._pitch_before_top_down = None
        self.transform.moved()
        self.update()

    @property
    def gesture_active(self) -> bool:
        return self.source.gesture_active

    @gesture_active.setter
    def gesture_active(self, active: bool) -> None:
        self.source.gesture_active = active

    def is_shown(self, source: object) -> bool:
        return self.source.is_shown(source)

    # Keeping in step with the document.

    def set_document(self, document: MapDocument | None) -> None:
        self.transform.grid = document.terrain if document is not None else None
        self.transform.focus = None
        self.cursor_world = None
        self._rebuild = True
        self._recolor = True
        self._recell = True
        self._reinstance = True
        self._fitted = False
        self.fit_map()

    def on_change(self, change: Change) -> None:
        if change.kind in (ChangeKind.TERRAIN, ChangeKind.WHOLE):
            document = self.document
            grid = document.terrain if document is not None else None
            if grid is not self.transform.grid:
                self.transform.grid = grid
                self._rebuild = True
            if change.kind is ChangeKind.TERRAIN and change.region is not None:
                if not self._rebuild:
                    self._dirty_chunks.update(chunks_touching(self._boxes, change.region))
                self._terrain_regions.append(change.region)
            else:
                self._rebuild = True
                self._recolor = True
                self._recell = True
        if change.kind in (ChangeKind.WATER, ChangeKind.WHOLE):
            self._rewater = True
        elif change.kind is ChangeKind.TERRAIN:
            self._water_depths_stale = True
        if change.kind in (ChangeKind.TERRAIN, ChangeKind.WHOLE):
            self._road_heights_stale = True
        if change.kind in (ChangeKind.OBJECTS, ChangeKind.TERRAIN, ChangeKind.WHOLE):
            self._reinstance = True
        self.update()

    def colors_changed(self) -> None:
        self._recolor = True
        self._refeedback = True
        self.update()

    def feedback_changed(self) -> None:
        """The tile feedback views changed: make their tints again with the next frame."""
        self._refeedback = True
        self.update()

    def textures_changed(self) -> None:
        """The game's art may read differently now (game data loaded or changed): ask again for
        the atlas when the one on the GPU is not the map's, and for models not loaded yet."""
        self._requested_key = None
        self._requested_models.clear()
        self._reinstance = True
        self.update()

    def set_atlas(self, key: Hashable, atlas: TerrainAtlas) -> None:
        """The atlas made for the texture table `key`; sent to the GPU with the next frame."""
        self._pending_atlas = (key, atlas)
        self.update()

    def set_models(
        self,
        models: Mapping[str, ModelGeometry | None],
        textures: Mapping[str, np.ndarray | None],
    ) -> None:
        """Models loaded for object names (None for one without a model) and their textures'
        pixels by lower-case name; sent to the GPU with the next frame."""
        self._pending_models.append((models, textures))
        self.update()

    def map_bounds(self) -> tuple[float, float, float, float] | None:
        return self.source.map_bounds()

    @property
    def top_down(self) -> bool:
        return self._pitch_before_top_down is not None

    def set_top_down(self, on: bool) -> None:
        """Show From Top Down View: look straight down at the target; turned off, the camera
        takes back the pitch it had."""
        if on == self.top_down:
            return
        if on:
            self._pitch_before_top_down = self.camera.pitch
            self.camera.pitch = MAX_PITCH
        else:
            assert self._pitch_before_top_down is not None
            self.camera.pitch = self._pitch_before_top_down
            self._pitch_before_top_down = None
        self.transform.moved()
        self.update()

    def game_camera(self) -> bool:
        """Look at the target the way the map's camera settings do: from its pitch and yaw,
        at its maximum camera height above the ground. False when the map stores none; the
        field of view stays the view's own."""
        document = self.document
        info = document.map.world_info if document is not None else None
        properties = getattr(info, "properties", None) or {}

        def number(key: str) -> float | None:
            stored = properties.get(key)
            try:
                return float(stored["value"]) if stored is not None else None
            except (TypeError, ValueError):
                return None

        pitch, yaw = number("cameraPitchAngle"), number("cameraYawAngle")
        height = number("cameraMaxHeight")
        if pitch is None or height is None or height <= 0:
            return False
        camera = self.camera
        camera.pitch = min(MAX_PITCH, max(MIN_PITCH, pitch))
        camera.yaw = (yaw or 0.0) % 360.0
        distance = height / math.sin(math.radians(camera.pitch))
        camera.distance = min(MAX_DISTANCE, max(MIN_DISTANCE, distance))
        self._pitch_before_top_down = None
        self.transform.moved()
        self.update()
        return True

    def models_changed(self) -> None:
        """Which model an object shows changed: drop the loaded models and ask for them
        again. Their textures are kept."""
        self._pending_models.clear()
        self._requested_models.clear()
        context = self.context()
        if context is not None and context.isValid():
            self.makeCurrent()
            for name in list(self._models):
                self._release_model(name)
            self.doneCurrent()
        self._models.clear()
        self._reinstance = True
        self.update()

    def reload_art(self) -> None:
        """Reload Textures: forget the terrain atlas and the object models, so they are asked
        for again."""
        self._atlas_key = self._requested_key = None
        self._pending_atlas = None
        self._pending_models.clear()
        self._requested_models.clear()
        context = self.context()
        if context is not None and context.isValid():
            self.makeCurrent()
            for name in list(self._models):
                self._release_model(name)
            if self._model_textures:
                glDeleteTextures(len(self._model_textures), list(self._model_textures.values()))
            self._release_water(textures=True)
            self._release_roads(textures=True)
            self.doneCurrent()
        self._models.clear()
        self._model_textures.clear()
        # Without a context the GPU objects went with it: forget them all the same.
        self._water = []
        self._water_drawn = set()
        self._water_textures.clear()
        self._rewater = True
        self._roads = []
        self._road_textures.clear()
        self._road_key = None
        self._reinstance = True
        self.update()

    def fit_map(self) -> None:
        """Look at the whole map."""
        self.camera.width, self.camera.height = max(self.width(), 1), max(self.height(), 1)
        bounds, grid = self.map_bounds(), self.transform.grid
        if bounds is not None and grid is not None:
            z = float(grid.heights.mean()) * FEET_PER_HEIGHT_UNIT
            self.camera.fit(*bounds, z)
            self._fitted = True
        self.transform.moved()
        self.update()

    def zoom_to(self, x: float, y: float, scale: float = 1.0) -> None:
        """Aim at a world position, coming in to at least `scale` pixels per world unit there."""
        camera = self.camera
        camera.look_at(x, y, self.transform.ground(x, y))
        focal = camera.pixels_per_unit_at(camera.target) * camera.distance
        camera.zoom(max(camera.distance / (focal / scale), 1.0))
        self.transform.moved()
        self.update()

    def paste_position(self) -> tuple[float, float]:
        if self.cursor_world is not None:
            return self.cursor_world
        return self.camera.target_x, self.camera.target_y

    def resizeEvent(self, event: QResizeEvent | None) -> None:  # noqa: N802 - Qt override
        self.camera.width, self.camera.height = max(self.width(), 1), max(self.height(), 1)
        self.transform.moved()
        if not self._fitted:
            self.fit_map()
        super().resizeEvent(event)

    # Projection hooks for the overlays.

    def _to_screen(self, x: float, y: float) -> QPointF | None:
        point = self.transform.project(x, y)
        return QPointF(*point) if point is not None else None

    def _flag_points(self, marker: Marker) -> list[QPointF] | None:
        """A sound flag stands in the world, on the ground under the object, as the game's."""
        ground = self.transform.ground(marker.x, marker.y)
        points = []
        for along, up in SOUND_FLAG:
            point = self.transform.project(marker.x + along, marker.y, ground + up)
            if point is None:
                return None
            points.append(QPointF(*point))
        return points

    def _screen_points(self, markers: Sequence[Marker]) -> list[QPointF | None]:
        if not markers:
            return []
        grid = self.transform.grid
        xs = np.fromiter((marker.x for marker in markers), dtype=np.float64, count=len(markers))
        ys = np.fromiter((marker.y for marker in markers), dtype=np.float64, count=len(markers))
        zs = ground_heights(grid, xs, ys) if grid is not None else np.zeros_like(xs)
        pixels, in_front = self.camera.project(np.stack((xs, ys, zs), axis=1))
        return [
            QPointF(sx, sy) if front else None
            for (sx, sy), front in zip(pixels.tolist(), in_front.tolist(), strict=True)
        ]

    def _screen_path(
        self, points: Sequence[tuple[float, float]], closed: bool = False
    ) -> list[QPointF] | None:
        """The outline on the ground, cut where it passes behind the camera; empty where none of
        it is in front."""
        return [QPointF(sx, sy) for sx, sy in self.transform.ground_path(points, closed)]

    def _world_circle(self, painter: QPainter, x: float, y: float, radius: float) -> None:
        corners = [
            (
                x + radius * math.cos(2 * math.pi * k / _CIRCLE_POINTS),
                y + radius * math.sin(2 * math.pi * k / _CIRCLE_POINTS),
            )
            for k in range(_CIRCLE_POINTS)
        ]
        path = self._screen_path(corners, closed=True)
        if path is not None:
            painter.drawPolygon(QPolygonF(path))

    def _draw_grid(self, painter: QPainter) -> None:
        settings, bounds = self.options.grid, self.transform.visible_world()
        assert settings is not None
        spacing = settings.spacing
        x0, y0, x1, y1 = bounds
        if spacing <= 0 or max(x1 - x0, y1 - y0) / spacing > _MAX_GRID_LINES:
            return
        painter.setPen(QPen(GRID_COLOR, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for x in _lines(x0, x1, spacing):
            path = self._screen_path([(x, y0), (x, y1)])
            if path is not None:
                painter.drawPolyline(QPolygonF(path))
        for y in _lines(y0, y1, spacing):
            path = self._screen_path([(x0, y), (x1, y)])
            if path is not None:
                painter.drawPolyline(QPolygonF(path))

    # The camera objects.

    def _point(self, position: Sequence[float]) -> QPointF | None:
        """Pixels for a world point at its own height, or None behind the camera."""
        pixels = self.transform.project(position[0], position[1], position[2])
        return QPointF(*pixels) if pixels is not None else None

    def _draw_world_segments(
        self, painter: QPainter, segments: Sequence[tuple[Sequence[float], Sequence[float]]]
    ) -> None:
        """Lines between world points, leaving out any with an end behind the camera."""
        for start, end in segments:
            first, second = self._point(start), self._point(end)
            if first is not None and second is not None:
                painter.drawLine(first, second)

    def _draw_world_polyline(self, painter: QPainter, points: Sequence[Sequence[float]]) -> None:
        """A path through world points, broken where it passes behind the camera."""
        run: list[QPointF] = []
        for point in points:
            pixel = self._point(point)
            if pixel is None:
                if len(run) > 1:
                    painter.drawPolyline(QPolygonF(run))
                run = []
                continue
            run.append(pixel)
        if len(run) > 1:
            painter.drawPolyline(QPolygonF(run))

    def _run_camera_command(self, command: object) -> None:
        if self.camera_host is not None:
            self.camera_host.execute(command)

    def _camera_size(self, position: Sequence[float], pixels: float) -> float:
        """A length in world units that spans `pixels` on screen at a point, so the camera
        objects and their handles stay the same size however far away they are."""
        return pixels / max(self.camera.pixels_per_unit_at(position), 1e-6)

    def _draw_camera_path(self, painter: QPainter) -> None:
        """The Cameras panel's objects: the camera's and the look-at point's paths at their own
        heights, each camera key drawn as a camera, look-at keys as markers, the preview's
        frustum, and the drag handles on the chosen object. Without a scene (the panel shows
        nothing, or this is the top-down view) the flat path on the ground is drawn instead."""
        scene = self.camera_scene
        if scene is None:
            super()._draw_camera_path(painter)
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        paths = ((scene.camera_path, _CAMERA_PATH), (scene.look_at_path, _LOOK_AT_PATH))
        for path, color in paths:
            if path:
                painter.setPen(QPen(color, 1.5, Qt.PenStyle.DashLine))
                self._draw_world_polyline(painter, path)
        if scene.preview is not None:
            self._draw_frustum(painter, scene)
        held = self.camera_editor.held(scene)
        for obj in scene.objects:
            self._draw_camera_object(painter, obj, held is not None and obj.key == held.key)
        self._draw_camera_handles(painter, scene)

    def _draw_frustum(self, painter: QPainter, scene: CameraScene) -> None:
        """What the preview sees, as the pyramid out to its far clip distance."""
        pose = scene.preview
        assert pose is not None
        forward, up = pose_axes(pose)
        rect = self.preview_rect()
        aspect = rect.width() / rect.height() if rect is not None else 4 / 3
        painter.setPen(QPen(_CAMERA_CURRENT, 1.0))
        self._draw_world_segments(
            painter,
            camera_edit.frustum_segments(
                pose.position,
                forward,
                up,
                pose.fov if pose.fov > 0 else math.radians(FIELD_OF_VIEW),
                max(scene.far_clip, 10.0),
                aspect,
            ),
        )

    def _draw_camera_object(
        self, painter: QPainter, obj: camera_edit.CameraObject, chosen: bool
    ) -> None:
        """A camera key as a wireframe camera, a look-at point as a marker; the chosen one is
        drawn white."""
        center = self._point(obj.position)
        if center is None:
            return
        if obj.is_camera:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            color = _CAMERA_CURRENT if chosen else _CAMERA_GLYPH
            painter.setPen(QPen(color, 2.0 if chosen else 1.2))
            size = self._camera_size(obj.position, camera_edit.GLYPH_PIXELS)
            self._draw_world_segments(painter, camera_edit.glyph_segments(obj, size))
            return
        painter.setPen(QPen(_CAMERA_CURRENT, 1.5) if chosen else QPen(Qt.PenStyle.NoPen))
        painter.setBrush(QBrush(_LOOK_AT_POINT))
        radius = camera_edit.GLYPH_PIXELS / 2
        corners = [
            QPointF(
                center.x() + radius * math.cos(step / 6 * math.tau),
                center.y() + radius * math.sin(step / 6 * math.tau),
            )
            for step in range(6)
        ]
        painter.drawPolygon(QPolygonF(corners))

    def _draw_camera_handles(self, painter: QPainter, scene: CameraScene) -> None:
        """The chosen object's drag handles: an arrow along each axis, in the map's directions or
        the camera's own, coloured x red, y green, z blue."""
        obj = self.camera_editor.held(scene)
        if obj is None:
            return
        axes = camera_edit.handle_axes(obj, scene.system, scene.motion)
        origin = self._point(obj.position)
        if origin is None or not axes:
            return
        length = self._camera_size(obj.position, camera_edit.HANDLE_PIXELS)
        drag = self.camera_editor.drag
        held = drag.axis if drag is not None else None
        tips = camera_edit.handle_tips(obj.position, axes, length)
        for index, (tip, (name, axis)) in enumerate(zip(tips, axes, strict=True)):
            end = self._point(tip)
            if end is None:
                continue
            hovered = self.camera_editor.hover == (obj.kind, obj.index, index)
            color = _HANDLE_HELD if (held == axis or hovered) else _HANDLE_COLORS[index]
            painter.setPen(QPen(color, 2.0))
            painter.setBrush(QBrush(color))
            painter.drawLine(origin, end)
            head = arrow_head((origin.x(), origin.y()), (end.x(), end.y()))
            if head is not None:
                painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in head]))
            if scene.motion == camera_edit.ROTATE:
                draw_label(painter, end + QPointF(6, -6), name[0], color)

    def _draw_preview_frame(self, painter: QPainter, rect: QRectF) -> None:
        """The camera preview's border and the lens it is looking through."""
        scene = self.camera_scene
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_PREVIEW_FRAME, 1.0))
        painter.drawRect(rect)
        if scene is None or scene.preview is None:
            return
        painter.setPen(QPen(_PREVIEW_LABEL))
        focal = focal_length(scene.preview.fov) if scene.preview.fov > 0 else 0.0
        painter.drawText(
            rect.adjusted(4, 2, -4, -2),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            f"Camera preview  {focal:.0f}mm",
        )

    # Drawing.

    def initializeGL(self) -> None:  # noqa: N802 - Qt override
        try:
            self._program = _compile_program(_VERTEX_SHADER, _FRAGMENT_SHADER)
            self._uniforms = {
                name: int(glGetUniformLocation(self._program, name)) for name in _UNIFORMS
            }
            self._model_program = _compile_program(_MODEL_VERTEX_SHADER, _MODEL_FRAGMENT_SHADER)
            self._model_uniforms = {
                name: int(glGetUniformLocation(self._model_program, name))
                for name in _MODEL_UNIFORMS
            }
            self._water_program = _compile_program(_WATER_VERTEX_SHADER, _WATER_FRAGMENT_SHADER)
            self._water_uniforms = {
                name: int(glGetUniformLocation(self._water_program, name))
                for name in _WATER_UNIFORMS
            }
            self._road_program = _compile_program(_ROAD_VERTEX_SHADER, _ROAD_FRAGMENT_SHADER)
            self._road_uniforms = {
                name: int(glGetUniformLocation(self._road_program, name)) for name in _ROAD_UNIFORMS
            }
            self.max_texture_size = int(glGetIntegerv(GL_MAX_TEXTURE_SIZE))
        except Exception as exc:  # noqa: BLE001 - any GL failure leaves the view showing why
            self.failure = f"The 3D view cannot draw: {exc}"

    def paintGL(self) -> None:  # noqa: N802 - Qt override
        document = self.document
        if self.failure is None:
            try:
                self._draw_world(document)
            except Exception as exc:  # noqa: BLE001 - keep the widget alive, show the error
                self.failure = f"The 3D view cannot draw: {exc}"
        painter = QPainter(self)
        if self.failure is not None or document is None:
            painter.fillRect(self.rect(), QColor(24, 26, 30))
            painter.setPen(QColor(200, 200, 200))
            text = self.failure if self.failure is not None else self.message
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
        else:
            preview = self.preview_rect()
            if preview is not None:
                painter.setClipRegion(
                    QRegion(self.rect()).subtracted(QRegion(preview.toAlignedRect()))
                )
            self._draw_overlays(painter)
            self.tool.paint(self, painter)
            self._draw_frames(painter)
            if preview is not None:
                painter.setClipping(False)
                self._draw_preview_frame(painter, preview)
        painter.end()

    def _draw_frames(self, painter: QPainter) -> None:
        """Show Letterbox's black bars and the safe frame, over everything else."""
        width, height = self.width(), self.height()
        if self.options.show_letterbox:
            band = letterbox_band(width, height)
            if band > 0:
                painter.fillRect(0, 0, width, band, Qt.GlobalColor.black)
                painter.fillRect(0, height - band, width, band, Qt.GlobalColor.black)
        if self.options.show_safe_frame:
            left, top, frame_width, frame_height, band = safe_frame(
                width, height, self.options.safe_frame_scale
            )
            painter.setPen(QPen(Qt.GlobalColor.black, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(left, top, frame_width, frame_height)
            if band > 0:
                painter.drawRect(left, top, frame_width, band)
                painter.drawRect(left, top + frame_height - band, frame_width, band)

    def _draw_world(self, document: MapDocument | None) -> None:
        ratio = self.devicePixelRatioF()
        glViewport(0, 0, int(self.width() * ratio), int(self.height() * ratio))
        glClearColor(*_BACKGROUND, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        grid = document.terrain if document is not None else None
        if document is None or grid is None:
            self._release()
            return
        self._sync(document, grid)
        if not self._chunks:
            return
        glEnable(GL_DEPTH_TEST)
        glDisable(GL_CULL_FACE)
        self._sync_models(document, grid)
        matrix = np.ascontiguousarray(self.camera.matrix(), dtype=np.float32)
        self._draw_pass(document, grid, matrix)
        self._draw_preview(document, grid, ratio)
        # Leave the state as QPainter expects it.
        glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
        glBindVertexArray(0)
        for unit in (GL_TEXTURE4, GL_TEXTURE3, GL_TEXTURE2, GL_TEXTURE1, GL_TEXTURE0):
            glActiveTexture(unit)
            glBindTexture(GL_TEXTURE_2D, 0)
        glUseProgram(0)
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_BLEND)
        glDepthMask(GL_TRUE)

    def _draw_pass(self, document: MapDocument, grid: TerrainGrid, matrix: np.ndarray) -> None:
        """The terrain, the roads on it, the objects and the water through one matrix: the view's
        own camera, or the camera preview's."""
        glPolygonMode(GL_FRONT_AND_BACK, GL_LINE if self.options.wireframe else GL_FILL)
        self._draw_terrain(document, grid, matrix)
        if self.options.show_roads:
            self._draw_road_surfaces(grid, matrix)
        if self.options.show_objects:
            self._draw_models(matrix)
        if self.options.show_water:
            self._draw_water_surfaces(document, grid, matrix)

    def preview_rect(self) -> QRectF | None:
        """Where the camera preview is drawn, in widget pixels: a pane in the top-left corner,
        a quarter of the view across. None when no preview is shown."""
        scene = self.camera_scene
        if scene is None or scene.preview is None:
            return None
        width = min(max(self.width() * _PREVIEW_SHARE, _PREVIEW_MIN), _PREVIEW_MAX)
        height = width * _PREVIEW_ASPECT
        if width + _PREVIEW_MARGIN * 2 > self.width():
            return None
        if height + _PREVIEW_MARGIN * 2 > self.height():
            return None
        return QRectF(_PREVIEW_MARGIN, _PREVIEW_MARGIN, width, height)

    def _draw_preview(self, document: MapDocument, grid: TerrainGrid, ratio: float) -> None:
        """The scene again, in the preview pane, from the pose the Cameras panel asks for: the
        animation at its frame, seen through its own field of view and out to its far clip."""
        scene = self.camera_scene
        rect = self.preview_rect()
        if rect is None or scene is None or scene.preview is None:
            return
        pose = scene.preview
        forward, up = pose_axes(pose)
        matrix = np.ascontiguousarray(
            pose_matrix(
                pose.position,
                forward,
                up,
                math.degrees(pose.fov) if pose.fov > 0 else FIELD_OF_VIEW,
                max(int(rect.width()), 1),
                max(int(rect.height()), 1),
                far=max(scene.far_clip, 10.0),
            ),
            dtype=np.float32,
        )
        left = int(rect.x() * ratio)
        bottom = int((self.height() - rect.y() - rect.height()) * ratio)
        width, height = int(rect.width() * ratio), int(rect.height() * ratio)
        glViewport(left, bottom, width, height)
        glScissor(left, bottom, width, height)
        glEnable(GL_SCISSOR_TEST)
        glClearColor(*_BACKGROUND, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self._draw_pass(document, grid, matrix)
        glDisable(GL_SCISSOR_TEST)
        glViewport(0, 0, int(self.width() * ratio), int(self.height() * ratio))

    def _send_lights(self, uniforms: dict[str, int], target: LightTarget) -> None:
        """A target's lights in the map's time of day, or the fixed light without a lighting
        chunk."""
        document = self.document
        lighting = document.map.global_lighting if document is not None else None
        lights = scene_lights(lighting, target)
        glUniform3f(uniforms["light"], *(float(v) for v in _LIGHT))
        glUniform1i(uniforms["map_lights"], int(lights is not None))
        if lights is None:
            return
        ambient, colors, directions = lights
        glUniform3f(uniforms["ambient"], *(float(v) for v in ambient))
        glUniform3fv(uniforms["light_color"], 3, np.asarray(colors, dtype=np.float32))
        glUniform3fv(uniforms["light_direction"], 3, np.asarray(directions, dtype=np.float32))

    def _draw_terrain(self, document: MapDocument, grid: TerrainGrid, matrix: np.ndarray) -> None:
        self.mode = self._choose_mode(document)
        rows, columns = grid.heights.shape
        glUseProgram(self._program)
        uniforms = self._uniforms
        glUniformMatrix4fv(uniforms["mvp"], 1, GL_TRUE, matrix)
        glUniform1i(uniforms["mode"], self.mode)
        glUniform2f(uniforms["cells"], float(columns), float(rows))
        glUniform1f(uniforms["border"], float(grid.border))
        glUniform2f(uniforms["height_range"], *self._height_range)
        self._send_lights(uniforms, LightTarget.TERRAIN)
        glUniform1i(uniforms["atlas_side"], self._atlas_side)
        glUniform1f(uniforms["atlas_cell_pixels"], float(self._atlas_cell_pixels))
        glUniform1i(uniforms["show_feedback"], int(self._use_feedback))
        for unit, (name, texture) in enumerate(
            (
                ("colors", self._colors_texture),
                ("cell_data", self._cells_texture),
                ("atlas", self._atlas_texture),
                ("feedback", self._feedback_texture),
                ("cliff_corners", self._cliff_texture),
            )
        ):
            glActiveTexture((GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_TEXTURE3, GL_TEXTURE4)[unit])
            glBindTexture(GL_TEXTURE_2D, texture)
            glUniform1i(uniforms[name], unit)
        for index in self._drawn_chunks(grid):
            chunk = self._chunks[index]
            glBindVertexArray(chunk.vao)
            glDrawElements(GL_TRIANGLES, chunk.count, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)

    def _drawn_chunks(self, grid: TerrainGrid) -> Sequence[int]:
        """Every chunk, or with Show All of 3d Map off those within half the Partial Map Size
        of the camera's target."""
        options = self.options
        if options.show_entire_map:
            return range(len(self._chunks))
        camera = self.camera
        radius = options.partial_map_size / 2 * WORLD_UNITS_PER_CELL
        return chunks_near(self._boxes, grid.border, camera.target_x, camera.target_y, radius)

    def _choose_mode(self, document: MapDocument) -> int:
        """The game's textures when their atlas matches the map's texture table (asking for one
        when it does not), else the top-down picture, else the height ramp."""
        blend = document.map.blend_tile_data
        if not self.options.show_texture or blend is None:
            return TerrainMode.RAMP
        key = atlas_key(blend.textures)
        if self._atlas_key == key and self._cells_texture:
            return TerrainMode.TEXTURES
        if self.atlas_provider is not None and self._requested_key != key:
            self._requested_key = key
            self.atlas_provider(key, self.max_texture_size)
        return TerrainMode.PICTURE if self._use_picture else TerrainMode.RAMP

    def _sync(self, document: MapDocument, grid: TerrainGrid) -> None:
        """Bring the GPU's copy of the terrain up to date with the document."""
        if self._rebuild:
            self._release_chunks()
            rows, columns = grid.heights.shape
            self._boxes = chunk_boxes(columns, rows)
            self._chunks = [self._upload_chunk(grid, box) for box in self._boxes]
            self._height_range = (
                float(grid.heights.min()) * FEET_PER_HEIGHT_UNIT,
                float(grid.heights.max()) * FEET_PER_HEIGHT_UNIT,
            )
            self._rebuild = False
            self._dirty_chunks.clear()
        elif self._dirty_chunks:
            for index in sorted(self._dirty_chunks):
                if index < len(self._chunks):
                    vertices = chunk_vertices(grid, self._boxes[index])
                    glBindBuffer(GL_ARRAY_BUFFER, self._chunks[index].vbo)
                    glBufferSubData(GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            self._dirty_chunks.clear()
        regions, self._terrain_regions = self._terrain_regions, []
        if self._recolor:
            self._upload_colors(grid)
            self._recolor = False
        else:
            for region in regions:
                self._patch_colors(grid, region)
        if self._recell or self._blend_tables_stale(document):
            self._upload_cells(document)
            self._recell = False
        else:
            for region in regions:
                self._patch_cells(document, region)
        if self._pending_atlas is not None:
            key, atlas = self._pending_atlas
            self._pending_atlas = None
            self._upload_atlas(key, atlas)
        if self._refeedback:
            self._refeedback = False
            self._upload_feedback()

    def _upload_chunk(self, grid: TerrainGrid, box: Box) -> _Chunk:
        x0, y0, x1, y1 = box
        vertices = chunk_vertices(grid, box)
        indices = grid_indices(x1 - x0 + 1, y1 - y0 + 1)
        vao = int(glGenVertexArrays(1))
        glBindVertexArray(vao)
        vbo = int(glGenBuffers(1))
        glBindBuffer(GL_ARRAY_BUFFER, vbo)
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_DYNAMIC_DRAW)
        ebo = int(glGenBuffers(1))
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(12))
        glEnableVertexAttribArray(1)
        glBindVertexArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        return _Chunk(vao, vbo, ebo, int(indices.size))

    def _picture(self, grid: TerrainGrid) -> np.ndarray | None:
        """The top-down view's texture colour picture, when there is one to colour the mesh."""
        picture = self.source.base_colors if self.options.show_texture else None
        rows, columns = grid.heights.shape
        if not (
            isinstance(picture, np.ndarray) and picture.ndim == 3 and picture.shape[2] in (3, 4)
        ):
            return None
        scale = picture.shape[0] // rows
        if scale < 1 or picture.shape[:2] != (rows * scale, columns * scale):
            return None
        return picture

    def _upload_colors(self, grid: TerrainGrid) -> None:
        picture = self._picture(grid)
        self._use_picture = picture is not None
        if picture is None:
            return
        if not self._colors_texture:
            self._colors_texture = int(glGenTextures(1))
        pixels = np.ascontiguousarray(picture, dtype=np.uint8)
        external, internal = (GL_RGB, GL_RGB8) if pixels.shape[2] == 3 else (GL_RGBA, GL_RGBA8)
        _send_texture(self._colors_texture, pixels, internal, external, GL_UNSIGNED_BYTE, True)
        self._colors_shape = pixels.shape

    def _patch_colors(self, grid: TerrainGrid, region: Region) -> None:
        """Re-send the picture's cells of `region`, and the ring around them its blends read."""
        picture = self._picture(grid)
        if picture is None or not self._use_picture or picture.shape != self._colors_shape:
            self._upload_colors(grid)
            return
        rows, columns = grid.heights.shape
        scale = picture.shape[0] // rows
        x0, y0 = max(region.x0 - 1, 0), max(region.y0 - 1, 0)
        x1, y1 = min(region.x1 + 1, columns), min(region.y1 + 1, rows)
        if x0 >= x1 or y0 >= y1:
            return
        block = np.ascontiguousarray(
            picture[y0 * scale : y1 * scale, x0 * scale : x1 * scale], dtype=np.uint8
        )
        external = GL_RGB if block.shape[2] == 3 else GL_RGBA
        _patch_texture(
            self._colors_texture, block, x0 * scale, y0 * scale, external, GL_UNSIGNED_BYTE, True
        )

    def _blend_tables_stale(self, document: MapDocument) -> bool:
        """Whether the blend descriptions were replaced (not just added to) since the cell data
        was made: every cell's masks may then mean something else."""
        blend = document.map.blend_tile_data
        tables = self._blend_tables
        return (
            blend is not None
            and tables is not None
            and tables[0][0] != id(blend.blend_descriptions)
        )

    def _cell_data(
        self, document: MapDocument, box: tuple[int, int, int, int] | None
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """The cell data and the cliff corner texels of the map, or of the box's cells."""
        blend = document.map.blend_tile_data
        layers = {layer: document.cells(layer) for layer in TileLayer}
        tiles = layers[TileLayer.TILES]
        blends, three_way = layers[TileLayer.BLENDS], layers[TileLayer.THREE_WAY_BLENDS]
        grid = document.terrain
        if blend is None or tiles is None or blends is None or three_way is None or grid is None:
            return None
        if tiles.shape != grid.heights.shape:
            return None
        descriptions = blend.blend_descriptions
        key = (id(descriptions), len(descriptions))
        if self._blend_tables is None or self._blend_tables[0] != key:
            self._blend_tables = (key, mask_indices(descriptions), blend_secondaries(descriptions))
        _, indices, secondaries = self._blend_tables
        cliffs = layers[TileLayer.CLIFF_TEXTURES]
        area = np.s_[:, :] if box is None else np.s_[box[1] : box[3], box[0] : box[2]]
        mapped = cliffs[area] if cliffs is not None and cliffs.shape == tiles.shape else None
        cliff = (
            cliff_cells(tiles[area], mapped, blend.cliff_texture_mappings, blend.textures)
            if mapped is not None
            else None
        )
        data = cell_data(
            tiles[area], blends[area], three_way[area], mapped, indices, secondaries, cliff
        )
        rows, columns = data.shape[:2]
        corners = (
            cliff.corners.reshape(rows, columns * 2, 4)
            if cliff is not None
            else np.zeros((rows, columns * 2, 4), dtype=np.float32)
        )
        return data, np.ascontiguousarray(corners, dtype=np.float32)

    def _upload_cells(self, document: MapDocument) -> None:
        tables = self._cell_data(document, None)
        if tables is None:
            for name in ("_cells_texture", "_cliff_texture"):
                texture = getattr(self, name)
                if texture:
                    glDeleteTextures(1, [texture])
                    setattr(self, name, 0)
            self._cells_shape = None
            return
        data, corners = tables
        if not self._cells_texture:
            self._cells_texture = int(glGenTextures(1))
        if not self._cliff_texture:
            self._cliff_texture = int(glGenTextures(1))
        data = np.ascontiguousarray(data)
        _send_texture(
            self._cells_texture, data, GL_RGBA16UI, GL_RGBA_INTEGER, GL_UNSIGNED_SHORT, False
        )
        _send_texture(self._cliff_texture, corners, GL_RGBA32F, GL_RGBA, GL_FLOAT, False)
        self._cells_shape = data.shape

    def _patch_cells(self, document: MapDocument, region: Region) -> None:
        if not self._cells_texture or self._cells_shape is None:
            self._upload_cells(document)
            return
        rows, columns = self._cells_shape[:2]
        x0, y0 = max(region.x0, 0), max(region.y0, 0)
        x1, y1 = min(region.x1, columns), min(region.y1, rows)
        if x0 >= x1 or y0 >= y1:
            return
        tables = self._cell_data(document, (x0, y0, x1, y1))
        if tables is None or not self._cliff_texture:
            self._upload_cells(document)
            return
        data, corners = tables
        _patch_texture(
            self._cells_texture,
            np.ascontiguousarray(data),
            x0,
            y0,
            GL_RGBA_INTEGER,
            GL_UNSIGNED_SHORT,
            False,
        )
        _patch_texture(self._cliff_texture, corners, x0 * 2, y0, GL_RGBA, GL_FLOAT, False)

    def _upload_feedback(self) -> None:
        pixels = self.source.tile_feedback()
        self._use_feedback = pixels is not None
        if pixels is None:
            return
        if not self._feedback_texture:
            self._feedback_texture = int(glGenTextures(1))
        _send_texture(self._feedback_texture, pixels, GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, False)

    def _upload_atlas(self, key: Hashable, atlas: TerrainAtlas) -> None:
        if not self._atlas_texture:
            self._atlas_texture = int(glGenTextures(1))
        pixels = np.ascontiguousarray(atlas.pixels, dtype=np.uint8)
        _send_texture(self._atlas_texture, pixels, GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, True)
        self._atlas_key = key
        self._atlas_side = atlas.side
        self._atlas_cell_pixels = atlas.cell_pixels

    # Objects.

    def _sync_models(self, document: MapDocument, grid: TerrainGrid) -> None:
        """Send loaded models to the GPU, ask for the ones the map's objects still lack, and
        work out where each model's copies stand when the objects, the ground or the filters
        changed."""
        while self._pending_models:
            models, textures = self._pending_models.pop(0)
            for key, pixels in textures.items():
                if pixels is not None and key not in self._model_textures:
                    texture = int(glGenTextures(1))
                    _send_texture(
                        texture, pixels, GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, True, repeat=True
                    )
                    self._model_textures[key] = texture
            for name, geometry in models.items():
                self._release_model(name)
                self._models[name] = self._upload_model(geometry) if geometry is not None else None
            self._reinstance = True
        visibility = self.source.visibility_key
        conditions = self.damage_thresholds.of_map(document.map, self.options.show_garrisoned)
        ghosts = list(self.tool.ghosts())
        ghost_state = tuple((obj.type_name, obj.position, obj.angle) for obj in ghosts)
        full = self._reinstance or visibility != self._visibility or conditions != self._conditions
        if not full and ghost_state == self._ghosts:
            return
        self._ghosts = ghost_state
        if full:
            self._reinstance = False
            self._visibility = visibility
            self._conditions = conditions
            groups: defaultdict[str, list[Object]] = defaultdict(list)
            objects_list = document.map.objects_list
            for obj in objects_list.object_list if objects_list is not None else []:
                if marker_kind(obj) is MarkerKind.OBJECT and self.is_shown(obj):
                    groups[self.model_key(obj)].append(obj)
            self._groups = groups
        ghost_groups: defaultdict[str, list[Object]] = defaultdict(list)
        for obj in ghosts:
            ghost_groups[self.model_key(obj)].append(obj)
        wanted = sorted(
            name
            for name in {*self._groups, *ghost_groups}
            if name not in self._models and name not in self._requested_models
        )
        if wanted and self.model_provider is not None:
            self._requested_models.update(wanted)
            self.model_provider(wanted)
        # Only the models the ghosts leave or come to need placing again when nothing else moved.
        names = list(self._models) if full else self._ghost_names | set(ghost_groups)
        self._ghost_names = set(ghost_groups)
        for name in names:
            model = self._models.get(name)
            if model is not None:
                shown = self._groups.get(name, []) + ghost_groups.get(name, [])
                self._place_instances(model, shown, grid)

    def _place_instances(self, model: _Model, objects: list[Object], grid: TerrainGrid) -> None:
        model.objects = objects
        model.count = len(objects)
        if not objects:
            model.matrices = np.zeros((0, 4, 4), dtype=np.float32)
            return
        # Where each object stands, which for a template with a rotation anchor is not its pivot.
        placed = [shown_position(obj, self.source.anchors) for obj in objects]
        xs = np.fromiter((position[0] for position in placed), dtype=np.float64, count=len(placed))
        ys = np.fromiter((position[1] for position in placed), dtype=np.float64, count=len(placed))
        heights = np.fromiter(
            (position[2] for position in placed), dtype=np.float64, count=len(placed)
        )
        angles = np.fromiter((obj.angle for obj in objects), dtype=np.float64, count=len(objects))
        scales = np.fromiter(
            (object_scale(obj) for obj in objects), dtype=np.float64, count=len(objects)
        )
        matrices = instance_matrices(xs, ys, ground_heights(grid, xs, ys) + heights, angles, scales)
        model.matrices = matrices
        # A GLSL mat4 attribute reads its four columns in turn.
        columns = np.ascontiguousarray(matrices.transpose(0, 2, 1), dtype=np.float32)
        glBindBuffer(GL_ARRAY_BUFFER, model.instances)
        glBufferData(GL_ARRAY_BUFFER, columns.nbytes, columns, GL_DYNAMIC_DRAW)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def _upload_model(self, geometry: ModelGeometry) -> _Model:
        instances = int(glGenBuffers(1))
        parts = []
        for part in geometry.parts:
            vao = int(glGenVertexArrays(1))
            glBindVertexArray(vao)
            buffers = []
            for location, array, size in (
                (0, part.positions, 3),
                (1, part.normals, 3),
                (2, part.uvs, 2),
            ):
                if array is None:
                    continue
                buffer = int(glGenBuffers(1))
                glBindBuffer(GL_ARRAY_BUFFER, buffer)
                glBufferData(GL_ARRAY_BUFFER, array.nbytes, array, GL_STATIC_DRAW)
                glVertexAttribPointer(location, size, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
                glEnableVertexAttribArray(location)
                buffers.append(buffer)
            ebo = int(glGenBuffers(1))
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, part.indices.nbytes, part.indices, GL_STATIC_DRAW)
            buffers.append(ebo)
            glBindBuffer(GL_ARRAY_BUFFER, instances)
            for column in range(4):
                location = _INSTANCE_LOCATION + column
                glVertexAttribPointer(
                    location, 4, GL_FLOAT, GL_FALSE, 64, ctypes.c_void_p(16 * column)
                )
                glEnableVertexAttribArray(location)
                glVertexAttribDivisor(location, 1)
            glBindVertexArray(0)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            parts.append(
                _Part(
                    vao,
                    buffers,
                    int(part.indices.size),
                    part.texture.lower() if part.texture is not None else None,
                    part.color,
                    part.translucent,
                    part.alpha_test,
                    part.two_sided,
                    part.additive,
                    part.unlit,
                )
            )
        return _Model(parts, instances, geometry)

    def _draw_models(self, matrix: np.ndarray) -> None:
        if not self._model_program or not any(self._models.values()):
            return
        uniforms = self._model_uniforms
        glUseProgram(self._model_program)
        glUniformMatrix4fv(uniforms["view_projection"], 1, GL_TRUE, matrix)
        self._send_lights(uniforms, LightTarget.OBJECTS)
        glActiveTexture(GL_TEXTURE0)
        glUniform1i(uniforms["texture_image"], 0)
        # Models are the one thing here with a back to them, and the game draws only their front:
        # a building seen from above is its inside, not a lid over it. A mesh marked two-sided
        # (a leaf card, a flame) has no back to cull.
        glEnable(GL_CULL_FACE)
        culling = True
        for translucent in (False, True):
            destination = 0
            if translucent:
                glEnable(GL_BLEND)
                glDepthMask(GL_FALSE)
            for model in self._models.values():
                if model is None or not model.count:
                    continue
                for part in model.parts:
                    if part.translucent is not translucent:
                        continue
                    if translucent:
                        # An additive mesh adds its light to the scene, keeping all of what is
                        # already drawn; every other one mixes into it by its own opacity.
                        factor = GL_ONE if part.additive else GL_ONE_MINUS_SRC_ALPHA
                        if factor != destination:
                            destination = factor
                            glBlendFunc(GL_SRC_ALPHA, factor)
                    if culling == part.two_sided:
                        culling = not part.two_sided
                        (glEnable if culling else glDisable)(GL_CULL_FACE)
                    texture = self._model_textures.get(part.texture, 0) if part.texture else 0
                    glBindTexture(GL_TEXTURE_2D, texture)
                    glUniform1i(uniforms["textured"], int(bool(texture)))
                    glUniform1i(uniforms["alpha_test"], int(part.alpha_test))
                    glUniform1i(uniforms["translucent"], int(translucent))
                    glUniform1i(uniforms["unlit"], int(part.unlit))
                    glUniform4f(uniforms["base_color"], *part.color)
                    glBindVertexArray(part.vao)
                    glDrawElementsInstanced(
                        GL_TRIANGLES, part.count, GL_UNSIGNED_INT, None, model.count
                    )
        glBindVertexArray(0)
        glBindTexture(GL_TEXTURE_2D, 0)
        # The water drawn after this, and the terrain of the next frame, have no back to cull.
        glDisable(GL_CULL_FACE)

    def _water_surface_drawn(self, area: object) -> bool:
        return self.options.show_water and id(area) in self._water_drawn

    def _draw_roads(self, painter: QPainter, scene: MapScene) -> None:
        """The roads themselves are the textured ground of `_draw_road_surfaces`, so over them the
        overlay draws only the outline of each selected segment's pieces."""
        selection = self.document.selection if self.document is not None else ()
        if not selection:
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_SELECTED_ROAD, 2))
        for piece in self.road_pieces(scene):
            segment = piece.segment
            if segment.start not in selection and segment.end not in selection:
                continue
            if not (self.is_shown(segment.start) and self.is_shown(segment.end)):
                continue
            path = self._screen_path(piece.corners, closed=True)
            if path is not None:
                painter.drawPolygon(QPolygonF(path))

    def _art(self) -> ArtTextures | None:
        provider = self.art_provider
        return provider() if provider is not None else None

    def _water_texture(self, art: ArtTextures | None, name: str | None) -> int:
        """A water texture on the GPU, sent the first time it is drawn; 0 without one."""
        if art is None or not name:
            return 0
        key = name.lower()
        if key not in self._water_textures:
            pixels = art.texture(name)
            texture = 0
            if pixels is not None:
                texture = int(glGenTextures(1))
                _send_texture(
                    texture, pixels, GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, True, repeat=True
                )
            self._water_textures[key] = texture
        return self._water_textures[key]

    def _sync_water(self, document: MapDocument, grid: TerrainGrid) -> None:
        """Make the lakes' and rivers' surfaces again when the water, the shown items, or (once a
        gesture is over) the terrain under them changed. Wave areas have no surface."""
        visibility = self.source.visibility_key
        depths = self._water_depths_stale and not self.gesture_active
        if not (self._rewater or depths or visibility != self._water_visibility):
            return
        self._release_water(textures=False)
        self._rewater = self._water_depths_stale = False
        self._water_visibility = visibility
        map = document.map
        art = self._art()
        lakes = map.standing_water_areas.areas if map.standing_water_areas is not None else []
        rivers = map.river_areas.areas if map.river_areas is not None else []
        for area in [*lakes, *rivers]:
            if not self.is_shown(area):
                continue
            if isinstance(area, RiverArea):
                mesh = river_mesh(area.lines, area.water_height, grid)
                look = river_look(area)
            else:
                mesh = lake_mesh(area.points, area.water_height, grid)
                material = art.material(area.fx_shader) if art is not None else None
                look = lake_look(area, material, map.environment_data)
            if mesh is not None:
                self._water.append(self._upload_water(mesh, look))
                self._water_drawn.add(id(area))

    def _upload_water(self, mesh: WaterMesh, look: WaterLook) -> _WaterDraw:
        vao = int(glGenVertexArrays(1))
        glBindVertexArray(vao)
        buffers = []
        for location, array, size in (
            (0, mesh.positions, 3),
            (1, mesh.uvs, 2),
            (2, mesh.depths, 1),
        ):
            buffer = int(glGenBuffers(1))
            glBindBuffer(GL_ARRAY_BUFFER, buffer)
            data = np.ascontiguousarray(array, dtype=np.float32)
            glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_STATIC_DRAW)
            glVertexAttribPointer(location, size, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
            glEnableVertexAttribArray(location)
            buffers.append(buffer)
        ebo = int(glGenBuffers(1))
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, mesh.indices.nbytes, mesh.indices, GL_STATIC_DRAW)
        buffers.append(ebo)
        glBindVertexArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        return _WaterDraw(vao, buffers, int(mesh.indices.size), look)

    def _draw_water_surfaces(
        self, document: MapDocument, grid: TerrainGrid, matrix: np.ndarray
    ) -> None:
        """The lakes' and rivers' surfaces at their heights, blended over the terrain and models
        without writing depth, in the map's order."""
        self._sync_water(document, grid)
        if not self._water_program or not self._water:
            return
        art = self._art()
        uniforms = self._water_uniforms
        glUseProgram(self._water_program)
        glUniformMatrix4fv(uniforms["mvp"], 1, GL_TRUE, matrix)
        glUniform1i(uniforms["surface"], 0)
        glUniform1i(uniforms["opacity"], 1)
        glUniform1i(uniforms["sparkles"], 2)
        glUniform1i(uniforms["noise"], 3)
        glEnable(GL_BLEND)
        glDepthMask(GL_FALSE)
        for draw in self._water:
            look = draw.look
            surface = self._water_texture(art, look.texture)
            opacity = self._water_texture(art, look.opacity_texture)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, surface)
            glActiveTexture(GL_TEXTURE1)
            glBindTexture(GL_TEXTURE_2D, opacity)
            sparkles = self._water_texture(art, look.sparkle_texture)
            noise = self._water_texture(art, look.noise_texture)
            glActiveTexture(GL_TEXTURE2)
            glBindTexture(GL_TEXTURE_2D, sparkles)
            glActiveTexture(GL_TEXTURE3)
            glBindTexture(GL_TEXTURE_2D, noise)
            glUniform1i(uniforms["textured"], int(bool(surface)))
            glUniform1i(uniforms["faded"], int(bool(opacity)))
            glUniform1i(uniforms["sparkling"], int(bool(sparkles and noise)))
            glUniform4f(uniforms["tint"], *look.color)
            glUniform1f(uniforms["uv_scale"], look.uv_scale)
            glUniform1i(uniforms["reflects"], int(look.reflection is not None))
            glUniform1f(uniforms["reflection"], look.reflection or 0.0)
            glUniform1i(uniforms["depth_fade"], int(look.depth_alpha is not None))
            glUniform2f(uniforms["depth_alpha"], *(look.depth_alpha or (0.0, 1.0)))
            glBlendFunc(GL_SRC_ALPHA, GL_ONE if look.additive else GL_ONE_MINUS_SRC_ALPHA)
            glBindVertexArray(draw.vao)
            glDrawElements(GL_TRIANGLES, draw.count, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)
        glActiveTexture(GL_TEXTURE0)
        glDepthMask(GL_TRUE)

    def _release_water(self, textures: bool) -> None:
        """Delete the water meshes (and with `textures`, the water textures) from the GPU; the
        context must be current."""
        if self._water:
            glDeleteVertexArrays(len(self._water), [draw.vao for draw in self._water])
            buffers = [buffer for draw in self._water for buffer in draw.buffers]
            glDeleteBuffers(len(buffers), buffers)
        self._water = []
        self._water_drawn = set()
        self._rewater = True
        if textures:
            live = [texture for texture in self._water_textures.values() if texture]
            if live:
                glDeleteTextures(len(live), live)
            self._water_textures.clear()

    # Roads.

    def _road_texture(self, art: ArtTextures | None, name: str | None) -> int:
        """A road texture on the GPU, sent the first time it is drawn; 0 without one."""
        if art is None or not name:
            return 0
        key = name.lower()
        if key not in self._road_textures:
            pixels = art.texture(name)
            texture = 0
            if pixels is not None:
                texture = int(glGenTextures(1))
                _send_texture(
                    texture, pixels, GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, True, repeat=True
                )
            self._road_textures[key] = texture
        return self._road_textures[key]

    def _sync_roads(self, grid: TerrainGrid) -> None:
        """Drape the roads over the terrain again when their pieces, the shown items or (once a
        gesture is over) the ground under them changed."""
        scene = self.scene
        if scene is None:
            return
        pieces = [
            piece
            for piece in self.road_pieces(scene)
            if self.is_shown(piece.segment.start) and self.is_shown(piece.segment.end)
        ]
        heights = self._road_heights_stale and not self.gesture_active
        key = (self.road_key(scene), self.source.visibility_key)
        if not heights and key == self._road_key:
            return
        self._release_roads(textures=False)
        self._road_heights_stale = False
        self._road_key = key
        for surface in road_surfaces(pieces, self._road_style, grid):
            self._roads.append(self._upload_road(surface))

    def _upload_road(self, surface: RoadSurface) -> _RoadDraw:
        vao = int(glGenVertexArrays(1))
        glBindVertexArray(vao)
        buffers = []
        for location, array, size in ((0, surface.positions, 3), (1, surface.uvs, 2)):
            buffer = int(glGenBuffers(1))
            glBindBuffer(GL_ARRAY_BUFFER, buffer)
            data = np.ascontiguousarray(array, dtype=np.float32)
            glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_STATIC_DRAW)
            glVertexAttribPointer(location, size, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
            glEnableVertexAttribArray(location)
            buffers.append(buffer)
        ebo = int(glGenBuffers(1))
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
        glBufferData(
            GL_ELEMENT_ARRAY_BUFFER, surface.indices.nbytes, surface.indices, GL_STATIC_DRAW
        )
        buffers.append(ebo)
        glBindVertexArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        fill = (BRIDGE_FILL if surface.bridge else ROAD_FILL).getRgbF()
        return _RoadDraw(vao, buffers, int(surface.indices.size), surface.texture, fill)

    def _draw_road_surfaces(self, grid: TerrainGrid, matrix: np.ndarray) -> None:
        """The roads on the ground, each texture in one draw, blended over the terrain so their
        clear edges fade into it and without writing depth, so the objects on them still draw."""
        self._sync_roads(grid)
        if not self._road_program or not self._roads:
            return
        art = self._art()
        uniforms = self._road_uniforms
        glUseProgram(self._road_program)
        glUniformMatrix4fv(uniforms["mvp"], 1, GL_TRUE, matrix)
        glUniform1i(uniforms["surface"], 0)
        self._send_lights(uniforms, LightTarget.TERRAIN)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthMask(GL_FALSE)
        glActiveTexture(GL_TEXTURE0)
        for draw in self._roads:
            texture = self._road_texture(art, draw.texture)
            glBindTexture(GL_TEXTURE_2D, texture)
            glUniform1i(uniforms["textured"], int(bool(texture)))
            glUniform4f(uniforms["tint"], *draw.color)
            glBindVertexArray(draw.vao)
            glDrawElements(GL_TRIANGLES, draw.count, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)
        glBindTexture(GL_TEXTURE_2D, 0)
        # The models drawn next take an opaque pass first, so leave the state they expect.
        glDisable(GL_BLEND)
        glDepthMask(GL_TRUE)

    def _release_roads(self, textures: bool) -> None:
        """Delete the road surfaces (and with `textures`, the road textures) from the GPU; the
        context must be current."""
        if self._roads:
            glDeleteVertexArrays(len(self._roads), [draw.vao for draw in self._roads])
            buffers = [buffer for draw in self._roads for buffer in draw.buffers]
            glDeleteBuffers(len(buffers), buffers)
        self._roads = []
        self._road_key = None
        if textures:
            live = [texture for texture in self._road_textures.values() if texture]
            if live:
                glDeleteTextures(len(live), live)
            self._road_textures.clear()

    def model_key(self, obj: Object) -> str:
        """The name `obj`'s model is loaded and drawn under: its type and its model conditions."""
        conditions = self._conditions or self.damage_thresholds
        return model_key(obj.type_name, model_conditions(obj.properties, conditions))

    def model_objects(self, name: str) -> list[Object]:
        """The objects drawn with the model loaded for `name` in the last frame."""
        model = self._models.get(name)
        return list(model.objects) if model is not None else []

    def _marker_footprint(self, marker: Marker) -> bool:
        """An object drawn as its model needs no footprint: the model shows where it stands."""
        if marker.kind is not MarkerKind.OBJECT:
            return True
        model = self._models.get(self.model_key(marker.source))
        return model is None or not model.parts

    def _marker_dot(self, marker: Marker) -> bool:
        """An object keeps its dot over its model: it marks where the object stands, and it is
        what a click picks it by first. Show Object Dots turns the object dots off for a clean
        picture; an object with no model to draw keeps its dot either way, as the only sign it is
        there."""
        return self.options.show_object_dots or self._marker_footprint(marker)

    def _dot_size(self, kind: MarkerKind) -> float:
        """A dot follows the camera's distance, taken at the target rather than under the cursor
        so the dots hold still while it moves: the default camera draws them full-sized, and
        backing away shrinks them as it shrinks the map. An object's dot is smaller than the rest:
        the model already shows the object, so the dot only marks its centre, and a map of
        thousands would be a spray of them."""
        camera = self.camera
        scale = camera.pixels_per_unit_at(camera.target)
        size = max(1.5, min(9.0, 12 * scale))
        return max(1.5, size * 0.55) if kind is MarkerKind.OBJECT else size

    def marker_at(
        self,
        screen: QPointF,
        world: tuple[float, float],
        pixels: float,
        accept: Callable[[Marker], bool],
    ) -> Marker | None:
        """The marker a click picks: the nearest dot to the click on screen, whatever stands in
        front of the object it belongs to, else the object whose model is under the click, else a
        marker with no dot by the ground under it, as in the top-down view. The dots are drawn over
        everything, so picking by them first is what the picture shows."""
        scene = self.scene
        if scene is None:
            return None
        markers = [
            marker
            for marker in scene.in_rect(*self.transform.visible_world())
            if self._marker_dot(marker) and accept(marker)
        ]
        best: Marker | None = None
        best_distance = pixels
        for marker, point in zip(markers, self._screen_points(markers), strict=True):
            if point is None:
                continue
            distance = math.hypot(point.x() - screen.x(), point.y() - screen.y())
            if distance <= best_distance:
                best, best_distance = marker, distance
        if best is None:
            best = self._model_marker_at(screen, accept)
        return best if best is not None else super().marker_at(screen, world, pixels, accept)

    def _model_marker_at(self, screen: QPointF, accept: Callable[[Marker], bool]) -> Marker | None:
        """The object whose model the ray through the click meets first, unless the terrain
        stands in front of it."""
        scene = self.scene
        if scene is None:
            return None
        origin, direction = self.camera.ray(screen.x(), screen.y())
        by_source = {id(marker.source): marker for marker in scene.markers}
        best: Marker | None = None
        best_distance = math.inf
        for model in self._models.values():
            if model is None or not model.count:
                continue
            # Leave out the copies a click may not pick before testing, so an unpickable model in
            # front does not hide a pickable one behind it.
            markers = [by_source.get(id(obj)) for obj in model.objects]
            keep = [
                index
                for index, marker in enumerate(markers)
                if marker is not None and accept(marker)
            ]
            if not keep:
                continue
            hit = ray_hit_instances(model.geometry, model.matrices[keep], origin, direction)
            if hit is not None and hit[1] < best_distance:
                best, best_distance = markers[keep[hit[0]]], hit[1]
        grid = self.transform.grid
        if best is None or grid is None:
            return best
        ground = ray_hit(grid, origin, direction)
        if ground is not None:
            reach = float(np.linalg.norm(np.asarray(ground) - origin))
            if reach + _GROUND_SLACK < best_distance:
                return None
        return best

    def _release_model(self, name: str) -> None:
        model = self._models.pop(name, None)
        if model is None:
            return
        glDeleteVertexArrays(len(model.parts), [part.vao for part in model.parts])
        buffers = [buffer for part in model.parts for buffer in part.buffers] + [model.instances]
        glDeleteBuffers(len(buffers), buffers)

    # Releasing.

    def _release_chunks(self) -> None:
        if self._chunks:
            glDeleteVertexArrays(len(self._chunks), [chunk.vao for chunk in self._chunks])
            buffers = [buffer for chunk in self._chunks for buffer in (chunk.vbo, chunk.ebo)]
            glDeleteBuffers(len(buffers), buffers)
        self._chunks = []
        self._boxes = []

    def _release(self) -> None:
        self._release_chunks()
        self._release_water(textures=False)
        self._release_roads(textures=False)
        for name in ("_colors_texture", "_cells_texture", "_feedback_texture", "_cliff_texture"):
            texture = getattr(self, name)
            if texture:
                glDeleteTextures(1, [texture])
                setattr(self, name, 0)
        self._colors_shape = None
        self._cells_shape = None
        self._rebuild = True
        self._recolor = True
        self._recell = True
        self._reinstance = True

    # Mouse and keys.

    def world_at(self, position: QPointF) -> tuple[float, float]:
        return self.transform.screen_to_world(position.x(), position.y())

    # Dragging the camera objects.

    def _camera_view(self) -> camera_edit.ViewState | None:
        """What the camera editor works on: this view's camera, how it projects, the objects the
        Cameras panel put in the world, and the map's named cameras."""
        scene = self.camera_scene
        if scene is None or self.camera_host is None:
            return None
        document = self.document
        named = document.map.named_cameras if document is not None else None
        transform = self.transform
        return camera_edit.ViewState(
            self.camera,
            lambda x, y, z: transform.project(x, y, z),
            scene,
            named.cameras if named is not None else (),
        )

    def camera_press(self, screen: tuple[float, float]) -> bool:
        """A left press over the camera objects, before the tool sees it: on a handle it starts a
        drag, on another object it chooses that one. False leaves the press to the tool."""
        state = self._camera_view()
        if state is None:
            return False
        result = self.camera_editor.press(state, screen)
        if result is None:
            return False
        if result == camera_edit.PICKED:
            self.camera_object_picked.emit(self.camera_editor.picked)
        self.update()
        return True

    def camera_drag(self, screen: tuple[float, float]) -> bool:
        """Carry a handle drag on."""
        state = self._camera_view()
        if state is None or not self.camera_editor.move(state, screen):
            return False
        self.update()
        return True

    def camera_release(self) -> bool:
        """End a handle drag, closing its command so the next drag is an undo entry of its own."""
        if not self.camera_editor.release():
            return False
        # Choose again what was dragged, so its handles are still there to drag on.
        self.camera_object_picked.emit(self.camera_editor.picked)
        self.update()
        return True

    def _camera_hover_at(self, screen: tuple[float, float]) -> None:
        """Light the handle the cursor is over, and show that it can be dragged."""
        state = self._camera_view()
        if state is None or not self.camera_editor.hover_at(state, screen):
            return
        if self.camera_editor.hover is not None:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif not (self._panning or self._orbiting or self._space_down):
            self.unsetCursor()
        self.update()

    def _gesture(self, event: QMouseEvent) -> Gesture:
        modifiers = event.modifiers()
        return Gesture(
            self.world_at(event.position()),
            event.position(),
            shift=bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
            alt=bool(modifiers & Qt.KeyboardModifier.AltModifier),
            right=event.button() == Qt.MouseButton.RightButton
            or bool(event.buttons() & Qt.MouseButton.RightButton),
        )

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802 - Qt override
        if event is None:
            return
        button = event.button()
        control = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        drag = button == Qt.MouseButton.MiddleButton or (
            button == Qt.MouseButton.LeftButton and self._space_down
        )
        orbit_right = button == Qt.MouseButton.RightButton and not self.tool.right_button
        if drag or orbit_right:
            self._orbiting = orbit_right or control
            self._panning = not self._orbiting
            self._last_mouse = event.position()
            self.setCursor(
                Qt.CursorShape.SizeAllCursor if self._orbiting else Qt.CursorShape.ClosedHandCursor
            )
            event.accept()
            return
        position = event.position()
        if button == Qt.MouseButton.LeftButton and self.camera_press((position.x(), position.y())):
            self._gesture_button = button
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        takes_button = button == Qt.MouseButton.LeftButton or (
            button == Qt.MouseButton.RightButton and self.tool.right_button
        )
        if takes_button and self.tool.press(self, self._gesture(event)):
            self.gesture_active = True
            self._gesture_button = button
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802 - Qt override
        if event is None:
            return
        position = event.position()
        if (self._panning or self._orbiting) and self._last_mouse is not None:
            delta = position - self._last_mouse
            if self._orbiting:
                self.camera.orbit(delta.x(), delta.y())
            else:
                self.camera.pan(delta.x(), delta.y())
            self._last_mouse = position
            self.transform.moved()
            self.update()
            event.accept()
            return
        self.cursor_world = self.world_at(position)
        if self.camera_editor.drag is not None:
            self.camera_drag((position.x(), position.y()))
            self._report_cursor()
            event.accept()
            return
        if not event.buttons():
            self._camera_hover_at((position.x(), position.y()))
        if event.buttons() & Qt.MouseButton.LeftButton or (
            self.gesture_active and event.buttons() & self._gesture_button
        ):
            self.tool.move(self, self._gesture(event))
        elif not event.buttons():
            self.tool.hover(self, self._gesture(event))
        self._report_cursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802 - Qt override
        if event is None:
            return
        if self._panning or self._orbiting:
            self._panning = self._orbiting = False
            self._last_mouse = None
            self.unsetCursor()
            event.accept()
            return
        if self.camera_release():
            self.gesture_finished.emit()
            event.accept()
            return
        if event.button() == self._gesture_button and self.gesture_active:
            self.gesture_active = False
            handled = self.tool.release(self, self._gesture(event))
            self.gesture_finished.emit()
            if handled:
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent | None) -> None:  # noqa: N802 - Qt override
        if event is None:
            return
        steps = event.angleDelta().y() / 120
        if self.options.reverse_scroll:
            steps = -steps
        if steps:
            position = event.position()
            anchor = self.transform.hit(position.x(), position.y())
            self.camera.zoom(_ZOOM_STEP**steps, anchor)
            self.transform.moved()
            self.update()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # noqa: N802 - Qt override
        if event is not None and self.tool.key(self, event.key()):
            event.accept()
            return
        if event is not None and event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent | None) -> None:  # noqa: N802 - Qt override
        if event is not None and event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = False
            if not (self._panning or self._orbiting):
                self.unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def leaveEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self.cursor_world = None
        self.cursor_moved.emit(None, None)
        self.tool.leave(self)

    def _report_cursor(self) -> None:
        grid = self.transform.grid
        if grid is None or self.cursor_world is None:
            self.cursor_moved.emit(None, None)
            return
        x, y = self.cursor_world
        cell = grid.nearest_cell(x, y)
        height = grid.elevation_at(x, y)
        self.cursor_moved.emit(cell, float(height) if height is not None else None)


def _send_texture(
    texture: int,
    pixels: np.ndarray,
    internal: int,
    external: int,
    kind: int,
    mipmaps: bool,
    repeat: bool = False,
) -> None:
    """Replace a texture's picture: bottom row first, filtered with mipmaps, or nearest texel for
    data; clamped at the edges unless it `repeat`s."""
    height, width = pixels.shape[:2]
    glBindTexture(GL_TEXTURE_2D, texture)
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
    glTexImage2D(GL_TEXTURE_2D, 0, internal, width, height, 0, external, kind, pixels)
    minify, magnify = (GL_LINEAR_MIPMAP_LINEAR, GL_LINEAR) if mipmaps else (GL_NEAREST, GL_NEAREST)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, minify)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, magnify)
    wrap = GL_REPEAT if repeat else GL_CLAMP_TO_EDGE
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, wrap)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, wrap)
    if mipmaps:
        glGenerateMipmap(GL_TEXTURE_2D)
    glBindTexture(GL_TEXTURE_2D, 0)


def _patch_texture(
    texture: int, block: np.ndarray, x: int, y: int, external: int, kind: int, mipmaps: bool
) -> None:
    glBindTexture(GL_TEXTURE_2D, texture)
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
    glTexSubImage2D(GL_TEXTURE_2D, 0, x, y, block.shape[1], block.shape[0], external, kind, block)
    if mipmaps:
        glGenerateMipmap(GL_TEXTURE_2D)
    glBindTexture(GL_TEXTURE_2D, 0)


def _lines(low: float, high: float, spacing: float) -> list[float]:
    first, last = math.ceil(low / spacing), math.floor(high / spacing)
    return [index * spacing for index in range(first, last + 1)]
