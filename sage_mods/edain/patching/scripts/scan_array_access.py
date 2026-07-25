import pe, sys
from capstone import x86, Cs, CS_ARCH_X86, CS_MODE_32
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

md = Cs(CS_ARCH_X86, CS_MODE_32); md.detail = True
name, va0, va1, fo, fs = next(s for s in pe.SECTIONS if s[0]==".text")
code = pe.DATA[fo:fo+fs]

# Superset disassembly: decode ONE instruction at every byte offset, keep those whose
# memory operand is [base + index*4 + disp] with disp in the m_command window (0x14)
# OR touches the trailing count/flag fields (0x94..0x9c). scale==4 required for the array.
arr_hits = {}   # va -> (mnemonic, op_str)
for i in range(len(code)):
    for ins in md.disasm(code[i:i+15], va0+i):
        for op in ins.operands:
            if op.type == x86.X86_OP_MEM:
                m = op.mem
                if m.index != 0 and m.scale == 4 and m.disp == 0x14 and m.base != 0:
                    arr_hits[ins.address] = (ins.mnemonic, ins.op_str)
        break  # only the instruction decoded at offset i

print(f"m_command[i] access candidates ([base + idx*4 + 0x14]): {len(arr_hits)}")
for va in sorted(arr_hits):
    mn, ops = arr_hits[va]
    print(f"  {va:08x}: {mn} {ops}")
