# `ProximityCaptureUpdate` — capture a flag by standing on it

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR), so a file
offset is `VA - 0x400000` throughout. Read statically from the repo's own `game.dat`
(11,346,944 bytes, `sha256:5481de75…`), 2026-08-18. Game data read straight out of the install's
`.big` archives.

**On which binary this was read from.** The repo-root `game.dat` is *not* stock — it differs from
the clean reference `sage_mods/edain/patching/engine/game.dat.backup` in eleven runs, mostly the
logic/render-rate `idiv` sites around `0x00632537` and the LAN transport around `0x0084B43D`. None
of them is within 32 bytes of any site this patch edits, or of any routine the cave calls, and the
patch applies and verifies against the clean reference as well as against the repo copy. The check
is worth repeating for anything derived from that file: RE done on it can describe a modified byte
as if it were stock.

**Status: built.** See
[`patches/experimental/capture_the_flag.py`](../patches/experimental/capture_the_flag.py). It is a
**very wacky and experimental** patch by construction and ships in
[`patches/experimental/`](../patches/experimental/) with `experimental = True`: it applies,
verifies, detects and round-trips against the real binary and against a synthetic stand-in, and
the cave disassembles back to what it was meant to say — but it has not been established in play.

```
sage-patch apply capture-the-flag --in game.dat.backup --out game.dat
sage-patch apply capture-the-flag --block-name HoldTheLineUpdate --in ... --out ...
sage-patch verify capture-the-flag game.dat
```

## Verdict up front

The mechanic is cheap; the *plumbing around* the mechanic is what costs.

**Cost as built:** 8 edited sites — two `push imm8` allocation literals, two repointed `call`s,
one vtable dword, one field-table `imm32` and three name `imm32`s — plus a 1008-byte cave holding
800 bytes of code, a seven-row field table and seven strings. No structure grew that anything
`memcpy`s, and no byte is shared with another bundled patch.

- Every primitive the tick needs already exists in the binary and is already used by three
  shipped patches: a radius scan, an `ObjectFilter`, a horde-member count, and — the one that
  matters most — **`Object::setTeam` at `0x00697C09`**, which performs the whole ownership
  handover with its own bookkeeping. Note the address: `0x0068BC01` reads like `setTeam` and is
  `setID`, which is a bug this patch shipped once. §4.1.
- There is **no capture module to extend**: today's capture flag carries no capture logic at all.
  It lives on the *capturing unit*, as a `SpecialAbilityUpdate`. So this patch is purely
  additive — nothing has to be taken away from the flag, and the stock right-click capture can
  stay alive beside it. §1.
- The art is free. The stock `CaptureFlag` already animates `START_CAPTURE`, `CANCEL_CAPTURE`
  and `CAPTURED`, which are exactly the three states a proximity capture has. §1.
- **Registering a genuinely new module is the expensive way in.** The cheap way is to adopt one
  of the four module names that the engine registers and *nothing in the shipped data uses* —
  `AutoFindHealingUpdate` is the one that already is a periodic-scan `UpdateModule` with a scan
  rate and a scan range. Renaming it in INI is three `imm32` edits; changing its behaviour is one
  dword — the vtable turns out to be **private to the class**, both of its references in the whole
  image being this module's own constructor and destructor, so slot 0 is repointed in place and no
  copy is needed at all. §5.
- The one real risk is **state**, not the algorithm: the accumulator is logic state, so every peer
  needs the same binary and replays do not cross. The module persisting nothing turned out to be
  harmless — see §7. §7.
- **A map-script prototype could settle some of the design, but not the percentage rule.** The
  script layer has the ownership flip and a per-player unit count in an area, so "contest by
  presence" can be played before a byte is written — but the count is only ever exposed as a
  *comparison against a constant*, so a share is not computable without the patch. §5C.

## 1. What a capture flag is today

`Object CaptureFlag`, from `ini.big`:

```
KindOf = IMMOBILE CAPTURABLE STRUCTURE SELECTABLE UNATTACKABLE CAPTUREFLAG NEVER_CULL_FOR_MP

Body = HighlanderBody ModuleTag_02
  MaxHealth = 1.0
End
Behavior = DestroyDie ModuleTagDeath_03
  DeathTypes = ALL
End
Behavior = AIUpdateInterface ModuleTag_03
  AILuaEventsList = CaptureFlagFunctions
End
```

That is the whole object. **A body, a die, an AI stub, and a draw** — the flag has no capture
behaviour on it whatsoever. Its `W3DScriptedModelDraw` carries `AnimationState = START_CAPTURE`,
`AnimationState = CANCEL_CAPTURE` and `AnimationState = CAPTURED`, with a Lua script per state
picking the raise/lower/re-raise transitions.

The capture itself is a **special power on the capturing unit**:

```
Behavior = SpecialAbilityUpdate ModuleTag_CaptureBuildingUpdate
  SpecialPowerTemplate = SpecialAbilityCaptureBuilding
  StartAbilityRange    = 15.0
  UnpackTime           = 1
  PreparationTime      = 20000
  PackTime             = 1
  DoCaptureFX          = Yes
End
```

driven by `Command_CaptureBuilding` (`SPECIAL_INFANTRY_CAPTURE_BUILDING`, enum 29). The install
carries 1,715 references to that button in `__edain_data.big` alone — it is on essentially every
basic infantry horde in the game.

Three consequences for the design, and they are all favourable:

1. **The patch is additive.** It adds a module to the flag; it removes nothing from the unit. A
   map or mod that wants the stock behaviour too can keep both, and one that wants only the new
   one drops `Command_CaptureBuilding` from its command sets — an INI change, not a patch flag.
2. **The model conditions are already spent.** `START_CAPTURE` (110), `CANCEL_CAPTURE` (111),
   `CAPTURING` (112) and `CAPTURED` (119) are stock entries in the engine's model-condition name
   table (base `0x00D9FAD8`), which is the table
   [`patches/utils/model_conditions.py`](../patches/utils/model_conditions.py) already reads and
   extends. Setting them from the new module means the shipped flag art works with no new asset
   and no new token.
3. **Nothing is watching for a second capturer.** Because capture is a per-unit ability with a
   `PreparationTime`, contested capture today is "whoever's timer finishes first", not a contest.
   The requested mechanic is not a variant of the stock one; it is a different thing that happens
   to reuse the stock one's art.

## 2. The module, as INI

Four of these are the fields the request names; two more are the ones the mechanic turns out to
need, and §2.1/§2.2 say why. The values shown are the compiled-in defaults, so a block that omits
a keyword gets these.

```
Behavior = ProximityCaptureUpdate ModuleTag_CTF
  ObjectFilter      = ANY +INFANTRY +CAVALRY -SUMMONED
  Radius            = 150.0
  TickRate          = 500           ; MILLISECONDS between evaluations, not frames
  TickAmount        = 4             ; progress added per tick, out of 100
  CaptureShare      = 50            ; percent of the present population needed to contend
  CountHordeMembers = Yes           ; count horde members, not horde objects
End
```

| keyword | parse fn | `ModuleData` | notes |
|---|---|---|---|
| `TickRate` | `0x0073A429` `Duration` | `0x08` | inherits `ScanRate`'s slot and its **millisecond** reader |
| `Radius` | `0x0042ED00` `Real` | `0x0C` | inherits `ScanRange`'s slot |
| `TickAmount` | `0x0042EC5E` `Int` | `0x10` | was `NeverHeal` |
| `CaptureShare` | `0x0042EC5E` `Int` | `0x14` | was `AlwaysHeal`; an integer percent, never a float |
| `ObjectFilter` | `0x0076392F` | `0x18` | new |
| `CountHordeMembers` | `0x0042E558` `Bool` | `0x1C` | new |

`TickRate` being a `Duration` is the one thing here that reads wrong at a glance: the keyword
takes milliseconds and the engine's parser divides into logic frames, so `TickRate = 500` is half
a second and `TickRate = 30` is **one frame**, not one second. It keeps `ScanRate`'s parse
function because reusing the slot is what makes the field free; the alternative was renaming the
unit as well as the keyword.

`ObjectFilter`'s relationship tokens (`ALLIES`, `ENEMIES`, `SAME_PLAYER`) are evaluated with the
**flag's own controlling player** as the filter's source, so they read relative to whoever
currently holds it. Every stock call site passes a null source there, which makes the evaluator
reject unconditionally whenever a relationship mask is set — those tokens would otherwise match
nothing at all and look like a broken filter.

### 2.1 Why "tick speed" is two numbers

A tick rate alone fixes the cadence, not the duration. Folding them into one keyword forces
"evaluate often" and "capture fast" to be the same decision, so a mod that wants a 20-second
capture re-evaluated four times a second has to pay for 80 partition scans instead of 5. Keeping
`TickRate` (frames between scans) and `TickAmount` (progress per scan, on a fixed 0..100 scale)
separate makes the capture time `100 / TickAmount * TickRate` and leaves the scan cost a tuning
knob of its own. It also makes the down-tick symmetrical for free. At the defaults that is 25
ticks of half a second — a little over twelve seconds to take an uncontested flag.

### 2.2 The horde trap

In BFME almost nothing on the field is a bare object. A ten-man horde is one `Object` with a
contain module holding ten member objects, so a scan that counts what the partition manager
returns scores a full horde and a lone hero **1 apiece**, and the percentage rule reads as
nonsense to anyone watching.

This is not speculation about this engine — it is the exact defect
[`large-group-bonus-filter.md`](large-group-bonus-filter.md) documents in
`LargeGroupBonusUpdate`, which hands its filter *down* into each candidate's contain interface
(`Object::getContain` `0x0068C866`, then vslot `+0x180`, "how many of my members match this
filter") instead of evaluating it on the candidate. The same two calls give this module member
counting for about twelve bytes.

`CountHordeMembers = Yes` should be the default. The `No` case is worth keeping only because
"one horde, one vote" is a legitimate different game.

## 3. The state machine

One accumulator, one claimant, per flag.

```
state:  progress   0..100      (integer)
        claimant   player index, or NONE
        owner      player index, or NEUTRAL

every TickRate frames:
  pop[]  = filtered population inside Radius, bucketed by controlling player
  total  = sum(pop)
  lead   = argmax(pop)                                 ; ties -> no contender
  contender = lead if total > 0 and pop[lead]/total >= CaptureShare else NONE

  if contender is NONE:                                ; nobody holds the share
      halt        -- progress and claimant unchanged
  elif claimant is NONE or contender == claimant:
      claimant = contender
      progress += TickAmount, clamped at 100
      if progress == 100 and owner != claimant:
          owner = claimant                             ; CAPTURE
  else:                                                ; someone else holds the share
      progress -= TickAmount, clamped at 0
      if progress == 0:
          owner    = NEUTRAL                           ; the flag drops
          claimant = contender                         ; and immediately starts rising for them
```

This is the behaviour as requested, with three edges nailed down that the request leaves open:

- **No contender decays, it does not halt.** The first build froze the bar, which left a flag
  stuck at 90% indefinitely once the units that raised it wandered off. It now falls at the same
  `TickAmount` it rose at, flying the losing-the-claim flag so the art plays `CANCEL_CAPTURE` -
  the state whose animation lowers the banner - and at zero the claim, the capturing id and every
  capture condition clear together. All three ways to have no contender behave the same: an empty
  radius, a tie, and a leader short of the share.
- **Ties do not contend.** With two players at exactly 50% and `CaptureShare = 50%`, both meet
  the threshold and neither leads. Freezing is the only answer that is symmetric.
- **Ownership changes twice, at the two ends of the bar.** The flag goes neutral at 0 and
  captured at 100, which is what makes "ticking down then up" one accumulator instead of two.
  A `CaptureShare` under 50% lets more than one player clear the bar; the contender is then the
  *highest* share that also meets it, which is why the rule is written as `argmax` first.

Model conditions map onto the transitions, and the mapping is decided by the **art**, not by the
state machine. The flag's `W3DScriptedModelDraw` defines exactly three `AnimationState`s —
`START_CAPTURE`, `CANCEL_CAPTURE` and `CAPTURED` — so those are the three the module sets: a bar
going *up* is `START_CAPTURE` (which plays `CAPFLAG_UP` and carries the `LuaEvent = OnStateEnter`
that raises the flag), a bar going *down* is `CANCEL_CAPTURE`, a full bar is `CAPTURED`, and an
empty one is no condition at all. A halt holds whichever it already was.

**`CAPTURING` (112) is deliberately never set**, and the first build got this wrong. It is a real
entry in the engine's name table, so setting it looks right and the mask reads back correctly —
but the flag's art has no `AnimationState = CAPTURING`, and a condition no state names selects
nothing. The drawable stays in `IdleUncaptured` with the flag down, and because `START_CAPTURE` is
the state carrying the Lua, the script that raises the flag never runs. The symptom is a capture
that works — ownership does change — with no flag ever appearing.

## 4. What the engine already gives us

Every one of these is either already used by a shipped patch in this repo, or read out of the
binary for this document.

| VA | what | provenance |
|---|---|---|
| `0x00DE4354` | `ThePartitionManager` | [`fog-of-war.md`](fog-of-war.md), confirmed live |
| `0x00A39340` | `PartitionManager::iterateObjectsInRange`, NULL-terminated variadic filter list | [`player-heal-filter.md`](player-heal-filter.md), [`large-group-bonus-filter.md`](large-group-bonus-filter.md) |
| `0x00C10E20` / `0x00660E71` | stock partition filter: candidate is not dead | `LargeGroupBonusUpdate`'s own scan |
| `0x00C10E14` / `0x00660AFE` | stock partition filter: `getControllingPlayer(candidate) == source player` | same |
| `0x0068B678` | `Object::getControllingPlayer` | used by two shipped patches |
| `0x0068C866` | `Object::getContain`, then vslot `+0x180` = count members matching a filter | [`large-group-bonus-filter.md`](large-group-bonus-filter.md) |
| `0x0076392F` / `0x0076406F` / `0x007629B0` / `0x00762977` / `0x00763543` | the `ObjectFilter` ABI: parse fn, ctor, dtor, was-specified, evaluate (`ret 0xc`) | [`player-heal-filter.md`](player-heal-filter.md) |
| `0x00697C09` | **`Object::setTeam`** (`ret 8`, second argument 1) | §4.1 |
| `0x0068BC01` | `Object::setID` - **not** `setTeam`, and the trap §4.1 is about | §4.1 |
| `Object+0x31C` | `m_team`; `Object+0x74` is `m_id` | `getControllingPlayer`'s first instruction |
| `MAX_PLAYER_COUNT` = 20 | width of every per-player array | [`addresses.py`](../addresses.py) |

### 4.0 Three things the disassembly settled that the scope had guessed at

| question | answer |
|---|---|
| What does `update` return? | **`eax = 1`**, "call me again next frame". The stock body returns it on every path (`xor eax,eax; inc eax` at `0x00898A26`); `LargeGroupBonusUpdate` returns `0x3FFFFFFF` to mean "never". |
| How does the module pace itself? | Not by comparing frames. `[instance+0x20]` is a **countdown**: while positive it is decremented and the body skipped, and at zero it is reloaded from `ScanRate`. The patch reuses that dword and that logic exactly. |
| Is `iterateObjectsInRange` callee-cleaned? | **No.** Two stock callers push six and nine arguments respectively and *neither* adjusts `esp` afterwards — both are `ebp`-framed and recover at the epilogue. The cave does the same, which is why its epilogue is `lea esp, [ebp-0xFC]` and not three `pop`s. |

The scan itself is cloned from `PlayerHealSpecialPower::doSpecialPower` (`0x008CC4B4`) rather than
from `LargeGroupBonusUpdate`: it passes **one** filter, raw, with no `0x00A394C0` adjustor call
and no SEH frame, and does all its other screening per candidate. That is exactly the shape this
module wants, and it removes every ambiguity in the variadic argument list.

The iterator is an 8-byte handle: `0x00444F19` advances it and returns the next object or NULL,
`0x0044A2A5` releases it. The stock caller releases it explicitly on the normal path, so the cave
needs no exception frame to do the same.

### 4.1 `Object::setTeam` — and the routine that is **not** it

`Object::setTeam` is **`0x00697C09`**: `__thiscall(ecx = Object*, Team* newTeam, Bool)`, `ret 8`,
both stock callers passing 1. It reads the current team, early-outs when unchanged, notifies the
player list, writes `Object+0x31C` and then runs a long tail of handover bookkeeping. The team to
pass is the contending unit's own `+0x31C`, so the module still needs no player-to-team lookup.

**The first build called `0x0068BC01` instead, believing it to be `setTeam`. It is
`Object::setID`**, and this is worth writing down because the disassembly reads exactly like an
ownership change:

```
0068bc04  mov  eax, [esi+0x74]       ; "the current team"        <- actually m_id
0068bc0c  cmp  eax, edi              ; unchanged? nothing to do
0068bc14  mov  ecx, [0xde412c]       ; TheGameLogic
0068bc1b  call 0x62902e              ; "leaving the old team"    <- erase from the id map
0068bc22  mov  [esi+0x74], edi       ; the store
0068bc2e  call 0x62ba64              ; "joining the new one"     <- insert under the new id
```

Every feature of that reading survives contact with the code: a field, a same-value early-out, a
deregister, a store, a register. What kills it is one fact from outside the disassembly —
`Object+0x74` is `m_id`, **measured live against 386 objects** in
[`live-object-model.md`](live-object-model.md) §2 and recorded as
[`addresses.OBJECT_ID`](../addresses.py). The two "notifications" then resolve as what they are:
`0x0062902E` reads `[obj+0x74]` and erases that key from the map at `TheGameLogic+0xB4`;
`0x0062BA64` reads it and inserts the object under it. It is an id-table re-key.

The symptom in play was not a crash. The flag's owner never changed, so the flag's Lua — which
picks the faction banner from a side name — kept resolving `Neutral` and fell into its `else`
branch; meanwhile every capture handed the flag a *unit's* id and clobbered that unit's entry in
`TheGameLogic`'s lookup table, so anything resolving that unit by id got the flag instead. A
patch can be self-consistent, verify, disassemble correctly and still be aimed at the wrong
function; the live measurement is what settled it, which is the same lesson
[`runtime-re-workflow.md`](runtime-re-workflow.md) opens with.

The team field itself is not ambiguous once you look at the right anchor: `getControllingPlayer`
(`0x0068B678`) is two instructions, and the first is `mov ecx, [ecx+0x31C]`.

### 4.2 The second argument, which decides whether anybody is told

`setTeam`'s third parameter is a **suppress-notification** flag, and getting it wrong is the most
expensive kind of mistake this binary offers: everything visible still works.

```
00697db8  cmp  byte [ebp+0xc], 0
00697dbc  jne  0x697dd3            ; non-zero -> skip the whole block
00697dbe  ...  getControllingPlayer(old), getControllingPlayer(new)
00697dce  call 0x00696f0a          ; Object::onCapture
```

`Object::onCapture` walks the object's module array and calls vslot `+0x24` on **every** module
with the old and new player, then marks the UI dirty. Pass non-zero and none of it happens: the
team moves, the minimap recolours, the object answers to its new owner — and not one module knows.

Only one stock caller passes 1, and it is savegame restore (`0x0069831E`), where suppressing is
correct because the modules are being rebuilt from a snapshot rather than reacting to a live
change. The public one-argument wrapper the game uses (`0x00698E6F`) passes 0.

**This patch shipped a build that passed 1**, copied from the restore path. Ownership changed, so
it read as working; but a captured shipyard never re-ran its `CommandSetUpgrade` and kept the
neutral command set. The symptom was three steps removed from the cause, and the only thing that
found it was someone capturing the same building the stock way and saying "it does not".

## 5. Where to put the module

### Option A — register a new module type

The registration ABI is fully documented: `ModuleFactory::addModule` at `0x006570FE`, called
once per module in a long run with `(newModule, newModuleData, 0, 0, &name, 1)`. See
[`banner-carrier-filter.md`](banner-carrier-filter.md) §1 for the shape.

What makes this the expensive option is not the registration, it is the **vtables**. A module
instance carries three vptrs, and authoring a correct `UpdateModule` vtable from scratch means
getting every inherited slot right — including the ones no module in this repo has ever had to
identify. Rejected for v1.

### Option B — adopt a dead module (recommended)

Four module names are registered by the engine and referenced by **nothing** in the shipped data.
Checked by grepping every `.big` in the install (35 archives; ini text in them is uncompressed):

| module | `ini.big` | `_patch201ini.big` | `__edain_data.big` | any archive |
|---|---|---|---|---|
| `AutoFindHealingUpdate` | 0 | 0 | 0 | **none** |
| `DemoTrapUpdate` | 0 | 0 | 0 | **none** |
| `MonsterDockUpdate` | 0 | 0 | 0 | **none** |
| `HijackerUpdate` | 0 | 0 | 0 | **none** |
| `SpecialEnemySenseUpdate` | 7 | 5 | 48 | in use — **not** available |

`SpecialEnemySenseUpdate` is listed because it is the tempting one — `ScanInterval` + `ScanRange`
+ `SpecialEnemyFilter` is three of the four requested fields already — and it is exactly the one
that cannot be taken.

**`AutoFindHealingUpdate` is the fit.** It is an `UpdateModule` whose entire reason to exist is
running a periodic scan, and two of its four fields are already the two we want.

| what | VA / value |
|---|---|
| name string `"AutoFindHealingUpdate"` | `0x00C0B874` |
| registration `push` | `0x00658B07`, `addModule` at `0x006570FE` |
| `newModule` | `0x0064DB9F`, `operator new 0x24` (`push 0x24` at `0x0064DBAA`) |
| `newModuleData` | `0x0064DBD7`, `operator new 0x18` (`push 0x18` at `0x0064DBE3`) |
| module instance ctor | `0x008988C7` — base ctor `0x00653114`, zeroes `+0x20`, writes vptrs `0x00C65348` at `+0`, `0x00C67300` at `+0xc`, `0x00C6533C` at `+0x10` |
| `ModuleData` ctor | `0x00898887` — vtable `0x00C07A30`, `+0x8 = 0`, `+0xc = 0.0`, `+0x10 = 0.95`, `+0x14 = 0.25` |
| field-parse table | `0x00C653A0` — 4 rows plus terminator, registered by `0x008988B6` under the name pushed at `0x00898867` |
| **the update slot** | vtable `0x00C6533C`, slot `+0x00` → `0x00898999` |
| crc / xfer / loadPostProcess | `0x00C65348` `+0x14`..`+0x20`, all `0x0063F3BF` — a bare `ret` |

The stock field table, read out of the image:

| row | keyword | parse fn | offset |
|---|---|---|---|
| `+0x00` | `ScanRate` | `0x0073A429` (`Duration`) | `0x08` |
| `+0x10` | `ScanRange` | `0x0042ED00` (`Real`) | `0x0c` |
| `+0x20` | `NeverHeal` | `0x0042ED00` | `0x10` |
| `+0x30` | `AlwaysHeal` | `0x0042ED00` | `0x14` |

`ScanRate` and `ScanRange` are `TickRate` and `Radius` under different names, with the right
parse functions already. The rebuilt table keeps their offsets, renames them, drops the two heal
fields, and adds `TickAmount`, `CaptureShare` (`Percent`) and `ObjectFilter` (`0x0076392F`).

**Renaming the block costs three `imm32`s.** The name string `0x00C0B874` is referenced three
times: the factory registration (`0x00658B07`), the module's own name thunk (`0x00898815`:
`mov eax, 0xC0B874; ret`), and the parse-table registration (`0x00898867`). Repoint all three at
a cave string and the block is spelled `ProximityCaptureUpdate` everywhere the engine says its
name.

**Changing its behaviour costs one dword, and no copy.** The scope assumed a vtable copy; the
image says otherwise. `0x00C6533C` has exactly **two** references in the whole binary — the
constructor's `mov [esi+0x10], 0xC6533C` at `0x008988E8` and the destructor's identical write at
`0x0089880C` — so the vtable is private to this class and slot `+0x00` can be repointed where it
lies. The update entry it holds is `0x00898999`.

**Instance state has room after one edit.** The instance is `0x24` bytes with exactly one dword
of its own (`+0x20`, zeroed by the ctor — the scan countdown). The accumulator wants three more:
`push 0x24` → `push 0x30` at `0x0064DBAA` buys them, and a cave shim on the constructor zeroes
`progress` at `+0x24`, sets `claimant` at `+0x28` to `-1` and clears the applied-conditions cache
at `+0x2C`. The shim is not optional — `operator new` does not zero, so without it a flag starts
life part-captured for a garbage player index.

As built, the instance is:

| offset | what | who writes it |
|---|---|---|
| `+0x20` | scan countdown | the stock constructor, then every tick |
| `+0x24` | progress, 0..100 | the cave shim, then the accumulator |
| `+0x28` | claimant player index, `-1` for nobody | the cave shim, then the accumulator |
| `+0x2C` | the model-condition bits last applied | the cave shim, then the condition step |

The price of Option B is that `AutoFindHealingUpdate` **ceases to exist**. Nothing in stock RotWK
or Edain uses it, so that price is zero today — but it is irreversible for a mod that later wants
it, and the patch's `description` has to say so rather than leaving it to be discovered.

### Option C — prototype in map scripts (and what Lua is *not*)

**Lua is not the prototyping vehicle**, and it is worth being precise about why, because the
flag's INI advertises Lua twice and neither one is a foothold.

- The Lua in `W3DScriptedModelDraw`'s `BeginScript` blocks is **drawable-side**. Everything it
  can touch is spelled `CurDrawable…` — `CurDrawablePrevAnimationState`,
  `CurDrawableSetTransitionAnimState`, `CurDrawableHideSubObjectPermanently`. It chooses which
  animation plays. It is client state and it does not enter the logic frame.
- `AILuaEventsList = CaptureFlagFunctions` sounds like more than it is. From `scripts.lua`'s
  event-list table, in full:

  ```xml
  <EventList Name="CaptureFlagFunctions" Inherit="BaseScriptFunctions">
      <EventHandler EventName="OnGenericEvent" ScriptFunctionName="OnCaptureFlagGenericEvent" .../>
  </EventList>
  ```

  One handler, on one event, and `BaseScriptFunctions` it inherits from is empty. It is
  **reactive, not a tick** — there is no per-frame entry point, no way to enumerate objects in a
  radius, and no way to change an object's owner.

**Map scripts are a different story**, and the primitives do exist. From Worldbuilder's own
script enums:

| token | what it buys |
|---|---|
| `NAMED_TRANSFER_OWNERSHIP_PLAYER` | the ownership flip, on a named object |
| `PLAYER_HAS_COMPARISON_UNIT_KIND_IN_TRIGGER_AREA` | per-player population of a `KindOf` inside a trigger area |
| `SKIRMISH_PLAYER_HAS_UNITS_IN_AREA`, `SKIRMISH_VALUE_IN_AREA` | coarser variants of the same |
| `SET_COUNTER`, `INCREMENT_COUNTER`, `DECREMENT_COUNTER`, `COUNTER`, `COUNTER_COUNTER` | the accumulator and its comparisons |
| `DISPLAY_COUNTER` | the progress bar, on screen, for free |

So a single-map prototype of "stand near it and it flips" is genuinely buildable in Worldbuilder,
with a visible counter, in an afternoon.

**What it cannot do is the percentage.** `PLAYER_HAS_COMPARISON_UNIT_KIND_IN_TRIGGER_AREA` is a
*condition* — it answers "does player P have `>= N` units of kind K here" against a **constant**
N. It does not deposit a count into a counter, so `pop[P] / total` is not expressible; the
closest a script gets is a ladder of hardcoded thresholds, which is a different rule wearing the
same name. `SET_COUNTER_TO_NUMBER_OBJECTS_PLAYER_OWNES_WITH_MODELCONDITION` counts a player's
objects *globally*, not in an area, so it does not close the gap either.

That splits the design questions in two:

- **Answerable in a map script**: does contest-by-presence feel good at all; what radius reads as
  "on the flag"; how long a capture should take; whether a neutral-at-zero midpoint is satisfying
  or just slow; whether flags change hands often enough to matter.
- **Only answerable with the patch**: the share rule itself — whether a *percentage* is better
  than a flat unit count, where the threshold sits, and how a three-way contest behaves.

If the share rule is the part you are confident about and the feel is the part you are not, the
prototype is worth its afternoon. If it is the other way round, skip it and build the patch.

## 6. What was built

Eight edited sites and one cave. Every stock byte at every site is asserted before it is written,
so the patch fails loudly on anything that is not this build.

| # | site | stock | becomes |
|---|---|---|---|
| 1 | `0x0064DBAA` | `push 0x24` | `push 0x30` — the module instance |
| 2 | `0x0064DBE3` | `push 0x18` | `push 0x20` — the `ModuleData` |
| 3 | `0x0064DBC6` | `call 0x008988C7` | the instance-constructor shim |
| 4 | `0x0064DBF8` | `call 0x00898887` | the `ModuleData`-constructor shim |
| 5 | `0x00C6533C` | `0x00898999` | the cave's `update` — the vtable slot |
| 6 | `0x008988BC+1` | `0x00C653A0` | the rebuilt field table |
| 7–9 | `0x00658B07+1`, `0x00898815+1`, `0x00898867+1` | `0x00C0B874` | the cave's block-name string |

The cave is 1008 bytes: 800 of code (the `update` routine, and the two constructor shims), a
seven-row field table, and seven strings.

The `update` routine, in order: the countdown gate; zero twenty counts and twenty teams on the
stack; ask once whether `ObjectFilter` was written and once for the flag's own player; one
partition scan with the stock "not dead" filter; per candidate, `getControllingPlayer`, the filter
evaluator, then either one or — through `getContain` and vtable slot `+0x180` — the horde's
matching-member count, bucketed by `Player+0x54`; the leader and whether a tie beat it; the share
as `best * 100 >= total * CaptureShare`; the accumulator; `setTeam` at 100; and the model
conditions, propagated through `0x0068B53C` only when they actually change.

### 6.0 Two bugs that only a running game found

Both shipped, both verified, both disassembled correctly, and neither was visible to any static
check. They are recorded because the *class* of mistake matters more than the instances.

**The wrong function.** The first build called `0x0068BC01` believing it to be `setTeam`; it is
`Object::setID` (§4.1). Caught by a fact measured outside the disassembly.

**The frame collision.** `counts[]` is based at `[ebp-0x90]` and twenty dwords reach `[ebp-0x44]`,
so `-0x44`, `-0x48` and `-0x4C` *are* `counts[19]`, `counts[18]` and `counts[17]`. Three scalars
added after the first draft — "was `ObjectFilter` written", "the flag's own player", "is the claim
being taken away" — were placed exactly there. Storing the flag's `Player*` wrote a pointer into
`counts[18]`; the tally elected 18 as the leader by a landslide, `teams[18]` was empty, and so the
bar filled to 100, `CAPTURED` was applied, and the ownership flip was skipped every single time.

What found it was reading the module's own instance out of a live match through
[`sage_live`](../../sage_live/README.md): walking `TheGameLogic`'s object table to the flag, its
module array to the adopted module, and then four dwords —

```
+0x20 countdown = 1
+0x24 progress  = 100
+0x28 claimant  = 18     <- there is no player 18
+0x2C applied   = 0x00800000
```

`claimant = 18` is not a value any correct run can produce, and it named the offending slot
outright. The scalars now live *below* both arrays at `-0xE4`, `-0xE8` and `-0xEC`, and
`TestFrameLayout` asserts on the emitted code that no scalar access falls inside either array.

### 6.02 The command set, and two wrong turns before it

`CommandSetUpgrade`'s apply routine asks its own vslot 0 whether the trigger is satisfied and
then writes the module's `CommandSet` (`ModuleData+0x138`) into **`Object+0x43C`**, the object's
command-set override:

```
008b7d0a  call [eax]              ; vslot 0 - is the trigger satisfied?
008b7d19  mov  eax, [esi-0xc]     ; ModuleData
008b7d1c  mov  edi, [esi-8]       ; the Object
008b7d1f  add  eax, 0x138         ; &ModuleData.CommandSet
008b7d25  lea  ecx, [edi+0x43c]   ; the object's override
```

Nothing re-runs it when an object changes hands, so a captured structure keeps whatever override
it had - for a neutral shipyard, none at all, hence the template's `GenericSelfRepairCommandSet`.
Re-running it under the new owner is the fix. Two things hid it, and each cost a live test:

**The subobject.** The routine is slot `+0x20` of the interface vtable at `module+0x10`. Every
generic module-array walk in the engine dispatches through the vtable at `module+0` -
`Object::onCapture` (`0x00696F0A`) calls `+0x24` there, the upgrade refresh at `0x006902FA` calls
`+0x20` there. Neither can reach it, so a build that called `0x006902FA` on the captured object
landed on an unrelated slot and did nothing whatsoever.

**The sibling class.** `0x00C6FD18` and `0x00C6DEF8` are two upgrade modules with an *identical*
interface layout, differing only at slots `+0x18` and `+0x20`. Reading a constructor and assuming
which class it belonged to picked the wrong one, giving a vtable check that never matched. What
settled it was the live object: of the `ShipWright`'s thirty-four modules, **seven** carry
`0x00C6DEF8` at `+0x10`, each with a non-null `CommandSet` at `ModuleData+0x138`. It also sits
directly below `CommandSetUpgrade`'s own `ModuleData` vtable (`0x00C6DF40`) and field-parse table
(`0x00C6DF70`).

The module now walks the captured object's module array, checks each entry's `+0x10` against
`0x00C6DEF8`, and calls `0x008B7CFA` on the interface. Both the flag and every `LINKED_TO_FLAG`
structure go through it.

### 6.025 The command set: what is actually missing, measured

**Open.** Recorded precisely because the measurement is the useful part.

A `CommandSetUpgrade` caches whether its trigger is satisfied in a byte at **`module+0x14`**. Its
apply routine's first act is to read it, through a two-instruction predicate at vtable slot 0:

```
004986c4  mov al, byte ptr [ecx + 4]     ; ecx = module+0x10, so module+0x14
004986c7  ret
```

Clear means return immediately. So applying the command set is gated on that byte, and calling
the apply routine on an object whose byte is clear does nothing at all.

Diffed across a stock right-click capture of a `ShipWright`, baseline to captured:

```
+0x43C override      0x0 -> 0x19773fc0        the override is written
module[24] +0x14     0   -> 1                 exactly one of seven fires
module[26..31] +0x14 0   -> 0                 wrong factions, correctly inert
```

So the stock path **evaluates the faction trigger against the new owner**, sets the byte on the
one matching module, and the apply then writes `+0x43C`. A capture by this module leaves all seven
bytes clear, so the shipyard keeps its neutral command set.

What is still not found is *what evaluates the trigger*. It is not `Object::onCapture`: that walks
the module array calling slot `+0x24` of the vtable at `module+0`, which for this class is
`0x008851E4`, a bare `ret 8`. The byte's setter is slot `+0x24` of the *interface* vtable at
`module+0x10` (`0x005B462D`), a linker-folded two-instruction setter whose call graph leads
nowhere. Five separate anchors have failed to reach the stock capture completion - the same gap
§4.1 opened with.

The module already calls the apply routine on the flag and on every linked structure, which is
the correct *second* half and is inert until the first half exists. Whoever picks this up starts
from a known target: make `module+0x14` true for the module whose `TriggeredBy` matches the new
owner's faction, and the rest already works.

### 6.03 What a stock capture does to a *linked* structure

Diffed live across two stock right-click captures, against the same structure captured by this
module. Almost every difference between two matches is a pointer; exactly one was not:

```
ShipWright +0x11A    stock = 80      mine = 00
```

`+0x118` gaining `0x00800000` is `CAPTURED`. The stock path marks the linked structure captured;
this module was moving its team and leaving it looking untouched. The engine ships a
`MonitorConditionUpdate` whose entire job is swapping a command set on a model condition, so an
unmarked structure is one nothing downstream believes has been captured. The linked sweep now
sets the bit and propagates it, exactly as the flag's own conditions are.

Two other differences are recorded but not acted on: the flag's `+0x2B7` goes `01 -> 00` on a
stock capture and stays `1` here, and `CaptureFlag+0x80` is **`0`** after a stock capture - so the
capturing-id write in §6.04 is this module's own addition rather than a reproduction of stock.
It earns its place on the animation, not on fidelity.

### 6.04 `Object+0x80`, and why the flag has to go up *slowly*

A stock capture reads as a flag being raised over the capture's duration: the old banner lowers,
the new one climbs. The pacing is not the module's - it is `CAPFLAG_UP` played under
`AnimationSpeedFactorRange = 0.2857`, entered when `START_CAPTURE` is set and left when
`CAPTURED` replaces it.

What decides *whose* banner climbs is `Object+0x80`. `START_CAPTURE` carries
`LuaEvent = OnStateEnter`, and `OnCaptureFlagGenericEvent` opens with:

```lua
local str = ObjectCapturingObjectPlayerSide(self)
if str == nil then str = ObjectPlayerSide(self) end
```

The first call is the binding at `0x0073684D`: `findObjectByID(self+0x80)`, then
`getControllingPlayer`, then that player's side name. Mid-capture the flag still belongs to the
*old* owner, so the fallback is the wrong answer by construction - the field exists precisely so
the banner going up is the one taking the flag, not the one losing it.

**Nothing in the stock image writes it.** Every store to `[reg+0x80]` in the `Object` compiland
is the constructor or destructor zeroing `+0x70`..`+0x80` in a run. So on a flag this module is
the only thing that can, and a build that did not write it produced: pole rises bare (neutral
hidden, faction not yet revealed), then the faction banner appears already at the top when
`CAPTURED` lands. Which is exactly what it looked like.

The module now publishes the contender's `ObjectID` there on every rising tick and clears it when
the bar empties. That also settled the storage question - the per-player array holds a
representative **object** rather than a team, since the team is `+0x31C` away and the id `+0x74`,
and the capture path needs both.

### 6.05 `LINKED_TO_FLAG`, or why capturing the flag was not enough

A flag on its own is scenery. What makes one worth taking is the structure beside it, and the
engine wires that with a **kindof**, not a script:

```
Object ShipWright
  KindOf = PRELOAD STRUCTURE SELECTABLE IMMOBILE SCORE NOT_AUTOACQUIRABLE AUTO_RALLYPOINT
           FS_FACTORY PORT CAN_CAST_REFLECTIONS LINKED_TO_FLAG NEVER_CULL_FOR_MP NOT_SELLABLE
```

Note what is *absent*: `CAPTURABLE`. A `ShipWright` cannot be captured directly at all - a flag is
its only route. And the map that surfaced this (`map mp fords of isen ii`) carries **no**
ownership-transfer script action of any kind, so nothing else was ever going to move it.

`LINKED_TO_FLAG` is bit 50, so byte `template+0x10E` mask `0x04`, read out of the engine's own
KindOf name table rather than hardcoded. On the tick a flag changes hands the module runs a
**second** partition scan over the same radius and hands the new team to every object carrying
that bit. A second scan rather than bookkeeping during the first: capture is a once-per-flag
event where the cost is irrelevant, whereas tracking candidates would add work to every tick of
every flag. `CaptureFlag` does not carry the bit itself, so a flag cannot match its own sweep.

This is unconditional - there is no keyword. A flag that should hand nothing over is a flag with
nothing `LINKED_TO_FLAG` near it, which is a map's decision rather than a module's.

### 6.1 The `ObjectFilter`, which needs three calls and not one

Constructing it is not optional. `0x0076392F` opens by releasing whatever it finds in the slot
unless it is `-1`, so an unconstructed handle hands `operator new`'s leftovers to the interned
store as an index — which is why the `ModuleData` shim calls `0x0076406F` on `+0x18` after the
stock constructor has run.

Evaluating it uses `0x00763543` directly rather than the convenience wrapper at `0x007640C1`,
because the wrapper hardcodes a null source player and the evaluator rejects unconditionally on a
null source whenever a relationship mask is set. The source passed is the **flag's own**
controlling player, fetched once per tick, so `ALLIES` / `ENEMIES` / `SAME_PLAYER` read relative
to whoever holds the flag.

### 6.2 `xfer`, and why it turned out not to be needed

The scope flagged this as one of the two hard parts. It is not, and the reasoning is worth
recording because the instinct is to write one.

The module's crc / xfer / loadPostProcess slots (`0x00C65348` `+0x14`..`+0x20`) are all
`0x0063F3BF`, a bare `ret`: the stock module persists nothing, and the patch leaves that alone.
What a save therefore loses is `progress` and `claimant` — *not* the flag's owner, which is the
`Object`'s team and is saved like any other object's. On load every peer reconstructs the same
thing: progress zero, claimant nobody. Identical on every peer is the whole of what determinism
requires, so this is a fidelity loss across a save (a flag at 90% comes back at 0%) rather than a
desync. Writing an `xfer` would improve the fidelity; it is not load-bearing.

### 6.3 `sage_ini` needed a new kind of delta

`Engine` had `FieldDelta`, `NoopDelta`, `EnumDelta` and `LimitDelta` — nothing that could say *a
block type exists that did not before*, which is precisely what a `ModuleFactory` patch does. This
change adds [`BlockDelta`](../../sage_ini/engine.py): `BlockDelta(name, base=...)` registers a real
subclass so the new block inherits its base's schema, and `BlockDelta(name, removed=True)` takes
one out. Both revert. Blocks are applied **before** fields, so a patch can declare keywords on a
block the same surface introduces — which `capture-the-flag` does, and which is also why two of
the anti-drift tests in `test_sagepatch.py` had to learn that "a real block" now means the stock
model's *or* one this surface creates.

## 7. Risks

- **Logic state.** The accumulator is simulation state and enters the CRC. Every peer must run
  the same patched binary, and replays do not cross — the same class as
  [`production-condition`](production-model-condition.md), and the reason this cannot be a
  client-local patch the way `replay-outcome` is.
- **Determinism.** Keep `progress` an integer on a 0..100 scale. Float accumulation across peers,
  over a scan whose iteration order is not guaranteed, is the classic way to desync a mechanic
  that "works" in single player. `CaptureShare` should be compared as an integer cross-multiply
  (`pop[lead] * 100 >= total * share`), never as a division.
- **Scan cost.** Eight flags at `TickRate = 30` is eight partition scans a second, on top of
  everything else scanning. Cheap, but it scales with flag count, and it is why `TickRate` is a
  keyword and not a constant.
- **The AI will never contest a flag.** `SkirmishAI` has no notion of this module and will not
  walk to one on purpose; flags will change hands only where the AI happens to be fighting. That
  is a design consequence, not a defect, but it decides whether the mode is playable against
  bots. Out of scope here.
- **Twenty buckets, not eight.** `MAX_PLAYER_COUNT` is 20 and every per-player array the engine
  embeds is that wide. A hardcoded 8 works in every test game and corrupts the cave in an
  observer slot.
- **`AutoFindHealingUpdate` is spent.** Irreversible, and said out loud in the patch description
  and in the `.sagepatch` surface, which declares the block removed rather than leaving it in the
  model for a mod to keep writing.
- **The capture trimmings are unclaimed.** `InitialCaptureBonus`, the capture FX and the capture
  sounds the stock path pays out are not reproduced, and §4.1's open question — whether `setTeam`
  plus the model condition is the whole of "captured" as far as the radar, the shroud and the UI
  are concerned — is still open. It is the first thing to check in a live match.

## 8. What v1 should not include

- `CountHordeMembers = No`. Always count members; add the keyword when someone asks.
- Decay when the flag is empty. It is a fifth keyword and it changes the feel a lot; settle it in
  the Lua prototype first.
- `InitialCaptureBonus`, capture FX, capture sounds, and anything else the stock capture pays
  out. Get the ownership flip right, then decide which of the stock trimmings are worth
  reproducing.
- Any interaction with the stock `Command_CaptureBuilding` path. Leaving both alive is free;
  making them exclusive is a second mechanism.
