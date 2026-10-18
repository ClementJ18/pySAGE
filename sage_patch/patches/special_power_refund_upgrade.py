"""Add a `SpecialPowerRefundUpgrade` behaviour: when its upgrade triggers, a named power on the
owning player's spellbook comes ready sooner, by a percentage of the cooldown it is running.

    Behavior = SpecialPowerRefundUpgrade ModuleTag_MerchantRefund
      TriggeredBy   = Upgrade_MerchantLeaves
      ConflictsWith = Upgrade_MerchantOrder
      SpecialPower  = SpellBookSummonTravellingMerchant
      RefundPercent = 50%
    End

With `RestartCooldown = Yes` the module instead starts the named power's cooldown over, at its
full length from now, whether or not it is running: the power's own `startPowerRecharge(1.0)`,
the call a cast makes. That is for a power whose result the player can give back, such as a
permanent summon sent away by an upgrade button on the summoned object:

    Behavior = SpecialPowerRefundUpgrade ModuleTag_SendAwayCooldown
      TriggeredBy     = Upgrade_SendAwayEnt
      SpecialPower    = SpellBookSummonEnt
      RestartCooldown = Yes
    End

The engine fixes a cooldown once, as an absolute ready frame, and nothing in INI can move it
afterwards. Map scripts can: `PLAYER_SET_SPECIAL_POWER_COUNTDOWN` finds the player's spellbook
object, finds the module for a named power on it and writes its ready frame. Apply makes the same
three lookups and the same write, with the new frame worked out from the module's own cooldown
length, so the refund is a share of the cooldown actually running and the button clock moves with
it. A power that is ready, paused, on a shared timer or kept by the second cooldown layout is left
alone by a refund; a restart leaves all of that to `startPowerRecharge`, which handles each case
itself.

The module is registered by cloning `TooltipUpgrade`'s layout, as `grant-science-upgrade` does.
Tooltip's `ModuleData` ends in two engine strings, so the name takes the first and the percentage
and the restart flag get four bytes each past them. `SpecialPowerRefundUpgradeWorldbuilderPatch`
teaches the editor the block.

Derivation: `../docs/special-power-refund-upgrade.md`.
"""

from __future__ import annotations

import struct

from sage_ini.engine import BlockDelta, Engine, FieldDelta

from ..addresses import (
    ASCII_STRING_COPY_CTOR,
    FTOL,
    GAME_DATA_ASCIISTRING_PARSER,
    GAME_LOGIC_FRAME,
    GET_FINAL_OVERRIDE,
    INI_PARSE_BOOL,
    INI_PARSE_PERCENT_TO_REAL,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_GET_SPECIAL_POWER_MODULE,
    PLAYER_GET_SPELLBOOK_OBJECT,
    SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL,
    SPECIAL_POWER_START_POWER_RECHARGE,
    SPECIAL_POWER_STORE_FIND_TEMPLATE,
    THE_GAME_LOGIC,
    THE_SPECIAL_POWER_STORE,
    WORLDBUILDER_INI_PARSE_PERCENT_TO_REAL,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER,
    WORLDBUILDER_SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL,
)
from ..asm import JAE, JBE, JE, JLE, JNE, Asm
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
    "MODULEDATA_SIZE",
    "POWER_FIELD",
    "REFUND_FIELD",
    "RESTART_FIELD",
    "SECTION_NAME",
    "WORLDBUILDER_SECTION_NAME",
    "SpecialPowerRefundUpgradePatch",
    "SpecialPowerRefundUpgradeWorldbuilderPatch",
]

SECTION_NAME = ".sprfnd"
BLOCK_NAME = "SpecialPowerRefundUpgrade"
#: The power's name, in the first of the Tooltip ModuleData's two `AsciiString`s.
POWER_FIELD = ("SpecialPower", 0x138)
#: The refund as a fraction of the cooldown, a `Real` in the four bytes this module adds. Tooltip's
#: second string at `+0x13C` cannot hold it: its destructor would free the float as a buffer.
REFUND_FIELD = ("RefundPercent", tooltip_twin.MODULEDATA_SIZE)
#: `RestartCooldown`, a `Bool` in the next four bytes (the parser writes one; the rest is padding).
RESTART_FIELD = ("RestartCooldown", tooltip_twin.MODULEDATA_SIZE + 4)
MODULEDATA_SIZE = tooltip_twin.MODULEDATA_SIZE + 8
# `and dword [esi+0x140], 0` / `and dword [esi+0x144], 0`: Tooltip's constructor knows nothing of
# the added bytes, and a module with neither line must do nothing.
_ZERO_REFUND = (
    b"\x83\xa6" + u32(REFUND_FIELD[1]) + b"\x00" + b"\x83\xa6" + u32(RESTART_FIELD[1]) + b"\x00"
)

# RemoveUpgradeUpgrade's addModule call: `push 0x6505C4` (ModuleData factory), `push 0x65058C`
# (runtime factory), `mov ecx, edi`, the unwind-state store `mov [ebp-4], 0xD7`, then the call.
# TooltipUpgrade's call belongs to `object-image-upgrade` and AudioLoopUpgrade's to
# `grant-science-upgrade`.
_REGISTER_PREFIX = bytes.fromhex("68c4056500688c0565008bcfc745fcd7000000")
_REGISTER_BYTES = bytes.fromhex("e897c8ffff")

# `SpecialPowerModuleInterface`, in the layout `SPECIAL_POWER_START_POWER_RECHARGE` writes.
_INTERFACE_DURATION = 0x04
_INTERFACE_READY_FRAME = 0x08
_INTERFACE_PAUSE_COUNT = 0x0C
_SLOT_GET_TEMPLATE = 0x18
_SLOT_SET_READY_FRAME = 0x20
_SLOT_START_POWER_RECHARGE = 0x3C
#: `SpecialPowerTemplate.SharedSyncedTimer`: such a power's timer is the `Player`'s, not the
#: module's.
_TEMPLATE_SHARED_SYNCED_TIMER = 0x59

_STRINGS = (
    ("block_name", BLOCK_NAME),
    ("power_name", POWER_FIELD[0]),
    ("refund_name", REFUND_FIELD[0]),
    ("restart_name", RESTART_FIELD[0]),
)
#: `1.0f`: the argument a cast passes to `startPowerRecharge`, meaning the whole cooldown.
_FULL_RECHARGE = 0x3F800000


def _field_table(
    layout: dict[str, int], string_parser: int, percent_parser: int, bool_parser: int
) -> bytes:
    return tooltip_twin.field_table(
        [
            (layout["power_name"], string_parser, POWER_FIELD[1]),
            (layout["refund_name"], percent_parser, REFUND_FIELD[1]),
            (layout["restart_name"], bool_parser, RESTART_FIELD[1]),
        ]
    )


def _strings() -> bytes:
    return b"".join(raw.encode() + b"\0" for _name, raw in _STRINGS)


def _layout(base: int, tables: tuple[tuple[str, int], ...]) -> dict[str, int]:
    cursor = base
    out: dict[str, int] = {}
    for name, size in tables:
        out[name] = cursor
        cursor += size
    for name, raw in _STRINGS:
        out[name] = cursor
        cursor += len(raw) + 1
    out["code"] = (cursor + 3) & ~3
    return out


class SpecialPowerRefundUpgradePatch(Patch):
    """Install the SpecialPowerRefundUpgrade module."""

    name = "special-power-refund-upgrade"
    author = "officialNecro"
    description = (
        "Adds a new Behavior SpecialPowerRefundUpgrade: when its TriggeredBy upgrade fires, the "
        "SpecialPower it names on the controlling player's spellbook comes ready sooner by "
        "RefundPercent of the cooldown it is running, and the button clock jumps with it; with "
        "RestartCooldown = Yes it instead starts that power's cooldown over at full length, as "
        "if it had just been cast (e.g. when a permanent summon is sent away). Nothing is undone "
        "when the upgrade is removed"
    )

    @staticmethod
    def _layout(base: int) -> dict[str, int]:
        return _layout(
            base,
            (
                ("upgrade", tooltip_twin.UPGRADE_VTABLE_SIZE),
                ("moduledata", tooltip_twin.MODULEDATA_VTABLE_SIZE),
                ("table", 4 * tooltip_twin.FIELD_ROW_SIZE),
            ),
        )

    def _assemble(self, base: int) -> Asm:
        layout = self._layout(base)
        a = Asm(layout["code"])

        # Entered in place of RemoveUpgradeUpgrade's addModule call.
        tooltip_twin.emit_game_skeleton(
            a,
            block_name=layout["block_name"],
            upgrade_vtable=layout["upgrade"],
            moduledata_vtable=layout["moduledata"],
            table=layout["table"],
            moduledata_size=MODULEDATA_SIZE,
            after_ctor=_ZERO_REFUND,
        )

        # UpgradeMux Apply, ECX = the mux. The lookups of script action
        # PLAYER_SET_SPECIAL_POWER_COUNTDOWN, for the object's controlling player: player ->
        # spellbook object, name -> template, object -> the module for that template.
        a.label("apply")
        a.emit(0x53, 0x56, 0x57, b"\x8b\xf1")  # push ebx / push esi / push edi / mov esi, ecx
        a.emit(b"\x8b\x7e", struct.pack("<b", tooltip_twin.MUX_OBJECT), b"\x85\xff")
        a.jcc(JE, "apply_done")
        a.emit(b"\x8b\x5e", struct.pack("<b", tooltip_twin.MUX_MODULE_DATA))  # ebx = ModuleData
        a.emit(b"\x83\xbb", u32(POWER_FIELD[1]), b"\x00")  # cmp dword [ebx+0x138], 0
        a.jcc(JE, "apply_done")  # no SpecialPower line: an empty AsciiString
        a.emit(b"\x8b\xcf")  # mov ecx, edi
        a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
        a.emit(b"\x85\xc0")
        a.jcc(JE, "apply_done")
        a.emit(b"\x8b\xc8")  # mov ecx, eax
        a.call_absolute(PLAYER_GET_SPELLBOOK_OBJECT)
        a.emit(b"\x85\xc0")
        a.jcc(JE, "apply_done")
        a.emit(b"\x8b\xf8")  # mov edi, eax              ; the spellbook object
        # The name goes to the lookup by value, and the lookup destroys it: copy-construct it into
        # the argument slot, as the script action does.
        a.emit(0x51, b"\x8b\xcc")  # push ecx / mov ecx, esp
        a.emit(b"\x8d\x83", u32(POWER_FIELD[1]), 0x50)  # lea eax, [ebx+0x138] / push eax
        a.call_absolute(ASCII_STRING_COPY_CTOR)  # ret 4
        a.emit(b"\x8b\x0d", u32(THE_SPECIAL_POWER_STORE))
        a.call_absolute(SPECIAL_POWER_STORE_FIND_TEMPLATE)  # ret 4
        a.emit(b"\x85\xc0")
        a.jcc(JE, "apply_done")  # unknown power
        a.emit(0x50, b"\x8b\xcf")  # push eax / mov ecx, edi
        a.call_absolute(OBJECT_GET_SPECIAL_POWER_MODULE)  # ret 4
        a.emit(b"\x85\xc0")
        a.jcc(JE, "apply_done")  # the spellbook has no module for it
        a.emit(b"\x8b\xf0")  # mov esi, eax              ; the SpecialPowerModuleInterface

        # RestartCooldown: start the cooldown over, as a cast does. startPowerRecharge picks the
        # length (with today's discounts) and handles shared timers and either layout itself, so
        # none of the refund's checks apply.
        a.emit(b"\x80\xbb", u32(RESTART_FIELD[1]), b"\x00")  # cmp byte [ebx+0x144], 0
        a.jcc(JE, "apply_refund")
        a.emit(0x68, u32(_FULL_RECHARGE))  # push 1.0f
        a.emit(b"\x8b\xce", b"\x8b\x06")  # mov ecx, esi / mov eax, [esi]
        a.emit(b"\xff\x50", _SLOT_START_POWER_RECHARGE)  # call [eax+0x3c]   ; ret 4
        a.jmp("apply_done")
        a.label("apply_refund")

        # Only the layout that keeps a cooldown length beside the ready frame: the module's own
        # startPowerRecharge says which one it is.
        a.emit(b"\x8b\x06")  # mov eax, [esi]
        a.emit(b"\x81\x78", _SLOT_START_POWER_RECHARGE, u32(SPECIAL_POWER_START_POWER_RECHARGE))
        a.jcc(JNE, "apply_done")
        a.emit(b"\x8b\xce", b"\xff\x50", _SLOT_GET_TEMPLATE)  # mov ecx, esi / call [eax+0x18]
        a.emit(b"\x85\xc0")
        a.jcc(JE, "apply_done")
        a.emit(b"\x8b\xc8")  # mov ecx, eax
        a.call_absolute(GET_FINAL_OVERRIDE)
        a.emit(b"\x80\x78", _TEMPLATE_SHARED_SYNCED_TIMER, 0x00)
        a.jcc(JNE, "apply_done")
        a.emit(b"\x83\x7e", _INTERFACE_PAUSE_COUNT, 0x00)  # a paused power's frame is not live
        a.jcc(JNE, "apply_done")

        a.emit(0xA1, u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
        a.emit(b"\x8b\x78", GAME_LOGIC_FRAME)  # mov edi, [eax+0x40]      ; now
        a.emit(b"\x8b\x46", _INTERFACE_READY_FRAME, b"\x3b\xc7")  # mov eax, [esi+8] / cmp eax, edi
        a.jcc(JBE, "apply_done")  # already ready
        a.emit(b"\x83\x7e", _INTERFACE_DURATION, 0x00)
        a.jcc(JLE, "apply_done")  # never recharged
        # refund = ftol(duration * RefundPercent), the engine's own rounding for a cooldown.
        a.emit(b"\xdb\x46", _INTERFACE_DURATION)  # fild dword [esi+4]
        a.emit(b"\xd8\x8b", u32(REFUND_FIELD[1]))  # fmul dword [ebx+0x140]
        a.call_absolute(FTOL)
        a.emit(b"\x85\xc0")
        a.jcc(JLE, "apply_done")  # nothing to give back: this module never lengthens a cooldown
        a.emit(b"\x8b\x4e", _INTERFACE_READY_FRAME, b"\x2b\xcf")  # ecx = readyFrame - now
        a.emit(b"\x3b\xc1")  # cmp eax, ecx
        a.jcc_short(JAE, "apply_ready_now")
        a.emit(b"\x8b\xc8")  # mov ecx, eax              ; the refund fits inside what is left
        a.label("apply_ready_now")
        a.emit(b"\x8b\x46", _INTERFACE_READY_FRAME, b"\x2b\xc1")  # eax = readyFrame - min(...)
        a.emit(0x50, b"\x8b\xce", b"\x8b\x06")  # push eax / mov ecx, esi / mov eax, [esi]
        a.emit(b"\xff\x50", _SLOT_SET_READY_FRAME)  # setReadyFrame, as the script action calls it
        a.label("apply_done")
        a.emit(0x5F, 0x5E, 0x5B, 0xC3)

        # Unapply: a refunded cooldown stays refunded.
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
        out += _field_table(
            layout, GAME_DATA_ASCIISTRING_PARSER, INI_PARSE_PERCENT_TO_REAL, INI_PARSE_BOOL
        )
        out += _strings()
        out += b"\0" * (-len(out) % 4)
        assert base + len(out) == layout["code"]
        out += self._code_bytes(base)
        return bytes(out)

    @staticmethod
    def _check_registration(data: bytes | bytearray) -> None:
        tooltip_twin.check_registration(
            data,
            SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL,
            _REGISTER_PREFIX,
            _REGISTER_BYTES,
            "build: RemoveUpgradeUpgrade",
        )

    def apply(self, data: bytearray) -> None:
        self._check_registration(data)
        base = allocate_section(
            data, SECTION_NAME, lambda va: self._build(data, va), tooltip_twin.CHARACTERISTICS
        )
        code = self._assemble(base)
        apply_byte_patch(
            data,
            va_to_offset(data, SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL) or 0,
            _REGISTER_BYTES,
            call_rel32(SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL, code.label_va("register")),
            "register SpecialPowerRefundUpgrade",
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
        want = call_rel32(SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL, code.label_va("register"))
        if read_bytes(data, SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL, len(want)) != want:
            problems.append(f"RemoveUpgradeUpgrade registration does not point into {SECTION_NAME}")
        return problems

    def ini_surface(self) -> Engine:
        return Engine(
            blocks=(BlockDelta(BLOCK_NAME, base="UpgradeBehavior", patch=self.name),),
            fields=(
                FieldDelta(BLOCK_NAME, POWER_FIELD[0], "Ref:specialpowers", patch=self.name),
                FieldDelta(BLOCK_NAME, REFUND_FIELD[0], "Float", 0.0, self.name),
                FieldDelta(BLOCK_NAME, RESTART_FIELD[0], "Bool", False, self.name),
            ),
        )


# The Worldbuilder half. The editor links its own engine copy and ModuleFactory, so the game-side
# registration does not teach it the block. Parser-only: the editor never fires upgrades.

# Eight bytes exactly: PE section names are not NUL-terminated when every byte is used.
WORLDBUILDER_SECTION_NAME = ".wbsprfn"

# Worldbuilder's RemoveUpgradeUpgrade registration: `push 0xC8B8B0` (ModuleData factory), `push
# 0xC8B840` (runtime factory), `mov ecx, [ebp-0x4E8]` (the ModuleFactory), then the call.
# AudioLoopUpgrade's call, the one before it, belongs to `grant-science-upgrade-wb`.
_WORLDBUILDER_REGISTER_PREFIX = bytes.fromhex("68b0b8c8006840b8c8008b8d18fbffff")
_WORLDBUILDER_REGISTER_BYTES = bytes.fromhex("e832e00100")


class SpecialPowerRefundUpgradeWorldbuilderPatch(Patch):
    """Teach **Worldbuilder** to parse the SpecialPowerRefundUpgrade behavior.

    **This patch targets `Worldbuilder.exe`, not `game.dat`.** It is the authoring half of
    `SpecialPowerRefundUpgradePatch`: the editor gains the block name and its three fields.
    """

    name = "special-power-refund-upgrade-wb"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): register the SpecialPowerRefundUpgrade Behavior and its "
        "SpecialPower, RefundPercent and RestartCooldown fields, so the editor can load object "
        "templates written for a game.dat carrying special-power-refund-upgrade; parser-only"
    )

    @staticmethod
    def _layout(base: int) -> dict[str, int]:
        return _layout(base, (("table", 4 * tooltip_twin.FIELD_ROW_SIZE),))

    def _assemble(self, base: int) -> Asm:
        layout = self._layout(base)
        a = Asm(layout["code"])
        # Entered in place of RemoveUpgradeUpgrade's addModule call. The ModuleData grows as the
        # game's does, because the editor's percent parser writes the same four bytes.
        tooltip_twin.emit_worldbuilder_skeleton(
            a,
            block_name=layout["block_name"],
            table=layout["table"],
            moduledata_size=MODULEDATA_SIZE,
            after_ctor=_ZERO_REFUND,
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
            _field_table(
                layout,
                WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER,
                WORLDBUILDER_INI_PARSE_PERCENT_TO_REAL,
                # The editor's Bool parser has not been located. It never reads the field, so
                # its string parser stands in: it accepts the token and keeps it in the four
                # bytes, which the ModuleData's destructor does not free (a few bytes per block,
                # once, in the editor).
                WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER,
            )
        )
        out += _strings()
        out += b"\0" * (-len(out) % 4)
        assert base + len(out) == layout["code"]
        out += self._code_bytes(base)
        return bytes(out)

    @staticmethod
    def _check_registration(data: bytes | bytearray) -> None:
        tooltip_twin.check_registration(
            data,
            WORLDBUILDER_SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL,
            _WORLDBUILDER_REGISTER_PREFIX,
            _WORLDBUILDER_REGISTER_BYTES,
            "Worldbuilder build: RemoveUpgradeUpgrade",
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
            va_to_offset(data, WORLDBUILDER_SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL) or 0,
            _WORLDBUILDER_REGISTER_BYTES,
            call_rel32(
                WORLDBUILDER_SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL, code.label_va("register")
            ),
            "register SpecialPowerRefundUpgrade in Worldbuilder",
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
            WORLDBUILDER_SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL, code.label_va("register")
        )
        if (
            read_bytes(data, WORLDBUILDER_SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL, len(want))
            != want
        ):
            problems.append(
                "Worldbuilder RemoveUpgradeUpgrade registration does not point into "
                f"{WORLDBUILDER_SECTION_NAME}"
            )
        return problems
