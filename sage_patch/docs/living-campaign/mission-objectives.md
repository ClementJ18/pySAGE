# Mission objectives in RotWK — nothing was removed

The complaint was that RotWK campaigns are a pain because you have no access to objectives, and the
question was whether they could be re-enabled. **There is nothing to re-enable.** Every part of the
objectives system is present in RotWK, live, and already authored in Edain's campaign data. This
document records what was checked, because the useful result is knowing where *not* to look.

Engine build `2.01.2614.37001`, ImageBase `0x400000`. Static analysis 2026-08-12, plus map parsing
with `sage_map` against BFME1 `maps.big` and the Edain map corpus.

## How the system works, end to end

```
map.ini              MissionObjectiveList { MissionObjectiveTag = SCRIPT:... }   <- the text, per map
   |
lotr.str             SCRIPT:angangmarobjectivetext_01 = "The Witch-king must survive."
   |
map scripts          SHOW_MISSION_OBJECTIVE(3)      <- a SLOT INDEX, not text
   |
0x007BDE35           TheMissionObjectiveTracker (0x00DE8C94) -> tracker->[0x10] -> setSlotVisible
   |
Objectives.apt       Objective1 .. Objective12, objective_checked / objective_unchecked
   |
Palantir.apt         OnBttnObjectives  (the in-battle HUD button)
StrategicPalantir.apt  _OnObjectivesButtonClicked, EnableObjectivesButton  (the world-map button)
```

The script actions carry **an integer slot index only**. The text lives in the map's `map.ini`, and
the screen has twelve fixed slots. That is why nothing in the map or the scripts mentions a string.

## Everything checked, and its state

| | state |
|---|---|
| `SHOW_MISSION_OBJECTIVE` (531) | **live** |
| `HIDE_MISSION_OBJECTIVE` (532) | **live** |
| `MARK_MISSION_OBJECTIVE_COMPLETED` (533) | **live** |
| `MARK_MISSION_OBJECTIVE_NOT_COMPLETED` (534) | **live** |
| `ENABLE_OBJECTIVES_SCREEN` (582) / `DISABLE_OBJECTIVES_SCREEN` (583) | **live** |
| `FLASH_OBJECTIVES_BUTTON` (587) | **live** |
| `CLOSE_OBJECTIVES_SCREEN` (598) | **live** |
| `TheMissionObjectiveTracker` | registered as a startup subsystem (`0x0063BA12`) |
| objectives-screen enabled flag | **defaults to enabled** — `0x00DE9EB8` initialised to `1` at `0x008E8830` |
| `Objectives.apt` | present, class `AptObjectivesMenu`, slots `Objective1`–`Objective12` |
| in-battle button | `Palantir.apt` — `OnBttnObjectives`, `FlashObjectivesButton` |
| world-map button | `StrategicPalantir.apt` — `_OnObjectivesButtonClicked`, `EnableObjectivesButton` |
| world-map tab | `StrategicPlayerStatus.apt` — `TabObjectives`, `ObjectivesWindow` |
| `data\ini\missionobjectives.ini` | present, and **empty by design** — "Any initialization fields required for TheMissionObjectiveTracker would go here. At the moment, there are none." |

Worth stating plainly because it is the opposite of every other finding in this investigation:
**none of the objective actions is a stub or gutted**, and the objectives-screen flag is enabled
unless a script turns it off. Its *only* writer in the entire image is
`ENABLE_/DISABLE_OBJECTIVES_SCREEN` (`0x008E89BD`, reached only from `0x007CF779`).

## Edain's data is already fully authored

Every campaign map's `map.ini` carries a `MissionObjectiveList`:

| campaign | maps | objective tags per map |
|---|---|---|
| Angmar | 11 | 4–15 (mission 01 has 9 + 3 bonus) |
| Evil | 8 | 4–12 |
| Good | 8 | 6–13 |
| **Moria** | **5** | **0 — none of the five defines any** |

The CSF labels resolve: `SCRIPT:ANGAngmarObjectiveText_01` → *"The Witch-king must survive."*
(the `.str` entries are lower-cased, which is fine — CSF lookup is case-insensitive).

And `map kampa angmar 01` drives them properly: **6 `SHOW_MISSION_OBJECTIVE`, 9
`HIDE_MISSION_OBJECTIVE`, 11 `MARK_MISSION_OBJECTIVE_COMPLETED`, 1 `FLASH_OBJECTIVES_BUTTON`**,
hiding slots 2–12 in `Map Setup` and revealing them from cinematic scripts as the mission proceeds.
That is exactly the BFME1 pattern.

## What BFME1 actually did differently — very little

BFME1's `Region` block has two fields RotWK's does not: `MissionObjectiveTag` and
`BonusMissionObjectiveTag` (two of only three BFME1-only `Region` fields — see
[`living-world-region-gating.md`](living-world-region-gating.md)). But BFME1's shipped
`livingworldregions.ini` **does not use them**, and BFME1's campaign maps carry no `map.str` at all
(`maps.big` contains zero `.str` files). BFME1 drove objectives the same way RotWK does: a slot
index from map scripts.

For scale, `map good helms deep` uses **5** objective actions. Edain's `map kampa angmar 01` uses
**27**. Edain's campaign is *more* thoroughly instrumented than BFME1's was.

## So where is the problem?

Not in the engine, not in the actions, not in the text, and not in the screen. The remaining
candidates are narrow, and all are about the **entry point** rather than the system:

**Edain's battle HUD is not the culprit — checked and cleared.** Converting both
`Palantir.apt` files to XML with `sage_apt` and comparing *placeobjects* rather than constant-pool
strings (a constant can survive with nothing placed that uses it):

| | stock | Edain |
|---|---|---|
| total placeobjects | 4050 | 4046 |
| objectives-named placements | `FlashObjectivesButton`, `Objectives`, `SetObjectivesButtonFlashEffectState`, `objectivesFlashEffect` | **identical, all four** |

So the in-battle objectives button is placed in Edain's HUD exactly as it is in stock.

What remains open:

| | question | how to settle |
|---|---|---|
| ~~1~~ | ~~Did Edain drop the objectives button from the battle HUD?~~ | **settled — no**, placements are identical to stock |
| 2 | What condition enables the **world-map** objectives button? | `setObjectivesButtonEnabled` (`0x00982B57`) invokes the APT function `EnableObjectivesButton`; it is reached **virtually** (vtable slot `0xC8600C`), so the gating condition needs the vtable's call sites traced |
| 3 | Does a living-world battle push the same HUD as a linear-campaign mission? | compare which Palantir movie is loaded in each mode |
| 4 | Are the Moria maps simply missing their `MissionObjectiveList`? | **yes** — 0 of 5 define one, so those five have no objectives *by data*, independent of everything else |

**Question 2 is now the live thread.** A note on it: a direct-call scan over `.text` found *zero*
callers of `0x00982B57`, which would have been a striking result — "nothing ever enables the
button". It is wrong. The address appears in a vtable at `0xC8600C`, so the call is virtual and the
scan simply cannot see it. Recorded because the same trap has produced two wrong conclusions
earlier in this investigation, and "no callers found" is never the same claim as "never called".

Item 4 is not a theory — it is a fact about the data, and it is fixable by authoring alone.

## Method

Script action status via the two-stage dispatch classifier in
[`dead-script-actions.md`](dead-script-actions.md). Map contents parsed with `sage_map`, reading
`content_type` *and* `internal_name` per action so the id↔name pairing is measured per occurrence.
APT symbol presence by extracting every `.apt`/`.const` in the install's archives and the loose
Edain tree and matching on substrings — which establishes that a symbol exists, **not** that a clip
is placed or reachable.
