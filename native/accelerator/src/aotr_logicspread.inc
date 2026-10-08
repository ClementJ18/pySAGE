// ================================================================ logic step: render frames inserted into the engine's own sequence (v26)
// The engine runs one logic step per six render frames by calling GameLogic::update(n) (0x62E4E8) with n = 1..6, and
// what each call does is hard-wired:
//   every n : clear the vector at this+0x164, run the pathfinder queue (0x6F2364) and 0x440809   ("pre-work")
//   n == 1  : commands, scripts, players ... and a per-object tail at the end of the call
//   n == 2  : two subsystem updates and a pass over all objects
//   n == 3  : module list 0, first half        n == 4 : list 0, second half        (lists: this+0xC8+12k)
//   n == 5  : lists 1 and 2, then AI::update, [destroy list], eleven subsystem updates + object deletion (~15 ms)
//   n == 6  : list 3
//   every n : the destroy list 0x629DA6 after the lists, then a short tail
// Measured in a battle that is 3 / 7 / 13 / 13 / 50 / 2 ms: one frame in six is a hitch and two idle in the frame
// limiter. v22-v25 moved the CUTS between the list halves (by clock, then by a cost model). That evened the frames
// out but changed where the per-call pre-work and destroy list fall relative to the module index - visible to the
// simulation, so not something a multiplayer game or a replay may depend on - and the cost model proved too crude
// (v25: the n4 slice predicted at 16 ms took 22).
//
// v26 does not move anything inside the sequence. The six logical calls U1..U6 run exactly as the engine wrote them,
// in order, each exactly once per step - the simulation is the stock one, bit for bit, whatever the timing. The only
// thing decided here is WHERE THE RENDER FRAMES FALL in that sequence:
//   - the engine's call for frame f is answered by a driver that runs logical calls until this frame's share of the
//     step's measured time is used up (frame 1 runs U1 and goes on into U2, U3...; frame 6 finishes whatever is left);
//   - a logical call can be left in the middle of a module list (before any module) or between its lists and the n5
//     block. Leaving skips the rest of the call (AI, destroy list, n5 block, tail) by going straight to the
//     function's epilogue; the next frame calls update(n) again in "resume" mode, where the pre-work is skipped (it
//     already ran for this logical call; the +0x164 vector must survive until the destroy list of this same call),
//     the list loop continues at the saved index, and everything after it runs as usual.
// The engine itself runs several update(n) calls in one render frame when its frame rate setting asks for it
// (dispatcher 0x6329B0), so back-to-back calls are native. Rendering between two module updates already happened at
// the list-half boundaries. Off (Pause/Break at the next step, or AOTR_LOGICSPREAD=0): the same stubs apply the
// engine's rules and the driver declines every call.

static volatile LONG g_lsWant = 1;                 // requested by the user (Pause key / env)
static volatile LONG g_lsInstalled = 0, g_lsToggles = 0;
static LONG  g_lsOn = 0;                           // in effect for the current step (decided at the engine's n == 1)
static DWORD g_lsThis = 0, g_lsStepFrame = 0, g_lsLastFrame = 0xFFFFFFFF;
static LONG  g_lsNext = 7;                         // next logical call to start or resume (2..6); 7 = the step is complete
static LONG  g_lsPaused = 0;                       // logical call g_lsNext was left unfinished ...
static LONG  g_lsAfterLists = 0;                   // ... after its lists, before the n5 block
static LONG  g_lsList = -1; static DWORD g_lsIndex = 0;   // ... or in list g_lsList, before index g_lsIndex
static LONG  g_lsInDriver = 0;                     // the function body is being run by the driver
static LONG  g_lsResume = 0;                       // ... as the continuation of a paused logical call
static LONG  g_lsEngineN = 0;
static LONG  g_lsStepDriven = 0;                   // U1 of the current step was run by the driver (else the whole step is the engine's)
static ULONG64 g_lsT0 = 0, g_lsBudget = 0;         // this frame: start and budget in rdtsc ticks (0 = run to the end)
static ULONG64 g_lsStepTicks = 0, g_lsTotalEma = 0, g_lsSubsEma = 0, g_lsSubsAtStep = 0;
static volatile LONG g_lsSteps = 0, g_lsStockSteps = 0, g_lsPausesList = 0, g_lsPausesBlock = 0, g_lsOdd = 0, g_lsCatchUp = 0, g_lsMatches = 0;
static volatile LONG g_lsStarted[8][8];            // [engine frame][logical call]: started or resumed there (report)
static volatile ULONG64 g_lsMinTicks = 6000000;    // ~2 ms: a step cheaper than this is left to the engine (refined by the report thread)
static ULONG64 g_lsFrameTicks[8];                  // this step: time the driver spent in each engine frame
static LONG  g_lsFactor = 920;                     // frames 1-5 get step * factor / 6000; tuned so that frame 6 comes out like the others (v26: a fixed 1042 left it at 56%)
static LONG  g_lsExpect = -1;                      // self-check: the index the list loop must ask about next (-1 = any: a list or a logical call just started)
static volatile LONG g_lsSeqBad = 0, g_lsSeqChecked = 0;

static __forceinline DWORD lsCount(const DWORD* hdr) { return (hdr[1] - hdr[0]) >> 2; }
static ULONG64 lsSubsTotal() { ULONG64 s = 0; for (int k = 1; k < SUB_N; ++k) s += (ULONG64)g_subT[k]; return s; }   // the n5 block (without AI::update, which runs before it)
static __forceinline bool lsOverBudget() { return g_lsBudget && (__rdtsc() - g_lsT0) >= g_lsBudget; }

// ---- the list loop: the engine's own rules, plus "continue where the paused call stopped"
// which lists this call visits: returns the first list, -1 for none; *last = one past the last list
static int __stdcall lsBegin(DWORD self, DWORD n, LONG* last) {
    int first;
    if (n == 3 || n == 4) { first = 0; *last = 1; }
    else if (n == 5) { first = 1; *last = 3; }
    else if (n == 6) { first = 3; *last = 4; }
    else return -1;
    if (g_lsInDriver && g_lsResume) {
        if (g_lsAfterLists) return -1;                                  // its lists are done: straight to what follows them
        if (g_lsList > first && g_lsList < *last) first = g_lsList;
    }
    return first;
}
// index to start list k at, minus one (the loop increments before use)
static int __stdcall lsStart(const DWORD* hdr, LONG k, DWORD n) {
    DWORD c = lsCount(hdr);
    if (g_lsInDriver && g_lsResume && k == g_lsList) {
        DWORD r = g_lsIndex; if (r > c) { r = c; g_lsOdd++; }
        g_lsList = -1;                                                  // used once
        g_lsExpect = (LONG)r;                                           // the module the paused call was about to process
        return (int)r - 1;
    }
    g_lsExpect = -1;                                                    // a list starts where the engine says
    return n == 4 ? (int)(c >> 1) - 1 : -1;
}
// about to process index i of list k: 0 go on, 1 the engine's own stop (first half of list 0 done), 2 leave the call here
static int __stdcall lsStop(const DWORD* hdr, LONG k, DWORD i, DWORD n) {
    if (g_lsInDriver) {
        if (g_lsExpect >= 0) { g_lsSeqChecked++; if ((DWORD)g_lsExpect != i && g_lsSeqBad++ < 4) logf("logicspread: SEQUENCE - list %d asked about index %u, expected %d (logical call %u, engine frame %d).", (int)k, i, (int)g_lsExpect, n, (int)g_lsEngineN); }
        g_lsExpect = (LONG)i + 1;
    }
    if (n == 3 && i == (lsCount(hdr) >> 1)) return 1;
    if (g_lsInDriver && g_lsEngineN != 6 && lsOverBudget()) { g_lsList = k; g_lsIndex = i; g_lsAfterLists = 0; g_lsPaused = 1; g_lsPausesList++; return 2; }
    return 0;
}
// list k ran to its end: 1 = run the engine's clean-up pass over it (modules that sleep forever leave the list)
static int __stdcall lsDone(LONG k, DWORD n) { return n > 3; }
// after the lists: 0 not n5 (on to the destroy list), 1 n5 (AI::update first), 2 leave the call here - the n5 block gets a frame of its own
static int __stdcall lsAfter(DWORD self, DWORD n) {
    if (n != 5) return 0;
    if (g_lsInDriver && g_lsEngineN != 6 && g_lsBudget && !(g_lsResume && g_lsAfterLists)) {
        ULONG64 used = __rdtsc() - g_lsT0;
        if (used + g_lsSubsEma > g_lsBudget + g_lsBudget / 4) { g_lsAfterLists = 1; g_lsPaused = 1; g_lsPausesBlock++; return 2; }
    }
    return 1;
}

// ---- the driver
#ifndef LS_UPDATE_ADDR
#define LS_UPDATE_ADDR 0x0062E4E8                   // GameLogic::update (the offline model substitutes its own)
#endif
typedef void (__fastcall* tLsUpdate)(DWORD, void*, DWORD);
static void lsRunLogical(DWORD self, LONG n) {
    g_lsResume = g_lsPaused; g_lsPaused = 0;
    if (!g_lsResume) { g_lsAfterLists = 0; g_lsList = -1; g_lsIndex = 0; }
    if (g_lsEngineN >= 0 && g_lsEngineN < 8 && n >= 0 && n < 8) g_lsStarted[g_lsEngineN][n]++;
    g_lsInDriver = 1;
    ((tLsUpdate)(ULONG_PTR)LS_UPDATE_ADDR)(self, NULL, (DWORD)n);       // the entry stub lets the driver's own calls through
    g_lsInDriver = 0; g_lsResume = 0;
    if (!g_lsPaused) { g_lsNext = n + 1; g_lsAfterLists = 0; g_lsList = -1; }
}
static void lsStepClosed() {                                           // the step's measured cost, for the next step's budgets
    if (g_lsStepDriven && g_lsFrameTicks[6]) {                          // timing only - nothing here can change what the logic does
        ULONG64 m = (g_lsFrameTicks[1] + g_lsFrameTicks[2] + g_lsFrameTicks[3] + g_lsFrameTicks[4] + g_lsFrameTicks[5]) / 5, l = g_lsFrameTicks[6];
        if (l * 100 < m * 92) { if (g_lsFactor > 700) g_lsFactor -= 4; } else if (l * 100 > m * 104) { if (g_lsFactor < 1100) g_lsFactor += 8; }   // quicker to back off: a heavy last frame is the worse error
    }
    for (int i = 0; i < 8; ++i) g_lsFrameTicks[i] = 0;
    if (g_lsStepTicks) {
        ULONG64 t = g_lsStepTicks; if (g_lsTotalEma && t > g_lsTotalEma * 3) t = g_lsTotalEma * 3;        // a loading hitch does not set the budgets
        g_lsTotalEma = g_lsTotalEma ? (g_lsTotalEma * 3 + t) / 4 : t;
        ULONG64 subs = lsSubsTotal(), s = subs - g_lsSubsAtStep; g_lsSubsAtStep = subs;
        g_lsSubsEma = g_lsSubsEma ? (g_lsSubsEma * 3 + s) / 4 : s;
    }
    g_lsStepTicks = 0;
}
// the engine's update(n) call. 1 = answered here (the caller gets a plain return), 0 = run the engine's body for n
static int __stdcall lsDrive(DWORD self, DWORD ne) {
    ULONG64 t0 = __rdtsc();
    DWORD fr = *(DWORD*)(ULONG_PTR)(self + 0x40);
    if (ne == 1) {
        if (g_lsOn && g_lsNext <= 6) {                                  // the engine started a new step before asking for all six frames of the last one
            if (self == g_lsThis && fr == g_lsStepFrame) { g_lsCatchUp++; g_lsEngineN = 6; g_lsBudget = 0; g_lsT0 = t0; while (g_lsNext <= 6) lsRunLogical(self, g_lsNext); }
            else { g_lsOdd++; g_lsNext = 7; g_lsPaused = 0; }           // another world: nothing of the old step may be continued
        }
        lsStepClosed();
        if (fr < g_lsLastFrame) { g_lsTotalEma = 0; g_lsSubsEma = 0; g_lsMatches++;   // the frame counter started over: a new match measures itself first
            // One line per match. The slicer keeps the engine's own call order, so a network game cannot desync
            // on it, but it has never actually been played against another machine. This records which mode the
            // match is (GameLogic+0x110) so the modes can be told apart without a diagnostic build; SLICER_OFF
            // next to the DLL turns the slicer off outright for a session where that guarantee has to be absolute.
            logf("logicspread: new match, game mode %d.", (int)*(DWORD*)(ULONG_PTR)(self + 0x110));
        }
        LONG want = g_lsWant;
        if (want != g_lsOn) { g_lsOn = want; logf("logicspread: %s from this logic step on.", want ? "ON - render frames are placed inside the engine's logic sequence by time" : "OFF - one engine call per frame"); }
        g_lsThis = self; g_lsNext = 7; g_lsPaused = 0; g_lsStepDriven = 0;
    }
    g_lsLastFrame = fr;
    bool drive = g_lsOn && g_lsTotalEma >= g_lsMinTicks && self == g_lsThis && ne >= 1 && ne <= 6 && (ne == 1 || g_lsStepDriven);
    if (drive && ne != 1 && fr != g_lsStepFrame) { drive = false; g_lsOdd++; g_lsNext = 7; g_lsPaused = 0; g_lsStepDriven = 0; }
    if (drive && *(BYTE*)(ULONG_PTR)(self + 0x125)) {                   // single-player pause: the engine's body returns at once; nothing is scheduled meanwhile
        DWORD mode = *(DWORD*)(ULONG_PTR)(self + 0x110);
        if (mode != 1 && mode != 5) return 0;
    }
    if (!drive) { if (ne == 1) g_lsStockSteps++; return 0; }             // (the step is then measured by lsFrameDone)
    if (ne == 1) { g_lsSteps++; g_lsStepDriven = 1; }
    g_lsEngineN = (LONG)ne; g_lsT0 = t0;
    g_lsBudget = ne == 6 ? 0 : g_lsTotalEma * (ULONG64)g_lsFactor / 6000;   // frames 1-5: a tuned sixth of the step; frame 6 takes what is left
    if (ne == 1) { g_lsNext = 1; g_lsPaused = 0; lsRunLogical(self, 1); g_lsStepFrame = *(DWORD*)(ULONG_PTR)(self + 0x40); }   // U1 (it advances the frame counter)
    while (g_lsNext <= 6) {
        if (!g_lsPaused && ne != 6 && lsOverBudget()) break;            // the next logical call starts in the next frame
        lsRunLogical(self, g_lsNext);
        if (g_lsPaused) break;
    }
    { ULONG64 dt = __rdtsc() - t0; g_lsStepTicks += dt; g_lsFrameTicks[ne] += dt; }
    return 1;
}
// from the dispatcher hook: a frame of a step that was not driven (the first step of a match, or OFF) is measured here
static void lsFrameDone(DWORD ne, ULONG64 ticks) {
    if (!g_lsInstalled) return;
    if (!g_lsStepDriven) g_lsStepTicks += ticks;
}
// before the dispatcher runs: no body can be active here. If the flags say otherwise, an exception left through the
// driver - forget the step's schedule rather than skip pre-work for ever.
static void lsFrameBegin() {
    if (g_lsInDriver || g_lsResume) { g_lsInDriver = 0; g_lsResume = 0; g_lsPaused = 0; g_lsNext = 7; g_lsStepDriven = 0; g_lsOdd++; }
}

static __declspec(naked) void lsStubEntry() {      // 0x62E4E8: mov eax, 0xB841DA (the SEH prologue's argument)
    __asm {
        cmp  dword ptr [g_lsInDriver], 0
        jne  lsN_body
        push ecx
        push dword ptr [esp + 8]                       // n
        push ecx                                       // this
        call lsDrive
        pop  ecx
        test eax, eax
        jz   lsN_body
        ret  4                                         // answered by the driver
    lsN_body:
        mov  eax, 0x00B841DA
        push 0x0062E4ED
        ret
    }
}
static __declspec(naked) void lsStubP1() {         // 0x62E5A7: call 0x5FF9D3 - clear the vector at this+0x164 (thiscall, 2 arguments)
    __asm {                                        // kept while a logical call is unfinished (also across the engine's own early-out calls during a single-player pause)
        cmp  dword ptr [g_lsResume], 0
        jne  lsP1_skip
        cmp  dword ptr [g_lsPaused], 0
        jne  lsP1_skip
        mov  eax, 0x005FF9D3
        jmp  eax
    lsP1_skip:
        ret  8
    }
}
static __declspec(naked) void lsStubP2a() {        // 0x62E69F: call 0x6F2364 - pathfinder queue
    __asm {
        cmp  dword ptr [g_lsResume], 0
        jne  lsP2a_skip
        mov  eax, 0x006F2364
        jmp  eax
    lsP2a_skip:
        ret
    }
}
static __declspec(naked) void lsStubP2b() {        // 0x62E6A4: call 0x440809
    __asm {
        cmp  dword ptr [g_lsResume], 0
        jne  lsP2b_skip
        mov  eax, 0x00440809
        jmp  eax
    lsP2b_skip:
        ret
    }
}
static __declspec(naked) void lsStubA() {          // 0x62E982: gate and list range
    __asm {
        lea  eax, [ebp - 0x20]
        push eax
        push dword ptr [ebp + 8]
        push esi
        call lsBegin
        cmp  eax, -1
        je   lsA_none
        mov  edi, eax
        mov  eax, 0x0062E9BE
        jmp  eax
    lsA_none:
        mov  eax, 0x0062EB63
        jmp  eax
    }
}
static __declspec(naked) void lsStubB() {          // 0x62E9D4: start index of this list (eax = start - 1)
    __asm {
        push dword ptr [ebp + 8]
        push dword ptr [ebp - 0x18]
        push edi
        call lsStart
        mov  ecx, 0x0062E9EA
        jmp  ecx
    }
}
static __declspec(naked) void lsStubC() {          // 0x62EA09: about to process index eax
    __asm {
        mov  dword ptr [ebp - 0x1c], eax
        push dword ptr [ebp + 8]
        push eax
        push dword ptr [ebp - 0x18]
        push edi
        call lsStop
        test eax, eax
        jnz  lsC_stop
        mov  eax, 0x0062EA24
        jmp  eax
    lsC_stop:
        cmp  eax, 2
        je   lsC_leave
        mov  eax, 0x0062EB51                           // the engine's own stop: on to the loop tail
        jmp  eax
    lsC_leave:
        xor  ebx, ebx                                  // the epilogue compares against a zero ebx, as on the normal way there
        mov  eax, 0x0062EE45
        jmp  eax
    }
}
static __declspec(naked) void lsStubD() {          // 0x62EADF: the list is finished
    __asm {
        push dword ptr [ebp + 8]
        push dword ptr [ebp - 0x18]
        call lsDone
        test eax, eax
        jz   lsD_skip
        mov  eax, 0x0062EAE5
        jmp  eax
    lsD_skip:
        mov  eax, 0x0062EB51
        jmp  eax
    }
}
static __declspec(naked) void lsStubF() {          // 0x62EB63: cmp [ebp+8],5 / jne 0x62EB74 - after the lists
    __asm {
        push dword ptr [ebp + 8]
        push esi
        call lsAfter
        cmp  eax, 1
        je   lsF_ai
        ja   lsF_leave
        mov  eax, 0x0062EB74
        jmp  eax
    lsF_ai:
        mov  eax, 0x0062EB69
        jmp  eax
    lsF_leave:
        xor  ebx, ebx
        mov  eax, 0x0062EE45
        jmp  eax
    }
}
static void lsSetCall(DWORD site, void* fn) {
    BYTE* q = (BYTE*)(ULONG_PTR)site; DWORD op = 0;
    if (!VirtualProtect(q, 5, PAGE_EXECUTE_READWRITE, &op)) return;
    *(LONG*)(q + 1) = (LONG)((DWORD)(ULONG_PTR)fn - (site + 5));
    VirtualProtect(q, 5, op, &op);
    FlushInstructionCache(GetCurrentProcess(), q, 5);
}
static void installLogicSpread() {
    static const BYTE kA[] = { 0x0F, 0x8E, 0xDB, 0x01, 0x00, 0x00 };                                   // 0x62E982 jle 0x62EB63
    static const BYTE kA0[] = { 0x83, 0x7D, 0x08, 0x02 };                                              // 0x62E97E cmp [ebp+8], 2 (kept)
    static const BYTE kB[] = { 0x83, 0x7D, 0x08, 0x04, 0x75, 0x0D, 0x8B, 0x47, 0x04, 0x2B, 0x07, 0xC1, 0xF8, 0x02, 0xD1, 0xE8, 0x48, 0xEB, 0x03, 0x83, 0xC8, 0xFF };
    static const BYTE kC[] = { 0x83, 0x7D, 0x08, 0x03, 0x89, 0x45, 0xE4, 0x75, 0x12, 0x8B, 0x4F, 0x04, 0x2B, 0x0F, 0xC1, 0xF9, 0x02, 0xD1, 0xE9, 0x3B, 0xC1, 0x0F, 0x84, 0x2D, 0x01, 0x00, 0x00 };
    static const BYTE kD[] = { 0x83, 0x7D, 0x08, 0x03, 0x7E, 0x6C };
    static const BYTE kTail[] = { 0xFF, 0x45, 0xE8, 0x8B, 0x45, 0xE8, 0x83, 0xC7, 0x0C, 0x3B, 0x45, 0xE0, 0x0F, 0x8C, 0x71, 0xFE, 0xFF, 0xFF };   // 0x62EB51 loop tail
    static const BYTE kF[] = { 0x83, 0x7D, 0x08, 0x05, 0x75, 0x0B };                                   // 0x62EB63 cmp [ebp+8],5 / jne 0x62EB74
    static const BYTE kN[] = { 0xB8, 0xDA, 0x41, 0xB8, 0x00, 0xE8 };                                   // 0x62E4E8 mov eax, 0xB841DA / call
    static const BYTE kEpi[] = { 0x8B, 0x45, 0xD8, 0x8A, 0x4D, 0xCC, 0x88, 0x08, 0xA1, 0x2C, 0x41, 0xDE, 0x00, 0x3B, 0xC3 };   // 0x62EE45 epilogue: restore the guard, cmp eax, ebx
    static const BYTE kP1[] = { 0x8D, 0x8E, 0x64, 0x01, 0x00, 0x00, 0x8B, 0x41, 0x04, 0x8B, 0x11, 0x50, 0x52, 0xE8 };           // 0x62E59A ... call 0x5FF9D3
    static const BYTE kP2[] = { 0xA1, 0x40, 0x4B, 0xDE, 0x00, 0x8B, 0x48, 0x10, 0xE8 };                                         // 0x62E697 ... call 0x6F2364
    bool ok = false;
    __try {
        ok = !memcmp((void*)0x0062E982, kA, sizeof(kA)) && !memcmp((void*)0x0062E97E, kA0, sizeof(kA0)) && !memcmp((void*)0x0062E9D4, kB, sizeof(kB)) &&
             !memcmp((void*)0x0062EA09, kC, sizeof(kC)) && !memcmp((void*)0x0062EADF, kD, sizeof(kD)) && !memcmp((void*)0x0062EB51, kTail, sizeof(kTail)) &&
             !memcmp((void*)0x0062EB63, kF, sizeof(kF)) && !memcmp((void*)0x0062E4E8, kN, sizeof(kN)) && !memcmp((void*)0x0062EE45, kEpi, sizeof(kEpi)) &&
             !memcmp((void*)0x0062E59A, kP1, sizeof(kP1)) && (0x0062E5A7 + 5 + *(LONG*)0x0062E5A8) == 0x005FF9D3 &&
             !memcmp((void*)0x0062E697, kP2, sizeof(kP2)) && (0x0062E69F + 5 + *(LONG*)0x0062E6A0) == 0x006F2364 &&
             *(BYTE*)0x0062E6A4 == 0xE8 && (0x0062E6A4 + 5 + *(LONG*)0x0062E6A5) == 0x00440809;
    } __except (EXCEPTION_EXECUTE_HANDLER) { ok = false; }
    if (!ok) { logf("logicspread: GameLogic::update differs from the analysed build - OFF (engine schedule untouched)."); return; }
    if (!g_subGlob[0]) { logf("logicspread: the n5 subsystem timers are not installed - OFF."); return; }
    char env[8]; env[0] = 0;
    if (GetEnvironmentVariableA("AOTR_LOGICSPREAD", env, sizeof(env)) && env[0] == '0') g_lsWant = 0;
    { char mk[MAX_PATH];                                   // the loader runs elevated, so a marker file is the switch that works
      if (GetFileAttributesA(aotrPath(mk, "SLICER_OFF")) != INVALID_FILE_ATTRIBUTES) {
          logf("logicspread: SLICER_OFF is present - the engine's frame schedule is left exactly as it ships.");
          return;
      } }
    g_lsSubsAtStep = lsSubsTotal();
    HANDLE fz[256]; int nf = 0;
    suspendOthers(fz, &nf, 256);
    patchJmp((BYTE*)0x0062E982, (void*)&lsStubA, sizeof(kA));
    patchJmp((BYTE*)0x0062E9D4, (void*)&lsStubB, sizeof(kB));
    patchJmp((BYTE*)0x0062EA09, (void*)&lsStubC, sizeof(kC));
    patchJmp((BYTE*)0x0062EADF, (void*)&lsStubD, sizeof(kD));
    patchJmp((BYTE*)0x0062EB63, (void*)&lsStubF, sizeof(kF));
    lsSetCall(0x0062E5A7, (void*)&lsStubP1);
    lsSetCall(0x0062E69F, (void*)&lsStubP2a);
    lsSetCall(0x0062E6A4, (void*)&lsStubP2b);
    patchJmp((BYTE*)0x0062E4E8, (void*)&lsStubEntry, 5);
    resumeAll(fz, nf);
    g_lsInstalled = 1;
    logf("logicspread: v26 - the engine's six logical update calls run unchanged and in order; render frames are placed inside that sequence by measured time (9 sites). %s. Pause/Break toggles it.",
         g_lsWant ? "On once one step has been measured" : "Starting OFF (AOTR_LOGICSPREAD=0)");
}
static void lsReport(LONG f) {
    if (!g_lsInstalled || f <= 0) return;
    static LONG lSteps = 0, lStock = 0, lPl = 0, lPb = 0; static LONG lSt[8][8];
    LONG st = g_lsSteps, sk = g_lsStockSteps, pl = g_lsPausesList, pb = g_lsPausesBlock;
    double k = (g_tscPerQpc > 0 && g_pqpf.QuadPart) ? 1000.0 / (g_tscPerQpc * (double)g_pqpf.QuadPart) : 0.0;     // ticks -> ms
    LONG ds = st - lSteps; if (ds < 1) ds = 1;
    if (k > 0) g_lsMinTicks = (ULONG64)(2.0 / k);
    char a[24], b[24], c[24], d1[24], d2[24];
    sprintf_s(a, "%.1f", (double)g_lsTotalEma * k); sprintf_s(b, "%.1f (x%d.%03d)", (double)(g_lsTotalEma * (ULONG64)g_lsFactor / 6000) * k, (int)(g_lsFactor / 1000), (int)(g_lsFactor % 1000)); sprintf_s(c, "%.1f", (double)g_lsSubsEma * k);
    sprintf_s(d1, "%.1f", (double)(pl - lPl) / (double)ds); sprintf_s(d2, "%.2f", (double)(pb - lPb) / (double)ds);
    char ln[1000]; int q = 0;
    q += wsprintfA(ln + q, "rt: logic slicer %s | steps sliced %d, engine-schedule %d | step %s ms, frame budget %s ms, n5 block %s ms | leaves per step: in a list %s, before the n5 block %s | logical calls started or resumed per engine frame:",
                   g_lsOn ? "ON" : "off", (int)(st - lSteps), (int)(sk - lStock), a, b, c, d1, d2);
    for (int e = 1; e <= 6; ++e) {
        q += wsprintfA(ln + q, " f%d[", e);
        for (int n = 1; n <= 6; ++n) { LONG v = g_lsStarted[e][n], dv = v - lSt[e][n]; lSt[e][n] = v; if (dv > 0) { char t[24]; sprintf_s(t, "%.1f", (double)dv / (double)ds); q += wsprintfA(ln + q, "U%d:%s ", n, t); } }
        q += wsprintfA(ln + q, "]");
    }
    q += wsprintfA(ln + q, " | order self-check: %d indices, %d out of sequence", (int)g_lsSeqChecked, (int)g_lsSeqBad);
    if (g_lsOdd || g_lsCatchUp) q += wsprintfA(ln + q, " | odd %d catch-up %d", (int)g_lsOdd, (int)g_lsCatchUp);
    q += wsprintfA(ln + q, " | matches %d", (int)g_lsMatches);
    logf("%s", ln);
    lSteps = st; lStock = sk; lPl = pl; lPb = pb;
}
