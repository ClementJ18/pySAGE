# sage_w3d

A lossless reader/writer for `.w3d`, the SAGE engine's model format: meshes (geometry, fixed-
pipeline and shader materials, textures, the collision AABB tree), hierarchies (skeletons),
animation (uncompressed and compressed/adaptive-delta), HLOD level-of-detail data, collision
boxes, and dazzles.

No public specification of this format exists. The chunk ids and field layouts here were derived
from the OpenSAGE.BlenderPlugin project (LGPL-3.0) used strictly as a format reference - chunk
ids, field layouts, semantics - never its code, which this package does not reuse; the
implementation and its architecture are this package's own.

## Binary format

A `.w3d` file is a flat sequence of chunks. Every chunk is an 8-byte header followed by its
payload:

```
uint32  chunk_type
uint32  size_field   # low 31 bits: payload size in bytes; bit 31 ("flagged"): conventionally
                     # set when the payload holds nested chunks
<size_field & 0x7FFFFFFF bytes of payload>
```

All integers are little-endian; strings are latin-1 in practice (old exporters leave garbage
bytes after a NUL terminator, so this package never assumes zero-padding and never decodes as
UTF-8, which would raise on that garbage).

## Architecture

- **Ordered children, not fixed fields.** Every container chunk (`Mesh`, `Hierarchy`, `HLOD`, ...)
  stores `chunks: list[...]` in file order rather than one named field per expected sub-chunk.
  Convenience read-only properties (`mesh.header`, `mesh.vertices`, `hierarchy.pivots`, ...) expose
  the sub-chunk(s) a caller usually wants directly. This is what makes duplicate or oddly-ordered
  sub-chunks in real files a non-issue - they still round-trip, in the order they were read.
- **Sizes are computed from serialized payloads, never from arithmetic.** The writer serializes a
  chunk's payload first, then emits `chunk_type`, `len(payload) | (0x80000000 if flagged else 0)`,
  payload.
- **`flagged` (bit 31) is data.** Every chunk model carries it and writes it back verbatim. Real
  exporters do not set it consistently for the same chunk type, so parsing always dispatches on
  `chunk_type`, never on this bit.
- **Fixed strings and NUL-terminated string chunks preserve raw bytes.** `FixedString` (a 16- or
  32-byte name field embedded in a larger struct) and `NulString` (a whole leaf chunk's payload -
  a texture or material name, mapper args, dazzle fields, mesh user text) both keep the exact raw
  bytes; `.value` decodes latin-1 up to the first NUL. Equality and round-trip compare `raw`, not
  `.value` - a real exporter's leftover buffer contents after the terminator still survive.
- **The leaf self-check degrade rule.** After parsing a leaf chunk's typed model from its payload,
  the parser immediately re-serializes it and compares the result back to the original payload.
  Anything that doesn't match exactly - a non-canonical field this package doesn't yet transcribe,
  or a payload too short/malformed to parse at all - is kept as an `UnknownChunk` (the exact
  original bytes) instead, with a `W3DDiagnostic` explaining why. A container is degraded the same
  way if a sub-chunk header inside it is truncated or overruns the payload. The result: the
  whole-file round trip (`write_w3d(parse_w3d(data)) == data`) holds unconditionally, and
  diagnostics say precisely where the typed model fell short.
- Parsing never raises past `parse_w3d`, except `W3DError` for input that isn't a chunk stream at
  all (1 to 7 bytes - too short to hold even one header - or a first chunk header whose size
  overruns the file). An empty file is instead a valid, empty chunk stream - a handful of real
  BFME2/RotWK `.w3d` files ship that way. Bytes after the last top-level chunk are kept on
  `W3DFile.trailing`.

## Model

```python
from sage_w3d import parse_w3d, write_w3d, parse_w3d_from_path, write_w3d_to_path, W3DFile

w3d = parse_w3d_from_path("model.w3d")
w3d.meshes            # list[Mesh]
w3d.hierarchy         # Hierarchy | None
w3d.hlod              # HLOD | None
w3d.animation         # Animation | None (uncompressed) - first of, see .animations for all
w3d.animations        # list[Animation]
w3d.compressed_animation  # CompressedAnimation | None - first of, see .compressed_animations
w3d.compressed_animations  # list[CompressedAnimation]
w3d.boxes             # list[CollisionBox]
w3d.dazzles           # list[Dazzle]
w3d.diagnostics       # list[W3DDiagnostic] - empty for a fully-modeled file

write_w3d_to_path(w3d, "model.rewritten.w3d")  # byte-identical to the input
```

A `Mesh` exposes `.header`, `.name`/`.container_name`, `.vertices`/`.normals` (and the `_2`
variants some skinned meshes carry alongside), `.triangles`, `.vertex_influences`,
`.material_passes`, `.vertex_materials`, `.textures`, `.shader_materials`, `.aabbtree`, and the
four `.prelit_*` baked-lighting wrappers. A `Hierarchy` exposes `.name`, `.pivots` (bones, each
with a parent index and rest-pose transform), and `.pivot_fixups`. An `HLOD` exposes `.model_name`/
`.hierarchy_name`, `.lod_arrays`, `.aggregate_array`, `.proxy_array` - each an `HLODSubObjectArray`
of bone-indexed sub-object references. `Animation`/`CompressedAnimation` expose `.name`,
`.channels`/`.time_coded_channels`/`.adaptive_delta_channels`, etc. See each module's docstring
(`mesh.py`, `hierarchy.py`, `hlod.py`, `animation.py`, `compressed_animation.py`, `objects.py`)
for the full field-level layout.

`sage_w3d.adaptive_delta` decodes (and can encode) the quantized per-frame deltas a compressed
adaptive-delta channel stores - not needed for the chunk's own round trip (the raw block bytes
already guarantee that), only to turn them into actual per-frame values.

## Command-line tool

```
sage-w3d info <w3d>          # one line per top-level chunk: name + key identity fields
sage-w3d tree <w3d>          # full recursive chunk tree: id, name, size, container/raw tags
sage-w3d json <w3d> [--out FILE] [--compact]
sage-w3d check <path>        # file or directory (recursive *.w3d): round-trip + diagnostics
sage-w3d view <w3d> [--art DIR ...] [--anim FILE]   # PyQt6/OpenGL viewer (needs [w3d-view])
```

## Rendering

`sage_w3d.render` turns a parsed `W3DFile` into a scene ready to draw, split into a
backend-agnostic assembly layer and a thin Qt/OpenGL viewport:

- `render/math3d.py` - stdlib 4x4 matrix math (quaternion-to-matrix, composition, point/direction
  transform). No numpy, no Qt.
- `render/scene.py` - `build_scene(model, resolver=None) -> Scene`. Resolves the model's skeleton
  (its own `Hierarchy`, or one looked up by name through an `AssetResolver`), places every visible
  mesh in world space, and returns a `Scene` of flat, upload-ready `RenderMesh`es. Stdlib-only,
  fully typed, no Qt/OpenGL/numpy - the whole point is that it is testable and usable without a
  GPU.
- `render/textures.py` - `decode_texture(data) -> (width, height, rgba_bytes)`. Lazily imports
  Pillow, so importing `sage_w3d.render` itself needs no extra dependency.
- `render/viewport.py` - `W3DViewport(QOpenGLWidget)`, the only module here that imports
  PyQt6/PyOpenGL/numpy. Uploads a scene's geometry once as vertex arrays and draws with
  `glDrawElements` (never `glBegin`); ported from finalBIGv2's W3D tab is its interaction design
  (orbit-drag camera, wheel zoom, camera and lighting presets), not its renderer.

Two vertex-space conventions this package's own corpus verifies:

1. **Skin meshes store vertices in bone-local space.** Applying the skeleton's rest-pose world
   matrices to each vertex via its 1-2 bone influences reproduces the mesh header's own
   `min_corner`/`max_corner` bounds - the invariant `tests/sage_w3d/test_full_render.py` checks
   across the whole real corpus.
2. **Rigid HLOD-attached meshes are bone-local too**, placed by their HLOD sub-object's bone
   world matrix, not by any transform baked into the mesh itself.

`build_scene` transforms **positions and normals together** through the same matrices (the
normal by the rotation part, renormalized) - unlike reference tool finalBIGv2, which transforms
skinned positions but leaves normals in bone-local space, so a model with rotated rest bones
(most real BFME skeletons) reads as inverted/caved-in under lighting. See `scene.py`'s module
docstring for the one-sentence diagnosis.

`AssetResolver` is a `Protocol` (`find_hierarchy(name)`, `find_texture(name)`), the extension
point for wiring in a real asset pipeline; `DirectoryResolver` is the stdlib implementation over
one or more folders (case-insensitive by stem, matching a `.tga` request against a shipped
`.dds` the way finalBIGv2's base-name texture matching does).
`examples/sage_w3d/view_model.py` shows a `pyBIG`-backed resolver chained with it.

Install the extra to use the viewer: `pip install "pysage-tools[w3d-view]"` (PyQt6, PyOpenGL,
numpy, Pillow).

### Animation playback

`render/pose.py` (stdlib-only, no numpy/Qt) turns a parsed `Animation`/`CompressedAnimation`
into playback: `PoseEvaluator(hierarchy, animation).evaluate(frame) -> Pose`, a `Pose` being one
frame's world matrix and visibility for every hierarchy pivot. It normalizes all four channel
kinds the corpus carries (uncompressed, time-coded, adaptive-delta, motion - the last of these
is the most common by far, over half of all channel instances measured across the BFME2/RotWK
corpus) into per-pivot tracks and samples them uniformly. Visibility comes from either kind of
on-disk channel: the bit channels, or the BFME float visibility channel (type 15 - on/off
switches and 0..1 fade ramps, thresholded at the 0.5 midpoint).

**Channel values are deltas composed onto the rest pose, not absolute local transforms** -
measured across the real corpus: 81 of 102 translation channels read as deltas against 21 that
could be read as absolute (decisively so on cases like a `B_PELVIS` channel whose constant value
would put the pelvis at ankle height if read as absolute); 118 of 127 idle-animation quaternion
channels compose on top of the rest rotation against 9 that looked like outright replacement.
The composition rule, taken from the released Renegade W3D engine source (`ww3d2/htree.cpp`):

```
world(pivot, f) = world(parent, f) . T(rest_t) . R(rest_q) . T(anim_t(f)) . R(anim_q(f))
```

`render/pose.py`'s module docstring has the full evidence and the one alternative composition
order (OpenSAGE's) worth knowing about if this one is ever visually wrong.

`render/scene.py`'s `Scene` carries the resolved `hierarchy: Hierarchy | None`, and every
`RenderMesh` carries `skin: MeshSkin | None` (bone-local rest positions/normals plus per-vertex
bone indices/weights - `None` when no skeleton resolved) and `rigid_bone: int | None` (a rigid
mesh's HLOD sub-object bone, for pose-time visibility; `None` for a skin mesh, since visibility
is a rigid-mesh-only effect in this package).

`render/viewport.py` re-skins a scene's meshes on the CPU against a `Pose` every frame:
`W3DViewport.set_pose(pose)` (numpy `_skinned_arrays` does the linear blend skinning;
`set_pose(None)` restores the baked rest pose). `PlaybackController(viewport)` drives a
`PoseEvaluator` on a timer - `play()`/`pause()`/`toggle()`, `set_frame(frame)` to scrub, and a
`frame_changed` signal a UI can follow. `sage-w3d view --anim FILE` plays a model's own animation
chunks (or `FILE`'s) with Space bound to toggle play/pause; `examples/sage_w3d/view_model.py`'s
sidebar adds a full animation picker with a scrub slider.
