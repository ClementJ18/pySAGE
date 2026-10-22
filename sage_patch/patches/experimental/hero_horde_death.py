"""Register an empty immortal hero horde with native DeathPreparation before stock destruction.

Experimental first version. See docs/hero-horde-death.md (German); no runtime validation.
The separate combo-horde-recruitment patch supplies mixed InitialPayload creation.
"""

from __future__ import annotations

from sage_patch.asm import JE, JNE, Asm
from sage_patch.patcher import Patch
from sage_patch.utils import allocate_section, file_offset, find_section, jmp_rel32, read_bytes

HOOK = 0x0087386C
RESUME = 0x00873872
ORIGINAL = bytes.fromhex("ffb6ecfeffff")
SECTION_NAME = ".hhrdead"
DEATH_PREPARATION = 0x008B3744
FIND_MODULE = 0x0068BDA5
RULE_LOOKUP = 0x00603AF6
NAME_KEY = 0x005487EC
RESPAWN_NAME = 0x00C0B098
NAME_GENERATOR = 0x00DD90E4
RESPAWN_VTABLE = 0x00C6C360
IMMORTAL_BODY_VTABLE = 0x00C71FE0

# Frozen evidence from game.dat.backup, not signatures harvested from the input being patched.
ANCHORS = {
    0x0087370B: bytes.fromhex("b892f7b900e8db971c0083ec548365f00056578b7d0885ff8bf1"),
    0x00873821: bytes.fromhex("8d9ee4feffff8b038bcbff909400000084c075ec"),
    0x00873835: bytes.fromhex(
        "8d45ec508bcbe8581dffff8b40048b0039007534837e5800752e"
        "8b86e8feffff6a008d4f3851ffb0500200008b0d7036de00e882a1d6ff"
    ),
    RESUME: bytes.fromhex("8b0d2c41de00e82e83dbff"),
    0x00C5B22C: bytes.fromhex("0b378700"),
    0x00C5BECC: bytes.fromhex("0b378700"),
    0x00C5CFDC: bytes.fromhex("0b378700"),
    FIND_MODULE: bytes.fromhex("568bb14c0200005733ffeb0e8b01ff50103b44240c"),
    NAME_KEY: bytes.fromhex("b847a8b700e8fa464f00"),
    RESPAWN_NAME: b"RespawnUpdate\0",
    0x008B3286: bytes.fromhex("c70660c3c600c7460c0073c600c7461054c3c600"),
    DEATH_PREPARATION: bytes.fromhex(
        "558bec83ec1c53568bf18b4e2c85c98b46048b5e088945fc740983f9040f85370100008b8b6c0200008b4924"
    ),
    0x008B3783: bytes.fromhex("8d880c010000578d45e450"),
    0x008B3797: bytes.fromhex("e85a03d5ff8b4dfc81c10c0100008bf88b013bf8"),
    0x008B37D4: bytes.fromhex("e81d03d5ff8bf83b7df8751268ffffff3f538bcee845d4f9ff"),
    0x008B381E: bytes.fromhex("53e8bee4deff6a048bcbe805ecddff6a018bcbe81aa1ddff"),
    0x008B3841: bytes.fromhex("807f20008bcb0f94c0884640"),
    0x008B3875: bytes.fromhex("8bcf5053e814dfecff"),
    0x008B389D: bytes.fromhex("5f5e5bc9c3"),
    0x0068D963: bytes.fromhex("8d8e580400008a010f84aa000000a8010f85de0000000c01"),
    # HERO test outside the HeroBar classifier rewritten by HeroBarPatch at 0x0092CD7F.
    0x0044A573: bytes.fromhex("f68013010000047405ff45c0eb03"),
    0x00855D25: bytes.fromhex("8b4604f6801501000020"),  # HORDE: template+115, bit 20
    RULE_LOOKUP: bytes.fromhex(
        "8b118b4a0485c9578b7c24088bc27417568b3739711072078bc18b4908eb03"
        "8b490c85c975ed5e3bc274078b0f3b481073028bc25fc20400"
    ),
    0x008C4A1A: bytes.fromhex("c7069020c700c7460c082fc700c74610e01fc700"),
    0x00C72038: bytes.fromhex("de478c00"),
    0x00C72064: bytes.fromhex("b44a8c00"),
}


def build_code(base_va: int) -> bytes:
    """Preserve flags, GPRs and aligned FXSAVE state; replay PUSH and rejoin stock destroy.

    ESI at entry is the contain interface. EBP is temporary only inside PUSHAD/POPAD.
    All native callees are thiscall and clean their explicit arguments.
    """
    a = Asm(base_va)
    a.emit(bytes.fromhex("9c608bec81ec1002000083e4f00fae0424"))
    # pushfd; pushad; mov ebp,esp; sub esp,210h; and esp,-16; fxsave [esp]
    a.emit(bytes.fromhex("8bb6ecfeffff85f6")).jcc(JE, "done")  # horde owner
    a.emit(bytes.fromhex("8b460485c0")).jcc(JE, "done")  # template
    a.emit(bytes.fromhex("f6801301000004")).jcc(JE, "done")  # HERO
    a.emit(bytes.fromhex("f6801501000020")).jcc(JE, "done")  # HORDE
    a.emit(bytes.fromhex("f6865804000001")).jcc(JNE, "done")  # effectively dead already
    a.emit(bytes.fromhex("8b865c02000085c0")).jcc(JE, "done")
    a.emit(bytes.fromhex("8138"), IMMORTAL_BODY_VTABLE.to_bytes(4, "little"))
    a.jcc(JNE, "done")
    a.emit(bytes.fromhex("83be6c02000000")).jcc(JE, "done")  # XP tracker
    a.emit(bytes.fromhex("8b0d"), NAME_GENERATOR.to_bytes(4, "little"))
    a.emit(bytes.fromhex("85c9")).jcc(JE, "done")
    a.emit(0x68, RESPAWN_NAME.to_bytes(4, "little")).call_absolute(NAME_KEY)
    a.emit(bytes.fromhex("508bce")).call_absolute(FIND_MODULE)
    a.emit(bytes.fromhex("85c0")).jcc(JE, "done")
    a.emit(bytes.fromhex("8138"), RESPAWN_VTABLE.to_bytes(4, "little")).jcc(JNE, "done")
    a.emit(bytes.fromhex("397008")).jcc(JNE, "done")  # module owner == horde
    a.emit(bytes.fromhex("8bf88b402c85c0")).jcc(JE, "state_ok")
    a.emit(bytes.fromhex("83f804")).jcc(JNE, "done")
    a.label("state_ok")
    a.emit(bytes.fromhex("8b5f0485db")).jcc(JE, "done")  # module data
    a.emit(bytes.fromhex("83bb0c01000000")).jcc(JE, "done")  # valid tree head
    a.emit(bytes.fromhex("8b866c020000ff7024"))  # rank temporary
    a.emit(bytes.fromhex("8bd4528d8b0c010000")).call_absolute(RULE_LOOKUP)
    a.emit(0x5A)  # pop rank temporary (callee cleaned pointer)
    a.emit(bytes.fromhex("3b830c010000")).jcc(JNE, "rule_found")
    a.emit(bytes.fromhex("6a018bd4528d8b0c010000")).call_absolute(RULE_LOOKUP)
    a.emit(0x5A)
    a.emit(bytes.fromhex("3b830c010000")).jcc(JE, "done")
    a.label("rule_found")
    a.emit(bytes.fromhex("80782000")).jcc(JNE, "done")  # AutoSpawn requires surviving object
    a.emit(bytes.fromhex("8bcf")).call_absolute(DEATH_PREPARATION)
    a.label("done")
    a.emit(bytes.fromhex("0fae0c248be5619d"))  # fxrstor [esp]; mov esp,ebp; popad; popfd
    a.emit(ORIGINAL).jmp_absolute(RESUME)
    return a.finish()


class HeroHordeDeathPatch(Patch):
    name = "hero-horde-death"
    author = "Ostkannit"
    experimental = True
    description = (
        "Register empty HERO/HORDE objects with ImmortalBody and a non-auto RespawnUpdate rule "
        "through native DeathPreparation before the unchanged destroy request"
    )

    @staticmethod
    def _anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            if read_bytes(data, va, len(expected)) != expected:
                raise ValueError(f"hero-horde-death: signature mismatch at {va:#010x}")

    def apply(self, data: bytearray) -> None:
        self._anchors(data)
        if find_section(data, SECTION_NAME) is not None:
            problems = self.verify(data)
            if problems:
                raise ValueError("; ".join(problems))
            return  # exact repeat is a no-op; damaged/foreign caves are never accepted
        if read_bytes(data, HOOK, 6) != ORIGINAL:
            raise ValueError("hero-horde-death: unexpected hook bytes")
        # Work on a copy so allocation failures leave even the in-memory input untouched.
        staged = bytearray(data)
        cave = allocate_section(staged, SECTION_NAME, build_code, 0x60000020)
        off = file_offset(staged, HOOK)
        staged[off : off + 6] = jmp_rel32(HOOK, cave, 6)
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
                return ["hero-horde-death: cave mismatch"]
            if read_bytes(data, HOOK, 6) != jmp_rel32(HOOK, va, 6):
                return ["hero-horde-death: hook mismatch"]
        except (ValueError, IndexError, TypeError) as exc:
            return [str(exc)]
        return []
