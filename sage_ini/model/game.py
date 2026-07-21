"""The Game container: every typed object built from a document, grouped by its class
`key` (`upgrades`, `weapons`, `objects`, …), plus the macro and string tables conversion
reads from. The `game` argument threaded into every converter.
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import sage_ini.model.definitions  # noqa: F401  (populate the class registry)
from sage_ini.model import data_blocks as _db
from sage_ini.model import ini_objects as _io
from sage_ini.model.objects import IniObject, get_class
from sage_ini.parser.ast import Block, IniDocument, MacroDef
from sage_ini.parser.diagnostics import Diagnostics
from sage_ini.parser.location import Span

__all__ = ["Game", "Redefinition"]


class _Table[T: IniObject]:
    """Typed accessor for one fixed Game table: `game.objects` reads `dict[str, Object]`.
    The table set can't grow (a mod adds entries, never new tables), so each is declared once
    on `Game` and the element type rides along on the class passed here. It's a live view onto
    the same `tables` dict the dynamic loader fills - reads and writes go to one place."""

    def __init__(self, cls: type[T]) -> None:
        assert cls.key is not None, f"{cls.__name__} has no table key"
        self.cls = cls
        self._key = cls.key

    def __get__(self, obj, owner=None) -> dict[str, T]:
        if obj is None:
            return self  # type: ignore[return-value]
        return cast("dict[str, T]", obj.tables[self._key])


@dataclass(frozen=True, slots=True)
class Redefinition:
    """A unique-named definition declared twice in one file (last wins). Cross-file
    redefinitions (the engine's override mechanism) are not recorded. A neutral load fact;
    the duplicate-definition lint rule judges it."""

    key: str  # the Game table the definition registers into
    name: str  # the shared definition name
    first: Span  # where the earlier (shadowed) definition opened
    second: Span  # where the later (winning) definition opened


class Game:
    # Typed views onto the fixed table set (see `_Table`). The dynamic `tables` dict below
    # stays the source of truth; these just give each known table its element type.
    upgrades = _Table(_io.Upgrade)
    armorsets = _Table(_io.Armor)
    specialpowers = _Table(_io.SpecialPower)
    sciences = _Table(_io.Science)
    attackpriorities = _Table(_io.AttackPriority)
    objectcreationlists = _Table(_io.ObjectCreationList)
    commandbuttons = _Table(_io.CommandButton)
    levels = _Table(_io.ExperienceLevel)
    emotions = _Table(_io.EmotionNugget)
    commandsets = _Table(_io.CommandSet)
    modifiers = _Table(_io.ModifierList)
    weapons = _Table(_io.Weapon)
    locomotors = _Table(_io.Locomotor)
    objects = _Table(_io.Object)
    factions = _Table(_io.PlayerTemplate)
    stancetemplates = _Table(_io.StanceTemplate)
    mappedimages = _Table(_db.MappedImage)
    audioevents = _Table(_db.AudioEvent)
    particlesystems = _Table(_db.FXParticleSystem)
    fxlists = _Table(_db.FXList)
    terrains = _Table(_db.Terrain)
    dialogevents = _Table(_db.DialogEvent)
    musictracks = _Table(_db.MusicTrack)
    multisounds = _Table(_db.Multisound)
    evaevents = _Table(_db.NewEvaEvent)
    videos = _Table(_db.Video)
    housecolors = _Table(_db.HouseColor)
    livingworldplayerarmys = _Table(_db.LivingWorldPlayerArmy)
    ranks = _Table(_db.Rank)
    autoresolvebodys = _Table(_db.AutoResolveBody)
    aibases = _Table(_db.AIBase)
    debugcommandmaps = _Table(_db.DebugCommandMap)
    cursors = _Table(_db.MouseCursor)
    livingworldarmyicons = _Table(_db.LivingWorldArmyIcon)
    livingworldanimobjects = _Table(_db.LivingWorldAnimObject)
    largegroupaudiomaps = _Table(_db.LargeGroupAudioMap)
    controlbarresizers = _Table(_db.ControlBarResizer)
    roads = _Table(_db.Road)
    windowtransitions = _Table(_db.WindowTransition)
    livingworldcampaigns = _Table(_db.LivingWorldCampaign)
    loadsubsystems = _Table(_db.LoadSubsystem)
    livingworldbuildings = _Table(_db.LivingWorldBuilding)
    livingworldbuildingicons = _Table(_db.LivingWorldBuildingIcon)
    ambientstreams = _Table(_db.AmbientStream)
    livingworldsounds = _Table(_db.LivingWorldSound)
    # evaevents also -> _db.PredefinedEvaEvent (use tables['evaevents'] for the alternate type)
    playeraitypes = _Table(_db.PlayerAIType)
    damagefxs = _Table(_db.DamageFX)
    factionvictorydatas = _Table(_db.FactionVictoryData)
    autoresolveleaderships = _Table(_db.AutoResolveLeadership)
    autoresolvehandicaplevels = _Table(_db.AutoResolveHandicapLevel)
    multiplayercolors = _Table(_db.MultiplayerColor)
    livingworldplayertemplates = _Table(_db.LivingWorldPlayerTemplate)
    bannertypes = _Table(_db.BannerType)
    livingworldbuildploticons = _Table(_db.LivingWorldBuildPlotIcon)
    spawnarmys = _Table(_db.SpawnArmy)
    aidozerassignments = _Table(_db.AIDozerAssignment)
    armydefinitions = _Table(_db.ArmyDefinition)
    controlbarschemes = _Table(_db.ControlBarScheme)
    concurrentregionbonus = _Table(_db.ConcurrentRegionBonus)
    crowdresponses = _Table(_db.CrowdResponse)
    livingworldobjects = _Table(_db.LivingWorldObject)
    watertexturelists = _Table(_db.WaterTextureList)
    skyboxtexturesets = _Table(_db.SkyboxTextureSet)
    livingworldregioncampaigns = _Table(_db.LivingWorldRegionCampaign)
    weatherdatas = _Table(_db.WeatherData)
    autoresolvecombatchains = _Table(_db.AutoResolveCombatChain)
    experiencescalartables = _Table(_db.ExperienceScalarTable)
    webpageurls = _Table(_db.WebpageURL)
    dynamicgamelods = _Table(_db.DynamicGameLOD)
    linearcampaigns = _Table(_db.LinearCampaign)
    staticgamelods = _Table(_db.StaticGameLOD)
    autoresolvereinforcementschedules = _Table(_db.AutoResolveReinforcementSchedule)
    gamedatas = _Table(_db.GameData)
    livingworldregioneffects = _Table(_db.LivingWorldRegionEffects)
    watersets = _Table(_db.WaterSet)
    aidatas = _Table(_db.AIData)
    fontdefaultsettings = _Table(_db.FontDefaultSettings)
    multiplayersettings = _Table(_db.MultiplayerSettings)
    victorysystemdatas = _Table(_db.VictorySystemData)
    armysummarydescriptions = _Table(_db.ArmySummaryDescription)
    audiolods = _Table(_db.AudioLOD)
    awardsystems = _Table(_db.AwardSystem)
    bridges = _Table(_db.Bridge)
    commandmaps = _Table(_db.CommandMap)
    createaherosystems = _Table(_db.CreateAHeroSystem)
    credits = _Table(_db.Credits)
    formationassistants = _Table(_db.FormationAssistant)
    ingamenotificationboxs = _Table(_db.InGameNotificationBox)
    ingameuis = _Table(_db.InGameUI)
    livingworldaitemplates = _Table(_db.LivingWorldAITemplate)
    livingworldautoresolveresourcebonus = _Table(_db.LivingWorldAutoResolveResourceBonus)
    livingworldautoresolvesciencepurchasepointbonus = _Table(
        _db.LivingWorldAutoResolveSciencePurchasePointBonus
    )
    livingworldmapinfos = _Table(_db.LivingWorldMapInfo)
    miscevadatas = _Table(_db.MiscEvaData)
    mouses = _Table(_db.Mouse)
    onlinechatcolors = _Table(_db.OnlineChatColors)
    optiongroups = _Table(_db.OptionGroup)
    regioncampains = _Table(_db.RegionCampain)
    scoredkillevaannouncers = _Table(_db.ScoredKillEvaAnnouncer)
    skirmishaidatas = _Table(_db.SkirmishAIData)
    animationsoundclientbehaviorglobalsettings = _Table(
        _db.AnimationSoundClientBehaviorGlobalSetting
    )
    aptbuttontooltipmaps = _Table(_db.AptButtonTooltipMap)
    audiosettings = _Table(_db.AudioSettings)
    buttonsets = _Table(_db.ButtonSet)
    cloudeffects = _Table(_db.CloudEffect)
    createaheroclass = _Table(_db.CreateAHeroClass)
    drawgroupinfos = _Table(_db.DrawGroupInfo)
    fires = _Table(_db.Fire)
    fireeffects = _Table(_db.FireEffect)
    firelogicsystems = _Table(_db.FireLogicSystem)
    fontsubstitutions = _Table(_db.FontSubstitution)
    gloweffects = _Table(_db.GlowEffect)
    largegroupaudiounusedknownkeys = _Table(_db.LargeGroupAudioUnusedKnownKeys)
    lightpointlevels = _Table(_db.LightPointLevel)
    miscaudios = _Table(_db.MiscAudio)
    pathfinders = _Table(_db.Pathfinder)
    ringeffects = _Table(_db.RingEffect)
    shadowmaps = _Table(_db.ShadowMap)
    shellmenuschemes = _Table(_db.ShellMenuScheme)
    strategichuds = _Table(_db.StrategicHUD)
    streamedsounds = _Table(_db.StreamedSound)
    watertransparencys = _Table(_db.WaterTransparency)

    def __init__(self):
        self.tables: defaultdict[str, dict[str, IniObject]] = defaultdict(dict)
        self.macros: dict[str, str] = {}
        # Macro definition sites, for jump-to-definition. Only the directly loaded document
        # records a site (expansion paths carry no span); the latest definition wins.
        self.macro_definitions: dict[str, Span] = {}
        self.strings: dict[str, str] = {}
        # Label definition sites, for jump-to-definition. Only labels in the mod's own
        # `.str`/`.csv` files are recorded; a base-game-only label has no entry.
        self.string_definitions: dict[str, Span] = {}
        # Lower-cased asset basenames (e.g. "gbarcher.w3d") found under the mod root. Backs the
        # missing-texture/model rules; empty when a file is built in isolation, so they no-op.
        self.assets: set[str] = set()
        # Lower-cased file-entry names (e.g. "gbarcher.w3d") read from any asset.dat the caller
        # provided (`--asset-dat`). Backs the sage_lint asset-dat-membership rules; empty when
        # none was given, so they no-op.
        self.asset_dat_names: set[str] = set()
        # WorldBuilder layout files (`.map`/`.bse`), full paths so the linter can resolve a
        # `MapFile` by basename and flag a stem that mismatches its `<name>/<name>.ext` folder.
        self.map_files: list[Path] = []
        self.diagnostics = Diagnostics()
        self.redefinitions: list[Redefinition] = []
        # Opening span of the latest definition per (key, name), to pair a same-file repeat
        # with the one it shadows.
        self._definition_sites: dict[tuple[str, str], Span] = {}
        # Notes raised while converting the current field; `validate` drains them per field to
        # attach each one's span.
        self._pending_warnings: list[tuple[str, str, dict]] = []
        # Lower-cased -> registered name indexes backing case-insensitive lookup, since the
        # engine interns both INI names and macro names case-insensitively.
        self._folded_names: defaultdict[str, dict[str, str]] = defaultdict(dict)
        self._folded_macros: dict[str, str] = {}
        # An already-built game consulted when a reference misses locally, so one file can be
        # rebuilt in isolation yet resolve names from its siblings (incremental re-lint path).
        self._reference_fallback: Game | None = None
        # True only while a map layer loads on top of the global game (`load_map`). In this mode
        # a same-name re-definition patches the shadowed object in place (the engine's map
        # override) rather than replacing it wholesale, so `register` links the new object to the
        # one it shadows. Off during the normal build, where a re-definition is a plain override.
        self._map_override = False

    def warn(self, code: str, message: str, extra: dict | None = None) -> None:
        self._pending_warnings.append((code, message, extra or {}))

    def register(self, obj: IniObject) -> None:
        if obj.key is not None:
            table = self.tables[obj.key]
            if self._map_override:
                # A map layer re-opening an existing definition patches it in place; keep the
                # shadowed object reachable so inheritance-aware rules resolve through it. The
                # shadowed object is an earlier one in this build (a same-file re-open, flagged
                # separately as a duplicate) or - on the incremental path, where the map is built
                # into a throwaway game against the global cache - the definition in that cache.
                previous = table.get(obj.name)
                if previous is None and self._reference_fallback is not None:
                    previous, _ = self._reference_fallback.lookup(obj.key, obj.name)
                if previous is not None and previous is not obj:
                    obj._override_base = previous
            table[obj.name] = obj
            if isinstance(obj.name, str):
                self._folded_names[obj.key][obj.name.lower()] = obj.name

    def get(self, key: str, name: str) -> IniObject:
        return self.tables[key][name]

    def lookup(self, key: str, name) -> tuple[IniObject | None, object]:
        """Resolve a cross-reference `name` in table `key` the way the engine does: an exact
        match first, then a case-insensitive one (engine name lookup ignores case). Returns
        `(obj, canonical)` - `canonical` is the definition's actual name, differing from `name`
        only on a case-only match (which the caller flags) - or `(None, name)` when unknown."""
        table = self.tables.get(key, {})
        obj = table.get(name)
        if obj is not None:
            return obj, name
        if isinstance(name, str):
            canonical = self._folded_names.get(key, {}).get(name.lower())
            if canonical is not None:
                return table[canonical], canonical
        if self._reference_fallback is not None:
            return self._reference_fallback.lookup(key, name)
        return None, name

    def define_macro(self, name: str, value: str) -> None:
        """Record a `#define`, keeping the case-folded index in step so a later reference in
        another casing still expands (the latest definition's casing is the canonical one)."""
        self.macros[name] = value
        self._folded_macros[name.lower()] = name

    def add_macros(self, macros) -> None:
        """Merge a mapping of `#define`s in (e.g. a sibling-file cache), folded index included."""
        for name, value in macros.items():
            self.define_macro(name, value)

    def has_macro(self, name) -> bool:
        """Whether `name` names a `#define`, matching case-insensitively. Side-effect-free, so a
        lint that only needs to know a macro exists does not raise the case warning."""
        if not isinstance(name, str):
            return False
        return name in self.macros or name.lower() in self._folded_macros

    def get_macro(self, value):
        """Resolve a macro name to its value; pass non-macro values through. A name that matches
        a `#define` only after case-folding still expands (engine matching is loose), but records
        a `macro-case` warning naming the defined spelling - macro names are uppercase by
        convention, so a mismatch is almost always a typo."""
        if not isinstance(value, str):
            return value
        if value in self.macros:
            return self.macros[value]
        canonical = self._folded_macros.get(value.lower())
        if canonical is not None:
            self.warn(
                "macro-case",
                f"macro {value!r} should be {canonical!r} (case mismatch)",
                {"given": value, "canonical": canonical},
            )
            return self.macros[canonical]
        return value

    def load_document(self, document: IniDocument) -> None:
        """Build every top-level block that maps to a known class."""
        for node in document.children:
            if isinstance(node, MacroDef):
                self.define_macro(node.name, node.value)
                self.macro_definitions[node.name] = node.span
            elif isinstance(node, Block):
                cls = get_class(node.name)
                if cls is not None:
                    cls.from_block(self, node)
                    self._note_definition(node, cls)

    def _note_definition(self, node: Block, cls: type[IniObject]) -> None:
        """Record a same-file repeat of a unique-named, labelled definition. A label-less or
        collection (`unique_name = False`) block names a category that repeats by design."""
        if cls.key is None or node.label is None or not cls.unique_name:
            return
        # Key by the registered name, so a malformed `Object Foo Bar` pairs with `Object Foo`.
        name = cls.object_name(node)
        ident = (cls.key, name)
        previous = self._definition_sites.get(ident)
        if previous is not None and previous.file == node.span.file:
            self.redefinitions.append(Redefinition(cls.key, name, previous, node.span))
        self._definition_sites[ident] = node.span

    def validate(self) -> Diagnostics:
        """Drive conversion of every loaded object's fields (and their nested sub-objects),
        collecting problems as diagnostics; the pass never raises."""
        for table in list(self.tables.values()):
            for obj in list(table.values()):
                obj.validate(self.diagnostics)
        return self.diagnostics
