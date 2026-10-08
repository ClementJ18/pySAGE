// ================================================================ crash log (diagnostic only)
// The Windows event log shows the game dying with an access violation inside its own heap code (game.dat+0x3330A, the
// free-chunk unlink of its dlmalloc) at the end of nearly every session since 2026-09-09 - always after "Exit" was
// pressed. The event log has no call chain, so it cannot say whose teardown frees or overruns what. This handler
// writes that down: exception code and address, the registers, the address touched, and every return address on the
// stack that points behind a call in game.dat or into this DLL. It changes nothing: it always returns
// EXCEPTION_CONTINUE_SEARCH, so whoever handled (or did not handle) the exception before still does.
// First-chance exceptions that are then handled would be logged too, so: access violations, illegal instructions,
// stack overflows and integer divides only, outside this DLL's own code, and at most 12 entries per process. AOTR_CRASHLOG=0 turns it off.
static volatile LONG g_clN = 0, g_clBusy = 0;
static LONG CALLBACK clHandler(EXCEPTION_POINTERS* ep) {
    if (!ep || !ep->ExceptionRecord || !ep->ContextRecord) return EXCEPTION_CONTINUE_SEARCH;
    DWORD code = ep->ExceptionRecord->ExceptionCode;
    if (code != 0xC0000005u && code != 0xC000001Du && code != 0xC00000FDu && code != 0xC0000094u) return EXCEPTION_CONTINUE_SEARCH;
    { DWORD ip = (DWORD)(ULONG_PTR)ep->ExceptionRecord->ExceptionAddress;                         // this DLL's own guarded probes fault on purpose and handle it themselves (v25: they used up the entries)
      if (g_selfLo && ip >= g_selfLo && ip < g_selfHi) return EXCEPTION_CONTINUE_SEARCH; }
    if (InterlockedIncrement(&g_clN) > 12) return EXCEPTION_CONTINUE_SEARCH;
    if (InterlockedExchange(&g_clBusy, 1)) return EXCEPTION_CONTINUE_SEARCH;               // an exception raised while this handler is writing: not its business
    const CONTEXT* c = ep->ContextRecord;
    char sym[160]; symName((DWORD)(ULONG_PTR)ep->ExceptionRecord->ExceptionAddress, sym);
    DWORD rw = ep->ExceptionRecord->NumberParameters >= 2 ? (DWORD)ep->ExceptionRecord->ExceptionInformation[0] : 9, at = ep->ExceptionRecord->NumberParameters >= 2 ? (DWORD)ep->ExceptionRecord->ExceptionInformation[1] : 0;
    logf("crash: exception %08X at %s (thread %u, %s %08X) | eax %08X ebx %08X ecx %08X edx %08X esi %08X edi %08X ebp %08X esp %08X | phase %d, logic sub-frame %d, frame %d",
         code, sym, GetCurrentThreadId(), rw == 0 ? "reading" : (rw == 1 ? "writing" : (rw == 8 ? "executing" : "touching")), at,
         c->Eax, c->Ebx, c->Ecx, c->Edx, c->Esi, c->Edi, c->Ebp, c->Esp, (int)g_phase, (int)g_lgCurN, (int)g_mkFrames);
    if (code == 0xC00000FDu) { g_clBusy = 0; return EXCEPTION_CONTINUE_SEARCH; }                  // no stack left to walk with
    char ln[1400]; int q = 0, found = 0;
    __try {
        NT_TIB* tib = (NT_TIB*)NtCurrentTeb();
        DWORD lo = c->Esp & ~3u, hi = (DWORD)(ULONG_PTR)tib->StackBase;
        if (hi > lo + 0x6000) hi = lo + 0x6000;                                                  // the nearest 24 KB of stack
        for (DWORD p = lo; p + 4 <= hi && found < 40; p += 4) {
            DWORD v = *(DWORD*)(ULONG_PTR)p;
            bool game = g_textLo && gsIsRet(v), self = g_selfLo && v >= g_selfLo && v < g_selfHi;
            if (!game && !self) continue;
            char s2[160]; symName(v, s2);
            q += wsprintfA(ln + q, " %s", s2); ++found;
            if (q > 1200) break;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { q += wsprintfA(ln + q, " (stack unreadable)"); }
    ln[q] = 0;
    logf("crash:   return addresses on the stack (nearest first, may include stale ones):%s", ln);
    g_clBusy = 0;
    return EXCEPTION_CONTINUE_SEARCH;
}
static void installCrashLog() {
    char env[8]; env[0] = 0;
    if (GetEnvironmentVariableA("AOTR_CRASHLOG", env, sizeof(env)) && env[0] == '0') return;
    if (!g_selfLo) { HMODULE hs = NULL;
        if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)&clHandler, &hs) && hs) {
            IMAGE_NT_HEADERS* nh = (IMAGE_NT_HEADERS*)((BYTE*)hs + ((IMAGE_DOS_HEADER*)hs)->e_lfanew); g_selfLo = (DWORD)(ULONG_PTR)hs; g_selfHi = g_selfLo + nh->OptionalHeader.SizeOfImage; } }
    if (AddVectoredExceptionHandler(1, clHandler)) logf("crashlog: fatal exceptions will be written here with their call chain (nothing is handled or changed).");
}
