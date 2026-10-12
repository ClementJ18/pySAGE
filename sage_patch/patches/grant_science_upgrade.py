"""Add a `GrantScienceUpgrade` behaviour: when its upgrade triggers, the owning player is granted a
science, as Zero Hour's module of the same name did.

    Behavior = GrantScienceUpgrade ModuleTag_GrantAnduril
      TriggeredBy  = Upgrade_ReforgeNarsil
      GrantScience = SCIENCE_Anduril
    End

The module is registered by cloning `TooltipUpgrade`'s layout, as `object-image-upgrade` does, and
its Apply makes the two calls behind script action `PLAYER_GRANT_SCIENCE`: the science is looked up
by name and handed to `Player::grantScience`, which honours `IsGrantable`, ignores a science the
player already has, and wakes the powers gated on it. The grant is never revoked. The name is stored
in Tooltip's own `AsciiString` at ModuleData `+0x138`, so nothing is enlarged.
`GrantScienceUpgradeWorldbuilderPatch` teaches the editor the block.

Derivation: `../docs/grant-science-upgrade.md`.
"""

from __future__ import annotations

import struct

from sage_ini.engine import BlockDelta, Engine, FieldDelta

from ..addresses import (
    GAME_DATA_ASCIISTRING_PARSER,
    GRANT_SCIENCE_UPGRADE_REGISTER_CALL,
    OBJECT_GET_CONTROLLING_PLAYER,
    PLAYER_GRANT_SCIENCE,
    SCIENCE_STORE_FRIENDLY_NAME_TO_SCIENCE,
    THE_SCIENCE_STORE,
    WORLDBUILDER_GRANT_SCIENCE_UPGRADE_REGISTER_CALL,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER,
)
from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
    find_section,
    read_bytes,
    u32,
    va_to_offset,
)
from .utils import name_tables, tooltip_twin

__all__ = [
    "BLOCK_NAME",
    "FIELD",
    "GrantScienceUpgradePatch",
    "GrantScienceUpgradeWorldbuilderPatch",
    "SECTION_NAME",
    "WORLDBUILDER_SECTION_NAME",
]

SECTION_NAME = ".grntsci"
BLOCK_NAME = "GrantScienceUpgrade"
#: The one keyword, and the Tooltip ModuleData `AsciiString` it is parsed into.
FIELD = ("GrantScience", 0x138)

# AudioLoopUpgrade's addModule call: `push 0x650532` (ModuleData factory), `push 0x6504FA`
# (runtime factory), `mov ecx, edi`, the unwind-state store `mov [ebp-4], 0xD6`, then the call. The
# registration stub replays whatever six arguments it displaces, so which stock module it wraps
# does not matter - only that no other patch wraps the same one. TooltipUpgrade's call belongs to
# `object-image-upgrade`.
_REGISTER_PREFIX = bytes.fromhex("683205650068fa0465008bcfc745fcd6000000")
_REGISTER_BYTES = bytes.fromhex("e8cfc8ffff")


def _field_table(name_va: int, parser: int) -> bytes:
    return tooltip_twin.field_table([(name_va, parser, FIELD[1])])


class GrantScienceUpgradePatch(Patch):
    """Install the GrantScienceUpgrade module."""

    name = "grant-science-upgrade"
    author = "officialNecro"
    description = (
        "Adds a new Behavior GrantScienceUpgrade (Zero Hour's): when its TriggeredBy upgrade "
        "fires, the controlling player is granted the GrantScience science, as script action "
        "PLAYER_GRANT_SCIENCE does; never revoked"
    )

    @staticmethod
    def _layout(base: int) -> dict[str, int]:
        cursor = base
        out: dict[str, int] = {}
        for name, size in (
            ("upgrade", tooltip_twin.UPGRADE_VTABLE_SIZE),
            ("moduledata", tooltip_twin.MODULEDATA_VTABLE_SIZE),
            ("table", 2 * tooltip_twin.FIELD_ROW_SIZE),
        ):
            out[name] = cursor
            cursor += size
        for name, raw in (("block_name", BLOCK_NAME), ("field_name", FIELD[0])):
            out[name] = cursor
            cursor += len(raw) + 1
        out["code"] = (cursor + 3) & ~3
        return out

    def _assemble(self, base: int) -> Asm:
        layout = self._layout(base)
        a = Asm(layout["code"])

        # Entered in place of AudioLoopUpgrade's addModule call.
        tooltip_twin.emit_game_skeleton(
            a,
            block_name=layout["block_name"],
            upgrade_vtable=layout["upgrade"],
            moduledata_vtable=layout["moduledata"],
            table=layout["table"],
        )

        # UpgradeMux Apply, ECX = the mux. What script action PLAYER_GRANT_SCIENCE does, for the
        # object's controlling player: name -> ScienceType, then Player::grantScience.
        a.label("apply")
        a.emit(0x56, 0x57, b"\x8b\xf1")
        a.emit(b"\x8b\x7e", struct.pack("<b", tooltip_twin.MUX_OBJECT), b"\x85\xff")
        a.jcc(JE, "apply_done")
        a.emit(b"\x8b\x46", struct.pack("<b", tooltip_twin.MUX_MODULE_DATA))
        a.emit(b"\x05", u32(FIELD[1]))
        a.emit(b"\x83\x38\x00")  # cmp dword [eax],0 ; no GrantScience line
        a.jcc(JE, "apply_done")
        a.emit(0x50, b"\x8b\x0d", u32(THE_SCIENCE_STORE))
        a.call_absolute(SCIENCE_STORE_FRIENDLY_NAME_TO_SCIENCE)
        a.emit(b"\x83\xf8\xff")
        a.jcc(JE, "apply_done")
        a.emit(b"\x8b\xf0", b"\x8b\xcf")
        a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
        a.emit(b"\x85\xc0")
        a.jcc(JE, "apply_done")
        a.emit(0x56, b"\x8b\xc8")
        a.call_absolute(PLAYER_GRANT_SCIENCE)
        a.label("apply_done")
        a.emit(0x5F, 0x5E, 0xC3)

        # Unapply: a granted science stays granted.
        a.label("unapply")
        a.emit(0xC3)

        a.finish()
        return a

    def _code_bytes(self, base: int) -> bytes:
        return tooltip_twin.resolve_immediates(self._assemble(base), tooltip_twin.GAME_IMMEDIATES)

    def _build(self, data: bytes | bytearray, base: int) -> bytes:
        layout = self._layout(base)
        code = self._assemble(base)

        out = bytearray(
            tooltip_twin.copied_vtables(data, code.label_va("apply"), code.label_va("unapply"))
        )
        out += _field_table(layout["field_name"], GAME_DATA_ASCIISTRING_PARSER)
        out += BLOCK_NAME.encode() + b"\0"
        out += FIELD[0].encode() + b"\0"
        out += b"\0" * (-len(out) % 4)
        assert base + len(out) == layout["code"]
        out += self._code_bytes(base)
        return bytes(out)

    @staticmethod
    def _check_registration(data: bytes | bytearray) -> None:
        tooltip_twin.check_registration(
            data,
            GRANT_SCIENCE_UPGRADE_REGISTER_CALL,
            _REGISTER_PREFIX,
            _REGISTER_BYTES,
            "build: AudioLoopUpgrade",
        )

    def apply(self, data: bytearray) -> None:
        self._check_registration(data)
        base = allocate_section(
            data, SECTION_NAME, lambda va: self._build(data, va), tooltip_twin.CHARACTERISTICS
        )
        code = self._assemble(base)
        apply_byte_patch(
            data,
            va_to_offset(data, GRANT_SCIENCE_UPGRADE_REGISTER_CALL) or 0,
            _REGISTER_BYTES,
            call_rel32(GRANT_SCIENCE_UPGRADE_REGISTER_CALL, code.label_va("register")),
            "register GrantScienceUpgrade",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        base, section_off, _size = located
        code = self._assemble(base)
        expected = self._build(data, base)
        problems: list[str] = []
        if bytes(data[section_off : section_off + len(expected)]) != expected:
            problems.append(f"{SECTION_NAME} does not hold the expected vtables, table and code")
        want = call_rel32(GRANT_SCIENCE_UPGRADE_REGISTER_CALL, code.label_va("register"))
        if read_bytes(data, GRANT_SCIENCE_UPGRADE_REGISTER_CALL, len(want)) != want:
            problems.append(f"AudioLoopUpgrade registration does not point into {SECTION_NAME}")
        return problems

    def ini_surface(self) -> Engine:
        return Engine(
            blocks=(BlockDelta(BLOCK_NAME, base="UpgradeBehavior", patch=self.name),),
            fields=(FieldDelta(BLOCK_NAME, FIELD[0], "Ref:sciences", patch=self.name),),
        )


# The Worldbuilder half. The editor links its own engine copy and ModuleFactory, so the game-side
# registration does not teach it the block. Parser-only: the editor never fires upgrades.

# Eight bytes exactly: PE section names are not NUL-terminated when every byte is used.
WORLDBUILDER_SECTION_NAME = ".wbgrnts"

# Worldbuilder's AudioLoopUpgrade registration: `push 0xC8B7A0` (ModuleData factory), `push
# 0xC8B730` (runtime factory), `mov ecx, [ebp-0x4E8]` (the ModuleFactory), then the call.
# TooltipUpgrade's call, the one before it, belongs to `object-image-upgrade-wb`.
_WORLDBUILDER_REGISTER_PREFIX = bytes.fromhex("68a0b7c8006830b7c8008b8d18fbffff")
_WORLDBUILDER_REGISTER_BYTES = bytes.fromhex("e897e00100")


class GrantScienceUpgradeWorldbuilderPatch(Patch):
    """Teach **Worldbuilder** to parse the GrantScienceUpgrade behavior.

    **This patch targets `Worldbuilder.exe`, not `game.dat`.** It is the authoring half of
    `GrantScienceUpgradePatch`: the editor gains the block name and its `GrantScience` field.
    """

    name = "grant-science-upgrade-wb"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): register the GrantScienceUpgrade Behavior and its "
        "GrantScience field, so the editor can load object templates written for a game.dat "
        "carrying grant-science-upgrade; parser-only"
    )

    @staticmethod
    def _layout(base: int) -> dict[str, int]:
        cursor = base
        out: dict[str, int] = {"table": cursor}
        cursor += 2 * tooltip_twin.FIELD_ROW_SIZE
        for name, raw in (("block_name", BLOCK_NAME), ("field_name", FIELD[0])):
            out[name] = cursor
            cursor += len(raw) + 1
        out["code"] = (cursor + 3) & ~3
        return out

    def _assemble(self, base: int) -> Asm:
        layout = self._layout(base)
        a = Asm(layout["code"])

        # Entered in place of AudioLoopUpgrade's addModule call.
        tooltip_twin.emit_worldbuilder_skeleton(
            a, block_name=layout["block_name"], table=layout["table"]
        )

        a.finish()
        return a

    def _code_bytes(self, base: int) -> bytes:
        return tooltip_twin.resolve_immediates(
            self._assemble(base), tooltip_twin.WORLDBUILDER_IMMEDIATES
        )

    def _build(self, base: int) -> bytes:
        layout = self._layout(base)
        out = bytearray(
            _field_table(layout["field_name"], WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER)
        )
        out += BLOCK_NAME.encode() + b"\0"
        out += FIELD[0].encode() + b"\0"
        out += b"\0" * (-len(out) % 4)
        assert base + len(out) == layout["code"]
        out += self._code_bytes(base)
        return bytes(out)

    @staticmethod
    def _check_registration(data: bytes | bytearray) -> None:
        tooltip_twin.check_registration(
            data,
            WORLDBUILDER_GRANT_SCIENCE_UPGRADE_REGISTER_CALL,
            _WORLDBUILDER_REGISTER_PREFIX,
            _WORLDBUILDER_REGISTER_BYTES,
            "Worldbuilder build: AudioLoopUpgrade",
        )

    def apply(self, data: bytearray) -> None:
        name_tables.check_not_rebased(data)
        self._check_registration(data)
        base = allocate_section(
            data, WORLDBUILDER_SECTION_NAME, self._build, tooltip_twin.CHARACTERISTICS
        )
        code = self._assemble(base)
        apply_byte_patch(
            data,
            va_to_offset(data, WORLDBUILDER_GRANT_SCIENCE_UPGRADE_REGISTER_CALL) or 0,
            _WORLDBUILDER_REGISTER_BYTES,
            call_rel32(WORLDBUILDER_GRANT_SCIENCE_UPGRADE_REGISTER_CALL, code.label_va("register")),
            "register GrantScienceUpgrade in Worldbuilder",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, WORLDBUILDER_SECTION_NAME)
        if located is None:
            return [f"no {WORLDBUILDER_SECTION_NAME} section: the file does not carry this patch"]
        base, section_off, _size = located
        code = self._assemble(base)
        expected = self._build(base)
        problems: list[str] = []
        if bytes(data[section_off : section_off + len(expected)]) != expected:
            problems.append(
                f"{WORLDBUILDER_SECTION_NAME} does not hold the expected field table and code"
            )
        want = call_rel32(
            WORLDBUILDER_GRANT_SCIENCE_UPGRADE_REGISTER_CALL, code.label_va("register")
        )
        if read_bytes(data, WORLDBUILDER_GRANT_SCIENCE_UPGRADE_REGISTER_CALL, len(want)) != want:
            problems.append(
                "Worldbuilder AudioLoopUpgrade registration does not point into "
                f"{WORLDBUILDER_SECTION_NAME}"
            )
        return problems
