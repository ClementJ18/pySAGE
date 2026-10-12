"""Tests for the model-condition-images patch.

The cave walks engine structures the tests cannot load, so the walk is run under an emulator over a
hand-built Object -> Drawable -> draw modules -> current state chain, with the image lookup
stubbed. What could be wrong without raising is which module answers, what falls through to the
stock resolver (and with which registers and flags), and when the ControlBar is marked dirty.
"""

from __future__ import annotations

import faulthandler
import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sage_patch.addresses import (
    CONTROL_BAR_BUTTON_IMAGE_FALLBACK,
    CONTROL_BAR_BUTTON_IMAGE_FALLBACK_RESUME,
    CONTROL_BAR_SELECT_PORTRAIT,
    CONTROL_BAR_SELECT_PORTRAIT_RESUME,
    MODEL_CONDITION_BUTTON_IMAGE,
    MODEL_CONDITION_PORTRAIT_IMAGE,
    OBJECT_IMAGE_UPGRADE_FIND_IMAGE,
    OBJECT_IMAGE_UPGRADE_THE_CONTROL_BAR,
    OBJECT_IMAGE_UPGRADE_THE_IMAGES,
    W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE,
    W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_HOOK,
    W3D_MODEL_DRAW_SET_MODEL_STATE,
    W3D_MODEL_DRAW_SET_MODEL_STATE_HOOK,
)
from sage_patch.patches.model_condition_images import (
    ANCHORS,
    HOOKS,
    SECTION_NAME,
    ModelConditionImagesPatch,
    build_code,
)
from sage_patch.patches.object_image_upgrade import ObjectImageUpgradePatch
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, jmp_rel32, va_to_offset
from tests.sage_patch.synthetic import model_condition_images_image


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


def _cave_va(data: bytes | bytearray) -> int:
    located = find_section(data, SECTION_NAME)
    assert located is not None, f"no {SECTION_NAME} section"
    return located[0]


@pytest.fixture
def image() -> bytearray:
    return model_condition_images_image()


@pytest.fixture
def patched() -> bytearray:
    data = model_condition_images_image()
    ModelConditionImagesPatch().apply(data)
    return data


class TestStructure:
    def test_the_fields_are_the_rows_offsets(self) -> None:
        offsets = sorted(
            struct.unpack_from("<I", blob, 12)[0] for blob in ANCHORS.values() if len(blob) == 16
        )
        assert offsets == [MODEL_CONDITION_BUTTON_IMAGE, MODEL_CONDITION_PORTRAIT_IMAGE]

    def test_every_hook_jumps_into_the_cave(self, patched: bytearray) -> None:
        code = build_code(_cave_va(patched))
        for va, (stock, label) in HOOKS.items():
            want = jmp_rel32(va, code.label_va(label)) + b"\x90" * (len(stock) - 5)
            assert _read(patched, va, len(stock)) == want

    def test_each_stub_replays_what_it_displaced(self) -> None:
        body = build_code(0x01000000).finish()
        for va, (stock, _label) in HOOKS.items():
            # The button exit keeps only its `mov`; its `jmp` is re-made against the cave.
            assert (stock if va != CONTROL_BAR_BUTTON_IMAGE_FALLBACK else stock[:4]) in body


class TestLifecycle:
    def test_apply_verify_detect(self, patched: bytearray) -> None:
        assert ModelConditionImagesPatch().verify(patched) == []
        assert isinstance(ModelConditionImagesPatch.detect(patched), ModelConditionImagesPatch)

    def test_an_unpatched_image_is_not_detected(self, image: bytearray) -> None:
        assert ModelConditionImagesPatch().verify(image) != []
        assert ModelConditionImagesPatch.detect(image) is None

    def test_a_second_apply_refuses_before_writing(self, patched: bytearray) -> None:
        before = bytes(patched)
        with pytest.raises(ValueError, match="already"):
            ModelConditionImagesPatch().apply(patched)
        assert bytes(patched) == before

    @pytest.mark.parametrize("va", sorted(ANCHORS), ids=lambda va: f"{va:#010x}")
    def test_a_drifted_anchor_refuses_before_writing(self, image: bytearray, va: int) -> None:
        off = va_to_offset(image, va)
        assert off is not None
        image[off] ^= 0xFF
        before = bytes(image)
        with pytest.raises(ValueError, match="layout is not this build's"):
            ModelConditionImagesPatch().apply(image)
        assert bytes(image) == before

    def test_registered_as_settled(self) -> None:
        assert PATCHES["model-condition-images"] is ModelConditionImagesPatch
        assert not ModelConditionImagesPatch.experimental


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_PAGE = 0x1000
_CAVE = 0x01000000
_HEAP = 0x20000000
_STACK = 0x30000000
_RETURN = 0x40000000
_IMAGES = 0x0BADC0DE
_CONTROL_BAR = _HEAP + 0xF000
_TEMPLATE = 0x7E7E7E7E
_OTHER_VTABLE_FN = 0x004C9323  # any slot +0x100 that is neither setModelState
_ZF = 1 << 6


@dataclass
class Module:
    set_model_state: int = W3D_MODEL_DRAW_SET_MODEL_STATE
    portrait: str | None = None
    button: str | None = None
    no_state: bool = False


@dataclass
class World:
    modules: list[Module] = field(default_factory=list)
    has_drawable: bool = True
    images_loaded: bool = True
    known: frozenset[str] = frozenset({"HP_Mounted", "HI_Mounted", "HP_Second"})
    lookups: list[str] = field(default_factory=list)


class _Emu:
    """One emulator holding the cave, the stub targets, and a world laid out on the heap."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_32)
        stops = {
            CONTROL_BAR_SELECT_PORTRAIT_RESUME,
            CONTROL_BAR_BUTTON_IMAGE_FALLBACK_RESUME,
            W3D_MODEL_DRAW_SET_MODEL_STATE_HOOK + 6,
            W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_HOOK + 6,
        }
        pages = {_CAVE, _STACK, _RETURN, OBJECT_IMAGE_UPGRADE_FIND_IMAGE & ~0xFFF}
        pages |= {
            OBJECT_IMAGE_UPGRADE_THE_IMAGES & ~0xFFF,
            OBJECT_IMAGE_UPGRADE_THE_CONTROL_BAR & ~0xFFF,
        }
        pages |= {va & ~0xFFF for va in stops}
        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            for page in sorted(pages):
                uc.mem_map(page, _PAGE)
            uc.mem_map(_HEAP, 0x10000)
        finally:
            if was_enabled:
                faulthandler.enable()

        self.code = build_code(_CAVE)
        uc.mem_write(_CAVE, self.code.finish())
        uc.mem_write(
            OBJECT_IMAGE_UPGRADE_THE_IMAGES,
            struct.pack("<I", _IMAGES if world.images_loaded else 0),
        )
        uc.mem_write(OBJECT_IMAGE_UPGRADE_THE_CONTROL_BAR, struct.pack("<I", _CONTROL_BAR))
        self._cursor = _HEAP + 0x100
        self.object = self._alloc(0x100)
        if world.has_drawable:
            drawable = self._alloc(0x200)
            uc.mem_write(self.object + 0x84, struct.pack("<I", drawable))
            array = self._alloc(4 * (len(world.modules) + 1))
            uc.mem_write(drawable + 0x14C, struct.pack("<I", array))
            self.modules = [self._module(m) for m in world.modules]
            uc.mem_write(array, b"".join(struct.pack("<I", m) for m in self.modules) + bytes(4))
        self.stops = stops
        uc.hook_add(UC_HOOK_CODE, self._on_code)

    def _alloc(self, size: int) -> int:
        va = self._cursor
        self._cursor += (size + 0xF) & ~0xF
        return va

    def string(self, text: str | None) -> int:
        """An AsciiString field value: NULL for none, else a buffer {refs, length, chars at +8}."""
        if text is None:
            return 0
        buf = self._alloc(8 + len(text) + 1)
        self.uc.mem_write(buf, struct.pack("<IH2x", 1, len(text)) + text.encode() + b"\0")
        return buf

    def state(self, portrait: str | None, button: str | None) -> int:
        state = self._alloc(0x100)
        self.uc.mem_write(
            state + MODEL_CONDITION_PORTRAIT_IMAGE, struct.pack("<I", self.string(portrait))
        )
        self.uc.mem_write(
            state + MODEL_CONDITION_BUTTON_IMAGE, struct.pack("<I", self.string(button))
        )
        return state

    def _module(self, m: Module) -> int:
        vtable = self._alloc(0x110)
        self.uc.mem_write(vtable + 0x100, struct.pack("<I", m.set_model_state))
        module = self._alloc(0x40)
        state = 0 if m.no_state else self.state(m.portrait, m.button)
        self.uc.mem_write(module, struct.pack("<I", vtable))
        self.uc.mem_write(module + 0x14, struct.pack("<I", state))
        return module

    def _on_code(self, uc: Uc, address: int, _size: int, _user: object) -> None:
        if address in self.stops:
            uc.emu_stop()
            return
        if address != OBJECT_IMAGE_UPGRADE_FIND_IMAGE:
            return
        esp = uc.reg_read(UC_X86_REG_ESP)
        ret, arg = struct.unpack("<II", bytes(uc.mem_read(esp, 8)))
        assert uc.reg_read(UC_X86_REG_ECX) == _IMAGES
        buf = struct.unpack("<I", bytes(uc.mem_read(arg, 4)))[0]
        text = bytes(uc.mem_read(buf + 8, 64)).split(b"\0")[0].decode()
        self.world.lookups.append(text)
        image = (0x1A6E0000 + len(self.world.lookups)) if text in self.world.known else 0
        uc.reg_write(UC_X86_REG_EAX, image)
        uc.reg_write(UC_X86_REG_ESP, esp + 8)
        uc.reg_write(UC_X86_REG_EIP, ret)

    def start(self, label: str, esp: int) -> int:
        self.uc.reg_write(UC_X86_REG_ESP, esp)
        self.uc.emu_start(self.code.label_va(label), _RETURN, count=2000)
        return self.uc.reg_read(UC_X86_REG_EIP)

    def call_resolver(self, label: str) -> tuple[int, int]:
        """Enter a resolver hook as `cdecl (template, object)`; answer (where it left, eax)."""
        esp = _STACK + 0x800 - 12
        self.uc.mem_write(esp, struct.pack("<III", _RETURN, _TEMPLATE, self.object))
        self.uc.reg_write(UC_X86_REG_ESI, 0x5E5E5E5E)
        left = self.start(label, esp)
        assert self.uc.reg_read(UC_X86_REG_ESI) == 0x5E5E5E5E
        # A `ret` pops the return address; a jump back into the stock resolver leaves it there.
        assert self.uc.reg_read(UC_X86_REG_ESP) == (esp + 4 if left == _RETURN else esp)
        return left, self.uc.reg_read(UC_X86_REG_EAX)


class TestResolvers:
    @pytest.mark.parametrize(
        ("label", "module", "want"),
        [
            ("portrait_hook", Module(portrait="HP_Mounted", button="HI_Mounted"), "HP_Mounted"),
            ("button_hook", Module(portrait="HP_Mounted", button="HI_Mounted"), "HI_Mounted"),
        ],
    )
    def test_the_current_state_names_the_image(self, label: str, module: Module, want: str) -> None:
        world = World(modules=[module])
        left, eax = _Emu(world).call_resolver(label)
        assert left == _RETURN
        assert eax != 0
        assert world.lookups == [want]

    def test_a_horde_draw_counts(self) -> None:
        world = World(
            modules=[
                Module(set_model_state=W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE, portrait="HP_Mounted")
            ]
        )
        assert _Emu(world).call_resolver("portrait_hook")[0] == _RETURN

    def test_the_first_module_with_a_known_image_wins(self) -> None:
        world = World(
            modules=[
                Module(set_model_state=_OTHER_VTABLE_FN, portrait="HP_Mounted"),
                Module(no_state=True),
                Module(portrait=None),
                Module(portrait="HP_Unknown"),
                Module(portrait="HP_Second"),
                Module(portrait="HP_Mounted"),
            ]
        )
        left, _ = _Emu(world).call_resolver("portrait_hook")
        assert left == _RETURN
        # Not the non-model module's, and the unknown name is passed over.
        assert world.lookups == ["HP_Unknown", "HP_Second"]

    @pytest.mark.parametrize(
        "world",
        [
            World(modules=[Module()]),
            World(modules=[Module(portrait="")]),
            World(modules=[Module(portrait="HP_Unknown")]),
            World(modules=[Module(portrait="HP_Mounted")], images_loaded=False),
            World(modules=[Module(portrait="HP_Mounted")], has_drawable=False),
            World(modules=[]),
        ],
        ids=["no name", "empty name", "unknown name", "no images", "no drawable", "no modules"],
    )
    def test_otherwise_the_stock_portrait_resolver_runs(self, world: World) -> None:
        emu = _Emu(world)
        left, _ = emu.call_resolver("portrait_hook")
        assert left == CONTROL_BAR_SELECT_PORTRAIT_RESUME
        # Its displaced `mov ecx, [esp+4]; test ecx, ecx` - the `je` after reads those flags.
        assert emu.uc.reg_read(UC_X86_REG_ECX) == _TEMPLATE
        assert not emu.uc.reg_read(UC_X86_REG_EFLAGS) & _ZF

    def test_otherwise_the_stock_button_resolver_runs(self) -> None:
        emu = _Emu(World(modules=[Module(portrait="HP_Mounted")]))
        left, _ = emu.call_resolver("button_hook")
        assert left == CONTROL_BAR_BUTTON_IMAGE_FALLBACK_RESUME
        assert emu.uc.reg_read(UC_X86_REG_ECX) == _TEMPLATE


class TestStateChange:
    def _run(
        self,
        hook: str,
        old: tuple[str | None, str | None] | None,
        new: tuple[str | None, str | None],
        share: bool = False,
    ) -> tuple[_Emu, int, int]:
        emu = _Emu(World(modules=[Module()]))
        module = emu.modules[0]
        old_state = 0 if old is None else emu.state(*old)
        if share:
            new_state = old_state
        else:
            new_state = emu.state(*new)
        emu.uc.mem_write(module + 0x14, struct.pack("<I", old_state))
        emu.uc.mem_write(module + 8, struct.pack("<I", 0xD7A3AB1E))  # the Drawable
        emu.uc.mem_write(module + 0xC0, struct.pack("<I", 0xC0C0C0C0))
        emu.uc.mem_write(_CONTROL_BAR + 0x28, b"\0")
        new_reg = UC_X86_REG_EDI if hook == "base_hook" else UC_X86_REG_EBX
        emu.uc.reg_write(UC_X86_REG_ESI, module)
        emu.uc.reg_write(new_reg, new_state)
        emu.uc.reg_write(UC_X86_REG_EDX, 0xED0ED0ED)
        esp = _STACK + 0x800
        left = emu.start(hook, esp)
        assert emu.uc.reg_read(UC_X86_REG_ESP) == esp
        assert emu.uc.reg_read(UC_X86_REG_ESI) == module
        assert emu.uc.reg_read(new_reg) == new_state
        assert emu.uc.reg_read(UC_X86_REG_EDX) == 0xED0ED0ED
        return emu, left, new_state

    @staticmethod
    def _dirty(emu: _Emu) -> bool:
        return bytes(emu.uc.mem_read(_CONTROL_BAR + 0x28, 1)) == b"\x01"

    @pytest.mark.parametrize("hook", ["base_hook", "horde_hook"])
    @pytest.mark.parametrize(
        ("old", "new", "dirty"),
        [
            ((None, None), ("HP_Mounted", None), True),
            ((None, "HI_A"), (None, "HI_B"), True),
            (("HP_Mounted", None), (None, None), True),
            ((None, None), (None, None), False),
            (None, ("HP_Mounted", "HI_Mounted"), False),
        ],
        ids=["portrait appears", "button changes", "portrait goes", "neither", "first state"],
    )
    def test_dirty_when_a_name_changes(
        self, hook: str, old: tuple | None, new: tuple, dirty: bool
    ) -> None:
        emu, _, _ = self._run(hook, old, new)
        assert self._dirty(emu) is dirty

    def test_re_entering_the_same_state_is_clean(self) -> None:
        emu, _, _ = self._run("base_hook", ("HP_Mounted", None), (None, None), share=True)
        assert not self._dirty(emu)

    def test_the_base_hook_replays_and_resumes(self) -> None:
        emu, left, new_state = self._run("base_hook", None, (None, None))
        assert left == W3D_MODEL_DRAW_SET_MODEL_STATE_HOOK + 6
        assert emu.uc.reg_read(UC_X86_REG_ECX) == 0xD7A3AB1E  # mov ecx, [esi+8]
        assert emu.uc.reg_read(UC_X86_REG_EAX) == new_state + 0x74  # lea eax, [edi+0x74]

    def test_the_horde_hook_replays_and_resumes(self) -> None:
        emu, left, _ = self._run("horde_hook", None, (None, None))
        assert left == W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_HOOK + 6
        assert emu.uc.reg_read(UC_X86_REG_ECX) == 0xC0C0C0C0  # mov ecx, [esi+0xc0]


#: Both copies a checkout can hold; neither is committed, so each check skips when absent.
_BINARIES = {
    "repo": Path(__file__).resolve().parents[2] / "game.dat",
    "clean": Path(__file__).resolve().parents[2] / "sage_patch" / "engine" / "game.dat.backup",
}


@pytest.mark.parametrize("which", sorted(_BINARIES))
class TestStockBinaries:
    def _stock(self, which: str) -> bytes:
        path = _BINARIES[which]
        if not path.exists():
            pytest.skip(f"needs {path.name}")
        return path.read_bytes()

    def test_every_site_is_stock(self, which: str) -> None:
        stock = self._stock(which)
        for va, (expected, _label) in HOOKS.items():
            assert _read(stock, va, len(expected)) == expected, f"{va:#010x}"
        for va, expected in ANCHORS.items():
            assert _read(stock, va, len(expected)) == expected, f"{va:#010x}"

    def test_apply_verify_detect_round_trip(self, which: str) -> None:
        data = bytearray(self._stock(which))
        ModelConditionImagesPatch().apply(data)
        assert ModelConditionImagesPatch().verify(data) == []
        assert isinstance(ModelConditionImagesPatch.detect(data), ModelConditionImagesPatch)

    @pytest.mark.parametrize("first_ours", [True, False])
    def test_composes_with_object_image_upgrade(self, which: str, first_ours: bool) -> None:
        # Both intercept the same two resolvers: object-image-upgrade at their entries, this patch
        # in their template fallbacks, so neither reads bytes the other rewrites.
        data = bytearray(self._stock(which))
        patches = [ModelConditionImagesPatch(), ObjectImageUpgradePatch()]
        for patch in patches if first_ours else patches[::-1]:
            patch.apply(data)
        assert all(patch.verify(data) == [] for patch in patches)
        assert CONTROL_BAR_SELECT_PORTRAIT in HOOKS
