"""Dump the structures `wotr-battle-observers` reads out of a running battle, as a fixture.

The emulated tests beside the patch run its cave over a world laid out at the offsets
`sage_patch.addresses` declares. That catches everything the cave gets wrong and nothing the
*beliefs* get wrong: a wrong offset and a fixture written at that same wrong offset cancel out.
Bytes taken from the engine cannot do that, because the engine laid them out.

So: get into a War of the Ring battle once, run this, and the numbers that decide every branch are
on disk. Re-checking a belief afterwards costs a `python -c`, not a network session.

Needs an **elevated** shell, because the game runs as administrator.

    python sage_patch/scripts/capture_wotr_battle.py --out battle.json

Excluded from ruff along with the rest of `scripts/`; this talks to a live process and is run by
hand, not imported.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sage_live.backends.memory import ProcessMemory, find_game_processes  # noqa: E402

from sage_patch import addresses as ad  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, default=None)
    parser.add_argument("--out", type=Path, default=Path("wotr_battle.json"))
    args = parser.parse_args()

    pid = args.pid
    if pid is None:
        found = list(find_game_processes())
        if not found:
            print("no running game.dat")
            return 1
        pid = found[0]

    m = ProcessMemory(pid)

    def u32(va: int) -> int | None:
        blob = m.read(va, 4)
        return None if blob is None else struct.unpack("<I", blob)[0]

    def i32(va: int) -> int | None:
        blob = m.read(va, 4)
        return None if blob is None else struct.unpack("<i", blob)[0]

    def u8(va: int) -> int | None:
        blob = m.read(va, 1)
        return None if blob is None else blob[0]

    def ascii_string(va: int) -> str:
        pointer = u32(va)
        if not pointer:
            return ""
        blob = m.read(pointer + 8, 128) or b""
        return blob.split(b"\0")[0].decode("latin1")

    logic = u32(ad.THE_GAME_LOGIC)
    info = u32(ad.THE_GAME_INFO)
    world = u32(ad.THE_LIVING_WORLD_LOGIC)

    out: dict[str, object] = {
        "pid": pid,
        "game_logic": {
            "game_mode": i32(logic + 0x110) if logic else None,
            "living_world_type": i32(logic + ad.GAME_LOGIC_LIVING_WORLD_TYPE) if logic else None,
        },
        "sites": {
            f"{va:#010x}": (m.read(va, n) or b"").hex()
            for va, n in (
                (0x006BEBE5, 2),
                (0x007F67DD, 4),
                (0x00627C41, 6),
                (0x00627C6E, 6),
                (0x00627CC1, 6),
                (0x00627E20, 5),
                (0x00627CEB, 6),
            )
        },
    }

    slots = []
    if info:
        out["auto_resolve_type"] = i32(info + 0x7C)
        for index in range(ad.GAME_INFO_SLOT_COUNT):
            slot = u32(info + ad.GAME_INFO_SLOT_ARRAY + index * 4)
            if not slot:
                slots.append(None)
                continue
            slots.append(
                {
                    "index": index,
                    "address": slot,
                    "state": i32(slot + ad.GAME_SLOT_STATE),
                    "start_pos": i32(slot + ad.GAME_SLOT_START_POS),
                    "player_template": i32(slot + ad.GAME_SLOT_PLAYER_TEMPLATE),
                    "team": i32(slot + ad.GAME_SLOT_TEAM),
                    "map_player": ascii_string(slot + ad.GAME_SLOT_MAP_PLAYER),
                    "living_world_id": i32(slot + ad.GAME_SLOT_LIVING_WORLD_PLAYER_ID),
                    "is_occupied": u8(slot + ad.GAME_SLOT_IS_OCCUPIED),
                }
            )
    out["slots"] = slots

    players = []
    battles = []
    if world:
        out["current_region_id"] = i32(world + ad.LIVING_WORLD_LOGIC_CURRENT_REGION_ID)
        begin = u32(world + ad.LIVING_WORLD_PLAYERS_BEGIN)
        end = u32(world + ad.LIVING_WORLD_PLAYERS_END)
        if begin and end:
            for at in range(begin, end, 4):
                player = u32(at)
                if not player:
                    continue
                players.append(
                    {
                        "address": player,
                        "id": i32(player + ad.LIVING_WORLD_PLAYER_ID),
                        "control": i32(player + 0x44),
                        "vote": i32(player + 0x334),
                        "flag_444": u8(player + 0x444),
                    }
                )
        store = u32(world + ad.LIVING_WORLD_LOGIC_BATTLE_STORE)
        if store:
            first = u32(store + ad.LIVING_WORLD_STORE_BATTLES_BEGIN)
            last = u32(store + ad.LIVING_WORLD_STORE_BATTLES_END)
            for at in range(first or 0, last or 0, 4):
                battle = u32(at)
                if not battle:
                    continue
                region = u32(battle + ad.LIVING_WORLD_BATTLE_REGION)
                sides = []
                side_begin = u32(battle + ad.LIVING_WORLD_BATTLE_SIDES_BEGIN)
                side_end = u32(battle + ad.LIVING_WORLD_BATTLE_SIDES_END)
                for side in range(side_begin or 0, side_end or 0, ad.LIVING_WORLD_BATTLE_SIDE_STRIDE):
                    members = []
                    member_begin = u32(side + ad.LIVING_WORLD_BATTLE_MEMBERS_BEGIN)
                    member_end = u32(side + ad.LIVING_WORLD_BATTLE_MEMBERS_END)
                    step = ad.LIVING_WORLD_BATTLE_MEMBER_STRIDE
                    for member in range(member_begin or 0, member_end or 0, step):
                        who = u32(member)
                        members.append(
                            {"player": who, "id": i32(who + ad.LIVING_WORLD_PLAYER_ID) if who else None}
                        )
                    sides.append(members)
                battles.append(
                    {
                        "address": battle,
                        "region": region,
                        "region_id": i32(region + ad.LIVING_WORLD_REGION_ID) if region else None,
                        "owner": i32(region + ad.LIVING_WORLD_REGION_OWNER) if region else None,
                        "sides": sides,
                    }
                )
    out["living_world_players"] = players
    out["battles"] = battles

    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"  living-world type {out['game_logic']['living_world_type']}, "
          f"current region {out.get('current_region_id')}")
    print(f"  {sum(1 for s in slots if s)} slots, {len(players)} players, {len(battles)} battles")
    for slot in slots:
        if slot:
            print(f"    slot {slot['index']}: state={slot['state']} occupied={slot['is_occupied']} "
                  f"lwId={slot['living_world_id']} mapPlayer={slot['map_player']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
