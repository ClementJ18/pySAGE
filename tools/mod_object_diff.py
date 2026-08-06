"""Compare the objects two mods define in the *same* install folder.

A mod switcher rewrites the install in place, so the two sides of the comparison never exist
on disk at once: this snapshots the object names an install defines, waits at the keyboard
while the other mod is activated, snapshots again, and splits the two name sets into shared /
only-A / only-B.

Names are matched case-insensitively (the engine's ini name lookup is), and the original
spelling of the first snapshot that used a name is what gets reported.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # `tools.` imports when run directly

from sage_ini.loader import load_game  # noqa: E402
from sage_ini.subsystems import thing_template_order  # noqa: E402
from sage_utils.gameroot import resolve_game_root  # noqa: E402

__all__ = ["object_names", "snapshot"]


def object_names(root: Path) -> dict[str, str]:
    """Every object name the ini tree at `root` defines, as lowercased-key -> original spelling.

    ThingTemplate registration order is the cheap read (it walks only the object files the
    SubsystemLegend lists, without converting anything to the typed model). A folder with no
    legend is not a full install but can still be a bare mod ini root, so fall back to a full
    load there and take the object table.
    """
    try:
        names = thing_template_order(root)
    except FileNotFoundError:
        names = list(load_game(root).game.objects)
    return {name.lower(): name for name in names}


def snapshot(install: Path, label: str) -> dict[str, str]:
    """Mount the install (if it is a live one) and read its object names, reporting what was
    seen so a mislabelled or half-switched snapshot is obvious before the diff is believed."""
    archives = sorted(path.name for path in install.glob("*.big"))
    print(f"[{label}] mounting {install}")
    if archives:
        print(f"[{label}] archives: {', '.join(archives)}")
    names = object_names(resolve_game_root(install))
    print(f"[{label}] {len(names)} objects")
    return names


def _write_list(path: Path, names: list[str]) -> None:
    path.write_text("".join(f"{name}\n" for name in names), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("install", type=Path, help="install folder holding the .big archives")
    parser.add_argument("--label-a", default="A", help="name for the first snapshot's mod")
    parser.add_argument("--label-b", default="B", help="name for the second snapshot's mod")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(tempfile.gettempdir()) / "sage_mod_object_diff",
        help="folder to write the object lists into",
    )
    parser.add_argument(
        "--sample", type=int, default=15, help="how many names of each group to print (0: none)"
    )
    args = parser.parse_args(argv)

    first = snapshot(args.install, args.label_a)
    print(f"\nswitch the install to {args.label_b}, then press Enter here.")
    input()
    second = snapshot(args.install, args.label_b)

    shared = sorted(first.keys() & second.keys())
    only_a = sorted(first.keys() - second.keys())
    only_b = sorted(second.keys() - first.keys())
    if not only_a and not only_b:
        print("\nthe two snapshots are identical - was the mod actually switched?")

    args.out.mkdir(parents=True, exist_ok=True)
    groups = (
        (f"{args.label_a}: all objects", "a.txt", sorted(first.values(), key=str.lower)),
        (f"{args.label_b}: all objects", "b.txt", sorted(second.values(), key=str.lower)),
        ("shared", "shared.txt", [first[key] for key in shared]),
        (f"only {args.label_a}", "only_a.txt", [first[key] for key in only_a]),
        (f"only {args.label_b}", "only_b.txt", [second[key] for key in only_b]),
    )
    print()
    for title, filename, names in groups:
        _write_list(args.out / filename, names)
        print(f"{title}: {len(names)} -> {args.out / filename}")
        for name in names[: args.sample]:
            print(f"    {name}")
        if args.sample and len(names) > args.sample:
            print(f"    ... {len(names) - args.sample} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
