// ---------------------------------------------------------------- mesh render list sort without reference-count churn (exact)
// MeshClass::Render (0x54B500) queues each FX-shaded mesh it draws into the mesh renderer [0xDDC9D4] with 0x57430D: a
// 32-byte element {RefPtr mesh; DWORD n; RefPtr lights[6]} appended to one of three vectors (+0x00, +0x0C, +0x18). The
// flush (0x574406) sorts each vector by the mesh's model pointer [mesh+0xC4] (the second one also by [mesh+0x310]) with
// 0x5740D0 - a quick sort (median of three, recursion budget 2*log2(n), heap sort 0x573B95 when the budget runs out,
// ranges of 16 or fewer left alone) followed by two insertion passes - and then draws the batches. Every element move in
// that sort copies, assigns and destroys seven reference-counted pointers through SEH-framed vector helpers.
// The replacement runs the same algorithm step for step (same median, partition, recursion order and insertion passes;
// the comparator is called in the same sequence on the same element values; the heap sort fallback is the stock code)
// but moves elements as plain 32-byte copies. Moves only permute the pointers inside the vector, so every reference count
// ends where the stock sort leaves it (the stock sort never releases an object either) and the order is identical, ties
// included. Checked: offline by rlsort_test.exe (stock sort code mapped from game.dat, results and comparator call
// sequences), at start-up on synthetic lists full of ties, and in game on the first 3000 sorts and one in 128 after that (stock sort on the real list, replacement on a copy, bytes compared; one
// difference turns the replacement off for the session).
// v15: the push (0x57430D) and the tail erase that empties each list after drawing (0x573816) run without their
// temporaries too. Push: the element is written in place with the reference the caller passed in and one reference per
// light (the stock code gets the same counts through a default element, a copy and seven reference-counted assignments);
// more than 6 lights or a full vector take the stock path. Erase: elements are released front to back, each one's lights
// back to front and then its mesh, exactly the stock destructor order (Delete_This at zero in the same sequence). Checked
// offline by rlsort_test.exe against the stock code (list bytes, reference counts, release order) and in game on the first
// 20000 pushes and one in 512 after that (stock push, then the element and reference counts compared with the prediction).
#include "aotr_rlsort_algo.h"
typedef void (__cdecl* tRlSort)(RlEl*, RlEl*, tRlPred);
typedef void (__fastcall* tRlFlush)(void*, void*);
typedef void (__fastcall* tRlPush)(DWORD*, void*, DWORD, DWORD*);
typedef DWORD (__fastcall* tRlErase)(DWORD*, void*, DWORD, DWORD);
typedef void (__fastcall* tRlDraw)(void*, void*, DWORD, DWORD);
typedef void (__fastcall* tRlMeshRender)(void*, void*, void*);
static tRlSort  o_rlSort = NULL;
static tRlFlush o_rlFlush = NULL;
static tRlPush  o_rlPush = NULL;
static tRlErase o_rlErase = NULL;
static tRlDraw o_rlDraw = NULL;
static tRlMeshRender o_rlMeshRender = NULL;
static volatile LONG g_rlPushLive = 0, g_rlPushOff = 0, g_rlPushCheckLeft = 20000, g_rlPushTick = 0, g_rlPushChecked = 0, g_rlPushMismatch = 0, g_rlPushStock = 0;
static volatile LONG g_rlEraseN[PH_N], g_rlEraseEls[PH_N], g_rlDrawN[PH_N], g_rlMeshN[PH_N];
static volatile LONG64 g_rlEraseT[PH_N], g_rlDrawT[PH_N], g_rlMeshT[PH_N];
static volatile LONG g_rlLive = 0, g_rlOff = 0, g_rlCheckLeft = 3000, g_rlTick = 0, g_rlMismatch = 0, g_rlFaults = 0, g_rlChecks = 0;
static volatile LONG g_rlSorts[PH_N], g_rlEls[PH_N], g_rlPushN[PH_N], g_rlFlushN[PH_N];
static volatile LONG64 g_rlSortT[PH_N], g_rlFlushT[PH_N], g_rlPushT[PH_N], g_rlCheckFastT = 0, g_rlCheckStockT = 0;
static RlEl* g_rlTmp = NULL;
static DWORD g_rlTmpCap = 0;

static bool rlTmpFor(DWORD n) {
    if (n <= g_rlTmpCap && g_rlTmp) return true;
    DWORD cap = n < 4096 ? 4096 : n + n / 2;
    RlEl* b = (RlEl*)VirtualAlloc(NULL, cap * sizeof(RlEl), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!b) return false;
    if (g_rlTmp) VirtualFree(g_rlTmp, 0, MEM_RELEASE);
    g_rlTmp = b; g_rlTmpCap = cap;
    return true;
}
static bool rlFastOnCopy(RlEl* begin, DWORD n, tRlPred pred) {
    memcpy(g_rlTmp, begin, n * sizeof(RlEl));
    __try { rlFastSort(g_rlTmp, g_rlTmp + n, pred); return true; }
    __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}
static void __cdecl hkRlSort(RlEl* begin, RlEl* end, tRlPred pred) {
    LONG ph = g_phase; if (ph < 0 || ph >= PH_N) ph = PH_OTHER;
    DWORD n = (DWORD)(end - begin);
    LONG64 t0 = qpcNow();
    if (!g_rlLive || g_rlOff || !g_mkTid) {
        o_rlSort(begin, end, pred);
    } else if (GetCurrentThreadId() == g_mkTid && (g_rlCheckLeft > 0 ? (g_rlCheckLeft--, true) : ((++g_rlTick & 127) == 0)) && rlTmpFor(n)) {
        bool ok = rlFastOnCopy(begin, n, pred);
        LONG64 t1 = qpcNow();
        o_rlSort(begin, end, pred);
        LONG64 t2 = qpcNow();
        if (!ok) { if (!g_rlFaults++) logf("rlsort: replacement faulted on a list of %u - stock sort for the rest of the session.", n); g_rlOff = 1; }
        else if (memcmp(g_rlTmp, begin, n * sizeof(RlEl))) {
            if (!g_rlMismatch++) logf("rlsort: SELF-CHECK MISMATCH on a list of %u (comparator %08X) - stock sort for the rest of the session.", n, (DWORD)(ULONG_PTR)pred);
            g_rlOff = 1;
        } else { g_rlChecks++; g_rlCheckFastT += t1 - t0; g_rlCheckStockT += t2 - t1; }
        g_rlSortT[ph] += t2 - t0; g_rlSorts[ph]++; g_rlEls[ph] += (LONG)n;
        return;
    } else {
        rlFastSort(begin, end, pred);
    }
    g_rlSortT[ph] += qpcNow() - t0; g_rlSorts[ph]++; g_rlEls[ph] += (LONG)n;
}
static void __fastcall hkRlFlush(void* self, void* edx) {
    LONG ph = g_phase; if (ph < 0 || ph >= PH_N) ph = PH_OTHER;
    if (g_ftOn && GetCurrentThreadId() == g_mkTid) ftScanLists((DWORD*)self);
    if (g_capOn) { const DWORD* r = (const DWORD*)self; capPrintf("L flush-begin list=%08X elements %u %u %u\n", (DWORD)(ULONG_PTR)self, (r[1] - r[0]) >> 5, (r[4] - r[3]) >> 5, (r[7] - r[6]) >> 5); }
    LONG64 t0 = qpcNow();
    o_rlFlush(self, edx);
    g_rlFlushT[ph] += qpcNow() - t0; g_rlFlushN[ph]++;
    if (g_capOn) capPrintf("L flush-end list=%08X\n", (DWORD)(ULONG_PTR)self);
}
// predicted element of a push, checked against what the stock push wrote
static bool rlPushMatches(DWORD* r, DWORD mesh, const DWORD* lights, DWORD* v, DWORD last0, LONG meshRefs0, const LONG* lightRefs0) {
    DWORD n = (DWORD)((LONG)(lights[1] - lights[0]) >> 2);
    const DWORD* src = (const DWORD*)(ULONG_PTR)lights[0];
    const DWORD* e = (const DWORD*)(ULONG_PTR)last0;
    if (v[1] != last0 + 32 || e[0] != mesh || e[1] != n || *(LONG*)(ULONG_PTR)(mesh + 4) != meshRefs0) return false;
    for (DWORD i = 0; i < 6; ++i) {
        DWORD p = i < n ? src[i] : 0;
        if (e[2 + i] != p) return false;
        if (p) {
            LONG occ = 0; for (DWORD j = 0; j < n; ++j) occ += src[j] == p;
            if (*(LONG*)(ULONG_PTR)(p + 4) != lightRefs0[i] + occ) return false;
        }
    }
    (void)r;
    return true;
}
static void __fastcall hkRlPush(DWORD* self, void* edx, DWORD mesh, DWORD* lights) {
    if (g_capOn) capPrintf("T push list=%08X mesh=%08X lights=%u\n", (DWORD)(ULONG_PTR)self, mesh, (DWORD)((LONG)(lights[1] - lights[0]) >> 2));
    LONG ph = g_phase; if (ph < 0 || ph >= PH_N) ph = PH_OTHER;
    ULONG64 t0 = g_diag ? __rdtsc() : 0;
    if (!g_rlPushLive || g_rlPushOff || !g_mkTid) {
        o_rlPush(self, edx, mesh, lights);
    } else if (GetCurrentThreadId() == g_mkTid && (g_rlPushCheckLeft > 0 ? (g_rlPushCheckLeft--, true) : ((++g_rlPushTick & 511) == 0))) {
        DWORD n = (DWORD)((LONG)(lights[1] - lights[0]) >> 2);
        DWORD model = *(DWORD*)(ULONG_PTR)(mesh + 0xC4);
        DWORD* v = self;
        if (n <= 6 && (*(BYTE*)(ULONG_PTR)(model + 0x19) & 4)) v = *(BYTE*)(ULONG_PTR)(*(DWORD*)(ULONG_PTR)(model + 0xBC)) ? self + 3 : self + 6;
        if (n <= 6 && ((LONG)(v[2] - v[1]) >> 5) >= 1) {
            DWORD last0 = v[1];
            LONG meshRefs0 = *(LONG*)(ULONG_PTR)(mesh + 4), lightRefs0[6];
            const DWORD* src = (const DWORD*)(ULONG_PTR)lights[0];
            for (DWORD i = 0; i < 6; ++i) lightRefs0[i] = (i < n && src[i]) ? *(LONG*)(ULONG_PTR)(src[i] + 4) : 0;
            o_rlPush(self, edx, mesh, lights);
            if (rlPushMatches(self, mesh, lights, v, last0, meshRefs0, lightRefs0)) g_rlPushChecked++;
            else { if (!g_rlPushMismatch++) logf("rlsort: PUSH SELF-CHECK MISMATCH (lights %u) - stock push for the rest of the session.", n); g_rlPushOff = 1; }
        } else {
            o_rlPush(self, edx, mesh, lights); g_rlPushStock++;
        }
    } else if (!rlPushFast(self, mesh, lights)) {
        o_rlPush(self, edx, mesh, lights); g_rlPushStock++;
    }
    if (g_diag) g_rlPushT[ph] += (LONG64)(__rdtsc() - t0);
    PSTAT(g_rlPushN[ph]++);
}
static DWORD __fastcall hkRlErase(DWORD* v, void* edx, DWORD first, DWORD last) {
    LONG ph = g_phase; if (ph < 0 || ph >= PH_N) ph = PH_OTHER;
    ULONG64 t0 = g_diag ? __rdtsc() : 0;
    LONG els = (LONG)((last - first) >> 5);
    DWORD r;
    if (g_rlPushLive && !g_rlPushOff && g_mkTid && GetCurrentThreadId() == g_mkTid && rlEraseTailFast(v, first, last)) r = first;
    else r = o_rlErase(v, edx, first, last);
    if (g_diag) g_rlEraseT[ph] += (LONG64)(__rdtsc() - t0);
    PSTAT(g_rlEraseN[ph]++; g_rlEraseEls[ph] += els);
    return r;
}
static void __fastcall hkRlDrawGen(void* self, void* edx, DWORD effect, DWORD count) {  // 0x54A1F0 while only drawgen wants to know the mesh
    DWORD prev = g_dgMesh; g_dgMesh = (DWORD)(ULONG_PTR)self;
    o_rlDraw(self, edx, effect, count);
    g_dgMesh = prev;
}
static void __fastcall hkRlDraw(void* self, void* edx, DWORD effect, DWORD count) {     // 0x54A1F0: draw one mesh (or an instanced group) with an effect
    if (g_capOn) capMesh("draw", (DWORD)(ULONG_PTR)self, effect, count);
    LONG ph = g_phase; if (ph < 0 || ph >= PH_N) ph = PH_OTHER;
    ULONG64 t0 = __rdtsc();
    DWORD prevMesh = g_dgMesh; g_dgMesh = (DWORD)(ULONG_PTR)self;
    o_rlDraw(self, edx, effect, count);
    g_dgMesh = prevMesh;
    g_rlDrawT[ph] += (LONG64)(__rdtsc() - t0); g_rlDrawN[ph]++;
}
static void __fastcall hkRlMeshRender(void* self, void* edx, void* rinfo) {             // 0x54B500 MeshClass::Render (culling, setup, list push)
    if (g_capOn) capPrintf("T mesh-render %08X rinfo=%08X\n", (DWORD)(ULONG_PTR)self, (DWORD)(ULONG_PTR)rinfo);
    LONG ph = g_phase; if (ph < 0 || ph >= PH_N) ph = PH_OTHER;
    ULONG64 t0 = __rdtsc();
    o_rlMeshRender(self, edx, rinfo);
    g_rlMeshT[ph] += (LONG64)(__rdtsc() - t0); g_rlMeshN[ph]++;
}

// start-up test: the stock sort (unpatched) and the replacement on the same synthetic lists must give identical bytes
struct RlFakeObj { DWORD vt; LONG refs; BYTE pad[0xC4 - 8]; DWORD model; BYTE pad2[0x310 - 0xC8]; DWORD inst; };
static volatile LONG g_rlFakeReleased = 0;
static void __fastcall rlFakeDelete(void*, void*) { g_rlFakeReleased++; }
static bool rlSelfTest(double* stockMs, double* fastMs, int* lists, int* heapFalls) {
    static DWORD fakeVt[4] = { 0, 0, 0, 0 };
    fakeVt[0] = (DWORD)(ULONG_PTR)&rlFakeDelete;
    const int kObj = 512, kMax = 6000;
    RlFakeObj* objs = (RlFakeObj*)VirtualAlloc(NULL, kObj * sizeof(RlFakeObj), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    RlEl* a = (RlEl*)VirtualAlloc(NULL, 3 * kMax * sizeof(RlEl), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!objs || !a) return false;
    RlEl* b = a + kMax, *c = a + 2 * kMax;
    DWORD seed = 12345;
    #define RLRND() (seed = seed * 1664525u + 1013904223u, seed >> 8)
    for (int i = 0; i < kObj; ++i) { objs[i].vt = (DWORD)(ULONG_PTR)fakeVt; objs[i].refs = 1000000; }
    static const int kSizes[] = { 1, 2, 3, 15, 16, 17, 18, 31, 32, 33, 64, 100, 257, 1000, 2047, 4096, 5999 };
    LONG64 tStock = 0, tFast = 0; int nl = 0; LONG hf0 = g_rlHeapFalls;
    bool good = true;
    for (int pattern = 0; pattern < 7 && good; ++pattern) {
        for (int si = 0; si < (int)(sizeof(kSizes) / sizeof(kSizes[0])) && good; ++si) {
            for (int rep = 0; rep < 1 && good; ++rep) {
                int n = kSizes[si];
                DWORD models = pattern == 0 ? 1 : pattern == 1 ? 3 : pattern == 2 ? 17 : pattern == 3 ? 400 : 64;
                for (int i = 0; i < kObj; ++i) {
                    objs[i].model = 0x1000 + (RLRND() % models) * 0x40;
                    objs[i].inst = RLRND() % (pattern == 4 ? 2 : 50);
                }
                for (int i = 0; i < n; ++i) {
                    int k;
                    if (pattern == 5) k = (i * kObj) / (n ? n : 1);                      // ascending models
                    else if (pattern == 6) k = kObj - 1 - (i * kObj) / (n ? n : 1);      // descending
                    else k = (int)(RLRND() % kObj);
                    if (pattern >= 5) objs[k].model = 0x1000 + (DWORD)k * 0x10;
                    a[i].w[0] = (DWORD)(ULONG_PTR)&objs[k];
                    a[i].w[1] = (DWORD)i;
                    for (int j = 2; j < 8; ++j) a[i].w[j] = (RLRND() & 1) ? (DWORD)(ULONG_PTR)&objs[RLRND() % kObj] : 0;
                }
                for (int pc = 0; pc < 2 && good; ++pc) {
                    tRlPred pred = (tRlPred)(ULONG_PTR)(pc ? kRlLessModelInst : kRlLessModel);
                    memcpy(b, a, n * sizeof(RlEl)); memcpy(c, a, n * sizeof(RlEl));
                    LONG64 t0 = qpcNow();
                    o_rlSort(a, a + n, pred);                                           // trampoline = stock code
                    LONG64 t1 = qpcNow();
                    rlFastSort(b, b + n, pred);                                          // inlined comparator
                    LONG64 t2 = qpcNow();
                    RlLessCall call = { pred };                                          // comparator called through its pointer
                    if (n) rlSortWith(c, c + n, call, pred);
                    tStock += t1 - t0; tFast += t2 - t1; ++nl;
                    if (memcmp(a, b, n * sizeof(RlEl)) || memcmp(a, c, n * sizeof(RlEl))) { good = false; logf("rlsort: start-up test differs (pattern %d, n %d, comparator %d).", pattern, n, pc); }
                    for (int i = 0; i < kObj && good; ++i) if (objs[i].refs != 1000000) { good = false; logf("rlsort: start-up test reference counts moved (pattern %d, n %d).", pattern, n); }
                }
            }
        }
    }
    #undef RLRND
    if (g_rlFakeReleased) { good = false; logf("rlsort: start-up test released an object."); }
    *stockMs = (double)tStock * 1000.0 / (double)g_pqpf.QuadPart;
    *fastMs = (double)tFast * 1000.0 / (double)g_pqpf.QuadPart;
    *lists = nl; *heapFalls = (int)(g_rlHeapFalls - hf0);
    VirtualFree(objs, 0, MEM_RELEASE); VirtualFree(a, 0, MEM_RELEASE);
    return good;
}
static void installRlSort() {
    static const BYTE kSort[]  = {0x56,0x8B,0x74,0x24,0x08,0x57,0x8B,0x7C,0x24,0x10,0x3B,0xF7,0x74,0x32};
    static const BYTE kFlush[] = {0x56,0x8B,0xF1,0x8B,0x06,0x3B,0x46,0x04,0x75,0x10};
    static const BYTE kPush[]  = {0xB8,0xEB,0xBF,0xB7,0x00,0xE8,0xD9,0x8B,0x4C,0x00};
    static const BYTE kHeap[]  = {0xFF,0x74,0x24,0x10,0x6A,0x00,0xFF,0x74};
    static const BYTE kErase[] = {0x55,0x8B,0xEC,0x56,0x57,0x8D,0x45,0x0B,0x50,0xFF,0x75,0x08};
    static const BYTE kDraw[]  = {0x6A,0xFF,0x68,0x58,0xA9,0xB7,0x00,0x64,0xA1,0x00,0x00,0x00};
    static const BYTE kMesh[]  = {0x83,0xEC,0x14,0x53,0x55,0x56,0x8B,0xF1,0x8B,0x06,0x57,0xFF};
    static const BYTE kDtor[]  = {0x8B,0x09,0x85,0xC9,0x74,0x09,0xFF,0x49,0x04,0x75,0x04,0x8B,0x01,0xFF,0x20,0xC3};
    static const BYTE kLess[]  = {0x8B,0x44,0x24,0x04,0x8B,0x00,0x8B,0x4C,0x24,0x08,0x8B,0x80,0xC4,0x00,0x00,0x00,0x8B,0x09,0x3B,0x81,0xC4,0x00,0x00,0x00,0x1B,0xC0,0xF7,0xD8,0xC3};
    static const BYTE kLess2[] = {0x8B,0x44,0x24,0x04,0x8B,0x4C,0x24,0x08,0x8B,0x00,0x8B,0x09,0x8B,0x90,0xC4,0x00,0x00,0x00,0x56,0x8B,0xB1,0xC4,0x00,0x00,0x00,0x3B,0xD6,0x75,0x0C,0x8B,0x80,0x10,0x03,0x00,0x00,0x3B,0x81,0x10,0x03,0x00,0x00,0x1B,0xC0,0xF7,0xD8,0x5E,0xC3};
    __try {
        if (memcmp((void*)0x005740D0, kSort, sizeof(kSort)) || memcmp((void*)0x00574406, kFlush, sizeof(kFlush)) || memcmp((void*)0x0057430D, kPush, sizeof(kPush)) ||
            memcmp((void*)(ULONG_PTR)kRlHeap, kHeap, sizeof(kHeap)) || memcmp((void*)(ULONG_PTR)kRlLessModel, kLess, sizeof(kLess)) || memcmp((void*)(ULONG_PTR)kRlLessModelInst, kLess2, sizeof(kLess2)) ||
            memcmp((void*)0x00573816, kErase, sizeof(kErase)) || memcmp((void*)0x0054A1F0, kDraw, sizeof(kDraw)) || memcmp((void*)0x0054B500, kMesh, sizeof(kMesh)) ||
            memcmp((void*)0x0047AF67, kDtor, sizeof(kDtor))) {
            logf("rlsort: render list code differs - replacement OFF."); return;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { return; }
    char env[8]; env[0] = 0;
    bool timersOnly = GetEnvironmentVariableA("AOTR_RLSORT", env, sizeof(env)) && env[0] == '0';
    o_rlSort = (tRlSort)makeTrampoline((BYTE*)0x005740D0, 5);           // push esi; mov esi, [esp+8]
    o_rlFlush = (tRlFlush)makeTrampoline((BYTE*)0x00574406, 5);         // push esi; mov esi, ecx; mov eax, [esi]
    o_rlPush = (tRlPush)makeTrampoline((BYTE*)0x0057430D, 5);           // mov eax, imm32 (the next instruction is a relative call)
    o_rlErase = (tRlErase)makeTrampoline((BYTE*)0x00573816, 5);         // push ebp; mov ebp, esp; push esi; push edi
    o_rlDraw = (tRlDraw)makeTrampoline((BYTE*)0x0054A1F0, 7);           // push -1; push imm32
    o_rlMeshRender = (tRlMeshRender)makeTrampoline((BYTE*)0x0054B500, 5); // sub esp, 14h; push ebx; push ebp
    if (!o_rlSort || !o_rlFlush || !o_rlPush || !o_rlErase || !o_rlDraw || !o_rlMeshRender) { logf("rlsort: alloc failed - OFF."); return; }
    double ms0 = 0, ms1 = 0; int nl = 0, hf = 0;
    bool ok = false;
    __try { ok = rlSelfTest(&ms0, &ms1, &nl, &hf); } __except (EXCEPTION_EXECUTE_HANDLER) { ok = false; logf("rlsort: start-up test faulted."); }
    char s0[32], s1[32];
    sprintf_s(s0, "%.2f", ms0); sprintf_s(s1, "%.2f", ms1);
    HANDLE fz[256]; int nf = 0;
    suspendOthers(fz, &nf, 256);
    patchJmp((BYTE*)0x005740D0, (void*)&hkRlSort, 5);
    patchJmp((BYTE*)0x00574406, (void*)&hkRlFlush, 5);
    patchJmp((BYTE*)0x0057430D, (void*)&hkRlPush, 5);
    patchJmp((BYTE*)0x00573816, (void*)&hkRlErase, 5);
    if (g_diag) patchJmp((BYTE*)0x0054A1F0, (void*)&hkRlDraw, 7);              // measurement only (~7k calls a frame)
    else if (g_dgOn) patchJmp((BYTE*)0x0054A1F0, (void*)&hkRlDrawGen, 7);      // drawgen needs the mesh of each draw
    if (g_diag) patchJmp((BYTE*)0x0054B500, (void*)&hkRlMeshRender, 5);        // measurement only (~8k calls a frame)
    resumeAll(fz, nf);
    g_rlLive = ok && !timersOnly;
    g_rlPushLive = ok && !timersOnly && !(GetEnvironmentVariableA("AOTR_RLPUSH", env, sizeof(env)) && env[0] == '0');
    logf("rlsort: start-up test %s on %d lists (stock %s ms, replacement %s ms, heap fallbacks %d) - render list sorts %s; list push %s, list clear %s; mesh render and draw timed.",
         ok ? "identical" : "FAILED", nl, s0, s1, hf, g_rlLive ? "replaced (self-checked)" : (timersOnly ? "stock (AOTR_RLSORT=0)" : "stock"),
         g_rlPushLive ? "in place (self-checked)" : "stock", g_rlPushLive ? "in place" : "stock");
}
static void rlReport(LONG f) {
    if (f <= 0 || !o_rlSort) return;
    static LONG lS[PH_N], lE[PH_N], lP[PH_N], lF[PH_N], lChk = 0; static LONG64 lST[PH_N], lPT[PH_N], lFT[PH_N], lCF = 0, lCS = 0;
    char ln[900]; int p = 0;
    p += wsprintfA(ln + p, "rt: rlsort %s |", !g_rlLive ? "stock" : g_rlOff ? "OFF" : (g_rlCheckLeft > 0 ? "checking" : "live"));
    for (int ph = 0; ph < PH_N; ++ph) {
        LONG s = g_rlSorts[ph] - lS[ph], e = g_rlEls[ph] - lE[ph], pn = g_rlPushN[ph] - lP[ph], fn = g_rlFlushN[ph] - lF[ph];
        LONG64 st = rd64(&g_rlSortT[ph]) - lST[ph], pt = rd64(&g_rlPushT[ph]) - lPT[ph], ft = rd64(&g_rlFlushT[ph]) - lFT[ph];
        lS[ph] += s; lE[ph] += e; lP[ph] += pn; lF[ph] += fn; lST[ph] += st; lPT[ph] += pt; lFT[ph] += ft;
        if (!s && !pn && !fn) continue;
        LONG64 ptq = g_tscPerQpc > 0 ? (LONG64)((double)pt / g_tscPerQpc) : 0;
        char a1[16], a2[16], a3[16], a4[16], a5[16], a6[16], a7[16];
        p += wsprintfA(ln + p, " %s: sorts/f %s elements/f %s sort %s ms/f, pushes/f %s push %s ms/f, flushes/f %s flush %s ms/f |", kPhaseName[ph],
                       perStr(s, f, a1), perStr(e, f, a2), msStr(st, f, a3), perStr(pn, f, a4), msStr(ptq, f, a5), perStr(fn, f, a6), msStr(ft, f, a7));
        if (p > 700) break;
    }
    LONG chk = g_rlChecks - lChk; LONG64 cf = rd64(&g_rlCheckFastT) - lCF, cs = rd64(&g_rlCheckStockT) - lCS;
    lChk += chk; lCF += cf; lCS += cs;
    char c1[32]; c1[0] = 0;
    if (chk > 0 && cf > 0) sprintf_s(c1, "%.1fx", (double)cs / (double)cf);
    p += wsprintfA(ln + p, " checked %d (stock/replacement time %s) mismatches %d faults %d heap-fallbacks %d", (int)chk, c1[0] ? c1 : "-", (int)g_rlMismatch, (int)g_rlFaults, (int)g_rlHeapFalls);
    logf("%s", ln);
    {
        static LONG lEN[PH_N], lEE[PH_N], lDN[PH_N], lMN[PH_N], lPC = 0, lPSt = 0; static LONG64 lET[PH_N], lDT[PH_N], lMT[PH_N];
        char l2[900]; int q = 0;
        q += wsprintfA(l2 + q, "rt: rlpush %s checked %d mismatches %d stock-path %d |", !g_rlPushLive ? "stock" : g_rlPushOff ? "OFF" : (g_rlPushCheckLeft > 0 ? "checking" : "live"),
                       (int)(g_rlPushChecked - lPC), (int)g_rlPushMismatch, (int)(g_rlPushStock - lPSt));
        lPC = g_rlPushChecked; lPSt = g_rlPushStock;
        for (int ph = 0; ph < PH_N; ++ph) {
            LONG en = g_rlEraseN[ph] - lEN[ph], ee = g_rlEraseEls[ph] - lEE[ph], dn = g_rlDrawN[ph] - lDN[ph], mn = g_rlMeshN[ph] - lMN[ph];
            LONG64 et = rd64(&g_rlEraseT[ph]) - lET[ph], dt = rd64(&g_rlDrawT[ph]) - lDT[ph], mt = rd64(&g_rlMeshT[ph]) - lMT[ph];
            lEN[ph] += en; lEE[ph] += ee; lDN[ph] += dn; lMN[ph] += mn; lET[ph] += et; lDT[ph] += dt; lMT[ph] += mt;
            if (!en && !dn && !mn) continue;
            double k = g_tscPerQpc > 0 ? 1.0 / g_tscPerQpc : 0;
            char b1[16], b2[16], b3[16], b4[16], b5[16], b6[16], b7[16];
            q += wsprintfA(l2 + q, " %s: clear elements/f %s clear %s ms/f, draws/f %s draw %s ms/f, mesh renders/f %s mesh render %s ms/f |", kPhaseName[ph],
                           perStr(ee, f, b1), msStr((LONG64)(et * k), f, b2), perStr(dn, f, b3), msStr((LONG64)(dt * k), f, b4), perStr(mn, f, b5), msStr((LONG64)(mt * k), f, b6));
            (void)b7;
            if (q > 700) break;
        }
        logf("%s", l2);
    }
}
