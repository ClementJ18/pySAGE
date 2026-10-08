// ================================================================ engine MutexClass: kernel mutex -> user-mode recursive lock
// The engine's MutexClass (vtable 0xBD7674: ctor 0x44087E -> CreateMutexA, Lock 0x440858 -> WaitForSingleObject,
// Unlock 0x4408AC -> ReleaseMutex, handle closed by the shared base destructor 0x44083B) guards a few task lists that
// the game thread polls hundreds of times a frame. Every Lock/Unlock pair is two system calls: the v19 battle profile
// has 0.9% of the game thread in ZwWaitForSingleObject and 0.5% in NtReleaseMutant under 0x440858 (~0.6 ms/frame).
//
// A mutex that is created without a name cannot be shared with another process, and the engine reads the handle
// only in those three functions, so such an instance can be backed by a CRITICAL_SECTION with the same behaviour:
// recursive for its owner, Lock(timeout) returns false when the time runs out, Unlock by a non-owner fails. Only
// instances whose construction this code saw are converted (unnamed, not initially owned); anything created before
// the hooks went in, or with a name, keeps its kernel mutex - an instance never mixes the two. The kernel object is
// still created and simply never used. Kill switch: AOTR_MUTEXCS=0.
//
// v27: the three instances the game has are all created before this DLL arrives (v23 log: "made 0"), so nothing was ever
// converted, and the v26 profile still has ~1.1% of the game thread in ZwWaitForSingleObject / NtReleaseMutant under
// the audio manager's mutex (70-250 lock/unlock pairs a frame). An EXISTING instance is adopted when it is provably
// idle: the game thread has just released its last level of it (its own recursion depth, counted here since the hooks
// went in, is zero), no thread is inside the kernel lock path (counted), the hooks have been in for 10 s (nothing
// taken before them can still be held), and a zero-timeout wait on the kernel mutex succeeds - so nobody holds it.
// While that test wait is held the instance gets its user-mode lock and is published; the decision "kernel or
// user-mode path" is made under one small lock, so no thread can slip into the kernel path between the test and the
// publication. From then on the kernel mutex is simply never touched again. AOTR_MUTEXADOPT=0 keeps v26 behaviour.
//
// Also here: two counters for the "could logic run beside rendering" question - how often render-object transforms
// are written in each phase of the frame (RenderObjClass::Set_Transform 0x53B260).

typedef BYTE  (__fastcall* tMxLock)(void*, void*, DWORD);
typedef BYTE  (__fastcall* tMxUnlock)(void*, void*);
typedef void* (__fastcall* tMxCtor)(void*, void*, DWORD, DWORD, DWORD);
typedef void  (__fastcall* tMxBaseDtor)(void*, void*);
typedef void  (__fastcall* tSetTransform)(void*, void*, const void*);
static tMxLock o_mxLock = NULL; static tMxUnlock o_mxUnlock = NULL; static tMxCtor o_mxCtor = NULL; static tMxBaseDtor o_mxDtor = NULL;
static tSetTransform o_setTransform = NULL;

#define MX_N 32
struct MxEnt { volatile DWORD key; CRITICAL_SECTION cs; };
static MxEnt g_mx[MX_N];
static CRITICAL_SECTION g_mxReg;                           // serializes construction / destruction only
static volatile LONG g_mxOn = 1, g_mxLive = 0, g_mxLocks = 0, g_mxContended = 0, g_mxKernel = 0, g_mxTimeouts = 0, g_mxMade = 0, g_mxGone = 0;
static volatile LONG g_stN[PH_N];                          // Set_Transform calls per phase
static CRITICAL_SECTION g_mxDecide;                        // "kernel path or user-mode path" is decided under this lock
static volatile LONG g_mxInKernel = 0, g_mxAdoptOn = 1, g_mxAdopted = 0, g_mxAdoptTries = 0;
static DWORD g_mxInstallTick = 0;
struct MxDepth { DWORD self; LONG depth; };
static MxDepth g_mxDepth[8];                               // game thread only: kernel recursion depth per instance since the hooks went in
static __forceinline MxDepth* mxDepthOf(void* self) {
    DWORD k = (DWORD)(ULONG_PTR)self;
    for (int i = 0; i < 8; ++i) if (g_mxDepth[i].self == k) return &g_mxDepth[i];
    for (int i = 0; i < 8; ++i) if (!g_mxDepth[i].self) { g_mxDepth[i].self = k; g_mxDepth[i].depth = 0; return &g_mxDepth[i]; }
    return NULL;
}

static __forceinline MxEnt* mxFind(void* self) {
    DWORD k = (DWORD)(ULONG_PTR)self;
    for (int i = 0; i < MX_N; ++i) if (g_mx[i].key == k) return &g_mx[i];
    return NULL;
}
static BYTE __fastcall hkMxLock(void* self, void* edx, DWORD timeout) {
    MxEnt* e = g_mxLive ? mxFind(self) : NULL;
    if (!e && g_mxAdoptOn) {                                  // not adopted (yet): decide under the lock, so an adoption cannot happen between this look-up and the kernel wait
        EnterCriticalSection(&g_mxDecide);
        e = g_mxLive ? mxFind(self) : NULL;
        if (!e) InterlockedIncrement(&g_mxInKernel);
        LeaveCriticalSection(&g_mxDecide);
        if (!e) {
            g_mxKernel++;
            BYTE r = o_mxLock(self, edx, timeout);
            InterlockedDecrement(&g_mxInKernel);
            if (r && __readfsdword(0x24) == g_mkTid) { MxDepth* d = mxDepthOf(self); if (d) d->depth++; }
            return r;
        }
    }
    if (!e) { g_mxKernel++; return o_mxLock(self, edx, timeout); }
    g_mxLocks++;
    if (TryEnterCriticalSection(&e->cs)) return 1;
    g_mxContended++;
    if (timeout == INFINITE) { EnterCriticalSection(&e->cs); return 1; }
    DWORD t0 = GetTickCount();
    for (int spin = 0;; ++spin) {
        if (TryEnterCriticalSection(&e->cs)) return 1;
        if (GetTickCount() - t0 >= timeout) { g_mxTimeouts++; return 0; }
        if (spin < 64) YieldProcessor(); else Sleep(spin < 256 ? 0 : 1);
    }
}
static void mxTryAdopt(void* self) {                       // game thread, right after it released its last level of this kernel mutex
    if (g_mxInKernel || GetTickCount() - g_mxInstallTick < 10000) return;
    HANDLE h = *(HANDLE*)((BYTE*)self + 4);
    if (!h) return;
    g_mxAdoptTries++;
    EnterCriticalSection(&g_mxDecide);
    if (!g_mxInKernel && !mxFind(self) && WaitForSingleObject(h, 0) == WAIT_OBJECT_0) {        // nobody waits, nobody holds
        EnterCriticalSection(&g_mxReg);
        for (int i = 0; i < MX_N; ++i) if (!g_mx[i].key) {
            InitializeCriticalSectionAndSpinCount(&g_mx[i].cs, 2000);
            g_mx[i].key = (DWORD)(ULONG_PTR)self;
            InterlockedIncrement(&g_mxLive); g_mxMade++; g_mxAdopted++;
            break;
        }
        LeaveCriticalSection(&g_mxReg);
        ReleaseMutex(h);
    }
    LeaveCriticalSection(&g_mxDecide);
}
static BYTE __fastcall hkMxUnlock(void* self, void* edx) {
    MxEnt* e = g_mxLive ? mxFind(self) : NULL;
    if (!e) {
        BYTE r = o_mxUnlock(self, edx);
        if (r && g_mxAdoptOn && __readfsdword(0x24) == g_mkTid) {
            MxDepth* d = mxDepthOf(self);
            if (d) { if (d->depth > 0) d->depth--; if (d->depth == 0) mxTryAdopt(self); }
        }
        return r;
    }
    if ((DWORD)(ULONG_PTR)e->cs.OwningThread != GetCurrentThreadId()) return 0;       // ReleaseMutex by a non-owner fails
    LeaveCriticalSection(&e->cs);
    return 1;
}
static void* __fastcall hkMxCtor(void* self, void* edx, DWORD notOwned, DWORD name, DWORD attrs) {
    void* r = o_mxCtor(self, edx, notOwned, name, attrs);
    if (g_mxOn && !name && notOwned) {                       // unnamed, not initially owned by its creator
        EnterCriticalSection(&g_mxReg);
        if (!mxFind(self)) for (int i = 0; i < MX_N; ++i) if (!g_mx[i].key) {
            InitializeCriticalSectionAndSpinCount(&g_mx[i].cs, 2000);
            g_mx[i].key = (DWORD)(ULONG_PTR)self;                                   // visible to Lock only once the lock exists
            InterlockedIncrement(&g_mxLive); g_mxMade++;
            break;
        }
        LeaveCriticalSection(&g_mxReg);
    }
    return r;
}
static void __fastcall hkMxBaseDtor(void* self, void* edx) {                       // every handle-owning sync object ends here
    if (g_mxLive) {
        MxEnt* e = mxFind(self);
        if (e) { EnterCriticalSection(&g_mxReg); e->key = 0; DeleteCriticalSection(&e->cs); InterlockedDecrement(&g_mxLive); g_mxGone++; LeaveCriticalSection(&g_mxReg); }
    }
    o_mxDtor(self, edx);
}
static void __fastcall hkSetTransform(void* self, void* edx, const void* m) {
    LONG ph = g_phase; if (ph < 0 || ph >= PH_N) ph = PH_OTHER;
    if (__readfsdword(0x24) == g_mkTid) g_stN[ph]++;
    o_setTransform(self, edx, m);
}
static void installMutexCs() {
    static const BYTE kLock[]  = { 0x8B, 0x41, 0x04, 0x85, 0xC0, 0x75, 0x04, 0x32, 0xC0 };
    static const BYTE kUnl[]   = { 0x8B, 0x41, 0x04, 0x85, 0xC0, 0x74, 0x0E, 0x50, 0xFF, 0x15, 0x24, 0x02, 0xBD, 0x00 };
    static const BYTE kCtor[]  = { 0x56, 0xFF, 0x74, 0x24, 0x0C, 0x8B, 0xF1, 0x83, 0x66, 0x04, 0x00 };
    static const BYTE kDtor[]  = { 0x56, 0x8B, 0xF1, 0x8B, 0x46, 0x04 };
    static const BYTE kSetT[]  = { 0x56, 0x8B, 0xF1, 0x8B, 0x4C, 0x24, 0x08, 0x8B, 0x01, 0x89, 0x46, 0x18 };
    bool okM = false, okT = false;
    __try {
        okM = !memcmp((void*)0x00440858, kLock, sizeof(kLock)) && !memcmp((void*)0x004408AC, kUnl, sizeof(kUnl)) && !memcmp((void*)0x0044087E, kCtor, sizeof(kCtor)) &&
              !memcmp((void*)0x0044083B, kDtor, sizeof(kDtor)) && *(DWORD*)0x00BD7674 == 0x00440858 && *(DWORD*)0x00BD7678 == 0x004408AC;
        okT = !memcmp((void*)0x0053B260, kSetT, sizeof(kSetT));
    } __except (EXCEPTION_EXECUTE_HANDLER) { okM = okT = false; }
    char env[8]; env[0] = 0;
    if (GetEnvironmentVariableA("AOTR_MUTEXCS", env, sizeof(env)) && env[0] == '0') g_mxOn = 0;
    env[0] = 0;
    if (GetEnvironmentVariableA("AOTR_MUTEXADOPT", env, sizeof(env)) && env[0] == '0') g_mxAdoptOn = 0;
    if (okM && g_mxOn) {
        InitializeCriticalSection(&g_mxReg); InitializeCriticalSection(&g_mxDecide); g_mxInstallTick = GetTickCount();
        o_mxLock = (tMxLock)makeTrampoline((BYTE*)0x00440858, 5); o_mxUnlock = (tMxUnlock)makeTrampoline((BYTE*)0x004408AC, 5);
        o_mxCtor = (tMxCtor)makeTrampoline((BYTE*)0x0044087E, 5); o_mxDtor = (tMxBaseDtor)makeTrampoline((BYTE*)0x0044083B, 6);
        if (!o_mxLock || !o_mxUnlock || !o_mxCtor || !o_mxDtor) okM = false;
    }
    if (!g_diag) okT = false;                                // the per-phase Set_Transform count is measurement only (~1,500 calls a frame through a detour)
    if (okT) { o_setTransform = (tSetTransform)makeTrampoline((BYTE*)0x0053B260, 7); if (!o_setTransform) okT = false; }
    HANDLE fz[256]; int nf = 0;
    suspendOthers(fz, &nf, 256);
    if (okM && g_mxOn) {
        patchJmp((BYTE*)0x00440858, (void*)&hkMxLock, 5); patchJmp((BYTE*)0x004408AC, (void*)&hkMxUnlock, 5);
        patchJmp((BYTE*)0x0044087E, (void*)&hkMxCtor, 5); patchJmp((BYTE*)0x0044083B, (void*)&hkMxBaseDtor, 6);
    }
    if (okT) patchJmp((BYTE*)0x0053B260, (void*)&hkSetTransform, 7);
    resumeAll(fz, nf);
    logf("mutexcs: engine MutexClass %s; render-object Set_Transform %s.",
         !okM ? "code differs - kernel mutexes kept" : (g_mxOn ? "hooked - unnamed mutexes created from now on use a user-mode recursive lock" : "kept (AOTR_MUTEXCS=0)"),
         okT ? "counted per phase" : (g_diag ? "not counted (code differs)" : "not counted (AOTR_DIAG=1 turns it on)"));
}
static void mxReport(LONG f) {
    if (f <= 0) return;
    static LONG lL = 0, lC = 0, lK = 0, lSt[PH_N];
    LONG l = g_mxLocks, c = g_mxContended, k = g_mxKernel;
    char a1[16], a2[16], a3[16];
    char ln[500]; int q = 0;
    q += wsprintfA(ln + q, "rt: mutexcs user-mode mutexes %d (made %d of which adopted %d, gone %d; adoption tries %d) | locks/f %s contended/f %s | still kernel locks/f %s timeouts %d | Set_Transform per frame:",
                   (int)g_mxLive, (int)g_mxMade, (int)g_mxAdopted, (int)g_mxGone, (int)g_mxAdoptTries, perStr(l - lL, f, a1), perStr(c - lC, f, a2), perStr(k - lK, f, a3), (int)g_mxTimeouts);
    lL = l; lC = c; lK = k;
    for (int p = 0; p < PH_N; ++p) { LONG v = g_stN[p], d = v - lSt[p]; lSt[p] = v; if (!d) continue; char b[16]; q += wsprintfA(ln + q, " %s %s", kPhaseName[p], perStr(d, f, b)); }
    logf("%s", ln);
}
