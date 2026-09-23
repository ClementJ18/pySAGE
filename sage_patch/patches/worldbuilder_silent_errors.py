"""Stop Worldbuilder's internal-build diagnostics stalling the editor on a mod's data.

Targets `Worldbuilder.exe`, an assert-enabled build where every gated `DEBUG_LOG`/`DEBUG_CRASH`
raises a modal box at startup. All of them ask one gate, `0x00712DC0`, whether to skip; it now
returns yes. Real load failures that throw outside the gate (for example in
`ScienceStore::getScienceFromInternalName`) still stop the editor. The editor loses all of its
diagnostics while this is applied.

Derivation: `../docs/worldbuilder-silent-errors.md`.
"""

from __future__ import annotations

from ..patcher import Patch
from ..utils import apply_byte_patch, file_offset

__all__ = ["REPORT_GATE_VA", "WorldbuilderSilentErrorsPatch"]

#: `Debug::shouldSkipReport` - the thunk onto `TheDebug->vtable[0x5c]` that every gated report
#: site consults first.
REPORT_GATE_VA = 0x00712DC0

_ORIGINAL = bytes.fromhex("558bec")  # push ebp ; mov ebp, esp
_PATCHED = bytes.fromhex("b001c3")  # mov al, 1 ; ret

#: The rest of the thunk, asserted but not rewritten, so that a build whose first three bytes
#: happen to be a prologue cannot be mistaken for this one. `0x5C` is the vtable slot and
#: `0x022ABC04` is `TheDebug`; the tail is `mov esp, ebp ; pop ebp ; ret`.
_FINGERPRINT = {
    0x00712DC3: bytes.fromhex("518b45048945fc8b55088b0d04bc2a028b01528b55fc52ff505c8be55dc3"),
}


class WorldbuilderSilentErrorsPatch(Patch):
    """Make Worldbuilder's gated asserts and error boxes never appear."""

    name = "worldbuilder-silent-errors"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): make every gated DEBUG_LOG/DEBUG_CRASH report skip "
        "itself, so the editor stops raising modal assert boxes on data the shipping game "
        "accepts silently. Needs no INI change. Silences all 25018 report sites, including ones "
        "worth reading, and does not affect the ungated throws that are real load failures"
    )

    def apply(self, data: bytearray) -> None:
        self._check_fingerprint(data)
        apply_byte_patch(
            data,
            file_offset(data, REPORT_GATE_VA),
            _ORIGINAL,
            _PATCHED,
            f"debug report gate @0x{REPORT_GATE_VA:08x}",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            off = file_offset(data, REPORT_GATE_VA)
        except ValueError as exc:
            return [str(exc)]
        got = bytes(data[off : off + len(_PATCHED)])
        if got == _PATCHED:
            return []
        if got == _ORIGINAL:
            return [f"the report gate @0x{REPORT_GATE_VA:08x} is unpatched"]
        return [
            f"the report gate @0x{REPORT_GATE_VA:08x} is {got.hex()}, expected "
            f"{_PATCHED.hex()} (patched) or {_ORIGINAL.hex()} (stock)"
        ]

    @staticmethod
    def _check_fingerprint(data: bytes | bytearray) -> None:
        for va, expected in _FINGERPRINT.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {got.hex()}, expected {expected.hex()} - "
                    "this is not the Worldbuilder these addresses were read from"
                )
