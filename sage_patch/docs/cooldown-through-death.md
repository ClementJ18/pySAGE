# Carrying a special-power cooldown through a hero's death

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); file offset is
`VA - 0x400000` for everything cited here. Read **statically** on 2026-08-17 from the stock
`game.dat` in this repo (11,346,944 bytes) with `pefile` + `capstone`, cross-checked against the
mod's own `__edain_data.big`. **Nothing below has been observed in a running game** - §9 is open.

**The request.** A hero who casts a power and dies at 50% of its cooldown should come back at 50%,
not with the power ready. Opt in per power with a bool on the `SpecialPower` block, plus a second
bool for whether the cooldown keeps *elapsing* while the hero is dead - so a hero dead long enough
returns with the cooldown gone.

**Verdict up front: the premise is half true, and which half decides the whole patch.** A hero has
**two** ways back from death and they differ in object identity:

| | how the hero returns | the `Object` | cooldowns today |
|---|---|---|---|
| **Path A** | `RespawnUpdate` respawns in place (`RespawnRules AutoSpawn:Yes`) | **the same one**, teleported to the respawn point | **already survive, and already tick while dead** |
| **Path B** | the player pays at the citadel; `ReviveMgr::reviveHero` fields the hero | **a brand-new one**, from the `ThingTemplate` | **lost with the old object** |

Path B is how a `Command = REVIVE` hero comes back - which is every recruitable hero in Edain (see
[`ai-revive-gate.md`](ai-revive-gate.md)) - so it is the path the request is about. The engine
already carries experience, level, the upgrade mask and two more object fields across that gap, from
a snapshot taken at death; **this patch adds cooldowns to a list the engine already maintains**,
rather than inventing one.

- **Cost:** 2 hooks (10 bytes) + 3 single-bit opcode widenings + 2 imm32 repoints for a relocated
  field table + a `0x6486`-byte cave, most of it the state table. Two new INI keys.
- **Risk:** low-medium. Nothing grows an engine structure; the failure mode is a wrong cooldown on
  a revived hero, not a crash. The one real cost is that the store is not in a savegame (§4.3).
- **Status: implemented as `cooldown-through-death`**
  ([`../patches/experimental/cooldown_through_death.py`](../patches/experimental/cooldown_through_death.py)),
  and **experimental**: it applies to and verifies against the real `game.dat`, it composes in
  either order with `hero-mana`, `recharge-rescale` and `queue-ignore-cp`, and every address here
  holds its stock bytes in the shipped binary - but it has never been in a running match. See
  [`../patches/experimental/`](../patches/experimental/) for what that promises and what it does
  not. Where the build departed from this scope, §10 says so and why.

## TL;DR

- **A cooldown is two fields on the module**, `duration` at interface `+0x04` and the absolute
  `readyFrame` at `+0x08`, and a correct restore must write **both** - the button clock is
  `1 - (readyFrame - now) / duration`. [`recharge-rescale.md`](recharge-rescale.md) §1 maps them.
- **Nothing in the death or respawn path resets a cooldown.** `setReadyFrame` (interface slot
  `+0x20`) has exactly two users in the whole binary: the script engine's special-power actions, and
  `HeroDie::onDie` - which clears **one** named power, the ini comment for which reads *"the special
  power that I recharge by dying"*. §1.4.
- **Path B loses cooldowns because it builds a new object**, not because anything clears them.
  `ReviveMgr::reviveHero` (`0x0078142F`) calls `TheThingFactory`'s `newObject` at `0x007814C2` and
  then re-applies a record written at death. §1.3.
- **The two modes are one storage decision, not two mechanisms.** Snapshot `(readyFrame, duration,
  deathFrame)`; at revive, `CooldownTicksWhileDead = No` writes `now + (readyFrame - deathFrame)`
  and `Yes` writes `readyFrame` unchanged - so "dead long enough clears it" is the *absence* of
  arithmetic, and needs no timer of its own. §3.2.
- **The INI surface is almost free.** `SpecialPowerTemplate` is `0x88` bytes with **two unused
  padding bytes at `+0x5A`/`+0x5B`**, wedged between the `PublicTimer` and `SharedSyncedTimer`
  bools and the next dword. The ctor leaves them uninitialised; widening one `mov byte` to a
  `mov dword` (`88` -> `89`, one byte, same length) zeroes both, and the same trick on the
  copy-from-default makes them inherit. §2.
- **Both hook sites are whole `call rel32` in the engine's own snapshot/restore code**, five bytes
  each, with the object already in a register at both. §5.
- **This is simulation state.** `readyFrame` gates whether an ability can fire, so every peer needs
  the patched binary and replays will not cross.

## 1. What actually happens when a hero dies

### 1.1 Where a cooldown lives

Unchanged from [`recharge-rescale.md`](recharge-rescale.md) §1, restated because the restore has to
write it: `SpecialPowerModuleInterface` sits at module `+0x10`, and

| interface offset | field |
|---|---|
| `+0x04` | **duration** - the length of the cooldown that was started, in frames |
| `+0x08` | **readyFrame** - absolute logic frame at which the power is ready |
| `+0x0C` | pause count |
| `+0x10` | frame the pause began |

`startPowerRecharge` (`0x00896E31`, in 23 module vtables at interface slot `+0x3C`) writes
`readyFrame` at `0x00896F70`/`0x00896F8B` and `duration` at `0x00896F8B`. `isReady` (`0x00896C72`)
and `getPercentReady` (`0x00896CF2`) recompute from those two on every call and cache nothing, so a
patch that keeps them mutually consistent needs no UI work at all.

### 1.2 Path A - `RespawnUpdate` keeps the object

`RespawnUpdate` (name string `0xC0B098`, registered at `0x0065A002`: `newModule` `0x0064F68C`,
`newModuleData` `0x0064F6C4`, module `0x44` bytes, `ModuleData` `0x120`, field table `0xC6CE80` -
`DeathAnim`, `RespawnAnim`, `RespawnRules`, `AutoRespawnAtObjectFilter`, `RespawnAsTemplate`) drives
death and in-place respawn from a state field at module `+0x2C`.

Its die handler (`0x008B37B0`..`0x008B389D`) plays `DeathAnim` (`0x005E3BA5` on `ModuleData+0x0C`)
and `DeathFX` (`0x004B1B5A` on `ModuleData+0xF0`), calls `Object::setEffectivelyDead(TRUE)`
(`0x0068D950`, which sets bit 0 of `Object+0x458`), and registers the hero with the player's revive
manager. **It never destroys the object.**

`RespawnUpdate::update` (`0x008B3A35`, interface vtable `0xC6C354` slot 0) then, in state 3,

```
008b3b08  push [module+0x30] / ecx = TheGameLogic / call 0x449681   ; the respawn-at object
008b3b44  copy that object's [+0x38..+0x40] over its own position
008b3b6f  call 0x697f0f                                            ; move THIS object there
008b3b7c  call 0x5e3ba5                                            ; RespawnAnim
008b3bbe  [Object+0x25c] vtable +0x58                              ; Body: restore health
008b3bb7  state = 4
```

so the hero that comes back **is the object that died**, teleported to the keep with its health
restored. Every module on it, including every `SpecialPowerModule`, still holds exactly the state it
held when the hero fell. Because `readyFrame` is an absolute frame and the logic clock never
stopped, a Path-A hero already returns with the cooldown where it would have been had they lived.
**For Path A the request is already implemented, in the "ticks while dead" flavour.** §7.1 says what
it would cost to make the other flavour true there too.

### 1.3 Path B - `ReviveMgr::reviveHero` builds a new one

The player's revive manager lives at `Player+0x758` and holds a vector of **`0xE8`-byte records** at
mgr `+0x04`/`+0x08` (`getByIndex` `0x007808AB` divides by `0xE8`; `findByKey` `0x007808DB` matches
`record+0xB4`). Records arrive two ways: from a `ThingTemplate` at game start
(`0x00781801`, called at `0x006B17EA` and `0x008BC4F7` over the `PlayerTemplate`'s hero list) and
**from a live `Object` at death** (`0x00781792`, whose only caller in the binary is the die handler
above, at `0x008B3879`).

The record built from an object (`0x00780DD4`) is a snapshot, and its contents are the answer to
"what survives a hero's death":

| record offset | what | written by |
|---|---|---|
| `+0x00`/`+0x08`/`+0x0C`/`+0x10` | `RespawnUpdate` and experience-tracker readings | ctor |
| `+0x14`..`+0xA4` | a `0x90`-byte blob copied from `Object+0x28C` - the upgrade mask | `0x00444DB3` |
| `+0xA4` | revive cost for the hero's level | `0x008B3C07` |
| `+0xA8` | frame the revive was started; `-1` = not being revived | `0x007812F7` |
| `+0xAC` | revive time for the hero's level | `0x008B3C1C` |
| `+0xB4` | the production id, the key `reviveHero` and `cancelRevive` match on | `0x007812F7` |
| `+0xB8`/`+0xBC`/`+0xC0` | copies of `Object+0x47C`, `+0x480`, `+0x488` | ctor |
| `+0xD8` | **experience** | the die handler, `0x008B3897` |
| `+0xE4` | `AsciiString` - the hero's template name | ctor |

`ReviveMgr::reviveHero` (`0x0078142F`) then, when the production completes
(`ProductionUpdate`, `0x008A250A`):

```
0078147b  copy the record                                  ; 0x6e267e
0078148b  call 0x7806fa                                    ; record -> ThingTemplate
007814c2  ecx = TheThingFactory [0xde4a40] / call 0x6d165e  ; *** a brand-new Object ***
007814cf  call 0x696e63 / 0x68c17d                         ; place it, set its producer
007814e1  newObj[+0x480] = record copy
00781563  call 0x79d833  /  00781574 call 0x79d745         ; restore level and experience
00781592  call 0x68cc6c                                    ; restore the upgrade mask -> +0x28c
00781614  [its RespawnUpdate module +0x41] = ...
```

The old object is gone and the new one's modules are freshly constructed, so every `readyFrame` is
zero and every power is ready. That is the behaviour the request wants changed, and the shape of the
fix is already on the page: **one more field in the snapshot at `0x008B3897`, one more restore
beside `0x00781592`.**

### 1.4 The one thing that *does* clear a cooldown on death

Worth knowing before writing a byte, because it is easy to mistake for the defect. `HeroDie`
(name string `0xC0B960`; `newModule` `0x006515F9`, module `0x14` bytes, `ModuleData` `0x3C` with the
`SpecialPowerTemplate` at `+0x38`, registered at `0x006588B9` with die-module mask 2) is reached
from `Object::setEffectivelyDead` at `0x0068D9EA` and does exactly one thing (`0x008C64FE`):

```
008c650a  push ModuleData+0x38                 ; the named SpecialPowerTemplate
008c6514  call 0x6ababd                        ; iterate the player's objects with 0x8c642d
  -- per object (0x008C642D):
008c6440    call 0x68c26d                      ; Object::getSpecialPowerModule(template)
008c644f    push TheGameLogic.frame
008c6456    call [interface vtable + 0x20]     ; setReadyFrame(now) -> the power is ready NOW
```

which is what the mod's own comment describes - `SpecialPowerTemplate = SpecialAbilitySmite ;the
special power that I recharge by dying`. It is opt-in, per hero, for **one** power, and it applies
across every object the player owns.

Interface slot `+0x20` is `0x0099344A`, a folded `mov [ecx+8], eax; ret 4` that appears in 27
vtables. Of the 44 callers of `Object::getSpecialPowerModule` (`0x0068C26D`), exactly four go on to
call slot `+0x20`: `0x007C4993`, `0x007C4A0B` and `0x007C4A6E` (the script engine's special-power
actions) and `0x008C6440` (the above). **There is no third writer, and none of them is in the death
or respawn path.** The other "make ready" route - main-vtable slot `+0x30` (`0x00896F99`, which
writes `readyFrame = now` under four conditions), reached through behaviour-interface slot `+0xB0`
(`0x006519C2`) and the module fan-out `0x0068BDF9` - has exactly one caller in the binary
(`0x008C7B3B`, inside a special-ability module's own effect), and it is not death either.

So: **the cooldown is never reset on death. It is discarded with the object, on Path B only.**

## 2. The INI surface: two bools in padding

`SpecialPowerTemplate` is allocated at `0x007B2292` (`push 0x88`), constructed at `0x007B1F5B`, and
its field table - 24 entries at `0x00DA5FD8`, terminated at `0x00DA6158` - puts two `Bool`s side by
side and then a dword:

| offset | field | parse fn |
|---|---|---|
| `0x58` | `PublicTimer` | `0x0042E558` |
| `0x59` | `SharedSyncedTimer` | `0x0042E558` |
| `0x5A` | **free** | |
| `0x5B` | **free** | |
| `0x5C` | `PalantirMovie` (`AsciiString`) | `0x0042EE5E` |

`+0x5A`/`+0x5B` are interior padding. A scan of `.text` for byte accesses at displacement `0x5A`
returns 15 sites and none is in the special-power regions (`0x0073Bxxx`, `0x007B1xxx`, `0x00896xxx`,
`0x00991xxx`), so nothing reads them today.

### 2.1 They are not zeroed, and that is a one-byte fix

The ctor writes the two bools as **separate byte stores** and stops:

```
007b1fd0  885e58    mov byte [esi+0x58], bl     ; bl = 0
007b1fd3  885e59    mov byte [esi+0x59], bl
007b1fd6  895e5c    mov dword [esi+0x5c], ebx
```

so a new field at `+0x5A` would start as heap garbage - which would make the patch change behaviour
on data that never names the keyword, the one thing it must not do. Widen the first store to a dword
(`88` -> `89`, **same instruction length**) and `0x58`..`0x5B` are zeroed in one go; the second
store becomes redundant and is left alone. This is the trick `lifetime-extend-upgrade` uses and that
[`recharge-rescale.md`](recharge-rescale.md) §3.4 records for exactly this situation.

### 2.2 `DefaultSpecialPower` inheritance is two more bytes

The copy-from-default (`0x007B1E6C`, used at `0x007B22E4` when a block names one) is field-by-field
and copies the two bools as bytes:

```
007b1f00  8a4558    mov al, [ebp+0x58]     ->  8b4558    mov eax, [ebp+0x58]
007b1f03  884358    mov [ebx+0x58], al     ->  894358    mov [ebx+0x58], eax
007b1f06  8a4559    mov al, [ebp+0x59]         (now redundant, harmless)
007b1f09  884359    mov [ebx+0x59], al
```

Two single-bit opcode edits, both same-length, and `eax` is already the scratch register the
surrounding copies use. Without them the new keys simply do not inherit from a default block, which
is a defensible smaller patch but a surprise waiting for a modder.

### 2.3 The field table

Two `imm32` references, both to `0x00DA5FD8`:

| site | bytes | what |
|---|---|---|
| `0x007B1ABE` | `b8 d8 5f da 00` | the `getFieldParse` accessor at `0x007B1ABD` |
| `0x007B2325` | `68 d8 5f da 00` | pushed into `INI::initFromINI` (`0x0042DB80`) by the block parser |

Copy the 24 entries into the cave, append two, keep the NULL terminator, repoint both. `initFromINI`
walks to the terminator and nothing reads an entry count, so length is free. 27 entries is 432 bytes
plus two name strings.

```
{ "PersistCooldownOnDeath", 0x0042E558, 0, 0x5A }
{ "CooldownTicksWhileDead", 0x0042E558, 0, 0x5B }
```

`0x0042E558` is the engine's own `Bool` parse function, already used by the two neighbours, so
`Yes`/`No` parsing, error messages and `map.ini` overrides all come for free.

**Alternative considered and rejected:** a `Flags` token (bit 7; the name table is at `0x00DA5F34`
with 7 entries, and bits 7..31 are unused). It needs no template storage at all, but it means
relocating the name table, it reads as `Flags = PERSIST_COOLDOWN_ON_DEATH` rather than the bool the
request asks for, and one token cannot express the second knob. Padding is cheaper *and* closer to
what was asked.

**`sage_ini` / `sage_lint`.** The patch declares both keys in its `ini_surface()`, the way
`lifetime-extend-upgrade` declares its two:

```python
Engine(fields=(
    FieldDelta("SpecialPower", self.keyword, "Bool", False, self.name),
    FieldDelta("SpecialPower", self.tick_keyword, "Bool", False, self.name),
))
```

so `sage-patch sagepatch game.dat -o .sagepatch` writes them down and `sage-lint` stops calling them
unknown attributes. Both default `False`, which is stock behaviour, which is what makes them opt-in.

## 3. The design

### 3.1 Snapshot at death, restore at revive

Both ends are inside code the engine already runs for this exact purpose, with everything needed
already in registers.

**Snapshot**, in the die handler, at the call that puts the hero on the revive list:

```
008b3877  push eax                   ; the auto-spawn flag
008b3878  push ebx                   ; the dying Object
008b3879  call 0x781792              ; <- the 5 bytes taken; addHero(Object *, Bool), ret 8
008b387e  mov ebx, [ebx+0x26c]       ; ebx is still the Object here
008b3897  mov [eax+0xd8], ecx        ; the engine's own snapshot: the experience
```

**Scoped at `0x008B3897`, built at `0x008B3879`**, six instructions earlier. Three reasons, all
found by reading the window rather than the function: the object is *in a register* here (`ebx`,
on both sides of the call) instead of behind an assumption about module layout; the site is
exactly five bytes, so the hook needs no `nop`; and the two tests in between - that the hero has an
experience tracker, and that the record reads back - would otherwise decide silently which heroes
got a snapshot. The later site is not wrong, it is just narrower for no gain.

The cave performs the stock call, then walks the object's module array at `Object+0x24C` - the
NULL-terminated walk the curse fan-out uses (`0x0068BDD0`), reaching each module's special-power
interface through its own vtable (`[m+0xC]` slot `+0x20`, the idiom at `0x008979F5`) so no module
layout is assumed - and for every power that is **on cooldown and flagged** stores

```
key   = (player, Object+0x04 /*ThingTemplate*/, the SpecialPowerTemplate)
value = (readyFrame /*iface+0x08*/, duration /*iface+0x04*/, deathFrame /*TheGameLogic.frame*/)
```

**Restore**, in `reviveHero`, beside the upgrade-mask restore:

```
0078158c  lea ecx, [esi+0x28c]       ; esi = the NEW object
00781592  call 0x68cc6c              ; <- the 5 bytes to take
```

The cave performs the stock call, then walks the new object's modules the same way, looks up each
power's key, and writes both fields back (§3.2). A power with no entry is left exactly as
constructed - ready - which is stock behaviour.

### 3.2 The two bools are two lines of arithmetic

With `now = TheGameLogic.frame` and the stored triple:

```
if (!template->PersistCooldownOnDeath)          -> write nothing            ; stock
if (template->CooldownTicksWhileDead) {
    if (readyFrame <= now)                      -> write nothing            ; dead long enough
    iface[+0x08] = readyFrame                                               ; absolute, untouched
} else {
    iface[+0x08] = now + (readyFrame - deathFrame)                          ; frozen while dead
}
iface[+0x04] = duration
```

Three properties fall out rather than needing engineering:

- **"Dead long enough clears the cooldown" is the absence of code.** The ticking mode restores an
  absolute frame; if that frame is already past, there is nothing to restore and the freshly built
  module is already in the right state. No timer, no expiry sweep.
- **The clock does not jump.** `getPercentReady` is `1 - (readyFrame - now)/duration`; restoring
  both fields keeps the ratio, so the button's pie resumes where it was. Restoring `readyFrame`
  without `duration` is the tempting one-liner and it is wrong - see
  [`recharge-rescale.md`](recharge-rescale.md) §3.3 and
  [`construction-speed-modifiers.md`](construction-speed-modifiers.md) §2.2 for the artefact it
  produces.
- **Half a cooldown is half a cooldown.** `readyFrame - deathFrame` is the remaining frames at the
  moment of death, in the same units `startPowerRecharge` wrote, so no rounding and no float.

### 3.3 What each flag is read on

The bools live on the `SpecialPowerTemplate`, reached through
`Overridable::getFinalOverride` (`0x00688D3C`) the way `startPowerRecharge` reaches `ReloadTime` and
`SharedSyncedTimer` (`0x00896E6C`, `0x00896EE3`).

**`PersistCooldownOnDeath` is read at the snapshot; `CooldownTicksWhileDead` at the restore.** That
split is not symmetry for its own sake - each flag is read where it decides something. The first
decides *whether there is anything to bank*, so reading it at the snapshot keeps the table holding
only entries that can ever be used; the scope originally put both at the restore, on the grounds
that a `map.ini` override flipping mid-match should stay coherent, and that reasoning was wrong in
the one case it mattered: banking every power on cooldown puts pressure on a fixed table (§4.1)
whose overflow silently drops a *flagged* hero. Both ends read the same override chain, so the two
placements differ only under an override that changed between the death and the revive, which
nothing in the engine does.

The restore reads the first flag too, and refuses without it - so a power whose keyword was turned
off between the death and the revive returns stock rather than restored.

## 4. Where the store lives

The one real decision. Three options, and the difference is savegames.

### 4.1 Built: a cave-owned table

A fixed-capacity table in a **writable** cave section, 24 bytes per entry (`Player *`,
`ThingTemplate *`, `SpecialPowerTemplate *`, `readyFrame`, `duration`, `deathFrame`), 1024 entries =
24 KB, scanned linearly, an entry free when its power pointer is NULL. A scan rather than a hash
because it runs on a hero's death and a hero's revive and nowhere else - twice a minute in a busy
match, against a table three orders of magnitude smaller than the object list `GameLogic::update`
already walks every frame.

Keyed on `(player, hero template, power template)` rather than on the revive record, deliberately: a
hero template is unique per player in this engine, both ends hold it (`Object+0x04` at death, the
new object's own at revive), and it sidesteps the record identity question in §9.2 entirely. On
overflow the patch **skips the entry**, degrading that hero to stock behaviour rather than
corrupting a neighbour. An entry is released by the restore that reads it, so the table holds only
heroes who are dead right now.

No engine structure grows. No ctor, dtor or xfer changes. Deterministic: written and read only from
logic-frame code, over the module and object lists in their engine order, so every peer produces
identical contents.

### 4.1.1 The epoch, and the defect it closes

**The table outlives the match that filled it, and two of its three key components outlive one
too.** `ThingTemplate`s are owned by the factory for the life of the process, and a new match's
`Player` can be allocated at an address an old one had. A hero who died in one match and was never
revived would then be holding a key that a *different* match can match - and hand a cooldown to
whoever does.

This was not in the scope. It surfaced while reading the built cave back, and it is the one place
where "the patch keeps its own state" stopped being free.

The fix is a dword at the front of the cave holding the last logic frame either hook saw. A frame
that has gone **backwards** is the signal, and it is exact for both ways this happens:

- a **new match** restarts the frame counter, so everything banked belongs to a game that is over;
- **loading a savegame** rewinds it, and everything banked after the save belongs to a timeline that
  no longer exists - so wiping is what that case wants too, and it is strictly better than the
  §4.3 behaviour it replaces there.

It costs two dwords compared per hook call and only touches the table on the frame the answer
changes. Zero is the correct initial value: the first frame either hook sees is at least that, so a
freshly patched binary never wipes a table that is already empty.

### 4.1.2 What `verify` may not assert

`hero-mana` adds its own `SpecialPower` field, so on a binary carrying both, **whichever patch was
applied second owns the field table** and the two references name *its* cave. That binary is
correct - both fields parse, because the later patch copies the earlier one's rows verbatim - so
`verify` holds the invariant that matters (the live table still carries these two rows, pointing at
this cave's strings and writing this cave's bytes) rather than the one that is easy to check (the
references still name this patch's own table). Asserting the easy one made a clean apply verify as
absent in one of the two orders, which is exactly the composition failure
[the framework's rule 3](../patcher.py) warns about.

### 4.2 The savegame-complete alternative: grow the record

The record is the *right* place - it is per-hero, it is already the thing that carries state across
this exact gap, and it is `Xfer`'d, so a save/load would restore cooldowns with everything else. It
costs materially more: every `0xE8` stride constant (`0x007808BC`, `0x007808EF`, `0x007817D6`,
`0x00781458`, `0x007818A3`, ...), the record's copy path (`0x006E267E`, `0x006E40A6`), its ctor and
its xfer. The records are held by value in a `vector` and copied whole on every revive, so the size
is baked into more places than a scan will confidently find. Not recommended first; recommended if
§9.4 shows savegames matter.

### 4.3 The honest limitation of 4.1

**A save/load between the death and the revive loses the snapshot**, and the hero returns with the
power ready - stock behaviour, not a corrupt one. Everything else survives: the table is rebuilt on
every death, so a hero who dies after the load is covered again. Say this in the modder docs.

Since §4.1.1, the loss is explicit rather than incidental: the load rewinds the frame counter and
the next hook wipes the table. That is the same answer, reached deliberately - and it is the right
one, because a table filled after the save describes a timeline the load discarded.

## 5. Hook inventory

| # | site | original bytes | what replaces it |
|---|---|---|---|
| 1 | `0x008B3879` | `e8 14 df ec ff` | `jmp <snap_hook>`; the cave calls `0x00781792`, then walks the dying object's powers |
| 2 | `0x00781592` | `e8 d5 b6 f0 ff` | `jmp <rest_hook>`; the cave calls `0x0068CC6C`, then writes the cooldowns back |
| 3 | `0x007B1FD0` | `88 5e 58` | `89 5e 58` - zero `+0x58`..`+0x5B` in the ctor (§2.1) |
| 4 | `0x007B1F00` | `8a 45 58` | `8b 45 58` - copy the padding from a default block (§2.2) |
| 5 | `0x007B1F03` | `88 43 58` | `89 43 58` - the store half of the same copy |
| 6 | `0x007B1ABE` | `d8 5f da 00` | the relocated field table |
| 7 | `0x007B2325` | `d8 5f da 00` | the same, in the block parser |

Ten bytes of hook, three single-byte opcode edits, two imm32 repoints. Both hook sites are whole
`call rel32` instructions, so both take a `jmp rel32` exactly and neither needs a `nop`.

The cave, as built, in emission order (the innermost first, so the internal calls resolve as
labels):

| block | bytes |
|---|---|
| the epoch dword and the two keyword strings | 50 |
| the rebuilt field table (27 x 16) | 432 |
| the slot table (1024 x 24) | 24,576 |
| `sync` - the epoch guard and the wipe (§4.1.1) | 58 |
| `find` - the linear scan, allocating or not | 90 |
| `snap` - the flavour test, the §3.1 reads, the insert | 158 |
| `rest` - the lookup and the §3.2 arithmetic | 166 |
| `snap_walk` / `rest_walk` - the module walks | 52 each |
| `snap_hook` / `rest_hook` - the displaced call, `pushad`, the walk | 49 each |
| **total** | **25,734** (`0x6486`), one **writable** section |

The table is 95% of it. That makes this the first patch in the package whose cave the game
**writes**, which `verify` asserts deliberately: `MEM_WRITE` as well as `MEM_EXECUTE`, and the slot
bytes present in the file rather than claimed as uninitialised virtual size, so what the table
starts as is a fact about the image.

### 5.1 Registers and flavours

- The snapshot cave is entered mid-function with `eax` = the record, `ecx` = the experience it must
  still store, `esi` = the module, `ebx` = the experience tracker, `edi` = the revive manager. All
  five are live afterwards; save and restore everything, and perform the stock store first so a
  bail-out is indistinguishable from stock.
- The restore cave has `esi` = the new object and `[ebp-0xf4]` = the record copy, and owes the
  caller `ebx`/`esi`/`edi`/`ebp`.
- **Skip the second `startPowerRecharge` flavour.** `0x00991500` keeps no `duration` (its
  `getPercentReady` at `0x009913BC` divides by the raw `ReloadTime`), so there is nothing coherent
  to restore. Discriminate the same way `recharge-rescale` does - `cmp [[spi]+0x3c], 0x00896E31`,
  fail closed - and leave the three flavour-2 vtables alone.
- **Skip `SharedSyncedTimer` powers.** `0x00896E71` diverts them to a timer on the `Player`
  (`0x006AD1B0`), which death does not touch, so there is nothing to carry. The check is one byte:
  `tmpl[+0x59]`.

## 6. What follows for free

- **The button clock**, §3.2 - no `.apt`, no `.csf`, no ControlBar hook.
- **The AI**, which asks `isReady` and `canUseSpecialPower`, both of which read the restored
  `readyFrame`. A revived hero it thought was armed simply is not.
- **`HeroDie` still wins.** It runs from `setEffectivelyDead`, before the record exists, and it
  writes the *old* object's module - so on Path B its effect is discarded either way, and on Path A
  it clears the cooldown as it always did. The two features do not fight.
- **Pause state is not carried, and should not be.** A `StartsPaused` power on a fresh object is
  paused again by its own `UnpauseSpecialPowerUpgrade` from the restored upgrade mask
  (`0x00781592`), which is the engine's answer and is already correct.

## 7. Out of scope, named

### 7.1 Making `CooldownTicksWhileDead = No` true on Path A

On Path A the cooldown ticks while the hero is dead, because nothing stops an absolute frame. Making
the freezing mode honest there means pausing on death and resuming on respawn - and the engine
already has exactly that: interface slot `+0x24` (`0x00896756`) banks the frame and the percent on
pause and, on the matching resume, does `readyFrame += now - pauseFrame`. Two more hooks in
`RespawnUpdate`'s die handler and its state-3 respawn, no storage, no arithmetic of ours. Deliberately
left out of the first cut: it is a second behaviour change on a path that today needs none, and it
wants its own live test.

### 7.2 The default asymmetry stays

With the keyword absent, Path A persists a cooldown and Path B resets it - exactly as the stock
engine behaves. The patch narrows that gap when the keyword is present and never widens it. A modder
who wants "reset on death everywhere" is asking for the opposite patch (clear the cooldown in the
Path-A respawn), which is not attempted here.

### 7.3 Create-A-Hero

CAH heroes reach the revive list through `createaherorespawn.inc` and the same `RespawnUpdate`, so
they should follow the same two paths - but their templates are built at runtime, which makes the
`ThingTemplate` pointer in §4.1's key a thing to check rather than assume. §9.5.

### 7.4 Not attempted

- **Changing how a cooldown starts.** `startPowerRecharge` keeps its stock arithmetic byte for byte.
- **A per-hero override.** The bools are on the power, as asked. A hero who wants one of their
  powers to persist and another not to already gets that; a hero who wants a *different* answer to
  the same power than another hero does not, and would need storage on the module instead.

## 8. Cost, risk and what it changes

| | |
|---|---|
| edits to `.text` | 2 hooks (10 bytes), 3 single-byte opcode widenings |
| edits to `.rdata` references | 2 imm32 repoints (one relocated field table) |
| new sections | 1 **writable** `.ctd`, `0x6486` bytes, 95% of it the slot table |
| INI surface | 2 new `Bool` keys on `SpecialPower`, both defaulting to `No` |
| structures | none grow; no ctor, dtor or xfer change |
| file size | +26 KB on an 11.3 MB binary |
| risk | low-medium |

**The safety property first: with neither keyword named, the binary behaves exactly as stock.** The
snapshot still runs and still costs a module walk per hero death, but nothing is ever written back,
because the restore reads a flag that is `0` for every power in an unmodified data set - and §2.1 is
what makes that claim true rather than probable.

What it does change:

- **Simulation state.** `readyFrame` gates whether an ability can fire. Every peer needs the patched
  binary and replays recorded on it will not play back on a stock one.
- **Cost, honestly.** One module walk per hero death and one per hero revive - events that happen
  seconds apart at most, not per frame. This is the cheap half of the family;
  `recharge-rescale`'s sweep is the expensive one.
- **Balance.** Dying stops being a way to re-arm a long cooldown. On heroes whose powers are their
  whole value that is a real nerf to trading a hero, and it is the point.

**Conflicts.** Nothing in the current `PATCHES` registry touches `0x008B3897`, `0x00781592`, the
`SpecialPower` field table, or `SpecialPowerTemplate+0x58`. `recharge-rescale` composes: it rewrites
`readyFrame`/`duration` on a *living* object from a per-frame sweep, and this patch writes them once
at the moment a revived object is built - a frame on which the sweep finds `frames_now == duration`
and exits, because the restored pair is self-consistent. `spell-recharge-filter` touches only
`SpecialPowerTemplate.Flags` and three module field tables. `ai-revive-gate` edits `canMakeUnit`,
upstream of everything here.

**Verification, as built.** `apply` refuses unless every window in the patch's `ANCHORS` table -
the two hook sites in context, the two fields' writers and readers, the `SharedSyncedTimer` divert,
the module-walk idiom, one vtable of each flavour and each callee's convention - holds its stock
bytes, and unless the interface vtable still names `startPowerRecharge` at `+0x3C`. `verify` then
checks the cave's own contents (both keywords, the rebuilt table, every byte of the code laid out
at the address it actually landed on), that the **live** field table still parses both keys into
`+0x5A`/`+0x5B` (§4.1.2), and the five rewritten sites.

**Not** asserted: `sizeof(SpecialPowerTemplate)`. The scope wanted the `push 0x88` at `0x007B2292`
pinned, since the padding claim rests on the two bytes being interior - but `hero-mana` legitimately
raises that constant to `0x8C`, so pinning it would have made the two patches mutually exclusive for
no safety gained. The claim is carried instead by what actually establishes it: the field table
naming no field at either offset, and the constructor and copy constructor being exactly the
instructions this patch widens.

## 9. What a live test has to settle

1. **Which path each hero in the mod actually takes.** `RespawnRules AutoSpawn:` decides it, and the
   corpus should be censused: a mod that is all `AutoSpawn:No` needs only Path B, and a mod that
   mixes them needs §7.1 to avoid two heroes behaving differently for reasons no player can see.
2. **Whether the die-time `addHero` appends a second record** for a hero already listed from the
   player template. `0x00781792` unconditionally `push_back`s and returns `size-1`, and the citadel's
   slot index is positional, so either something upstream dedupes or the two records coexist. This
   is why §4.1 keys on the template rather than the record - but the answer decides whether §4.2 is
   even available.
3. **That the snapshot sees every power on the dying hero**, read out of process with `sage_live`
   at the moment of death: `iface+0x04`/`+0x08` on each module against the table.
4. **Savegame behaviour** across the §4.3 gap: save while a hero is dead, load, revive, and confirm
   the hero returns ready rather than wrong.
5. **Create-A-Hero**, §7.3: whether the runtime-built template gives a stable key across death.
6. **`RespawnAsTemplate`**, which changes the template on respawn and therefore the key. Expect the
   cooldown not to carry; confirm it fails to stock rather than onto the wrong power.
7. **Determinism.** Two patched clients, one hero, one long cooldown, one death: the revived hero's
   `readyFrame` must agree to the frame on both, and a recorded replay must play back identically.
8. **Degenerate cases** - a hero who dies on the same frame they cast; a cooldown that expires while
   dead in the freezing mode; a hero revived twice without dying in between; and a `duration` of 0
   from a pre-patch savegame.
9. **The epoch guard actually firing** (§4.1.1): quit to the menu mid-match with a hero dead, start
   another, and confirm the new match's hero is not handed the old one's cooldown - the case the
   guard exists for, and the only one where a table entry could reach a game it does not belong to.
10. **Two objects of the same template owned by one player.** The key is
    `(player, hero template, power template)`, which is unique per hero *because heroes are unique*.
    Anything with a `RespawnUpdate` that is not - a summoned pair, a mod that fields two of the same
    hero - would share one slot, and the second death would overwrite the first. Fail-soft, and
    worth knowing before somebody builds on it.
11. **`StartsPaused` powers.** The restore writes the ready frame onto a module that may be paused
    from construction; the engine's resume then adds the paused interval to it. On the revive frame
    that is zero or near it, but a power that stays paused until an upgrade lands would be shifted
    by the whole wait. Stock behaves the same way for a cooldown started while paused, so this is a
    thing to observe rather than a thing to fix blind.

## 10. Where the build departed from this scope

Written down rather than edited away, because the differences are the parts the scope could not
have got right by reading alone - and each one is a claim a live test can still falsify.

| # | scoped | built | why |
|---|---|---|---|
| 1 | snapshot at `0x008B3897`, 6 bytes | at `0x008B3879`, 5 bytes | the object is in `ebx` there, the site is exactly a `jmp`, and two tests in between were silently choosing which heroes got a snapshot (§3.1) |
| 2 | both flags read at the restore | `PersistCooldownOnDeath` read at the snapshot | it decides whether to bank at all, and banking unflagged powers puts pressure on a table whose overflow drops a flagged hero (§3.3) |
| 3 | open-addressed table | linear scan | it runs twice per hero death; the probing was complexity with nothing to buy (§4.1) |
| 4 | *nothing* | the epoch guard | **a defect**: the table outlived the match that filled it, and templates outlive a match too (§4.1.1) |
| 5 | `verify` pins the table references | `verify` pins the live rows | pinning the references made a correct binary verify as unpatched whenever `hero-mana` was applied second (§4.1.2) |
| 6 | `verify` pins `sizeof` at `0x88` | it does not | `hero-mana` legitimately raises it to `0x8C`; pinning it would have made the two mutually exclusive (§8) |

Item 4 is the one worth reading twice. Every other line is an improvement on a decision; that one is
a bug the scope shipped, found by reading the built cave back and asking what happens to the table
when the match ends. A patch that keeps its own state has to say when that state stops being true,
and this scope did not until it had been written.

## Appendix - every address this document depends on

| VA | meaning |
|---|---|
| `0x00435F30` / `0x00436030` | `AsciiString` assign, used by the record ctor and the default copy |
| `0x00444DB3` | the `Object+0x28C` upgrade-mask copy into `record+0x14` |
| `0x00449681` | the `TheGameLogic` lookup that turns a stored id into an `Object` |
| `0x0042DB80` | `INI::initFromINI(instance, fieldTable)` |
| `0x0042E558` | the engine's `Bool` INI parse function |
| `0x004B1B5A` | the FX-list player used for `DeathFX` / `RespawnFX` |
| `0x005E3BA5` / `0x005E3B79` | start / stop a model-condition animation |
| `0x0062684D` | the object flag the die handler sets and the respawn clears |
| `0x0064F68C` / `0x0064F6C4` | `RespawnUpdate` `newModule` (`0x44`) / `newModuleData` (`0x120`) |
| `0x0065A002` | `RespawnUpdate`'s `ModuleFactory::addModule` registration |
| `0x006515F9` / `0x00653868` | `HeroDie` `newModule` (`0x14`) / `newModuleData` (`0x3C`) |
| `0x006519AF` | thunk: behaviour slot `+0xAC` -> `startPowerRecharge` |
| `0x006519C2` | thunk: behaviour slot `+0xB0` -> main-vtable slot `+0x30` |
| `0x006588B9` | `HeroDie`'s registration (die-module mask 2) |
| `0x00688D3C` | `Overridable::getFinalOverride` |
| `0x0068B678` | `Object::getControllingPlayer` |
| `0x0068BDD0` / `0x0068BDF9` | the two `Object+0x24C` module fan-outs (slot `+0xAC` / `+0xB0`) |
| `0x0068BDA5` | `Object::findModule(nameKey)` - how `RespawnUpdate` and `HeroDie` are found |
| `0x0068C26D` | `Object::getSpecialPowerModule(template)` - 44 callers, 4 reach slot `+0x20` |
| `0x0068CC6C` | the upgrade-mask restore onto `Object+0x28C` - **restore hook site's callee** |
| `0x0068D950` | `Object::setEffectivelyDead(Bool)`; `0x0068D9EA` reaches `HeroDie` |
| `0x006AD1B0` | `Player::startSharedSyncedTimer` - the path this patch skips |
| `0x006ABABD` | the per-player object iteration `HeroDie::onDie` uses |
| `0x006B17EA` / `0x008BC4F7` | the game-start `addHero` calls, from the player template's hero list |
| `0x006D165E` | `ThingFactory::newObject` - **the new hero object on Path B** |
| `0x006E267E` / `0x006E40A6` | the record's copy and the vector `push_back` |
| `0x00697F0F` | the position setter Path A's respawn uses |
| `0x0073B22F` | the stock `SpecialPowerTemplate` reference parse function |
| `0x007806FA` | record -> `ThingTemplate` |
| `0x007808AB` / `0x007808DB` | `ReviveMgr` get-by-index (`0xE8` stride) / find-by-key (`+0xB4`) |
| `0x00780C46` / `0x00780C64` | `canRevive` (`+0xA8 == -1`) / `cancelRevive` |
| `0x00780DD4` | the record ctor from a live `Object` - the death snapshot |
| `0x00781792` / `0x00781801` | `addHero` from an `Object` (one caller) / from a `ThingTemplate` |
| `0x007812B2` | `startRevive` - writes `+0xB4` (id) and `+0xA8` (frame) |
| `0x0078142F` | **`ReviveMgr::reviveHero`** |
| `0x007814C2` | its `newObject` call |
| `0x00781563` / `0x00781574` | its level and experience restores |
| `0x00781592` | **restore hook site** - `e8 d5 b6 f0 ff` |
| `0x0079D745` / `0x0079D833` | the experience-tracker setters used there |
| `0x007B1ABD` / `0x007B1ABE` | the `SpecialPower` `getFieldParse` accessor and its imm32 |
| `0x007B1E6C` | copy-from-default; `0x007B1F00`..`0x007B1F0B` is the `+0x58`/`+0x59` half |
| `0x007B1F5B` | `SpecialPowerTemplate` ctor; `0x007B1FD0`/`0x007B1FD3` the two byte stores |
| `0x007B2292` | `push 0x88` - `sizeof(SpecialPowerTemplate)` |
| `0x007B2325` | the field-table imm32 in the block parser |
| `0x007C4993` / `0x007C4A0B` / `0x007C4A6E` | the script engine's `setReadyFrame` actions |
| `0x00896756` | interface slot `+0x24` - pause / resume, `readyFrame += now - pauseFrame` |
| `0x00896C72` / `0x00896CF2` | `isReady` / `getPercentReady` |
| `0x00896E31` | `startPowerRecharge`, flavour 1 - 23 vtables, interface at module `+0x10` |
| `0x00896E71` | the `SharedSyncedTimer` divert (`template+0x59`) |
| `0x00896F70` / `0x00896F8B` | `readyFrame` (partial / full) and `duration` (full only) |
| `0x00896F99` | main-vtable slot `+0x30` - `readyFrame = now` |
| `0x008979F5` | the `getSpecialPower` idiom the module walk copies |
| `0x008A250A` | `ProductionUpdate`'s call into `reviveHero` |
| `0x008B3244` | `RespawnUpdate` module ctor - vtables `0xC6C360` / `0xC67300` / `0xC6C354` |
| `0x008B37B0`..`0x008B389D` | its die handler; `0x008B3879` is the `addHero` call |
| `0x008B3879` | **snapshot hook site** - `e8 14 df ec ff`, the `addHero` call; `ebx` is the Object |
| `0x008B3897` | the engine's own snapshot beside it - the experience store (§10 item 1) |
| `0x008B3A35` | `RespawnUpdate::update`; `0x008B3B08` is the state-3 in-place respawn |
| `0x008B3C07` / `0x008B3C1C` | revive cost / time for the hero's level |
| `0x008C642D` | `HeroDie`'s per-object callback - the `setReadyFrame(now)` |
| `0x008C64FE` | `HeroDie::onDie` |
| `0x0099344A` | interface slot `+0x20`, `setReadyFrame` - a folded setter in 27 vtables |
| `0x00991500` | `startPowerRecharge`, flavour 2 - no `duration`, skipped |
| `0x00C06050` | the special-power family's `BehaviorModuleInterface` vtable |
| `0x00C64FF0` | flavour-1 `SpecialPowerModuleInterface` vtable |
| `0x00C6CE80` | `RespawnUpdate`'s field table (14 entries) |
| `0x00DA5F34` | `SpecialPower.Flags` name table (7 entries) |
| `0x00DA5FD8` | **the `SpecialPower` field table** - 24 entries, ends `0x00DA6158` |
| `0x00DE412C` | `TheGameLogic` - frame at `+0x40`, object list head at `+0xAC` |
| `0x00DE4A40` | `TheThingFactory` |
| `0x00DE878C` | `TheSpecialPowerStore` |
| `Player+0x758` | the revive manager; records of `0xE8` bytes at mgr `+0x04`/`+0x08` |
| `Object+0x04` / `+0x24C` / `+0x25C` / `+0x26C` / `+0x28C` / `+0x458` | template, module array, body, experience tracker, upgrade mask, status byte |
