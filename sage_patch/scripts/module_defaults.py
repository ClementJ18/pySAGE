"""Recover every engine module, its INI fields and their compiled-in defaults.

The engine registers each behaviour/draw/update module through one
`addModule(instanceFactory, moduleDataFactory, ..., &name, interfaceMask)` call.
The ModuleData factory allocates the struct, runs its constructor and hands back a
`buildFieldParse` function, which appends one or more 16-byte-stride INI field
tables of `{const char *name, parseFn, userData, offset}`.

Field names and offsets come from those tables. A field whose INI keyword is absent
from a `.ini` block keeps whatever the ModuleData constructor wrote at its offset, and
that is read two ways: by running the constructor in unicorn, twice over differently
poisoned uninitialised state so that only what does not depend on it is believed, and
by linear constant-tracking through its instructions, which also reads the string
literals emulation cannot build. The two are compared, and any disagreement printed.

A field's type is its parse function. Those are identified from their bodies: the
scaling constant a real parser applies, the range the engine checks and complains
about, the lookup array a token parser resolves against, or the keywords a sub-block
parser accepts.

Usage:
    python module_defaults.py <game.dat> [--json out.json] [--markdown out.md]
                                         [--enums out.json]
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import struct
from typing import Any, Iterator, Optional

import pefile
from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from unicorn import (
    UC_ARCH_X86,
    UC_HOOK_BLOCK,
    UC_HOOK_CODE,
    UC_HOOK_MEM_UNMAPPED,
    UC_MODE_32,
    UC_PROT_READ,
    UC_PROT_WRITE,
    Uc,
    UcError,
)
from unicorn.x86_const import (
    UC_X86_REG_DS,
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_ECX,
    UC_X86_REG_EIP,
    UC_X86_REG_ES,
    UC_X86_REG_ESP,
    UC_X86_REG_FS,
    UC_X86_REG_GDTR,
    UC_X86_REG_SS,
)

__all__ = [
    "Image",
    "ModuleInfo",
    "FieldInfo",
    "extract",
    "block_keywords",
    "lookup_table",
    "name_table",
    "field_table_of",
    "ini_blocks",
    "BLOCK_TYPES",
    "NAME_TABLES",
    "PARSE_TYPES",
    "TYPE_TABLES",
]

ADD_MODULE = 0x6570FE
# A block keyword is CamelCase; the field table its parser owns is what really decides.
INI_KEYWORD = re.compile(r"^[A-Z][A-Za-z0-9_]{2,40}$")
INI_BLOCK_MIN_FIELDS = 2
EH_PROLOG = 0xA3CEF0
OPERATOR_NEW = (0x42F6E0, 0x42F6A0)
STR_ASSIGN = (0x4374E0, 0x4050E6, 0x436030, 0x40611E)
STR_COPY = 0x436030
STR_RELEASE = 0x435D50
HELPERS = set(OPERATOR_NEW) | set(STR_ASSIGN) | {EH_PROLOG, 0x42DBBD, STR_RELEASE}
# `MultiIniFieldParse::add`, the one call inside a `buildFieldParse` that takes a table
# rather than contributing one. Every other call there is a base class's own.
MULTI_FIELD_ADD = 0x42B8D7
# INI::initFromINI(instance, fieldTable) and its buildFieldParse variant, the two ways a
# block parser hands a block to the reader
INI_PARSE_FIELDS, INI_PARSE_MULTI = 0x42DB80, 0x42DBBD
INI_NEXT_TOKEN = (0x42DC9F, 0x42DD73)
INI_NEXT_TOKEN_OR_NULL = 0x42DBF5
# INI::registerBlock(keyword, parser): a block type added at startup, not in a static table
INI_REGISTER_BLOCK = 0x73B0E8
CXX_THROW = 0xA3CE04
# The deepest chain the engine actually has is four (`CitadelSlaughterHordeContain`);
# the cap is a guard against following a call that is not a base class at all.
MAX_BASE_DEPTH = 8

# Parse functions identified from their bodies and from the fields that use them.
# Anything absent renders as the raw address.
PARSE_TYPES = {
    0x0042E558: "Bool",
    0x0042ED00: "Real",
    0x0042EE5E: "AsciiString",
    0x0042EC5E: "Int",
    0x0073A302: "FXList",
    0x0042EEFA: "Percent",
    0x0076392F: "KindOfFilter",
    0x0073B217: "AudioEventRTS",
    0x0042E59E: "AsciiStringList",
    0x0042E956: "Enum",
    0x0042EED6: "AsciiStringList",
    0x006564E7: "KindOfFlags",
    0x0073AE79: "WeaponTemplate",
    0x0042F247: "Coord3D",
    0x0042F298: "Coord2D",
    0x0042F2FA: "Coord2DInt",
    0x0066F603: "UpgradeMask",
    0x005DE588: "EvaEvent",
    0x008BDBB5: "FXList",
    0x008BDC21: "ObjectCreationList",
    0x008BDC8C: "ParticleSystem",
    0x0088A4AC: "FXList",
    0x0088A55B: "ObjectCreationList",
    0x0088A60A: "ParticleSystem",
    0x0042ECB2: "UnsignedInt",
    0x0073A368: "ObjectCreationList",
    0x0042E840: "BitFlags",
    0x007B1E5C: "ObjectStatusFlags",
    0x0073A5C9: "DamageTypeFlags",
    # Reals that scale or range-check what they parse. The constant the parser
    # multiplies by names the conversion (0.0174533 = pi/180, so degrees in and
    # radians out), and where there is no constant the engine's own complaint
    # string names the range it enforces ("expected > 0").
    0x0042EE15: "AngleReal",
    0x0073A2D6: "AngularVelocityReal",
    0x0073A4B6: "VelocityReal",
    0x0073A403: "DurationReal",
    0x0073A429: "Duration",
    0x0042ED1C: "PositiveReal",
    0x0042ED6F: "NonNegativeReal",
    0x0042EDC2: "NonPositiveReal",
    # Integers narrower than a dword: the parser range-checks, then stores through
    # a byte or word move.
    0x0042EB2A: "Int8",
    0x0042EB75: "UInt8",
    0x0042EC11: "UInt16",
    # Colours: three or four channels scaled by 1/255 into floats.
    0x0042EF99: "RGBColor",
    0x0042F13E: "RGBAColor",
    # Tokens resolved against a name array, either the field table's userData
    # (`LookupList`) or a static array owned by the flag type.
    0x0042E9B7: "LookupList",
    0x0073A68A: "DeathTypeFlags",
    0x004B8C21: "ModelConditionFlags",
    0x00869F22: "ModelConditionFlag",
    0x008514ED: "ModelConditionFlag",
    0x006C9951: "WeaponSetFlags",
    0x00866FF0: "ObjectStatusFlags",
    0x008D239B: "SpecialPowerTrigger",
    0x00992693: "SpecialPowerAIType",
    0x008E09CE: "EmotionType",
    0x008966F9: "WeatherType",
    # Names looked up in another INI subsystem's template store.
    0x0073AF89: "UpgradeTemplate",
    0x0073B22F: "SpecialPowerTemplate",
    0x0073AFE3: "ScienceType",
    0x0073AECB: "ParticleSystem",
    0x0073B549: "FXList",
    0x0073ACEF: "AudioEventRTS",
    0x0073AD07: "AudioEventRTS",
    # A moment token followed by the thing to play at it. Which moments are on offer
    # differs between modules, so the list is attached per parse function below.
    0x0086158D: "MomentFXList",
    0x008A8A1D: "MomentFXList",
    0x008A818F: "MomentFXList",
    0x008615FE: "MomentOCL",
    0x008A8A82: "MomentOCL",
    0x008A81F2: "MomentOCL",
    0x008A9AC9: "MomentOCL",
    0x00861903: "MomentSound",
    0x00861672: "MomentWeapon",
    0x008A9B2B: "AngleFXList",
    0x008A1700: "DisabledTypeFlags",
    0x008BA71A: "ModelConditionFlagRange",
    0x0086C30A: "MeleeBehavior",
    # `Behavior = <module> <tag>` and its siblings: the keyword that attaches a module
    # to an object, and the geometry primitive an object's shape is built from.
    0x0073F24D: "Module",
    0x00AD4040: "GeometryType",
    # Parsers with a syntax of their own, each read from its body: what it scans, what it
    # resolves a token against, how it stores the result. `build_wiki.py` documents each.
    0x0073A4DC: "AccelerationReal",
    0x008ED575: "AIKindOf",
    0x008ED5C4: "AIKindOfList",
    0x004B65FE: "AngleReal",
    0x004B661E: "AngleReal",
    0x005D86F1: "ArmorCoefficient",
    0x0073D99B: "ArmorSetFlags",
    0x004B2687: "AsciiString",
    0x00621411: "AsciiString",
    0x00888B65: "AsciiString",
    0x00AD16B0: "AsciiString",
    0x00806264: "AttributeModifier",
    0x0073BB7D: "AudioEventRTSList",
    0x00860324: "AudioEventRTSList",
    0x00836A37: "AutoResolveArmor",
    0x00829153: "AutoResolveBody",
    0x00829A85: "AutoResolveCombatChain",
    0x00828A07: "AutoResolveLeadership",
    0x008287E3: "AutoResolveUnitTypeFlags",
    0x0082A029: "AutoResolveWeapon",
    0x006D9FDC: "BitFlags",
    0x0042EF5A: "BitFlags16",
    0x008678EB: "BoneConditionState",
    0x004C232A: "BoneNameKey",
    0x004C236F: "BoneNameKey",
    0x004B26AF: "Bool",
    0x0075CAA4: "Bool",
    0x0093B44C: "Bool",
    0x0093B46D: "Bool",
    0x0093B48F: "Bool",
    0x00AD16F0: "Bool",
    0x00AD1730: "Bool",
    0x00AD2B30: "Bool",
    0x0042E574: "BoolBit",
    0x005E3183: "BoolOrInt",
    0x0085B11B: "BridgeFXEntry",
    0x0085B1C5: "BridgeOCLEntry",
    0x0042E976: "ByteEnum",
    0x0079BD2F: "CastleUnpack",
    0x006CB608: "ClearNuggets",
    0x0080C9E1: "CommandButton",
    0x0075CB37: "CommandType",
    0x00AD3D30: "ContactPoint",
    0x00AD14C0: "Coord2D",
    0x0042F2D2: "Coord2DList",
    0x006CF43F: "Coord2DList",
    0x00AD1770: "Coord3D",
    0x00825DC2: "CrowdResponse",
    0x0073AF3F: "DamageFX",
    0x0076246E: "DamageFXDuration",
    0x0076238A: "DamageFXFXList",
    0x007623FC: "DamageFXFXList",
    0x00762311: "DamageFXReal",
    0x008612E7: "DeathFlags",
    0x0073B071: "DurationByte",
    0x006C9D99: "DurationRange",
    0x006C9E7A: "DurationRange",
    0x00899C7D: "EatObjectEntry",
    0x004C30BD: "EmbedPortal",
    0x008E0A11: "EmotionAIType",
    0x008E0CA9: "EmotionNuggetRef",
    0x0073B6D5: "EnumList",
    0x0073B7CB: "EnumList",
    0x005DE179: "EvaEventList",
    0x0079CA81: "FactionDecal",
    0x0061C0A5: "FactionFlags",
    0x0093B931: "FactionNameList",
    0x009A7CB8: "FactionNameList",
    0x0062145C: "FontDesc",
    0x00778C93: "FontDesc",
    0x004C425B: "FXEvent",
    0x004C4284: "FXEvent",
    0x006C9CDC: "FXList",
    0x0068A2B8: "FXListAtBone",
    0x00890CD9: "FXListAtBone",
    0x006C9C9A: "FXListByVeterancy",
    0x0064501B: "GameDifficulty",
    0x00AD4310: "GeometryOther",
    0x00AD3BC0: "GeometryType",
    0x0073D0FD: "HealthFraction",
    0x005DC399: "Int",
    0x008CEF70: "Int",
    0x008CF53A: "Int",
    0x008D000E: "Int",
    0x0093B4B1: "Int",
    0x0042EC7A: "IntList",
    0x005FD599: "IntList",
    0x0086DF0B: "IntList",
    0x009015CE: "IntList",
    0x00641911: "IntPair",
    0x0042F382: "IntRange",
    0x0086DED1: "IntSet",
    0x007EEC77: "LargeGroupAudioKeys",
    0x006CF475: "LinearTarget",
    0x006E398A: "LivingWorldPlayerTypeList",
    0x007FCE85: "LivingWorldSoundFlags",
    0x0073B192: "LocalizedString",
    0x0073D3E0: "LocalizedString",
    0x005DF31D: "LookupList",
    0x004B65BA: "LowercaseAsciiString",
    0x004C3236: "LuaEvent",
    0x0073A9C2: "MappedImage",
    0x00688E67: "ModelConditionFlags",
    0x008E092B: "ModelConditionFlags",
    0x004CEF06: "ModelConditionFlagsList",
    0x004C21EE: "ModelName",
    0x004C33C8: "ModelWithProbability",
    0x00804DEA: "ModifierCategory",
    0x0089F32D: "ModifierCategoryFlags",
    0x0073E716: "ModuleTag",
    0x005FC8DE: "Money",
    0x00548990: "NameKey",
    0x0075CAA9: "NameKey",
    0x005489D4: "NameKeyList",
    0x0061A4FF: "NameKeyList",
    0x0061A5B5: "NameKeyList",
    0x00621F44: "NotificationType",
    0x00653381: "ObjectCount",
    0x0079CA18: "ObjectCount",
    0x0086AF0A: "ObjectCount",
    0x0087EC0B: "ObjectCount",
    0x008A3633: "ObjectCount",
    0x005FD78C: "ObjectPercent",
    0x005FD7D9: "ObjectPercent",
    0x0074040D: "ObjectPrerequisite",
    0x007013C2: "ObjectPriority",
    0x00719B59: "ObjectReal",
    0x0075E9AF: "ObjectReal",
    0x008C81CD: "ObjectReal",
    0x005FD841: "ObjectVeterancy",
    0x0089ECD7: "Obsolete",
    0x008601EB: "OCLList",
    0x008CD3A8: "OCLList",
    0x004BCE37: "ParticleSysBone",
    0x004BCE4E: "ParticleSysBone",
    0x006C9D46: "ParticleSystem",
    0x006C9D04: "ParticleSystemByVeterancy",
    0x005D875A: "Percent",
    0x005DC3C7: "Percent",
    0x008BA26F: "Percent",
    0x006A926A: "Probability",
    0x0085D29C: "QueryEntry",
    0x0042EE9A: "QuotedAsciiString",
    0x005EA54B: "QuotedAsciiString",
    0x007EFB84: "QuotedAsciiString",
    0x008C7ACC: "QuotedAsciiString",
    0x008CC228: "QuotedAsciiString",
    0x004C7C56: "RandomTexture",
    0x0073A396: "RandomVariable",
    0x004B265F: "Real",
    0x00AD2B60: "Real",
    0x00AD2BC0: "Real",
    0x00AD2C10: "Real",
    0x008ED4AA: "RealList",
    0x0073B723: "RealOrFCurve",
    0x00642182: "RealPerMPSlot",
    0x006422D2: "RealPerMPSlot",
    0x00642408: "RealPerMPSlot",
    0x0064253E: "RealPerMPSlot",
    0x00642674: "RealPerMPSlot",
    0x0042F334: "RealRange",
    0x004B262A: "RealRange",
    0x007F2A14: "RegionBonus",
    0x007F4A9D: "RegionNameList",
    0x006213CF: "RGBAColor",
    0x0042F03F: "RGBAColorInt",
    0x005DF33E: "RGBColorSigned",
    0x008C6B1E: "ScienceInt",
    0x008C7A8F: "ScienceOCL",
    0x00740483: "SciencePrerequisite",
    0x0073BCBF: "SciencePrerequisiteList",
    0x0073B4A0: "ScienceTypeList",
    0x0042DB44: "ScriptText",
    0x0042EE37: "SecondsToMs",
    0x004B92D3: "ShadowType",
    0x007A7B81: "SpawnerTrigger",
    0x0075D4D0: "StanceList",
    0x006C6B0D: "TacticalAITargetList",
    0x0088494C: "TemplateFilter",
    0x004C2EEC: "TextureSwap",
    0x004C3321: "TextureSwap",
    0x008B9420: "TextureSwap",
    0x0073AD1F: "ThingTemplate",
    0x008E08DC: "ThreatThreshold",
    0x008E0906: "ThreatThreshold",
    0x004C42A8: "TimeOfDayTexture",
    0x0086BA2C: "UpgradeCreationTrigger",
    0x008E02AF: "UpgradeHeuristic",
    0x0061EB52: "UpgradeNameList",
    0x007404E0: "UpgradePrerequisite",
    0x006897B9: "UpgradeTemplateList",
    0x0073B304: "UpgradeTemplateList",
    0x007F3646: "UpgradeTemplateList",
    0x007F36A9: "UpgradeTemplateList",
    0x008050D3: "UpgradeWithDelay",
    0x006CB559: "WeaponBonus",
    0x006CB5AB: "WeaponBonus",
    0x008BEDF8: "WeaponName",
    0x006C7FE6: "WeaponSlotBitFlags",
    0x004C317B: "WeaponSlotBone",
    0x006C9961: "WeaponSlotKindOf",
    0x006C9992: "WeaponSlotKindOf",
    0x006C9589: "WeaponSlotModelConditions",
    0x006C7FB3: "WeaponSlotWeapon",
    0x0086022E: "WeaponTemplateList",
    0x004CF066: "WeatherTexture",
    0x004CFEB9: "WeatherTexture",
    0x005DA4CD: "WeightedSoundList",
    0x005DC241: "WindowTransition",
    0x007F3C5C: "WorldToMapMatch",
    0x0073B4FF: "SpecialPowerTemplateList",
    0x00836792: "MissionObjectiveTagList",
    0x008367EB: "MissionObjectiveTagList",
    0x005DA4F7: "AudioEventRTSList",
    0x008E7E95: "Coord2DList",
    0x006FEC18: "ScienceType",
    0x008DC24C: "WeaponSlotAngle",
    0x008DC27F: "WeaponSlotReal",
    0x008DC20F: "WeaponSlotFlags",
    0x005DF2DB: "LookupList",
    0x0063F3BF: "Ignored",
    0x0061542B: "QuotedAsciiStringList",
    0x0062472D: "ButtonTooltipMapping",
    0x00618B95: "FontSizeSubstitution",
    0x00834FBF: "FormationTemplate",
    0x005F7BDB: "ParticleSystemModule",
    0x005F7C81: "ParticleSystemModule",
    0x005F7CEF: "ParticleSystemModule",
    0x005F7D5D: "ParticleSystemModule",
    0x005F7DCB: "ParticleSystemModule",
    0x005F7E39: "ParticleSystemModule",
    0x005F7EA7: "ParticleSystemModule",
    0x005F7F15: "ParticleSystemModule",
    0x005FA052: "ParticleSystemModule",
    0x0073A46F: "DurationUInt16",
    0x006D8347: "UnsignedInt",
    0x006D8442: "MappedImageList",
    0x006D8468: "ImageSequence",
    0x0069C374: "DecalTexture",
}

# The lists those types resolve their tokens against, where the array is reached from
# inside the parse function rather than from the field table's userData.
PARSER_TABLES = {
    0x0086158D: 0x00DAE770,
    0x008615FE: 0x00DAE770,
    0x00861903: 0x00DAE770,
    0x00861672: 0x00DAE770,
    0x008A8A1D: 0x00DB0ED0,
    0x008A8A82: 0x00DB0ED0,
    0x008A818F: 0x00DB0E7C,
    0x008A81F2: 0x00DB0E7C,
    0x008A9AC9: 0x00DB0F20,
    0x008A1700: 0x00DAD904,
    0x008BA71A: 0x00D9FAD8,
    0x0086C30A: 0x00DAEB2C,
    0x00AD4040: 0x00DC1C38,
    0x008D239B: 0x00DB4B08,
    0x004BCE37: 0x00D99E70,
    0x004BCE4E: 0x00D99E70,
    0x004C317B: 0x00DA12E4,
    0x004C42A8: 0x00DA3A68,
    0x004CEF06: 0x00D9FAD8,
    0x004CF066: 0x00DA3A84,
    0x004CFEB9: 0x00DA3A84,
    0x005D86F1: 0x00D9DA08,
    0x005DF31D: 0x00BF3350,
    0x005FD841: 0x00D9F5E4,
    0x0061C0A5: 0x00DA3AC0,
    0x00688E67: 0x00D9FAD8,
    0x006C6B0D: 0x00DA1208,
    0x006C7FB3: 0x00DA12E4,
    0x006C7FE6: 0x00DA1314,
    0x006C9589: 0x00DA12E4,
    0x006C9961: 0x00DA12E4,
    0x006C9992: 0x00DA12E4,
    0x006C9C9A: 0x00D9F5E4,
    0x006C9D04: 0x00D9F5E4,
    0x006CB559: 0x00DA1740,
    0x006CB5AB: 0x00DA1740,
    0x006D9FDC: 0x00DA1FE4,
    0x0073A396: 0x00DA1CBC,
    0x0073D99B: 0x00D9FA80,
    0x0075CB37: 0x00DA4D10,
    0x0075D4D0: 0x00C53660,
    0x00762311: 0x00DA5110,
    0x0076238A: 0x00DA5110,
    0x007623FC: 0x00DA5110,
    0x0076246E: 0x00DA5110,
    0x007A7B81: 0x00D9FAD8,
    0x007F2A14: 0x00C4CBD0,
    0x007FCE85: 0x00DA6958,
    0x00804DEA: 0x00D9FA40,
    0x00806264: 0x00DA6D28,
    0x008287E3: 0x00DADBE4,
    0x008612E7: 0x00D9FAD8,
    0x008678EB: 0x00D9FAD8,
    0x0089F32D: 0x00D9FA40,
    0x008E02AF: 0x00DB4F44,
    0x008E092B: 0x00D9FAD8,
    0x008E0A11: 0x00D9F9EC,
    0x008ED575: 0x00DB55C8,
    0x008ED5C4: 0x00DB55C8,
    0x00AD3BC0: 0x00DC1C38,
    0x00AD4310: 0x00DC1C38,
    0x008DC20F: 0x00DA12E4,
    0x008DC24C: 0x00DA12E4,
    0x008DC27F: 0x00DA12E4,
    0x005DF2DB: 0x00BF3234,
}

# Sub-block parsers shared by more than one keyword, so the block's name cannot be
# taken from the keyword that uses it. Single-user blocks are named automatically.
BLOCK_TYPES = {
    0x00851412: "AnimAndDuration",
    0x00881681: "RiderInfo",
    0x0073A74B: "OpacityEnvelope",
    0x008C3F1F: "DamageCreationList",
    0x004C8840: "AnimationState",
    0x004C800E: "ModelConditionState",
    0x008D07CF: "ModelConditionAudio",
    # Nested blocks named after what they hold rather than after a keyword taking them.
    0x0073BEC3: "AddModule",
    0x0082FD19: "AIEconomyAssignment",
    0x0082FD30: "AIWallNodeAssignment",
    0x004C7A89: "Animation",
    0x0073FAC4: "ArmorSet",
    0x0061DBC8: "Attribute",
    0x008E5DBC: "AudioEvent",
    0x009494E2: "AutoResolveArmor",
    0x009493FA: "AutoResolveWeapon",
    0x006E1376: "BuildingNugget",
    0x007F4B0E: "Connection",
    0x00909F2D: "ControlPoint",
    0x006CD6F4: "DamageContainedNugget",
    0x006CD301: "DamageNugget",
    0x007327BC: "DeliveryDecal",
    0x006CD757: "DOTNugget",
    0x008E5A80: "EnableRegion",
    0x008E7EBC: "EyeTowerPoints",
    0x005F05B8: "FireWeaponOCLNugget",
    0x0073D711: "Flammability",
    0x008E5BE0: "ForceBattle",
    0x0073BE51: "FormationPreviewDecal",
    0x00721AF4: "ImagePart",
    0x007213E9: "ImagePart",
    0x0073BF17: "InheritableModule",
    0x007EF63F: "LargeGroupAudioSound",
    0x00973910: "LivingWorldBuildingIconObject",
    0x00973A33: "LivingWorldBuildPlotIconObject",
    0x0073BF6B: "LocomotorSet",
    0x008E6106: "MoveArmy",
    0x008E589C: "MoveCamera",
    0x009A7AF1: "OwnershipSet",
    0x009023D8: "PlayerDefeatCondition",
    0x00902375: "PlayerDefeatCondition",
    0x0074057B: "Prerequisites",
    0x0073E7ED: "ReplaceModule",
    0x007F3BF3: "RestrictBuildings",
    0x008E6185: "SetPlayerControlOfArmy",
    0x006FF6A7: "SkillSet",
    0x007001DB: "SkirmishBuildList",
    0x009A792F: "SpawnArmies",
    0x008E78CE: "SpawnArmy",
    0x008E5CF2: "SpawnBuilding",
    0x009A7854: "SpawnBuildings",
    0x008E7981: "SplineCamera",
    0x009A7DD4: "StartingRestriction",
    0x006CD887: "StealMoneyNugget",
    0x0061F82B: "SubClass",
    0x009024A2: "TeamDefeatCondition",
    0x0090243F: "TeamDefeatCondition",
    0x00902588: "TeamVictoryCondition",
    0x00902525: "TeamVictoryCondition",
    0x0073C073: "ThreatBreakdown",
    0x006620A2: "TurretAIData",
    0x007FAA42: "Tutorial",
    0x0073F5B1: "UnitSpecificFX",
    0x0073F684: "UnitSpecificSounds",
    0x008E5F3A: "UpdateAnimObject",
    0x00619141: "ViewInfo",
    0x0073ED19: "WeaponSet",
    0x008E5E63: "WorldText",
    0x006001D4: "ShellMenuImagePart",
}

# Name arrays the flag and enum types resolve their tokens against: a
# NULL-terminated `const char*[]` reached from a static member rather than from the
# field table, so the address is recorded here and re-read from the binary. Every
# entry is checked against `NAME_TABLE_HEADS` on extraction.
NAME_TABLES = {
    "KindOf": 0x00DA0E68,
    "ObjectStatus": 0x00D8AFF0,
    "ModelCondition": 0x00D9FAD8,
    "WeaponSetFlags": 0x00DA1328,
    "DamageType": 0x00DA3960,
    "DeathType": 0x00DA39E8,
    "SpecialPowerType": 0x00DA5C90,
    "SpecialPowerFlags": 0x00DB4B08,
    "SpecialPowerAIType": 0x00DB84F8,
    "ArmorSetFlags": 0x00D9FA80,
    "EmotionType": 0x00D9FA08,
    "WeatherType": 0x00DB0074,
    "VeterancyLevel": 0x00D9F5E4,
    "SlotTypes": 0x00DA12E4,
    "LocomotorSetType": 0x00DA0530,
    "LivingWorldObjectType": 0x00DA3A90,
    "ParticleSysBonePersist": 0x00D8AF08,
}

# Arrays that run straight into the next one with no NULL between them, so the
# terminator cannot give their length and the members have to: the weather list ends
# at SUNNY, and both health-ratio lists end at ADD_CURRENT_HEALTH_TOO.
TABLE_LENGTHS = {
    0x00DB0074: 5,
    0x00DB05EC: 3,
    0x00DB1FFC: 3,
}

NAME_TABLE_HEADS = {
    "KindOf": "OBSTACLE",
    "ObjectStatus": "DESTROYED",
    "ModelCondition": "TOPPLED",
    "WeaponSetFlags": "VETERAN",
    "DamageType": "FORCE",
    "DeathType": "NORMAL",
    "SpecialPowerType": "SPECIAL_INVALID",
    "SpecialPowerFlags": "TARGETPOS",
    "SpecialPowerAIType": "AI_SPECIAL_POWER_BASIC_SELF_BUFF",
    "ArmorSetFlags": "VETERAN",
    "EmotionType": "TAUNT",
    "WeatherType": "NONE",
    "VeterancyLevel": "REGULAR",
    "SlotTypes": "PRIMARY",
    "LocomotorSetType": "SET_NORMAL",
    "LivingWorldObjectType": "ARMY",
    "ParticleSysBonePersist": "NONE",
}

# The flag and enum types whose members come from a static array rather than from
# the field's own userData.
TYPE_TABLES = {
    "KindOfFlags": "KindOf",
    "KindOfFilter": "KindOf",
    "ObjectStatusFlags": "ObjectStatus",
    "ModelConditionFlags": "ModelCondition",
    "ModelConditionFlag": "ModelCondition",
    "WeaponSetFlags": "WeaponSetFlags",
    "DamageTypeFlags": "DamageType",
    "DeathTypeFlags": "DeathType",
    "SpecialPowerAIType": "SpecialPowerAIType",
    "EmotionType": "EmotionType",
    "WeatherType": "WeatherType",
}

FLOATY = {"Real", "Percent", "DurationReal", "AngleReal", "VelocityReal",
          "AngularVelocityReal", "PositiveReal", "NonNegativeReal", "NonPositiveReal"}

# The scale factors the parsers apply, as the engine holds them. Logic runs at five
# frames a second, so a millisecond is 0.005 frames and a frame is 0.2 seconds.
LOGIC_FRAMES_PER_SECOND = 0x00D9F608
FRAMES_PER_MSEC = 0x00D9F610
SECONDS_PER_FRAME = 0x00D9F61C
RADIANS_PER_DEGREE = 0x00BD1900
# Globals in .data that nothing writes after startup, so a constructor that loads one
# (`mov eax, [LOGIC_FRAMES_PER_SECOND]; add eax, eax` is "two seconds") has a default.
ENGINE_CONSTANTS = {LOGIC_FRAMES_PER_SECOND}

# Values spread over consecutive dwords: (count, the labels the parser reads them by).
COMPOSITE_TYPES = {
    "Coord3D": (3, ("X", "Y", "Z")),
    "Coord2D": (2, ("X", "Y")),
    "RGBColor": (3, ("R", "G", "B")),
    "RGBAColor": (1, ("",)),
    "Coord2DInt": (2, ("X", "Y")),
}

# Names looked up in another store or table: the constructor can only leave them empty.
REFERENCE_TYPES = {"AsciiString", "AsciiStringList", "AudioEventRTS", "FXList",
                   "ObjectCreationList", "ParticleSystem", "WeaponTemplate", "UpgradeTemplate",
                   "SpecialPowerTemplate", "ScienceType"}

FLAG_TYPES = {"BitFlags", "KindOfFlags", "KindOfFilter", "ObjectStatusFlags", "DeathTypeFlags",
              "DamageTypeFlags", "WeaponSetFlags", "ModelConditionFlags", "DisabledTypeFlags"}
# The mask parsers that take a `NONE` or `ALL` token of their own.
ACCEPTS_NONE = {"BitFlags", "DeathTypeFlags", "DamageTypeFlags"}
ACCEPTS_ALL = {"DeathTypeFlags", "DamageTypeFlags"}

# Words a sub-block parser mentions that are not keywords of the block: the
# terminator, the empty-reference token and the C format specifiers.
NOT_KEYWORDS = {"End", "None", "NoSound", "Unknown", "Yes", "No"}

R32 = ("eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi")
R8OF = {"al": "eax", "cl": "ecx", "dl": "edx", "bl": "ebx",
        "ah": "eax", "ch": "ecx", "dh": "edx", "bh": "ebx"}
R16OF = {"ax": "eax", "cx": "ecx", "dx": "edx", "bx": "ebx"}
# Register arithmetic the constructors build constants with (`xor eax, eax; inc eax` is 1).
REG_ARITH = {
    "inc": lambda a, _b: a + 1,
    "dec": lambda a, _b: a - 1,
    "neg": lambda a, _b: -a,
    "add": lambda a, b: a + b,
    "sub": lambda a, b: a - b,
    "or": lambda a, b: a | b,
    "and": lambda a, b: a & b,
    "shl": lambda a, b: a << b,
    "imul": lambda a, b: a * b,
}


class Image:
    """Minimal read-only view of the 32-bit PE, plus a capstone decoder."""

    def __init__(self, path: str) -> None:
        pe = pefile.PE(path, fast_load=True)
        self.path = path
        self.base = pe.OPTIONAL_HEADER.ImageBase
        self.data = open(path, "rb").read()
        self.sections: list[tuple[str, int, int, int]] = []
        # bytes actually in the file per section; the rest of a section is zero when loaded
        self.raw_sizes: dict[int, int] = {}
        for s in pe.sections:
            name = s.Name.rstrip(b"\x00").decode("latin1")
            size = max(s.Misc_VirtualSize, s.SizeOfRawData)
            self.sections.append((name, self.base + s.VirtualAddress, size,
                                  s.PointerToRawData))
            self.raw_sizes[self.base + s.VirtualAddress] = s.SizeOfRawData
        self.md = Cs(CS_ARCH_X86, CS_MODE_32)
        text = next(s for s in self.sections if s[0] == ".text")
        self.text_va = text[1]
        self.text = self.data[text[3]:text[3] + text[2]]
        self._writes = self._static_init_writes()
        self._write_vas = [va for va, _ in self._writes]

    def section_of(self, va: int) -> Optional[str]:
        for name, va0, size, _ in self.sections:
            if va0 <= va < va0 + size:
                return name
        return None

    def read(self, va: int, n: int) -> bytes:
        """Bytes at `va` as the engine sees them once its static initialisers have run."""
        raw = self._raw(va, n)
        k = bisect.bisect_left(self._write_vas, va - 3)
        if k == len(self._write_vas) or self._write_vas[k] >= va + len(raw):
            return raw
        out = bytearray(raw)
        while k < len(self._writes) and self._writes[k][0] < va + len(raw):
            at, value = self._writes[k]
            for j, byte in enumerate(value):
                if 0 <= at + j - va < len(out):
                    out[at + j - va] = byte
            k += 1
        return bytes(out)

    def _static_init_writes(self) -> list[tuple[int, bytes]]:
        """Stores the engine's guarded static initialisers make into the data sections.

        A field table whose rows hold something the compiler cannot fold into a constant -
        another table's address, an `offsetof` through a base - is written at runtime the
        first time its `buildFieldParse` runs: `test byte [guard], 1 / jne done /
        or dword [guard], 1` and then a run of absolute stores. On disk those slots are
        zero, which reads as a missing userData, an offset of 0, or a table that ends a
        row early. The stores are constants or registers zeroed just before the guard,
        so they can be replayed here and the tables read as the running engine sees them.
        """
        td, base = self.text, self.text_va
        writes: dict[int, bytes] = {}
        at = td.find(b"\x83\x0d")
        while at != -1:
            guard = struct.unpack_from("<I", td, at + 2)[0]
            test = td.rfind(b"\xf6\x05" + struct.pack("<I", guard), max(0, at - 0x30), at)
            if test != -1 and self.section_of(guard) not in (None, ".text"):
                writes.update(self._replay_init(base + test, base + at))
            at = td.find(b"\x83\x0d", at + 1)
        return sorted(writes.items())

    def _replay_init(self, test: int, guard_or: int) -> dict[int, bytes]:
        regs: dict[str, int] = {}
        start = test
        for s in range(test - 0x18, test):
            if any(i.address == test for i in self.md.disasm(self._raw(s, test - s + 8), s)):
                start = s
                break
        out: dict[int, bytes] = {}
        for i in self.md.disasm(self._raw(start, 0x400), start):
            m, o = i.mnemonic, i.op_str
            dst, _, src = o.partition(", ")
            if i.address > guard_or and (m in ("call", "ret", "jmp", "int3") or m.startswith("j")):
                break
            if m == "xor" and dst == src and dst in R32:
                regs[dst] = 0
            elif m == "mov" and dst in R32:
                if src.startswith("0x") or src.isdigit():
                    regs[dst] = int(src, 0)
                else:
                    regs.pop(dst, None)
            elif (i.address > guard_or and m == "mov" and dst.startswith("dword ptr [0x")
                    and dst.endswith("]")):
                va = int(dst[dst.index("[") + 1:-1], 16)
                value = (int(src, 0) if src.startswith("0x") or src.isdigit()
                         else regs.get(src))
                if value is not None and self.section_of(va) not in (None, ".text"):
                    out[va] = struct.pack("<I", value & 0xFFFFFFFF)
        return out

    def _raw(self, va: int, n: int) -> bytes:
        """Bytes at `va` as loaded, before static initialisers: past what the file holds
        for the section - `.data`'s uninitialised tail - that is zeros."""
        for _, va0, size, fo in self.sections:
            if va0 <= va < va0 + size:
                rel = va - va0
                n = min(n, size - rel)
                stored = self.raw_sizes[va0]
                data = self.data[fo + rel:fo + min(rel + n, stored)] if rel < stored else b""
                return data + bytes(n - len(data))
        return b""

    def u32(self, va: int) -> int:
        raw = self.read(va, 4)
        return struct.unpack("<I", raw)[0] if len(raw) == 4 else 0

    def cstr(self, va: int, maxlen: int = 96) -> Optional[str]:
        raw = self.read(va, maxlen)
        end = raw.find(b"\x00")
        if end <= 0:
            return None
        try:
            return raw[:end].decode("ascii")
        except UnicodeDecodeError:
            return None

    def is_text(self, va: int) -> bool:
        return self.section_of(va) == ".text"

    def is_str(self, va: int) -> bool:
        return _is_data(self, va) and self.cstr(va) is not None

    def calls_to(self, target: int) -> list[int]:
        out, td = [], self.text
        for i in range(len(td) - 5):
            if td[i] == 0xE8:
                rel = struct.unpack("<i", td[i + 1:i + 5])[0]
                if self.text_va + i + 5 + rel == target:
                    out.append(self.text_va + i)
        return out

    def func_start(self, va: int, back: int = 0x4000) -> Optional[int]:
        """Nearest preceding MSVC prologue: `__EH_prolog` entry or `push ebp; mov ebp,esp`."""
        td, base = self.text, self.text_va
        best = None
        for a in range(max(base, va - back), va):
            i = a - base
            if td[i] == 0xB8 and td[i + 5] == 0xE8:
                rel = struct.unpack("<i", td[i + 6:i + 10])[0]
                if a + 10 + rel == EH_PROLOG:
                    best = a
            elif td[i:i + 3] == b"\x55\x8b\xec":
                best = a
        return best

    def disasm(self, start: int, maxlen: int = 0x9000) -> Iterator[Any]:
        """Linear decode from a function start, stopping at the first `ret`."""
        for ins in self.md.disasm(self.read(start, maxlen), start):
            yield ins
            if ins.mnemonic in ("ret", "retf"):
                return


def name_table(img: Image, va: int, limit: int = 1024) -> list[str]:
    """The NULL-terminated `const char*[]` at `va`, empty if that is not what is there.

    Members are identifiers, so a pointer to something with a space in it - a message,
    a format string - ends the array as surely as the NULL does. Not every array is
    NULL-terminated: where one runs straight into the next, the repeated member name
    is the seam, and the array ends there.
    """
    out: list[str] = []
    for k in range(min(limit, TABLE_LENGTHS.get(va, limit))):
        p = img.u32(va + 4 * k)
        if not p or not _is_data(img, p):
            break
        s = img.cstr(p, 64)
        if not s or not s.isprintable() or " " in s or not 0 < len(s) <= 48:
            break
        if s in out:
            break
        out.append(s)
    return out


def lookup_table(img: Image, va: int, limit: int = 256) -> list[tuple[str, int]]:
    """The `{const char *name, int value}` pairs of a lookup list at `va`."""
    out: list[tuple[str, int]] = []
    for k in range(limit):
        p = img.u32(va + 8 * k)
        if not p or not _is_data(img, p):
            break
        s = img.cstr(p, 64)
        if not s or not s.isprintable() or " " in s or not 0 < len(s) <= 48:
            break
        out.append((s, img.u32(va + 8 * k + 4)))
    return out


def field_table_of(img: Image, fn: int, max_offset: int = 0x4000, limit: int = 200,
                   depth: int = 0, maxdepth: int = 1,
                   seen: Optional[set[int]] = None,
                   min_rows: int = 2) -> list[tuple[str, int, int, int]]:
    """The field table a parser hands to the INI reader, if it uses one.

    Every block the engine reads - a module, a nested block, a whole `Object` - is read
    through the same 16-byte-stride table, either pushed directly or fetched from a
    constant-returning accessor. A name array can pass `_looks_like_table`, so a real
    table is told apart by its rows: every parse function is code, and every offset is
    a plausible struct offset.
    """
    seen = seen if seen is not None else set()
    if fn in seen or depth > maxdepth:
        return []
    seen.add(fn)

    def rows_at(addr: int) -> list[tuple[str, int, int, int]]:
        if not _looks_like_table(img, addr):
            return []
        rows = parse_table(img, addr, limit)
        ok = all(img.is_text(r[1]) and r[3] < max_offset for r in rows)
        return rows if len(rows) >= min_rows and ok else []

    ins = list(img.disasm(fn, 0x900))
    # the parser's own table first, then the one a helper it calls hands over
    for i in ins:
        if i.mnemonic == "call" and i.op_str.startswith("0x"):
            accessor = const_return(img, int(i.op_str, 16))
            if accessor:
                rows = rows_at(accessor)
                if rows:
                    return rows
        for tok in i.op_str.replace(",", " ").replace("[", " ").replace("]", " ").split():
            if not tok.startswith("0x"):
                continue
            try:
                a = int(tok, 16)
            except ValueError:
                continue
            rows = rows_at(a)
            if rows:
                return rows
    for i in ins:
        if i.mnemonic in ("call", "jmp") and i.op_str.startswith("0x") and len(ins) < 200:
            target = int(i.op_str, 16)
            if img.is_text(target):
                rows = field_table_of(img, target, max_offset, limit, depth + 1,
                                      maxdepth, seen, min_rows)
                if rows:
                    return rows
    return []


def registered_rows(img: Image, fn: int) -> list[tuple[str, int, int, int]]:
    """The rows a parser's block gets from a `buildFieldParse` it hands over.

    A block read through `MultiIniFieldParse` - a weapon nugget, the turret data - has
    no table of its own for the parser to push: it pushes the function that adds the
    tables instead. A pushed function counts as one only if it really does call
    `MultiIniFieldParse::add`, which `field_tables` checks.
    """
    for i in img.disasm(fn, 0x600):
        if i.mnemonic == "push" and i.op_str.startswith("0x") and img.is_text(int(i.op_str, 16)):
            rows = [(kw, parse, ud, off + extra)
                    for tab, _src, extra in field_tables(img, int(i.op_str, 16))
                    for kw, parse, ud, off in parse_table(img, tab)]
            if rows:
                return rows
    return []


def block_keywords(img: Image, fn: int) -> list[str]:
    """The keywords a sub-block parser compares its tokens against.

    A block parser strcmps the token it read against each keyword it accepts, so the
    identifier-shaped strings it references in order are the block's schema. Engine
    keywords are CamelCase, which separates them from the SHOUTING enum members and
    from the sentences in the error messages.
    """
    out: list[str] = []
    for i in img.disasm(fn, 0x600):
        for tok in i.op_str.replace(",", " ").replace("[", " ").replace("]", " ").split():
            if not tok.startswith("0x"):
                continue
            try:
                va = int(tok, 16)
            except ValueError:
                continue
            if not _is_data(img, va):
                continue
            s = img.cstr(va, 64)
            if (s and s not in out and s not in NOT_KEYWORDS and 1 < len(s) <= 32
                    and s[0].isupper() and s.isalnum() and any(c.islower() for c in s)):
                out.append(s)
    return out


def _memop(op: str) -> Optional[tuple[str, int]]:
    """`[reg + disp]` -> (reg, disp). Indexed forms are rejected."""
    if "[" not in op or "*" in op:
        return None
    inner = op[op.index("[") + 1:op.index("]")]
    parts = [p.strip() for p in inner.replace("-", "+-").split("+")]
    if not parts or parts[0] not in R32:
        return None
    disp = 0
    for p in parts[1:]:
        try:
            disp += int(p, 0)
        except ValueError:
            return None
    return parts[0], disp


_WIDTHS = {"byte": 1, "word": 2, "dword": 4, "qword": 8}


def _width(op: str) -> int:
    """Bytes a memory operand covers, from capstone's `dword ptr [...]` size prefix."""
    return _WIDTHS.get(op.split(" ", 1)[0], 1)


class FieldInfo(dict):
    """One INI keyword: name, struct offset, parse function, type, default."""


class ModuleInfo(dict):
    """One registered module: name, sizeof(ModuleData), and its fields."""


def registrations(img: Image) -> list[tuple[Optional[str], Optional[int], Optional[int], Optional[str]]]:
    """(name, instanceFactory, moduleDataFactory, interfaceMask) per addModule call."""
    sites = img.calls_to(ADD_MODULE)
    starts = sorted({s for s in (img.func_start(v) for v in sites) if s})
    out = []
    for start in starts:
        ins = list(img.disasm(start))
        name: Optional[str] = None
        pushes: list[str] = []
        for k, i in enumerate(ins):
            # `push <string> ; lea ecx, [ebp-N]` is the module-name assign, whichever
            # AsciiString helper follows it
            if (i.mnemonic == "push" and i.op_str.startswith("0x")
                    and img.is_str(int(i.op_str, 16))
                    and k + 1 < len(ins) and ins[k + 1].mnemonic == "lea"
                    and ins[k + 1].op_str.startswith("ecx, [ebp -")):
                name = img.cstr(int(i.op_str, 16))
                pushes = []
            elif i.mnemonic == "push":
                pushes.append(i.op_str)
            elif i.mnemonic == "call" and i.op_str.startswith("0x"):
                if int(i.op_str, 16) == ADD_MODULE:
                    fns = [int(p, 16) for p in pushes
                           if p.startswith("0x") and img.is_text(int(p, 16))]
                    mask = pushes[-6] if len(pushes) >= 6 else None
                    out.append((name, fns[-1] if fns else None,
                                fns[-2] if len(fns) > 1 else None, mask))
                    name, pushes = None, []
                else:
                    pushes = []
    return out


def moduledata_info(img: Image, fn: Optional[int]) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """(sizeof, constructor, buildFieldParse) from a ModuleData factory thunk."""
    if not fn:
        return None, None, None
    size = ctor = bfp = None
    pending: Optional[int] = None
    for i in img.disasm(fn, 0x200):
        if i.mnemonic == "push" and i.op_str.startswith("0x"):
            v = int(i.op_str, 16)
            if img.is_text(v):
                bfp = v
            elif 4 <= v <= 0x8000:
                pending = v
        elif i.mnemonic == "call" and i.op_str.startswith("0x"):
            t = int(i.op_str, 16)
            if t in OPERATOR_NEW and size is None:
                size = pending
            elif t not in HELPERS and ctor is None and size is not None:
                ctor = t
    return size, ctor, bfp


def _is_data(img: Image, va: int) -> bool:
    """Mapped, and not in the code section - `.rdata`/`.data`, or a patch's appended cave.

    Naming the two stock sections outright would refuse a table a patch has relocated: a rebuilt
    field table lives in the section that patch appended, which is where a patched `game.dat`
    keeps it and where the engine reads it from. What discriminates a table is its shape, checked
    below, not which section it happens to sit in."""
    section = img.section_of(va)
    return section is not None and section != ".text"


def _looks_like_table(img: Image, a: int) -> bool:
    if not _is_data(img, a):
        return False
    first = img.u32(a)
    return bool(first and _is_data(img, first) and img.cstr(first))


def const_return(img: Image, fn: int) -> Optional[int]:
    """`mov eax, imm32 ; ret` accessors return a base class's field table."""
    ins = list(img.disasm(fn, 0x10))
    if (len(ins) >= 2 and ins[0].mnemonic == "mov"
            and ins[0].op_str.startswith("eax, 0x") and ins[1].mnemonic == "ret"):
        return int(ins[0].op_str.split(", ")[1], 16)
    return None


def field_tables(img: Image, bfp: Optional[int], depth: int = 0,
                 seen: Optional[set[int]] = None) -> list[tuple[int, int, int]]:
    """(field table, the `buildFieldParse` that appended it, extra offset) for one module.

    Every table reaches the module through `MultiIniFieldParse::add(table, extraOffset)`,
    either pushed directly or fetched from a base class through a trivial
    constant-returning accessor and then pushed from `eax`. The extra offset is where
    the struct the table describes sits inside the ModuleData: the shared die and
    upgrade conditions (`DieMuxData`, `UpgradeMuxData`) are embedded members, so their
    table's own offsets only become ModuleData offsets once it is added. The compiler
    often pushes that offset before calling the accessor, so the call's arguments are
    read off a small emulated stack rather than from the instructions next to it.

    A base class's own `buildFieldParse`, which a derived one calls before adding its
    own, is where inheritance lives: `OCLSpecialPower` declares five keywords itself
    and takes the other thirty-five from `SpecialPowerModule` through it. A derived
    class that adds nothing of its own tail-jumps to its base instead of calling it.
    Following either in place keeps the engine's own order, in which the base's table
    is searched first and therefore wins a keyword declared in both.

    The second element of each triple names the class the table belongs to, which is
    what lets an inherited field name where it came from.
    """
    tabs: list[tuple[int, int, int]] = []
    if not bfp or depth > MAX_BASE_DEPTH:
        return tabs
    seen = seen if seen is not None else set()
    if bfp in seen:
        return tabs
    seen.add(bfp)
    regs: dict[str, int] = {}
    stack: list[Optional[int]] = []
    for i in img.disasm(bfp, 0x300):
        m, o = i.mnemonic, i.op_str
        dst, _, src = o.partition(", ")
        if m == "push":
            stack.append(int(o, 16) if o.startswith("0x") else
                         int(o) if o.isdigit() else regs.get(o))
        elif m == "pop":
            if stack:
                stack.pop()
            regs.pop(o, None)
        elif m == "add" and dst == "esp" and (src.startswith("0x") or src.isdigit()):
            del stack[len(stack) - int(src, 0) // 4:]
        elif m == "xor" and dst == src and dst in R32:
            regs[dst] = 0
        elif m == "mov" and dst in R32:
            if src.startswith("0x") or src.isdigit():
                regs[dst] = int(src, 0)
            else:
                regs.pop(dst, None)
        elif m in ("call", "jmp") and o.startswith("0x"):
            target = int(o, 16)
            if m == "jmp" and bfp <= target < i.address + 0x100:
                continue
            if target == MULTI_FIELD_ADD:
                tab = stack[-1] if stack else None
                extra = stack[-2] if len(stack) > 1 else None
                del stack[-2:]
                if tab is not None and _looks_like_table(img, tab):
                    if extra is None:
                        raise ValueError("0x%08x: no extra offset for table 0x%08x at 0x%08x"
                                         % (bfp, tab, i.address))
                    tabs.append((tab, bfp, extra))
            else:
                a = const_return(img, target)
                if a is not None:
                    regs["eax"] = a
                elif target not in HELPERS and img.is_text(target):
                    tabs.extend(field_tables(img, target, depth + 1, seen))
                    regs.pop("eax", None)
            if m == "jmp":
                break
    return tabs


def parse_table(img: Image, tab: int, limit: int = 200) -> list[tuple[str, int, int, int]]:
    """(keyword, parseFn, userData, offset) rows of a 16-byte-stride field table."""
    out = []
    for k in range(limit):
        e = tab + k * 16
        namep = img.u32(e)
        if not namep or not _is_data(img, namep):
            break
        nm = img.cstr(namep)
        if not nm or not nm.isprintable() or len(nm) > 64:
            break
        out.append((nm, img.u32(e + 4), img.u32(e + 8), img.u32(e + 12)))
    return out


def ctor_defaults(img: Image, ctor: Optional[int], depth: int = 0, maxdepth: int = 5,
                  bases: Optional[dict[int, int]] = None) -> dict[int, Any]:
    """{offset: value} written by a ModuleData constructor, by constant tracking.

    Handles the MSVC idioms the engine actually uses: immediate stores, stores of a
    zeroed or constant-loaded register (`push imm / pop reg` included), `movss` from an
    .rdata float, `xorps`, `or dword [x], -1`, `and dword [x], 0`, loads of the logic
    frame rate, and AsciiString initialisation. A base class constructor invoked with
    `ecx == this` is followed in place. A call on a member (`lea ecx, [this+L]`) is
    followed too, its writes rebased by L, and `bases` records L for each of them: that
    call is a member's constructor only most of the time, and the caller uses it to
    drop what an assignment or a setter wrote past the member's own end.

    A register is only trusted while nothing has changed it since it was loaded: a call
    clobbers `eax`, `ecx`, `edx` and the xmm registers, and any instruction the walk does
    not model forgets the register it writes.
    """
    if not ctor or depth > maxdepth:
        return {}
    out: dict[int, Any] = {}
    origin: dict[int, int] = {}
    ireg: dict[str, int] = {}
    freg: dict[str, float] = {}
    pushes: list[str] = []
    lea_off: Optional[int] = None
    this = {"ecx"}

    def put(off: int, value: Any) -> None:
        out[off] = value
        origin.pop(off, None)

    def forget(off: int) -> None:
        out.pop(off, None)
        origin.pop(off, None)

    for i in img.disasm(ctor, 0x1200):
        m, o = i.mnemonic, i.op_str
        dst, _, src = o.partition(", ")
        if m == "push":
            pushes.append(o)
            continue
        if dst in ("ecx", "cx", "cl") and m not in ("lea", "cmp", "test"):
            lea_off = None
        if m == "pop" and dst in R32:
            last = pushes.pop() if pushes else ""
            if last.startswith("0x") or last.lstrip("-").isdigit():
                ireg[dst] = int(last, 0)
            else:
                ireg.pop(dst, None)
            this.discard(dst)
        elif m == "xor" and dst == src and dst in R32:
            ireg[dst] = 0
            this.discard(dst)
        elif m == "xorps" and dst == src:
            freg[dst] = 0.0
        elif m == "mov" and dst in R32:
            if src in this:
                this.add(dst)
            elif src.startswith("0x") or src.lstrip("-").isdigit():
                ireg[dst] = int(src, 0)
                this.discard(dst)
            elif src.startswith("dword ptr [0x") and src.endswith("]") and (
                    int(src[src.index("[") + 1:-1], 16) in ENGINE_CONSTANTS):
                ireg[dst] = img.u32(int(src[src.index("[") + 1:-1], 16))
                this.discard(dst)
            else:
                ireg.pop(dst, None)
                this.discard(dst)
        elif m in REG_ARITH and dst in R32 and dst in ireg and (
                not src or src in ireg or src.startswith("0x") or src.lstrip("-").isdigit()):
            operand = ireg[src] if src in ireg else int(src, 0) if src else 0
            ireg[dst] = REG_ARITH[m](ireg[dst], operand) & 0xFFFFFFFF
        elif m == "movss" and dst.startswith("xmm"):
            if src.startswith("dword ptr [0x"):
                a = int(src[src.index("[") + 1:src.index("]")], 16)
                raw = img.read(a, 4)
                if len(raw) == 4:
                    freg[dst] = struct.unpack("<f", raw)[0]
                else:
                    freg.pop(dst, None)
            elif src in freg:
                freg[dst] = freg[src]
            else:
                freg.pop(dst, None)
        elif m in ("mov", "movss", "or", "and") and "[" in dst:
            mm = _memop(dst)
            if not mm or mm[0] not in this:
                continue
            off = mm[1]
            if m == "movss":
                if src in freg:
                    put(off, freg[src])
                else:
                    forget(off)
            elif m == "or" and src == "0xffffffff":
                put(off, 0xFFFFFFFF)
            elif m == "or":
                forget(off)
            elif m == "and" and src == "0":
                # `and dword [this+off], 0` is the engine's idiom for zeroing a member, and it
                # zeroes all four bytes - so a narrower field sharing the dword is defaulted by
                # it too, unless a later store overwrites that byte (this walk is linear, so a
                # later `out[off]` wins). Without this a `Bool` packed beside an `Int` reads as
                # having no compiled-in default when it plainly has one.
                for k in range(_width(dst)):
                    put(off + k, 0)
            elif m == "and":
                forget(off)
            elif m == "mov":
                if src.startswith("0x") or src.lstrip("-").isdigit():
                    put(off, int(src, 0))
                elif src in ireg:
                    put(off, ireg[src])
                elif src in R8OF and R8OF[src] in ireg and not src.endswith("h"):
                    put(off, ireg[R8OF[src]] & 0xFF)
                elif src in R16OF and R16OF[src] in ireg:
                    put(off, ireg[R16OF[src]] & 0xFFFF)
                else:
                    # a store of something not known here - a call's result, a value
                    # loaded from elsewhere - overrides what an earlier store left
                    forget(off)
        elif m == "lea" and dst in R32:
            mm = _memop(src)
            if mm and mm[0] in this and mm[1] == 0:
                this.add(dst)
            elif dst == "ecx":
                lea_off = mm[1] if mm and mm[0] in this else None
                ireg.pop(dst, None)
            else:
                this.discard(dst)
                ireg.pop(dst, None)
        elif m == "call" and o.startswith("0x"):
            t = int(o, 16)
            if t in STR_ASSIGN and lea_off is not None:
                text = ""
                for p in reversed(pushes[-3:]):
                    if p.startswith("0x") and img.is_str(int(p, 16)):
                        text = img.cstr(int(p, 16)) or ""
                        break
                put(lea_off, '"%s"' % text)
            elif t not in HELPERS and lea_off is None and "ecx" in this:
                # base class constructor sharing `this`
                for k, v in ctor_defaults(img, t, depth + 1, maxdepth, origin).items():
                    out.setdefault(k, v)
            elif t not in HELPERS and lea_off is not None:
                for k, v in ctor_defaults(img, t, depth + 1, maxdepth).items():
                    if k + lea_off not in out:
                        out[k + lea_off] = v
                        origin[k + lea_off] = lea_off
            lea_off = None
            pushes = []
            for reg in ("eax", "ecx", "edx"):
                ireg.pop(reg, None)
            this.discard("eax")
            this.discard("edx")
            freg.clear()
        else:
            written = R8OF.get(dst) or R16OF.get(dst) or (dst if dst in R32 else None)
            if written and m not in ("cmp", "test", "push"):
                ireg.pop(written, None)
                if written != dst or m != "mov":
                    this.discard(written)
    if bases is not None:
        bases.update(origin)
    return out


def _drop_stray(defaults: dict[int, Any], bases: dict[int, int],
                fields: list[tuple[int, int]]) -> dict[int, Any]:
    """The defaults without what a call on a member wrote past that member's end.

    `fields` is (offset, the extra offset its table was added at) per field. A value
    that came from a call on the member at L is kept when L is where a table was added -
    the shared die and upgrade conditions are embedded structs whose constructor writes
    every field of theirs - or when no other field lies between L and the value, so it
    can still be the member's own. Otherwise the call was an assignment or a setter whose
    writes landed in someone else's field.
    """
    offsets = sorted({off for off, _ in fields})
    embedded = {extra for _, extra in fields}
    return {off: value for off, value in defaults.items()
            if bases.get(off) is None or bases[off] in embedded
            or not any(bases[off] < other < off for other in offsets)}



# Windows calls an engine function can make on its way to a value without that value
# depending on them, with the number of argument dwords each pops on return
STDCALL_ARGS = {
    "InitializeCriticalSection": 1, "DeleteCriticalSection": 1, "EnterCriticalSection": 1,
    "LeaveCriticalSection": 1, "InterlockedIncrement": 1, "InterlockedDecrement": 1,
    "InterlockedExchange": 2, "InterlockedExchangeAdd": 2, "GetTickCount": 0,
    "GetCurrentThreadId": 0, "GetCurrentProcessId": 0, "GetLastError": 0,
    "QueryPerformanceCounter": 1, "QueryPerformanceFrequency": 1, "OutputDebugStringA": 1,
    "TlsGetValue": 1, "timeGetTime": 0,
}


class Emulator:
    """Runs constructors in unicorn, to read the defaults they really write.

    Constant tracking reads a constructor; this runs it, member constructors, loops,
    x87 arithmetic and all. A constructor may also read globals the engine only fills
    at startup - a lookup of an FXList by name, a pool allocator - which nothing here
    initialises. So every constructor runs twice, once over zeroed uninitialised data
    and heap and once over poisoned ones, and a value is only believed if both runs
    agree on it: anything derived from a global the engine fills in later differs
    between the runs and is dropped. An engine function that faults in this bare
    process is stubbed to return zero in one run and poison in the other, so whatever
    is computed from it fails the same test.

    Engine strings live in a memory pool nothing initialises, so string-valued fields
    are left to constant tracking, which reads the literal a constructor assigns.
    """

    POISON = 0xCD
    UNSET = (0x00, 0x5A)
    STACK, STACK_SIZE = 0x08000000, 0x100000
    HEAP, HEAP_SIZE = 0x09000000, 0x400000
    TEB, GDT, RET, BUF, BUF_SIZE = 0x07F00000, 0x07D00000, 0x07E00000, 0x0C000000, 0x10000
    IMPORTS = 0x07C00000
    BUDGET = 400000

    def __init__(self, img: Image, path: str) -> None:
        self.img = img
        self.stubs: dict[int, int] = {}
        self.hooked: set[int] = set()
        self.pages: list[int] = []
        self.variant = 0
        self.path_hash = 0
        self.faulted = False
        self.capturing: Optional[
            list[tuple[list[tuple[str, int, int, int]], Optional[bytes]]]] = None
        # the first reset fills the whole heap; later ones only what a run handed out
        self.heap_top = self.HEAP + self.HEAP_SIZE
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_32)
        lo = min(s[1] for s in img.sections) & ~0xFFF
        hi = (max(s[1] + s[2] for s in img.sections) + 0xFFF) & ~0xFFF
        uc.mem_map(lo, hi - lo)
        # what a constructor can change, as each run starts it: the initialised part of
        # .data as shipped, the uninitialised rest zeroed in one run and poisoned in the other
        self.data: list[tuple[int, tuple[bytes, bytes]]] = []
        for name, va, size, _fo in img.sections:
            raw = img.read(va, size)
            uc.mem_write(va, raw)
            if name == ".data":
                # A dumped image claims the whole section as file data, its uninitialised
                # tail included (as zeros), so the header cannot say where that tail
                # starts. It starts no later than the trailing run of zeros, and poisoning
                # from there errs towards distrusting a value, never towards believing one.
                shipped = img._raw(va, img.raw_sizes[va]).rstrip(b"\0")
                shipped += bytes(-len(shipped) % 4)
                images = []
                for fill in self.UNSET:
                    data = bytearray(shipped + bytes([fill]) * (size - len(shipped)))
                    # the static initialisers the image replays do run before any of this
                    for at, value in img._writes:
                        if va <= at < va + size:
                            data[at - va:at - va + len(value)] = value
                    images.append(bytes(data))
                self.data.append((va, (images[0], images[1])))
        for base, size in ((self.STACK, self.STACK_SIZE), (self.HEAP, self.HEAP_SIZE),
                           (self.TEB, 0x1000), (self.GDT, 0x1000), (self.RET, 0x1000),
                           (self.BUF, self.BUF_SIZE)):
            uc.mem_map(base, size, UC_PROT_READ | UC_PROT_WRITE)
        uc.mem_write(self.TEB, struct.pack("<I", 0xFFFFFFFF) + bytes(0x14)
                     + struct.pack("<I", self.TEB))
        # `__EH_prolog` links SEH frames through fs:[0], so FS needs a real segment
        gdt = b"".join(_gdt_entry(*e) for e in ((0, 0, 0, 0), (0, 0xFFFFF, 0x9A, 0xC),
                                                (0, 0xFFFFF, 0x92, 0xC),
                                                (self.TEB, 0xFFF, 0x92, 0x4)))
        uc.mem_write(self.GDT, gdt)
        uc.reg_write(UC_X86_REG_GDTR, (0, self.GDT, len(gdt) - 1, 0))
        for reg in (UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS):
            uc.reg_write(reg, 2 << 3)
        uc.reg_write(UC_X86_REG_FS, 3 << 3)
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._map_page)
        # Copying a string draws on a memory pool nothing here sets up, and branches on
        # its uninitialised state. String defaults are read by constant tracking anyway,
        # so the copy starts out stubbed.
        self._stub_out(STR_COPY)
        uc.hook_add(UC_HOOK_BLOCK, self._block)
        for fn in OPERATOR_NEW:
            uc.hook_add(UC_HOOK_CODE, self._new, begin=fn, end=fn)
        for fn in (INI_PARSE_FIELDS, INI_PARSE_MULTI, CXX_THROW, INI_NEXT_TOKEN_OR_NULL,
                   *INI_NEXT_TOKEN):
            uc.hook_add(UC_HOOK_CODE, self._ini, begin=fn, end=fn)
        uc.mem_write(self.RET + 0x100, b"Default\0")
        # The engine reaches the system DLLs both through `jmp [slot]` thunks and with a
        # direct `call [slot]`, so every import slot is pointed at an address of its own
        # that _import answers.
        self.imports = _imports(path)
        size = (4 * len(self.imports) + 0xFFF) & ~0xFFF
        uc.mem_map(self.IMPORTS, size)
        for k, (slot, _dll, _name) in enumerate(self.imports):
            uc.mem_write(slot, struct.pack("<I", self.IMPORTS + 4 * k))
        uc.hook_add(UC_HOOK_CODE, self._import, begin=self.IMPORTS,
                    end=self.IMPORTS + 4 * len(self.imports) - 1)
        self.thunks = set(_import_thunks(img, path))

    def run(self, ctor: int) -> Optional[tuple[bytes, bytes]]:
        """The instance as each of the two runs leaves it, or None if they cannot be
        believed: one never returns, or the two took different paths through the code.

        Agreeing bytes alone are not enough. A constructor that looks a default up by a
        name in global game data skips the lookup when the name reads as empty, and both
        runs can reach "empty" by different routes and leave the field identical - zero
        where the running game stores a pointer. A branch on something uninitialised
        shows up as a difference in the path, so the paths have to match as well.
        """
        runs, paths = [], []
        for variant in (0, 1):
            mem = self._run(ctor, variant)
            if mem is None:
                return None
            runs.append(mem)
            paths.append(self.path_hash)
        if paths[0] != paths[1]:
            return None
        return runs[0], runs[1]

    def capture(self, parser: int) -> Optional[tuple[list[tuple[str, int, int, int]],
                                                     Optional[tuple[bytes, bytes]]]]:
        """The field rows a block parser hands to the INI reader, and the instance they
        fill as each run had it at that moment - or None if the parser never gets there.

        The parser runs on an INI whose every token reads `Default`, up to the moment it
        calls `initFromINI`. Its table is the one the run that starts from zeroed
        memory passes, as the running game does: a table assembled on the stack, or in
        a static the first call fills, can only be read here. The instance's defaults
        are believed where both runs reached that call the same way, on an instance
        each allocated itself; a global instance is whatever its static constructor,
        which nothing here runs, would leave.
        """
        got = []
        # What a constructor had stubbed would break a parser that needs it, and the
        # other way round, so a parser starts from the stubs every emulator starts with.
        stubs, self.stubs = self.stubs, {STR_COPY: self.stubs[STR_COPY]}
        for variant in (0, 1):
            self.capturing = []
            self._run(parser, variant)
            seen, self.capturing = self.capturing, None
            if not seen:
                break
            got.append((seen[0], self.path_hash))
        self.stubs = stubs
        if not got or not got[0][0][0]:
            return None
        (rows, mem), path = got[0]
        if len(got) < 2 or path != got[1][1] or mem is None or got[1][0][1] is None:
            return rows, None
        return rows, (mem, got[1][0][1])

    def _ini(self, _uc: Any, address: int, _size: int, _data: Any) -> None:
        if self.capturing is None:
            return
        if address in INI_NEXT_TOKEN:
            self._return(self.RET + 0x100, _ret_imm(self.img, address))
        elif address == INI_NEXT_TOKEN_OR_NULL:
            self._return(0, _ret_imm(self.img, address))
        else:
            # the first block handed over, or a throw before any, ends the run
            if address != CXX_THROW and not self.capturing:
                inst, arg = self._arg(0), self._arg(1)
                if address == INI_PARSE_FIELDS:
                    rows = self._rows(arg)
                else:
                    rows = [(kw, parse, ud, off + extra)
                            for tab, _src, extra in field_tables(self.img, arg)
                            for kw, parse, ud, off in parse_table(self.img, tab)]
                size = max((r[3] for r in rows), default=0) + 16
                mem = None
                if self.HEAP <= inst and inst + size <= self.heap_top:
                    mem = bytes(self.uc.mem_read(inst, size))
                self.capturing.append((rows, mem))
            self.uc.reg_write(UC_X86_REG_EIP, self.RET)

    def _rows(self, table: int) -> list[tuple[str, int, int, int]]:
        rows = []
        for k in range(500):
            try:
                name, parse, ud, off = struct.unpack("<4I", self.uc.mem_read(table + 16 * k, 16))
            except UcError:
                return []
            if not name:
                return rows
            keyword = self.img.cstr(name, 64) if _is_data(self.img, name) else None
            if not keyword or not self.img.is_text(parse) or off >= 0x10000:
                return []
            rows.append((keyword, parse, ud, off))
        return []

    def _run(self, ctor: int, variant: int) -> Optional[bytes]:
        for _attempt in range(25):
            self._reset(variant)
            uc = self.uc
            sp = self.STACK + self.STACK_SIZE - 0x100
            # a block parser's one argument, the INI being read, is the buffer as well
            uc.mem_write(sp, struct.pack("<II", self.RET, self.BUF))
            uc.reg_write(UC_X86_REG_ESP, sp)
            uc.reg_write(UC_X86_REG_EBP, sp + 0x80)
            uc.reg_write(UC_X86_REG_ECX, self.BUF)
            start = ctor
            for _escape in range(50):
                try:
                    uc.emu_start(start, self.RET, count=self.BUDGET)
                    ran_out = True
                except UcError:
                    ran_out = False
                eip = uc.reg_read(UC_X86_REG_EIP)
                if eip == self.RET:
                    return bytes(uc.mem_read(self.BUF, self.BUF_SIZE))
                if self.faulted:
                    break
                if ran_out:
                    # A loop counting through poison. Whatever happens to be running when
                    # the budget ends is no more to blame than its callers, and stubbing
                    # it would only break the next constructor that needs it.
                    return None
                # a call through a pointer nothing initialised lands outside the code:
                # return to the caller with a value that fails the agreement test
                esp = uc.reg_read(UC_X86_REG_ESP)
                if not self.STACK <= esp < sp:
                    break
                back = struct.unpack("<I", uc.mem_read(esp, 4))[0]
                if self.img.is_text(eip) or not self.img.is_text(back):
                    break
                uc.reg_write(UC_X86_REG_ESP, esp + 4)
                uc.reg_write(UC_X86_REG_EAX, 0x5A5A5A5A if variant else 0)
                start = back
            culprit = self._innermost_callee(sp)
            if culprit is None or culprit in self.stubs or culprit == ctor:
                return None
            self._stub_out(culprit)
        return None

    def _block(self, _uc: Any, address: int, _size: int, _data: Any) -> None:
        self.path_hash = hash((self.path_hash, address))

    def _reset(self, variant: int) -> None:
        self.variant = variant
        self.path_hash = 0
        self.faulted = False
        fill = self.UNSET[variant]
        for va, images in self.data:
            self.uc.mem_write(va, images[variant])
        self.uc.mem_write(self.HEAP, bytes([fill]) * (self.heap_top - self.HEAP))
        self.uc.mem_write(self.BUF, bytes([self.POISON]) * self.BUF_SIZE)
        for page in self.pages:
            self.uc.mem_write(page, bytes([fill]) * 0x1000)
        self.heap_top = self.HEAP

    def _innermost_callee(self, top: int) -> Optional[int]:
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        if not self.STACK <= esp < top:
            return None
        for a in range(esp, top, 4):
            back = struct.unpack("<I", self.uc.mem_read(a, 4))[0] - 5
            if self.img.is_text(back) and self.img.read(back, 1) == b"\xe8":
                callee = back + 5 + struct.unpack("<i", self.img.read(back + 1, 4))[0]
                if callee not in self.thunks:
                    return callee
        return None

    def _map_page(self, uc: Any, _access: int, address: int, _size: int, _value: int,
                  _data: Any) -> bool:
        try:
            # readable and writable, never executable: running into one is a call
            # through a pointer the engine would have set up, which _run unwinds
            uc.mem_map(address & ~0xFFF, 0x1000, UC_PROT_READ | UC_PROT_WRITE)
            uc.mem_write(address & ~0xFFF, bytes([self.UNSET[self.variant]]) * 0x1000)
        except UcError:
            return False
        self.pages.append(address & ~0xFFF)
        return True

    def _return(self, value: int, pop: int = 0) -> None:
        uc = self.uc
        esp = uc.reg_read(UC_X86_REG_ESP)
        ret = struct.unpack("<I", uc.mem_read(esp, 4))[0]
        uc.reg_write(UC_X86_REG_EAX, value & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + pop)
        uc.reg_write(UC_X86_REG_EIP, ret)

    def _arg(self, k: int) -> int:
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        return struct.unpack("<I", self.uc.mem_read(esp + 4 + 4 * k, 4))[0]

    def _alloc(self, n: int) -> int:
        p = self.heap_top
        if p + n > self.HEAP + self.HEAP_SIZE:
            # a size read from poison
            self.faulted = True
            self.uc.emu_stop()
            return 0
        self.heap_top += (n + 15) & ~15
        return p

    def _new(self, _uc: Any, _address: int, _size: int, _data: Any) -> None:
        self._return(self._alloc(self._arg(0)))

    def _stub(self, _uc: Any, address: int, _size: int, _data: Any) -> None:
        if address in self.stubs:
            self._return(0x5A5A5A5A if self.variant else 0, self.stubs[address])

    def _stub_out(self, fn: int) -> None:
        if fn not in self.hooked:
            self.hooked.add(fn)
            self.uc.hook_add(UC_HOOK_CODE, self._stub, begin=fn, end=fn)
        self.stubs[fn] = _ret_imm(self.img, fn)

    def _import(self, _uc: Any, address: int, _size: int, _data: Any) -> None:
        _slot, dll, name = self.imports[(address - self.IMPORTS) // 4]
        if dll.startswith("msvcr"):
            self._crt(name)
        elif name in STDCALL_ARGS:
            self._return(0x5A5A5A5A if self.variant else 0, 4 * STDCALL_ARGS[name])
        else:
            # how many arguments it pops is unknown, so its caller cannot go on
            self.faulted = True
            self.uc.emu_stop()

    def _cstr(self, p: int) -> bytes:
        out = b""
        while len(out) < 0x1000:
            chunk = bytes(self.uc.mem_read(p + len(out), 64))
            if b"\0" in chunk:
                return out + chunk[:chunk.index(b"\0")]
            out += chunk
        return out

    def _compare(self, name: str) -> int:
        if name == "strlen":
            return len(self._cstr(self._arg(0)))
        if name == "memcmp":
            n = self._arg(2)
            a, b = (bytes(self.uc.mem_read(self._arg(k), n)) for k in (0, 1))
        else:
            a, b = self._cstr(self._arg(0)), self._cstr(self._arg(1))
            if name != "strcmp":
                a, b = a.lower(), b.lower()
        return (a > b) - (a < b)

    def _crt(self, name: str) -> None:
        uc, value = self.uc, 0
        if name == "memset":
            p, byte, n = self._arg(0), self._arg(1), self._arg(2)
            uc.mem_write(p, bytes([byte & 0xFF]) * n)
            value = p
        elif name in ("memcpy", "memmove"):
            dst, src, n = self._arg(0), self._arg(1), self._arg(2)
            uc.mem_write(dst, bytes(uc.mem_read(src, n)))
            value = dst
        elif name in ("malloc", "calloc"):
            n = self._arg(0) * (self._arg(1) if name == "calloc" else 1)
            value = self._alloc(n)
            if name == "calloc":
                uc.mem_write(value, bytes(n))
        elif name in ("strcmp", "_stricmp", "_strcmpi", "strlen", "memcmp"):
            value = self._compare(name)
        else:
            # anything else the C runtime does is outside what a constructor's defaults
            # can rest on, so make it fail the agreement test
            value = 0x5A5A5A5A if self.variant else 0
        self._return(value)


def _gdt_entry(base: int, limit: int, access: int, flags: int) -> bytes:
    return struct.pack("<Q", (limit & 0xFFFF) | ((base & 0xFFFFFF) << 16) | (access << 40)
                       | (((limit >> 16) & 0xF) << 48) | (flags << 52)
                       | (((base >> 24) & 0xFF) << 56))


def _ret_imm(img: Image, fn: int) -> int:
    for i in img.disasm(fn, 0x4000):
        if i.mnemonic == "ret":
            return int(i.op_str, 0) if i.op_str else 0
    return 0


def _imports(path: str) -> list[tuple[int, str, str]]:
    """Every import slot, with the lower-cased DLL and the name it imports."""
    pe = pefile.PE(path, fast_load=True)
    pe.parse_data_directories(
        directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
    return [(imp.address, dll.dll.decode().lower(),
             (imp.name or b"#%d" % imp.ordinal).decode())
            for dll in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) for imp in dll.imports]


def _import_thunks(img: Image, path: str) -> dict[int, str]:
    """`jmp [IAT slot]` thunk address -> the import it jumps to."""
    slots = {slot: name for slot, _dll, name in _imports(path)}
    thunks: dict[int, str] = {}
    at = img.text.find(b"\xff\x25")
    while at != -1:
        slot = struct.unpack_from("<I", img.text, at + 2)[0]
        if slot in slots:
            thunks[img.text_va + at] = slots[slot]
        at = img.text.find(b"\xff\x25", at + 1)
    return thunks


def emulated_values(runs: Optional[tuple[bytes, bytes]], kind: str,
                    off: int) -> dict[int, Any]:
    """The dwords (or, for a narrow type, the bytes) a field's default is rendered from,
    where both runs wrote the same thing; empty when they did not."""
    if runs is None or kind in ("AsciiString", "AsciiStringList"):
        return {}
    a, b = runs
    width = {"Bool": 1, "Int8": 1, "UInt8": 1, "UInt16": 2}.get(kind)
    if width:
        if off + width > len(a) or a[off:off + width] != b[off:off + width]:
            return {}
        if a[off:off + width] == bytes([Emulator.POISON]) * width:
            return {}
        return {off: int.from_bytes(a[off:off + width], "little")}
    out: dict[int, Any] = {}
    for k in range(COMPOSITE_TYPES.get(kind, (1,))[0]):
        lo, hi = off + 4 * k, off + 4 * k + 4
        if hi > len(a) or a[lo:hi] != b[lo:hi] or a[lo:hi] == bytes([Emulator.POISON]) * 4:
            return {}
        out[lo] = struct.unpack_from("<I", a, lo)[0]
    return out

def render_default(img: Image, kind: str, defaults: dict[int, Any], off: int,
                   members: list[str], pairs: list[tuple[str, int]]) -> Optional[str]:
    """A recovered default as an INI author would write it, or None if it cannot be.

    The constructor stores what the parser would have produced, so the parser's
    conversion is undone here: frames back to milliseconds, radians to degrees,
    per-frame rates to per-second ones, fractions to percentages, indices and masks to
    the names they stand for. The scale factors are the engine's own constants, read
    from the image. A null reference or an empty string comes out as `""`, which is a
    real default with nothing to write for it. A value the parser could never produce -
    `SlowDeathBehavior.FadeDelay`'s `0xFACADE00`, an unsigned `-1` - is a sentinel the
    engine tests for, and is shown in hex. A pointer that leaked through the tracker (a
    vtable, a string, a default object) is reported as unresolved rather than as a
    wrong number.
    """
    raw = defaults.get(off)
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if kind in REFERENCE_TYPES:
        return '""' if raw == 0 else None
    if isinstance(raw, int) and raw >= 0x400000 and img.section_of(raw) and kind not in FLOATY:
        return None
    if kind in FLOATY or kind in COMPOSITE_TYPES:
        return _render_real(img, kind, defaults, off)
    if not isinstance(raw, int):
        return None
    raw &= 0xFFFFFFFF
    signed = raw - (1 << 32) if raw & 0x80000000 else raw
    if kind == "Bool":
        return "Yes" if raw & 0xFF else "No"
    if kind == "Int":
        return str(signed)
    if kind == "Int8":
        return str((raw & 0xFF) - 0x100 if raw & 0x80 else raw & 0xFF)
    if kind == "UInt8":
        return str(raw & 0xFF)
    if kind == "UInt16":
        return str(raw & 0xFFFF)
    if kind == "UnsignedInt":
        return str(raw)
    if kind == "Duration":
        if raw >= 0x80000000:
            return "0x%08X" % raw
        return _num(raw / _f32(img, FRAMES_PER_MSEC))
    if kind == "Enum":
        return members[raw] if raw < len(members) else ('""' if signed == -1 else None)
    if kind == "LookupList":
        return next((name for name, value in pairs if value == raw), None)
    if kind in ("ModelConditionFlag", "EvaEvent"):
        if signed == -1:
            return '""'
        return members[raw] if raw < len(members) else None
    if kind in FLAG_TYPES:
        if raw == 0:
            return "NONE" if kind in ACCEPTS_NONE else '""'
        if raw == 0xFFFFFFFF and kind in ACCEPTS_ALL:
            return "ALL"
        if len(members) > 32 or any(bit >= len(members) for bit in range(32) if raw >> bit & 1):
            return None
        return " ".join(members[bit] for bit in range(32) if raw >> bit & 1)
    if kind in TYPE_TABLES:
        if signed == -1:
            return '""'
        return members[raw] if raw < len(members) else None
    if kind == "UpgradeMask":
        return '""' if raw == 0 else None
    return None


def _f32(img: Image, va: int) -> float:
    return struct.unpack("<f", img.read(va, 4))[0]


def _num(value: float) -> str:
    return "%.6g" % value


def _real(raw: Any) -> Optional[float]:
    """A tracked value as the float it is: a `movss` already is one, an immediate store
    is its bit pattern."""
    if isinstance(raw, float):
        return raw
    if not isinstance(raw, int):
        return None
    value = struct.unpack("<f", struct.pack("<I", raw & 0xFFFFFFFF))[0]
    return None if value != value else value


def _render_real(img: Image, kind: str, defaults: dict[int, Any], off: int) -> Optional[str]:
    if kind == "RGBAColor":
        raw = defaults.get(off)
        if not isinstance(raw, int):
            return None
        argb = raw & 0xFFFFFFFF
        return "R:%d G:%d B:%d A:%d" % (argb >> 16 & 0xFF, argb >> 8 & 0xFF, argb & 0xFF,
                                        argb >> 24)
    if kind == "Coord2DInt":
        parts = [defaults.get(off + 4 * k) for k in range(2)]
        if not all(isinstance(p, int) for p in parts):
            return None
        return "X:%d Y:%d" % tuple(p - (1 << 32) if p & 0x80000000 else p for p in parts)
    count, labels = COMPOSITE_TYPES.get(kind, (1, ("",)))
    values = [_real(defaults.get(off + 4 * k)) for k in range(count)]
    if any(v is None for v in values):
        return None
    reals: list[float] = [v for v in values if v is not None]
    if kind == "RGBColor":
        return " ".join("%s:%d" % (label, round(v * 255))
                        for label, v in zip(labels, reals, strict=True))
    if count > 1:
        return " ".join("%s:%s" % (label, _num(v))
                        for label, v in zip(labels, reals, strict=True))
    value = reals[0]
    if kind == "Percent":
        return _num(value * 100) + "%"
    if kind == "AngleReal":
        return _num(value / _f32(img, RADIANS_PER_DEGREE))
    if kind == "DurationReal":
        return _num(value / _f32(img, FRAMES_PER_MSEC))
    if kind == "VelocityReal":
        return _num(value / _f32(img, SECONDS_PER_FRAME))
    if kind == "AngularVelocityReal":
        return _num(value / (_f32(img, SECONDS_PER_FRAME) * _f32(img, RADIANS_PER_DEGREE)))
    return _num(value)


def field_type(img: Image, keyword: str, parse: int,
               blocks: dict[str, dict[str, Any]]) -> str:
    """The type name for a field, registering the sub-block schema behind it.

    An unidentified parse function that reads a nested block is a sub-block type;
    unless it is shared between keywords, the keyword that takes it names it. The
    block's own schema comes from its field table where it has one, and from the
    keywords it compares tokens against where it parses by hand.
    """
    if parse in PARSE_TYPES:
        return PARSE_TYPES[parse]
    name = BLOCK_TYPES.get(parse, keyword)
    if name in blocks and blocks[name]["parse_fn"] == parse:
        return name
    # a nested block may have a single keyword; the table's shape still has to hold
    rows = field_table_of(img, parse, min_rows=1) or registered_rows(img, parse)
    words = [kw for kw, _fn, _ud, _off in rows] or block_keywords(img, parse)
    if not rows and len(words) < 2 and parse not in BLOCK_TYPES:
        return "0x%08x" % parse
    if name in blocks:
        # Another parser already took the name. Several wrap the same block - the
        # `ArmorSet` an `AddModule` takes is the one an `Object` takes - and then it is
        # the same type; a block with other keywords is not, and keeps its address.
        return name if blocks[name]["keywords"] == words else "0x%08x" % parse
    # registered before its own fields are typed, so a block nested in itself ends
    entry: dict[str, Any] = {"parse_fn": parse, "keywords": words, "fields": []}
    blocks[name] = entry
    entry["fields"] = [{"name": kw, "type": field_type(img, kw, fn, blocks),
                        "parse_fn": fn, "offset": off}
                       for kw, fn, _ud, off in rows]
    return name


class Catalogue:
    """The shared side-tables an extraction fills in: enums, lookups, sub-blocks."""

    def __init__(self) -> None:
        self.blocks: dict[str, dict[str, Any]] = {}
        self.tables: dict[str, list[str]] = {}
        self.lookups: dict[str, list[tuple[str, int]]] = {}
        self.conflicts: list[str] = []

    def field(self, img: Image, row: tuple[str, int, int, int], defaults: dict[int, Any],
              runs: Optional[tuple[bytes, bytes]] = None, owner: str = "") -> FieldInfo:
        """One field-table row as a typed field, registering what it points at.

        The default is the emulated constructor's where its two runs agree, and the
        constant tracker's otherwise. Where both have one and they differ, the
        emulator's stands - it ran the code - and the disagreement is recorded.
        """
        keyword, parse, ud, off = row
        kind = field_type(img, keyword, parse, self.blocks)
        ud = ud or PARSER_TABLES.get(parse, 0)
        members = name_table(img, ud) if ud else []
        pairs = lookup_table(img, ud) if kind == "LookupList" and ud else []
        if len(members) > 1 and kind != "LookupList":
            self.tables.setdefault("0x%08x" % ud, members)
        elif len(pairs) > 1:
            self.lookups.setdefault("0x%08x" % ud, pairs)
        else:
            ud = 0
        if kind in TYPE_TABLES:
            members = name_table(img, NAME_TABLES[TYPE_TABLES[kind]])
        tracked = render_default(img, kind, defaults, off, members, pairs)
        emulated = render_default(img, kind, emulated_values(runs, kind, off), off,
                                  members, pairs)
        if tracked is not None and emulated is not None and tracked != emulated:
            self.conflicts.append("%s.%s [%s]: tracked %s, emulated %s"
                                  % (owner, keyword, kind, tracked, emulated))
        return FieldInfo(
            name=keyword,
            offset=off,
            type=kind,
            parse_fn=parse,
            userdata="0x%08x" % ud if ud else None,
            default=emulated if emulated is not None else tracked,
        )


def alloc_ctor(img: Image, fn: int) -> Optional[int]:
    """The constructor a block parser runs on the instance it allocates, if it does.

    Some block types are allocated and constructed right there in the parser, which
    puts their defaults within reach of the same constant tracking modules use. The
    ones built through a factory elsewhere are not, and get no defaults.
    """
    size: Optional[int] = None
    pending: Optional[int] = None
    for i in img.disasm(fn, 0x600):
        if i.mnemonic == "push" and i.op_str.startswith("0x"):
            value = int(i.op_str, 16)
            if 4 <= value <= 0x8000:
                pending = value
        elif i.mnemonic == "call" and i.op_str.startswith("0x"):
            target = int(i.op_str, 16)
            if target in OPERATOR_NEW and size is None:
                size = pending
            elif target not in HELPERS and size is not None:
                return target
    return None


def ini_blocks(img: Image, cat: Catalogue, emu: Emulator) -> dict[str, dict[str, Any]]:
    """Every INI block keyword whose parser owns a field table.

    The loader dispatches a block on `{keyword, parser}` pairs sitting in the data
    sections, or registered at startup through `INI::registerBlock`. Rather than trust
    the pairs - a string next to a function pointer is a common enough accident - each
    candidate is kept only if its parser really does hand a field table to the INI
    reader, which is what makes it a block type at all.
    """
    candidates: dict[str, set[int]] = {}
    for name, va0, size, _fo in img.sections:
        if name not in (".rdata", ".data"):
            continue
        for va in range(va0, va0 + size - 8, 4):
            strp, fn = img.u32(va), img.u32(va + 4)
            if not strp or not fn or not img.is_text(fn):
                continue
            if not _is_data(img, strp):
                continue
            keyword = img.cstr(strp, 48)
            if keyword and INI_KEYWORD.match(keyword):
                candidates.setdefault(keyword, set()).add(fn)
    for call in img.calls_to(INI_REGISTER_BLOCK):
        pushed: list[int] = []
        for start in range(call - 16, call - 9):
            ins = list(img.disasm(start, call - start))
            if ins and ins[-1].address + ins[-1].size == call:
                pushed = [int(i.op_str, 16) for i in ins
                          if i.mnemonic == "push" and i.op_str.startswith("0x")][-2:]
                if len(pushed) == 2:
                    break
        if len(pushed) == 2 and img.is_text(pushed[0]) and _is_data(img, pushed[1]):
            keyword = img.cstr(pushed[1], 48)
            if keyword and INI_KEYWORD.match(keyword):
                candidates.setdefault(keyword, set()).add(pushed[0])

    # A field-table row is a keyword next to a parse function too, so a keyword often
    # has several candidates: the block parser that owns its whole schema, and the leaf
    # parsers of same-named fields elsewhere. The fullest table is the block's.
    rows_of: dict[int, list[tuple[str, int, int, int]]] = {}
    out: dict[str, dict[str, Any]] = {}
    for keyword, fns in sorted(candidates.items()):
        best: list[tuple[str, int, int, int]] = []
        chosen = 0
        for fn in sorted(fns):
            if fn not in rows_of:
                rows_of[fn] = field_table_of(img, fn, max_offset=0x10000, limit=500,
                                             maxdepth=2)
            if len(rows_of[fn]) > len(best):
                best, chosen = rows_of[fn], fn
        if len(best) < INI_BLOCK_MIN_FIELDS:
            continue
        ctor = alloc_ctor(img, chosen)
        bases: dict[int, int] = {}
        defaults = ctor_defaults(img, ctor, bases=bases) if ctor else {}
        defaults = _drop_stray(defaults, bases, [(row[3], 0) for row in best])
        runs = emu.run(ctor) if ctor else None
        fields = [cat.field(img, row, defaults, runs, keyword) for row in best]
        out[keyword] = {
            "parse_fn": chosen,
            "moduledata_ctor": ctor,
            "fields": sorted(fields, key=lambda f: f["name"].lower()),
        }
    # What is left is read in a way no table address in the code gives away: a table
    # assembled on the stack or filled in on first use, a single-keyword table, one
    # behind a getter. Running the parser shows the table it really passes.
    reaches: dict[tuple[int, int], bool] = {}
    for keyword, fns in sorted(candidates.items()):
        if keyword in out:
            continue
        for fn in sorted(fns):
            if not _reaches(img, fn, (INI_PARSE_FIELDS, INI_PARSE_MULTI), reaches):
                continue
            got = emu.capture(fn) or (virtual_rows(img, fn, keyword), None)
            if not got[0]:
                continue
            rows, runs = got
            out[keyword] = {
                "parse_fn": fn,
                "moduledata_ctor": None,
                "fields": sorted((cat.field(img, row, {}, runs, keyword) for row in rows),
                                 key=lambda f: f["name"].lower()),
            }
            break
    return dict(sorted(out.items()))


def virtual_rows(img: Image, parser: int, keyword: str) -> list[tuple[str, int, int, int]]:
    """The rows of a block whose parser asks a global object for its table.

    `InGameUI` hands the reader whatever `TheInGameUI->getFieldParse()` returns, a
    virtual call on an object only the running game creates. Of the classes whose vtable
    has a table getter in that slot, the block's own is the one that also names itself
    after the block keyword.
    """
    ins = list(img.disasm(parser, 0x80))
    if not any(i.mnemonic == "call" and i.op_str == "0x%x" % INI_PARSE_FIELDS for i in ins):
        return []
    slots = [re.fullmatch(r"dword ptr \[e[abcd]x \+ (0x[0-9a-f]+)\]", i.op_str)
             for i in ins if i.mnemonic == "call"]
    slot = next((int(m.group(1), 16) for m in slots if m), None)
    if slot is None:
        return []
    tables: set[int] = set()
    for name, va0, size, _fo in img.sections:
        if name != ".rdata":
            continue
        for va in range(va0, va0 + size - slot - 4, 4):
            getter = img.u32(va + slot)
            if not img.is_text(getter) or not img.is_text(img.u32(va)):
                continue
            table = const_return(img, getter)
            if not table or not _looks_like_table(img, table):
                continue
            # the name getter sits in the same vtable, or in the one just before it
            for at in range(va - 0x10, va + slot, 4):
                named = const_return(img, img.u32(at)) if img.is_text(img.u32(at)) else None
                if named and _is_data(img, named) and img.cstr(named, 64) == keyword:
                    tables.add(table)
                    break
    if len(tables) != 1:
        return []
    rows = parse_table(img, tables.pop(), 500)
    return rows if all(img.is_text(r[1]) for r in rows) else []


def _reaches(img: Image, fn: int, targets: tuple[int, ...],
             memo: dict[tuple[int, int], bool], depth: int = 2) -> bool:
    """Whether `fn` calls one of `targets`, itself or through at most `depth` callees."""
    if (fn, depth) in memo:
        return memo[fn, depth]
    memo[fn, depth] = False
    calls = [int(i.op_str, 16) for i in img.disasm(fn, 0x600)
             if i.mnemonic in ("call", "jmp") and i.op_str.startswith("0x")]
    found = any(t in targets for t in calls) or depth > 0 and any(
        img.is_text(t) and t not in HELPERS and _reaches(img, t, targets, memo, depth - 1)
        for t in calls)
    memo[fn, depth] = found
    return found


def extract(img: Image) -> tuple[list[ModuleInfo], dict[str, Any], list[str]]:
    """Every registered module with its fields, plus the types those fields use.

    The second return value carries what a field's type alone cannot: the member
    names behind every enum and flag type, the keywords of every sub-block, and the
    INI block types that are read the same way modules are. The third lists every
    default on which constant tracking and emulation disagree.
    """
    mods: list[ModuleInfo] = []
    cat = Catalogue()
    emu = Emulator(img, img.path)
    blocks, tables, lookups = cat.blocks, cat.tables, cat.lookups
    reg = [(name, mask) + moduledata_info(img, md)
           for name, inst, md, mask in registrations(img)]
    # A base class is usually a registered module in its own right, which is what lets
    # an inherited field name where it came from. Two things stop that being exact: the
    # purely abstract bases (`DockUpdate`, `SpecialPowerUpdate`) are never registered,
    # and several keywords can share one ModuleData class (`ActiveBody` is also
    # `ImmortalBody`), in which case the first registered wins the name.
    declared_by: dict[int, str] = {}
    for name, _mask, _size, _ctor, bfp in reg:
        if bfp and name:
            declared_by.setdefault(bfp, name)
    for name, mask, size, ctor, bfp in reg:
        bases: dict[int, int] = {}
        defaults = ctor_defaults(img, ctor, bases=bases)
        rows: list[tuple[tuple[str, int, int, int], int, int]] = []
        seen: set[str] = set()
        for tab, source, extra in field_tables(img, bfp):
            for keyword, parse, ud, off in parse_table(img, tab):
                if keyword not in seen:
                    seen.add(keyword)
                    rows.append(((keyword, parse, ud, off + extra), source, extra))
        defaults = _drop_stray(defaults, bases, [(row[3], extra) for row, _, extra in rows])
        runs = emu.run(ctor) if ctor else None
        fields: list[FieldInfo] = []
        for row, source, _extra in rows:
            field = cat.field(img, row, defaults, runs, name or "")
            if source != bfp:
                field["inherited"] = True
                if source in declared_by:
                    field["inherited_from"] = declared_by[source]
            fields.append(field)
        mods.append(ModuleInfo(
            name=name,
            interface_mask=mask,
            moduledata_size=size,
            moduledata_ctor=ctor,
            fields=sorted(fields, key=lambda f: f["name"].lower()),
        ))
    enums: dict[str, str] = {}
    types: dict[str, str] = {}
    for enum, va in NAME_TABLES.items():
        members = name_table(img, va)
        if not members or members[0] != NAME_TABLE_HEADS[enum]:
            raise ValueError("%s: no name array at 0x%08x (found %r)"
                             % (enum, va, members[:1]))
        tables["0x%08x" % va] = members
        enums[enum] = "0x%08x" % va
        for type_name, target in TYPE_TABLES.items():
            if target == enum:
                types[type_name] = "0x%08x" % va
    ini = ini_blocks(img, cat, emu)
    return (sorted(mods, key=lambda m: (m["name"] or "").lower()),
            {"name_tables": tables, "lookup_tables": lookups, "enums": enums,
             "types": types, "blocks": dict(sorted(blocks.items())),
             "ini_blocks": ini},
            cat.conflicts)


def to_markdown(mods: list[ModuleInfo]) -> str:
    total = sum(len(m["fields"]) for m in mods)
    known = sum(1 for m in mods for f in m["fields"] if f["default"] is not None)
    unlabelled = sum(1 for m in mods for f in m["fields"] if f["type"].startswith("0x"))
    lines = [
        "# Engine module reference - fields and compiled-in defaults",
        "",
        "Generated from `game.dat` by [`../scripts/module_defaults.py`](../scripts/module_defaults.py);",
        "regenerate rather than edit. **%d modules, %d fields, %d with a recovered "
        "default (%.0f%%).**"
        % (len(mods), total, known, 100.0 * known / total if total else 0),
        "",
        "A listed default is what the ModuleData constructor writes, so it is the value in",
        "force whenever an INI block omits that keyword. Field names and offsets come from",
        "the engine's own 16-byte-stride INI field-parse tables; defaults come from running",
        "each constructor in an emulator, and from constant-tracking through its",
        "instructions where emulation cannot vouch for a value.",
        "",
        "## Reading this",
        "",
        "- Defaults are written the way an INI author would write them: durations in",
        "  milliseconds, angles in degrees, speeds and turn rates per second, percentages",
        "  with `%`, enum and flag values by name. `\"\"` is an empty string, list or",
        "  reference. A value in hex is a sentinel the engine tests for and no INI value",
        "  produces it.",
        "- `-` in the default column means neither method could vouch for the value -",
        "  typically one the constructor looks up in game data loaded at startup. It does",
        "  not mean the field is unset.",
        "- `type` is derived from the field's parse function. %d fields (%.0f%%) use a"
        % (unlabelled, 100.0 * unlabelled / total if total else 0),
        "  parse function that has not been identified and show its raw address instead.",
        "- Offsets are into ModuleData, not into the module instance.",
        "- Types are checked for internal consistency: no `Bool` resolves to a non-boolean.",
        "  `AimWeaponBehavior.AimFarDistance` is a genuine `FLT_MAX`, and",
        "  `SlowDeathBehavior.FadeDelay`'s `0xFACADE00` is the constructor's own \"not set\".",
        "",
    ]
    for m in mods:
        if not m["fields"]:
            continue
        size = "0x%x" % m["moduledata_size"] if m["moduledata_size"] else "?"
        lines += ["## %s" % m["name"],
                  "",
                  "`sizeof(ModuleData)` = %s, %d field%s"
                  % (size, len(m["fields"]), "" if len(m["fields"]) == 1 else "s"),
                  "",
                  "| field | type | offset | default |",
                  "|---|---|---|---|"]
        for f in m["fields"]:
            lines.append("| `%s` | %s | `0x%x` | %s |"
                         % (f["name"], f["type"], f["offset"],
                            "`%s`" % f["default"] if f["default"] is not None else "-"))
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("binary", help="path to game.dat")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--markdown", dest="md_out")
    ap.add_argument("--enums", dest="enum_out",
                    help="write the enum, lookup, sub-block and INI block schemas here")
    args = ap.parse_args()

    img = Image(args.binary)
    mods, types, conflicts = extract(img)
    total = sum(len(m["fields"]) for m in mods)
    known = sum(1 for m in mods for f in m["fields"] if f["default"] is not None)
    print("modules: %d  fields: %d  defaults recovered: %d (%.0f%%)"
          % (len(mods), total, known, 100.0 * known / total if total else 0))
    print("tracked and emulated defaults disagree on %d field(s)" % len(conflicts))
    for line in conflicts:
        print("  " + line)
    print("enums: %d  lookups: %d  sub-blocks: %d  INI block types: %d"
          % (len(types["name_tables"]), len(types["lookup_tables"]), len(types["blocks"]),
             len(types["ini_blocks"])))

    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump(mods, fh, indent=1)
        print("wrote %s" % args.json_out)
    if args.md_out:
        with open(args.md_out, "w") as fh:
            fh.write(to_markdown(mods))
        print("wrote %s" % args.md_out)
    if args.enum_out:
        with open(args.enum_out, "w") as fh:
            json.dump(types, fh, indent=1)
        print("wrote %s" % args.enum_out)


if __name__ == "__main__":
    main()
