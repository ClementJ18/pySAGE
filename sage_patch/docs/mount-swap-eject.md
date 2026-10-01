# Passengers across a mount swap

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`.

**Symptom.** Edain's Aragorn (`GondorAragornEntwicklung3`) carries Pippin in a `TransportContain`
(`PassengerFilter = NONE +HOBBIT`, `EjectPassengersOnDeath = Yes`). When Aragorn takes his crowned
form (`ToggleMountedSpecialAbilityUpdate` with `MountedTemplate = GondorAragornEntwicklung4`)
while Pippin is riding, Pippin is gone. There is no death animation and no death FX, and he does
not come back.

**Verdict:** the swap never touches the old object's contain modules, and the old object is then
removed with `GameLogic::destroyObject`. Anything still inside is deleted with it.
`EjectPassengersOnDeath` is read only by `OpenContain::onDie`, and a retire is not a death.
`mount-swap-eject` hooks the retire, just before `destroyObject`, and empties every ejecting
contain the way death would.

- **Cost:** one 6-byte `jmp` and a 90-byte cave (`.mntejc`). No INI change: the existing
  `EjectPassengersOnDeath` on the contain is the opt-in.
- **Risk:** low. The cave only makes the two calls stock death makes, on the modules stock death
  would make them on, and skips any module that isn't an `OpenContain`.
- **Status:** built ([`patches/mount_swap_eject.py`](../patches/mount_swap_eject.py)), statically
  verified against the Edain install's `game.dat` and the stock one, and emulated.
  **Not runtime-verified.**

## 1. The swap and the retire

The swap (`0x008b140d`, [`lifetime-transform.md`](lifetime-transform.md) §1a) builds the
replacement, then copies across experience, health, the drawable, the team, the selection, the
special-power timers and, at `0x008b1608`, the AI's current command (`Object+0x260` is the
`AIUpdate`). Nothing reads `Object+0x258` (the contain) or walks the modules.

A step later, slot 19 (`0x008b125f`), or its sibling's tail at `0x008b2082`, jumps to the retire
at `0x008b1e9a`. `lifetime-fields` calls the retire directly as well:

```
008b1e9a  push esi
008b1e9b  mov  esi, [ecx+8]            ; the old Object
          ...                          ; hide the drawable, drop it out of the UI
008b1ed9  mov  ecx, [0x00de412c]       ; TheGameLogic          <- hooked (6 bytes)
008b1edf  push esi
008b1ee0  call 0x0062bbab              ; destroyObject(old)
008b1ee5  pop  esi
008b1ee6  ret
```

The only branch into `0x008b1ed9..0x008b1ee6` is the `je` at `0x008b1ece`, and it lands exactly on
the hook's first byte.

## 2. What death does with the flag

`EjectPassengersOnDeath` is byte `+0x82` of `OpenContainModuleData` (row `0x00c5a050` of the base
field table at `0x00c59f30`; `KillPassengersOnDeath` is `+0x83`). `OpenContain::onDie`
(`0x00867120`) is reached through the die interface at module `+0x28`, and `TransportContain` uses
it unchanged (constructor `0x0086b67d` stamps die vtable `0x00c5dfa0`):

```
00867151  cmp  byte [eax+0x82], 0      ; EjectPassengersOnDeath
00867158  je   .kill_all               ;   no -> destroy every passenger
0086715a  ...                          ; DamagePercentToUnits > 0 -> processDamageToContained
00867173  lea  ecx, [esi-0x28]         ; the module
00867178  call [eax+0x64]              ; kill the riders who are not free to exit
0086717b  lea  ecx, [esi-8]            ; its contain interface (module +0x20)
00867180  push 0
00867182  call [eax+0xa8]              ; removeAllContained(false)
```

- **`+0x64`** on `TransportContain` (`0x0086b05f`) asks slot `+0x6c` (`0x0086a2d0`) about each
  passenger. On firm ground the answer is yes. A passenger who can't get out from where the
  transport is (it is airborne, or there is nowhere to exit to) is killed, or destroyed if the
  transport's flag at `ModuleData+0x142` is set. `OpenContain`'s own `+0x64` is a bare `ret`.
- **`+0xa8`** is `OpenContain::removeAllContained` (`0x00866675`, inherited by `TransportContain`
  through interface vtable `0x00c5a690`). It pops the item list front until the list is empty,
  each time through `removeFromContain` (`0x00865eb6`): `onRemoving`, the contained status
  cleared, the passenger's team and position restored. The passenger is back in the world where
  the container stands.

The cave makes those two calls in that order. It leaves out `processDamageToContained`, because
`DamagePercentToUnits` is damage from the container dying, and a swap isn't one.

## 3. Which contains

`Object+0x258` holds only one contain. The constructor's module loop (`0x0069a3be`) stores every
module's non-NULL `getContain()` there without checking whether one is already set, so the
**last** contain declared wins. Edain's Gandalf declares the hobbit `TransportContain` and then
the ring pickup `CitadelSlaughterHordeContain`, so his `+0x258` is the ring. The cave therefore
walks the whole module list at `Object+0x24c` (NULL-terminated, the list `destroyObject` walks),
and for each module:

1. **Is it an `OpenContain`?** The module's behaviour interface (`+0x0c`) has `getContain` at
   slot `+0x08`. The cave acts only if that slot is `OpenContain::getContain` (`0x008a18e0`, which
   answers module `+0x20`). That match is what guarantees that `+0x04` is an
   `OpenContainModuleData` and that `+0x20` is the contain interface.
2. **`EjectPassengersOnDeath = Yes`?** Otherwise it is left alone: passengers are deleted as
   before. A contain that doesn't ask for its passengers to survive its container's death does
   not get them back from a swap either.
3. **Not a horde?** If `getHordeIface` (`+0x7c`) is non-NULL, the contain is skipped. The swap
   creates the new horde with its own members, and freed old members would be left standing
   beside it.

In Edain's INI, the objects this changes are the forms with a hobbit `TransportContain`: Aragorn
(`GondorAragornEntwicklung3` and its children), Gandalf, `GondorGandalf_forHK` and mounted
Thranduil. No horde and no ring contain sets the flag.

## 4. The patch

```
push ebx / push edi
mov  ebx, [esi+0x24c]
.next:
mov  eax, [ebx]                ; module
test eax, eax / je .done
add  ebx, 4
mov  ecx, [eax+0xc]            ; behaviour-interface vtable
cmp  dword [ecx+8], 0x008a18e0 / jne .next
mov  ecx, [eax+4]
cmp  byte [ecx+0x82], 0 / je .next
lea  edi, [eax+0x20]
mov  ecx, edi / mov eax, [edi] / call [eax+0x7c]
test eax, eax / jne .next
lea  ecx, [edi-0x20] / mov eax, [ecx] / call [eax+0x64]
push 0 / mov ecx, edi / mov eax, [edi] / call [eax+0xa8]
jmp  .next
.done:
pop  edi / pop ebx
mov  ecx, [0x00de412c]         ; displaced
jmp  0x008b1edf                ; push esi / call destroyObject
```

`apply` asserts the whole retire, `getContain` and the `onDie` eject arm, and decodes the
`destroyObject` call the cave rejoins in front of. `lifetime-fields` anchors only the retire's
first 24 bytes, which this patch leaves alone. The two patches apply in either order, and so do
this one and `mount-health-ratio`.

`tests/sage_patch/test_mount_swap_eject.py` runs the retire under unicorn over a fake object whose
modules are an ejecting transport, one with the flag off, a horde, a non-`OpenContain` and a
second ejecting transport. Stock makes no calls. Patched calls `+0x64` on each transport module,
then `+0xa8(0)` on its interface, and touches nothing else.

## 5. Without the patch

No INI change makes the swap spare a passenger. The only data-side way out is to not carry one
across it, for example by gating the transform's button while a hobbit is aboard, or by putting
an `EVACUATE` in front of it.

## 6. Open

- **Runtime.** Level Aragorn to 10 with Pippin riding and take the crowned form. Pippin should be
  standing beside him with his experience intact. Then do the same with Gandalf, whose ring
  contain is the one at `+0x258`. Logic-side, so every peer needs the patch.
- **Re-boarding.** Pippin is dropped, not carried across. Keeping him mounted would take moving
  him into the new object's contain inside the swap, which is the other fix this one was chosen
  over.
