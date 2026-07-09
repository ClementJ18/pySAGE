"""Derive replay id -> definition-name tables from a full engine-order sage_ini load.

Each replay id space is the load-order index of one `sage_ini` `Game` table plus a constant
offset (reverse-engineered from labelled replays, see sage_replay/object_id_mapping_plan.md):

    spellbook science id (0x414 arg1)   = game.sciences index       + 1
    special-power cast id (0x411/0x456) = game.specialpowers index  + 1
    unit recruit id (0x417 flag=false)  = game.objects index        + 1201

The offsets are only constant when the load reproduces the engine's full object set. Edain's
`_mod` alone is missing the base BFME2/RotWK objects it doesn't redefine, so a mod-only load's
object indices fall behind and the offset drifts. This tool first rebuilds the engine's merged
ini tree - base `.big` archives (BFME2 then RotWK, later overriding earlier) with `_mod`
overlaid on top - then loads it; the object offset is then globally constant (verified across
all replay-confirmed units, Gondor + Rohan + Imladris).

Usage:
    python -m tools.replay_idmap --bfme2 C:/BFME2 --rotwk C:/RotWK \
        --mod C:/Users/.../Edain-Mod/_mod/data/ini \
        --merged <scratch>/merged_ini -o object_ids.generated.json
"""

import argparse
import json
import shutil
from pathlib import Path

from pyBIG import Archive

from sage_ini.loader import load_game

# space name -> (Game table attribute, offset)
SPACES = {
    "spellbook_sciences": ("sciences", 1),
    "special_powers": ("specialpowers", 1),
    "objects": ("objects", 1201),
}

# id -> expected template, offset-independent; the load fails loudly if any is off.
ANCHORS = {
    "spellbook_sciences": {
        181: "SCIENCE_NebelbergeTrommel",
        183: "SCIENCE_PaktdesHasses",
        190: "SCIENCE_BalrogAllyWild",
    },
    "special_powers": {
        265: "SpellBookNebelbergeTrommel",
        1097: "SpellBookCaveBats",
        357: "SpellBookBalrogAllyWild",
    },
    # Offset +1201 is validated for the mid-range unit block (6279–9192). It does NOT hold
    # at the top of the object list - CPObject (replay id 11120) lands ~1280 positions late
    # in this load, so the file order still diverges from the engine's for the tail.
    "objects": {
        6279: "GondorFighterHorde",  # lowest confirmed unit
        6348: "GondorWachterderVesteHorde",
        8342: "GondorBatteringRam",
        9192: "RohanTrebuchet",  # highest confirmed unit where +1201 holds
    },
}

_INI_PREFIX = "data\\ini\\"


def build_merged_tree(base_archives: list[Path], mod_dir: Path, out: Path) -> None:
    """Extract every `data\\ini\\…` entry from the base `.big`s (in override order) and
    overlay `mod_dir` on top, reproducing the engine's merged ini filesystem."""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for archive_path in base_archives:
        archive = Archive(archive_path.read_bytes())
        for name in archive.file_list():
            if not name.lower().startswith(_INI_PREFIX):
                continue
            dest = out / name[len(_INI_PREFIX) :].replace("\\", "/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(archive.read_file(name))

    for src in mod_dir.rglob("*"):
        if src.is_file():
            dest = out / src.relative_to(mod_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)


def base_archives(bfme2: Path, rotwk: Path) -> list[Path]:
    """The ini-bearing base archives, in engine override order (later wins)."""
    return [
        bfme2 / "ini.big",
        rotwk / "ini.big",
        rotwk / "_patch201ini.big",
        rotwk / "_____english_ini.big",
    ]


def generate(game, table_attr: str, offset: int) -> dict[str, str]:
    return {str(i + offset): name for i, name in enumerate(getattr(game, table_attr))}


def check_anchors(tables: dict[str, dict[str, str]]) -> list[str]:
    problems = []
    for space, anchors in ANCHORS.items():
        for rid, expected in anchors.items():
            got = tables[space].get(str(rid))
            if got != expected:
                problems.append(f"  {space} id {rid}: expected {expected!r}, got {got!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bfme2", type=Path, required=True, help="BFME2 install dir (has ini.big)")
    parser.add_argument("--rotwk", type=Path, required=True, help="RotWK install dir (has ini.big)")
    parser.add_argument("--mod", type=Path, required=True, help="Edain _mod/data/ini")
    parser.add_argument("--merged", type=Path, required=True, help="where to build the merged tree")
    parser.add_argument("--reuse", action="store_true", help="reuse an existing merged tree")
    parser.add_argument("-o", "--out", type=Path, default=Path("object_ids.generated.json"))
    args = parser.parse_args(argv)

    if not (args.reuse and args.merged.exists()):
        print(f"building merged ini tree at {args.merged} …")
        build_merged_tree(base_archives(args.bfme2, args.rotwk), args.mod, args.merged)

    print("loading merged tree …")
    game = load_game(args.merged).game

    tables = {name: generate(game, attr, off) for name, (attr, off) in SPACES.items()}
    problems = check_anchors(tables)
    if problems:
        print("ANCHOR MISMATCH - offsets no longer hold (mod/base changed?):")
        print("\n".join(problems))
        return 1
    print("anchors OK: sciences (+1), special powers (+1), objects (+1201) all verified")

    payload = {
        "_meta": {
            "source": "generated from the merged BFME2+RotWK+Edain ini load order",
            "offsets": {name: off for name, (_, off) in SPACES.items()},
            "note": "sciences/special-power ids are per-table index + 1 (exact, whole table). "
            "objects are game.objects index + 1201, VALIDATED ONLY for the faction-unit range "
            "(ids ~6279-9192); the engine's object-file load order is not alphabetical, so "
            "'system'/'Projectile'/etc. objects at the tail (e.g. CPObject, replay id 11120) "
            "are mis-placed here. Names are ini template names.",
        },
        **tables,
    }
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(
        f"wrote {args.out}: {len(tables['spellbook_sciences'])} sciences, "
        f"{len(tables['special_powers'])} special powers, {len(tables['objects'])} objects"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
