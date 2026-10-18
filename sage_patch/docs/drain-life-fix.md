# DrainLife with DelayTime and on DOT ticks

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR), read from the
repo's `game.dat`.

- **Cost:** 4 `rel32` repoints, one `je` to `jmp`, two byte moves widened to dword moves of the
  same length, and a `0xD0`-byte `.drain` cave. No INI keyword is added.
- **Risk:** low. The drain keeps every stock rule. It now runs when each hit lands instead of
  straight after the nugget's `attemptDamage` call.
- **Status:** static-verified and emulated over the real `game.dat`: the cave's three routines,
  the patched constructor and copy, and both the stock immediate path and the delayed-damage list
  reaching the drain (`tests/sage_patch/test_drain_life_fix_emulated.py`). Not yet seen in a
  running game.

```
sage-patch apply drain-life-fix --in game.dat.backup --out game.dat
```

## The complaint

- A `DamageNugget` with `DrainLife = Yes` and a `DelayTime` never heals its source.
- A `DOTNugget` with `DrainLife = Yes` heals on its first tick only.

## Why

### The drain is a step after one call

`DrainLife` (Bool, nugget `+0x1B4`) and `DrainLifeMultiplier` (Real, `+0x1B8`) are read in one
place, `DamageNugget::doDamage` (`0x0090E683`), right after it asks the target to take the hit:

```
0090e6a9  call 0x90e28c               ; build the DamageInfo at [ebp-0x7c]
0090e6c7  call 0x698e7d               ; target->attemptDamage(&info)
0090e6cc  cmp  byte [esi+0x1b4], 0    ; DrainLife?
0090e6d3  movss xmm0, [esi+0x1b8]
0090e6db  mulss xmm0, [ebp-0xc]       ;   x info.output.actualDamageDealt (+0x70)
0090e6e5  je   0x90e722               ;   off -> done
0090e6f4  push [edi+8]                ; the source id
0090e6fd  call 0x449681               ; TheGameLogic->findObjectByID
0090e709  test byte [ecx+0x10b], 2    ; a PROJECTILE? -> done
0090e71d  call 0x690532               ; source->attemptHealing(amount, NULL)
```

So it heals for whatever that one call dealt.

### A delayed hit deals nothing in that call

`Object::attemptDamage` (`0x00698E7D`) never applies a delayed hit:

```
00698e9c  movss xmm0, [eax+0x28]      ; info's delay
00698ea1  comiss xmm0, 0
00698ea9  jbe   0x698eb8
00698eab  lea   ecx, [esi+0x460]      ; delay > 0: queue a copy on the object's delayed list
00698eb1  call  0x695031
00698eb8  call  0x697e50              ; otherwise: the body-damage step, which fills the output
```

`DelayTime` is exactly that delay (the nugget writes it to `info+0x28`, plus distance over
`DamageSpeed`). So with a delay, the call returns having dealt 0, and the drain heals 0. The
queued copy lands later from the list's update (`0x00697EB6`), which calls the body-damage step
directly at `0x00697EEA`:

```
00697ed0  movss xmm0, [eax+0x28]
00697ed5  subss xmm0, 1.0             ; a frame passes
00697ee5  jbe   ...                   ; still waiting
00697eea  call  0x697e50              ; land it: no drain anywhere on this path
```

### A DOT tick is not the nugget's call

`DOTNugget::doDamage` (`0x00911407`) builds a `DamageInfo` into a DOT entry (`DamageInfo`, then
interval, duration and next frame at `+0x7C..+0x84`), registers it with the manager at
`TheGameLogic+0x174` (`0x00821073`), then deals the first hit through `DamageNugget::doDamage`,
which drains. The manager stores the entry through the `DamageInfo` copy constructor
(`0x00820961`). Each later tick (`0x00820F86`) calls `Object::attemptDamage` on the stored info
directly. That's the first tick only.

## The patch

### Carrying the multiplier in the `DamageInfo`

`DamageInfo` is `0x7C` bytes: a vtable, the input at `+0x04`, the output at `+0x6C`. The drain
needs the multiplier wherever the info goes, and only two routines ever build an input (they are
the only writers of its vtable `0x00C0F3A8`): the constructor `0x0066341C` and the memberwise copy
constructor `0x00662A5C`. Neither touches the three padding bytes after the Bool at input `+0x4C`
(`DamageInfo+0x51..+0x53`):

| site | stock | patched |
|---|---|---|
| `0x00663492` ctor | `mov byte [eax+0x4c], cl` (`ecx` zero) | `mov dword [eax+0x4c], ecx` |
| `0x00662ADA` copy | `mov dl, [ecx+0x4c]` / `mov [eax+0x4c], dl` | `mov edx, [ecx+0x4c]` / `mov [eax+0x4c], edx` |

Both are the same length, and the Bool itself moves as before. Now every input starts with the
padding zeroed, and every copy carries it: the delayed list's copy (`0x00692B7B` → `0x00664321`)
and the DOT manager's copy.

The multiplier is stored as the top 24 bits of its float, read back as the dword at
`DamageInfo+0x50` with the low byte (the Bool) cleared. That's exact for 0.5, 1, 1.5, 2 and the
like, and good to about five digits otherwise. Zero means "no drain".

### Stamping it

- **`stamp_attempt`**, at `0x0090E6C7` (`doDamage`'s `attemptDamage` call; `esi` is the nugget):
  when `DrainLife` is set, writes the multiplier into the info, then tail-jumps to
  `attemptDamage`.
- **`stamp_dot`**, at `0x00911477` (`DOTNugget::doDamage`'s `manager->add(targetID, entry)`):
  the same on the entry's `DamageInfo` before the manager copies it.

### Draining where the hit lands

**`damage_now(info)`** (`__thiscall` on the target, `ret 4`) replaces both calls to the
body-damage step, `0x00698EBA` (immediate) and `0x00697EEA` (a delay running out). It:

1. clears the output's damage dealt, since a DOT reuses one info for every tick and the body
   may skip one;
2. calls the body-damage step;
3. drains as the stock code did: multiplier × damage dealt, nothing for `DAMAGE_HEALING` (7), a
   zero or NaN amount, a missing source or a `PROJECTILE` source, through
   `source->attemptHealing(amount, NULL)`.

The stock drain after `doDamage`'s `attemptDamage` call is skipped (`je` at `0x0090E6E5` becomes
`jmp`), so an immediate hit heals once.

## Behaviour

- **`DelayTime`:** the source heals when the hit lands, by what that hit dealt.
- **`DOTNugget`:** the source heals on every tick, by that tick's damage. If the source is dead
  by then, there's no heal, as for a direct hit from a dead source.
- **Immediate hits:** unchanged, with one heal per hit.
- **Composition:** applies before or after every other registered patch that applies to this
  binary.

## Not covered

- **Saved games.** The delayed list and DOT entries are saved field by field, and the padding
  isn't a saved field. A hit queued before a save and landing after a load doesn't drain.
- **Precision.** The multiplier's last mantissa byte is dropped (see above).

## Addresses

| VA | meaning |
|---|---|
| `0x0090E683` | `DamageNugget::doDamage` |
| `0x0090E6C7` | its `attemptDamage` call (hooked) |
| `0x0090E6CC` | the stock drain (pinned) |
| `0x0090E6E5` | the `je` past it (now `jmp`) |
| `0x00911407` | `DOTNugget::doDamage` |
| `0x00911477` | its DOT manager registration (hooked) |
| `0x00821073` | the DOT manager's add |
| `0x00820F86` | a DOT tick: `attemptDamage` on the stored info |
| `0x00698E7D` | `Object::attemptDamage` |
| `0x00698EBA` | its immediate body-damage call (hooked) |
| `0x00697EB6` | the delayed-damage list update |
| `0x00697EEA` | its body-damage call when a delay runs out (hooked) |
| `0x00697E50` | the body-damage step |
| `0x00690532` | `Object::attemptHealing(amount, source)` |
| `0x0066341C` / `0x00662A5C` | `DamageInfoInput` constructor / copy constructor |
| `0x00663492` / `0x00662ADA` | their byte moves at input `+0x4C` (widened) |
