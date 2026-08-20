"""Why the spell store is dead at a raised client rate, branched in one live reading.

`sage_patch/docs/render-rate.md` §9.6 records the symptom and stops at "mechanism unknown":
at a faster client the spellbook goes grey and no power can be bought, and it reproduces on a
**stock** binary with Edain's debug `x2 speed` button, so it is not the render-rate patch's
doing. What it never established is *which* of four different failures is happening, and each
one leads somewhere else.

The store is `SpellStore.apt` driven by `AptSpellStore`, and the two halves are separable:

  * **The engine decides the colour.** `AptSpellStore::update` (`0x00822E43`) recomputes a
    state per button every client frame and calls `SetSpellButtonState` (`0x008229B5`) only
    when it differs from the cached one - so the cache at `this+0x2AC` *is* what the movie is
    showing. The state is an index into the table at `0x00C50BF8`: `_unused`, `_disabled`,
    `_disabled_level`, `_already_purchased`, `_purchased`, `_active`. The APT plays whatever
    label it is handed; it does not decide anything.

  * **The APT decides whether a click is delivered.** Every spell button's handler reads
    `extern["AptSpellStore::InputEnabled"]` first and returns without calling `OnBttnSpell`
    when it is false. That getter is `0x00822974` and is two comparisons, both readable here.

So the outcomes it tells apart:

  * **every button `_unused`** - the button array was never filled, which points at the
    `AptSpellStore::OnInitialized` handshake (`0x0082334C` resolves `SpellStore/Buttons/Spell%d`).
  * **every button `_disabled`** - `0x005FED5B` is answering false, which is prerequisites
    (`0x005FED05`) *and* `cost (0x005FEC64) <= availablePoints (vtable+4 on this+0x288)`.
  * **buttons `_active` but nothing buyable** - the states are right and the click is being
    swallowed, by the input gate or by the closing latch at `this+0x2A2`.
  * **the instance is null** - the store never constructed at all.

**Two things measured on 2026-08-20 change how any of that reads, and both are in the engine
rather than in the rate.** Opening the panel puts `GameEngine::update` into its modal spin
(`THE_MODAL_SCREEN`), so the client and logic frames stop entirely for as long as the store is
up - which means the button colours *cannot* refresh while you are looking at them. And
`OnBttnSpell` buys nothing: it stages the science in the basket at `this+0x290` and leaves the
commit to close. Between them, "I clicked an available spell and the screen did not react" is
what a working store looks like, so the basket is the only honest evidence a click landed.

Read-only, needs no patch, and it needs an elevated shell because `game.dat` runs as
administrator. **Open the spell store before running it** - `update` returns early while the
panel is shut (`this+0x2A0`) - and give the game focus, which is what `--delay` is for.

    python examples/sage_live/spell_store_probe.py --delay 10 --seconds 5 --json store-30.json
    python examples/sage_live/spell_store_probe.py --game "C:/Program Files (x86)/Games/bfme/rotwk"

To test the basket rather than the colours: start it with `--delay`, click a spell that reads
`_active` while it samples, and watch `staged points seen as` change. It either moves or it
does not, and that is the whole question.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from sage_live.backends.memory import ProcessMemory, find_game_processes  # noqa: E402

# The pacing globals, only so a reading is stamped with the rate it was taken at - this probe
# does not care how the rate got raised, which is the point of it working on a stock binary.
CLIENT_RATE = 0x00D9F60C
THE_GAME_CLIENT = 0x00DE4388
CLIENT_FRAME = 0x10  # GameClient+0x10
THE_GAME_LOGIC = 0x00DE412C
LOGIC_FRAME = 0x40  # GameLogic+0x40
THE_IN_GAME_UI = 0x00DE4830

# `AptSpellStore`. The instance is stored to this global by its own constructor at
# `0x00823852`, in the same block that registers the `AptSpellStore::OnInitialized` callback -
# so a null here means the store has never been built, not that it is merely closed.
THE_APT_SPELL_STORE = 0x00DE8AD4

# `update` also aborts before `this+0x2A0` when the UI singleton at `[0x00DE4A70]` is null or
# `0x006D4609` answers false (it tests `[[that]+0x10]+0x60 & 7`). Named only by address: the same
# global fronts the tooltip builder (`addresses.DESCRIPTION_TAIL`), and what it is has never been
# pinned down. Reported because "update never ran" and "update ran and chose _disabled" are
# different bugs, and the button table alone cannot tell them apart.
THE_UI_PRECONDITION = 0x00DE4A70

# The engine's modal-screen pointer, and the reason the game stops dead while the store is open.
# `GameEngine::update` (`0x0044181F`) tail-calls the normal path only when this is null; when it
# is set it enters a spin at `0x0044184C` - `Sleep(5)`, pump, repeat - which never reaches the
# client or logic update, so both frame counters stand still while the window stays responsive.
# It leaves that spin for `TheGameLogic+0x110` of 1 or 5 only, so a skirmish (mode 2) stays in it.
# Designed behaviour, unrelated to the client rate, and it means `AptSpellStore::update` - the
# only thing that repaints a button - cannot run for as long as the panel is up.
THE_MODAL_SCREEN = 0x00DC3C64

# The basket. `OnBttnSpell` does not buy anything: `0x0082355F` appends the science to the vector
# at `this+0x290` and adds its cost to the running total at `this+0x29C`, and `OnBttnReset`
# (`0x00823484`) clears exactly those two. So a click stages a purchase locally and something on
# close commits it - which makes "I clicked and nothing happened" the expected appearance, not a
# symptom, and makes this vector the only evidence that a click was received at all.
STORE_STAGED_BEGIN = 0x290
STORE_STAGED_END = 0x294
STORE_STAGED_COST = 0x29C

# Fields, all read off `update` (`0x00822E43`) with `esi = this`.
STORE_ENABLED = 0x2A0  # 0x00822E72: update returns immediately while this is 0
STORE_LAYOUT = 0x2A4  # cached GetLayout(): 0 campaignGood, 1 campaignEvil, 2/3 multiplayer
STORE_SOURCE = 0x288  # embedded object; vtable +0 "holds it", +4 available points, +8 level
STORE_SELECTED = 0x354  # hovered/selected button index, -1 for none

# The one gate the click path has and the colour path does not, which makes it the only way the
# store can read healthy and still refuse every purchase. `OnBttnSpell` (`0x008235A5`) discards
# the click at `0x008235D5` while `+0x2A2` is set; the close routine at `0x008228AD` sets it and
# then sets `+0x2A3` once it has told the movie. `update` never looks at either, so buttons go on
# being coloured `_active` behind a store that is treating itself as shut.
STORE_CLOSING = 0x2A2
STORE_CLOSE_SENT = 0x2A3
STORE_HELP_SHOWN = 0x358  # cached `ShowSpellHelpText` state
STORE_SUPPRESS = 0x359  # set at 0x0082313A once the description has been pushed
STORE_BUTTONS = 0x2A8  # CommandButton pointer, stride 8
STORE_STATES = 0x2AC  # the state last sent to the movie, stride 8
STORE_SLOTS = 20  # `cmp dword ptr [ebp - 0x14], 0x14` at 0x0082324E

# CommandButton's science vector, from 0x008231DD and 0x00823057: `{begin, end}` of ids.
BUTTON_SCIENCES = 0xA4
BUTTON_SCIENCES_END = 0xA8

# `0x00C50BF8`, indexed by the state `update` computes. The two that matter are 1 and 5.
STATE_NAMES = {
    0: "_unused",
    1: "_disabled",
    2: "_disabled_level",
    3: "_already_purchased",
    4: "_purchased",
    5: "_active",
}

# The layouts `SetLayout` is sent, from 0x00822E8E: GetLayout returns 2 for a multiplayer game
# and 3 for an Angmar campaign seat, both of which take the `_multiplayer` movie label.
LAYOUT_NAMES = {0: "_campaignGood", 1: "_campaignEvil", 2: "_multiplayer", 3: "_multiplayer"}

# `0x00822974`: the getter behind `extern["AptSpellStore::InputEnabled"]`. It is
# `(TheGameLogic[0x110] == 6) || (TheInGameUI[0x16] != 0)`, returning the strings "1" or "0".
GAME_LOGIC_MODE = 0x110
IN_GAME_UI_FLAG = 0x16
INPUT_ENABLED_MODE = 6


class Probe:
    """Typed reads against the live process. Every accessor returns None on a failed read."""

    def __init__(self, memory: ProcessMemory) -> None:
        self.memory = memory

    def u32(self, address: int) -> int | None:
        raw = self.memory.read(address, 4)
        return struct.unpack("<I", raw)[0] if raw else None

    def i32(self, address: int) -> int | None:
        raw = self.memory.read(address, 4)
        return struct.unpack("<i", raw)[0] if raw else None

    def u8(self, address: int) -> int | None:
        raw = self.memory.read(address, 1)
        return raw[0] if raw else None

    def pointer(self, address: int) -> int | None:
        value = self.u32(address)
        return value if value and 0x00010000 <= value <= 0x7FFFFFFF else None


def science_names(game: str | Path | None) -> dict[int, str]:
    """Science ids to names, or an empty map when `--game` was not given.

    The ids the engine holds are `game.sciences` index + 1 (`sage_replay.idspace`), and the
    only honest way to reproduce that numbering is to load the ini the same way the live
    resolver does - the load order is what assigns the ids, so a hand-rolled parse of
    `science.ini` would mislabel every button rather than fail. Loading is slow enough to be
    opt-in, and a table of raw ids already branches the investigation.
    """
    if game is None:
        return {}
    from sage_live.utils.resolve import Resolver  # noqa: PLC0415 - only when naming was asked for
    from sage_replay.idspace import SCIENCE_OFFSET  # noqa: PLC0415
    from sage_utils.gameroot import resolve_game_root  # noqa: PLC0415

    resolver = Resolver.from_root(resolve_game_root(game))
    order = list(resolver.game.sciences)
    return {index + SCIENCE_OFFSET: name for index, name in enumerate(order)}


def _or_unreadable(value: int | None) -> int:
    return -1 if value is None else value


def read_gates(probe: Probe, store: int) -> dict:
    """What stops `update` before it computes a button state, as far as it reads from outside.

    Two of its three preconditions are plain reads. The third is `0x006D4609`, a predicate over
    the same singleton, which cannot be evaluated without calling it - so a run that reports
    both of these healthy and a stale button table has that call as its remaining suspect.
    """
    enabled = probe.u8(store + STORE_ENABLED)
    layout = probe.i32(store + STORE_LAYOUT)
    return {
        "ui_precondition": probe.pointer(THE_UI_PRECONDITION),
        "modal": probe.pointer(THE_MODAL_SCREEN),
        "enabled": enabled,
        "layout": layout,
        "layout_name": LAYOUT_NAMES.get(layout) if layout is not None else None,
        "closing": probe.u8(store + STORE_CLOSING),
        "close_sent": probe.u8(store + STORE_CLOSE_SENT),
        "selected": probe.i32(store + STORE_SELECTED),
        "help_shown": probe.u8(store + STORE_HELP_SHOWN),
        "suppress": probe.u8(store + STORE_SUPPRESS),
        "source_vtable": probe.u32(store + STORE_SOURCE),
    }


def read_input_gate(probe: Probe) -> dict:
    """`AptSpellStore::InputEnabled`, recomputed here exactly as `0x00822974` computes it.

    Recomputed rather than read because the movie holds no copy: the getter runs on every
    click, so the only way to know what a click would have seen is to evaluate the same two
    comparisons against the same two objects.
    """
    logic = probe.pointer(THE_GAME_LOGIC)
    ui = probe.pointer(THE_IN_GAME_UI)
    mode = probe.i32(logic + GAME_LOGIC_MODE) if logic else None
    flag = probe.u8(ui + IN_GAME_UI_FLAG) if ui else None
    enabled = None
    if mode is not None and flag is not None:
        enabled = mode == INPUT_ENABLED_MODE or flag != 0
    return {
        "game_logic_mode": mode,
        "in_game_ui_flag": flag,
        "input_enabled": enabled,
    }


def read_basket(probe: Probe, store: int, names: dict[int, str]) -> dict:
    """What the store has staged but not yet committed - the only proof a click was received.

    While the panel is up the game is in the modal spin (see `THE_MODAL_SCREEN`), so nothing
    repaints and nothing in the simulation moves. A click still runs `OnBttnSpell`, because the
    spin pumps input, and its whole effect is to land here. An empty basket after clicking a
    button that reads `_active` therefore means the click never reached the handler; a full one
    means it did, and the question moves to whether closing the store commits it.
    """
    begin = probe.pointer(store + STORE_STAGED_BEGIN)
    end = probe.u32(store + STORE_STAGED_END)
    staged: list[dict] = []
    if begin and end and end >= begin:
        for index in range((end - begin) // 4):
            science = probe.i32(begin + index * 4)
            staged.append({"science": science, "science_name": names.get(science or -1)})
    return {"staged": staged, "cost": probe.i32(store + STORE_STAGED_COST)}


def read_buttons(probe: Probe, store: int, names: dict[int, str]) -> list[dict]:
    """One row per slot: the CommandButton, its first science, and the state the movie is in."""
    rows = []
    for slot in range(STORE_SLOTS):
        button = probe.u32(store + STORE_BUTTONS + slot * 8)
        state = probe.i32(store + STORE_STATES + slot * 8)
        science = None
        count = None
        if button:
            begin = probe.pointer(button + BUTTON_SCIENCES)
            end = probe.u32(button + BUTTON_SCIENCES_END)
            if begin and end and end >= begin:
                count = (end - begin) // 4
                science = probe.i32(begin) if count else None
        rows.append(
            {
                "slot": slot,
                "button": button,
                "state": state,
                "state_name": STATE_NAMES.get(state) if state is not None else None,
                "science": science,
                "science_name": names.get(science) if science is not None else None,
                "science_count": count,
            }
        )
    return rows


def watch(probe: Probe, store: int, seconds: float) -> dict:
    """Every distinct state vector the store passes through, and the gate alongside it.

    A single reading is not enough on its own. `update` only pushes a state that *changed*, so
    a button that reached `_active` once and fell back to `_disabled` is indistinguishable from
    one that was never active - unless the fallback is caught happening. This is also what
    catches an input gate that flickers rather than sitting false.
    """
    seen: Counter[tuple[int, ...]] = Counter()
    gates: Counter[bool | None] = Counter()
    latches: Counter[int | None] = Counter()
    costs: Counter[int | None] = Counter()
    samples = 0

    # The rate has to be measured in wall clock, not read. Edain's debug `x2 speed` button - the
    # repro §9.6 rests on - leaves `[0x00D9F60C]` at 30 and changes the loop pace instead, and it
    # does not touch the client-to-logic ratio either. So neither the rate constant nor the two
    # frame counters distinguish a doubled client from a stock one; only frames per second does.
    client = probe.pointer(THE_GAME_CLIENT)
    logic = probe.pointer(THE_GAME_LOGIC)
    first_client = probe.u32(client + CLIENT_FRAME) if client else None
    first_logic = probe.u32(logic + LOGIC_FRAME) if logic else None

    start = time.perf_counter()
    while time.perf_counter() - start < seconds:
        latches[probe.u8(store + STORE_CLOSING)] += 1
        costs[probe.i32(store + STORE_STAGED_COST)] += 1
        # An unreadable slot reads back as -1, never as 0: a failed read that looked like
        # `_unused` would land the verdict on the one outcome that is hardest to disprove.
        states = tuple(
            _or_unreadable(probe.i32(store + STORE_STATES + slot * 8))
            for slot in range(STORE_SLOTS)
        )
        seen[states] += 1
        gates[read_input_gate(probe)["input_enabled"]] += 1
        samples += 1

    elapsed = time.perf_counter() - start
    last_client = probe.u32(client + CLIENT_FRAME) if client else None
    last_logic = probe.u32(logic + LOGIC_FRAME) if logic else None
    measured = {"elapsed": round(elapsed, 3), "client_fps": None, "logic_fps": None}
    if first_client is not None and last_client is not None and elapsed > 0:
        measured["client_fps"] = round((last_client - first_client) / elapsed, 2)
    if first_logic is not None and last_logic is not None and elapsed > 0:
        measured["logic_fps"] = round((last_logic - first_logic) / elapsed, 2)

    return {
        "measured": measured,
        "closing_seen": {str(key): value for key, value in latches.items()},
        "staged_cost_seen": {str(key): value for key, value in costs.items()},
        "samples": samples,
        "distinct_state_vectors": len(seen),
        "vectors": [
            {"count": count, "states": list(states)} for states, count in seen.most_common(8)
        ],
        "input_enabled_seen": {str(key): value for key, value in gates.items()},
    }


def verdict(
    gates: dict, buttons: list[dict], gate: dict, flicker: dict, basket: dict
) -> tuple[str, str]:
    """Which failure this is, and where §9.6's investigation goes from here.

    Ordered so that a reading which cannot mean anything is rejected before one that can: an
    `update` that never ran leaves a button table that looks exactly like a real diagnosis.
    """
    stopped = not flicker["measured"]["client_fps"]
    if stopped and not gates["modal"]:
        return (
            "the client is not running, and not because of a modal screen",
            "the client frame did not advance once while sampling and [0x00DC3C64] is null, so"
            " every field below is whatever the last live frame left behind - including the"
            " button states, which look like a diagnosis and are not one. Give the game focus"
            " and use --delay.",
        )
    if stopped:
        staged = len(basket["staged"])
        return (
            "modal: the store is open and the game is stopped by design",
            f"[0x00DC3C64] is set, so GameEngine::update is in its Sleep(5) spin and neither"
            f" the client nor the logic advances - which is why nothing repaints while the"
            f" panel is up. {staged} science(s) staged for {basket['cost']} points. Clicking"
            f" more should raise that; if it does not move, the click is not reaching"
            f" OnBttnSpell (0x008235A5).",
        )
    if not gates["ui_precondition"]:
        return (
            "update never runs",
            "[0x00DE4A70] is null, so update() returns before reading a single button - every"
            " state below is stale. Nothing about the spell store can be concluded from it.",
        )
    if not gates["enabled"]:
        return (
            "store closed",
            "update() returns at this+0x2A0 - open the spell store and run this again.",
        )

    if gates["closing"]:
        return (
            "clicks discarded by the closing latch",
            "this+0x2A2 is set, so OnBttnSpell (0x008235A5) returns at 0x008235D5 before it"
            " looks at a button - while update() goes on colouring them. Whatever colour the"
            " table below shows, no click can reach a purchase. Find what set it: the close"
            " routine at 0x008228AD is the only writer.",
        )

    tally = Counter(row["state"] for row in buttons if row["button"])
    if not tally:
        return (
            "no buttons",
            "the array at this+0x2A8 is empty: the OnInitialized handshake never resolved"
            " SpellStore/Buttons/Spell%d. Instrument 0x0082334C next.",
        )
    if set(tally) <= {0}:
        return (
            "every button _unused",
            "the buttons exist but were never given a state. Instrument 0x0082334C and the"
            " OnInitialized callback at 0x0082285B.",
        )
    if 5 in tally and gate["input_enabled"] is False:
        return (
            "states correct, clicks discarded",
            "buttons are _active and the input gate is false, so OnBttnSpell never fires."
            " The fault is 0x00822974's two inputs, both printed above.",
        )
    if 5 not in tally and tally.get(1):
        return (
            "every purchasable button _disabled",
            "0x005FED5B answered false. Split its two conjuncts next: prerequisites"
            " (0x005FED05) against cost (0x005FEC64) versus available points (vtable+4 on"
            " this+0x288, printed above).",
        )
    return (
        "store looks healthy",
        "at least one button is _active and the input gate is open - if a purchase still fails"
        " the fault is past the click, in OnBttnSpell's order.",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=3.0, help="how long to watch for flicker")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="wait this long before reading, so the game can be given focus again",
    )
    parser.add_argument("--json", type=Path, help="write the reading here for cross-run diffing")
    parser.add_argument("--game", help="install or ini tree, to name the sciences (slow)")
    args = parser.parse_args()

    pids = find_game_processes()
    if not pids:
        raise SystemExit("no game.dat running - start a match first")
    try:
        memory = ProcessMemory(pids[0])
    except PermissionError as exc:
        raise SystemExit(f"{exc}\nrun this from an elevated shell") from exc

    probe = Probe(memory)
    names = science_names(args.game)
    print(f"attached to game.dat pid {pids[0]}")
    if args.delay:
        print(f"  waiting {args.delay}s - click back into the game now")
        time.sleep(args.delay)

    client = probe.pointer(THE_GAME_CLIENT)
    logic = probe.pointer(THE_GAME_LOGIC)
    rate = probe.i32(CLIENT_RATE)
    frames = {
        "client_rate": rate,
        "client_frame": probe.u32(client + CLIENT_FRAME) if client else None,
        "logic_frame": probe.u32(logic + LOGIC_FRAME) if logic else None,
    }
    print(
        f"  client rate {frames['client_rate']}   client frame {frames['client_frame']}"
        f"   logic frame {frames['logic_frame']}"
    )

    store = probe.pointer(THE_APT_SPELL_STORE)
    if store is None:
        print("\nAptSpellStore [0x00DE8AD4] is null - the store has never been constructed.")
        print("  Its constructor sets this at 0x00823852; nothing below can be read.")
        memory.close()
        raise SystemExit(1)

    gates = read_gates(probe, store)
    precondition = gates["ui_precondition"]
    print(f"\nspell store  (instance 0x{store:08X})")
    print(f"  ui gate  [0x00DE4A70] = {'null' if not precondition else f'0x{precondition:08X}'}")
    print(f"  update gate  +0x2A0 = {gates['enabled']}   (0 -> update() returns immediately)")
    print(f"  layout       +0x2A4 = {gates['layout']} {gates['layout_name'] or ''}")
    print(
        f"  click gate   +0x2A2 = {gates['closing']}   (non-zero -> every click discarded)"
        f"   close sent +0x2A3 = {gates['close_sent']}"
    )
    print(f"  selected     +0x354 = {gates['selected']}")
    print(f"  help shown   +0x358 = {gates['help_shown']}   suppress +0x359 = {gates['suppress']}")
    source = gates["source_vtable"]
    print(f"  source vtbl [+0x288] = {'null' if not source else f'0x{source:08X}'}")

    gate = read_input_gate(probe)
    print("\ninput gate  (0x00822974)")
    print(f"  TheGameLogic+0x110 = {gate['game_logic_mode']}   (== 6 enables)")
    print(f"  TheInGameUI +0x16  = {gate['in_game_ui_flag']}   (!= 0 enables)")
    answer = {True: '"1" clicks delivered', False: '"0" CLICKS DISCARDED', None: "unreadable"}
    print(f"  -> AptSpellStore::InputEnabled = {answer[gate['input_enabled']]}")

    buttons = read_buttons(probe, store, names)
    print("\nbuttons  (this+0x2A8, stride 8)")
    print("  slot  button      science  state")
    for row in buttons:
        if not row["button"]:
            continue
        label = row["science_name"] or (row["science"] if row["science"] is not None else "-")
        state = f"{row['state']} {row['state_name'] or '?'}"
        print(f"  {row['slot']:>4}  0x{row['button']:08X}  {label!s:>7}  {state}")
    tally = Counter(row["state_name"] for row in buttons if row["button"])
    print(f"  tally: {dict(tally)}")

    basket = read_basket(probe, store, names)
    print("\nstaged  (this+0x290, committed on close - a click only lands here)")
    if basket["staged"]:
        for entry in basket["staged"]:
            print(f"  {entry['science_name'] or entry['science']}")
    else:
        print("  nothing staged")
    print(f"  points committed  +0x29C = {basket['cost']}")

    flicker = watch(probe, store, args.seconds)
    print(f"\nover {args.seconds}s: {flicker['samples']} samples")
    measured = flicker["measured"]
    print(
        f"  measured {measured['client_fps']} client fps, {measured['logic_fps']} logic fps"
        f"   ([0x00D9F60C] says {frames['client_rate']} - the debug x2 button does not move it)"
    )
    print(f"  distinct state vectors: {flicker['distinct_state_vectors']}")
    print(f"  input gate seen as: {flicker['input_enabled_seen']}")
    print(f"  click gate seen as: {flicker['closing_seen']}")
    print(f"  staged points seen as: {flicker['staged_cost_seen']}")

    headline, next_step = verdict(gates, buttons, gate, flicker, basket)
    print(f"\nverdict: {headline}")
    print(f"  {next_step}")

    memory.close()

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "pid": pids[0],
                    "frames": frames,
                    "store": f"0x{store:08X}",
                    "gates": gates,
                    "basket": basket,
                    "input_gate": gate,
                    "buttons": buttons,
                    "flicker": flicker,
                    "verdict": headline,
                },
                indent=2,
            )
        )
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
