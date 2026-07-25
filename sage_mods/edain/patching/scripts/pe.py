"""Shared PE helpers for game.dat analysis."""
import pefile, struct
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

PATH = r"C:\Program Files (x86)\Games\bfme\rotwk\game.dat"
_pe = pefile.PE(PATH, fast_load=True)
IMAGE_BASE = _pe.OPTIONAL_HEADER.ImageBase
DATA = open(PATH, "rb").read()

# section table: (name, va_start, va_end, file_off, file_size)
SECTIONS = []
for s in _pe.sections:
    name = s.Name.rstrip(b"\x00").decode("latin1")
    SECTIONS.append((name, IMAGE_BASE + s.VirtualAddress,
                     IMAGE_BASE + s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData),
                     s.PointerToRawData, s.SizeOfRawData))

def off_to_va(off):
    for name, va0, va1, fo, fs in SECTIONS:
        if fo <= off < fo + fs:
            return va0 + (off - fo)
    return None

def va_to_off(va):
    for name, va0, va1, fo, fs in SECTIONS:
        if va0 <= va < va0 + fs:
            return fo + (va - va0)
    return None

def read_va(va, n):
    off = va_to_off(va)
    return DATA[off:off+n] if off is not None else None

def find_imm_refs(target_va):
    """Return file offsets where the 4-byte LE value == target_va appears."""
    needle = struct.pack("<I", target_va)
    out, i = [], 0
    while True:
        i = DATA.find(needle, i)
        if i < 0: break
        out.append(i); i += 1
    return out

md = Cs(CS_ARCH_X86, CS_MODE_32)
md.detail = True

def disasm(va, nbytes=64):
    off = va_to_off(va)
    code = DATA[off:off+nbytes]
    return list(md.disasm(code, va))

def print_disasm(va, nbytes=64):
    for ins in disasm(va, nbytes):
        print(f"  {ins.address:08x}: {ins.mnemonic:<7} {ins.op_str}")

if __name__ == "__main__":
    print(f"ImageBase = 0x{IMAGE_BASE:08x}")
    for s in SECTIONS:
        print(f"  {s[0]:<8} VA {s[1]:08x}-{s[2]:08x}  file {s[3]:08x}+{s[4]:x}")
