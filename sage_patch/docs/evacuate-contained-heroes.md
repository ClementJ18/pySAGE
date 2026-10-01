# EVACUATE and passengers that carry a contain

**Symptom.** Put a ring-bearing hero (Edain's `DwarvenDain_mod`, any hero that can pick up the
One Ring) into a mineshaft (`TunnelContain`) with other units and press the exit-all button
(`Command = EVACUATE`). Everyone leaves except the hero. The per-slot exit buttons
(`EXIT_CONTAINER`) still let him out.

**Cause.** KindOf plays no part. A hero that can pick up the ring carries a contain module of its
own, the ring-pickup `CitadelSlaughterHordeContain`:

```ini
Behavior = CitadelSlaughterHordeContain ModuleTag_SlaughterMe
    PassengerFilter             = NONE +TheDroppedRing
    StatusForRingEntry          = HOLDING_THE_RING
    UpgradeForRingEntry         = Upgrade_RingHero Upgrade_FortressRingHero
    ...
```

The exit-all loop only knows two kinds of passenger: one with no contain, and one whose contain
is a horde. A passenger whose contain is anything else is skipped.

Static reading of build 2.01.2614.37001; not yet confirmed in a running game.

## 1. From the button to the loop

| step | where | what |
|---|---|---|
| ControlBar | `0x0094104C` | `GUICOMMAND_EVACUATE` (17) posts `MSG_EVACUATE` (`0x41E`) with no arguments: the selection is the subject |
| logic dispatch | `0x0077AA2F` | the `0x41A..0x435` arm: `jmp [eax*4 + 0x77D0B7]`, index `0x41E-0x41A = 4` -> `0x0077AD4E` |
| `MSG_EVACUATE` case | `0x0077AD4E` | `group->0x0076FB64(1)`, then `group->groupEvacuate(0)` at `0x007725DF` |
| `groupEvacuate` | `0x007725DF` | per member: with an `AIUpdate` (`+0x260`) it is a unit and gets a move/exit order; without one, if `KindOf` byte `+0x108` bit `0x80` is set, `[obj+0x258]->vtbl[+0x80](cmdSource)` - the contain's exit-all |
| `TunnelContain` `+0x80` | `0x0087CE8F` | `CONTAIN_EXIT_ALL_PASSENGERS(module, [iface-0x18], cmdSource)` |

The same `+0x80` target `0x0087CE8F` sits in five contain vtables: `HordeGarrisonContain`
(`0x00C5C9F0`), `TunnelContain` (`0x00C5DCE0`), `SlaughterHordeContain` (`0x00C5F0D0`),
`CitadelSlaughterHordeContain` (`0x00C5F2E8`) and `0x00C5F688`. A second wrapper, `0x0087A559`
(vtables `0x00C5C370`, `0x00C5DA10`), calls the same loop. So a garrisoned building drops the
hero in the same way a mineshaft does.

The case at `0x0077AD6F` (`[obj+0x258]->vtbl[+0x8C]`) is `MSG_EVACUATE_CONTESTERS`, not this
one. Every contain class has a `ret 4` in that slot.

## 2. The loop

`CONTAIN_EXIT_ALL_PASSENGERS` = `0x00991027`, `__stdcall(contain, cmdSource, arg)`. It copies the
contained list through contain-interface slot `+0x118` into a local `std::list` (sentinel in
`[ebp+8]`), then:

```
0099105e  mov  eax, [esi+8]            ; passenger
00991061  mov  ecx, [eax+0x258]        ; its own contain
00991067  test ecx, ecx
00991069  je   0x991086                ;   none -> aiExit arm
0099106b  mov  eax, [ecx]
0099106d  call [eax+0x7c]              ; getHordeIface
00991070  test eax, eax
00991072  je   0x99109e                ;   not a horde -> NEXT PASSENGER   <-- the bug
00991074  push [ebp+0x10]
00991077  mov  edx, [eax]
00991079  push [ebp+0xc]
0099107c  mov  ecx, eax
0099107e  call [edx+0x84]              ; horde: the whole battalion exits
00991084  jmp  0x99109e
00991086  mov  eax, [eax+0x260]        ; AIUpdate
0099108c  test eax, eax
0099108e  je   0x99109e
00991090  push [ebp+0x10]
00991093  lea  ecx, [eax+0x20]
00991096  push [ebp+0xc]
00991099  call 0x7716c1                ; aiExit(container, cmdSource)
0099109e  mov  esi, [esi]
009910a0  cmp  esi, [ebp+8]
009910a3  jne  0x99105e
```

`getHordeIface` (`CONTAIN_GET_HORDE_IFACE_SLOT` `+0x7C`) is `0x00851E97`, `xor eax, eax; ret`, for
`CitadelSlaughterHordeContain` and `SlaughterHordeContain` (and `TunnelContain`). Only the
`HordeContain` family answers it (`0x00872A6F`). A ring hero therefore reaches `0x00991072` with
`eax = 0` and never reaches either exit.

The per-slot `EXIT_CONTAINER` button doesn't go through this loop. It orders one object out
directly, which is why that button still works.

## 3. Fixes

**INI.** None that keeps ring pickup. The pickup fields (`StatusForRingEntry`,
`UpgradeForRingEntry`, `ObjectToDestroyForRingEntry`) exist only on the slaughter contains. A
module can't be added or removed while the hero is in the tunnel, and the only contains that
answer `getHordeIface` are the horde family, which can't pick up the ring. Giving the hero any
non-horde contain brings the bug back.

**Patch: `evacuate-contained-heroes`**. The seven bytes at `0x00991070`
(`test eax, eax / je / push [ebp+0x10]`) become a `jmp` into a `.evacht` cave:

```
test eax, eax
je   .no_horde
push dword [ebp+0x10]      ; displaced
jmp  0x991077              ; horde arm, unchanged
.no_horde:
mov  eax, [esi+8]          ; the passenger again
jmp  0x991086              ; aiExit arm
```

A passenger with a non-horde contain now leaves by the same `aiExit` a plain unit gets. One with
a contain and no `AIUpdate` is still skipped, as a plain one without AI is today. Hordes and plain
units are unchanged.

`tests/sage_patch/test_evacuate_contained_heroes.py` runs the stock and patched loop bytes
under unicorn over a unit, a battalion, a ring hero and an AI-less contain-carrier. Stock sends
out the first two. Patched sends out the first three.

## 4. Still open

- Not played. The check: put Dain and a battalion in a dwarven mineshaft, press evacuate, and
  confirm he leaves. Do it once while he holds the ring, then again with a garrisoned tower.
  Logic-side, so every peer needs the patch.
- `0x0076FB64(1)`, which the `MSG_EVACUATE` case calls on the group first, is not identified.
  The fix doesn't depend on it.
