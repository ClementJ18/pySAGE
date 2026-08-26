# Turning into another unit when a `LifetimeUpdate` expires

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000` for everything cited here. Read from a clean `game.dat` (11,346,944 bytes) — not
from an install's patched copy.

**Verdict up front: the transform already exists and is already correct — it is just wired to a
special power.** `ToggleMountedSpecialAbilityUpdate`'s mount swap is a self-contained
`__thiscall` that reads *three fields* of its `ModuleData` and *two* of its module instance, and
calls nothing virtual on either. So a `LifetimeUpdate` can call it directly with its own
`ModuleData` and its own `Object`, and get the identical swap the mount button gets, with none of
the ability plumbing that can refuse to fire.

- **Cost:** 3 patch sites (one of them 5 bytes of whole instructions), 101 bytes of cave code, a
  144-byte scratch built on the stack, one new INI field on `LifetimeUpdate`,
  `sizeof(ModuleData)` `0x18` → `0xe8`. No reimplementation of the transfer — health, experience,
  team, position, facing, selection, hero slot, score bookkeeping and contained passengers all keep
  whatever the mount mechanic does with them today.
- **Risk:** *low-to-moderate*. The two functions it calls are stock and untouched, and the whole
  compatibility surface is `ModuleData+0xd8..0xe0`. The moderate half is that a `LifetimeUpdate`'s
  `ModuleData` is not a `ToggleMountedSpecialAbilityUpdate`'s, so the patch asserts a layout rather
  than a type, and one call happens a step earlier than it does in stock (§7).
- **Status:** **built** as `lifetime-fields`'s third keyword
  ([`patches/lifetime_fields.py`](../patches/lifetime_fields.py)), applying and verifying against a
  clean `game.dat`, with every site and anchor below asserted against it by
  [`tests/sage_patch/test_lifetime_fields.py`](../../tests/sage_patch/test_lifetime_fields.py).
  **Not runtime-verified.**

```
Behavior = LifetimeUpdate ModuleTag_Life
  MinLifetime        = 60000
  MaxLifetime        = 60000
  ExpirationTemplate = LothlorienGaladriel   ; become her instead of dying
End
```

## 1. What the mount mechanic actually is

`ToggleMountedSpecialAbilityUpdate` is a `SpecialAbilityUpdate` subclass registered at
`0x00659683` (interface mask 9), module `sizeof` `0x90` from the thunk at `0x0064f376`, module data
`sizeof` `0xe8` from `0x0064f3b1`. Its primary vtable at `0x00c6bda0` overrides ten of
`SpecialAbilityUpdate`'s slots (`0x00c563d0`); two of them matter.

| address | what |
|---|---|
| `0x008b1690` | slot 17 — the ability finishing. Reads `MountedTemplate`; **empty → the model-condition toggle, non-empty → the swap** |
| `0x008b140d` | **the swap** — create the replacement and move everything onto it |
| `0x008b12bf` | the `SynchronizeTimerOnSpecialPower` pass, called from the swap's tail |
| `0x008b125f` | slot 19 — later; if the swap flag is set, retires the old object by jumping to `0x008b1e9a` |
| `0x008b1e9a` | hide the drawable, drop it out of the UI, `GameLogic::destroyObject` |

The template lives at `ModuleData+0xd8` (`MountedTemplate`, `AsciiString`, parsed by `0x0042ee5e`)
and the power list at `+0xdc` (a vector, parsed by `0x0042eed6`).

### 1a. The swap, `0x008b140d`

```
008b1422  mov  eax, [edi+4]           ; ModuleData
008b142b  add  eax, 0xd8              ; &MountedTemplate
008b1434  call 0x006d1305             ; TheThingFactory->findTemplate  -- null -> 0x008b1681, no flag
008b1444  mov  edi, [edi+8]           ; the Object (this+8), from here on
008b1464  call 0x0068b678             ; Object::getControllingPlayer   -> ebx
008b1483  call [BuildAssistant+0x38]  ; 0x00797796 buildObjectNow(old, tmpl, &old->pos, angle, player)
008b1499  call 0x0079f0e1             ; ScoreKeeper::addObjectBuilt(old, -1)  -- un-count the old one
008b14ab  call 0x00436030             ; Object+0x88 -> new
008b14bd  call 0x005ea74e             ; Object+0x488 -> new
008b14e1  call 0x0079d8ef             ; health: new->body := old->body health, a guard byte +0x3c around it
008b150d  call [body+0xac]            ; experience: new := old, through Object+0x25c
008b151e  call 0x00670aa2             ; the new drawable, argument 10
008b1527  call 0x006aabb2             ; the player's slot for the old object; if != -1, name the new one
008b1560  call 0x006682b1             ; contain module
008b156d  call 0x0069954a             ; setTeam(new, old->m_team)  -- Object+0x31c
008b158e  call 0x0060a1d5             ; TheInGameUI: carry the selection across
008b15fa  call 0x008b12bf             ; SynchronizeTimerOnSpecialPower
008b1608  …                           ; the old contain module's passengers
008b167a  mov  byte [ebx+0x8c], 1     ; "the swap happened" -- this+0x8c
```

**What it touches of its own `this`:** `+0x04` (`ModuleData*`), `+0x08` (`Object*`), `+0x8c` (the
flag) — and nothing else. **No virtual call is made on `this`**, so it needs no vtable. The tail
call `0x008b12bf` reads `this+0x04` and `this+0x08` on the same terms and touches `ModuleData` only
at `+0xdc`/`+0xe0`, short-circuiting at `0x008b12d0` when those two are equal.

**What it touches of its own `ModuleData`:** `+0xd8` only, plus `+0xdc`/`+0xe0` through
`0x008b12bf`. `CancelDisguiseWhenDismounting` at `+0xd5` is read by `0x008b1690`, not by the swap.

### 1b. Retiring the old object, `0x008b1e9a`

```
008b1e9b  mov  esi, [ecx+8]            ; the Object -- the only thing it reads off `this`
008b1ea0  call 0x0068c18f
008b1ea7  call 0x0068c6ee
008b1ebb  call 0x0070e013 / 0x006718fb ; the drawable, hidden
008b1ed4  call 0x006e85fb              ; out of the UI (0x00de4b40 +0x10)
008b1ee0  call 0x0062bbab              ; TheGameLogic->destroyObject(old)
```

`destroyObject` (`0x0062bbab`) refuses an object already carrying `Object+0x94 & 1` and otherwise
walks its module list — it is the deferred retire, not a kill, so no death FX, no
`SlowDeathBehavior`, no `CreateObjectDie`, and nothing scores.

## 2. Where `LifetimeUpdate` decides to die

`LifetimeUpdate::update` is `0x007a7f8b` and is described in full in
[`lifetime-extend-upgrade.md`](lifetime-extend-upgrade.md) §1: the module sleeps to an absolute
death frame and this function runs once, on it. Its shape:

```
007a7f90  mov  ebx, [ecx-0x0c]        ; ModuleData
007a7f94  mov  edi, [ecx-0x08]        ; Object
007a7f97  push 0x9a / call 0x0046e918 ; THROWN_PROJECTILE -> return 1, come back next frame
007a7faf  cmp  byte [ebx+0x11], 0     ; ScoreKill
007a7fb3  push esi
007a7fb4  je   0x007a7ff1             ;   No  -> suppress the owner's "unit lost", addObjectBuilt(-1)
   …                                  ;   Yes -> credit the kill to the producer
007a8026  push [ebx+0x14]             ; DeathType
007a8029  mov  ecx, edi
007a802b  push 8 / call 0x00698ec3    ; Object::kill
007a8032  mov  eax, 0x3fffffff
```

**The hook goes at `0x007a7faf`, not at the kill**, and the five bytes there are two whole
instructions (`80 7b 11 00` + `56`). Two reasons, and the second is the one that matters:

- `ebx` and `edi` are already the `ModuleData` and the `Object`, and the `THROWN_PROJECTILE` guard
  above has already run — a projectile in flight still gets its stock reprieve.
- **The `ScoreKill = No` arm double-counts.** It calls `ScoreKeeper::addObjectBuilt(obj, -1)` at
  `0x007a8017`, and the swap calls the same function on the same object at `0x008b1499`. Hooking at
  the kill leaves both, so every transform walks the owner's "units built" counter down by one.
  Hooking at `0x007a7faf` skips the arm entirely and lets the swap do the one decrement it means to
  do.

`0x007a8038` is the epilogue *before* `pop esi`, which is where the `THROWN_PROJECTILE` arm returns
through — so the transform path returns the same way and never pushes `esi`.

## 3. The `ModuleData` is the whole trick

The swap wants an `AsciiString` at `+0xd8` and a vector at `+0xdc`. `LifetimeUpdate`'s `ModuleData`
is `0x18` bytes with five fields, and its allocation thunk `0x0064e08b` is its own — the same
single-caller thunk [`lifetime-extend-upgrade.md`](lifetime-extend-upgrade.md) §6 already grows.
Grow it to `0xe8` — exactly `ToggleMountedSpecialAbilityUpdate`'s size — zero everything past
`0x18`, and put the new keyword's row at offset `0xd8` with the engine's own `AsciiString` parse
function. The result is a `ModuleData` **byte-compatible with what the swap reads**, for one row of
table and no cave code:

```
LifetimeUpdate ModuleData   +0x08  MinLifetime          (stock)
                            +0x0c  MaxLifetime          (stock)
                            +0x10  WaitForWakeUp        (stock)
                            +0x11  ScoreKill            (stock)
                            +0x14  DeathType            (stock)
                            +0x18  ExtendedByUpgrades   36 dwords, the upgrade extension
                            +0xa8  UpgradeLifetimeBonus            the upgrade extension
                            +0xd8  ExpirationTemplate   AsciiString, this patch
                            +0xdc  (zero)               reads as an empty vector -- §9
                            sizeof = 0xe8
```

Zeroing is not tidiness: `LifetimeUpdate`'s constructor writes only its own five fields, so without
it every `LifetimeUpdate` in the game that does not declare the keyword would hand the swap
whatever the allocator returned. `operator new` at `0x0042f6e0` does not zero.

The **module instance** cannot be reused the same way — the swap writes its flag at `this+0x8c` and
`LifetimeUpdate`'s instance is `0x2c` bytes. That is what the 144-byte scratch is for: two pointers
and a byte, filled in immediately before the call. It lives on the **stack**, not in the cave, so
there is no shared buffer to reason about and no writable section to ask for.

## 4. What the transform carries, and what it does not

Everything in §1a, for free — and the two that will surprise a modder, stated plainly:

- **Health is absolute, not proportional.** `0x008b14d8` loads `old->body[+0x10]` and hands that
  number to the new body. A 3000 HP temporary form reverting into a 1500 HP hero arrives at full
  health (the setter clamps); the other direction arrives at half. That is the mount semantic and
  this patch does not change it — a `TransferHealthAsPercent` keyword is a v2 question.
- **Ability cooldowns do not carry**, because `+0xdc` is a zeroed empty vector and `0x008b12bf`
  short-circuits. In the data this replaces, `SynchronizeTimerOnSpecialPower` is exactly what
  carries them. Exposing it is one more table row at `+0xdc` and zero cave code — but see §9.

Experience and level do carry, which is what makes this usable on heroes.

## 5. The recipe

Three sites, one cave section (`sage_patch.utils.allocate_section`).

| # | site | stock bytes | what |
|---|---|---|---|
| 1 | `0x0064e096` | `56 6a 18 e8 42 16 de ff` | `sizeof(ModuleData)` `0x18` → `0xe8`, and zero what it added (52 dwords) |
| 2 | `0x007a7e00` | `68 60 18 c3 00` | `push` the rebuilt field table (in place) |
| 3 | `0x007a7faf` | `80 7b 11 00 56` | the transform, ahead of the scoring arm and the kill |

```asm
cave_expire:                       ; site 3. ebx = ModuleData, edi = Object, esi not yet pushed
    lea  ecx, [ebx+0xd8]           ;   &ExpirationTemplate
    call 0x00401e64                ;   AsciiString::isEmpty -> al  (1 when there is no template)
    test al, al
    jne  .stock
    sub  esp, 0x90                 ;   the module-shaped scratch, on the stack
    mov  [esp+0x04], ebx           ;   ModuleData ...
    mov  [esp+0x08], edi           ;   ... Object ...
    mov  byte [esp+0x8c], 0        ;   ... and the flag the swap sets on success
    mov  ecx, esp
    call 0x008b140d                ;   the mount swap, verbatim
    cmp  byte [esp+0x8c], 0
    je   .abort                    ;   no such template, or the build refused -> die as stock
    mov  ecx, esp
    call 0x008b1e9a                ;   hide, deselect, destroyObject(old)
    add  esp, 0x90
    mov  eax, 0x3fffffff
    jmp  0x007a8038                ;   pop edi / pop ebx / leave / ret -- esi was never pushed
.abort:
    add  esp, 0x90
.stock:
    push esi                       ;   the displaced pair, in the other order: push sets no flags
    cmp  byte [ebx+0x11], 0
    jmp  0x007a7fb4
```

`mov eax, 0x3fffffff / jmp 0x007a8038` is the same "sleep forever" the stock kill returns, through
the same epilogue. The scratch is `0x90` bytes because that is
`ToggleMountedSpecialAbilityUpdate`'s own `sizeof`, so the flag at `+0x8c` lands inside it; only
those three slots are ever touched, so nothing has to be zeroed and whatever the stack held is
never read. On the stack rather than in the cave, it needs no writable section and cannot be shared
between two transforms — which is what makes the reentrancy question in §9 moot rather than merely
unlikely.

**The stack has to be balanced before the exit**, and both arms do it: `0x007a8038` pops `edi` and
`ebx` before its `leave`, so a scratch still standing there would hand `update`'s caller two words
of garbage. The `.stock` arm is reached without the `sub` on the no-keyword path and with a
matching `add` on the abort path, so an object with no template never moves `esp` at all.

**Cave budget, as built:** 101 (expire) beside `lifetime-fields`'s other four stubs (221 bytes),
144 (nine rows and the terminator) and 59 (the three keyword strings) = **526 bytes** including
alignment. One `0x1000` section.

An object that does not declare the keyword pays one `AsciiString::isEmpty` — two compares — once,
on the frame it dies. Everything else about it is byte-identical to stock.

## 6. It is one patch with the upgrade extension

Sites 1 and 2 are also the extension's: `ExtendedByUpgrades` grows the same `ModuleData` at the
same eight bytes and rebuilds the same field table behind the same `push`. There is no version of
this that is a separate patch and still obeys the repo's second and third composition rules — two
patches adding keywords to one INI block compete for one table pointer, and `apply_byte_patch`
raises on whichever runs second. So `LifetimeUpdate`'s `ModuleData` and field table have **one
owner**, [`patches/lifetime_fields.py`](../patches/lifetime_fields.py), and each keyword is armed
by its own declaration:

| keyword | arms | costs when absent |
|---|---|---|
| `ExtendedByUpgrades` / `UpgradeLifetimeBonus` | the per-frame poll and the extension at `update`'s entry | one 36-dword scan on the frame the object dies |
| `ExpirationTemplate` | the transform at `0x007a7faf` | one `AsciiString::isEmpty` on the same frame |

The layout composes without anything moving: the mask at `0x18`, the bonus at `0xa8`, the template
at the `0xd8` the swap fixes, and the vector behind it — `0xe8` in total, which is
`ToggleMountedSpecialAbilityUpdate`'s own `sizeof` and therefore exactly the size that makes the
`ModuleData` readable by the code this patch borrows.

## 7. Properties

- **Determinism.** This changes *which objects exist*, which is logic-side and CRC'd. **Every peer
  must run the same patched binary**, and replays do not cross — the same rule as
  `lifetime-fields`.
- **The keyword is fatal on a stock build**, like every keyword in this package: SAGE treats an
  unknown field in a known block as a parse error.
- **Savegames need no version bump.** `ModuleData` is template data and is never xfer'd; the
  transform itself creates and destroys objects, which the save path already handles.
- **The swap and the retire happen in one call**, where stock splits them across the ability's
  unpack and pack steps (`0x008b1690`, then `0x008b125f`). Nothing in `0x008b140d` defers work to
  the old object, and `destroyObject` is itself deferred to the end of the frame — but this is the
  one place the patch does something the engine does not currently do, and it is the first thing to
  watch in a live test.
- **No death.** The old object is retired, not killed: no `DeathType`, no death FX, no
  `SlowDeathBehavior`, no `CreateObjectDie`, nothing scored. `DeathType` on a `LifetimeUpdate` that
  declares `ExpirationTemplate` becomes dead data and `ScoreKill = Yes` becomes unreachable — worth
  a `sage_lint` rule rather than an engine check.
- **The in-world timer is unaffected**, and now means what a player already reads it as: the bar
  drains to the transform instead of to a death.
- **Composition.** Order-independent. No other bundled patch touches `LifetimeUpdate`,
  `ToggleMountedSpecialAbilityUpdate`, `BuildAssistant`'s slot 14 or `GameLogic::destroyObject`,
  and the three keywords that do share those bytes share a patch (§6).
- **`sagepatch` surface.** `FieldDelta("LifetimeUpdate", keyword, "Ref:objects", None, …)` — the
  grammar already spells a single cross-reference, so unlike `Ref[]:` this costs `sage_ini`
  nothing.
- **CLI.** `--template-keyword NAME` (default `ExpirationTemplate`), validated against the five
  stock keywords and against the other two the patch adds, the way the existing options are.

## 8. What it replaces in the data

The pattern this is for, from Edain's `LothlorienGaladrielGood`
(`object/goodfaction/units/lothlorien/lothloriengaladriel.ini:2414`): a temporary Ring form that is
supposed to revert. Four modules, two of which exist only to press a hidden button:

```
Behavior = LifetimeUpdate ModuleTag_HatchTrigger
    MinLifetime = #ADD( GALADRIEL_TRANSFORMATION_TIME_GOOD 6000 )
    MaxLifetime = #ADD( GALADRIEL_TRANSFORMATION_TIME_GOOD 6000 )
End
Behavior = SpecialPowerModule ModuleTag_RingannehmenStarter …
Behavior = ToggleMountedSpecialAbilityUpdate ModuleTag_Ringannehmen
    SpecialPowerTemplate = SpecialAbilityGandalfVerfuhrte
    MountedTemplate      = LothlorienGaladriel
    …
End
Behavior = DoCommandUpgrade Module_DoCommandUpgradeRingannehmen3
    TriggeredBy                 = Upgrade_DisMountAI
    GetUpgradeCommandButtonName = Command_SpecialAbilityGandalfVerfuhrte
End
Behavior = ObjectCreationUpgrade MakeTheFreeTreb3
    TriggeredBy   = Upgrade_ElfFaction
    GrantUpgrade  = Upgrade_DisMountAI
    Delay         = GALADRIEL_TRANSFORMATION_TIME_GOOD
End
```

The `6000` is the tell: six seconds of slack between when the button is pressed and when the
`LifetimeUpdate` gives up and kills her. The button is a special power, so it can be refused — and
when it is, the timer is the thing that runs out. With the keyword, the whole contraption is one
module and the failure mode does not exist:

```
Behavior = LifetimeUpdate ModuleTag_HatchTrigger
    MinLifetime        = GALADRIEL_TRANSFORMATION_TIME_GOOD
    MaxLifetime        = GALADRIEL_TRANSFORMATION_TIME_GOOD
    ExpirationTemplate = LothlorienGaladriel
End
```

**Two objects use the button trick today** — `LothlorienGaladrielGood` and
`LothlorienGaladrielEvil`. That is the population the patch *fixes*. The population it *opens up*
is larger: **20 objects carry both a `LifetimeUpdate` and a `ToggleMountedSpecialAbilityUpdate`**,
and **33 carry both a `LifetimeUpdate` and a `DoCommandUpgrade`** — summoned heroes, temporary
hordes and creep forms that today can only expire by dying. Counted over the Edain tree at
`Documents/Edain/Edain-Mod/_mod/data/ini`, per object block including `ChildObject`.

`ExpirationTemplate` appears in no `.ini` in that tree and in none of the install's `.big` archives,
so a mod adopting the default is adding a name, not shadowing one.

## 9. Open questions and what needs a live test

- **The one-call ordering** (§7). Stock puts a pack step between the swap and the retire; this puts
  nothing. Watch for the old object's drawable surviving a frame, and for anything in
  `0x008b140d`'s contain-transfer tail that assumes the old object is still selectable.
- **A zeroed vector at `+0xdc` is read, never written — keep it that way in v1.** `0x008b12bf`
  compares `[+0xdc]` against `[+0xe0]` and does nothing when they match, so all-zero is safe to
  *read*. Exposing `SynchronizeTimerOnSpecialPower` means letting `0x0042eed6` *append* to a vector
  that `LifetimeUpdate`'s constructor never constructed — `0x0042ca04` and `0x0042e59e` would have
  to be checked against `{0,0,0}` first. Cooldown carry-over is the one thing the data in §8 loses,
  so this is the first v2 item, not a nice-to-have.
- **Hordes.** `buildObjectNow` (`0x00797796`) has a distinct arm for horde templates
  (`ThingTemplate+0x109 & 0x40`, going through the contain module's vtable `+0x1f8`), and four of
  the 20 objects in §8 are hordes. Untested here; the swap is the stock path, but no mount in the
  shipped data is a horde, so this arm may never have run under a `MountedTemplate`.
- **A contained or garrisoned unit.** Unknown whether the transform is safe for an object inside a
  transport or a building at the moment it expires. `0x008b1690` gates the stock swap behind an
  ability that would itself have been refused in most of those states; this patch has no such gate,
  which is the point of it and also its sharpest edge.
- **Recursion.** Two templates each naming the other in `ExpirationTemplate` ping-pong forever.
  That is a mod's business, not a crash, but a `sage_lint` cycle check would be cheap.
- **Not runtime-verified.** The patch applies and verifies against a clean `game.dat` and every
  site and anchor is asserted against it, but a patch is a reading of the machine code and its
  tests are written from the same reading. Only the running game disagrees.

## 10. Verification notes

Read directly from a clean `game.dat` and reproducible from the addresses above: the module
registration at `0x00659683` and its two factory thunks; the vtable diff of `0x00c563d0` against
`0x00c6bda0` that names the ten overrides; `0x008b140d` in full, including that its only uses of
`this` are `+0x04`, `+0x08` and `+0x8c` and that it makes no virtual call on it; `0x008b12bf`'s
`+0xdc`/`+0xe0` short-circuit; `0x008b1e9a`'s single use of `[ecx+8]`; the `MountedTemplate` and
`SynchronizeTimerOnSpecialPower` rows at `0x00c05a48` and `0x00c05a58` with their offsets `0xd8`
and `0xdc` and parse functions `0x0042ee5e` and `0x0042eed6`; `AsciiString::isEmpty` at
`0x00401e64` returning 1 for a null buffer or a zero length word; `0x008b140d` having exactly one
caller and `0x008b1e9a` exactly two; `LifetimeUpdate`'s field table at `0x00c31860` (five rows) and
its single reference at `0x007a7e01`; `LifetimeUpdate::update` in full, its two convergent scoring
arms, the five bytes at `0x007a7faf` and the epilogue at `0x007a8038`; and
`GameLogic::destroyObject` at `0x0062bbab` with its `Object+0x94 & 1` guard.

Every site and every anchor above is asserted against a clean `game.dat` by
[`tests/sage_patch/test_lifetime_fields.py`](../../tests/sage_patch/test_lifetime_fields.py)
(`TestInstalledBinary`, skipped where the binary is absent), and the expiry stub is disassembled
back and checked instruction by instruction against what §5 says it does — the flag cleared before
the swap and read after it, both calls made on the scratch, the stack balanced on all three arms,
and the displaced pair re-executed with the compare last.

The `0x0079f0e1` double-decrement in §2 is read from two call sites, not observed.

The data figures in §8 are counted over the Edain tree, per object block, not estimated.
