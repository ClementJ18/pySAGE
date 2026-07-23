"""Command-line entry point: `python -m sage_w3d <command>` (or `sage-w3d`).

Reads and inspects `.w3d` model files - no game data beyond the file itself is required.

- `info <w3d>` - one line per top-level chunk: its name and key identity fields (a mesh's
  container/name and vertex/face counts, a hierarchy's name and pivot count, an animation's
  name/frame count/rate, an HLOD's model/hierarchy name and LOD count), plus a diagnostic count.
- `tree <w3d>` - the full recursive chunk tree, indented, one line per chunk: id, name, payload
  size, and whether it is a container and/or kept as raw bytes; an id this package has never
  seen is labeled `unknown`.
- `json <w3d> [--out FILE] [--compact]` - the full parsed structure as JSON.
- `check <path>` - a `.w3d` file, or a directory (recursively, `*.w3d`/`*.W3D`): parse, write,
  and confirm the result is byte-identical to the input; reports diagnostics. Exits 1 if any
  file mismatches or fails to parse (diagnostics alone do not fail).
- `view <w3d> [--art DIR ...] [--anim FILE]` - open a PyQt6/OpenGL viewer for the model (needs the
  `w3d-view` extra). Plays the model's own animation chunks, or `--anim`'s, if either resolves
  against the model's hierarchy - Space toggles play/pause; no other chrome (the full transport
  UI belongs to `examples/sage_w3d/view_model.py`).
"""

import argparse
import base64
import json as json_module
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path

from sage_utils.cli import existing_dir, existing_file, existing_path, utf8_stdout
from sage_w3d.animation import Animation, AnimationBitChannel, AnimationChannel, AnimationHeader
from sage_w3d.binary import FixedString, NulString, write_chunk
from sage_w3d.chunks import (
    W3D_CHUNK_AABBTREE,
    W3D_CHUNK_AABBTREE_HEADER,
    W3D_CHUNK_AABBTREE_NODES,
    W3D_CHUNK_ANIMATION,
    W3D_CHUNK_ANIMATION_BIT_CHANNEL,
    W3D_CHUNK_ANIMATION_CHANNEL,
    W3D_CHUNK_ANIMATION_HEADER,
    W3D_CHUNK_BOX,
    W3D_CHUNK_COMPRESSED_ANIMATION,
    W3D_CHUNK_COMPRESSED_ANIMATION_CHANNEL,
    W3D_CHUNK_COMPRESSED_ANIMATION_HEADER,
    W3D_CHUNK_COMPRESSED_ANIMATION_MOTION_CHANNEL,
    W3D_CHUNK_COMPRESSED_BIT_CHANNEL,
    W3D_CHUNK_DAZZLE,
    W3D_CHUNK_HIERARCHY,
    W3D_CHUNK_HIERARCHY_HEADER,
    W3D_CHUNK_HLOD,
    W3D_CHUNK_HLOD_HEADER,
    W3D_CHUNK_HLOD_SUB_OBJECT,
    W3D_CHUNK_HLOD_SUB_OBJECT_ARRAY_HEADER,
    W3D_CHUNK_MATERIAL_INFO,
    W3D_CHUNK_MATERIAL_PASS,
    W3D_CHUNK_MESH,
    W3D_CHUNK_MESH_HEADER,
    W3D_CHUNK_PIVOTS,
    W3D_CHUNK_SHADER_MATERIAL,
    W3D_CHUNK_SHADER_MATERIAL_HEADER,
    W3D_CHUNK_SHADER_MATERIAL_PROPERTY,
    W3D_CHUNK_SHADER_MATERIALS,
    W3D_CHUNK_SHADERS,
    W3D_CHUNK_TEXTURE,
    W3D_CHUNK_TEXTURE_INFO,
    W3D_CHUNK_TEXTURE_STAGE,
    W3D_CHUNK_TEXTURES,
    W3D_CHUNK_TRIANGLES,
    W3D_CHUNK_VERTEX_INFLUENCES,
    W3D_CHUNK_VERTEX_MATERIAL,
    W3D_CHUNK_VERTEX_MATERIAL_INFO,
    W3D_CHUNK_VERTEX_MATERIALS,
    UnknownChunk,
    W3DError,
    chunk_name,
)
from sage_w3d.compressed_animation import (
    AdaptiveDeltaAnimationChannel,
    CompressedAnimation,
    CompressedAnimationHeader,
    MotionChannel,
    TimeCodedAnimationChannel,
    TimeCodedBitChannel,
)
from sage_w3d.hierarchy import Hierarchy, HierarchyHeader, Pivots
from sage_w3d.hlod import HLOD, HLODArrayHeader, HLODHeader, HLODSubObject
from sage_w3d.mesh import (
    AABBTree,
    AABBTreeHeader,
    AABBTreeNodes,
    MaterialInfo,
    MaterialPass,
    Mesh,
    MeshHeader,
    ShaderMaterial,
    ShaderMaterialHeader,
    ShaderMaterialProperty,
    ShaderMaterials,
    Shaders,
    Texture,
    TextureInfo,
    Textures,
    TextureStage,
    Triangles,
    VertexInfluences,
    VertexMaterial,
    VertexMaterialInfo,
    VertexMaterials,
)
from sage_w3d.objects import CollisionBox, Dazzle
from sage_w3d.render.pose import AnimationSource, PoseEvaluator
from sage_w3d.render.scene import DirectoryResolver, build_scene
from sage_w3d.w3d import W3DFile, parse_w3d_from_path, write_w3d

# One fixed chunk id per named (non chunk_type-tagged) dataclass - the tagged generic wrappers
# (StringChunk, Vec3ListChunk, ..., Prelit, HLODSubObjectArray) carry their own `chunk_type`
# instead and are not listed here; see `_chunk_type_of`.
_TYPE_TO_CHUNK_ID: dict[type, int] = {
    Mesh: W3D_CHUNK_MESH,
    MeshHeader: W3D_CHUNK_MESH_HEADER,
    Triangles: W3D_CHUNK_TRIANGLES,
    VertexInfluences: W3D_CHUNK_VERTEX_INFLUENCES,
    MaterialInfo: W3D_CHUNK_MATERIAL_INFO,
    Shaders: W3D_CHUNK_SHADERS,
    VertexMaterials: W3D_CHUNK_VERTEX_MATERIALS,
    VertexMaterial: W3D_CHUNK_VERTEX_MATERIAL,
    VertexMaterialInfo: W3D_CHUNK_VERTEX_MATERIAL_INFO,
    Textures: W3D_CHUNK_TEXTURES,
    Texture: W3D_CHUNK_TEXTURE,
    TextureInfo: W3D_CHUNK_TEXTURE_INFO,
    MaterialPass: W3D_CHUNK_MATERIAL_PASS,
    TextureStage: W3D_CHUNK_TEXTURE_STAGE,
    ShaderMaterials: W3D_CHUNK_SHADER_MATERIALS,
    ShaderMaterial: W3D_CHUNK_SHADER_MATERIAL,
    ShaderMaterialHeader: W3D_CHUNK_SHADER_MATERIAL_HEADER,
    ShaderMaterialProperty: W3D_CHUNK_SHADER_MATERIAL_PROPERTY,
    AABBTree: W3D_CHUNK_AABBTREE,
    AABBTreeHeader: W3D_CHUNK_AABBTREE_HEADER,
    AABBTreeNodes: W3D_CHUNK_AABBTREE_NODES,
    Hierarchy: W3D_CHUNK_HIERARCHY,
    HierarchyHeader: W3D_CHUNK_HIERARCHY_HEADER,
    Pivots: W3D_CHUNK_PIVOTS,
    HLOD: W3D_CHUNK_HLOD,
    HLODHeader: W3D_CHUNK_HLOD_HEADER,
    HLODArrayHeader: W3D_CHUNK_HLOD_SUB_OBJECT_ARRAY_HEADER,
    HLODSubObject: W3D_CHUNK_HLOD_SUB_OBJECT,
    CollisionBox: W3D_CHUNK_BOX,
    Dazzle: W3D_CHUNK_DAZZLE,
    Animation: W3D_CHUNK_ANIMATION,
    AnimationHeader: W3D_CHUNK_ANIMATION_HEADER,
    AnimationChannel: W3D_CHUNK_ANIMATION_CHANNEL,
    AnimationBitChannel: W3D_CHUNK_ANIMATION_BIT_CHANNEL,
    CompressedAnimation: W3D_CHUNK_COMPRESSED_ANIMATION,
    CompressedAnimationHeader: W3D_CHUNK_COMPRESSED_ANIMATION_HEADER,
    TimeCodedAnimationChannel: W3D_CHUNK_COMPRESSED_ANIMATION_CHANNEL,
    AdaptiveDeltaAnimationChannel: W3D_CHUNK_COMPRESSED_ANIMATION_CHANNEL,
    TimeCodedBitChannel: W3D_CHUNK_COMPRESSED_BIT_CHANNEL,
    MotionChannel: W3D_CHUNK_COMPRESSED_ANIMATION_MOTION_CHANNEL,
}


def _chunk_type_of(node: object) -> int:
    explicit = getattr(node, "chunk_type", None)
    if explicit is not None:
        return explicit
    return _TYPE_TO_CHUNK_ID[type(node)]


def _full_bytes(node: object) -> bytes:
    """The complete bytes (header + payload) of any chunk node, typed or `UnknownChunk` -
    computed generically from the uniform `.chunks` (container) / `.write()` (leaf) protocol
    every chunk dataclass in this package follows."""
    if isinstance(node, UnknownChunk):
        return write_chunk(node.chunk_type, node.flagged, node.data)
    chunks = getattr(node, "chunks", None)
    flagged = node.flagged  # type: ignore[attr-defined]
    if chunks is not None:
        payload = b"".join(_full_bytes(c) for c in chunks)
    else:
        payload = node.write()  # type: ignore[attr-defined]
    return write_chunk(_chunk_type_of(node), flagged, payload)


def _print_tree(node: object, indent: int, out: list[str]) -> None:
    if isinstance(node, UnknownChunk):
        size = len(node.data)
        tags = " [raw]"
        chunk_type = node.chunk_type
    else:
        chunk_type = _chunk_type_of(node)
        size = len(_full_bytes(node)) - 8
        tags = ""
    chunks = getattr(node, "chunks", None)
    if chunks is not None:
        tags = " [container]" + tags
    out.append(f"{'  ' * indent}0x{chunk_type:08X} {chunk_name(chunk_type)} size={size}{tags}")
    if chunks is not None:
        for child in chunks:
            _print_tree(child, indent + 1, out)


def _run_tree(args: argparse.Namespace) -> int:
    w3d = parse_w3d_from_path(args.w3d)
    lines: list[str] = []
    for chunk in w3d.chunks:
        _print_tree(chunk, 0, lines)
    print("\n".join(lines))
    if w3d.trailing:
        print(f"# {len(w3d.trailing)} trailing byte(s) after the last top-level chunk")
    return 0


def _mesh_summary(mesh: Mesh) -> str:
    verts, faces = len(mesh.vertices), len(mesh.triangles)
    return f"MESH {mesh.container_name}.{mesh.name}  verts={verts} faces={faces}"


def _hierarchy_summary(h: Hierarchy) -> str:
    return f"HIERARCHY {h.name}  pivots={len(h.pivots)}"


def _animation_summary(a: Animation) -> str:
    header = a.header
    frames = header.num_frames if header else 0
    rate = header.frame_rate if header else 0
    return f"ANIMATION {a.name}  frames={frames} rate={rate}  channels={len(a.channels)}"


def _compressed_animation_summary(a: CompressedAnimation) -> str:
    header = a.header
    frames = header.num_frames if header else 0
    rate = header.frame_rate if header else 0
    return f"COMPRESSED_ANIMATION {a.name}  frames={frames} rate={rate}"


def _hlod_summary(h: HLOD) -> str:
    return f"HLOD {h.model_name} -> {h.hierarchy_name}  lods={len(h.lod_arrays)}"


def _run_info(args: argparse.Namespace) -> int:
    w3d = parse_w3d_from_path(args.w3d)
    for chunk in w3d.chunks:
        if isinstance(chunk, Mesh):
            print(_mesh_summary(chunk))
        elif isinstance(chunk, Hierarchy):
            print(_hierarchy_summary(chunk))
        elif isinstance(chunk, Animation):
            print(_animation_summary(chunk))
        elif isinstance(chunk, CompressedAnimation):
            print(_compressed_animation_summary(chunk))
        elif isinstance(chunk, HLOD):
            print(_hlod_summary(chunk))
        elif isinstance(chunk, CollisionBox):
            print(f"BOX {chunk.name.value}")
        elif isinstance(chunk, Dazzle):
            print(f"DAZZLE {chunk.name} ({chunk.type_name})")
        elif isinstance(chunk, UnknownChunk):
            print(f"{chunk_name(chunk.chunk_type)}  size={len(chunk.data)} bytes")
        else:
            print(chunk_name(_chunk_type_of(chunk)))

    print(f"\ndiagnostics: {len(w3d.diagnostics)}")
    for d in w3d.diagnostics:
        print(f"  offset {d.offset}: {d.message}")
    return 0


def _json_value(obj: object) -> object:
    if isinstance(obj, FixedString):
        result: dict[str, object] = {"value": obj.value}
        try:
            canonical = FixedString.from_value(obj.value, len(obj.raw)).raw
        except ValueError:
            canonical = None
        if canonical != obj.raw:
            result["raw"] = base64.b64encode(obj.raw).decode("ascii")
        return result
    if isinstance(obj, NulString):
        result = {"value": obj.value}
        canonical = obj.value.encode("latin-1") + b"\0"
        if canonical != obj.raw:
            result["raw"] = base64.b64encode(obj.raw).decode("ascii")
        return result
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _json_value(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [_json_value(v) for v in obj]
    return obj


def _run_json(args: argparse.Namespace) -> int:
    w3d = parse_w3d_from_path(args.w3d)
    document = {
        "chunks": [_json_value(c) for c in w3d.chunks],
        "trailing": base64.b64encode(w3d.trailing).decode("ascii"),
        "diagnostics": [_json_value(d) for d in w3d.diagnostics],
    }
    text = json_module.dumps(document, indent=None if args.compact else 2)
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def _iter_w3d_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".w3d")


def _run_check(args: argparse.Namespace) -> int:
    files = _iter_w3d_files(args.path)
    if not files:
        print(f"no .w3d files found under {args.path}")
        return 0

    failures = 0
    total_diagnostics = 0
    for path in files:
        data = path.read_bytes()
        try:
            w3d = parse_w3d_from_path(path)
        except W3DError as exc:
            print(f"FAIL {path}: {exc}")
            failures += 1
            continue

        rewritten = write_w3d(w3d)
        if rewritten != data:
            print(f"FAIL {path}: round-trip mismatch ({len(rewritten)} vs {len(data)} bytes)")
            failures += 1
            continue

        total_diagnostics += len(w3d.diagnostics)
        if w3d.diagnostics:
            print(f"ok   {path}  ({len(w3d.diagnostics)} diagnostic(s))")

    print(f"\n{len(files)} file(s), {failures} failure(s), {total_diagnostics} diagnostic(s)")
    return 1 if failures else 0


def _view_animation_sources(model: W3DFile, anim_path: Path | None) -> list[AnimationSource]:
    """The model's own `animations + compressed_animations`, plus `anim_path`'s (parsed
    separately) if given - the same "model file, optionally plus a standalone animation file"
    shape `examples/sage_w3d/view_model.py`'s `--anim` uses."""
    sources: list[AnimationSource] = [*model.animations, *model.compressed_animations]
    if anim_path is not None:
        anim_model = parse_w3d_from_path(anim_path)
        sources += [*anim_model.animations, *anim_model.compressed_animations]
    return sources


def _run_view(args: argparse.Namespace) -> int:
    try:
        from PyQt6.QtCore import Qt  # noqa: PLC0415 - needs [w3d-view]
        from PyQt6.QtGui import QKeySequence, QShortcut  # noqa: PLC0415 - needs [w3d-view]
        from PyQt6.QtWidgets import QApplication, QMainWindow  # noqa: PLC0415 - needs [w3d-view]

        from sage_w3d.render.viewport import PlaybackController, W3DViewport  # noqa: PLC0415
    except ImportError as exc:
        print(
            f'view: {exc}\nInstall the "w3d-view" extra: pip install "pysage-tools[w3d-view]"',
            file=sys.stderr,
        )
        return 1

    model = parse_w3d_from_path(args.w3d)
    art_dirs = args.art if args.art else [args.w3d.parent]
    scene = build_scene(model, DirectoryResolver(*art_dirs))

    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = QMainWindow()
    window.setWindowTitle(args.w3d.name)
    viewport = W3DViewport(scene)
    window.setCentralWidget(viewport)
    window.resize(900, 700)

    sources = _view_animation_sources(model, args.anim)
    if sources and scene.hierarchy is not None:
        controller = PlaybackController(viewport, parent=window)
        controller.set_evaluator(PoseEvaluator(scene.hierarchy, sources[0]))
        controller.play()
        shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), window)
        shortcut.activated.connect(controller.toggle)

    window.show()
    app.exec()
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    parser = argparse.ArgumentParser(prog="sage-w3d", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    info = subparsers.add_parser("info", help="one-line-per-chunk summary")
    info.add_argument("w3d", type=existing_file)
    info.set_defaults(func=_run_info)

    tree = subparsers.add_parser("tree", help="full recursive chunk tree")
    tree.add_argument("w3d", type=existing_file)
    tree.set_defaults(func=_run_tree)

    to_json = subparsers.add_parser("json", help="the parsed structure as a JSON document")
    to_json.add_argument("w3d", type=existing_file)
    to_json.add_argument("--out", type=Path, default=None, help="write to a file instead of stdout")
    to_json.add_argument("--compact", action="store_true", help="single-line JSON")
    to_json.set_defaults(func=_run_json)

    check = subparsers.add_parser("check", help="round-trip check a file or a directory of them")
    check.add_argument("path", type=existing_path)
    check.set_defaults(func=_run_check)

    view = subparsers.add_parser("view", help="open a PyQt6/OpenGL viewer (needs [w3d-view])")
    view.add_argument("w3d", type=existing_file)
    view.add_argument(
        "--art",
        type=existing_dir,
        nargs="*",
        default=[],
        help="art directories to resolve skeletons/textures from (default: the model's directory)",
    )
    view.add_argument(
        "--anim",
        type=existing_file,
        default=None,
        help="a .w3d carrying animation chunks to play, in addition to the model's own",
    )
    view.set_defaults(func=_run_view)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
