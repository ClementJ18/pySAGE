# Experience credited to a horde object itself

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR), read from the
repo's `game.dat` on 2026-10-22.

- **Cost:** one six-byte call repointed (`call rel32` and a `nop`) and a `0xEB`-byte `.hordexp`
  cave. No INI keyword is added.
- **Risk:** low. A member killer takes the stock path unchanged. Only experience whose killer is
  the horde object itself is rerouted, and an empty horde keeps the stock call.
- **Status:** static-verified, and the cave emulated over the real `game.dat`
  (`tests/sage_patch/test_horde_self_experience_emulated.py`). **Seen live, 2026-10-23**, in
  Edain's `tests/test_bloodthirsty_combo_level.py`: one level-1 `MordorFighterHorde` ate
  another, it and every orc in it held `Upgrade_ObjectLevel1` and `2` with a banner carrier,
  and the `MordorAufseherFighterHordeComboHorde` it made with an overseer kept the level and
  the banner.

```
sage-patch apply horde-self-experience --in game.dat.backup --out game.dat
```

## The complaint

Reported on Edain (2026-10-22): a Mordor orc horde that eats another with its sacrifice
(`BloodthirstyUpdate`) reaches level 2 and gets its banner, but once it joins an overseer the
combo horde is level 1 and the banner is gone.

## Why

### A horde keeps one experience account per member template

`HORDE_EXPERIENCE_ADD` (`0x00873A02`, horde-interface slot `+0xC0`, `__thiscall`, `ret 8`) takes
`(member, Real xp)`. It keys an account in the interface's map (`+0x13C`) by the **member's**
template id (the word at `ThingTemplate+0x5E8`), adds `xp` to it, sets every member of that
template to the account (callback `0x0086BC09`, through `EXPERIENCE_TRACKER_SET_ABSOLUTE`), and
raises the horde object's own tracker to the account.

### The kill scorer passes the killer as the member

The kill scorer (`0x00695475`, `__thiscall` on the killer, `(victim, ?, Real modifier)`) finds the
horde of the killer through `0x00694BF8` (the killer itself when it is a horde, else the horde
containing it) and credits it:

```
00695504  mov  ecx, esi                 ; the killer
00695506  call 0x694bf8                 ; its horde's interface
0069550b  mov  edi, eax
...
0069553f  fld  dword [ebp+0x10]         ; xp
00695542  mov  eax, [edi]
00695544  push ecx
00695545  fstp dword [esp]
00695548  push esi                      ; the killer, as the member
00695549  mov  ecx, edi
0069554b  call [eax+0xc0]               ; HORDE_EXPERIENCE_ADD(killer, xp)
```

A member killer keys the account by its own template, so its group ranks up and the horde
follows.

### A sacrifice makes the horde object the killer

`BloodthirstyUpdate` (`ModuleData` table `0x00C557B0`; the sacrifice at `0x00850EF0`) calls the
scorer on the eating horde object, with the eaten horde as the victim and `ExperienceModifier` as
the modifier (`0x00850F43`-`0x00850F4A`). The killer is now the horde itself, so the account is
keyed by the **horde's** template (`MordorFighterHorde`). No member has that template: the
callback sets nobody, and only the horde object's tracker rises. That is enough for its level
and its banner carrier, which `0x008719E4` spawns from the horde object's own rank.

### A merge rebuilds the horde from its members

When members join a horde (the loop at `0x00876A4E`), each member's tracker XP is written to its
group's account and the horde object is set to the **highest** member XP
(`EXPERIENCE_TRACKER_SET_ABSOLUTE` at `0x00876AFA`). A `ComboHorde` merge goes through it, so the
sacrificed rank, which no member holds, is gone, and the combo is level 1 with no banner.

Combat XP survives a merge because it lives in the members. Edain's dwarf pony-pack combos keep
their level for that reason (seen live, 2026-10-17).

### Why an INI fix does not work

- A horde's `LevelUpUpgrade` (`0x008B7F90`) gains `min(LevelsToGain, LevelCap - level)` levels,
  measured on the horde object, which the sacrifice has already raised, so it gains none. When
  it does gain, it raises each member one level per level through slot `+0xC4`
  (`0x00876C23`).
- A member's `LevelUpUpgrade` on `Upgrade_ObjectLevel<n>` raises the member's tracker but not its
  group account, and the next combat kill sets the member back to `account + xp`. With a horde
  `LevelUpUpgrade` (Basic Training) it also stacks with the `+0xC4` raise, one level too many.

## The patch

The scorer's `call [eax+0xC0]` becomes `call distribute`. `distribute(killer, xp)` stands in for
the slot, with the same arguments and `ret 8`:

- **A member killer** (`killer != [iface-0x114]`, the module's owning object at module `+0x08`):
  a tail jump to the interface's own slot. Nothing changes.
- **The horde object itself:** walk the contained list (`[horde+0x258]`, list sentinel at
  `+0x34`, `Object` at node `+0x08`) and keep the first member of each experience group, up to
  eight groups. Call the slot once per kept member with the **full** `xp`, as if a member of each
  group had made the kill. Each call sets its group and raises the horde.
- **No members** (no contain, or an empty list): the stock call, on the horde.

What changes in game:

- A sacrifice ranks up the members, so a merge, a later combat kill and anything else that reads
  the members keep it.
- Each group of a mixed horde gets the whole amount, the way the native `LevelGrantSpecialPower`
  per-member path reaches every group.
- Sacrifice XP now adds to combat XP. Stock, the horde's own account held only sacrifice XP, and
  the horde object was raised to it, never past its combat XP: a veteran horde's sacrifice was
  worth little. Now the sacrifice is added to the members' accounts on top of what they earned.

## Not covered

- Who else credits a horde object directly. Any other caller of the scorer with a horde as the
  killer is rerouted the same way. Only `BloodthirstyUpdate` was traced.
- The stock account keyed by the horde's template is no longer filled by a sacrifice. Nothing read
  outside `HORDE_EXPERIENCE_ADD` was found to depend on it.
