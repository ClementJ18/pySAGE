# What RotWK lost from BFME1's script actions, and the blueprint for putting it back

BFME1 `C:\BFME1\lotrbfme.exe` against RotWK `game.dat` build `2.01.2614.37001`, both ImageBase
`0x400000`. Recovered statically on 2026-08-12. Companion to
[`dead-script-actions.md`](dead-script-actions.md), which establishes the RotWK side.

**Nothing here has been run.** Static analysis only.

## Why the two binaries can be compared at all

Both games use the same two-stage dispatch and the same action enum:

| | BFME1 | RotWK |
|---|---|---|
| `ScriptActions::executeAction` | `0x00703BF0` | `0x007CAFA5` |
| case bound | `cmp edx, 0x21E` → **543** actions | `cmp eax, 0x257` → **600** actions |
| jump table | `0x0070D6A0` | `0x007CF857` |
| shared epilogue (a stub target) | `0x0070D68B` | `0x007CF846` |
| stub entries | 55 | 66 |
| template table stride / base | `0x7C` / `+0x24` | `0x80` / `+0x2C` |

The low enum is identical in both — `VICTORY` 3, `DEFEAT` 4, `NO_OP` 5, `SET_TIMER` 6,
`PLAY_SOUND_EFFECT` 7 — but RotWK **inserted** actions partway through, so ids diverge higher up
(`UNIT_ASSIMILATE_WITH_ARMY_BY_NAME` is 541 in BFME1, 542 in RotWK). Every comparison below is
therefore **by name**, never by id.

One BFME1 quirk: it was built with incremental linking, so most `call` targets land in a thunk table
of `jmp` instructions around `0x0041E800`. Resolve one hop to reach the real function.

## The result: eight actions regressed, none improved

Live in BFME1, **stub** in RotWK:

| action | BFME1 impl | bears on |
|---|---|---|
| `UNIT_ASSIMILATE_WITH_ARMY_BY_NAME` | `0x006F7820` | hero handoff |
| `TEAM_ASSIMILATE_WITH_ARMY_BY_NAME` | `0x006F7820` | hero handoff |
| `PLAYER_ASSIMILATE_WITH_ARMY_BY_NAME` | `0x006F7820` | hero handoff |
| `REMOVE_REINFORCEMENT_ARMY` | `0x006F1290` | reinforcements |
| `REINFORCEMENTS_DISPLAY_BANNER` | `0x006ED8C0` | reinforcements |
| `DRAW_SKYBOX_BEGIN` | — | visuals |
| `DRAW_SKYBOX_END` | — | visuals |
| `PALANTIR_EVENT` | — | UI |

**Nothing went the other way** — there is no action stubbed in BFME1 that RotWK implements. RotWK
also *added* 52 actions BFME1 never had, including the whole carryover/revival family
(`CREATE_UNIT_REVIVAL_ENTRY*`, `CREATE_DELAYED_CARRYOVER_UNIT_AT_WAYPOINT`) and the `ATTACK_MOVE_*`
group, all of which are live.

So the picture is not "RotWK is a cut-down BFME1". It is: RotWK added a lot, and dropped exactly
eight things — but five of those eight are precisely the ones you need.

`DRAW_SKYBOX_BEGIN` is worth flagging separately: it is called **227 times** across the Edain map
corpus and does nothing in RotWK, while it worked in BFME1.

## What never worked in either game

This is the expectation-correcting half, and it matters more than the regression list.

| action | BFME1 | RotWK |
|---|---|---|
| `LIVING_WORLD_MOVE_ARMY_TO_POSITION` | **gutted** | **gutted** |
| `LIVING_WORLD_MOVE_ARMY_TO_ZONE` | **stub** | **stub** |
| `LIVING_WORLD_SPAWN_ARMY_AT_POSITION` | **gutted** | **gutted** |
| `LIVING_WORLD_SPAWN_ARMY_IN_ZONE` | **stub** | **stub** |
| `LIVING_WORLD_DESPAWN_ARMY` | **stub** | **stub** |

"Gutted" means the body survives, reads its parameters and drops them. BFME1's
`LIVING_WORLD_MOVE_ARMY_TO_POSITION` at `0x0070B452`:

```asm
0070b452  cmp  dword ptr [esi + 8], 2     ; paramCount > 2 ?
0070b458  ecx = action->params[2]
0070b45f  push &local ; call 0x0074FEE0   ; Parameter::getCoord3D(&local)
0070b477  ret  4                          ; ...and that is the whole function
```

RotWK's version at `0x007CE72F` is the same shape calling `0x007B32DE`. Two different games, two
different builds, the same action reading a coordinate into a stack slot and returning.

**So spawning, moving or despawning a living-world army from a mission script has never worked in
any shipped SAGE build.** The WorldBuilder entries are vestigial in both. If the BFME1 campaign
achieved those effects, it did not do so through these actions — it did so through the campaign
INI's Act verbs (`SpawnArmy`, `MoveArmy`, `MergePlayerArmy`, `DespawnArmy`), which is a different
system entirely and the subject of [`living-world-parity.md`](living-world-parity.md) §6.

That distinction is the single most useful thing in this document: **the strategic layer is driven
from campaign INI acts, not from mission scripts.** Mission scripts only ever reached across the
boundary for unit-level things — assimilate and reinforcements — and those are exactly the eight
that regressed.

## The blueprint: BFME1's assimilate-by-name

All three variants share one body, because BFME1 passes the action type through:

```asm
0070d61f  ecx = paramCount > 1 ? action->params[1] : 0
0070d632  esi = action->params[0]
0070d635  push edx        ; <-- edx still holds the action type from the dispatcher
0070d636  push ecx ; push esi
0070d63a  call 0x0041E80D -> 0x006F7820
```

And the implementation:

```asm
006f7820  assimilateByName(param0, param1, actionType)        ; ret 0xC
  eax = param1 + 0x10                  ; the ARMY name AsciiString
  ecx = [0x012F0898]                   ; the army manager (a global in BFME1)
  call 0x00783880                      ; findArmyByName(name) -> esi
  if (!esi) return

  ecx        = esi->[0x20]             ; save
  esi->[0x20] = 4                      ; <-- a mode flag, set for the duration
  switch (actionType - 0x21B) {        ; 0x21B = 539 = PLAYER_...
    case 0: ...                        ; player
    case 1: ...                        ; team  (0x006F78AA)
    case 2:                            ; unit
      ecx = [0x012F076C]               ; TheScriptEngine
      call [vt+0x68](param0)           ; findObjectByName -> the unit
      if (!unit) break
      ecx = [0x012F0898]
      push unit ; push esi->[4]        ; the army's handle
      call 0x00783930                  ; assimilate(unit, handle)
  }
  esi->[0x20] = saved                  ; restore
```

Three things to take from this:

1. **Parameter order is (object, army name)**, and it is *identical in both games*. Both templates
   declare types `0xE` then `0xA` with the UI text `Set ⟨…⟩ to be assimilated by army ⟨…⟩. `, and
   BFME1's implementation reads `params[1]` as the army. Type `0xA` is an army name — confirmed by
   `REMOVE_REINFORCEMENT_ARMY`, whose single parameter is `0xA` — and `0xE` is a unit/object name.
   A RotWK cave can therefore take the parameter order straight from the surviving template.
2. **The army is resolved by name, then a handle field is taken off it** and that handle — not the
   army pointer — is what `assimilate` consumes. RotWK's live path does the same thing with
   different offsets (`army->[0x78]->[0x1C]`; see
   [`dead-script-actions.md`](dead-script-actions.md)). The shape ports; the offsets do not.
3. **`army->[0x20] = 4` for the duration of the call, restored afterwards.** A mode flag whose
   meaning is unknown. A naive RotWK revival that skips it would be subtly wrong in a way that
   would be very hard to diagnose, and finding RotWK's equivalent field is a prerequisite, not a
   detail.

The templates line up field for field, which is worth stating because it is what makes a port
cheap — RotWK kept the entire WorldBuilder-facing half of these three actions and dropped only the
body:

| field | RotWK id 542 | BFME1 id 541 |
|---|---|---|
| internal name | `UNIT_ASSIMILATE_WITH_ARMY_BY_NAME` | same |
| UI description | `Unit_/Assimilates unit with an army by name.` | same |
| param types (`T+0x6C`, `T+0x70`) | `0xE`, `0xA` | `0xE`, `0xA` |
| UI fragments | `Set ` / ` to be assimilated by army ` / `. ` | same |

The two reinforcement regressions are trivial by comparison — both are one-line delegations:

```
REMOVE_REINFORCEMENT_ARMY    -> ScriptActions::removeReinforcementArmy(param0.name)   0x006F1290
REINFORCEMENTS_DISPLAY_BANNER-> ScriptActions::displayReinforcementBanner()           0x006ED8C0
```

Whether RotWK retains equivalent methods is unchecked.

## What this means for reimplementing the BFME1 campaign

Reordered by what the evidence now supports:

1. **Do not plan to drive the strategic map from mission scripts.** That never worked. The BFME1
   campaign moved armies through campaign INI acts, and RotWK's act system is *richer* than BFME1's
   (18 `SpawnArmy` fields to 9). The parity gap there is `MergePlayerArmy` / `DespawnArmy` at the
   **INI** level — [`living-world-parity.md`](living-world-parity.md) §6.
2. **The hero handoff is the one genuine, well-understood regression.** Three actions, one shared
   BFME1 implementation, and RotWK still has every building block. This is the most tractable patch
   in the whole investigation and it fixes a complaint that currently costs manual work in every
   mission.
3. **Carryover is a RotWK invention, not a BFME1 feature.** BFME1 has no `CARRYOVER` or
   `REVIVAL_ENTRY` actions at all. So "make heroes persist like BFME1 did" is the wrong frame —
   BFME1 did not do it either. RotWK's machinery is live and strictly ahead; the open question is
   whether the living-world battle-exit path feeds it
   ([`living-world-parity.md`](living-world-parity.md) §3).
4. **`DRAW_SKYBOX_BEGIN`/`END` are free wins if anyone cares about the visuals** — 227 call sites
   already exist in the map corpus, written by authors who presumably expected them to work.

## Unknowns

| | question | how to settle |
|---|---|---|
| 1 | Does RotWK have an equivalent of BFME1's `army->[0x20]` mode flag? | compare the RotWK army struct around the live `assimilate` path |
| 2 | Is `army->[0x78]` populated for an army not participating in the current battle? | live read via `live-bridge` in a running battle |
| ~~3~~ | ~~What parameter order does RotWK's template declare?~~ | **settled** — `(object, army)`, types `0xE`/`0xA`, identical to BFME1 |
| 4 | Do RotWK equivalents of `0x006F1290` / `0x006ED8C0` survive? | search RotWK for the reinforcement-army list methods |

**Question 2 is the one that decides whether the patch is worth writing.** If the battle-side record
only exists for armies the battle instantiated, then resolving an arbitrary campaign army by name
yields nothing and the action cannot work — which would also be a plausible reason the by-name
variants were dropped rather than carried forward.

Question 1 is the one most likely to produce a subtly broken patch if skipped.

## Method

Both binaries: locate the indexed `jmp` dispatcher by scanning `.text` for `FF 24 85` with a table
of ≥250 plausible code pointers; read the case bound from the preceding `cmp`; take the `ja` target
as the stub/epilogue address. Names come from each binary's template-registration constructor,
harvested by matching `push <str> ; lea ecx, [esi+disp32] ; call <AsciiString assign>` and bucketing
by `disp32 % stride`. Comparison is by name. Classification of "gutted" follows the method in
[`dead-script-actions.md`](dead-script-actions.md).
