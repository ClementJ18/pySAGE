import pe, struct, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
name, va0, va1, fo, fs = next(s for s in pe.SECTIONS if s[0]==".text")
data = pe.DATA

# Reliable byte patterns for the constant 33 used as bound/count:
#  6A 21                 push 0x21
#  83 /7(cmp) modrm F8..FF, imm 21   -> cmp r32, 0x21   (modrm 0xF8..0xFF)
#  3D 21 00 00 00        cmp eax, 0x21 (imm32)
#  B8..BF 21 00 00 00    mov r32, 0x21
#  BA 21 00 00 00 etc handled by mov set
def disasm1(off):
    for ins in pe.md.disasm(data[off:off+15], pe.off_to_va(off)):
        return ins
    return None

hits=[]
for i in range(fo, fo+fs-5):
    b=data[i]
    cand=False
    if b==0x6A and data[i+1]==0x21: cand=True                        # push 0x21
    elif b==0x83 and 0xF8<=data[i+1]<=0xFF and data[i+2]==0x21: cand=True  # cmp r32,imm8
    elif b==0x3D and data[i+1]==0x21 and data[i+2]==0 and data[i+3]==0 and data[i+4]==0: cand=True # cmp eax,imm32
    elif 0xB8<=b<=0xBF and data[i+1]==0x21 and data[i+2]==0 and data[i+3]==0 and data[i+4]==0: cand=True # mov r32,imm32
    if cand:
        ins=disasm1(i)
        if ins and (ins.mnemonic in ('push','cmp','mov')) and '0x21' in ins.op_str:
            hits.append((ins.address, ins.mnemonic, ins.op_str))

# de-dup overlapping
seen=set(); uniq=[]
for a,m,o in hits:
    if a in seen: continue
    seen.add(a); uniq.append((a,m,o))

print(f"total push/cmp/mov 0x21 sites in .text: {len(uniq)}")
CS_LO,CS_HI=0x0080c840,0x0080caa0
for a,m,o in uniq:
    tag=" <-- CommandSet compiland" if CS_LO<=a<CS_HI else (" <-- parser/store" if 0x720000<=a<0x722000 else "")
    print(f"  {a:08x}: {m} {o}{tag}")
