"""Stop Worldbuilder's internal-build diagnostics stalling the editor on a mod's data.

**This patch targets `Worldbuilder.exe`, not `game.dat`.**

`Worldbuilder.exe` prints ``_INTERNAL defined.`` on startup: it is an assert-enabled build, so
every `DEBUG_LOG` / `DEBUG_CRASH` in the shared engine is *live* in it and compiled out of the
shipping `game.dat`. On a mod with a long history that is not a trickle - it is a wall. Each one
raises a modal ``Assertion failed`` / ``Error hit`` box during startup, and the editor gets no
further until somebody clicks it, which on screen looks exactly like the splash appearing and then
vanishing.

Every one of them funnels through a single gate. The report sites all open the same way:

    push 0
    call 0x00712DC0          ; may I skip this report?
    add  esp, 4
    movzx ecx, al
    test ecx, ecx
    jne  <past the report>   ; non-zero -> skip
    ...
    call [TheDebug + 0x60]   ; second gate, same shape
    jne  <past the report>
    ...build and show the box...

`0x00712DC0` is a four-line thunk onto ``TheDebug->vtable[0x5c]``, and **25,018 call sites reach
it** - which is the measure of how many individual patches this one replaces. Returning a non-zero
`al` from it takes the `jne` at every one of them.

    00712dc0  55 8b ec        push ebp ; mov ebp, esp   ->   b0 01    mov al, 1
    00712dc3  51              push ecx                  ->   c3       ret

The function is caller-cleaned (it ends in a bare `ret` and every site does its own
``add esp, 4``), so returning before the frame is set up leaves the stack exactly as the original
did.

What this does **not** silence
------------------------------
Only the *gated* reports, which are the ones that stall. A `throw` that sits outside the gate is
untouched, and there are several on the INI path - `scanLookupList`, ``Unknown block '%s'``, and
`ScienceStore::getScienceFromInternalName` among them. Those are real load failures rather than
complaints, they still stop the editor, and each still needs its own patch
(`science-prereqs-wb` is one). So this is not a blanket "ignore the mod's problems" switch: it
removes the noise and leaves the failures.

The cost, stated plainly
------------------------
The editor loses **all** of its diagnostics, including ones a modder would want. That is a real
loss and the reason this is a separate patch rather than part of another: apply it when the
editor's asserts are what is standing between you and opening the tool, and revert it when you
want the editor's opinion on your data. The shipped `Worldbuilder.dbgcmd` (``debug.errors -``)
looks like it should do this and does not - it does not gate these sites - which is what leaves a
binary patch as the way to get it.
"""

from __future__ import annotations

from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = ["REPORT_GATE_VA", "WorldbuilderSilentErrorsPatch"]

#: `Debug::shouldSkipReport` - the thunk onto ``TheDebug->vtable[0x5c]`` that every gated report
#: site consults first.
REPORT_GATE_VA = 0x00712DC0

_ORIGINAL = bytes.fromhex("558bec")  # push ebp ; mov ebp, esp
_PATCHED = bytes.fromhex("b001c3")  # mov al, 1 ; ret

#: The rest of the thunk, asserted but not rewritten, so that a build whose first three bytes
#: happen to be a prologue cannot be mistaken for this one. `0x5C` is the vtable slot and
#: `0x022ABC04` is `TheDebug`; the tail is ``mov esp, ebp ; pop ebp ; ret``.
_FINGERPRINT = {
    0x00712DC3: bytes.fromhex("518b45048945fc8b55088b0d04bc2a028b01528b55fc52ff505c8be55dc3"),
}


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped - not the expected build")
    return off


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
            _offset(data, REPORT_GATE_VA),
            _ORIGINAL,
            _PATCHED,
            f"debug report gate @0x{REPORT_GATE_VA:08x}",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            off = _offset(data, REPORT_GATE_VA)
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
            off = _offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {got.hex()}, expected {expected.hex()} - "
                    "this is not the Worldbuilder these addresses were read from"
                )
