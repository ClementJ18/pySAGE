# The `FS_*` KindOf flags, and what the AI actually does with them

Recovered statically 2026-08-25 against the repo's `game.dat`, ROTWK build `2.01.2614.37001`,
ImageBase `0x400000`. Nothing here has been runtime-verified; see [Status](#status).

## TL;DR

- The `FS_` family is five KindOf bits: `FS_POWER`, `FS_FACTORY`, `FS_BASE_DEFENSE`,
  `FS_TECHNOLOGY`, `FS_CASH_PRODUCER`. The prefix is Generals-era **F**action**S**tructure.
- **`FS_BASE_DEFENSE` does not schedule, prioritise or gate AI construction.** It has exactly five
  read sites in `.text`, and none of them is in the `SkirmishAI` subsystem. Three are the castle
  plot-list selector, one is the threat evaluator, one is a target filter.
- Its only build-related effect is **which plot vector a castle offers**: a template carrying it is
  matched against the castle's *second* member vector (`+0x74`) instead of the normal one
  (`+0x50`). That is a **placement** rule, not a decision to build.
- `FS_POWER` and `FS_TECHNOLOGY` are **read nowhere** — no bit test against either survives
  verification. They are inert in this build.
- `FS_FACTORY` is the live one: eight read sites, **two of them inside `SkirmishAI`**. That
  contrast is the whole finding — the AI reads `FS_FACTORY` and never reads `FS_BASE_DEFENSE`.
- Consequently an `FS_ALWAYS_BUILD` modelled on `FS_BASE_DEFENSE` would inherit **nothing**
  useful.
- **`BASE_DEFENSE_FOUNDATION` is the other half of the pairing, and it has exactly one read site**
  — `0x008584AF`, a shifted `xor` against `FS_BASE_DEFENSE` that demands the two flags **match**.
  See [§2.5](#25-base_defense_foundation-the-other-half).
- Putting the new flag on the **foundation** instead of the building is the tractable design: it
  hooks `FoundationAIUpdate::update`, which already ticks and already knows when its plot is free,
  and it needs no part of the AI scheduler. See [§5](#5-scoping-always_build-on-the-foundation).

## 1. Where the bits live

`ThingTemplate`'s KindOf bitfield starts at **`tmpl+0x108`** and is addressed by
`KindOfMaskType::test(idx)` at **`0x006AACF0`**:

```asm
006aacfb  and  ecx, 0x1f          ; bit   = idx & 31
006aacff  shl  esi, cl
006aad03  shr  ecx, 5             ; dword = idx >> 5
006aad06  test [edx + ecx*4], esi
```

The name table is `0x00DA0E68`, 222 members, NULL-terminated at `0x00DA11E0`. Byte `+N` of the
mask is therefore `tmpl+0x108+N`, which is how every inline test below reads.

| flag | index | inline test |
|---|---|---|
| `FS_POWER` | 62 | `test byte [tmpl+0x10F], 0x40` |
| `FS_FACTORY` | 63 | `test byte [tmpl+0x10F], 0x80` |
| `FS_BASE_DEFENSE` | 64 | `test byte [tmpl+0x110], 0x01` |
| `FS_TECHNOLOGY` | 65 | `test byte [tmpl+0x110], 0x02` |
| `FS_CASH_PRODUCER` | 135 | `test byte [tmpl+0x118], 0x80` |

The related foundation flags, for reference: `BASE_FOUNDATION` 104 (`tmpl+0x115` bit 1),
`NEED_BASE_FOUNDATION` 105, `BASE_DEFENSE_FOUNDATION` 153 (`tmpl+0x11B` bit 2).

### How the read sites were enumerated

Two sweeps over `.text`, because one alone is a false-negative machine:

1. every `F6 /0 disp32 imm8` (`test byte [reg+disp32], imm8`) whose `disp32` is an FS_ byte;
2. every `mov r32, [reg+disp32]` on an FS_ dword followed within eight instructions by a
   `test`/`and` on that register — the load-then-test idiom the first sweep cannot see.

Sweep 2's raw output is mostly noise: offsets `0x110`/`0x118` are common struct fields, and a
`shr` before the mask changes which bit is meant. Every surviving candidate was confirmed by
reading its context for a base register provably loaded from `[obj+4]` (the `Object` → template
link) or from a template-typed argument. **Sites whose base register is also written (`or`/`and`
into the same offset) were rejected** — a `ThingTemplate` is immutable at runtime, so a mutation
site is a different struct. That rule alone eliminated the entire `0x005Exxxx` / `0x0066Axxxx` /
`0x0076Axxxx` cluster that a naive scan reports as `FS_CASH_PRODUCER`.

## 2. `FS_BASE_DEFENSE`: five reads, and what each one does

Excluding the INI parser at `0x0089B86E` / `0x0089BA3B`, which only sets and clears the bit.

### 2.1 The castle plot-list selector — three sites, one rule

`0x007996D3`, `0x0079A5EC` and `0x0079A688` are three `CastleBehavior` entry points that all open
with the same shape. `0x007996D3` ("does this castle have a free plot for `t`?") is the clearest:

```asm
007996d3  cmp  dword [ecx+0x34], 4       ; castle must be in state 4
007996d7  je   .go
007996d9  xor  al, al                    ; otherwise: no
...
007996dd  mov  eax, [esp+4]              ; eax = ThingTemplate * (may be NULL)
007996e4  lea  edi, [ecx+0x50]           ; default: the normal plot id vector
007996e7  je   .walk                     ; NULL template -> normal vector
007996e9  test byte [eax+0x110], 1       ; FS_BASE_DEFENSE ?
007996f0  je   .walk                     ; no -> normal vector
007996f2  lea  eax, [ecx+0x74]           ; yes -> the base-defense plot id vector
007996f5  mov  ecx, [eax+4]
007996f8  sub  ecx, [eax]
007996fa  sar  ecx, 2                    ; ... but only if it is non-empty
007996fd  je   .walk
007996ff  mov  edi, eax
```

Read it as one sentence: **the castle offers its `+0x74` plot vector instead of its `+0x50` one
when, and only when, the template is `FS_BASE_DEFENSE` and that vector is not empty.** Then it
walks the chosen vector, resolves each member id, and asks each member's foundation interface
whether it is occupied.

`0x0079A5EC` is the same test in the "find me a free plot" form, with a slot index argument (`-2`
meaning "any", otherwise clamped into range); `0x0079A688` is the same test again in a third walk.
Same rule, three times.

This pairs with what [`foundation-rebind.md`](foundation-rebind.md) §2.3 already records about
`FoundationAIUpdate`'s adopt-scan at `0x008583E3`, which checks the
`BASE_DEFENSE_FOUNDATION`(153) / `FS_BASE_DEFENSE`(64) pairing before claiming a standing object.
The two halves are consistent: `BASE_DEFENSE_FOUNDATION` marks the *plot*, `FS_BASE_DEFENSE` marks
the *building allowed on it*.

**This is why marking an outpost building `FS_BASE_DEFENSE` is load-bearing today.** It is not a
hint to build — it is the key that makes the building match a `BASE_DEFENSE_FOUNDATION` plot at
all. Remove it and the building stops being placeable there; adding it does not make anyone place
it sooner.

### 2.2 The threat evaluator — `0x0068F0EC`

`ecx` is an `Object`, `edx = [ecx+4]` its template:

```asm
0068f0f3  mov  eax, [edx+0x108]
0068f0f9  test al, al
0068f0fb  jns  .not_structure            ; bit 0x80 of byte +0 = STRUCTURE
0068f105  test al, 8                     ; bit 0x08 of byte +0 = CAN_ATTACK
0068f107  je   .tail                     ; a structure that cannot attack: no threat
0068f10d  test byte [edx+0x110], 1       ; FS_BASE_DEFENSE ?
0068f114  je   .use_threatlevel
0068f116  fld  dword [ecx+0x340]         ; yes: threat = two runtime, weapon-derived reals
0068f11c  fadd dword [ecx+0x33c]
0068f122  leave
0068f123  ret
.use_threatlevel:
0068f124  movss xmm0, [edx+0x52c]        ; no: the template's ThreatLevel
```

`tmpl+0x52C` is `ThreatLevel` — confirmed against the recovered `Object` field table in
[`ini-types.json`](ini-types.json), which puts `ThreatLevel` at `+0x52C` (between `CrushZFactor`
`+0x528` and `ThreatBreakdown` `+0x530`).

So for an attacking `FS_BASE_DEFENSE` structure the AI's threat number comes from the object's
live weapon state rather than the authored `ThreatLevel`. Three of this function's ten callers are
`SkirmishAI` (`0x009A2716`, `0x009EAFF1`, `0x009EB01B`), which matches the presence of
`AITargetHeuristicBaseDefense.cpp` in the pool strings. **This affects how the AI attacks base
defences, not whether it builds them.**

### 2.3 A target filter — `0x00661869`

A vtable slot (`0x00C0F19C` slot `+0x10`). `esi` is the candidate `Object`:

```asm
0066186e  mov  eax, [esi+4]
00661871  test byte [eax+0x108], 0x80    ; STRUCTURE ?
0066187b  je   .accept                   ; not a structure -> accept
...
006618bb  mov  eax, [esi+4]
006618be  test byte [eax+0x110], 1       ; FS_BASE_DEFENSE ?
006618c5  jne  .accept                   ; -> accept unconditionally
006618c7  cmp  dword [esi+0x258], 0      ; otherwise it has to pass a further test
006618d2  call 0x691269                  ; (which begins with testStatus(NO_ATTACK))
```

An `FS_BASE_DEFENSE` structure short-circuits to accepted where an ordinary structure must earn
it. This reads as the "don't bother with insignificant buildings" carve-out — `AIData` does expose
`AttackIgnoreInsignificantBuildings` (`+0x68`) — but the link from that field to this function was
**not** traced, so treat the naming as a plausible reading and the behaviour as the established
fact.

### 2.4 The negative result

Two sweeps establish this and it is the load-bearing claim of the whole document:

- **No `SkirmishAI` code (`0x0096xxxx`–`0x009Exxxx`) reads `FS_BASE_DEFENSE`.** All five sites are
  at `0x0066`, `0x0068` and `0x0079`.
- **`SkirmishAI` makes zero direct calls into the castle plot region `0x799000`–`0x79B000`.**
  Scanning every `E8 rel32` with a source in `0x960000`–`0x9F0000` and a target in that window
  returns nothing.

The AI therefore neither reads the flag nor calls the code that does. Whatever makes the AI slow
to build on an outpost plot, `FS_BASE_DEFENSE` is not the lever.

### 2.5 `BASE_DEFENSE_FOUNDATION`: the other half

A `test byte [tmpl+0x11B], 2` sweep finds **nothing**, because the engine never reads this flag
that way. Its one read site is inside `FoundationAIUpdate`'s adopt-scan (`0x008583E3`, main vtable
`0x00C56E30` slot `+0x40`), and it reads the bit **shifted out of a dword and XORed** against the
candidate's `FS_BASE_DEFENSE`:

```asm
008584a0  mov  eax, [esi+4]         ; esi = the PLOT object -> its ThingTemplate
008584a3  mov  eax, [eax+0x118]     ; KindOf dword 4 (bytes +0x10 .. +0x13)
008584a9  mov  ecx, [edi+4]         ; edi = the candidate building -> its ThingTemplate
008584ac  shr  eax, 0x19            ; bit 25 -> bit 0 == BASE_DEFENSE_FOUNDATION (153)
008584af  xor  al, [ecx+0x110]      ; XOR against FS_BASE_DEFENSE (64)
008584b5  test al, 1
008584b7  jne  .reject              ; the two bits must MATCH
008584b9  push [edi+0x74]           ; accept: setBuiltOnObject(candidate->id)
008584bc  mov  ecx, [ebp-0x10]
008584bf  call 0x8582de
008584c4  push esi                  ; and setProducer(candidate, plot)
008584c7  call 0x68b6a1
```

The bit arithmetic checks out: the dword at `tmpl+0x118` spans bytes `0x118`–`0x11B`, so bit 25 is
byte `0x11B` bit `0x02` — exactly `BASE_DEFENSE_FOUNDATION` (index 153, byte `+0x13`, bit `0x02`).

`xor` makes the rule **symmetric and exclusive in both directions**:

| plot | building | verdict |
|---|---|---|
| `BASE_DEFENSE_FOUNDATION` | `FS_BASE_DEFENSE` | accepted |
| `BASE_DEFENSE_FOUNDATION` | anything else | rejected |
| plain foundation | `FS_BASE_DEFENSE` | **rejected** |
| plain foundation | anything else | accepted |

So the flags are not a hint or a preference — they are a strict two-way type match, and the
castle-side rule in §2.1 is the same pairing enforced from the other end. Note the third row: an
`FS_BASE_DEFENSE` building is *barred* from ordinary plots, which is a constraint worth knowing
before adding the flag to anything.

This scan is a **one-shot**. Per [`foundation-rebind.md`](foundation-rebind.md) §2.3 it runs only
under the `+0x1C` flag set by the module constructor, is cleared immediately
(`0x00858505  mov byte [esi+0x1c], 0`), and never re-runs — it exists to adopt whatever the map
placed on the plot at load.

One more appearance, unidentified: `0x0079C64B`–`0x0079C65E` builds a KindOf set through
`0x006615E5` from `(0, STRUCTURE, WALK_ON_TOP_OF_WALL, BASE_FOUNDATION, BASE_DEFENSE_FOUNDATION,
TACTICAL_MARKER)` and stores it at `[esi+0x30]`. The owning class was not identified, so this is
recorded as a sighting, not as behaviour.

## 3. `FS_FACTORY`: the one the AI actually reads

Eight sites, every one a verified `mov reg, [obj+4]` template read:

| site | context |
|---|---|
| `0x00793E68` | takes a template; if `FS_FACTORY`, resolves its CommandSet (`tmpl+0x70`) through `0x0071EFA2` and walks the buttons (`0x0080C837`) checking command types 1/3/0x35 — "can this factory actually produce anything" |
| `0x008BC56E` | `[ecx+4]` |
| `0x008F06BF` | `AIPlayer`'s structure-created hook; gates entry into the SkirmishAI producer index — already documented in [`ai-construction-gate.md`](ai-construction-gate.md) §3 |
| `0x008F0C6C` | `[esi+4]` |
| `0x008F5395` | the legacy `AIPlayer::findFactory` |
| `0x0090D7ED` | `[esi+4]`, inside an object-filter predicate |
| **`0x009B79EF`** | **`SkirmishAI`** — `[ebx+4]`, then `test byte [eax+0x120], 4` (index 194) |
| **`0x009E7353`** | **`SkirmishAI`** — `[edi+4]` |

`FS_FACTORY` is what tells the engine "this structure produces things", and it is consulted on the
AI's live path. This is the shape a *working* AI-facing KindOf has, and it is exactly the shape
`FS_BASE_DEFENSE` does not have.

## 4. `FS_POWER`, `FS_TECHNOLOGY`, `FS_CASH_PRODUCER`

### `FS_POWER` (62) — inert

**Zero read sites.** No `test byte [tmpl+0x10F], 0x40`, and no combined mask either — a
`test ... 0xC0` would have surfaced in sweep 1 as `FS_POWER|FS_FACTORY` and none did. Generals used
it for power plants feeding a base-wide power budget; RotWK has no power economy and the bit was
never rewired. Inferred purpose: **dead Generals inheritance.**

### `FS_TECHNOLOGY` (65) — inert

**Zero confirmed read sites.** Two candidates were examined and both fail:

- `0x006CBA40` — `test byte [eax+0x110], 2`, but `eax` comes from `call [esi+0x2c]` on a
  linked-list node payload, and the same pointer is then used as `[eax+0x17c]` (a list head). Not
  a template.
- `0x006DD043` — `mov eax, [esi+0x110]; sub eax, 6; neg; sbb` is an integer state comparison
  (`== 6`), not a bit test.

Inferred purpose: **Generals-era "tech building / captured neutral structure" marker, dead here.**

### `FS_CASH_PRODUCER` (135) — one confirmed read

`0x008660B4`, in the function at `0x00865EB6`. `eax` is a template loaded from `[[ebp-0x10]+4]`,
and the flag is checked immediately after `GARRISON` (index 118):

```asm
008660a8  mov  eax, [eax+4]
008660ab  test byte [eax+0x116], 0x40    ; GARRISON
008660b2  jne  .ok
008660b4  test byte [eax+0x118], 0x80    ; FS_CASH_PRODUCER
008660bb  je   .reject
```

Inferred purpose: **marks a structure as an income building** — the resource-producer counterpart
to `FS_FACTORY`. The one confirmed site is a gameplay predicate, not AI economy planning; the
`SkirmishAI` economy tunables (`FarmingThreshold`, `EconomyMaxFarms`, `DisableEconomyBuilding`)
were not traced to it.

## 5. Scoping `ALWAYS_BUILD` on the foundation

### 5.1 Why the foundation is the right place

Marking the *building* cannot work: §2.4 shows the AI never reads a building-side KindOf on any
path that decides to construct, so a building-side flag has nothing to hook into and the AI
scheduler — which is not yet located — would have to be found and patched first.

Marking the *plot* changes the problem completely. `FoundationAIUpdate` is a module that already
ticks on every foundation, already owns the plot `Object`, and already tracks whether it is
occupied. A plot that builds its own first available option needs no AI code at all, works
identically for every owner, and reuses primitives the engine already exposes.

### 5.2 The pieces the engine already provides

| what | where | notes |
|---|---|---|
| the tick | `FoundationAIUpdate::update` `0x008584DB` | the hook lives here |
| "am I free" | module `+0x18` = built-on `ObjectID` | zero, or fails `findObjectByID` (`0x00449681`), means free — the test the tick already performs at `0x008585EC`–`0x00858601` |
| the plot `Object` | `[module-8]` | the module's owner back-pointer, used throughout the tick |
| adopt-scan one-shot | module `+0x1C` | already consumed at load; do not reuse |
| `setBuiltOnObject` | `0x008582DE` | how the tick records occupancy |
| the plot's CommandSet name | `tmpl+0x70` | as used by `0x00793E64` |
| CommandSet lookup | `0x0071EFA2` | name → `CommandSet *` |
| `getCommandButton(i)` | `0x0080C837` | `m_command[33]` at `+0x14`, **no bound check** — see [`commandset-button-limit.md`](commandset-button-limit.md) |
| button's target template | `CommandButton+0x20` (`Object`) | `+0x14` is `Command` |
| the affordability / prereq gate | `TheBuildAssistant` vtable `+0x64` = `0x00793ECB` | already named `CAN_MAKE_UNIT_PRODUCTION_GATE` in [`addresses.py`](../addresses.py) |
| **the build primitive** | `TheBuildAssistant` (`0x00DE8200`) vtable `+0x38` = **`0x00797796`** | `buildObjectNow(builder, template, pos, angle, player)` |

The vtable base is `0x00C307D8`, confirmed rather than assumed: slot `+0x64` is `0x00793ECB` and
slot `+0x68` is `0x00794F38`, both already named in `addresses.py`.

`buildObjectNow` matters because **it already knows about plots**. At `0x0079784F` it branches on
the builder's `BASE_FOUNDATION` (index 104) and, when set, fetches the plot's foundation interface
through `0x0068C3C3` and calls its vtable `+0x1C`:

```asm
0079784f  test byte [eax+0x115], 1     ; builder is a BASE_FOUNDATION
00797856  je   .not_a_plot
00797858  mov  ecx, edi                ; the plot Object
0079785a  call 0x68c3c3                ; -> its foundation interface
0079785f  fld  dword [ebp+0x14]        ; angle
00797862  mov  edx, [eax]
00797864  push 0 / push 0 / push [ebp+0x18]   ; player
0079786f  push ebx / push esi          ; position, template
00797873  call [edx+0x1c]              ; the foundation's own "build this here"
```

So the cave calls one function with the plot as the builder, and the engine routes it down the
plot path itself. No reimplementation of construction is needed.

### 5.3 The patch

1. **The flag.** New KindOf name at index 222. `KindOfMaskType::test` (`0x006AACF0`) is
   width-agnostic (`mask[idx>>5]`, no bound check), and index 221 already lives in dword 6
   (`tmpl+0x120`), confirmed by the live read `test byte [eax+0x120], 4` (index 194) at
   `0x009B79F8`. Index 222 is therefore bit `0x40000000` of a dword templates already carry — no
   struct growth, no mask-width change. The name table must move, though: it ends at `0x00DA11E0`
   and the next table begins at `0x00DA11E4`, so relocate it to a cave and repoint the 14
   references to `0x00DA0E68`, exactly as `commandset-button-limit` does.

2. **The hook.** Inside `FoundationAIUpdate::update`, on the branch that has established the plot
   is free. Guard on the plot template carrying `ALWAYS_BUILD`.

3. **Selection.** Walk the plot's CommandSet, slots 0..32. Take each button's `Object`
   (`+0x20`); skip null. Offer it to the `+0x64` gate. **First one that passes wins** — which is
   exactly the requested behaviour and needs no scoring, no priorities and no AI state.

4. **Execute.** `[0x00DE8200]` vtable `+0x38` with `(plotObj, template, plotPos, plotAngle,
   plotOwner)`.

### 5.4 Four things to decide before writing it

These are design choices, not unknowns, but getting them wrong produces a patch that technically
works and ruins matches.

- **Whose plots?** The tick runs on every foundation, human-owned included. Without an owner
  check, human players' plots would fill themselves in too. If the intent is AI-only, gate on the
  controlling player — `0x0068B678` is the object → player accessor used throughout this region.
- **Throttling.** The update runs on a logic cadence, so an unguarded hook retries the whole
  CommandSet walk constantly, and a plot that can afford nothing burns the scan every tick.
  A frame stamp is needed. It must be **frame-based, not wall-clock**, or replays and multiplayer
  desync. The module has no obvious spare dword, so this likely needs a cave-side table keyed by
  `ObjectID`, or a repurposed field established as unused first.
- **Does `buildObjectNow` charge for it?** The `+0x64` gate checks cost and prerequisites, but
  whether the build primitive itself deducts the money was **not** traced. If it does not, a
  cave that gates then builds gets the structure free. This must be settled before the patch is
  trusted — it is the difference between "the AI builds promptly" and "the AI builds free".
- **Which buttons count.** The `Command` enum backing `CommandButton+0x14` was not recovered
  (parse fn `0x0075CB37`), so the exact id for a plot-build button is unknown. Selecting on
  "`Object` is non-null **and** the `+0x64` gate passes" sidesteps this and is the safer filter,
  but recovering the enum would let the walk reject non-build buttons up front.

### 5.5 Determinism

Everything the hook reads — occupancy, KindOf, CommandSet contents, player resources — is logic
state, and `FoundationAIUpdate::update` runs on the logic thread on every peer. So the added edge
is network- and replay-safe by the same argument as
[`ai-construction-gate.md`](ai-construction-gate.md) §Determinism, **provided** the throttle in
§5.4 is a logic-frame counter and the CommandSet walk is ordered (it is — a plain index scan).

### 5.6 The cheaper experiment, still worth running first

The stall the patch is meant to fix has not actually been attributed to a cause. Since §2.4 rules
out `FS_BASE_DEFENSE`, the remaining suspects are the AI's own pacing, and those are reachable from
INI without touching the binary: `AIData`'s `StructureSeconds`, `StructuresPoorRate` /
`StructuresWealthyRate` and `RebuildDelayTimeSeconds` (the struct is at `[TheAI(0x00DE4B40)+0x18]`,
parse fn `0x005D869A`), and `SkirmishAIData`'s `DefenseTreeNodeRadius` (`[TheSkirmishAIManager
(0x00DE4938)+0x10] +0x974`). If tightening those changes the observed behaviour, that both
identifies the responsible loop and may remove the need for the patch.

## 6. Routes that need no binary patch

### 6.0 Edain already solves this in data — and this supersedes §5

Before any of the routes below, the important finding: **the mod already implements
"AI fills its plots", entirely in INI, and the pattern is worth copying rather than replacing.**

Worked example, `ImladrisDunedainOutpost2` in
`object/goodfaction/structures/imladris/dunedaincampkeep.ini`.

**1. The engine grants an "I am AI-owned" upgrade to everything.** `default/object.ini` carries an
`InheritableModule`, so every Object in the game inherits it:

```ini
Behavior = ObjectCreationUpgrade ModuleTag_RealAI
    TriggeredBy  = Upgrade_EasyAISinglePlayer ... Upgrade_BrutalAIMultiPlayer
    Delay        = 500
    GrantUpgrade = Upgrade_ObjectUnderAIControl
End
```

So an AI-owned object gains `Upgrade_ObjectUnderAIControl` **500 logic frames (~16 s) after
creation**. That delay is a plain, tunable cause of "the AI does nothing for a while".

**2. Plots swap to an AI-only CommandSet on that upgrade.** One numbered ChildObject per slot in
the `.bse` layout:

```ini
ChildObject DunedainBuildingFoundation1 DunedainBuildingFoundation
    Behavior = CommandSetUpgrade ModuleTag_CommandSetAI
        TriggeredBy = Upgrade_ObjectUnderAIControl
        CommandSet  = DunedainFoundationCommandSet_ForAI1
    End
End
```

**3. Each AI CommandSet holds exactly one button**, so the AI has no choice to make — "first
building it can" becomes "the only building it can":

```ini
CommandSet DunedainFoundationCommandSet_ForAI1
    1 = Command_ConstructDunedainTurmBFME1_ForAI
End
```

against the human set, which offers four.

**4. The button is `FOUNDATION_CONSTRUCT`** — this incidentally answers the open question in §5.4
about which `Command` value a plot-build button uses:

```ini
CommandButton Command_ConstructDunedainTurmBFME1_ForAI
    Command = FOUNDATION_CONSTRUCT
    Object  = DunedainTurm_ForAI
End
```

**5. The AI's target is a free `_ForAI` variant that carries the flag:**

```ini
ChildObject DunedainTurm_ForAI DunedainTurm
    BuildCost = 0
    KindOf    = +FS_BASE_DEFENSE
End
```

`BuildCost = 0` removes the affordability gate — the AI never has to save up, which is the other
half of "why is it slow". `KindOf = +FS_BASE_DEFENSE` is the §2.5 pairing, added on the AI variant
so it matches a `BASE_DEFENSE_FOUNDATION` plot.

**The numbering lives in the `.bse`, not the INI.** `CommandSetUpgrade` is declared on the numbered
ChildObjects only — the plain `DunedainBuildingFoundation` has none — so a base template that
places the unnumbered object gets the human CommandSet and no free `_ForAI` variants. Parsing
`bases/dunedain_outpost/dunedain_outpost.bse` with `python -m sage_map info` shows it places
exactly the numbered ones:

```
1 x DunedainBuildingFoundation1
1 x DunedainBuildingFoundation2
1 x DunedainBuildingFoundation3
1 x DunedainCampKeep
1 x BaseCenterGeneric
```

So this outpost is **fully wired**, and it has no base-defence plots at all —
`DunedainBaseDefenceFoundation` (and the empty `BauplatzKICommandSet` it swaps to under AI control)
belong to other layouts and are not part of `dunedain_outpost`.

That matters for diagnosis: where the pattern is wired, the remaining latency is not the wiring.
It is the inherited `Delay = 500` before the AI CommandSet appears at all, plus whatever cadence
makes the AI press the button — the scheduler §5.4 could not locate.

**What this means for §5.** The foundation-side `ALWAYS_BUILD` patch solves a problem the data
layer already solves better: per-plot control, per-faction control, no engine change, and the
"which building" decision stays in INI where a modder can see it. Treat §5 as the fallback for
cases the data pattern genuinely cannot express, not as the plan.



The patch in §5 is not the only way to fill a plot, and probably not the first thing to try. The
engine ships a family of **script actions** built for exactly this job, and RotWK exposes a Lua
layer that can reach them.

### 6.1 The script actions already exist

From the ScriptEngine's action templates, with the engine's own UI strings:

| action | engine description |
|---|---|
| **`BUILD_BASE_BUILDING`** (`0x00C3EF50`) | "Player_/AI/AI build base building in **first available slot** in a referenced base." |
| `BUILD_BASE_BUILDING_IN_SLOT` (`0x00C3EEAC`) | "Base/AI build base building in slot in a referenced base." |
| `BUILD_BUILDING_ON_FOUNDATION` (`0x00C3ED2C`) | "Build building on the chosen foundation." |
| `BUILD_BASE_BUILDING_PER_TACTICAL_MARKER` (`0x00C35C5C`) | "AI build base building on a foundation chosen by proximity to tactical marker (new)." |
| `BUILD_BASE_BUILDING_WITH_TACTIC` / `_PER_TACTIC` (`0x00C35C1C` / `0x00C35C3C`) | tactic-driven variants |
| `NAMED_BASE_UNPACK` / `NAMED_BASE_UNPACK_FREE` (`0x00C3F060` / `0x00C3EFD8`) | "Unpack a base so team can start building structures on it." |
| `SKIRMISH_BUILD_BUILDING` (`0x00C4AB6C`) | skirmish-side build |
| `SKIRMISH_BUILD_BASE_DEFENSE_FRONT` / `_FLANK` (`0x00C4A7A8` / `0x00C4A70C`) | skirmish base-defence placement |

`BUILD_BASE_BUILDING` is, verbatim, the behaviour §5 was going to add in assembly. The plot-side
machinery `buildObjectNow` exposes (§5.2) is the same machinery these actions drive — the callers
of `CastleBehavior::hasFreePlotFor` (`0x007996D3`) and the plot picker (`0x0079A5EC`) are all in
the ScriptActions region (`0x007Bxxxx`–`0x007Exxxx`), not in `SkirmishAI`.

### 6.2 What the `.bse` / `AIBase` system is, and is not

`AIBase` (INI block, parse fn `0x0082F676`) pairs a `Side` with a `.bse` map file (the `.bse`
literal is pushed at `0x0082FB1C` from that same parser), optionally filtered by `GameMapToUseOn`
and `PlayerPositions`.

Checked against the Edain tree: **480 `.bse` files**, and **115 `AIBase` blocks** in
`data/ini/default/skirmishaidata.ini`. But every one of those blocks names a main-base WotR layout
(`ai base - gondor wotr`, `ai base - rohan wotr - 01`, …) and **none references a camp** — a
`Map =` value containing "camp" appears zero times. The many `*_camp*.bse` files
(`angmar_camp`, `angmar_campE`, `angmar_campN`, …) are WorldBuilder placement templates, not AI
base layouts.

So the `.bse` route governs where an AI's *starting* base comes from. It is not a mechanism for
filling an outpost captured mid-match, and extending it is not the path.

### 6.3 The Lua layer

RotWK loads `Data\Scripts\Scripts.lua` and `Data\Scripts\ScriptEvents.xml` (both literals present
in the binary), and Edain ships both. The engine registers a small object-scoped Lua API — the
name table sits around `0x00C24BB4`–`0x00C24E80` and includes `ObjectGrantUpgrade`,
`ObjectHasUpgrade`, `ObjectDoSpecialPower`, `ObjectPlayerSide`, `ObjectTeamName`,
`ObjectDispatchEvent`, the `ObjectBroadcastEventTo*` family — and, importantly, **`ExecuteAction`**
and **`EvaluateCondition`**.

`ScriptEvents.xml` declares the hooks, including `OnCreated` ("sent when an object has been
constructed") and `OnBuildingComplete` ("sent when an object has completed building").

So the shape of a no-patch solution is: an outpost or plot fires `OnCreated` /
`OnBuildingComplete`, and a Lua handler calls `ExecuteAction` on one of §6.1's build actions.

**The open question, and it is the decisive one.** Edain's `Scripts.lua` contains exactly **one**
`ExecuteAction` call, `ExecuteAction("NAMED_KILL", self)` — an action name plus one object. The
build actions take more: a base reference, a thing template, a slot index, a result reference name.
Whether the Lua binding marshals additional parameters at all was **not** determined; reading the
registration block around `0x00739C80` did not settle which C function belongs to the
`ExecuteAction` name (the name/function pairing in that block is ambiguous on a first read, and the
candidate at `0x007366FE` takes a number and returns a string, so it is a different binding).

This is cheap to settle empirically — write a Lua handler that calls a build action with
parameters and see whether it runs — and it is worth settling before writing any assembly, because
if it works the whole of §5 becomes unnecessary.

### 6.4 Choosing between the routes

The axis is **how much of the map surface has to be covered**:

| route | covers | cost | main risk |
|---|---|---|---|
| map / AI scripts (§6.1) | only maps you author | none — intended mechanism | does not reach user-made maps |
| Lua handler (§6.3) | mod-wide, every map | small, no engine change | `ExecuteAction` parameter marshalling unverified |
| binary patch (§5) | mod-wide, every map | largest; name-table relocation + cave | does `buildObjectNow` charge? (§5.4) |
| skip plots entirely | mod-wide | data-only | loses plot bookkeeping and player choice |

The last row is worth stating explicitly: if AI outposts do not need to offer a *choice*, the
simplest answer is not to make the AI choose. An outpost variant that arrives with its structures
already present — or that creates them itself — removes the problem instead of solving it. The
cost is that the plot never records occupancy (`setBuiltOnObject` at `0x008582DE` is never called),
so anything that walks the castle's member vectors will still consider those plots free.

## 7. What was checked in the Edain tree

For reproducibility, the data-side claims above come from
`C:\Users\Clement\Documents\Edain\Edain-Mod\_mod` (the dev tree, per `tests/corpus_roots.txt`):

- `bases/*.bse` — 480 files, including directional camp variants.
- `data/ini/default/skirmishaidata.ini` — 115 `AIBase` blocks, all main-base WotR layouts, no camp.
- `data/scripts/Scripts.lua`, `data/scripts/ScriptEvents.xml` — the Lua layer, one `ExecuteAction`.
- `data/ini/object/**/campsandcastles.ini` — Edain's base-defence plots carry **both**
  `BASE_FOUNDATION` and `BASE_DEFENSE_FOUNDATION`, with a per-faction CommandSet, e.g.
  `KindOf = STRUCTURE SELECTABLE IMMOBILE BASE_FOUNDATION BASE_DEFENSE_FOUNDATION UNATTACKABLE ...`
  alongside `CommandSet = AngmarBaseDefenceFoundationCommandSet`. This matches the pairing in §2.5
  and is the CommandSet a §5 patch would walk.

## Status

**Static only, and partial.** Every address and disassembly listing above was read out of the
repo's `game.dat` and every FS_ read site was individually confirmed by its surrounding context.
The §6–§7 data claims come from reading the Edain dev tree. Nothing has been observed in a running
game, and no patch has been written.

Open items, in the order they matter:

1. **Can Lua's `ExecuteAction` carry parameters?** (§6.3) If yes, §5 is unnecessary. Settle this
   first — it is an experiment, not an RE task.
2. **Does `buildObjectNow` deduct the cost?** (§5.4) Blocks trusting the patch.
3. The AI structure-build scheduler (§5.6) — still unlocated, but no longer on the critical path
   now that the foundation-side design avoids it.
4. The `AttackIgnoreInsignificantBuildings` link in §2.3 — cosmetic, affects only a name.
