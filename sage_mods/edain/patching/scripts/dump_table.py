import pe, struct, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def cstr(va, maxlen=48):
    o = pe.va_to_off(va)
    if o is None: return None
    end = pe.DATA.find(b"\x00", o)
    if end < 0 or end-o > maxlen: return None
    return pe.DATA[o:end].decode("latin1")

TAB = 0x00c4f3d8
print("=== CommandSet field-parse table @ 0x%08x ===" % TAB)
print("entry = { char* name, void* parseFn, void* userData, uint offset }\n")
o = pe.va_to_off(TAB)
for i in range(36):
    ent = pe.DATA[o+i*16 : o+i*16+16]
    if len(ent) < 16: break
    name_p, fn, ud, offs = struct.unpack("<IIII", ent)
    nm = cstr(name_p)
    print(f"[{i:2}] name={nm!r:>6}  fn=0x{fn:08x}  userData=0x{ud:08x}  offset=0x{offs:x}({offs})")
    if name_p == 0:  # terminator
        print("   (terminator)")
        break

# who references this table address? -> the getFieldParse/parse function
print("\n=== refs to table VA 0x%08x ===" % TAB)
for r in pe.find_imm_refs(TAB):
    va = pe.off_to_va(r)
    sec = next((n for n,a,b,fo,fs in pe.SECTIONS if a<=va<b), "?")
    print(f"  ref @ 0x{va:08x} ({sec})")
    if sec == ".text":
        pe.print_disasm(va-24, 60)
