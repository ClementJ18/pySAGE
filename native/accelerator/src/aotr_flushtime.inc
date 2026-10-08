// ---------------------------------------------------------------- render pass breakdown timers (measurement)
// Inclusive time per phase of the parts of a render pass that the v15 timers left unexplained: the scene render stages
// Customized_Render 0x46FE84 and the draw loop 0x470F44, and inside the render list draw 0x573BEB the batch test
// 0x549430, mesh begin/end 0x54A080 / 0x549550, the light chain link/unlink 0x56815D / 0x5681B0 and the effect wrapper
// virtuals Begin (+8), BeginPass (+0xC), CommitChanges (+0x10, from the mesh draw), EndPass (+0x14) and End (+0x18).
// The effect wrappers are timed by pointing those vtable slots of each wrapper class seen in the render lists at thunks
// that call the original slot; arguments, results and call order are unchanged.
enum { FT_CULL = 0, FT_DRAWLOOP, FT_BATCHCMP, FT_MBEGIN, FT_MEND, FT_LINK, FT_UNLINK, FT_FXBEGIN, FT_FXPASS, FT_FXCOMMIT, FT_FXENDPASS, FT_FXEND, FT_PICK, FT_N };
static const char* const kFtName[FT_N] = { "customized-render", "draw-loop", "batch-test", "mesh-begin", "mesh-end", "fx-link", "fx-unlink",
                                           "fx.Begin", "fx.BeginPass", "fx.Commit", "fx.EndPass", "fx.End", "mesh-ray-cast" };
static volatile LONG64 g_ftPickTris[PH_N];
static volatile LONG g_ftN[FT_N][PH_N];
static volatile LONG64 g_ftT[FT_N][PH_N];
static volatile LONG g_ftOn = 0;
#define FT_ACC(k, t0) do { LONG ph_ = g_phase; if (ph_ < 0 || ph_ >= PH_N) ph_ = PH_OTHER; g_ftT[k][ph_] += (LONG64)(__rdtsc() - (t0)); g_ftN[k][ph_]++; } while (0)
typedef DWORD (__fastcall* tFtT0)(void*, void*);
typedef DWORD (__fastcall* tFtT1)(void*, void*, DWORD);
typedef DWORD (__fastcall* tFtT2)(void*, void*, DWORD, DWORD);
typedef DWORD (__cdecl* tFtC2)(DWORD, DWORD);
static tFtT1 o_ftCull = NULL, o_ftDraw = NULL, o_ftCmp = NULL;
static tFtT0 o_ftMBegin = NULL, o_ftMEnd = NULL;
static tFtC2 o_ftLink = NULL, o_ftUnlink = NULL;
static tFtT1 o_ftPick = NULL;
static DWORD __fastcall ftCull(void* s, void* e, DWORD a)   { ULONG64 t = __rdtsc(); DWORD r = o_ftCull(s, e, a); FT_ACC(FT_CULL, t); return r; }
static DWORD __fastcall ftDraw(void* s, void* e, DWORD a)   { ULONG64 t = __rdtsc(); DWORD r = o_ftDraw(s, e, a); FT_ACC(FT_DRAWLOOP, t); return r; }
static DWORD __fastcall ftCmp(void* s, void* e, DWORD a)    { ULONG64 t = __rdtsc(); DWORD r = o_ftCmp(s, e, a); FT_ACC(FT_BATCHCMP, t); if (g_capOn) capPrintf("B batch-test %08X %08X -> %u\n", (DWORD)(ULONG_PTR)s, a, r & 0xFF); return r; }
static DWORD __fastcall ftMBegin(void* s, void* e)          { if (g_capOn) capPrintf("B mesh-begin %08X\n", (DWORD)(ULONG_PTR)s); ULONG64 t = __rdtsc(); DWORD r = o_ftMBegin(s, e); FT_ACC(FT_MBEGIN, t); return r; }
static DWORD __fastcall ftMEnd(void* s, void* e)            { if (g_capOn) capPrintf("B mesh-end %08X\n", (DWORD)(ULONG_PTR)s); ULONG64 t = __rdtsc(); DWORD r = o_ftMEnd(s, e); FT_ACC(FT_MEND, t); return r; }
static DWORD __cdecl ftLink(DWORD a, DWORD b)               { ULONG64 t = __rdtsc(); DWORD r = o_ftLink(a, b); FT_ACC(FT_LINK, t); if (g_capOn) capPrintf("B fx-link lights=%08X n=%u -> %08X\n", a, b, r); return r; }
static DWORD __cdecl ftUnlink(DWORD a, DWORD b)             { if (g_capOn) capPrintf("B fx-unlink %08X %u\n", a, b); ULONG64 t = __rdtsc(); DWORD r = o_ftUnlink(a, b); FT_ACC(FT_UNLINK, t); return r; }
static DWORD __fastcall ftPick(void* s, void* e, DWORD a)   { LONG ph_ = g_phase; if (ph_ < 0 || ph_ >= PH_N) ph_ = PH_OTHER; g_ftPickTris[ph_] += *(LONG*)((BYTE*)s + 0x24); ULONG64 t = __rdtsc(); DWORD r = o_ftPick(s, e, a); FT_ACC(FT_PICK, t); return r; }

struct FtVt { DWORD vt; DWORD orig[5]; };                  // original slots +8, +0xC, +0x10, +0x14, +0x18
#define FT_VT_MAX 48
static FtVt g_ftVt[FT_VT_MAX];
static LONG g_ftVtN = 0;
static DWORD g_ftLastVt = 0;
static __forceinline const FtVt* ftVtOf(void* self) {
    DWORD vt = *(DWORD*)self;
    for (LONG i = 0; i < g_ftVtN; ++i) if (g_ftVt[i].vt == vt) return &g_ftVt[i];
    return NULL;
}
static DWORD __fastcall ftFxBegin(void* s, void* e, DWORD a, DWORD b) { const FtVt* v = ftVtOf(s); if (g_capOn) capPrintf("X fx.Begin wrapper=%08X vt=%08X args=%08X %08X\n", (DWORD)(ULONG_PTR)s, *(DWORD*)s, a, b); ULONG64 t = __rdtsc(); DWORD r = ((tFtT2)(ULONG_PTR)v->orig[0])(s, e, a, b); FT_ACC(FT_FXBEGIN, t); return r; }
static DWORD __fastcall ftFxPass(void* s, void* e, DWORD a)           { const FtVt* v = ftVtOf(s); if (g_capOn) capPrintf("X fx.BeginPass wrapper=%08X pass=%u\n", (DWORD)(ULONG_PTR)s, a); ULONG64 t = __rdtsc(); DWORD r = ((tFtT1)(ULONG_PTR)v->orig[1])(s, e, a); FT_ACC(FT_FXPASS, t); return r; }
static DWORD __fastcall ftFxCommit(void* s, void* e, DWORD a)         { const FtVt* v = ftVtOf(s); if (g_capOn) capPrintf("X fx.Commit wrapper=%08X arg=%08X\n", (DWORD)(ULONG_PTR)s, a); ULONG64 t = __rdtsc(); DWORD r = ((tFtT1)(ULONG_PTR)v->orig[2])(s, e, a); FT_ACC(FT_FXCOMMIT, t); return r; }
static DWORD __fastcall ftFxEndPass(void* s, void* e)                 { const FtVt* v = ftVtOf(s); if (g_capOn) capPrintf("X fx.EndPass wrapper=%08X\n", (DWORD)(ULONG_PTR)s); ULONG64 t = __rdtsc(); DWORD r = ((tFtT0)(ULONG_PTR)v->orig[3])(s, e); FT_ACC(FT_FXENDPASS, t); return r; }
static DWORD __fastcall ftFxEnd(void* s, void* e)                     { const FtVt* v = ftVtOf(s); if (g_capOn) capPrintf("X fx.End wrapper=%08X\n", (DWORD)(ULONG_PTR)s); ULONG64 t = __rdtsc(); DWORD r = ((tFtT0)(ULONG_PTR)v->orig[4])(s, e); FT_ACC(FT_FXEND, t); return r; }
static __forceinline bool ftIsGameCode(DWORD f) { return f >= g_textLo && f < g_textHi; }
// game thread, from the render list flush: time the wrapper virtuals of every effect class the lists use
static void ftRegisterVt(DWORD obj) {
    if (!g_ftOn || !obj) return;
    DWORD vt = *(DWORD*)(ULONG_PTR)obj;
    if (vt == g_ftLastVt) return;
    g_ftLastVt = vt;
    for (LONG i = 0; i < g_ftVtN; ++i) if (g_ftVt[i].vt == vt) return;
    if (g_ftVtN >= FT_VT_MAX) return;
    DWORD* slots = (DWORD*)(ULONG_PTR)(vt + 8);
    for (int k = 0; k < 5; ++k) if (!ftIsGameCode(slots[k])) return;
    FtVt& v = g_ftVt[g_ftVtN];
    v.vt = vt; for (int k = 0; k < 5; ++k) v.orig[k] = slots[k];
    g_ftVtN++;                                               // visible to the thunks before any slot points at them
    logf("flushtime: effect wrapper class vtable game.dat+%06X: Begin +%06X BeginPass +%06X commit +%06X EndPass +%06X End +%06X", vt - 0x400000, v.orig[0] - 0x400000, v.orig[1] - 0x400000, v.orig[2] - 0x400000, v.orig[3] - 0x400000, v.orig[4] - 0x400000);
    DWORD op = 0;
    if (!VirtualProtect(slots, 20, PAGE_READWRITE, &op)) return;
    slots[0] = (DWORD)(ULONG_PTR)&ftFxBegin; slots[1] = (DWORD)(ULONG_PTR)&ftFxPass; slots[2] = (DWORD)(ULONG_PTR)&ftFxCommit;
    slots[3] = (DWORD)(ULONG_PTR)&ftFxEndPass; slots[4] = (DWORD)(ULONG_PTR)&ftFxEnd;
    VirtualProtect(slots, 20, op, &op);
}
static void ftScanLists(DWORD* r) {
    for (int l = 0; l < 3; ++l) {
        DWORD first = r[l * 3], last = r[l * 3 + 1];
        for (DWORD a = first; a < last; a += 32) {
            const DWORD* el = (const DWORD*)(ULONG_PTR)a;
            if (el[1] > 0 && el[2]) ftRegisterVt(el[2]);
        }
    }
}
static void installFlushTimers() {
    static const BYTE kCull[] = {0x55,0x8B,0xEC,0x83,0xEC,0x0C,0x53,0x56};
    static const BYTE kDraw[] = {0xB8,0x28,0x2F,0xB7,0x00,0xE8,0xA2,0xBF};
    static const BYTE kCmp[]  = {0x83,0xEC,0x18,0x55,0x8B,0xE9,0x8B,0x85};
    static const BYTE kMBeg[] = {0x55,0x8B,0xEC,0x83,0xEC,0x20,0x56,0x8B};
    static const BYTE kMEnd[] = {0x8B,0x81,0xC4,0x00,0x00,0x00,0x85,0xC0};
    static const BYTE kLink[] = {0x55,0x8B,0xEC,0x53,0x8B,0x5D,0x0C,0x85};
    static const BYTE kUnl[]  = {0x55,0x8B,0xEC,0x51,0x56,0x33,0xF6,0x39};
    static const BYTE kPick[] = {0x83,0xEC,0x18,0x53,0x55,0x8B,0xE9,0x8B};
    char env[8]; env[0] = 0;
    if (GetEnvironmentVariableA("AOTR_FLUSHTIME", env, sizeof(env)) && env[0] == '0') { logf("flushtime: disabled by AOTR_FLUSHTIME=0."); return; }
    __try {
        if (memcmp((void*)0x0046FE84, kCull, 8) || memcmp((void*)0x00470F44, kDraw, 8) || memcmp((void*)0x00549430, kCmp, 8) || memcmp((void*)0x0054A080, kMBeg, 8) ||
            memcmp((void*)0x00549550, kMEnd, 8) || memcmp((void*)0x0056815D, kLink, 8) || memcmp((void*)0x005681B0, kUnl, 8) || memcmp((void*)0x0056C600, kPick, 8)) {
            logf("flushtime: render pass code differs - breakdown timers OFF."); return;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { return; }
    o_ftCull = (tFtT1)makeTrampoline((BYTE*)0x0046FE84, 6);
    o_ftDraw = (tFtT1)makeTrampoline((BYTE*)0x00470F44, 5);
    o_ftCmp = (tFtT1)makeTrampoline((BYTE*)0x00549430, 6);
    o_ftMBegin = (tFtT0)makeTrampoline((BYTE*)0x0054A080, 6);
    o_ftMEnd = (tFtT0)makeTrampoline((BYTE*)0x00549550, 6);
    o_ftLink = (tFtC2)makeTrampoline((BYTE*)0x0056815D, 7);
    o_ftUnlink = (tFtC2)makeTrampoline((BYTE*)0x005681B0, 5);
    o_ftPick = (tFtT1)(ULONG_PTR)0x0056C600;                     // not hooked here any more: aotr_pick.inc owns the brute-force mesh cast
    if (!o_ftCull || !o_ftDraw || !o_ftCmp || !o_ftMBegin || !o_ftMEnd || !o_ftLink || !o_ftUnlink || !o_ftPick) { logf("flushtime: alloc failed - OFF."); return; }
    HANDLE fz[256]; int nf = 0;
    suspendOthers(fz, &nf, 256);
    patchJmp((BYTE*)0x0046FE84, (void*)&ftCull, 6);
    patchJmp((BYTE*)0x00470F44, (void*)&ftDraw, 5);
    patchJmp((BYTE*)0x00549430, (void*)&ftCmp, 6);
    patchJmp((BYTE*)0x0054A080, (void*)&ftMBegin, 6);
    patchJmp((BYTE*)0x00549550, (void*)&ftMEnd, 6);
    patchJmp((BYTE*)0x0056815D, (void*)&ftLink, 7);
    patchJmp((BYTE*)0x005681B0, (void*)&ftUnlink, 5);
    (void)&ftPick;
    resumeAll(fz, nf);
    g_ftOn = 1;
    logf("flushtime: render pass breakdown timers installed (customized render, draw loop, batch test, mesh begin/end, light chain, effect wrapper virtuals).");
}
static void ftReport(LONG f) {
    if (!g_ftOn || f <= 0) return;
    static LONG lN[FT_N][PH_N]; static LONG64 lT[FT_N][PH_N];
    double k = g_tscPerQpc > 0 ? 1.0 / g_tscPerQpc : 0;
    for (int ph = PH_SHADOW; ph <= PH_VIEWS; ++ph) {
        char ln[900]; int p = 0;
        p += wsprintfA(ln + p, "rt: pass parts %s (%d effect classes):", kPhaseName[ph], (int)g_ftVtN);
        for (int i = 0; i < FT_N; ++i) {
            LONG n = g_ftN[i][ph] - lN[i][ph]; LONG64 t = rd64(&g_ftT[i][ph]) - lT[i][ph];
            lN[i][ph] += n; lT[i][ph] += t;
            char a1[16], a2[16];
            p += wsprintfA(ln + p, " %s %s/f %s ms/f |", kFtName[i], perStr(n, f, a1), msStr((LONG64)(t * k), f, a2));
            if (p > 820) break;
        }
        logf("%s", ln);
    }
    static LONG lPN = 0; static LONG64 lPT = 0, lPTris = 0;
    LONG pn = 0; LONG64 pt = 0, ptris = 0;
    for (int ph = 0; ph < PH_N; ++ph) { pn += g_ftN[FT_PICK][ph]; pt += rd64(&g_ftT[FT_PICK][ph]); ptris += rd64(&g_ftPickTris[ph]); }
    char c1[16], c2[16], c3[16];
    logf("rt: mesh ray casts (all phases): calls/f %s triangles/f %s time %s ms/f", perStr(pn - lPN, f, c1), perStr((LONG)(ptris - lPTris), f, c2), msStr((LONG64)((pt - lPT) * k), f, c3));
    lPN = pn; lPT = pt; lPTris = ptris;
}
