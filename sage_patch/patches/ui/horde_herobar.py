"""Display banner health or the members' combined current/max health on a horde's hero bar.

BannerCarrierDestroyHordeOnDeath selects the banner path. All other hordes use the members'
HP-weighted health, independently of KindOf flags. This changes display only.
See docs/horde-herobar.md for the native interfaces, ABI and fallback rules.
"""

from __future__ import annotations

import struct

from sage_patch.addresses import (
    CONTAIN_ITEM_LIST_WALK,
    CONTAIN_ITEM_LIST_WALK_ENTRY,
    HORDE_IFACE_BANNER_CARRIER_ID,
)
from sage_patch.asm import JBE, JE, JNE, Asm
from sage_patch.patcher import Patch
from sage_patch.utils import allocate_section, file_offset, find_section, jmp_rel32, read_bytes

__all__ = [
    "ANCHORS",
    "BANNER_DESTROYS_HORDE",
    "FIND_OBJECT_BY_ID",
    "HOOK",
    "MAX_MEMBERS",
    "ORIGINAL",
    "RESUME",
    "SECTION_NAME",
    "THE_GAME_LOGIC",
    "HordeHerobarPatch",
    "build_code",
]

HOOK = 0x0092D5EB
RESUME = 0x0092D5F0
ORIGINAL = bytes.fromhex("8b01ff5014")
SECTION_NAME = ".hrdhbar"
MAX_MEMBERS = 128
BANNER_DESTROYS_HORDE = 0x224  # HordeContain ModuleData
FIND_OBJECT_BY_ID = 0x00449681  # thiscall(GameLogic*, ObjectID), ret 4
THE_GAME_LOGIC = 0x00DE412C
_JS = 0x8

ANCHORS = {
    0x0087193C: bytes.fromhex("39866c0200000f858d000000"),
    0x00871950: bytes.fromhex("80bf2402000000745c"),
    0x00876427: bytes.fromhex("8d866c02000050578bcee85effffff"),
    FIND_OBJECT_BY_ID: bytes.fromhex(
        "837c24040074148d4424045081c1b4000000e8f7b7260085c0750433c0eb038b4008c20400"
    ),
    0x005F2D41: bytes.fromhex("d94108c3"),  # Body::getHealth
    0x006AA274: bytes.fromhex("d94110c3"),  # Body::getMaxHealth
    0x00C72100: bytes.fromhex("412d5f00"),  # ActiveBody interface slot +10
    0x00C7210C: bytes.fromhex("74a26a00"),  # ActiveBody interface slot +1C
    0x008C1D75: bytes.fromhex("f30f1041100f2f0594b5c1007607d94108d87110c3"),
    0x0092D5D7: bytes.fromhex("8b45e08b885c02000085c9c745bc010000007423"),
    RESUME: bytes.fromhex("d80dd888bd00d8059c86bd00e8a3f9100083f8647f0885c07d0733c0eb036a6458"),
    0x0092D611: bytes.fromhex("8945cc83f8018d45bc7c038d45cc"),
    CONTAIN_ITEM_LIST_WALK: CONTAIN_ITEM_LIST_WALK_ENTRY,
    0x00872A6F: bytes.fromhex("8d41e081c1fc000000f7"),  # contain -> horde adjustor
}


def _require_positive(a: Asm, slot: int, otherwise: str) -> None:
    """Compare a float local with zero without leaving a value on the x87 stack.

    JBE also rejects an unordered (NaN) maximum. Both temporaries are popped even when rejected.
    """
    a.emit(bytes.fromhex("d9eed94424"), slot)  # fldz; fld [esp+slot]
    a.emit(bytes.fromhex("dff1ddd8")).jcc(JBE, otherwise)  # fcomip st,st(1); fstp st(0)


def build_code(base_va: int) -> bytes:
    """Return one ratio in ST(0), preserving GPRs, flags and the original stack pointer.

    Four stack locals hold total current HP, total maximum HP, an iteration budget and one
    member's maximum. Each native getter's x87 result is stored before calling another getter.
    """
    a = Asm(base_va)
    a.emit(bytes.fromhex("9c6083ec1033c089042489442404c7442408"))
    a.emit(struct.pack("<I", MAX_MEMBERS))
    a.emit(bytes.fromhex("8b75e085f6")).jcc(JE, "original")  # displayed Object
    a.emit(bytes.fromhex("8bbe5802000085ff")).jcc(JE, "original")  # contain interface
    a.emit(bytes.fromhex("8bcf8b01ff507c85c0")).jcc(JE, "original")  # native horde interface
    a.emit(bytes.fromhex("8bd88b47e485c0")).jcc(JE, "original")  # EBX=horde, EAX=ModuleData
    a.emit(bytes.fromhex("80b8"), struct.pack("<I", BANNER_DESTROYS_HORDE), 0)
    a.jcc(JNE, "banner_health")

    a.emit(bytes.fromhex("8b7f3485ff")).jcc(JE, "original")  # list sentinel
    a.emit(bytes.fromhex("8b1f"))
    a.label("member_loop")
    a.emit(bytes.fromhex("3bdf")).jcc(JE, "calculate")
    a.emit(bytes.fromhex("85db")).jcc(JE, "original")
    a.emit(bytes.fromhex("ff4c2408")).jcc(_JS, "original")
    a.emit(bytes.fromhex("8b730885f6")).jcc(JE, "next_member")
    a.emit(bytes.fromhex("8bb65c02000085f6")).jcc(JE, "next_member")  # ESI=member body
    a.emit(bytes.fromhex("8bce8b01ff501cd95c240c"))  # getMaxHealth; fstp [esp+C]
    _require_positive(a, 0x0C, "next_member")
    a.emit(bytes.fromhex("8bce8b01ff5010d80424d91c24"))  # getHealth; add to current sum
    a.emit(bytes.fromhex("d944240cd8442404d95c2404"))  # add this maximum to maximum sum
    a.label("next_member")
    a.emit(bytes.fromhex("8b1b")).jmp("member_loop")

    a.label("calculate")
    _require_positive(a, 0x04, "zero")
    a.emit(bytes.fromhex("d90424d8742404")).jmp("return_ratio")  # current / maximum
    a.label("zero")
    a.emit(bytes.fromhex("d9ee"))  # an empty/zero-capacity list has zero health
    a.label("return_ratio")
    a.emit(bytes.fromhex("83c410619d")).jmp_absolute(RESUME)

    a.label("banner_health")
    a.emit(bytes.fromhex("8b83"), struct.pack("<I", HORDE_IFACE_BANNER_CARRIER_ID))
    a.emit(bytes.fromhex("85c0")).jcc(JE, "original")
    a.emit(bytes.fromhex("8b0d"), struct.pack("<I", THE_GAME_LOGIC))
    a.emit(bytes.fromhex("85c9")).jcc(JE, "original")
    a.emit(0x50).call_absolute(FIND_OBJECT_BY_ID)
    a.emit(bytes.fromhex("85c0")).jcc(JE, "original")
    a.emit(bytes.fromhex("3bc6")).jcc(JE, "original")  # reject a container self-reference
    a.emit(bytes.fromhex("8b885c02000085c9")).jcc(JE, "original")
    a.emit(ORIGINAL).jmp("return_ratio")
    a.label("original")
    a.emit(bytes.fromhex("83c410619d"))  # restore original ECX before the stock call
    a.emit(ORIGINAL).jmp_absolute(RESUME)
    return a.finish()


class HordeHerobarPatch(Patch):
    name = "horde-herobar"
    author = "Ostkannit"
    runtime_verified = "partly"
    description = (
        "Show the registered banner's health when BannerCarrierDestroyHordeOnDeath is Yes; "
        "otherwise show total member current HP / total member maximum HP. "
        "Independent of KindOf flags; display only"
    )

    @staticmethod
    def _anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            if read_bytes(data, va, len(expected)) != expected:
                raise ValueError(f"horde-herobar: signature mismatch at {va:#010x}")

    def apply(self, data: bytearray) -> None:
        self._anchors(data)
        if find_section(data, SECTION_NAME) is not None:
            if problems := self.verify(data):
                raise ValueError("; ".join(problems))
            return
        if read_bytes(data, HOOK, len(ORIGINAL)) != ORIGINAL:
            raise ValueError("horde-herobar: unexpected hook bytes")
        staged = bytearray(data)
        cave = allocate_section(staged, SECTION_NAME, build_code, 0x60000020)
        off = file_offset(staged, HOOK)
        staged[off : off + len(ORIGINAL)] = jmp_rel32(HOOK, cave)
        if problems := self.verify(staged):
            raise ValueError("; ".join(problems))
        data[:] = staged

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            self._anchors(data)
            section = find_section(data, SECTION_NAME)
            if section is None:
                return [f"{SECTION_NAME} section missing"]
            va, off, size = section
            code = build_code(va)
            if size != len(code) or data[off : off + len(code)] != code:
                return ["horde-herobar: cave mismatch"]
            if read_bytes(data, HOOK, len(ORIGINAL)) != jmp_rel32(HOOK, va):
                return ["horde-herobar: hook mismatch"]
        except (ValueError, IndexError, TypeError, struct.error) as exc:
            return [str(exc)]
        return []
