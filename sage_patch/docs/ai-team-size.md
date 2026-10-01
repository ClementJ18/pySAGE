# Sizing the AI's attack teams in battalions

The reverse-engineering behind [`patches/ai_team_size.py`](../patches/ai_team_size.py). ROTWK
`game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-09-29, with the
symptom measured live in two Edain skirmishes against an Imladris AI the same day.

## TL;DR

- The skirmish AI sends its army in one battalion at a time. Measured over two games against
  Imladris: 60% and 78% of the AI groups in contact with the enemy were a single battalion.
- Every attack team is a team prototype with a **min** (`+0x2D4`) and a **max** (`+0x2D0`) size,
  written by the tactic that owns it. The team builder declares a team finished once it has the min
  **and** either the max or enough threat to beat the target's defenders.
- It measures size with **`0x009A24A6`**, which counts every object on the team that is
  `CAN_ATTACK`, `HERO` or `SUPPORT`. A battalion puts its members on its own team
  (`HordeContain`, `0x00870667`), so **one battalion of five counts as six**.
- Six clears every min (3-5 for an attack on a structure) and equals the max of the attack
  tactics (6), so the threat test is never reached and the recruiter, which starts from the same
  count, stops adding battalions. The team leaves with whatever was idle when it formed.
- The fix: one 6-byte hook at the count's loop head, **`0x009A24C6`**, into a cave that skips any
  object carrying `HORDE_MEMBER`. See [§4](#4-the-patch).
- **AI-only by construction**: the count's only two callers are the team builder's update.
  **All factions** - the defect is in the engine, not in any one army; factions that build cheap
  battalions in bulk hide it because several are idle at once when a team forms.

## 1. From target to team

The tactical AI is the `SkirmishAI\AITacticalAI` tree; the source paths pushed to the random-number
calls are what tie code to files (the build has no RTTI).

| Address | What |
| --- | --- |
| `0x0090B4E7` | Target chooser: one slot per `TacticalAITargets` entry, with its `MaxTeamsPerTarget` |
| `0x0090C349` | Tactics generator, offensive arm: gated by `OffensiveTacticActivationProbability` (`AIDifficulty.cpp`), asks every prototype `vtable+4` "can I run against this target", clones a random yes (`vtable+0x30`) |
| `0x008F21F7` | `AITactic` init: for each team the tactic wants (`vtable+0x10`), asks `TheTeamFactory` for a prototype, tags it with the target type (`+0x2CC`) and index (`+0x2DC`), and calls `vtable+0xC` to size it |
| `0x008F121F` | Base sizing: an `ENEMY_STRUCTURE` target gets min = random 3..5 |
| `0x009B49CE` | `FormationAttack` sizing: min 2, max 6. `SimpleAttack` uses the base |

The offensive prototypes, from the generator's constructor: `SimpleAttack`, `FormationAttack`
(registered twice), `FlankAttack`, `PincerAttack`, `FeintAttack`, `AIBasePenetrationTroopsTactic`,
`SimpleSiege`, `SiegeGates`. Target types are the enum at `0x00DA1208`: 0 `ENEMY_STRUCTURE`,
1 `DEFENSIVE`, 2 `OPPORTUNITY`, 3 `EXPANSION`, 4 `TARGETLESS`.

## 2. The team builder

Vtable `0x00C88344`, update at `0x009A3366`. Two passes over the prototypes still recruiting
(`+0x31C` set):

1. **Recruit.** `OPPORTUNITY` prototypes first have their max clamped to 2 (`0x009A3345`). Then
   `0x009A32C1` gets or creates the team, takes `count = AI_TEAM_SIZE(team)` (`0x009A3311`) and,
   for a prototype with no unit list of its own, hands `&count` to `0x009A2E06`. That walks the
   player's objects, nearest first when the team has a place to go, and moves each acceptable idle
   one onto the team (`0x0069954A`) while `count < max`.
2. **Finish.** `0x009A33A7`:

```asm
009a33d1  call 0x009a24a6            ; AI_TEAM_SIZE(team)
009a33d6  cmp  eax, [ebx+0x1a8]      ; prototype +0x2D4, the min
009a33e0  jb   still_recruiting
          ...
009a33ed  cmp  dword [ebx+0x1a0], 1  ; DEFENSIVE: done at the min
009a33f4  je   done
009a33fa  cmp  eax, [ebx+0x1a4]      ; prototype +0x2D0, the max
009a3400  jae  done
009a3405  call 0x009a26a1            ; team threat >= threat at the target?
009a340c  je   still_recruiting
done:     ...                        ; mark built, tell the tactic, stop recruiting
```

`0x009A26A1` sums the members' threat and compares it with the target's (`0x006C6743`), so the
design is sound: wait for the min, then for a full team or one strong enough. What breaks it is
the unit of measure.

Once built, the tactic hears about it (`0x0090B944` -> `0x008F1F90`); when all its teams have
reported, its tick (`0x008F11DA`) waits `[0x00DE9F08]` frames and calls `vtable+0x18`, which for
`SimpleAttack` sends the team at the target.

## 3. What `AI_TEAM_SIZE` counts

```asm
009a24c6  mov  eax, [ebp-0x18]       ; the team member
009a24c9  mov  eax, [eax+4]          ; its ThingTemplate
009a24cc  test byte  [eax+0x108], 8          ; CAN_ATTACK
009a24d3  jne  count
009a24d5  test dword [eax+0x110], 0x4000000  ; HERO
009a24db  jne  count
009a24dd  test dword [eax+0x120], 0x4000000  ; SUPPORT
009a24e3  je   next
count:    inc  edi
next:     lea  ecx, [ebp-0x18]       ; advance
          ...
009a24f2  jne  0x009a24c6
```

The KindOf bitset starts at `ThingTemplate+0x108` (it decodes `CAN_ATTACK`, `IMMOBILE`, `HERO`,
`SUPPORT` and `STRUCTURE` at the offsets the AI tests them). Every object on the team is visited,
and `HordeContain`'s team-change handler (`0x00870667`) walks the contain list and calls `setTeam`
on each member, so the members are on the team. A battalion of `n` is therefore `n + 1`.

Imladris battalions are five strong. One of them is six: past the 3-5 min, at `FormationAttack`'s
max, and at the recruiter's cap, which starts from the same count. The threat test is dead code
for any team holding a battalion.

## 4. The patch

`0x009A24C6` is six bytes, two whole instructions, and the loop's only branch target (the back-edge
at `0x009A24F2`). It becomes `jmp cave` + `nop`:

```asm
cave:  mov  eax, [ebp-0x18]
       test byte [eax+0x98], 0x40    ; ObjectStatus HORDE_MEMBER (bit 38)
       jne  member
       mov  eax, [eax+4]             ; the displaced template read
       jmp  0x009a24cc               ; the stock KindOf tests
member:
       jmp  0x009a24e6               ; not counted: next object
```

`HORDE_MEMBER` rather than "is contained": `HordeContain::addToContain` (`0x0086CF2A`) clears it for
a `MACHINE`, `HERO` or `SIEGE_TOWER` that joins a battalion, so heroes and siege still count as
units, and a garrisoned unit (contained, not a member) still counts. The cave writes only `eax`,
which every resume point reloads; `edi` (the count) and `esi` (the `0x4000000` mask) are untouched.

Anchors: the function's prologue, both resume points, the back-edge, both team-builder call sites
(their displacement proves the team builder calls this function) and `Object::testStatus`, which
pins the status bit encoding.

## 5. What changes in a game

- An attack on a structure waits for 3-5 battalions, then keeps recruiting until it has 6 or
  out-threatens the defenders. `FormationAttack` needs 2.
- `OPPORTUNITY` teams (max 2) and `DEFENSIVE` teams (done at the min) are barely affected.
- A team that cannot reach its min holds the battalions it has while it waits. Targets expire
  (`SecondsTillTargetsCanExpire`, `ChanceForTargetToExpire`), which should release them; **not yet
  observed in a running game.**

## 6. Status

Static only. Applied to a copy of `game.dat`: all anchors match and the patched loop disassembles
as above. Not yet run in a game - `runtime_verified` stays empty until it has been.
