"""Tests for `recharge-rescale`, which lets a cooldown already running respond to a recharge
modifier granted after the cast.

The patch rewrites **four bytes** and reads two dozen windows it does not rewrite, so almost
everything that can go wrong here is silent. Four kinds of silence are checked separately.

The **field offsets**: the cave writes two fields of a live `SpecialPowerModule`, and one wrong
displacement is a write into the pause bookkeeping or into the module's `Object *`. Every offset it
uses is re-derived from the engine's own instructions - carried in the patch's anchor table - rather
than restated here, so a test that agreed with a mistyped constant is not possible.

The **arithmetic it reproduces**: the whole design rests on recomputing `startPowerRecharge`'s
formula exactly, including which modifier type it asks for, which flag bit gates the player
discount, and the `>= 1` clamp. Each of those is checked against the stock site it copies.

The **x87 discipline**: the cave pushes three values onto the FPU stack and must pop all three.
A leak would not fail anything here or in the frame it happens in - it would overflow the engine's
own FPU stack minutes later, somewhere else entirely.

The **flavour test**: three module vtables carry a *different* `startPowerRecharge` whose ready
frame is at `+0x04`, where this layout keeps the duration. Writing one as if it were the other
corrupts it silently, so the constant the cave compares against is checked against a real vtable
slot of each flavour.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import apply_patches
from sage_patch.patches.experimental.recharge_rescale import (
    ANCHORS,
    FTOL,
    GAME_LOGIC_FIRST_OBJECT,
    GAME_LOGIC_FRAME,
    GET_CONTROLLING_PLAYER,
    GET_FINAL_OVERRIDE,
    GET_MODIFIER_MULTIPLIER,
    GET_SPECIAL_POWER_SLOT,
    GET_SPELL_RECHARGE_MODIFIER,
    HOOK_CALL_VA,
    LOGIC_FRAME_GATE,
    MODULE_INTERFACE,
    OBJECT_MODULES,
    OBJECT_NEXT,
    RECHARGE_TIME_MODIFIER,
    SECTION_CHARACTERISTICS,
    SECTION_NAME,
    SPI_DURATION,
    SPI_PAUSE_COUNT,
    SPI_READY_FRAME,
    SPI_VTABLE_RECHARGE_SLOT,
    SPI_VTABLE_TEMPLATE_SLOT,
    START_POWER_RECHARGE,
    START_POWER_RECHARGE_ALT,
    TEMPLATE_FLAGS,
    TEMPLATE_RELOAD_TIME,
    TEMPLATE_RESPECT_RECHARGE_DISCOUNT,
    TEMPLATE_SHARED_SYNCED_TIMER,
    RechargeRescalePatch,
    build_section,
)
from sage_patch.utils import find_section, va_to_offset

from .synthetic import recharge_rescale_image

_GAME_DAT = Path(r"C:\Program Files (x86)\Games\bfme\rotwk\game.dat")

#: The stock windows individual assertions read back through, by the VA the patch files them under.
_HOOK_WINDOW = 0x0062E568
_RECHARGE_ENTRY = 0x00896E31
_SHARED_TIMER_WINDOW = 0x00896E6C
_MODIFIER_QUERY_WINDOW = 0x00896E87
_FLAG_WINDOW = 0x00896EBA
_RELOAD_WINDOW = 0x00896EE3
_STORE_WINDOW = 0x00896F75
_IS_READY_WINDOW = 0x00896CD4
_PERCENT_WINDOW = 0x00896D8F
_GET_SPECIAL_POWER_WINDOW = 0x008979F5
_MODULE_WALK_WINDOW = 0x0068BDD0
_MULTIPLIER_CALLEE_WINDOW = 0x0068C82D
_VTABLE_F1 = 0x00C6502C
_VTABLE_F2 = 0x00C6512C


def _call_bytes(from_va: int, to_va: int) -> bytes:
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def at(data: bytes | bytearray, va: int, length: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + length])


@pytest.fixture
def image() -> bytearray:
    return recharge_rescale_image()


def _patched(image: bytearray) -> bytearray:
    data = bytearray(image)
    RechargeRescalePatch().apply(data)
    return data


def _cave(data: bytes | bytearray) -> tuple[int, int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    return located


def _hook_target(data: bytes | bytearray) -> int:
    off = va_to_offset(data, HOOK_CALL_VA)
    assert off is not None
    return HOOK_CALL_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]


def _disassembled(data: bytes | bytearray) -> list:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    section_va, off, vsize = _cave(data)
    return list(md.disasm(bytes(data[off : off + vsize]), section_va))


class TestRoundTrip:
    def test_apply_then_verify(self, image: bytearray) -> None:
        assert RechargeRescalePatch().verify(_patched(image)) == []

    def test_verify_rejects_an_unpatched_image(self, image: bytearray) -> None:
        problems = RechargeRescalePatch().verify(image)
        assert problems and SECTION_NAME in problems[0]

    def test_detect_recovers_the_patch(self, image: bytearray) -> None:
        assert RechargeRescalePatch.detect(_patched(image)) is not None
        assert RechargeRescalePatch.detect(image) is None

    def test_apply_is_idempotent_only_once(self, image: bytearray) -> None:
        """A second application must fail rather than double-patch: the hooked `call` no longer
        holds its original displacement and `apply_byte_patch` asserts it."""
        data = _patched(image)
        with pytest.raises(ValueError):
            RechargeRescalePatch().apply(data)

    def test_apply_patches_writes_a_file(self, image: bytearray, tmp_path) -> None:
        src, out = tmp_path / "game.dat.backup", tmp_path / "game.dat"
        src.write_bytes(bytes(image))
        apply_patches(src, [RechargeRescalePatch()], output=out)
        assert RechargeRescalePatch().verify(out.read_bytes()) == []
        assert src.read_bytes() == bytes(image)  # the input is never modified

    def test_the_patch_is_attributed(self) -> None:
        assert RechargeRescalePatch.author

    def test_the_patch_declares_itself_experimental(self) -> None:
        """It lives in `patches/experimental`, and the attribute is what `apply` warns from. The
        suite-wide `TestExperimentalPatchesAreDeclared` checks the pair agrees; this says which
        side of the pair this patch is on."""
        assert RechargeRescalePatch.experimental is True


class TestTheEdit:
    def test_the_hook_retargets_the_frame_gate_into_the_cave(self, image: bytearray) -> None:
        data = _patched(image)
        section_va, _off, vsize = _cave(data)
        assert at(image, HOOK_CALL_VA, 5) == _call_bytes(HOOK_CALL_VA, LOGIC_FRAME_GATE)
        assert section_va <= _hook_target(data) < section_va + vsize

    def test_the_hook_site_is_the_call_the_frame_increment_depends_on(self) -> None:
        """The whole determinism argument is that the sweep runs under exactly the pair of flags
        that lets `0x0062E577` advance the frame. Read that back out of the stock window rather
        than trusting the address: `call <gate>; test al,al; je; test bl,bl; jne; inc [esi+0x40]`.
        """
        window = ANCHORS[_HOOK_WINDOW]
        call_at = HOOK_CALL_VA - _HOOK_WINDOW
        assert window[call_at] == 0xE8
        target = HOOK_CALL_VA + 5 + struct.unpack_from("<i", window, call_at + 1)[0]
        assert target == LOGIC_FRAME_GATE
        assert window[call_at + 5 :] == bytes.fromhex("84c0740784db7507") + bytes(
            [0xFF, 0x46, GAME_LOGIC_FRAME]
        )

    def test_nothing_outside_the_one_call_and_the_cave_is_rewritten(self, image: bytearray) -> None:
        """The patch's whole footprint in existing code is **four bytes** of displacement.
        Everything else it changes is the PE header block and the bytes it appends."""
        data = _patched(image)
        headers = 0x400  # SizeOfHeaders in the stand-in; the section table lives inside it
        changed = {i for i in range(headers, len(image)) if data[i] != image[i]}
        off = va_to_offset(data, HOOK_CALL_VA)
        assert off is not None
        assert changed <= set(range(off + 1, off + 5))  # the displacement; the 0xE8 stays put

    def test_the_cave_carries_no_writable_state(self, image: bytearray) -> None:
        """The design's central claim is that it needs no per-module storage - the duration field
        already records the baked-in multiplier. A writable cave would mean that claim slipped."""
        assert SECTION_CHARACTERISTICS & 0x80000000 == 0  # not IMAGE_SCN_MEM_WRITE
        data = _patched(image)
        _va, off, vsize = _cave(data)
        assert bytes(data[off : off + vsize]) == build_section(_cave(data)[0])[0]


class TestWhatTheCaveCalls:
    def test_the_cave_leaves_only_by_the_routines_it_names(self, image: bytearray) -> None:
        """Nothing may `jmp` out - the hook is a plain `call` that returns - and the only `call`s
        out are the six engine routines the design names. Anything else leaving the cave is a
        resolved branch gone wrong, which assembles and applies perfectly."""
        data = _patched(image)
        section_va, _off, vsize = _cave(data)
        external = [
            (i.mnemonic, int(i.op_str, 16))
            for i in _disassembled(data)
            if i.op_str.startswith("0x")
            and not section_va <= int(i.op_str, 16) < section_va + vsize
        ]
        assert [target for kind, target in external if kind == "jmp"] == []
        assert {target for kind, target in external if kind == "call"} == {
            LOGIC_FRAME_GATE,
            GET_FINAL_OVERRIDE,
            GET_MODIFIER_MULTIPLIER,
            GET_CONTROLLING_PLAYER,
            GET_SPELL_RECHARGE_MODIFIER,
            FTOL,
        }

    def test_the_gate_is_called_before_anything_else(self, image: bytearray) -> None:
        """The hook stands in for a `call` whose return value the caller reads, so the very first
        thing at the entry point has to be that call - and its result has to survive the sweep,
        which is what `pushad`/`popad` is for."""
        data = _patched(image)
        entry = _hook_target(data)
        body = [i for i in _disassembled(data) if i.address >= entry]
        assert body[0].mnemonic == "call"
        assert int(body[0].op_str, 16) == LOGIC_FRAME_GATE
        mnemonics = [i.mnemonic for i in body]
        assert mnemonics.count("pushal") == 1
        assert mnemonics.count("popal") == 1

    def test_the_modifier_query_is_seeded_before_the_call(self, image: bytearray) -> None:
        """`getModifierMultiplier` returns **without writing its out-parameter** when the object
        has no modifier holder, which is the common case - so the slot must already hold 1.0f or
        the multiplier is read from stack garbage. The stock site seeds it for the same reason."""
        # the callee's early exit: `call getModifierHolder; test eax,eax; jne; xor al,al; ret 0x10`
        assert ANCHORS[_MULTIPLIER_CALLEE_WINDOW].endswith(bytes.fromhex("32c0c21000"))
        seed = bytes.fromhex("c745fc") + struct.pack("<f", 1.0)
        data = _patched(image)
        _va, off, vsize = _cave(data)
        assert bytes(data[off : off + vsize]).count(seed) == 1

    def test_the_modifier_type_is_the_one_the_stock_site_asks_for(self, image: bytearray) -> None:
        """`RECHARGE_TIME` is attribute type 12, read back out of the stock query rather than
        restated - a patch asking for 13 would silently scale cooldowns by `PRODUCTION`."""
        window = ANCHORS[_MODIFIER_QUERY_WINDOW]
        push = window.index(bytes([0x6A, RECHARGE_TIME_MODIFIER]))
        # ... and it is the last thing pushed before the call, i.e. argument 1
        assert window[push + 2 :].startswith(bytes.fromhex("8bcb"))  # mov ecx, <the Object>
        assert window[push + 4 :].startswith(bytes.fromhex("f30f1145f4e8"))  # the seed, then call


class TestTheOffsetsItUses:
    """Every structure offset the cave depends on, re-derived from the engine's own instructions.

    Each assertion reads a stock window the patch already carries, so none of these can agree with
    a mistyped constant: the window is the engine's, the constant is the patch's."""

    def test_ready_frame_and_duration_are_the_pair_the_full_recharge_writes(self) -> None:
        """One site writes both, which is what makes the duration a usable record of the
        multiplier: `readyFrame = frame + n` then `duration = n`."""
        window = ANCHORS[_STORE_WINDOW]
        assert bytes([0x89, 0x46, SPI_READY_FRAME]) in window  # mov [esi+8], eax
        assert bytes([0x89, 0x46, SPI_DURATION]) in window  # mov [esi+4], eax

    def test_the_pause_count_is_the_one_is_ready_screens_on(self) -> None:
        """`isReady` is `[esi+0xC] == 0 && frame >= [esi+8]` - both offsets from a second reader,
        independent of the site that wrote them."""
        window = ANCHORS[_IS_READY_WINDOW]
        assert window.startswith(bytes([0x83, 0x7E, SPI_PAUSE_COUNT, 0x00]))
        assert bytes([0x3B, 0x46, SPI_READY_FRAME]) in window  # cmp eax, [esi+8]

    def test_the_duration_is_the_percent_readouts_denominator(self) -> None:
        """The third reader, and the reason both fields are rescaled together: the clock is
        `1 - remaining/duration`, so moving one without the other makes it jump."""
        window = ANCHORS[_PERCENT_WINDOW]
        assert window.startswith(bytes([0x8B, 0x46, SPI_DURATION, 0xDB, 0x46, SPI_DURATION]))

    def test_the_template_offsets_are_the_ones_the_cast_time_code_reads(self) -> None:
        assert ANCHORS[_SHARED_TIMER_WINDOW][5:9] == bytes(
            [0x80, 0x78, TEMPLATE_SHARED_SYNCED_TIMER, 0x00]
        )
        assert ANCHORS[_RELOAD_WINDOW].startswith(bytes([0x8B, 0x40, TEMPLATE_RELOAD_TIME]))
        assert ANCHORS[_FLAG_WINDOW].startswith(bytes([0x8B, 0x40, TEMPLATE_FLAGS]))

    def test_the_discount_flag_is_bit_five(self) -> None:
        """The stock gate is `shr eax,5 / test al,1`; the cave tests the same bit as a mask on the
        low byte, which is only the same bit if the mask is 0x20."""
        window = ANCHORS[_FLAG_WINDOW]
        shift = window[3:6]
        assert shift == bytes.fromhex("c1e805")  # shr eax, 5
        assert window[6:8] == bytes.fromhex("a801")  # test al, 1
        assert TEMPLATE_RESPECT_RECHARGE_DISCOUNT == 1 << shift[2]

    def test_the_object_list_is_the_one_game_logic_update_walks(self) -> None:
        assert ANCHORS[0x0062E908] == bytes([0x8B, 0x9E]) + struct.pack(
            "<I", GAME_LOGIC_FIRST_OBJECT
        )
        assert ANCHORS[0x0062E92B].startswith(bytes([0x8B, 0x9B]) + struct.pack("<I", OBJECT_NEXT))

    def test_the_module_array_and_the_interface_offset_come_from_the_curse_walk(self) -> None:
        window = ANCHORS[_MODULE_WALK_WINDOW]
        assert window.startswith(bytes([0x56, 0x8B, 0xB1]) + struct.pack("<I", OBJECT_MODULES))
        assert bytes([0x8D, 0x48, MODULE_INTERFACE]) in window  # lea ecx, [eax+0xc]

    def test_the_special_power_getter_is_the_slot_the_engine_asks(self) -> None:
        """`add eax,0xc / mov edx,[eax] / mov ecx,eax / call [edx+0x20]` - the interface offset and
        the slot in one window, so neither can drift alone."""
        assert ANCHORS[_GET_SPECIAL_POWER_WINDOW] == bytes([0x83, 0xC0, MODULE_INTERFACE]) + bytes(
            [0x8B, 0x10, 0x8B, 0xC8, 0xFF, 0x52, GET_SPECIAL_POWER_SLOT]
        )

    def test_the_cave_touches_only_the_offsets_it_documents(self, image: bytearray) -> None:
        """Every structure access the cave makes, by displacement. A stray one is a read or a write
        into an unrelated member of a live object, which nothing else here would catch."""
        displacements = set()
        for i in _disassembled(_patched(image)):
            for register in ("eax", "ebx", "ecx", "edx", "esi", "edi"):
                marker = f"[{register} + "
                if marker in i.op_str:
                    displacements.add(int(i.op_str.split(marker)[1].split("]")[0], 16))
        assert displacements == {
            SPI_DURATION,
            SPI_READY_FRAME,
            SPI_PAUSE_COUNT,
            SPI_VTABLE_TEMPLATE_SLOT,
            SPI_VTABLE_RECHARGE_SLOT,
            TEMPLATE_FLAGS,  # == TEMPLATE_RELOAD_TIME, one value, two meanings
            TEMPLATE_SHARED_SYNCED_TIMER,
            MODULE_INTERFACE,
            GET_SPECIAL_POWER_SLOT,
            GAME_LOGIC_FRAME,
            GAME_LOGIC_FIRST_OBJECT,
            OBJECT_NEXT,
            OBJECT_MODULES,
        }


class TestTheFlavourTest:
    def test_the_constant_is_the_function_a_flavour_one_vtable_holds(self) -> None:
        assert struct.unpack("<I", ANCHORS[_VTABLE_F1])[0] == START_POWER_RECHARGE
        assert ANCHORS[_RECHARGE_ENTRY][:6] == bytes.fromhex("558bec83ec0c")  # its prologue

    def test_the_other_flavour_is_a_different_function_that_writes_a_different_field(self) -> None:
        """Flavour 2 stores its ready frame at `+0x04`, where this layout keeps the duration, so
        treating one as the other writes a frame number into the clock's denominator."""
        assert struct.unpack("<I", ANCHORS[_VTABLE_F2])[0] == START_POWER_RECHARGE_ALT
        assert START_POWER_RECHARGE_ALT != START_POWER_RECHARGE
        assert ANCHORS[0x0099161C].startswith(bytes([0x89, 0x46, SPI_DURATION]))

    def test_the_cave_compares_against_the_flavour_one_function(self, image: bytearray) -> None:
        """`mov eax,[ebx] / mov eax,[eax+0x3c] / cmp eax, <f1>` - and the alternative appears
        nowhere, because anything that is not flavour 1 is skipped rather than special-cased."""
        data = _patched(image)
        _va, off, vsize = _cave(data)
        code = bytes(data[off : off + vsize])
        assert code.count(bytes([0x3D]) + struct.pack("<I", START_POWER_RECHARGE)) == 1
        assert struct.pack("<I", START_POWER_RECHARGE_ALT) not in code


class TestTheArithmetic:
    def test_the_fpu_stack_balances(self, image: bytearray) -> None:
        """Three values go onto the x87 stack and three come off: two `fild`s and the `fld` inside
        the player-modifier getter, against one `fstp` and two `ftol`s (which pop). A leak here
        would not fail in the frame that caused it - it would overflow the engine's FPU stack
        minutes later, in unrelated code."""
        instructions = _disassembled(_patched(image))
        pushes = sum(1 for i in instructions if i.mnemonic == "fild")
        pops = sum(1 for i in instructions if i.mnemonic == "fstp")
        for i in instructions:
            if i.mnemonic == "call" and i.op_str.startswith("0x"):
                target = int(i.op_str, 16)
                pushes += target == GET_SPELL_RECHARGE_MODIFIER  # `fld [Player+0x718]`
                pops += target == FTOL  # consumes st(0)
        assert pushes == pops == 3

    def test_the_two_factors_multiply_in_the_stock_order_and_precision(
        self, image: bytearray
    ) -> None:
        """The stock formula is `fild ReloadTime / fmul <player> / fmul <attribute>`, both
        multiplies in an x87 register - so the intermediate is never rounded to a Real. Folding the
        player factor into the attribute slot first would round it, and one ULP either side of the
        `ftol` boundary is a duration a frame off the engine's own, which reads as a spurious
        rescale on the first frame after every cast. So the shape is asserted, not just the maths:
        one `fstp` (the player factor into its own slot) and **two consecutive `fmul`s**.

        The `fadd` also has to name the engine's own 1.0f, which is the constant the stock gate
        adds at `0x00896ECC` - read back out of the anchor rather than restated."""
        one_float = ANCHORS[_FLAG_WINDOW][ANCHORS[_FLAG_WINDOW].index(b"\xd8\x05") + 2 :][:4]
        mnemonics = [
            (i.mnemonic, i.op_str) for i in _disassembled(_patched(image)) if i.mnemonic[0] == "f"
        ]
        assert ("fadd", f"dword ptr [0x{struct.unpack('<I', one_float)[0]:x}]") in mnemonics
        assert [m for m, _ in mnemonics] == [
            "fadd",
            "fstp",  # 1 + Player[0x718] -> its own slot
            "fild",
            "fmul",
            "fmul",  # ReloadTime * player * attribute -> frames_now
            "fild",
            "fimul",
            "fidiv",  # remaining * frames_now / duration
        ]
        # and the engine's own sequence, for the same three steps, in the same order
        stock = ANCHORS[_RELOAD_WINDOW]
        assert bytes.fromhex("db45fc") in stock  # fild <ReloadTime>
        assert stock[stock.index(bytes.fromhex("db45fc")) :].count(b"\xd8\x4d") == 2  # two fmuls

    def test_both_results_are_clamped_to_at_least_one_frame(self, image: bytearray) -> None:
        """The stock formula clamps its frame count to `>= 1` (`test edi,edi / jne / inc edi`), and
        the rescaled remainder needs the same floor or a degenerate multiplier makes a cooldown
        that never finishes shrinking. Both clamps, in the cave, as `jg` over a `mov eax, 1`."""
        assert ANCHORS[_RELOAD_WINDOW].endswith(bytes.fromhex("85ff750147"))  # the stock clamp
        data = _patched(image)
        _va, off, vsize = _cave(data)
        code = bytes(data[off : off + vsize])
        assert code.count(bytes.fromhex("85c07f05b801000000")) == 2

    def test_the_rescale_is_gated_on_an_integer_comparison(self, image: bytearray) -> None:
        """The exit almost every power takes: the recomputed duration equals the stored one. It has
        to be an integer compare against the stored field, not a float tolerance, or the patch
        would rewrite a cooldown every frame and truncate it a frame at a time."""
        instructions = _disassembled(_patched(image))
        compares = [i for i in instructions if i.mnemonic == "cmp" and "ebp - 0x14" in i.op_str]
        assert [i.op_str for i in compares] == ["eax, dword ptr [ebp - 0x14]"]
        # the same slot the stored duration was read into, and the divisor of the rescale
        assert [i.op_str for i in instructions if i.mnemonic == "fidiv"] == [
            "dword ptr [ebp - 0x14]"
        ]


class TestTheBuildFingerprint:
    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_disturbed_anchor_refuses_to_apply(self, image: bytearray, va: int) -> None:
        data = bytearray(image)
        off = va_to_offset(data, va)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError, match="not the expected build"):
            RechargeRescalePatch().apply(data)

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_disturbed_anchor_fails_verification(self, image: bytearray, va: int) -> None:
        data = _patched(image)
        off = va_to_offset(data, va)
        assert off is not None
        data[off] ^= 0xFF
        assert RechargeRescalePatch().verify(data) != []

    def test_verify_survives_the_hooked_call_it_rewrote(self, image: bytearray) -> None:
        """The hook's anchor window contains the `call` the patch repoints, so verification has to
        blank those five bytes - otherwise a correctly patched image reports its own edit."""
        data = _patched(image)
        assert RechargeRescalePatch().verify(data) == []
        assert at(data, HOOK_CALL_VA, 5) != _call_bytes(HOOK_CALL_VA, LOGIC_FRAME_GATE)

    def test_a_moved_cave_fails_verification(self, image: bytearray) -> None:
        """Every engine call in the cave is a resolved displacement, so a cave built for another
        base address would call into the middle of unrelated functions."""
        data = _patched(image)
        section_va, off, _vsize = _cave(data)
        content, _tick = build_section(section_va + 0x1000)
        data[off : off + len(content)] = content
        problems = RechargeRescalePatch().verify(data)
        assert problems and SECTION_NAME in problems[0]


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="the ROTWK game.dat is not installed here")
class TestInstalledBinary:
    """The addresses, against the real build. The stand-in is built from the patch's own anchor
    table, so only this can say those addresses hold those bytes."""

    @pytest.fixture
    def game(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_anchor_holds_its_stock_bytes(self, game: bytes) -> None:
        for va, expected in ANCHORS.items():
            assert at(game, va, len(expected)) == expected, f"0x{va:08x}"

    def test_both_recharge_implementations_are_reachable_from_a_vtable(self, game: bytes) -> None:
        """The flavour test compares against a function pointer, so what has to be true of the real
        build is that both functions really do sit at interface slot `+0x3C` of some vtable."""
        for vtable_slot_va, expected in (
            (_VTABLE_F1, START_POWER_RECHARGE),
            (_VTABLE_F2, START_POWER_RECHARGE_ALT),
        ):
            assert struct.unpack("<I", at(game, vtable_slot_va, 4))[0] == expected

    def test_the_recharge_time_modifier_is_read_at_the_two_sites_the_design_names(
        self, game: bytes
    ) -> None:
        """If a third site scaled a recharge, the duration would stop being a complete record of
        the baked-in multiplier and the rescale would fight it every frame."""
        anchor_off = va_to_offset(game, _RECHARGE_ENTRY)
        assert anchor_off is not None
        delta = _RECHARGE_ENTRY - anchor_off  # .text is contiguous in this build

        needle = bytes([0x6A, RECHARGE_TIME_MODIFIER])  # push 0x0c, the type argument
        sites = []
        start = 0
        while True:
            found = game.find(needle, start)
            if found < 0:
                break
            start = found + 1
            # the query is the next `call rel32` within a couple of instructions of the push
            for call in range(found + 2, min(found + 24, len(game) - 5)):
                if game[call] != 0xE8:
                    continue
                target = (call + delta) + 5 + struct.unpack_from("<i", game, call + 1)[0]
                if target == GET_MODIFIER_MULTIPLIER:
                    sites.append(call + delta)
                break
        assert sites == [0x00896EA0, 0x00991564]

    def test_apply_and_verify_round_trip_on_the_real_binary(self, game: bytes) -> None:
        data = bytearray(game)
        RechargeRescalePatch().apply(data)
        assert RechargeRescalePatch().verify(data) == []
        assert RechargeRescalePatch.detect(data) is not None
