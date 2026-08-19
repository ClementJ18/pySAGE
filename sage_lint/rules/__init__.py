"""Lint rules. Importing this package registers the concrete rules in `RULES`."""

from sage_lint.rules.asset_dat import AssetDatMissingModelRule, AssetDatMissingTextureRule
from sage_lint.rules.assets import (
    MapFolderNameRule,
    MissingMapFileRule,
    MissingModelFileRule,
    MissingTextureFileRule,
)
from sage_lint.rules.base import RULES, Rule, run_rules
from sage_lint.rules.commandset import (
    CommandSetButtonRule,
    DuplicateReviveButtonRule,
    InitialVisibleLimitRule,
    PushCommandRangeOverflowRule,
)
from sage_lint.rules.definitions import (
    DuplicateDefinitionRule,
    UnusedDefinitionRule,
    UnusedObjectRule,
)
from sage_lint.rules.experience import ExperienceLevelConflictRule
from sage_lint.rules.macros import UndefinedMacroRule
from sage_lint.rules.map_ini import MapBareModuleRule
from sage_lint.rules.modifier_fx import ModifierFxDurationRule
from sage_lint.rules.module_ops import ModuleOperationRule
from sage_lint.rules.module_refs import ModuleTagReferenceRule
from sage_lint.rules.modules import UnrecognizedBlockRule
from sage_lint.rules.references import DanglingAssetReferenceRule, DanglingReferenceRule
from sage_lint.rules.respawn import RespawnLevelRule, RespawnOrderRule
from sage_lint.rules.schema import (
    OutOfRangeRule,
    PatchedOutFieldRule,
    RepeatedScalarFieldRule,
    SpuriousBlockLabelRule,
    UnknownAttributeRule,
)
from sage_lint.rules.strings import MapLocalStringRule, UnknownStringLabelRule

__all__ = [
    "RULES",
    "AssetDatMissingModelRule",
    "AssetDatMissingTextureRule",
    "CommandSetButtonRule",
    "DanglingAssetReferenceRule",
    "DanglingReferenceRule",
    "DuplicateDefinitionRule",
    "DuplicateReviveButtonRule",
    "ExperienceLevelConflictRule",
    "InitialVisibleLimitRule",
    "MapBareModuleRule",
    "MapFolderNameRule",
    "MapLocalStringRule",
    "MissingMapFileRule",
    "MissingModelFileRule",
    "MissingTextureFileRule",
    "ModifierFxDurationRule",
    "ModuleOperationRule",
    "ModuleTagReferenceRule",
    "OutOfRangeRule",
    "PatchedOutFieldRule",
    "PushCommandRangeOverflowRule",
    "RepeatedScalarFieldRule",
    "RespawnLevelRule",
    "RespawnOrderRule",
    "Rule",
    "SpuriousBlockLabelRule",
    "UndefinedMacroRule",
    "UnknownAttributeRule",
    "UnrecognizedBlockRule",
    "UnknownStringLabelRule",
    "UnusedDefinitionRule",
    "UnusedObjectRule",
    "run_rules",
]
