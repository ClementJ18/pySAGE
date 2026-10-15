"""Ask whether a player may build the unit that was requested, not the button's own.

`BuildAssistant::canMakeUnit` walks a producer's `CommandSet` for a build button whose template
is `EquivalentTo` the wanted one, and then asks the player whether it may build *the button's*
template. `ProductionUpdate` asks the same question every frame about the template *in the
queue*. When a mod disallows one of two equivalent units for a player - Edain's AI scripts do,
for the Last Alliance battalions - the gate says yes on the strength of the allowed one, the
disallowed one is queued, and production holds it at 0% for the rest of the match with every
entry behind it.

Eight bytes: the gate pushes the wanted template instead of fetching the button's. Nothing
changes when the two are the same template, which is every player click. No INI change.

Derivation: `../docs/ai-equivalent-build-gate.md`.
"""

from __future__ import annotations

from ..addresses import (
    CAN_MAKE_UNIT_ACCEPT_TEMPLATE,
    CAN_MAKE_UNIT_ACCEPT_TEMPLATE_BYTES,
    CAN_MAKE_UNIT_CAN_BUILD_CALL,
    CAN_MAKE_UNIT_CAN_BUILD_CALL_BYTES,
    CAN_MAKE_UNIT_EQUIVALENT_CALL,
    CAN_MAKE_UNIT_EQUIVALENT_CALL_BYTES,
)
from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = ["ANCHORS", "PUSH_WANTED", "AiEquivalentBuildGatePatch"]

#: `push dword [ebp+0xc]` - `canMakeUnit`'s own `what` argument - then one `nop` per byte left
#: of the `mov ecx, esi` / `call CommandButton::getThingTemplate` / `push eax` it replaces.
PUSH_WANTED = bytes.fromhex("ff750c") + b"\x90" * (len(CAN_MAKE_UNIT_ACCEPT_TEMPLATE_BYTES) - 3)

#: Byte windows the patch depends on and does not write: the equivalence test that lets a
#: button stand for another template, and the call the pushed template is an argument of.
ANCHORS: dict[int, bytes] = {
    CAN_MAKE_UNIT_EQUIVALENT_CALL: CAN_MAKE_UNIT_EQUIVALENT_CALL_BYTES,
    CAN_MAKE_UNIT_CAN_BUILD_CALL: CAN_MAKE_UNIT_CAN_BUILD_CALL_BYTES,
}


class AiEquivalentBuildGatePatch(Patch):
    name = "ai-equivalent-build-gate"
    author = "officialNecro"
    description = (
        "A producer whose build button is EquivalentTo the wanted unit is asked whether the "
        "player may build the wanted unit, not the button's, so a unit a script disallowed is "
        "no longer queued through its allowed twin and held at 0% for the rest of the match. "
        "All factions. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        apply_byte_patch(
            data,
            self._offset(data, CAN_MAKE_UNIT_ACCEPT_TEMPLATE),
            CAN_MAKE_UNIT_ACCEPT_TEMPLATE_BYTES,
            PUSH_WANTED,
            "canMakeUnit: test the wanted template's buildability",
        )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        """Raise unless the site sits between `canMakeUnit`'s equivalence test and its
        buildability call.

        `[ebp+0xc]` is the wanted template only inside that function: a build whose gate moved
        would otherwise have some other frame's argument pushed in its place."""
        for va, expected in ANCHORS.items():
            off = cls._offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - this is not "
                    "canMakeUnit's equivalence test and buildability call of the expected build"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            self._check_anchors(data)
        except ValueError as exc:
            return [str(exc)]
        off = self._offset(data, CAN_MAKE_UNIT_ACCEPT_TEMPLATE)
        got = bytes(data[off : off + len(PUSH_WANTED)])
        if got == PUSH_WANTED:
            return []
        stock = got == CAN_MAKE_UNIT_ACCEPT_TEMPLATE_BYTES
        which = "the stock button-template fetch" if stock else "something else"
        return [
            f"{CAN_MAKE_UNIT_ACCEPT_TEMPLATE:#010x} holds {got.hex()} ({which}): the file does "
            "not carry this patch"
        ]
