# sage_w3d

A lossless reader and writer for `.w3d`, the SAGE engine's model format: meshes (geometry,
materials, textures, the collision AABB tree), hierarchies (skeletons), animation (uncompressed and
compressed), HLOD level-of-detail data, collision boxes and dazzles, plus a scene builder and an
OpenGL viewer.

No public specification exists. Chunk ids and field layouts were taken from the
OpenSAGE.BlenderPlugin project (LGPL-3.0) as a format reference only; none of its code is reused.

## Binary format

A `.w3d` file is a flat sequence of chunks, each an 8-byte header and a payload:

```
uint32  chunk_type
uint32  size_field   # low 31 bits: payload size; bit 31 ("flagged"): usually set on containers
<size_field & 0x7FFFFFFF bytes of payload>
```

Integers are little-endian. Strings are latin-1; old exporters leave garbage after the NUL, so
strings are never assumed zero-padded or decoded as UTF-8.

## Design

- **Containers keep their children in file order** (`chunks: list[...]`), with convenience
  properties (`mesh.header`, `mesh.vertices`, `hierarchy.pivots`, ...) for the usual ones. Duplicate
  or oddly ordered sub-chunks still round-trip.
- **Sizes come from the serialized payload**, never from arithmetic.
- **The `flagged` bit is data**: kept and written back, never used to decide parsing, because
  exporters set it inconsistently.
- **Names keep their raw bytes.** `FixedString` and `NulString` compare on `raw`; `.value` decodes up
  to the first NUL.
- **A leaf that does not re-serialize exactly is kept as an `UnknownChunk`** (its original bytes),
  with a `W3DDiagnostic` saying why; so is a container with a broken sub-chunk header. So
  `write_w3d(parse_w3d(data)) == data` always holds.
- Parsing raises only `W3DError`, for input that is not a chunk stream at all. An empty file is a
  valid empty stream (some shipped files are), and trailing bytes are kept on `W3DFile.trailing`.

## Model

```python
from sage_w3d import parse_w3d_from_path, write_w3d_to_path

w3d = parse_w3d_from_path("model.w3d")
w3d.meshes                 # list[Mesh]
w3d.hierarchy              # Hierarchy | None
w3d.hlod                   # HLOD | None
w3d.animations             # list[Animation]  (.animation is the first)
w3d.compressed_animations  # list[CompressedAnimation]  (.compressed_animation is the first)
w3d.boxes                  # list[CollisionBox]
w3d.dazzles                # list[Dazzle]
w3d.diagnostics            # list[W3DDiagnostic], empty for a fully modelled file

write_w3d_to_path(w3d, "model.rewritten.w3d")  # byte-identical to the input
```

Field-level layouts are in each module's docstring (`mesh.py`, `hierarchy.py`, `hlod.py`,
`animation.py`, `compressed_animation.py`, `objects.py`). `sage_w3d.adaptive_delta` decodes the
quantized deltas of compressed channels into per-frame values.

## Command-line tool

```
sage-w3d info <w3d>          # one line per top-level chunk
sage-w3d tree <w3d>          # the full chunk tree
sage-w3d json <w3d> [--out FILE] [--compact]
sage-w3d check <path>        # file or directory: round trip + diagnostics
sage-w3d view <w3d> [--art DIR ...] [--anim FILE]   # the viewer (needs [w3d-view])
```

## Rendering

`sage_w3d.render` builds a drawable scene in plain Python and draws it with a thin Qt/OpenGL layer:

- `math3d.py`: stdlib 4x4 matrix maths.
- `scene.py`: `build_scene(model, resolver=None) -> Scene` resolves the skeleton (the model's own, or
  one found through an `AssetResolver`) and places every visible mesh in world space. Stdlib only,
  so it is testable without a GPU.
- `textures.py`: `decode_texture(data)`, importing Pillow lazily.
- `viewport.py`: `W3DViewport(QOpenGLWidget)`, the only module importing PyQt6, PyOpenGL and numpy.

Skin meshes and rigid HLOD-attached meshes store vertices in bone-local space (checked across the
corpus by `tests/sage_w3d/test_full_render.py`). `build_scene` transforms positions and normals
together, so models with rotated rest bones light correctly.

`AssetResolver` is a protocol (`find_hierarchy`, `find_texture`); `DirectoryResolver` implements it
over folders, matching a `.tga` request to a `.dds` by stem. `examples/sage_w3d/view_model.py`
chains it with a `.big` archive resolver. The viewer needs `pip install "pysage-tools[w3d-view]"`.

### Animation playback

`render/pose.py` (stdlib only): `PoseEvaluator(hierarchy, animation).evaluate(frame)` returns a
`Pose`, each pivot's world matrix and visibility, from all four channel kinds (uncompressed,
time-coded, adaptive-delta, motion) and both visibility forms (bit channels and BFME's float
channel, thresholded at 0.5).

Channel values are deltas on the rest pose, not absolute transforms (measured across the corpus),
composed as in the Renegade W3D source (`ww3d2/htree.cpp`):

```
world(pivot, f) = world(parent, f) . T(rest_t) . R(rest_q) . T(anim_t(f)) . R(anim_q(f))
```

`W3DViewport.set_pose(pose)` skins meshes on the CPU each frame (`None` restores the rest pose), and
`PlaybackController(viewport)` drives playback (`play`, `pause`, `set_frame`, a `frame_changed`
signal). `sage-w3d view --anim FILE` plays with Space to toggle.
