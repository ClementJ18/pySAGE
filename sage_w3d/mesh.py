"""The W3D mesh chunk (`0x00000000`) and every sub-chunk it can carry: geometry arrays,
materials (fixed-pipeline vertex materials and shaders, or shader-material FX properties),
textures, material passes, the collision AABB tree, and the four prelit-data wrappers that
bundle their own copy of the material sub-tree for a baked lighting pass.

Every container here follows the same shape (CONVENTIONS.md / the package README): a `chunks`
list holding the sub-chunks in file order, `UnknownChunk` standing in for anything unmodeled or
that failed its self-check, and read-only properties for convenient access to the sub-chunks a
caller usually wants directly."""

import struct
from dataclasses import dataclass

from sage_w3d.binary import (
    ChunkEntry,
    FixedString,
    NulString,
    RgbaListChunk,
    StringChunk,
    UInt32ListChunk,
    Vec2ListChunk,
    Vec3ListChunk,
    all_of,
    first_of,
    parse_leaf,
    parse_record_list,
    parse_uint32_array,
    parse_vec2_array,
    parse_vec3_array,
    split_or_degrade,
    write_chunk,
    write_uint32_array,
    write_vec2_array,
    write_vec3_array,
)
from sage_w3d.chunks import (
    W3D_CHUNK_AABBTREE,
    W3D_CHUNK_AABBTREE_HEADER,
    W3D_CHUNK_AABBTREE_NODES,
    W3D_CHUNK_AABBTREE_POLYINDICES,
    W3D_CHUNK_BITANGENTS,
    W3D_CHUNK_DCG,
    W3D_CHUNK_DIG,
    W3D_CHUNK_MATERIAL_INFO,
    W3D_CHUNK_MATERIAL_PASS,
    W3D_CHUNK_MESH,
    W3D_CHUNK_MESH_HEADER,
    W3D_CHUNK_MESH_USER_TEXT,
    W3D_CHUNK_NORMALS_2,
    W3D_CHUNK_PER_FACE_TEXCOORD_IDS,
    W3D_CHUNK_PRELIT_LIGHTMAP_MULTI_PASS,
    W3D_CHUNK_PRELIT_LIGHTMAP_MULTI_TEXTURE,
    W3D_CHUNK_PRELIT_UNLIT,
    W3D_CHUNK_PRELIT_VERTEX,
    W3D_CHUNK_SCG,
    W3D_CHUNK_SHADER_IDS,
    W3D_CHUNK_SHADER_MATERIAL,
    W3D_CHUNK_SHADER_MATERIAL_HEADER,
    W3D_CHUNK_SHADER_MATERIAL_ID,
    W3D_CHUNK_SHADER_MATERIAL_PROPERTY,
    W3D_CHUNK_SHADER_MATERIALS,
    W3D_CHUNK_SHADERS,
    W3D_CHUNK_STAGE_TEXCOORDS,
    W3D_CHUNK_TANGENTS,
    W3D_CHUNK_TEXTURE,
    W3D_CHUNK_TEXTURE_IDS,
    W3D_CHUNK_TEXTURE_INFO,
    W3D_CHUNK_TEXTURE_NAME,
    W3D_CHUNK_TEXTURE_STAGE,
    W3D_CHUNK_TEXTURES,
    W3D_CHUNK_TRIANGLES,
    W3D_CHUNK_VERTEX_INFLUENCES,
    W3D_CHUNK_VERTEX_MAPPER_ARGS0,
    W3D_CHUNK_VERTEX_MAPPER_ARGS1,
    W3D_CHUNK_VERTEX_MATERIAL,
    W3D_CHUNK_VERTEX_MATERIAL_IDS,
    W3D_CHUNK_VERTEX_MATERIAL_INFO,
    W3D_CHUNK_VERTEX_MATERIAL_NAME,
    W3D_CHUNK_VERTEX_MATERIALS,
    W3D_CHUNK_VERTEX_NORMALS,
    W3D_CHUNK_VERTEX_SHADE_INDICES,
    W3D_CHUNK_VERTICES,
    W3D_CHUNK_VERTICES_2,
    Rgba,
    UnknownChunk,
    Version,
    W3DDiagnostic,
)

__all__ = [
    "AABBTree",
    "AABBTreeHeader",
    "AABBTreeNode",
    "AABBTreeNodes",
    "GEOMETRY_TYPE_CAMERA_ALIGNED",
    "GEOMETRY_TYPE_CAMERA_ORIENTED",
    "GEOMETRY_TYPE_CAST_SHADOW",
    "GEOMETRY_TYPE_HIDDEN",
    "GEOMETRY_TYPE_SKIN",
    "GEOMETRY_TYPE_TWO_SIDED",
    "MaterialInfo",
    "MaterialPass",
    "Mesh",
    "MeshHeader",
    "PerFaceTexCoordIds",
    "Prelit",
    "Shader",
    "ShaderMaterial",
    "ShaderMaterialHeader",
    "ShaderMaterialProperty",
    "ShaderMaterials",
    "Shaders",
    "Texture",
    "TextureInfo",
    "TextureStage",
    "Textures",
    "Triangle",
    "Triangles",
    "VertexInfluence",
    "VertexInfluences",
    "VertexMaterial",
    "VertexMaterialInfo",
    "VertexMaterials",
    "parse_mesh_chunk",
    "write_mesh_chunk",
]

_STRING_PROPERTY = 1
_FLOAT_PROPERTY = 2
_VEC2_PROPERTY = 3
_VEC3_PROPERTY = 4
_VEC4_PROPERTY = 5
_LONG_PROPERTY = 6
_BOOL_PROPERTY = 7

# Bits of MeshHeader.attrs a renderer needs to read (values from the OpenSAGE Blender plugin's
# mesh.py, used strictly as a format reference the same way the rest of this package is).
GEOMETRY_TYPE_HIDDEN = 0x1000
GEOMETRY_TYPE_TWO_SIDED = 0x2000
GEOMETRY_TYPE_CAMERA_ALIGNED = 0x10000
GEOMETRY_TYPE_CAMERA_ORIENTED = 0x60000
GEOMETRY_TYPE_CAST_SHADOW = 0x8000
GEOMETRY_TYPE_SKIN = 0x20000

_MESH_HEADER_FMT = "<2I16s16s9I3f3f3ff"
_MESH_HEADER_SIZE = struct.calcsize(_MESH_HEADER_FMT)


@dataclass
class MeshHeader:
    """The mesh's `0x1F` header: version, geometry-type/prelit-type attribute bits, the mesh and
    container names, and the stored (not derived - hazard 7) element counts and bounding
    volumes."""

    flagged: bool
    version: Version
    attrs: int
    mesh_name: FixedString
    container_name: FixedString
    face_count: int
    vert_count: int
    matl_count: int
    damage_stage_count: int
    sort_level: int
    prelit_version: int
    future_count: int
    vert_channel_flags: int
    face_channel_flags: int
    min_corner: tuple[float, float, float]
    max_corner: tuple[float, float, float]
    sph_center: tuple[float, float, float]
    sph_radius: float

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "MeshHeader":
        (
            version_raw,
            attrs,
            mesh_name,
            container_name,
            face_count,
            vert_count,
            matl_count,
            damage_stage_count,
            sort_level,
            prelit_version,
            future_count,
            vert_channel_flags,
            face_channel_flags,
            minx,
            miny,
            minz,
            maxx,
            maxy,
            maxz,
            cx,
            cy,
            cz,
            sph_radius,
        ) = struct.unpack(_MESH_HEADER_FMT, payload)
        return MeshHeader(
            flagged=flagged,
            version=Version.parse(version_raw),
            attrs=attrs,
            mesh_name=FixedString(raw=mesh_name),
            container_name=FixedString(raw=container_name),
            face_count=face_count,
            vert_count=vert_count,
            matl_count=matl_count,
            damage_stage_count=damage_stage_count,
            sort_level=sort_level,
            prelit_version=prelit_version,
            future_count=future_count,
            vert_channel_flags=vert_channel_flags,
            face_channel_flags=face_channel_flags,
            min_corner=(minx, miny, minz),
            max_corner=(maxx, maxy, maxz),
            sph_center=(cx, cy, cz),
            sph_radius=sph_radius,
        )

    def write(self) -> bytes:
        return struct.pack(
            _MESH_HEADER_FMT,
            self.version.encode(),
            self.attrs,
            self.mesh_name.raw,
            self.container_name.raw,
            self.face_count,
            self.vert_count,
            self.matl_count,
            self.damage_stage_count,
            self.sort_level,
            self.prelit_version,
            self.future_count,
            self.vert_channel_flags,
            self.face_channel_flags,
            *self.min_corner,
            *self.max_corner,
            *self.sph_center,
            self.sph_radius,
        )


@dataclass
class Triangle:
    """One record of a `TRIANGLES` array: the three vertex indices, a surface-type id, and the
    face normal/plane distance."""

    vert_ids: tuple[int, int, int]
    surface_type: int
    normal: tuple[float, float, float]
    distance: float

    @staticmethod
    def parse(data: bytes) -> "Triangle":
        v0, v1, v2, surface_type, nx, ny, nz, distance = struct.unpack("<4I3ff", data)
        return Triangle(
            vert_ids=(v0, v1, v2), surface_type=surface_type, normal=(nx, ny, nz), distance=distance
        )

    def write(self) -> bytes:
        return struct.pack("<4I3ff", *self.vert_ids, self.surface_type, *self.normal, self.distance)


@dataclass
class Triangles:
    flagged: bool
    triangles: list[Triangle]

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "Triangles":
        return Triangles(flagged=flagged, triangles=parse_record_list(payload, 32, Triangle.parse))

    def write(self) -> bytes:
        return b"".join(t.write() for t in self.triangles)


@dataclass
class VertexInfluence:
    """One record of a `VERTEX_INFLUENCES` array. Bone weights are kept as the raw 0-10000-ish
    on-disk integers (hundredths of a percent), not the divided float the source tool exposes -
    dividing then re-multiplying by 100 does not always recover the original integer bit-for-bit,
    which would break the round trip for no reason. `.bone_weight`/`.xtra_weight` give the
    divided float for convenience."""

    bone_idx: int
    xtra_idx: int
    bone_weight_raw: int
    xtra_weight_raw: int

    @property
    def bone_weight(self) -> float:
        return self.bone_weight_raw / 100

    @property
    def xtra_weight(self) -> float:
        return self.xtra_weight_raw / 100

    @staticmethod
    def parse(data: bytes) -> "VertexInfluence":
        bone_idx, xtra_idx, bone_weight_raw, xtra_weight_raw = struct.unpack("<4H", data)
        return VertexInfluence(bone_idx, xtra_idx, bone_weight_raw, xtra_weight_raw)

    def write(self) -> bytes:
        return struct.pack(
            "<4H", self.bone_idx, self.xtra_idx, self.bone_weight_raw, self.xtra_weight_raw
        )


@dataclass
class VertexInfluences:
    flagged: bool
    influences: list[VertexInfluence]

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "VertexInfluences":
        return VertexInfluences(
            flagged=flagged, influences=parse_record_list(payload, 8, VertexInfluence.parse)
        )

    def write(self) -> bytes:
        return b"".join(i.write() for i in self.influences)


@dataclass
class PerFaceTexCoordIds:
    """`STAGE_TEXCOORD`'s per-face companion: three signed indices per face into a stage's
    texcoord array."""

    flagged: bool
    faces: list[tuple[int, int, int]]

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "PerFaceTexCoordIds":
        return PerFaceTexCoordIds(
            flagged=flagged, faces=parse_record_list(payload, 12, lambda b: struct.unpack("<3i", b))
        )

    def write(self) -> bytes:
        return b"".join(struct.pack("<3i", *f) for f in self.faces)


@dataclass
class MaterialInfo:
    flagged: bool
    pass_count: int
    vert_matl_count: int
    shader_count: int
    texture_count: int

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "MaterialInfo":
        return MaterialInfo(flagged, *struct.unpack("<4I", payload))

    def write(self) -> bytes:
        return struct.pack(
            "<4I", self.pass_count, self.vert_matl_count, self.shader_count, self.texture_count
        )


@dataclass
class Shader:
    """One 16-byte fixed-pipeline shader record (`SHADERS` array element) - a bundle of small
    render-state enums the game reads by field position, not by name."""

    depth_compare: int
    depth_mask: int
    color_mask: int
    dest_blend: int
    fog_func: int
    pri_gradient: int
    sec_gradient: int
    src_blend: int
    texturing: int
    detail_color_func: int
    detail_alpha_func: int
    shader_preset: int
    alpha_test: int
    post_detail_color_func: int
    post_detail_alpha_func: int
    pad: int

    @staticmethod
    def parse(data: bytes) -> "Shader":
        return Shader(*struct.unpack("<16B", data))

    def write(self) -> bytes:
        return struct.pack(
            "<16B",
            self.depth_compare,
            self.depth_mask,
            self.color_mask,
            self.dest_blend,
            self.fog_func,
            self.pri_gradient,
            self.sec_gradient,
            self.src_blend,
            self.texturing,
            self.detail_color_func,
            self.detail_alpha_func,
            self.shader_preset,
            self.alpha_test,
            self.post_detail_color_func,
            self.post_detail_alpha_func,
            self.pad,
        )


@dataclass
class Shaders:
    flagged: bool
    shaders: list[Shader]

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "Shaders":
        return Shaders(flagged=flagged, shaders=parse_record_list(payload, 16, Shader.parse))

    def write(self) -> bytes:
        return b"".join(s.write() for s in self.shaders)


@dataclass
class VertexMaterialInfo:
    flagged: bool
    attributes: int
    ambient: Rgba
    diffuse: Rgba
    specular: Rgba
    emissive: Rgba
    shininess: float
    opacity: float
    translucency: float

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "VertexMaterialInfo":
        (
            attributes,
            ar,
            ag,
            ab,
            aa,
            dr,
            dg,
            db,
            da,
            sr,
            sg,
            sb,
            sa,
            er,
            eg,
            eb,
            ea,
            shininess,
            opacity,
            translucency,
        ) = struct.unpack("<I16Bfff", payload)
        return VertexMaterialInfo(
            flagged=flagged,
            attributes=attributes,
            ambient=Rgba(ar, ag, ab, aa),
            diffuse=Rgba(dr, dg, db, da),
            specular=Rgba(sr, sg, sb, sa),
            emissive=Rgba(er, eg, eb, ea),
            shininess=shininess,
            opacity=opacity,
            translucency=translucency,
        )

    def write(self) -> bytes:
        c = (
            *_rgba_tuple(self.ambient),
            *_rgba_tuple(self.diffuse),
            *_rgba_tuple(self.specular),
            *_rgba_tuple(self.emissive),
        )
        return struct.pack(
            "<I16Bfff", self.attributes, *c, self.shininess, self.opacity, self.translucency
        )


def _rgba_tuple(color: Rgba) -> tuple[int, int, int, int]:
    return (color.r, color.g, color.b, color.a)


VertexMaterialChunk = StringChunk | VertexMaterialInfo | UnknownChunk


@dataclass
class VertexMaterial:
    """A `0x2B` vertex-material: name, the fixed-pipeline color/shininess info, and up to two
    mapper-args strings, in whatever order the exporter wrote them."""

    flagged: bool
    chunks: list[VertexMaterialChunk]

    @property
    def name(self) -> str | None:
        c = first_of(self.chunks, StringChunk, W3D_CHUNK_VERTEX_MATERIAL_NAME)
        return c.text.value if c is not None else None

    @property
    def info(self) -> VertexMaterialInfo | None:
        return first_of(self.chunks, VertexMaterialInfo)

    @property
    def args0(self) -> str | None:
        c = first_of(self.chunks, StringChunk, W3D_CHUNK_VERTEX_MAPPER_ARGS0)
        return c.text.value if c is not None else None

    @property
    def args1(self) -> str | None:
        c = first_of(self.chunks, StringChunk, W3D_CHUNK_VERTEX_MAPPER_ARGS1)
        return c.text.value if c is not None else None


def _parse_vertex_material_child(
    entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]
):
    header_offset = base_offset + entry.header_offset
    if entry.chunk_type in (
        W3D_CHUNK_VERTEX_MATERIAL_NAME,
        W3D_CHUNK_VERTEX_MAPPER_ARGS0,
        W3D_CHUNK_VERTEX_MAPPER_ARGS1,
    ):
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: StringChunk(entry.chunk_type, entry.flagged, NulString(raw=p)),
            StringChunk.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_VERTEX_MATERIAL_INFO:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: VertexMaterialInfo.parse(entry.flagged, p),
            VertexMaterialInfo.write,
            diagnostics,
        )
    return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)


def _parse_vertex_material(entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]):
    header_offset = base_offset + entry.header_offset
    entries = split_or_degrade(
        entry.chunk_type, entry.flagged, entry.payload, header_offset, diagnostics
    )
    if entries is None:
        return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)
    payload_offset = header_offset + 8
    chunks = [_parse_vertex_material_child(e, payload_offset, diagnostics) for e in entries]
    return VertexMaterial(flagged=entry.flagged, chunks=chunks)


def _write_vertex_material_child(chunk) -> bytes:
    if isinstance(chunk, UnknownChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.data)
    if isinstance(chunk, StringChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.text.write())
    if isinstance(chunk, VertexMaterialInfo):
        return write_chunk(W3D_CHUNK_VERTEX_MATERIAL_INFO, chunk.flagged, chunk.write())
    raise TypeError(f"unwritable vertex material chunk: {chunk!r}")


def _write_vertex_material(vm: VertexMaterial) -> bytes:
    payload = b"".join(_write_vertex_material_child(c) for c in vm.chunks)
    return write_chunk(W3D_CHUNK_VERTEX_MATERIAL, vm.flagged, payload)


@dataclass
class VertexMaterials:
    flagged: bool
    chunks: list["VertexMaterial | UnknownChunk"]


def _parse_vertex_materials(entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]):
    header_offset = base_offset + entry.header_offset
    entries = split_or_degrade(
        entry.chunk_type, entry.flagged, entry.payload, header_offset, diagnostics
    )
    if entries is None:
        return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)
    payload_offset = header_offset + 8
    chunks = [
        _parse_vertex_material(e, payload_offset, diagnostics)
        if e.chunk_type == W3D_CHUNK_VERTEX_MATERIAL
        else UnknownChunk(e.chunk_type, e.flagged, e.payload)
        for e in entries
    ]
    return VertexMaterials(flagged=entry.flagged, chunks=chunks)


def _write_vertex_materials(vms: VertexMaterials) -> bytes:
    def _write_one(c):
        if isinstance(c, VertexMaterial):
            return _write_vertex_material(c)
        return write_chunk(c.chunk_type, c.flagged, c.data)

    payload = b"".join(_write_one(c) for c in vms.chunks)
    return write_chunk(W3D_CHUNK_VERTEX_MATERIALS, vms.flagged, payload)


@dataclass
class TextureInfo:
    flagged: bool
    attributes: int
    animation_type: int
    frame_count: int
    frame_rate: float

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "TextureInfo":
        attributes, animation_type, frame_count, frame_rate = struct.unpack("<2H If", payload)
        return TextureInfo(flagged, attributes, animation_type, frame_count, frame_rate)

    def write(self) -> bytes:
        return struct.pack(
            "<2HIf", self.attributes, self.animation_type, self.frame_count, self.frame_rate
        )


TextureChunk = StringChunk | TextureInfo | UnknownChunk


@dataclass
class Texture:
    flagged: bool
    chunks: list[TextureChunk]

    @property
    def name(self) -> str | None:
        c = first_of(self.chunks, StringChunk, W3D_CHUNK_TEXTURE_NAME)
        return c.text.value if c is not None else None

    @property
    def info(self) -> TextureInfo | None:
        return first_of(self.chunks, TextureInfo)


def _parse_texture_child(
    entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]
) -> TextureChunk:
    header_offset = base_offset + entry.header_offset
    if entry.chunk_type == W3D_CHUNK_TEXTURE_NAME:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: StringChunk(entry.chunk_type, entry.flagged, NulString(raw=p)),
            StringChunk.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_TEXTURE_INFO:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: TextureInfo.parse(entry.flagged, p),
            TextureInfo.write,
            diagnostics,
        )
    return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)


def _parse_texture(entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]):
    header_offset = base_offset + entry.header_offset
    entries = split_or_degrade(
        entry.chunk_type, entry.flagged, entry.payload, header_offset, diagnostics
    )
    if entries is None:
        return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)
    payload_offset = header_offset + 8
    chunks = [_parse_texture_child(e, payload_offset, diagnostics) for e in entries]
    return Texture(flagged=entry.flagged, chunks=chunks)


def _write_texture_child(chunk) -> bytes:
    if isinstance(chunk, UnknownChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.data)
    if isinstance(chunk, StringChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.text.write())
    if isinstance(chunk, TextureInfo):
        return write_chunk(W3D_CHUNK_TEXTURE_INFO, chunk.flagged, chunk.write())
    raise TypeError(f"unwritable texture chunk: {chunk!r}")


def _write_texture(texture: Texture) -> bytes:
    payload = b"".join(_write_texture_child(c) for c in texture.chunks)
    return write_chunk(W3D_CHUNK_TEXTURE, texture.flagged, payload)


@dataclass
class Textures:
    flagged: bool
    chunks: list["Texture | UnknownChunk"]


def _parse_textures(entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]):
    header_offset = base_offset + entry.header_offset
    entries = split_or_degrade(
        entry.chunk_type, entry.flagged, entry.payload, header_offset, diagnostics
    )
    if entries is None:
        return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)
    payload_offset = header_offset + 8
    chunks = [
        _parse_texture(e, payload_offset, diagnostics)
        if e.chunk_type == W3D_CHUNK_TEXTURE
        else UnknownChunk(e.chunk_type, e.flagged, e.payload)
        for e in entries
    ]
    return Textures(flagged=entry.flagged, chunks=chunks)


def _write_textures(textures: Textures) -> bytes:
    def _write_one(c):
        if isinstance(c, Texture):
            return _write_texture(c)
        return write_chunk(c.chunk_type, c.flagged, c.data)

    payload = b"".join(_write_one(c) for c in textures.chunks)
    return write_chunk(W3D_CHUNK_TEXTURES, textures.flagged, payload)


TextureStageChunk = UInt32ListChunk | Vec2ListChunk | PerFaceTexCoordIds | UnknownChunk


@dataclass
class TextureStage:
    flagged: bool
    chunks: list[TextureStageChunk]

    @property
    def texture_ids(self) -> list[int]:
        c = first_of(self.chunks, UInt32ListChunk, W3D_CHUNK_TEXTURE_IDS)
        return c.values if c is not None else []

    @property
    def tex_coords(self) -> list[tuple[float, float]]:
        c = first_of(self.chunks, Vec2ListChunk, W3D_CHUNK_STAGE_TEXCOORDS)
        return c.vectors if c is not None else []


def _parse_texture_stage_child(
    entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]
):
    header_offset = base_offset + entry.header_offset
    if entry.chunk_type == W3D_CHUNK_TEXTURE_IDS:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: UInt32ListChunk(entry.chunk_type, entry.flagged, parse_uint32_array(p)),
            UInt32ListChunk.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_STAGE_TEXCOORDS:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: Vec2ListChunk(entry.chunk_type, entry.flagged, parse_vec2_array(p)),
            Vec2ListChunk.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_PER_FACE_TEXCOORD_IDS:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: PerFaceTexCoordIds.parse(entry.flagged, p),
            PerFaceTexCoordIds.write,
            diagnostics,
        )
    return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)


def _parse_texture_stage(entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]):
    header_offset = base_offset + entry.header_offset
    entries = split_or_degrade(
        entry.chunk_type, entry.flagged, entry.payload, header_offset, diagnostics
    )
    if entries is None:
        return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)
    payload_offset = header_offset + 8
    chunks = [_parse_texture_stage_child(e, payload_offset, diagnostics) for e in entries]
    return TextureStage(flagged=entry.flagged, chunks=chunks)


def _write_texture_stage_child(chunk) -> bytes:
    if isinstance(chunk, UnknownChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.data)
    if isinstance(chunk, UInt32ListChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, write_uint32_array(chunk.values))
    if isinstance(chunk, Vec2ListChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, write_vec2_array(chunk.vectors))
    if isinstance(chunk, PerFaceTexCoordIds):
        return write_chunk(W3D_CHUNK_PER_FACE_TEXCOORD_IDS, chunk.flagged, chunk.write())
    raise TypeError(f"unwritable texture stage chunk: {chunk!r}")


def _write_texture_stage(stage: TextureStage) -> bytes:
    payload = b"".join(_write_texture_stage_child(c) for c in stage.chunks)
    return write_chunk(W3D_CHUNK_TEXTURE_STAGE, stage.flagged, payload)


MaterialPassChunk = UInt32ListChunk | RgbaListChunk | TextureStage | Vec2ListChunk | UnknownChunk


@dataclass
class MaterialPass:
    flagged: bool
    chunks: list[MaterialPassChunk]

    @property
    def vertex_material_ids(self) -> list[int]:
        c = first_of(self.chunks, UInt32ListChunk, W3D_CHUNK_VERTEX_MATERIAL_IDS)
        return c.values if c is not None else []

    @property
    def shader_ids(self) -> list[int]:
        c = first_of(self.chunks, UInt32ListChunk, W3D_CHUNK_SHADER_IDS)
        return c.values if c is not None else []

    @property
    def shader_material_ids(self) -> list[int]:
        c = first_of(self.chunks, UInt32ListChunk, W3D_CHUNK_SHADER_MATERIAL_ID)
        return c.values if c is not None else []

    @property
    def dcg(self) -> list[Rgba]:
        c = first_of(self.chunks, RgbaListChunk, W3D_CHUNK_DCG)
        return c.colors if c is not None else []

    @property
    def dig(self) -> list[Rgba]:
        c = first_of(self.chunks, RgbaListChunk, W3D_CHUNK_DIG)
        return c.colors if c is not None else []

    @property
    def scg(self) -> list[Rgba]:
        c = first_of(self.chunks, RgbaListChunk, W3D_CHUNK_SCG)
        return c.colors if c is not None else []

    @property
    def texture_stages(self) -> list[TextureStage]:
        return all_of(self.chunks, TextureStage)


_ID_ARRAY_CHUNK_TYPES = (
    W3D_CHUNK_VERTEX_MATERIAL_IDS,
    W3D_CHUNK_SHADER_IDS,
    W3D_CHUNK_SHADER_MATERIAL_ID,
)
_RGBA_ARRAY_CHUNK_TYPES = (W3D_CHUNK_DCG, W3D_CHUNK_DIG, W3D_CHUNK_SCG)


def _parse_material_pass_child(
    entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]
):
    header_offset = base_offset + entry.header_offset
    if entry.chunk_type in _ID_ARRAY_CHUNK_TYPES:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: UInt32ListChunk(entry.chunk_type, entry.flagged, parse_uint32_array(p)),
            UInt32ListChunk.write,
            diagnostics,
        )
    if entry.chunk_type in _RGBA_ARRAY_CHUNK_TYPES:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: RgbaListChunk(
                entry.chunk_type, entry.flagged, parse_record_list(p, 4, lambda b: Rgba(*b))
            ),
            RgbaListChunk.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_STAGE_TEXCOORDS:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: Vec2ListChunk(entry.chunk_type, entry.flagged, parse_vec2_array(p)),
            Vec2ListChunk.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_TEXTURE_STAGE:
        return _parse_texture_stage(entry, base_offset, diagnostics)
    return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)


def _parse_material_pass(entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]):
    header_offset = base_offset + entry.header_offset
    entries = split_or_degrade(
        entry.chunk_type, entry.flagged, entry.payload, header_offset, diagnostics
    )
    if entries is None:
        return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)
    payload_offset = header_offset + 8
    chunks = [_parse_material_pass_child(e, payload_offset, diagnostics) for e in entries]
    return MaterialPass(flagged=entry.flagged, chunks=chunks)


def _write_material_pass_child(chunk) -> bytes:
    if isinstance(chunk, UnknownChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.data)
    if isinstance(chunk, UInt32ListChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, write_uint32_array(chunk.values))
    if isinstance(chunk, RgbaListChunk):
        return write_chunk(
            chunk.chunk_type,
            chunk.flagged,
            b"".join(bytes((c.r, c.g, c.b, c.a)) for c in chunk.colors),
        )
    if isinstance(chunk, Vec2ListChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, write_vec2_array(chunk.vectors))
    if isinstance(chunk, TextureStage):
        return _write_texture_stage(chunk)
    raise TypeError(f"unwritable material pass chunk: {chunk!r}")


def _write_material_pass(mp: MaterialPass) -> bytes:
    payload = b"".join(_write_material_pass_child(c) for c in mp.chunks)
    return write_chunk(W3D_CHUNK_MATERIAL_PASS, mp.flagged, payload)


_SHADER_MATERIAL_HEADER_FMT = "<B32sI"


@dataclass
class ShaderMaterialHeader:
    flagged: bool
    version: int
    type_name: FixedString
    technique: int

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "ShaderMaterialHeader":
        version, type_name, technique = struct.unpack(_SHADER_MATERIAL_HEADER_FMT, payload)
        return ShaderMaterialHeader(flagged, version, FixedString(raw=type_name), technique)

    def write(self) -> bytes:
        return struct.pack(
            _SHADER_MATERIAL_HEADER_FMT, self.version, self.type_name.raw, self.technique
        )


@dataclass
class ShaderMaterialProperty:
    """One `FXShader` constant. `name_length`/`string_value_length` are the redundant length
    prefixes the format stores alongside each NUL-terminated string (the string's own NUL is what
    actually delimits it) - kept as read, and rewritten as read, rather than recomputed, in case
    a real exporter's count and its NUL-terminated bytes ever disagree."""

    flagged: bool
    prop_type: int
    name_length: int
    name: str
    string_value_length: int | None
    value: (
        str
        | float
        | int
        | tuple[float, float]
        | tuple[float, float, float]
        | tuple[float, float, float, float]
    )

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "ShaderMaterialProperty":
        prop_type, name_length = struct.unpack_from("<II", payload, 0)
        offset = 8
        name, offset = _read_nul_str(payload, offset)
        string_value_length: int | None = None
        value: (
            str
            | float
            | int
            | tuple[float, float]
            | tuple[float, float, float]
            | tuple[float, float, float, float]
        )
        if prop_type == _STRING_PROPERTY:
            (string_value_length,) = struct.unpack_from("<I", payload, offset)
            offset += 4
            value, offset = _read_nul_str(payload, offset)
        elif prop_type == _FLOAT_PROPERTY:
            (value,) = struct.unpack_from("<f", payload, offset)
            offset += 4
        elif prop_type == _VEC2_PROPERTY:
            value = struct.unpack_from("<2f", payload, offset)
            offset += 8
        elif prop_type == _VEC3_PROPERTY:
            value = struct.unpack_from("<3f", payload, offset)
            offset += 12
        elif prop_type == _VEC4_PROPERTY:
            value = struct.unpack_from("<4f", payload, offset)
            offset += 16
        elif prop_type == _LONG_PROPERTY:
            (value,) = struct.unpack_from("<i", payload, offset)
            offset += 4
        elif prop_type == _BOOL_PROPERTY:
            (value,) = struct.unpack_from("<B", payload, offset)
            offset += 1
        else:
            raise struct.error(f"unknown shader material property type {prop_type}")
        if offset != len(payload):
            raise struct.error(
                f"{len(payload) - offset} unconsumed byte(s) in shader material property"
            )
        return ShaderMaterialProperty(
            flagged, prop_type, name_length, name, string_value_length, value
        )

    def write(self) -> bytes:
        out = (
            struct.pack("<II", self.prop_type, self.name_length)
            + self.name.encode("latin-1")
            + b"\0"
        )
        if self.prop_type == _STRING_PROPERTY:
            assert isinstance(self.value, str)
            assert self.string_value_length is not None
            out += (
                struct.pack("<I", self.string_value_length) + self.value.encode("latin-1") + b"\0"
            )
        elif self.prop_type == _FLOAT_PROPERTY:
            out += struct.pack("<f", self.value)
        elif self.prop_type == _VEC2_PROPERTY:
            assert isinstance(self.value, tuple)
            out += struct.pack("<2f", *self.value)
        elif self.prop_type == _VEC3_PROPERTY:
            assert isinstance(self.value, tuple)
            out += struct.pack("<3f", *self.value)
        elif self.prop_type == _VEC4_PROPERTY:
            assert isinstance(self.value, tuple)
            out += struct.pack("<4f", *self.value)
        elif self.prop_type == _LONG_PROPERTY:
            out += struct.pack("<i", self.value)
        elif self.prop_type == _BOOL_PROPERTY:
            out += struct.pack("<B", self.value)
        else:
            raise ValueError(f"unknown shader material property type {self.prop_type}")
        return out


def _read_nul_str(data: bytes, offset: int) -> tuple[str, int]:
    nul = data.index(b"\0", offset)
    return data[offset:nul].decode("latin-1"), nul + 1


ShaderMaterialChunk = ShaderMaterialHeader | ShaderMaterialProperty | UnknownChunk


@dataclass
class ShaderMaterial:
    flagged: bool
    chunks: list[ShaderMaterialChunk]

    @property
    def header(self) -> ShaderMaterialHeader | None:
        return first_of(self.chunks, ShaderMaterialHeader)

    @property
    def properties(self) -> list[ShaderMaterialProperty]:
        return all_of(self.chunks, ShaderMaterialProperty)


def _parse_shader_material_child(
    entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]
):
    header_offset = base_offset + entry.header_offset
    if entry.chunk_type == W3D_CHUNK_SHADER_MATERIAL_HEADER:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: ShaderMaterialHeader.parse(entry.flagged, p),
            ShaderMaterialHeader.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_SHADER_MATERIAL_PROPERTY:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: ShaderMaterialProperty.parse(entry.flagged, p),
            ShaderMaterialProperty.write,
            diagnostics,
        )
    return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)


def _parse_shader_material(entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]):
    header_offset = base_offset + entry.header_offset
    entries = split_or_degrade(
        entry.chunk_type, entry.flagged, entry.payload, header_offset, diagnostics
    )
    if entries is None:
        return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)
    payload_offset = header_offset + 8
    chunks = [_parse_shader_material_child(e, payload_offset, diagnostics) for e in entries]
    return ShaderMaterial(flagged=entry.flagged, chunks=chunks)


def _write_shader_material_child(chunk) -> bytes:
    if isinstance(chunk, UnknownChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.data)
    if isinstance(chunk, ShaderMaterialHeader):
        return write_chunk(W3D_CHUNK_SHADER_MATERIAL_HEADER, chunk.flagged, chunk.write())
    if isinstance(chunk, ShaderMaterialProperty):
        return write_chunk(W3D_CHUNK_SHADER_MATERIAL_PROPERTY, chunk.flagged, chunk.write())
    raise TypeError(f"unwritable shader material chunk: {chunk!r}")


def _write_shader_material(sm: ShaderMaterial) -> bytes:
    payload = b"".join(_write_shader_material_child(c) for c in sm.chunks)
    return write_chunk(W3D_CHUNK_SHADER_MATERIAL, sm.flagged, payload)


@dataclass
class ShaderMaterials:
    flagged: bool
    chunks: list["ShaderMaterial | UnknownChunk"]


def _parse_shader_materials(entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]):
    header_offset = base_offset + entry.header_offset
    entries = split_or_degrade(
        entry.chunk_type, entry.flagged, entry.payload, header_offset, diagnostics
    )
    if entries is None:
        return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)
    payload_offset = header_offset + 8
    chunks = [
        _parse_shader_material(e, payload_offset, diagnostics)
        if e.chunk_type == W3D_CHUNK_SHADER_MATERIAL
        else UnknownChunk(e.chunk_type, e.flagged, e.payload)
        for e in entries
    ]
    return ShaderMaterials(flagged=entry.flagged, chunks=chunks)


def _write_shader_materials(sms: ShaderMaterials) -> bytes:
    def _write_one(c):
        if isinstance(c, ShaderMaterial):
            return _write_shader_material(c)
        return write_chunk(c.chunk_type, c.flagged, c.data)

    payload = b"".join(_write_one(c) for c in sms.chunks)
    return write_chunk(W3D_CHUNK_SHADER_MATERIALS, sms.flagged, payload)


@dataclass
class AABBTreeHeader:
    """`AABBTREE_HEADER`'s trailing 24 bytes are padding in every known file, but stored raw
    rather than assumed zero (hazard 5) - some tools leave stack garbage there."""

    flagged: bool
    node_count: int
    poly_count: int
    padding: bytes

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "AABBTreeHeader":
        node_count, poly_count = struct.unpack_from("<2I", payload, 0)
        return AABBTreeHeader(flagged, node_count, poly_count, payload[8:32])

    def write(self) -> bytes:
        return struct.pack("<2I", self.node_count, self.poly_count) + self.padding


@dataclass
class AABBTreeNode:
    min_corner: tuple[float, float, float]
    max_corner: tuple[float, float, float]
    front: int
    back: int

    @staticmethod
    def parse(data: bytes) -> "AABBTreeNode":
        minx, miny, minz, maxx, maxy, maxz, front, back = struct.unpack("<3f3f2i", data)
        return AABBTreeNode((minx, miny, minz), (maxx, maxy, maxz), front, back)

    def write(self) -> bytes:
        return struct.pack("<3f3f2i", *self.min_corner, *self.max_corner, self.front, self.back)


@dataclass
class AABBTreeNodes:
    flagged: bool
    nodes: list[AABBTreeNode]

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "AABBTreeNodes":
        return AABBTreeNodes(
            flagged=flagged, nodes=parse_record_list(payload, 32, AABBTreeNode.parse)
        )

    def write(self) -> bytes:
        return b"".join(n.write() for n in self.nodes)


AABBTreeChunk = AABBTreeHeader | UInt32ListChunk | AABBTreeNodes | UnknownChunk


@dataclass
class AABBTree:
    flagged: bool
    chunks: list[AABBTreeChunk]

    @property
    def header(self) -> AABBTreeHeader | None:
        return first_of(self.chunks, AABBTreeHeader)

    @property
    def poly_indices(self) -> list[int]:
        c = first_of(self.chunks, UInt32ListChunk, W3D_CHUNK_AABBTREE_POLYINDICES)
        return c.values if c is not None else []

    @property
    def nodes(self) -> list[AABBTreeNode]:
        c = first_of(self.chunks, AABBTreeNodes)
        return c.nodes if c is not None else []


def _parse_aabbtree_child(entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]):
    header_offset = base_offset + entry.header_offset
    if entry.chunk_type == W3D_CHUNK_AABBTREE_HEADER:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: AABBTreeHeader.parse(entry.flagged, p),
            AABBTreeHeader.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_AABBTREE_POLYINDICES:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: UInt32ListChunk(entry.chunk_type, entry.flagged, parse_uint32_array(p)),
            UInt32ListChunk.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_AABBTREE_NODES:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: AABBTreeNodes.parse(entry.flagged, p),
            AABBTreeNodes.write,
            diagnostics,
        )
    return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)


def _parse_aabbtree(entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]):
    header_offset = base_offset + entry.header_offset
    entries = split_or_degrade(
        entry.chunk_type, entry.flagged, entry.payload, header_offset, diagnostics
    )
    if entries is None:
        return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)
    payload_offset = header_offset + 8
    chunks = [_parse_aabbtree_child(e, payload_offset, diagnostics) for e in entries]
    return AABBTree(flagged=entry.flagged, chunks=chunks)


def _write_aabbtree_child(chunk) -> bytes:
    if isinstance(chunk, UnknownChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.data)
    if isinstance(chunk, AABBTreeHeader):
        return write_chunk(W3D_CHUNK_AABBTREE_HEADER, chunk.flagged, chunk.write())
    if isinstance(chunk, UInt32ListChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, write_uint32_array(chunk.values))
    if isinstance(chunk, AABBTreeNodes):
        return write_chunk(W3D_CHUNK_AABBTREE_NODES, chunk.flagged, chunk.write())
    raise TypeError(f"unwritable AABB tree chunk: {chunk!r}")


def _write_aabbtree(tree: AABBTree) -> bytes:
    payload = b"".join(_write_aabbtree_child(c) for c in tree.chunks)
    return write_chunk(W3D_CHUNK_AABBTREE, tree.flagged, payload)


_MATERIAL_SET_CHUNK_TYPES = (
    W3D_CHUNK_MATERIAL_INFO,
    W3D_CHUNK_SHADERS,
    W3D_CHUNK_VERTEX_MATERIALS,
    W3D_CHUNK_TEXTURES,
    W3D_CHUNK_MATERIAL_PASS,
)


def _parse_material_set_entry(
    entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]
):
    """Sub-chunk types a Mesh's own material data shares with each `Prelit` wrapper (a prelit
    chunk bundles its own copy of the same material sub-tree). Returns `None` for anything else,
    so the caller tries its own additional chunk types first."""
    if entry.chunk_type == W3D_CHUNK_MATERIAL_INFO:
        header_offset = base_offset + entry.header_offset
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: MaterialInfo.parse(entry.flagged, p),
            MaterialInfo.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_SHADERS:
        header_offset = base_offset + entry.header_offset
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: Shaders.parse(entry.flagged, p),
            Shaders.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_VERTEX_MATERIALS:
        return _parse_vertex_materials(entry, base_offset, diagnostics)
    if entry.chunk_type == W3D_CHUNK_TEXTURES:
        return _parse_textures(entry, base_offset, diagnostics)
    if entry.chunk_type == W3D_CHUNK_MATERIAL_PASS:
        return _parse_material_pass(entry, base_offset, diagnostics)
    return None


def _write_material_set_entry(chunk) -> bytes | None:
    if isinstance(chunk, MaterialInfo):
        return write_chunk(W3D_CHUNK_MATERIAL_INFO, chunk.flagged, chunk.write())
    if isinstance(chunk, Shaders):
        return write_chunk(W3D_CHUNK_SHADERS, chunk.flagged, chunk.write())
    if isinstance(chunk, VertexMaterials):
        return _write_vertex_materials(chunk)
    if isinstance(chunk, Textures):
        return _write_textures(chunk)
    if isinstance(chunk, MaterialPass):
        return _write_material_pass(chunk)
    return None


PrelitChunk = MaterialInfo | Shaders | VertexMaterials | Textures | MaterialPass | UnknownChunk

_PRELIT_TYPES = (
    W3D_CHUNK_PRELIT_UNLIT,
    W3D_CHUNK_PRELIT_VERTEX,
    W3D_CHUNK_PRELIT_LIGHTMAP_MULTI_PASS,
    W3D_CHUNK_PRELIT_LIGHTMAP_MULTI_TEXTURE,
)


@dataclass
class Prelit:
    """One of the four prelit-data wrappers (`PRELIT_UNLIT`/`_VERTEX`/`_LIGHTMAP_MULTI_PASS`/
    `_LIGHTMAP_MULTI_TEXTURE`) - `chunk_type` says which. Each bundles its own material_info/
    shaders/vertex_materials/textures/material_passes set for that lighting pass."""

    chunk_type: int
    flagged: bool
    chunks: list[PrelitChunk]

    @property
    def material_info(self) -> MaterialInfo | None:
        return first_of(self.chunks, MaterialInfo)

    @property
    def material_passes(self) -> list[MaterialPass]:
        return all_of(self.chunks, MaterialPass)


def _parse_prelit(entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]):
    header_offset = base_offset + entry.header_offset
    entries = split_or_degrade(
        entry.chunk_type, entry.flagged, entry.payload, header_offset, diagnostics
    )
    if entries is None:
        return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)
    payload_offset = header_offset + 8
    chunks = []
    for e in entries:
        parsed = _parse_material_set_entry(e, payload_offset, diagnostics)
        chunks.append(
            parsed if parsed is not None else UnknownChunk(e.chunk_type, e.flagged, e.payload)
        )
    return Prelit(chunk_type=entry.chunk_type, flagged=entry.flagged, chunks=chunks)


def _write_prelit(prelit: Prelit) -> bytes:
    def _write_one(c):
        written = _write_material_set_entry(c)
        if written is not None:
            return written
        return write_chunk(c.chunk_type, c.flagged, c.data)

    payload = b"".join(_write_one(c) for c in prelit.chunks)
    return write_chunk(prelit.chunk_type, prelit.flagged, payload)


MeshChunk = (
    MeshHeader
    | StringChunk
    | Vec3ListChunk
    | VertexInfluences
    | Triangles
    | UInt32ListChunk
    | MaterialInfo
    | Shaders
    | VertexMaterials
    | Textures
    | MaterialPass
    | ShaderMaterials
    | AABBTree
    | Prelit
    | UnknownChunk
)

_VEC3_ARRAY_CHUNK_TYPES = (
    W3D_CHUNK_VERTICES,
    W3D_CHUNK_VERTEX_NORMALS,
    W3D_CHUNK_VERTICES_2,
    W3D_CHUNK_NORMALS_2,
    W3D_CHUNK_TANGENTS,
    W3D_CHUNK_BITANGENTS,
)


@dataclass
class Mesh:
    """The `MESH` chunk: the ordered list of every sub-chunk it carried, in file order."""

    flagged: bool
    chunks: list[MeshChunk]

    @property
    def header(self) -> MeshHeader | None:
        return first_of(self.chunks, MeshHeader)

    @property
    def name(self) -> str:
        h = self.header
        return h.mesh_name.value if h is not None else ""

    @property
    def container_name(self) -> str:
        h = self.header
        return h.container_name.value if h is not None else ""

    @property
    def user_text(self) -> str | None:
        c = first_of(self.chunks, StringChunk, W3D_CHUNK_MESH_USER_TEXT)
        return c.text.value if c is not None else None

    @property
    def vertices(self) -> list[tuple[float, float, float]]:
        c = first_of(self.chunks, Vec3ListChunk, W3D_CHUNK_VERTICES)
        return c.vectors if c is not None else []

    @property
    def normals(self) -> list[tuple[float, float, float]]:
        c = first_of(self.chunks, Vec3ListChunk, W3D_CHUNK_VERTEX_NORMALS)
        return c.vectors if c is not None else []

    @property
    def vertices_2(self) -> list[tuple[float, float, float]]:
        c = first_of(self.chunks, Vec3ListChunk, W3D_CHUNK_VERTICES_2)
        return c.vectors if c is not None else []

    @property
    def normals_2(self) -> list[tuple[float, float, float]]:
        c = first_of(self.chunks, Vec3ListChunk, W3D_CHUNK_NORMALS_2)
        return c.vectors if c is not None else []

    @property
    def tangents(self) -> list[tuple[float, float, float]]:
        c = first_of(self.chunks, Vec3ListChunk, W3D_CHUNK_TANGENTS)
        return c.vectors if c is not None else []

    @property
    def bitangents(self) -> list[tuple[float, float, float]]:
        c = first_of(self.chunks, Vec3ListChunk, W3D_CHUNK_BITANGENTS)
        return c.vectors if c is not None else []

    @property
    def vertex_influences(self) -> list[VertexInfluence]:
        c = first_of(self.chunks, VertexInfluences)
        return c.influences if c is not None else []

    @property
    def triangles(self) -> list[Triangle]:
        c = first_of(self.chunks, Triangles)
        return c.triangles if c is not None else []

    @property
    def shade_indices(self) -> list[int]:
        c = first_of(self.chunks, UInt32ListChunk, W3D_CHUNK_VERTEX_SHADE_INDICES)
        return c.values if c is not None else []

    @property
    def material_info(self) -> MaterialInfo | None:
        return first_of(self.chunks, MaterialInfo)

    @property
    def shaders(self) -> list[Shader]:
        c = first_of(self.chunks, Shaders)
        return c.shaders if c is not None else []

    @property
    def vertex_materials(self) -> VertexMaterials | None:
        return first_of(self.chunks, VertexMaterials)

    @property
    def textures(self) -> Textures | None:
        return first_of(self.chunks, Textures)

    @property
    def shader_materials(self) -> ShaderMaterials | None:
        return first_of(self.chunks, ShaderMaterials)

    @property
    def material_passes(self) -> list[MaterialPass]:
        return all_of(self.chunks, MaterialPass)

    @property
    def aabbtree(self) -> AABBTree | None:
        return first_of(self.chunks, AABBTree)

    @property
    def prelit_unlit(self) -> Prelit | None:
        return first_of(self.chunks, Prelit, W3D_CHUNK_PRELIT_UNLIT)

    @property
    def prelit_vertex(self) -> Prelit | None:
        return first_of(self.chunks, Prelit, W3D_CHUNK_PRELIT_VERTEX)

    @property
    def prelit_lightmap_multi_pass(self) -> Prelit | None:
        return first_of(self.chunks, Prelit, W3D_CHUNK_PRELIT_LIGHTMAP_MULTI_PASS)

    @property
    def prelit_lightmap_multi_texture(self) -> Prelit | None:
        return first_of(self.chunks, Prelit, W3D_CHUNK_PRELIT_LIGHTMAP_MULTI_TEXTURE)


def _parse_mesh_child(
    entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]
) -> MeshChunk:
    header_offset = base_offset + entry.header_offset
    if entry.chunk_type == W3D_CHUNK_MESH_HEADER:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: MeshHeader.parse(entry.flagged, p),
            MeshHeader.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_MESH_USER_TEXT:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: StringChunk(entry.chunk_type, entry.flagged, NulString(raw=p)),
            StringChunk.write,
            diagnostics,
        )
    if entry.chunk_type in _VEC3_ARRAY_CHUNK_TYPES:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: Vec3ListChunk(entry.chunk_type, entry.flagged, parse_vec3_array(p)),
            Vec3ListChunk.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_VERTEX_INFLUENCES:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: VertexInfluences.parse(entry.flagged, p),
            VertexInfluences.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_TRIANGLES:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: Triangles.parse(entry.flagged, p),
            Triangles.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_VERTEX_SHADE_INDICES:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: UInt32ListChunk(entry.chunk_type, entry.flagged, parse_uint32_array(p)),
            UInt32ListChunk.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_SHADER_MATERIALS:
        return _parse_shader_materials(entry, base_offset, diagnostics)
    if entry.chunk_type == W3D_CHUNK_AABBTREE:
        return _parse_aabbtree(entry, base_offset, diagnostics)
    if entry.chunk_type in _PRELIT_TYPES:
        return _parse_prelit(entry, base_offset, diagnostics)

    shared = _parse_material_set_entry(entry, base_offset, diagnostics)
    if shared is not None:
        return shared
    return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)


def _write_mesh_child(chunk: MeshChunk) -> bytes:
    if isinstance(chunk, UnknownChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.data)
    if isinstance(chunk, MeshHeader):
        return write_chunk(W3D_CHUNK_MESH_HEADER, chunk.flagged, chunk.write())
    if isinstance(chunk, StringChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.text.write())
    if isinstance(chunk, Vec3ListChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, write_vec3_array(chunk.vectors))
    if isinstance(chunk, VertexInfluences):
        return write_chunk(W3D_CHUNK_VERTEX_INFLUENCES, chunk.flagged, chunk.write())
    if isinstance(chunk, Triangles):
        return write_chunk(W3D_CHUNK_TRIANGLES, chunk.flagged, chunk.write())
    if isinstance(chunk, UInt32ListChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, write_uint32_array(chunk.values))
    if isinstance(chunk, ShaderMaterials):
        return _write_shader_materials(chunk)
    if isinstance(chunk, AABBTree):
        return _write_aabbtree(chunk)
    if isinstance(chunk, Prelit):
        return _write_prelit(chunk)

    written = _write_material_set_entry(chunk)
    if written is not None:
        return written
    raise TypeError(f"unwritable mesh chunk: {chunk!r}")


def parse_mesh_chunk(
    payload: bytes, flagged: bool, header_offset: int, diagnostics: list[W3DDiagnostic]
):
    entries = split_or_degrade(W3D_CHUNK_MESH, flagged, payload, header_offset, diagnostics)
    if entries is None:
        return UnknownChunk(W3D_CHUNK_MESH, flagged, payload)
    payload_offset = header_offset + 8
    chunks = [_parse_mesh_child(e, payload_offset, diagnostics) for e in entries]
    return Mesh(flagged=flagged, chunks=chunks)


def write_mesh_chunk(mesh: Mesh) -> bytes:
    payload = b"".join(_write_mesh_child(c) for c in mesh.chunks)
    return write_chunk(W3D_CHUNK_MESH, mesh.flagged, payload)
