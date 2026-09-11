"""Tests for `standalone-launcher`, which takes the launcher's shared-memory token out of
`gi.dat` instead of decrypting it under a key built from the install path's volume serial.

Two of these carry most of the weight, and neither is about the framework.

:meth:`TestShape.test_reproduces_the_shipped_edain_diff` is the real oracle. The edit is the Edain
mod's, distributed as an IDA difference file; this package re-derives it from two function
addresses rather than copying 38 hex bytes, and that is only worth doing if the derivation lands on
exactly the same bytes. The literal below is transcribed from `lotrbfme2ep1_manual.diff`.

:meth:`TestInstalledBinary.test_apply_reproduces_the_shipped_launcher` is the same claim against
the real files: forced back to the EA bytes, `apply` must reproduce the Edain launcher *in full* -
not just at the site, but byte for byte across the whole 499,712-byte image, which is what proves
the patch writes nothing else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch.patches.multi_instance import MultiInstanceLauncherPatch, MultiInstancePatch
from sage_patch.patches.standalone_launcher import (
    ANCHORS,
    GI_DAT_G4_ACCESSOR,
    STRCPY,
    TOKEN_SITE,
    TOKEN_SITE_LENGTH,
    TOKEN_SITE_STOCK,
    StandaloneLauncherPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import instance_guard_image, standalone_launcher_image

_INSTALL = Path(r"C:\Program Files (x86)\Games\bfme\rotwk")
_LAUNCHER = _INSTALL / "lotrbfme2ep1.exe"

#: The replacement exactly as `lotrbfme2ep1_manual.diff` states it, transcribed by hand. Not
#: imported from the patch - the whole point is to check the patch against an outside source.
EDAIN_DIFF = bytes.fromhex("e878b200005057e831ec030083c408" + "90" * 23)


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


@pytest.fixture
def patch() -> StandaloneLauncherPatch:
    return StandaloneLauncherPatch()


@pytest.fixture
def image() -> bytearray:
    return standalone_launcher_image()


class TestShape:
    def test_reproduces_the_shipped_edain_diff(self):
        assert build_code() == EDAIN_DIFF

    def test_the_replacement_is_exactly_as_long_as_what_it_replaces(self):
        """In place, so nothing downstream shifts and no cave is needed."""
        assert len(build_code()) == TOKEN_SITE_LENGTH == len(TOKEN_SITE_STOCK) == 38

    def test_the_two_calls_reach_the_functions_they_name(self):
        """The point of emitting rather than transcribing: the displacements are computed from
        the addresses, so the patch says which functions it calls and cannot disagree with
        itself."""
        code = build_code()
        for offset, target in ((0, GI_DAT_G4_ACCESSOR), (7, STRCPY)):
            assert code[offset] == 0xE8, f"offset {offset} is not a call"
            rel = int.from_bytes(code[offset + 1 : offset + 5], "little", signed=True)
            assert TOKEN_SITE + offset + 5 + rel == target

    def test_the_tail_is_padding(self):
        """`strcpy` plus its cleanup is 15 bytes; the rest has to be unreachable filler rather
        than anything that could execute."""
        assert set(build_code()[15:]) == {0x90}

    def test_the_site_and_the_anchors_are_disjoint(self):
        """An anchor overlapping the site would still hold its stock bytes after `apply`, so
        `verify` would report a correctly patched file as broken. The clamp anchor ends exactly
        where the site begins, which is the closest of them."""
        spans = sorted(
            [(TOKEN_SITE, TOKEN_SITE + TOKEN_SITE_LENGTH, "the token site")]
            + [(va, va + len(blob), f"anchor 0x{va:08x}") for va, blob in ANCHORS.items()]
        )
        previous_end, previous_what = 0, "start of image"
        for start, end, what in spans:
            assert start >= previous_end, f"{what} overlaps {previous_what}"
            previous_end, previous_what = end, what

    def test_it_says_which_binary_it_wants(self):
        """The CLI labels every path argument `GAME_DAT`, so a patch that wants a different file
        has to say so in the text `sage-patch list` prints."""
        assert "lotrbfme2ep1.exe" in StandaloneLauncherPatch.description


class TestApply:
    def test_writes_the_replacement(self, patch, image):
        patch.apply(image)
        assert at(image, TOKEN_SITE, TOKEN_SITE_LENGTH) == build_code()

    def test_leaves_the_anchors_alone(self, patch, image):
        patch.apply(image)
        for va, expected in ANCHORS.items():
            assert at(image, va, len(expected)) == expected

    def test_verify_is_clean_afterwards(self, patch, image):
        patch.apply(image)
        assert patch.verify(image) == []

    def test_a_clean_image_does_not_verify(self, patch, image):
        problems = patch.verify(image)
        assert len(problems) == 1
        assert "still derived from the install path" in problems[0]

    def test_detect_answers_only_after_apply(self, patch, image):
        assert StandaloneLauncherPatch.detect(image) is None
        patch.apply(image)
        assert isinstance(StandaloneLauncherPatch.detect(image), StandaloneLauncherPatch)

    def test_applying_twice_raises(self, patch, image):
        patch.apply(image)
        with pytest.raises(ValueError, match="expected"):
            patch.apply(image)

    def test_adds_no_ini_surface(self, patch, image):
        """It changes what the launcher hands the engine, not the INI the engine parses."""
        assert patch.ini_surface() is STOCK


class TestRefusals:
    def test_a_changed_anchor_refuses(self, patch, image):
        va = next(iter(ANCHORS))
        image[va_to_offset(image, va)] ^= 0xFF
        with pytest.raises(ValueError, match="unexpected build"):
            patch.apply(image)

    def test_a_refusal_writes_nothing(self, patch, image):
        va = next(iter(ANCHORS))
        image[va_to_offset(image, va)] ^= 0xFF
        with pytest.raises(ValueError):
            patch.apply(image)
        assert at(image, TOKEN_SITE, TOKEN_SITE_LENGTH) == TOKEN_SITE_STOCK

    def test_a_moved_site_refuses(self, patch, image):
        """Every anchor passes but the 38 bytes are not the ones being replaced - which is what a
        build where the key schedule is called differently would look like."""
        off = va_to_offset(image, TOKEN_SITE)
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="expected"):
            patch.apply(image)

    def test_an_all_zero_image_refuses(self, patch):
        """The degenerate wrong binary: every site reads zero rather than something plausible."""
        blank = standalone_launcher_image()
        for va, blob in ANCHORS.items():
            off = va_to_offset(blank, va)
            blank[off : off + len(blob)] = bytes(len(blob))
        with pytest.raises(ValueError, match="unexpected build"):
            patch.apply(blank)

    @pytest.mark.parametrize(
        "other", [MultiInstancePatch(), MultiInstanceLauncherPatch()], ids=lambda p: p.name
    )
    def test_it_refuses_the_other_binaries(self, patch, other):
        """`game.dat`, and the same launcher described by the only other patch that targets it."""
        wrong = instance_guard_image(other)
        assert StandaloneLauncherPatch.detect(wrong) is None
        with pytest.raises(ValueError, match="unexpected build"):
            patch.apply(wrong)


class TestRegistry:
    def test_is_registered(self):
        assert PATCHES[StandaloneLauncherPatch.name] is StandaloneLauncherPatch


@pytest.mark.skipif(
    not _LAUNCHER.exists(), reason="requires a local ROTWK install (not available in CI)"
)
class TestInstalledBinary:
    """Against the real launcher. This is the only thing here that can catch a patch aimed at
    bytes that are not actually the token derivation."""

    @pytest.fixture
    def installed(self) -> bytearray:
        return bytearray(_LAUNCHER.read_bytes())

    def test_the_anchors_are_present(self, patch, installed):
        for va, expected in ANCHORS.items():
            assert at(installed, va, len(expected)) == expected, f"0x{va:08x}"

    def test_the_site_reads_stock_or_patched(self, patch, installed):
        got = at(installed, TOKEN_SITE, TOKEN_SITE_LENGTH)
        assert got in (TOKEN_SITE_STOCK, build_code()), got.hex()

    def test_apply_reproduces_the_shipped_launcher(self, patch, installed):
        """Forced back to the EA bytes first, so this passes whether or not the installed copy
        already carries the patch - and then the whole image, not just the site, has to come back
        identical to what Edain ships."""
        shipped = bytes(installed)
        off = va_to_offset(installed, TOKEN_SITE)
        installed[off : off + TOKEN_SITE_LENGTH] = TOKEN_SITE_STOCK
        if bytes(installed) == shipped:  # an unpatched EA launcher: nothing to compare against
            pytest.skip("the installed launcher is stock, so there is no Edain build to match")
        assert patch.verify(installed) != []
        patch.apply(installed)
        assert patch.verify(installed) == []
        assert bytes(installed) == shipped
