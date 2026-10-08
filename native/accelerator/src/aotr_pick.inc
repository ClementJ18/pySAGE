// ================================================================ mouse pick (W3DView scene ray cast)
// One chain is the largest single item left in a battle frame: the view's "which drawable is under this screen
// point" query (0x48AB28, from GameClient\W3DView.cpp) -> scene cast ray 0x471A5B -> HLodClass::Cast_Ray
// 0x59C680 -> MeshClass::Cast_Ray 0x56C600, about 4.4% of all game-thread samples, ~2 ms of a 45 ms frame.
//
// This measures it - calls a frame, their arguments, their callers and their cost - and answers a repeat of a
// query already made in the same frame with the same arguments from the previous result. That shortcut only
// turns on after the same arguments have been recomputed and matched enough times to show the answer does not
// change within a frame, one repeat in 32 keeps being recomputed and compared afterwards, and a single
// difference turns it off for the rest of the session. Nothing about the query is changed when it does run.
// Kill switch: AOTR_PICK=0 (measure only, never answer from the memo).

typedef void* (__fastcall* tPick)(void*, void*, const DWORD*, DWORD, DWORD);
static tPick o_pick = NULL;
static volatile LONG g_pkAllow = 1;                    // memo allowed at all (AOTR_PICK)
static volatile LONG g_pkLive = 0;                     // memo answering repeats
static volatile LONG g_pkKill = 0;                     // a recomputed repeat differed: never again
static volatile LONG g_pkN = 0, g_pkRep = 0, g_pkServed = 0, g_pkChecked = 0, g_pkMism = 0, g_pkFaults = 0;
static volatile LONG64 g_pkTicks = 0, g_pkSaved = 0;
static LONG g_pkCheckLeft = 400;                       // clean repeats needed before the memo answers
static LONG g_pkNPhase[PH_N];                          // calls per phase
struct PkCaller { DWORD ra; LONG n; };
static PkCaller g_pkRA[12];
static struct { void* self; DWORD x, y, b, f; void* res; LONG frame; LONG64 cost; LONG valid; } g_pkM;

static void pkNoteCaller(DWORD ra) {
    for (int i = 0; i < 12; ++i) {
        if (g_pkRA[i].ra == ra) { g_pkRA[i].n++; return; }
        if (!g_pkRA[i].ra) { g_pkRA[i].ra = ra; g_pkRA[i].n = 1; return; }
    }
}
static void* __fastcall hkPick(void* self, void* edx, const DWORD* pt, DWORD b, DWORD flags) {
    if (__readfsdword(0x24) != g_mkTid || !g_mkTid) return o_pick(self, edx, pt, b, flags);
    pkNoteCaller((DWORD)(ULONG_PTR)_ReturnAddress());
    LONG frame = g_mkFrames, ph = g_phase; if (ph < 0 || ph >= PH_N) ph = PH_OTHER;
    DWORD x = 0, y = 0; LONG haveArgs = 0;
    __try { if (pt) { x = pt[0]; y = pt[1]; haveArgs = 1; } } __except (EXCEPTION_EXECUTE_HANDLER) { haveArgs = 0; g_pkFaults++; }
    LONG same = haveArgs && g_pkM.valid && g_pkM.frame == frame && g_pkM.self == self &&
                g_pkM.x == x && g_pkM.y == y && g_pkM.b == b && g_pkM.f == flags;
    if (same) {
        LONG rep = InterlockedIncrement(&g_pkRep);
        if (g_pkAllow && g_pkLive && !g_pkKill && (rep & 31) != 0) {
            InterlockedIncrement(&g_pkServed);
            g_pkSaved += g_pkM.cost;
            return g_pkM.res;
        }
    }
    LONG64 t0 = qpcNow();
    void* r = o_pick(self, edx, pt, b, flags);
    LONG64 dt = qpcNow() - t0;
    g_pkTicks += dt; InterlockedIncrement(&g_pkN); g_pkNPhase[ph]++;
    if (same) {
        InterlockedIncrement(&g_pkChecked);
        if (r != g_pkM.res) {
            InterlockedIncrement(&g_pkMism);
            g_pkKill = 1; g_pkLive = 0;
            logf("pick: a repeated query in one frame returned a different result - memo OFF for this session (after %d checks).", (int)g_pkChecked);
        } else if (!g_pkLive && g_pkCheckLeft > 0 && --g_pkCheckLeft == 0 && g_pkAllow) {
            g_pkLive = 1;
            logf("pick: %d repeated queries recomputed, all identical - repeats in the same frame now answered from the previous result (1 in 32 still recomputed and compared).", (int)g_pkChecked);
        }
    }
    if (haveArgs) { g_pkM.self = self; g_pkM.x = x; g_pkM.y = y; g_pkM.b = b; g_pkM.f = flags; g_pkM.res = r; g_pkM.frame = frame; g_pkM.cost = dt; g_pkM.valid = 1; }
    else g_pkM.valid = 0;
    return r;
}
// ---------------------------------------------------------------- brute-force mesh cast: skip meshes the ray cannot reach
// The scene cast hands every object whose bounding SPHERE the ray crosses to HLodClass::Cast_Ray, which casts against
// every sub-mesh of the current LOD. A mesh without an AABTree (most unit meshes) goes to the brute-force loop
// 0x56C600: for EVERY triangle it builds the face normal, normalizes it (the InvSqrt that is 1.2% of a battle frame
// on its own) and calls Collide. Nothing tests the mesh's own bounding box first, so a ray that passes a unit's
// sphere pays for every triangle of its sword, shield, cape and body even when it misses all of them.
//
// The ray the loop tests against is at test+0xC (P0) / test+0x18 (P1), in whatever space the vertices it is about to
// read are in: [[model+0x30]+0xC] + 12 * index, indices three WORDs a triangle at [[model+0x2C]+0xC]. (v21 used the
// model's stored box at +0x60/+0x6C; that is only valid for rigid meshes - for skinned ones the loop runs on
// deformed vertices in another space, and the self-proof caught it after ~1,900 checks without ever having skipped
// anything.) So the bounds are taken from exactly those vertices, which costs a twentieth of the loop. A segment
// that misses the box of all the triangles' vertices misses every triangle, so the loop can only return "no hit"
// and leave the result untouched - which is what is returned here without running it.
// The box is grown by a generous margin so rounding can only make this test say "may hit". It proves itself
// before it is trusted: for the first 3000 would-be skips the stock loop still runs and must return 0 with the
// test and result bytes unchanged, 1 skip in 16 stays checked for good, and one violation turns it off.
// Kill switch: AOTR_PICKBOX=0.
typedef BYTE (__fastcall* tBfCast)(void*, void*, DWORD*);
static tBfCast o_bfCast = NULL;
static volatile LONG g_pbAllow = 1, g_pbLive = 0, g_pbKill = 0;
static volatile LONG g_pbCasts = 0, g_pbMiss = 0, g_pbSkipped = 0, g_pbChecked = 0, g_pbBad = 0, g_pbOdd = 0;
static volatile LONG64 g_pbPolys = 0, g_pbPolysSkipped = 0, g_pbTicks = 0, g_pbTicksMiss = 0;
static LONG g_pbCheckLeft = 3000, g_pbTick = 0;

static __forceinline double pbAbs(double v) { return v < 0 ? -v : v; }
static __forceinline bool pbFinite(float v) { DWORD b; memcpy(&b, &v, 4); return (b & 0x7F800000u) != 0x7F800000u; }
// true only when the segment P0->P1 certainly stays outside the box grown by the margin
static bool pbSegmentMissesBox(const float* mn, const float* mx, const float* p0, const float* p1) {
    double scale = 1.0;
    for (int i = 0; i < 3; ++i) {
        if (!pbFinite(mn[i]) || !pbFinite(mx[i]) || !pbFinite(p0[i]) || !pbFinite(p1[i]) || mn[i] > mx[i]) return false;
        double a = pbAbs((double)mn[i]), b = pbAbs((double)mx[i]), c = pbAbs((double)p0[i]), d = pbAbs((double)p1[i]);
        if (a > scale) scale = a; if (b > scale) scale = b; if (c > scale) scale = c; if (d > scale) scale = d;
    }
    double eps = 0.02 + 2e-3 * scale;
    double t0 = -0.02, t1 = 1.02;                        // a little more than the whole segment
    for (int i = 0; i < 3; ++i) {
        double lo = (double)mn[i] - eps, hi = (double)mx[i] + eps, o = (double)p0[i], dir = (double)p1[i] - o;
        if (pbAbs(dir) < 1e-12) { if (o < lo || o > hi) return true; continue; }
        double ta = (lo - o) / dir, tb = (hi - o) / dir;
        if (ta > tb) { double t = ta; ta = tb; tb = t; }
        if (ta > t0) t0 = ta;
        if (tb < t1) t1 = tb;
        if (t0 > t1) return true;
    }
    return false;
}
// bounds of every vertex the brute-force loop will read (4-wide loads: the 4th lane is the next vertex's x, ignored)
static bool pbVertexBounds(const BYTE* model, LONG polys, float* mn, float* mx) {
    DWORD ih = *(DWORD*)(model + 0x2C), vh = *(DWORD*)(model + 0x30);
    if (!ih || !vh) return false;
    const WORD* idx = *(const WORD**)(ULONG_PTR)(ih + 0xC); const float* v = *(const float**)(ULONG_PTR)(vh + 0xC);
    if (!idx || !v) return false;
    __m128 lo = _mm_loadu_ps(v + 3 * idx[0]), hi = lo;
    for (LONG i = 1, n = polys * 3; i < n; ++i) { __m128 q = _mm_loadu_ps(v + 3 * idx[i]); lo = _mm_min_ps(lo, q); hi = _mm_max_ps(hi, q); }
    float a[4], b[4]; _mm_storeu_ps(a, lo); _mm_storeu_ps(b, hi);
    mn[0] = a[0]; mn[1] = a[1]; mn[2] = a[2]; mx[0] = b[0]; mx[1] = b[1]; mx[2] = b[2];
    return true;
}
static BYTE __fastcall hkBfCast(void* model, void* edx, DWORD* test) {
    if (__readfsdword(0x24) != g_mkTid || !g_mkTid || g_pbKill || !test) return o_bfCast(model, edx, test);
    LONG polys = *(LONG*)((BYTE*)model + 0x24);
    InterlockedIncrement(&g_pbCasts); g_pbPolys += polys;
    bool miss = false;
    if (polys >= 12 && polys < 20000) {
        __try { float mn[3], mx[3]; miss = pbVertexBounds((const BYTE*)model, polys, mn, mx) && pbSegmentMissesBox(mn, mx, (const float*)(test + 3), (const float*)(test + 6)); }
        __except (EXCEPTION_EXECUTE_HANDLER) { miss = false; g_pbOdd++; }
    }
    if (!miss) { ULONG64 t = __rdtsc(); BYTE r = o_bfCast(model, edx, test); g_pbTicks += (LONG64)(__rdtsc() - t); return r; }
    InterlockedIncrement(&g_pbMiss);
    bool check = !g_pbLive || !g_pbAllow || ((++g_pbTick & 15) == 0);
    if (!check) { InterlockedIncrement(&g_pbSkipped); g_pbPolysSkipped += polys; return 0; }
    // prove it: the stock loop must find nothing and change nothing
    BYTE tb[0x44], rb[0x28]; DWORD* res = NULL; bool haveRes = false;
    memcpy(tb, test, sizeof(tb));
    __try { res = (DWORD*)(ULONG_PTR)test[0]; if (res) { memcpy(rb, res, sizeof(rb)); haveRes = true; } } __except (EXCEPTION_EXECUTE_HANDLER) { haveRes = false; }
    ULONG64 t = __rdtsc();
    BYTE r = o_bfCast(model, edx, test);
    LONG64 dt = (LONG64)(__rdtsc() - t);
    g_pbTicks += dt; g_pbTicksMiss += dt;
    InterlockedIncrement(&g_pbChecked);
    bool same = r == 0 && !memcmp(tb, test, sizeof(tb)) && (!haveRes || !memcmp(rb, res, sizeof(rb)));
    if (!same) {
        if (!g_pbBad++) logf("pick: box pre-test VIOLATION (stock cast returned %d or changed the test; model %08X, %d polygons) - pre-test OFF for this session.", (int)r, (DWORD)(ULONG_PTR)model, (int)polys);
        g_pbKill = 1; g_pbLive = 0;
    } else if (!g_pbLive && g_pbAllow && g_pbCheckLeft > 0 && --g_pbCheckLeft == 0) {
        g_pbLive = 1;
        logf("pick: %d brute-force mesh casts whose box the ray misses all found nothing and changed nothing - such casts are now skipped (1 in 16 still run and compared).", (int)g_pbChecked);
    }
    return r;
}
static void installPick() {
    static const BYTE kPick[] = { 0xB8, 0xDD, 0x3D, 0xB7, 0x00, 0xE8 };            // mov eax, offset handler; call __SEH_prolog
    __try { if (memcmp((void*)0x0048AB28, kPick, sizeof(kPick))) { logf("pick: view pick code differs - measurement OFF."); return; } }
    __except (EXCEPTION_EXECUTE_HANDLER) { return; }
    char env[8]; env[0] = 0;
    if (GetEnvironmentVariableA("AOTR_PICK", env, sizeof(env)) && env[0] == '0') g_pkAllow = 0;
    o_pick = (tPick)makeTrampoline((BYTE*)0x0048AB28, 5);
    if (!o_pick) { logf("pick: trampoline alloc failed - OFF."); return; }
    static const BYTE kBf[] = { 0x83, 0xEC, 0x18, 0x53, 0x55, 0x8B, 0xE9, 0x8B, 0x45, 0x30 };   // sub esp,18h; push ebx; push ebp; mov ebp,ecx; mov eax,[ebp+30h]
    static const BYTE kBfTail[] = { 0xE9 };                                                     // 0x56CFCD: jmp 0x56C600 (the no-AABTree path)
    bool bfOk = false;
    __try { bfOk = !memcmp((void*)0x0056C600, kBf, sizeof(kBf)) && !memcmp((void*)0x0056CFCD, kBfTail, 1); } __except (EXCEPTION_EXECUTE_HANDLER) { bfOk = false; }
    if (bfOk) { o_bfCast = (tBfCast)makeTrampoline((BYTE*)0x0056C600, 5); if (!o_bfCast) bfOk = false; }
    if (GetEnvironmentVariableA("AOTR_PICKBOX", env, sizeof(env)) && env[0] == '0') g_pbAllow = 0;
    HANDLE fz[256]; int nf = 0;
    suspendOthers(fz, &nf, 256);
    patchJmp((BYTE*)0x0048AB28, (void*)&hkPick, 5);
    if (bfOk) patchJmp((BYTE*)0x0056C600, (void*)&hkBfCast, 5);
    resumeAll(fz, nf);
    logf("pick: brute-force mesh cast 0x56C600 %s.", !bfOk ? "differs - box pre-test OFF" : (g_pbAllow ? "hooked - casts whose box the ray misses are skipped once 3000 of them have been proven empty" : "hooked, measurement only (AOTR_PICKBOX=0)"));
    logf("pick: view scene pick 0x48AB28 hooked - timed per frame%s.", g_pkAllow ? "; repeats in one frame answered from the previous result once 400 recomputed repeats have matched" : " (AOTR_PICK=0: measurement only)");
}
static void pickReport(LONG f) {
    if (f <= 0 || !o_pick) return;
    static LONG lN = 0, lRep = 0, lSrv = 0, lChk = 0; static LONG64 lT = 0, lS = 0;
    LONG n = g_pkN, rep = g_pkRep, srv = g_pkServed, chk = g_pkChecked;
    LONG64 t = rd64(&g_pkTicks), s = rd64(&g_pkSaved);
    char a1[16], a2[16], a3[16], a4[16], a5[16];
    char ln[900]; int q = 0;
    q += wsprintfA(ln + q, "rt: pick %s | queries/f %s (%s ms/f) repeats/f %s answered/f %s (%s ms/f saved) checked %d mismatches %d faults %d |",
                   g_pkKill ? "OFF (mismatch)" : (!g_pkAllow ? "measure only" : (g_pkLive ? "memo live" : "checking")),
                   perStr(n - lN, f, a1), msStr(t - lT, f, a2), perStr(rep - lRep, f, a3), perStr(srv - lSrv, f, a4), msStr(s - lS, f, a5), (int)(chk - lChk), (int)g_pkMism, (int)g_pkFaults);
    lN = n; lRep = rep; lSrv = srv; lChk = chk; lT = t; lS = s;
    q += wsprintfA(ln + q, " by phase:");
    for (int p = 0; p < PH_N; ++p) {
        static LONG lP[PH_N]; LONG v = g_pkNPhase[p]; LONG d = v - lP[p]; lP[p] = v;
        if (!d) continue;
        char b1[16]; q += wsprintfA(ln + q, " %s %s", kPhaseName[p], perStr(d, f, b1));
    }
    q += wsprintfA(ln + q, " | callers:");
    for (int i = 0; i < 12 && g_pkRA[i].ra; ++i) {
        static LONG lC[12]; LONG d = g_pkRA[i].n - lC[i]; lC[i] = g_pkRA[i].n;
        if (!d) continue;
        char b1[16]; q += wsprintfA(ln + q, " %08X %s", g_pkRA[i].ra, perStr(d, f, b1));
        if (q > 800) break;
    }
    logf("%s", ln);
    if (o_bfCast) {
        static LONG lC = 0, lM = 0, lS = 0, lK = 0; static LONG64 lP = 0, lPS = 0, lT = 0, lTM = 0;
        LONG c = g_pbCasts, m = g_pbMiss, sk = g_pbSkipped, ck = g_pbChecked;
        LONG64 po = rd64(&g_pbPolys), ps = rd64(&g_pbPolysSkipped), tt = rd64(&g_pbTicks), tm = rd64(&g_pbTicksMiss);
        LONG64 msAll = g_tscPerQpc > 0 ? (LONG64)((double)(tt - lT) / g_tscPerQpc) : 0, msMiss = g_tscPerQpc > 0 ? (LONG64)((double)(tm - lTM) / g_tscPerQpc) : 0;
        char b1[16], b2[16], b3[16], b4[16], b5[16], b6[16], b7[16];
        logf("rt: pick box %s | brute-force casts/f %s (%s triangles/f, %s ms/f run) box-missed/f %s skipped/f %s (%s triangles/f) | still run for proof %d (%s ms/f) violations %d odd %d",
             g_pbKill ? "OFF (violation)" : (!g_pbAllow ? "measure only" : (g_pbLive ? "live" : "proving")),
             perStr(c - lC, f, b1), perStr((LONG)(po - lP), f, b2), msStr(msAll, f, b3), perStr(m - lM, f, b4), perStr(sk - lS, f, b5), perStr((LONG)(ps - lPS), f, b6),
             (int)(ck - lK), msStr(msMiss, f, b7), (int)g_pbBad, (int)g_pbOdd);
        lC = c; lM = m; lS = sk; lK = ck; lP = po; lPS = ps; lT = tt; lTM = tm;
    }
    {   // name what the view's draw calls on TheTerrainLogic (slot 0x20) once it exists
        static bool named = false;
        if (!named) __try {
            DWORD tl = *(DWORD*)0x00DE4690;
            if (tl) { DWORD vt = *(DWORD*)(ULONG_PTR)tl; logf("pick: TheTerrainLogic %08X vtable game.dat+%06X slot20 game.dat+%06X slot28 game.dat+%06X", tl, vt - 0x400000, *(DWORD*)(ULONG_PTR)(vt + 0x20) - 0x400000, *(DWORD*)(ULONG_PTR)(vt + 0x28) - 0x400000); named = true; }
            DWORD m = *(DWORD*)0x00DE3744;                                        // the unnamed manager W3DDisplay::draw updates every frame (1.2 ms/f)
            if (tl && m) { DWORD vt = *(DWORD*)(ULONG_PTR)m; logf("pick: object at DE3744 %08X vtable game.dat+%06X update(slot28) game.dat+%06X slot2C game.dat+%06X slot30 game.dat+%06X", m, vt - 0x400000,
                           *(DWORD*)(ULONG_PTR)(vt + 0x28) - 0x400000, *(DWORD*)(ULONG_PTR)(vt + 0x2C) - 0x400000, *(DWORD*)(ULONG_PTR)(vt + 0x30) - 0x400000); }
        } __except (EXCEPTION_EXECUTE_HANDLER) { named = true; }
    }
}
