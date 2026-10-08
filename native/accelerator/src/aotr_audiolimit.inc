// ================================================================ audio request limit check: indexed instead of quadratic
// MilesAudioManager keeps every sound request it has not served yet in a list (manager+0x98; STLport list: the member
// is the head node pointer, a node is next / prev / AudioRequest*). Looping positional sounds that are over their
// limit stay in that list and are retried every frame, so in a long battle it holds hundreds to thousands of entries.
// processRequestList (0x461CA3) walks it once a frame, and for every request the limit check (0x456D8B, reached through
// 0x461A83 -> 0x45D852 -> 0x45CB3B) walks the WHOLE list again to count the requests for the same sound: R * R node
// visits a frame. The v23 battle profile has that one function at 1% of the game thread early and 7.5% (3.3 ms/frame)
// after four minutes, still growing.
//
// Only that inner loop is replaced (0x456E88..0x456EBD, continuing at 0x456EBE with both counters raised by the
// number of matches - exactly what the loop does). What it counts: list entries whose request has an event with the
// same info pointer ([event+8]) as the event being checked, that are not that event, and whose flag [event+0x4B] is 0.
// Here the count comes from an index of the list by info pointer, built on the first check of each
// processRequestList pass (one walk) and used until that pass ends:
//   - every entry that is counted is read again, live, from its list node (request, event, info, flag), so a flag
//     that changes between two checks is seen exactly as the walk would see it;
//   - the list can only change through the list primitives; every call to them from the audio manager goes through a
//     thunk here. The pass's own erase takes the entry out of the index, anything else marks the index stale and the
//     next check rebuilds it (at most 8 rebuilds a pass, then plain walks);
//   - independent of that, each check verifies that the list still starts and ends where the index says, and that
//     every node it counts is still linked where it was; any doubt -> the plain walk, which is the original loop.
// Checks made outside a pass (a new sound being added) use the plain walk.
// Self-proving: the first 20000 indexed answers are compared with the plain walk, afterwards 1 in 64; a single
// difference switches the index off for good (the plain walk's answer is the one used). Kill switch: AOTR_AUDIOLIMIT=0.

#ifndef AL_PRIM_PUSHBACK                                   // the list primitives (the offline test substitutes its own)
#define AL_PRIM_PUSHBACK  0x0060011F
#define AL_PRIM_PUSHFRONT 0x0086DC96
#define AL_PRIM_ERASE     0x00702055
#define AL_PRIM_POPBACK   0x0094EB6C
#define AL_PRIM_CLEAR     0x005FFE47
#endif
typedef void  (__fastcall* tAlPass)(void*, void*);
typedef void  (__fastcall* tAlPush)(void*, void*, void*);
typedef void* (__fastcall* tAlErase)(void*, void*, void*, void*);
typedef void  (__fastcall* tAlVoid)(void*, void*);
static tAlPass o_alPass = NULL;

#define AL_MAXENT 4096
#define AL_HASHN  8192                                     // power of two, twice the entries
struct AlEnt  { DWORD node, info; LONG next, dead; };
struct AlSlot { DWORD key, epoch; LONG head, tail; };
static AlEnt  g_alEnt[AL_MAXENT];
static AlSlot g_alInfo[AL_HASHN], g_alNode[AL_HASHN];
static DWORD  g_alEpoch = 0, g_alMgr = 0, g_alHead = 0, g_alPassTid = 0;
static LONG   g_alN = 0, g_alFirst = 0, g_alLast = -1, g_alUnkHead = -1, g_alUnkTail = -1;
static volatile LONG g_alLive = 0, g_alDirty = 1, g_alInPass = 0, g_alSmall = 0, g_alPassRebuilds = 0, g_alProofLeft = 20000;
static volatile LONG g_alCalls = 0, g_alIdx = 0, g_alRebuilds = 0, g_alStale = 0, g_alChecked = 0, g_alMismatch = 0, g_alFaults = 0, g_alTooBig = 0, g_alErased = 0, g_alMut = 0, g_alPasses = 0;
static volatile LONG64 g_alWalkNodes = 0, g_alIdxEnts = 0, g_alBuildNodes = 0, g_alSavedNodes = 0;
static volatile ULONG64 g_alTicks = 0;

static __forceinline DWORD alHash(DWORD p) { return ((p >> 3) * 2654435761u) >> 19; }          // 13 bits

// the original loop, instruction for instruction
static LONG alWalk(DWORD mgr, DWORD event, LONG* visited) {
    DWORD head = *(DWORD*)(ULONG_PTR)(mgr + 0x98), info = *(DWORD*)(ULONG_PTR)(event + 8);
    LONG c = 0, v = 0;
    for (DWORD n = *(DWORD*)(ULONG_PTR)head; n != head; n = *(DWORD*)(ULONG_PTR)n) {
        ++v;
        DWORD req = *(DWORD*)(ULONG_PTR)(n + 8); if (!req) continue;
        DWORD ev = *(DWORD*)(ULONG_PTR)(req + 4); if (!ev) continue;
        if (*(DWORD*)(ULONG_PTR)(ev + 8) != info || ev == event || *(BYTE*)(ULONG_PTR)(ev + 0x4B)) continue;
        ++c;
    }
    if (visited) *visited = v;
    return c;
}
static __forceinline AlSlot* alFind(AlSlot* tab, DWORD key) {
    for (DWORD h = alHash(key), i = 0; i < AL_HASHN; ++i, h = (h + 1) & (AL_HASHN - 1)) {
        AlSlot& s = tab[h];
        if (s.epoch != g_alEpoch) return NULL;
        if (s.key == key) return &s;
    }
    return NULL;
}
static __forceinline AlSlot* alClaim(AlSlot* tab, DWORD key) {
    for (DWORD h = alHash(key), i = 0; i < AL_HASHN; ++i, h = (h + 1) & (AL_HASHN - 1)) {
        AlSlot& s = tab[h];
        if (s.epoch != g_alEpoch) { s.epoch = g_alEpoch; s.key = key; s.head = s.tail = -1; return &s; }
        if (s.key == key) return &s;
    }
    return NULL;
}
static bool alBuild(DWORD mgr) {
    DWORD head = *(DWORD*)(ULONG_PTR)(mgr + 0x98);
    if (!++g_alEpoch) { memset(g_alInfo, 0, sizeof(g_alInfo)); memset(g_alNode, 0, sizeof(g_alNode)); g_alEpoch = 1; }
    LONG n = 0; g_alUnkHead = g_alUnkTail = -1; g_alMgr = 0;
    for (DWORD node = *(DWORD*)(ULONG_PTR)head; node != head; node = *(DWORD*)(ULONG_PTR)node) {
        if (n >= AL_MAXENT) { g_alTooBig++; return false; }
        DWORD req = *(DWORD*)(ULONG_PTR)(node + 8), ev = req ? *(DWORD*)(ULONG_PTR)(req + 4) : 0, info = ev ? *(DWORD*)(ULONG_PTR)(ev + 8) : 0;
        AlEnt& e = g_alEnt[n]; e.node = node; e.info = info; e.next = -1; e.dead = 0;
        AlSlot* ns = alClaim(g_alNode, node); if (!ns || ns->head >= 0) return false;              // full, or the same node twice: not a list this index understands
        ns->head = n;
        if (info) {
            AlSlot* is = alClaim(g_alInfo, info); if (!is) return false;
            if (is->tail >= 0) g_alEnt[is->tail].next = n; else is->head = n;
            is->tail = n;
        } else { if (g_alUnkTail >= 0) g_alEnt[g_alUnkTail].next = n; else g_alUnkHead = n; g_alUnkTail = n; }
        ++n;
    }
    g_alN = n; g_alFirst = 0; g_alLast = n - 1; g_alHead = head; g_alMgr = mgr;
    g_alBuildNodes += n;
    return true;
}
// one entry, read live from its node. 1 = counts, 0 = does not, -1 = the index cannot be trusted
static __forceinline int alEntry(const AlEnt& e, DWORD info, DWORD event) {
    DWORD node = e.node, nx = *(DWORD*)(ULONG_PTR)node, pv = *(DWORD*)(ULONG_PTR)(node + 4);
    if (*(DWORD*)(ULONG_PTR)pv != node || *(DWORD*)(ULONG_PTR)(nx + 4) != node) return -1;         // not linked where it was
    DWORD req = *(DWORD*)(ULONG_PTR)(node + 8); if (!req) return e.info ? -1 : 0;
    DWORD ev = *(DWORD*)(ULONG_PTR)(req + 4); if (!ev) return e.info ? -1 : 0;
    if (*(DWORD*)(ULONG_PTR)(ev + 8) != e.info) return -1;                                          // its info changed since the index was built
    if (!e.info || e.info != info) return 0;
    return (ev == event || *(BYTE*)(ULONG_PTR)(ev + 0x4B)) ? 0 : 1;
}
static LONG alIndexed(DWORD mgr, DWORD event, bool* ok) {
    LONG c = 0, seen = 0;
    __try {
        DWORD head = *(DWORD*)(ULONG_PTR)(mgr + 0x98);
        if (head != g_alHead) { *ok = false; return 0; }
        while (g_alFirst <= g_alLast && g_alEnt[g_alFirst].dead) ++g_alFirst;
        while (g_alLast >= g_alFirst && g_alEnt[g_alLast].dead) --g_alLast;
        DWORD first = *(DWORD*)(ULONG_PTR)head, last = *(DWORD*)(ULONG_PTR)(head + 4);
        if (g_alFirst > g_alLast) { if (first != head) { *ok = false; return 0; } }
        else if (first != g_alEnt[g_alFirst].node || last != g_alEnt[g_alLast].node) { *ok = false; return 0; }   // something was added at an end
        DWORD info = *(DWORD*)(ULONG_PTR)(event + 8);
        AlSlot* is = alFind(g_alInfo, info);
        for (LONG i = is ? is->head : -1; i >= 0; i = g_alEnt[i].next) {
            if (g_alEnt[i].dead) continue;
            int r = alEntry(g_alEnt[i], info, event); ++seen;
            if (r < 0) { *ok = false; return 0; }
            c += r;
        }
        for (LONG i = g_alUnkHead; i >= 0; i = g_alEnt[i].next) {                                   // entries that had no event / info when the index was built
            if (g_alEnt[i].dead) continue;
            int r = alEntry(g_alEnt[i], info, event); ++seen;
            if (r < 0) { *ok = false; return 0; }
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { g_alFaults++; *ok = false; return 0; }
    g_alIdxEnts += seen;
    return c;
}
static LONG __stdcall alCount(DWORD mgr, DWORD event) {
    ULONG64 t0 = __rdtsc();
    LONG c, v = 0;
    g_alCalls++;
    bool use = false;
    if (g_alLive && g_alInPass && __readfsdword(0x24) == g_alPassTid) {
        if ((g_alDirty || mgr != g_alMgr) && !g_alSmall && g_alPassRebuilds < 8) {
            g_alPassRebuilds++; g_alRebuilds++;
            if (alBuild(mgr)) { g_alDirty = 0; if (g_alN < 48) g_alSmall = 1; }        // a short list is walked as before
            else g_alSmall = 1;                                                           // too long for the index: plain walks for the rest of this pass
        }
        use = !g_alDirty && !g_alSmall && mgr == g_alMgr;
    }
    if (use) {
        bool ok = true;
        c = alIndexed(mgr, event, &ok);
        if (!ok) { g_alDirty = 1; g_alStale++; if (g_alFaults > 3) g_alLive = 0; c = alWalk(mgr, event, &v); g_alWalkNodes += v; }
        else {
            LONG k = ++g_alIdx;
            if (g_alProofLeft > 0 || !(k & 63)) {
                LONG w = alWalk(mgr, event, &v); g_alChecked++;
                if (g_alProofLeft > 0) g_alProofLeft--;
                if (w != c) {
                    g_alMismatch++; g_alLive = 0;
                    logf("audiolimit: MISMATCH - index says %d, the list walk says %d (event %08X, info %08X, list of %d, %d visited). Index OFF; the walk's answer is used.",
                         (int)c, (int)w, event, *(DWORD*)(ULONG_PTR)(event + 8), (int)g_alN, (int)v);
                    c = w;
                }
            } else g_alSavedNodes += g_alN;
        }
    } else { c = alWalk(mgr, event, &v); g_alWalkNodes += v; }
    g_alTicks += __rdtsc() - t0;
    return c;
}
static void __fastcall hkAlPass(void* mgr, void* edx) {
    g_alPassTid = __readfsdword(0x24); g_alDirty = 1; g_alSmall = 0; g_alPassRebuilds = 0; g_alInPass = 1; g_alPasses++;
    o_alPass(mgr, edx);
    g_alInPass = 0;
}
// ---- the list primitives, as called by the audio manager
static __forceinline void alMutated(void* list) { if (g_alMgr && (DWORD)(ULONG_PTR)list == g_alMgr + 0x98) { g_alDirty = 1; g_alMut++; } }
static void  __fastcall alThPushBack(void* list, void* edx, void* pval)  { alMutated(list); ((tAlPush)(ULONG_PTR)AL_PRIM_PUSHBACK)(list, edx, pval); }
static void  __fastcall alThPushFront(void* list, void* edx, void* pval) { alMutated(list); ((tAlPush)(ULONG_PTR)AL_PRIM_PUSHFRONT)(list, edx, pval); }
static void  __fastcall alThPopBack(void* list, void* edx)               { alMutated(list); ((tAlVoid)(ULONG_PTR)AL_PRIM_POPBACK)(list, edx); }
static void  __fastcall alThClear(void* list, void* edx)                 { alMutated(list); ((tAlVoid)(ULONG_PTR)AL_PRIM_CLEAR)(list, edx); }
static void* __fastcall alThErase(void* list, void* edx, void* res, void* node) {
    if (g_alMgr && (DWORD)(ULONG_PTR)list == g_alMgr + 0x98 && !g_alDirty) {
        AlSlot* ns = (g_alInPass && __readfsdword(0x24) == g_alPassTid) ? alFind(g_alNode, (DWORD)(ULONG_PTR)node) : NULL;
        if (ns && ns->head >= 0 && !g_alEnt[ns->head].dead) { g_alEnt[ns->head].dead = 1; g_alErased++; }
        else { g_alDirty = 1; g_alMut++; }
    }
    return ((tAlErase)(ULONG_PTR)AL_PRIM_ERASE)(list, edx, res, node);
}
struct AlSite { DWORD at, target; void* thunk; };
static const AlSite kAlSite[] = {
    { 0x00453D70, 0x00702055, (void*)&alThErase }, { 0x00453DB0, 0x00702055, (void*)&alThErase }, { 0x00453DE4, 0x00702055, (void*)&alThErase },
    { 0x00453E0F, 0x00702055, (void*)&alThErase }, { 0x004567E5, 0x00702055, (void*)&alThErase }, { 0x0045AAF1, 0x00702055, (void*)&alThErase },
    { 0x0045D162, 0x00702055, (void*)&alThErase }, { 0x0045F4C0, 0x00702055, (void*)&alThErase }, { 0x004603E7, 0x00702055, (void*)&alThErase },
    { 0x00460B67, 0x00702055, (void*)&alThErase }, { 0x00461D05, 0x00702055, (void*)&alThErase },
    { 0x0045522F, 0x0086DC96, (void*)&alThPushFront }, { 0x00458D28, 0x0086DC96, (void*)&alThPushFront }, { 0x0045CE2B, 0x0086DC96, (void*)&alThPushFront },
    { 0x00455236, 0x0060011F, (void*)&alThPushBack }, { 0x00455308, 0x0060011F, (void*)&alThPushBack }, { 0x004553E2, 0x0060011F, (void*)&alThPushBack },
    { 0x00455F1F, 0x0060011F, (void*)&alThPushBack }, { 0x00455F91, 0x0060011F, (void*)&alThPushBack }, { 0x00455FD4, 0x0060011F, (void*)&alThPushBack },
    { 0x00456096, 0x0060011F, (void*)&alThPushBack }, { 0x00456170, 0x0060011F, (void*)&alThPushBack }, { 0x00456258, 0x0060011F, (void*)&alThPushBack },
    { 0x00458B3C, 0x0060011F, (void*)&alThPushBack }, { 0x00458D2F, 0x0060011F, (void*)&alThPushBack }, { 0x0045CE32, 0x0060011F, (void*)&alThPushBack },
    { 0x0045E284, 0x0060011F, (void*)&alThPushBack }, { 0x0045E318, 0x0060011F, (void*)&alThPushBack }, { 0x0045F68E, 0x0060011F, (void*)&alThPushBack },
    { 0x0045F775, 0x0060011F, (void*)&alThPushBack },
    { 0x00460791, 0x0094EB6C, (void*)&alThPopBack },
    { 0x00458BF4, 0x005FFE47, (void*)&alThClear }, { 0x00460974, 0x005FFE47, (void*)&alThClear }, { 0x00460983, 0x005FFE47, (void*)&alThClear },
    { 0x00460A8B, 0x005FFE47, (void*)&alThClear },
};
#define AL_NSITE ((int)(sizeof(kAlSite) / sizeof(kAlSite[0])))
static void installAudioLimit() {
    static const BYTE kLoop[54] = { 0x8B, 0x9B, 0x98, 0x00, 0x00, 0x00, 0x8B, 0x0B, 0xEB, 0x28, 0x8B, 0x41, 0x08, 0x85, 0xC0, 0x74, 0x1F, 0x8B, 0x40, 0x04, 0x85, 0xC0, 0x74, 0x18,
        0x8B, 0x50, 0x08, 0x3B, 0x57, 0x08, 0x75, 0x10, 0x3B, 0xC7, 0x74, 0x0C, 0x80, 0x78, 0x4B, 0x00, 0x75, 0x06, 0xFF, 0x45, 0xFC, 0xFF, 0x45, 0x08, 0x8B, 0x09, 0x3B, 0xCB, 0x75, 0xD4 };
    static const BYTE kPass[6] = { 0xB8, 0xCA, 0x26, 0xB7, 0x00, 0xE8 };
    static const BYTE kAfter[3] = { 0x8B, 0x45, 0xF8 };                                           // 0x456EBE: mov eax, [ebp-8]
    char env[8]; env[0] = 0;
    if (GetEnvironmentVariableA("AOTR_AUDIOLIMIT", env, sizeof(env)) && env[0] == '0') { logf("audiolimit: off (AOTR_AUDIOLIMIT=0)."); return; }
    bool ok = false; int bad = -1;
    __try {
        ok = !memcmp((void*)0x00456E88, kLoop, sizeof(kLoop)) && !memcmp((void*)0x00461CA3, kPass, sizeof(kPass)) && !memcmp((void*)0x00456EBE, kAfter, sizeof(kAfter));
        for (int i = 0; ok && i < AL_NSITE; ++i) {
            const BYTE* p = (const BYTE*)(ULONG_PTR)kAlSite[i].at;
            if (p[0] != 0xE8 || (DWORD)(kAlSite[i].at + 5 + *(LONG*)(p + 1)) != kAlSite[i].target) { ok = false; bad = i; }
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { ok = false; }
    if (!ok) { logf("audiolimit: code differs (%s%08X) - the engine's own list walk stays.", bad >= 0 ? "call site " : "loop / pass ", bad >= 0 ? kAlSite[bad].at : 0x00456E88); return; }
    o_alPass = (tAlPass)makeTrampoline((BYTE*)0x00461CA3, 5);
    if (!o_alPass) { logf("audiolimit: no trampoline - off."); return; }
    BYTE code[15] = { 0x57, 0x53, 0xE8, 0, 0, 0, 0, 0x01, 0x45, 0xFC, 0x01, 0x45, 0x08, 0xEB, 0x27 };  // push edi; push ebx; call alCount; add [ebp-4],eax; add [ebp+8],eax; jmp 0x456EBE
    *(LONG*)(code + 3) = (LONG)((DWORD)(ULONG_PTR)&alCount - (0x00456E8A + 5));
    HANDLE fz[256]; int nf = 0;
    suspendOthers(fz, &nf, 256);
    DWORD op = 0;
    for (int i = 0; i < AL_NSITE; ++i) {
        BYTE* p = (BYTE*)(ULONG_PTR)kAlSite[i].at;
        if (VirtualProtect(p, 5, PAGE_EXECUTE_READWRITE, &op)) { *(LONG*)(p + 1) = (LONG)((DWORD)(ULONG_PTR)kAlSite[i].thunk - (kAlSite[i].at + 5)); VirtualProtect(p, 5, op, &op); FlushInstructionCache(GetCurrentProcess(), p, 5); }
    }
    bool wrote = false;
    if (VirtualProtect((void*)0x00456E88, sizeof(code), PAGE_EXECUTE_READWRITE, &op)) {
        memcpy((void*)0x00456E88, code, sizeof(code)); VirtualProtect((void*)0x00456E88, sizeof(code), op, &op);
        FlushInstructionCache(GetCurrentProcess(), (void*)0x00456E88, sizeof(code)); wrote = true;
    }
    if (wrote) { patchJmp((BYTE*)0x00461CA3, (void*)&hkAlPass, 5); g_alLive = 1; }
    resumeAll(fz, nf);
    logf("audiolimit: %s", wrote ? "sound request limit check indexed (0x456D8B list walk replaced, 35 list call sites watched); proving against the plain walk first."
                                 : "could not write the patch - the engine's own list walk stays.");
}
static void alReport(LONG f) {
    if (f <= 0 || !o_alPass) return;
    static LONG lC = 0, lI = 0, lR = 0, lS = 0, lE = 0, lM = 0, lP = 0; static LONG64 lW = 0, lX = 0, lB = 0, lSv = 0; static ULONG64 lT = 0;
    LONG c = g_alCalls, i = g_alIdx, r = g_alRebuilds, s = g_alStale, e = g_alErased, m = g_alMut, p = g_alPasses;
    LONG64 w = g_alWalkNodes, x = g_alIdxEnts, b = g_alBuildNodes, sv = g_alSavedNodes; ULONG64 t = g_alTicks;
    char a1[16], a2[16], a3[16], a4[16], a5[16], a6[16], a7[16], a8[16], a9[16], a10[16], a11[16];
    LONG64 q = g_tscPerQpc > 0 ? (LONG64)((double)(t - lT) / g_tscPerQpc) : 0;
    logf("rt: audio limit %s | checks/f %s indexed/f %s | list %s entries at a rebuild, rebuilds/f %s stale/f %s | nodes walked/f %s, entries read/f %s, walk avoided/f %s nodes | erased-in-pass/f %s other list changes/f %s | %s ms/f | proof left %d, compared %d, mismatches %d, faults %d, too big %d",
         g_alLive ? "index live" : (g_alMismatch ? "OFF (mismatch)" : "off"), perStr(c - lC, f, a1), perStr(i - lI, f, a2),
         perStr((LONG)(b - lB), (r - lR) > 0 ? (r - lR) : 1, a3), perStr(r - lR, f, a4), perStr(s - lS, f, a5), perStr((LONG)(w - lW), f, a6), perStr((LONG)(x - lX), f, a7), perStr((LONG)(sv - lSv), f, a8),
         perStr(e - lE, f, a9), perStr(m - lM, f, a10), msStr(q, f, a11), (int)g_alProofLeft, (int)g_alChecked, (int)g_alMismatch, (int)g_alFaults, (int)g_alTooBig);
    lC = c; lI = i; lR = r; lS = s; lE = e; lM = m; lP = p; lW = w; lX = x; lB = b; lSv = sv; lT = t;
}
