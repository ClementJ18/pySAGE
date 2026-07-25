import pe, struct, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def cstr(va, maxlen=8):
    o = pe.va_to_off(va)
    if o is None: return None
    end = pe.DATA.find(b"\x00", o)
    if end < 0 or end-o > maxlen: return None
    return pe.DATA[o:end].decode("latin1")

# every dword in .rdata+.data pointing to a pure-decimal string
hits = []
for name, va0, va1, fo, fs in pe.SECTIONS:
    if name not in (".rdata", ".data"): continue
    for off in range(fo, fo+fs, 4):
        dv = struct.unpack("<I", pe.DATA[off:off+4])[0]
        if not dv: continue
        s = cstr(dv)
        if s and all(c in "0123456789" for c in s) and 1 <= len(s) <= 2:
            hits.append((pe.off_to_va(off), int(s), s))

print(f"total decimal-string pointer dwords: {len(hits)}")
# find clusters: consecutive entries whose VA locations are within 16 bytes stride
hits.sort()
cluster=[hits[0]]
clusters=[]
for prev,cur in zip(hits, hits[1:]):
    if cur[0]-prev[0] <= 24:
        cluster.append(cur)
    else:
        if len(cluster)>=6: clusters.append(cluster)
        cluster=[cur]
if len(cluster)>=6: clusters.append(cluster)

print(f"clusters (>=6): {len(clusters)}")
for c in clusters:
    vals=[v for _,v,_ in c]
    stride = c[1][0]-c[0][0] if len(c)>1 else 0
    print(f"\ncluster @ {c[0][0]:08x} stride={stride} count={len(c)} min={min(vals)} max={max(vals)}")
    print("  values:", vals)
