# `EXPERIENCE_AWARD` — an `AttributeModifier` that scales the experience an object grants

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`. Read from the repo's `game.dat` (11,346,944 bytes), which
`sage-patch sagepatch` reports as carrying no known patch, so every byte quoted here is stock.

**Status: built** - see [`patches/experience_award.py`](../patches/experience_award.py) - and
**statically verified, not runtime-verified.** Every site is byte-asserted in the tests against the
real `game.dat`, and the stub is run under an emulator against stand-ins for the two engine
functions it calls. None of it has been watched in a running game.

```
sage-patch apply experience-award --in game.dat.backup --out game.dat
sage-patch apply experience-award --keyword KILL_VALUE --in ... --out ...
sage-patch apply experience-award-wb --in Worldbuilder.exe.backup --out Worldbuilder.exe
sage-patch verify experience-award game.dat
```

```ini
ModifierList SummonedWorthless
  Category = SPELL
  Modifier = EXPERIENCE_AWARD 0%       ; killing this object teaches nothing
End

ModifierList MarkedForDeath
  Category = SPELL
  Modifier = EXPERIENCE_AWARD 200%     ; and this one is worth double
  Duration = 20000
End
```

The modifier sits on the object that **dies**. The stock `EXPERIENCE` type is the other half: it
sits on the killer and scales what that killer earns. A kill is multiplied by both.

- **Cost:** 2 five-byte `call rel32` retargets + 77 bytes of stub + a 116 → 120-byte table copy +
  2 repointed imm32 operands.
- **Risk:** low and opt-in - an object with no modifier holder gets its stock award back, and an
  award of 0 (an allied kill) never reaches the query. It **is** simulation state; §5.

## 1. The one place the award is read

`ExperienceTracker::getExperienceValue(Object *killer, Bool evenFromAllies)` is `0x0079D1DB` -
`__thiscall` on the **victim's** tracker, `ret 8`, an `Int` in `eax`:

```
0079d1db  push esi
0079d1dc  mov  esi, ecx
0079d1de  push dword [esi+0x34]      ; the tracker's owner: the victim
0079d1e1  mov  ecx, [esp+0xc]        ; the killer
0079d1e5  call 0x68d7ab              ; killer's relationship to the victim
0079d1ea  cmp  eax, 2                ; ALLIES
0079d1ed  jne  0x79d1fa
0079d1ef  cmp  byte [esp+0xc], 0     ; evenFromAllies
0079d1f4  jne  0x79d1fa
0079d1f6  xor  eax, eax              ; an allied kill is worth nothing
0079d1f8  jmp  0x79d1fd
0079d1fa  mov  eax, [esi+0x14]       ; the current level's ExperienceAward
0079d1fd  pop  esi
0079d1fe  ret  8
```

`0x0068D7AB` reads `[arg+4]` and tests template KindOf bytes through it, so the dword at tracker
`+0x34` is an `Object *`, and it is the object whose award this is. `ExperienceAward` itself is
`ExperienceLevel +0x1C` (field table `0x00C11BF0`, row 1); the tracker caches the current level's
value at `+0x14`.

A scan of `.text` for a `call rel32` landing on `0x0079D1DB` finds exactly two, and no dword in the
image holds its address, so nothing reaches it indirectly. The tests repeat that scan against the
real binary.

| caller | what it feeds |
|---|---|
| `0x006954B5` | **the killer's experience.** Inside `0x00695475`, `__thiscall` on the killer, `(Object *victim, Bool evenFromAllies, Real share)`, `ret 0xC`. The award is converted to a `Real`, multiplied by `share`, then by the killer's own `EXPERIENCE` modifier (`push 6` at `0x006954E8`, type 6), and handed to `ExperienceTracker::addExperiencePoints` (`0x0079D833`) at `0x00695566` |
| `0x006AB083` | **the killing player's tally.** Inside `0x006AAFC3`, `__thiscall` on the killer's `Player`, reached only from `0x0068BE33`. The award times `share` is added to the player's score keeper (`Player +0x3DC`, `0x0079DBA1`) and to the rank-point accumulator at `Player +8` (`0x00782AA4`) - the points that buy spellbook powers |

Both callers do the same thing with the answer on the next instruction (`cvtsi2ss xmm0, eax`), so
scaling `eax` scales everything downstream of either.

`0x00695475` is reached from the kill-scoring routine `0x006955BC` (which also bumps the kill
counters and calls `ScoreKeeper::addObjectDestroyed`) at `0x006957AD`, per horde member through the
callback `0x006955A6`, and from `0x00850F4A`. One of `0x006955BC`'s eight callers is `0x008C45B7`,
inside the `ActiveBody` compiland, i.e. the kill is scored from the damage path.

**Not established:** that an `AttributeModifier` on the victim is still held at the moment the
kill is scored. The scoring call sits in the damage path rather than in a die module, which is the
order that would keep it, but nothing here read what death does to the modifier holder. This is
the first thing to confirm in a live match.

## 2. The hook

Both `call` operands are retargeted at one wrapper with `getExperienceValue`'s own contract, which
runs the stock function and scales what it returns:

```
        push  esi
        mov   esi, ecx                ; the victim's tracker
        push  dword [esp+0xc]         ; evenFromAllies
        push  dword [esp+0xc]         ; killer
        call  0x79d1db                ; ret 8
        test  eax, eax
        jle   done                    ; nothing to scale
        mov   ecx, [esi+0x34]         ; the victim
        test  ecx, ecx
        je    done
        push  eax                     ; the award, kept across the query
        push  1.0                     ; *out, seeded
        push  1                       ; flag, as the engine's own sites pass
        push  0                       ; no ctx
        lea   edx, [esp+8]
        push  edx                     ; &out
        push  <EXPERIENCE_AWARD>
        call  0x68c82d                ; getModifierMultiplier, ret 0x10
        cvtsi2ss  xmm0, [esp+4]
        mulss     xmm0, [esp]
        cvttss2si eax, xmm0
        add   esp, 8
        test  eax, eax
        jns   done
        xor   eax, eax                ; never a negative award
done:   pop   esi
        ret   8
```

Wrapping the two calls rather than rewriting the function keeps every edit a whole instruction
with nothing branching into it: inside `0x0079D1DB` the only five-byte window that sees the award
straddles `0x0079D1FD`, which the allied-kill `jmp` lands on.

`getModifierMultiplier` (`0x0068C82D`) and what its value means are derived in
[`healing-received-modifier.md`](healing-received-modifier.md) §3: a plain multiplier, several
active lists multiplying together, and an early return that does **not** write `*out` for an object
with no modifier holder - hence the seed.

Register use matches the function being stood in for: `esi` is saved and restored, and `eax`,
`ecx`, `edx` and `xmm0` are the callee's to clobber. Neither caller holds anything on the x87
stack across the call.

## 3. What it means in play

- **The product is truncated to an integer**, because that is what the callers convert. An award
  of 5 at 50% is 2.
- **0% removes the kill's value entirely.** `0x006AB091` tests the player-side amount `> 0` and
  skips both adds; on the unit side `addExperiencePoints` receives 0.
- **A negative multiplier is clamped to 0.** Neither caller is written to take experience away.
- **It scales both halves of a kill.** The killer's experience and the player's rank points come
  from the same value; there is no separate keyword for either.
- **It is read on the dying object alone.** A horde member is asked for its own modifier, not its
  horde's.
- **The killer's `share` and `EXPERIENCE` still apply**, after it and unchanged.

## 4. What this does not do

- **`ExperienceAwardOwnGuysDie`** (`ExperienceLevel +0x20`, cached at tracker `+0x18`) is read by
  the neighbouring function at `0x0079D201`, which is not touched.
- **Experience that is not a kill award**: `addExperiencePoints` has fifteen call sites, and the
  other fourteen - resource income, `SlaughterHordeContain`, `LevelGrantSpecialPower`, script
  grants - do not ask a victim what it is worth.
- **Bounty.** Gold for a kill is `BOUNTY_PERCENTAGE` on the killer and the template's
  `BountyValue`, a separate path.
- **It does not filter by killer.** The killer is on the stub's stack and unused.

## 5. Determinism and loading

Experience is simulation state: every peer must run the same patched binary, and a replay recorded
on it will not play back on a stock one.

INI naming the keyword **fails to load** on an unpatched `game.dat` - the name walk raises
`"Attribute '%s' not found"` - and ends Worldbuilder's load unless the editor carries
`experience-award-wb`. The name table is shared with `production-split` and `healing-received`;
[`patches/utils/modifier_types.py`](../patches/utils/modifier_types.py) reads it live, so the
three compose in any order and the type's index is whatever the image hands out at apply time.

## 6. Address summary

| what | VA |
|---|---|
| `ExperienceTracker::getExperienceValue` | `0x0079D1DB` |
| its two callers (the retargeted calls) | `0x006954B5`, `0x006AB083` |
| the tracker's owner / its cached award | tracker `+0x34` / `+0x14` |
| the killer-side award routine / its `EXPERIENCE` read | `0x00695475` / `0x006954E8` |
| the player-side award routine / its only caller | `0x006AAFC3` / `0x0068BE33` |
| kill scoring / its per-member callback | `0x006955BC` / `0x006955A6` |
| `ExperienceTracker::addExperiencePoints` | `0x0079D833` |
| score-keeper add / rank-point add | `0x0079DBA1` / `0x00782AA4` |
| the own-guys-die sibling | `0x0079D201` |
| `Object::getModifierMultiplier` | `0x0068C82D` |
| modifier-type name table / its two references | `0x00DA6D28` / `0x00804CB3`, `0x00804CBA` |
