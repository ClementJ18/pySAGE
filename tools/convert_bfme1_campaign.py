"""Convert a BFME1 `LivingWorldCampaign` into an Edain War of the Ring scenario.

Written for BFME1's `mordorcampaign.ini`: its acts, armies and forced battles become a
`LivingWorldCampaign` on Edain's `DefaultCampaign` region map, with the BFME1
`LivingWorldPlayerArmy` blocks it spawns appended after it, in the shape `wotrscenarioangmar.inc`
uses.

What carries straight across: `EnableRegion`, `ForceBattle`, `MoveCamera`, `EyeTowerPoints`,
`DespawnArmy`, `EndAct`, and the army rosters. What is translated:

- `SplineCamera` becomes a chain of `MoveCamera`s through its control points, at a fraction of
  BFME1's pace (`CAMERA_TIME_SCALE`);
- `SpawnArmy` names by `ScriptingName`, owns through `SpawnForTemplates` (every BFME1
  `PlayerOwned = Yes` army belongs to the one Mordor player, every other to Men), keeps its point
  with `ExactPosition = Yes`, and maps icons and banners to Edain's;
- `ToggleArmyControl` becomes `SetPlayerControlOfArmy`;
- `MoveArmy`'s `MoveTo` point becomes `TargetRegionName`, the Edain region whose centre is nearest.
  Only an army's last move in an act is kept, and a move is left out when the point lies between
  regions, or when it enters a region the other side holds at the start and no battle is forced
  there in that act or the next;
- `RegionReinforcements` becomes a `MoveArmy` per reinforcing army.

Every translation the tool cannot make faithfully is written into the output as a comment starting
`; FLAG(<kind>)`, and listed again in the file header and on stdout:

- `region`   - a BFME1 region Edain's `DefaultCampaign` does not have, or only approximates
- `position` - a `MoveTo` point far from every Edain region centre, so the move is left out
- `unit`     - an `ArmyEntry` template Edain does not define
- `hero`     - an army with no `HeroTemplateName`, which the engine merges away on spawn
- `march`    - a move into a region the other side holds, left out so it starts no battle
- `verb`     - a verb or field ROTWK has no equivalent for, rewritten or left out

Text, audio and Palantir videos are BFME1 assets Edain does not carry; they are kept as commented
`; PLACEHOLDER(...)` lines so the port can fill them in later. BFME1's city mouse-over armies exist
only to play those videos and are left out.

BFME1's regions had nothing to build on, so the scenario gets its own region campaign: a copy of
Edain's region file, written beside it, with every `BuildingSpot` and `CreateAutoFort = Yes`
commented out, under a `LivingWorldRegionCampaign` whose settings are copied from
`DefaultCampaign`.

The output needs three `sage_patch` patches: `campaign-army-verbs` (`DespawnArmy`, `ForceBattle`,
`ExactPosition`), `scenario-player-factions` (the `:N` slot qualifiers on `DisabledFactions`) and
`hide-selection-details` (`Scenario`'s `HideSelectionDetails`).

Dev-only, like the other scripts here: it reads a BFME1 dump and an Edain tree by path and is not
part of the package.

    python tools/convert_bfme1_campaign.py mordorcampaign.ini --edain <Edain>/_mod/data/ini \\
        --out <Edain>/_mod/data/ini/campaigns/scenarios/wotrscenariomordor.inc
"""

from __future__ import annotations

import argparse
import difflib
import math
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Block", "Converter", "main", "parse_blocks"]

CAMPAIGN_NAME = "WOTRScenarioMordor"
#: The scenario's own region campaign: Edain's `DefaultCampaign` with every build plot removed, so
#: the war is fought with the armies the story gives rather than ones the player builds.
REGION_CAMPAIGN = "RingkriegMordor"
REGION_SOURCE = "DefaultCampaign"
REGION_FILE = "livingworldmordorregions.inc"

EVIL_TEMPLATE = "PlayerMordor"
GOOD_TEMPLATE = "PlayerMen"
EVIL_FACTION = "FactionMordor"
GOOD_FACTION = "FactionMen"
#: Every other playable faction, disabled for the scenario.
OTHER_FACTIONS = (
    "FactionArnor",
    "FactionElves",
    "FactionRohan",
    "FactionImladris",
    "FactionAngmar",
    "FactionDwarves",
    "FactionIsengard",
    "FactionWild",
    "FactionEvilmen",
    "FactionBelfalas",
)

#: What the Mordor player holds when the war opens. BFME1 had no ownership at all - its evil
#: player simply had armies - but a War of the Ring player with no region is defeated, so these
#: are the homeland the BFME1 armies start from: Barad-dûr, the Black Gate, Minas Morgul, Isengard
#: for Saruman and Rhûn for the Easterlings. Men hold every other region the story opens.
EVIL_REGIONS = ("Mount_Doom", "Nurn", "Lithlad", "Minas_Morgul", "Black_Gate", "Isengard", "Rhun")
EVIL_CAPITAL = "Mount_Doom"
GOOD_CAPITAL = "Minas_Tirith"

#: BFME1 region names Edain spells differently. A note marks a region Edain only approximates,
#: which is flagged every time it is used.
REGION_RENAMES: dict[str, tuple[str, str | None]] = {
    "Fangorn": ("Fangorn_Forest", None),
    "Gap_of_Rohan": ("Gap_Rohan", None),
    "Eaves_of_Fangorn": ("Eaves_Fangorn", None),
    "Eastern_Rohan": ("East_Rohan", None),
    "Mouths_of_the_Entwash": ("Mouths_Entwash", None),
    "Brownlands": ("Old_Brown_Lands", "approximated by Edain's Old_Brown_Lands"),
    "Cirith_Ungol": ("Shelob_Lair", "approximated by Edain's Shelob_Lair"),
}

#: BFME1 regions with no Edain counterpart: where they were, and a point inside the old region a
#: `ForceBattle` can name instead, so the battle lands in whatever Edain region covers it.
MISSING_REGIONS: dict[str, tuple[str, tuple[float, float] | None]] = {
    "Amon_Hen": ("between Emyn_Muil and Mouths_Entwash", (1018.0, 496.0)),
    "Fords_of_Isen": ("between Gap_Rohan and Helms_Deep", (155.0, 430.0)),
    "Rohan": ("between Westfold and Edoras", (475.0, 380.0)),
    "Cross_Roads": ("between Osgiliath, Minas_Morgul and Central_Ithilien", None),
    "Harlond": ("the quays of Minas_Tirith, by Lebennin", None),
    "Emyn_Arnen": ("between Osgiliath, Central_Ithilien and Southern_Ithilien", None),
}

ICONS = {
    "RohanArmy": "RohanArmyIcon",
    "GondorArmy": "MoWArmyIcon",
    "MordorArmy": "MordorArmyIcon",
    "IsengardArmy": "IsengardArmyIcon",
    "ElvenArmy": "ElfArmyIcon",
}
#: The flag each army flies, by BFME1 army name, where BFME1's own `Banner` is missing or has no
#: Edain counterpart. `None` means no flag. An army not listed keeps the banner BFME1 gave it.
ARMY_BANNERS: dict[str, str | None] = {
    "Saruman": "BannerIsengard",
    "Lurtz": "BannerIsengard",
    "Eomer": "BannerRohan",
    "Rohan_1": "BannerRohan",
    "Rohan": "BannerRohan",
    "Ents": "BannerElves",
    "Elves": "BannerElves",
    "Faramir": "BannerMen",
    "Gondor_1": "BannerMen",
    "Easterlings": "BannerMordor",
    "Mordor_1": "BannerMordor",
    "Mordor_2": "BannerMordor",
    "Oathbreakers": None,
}

#: The hero each army is named for. The engine keeps a spawned army separate only when it names a
#: hero: one without is merged into the army its player already has in the region, and loses its
#: `ScriptingName` with it, so every later verb that names it finds nothing. Edain's own scenarios
#: give every story army a hero for the same reason, whether or not the roster contains it.
ARMY_HEROES: dict[str, str] = {
    "Saruman": "IsengardSaruman",
    "Lurtz": "IsengardLurtz",
    "Eomer": "RohanEomer",
    "Rohan_1": "RohanHama",
    "Rohan": "RohanTheoden",
    "Faramir": "GondorFaramir",
    "Gondor_1": "GondorBeregond",
    "Ents": "ImladrisTreeBerd",
    "Elves": "ElvenHaldir",
    "Oathbreakers": "GondorAragorn",
    "Mordor_1": "MordorGothmog",
    "Mordor_2": "MordorMouthOfSauron",
    "MorgulArmy": "AngmarWitchking",
    "Easterlings": "KhamulMounted",
    "Haradrim": "HaradSuladan",
    "Haradrim_Enemy": "HaradSuladan",
}

#: BFME1 unit templates Edain has under another name.
UNIT_REPLACEMENTS: dict[str, str] = {"RohanTreeBerd": "ImladrisTreeBerd"}

#: How far a `MoveTo` point may sit from the nearest Edain region centre before the choice of
#: region is worth a second look.
FAR = 150.0

#: BFME1's intro flight is 30 seconds timed against narration Edain does not have, and no ROTWK
#: data uses `SplineCamera` to prove the verb against. So the flight becomes a chain of
#: `MoveCamera`s - the form Edain's own intros use - at this fraction of BFME1's timing, and no
#: leg scrolls faster than `MIN_SCROLL_TIME` seconds.
CAMERA_TIME_SCALE = 0.2
MIN_SCROLL_TIME = 1.0
#: How far into a leg's scroll the next leg starts. Each `MoveCamera` takes over from the one
#: before, so starting before the last has arrived leaves no pause at each point - Edain's own
#: intros start their moves 0.7 seconds apart on 3-second scrolls.
CAMERA_LEG_START = 0.5

_POINT = re.compile(r"X:\s*(-?[\d.]+)\s*Y:\s*(-?[\d.]+)")
_OBJECT = re.compile(r"^\s*(?:Object|ChildObject|ObjectReskin)\s+(\w+)", re.MULTILINE)
_KEY_WIDTH = 21


@dataclass
class Block:
    """One INI block: its keyword, the rest of its header line, and its fields and child blocks in
    the order they were written."""

    kind: str
    name: str
    line: int
    items: list[tuple[str, str] | Block] = field(default_factory=list)

    def get(self, key: str) -> str | None:
        value = None
        for item in self.items:
            if isinstance(item, tuple) and item[0].lower() == key.lower():
                value = item[1]
        return value

    def values(self, key: str) -> list[str]:
        return [v for item in self.items if isinstance(item, tuple) for k, v in [item] if k == key]

    def blocks(self, kind: str) -> list[Block]:
        return [item for item in self.items if isinstance(item, Block) and item.kind == kind]


def parse_blocks(text: str, keep: Iterable[str]) -> list[Block]:
    """The top-level blocks of the kinds in `keep`, with everything nested in them.

    Any other top-level block is skipped to its unindented `End`, because BFME1's region campaign
    bodies hold keyword lines with no `=` (`Geometry`, `Position`, `Time`) that would otherwise read
    as block openers."""
    kinds = set(keep)
    found: list[Block] = []
    stack: list[Block] = []
    skipping = False
    for number, raw in enumerate(text.splitlines(), 1):
        if skipping:
            skipping = raw.rstrip() != "End"
            continue
        line = re.split(r";|//", raw, maxsplit=1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line == "End":
            if stack:
                stack.pop()
            continue
        if "=" in line:
            if stack:
                key, value = (part.strip() for part in line.split("=", 1))
                stack[-1].items.append((key, value))
            continue
        kind, _, name = line.partition(" ")
        kind, _, rest = kind.partition("\t")
        block = Block(kind, (rest + " " + name).strip(), number)
        if stack:
            stack[-1].items.append(block)
        elif kind in kinds:
            found.append(block)
        else:
            skipping = True
            continue
        stack.append(block)
    return found


def _point(value: str | None) -> tuple[float, float] | None:
    match = _POINT.search(value or "")
    return (float(match.group(1)), float(match.group(2))) if match else None


def _yes(value: str | None) -> bool:
    return (value or "").strip().lower() == "yes"


def _row(key: str, value: str, note: str | None = None) -> str:
    text = f"{key:<{_KEY_WIDTH}} = {value}"
    return f"{text} ; {note}" if note else text


class Converter:
    """One conversion: the Edain tables it resolves against, the flags it raised, and the text."""

    def __init__(self, regions: dict[str, tuple[float, float] | None], objects: set[str]) -> None:
        self.regions = regions
        self.objects = {name.lower(): name for name in objects}
        self.flags: dict[tuple[str, str], list[str]] = {}
        self.where = ""
        self.armies_used: list[str] = []
        self.story_regions: set[str] = set()
        # Filled by `survey` before any act is written.
        self.sides: dict[str, str] = {}
        self.held: dict[str, str] = {}
        self.battles: list[set[str]] = []
        self.act_index = 0
        self.superseded: set[int] = set()

    def survey(self, acts: list[Block]) -> None:
        """What the whole campaign says before any act is written: the side each army fights for,
        which side holds each region when the war opens, and where each act forces a battle."""
        for act in acts:
            for spawn in act.blocks("SpawnArmy"):
                side = "evil" if _yes(spawn.get("PlayerOwned")) else "good"
                self.sides.setdefault(spawn.get("Name") or "", side)
        opened: set[str | None] = set()
        for act in acts:
            battles: set[str | None] = set()
            for block in act.blocks("EnableRegion"):
                opened.add(self.quiet_region(block.get("Region")))
            for block in act.blocks("ForceBattle"):
                region = self.battle_region(block)
                opened.add(region)
                battles.add(region)
            for block in act.blocks("RegionReinforcements"):
                opened.add(self.quiet_region(block.get("RegionName")))
            self.battles.append({region for region in battles if region})
        self.held = dict.fromkeys(EVIL_REGIONS, "evil")
        for name in opened | {GOOD_CAPITAL}:
            if name:
                self.held.setdefault(name, "good")

    def quiet_region(self, name: str | None) -> str | None:
        """The Edain region for a BFME1 name, without flagging anything."""
        if not name:
            return None
        if name in self.regions:
            return name
        target = REGION_RENAMES.get(name, (None, None))[0]
        return target if target in self.regions else None

    def battle_region(self, block: Block) -> str | None:
        """The Edain region a `ForceBattle` lands in: its region, else the one nearest its point."""
        region = self.quiet_region(block.get("Region"))
        if region:
            return region
        source = block.get("Region") or ""
        point = _point(block.get("Position")) or MISSING_REGIONS.get(source, ("", None))[1]
        return self.nearest(point)[0] if point else None

    def flag(self, kind: str, message: str) -> str:
        wheres = self.flags.setdefault((kind, message), [])
        if self.where not in wheres:
            wheres.append(self.where)
        return f"; FLAG({kind}): {message}"

    def region(self, name: str) -> tuple[str | None, str | None]:
        """The Edain region for a BFME1 one, and the flag comment it needs, if any."""
        if name in self.regions:
            self.story_regions.add(name)
            return name, None
        if name in REGION_RENAMES:
            target, note = REGION_RENAMES[name]
            if target not in self.regions:
                return None, self.flag("region", f"{name} -> {target}, which Edain lacks")
            self.story_regions.add(target)
            if note:
                return target, self.flag("region", f"BFME1 {name} {note}")
            return target, None
        where, _ = MISSING_REGIONS.get(name, ("unknown", None))
        return None, self.flag("region", f"BFME1 {name} has no Edain region ({where})")

    def nearest(self, point: tuple[float, float]) -> tuple[str, float]:
        return min(
            ((name, math.dist(point, centre)) for name, centre in self.regions.items() if centre),
            key=lambda pair: pair[1],
        )

    def convert(
        self, campaign: Block, armies: list[Block], source: str, region_campaign: list[str]
    ) -> str:
        all_acts = campaign.blocks("Act")
        self.survey(all_acts)
        acts: list[str] = []
        for index, act in enumerate(all_acts):
            self.where = f"Act {act.name}"
            acts.extend(self.act(act, index))
        self.where = "armies"
        army_text = self.player_armies(armies)
        self.where = "scenario"
        scenario = self.scenario()
        body = [
            f"LivingWorldCampaign {CAMPAIGN_NAME}",
            "    IsEvilCampaign        = Yes",
            "    ForceAdvanceTurnPhase = Yes",
            "",
            '    #include "..\\Common\\LivingWorldDefaultRTSSettings.inc"',
            "",
            *scenario,
            "",
            *acts,
            "End",
            "",
            *region_campaign,
            "",
            *army_text,
        ]
        return "\n".join([*self.header(source), "", *body, ""])

    def header(self, source: str) -> list[str]:
        lines = [
            ";//////////////////////////////////////////////////",
            f";// {CAMPAIGN_NAME} - BFME1's Mordor campaign on Edain's War of the Ring map",
            ";//",
            f";// Generated by tools/convert_bfme1_campaign.py from {source}.",
            ";// Hand edits are lost when it is regenerated.",
            ";// Needs the campaign-army-verbs, scenario-player-factions and",
            ";// hide-selection-details patches.",
            ";//",
            f";// {len(self.flags)} flags - search this file for FLAG( to find each one:",
        ]
        for (kind, message), wheres in sorted(self.flags.items()):
            lines.append(f";//   {kind:<8} {message}")
            lines.append(f";//            in {', '.join(wheres)}")
        lines.append(";//////////////////////////////////////////////////")
        return lines

    def scenario(self) -> list[str]:
        for name in (*EVIL_REGIONS, EVIL_CAPITAL, GOOD_CAPITAL):
            if name not in self.regions:
                self.flag("region", f"scenario region {name} is not in {REGION_SOURCE}")
        good = sorted(name for name, side in self.held.items() if side == "good")
        disabled = sorted(set(self.regions) - set(EVIL_REGIONS))
        factions = [f"{GOOD_FACTION}:1", f"{EVIL_FACTION}:2", *OTHER_FACTIONS]
        return [
            "    Scenario",
            "        ; PLACEHOLDER(text): these strings are not in Edain's string table yet",
            "        " + _row("DisplayName", "LWScenario:CampaignMordor"),
            "        " + _row("DisplayDescription", "LWScenario:CampaignMordorDescription"),
            "        " + _row("DisplayGameType", "LWScenario:WOTRGameTypeCampaign"),
            "        " + _row("DisplayObjectives", "LWScenario:WOTRObjectivesCampaign"),
            "        " + _row("DisplayFiction", "LWScenario:CampaignMordorFiction"),
            "        " + _row("DisplayVictoriousText", "CONTROLBAR:hiddenbutton"),
            "        " + _row("DisplayDefeatedText", "CONTROLBAR:hiddenbutton"),
            "",
            "        " + _row("RegionCampaign", REGION_CAMPAIGN),
            "        " + _row("MinPlayers", "2"),
            "        " + _row("MaxPlayers", "2"),
            "",
            "        ; Only the homeland starts open; each act opens the regions it reaches.",
            "        " + _row("DisableRegions", " ".join(disabled)),
            "        " + _row("DisabledFactions", " ".join(factions)),
            "        " + _row("DefaultStartSpots", f"{EVIL_CAPITAL} {GOOD_CAPITAL}"),
            "        " + _row("HistoricalScenario", "Yes"),
            "        ; Needs the hide-selection-details patch.",
            "        " + _row("HideSelectionDetails", "Yes"),
            "",
            "        PlayerDefeatCondition",
            "            " + _row("Teams", "1 2"),
            "            " + _row("LoseIfCapitalLost", "No"),
            "            " + _row("NumControlledRegionsLessOrEqualTo", "0"),
            "        End",
            "",
            "        TeamDefeatCondition",
            "            " + _row("Teams", "1 2"),
            "            " + _row("NumControlledRegionsLessOrEqualTo", "0"),
            "        End",
            "",
            "        StartingRestriction",
            "            " + _row("Factions", EVIL_FACTION),
            "            " + _row("Regions", EVIL_CAPITAL),
            "            " + _row("Teams", "1"),
            "        End",
            "",
            "        StartingRestriction",
            "            " + _row("Factions", GOOD_FACTION),
            "            " + _row("Regions", GOOD_CAPITAL),
            "            " + _row("Teams", "2"),
            "        End",
            "",
            "        OwnershipSet",
            "            " + _row("Regions", " ".join(EVIL_REGIONS)),
            "            " + _row("StartRegion", EVIL_CAPITAL),
            "        End",
            "",
            "        OwnershipSet",
            "            " + _row("Regions", " ".join(good)),
            "            " + _row("StartRegion", GOOD_CAPITAL),
            "        End",
            "    End",
        ]

    def act(self, act: Block, index: int) -> list[str]:
        self.act_index = index
        last: dict[str, int] = {}
        for block in act.blocks("MoveArmy"):
            last[block.get("Name") or ""] = id(block)
        self.superseded = {
            id(block)
            for block in act.blocks("MoveArmy")
            if last[block.get("Name") or ""] != id(block)
        }
        lines = ["    ;//////////////////////////////////////////////////", f"    Act {act.name}"]
        for item in act.items:
            if isinstance(item, Block):
                handler = getattr(self, f"verb_{item.kind}", None)
                if handler is None:
                    lines.append("        " + self.flag("verb", f"{item.kind} has no ROTWK verb"))
                    lines.extend(_commented(self.copy(item, 8)))
                else:
                    lines.extend(handler(item))
                continue
            key, value = item
            if key == "DespawnArmy":
                lines.append("        " + _row(key, value))
            elif key in ("EndAct", "JumpToAct", "CallActSubroutine"):
                lines.append("        " + _row(key, value))
            else:
                lines.append("        " + self.flag("verb", f"Act field {key} has no ROTWK field"))
                lines.append("        ;" + _row(key, value))
        lines.extend(["    End", ""])
        return lines

    def copy(self, block: Block, indent: int) -> list[str]:
        pad = " " * indent
        lines = [f"{pad}{block.kind} {block.name}".rstrip()]
        for item in block.items:
            if isinstance(item, Block):
                lines.extend(self.copy(item, indent + 4))
            else:
                lines.append(f"{pad}    " + _row(*item))
        lines.append(f"{pad}End")
        return lines

    def written(self, kind: str, rows: Iterable[str], indent: int = 8) -> list[str]:
        pad = " " * indent
        return [f"{pad}{kind}", *(f"{pad}    {row}" for row in rows), f"{pad}End"]

    def verb_SpawnArmy(self, block: Block) -> list[str]:
        name = block.get("Name") or ""
        army = block.get("PlayerArmy") or ""
        if _yes(block.get("IsCity")) or name.endswith("_Mouseover"):
            return [f"        ; BFME1 city mouse-over {name}, only there to play a video: left out"]
        self.armies_used.append(army)
        owner = EVIL_TEMPLATE if _yes(block.get("PlayerOwned")) else GOOD_TEMPLATE
        rows = [
            _row("ScriptingName", name),
            _row("SpawnForTemplates", owner),
            _row("PlayerArmy", army),
        ]
        hero = ARMY_HEROES.get(name)
        if hero is None:
            rows.append(
                self.flag(
                    "hero",
                    f"{name} names no hero, so it merges into its player's army if it spawns in "
                    "a region that player owns",
                )
            )
        elif hero.lower() not in self.objects:
            rows.append(self.flag("hero", f"Edain has no hero {hero} for {name}"))
        else:
            rows.append(_row("HeroTemplateName", self.objects[hero.lower()]))
        icon = block.get("Icon")
        if icon:
            rows.append(_row("Icon", ICONS.get(icon, icon)))
        if block.get("IconSize"):
            rows.append(_row("IconSize", block.get("IconSize") or ""))
        original = block.get("Banner")
        banner = ARMY_BANNERS.get(name, original)
        if banner:
            note = f"BFME1 {original}" if original and original != banner else None
            rows.append(_row("Banner", banner, note))
        if block.get("Position"):
            rows.append(_row("Position", block.get("Position") or ""))
            rows.append(_row("ExactPosition", "Yes"))
        if block.get("Faction"):
            rows.append(f"; BFME1 Faction = {block.get('Faction')}: owned by the one Mordor player")
        if block.get("PalantirMovie"):
            rows.append(f"; PLACEHOLDER(video): PalantirMovie = {block.get('PalantirMovie')}")
        lines = self.written("SpawnArmy", rows)
        if block.get("PlayerControlled") and not _yes(block.get("PlayerControlled")):
            lines.extend(self.control(name, "No"))
        return lines

    def control(self, name: str, controllable: str) -> list[str]:
        return self.written(
            "SetPlayerControlOfArmy",
            [_row("ArmyScriptingName", name), _row("IsControllableByOwner", controllable)],
        )

    def verb_ToggleArmyControl(self, block: Block) -> list[str]:
        return self.control(block.get("Name") or "", block.get("PlayerControl") or "Yes")

    def verb_MoveArmy(self, block: Block) -> list[str]:
        name = block.get("Name") or ""
        if name.endswith("_Mouseover"):
            return [f"        ; BFME1 video update for city mouse-over {name}: left out"]
        rows = [_row("ArmyScriptingName", name)]
        move_to = block.get("MoveTo")
        point = _point(move_to)
        if point is None:
            return ["        " + self.flag("position", f"MoveArmy {name} has no MoveTo point")]
        region, distance = self.nearest(point)
        note = f"BFME1 MoveTo {move_to}, region centre {distance:.0f} away"
        rows.append(_row("TargetRegionName", region, note))
        if block.get("MoveSpeed"):
            rows.append(f"; BFME1 MoveSpeed = {block.get('MoveSpeed')}: no ROTWK move speed")
        if _yes(block.get("PlayNextActAfterMove")):
            rows.append("; BFME1 PlayNextActAfterMove = Yes: the next act runs on the next turn")
        if block.get("PalantirMovie"):
            rows.append(f"; PLACEHOLDER(video): PalantirMovie = {block.get('PalantirMovie')}")
        lines = self.written("MoveArmy", rows)
        if id(block) in self.superseded:
            # BFME1 steers an army through waypoints within one act; ROTWK moves region to region,
            # so an act's last move is the army's destination and the earlier ones are only a route.
            note = f"        ; {name} moves again later in this act: only its last move is kept"
            return [note, *_commented(lines)]
        if distance <= FAR:
            side, holder = self.sides.get(name), self.held.get(region)
            battles = set(self.battles[self.act_index])
            if self.act_index + 1 < len(self.battles):
                battles |= self.battles[self.act_index + 1]
            if side and holder and holder != side and region not in battles:
                # An army entering a region the other side holds starts a battle there; the story
                # only fights where it forces a battle, so any other such march is left out.
                message = (
                    f"MoveArmy {name} into {region}, which the other side holds at the start: "
                    "left out so the story starts no battle there"
                )
                return ["        " + self.flag("march", message), *_commented(lines)]
            return lines
        # A point this far from every centre is a waypoint between regions; sending the army to
        # whichever centre happens to be nearest would march it somewhere the story never goes.
        # It stays put, and the next move that does land in a region catches it up.
        message = (
            f"MoveArmy {name} to {move_to} lies between regions ({region} is {distance:.0f} away)"
        )
        return ["        " + self.flag("position", f"{message}: left in place"), *_commented(lines)]

    def verb_EnableRegion(self, block: Block) -> list[str]:
        source = block.get("Region") or ""
        region, note = self.region(source)
        if region is None:
            return [f"        {note}", *_commented(self.copy(block, 8))]
        lines = self.written("EnableRegion", [_row("Region", region)])
        return [f"        {note}", *lines] if note else lines

    def verb_ForceBattle(self, block: Block) -> list[str]:
        rows: list[str] = []
        source = block.get("Region")
        position = block.get("Position")
        if source:
            region, note = self.region(source)
            if note:
                rows.append(note)
            if region is not None:
                rows.append(_row("Region", region))
            elif position is None and MISSING_REGIONS.get(source, ("", None))[1] is not None:
                x, y = MISSING_REGIONS[source][1]  # type: ignore[misc]
                position = f"X:{x:g} Y:{y:g}"
                rows.append(f"; the battle lands in whichever Edain region covers BFME1's {source}")
            elif position is None:
                return [
                    "        " + self.flag("region", f"ForceBattle in {source} has nowhere to go"),
                    *_commented(self.copy(block, 8)),
                ]
        if position:
            rows.append(_row("Position", position))
        if block.get("UseArmy"):
            rows.append(_row("UseArmy", block.get("UseArmy") or ""))
        if block.get("ArmyAttackDirection"):
            direction = block.get("ArmyAttackDirection") or ""
            rows.append(_row("ArmyAttackDirection", direction, "parsed, not used by ROTWK"))
        return self.written("ForceBattle", rows)

    def verb_RegionReinforcements(self, block: Block) -> list[str]:
        source = block.get("RegionName") or ""
        region, note = self.region(source)
        lines = [
            "        "
            + self.flag(
                "verb",
                "RegionReinforcements has no ROTWK equivalent: its armies are moved in instead",
            ),
            *_commented(self.copy(block, 8)),
        ]
        if note:
            lines.append(f"        {note}")
        if region is None:
            return lines
        for army in block.values("AddReinforcementArmy"):
            lines.extend(
                self.written(
                    "MoveArmy", [_row("ArmyScriptingName", army), _row("TargetRegionName", region)]
                )
            )
        return lines

    def verb_MoveCamera(self, block: Block) -> list[str]:
        return self.copy(block, 8)

    def verb_SplineCamera(self, block: Block) -> list[str]:
        points = sorted(
            block.blocks("ControlPoint"), key=lambda point: float(point.get("Time") or 0)
        )
        if not points:
            return []
        length = float(points[-1].get("Time") or 0)
        lines = [
            f"        ; BFME1 SplineCamera: {len(points)} control points over {length:g}s, replayed"
            f" as MoveCamera at {CAMERA_TIME_SCALE:g}x that pace",
        ]
        start = float(block.get("DelayFromActStart") or 0)
        previous = 0.0
        for point in points:
            time = float(point.get("Time") or 0)
            scroll = max(MIN_SCROLL_TIME, (time - previous) * CAMERA_TIME_SCALE)
            rows = [
                _row("DelayFromActStart", f"{start:.1f}"),
                _row("Position", point.get("Position") or ""),
                _row("ViewAngle", point.get("Angle") or "0"),
                _row("ScrollTime", f"{scroll:.1f}"),
            ]
            lines.extend(self.written("MoveCamera", rows))
            start += scroll * CAMERA_LEG_START
            previous = time
        return lines

    def verb_EyeTowerPoints(self, block: Block) -> list[str]:
        return self.copy(block, 8)

    def verb_WorldText(self, block: Block) -> list[str]:
        return ["        ; PLACEHOLDER(text)", *_commented(self.copy(block, 8))]

    def verb_AudioEvent(self, block: Block) -> list[str]:
        return ["        ; PLACEHOLDER(audio)", *_commented(self.copy(block, 8))]

    def player_armies(self, armies: list[Block]) -> list[str]:
        used = set(self.armies_used)
        lines = [
            ";//////////////////////////////////////////////////",
            ";// Player armies, from the BFME1 campaign",
            ";//////////////////////////////////////////////////",
            "",
        ]
        left_out = [army.get("Name") or "" for army in armies if army.get("Name") not in used]
        if left_out:
            lines.append("; Not spawned by any converted act, so left out: " + " ".join(left_out))
            lines.append("")
        for army in armies:
            name = army.get("Name")
            if name not in used:
                continue
            self.where = f"army {name}"
            lines.append("LivingWorldPlayerArmy")
            for item in army.items:
                if isinstance(item, Block):
                    lines.extend(self.army_entry(item))
                    continue
                key, value = item
                if key in ("Name", "DisplayNameTag", "Color", "NightColor"):
                    lines.append("    " + _row(key, value))
                else:
                    lines.append(f"    ; BFME1 {key} = {value}: no ROTWK field")
            lines.extend(["End", ""])
        return lines

    def army_entry(self, entry: Block) -> list[str]:
        template = entry.get("ThingTemplate") or ""
        replacement = UNIT_REPLACEMENTS.get(template)
        known = self.objects.get((replacement or template).lower())
        if known is None:
            close = difflib.get_close_matches(template, list(self.objects.values()), 3, 0.6)
            hint = f" (close: {', '.join(close)})" if close else ""
            return [
                "    " + self.flag("unit", f"Edain has no {template}{hint}"),
                *_commented(self.copy(entry, 4)),
            ]
        note = f"BFME1 {template}" if replacement else None
        rows = [_row("ThingTemplate", known, note), _row("Quantity", entry.get("Quantity") or "1")]
        return self.written("ArmyEntry", rows, 4)


def _commented(lines: Iterable[str]) -> Iterator[str]:
    """Lines kept as comments, at their own indentation."""
    for line in lines:
        stripped = line.lstrip()
        yield f"{line[: len(line) - len(stripped)]};{stripped}"


def edain_regions(ini_root: Path) -> dict[str, tuple[float, float] | None]:
    text = (ini_root / "campaigns" / "common" / "livingworldregions.inc").read_text("cp1252")
    blocks = parse_blocks(text, ["Region"])
    return {block.name: _point(block.get("CenterPoint")) for block in blocks}


def plotless_regions(ini_root: Path) -> str:
    """Edain's region file with every build plot commented out, left otherwise untouched so the
    copy stays a line-for-line diff of the file it came from."""
    text = (ini_root / "campaigns" / "common" / "livingworldregions.inc").read_text("cp1252")
    plot = re.compile(r"^(\s*)(BuildingSpot\s*=.*|CreateAutoFort\s*=\s*Yes\b.*)$", re.IGNORECASE)
    lines = [
        f"; A copy of livingworldregions.inc for {CAMPAIGN_NAME}, with no build plots.",
        "; Generated by tools/convert_bfme1_campaign.py; hand edits are lost on regeneration.",
        "",
    ]
    lines.extend(plot.sub(r"\1;\2", line) for line in text.splitlines())
    return "\n".join(lines) + "\n"


def region_campaign(ini_root: Path) -> list[str]:
    """`REGION_CAMPAIGN`: `DefaultCampaign`'s settings, read from `riskcampaign.ini` so they follow
    Edain's, over the plot-free copy of its regions."""
    text = (ini_root / "campaigns" / "riskcampaign.ini").read_text("cp1252").splitlines()
    start = next(
        index
        for index, line in enumerate(text)
        if re.match(rf"\s*LivingWorldRegionCampaign\s+{REGION_SOURCE}\b", line)
    )
    end = next(index for index in range(start, len(text)) if "#include" in text[index])
    return [
        f"LivingWorldRegionCampaign {REGION_CAMPAIGN}",
        *text[start + 1 : end],
        f'    #include "..\\Common\\{REGION_FILE}"',
        "End",
    ]


def edain_objects(ini_root: Path) -> set[str]:
    names: set[str] = set()
    for path in ini_root.rglob("*.in[ic]"):
        names.update(_OBJECT.findall(path.read_text("cp1252", errors="replace")))
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="the BFME1 campaign ini")
    parser.add_argument("--edain", type=Path, required=True, help="Edain's _mod/data/ini")
    parser.add_argument("--out", type=Path, required=True, help="the scenario .inc to write")
    args = parser.parse_args(argv)

    text = args.source.read_text("cp1252")
    blocks = parse_blocks(text, ["LivingWorldCampaign", "LivingWorldPlayerArmy"])
    campaigns = [block for block in blocks if block.kind == "LivingWorldCampaign"]
    if len(campaigns) != 1:
        print(f"expected one LivingWorldCampaign, found {len(campaigns)}", file=sys.stderr)
        return 1
    armies = [block for block in blocks if block.kind == "LivingWorldPlayerArmy"]

    converter = Converter(edain_regions(args.edain), edain_objects(args.edain))
    output = converter.convert(campaigns[0], armies, args.source.name, region_campaign(args.edain))
    args.out.write_text(output, "cp1252")
    regions_out = args.edain / "campaigns" / "common" / REGION_FILE
    regions_out.write_text(plotless_regions(args.edain), "cp1252")

    acts = len(campaigns[0].blocks("Act"))
    print(f"wrote {args.out} ({acts} acts, {len(converter.flags)} flags)")
    print(f"wrote {regions_out}")
    for (kind, message), wheres in sorted(converter.flags.items()):
        print(f"  {kind:<8} {message}")
        print(f"           in {', '.join(wheres)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
