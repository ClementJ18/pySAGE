# Making AI special-power hooks respect `EnableOnModelCondition`

The reverse engineering behind
[`patches/experimental/ai_power_model_condition.py`](../patches/experimental/ai_power_model_condition.py).
ROTWK `game.dat` build `2.01.2614.37001`, ImageBase `0x400000`. Recovered statically 2026-09-28.

## TL;DR

- A `CommandButton`'s `EnableOnModelCondition` (`+0x194`) and `DisableOnModelCondition`
  (`+0x1E0`) are evaluated in exactly one place: the pure predicate at **`0x00942490`**,
  `stdcall(button, object)`, which the control bar calls to grey a button out
  ([`multi-execute-gate.md`](multi-execute-gate.md) §"The one place model conditions are
  evaluated").
- `AISpecialPowerUpdate::update` (**`0x008B73B7`**) never calls it. Once its power is ready it
  hands straight to the coin flip, the type's picker and the cast (`0x00993055`). So an AI hook
  fires a power its own button would refuse a player.
- Example: Edain's Ambush of the Wood-Elves (`Command_ElvenAmbush`,
  `EnableOnModelCondition = INVISIBLE_CAMOUFLAGE`). A hook on it would ambush from open ground.
- The fix: one 6-byte hook at **`0x008B7457`**, the first instruction after the ready check. It
  goes into a cave that calls `0x00942490` with the hook's bound button and its object, and
  leaves by the tick's stock "did not cast" exit (`0x008B7493`) when the answer is `DISABLED`.
- **AI-only by construction.** The tick belongs to the `AISpecialPowerUpdate` module. Player
  clicks and `DoCommandUpgrade` presses (`Object::doCommandButton`, `0x00696FD2`) don't reach it,
  so a mod's deliberate auto-presses still fire regardless of conditions.

## 1. The module and its tick

`AISpecialPowerUpdate`'s constructor (`0x008B703A`) builds a module whose
`UpdateModuleInterface` vtable is `0x00C6D948`:

```asm
008b7055  mov dword [esi],      0xc6da14
008b705b  mov dword [esi+0xc],  0xc6d958
008b7062  mov dword [esi+0x10], 0xc6d948     ; UpdateModuleInterface
```

Slot 0 of `0x00C6D948` is `0x008B73B7`, the per-frame `update`. It runs with `esi` = the
interface (module `+0x10`), so the fields it reads sit at negative and small positive offsets:

| read as | module offset | what |
|---|---|---|
| `[esi-0xC]` | `+0x04` | the module data (`CommandButtonName`, `SpecialPowerAIType`, …) |
| `[esi-8]` | `+0x08` | the owning `Object *` |
| `[esi+0x10]` | `+0x20` | active flag |
| `[esi+0x11]` | `+0x21` | bound flag; see "Binding" in pySAGE-edain's `docs/ai-special-powers.md` |
| `[esi+0x14]` | `+0x24` | the type behaviour the factory at `0x0099272E` built |

The type behaviour's `+0xC` is the `CommandButton *` the bind (`0x008B714F`) found.

```asm
008b7426  mov  ecx, [esi+0x14]
008b7429  push dword [esi-8]
008b742c  mov  eax, [ecx]
008b742e  call [eax+4]                   ; behaviour housekeeping
008b7431  mov  eax, [esi+0x14]
008b7434  mov  eax, [eax+0xc]            ; the bound CommandButton
008b7437  cmp  eax, ebx                  ; ebx = 0
008b7439  je   0x8b749e                  ; no button -> sleep
008b743b  mov  eax, [eax+0x44]           ; its SpecialPowerTemplate
008b743e  cmp  eax, ebx
008b7440  push edi
008b7441  mov  edi, [esi-0xc]            ; module data
008b7444  je   0x8b7451
008b7446  push eax
008b7447  lea  ecx, [esi-0x10]
008b744a  call 0x8b708b                  ; is the power ready?
008b744f  jmp  0x8b7453
008b7451  mov  al, 1
008b7453  cmp  al, bl
008b7455  je   0x8b7493                  ; not ready -> did not cast
008b7457  mov  cl, [edi+0x19]            ; <- the hook site
008b745a  mov  eax, [esi-8]
008b745d  push ecx                       ; SpellMakesAStructure
008b745e  mov  cl, [edi+0x18]
008b7461  push ecx                       ; RandomizeTargetLocation
008b7462  mov  ecx, [esi+0x14]
008b7465  push eax                       ; the Object
008b7466  call 0x993055                  ; coin flip, picker, cast
...
008b7493  mov  ecx, [esi+0x14]           ; did not cast
008b7496  mov  eax, [ecx]
008b7498  pop  edi / pop esi / pop ebx
008b749b  jmp  [eax+0x10]                ; the behaviour's next-wake computation
```

The ready check `0x008B708B` asks about object status bit `0x5A`, calls `canUseSpecialPower`
(`0x007B1D79`), then asks the power module itself. It never looks at the button.

Nothing else between the bind and the cast looks at the button either: `0x00993055` rolls the
coin and calls the type's slot 7; the pickers in pySAGE-edain's `docs/ai-special-powers.md` read
health, enemies and allies. So a hook on a button with `EnableOnModelCondition` casts whenever its
picker is satisfied, whatever the object's model conditions.

## 2. The predicate

`0x00942490`, in full:

```asm
00942490  push ebx / push esi / push edi
00942493  mov  edi, [esp+0x10]           ; button
00942497  lea  esi, [edi+0x1e0]          ; DisableOnModelCondition
0094249d  mov  ecx, esi
0094249f  call 0x4b3783                  ; any bit set?
009424a4  test al, al
009424a6  mov  ebx, [esp+0x14]           ; object
009424aa  je   0x9424bc
009424ac  push esi
009424ad  lea  ecx, [ebx+0x10c]          ; object's model conditions
009424b3  call 0x6632e9                  ; any in common?
009424b8  test al, al
009424ba  jne  0x9424dd                  ; -> DISABLED
009424bc  lea  esi, [edi+0x194]          ; EnableOnModelCondition
009424c2  mov  ecx, esi
009424c4  call 0x4b3783
009424c9  test al, al
009424cb  je   0x9424e1                  ; none listed -> AVAILABLE
009424cd  push esi
009424ce  lea  ecx, [ebx+0x10c]
009424d4  call 0x6632e9
009424d9  test al, al
009424db  jne  0x9424e1                  ; has one of them -> AVAILABLE
009424dd  push 3                         ; DISABLED
009424df  jmp  0x9424e3
009424e1  push 2                         ; AVAILABLE
009424e3  pop eax / pop edi / pop esi / pop ebx
009424e7  ret 8
```

The semantics, which the patch inherits unchanged:

- any `DisableOnModelCondition` flag present → disabled;
- else no `EnableOnModelCondition` flags → available;
- else **any one** of the enable flags present → available.

Both helpers walk the 19-dword `ModelConditionFlags`. `0x004B3783` writes only `eax`;
`0x006632E9` writes `eax`, `ecx`, `edx` and saves `esi`. The predicate saves `ebx`, `esi`, `edi`.
`Object+0x10C` is the logic object's mask, not the drawable's
([`ai-revive-gate.md`](ai-revive-gate.md) §Scope), so the answer is the same on every peer.

## 3. The patch

| | |
|---|---|
| hook | `0x008B7457`, the 6 bytes `8a 4f 19 8b 46 f8` (`mov cl,[edi+0x19]` / `mov eax,[esi-8]`) |
| becomes | `jmp rel32` into the cave + one `nop` |
| cave | `.aipmc`, allocated past every existing section |

```asm
push dword [esi-8]            ; the Object
mov  eax, [esi+0x14]          ; the type behaviour
push dword [eax+0xc]          ; its bound CommandButton
call 0x00942490               ; stdcall, ret 8
cmp  eax, 3                   ; DISABLED
je   disabled
mov  cl, [edi+0x19]           ; the displaced instructions
mov  eax, [esi-8]
jmp  0x008B745D               ; on to the cast step
disabled:
jmp  0x008B7493               ; the stock not-ready exit
```

**Why here.** The hook site is reached only by fallthrough from the ready test, so the power is
known to be castable and the button known to be non-NULL (`0x008B7437`). It sits before the coin
flip, so a disabled tick draws no random number. The logic RNG sequence changes against an
unpatched binary, but it is identical on every patched peer.

**Why the not-ready exit.** A disabled button behaves exactly like a power still recharging: the
behaviour computes its next wake-up and the hook tries again later. When the condition appears
(the unit is camouflaged again), the next tick casts as normal.

**Register safety.** At the hook `esi` is the interface, `edi` the module data and `ebx` is 0 for
the tick's compares. The predicate preserves all three. It writes `eax`, `ecx`, `edx`: the
displaced instructions reload `cl` and `eax`, and the upper bytes of `ecx` are pushed with the
`bool` exactly as in stock, where they are also garbage. `edx` isn't read before being written
on either exit. The call is `stdcall` with two arguments and `ret 8`, so the stack is balanced.

### Anchors

| anchor | asserts |
|---|---|
| `0x008B7062` = `c7 46 10 48 d9 c6 00` | the constructor stamps vtable `0x00C6D948` |
| `0x00C6D948` = `0x008B73B7` | its slot 0 is the function being hooked |
| `0x008B73B7` = `53 56 8b f1 33 db` | the tick's prologue |
| `0x008B7431` (38 bytes) | the button load, the NULL test and the ready check the hook follows |
| `0x008B745D` (14 bytes) | the rest of the cast step's argument set-up and `call 0x00993055` |
| `0x008B7493` = `8b 4e 14 8b 01 5f 5e 5b ff 60 10` | the not-cast exit |
| `0x00942490` (90 bytes) | the whole predicate, since the cave relies on what it clobbers |

## 4. What it changes in a mod

All 430 Edain buttons carrying `EnableOnModelCondition` or `DisableOnModelCondition` are now
honoured by any AI hook naming them, not just the one this was written for. A hook that has
been firing only *because* its gate was ignored goes quiet. That is the button's intended rule,
but before shipping, list the hooks whose buttons carry either field and check each one.

Not affected:

- **`DoCommandUpgrade`** presses (`Object::doCommandButton` via `ControlBar::findCommandButton`)
  bypass this tick, so Edain's Enshrouding Mist and Heart Tree auto-ambushes still fire.
- **Players.** The control bar already applied the rule, and
  [`multi-execute-gate`](multi-execute-gate.md) applies it per member in a group.
- **`AutoAbility`**'s own update (`0x0085D9D1`, reached through a vtable) runs its own copy of
  the same two tests.

## 5. Status

**Static only.** The cave is written against the disassembly above. It applies to a clean
`game.dat` and `sage-patch verify` confirms it. It runs under Unicorn in
`tests/sage_patch/test_ai_power_model_condition.py` against the engine's own predicate and both
helpers: enabled, disabled, disable-over-enable and any-of-enable, with registers and stack
checked on both exits. It hasn't been seen in a match, so it stays in `patches/experimental/`.

What to watch live: a Lothlórien AI with an `AI_SPECIAL_POWER_RANGED_AOE_ATTACK` hook on
`Command_ElvenAmbush` should ambush from inside a forest or mist and never from open ground.

## 6. Composition

`0x008B7457` and the rest of `AISpecialPowerUpdate::update` are touched by no other bundled patch.
[`multi-execute-gate`](multi-execute-gate.md) *calls* `0x00942490` from its own cave and
doesn't write it. The cave is allocated by name past every existing section, so the patch is
order-independent.
