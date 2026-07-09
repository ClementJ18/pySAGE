"""Living-World (War of the Ring) campaign sub-blocks. A `LivingWorldCampaign` nests `Act`s
(which spawn armies and aim the eye-tower camera) and `Scenario`s (with their victory/defeat
conditions); a region campaign nests `Region`s (with map connections and build restrictions);
`LivingWorldBuilding` nests `BuildingNugget`s, and `LinearCampaign` nests `Mission`s.

These are deeply nested and largely descriptive, so fields are typed conservatively - labels,
map/army names and `X:Y:` coordinates as raw strings, plain counts/flags as Int/Bool - and
each container declares its child blocks via `nested_attributes`. The named blocks (`Act One`,
`Region <name>`) take the token after the keyword as their name. Repeated point/list fields
are `List`s so they are not mistaken for last-wins scalars.
"""

import sage_ini.model.types as t
from sage_ini.model.objects import NestedAttribute


class EyeTowerPoints(NestedAttribute):
    """The `EyeTowerPoints` block in an `Act`: the camera look-points the eye sweeps."""

    LookPoint: t.List[t.Untyped]


class WorldText(NestedAttribute):
    """A scripted on-screen caption during an `Act` (`StringTag` shown after a delay)."""

    StringTag: t.Untyped
    DelayFromActStart: t.Float


class MoveCamera(NestedAttribute):
    """A scripted camera move during an `Act`: where it scrolls to, over how long."""

    Position: t.Coords
    ViewAngle: t.Int
    ScrollTime: t.Float
    DelayFromActStart: t.Float


class MoveArmy(NestedAttribute):
    """A scripted army move during an `Act`: send the named army to a region."""

    ArmyScriptingName: t.Untyped
    TargetRegionName: t.Untyped
    DefaultArmyMoveSpeed: t.Float
    DelayFromActStart: t.Float


class SetPlayerControlOfArmy(NestedAttribute):
    """Hand a scripted army to (or take it from) the owning player during an `Act`."""

    ArmyScriptingName: t.Untyped
    IsControllableByOwner: t.Bool
    DelayFromActStart: t.Float


class EnableRegion(NestedAttribute):
    """Open a region for play during an `Act`."""

    Region: t.Untyped
    ArmyScriptingName: t.Untyped
    DelayFromActStart: t.Float


# The scripted actions an `Act` (and a `Scenario`'s historical setup) sequences.
_ACT_ACTIONS = {
    name: [name]
    for name in (
        "SpawnArmy",  # reuses the top-level SpawnArmy class
        "EyeTowerPoints",
        "WorldText",
        "MoveCamera",
        "MoveArmy",
        "SetPlayerControlOfArmy",
        "EnableRegion",
    )
}


class StartingRestriction(NestedAttribute):
    """A `Scenario` starting restriction: which teams/factions may start in which regions."""

    Teams: t.Untyped
    Regions: t.Untyped
    Factions: t.Untyped


class Act(NestedAttribute):
    """One `Act <name>` of a `LivingWorldCampaign`: the armies it spawns, the eye-tower camera
    points and the scripted actions (text, camera, army moves) played as a stage of the war."""

    nested_attributes = _ACT_ACTIONS


class _DefeatCondition(NestedAttribute):
    Teams: t.Untyped
    LoseIfCapitalLost: t.Bool
    NumControlledRegionsLessOrEqualTo: t.Int
    ControlledRegions: t.Opaque
    ControlledRegionsHeldForTurns: t.Int
    NumControlledRegionsGreaterOrEqualTo: t.Int


class PlayerDefeatCondition(_DefeatCondition):
    """When a player loses a `Scenario` (capital lost, too few regions)."""


class TeamDefeatCondition(_DefeatCondition):
    """When a team loses a `Scenario`."""


class _VictoryCondition(NestedAttribute):
    Teams: t.Untyped
    NumControlledRegionsGreaterOrEqualTo: t.Int
    ControlledRegions: t.List[t.Untyped]


class PlayerVictoryCondition(_VictoryCondition):
    """When a player wins a `Scenario`."""


class TeamVictoryCondition(_VictoryCondition):
    """When a team wins a `Scenario`."""


class SpawnArmies(NestedAttribute):
    """Pre-placed armies in an `OwnershipSet`."""

    Player: t.Untyped
    Army: t.List[t.Untyped]
    Armies: t.List[t.Opaque]
    Region: t.Opaque


class SpawnBuildings(NestedAttribute):
    """Pre-placed buildings in an `OwnershipSet`."""

    Player: t.Untyped
    Building: t.List[t.Untyped]
    Region: t.Opaque
    Buildings: t.List[t.Opaque]


class OwnershipSet(NestedAttribute):
    """A `Scenario` starting layout: which regions a player owns and what is placed on them."""

    Regions: t.List[t.Untyped]
    StartRegion: t.Untyped

    nested_attributes = {"SpawnArmies": ["SpawnArmies"], "SpawnBuildings": ["SpawnBuildings"]}


class Scenario(NestedAttribute):
    """One `Scenario` of a `LivingWorldCampaign`: its display text, the region campaign it
    plays on, and the conditions that win or lose it."""

    DisplayName: t.Untyped
    DisplayDescription: t.Untyped
    DisplayGameType: t.Untyped
    DisplayObjectives: t.Untyped
    DisplayFiction: t.Untyped
    DisplayVictoriousText: t.Untyped
    DisplayDefeatedText: t.Untyped
    RegionCampaign: t.RegionCampaignRef
    NumPlayers: t.Int
    MaxPlayers: t.Int
    DefaultStartSpots: t.List[t.Opaque]
    DisallowStartInRegions: t.List[t.Opaque]
    DisableRegions: t.List[t.Opaque]
    DisabledFactions: t.Opaque
    HistoricalScenario: t.Bool
    MinPlayers: t.Int

    nested_attributes = {
        "PlayerDefeatCondition": ["PlayerDefeatCondition"],
        "TeamDefeatCondition": ["TeamDefeatCondition"],
        "PlayerVictoryCondition": ["PlayerVictoryCondition"],
        "TeamVictoryCondition": ["TeamVictoryCondition"],
        "OwnershipSet": ["OwnershipSet"],
        "StartingRestriction": ["StartingRestriction"],
        **_ACT_ACTIONS,  # a historical scenario sequences the same scripted actions
    }


class Connection(NestedAttribute):
    """A map link between two `Region`s, via an optional detour point."""

    Region: t.Untyped
    DetourPoint: t.List[t.Untyped]


class RestrictBuildings(NestedAttribute):
    """A per-region cap on how many of certain buildings may be built."""

    Buildings: t.Untyped
    NumberAllowed: t.Int


class Region(NestedAttribute):
    """One `Region <name>` of a region campaign: its map, display, army/building spots, and
    the connections and build restrictions that shape it on the strategic map."""

    DisplayName: t.Untyped
    MapName: t.Untyped
    HeroArmySpot: t.List[t.Untyped]
    BuildingSpot: t.List[t.Untyped]
    SubObject: t.List[t.Untyped]
    ConqueredNotice: t.Untyped
    SkirmishStillImage: t.Untyped

    SkirmishMusicTrack: t.Opaque
    RegionPortrait: t.Opaque
    ConnectsTo: t.List[t.Opaque]
    GarrisonArmySpot: t.Coords
    CenterPoint: t.Coords
    CustomCenterPoint: t.Bool
    CPLimit: t.Int
    AllyCPLimit: t.Int
    MovieNameFirstTime: t.Opaque
    MovieNameRepeat: t.Opaque

    # Per-region strategic bonuses granted to its owner.
    AttackBonus: t.Int
    DefenseBonus: t.Int
    ArmyBonus: t.Int
    LegendaryBonus: t.Int
    ExperienceBonus: t.Int
    ResourceBonus: t.Int
    FertileTerritoryBonus: t.Int

    # Auto-built fortress.
    CreateAutoFort: t.Bool
    FortressPortrait: t.Opaque
    FortressDisplayName: t.Untyped
    FortressDisplayDescription: t.Untyped

    nested_attributes = {"Connection": ["Connection"], "RestrictBuildings": ["RestrictBuildings"]}


class ArmyToSpawn(NestedAttribute):
    """The army a `BuildingNugget` can construct, with its build UI."""

    PlayerArmy: t.Untyped
    Icon: t.ArmyIcon
    IconSize: t.Untyped
    PalantirMovie: t.Untyped
    BuildTime: t.Int
    ConstructButtonImage: t.Untyped
    ConstructButtonTitle: t.Untyped
    ConstructButtonHelp: t.Untyped
    HeroTemplateName: t.String


class BuildingNugget(NestedAttribute):
    """A buildable nugget of a `LivingWorldBuilding`: the bonus it grants, its queue and the
    armies it can spawn."""

    Type: t.Untyped
    Amount: t.Int
    Bonus: t.List[t.Untyped]
    BonusKey: t.Untyped
    TreasureAmount: t.Int
    QueueSize: t.Int
    StrengtheningRange: t.Untyped  # a named range keyword (e.g. THIS_TERRITORY), not a number
    NumUpgradesPerTurn: t.Int
    UpgradeableUnits: t.List[t.ObjectRef]

    nested_attributes = {"ArmyToSpawn": ["ArmyToSpawn"]}


class Mission(NestedAttribute):
    """One `Mission` of a `LinearCampaign`: the map and the load/intro presentation."""

    Map: t.Untyped
    IntroMovie: t.Untyped
    LoadScreenImage: t.Untyped
    LoadScreenMusicTrack: t.Untyped
    DelayCarryoverSpawningOf: t.List[t.ObjectRef]
    MillisecondsAfterStartToStartFadeUp: t.Int


class ColorIntensityControlPoint(NestedAttribute):
    """A keyframe in a region-effect colour envelope (`Value`/`Color`)."""

    Value: t.Untyped
    Color: t.RGB
    Intensity: t.Float
    Time: t.Float


class _RegionEffect(NestedAttribute):
    """A named region-highlight effect; its colour envelope is a run of control points."""

    nested_attributes = {"ColorIntensityControlPoint": ["ColorIntensityControlPoint"]}

    Geometry: t.Untyped
    LoadInShell: t.Bool


class BordersEffect(_RegionEffect):
    pass


class FilledOwnershipEffect(_RegionEffect):
    pass


class MouseoverEffectFlareup(_RegionEffect):
    pass


class HomeRegionHighlight(_RegionEffect):
    pass


class RegionSelectionEffect(_RegionEffect):
    pass


class UnifiedEffect(_RegionEffect):
    pass


class ArmyEntry(NestedAttribute):
    """One unit slot of a `LivingWorldPlayerArmy`: a template and how many of it."""

    ThingTemplate: t.Untyped
    Quantity: t.Int


class BonusForLevel(NestedAttribute):
    """A per-level bonus tier of an `AutoResolveLeadership`: the multipliers applied once a
    unit reaches `MinLevel` (kept as raw strings - the values are percentages)."""

    MinLevel: t.Int
    WeaponMultiplier: t.Float
    ExperienceMultiplier: t.Float
    ArmorMultiplier: t.Float
    MaximumUnitsAffected: t.Int
    Priority: t.Int


class Bonus(NestedAttribute):
    """A bonus tier of a living-world auto-resolve resource/science-point bonus: the threshold
    it kicks in at and the combat multipliers it grants."""

    MinResourceBonus: t.Int
    MinSciencePurchasePoints: t.Int
    MinSciencePurchasePointsForBonus: t.Int
    WeaponMultiplier: t.Float
    ArmorMultiplier: t.Float
    ExperienceMultiplier: t.Float
