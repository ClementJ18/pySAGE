"""Tests for the observer-switch patch.

There is no hand-written assembly here: the whole patch is one `call` aimed somewhere else. So
what the tests have to establish is that the edit really is only that, and that the checks around
it can tell the two predicates apart.

Three carry most of the weight. :meth:`TestShape.test_the_edit_is_one_call_retargeted` pins what
this patch is allowed to be. :meth:`TestShape.test_the_two_predicates_are_adjacent` is why the
"wrong function" check matters at all — the stock target sits immediately before the new one, so a
mis-derived `rel32` lands in real code. And
:meth:`TestShape.test_the_fingerprint_excludes_the_call_it_edits` is what keeps `verify` honest: a
fingerprint covering the call would still hold its stock bytes after `apply`, and `verify` would
report a correctly patched file as broken.

The synthetic image is built from the patch's own tables, so it cannot confirm the addresses are
the right ones; :class:`TestInstalledBinary` does that against the real `game.dat` when it is
present, and ``docs/observer-switch.md`` records the derivation.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    IS_MULTIPLAYER_OR_ITS_REPLAY,
    IS_MULTIPLAYER_OR_ITS_REPLAY_BYTES,
    IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY,
    IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY_BYTES,
    OBSERVER_BAR_GATE_CALL,
    OBSERVER_BAR_GATE_CALL_BYTES,
    OBSERVER_BAR_GATE_FINGERPRINT,
    OBSERVER_BAR_GATE_FINGERPRINT_BYTES,
    OBSERVER_BAR_HIDE,
    OBSERVER_BAR_SHOW,
    PLAYER_LIST_LOCAL_IS_NOT_ACTIVE,
)
from sage_patch.patches.observer_switch import ANCHORS, ObserverSwitchPatch, patched_call_bytes
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import observer_switch_image

_GAME_DAT = Path(r"C:\Program Files (x86)\Games\bfme\rotwk\game.dat")

#: Where the `call` sits inside the run that identifies it.
_CALL_AT = OBSERVER_BAR_GATE_FINGERPRINT_BYTES.index(OBSERVER_BAR_GATE_CALL_BYTES)


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


def _fingerprint_call_targets() -> set[int]:
    """Every ``call rel32`` in the identifying run, by destination.

    Decoded rather than counted: ``c0 e8 07`` (``shr al, 7``) contains an ``e8`` that is not an
    opcode, and only resolving the displacement tells the two apart."""
    blob = OBSERVER_BAR_GATE_FINGERPRINT_BYTES
    targets = set()
    for i in range(len(blob) - 4):
        if blob[i] != 0xE8:
            continue
        va = OBSERVER_BAR_GATE_FINGERPRINT + i
        targets.add(va + 5 + struct.unpack_from("<i", blob, i + 1)[0])
    return {t for t in targets if 0x00400000 <= t < 0x00E00000}


def call_target(data: bytes | bytearray, va: int = OBSERVER_BAR_GATE_CALL) -> int:
    raw = at(data, va, 5)
    assert raw[0] == 0xE8, f"0x{va:08x} is not a call: {raw.hex()}"
    return va + 5 + struct.unpack("<i", raw[1:])[0]


@pytest.fixture
def patch() -> ObserverSwitchPatch:
    return ObserverSwitchPatch()


@pytest.fixture
def image() -> bytearray:
    return observer_switch_image()


class TestShape:
    def test_the_edit_is_one_call_retargeted(self):
        """Five bytes, the same opcode, a different destination. Nothing else about the palantir's
        gate moves - the two predicates it calls have the same signature, so the caller's registers
        and its use of the result are unchanged."""
        stock, patched = OBSERVER_BAR_GATE_CALL_BYTES, patched_call_bytes()
        assert len(stock) == len(patched) == 5
        assert stock[0] == patched[0] == 0xE8
        assert stock != patched

    def test_the_stock_call_names_the_network_only_predicate(self):
        """What makes this `call` the observer bar's gate rather than any other: it points at the
        predicate that whitelists the recorded mode against the two network flavours."""
        rel = struct.unpack("<i", OBSERVER_BAR_GATE_CALL_BYTES[1:])[0]
        assert OBSERVER_BAR_GATE_CALL + 5 + rel == IS_MULTIPLAYER_OR_ITS_REPLAY

    def test_the_patched_call_names_the_skirmish_aware_predicate(self):
        rel = struct.unpack("<i", patched_call_bytes()[1:])[0]
        assert OBSERVER_BAR_GATE_CALL + 5 + rel == IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY

    def test_the_two_predicates_are_adjacent(self):
        """The sibling begins exactly where the stock one ends, which is what makes the anchors
        load-bearing: a `rel32` off by a few bytes lands inside real code, not in a hole."""
        assert (
            IS_MULTIPLAYER_OR_ITS_REPLAY + len(IS_MULTIPLAYER_OR_ITS_REPLAY_BYTES)
            == IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY
        )

    def test_both_predicates_are_thiscall_bools(self):
        """Both end `mov al, 1 / ret` on one path and `xor al, al / ret` on the other, take no
        stack argument and clean nothing - so one can stand in for the other at a call site."""
        for blob in (
            IS_MULTIPLAYER_OR_ITS_REPLAY_BYTES,
            IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY_BYTES,
        ):
            assert blob.endswith(b"\xc3"), "not a plain ret"
            assert b"\xb0\x01" in blob and b"\x32\xc0" in blob, "not a bool in al"
            assert b"\xc2" not in blob[-3:], "cleans stack arguments, so not a drop-in"

    def test_the_fingerprint_excludes_the_call_it_edits(self):
        """The run is checked either side of the call, never across it - otherwise `verify` would
        be asserting the stock bytes it just replaced."""
        assert OBSERVER_BAR_GATE_FINGERPRINT_BYTES.count(OBSERVER_BAR_GATE_CALL_BYTES) == 1
        assert OBSERVER_BAR_GATE_FINGERPRINT + _CALL_AT == OBSERVER_BAR_GATE_CALL

    def test_the_fingerprint_covers_both_halves_of_the_gate(self):
        """The run names all four functions the gate touches: the two predicates it ANDs, and the
        two `SetObserverStuffState` thunks that are the whole point of the answer. A bare `call`
        says nothing about which comparison it is; those do."""
        assert _fingerprint_call_targets() == {
            IS_MULTIPLAYER_OR_ITS_REPLAY,
            PLAYER_LIST_LOCAL_IS_NOT_ACTIVE,
            OBSERVER_BAR_SHOW,
            OBSERVER_BAR_HIDE,
        }

    def test_the_edit_does_not_overlap_what_it_reads(self):
        spans = [
            (OBSERVER_BAR_GATE_CALL, OBSERVER_BAR_GATE_CALL + 5, "the call"),
            *((va, va + len(blob), f"anchor 0x{va:08x}") for va, blob in ANCHORS.items()),
        ]
        previous_end, previous_what = 0, "start of image"
        for start, end, what in sorted(spans):
            assert start >= previous_end, f"{what} overlaps {previous_what}"
            previous_end, previous_what = end, what


class TestApply:
    def test_retargets_the_call(self, patch, image):
        assert call_target(image) == IS_MULTIPLAYER_OR_ITS_REPLAY
        patch.apply(image)
        assert call_target(image) == IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY

    def test_changes_nothing_else(self, patch, image):
        before = bytes(image)
        patch.apply(image)
        differing = [i for i, (a, b) in enumerate(zip(before, image, strict=True)) if a != b]
        off = va_to_offset(image, OBSERVER_BAR_GATE_CALL)
        assert differing and set(differing) <= set(range(off, off + 5))

    def test_leaves_both_predicates_alone(self, patch, image):
        patch.apply(image)
        for va, expected in ANCHORS.items():
            assert at(image, va, len(expected)) == expected

    def test_verify_is_clean_afterwards(self, patch, image):
        patch.apply(image)
        assert patch.verify(image) == []

    def test_a_clean_image_does_not_verify(self, patch, image):
        problems = patch.verify(image)
        assert len(problems) == 1
        assert "stock network-only" in problems[0]

    def test_detect_answers_only_after_apply(self, patch, image):
        assert ObserverSwitchPatch.detect(image) is None
        patch.apply(image)
        assert isinstance(ObserverSwitchPatch.detect(image), ObserverSwitchPatch)

    def test_applying_twice_raises(self, patch, image):
        patch.apply(image)
        with pytest.raises(ValueError, match="expected"):
            patch.apply(image)

    def test_adds_no_ini_surface(self, patch):
        """This changes engine behaviour, not the INI the engine parses, so there is nothing for
        `sage-patch sagepatch` to write."""
        assert patch.ini_surface() is STOCK


class TestRefusals:
    def test_a_changed_gate_refuses(self, patch, image):
        image[va_to_offset(image, OBSERVER_BAR_GATE_FINGERPRINT)] ^= 0xFF
        with pytest.raises(ValueError, match="not the observer bar"):
            patch.apply(image)

    def test_a_changed_tail_of_the_gate_refuses(self, patch, image):
        """The half *after* the call - the local-player test and the show/hide thunks - is as
        load-bearing as the half before it."""
        va = OBSERVER_BAR_GATE_FINGERPRINT + len(OBSERVER_BAR_GATE_FINGERPRINT_BYTES) - 1
        image[va_to_offset(image, va)] ^= 0xFF
        with pytest.raises(ValueError, match="not the observer bar"):
            patch.apply(image)

    @pytest.mark.parametrize(
        "va", list(ANCHORS), ids=["stock predicate", "skirmish-aware predicate"]
    )
    def test_a_moved_predicate_refuses(self, patch, image, va):
        image[va_to_offset(image, va)] ^= 0xFF
        with pytest.raises(ValueError, match="not this build's"):
            patch.apply(image)

    def test_a_refusal_writes_nothing(self, patch, image):
        image[va_to_offset(image, IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY)] ^= 0xFF
        with pytest.raises(ValueError):
            patch.apply(image)
        assert at(image, OBSERVER_BAR_GATE_CALL, 5) == OBSERVER_BAR_GATE_CALL_BYTES

    def test_an_all_zero_image_refuses(self, patch):
        """The degenerate wrong binary: every site reads zero rather than something plausible."""
        blank = bytearray(observer_switch_image())
        for va, blob in (
            (OBSERVER_BAR_GATE_FINGERPRINT, OBSERVER_BAR_GATE_FINGERPRINT_BYTES),
            *ANCHORS.items(),
        ):
            off = va_to_offset(blank, va)
            blank[off : off + len(blob)] = bytes(len(blob))
        assert ObserverSwitchPatch.detect(blank) is None
        with pytest.raises(ValueError):
            patch.apply(blank)


class TestRegistry:
    def test_is_registered(self):
        assert PATCHES[ObserverSwitchPatch.name] is ObserverSwitchPatch


@pytest.mark.skipif(
    not _GAME_DAT.exists(), reason="requires a local ROTWK install (not available in CI)"
)
class TestInstalledBinary:
    """The addresses against the real `game.dat`. This is the only thing here that can catch a
    patch aimed at bytes that are not actually the observer bar's gate."""

    @pytest.fixture
    def installed(self) -> bytearray:
        return bytearray(_GAME_DAT.read_bytes())

    def test_the_gate_is_present(self, installed):
        got = at(installed, OBSERVER_BAR_GATE_FINGERPRINT, len(OBSERVER_BAR_GATE_FINGERPRINT_BYTES))
        # Everything but the call, which may already be patched.
        assert got[:_CALL_AT] == OBSERVER_BAR_GATE_FINGERPRINT_BYTES[:_CALL_AT]
        assert got[_CALL_AT + 5 :] == OBSERVER_BAR_GATE_FINGERPRINT_BYTES[_CALL_AT + 5 :]

    def test_both_predicates_are_present(self, installed):
        for va, expected in ANCHORS.items():
            assert at(installed, va, len(expected)) == expected, f"0x{va:08x}"

    def test_the_call_reads_stock_or_patched(self, installed):
        assert call_target(installed) in (
            IS_MULTIPLAYER_OR_ITS_REPLAY,
            IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY,
        )

    def test_applies_to_a_stock_copy(self, installed):
        if call_target(installed) != IS_MULTIPLAYER_OR_ITS_REPLAY:
            pytest.skip("the installed game.dat already carries this patch")
        patch = ObserverSwitchPatch()
        patch.apply(installed)
        assert patch.verify(installed) == []
