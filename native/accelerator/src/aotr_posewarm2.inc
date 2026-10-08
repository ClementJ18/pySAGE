// ---------------------------------------------------------------- parallel skeleton tree updates (pose warm v2)
// The scene render (RTS3DScene vtable +0x90, 0x47177E, thiscall, rinfo, ret 4) gathers and draws the objects of the scene
// list [scene+0xF4] (circular, head at scene+0xF0, next at +4, render object = [node+0xC] - 8) for one pass: Customized_
// Render 0x46FE84 and the draw at 0x470F44 both run inside it. Drawing an animated HLod runs
// Animatable3DObj::Update_Sub_Object_Transforms (0x5A5050) on the game thread whenever its tree is invalid: ~420 per big
// battle frame, 2.1 ms, nearly all in the shadow pass. That update reads the object's transform [+0x18..+0x48), its HTree,
// animation mode and animation arguments [+0xF8..+0x120) plus shared read-only animation data, and writes the object's
// own HTree. So when a pass starts, the objects drawn in the previous frame whose trees are invalid now get that update on
// worker threads (the game thread takes jobs too and waits for all of them). Each job keeps the input words it computed
// from and puts the object's valid flag [+0xF4] back. When the stock pass reaches the update for a warmed object, the hook
// skips the recomputation only if all input words are unchanged, and sets the valid flag as the update would; any other
// case runs the stock update on the game thread. The workers run with the game thread's MXCSR and x87 control word.
// Self-check: the first 20000 warmed objects, and one in 64 after that, are recomputed by the stock update anyway and
// their whole pivot arrays compared with the warmed result; one difference turns warming off for the session.
// v16 (full warm): when every sub-object of an HLod (all LOD models and additional models) is a plain MeshClass owned by
// that HLod (vtable Set_Transform 0x53B260, Set_Animation_Hidden 0x46C754, +0x5C setter 0x46C695, no-op +0xA8, container
// [+0x7C] == the HLod), the job runs the whole stock HLod update 0x59CD70 instead: the tree update plus the transform,
// hidden flag and +0x90 value it gives every sub-object. MeshClass::Set_Transform only notifies a scene for objects
// without a container, so that work touches the HLod and its own sub-objects only. The job puts back the valid flag
// [+0xF4] and the sub-objects-dirty bit (bit 21 of [+0x10]); when the pass calls 0x59CD70 for the object and the input
// words are unchanged, the hook sets both as the stock update would and skips it. Which jobs get self-checked is decided
// when they are scheduled, so the worker hashes only those (pivots, plus each sub-object's transform, +0x74, +0x90 and
// the two flag bits Set_Transform / Set_Animation_Hidden write); the check runs the stock update and compares.
// After the hash the job also fills each sub-object's cached world bounding sphere and box (MeshClass 0x54AFC0, the
// computation its first bounds query in the pass would run: model object-space bounds through the new transform, then
// the valid bit 1 of [+0x12]); with the HLod clean at that moment its Validate_Transform finds nothing to update.
#define PW_MAXJOBS 4096
#define PW_TAB     16384
#define PW_SEEN    16384
#define PW_WORKERS_MAX 8
struct PwJob  { DWORD obj; DWORD hash; BYTE in[88]; BYTE valid0, ok, full, check; BYTE flags12; BYTE pad[3]; };
struct PwEnt  { DWORD obj, gen; LONG job; };
struct PwSeen { DWORD obj; LONG frame; };
typedef void (__fastcall* tCustRender)(void*, void*, void*);
static tCustRender o_custRender = NULL;
static PwJob*  g_pwJobs = NULL;
static PwEnt*  g_pwTab = NULL;
static PwSeen* g_pwSeen = NULL;
static DWORD   g_pwGen = 1, g_pwGenLive = 0;
static HANDLE  g_pwSem = NULL;
static int     g_pwNW = 0;
static volatile LONG g_pwNext = 0, g_pwCount = 0, g_pwDone = 0, g_pwMxcsr = 0x1F80, g_pwFpcw = 0x27F;
static volatile LONG g_pwKill = 0, g_pwCheckLeft = 20000, g_pwCheckTick = 0;
static LONG g_pwLastJobs[PH_N];                               // jobs of the previous pass per phase: wake workers before the scan
static volatile LONG g_pwWarmed = 0, g_pwSkips = 0, g_pwStale = 0, g_pwChecked = 0, g_pwMismatch = 0, g_pwPasses = 0, g_pwFaults = 0;
static volatile LONG g_pwBoundsOn = 1, g_pwBoundsWarmed = 0;
static volatile LONG g_pwFullOn = 1, g_pwFullJobs = 0, g_pwFullSkips = 0, g_pwFullStale = 0, g_pwFullChecked = 0, g_pwFullMismatch = 0, g_pwFullRefused = 0;
static volatile LONG64 g_pwTicks = 0, g_pwScanTicks = 0;
static volatile LONG64 g_pwWaitTicks = 0;      // game thread waiting for the workers to finish a pass
static volatile LONG g_pwWaitN = 0, g_pwStop = 0, g_pwWaitRep = 0; static volatile LONG64 g_pwWaitRepT = 0;
static volatile LONG g_pwCand[8];        // scan tally: 0 nodes, 1 not HLod, 2 no tree/slaved, 3 animation mode, 4 already clean, 5 not drawn last frame, 6 taken
static int g_pwDepth = 0;

static __forceinline DWORD pwMix(DWORD h, DWORD w) { h ^= w; h *= 0x9E3779B1u; return (h << 13) | (h >> 19); }
static DWORD pwPivotHash(DWORD obj) {
    DWORD ht = *(DWORD*)(ULONG_PTR)(obj + 0xF8);
    if (!ht) return 0;
    DWORD n = *(DWORD*)(ULONG_PTR)(ht + 0x10), piv = *(DWORD*)(ULONG_PTR)(ht + 0x14);
    if (!piv || n > 1024) return 1;
    const DWORD* p = (const DWORD*)(ULONG_PTR)piv; DWORD words = n * (0x58 / 4), h = 2166136261u;
    for (DWORD i = 0; i < words; ++i) h = pwMix(h, p[i]);
    return h ^ n;
}
// what the stock HLod update writes into one sub-object (MeshClass): transform, +0x74, +0x90, hidden bit, bounds bit
static __forceinline DWORD pwSubMix(DWORD h, DWORD m) {
    const DWORD* w = (const DWORD*)(ULONG_PTR)(m + 0x18);
    for (int i = 0; i < 12; ++i) h = pwMix(h, w[i]);
    h = pwMix(h, *(DWORD*)(ULONG_PTR)(m + 0x90));
    { DWORD vt = *(DWORD*)(ULONG_PTR)m;                              // a box: its cached world-space box as well
      if (vt == 0x00BEA9B8) { const DWORD* c = (const DWORD*)(ULONG_PTR)(m + 0x10C); for (int i = 0; i < 6; ++i) h = pwMix(h, c[i]); }
      else if (vt == 0x00BEABC8) { const DWORD* c = (const DWORD*)(ULONG_PTR)(m + 0x130); for (int i = 0; i < 6; ++i) h = pwMix(h, c[i]); } }
    return pwMix(h, (DWORD)*(BYTE*)(ULONG_PTR)(m + 0x74) | ((DWORD)(*(BYTE*)(ULONG_PTR)(m + 0x11) & 0x40) << 8) | ((DWORD)(*(BYTE*)(ULONG_PTR)(m + 0x12) & 0x02) << 16));
}
static DWORD pwSubHash(DWORD o) {
    DWORD h = 0x811C9DC5u;
    LONG lods = *(LONG*)(ULONG_PTR)(o + 0x120); DWORD lodArr = *(DWORD*)(ULONG_PTR)(o + 0x128);
    for (LONG l = 0; l < lods; ++l) {
        LONG cnt = *(LONG*)(ULONG_PTR)(lodArr + l * 0x28 + 0x10); DWORD items = *(DWORD*)(ULONG_PTR)(lodArr + l * 0x28 + 4);
        for (LONG i = 0; i < cnt; ++i) h = pwSubMix(h, *(DWORD*)(ULONG_PTR)(items + i * 0x14));
    }
    LONG add = *(LONG*)(ULONG_PTR)(o + 0x148); DWORD addArr = *(DWORD*)(ULONG_PTR)(o + 0x13C);
    for (LONG i = 0; i < add; ++i) h = pwSubMix(h, *(DWORD*)(ULONG_PTR)(addArr + i * 0x14));
    return h;
}
// v21 showed why only ~13 of ~430 objects a frame qualified: almost every unit carries a collision box, and the test
// accepted plain meshes only. The two box classes (AABoxRenderObjClass vtable 0xBEA9B8, class id 0x1A, and
// OBBoxRenderObjClass 0xBEABC8, 0x1B) share every method the HLod update calls on a sub-object with MeshClass,
// except Set_Transform (0x574FC0): the base Set_Transform followed by their own cached-box recompute (vt+0x208:
// 0x575000 / 0x575120), which is arithmetic on the object's own fields and calls nothing. Same ownership rule.
static LONG g_pwBoxOk = 0;                                 // the two box vtables look as analysed (checked at install)
static __forceinline bool pwIsBox(const DWORD* vt) { return g_pwBoxOk && (vt == (const DWORD*)0x00BEA9B8 || vt == (const DWORD*)0x00BEABC8); }
static __forceinline bool pwMeshOk(DWORD m, DWORD o, DWORD bone, DWORD pivots) {
    if (!m || bone >= pivots) return false;
    const DWORD* vt = *(const DWORD**)(ULONG_PTR)m;
    if (pwIsBox(vt)) return *(DWORD*)(ULONG_PTR)(m + 0x7C) == o;
    return vt[0x54 / 4] == 0x0053B260 && vt[0x19C / 4] == 0x0046C754 && vt[0x5C / 4] == 0x0046C695 && vt[0xA8 / 4] == 0x00A88AC0
        && vt[0x1FC / 4] == 0x0054AFC0 && vt[0x50 / 4] == 0x0053B320 && vt[0x10C / 4] == 0x005498E0 && vt[0x110 / 4] == 0x00549920
        && *(DWORD*)(ULONG_PTR)(m + 0x7C) == o;
}
typedef void (__fastcall* tPwBounds)(DWORD, DWORD);
static void pwWarmBounds(DWORD o) {             // every sub-object's cached world bounds, as its first query would compute them
    LONG n = 0;
    LONG lods = *(LONG*)(ULONG_PTR)(o + 0x120); DWORD lodArr = *(DWORD*)(ULONG_PTR)(o + 0x128);
    for (LONG l = 0; l < lods; ++l) {
        LONG cnt = *(LONG*)(ULONG_PTR)(lodArr + l * 0x28 + 0x10); DWORD items = *(DWORD*)(ULONG_PTR)(lodArr + l * 0x28 + 4);
        for (LONG i = 0; i < cnt; ++i) { DWORD m = *(DWORD*)(ULONG_PTR)(items + i * 0x14); if (!(*(BYTE*)(ULONG_PTR)(m + 0x12) & 2)) { ((tPwBounds)(ULONG_PTR)(*(DWORD**)(ULONG_PTR)m)[0x1FC / 4])(m, 0); ++n; } }
    }
    LONG add = *(LONG*)(ULONG_PTR)(o + 0x148); DWORD addArr = *(DWORD*)(ULONG_PTR)(o + 0x13C);
    for (LONG i = 0; i < add; ++i) { DWORD m = *(DWORD*)(ULONG_PTR)(addArr + i * 0x14); if (!(*(BYTE*)(ULONG_PTR)(m + 0x12) & 2)) { ((tPwBounds)(ULONG_PTR)(*(DWORD**)(ULONG_PTR)m)[0x1FC / 4])(m, 0); ++n; } }
    InterlockedExchangeAdd(&g_pwBoundsWarmed, n);
}
static bool pwSubsOk(DWORD o) {                 // top-level HLod; every sub-object a plain MeshClass it owns; bone indices in range
    DWORD ht = *(DWORD*)(ULONG_PTR)(o + 0xF8);
    if (!ht || *(DWORD*)(ULONG_PTR)(o + 0x7C)) return false;          // inside another container: its validation could walk up
    DWORD pivots = *(DWORD*)(ULONG_PTR)(ht + 0x10);
    LONG lods = *(LONG*)(ULONG_PTR)(o + 0x120); DWORD lodArr = *(DWORD*)(ULONG_PTR)(o + 0x128);
    if (lods < 0 || lods > 16 || (lods && !lodArr)) return false;
    for (LONG l = 0; l < lods; ++l) {
        LONG cnt = *(LONG*)(ULONG_PTR)(lodArr + l * 0x28 + 0x10); DWORD items = *(DWORD*)(ULONG_PTR)(lodArr + l * 0x28 + 4);
        if (cnt < 0 || cnt > 256 || (cnt && !items)) return false;
        for (LONG i = 0; i < cnt; ++i) if (!pwMeshOk(*(DWORD*)(ULONG_PTR)(items + i * 0x14), o, *(DWORD*)(ULONG_PTR)(items + i * 0x14 + 4), pivots)) return false;
    }
    LONG add = *(LONG*)(ULONG_PTR)(o + 0x148); DWORD addArr = *(DWORD*)(ULONG_PTR)(o + 0x13C);
    if (add < 0 || add > 256 || (add && !addArr)) return false;
    for (LONG i = 0; i < add; ++i) if (!pwMeshOk(*(DWORD*)(ULONG_PTR)(addArr + i * 0x14), o, *(DWORD*)(ULONG_PTR)(addArr + i * 0x14 + 4), pivots)) return false;
    return true;
}
// Diagnostic: v20 takes ~430 objects a frame but only ~13 qualify for the whole-HLod update. This says which test
// refuses the rest (sampled 1 in 8), and which sub-object classes they carry, so the test can be widened on facts.
static volatile LONG g_pwWhy[8];           // 0 in a container, 1 no tree, 2 lod table, 3 null/bone range, 4 sub-object class, 5 sub-object owner, 6 extra list, 7 sampled
static DWORD g_pwBadVt[12]; static volatile LONG g_pwBadVtN[12]; static BYTE g_pwBadSlot[12];
static LONG g_pwWhyTick = 0;
static int pwMeshWhy(DWORD m, DWORD o, DWORD bone, DWORD pivots) {
    if (!m || bone >= pivots) return 3;
    const DWORD* vt = *(const DWORD**)(ULONG_PTR)m;
    if (pwIsBox(vt)) return *(DWORD*)(ULONG_PTR)(m + 0x7C) == o ? -1 : 5;
    static const DWORD kSlot[8] = { 0x54, 0x19C, 0x5C, 0xA8, 0x1FC, 0x50, 0x10C, 0x110 };
    static const DWORD kWant[8] = { 0x0053B260, 0x0046C754, 0x0046C695, 0x00A88AC0, 0x0054AFC0, 0x0053B320, 0x005498E0, 0x00549920 };
    for (int k = 0; k < 8; ++k) if (vt[kSlot[k] / 4] != kWant[k]) {
        for (int i = 0; i < 12; ++i) {
            if (g_pwBadVt[i] == (DWORD)(ULONG_PTR)vt) { g_pwBadVtN[i]++; break; }
            if (!g_pwBadVt[i]) { g_pwBadVt[i] = (DWORD)(ULONG_PTR)vt; g_pwBadSlot[i] = (BYTE)k; g_pwBadVtN[i] = 1; break; }
        }
        return 4;
    }
    if (*(DWORD*)(ULONG_PTR)(m + 0x7C) != o) return 5;
    return -1;
}
static void pwWhyNot(DWORD o) {
    g_pwWhy[7]++;
    DWORD ht = *(DWORD*)(ULONG_PTR)(o + 0xF8);
    if (*(DWORD*)(ULONG_PTR)(o + 0x7C)) { g_pwWhy[0]++; return; }
    if (!ht) { g_pwWhy[1]++; return; }
    DWORD pivots = *(DWORD*)(ULONG_PTR)(ht + 0x10);
    LONG lods = *(LONG*)(ULONG_PTR)(o + 0x120); DWORD lodArr = *(DWORD*)(ULONG_PTR)(o + 0x128);
    if (lods < 0 || lods > 16 || (lods && !lodArr)) { g_pwWhy[2]++; return; }
    for (LONG l = 0; l < lods; ++l) {
        LONG cnt = *(LONG*)(ULONG_PTR)(lodArr + l * 0x28 + 0x10); DWORD items = *(DWORD*)(ULONG_PTR)(lodArr + l * 0x28 + 4);
        if (cnt < 0 || cnt > 256 || (cnt && !items)) { g_pwWhy[2]++; return; }
        for (LONG i = 0; i < cnt; ++i) { int w = pwMeshWhy(*(DWORD*)(ULONG_PTR)(items + i * 0x14), o, *(DWORD*)(ULONG_PTR)(items + i * 0x14 + 4), pivots); if (w >= 0) { g_pwWhy[w]++; return; } }
    }
    LONG add = *(LONG*)(ULONG_PTR)(o + 0x148); DWORD addArr = *(DWORD*)(ULONG_PTR)(o + 0x13C);
    if (add < 0 || add > 256 || (add && !addArr)) { g_pwWhy[6]++; return; }
    for (LONG i = 0; i < add; ++i) { int w = pwMeshWhy(*(DWORD*)(ULONG_PTR)(addArr + i * 0x14), o, *(DWORD*)(ULONG_PTR)(addArr + i * 0x14 + 4), pivots); if (w >= 0) { g_pwWhy[w == 4 ? 4 : (w == 5 ? 5 : 6)]++; return; } }
}
static __forceinline DWORD pwSlot(DWORD obj) { return (obj * 2654435761u) >> 18; }   // 14 bits
static void pwSeenMark(DWORD obj, LONG frame) {
    DWORD h = pwSlot(obj);
    for (int i = 0; i < 8; ++i) {
        PwSeen& s = g_pwSeen[(h + i) & (PW_SEEN - 1)];
        if (s.obj == obj) { s.frame = frame; return; }
        if (!s.obj || s.frame < frame - 2) { s.obj = obj; s.frame = frame; return; }
    }
    g_pwSeen[h].obj = obj; g_pwSeen[h].frame = frame;
}
static bool pwSeenRecently(DWORD obj, LONG frame) {
    DWORD h = pwSlot(obj);
    for (int i = 0; i < 8; ++i) { const PwSeen& s = g_pwSeen[(h + i) & (PW_SEEN - 1)]; if (s.obj == obj) return s.frame >= frame - 1; }
    return false;
}
static void pwRunJob(LONG i) {
    PwJob& j = g_pwJobs[i];
    __try {
        DWORD o = j.obj;
        bool full = g_pwFullOn && pwSubsOk(o);
        if (!full && g_pwFullOn && ((++g_pwWhyTick & 7) == 0)) pwWhyNot(o);
        if (full) {
            o_an[AN_HLOD]((void*)(ULONG_PTR)o, NULL);                        // stock HLod update: tree + sub-object transforms
            j.full = 1;
            if (j.check) j.hash = pwPivotHash(o) ^ pwSubHash(o);
            if (g_pwBoundsOn) pwWarmBounds(o);                                // the HLod is still clean here
            BYTE* f = (BYTE*)(ULONG_PTR)(o + 0x12);
            *f = (BYTE)((*f & ~0x20) | (j.flags12 & 0x20));                   // sub-objects-dirty bit as it was
        } else {
            o_an[AN_TREE]((void*)(ULONG_PTR)o, NULL);
            if (j.check) j.hash = pwPivotHash(o);
        }
        *(BYTE*)(ULONG_PTR)(o + 0xF4) = j.valid0;
        j.ok = 1;
    } __except (EXCEPTION_EXECUTE_HANDLER) { j.ok = 0; g_pwFaults++; g_pwKill = 1; }
}
static void pwApplyFpu() {
    _mm_setcsr((unsigned)g_pwMxcsr);
    WORD cw = (WORD)g_pwFpcw;
    __asm fldcw cw
}
static DWORD WINAPI pwWorker(LPVOID) {
    for (;;) {
        WaitForSingleObject(g_pwSem, INFINITE);
        for (int spin = 0; g_pwCount == 0 && spin < 50000; ++spin) _mm_pause();    // woken ahead of the jobs: wait ~2 ms for them
        pwApplyFpu();
        for (;;) { LONG i = InterlockedIncrement(&g_pwNext) - 1; if (i >= g_pwCount) break; pwRunJob(i); InterlockedIncrement(&g_pwDone); }
    }
    return 0;
}
static void __fastcall hkCustRender(void* scene, void* edx, void* rinfo) {
    if (g_pwKill || g_pwStop || g_pwDepth || GetCurrentThreadId() != g_mkTid || !g_mkTid) { g_pwDepth++; o_custRender(scene, edx, rinfo); g_pwDepth--; return; }
    LONG64 t0 = qpcNow();
    LONG n = 0, frame = g_mkFrames, ph = g_phase; if (ph < 0 || ph >= PH_N) ph = PH_OTHER;
    LONG woke = 0;
    if (g_pwLastJobs[ph] >= 8) { woke = g_pwLastJobs[ph] / 24; if (woke > g_pwNW) woke = g_pwNW; if (woke > 0) ReleaseSemaphore(g_pwSem, woke, NULL); }
    __try {
        DWORD head = (DWORD)(ULONG_PTR)scene + 0xF0, node = *(DWORD*)(ULONG_PTR)(head + 4);
        for (int guard = 0; node && node != head && guard < 200000 && n < PW_MAXJOBS; ++guard) {
            DWORD o = *(DWORD*)(ULONG_PTR)(node + 0xC);
            node = *(DWORD*)(ULONG_PTR)(node + 4);
            if (!o) continue;
            o -= 8;
            g_pwCand[0]++;
            const DWORD* ob = (const DWORD*)(ULONG_PTR)o;
            if (((const DWORD*)(ULONG_PTR)ob[0])[0xA8 / 4] != 0x0059CD70) { g_pwCand[1]++; continue; }   // HLod
            if (!ob[0xF8 / 4] || ob[0xFC / 4]) { g_pwCand[2]++; continue; }             // has its own tree, not slaved to another object's bone
            DWORD mode = ob[0x100 / 4];
            if (mode < 1 || mode > 3 || (mode == 2 && ob[0x110 / 4])) { g_pwCand[3]++; continue; }       // base pose, one or two animations, no auto-advance
            BYTE valid = *(BYTE*)(ULONG_PTR)(o + 0xF4);
            if (valid && !((ob[0x10 / 4] >> 21) & 1)) { g_pwCand[4]++; continue; }      // the stock pass would not update it
            if (!pwSeenRecently(o, frame)) { g_pwCand[5]++; continue; }
            g_pwCand[6]++;
            PwJob& j = g_pwJobs[n];
            j.obj = o; j.valid0 = valid; j.ok = 0; j.hash = 0; j.full = 0; j.flags12 = *(BYTE*)(ULONG_PTR)(o + 0x12);
            j.check = (BYTE)(g_pwCheckLeft > 0 ? (g_pwCheckLeft--, 1) : ((++g_pwCheckTick & 63) == 0));
            memcpy(j.in, (void*)(ULONG_PTR)(o + 0x18), 48); memcpy(j.in + 48, (void*)(ULONG_PTR)(o + 0xF8), 40);
            ++n;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { n = 0; g_pwFaults++; }
    g_pwScanTicks += qpcNow() - t0;
    g_pwLastJobs[ph] = n;
    if (n >= 8) {
        g_pwMxcsr = (LONG)_mm_getcsr();
        { WORD cw = 0; __asm fnstcw cw
          g_pwFpcw = cw; }
        g_pwNext = 0; g_pwDone = 0; g_pwCount = n;
        LONG wake = n / 24; if (wake > g_pwNW) wake = g_pwNW;
        if (wake > woke) ReleaseSemaphore(g_pwSem, wake - woke, NULL);
        for (;;) { LONG i = InterlockedIncrement(&g_pwNext) - 1; if (i >= n) break; pwRunJob(i); InterlockedIncrement(&g_pwDone); }
        { LONG64 tw = qpcNow();
          for (int spin = 0; g_pwDone < n; ++spin) { if (spin < 20000) _mm_pause(); else SwitchToThread(); }
          LONG64 dw = qpcNow() - tw;
          g_pwWaitTicks += dw; g_pwWaitRepT += dw; g_pwWaitRep++;
          if (++g_pwWaitN >= 400) {                                   // ~200 frames of two passes
              double ms = g_pqpf.QuadPart ? (double)g_pwWaitTicks * 1000.0 / (double)g_pqpf.QuadPart / (double)g_pwWaitN : 0.0;
              if (ms > 1.0) { g_pwStop = 1; char b[32]; sprintf_s(b, "%.2f", ms);
                              logf("pose-warm2: the game thread waited %s ms per pass for the warm jobs - warming OFF (it costs more than the updates it moves off this thread).", b); }
              g_pwWaitN = 0; g_pwWaitTicks = 0;
          } }
        g_pwCount = 0;
        if (!g_pwKill) {
            ++g_pwGen;
            for (LONG i = 0; i < n; ++i) {
                if (!g_pwJobs[i].ok) continue;
                DWORD h = pwSlot(g_pwJobs[i].obj);
                for (int k = 0; k < 8; ++k) {
                    PwEnt& e = g_pwTab[(h + k) & (PW_TAB - 1)];
                    if (e.gen != g_pwGen || e.obj == g_pwJobs[i].obj) { e.obj = g_pwJobs[i].obj; e.gen = g_pwGen; e.job = i; break; }
                }
            }
            g_pwGenLive = g_pwGen;
            g_pwWarmed += n; g_pwPasses++;
            for (LONG i = 0; i < n; ++i) if (g_pwJobs[i].full) g_pwFullJobs++;
        }
    }
    g_pwTicks += qpcNow() - t0;
    g_pwDepth++;
    o_custRender(scene, edx, rinfo);
    g_pwDepth--;
    g_pwGenLive = 0;
}
// called from the tree-update hook on the game thread; true when the stock update may be skipped
static bool pwTrySkip(DWORD o) {
    DWORD h = pwSlot(o);
    for (int k = 0; k < 8; ++k) {
        PwEnt& e = g_pwTab[(h + k) & (PW_TAB - 1)];
        if (e.gen != g_pwGenLive) continue;
        if (e.obj != o) continue;
        PwJob& j = g_pwJobs[e.job];
        e.gen = 0;                                                     // one use per pass
        if (j.full) { g_pwFullStale++; return false; }                  // a full job whose HLod hook did not take it: stock
        if (j.obj != o || memcmp(j.in, (void*)(ULONG_PTR)(o + 0x18), 48) || memcmp(j.in + 48, (void*)(ULONG_PTR)(o + 0xF8), 40)) { g_pwStale++; return false; }
        if (j.check) {
            o_an[AN_TREE]((void*)(ULONG_PTR)o, NULL);
            if (pwPivotHash(o) != j.hash) {
                if (!g_pwMismatch++) logf("pose-warm2: SELF-CHECK MISMATCH on object %08X (mode %u) - parallel tree updates OFF for this session.", o, *(DWORD*)(ULONG_PTR)(o + 0x100));
                g_pwKill = 1;
            } else g_pwChecked++;
            return true;                                               // the stock update already ran
        }
        *(BYTE*)(ULONG_PTR)(o + 0xF4) = 1;
        g_pwSkips++;
        return true;
    }
    return false;
}
// called from the HLod update hook (0x59CD70) on the game thread; true when the stock update is done or may be skipped
static bool pwTrySkipFull(DWORD o) {
    DWORD h = pwSlot(o);
    for (int k = 0; k < 8; ++k) {
        PwEnt& e = g_pwTab[(h + k) & (PW_TAB - 1)];
        if (e.gen != g_pwGenLive || e.obj != o) continue;
        PwJob& j = g_pwJobs[e.job];
        if (!j.full || !g_pwFullOn) return false;                       // tree-only job (or warming just turned off): the tree hook inside takes it
        e.gen = 0;                                                     // one use per pass
        if (j.obj != o || memcmp(j.in, (void*)(ULONG_PTR)(o + 0x18), 48) || memcmp(j.in + 48, (void*)(ULONG_PTR)(o + 0xF8), 40)) { g_pwFullStale++; return false; }
        if (j.check) {
            o_an[AN_HLOD]((void*)(ULONG_PTR)o, NULL);                   // stock update (its tree hook finds no live entry)
            if ((pwPivotHash(o) ^ pwSubHash(o)) != j.hash) {
                if (!g_pwFullMismatch++) logf("pose-warm2: FULL SELF-CHECK MISMATCH on object %08X (mode %u) - whole-HLod warming OFF for this session.", o, *(DWORD*)(ULONG_PTR)(o + 0x100));
                g_pwFullOn = 0;
            } else g_pwFullChecked++;
            return true;
        }
        *(BYTE*)(ULONG_PTR)(o + 0xF4) = 1;                              // what the stock update leaves: valid, sub-objects clean
        *(BYTE*)(ULONG_PTR)(o + 0x12) &= 0xDF;
        g_pwFullSkips++;
        return true;
    }
    return false;
}
static void installPoseWarm2() {
    __try {
        g_pwBoxOk = *(DWORD*)0x00BEA9B8 != 0 && *(DWORD*)(0x00BEA9B8 + 0x54) == 0x00574FC0 && *(DWORD*)(0x00BEABC8 + 0x54) == 0x00574FC0 &&
                    *(DWORD*)(0x00BEA9B8 + 0x208) == 0x00575000 && *(DWORD*)(0x00BEABC8 + 0x208) == 0x00575120 &&
                    *(DWORD*)(0x00BEA9B8 + 0x1FC) == 0x0053BC90 && *(DWORD*)(0x00BEABC8 + 0x1FC) == 0x0053BC90 &&
                    *(DWORD*)(0x00BEA9B8 + 0x19C) == 0x0046C754 && *(DWORD*)(0x00BEABC8 + 0x19C) == 0x0046C754 &&
                    *(DWORD*)(0x00BEA9B8 + 0x5C) == 0x0046C695 && *(DWORD*)(0x00BEABC8 + 0x5C) == 0x0046C695 &&
                    *(DWORD*)(0x00BEA9B8 + 0x50) == 0x0053B320 && *(DWORD*)(0x00BEABC8 + 0x50) == 0x0053B320;
    } __except (EXCEPTION_EXECUTE_HANDLER) { g_pwBoxOk = 0; }
    logf("pose-warm2: collision-box sub-objects %s.", g_pwBoxOk ? "accepted for whole-HLod updates (AABox / OBBox vtables as analysed)" : "NOT accepted (their vtables differ)");
    static const BYTE kCust[] = {0x55,0x8B,0xEC,0x83,0xEC,0x28,0x53,0x56,0x8B,0x35,0x58,0x3B,0xDE,0x00};
    static const BYTE kTreeTail[] = {0xC6,0x86,0xF4,0x00,0x00,0x00,0x01};   // mov byte ptr [esi+0xF4], 1 (end of the update)
    __try {
        if (!o_an[AN_TREE] || memcmp((void*)0x0047177E, kCust, sizeof(kCust)) || memcmp((void*)0x005A50C5, kTreeTail, sizeof(kTreeTail))) {
            logf("pose-warm2: scene render or tree update differs - parallel tree updates OFF."); return;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { return; }
    char env[8]; env[0] = 0;
    if (GetEnvironmentVariableA("AOTR_POSEWARM2", env, sizeof(env)) && env[0] == '0') { logf("pose-warm2: disabled by AOTR_POSEWARM2=0."); return; }
    env[0] = 0;
    if (GetEnvironmentVariableA("AOTR_POSEWARM3", env, sizeof(env)) && env[0] == '0') g_pwFullOn = 0;
    env[0] = 0;
    if (GetEnvironmentVariableA("AOTR_POSEWARM3BOUNDS", env, sizeof(env)) && env[0] == '0') g_pwBoundsOn = 0;
    static const BYTE kHLodTail[] = {0x80,0x63,0x12,0xDF,0x5F,0x5E,0x5D,0x5B,0x83,0xC4,0x4C,0xC3};   // and byte [ebx+12h], 0DFh ... ret
    __try { if (memcmp((void*)0x0059D267, kHLodTail, sizeof(kHLodTail))) g_pwFullOn = 0; } __except (EXCEPTION_EXECUTE_HANDLER) { g_pwFullOn = 0; }
    g_pwJobs = (PwJob*)VirtualAlloc(NULL, PW_MAXJOBS * sizeof(PwJob), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    g_pwTab = (PwEnt*)VirtualAlloc(NULL, PW_TAB * sizeof(PwEnt), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    g_pwSeen = (PwSeen*)VirtualAlloc(NULL, PW_SEEN * sizeof(PwSeen), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    o_custRender = (tCustRender)makeTrampoline((BYTE*)0x0047177E, 6);
    g_pwSem = CreateSemaphoreA(NULL, 0, 1 << 20, NULL);
    if (!g_pwJobs || !g_pwTab || !g_pwSeen || !o_custRender || !g_pwSem) { logf("pose-warm2: alloc failed - OFF."); return; }
    SYSTEM_INFO si; GetSystemInfo(&si);
    int w = (int)si.dwNumberOfProcessors / 2 - 2; if (w > PW_WORKERS_MAX) w = PW_WORKERS_MAX; if (w < 1) w = 1;
    for (int i = 0; i < w; ++i) { HANDLE h = CreateThread(NULL, 256 * 1024, pwWorker, NULL, 0, NULL); if (h) { ++g_pwNW; CloseHandle(h); } }
    HANDLE fz[256]; int nf = 0;
    suspendOthers(fz, &nf, 256);
    patchJmp((BYTE*)0x0047177E, (void*)&hkCustRender, 6);
    resumeAll(fz, nf);
    logf("pose-warm2: scene render 0x47177E hooked - skeleton tree updates of the objects each pass will draw run on %d worker threads (self-checked); whole-HLod updates %s.", g_pwNW, g_pwFullOn ? "on (self-checked)" : "off");
}
