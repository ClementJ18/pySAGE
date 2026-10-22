"""Show the sum of member health ratios divided by Slots on a horde's hero-bar entry.

Port of the user's verified Cheat Engine prototype. No object health is written.
Derivation and limits: docs/horde-herobar.md (German).
"""

from __future__ import annotations

import struct

from sage_patch.addresses import (
    CONTAIN_ITEM_LIST_WALK,
    CONTAIN_ITEM_LIST_WALK_ENTRY,
    HORDE_IFACE_BANNER_CARRIER_ID,
)
from sage_patch.asm import JE, JG, JL, JNE, Asm
from sage_patch.patcher import Patch
from sage_patch.utils import allocate_section, file_offset, find_section, jmp_rel32, read_bytes

HOOK = 0x0092D5EB
RESUME = 0x0092D5F0
ORIGINAL = bytes.fromhex("8b01ff5014")
SECTION_NAME = ".hrdhbar"
MAX_SLOTS = 128  # Decimal: CE's unprefixed `128` can otherwise mean hexadecimal 0x128.
MELEE_HORDE_INDEX = 119
MELEE_HORDE_BYTE = 0x116
MELEE_HORDE_MASK = 0x80
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
    0x008C1D75: bytes.fromhex("f30f1041100f2f0594b5c1007607d94108d87110c3"),
    0x00DA1044: bytes.fromhex("2860c100"),  # stock KindOf table[119] -> MELEE_HORDE
    0x00C16028: b"MELEE_HORDE\0",
    0x0092D5D7: bytes.fromhex("8b45e08b885c02000085c9c745bc010000007423"),
    RESUME: bytes.fromhex("d80dd888bd00d8059c86bd00e8a3f9100083f8647f0885c07d0733c0eb036a6458"),
    0x0092D611: bytes.fromhex("8945cc83f8018d45bc7c038d45cc"),
    CONTAIN_ITEM_LIST_WALK: CONTAIN_ITEM_LIST_WALK_ENTRY,
    0x0086C8AC: bytes.fromhex("8b81e8feffff8b8098000000c3"),  # Horde-interface Slots getter
    0x00872A6F: bytes.fromhex("8d41e081c1fc000000f7"),  # contain -> horde adjustor
    0x00855D25: bytes.fromhex("8b4604f6801501000020"),  # HORDE bit
}


def build_code(base_va: int) -> bytes:
    """Match CE's stack/x87 ABI: success adds one ST(0), fallback replays the original call.

    12 stack-local bytes hold float sum, integer Slots and the loop budget.
    No FXSAVE/FXRSTOR: the new ST(0) is intentionally returned to the original percentage code.
    """
    a = Asm(base_va)
    a.emit(bytes.fromhex("9c6083ec0cc7042400000000c7442408"))
    a.emit(struct.pack("<I", MAX_MEMBERS))
    a.emit(bytes.fromhex("8b75e085f6")).jcc(JE, "original")  # displayed Object
    a.emit(bytes.fromhex("8b460485c0")).jcc(JE, "original")  # ThingTemplate
    a.emit(bytes.fromhex("f7801401000000200000")).jcc(JE, "original")  # HORDE
    # MELEE_HORDE never enters the member aggregation; a mortal banner may supply its health.
    a.emit(bytes.fromhex("f680"), struct.pack("<I", MELEE_HORDE_BYTE), MELEE_HORDE_MASK)
    a.jcc(JNE, "banner_health")
    a.emit(bytes.fromhex("8bbe58020000"))  # mov edi,[esi+258]
    a.emit(bytes.fromhex("85ff")).jcc(JE, "original")
    a.emit(bytes.fromhex("8bcf8b01ff507c85c0")).jcc(JE, "original")
    # EDI remains the contain interface at Runtime+20; the returned horde iface is only a gate.
    a.emit(bytes.fromhex("8b47e485c0")).jcc(JE, "original")  # [contain-1c] ModuleData
    a.emit(bytes.fromhex("8b809800000083f801")).jcc(JL, "original")
    a.emit(0x3D, struct.pack("<I", MAX_SLOTS)).jcc(JG, "original")
    a.emit(bytes.fromhex("894424048b7f3485ff")).jcc(JE, "original")
    a.emit(bytes.fromhex("8b1f"))  # first list node
    a.label("member_loop")
    a.emit(bytes.fromhex("3bdf")).jcc(JE, "calculate")
    a.emit(bytes.fromhex("85db")).jcc(JE, "original")
    a.emit(bytes.fromhex("ff4c2408")).jcc(_JS, "original")
    a.emit(bytes.fromhex("8b730885f6")).jcc(JE, "next_member")
    a.emit(bytes.fromhex("8b8e5c02000085c9")).jcc(JE, "next_member")
    a.emit(ORIGINAL)  # Body::getHealthRatio(), __thiscall, no arguments, result ST(0)
    a.emit(bytes.fromhex("d80424d91c24"))  # fadd [esp]; fstp [esp]
    a.label("next_member")
    a.emit(bytes.fromhex("8b1b")).jmp("member_loop")
    a.label("calculate")
    a.emit(bytes.fromhex("d90424db442404def9"))  # fld sum; fild Slots; fdivp st(1),st(0)
    a.label("return_ratio")
    a.emit(bytes.fromhex("83c40c619d")).jmp_absolute(RESUME)

    a.label("banner_health")
    a.emit(bytes.fromhex("8bbe5802000085ff")).jcc(JE, "original")  # contain interface
    a.emit(bytes.fromhex("8b47e485c0")).jcc(JE, "original")  # ModuleData
    a.emit(bytes.fromhex("80b8"), struct.pack("<I", BANNER_DESTROYS_HORDE), 0)
    a.jcc(JE, "original")  # ordinary MELEE_HORDE retains its container getter
    a.emit(bytes.fromhex("8bcf8b01ff507c85c0")).jcc(JE, "original")  # horde interface
    a.emit(bytes.fromhex("8b80"), struct.pack("<I", HORDE_IFACE_BANNER_CARRIER_ID))
    a.emit(bytes.fromhex("85c0")).jcc(JE, "original")
    a.emit(bytes.fromhex("8b0d"), struct.pack("<I", THE_GAME_LOGIC))
    a.emit(bytes.fromhex("85c9")).jcc(JE, "original")
    a.emit(0x50).call_absolute(FIND_OBJECT_BY_ID)  # GameLogic consumes the pushed ObjectID
    a.emit(bytes.fromhex("85c0")).jcc(JE, "original")
    a.emit(bytes.fromhex("3bc6")).jcc(JE, "original")  # never use the container as its own banner
    a.emit(bytes.fromhex("8b885c02000085c9")).jcc(JE, "original")
    a.emit(ORIGINAL).jmp("return_ratio")  # exactly one banner ratio in ST(0)
    a.label("original")
    a.emit(bytes.fromhex("83c40c619d"))  # restore ORIGINAL ECX and stack before original call
    a.emit(ORIGINAL).jmp_absolute(RESUME)
    return a.finish()


class HordeHerobarPatch(Patch):
    name = "horde-herobar"
    author = "Ostkannit"
    runtime_verified = "partly"
    description = (
        "Show a horde's member health ratios divided by HordeContain Slots on its hero-bar entry; "
        "MELEE_HORDE with BannerCarrierDestroyHordeOnDeath uses its banner health, "
        "otherwise stock. "
        "Display only; no HP or selection changes"
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
