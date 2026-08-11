# Half-formed hordes: units that can only be trampled or splashed

Recon for a possible patch. Static work against this repo's `game.dat`
(RotWK `2.01.2614.37001`, ImageBase `0x400000`), plus one live session - section 6a is what the
running game said, and it moved the recommendation.

**The report.** A horde produced by the AI is sometimes given an order before it has finished
forming. The result is a set of loose units that behave as individuals and **cannot be
attacked** - they die only to trampling or to area-of-effect spells.

**Verdict up front.** The *symptom* is explained and is patchable. Every attack order in this
engine passes through one small function that rewrites the victim into the horde it belongs to,
and that function has two ways to hand back something nobody can hit: it redirects a loose unit
to a horde it is no longer inside, and it returns `NULL` - which the caller treats as "this
cannot be attacked" - when the horde it lands on has no members.

> ⚠ **Read §6c before acting on any of this. Two patches were built from the analysis below,
> applied, and tested against a save that carries the fault - neither fixed it.** A
> behaviour-neutral probe then showed why: the order is never refused inside `aiAttackObject`,
> the function every option here targets. The reverse-engineering stands and the state
> description in §6b is measured fact; the causal conclusion drawn from them does not hold.

**The bug has now been read out of a live game** (§6b), from a save carrying it, and it is the
predicted state exactly: a `GoblinFighterHorde` alive with **zero members** and no body,
standing a thousand units from the fifteen un-contained goblins that still name it as their
producer - three of which are beating on a hero who cannot hit back, because his every attack
is redirected onto that ghost.

The live work also **changed which fix to prefer, twice**. Ordering a battalion during its own
formation cannot break it - the engine drops such orders, so the player cannot do what the AI
does - and normal forming turns out to be indistinguishable from the fault by container
emptiness alone, which rules out options A and B. The same save then supplied the
discriminator that does hold: **a unit still leaving a building carries `IS_LEAVING_FACTORY`
and a stranded one does not.** That is option D, and it is the recommendation.

The *cause* - what leaves a horde empty and its units loose - is still **not** located, though
§6b names its signature: the ghost container never cleared `IS_LEAVING_FACTORY`.

## 1. Why "trample and AoE only" is the whole clue

Those two are exactly the damage paths that never ask "may I attack this object". Trampling is
resolved in the collision path, and an AoE spell damages whatever a partition-manager scan
returns inside a radius. Everything else - a right-click, an AI auto-acquire, a horde told to
charge - goes through `AIUpdateInterface::aiAttackObject`, which first asks a helper what it is
really allowed to aim at.

So the report is not saying "these units are invulnerable". It is saying **target selection
refuses them**, and target selection is one function.

## 2. The pieces that had to be recovered first

| fact | value | how it was established |
|---|---|---|
| `Object::testStatus(bit)` | `0x0044DDEC` | one helper, `and eax, [esi + edx*4 + 0x94]` |
| `Object::m_status` | **`Object+0x94`**, 4 dwords | the offset that helper indexes |
| `ObjectStatus` name table | `0x00D8AFF0`, index 0 = `DESTROYED` | 91 call sites carry a literal bit index; all 39 distinct values name a plausible status |
| `KindOf` name table | `0x00DA0E68`, index 0 = `OBSTACLE` | same shape, 222 entries |
| `ThingTemplate::m_kindof` | **`template+0x108`**, 8 dwords | field table entry 53 (`KindOf`) |
| `Object::m_containedBy` | `Object+0x27C` | already in [`live-object-model.md`](live-object-model.md); the code below reads it |
| `Object::m_id` / second id | `+0x74` / **`+0x78`** | `+0x74` is measured; `+0x78` is fed to `findObjectByID` (see §4) |

Two status bits and one kind matter here:

- `HORDE_MEMBER` = bit **38** (`0x26`) - 11 test sites.
- `IS_LEAVING_FACTORY` = bit **90** (`0x5A`).
- `KINDOF HORDE` = bit **109** → `template+0x114 & 0x2000`.
- `KINDOF MELEE_HORDE` = bit **119** → `template+0x116 & 0x80`.

The kind numbering checks itself: the engine loads `edi, 0x2000` and tests `[template+0x114]`
in the horde code below, and elsewhere tests `[template+0x115] & 0x20` - the same bit reached
byte-wise. Two independent encodings of bit 109 agreeing is what makes the table base right
rather than merely plausible.

## 3. The horde plumbing, for orientation

| thing | address |
|---|---|
| `HordeContain` instance factory / ctor / size | `0x0064B5D5` / `0x008727F9` / `0x30C` bytes |
| `HordeContain` primary vtable | `0x00C5B5F8` |
| its `ContainModuleInterface` sub-object | instance `+0x11C`, vtable `0x00C5B1F8` |
| interface: get the horde interface | vtable `+0x7C` → `0x00875C93` |
| interface: count members (takes a filter) | vtable `+0x180` → `0x008706DF` |
| interface: pick a member | vtable `+0x48` → `0x0086FA87` |
| `HordeAIUpdate` ctor / vtable / size | `0x0089DFAE` / `0x00C66D48` / `0x4AC` bytes |

The AI state machine defines a separate family of states for hordes, which is where "still
forming" lives: `AIHordeEnterState` id `0x35`, **`AIHordeExitState` id `0x41`**,
`AIHordeExitAndMoveToState` id `0x45`, plus `AIHordeExitAndFollowPathState`; the non-horde
equivalents are `AIExitState` `0x42`, `AIExitAndMoveToState` `0x44`,
`AIExitAndFollowPathState` `0x10`. They are all defined in one table at `0x00753755`.
"Ordered while leaving the factory" is a transition out of the `0x41` / `0x45` pair.

Worth noting for the patch: **`HordeAIUpdate` does not override `aiAttackObject`.** Its vtable
slot `+0x88` holds the same base implementation every other AI update uses, so a fix at that
level reaches hordes, single units, heroes and the AI in one place.

## 4. The function that decides what you are allowed to hit

`0x00668167`–`0x0066823D`. Custom calling convention (LTCG): the victim arrives in `eax`, the
attacker and an out-parameter on the stack. Annotated:

```c
Object *resolveAttackTarget(Object *victim /*eax*/, Object *attacker, Bool *outIsHordeTarget)
{
    Object *target;

    if (!attacker->testStatus(HORDE_MEMBER)) {            // 0x668172   branch A
        Object *c = victim->m_containedBy;                // 0x66817D   +0x27C
        if (c && c->tmpl->isKindOf(HORDE))                // 0x66818F
            target = c;
        else {                                            // 0x6681D0   the ancestry fallback
            Object *p = TheGameLogic->findObjectByID(victim->field_78);
            target = (p && p->tmpl->isKindOf(HORDE)) ? p : victim;
        }
    } else {                                              // 0x6681EF   branch B
        if (!victim->tmpl->isKindOf(HORDE))
            target = victim;
        else {
            HordeIface *h = victim->m_contain->getHordeIface();   // +0x258, vt +0x7C
            if (!h)                       target = victim;
            else if (h->count(0) == 0)    return NULL;    // 0x66821D   <-- refusal
            else {
                Object *m = h->pickMember(0, 0, 0.0f, 0, 0);      // vt +0x48
                if (!m)                   return NULL;    // 0x668234   <-- refusal
                target = m;
            }
        }
    }

    *outIsHordeTarget = target->tmpl->isKindOf(HORDE)
                     && !attacker->tmpl->isKindOf(MELEE_HORDE)
                     && !attacker->testStatus(HORDE_MEMBER);
    return target;
}
```

Its only two callers are `AIUpdateInterface::aiAttackObject` (`0x0066BD33`, vtable slot `+0x88`)
and the force-attack variant (`0x0066BF4C`, slot `+0x98`). Both do the same thing with a `NULL`
result: `or eax, 0xFFFFFFFF` and return **without ever setting the attack state**. The order is
dropped on the floor - no error, no state change, the unit just carries on.

That is the shape of "cannot be attacked", exactly.

## 5. How a half-formed horde lands in it

Two independent ways, and the reported symptom needs only one:

**Branch A, the ancestry fallback (`0x6681D0`).** A unit that is *not* inside a horde is still
redirected to the horde named by `victim+0x78` - a second `ObjectID` sitting next to `m_id`,
almost certainly `m_producerID` in the Generals-lineage layout, i.e. "who made me". So a member
that has genuinely left its horde keeps being aimed *through* it. Every attacker that is not
itself a horde member takes this branch - which includes **the horde object itself when a
battalion is ordered to attack**, and every hero. The attackers then walk toward a container
that has nothing in it, and the loose units are never touched.

**Branch B, the two refusals.** If what you clicked resolves to a horde object and that horde
reports zero members - or its member pick returns nothing - the helper returns `NULL` and the
order is silently refused. Note the asymmetry worth exploiting: branch B already *has* a member
count check and merely draws the wrong conclusion from it; branch A has no such check at all.

Both stories end at the same place: **an empty container object is still a valid attack target
in this engine, and it swallows every order aimed at the units that used to be in it.**

## 6. What is not established, and the reading that settles it

Everything above is static. Two links remain open:

1. That the broken units really are pointing at an empty horde - as opposed to being contained
   by one whose members are unpickable - is the question. The two cases want different patches.
2. Whether the ghost container is still damageable at all (it decides whether option C below
   is a fix or only a de-silencing).

**`Object+0x78` is `GameObject.producer_id`.** On
the recorded match in `tests/sage_live/fixtures/match.snapshot.gz` it equals `parent_id` for
**40 of 40** battalion members, every one of them naming a container that is really in the
table. Objects produced by something that does not contain them behave sensibly too - a lair's
spawned creeps and a structure's fences carry a producer and no parent. So the field is the
producer link the fallback treats as a horde link, measured rather than inferred, and the
disagreement between the two is exactly what a broken battalion should show.

`sage_live` reads both halves of the state: `parent_id` (`Object+0x27C`), `producer_id`
(`+0x78`), and `status` - the engine's `ObjectStatus` bits at `+0x94`, decoded through the
image's own name table, so `HORDE_MEMBER` and `IS_LEAVING_FACTORY` read as names.

## 6a. What the live run showed

`examples/sage_live/horde_formation.py`, against RotWK 2.01 + Edain, 2026-08-05, on a fresh
skirmish as Gondor with a barracks built for the purpose. Six battalions recruited across five
trials, ordered at 0, 4, 8 and 12 frames after the container appeared.

**The layout reads true live.** Members carry `HORDE_MEMBER`, a battalion in combat carries
`IS_ATTACKING`, and `producer_id` equals `parent_id` on every healthy member - three different
bits landing on names that match what those objects are visibly doing.

**Normal formation, measured, and it looks exactly like the bug for half a second.** The
timing was identical in all six recruits:

| frame | what the observation shows |
|---|---|
| `n` | the horde container appears, with **zero** members |
| `n+2 … n+15` | members appear one per logic frame, each **un-contained**, each flagged `IS_LEAVING_FACTORY` |
| `n+16` | all 15 become members at once; no orphans, no `IS_LEAVING_FACTORY` |

So `parent_id is None` beside a live `producer_id` is the *ordinary* state of a unit walking
out of a barracks - fourteen of them at once, for up to fourteen frames. Anything hunting the
broken state has to require it to **persist**, or it calls every healthy recruit a break.

**This is a measured argument against option A.** During those sixteen frames the producer-id
fallback at `0x6681D0` is the *only* thing tying a member to its battalion, which is evidently
what it is for. Removing it would make every freshly trained unit individually targetable for
half a second, every time one is trained - a real change to normal play, not a corner case.

**The player's order path cannot interrupt a forming battalion at all.** Select + move, and
select + attack-move, issued at each of the four delays, were accepted into the message stream
(the bridge confirms the hook consumed them) and then **did nothing**: the container did not
move a single unit over the following 500 frames. The control rules out the instrument - the
same order, to the same horde, once formed, moved it 396 units in eight seconds.

That is worth stating plainly because it bounds what this script can prove: **logic drops an
order aimed at a horde that is still coming out of the building.** The report is about hordes
the *AI* makes, and the skirmish AI does not order through selection and the message stream -
it drives `AIUpdate` directly. So "the same order, only earlier" is not what the AI is doing,
and the deliberate path cannot make the AI's mistake for it. Hence `--observe`, which watches
every battalion in the match and reports any unit that stays un-contained past forming,
wherever it came from.

## 6b. The bug, witnessed

A save carrying the fault, read at frame 2952 (1473 objects). The scene: goblins beating on
the dwarven hero **Nár** (`DwarvenNar`, id 2999, 3785/5368 hp) while he does not fight back.

**The container is a ghost, and it is exactly the state predicted.**

| | value |
|---|---|
| id 7086 | `GoblinFighterHorde`, owner 5, alive |
| members | **0** |
| body | none (`has_body` false) - nothing can damage it |
| position | 1435, 2245 - **1068 units away from Nár**, back at the factory |
| status | `IS_LEAVING_FACTORY`, and nothing else but the draw flag |

**Its fifteen units are all free-standing and all alive**, `parent_id` empty on every one,
`producer_id` 7086 on every one, 5/5 hit points on every one. Twelve are still milling about
the factory 7-57 units from the ghost; **three walked off and are the ones hitting Nár**, 25-47
units from him and ~1090 from their own container.

That is the whole failure, and it explains Nár exactly. He is a hero, so he is **not**
`HORDE_MEMBER`, so his attack takes branch A: `m_containedBy` is empty, the producer fallback
resolves 7086, 7086 is `KINDOF HORDE` - so every attack he makes is aimed at a bodiless object
a thousand units away, and never at the goblin standing on him. Trampling and splash still work
because neither goes through this function. `IS_LEAVING_FACTORY` still set on a container whose
units left long ago is the cause-side signature: the exit never completed.

**Two things the sweep has to get right.**

1. **The broken units do not carry `HORDE_MEMBER`.** They kept the producer link and lost the
   status, so hunting on that bit finds only corpses (`DEATH_1`, `SINKING`), which detach from a
   horde normally.
2. **An empty container is not by itself abnormal.** §6a measured members joining only at
   `n+16`, so a *healthy* battalion's container is empty for the whole of forming. Emptiness
   alone therefore fires during every normal recruit, not only on the fault.

**The same save contains the healthy control**, which is what makes the discriminator solid
rather than plausible - horde 8823, a `GoblinArcherHorde` caught mid-formation:

| | 7086, broken | 8823, forming |
|---|---|---|
| members | 0 | 0 |
| units naming it | 15 | 6 |
| of those, still `IS_LEAVING_FACTORY` | **0** | **6** |
| container status | `IS_LEAVING_FACTORY` | `IS_LEAVING_FACTORY`, `UNDER_CONSTRUCTION`, `UNSELECTABLE` |

So forming and broken are told apart by one bit on the victim: **a unit still coming out of a
building has `IS_LEAVING_FACTORY`; one this fault has stranded does not.** That is the condition
the patch wants, and it is measured on both sides.

## 6c. The order is not refused inside `aiAttackObject`

Gating the target resolution does not help. Live against the save, gating the inlined fallback
in `resolveAttackTarget` (§7 option D) has no effect, and gating the shared `Object::getHorde` -
the helper with 114 callers - has no effect either: Nár still never engages and his AI goal
stays `0`, the order refused outright rather than mis-aimed.

A behaviour-free probe build says why. It records, into its own writable PE section, what
`AIUpdateInterface::aiAttackObject` does: the victim handed to the resolver, what the resolver
returned, and a counter on each of the function's two `or eax,-1` refusal paths (`0x0066BD5E`
and `0x0066BDCB`).

**Neither refusal counter ever increments.** Not once - not while a whole battle resolves
attacks through the same function (the resolver-entered counter runs to 161 at idle and climbs
by ~100 per probe, so the instrument is plainly live). An order that visibly does nothing is
therefore **not being refused inside `aiAttackObject` at all**.

The redirect is real and the discriminator is real, but neither is what drops the order: it is
dropped **above** the AI layer, before `aiAttackObject` is reached. `AIGroup` - the layer a
selection-based order actually goes through - is the next place to look, and it should be
instrumented the same way rather than reasoned about.

Two practical notes for whoever picks this up. The probe section must be allocated
**writable** (`0xE0000060`); allocated as code+read like the other caves, the first counter
write faults and the game dies the moment anything attacks. And the counters are far too coarse
to attribute a single order during a battle - hundreds of resolutions per second run through
them - so the next instrument wants a ring buffer of `(attacker, victim, outcome)`, not
last-value fields.

## 7. Patch options

All byte windows below were read out of this repo's `game.dat` and verified as originals, so
they drop straight into the existing `Patch` machinery (which checks the original bytes before
writing). None needs a code cave or a new PE section.

**Option A - containment, not ancestry, decides the target.** Kill the `+0x78` fallback, so an
object is only treated as part of a horde when it is actually inside one.

| at | from | to | meaning |
|---|---|---|---|
| `0x0066818A` | `74 44` | `74 0D` | `containedBy == NULL` → target the victim itself |
| `0x00668195` | `74 39` | `74 02` | container is not a horde → target the victim itself |

Two bytes. It makes the block at `0x6681D0` dead code. It is also **the one option §6a argues
against**: the fallback is load-bearing during every normal recruit, where fourteen members
spend up to fourteen frames un-contained and it is the only thing making them a battalion.
Applying this would make every freshly trained unit individually targetable for half a second.
Keep it as the cheap experiment it is, not as the fix.

**Option C - never refuse the order.** Make branch B fall back to the horde object instead of
returning `NULL`:

| at | from | to |
|---|---|---|
| `0x0066821D` | `76 1B` | `76 11` |
| `0x00668230` | `8B F0 3B F3 0F 85 5F FF FF FF` | `85 C0 0F 45 F0 E9 5F FF FF FF` |

which is `test eax,eax` / `cmovne esi,eax` / `jmp 0x668199` - keep the picked member if there
was one, otherwise keep the victim. Ten bytes, and the four bytes at `0x0066823A` become dead.
On its own this only converts a silent refusal into an attack on a ghost; it is a companion to
A, not a substitute.

**Option D - follow the ancestry link only while the unit is still coming out.** The one §6b
argues for, and the only one whose condition was measured on both a broken battalion and a
healthy one in the same save. Branch A's fallback is right during forming and wrong afterwards,
and the engine already records which is which: gate it on the victim's `IS_LEAVING_FACTORY`.

```c
else {                                            // 0x6681D0, the ancestry fallback
    if (!victim->testStatus(IS_LEAVING_FACTORY))  // <-- inserted
        target = victim;                          //     stranded: it is its own target
    else { ... existing lookup by producer id ... }
}
```

The whole fallback block is `0x006681D0`-`0x006681EE`, 31 bytes, entered only by the two `je`s
above it, so it can be relocated wholesale:

```
0x006681D0  ff 76 78 8b 0d 2c 41 de 00 e8 a3 14 de ff 3b c3
0x006681E0  74 b7 8b 48 04 85 b9 14 01 00 00 74 ac eb a8
```

Replace with `jmp rel32` into a cave that prefixes the test and then runs what those bytes did:

```
push 0x5A                  ; IS_LEAVING_FACTORY
mov  ecx, esi              ; the victim
call 0x0044DDEC            ; Object::testStatus - clobbers eax/ecx/edx, preserves ebx/esi/edi
test al, al
je   0x00668199            ; not leaving: target the victim itself
...the 31 original bytes, with their three relative branches retargeted...
```

`testStatus` leaves `esi` (victim), `ebx` (zero) and `edi` (the `KINDOF HORDE` mask) alone,
which is what the rest of the function still needs, so nothing has to be saved around it.

**What none of these do** is stop the horde breaking. They stop the break from producing
unkillable units. The cause-side signature is now known too, and is where a real fix would go:
the ghost container still carries `IS_LEAVING_FACTORY` long after its units finished leaving,
so the exit sequence is what failed to complete.

## 8. Suggested order of work

1. Reproducing through the live bridge returns a *negative* with a reason (§6a). The player's
   order path cannot interrupt forming, so the trigger is not "an order arriving early" as such.
   What that run establishes is the normal timing, which is the baseline any further hunt
   measures against.
2. Catching the state rather than causing it works, from a save (§6b). Hunt on **`parent_id`
   empty + a live horde producer**, and do *not* require `HORDE_MEMBER` (the stranded units have
   lost it) or accept `DEATH_1`/`SINKING` (corpses detach normally).
3. Apply **D**, and confirm against this save that Nár's attack now resolves to the goblin in
   front of him. **A** is a diagnostic, not a candidate.
4. For the cause, the AI's own path is where to look, since it is the one that can order a
   horde the player cannot: `AIHordeExitState` (`0x41`) and `AIHordeExitAndMoveToState`
   (`0x45`), and what drops a player order in that window - because whatever performs that drop
   is exactly what the AI is bypassing. The INI-side lever to test first is
   `HordesWaitForHordes`, a `Bool` at `TheGlobalData+0xB9` (`[0x00DE4B40]+0x18`) that gates
   three horde-specific code paths, and a `GameData.ini` flag costs nothing to flip.
