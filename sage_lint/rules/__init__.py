"""Lint rules. Importing this package registers the concrete rules in `RULES`."""

from sage_lint.rules.assets import (
    MapFolderNameRule,
    MissingMapFileRule,
    MissingModelFileRule,
    MissingTextureFileRule,
)
from sage_lint.rules.base import RULES, Rule, run_rules
from sage_lint.rules.commandset import CommandSetButtonRule
from sage_lint.rules.definitions import (
    DuplicateDefinitionRule,
    UnusedDefinitionRule,
    UnusedObjectRule,
)
from sage_lint.rules.macros import UndefinedMacroRule
from sage_lint.rules.map_ini import MapBareModuleRule
from sage_lint.rules.module_ops import ModuleOperationRule
from sage_lint.rules.module_refs import ModuleTagReferenceRule
from sage_lint.rules.modules import UnrecognizedBlockRule
from sage_lint.rules.references import DanglingAssetReferenceRule, DanglingReferenceRule
from sage_lint.rules.respawn import RespawnLevelRule, RespawnOrderRule
from sage_lint.rules.schema import (
    OutOfRangeRule,
    RepeatedScalarFieldRule,
    SpuriousBlockLabelRule,
    UnknownAttributeRule,
)
from sage_lint.rules.strings import UnknownStringLabelRule

__all__ = [
    "RULES",
    "CommandSetButtonRule",
    "DanglingAssetReferenceRule",
    "DanglingReferenceRule",
    "DuplicateDefinitionRule",
    "MapBareModuleRule",
    "MapFolderNameRule",
    "MissingMapFileRule",
    "MissingModelFileRule",
    "MissingTextureFileRule",
    "ModuleOperationRule",
    "ModuleTagReferenceRule",
    "OutOfRangeRule",
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
