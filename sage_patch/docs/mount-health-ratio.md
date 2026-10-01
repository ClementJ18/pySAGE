# Health across a mount swap

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`.

**Verdict:** `ToggleMountedSpecialAbilityUpdate` copies the old object's current health onto the
replacement as an absolute number of hit points. It does not scale by the ratio or clamp to the new
maximum. Two templates with different `MaxHealth` therefore trade health at a different ratio in
each direction. `mount-health-ratio` replaces the one read the copy makes, so the stored value
becomes `old current / old max x new max`.

- **Cost:** two 5-byte `call` hooks and a 23-byte cave (`.mnthp`). No INI change.
- **Risk:** low. The cave calls two body getters that every body class already has, and the stock
  code still does the store.
- **Status:** built ([`patches/mount_health_ratio.py`](../patches/mount_health_ratio.py)) and
  statically verified against the Edain install's `game.dat`. **Not runtime-verified.**

## 1. The example

Edain's `WildZuchtdracheOld` (ground, `MaxHealth = BASE_HEALTH_MONSTER_ELITE` = 5600) and
`WildZuchtdracheOldFlying` (`MaxHealth = 5000`) point at each other through `MountedTemplate`.
Stock, a full-health dragon on the ground takes off holding 5600 of 5000. A damaged one reads a
higher fraction in the air than it did on the ground: 3000/5600 is 54%, and 3000/5000 is 60%.

## 2. The hand-over

The mount swap is `0x008b140d` (see [`lifetime-transform.md`](lifetime-transform.md) §1a). The
dismount path has a sibling whose body is byte-identical at this point. In both, `esi` is the new
object and `edi` the old:

```
008b14c8  mov  byte [eax+0x3c], 0          ; experience first: the guard off,
008b14d8  fld  dword [old xp+0x10]
008b14e1  call 0x0079d8ef                  ;   new xp := old xp, running the new object's level-ups
008b14ec  mov  byte [eax+0x3c], 1          ;   guard back on
008b14f0  mov  eax, [esi+0x25c]            ; new body            <- TOGGLE_MOUNTED_MOUNT_HEALTH_COPY
008b14f6  mov  ecx, [edi+0x25c]            ; old body
008b14fc  mov  ebx, [eax]                  ; new body's vtable
008b14fe  mov  [ebp-0x14], eax
008b1501  mov  eax, [ecx]                  ; <- hooked: these two instructions
008b1503  call [eax+0x10]                  ;    old->getHealth()   fld [ecx+8]
008b1506  push ecx
008b1507  mov  ecx, [ebp-0x14]
008b150a  fstp dword [esp]
008b150d  call [ebx+0xac]                  ; new->setHealth(h)     movss [ecx+8], h / ret 4
```

The dismount copy is the same 35 bytes at `0x008b236f`. A search of the whole image for the
`getHealth` → `[ebx+0xac]` pair finds these two sites and no others. No direct branch targets any
byte in either hooked window.

Body slot `+0xac` is `0x005015c6` in all six `ActiveBody`-family vtables:

```
005015c6  movss xmm0, [esp+4]
005015cc  movss [ecx+8], xmm0     ; current health, raw
005015d1  ret 4
```

It does not clamp, recompute the damage state or look at the maximum.

**Level-ups happen before the store.** `0x0079d8ef` writes the experience and calls `0x0079d141`,
which walks the level table and calls the tracker's level-gained slot (`[vtbl+0x10]`) once for each
level crossed. That slot is what applies each level's `AttributeModifiers`, such as
`HEALTH_MULT 110%` on Edain's monster heroes. So by `0x008b14f0` the new body's maximum already
includes its rank bonus, and a ratio taken against it lands at the right fraction of the right
maximum.

## 3. The getters the cave uses

`BODY_GET_HEALTH_RATIO_SLOT` (`+0x14`) and `BODY_GET_MAX_HEALTH_SLOT` (`+0x1c`), across every body
vtable that carries `ActiveBody::internalChangeHealth`:

| vtable | `+0x10` getHealth | `+0x14` ratio | `+0x1c` max |
|---|---|---|---|
| five of the six | `fld [ecx+8]` | `0x008c1d75`: `max > 0 ? cur / max : 0` | `fld [ecx+0x10]` |
| `0x00c72200` | same | `0x008c4ea4`: forwards to a linked object's body, else 0 | `0x008c51ee`: the same forwarding |
| `InactiveBody` | `0` | `0` | `0` (and `setHealth` is a bare `ret 4`) |

The forwarding body's ratio and maximum both come from the same linked object, so their product is
consistent. An `InactiveBody` on either side gives the same result stock does: the store becomes 0,
or is a no-op.

## 4. The patch

Each hooked `mov eax,[ecx] / call [eax+0x10]` becomes `call .mnthp`:

```
mov  eax, [ecx]
call [eax+0x14]         ; old ratio
push ecx
fstp dword [esp]        ; parked: the x87 stack must be empty across a call
mov  ecx, [ebp-0x14]    ; the new body, from the swap's own frame
mov  eax, [ecx]
call [eax+0x1c]         ; new maximum
fmul dword [esp]
pop  ecx
ret                     ; st(0) = ratio x new max, for the stock fstp / setHealth
```

It holds no absolute address, so both sites share one copy. `apply` asserts the whole 35-byte
sequence at both sites, not just the five bytes it replaces. The cave depends on `ecx` holding the
old body and `[ebp-0x14]` the new one, and only the surrounding instructions guarantee that.

The patch does not clamp. An old object that is already above its maximum crosses over at the same
fraction above the new one. The swap itself can no longer put a unit above its maximum.

## 5. Without the patch

No INI keyword controls the hand-over. The only data-side fix is to give both templates of a pair
the same `MaxHealth`, and the same health bonuses from upgrades and levels. With equal maximums, an
absolute copy and a ratio copy give the same result.

## 6. Open

- **Runtime.** In a game: take a `WildZuchtdracheOld` to about half health, toggle it to flying
  and back, and read `[[obj+0x25c]+0x08]` / `+0x10` with `sage_live` on each form. The fraction
  should hold at every step. Check a ranked dragon as well, to confirm the §2 claim that the rank
  bonus is already in the new maximum when the store runs.
