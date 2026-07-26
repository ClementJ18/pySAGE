import pe, struct, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
name, va0, va1, fo, fs = next(s for s in pe.SECTIONS if s[0]==".text")
data = pe.DATA

def direct_callers(target):
    out=[]
    for i in range(fo, fo+fs-5):
        if data[i]==0xE8:
            rel=struct.unpack("<i", data[i+1:i+5])[0]
            va=pe.off_to_va(i)
            if va+5+rel == target:
                out.append(va)
    return out

for nm,addr in [("getCommandButton",0x0080c846),("setCommandButton",0x0080c8ef),
                ("clearButtons",0x0080c8e2),("resetCount",0x0080c91b)]:
    c=direct_callers(addr)
    print(f"\n=== direct callers of {nm} @0x{addr:08x}: {len(c)} ===")
    for v in c: print(f"  {v:08x}")

# every 0x21 immediate (push 6A21 / cmp 83..21 / mov B?..21) inside the CommandSet compiland
print("\n=== 0x21 (33) immediates in CommandSet compiland 0x80c840..0x80caa0 ===")
lo,hi=0x0080c840,0x0080caa0
o0=pe.va_to_off(lo)
from capstone import x86
seen=set()
for i in range(o0, pe.va_to_off(hi)):
    for ins in pe.md.disasm(data[i:i+15], pe.off_to_va(i)):
        for op in ins.operands:
            if op.type==x86.X86_OP_IMM and op.imm==0x21:
                if ins.address not in seen and lo<=ins.address<hi:
                    seen.add(ins.address)
                    print(f"  {ins.address:08x}: {ins.mnemonic} {ins.op_str}")
        break
