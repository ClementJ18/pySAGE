// ---------------------------------------------------------------- logic step timing by module type and subsystem (measurement)
// GameLogic::update runs every due sleepy-update module through its UpdateModuleInterface (0x62EA97: lea ecx,[ebx+0x10];
// mov eax,[ecx]; call [eax]) and, in sub-frame 5, twelve subsystem updates (mov ecx,[global]; mov eax,[ecx];
// call [eax+0x28] at 0x62EB69..0x62EC05). Those sites call the same functions through timed wrappers that charge the
// time to the module's interface vtable (per logic sub-frame) or to the subsystem; arguments and results are unchanged.
struct ModT { DWORD vt; LONG n[7]; LONG64 t[7]; LONG ln; LONG64 lt; DWORD w; };
// A fixed cost per module type (units of 0.1 microsecond per update, measured in the v23 battle). The logic spread cuts
// the list work by this count instead of by the clock, so the cuts are a pure function of the game state: the same on
// every machine of a multiplayer game and in every replay. The numbers only need to be roughly right - they balance the
// frames, they do not change what runs or in which order.
struct ModW { DWORD vt; DWORD w; };
static const ModW kModW[] = {                              // v25: the v23 and v24 battles together
    { 0x00C6A5A8, 108 }, { 0x00C5D3E0, 880 }, { 0x00C66D3C, 527 }, { 0x00C6D948, 61 }, { 0x00C64284, 1608 }, { 0x00C6D1A0, 79 }, { 0x00C57F80, 8379 }, { 0x00C6B408, 98 },
    { 0x00C67E2C, 77 }, { 0x00C6AC9C, 145 }, { 0x00C585F8, 551 }, { 0x00C629BC, 832 }, { 0x00C67598, 1502 }, { 0x00C11F18, 4 }, { 0x00C6450C, 76 }, { 0x00C12154, 1698 },
    { 0x00C63888, 51 }, { 0x00C5E378, 87 }, { 0x00C68844, 12 }, { 0x00C60670, 46 }, { 0x00C6E150, 2 }, { 0x00C57FC8, 65 }, { 0x00C769EC, 527 }, { 0x00C58DC8, 11 },
    { 0x00C61FA4, 51 }, { 0x00C5FBCC, 481 }, { 0x00C56C5C, 21 }, { 0x00C60C28, 168 }, { 0x00C66C04, 90 }, { 0x00C689A8, 160 }, { 0x00C306B8, 343 }, { 0x00C2E1B8, 2200 },
    { 0x00C4E9F8, 9 }, { 0x00C57828, 2 }, { 0x00C56D60, 1 },
};
#define MODW_DEFAULT 3                                     // a type that never reached the top of a timing report is cheap (v24 over-weighted the tail: the n5 slice ran short)
static ULONG64 g_lsCost = 0;                               // running sum of the costs of the module updates made (game thread)
static DWORD mtWeight(DWORD vt) { for (int i = 0; i < (int)(sizeof(kModW) / sizeof(kModW[0])); ++i) if (kModW[i].vt == vt) return kModW[i].w; return MODW_DEFAULT; }
#define MT_N 1024
static ModT* g_mt = NULL;
static volatile LONG g_mtDrop = 0, g_mtOn = 0;
static DWORD __fastcall mtUpdate(DWORD* iface) {
    DWORD vt = *iface;
    ULONG64 t0 = __rdtsc();
    DWORD r = ((DWORD (__fastcall*)(DWORD*, void*))(ULONG_PTR)(*(DWORD*)(ULONG_PTR)vt))(iface, NULL);
    LONG64 dt = (LONG64)(__rdtsc() - t0);
    LONG k = g_lgCurN; if (k < 0 || k > 6) k = 0;
    DWORD h = (vt * 2654435761u) >> 22;
    for (int i = 0; i < 16; ++i) {
        ModT& m = g_mt[(h + i) & (MT_N - 1)];
        if (m.vt == vt || !m.vt) { if (!m.vt) { m.vt = vt; m.w = mtWeight(vt); } m.n[k]++; m.t[k] += dt; g_lsCost += m.w; return r; }
    }
    g_mtDrop++; g_lsCost += mtWeight(vt);
    return r;
}
static __declspec(naked) void mtStub() {
    __asm {
        lea ecx, [ebx + 0x10]
        jmp mtUpdate
    }
}
#define SUB_N 12
static const DWORD kSubSite[SUB_N] = { 0x0062EB69, 0x0062EB85, 0x0062EB90, 0x0062EB9B, 0x0062EBA6, 0x0062EBB8, 0x0062EBC3, 0x0062EBCE, 0x0062EBD9, 0x0062EBEF, 0x0062EBFA, 0x0062EC05 };
static const char* const kSubName[SUB_N] = { "AI", "sub4358", "Taint", "BuildAssistant", "sub3BE8", "WeaponStore", "LocomotorStore", "VictoryConditions", "DelayedXP", "SkirmishAI", "MineshaftNet", "TeamFactory" };
static DWORD g_subGlob[SUB_N];
static DWORD g_subFn[SUB_N];                       // the update each subsystem singleton actually runs (named once seen)
static volatile LONG64 g_subT[SUB_N];
static volatile LONG g_subN[SUB_N];
static void __stdcall subTimed(int k) {
    DWORD obj = *(DWORD*)(ULONG_PTR)g_subGlob[k];
    DWORD fn = *(DWORD*)(ULONG_PTR)(*(DWORD*)(ULONG_PTR)obj + 0x28);
    if (g_subFn[k] != fn) { g_subFn[k] = fn; logf("modtime: %s update is game.dat+%06X (object %08X)", kSubName[k], fn - 0x400000, obj); }
    ULONG64 t0 = __rdtsc();
    ((void (__fastcall*)(DWORD, void*))(ULONG_PTR)fn)(obj, NULL);
    g_subT[k] += (LONG64)(__rdtsc() - t0); g_subN[k]++;
}
#define SUB_STUB(k) static __declspec(naked) void subStub##k() { __asm push k __asm call subTimed __asm ret }
SUB_STUB(0) SUB_STUB(1) SUB_STUB(2) SUB_STUB(3) SUB_STUB(4) SUB_STUB(5) SUB_STUB(6) SUB_STUB(7) SUB_STUB(8) SUB_STUB(9) SUB_STUB(10) SUB_STUB(11)
static void* const kSubStub[SUB_N] = { (void*)&subStub0, (void*)&subStub1, (void*)&subStub2, (void*)&subStub3, (void*)&subStub4, (void*)&subStub5, (void*)&subStub6, (void*)&subStub7, (void*)&subStub8, (void*)&subStub9, (void*)&subStub10, (void*)&subStub11 };
static void mtWriteCall(DWORD site, void* fn, int len) {
    BYTE* q = (BYTE*)(ULONG_PTR)site; DWORD op = 0;
    VirtualProtect(q, len, PAGE_EXECUTE_READWRITE, &op);
    q[0] = 0xE8; *(DWORD*)(q + 1) = (DWORD)(ULONG_PTR)fn - (site + 5);
    for (int i = 5; i < len; ++i) q[i] = 0x90;
    VirtualProtect(q, len, op, &op);
    FlushInstructionCache(GetCurrentProcess(), q, len);
}
static void installModuleTimers() {
    static const BYTE kModSite[] = {0x8D,0x4B,0x10,0x8B,0x01,0xFF,0x10,0x83,0xF8,0x01};
    __try {
        if (memcmp((void*)0x0062EA97, kModSite, sizeof(kModSite))) { logf("modtime: module update site differs - logic timers OFF."); return; }
        for (int k = 0; k < SUB_N; ++k) {
            const BYTE* b = (const BYTE*)(ULONG_PTR)kSubSite[k];
            if (b[0] != 0x8B || b[1] != 0x0D || b[6] != 0x8B || b[7] != 0x01 || b[8] != 0xFF || b[9] != 0x50 || b[10] != 0x28) { logf("modtime: subsystem site %08X differs - logic timers OFF.", kSubSite[k]); return; }
            g_subGlob[k] = *(DWORD*)(b + 2);
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { return; }
    g_mt = (ModT*)VirtualAlloc(NULL, MT_N * sizeof(ModT), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!g_mt) return;
    HANDLE fz[256]; int nf = 0;
    suspendOthers(fz, &nf, 256);
    mtWriteCall(0x0062EA97, (void*)&mtStub, 7);
    for (int k = 0; k < SUB_N; ++k) mtWriteCall(kSubSite[k], kSubStub[k], 11);
    resumeAll(fz, nf);
    g_mtOn = 1;
    logf("modtime: logic module updates (0x62EA97) and the 12 sub-frame-5 subsystem updates are timed.");
}
static int __cdecl mtCmp(const void* a, const void* b) {
    const ModT* x = *(const ModT* const*)a, *y = *(const ModT* const*)b;
    return x->lt < y->lt ? 1 : (x->lt > y->lt ? -1 : 0);
}
static void mtReport(LONG frames) {                      // every 30 s from the RT report thread
    if (!g_mtOn || frames <= 0 || g_tscPerQpc <= 0) return;
    static ModT* order[MT_N]; int m = 0;
    static LONG lastN[MT_N][7]; static LONG64 lastT[MT_N][7];
    static LONG64 dT[MT_N][7]; static LONG dN[MT_N][7];
    for (int i = 0; i < MT_N; ++i) {
        ModT& e = g_mt[i]; if (!e.vt) continue;
        LONG64 tot = 0; LONG cnt = 0;
        for (int k = 0; k < 7; ++k) { LONG n = e.n[k]; LONG64 t = e.t[k]; dN[i][k] = n - lastN[i][k]; dT[i][k] = t - lastT[i][k]; lastN[i][k] = n; lastT[i][k] = t; tot += dT[i][k]; cnt += dN[i][k]; }
        e.lt = tot; e.ln = cnt;
        if (tot > 0) order[m++] = &e;
    }
    qsort(order, m, sizeof(order[0]), mtCmp);
    LONG64 all = 0; for (int i = 0; i < m; ++i) all += order[i]->lt;
    char a1[16]; logf("modtime: %d module types ran; all module updates %s ms/f (drops %d)", m, msStr((LONG64)((double)all / g_tscPerQpc), frames, a1), (int)g_mtDrop);
    for (int i = 0; i < m && i < 30; ++i) {
        ModT& e = *order[i]; int idx = (int)(&e - g_mt);
        char c1[16], t1[16], sub[200]; int sp = 0; sub[0] = 0;
        for (int k = 1; k < 7; ++k) if (dT[idx][k] > 0) { char x[16]; sp += wsprintfA(sub + sp, " n%d %s", k, msStr((LONG64)((double)dT[idx][k] / g_tscPerQpc), frames, x)); }
        logf("modtime:   vt %08X calls/f %s ms/f %s |%s", e.vt, perStr(e.ln, frames, c1), msStr((LONG64)((double)e.lt / g_tscPerQpc), frames, t1), sub);
    }
    static LONG64 lSubT[SUB_N]; static LONG lSubN[SUB_N];
    char line[600]; int lp = 0;
    for (int k = 0; k < SUB_N; ++k) {
        LONG64 t = rd64(&g_subT[k]); LONG n = g_subN[k]; LONG64 d = t - lSubT[k]; LONG dn = n - lSubN[k]; lSubT[k] = t; lSubN[k] = n;
        char x[16]; lp += wsprintfA(line + lp, " %s %s", kSubName[k], msStr((LONG64)((double)d / g_tscPerQpc), dn > 0 ? dn : 1, x));
    }
    logf("modtime: sub-frame-5 subsystems ms per logic step:%s", line);
}
