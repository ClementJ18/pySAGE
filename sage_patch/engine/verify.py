#!/usr/bin/env python3
"""Static verification of the patched binary (N=64). Target via env TARGET (default game.dat)."""

import os
import struct
import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
IB = 0x400000
d = open(os.path.join(os.path.dirname(__file__), os.environ.get("TARGET", "game.dat")), "rb").read()

# build section map (rva,vsize,pr,rs,name)
e = struct.unpack_from("<I", d, 0x3C)[0]
nsec = struct.unpack_from("<H", d, e + 6)[0]
szopt = struct.unpack_from("<H", d, e + 20)[0]
sectab = e + 24 + szopt
secs = []
for i in range(nsec):
    o = sectab + i * 40
    name = d[o : o + 8].rstrip(b"\x00").decode("latin1")
    vs, va, rs, pr = struct.unpack_from("<IIII", d, o + 8)
    secs.append((name, va, vs, pr, rs))


def va_off(va):
    rva = va - IB
    for _name, sva, vs, pr, rs in secs:
        if sva <= rva < sva + max(vs, rs):
            return pr + (rva - sva)
    return None


def cstr(va):
    o = va_off(va)
    if o is None:
        return None
    end = d.find(b"\x00", o)
    return d[o:end].decode("latin1") if 0 < end - o < 40 else None


md = Cs(CS_ARCH_X86, CS_MODE_32)


def dis1(va):
    o = va_off(va)
    ins = next(md.disasm(d[o : o + 8], va))
    return f"{ins.mnemonic} {ins.op_str}"


print("=== sections ===")
for s in secs:
    print(f"  {s[0]:<9} VA={IB + s[1]:08x} VS={s[2]:06x} PR={s[3]:06x}")

print("\n=== patched instruction sites ===")
for va, lbl in [
    (0x720298, "alloc size"),
    (0x80C97E, "ctor count push"),
    (0x80C987, "ctor count store"),
    (0x80C980, "ctor flag store"),
    (0x80C8FC, "set bound"),
    (0x80C909, "set &count"),
    (0x80C8EF, "set flag guard"),
    (0x80C8C6, "slot-scan bound"),
    (0x80C8E3, "clear stosd"),
    (0x80C91D, "reset stosd"),
    (0x943DF9, "consumer count read"),
    (0x7950E2, "AI scan bound"),
    (0x72065C, "parser table ptr"),
    (0x71C2EE, "getFieldParse ptr"),
]:
    print(f"  {va:08x} {lbl:<20} {dis1(va)}")

# resolve the new table
tab_va = 0xED3000
print(f"\n=== new table @0x{tab_va:08x} ===")
o = va_off(tab_va)
ok = True
for i in range(66):
    name_p, fn, ud, off = struct.unpack_from("<IIII", d, o + i * 16)
    nm = cstr(name_p) if name_p else None
    if i < 3 or i in (32, 33, 34, 63, 64, 65):
        print(f"  [{i:2}] name={nm!r:>7} fn=0x{fn:08x} ud={ud:2} off=0x{off:x}")
    # checks
    if i < 64:
        if nm != str(i + 1) or fn != 0x0080C9E1 or ud != i or off != 0x14:
            ok = False
            print(f"   !! slot {i} bad")
    elif i == 64:
        if nm != "InitialVisible" or off != 0x114:
            ok = False
            print("   !! InitialVisible bad")
    elif i == 65:
        if (name_p, fn, ud, off) != (0, 0, 0, 0):
            ok = False
            print("   !! terminator bad")
print("TABLE OK" if ok else "TABLE FAILED")

# check the two refs point at the table
r1 = struct.unpack_from("<I", d, va_off(0x72065C) + 1)[0]
r2 = struct.unpack_from("<I", d, va_off(0x71C2EE) + 1)[0]
print(f"parser ref -> 0x{r1:08x} ; getFieldParse ref -> 0x{r2:08x} ; match={r1 == tab_va == r2}")
