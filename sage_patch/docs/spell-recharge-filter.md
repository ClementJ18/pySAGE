# Forcing the recharge discount onto named special powers

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); file offset is
`VA - 0x400000` for everything cited here. Read from the repo's own `game.dat` (11,346,944 bytes).

**Verdict up front: this is much cheaper than it looks, because all three modules meet in one
function.** `SpellRechargeModifierUpgrade`, `CurseSpecialPower` and
`SpecialPowerTimerRefreshSpecialPower` do not each own a copy of the recharge maths — every one of
them ends up inside `SpecialAbilityUpdate::startPowerRecharge` at `0x00896e31`, and
`RESPECT_RECHARGE_TIME_DISCOUNT` is tested at **exactly one instruction in the whole binary**
(`0x00896eba`). There is no second gate to find and no enum to grow.

The awkward part is not the gate, it is the plumbing behind it:

- **`SpellRechargeModifierUpgrade` collapses to a single float on the Player** (`Player+0x718`).
  By the time the gate runs, the engine cannot tell *which* upgrade granted the discount, so a
  filter stored on that module's `ModuleData` cannot be consulted at the point of use without new
  player-side state. See [The one design decision](#the-one-design-decision).
- **Two paths already ignore the flag entirely** — `SharedSyncedTimer = Yes` powers, and any
  `RECHARGE_TIME` attribute modifier. Part of what is being asked for already exists, for a subset
  of powers. See [Two paths that already ignore the flag](#two-paths-that-already-ignore-the-flag).

- **Cost:** 3 imm32 repoints + ~150 bytes of cave. No structure grows, no ctor/dtor changes.
- **Risk:** low. Omitting the keyword leaves the binary behaviourally identical.
- **Status:** **scoped, not built.**

## The choke point

`SpecialAbilityUpdate::startPowerRecharge` — `0x00896e31`, `__thiscall`, `ret 4`, one `float`
argument. It is an adjustor thunk on the `SpecialPowerModuleInterface` subobject at `module+0x10`:
`ecx-0xc` is the `ModuleData`, `ecx-8` is the `Object`. Its address appears in **23 module
vtables**, always at interface slot `+0x3c`.

Annotated, with the parts that matter:

```
00896e31  push ebp / mov ebp,esp / sub esp,0xc
00896e3b  mov  edi, [esi-0xc]          ; ModuleData
00896e3e  cmp  dword [edi+8], 0        ; SpecialPowerTemplate - bail if unset
00896e49  mov  ebx, [esi-8]            ; Object
00896e56  call 0x68b678                ; Object::getControllingPlayer -> [ebp-4]
00896e6c  call 0x688d3c                ; template -> final override
00896e71  cmp  byte [eax+0x59], 0      ; SharedSyncedTimer
00896e75  je   0x896e87
00896e7a  call 0x6ad1b0                ;   Yes -> Player-side shared timer, RETURNS (see below)
00896e87  movss xmm0, [0xbd1908]       ; 1.0f
00896ea0  call 0x68c82d                ; attribute-modifier bonus 0xc (RECHARGE_TIME) -> [ebp-0xc]
00896ea5  movss xmm0, [0xbd1908]       ; [ebp-8] = 1.0
00896eb5  call 0x688d3c                ; template -> final override
00896eba  mov  eax, [eax+0x18]         ; SpecialPowerTemplate.Flags
00896ebd  shr  eax, 5                  ;   <-- THE GATE
00896ec0  test al, 1                   ;   bit 5 = RESPECT_RECHARGE_TIME_DISCOUNT
00896ec2  je   0x896ed5                ;   not set -> multiplier stays 1.0
00896ec7  call 0x6aaad2                ; fld [Player+0x718]
00896ecc  fadd [0xbd1908]              ; + 1.0
00896ed2  fstp [ebp-8]                 ; multiplier = 1 + playerModifier
00896ee3  mov  eax, [eax+0x20]         ; SpecialPowerTemplate.ReloadTime (frames, int)
00896ef6  fmul [ebp-8]                 ;   * discount multiplier
00896ef9  fmul [ebp-0xc]               ;   * RECHARGE_TIME attribute modifier
00896efc  call 0xa3cfa4                ; ftol -> edi, clamped to >= 1
00896f10  comiss xmm0, [ebp+8]         ; 1.0 vs the float argument
00896f14  jbe  0x896f75                ;   arg >= 1.0 -> full recharge
                                       ;   arg <  1.0 -> partial recharge from the remaining time
00896f7f  mov  [esi+8], eax            ; readyFrame = TheGameLogic.frame + frames
```

`0x00896ebd..0x00896ec2` is why a naive `test byte [eax+0x18], 0x20` scan of `.text` finds nothing:
the compiler emitted `shr`/`test al,1` instead. A scan for that shape across the whole `.text`
(2.7 M instructions, resilient linear sweep) returns two hits, and the other one
(`0x007fc508`) reads an `AudioEventRTS`, not a template. **`0x00896eba` is the only consumer of
`RESPECT_RECHARGE_TIME_DISCOUNT` in the binary.**

### The flag is bit 5

`SpecialPower`'s `Flags` field is a 4-byte bitmask at `SpecialPowerTemplate+0x18`, parsed by
`0x0042e840` against the name table at `0x00da5f34`:

| bit | token |
|---|---|
| `0` | `NEEDS_TARGET` |
| `1` | `WATER_OK` |
| `2` | `NEEDS_OBJECT_FILTER` |
| `3` | `LIMIT_DISTANCE` |
| `4` | `NO_FORBIDDEN_OBJECTS` |
| `5` | **`RESPECT_RECHARGE_TIME_DISCOUNT`** |
| `6` | `PATHABLE_ONLY` |

Table index equals bit index, which the `shr eax,5` at the gate confirms independently.

`SpecialPowerTemplate` layout, the four members this document needs:

| offset | field |
|---|---|
| `0x10` | template name (`AsciiString`) — the key `findSpecialPowerTemplate` compares |
| `0x14` | shared-timer id |
| `0x18` | `Flags` |
| `0x20` | `ReloadTime` (frames, int) |
| `0x59` | `SharedSyncedTimer` |

The templates are heap objects owned by `TheSpecialPowerStore` (`[0x00de878c]`, a `vector<SpecialPowerTemplate*>`
at store `+0xc`/`+0x10`), **not** `.rdata`. `Flags` is writable at runtime.

## How each of the three modules reaches the gate

### `SpellRechargeModifierUpgrade` — it is not a filter, it is a scalar

Registered at `0x0065a227` (mask `0x8c`), `newModule` `0x00650104`, `newModuleData` `0x0065013c`
(`sizeof(ModuleData)` = `0x14c`), `ModuleData` ctor `0x008ba1ab`, `buildFieldParse` `0x008ba294`,
own field table `0x00c6f0d0`.

`Percentage` (`+0x138`) is **not a single number** — it is a `vector<float>` (`begin` at `+0x138`,
`end` at `+0x13c`), one entry per level, parsed by `0x008ba26f`. On activation
(`0x008ba05e`, `0x008ba139`):

```
008ba073  call 0x6aaae7            ; Player+0x71c--   (level counter)
008ba07a  call 0x6aaad9            ; eax = Player+0x71c
008ba083  dec  eax                 ; index, clamped into [0, size-1]
008ba0bb  fld  dword [ecx+eax*4]   ; Percentage[index]
008ba0c4  call 0x6aaaee            ; Player+0x718 = that float
```

| VA | what |
|---|---|
| `0x006aaad2` | `fld [Player+0x718]` — get the recharge modifier |
| `0x006aaaee` | `movss [Player+0x718], arg` — set it |
| `0x006aaad9` / `0x006aaae0` / `0x006aaae7` | get / inc / dec `Player+0x71c` |

`Player+0x718` is zeroed in the player reset at `0x006b045b` (`xorps xmm0,xmm0`). The whole feature
is therefore *one float per player*: `multiplier = 1.0 + Player+0x718`, so a player who never
researched anything gets `1.0` and is unaffected. **This is the fact that makes the cheap design
safe** (see below).

There are exactly four writers of `Player+0x718` and all four are in
`SpellRechargeModifierUpgrade`. There are two readers: the gate at `0x00896ec7`, and the
shared-timer path at `0x006ad20e`.

### `CurseSpecialPower` — it calls `startPowerRecharge` on every module of the victim

Registered at `0x0065aa9a` (mask `1`), `newModule` `0x00652cda`, `newModuleData` `0x00652d15`
(`sizeof` = `0xdc`), ctor `0x008d1192`, `buildFieldParse` `0x008d11c2`, field table `0x00c76440`
(`TriggerFX` `+0xd0`, `CursedFX` `+0xd4`, `CursePercentage` `+0xd8`, default `1.0`).

`doSpecialPower` (`0x008d134c`) runs a partition scan and calls `0x008d12e3` per candidate. That
function screens the victim (status bit `0x113:4`, not `KINDOF` 3 or 2, not `0x68d7ab`) and then:

```
008d1325  fld  dword [edi+0xd8]     ; CursePercentage
008d1331  call 0x68bdd0             ; Object::<curse all modules>
```

`0x0068bdd0` walks the victim's null-terminated module array at `Object+0x24c` and, for each
module `m`, calls `[[m+0xc] + 0xac](percentage)`. For `SpecialPowerTimerRefreshSpecialPower` that
slot is `0x006519af`:

```
006519af  fld  dword [esp+4]
006519b3  add  ecx, 4               ; m+0xc -> m+0x10 (SpecialPowerModuleInterface)
006519bc  call dword [eax+0x3c]     ; = 0x896e31, startPowerRecharge
```

So **Curse is `startPowerRecharge(CursePercentage)` applied to every special power the victim
owns** — and every one of those calls passes through the gate.

### `SpecialPowerTimerRefreshSpecialPower` — a one-name version of the feature already

Registered at `0x0065b4d4` (mask `0x100`), `newModule` `0x00654884` (`0x34` bytes), `newModuleData`
`0x0064d965` (`sizeof(ModuleData)` = `0x7c` — the plain `SpecialAbilityUpdateModuleData`, ctor
`0x00896834`), `buildFieldParse` `0x0089699b`, field table `0x00c64db0` (35 entries).

Its `doSpecialPower` is `0x00897987`:

```
008979b1  cmp  byte [ebx+0xc], 0    ; UpdateModuleStartsAttack
008979b5  jne  0x8979c5
008979bc  call dword [eax+0x3c]     ;   No -> startPowerRecharge(1.0) on ITSELF
008979c5  lea  esi, [ebx+0x6c]      ; OnTriggerRechargeSpecialPower
008979ca  call 0x401e64             ; isEmpty? -> done
008979d6  call 0x688d3c             ; own template; if its name matches the string, done
008979ed  mov  esi, [eax+0x24c]     ; else walk the object's module array
008979fc  call dword [edx+0x20]     ;   -> SpecialPower interface
00897a0a  call dword [edx+0x18]     ;   -> its SpecialPowerTemplate
00897a21  call 0x4065aa             ;   compare template+0x10 against the string
00897a35  call dword [eax+0x3c]     ;   match -> startPowerRecharge(1.0)
```

Note what this already is: **a name-matched special-power selector**, limited to exactly one name.
The requested filter is the plural of a mechanism the module already has.

That plural has since been built, for this keyword rather than for the discount:
[`trigger-recharge-list`](trigger-recharge-list.md) makes `OnTriggerRechargeSpecialPower` take any
number of names, by repointing the parse function at `0x00C64FA4` and the compare at `0x00897A21`.
It is not this feature - it changes *which powers this module recharges*, not which powers respect
a `SpellRechargeModifierUpgrade` - but it is the same function, and the two edits it makes are
disjoint from the ones scoped here.

### Two paths that already ignore the flag

Worth knowing before writing any bytes, because for some powers the feature is already shipped:

- **`SharedSyncedTimer = Yes`.** `0x00896e71` diverts to `Player::startSharedSyncedTimer`
  (`0x006ad1b0`) and returns. That function does `fild [tmpl+0x20]` / `fmul [Player+0x718]` at
  `0x006ad20e` with **no flag test at all**. The `cmp eax,edi / sbb / and` idiom at
  `0x006ad219..0x006ad222` reproduces `reload + modifier*reload`, i.e. the same
  `1 + modifier` scaling. So a shared-timer power respects the discount whether or not it is
  flagged.
- **`RECHARGE_TIME` attribute modifiers.** `0x00896ea0` fetches bonus type `0xc` (index 12 in the
  attribute-modifier enum = `RECHARGE_TIME`) into `[ebp-0xc]` and multiplies it in at
  `0x00896ef9`, unconditionally. A mod that can reach the object with an attribute modifier can
  already scale any power's recharge, flag or no flag.

## The one design decision

At the gate the engine holds the `Object`, its `Player`, and the `SpecialPowerTemplate` of the
power being recharged. It does **not** hold the `SpellRechargeModifierUpgrade` (or the Curse, or
the Refresh) that caused the discount — `Player+0x718` is a single float with no provenance. So a
filter written on those modules has to be turned into something the gate *can* see. Three ways:

**(a) Mark the templates at INI-parse time — recommended.** The keyword's parse function resolves
each name against `TheSpecialPowerStore` and sets bit 5 on the template there and then. Nothing is
stored in the `ModuleData`, nothing is read at runtime, the gate is untouched. This is exactly the
literal request — *"treat these powers as if they had `RESPECT_RECHARGE_TIME_DISCOUNT`"* — and it
costs three `imm32` repoints.

Its honest limitation: the mark is **global and permanent for the session**, not scoped to the
module that wrote it. If any object's `SpellRechargeModifierUpgrade` names `SpellBook_Sunflare`,
then `SpellBook_Sunflare` is discountable for every player. That is harmless in the common case
*because `Player+0x718` defaults to `0.0`*: a player with no recharge upgrade multiplies by `1.0`
and sees no change. It is not harmless in two cases, both worth a line in the modder docs:

  - two different upgrades with different power lists no longer distinguish themselves — the union
    applies to whoever has a modifier;
  - a **cursed** enemy who happens to own a recharge modifier now has the curse's reset scaled by
    their own discount on a force-marked power, where before it was not.

**(b) Runtime mark with a refcount.** Same field, but the mark is applied when the upgrade
activates (`0x008ba05e` / `0x008ba139`) and released when it deactivates, with a per-template
counter in the cave so overlapping upgrades nest. Scopes the change to "while somebody has this
upgrade" instead of "always", at the cost of a counter table and two more hooks. Still not
per-player. Do this only if (a) proves visibly wrong in play.

**(c) True per-player scoping.** Would need a set on `Player` — which means growing the `Player`
allocation, and then `Player::xfer` for savegames and replay determinism. That is a different
patch of a different size, and nothing above suggests it is worth it.

Take (a). It matches what was asked, it is the smallest thing that can possibly work, and (b) is a
strict superset that can be added later without redoing any of it.

## The recipe

Three `imm32` repoints and one cave section (`sage_patch.utils.allocate_section` /
`append_section`, the mechanism `.cahfac` already uses). **No `ModuleData` changes anywhere** — no
size bump, no ctor, no dtor, no relocated field table.

### 1. Give each module a second field table

`MultiIniFieldParse` (`0x0042b8d7`) is an array of up to **16** table pointers with a count at
`+0x80`; nothing inspects entry counts. The three modules currently register 2, 2 and 1 tables
respectively, so there is no need to relocate and grow the existing tables (all three of which are
boxed in by adjacent `.rdata` anyway — `0x00c6f0d0` ends at `0x00c6f110`, `0x00c76440` at
`0x00c76480`, `0x00c64db0` at `0x00c64ff0`, and a vtable starts at each of those addresses).
Instead, wrap each `buildFieldParse` and add one more table.

| module | `buildFieldParse` | `push` site | imm32 to patch | file off |
|---|---|---|---|---|
| `SpecialPowerTimerRefreshSpecialPower` | `0x0089699b` | `0x0064d99c` | `0x0064d99d` | `0x0024d99d` |
| `SpellRechargeModifierUpgrade` | `0x008ba294` | `0x00650176` | `0x00650177` | `0x00250177` |
| `CurseSpecialPower` | `0x008d11c2` | `0x00652d4f` | `0x00652d50` | `0x00252d50` |

Each site is `68 <imm32>` followed by `56 e8 …`; verify those two bytes before writing.

```asm
cave_bfp_<module>:
    mov  ecx, [esp+4]        ; MultiIniFieldParse*
    push 0                   ; offsetAdjust
    push cave_table
    call 0x42b8d7            ; MultiIniFieldParse::add, ret 8
    jmp  0x<original>        ; tail-call; it re-reads [esp+4] itself
                             ; 16 bytes each
```

All three wrappers point at **the same** `cave_table`, because the new parse function ignores its
`store` argument entirely:

```
{ "AffectedSpecialPowers", cave_parse_powers, 0, 0 }
{ NULL, NULL, 0, 0 }
```

32 bytes of table, 24 bytes for the name string, shared three ways.

### 2. The parse function

Standard `cdecl` field-parse signature `(INI* ini, void* instance, void* store, const void* userData)`.
It reads tokens to end of line, resolves each against `TheSpecialPowerStore`, and sets bit 5.

```asm
cave_parse_powers:
    push ebp
    mov  ebp, esp
.next:
    push 0
    mov  ecx, [ebp+8]              ; INI*
    call 0x42dbf5                  ; getNextTokenOrNull -> eax, NULL at end of line; ret 4
    test eax, eax
    je   .done
    mov  ecx, [0xde878c]           ; TheSpecialPowerStore
    test ecx, ecx
    je   .done
    push ecx                       ; reserve the by-value AsciiString slot
    mov  ecx, esp
    push eax
    call 0x4374e0                  ; AsciiString::AsciiString(const char*); ret 4
    mov  ecx, [0xde878c]
    call 0x69c146                  ; findSpecialPowerTemplate(AsciiString byval); ret 4
    test eax, eax
    je   .next
    mov  ecx, eax
    call 0x688d3c                  ; -> final override
    or   dword [eax+0x18], 0x20    ; RESPECT_RECHARGE_TIME_DISCOUNT
    jmp  .next
.done:
    pop  ebp
    ret                            ; ~48 bytes
```

Stack discipline, since it is the only thing here that can go wrong:

- `0x0042dbf5`, `0x004374e0` and `0x0069c146` are all callee-cleanup (`ret 4`). Verified from
  their stock call sites — `0x008d23c0` and `0x0073b22f` neither `add esp` nor reload after
  calling them, and `0x0073b22f` relies on `0x004374e0` restoring `esp` to the reserved slot so
  that `0x0069c146` finds its argument at `[esp+4]`.
- `push ecx` before `mov ecx, esp` is the ordinary MSVC "reserve four bytes" idiom; the pushed
  value is never read.
- The by-value `AsciiString` is consumed by `0x0069c146`'s `ret 4` and never destroyed, leaking
  one `AsciiStringData` refcount per token per INI load. **The stock `SpecialPowerTemplate` parse
  function at `0x0073b22f` leaks exactly the same way**, so this matches the engine rather than
  regressing it.

`0x0069c146` copies its argument and forwards to `0x007b1d07`, which linearly scans
`store[0xc]..store[0x10]` comparing `template+0x10` case-insensitively. Unknown names return
`NULL` and are silently skipped — consider emitting an INI warning instead, since a typo would
otherwise be invisible.

### 3. Nothing else

No hook at `0x00896eba`. No cave in the recharge path. The gate keeps testing the flag; the flag
is simply true for the named powers by the time any object exists.

### Cave budget

| block | bytes |
|---|---|
| `cave_parse_powers` | ~48 |
| 3 × `cave_bfp_*` | 48 |
| shared field table (2 × 16) | 32 |
| `"AffectedSpecialPowers\0"` | 24 |
| **total** | **~152** |

One `0x1000` section.

### Ordering — why parse time works

`SpecialPower` INI blocks are fully parsed before any `Object` block that references them. This is
not an assumption: the stock `SpecialPowerTemplate` keyword (`0x0073b22f`, used by
`SpecialAbilityUpdate.SpecialPowerTemplate` at `+0x8`) resolves eagerly through the same store and
stores a raw pointer, so if the order were the other way round every ability in the game would
fail to parse.

## What a mod then writes

```ini
Behavior = SpellRechargeModifierUpgrade ModuleTag_Recharge
  TriggeredBy            = Upgrade_LoreMaster
  Percentage             = -15% -25% -40%
  AffectedSpecialPowers  = SpecialAbilityHeal SpecialAbilityWordOfPower
End

Behavior = CurseSpecialPower ModuleTag_Curse
  SpecialPowerTemplate   = SpecialAbilityCurse
  CursePercentage        = 100%
  AffectedSpecialPowers  = SpecialAbilityHeal
End
```

The keyword is a **whitelist that widens**, never one that narrows: a power already carrying
`RESPECT_RECHARGE_TIME_DISCOUNT` behaves exactly as before, and omitting the keyword leaves the
binary bit-for-bit stock (no template is written, the gate reads the same flags it always did).

## Known rough edges

- **The keyword's effect is global, not per-module.** Covered above. The mitigating fact is that
  `Player+0x718` defaults to `0.0`, so a player without a recharge upgrade multiplies by `1.0`.
  This must be in the modder-facing docs, not just here.
- **Curse and Refresh get a widening, not a narrowing.** The literal request is satisfied
  (the named powers become discountable), but a modder who wants "this curse only affects *these*
  powers" needs a different patch: a cave replacing `call 0x68bdd0` at `0x008d1331` that walks
  `Object+0x24c` itself and name-matches before calling slot `+0xac`. That one **does** need
  storage in `CurseSpecialPowerModuleData`, which is packed solid to `0xdc`, so it also needs a
  size bump and ctor/dtor work. Out of scope here; worth its own doc if wanted.
- **Overrides.** `0x00688d3c` is the `getFinalOverride` chain and the cave writes through it, so
  the bit lands on whatever override is current at parse time. A `map.ini` override created
  *after* the object was parsed may or may not inherit `Flags`; check before relying on it.
- **`SharedSyncedTimer` powers do not need the keyword** and naming one is a no-op — that path
  never reaches the gate. Reject or warn at parse time rather than leaving a modder puzzled.
- **`ReloadTime` is an int frame count.** The result is floored (`0xa3cfa4`) and clamped to `>= 1`
  at `0x00896f03`, so very short powers cannot be discounted below one frame.
- **Conflicts.** Nothing in the current `PATCHES` registry touches
  `0x0064d99d`, `0x00650177`, `0x00652d50`, the three field tables, or `SpecialPowerTemplate`.
- **Verification.** A `sage-patch verify` pass should assert the three `push imm32` sites, the
  bytes `8b 40 18 c1 e8 05 a8 01` at `0x00896eba` (the untouched gate — if a future build changes
  it, the whole premise moved), and that `0x0089699b`, `0x008ba294` and `0x008d11c2` are each
  referenced exactly once.

## Appendix — every address this document depends on

| VA | meaning |
|---|---|
| `0x00401e64` | `AsciiString::isEmpty` |
| `0x0042b8d7` | `MultiIniFieldParse::add(table, offsetAdjust)`, `ret 8`, cap 16, count at `+0x80` |
| `0x0042dbf5` | `INI::getNextTokenOrNull(sep)` — `NULL` at end of line, `ret 4` |
| `0x0042dc9f` | `INI::getNextToken(sep)` — asserts instead of returning `NULL` |
| `0x0042e840` | `BitFlags` INI parse function (name table in `userData`) |
| `0x0042f6e0` | `operator new` |
| `0x004065aa` | `AsciiString::compareNoCase` |
| `0x004374e0` | `AsciiString::AsciiString(const char*)`, `__thiscall`, `ret 4` |
| `0x0064d965` | `SpecialPowerTimerRefreshSpecialPower` `newModuleData` (`0x7c`) |
| `0x0064d99c` | `push 0x89699b` — repoint site 1 |
| `0x00650104` / `0x0065013c` | `SpellRechargeModifierUpgrade` `newModule` / `newModuleData` (`0x14c`) |
| `0x00650176` | `push 0x8ba294` — repoint site 2 |
| `0x006519af` | thunk: interface slot `+0xac` → `startPowerRecharge` |
| `0x00652cda` / `0x00652d15` | `CurseSpecialPower` `newModule` / `newModuleData` (`0xdc`) |
| `0x00652d4f` | `push 0x8d11c2` — repoint site 3 |
| `0x0065a227` / `0x0065aa9a` / `0x0065b4d4` | the three `ModuleFactory::addModule` registrations |
| `0x00688d3c` | `Overridable::getFinalOverride` |
| `0x0068b678` | `Object::getControllingPlayer` |
| `0x0068bdd0` | walk `Object+0x24c`, call interface slot `+0xac` with a float — the curse fan-out |
| `0x0068c82d` | attribute-modifier bonus lookup (type `0xc` = `RECHARGE_TIME`) |
| `0x0069c146` | `SpecialPowerStore::findSpecialPowerTemplate(AsciiString)`, `ret 4` |
| `0x006aaad2` / `0x006aaaee` | get / set `Player+0x718`, the spell recharge modifier |
| `0x006aaad9` / `0x006aaae0` / `0x006aaae7` | get / inc / dec `Player+0x71c`, the level counter |
| `0x006ad1b0` | `Player::startSharedSyncedTimer` — applies the modifier **without** the flag test |
| `0x006ad20e` | `fmul [Player+0x718]` inside that path |
| `0x006b045b` | `Player+0x718 = 0.0` in the player reset |
| `0x0073b22f` | stock `SpecialPowerTemplate` INI parse fn — the idiom the cave copies |
| `0x007b1d07` | linear scan of the special-power store by name |
| `0x00896834` | `SpecialAbilityUpdateModuleData` ctor |
| `0x0089699b` | `SpecialPowerTimerRefreshSpecialPower` `buildFieldParse` |
| `0x00896e31` | **`SpecialAbilityUpdate::startPowerRecharge(float)`** — the choke point |
| `0x00896e71` | `SharedSyncedTimer` divert |
| `0x00896eba` | **the `RESPECT_RECHARGE_TIME_DISCOUNT` test — the only one in the binary** |
| `0x00896ec7` | `fld [Player+0x718]` |
| `0x00897987` | `SpecialPowerTimerRefreshSpecialPower::doSpecialPower` |
| `0x008ba05e` / `0x008ba139` | `SpellRechargeModifierUpgrade` activate / deactivate |
| `0x008ba1ab` / `0x008ba294` | its `ModuleData` ctor / `buildFieldParse` |
| `0x008ba26f` | its `Percentage` list parse function |
| `0x008d11c2` / `0x008d1192` | `CurseSpecialPower` `buildFieldParse` / `ModuleData` ctor |
| `0x008d12e3` | Curse per-victim screen, then `0x68bdd0` |
| `0x008d134c` | `CurseSpecialPower::doSpecialPower` |
| `0x00a3cfa4` | `ftol` |
| `0x00bd1908` | `1.0f` |
| `0x00c64db0` | `SpecialAbilityUpdate` field table (35 entries, ends `0x00c64ff0`) |
| `0x00c64ff0` | `SpecialPowerModuleInterface` vtable; `startPowerRecharge` at slot `+0x3c` |
| `0x00c6f0d0` | `SpellRechargeModifierUpgrade` field table (3 entries, ends `0x00c6f110`) |
| `0x00c76440` | `CurseSpecialPower` field table (3 entries, ends `0x00c76480`) |
| `0x00da5f34` | `SpecialPower.Flags` name table — index 5 is the flag |
| `0x00de412c` | `TheGameLogic` (frame counter at `+0x40`) |
| `0x00de878c` | `TheSpecialPowerStore` (template vector at `+0xc`/`+0x10`) |
