# `replace-self-rubble` — a `ReplaceSelfUpgrade` must not bulldoze the rubble it lands on

**Status: implemented as `replace-self-rubble`**
([`../patches/replace_self_rubble.py`](../patches/replace_self_rubble.py)). It applies and verifies
against the real `game.dat` and composes in either order with `foundation-rebind`, which reads the
same `ReplaceSelfUpgrade` creation `call`. Every address below was recovered **statically** from
ROTWK `game.dat` build `2.01.2614.37001` (ImageBase `0x400000`) on 2026-09-30 with `explore.py`.
**Not yet runtime-verified**: §6 is the in-game check.

## 0. The bug

A citadel whose death leaves rubble (`KeepObjectDie`, rebuilt later — Edain's
`MordorFortressCitadel` carries `KeepObjectDie` and `RubbleRiseUpdate`) disappears when a structure
that overlaps it is changed by a `ReplaceSelfUpgrade`. The rubble is destroyed outright, so there
is nothing left to rebuild.

## TL;DR

- `ReplaceSelfUpgrade::upgradeImplementation` (`0x008BB5FA`) does not create the replacement
  through `ThingFactory` directly. It calls **`BuildAssistant::buildObjectNow`** (`0x00797796`,
  `TheBuildAssistant` vtable `+0x38`) at `0x008BB8D9`.
- `buildObjectNow` **clears the construction site first**, unless the constructor is a `DOZER` or
  the new template is `NO_COLLIDE` (`0x007977CF`–`0x007977E8`). The clearing,
  `clearRemovablesForConstruction` (`0x00796576`), walks every object the new footprint collides
  with and calls `GameLogic::destroyObject` on each one that `isRemovableForConstruction`
  (`0x007940A6`) accepts.
- That predicate accepts **anything effectively dead** (`Object+0x458` bit 0). Rubble is exactly
  that: a structure that died and was kept. So the rubble citadel under the replacement's
  footprint is destroyed.
- The fix is a single repointed `call`. In the clearing loop the predicate call (`0x007965E6`) goes
  to a cave that answers **"not removable" for an effectively-dead object**, but only when
  `ReplaceSelfUpgrade` called `buildObjectNow` and `buildObjectNow` called the loop. `SHRUBBERY`
  and `CLEARED_BY_BUILD` are still cleared, as stock clears them dead or alive. Every other
  caller of the clearing loop is untouched.

## 1. The path from the upgrade to the destroy

```
008bb8b4  a1 0082de00        mov  eax, [TheBuildAssistant]
008bb8b9  8b 18              mov  ebx, [eax]                 ; its vtable
...
008bb8d5  57                 push edi                         ; the template
008bb8d6  ff 75 e0           push [ebp-0x20]                  ; the old object, as "constructor"
008bb8d9  ff 53 38           call [ebx+0x38]                  ; buildObjectNow  (0x00C30810 -> 0x00797796)
008bb8dc  8b f8              mov  edi, eax                    ; the replacement
```

`buildObjectNow(constructor, template, pos, angle, owner)`, `ret 0x14`:

```
007977c9  8b 7d 08           mov  edi, [ebp+8]                ; constructor
007977cc  8b 47 04           mov  eax, [edi+4]
007977cf  f6 80 09 01 00 00 40  test byte [eax+0x109], 0x40   ; constructor is DOZER (14)
007977d6  75 34              jnz  .skip
007977d8  f6 86 0b 01 00 00 40  test byte [esi+0x10b], 0x40   ; template is NO_COLLIDE (30)
007977df  75 2b              jnz  .skip
007977e1  f6 86 1a 01 00 00 20  test byte [esi+0x11a], 0x20   ; template KindOf 149
007977e8  75 22              jnz  .skip
...
007977f3  e8 7e ed ff ff     call 0x796576                    ; clearRemovablesForConstruction
...
00797807  e8 59 fc ff ff     call 0x797465                    ; move units off the footprint
```

The constructor is the old object, not a dozer, so the site is cleared.

`clearRemovablesForConstruction(template, pos, angle)` builds a would-collide filter from the
template's geometry at `pos`/`angle` (`0x0067C5F3`), iterates `ThePartitionManager` over it, and
for each hit:

```
007965e3  52                 push edx                         ; the object
007965e4  8b cf              mov  ecx, edi
007965e6  e8 bb da ff ff     call 0x7940a6                    ; isRemovableForConstruction  <- hooked
007965eb  3c 01              cmp  al, 1
007965ed  75 18              jne  .next
007965ef  8b 42 04           mov  eax, [edx+4]                ; edx read again: must survive the call
007965f2  f6 80 0f 01 00 00 04  test byte [eax+0x10f], 4      ; KindOf 58 is never destroyed
007965f9  75 0c              jnz  .next
007965fb  8b 0d 2c 41 de 00  mov  ecx, [TheGameLogic]
00796601  52                 push edx
00796602  e8 a4 55 e9 ff     call 0x62bbab                    ; GameLogic::destroyObject
```

and the predicate (`ret 4`, `this` unused):

```c
if (!obj)                              return false;
if (tmpl->isKindOf(INERT))             return false;   // 89
if (tmpl->isKindOf(TAINT))             return false;   // 152
if (tmpl->isKindOf(SHRUBBERY))         return true;    // 6
if (tmpl->isKindOf(CLEARED_BY_BUILD))  return true;    // 51
return obj->[0x458] & 1;                               // effectively dead
```

(The same predicate decides what does *not* block placement in `isLocationClearOfObjects`; see
[`castle-unpack-clearance.md`](castle-unpack-clearance.md) §2.4.)

## 2. Why it only bites a replacement

Ordinary construction runs the same clearing, but placement gets there first. A player can only put
a building where `isLocationClearOfObjects` allows. A `ReplaceSelfUpgrade` performs no placement
check against the rubble; `0x008BB23F` only tests `WALL_HUB` clashes and terrain height. It builds
wherever the old object stood, and its footprint can overlap a structure the old object already
overlapped harmlessly. While the citadel lives, the clearing leaves it alone (alive, so not
removable). Once it is rubble, the next upgrade of the overlapping structure destroys it.

## 3. The fix

**Hook:** `0x007965E6`, the `call isRemovableForConstruction` in the clearing loop. The five
bytes stay a `call`; only the displacement changes. The cave is 0x5D bytes in `.rsrubl`:

```
cmp  dword [ebp+4], 0x007977F8     ; the loop was called by buildObjectNow ...
jne  stock
mov  eax, [ebp]                    ; ... whose frame is the one above
cmp  dword [eax+4], 0x008BB8DC     ; ... and buildObjectNow was called by ReplaceSelfUpgrade
jne  stock
mov  eax, [esp+4]                  ; the object
test eax, eax
je   stock
test byte [eax+0x458], 1           ; effectively dead?
je   stock
mov  ecx, [eax+4]
test byte [ecx+0x108], 0x40        ; SHRUBBERY: stock clears it, keep doing so
jne  stock
test byte [ecx+0x10e], 0x08        ; CLEARED_BY_BUILD: likewise
jne  stock
xor  al, al                        ; not removable: the rubble stays
ret  4
stock:
jmp  0x007940A6
```

**Why a frame walk rather than a flag.** Both frames are laid out by MSVC's `__EH_prolog`
(`0x00A3CEF0`): `push -1; push handler; push fs:[0]; ...; mov [esp+0xc], ebp; lea ebp, [esp+0xc]`.
So in `clearRemovablesForConstruction` and in `buildObjectNow`, `[ebp]` is the caller's `ebp` and
`[ebp+4]` is the return address. The chain is therefore readable from the hook with no state. The
first comparison proves the loop's caller is `buildObjectNow`, so the `[ebp]` dereference is only
ever made into a `buildObjectNow` frame. The obvious alternative was to set a flag around the
`call [ebx+0x38]` at `0x008BB8D9`. That call is pinned byte-for-byte by `foundation-rebind`, and
rewriting it would break that patch. A flag would also need clearing on every exit, including a
nested `ReplaceSelfUpgrade` fired while the replacement is created.

**Register contract.** The loop re-reads `edx` after the call. The cave uses only `eax` and `ecx`,
which the stock predicate also clobbers. Stack effect is `ret 4` on both paths, as stock.

**Anchors** (`ANCHORS` in the patch, each disturbed in turn by the tests): the clearing loop, the
predicate, `__EH_prolog`, both functions' prologues, `buildObjectNow`'s `call` to the loop, the
`ReplaceSelfUpgrade` creation sequence, and the vtable entry `0x00C30810` that makes
`call [ebx+0x38]` mean `buildObjectNow`.

An `.rdata` table at `0x00D11500..` holds a run of increasing `.text` addresses, several of them
mid-instruction, and `0x007965E6` is one of them. It is not a dispatch table: nothing references it
and its entries are not instruction starts. The hook does not move that address anyway.

## 4. Blast radius

- **Only a `ReplaceSelfUpgrade`'s site clearing changes, and only for effectively-dead objects.**
  Ordinary construction, castle unpacks and scripted builds that go through `buildObjectNow` from
  anywhere else still clear rubble as stock does.
- A dead unit whose body lies under a replacement's footprint is no longer deleted instantly. It
  finishes its death as it would anywhere else.
- `moveObjectsForConstruction` (`0x00797465`) asks the unhooked predicate directly, so it still
  treats rubble as removable and does not try to move it. Structures are immobile anyway.
- **Simulation state.** Every peer needs the same binary.

## 5. Not covered, deliberately

- **The mount swap** (`SpecialAbility` `MountedTemplate`, `0x008B1483`, return `0x008B1489`) also
  replaces an object through `buildObjectNow` and so also clears rubble under the new footprint.
  It is left stock because no report ties it to this bug. Covering it means one more return
  address in the cave.
- **`ReplaceSelfUpgrade`'s own `WALL_SEGMENT` kill** (`0x008BB80D`–`0x008BB8AF`) builds a
  would-collide filter with `KindOf WALL_SEGMENT` and calls `Object::kill` on every wall segment
  under the new footprint. That is intended behaviour, for a hub upgrade replacing the segments it
  absorbs, and it cannot reach a citadel, which is not a `WALL_SEGMENT`.
- **Building on rubble by hand.** Placement treats rubble as non-blocking and the clearing then
  destroys it. Whether a player should be able to build over a rebuildable citadel is a design
  question for the data, not this bug.

## 6. In-game check

1. Let a citadel die and stay as rubble.
2. Upgrade the structure overlapping it that carries the `ReplaceSelfUpgrade`.
3. The rubble must still be there, still selectable for rebuild. Rebuild it and check that both
   structures stand.
4. Control: upgrade the same structure while a tree (`SHRUBBERY`) lies under the new footprint.
   The tree must still be cleared.

A breakpoint on the cave's `xor al, al` confirms it is the path taken. A breakpoint on
`0x00796602` (`destroyObject` in the loop) must no longer fire for the citadel.

## 7. Address table

| what | address |
|---|---|
| `ReplaceSelfUpgrade::upgradeImplementation` | `0x008BB5FA` |
| … its creation sequence / `call [ebx+0x38]` / return | `0x008BB8B4` / `0x008BB8D9` / `0x008BB8DC` |
| … its `WALL_SEGMENT` kill loop | `0x008BB80D`–`0x008BB8AF` |
| `TheBuildAssistant` / vtable / slot `+0x38` entry | `0x00DE8200` / `0x00C307D8` / `0x00C30810` |
| **`BuildAssistant::buildObjectNow`** (`ret 0x14`) | **`0x00797796`** |
| … its skip-clearing gates (`DOZER`, `NO_COLLIDE`, 149) | `0x007977CF`–`0x007977E8` |
| … its call to the clearing / return | `0x007977F3` / `0x007977F8` |
| `BuildAssistant::moveObjectsForConstruction` | `0x00797465` |
| **`BuildAssistant::clearRemovablesForConstruction`** (`ret 0xC`) | **`0x00796576`** |
| … the loop body / the hooked predicate `call` / its `destroyObject` | `0x007965E3` / **`0x007965E6`** / `0x00796602` |
| **`BuildAssistant::isRemovableForConstruction`** (`ret 4`) | **`0x007940A6`** |
| MSVC `__EH_prolog` | `0x00A3CEF0` |
| `Object+0x458` bit 0, effectively dead | `OBJECT_EFFECTIVELY_DEAD_FLAG` |

`KindOf` indices used above: `SHRUBBERY` 6, `DOZER` 14, `NO_COLLIDE` 30, `CLEARED_BY_BUILD` 51,
`INERT` 89, `TAINT` 152.
