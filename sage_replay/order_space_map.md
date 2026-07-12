# Replay order-space map - WIP (Phase 4)

Single source of truth for **what every BFME2 replay order type means and how its ids resolve
to game definitions.** Supersedes the scattered per-replay findings of the retired
`object_id_mapping_plan.md` (the narrative of how each id space was found lives in git history).

Scope note: most section A order *meanings* were validated on **vanilla BFME2 1.06**; `0x419`
was solved on the **RotWK 2.01 + Edain fixture corpus** (12 replays, 113k chunks) - the same
corpus the section B census draws on, resolved against a mounted RotWK 2.01 + Edain tree and
cross-referenced against the loaded game's CommandButton table. The id-space *offsets* are noted
per game (they differ between vanilla BFME2 and merged RotWK/Edain).

## Status legend

| mark | meaning |
|------|---------|
| ✅ | solved - resolves to a definition name **exactly** (offset 0, or the benign 1-based +1) |
| 🟡 | works, but carries a **provisional non-zero offset** flagged as a likely bug (drive to 0) |
| ❓ | meaning **unknown** - parses as an opaque block, semantics unconfirmed |
| ⬜ | **not started** - needs a labelled replay or analysis |

---

## A. Content-bearing orders (reference game definitions) - the core table

| order  | meaning | id arg | id space → definition | offset | status |
|--------|---------|--------|-----------------------|--------|--------|
| `0x417` flag=**False** | recruit unit / buy purchasable upgrade | Int arg1 | `thing_template_order(root)` index | **+1** (BFME2, offset→0) | ✅ |
| `0x417` flag=**True**  | recruit fortress hero by command-slot | Int arg1 | building CommandSet **slot index** | n/a (per-building) | ✅ mechanism; ⬜ slot→hero needs the building's CommandSet resolved |
| `0x419` | build structure from the **placement UI** (Int template, Position, Float angle) - a build issued from a placement interface, not from a selected builder unit | Int arg0 | `thing_template_order` index - id of the **finished building** | **+1** (offset→0) | ✅ 491/491 corpus orders resolve (94 templates), faction-consistent in all 12 fixtures |
| `0x41A` | build structure issued to a **selected mobile builder** (dozer/porter/tunnel-digger) (Int template, Position, Float rot) | Int arg0 | `thing_template_order` index - id of the **finished building** | **+1** (offset→0) | ✅ vanilla porter builds 25/25; RotWK/Edain corpus 15/15 - Goblin tunnel-diggers only (OrkstadtTunnelBaseBuild 8, GundabadTunnel 7), all DOZER_CONSTRUCT-only templates. (The old 0/2/3 faction gap was a `_walk` bug, fixed by the engine's `INI::loadDirectory` two-pass order - see section D / OPEN 1) |
| `0x43F` | **unpack / build at a selected plot** - creates the named template at the selected object with no placement UI (signature: a single Int, no Position). Covers settlement extern unpacks, fixed-spot castle builds AND **castle/camp/outpost claims**: a target carrying a `CastleBehavior` unpacks the base its `CastleToUnpackForFaction` row names for the issuing player's faction (narrate/stats resolve it). Ground truths: Bluvil's slaughterhouse unpack (frame 462 of `cfda93ec`, button `Command_UnpackExplicitMordorSlaughterhouse` → `MordorSlaughterHouse_Extern`), the Dunedain outpost unpack (user-watched, `0d0f32fa` @20:45, raw 7041 = `ImladrisDunedainOutpost2` → base `dunedain_outpost`), and the Gondor outpost signal fire (user-confirmed, same replay @19:13, raw 7485 = `GondorLeuchtfeuer`, `Command_UnpackExplicitGondorLeuchtfeuer`). Raw id 1087 = Generals `MSG_DO_SALVAGE` → repurposed | Int arg0 | `thing_template_order` index - the **created** template | **+1** (offset→0, same standard rule as `0x417`/`0x419`). ⚠ The earlier "+2" was an **artifact of the resolving table, not the order**: it was calibrated against the Edain-Mod `_mod`-tree overlay mount, whose registration table is shifted one low around the anchor (slaughterhouse extern at id 4412 there vs 4413 on the live-install mount) and scores badly corpus-wide under ANY constant (39%/29% button-reachable). On the faithful live-install mount (`C:\BFME2`+`C:\RotWK`, first-registration-wins big mounting) the standard id resolves **2136/2166 (98.6%)** of all fixture `0x43F` orders to `CASTLE_UNPACK_EXPLICIT_OBJECT`/`FOUNDATION_CONSTRUCT` targets vs 47% under +2. Lesson: resolve ids against the install mount; an overlay tree can carry a shifted table | ✅ (narrated + counted in stats, base naming via CastleBehavior); 🟡 the ~30 no-button std-rule stragglers (expansion pads, plot variants) |
| `0x415` | purchase / research at a building | Int arg1 (ObjId arg0 = target building, 0=selection) | `Upgrade` table (`TheUpgradeCenter`) index | **id = 0-based idx + 3** (uniform; survey-calibrated 2026-07-10) | 🟡 the +3 constant itself is a likely bug - probe reserved/base upgrades or subsystem order. ⚠ the old "+3 over a 1-based index" reading was **one high**: the Mordor FireArrows/ForgedBlades anchor pair matches as a *set* under both offsets, hiding the off-by-one until an in-game replay survey pinned WolfRiders→RhudaurSpearmen and BattleWagonHearth→OrcWarriors; the corrected offset also fixes cross-faction leaks (Mordor id 70 → MordorFireArrows, not RohanWallHub; Rohan id 250 → MerryKnappeRohans, not Pippin) and holds across both the `includes/upgrade.inc` and inline `upgrade.ini` regions |
| `0x414` | purchase spellbook power | **Int arg1** (arg0 = the issuing player's chunk *number* - validated 231/231 corpus-wide; the old "branch/side science" reading is WRONG) | `game.sciences` index | +1 | ✅ |
| `0x416` | cancel queued upgrade (Generals `MSG_CANCEL_UPGRADE`, same raw id 1046) | Int arg0 | same `Upgrade` space as `0x415` (observed ids 51-507 sit inside the 0x415 range) | 0-based idx +3 assumed (as `0x415`) | 🟡 strong (enum + id-space fit; confirm with a labelled cancel replay) |
| `0x418` | cancel queued unit (Generals `MSG_CANCEL_UNIT_CREATE`, same raw id 1048) | Int arg1 | same thing-template space as `0x417` recruits (ids overlap recruit ids; bursts = clicking queued portraits) | +1 | 🟡 strong |
| `0x410` | cast special power - **self / no target** | Int arg0 | `game.specialpowers` index | +1 | ✅ |
| `0x411` | cast special power - **at location** (Position) | Int arg0 | `game.specialpowers` index | +1 | ✅ |
| `0x412` | cast special power - **at object** (ObjId target) | Int arg0 | `game.specialpowers` index | +1 | ✅ |
| `0x456` | cast special power - **untargeted / global** | Int arg0 | `game.specialpowers` index | +1 | ✅ |
| `0x457` | toggle weapon set (bow↔sword etc.) | - (ObjId = runtime unit) | no static id space | n/a | ✅ meaning |

**Composite abilities:** one click can emit **N** special-power orders same-frame, where N = the
length of the primary `CommandButton`'s `CommandTrigger` chain (e.g. Elrond Restoration → 25 +
26 heal). De-dup / label-expand by following `CommandTrigger`, not by guessing.

### Power targeting - the cast arg layout & `Options` bitfield

Every cast carries `[powerId, **options**, …]` where `options` (the 2nd Integer) is the firing
`CommandButton`'s **Options bitfield**. Its `NEED_TARGET_*` bits decide what the power targets, and
the engine picks the order type to match (invariant validated on **every** cast in the RotWK/Edain
replay: `0x411 ⟺ bit POS`, `0x412 ⟺ any object bit`):

| order | arg layout | targets |
|-------|-----------|---------|
| `0x410` self | `[powerId, options, srcObjId, objId]` | none - cast on the caster/selection |
| `0x411` at location | `[powerId, Position, objId, options, srcObjId]` | a **ground point** (`NEED_TARGET_POS`) |
| `0x412` at object | `[powerId, targetObjId, options, objId, Position]` | a **target object** + its location |
| `0x456` global | `[powerId, options, objId]` | none - global (e.g. summon-anywhere) |

The trailing/`src` ObjectId is the **casting source** (fortress/hero). Naming the actual `0x412`
target object still needs runtime ObjectId→template tracking.

Confirmed BFME2/RotWK `CommandButtonOption` bits (order integer ↔ each button's `Options` text;
each anchored by a single-flag cast - Shelob web `1`, Sauron's Influence `4`, Drogoth `7`, most
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

### Build orders - `0x419` placement UI vs `0x41A` mobile builder

`0x419` is the **placement-UI** build (every build issued from a placement interface rather than a
selected builder); `0x41A` is the **mobile-builder** construct (issued to a selected
dozer/porter/tunnel-digger). Vanilla BFME2 building is almost entirely porter-based (`0x41A`); Edain
moved nearly everything to the placement UI (`0x419`), so in the RotWK/Edain corpus `0x419` fires
491× and `0x41A` only 15×. Both resolve their Integer through the same `thing_template_order` +1 rule
as `0x417` (offset +1 → 0, benign 1-based).

Classifying the 491 `0x419` orders by the command type of the CommandButton(s) targeting each built
template (`Command` ∈ DOZER_CONSTRUCT / FOUNDATION_CONSTRUCT / CASTLE_UNPACK /
CASTLE_UNPACK_EXPLICIT_OBJECT, `Object` = the template):

| count | button type of the template | reading |
|------:|-----------------------------|---------|
| 223 | FOUNDATION_CONSTRUCT-only | castle/settlement foundation plots |
| 155 | FOUNDATION_CONSTRUCT + DOZER_CONSTRUCT | plots also placeable by a dozer |
| 55 | DOZER_CONSTRUCT-only | all `*FreeBuild`/`*WOTR`/`*ForAI` variants - Edain's free-build system uses dozer buttons but issues from the placement UI |
| 6 | CASTLE_UNPACK_EXPLICIT_OBJECT | camp/settlement **unpack** builds (ElvenCitadel 3 - also has a dozer button; GondorFarm_Extern3 3) |
| 52 | no build button targets the template directly | wall pieces, expansion pads, Isengard scaffolding + two Angmar horde deploys - reach their template via wall-hub/castle-expansion chains, not a direct build button |

The DOZER_CONSTRUCT-only tail (all placement-UI free-build variants): RohanArmoryModFreeBuild 22,
GondorWohnhaus01FreeBuild 12, ElvenBattleTowerWOTR 8, MoriaTunnelBaseBuild_ForAI_WOTR 6,
IsengardArmoryWOTR 4, DwarvenStoneMakerWOTR 2, OrkstadtTunnelMain_ForAI 1. The unmatched-template
tail spans 16 templates (AngmarHalfCastleEndPiece 12, BruchtalCampWall 9,
AngmarFortressExpansionPadSide 6, …); **noted curiosity**: two Angmar horde deploys ride the same
placement order (GoblinArcherHorde 5, GundabadLancerHorde 2, GundabadLancerHordeFormation 1) - Edain
deploy/station mechanics on the placement path, still resolving sensibly.

**Build-button census** across the whole RotWK+Edain tree (665 distinct buildable templates):
DOZER_CONSTRUCT 395, FOUNDATION_CONSTRUCT 266, CASTLE_UNPACK_EXPLICIT_OBJECT 126, and exactly one
CASTLE_UNPACK (non-explicit) button - target EntMoot, never seen in the corpus.

---

## B. Control / camera / selection orders (no static content id)

Needed for a complete narrator, but they reference **runtime** object handles or UI, not
definitions. Census of the full 12-fixture corpus (113k chunks, 76 distinct types), 2026-07-09;
key claims re-validated independently (group-select/0x3EC 2504/2504, 0x469 value set,
0x462 handshake 12/12, 0x474 echo in the ground-truth 1v1). Generals raw-id anchors are from
EA's released source (`MessageStream.h`; see section E).

| order  | signature | meaning | status |
|--------|-----------|---------|--------|
| `0x3E9` | (Bool, ObjectId×0-38) | **select**: `True` = new selection (the common case), `False` = additive; empty list = select-none. Generals `MSG_CREATE_SELECTED_GROUP`, same raw id | ✅ meaning; ⬜ handle→template needs runtime-object tracking |
| `0x3EA` | (Bool, ObjectId×0-36) | select-all-of-type / double-click select (Generals `..._NO_SOUND`, same raw id); usually additive (`False`) right after a `0x3E9` | 🟡 |
| `0x3EB` | (Bool, ObjectId) | remove-single-object from selection (shift-deselect?) | ❓ |
| `0x3EC` | (Bool `True`) | **deselect / selection emptied** (Generals raw id 1004) - fires after an empty band-box, after **every** `0x419` (491/491), and same-frame before **every** group-select (2504/2504). Not a mode toggle | ✅ |
| `0x3ED` | (ObjectId) | remove-from-selection candidate (raw id 1005 adjacency) | ❓ |
| `0x3EE`-`0x3F7` | (ObjectId×1-38) | **CreateGroup 0-9** (Ctrl+digit; args = the group's members). Usage decays like real habits (g1 270 → g9 1) | ✅ |
| `0x3F8`-`0x401` | () | **SelectGroup 0-9** (digit press) | ✅ |
| `0x403`/`0x404`/`0x405` | () | no-arg hotkeys, strong per-player skew - select-all / cycle-hero / go-to-fortress family | ❓ |
| `0x40E` | (Int, Pos, Int, ObjId) | single occurrence in the 2026-07-11 1v1 fixture batch - rally-point-shaped signature (cf `0x413`), unexamined | ❓ |
| `0x40F` | (Int{1,2}, Int, Int=INT_MAX) | 2-state toggle on a runtime object (arg1 is ObjectId-typed-as-Int) - gate open/close candidate | ❓ |
| `0x413` | (ObjId, Pos, Bool, ObjId) | **set rally point** (Generals `MSG_SET_RALLY_POINT`, same raw id): building, point, flag, rally-target object | ✅ |
| `0x419` | (Integer, Position, Float) | **placement-UI structure build - SOLVED, moved to section A** (Integer resolves in `thing_template_order`; Generals `MSG_DOZER_CONSTRUCT` signature: thing, location, angle). Start-of-game heavy but **recurs mid-game** (castle build plots); every one followed by same-frame `0x3EC` | ✅ → A |
| `0x41B` | () | cancel build / exit placement mode (Generals `MSG_DOZER_CANCEL_CONSTRUCT`, same raw id) | 🟡 |
| `0x41C` | () | **sell** selected building (Generals `MSG_SELL`, same raw id) | 🟡 |
| `0x41D` | (ObjectId×2) | exit container (Generals `MSG_EXIT`, same raw id) | ❓ |
| `0x41E` | () | evacuate garrison (Generals `MSG_EVACUATE`, same raw id) | ❓ |
| `0x423` | (ObjectId) | **combine hordes** (Edain horde-merge). Ground truth: the labelled `combo replay.BfME2Replay` fixture (build 2×BruchtalLichtbringerHorde, toggle each to an element, then combine) emits exactly **one** `0x423 ObjectId=237` at frame 707 - the user-stated combine moment (~706) - and no other content order there; the ObjectId is a runtime handle in the just-created horde cluster (232-238). ⚠ Supersedes the earlier "periodic auto-order, not a human click" reading: the corpus "pairs 8-12 frames apart every ~4-5 min" is combining recurring through a real match (one 0x423 per merge, sometimes per participating horde), **not** an engine tick. The two `0x410` casts in the same window (ids 1111/1110) are the horde's `ToggleMountedSpecialAbilityUpdate` element toggles (Wasser/Licht), resolving correctly under the standard +1 - not the combine | ✅ meaning (ground-truthed); 🟡 arg semantics (single ObjectId = target/primary horde of the merge) |
| `0x424` | (ScreenRectangle) | band-box select; followed same-frame by `0x3E9` (units caught) or `0x3EC` (empty box) | ✅ |
| `0x425` | (ObjectId, Position) | **context/smart command on an object** (attack/enter/gather; Pos = click point) - the object-target twin of `0x42F`; shift-queues | 🟡 |
| `0x42C` | (ObjectId×2) | two-object action - enter/garrison candidate | ❓ |
| `0x42E` | (Position) | 2 occurrences in one 1v1 fixture (2026-07-11 batch) - a rare Position sibling of the `0x42F`/`0x430` ground-command family, unexamined | ❓ |
| `0x42F` | (Position) | ground smart command (move; shift-chains into waypoint queues; 32k occurrences = the most frequent order) | ✅ (upgraded from tentative) |
| `0x430` | (Position) | second ground command at ~5% of `0x42F` volume - **attack-move** candidate | 🟡 |
| `0x435` | () | no-arg on selection, mash bursts - stop / hold-position candidate (vs `0x461`) | ❓ |
| `0x436`/`0x437`/`0x439` | () / (ObjId) / (ObjId) | rare; `0x439` = repair candidate | ❓ |
| `0x43D` | () | rare but near-universal (~2-3/game) - ESC / cancel-mode candidate | ❓ |
| `0x444` | (Position) | camera jump (Generals `MSG_SET_REPLAY_CAMERA` raw id + signature) | 🟡 |
| `0x453` | (ObjectId) | **end-of-game sweep**: exactly 17 per player, every player, same frames, at decided ends; plus sporadic mid-game bursts | 🟡 pattern; ❓ meaning |
| `0x457` | - (ObjId = runtime unit) | toggle weapon set (bow↔sword etc.) | ✅ meaning |
| `0x458` | (Int, ObjId) | Int sits in the special-power id space - autocast toggle / power-cancel candidate | ❓ |
| `0x45C` | (Int) | single occurrence in the 2026-07-11 1v1 fixture batch, unexamined | ❓ |
| `0x45D` | () | rare no-arg, one player dominant | ❓ |
| `0x460` | (ObjId, Int) | building + template id, long chained runs on production buildings - production-queue / spawn-type manipulation | ❓ |
| `0x461` | () | most frequent no-arg command, interleaves move streams - **stop** candidate | 🟡 |
| `0x462` | (Int, Bool `True`) | **start-of-match handshake**: at tc≈11-15 every player emits Int = its own chunk number (12/12 files, zero exceptions); some emit Int=0 at tc=1 | ✅ pattern |
| `0x463` | (Int, Pos, Pos, Int, ObjId) | **wall-segment build**: template id (resolves in the `thing_template_order` space → WildOrkstadtExpansionSklavenlager 24, WildOrkstadtExpansionBeutehort 5, faction-consistent Misty Mountains Orkstadt wall expansions), two endpoint positions, flags (16384/32768), builder/hub object | 🟡 |
| `0x464` | (Pos, Float, Int 0-9, Bool) | position + facing angle + small index + flag - formation/facing move (right-click drag) | ❓ |
| `0x466` | (Int×3) | **resource gift to ally**: arg0 = own number (25/25), arg1 = teammate's number, arg2 = amount (212-7160) | 🟡 |
| `0x468` | (Int ∈ {1,2,3}) | **stance set** (aggressive / hold / passive) - issued between select and move orders | 🟡 |
| `0x469` | (Int, Int) | **modal-state bracket**: only `(1,0)` = enter and `(0,1)` = exit ever occur (435/435). Unconditional `(0,1)` per player at match start; survivors emit `(0,1)`+4×`0x3EC` 2-6 frames after every enemy `0x448`; **team-synchronized `(0,1)` waves at game end** (victory/defeat dialogs). NOT a group op | ✅ mechanics; ❓ UI meaning |
| `0x473`/`0x474`/`0x475` | (ObjectId) | **all-client echoes** - every client emits the SAME ObjectId within 1-2 frames (engine broadcast in each player's name). `0x474` fires only in the final minutes of decided games - in the ground-truth 1v1, twice at 98% (objs 24037/24039), *before* the loser's `0x448`: prime **fortress-destroyed / defeat-event** candidate. `0x475` = lesser major-object-destroyed echo | 🟡 |
| `0x44A` | (Int, Timestamp×2, Bool×2) | **per-client checksum heartbeat**, exactly every 100 frames (= the header's `REPLAY_CRC_INTERVAL` 100; Generals `MSG_LOGIC_CRC` at raw−3) - only humans emit any orders (AI players are completely silent), so a heartbeat going quiet marks that client's departure | ✅ |
| `0x448` | (Boolean) | voluntary **leave-game** (Generals `MSG_SELF_DESTRUCT` "quit to observer" at raw−3) - a player's final order when they exit mid-game, the recorder's own exit included; exiting from the post-game victory/defeat screen emits none (only `True` observed so far) | ✅ meaning |
| `0x1D`  | - | **end-of-recording marker** (likely Generals `MSG_CLEAR_GAME_DATA` 27 shifted +2) - issued once, at the last timecode, attributed to the player whose client wrote the file: it identifies the replay's **point of view**. The same PoV index is in the header tail (see section E) | ✅ |

Corpus-wide argument-type facts: only Integer/Float/Boolean/ObjectId/Position/ScreenRectangle/
Timestamp(9) ever occur; Timestamp rides exclusively the `0x44A` heartbeat (2 per chunk).
DrawableID(4)/TeamID(5)/ScreenPosition(7)/WideChar(10) are unattested in BFME2 replays.
Only `0x3E9`/`0x3EA` have two signatures (their ObjectId list may be empty).

### Session-end shapes → winner inference

The three signals above make match endings legible ([`winner.py`](winner.py) /
`python -m sage_replay winner <replay>`), validated on a ground-truth 1v1 (the `0x448`
issuer had indeed lost) plus the fixture corpus:

- **Concession** - an opposing human's `0x448`, recorder plays on to `0x1D`. When every
  human on all-but-one side leaves, the surviving side won (`decided`).
- **PoV quit** - the recorder's own `0x448` immediately before `0x1D` while others still
  heartbeat. The recorder conceded; everyone else's fate lies beyond the recording
  (`recorder_left`) - a replay is one client's log and can be *incomplete* this way.
- **Elimination** - no `0x448` anywhere, all heartbeats run to the end, recording closes
  from the post-game screen. The input stream never records the elimination itself, so
  the verdict is `undetermined` (but see the decided-game signature below).

Sides containing AI players can never be shown to have departed (AIs emit nothing), so
vs-AI outcomes are also `undetermined` unless the humans quit.

**Decided-game signature (2026-07-09 corpus mining - candidates for closing the elimination
gap, supersedes the old `0x3F9`/`0x3FA` candidates, which turned out to be SelectGroup1/2):**

1. `0x474` **all-client echo** (same ObjectId from every client within 1-2 frames) fires only
   in the final minutes of decided games. In the ground-truth 1v1 it fires twice at 98%
   (objects 24037/24039) ~100 frames **before** the loser's `0x448` - fortress-destroyed /
   defeat-event candidate.
2. **Team-synchronized `0x469 (0,1)` waves** (+4×`0x3EC` per player): survivors emit one 2-6
   frames after every enemy `0x448`; at decided ends the waves come team-by-team (losing team
   first - the defeat dialog, winners ~25 frames later - the victory dialog). Present even in
   the tails of both truncated (crashed) fixtures, so those games *did* reach a decision.
3. `0x453` **sweep**: exactly 17 per player, all players, same frames, at fully-decided ends.

Falsification (needs recordings): a controlled fortress-kill game should show `0x474` echoing
the dying fortress's runtime id, then the `0x469` waves; a concession-only game should show
the waves but no `0x474`.

**Header-level end facts** (see `format_coverage_plan.md` for the full header decode): the
tail's first field is the **local player index as an ASCII string** = the replay's PoV
(matches the `0x1D` attribution 10/10, and supplies the PoV for crashed replays that lack
`0x1D`); `unknown1`'s second uint32 is an **abnormal-end frame** (0xFFFFFFFF when the
recording finalized; else the last completed heartbeat frame) - so crashes are detectable
from the header alone.

---

## C. Order types seen in Edain replays, not yet mapped in BFME2

| order  | hypothesis | status |
|--------|------------|--------|
| `0x416` | ~~building/unit upgrade action~~ **resolved: cancel queued upgrade** - moved to section A | ✅ |
| `0x43F` | ~~building action - economy/spawner id, base-setup skew~~ **resolved: unpack / build at a selected plot** (the "economy buildings" were the unpackable settlement externs; the early-game skew was base setup) - moved to section A | ✅ |

---

## D. Id-space **generation** side (derive the whole table from sage_ini, no replay per id)

| space | rule | BFME2 | RotWK/Edain (merged) | status |
|-------|------|-------|----------------------|--------|
| objects (`0x417` recruit / `0x419`/`0x41A` build / `0x463` wall; `0x43F` plot unpack rides the same table at **+2** - section A) | `thing_template_order` idx +1 | ✅ offset 0, 36/36 ([`subsystems.py`](../sage_ini/subsystems.py)) | ✅ validated on a **mounted RotWK+Edain install** - recruits & builds resolve to faction-consistent units/structures for both players (Misty Mountains + Mordor), 200+ orders; `0x419` adds 491/491 across all 12 fixtures (section A); the tail (CPObject, system objects) also orders sensibly | ✅ |
| sciences (`0x414`) | `game.sciences` idx +1 | ⬜ not regenerated for vanilla | ✅ (merged) - every spellbook purchase resolves to a faction-appropriate power (Eye of Sauron, Awaken Kankra, DragonsOfYore…) | ✅ |
| special powers (`0x410-412`/`0x456`) | `game.specialpowers` idx +1 | ✅ 16/16 (Replay 6) | ✅ (merged) - casts resolve to the caster's faction abilities | ✅ |
| upgrades (`0x415`/`0x416`) | `Upgrade` table **0-based** idx +3 (`DefaultUpgrade` = id 3) | 🟡 not re-checked on vanilla since the correction | ✅ **survey-calibrated 2026-07-10** - an in-game replay survey pinned the offset one lower than the old "confirmed" reading (the ForgedBlades/FireArrows anchor pair matches as a set under both, masking the off-by-one); the corrected offset resolves faction-consistently corpus-wide (section A `0x415` row) | ✅ (constant +3 still unexplained - OPEN 4) |

The merged tree is built by mounting the install's `.big` archives (first-wins alphabetical
override: `__edain_data` > `_patch201ini` > `ini.big`) into one `data/ini` tree with
[`tools/mount_game.py`](../tools/mount_game.py); [`narrate.py`](narrate.py) then retells the
match (`python -m sage_replay narrate <replay> --game <install>`).

---

## E. Generals GameMessage lineage (EA source, 2026-07-09)

EA's released Generals/ZH source (github.com/electronicarts/CnC_Generals_Zero_Hour, GPLv3 -
format documentation only, per the OpenSAGE policy) pins the enum BFME2's order ids descend
from: `GameMessage::Type` in `GameEngine/Include/Common/MessageStream.h`, deliberately
ifdef-free between `MSG_BEGIN_NETWORK_MESSAGES = 1000` and `MSG_END_NETWORK_MESSAGES` so
replay values stay stable across builds. The full value list and the per-id BFME2 comparison
live in the session findings (`findings_ea_source.md`); the shift picture:

- **identical raw ids through ~1049** (selection block 1001-1035, content block 1040-1049:
  powers, sciences, upgrades, unit-queue, dozer-construct - all the section A/B "same raw id"
  anchors);
- **+2 by 1058** (band-box: BFME2 `0x424` = Generals `MSG_AREA_SELECTION` 1058);
- **+3 from ~1068** (move `0x42F`↔`MSG_DO_MOVETO` 1068, leave `0x448`↔`MSG_SELF_DESTRUCT`
  1093, heartbeat `0x44A`↔`MSG_LOGIC_CRC` 1095);
- everything ≥ `0x453` except the shifted tail is **BFME2's own appended block** (Generals
  ends at 1096/1097).

Two decisive extractions besides the ids: the argument-type enum names our unknowns
(4=DrawableID, 5=TeamID, 9=Timestamp, **10=WideChar - 2 bytes on disk, not 4**; Boolean is
1 byte), and `GameMessage::getCommandTypeAsAsciiString` stringifies every enumerator and is
**not debug-gated** - so every `MSG_*` name should exist as a string literal in BFME2's
`game.dat`, making a Ghidra pass the one-shot naming source for all ~76 BFME2 order ids.

Also from the same source: the Generals replay header is now fully named (frameDuration,
desync flag, per-player disconnect bools, exeCRC+iniCRC, ASCII localPlayerIndex, difficulty /
originalGameMode / rankPoints / maxFPS), the `M=` digit prefix is the **map-contents bitmask
in hex** (BFME2's constant `387` = mask 0x387), the metadata `C=` key is the CRC interval
(`REPLAY_CRC_INTERVAL` 100 - the heartbeat cadence AND the constant 100 opening BFME2's
17-byte header block), and the slot string's `TT` = `<accepted><hasMap>` flags with the
field after team named `NATBehavior`.

## OPEN - what still needs filling in (ranked)

1. **✅ DONE - engine's true INI directory order implemented → `0x41A` gap eliminated,
   then re-validated on the merged RotWK/Edain tree.** The `0x41A` faction gap (0/2/3) was NOT
   scaffold states - it was a `_walk` bug: the engine's `INI::loadDirectory` loads top-level files
   first, then **all subdirectory files as one flat path-sorted list** (not recursive
   files-before-subdirs). [subsystems.py](../sage_ini/subsystems.py) `_walk` now does the two-pass;
   validated 36/36 units + 25/25 builds at offset 0 on real BFME2 (`test_thing_ids.py`
   `BUILD_ANCHORS`) **and** on a mounted RotWK+Edain install (recruits/builds resolve
   faction-consistently for both players). The old **CPObject tail worry is retired**: CPObject is
   a real `ChildObject` in `object/system/system.ini` that now lands at a stable tail id (11073)
   among the other system objects. Source: EA CnC Generals `INI.cpp` (OpenSAGE mirrors it).
2. **✅ DONE - English narrator built.** [`narrate.py`](narrate.py) + `python -m sage_replay narrate
   <replay> --game <install>` resolve recruit / build / power / spellbook / upgrade ids and retell a
   match. It narrates both build orders - `0x419` placement-UI and `0x41A` mobile-builder (verb
   "unpacks" for CASTLE_UNPACK* templates, else "builds", with the placement position) - and `0x463`
   wall segments; [`tools/mount_game.py`](../tools/mount_game.py) mounts a live install's `.big`
   archives (first-wins alphabetical override) into the `data/ini` tree the loaders need.
3. **🟡 Builds - close the remaining gaps.** `0x419` placement-UI build and `0x41A` mobile-builder
   are solved (section A). Still open: confirm `0x41B` cancel-construct and `0x41C` sell with one
   labelled recording; exercise a plain **CASTLE_UNPACK** (only such button in the tree targets
   EntMoot, unseen in the corpus); and account for the unmatched-`0x419` template tail (wall/expansion
   chains) and the two Angmar horde deploys riding the placement order.
4. **⬜ `0x415` +3 → 0.** Survey-corrected 2026-07-10: id = **0-based** table idx + 3 (`DefaultUpgrade`
   = id 3), uniform across the `includes/upgrade.inc` and inline `upgrade.ini` regions - the old
   "+3 over 1-based" reading was one high (section A row). The +3 constant still wants a real
   explanation: 3 reserved leading ids, entries the engine registers before `DefaultUpgrade`, or a
   subsystem miscount. ⚠ method lesson: an anchor pair that is *adjacent in the table* (FireArrows/
   ForgedBlades) validates the id space but NOT the offset - it matches as a set under ±1; calibrate
   offsets on a surveyed single action or a non-adjacent pair.
5. **⬜ Rewire [`replay_idmap.py`](../tools/replay_idmap.py)** to source objects from the mounted
   `thing_template_order` (now validated on RotWK/Edain) and drop the old `game.objects` +1201 column.
6. **✅ DONE (2026-07-11) - `0x43F` = unpack / build at a selected plot; offset driven to 0
   (2026-07-11, later the same day).** First read as a `thing_template_order` id at **+2** from the
   slaughterhouse ground truth; two further user-confirmed anchors (the `0d0f32fa` Dunedain outpost
   unpack @20:45 and Gondor signal-fire outpost claim @19:13) resolved only at the standard +1,
   which exposed the +2 as a **table artifact**: the Edain-Mod `_mod`-overlay mount's registration
   table is shifted one low near the slaughterhouse anchor and misordered further out (39%/29%
   corpus button-reachability under +2/+1), while the live-install mount resolves 2136/2166
   (98.6%) of all fixture `0x43F` orders under the standard id. The standing offset directive
   vindicated again: the constant was a bug in *our* table, not an engine feature. Castle/camp/
   outpost claims are `0x43F` (or `0x419`) orders whose target template carries a `CastleBehavior`;
   `GameData.castle_bases` + the player's faction `Side` name the unpacked base
   (`CastleToUnpackForFaction`). Residual: the ~30 no-button std-rule stragglers, the Rohan/Wild
   button chains, and **why the overlay tree's table drifts** (find the missing/extra registration
   - it also silently shifts any id resolved against that mount). `0x416` is resolved (cancel
   upgrade, section A).
7. **⬜ Cross-faction / cross-version validation** of the special-power +1 (the lone odd resolution
   so far is `AragornBladeMaster` for a Mordor caster - check if a real shared/neutral ability).
8. **⬜ Runtime ObjectId → template** (`0x3E9`, `0x457` targets, `0x412` object targets): track
   object creation through the stream to name selections/targets - needed to narrate *who/what* a
   power targets, not just the power. (`0x42F`/`0x469`/`0x462`/`0x3EC` are now characterized -
   section B.)
9. **🟡 Elimination signature - candidates found (2026-07-09), needs falsification.** The
   decided-game signature (section B footnote): `0x474` all-client echo (fortress-destroyed
   candidate) → loser's `0x448` → team-synchronized `0x469 (0,1)` dialog waves + `0x453` sweep.
   The old `0x3F9`/`0x3FA` candidates are retired (they are SelectGroup1/2). Needs one
   controlled fortress-kill recording (echoed ObjectId should be the dying fortress) and one
   concession-only recording (waves without `0x474`); then teach [`winner.py`](winner.py) the
   signature so fought-to-the-end games stop returning `undetermined`.
10. **⬜ Ghidra one-shot order naming.** `GameMessage::getCommandTypeAsAsciiString` is not
    debug-gated, so BFME2's `game.dat` should carry every `MSG_*` name as a string literal
    (section E) - recover the name table and replace every 🟡/❓ in section B with the
    engine's own name. The Ghidra workflow built for the `.sav` reverse-engineering
    (string search + call-site adjacency) transfers directly.
