"""Block-opening keywords. A `Key = Value` line is syntactically identical whether it is a
plain attribute or a `... End` block header, so the block parser consults these curated
lists to disambiguate; a missing opener surfaces as an `End`-imbalance diagnostic rather
than silent mis-nesting. Bootstrapped by `tools/scan_block_keywords.py`, then curated by hand.
"""

BLOCK_OPENING_KEYWORDS: frozenset[str] = frozenset(
    {
        "Animation",
        "AnimationState",
        "AudioLOD",
        "Behavior",
        "Body",
        "ClientBehavior",
        "ClientUpdate",
        "ConditionState",
        "Draw",
        "DynamicGameLOD",
        "LodOptions",
        "MeleeBehavior",
        "ModelConditionState",
        "RadiusCursorTemplate",
        "SoundState",
        "SoundUpgrade",
        "SpawnArmies",
        "StaticGameLOD",
        "ThreatBreakdown",
        "TransitionState",
    }
)

# Keys that open a block only under a specific parent block. Needed where a
# key is an opener in one context and a plain attribute elsewhere:
# `Color = DefaultColor ... End` inside FXParticleSystem vs
# `Color = R:64 G:64 B:96` in draw modules.
CONTEXTUAL_BLOCK_OPENERS: dict[str, frozenset[str]] = {
    "FXParticleSystem": frozenset(
        {
            "Alpha",
            "Color",
            "Emitter",
            "EmissionVelocity",
            "EmissionVolume",
            "Event",
            "Physics",
            "Update",
            "Wind",
        }
    ),
    "Window": frozenset({"Transition"}),
}

# Value shapes that open a block regardless of the key: `Radius = FCurve`,
# `Angle = FCurve`, ... each carry a curve body terminated by End.
OPENER_VALUE_TOKENS: frozenset[str] = frozenset({"FCurve"})

# Keys that open a block only when the value starts with a marker token:
# `AddEmotion = OVERRIDE Taunt_Base ... End` is a block, while plain
# `AddEmotion = Terror_Base` is an attribute.
CONDITIONAL_VALUE_OPENERS: dict[str, str] = {
    "AddEmotion": "OVERRIDE",
}

# Bare lines (no '=') open blocks by default; these first tokens are the
# exceptions - value lines like `ParticleSysBone NONE GoldChestGlimmer`.
# A value key missing from this list surfaces as unclosed-block diagnostics.
BARE_VALUE_KEYS: frozenset[str] = frozenset(
    {
        "AnimationSpeedFactorRange",
        "AttributeModifier",
        "Blank",
        "BoneSpecificConditionState",
        "BuildUpClockColor",
        "ButtonBorderActionColor",
        "ButtonBorderAlteredColor",
        "ButtonBorderBuildColor",
        "ButtonBorderSystemColor",
        "ButtonBorderUpgradeColor",
        "ClearNuggets",
        "CommandBarBorderColor",
        "ConflictsWith",
        "CrewPrepareInterval",
        "DamagedHideSubObject",
        "DamagedShowSubObject",
        "Delay",
        "EvaEventForwardReference",
        "Geometry",
        "GeometryContactPoint",
        "GeometryName",
        "ImageName",
        "Intensity",
        "Layer",
        "ParticleSysBone",
        "Position",
        "PristineHideSubObject",
        "PristineShowSubObject",
        "ReallyDamagedHideSubObject",
        "ReallyDamagedShowSubObject",
        "RemoveModule",
        "RubbleNeighbor",
        "Scale",
        "ScreenCreationRes",
        "ShadowColor",
        "Side",
        "Size",
        "StateName",
        "Time",
        "WeaponFireFXBone",
        "WeatherTexture",
    }
)

# Bare value keys that only apply under a specific parent, where the same
# token is a block opener elsewhere: `CommandSet X` is a top-level block in
# commandset.ini but a sloppy equals-less attribute inside an Object.
CONTEXTUAL_BARE_VALUE_KEYS: dict[str, frozenset[str]] = {
    "Object": frozenset({"CommandSet"}),
}
