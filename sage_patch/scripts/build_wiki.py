"""Render the engine module reference as a browsable static HTML site.

Reads what `module_defaults.py` recovered from `game.dat` - modules, fields, types,
defaults, enum name arrays and sub-block schemas - and writes a page per module plus
the type, enum and coverage pages that give a field's type a meaning. `sage_ini`
supplies the second opinion: its enums are matched against the engine's own name
arrays so each list can say whether the two sources agree.

The site is self-contained and opens from the filesystem: no server, no CDN, and the
search index ships as a script rather than as data fetched at runtime. It is a build
artefact, not part of the repository: it lands in `build/wiki/` and is regenerated from
the JSON in `sage_patch/docs/`.

Usage:
    python build_wiki.py [--out build/wiki]
"""

from __future__ import annotations

import argparse
import html
import inspect
import json
import os
import shutil
from typing import Any, Optional

import sage_ini.model.enums as sage_enums
import sage_ini.model.types as sage_types
from sage_ini.model.objects import REGISTRY as SAGE_REGISTRY
from sage_utils import webtheme

__all__ = ["build", "TYPE_DOCS", "CATEGORIES"]

HERE = os.path.dirname(os.path.abspath(__file__))


def _asset(name: str) -> str:
    with open(os.path.join(HERE, "wiki_assets", name), encoding="utf-8") as f:
        return f.read()


REPO = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir))
DOCS = os.path.join(HERE, os.pardir, "docs")
MODULE_JSON = os.path.join(DOCS, "module-reference.json")
TYPE_JSON = os.path.join(DOCS, "ini-types.json")
DEFAULT_OUT = os.path.join(REPO, "build", "wiki")

ENGINE_BUILD = "2.01.2614.37001"

# How `module_defaults.py` writes a default that is known to be nothing at all.
EMPTY = '""'

# Modules are grouped by the interface their name ends in, which is also the INI
# keyword that takes them: `Behavior = ...`, `Draw = ...`, `Body = ...`.
CATEGORIES = [
    ("Update", "Update", "Per-frame logic: production, movement, abilities, spawning."),
    ("Behavior", "Behavior", "Behaviours attached with `Behavior =`, the largest catch-all group."),
    ("SpecialPower", "Special power", "The modules behind a `SpecialPower` template."),
    ("Upgrade", "Upgrade", "Modules that fire when an upgrade is granted."),
    ("Draw", "Draw", "Draw modules: what the object looks like and how it animates."),
    ("Contain", "Contain", "Containers: garrisons, transports, hordes."),
    ("Die", "Die", "What happens when the object dies."),
    ("Body", "Body", "Health, armour and damage state."),
    ("Collide", "Collide", "Reactions to bumping into another object."),
    ("Create", "Create", "One-shot logic at creation time."),
    ("", "Other", "Modules whose name does not end in an interface suffix."),
]

# What a type means to someone writing INI: what you write, and what the engine
# stores once it has parsed it. Engine-side facts (scaling, range checks, the name
# array a token is resolved against) come from the parse function itself.
TYPE_DOCS: dict[str, tuple[str, str, str]] = {
    "Bool": (
        "Scalar",
        "`Yes` or `No`",
        "A single byte. Anything the parser does not recognise is a parse error, "
        "not a silent `No`.",
    ),
    "Int": (
        "Scalar",
        "a whole number",
        "Signed 32-bit. The parser accepts the INI math operators and macros, so "
        "`#ADD(2 3)` is as valid as `5`.",
    ),
    "Int8": (
        "Scalar",
        "a whole number, -128 to 127",
        "Stored in one byte. A value outside the range is rejected and the field "
        "keeps its default.",
    ),
    "UInt8": (
        "Scalar",
        "a whole number, 0 to 255",
        "Stored in one byte. A value outside the range is rejected and the field "
        "keeps its default.",
    ),
    "UInt16": (
        "Scalar",
        "a whole number, 0 to 65535",
        "Stored in two bytes. A value outside the range is rejected and the "
        "field keeps its default.",
    ),
    "Real": ("Scalar", "a decimal number", "A 32-bit float, stored exactly as written."),
    "PositiveReal": (
        "Scalar",
        "a decimal number greater than zero",
        "The parser range-checks it and logs `invalid Real value ... "
        "expected > 0` for anything else.",
    ),
    "NonNegativeReal": (
        "Scalar",
        "a decimal number, zero or greater",
        "The parser range-checks it and logs `invalid Real value ... "
        "expected >= 0` for anything else.",
    ),
    "NonPositiveReal": (
        "Scalar",
        "a decimal number, zero or less",
        "The parser range-checks it and logs `invalid Real value ... "
        "expected <= 0` for anything else.",
    ),
    "Percent": (
        "Scalar",
        "a percentage, `50` meaning half",
        "Divided by 100 on the way in, so the stored value is a fraction. "
        "Defaults are shown as you would write them, `50%`.",
    ),
    "AngleReal": (
        "Scalar",
        "an angle in degrees",
        "Multiplied by pi/180, so the engine stores radians. Defaults are shown "
        "in degrees.",
    ),
    "Duration": (
        "Scalar",
        "a duration in milliseconds",
        "Converted to whole logic frames (five a second, rounded up) and stored as an "
        "integer, so anything finer than 200 ms is lost. Defaults are shown in "
        "milliseconds; a value in hex is a sentinel the engine tests for, not a duration.",
    ),
    "DurationReal": (
        "Scalar",
        "a duration in milliseconds",
        "Converted to logic frames and kept fractional. Defaults are shown in milliseconds.",
    ),
    "VelocityReal": (
        "Scalar",
        "a speed in world units per second",
        "Converted to units per logic frame. Defaults are shown per second.",
    ),
    "AngularVelocityReal": (
        "Scalar",
        "a turn rate in degrees per second",
        "Converted to radians per logic frame. Defaults are shown in degrees per second.",
    ),
    "UnsignedInt": (
        "Scalar",
        "a whole number, zero or greater",
        "Unsigned 32-bit. Where the field table gives a maximum, a larger value is "
        "rejected with `value out of range`.",
    ),
    "Coord3D": (
        "Scalar",
        "`X:<real> Y:<real> Z:<real>`",
        "Three floats, each with its label.",
    ),
    "Coord2D": ("Scalar", "`X:<real> Y:<real>`", "Two floats, each with its label."),
    "Coord2DInt": (
        "Scalar",
        "`X:<int> Y:<int>`",
        "Two whole numbers, each with its label.",
    ),
    "RGBColor": (
        "Scalar",
        "`R:<0-255> G:<0-255> B:<0-255>`",
        "Each channel is divided by 255 and stored as a float.",
    ),
    "RGBAColor": (
        "Scalar",
        "`R:<0-255> G:<0-255> B:<0-255> A:<0-255>`",
        "Packed into one 32-bit ARGB value. `A:` may be left out and then means 255.",
    ),
    "AsciiString": (
        "Text",
        "one token, or a quoted string",
        "Stored verbatim. What the name has to match depends on the field - "
        "a bone, a subobject, an object name.",
    ),
    "AsciiStringList": ("Text", "any number of tokens on the line", "Stored as a list of strings."),
    "Enum": (
        "Enumeration",
        "one token from a fixed list",
        "The token's position in the list is what gets stored. The list lives in "
        "the field's own parse table, so each field names its own.",
    ),
    "LookupList": (
        "Enumeration",
        "one token from a fixed list",
        "Like `Enum`, but each name carries an explicit value rather than its position.",
    ),
    "BitFlags": (
        "Flag set",
        "any number of tokens on one line",
        "Each token turns on one bit. The list lives in the field's own parse "
        "table, so each field names its own.",
    ),
    "KindOfFlags": (
        "Flag set",
        "any number of `KindOf` tokens",
        "Turns on one bit each in the object's KindOf mask.",
    ),
    "KindOfFilter": (
        "Flag set",
        "`KindOf` tokens, `+` to require and `-` to exclude",
        "A test against another object's KindOf mask rather than a value of its own.",
    ),
    "ObjectStatusFlags": (
        "Flag set",
        "any number of `ObjectStatus` tokens",
        "Runtime status bits, the same set the engine sets and clears as an object plays.",
    ),
    "ModelConditionFlags": (
        "Flag set",
        "any number of `ModelCondition` tokens",
        "The condition set a draw module matches its art against.",
    ),
    "ModelConditionFlag": (
        "Enumeration",
        "one `ModelCondition` token",
        "A single condition, not a set.",
    ),
    "WeaponSetFlags": (
        "Flag set",
        "any number of weapon-set tokens",
        "Selects which `WeaponSet` block applies.",
    ),
    "DamageTypeFlags": (
        "Flag set",
        "`DamageType` tokens, or `ALL` / `NONE`",
        "`ALL` and `NONE` set and clear every bit.",
    ),
    "DeathTypeFlags": (
        "Flag set",
        "`DeathType` tokens, or `ALL` / `NONE`",
        "`ALL` and `NONE` set and clear every bit.",
    ),
    "SpecialPowerTrigger": (
        "Reference",
        "a `SpecialPower` name, optionally followed by a trigger token",
        "Each line adds one more power to trigger, up to eight. The token comes from "
        "the special power flag list.",
    ),
    "SpecialPowerAIType": (
        "Enumeration",
        "one `AI_SPECIAL_POWER_*` token",
        "Tells the AI how to use the power.",
    ),
    "EmotionType": (
        "Enumeration",
        "one emotion token",
        "One of the engine's fixed emotion reactions.",
    ),
    "WeatherType": ("Enumeration", "one weather token", "Global weather state."),
    "UpgradeMask": (
        "Reference",
        "any number of `Upgrade` names",
        "Stored as a bit per upgrade in a fixed-width mask, which is why "
        "the number of upgrades a build supports is capped.",
    ),
    "WeaponTemplate": (
        "Reference",
        "a `Weapon` name",
        "Resolved against Weapon.ini when the object is loaded.",
    ),
    "UpgradeTemplate": ("Reference", "an `Upgrade` name", "Resolved against Upgrade.ini."),
    "SpecialPowerTemplate": (
        "Reference",
        "a `SpecialPower` name",
        "Resolved against SpecialPower.ini.",
    ),
    "ScienceType": ("Reference", "a `Science` name", "Resolved against Science.ini."),
    "ObjectCreationList": ("Reference", "an `ObjectCreationList` name", "`None` clears the field."),
    "ParticleSystem": ("Reference", "an `FXParticleSystem` name", "`None` clears the field."),
    "FXList": (
        "Reference",
        "an `FXList` name",
        "`None` clears the field. An unknown name is reported with its line number at load time.",
    ),
    "AudioEventRTS": (
        "Reference",
        "a sound or voice event name",
        "Resolved against the audio INI. `NoSound` clears it.",
    ),
    "EvaEvent": ("Reference", "an EVA event name", "Resolved against Eva.ini."),
    "MomentFXList": (
        "Reference",
        "a moment token, then an `FXList` name",
        "One line per moment, so a module can play something different at "
        "each stage. Which moments are on offer depends on the module.",
    ),
    "MomentOCL": (
        "Reference",
        "a moment token, then an `ObjectCreationList` name",
        "One line per moment. Which moments are on offer depends on the module.",
    ),
    "MomentSound": ("Reference", "a moment token, then a sound name", "One line per moment."),
    "MomentWeapon": ("Reference", "a moment token, then a `Weapon` name", "One line per moment."),
    "AngleFXList": (
        "Reference",
        "an angle in degrees, then an `FXList` name",
        "Picks the effect by the angle of impact.",
    ),
    "DisabledTypeFlags": (
        "Flag set",
        "any number of disabled-state tokens",
        "The states an object can be disabled in - held, paralysed, unmanned and the rest.",
    ),
    "ModelConditionFlagRange": (
        "Flag set",
        "exactly two `ModelCondition` tokens",
        "The pair names the ends of a range; the engine complains if you give it anything but two.",
    ),
    "MeleeBehavior": (
        "Enumeration",
        "one melee-behaviour token",
        "How a horde's members close on their target.",
    ),
    "Module": (
        "Reference",
        "a module name, then a tag of your own",
        "Attaches a module and opens its block. The tag only has to be unique "
        "within the object, and is what an override or a `RemoveModule` refers "
        "to later.",
    ),
    "GeometryType": (
        "Enumeration",
        "one geometry token",
        "The primitive the object's collision shape is built from.",
    ),
    # The parsers with a syntax of their own; what each one reads and keeps was read
    # from its body.
    "AccelerationReal": (
        "Scalar",
        "`<real per second^2>`",
        "Real * (0.2 s/frame)^2 -> per-frame^2 acceleration.",
    ),
    "AIKindOf": (
        "Enumeration",
        "`<AIKindOf> or \"<AIKindOf>\"`",
        "Optionally quoted string indexed, stored as dword; throws \"invalid AI_KINDOF\".",
    ),
    "AIKindOfList": (
        "Flag set",
        "`<AIKindOf> ...`",
        "Each token indexed into a fixed array at field, max 17.",
    ),
    "AnimationSet": (
        "Text",
        "`<animation> <animation> <animation>`",
        "Three animation names kept together as one set. Each line adds another set.",
    ),
    "ArmorCoefficient": (
        "Scalar",
        "`<DamageType|Default> <percent>`",
        "Percent/100 stored at instance+4+4*DamageType; Default fills all 28 entries. Each "
        "line adds another entry.",
    ),
    "ArmorSetFlags": (
        "Flag set",
        "`<ArmorSetFlag> ... | +X -Y | NONE`",
        "Each token turns on one bit; `+X` adds and `-X` removes one, `NONE` clears them all.",
    ),
    "AttributeModifier": (
        "Scalar",
        "`<ModifierAttribute> <real>[%] [<string> ...]`",
        "Attribute index, value (percent if it contains '%'), optional string list; appended.",
    ),
    "AudioEventRTSList": (
        "Reference",
        "`<sound> ... | NoSound`",
        "Every token parsed as AudioEventRTS (\"NoSound\" allowed, \"Invalid Sound\" "
        "otherwise) and pushed.",
    ),
    "AutoResolveArmorCoefficient": (
        "Scalar",
        "`<AutoResolveUnitType> <percent>`",
        "Percent stored for that auto-resolve unit type. Each line sets one type.",
    ),
    "AutoResolveBody": (
        "Reference",
        "`<name>`",
        "Looked up by name in the LW auto-resolve body store; pointer stored; throws \"Unknown "
        "LivingWorldAutoResolveBody %s\".",
    ),
    "AutoResolveCombatChain": (
        "Reference",
        "`<name>`",
        "Looked up; pointer stored; throws \"Unknown LivingWorldAutoResolveCombatChain %s\".",
    ),
    "AutoResolveLeadership": (
        "Reference",
        "`<name>`",
        "Looked up; pointer stored; throws \"Unknown LivingWorldAutoResolveLeadership %s\".",
    ),
    "AutoResolveTarget": (
        "Scalar",
        "`Target:<AutoResolveUnitType> Priority:<int>`",
        "Int priority stored for that auto-resolve unit type; naming a type twice is an "
        "error. Each line adds another target.",
    ),
    "AutoResolveUnitTypeFlags": (
        "Flag set",
        "`<AutoResolveUnit_*> ... | +X -Y | NONE`",
        "Each token turns on one bit; `+X` adds and `-X` removes one, `NONE` clears them all.",
    ),
    "BitFlags16": (
        "Flag set",
        "`<name> ...`",
        "BitFlags; throws if any bit above 15 is set; stored as a word.",
    ),
    "BoneConditionState": (
        "Scalar",
        "`<uint boneIndex> <ModelConditionFlag> ...`",
        "Map<UnsignedInt, ModelConditionFlags> at a fixed offset (field offset ignored): key "
        "from scanUInt, value from the ModelCondition token loop, inserted.",
    ),
    "BoneNameKey": (
        "Text",
        "`<bone> | None`",
        "Bone name -> NameKey and a new turret entry pushed.",
    ),
    "BoolBit": (
        "Scalar",
        "`<bool>`",
        "ScanBool; Yes ORs the userData mask into the dword field, No ANDs it out.",
    ),
    "BoolOrInt": (
        "Scalar",
        "`<1..4> | <bool>`",
        "Atoi value 1..4 stored as-is, otherwise scanBool (0/1); dword.",
    ),
    "BridgeFXEntry": (
        "Scalar",
        "`FX <FXList> Delay <ms> Bone <bone>`",
        "{FXList*, Duration frames, AsciiString bone} pushed; FX/Delay/Bone keywords mandatory.",
    ),
    "BridgeOCLEntry": (
        "Scalar",
        "`OCL <ObjectCreationList> Delay <ms> Bone <bone>`",
        "{OCL*, Duration frames, AsciiString bone} pushed; OCL/Delay/Bone keywords mandatory.",
    ),
    "ButtonTooltipMapping": (
        "Text",
        "`<AptButtonPath> <TooltipLabel>`",
        "Maps an Apt button path to the string label of its tooltip. Each line adds another "
        "entry.",
    ),
    "ByteEnum": (
        "Enumeration",
        "`<name>`",
        "ScanIndexList(token, userData names), range-checked 0..255, stored as a byte.",
    ),
    "CastleUnpack": (
        "Scalar",
        "`<Faction> <CastleTemplate> [<uint>] [<uint>]`",
        "Faction name -> NameKey inserted into map at field with value {AsciiString castle, "
        "UnsignedInt, UnsignedInt}; castle name also registered with TheSidesList.",
    ),
    "ClearNuggets": (
        "Text",
        "`(no value)`",
        "Takes no value: deletes every damage nugget already attached to the weapon, so the "
        "nuggets that follow replace them.",
    ),
    "CommandButton": (
        "Reference",
        "`<CommandButtonName>`",
        "CommandButton lookup and pointer stored into field[userData] (slot index); unknown "
        "name throws.",
    ),
    "CommandType": (
        "Enumeration",
        "`<GUICommand name>`",
        "Index (61 entries: NONE, FOUNDATION_CONSTRUCT, UNIT_BUILD,...) stored as dword; "
        "throws \"Command '%s' not found\".",
    ),
    "ContactPoint": (
        "Scalar",
        "`X:<real> Y:<real> Z:<real> [<tag>]`",
        "Coord3D (plus optional trailing token) appended to the object's contact-point list; "
        "extents recomputed.",
    ),
    "Coord2DList": (
        "Scalar",
        "`X:<real> Y:<real>`",
        "Coord2D push_back.",
    ),
    "CrowdResponse": (
        "Reference",
        "`<name>`",
        "Looked up in crowd-response store, pointer stored; throws \"Unknown CrowdResponse "
        "name '%s'\".",
    ),
    "DamageFX": (
        "Reference",
        "`<DamageFXName> | None`",
        "Name -> NameKey -> DamageFX store lookup; pointer stored; None -> null.",
    ),
    "DamageFXDuration": (
        "Scalar",
        "`[<VeterancyLevel>] <DamageFXType|Default> <ms>`",
        "Duration in ms -> frames written to the [veterancy][damageFXType] table. Each line "
        "adds another entry.",
    ),
    "DamageFXFXList": (
        "Scalar",
        "`[<VeterancyLevel>] <DamageFXType|Default> <FXList>`",
        "FXList* written to the same [veterancy][damageFXType] table. Each line adds another "
        "entry.",
    ),
    "DamageFXReal": (
        "Scalar",
        "`[<VeterancyLevel>] <DamageFXType|Default> <real>`",
        "Real written to table[veterancy 0..3][damageFXType 0..35] (16-byte cells, 64-byte "
        "rows); Veterancy* fields take a level (names = userData), plain ones fill all levels; "
        "Default fills all 36 types. Each line adds another entry.",
    ),
    "DeathFlags": (
        "Scalar",
        "`<ModelConditionFlag | ObjectStatus> ...`",
        "Tokens parsed as ModelConditionFlags into a fixed offset, 5 reserved condition bits "
        "masked out; the leftover tokens are parsed as ObjectStatus flags into a fixed offset "
        "with status bits - masked out.",
    ),
    "DecalTexture": (
        "Text",
        "`<texture>`",
        "Name of the texture the decal is drawn with.",
    ),
    "DurationByte": (
        "Scalar",
        "`<ms>`",
        "Ms -> ceil frames (* 0.005), must be < 256 frames (\"Duration %u must be less than %d "
        "frames\"), stored as byte.",
    ),
    "DurationRange": (
        "Scalar",
        "`<ms> | Min:<ms> Max:<ms>`",
        "Two Ints (min at field, max at the paired field) converted ms -> ceil frames; a "
        "single value sets both.",
    ),
    "DurationUInt16": (
        "Scalar",
        "`<milliseconds>`",
        "Unsigned Int in ms, rounded up to whole logic frames and stored as a 16-bit count.",
    ),
    "EatObjectEntry": (
        "Scalar",
        "`MyHealth:<percent> TargetHealth:<percent> Filter:<KindOfFilter ...>`",
        "Three labelled values (Percent, Percent, ObjectFilter) required in this order, entry "
        "appended.",
    ),
    "EmbedPortal": (
        "Scalar",
        "`<ramp|ladder|...> <bone>`",
        "New entry pushed; first quoted token lower-cased and mapped to type 2 (ramp) / 3 "
        "(ladder) at entry-8, second quoted token assigned as bone name at entry-4.",
    ),
    "EmotionAIType": (
        "Enumeration",
        "`<BACK_AWAY|AVOID_SCARER|IDLE|RUN_AWAY_PANIC|FACE_OBJECT|QUARREL>`",
        "Index stored as dword; throws \"Emotion AI type expected.\".",
    ),
    "EmotionNuggetRef": (
        "Reference",
        "`<EmotionNuggetName>`",
        "Named emotion nugget looked up and its whole data copied into this nugget.",
    ),
    "EnumList": (
        "Flag set",
        "`<name> ... | None`",
        "Vector cleared, each token scanIndexList against the field userData array, index "
        "push_back; None clears.",
    ),
    "EvaEventList": (
        "Reference",
        "`<EvaEvent> ... | None`",
        "Every token resolved and push_back.",
    ),
    "FactionDecal": (
        "Scalar",
        "`<Faction> <Texture> <real>`",
        "{AsciiString, AsciiString, Real} push_back into vector at a fixed offset (field "
        "offset ignored); also emits a debug-log line first.",
    ),
    "FactionFlags": (
        "Flag set",
        "`<Men|Elves|Dwarves|Isengard|Mordor|Wild|Angmar|Arnor|...> ... | NONE`",
        "Each token turns on one bit; `+X` adds and `-X` removes one, `NONE` clears them all.",
    ),
    "FactionNameList": (
        "Reference",
        "`<faction> ...`",
        "AsciiStringList, each name resolved as a Faction and stored.",
    ),
    "FilteredPercent": (
        "Scalar",
        "`<percent> <ObjectFilter ...>`",
        "A percent and the object filter it applies to. Each line adds another entry.",
    ),
    "FontDesc": (
        "Scalar",
        "`\"<font name>\" <int size> <bool bold>`",
        "Quoted name -> AsciiString at field, Int size at field+4, Bool byte at field+8.",
    ),
    "FontSizeSubstitution": (
        "Scalar",
        "`<int size> = <int size> \"<font name>\"`",
        "Two Ints and a quoted font name: text in the block's font at the first size is drawn "
        "in the named font at the second size. Each line adds another entry.",
    ),
    "FormationTemplate": (
        "Text",
        "`<name>` followed by a sub-block",
        "Names a formation layout and reads a sub-block for it. The stock INI never uses it, "
        "and its keywords are not listed here.",
    ),
    "FXEvent": (
        "Scalar",
        "`Frame:<int> [FrameStep:<int>] [FrameStop:<int>] [FireWhenSkipped] Name:<FXList>`",
        "Event struct parsed (keywords Frame, FrameStep, FrameStop, FireWhenSkipped, Name -> "
        "FX store) and appended to the state.",
    ),
    "FXListAtBone": (
        "Scalar",
        "`FX <FXList> [BONE <bone>]`",
        "{FXList*, AsciiString bone} pushed; \"FX\" keyword mandatory (\"'fx' expected\").",
    ),
    "FXListByVeterancy": (
        "Scalar",
        "`<VeterancyLevel> <FXList>`",
        "FXList stored in slot [veterancy]. Each line adds another entry.",
    ),
    "GameDifficulty": (
        "Enumeration",
        "`EASY|NORMAL|HARD|BRUTAL`",
        "0..3 stored as dword; anything else throws \"invalid GameDifficulty data\".",
    ),
    "GeometryOther": (
        "Scalar",
        "`GeomType:<SPHERE|CYLINDER|BOX> IsSmall:<bool> Height:<real> MajorRadius:<real> "
        "MinorRadius:<real> OffsetX:<real> OffsetY:<real> OffsetZ:<real> (label/value pairs, "
        "any order)`",
        "Builds one geometry entry from label/value token pairs and appends it to the object's "
        "\"other\" geometry list; extents recomputed.",
    ),
    "HealthFraction": (
        "Scalar",
        "`<real>`",
        "Real multiplied by the Body's max health (needs Body first) and truncated to Int, "
        "range-checked.",
    ),
    "Ignored": (
        "Scalar",
        "`<anything>`",
        "Accepted and ignored: this build reads nothing from the line.",
    ),
    "ImageSequence": (
        "Reference",
        "`<base image name>`",
        "Adds `NumberImages` MappedImages named `<base>000`, `<base>001`, ... (`%s%03d`); "
        "`NumberImages` has to come first.",
    ),
    "IntList": (
        "Scalar",
        "`<int> ... (1-based team numbers)`",
        "IntList then every stored value decremented by 1 (1-based in INI -> 0-based index). "
        "Each line adds another entry.",
    ),
    "IntPair": (
        "Scalar",
        "`<int> <int>`",
        "Two Ints at field and field+4.",
    ),
    "IntRange": (
        "Scalar",
        "`<int min> <int max>`",
        "Two Ints at field / field+4, swapped so min <= max.",
    ),
    "IntSet": (
        "Scalar",
        "`<int> <int> ...`",
        "Every remaining token atoid and inserted into set<Int> at field.",
    ),
    "LargeGroupAudioKeys": (
        "Text",
        "`<key> ...`",
        "Every token registered in the global LargeGroupAudio key map which hands out a bit "
        "index; that bit is OR'd into the mask at field. Each line adds another entry.",
    ),
    "LinearTarget": (
        "Scalar",
        "`X:<real> Y:<real> T:<uint>`",
        "{Real x, Real y, UnsignedInt t} pushed.",
    ),
    "LivingWorldPlayerTypeList": (
        "Reference",
        "`<player type> ...`",
        "Every token resolved and push_back; throws \"Unknown Living World player type '%s'\".",
    ),
    "LivingWorldSoundFlags": (
        "Flag set",
        "`<flag> ... | +X -Y | NONE`",
        "Each token turns on one bit; `+X` adds and `-X` removes one, `NONE` clears them all.",
    ),
    "LocalizedString": (
        "Text",
        "`<label from game text>`",
        "Looked up in the game text when the INI loads and stored as the translated string; an "
        "unknown label is a load error (\"Label '%s' not found in game text\").",
    ),
    "LowercaseAsciiString": (
        "Text",
        "`<name> or \"<name>\"`",
        "Optionally quoted string assigned to the AsciiString field, then lower-cased in place.",
    ),
    "LuaEvent": (
        "Scalar",
        "`Frame <int> Data <string> OnStateEnter|OnStateLeave (keywords in any order)`",
        "Event {frame, data string, enter/leave flag} built from keyword tokens and appended.",
    ),
    "MappedImage": (
        "Reference",
        "`<MappedImageName>`",
        "Image collection lookup; pointer stored.",
    ),
    "MappedImageList": (
        "Reference",
        "`<MappedImage>`",
        "MappedImage looked up by name. Each line adds another entry.",
    ),
    "MissionObjectiveTagList": (
        "Text",
        "`<tag> ...`",
        "Every token is added to the list of mission objective tags; the bonus variant marks "
        "them as bonus objectives.",
    ),
    "ModelConditionFlagsList": (
        "Flag set",
        "`<ModelConditionFlag> ...`",
        "ModelConditionFlags parsed into a temporary and pushed: one alternative set per "
        "occurrence.",
    ),
    "ModelName": (
        "Text",
        "`<model> [ExtraMesh Yes|No]`",
        "Model name pushed onto the state's model list at a fixed offset; the list is cleared "
        "first unless ExtraMesh is Yes.",
    ),
    "ModelWithProbability": (
        "Scalar",
        "`<model> [prob <1..100>]`",
        "{AsciiString model, Int probability} pushed; probability outside 1..100 throws.",
    ),
    "ModifierCategory": (
        "Enumeration",
        "`<ModifierCategory>`",
        "Index over names (must be 1..14) stored as dword; else \"Invalid Category encountered "
        "by ModifierList::Category\".",
    ),
    "ModifierCategoryFlags": (
        "Flag set",
        "`<ModifierCategory> ... | +X -Y | NONE`",
        "BitFlags (4 dwords), tokens resolved against names (NONE, LEADERSHIP, FORMATION, "
        "SPELL, WEAPON, STRUCTURE, LEVEL, BUFF,...); +/- add/remove, NONE clears.",
    ),
    "ModuleTag": (
        "Reference",
        "`<ModuleTag>`",
        "Finds the module with that tag in the object template and removes it; throws "
        "\"RemoveModule %s was not found for %s.\"; only valid in MODULEPARSE_NORMAL mode. "
        "Each line adds another entry.",
    ),
    "Money": (
        "Scalar",
        "`<int>`",
        "Int deposited into a Money object.",
    ),
    "NameKey": (
        "Text",
        "`<name> or \"<name>\"`",
        "Optionally quoted string -> NameKey via TheNameKeyGenerator, stored as dword.",
    ),
    "NameKeyList": (
        "Reference",
        "`<award> ...`",
        "NameKeyList, each key validated against AwardSystemManager awards; throws \"The Award "
        "%s does not exist\". Each line adds another entry.",
    ),
    "NotificationType": (
        "Reference",
        "`<name>`",
        "Creates a notification-type object for the token and files it in a name-keyed map "
        "when not already present; no nested block is parsed here. Each line adds another "
        "entry.",
    ),
    "ObjectCount": (
        "Scalar",
        "`<ObjectTemplate> [<int count=1>]`",
        "{AsciiString name, Int count} pushed onto a list at a fixed offset (field offset "
        "ignored); count defaults to 1.",
    ),
    "ObjectPercent": (
        "Scalar",
        "`<ObjectTemplate> <percent>`",
        "Map NameKey(template) -> Real (percent/100) entry. Each line adds another entry.",
    ),
    "ObjectPrerequisite": (
        "Reference",
        "`<ObjectTemplate> ...`",
        "One prerequisite whose names are all the tokens (OR-group), appended.",
    ),
    "ObjectPriority": (
        "Scalar",
        "`<ObjectTemplate> <int>`",
        "Template resolved; when found, {template name, Int priority} pushed; unknown "
        "templates dropped.",
    ),
    "ObjectReal": (
        "Scalar",
        "`<ObjectTemplate> <real>`",
        "{AsciiString, Real} pushed onto a vector at a fixed offset (field offset ignored).",
    ),
    "ObjectVeterancy": (
        "Scalar",
        "`<ObjectTemplate> <VeterancyLevel>`",
        "Map NameKey(template) -> veterancy index. Each line adds another entry.",
    ),
    "Obsolete": (
        "Text",
        "`(value ignored)`",
        "Takes no value and stores nothing; the engine only writes a debug-log line saying the "
        "keyword is obsolete.",
    ),
    "OCLList": (
        "Reference",
        "`<ObjectCreationList> ...`",
        "Every token resolved in the OCL store and the pointer push_back.",
    ),
    "ParticleSystemByVeterancy": (
        "Scalar",
        "`<VeterancyLevel> <ParticleSystem>`",
        "ParticleSystem stored in slot [veterancy]. Each line adds another entry.",
    ),
    "ParticleSystemModule": (
        "Reference",
        "`<ModuleType>` followed by a sub-block",
        "Picks a particle-system module by its type name (`Update = DefaultUpdate`) and reads "
        "that module's sub-block up to `End`. Its keywords depend on the module type, which "
        "the engine registers at startup, so they are not listed here.",
    ),
    "Probability": (
        "Scalar",
        "`<int numerator> <separator> <int denominator>`",
        "Token 1 -> Int numerator at field, token 2 ignored, token 3 -> Int denominator (>= 1) "
        "at field+4.",
    ),
    "QueryEntry": (
        "Scalar",
        "`<int> <KindOfFilter ...>`",
        "{Int, KindOfFilter} appended to a fixed in-place array of at most 6 (\"iniParseQuery: "
        "Too many queries\").",
    ),
    "QuotedAsciiString": (
        "Text",
        "`<text> or \"<text with spaces>\"`",
        "Optionally quoted string assigned to the AsciiString field.",
    ),
    "QuotedAsciiStringList": (
        "Text",
        "`<text> or \"<text with spaces>\"`",
        "Optionally quoted string. Each line adds another entry.",
    ),
    "RandomTexture": (
        "Scalar",
        "`<newTexture> <int> <oldTexture>`",
        "Entry keyed by oldTexture found or created; newTexture appended to its candidate "
        "list; Int stored at a fixed offset.",
    ),
    "RandomVariable": (
        "Scalar",
        "`<real min> <real max> [CONSTANT|UNIFORM|GAUSSIAN|TRIANGULAR|LOW_BIAS|HIGH_BIAS]`",
        "{Real low, Real high, distribution index} set.",
    ),
    "RealList": (
        "Scalar",
        "`<real> <real> ...`",
        "Reals into a fixed array at field, index = position, at most 17.",
    ),
    "RealOrFCurve": (
        "Scalar",
        "`<real> | FCurve newline Key = ... End`",
        "A plain \"%f\" value is stored as a constant curve; keyword FCurve opens a nested key "
        "block; anything else throws \"'FCurve' expected\".",
    ),
    "RealPerMPSlot": (
        "Scalar",
        "`MP1 <real> MP2 <real> ... MP8 <real> (any subset)`",
        "A value per multiplayer slot, written into a fixed GameData array; slots left out "
        "keep theirs. The field table offset is not used.",
    ),
    "RealRange": (
        "Scalar",
        "`<real min> <real max>`",
        "Two Reals at field / field+4, swapped so min <= max.",
    ),
    "RealSequence": (
        "Scalar",
        "`<real> <real> ...`",
        "Every Real on the line is appended to a list.",
    ),
    "RegionBonus": (
        "Enumeration",
        "`<name> | None`",
        "Index over names stored as dword.",
    ),
    "RegionNameList": (
        "Reference",
        "`<Region> ...`",
        "One connection entry per token, pushed.",
    ),
    "RGBAColorInt": (
        "Scalar",
        "`R:<0-255> G:<0-255> B:<0-255> [A:<0-255>]`",
        "Four Int channels (alpha defaults to 255), range-checked 0..255, not scaled.",
    ),
    "RGBColorSigned": (
        "Scalar",
        "`R:<-255..255> G:<-255..255> B:<-255..255>`",
        "Three channels range-checked -255..255, * 1/255 into three Reals.",
    ),
    "ScienceInt": (
        "Scalar",
        "`<Science> <int>`",
        "{ScienceType, Int} pair push_back.",
    ),
    "ScienceOCL": (
        "Scalar",
        "`<Science> <ObjectCreationList>`",
        "{ScienceType, OCL*} pair push_back.",
    ),
    "SciencePrerequisite": (
        "Reference",
        "`<Science>`",
        "Prerequisite with one science appended.",
    ),
    "SciencePrerequisiteList": (
        "Reference",
        "`<Science> [OR <Science>] ... | None`",
        "Vector reset, sciences resolved and push_back; \"OR\" groups alternatives; None clears.",
    ),
    "ScienceTypeList": (
        "Reference",
        "`<Science> ... | None`",
        "Vector cleared, every token resolved via TheScienceStore and push_back; None clears.",
    ),
    "ScriptText": (
        "Text",
        "`newline <script lines> ... <end token>`",
        "Following raw lines concatenated until a line equal to the block end token, assigned "
        "to an AsciiString.",
    ),
    "SecondsToMs": (
        "Scalar",
        "`<seconds>`",
        "Real * 1000 truncated (ftol) -> Int milliseconds.",
    ),
    "ShadowType": (
        "Flag set",
        "`<shadow flag> ...`",
        "BitFlags16; when nonzero allocates a 40-byte shadow-info at a fixed offset and stores "
        "the type in it.",
    ),
    "SpawnerTrigger": (
        "Scalar",
        "`UNIT <name> NEWMODELCONDITION <ModelConditionFlags> FX <FXList> "
        "SPAWNERMODELCONDITION <ModelConditionFlags> (keywords in any order)`",
        "Trigger struct (unit name, two ModelConditionFlags, FXList*) appended to a vector; "
        "capacity-checked (\"parseUpgradeCreation: Too many triggers\").",
    ),
    "SpecialPowerTemplateList": (
        "Reference",
        "`<SpecialPower> ...`",
        "Each name is resolved against the special power store and appended to a list.",
    ),
    "StanceList": (
        "Flag set",
        "`<Battle|Aggressive|HoldGround|Porcupine|HoldGroundMoving> ...`",
        "Each token indexed against names (index 1..5 accepted) and push_back.",
    ),
    "TacticalAITargetList": (
        "Flag set",
        "`<ENEMY_STRUCTURE|DEFENSIVE|OPPORTUNITY|EXPANSION|TARGETLESS> ...`",
        "Every token indexed against names (5) and push_back; throws \"invalid AITARGET\".",
    ),
    "TemplateFilter": (
        "Scalar",
        "`<ObjectTemplate> <KindOfFilter ...>`",
        "{AsciiString, ObjectFilter} pushed onto a list at field.",
    ),
    "TextureSwap": (
        "Scalar",
        "`<oldTexture> <newTexture>`",
        "Two AsciiStrings pushed as a pair.",
    ),
    "ThingTemplate": (
        "Reference",
        "`<ObjectTemplate> | None`",
        "ThingFactory::findTemplate pointer stored; None -> null; unknown name logs "
        "\"ThingTemplate %s not found!\" and stores null.",
    ),
    "ThreatThreshold": (
        "Scalar",
        "`<uint>`",
        "{Int mode = -1 (above), UnsignedInt value} at field / field+4.",
    ),
    "TimeOfDayTexture": (
        "Scalar",
        "`<oldTexture> <TimeOfDay> <int> <newTexture>`",
        "{AsciiString, TimeOfDay index, Int, AsciiString} pushed at a fixed offset.",
    ),
    "UpgradeCreationTrigger": (
        "Scalar",
        "`<UpgradeName> <ObjectName> <uint>`",
        "{AsciiString upgrade, AsciiString object, UnsignedInt} pushed into 12-byte-entry "
        "vector at a fixed offset; at most 4 (\"iniParseQuery: Too many triggers\").",
    ),
    "UpgradeHeuristic": (
        "Enumeration",
        "`<AI_UPGRADEHEURISTIC_*>`",
        "Optionally quoted name indexed against names (8 entries), dword.",
    ),
    "UpgradeNameList": (
        "Reference",
        "`<upgrade> ...`",
        "AsciiStringList; each name (optional leading '@' handled) inserted into the "
        "bling-upgrade map.",
    ),
    "UpgradePrerequisite": (
        "Reference",
        "`<Upgrade>`",
        "Prerequisite with one upgrade appended.",
    ),
    "UpgradeTemplateList": (
        "Reference",
        "`<Upgrade> ...`",
        "Every token -> NameKey -> UpgradeCenter findUpgradeByKey; only player upgrades "
        "([upgrade+4]==0) push_back.",
    ),
    "UpgradeWithDelay": (
        "Reference",
        "`<Upgrade> [Delay <ms>]`",
        "Allocates {Upgrade*, frames} at a fixed offset: upgrade via "
        "UpgradeCenter::findUpgrade, optional Delay ms -> frames.",
    ),
    "WeaponBonus": (
        "Scalar",
        "`<WeaponBonusCondition> <WeaponBonusField> <percent>`",
        "Percent/100 written to the bonus table [condition][field]. Each line adds another entry.",
    ),
    "WeaponName": (
        "Reference",
        "`<WeaponTemplate>`",
        "Name validated in the weapon store; when found stored as AsciiString at instance+8 "
        "(field offset ignored); unknown names silently ignored.",
    ),
    "WeaponSlotAngle": (
        "Scalar",
        "`<WeaponSlot> <angle in degrees>`",
        "The slot token picks which weapon slot the angle applies to; the angle is stored in "
        "radians.",
    ),
    "WeaponSlotBitFlags": (
        "Scalar",
        "`<WeaponSlot> <FROM_PLAYER|FROM_SCRIPT|FROM_AI> ...`",
        "The slot token picks which weapon slot the flags that follow apply to.",
    ),
    "WeaponSlotBone": (
        "Scalar",
        "`<WeaponSlot> <bone>`",
        "Bone name (quoted string, lower-cased) stored in the per-weapon-slot bone array.",
    ),
    "WeaponSlotFlags": (
        "Flag set",
        "`<WeaponSlot> ...`",
        "Each slot named turns on its bit in the mask.",
    ),
    "WeaponSlotKindOf": (
        "Scalar",
        "`<WeaponSlot> <KindOf> ...`",
        "The slot token picks which weapon slot the KindOf set that follows applies to.",
    ),
    "WeaponSlotModelConditions": (
        "Scalar",
        "`<WeaponSlot> <ModelConditionFlag> ...`",
        "Slot index selects the per-slot ModelConditionFlags.",
    ),
    "WeaponSlotReal": (
        "Scalar",
        "`<WeaponSlot> <real>`",
        "The slot token picks which weapon slot the value applies to.",
    ),
    "WeaponSlotWeapon": (
        "Scalar",
        "`<WeaponSlot> <WeaponTemplate>`",
        "Slot index selects the per-slot WeaponTemplate*.",
    ),
    "WeaponTemplateList": (
        "Reference",
        "`<WeaponTemplate> ...`",
        "Every token resolved in the weapon store, pointer push_back.",
    ),
    "WeatherTexture": (
        "Scalar",
        "`<NORMAL|SNOWY> <texture>`",
        "{weather index, AsciiString} pushed.",
    ),
    "WeightedSoundList": (
        "Scalar",
        "`<file>[:<weight>] ...`",
        "Every token split at the last ':'; {AsciiString name, weight (atoi, default 1000)} "
        "pushed; total weight accumulated.",
    ),
    "WindowTransition": (
        "Reference",
        "`<TransitionName>`",
        "Token -> NameKey resolved by TheTransitionHandler; result stored via virtual call.",
    ),
    "WorldToMapMatch": (
        "Scalar",
        "`World <name> RTS <name> ...`",
        "Entry allocated and push_back; sub-keys World/RTS parsed; throws on unknown sub-key.",
    ),
}

CATEGORY_ORDER = [
    "Scalar",
    "Text",
    "Enumeration",
    "Flag set",
    "Reference",
    "Sub-block",
    "Unidentified",
]

# How a typed-in value is checked. Types not listed here take their kind from their
# category, so every enum checks its tokens and every reference checks nothing.
VALUE_KINDS = {
    "Bool": "bool",
    "Int": "int",
    "Int8": "int8",
    "UInt8": "uint8",
    "UInt16": "uint16",
    "UnsignedInt": "uint32",
    "Money": "int",
    "BoolBit": "bool",
    "SecondsToMs": "real",
    "DurationByte": "real",
    "DurationUInt16": "real",
    "AccelerationReal": "real",
    "HealthFraction": "real",
    "RGBAColorInt": "rgba",
    "RGBColorSigned": "rgb",
    "Real": "real",
    "Percent": "percent",
    "Duration": "real",
    "DurationReal": "real",
    "AngleReal": "real",
    "VelocityReal": "real",
    "AngularVelocityReal": "real",
    "PositiveReal": "positive",
    "NonNegativeReal": "nonneg",
    "NonPositiveReal": "nonpos",
    "Coord3D": "coord3",
    "Coord2D": "coord2",
    "Coord2DInt": "coord2int",
    "RGBColor": "rgb",
    "RGBAColor": "rgba",
    "ModelConditionFlagRange": "pair",
    "AngleFXList": "text",
    "Module": "module",
}

# Token lists the binary does not name and `sage_ini` does not model, named here after
# what the module that reads them calls them.
ENUM_NAMES = {
    "0x00db0e7c": "StructureCollapsePhase",
    "0x00db0ed0": "RubbleRisePhase",
    "0x00db0f20": "StructureTopplePhase",
    "0x00d9e6bc": "LodLevel",
}


def annotation_target(annotation: Any, depth: int = 0) -> Optional[str]:
    """The table a `sage_ini` annotation points at, through whatever wraps it.

    The model says what the engine's parse function cannot: that this string names an
    upgrade, or that one names an object. It says it in several shapes - a `Reference`
    marker, the model class itself, or either of those inside a list, a nullable or a
    union - and all of them lead back to one table key.
    """
    if annotation is None or depth > 5:
        return None
    for meta in getattr(annotation, "__metadata__", ()):
        if isinstance(meta, sage_types.Reference):
            return meta.key
    key = getattr(annotation, "key", None)
    if isinstance(key, str):
        return key
    for attr in ("element", "inner"):
        found = annotation_target(getattr(annotation, attr, None), depth + 1)
        if found:
            return found
    for attr in ("types", "element_types", "values"):
        options = getattr(annotation, attr, None)
        if not isinstance(options, (list, tuple)):
            continue  # a class's own `values` is a method, not a set of alternatives
        for option in options:
            found = annotation_target(option, depth + 1)
            if found:
                return found
    return None


def sage_annotations(name: str) -> dict[str, Any]:
    """Every field `sage_ini` models for a block or module, base classes included."""
    cls = SAGE_REGISTRY.get(name)
    if cls is None:
        return {}
    merged: dict[str, Any] = {}
    for base in reversed(getattr(cls, "__mro__", ())):
        merged.update(getattr(base, "__annotations__", {}))
    return merged


def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def prose(text: str) -> str:
    """Escape a written description, turning its `backticks` into code spans."""
    parts = esc(text).split("`")
    return "".join(p if i % 2 == 0 else f"<code>{p}</code>" for i, p in enumerate(parts))


def slug(name: str) -> str:
    """A filename-safe, case-insensitive-unique key for a module name."""
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name)


class Reference:
    """The extracted data, with everything the pages ask of it worked out once."""

    def __init__(self, modules: list[dict], types: dict) -> None:
        self.modules = [m for m in modules if m.get("name")]
        self.name_tables: dict[str, list[str]] = types["name_tables"]
        self.lookup_tables: dict[str, list] = types["lookup_tables"]
        self.blocks: dict[str, dict] = types["blocks"]
        self.ini_blocks: dict[str, dict] = types.get("ini_blocks", {})
        self.type_tables: dict[str, str] = types["types"]
        self.engine_enums: dict[str, str] = types["enums"]
        self.sage_enums = self._sage_enums()
        self.enums = self._name_enums()
        self.field_types = self._field_types()
        self.targets = self._sage_targets()

    @staticmethod
    def _sage_enums() -> dict[str, tuple[list[str], Optional[str]]]:
        """`sage_ini`'s enums: members and docstring, for cross-checking the engine's.

        Only a docstring written on the class itself counts - inherited ones describe
        `Enum`, not the list.
        """
        out = {}
        for name, cls in vars(sage_enums).items():
            if (
                isinstance(cls, type)
                and issubclass(cls, sage_enums.BFMEEnum)
                and cls.__members__
                and not name.startswith("_")
                and name not in ("BFMEEnum", "CaseInsensitiveEnum", "FakeEnum")
            ):
                doc = cls.__dict__.get("__doc__")
                out[name] = (list(cls.__members__), inspect.cleandoc(doc) if doc else None)
        return out

    def _match_sage_enum(self, members: list[str]) -> Optional[str]:
        """The `sage_ini` enum that models the same list, by how far the two overlap.

        Overlap rather than position: the two agree on what the list holds far more
        often than on the order, and where they disagree on order the engine's is the
        one that counts.
        """
        mine = {m.upper() for m in members}
        best, score = None, 0.0
        for name, (theirs, _doc) in self.sage_enums.items():
            if len(theirs) < 2:
                continue
            other = {t.upper() for t in theirs}
            ratio = len(mine & other) / len(mine | other)
            if ratio > score:
                best, score = name, ratio
        return best if score >= 0.7 else None

    def _name_enums(self) -> dict[str, dict]:
        """Every name array, keyed by the name this site gives it.

        The engine's own flag types name themselves. A list that a field's parse table
        points at has no name in the binary, so it takes the matching `sage_ini` enum's
        name, or failing that the field that uses it. The same list is often compiled
        into several arrays; those are one enum here, listed under every address it
        was found at.
        """
        by_table: dict[str, str] = {va: name for name, va in self.engine_enums.items()}
        users: dict[str, list[tuple[str, str, str]]] = {}
        from_type: dict[str, str] = {}
        owned = [("m", m["name"], m["fields"]) for m in self.modules] + [
            ("b", n, blk["fields"]) for n, blk in self.ini_blocks.items()
        ]
        for page_dir, owner, fields in owned:
            for f in fields:
                if f.get("userdata"):
                    users.setdefault(f["userdata"], []).append((page_dir, owner, f["name"]))
                    kind = TYPE_DOCS.get(f["type"], ("", "", ""))[0]
                    if f["type"].endswith("Flags") and f["type"] != "BitFlags":
                        from_type.setdefault(f["userdata"], f["type"][: -len("Flags")])
                    elif kind == "Enumeration" and f["type"] not in ("Enum", "LookupList"):
                        from_type.setdefault(f["userdata"], f["type"])
        enums: dict[str, dict] = {}
        by_members: dict[tuple[str, ...], str] = {}
        for va, members in sorted(
            self.name_tables.items(), key=lambda kv: (kv[0] not in by_table, kv[0])
        ):
            key = tuple(members)
            if key in by_members:
                enum = enums[by_members[key]]
                enum["tables"].append(va)
                enum["users"] = sorted(set(enum["users"]) | set(users.get(va, [])))
                continue
            name = by_table.get(va)
            matched = self._match_sage_enum(members)
            if not name:
                name = (
                    matched
                    or ENUM_NAMES.get(va)
                    or from_type.get(va)
                    or users.get(va, [("", "", "Unnamed")])[0][2] + "Values"
                )
            while name in enums:
                name += "'"
            doc = self.sage_enums.get(matched or name, ([], None))[1]
            by_members[key] = name
            enums[name] = {
                "members": members,
                "table": va,
                "tables": [va],
                "kind": "index",
                "sage_ini": matched,
                "doc": doc,
                "users": sorted(users.get(va, [])),
                "engine_named": va in by_table,
            }
        for va, pairs in sorted(self.lookup_tables.items()):
            members = [p[0] for p in pairs]
            matched = self._match_sage_enum(members)
            name = matched or (users.get(va, [("", "", "Unnamed")])[0][2] + "Values")
            enums[name] = {
                "members": members,
                "values": [p[1] for p in pairs],
                "table": va,
                "tables": [va],
                "kind": "lookup",
                "sage_ini": matched,
                "doc": self.sage_enums.get(matched or name, ([], None))[1],
                "users": sorted(users.get(va, [])),
                "engine_named": False,
            }
        return enums

    def enum_for_type(self, type_name: str) -> Optional[str]:
        """The enum page a type's tokens come from, if the type owns a fixed list."""
        va = self.type_tables.get(type_name)
        if not va:
            return None
        for name, enum in self.enums.items():
            if enum["table"] == va and enum["engine_named"]:
                return name
        return None

    def enum_for_field(self, field: dict) -> Optional[str]:
        """The enum page a field's own token list lives on."""
        va = field.get("userdata")
        if not va:
            return self.enum_for_type(field["type"])
        for name, enum in self.enums.items():
            if va in enum["tables"]:
                return name
        return None

    def _field_types(self) -> dict[str, list[tuple[str, str, str]]]:
        """type name -> the (page, owner, field) triples that use it."""
        out: dict[str, list[tuple[str, str, str]]] = {}
        for m in self.modules:
            for f in m["fields"]:
                out.setdefault(f["type"], []).append(("m", m["name"], f["name"]))
        for name, blk in self.ini_blocks.items():
            for f in blk["fields"]:
                out.setdefault(f["type"], []).append(("b", name, f["name"]))
        return out

    def _sage_targets(self) -> dict[str, dict[str, tuple[str, bool]]]:
        """owner -> field -> (the block its value names, whether that block has a page).

        Straight from `sage_ini`'s model rather than from the binary: the engine parses
        these fields as plain strings and never says what the string has to match.
        """
        by_key: dict[str, list[str]] = {}
        for keyword, cls in SAGE_REGISTRY.items():
            key = getattr(cls, "key", None)
            if isinstance(key, str) and not keyword.startswith("_"):
                by_key.setdefault(key, []).append(keyword)
        named: dict[str, str] = {}
        for key, keywords in by_key.items():
            here = [k for k in keywords if k in self.ini_blocks]
            named[key] = min(here or keywords, key=lambda k: (len(k), k))

        out: dict[str, dict[str, tuple[str, bool]]] = {}
        owners = [m["name"] for m in self.modules] + list(self.ini_blocks)
        for owner in owners:
            for field, annotation in sage_annotations(owner).items():
                key = annotation_target(annotation)
                block = named.get(key or "")
                if block:
                    out.setdefault(owner, {})[field] = (block, block in self.ini_blocks)
        return out

    def target_of(self, owner: str, field: dict) -> Optional[tuple[str, bool]]:
        """What a field's value names, where the engine's own type does not say."""
        if self.type_category(field["type"]) not in ("Text", "Unidentified"):
            return None
        return self.targets.get(owner, {}).get(field["name"])

    def category(self, module: str) -> str:
        for suffix, label, _blurb in CATEGORIES:
            if suffix and module.endswith(suffix):
                return label
        return "Other"

    def type_category(self, type_name: str) -> str:
        if type_name in TYPE_DOCS:
            return TYPE_DOCS[type_name][0]
        if type_name in self.blocks:
            return "Sub-block"
        return "Unidentified"


def page(
    ref: Reference,
    title: str,
    body: str,
    base: str = "",
    subtitle: str = "",
    active: str = "",
    extra: str = "",
) -> str:
    """The shell every page shares: head, sidebar mount point, content."""
    return f"""<!DOCTYPE html>
<html lang="en" data-base="{base}" data-active="{esc(active)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} - SAGE module reference</title>
<link rel="stylesheet" href="{base}assets/wiki.css">
</head>
<body>
<a class="skip" href="#content">Skip to content</a>
<button id="menu" aria-label="Toggle navigation">Menu</button>
<nav id="sidebar" aria-label="Site">
  <a class="brand" href="{base}index.html">SAGE<span>module reference</span></a>
  <div class="searchbox">
    <input id="q" type="search" placeholder="Search modules, fields, types" autocomplete="off"
           aria-label="Search" spellcheck="false">
    <kbd>/</kbd>
  </div>
  <div id="results" hidden></div>
  <div id="nav"></div>
</nav>
<main id="content">
<header class="pagehead">
  <h1>{esc(title)}</h1>
  {f'<p class="sub">{subtitle}</p>' if subtitle else ""}
</header>
{body}
<footer>
  Generated from <code>game.dat</code> build {ENGINE_BUILD} by
  <code>sage_patch/scripts/build_wiki.py</code>. Field names, offsets, types and
  defaults are read out of the binary, not transcribed from another reference.
</footer>
</main>
<script src="{base}assets/data.js"></script>
{f'<script src="{base}assets/{extra}"></script>' if extra else ""}
<script src="{base}assets/wiki.js"></script>
</body>
</html>
"""


def type_tip(ref: Reference, type_name: str) -> str:
    """The one-line explanation that hangs off a type wherever it is mentioned."""
    if type_name.startswith("0x"):
        return "Parse function not identified, so neither the syntax nor the stored form is known."
    if type_name in TYPE_DOCS:
        _cat, writes, detail = TYPE_DOCS[type_name]
        return f"You write {writes.replace('`', '')}. {detail}".replace("`", "")
    block = ref.blocks.get(type_name)
    if block:
        words = block["keywords"]
        listed = ", ".join(words[:8]) + (", ..." if len(words) > 8 else "")
        return "A nested block ended by End." + (f" Keywords: {listed}." if words else "")
    return type_name


def type_link(ref: Reference, type_name: str, base: str) -> str:
    """A type cell: the type, linked to whatever page explains it, tip in tow."""
    tip = esc(type_tip(ref, type_name))
    if type_name.startswith("0x"):
        return (
            f'<a class="t t-unknown" href="{base}types.html#unidentified" '
            f'data-tip="{tip}" aria-label="{tip}">{esc(type_name)}</a>'
        )
    cat = ref.type_category(type_name)
    cls = "t-" + cat.split()[0].lower()
    return (
        f'<a class="t {cls}" href="{base}types.html#{esc(slug(type_name))}" '
        f'data-tip="{tip}" aria-label="{tip}">{esc(type_name)}</a>'
    )


def field_kind(ref: Reference, type_name: str) -> str:
    """The shape a value has to have, which is all the page checks a typed value against.

    Coarser than the type: every duration, angle and speed is a number to the field that
    takes it, and the checks worth making from a browser are the ones the engine's own
    parser makes - is it a number, is it in range, is that token a member of the list.
    """
    if type_name in VALUE_KINDS:
        return VALUE_KINDS[type_name]
    if type_name.startswith("Moment"):
        return "keyed"
    cat = ref.type_category(type_name)
    if cat == "Enumeration":
        return "enum"
    if cat == "Flag set":
        return "flags"
    if cat == "Sub-block":
        return "block"
    return "text"


def value_control(ref: Reference, field: dict, enum: Optional[str], kind: str, default: str) -> str:
    """The control the value column offers for a field.

    A type with a short, closed answer gets picked rather than typed: a bool is one of
    two words, and a KindOf set is any number of names from a list the engine fixes.
    The KindOf options are filled in from the shipped member list rather than written
    into every page, since there are 222 of them.
    """
    common = (
        f' data-field="{esc(field["name"])}" data-kind="{kind}"'
        f' data-default="{esc(default)}"' + (f' data-enum="{esc(enum)}"' if enum else "")
    )
    label = f' aria-label="Value for {esc(field["name"])}"'
    if kind == "bool":
        shown = default or "unset"
        return (
            f'<select class="fieldval"{label}{common}>'
            f'<option value="">default: {esc(shown)}</option>'
            f"<option>Yes</option><option>No</option></select>"
        )
    if field["type"] in ("KindOfFlags", "KindOfFilter"):
        # a filter tests a mask rather than setting one, so its tokens carry a sign
        sign = "+" if field["type"] == "KindOfFilter" else ""
        return (
            f'<select class="fieldval" multiple size="4"{label}{common}'
            f' data-members="KindOf" data-sign="{sign}"></select>'
        )
    return (
        f'<input class="fieldval" type="text" spellcheck="false"{label}'
        f' placeholder="{esc(default)}"{common}>'
    )


def target_link(ref: Reference, owner: str, field: dict, base: str) -> str:
    """What the value names, where the engine's type only says "string"."""
    found = ref.target_of(owner, field)
    if not found:
        return ""
    block, has_page = found
    tip = esc(
        f"sage_ini models this as naming a {block}; the engine parses it as a "
        f"plain string and does not say what it has to match"
    )
    if has_page:
        return (
            f' <a class="reflink" href="{base}b/{esc(slug(block))}.html" '
            f'data-tip="{tip}">&rarr; {esc(block)}</a>'
        )
    return f' <span class="reflink" data-tip="{tip}">&rarr; {esc(block)}</span>'


def field_rows(
    ref: Reference, owner: str, fields: list[dict], base: str, origins: bool = False
) -> str:
    rows = []
    for f in fields:
        enum = ref.enum_for_field(f)
        extra = ""
        if enum:
            extra = f' <a class="enumref" href="{base}enums.html#{esc(slug(enum))}">{esc(enum)}</a>'
        extra += target_link(ref, owner, f, base)
        if f["default"] == EMPTY:
            default = (
                '<span class="none" title="no value: an empty string or list, '
                'or no reference">empty</span>'
            )
        elif f["default"] is not None:
            default = f"<code>{esc(f['default'])}</code>"
        else:
            default = (
                '<span class="none" title="not recoverable by constant tracking">-</span>'
            )
        kind = field_kind(ref, f["type"])
        control = value_control(ref, f, enum, kind, writable_default(f))
        rows.append(
            f'<tr id="{esc(slug(f["name"]))}">'
            f'<td class="fname"><code>{esc(f["name"])}</code></td>'
            f"<td>{type_link(ref, f['type'], base)}{extra}</td>"
            f'<td class="num">{default}</td>'
            f"{origin_cell(f) if origins else ''}"
            f'<td class="val">{control}<span class="why"></span></td></tr>'
        )
    return "\n".join(rows)


def origin_cell(field: dict) -> str:
    """Which class in the chain declares a keyword, on a module that inherits some.

    The engine searches the base's table first, so a keyword declared in both is the
    base's - offset, type and default included - and the derived one's line is dead.
    The link is to a sibling page: only modules ever carry this column, and they all
    live in one directory.
    """
    if not field.get("inherited"):
        return '<td class="from own">its own</td>'
    parent = field.get("inherited_from")
    if not parent:
        return '<td class="from">a base class</td>'
    return (
        f'<td class="from"><a href="{esc(slug(parent))}.html"><code>{esc(parent)}</code></a></td>'
    )


def writable_default(field: dict) -> str:
    """The default as a value you could write after the `=`, or "" when there is none."""
    default = field["default"]
    return "" if default is None or default == EMPTY else default


def ini_skeleton(header: str, fields: list[dict]) -> str:
    """The block with every keyword at the value it holds when left out.

    A keyword whose default could not be recovered, or is empty, is left out rather
    than written blank, since a blank line is not something you could paste.
    """
    written = [f for f in fields if writable_default(f)]
    width = max((len(f["name"]) for f in written), default=0)
    lines = [header]
    lines += [f"  {f['name']:<{width}} = {f['default']}" for f in written]
    lines.append("End")
    return esc("\n".join(lines))


def schema_page(
    ref: Reference,
    name: str,
    fields: list[dict],
    header: str,
    lead: str,
    base: str,
    facts: str = "",
) -> str:
    """The page shared by a module and an INI block: its fields, and a block to paste."""
    origins = any(f.get("inherited") for f in fields)
    column = "<th>Declared in</th>" if origins else ""
    unknown = [f for f in fields if f["type"].startswith("0x")]
    warn = ""
    if unknown:
        names = ", ".join(f"<code>{esc(f['name'])}</code>" for f in unknown)
        verb = "uses" if len(unknown) == 1 else "use"
        warn = (
            f'<p class="note">{len(unknown)} field'
            f"{'' if len(unknown) == 1 else 's'} here {verb} a parse function that "
            f"has not been identified, so the type column shows its address: "
            f"{names}.</p>"
        )
    body = f"""
{facts}
{warn}
<table class="fields sortable" data-module="{esc(header)}">
<thead><tr><th>Field</th><th>Type</th><th>Default</th>{column}<th>Value</th></tr></thead>
<tbody>
{field_rows(ref, name, fields, base, origins)}
</tbody>
</table>
<div class="inirow">
<details class="skeleton">
<summary>INI block, every keyword at its default</summary>
<p class="note">The engine writes these values before it reads the block, so a keyword
you leave out behaves exactly as if you had written the line below. Fill in the value
column above and the line follows. Keywords whose default could not be recovered are
left out until you give them a value. {lead}</p>
<pre><code id="ini">{ini_skeleton(header, fields)}</code></pre>
</details>
<button class="copyini" type="button">Copy INI</button>
</div>
"""
    return page(ref, name, body, base=base, active=name)


def inherits_fact(module: dict) -> list[str]:
    """What the module takes from its base classes, counted per class.

    A module's own keywords are usually the smaller half: `OCLSpecialPower` declares
    five and inherits thirty-five, and a page that showed only the five would describe
    a module nobody could write a working block for.
    """
    inherited = [f for f in module["fields"] if f.get("inherited")]
    if not inherited:
        return []
    per: dict[str, int] = {}
    for f in inherited:
        per[f.get("inherited_from") or ""] = per.get(f.get("inherited_from") or "", 0) + 1
    parts = []
    for parent, count in sorted(per.items(), key=lambda kv: (-kv[1], kv[0])):
        where = (
            f'<a href="{esc(slug(parent))}.html"><code>{esc(parent)}</code></a>'
            if parent
            else "an unregistered base class"
        )
        parts.append(f"{count} from {where}")
    own = len(module["fields"]) - len(inherited)
    return [f"<div><dt>Fields</dt><dd>{own} of its own, {', '.join(parts)}</dd></div>"]


def module_page(ref: Reference, module: dict) -> str:
    mask = module.get("interface_mask") or ""
    items = []
    if mask.startswith("0x") or mask.isdigit():
        items.append(f"<div><dt>Interface mask</dt><dd><code>{esc(mask)}</code></dd></div>")
    items += inherits_fact(module)
    facts = f'<dl class="facts">{"".join(items)}</dl>' if items else ""
    lead = (
        "The leading keyword (<code>Behavior</code>, <code>Draw</code>, "
        "<code>Body</code>, ...) depends on which interface you are attaching."
    )
    return schema_page(
        ref, module["name"], module["fields"], f"{module['name']} ModuleTag_01", lead, "../", facts
    )


def block_page(ref: Reference, name: str, block: dict) -> str:
    shared = sorted(
        n
        for n, other in ref.ini_blocks.items()
        if other["parse_fn"] == block["parse_fn"] and n != name
    )
    facts = ""
    if shared:
        links = ", ".join(
            f'<a href="{esc(slug(n))}.html"><code>{esc(n)}</code></a>' for n in shared
        )
        facts = f'<p class="note">The same schema is read for {links}.</p>'
    if block.get("file_set"):
        lead = (
            f"Every top-level block in the <code>{esc(name)}</code> INI files is read with "
            "this schema, whatever keyword it starts with."
        )
    elif block.get("top_level"):
        lead = (
            "A named block takes its name after the keyword "
            f"(<code>{esc(name)} SomeName</code>); the settings blocks that exist once "
            "take none."
        )
    else:
        lead = (
            "A nested block: the INI loader does not take it at the top of a file, only "
            "inside another block."
        )
    return schema_page(ref, name, block["fields"], name, lead, "../", facts)


def modules_page(ref: Reference) -> str:
    parts = []
    for _suffix, label, blurb in CATEGORIES:
        group = [m for m in ref.modules if ref.category(m["name"]) == label]
        if not group:
            continue
        items = "\n".join(
            f'<li><a href="m/{esc(slug(m["name"]))}.html">{esc(m["name"])}</a>'
            f'<span class="count">{len(m["fields"])}</span></li>'
            for m in group
        )
        parts.append(
            f'<section id="{esc(slug(label))}"><h2>{esc(label)} '
            f'<span class="count">{len(group)}</span></h2>'
            f'<p class="note">{blurb}</p><ul class="modgrid">{items}</ul></section>'
        )
    return page(
        ref,
        "All modules",
        "\n".join(parts),
        subtitle=f"{len(ref.modules)} modules registered by the engine, "
        f"grouped by the interface they attach to",
        active="modules",
    )


def blocks_page(ref: Reference) -> str:
    items = "\n".join(
        f'<li><a href="b/{esc(slug(name))}.html">{esc(name)}</a>'
        f'<span class="count">{len(blk["fields"])}</span></li>'
        for name, blk in sorted(ref.ini_blocks.items(), key=lambda kv: kv[0].lower())
    )
    fields = sum(len(b["fields"]) for b in ref.ini_blocks.values())
    body = f"""<p class="lead">The block types the INI loader dispatches on, each read
through a field table of its own - the same machinery a module's data goes through.
`Object`, `Weapon`, `Locomotor`, `GameData` and the rest live here, alongside the
nested blocks that only appear inside another.</p>
<ul class="modgrid">{items}</ul>"""
    return page(
        ref,
        "All blocks",
        body.replace("`", ""),
        subtitle=f"{len(ref.ini_blocks)} block types, {fields} fields",
        active="blocks",
    )


def types_page(ref: Reference) -> str:
    sections = []
    for cat in CATEGORY_ORDER:
        entries = []
        if cat == "Sub-block":
            names = sorted(ref.blocks)
        elif cat == "Unidentified":
            names = sorted({t for t in ref.field_types if t.startswith("0x")})
        else:
            names = sorted(n for n, d in TYPE_DOCS.items() if d[0] == cat)
        for name in names:
            users = ref.field_types.get(name, [])
            examples = ", ".join(
                f'<a href="{d}/{esc(slug(owner))}.html#{esc(slug(fld))}">'
                f"<code>{esc(owner)}.{esc(fld)}</code></a>"
                for d, owner, fld in users[:3]
            )
            more = f" and {len(users) - 3} more" if len(users) > 3 else ""
            table = ""
            if cat == "Sub-block":
                block = ref.blocks[name]
                words = block["keywords"]
                writes = "a nested block ended by <code>End</code>"
                if block.get("fields"):
                    detail = (
                        "The engine reads it through its own field table, so its "
                        "keywords carry types and offsets of their own."
                    )
                    rows = "\n".join(
                        f'<tr><td class="fname"><code>{esc(f["name"])}</code></td>'
                        f"<td>{type_link(ref, f['type'], '')}</td></tr>"
                        for f in block["fields"]
                    )
                    table = (
                        f'<table class="fields sub"><thead><tr><th>Keyword</th>'
                        f"<th>Type</th></tr></thead><tbody>{rows}"
                        f"</tbody></table>"
                    )
                elif words:
                    detail = (
                        "The parser reads the block by hand; the keywords it "
                        "compares against are "
                        + ", ".join(f"<code>{esc(w)}</code>" for w in words)
                        + "."
                    )
                else:
                    detail = (
                        "A nested block whose keywords the extractor could not "
                        "recover: the parser neither uses a field table nor "
                        "compares against plain strings."
                    )
            elif cat == "Unidentified":
                writes = "unknown"
                detail = (
                    "The parse function at this address has not been identified, so "
                    "neither the syntax nor the stored form is documented here."
                )
            else:
                _cat, writes, detail = TYPE_DOCS[name]
                writes, detail = prose(writes), prose(detail)
            enum = ref.enum_for_type(name)
            enum_link = (
                f'<p class="tokens">Tokens come from '
                f'<a href="enums.html#{esc(slug(enum))}">{esc(enum)}</a>.</p>'
                if enum
                else ""
            )
            entries.append(f"""
<article class="type" id="{esc(slug(name))}">
  <h3><code>{esc(name)}</code><span class="count">{len(users)} field{"" if len(users) == 1 else "s"}</span></h3>
  <p class="writes"><span class="label">You write</span> {writes}</p>
  <p>{detail}</p>
  {enum_link}
  {f'<p class="uses"><span class="label">Used by</span> {examples}{more}</p>' if examples else ""}
  {table}
</article>""")
        if entries:
            anchor = "unidentified" if cat == "Unidentified" else slug(cat)
            sections.append(
                f'<section id="{anchor}"><h2>{esc(cat)} types</h2>'
                + "\n".join(entries)
                + "</section>"
            )
    intro = """<p class="lead">A field's type is its parse function: the code the engine
runs on the rest of the line. Everything below was read out of those functions - the
constant a real is scaled by, the range it is checked against, the array a token is
looked up in.</p>"""
    return page(
        ref,
        "Types",
        intro + "\n".join(sections),
        subtitle="What each field type accepts and how the engine stores it",
        active="types",
    )


def enums_page(ref: Reference) -> str:
    sections = []
    for name, enum in sorted(ref.enums.items(), key=lambda kv: kv[0].lower()):
        members = enum["members"]
        values = enum.get("values")
        cells = "\n".join(
            f'<li><span class="idx">{values[i] if values else i}</span><code>{esc(m)}</code></li>'
            for i, m in enumerate(members)
        )
        users = enum["users"]
        used = ", ".join(
            f'<a href="{d}/{esc(slug(owner))}.html#{esc(slug(fld))}">'
            f"<code>{esc(owner)}.{esc(fld)}</code></a>"
            for d, owner, fld in users[:4]
        )
        more = f" and {len(users) - 4} more" if len(users) > 4 else ""
        cross = ""
        if enum["sage_ini"]:
            theirs = ref.sage_enums[enum["sage_ini"]][0]
            if len(theirs) == len(members):
                cross = (
                    f"Agrees with <code>sage_ini</code>'s "
                    f"<code>{esc(enum['sage_ini'])}</code>, member for member."
                )
            elif len(theirs) < len(members):
                cross = (
                    f"<code>sage_ini</code>'s <code>{esc(enum['sage_ini'])}</code> "
                    f"stops at {len(theirs)}; the engine list continues to "
                    f"{len(members)}."
                )
            else:
                cross = (
                    f"<code>sage_ini</code>'s <code>{esc(enum['sage_ini'])}</code> "
                    f"carries {len(theirs)} names against the engine's "
                    f"{len(members)}."
                )
        kind = (
            "token to value lookup" if enum["kind"] == "lookup" else "index list, first member is 0"
        )
        if not enum["engine_named"] and not enum["sage_ini"]:
            cross += (
                " The binary does not name the list, so the name above is this "
                "site's, taken from the field that reads it."
            )
        where = ", ".join(f"<code>{esc(va)}</code>" for va in enum["tables"])
        copies = (
            f" The same list is compiled in at {len(enum['tables'])} addresses."
            if len(enum["tables"]) > 1
            else ""
        )
        sections.append(f"""
<article class="enum" id="{esc(slug(name))}">
  <h2>{esc(name)}<span class="count">{len(members)} members</span></h2>
  {f"<p>{esc(enum['doc'].splitlines()[0])}</p>" if enum["doc"] else ""}
  <p class="note">Read from the engine's own name array at {where} ({kind}).{copies}
  {cross}</p>
  {f'<p class="uses"><span class="label">Used by</span> {used}{more}</p>' if used else ""}
  <ol class="members">{cells}</ol>
</article>""")
    intro = """<p class="lead">These are the engine's token lists, read from the arrays
its parsers resolve names against, so a member's position here is the value the engine
stores. Where <code>sage_ini</code> models the same list, the two are compared.</p>"""
    return page(
        ref,
        "Enumerations",
        intro + "\n".join(sections),
        subtitle=f"{len(ref.enums)} token lists recovered from the binary",
        active="enums",
    )


def index_page(ref: Reference) -> str:
    groups = "\n".join(
        f'<a class="group" href="modules.html#{slug(label)}"><b>{esc(label)}</b>'
        f"<span>{sum(1 for m in ref.modules if ref.category(m['name']) == label)}</span></a>"
        for _s, label, _b in CATEGORIES
        if any(ref.category(m["name"]) == label for m in ref.modules)
    )
    blocks = len(ref.ini_blocks)
    body = f"""
<p class="lead">Every module the ROTWK engine registers and every block type its INI
loader dispatches on, with the keywords each accepts, the type of every keyword and the
value it holds when you leave the line out - read out of the binary rather than
transcribed.</p>

<section>
<h2>Start here</h2>
<div class="tiles">
  <a class="tile" href="modules.html"><b>Modules</b>
    <span>All {len(ref.modules)} modules, grouped by the interface they attach to. Each
    page lists its fields with types and defaults, and an INI block you can paste with
    every keyword at its default.</span></a>
  <a class="tile" href="types.html"><b>Types</b>
    <span>What each type accepts and how the engine stores it - which reals are scaled
    into radians or logic frames, which strings are references into another INI file.</span></a>
  <a class="tile" href="blocks.html"><b>Blocks</b>
    <span>The {blocks} block types the INI loader dispatches on - <code>Object</code>,
    <code>Weapon</code>, <code>Locomotor</code>, <code>GameData</code> and the rest -
    read through field tables of their own.</span></a>
  <a class="tile" href="enums.html"><b>Enumerations</b>
    <span>The engine's token lists in engine order, read from the arrays its parsers
    resolve names against, cross-checked against <code>sage_ini</code>.</span></a>
  <a class="tile" href="check.html"><b>Check a block</b>
    <span>Paste INI and have every keyword checked against these tables: unknown
    keywords, values of the wrong shape, tokens that are not in the list, and lines
    that only repeat a default.</span></a>
</div>
</section>

<section>
<h2>Browse by group</h2>
<div class="groups">{groups}</div>
</section>

<section>
<h2>How to read a module page</h2>
<ul class="legend">
  <li><b>Field</b> - the INI keyword, spelled as the engine's parse table spells it.</li>
  <li><b>Type</b> - the parse function behind the keyword. Hover it for what it accepts,
      click it for the full entry. A second, smaller link appears when the field's tokens
      come from a fixed list, and a <span class="reflink">&rarr; Block</span> when
      <code>sage_ini</code> knows what the string has to name - the engine itself parses
      those as plain strings and says nothing about what they match.</li>
  <li><b>Default</b> - what the module's constructor writes before the block is read,
      so it is the value in force when the keyword is absent. A <span class="none">-</span>
      means constant tracking could not resolve the write, which in practice means an
      empty string or container rather than an unset field.</li>
</ul>
</section>

<section>
<h2>Where this comes from</h2>
<p>The engine registers each module with a factory that builds a 16-byte-stride table of
<code>{{keyword, parseFn, userData, offset}}</code>. Those tables give the field names,
their offsets and their parse functions. Defaults come from tracking constants through
each module's <code>ModuleData</code> constructor; enum members come from the name arrays
the parsers resolve tokens against; sub-block schemas come from the keywords their
parsers compare against.</p>
<p class="note">Read from <code>game.dat</code> build {ENGINE_BUILD}. Numbers are what
this build does - another build can differ. Nothing here is transcribed from another
reference, so where this site and another disagree, both are worth re-checking.</p>
</section>
"""
    return page(
        ref,
        "SAGE module reference",
        body,
        subtitle="Modules, fields, types and compiled-in defaults, read out of the ROTWK engine",
        active="index",
    )


def field_data(ref: Reference) -> str:
    """Every schema the checker validates against: modules, INI blocks, sub-blocks.

    One entry per field - the kind to check it against, the token list if it has one,
    and the default - so a pasted block can be told what the engine would make of it.
    """
    schemas: dict[str, dict[str, list]] = {}

    def add(name: str, fields: list[dict]) -> None:
        entry = schemas.setdefault(name, {})
        for f in fields:
            found = ref.target_of(name, f) if "default" in f else None
            entry.setdefault(
                f["name"],
                [
                    field_kind(ref, f["type"]),
                    ref.enum_for_field(f),
                    f.get("default"),
                    f["type"],
                    found[0] if found else None,
                ],
            )

    for module in ref.modules:
        add(module["name"], module["fields"])
    for name, blk in ref.ini_blocks.items():
        add(name, blk["fields"])
    for name, blk in ref.blocks.items():
        if blk.get("fields"):
            add(name, blk["fields"])
        else:
            entry = schemas.setdefault(name, {})
            for word in blk["keywords"]:
                entry.setdefault(word, ["text", None, None, "AsciiString"])
    data = {
        "schemas": schemas,
        "modules": sorted(m["name"] for m in ref.modules),
        "blocks": sorted(ref.ini_blocks),
    }
    return "window.WIKI_FIELDS = " + json.dumps(data, separators=(",", ":")) + ";\n"


def check_page(ref: Reference) -> str:
    body = """
<p class="lead">Paste a block - an <code>Object</code>, a <code>Weapon</code>, a
<code>Behavior = ...</code> module, anything with an <code>End</code> - and every
keyword in it is checked against what the engine's own parser accepts: is the keyword
one this block has, is the value the shape its type wants, is that token in the list.
Lines that only repeat a compiled-in default are called out too, since they do nothing.</p>
<p class="note">Nothing leaves the page: the schemas are already loaded, and the check
runs here.</p>
<div class="checkbar">
  <button id="checkrun" type="button">Check</button>
  <button id="checkclear" class="ghost" type="button">Clear</button>
  <span id="checksummary"></span>
</div>
<textarea id="checkinput" spellcheck="false" rows="14"
  placeholder="Behavior = ProductionUpdate ModuleTag_01
  MaxQueueEntries = 20
  GiveNoXP = Yes
End"></textarea>
<div id="checkout"></div>
"""
    return page(
        ref,
        "Check a block",
        body,
        subtitle="Validate a pasted INI block against the engine's field tables",
        active="check",
        extra="fields.js",
    )


def search_data(ref: Reference) -> str:
    """The sidebar tree and the search index, as a script so `file://` works."""
    modules = [
        {"n": m["name"], "c": ref.category(m["name"]), "f": [f["name"] for f in m["fields"]]}
        for m in ref.modules
    ]
    blocks = [
        {"n": name, "f": [f["name"] for f in blk["fields"]]}
        for name, blk in sorted(ref.ini_blocks.items(), key=lambda kv: kv[0].lower())
    ]
    types = [[t, ref.type_category(t)] for t in sorted(ref.field_types) if not t.startswith("0x")]
    data = {
        "modules": modules,
        "blocks": blocks,
        "groups": [label for _s, label, _b in CATEGORIES],
        "types": types,
        "enums": sorted(ref.enums),
        "members": {name: enum["members"] for name, enum in sorted(ref.enums.items())},
        "pages": [
            ["index.html", "Home"],
            ["modules.html", "All modules"],
            ["blocks.html", "All blocks"],
            ["types.html", "Types"],
            ["enums.html", "Enumerations"],
            ["check.html", "Check a block"],
        ],
    }
    return "window.WIKI = " + json.dumps(data, separators=(",", ":")) + ";\n"


# The reference is one site over every module, with no faction anywhere in it, so it takes the
# default skin. `sage_utils.webtheme` holds the palette the aggregate pages and the replay
# browser read too - the three are published side by side and used to disagree about what a
# panel is.
CSS = webtheme.wiki_tokens(webtheme.STEEL) + _asset("wiki.css")

JS = _asset("wiki.js")


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def build(out_dir: str) -> int:
    """Write the whole site, returning the number of pages written."""
    with open(MODULE_JSON, encoding="utf-8") as fh:
        modules = json.load(fh)
    with open(TYPE_JSON, encoding="utf-8") as fh:
        types = json.load(fh)
    ref = Reference(modules, types)

    for stale in ("m", "b"):
        if os.path.isdir(os.path.join(out_dir, stale)):
            shutil.rmtree(os.path.join(out_dir, stale))
    write(os.path.join(out_dir, "assets", "wiki.css"), CSS.lstrip())
    write(os.path.join(out_dir, "assets", "wiki.js"), JS.lstrip())
    write(os.path.join(out_dir, "assets", "data.js"), search_data(ref))
    write(os.path.join(out_dir, "index.html"), index_page(ref))
    write(os.path.join(out_dir, "modules.html"), modules_page(ref))
    write(os.path.join(out_dir, "blocks.html"), blocks_page(ref))
    write(os.path.join(out_dir, "assets", "fields.js"), field_data(ref))
    write(os.path.join(out_dir, "check.html"), check_page(ref))
    write(os.path.join(out_dir, "types.html"), types_page(ref))
    write(os.path.join(out_dir, "enums.html"), enums_page(ref))
    for module in ref.modules:
        write(os.path.join(out_dir, "m", slug(module["name"]) + ".html"), module_page(ref, module))
    for name, block in ref.ini_blocks.items():
        write(os.path.join(out_dir, "b", slug(name) + ".html"), block_page(ref, name, block))
    return len(ref.modules) + len(ref.ini_blocks) + 6


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=DEFAULT_OUT, help="output directory (default: build/wiki)")
    args = ap.parse_args()
    pages = build(args.out)
    print("wrote %d pages to %s" % (pages, os.path.normpath(args.out)))


if __name__ == "__main__":
    main()
