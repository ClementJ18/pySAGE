# The upgrade limit — why adding upgrades eventually corrupts unrelated ones

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), verified against the
clean `engine/game.dat.backup`.

**Verdict up front:** the engine can hold **1152 upgrades**. Every upgrade mask is a fixed 36-dword
bitfield, the index allocator that fills it has no ceiling, and none of the 33 sites that index into
a mask bounds-check. Upgrade 1152 sets bit 0 of whatever mask is laid out next, which in practice is
another upgrade mask. So the failure is not a crash at a clean boundary — it is `RequiredUpgrades`
quietly reading as `ExcludedUpgrades`, on upgrades defined late in load order, scattered across
apparently unrelated units.

## The mask is 36 dwords

`UpgradeMaskType` is 144 bytes / 36 dwords / **1152 bits**, hard-coded at every site that touches it:

| site | evidence |
|---|---|
| `0x0066f613` | `push 0x90` → `memset(mask, 0, 0x90)` at `parseUpgradeMask` entry |
| `0x00444db4` | `push 0x90` → `memcpy` copy constructor |
| `0x0068cc70` | `push 0x24 ; pop edx` — `operator\|=` loop counter |
| `0x00444dd7` | `cmp eax, 0x24` — `any()` loop bound |
| `0x00446152` | `cmp edi, 0x24` — `countBits()` loop bound (SWAR popcount) |

The INI field-parse tables agree independently. Every mask pair declared in the same block sits
exactly `0x90` apart, with no padding between them:

```
table@0x00c76ad8  TriggeredBy                     offset=0x000
table@0x00c76ae8  ConflictsWith                   offset=0x090
table@0x00c805c0  RequiredUpgrades                offset=0x004
table@0x00c805d0  ExcludedUpgrades                offset=0x094
table@0x00c80648  RequiredUpgrades                offset=0x004
table@0x00c80658  ExcludedUpgrades                offset=0x094
table@0x00c68e78  RequiredUpgrades                offset=0x0d4
table@0x00c68e88  ForbiddenUpgrades               offset=0x164
table@0x00c703f0  Upgrade                         offset=0x00c
table@0x00c507f8  IgnoreTreeCheckUpgrades         offset=0x01c
table@0x00c2be18  CreateAHeroUIAllowableUpgrades  offset=0x24c
table@0x00da4988  WorldMapArmoryUpgradesAllowed   offset=0x404
```

Same 16-byte `{const char* name, parseFn, userData, offset}` stride as the CommandSet table.

## The allocator has no ceiling

`UpgradeCenter::newUpgrade` at `0x0066fc27` hands out one bit index per upgrade and increments a
bare counter:

```
0x0066fc34  push 0x9c                    ; sizeof(UpgradeTemplate)
0x0066fc3b  call 0x42f6e0                ; operator new
...
0x0066fca8  call 0x49f474                ; TheNameKeyGenerator->nameToKey(name)
0x0066fcad  cmp byte ptr [ebp+0xc], 0    ; arg2: allocate an index?
0x0066fcb1  mov [esi+0xc], eax           ; template->nameKey
0x0066fcb5  je  0x66fcc0
0x0066fcb7  mov eax, [edi+0x10]          ; center->nextIndex
0x0066fcba  mov [esi+0x38], eax          ; template->bitIndex = nextIndex
0x0066fcbd  inc dword ptr [edi+0x10]     ; ++nextIndex  -- no cmp, no clamp, no assert
```

One bit per **distinct upgrade name**. INI overrides are free: the override path at `0x0066fd3a`
saves the existing index (`mov edi, [esi+0x38]`), retires the old template, then calls `newUpgrade`
with `allocIndex = 0` and restores the index onto the replacement (`0x0066fd75`).

The index is handed out *before* the `Type` field is ever parsed, so `Type = OBJECT` upgrades cost
exactly as much as `Type = PLAYER` ones. This is a common wrong assumption — object upgrades are not
cheaper.

```
sizeof(UpgradeTemplate) = 0x9c
  +0x08  AsciiString name
  +0x0c  NameKeyType nameKey
  +0x38  Int         bitIndex          <-- the mask bit this upgrade owns
  +0x64  UpgradeTemplate *next         (singly-linked; list head at UpgradeCenter+0x0c)
  +0x94  Bool        superseded        (set at 0x0066fd62 when an override retires it)

TheUpgradeCenter = 0x00de45a0
  +0x0c  UpgradeTemplate *head
  +0x10  Int  nextIndex                <-- the allocator
  +0x18  std::vector<UpgradeTemplate*> retired templates
```

## Nothing checks the bit index

Every consumer performs the same unguarded `mask[idx >> 5] |= 1 << (idx & 31)`. The canonical form,
from `parseUpgradeMask` at `0x0066f6a7`:

```
0x0066f6a7  8b4e38     mov ecx, [esi+0x38]      ; bitIndex, straight off the template
0x0066f6aa  8b5510     mov edx, [ebp+0x10]      ; the destination mask
0x0066f6ad  8bc1       mov eax, ecx
0x0066f6af  c1e805     shr eax, 5               ; word = idx / 32
0x0066f6b2  8d0482     lea eax, [edx + eax*4]   ; &mask[word]   <-- word is never bounded
0x0066f6b5  33d2       xor edx, edx
0x0066f6b7  83e11f     and ecx, 0x1f            ; bit = idx % 32
0x0066f6ba  42         inc edx
0x0066f6bb  d3e2       shl edx, cl
0x0066f6bd  0910       or  dword ptr [eax], edx
```

Scanning `.text` for the full idiom (`mov reg,[reg+0x38]` followed within 0x30 bytes by both
`shr ...,5` and `and ...,0x1f`) yields **33 sites**. Checking a ±0x30 byte window around each for any
comparison against `0x24`, `0x90`, or `1152`: **0 of 33**.

## What the overflow lands in

Masks are allocated in adjacent pairs, so the write does not fall off into unmapped memory — it
falls into a live mask. `0x006ae649` clears the same bit in both of the **player's** masks back to
back, which pins that layout exactly:

```
0x006ae649  8b4f38          mov ecx, [edi+0x38]
0x006ae65a  8d9496bc000000  lea edx, [esi + edx*4 + 0xbc]    ; Player: upgrades in progress
0x006ae663  211a            and dword ptr [edx], ebx
0x006ae665  8b4f38          mov ecx, [edi+0x38]
0x006ae675  8d94964c010000  lea edx, [esi + edx*4 + 0x14c]   ; Player: completed = 0xbc + 0x90
0x006ae67e  211a            and dword ptr [edx], ebx
```

`esi` is a `Player`, not an `Object`: this is `Player::removeUpgrade`, and the same function walks
the player's upgrade list off `[esi+0x9c]` (`0x006ae643`) while its caller at `0x006ae5d8` reads
`[ebx+0x30c]`, the player's default `Team`.

The same adjacency shows up at `0x0090da40` / `0x0090da7e` (`+0x04` / `+0x94`, the
`RequiredUpgrades` / `ExcludedUpgrades` runtime pair) and at `0x006e2874` / `0x006e2887`
(`ebp-0xac` / `ebp-0x1c`, where `ebp` holds a struct pointer rather than a frame pointer — this
function is compiled with frame-pointer omission).

| mask | base | first out-of-range dword |
|---|---|---|
| player, in progress | `Player+0x0bc` | `Player+0x14c` — the player's completed mask |
| `TriggeredBy` | `+0x000` | `+0x090` — `ConflictsWith` |
| `RequiredUpgrades` | `+0x004` | `+0x094` — `ExcludedUpgrades` |
| `RequiredUpgrades` | `+0x0d4` | `+0x164` — `ForbiddenUpgrades` |
| object, completed | `Object+0x28c` | `Object+0x31c` — `Object::m_team` |

**Which mask belongs to which owner**, since the two pairs are easy to swap: the object carries one
mask and the player carries two. `UpgradeMux`'s condition test at `0x008b8fe0` names all three in six
instructions — `lea ecx,[edi+0x28c]` on the `Object` it holds in `edi`, then
`getControllingPlayer(edi)` (`0x0068b678`) and `lea ecx,[eax+0x14c]` on the result. That getter is
`mov ecx,[this+0x31c] / jmp Team::getControllingPlayer`, so `Object+0x31c` is the object's `Team*` —
the dword the object mask overflows into, and the reason the object-side overflow is *worse* than the
player-side one: bit 1152 on an object does not alias another mask, it sets bit 0 of a pointer.
[`live-object-model.md`](live-object-model.md) §3a pins the same three offsets live, with an
observable effect rather than an inference.

So upgrade 1152 aliases upgrade 0 of the neighbouring condition. `Required` reads as `Excluded`,
`in progress` reads as `completed`, `TriggeredBy` reads as `ConflictsWith`. Symptoms are upgrades
that appear already researched, buttons permanently greyed out, prerequisites satisfied that should
not be — affecting only upgrades defined late in load order, and presenting on units that have no
obvious relationship to each other.

## Budget

Counting `Upgrade <name>` block headers in the `data/data/ini` tree in this repo:

| file | upgrades |
|---|---|
| `upgrade.ini` | 392 |
| `createaheroupgrades.inc` (`#include` at `upgrade.ini:2868`) | 447 |
| `default/upgrade.ini` | 1 |
| **total** | **840** |

840 of 1152, leaving **312 free slots**.

That tree is **BFME2** data (no Angmar; `playertemplate.ini` lists six playable factions), while
`game.dat` is the ROTWK 2.01 binary. ROTWK ships Angmar's upgrades on top of this set, so real
headroom on a ROTWK install is **less than 312**. The 1152 ceiling is a property of the binary and
does not move; only the starting balance does.

312 is well within reach of a large mod, which is why this presents as a recurring complaint rather
than a theoretical limit.

## Two adjacent footguns

Distinct from the count limit, but blamed on it often enough to note:

- **`parseUpgradeMask` clears the whole mask on entry** (`memset(mask, 0, 0x90)` at `0x0066f613`).
  Mask fields do not accumulate. A second `RequiredUpgrades =` line in the same block silently
  discards the first.
- **Indices are assigned in INI load order**, so they are a pure runtime artifact. Stable within a
  run; not stable across mod versions.

## Assessment

Widening the mask is not an in-place edit. 144 bytes is baked into `Player`, `Object`, the
`UpgradeTemplate`-adjacent structures, all 33 index sites, and the five helper functions above. Every
mask is *mid-struct* in its owner, so growing it shifts the offset of every member declared after it
— the same offset-shift blocker as [`MAX_PLAYER_COUNT`](max-player-count.md), and for the same
reason. It is unlike [the CommandSet limit](commandset-button-limit.md), where the array was the last
member of one object and nothing else knew its size.

What is tractable is a **diagnostic** rather than a capacity increase: a guard at `0x0066fcb7` that
fails the INI load with a named error when `nextIndex` would reach 1152, instead of letting the
allocator run past the end. That converts an unexplainable class of bug into one message at load
time, and is small enough to fit the verify-then-write [`Patch`](../README.md) framework without
needing a `.cmdext` section. Not implemented.

## Verification notes

Verified directly against the binary: the 36-dword mask width (five independent sites plus the
field-table offset deltas), the `newUpgrade` allocator and its absence of a cap, the override path
reusing indices, `sizeof(UpgradeTemplate) = 0x9c` and the member offsets listed, the 33 index sites
and the absence of a bound constant at every one, the `Player+0xbc` / `Player+0x14c` adjacency and
which owner each mask belongs to, and the upgrade counts in `data/data/ini`.

Not established: how upgrade masks are serialized into savegames and replays — if that is by index
rather than by name, adding or reordering upgrade definitions would break cross-version save
compatibility as a separate issue from the count limit.
