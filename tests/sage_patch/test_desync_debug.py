"""Tests for the desync-debug patch.

The patch is three initialisers, so "it applies" is trivially true and nearly worthless as a test.
What its correctness actually rests on is the *range* it accepts and the values it writes, because
every failure mode here is silent - a binary with a bad interval applies, verifies and then either
divides by zero on the first frame of the first match or claims to be patched when it is stock.
So the tests are mostly about the edges:

* **zero is refused.** The heartbeat gate's `div ecx` has no guard, and an interval of 0 is an
  integer divide-by-zero on the logic thread. Nothing downstream would catch it.
* **100 and above are refused.** At 100 every site holds its stock bytes, so a `verify` that
  passed there would make `detect` report every unpatched `game.dat` as carrying the patch -
  `test_stock_is_not_detected` is the assertion that would fail if the ceiling ever moved up.
* **the interval is written little-endian as a dword at the right site.** It is read back through
  `struct`, not compared against the constant that produced it.
* **the two optional sites are checked in both directions.** An off-by-default parameter that
  `verify` ignored would let a binary with the self-check armed pass as one built without it.
* **`detect` recovers all three parameters**, which is what makes a `.sagepatch` manifest
  round-trip to the same build rather than to this version's defaults.

`TestAgainstTheRealBinary` is the one that ties the addresses to the build: the stock values are
asserted where the patch expects them, so a `game.dat` on disk that disagrees fails here rather
than at apply time on someone's install.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    DESYNC_FOCUS_FRAME,
    DESYNC_FOCUS_FRAME_UNSET,
    DESYNC_VERIFY_CLIENT_CRC_FLAG,
    NET_CRC_INTERVAL,
    NET_CRC_INTERVAL_STOCK,
)
from sage_patch.patches.desync_debug import (
    MAX_FOCUS_FRAME,
    MAX_INTERVAL,
    MIN_FOCUS_FRAME,
    MIN_INTERVAL,
    DesyncDebugPatch,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset

from .synthetic import _sparse_image, desync_debug_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def _applied(**kwargs) -> bytearray:
    data = desync_debug_image()
    DesyncDebugPatch(**kwargs).apply(data)
    return data


def _dword(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    assert off is not None
    return int(struct.unpack_from("<I", data, off)[0])


def _byte(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    assert off is not None
    return data[off]


class TestApply:
    def test_applies_and_verifies(self):
        assert DesyncDebugPatch().verify(_applied()) == []

    def test_absent_from_an_unpatched_image(self):
        problems = DesyncDebugPatch().verify(desync_debug_image())
        assert len(problems) == 1
        assert "NetCRCInterval" in problems[0]

    def test_stock_is_not_detected(self):
        """The reason the interval stops one short of 100: a stock binary must not read back as a
        patched one, and the interval is the only site that distinguishes them when both optional
        parameters are left off."""
        assert DesyncDebugPatch.detect(desync_debug_image()) is None

    def test_it_does_not_grow_the_image(self):
        """No cave, no section: three same-length overwrites."""
        assert len(_applied()) == len(desync_debug_image())

    def test_only_the_three_sites_change(self):
        stock, patched = desync_debug_image(), _applied(verify_client_crc=True, focus_frame=900)
        sites = {
            va_to_offset(stock, NET_CRC_INTERVAL): 4,
            va_to_offset(stock, DESYNC_VERIFY_CLIENT_CRC_FLAG): 1,
            va_to_offset(stock, DESYNC_FOCUS_FRAME): 4,
        }
        allowed = {i for off, size in sites.items() for i in range(off, off + size)}
        differing = {i for i in range(len(stock)) if stock[i] != patched[i]}
        assert differing, "the patch changed nothing"
        assert differing <= allowed

    def test_applying_twice_raises(self):
        """`apply_byte_patch` asserts the stock bytes, so the second pass fails loudly rather than
        writing an interval derived from an already-patched one."""
        data = _applied()
        with pytest.raises(ValueError, match="expected 64000000"):
            DesyncDebugPatch().apply(data)

    def test_an_unmapped_site_is_refused(self):
        data = _sparse_image({NET_CRC_INTERVAL: struct.pack("<I", NET_CRC_INTERVAL_STOCK)})
        with pytest.raises(ValueError, match="is not mapped"):
            DesyncDebugPatch().apply(data)

    def test_a_binary_that_is_not_this_build_is_refused(self):
        """`NetCRCInterval` holding something other than 100 is the cheapest signal that the
        address means something else here."""
        data = _sparse_image(
            {
                NET_CRC_INTERVAL: struct.pack("<I", 60),
                DESYNC_VERIFY_CLIENT_CRC_FLAG: bytes(1),
                DESYNC_FOCUS_FRAME: struct.pack("<I", DESYNC_FOCUS_FRAME_UNSET),
            }
        )
        with pytest.raises(ValueError, match="expected 64000000"):
            DesyncDebugPatch().apply(data)


class TestTheInterval:
    """The parameter the patch exists for, read back out of the image."""

    @pytest.mark.parametrize("interval", [MIN_INTERVAL, 5, 10, MAX_INTERVAL])
    def test_it_lands_little_endian_at_the_global(self, interval):
        assert _dword(_applied(crc_interval=interval), NET_CRC_INTERVAL) == interval

    def test_zero_is_refused(self):
        """The gate divides the frame by this with no zero guard, so a 0 is a divide-by-zero on
        the logic thread on the first frame - which nothing downstream would report as a bad
        parameter."""
        with pytest.raises(ValueError, match="no zero guard"):
            DesyncDebugPatch(crc_interval=0)

    def test_negative_is_refused(self):
        with pytest.raises(ValueError, match="crc_interval must be in"):
            DesyncDebugPatch(crc_interval=-1)

    def test_the_stock_value_is_refused(self):
        with pytest.raises(ValueError, match="what the engine ships"):
            DesyncDebugPatch(crc_interval=NET_CRC_INTERVAL_STOCK)

    def test_coarser_than_stock_is_refused(self):
        """Above 100 the skirmish re-seed clamps and the `GameInfo` constructor does not, so the
        two paths would disagree about the cadence."""
        with pytest.raises(ValueError, match="crc_interval must be in"):
            DesyncDebugPatch(crc_interval=250)

    def test_the_ceiling_is_one_below_stock(self):
        assert MAX_INTERVAL == NET_CRC_INTERVAL_STOCK - 1


class TestTheOptionalSwitches:
    """Both default off, and both are verified in *both* directions - a `verify` that only checked
    the on state would pass a binary with the self-check armed against a patch built without it."""

    def test_verify_client_crc_defaults_to_the_stock_zero(self):
        assert _byte(_applied(), DESYNC_VERIFY_CLIENT_CRC_FLAG) == 0

    def test_verify_client_crc_arms_the_gate(self):
        assert _byte(_applied(verify_client_crc=True), DESYNC_VERIFY_CLIENT_CRC_FLAG) == 1

    def test_an_armed_gate_fails_a_patch_built_without_it(self):
        problems = DesyncDebugPatch(verify_client_crc=False).verify(
            _applied(verify_client_crc=True)
        )
        assert len(problems) == 1
        assert "verifyClientCRC" in problems[0]

    def test_the_focus_frame_defaults_to_the_unset_sentinel(self):
        assert _dword(_applied(), DESYNC_FOCUS_FRAME) == DESYNC_FOCUS_FRAME_UNSET

    def test_the_focus_frame_lands_at_the_global(self):
        assert _dword(_applied(focus_frame=12345), DESYNC_FOCUS_FRAME) == 12345

    def test_a_set_focus_frame_fails_a_patch_built_without_one(self):
        problems = DesyncDebugPatch().verify(_applied(focus_frame=12345))
        assert len(problems) == 1
        assert "focus frame" in problems[0]

    @pytest.mark.parametrize("frame", [0, -1, MAX_FOCUS_FRAME + 1])
    def test_an_out_of_range_focus_frame_is_refused(self, frame):
        """The engine's own handler rejects a non-positive `atoi`, and `0xFFFFFFFF` is the unset
        sentinel - so a focus frame outside the positive signed ints is not expressible."""
        with pytest.raises(ValueError, match="focus_frame must be in"):
            DesyncDebugPatch(focus_frame=frame)

    @pytest.mark.parametrize("frame", [MIN_FOCUS_FRAME, MAX_FOCUS_FRAME])
    def test_the_range_edges_are_accepted(self, frame):
        assert _dword(_applied(focus_frame=frame), DESYNC_FOCUS_FRAME) == frame


class TestDetect:
    """What makes a `.sagepatch` manifest rebuild the same binary rather than this version's
    defaults: all three parameters have to come back out of the image."""

    @pytest.mark.parametrize(
        ("interval", "verify_crc", "focus"),
        [
            (1, False, None),
            (10, True, None),
            (99, False, 4200),
            (7, True, 1),
        ],
    )
    def test_it_recovers_every_parameter(self, interval, verify_crc, focus):
        data = _applied(crc_interval=interval, verify_client_crc=verify_crc, focus_frame=focus)
        found = DesyncDebugPatch.detect(data)
        assert isinstance(found, DesyncDebugPatch)
        assert (found.crc_interval, found.verify_client_crc, found.focus_frame) == (
            interval,
            verify_crc,
            focus,
        )

    def test_the_recovered_options_rebuild_the_same_patch(self):
        original = DesyncDebugPatch(crc_interval=25, verify_client_crc=True, focus_frame=808)
        data = desync_debug_image()
        original.apply(data)
        found = DesyncDebugPatch.detect(data)
        assert found is not None
        assert DesyncDebugPatch(**found.options()).verify(data) == []

    def test_it_never_raises_on_an_arbitrary_image(self):
        """A detection sweep runs over binaries this patch knows nothing about, so an unmapped or
        nonsense site is 'not this patch', never an exception."""
        assert DesyncDebugPatch.detect(bytearray(64)) is None
        assert DesyncDebugPatch.detect(_sparse_image({NET_CRC_INTERVAL: b"\x05\x00\x00\x00"})) is (
            None
        )


class TestCli:
    def test_the_defaults_match_the_constructor(self):
        parser = pytest.importorskip("argparse").ArgumentParser()
        DesyncDebugPatch.add_cli_arguments(parser)
        built = DesyncDebugPatch.from_cli_args(parser.parse_args([]))
        assert built.options() == DesyncDebugPatch().options()

    def test_every_parameter_round_trips(self):
        parser = pytest.importorskip("argparse").ArgumentParser()
        DesyncDebugPatch.add_cli_arguments(parser)
        args = parser.parse_args(
            ["--crc-interval", "5", "--verify-client-crc", "--focus-frame", "9"]
        )
        built = DesyncDebugPatch.from_cli_args(args)
        assert (built.crc_interval, built.verify_client_crc, built.focus_frame) == (5, True, 9)


class TestRegistration:
    def test_it_is_registered_and_settled(self):
        assert PATCHES[DesyncDebugPatch.name] is DesyncDebugPatch
        assert not DesyncDebugPatch().experimental

    def test_it_declares_no_ini_surface(self):
        """It changes no keyword and no token: every switch it flips is unreachable from INI, and
        that is the reason the patch exists."""
        assert DesyncDebugPatch().ini_surface() is STOCK

    def test_the_name_says_what_it_is_for(self):
        assert DesyncDebugPatch(crc_interval=5).__str__().startswith("desync-debug (every 5 ")


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestAgainstTheRealBinary:
    """The addresses, against the build they were read from. This is what would catch a transcribed
    digit, which every synthetic test above is blind to by construction."""

    @staticmethod
    def _game() -> bytes:
        return _GAME_DAT.read_bytes()

    def test_the_interval_ships_at_one_hundred(self):
        assert _dword(self._game(), NET_CRC_INTERVAL) == NET_CRC_INTERVAL_STOCK

    def test_the_self_check_gate_ships_clear(self):
        assert _byte(self._game(), DESYNC_VERIFY_CLIENT_CRC_FLAG) == 0

    def test_the_focus_frame_ships_unset(self):
        assert _dword(self._game(), DESYNC_FOCUS_FRAME) == DESYNC_FOCUS_FRAME_UNSET

    def test_it_applies_to_the_real_binary(self):
        data = bytearray(self._game())
        patch = DesyncDebugPatch(crc_interval=5, verify_client_crc=True, focus_frame=3000)
        patch.apply(data)
        assert patch.verify(data) == []
        assert len(data) == len(self._game())
