"""Safe reproducible hero-horde PoC build/restore; never edits its input. See German docs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sage_patch.patches.combo_horde_recruitment import ComboHordeRecruitmentPatch  # noqa: E402
from sage_patch.patches.experimental.hero_horde_death import (  # noqa: E402
    ANCHORS,
    HOOK,
    HeroHordeDeathPatch,
)
from sage_patch.patches.horde_herobar import (  # noqa: E402
    ANCHORS as HEROBAR_ANCHORS,
)
from sage_patch.patches.horde_herobar import (  # noqa: E402
    HOOK as HEROBAR_HOOK,
)
from sage_patch.patches.horde_herobar import HordeHerobarPatch  # noqa: E402
from sage_patch.pe import image_sections  # noqa: E402
from sage_patch.utils import file_offset  # noqa: E402

SOURCE_SHA256 = "5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26"


def digest(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def write_once(path: Path, content: bytes) -> None:
    """Repeat identical builds without rewriting; refuse to replace any other existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"Output exists with different content: {path}")
        return
    with path.open("xb") as stream:
        stream.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--payload", action="store_true", help="add separate combo-horde patch")
    ui = parser.add_mutually_exclusive_group()
    ui.add_argument("--herobar", action="store_true", help="add HordeHerobarPatch independently")
    ui.add_argument("--only-herobar", action="store_true", help="build only HordeHerobarPatch")
    parser.add_argument("--restore", type=Path, metavar="MANIFEST", help="restore verified source")
    args = parser.parse_args()
    source, target = args.source.resolve(), args.out.resolve()
    manifest_path = target.with_name(target.name + ".json")
    if source == target or target.name.endswith(".backup") or manifest_path == source:
        raise ValueError("Output must be a separate file and may not be a .backup file")
    original = source.read_bytes()
    if digest(original) != SOURCE_SHA256:
        raise ValueError("Input SHA256 differs from the verified game.dat.backup")
    if args.restore:
        if args.payload or args.herobar or args.only_herobar:
            raise ValueError("--restore cannot be combined with patch selection options")
        manifest = json.loads(args.restore.read_text())
        patched = Path(manifest["output"])
        if digest(patched.read_bytes()) != manifest["output_sha256"]:
            raise ValueError("Patched file differs from the restore manifest")
        if manifest["source_sha256"] != SOURCE_SHA256:
            raise ValueError("Manifest source hash differs")
        if target == patched.resolve() or target == args.restore.resolve():
            raise ValueError("Restore output must also be separate from the patch and manifest")
        write_once(target, original)
        print(f"Restored verified original copy: {target} sha256={SOURCE_SHA256}")
        return
    data = bytearray(original)
    if args.only_herobar and args.payload:
        raise ValueError("--only-herobar cannot be combined with --payload")
    patches = [] if args.only_herobar else [HeroHordeDeathPatch()]
    if args.payload:
        patches.append(ComboHordeRecruitmentPatch())
    if args.herobar or args.only_herobar:
        patches.append(HordeHerobarPatch())
    selected_anchors = {} if args.only_herobar else dict(ANCHORS)
    if args.herobar or args.only_herobar:
        selected_anchors.update(HEROBAR_ANCHORS)
    primary_hook = HEROBAR_HOOK if args.only_herobar else HOOK
    for patch in patches:
        patch.apply(data)
        if problems := patch.verify(data):
            raise ValueError(f"{patch.name}: {problems}")
    manifest = {
        "schema": 1,
        "status": "experimental; static and emulation checks only; no game runtime validation",
        "source": str(source),
        "source_sha256": SOURCE_SHA256,
        "output": str(target),
        "output_sha256": digest(data),
        "patches": [p.name for p in patches],
        "hook": {
            "va": hex(primary_hook),
            "rva": hex(primary_hook - 0x400000),
            "file_offset": hex(file_offset(original, primary_hook)),
        },
        "anchors": {hex(va): expected.hex() for va, expected in selected_anchors.items()},
        "sections": [
            {
                "name": s.name,
                "va": hex(s.virtual_address),
                "file_offset": hex(s.raw_offset),
                "size": s.virtual_size,
            }
            for s in image_sections(data)
        ],
    }
    content = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
    # Preflight BOTH destinations before creating either one.
    for path, wanted in ((target, bytes(data)), (manifest_path, content)):
        if path.exists() and path.read_bytes() != wanted:
            raise ValueError(f"Output exists with different content: {path}")
    write_once(target, bytes(data))
    write_once(manifest_path, content)
    print(f"Verified PoC copy: {target} sha256={digest(data)}")


if __name__ == "__main__":
    main()
