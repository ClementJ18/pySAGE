"""Add a checkbox row to the shell Options screen's APT movie.

The engine side of a new option is `unit-plate-option`'s ladder and save hooks; this is the other
half. `AptOptions::InitGadgets` dispatches on a gadget's **instance name**, so the row exists as
soon as the movie declares a clip called `Options::<Something>` that names the init callback -
see `../docs/options-menu-rows.md` §4.

Three blocks go in: the checkbox (a copy of `Options::HealthBars` at a free depth and a free slot
in the column), a label `edittext` appended past the last character, and a placement for that
label. Everything else in the movie is left alone, and `sage_apt` round-trips the file byte-exact,
so the diff is only what is asked for here.

Usage:
    python options_add_row.py <apt/options.big> --out <dir>
    python options_add_row.py <apt/options.big> --out <dir> \\
        --gadget Options::UnitPlates --label EnableUnitPlates --y 270.05

The output directory receives the loose movie files (`Options.apt`, `Options.const`, `Options.dat`
and the `Options_geometry/` tree), which is the shape a mod's `apt/` folder wants. The label
resolves through the string table as `APT:<label>`, so add that key to `Lotr.csv` in every
language the mod ships.
"""

from __future__ import annotations

import argparse
import re
import struct
import subprocess
import sys
from pathlib import Path

#: The stock `Options::HealthBars` checkbox is the template: same character (the imported
#: `CheckBox`), same clip actions, same column. Only the depth, the name and the row change.
CHECKBOX = """        <placeobject depth="{depth}" character="98" rotm00="0.99998474" rotm01="0" rotm10="0"\
 rotm11="1" tx="{x}" ty="{y}" red="255" green="255" blue="255" alpha="255" ratio="0"\
 clipdepth="-1" unknown="0">
          <poflags value="HasCharacter|HasClipActions|HasMatrix|HasName"/>
          <poname name="{gadget}"/>
          <clipactions>
            <clipaction flags="512" flags2="0">
              <pushstring str="_type"/>
              <setstringvar str="CheckBox"/>
              <pushstring str="_Load"/>
              <setstringvar str="Apt/CheckBox.wnd"/>
              <pushstring str="_Init"/>
              <setstringvar str="AptOptions::InitGadgets"/>
              <pushstring str="_CheckBoxString"/>
              <setstringvar str=""/>
              <end/>
            </clipaction>
          </clipactions>
        </placeobject>
"""

#: Copied from `edittext` 146, the `$EnableHealthBars` label, so the new one matches the column's
#: font, colour and metrics exactly.
LABEL_CHARACTER = """  <edittext id="{cid}" top="-2" left="-2" bottom="21.15" right="176" font="2" alignment="0"\
 red="255" green="138" blue="193" alpha="77" height="16" readonly="1" multiline="0" wordwrap="0">
    <ettext text="${label}"/>
    <etvar variable=""/>
  </edittext>
"""

LABEL_PLACEMENT = """        <placeobject depth="{depth}" character="{cid}" rotm00="1" rotm01="0" rotm10="0"\
 rotm11="1" tx="{x}" ty="{y}" red="255" green="255" blue="255" alpha="255" ratio="0"\
 clipdepth="-1" unknown="0">
          <poflags value="HasCharacter|HasMatrix|HasName"/>
          <poname name="{name}"/>
        </placeobject>
"""

#: The row this one is inserted after, and the label beside it. Both are on the Graphics page, in
#: the left-hand column that runs Brightness (169/197), HealthBars (230/236), ScrollSpeed (316/344)
#: - so the default `--y` of 270 is the free slot between the second and the third.
ANCHOR_GADGET = "Options::HealthBars"
ANCHOR_LABEL = 'depth="23" character="146"'


def unpack_big(path: Path, out: Path) -> list[str]:
    """Extract a `.big` archive, preserving its entry names."""
    data = path.read_bytes()
    # Both magics ship: `apt/*.big` are BIGF, the `.big`s at the game root are BIG4.
    if data[:4] not in (b"BIG4", b"BIGF"):
        raise SystemExit(f"{path} is not a BIG archive")
    count = struct.unpack_from(">I", data, 8)[0]
    off, names = 16, []
    for _ in range(count):
        entry_off, size = struct.unpack_from(">II", data, off)
        off += 8
        end = data.index(b"\x00", off)
        name = data[off:end].decode("latin-1")
        off = end + 1
        names.append(name)
        target = out / name.replace("\\", "/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data[entry_off : entry_off + size])
    return names


def insert_rows(xml: Path, gadget: str, label: str, name: str, x: float, y: float,
                depth: int, label_depth: int) -> None:
    """Splice the three blocks into a decompiled `Options.xml`, bottom-up so line numbers hold."""
    lines = xml.read_text(encoding="utf-8").splitlines(keepends=True)
    text = "".join(lines)
    if gadget in text:
        raise SystemExit(f"{xml} already declares {gadget}")

    cid = max(int(m) for m in re.findall(r'^  <[a-z]+ id="(\d+)"', text, re.M)) + 1
    last_char = max(
        i for i, line in enumerate(lines) if re.match(r'^  <[a-z]+ id="\d+"', line)
    )
    while "/>" not in lines[last_char] and not lines[last_char].startswith("  </"):
        last_char += 1

    def end_of_placeobject(start: int) -> int:
        i = start
        while "</placeobject>" not in lines[i]:
            i += 1
        return i + 1

    anchor_gadget = next(i for i, line in enumerate(lines) if f'"{ANCHOR_GADGET}"' in line)
    anchor_label = next(i for i, line in enumerate(lines) if ANCHOR_LABEL in line)

    # Bottom-up: the character list is last, then the label placement, then the checkbox.
    lines.insert(last_char + 1, LABEL_CHARACTER.format(cid=cid, label=label))
    lines.insert(
        end_of_placeobject(anchor_label),
        LABEL_PLACEMENT.format(depth=label_depth, cid=cid, x=x + 35.85, y=y + 6.45, name=name),
    )
    lines.insert(
        end_of_placeobject(anchor_gadget),
        CHECKBOX.format(depth=depth, x=x, y=y, gadget=gadget),
    )
    xml.write_text("".join(lines), encoding="utf-8")
    print(f"inserted {gadget} at depth {depth}, label character {cid} (${label})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("options_big", type=Path, help="the stock apt/options.big")
    ap.add_argument("--out", type=Path, required=True, help="directory for the rebuilt movie")
    ap.add_argument("--gadget", default="Options::UnitPlates")
    ap.add_argument("--label", default="EnableUnitPlates", help="string key, minus the APT: prefix")
    ap.add_argument("--name", default="UnitPlates", help="instance name for the label clip")
    ap.add_argument("--x", type=float, default=-99.800003)
    ap.add_argument("--y", type=float, default=270.04999)
    ap.add_argument("--depth", type=int, default=17)
    ap.add_argument("--label-depth", type=int, default=26)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    unpack_big(args.options_big, args.out)
    apt = args.out / "Options.apt"
    if not apt.exists():
        raise SystemExit(f"{args.options_big} holds no Options.apt")

    run = [sys.executable, "-m", "sage_apt"]
    subprocess.run([*run, "to-xml", str(apt)], check=True)
    insert_rows(
        apt.with_suffix(".xml"), args.gadget, args.label, args.name,
        args.x, args.y, args.depth, args.label_depth,
    )
    subprocess.run([*run, "to-apt", str(apt.with_suffix(".xml"))], check=True)
    subprocess.run([*run, "check", str(apt)], check=True)
    print(f"\nrebuilt movie in {args.out}")
    print(f"add APT:{args.label.lower()} to Lotr.csv, and apply `unit-plate-option` to game.dat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
