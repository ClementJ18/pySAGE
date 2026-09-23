"""Addresses in RotWK 2.01's `Worldbuilder.exe` (not `game.dat`)."""

from __future__ import annotations

__all__ = [
    "WORLDBUILDER_ASCIISTRING_SET",
    "WORLDBUILDER_ASCIISTRING_SET_2",
    "WORLDBUILDER_ASCIISTRING_SET_LENGTH",
    "WORLDBUILDER_OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE",
    "WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_CTOR",
    "WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_DTOR",
    "WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER",
    "WORLDBUILDER_OBJECT_IMAGE_UPGRADE_BUILD_UPGRADE_FIELDS",
    "WORLDBUILDER_OBJECT_IMAGE_UPGRADE_MODULEDATA_CTOR",
    "WORLDBUILDER_OBJECT_IMAGE_UPGRADE_OPERATOR_NEW",
    "WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER",
    "WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL",
    "WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CLEANUP",
    "WORLDBUILDER_OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK",
    "WORLDBUILDER_PARAMETER_UI_TEXT_SWITCH",
    "WORLDBUILDER_SCRIPT_ACTION_TEMPLATES_INIT",
    "WORLDBUILDER_SCRIPT_CONDITION_TEMPLATES_INIT",
    "WORLDBUILDER_SCRIPT_TEMPLATE_FLAGS_OR",
    "WORLDBUILDER_STRLEN",
]

# Worldbuilder.exe's independent copy of the ObjectImageUpgrade registration dependencies.
# Derived from the original RotWK 2.01 editor in `docs/object-image-upgrade.md`: the registration
# is TooltipUpgrade's entry in the monolithic ModuleFactory initializer, while the constructor,
# field-table builder and parser are the editor's own debug-build copies. These must never be
# replaced with the numerically unrelated `game.dat` addresses above.
WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL = 0x00C75BBF
WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER = 0x00C93CC0
WORLDBUILDER_OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK = 0x00C8B4A0
WORLDBUILDER_OBJECT_IMAGE_UPGRADE_MODULEDATA_CTOR = 0x00C8B5A0
WORLDBUILDER_OBJECT_IMAGE_UPGRADE_OPERATOR_NEW = 0x006FC1A0
WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CLEANUP = 0x006D2050
WORLDBUILDER_OBJECT_IMAGE_UPGRADE_BUILD_UPGRADE_FIELDS = 0x00BEA580
WORLDBUILDER_OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE = 0x006CD090
WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER = 0x006D4C30
# Use the same jump thunks the stock registration sequence calls, not private local aliases.
WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_CTOR = 0x00402EE1
WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_DTOR = 0x0040B0E6
# Worldbuilder.exe's script template tables (`docs/worldbuilder-script-templates.md`). Two
# debug-build functions fill fixed 0x80-byte records from `this+0x20`: actions at records 0-599,
# conditions from record 600. Both take the table owner in ecx and end at their only `ret`.
WORLDBUILDER_SCRIPT_ACTION_TEMPLATES_INIT = 0x00FE0AF0
WORLDBUILDER_SCRIPT_CONDITION_TEMPLATES_INIT = 0x00FD8100
# `push b; push a; call` returning `a | b`, the value stored in a record's flags field.
WORLDBUILDER_SCRIPT_TEMPLATE_FLAGS_OR = 0x00FF3380
# The AsciiString setters those functions call with the destination in ecx: two `(const char *)`
# thunks, and the `(const char *, length)` routine behind them that inlined sets call directly.
WORLDBUILDER_ASCIISTRING_SET = 0x00405191
WORLDBUILDER_ASCIISTRING_SET_2 = 0x00402513
WORLDBUILDER_ASCIISTRING_SET_LENGTH = 0x00710DC0
# The CRT `strlen` the inlined sets measure their literal with.
WORLDBUILDER_STRLEN = 0x016C368C
# `Parameter::getUiText`'s jump table over the 78 parameter types (`cmp type, 0x4d`); each case
# prints one argument, and the enum cases hold their value names.
WORLDBUILDER_PARAMETER_UI_TEXT_SWITCH = 0x00AAE408
