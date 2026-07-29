"""Read and write the game's skirmish lobby file, so a match can be started to a known setup.

Every live test so far has needed someone to click through the lobby and then *say* what they
picked. That makes a run unrepeatable: change one thing and the previous measurement is no longer
comparable. `Skirmish.ini` is where the engine remembers the lobby, and it is plain text.

**The lobby stores the same string a replay header stores.** The `GameInfo` value is byte-for-byte
the format `sage_replay.ReplayMetadata` already parses - map, map CRC, seed, and a slot list
carrying each player's faction, start position, team and colour. So none of that is re-implemented
here: this module handles the file's own line format and delegates the payload, and
`ReplayMetadata.to_string` is round-trip-tested against the whole replay corpus.

The file's line format is `:<index>:<user>:<key> = <value>`, plus two unprefixed keys:

    :0:B_00e_00n_00:GameInfo = M=387maps/map wor forlindon;MC=440170C3;...;S=HBen,0,0,TT,0,3,...
    :0:B_00e_00n_00:HeroIndexes = :3:-1:-1:-1:-1:-1:-1:-1:
    :0:B_00e_00n_00:Map = maps\\map wor forlindon\\map wor forlindon.map
    CurrentUserName = B_00e_00n_00
    UserNames = B_00e_00n_00_2C_00

**The running game owns this file.** It reads it when the lobby opens and rewrites it when a
match starts, so an edit made while the game is running is either ignored or overwritten. `save`
refuses outright while a `game.dat` is running, rather than writing something that will be lost.

    python tools/skirmish_config.py show
    python tools/skirmish_config.py set --faction 3 --seed 1234
    python tools/skirmish_config.py set --seed 1234 --dry-run   # print, write nothing

**What is verified and what is not.** The `GameInfo` payload round-trips byte-for-byte across the
whole replay corpus, and `faction` is confirmed against a running game (slot faction 3 is
`FactionMen`; that match's local player reported Side `Men`). `start_position` is **not**
confirmed for this file: the replay corpus only ever carries -1..5, while the lobby file holds 51
and 27, so the field either means something else here or was left stale. It is settable, and
deliberately not described as a start position in the CLI help beyond what was measured.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sage_live.memory import find_game_processes  # noqa: E402
from sage_replay.replay import (  # noqa: E402
    ReplayGameType,
    ReplayMetadata,
    ReplaySlot,
    ReplaySlotType,
)

__all__ = [
    "DEFAULT_PATH",
    "SkirmishConfig",
    "SkirmishEntry",
    "default_path",
]

# `:0:User:Key = value`. The value may contain anything, including further colons and equals.
_ENTRY = re.compile(r"^:(\d+):([^:]*):([^:=]+?)\s*=\s*(.*)$")
_PLAIN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")

_USER_DIR = "My The Lord of the Rings, The Rise of the Witch-king Files"
DEFAULT_PATH = Path(os.environ.get("APPDATA", "")) / _USER_DIR / "Skirmish.ini"


def default_path() -> Path:
    """Where RotWK keeps its lobby state for the current Windows user."""
    return DEFAULT_PATH


@dataclass
class SkirmishEntry:
    """One saved lobby configuration, as `:<index>:<user>:<key>` lines.

    `metadata` is the parsed `GameInfo`; mutate its `slots` and call `SkirmishConfig.save`.
    `keys` keeps every line's raw value in file order, so a key this module does not model
    survives a write untouched.
    """

    index: int
    user: str
    keys: dict[str, str] = field(default_factory=dict)
    metadata: ReplayMetadata | None = None

    @property
    def map_path(self) -> str:
        """The `Map` line - a backslashed path to the `.map` file, distinct from `GameInfo`'s."""
        return self.keys.get("Map", "")

    @property
    def occupied(self) -> list[ReplaySlot]:
        return [] if self.metadata is None else self.metadata.players

    def describe(self) -> str:
        if self.metadata is None:
            return f"[{self.index}] {self.user}: no GameInfo"
        lines = [
            f"[{self.index}] {self.user}",
            f"      map   {self.metadata.map_file}",
            f"      seed  {self.metadata.seed}",
            f"      crc   {self.metadata.map_crc:X}  size {self.metadata.map_size}",
        ]
        for position, slot in enumerate(self.metadata.slots):
            if slot.slot_type is ReplaySlotType.Empty:
                continue
            who = (
                slot.human_name
                if slot.slot_type is ReplaySlotType.Human
                else f"AI/{slot.computer_difficulty.name if slot.computer_difficulty else '?'}"
            )
            lines.append(
                f"      slot {position}  {who:<16} faction={slot.faction:<4} "
                f"start={slot.start_position:<4} team={slot.team:<3} colour={slot.color}"
            )
        return "\n".join(lines)


@dataclass
class SkirmishConfig:
    """The whole file: saved entries plus the two unprefixed user keys."""

    entries: list[SkirmishEntry] = field(default_factory=list)
    plain: dict[str, str] = field(default_factory=dict)
    # Line order is preserved exactly, because the engine rewrites this file itself and a
    # reordered file is a gratuitous diff against whatever it writes next.
    order: list[tuple[int, str, str] | str] = field(default_factory=list)

    @staticmethod
    def parse(text: str, game_type: ReplayGameType = ReplayGameType.Bfme2) -> SkirmishConfig:
        config = SkirmishConfig()
        by_key: dict[tuple[int, str], SkirmishEntry] = {}
        for line in text.splitlines():
            if not line.strip():
                continue
            entry_match = _ENTRY.match(line)
            if entry_match:
                index, user, key, value = entry_match.groups()
                entry = by_key.get((int(index), user))
                if entry is None:
                    entry = SkirmishEntry(index=int(index), user=user)
                    by_key[(int(index), user)] = entry
                    config.entries.append(entry)
                entry.keys[key] = value
                config.order.append((int(index), user, key))
                if key == "GameInfo":
                    entry.metadata = ReplayMetadata.from_string(value, game_type)
                continue
            plain_match = _PLAIN.match(line)
            if plain_match:
                config.plain[plain_match.group(1)] = plain_match.group(2)
                config.order.append(plain_match.group(1))
        return config

    @staticmethod
    def load(path: Path | None = None) -> SkirmishConfig:
        return SkirmishConfig.parse((path or default_path()).read_text(encoding="latin-1"))

    def render(self) -> str:
        """The file back, in its original line order, with `GameInfo` rebuilt from `metadata`."""
        by_key = {(e.index, e.user): e for e in self.entries}
        lines: list[str] = []
        for item in self.order:
            if isinstance(item, str):
                lines.append(f"{item} = {self.plain[item]}")
                continue
            index, user, key = item
            entry = by_key[(index, user)]
            value = entry.keys[key]
            if key == "GameInfo" and entry.metadata is not None:
                value = entry.metadata.to_string()
            lines.append(f":{index}:{user}:{key} = {value}")
        return "\n".join(lines) + "\n"

    def save(self, path: Path | None = None) -> Path:
        """Write the file back. Refuses while a game is running - it would be overwritten."""
        target = path or default_path()
        if find_game_processes():
            raise RuntimeError(
                "game.dat is running; it rewrites Skirmish.ini when a match starts, so this "
                "edit would be lost. Close the game first."
            )
        target.write_text(self.render(), encoding="latin-1")
        return target

    def for_user(self, user: str | None = None) -> list[SkirmishEntry]:
        """Entries belonging to one user, `CurrentUserName` by default."""
        name = user if user is not None else self.plain.get("CurrentUserName", "")
        return [e for e in self.entries if e.user == name] or list(self.entries)

    def entry(self, index: int = 0, user: str | None = None) -> SkirmishEntry | None:
        """One saved configuration by its `:<index>:` number.

        **What the index means is not established.** The file holds several entries and the
        engine picks one; measured once, a solo skirmish launched from the menu ran the
        configuration in entry **0**, while entry 1 held a two-slot setup for a different map.
        That is consistent with the index bucketing by player count, and equally consistent with
        it being an arbitrary save slot - one observation cannot tell those apart. So this takes
        the index explicitly and defaults to 0, which is the one observed to be live, rather
        than guessing at "most recent".
        """
        return next((e for e in self.for_user(user) if e.index == index), None)


def _slot_of(entry: SkirmishEntry, index: int | None) -> tuple[int, ReplaySlot]:
    """The slot to edit: the one asked for, else the only occupied human slot."""
    if entry.metadata is None:
        raise SystemExit("this entry has no GameInfo to edit")
    total = len(entry.metadata.slots)
    if index is not None:
        if not 0 <= index < total:
            raise SystemExit(f"slot {index} is outside the {total} slots in this file")
        return index, entry.metadata.slots[index]
    humans = [
        (i, s) for i, s in enumerate(entry.metadata.slots) if s.slot_type is ReplaySlotType.Human
    ]
    if len(humans) != 1:
        raise SystemExit(f"{len(humans)} human slots here - name one with --slot")
    return humans[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", type=Path, default=None, help="Skirmish.ini (default: AppData)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("show", help="print every saved lobby configuration")

    edit = sub.add_parser("set", help="change fields of one slot, and write the file back")
    edit.add_argument("--entry", type=int, default=0, help="which saved configuration (default 0)")
    edit.add_argument("--slot", type=int, help="slot index (default: the only human slot)")
    edit.add_argument("--faction", type=int, help="PlayerTemplate index; -1 is lobby Random")
    edit.add_argument(
        "--start", type=int, help="slot field 7 (start position in replays; see docs)"
    )
    edit.add_argument("--team", type=int)
    edit.add_argument("--colour", type=int)
    edit.add_argument("--seed", type=int, help="the match seed - the whole point of this tool")
    edit.add_argument("--dry-run", action="store_true", help="print the result, write nothing")

    args = parser.parse_args(argv)
    path = args.path or default_path()
    if not path.is_file():
        raise SystemExit(f"no Skirmish.ini at {path}")
    config = SkirmishConfig.load(path)

    if args.command == "show":
        print(f"{path}\n")
        for entry in config.entries:
            print(entry.describe())
        print(f"\ncurrent user {config.plain.get('CurrentUserName', '?')}")
        print("a solo skirmish launched from the menu was observed running entry [0]")
        return 0

    entry = config.entry(args.entry)
    if entry is None:
        raise SystemExit(f"no entry [{args.entry}] in this file - run `show`")
    index, slot = _slot_of(entry, args.slot)
    for name, value in (
        ("faction", args.faction),
        ("start_position", args.start),
        ("team", args.team),
        ("color", args.colour),
    ):
        if value is not None:
            print(f"  slot {index}: {name} {getattr(slot, name)} -> {value}")
            setattr(slot, name, value)
    if args.seed is not None and entry.metadata is not None:
        print(f"  seed {entry.metadata.seed} -> {args.seed}")
        entry.metadata.seed = args.seed

    if args.dry_run:
        print("\n--- would write ---")
        print(config.render())
        return 0
    try:
        print(f"\nwrote {config.save(path)}")
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
