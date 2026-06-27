"""Unit tests for the shared sage_utils helpers (source loading + views)."""

from pathlib import Path

import pytest
from pyBIG import Archive

import sage_ini.model.definitions  # noqa: F401  (register classes)
from sage_ini.model.game import Game
from sage_ini.model.state import UnitState, has_kindof
from sage_ini.parser.blockparser import parse
from sage_ini.parser.io import ASSET_SUFFIXES, MAP_SUFFIXES
from sage_ini.suggest import closest_names
from sage_utils.sources import (
    LOAD_SUFFIXES,
    big_member_basenames,
    load_saved_sources,
    load_sources,
    loadable_files,
    merge_shadowed,
    parse_str,
    save_sources,
)
from sage_utils.views import (
    FilterSignature,
    build_cost_view,
    builder_index,
    builders_of,
    clean_text,
    clip_reload_time,
    command_button_images,
    command_buttons_view,
    description,
    display_name,
    display_name_index,
    effective_health,
    effective_health_against,
    filter_signature,
    modifier_view,
    mounted_template,
    object_button_image,
    playable_factions,
    portrait_mapped_images,
    resource_production_view,
    select_portrait_image,
    special_power_view,
    upgrade_label,
    upgrade_toggle_labels,
    weapon_attack_interval,
    weapon_damage_per_shot,
    weapon_dps,
    weapon_top_nugget,
)

# Peripheral package (not the sage_ini/sage_lint engine): full suite only.
pytestmark = pytest.mark.full


def test_parse_str_reads_label_value_end_blocks():
    text = "\n".join(
        [
            "// a comment",
            "OBJECT:Fighter",
            '"Orc Warrior"',
            "END",
            "",
            "CONTROLBAR:Build",
            '"Build"',
            "END",
        ]
    )

    assert parse_str(text) == {"OBJECT:Fighter": "Orc Warrior", "CONTROLBAR:Build": "Build"}


def test_parse_str_joins_multiline_values():
    text = 'LABEL\n"first "\n"second"\nEND\n'

    assert parse_str(text) == {"LABEL": "first second"}


def test_loadable_files_filters_by_suffix(tmp_path: Path):
    (tmp_path / "weapon.ini").write_bytes(b"Weapon Sword\nEnd\n")
    (tmp_path / "strings.str").write_bytes(b'L\n"v"\nEND\n')
    (tmp_path / "notes.txt").write_bytes(b"ignored")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "more.inc").write_bytes(b"#define DMG 10\n")

    keys = {key for key, _path in loadable_files(tmp_path)}

    assert keys == {"weapon.ini", "strings.str", "sub/more.inc"}


def test_merge_shadowed_skips_files_claimed_by_the_mod(tmp_path: Path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "weapon.ini").write_bytes(b"Weapon Base\nEnd\n")
    (base / "extra.ini").write_bytes(b"Object FromBase\nEnd\n")

    merged = merge_shadowed(
        [("folder", str(base))], tmp_path / "work", shadow=frozenset({"weapon.ini"})
    )

    keys = {key for key, _path in loadable_files(merged)}
    # weapon.ini is shadowed by the mod, so it is not copied; extra.ini survives.
    assert keys == {"extra.ini"}


def test_merge_shadowed_highest_priority_source_wins(tmp_path: Path):
    high = tmp_path / "high"
    low = tmp_path / "low"
    high.mkdir()
    low.mkdir()
    (high / "shared.ini").write_bytes(b"Object High\nEnd\n")
    (low / "shared.ini").write_bytes(b"Object Low\nEnd\n")
    (low / "only_low.ini").write_bytes(b"Object OnlyLow\nEnd\n")

    merged = merge_shadowed([("folder", str(high)), ("folder", str(low))], tmp_path / "work")

    assert (merged / "shared.ini").read_bytes() == b"Object High\nEnd\n"
    assert (merged / "only_low.ini").exists()


def test_merge_shadowed_widened_suffixes_include_maps(tmp_path: Path):
    # The linter widens the merge set to `.map`/`.bse` so a base-game layout reaches the index
    # and can be parsed; the default set (ini/str) still leaves maps out.
    base = tmp_path / "base"
    (base / "maps" / "town").mkdir(parents=True)
    (base / "maps" / "town" / "town.map").write_bytes(b"x")
    (base / "rules.ini").write_bytes(b"Object Foo\nEnd\n")

    default = {key for key, _ in loadable_files(base)}
    assert default == {"rules.ini"}  # maps excluded by default

    widened = LOAD_SUFFIXES | MAP_SUFFIXES
    merged = merge_shadowed([("folder", str(base))], tmp_path / "work", suffixes=widened)
    keys = {key for key, _ in loadable_files(merged, widened)}
    assert keys == {"rules.ini", "maps/town/town.map"}  # the map is merged in too


def _make_big(directory: Path, dest: Path) -> Path:
    Archive.from_directory(str(directory)).save(str(dest))
    return dest


def test_big_member_basenames_lists_names_without_extracting(tmp_path: Path):
    src = tmp_path / "src"
    (src / "art").mkdir(parents=True)
    (src / "maps").mkdir()
    (src / "art" / "HeroUI_001.dds").write_bytes(b"x")
    (src / "art" / "model.w3d").write_bytes(b"x")
    (src / "maps" / "town.map").write_bytes(b"x")
    (src / "rules.ini").write_bytes(b"Object Foo\nEnd\n")
    big = _make_big(src, tmp_path / "pack.big")

    # texture/model names are indexed (lower-cased basenames), ini/maps are not asset kinds
    assert big_member_basenames(big, ASSET_SUFFIXES) == {"heroui_001.dds", "model.w3d"}
    # the same primitive lists maps when asked
    assert big_member_basenames(big, MAP_SUFFIXES) == {"town.map"}


def test_load_sources_parses_objects_and_strings(tmp_path: Path):
    (tmp_path / "units.ini").write_bytes(b"Object Fighter\nEnd\n")
    (tmp_path / "lang.str").write_bytes(b'OBJECT:Fighter\n"Soldier"\nEND\n')

    game, names = load_sources([("folder", str(tmp_path))])

    assert "Fighter" in names
    assert game.strings["OBJECT:Fighter"] == "Soldier"


def test_save_and_load_sources_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    sources = [("folder", r"C:\data"), ("big", r"C:\mod.big")]

    save_sources(sources, app="sage_test")

    assert load_saved_sources(app="sage_test") == sources
    assert load_saved_sources(app="other_app") == []


VIEWS_FIXTURE = """
Object PaidUnit
  BuildCost = 300
  BuildTime = 30
  BountyValue = 50
  KindOf = INFANTRY SELECTABLE
End
Object FreeUnit
  BuildCost = 300
  BuildTime = 30
  KindOf = INFANTRY BUILD_FOR_FREE
End
ChildObject FreeChild FreeUnit
End
Object NoCostFreeUnit
  KindOf = BUILD_FOR_FREE
End
"""


def _views_game() -> Game:
    game = Game()
    result = parse(VIEWS_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


def test_has_kindof_detects_flag_and_inherits_from_parent():
    game = _views_game()
    objects = game.objects
    assert has_kindof(objects["FreeUnit"], "BUILD_FOR_FREE") is True
    assert has_kindof(objects["PaidUnit"], "BUILD_FOR_FREE") is False
    # A ChildObject inherits its template's kinds via the parent chain.
    assert has_kindof(objects["FreeChild"], "BUILD_FOR_FREE") is True


def test_build_for_free_forces_zero_cost():
    objects = _views_game().objects
    assert build_cost_view(objects["PaidUnit"])["BuildCost"] == 300
    assert build_cost_view(objects["FreeUnit"])["BuildCost"] == 0
    assert build_cost_view(objects["FreeChild"])["BuildCost"] == 0
    # Build time is untouched; only the cost is forced to zero.
    assert build_cost_view(objects["FreeUnit"])["BuildTime"] == 30
    # A free unit that declares no cost at all still reads 0, not None.
    assert build_cost_view(objects["NoCostFreeUnit"])["BuildCost"] == 0


PRODUCTION_FIXTURE = """
Object TerrainProducer
  Behavior = TerrainResourceBehavior ModuleTag_Money
    MaxIncome = 40
    IncomeInterval = 12000
  End
End
Object DepositProducer
  Behavior = AutoDepositUpdate ModuleTag_Deposit
    DepositAmount = 25
    DepositTiming = 6000
  End
End
Object PlainUnit
End
"""


def _production_game() -> Game:
    game = Game()
    result = parse(PRODUCTION_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


def test_resource_production_view_reads_both_modules():
    objects = _production_game().objects
    terrain = resource_production_view(objects["TerrainProducer"])
    assert terrain["MaxIncome"] == 40
    assert terrain["IncomeInterval"] == 12  # ms -> seconds
    assert terrain["DepositAmount"] is None and terrain["DepositTiming"] is None

    deposit = resource_production_view(objects["DepositProducer"])
    assert deposit["DepositAmount"] == 25
    assert deposit["DepositTiming"] == 6  # ms -> seconds
    assert deposit["MaxIncome"] is None and deposit["IncomeInterval"] is None

    # A non-producer reads every field as None (the UI shows no card).
    plain = resource_production_view(objects["PlainUnit"])
    assert plain == {
        "MaxIncome": None,
        "IncomeInterval": None,
        "DepositAmount": None,
        "DepositTiming": None,
    }


def test_build_cost_view_reads_bounty_value():
    objects = _views_game().objects
    assert build_cost_view(objects["PaidUnit"])["BountyValue"] == 50
    # An object that declares no bounty degrades to None (the UI hides the row).
    assert build_cost_view(objects["FreeUnit"])["BountyValue"] is None


COMMANDS_FIXTURE = """
Object SomeHorde
End
Upgrade Upgrade_Axe
  BuildCost = 500
  BuildTime = 20
End
SpecialPower SpecialThing
End
CommandButton Command_BuildHorde
  Command = UNIT_BUILD
  Object = SomeHorde
End
CommandButton Command_Axe
  Command = OBJECT_UPGRADE
  Upgrade = Upgrade_Axe
End
CommandButton Command_Power
  Command = SPECIAL_POWER
  SpecialPower = SpecialThing
End
CommandButton Command_Spell
  Command = SPELL_BOOK
  SpecialPower = SpecialThing
End
CommandButton Command_Fire
  Command = FIRE_WEAPON
  WeaponSlot = SECONDARY
End
CommandButton Command_Toggle
  Command = TOGGLE_WEAPONSET
  FlagsUsedForToggle = WEAPONSET_TOGGLE_1
End
CommandSet TestSet
  1 = Command_BuildHorde
  2 = Command_Axe
  3 = Command_Power
  4 = Command_Fire
  5 = Command_Toggle
  6 = Command_Missing
  7 = Command_Spell
End
"""


def _commands_game() -> Game:
    game = Game()
    result = parse(COMMANDS_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


def test_command_buttons_view_keys_each_action():
    game = _commands_game()
    command_set = game.commandsets["TestSet"]
    by_name = {b["name"]: b for b in command_buttons_view(game, command_set)}

    # In slot order; a slot whose button isn't loaded still appears (command None).
    assert [b["name"] for b in command_buttons_view(game, command_set)] == [
        "Command_BuildHorde",
        "Command_Axe",
        "Command_Power",
        "Command_Fire",
        "Command_Toggle",
        "Command_Missing",
        "Command_Spell",
    ]

    assert by_name["Command_BuildHorde"]["command"] == "UNIT_BUILD"
    assert by_name["Command_BuildHorde"]["object"] == "SomeHorde"

    assert by_name["Command_Axe"]["command"] == "OBJECT_UPGRADE"
    assert by_name["Command_Axe"]["upgrade"] == {
        "name": "Upgrade_Axe",
        "cost": 500,
        "time": 20,
    }

    assert by_name["Command_Power"]["special_power"] == "SpecialThing"
    # A spellbook's SPELL_BOOK button is also a special-power button (so it's clickable).
    assert by_name["Command_Spell"]["command"] == "SPELL_BOOK"
    assert by_name["Command_Spell"]["special_power"] == "SpecialThing"
    assert by_name["Command_Fire"]["weapon_slot"] == "SECONDARY"
    assert by_name["Command_Toggle"]["toggle_flags"] == ["WEAPONSET_TOGGLE_1"]

    # An unresolved button degrades to its raw name with no action.
    assert by_name["Command_Missing"]["command"] is None
    assert by_name["Command_Missing"]["text"] == "Command_Missing"


IMAGE_COMMANDS_FIXTURE = """
Object SomeHorde
End
MappedImage Icon_Build
  Texture = INGameUI.tga
  Coords = Left:0 Top:0 Right:60 Bottom:60
End
CommandButton Command_Build
  Command = UNIT_BUILD
  Object = SomeHorde
  ButtonImage = Icon_Build
End
CommandButton Command_NoIcon
  Command = OBJECT_UPGRADE
End
CommandButton Command_UnloadedIcon
  Command = SPECIAL_POWER
  ButtonImage = Unloaded_Icon
End
CommandSet IconSet
  1 = Command_Build
  2 = Command_NoIcon
  3 = Command_Missing
  4 = Command_UnloadedIcon
End
"""


def test_command_button_images_pairs_buttons_with_mapped_images():
    game = Game()
    result = parse(IMAGE_COMMANDS_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    entries = command_button_images(game, game.commandsets["IconSet"])

    # In slot order, every slot present (incl. the button with no icon and the
    # unloaded one), paired with its resolved MappedImage(s) — a list, since the
    # button's ButtonImage may name several layered images.
    assert [e["name"] for e in entries] == [
        "Command_Build",
        "Command_NoIcon",
        "Command_Missing",
        "Command_UnloadedIcon",
    ]
    assert entries[0]["image"] == [game.mappedimages["Icon_Build"]]
    assert entries[1]["image"] == []  # button has no ButtonImage
    assert entries[2]["image"] == []  # slot's button isn't loaded

    # `image_names` carries the icon's real name whether or not the MappedImage loaded:
    # the resolved button gets its definition's name, the button with an unloaded
    # ButtonImage keeps the raw token (so it isn't mistaken for the command button),
    # and a button with no ButtonImage at all has none.
    assert entries[0]["image_names"] == ["Icon_Build"]
    assert entries[1]["image_names"] == []
    assert entries[3]["image"] == []  # MappedImage definition wasn't loaded
    assert entries[3]["image_names"] == ["Unloaded_Icon"]


PORTRAIT_FIXTURE = """
MappedImage UPGondor_Porter
  Texture = INGameUI.tga
  Coords = Left:0 Top:0 Right:64 Bottom:64
End
MappedImage BIGondor_Porter
  Texture = INGameUI.tga
  Coords = Left:0 Top:0 Right:60 Bottom:60
End
Object PortraitUnit
  SelectPortrait = UPGondor_Porter
  ButtonImage = BIGondor_Porter
End
Object NoPortraitUnit
End
"""


def test_object_portrait_and_button_images_resolve():
    game = Game()
    result = parse(PORTRAIT_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    objects = game.objects
    images = game.mappedimages

    # SelectPortrait / ButtonImage resolve to their MappedImages as a list
    # (croppable like a command-button icon, which may carry several)...
    assert select_portrait_image(objects["PortraitUnit"]) == [images["UPGondor_Porter"]]
    assert object_button_image(objects["PortraitUnit"]) == [images["BIGondor_Porter"]]
    # ...and an object without either carries an empty list.
    assert select_portrait_image(objects["NoPortraitUnit"]) == []
    assert object_button_image(objects["NoPortraitUnit"]) == []


HORDE_PORTRAIT_FIXTURE = """
MappedImage UPShellPortrait
  Texture = INGameUI.tga
  Coords = Left:0 Top:0 Right:64 Bottom:64
End
MappedImage UPMemberPortrait
  Texture = INGameUI.tga
  Coords = Left:0 Top:0 Right:64 Bottom:64
End
Object ShellPortraitMember
End
Object ShellPortraitHorde
  SelectPortrait = UPShellPortrait
  Behavior = HordeContain ModuleTag_Horde
    InitialPayload = ShellPortraitMember 4
  End
End
Object MemberPortraitMember
  SelectPortrait = UPMemberPortrait
End
Object MemberPortraitHorde
  Behavior = HordeContain ModuleTag_Horde
    InitialPayload = MemberPortraitMember 4
  End
End
"""


def test_horde_portrait_falls_to_shell_or_member():
    game = Game()
    result = parse(HORDE_PORTRAIT_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    objects, images = game.objects, game.mappedimages
    # A horde whose portrait lives on the shell (the member defines none) uses the shell's —
    # the case the member-first lookup used to miss, returning nothing.
    assert portrait_mapped_images(objects["ShellPortraitHorde"]) == [images["UPShellPortrait"]]
    # A horde whose portrait lives only on the contained unit still uses the member's.
    assert portrait_mapped_images(objects["MemberPortraitHorde"]) == [images["UPMemberPortrait"]]


SPECIAL_POWERS_FIXTURE = """
SpecialPower SpecialPower_Fire
  ReloadTime = 30000
End
SpecialPower SpecialPower_Buff
End
SpecialPower SpecialPower_Summon
End
SpecialPower SpecialPower_Plain
End
Weapon SpecialFireWeapon
  AttackRange = 250
  DamageNugget
    Damage = 100
    DamageType = MAGIC
  End
End
ModifierList Buff_Modifiers
  Modifier = HEALTH 500
End
Object SummonedKnight
End
ObjectCreationList OCL_Summon
  CreateObject
    ObjectNames = SummonedKnight
  End
End
Object HeroUnit
  Behavior = UnpauseSpecialPowerUpgrade ModuleTag_FireEnabler
    SpecialPowerTemplate = SpecialPower_Fire
    TriggeredBy = Upgrade_Fire
  End
  Behavior = SpecialPowerModule ModuleTag_FireStarter
    SpecialPowerTemplate = SpecialPower_Fire
    StartsPaused = Yes
  End
  Behavior = WeaponFireSpecialAbilityUpdate ModuleTag_Fire
    SpecialPowerTemplate = SpecialPower_Fire
    SpecialWeapon = SpecialFireWeapon
  End
  Behavior = SpecialPowerModule ModuleTag_Buff
    SpecialPowerTemplate = SpecialPower_Buff
    AttributeModifier = Buff_Modifiers
  End
  Behavior = OCLSpecialPower ModuleTag_Summon
    SpecialPowerTemplate = SpecialPower_Summon
    OCL = OCL_Summon
  End
End
"""


def _special_powers_game() -> Game:
    game = Game()
    result = parse(SPECIAL_POWERS_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


def test_special_power_view_resolves_each_module_kind():
    game = _special_powers_game()
    hero = game.objects["HeroUnit"]

    # WeaponFireSpecialAbilityUpdate — the fired SpecialWeapon, as a weapon entry.
    # The power is also wired by an enabler and a paused starter sharing its
    # template; the weapon-fire module (the real effect) must win over them.
    fire = special_power_view(game, hero, "SpecialPower_Fire")
    assert fire["kind"] == "weapon"
    assert fire["weapon"]["name"] == "SpecialFireWeapon"
    assert fire["weapon"]["range"] == 250
    assert fire["weapon"]["nuggets"][0]["damage"] == 100
    # ReloadTime (ms) surfaces as the cooldown in whole seconds.
    assert fire["cooldown"] == 30
    # A power that declares no ReloadTime has no cooldown.
    assert special_power_view(game, hero, "SpecialPower_Buff")["cooldown"] is None

    # SpecialPowerModule — its AttributeModifier ModifierList (toggled on the unit).
    buff = special_power_view(game, hero, "SpecialPower_Buff")
    assert buff["kind"] == "modifier"
    assert buff["modifier"] is game.modifiers["Buff_Modifiers"]

    # OCLSpecialPower — the objects its ObjectCreationList summons. A directly
    # summoned real object is a leaf (nothing nested under it).
    summon = special_power_view(game, hero, "SpecialPower_Summon")
    assert summon["kind"] == "summon"
    assert summon["summoned"] == [{"name": "SummonedKnight", "summoned": []}]

    # A power with no matching module degrades to name-only (kind "").
    plain = special_power_view(game, hero, "SpecialPower_Plain")
    assert plain["kind"] == ""
    assert plain["summoned"] == []


EGG_SUMMON_FIXTURE = """
SpecialPower SpecialPower_EggSummon
End
Object RealKnight
End
ObjectCreationList OCL_HatchKnight
  CreateObject
    ObjectNames = RealKnight
  End
End
ObjectCreationList OCL_SummonEgg
  CreateObject
    ObjectNames = KnightSummonEgg
  End
End
Object KnightSummonEgg
  KindOf = INERT UNATTACKABLE
  Behavior = LifetimeUpdate ModuleTag_Hatch
    MinLifetime = 0.0
    MaxLifetime = 0.0
  End
  Behavior = SlowDeathBehavior ModuleTag_HatchProcess
    OCL = FINAL OCL_HatchKnight
  End
End
Object EggCaster
  Behavior = OCLSpecialPower ModuleTag_Summon
    SpecialPowerTemplate = SpecialPower_EggSummon
    OCL = OCL_SummonEgg
  End
End
"""


def test_special_power_view_hatches_summon_eggs():
    """An OCLSpecialPower that summons an egg resolves into the chain
    egg → the real object the egg hatches on death, both kept visible."""
    game = Game()
    result = parse(EGG_SUMMON_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)

    caster = game.objects["EggCaster"]
    summon = special_power_view(game, caster, "SpecialPower_EggSummon")
    assert summon["kind"] == "summon"
    assert summon["summoned"] == [
        {"name": "KnightSummonEgg", "summoned": [{"name": "RealKnight", "summoned": []}]}
    ]


NAMES_FIXTURE = """
Object Knight
  DisplayName = OBJECT:Knight
  Description = CONTROLBAR:KnightDesc
End
Object KnightVariant
  DisplayName = OBJECT:Knight
End
Object Nameless
End
Object RiderMounted
  DisplayName = OBJECT:Rider
End
Object Rider
  DisplayName = OBJECT:Rider
  Behavior = ToggleMountedSpecialAbilityUpdate ModuleTag_Mount
    SpecialPowerTemplate = SpecialPower_Mount
    MountedTemplate = RiderMounted
  End
End
"""


def _names_game() -> Game:
    game = Game()
    result = parse(NAMES_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    game.strings.update(
        {
            "OBJECT:Knight": "Gondor Knight",
            "OBJECT:Rider": "Rider of Rohan",
            "CONTROLBAR:KnightDesc": "A heavily armoured swordsman.",
        }
    )
    return game


def test_clean_text_flattens_newline_breaks():
    nl = "\\n"  # the literal two-character break stored in the string tables
    # A break with no period before it gains one; an existing period is kept.
    assert clean_text("Game Experience May" + nl + "Change Online") == (
        "Game Experience May. Change Online"
    )
    assert clean_text("It heals." + nl + "Use wisely") == "It heals. Use wisely"
    assert clean_text("BASIC" + nl + "TUTORIAL") == "BASIC. TUTORIAL"
    # A colon (and other non-alphanumeric ends) is left as-is, not given a period.
    assert clean_text("Ends colon:" + nl + "Next") == "Ends colon: Next"
    # A trailing break is dropped; each interior break becomes a sentence.
    assert clean_text("A warrior" + nl + "Deals damage" + nl) == "A warrior. Deals damage"
    # No break (and None) pass through untouched.
    assert clean_text("Orc Warrior") == "Orc Warrior"
    assert clean_text(None) is None


def test_description_returns_raw_text_for_the_ui_to_clean():
    game = Game()
    result = parse(
        "Object Hero\n  DisplayName = OBJECT:Hero\n  Description = OBJECT:HeroDesc\nEnd\n",
        file="t.ini",
    )
    assert not result.diagnostics
    game.load_document(result.document)
    game.strings.update(
        {"OBJECT:Hero": "Captain", "OBJECT:HeroDesc": "A bold leader\\nRallies nearby troops"}
    )
    obj = game.objects["Hero"]
    # The resolver keeps the raw \n (the wiki does its own line handling); the
    # display layer flattens it via clean_text.
    assert description(game, obj) == "A bold leader\\nRallies nearby troops"
    assert clean_text(description(game, obj)) == "A bold leader. Rallies nearby troops"


def test_display_name_and_description_resolve_labels():
    game = _names_game()
    objects = game.objects
    assert display_name(game, objects["Knight"]) == "Gondor Knight"
    assert description(game, objects["Knight"]) == "A heavily armoured swordsman."
    # No DisplayName / Description label declared → None (callers fall back).
    assert display_name(game, objects["Nameless"]) is None
    assert description(game, objects["Nameless"]) is None
    # A DisplayName whose label isn't in the string table also degrades to None.
    assert description(game, objects["KnightVariant"]) is None


def test_description_falls_back_to_recruit_text():
    game = Game()
    result = parse(
        "Object NoDesc\n  RecruitText = CONTROLBAR:Recruit\nEnd\n"
        "Object DescWins\n  Description = CONTROLBAR:Desc\n"
        "  RecruitText = CONTROLBAR:Recruit\nEnd\n",
        file="t.ini",
    )
    assert not result.diagnostics
    game.load_document(result.document)
    game.strings.update(
        {"CONTROLBAR:Recruit": "Recruited from the barracks.", "CONTROLBAR:Desc": "A soldier."}
    )
    # No Description → the RecruitText stands in.
    assert description(game, game.objects["NoDesc"]) == "Recruited from the barracks."
    # Description still wins when both are present.
    assert description(game, game.objects["DescWins"]) == "A soldier."


def test_display_name_index_maps_display_names_to_raw_names():
    game = _names_game()
    names = sorted(game.objects)
    display_names, index = display_name_index(game, names)
    # Distinct display names only, sorted; objects without one are skipped.
    assert display_names == ["Gondor Knight", "Rider of Rohan"]
    # Lookup is case-insensitive and maps back to the raw object name.
    assert index["gondor knight"] == "Knight"
    assert index["rider of rohan"] == "Rider"
    # When several objects share a display name, the first (in name order) wins.
    assert index["gondor knight"] != "KnightVariant"


def test_mounted_template_links_to_the_mounted_object():
    game = _names_game()
    objects = game.objects
    assert mounted_template(objects["Rider"]) == "RiderMounted"
    # A unit with no ToggleMountedSpecialAbilityUpdate has no mounted form.
    assert mounted_template(objects["Knight"]) is None


def test_modifier_view_lists_each_modifier_line():
    game = _special_powers_game()
    view = modifier_view(game.modifiers["Buff_Modifiers"])
    assert view["name"] == "Buff_Modifiers"
    assert view["modifiers"] == [("HEALTH", "500")]

    # An absent list (e.g. the modifier block lives in an unloaded source).
    assert modifier_view(None) == {"name": None, "modifiers": []}


def test_modifier_view_resolves_macro_values():
    game = Game()
    result = parse(
        "#define BONUS_HP 750\n"
        "ModifierList Buff\n  Modifier = HEALTH BONUS_HP\n  Modifier = ARMOR 25% PIERCE\nEnd\n",
        file="t.ini",
    )
    assert not result.diagnostics
    game.load_document(result.document)
    view = modifier_view(game.modifiers["Buff"])
    # The macro value is resolved to its definition; a plain value passes through.
    assert view["modifiers"] == [("HEALTH", "750"), ("ARMOR (PIERCE)", "25%")]


COMBAT_FIXTURE = """
Armor TestArmor
  Armor = DEFAULT 100%
  Armor = PIERCE 50%
  Armor = SLASH 200%
End
Weapon TestSword
  FiringDuration = 500
  DelayBetweenShots = 1500
  DamageNugget
    Damage = 60
    DamageType = SLASH
    Radius = 0
  End
  DamageNugget
    Damage = 20
    DamageType = SLASH
    Radius = 0
  End
End
Weapon TestBow
  AttackRange = 300
  ClipSize = 1
  ClipReloadTime = Min:1500 Max:2000
  DamageNugget
    Damage = 40
    DamageType = PIERCE
    Radius = 0
  End
End
Object TestWarrior
  WeaponSet
    Conditions = None
    Weapon = PRIMARY TestSword
  End
  ArmorSet
    Conditions = None
    Armor = TestArmor
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 300
  End
End
Object NoArmorUnit
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 120
  End
End
Object SpellBookLike
  CommandSet = SomeCommandSet
End
"""


def _combat_game() -> Game:
    game = Game()
    result = parse(COMBAT_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


def test_weapon_attack_interval_uses_cycle_then_clip_reload():
    weapons = _combat_game().weapons
    # A normal weapon's cycle is FiringDuration + mean DelayBetweenShots.
    assert weapon_attack_interval(weapons["TestSword"]) == 2000
    # A one-shot clip weapon has a zero cycle, so it paces by ClipReloadTime (Max).
    assert weapon_attack_interval(weapons["TestBow"]) == 2000
    assert clip_reload_time(weapons["TestBow"]) == 2000
    # A weapon with neither a cycle nor a clip reload has no interval.
    assert clip_reload_time(weapons["TestSword"]) is None


def test_weapon_damage_per_shot_and_dps():
    game = _combat_game()
    state = UnitState(game.objects["TestWarrior"])
    sword = game.weapons["TestSword"]
    # Both damage nuggets of a shot are summed (60 + 20).
    assert weapon_damage_per_shot(sword, state) == 80
    assert weapon_top_nugget(sword, state) == (60, "SLASH")
    # DPS = per-shot damage / cycle in seconds = 80 / (2000 ms) = 40.
    assert weapon_dps(sword, state) == 40


def test_weapon_dps_reflects_active_damage_modifiers():
    game = Game()
    result = parse(
        "ModifierList DmgBuff\n  Modifier = DAMAGE_MULT 200%\nEnd\n" + COMBAT_FIXTURE,
        file="t.ini",
    )
    assert not result.diagnostics
    game.load_document(result.document)
    state = UnitState(game.objects["TestWarrior"])
    sword = game.weapons["TestSword"]
    state.extra_modifiers = [game.modifiers["DmgBuff"]]
    # DAMAGE_MULT 200% doubles every nugget: (60 + 20) * 2 = 160 per shot, 80 DPS.
    assert weapon_damage_per_shot(sword, state) == 160
    assert weapon_dps(sword, state) == 80


def test_bodyless_object_resolves_to_none_without_crashing():
    """A spellbook-like object has no Body, armor or weapons; reading its combat
    stats must degrade to None/empty, not raise (the panel renders such objects)."""
    game = _combat_game()
    state = UnitState(game.objects["SpellBookLike"])
    assert state.base_max_health is None
    assert state.max_health is None
    assert state.vision is None
    assert state.armor is None
    assert effective_health(state) == {}
    assert effective_health_against(state, "PIERCE") is None


def test_effective_health_per_damage_type():
    game = _combat_game()
    state = UnitState(game.objects["TestWarrior"])
    effective = effective_health(state)
    # health / coefficient: 300/1 default, 300/0.5 pierce (tougher), 300/2 slash (weaker).
    assert effective == {"DEFAULT": 300, "PIERCE": 600, "SLASH": 150}


BUILDERS_FIXTURE = """
Object Knight
End
Object Archer
End
Object SiegeRam
End
Upgrade Upgrade_Expand
End
CommandButton Command_BuildKnight
  Command = UNIT_BUILD
  Object = Knight
End
CommandButton Command_BuildArcher
  Command = UNIT_BUILD
  Object = Archer
End
CommandButton Command_BuildSiege
  Command = UNIT_BUILD
  Object = SiegeRam
End
CommandSet Barracks_CommandSet
  1 = Command_BuildKnight
  2 = Command_BuildArcher
End
CommandSet Keep_CommandSet
  1 = Command_BuildKnight
End
CommandSet Expanded_CommandSet
  1 = Command_BuildSiege
End
Object Barracks
  CommandSet = Barracks_CommandSet
End
Object Keep
  CommandSet = Keep_CommandSet
End
Object Workshop
  Behavior = CommandSetUpgrade ModuleTag_Expand
    TriggeredBy = Upgrade_Expand
    CommandSet = Expanded_CommandSet
  End
End
"""


def _builders_game() -> Game:
    game = Game()
    result = parse(BUILDERS_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


def test_builder_index_maps_units_to_their_builders():
    index = builder_index(_builders_game())
    # A unit built by several structures lists them in object-table order.
    assert index["Knight"] == ["Barracks", "Keep"]
    assert index["Archer"] == ["Barracks"]
    # A command set a CommandSetUpgrade swaps in counts, even when not yet active.
    assert index["SiegeRam"] == ["Workshop"]
    # Nothing builds the structures themselves.
    assert "Barracks" not in index


def test_builders_of_caches_on_the_game():
    game = _builders_game()
    assert builders_of(game, "Knight") == ["Barracks", "Keep"]
    # An object nobody builds resolves to an empty list.
    assert builders_of(game, "Barracks") == []
    # The index is built once and cached on the game, so a second call reuses it.
    cached = game._builder_index
    assert builders_of(game, "Archer") == ["Barracks"]
    assert game._builder_index is cached


FACTIONS_FIXTURE = """
PlayerTemplate FactionMen
  Side = Men
  PlayableSide = Yes
  DisplayName = INI:FactionMen
  SpellBook = GoodSpellBook
  SpellBookMp = MenSpellBook
  BuildableHeroesMP = CreateAHero GondorBoromir GondorBoromir RohanTheoden
  BuildableRingHeroesMP = RingHeroDummy ElvenGaladriel_RingHero
End
PlayerTemplate FactionNeutral
  Side = Neutral
  PlayableSide = No
  DisplayName = INI:FactionNeutral
End
PlayerTemplate FactionElves
  Side = Elves
  PlayableSide = Yes
  DisplayName = INI:FactionElves
  SpellBook = GoodSpellBook
End
"""


def test_playable_factions_lists_heroes_and_spellbook():
    game = Game()
    result = parse(FACTIONS_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    game.strings.update({"INI:FactionMen": "Men of the West", "INI:FactionElves": "Elves"})

    factions = playable_factions(game)
    # Only PlayableSide = Yes factions, in table order; the neutral one is dropped.
    assert [f["name"] for f in factions] == ["FactionMen", "FactionElves"]

    men = factions[0]
    assert men["display"] == "Men of the West"  # localized DisplayName
    # Heroes: BuildableHeroesMP then BuildableRingHeroesMP, de-duplicated, in order;
    # the CreateAHero and RingHeroDummy placeholders are filtered out.
    assert men["heroes"] == [
        "GondorBoromir",
        "RohanTheoden",
        "ElvenGaladriel_RingHero",
    ]
    # The faction-specific MP spellbook is preferred over the shared one.
    assert men["spellbook"] == "MenSpellBook"

    # A faction with only the shared SpellBook falls back to it; no heroes listed.
    assert factions[1]["spellbook"] == "GoodSpellBook"
    assert factions[1]["heroes"] == []


WEAPON_FILTER_FIXTURE = """
Weapon TrollPunch
  DamageNugget
    Damage = 150
    Radius = 50
    DamageType = WATER
    DamageScalar = 250% ANY +HERO +MACHINE +MONSTER
    DamageScalar = 0% ANY +STRUCTURE
  End
  DamageNugget
    Damage = 240
    Radius = 30
    DamageType = SIEGE
    DamageScalar = 0% ALL -STRUCTURE ENEMIES
  End
  MetaImpactNugget
    ShockWaveRadius = 50
    HeroResist = 1.0
  End
End
"""


def _weapon_filter_game() -> Game:
    game = Game()
    result = parse(WEAPON_FILTER_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


def test_filter_signature_canonicalizes_damage_scalars():
    weapon = _weapon_filter_game().weapons["TrollPunch"]
    damage_nuggets = [n for n in weapon.Nuggets if type(n).__name__ == "DamageNugget"]
    first, second = damage_nuggets

    # An inclusion filter: descriptor and `+` members, no relations or exclusions.
    bonus = first.DamageScalar[0]
    assert bonus.Scalar == 2.5  # 250% -> fraction
    assert filter_signature(bonus.ObjectFilter) == FilterSignature(
        descriptor="ANY",
        relations=frozenset(),
        inclusion=frozenset({"HERO", "MACHINE", "MONSTER"}),
        exclusion=frozenset(),
    )

    structure = first.DamageScalar[1]
    assert structure.Scalar == 0.0
    assert filter_signature(structure.ObjectFilter).inclusion == frozenset({"STRUCTURE"})

    # An exclusion filter keeps its descriptor, relation and `-` member distinct.
    spare = second.DamageScalar[0]
    assert filter_signature(spare.ObjectFilter) == FilterSignature(
        descriptor="ALL",
        relations=frozenset({"ENEMIES"}),
        inclusion=frozenset(),
        exclusion=frozenset({"STRUCTURE"}),
    )


def test_filter_signature_is_none_for_an_unscoped_multiplier():
    # A bare `DamageScalar = 50%` scopes to nothing — the signature is None ("everything").
    game = Game()
    result = parse(
        "Weapon Flat\n  DamageNugget\n    Damage = 10\n    DamageScalar = 50%\n  End\nEnd\n",
        file="t.ini",
    )
    assert not result.diagnostics
    game.load_document(result.document)
    scaled = game.weapons["Flat"].Nuggets[0].DamageScalar[0]
    assert scaled.Scalar == 0.5
    assert scaled.ObjectFilter is None
    assert filter_signature(scaled.ObjectFilter) is None


def test_effective_health_against_specific_type():
    game = _combat_game()
    state = UnitState(game.objects["TestWarrior"])
    assert effective_health_against(state, "PIERCE") == 600
    assert effective_health_against(state, "SLASH") == 150
    # An unlisted type falls back to the armor's DEFAULT coefficient.
    assert effective_health_against(state, "MAGIC") == 300
    # With no armor at all, full damage gets through, so effective HP is raw health.
    no_armor = UnitState(game.objects["NoArmorUnit"])
    assert effective_health_against(no_armor, "PIERCE") == 120
    assert effective_health(no_armor) == {}


def test_closest_names_finds_a_misspelled_unit():
    names = ["Ithilien Rangers", "Gondor Knight", "Tower Guard", "Mordor Orc Warrior"]
    # A one-letter typo of a multi-word name still resolves (the search box's typo tolerance).
    assert closest_names("Itilien Rangers", names) == ["Ithilien Rangers"]
    assert closest_names("Gondr Knight", names)[0] == "Gondor Knight"
    # Nothing close enough yields no suggestion rather than a misleading one.
    assert closest_names("zzzzzzzz", names) == []
    # Not gated by the global suggestion flag — an interactive caller always gets matches.
    assert closest_names("Tower Gaurd", names) == ["Tower Guard"]


def test_closest_names_is_case_insensitive_and_capped():
    names = [f"Unit{i}" for i in range(10)]
    matches = closest_names("unit", names, count=3)
    assert len(matches) <= 3
    assert all(m.startswith("Unit") for m in matches)  # candidates keep their own casing


UPGRADE_LABEL_FIXTURE = """
Upgrade Upgrade_FireArrows
  DisplayName = UPGRADE:FireArrows
End
Upgrade Upgrade_FireArrowsElite
  DisplayName = UPGRADE:FireArrows
End
Upgrade Upgrade_NoLabel
End
"""


def _upgrade_label_game() -> Game:
    game = Game()
    result = parse(UPGRADE_LABEL_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    game.strings.update({"UPGRADE:FireArrows": "Fire Arrows"})
    return game


def test_upgrade_label_prefers_the_localized_name():
    game = _upgrade_label_game()
    assert upgrade_label(game, "Upgrade_FireArrows") == "Fire Arrows"
    # No localized DisplayName (or upgrade not loaded) falls back to the raw template id.
    assert upgrade_label(game, "Upgrade_NoLabel") == "Upgrade_NoLabel"
    assert upgrade_label(game, "Upgrade_NotLoaded") == "Upgrade_NotLoaded"


def test_upgrade_toggle_labels_disambiguate_duplicate_display_names():
    game = _upgrade_label_game()
    labels = upgrade_toggle_labels(
        game, ["Upgrade_FireArrows", "Upgrade_FireArrowsElite", "Upgrade_NoLabel"]
    )
    # Two upgrades share the display name "Fire Arrows", so each keeps its raw id in parens.
    assert labels["Upgrade_FireArrows"] == "Fire Arrows (Upgrade_FireArrows)"
    assert labels["Upgrade_FireArrowsElite"] == "Fire Arrows (Upgrade_FireArrowsElite)"
    # An id with no localized label is left as-is (no redundant "(id)").
    assert labels["Upgrade_NoLabel"] == "Upgrade_NoLabel"


def test_upgrade_toggle_labels_keep_a_unique_name_clean():
    game = _upgrade_label_game()
    # When only one upgrade carries the shared display name, no disambiguation is added.
    labels = upgrade_toggle_labels(game, ["Upgrade_FireArrows", "Upgrade_NoLabel"])
    assert labels["Upgrade_FireArrows"] == "Fire Arrows"
