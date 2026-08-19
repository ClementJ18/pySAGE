"""Tests for the maintenance-cost patch.

The patch is five edits to engine bytes plus ~300 bytes of hand-encoded x86, and none of that
fails loudly when it is wrong: a mis-encoded displacement assembles, applies and verifies, and
then the game charges the wrong player or jumps into the middle of an instruction. So the tests
that matter here **disassemble the result back** and assert it says what it was meant to say -
the stance `test_command_point_upkeep` and `test_inflation_readout` take for their bytes.

Three properties carry more weight than the rest, because each of them is a way for the patch to
be silently catastrophic rather than merely wrong:

* **A charge never reaches `Money::deposit`.** The balance is unsigned and `deposit` does not
  clamp, so one negative arriving there is four billion gold rather than a bug anybody notices as
  a bug. Both charge paths are asserted to call `MONEY_WITHDRAW` and neither to call
  `MONEY_DEPOSIT`.
* **A positive amount is untouched.** Every edit sits behind a sign test, and the two in-place
  condition rewrites have to preserve the stock outcome for every value the stock build could
  reach them with - which `TestThePositivePathIsStock` asserts against the emitted instructions
  rather than against the intent.
* **The stack is balanced on both paths.** The entries leave by `jmp`, not `ret`, so a leaked
  slot is not recovered by a caller - it corrupts the module update it returns into.

`TestItComputesNothing` guards the seam with `auto-deposit-inflation`: this patch charges whatever
amount reaches its hook and multiplies nothing, which is the only reason an `AutoDepositUpdate`
charge is inflated exactly when that patch is applied and flat when it is not.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import MaintenanceCostPatch
from sage_patch.addresses import (
    AUTO_DEPOSIT_DEPOSIT,
    AUTO_DEPOSIT_DEPOSIT_BYTES,
    AUTO_DEPOSIT_DEPOSIT_RESUME,
    AUTO_DEPOSIT_PAY,
    AUTO_DEPOSIT_PAY_BYTES,
    AUTO_DEPOSIT_PAY_RESUME,
    AUTO_DEPOSIT_TRUNCATE,
    AUTO_DEPOSIT_TRUNCATE_BYTES,
    AUTO_DEPOSIT_XP_GATE,
    AUTO_DEPOSIT_XP_GATE_BYTES,
    AUTO_DEPOSIT_XP_GATE_RESUME,
    AUTO_DEPOSIT_XP_GATE_SKIP,
    FLOAT_ONE,
    FLOAT_ONE_PERCENT,
    FLOAT_TWO_PERCENT,
    GUI_LOSE_CASH,
    LOSE_CASH_COLOR,
    MONEY_DEPOSIT,
    MONEY_WITHDRAW,
    OBJECT_FILTER_ALLOW,
    OBJECT_FILTER_IS_VALID,
    PLAYER_FOR_EACH_TEAM_OBJECT,
    TERRAIN_RESOURCE_EXP_BLOCK,
    TERRAIN_RESOURCE_FLOOR,
    TERRAIN_RESOURCE_FLOOR_BYTES,
    TERRAIN_RESOURCE_INCOME_GATE,
    TERRAIN_RESOURCE_INCOME_GATE_BYTES,
    TERRAIN_RESOURCE_PAY,
    TERRAIN_RESOURCE_PAY_BYTES,
    TERRAIN_RESOURCE_PAY_RESUME,
    UNICODE_STRING_DTOR,
)
from sage_patch.patches import maintenance_cost as mc
from sage_patch.utils import find_section, va_to_offset

IMAGE_BASE = 0x400000

#: The real binary, when the working copy has one. The synthetic image is built from this
#: patch's own window table, so it round-trips whatever that table says; only the shipped
#: `game.dat` can confirm that `0x008856B0` is the money pointer rather than the middle of
#: something else.
_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: Every entry point, and the address the *stock* path out of it rejoins at. A charge path leaving
#: somewhere else is the point of the patch; a positive path leaving somewhere else is a bug.
ENTRIES = ("lose_text", "trb_floor", "trb_pay", "adu_pay", "adu_xp")


def synthetic_image() -> bytearray:
    """A PE32 image mapping every address this patch touches, with the real original bytes
    planted, so the whole apply + verify path runs in CI without the copyrighted `game.dat`.

    Flat and one-section: file offset is `VA - IMAGE_BASE` throughout, which is what the sparse
    images elsewhere in this directory buy with a section table instead.
    """
    highest = max(va + len(win) for va, win, _what in MaintenanceCostPatch._windows())  # noqa: SLF001
    data = bytearray(((highest - IMAGE_BASE + 0x1000) // 0x200 + 1) * 0x200)

    data[0:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine (i386)
    struct.pack_into("<H", data, e + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)  # PE32 magic
    struct.pack_into("<I", data, opt + 28, IMAGE_BASE)
    struct.pack_into("<I", data, opt + 32, 0x1000)  # SectionAlignment
    struct.pack_into("<I", data, opt + 36, 0x200)  # FileAlignment
    struct.pack_into("<I", data, opt + 56, 0x2000000)  # SizeOfImage
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders, room for more headers
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    mapped = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, mapped, 0x1000, mapped, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header

    for va, window, _what in MaintenanceCostPatch._windows():  # noqa: SLF001
        off = va - IMAGE_BASE
        data[off : off + len(window)] = window
    # Two windows this patch does not own: `second-resource`'s hook site, which it has to leave
    # alone, and `auto-deposit-inflation`'s, so the composition test below has something to apply.
    for va, window in (
        (AUTO_DEPOSIT_DEPOSIT, AUTO_DEPOSIT_DEPOSIT_BYTES),
        (AUTO_DEPOSIT_TRUNCATE, AUTO_DEPOSIT_TRUNCATE_BYTES),
    ):
        off = va - IMAGE_BASE
        data[off : off + len(window)] = window
    return data


@pytest.fixture(scope="module")
def image() -> bytearray:
    return synthetic_image()


@pytest.fixture(scope="module")
def patched(image: bytearray) -> bytes:
    data = bytearray(image)
    MaintenanceCostPatch().apply(data)
    return bytes(data)


def cave(data: bytes) -> tuple[int, bytes]:
    """``(section VA, the emitted code)``."""
    section_va, off, vsize = find_section(data, mc.SECTION_NAME)
    return section_va, bytes(data[off : off + vsize])


def disasm(data: bytes):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    code_va, code = cave(data)
    return list(md.disasm(code, code_va)), code, code_va


def routine(data: bytes, name: str):
    """The instructions of one labelled routine, from its label to the next one."""
    insns, _code, code_va = disasm(data)
    code = mc._assemble(code_va)  # noqa: SLF001
    starts = sorted(code.label_va(entry) for entry in ENTRIES)
    begin = code.label_va(name)
    end = next((s for s in starts if s > begin), code_va + sum(i.size for i in insns))
    return [i for i in insns if begin <= i.address < end]


class TestWhatAChargeMeans:
    """`charge` is the rule in Python; the emitted code is asserted against it below.

    Stating it once is what makes "did I mean this?" a separate question from "did I encode it
    right?" - the two failure modes this patch has.
    """

    def test_no_inflation_is_full_price(self):
        assert mc.charge(-5, 1.0, floor=True) == 5
        assert mc.charge(-5, 1.0, floor=False) == 5

    @pytest.mark.parametrize(
        ("multiplier", "taken"),
        [(1.0, 5), (0.8, 4), (0.6, 3), (0.5, 2), (0.1, 1), (0.0, 1)],
    )
    def test_inflation_scales_the_charge_the_way_it_scales_an_income(self, multiplier, taken):
        """Ten farms that keep 60% of their income cost 60% of their upkeep - one multiplier
        applied to one signed number, upstream of this patch. For `TerrainResourceBehavior` the
        engine applies it; for `AutoDepositUpdate` `auto-deposit-inflation` does, and the
        multiplier is 1.0 without it. `0.5` gives 2 rather than 3 because rounding is toward
        zero."""
        assert mc.charge(-5, multiplier, floor=True) == taken

    def test_a_charge_scaled_to_nothing_still_floors_where_an_income_would(self):
        """The stock floor exists so an income never rounds away to nothing; mirrored, a charge
        never does either. Only `TerrainResourceBehavior` has that rule."""
        assert mc.charge(-5, 0.0, floor=True) == 1
        assert mc.charge(-5, 0.0, floor=False) == 0

    def test_rounding_is_toward_zero_in_the_players_favour(self):
        assert mc.charge(-10, 0.35, floor=False) == 3  # 3.5, not 4

    def test_a_positive_amount_is_not_a_charge(self):
        with pytest.raises(ValueError, match="only a negative"):
            mc.charge(5, 1.0, floor=True)


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self, patched):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns, code, _code_va = disasm(patched)
        assert sum(i.size for i in insns) == len(code)

    def test_it_relocates_with_its_section(self):
        a = mc._assemble(0x00F00000).finish()  # noqa: SLF001
        b = mc._assemble(0x00F01000).finish()  # noqa: SLF001
        assert a != b
        assert len(a) == len(b)

    @pytest.mark.parametrize("name", ENTRIES)
    def test_no_routine_falls_through_into_the_next(self, patched, name):
        """Every routine ends by leaving - `ret` for the two helpers, `jmp` back into the engine
        for the four entries. A fall-through would run the next routine's prologue as if it were
        this one's continuation."""
        assert routine(patched, name)[-1].mnemonic in {"ret", "jmp"}

    def test_a_charge_never_reaches_money_deposit(self, patched):
        """The balance is unsigned and `Money::deposit` is an unclamped `add`, so a negative
        arriving there is about four billion gold. Both charge paths withdraw instead, and the
        cave calls `deposit` nowhere - the positive path rejoins the engine's own call."""
        insns, _code, _va = disasm(patched)
        called = {
            int(i.op_str, 16) for i in insns if i.mnemonic == "call" and i.op_str.startswith("0x")
        }
        assert MONEY_DEPOSIT not in called
        assert MONEY_WITHDRAW in called
        for name in ("trb_pay", "adu_pay"):
            withdrawals = [
                i
                for i in routine(patched, name)
                if i.mnemonic == "call" and i.op_str == hex(MONEY_WITHDRAW)
            ]
            assert len(withdrawals) == 1, name

    def test_the_amount_is_negated_before_it_is_withdrawn(self, patched):
        """`withdraw` takes a magnitude, and both modules already pushed the signed amount as the
        deposit's first argument - so negating that slot in place is the whole conversion, and
        `withdraw`'s `ret 0xc` cleans the stock call's own stack."""
        for name in ("trb_pay", "adu_pay"):
            text = [i.mnemonic + " " + i.op_str for i in routine(patched, name)]
            assert "neg dword ptr [esp]" in text, name


class TestItComputesNothing:
    """The charge is whatever amount reached the hook. That is the whole of how
    `auto-deposit-inflation` decides whether an `AutoDepositUpdate` charge is inflated, so it is
    worth asserting that this patch cannot quietly grow a multiplier of its own.
    """

    def test_the_cave_calls_no_inflation_machinery(self, patched):
        insns, _code, _va = disasm(patched)
        called = {
            int(i.op_str, 16) for i in insns if i.mnemonic == "call" and i.op_str.startswith("0x")
        }
        assert not called & {
            OBJECT_FILTER_IS_VALID,
            OBJECT_FILTER_ALLOW,
            PLAYER_FOR_EACH_TEAM_OBJECT,
        }

    def test_it_reads_none_of_the_inflation_constants(self, patched):
        """`0.01f` and `0.02f` are the multiplier's; the only float this patch touches is the sign
        of the one already in `TerrainResourceBehavior`'s frame."""
        insns, _code, _va = disasm(patched)
        referenced = {
            int(i.op_str.split("[")[1].split("]")[0], 16) for i in insns if "[0x" in i.op_str
        }
        assert not referenced & {FLOAT_ONE, FLOAT_ONE_PERCENT, FLOAT_TWO_PERCENT}

    def test_the_auto_deposit_charge_is_the_amount_that_arrived(self, patched):
        """No multiply, no convert - `neg` and `withdraw`. What reaches `[esp]` is what is taken,
        which is why applying `auto-deposit-inflation` inflates a charge and not applying it
        leaves the charge flat."""
        text = [i.mnemonic for i in routine(patched, "adu_pay")]
        assert "mulss" not in text
        assert "cvtsi2ss" not in text
        assert "cvttss2si" not in text


class TestThePositivePathIsStock:
    def test_the_income_gate_keeps_its_length_and_its_target(self, patched):
        """`jle` -> `je` in place: six bytes for six, the same rel32, so the zero case still lands
        exactly where it landed and nothing downstream moves."""
        off = va_to_offset(patched, TERRAIN_RESOURCE_INCOME_GATE)
        got = bytes(patched[off : off + len(TERRAIN_RESOURCE_INCOME_GATE_BYTES)])
        assert len(got) == len(TERRAIN_RESOURCE_INCOME_GATE_BYTES)
        assert got[2:] == TERRAIN_RESOURCE_INCOME_GATE_BYTES[2:]
        assert got[:2] == b"\x0f\x84"

    def test_the_floor_keeps_the_stock_sequence_for_an_income(self, patched):
        """The positive branch is the stock instructions, condition included, so an income that
        rounds to zero is still raised to one gold and nothing else is."""
        text = [i.mnemonic + " " + i.op_str for i in routine(patched, "trb_floor")]
        assert "test ebx, ebx" in text
        assert any(m.startswith("jg ") for m in text)
        assert "mov ebx, 1" in text
        assert "mov ebx, 0xffffffff" in text, "and the charge branch floors at -1"

    @pytest.mark.parametrize(
        ("name", "resume"),
        [("trb_pay", TERRAIN_RESOURCE_PAY_RESUME), ("adu_pay", AUTO_DEPOSIT_PAY_RESUME)],
    )
    def test_a_positive_amount_rejoins_the_stock_deposit(self, patched, name, resume):
        """The sign test is the first branch in both entries and its untaken side goes straight
        back - so a mod that declares no negative income runs the stock instruction stream with
        one jump in the middle of it."""
        insns = routine(patched, name)
        assert insns[0].mnemonic == "lea", "the displaced instruction comes first"
        assert insns[1].mnemonic == "test"
        assert insns[2].mnemonic == "jl"
        assert insns[3].mnemonic == "jmp" and int(insns[3].op_str, 16) == resume

    def test_the_auto_deposit_hook_leaves_the_deposit_call_alone(self, patched):
        """`second-resource` owns that call. Stopping one instruction short of it is the whole
        reason the hook is on the `lea` rather than on the `call`."""
        off = va_to_offset(patched, AUTO_DEPOSIT_DEPOSIT)
        assert bytes(patched[off : off + len(AUTO_DEPOSIT_DEPOSIT_BYTES)]) == (
            AUTO_DEPOSIT_DEPOSIT_BYTES
        )

    def test_the_experience_gate_still_honours_give_no_xp(self, patched):
        """The stock `GiveNoXP` test is reproduced, not replaced: the new reason to skip is a
        second condition after it, and both land on the address the stock `jne` jumped to."""
        insns = routine(patched, "adu_xp")
        text = [i.mnemonic + " " + i.op_str for i in insns]
        assert text[0] == "cmp byte ptr [eax + 0x20], 0"
        assert text[2] == "cmp dword ptr [eax + 0xc], 0"
        targets = [int(i.op_str, 16) for i in insns if i.mnemonic == "jmp"]
        assert targets == [AUTO_DEPOSIT_XP_GATE_RESUME, AUTO_DEPOSIT_XP_GATE_SKIP]


class TestTheChargePath:
    def test_a_terrain_charge_grants_no_experience(self, patched):
        """`ebx` is the experience block's only input, so zeroing it makes a charge tick the stock
        "no income this tick" case rather than a veterancy drain down an unaudited path."""
        insns = routine(patched, "trb_pay")
        text = [i.mnemonic + " " + i.op_str for i in insns]
        assert "xor ebx, ebx" in text
        assert text.index("xor ebx, ebx") > text.index("neg dword ptr [esp]")
        assert int(insns[-1].op_str, 16) == TERRAIN_RESOURCE_EXP_BLOCK

    def test_an_auto_deposit_charge_skips_the_deposit_call(self, patched):
        insns = routine(patched, "adu_pay")
        assert int(insns[-1].op_str, 16) == AUTO_DEPOSIT_DEPOSIT_RESUME

    @pytest.mark.parametrize("name", ["trb_pay", "adu_pay"])
    def test_nothing_is_said_when_nothing_was_taken(self, patched, name):
        """`withdraw` clamps to the purse and returns what it took, so a broke player is charged
        zero - and a floating "-0" over the building would be noise."""
        insns = routine(patched, name)
        after = [i for i in insns if i.address > _call_of(insns, MONEY_WITHDRAW)]
        assert after[0].mnemonic == "test" and after[0].op_str == "eax, eax"
        assert after[1].mnemonic == "je"

    @pytest.mark.parametrize("name", ["trb_pay", "adu_pay"])
    def test_the_charge_text_is_balanced(self, patched, name):
        """`lose_text` is cdecl, so its two arguments are the caller's to drop - and the entries
        leave by `jmp`, so a leaked slot corrupts the update they return into rather than being
        recovered by anybody."""
        text = [i.mnemonic + " " + i.op_str for i in routine(patched, name)]
        assert text.count("add esp, 8") == 1


class TestTheFloatingText:
    def test_it_uses_the_engines_own_lose_cash_string(self, patched):
        """`GUI:LoseCash` and the red the engine draws it in come from the money-transfer site at
        `0x008C6980`, whose green half is what both income modules already draw. No new string
        key, so no `.csf` edit - the same reason `inflation-readout` needs none."""
        pushes = [
            int(i.op_str, 16)
            for i in routine(patched, "lose_text")
            if i.mnemonic == "push" and i.op_str.startswith("0x")
        ]
        assert pushes == [GUI_LOSE_CASH, LOSE_CASH_COLOR]

    def test_the_string_starts_empty_and_is_destroyed(self, patched):
        """`UNICODE_STRING_CONCAT` *replaces* rather than appends and releases what the
        destination held, so the slot has to start zeroed - and the result owns a real allocation,
        so it has to be destroyed before the frame goes."""
        insns = routine(patched, "lose_text")
        text = [i.mnemonic + " " + i.op_str for i in insns]
        assert "and dword ptr [ebp - 4], 0" in text
        assert any(i.mnemonic == "call" and i.op_str == hex(UNICODE_STRING_DTOR) for i in insns)
        assert text.index("and dword ptr [ebp - 4], 0") < text.index("lea ecx, [ebp - 4]")

    def test_the_frame_is_balanced(self, patched):
        insns = routine(patched, "lose_text")
        assert [i.mnemonic for i in insns[:4]] == ["push", "mov", "sub", "push"]
        assert [i.mnemonic for i in insns[-3:]] == ["pop", "leave", "ret"]


class TestApply:
    def test_apply_then_verify(self, patched):
        assert MaintenanceCostPatch().verify(patched) == []

    def test_detect_round_trips(self, patched):
        found = MaintenanceCostPatch.detect(patched)
        assert found is not None
        assert found.name == "maintenance-cost"

    def test_a_clean_image_carries_nothing(self, image):
        assert MaintenanceCostPatch.detect(bytes(image)) is None
        assert MaintenanceCostPatch().verify(bytes(image))

    def test_it_writes_nothing_outside_its_sites(self, image, patched):
        """Everything past the original image is the appended cave; everything inside it is one of
        the five windows."""
        windows = {
            va - IMAGE_BASE + i
            for va, win, _what in MaintenanceCostPatch._windows()  # noqa: SLF001
            for i in range(len(win))
        }
        changed = {i for i in range(len(image)) if image[i] != patched[i]}
        # the rest is the PE header growing by one section entry and its counts moving with it
        assert changed - windows <= set(range(0x400))

    def test_the_section_is_not_writable(self, patched):
        """The cave is code and an import-free one; nothing in it is written at run time."""
        section_va, _code = cave(patched)
        assert section_va  # it exists
        assert not (mc._CHARACTERISTICS & 0x80000000)  # noqa: SLF001

    def test_the_section_name_survives_the_eight_byte_pe_field(self, patched):
        assert len(mc.SECTION_NAME) <= 8
        assert find_section(patched, mc.SECTION_NAME) is not None

    def test_refuses_to_apply_twice(self, image):
        data = bytearray(image)
        MaintenanceCostPatch().apply(data)
        with pytest.raises(ValueError, match="already carries"):
            MaintenanceCostPatch().apply(data)

    @pytest.mark.parametrize(
        ("va", "window"),
        [
            (TERRAIN_RESOURCE_INCOME_GATE, TERRAIN_RESOURCE_INCOME_GATE_BYTES),
            (TERRAIN_RESOURCE_FLOOR, TERRAIN_RESOURCE_FLOOR_BYTES),
            (TERRAIN_RESOURCE_PAY, TERRAIN_RESOURCE_PAY_BYTES),
            (AUTO_DEPOSIT_PAY, AUTO_DEPOSIT_PAY_BYTES),
            (AUTO_DEPOSIT_XP_GATE, AUTO_DEPOSIT_XP_GATE_BYTES),
        ],
    )
    def test_refuses_a_build_whose_site_is_not_the_stock_one(self, image, va, window):
        data = bytearray(image)
        off = va - IMAGE_BASE
        data[off : off + len(window)] = b"\x90" * len(window)
        with pytest.raises(ValueError, match="unexpected build"):
            MaintenanceCostPatch().apply(data)
        assert find_section(data, mc.SECTION_NAME) is None, "a refused build keeps no cave"

    def test_verify_notices_a_tampered_cave(self, patched):
        data = bytearray(patched)
        _section_va, off, _vsize = find_section(data, mc.SECTION_NAME)
        data[off] ^= 0xFF
        assert MaintenanceCostPatch().verify(bytes(data))

    def test_verify_notices_a_reverted_site(self, patched):
        data = bytearray(patched)
        off = va_to_offset(data, TERRAIN_RESOURCE_PAY)
        data[off : off + len(TERRAIN_RESOURCE_PAY_BYTES)] = TERRAIN_RESOURCE_PAY_BYTES
        assert MaintenanceCostPatch().verify(bytes(data))

    def test_it_adds_no_ini_surface(self, patched):
        """`INI::parseInt` already takes a minus sign, so there is no keyword to declare - which
        is also why a mod using this still loads on an unpatched binary."""
        assert MaintenanceCostPatch().ini_surface().fields == ()


def _call_of(insns, target: int) -> int:
    """The address of the `call` to ``target`` in ``insns``."""
    for i in insns:
        if i.mnemonic == "call" and i.op_str == hex(target):
            return i.address
    raise AssertionError(f"no call to 0x{target:08x}")


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the addresses are right."""

    @pytest.fixture(scope="class")
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_site_holds_its_stock_bytes(self, stock):
        for va, window, what in MaintenanceCostPatch._windows():  # noqa: SLF001
            off = va_to_offset(stock, va)
            assert off is not None, f"0x{va:08x} is not mapped"
            assert bytes(stock[off : off + len(window)]) == window, what

    def test_the_second_resource_hook_site_is_a_whole_call(self, stock):
        """This patch stops one instruction short of it on purpose. If that call ever moves, the
        reason for hooking the `lea` instead moves with it."""
        off = va_to_offset(stock, AUTO_DEPOSIT_DEPOSIT)
        assert (
            bytes(stock[off : off + len(AUTO_DEPOSIT_DEPOSIT_BYTES)]) == AUTO_DEPOSIT_DEPOSIT_BYTES
        )

    def test_apply_verify_detect_round_trip(self, stock):
        data = bytearray(stock)
        patch = MaintenanceCostPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert MaintenanceCostPatch.detect(data) is not None

    def test_it_composes_with_the_patches_that_share_its_functions(self, stock):
        """`terrain-resource-exp` owns the experience block this patch jumps to, `second-resource`
        owns the deposit call it stops short of, and `command-point-upkeep` scales the multiplier
        it rides on. None of the three is order-sensitive against this one."""
        from sage_patch import (  # noqa: PLC0415
            CommandPointUpkeepPatch,
            InflationReadoutPatch,
            SecondResourcePatch,
            TerrainResourceExpPatch,
        )

        others = (
            TerrainResourceExpPatch,
            SecondResourcePatch,
            CommandPointUpkeepPatch,
            InflationReadoutPatch,
        )
        for other in others:
            for order in ((MaintenanceCostPatch, other), (other, MaintenanceCostPatch)):
                data = bytearray(stock)
                for cls in order:
                    cls().apply(data)
                for cls in order:
                    assert cls().verify(data) == [], f"{order[0].name} then {order[1].name}"


class TestWithAutoDepositInflation:
    """The seam between the two patches is one number in `eax`, so it is asserted as bytes rather
    than as intent: neither hook may move onto the other's instruction, and the scale has to land
    *above* the charge or a charge would be taken unscaled."""

    def test_the_hooks_are_ordered_and_disjoint(self):
        scale_end = AUTO_DEPOSIT_TRUNCATE + len(AUTO_DEPOSIT_TRUNCATE_BYTES)
        assert scale_end <= AUTO_DEPOSIT_PAY, "the scale has to finish before the charge starts"

    def test_both_apply_in_either_order(self, image):
        from sage_patch import AutoDepositInflationPatch  # noqa: PLC0415

        pair = (MaintenanceCostPatch, AutoDepositInflationPatch)
        for order in (pair, pair[::-1]):
            data = bytearray(image)
            for cls in order:
                cls().apply(data)
            for cls in order:
                assert cls().verify(data) == [], f"{order[0].name} then {order[1].name}"
