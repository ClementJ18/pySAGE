# Replay order-space map — WIP (Phase 4)

Single source of truth for **what every BFME2 replay order type means and how its ids resolve
to game definitions.** Supersedes the scattered per-replay findings in
[`object_id_mapping_plan.md`](object_id_mapping_plan.md) for *status* (that file keeps the
narrative of how each was found).

Scope note: the order *meanings* below are validated on **vanilla BFME2 1.06**; the id-space
*offsets* are noted per game (they differ between vanilla BFME2 and merged RotWK/Edain).

## Status legend

| mark | meaning |
|------|---------|
| ✅ | solved — resolves to a definition name **exactly** (offset 0, or the benign 1-based +1) |
| 🟡 | works, but carries a **provisional non-zero offset** flagged as a likely bug (drive to 0) |
| ❓ | meaning **unknown** — parses as an opaque block, semantics unconfirmed |
| ⬜ | **not started** — needs a labelled replay or analysis |

---

## A. Content-bearing orders (reference game definitions) — the core table

| order  | meaning | id arg | id space → definition | offset | status |
|--------|---------|--------|-----------------------|--------|--------|
| `0x417` flag=**False** | recruit unit / buy purchasable upgrade | Int arg1 | `thing_template_order(root)` index | **+1** (BFME2, offset→0) | ✅ |
| `0x417` flag=**True**  | recruit fortress hero by command-slot | Int arg1 | building CommandSet **slot index** | n/a (per-building) | ✅ mechanism; ⬜ slot→hero needs the building's CommandSet resolved |
| `0x41A` | build structure (Int template, Position, Float rot) | Int arg0 | `thing_template_order` index — id of the **finished building** | **+1** (offset→0) | ✅ the old 0/2/3 faction gap was a `_walk` bug; fixed by the engine's `INI::loadDirectory` two-pass order (36/36 units + 25/25 builds) |
| `0x415` | purchase / research at a building | Int arg1 (ObjId arg0 = target building, 0=selection) | `Upgrade` table (`TheUpgradeCenter`) index | **+3** | 🟡 offset is a likely bug — probe reserved/base upgrades or subsystem order |
| `0x414` | purchase spellbook power | **Int arg1** (arg0 = the branch/side science, varies by faction — 3/4 in the Edain replay) | `game.sciences` index | +1 | ✅ |
| `0x410` | cast special power — **self / no target** | Int arg0 | `game.specialpowers` index | +1 | ✅ |
| `0x411` | cast special power — **at location** (Position) | Int arg0 | `game.specialpowers` index | +1 | ✅ |
| `0x412` | cast special power — **at object** (ObjId target) | Int arg0 | `game.specialpowers` index | +1 | ✅ |
| `0x456` | cast special power — **untargeted / global** | Int arg0 | `game.specialpowers` index | +1 | ✅ |
| `0x457` | toggle weapon set (bow↔sword etc.) | — (ObjId = runtime unit) | no static id space | n/a | ✅ meaning |

**Composite abilities:** one click can emit **N** special-power orders same-frame, where N = the
length of the primary `CommandButton`'s `CommandTrigger` chain (e.g. Elrond Restoration → 25 +
26 heal). De-dup / label-expand by following `CommandTrigger`, not by guessing.

### Power targeting — the cast arg layout & `Options` bitfield

Every cast carries `[powerId, **options**, …]` where `options` (the 2nd Integer) is the firing
`CommandButton`'s **Options bitfield**. Its `NEED_TARGET_*` bits decide what the power targets, and
the engine picks the order type to match (invariant validated on **every** cast in the RotWK/Edain
replay: `0x411 ⟺ bit POS`, `0x412 ⟺ any object bit`):

| order | arg layout | targets |
|-------|-----------|---------|
| `0x410` self | `[powerId, options, srcObjId, objId]` | none — cast on the caster/selection |
| `0x411` at location | `[powerId, Position, objId, options, srcObjId]` | a **ground point** (`NEED_TARGET_POS`) |
| `0x412` at object | `[powerId, targetObjId, options, objId, Position]` | a **target object** + its location |
| `0x456` global | `[powerId, options, objId]` | none — global (e.g. summon-anywhere) |

The trailing/`src` ObjectId is the **casting source** (fortress/hero). Naming the actual `0x412`
target object still needs runtime ObjectId→template tracking.

Confirmed BFME2/RotWK `CommandButtonOption` bits (order integer ↔ each button's `Options` text;
each anchored by a single-flag cast — Shelob web `1`, Sauron's Influence `4`, Drogoth `7`, most
spellbooks `32`, `544`=pos+contextmode, `16777216`=toggle-weaponset):

| bit | value | flag | | bit | value | flag |
|----:|------:|------|-|----:|------:|------|
| 0 | 1 | NEED_TARGET_ENEMY_OBJECT | | 8 | 256 | OK_FOR_MULTI_SELECT |
| 1 | 2 | NEED_TARGET_NEUTRAL_OBJECT | | 9 | 512 | CONTEXTMODE_COMMAND |
| 2 | 4 | NEED_TARGET_ALLY_OBJECT | | 20 | 1048576 | OK_FOR_MULTI_EXECUTE |
| 5 | 32 | NEED_TARGET_POS | | 24 | 16777216 | TOGGLE_IMAGE_ON_WEAPONSET |
| 6 | 64 | NEED_UPGRADE | | 27 | 134217728 | UNMOUNTED_ONLY |
| | | | | 30 | 1073741824 | ON_GROUND_ONLY |

Allegiance from the object bits: enemy(1)/neutral(2) → an enemy target; ally(4) → a friendly target
(Edain mind-control abilities like Sauron's Influence are `NEED_TARGET_ALLY_OBJECT`); all three (7) →
any unit. `narrate.py::_target_phrase` renders this. (These match the OpenSAGE Generals reverse-eng
notes in `…/Logic/Orders/SpecialPowerArguments.md` where they overlap; BFME extends the high bits.)

---

## B. Control / camera / selection orders (no static content id)

Needed for a complete narrator, but they reference **runtime** object handles or UI, not
definitions. Lower priority than section A.

| order  | signature | meaning | status |
|--------|-----------|---------|--------|
| `0x3E9` | (Bool, ObjectId) | select single on-map object (runtime handle) | ✅ meaning; ⬜ handle→template needs runtime-object tracking |
| `0x424` | (ScreenRectangle) | band-box select | ✅ meaning (no id) |
| `0x42F` | (Position) | move-to / rally to ground | 🟡 tentative — confirm move vs rally |
| `0x469` | (Integer, Integer) | ❓ selection-group op? (pairs like (1,0)/(0,1)) | ❓ |
| `0x462` | (Integer, Boolean) | ❓ | ❓ |
| `0x3EC` | (Boolean) | ❓ toggle/confirm (recurs before actions) | ❓ |
| `0x419` | (Integer, Position, Float) | start-of-game unit placement | ✅ known (noise for id-mapping) |
| `0x44A` | (hash-like) | **per-client checksum heartbeat**, every ~100 frames — only humans emit any orders (AI players are completely silent), so a heartbeat going quiet marks that client's departure | ✅ |
| `0x448` | (Boolean) | voluntary **leave-game** — a player's final order when they exit mid-game, the recorder's own exit included; exiting from the post-game victory/defeat screen emits none (only `True` observed so far) | ✅ meaning |
| `0x1D`  | — | **end-of-recording marker** — issued once, at the last timecode, attributed to the player whose client wrote the file: it identifies the replay's **point of view** | ✅ |

### Session-end shapes → winner inference

The three signals above make match endings legible ([`winner.py`](winner.py) /
`python -m sage_replay winner <replay>`), validated on a ground-truth 1v1 (the `0x448`
issuer had indeed lost) plus the fixture corpus:

- **Concession** — an opposing human's `0x448`, recorder plays on to `0x1D`. When every
  human on all-but-one side leaves, the surviving side won (`decided`).
- **PoV quit** — the recorder's own `0x448` immediately before `0x1D` while others still
  heartbeat. The recorder conceded; everyone else's fate lies beyond the recording
  (`recorder_left`) — a replay is one client's log and can be *incomplete* this way.
- **Elimination** — no `0x448` anywhere, all heartbeats run to the end, recording closes
  from the post-game screen. The input stream never records the elimination itself, so
  the verdict is `undetermined` (see OPEN item on the elimination signature).

Sides containing AI players can never be shown to have departed (AIs emit nothing), so
vs-AI outcomes are also `undetermined` unless the humans quit.

---

## C. Order types seen in Edain replays, not yet mapped in BFME2

From the Edain corpus (`object_id_mapping_plan.md`); need a labelled BFME2 replay to confirm.

| order  | hypothesis | status |
|--------|------------|--------|
| `0x416` | building/unit upgrade action | ⬜ |
| `0x43F` | building action — its **Integer is an object-space id** (resolves to economy/spawner buildings: Goblin lair, Mordor slaughterhouse/slave-farm in the Edain replay), not an upgrade; exact semantics (rally? auto-produce?) still open | 🟡 seen in RotWK/Edain too |

---

## D. Id-space **generation** side (derive the whole table from sage_ini, no replay per id)

| space | rule | BFME2 | RotWK/Edain (merged) | status |
|-------|------|-------|----------------------|--------|
| objects (`0x417` recruit / `0x41A` build) | `thing_template_order` idx +1 | ✅ offset 0, 36/36 ([`subsystems.py`](../sage_ini/subsystems.py)) | ✅ validated on a **mounted RotWK+Edain install** — recruits & builds resolve to faction-consistent units/structures for both players (Misty Mountains + Mordor), 200+ orders; the tail (CPObject, system objects) also orders sensibly | ✅ |
| sciences (`0x414`) | `game.sciences` idx +1 | ⬜ not regenerated for vanilla | ✅ (merged) — every spellbook purchase resolves to a faction-appropriate power (Eye of Sauron, Awaken Kankra, DragonsOfYore…) | ✅ |
| special powers (`0x410-412`/`0x456`) | `game.specialpowers` idx +1 | ✅ 16/16 (Replay 6) | ✅ (merged) — casts resolve to the caster's faction abilities | ✅ |
| upgrades (`0x415`) | `Upgrade` table idx +3 | 🟡 +3 provisional | ✅ +3 **confirmed** — id−3 lands exactly on `Upgrade_MordorForgedBlades` / `Upgrade_MordorFireArrows` for the Mordor player | ✅ +3 (benign) |

The merged tree is built by mounting the install's `.big` archives (first-wins alphabetical
override: `__edain_data` > `_patch201ini` > `ini.big`) into one `data/ini` tree with
[`tools/mount_game.py`](../tools/mount_game.py); [`narrate.py`](narrate.py) then retells the
match (`python -m sage_replay narrate <replay> --game <install>`).

---

## OPEN — what still needs filling in (ranked)

1. **✅ DONE — engine's true INI directory order implemented → `0x41A` gap eliminated,
   then re-validated on the merged RotWK/Edain tree.** The `0x41A` faction gap (0/2/3) was NOT
   scaffold states — it was a `_walk` bug: the engine's `INI::loadDirectory` loads top-level files
   first, then **all subdirectory files as one flat path-sorted list** (not recursive
   files-before-subdirs). [subsystems.py](../sage_ini/subsystems.py) `_walk` now does the two-pass;
   validated 36/36 units + 25/25 builds at offset 0 on real BFME2 (`test_thing_ids.py`
   `BUILD_ANCHORS`) **and** on a mounted RotWK+Edain install (recruits/builds resolve
   faction-consistently for both players). The old **CPObject tail worry is retired**: CPObject is
   a real `ChildObject` in `object/system/system.ini` that now lands at a stable tail id (11073)
   among the other system objects. Source: EA CnC Generals `INI.cpp` (OpenSAGE mirrors it).
2. **✅ DONE — English narrator built.** [`narrate.py`](narrate.py) + `python -m sage_replay narrate
   <replay> --game <install>` resolve recruit / build / power / spellbook / upgrade ids and retell a
   match; [`tools/mount_game.py`](../tools/mount_game.py) mounts a live install's `.big` archives
   (first-wins alphabetical override) into the `data/ini` tree the loaders need.
4. **⬜ `0x415` +3 → 0.** The +3 is confirmed benign on Edain (id−3 hits the right upgrade), but
   drive it to a real explanation: does the `Upgrade` table have 3 reserved/base entries the engine
   registers first (`DefaultUpgrade` + the two `Upgrade_TestBuilding`), or is it a subsystem miscount?
5. **⬜ Rewire [`replay_idmap.py`](../tools/replay_idmap.py)** to source objects from the mounted
   `thing_template_order` (now validated on RotWK/Edain) and drop the old `game.objects` +1201 column.
6. **⬜ Semantics of `0x43F`** — its Integer is an object-space id (economy/spawner buildings);
   confirm what the action *does* (rally? auto-produce? unit-upgrade-in-place). Same for `0x416`.
7. **⬜ Cross-faction / cross-version validation** of the special-power +1 (the lone odd resolution
   so far is `AragornBladeMaster` for a Mordor caster — check if a real shared/neutral ability).
8. **⬜ Runtime ObjectId → template** (`0x3E9`, `0x457` targets, `0x412` object targets): track
   object creation through the stream to name selections/targets — needed to narrate *who/what* a
   power targets, not just the power. Then confirm the control orders `0x42F`/`0x469`/`0x462`/`0x3EC`.
9. **⬜ Elimination signature.** A game that ends by fortress-kill leaves no `0x448` — the
   recording just closes from the post-game screen, so `winner` returns `undetermined` for
   fought-to-the-end games. Needs one controlled game ending in a destroyed fortress to diff the
   tail; candidates: the rare late orders `0x3F9`/`0x3FA`/`0x468`/`0x469` seen near a known
   game end, or a behaviour change in the defeated client's heartbeat.
