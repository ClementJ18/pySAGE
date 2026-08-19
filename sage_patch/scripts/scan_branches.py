"""Over-approximate every direct branch in .text: decode a branch at EVERY byte offset.

Linear sweep gives up at the first undecodable byte, which silently truncated an earlier check.
This cannot: it treats every offset as a possible instruction start, so it produces false
positives but never a false negative. A window with no hits here is definitively unreachable
by a direct branch."""
import struct, sys, pefile

PATH = r"C:\Users\Clement\Documents\GitHub\pySAGE\sage_mods\edain\patching\engine\game.dat.backup"
pe = pefile.PE(PATH, fast_load=True); BASE = pe.OPTIONAL_HEADER.ImageBase
DATA = open(PATH, "rb").read()
sec = next(s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text")
V0, FO, FS = BASE + sec.VirtualAddress, sec.PointerToRawData, sec.SizeOfRawData
code = DATA[FO:FO + FS]

def targets():
    """Yield (branch VA, kind, target VA) for every byte that could start a direct branch."""
    for off in range(len(code) - 6):
        b = code[off]
        va = V0 + off
        if b in (0xE8, 0xE9):                              # call/jmp rel32
            yield va, "rel32", va + 5 + struct.unpack_from("<i", code, off + 1)[0]
        elif b == 0xEB or 0x70 <= b <= 0x7F:               # jmp/jcc rel8
            yield va, "rel8", va + 2 + struct.unpack_from("<b", code, off + 1)[0]
        elif b == 0x0F and 0x80 <= code[off + 1] <= 0x8F:  # jcc rel32
            yield va, "jcc32", va + 6 + struct.unpack_from("<i", code, off + 2)[0]

#: The windows to check, as `(VA, length, label)`. Edit this for whatever patch is being scoped;
#: what is here is `maintenance-cost`'s five and `auto-deposit-inflation`'s one.
WINDOWS = [
    (0x0088567A, 6, "TRB income gate (in place)"),
    (0x0088569F, 7, "TRB floor"),
    (0x008856B0, 6, "TRB pay"),
    (0x0089DCDD, 5, "ADU scale (auto-deposit-inflation)"),
    (0x0089DCFF, 6, "ADU pay"),
    (0x0089DD19, 6, "ADU xp gate"),
]
hits = {w[2]: {"first": [], "interior": []} for w in WINDOWS}
for va, kind, tgt in targets():
    for start, size, label in WINDOWS:
        if tgt == start:
            hits[label]["first"].append((hex(va), kind))
        elif start < tgt < start + size:
            hits[label]["interior"].append((hex(va), kind, hex(tgt)))

for _start, _size, label in WINDOWS:
    h = hits[label]
    print(f"{label:36} first-byte: {len(h['first']):3}   INTERIOR: {h['interior']}")

# and the jump tables: does any window byte appear as an absolute imm32 anywhere in the image?
for start, size, label in WINDOWS:
    for t in range(start, start + size):
        c = DATA.count(struct.pack("<I", t))
        if c:
            print(f"  !! {label}: 0x{t:08x} appears as imm32 {c}x")
