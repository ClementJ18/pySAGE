"""Build verified hero-horde patch copies or restore the verified source to a separate file."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sage_patch.patches.combo_horde_recruitment import ComboHordeRecruitmentPatch  # noqa: E402
from sage_patch.patches.experimental.hero_horde_death import HeroHordeDeathPatch  # noqa: E402
from sage_patch.patches.horde_herobar import HordeHerobarPatch  # noqa: E402

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
    parser.add_argument(
        "--payload", action="store_true", help="also apply ComboHordeRecruitmentPatch"
    )
    ui = parser.add_mutually_exclusive_group()
    ui.add_argument("--herobar", action="store_true", help="also apply HordeHerobarPatch")
    ui.add_argument("--only-herobar", action="store_true", help="apply only HordeHerobarPatch")
    parser.add_argument(
        "--restore",
        action="store_true",
        help="copy the verified original instead of applying patches",
    )
    args = parser.parse_args()
    if args.restore and (args.payload or args.herobar or args.only_herobar):
        parser.error("--restore cannot be combined with patch selection options")
    if args.only_herobar and args.payload:
        parser.error("--only-herobar cannot be combined with --payload")
    source, target = args.source.resolve(), args.out.resolve()
    if source == target or target.name.lower().endswith(".backup"):
        raise ValueError("Output must be a separate file and may not be a .backup file")
    original = source.read_bytes()
    if digest(original) != SOURCE_SHA256:
        raise ValueError("Input SHA256 differs from the verified game.dat.backup")
    if args.restore:
        write_once(target, original)
        print(f"Restored verified original copy: {target} sha256={SOURCE_SHA256}")
        return
    data = bytearray(original)
    patches = [] if args.only_herobar else [HeroHordeDeathPatch()]
    if args.payload:
        patches.append(ComboHordeRecruitmentPatch())
    if args.herobar or args.only_herobar:
        patches.append(HordeHerobarPatch())
    for patch in patches:
        patch.apply(data)
    # Verify the final combination, including any effects of later patches on earlier ones.
    for patch in patches:
        if problems := patch.verify(data):
            raise ValueError(f"{patch.name}: {problems}")
    write_once(target, bytes(data))
    print(f"Verified patch copy: {target} sha256={digest(data)}")


if __name__ == "__main__":
    main()
