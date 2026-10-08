// ================================================================ frame capture (AOTR_CAPTURE=1; diagnostics only)
// Groundwork for generating a render pass's Direct3D call stream on a worker thread: before anything can be generated
// the stream has to be known exactly. In capture mode a few battle frames are written out in full: every record that
// goes into the render queue (operation, arguments, the first bytes and a hash of its payload), in order, interleaved
// with marks from the engine-side hooks - render stage begin/end, render list flush, batch / mesh / effect wrapper
// calls with the objects involved, and for every mesh drawn its transform and the head of its skeleton - so that each
// parameter upload can be traced back to the engine data it came from. During captured frames effect-parameter
// batching and the vertex-input de-dupe are switched off, so the log shows every call the ENGINE makes.
// The text goes to memory while the frame runs and to capture_<n>.txt (next to the log) from a helper thread afterwards.
static volatile LONG g_capWanted = 0, g_capOn = 0, g_capRounds = 0, g_capFramesLeft = 0, g_capBusyWriting = 0;
static char* g_capBuf = NULL;
static DWORD g_capPos = 0;
#define CAP_CAP (96u << 20)
static DWORD g_capLastTick = 0;
static LONG g_capFullLeft = 0;                             // draws of this stage that still get their whole skeleton written out
static void capPrintf(const char* fmt, ...) {
    if (!g_capBuf || g_capPos + 1200 > CAP_CAP) return;
    va_list ap; va_start(ap, fmt);
    int n = wvsprintfA(g_capBuf + g_capPos, fmt, ap);
    va_end(ap);
    if (n > 0) g_capPos += (DWORD)n;
}
static void capHex(const BYTE* p, DWORD n) {                       // n bytes as hex words
    if (!g_capBuf || g_capPos + n * 3 + 16 > CAP_CAP) return;
    static const char kH[] = "0123456789ABCDEF";
    char* o = g_capBuf + g_capPos;
    for (DWORD i = 0; i < n; ++i) { if (i && !(i & 3)) *o++ = ' '; *o++ = kH[p[i] >> 4]; *o++ = kH[p[i] & 15]; }
    g_capPos = (DWORD)(o - g_capBuf);
}
static DWORD capHash(const BYTE* p, DWORD n) { DWORD h = 2166136261u; for (DWORD i = 0; i < n; ++i) { h ^= p[i]; h *= 16777619u; } return h; }
static bool capReadable(DWORD a, DWORD n) { return a >= 0x10000 && !IsBadReadPtr((void*)(ULONG_PTR)a, n); }
// a mesh about to be drawn: who it is, where it is, and the head of its skeleton
static void capMesh(const char* what, DWORD mesh, DWORD effect, DWORD count) {
    if (!g_capOn) return;
    capPrintf("M %s mesh=%08X", what, mesh);
    if (capReadable(mesh, 0x310)) {
        DWORD vt = *(DWORD*)(ULONG_PTR)mesh, cont = *(DWORD*)(ULONG_PTR)(mesh + 0x7C), model = *(DWORD*)(ULONG_PTR)(mesh + 0xC4);
        capPrintf(" vt=%08X cont=%08X model=%08X fx=%08X fxvt=%08X count=%u f2F4=%08X f2F8=%08X f2FC=%08X xf=", vt, cont, model, effect,
                  capReadable(effect, 4) ? *(DWORD*)(ULONG_PTR)effect : 0, count, *(DWORD*)(ULONG_PTR)(mesh + 0x2F4), *(DWORD*)(ULONG_PTR)(mesh + 0x2F8), *(DWORD*)(ULONG_PTR)(mesh + 0x2FC));
        capHex((const BYTE*)(ULONG_PTR)(mesh + 0x18), 48);
        if (capReadable(model, 0xC0)) { capPrintf(" modelflags=%02X polys=%d", (int)*(BYTE*)(ULONG_PTR)(model + 0x19), *(LONG*)(ULONG_PTR)(model + 0x24)); }
        if (cont && capReadable(cont, 0x100)) {
            DWORD ht = *(DWORD*)(ULONG_PTR)(cont + 0xF8);
            capPrintf(" contvt=%08X htree=%08X contxf=", *(DWORD*)(ULONG_PTR)cont, ht); capHex((const BYTE*)(ULONG_PTR)(cont + 0x18), 48);
            if (ht && capReadable(ht, 0x18)) {
                DWORD n = *(DWORD*)(ULONG_PTR)(ht + 0x10), piv = *(DWORD*)(ULONG_PTR)(ht + 0x14);
                capPrintf(" pivots=%u", n);
                DWORD show = (g_capFullLeft > 0 && n <= 96) ? n : (n < 3 ? n : 3);
                if (show == n && n > 3) g_capFullLeft--;
                if (piv && n && n <= 1024 && capReadable(piv, 0x58 * show)) { capPrintf(" piv[%u]=", show); capHex((const BYTE*)(ULONG_PTR)piv, 0x58 * show); }
            }
        }
    }
    capPrintf("\n");
}
static DWORD WINAPI capWriter(LPVOID) {
    char path[MAX_PATH]; wsprintfA(path, "%s\\capture_%d.txt", g_dir, (int)g_capRounds);
    HANDLE h = CreateFileA(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h != INVALID_HANDLE_VALUE) { DWORD w = 0, off = 0; while (off < g_capPos) { DWORD n = g_capPos - off > (1u << 20) ? (1u << 20) : g_capPos - off; if (!WriteFile(h, g_capBuf + off, n, &w, NULL) || !w) break; off += w; } CloseHandle(h); }
    logf("capture: round %d written to %s (%u bytes).", (int)g_capRounds, path, g_capPos);
    g_capPos = 0; g_capBusyWriting = 0;
    return 0;
}
