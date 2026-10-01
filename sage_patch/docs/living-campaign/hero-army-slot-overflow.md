# Five leaders in one territory — the hero-army slot cap

Engine build `2.01.2614.37001`, ImageBase `0x400000`. **Static analysis, 2026-10-01. Nothing here
has been run in game, and the faulting instruction has not been observed.**

**Scoped, not built.** Reported: the War of the Ring game crashes once a fifth `PlayerArmy` (army
with a leader) of the same player moves into one territory.

## 1. Where "four" comes from: authored data, not a constant

A region parks its armies on authored spots. The `Region` field table (`0x00C4C8A0`) has two
coordinate-list rows, both parsed by `0x0042F2D2` (read a `Coord2D` with `0x0042F298`, then
`push_back` it with `0x0097D718`):

| keyword | positions | occupants | used for |
|---|---|---|---|
| `HeroArmySpot` | `region+0x104` | `region+0x1A0` | an army **with** a `HeroTemplateName` (`army+0x18` non-empty) |
| `GarrisonArmySpot` | `region+0x110` | `region+0x1AC` | an army without one |

Positions are `vector<Coord2D>` (stride 8). Occupants are a `vector<vector<Army*>>` (stride 12), one
inner vector per spot, sized to the position count by `0x007F51C9` (resize via `0x007F51A2`).

**Every one of Edain's 100 regions authors exactly four `HeroArmySpot`s** (`livingworldregions.inc`:
400 hero spots, 100 garrison spots). Retail authors three per region (114 / 38). Every Edain story
and recruited army carries a `HeroTemplateName` ([`force-battle.md`](force-battle.md)), so every
Edain army competes for the four hero spots. Four leaders fit, and the fifth does not.

## 2. The slot functions

**`Region::reserveArmySlot(Army*, Coord2D* out) -> bool`, `0x007F3D27`, `ret 8`.**

```asm
007f3d35  call ASCII_STRING_IS_EMPTY        ; army+0x18, the hero name
007f3d3c  jne  0x7f3d4c                     ; no hero -> Garrison lists
007f3d3e  lea  ebx, [esi+0x104]             ; HeroArmySpot positions
007f3d44  lea  eax, [esi+0x1a0]             ;           occupants
...
007f3d58  mov  edi, [eax]                   ; <- hook site, 5 bytes, see section 4
007f3d5a  mov  eax, [eax+4]
007f3d5d  ...  eax = count (idiv 0xC)
007f3d6d  mov  edx, [ecx+4] / sub edx,[ecx] / test edx,0xFFFFFFFC
007f3d78  je   0x7f3d8b                     ; first EMPTY spot wins
007f3d82  xor  al, al                       ; none empty -> return false, *out untouched
007f3d8b  push_back(occupants[esi], army)   ; 0x0090BE00
007f3da1  *out = positions[esi]; return true
```

**`Region::releaseArmySlot(Army*)`, `0x007F2199`, `ret 4`.** It picks the same list by the same
test and calls `0x007F2121`, which searches **every** spot's inner vector for the army and erases
it (`0x005FF944`). It is a no-op for an army holding no spot.

The inner vector is the important detail. **A spot can already hold several armies.** The engine
just never puts a second one there, because the search accepts only an empty spot.

## 3. The callers, and which of them can fault

| call | in | return checked? | on `false` |
|---|---|---|---|
| `0x006B46BD` | the move-snap pass (`0x006B45C7`, phase 1, just before `LIVING_WORLD_CONFLICT_PASS`) | **yes** | the army's path end is not snapped to a spot; it stands where its path ends. No fault in this function |
| `0x006B736F` | `LivingWorldLogic::spawnArmy` (`0x006B7229`), hero army | **no** | `ARMY_SET_POSITION` (`0x0071B39E`) is called with `[ebp-0x24]`, **an uninitialised stack `Coord2D`** |
| `0x006B73A9` | `spawnArmy`, hero-less army with nothing to fold into | **no** | the same, with `[ebp-0x1C]` |

The move-snap pass is two loops over every player's armies (`player+0x1E4`) that have a pending
path (`0x0071A87D`). The first loop releases each moving army's spot in the region it is leaving
(`0x006B462F`). The second reserves a spot in the destination (`0x0071A8DC`, the path's end region)
and, on success, rewrites the path's last waypoint to it (`0x0071B169`).

So the reported trigger, a fifth leader *moving* in, takes the checked path, and **the static read
shows no fault there.** The fifth army arrives un-slotted, standing on its path end. Something
downstream then fails. The leading candidates, none confirmed:

1. **An un-slotted army is later handed to `spawnArmy`'s path.** Recruiting at a fortress spawns
   a hero army, and so does a scripted `SpawnArmy`, a carryover respawn or a retreat. Any of these
   into a region already holding four leaders sets the army's position from stack garbage.
   `ARMY_UPDATE_REGION` then resolves a region from that position, and everything that trusts it
   (conflict pass, AI planner, icon draw) is reading nonsense. This is a real bug in any case, and
   a plausible fault.
2. **Something assumes every army in a region holds a spot.** No such reader was found. Every
   static user of `+0x1A0` / `+0x1AC` is one of: reserve, release, the constructor (`0x007F5098`),
   the destructor (`0x007F4A08`), the resize (`0x007F51C9`) or xfer (`0x007F54E8`, which re-registers
   each occupant through `0x006B98E0` on load). Still, an un-slotted army that later *leaves* runs
   release for a spot it does not hold, and an indirect reader may have been missed.
3. **The battle, not the move.** If the territory is contested, five or more leaders on one side
   go into the battle. `createBattle` (`0x0060F9D1`) and the `LivingWorldBattle` constructor
   (`0x007F869C`) walk plain vectors with no fixed cap. The battle map's per-player army spawn
   points have not been checked.

Which one it is decides whether the patch below is the whole fix, so §5 settles it before
building.

## 4. The patch: `hero-army-slot-overflow`

**Never fail a reservation while the region has any spot. Pick the least-occupied spot instead
of only an empty one.** With a free spot available, this behaves exactly like stock: the first
empty spot is the least occupied, and ties go to the lowest index. Without one, the fifth leader
shares a spot, and the inner vector already supports that. Release needs no change, because
`0x007F2121` already searches every spot.

This makes every caller succeed, so it also closes candidate 1's uninitialised read with no
change to `spawnArmy`. It covers garrison spots too, by the same code path.

### Site

| site | stock | becomes |
|---|---|---|
| `0x007F3D58` | `8B 38 8B 40 04` (`mov edi,[eax]` / `mov eax,[eax+4]`) | `jmp <cave>` |

Five bytes, two whole instructions, and no branch lands inside them (`0x007F3D4A` jumps *to*
`0x007F3D58`, which is fine). No shipped patch touches `0x007F3D27`–`0x007F3DB6`.

### Cave (~40 bytes, `allocate_section`)

On entry, `eax` = `&occupants`, `ebx` = `&positions`, and `esi`, `edi`, `ebx` are saved by the
prologue.

```asm
cave:
    mov   edi, [eax]                ; occupants.begin
    mov   ecx, [eax+4]
    sub   ecx, edi                  ; bytes
    jz    fail                      ; region authored no spots: stock false
    ; count = bytes / 12, walked by pointer, so no division is needed
    xor   esi, esi                  ; best index
    or    edx, -1                   ; best size (unsigned max)
    push  ebp                       ; scratch (ebp is restored before 0x7F3D8B reads [ebp+8])
    xor   ebp, ebp                  ; i
    lea   eax, [edi+ecx]            ; end
    mov   ecx, edi
loop:
    push  eax
    mov   eax, [ecx+4]
    sub   eax, [ecx]                ; inner size in bytes
    cmp   eax, edx
    jae   next
    mov   edx, eax
    mov   esi, ebp
next:
    pop   eax
    inc   ebp
    add   ecx, 12
    cmp   ecx, eax
    jb    loop
    pop   ebp
    jmp   0x007F3D8B                ; stock success arm: push_back into occupants[esi], *out = positions[esi]
fail:
    jmp   0x007F3D82                ; stock xor al,al epilogue
```

`0x007F3D8B` reads only `esi` (index), `edi` (occupants begin), `ebx` (`&positions`) and the
frame, all of which the cave leaves as the stock search would. The exact register shuffle is for
the build, not this scope. Only the contract above is required.

### Tests (house pattern)

- stock bytes at `0x007F3D58`, plus the surrounding `0x007F3D3E`–`0x007F3D8B` shape the cave relies
  on (the two `lea` pairs, the `0x7F3D82` fail arm, the `0x7F3D8B` success arm);
- apply → verify → detect round-trip, and `detect` returning `None` on a stock image;
- a unicorn run of `0x007F3D27` against a synthetic region (see `tests/sage_patch/synthetic.py`):
  4 spots with 0/1/1/1 occupants returns spot 0 (stock behaviour); 4 full spots return spot 0 with
  two occupants and `true`; 0 spots return `false`; a 1/0/1/1 region returns spot 1;
- composition: applies alongside every `living-world` patch, with no shared bytes.

### Cost

One site, roughly 40 bytes of cave, ~120 lines of patch and ~250 of tests. Static confidence is
high, because the data structure already allows sharing. What is not established is whether it
fixes the reported crash (§3).

### What it does not do

- **The fifth icon overlaps the first.** Two leaders on one spot draw at one position. Fanning them
  out means offsetting `*out` by occupant index in the cave, a small v2 once v1 is played. The INI
  half of the answer is free: an Edain region that should hold more leaders can author more
  `HeroArmySpot`s, and the engine sizes everything from the count.
- **It does not repair `spawnArmy`'s ignored return** for a region with *zero* spots of the right
  kind. No Edain region is like that, but the stock bug stays for such a map.

## 5. Settle the cause before building

The cheapest test that discriminates, all on `C:\RotWK` with the
[`crash-dump`](../../patches/crash_dump.py) patch applied:

| | experiment | tells you |
|---|---|---|
| 1 | Move five leaders into one **own, uncontested** territory and end the turn. Save the dump | whether the move alone crashes (candidates 1/2) or needs a battle (3). The dump's faulting instruction and `ebp` walk (the method in [`ai-disabled-regions.md`](ai-disabled-regions.md)) name the site |
| 2 | Same, into a contested territory | candidate 3 |
| 3 | Control: add a fifth `HeroArmySpot` to one Edain region and repeat 1 there | if five leaders then survive, the spot cap is the cause and §4 is the fix. If they still crash, the cause is elsewhere and the dump says where |
| 4 | Four leaders in a region, then recruit a fifth hero there | candidate 1 directly: the stack-garbage `spawnArmy` path |

Experiment 3 needs no patch and no dump, and on its own decides whether §4 is the right patch.

## Corrections made alongside

[`force-battle.md`](force-battle.md) §"`SpawnArmy`'s `Position` is snapped" had the two lists
swapped: a hero army takes the `HeroArmySpot` lists (`+0x104` / `+0x1A0`), and a hero-less one the
`GarrisonArmySpot` lists (`+0x110` / `+0x1AC`). Its open question 4 is answered by `0x007F2199`
above. Release is per army and searches every spot, but the move-snap pass releases only from the
army's *current* region (`ARMY_UPDATE_REGION` at `0x006B4621`). So a teleported `UseArmy` that never
released its old spot leaves that spot occupied by an absent army, which is one more way a region
can run out of spots.
