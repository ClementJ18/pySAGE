// ---------------------------------------------------------------- ThingTemplate equivalence memo (exact results)
// ThingTemplate::isEquivalentTo (0x73D5C2, thiscall, one template argument, bool in al) answers "same unit type?" for
// object filters, auras and AI target scans, ~120k times per battle frame. Past the pointer and final-override checks it
// compares AsciiString names case-insensitively across four name lists of the two templates. That answer depends only on
// template data fixed by INI loading, so the memo keeps it per template pair together with both final overrides (the
// [+4] chain, walked on every call like the original does) and is cleared whenever the logic frame counter
// ([TheGameLogic 0xDE412C]+0x40) goes backwards, i.e. before every new game's templates are used. Game thread only.
typedef BYTE (__fastcall* tIsEquiv)(void*, void*, void*);
static tIsEquiv o_isEquiv = NULL;
struct EqMemo { DWORD a, b, fab; BYTE r, used, pad[2]; };
#define EQ_N 8192
static EqMemo* g_eqMemo = NULL;
static volatile LONG g_eqHit = 0, g_eqMiss = 0, g_eqFast = 0, g_eqClears = 0;
static DWORD g_eqLastFrame = 0;
static __forceinline DWORD eqFinal(DWORD t) { DWORD n; while ((n = *(DWORD*)(ULONG_PTR)(t + 4)) != 0) t = n; return t; }
static void eqNewGameCheck() {
    DWORD gl = *(DWORD*)(ULONG_PTR)0x00DE412C;
    if (!gl) return;
    DWORD fr = *(DWORD*)(ULONG_PTR)(gl + 0x40);
    if (fr < g_eqLastFrame) { memset(g_eqMemo, 0, EQ_N * sizeof(EqMemo)); g_eqClears++; }
    g_eqLastFrame = fr;
}
static BYTE __fastcall hkIsEquiv(void* ecx, void* edx, void* other) {
    DWORD a = (DWORD)(ULONG_PTR)ecx, b = (DWORD)(ULONG_PTR)other;
    if (!a || !b || a == b || __readfsdword(0x24) != g_mkTid) return o_isEquiv(ecx, edx, other);
    DWORD fa = eqFinal(a), fb = eqFinal(b);
    if (fa == fb) { g_eqFast++; return 1; }                        // what the original returns for equal final overrides
    eqNewGameCheck();
    DWORD fab = fa ^ (fb * 0x9E3779B1u);
    EqMemo& e = g_eqMemo[((a * 2654435761u) ^ (b * 2246822519u)) >> 19];
    if (e.used && e.a == a && e.b == b && e.fab == fab) { g_eqHit++; return e.r; }
    BYTE r = o_isEquiv(ecx, edx, other);
    e.a = a; e.b = b; e.fab = fab; e.r = r; e.used = 1;
    g_eqMiss++;
    return r;
}
static void installEquivMemo() {
    static const BYTE kPre[] = {0x55,0x8B,0xEC,0x83,0xEC,0x0C,0x53,0x56,0x8B,0xF1,0x85,0xF6,0x57};
    static const BYTE kFinal[] = {0x8B,0xC1,0xEB,0x02,0x8B,0xC2,0x8B,0x50,0x04,0x85,0xD2,0x75,0xF7,0xC3};
    __try {
        if (memcmp((void*)0x0073D5C2, kPre, sizeof(kPre)) || memcmp((void*)0x00465AF4, kFinal, sizeof(kFinal))) {
            logf("equiv-memo: template equivalence code differs - memo OFF."); return;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { return; }
    g_eqMemo = (EqMemo*)VirtualAlloc(NULL, EQ_N * sizeof(EqMemo), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    o_isEquiv = (tIsEquiv)makeTrampoline((BYTE*)0x0073D5C2, 6);
    if (!g_eqMemo || !o_isEquiv) { logf("equiv-memo: alloc failed - memo OFF."); return; }
    HANDLE fz[256]; int nf = 0;
    suspendOthers(fz, &nf, 256);
    patchJmp((BYTE*)0x0073D5C2, (void*)&hkIsEquiv, 6);
    resumeAll(fz, nf);
    logf("equiv-memo: ThingTemplate::isEquivalentTo 0x73D5C2 memoized on the game thread (per template pair and final overrides; cleared each new game).");
}

// ---------------------------------------------------------------- object filter template memo (exact results)
// 0x763543 (thiscall: filter holder, template, player, team; bool; ret 0xC) is the object filter test that AI scans,
// prerequisite checks and "does this player have ..." loops run for every object of a player (5% of a battle frame).
// It first looks up the filter's entry in the table [0xDE78B0] (0x94 bytes per entry, index at [holder]), then applies
// the player/relationship checks, and from 0x763644 on decides from the entry's name, template and KindOf lists and the
// template alone (the entry and the template are INI data; the lazily written mode [entry+0x80] 0 -> 3 gives the same
// answer both ways). The memo keeps that second part's answer per (filter index, template): the whole function runs
// normally, a stub at 0x763644 returns the stored answer through the function's own exit when there is one, and
// otherwise the answer the function returns is stored. Cleared each new game, game thread only.
typedef BYTE (__fastcall* tObjFilter)(void*, void*, DWORD, DWORD, DWORD);
static tObjFilter o_objFilter = NULL;
struct FltMemo { DWORD id, t; BYTE r, used, pad[2]; };
#define FLT_N 32768
static FltMemo* g_flt = NULL;
static DWORD g_fltPendId = 0, g_fltPendT = 0, g_fltLastFrame = 0;
static BYTE g_fltActive = 0, g_fltPend = 0;
static volatile LONG g_fltHit = 0, g_fltMiss = 0, g_fltCalls = 0, g_fltClears = 0;
static DWORD kFltExit = 0x0076378B, kFltCont = 0x0076364A;
static BYTE __fastcall hkObjFilter(void* ecx, void* edx, DWORD t, DWORD p, DWORD team) {
    if (__readfsdword(0x24) != g_mkTid || g_fltActive) return o_objFilter(ecx, edx, t, p, team);
    DWORD gl = *(DWORD*)(ULONG_PTR)0x00DE412C;
    if (gl) { DWORD fr = *(DWORD*)(ULONG_PTR)(gl + 0x40); if (fr < g_fltLastFrame) { memset(g_flt, 0, FLT_N * sizeof(FltMemo)); g_fltClears++; } g_fltLastFrame = fr; }
    g_fltActive = 1; g_fltPend = 0; g_fltCalls++;
    BYTE r = o_objFilter(ecx, edx, t, p, team);
    g_fltActive = 0;
    if (g_fltPend) {
        g_fltPend = 0;
        FltMemo& e = g_flt[((g_fltPendId * 2654435761u) ^ (g_fltPendT * 2246822519u)) >> 17];
        e.id = g_fltPendId; e.t = g_fltPendT; e.r = r; e.used = 1;
    }
    return r;
}
static int __stdcall fltStatic(DWORD entry, DWORD t) {         // at 0x763644: -1 = run the template checks, else the answer
    if (!g_fltActive) return -1;
    DWORD base = *(DWORD*)(ULONG_PTR)0x00DE78B0;
    if (entry < base || (entry - base) % 0x94) return -1;
    DWORD id = (entry - base) / 0x94;
    const FltMemo& e = g_flt[((id * 2654435761u) ^ (t * 2246822519u)) >> 17];
    if (e.used && e.id == id && e.t == t) { g_fltHit++; return e.r; }
    g_fltPendId = id; g_fltPendT = t; g_fltPend = 1; g_fltMiss++;
    return -1;
}
static __declspec(naked) void fltStub() {
    __asm {
        push dword ptr [ebp + 8]
        push esi
        call fltStatic
        cmp eax, -1
        je fltMiss
        jmp dword ptr [kFltExit]
    fltMiss:
        mov edi, dword ptr [esi + 0x1C]
        sub edi, dword ptr [esi + 0x18]
        jmp dword ptr [kFltCont]
    }
}
static void installFilterMemo() {
    static const BYTE kEntry[] = {0xB8,0x5A,0x26,0xB9,0x00,0xE8};
    static const BYTE kStatic[] = {0x8B,0x7E,0x1C,0x2B,0x7E,0x18,0x33,0xDB,0xC1,0xFF,0x02};
    static const BYTE kExit[] = {0x5F,0x8B,0x4D,0xF4,0x5E,0x5B};
    static const BYTE kMode3[] = {0xC7,0x86,0x80,0x00,0x00,0x00,0x03,0x00,0x00,0x00};
    __try {
        if (memcmp((void*)0x00763543, kEntry, sizeof(kEntry)) || memcmp((void*)0x00763644, kStatic, sizeof(kStatic)) ||
            memcmp((void*)0x0076378B, kExit, sizeof(kExit)) || memcmp((void*)0x00763777, kMode3, sizeof(kMode3))) {
            logf("filter-memo: object filter code differs - memo OFF."); return;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { return; }
    g_flt = (FltMemo*)VirtualAlloc(NULL, FLT_N * sizeof(FltMemo), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    o_objFilter = (tObjFilter)makeTrampoline((BYTE*)0x00763543, 5);   // mov eax, imm32 (the next instruction is a relative call)
    if (!g_flt || !o_objFilter) { logf("filter-memo: alloc failed - memo OFF."); return; }
    HANDLE fz[256]; int nf = 0;
    suspendOthers(fz, &nf, 256);
    patchJmp((BYTE*)0x00763543, (void*)&hkObjFilter, 5);
    patchJmp((BYTE*)0x00763644, (void*)&fltStub, 6);
    resumeAll(fz, nf);
    logf("filter-memo: object filter 0x763543 template checks memoized per (filter, template) on the game thread.");
}
