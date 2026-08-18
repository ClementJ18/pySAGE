import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

path = sys.argv[1]
d = open(path, "rb").read()
assert d[:4] == b"MDMP", d[:4]
ver, nstreams, dir_rva = struct.unpack_from(
    "<III", d, 4
)  # after signature(4): version, nstreams, rva
# header: Signature(4) Version(4) NumberOfStreams(4) StreamDirectoryRva(4) ...
nstreams, dir_rva = struct.unpack_from("<II", d, 8)
streams: dict[int, tuple[int, int]] = {}
for i in range(nstreams):
    st, dsz, rva = struct.unpack_from("<III", d, dir_rva + i * 12)
    streams.setdefault(st, (dsz, rva))


# ModuleListStream = 4
def modules():
    if 4 not in streams:
        return []
    dsz, rva = streams[4]
    n = struct.unpack_from("<I", d, rva)[0]
    mods = []
    off = rva + 4
    for _ in range(n):
        # MINIDUMP_MODULE: BaseOfImage(8) SizeOfImage(4) CheckSum(4) TimeDateStamp(4)
        #   ModuleNameRva(4) VersionInfo(13*4=52) CvRecord(8) MiscRecord(8)
        #   Reserved0(8) Reserved1(8)
        base, size, chk, tds, name_rva = struct.unpack_from("<QIIII", d, off)
        # module name: ULONG32 length (bytes) + UTF-16
        ln = struct.unpack_from("<I", d, name_rva)[0]
        name = d[name_rva + 4 : name_rva + 4 + ln].decode("utf-16-le", "replace")
        mods.append((base, size, name))
        off += 108  # sizeof(MINIDUMP_MODULE)
    return mods


mods = modules()
game = None
for base, size, name in mods:
    if name.lower().endswith("game.dat"):
        game = (base, size, name)
print("game.dat module:", None if not game else f"base=0x{game[0]:x} size=0x{game[1]:x}")

# ExceptionStream = 6
if 6 in streams:
    dsz, rva = streams[6]
    tid, align = struct.unpack_from("<II", d, rva)
    # MINIDUMP_EXCEPTION at rva+8: ExceptionCode(4) ExceptionFlags(4) ExceptionRecord(8)
    #   ExceptionAddress(8) NumberParameters(4) __align(4) ExceptionInformation[15](8 each)
    er = rva + 8
    code, flags, exrec, exaddr, nparam = struct.unpack_from("<IIQQI", d, er)
    info = [
        struct.unpack_from("<Q", d, er + 8 + 8 + 8 + 4 + 4 + k * 8)[0]
        for k in range(min(nparam, 15))
    ]
    print(f"ExceptionCode = 0x{code:08x}")
    print(f"ExceptionAddress (faulting EIP) = 0x{exaddr:x}")
    if game:
        b = game[0]
        if b <= exaddr < b + game[1]:
            rel = exaddr - b
            print(f"  -> game.dat + 0x{rel:x}  (VA if base 0x400000: 0x{0x400000 + rel:x})")
    if code == 0xC0000005 and len(info) >= 2:
        rw = {0: "read", 1: "write", 8: "execute"}.get(info[0], info[0])
        print(f"ACCESS_VIOLATION: {rw} at address 0x{info[1]:x}")

    # thread context: LocationDescriptor right after MINIDUMP_EXCEPTION
    # (which is 8+8+8+4+4+15*8 = 152 bytes)
    ctx_loc = er + 8 + 8 + 8 + 4 + 4 + 15 * 8
    csz, crva = struct.unpack_from("<II", d, ctx_loc)
    c = crva

    def r(o):
        return struct.unpack_from("<I", d, c + o)[0]

    Edi, Esi, Ebx, Edx, Ecx, Eax = (r(0x9C), r(0xA0), r(0xA4), r(0xA8), r(0xAC), r(0xB0))
    Ebp, Eip, Esp = r(0xB4), r(0xB8), r(0xC4)
    print(f"\nregs: eip={Eip:08x} esp={Esp:08x} ebp={Ebp:08x}")
    print(
        f"      eax={Eax:08x} ecx={Ecx:08x} edx={Edx:08x} ebx={Ebx:08x} esi={Esi:08x} edi={Edi:08x}"
    )

    # memory ranges (Memory64ListStream=9 preferred; MemoryListStream=5)
    ranges = []
    if 9 in streams:
        _, rva = streams[9]
        n = struct.unpack_from("<Q", d, rva)[0]
        base_rva = struct.unpack_from("<Q", d, rva + 8)[0]
        off = rva + 16
        cur = base_rva
        for _ in range(n):
            sa, sz = struct.unpack_from("<QQ", d, off)
            off += 16
            ranges.append((sa, sz, cur))
            cur += sz
    if 5 in streams:
        _, rva = streams[5]
        n = struct.unpack_from("<I", d, rva)[0]
        off = rva + 4
        for _ in range(n):
            sa, dsz2, drva = struct.unpack_from("<QII", d, off)
            off += 16
            ranges.append((sa, dsz2, drva))

    def read_mem(addr, ln):
        for sa, sz, fr in ranges:
            if sa <= addr < sa + sz:
                o = fr + (addr - sa)
                return d[o : o + min(ln, sz - (addr - sa))]
        return None

    # The engine's own "Game crash" code, raised by `Debug::crash`. Stock, it arrives with no
    # parameters at all, which is why four of the six dumps in the install root say a crash
    # happened and not which one. The `crash-dump` patch fills three: the formatted crash text,
    # the .rdata literal saying whether it was an assertion or an error, and the mode. The first
    # is a heap pointer, so it resolves only in a dump whose type carried the heap.
    if code == 0x04560123:
        if not nparam:
            print("\nGame crash: no exception parameters (binary without the crash-dump patch)")
        labels = ("message", "kind", "mode")
        for k, value in enumerate(info):
            label = labels[k] if k < len(labels) else f"param[{k}]"
            pointerish = value > 0x10000
            blob = read_mem(value, 0x400) if pointerish else None
            if blob and b"\x00" in blob:
                text = blob.partition(b"\x00")[0].decode("ascii", "replace")
                print(f"\n{label}: {text}")
            elif pointerish:
                print(f"\n{label}: 0x{value:x}  (not in any captured range)")
            else:
                print(f"\n{label}: 0x{value:x}")

    if game:  # the stack walk is only meaningful relative to the game.dat module
        GB, GE = game[0], game[0] + game[1]
        stk = read_mem(Esp, 0x200)
        print(f"\nstack walk from esp (return addrs in game.dat 0x{GB:x}-0x{GE:x}):")
        if stk:
            for i in range(0, len(stk), 4):
                v = struct.unpack_from("<I", stk, i)[0]
                if GB <= v < GE:
                    print(f"  [esp+0x{i:03x}] 0x{v:08x}   (game.dat+0x{v - GB:x})")
