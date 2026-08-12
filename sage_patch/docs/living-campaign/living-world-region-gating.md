# Why the player can wander, and why reachable regions read poorly

Both complaints — "the player can waste an act moving into already-conquered allied territory" and
"BFME1 showed clearly which territories you could reach this turn" — come back to the same cause,
and it is **not an engine regression**. RotWK has the machinery; Edain's campaigns never use it.

Engine build `2.01.2614.37001`, ImageBase `0x400000`. Recovered statically 2026-08-12 against the
installed `game.dat`, BFME1 `C:\BFME1\lotrbfme.exe`, and the Edain INI corpus.

## The finding in one table

| | BFME1 `GondorCampaign` | BFME1 `MordorCampaign` | Edain Angmar | Edain Evil | Edain Moria |
|---|---|---|---|---|---|
| acts | 46 | 45 | 12 | 8 | 5 |
| **`EnableRegion`** | **37** | **38** | **0** | **0** | **0** |
| `ForceBattle` | 9 | 7 | 0 | 0 | 0 |
| `MoveArmy` | 133 | 39 | 23 | 10 | 5 |

BFME1 issues roughly **one `EnableRegion` per act**. Edain issues none, in any campaign.

That is the whole story. BFME1's campaign turned regions on as the story reached them, so at any
given act only a handful of regions existed to move into — which is experienced as "you could only
move into enemy territory". Nothing was restricting the *direction* of movement; the map simply had
not opened up yet.

## `EnableRegion` is live in RotWK

It is the first verb in the Act verb table (`0x00C84030`) and it is implemented end to end — checked
deliberately, because this investigation has twice been caught by verbs that parse and do nothing:

```
parse      0x008E5A80   field table 0x00C78710 -> a single field, Region (AsciiString, +0x04)
append     0x0096DF1A   -> act+0x08, 8-byte records
execute    0x0096C6CE   pass 1 of the 10 the act runner makes:
                            for each record:
                                name = record+4
                                [0x00DE4950]->[0xB0]->setRegionEnabled(name, true)   ; 0x00610289
resolve    0x00610278   name -> live region
apply      0x007F1067   Region::setEnabled(bool):
                            region->[0x1C2]        = enabled     ; the flag
                            region->[0x1B8]->[0x2C] = enabled     ; mirrored onto an attached object
```

Syntax, from BFME1's `gondorcampaign.ini` and matching RotWK's field table exactly:

```
Act Three
    EnableRegion
        Region = Rohan
    End
    EnableRegion
        Region = Eastern_Rohan
    End
    EnableRegion
        Region = Westfold
    End
End
```

**One field, one verb, no patch.** This is INI-only work available today.

### RotWK's model is *disable then enable*, and both halves are already there

`EnableRegion` only turns regions **on**, so on its own it would do nothing on a map where
everything starts enabled. The other half is a `Scenario` field, and tracing the campaign start-up
shows exactly how they pair:

```asm
00932b82  <one of the two state builders LivingWorldCampaign::begin calls>
00932b8a  ecx = [0x00DE4950]->[0xB0]        ; the region manager
00932b90  call 0x0060E926                   ; reset regions
00932b95  esi = campaign->[0x1C]            ; the Scenario block
00932b9c  list = esi->[0x1C] .. esi->[0x20] ; <-- DisableRegions
00932baf  for each name: setRegionEnabled(name, 0)
```

And `DisableRegions` is confirmed at `Scenario + 0x1C` in the Scenario field table (`0x00C7A578`).

So the intended authoring pattern is:

```
LivingWorldCampaign WOTRScenarioAngmar
    Scenario
        DisableRegions = High_Pass Ettenmoors Tower_Hills Grey_Havens Celduin Erebor Mirkwood
    End

    Act One
        EnableRegion
            Region = Fornost
        End
    End
End
```

Start with the map closed, open it act by act. That is BFME1's progression expressed with RotWK's
own two features — and arguably a better design than BFME1's, since the starting state is declared
in one place.

**Edain uses neither.** `wotrscenarioangmar.inc` carries a `DisableRegions` line **commented out**
(alongside a second commented variant listing more regions), and zero `EnableRegion` blocks. Someone
reached for exactly this and stopped. As with `MergePlayerArmy`, the authoring intent is already in
the file.

## Why this also explains the unclear reachability display

`Region::setEnabled` writes the flag twice — once on the region (`+0x1C2`) and once onto an object
hanging off `region+0x1B8`, at `+0x2C`. The second write is what makes enabling *visible*: the
region's attached presentation object carries the same flag.

So the "which regions can I reach" affordance is **downstream of the enabled state**. In BFME1 that
state changed every act and the display changed with it. In Edain every region is enabled from the
start and stays that way, so the display has nothing to distinguish — every territory looks the
same, all the time.

That is a hypothesis about the *display* half, not a proven one: I established that enabling writes
a flag onto an attached object, not that the UI reads that flag to draw a reachability indicator.
The gating half — that `EnableRegion` is live and unused — is solid.

## The second, independent UI gap

RotWK's `Region` block carries the popup machinery, and it is **identical to BFME1's**:

| field | offset | RotWK | BFME1 |
|---|---|---|---|
| `RegionPortrait` | `+0x070` | ✓ | ✓ |
| `CustomUIPopupPoint` | `+0x0CB` (bool) | ✓ | ✓ |
| `UIPopupPoint` | `+0x0D0` (coord) | ✓ | ✓ |
| `CustomCenterPoint` / `CenterPoint` | `+0x089` / `+0x080` | ✓ | ✓ |

Diffing the two `Region` field tables, RotWK has **50** fields to BFME1's 28, and the only BFME1-only
fields are `MissionObjectiveTag`, `BonusMissionObjectiveTag` and `SkirmishOpponent` — none of them
UI-related. Nothing about region presentation was removed.

**What Edain sets, across all 111 regions:**

| field | set on |
|---|---|
| `RegionPortrait` | **111 / 111** |
| `CenterPoint` (+ `CustomCenterPoint`) | **111 / 111** |
| `UIPopupPoint` | **0** |
| `CustomUIPopupPoint` | **0** |

And the consumer, `0x0060EFBD`:

```asm
0060efc8  region = findRegion(name)
0060efd5  cmp byte [region + 0xCB], 0        ; CustomUIPopupPoint
0060efdc  je  0060effa                       ; not set ->
0060efe4  ... getCustomPopupPoint()          ;   use UIPopupPoint
0060effa  call 0x0060EF99                    ;   else fall back to the CENTRE POINT
```

So every region popup in Edain renders at the region's geometric centre, because the field that
would place it deliberately is never set. BFME1's own shipped campaign did not set it either — its
regions are pure geometry (`RegionObject` + `SubObject`, 76 regions, no `RegionPortrait`, no
`UIPopupPoint`) — so this is **not** the thing BFME1 did differently. It is simply an unused RotWK
affordance that happens to be the right lever for the complaint.

## What to do

1. **Uncomment `DisableRegions` and add `EnableRegion` per act.** Highest value, zero cost, no
   patch. Close the map at campaign start, open it as the story reaches each region, and the
   "wasted act" problem disappears by construction rather than by asking the player to know better.
   This is the single cheapest improvement identified in the whole investigation, and both halves
   are already written into `wotrscenarioangmar.inc` — one commented out, one absent.
2. **Set `UIPopupPoint` per region** where the centre is a poor spot — `CustomUIPopupPoint = Yes`
   plus a coordinate placing the portrait above the territory. Also INI-only.
3. **Consider `ForceBattle`**, likewise unused (BFME1: 9 and 7; Edain: 0). It pins where a battle
   happens rather than leaving it to the player's approach.

None of these needs a patch, and none depends on the four missing Act verbs
([`bfme1-act-verbs.md`](bfme1-act-verbs.md)) or on any of the dead script actions
([`dead-script-actions.md`](dead-script-actions.md)).

## Unknowns

| | question | how to settle |
|---|---|---|
| 1 | Does the world-map UI actually hide or grey disabled regions, or only block movement? | enable a subset in a test act and look |
| 2 | What is `[TheLivingWorldManager + 0xB0]`, and can pass 1 be skipped if it is null? | live read via `live-bridge`; the pass early-outs when it is zero |
| 3 | Does `EnableRegion` have a disable counterpart, or is enabling one-way per campaign? | `Region::setEnabled` takes a bool and the disable path at `0x007F1081` exists — but no verb passes `false`, so check whether anything else calls it |

Question 3 matters for authoring: if regions can only ever be turned *on*, an act cannot close a
front behind the player, and the gating is monotonic.

## Method

Act verb table and field tables dumped as 16-byte rows; executor located by matching the act-list
offset from the append thunk against the ten passes the act runner (`0x0096E362`) makes; field
offsets read from the `Region` block table at `0x00C4C8A0`. INI counts are of live (uncommented)
lines across `D:\Edain-Mod\_mod\data\ini\campaigns` and BFME1's `ini.big`.
