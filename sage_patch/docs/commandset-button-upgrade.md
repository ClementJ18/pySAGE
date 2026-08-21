# Buying single command buttons with an upgrade — reverse-engineering notes

The RE behind
[`patches/commandset_button_upgrade.py`](../patches/commandset_button_upgrade.py). Engine build
`2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR), read statically from
`sage_mods/edain/patching/engine/game.dat.backup` (11,346,432 bytes) — the clean reference,
**not** the repo-root `game.dat`, which carries 11 modifications.

**Status: built** as `commandset-button-upgrade`, applying and verifying against the real binary
and against a synthetic stand-in, and composing with `commandset-limit` in either order.

## The gap

An object's command bar comes from exactly one named `CommandSet`. The only stock way to change
it at runtime is `CommandSetUpgrade`, which swaps the *whole* set:

```
Behavior = CommandSetUpgrade ModuleTag_01
  TriggeredBy = Upgrade_BuySpear
  CommandSet  = KnightCommandSetWithSpear
End
```

So "this unit can buy any of four abilities" costs **2^4 = 16** hand-written `CommandSet` blocks
and 16 `CommandSetUpgrade` modules, each naming a combination. Adding a fifth ability doubles it
again. The combinatorics, not the engine, are what stop mods from doing this.

## TL;DR

- **The engine already builds command sets at runtime.** The Create-A-Hero designer at
  `0x00809FFB` sprintf's a name (`CommandSet_%s_%s_rank_%d`, `0x00C4F270`), creates a **mutable**
  `CommandSet` under it, copies a base set's buttons in, overlays its own `(button, slot)` list,
  and points the object at it. Every primitive this patch needs is in that one function (§2).
- `Object::getCommandSetString` @ `0x0069156B` is the **single funnel** — 54 callers, including
  the Apt control bar and `BuildAssistant::canMakeUnit`. It is a four-way priority chain over
  three per-object override strings and the template's (§1).
- `Object::setCommandSetStringOverride` @ `0x00693B94` writes the third of those and **already
  fires the control-bar refresh**, so the UI side is free.
- The `UpgradeMux` interface (vtable `0x00C6DEF8`) gives an exact, cheap way to enumerate "every
  upgrade module on this object that is currently applied": walk `Object+0x24C`, compare each
  module's own vtable pointer against `0x00C6DF40`, read the latch byte at `module+0x14` (§3).
  Three loads, no virtual calls. That is what makes *accumulating* buttons possible rather than
  *replacing* them.
- **Removal comes free**, from a slot the first scan of this missed: `Object::updateUpgradeModules`
  calls mux slot `+0x18` on every module on every pass, and for `CommandSetUpgrade` that slot
  (`0x008B7CAB`) runs `unUpgradeImplementation` and then `attemptUpgrade` — a reset-and-re-evaluate
  over the whole module set (§5).
- Shape: **one new `AsciiString` field on the existing `CommandSetUpgrade`**, not a new module.
  `sizeof(ModuleData)` `0x13C` → `0x140`, the table rebuilt in the cave (it has one row and no
  slack), constructor and destructor shims, two entry hooks. **Six edits and a `0x4DF`-byte
  cave** — the same order as [`upgrade-grant-lists`](upgrade-grant-lists.md) and
  [`lifetime-extend-upgrade`](lifetime-extend-upgrade.md).

INI:

```
Behavior = CommandSetUpgrade ModuleTag_Spear
  TriggeredBy    = Upgrade_BuySpear
  CommandButtons = Command_ThrowSpear:5 Command_BraceSpear
End
```

`Name:Slot` pins a button to a numbered slot; a bare `Name` takes the lowest free one. The stock
`CommandSet` keyword keeps its stock meaning, and a module that does not name `CommandButtons`
executes stock bytes.

## 1. Where an object's command set comes from

`Object::getCommandSetString()` @ `0x0069156B`, 15 instructions, returns an `AsciiString*`:

```
0069156F  lea edi,[esi+0x438]   ; if not empty -> return it
00691580  lea edi,[esi+0x440]   ; else if not empty -> return it
00691591  lea edi,[esi+0x43c]   ; else if not empty -> return it
006915A6  mov eax,[esi+4]       ; else -> getTemplate()
006915A9  add eax,0x70          ;         ->m_commandSetString  (the INI `CommandSet`)
```

`0x00401E64` is `AsciiString::isEmpty`. Priority is therefore **`+0x438` > `+0x440` > `+0x43C` >
template**, and the three overrides belong to three different subsystems:

| field | written by | note |
|---|---|---|
| `+0x438` | Create-A-Hero design build, `0x0080A062` | highest priority; a CAH hero ignores the other two |
| `+0x440` | `0x008585A7`, `0x00858679`, `0x008586AD` — the garrison/occupancy swap (one arm stores the literal `"empty"`, `0x00C56E74`) | outranks `CommandSetUpgrade` |
| `+0x43C` | **`Object::setCommandSetStringOverride`** @ `0x00693B94` — `CommandSetUpgrade`'s field | the one this patch uses |

The 54 callers of `getCommandSetString` re-read it every time they populate, so a changed override
takes effect on the next repopulate; nothing caches the resolved name.

### `setCommandSetStringOverride` @ `0x00693B94`

```
00693B9D  lea edi,[esi+0x43c]
00693BA5  call 0x436030            ; AsciiString::set
00693BAC  call 0x68b678            ; getControllingPlayer
00693BB9  call 0x6aa5b3            ; ...is local?
00693BC9  call 0x4065aa            ; compare
00693BD9  call 0x6a9999            ; TheInGameUI [0x00DE4938]
00693BE7  call 0x8e3d1e            ; refresh(obj, 2)
```

The UI notification is already in the function. `CommandSetUpgrade::upgradeImplementation`
(`0x008B7C68`) piles on a deselect/reselect (`0x006A99CB` then `0x006A9D9C`) and sets the store's
dirty byte `[TheCommandSetStore+0x28] = 1`. Reusing that setter buys the whole client side.

## 2. The engine's own runtime command-set builder

`0x00809FFB` — the Create-A-Hero design's set build, one argument (the rank). It is the working
model for this patch, and every call in it is reusable:

```
0080A051  push 0xc4f270            ; "CommandSet_%s_%s_rank_%d"
0080A057  call 0x437a90            ; format into a local AsciiString
0080A062  lea ecx,[esi+0x438]      ; store the generated name on the Object
0080A069  call 0x436030
0080A074  push 1                   ; <-- the mutable flag
0080A07A  call 0x72028b            ; CommandSetStore::newCommandSet(name, mutable)
0080A084  call 0x80c8d2            ; clearCommandButtons
0080A09A  call 0x71efa2            ; findCommandSet(base name)
0080A0A5  loop edi = 0..0x20:
0080A0A8    call 0x80c837          ;   getCommandButton(base, edi)
0080A0B6    call 0x80c8ef          ;   setCommandButton(new, edi, button)
0080A0CE  loop over its own 15-entry (name, level, slot) table:
0080A105    call 0x71d6ea          ;   findCommandButton(name)
0080A117    call 0x80c8ef          ;   setCommandButton(new, slot, button)
0080A148  call 0x71d6ea            ; "Command_AttackMove" (0x00C4F25C)
0080A157  call 0x80c8ef            ;   -> slot 0x10
0080A164  mov byte [eax+0x28],1    ; store dirty
```

Three things follow that are not obvious from the `CommandSet` INI block:

**`0x0072028B` always creates.** It is `operator new(0xA0)` + ctor + `map[name] = set`
(`0x0071F52D` returns the slot, `0x007202D2` writes it). Calling it twice with one name overwrites
the map entry and leaks the old object. The patch must call `findCommandSet` (`0x0071EFA2`) first
and only create on a miss — which also makes the synthetic set a **cache**.

**Sets have a mutable flag at `+0x9C`.** Both `clearCommandButtons` (`0x0080C8D2`) and
`setCommandButton` (`0x0080C8EF`) open with `cmp dword [ecx+0x9c], 1 / jne ret`. INI-parsed sets
are created with `0` (`push ebx` at `0x007205FD` and `0x0072064F`, `ebx = 0`) and are therefore
**silently immutable**; only sets created with `1` can be written. So the patch cannot mutate a
mod's own `CommandSet` in place even if it wanted to — synthesis is the only route, and that is
the right answer anyway, since an INI set is shared by every object of every template naming it.

**The name is the identity.** Two peers that generate the same string get the same set. That is
what makes this deterministic across a network game (§5).

## 3. Enumerating the upgrade modules that are currently applied

The naive design — "on upgrade, add my button to whatever set is showing" — cannot be undone and
is order-dependent. The correct design rebuilds the **union** of every applied overlay each time
one changes. `Object::updateUpgradeModules` @ `~0x006936FC` shows the walk:

```
006936FC  call 0x68b678             ; getControllingPlayer
0069371B  add eax,0x14c             ; player's completed-upgrade mask
00693740  mov esi,[edi+0x24c]       ; Object::m_behaviors, NUL-terminated BehaviorModule*[]
0069374D  lea ecx,[eax+0xc]         ;   the BehaviorModule interface subobject
00693752  call [eax+0x28]           ;   getUpgrade()  -> UpgradeMux* (module+0x10), or NULL
0069375F  call [eax+0x00]           ;   isAlreadyUpgraded()
00693773  lea eax,[edi+0x28c]       ;   object's completed-upgrade mask, OR'd into the player's
006937A8  call [eax+0x04]           ;   attemptUpgrade(mask)
```

The `UpgradeMux` interface vtable (`0x00C6DEF8` for `CommandSetUpgrade`) is shared by every
upgrade module:

| slot | fn | meaning |
|---|---|---|
| `+0x00` | `0x004986C4` — `return byte[this+4]` | `isAlreadyUpgraded()` — **the latch** |
| `+0x04` | `0x008D26BF` | `attemptUpgrade(mask)`: `if (vt[8](mask)) giveSelfUpgrade()` |
| `+0x08` | `0x008D26F3` | `isUpgradeConditionsMet(mask)` — the `TriggeredBy` / `ConflictsWith` test |
| `+0x0C` | `0x008D2901` | `attemptRemoveUpgrade(mask)` |
| `+0x14` | `0x008D26B3` | `if (byte[this+4]) upgradeImplementation()` — re-apply |
| `+0x20` | `0x008B7CFA` | `unUpgradeImplementation()` (module-specific) |
| `+0x24` | `0x005B462D` — `byte[this+4] = arg` | `setUpgradeExecuted(bool)` |
| `+0x28` | `0x008B7C68` | `upgradeImplementation()` (module-specific) |
| `+0x2C` | `0x00863B4F` | `getUpgradeActivationMasks` — `0x24` dwords each from `ModuleData+8` and `+0x98` |

So the rebuild predicate is two loads and a compare per module: `[mux] == 0x00C6DEF8` identifies
one of ours, `byte[mux+4]` says whether it is applied, and `[mux-0xC]` is its `ModuleData`. No
mask arithmetic, no re-evaluation of `TriggeredBy`.

**One ordering trap.** `giveSelfUpgrade` @ `0x00855388` is

```
0085539B  call [eax+0x28]     ; upgradeImplementation()   <-- runs first
008553A4  call [eax+0x24]     ; setUpgradeExecuted(true)  <-- latch set after
```

so while our own implementation is running its latch is still `0`. The walk must count `this` as
applied — a pointer compare against the `mux` it was entered with.

## 4. What was built

### 4.1 The field

One new `AsciiString` on `CommandSetUpgradeModuleData`, at **`+0x13C`** — the first byte past the
current `sizeof`, and directly after the stock `CommandSet` at `+0x138`. The `ModuleData` layout
is `UpgradeMuxData` at `+0x08` (`TriggeredBy` `+0x08`, `ConflictsWith` `+0x98`,
`CustomAnimAndDuration` `+0x128`, the three flags `+0x134..0x136`) then `CommandSet` at `+0x138`.

A single `AsciiString` holding a whitespace-separated token list costs one pointer of structure
growth — the same lever as [`upgrade-grant-lists`](upgrade-grant-lists.md), and it gets
multi-button grants for free. `patches/utils/token_lists.py` supplies the parser; the cave walks
the tokens itself, because each one may carry a `:slot` suffix.

**The `:` survives tokenisation.** `INI::getNextAsciiString` (`0x0042E757`) splits through
`getNextTokenOrNull` (`0x0042DBF5`), whose default separator set is the `INI`'s own `+0x418`,
initialised at `0x0042CAEE` to the string at `0x00BD3D30` — `" \n\r\t="`, five characters, no
colon. So `Command_Foo:5` arrives as one token, the way `DeathAnimAndDuration`'s `AnimState:X`
does.

### 4.2 Runtime

Hook `CommandSetUpgrade::upgradeImplementation` @ `0x008B7C68` at its entry. If **no** module on
the object carries a non-empty `CommandButtons`, fall straight back into the stock body: an
existing mod's bytes and behaviour are unchanged. The test is on the object rather than on this
module because a plain `CommandSetUpgrade` sharing an object with an overlay has to route through
the rebuild too — otherwise whichever of the two fired last would win, and the answer would
depend on module order. Otherwise:

1. **Base set name.** Walk `Object+0x24C` once. Applied `CommandSetUpgrade` modules that name a
   plain `CommandSet` supply the base (last in module order wins, which is what stock last-writer
   semantics already give); if none does, the base is `getTemplate()->+0x70`. Deriving the base
   from the walk rather than from the object's current override is what makes the operation
   idempotent — re-running it produces the same set, which matters because the same walk is the
   removal path and the reload path.
2. **Synthetic name.** `<base>` plus each applied module's tokens, in module-array order. Module
   order comes from the INI, so it is identical on every peer.
3. `findCommandSet(name)` (`0x0071EFA2`). Hit -> step 6.
4. Miss -> `newCommandSet(name, 1)` (`0x0072028B`), `clearCommandButtons` (`0x0080C8D2`).
5. Copy the base's buttons (`0x0080C837` / `0x0080C8EF`), then overlay each token: resolve with
   `findCommandButton` (`0x0071D6EA`), write at the named slot, or at the lowest index whose
   `getCommandButton` is NULL.
6. `setCommandSetStringOverride(object, name)` (`0x00693B94`), then the stock tail — deselect,
   reselect, `[TheCommandSetStore+0x28] = 1`.

`unUpgradeImplementation` (`0x008B7CFA`, vtable slot `+0x20`) goes to the same cave with `this`
excluded from the union, guarded by the same latch check the stock body opens with, and finishing
with the same `setUpgradeExecuted(false)` — so removal is the same code path.

**The latch is not the caller's own truth.** `UpgradeMux::giveSelfUpgrade` (`0x00855388`) calls
`upgradeImplementation` at `0x0085539B` and `setUpgradeExecuted(true)` at `0x008553A4`, in that
order, so a module's own latch is still clear while its implementation runs; `unUpgradeImplementation`
is the mirror, running while its own latch is still set. Both hooks therefore tell the walk what
to count `this` as, rather than letting it read `module+0x14`.

### 4.3 What it cost

Six byte ranges and a `0x4DF`-byte cave (`.cmdbtn`):

| # | site | edit |
|---|---|---|
| 1 | `push 0xC6DF70` @ `0x008B7C10` | `imm32` -> the rebuilt field table in the cave |
| 2 | `push 0x13C` @ `0x00655452` | `imm32` -> `0x140` |
| 3 | `call 0x436030` @ `0x00655432` (ctor) | `rel32` -> a shim that zeroes `+0x13C`, then tail-calls it |
| 4 | `call 0x435D50` @ `0x00656004` (dtor) | `rel32` -> a shim that destroys `+0x13C`, then tail-calls it |
| 5 | `0x008B7C68` (7 bytes) | `jmp rel32` + two `nop` |
| 6 | `0x008B7CFA` (5 bytes) | `jmp rel32` |

The cave is the rebuilt table (`0x30`), the keyword string (`0x10` padded), the shared list parser
(`0x76`) and `0x429` of code: the two hooks, the module scan, the rebuild, the token walk and the
two shims.

Sites 3 and 4 are symmetric one-instruction retargets, and neither shim has to know which register
holds the `ModuleData`: both calls are reached with `ecx` = `&ModuleData->CommandSet` (the `lea`s
at `0x0065541A` and `0x00655FFE`), so the new field is `ecx+4`. The constructor at `0x00655400`
zeroes `+0x138` and assigns it the global empty `AsciiString` at `0x00DC62B8`; the destructor at
`0x00655FE9` releases it. Neither is shared — both belong to `CommandSetUpgradeModuleData` alone.

**The five-byte window at `0x008B7CFA` is exact.** It is the `mov eax, 0x00BA3234` that hands
`__EH_prolog` its handler table, so the passthrough puts `eax` back and resumes on the `call`
itself. The upgrade hook has no such luck: five bytes there would cut `lea ecx, [esi-0x10]` in
half, so it displaces **seven** (four instructions) and re-executes all four before jumping back
to `0x008B7C6F`.

**The bound is read at run time, not baked in.** `commandset-limit` rewrites the `imm8` of
`cmp edx, 0x21` inside `setCommandButton` (`0x0080C8FE`), and that byte is the only place the live
slot count is written down. The cave loads it with `movsx eax, byte [0x0080C8FE]` on every
rebuild. Baking it at apply time instead would break rule 3 of the patch framework's composition
rules — deriving output from bytes another patch rewrites — and the two would silently disagree
in one of the two application orders. Both orders are checked.

**No new module registration.** Adding a genuinely new module name means one more
`addModuleInternal` call (the pattern at `0x0065A2C2`: `push "CommandSetUpgrade"` /
`push 0x84` interface mask / `push 0x00655446` newModuleData / `push 0x0064FC25` newModule) plus
cloning four vtables into the cave. That is roughly triple the surface for a cosmetically nicer
keyword, and it is the right call only if the two behaviours turn out to need different
`TriggeredBy` semantics.

## 5. How removal reaches this patch

Scoping this, the removal path looked like the thing that might sink it: `attemptRemoveUpgrade`
(`0x008D2901`) clears the latch and the custom animation and does **not** call
`unUpgradeImplementation`, and the only caller of vtable slot `+0x20` that a call scan finds is
the debug handler at `0x006974D0`. On that reading a revoked upgrade would leave its button behind.

That reading was wrong, and the answer is one slot over. `Object::updateUpgradeModules` ends each
module's turn with `call [eax+0x18]` at `0x006937AF` — **unconditionally, for every upgrade module
on the object, on every pass**, whether or not it just fired. For `CommandSetUpgrade` that slot is
its own `0x008B7CAB`:

```
008b7cb9  call [eax+0x20]      ; unUpgradeImplementation()   -- always, first
008b7cbf  getControllingPlayer / player+0x14c
008b7ce4  mask |= object+0x28c
008b7cf4  call [eax+0x04]      ; attemptUpgrade(mask)
```

So the engine already runs a **reset-and-re-evaluate** over the whole module set every time
anything changes: each module undoes itself (`unUpgradeImplementation` clears the latch at
`0x008B7D6B`), then re-tests its `TriggeredBy` and `ConflictsWith`. Hooking both halves is
therefore all removal needs — when the upgrade is gone the re-test fails and the module stays off,
and the last overlay to re-apply rebuilds the union without it.

Reset and re-apply interleave per module rather than running as two phases, so the override
flickers through intermediate values within one pass. That is harmless because the rebuild is a
pure function of the latches: whichever module goes last writes the correct final answer.

## 6. Consequences worth knowing

- **Not client-local.** `getCommandSetString` feeds `BuildAssistant::canMakeUnit` @ `0x00794FB8`,
  which is logic-side, so **every peer must run the same patched binary** and replays do not cross
  — same footing as [`production-condition`](production-model-condition.md).
- **Store growth.** One `CommandSet` per distinct combination actually realised in a match
  (`0xA0` bytes stock, `0x110` at N=64), never freed. Bounded by reachable combinations, not by
  the 2^n the INI would have needed. The cave calls `findCommandSet` before `newCommandSet` for
  exactly this reason: `newCommandSet` always allocates and overwrites the map entry, so building
  the same combination twice would leak the first copy.
- **Create-A-Hero heroes ignore it.** The CAH design writes `+0x438`, which outranks `+0x43C`
  (§1). Same for a garrisoned structure's `+0x440`.
- **Determinism rests on module order**, which is INI order. `Object+0x24C` is sized from
  `(template+0x2E8 - template+0x2E4) / 0x14` at `0x00699E65` — a contiguous vector of module
  records on the `ThingTemplate`, appended to as the INI is read — so every peer parsing the same
  files builds the same array in the same order, and the synthetic name comes out the same.
- **A slot past the limit is dropped silently**, because `setCommandButton`'s own guard drops it.
  That is the engine's behaviour for a bad slot, not something this patch adds, but it means a
  typo'd `Command_Foo:99` shows as a missing button rather than an error.

## 7. Open verification items

1. **Is mux slot `+0x14` on the load path?** `Object+0x43C` appears in no `xfer` — the scan finds
   it written only by the constructor (`0x00699C38`), the destructor (`0x0069AA8A`) and the setter
   — so the override does not survive a save. Slot `+0x14` (`0x008D26B3`: "if the latch is set,
   re-run `upgradeImplementation`") exists precisely to re-apply on load, and if it is on the load
   path the synthetic set is rebuilt for free. Not yet confirmed.
2. **Does the Apt control bar cache the resolved `CommandSet*`** anywhere past the deselect /
   reselect refresh (`0x00943D97` re-reads it per populate, but the `0x0092…`–`0x009E…` cluster
   has its own mirror array at `ControlBar+0x2B0`).

## Key addresses (v2.01.2614.37001, ImageBase `0x400000`)

| what | address |
|---|---|
| `Object::getCommandSetString` | `0x0069156B` |
| `Object::setCommandSetStringOverride` | `0x00693B94` |
| `Object::updateUpgradeModules` | `~0x006936FC` |
| `Object` module array / upgrade mask | `+0x24C` / `+0x28C` |
| `Object` command-set overrides | `+0x438`, `+0x440`, `+0x43C` |
| `ThingTemplate::m_commandSetString` | `+0x70` |
| `Player` upgrade mask | `+0x14C` |
| CAH runtime set builder | `0x00809FFB` |
| `CommandSetStore::findCommandSet` | `0x0071EFA2` |
| `CommandSetStore::newCommandSet` | `0x0072028B` |
| `CommandSetStore::findCommandButton` | `0x0071D6EA` |
| `TheCommandSetStore` | `0x00DE7744` (dirty byte `+0x28`) |
| `CommandSet::getCommandButton` / `setCommandButton` / `clear` | `0x0080C837` / `0x0080C8EF` / `0x0080C8D2` |
| `setCommandButton`'s slot guard / its `imm8` | `0x0080C8FC` / `0x0080C8FE` |
| `CommandSetUpgrade::upgradeImplementation` | `0x008B7C68` (resume `0x008B7C6F`) |
| `CommandSetUpgrade::unUpgradeImplementation` | `0x008B7CFA` (resume `0x008B7CFF`) |
| `CommandSetUpgrade::attemptUnUpgrade` (mux slot `+0x18`) | `0x008B7CAB` |
| `CommandSetUpgrade` module vtable | `0x00C6DF40` (written at `0x008B7C2B`) |
| `CommandSetUpgrade` field table / its one reference | `0x00C6DF70` / `push` @ `0x008B7C10` |
| `CommandSetUpgradeModuleData` ctor / dtor / `sizeof` | `0x00655400` / `0x00655FE9` / `0x13C` (`push` @ `0x00655452`) |
| its `CommandSet` default / release | `call` @ `0x00655432` / `call` @ `0x00656004` |
| `UpgradeMux` interface vtable (this module) | `0x00C6DEF8` |
| `UpgradeMuxData` base field table | `0x00C76AD8` (one reference, `0x008D26E1`) |
| `UpgradeMux::giveSelfUpgrade` / `setUpgradeExecuted` | `0x00855388` / `0x005B462D` |
| `UpgradeMux::isUpgradeConditionsMet` / `setCustomAnim(false)` | `0x008D26F3` / `0x008D28F9` |
| the `UpgradeMux` "already upgraded" latch | `module+0x14` (= interface `+0x04`) |
| `INI` default separators (`" \n\r\t="`) | `0x00BD3D30`, installed at `0x0042CAEE` |
| `TheGameLogic` / `TheUpgradeCenter` | `0x00DE412C` / `0x00DE45A0` |
| the selection global the module deselects through | `0x00DE4938` (`0x006A99CB` / `0x006A9D9C`) |
