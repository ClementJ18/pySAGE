"""End-to-end tests for the ported game-object definitions.

These exercise real classes (Upgrade, Weapon, Object, ...) through the typed
layer: construction from a realistic block plus lazy field access.
"""

import pytest

import sage_ini.model.definitions  # noqa: F401  (register classes)
from sage_ini.model.behaviors import Body
from sage_ini.model.data_blocks import (
    AudioEvent,
    AudioSettings,
    InGameUI,
    LivingWorldMapInfo,
    MappedImage,
    MiscAudio,
)
from sage_ini.model.enums import (
    ButtonBorderTypes,
    DamageType,
    EditorSorting,
    EmotionNuggetAIState,
    EmotionTypes,
    GeometryType,
    ModelCondition,
    RadarPriority,
    SlotTypes,
)
from sage_ini.model.game import Game
from sage_ini.model.ini_objects import (
    ChildObject,
    CommandButton,
    EmotionNugget,
    Locomotor,
    Object,
    ObjectReskin,
    Upgrade,
    Weapon,
)
from sage_ini.model.nuggets import ClearNuggets, DamageNugget
from sage_ini.model.objects import Draw, get_class
from sage_ini.parser.ast import Block
from sage_ini.parser.blockparser import parse


def load(text: str) -> Game:
    game = Game()
    result = parse(text, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


def test_upgrade_fields_and_defaults():
    game = load(
        """\
        Upgrade Upgrade_Test
            Type = PLAYER
            BuildCost = 800
            BuildTime = 30
        End
        """
    )
    upgrade = game.upgrades["Upgrade_Test"]
    assert isinstance(upgrade, Upgrade)
    assert upgrade.BuildCost == 800
    assert upgrade.BuildTime == 30
    assert upgrade.PersistsInCampaign is False  # default
    assert upgrade.Tooltip is None  # annotated, absent, no default


def test_weapon_with_nuggets():
    game = load(
        """\
        Weapon TestSword
            AttackRange = 40
            DamageNugget
                Damage = 100
                DamageType = SLASH
            End
            MetaImpactNugget
                ShockWaveAmount = 5
            End
        End
        """
    )
    weapon = game.weapons["TestSword"]
    assert isinstance(weapon, Weapon)
    assert weapon.AttackRange == 40
    assert [type(n).__name__ for n in weapon.Nuggets] == ["DamageNugget", "MetaImpactNugget"]
    nugget = weapon.Nuggets[0]
    assert isinstance(nugget, DamageNugget)
    assert nugget.Damage == 100


def test_clear_nuggets_one_liner_parses_and_is_a_nugget():
    # ClearNuggets is written as a bare one-liner with no body/End; it must not open a block
    # (which would swallow the following nugget and leave the weapon unclosed), and it lands in
    # the weapon's Nuggets list as a body-less ClearNuggets, not an unknown attribute.
    game = load(
        """\
        Weapon EagleClawWyrmAttack
            ClearNuggets
            DamageNugget
                Damage = 2000
                DamageType = HERO
            End
        End
        """
    )
    weapon = game.weapons["EagleClawWyrmAttack"]
    assert [type(n).__name__ for n in weapon.Nuggets] == ["ClearNuggets", "DamageNugget"]
    assert isinstance(weapon.Nuggets[0], ClearNuggets)
    assert "ClearNuggets" not in weapon.fields  # routed to the group, not stored as a field


def test_object_with_behaviors_and_weaponset():
    game = load(
        """\
        Object TestUnit
            BuildCost = 600
            CommandPoints = 60
            WeaponSet
                Conditions = None
                Weapon = PRIMARY TestSword
            End
            Behavior = AutoHealBehavior ModuleTag_Heal
                HealingAmount = 5
            End
            Draw = W3DHordeModelDraw ModuleTag_Draw
            End
        End
        """
    )
    unit = game.objects["TestUnit"]
    assert isinstance(unit, Object)
    assert unit.BuildCost == 600
    assert [type(w).__name__ for w in unit.WeaponSet] == ["WeaponSet"]
    assert [type(m).__name__ for m in unit.modules] == ["AutoHealBehavior"]


def test_draw_modules_are_typed_and_grouped():
    game = load(
        """\
        Object TestUnit
            Draw = W3DHordeModelDraw ModuleTag_01
                DefaultModelConditionState
                    Model = MUOrcWar_SKN
                End
            End
            Draw = W3DScriptedModelDraw ModuleTag_02
            End
        End
        """
    )
    unit = game.objects["TestUnit"]
    assert [type(d).__name__ for d in unit.Draw] == ["W3DHordeModelDraw", "W3DScriptedModelDraw"]
    assert isinstance(unit.Draw[0], Draw)
    # draws are not mixed into the behavior modules list
    assert unit.modules == []
    # the draw module's state block is now typed into its nested group, not kept generic
    assert [b for b in unit.Draw[0].extras if isinstance(b, Block)] == []
    states = unit.Draw[0].DefaultModelConditionState
    assert [type(s).__name__ for s in states] == ["DefaultModelConditionState"]
    assert states[0].Model == ["MUOrcWar_SKN"]


def test_keyed_model_and_animation_states_are_typed():
    game = load(
        """\
        Object TestUnit
            Draw = W3DScriptedModelDraw ModuleTag_01
                ModelConditionState = MOUNTED
                    Model = GUFrmrHrs_SKN
                End
                AnimationState = MOVING ATTACKING
                    StateName = STATE_Charge
                    Animation = GUFaramir_CHRC
                        AnimationName = GUFaramir_SKL.GUFaramir_CHRC
                        AnimationMode = ONCE
                    End
                End
            End
        End
        """
    )
    draw = game.objects["TestUnit"].Draw[0]
    # the flag set in the header becomes the state's name (its key), not a dangling class
    assert draw.extras == []
    assert [s.name for s in draw.ModelConditionState] == ["MOUNTED"]
    assert draw.ModelConditionState[0].Model == ["GUFrmrHrs_SKN"]

    anim_state = draw.AnimationState[0]
    assert anim_state.name == "MOVING ATTACKING"
    assert anim_state.StateName == "STATE_Charge"
    # the animation clip nests one level deeper and is itself typed
    clip = anim_state.Animation[0]
    assert clip.name == "GUFaramir_CHRC"
    assert clip.AnimationName == "GUFaramir_SKL.GUFaramir_CHRC"
    assert clip.AnimationMode == "ONCE"


def test_model_condition_state_keeps_extra_mesh_models():
    # `Model` repeats when extra meshes are attached; every line is kept verbatim, not collapsed
    # to the last, so the primary model and its `ExtraMesh:Yes` extras all survive.
    game = load(
        """\
        Object TestUnit
            Draw = W3DModelDraw ModuleTag_01
                DefaultModelConditionState
                    Model = MUOrkArchr_SKN
                    Model = MUOrkArchr_SKB ExtraMesh:Yes
                End
            End
        End
        """
    )
    state = game.objects["TestUnit"].Draw[0].DefaultModelConditionState[0]
    assert state.Model == ["MUOrkArchr_SKN", "MUOrkArchr_SKB ExtraMesh:Yes"]


def test_geometry_fields_repeat_per_geometry_block():
    # Geometry fields repeat once per geometry block; each occurrence is kept as its own entry.
    game = load(
        """\
        Object TestUnit
            GeometryRotationAnchorOffset = X:1 Y:2 Z:3
            GeometryRotationAnchorOffset = X:4 Y:5 Z:6
            GeometryOther = GeomType:BOX IsSmall:No MajorRadius:10
            GeometryOther = GeomType:CYLINDER IsSmall:Yes MajorRadius:5
        End
        """
    )
    obj = game.objects["TestUnit"]
    assert obj.GeometryRotationAnchorOffset == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    assert obj.GeometryOther == [
        "GeomType:BOX IsSmall:No MajorRadius:10",
        "GeomType:CYLINDER IsSmall:Yes MajorRadius:5",
    ]


def test_gamedata_fields_collect_repeated_lines():
    # `StandardPublicBone` and `WeaponBonus` repeat in GameData; every line lands in the attribute.
    game = load(
        """\
        GameData
            StandardPublicBone = Bone01
            StandardPublicBone = Bone02
            WeaponBonus = GARRISONED DAMAGE 0%
            WeaponBonus = SCRIPT_ABLE DAMAGE 150%
        End
        """
    )
    data = game.gamedatas["GameData"]
    assert data.StandardPublicBone == ["Bone01", "Bone02"]
    assert data.WeaponBonus == [
        ("GARRISONED", "DAMAGE", "0%"),
        ("SCRIPT_ABLE", "DAMAGE", "150%"),
    ]


def test_fxparticlesystem_sub_blocks_are_typed():
    game = load(
        """\
        FXParticleSystem TestFX
            System
                ParticleName = EXsnowcloud02.tga
                SystemLifetime = 2500
                Lifetime = 75 75
            End
            Color = DefaultColor
                Color1 = R:213 G:205 B:252 0
            End
            EmissionVolume = BoxEmissionVolume
                IsHollow = Yes
                HalfSize = X:35 Y:70 Z:5
            End
        End
        """
    )
    fx = game.tables["particlesystems"]["TestFX"]
    assert fx.extras == []
    assert fx.System[0].ParticleName == "EXsnowcloud02.tga"
    assert fx.System[0].SystemLifetime == 2500
    assert fx.System[0].Lifetime == [75, 75]
    # variant-keyed blocks take the variant token as their name
    assert fx.Color[0].name == "DefaultColor"
    assert fx.EmissionVolume[0].name == "BoxEmissionVolume"
    assert fx.EmissionVolume[0].IsHollow is True
    assert fx.EmissionVolume[0].HalfSize == [35.0, 70.0, 5.0]


def test_fxlist_nuggets_are_typed_and_grouped():
    game = load(
        """\
        FXList FX_Test
            ParticleSystem
                Name = SomeParticleSys
                Count = 3
            End
            TintDrawable
                Color = R:255 G:255 B:255
                SustainedColorTime = 30
            End
            TintDrawable
                SustainedColorTime = 52
            End
        End
        """
    )
    fx = game.tables["fxlists"]["FX_Test"]
    assert fx.extras == []
    assert fx.ParticleSystem[0].Count == 3
    # repeated nuggets each get their own typed entry
    assert [t.SustainedColorTime for t in fx.TintDrawable] == [30, 52]
    assert fx.TintDrawable[0].Color == [255.0, 255.0, 255.0]


def test_eva_event_side_sounds_are_typed():
    game = load(
        """\
        PredefinedEvaEvent BuildingStolen
            Priority = 6
            AlwaysPlayFromHomeBase = Yes
            SideSound
                Side = Angmar
                Sound = CampThrallBuildingLost
            End
            SideSound
                Side = Mordor
                Sound = CampOrcBuildingLost
            End
        End
        """
    )
    eva = game.tables["evaevents"]["BuildingStolen"]
    assert eva.Priority == 6
    assert eva.AlwaysPlayFromHomeBase is True
    assert eva.extras == []
    assert [(s.Side, s.Sound) for s in eva.SideSound] == [
        ("Angmar", "CampThrallBuildingLost"),
        ("Mordor", "CampOrcBuildingLost"),
    ]


def test_window_transition_nests_window_and_transition_blocks():
    game = load(
        """\
        WindowTransition MainMenuFade
            Window
                WinName = MainMenu.wnd:Ruler
                Transition = SOUNDFADE
                    StartFrame = 0
                    EndFrame = 30
                    LeaveSilent = Yes
                End
            End
        End
        """
    )
    wt = game.tables["windowtransitions"]["MainMenuFade"]
    assert wt.extras == []
    window = wt.Window[0]
    assert window.WinName == "MainMenu.wnd:Ruler"
    assert window.extras == []
    # the fade is a second level of nesting, keyed by the transition type
    transition = window.Transition[0]
    assert transition.name == "SOUNDFADE"
    assert transition.EndFrame == 30
    assert transition.LeaveSilent is True


def test_army_member_definitions_are_named_and_typed():
    game = load(
        """\
        Object GondorFighterHorde
        End
        Object GondorArcherHorde
        End
        ArmyDefinition GondorArmy
            ArmyMemberDefinition GondorFighterHorde_Member
                Unit = GondorFighterHorde
                PercentageOfArmyPhase1 = 30.0
            End
            ArmyMemberDefinition GondorArcherHorde_Member
                Unit = GondorArcherHorde
                PercentageOfArmyPhase1 = 20.0
            End
        End
        """
    )
    army = game.tables["armydefinitions"]["GondorArmy"]
    assert army.extras == []
    members = army.ArmyMemberDefinition
    # the token after the keyword names each member
    assert [m.name for m in members] == [
        "GondorFighterHorde_Member",
        "GondorArcherHorde_Member",
    ]
    # Unit is a (strict) Object reference, resolving to the defined object
    assert members[0].Unit.name == "GondorFighterHorde"
    assert members[0].PercentageOfArmyPhase1 == 30.0


def test_living_world_campaign_nests_acts_and_armies():
    game = load(
        """\
        LivingWorldCampaign WotR
            Act One
                EyeTowerPoints
                    LookPoint = X:436 Y:687
                    LookPoint = X:481 Y:287
                End
                SpawnArmy
                    PlayerArmy = GondorArmy
                End
            End
        End
        """
    )
    camp = game.tables["livingworldcampaigns"]["WotR"]
    assert camp.extras == []
    act = camp.Act[0]
    assert act.name == "One"
    assert act.extras == []  # SpawnArmy and EyeTowerPoints both typed, three levels deep
    # repeated LookPoint lines collect into one list (tokens flattened, grouping not kept yet)
    assert act.EyeTowerPoints[0].LookPoint == ["X:436", "Y:687", "X:481", "Y:287"]
    assert [type(a).__name__ for a in act.SpawnArmy] == ["SpawnArmy"]


def test_living_world_act_scripted_actions_are_typed():
    game = load(
        """\
        LivingWorldCampaign WotR
            Act One
                WorldText
                    StringTag = LW:Intro
                    DelayFromActStart = 4.0
                End
                MoveArmy
                    ArmyScriptingName = WitchKing_Army
                    TargetRegionName = Rivendell
                End
                SetPlayerControlOfArmy
                    ArmyScriptingName = WitchKing_Army
                    IsControllableByOwner = Yes
                End
            End
        End
        """
    )
    act = game.tables["livingworldcampaigns"]["WotR"].Act[0]
    assert act.extras == []
    assert act.WorldText[0].StringTag == "LW:Intro"
    assert act.MoveArmy[0].TargetRegionName == "Rivendell"
    assert act.SetPlayerControlOfArmy[0].IsControllableByOwner is True


def test_object_threat_and_flammability_subblocks_are_typed():
    game = load(
        """\
        Object Foo
            ThreatBreakdown
                AIKindOf = STRUCTURE
            End
            Flammability
                Fuel = 100
                MaxBurnRate = 10
            End
        End
        """
    )
    obj = game.objects["Foo"]
    assert obj.extras == []
    assert obj.ThreatBreakdown[0].AIKindOf == "STRUCTURE"
    assert obj.Flammability[0].Fuel == 100


def test_objectcreationlist_fireweapon_nugget_is_typed():
    game = load(
        """\
        Weapon SomeWeapon
        End
        ObjectCreationList OCL_Test
            FireWeapon
                Weapon = SomeWeapon
            End
        End
        """
    )
    ocl = game.tables["objectcreationlists"]["OCL_Test"]
    assert ocl.extras == []
    assert ocl.FireWeapon[0].Weapon.name == "SomeWeapon"


def test_threat_breakdown_with_a_stray_label_still_parses():
    # `ThreatBreakdown = X` is engine-tolerated, so it parses as a ThreatBreakdown (the label
    # is flagged separately by the spurious-block-label rule).
    game = load(
        """\
        Object Foo
            ThreatBreakdown = IsengardBeserker_DetailedThreat
                AIKindOf = INFANTRY
            End
        End
        """
    )
    obj = game.objects["Foo"]
    assert obj.extras == []
    assert obj.ThreatBreakdown[0].AIKindOf == "INFANTRY"
    assert obj.ThreatBreakdown[0].name == "IsengardBeserker_DetailedThreat"


def test_horde_melee_behavior_is_keyed_by_type():
    game = load(
        """\
        Object Horde
            Behavior = HordeContain ModuleTag_Horde
                MeleeBehavior = Amoeba
                    InnerRange = 5.0
                End
            End
        End
        """
    )
    contain = game.objects["Horde"].modules[0]
    assert contain.extras == []
    assert contain.MeleeBehavior[0].name == "Amoeba"
    assert contain.MeleeBehavior[0].InnerRange == 5.0


def test_a_misspelled_module_class_is_not_swallowed_as_a_keyed_block():
    # `Behavior` is a registered base class, but a typo'd behavior must stay unrecognized
    # (an `_extras` block the lint flags) rather than resolve to the bare Behavior module.
    game = load("Object Foo\n    Behavior = PhysicsBeavior Tag\n    End\nEnd\n")
    extras = [b for b in game.objects["Foo"].extras if isinstance(b, Block)]
    assert [b.name for b in extras] == ["Behavior"]
    assert game.objects["Foo"].modules == []


def test_all_corpus_draw_types_are_registered():
    # every Draw module type observed in the corpora resolves to a Draw subclass
    corpus_draw_types = [
        "W3DScriptedModelDraw",
        "DefaultDraw",
        "W3DFloorDraw",
        "W3DHordeModelDraw",
        "W3DTreeDraw",
        "RenderObjectDraw",
        "GpuDraw",
        "W3DPropDraw",
        "W3DStreakDraw",
        "W3DTruckDraw",
        "LightningDraw",
        "W3DDefaultDraw",
        "W3DBuffDraw",
        "W3DLightDraw",
        "W3DSailModelDraw",
        "StreakDraw",
        "ButterflyDraw",
        "W3DTornadoDraw",
        "W3DQuadrupedDraw",
        "W3DLaserDraw",
        "W3DProjectileStreamDraw",
        "QuadDraw",
        "W3DDebrisDraw",
    ]
    for name in corpus_draw_types:
        cls = get_class(name)
        assert cls is not None and issubclass(cls, Draw), name


def test_newly_typed_behaviors():
    game = load(
        """\
        Object TestStructure
            Behavior = CostModifierUpgrade ModuleTag_Discount
                TriggeredBy = Upgrade_Forge
                LabelForPalantirString = GUI:UPGRADE_DISCOUNT
                UpgradeDiscount = Yes
                ApplyToTheseUpgrades = Upgrade_A Upgrade_B
                Percentage = -10%
                Percentage = -20%
            End
            Behavior = OathbreakersFadeAwayBehavior ModuleTag_Fade
                FadeOutTime = 5000
            End
            Behavior = BridgeBehavior ModuleTag_Bridge
                LateralScaffoldSpeed = 1.5
                VerticalScaffoldSpeed = 2.0
            End
            Behavior = AODHordeContain ModuleTag_Contain
                Slots = 40
                AmplitudeScale = 20
                LargeUnitTimeout = 12000
            End
            ClientBehavior = UpgradeSoundSelectorClientBehavior ModuleTag_Sound
            End
        End
        """
    )
    unit = game.objects["TestStructure"]
    mods = {type(m).__name__: m for m in unit.modules}
    assert set(mods) == {
        "CostModifierUpgrade",
        "OathbreakersFadeAwayBehavior",
        "BridgeBehavior",
        "AODHordeContain",
        "UpgradeSoundSelectorClientBehavior",
    }
    assert mods["CostModifierUpgrade"].Percentage == [pytest.approx(-0.10), pytest.approx(-0.20)]
    assert mods["CostModifierUpgrade"].UpgradeDiscount is True
    assert mods["OathbreakersFadeAwayBehavior"].FadeOutTime == 5000
    assert mods["BridgeBehavior"].VerticalScaffoldSpeed == 2.0
    assert mods["AODHordeContain"].LargeUnitTimeout == 12000


def test_behavior_reference_fields_are_raw_accessible():
    # fields integrated from the engine field list (FXList/AudioEvent/... -> raw name)
    game = load(
        """\
        Object O
            Behavior = AutoHealBehavior Tag
                HealingAmount = 50
                HealingDelay = 250
                UnitHealPulseFX = FX_HealGlow
            End
        End
        """
    )
    behavior = game.objects["O"].modules[0]
    assert behavior.HealingAmount == 50  # hand-curated Int
    assert behavior.HealingDelay == 250  # integrated UnsignedInteger -> Int
    # UnitHealPulseFX is an FXList reference; with no fxlists table it stays raw
    assert behavior.UnitHealPulseFX == "FX_HealGlow"


def test_behavior_fxlist_reference_resolves_when_table_populated():
    game = load(
        """\
        Object O
            Behavior = AutoHealBehavior Tag
                UnitHealPulseFX = FX_HealGlow
            End
        End
        """
    )
    target = object()
    game.fxlists["FX_HealGlow"] = target
    behavior = game.objects["O"].modules[0]
    assert behavior.UnitHealPulseFX is target  # same field now resolves to the definition


def test_object_core_fields_are_typed():
    game = load(
        """\
        Object GondorPorter
            EditorSorting = UNIT
            Side = Men
            RadarPriority = UNIT
            ThreatLevel = 1.0
            Geometry = BOX
            GeometryMajorRadius = 12.0
            GeometryHeight = 18.0
            GeometryIsSmall = Yes
            GeometryOffset = X:0 Y:0 Z:-10
            Shadow = SHADOW_VOLUME
            ShadowSizeX = 30
            VisionSide = 50%
            SelectPortrait = UPGondor_Porter
            VoiceSelect = OrcPorterGenericVoiceSelect
            SoundOnDamaged = BuildingLightDamageStone
            EvaEventDamagedOwner = UnitUnderAttack
        End
        """
    )
    unit = game.objects["GondorPorter"]
    assert unit.EditorSorting == [EditorSorting.UNIT]
    assert unit.Side == "Men"  # Opaque: raw token
    assert unit.RadarPriority is RadarPriority.UNIT
    assert unit.ThreatLevel == 1.0
    # Per-shape geometry is marker-grouped into typed shapes; GeometryIsSmall is
    # one of the per-shape keys (the data writes it once per geometry block).
    assert [s.type for s in unit.geometry] == [GeometryType.BOX]
    assert unit.geometry[0].GeometryMajorRadius == 12.0
    assert unit.geometry[0].GeometryHeight == 18.0
    assert unit.geometry[0].GeometryOffset == [0.0, 0.0, -10.0]
    assert unit.geometry[0].GeometryIsSmall is True
    assert unit.ShadowSizeX == 30
    assert unit.VisionSide == pytest.approx(0.50)
    # Tier A references degrade to the raw name until their tables exist
    assert unit.SelectPortrait == "UPGondor_Porter"
    assert unit.VoiceSelect == "OrcPorterGenericVoiceSelect"
    assert unit.EvaEventDamagedOwner == "UnitUnderAttack"


def test_data_block_definitions_are_typed_and_tabled():
    game = load(
        """\
        MappedImage UCCommon_BackArrow
            Texture = UCComponents.tga
            TextureWidth = 512
            TextureHeight = 256
            Coords = Left:1 Top:2 Right:30 Bottom:40
            Status = NONE
        End
        AudioEvent Snd_Click
            Volume = 80
            MinRange = 100
            MaxRange = 500
        End
        """
    )
    img = game.mappedimages["UCCommon_BackArrow"]
    assert isinstance(img, MappedImage)
    assert img.Texture == "UCComponents.tga"
    assert img.TextureWidth == 512
    assert img.Coords == {"Left": "1", "Top": "2", "Right": "30", "Bottom": "40"}
    snd = game.audioevents["Snd_Click"]
    assert isinstance(snd, AudioEvent)
    assert snd.Volume == 80
    assert snd.MaxRange == 500


def test_tier_a_reference_resolves_to_data_block_definition():
    # The Tier A `Image` references on CommandButton.ButtonImage now resolve to
    # the MappedImage definition once that block is registered (Tier D). The
    # field is a `List[Image]`, so the resolved definition arrives in a list.
    game = load(
        """\
        MappedImage BIArmory_Porter
            Texture = INGameUI.tga
        End
        CommandButton Command_Build
            Command = UNIT_BUILD
            ButtonImage = BIArmory_Porter
        End
        """
    )
    button = game.commandbuttons["Command_Build"]
    assert isinstance(button, CommandButton)
    assert button.ButtonImage == [game.mappedimages["BIArmory_Porter"]]


def test_unresolved_reference_still_degrades_to_raw_name():
    # A reference with no matching definition stays the raw token (lossless).
    game = load(
        """\
        CommandButton Command_X
            ButtonImage = DoesNotExist
        End
        """
    )
    assert game.commandbuttons["Command_X"].ButtonImage == ["DoesNotExist"]


def test_unknown_behavior_is_retained_as_generic():
    game = load(
        """\
        Object TestUnit
            Behavior = SomeUnknownModExclusiveBehavior ModuleTag_X
                Whatever = 1
            End
        End
        """
    )
    unit = game.objects["TestUnit"]
    assert unit.modules == []  # not a known module type
    assert [b.label for b in unit.extras if isinstance(b, Block)] == [
        "SomeUnknownModExclusiveBehavior ModuleTag_X"
    ]


def test_childobject_captures_parent_name():
    game = load(
        """\
        Object BaseUnit
            BuildCost = 100
        End
        ChildObject DerivedUnit BaseUnit
            BuildCost = 150
        End
        """
    )
    child = game.objects["DerivedUnit"]
    assert isinstance(child, ChildObject)
    assert child.name == "DerivedUnit"
    assert child.parent_name == "BaseUnit"
    assert child.BuildCost == 150


def test_childobject_inherits_unset_field_from_parent():
    game = load(
        """\
        Object BaseUnit
            BuildCost = 100
            CommandPoints = 5
        End
        ChildObject DerivedUnit BaseUnit
            CommandPoints = 9
        End
        """
    )
    child = game.objects["DerivedUnit"]
    assert child.CommandPoints == 9  # own value wins
    assert child.BuildCost == 100  # inherited from parent
    assert child.parent.name == "BaseUnit"


def test_childobject_inheritance_chains():
    game = load(
        """\
        Object Grandparent
            BuildCost = 50
        End
        ChildObject Parent Grandparent
            CommandPoints = 1
        End
        ChildObject Kid Parent
        End
        """
    )
    kid = game.objects["Kid"]
    assert kid.CommandPoints == 1  # from Parent
    assert kid.BuildCost == 50  # from Grandparent, two hops up


def test_objectreskin_is_a_real_object_inheriting_from_its_base():
    game = load(
        """\
        Object StructureDwarvenAxe
            BuildCost = 7
        End
        ObjectReskin StructureUpgradedDwarvenAxe StructureDwarvenAxe
        End
        """
    )
    reskin = game.objects["StructureUpgradedDwarvenAxe"]
    assert isinstance(reskin, ObjectReskin)
    assert reskin.name == "StructureUpgradedDwarvenAxe"
    assert reskin.parent_name == "StructureDwarvenAxe"
    # a reskin inherits its base's fields, and resolves where an Object is named
    assert reskin.BuildCost == 7
    assert Object.convert(game, "StructureUpgradedDwarvenAxe") is reskin


def test_commandset_buttons_and_helpers():
    game = load(
        """\
        CommandButton Command_A
        End
        CommandButton Command_B
        End
        CommandButton Command_C
        End
        CommandSet TestSet
            InitialVisible = 2
            1 = Command_A
            2 = Command_B
            4 = Command_C
        End
        """
    )
    cs = game.commandsets["TestSet"]
    buttons = cs.CommandButtons
    assert set(buttons) == {1, 2, 4}
    assert buttons[1] is game.commandbuttons["Command_A"]
    assert cs.as_list() == [buttons[1], buttons[2], None, buttons[4]]
    assert set(cs.initial_visible()) == {1, 2}
    assert cs.get_button(2) is buttons[2]
    with pytest.raises(KeyError):
        cs.get_button(99)


def test_emotion_nugget_uses_reference_enums():
    game = load(
        """\
        EmotionNugget Taunt_Base
            Type = TAUNT
            IgnoreIfUnitBusy = Yes
            AIState = FACE_OBJECT
            ModelConditions = EMOTION_TAUNTING
            Duration = 5000
            StartFXList = FX_EmotionTaunt
        End
        """
    )
    nugget = game.emotions["Taunt_Base"]
    assert isinstance(nugget, EmotionNugget)
    assert nugget.Type is EmotionTypes.TAUNT
    assert nugget.AIState is EmotionNuggetAIState.FACE_OBJECT
    assert nugget.ModelConditions == [ModelCondition.EMOTION_TAUNTING]
    assert nugget.Duration == 5000
    assert nugget.IgnoreIfUnitBusy is True
    assert nugget.StartFXList == "FX_EmotionTaunt"  # FXList cross-ref kept as raw name


def test_commandbutton_enum_fields():
    game = load(
        """\
        CommandButton Command_ToggleWeapon
            Command = TOGGLE_WEAPONSET
            ButtonBorderType = ACTION
            WeaponSlot = SECONDARY
            FlagsUsedForToggle = WEAPONSET_TOGGLE_1
        End
        """
    )
    button = game.commandbuttons["Command_ToggleWeapon"]
    assert button.ButtonBorderType is ButtonBorderTypes.ACTION
    assert button.WeaponSlot is SlotTypes.SECONDARY
    assert button.FlagsUsedForToggle == [ModelCondition.WEAPONSET_TOGGLE_1]


def test_weapon_attack_speed():
    # attack cadence for the real-time duel: FiringDuration + DelayBetweenShots.
    game = load(
        """\
        Weapon SlowAxe
            FiringDuration = 1200
            DelayBetweenShots = 2400
        End
        """
    )
    weapon = game.weapons["SlowAxe"]
    assert weapon.AttackSpeed == 3600


def test_weapon_delay_between_shots_range():
    # DelayBetweenShots may be a single time or an explicit Min/Max range; the
    # cadence uses the average delay (1000) plus FiringDuration (200) = 1200.
    game = load(
        """\
        Weapon Volley
            FiringDuration = 200
            DelayBetweenShots = Min:500 Max:1500
        End
        """
    )
    weapon = game.weapons["Volley"]
    delay = weapon.DelayBetweenShots
    assert (delay.min, delay.max, delay.average) == (500, 1500, 1000)
    assert weapon.AttackSpeed == 1200


def test_weapon_delay_between_shots_two_numbers():
    # `10 500` is a bare-number range (randomise between the two), like Min/Max.
    game = load(
        """\
        Weapon Spread
            DelayBetweenShots = 10    500
        End
        """
    )
    delay = game.weapons["Spread"].DelayBetweenShots
    assert (delay.min, delay.max) == (10, 500)


def test_weapon_clip_reload_time_range():
    # ClipReloadTime is a duration range like DelayBetweenShots: a Min/Max pair converts
    # cleanly (not a conversion error), even when the two bounds are equal.
    game = load(
        """\
        Weapon Bow
            ClipReloadTime = Min: 1300 Max: 1300
        End
        """
    )
    assert not [d for d in game.validate() if d.code == "conversion-error"]
    reload_time = game.weapons["Bow"].ClipReloadTime
    assert (reload_time.min, reload_time.max) == (1300, 1300)


def test_castle_unpack_for_faction_groups_by_side():
    # CastleToUnpackForFaction repeats; each side accumulates its castle objects.
    game = load(
        """\
        Object Fortress_Dwarven
        End
        Object Fortress_Elven
        End
        Object Keep
            Behavior = CastleBehavior ModuleTag_01
                CastleToUnpackForFaction = Dwarves Fortress_Dwarven
                CastleToUnpackForFaction = Elves Fortress_Elven
            End
        End
        """
    )
    castle = game.objects["Keep"].modules[0]
    mapping = castle.CastleToUnpackForFaction
    assert set(mapping) == {"Dwarves", "Elves"}
    # Values are kept as the raw castle names (GroupedByKey[FactionSide, String]).
    assert mapping["Dwarves"] == ["Fortress_Dwarven"]
    assert mapping["Elves"] == ["Fortress_Elven"]


def test_slow_death_ocl_groups_by_phase():
    # SlowDeath OCL is `<phase> <ocl>`, keyed by SlowDeathPhase, repeating.
    game = load(
        """\
        ObjectCreationList OCL_Rubble
        End
        ObjectCreationList OCL_Spawn
        End
        Object Tower
            Behavior = SlowDeathBehavior ModuleTag_01
                OCL = INITIAL OCL_Rubble
                OCL = FINAL OCL_Spawn
            End
        End
        """
    )
    death = game.objects["Tower"].modules[0]
    phases = {phase.name: [o.name for o in ocls] for phase, ocls in death.OCL.items()}
    assert phases == {"INITIAL": ["OCL_Rubble"], "FINAL": ["OCL_Spawn"]}


def test_weapon_linear_target_position_and_time():
    # LinearTarget repeats, one waypoint per line, so it reads as a list; each is
    # a colon-keyed X/Y offset plus T, a time in frames, and the spacing around
    # the colons varies in the data and must not matter.
    game = load(
        """\
        Weapon Leading
            LinearTarget = X: 12.5   Y:-46.74    T:5
            LinearTarget = X:-30      T:10
        End
        """
    )
    targets = game.weapons["Leading"].LinearTarget
    assert [t.Position for t in targets] == [[12.5, -46.74, 0.0], [-30.0, 0.0, 0.0]]
    assert [t.T for t in targets] == [5, 10]


def test_object_body_health_is_accessible():
    # health for the duel example: MaxHealth lives on the body module.
    game = load(
        """\
        Object Tank
            Body = ActiveBody ModuleTag_Body
                MaxHealth = 300
                InitialHealth = 300
            End
        End
        """
    )
    unit = game.objects["Tank"]
    body = next(m for m in unit.modules if isinstance(m, Body))
    assert type(body).__name__ == "ActiveBody"
    assert body.MaxHealth == 300


def test_weapon_resolution_and_armor_damage_scalar():
    # The combat-math path: attacker's weapon nugget vs defender's armor scalar.
    game = load(
        """\
        Weapon OrcAxe
            DamageNugget
                Damage = 12
                DamageType = SLASH
            End
        End
        Armor LightArmor
            Armor = DEFAULT 100%
            Armor = SLASH 50%
        End
        Object Attacker
            WeaponSet
                Weapon = PRIMARY OrcAxe
            End
        End
        Object Defender
            ArmorSet
                Armor = LightArmor
            End
        End
        """
    )
    attacker = game.objects["Attacker"]
    defender = game.objects["Defender"]

    slot, weapon = attacker.WeaponSet[0].Weapon[0]
    assert slot is SlotTypes.PRIMARY
    assert isinstance(weapon, Weapon)
    assert weapon.name == "OrcAxe"

    armor = defender.ArmorSet[0].Armor
    assert armor.get_damage_scalar(DamageType.SLASH) == 0.5
    assert armor.get_damage_scalar(DamageType.PIERCE) == 1.0  # falls back to DEFAULT

    nugget = weapon.Nuggets[0]
    assert nugget.Damage * armor.get_damage_scalar(nugget.DamageType) == 6.0


def test_cross_reference_between_objects():
    game = load(
        """\
        Upgrade Upgrade_Base
            BuildCost = 100
        End
        CommandButton Command_Test
            Upgrade = Upgrade_Base
        End
        """
    )
    button = game.commandbuttons["Command_Test"]
    assert button.Upgrade is game.upgrades["Upgrade_Base"]


def test_attack_priority_definition_loads_with_default_and_targets():
    game = load(
        """\
        Object GondorFighter
        End
        AttackPriority AttackPriority_Test
            Default = 35
            Target = GondorFighter 10
            Target = MordorOrc 5
        End
        """
    )
    priority = game.attackpriorities["AttackPriority_Test"]
    assert priority.Default == 35
    # Each Target weights an object (resolved when loaded, else its raw name) by an integer.
    assert priority.Target[0].Target is game.objects["GondorFighter"]
    assert priority.Target[0].Value == 10
    assert priority.Target[1].Target == "MordorOrc"  # not loaded -> raw name
    assert priority.Target[1].Value == 5


def test_retyped_behavior_fields_convert_to_their_references():
    # Fields recently lifted off the String typehint now resolve to enums/records/references.
    game = load(
        """\
        ObjectCreationList OCL_SpawnDeadRider
        End
        CommandSet UpgradedSet
        End
        Object Hero
            Behavior = AISpecialPowerUpdate ModuleTag_AI
                SpecialPowerAIType = AI_SPECIAL_POWER_CHARGE
            End
            Behavior = RespawnUpdate ModuleTag_Respawn
                RespawnRules = AutoSpawn:No Cost:1500 Time:60000 Health:100%
            End
            Behavior = DetachableRiderUpdate ModuleTag_Rider
                DeathEntry = AnimState:DEATH_2 AnimTime:3000 RiderOCL:OCL_SpawnDeadRider
            End
            Behavior = CommandSetUpgrade ModuleTag_Set
                CommandSet = UpgradedSet
            End
        End
        """
    )
    mods = {type(m).__name__: m for m in game.objects["Hero"].modules}
    assert mods["AISpecialPowerUpdate"].SpecialPowerAIType.name == "AI_SPECIAL_POWER_CHARGE"
    respawn = mods["RespawnUpdate"].RespawnRules
    assert (respawn.AutoSpawn, respawn.Cost, respawn.Time, respawn.Health) == (
        False,
        1500,
        60000,
        1.0,
    )
    death = mods["DetachableRiderUpdate"].DeathEntry
    assert death.AnimState.name == "DEATH_2"
    assert death.RiderOCL is game.objectcreationlists["OCL_SpawnDeadRider"]
    assert mods["CommandSetUpgrade"].CommandSet is game.commandsets["UpgradedSet"]


def test_part_the_heavens_update_parses_color_and_nested_fcurves():
    game = load(
        """\
        MappedImage SCCommandBar
        End
        Object Test
            Behavior = PartTheHeavensUpdate ModuleTag_02
                Texture = SCCommandBar
                Color = R:255 G:255 B:255
                Radius = FCurve
                    Key = T:0 V:0 O:0
                    Key = T:20 V:100
                End
                Angle = FCurve
                    InPadding = HOLD
                    OutPadding = CYCLE
                    Key = T:0 V:0
                    Key = T:100 V:360 I:0 O:0
                End
            End
        End
        """
    )
    heavens = game.objects["Test"].modules[0]
    assert heavens.Texture is game.mappedimages["SCCommandBar"]
    assert heavens.Color == [255.0, 255.0, 255.0, 255.0]  # alpha defaults opaque
    # Each FCurve field routes to its own group by field name, even though all share the
    # FCurve block type.
    [radius] = heavens.Radius
    assert [(k.T, k.V) for k in radius.Key] == [(0, 0), (20, 100)]
    [angle] = heavens.Angle
    assert (angle.InPadding, angle.OutPadding) == ("HOLD", "CYCLE")
    assert angle.Key[1].V == 360
    assert heavens.Opacity == []  # absent field is an empty group


def test_locomotor_fields_are_typed():
    game = load(
        """\
        Locomotor HorseLoco
            Surfaces = GROUND RUBBLE
            Appearance = FOUR_WHEELS
            ZAxisBehavior = NO_Z_MOTIVE_FORCE
            Speed = 80
            Acceleration = 25.5
            TurnTime = 600
            StickToGround = Yes
            CanMoveBackwards = No
            FrontWheelTurnAngle = 30
        End
        """
    )
    loco = game.locomotors["HorseLoco"]
    assert isinstance(loco, Locomotor)
    # Numeric fields convert; flag/enum fields stay raw strings.
    assert loco.Speed == 80 and loco.Acceleration == 25.5
    assert loco.TurnTime == 600 and loco.FrontWheelTurnAngle == 30
    assert loco.StickToGround is True and loco.CanMoveBackwards is False
    assert loco.Surfaces == "GROUND RUBBLE"
    assert loco.Appearance == "FOUR_WHEELS"


def test_audioevent_fields_are_typed():
    game = load(
        """\
        AudioEvent Snd_Sword
            Sounds = WIImpac_sword01 WIImpac_sword02
            Type = world player
            Control = fade_on_kill RANDOMSTART
            SubmixSlider = SoundFX
            Delay = 200 600
            VolumeShift = -5 5
            ReverbEffectLevel = 100
            VolumeSliderMultiplier = Slider:Voice Multiplier:70
            VolumeSliderMultiplier = Slider:SoundFX Multiplier:50
        End
        """
    )
    snd = game.audioevents["Snd_Sword"]
    assert isinstance(snd, AudioEvent)
    # The wave-file list splits into its filenames; the delay/shift ranges stay raw.
    assert snd.Sounds == ["WIImpac_sword01", "WIImpac_sword02"]
    assert snd.Delay == "200 600" and snd.VolumeShift == "-5 5"
    assert snd.ReverbEffectLevel == 100
    # Type/Control are bitflag sets (FlagList of the audio enums); SubmixSlider is a single
    # enum. Lower/mixed-case tokens match the members case-insensitively without warning.
    assert [m.name for m in snd.Type] == ["WORLD", "PLAYER"]
    assert [m.name for m in snd.Control] == ["FADE_ON_KILL", "RANDOMSTART"]
    assert snd.SubmixSlider.name == "SOUNDFX"
    # VolumeSliderMultiplier repeats (one per mixer slider): each colon-keyed line is its own
    # typed record, not a clobbered last-wins scalar.
    mults = snd.VolumeSliderMultiplier
    assert [(m.Slider, m.Multiplier) for m in mults] == [("Voice", 70), ("SoundFX", 50)]


def test_audiosettings_fields_are_typed():
    game = load(
        """\
        AudioSettings
            AudioRoot = Data/Audio
            UseDigital = Yes
            OutputRate = 44100
            DefaultMusicVolume = 70%
            GlobalCaveReverbMultiplier = 35%
            AutomaticSubtitleTextColor = R:255 G:204 B:0 A:255
        End
        """
    )
    settings = game.audiosettings["AudioSettings"]
    assert isinstance(settings, AudioSettings)
    assert settings.AudioRoot == "Data/Audio"
    assert settings.UseDigital is True
    assert settings.OutputRate == 44100
    # percentages convert to fractions; colors to RGBA lists
    assert settings.DefaultMusicVolume == 0.7
    assert settings.GlobalCaveReverbMultiplier == 0.35
    assert settings.AutomaticSubtitleTextColor == [255.0, 204.0, 0.0, 255.0]


def test_miscaudio_fields_resolve_to_sounds():
    game = load(
        """\
        AudioEvent MoneyDeposited
            Volume = 80
        End
        MiscAudio
            MoneyDepositSound = MoneyDeposited
            CrateHeal = NoSound
        End
        """
    )
    misc = game.miscaudios["MiscAudio"]
    assert isinstance(misc, MiscAudio)
    # a defined event resolves to the AudioEvent; an unknown name passes through raw
    assert misc.MoneyDepositSound is game.audioevents["MoneyDeposited"]
    assert misc.CrateHeal == "NoSound"


def test_ingameui_position_and_color_fields_are_typed():
    game = load(
        """\
        InGameUI
            MessagePosition = X:-44 Y:10
            MessageColor1 = R:255 G:255 B:255
            MessagePointSize = 10
            MilitaryCaptionCentered = Yes
        End
        """
    )
    ui = game.ingameuis["InGameUI"]
    assert isinstance(ui, InGameUI)
    assert ui.MessagePosition == [-44.0, 10.0, 0.0]  # Z defaults to 0
    assert ui.MessageColor1 == [255.0, 255.0, 255.0, 255.0]  # alpha defaults opaque
    assert ui.MessagePointSize == 10
    assert ui.MilitaryCaptionCentered is True


def test_livingworldmapinfo_fields_are_typed():
    game = load(
        """\
        LivingWorldMapInfo
            MapObject = LivingMap
            NumWorldTiles = 20
            Center = X:226 Y:844
            ArmyLineColorAttacking = R:255 G:0 B:0
            DefaultArmyMoveSpeed = 20.0
        End
        """
    )
    info = game.livingworldmapinfos["LivingWorldMapInfo"]
    assert isinstance(info, LivingWorldMapInfo)
    assert info.MapObject == "LivingMap"
    assert info.NumWorldTiles == 20
    assert info.Center == [226.0, 844.0, 0.0]
    assert info.ArmyLineColorAttacking == [255.0, 0.0, 0.0, 255.0]
    assert info.DefaultArmyMoveSpeed == 20.0


def test_object_world_map_prop_fields_are_typed():
    game = load(
        """\
        Object TreasureChest
            Scale = 1.5
            Clickable = Yes
            OrientAngle = 25
            FadeTypeForSelection = INOUT
            DisplayColor = R:100 G:100 B:100
            LiveCameraOffset = X:-112 Y:81 Z:57
            CrushKnockback = 40
            BuildVariations = RohanEntFir RohanEntBirch
        End
        """
    )
    obj = game.objects["TreasureChest"]
    assert isinstance(obj, Object)
    assert obj.Scale == 1.5
    assert obj.Clickable is True
    assert obj.OrientAngle == 25
    assert obj.FadeTypeForSelection == "INOUT"
    assert obj.DisplayColor == [100.0, 100.0, 100.0, 255.0]
    assert obj.LiveCameraOffset == [-112.0, 81.0, 57.0]
    assert obj.CrushKnockback == 40
    # a space-separated list of build-variation object names
    assert obj.BuildVariations == ["RohanEntFir", "RohanEntBirch"]
