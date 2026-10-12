"""Let `ModelConditionState`'s `PortraitImageName` and `ButtonImageName` reach the UI for every
object, not only Create-a-Hero heroes.

    ConditionState = MOUNTED
      Model             = GUMounted_SKN
      PortraitImageName = HP_Hero_Mounted
      ButtonImageName   = HI_Hero_Mounted
    End

Stock, both fields parse into every state but the two UI resolvers only read them for an object
with `KindOf = CREATE_A_HERO` (through the hero's Create-a-Hero record). The patch gives the
resolvers' template fallbacks a first look at the object's model draws: the first one whose current
state names an image wins, and an empty or unknown name falls through to the template's
`SelectPortrait` / `ButtonImage` as before. A state change whose two names differ from the old
state's marks the ControlBar dirty so the shown image follows it. Presentation only.

Derivation: `../docs/model-condition-images.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    CONTROL_BAR_BUTTON_IMAGE_FALLBACK,
    CONTROL_BAR_BUTTON_IMAGE_FALLBACK_BYTES,
    CONTROL_BAR_BUTTON_IMAGE_FALLBACK_RESUME,
    CONTROL_BAR_SELECT_PORTRAIT,
    CONTROL_BAR_SELECT_PORTRAIT_BYTES,
    CONTROL_BAR_SELECT_PORTRAIT_RESUME,
    DRAWABLE_DRAW_MODULES,
    DRAWABLE_DRAW_MODULES_WALK,
    DRAWABLE_DRAW_MODULES_WALK_BYTES,
    MODEL_CONDITION_BUTTON_IMAGE,
    MODEL_CONDITION_FIELD_ROWS,
    MODEL_CONDITION_PORTRAIT_IMAGE,
    OBJECT_GET_DRAWABLE,
    OBJECT_GET_DRAWABLE_BYTES,
    OBJECT_IMAGE_UPGRADE_FIND_IMAGE,
    OBJECT_IMAGE_UPGRADE_THE_CONTROL_BAR,
    OBJECT_IMAGE_UPGRADE_THE_IMAGES,
    W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE,
    W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_HOOK,
    W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_HOOK_BYTES,
    W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_STORE,
    W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_STORE_BYTES,
    W3D_MODEL_DRAW_CUR_STATE,
    W3D_MODEL_DRAW_SET_MODEL_STATE,
    W3D_MODEL_DRAW_SET_MODEL_STATE_HOOK,
    W3D_MODEL_DRAW_SET_MODEL_STATE_HOOK_BYTES,
    W3D_MODEL_DRAW_SET_MODEL_STATE_SLOT,
    W3D_MODEL_DRAW_SET_MODEL_STATE_SLOTS,
    W3D_MODEL_DRAW_SET_MODEL_STATE_STORE,
    W3D_MODEL_DRAW_SET_MODEL_STATE_STORE_BYTES,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, jmp_rel32

__all__ = ["ANCHORS", "HOOKS", "ModelConditionImagesPatch", "SECTION_NAME", "build_code"]

SECTION_NAME = ".mcimg"

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

_CONTROL_BAR_DIRTY = 0x28

#: `{hook va: (stock bytes, cave label)}`. Each site is a whole number of instructions, one `jmp`
#: plus `nop` padding, and its stub replays what it displaced.
HOOKS = {
    CONTROL_BAR_SELECT_PORTRAIT: (CONTROL_BAR_SELECT_PORTRAIT_BYTES, "portrait_hook"),
    CONTROL_BAR_BUTTON_IMAGE_FALLBACK: (CONTROL_BAR_BUTTON_IMAGE_FALLBACK_BYTES, "button_hook"),
    W3D_MODEL_DRAW_SET_MODEL_STATE_HOOK: (W3D_MODEL_DRAW_SET_MODEL_STATE_HOOK_BYTES, "base_hook"),
    W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_HOOK: (
        W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_HOOK_BYTES,
        "horde_hook",
    ),
}

#: What the cave's reading depends on besides the hooked bytes, as `{va: bytes}`.
ANCHORS = {
    # The two field rows, whose offsets the cave reads the names at.
    **MODEL_CONDITION_FIELD_ROWS,
    # Both implementations store the new state at `m_curState`, and slot +0x100 names them.
    W3D_MODEL_DRAW_SET_MODEL_STATE_STORE: W3D_MODEL_DRAW_SET_MODEL_STATE_STORE_BYTES,
    W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_STORE: W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_STORE_BYTES,
    **{slot: struct.pack("<I", fn) for slot, fn in W3D_MODEL_DRAW_SET_MODEL_STATE_SLOTS.items()},
    # Object -> Drawable -> draw module array.
    OBJECT_GET_DRAWABLE: OBJECT_GET_DRAWABLE_BYTES,
    DRAWABLE_DRAW_MODULES_WALK: DRAWABLE_DRAW_MODULES_WALK_BYTES,
    # The image lookup the cave calls: `__thiscall` on TheMappedImageCollection, `ret 4`.
    OBJECT_IMAGE_UPGRADE_FIND_IMAGE: bytes.fromhex("558bec56ff75088bf1"),
}


def build_code(base_va: int) -> Asm:
    a = Asm(base_va)

    # Image *stateImage(Object *, field offset), cdecl. The first model draw whose current state
    # names a known image answers; NULL otherwise. Keeps ebx/esi/edi/ebp.
    a.label("state_image")
    a.emit(0x56)  # push esi
    a.emit(b"\x8b\x44\x24\x08")  # mov eax, [esp+8]          the Object
    a.emit(b"\x85\xc0")
    a.jcc(JE, "none")
    a.emit(b"\x8b\x80\x84\x00\x00\x00")  # mov eax, [eax+0x84]   the Drawable
    a.emit(b"\x85\xc0")
    a.jcc(JE, "none")
    a.emit(b"\x8b\xb0", struct.pack("<I", DRAWABLE_DRAW_MODULES))  # mov esi, [eax+0x14c]
    a.emit(b"\x85\xf6")
    a.jcc(JE, "none")
    a.label("walk")
    a.emit(b"\x8b\x0e")  # mov ecx, [esi]                 the module
    a.emit(b"\x85\xc9")
    a.jcc(JE, "none")
    a.emit(b"\x8b\x01")  # mov eax, [ecx]                 its vtable
    a.emit(b"\x8b\x80", struct.pack("<I", W3D_MODEL_DRAW_SET_MODEL_STATE_SLOT))
    a.emit(b"\x3d", struct.pack("<I", W3D_MODEL_DRAW_SET_MODEL_STATE))
    a.jcc(JE, "model")
    a.emit(b"\x3d", struct.pack("<I", W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE))
    a.jcc(JNE, "next")
    a.label("model")
    a.emit(b"\x8b\x49", W3D_MODEL_DRAW_CUR_STATE)  # mov ecx, [ecx+0x14]   m_curState
    a.emit(b"\x85\xc9")
    a.jcc(JE, "next")
    a.emit(b"\x03\x4c\x24\x0c")  # add ecx, [esp+0xc]        &state->name
    a.emit(b"\x8b\x01")  # mov eax, [ecx]                 the AsciiString's buffer
    a.emit(b"\x85\xc0")
    a.jcc(JE, "next")
    a.emit(b"\x66\x83\x78\x04\x00")  # cmp word [eax+4], 0     its length
    a.jcc(JE, "next")
    a.emit(b"\x8b\x15", struct.pack("<I", OBJECT_IMAGE_UPGRADE_THE_IMAGES))  # mov edx, [TheImages]
    a.emit(b"\x85\xd2")
    a.jcc(JE, "none")
    a.emit(0x51)  # push ecx
    a.emit(b"\x8b\xca")  # mov ecx, edx
    a.call_absolute(OBJECT_IMAGE_UPGRADE_FIND_IMAGE)
    a.emit(b"\x85\xc0")
    a.jcc(JNE, "found")
    a.label("next")
    a.emit(b"\x83\xc6\x04")  # add esi, 4
    a.jmp("walk")
    a.label("none")
    a.emit(b"\x33\xc0")
    a.label("found")
    a.emit(0x5E, 0xC3)  # pop esi / ret

    # void stateChanged(module, new state), cdecl, keeps every register. Marks the ControlBar dirty
    # when either name differs from the outgoing state's. A first state (old NULL) is a new
    # drawable, which nothing can have selected yet.
    a.label("state_changed")
    a.emit(0x50, 0x51, 0x52)  # push eax / ecx / edx
    a.emit(b"\x8b\x4c\x24\x10")  # mov ecx, [esp+0x10]       the module
    a.emit(b"\x8b\x54\x24\x14")  # mov edx, [esp+0x14]       the new state
    a.emit(b"\x8b\x49", W3D_MODEL_DRAW_CUR_STATE)  # mov ecx, [ecx+0x14]   the old state
    a.emit(b"\x85\xc9")
    a.jcc(JE, "unchanged")
    a.emit(b"\x3b\xca")  # cmp ecx, edx
    a.jcc(JE, "unchanged")
    for field in (MODEL_CONDITION_PORTRAIT_IMAGE, MODEL_CONDITION_BUTTON_IMAGE):
        a.emit(b"\x8b\x41", field)  # mov eax, [ecx+field]
        a.emit(b"\x3b\x42", field)  # cmp eax, [edx+field]
        a.jcc(JNE, "dirty")
    a.jmp("unchanged")
    a.label("dirty")
    a.emit(b"\xa1", struct.pack("<I", OBJECT_IMAGE_UPGRADE_THE_CONTROL_BAR))
    a.emit(b"\x85\xc0")
    a.jcc(JE, "unchanged")
    a.emit(b"\xc6\x40", _CONTROL_BAR_DIRTY, 0x01)  # mov byte [eax+0x28], 1
    a.label("unchanged")
    a.emit(0x5A, 0x59, 0x58, 0xC3)

    # Image *selectPortrait(ThingTemplate *, Object *), cdecl: the state's portrait, else stock.
    a.label("portrait_hook")
    a.emit(b"\x6a", MODEL_CONDITION_PORTRAIT_IMAGE)
    a.emit(b"\xff\x74\x24\x0c")  # push [esp+0xc]            the Object
    a.call("state_image")
    a.emit(b"\x83\xc4\x08")
    a.emit(b"\x85\xc0")
    a.jcc(JNE, "portrait_found")
    a.emit(CONTROL_BAR_SELECT_PORTRAIT_BYTES)  # mov ecx, [esp+4] / test ecx, ecx
    a.jmp_absolute(CONTROL_BAR_SELECT_PORTRAIT_RESUME)
    a.label("portrait_found")
    a.emit(0xC3)

    # The button resolver's template exit, with the same two arguments: the state's button image,
    # else stock's `mov ecx, [esp+4]; jmp ThingTemplate::getButtonImage`.
    a.label("button_hook")
    a.emit(b"\x6a", MODEL_CONDITION_BUTTON_IMAGE)
    a.emit(b"\xff\x74\x24\x0c")
    a.call("state_image")
    a.emit(b"\x83\xc4\x08")
    a.emit(b"\x85\xc0")
    a.jcc(JNE, "button_found")
    a.emit(CONTROL_BAR_BUTTON_IMAGE_FALLBACK_BYTES[:4])  # mov ecx, [esp+4]
    a.jmp_absolute(CONTROL_BAR_BUTTON_IMAGE_FALLBACK_RESUME)
    a.label("button_found")
    a.emit(0xC3)

    # The two setModelState sites: module in esi, new state in edi (base) or ebx (Horde).
    a.label("base_hook")
    a.emit(0x57, 0x56)  # push edi / push esi
    a.call("state_changed")
    a.emit(b"\x83\xc4\x08")
    a.emit(W3D_MODEL_DRAW_SET_MODEL_STATE_HOOK_BYTES)
    a.jmp_absolute(W3D_MODEL_DRAW_SET_MODEL_STATE_HOOK + 6)

    a.label("horde_hook")
    a.emit(0x53, 0x56)  # push ebx / push esi
    a.call("state_changed")
    a.emit(b"\x83\xc4\x08")
    a.emit(W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_HOOK_BYTES)
    a.jmp_absolute(W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_HOOK + 6)

    a.finish()
    return a


def _hook_bytes(va: int, stock: bytes, target: int) -> bytes:
    return jmp_rel32(va, target) + b"\x90" * (len(stock) - 5)


class ModelConditionImagesPatch(Patch):
    name = "model-condition-images"
    author = "officialNecro"
    description = (
        "Make ModelConditionState PortraitImageName and ButtonImageName work for every object, not "
        "only Create-a-Hero heroes: the selected portrait and the object's button image follow its "
        "current model state, falling back to the Object's SelectPortrait and ButtonImage when the "
        "state names none. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        base = allocate_section(
            data, SECTION_NAME, lambda va: build_code(va).finish(), _CHARACTERISTICS
        )
        code = build_code(base)
        for va, (stock, label) in HOOKS.items():
            apply_byte_patch(
                data,
                file_offset(data, va),
                stock,
                _hook_bytes(va, stock, code.label_va(label)),
                f"model-condition-images {label}",
            )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, (stock, _label) in HOOKS.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(stock)])
            if got != stock:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {stock.hex()} - the file already "
                    "carries this patch, another patch rewrote the site, or it is not the "
                    "expected build"
                )
        for va, expected in ANCHORS.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the model draw "
                    "or ModelConditionState layout is not this build's"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        base, section_off, vsize = located
        problems: list[str] = []
        code = build_code(base)
        body = code.finish()
        if vsize < len(body) or bytes(data[section_off : section_off + len(body)]) != body:
            problems.append(f"the routine in {SECTION_NAME} is not the one this patch builds")
        for va, (stock, label) in HOOKS.items():
            want = _hook_bytes(va, stock, code.label_va(label))
            off = file_offset(data, va)
            if bytes(data[off : off + len(want)]) != want:
                problems.append(f"hook at {va:#010x} does not jump into {SECTION_NAME}")
        return problems
