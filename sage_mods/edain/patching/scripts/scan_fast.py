import pe, sys
from capstone import x86
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

name, va0, va1, fo, fs = next(s for s in pe.SECTIONS if s[0]==".text")
data = pe.DATA

def scan(disp, label):
    hits = {}
    # ModRM with mod=01, rm=100 (SIB follows): (b & 0xC7)==0x44
    # SIB with scale=2 (*4): (b & 0xC0)==0x80
    # then disp8 == disp
    for i in range(fo, fo+fs-4):
        if (data[i] & 0xC7) == 0x44 and (data[i+1] & 0xC0) == 0x80 and data[i+2] == disp:
            # opcode is at i-1 (1-byte opcodes) or i-2 (0F xx). Try both.
            for back in (1, 2):
                op = i - back
                for ins in pe.md.disasm(data[op:op+15], pe.off_to_va(op)):
                    ok = False
                    for o in ins.operands:
                        if o.type == x86.X86_OP_MEM and o.mem.scale == 4 and o.mem.disp == disp and o.mem.index != 0 and o.mem.base != 0:
                            ok = True
                    if ok and ins.size >= back + 3:
                        hits[ins.address] = (ins.mnemonic, ins.op_str)
                    break
    print(f"\n=== [{label}] [base + idx*4 + 0x{disp:x}] accesses: {len(hits)} ===")
    for va in sorted(hits):
        mn, ops = hits[va]
        print(f"  {va:08x}: {mn} {ops}")
    return hits

scan(0x14, "m_command[i]")
