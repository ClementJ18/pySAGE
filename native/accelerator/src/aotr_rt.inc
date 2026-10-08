// ================================================================ render thread (RT) v1 (2026-09-15)
// Moves all Direct3D 9 device work and all ID3DXEffect work off the game's render thread onto one
// dedicated worker thread. The game's own render code keeps running on its thread (it is not
// thread-safe), but every IDirect3DDevice9 / resource / ID3DXEffect call it makes is recorded into an
// ordered command queue, with arguments and all pointed-to data copied at call time, and executed on
// the worker in exactly the same order. Calls that must return live data (Get*, Create*, Lock, ...)
// first wait for the worker to finish everything queued before them, then run on the game thread while
// the worker is parked, so the device never sees two threads at once and the call order never changes.
// Output is identical by construction. The gain: D3DX effect work (~16% of a battle frame) and DXVK's
// front-end (~5%) run in parallel with the game's own frame work, for the shadow pass and the main view.
//
// Classes hooked (whole vtables): IDirect3DDevice9 (119), ID3DXEffect (79), Texture/Cube/Volume textures,
// Surface, Volume, Vertex/Index buffers, StateBlock, Query, SwapChain. D3DX global functions that touch
// the device (effect/texture creation, surface loads, mip filtering) run as one exclusive scope.
// Kill switch: environment variable AOTR_RT=0.

#include <emmintrin.h>
#include <float.h>

static volatile LONG g_rtActive = 0;
static bool  g_rtTried = false;
static volatile LONG g_rtInitDone = 0;
static DWORD g_rtMainTid = 0, g_rtWorkerTid = 0;

// The loader calls SageAccelInitialize on the engine's Direct3D resolve thread.
// Effect-call counts cannot distinguish this thread from the loading-screen thread.
static __forceinline bool rtIsGameThread(DWORD tid) {
    return g_mkTid != 0 && tid == g_mkTid;
}
static bool rtRehookDevice(void* dev);
static void rtEnterExec();
static int   g_rtDirectScope = 0;                     // game thread only: inside an exclusive D3DX scope
static int   g_rtXDepth = 0;                          // render thread: nesting depth of D3DX global calls (install waits for 0)
static CRITICAL_SECTION g_rtInitCs;                  // serializes rtInit between the init thread and test entry points
static CRITICAL_SECTION g_rtExecCs;                   // held by whoever is executing device/D3DX work
static HANDLE g_rtWake = NULL, g_rtDrained = NULL, g_rtPresented = NULL, g_rtReady = NULL;
static volatile LONG g_rtWorkerSleeping = 0, g_rtDrainWaiting = 0, g_rtMainSleeping = 0;
static volatile LONG g_rtQHit = 0, g_rtQMiss = 0, g_rtNStaged = 0, g_rtNStageFallback = 0;
__declspec(align(64)) struct RtProdHot { DWORD localHead; DWORD cachedTail; DWORD seq; DWORD unpublished; LONG nAsync; LONG64 bytes; DWORD pubN; DWORD lastCpu; LONG cpuSib, cpuOther, cpuMigr; };   // game thread only
__declspec(align(64)) struct RtPubHot  { volatile DWORD head; };                                        // game thread writes, worker reads once per batch
__declspec(align(64)) struct RtLockHot { volatile LONG want; };                                        // game thread sets around a direct call; worker reads per record
__declspec(align(64)) struct RtWorkHot { volatile DWORD tail; volatile DWORD execSeq; volatile LONG64 busy; volatile DWORD cpu; };   // worker writes once per batch
static RtProdHot g_rtPH; static RtPubHot g_rtPB; static RtWorkHot g_rtWH; static RtLockHot g_rtLK;
static volatile DWORD g_rtDrainSeq = 0;
static bool g_rtObjRefs = true;                         // AddRef objects in queued records (off once every class has a Release hook)
#define g_rtLocalHead g_rtPH.localHead
#define g_rtSeq       g_rtPH.seq
#define g_rtHead      g_rtPB.head
#define g_rtTail      g_rtWH.tail
#define g_rtExecSeq   g_rtWH.execSeq
#define RT_BUF_SIZE (32u << 20)                        // power of two
static BYTE* g_rtBuf = NULL;
static volatile LONG g_rtPendingPresents = 0;
// Present runs on the worker, so its HRESULT arrives after the game thread has already returned from Present.
// The game thread therefore returns the result of the PREVIOUS Present. That matters in exactly one case and it
// is the case that used to crash: the game runs fullscreen exclusive, so minimising loses the device, and the
// engine only learns that from Present's return value. Returning a hardcoded D3D_OK meant it never learned, kept
// drawing into a lost device and died in its own memory code on the way back. Device loss persists until a
// successful Reset, so reporting it one frame late loses nothing - the engine sees it, calls
// TestCooperativeLevel (which is synchronous and truthful) and resets. While the device is healthy this is 0,
// exactly what was returned before.
static volatile LONG g_rtPresentHR = 0;
static volatile LONG g_rtNSync = 0, g_rtNRelease = 0, g_rtNForeign = 0, g_rtNPresent = 0, g_rtNScope = 0;
static volatile LONG g_rtNLocked = 0, g_rtNDirectLock = 0, g_rtNDirectUnlock = 0, g_rtNMirror = 0;
static volatile int g_rtWorkerOp = 511;
static int g_rtCurOp = 511;                                // game thread: op whose synchronous path is draining (511 = internal)
static volatile LONG64 g_rtDrainOpTicks[512];
static volatile LONG64 g_rtDrainTicks = 0, g_rtPresentWaitTicks = 0;
static volatile LONG g_rtOpN[512];                      // queued calls per op (diagnostic)
#define g_rtNAsync g_rtPH.nAsync
#define g_rtBytes g_rtPH.bytes
#define g_rtBusyTicks g_rtWH.busy
static volatile LONG g_rtSyncHist[512];
static DWORD g_d3d9Lo2 = 0, g_d3d9Hi2 = 0, g_dxLo = 0, g_dxHi = 0;
static unsigned int g_rtX87 = 0, g_rtMxcsr = 0;             // game thread floating-point state, mirrored on the worker
static volatile LONG g_rtInstalled = 0;                       // worker running and all vtables hooked (toggle-able)
static volatile LONG g_rtWantOn = 1, g_rtToggles = 0;           // live A/B switch (Scroll Lock), applied at Present on the render thread

struct RtRec {
    WORD  kind;      // 1 = call, 2 = wrap to buffer start
    BYTE  nargs;     // stdcall arguments including `this`
    BYTE  flags;     // bit0 = Present (frame bookkeeping after execution)
    DWORD size;      // whole record, 16-byte aligned
    void* fn;        // original (unhooked) method
    DWORD seq;
    WORD  objMask;   // bit i: args[i] is a COM object to Release after the call
    WORD  op;
    DWORD pad;
};

static __forceinline DWORD rtAl16(DWORD n) { return (n + 15) & ~15u; }
static __forceinline DWORD* rtArgs(RtRec* r) { return (DWORD*)(r + 1); }
static __forceinline BYTE* rtPayload(RtRec* r) { return (BYTE*)r + rtAl16(sizeof(RtRec) + (DWORD)r->nargs * 4); }
static void rtDrain();
static void rtInstall(void* fx);
static const char* rtOpName(int op);
static DWORD WINAPI rtKeyThread(LPVOID);
static void rtQForget(DWORD fx);

// Sequence numbers are 32-bit and wrap (a long session queues several billion calls). Everything in flight fits
// in half the ring, so two sequence numbers are never more than 2^31 apart: compare them modulo 2^32.
static __forceinline bool rtSeqReached(DWORD cur, DWORD target) { DWORD d = target - cur; return d == 0 || d >= 0x80000000u; }

// Per object (hashed), the sequence number of the newest queued record that names it - game thread only.
// A synchronous call on an object none of whose records is still pending can run without draining the queue:
// nothing still queued can change what it observes. Hash collisions only make an object look busy.
#define RT_REFN 16384
static DWORD g_rtRefSeq[RT_REFN];
static __forceinline DWORD rtRefIdx(DWORD o) { return ((o >> 3) ^ (o >> 17)) & (RT_REFN - 1); }
#ifdef AOTR_V4_NOTOUCH
static __forceinline void rtTouch(DWORD) {}
#else
static WORD g_rtRefOp[RT_REFN];                                                           // the op of that record (diagnostic)
// The hashed table answers "maybe pending": with ~1500 textures named per frame, 9% of the slots are busy, and the
// v23 log shows exactly that share of the system-memory staging locks waiting for the whole queue because some
// unrelated texture shared their slot ("named by ib.Unlock", "by dev.QueryInterface"...). The few objects the game
// actually locks get an exact entry of their own the first time they are asked about: from then on a touch of their
// slot also updates that entry (one byte test on the hot path), and the answer for them is no longer a guess.
#define RT_XN 192                                                                          // v25: 48 entries were recycled every few seconds by freshly loaded textures
struct RtXRef { DWORD obj, seq, lastUse; WORD op, pad; };       // op: the queued call that named it last (0xFFFF unknown)
static RtXRef g_rtX[RT_XN];
static BYTE g_rtXMark[RT_REFN];                                                            // 0 none, k = entry k-1 lives in this slot, 0xFF = more than one
static LONG g_rtXN = 0;
static volatile LONG g_rtNXHit = 0, g_rtNXSaved = 0, g_rtNXAdd = 0, g_rtNXEvict = 0;
// Exact-object index, game thread only. Bucket links store array index + 1;
// zero ends a chain. Explicit unlinking keeps eviction from leaving stale keys.
#define RT_XHASHN 512
static WORD g_rtXHead[RT_XHASHN], g_rtXNext[RT_XN];
static __forceinline DWORD rtXHash(DWORD o) { return ((o >> 3) * 2654435761u) >> 23; }
static __forceinline LONG rtXFind(DWORD o) {
    for (WORD link = g_rtXHead[rtXHash(o)]; link; link = g_rtXNext[link - 1]) {
        LONG i = link - 1;
        if (g_rtX[i].obj == o) return i;
    }
    return -1;
}
static void rtXIndexRemove(LONG i) {
    if (!g_rtX[i].obj) return;      // an unlinked entry: hashing 0 lands in bucket 0 and would cut a chain not ours
    WORD* link = &g_rtXHead[rtXHash(g_rtX[i].obj)];
    while (*link && *link != i + 1) link = &g_rtXNext[*link - 1];
    if (*link) *link = g_rtXNext[i];
    g_rtXNext[i] = 0;
}
static void rtXIndexAdd(LONG i) {
    DWORD bucket = rtXHash(g_rtX[i].obj);
    g_rtXNext[i] = g_rtXHead[bucket];
    g_rtXHead[bucket] = (WORD)(i + 1);
}
static void rtXTouchSlow(DWORD o, DWORD seq, BYTE mark, WORD op) {
    if (mark != 0xFF) { RtXRef& x = g_rtX[mark - 1]; if (x.obj == o) { x.seq = seq; x.op = op; } return; }
    LONG i = rtXFind(o);
    if (i >= 0) { g_rtX[i].seq = seq; g_rtX[i].op = op; }
}
// v26: a second table under an independent hash. Each table alone never misses a pending object (an object's slot
// always carries a sequence number at least as new as its own), so "pending only if BOTH say so" never misses one
// either - but a false alarm now needs a collision in both tables at once (~1% instead of ~10-20%). v25 showed the
// remaining waits on small system-memory uploads all came from objects without an exact entry, answered by the one
// shared slot.
static DWORD g_rtRefSeq2[RT_REFN];
static __forceinline DWORD rtRefIdx2(DWORD o) { return (o * 2654435761u) >> 18; }           // top 14 bits of a multiplicative hash
static volatile LONG g_rtNH2Saved = 0;
static __forceinline void rtTouch(DWORD o, WORD op = 0xFFFF) {                              // before rtCommit: the record's own seq
    DWORD i = rtRefIdx(o), q = g_rtSeq + 1;
    g_rtRefSeq[i] = q;
    g_rtRefSeq2[rtRefIdx2(o)] = q;
    if (g_rtXMark[i]) rtXTouchSlow(o, q, g_rtXMark[i], op);
}
#endif
static __forceinline bool rtSeqPending(DWORD e) {
    if ((DWORD)(g_rtSeq - e) > (1u << 24)) return false;                                     // older than anything the ring can hold
    DWORD d = e - g_rtExecSeq;
    return d != 0 && d < 0x80000000u;
}
#ifdef AOTR_V4_NOTOUCH
static __forceinline bool rtRefPending(DWORD o) { return rtSeqPending(g_rtRefSeq[rtRefIdx(o)]); }
#else
static void rtXRemark(DWORD slot) {                                                         // recompute one slot's mark
    int n = 0, k = 0;
    for (LONG i = 0; i < g_rtXN; ++i) if (g_rtX[i].obj && rtRefIdx(g_rtX[i].obj) == slot) { ++n; k = (int)i + 1; }
    g_rtXMark[slot] = n == 0 ? 0 : (n == 1 ? (BYTE)k : 0xFF);
}
static WORD g_rtPendOp = 0xFFFF; static BYTE g_rtPendExact = 0;                             // why the last rtRefPending said "pending" (diagnostic)
static bool rtRefPending(DWORD o) {                                                         // call with the exec lock held (game thread)
    DWORD slot = rtRefIdx(o), hashed = g_rtRefSeq[slot];
    LONG i = rtXFind(o);
    if (i >= 0) {
        g_rtX[i].lastUse = (DWORD)g_mkFrames; g_rtNXHit++;
        bool pend = rtSeqPending(g_rtX[i].seq);
        if (!pend && rtSeqPending(hashed)) g_rtNXSaved++;                                     // the shared slot alone would have said "wait"
        if (pend) { g_rtPendOp = g_rtX[i].op; g_rtPendExact = 1; }
        return pend;
    }
    g_rtPendOp = g_rtRefOp[slot]; g_rtPendExact = 0;
    LONG k = -1;                                                                              // first question about this object: give it an entry
    if (g_rtXN < RT_XN) k = g_rtXN++;
    else {
        DWORD oldest = 0;
        for (LONG i = 0; i < RT_XN; ++i) {                                                    // replace the least recently asked-about entry that is not pending
            if (rtSeqPending(g_rtX[i].seq)) continue;
            DWORD age = (DWORD)g_mkFrames - g_rtX[i].lastUse;
            if (k < 0 || age > oldest) { k = i; oldest = age; }
        }
        if (k >= 0) { DWORD os = rtRefIdx(g_rtX[k].obj); rtXIndexRemove(k); g_rtX[k].obj = 0; rtXRemark(os); g_rtNXEvict++; }
    }
    DWORD hashed2 = g_rtRefSeq2[rtRefIdx2(o)];
    bool p1 = rtSeqPending(hashed), p2 = rtSeqPending(hashed2);
    if (p1 && !p2) g_rtNH2Saved++;
    DWORD best = (p1 && p2) ? ((DWORD)(hashed - hashed2) < 0x80000000u ? hashed2 : hashed) : (p1 ? hashed2 : hashed);   // the older of two upper bounds is still an upper bound
    if (k >= 0) { g_rtX[k].obj = o; g_rtX[k].seq = best; g_rtX[k].op = 0xFFFF; g_rtX[k].lastUse = (DWORD)g_mkFrames; rtXIndexAdd(k); rtXRemark(slot); g_rtNXAdd++; }
    return p1 && p2;
}
#endif

static volatile LONG g_rtCpuHistW[64], g_rtCpuHistM[64];
static volatile LONG g_rtWaitCalls = 0, g_rtWaitTimeouts = 0, g_rtDrains = 0, g_rtWorkerSleeps = 0, g_rtWorkerTimeouts = 0;
static volatile LONG64 g_rtWaitTicks = 0;
static void rtWaitH(HANDLE h, DWORD ms) {
    // Pump only messages *sent* from other threads, so a worker blocked in a cross-thread SendMessage
    // (window changes inside the driver) can never deadlock against a waiting game thread.
    LONG64 tw = qpcNow();
    DWORD w = MsgWaitForMultipleObjects(1, &h, FALSE, ms, QS_SENDMESSAGE);
    g_rtWaitTicks += qpcNow() - tw; g_rtWaitCalls++; if (w == WAIT_TIMEOUT) g_rtWaitTimeouts++;
    if (w == WAIT_OBJECT_0 + 1) { MSG m; PeekMessageA(&m, NULL, 0, 0, PM_NOREMOVE | PM_QS_SENDMESSAGE); }
}
// Native D3D9 may send a window message while holding the worker execution lock.
// A blocking EnterCriticalSection on the window thread cannot service that message.
static void rtEnterExec() {
    if (GetCurrentThreadId() != g_mkTid) {
        EnterCriticalSection(&g_rtExecCs);
        return;
    }
    while (!TryEnterCriticalSection(&g_rtExecCs)) {
        MSG message;
        PeekMessageA(&message, NULL, 0, 0, PM_NOREMOVE | PM_QS_SENDMESSAGE);
        Sleep(0);
    }
}
// ---------------------------------------------------------------- effect parameter writes, batched
// About 55k of the ~135k calls queued in a battle frame are ID3DXEffect parameter writes (SetVector, SetMatrix,
// SetFloat, SetInt, SetBool, SetTexture, SetRawValue), in runs of ~20 between a Begin and a CommitChanges. D3DX
// does almost nothing in them (a direct SetVector is ~5 ns), so as one full record each (~25-30 ns: header, space
// check, sequence number, publish bookkeeping) the queue's own overhead was most of their cost. A run now goes
// into ONE record (kind 8) as compact entries {slot, effect, handle, value or bytes}; the worker replays the
// entries in order with the original methods, so D3DX sees exactly the same calls in exactly the same order.
// The open batch is game-thread state and is closed (committed) before anything else can enter or wait for the
// queue: rtAlloc and rtDrain close it first, so the record order and every drain target are what they were.
// An object named by a batched SetTexture is stamped with the sequence number the batch will get, as before.
// Kill switch: AOTR_FXBATCH=0.
#define RT_FX_CAP  8192u
#define RT_FX_MAXN 1024u
// Written for every entry by the game thread, so it gets a cache line of its own: next to anything the worker reads
// or writes, each entry would cost a cache-line transfer (measured: 13 -> 26 ns per call). The worker gets the
// effect's method table through the record itself (its fn field), not through shared state.
__declspec(align(64)) struct RtFxHot { RtRec* rec; BYTE* base; DWORD pos, n; LONG on; LONG nBatch, nEntry; LONG opN[8]; };
static RtFxHot g_rtFx = { NULL, NULL, 0, 0, 1, 0, 0, { 0, 0, 0, 0, 0, 0, 0, 0 } };
#define g_rtFxRec     g_rtFx.rec
#define g_rtFxBase    g_rtFx.base
#define g_rtFxPos     g_rtFx.pos
#define g_rtFxN       g_rtFx.n
#define g_rtFxBatchOn g_rtFx.on
#define g_rtNFxBatch  g_rtFx.nBatch
#define g_rtNFxEntry  g_rtFx.nEntry
static const WORD kRtFxOp[8] = { 142, 146, 150, 154, 158, 164, 172, 198 };   // SetBool, SetInt, SetFloat, SetVector, SetMatrix, SetMatrixTranspose, SetTexture, SetRawValue
static void rtFxClose();

static RtRec* rtAlloc(int nargs, DWORD pl) {
    if (g_rtFxRec) rtFxClose();                          // nothing may be queued behind an open batch's back
    DWORD need = rtAl16(sizeof(RtRec) + (DWORD)nargs * 4) + rtAl16(pl) + 96;   // + per-item alignment slack
    for (;;) {
        DWORD head = g_rtLocalHead;
        DWORD used = (head - g_rtPH.cachedTail) & (RT_BUF_SIZE - 1);            // stale tail only overestimates
        if (used + need + 65536 > RT_BUF_SIZE / 2) {
            g_rtPH.cachedTail = g_rtTail;
            used = (head - g_rtPH.cachedTail) & (RT_BUF_SIZE - 1);
            if (used + need + 65536 > RT_BUF_SIZE / 2) { rtDrain(); g_rtPH.cachedTail = g_rtTail; continue; }   // never more than half the ring in flight
        }
        if (head + need + sizeof(RtRec) > RT_BUF_SIZE) {
            RtRec* w = (RtRec*)(g_rtBuf + head); w->kind = 2; w->size = 0;
            g_rtLocalHead = 0; g_rtHead = 0; g_rtPH.unpublished = 0;            // everything before the wrap is complete: publish it
            if (g_rtWorkerSleeping) SetEvent(g_rtWake);
            continue;
        }
        RtRec* r = (RtRec*)(g_rtBuf + head);
        r->kind = 1; r->nargs = (BYTE)nargs; r->flags = 0; r->size = need; r->fn = NULL; r->objMask = 0; r->op = 0; r->pad = 0;
        return r;
    }
}
static __forceinline void rtPublish() {
#ifdef AOTR_V4_CPUSTAT
    g_rtCpuHistM[GetCurrentProcessorNumber() & 63]++;
#endif
    g_rtHead = g_rtLocalHead;
    g_rtPH.unpublished = 0;
    if (g_rtWorkerSleeping) SetEvent(g_rtWake);
    PSTAT(if ((++g_rtPH.pubN & 7) == 0) {                // where are the two threads? (Intel: logical processors 2k and 2k+1 share a core)
        DWORD m = GetCurrentProcessorNumber(), w = g_rtWH.cpu;
        if (m != g_rtPH.lastCpu) { g_rtPH.lastCpu = m; g_rtPH.cpuMigr++; }
        if ((m ^ w) == 1) g_rtPH.cpuSib++; else g_rtPH.cpuOther++;
    });
}
static void capRecord(RtRec* r, DWORD po);
static __forceinline void rtCommit(RtRec* r, DWORD po) {
    if (g_capOn) capRecord(r, po);
    r->size = rtAl16((DWORD)(rtPayload(r) - (BYTE*)r) + po);
    r->seq = ++g_rtSeq;
    g_rtLocalHead = (DWORD)((BYTE*)r - g_rtBuf) + r->size;
    PSTAT(g_rtNAsync++; g_rtBytes += r->size; g_rtOpN[r->op & 511]++);
    if (++g_rtPH.unpublished >= 32 || (r->flags & 1)) rtPublish();   // Present publishes immediately
}
static void rtFxClose() {
    RtRec* r = g_rtFxRec; g_rtFxRec = NULL;
    DWORD n = g_rtFxN;
    r->pad = n;                                          // entry count for the worker
    rtCommit(r, g_rtFxPos);
    if (n > 1) {                                         // statistics and the publish cadence stay in calls, not records
        PSTAT(g_rtNAsync += (LONG)(n - 1));
        g_rtPH.unpublished += n - 1;
        if (g_rtPH.unpublished >= 32) rtPublish();
    }
    PSTAT(g_rtNFxBatch++; g_rtNFxEntry += (LONG)n;
          for (int k = 0; k < 8; ++k) if (g_rtFx.opN[k]) { g_rtOpN[kRtFxOp[k]] += g_rtFx.opN[k]; g_rtFx.opN[k] = 0; });
}
static void rtDrain() {
    if (g_rtFxRec) rtFxClose();                          // the drain target has to include the open batch
    DWORD target = g_rtSeq;
    if (rtSeqReached(g_rtExecSeq, target)) { g_rtCurOp = 511; return; }
    rtPublish();
    LONG64 t0 = qpcNow();
    g_rtDrains++;
    g_rtDrainSeq = target;
    InterlockedExchange(&g_rtDrainWaiting, 1);
    if (g_rtWorkerSleeping) SetEvent(g_rtWake);
    int spins = 0; bool warned = false;
    while (!rtSeqReached(g_rtExecSeq, target)) {
        if (++spins < 8192) { _mm_pause(); continue; }
        InterlockedExchange(&g_rtMainSleeping, 1);
        if (!rtSeqReached(g_rtExecSeq, target)) rtWaitH(g_rtDrained, 1);
        InterlockedExchange(&g_rtMainSleeping, 0);
        if (!warned && (spins & 1023) == 0 && qpcNow() - t0 > g_pqpf.QuadPart * 5) {
            warned = true;
            RtRec* cur = (RtRec*)(g_rtBuf + g_rtTail);
            logf("rt: WARNING game thread waited > 5 s for the worker (exec seq %u, target %u, next op %s).", g_rtExecSeq, target, rtOpName(cur->op));
        }
    }
    InterlockedExchange(&g_rtDrainWaiting, 0);
    LONG64 dt = qpcNow() - t0;
    g_rtDrainTicks += dt; g_rtDrainOpTicks[g_rtCurOp & 511] += dt; g_rtCurOp = 511;
}
static __forceinline bool rtIsName(DWORD h) { return h != 0 && (h & 0x80000003u) != 0x80000003u; }
static DWORD rtStrBytes(DWORD s) {
    if (!s) return 0;
    __try { return (DWORD)strlen((const char*)(ULONG_PTR)s) + 1; } __except (EXCEPTION_EXECUTE_HANDLER) { return 0; }
}
static __forceinline DWORD rtHandleBytes(DWORD h) { return rtIsName(h) ? rtStrBytes(h) : 0; }
static __forceinline DWORD rtBytes(BYTE* P, DWORD* po, DWORD ptr, DWORD n) {
    if (!ptr) return 0;
    DWORD at = rtAl16(*po);
    if (n) memcpy(P + at, (const void*)(ULONG_PTR)ptr, n);
    *po = at + n;
    return (DWORD)(ULONG_PTR)(P + at);
}
static DWORD rtStr(BYTE* P, DWORD* po, DWORD s) { return s ? rtBytes(P, po, s, rtStrBytes(s)) : 0; }
static DWORD rtHandle(BYTE* P, DWORD* po, DWORD h) { return rtIsName(h) ? rtStr(P, po, h) : h; }
// ---------------------------------------------------------------- locks of textures the queue cannot know yet
// A texture created while the render thread is live starts out named by nothing: no queued call mentions it, so no
// queued draw can sample it (a draw samples a texture only through SetTexture or an effect's texture parameter, and
// both name the object when they are queued). Until the first queued call names it, its system-memory copy can be
// locked and filled at once - the usual case of a texture that is created and then filled - instead of waiting for
// the whole queue. The registry is dropped on Release and on device reset, and any naming removes the texture.
#define RT_FRESH_N 256
static DWORD g_rtFresh[RT_FRESH_N];
static LONG g_rtFreshN = 0, g_rtFreshOn = 1;
static BYTE g_rtFreshMark[RT_REFN];
static volatile LONG g_rtNFreshLock = 0, g_rtNFreshMiss = 0, g_rtNFreshAdd = 0;
static void rtFreshAdd(DWORD obj) {
    if (!obj || !g_rtFreshOn) return;
    if (g_rtFreshN >= RT_FRESH_N) { g_rtFreshMark[rtRefIdx(g_rtFresh[0])] = 0; memmove(g_rtFresh, g_rtFresh + 1, (RT_FRESH_N - 1) * sizeof(DWORD)); g_rtFreshN = RT_FRESH_N - 1;
                                    for (LONG i = 0; i < g_rtFreshN; ++i) g_rtFreshMark[rtRefIdx(g_rtFresh[i])] = 1; }
    g_rtFresh[g_rtFreshN++] = obj; g_rtFreshMark[rtRefIdx(obj)] = 1; g_rtNFreshAdd++;
}
static void rtFreshDropSlow(DWORD obj) {
    for (LONG i = 0; i < g_rtFreshN; ++i) if (g_rtFresh[i] == obj) { g_rtFresh[i] = g_rtFresh[--g_rtFreshN]; break; }
    DWORD idx = rtRefIdx(obj);
    for (LONG i = 0; i < g_rtFreshN; ++i) if (rtRefIdx(g_rtFresh[i]) == idx) return;
    g_rtFreshMark[idx] = 0;
}
static __forceinline void rtFreshName(DWORD obj) { if (g_rtFreshN && g_rtFreshMark[rtRefIdx(obj)]) rtFreshDropSlow(obj); }
static __forceinline bool rtFreshHas(DWORD obj) {
    if (!obj || !g_rtFreshN || !g_rtFreshMark[rtRefIdx(obj)]) return false;
    for (LONG i = 0; i < g_rtFreshN; ++i) if (g_rtFresh[i] == obj) return true;
    return false;
}
static void rtFreshForget() { for (LONG i = 0; i < g_rtFreshN; ++i) g_rtFreshMark[rtRefIdx(g_rtFresh[i])] = 0; g_rtFreshN = 0; }

// The "newest queued record naming this object" table is consulted for two kinds of object only: surfaces and
// textures about to be locked. Vertex buffers, index buffers, vertex declarations and shaders were stamped into the
// same 16k-slot hash on every SetStreamSource / SetIndices / SetVertexDeclaration / Set*Shader (~30k times a frame),
// which did nothing useful and made unrelated surfaces look busy: the v22 log shows 64x64 system-memory surfaces
// "named by SetStreamSource", each such false hit a ~2 ms wait for the whole queue. Those ops no longer stamp.
static BYTE g_rtOpNoTouch[512];                          // 1: this op's object arguments are never a texture or a surface
static void rtOpNoTouchInit() { g_rtOpNoTouch[87] = g_rtOpNoTouch[92] = g_rtOpNoTouch[100] = g_rtOpNoTouch[104] = g_rtOpNoTouch[107] = 1; }   // SetVertexDeclaration, SetVertexShader, SetStreamSource, SetIndices, SetPixelShader
static __forceinline DWORD rtObj(RtRec* r, int argIndex, DWORD obj) {
    if (obj && !g_rtOpNoTouch[r->op & 511]) { rtTouch(obj, (WORD)r->op); g_rtRefOp[rtRefIdx(obj)] = (WORD)r->op; rtFreshName(obj); }
    if (obj && g_rtObjRefs) { ((DWORD(__stdcall*)(DWORD))(*(DWORD**)(ULONG_PTR)obj)[1])(obj); r->objMask |= (WORD)(1u << argIndex); }
    return obj;
}

// Parameter blocks recorded through the queue get proxy handles. D3DX handles are the bitwise NOT of an object
// pointer (d3dx9_27 SetFloat: (h & 0x80000003) == 0x80000003 -> ~h), and game.dat is large-address-aware, so a
// real handle can take almost any value - except the NOT of an address in the first 64 KB, which Windows never
// allocates. Proxies are 0xFFFF0003 | index << 2 (index 1..16383). The worker stores the real handle when
// EndParameterBlock executes and translates in Apply/DeleteParameterBlock, all in queue order.
#define RT_PBN (1u << 14)
static DWORD* g_rtPBReal = NULL;
static __forceinline bool rtIsPBProxy(DWORD h) { return (h & 0xFFFF0003u) == 0xFFFF0003u; }
static __forceinline DWORD rtPBIndex(DWORD h) { return (h >> 2) & (RT_PBN - 1); }
static __forceinline DWORD rtPBReal(DWORD h) { return (rtIsPBProxy(h) && g_rtPBReal) ? g_rtPBReal[rtPBIndex(h)] : h; }

typedef DWORD (__stdcall* RtF1)(DWORD);
typedef DWORD (__stdcall* RtF2)(DWORD, DWORD);
typedef DWORD (__stdcall* RtF3)(DWORD, DWORD, DWORD);
typedef DWORD (__stdcall* RtF4)(DWORD, DWORD, DWORD, DWORD);
typedef DWORD (__stdcall* RtF5)(DWORD, DWORD, DWORD, DWORD, DWORD);
typedef DWORD (__stdcall* RtF6)(DWORD, DWORD, DWORD, DWORD, DWORD, DWORD);
typedef DWORD (__stdcall* RtF7)(DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD);
typedef DWORD (__stdcall* RtF8)(DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD);
typedef DWORD (__stdcall* RtF9)(DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD);
typedef DWORD (__stdcall* RtF10)(DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD);
static void rtExec(RtRec* r) {
    DWORD* a = rtArgs(r);
    if (r->kind == 4) {                                  // engine per-pixel write (SurfaceClass DrawPixel / alpha): Lock 1x1, write, Unlock
        struct { LONG l, t, rr, b; } rc = { (LONG)a[1], (LONG)a[2], (LONG)a[1] + 1, (LONG)a[2] + 1 };
        struct { INT pitch; void* bits; } lr = { 0, NULL };
        ((DWORD(__stdcall*)(DWORD, void*, void*, DWORD))r->fn)(a[0], &lr, &rc, 0);
        if (lr.bits) switch (a[4]) {
            case 1: *(BYTE*)lr.bits = (BYTE)a[3]; break;
            case 2: *(WORD*)lr.bits = (WORD)a[3]; break;
            case 4: *(DWORD*)lr.bits = a[3]; break;
            case 0x100: ((BYTE*)lr.bits)[3] = (BYTE)a[3]; break;
        }
        ((DWORD(__stdcall*)(DWORD))(ULONG_PTR)a[5])(a[0]);
        return;
    }
    if (r->kind == 7) {                                  // staged full-rect write (engine shroud textures): LockRect(rect), copy rows, UnlockRect
        struct { LONG l, t, rr, b; } rc = { (LONG)a[1], (LONG)a[2], (LONG)a[3], (LONG)a[4] };
        struct { INT pitch; void* bits; } lr = { 0, NULL };
        DWORD w = a[3] - a[1], hgt = a[4] - a[2], rowBytes = w * a[5];
        ((DWORD(__stdcall*)(DWORD, void*, void*, DWORD))(ULONG_PTR)a[7])(a[0], &lr, &rc, 0x800);
        if (lr.bits) for (DWORD y = 0; y < hgt; ++y) memcpy((BYTE*)lr.bits + (INT)y * lr.pitch, (BYTE*)(ULONG_PTR)a[6] + y * rowBytes, rowBytes);
        ((DWORD(__stdcall*)(DWORD))(ULONG_PTR)a[8])(a[0]);
        return;
    }
    if (r->kind == 5) { g_rtPBReal[a[1]] = ((RtF1)r->fn)(a[0]); return; }                       // EndParameterBlock -> proxy slot
    if (r->kind == 6) {                                                                          // Apply/DeleteParameterBlock via proxy
        ((RtF2)r->fn)(a[0], g_rtPBReal[a[1]]);
        if (a[2]) g_rtPBReal[a[1]] = 0;
        return;
    }
    if (r->kind == 9) {                                  // UpdateSurface from a snapshot: rows -> private staging surface -> UpdateSurface
        struct { LONG l, t, rr, b; } rc = { (LONG)a[2], (LONG)a[3], (LONG)a[4], (LONG)a[5] };
        struct { INT pitch; void* bits; } lr = { 0, NULL };
        DWORD w = a[4] - a[2], hgt = a[5] - a[3], rowBytes = w * a[6];
        if ((LONG)((DWORD(__stdcall*)(DWORD, void*, void*, DWORD))(ULONG_PTR)a[12])(a[1], &lr, &rc, 0x800) >= 0) {
            if (lr.bits) for (DWORD y = 0; y < hgt; ++y) memcpy((BYTE*)lr.bits + (INT)y * lr.pitch, (const BYTE*)(ULONG_PTR)a[7] + y * rowBytes, rowBytes);
            ((DWORD(__stdcall*)(DWORD))(ULONG_PTR)a[13])(a[1]);
        }
        struct { LONG x, y; } pt = { (LONG)a[9], (LONG)a[10] };
        ((DWORD(__stdcall*)(DWORD, DWORD, void*, DWORD, void*))(ULONG_PTR)a[14])(a[0], a[1], (a[11] & 1) ? (void*)&rc : NULL, a[8], (a[11] & 2) ? (void*)&pt : NULL);
        return;
    }
    if (r->kind == 8) {                                  // a run of effect parameter writes (see rtFxRoom)
        const DWORD* e = (const DWORD*)rtPayload(r);
        void** O = (void**)r->fn;                          // the effect's original methods, put there by rtFxRoom
        for (DWORD i = r->pad; i; --i) {
            DWORD w0 = e[0], slot = w0 & 0xFF, nb = (w0 >> 8) & 0x7FFFFF;
            if (slot == 78) {
                ((RtF5)O[78])(e[1], e[2], (w0 & 0x80000000u) ? (DWORD)(ULONG_PTR)(e + 5) : 0, e[3], e[4]);
                e = (const DWORD*)((const BYTE*)e + 20 + ((nb + 3) & ~3u));
            } else if (slot == 34 || slot == 38 || slot == 44) {
                ((RtF3)O[slot])(e[1], e[2], (w0 & 0x80000000u) ? (DWORD)(ULONG_PTR)(e + 3) : 0);
                e = (const DWORD*)((const BYTE*)e + 12 + ((nb + 3) & ~3u));
            } else {
                ((RtF3)O[slot])(e[1], e[2], e[3]);
                e += 4;
            }
        }
        return;
    }
    if (r->kind == 3) {                                  // staged write-only buffer lock: Lock, copy, Unlock in queue order
        void* mapped = NULL;
        if ((LONG)((DWORD(__stdcall*)(DWORD, DWORD, DWORD, void**, DWORD))r->fn)(a[0], a[1], a[2], &mapped, a[3]) >= 0 && mapped)
            memcpy(mapped, (const void*)(ULONG_PTR)a[5], a[2]);
        ((DWORD(__stdcall*)(DWORD))(ULONG_PTR)a[4])(a[0]);
        if (r->objMask & 1) ((DWORD(__stdcall*)(DWORD))(*(DWORD**)(ULONG_PTR)a[0])[2])(a[0]);
        return;
    }
    DWORD ret_ = 0;
    switch (r->nargs) {
    case 1:  ((RtF1)r->fn)(a[0]); break;
    case 2:  ((RtF2)r->fn)(a[0], a[1]); break;
    case 3:  ((RtF3)r->fn)(a[0], a[1], a[2]); break;
    case 4:  ((RtF4)r->fn)(a[0], a[1], a[2], a[3]); break;
    case 5:  ret_ = ((RtF5)r->fn)(a[0], a[1], a[2], a[3], a[4]); break;         // device Present lands here
    case 6:  ret_ = ((RtF6)r->fn)(a[0], a[1], a[2], a[3], a[4], a[5]); break;   // swap-chain Present lands here
    case 7:  ((RtF7)r->fn)(a[0], a[1], a[2], a[3], a[4], a[5], a[6]); break;
    case 8:  ((RtF8)r->fn)(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]); break;
    case 9:  ((RtF9)r->fn)(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8]); break;
    case 10: ((RtF10)r->fn)(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], a[9]); break;
    }
    if (r->objMask) {
        for (int i = 0; i < r->nargs; ++i)
            if (((r->objMask >> i) & 1) && a[i]) ((DWORD(__stdcall*)(DWORD))(*(DWORD**)(ULONG_PTR)a[i])[2])(a[i]);   // worker bypasses hooks
    }
    if (r->flags & 1) { InterlockedExchange(&g_rtPresentHR, (LONG)ret_); InterlockedDecrement(&g_rtPendingPresents); SetEvent(g_rtPresented); }
}
static DWORD WINAPI rtWorker(LPVOID) {
    g_rtWorkerTid = GetCurrentThreadId();
    // same x87 precision/rounding and SSE modes as the game thread, so D3DX's x87 preshader math and any
    // driver float code produce bit-identical results on this thread
    _control87(g_rtX87, _MCW_PC | _MCW_RC | _MCW_EM | _MCW_IC | _MCW_DN);
    _mm_setcsr(g_rtMxcsr);
    SetEvent(g_rtReady);
    DWORD tail = g_rtTail;
    for (;;) {
        DWORD head = g_rtHead;
        if (tail == head) {
            if (g_rtDrainWaiting && g_rtMainSleeping && rtSeqReached(g_rtExecSeq, g_rtDrainSeq)) SetEvent(g_rtDrained);
            for (int spins = 0; g_rtHead == tail && spins < 4000; ++spins) _mm_pause();
            if (g_rtHead == tail) {
                InterlockedExchange(&g_rtWorkerSleeping, 1);
                if (g_rtHead == tail) { g_rtWorkerSleeps++; if (WaitForSingleObject(g_rtWake, 2) == WAIT_TIMEOUT) g_rtWorkerTimeouts++; }   // timed: a lost wakeup costs at most 2 ms
                InterlockedExchange(&g_rtWorkerSleeping, 0);
            }
            continue;
        }
#ifndef AOTR_V4_NOLOCKWANT
        if (g_rtLK.want)                               // a direct call is waiting for the lock: let it in before taking it back
            for (int k = 0; g_rtLK.want && k < 65536; ++k) _mm_pause();
#endif
        rtEnterExec();
        LONG64 t0 = qpcNow();
        DWORD seq = g_rtExecSeq;
#ifndef AOTR_V4_NOLOCKWANT
        for (int n = 0; n < 256 && tail != head && !g_rtLK.want; ++n) {      // the game thread may want the lock for a direct call
#else
        for (int n = 0; n < 256 && tail != head; ++n) {
#endif
            RtRec* r = (RtRec*)(g_rtBuf + tail);
            if (r->kind == 2) { tail = 0; continue; }
            g_rtWorkerOp = r->op;
            rtExec(r);
            seq = r->seq;
            tail += r->size;
        }
        g_rtTail = tail; g_rtExecSeq = seq;                 // publish progress once per batch
        g_rtWH.cpu = GetCurrentProcessorNumber();
#ifdef AOTR_V4_CPUSTAT
        g_rtCpuHistW[GetCurrentProcessorNumber() & 63]++;
#endif
        g_rtBusyTicks += qpcNow() - t0;
        LeaveCriticalSection(&g_rtExecCs);
        if (g_rtDrainWaiting && g_rtMainSleeping && rtSeqReached(seq, g_rtDrainSeq)) SetEvent(g_rtDrained);
    }
    return 0;
}

// technique mirror (effect -> current technique handle) and pass-count cache, game thread only
#define RT_FXT 2048
#define RT_PC  8192
struct RtTech { DWORD fx, tech; };
struct RtPass { DWORD fx, tech, passes; };
static RtTech g_rtTech[RT_FXT];
static RtPass g_rtPass[RT_PC];
static void rtTechSet(DWORD fx, DWORD tech) {
    DWORD h = (fx * 2654435761u) >> 8;
    for (int i = 0; i < RT_FXT; ++i) { RtTech* e = &g_rtTech[(h + i) & (RT_FXT - 1)];
        if (e->fx == fx || e->fx == 0) { e->fx = fx; e->tech = tech; return; } }
}
static DWORD rtTechGet(DWORD fx) {
    DWORD h = (fx * 2654435761u) >> 8;
    for (int i = 0; i < RT_FXT; ++i) { RtTech* e = &g_rtTech[(h + i) & (RT_FXT - 1)];
        if (e->fx == fx) return e->tech; if (e->fx == 0) return 0; }
    return 0;
}
static bool rtPassGet(DWORD fx, DWORD tech, DWORD* passes) {
    DWORD h = ((fx ^ (tech * 40503u)) * 2654435761u) >> 8;
    for (int i = 0; i < RT_PC; ++i) { RtPass* e = &g_rtPass[(h + i) & (RT_PC - 1)];
        if (e->fx == fx && e->tech == tech) { *passes = e->passes; return true; } if (e->fx == 0) return false; }
    return false;
}
static void rtPassPut(DWORD fx, DWORD tech, DWORD passes) {
    DWORD h = ((fx ^ (tech * 40503u)) * 2654435761u) >> 8;
    for (int i = 0; i < RT_PC; ++i) { RtPass* e = &g_rtPass[(h + i) & (RT_PC - 1)];
        if ((e->fx == fx && e->tech == tech) || e->fx == 0 || e->fx == 1) { e->fx = fx; e->tech = tech; e->passes = passes; return; } }
}
static void rtFxForget(DWORD fx) {                     // an effect may be destroyed: drop what we know about it
    for (int i = 0; i < RT_PC; ++i) if (g_rtPass[i].fx == fx) { g_rtPass[i].fx = 1; g_rtPass[i].tech = 0; }   // tombstone
    DWORD h = (fx * 2654435761u) >> 8;
    for (int i = 0; i < RT_FXT; ++i) { RtTech* e = &g_rtTech[(h + i) & (RT_FXT - 1)]; if (e->fx == fx) { e->tech = 0; break; } if (e->fx == 0) break; }
}

// exec lock for a direct call from the game thread: the worker stops after its current record
static __forceinline void rtExecLock() { g_rtLK.want = 1; rtEnterExec(); g_rtLK.want = 0; }

// diagnostics: who still forces synchronous calls (return address + op), and what the locked surfaces are
struct RtSyncCaller { DWORD ra; WORD op; WORD pad; LONG n, ln; };
#define RT_SCN 512
static RtSyncCaller g_rtSC[RT_SCN];
static volatile LONG g_rtSCDrop = 0;
static const char* rtOpName(int op);
static void rtSyncNote(int op, DWORD ra) {
    if (g_capOn) capPrintf("S sync %s ra=%08X\n", rtOpName(op), ra);
#ifdef AOTR_PROD
    return;
#else
    DWORD h = ((ra * 2654435761u) ^ (DWORD)op) >> 23;
    for (int i = 0; i < 16; ++i) {
        RtSyncCaller& e = g_rtSC[(h + i) & (RT_SCN - 1)];
        if (e.ra == ra && e.op == (WORD)op) { e.n++; return; }
        if (e.ra == 0) { e.op = (WORD)op; e.ra = ra; e.n = 1; return; }
    }
    g_rtSCDrop++;
#endif
}
struct RtLockStat { DWORD ra, fmt, usage, flags; WORD w, h, blocker; BYTE pool, fast; LONG n, ln; BYTE who, exact; };   // who: 0 the object itself, 1 its texture; exact: from the object's own entry
#define RT_LSN 128
static RtLockStat g_rtLS[RT_LSN];
static void rtLockNote(DWORD ra, const BYTE* desc, DWORD flags, int fast, WORD blocker = 0xFFFF, BYTE who = 0, BYTE exact = 0) {
    const DWORD* d = (const DWORD*)desc;                     // D3DSURFACE_DESC: Format Type Usage Pool MSType MSQuality Width Height
    DWORD h = ((ra * 2654435761u) ^ d[0] ^ (flags << 8) ^ (DWORD)fast) >> 25;
    for (int i = 0; i < 16; ++i) {
        RtLockStat& e = g_rtLS[(h + i) & (RT_LSN - 1)];
        if (e.ra == ra && e.fmt == d[0] && e.flags == flags && e.fast == (BYTE)fast && e.pool == (BYTE)d[3] && e.w == (WORD)d[6] && e.h == (WORD)d[7] && e.usage == d[2]) { e.n++; if (!fast) { e.blocker = blocker; e.who = who; e.exact = exact; } return; }
        if (e.ra == 0) { e.fmt = d[0]; e.usage = d[2]; e.flags = flags; e.w = (WORD)d[6]; e.h = (WORD)d[7]; e.pool = (BYTE)d[3]; e.fast = (BYTE)fast; e.n = 1; e.blocker = blocker; e.who = who; e.exact = exact; e.ra = ra; return; }
    }
}

// ---------------------------------------------------------------- vertex-input state that is already in place
// SetStreamSource, SetIndices and SetVertexDeclaration are ~31k of the ~140k calls queued in a battle frame: the
// engine sets them for every draw, and the render list is sorted by model, so most of them bind what is bound
// already. Binding the same buffer / declaration again changes nothing in Direct3D, so such a call is not queued.
// The shadow below is what the QUEUE has set (it runs ahead of the worker, in order). It is dropped by everything
// that can change these bindings behind it: SetFVF (declaration), Draw*PrimitiveUP (stream 0, indices), state block
// Apply, Reset, any call that does not go through the queue (other thread, direct scope, render thread off), and it
// is bypassed while a state block is being recorded. A bound object cannot be freed and its address reused while it
// is bound (the device holds it), so equal pointers mean the same object. Kill switch: AOTR_DEVDEDUPE=0.
__declspec(align(64)) struct RtDevShadow { DWORD dev, ib, decl; DWORD vb[16], off[16], stride[16]; DWORD vbOk; LONG ibOk, declOk, recording, on; LONG nSkip, nSet; };
static RtDevShadow g_rtDs;
static __forceinline void rtDsInvalAll() { g_rtDs.vbOk = 0; g_rtDs.ibOk = 0; g_rtDs.declOk = 0; }
static __forceinline void rtDsInvalDecl() { g_rtDs.declOk = 0; }
static __forceinline void rtDsInvalUP(int indexed) { g_rtDs.vbOk &= ~1u; if (indexed) g_rtDs.ibOk = 0; }
static __forceinline void rtDsRecording(int on) { g_rtDs.recording = on; rtDsInvalAll(); }

#include "aotr_rt_gen.inc"
static volatile LONG g_rtTMAny = 0;                     // radar texture mirrors live (aotr_rtmirror.inc)
static volatile LONG g_rtBMAny = 0;                     // buffer mirrors live (rtBufLock)
static void rtBMKillAll();
static void rtAnnForget(DWORD fx);
static void rtTMKill(DWORD obj);
static void rtTMKillAll();
static DWORD g_rtSurfLockCaller = 0;                       // game code that called SurfaceClass::Lock (set by its detour, for the lock statistics)
static volatile LONG g_rtNSyncDL = 0;                       // drained locks of system-memory surfaces that were then unlocked directly
static volatile LONG g_rtInAsyncFilter = 0;                 // worker: inside a queued D3DXFilterTexture of a mirrored texture
static volatile LONG g_rtNAsyncFilter = 0;
static bool rtTMLockD3D(DWORD surf, DWORD flags, INT* pitch, void** bits);
static bool rtTMUnlockD3D(DWORD surf);
static LONG g_rtTMAtlasOn = 1, g_rtTMAtlasAny = 0;       // terrain atlas mirror; Any: accept every caller (offline harness)

// ---------------------------------------------------------------- hand-written hooks
#define RT_PASSTHRU(CLS, SLOT, SIG, ...) do { \
    DWORD tid_ = GetCurrentThreadId(); \
    if (tid_ != g_rtMainTid || !g_rtActive || g_rtDirectScope) { \
        if (g_rtActive && tid_ != g_rtWorkerTid && tid_ != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((SIG)g_rtO_##CLS[SLOT])(__VA_ARGS__); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; } \
        return ((SIG)g_rtO_##CLS[SLOT])(__VA_ARGS__); } } while (0)
#define RT_SYNC(CLS, SLOT, OP, SIG, ...) do { rtSyncNote(OP, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = OP; rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r_ = ((SIG)g_rtO_##CLS[SLOT])(__VA_ARGS__); \
    g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs); g_rtNSync++; g_rtSyncHist[OP]++; return r_; } while (0)

typedef DWORD (__stdcall* RtS5)(void*, DWORD, DWORD, DWORD, DWORD);
typedef DWORD (__stdcall* RtS6)(void*, DWORD, DWORD, DWORD, DWORD, DWORD);
static void rtPresentBackpressure() {
    if (g_rtPendingPresents <= 1) return;
    LONG64 t0 = qpcNow();
    while (g_rtPendingPresents > 1) rtWaitH(g_rtPresented, 2);
    g_rtPresentWaitTicks += qpcNow() - t0;
}
static void rtMirInvalidate();
static void rtDirectLocksForget();
static void rtApplyToggle() {                          // render thread only
    LONG want = g_rtWantOn;
    rtDsInvalAll();                                      // the vertex-input shadow does not survive a switch
    rtMirInvalidate(); rtDirectLocksForget(); rtFreshForget();
    if (want && !g_rtActive) {
        memset(g_rtTech, 0, sizeof(g_rtTech));          // techniques set while off were not mirrored: Begin re-learns them synchronously
        InterlockedExchange(&g_rtActive, 1); g_rtToggles++; logf("rt: render thread switched ON (Scroll Lock)."); }
    else if (!want && g_rtActive) { rtDrain(); rtEnterExec(); InterlockedExchange(&g_rtActive, 0); LeaveCriticalSection(&g_rtExecCs);
        g_rtToggles++; logf("rt: render thread switched OFF (Scroll Lock) - every call runs directly on the game thread."); }
}
static DWORD __stdcall rt_dev_17(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {      // Present
    if (g_rtInstalled && ((g_rtWantOn != 0) != (g_rtActive != 0)) && GetCurrentThreadId() == g_rtMainTid) rtApplyToggle();
    RT_PASSTHRU(dev, 17, RtS5, self, a0, a1, a2, a3);
    if (a3) RT_SYNC(dev, 17, 17, RtS5, self, a0, a1, a2, a3);                                   // dirty region: rare
    RtRec* r = rtAlloc(5, (a0 ? 16 : 0) + (a1 ? 16 : 0)); r->fn = g_rtO_dev[17]; r->op = 17; r->flags = 1;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0;
    A[0] = (DWORD)(ULONG_PTR)self; A[1] = rtBytes(P, &po, a0, 16); A[2] = rtBytes(P, &po, a1, 16); A[3] = a2; A[4] = 0;
    InterlockedIncrement(&g_rtPendingPresents); g_rtNPresent++;
    if (!g_engineHooks) ++g_mkFrames;                     // no engine frame counter on this build; the caches age by this
    rtCommit(r, po);
    rtPresentBackpressure();                              // at most one finished frame waiting on the worker
    return (DWORD)g_rtPresentHR;                          // the last Present the worker actually ran
}
static DWORD __stdcall rt_sc_3(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4) {   // IDirect3DSwapChain9::Present
    if (g_rtInstalled && ((g_rtWantOn != 0) != (g_rtActive != 0)) && GetCurrentThreadId() == g_rtMainTid) rtApplyToggle();
    RT_PASSTHRU(sc, 3, RtS6, self, a0, a1, a2, a3, a4);
    if (a3) RT_SYNC(sc, 3, 393, RtS6, self, a0, a1, a2, a3, a4);
    RtRec* r = rtAlloc(6, (a0 ? 16 : 0) + (a1 ? 16 : 0)); r->fn = g_rtO_sc[3]; r->op = 393; r->flags = 1;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0;
    A[0] = (DWORD)(ULONG_PTR)self; A[1] = rtBytes(P, &po, a0, 16); A[2] = rtBytes(P, &po, a1, 16); A[3] = a2; A[4] = 0; A[5] = a4;
    InterlockedIncrement(&g_rtPendingPresents); g_rtNPresent++;
    rtCommit(r, po);
    rtPresentBackpressure();
    return (DWORD)g_rtPresentHR;
}
static float __stdcall rt_dev_80(void* self) {                                                  // GetNPatchMode (float return)
    typedef float (__stdcall* F)(void*);
    DWORD tid = GetCurrentThreadId();
    if (g_rtActive && tid == g_rtMainTid && !g_rtDirectScope) { rtDrain(); rtEnterExec(); g_rtDirectScope++; float f = ((F)g_rtO_dev[80])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs); return f; }
    if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); float f = ((F)g_rtO_dev[80])(self); LeaveCriticalSection(&g_rtExecCs); return f; }
    return ((F)g_rtO_dev[80])(self);
}
static __forceinline DWORD rtPrimVerts(DWORD type, DWORD prims) {
    switch (type) { case 1: return prims; case 2: return prims * 2; case 3: return prims + 1; case 4: return prims * 3; case 5: case 6: return prims + 2; }
    return 0;
}
static DWORD __stdcall rt_dev_83(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {      // DrawPrimitiveUP
    rtDsInvalUP(0);                                      // Direct3D unbinds stream 0 after a ...UP draw
    RT_PASSTHRU(dev, 83, RtS5, self, a0, a1, a2, a3);
    DWORD vb = a2 ? rtPrimVerts(a0, a1) * a3 : 0;
    RtRec* r = rtAlloc(5, vb); r->fn = g_rtO_dev[83]; r->op = 83;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0;
    A[0] = (DWORD)(ULONG_PTR)self; A[1] = a0; A[2] = a1; A[3] = rtBytes(P, &po, a2, vb); A[4] = a3;
    rtCommit(r, po); return 0;
}
typedef DWORD (__stdcall* RtS9)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD);
static DWORD __stdcall rt_dev_84(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4, DWORD a5, DWORD a6, DWORD a7) {  // DrawIndexedPrimitiveUP
    rtDsInvalUP(1);                                      // Direct3D unbinds stream 0 and the indices after a ...UP draw
    RT_PASSTHRU(dev, 84, RtS9, self, a0, a1, a2, a3, a4, a5, a6, a7);
    DWORD ib = a4 ? rtPrimVerts(a0, a3) * (a5 == 102 ? 4 : 2) : 0;
    DWORD vb = a6 ? (a1 + a2) * a7 : 0;
    RtRec* r = rtAlloc(9, ib + vb); r->fn = g_rtO_dev[84]; r->op = 84;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0;
    A[0] = (DWORD)(ULONG_PTR)self; A[1] = a0; A[2] = a1; A[3] = a2; A[4] = a3; A[5] = rtBytes(P, &po, a4, ib); A[6] = a5; A[7] = rtBytes(P, &po, a6, vb); A[8] = a7;
    rtCommit(r, po); return 0;
}
typedef DWORD (__stdcall* RtS1)(void*);
typedef DWORD (__stdcall* RtS2)(void*, DWORD);
typedef DWORD (__stdcall* RtS3)(void*, DWORD, DWORD);
typedef DWORD (__stdcall* RtS4)(void*, DWORD, DWORD, DWORD);
static DWORD __stdcall rt_fx_2(void* self) {                                                    // ID3DXEffect::Release
    DWORD tid = GetCurrentThreadId();
    if (!g_rtActive && !g_rtTried && rtIsGameThread(tid) && !g_rtXDepth) rtInstall(self);
    RT_PASSTHRU(fx, 2, RtS1, self);
    rtFxForget((DWORD)(ULONG_PTR)self);
    rtQForget((DWORD)(ULONG_PTR)self);
    rtAnnForget((DWORD)(ULONG_PTR)self);
    RT_SYNC(fx, 2, 122, RtS1, self);
    return 0;
}
static DWORD __stdcall rt_fx_20(void* self, DWORD a0, DWORD a1, DWORD a2) {                    // SetValue
    DWORD tid = GetCurrentThreadId();
    if (!g_rtActive && !g_rtTried && rtIsGameThread(tid) && !g_rtXDepth) rtInstall(self);
    RT_PASSTHRU(fx, 20, RtS4, self, a0, a1, a2);
    if (a2 == 0xFFFFFFFFu || a2 > (1u << 20)) RT_SYNC(fx, 20, 140, RtS4, self, a0, a1, a2);     // D3DX_DEFAULT size: let D3DX decide
    RtRec* r = rtAlloc(4, rtHandleBytes(a0) + (a1 ? a2 : 0)); r->fn = g_rtO_fx[20]; r->op = 140;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0;
    A[0] = (DWORD)(ULONG_PTR)self; A[1] = rtHandle(P, &po, a0); A[2] = rtBytes(P, &po, a1, a2); A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD rtPtrArray(void* self, DWORD a0, DWORD a1, DWORD a2, int slot, int op) {             // Set(Transpose)MatrixPointerArray
    if (!a1 || a2 > 4096) RT_SYNC(fx, slot, op, RtS4, self, a0, a1, a2);
    RtRec* r = rtAlloc(4, rtHandleBytes(a0) + a2 * 64 + a2 * 4 + 32); r->fn = g_rtO_fx[slot]; r->op = (WORD)op;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0;
    A[0] = (DWORD)(ULONG_PTR)self; A[1] = rtHandle(P, &po, a0);
    DWORD at = rtAl16(po); const DWORD* src = (const DWORD*)(ULONG_PTR)a1;
    for (DWORD i = 0; i < a2; ++i) memcpy(P + at + i * 64, (const void*)(ULONG_PTR)src[i], 64);
    DWORD at2 = rtAl16(at + a2 * 64);
    for (DWORD i = 0; i < a2; ++i) ((DWORD*)(P + at2))[i] = (DWORD)(ULONG_PTR)(P + at + i * 64);
    po = at2 + a2 * 4;
    A[2] = (DWORD)(ULONG_PTR)(P + at2); A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_fx_42(void* self, DWORD a0, DWORD a1, DWORD a2) {
    DWORD tid = GetCurrentThreadId();
    if (!g_rtActive && !g_rtTried && rtIsGameThread(tid) && !g_rtXDepth) rtInstall(self);
    RT_PASSTHRU(fx, 42, RtS4, self, a0, a1, a2);
    return rtPtrArray(self, a0, a1, a2, 42, 162);
}
static DWORD __stdcall rt_fx_48(void* self, DWORD a0, DWORD a1, DWORD a2) {
    DWORD tid = GetCurrentThreadId();
    if (!g_rtActive && !g_rtTried && rtIsGameThread(tid) && !g_rtXDepth) rtInstall(self);
    RT_PASSTHRU(fx, 48, RtS4, self, a0, a1, a2);
    return rtPtrArray(self, a0, a1, a2, 48, 168);
}
static DWORD __stdcall rt_fx_58(void* self, DWORD a0) {                                        // SetTechnique (+ mirror)
    DWORD tid = GetCurrentThreadId();
    if (!g_rtActive && !g_rtTried && rtIsGameThread(tid) && !g_rtXDepth) rtInstall(self);
    RT_PASSTHRU(fx, 58, RtS2, self, a0);
    rtTechSet((DWORD)(ULONG_PTR)self, rtIsName(a0) ? 0 : a0);
    RtRec* r = rtAlloc(2, rtHandleBytes(a0)); r->fn = g_rtO_fx[58]; r->op = 178;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0;
    A[0] = (DWORD)(ULONG_PTR)self; A[1] = rtHandle(P, &po, a0);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_fx_63(void* self, DWORD a0, DWORD a1) {                              // Begin (pass count from cache)
    DWORD tid = GetCurrentThreadId();
    if (!g_rtActive && !g_rtTried && rtIsGameThread(tid) && !g_rtXDepth) rtInstall(self);
    RT_PASSTHRU(fx, 63, RtS3, self, a0, a1);
    DWORD fx = (DWORD)(ULONG_PTR)self, tech = rtTechGet(fx), passes = 0;
    if (tech && rtPassGet(fx, tech, &passes)) {
        if (a0) *(UINT*)(ULONG_PTR)a0 = passes;
        RtRec* r = rtAlloc(3, 4); r->fn = g_rtO_fx[63]; r->op = 183;
        DWORD* A = rtArgs(r); BYTE* P = rtPayload(r);
        A[0] = fx; A[1] = (DWORD)(ULONG_PTR)P; A[2] = a1;      // D3DX writes the pass count into the record
        rtCommit(r, 4); return 0;
    }
    rtDrain(); rtEnterExec(); g_rtDirectScope++;
    DWORD hr = ((RtS3)g_rtO_fx[63])(self, a0, a1);
    g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs); g_rtNSync++; g_rtSyncHist[183]++;
    if ((LONG)hr >= 0 && tech && a0) rtPassPut(fx, tech, *(UINT*)(ULONG_PTR)a0);
    return hr;
}
static DWORD __stdcall rt_fx_71(void* self, DWORD a0) {                                        // SetStateManager: callbacks into game code
    RT_PASSTHRU(fx, 71, RtS2, self, a0);
    if (a0) {                                           // D3DX would call game code from the worker: stop the render thread for good
        rtDrain(); rtEnterExec();
        InterlockedExchange(&g_rtInstalled, 0); InterlockedExchange(&g_rtActive, 0);   // from here on every hook passes straight through
        DWORD hr = ((RtS2)g_rtO_fx[71])(self, a0);
        LeaveCriticalSection(&g_rtExecCs);
        logf("rt: the game installed an ID3DXEffectStateManager - render thread switched OFF (all calls direct again).");
        return hr;
    }
    RT_SYNC(fx, 71, 191, RtS2, self, a0);
    return 0;
}


// ---------------------------------------------------------------- render-target / depth-stencil mirrors
// GetRenderTarget / GetDepthStencilSurface answer from the state the queued Set* calls will leave on the device,
// validated exactly as DXVK validates the Set* call (index range, NULL target 0, RENDERTARGET / DEPTHSTENCIL usage).
// Unknown until the first synchronous Get or Set; invalidated by Reset, by the live toggle and by any Set* that
// runs outside the queue (D3DX scopes, other threads, render thread off).
#define RT_D3DERR_NOTFOUND 0x88760866u
static DWORD g_rtMirRT[4], g_rtMirDS;
static BYTE  g_rtMirRTOk[4], g_rtMirDSOk;
static void rtMirInvalidate() { g_rtMirRTOk[0] = g_rtMirRTOk[1] = g_rtMirRTOk[2] = g_rtMirRTOk[3] = 0; g_rtMirDSOk = 0; }
// The right original for a method of a surface that may belong to a class we never hooked: one implementation
// can give depth-stencil surfaces, back buffers and plain surfaces separate vtables, and only the class seen at
// install time is in g_rtO_surf. Where our hook sits in this object's own vtable the saved original is the right
// function; where it does not, the object's own entry is.
static void* rtSurfOrig(DWORD surf, int slot) {
    DWORD fn = 0;
    __try { fn = (*(DWORD**)(ULONG_PTR)surf)[slot]; } __except (EXCEPTION_EXECUTE_HANDLER) { return NULL; }
    if (!fn) return NULL;
    if (fn == (DWORD)(ULONG_PTR)g_rtH_surf[slot]) return g_rtO_surf[slot];
    return (void*)(ULONG_PTR)fn;
}
static __forceinline bool rtSurfUsage(DWORD surf, DWORD* usage) {
    // What GetDesc returns is immutable, and it has to be this surface's own GetDesc: rtSurfOrig picks the right
    // one for the object's class.
    BYTE d[32];
    void* fn = rtSurfOrig(surf, 12);
    if (!fn) return false;
    LONG hr = (LONG)((RtS2)(ULONG_PTR)fn)((void*)(ULONG_PTR)surf, (DWORD)(ULONG_PTR)d);
    if (hr < 0) return false;
    *usage = ((DWORD*)d)[2]; return true;
}
#define RT_DS_DIRECT(SLOT, SIG, ...) \
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) { \
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((SIG)g_rtO_dev[SLOT])(__VA_ARGS__); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; } \
        return ((SIG)g_rtO_dev[SLOT])(__VA_ARGS__); \
    }
static DWORD __stdcall rt_dev_100(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {        // SetStreamSource(stream, buffer, offset, stride)
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) { if (a0 < 16) g_rtDs.vbOk &= ~(1u << a0); else g_rtDs.vbOk = 0; }
    RT_DS_DIRECT(100, RtS5, self, a0, a1, a2, a3)
    bool track = g_rtDs.on && !g_rtDs.recording && a0 < 16;
    if (track && g_rtDs.dev == (DWORD)(ULONG_PTR)self && ((g_rtDs.vbOk >> a0) & 1) && g_rtDs.vb[a0] == a1 && g_rtDs.off[a0] == a2 && g_rtDs.stride[a0] == a3) { PSTAT(g_rtDs.nSkip++); return 0; }
    RtRec* r = rtAlloc(5, 0); r->fn = g_rtO_dev[100]; r->op = 100;
    DWORD* A = rtArgs(r);
    A[0] = (DWORD)(ULONG_PTR)self; A[1] = a0; A[2] = rtObj(r, 2, a1); A[3] = a2; A[4] = a3;
    rtCommit(r, 0);
    if (track) {
        if (g_rtDs.dev != (DWORD)(ULONG_PTR)self) { rtDsInvalAll(); g_rtDs.dev = (DWORD)(ULONG_PTR)self; }
        g_rtDs.vb[a0] = a1; g_rtDs.off[a0] = a2; g_rtDs.stride[a0] = a3; g_rtDs.vbOk |= 1u << a0;
    } else if (a0 < 16) g_rtDs.vbOk &= ~(1u << a0);
    PSTAT(g_rtDs.nSet++);
    return 0;
}
static DWORD __stdcall rt_dev_104(void* self, DWORD a0) {                                       // SetIndices
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) g_rtDs.ibOk = 0;
    RT_DS_DIRECT(104, RtS2, self, a0)
    bool track = g_rtDs.on && !g_rtDs.recording;
    if (track && g_rtDs.dev == (DWORD)(ULONG_PTR)self && g_rtDs.ibOk && g_rtDs.ib == a0) { PSTAT(g_rtDs.nSkip++); return 0; }
    RtRec* r = rtAlloc(2, 0); r->fn = g_rtO_dev[104]; r->op = 104;
    DWORD* A = rtArgs(r);
    A[0] = (DWORD)(ULONG_PTR)self; A[1] = rtObj(r, 1, a0);
    rtCommit(r, 0);
    if (track) { if (g_rtDs.dev != (DWORD)(ULONG_PTR)self) { rtDsInvalAll(); g_rtDs.dev = (DWORD)(ULONG_PTR)self; } g_rtDs.ib = a0; g_rtDs.ibOk = 1; } else g_rtDs.ibOk = 0;
    PSTAT(g_rtDs.nSet++);
    return 0;
}
static DWORD __stdcall rt_dev_87(void* self, DWORD a0) {                                        // SetVertexDeclaration
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) g_rtDs.declOk = 0;
    RT_DS_DIRECT(87, RtS2, self, a0)
    bool track = g_rtDs.on && !g_rtDs.recording;
    if (track && g_rtDs.dev == (DWORD)(ULONG_PTR)self && g_rtDs.declOk && g_rtDs.decl == a0) { PSTAT(g_rtDs.nSkip++); return 0; }
    RtRec* r = rtAlloc(2, 0); r->fn = g_rtO_dev[87]; r->op = 87;
    DWORD* A = rtArgs(r);
    A[0] = (DWORD)(ULONG_PTR)self; A[1] = rtObj(r, 1, a0);
    rtCommit(r, 0);
    if (track) { if (g_rtDs.dev != (DWORD)(ULONG_PTR)self) { rtDsInvalAll(); g_rtDs.dev = (DWORD)(ULONG_PTR)self; } g_rtDs.decl = a0; g_rtDs.declOk = 1; } else g_rtDs.declOk = 0;
    PSTAT(g_rtDs.nSet++);
    return 0;
}
// ---------------------------------------------------------------- UpdateSurface out of a small system-memory surface
// The engine keeps a few 64x64 system-memory surfaces that it locks, edits and uploads with UpdateSurface several
// times a frame. Queued as it was, the upload names the source surface, and D3D reads the source's pixels when the
// call finally runs on the worker - so the engine's NEXT lock of that surface had to wait until the whole queue was
// done (~2 ms each, the biggest remaining wait in a battle). Now the rectangle's pixels are read when the call is
// made and travel in the record; the worker writes them into a private system-memory surface of the same size and
// format and uploads from that. The destination gets exactly the pixels it would have got, in the same place in the
// queue, and the engine's surface is never named by a queued call. Kill switch: AOTR_USSNAP=0.
static LONG g_rtUSOn = 1;
static volatile LONG g_rtNUSSnap = 0, g_rtNUSGeneric = 0, g_rtNUSStage = 0;
struct RtUSStage { DWORD dev, w, h, fmt; DWORD surf; };
#define RT_USN 12
static RtUSStage g_rtUS[RT_USN];
static BYTE* g_rtUSTmp = NULL;
static __forceinline DWORD rtFmtBytes(DWORD f) { return (f == 21 || f == 22) ? 4 : (f == 20 ? 3 : ((f >= 23 && f <= 26) || f == 51) ? 2 : ((f == 28 || f == 50) ? 1 : 0)); }
static DWORD rtUSStageFor(void* dev, DWORD w, DWORD h, DWORD fmt) {                            // game thread
    for (int i = 0; i < RT_USN; ++i) if (g_rtUS[i].surf && g_rtUS[i].dev == (DWORD)(ULONG_PTR)dev && g_rtUS[i].w == w && g_rtUS[i].h == h && g_rtUS[i].fmt == fmt) return g_rtUS[i].surf;
    int slot = -1; for (int i = 0; i < RT_USN; ++i) if (!g_rtUS[i].surf) { slot = i; break; }
    if (slot < 0) return 0;
    void* sfc = NULL;
    rtExecLock(); g_rtDirectScope++;
    DWORD hr = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, void**, void*))g_rtO_dev[36])(dev, w, h, fmt, 2, &sfc, NULL);   // CreateOffscreenPlainSurface, SYSTEMMEM
    g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    if ((LONG)hr < 0 || !sfc) return 0;
    g_rtUS[slot].dev = (DWORD)(ULONG_PTR)dev; g_rtUS[slot].w = w; g_rtUS[slot].h = h; g_rtUS[slot].fmt = fmt; g_rtUS[slot].surf = (DWORD)(ULONG_PTR)sfc; g_rtNUSStage++;
    return g_rtUS[slot].surf;
}
static void rtUSForget() {                                                                   // game thread, before a device Reset: nothing queued may still use them
    bool any = false; for (int i = 0; i < RT_USN; ++i) if (g_rtUS[i].surf) any = true;
    if (!any) return;
    rtDrain(); rtEnterExec(); g_rtDirectScope++;
    for (int i = 0; i < RT_USN; ++i) if (g_rtUS[i].surf) { void* rel = rtSurfOrig(g_rtUS[i].surf, 2); if (rel) ((DWORD(__stdcall*)(void*))rel)((void*)(ULONG_PTR)g_rtUS[i].surf); g_rtUS[i].surf = 0; }
    g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
}
static DWORD __stdcall rt_dev_30(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {          // UpdateSurface(src, srcRect, dst, dstPoint)
    RT_PASSTHRU(dev, 30, RtS5, self, a0, a1, a2, a3);
    if (g_rtUSOn && a0 && a2 && !g_rtObjRefs) {
        BYTE desc[32]; void* gd = rtSurfOrig(a0, 12);
        if (gd && (LONG)((RtS2)gd)((void*)(ULONG_PTR)a0, (DWORD)(ULONG_PTR)desc) >= 0) {
            const DWORD* d = (const DWORD*)desc;                                                // Format Type Usage Pool MSType MSQuality Width Height
            DWORD bpp = rtFmtBytes(d[0]), w = d[6], h = d[7];
            LONG l = 0, t = 0, r = (LONG)w, b = (LONG)h;
            if (a1) { const LONG* q = (const LONG*)(ULONG_PTR)a1; l = q[0]; t = q[1]; r = q[2]; b = q[3]; }
            if (d[3] == 2 && bpp && w && h && w <= 512 && h <= 512 && l >= 0 && t >= 0 && r > l && b > t && r <= (LONG)w && b <= (LONG)h) {
                if (!g_rtUSTmp) g_rtUSTmp = (BYTE*)VirtualAlloc(NULL, 512 * 512 * 4, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
                DWORD stage = g_rtUSTmp ? rtUSStageFor(self, w, h, d[0]) : 0;
                void* fl = rtSurfOrig(a0, 13); void* fu = rtSurfOrig(a0, 14);
                DWORD rw = (DWORD)(r - l), rh = (DWORD)(b - t), rowBytes = rw * bpp, bytes = rowBytes * rh;
                bool got = false;
                if (stage && fl && fu) {
                    struct { LONG l, t, r, b; } rc = { l, t, r, b };
                    struct { INT pitch; void* bits; } lr = { 0, NULL };
                    rtExecLock(); g_rtDirectScope++;
                    if (!rtRefPending(a0) && (LONG)((DWORD(__stdcall*)(void*, void*, void*, DWORD))fl)((void*)(ULONG_PTR)a0, &lr, &rc, 0x10 | 0x800) >= 0) {   // READONLY | NOSYSLOCK
                        if (lr.bits && lr.pitch >= (INT)rowBytes) { for (DWORD y = 0; y < rh; ++y) memcpy(g_rtUSTmp + y * rowBytes, (const BYTE*)lr.bits + (INT)y * lr.pitch, rowBytes); got = true; }
                        ((DWORD(__stdcall*)(void*))fu)((void*)(ULONG_PTR)a0);
                    }
                    g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
                }
                if (got) {
                    RtRec* rec = rtAlloc(15, bytes); rec->kind = 9; rec->fn = g_rtO_dev[30]; rec->op = 30;
                    DWORD* A = rtArgs(rec); BYTE* P = rtPayload(rec); DWORD po = 0;
                    A[0] = (DWORD)(ULONG_PTR)self; A[1] = stage; A[2] = (DWORD)l; A[3] = (DWORD)t; A[4] = (DWORD)r; A[5] = (DWORD)b; A[6] = bpp;
                    A[7] = rtBytes(P, &po, (DWORD)(ULONG_PTR)g_rtUSTmp, bytes);
                    A[8] = a2; A[9] = a3 ? (DWORD)((const LONG*)(ULONG_PTR)a3)[0] : 0; A[10] = a3 ? (DWORD)((const LONG*)(ULONG_PTR)a3)[1] : 0;
                    A[11] = (a1 ? 1u : 0u) | (a3 ? 2u : 0u);
                    A[12] = (DWORD)(ULONG_PTR)g_rtO_surf[13]; A[13] = (DWORD)(ULONG_PTR)g_rtO_surf[14]; A[14] = (DWORD)(ULONG_PTR)g_rtO_dev[30];
                    rtTouch(a2, 30); g_rtRefOp[rtRefIdx(a2)] = 30; rtFreshName(a2);                       // the destination is named, the source is not
                    rtCommit(rec, po); g_rtNUSSnap++;
                    return 0;
                }
            }
        }
    }
    g_rtNUSGeneric++;
    DWORD pl = (a1 ? 16 : 0) + (a3 ? 8 : 0);
    RtRec* r = rtAlloc(5, pl); r->fn = g_rtO_dev[30]; r->op = 30;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtObj(r, 1, a0);
    A[2] = rtBytes(P, &po, a1, 16);
    A[3] = rtObj(r, 3, a2);
    A[4] = rtBytes(P, &po, a3, 8);
    rtCommit(r, po); return 0;
}
static __forceinline DWORD* rtFxRoom(DWORD need) {                                             // need: bytes, a multiple of 4
    if (g_rtFxRec) {
        if (g_rtFxPos + need <= RT_FX_CAP && g_rtFxN < RT_FX_MAXN) return (DWORD*)(g_rtFxBase + g_rtFxPos);
        rtFxClose();
    }
    RtRec* r = rtAlloc(0, RT_FX_CAP);
    r->kind = 8; r->op = 510; r->fn = (void*)g_rtO_fx;
    g_rtFxRec = r; g_rtFxBase = rtPayload(r); g_rtFxPos = 0; g_rtFxN = 0;
    return (DWORD*)g_rtFxBase;
}
#define RT_FX_PRE(SLOT, SIG, ...) \
    DWORD tid = __readfsdword(0x24); \
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) { rtFxInvalAll(0); g_rtNFxOffSlot[(SLOT) & 127]++; g_rtNFxOffWho[tid != g_rtMainTid ? 0 : (!g_rtActive ? 1 : 2)]++; } \
    if (!g_rtActive && !g_rtTried && rtIsGameThread(tid) && !g_rtXDepth) rtInstall(self); \
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) { \
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((SIG)g_rtO_fx[SLOT])(__VA_ARGS__); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; } \
        return ((SIG)g_rtO_fx[SLOT])(__VA_ARGS__); \
    }
typedef DWORD (__stdcall* RtFxS3)(void*, DWORD, DWORD);
typedef DWORD (__stdcall* RtFxS5)(void*, DWORD, DWORD, DWORD, DWORD);
// SetBool / SetInt / SetFloat [h v]
// ---------------------------------------------------------------- effect parameters that already hold the value
// A frame capture of a heavy battle (2026-09-18) shows what the engine actually writes: in the shadow pass one
// world-matrix handle is set 4,668 times a frame with only 327 distinct matrices - 4,421 of those writes are the
// IDENTITY matrix, in runs of up to 2,397 (a static caster's vertices are already in world space). Whole handles are
// constant for the frame (two per-batch matrices and two floats, 973 writes each, every one identical), and across
// both passes about 39,000 parameter writes a frame set the value the effect already holds.
// Setting a D3DX effect parameter to the value it already has changes nothing, so such a write is not queued. What
// the effect holds is tracked per (effect, handle) here; anything that can change a parameter behind this table drops
// it: applying a parameter block, the recording of one (during which nothing is skipped or remembered), releasing an
// effect, a device reset, and every call that does not go through the queue (another thread, a direct scope, the
// render thread off). Textures and raw values are never skipped: a released texture's address can come back for a
// different texture, and raw values were measured 98% distinct anyway. Kill switch: AOTR_FXDEDUPE=0.
#define RT_FXV 16384                                             // power of two, open addressing, 4 probes
struct RtFxVal { DWORD fx, h, epoch; WORD slot, nb; BYTE v[64]; };
static RtFxVal* g_rtFxV = NULL;                // committed at install
static DWORD g_rtFxEpoch = 1;
// Untracked effect setters can invalidate remembered values; keep this cache disabled.
static LONG g_rtFxDedupeOn = 0, g_rtFxRecording = 0;
// The engine applies a parameter block per batch (about 2,000 times a frame), and a block sets only a handful of
// parameters. Which ones is known from the recording between BeginParameterBlock and EndParameterBlock: those
// handles are dropped from the table when the block is applied, instead of dropping everything.
#define RT_FXB 64
struct RtFxBlk { LONG n; LONG known; DWORD fx[RT_FXB], h[RT_FXB]; };
static RtFxBlk* g_rtFxBlk = NULL;                             // indexed like the parameter-block proxies
static RtFxBlk g_rtFxBlkRec;
static volatile LONG g_rtNFxBlkInval = 0;
static volatile LONG g_rtNFxSkip = 0, g_rtNFxKept = 0, g_rtNFxInval = 0;
static volatile LONG g_rtNFxOffSlot[128], g_rtNFxOffWho[3];   // which setter, and from where: 0 other thread, 1 render thread off, 2 direct scope
static volatile LONG g_rtNFxInvalWhy[4] = { 0, 0, 0, 0 };   // 0 off-queue call, 1 parameter block without a recording, 2 device reset, 3 other
static __forceinline void rtFxInvalAll(int why = 3) {
    if (!g_rtFxV) return;
    g_rtNFxInvalWhy[why & 3]++; if (++g_rtFxEpoch == 0) { memset(g_rtFxV, 0, RT_FXV * sizeof(*g_rtFxV)); g_rtFxEpoch = 1; } g_rtNFxInval++; }
static __forceinline void rtFxForget(DWORD fx, DWORD h) {     // this handle's value is no longer known
    if (!g_rtFxV) return;
    DWORD i = ((fx >> 4) ^ (h * 2654435761u)) & (RT_FXV - 1);
    for (int k = 0; k < 4; ++k, i = (i + 1) & (RT_FXV - 1)) {
        RtFxVal& e = g_rtFxV[i];
        if (e.epoch == g_rtFxEpoch && e.fx == fx && e.h == h) { e.epoch = 0; return; }
        if (e.epoch != g_rtFxEpoch) return;
    }
}
static void rtFxBlkApply(DWORD idx) {                          // a recorded block was applied
    RtFxBlk* b = (g_rtFxBlk && idx < RT_PBN) ? &g_rtFxBlk[idx] : NULL;
    if (!b || !b->known) { rtFxInvalAll(1); return; }
    for (LONG i = 0; i < b->n; ++i) rtFxForget(b->fx[i], b->h[i]);
    g_rtNFxBlkInval++;
}
// true: the effect already holds these bytes for this handle (nothing to do). Otherwise the table remembers them.
static __forceinline bool rtFxHeld(void* self, DWORD h, DWORD slot, const void* p, DWORD nb) {
    if (!g_rtFxDedupeOn || !g_rtFxV || !p || nb > 64 || rtIsName(h)) return false;
    DWORD fx = (DWORD)(ULONG_PTR)self;
    if (g_rtFxRecording) {                                     // recorded into a block: its value is no longer known, and the block sets it
        rtFxForget(fx, h);
        RtFxBlk& b = g_rtFxBlkRec;
        for (LONG i = 0; i < b.n; ++i) if (b.fx[i] == fx && b.h[i] == h) return false;
        if (b.n < RT_FXB) { b.fx[b.n] = fx; b.h[b.n] = h; b.n++; } else b.known = 0;
        return false;
    }
    DWORD i = ((fx >> 4) ^ (h * 2654435761u)) & (RT_FXV - 1);
    for (int k = 0; k < 4; ++k, i = (i + 1) & (RT_FXV - 1)) {
        RtFxVal& e = g_rtFxV[i];
        if (e.epoch == g_rtFxEpoch && e.fx == fx && e.h == h) {
            if (e.slot == (WORD)slot && e.nb == (WORD)nb && !memcmp(e.v, p, nb)) { PSTAT(g_rtNFxSkip++); return true; }
            e.slot = (WORD)slot; e.nb = (WORD)nb; memcpy(e.v, p, nb); PSTAT(g_rtNFxKept++); return false;
        }
        if (e.epoch != g_rtFxEpoch) {                            // a free slot, or one left from an older epoch
            e.epoch = g_rtFxEpoch; e.fx = fx; e.h = h; e.slot = (WORD)slot; e.nb = (WORD)nb; memcpy(e.v, p, nb); PSTAT(g_rtNFxKept++); return false;
        }
    }
    g_rtNFxKept++;
    return false;                                                // four collisions: this handle is simply never skipped
}
static __forceinline DWORD rtFxSetValue(void* self, DWORD a0, DWORD a1, DWORD slot) {
    if (g_dgTracing) dgTraceAdd(slot, self, a0, &a1, 4);
    if (rtFxHeld(self, a0, slot, &a1, 4)) return 0;
    if (!g_rtFxBatchOn || rtIsName(a0)) {
        RtRec* r = rtAlloc(3, rtHandleBytes(a0)); r->fn = g_rtO_fx[slot]; r->op = (WORD)(120 + slot);
        DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0;
        A[0] = (DWORD)(ULONG_PTR)self; A[1] = rtHandle(P, &po, a0); A[2] = a1;
        rtCommit(r, po); return 0;
    }
    DWORD* e = rtFxRoom(16);
    e[0] = slot; e[1] = (DWORD)(ULONG_PTR)self; e[2] = a0; e[3] = a1;
    g_rtFxPos += 16; g_rtFxN++; PSTAT(g_rtFx.opN[(slot - 22) >> 2]++);   // 22 -> 0, 26 -> 1, 30 -> 2
    return 0;
}
// SetVector / SetMatrix / SetMatrixTranspose [h p16|p64]
static __forceinline DWORD rtFxSetBytes(void* self, DWORD a0, DWORD a1, DWORD slot, DWORD nb) {
    if (g_dgTracing) dgTraceAdd(slot, self, a0, (const void*)(ULONG_PTR)a1, a1 ? nb : 0);
    if (a1 && rtFxHeld(self, a0, slot, (const void*)(ULONG_PTR)a1, nb)) return 0;
    if (!g_rtFxBatchOn || rtIsName(a0)) {
        RtRec* r = rtAlloc(3, rtHandleBytes(a0) + (a1 ? nb : 0)); r->fn = g_rtO_fx[slot]; r->op = (WORD)(120 + slot);
        DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0;
        A[0] = (DWORD)(ULONG_PTR)self; A[1] = rtHandle(P, &po, a0); A[2] = rtBytes(P, &po, a1, nb);
        rtCommit(r, po); return 0;
    }
    if (a1) {
        DWORD* e = rtFxRoom(12 + nb);
        e[0] = slot | (nb << 8) | 0x80000000u; e[1] = (DWORD)(ULONG_PTR)self; e[2] = a0;
        memcpy(e + 3, (const void*)(ULONG_PTR)a1, nb);
        g_rtFxPos += 12 + nb;
    } else {
        DWORD* e = rtFxRoom(12);
        e[0] = slot; e[1] = (DWORD)(ULONG_PTR)self; e[2] = a0;
        g_rtFxPos += 12;
    }
    g_rtFxN++; PSTAT(g_rtFx.opN[slot == 34 ? 3 : (slot == 38 ? 4 : 5)]++);
    return 0;
}
static DWORD __stdcall rt_fx_22(void* self, DWORD a0, DWORD a1) { RT_FX_PRE(22, RtFxS3, self, a0, a1) return rtFxSetValue(self, a0, a1, 22); }     // SetBool
static DWORD __stdcall rt_fx_26(void* self, DWORD a0, DWORD a1) { RT_FX_PRE(26, RtFxS3, self, a0, a1) return rtFxSetValue(self, a0, a1, 26); }     // SetInt
static DWORD __stdcall rt_fx_30(void* self, DWORD a0, DWORD a1) { RT_FX_PRE(30, RtFxS3, self, a0, a1) return rtFxSetValue(self, a0, a1, 30); }     // SetFloat
static DWORD __stdcall rt_fx_34(void* self, DWORD a0, DWORD a1) { RT_FX_PRE(34, RtFxS3, self, a0, a1) return rtFxSetBytes(self, a0, a1, 34, 16); } // SetVector
static DWORD __stdcall rt_fx_38(void* self, DWORD a0, DWORD a1) { RT_FX_PRE(38, RtFxS3, self, a0, a1) return rtFxSetBytes(self, a0, a1, 38, 64); } // SetMatrix
static DWORD __stdcall rt_fx_44(void* self, DWORD a0, DWORD a1) { RT_FX_PRE(44, RtFxS3, self, a0, a1) return rtFxSetBytes(self, a0, a1, 44, 64); } // SetMatrixTranspose
static DWORD __stdcall rt_fx_52(void* self, DWORD a0, DWORD a1) {                                // SetTexture [h o]
    RT_FX_PRE(52, RtFxS3, self, a0, a1)
    if (!g_rtFxBatchOn || rtIsName(a0) || (a1 && g_rtObjRefs)) {                                  // per-call object refs need a record of their own
        RtRec* r = rtAlloc(3, rtHandleBytes(a0)); r->fn = g_rtO_fx[52]; r->op = 172;
        DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0;
        A[0] = (DWORD)(ULONG_PTR)self; A[1] = rtHandle(P, &po, a0); A[2] = rtObj(r, 2, a1);
        rtCommit(r, po); return 0;
    }
    DWORD* e = rtFxRoom(16);                                                                      // first: the batch this entry joins decides the sequence number
    if (a1) { rtTouch(a1, 172); g_rtRefOp[rtRefIdx(a1)] = 172; rtFreshName(a1); }                     // named by the batch's own record, exactly as rtObj would
    e[0] = 52; e[1] = (DWORD)(ULONG_PTR)self; e[2] = a0; e[3] = a1;
    g_rtFxPos += 16; g_rtFxN++; g_rtFx.opN[6]++;
    return 0;
}
static DWORD __stdcall rt_fx_78(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {          // SetRawValue [h p v v]
    RT_FX_PRE(78, RtFxS5, self, a0, a1, a2, a3)
    if (g_dgTracing) dgTraceAdd(78, self, a0, (const void*)(ULONG_PTR)a1, a1 ? a3 : 0);
    if (!g_rtFxBatchOn || rtIsName(a0) || (a1 && a3 > 2048)) {
        RtRec* r = rtAlloc(5, rtHandleBytes(a0) + (a1 ? a3 : 0)); r->fn = g_rtO_fx[78]; r->op = 198;
        DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0;
        A[0] = (DWORD)(ULONG_PTR)self; A[1] = rtHandle(P, &po, a0); A[2] = rtBytes(P, &po, a1, a1 ? a3 : 0); A[3] = a2; A[4] = a3;
        rtCommit(r, po); return 0;
    }
    DWORD nb = a1 ? a3 : 0, room = 20 + ((nb + 3) & ~3u);
    DWORD* e = rtFxRoom(room);
    e[0] = 78 | (nb << 8) | (a1 ? 0x80000000u : 0); e[1] = (DWORD)(ULONG_PTR)self; e[2] = a0; e[3] = a2; e[4] = a3;
    if (nb) memcpy(e + 5, (const void*)(ULONG_PTR)a1, nb);
    g_rtFxPos += room; g_rtFxN++; g_rtFx.opN[7]++;
    return 0;
}
static DWORD __stdcall rt_dev_23(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4, DWORD a5, DWORD a6, DWORD a7) {   // CreateTexture
    DWORD tid = __readfsdword(0x24);
    typedef DWORD (__stdcall* RtCT)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((RtCT)g_rtO_dev[23])(self, a0, a1, a2, a3, a4, a5, a6, a7); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((RtCT)g_rtO_dev[23])(self, a0, a1, a2, a3, a4, a5, a6, a7);
    }
    rtExecLock(); g_rtDirectScope++;
    DWORD r = ((RtCT)g_rtO_dev[23])(self, a0, a1, a2, a3, a4, a5, a6, a7);
    if ((LONG)r >= 0 && a6) rtFreshAdd(*(DWORD*)(ULONG_PTR)a6);                                 // nothing queued can name it yet
    g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_16(void* self, DWORD a0) {
    // Reset must repair the table even while rendering is toggled off. A compatibility
    // shim may replace some or all slots in the existing table during the call.
    DWORD tid = GetCurrentThreadId();
    if (g_rtActive && tid == g_rtMainTid && !g_rtDirectScope) rtDrain();
    rtEnterExec();
    rtMirInvalidate(); rtDsInvalAll(); rtFxInvalAll(2);
    if (g_rtTMAny) rtTMKillAll();
    if (g_rtBMAny) rtBMKillAll();
    rtDirectLocksForget(); rtFreshForget();
    g_rtDirectScope++;
    DWORD result = ((RtS2)g_rtO_dev[16])(self, a0);
    bool hooked = rtRehookDevice(self);
    g_rtDirectScope--;
    if (!hooked) {
        InterlockedExchange(&g_rtWantOn, 0);
        InterlockedExchange(&g_rtActive, 0);
        InterlockedExchange(&g_rtInstalled, 0);
        logf("sage: device hooks could not be restored after Reset; render thread disabled.");
    }
    if ((LONG)result >= 0) InterlockedExchange(&g_rtPresentHR, 0);
    LeaveCriticalSection(&g_rtExecCs);
    return result;
}
static DWORD __stdcall rt_dev_37(void* self, DWORD a0, DWORD a1) {                             // SetRenderTarget
    { DWORD tid_ = GetCurrentThreadId(); if (tid_ != g_rtMainTid || !g_rtActive || g_rtDirectScope) rtMirInvalidate(); }
    RT_PASSTHRU(dev, 37, RtS3, self, a0, a1);
    if (a0 < 4 && !(a0 == 0 && !a1)) {
        DWORD usage = 0;
        if (!a1) { g_rtMirRT[a0] = 0; g_rtMirRTOk[a0] = 1; }
        else if (rtSurfUsage(a1, &usage)) { if (usage & 1) { g_rtMirRT[a0] = a1; g_rtMirRTOk[a0] = 1; } }   // D3DUSAGE_RENDERTARGET, else the call fails
        else g_rtMirRTOk[a0] = 0;
    }
    RtRec* r = rtAlloc(3, 0); r->fn = g_rtO_dev[37]; r->op = 37;
    DWORD* A = rtArgs(r); A[0] = (DWORD)(ULONG_PTR)self; A[1] = a0; A[2] = rtObj(r, 2, a1);
    rtCommit(r, 0); return 0;
}
static DWORD __stdcall rt_dev_39(void* self, DWORD a0) {                                       // SetDepthStencilSurface
    { DWORD tid_ = GetCurrentThreadId(); if (tid_ != g_rtMainTid || !g_rtActive || g_rtDirectScope) rtMirInvalidate(); }
    RT_PASSTHRU(dev, 39, RtS2, self, a0);
    { DWORD usage = 0;
      if (!a0) { g_rtMirDS = 0; g_rtMirDSOk = 1; }
      else if (rtSurfUsage(a0, &usage)) { if (usage & 2) { g_rtMirDS = a0; g_rtMirDSOk = 1; } }            // D3DUSAGE_DEPTHSTENCIL, else the call fails
      else g_rtMirDSOk = 0; }
    RtRec* r = rtAlloc(2, 0); r->fn = g_rtO_dev[39]; r->op = 39;
    DWORD* A = rtArgs(r); A[0] = (DWORD)(ULONG_PTR)self; A[1] = rtObj(r, 1, a0);
    rtCommit(r, 0); return 0;
}
static DWORD __stdcall rt_dev_38(void* self, DWORD a0, DWORD a1) {                             // GetRenderTarget
    RT_PASSTHRU(dev, 38, RtS3, self, a0, a1);
    if (a0 < 4 && a1 && g_rtMirRTOk[a0]) {
        DWORD sfc = g_rtMirRT[a0]; g_rtNMirror++;
        if (!sfc) { *(DWORD*)(ULONG_PTR)a1 = 0; return RT_D3DERR_NOTFOUND; }
        { void* af = rtSurfOrig(sfc, 1); if (!af) return RT_D3DERR_NOTFOUND; ((RtS1)af)((void*)(ULONG_PTR)sfc); }   // AddRef, as DXVK's ref()
        *(DWORD*)(ULONG_PTR)a1 = sfc; return 0;
    }
    rtSyncNote(38, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 38;
    rtDrain(); rtEnterExec(); g_rtDirectScope++;
    DWORD hr = ((RtS3)g_rtO_dev[38])(self, a0, a1);
    g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs); g_rtNSync++; g_rtSyncHist[38]++;
    if (a0 < 4 && a1) {
        if ((LONG)hr >= 0) { g_rtMirRT[a0] = *(DWORD*)(ULONG_PTR)a1; g_rtMirRTOk[a0] = 1; }
        else if (hr == RT_D3DERR_NOTFOUND) { g_rtMirRT[a0] = 0; g_rtMirRTOk[a0] = 1; }
    }
    return hr;
}
static DWORD __stdcall rt_dev_40(void* self, DWORD a0) {                                       // GetDepthStencilSurface
    RT_PASSTHRU(dev, 40, RtS2, self, a0);
    if (a0 && g_rtMirDSOk) {
        DWORD sfc = g_rtMirDS; g_rtNMirror++;
        if (!sfc) { *(DWORD*)(ULONG_PTR)a0 = 0; return RT_D3DERR_NOTFOUND; }
        { void* af = rtSurfOrig(sfc, 1); if (!af) return RT_D3DERR_NOTFOUND; ((RtS1)af)((void*)(ULONG_PTR)sfc); }
        *(DWORD*)(ULONG_PTR)a0 = sfc; return 0;
    }
    rtSyncNote(40, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 40;
    rtDrain(); rtEnterExec(); g_rtDirectScope++;
    DWORD hr = ((RtS2)g_rtO_dev[40])(self, a0);
    g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs); g_rtNSync++; g_rtSyncHist[40]++;
    if (a0) {
        if ((LONG)hr >= 0) { g_rtMirDS = *(DWORD*)(ULONG_PTR)a0; g_rtMirDSOk = 1; }
        else if (hr == RT_D3DERR_NOTFOUND) { g_rtMirDS = 0; g_rtMirDSOk = 1; }
    }
    return hr;
}

// ---------------------------------------------------------------- direct locks of system-memory surfaces
// A SYSTEMMEM / SCRATCH surface is never sampled by draws; only calls that name it (or its texture) read or
// write its memory. When none of those is still queued, LockRect runs at once under the exec lock instead of
// waiting for the whole queue, and its UnlockRect runs directly too. Anything else keeps the synchronous path.
struct RtDL { DWORD obj, sub, surf; };                    // (surface, 0, surface) or (texture, level, level surface)
#define RT_DLN 64
static RtDL g_rtDL[RT_DLN];
static int g_rtNDL = 0;
static void rtDirectLocksForget() { g_rtNDL = 0; }
static const GUID kRtIIDUnknown = {0x00000000, 0x0000, 0x0000, {0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46}};   // container: texture, swap chain or device
static __forceinline bool rtSysPool(const BYTE* desc) { DWORD pool = ((const DWORD*)desc)[3]; return pool == 2 || pool == 3; }
static DWORD __stdcall rt_surf_13(void* self, DWORD a0, DWORD a1, DWORD a2) {                  // IDirect3DSurface9::LockRect
    if (g_rtTMAtlasOn && a0 && !a1 && g_rtActive && !g_rtDirectScope && __readfsdword(0x24) == g_rtMainTid) {   // the terrain atlas: full lock, served from its mirror
        DWORD ra0 = (DWORD)(ULONG_PTR)_ReturnAddress();
        if (g_rtTMAtlasAny || (ra0 >= 0x004EEC82u && ra0 < 0x004EEE80u)) {
            INT pitch = 0; void* bits = NULL;
            if (rtTMLockD3D((DWORD)(ULONG_PTR)self, a2, &pitch, &bits)) { ((INT*)(ULONG_PTR)a0)[0] = pitch; ((void**)(ULONG_PTR)a0)[1] = bits; return 0; }
        }
    }
    if (g_rtTMAny && !(g_rtInAsyncFilter && __readfsdword(0x24) == g_rtWorkerTid)) rtTMKill((DWORD)(ULONG_PTR)self);   // a lock outside the mirror paths (the queued mip filter only reads level 0)
    RT_PASSTHRU(surf, 13, RtS4, self, a0, a1, a2);
    DWORD sfc = (DWORD)(ULONG_PTR)self, ra = (DWORD)(ULONG_PTR)_ReturnAddress();
    if (ra == 0x00516067u && g_rtSurfLockCaller) ra = g_rtSurfLockCaller;   // SurfaceClass::Lock: the statistics name ITS caller (4 arguments + its 8 bytes of locals above the return address)
    BYTE desc[32]; bool sysSurf = false; WORD pendOp = 0xFFFF; BYTE pendWho = 0, pendExact = 0;
    if ((LONG)((RtS2)g_rtO_surf[12])(self, (DWORD)(ULONG_PTR)desc) >= 0) {                     // GetDesc: immutable
        sysSurf = rtSysPool(desc);
        if ((rtSysPool(desc) || g_rtFreshN) && g_rtNDL < RT_DLN) {
            rtExecLock(); g_rtDirectScope++;
            DWORD cont = 0; void* c = NULL;
            if ((LONG)((DWORD(__stdcall*)(void*, const GUID*, void**))g_rtO_surf[11])(self, &kRtIIDUnknown, &c) >= 0 && c) {    // GetContainer
                cont = (DWORD)(ULONG_PTR)c; ((DWORD(__stdcall*)(void*))(*(void***)c)[2])(c);
            }
            bool fresh_ = !rtSysPool(desc) && cont && rtFreshHas(cont);
            if (fresh_) g_rtNFreshLock++; else if (!rtSysPool(desc)) g_rtNFreshMiss++;
            bool pendS = false, pendC = false;
            if (rtSysPool(desc) || fresh_) { pendS = rtRefPending(sfc); if (pendS) { pendOp = g_rtPendOp; pendExact = g_rtPendExact; }
                                             else if (cont && (pendC = rtRefPending(cont)) != false) { pendOp = g_rtPendOp; pendExact = g_rtPendExact; pendWho = 1; } }
            if ((rtSysPool(desc) || fresh_) && !pendS && !pendC) {
                DWORD hr = ((RtS4)g_rtO_surf[13])(self, a0, a1, a2);
                if ((LONG)hr >= 0) { RtDL& e = g_rtDL[g_rtNDL++]; e.obj = sfc; e.sub = 0; e.surf = sfc; }
                g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
                g_rtNDirectLock++; rtLockNote(ra, desc, a2, 1);
                return hr;
            }
            g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
        }
        rtLockNote(ra, desc, a2, 0, pendOp, pendWho, pendExact);
    }
    // Synchronous: the queue drains, then the lock runs here. A system-memory surface locked this way is remembered
    // as locked directly, so its UnlockRect runs directly as well instead of being queued. (A queued unlock left the
    // surface "pending" when the engine uploaded it a moment later, which sent that UpdateSurface down the generic
    // path, which made the next lock of the same staging surface wait again: v23 shows whole bursts of 64x64 glyph
    // uploads each waiting for the queue once one of them had.)
    rtSyncNote(303, ra); g_rtCurOp = 303; rtDrain(); rtEnterExec(); g_rtDirectScope++;
    DWORD hr_ = ((RtS4)g_rtO_surf[13])(self, a0, a1, a2);
    if ((LONG)hr_ >= 0 && sysSurf && g_rtNDL < RT_DLN) { RtDL& e = g_rtDL[g_rtNDL++]; e.obj = sfc; e.sub = 0; e.surf = sfc; g_rtNSyncDL++; }
    g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs); g_rtNSync++; g_rtSyncHist[303]++;
    return hr_;
}
static DWORD __stdcall rt_surf_14(void* self) {                                                // IDirect3DSurface9::UnlockRect
    RT_PASSTHRU(surf, 14, RtS1, self);
    DWORD sfc = (DWORD)(ULONG_PTR)self;
    if (g_rtTMAny && rtTMUnlockD3D(sfc)) return 0;                                                // locked through the atlas mirror: the rows are queued
    for (int i = g_rtNDL - 1; i >= 0; --i) {
        if (g_rtDL[i].surf != sfc) continue;
        g_rtDL[i] = g_rtDL[--g_rtNDL];
        rtExecLock(); g_rtDirectScope++;
        DWORD hr = ((RtS1)g_rtO_surf[14])(self);
        g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
        g_rtNDirectUnlock++;
        return hr;
    }
    RtRec* r = rtAlloc(1, 0); r->fn = g_rtO_surf[14]; r->op = 304; rtArgs(r)[0] = sfc;
    rtTouch(sfc, 304); g_rtRefOp[rtRefIdx(sfc)] = 304; rtCommit(r, 0); return 0;
}
static DWORD __stdcall rt_tex_19(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {        // IDirect3DTexture9::LockRect(level, locked, rect, flags)
    if (g_rtTMAny && !(g_rtInAsyncFilter && __readfsdword(0x24) == g_rtWorkerTid)) rtTMKill((DWORD)(ULONG_PTR)self);
    RT_PASSTHRU(tex, 19, RtS5, self, a0, a1, a2, a3);
    DWORD t = (DWORD)(ULONG_PTR)self, ra = (DWORD)(ULONG_PTR)_ReturnAddress();
    BYTE desc[32]; WORD tPendOp = 0xFFFF; BYTE tPendWho = 0, tPendExact = 0;
    if ((LONG)((RtS3)g_rtO_tex[17])(self, a0, (DWORD)(ULONG_PTR)desc) >= 0) {                  // GetLevelDesc: immutable
        if ((rtSysPool(desc) || rtFreshHas(t)) && g_rtNDL < RT_DLN) {
            bool fresh_ = !rtSysPool(desc);
            if (fresh_) g_rtNFreshLock++;
            rtExecLock(); g_rtDirectScope++;
            void* lvl = NULL;
            ((RtS3)g_rtO_tex[18])(self, a0, (DWORD)(ULONG_PTR)&lvl);                                // GetSurfaceLevel
            DWORD ls = (DWORD)(ULONG_PTR)lvl;
            if (lvl) { void* rf = rtSurfOrig((DWORD)(ULONG_PTR)lvl, 2); if (rf) ((RtS1)rf)(lvl); }
            bool pendT = rtRefPending(t), pendL = false;
            if (pendT) { tPendOp = g_rtPendOp; tPendExact = g_rtPendExact; }
            else if (ls && (pendL = rtRefPending(ls)) != false) { tPendOp = g_rtPendOp; tPendExact = g_rtPendExact; tPendWho = 1; }
            if (!pendT && !pendL) {
                DWORD hr = ((RtS5)g_rtO_tex[19])(self, a0, a1, a2, a3);
                if ((LONG)hr >= 0) { RtDL& e = g_rtDL[g_rtNDL++]; e.obj = t; e.sub = a0; e.surf = ls; }
                g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
                g_rtNDirectLock++; rtLockNote(ra, desc, a3 | 0x80000000u, 1);
                return hr;
            }
            g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
        }
        rtLockNote(ra, desc, a3 | 0x80000000u, 0, tPendOp, tPendWho, tPendExact);
    }
    RT_SYNC(tex, 19, 219, RtS5, self, a0, a1, a2, a3);
    return 0;
}
static DWORD __stdcall rt_tex_20(void* self, DWORD a0) {                                       // IDirect3DTexture9::UnlockRect(level)
    RT_PASSTHRU(tex, 20, RtS2, self, a0);
    DWORD t = (DWORD)(ULONG_PTR)self;
    if (g_rtNDL) {
        DWORD ls = 0;
        for (int i = g_rtNDL - 1; i >= 0; --i) {
            bool hit = (g_rtDL[i].obj == t && g_rtDL[i].sub == a0);
            if (!hit && g_rtDL[i].obj == g_rtDL[i].surf) {                                          // locked through the level surface?
                if (!ls) { void* lvl = NULL; g_rtDirectScope++; ((RtS3)g_rtO_tex[18])(self, a0, (DWORD)(ULONG_PTR)&lvl);
                           if (lvl) { ls = (DWORD)(ULONG_PTR)lvl; void* rf = rtSurfOrig(ls, 2); if (rf) ((RtS1)rf)(lvl); } g_rtDirectScope--; }
                hit = ls && g_rtDL[i].surf == ls;
            }
            if (!hit) continue;
            g_rtDL[i] = g_rtDL[--g_rtNDL];
            rtExecLock(); g_rtDirectScope++;
            DWORD hr = ((RtS2)g_rtO_tex[20])(self, a0);
            g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
            g_rtNDirectUnlock++;
            return hr;
        }
    }
    RtRec* r = rtAlloc(2, 0); r->fn = g_rtO_tex[20]; r->op = 220; DWORD* A = rtArgs(r); A[0] = t; A[1] = a0;
    rtTouch(t, 220); g_rtRefOp[rtRefIdx(t)] = 220; rtCommit(r, 0); return 0;
}

// ---------------------------------------------------------------- immutable ID3DXEffect queries (cached)
// Descriptions, handle lookups and IsParameterUsed never change for a live effect. The game asks for them
// thousands of times per frame (GetParameterDesc ~9000/frame in battle), and each one used to force a full
// queue drain. First call per key runs synchronously; later calls are answered from this cache.
#define RT_QC 65536
struct RtQ { DWORD fx; WORD slot; BYTE pad0; BYTE valid; DWORD a0, a1; DWORD soff; WORD slen; WORD pad1; DWORD ret; BYTE out[44]; };
static RtQ* g_rtQ = NULL;
#define RT_QSTR (4u << 20)
static char* g_rtQStr = NULL;                           // key strings, append-only
static DWORD g_rtQStrTop = 0;
static __forceinline DWORD rtQHash(DWORD fx, DWORD slot, DWORD a0, DWORD a1) {
    DWORD h = (fx * 2654435761u) ^ (slot * 40503u) ^ (a0 * 2246822519u) ^ (a1 * 3266489917u);
    return h ^ (h >> 15);
}
static RtQ* rtQFind(DWORD fx, DWORD slot, DWORD a0, DWORD a1, const char* str, int slen) {
    if (!g_rtQ) return NULL;
    DWORD h = rtQHash(fx, slot, a0, a1);
    for (int i = 0; i < 64; ++i) {
        RtQ* e = &g_rtQ[(h + i) & (RT_QC - 1)];
        if (e->fx == 0) return NULL;
        if (e->valid && e->fx == fx && e->slot == slot && e->a0 == a0 && e->a1 == a1 && e->slen == (WORD)slen && (slen == 0 || memcmp(g_rtQStr + e->soff, str, slen) == 0)) return e;
    }
    return NULL;
}
static RtQ* rtQNew(DWORD fx, DWORD slot, DWORD a0, DWORD a1, const char* str, int slen) {
    if (!g_rtQ) return NULL;
    DWORD h = rtQHash(fx, slot, a0, a1);
    for (int i = 0; i < 64; ++i) {
        RtQ* e = &g_rtQ[(h + i) & (RT_QC - 1)];
        if (!e->valid) {
            if (slen) { if (!g_rtQStr || g_rtQStrTop + (DWORD)slen > RT_QSTR) return NULL; memcpy(g_rtQStr + g_rtQStrTop, str, slen); e->soff = g_rtQStrTop; g_rtQStrTop += slen; }
            e->fx = fx; e->slot = (WORD)slot; e->a0 = a0; e->a1 = a1; e->slen = (WORD)slen; return e;
        }
    }
    return NULL;
}
static void rtQForget(DWORD fx) { if (g_rtQ) for (int i = 0; i < RT_QC; ++i) if (g_rtQ[i].fx == fx) g_rtQ[i].valid = 0; }   // keep fx as tombstone
static int rtQStr(DWORD s, DWORD* hash) {               // -1 = not cacheable
    if (!s) return -1;
    __try {
        const char* p = (const char*)(ULONG_PTR)s; DWORD h = 2166136261u; int n = 0;
        for (; n < 1000 && p[n]; ++n) h = (h ^ (BYTE)p[n]) * 16777619u;
        if (p[n]) return -1;
        *hash = h; return n;
    } __except (EXCEPTION_EXECUTE_HANDLER) { return -1; }
}
typedef DWORD (__stdcall* RtFx1)(void*, DWORD);
typedef DWORD (__stdcall* RtFx2)(void*, DWORD, DWORD);
static DWORD rtQSync1(void* self, int slot, DWORD x) { RT_SYNC(fx, slot, 120 + slot, RtFx1, self, x); return 0; }
static DWORD rtQSync2(void* self, int slot, DWORD x, DWORD y) { RT_SYNC(fx, slot, 120 + slot, RtFx2, self, x, y); return 0; }
static DWORD rtQDesc0(void* self, int slot, DWORD pDesc, int bytes) {                 // GetDesc(pDesc)
    DWORD fx = (DWORD)(ULONG_PTR)self;
    if (!pDesc) return rtQSync1(self, slot, pDesc);
    RtQ* e = rtQFind(fx, slot, 0, 0, NULL, 0);
    if (e) { memcpy((void*)(ULONG_PTR)pDesc, e->out, bytes); g_rtQHit++; return e->ret; }
    DWORD hr = rtQSync1(self, slot, pDesc); g_rtQMiss++;
    if ((LONG)hr >= 0 && (e = rtQNew(fx, slot, 0, 0, NULL, 0)) != NULL) { memcpy(e->out, (void*)(ULONG_PTR)pDesc, bytes); e->ret = hr; e->valid = 1; }
    return hr;
}
static DWORD rtQDesc1(void* self, int slot, DWORD h, DWORD pDesc, int bytes) {        // Get*Desc(handle, pDesc)
    DWORD fx = (DWORD)(ULONG_PTR)self;
    if (!pDesc || rtIsName(h)) return rtQSync2(self, slot, h, pDesc);
    RtQ* e = rtQFind(fx, slot, h, 0, NULL, 0);
    if (e) { memcpy((void*)(ULONG_PTR)pDesc, e->out, bytes); g_rtQHit++; return e->ret; }
    DWORD hr = rtQSync2(self, slot, h, pDesc); g_rtQMiss++;
    if ((LONG)hr >= 0 && (e = rtQNew(fx, slot, h, 0, NULL, 0)) != NULL) { memcpy(e->out, (void*)(ULONG_PTR)pDesc, bytes); e->ret = hr; e->valid = 1; }
    return hr;
}
static DWORD rtQVal1(void* self, int slot, DWORD idx) {                                // GetTechnique(i), GetFunction(i)
    DWORD fx = (DWORD)(ULONG_PTR)self;
    RtQ* e = rtQFind(fx, slot, idx, 0, NULL, 0);
    if (e) { g_rtQHit++; return e->ret; }
    DWORD r = rtQSync1(self, slot, idx); g_rtQMiss++;
    if ((e = rtQNew(fx, slot, idx, 0, NULL, 0)) != NULL) { e->ret = r; e->valid = 1; }
    return r;
}
// ---------------------------------------------------------------- GetInt on annotation handles
// Annotations are fixed effect metadata; the engine reads the int annotation "MaxSkinningBones" whenever it sets up a
// skinned mesh, and every read was a synchronous queue drain. Handles returned by GetAnnotation / GetAnnotationByName
// are recorded per effect; the first GetInt on such a handle runs synchronously and its result is kept, later reads
// return it. Everything recorded for an effect is forgotten on any Release of that effect.
struct RtAnn { DWORD fx, h, val, hr; BYTE state, pad[3]; };      // state 1: annotation handle, 2: value kept
#define RT_ANN 1024
static RtAnn g_rtAnn[RT_ANN];
static volatile LONG g_rtNAnnHit = 0;
static RtAnn* rtAnnSlot(DWORD fx, DWORD h, bool create) {
    DWORD k = ((fx * 2654435761u) ^ (h * 2246822519u)) >> 22;
    for (int i = 0; i < 8; ++i) {
        RtAnn& a = g_rtAnn[(k + i) & (RT_ANN - 1)];
        if (a.state && a.fx == fx && a.h == h) return &a;
        if (!a.state) { if (!create) return NULL; a.fx = fx; a.h = h; a.state = 1; return &a; }
    }
    return NULL;
}
static void rtAnnNote(DWORD fx, DWORD h) { if (h && !rtIsName(h)) rtAnnSlot(fx, h, true); }
static void rtAnnForget(DWORD fx) { for (int i = 0; i < RT_ANN; ++i) if (g_rtAnn[i].state && g_rtAnn[i].fx == fx) g_rtAnn[i].state = 0; }
static DWORD rtQVal2(void* self, int slot, DWORD h, DWORD idx);
static DWORD rtQVal2Ann(void* self, int slot, DWORD h, DWORD idx);
static DWORD rtQVal2(void* self, int slot, DWORD h, DWORD idx) {                       // GetParameter/Element/Pass/Annotation(h, i), IsParameterUsed(h, h)
    if (slot == 18) { DWORD r = rtQVal2Ann(self, slot, h, idx); rtAnnNote((DWORD)(ULONG_PTR)self, r); return r; }
    return rtQVal2Ann(self, slot, h, idx);
}
static DWORD rtQVal2Ann(void* self, int slot, DWORD h, DWORD idx) {
    DWORD fx = (DWORD)(ULONG_PTR)self;
    if (rtIsName(h) || (slot == 62 && rtIsName(idx))) return rtQSync2(self, slot, h, idx);
    RtQ* e = rtQFind(fx, slot, h, idx, NULL, 0);
    if (e) { g_rtQHit++; return e->ret; }
    DWORD r = rtQSync2(self, slot, h, idx); g_rtQMiss++;
    if ((e = rtQNew(fx, slot, h, idx, NULL, 0)) != NULL) { e->ret = r; e->valid = 1; }
    return r;
}
static DWORD rtQStr1(void* self, int slot, DWORD name) {                               // GetTechniqueByName, GetFunctionByName
    DWORD fx = (DWORD)(ULONG_PTR)self, sh = 0; int n = rtQStr(name, &sh);
    if (n < 0) return rtQSync1(self, slot, name);
    RtQ* e = rtQFind(fx, slot, 0, sh, (const char*)(ULONG_PTR)name, n);
    if (e) { g_rtQHit++; return e->ret; }
    DWORD r = rtQSync1(self, slot, name); g_rtQMiss++;
    if ((e = rtQNew(fx, slot, 0, sh, (const char*)(ULONG_PTR)name, n)) != NULL) { e->ret = r; e->valid = 1; }
    return r;
}
static DWORD rtQStr2Ann(void* self, int slot, DWORD h, DWORD name);
static DWORD rtQStr2(void* self, int slot, DWORD h, DWORD name) {
    DWORD r = rtQStr2Ann(self, slot, h, name);
    if (slot == 19) rtAnnNote((DWORD)(ULONG_PTR)self, r);
    return r;
}
static DWORD rtQStr2Ann(void* self, int slot, DWORD h, DWORD name) {                   // GetParameterByName/BySemantic, GetPassByName, GetAnnotationByName
    DWORD fx = (DWORD)(ULONG_PTR)self, sh = 0, ka0 = h; int n; char kb[2016]; const char* key = (const char*)(ULONG_PTR)name;
    if (rtIsName(h)) {                                  // parent given by name: key = parent \x01 name
        DWORD ph = 0; int pn = rtQStr(h, &ph); n = rtQStr(name, &sh);
        if (pn < 0 || n < 0) return rtQSync2(self, slot, h, name);
        memcpy(kb, (const char*)(ULONG_PTR)h, pn); kb[pn] = 1; memcpy(kb + pn + 1, key, n);
        key = kb; n = pn + 1 + n; sh = sh * 16777619u ^ ph; ka0 = 0xFFFFFFFFu;
    } else n = rtQStr(name, &sh);
    if (n < 0) return rtQSync2(self, slot, h, name);
    RtQ* e = rtQFind(fx, slot, ka0, sh, key, n);
    if (e) { g_rtQHit++; return e->ret; }
    DWORD r = rtQSync2(self, slot, h, name); g_rtQMiss++;
    if ((e = rtQNew(fx, slot, ka0, sh, key, n)) != NULL) { e->ret = r; e->valid = 1; }
    return r;
}
#define RT_FXQ_PRE(SLOT, SIG, ...) DWORD tid = __readfsdword(0x24); \
    if (!g_rtActive && !g_rtTried && rtIsGameThread(tid) && !g_rtXDepth) rtInstall(self); \
    RT_PASSTHRU(fx, SLOT, SIG, __VA_ARGS__)
static DWORD __stdcall rt_fx_3(void* self, DWORD a0)            { RT_FXQ_PRE(3, RtFx1, self, a0);  return rtQDesc0(self, 3, a0, 16); }
static DWORD __stdcall rt_fx_4(void* self, DWORD a0, DWORD a1)  { RT_FXQ_PRE(4, RtFx2, self, a0, a1); return rtQDesc1(self, 4, a0, a1, 44); }
static DWORD __stdcall rt_fx_5(void* self, DWORD a0, DWORD a1)  { RT_FXQ_PRE(5, RtFx2, self, a0, a1); return rtQDesc1(self, 5, a0, a1, 12); }
static DWORD __stdcall rt_fx_6(void* self, DWORD a0, DWORD a1)  { RT_FXQ_PRE(6, RtFx2, self, a0, a1); return rtQDesc1(self, 6, a0, a1, 16); }
static DWORD __stdcall rt_fx_7(void* self, DWORD a0, DWORD a1)  { RT_FXQ_PRE(7, RtFx2, self, a0, a1); return rtQDesc1(self, 7, a0, a1, 8); }
static DWORD __stdcall rt_fx_8(void* self, DWORD a0, DWORD a1)  { RT_FXQ_PRE(8, RtFx2, self, a0, a1); return rtQVal2(self, 8, a0, a1); }
static DWORD __stdcall rt_fx_9(void* self, DWORD a0, DWORD a1)  { RT_FXQ_PRE(9, RtFx2, self, a0, a1); return rtQStr2(self, 9, a0, a1); }
static DWORD __stdcall rt_fx_10(void* self, DWORD a0, DWORD a1) { RT_FXQ_PRE(10, RtFx2, self, a0, a1); return rtQStr2(self, 10, a0, a1); }
static DWORD __stdcall rt_fx_11(void* self, DWORD a0, DWORD a1) { RT_FXQ_PRE(11, RtFx2, self, a0, a1); return rtQVal2(self, 11, a0, a1); }
static DWORD __stdcall rt_fx_12(void* self, DWORD a0)           { RT_FXQ_PRE(12, RtFx1, self, a0); return rtQVal1(self, 12, a0); }
static DWORD __stdcall rt_fx_13(void* self, DWORD a0)           { RT_FXQ_PRE(13, RtFx1, self, a0); return rtQStr1(self, 13, a0); }
static DWORD __stdcall rt_fx_14(void* self, DWORD a0, DWORD a1) { RT_FXQ_PRE(14, RtFx2, self, a0, a1); return rtQVal2(self, 14, a0, a1); }
static DWORD __stdcall rt_fx_15(void* self, DWORD a0, DWORD a1) { RT_FXQ_PRE(15, RtFx2, self, a0, a1); return rtQStr2(self, 15, a0, a1); }
static DWORD __stdcall rt_fx_16(void* self, DWORD a0)           { RT_FXQ_PRE(16, RtFx1, self, a0); return rtQVal1(self, 16, a0); }
static DWORD __stdcall rt_fx_17(void* self, DWORD a0)           { RT_FXQ_PRE(17, RtFx1, self, a0); return rtQStr1(self, 17, a0); }
static DWORD __stdcall rt_fx_18(void* self, DWORD a0, DWORD a1) { RT_FXQ_PRE(18, RtFx2, self, a0, a1); return rtQVal2(self, 18, a0, a1); }
static DWORD __stdcall rt_fx_19(void* self, DWORD a0, DWORD a1) { RT_FXQ_PRE(19, RtFx2, self, a0, a1); return rtQStr2(self, 19, a0, a1); }
static DWORD __stdcall rt_fx_27(void* self, DWORD a0, DWORD a1) {                             // GetInt: kept for annotation handles
    RT_FXQ_PRE(27, RtFx2, self, a0, a1);
    RtAnn* an = a1 ? rtAnnSlot((DWORD)(ULONG_PTR)self, a0, false) : NULL;
    if (an && an->state == 2) { *(DWORD*)(ULONG_PTR)a1 = an->val; g_rtNAnnHit++; return an->hr; }
    rtSyncNote(147, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 147;
    rtDrain(); rtEnterExec(); g_rtDirectScope++;
    DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[27])(self, a0, a1);
    g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs); g_rtNSync++; g_rtSyncHist[147]++;
    if (an && (LONG)r >= 0) { an->val = *(DWORD*)(ULONG_PTR)a1; an->hr = r; an->state = 2; }
    return r;
}
static DWORD __stdcall rt_fx_62(void* self, DWORD a0, DWORD a1) { RT_FXQ_PRE(62, RtFx2, self, a0, a1); return rtQVal2(self, 62, a0, a1); }

// ---------------------------------------------------------------- parameter blocks through the queue (proxy handles)
// The engine rebuilds material parameter blocks during battles (Delete, Begin, Set*, End); each synchronous
// Begin/End used to wait for the whole queue.
static BYTE* g_rtPBLive = NULL;                         // game thread: proxy index handed out and not yet deleted
static DWORD g_rtPBFree[RT_PBN]; static int g_rtPBNFree = 0; static DWORD g_rtPBNext = 1;
static volatile LONG g_rtNPBProxy = 0;
static DWORD rtPBAlloc() {
    if (!g_rtPBReal || !g_rtPBLive) return 0;
    DWORD idx = g_rtPBNFree ? g_rtPBFree[--g_rtPBNFree] : (g_rtPBNext < RT_PBN ? g_rtPBNext++ : 0);
    if (idx) g_rtPBLive[idx] = 1;
    return idx;
}
static void rtPBRelease(DWORD idx) { g_rtPBLive[idx] = 0; if (g_rtPBNFree < (int)RT_PBN) g_rtPBFree[g_rtPBNFree++] = idx; }
static DWORD __stdcall rt_fx_73(void* self) {                                                    // BeginParameterBlock
    g_rtFxRecording = 1;                                                                         // recorded: nothing may be skipped, and the handles are collected
    g_rtFxBlkRec.n = 0; g_rtFxBlkRec.known = 1;
    RT_FXQ_PRE(73, RtS1, self);
    RtRec* r = rtAlloc(1, 0); r->fn = g_rtO_fx[73]; r->op = 193; rtArgs(r)[0] = (DWORD)(ULONG_PTR)self;
    rtCommit(r, 0); return 0;
}
static DWORD __stdcall rt_fx_74(void* self) {                                                    // EndParameterBlock -> proxy handle
    g_rtFxRecording = 0;
    RT_FXQ_PRE(74, RtS1, self);
    DWORD idx = rtPBAlloc();
    if (!idx) { rtFxInvalAll(); RT_SYNC(fx, 74, 194, RtS1, self); }                             // table exhausted: real handle, and the block's handles stay unknown
    if (g_rtFxBlk) g_rtFxBlk[idx] = g_rtFxBlkRec;
    RtRec* r = rtAlloc(2, 0); r->kind = 5; r->fn = g_rtO_fx[74]; r->op = 194;
    DWORD* A = rtArgs(r); A[0] = (DWORD)(ULONG_PTR)self; A[1] = idx;
    rtCommit(r, 0); g_rtNPBProxy++;
    return 0xFFFF0003u | (idx << 2);
}
static DWORD __stdcall rt_fx_75(void* self, DWORD a0) {                                          // ApplyParameterBlock
    if (rtIsPBProxy(a0)) rtFxBlkApply(rtPBIndex(a0)); else rtFxInvalAll(1);                       // only what the block sets
    RT_FXQ_PRE(75, RtS2, self, rtPBReal(a0));                                                    // outside the queue: the real handle
    RtRec* r;
    if (rtIsPBProxy(a0)) { r = rtAlloc(3, 0); r->kind = 6; r->fn = g_rtO_fx[75]; r->op = 195; DWORD* A = rtArgs(r); A[0] = (DWORD)(ULONG_PTR)self; A[1] = rtPBIndex(a0); A[2] = 0; }
    else { r = rtAlloc(2, 0); r->fn = g_rtO_fx[75]; r->op = 195; DWORD* A = rtArgs(r); A[0] = (DWORD)(ULONG_PTR)self; A[1] = a0; }
    rtCommit(r, 0); return 0;
}
static DWORD __stdcall rt_fx_76(void* self, DWORD a0) {                                          // DeleteParameterBlock
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && rtIsGameThread(tid) && !g_rtXDepth) rtInstall(self);
    bool proxy = rtIsPBProxy(a0) && g_rtPBReal && g_rtPBLive;
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        DWORD real = rtPBReal(a0), hr;
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); hr = ((RtS2)g_rtO_fx[76])(self, real); LeaveCriticalSection(&g_rtExecCs); }
        else hr = ((RtS2)g_rtO_fx[76])(self, real);
        if (proxy && tid == g_rtMainTid && g_rtPBLive[rtPBIndex(a0)]) { g_rtPBReal[rtPBIndex(a0)] = 0; rtPBRelease(rtPBIndex(a0)); }
        return hr;
    }
    RtRec* r;
    if (proxy) {
        DWORD idx = rtPBIndex(a0);
        if (!g_rtPBLive[idx]) return 0x8876086Cu;                                                // already deleted: D3DERR_INVALIDCALL, nothing queued
        r = rtAlloc(3, 0); r->kind = 6; r->fn = g_rtO_fx[76]; r->op = 196; DWORD* A = rtArgs(r); A[0] = (DWORD)(ULONG_PTR)self; A[1] = idx; A[2] = 1;
        rtCommit(r, 0); rtPBRelease(idx); return 0;
    }
    r = rtAlloc(2, 0); r->fn = g_rtO_fx[76]; r->op = 196; DWORD* A = rtArgs(r); A[0] = (DWORD)(ULONG_PTR)self; A[1] = a0;
    rtCommit(r, 0); return 0;
}

#include "aotr_rtmirror.inc"

// ---------------------------------------------------------------- engine per-pixel surface writes (radar blips)
// SurfaceClass::DrawPixel (0x5165E0) and its alpha twin (0x5166C0) do GetDesc + LockRect(1x1) + write + UnlockRect
// for every pixel - ~650 synchronous queue drains per battle frame for the minimap. The description is immutable,
// so it is read on the game thread; the lock, the write and the unlock become one record the worker executes in
// queue order, exactly as the engine would have.
typedef void (__fastcall* tRtPixelFn)(DWORD* sc, void* edx, DWORD x, DWORD y, DWORD v);
static tRtPixelFn o_rtDrawPixel = NULL, o_rtSetAlpha = NULL;
static volatile LONG g_rtNPixel = 0;
static void rtPixelRecord(DWORD surf, DWORD x, DWORD y, DWORD v, DWORD mode) {
    RtRec* r = rtAlloc(6, 0); r->kind = 4; r->fn = g_rtO_surf[13]; r->op = 303;
    DWORD* A = rtArgs(r); A[0] = surf; A[1] = x; A[2] = y; A[3] = v; A[4] = mode; A[5] = (DWORD)(ULONG_PTR)g_rtO_surf[14];
    rtTouch(surf); rtCommit(r, 0); g_rtNPixel++;
}
static void __fastcall hk_rtDrawPixel(DWORD* sc, void* edx, DWORD x, DWORD y, DWORD color) {
    if (__readfsdword(0x24) != g_rtMainTid || !g_rtActive || g_rtDirectScope || !sc || !sc[0]) { o_rtDrawPixel(sc, edx, x, y, color); return; }
    DWORD desc[3] = {0, 0, 0};
    ((void (__fastcall*)(DWORD*, void*, DWORD*))(ULONG_PTR)0x00515FD0)(sc, NULL, desc);          // SurfaceClass::Get_Description
    DWORD bpp = (DWORD)((int (__fastcall*)(DWORD*, void*))(ULONG_PTR)0x00515F10)(desc, NULL);     // bytes per pixel of that format
    if (g_rtTMAny) rtTMPixel(sc[0], x, y, color, bpp);
    rtPixelRecord(sc[0], x, y, color, bpp);
}
static void __fastcall hk_rtSetAlpha(DWORD* sc, void* edx, DWORD x, DWORD y, DWORD alpha) {
    if (__readfsdword(0x24) != g_rtMainTid || !g_rtActive || g_rtDirectScope || !sc || !sc[0]) { o_rtSetAlpha(sc, edx, x, y, alpha); return; }
    DWORD desc[3] = {0, 0, 0};
    ((void (__fastcall*)(DWORD*, void*, DWORD*))(ULONG_PTR)0x00515FD0)(sc, NULL, desc);
    if (g_rtTMAny) rtTMPixel(sc[0], x, y, alpha, desc[0] == 21 ? 0x100u : 0u);
    rtPixelRecord(sc[0], x, y, alpha, desc[0] == 21 ? 0x100u : 0u);                               // alpha byte of A8R8G8B8 only
}
// W3DShroud-style texture updates (0x472EF4 16-bit, 0x473E?? 32-bit) lock a rect of a MANAGED texture through
// SurfaceClass::Lock(pitch, l, t, r, b) (0x516090), memcpy every row of the rect from the CPU shroud buffer and unlock
// (0x516110). At those two call-site pairs only, the rect goes to a staging buffer with pitch = width * bytes per pixel
// and the unlock queues LockRect + row copies + UnlockRect for the worker - the same lock, the same bytes, in order.
struct RtShrStage { DWORD* sc; DWORD surf, l, t, r, b, bpp, cap; BYTE* mem; };
static RtShrStage g_rtShr[4];
static int g_rtNShr = 0;
static volatile LONG g_rtNShroud = 0;
typedef void* (__fastcall* tRtSurfLock)(DWORD*, void*, int*, DWORD, DWORD, DWORD, DWORD);
typedef void  (__fastcall* tRtSurfUnlock)(DWORD*, void*);
static const DWORD kSurfLockRect = 0x00516090, kSurfUnlock = 0x00516110;
static void* __fastcall hk_rtShroudLock(DWORD* sc, void* edx, int* pitch, DWORD l, DWORD t, DWORD r, DWORD b) {
    tRtSurfLock orig = (tRtSurfLock)(ULONG_PTR)kSurfLockRect;
    if (g_rtTMAny && sc && sc[0]) rtTMKill(sc[0]);
    if (__readfsdword(0x24) != g_rtMainTid || !g_rtActive || g_rtDirectScope || !sc || !sc[0] || !pitch || r <= l || b <= t || g_rtNShr >= 4)
        return orig(sc, edx, pitch, l, t, r, b);
    BYTE desc[32];
    if ((LONG)((RtS2)g_rtO_surf[12])((void*)(ULONG_PTR)sc[0], (DWORD)(ULONG_PTR)desc) < 0) return orig(sc, edx, pitch, l, t, r, b);
    const DWORD* d = (const DWORD*)desc;                // Format Type Usage Pool MSType MSQuality Width Height
    DWORD bpp = (d[0] == 21 || d[0] == 22) ? 4u : ((d[0] >= 23 && d[0] <= 26) ? 2u : 0u);
    DWORD w = r - l, h = b - t;
    if (!bpp || r > d[6] || b > d[7] || w > 4096 || h > 4096) return orig(sc, edx, pitch, l, t, r, b);
    DWORD bytes = w * h * bpp;
    RtShrStage& st = g_rtShr[g_rtNShr];
    if (st.cap < bytes) {
        if (st.mem) VirtualFree(st.mem, 0, MEM_RELEASE);
        st.mem = (BYTE*)VirtualAlloc(NULL, bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE); st.cap = st.mem ? bytes : 0;
        if (!st.mem) return orig(sc, edx, pitch, l, t, r, b);
    }
    st.sc = sc; st.surf = sc[0]; st.l = l; st.t = t; st.r = r; st.b = b; st.bpp = bpp;
    g_rtNShr++;
    *pitch = (int)(w * bpp);
    return st.mem;
}
static void __fastcall hk_rtShroudUnlock(DWORD* sc, void* edx) {
    for (int i = g_rtNShr - 1; i >= 0; --i) {
        if (g_rtShr[i].sc != sc) continue;
        RtShrStage st = g_rtShr[i];
        g_rtShr[i] = g_rtShr[g_rtNShr - 1]; g_rtShr[g_rtNShr - 1] = st;        // keep the buffer with its slot
        g_rtShr[g_rtNShr - 1].sc = NULL; g_rtNShr--;
        DWORD bytes = (st.r - st.l) * (st.b - st.t) * st.bpp;
        RtRec* rec = rtAlloc(9, bytes); rec->kind = 7; rec->op = 304;
        DWORD* A = rtArgs(rec); BYTE* P = rtPayload(rec); DWORD po = 0;
        A[0] = st.surf; A[1] = st.l; A[2] = st.t; A[3] = st.r; A[4] = st.b; A[5] = st.bpp;
        A[6] = rtBytes(P, &po, (DWORD)(ULONG_PTR)st.mem, bytes);
        A[7] = (DWORD)(ULONG_PTR)g_rtO_surf[13]; A[8] = (DWORD)(ULONG_PTR)g_rtO_surf[14];
        rtTouch(st.surf); rtCommit(rec, po); g_rtNShroud++;
        return;
    }
    ((tRtSurfUnlock)(ULONG_PTR)kSurfUnlock)(sc, edx);
}
static bool rtCallTo(DWORD site, DWORD target) {
    const BYTE* q = (const BYTE*)(ULONG_PTR)site;
    return q[0] == 0xE8 && site + 5 + *(const DWORD*)(q + 1) == target;
}
static void rtSetCall(DWORD site, void* hook) {
    BYTE* q = (BYTE*)(ULONG_PTR)site; DWORD op = 0;
    VirtualProtect(q, 5, PAGE_EXECUTE_READWRITE, &op);
    *(DWORD*)(q + 1) = (DWORD)(ULONG_PTR)hook - (site + 5);
    VirtualProtect(q, 5, op, &op);
    FlushInstructionCache(GetCurrentProcess(), q, 5);
}
static void rtInstallShroudHooks() {
    static const DWORD kSites[4][2] = { {0x0047308C, kSurfLockRect}, {0x004730C0, kSurfUnlock}, {0x00473EB3, kSurfLockRect}, {0x00473EE8, kSurfUnlock} };
    // the row loops between them: 16-bit (add ebx,ebx / memcpy) and 32-bit (shl ebx,2 / memcpy)
    static const BYTE kLoop16[] = {0x03,0xDB}, kLoop32[] = {0xC1,0xE3,0x02};
    __try {
        for (int i = 0; i < 4; ++i) if (!rtCallTo(kSites[i][0], kSites[i][1])) { logf("rt: shroud texture call sites differ - shroud updates stay synchronous."); return; }
        if (memcmp((void*)0x0047309B, kLoop16, 2) || memcmp((void*)0x00473EC2, kLoop32, 3)) { logf("rt: shroud row loops differ - shroud updates stay synchronous."); return; }
    } __except (EXCEPTION_EXECUTE_HANDLER) { return; }
    HANDLE fz[256]; int nf = 0;
    suspendOthers(fz, &nf, 256);
    rtSetCall(0x0047308C, (void*)&hk_rtShroudLock); rtSetCall(0x004730C0, (void*)&hk_rtShroudUnlock);
    rtSetCall(0x00473EB3, (void*)&hk_rtShroudLock); rtSetCall(0x00473EE8, (void*)&hk_rtShroudUnlock);
    resumeAll(fz, nf);
    logf("rt: shroud texture updates (0x47308C/0x473EB3) go through the queue.");
}
static void rtInstallPixelHooks() {
    static const BYTE kPre[]  = {0x83,0xEC,0x24,0x56,0x8B,0xF1,0x83,0x3E,0x00,0x0F,0x84};
    static const BYTE kDesc[] = {0x83,0xEC,0x20,0x33,0xC0,0x89,0x04,0x24};
    static const BYTE kBpp[]  = {0x8B,0x09,0x83,0xC1,0xEC,0x33,0xC0};
    __try {
        if (memcmp((void*)0x005165E0, kPre, sizeof(kPre)) || memcmp((void*)0x005166C0, kPre, sizeof(kPre)) ||
            memcmp((void*)0x00515FD0, kDesc, sizeof(kDesc)) || memcmp((void*)0x00515F10, kBpp, sizeof(kBpp))) {
            logf("rt: engine per-pixel surface functions differ - pixel writes stay synchronous."); return;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { return; }
    o_rtDrawPixel = (tRtPixelFn)makeTrampoline((BYTE*)0x005165E0, 6);
    o_rtSetAlpha  = (tRtPixelFn)makeTrampoline((BYTE*)0x005166C0, 6);
    if (!o_rtDrawPixel || !o_rtSetAlpha) return;
    HANDLE fz[256]; int nf = 0;
    suspendOthers(fz, &nf, 256);
    patchJmp((BYTE*)0x005165E0, (void*)&hk_rtDrawPixel, 6);
    patchJmp((BYTE*)0x005166C0, (void*)&hk_rtSetAlpha, 6);
    resumeAll(fz, nf);
    logf("rt: engine per-pixel surface writes (DrawPixel 0x5165E0, alpha 0x5166C0) go through the queue.");
}
static void rtInstallEngineHooks() { rtInstallPixelHooks(); rtInstallShroudHooks(); rtInstallTexMirrors(); }

// ---------------------------------------------------------------- staged write-only buffer locks
// DISCARD / NOOVERWRITE locks on vertex and index buffers (hundreds per frame: particles, UI, terrain) used
// to drain the queue. The game now writes into staging memory; at Unlock one record carries the bytes and
// the worker does Lock + copy + Unlock in queue order. Read or plain locks stay synchronous.
#define RT_ARENA_SIZE (64u << 20)
static BYTE* g_rtArena = NULL;
static DWORD g_rtArenaTop = 0;
// CPU mirrors for plain buffer locks: a lock without DISCARD / NOOVERWRITE / READONLY must show the buffer's current
// bytes, so it used to drain the queue. The first such lock of a buffer reads the whole buffer once (synchronously) into
// a mirror and keeps a reference to the buffer; later plain locks get staging memory filled from the mirror, and every
// staged unlock of the buffer (plain or NOOVERWRITE) writes the staged bytes into the mirror as it queues them. A
// DISCARD lock, any lock outside this path (another thread, a scoped D3DX call) or a Reset drops the mirror first.
struct RtBufMir { DWORD buf, len, cap, lastFrame; BYTE* mem; BYTE live, dead, isIB, pad; };
#define RT_BMIR 384
#define RT_BMIX 1024                                              // pointer -> mirror index (open addressing)
#define RT_BM_BYTES (320u << 20)                                  // mirror memory ceiling
static RtBufMir g_rtBM[RT_BMIR];
static short g_rtBMIx[RT_BMIX];                                   // slot + 1, 0 = empty
static DWORD g_rtBMBytes = 0, g_rtBMReapFrame = 0;
static volatile LONG g_rtNBMAdopt = 0, g_rtNBMLock = 0, g_rtNBMDrop = 0, g_rtNBMFail = 0, g_rtNBMEvict = 0;
static volatile LONG g_rtBufFallback[9];                          // 0 readonly, 1 no ptr, 2 stages full, 3 desc, 4 range, 5 arena, 6 no mirror, 7 other
static __forceinline DWORD rtBMHash(DWORD b) { return (b * 2654435761u) >> 22; }
static RtBufMir* rtBMFind(DWORD b) {
    DWORD h = rtBMHash(b);
    for (int i = 0; i < 16; ++i) {
        short e = g_rtBMIx[(h + i) & (RT_BMIX - 1)];
        if (!e) return NULL;
        RtBufMir& m = g_rtBM[e - 1];
        if (m.buf == b && m.live && !m.dead) return &m;           // a dead mirror of the same buffer may still sit earlier in the chain
    }
    return NULL;
}
static void rtBMIndexRebuild() {
    memset(g_rtBMIx, 0, sizeof(g_rtBMIx));
    for (int i = 0; i < RT_BMIR; ++i) {
        if (!g_rtBM[i].live) continue;
        DWORD h = rtBMHash(g_rtBM[i].buf);
        for (int k = 0; k < 16; ++k) { short& e = g_rtBMIx[(h + k) & (RT_BMIX - 1)]; if (!e) { e = (short)(i + 1); break; } }
    }
}
static LONG g_rtBMDead = 0;
static void rtBMKill(DWORD b) { RtBufMir* m = rtBMFind(b); if (m) { m->dead = 1; g_rtNBMDrop++; g_rtBMDead++; } }
static void rtBMKillAll() { for (int i = 0; i < RT_BMIR; ++i) if (g_rtBM[i].live && !g_rtBM[i].dead) { g_rtBM[i].dead = 1; g_rtNBMDrop++; g_rtBMDead++; } }
struct RtStage { DWORD buf, off, size, flags; BYTE* mem; RtBufMir* mir; };
#define RT_STG 256
static RtStage g_rtStage[RT_STG];
static int g_rtNStage = 0;
static bool rtBMPending(const RtBufMir* m) { for (int k = 0; k < g_rtNStage; ++k) if (g_rtStage[k].mir == m) return true; return false; }
static void rtBMRelease(RtBufMir& m) {                            // game thread: give the kept reference back through the queue
    m.live = 0; m.dead = 0;
    if (m.isIB) rt_ib_2((void*)(ULONG_PTR)m.buf); else rt_vb_2((void*)(ULONG_PTR)m.buf);
}
static void rtBMReap() {                                          // once a frame (or when mirrors died): release dead mirrors and ones idle for a minute
    if (g_rtBMReapFrame == (DWORD)g_mkFrames && !g_rtBMDead) return;
    g_rtBMReapFrame = (DWORD)g_mkFrames;
    bool changed = false; LONG left = 0;
    for (int i = 0; i < RT_BMIR; ++i) {
        RtBufMir& m = g_rtBM[i];
        if (!m.live || !(m.dead || (DWORD)(g_mkFrames - m.lastFrame) > 1800)) continue;
        if (rtBMPending(&m)) { if (m.dead) left++; continue; }
        rtBMRelease(m); changed = true;
    }
    g_rtBMDead = left;
    if (changed) rtBMIndexRebuild();
}
static int rtBMFreeSlot(DWORD need) {                             // a free slot with room for need bytes, evicting the least recently locked mirrors
    for (int round = 0; round < RT_BMIR; ++round) {
        int slot = -1;
        for (int i = 0; i < RT_BMIR; ++i) if (!g_rtBM[i].live) { slot = i; break; }
        DWORD have = slot >= 0 ? g_rtBM[slot].cap : 0;
        if (slot >= 0 && g_rtBMBytes - have + need <= RT_BM_BYTES) return slot;
        int lru = -1;
        for (int i = 0; i < RT_BMIR; ++i) if (g_rtBM[i].live && (lru < 0 || g_rtBM[i].lastFrame < g_rtBM[lru].lastFrame) && !rtBMPending(&g_rtBM[i])) lru = i;
        if (lru < 0) return -1;
        rtBMRelease(g_rtBM[lru]);
        if (slot >= 0) { g_rtBMBytes -= g_rtBM[slot].cap; VirtualFree(g_rtBM[slot].mem, 0, MEM_RELEASE); g_rtBM[slot].mem = NULL; g_rtBM[slot].cap = 0; }
        g_rtNBMEvict++;
        rtBMIndexRebuild();
    }
    return -1;
}
static RtBufMir* rtBMAdopt(void* self, void** O, bool isIB, DWORD len) {
    if (!len || len > (8u << 20)) return NULL;
    int slot = rtBMFreeSlot(len);
    if (slot < 0) return NULL;
    RtBufMir& m = g_rtBM[slot];
    if (m.cap < len) {
        if (m.mem) { VirtualFree(m.mem, 0, MEM_RELEASE); g_rtBMBytes -= m.cap; }
        m.mem = (BYTE*)VirtualAlloc(NULL, len, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE); m.cap = m.mem ? len : 0; g_rtBMBytes += m.cap;
    }
    if (!m.mem) return NULL;
    rtSyncNote(isIB ? 361 : 341, 0); g_rtCurOp = isIB ? 361 : 341;
    rtDrain(); rtEnterExec(); g_rtDirectScope++;
    bool ok = false; void* p = NULL;
    ((DWORD(__stdcall*)(void*))O[1])(self);                                                        // AddRef: kept while mirrored
    if ((LONG)((RtS5)O[11])(self, 0, 0, (DWORD)(ULONG_PTR)&p, 0x10) >= 0) {                        // READONLY, whole buffer
        if (p) { memcpy(m.mem, p, len); ok = true; }
        ((RtS1)O[12])(self);
    }
    if (!ok) ((DWORD(__stdcall*)(void*))O[2])(self);
    g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs); g_rtNSync++;
    if (!ok) { g_rtNBMFail++; return NULL; }
    m.buf = (DWORD)(ULONG_PTR)self; m.len = len; m.lastFrame = g_mkFrames; m.isIB = isIB ? 1 : 0; m.live = 1; m.dead = 0;
    { DWORD h = rtBMHash(m.buf); bool put = false;
      for (int k = 0; k < 16; ++k) { short& e = g_rtBMIx[(h + k) & (RT_BMIX - 1)]; if (!e) { e = (short)(slot + 1); put = true; break; } }
      if (!put) rtBMIndexRebuild(); }
    g_rtBMAny = 1; g_rtNBMAdopt++;
    return &m;
}
static DWORD rtBufLock(void* self, void** O, int op, DWORD off, DWORD size, DWORD ppData, DWORD flags, DWORD ra) {
    bool plain = !(flags & 0x3010);
    int why = 7;
    if (flags & 0x10) why = 0; else if (!ppData) why = 1; else if (g_rtNStage >= RT_STG) why = 2;
    if (g_rtArena && ppData && ((flags & 0x3000) || plain) && !(flags & 0x10) && g_rtNStage < RT_STG) {
        BYTE desc[32];
        why = 3;
        if ((LONG)((DWORD(__stdcall*)(void*, BYTE*))O[13])(self, desc) >= 0) {                  // GetDesc: immutable
            DWORD len = *(DWORD*)(desc + 16);
            DWORD n = size ? size : (len > off ? len - off : 0);
            why = 4;
            if (n && off <= len && n <= len - off && n <= RT_BUF_SIZE / 8) {
                DWORD b = (DWORD)(ULONG_PTR)self;
                RtBufMir* m = NULL;
                if (plain) {
                    if (g_rtBMAny) rtBMReap();
                    m = rtBMFind(b);
                    if (!m) m = rtBMAdopt(self, O, op != 341, len);
                    if (m && m->len != len) { m->dead = 1; g_rtNBMDrop++; g_rtBMDead++; m = NULL; }
                } else if (g_rtBMAny) {
                    if (flags & 0x2000) rtBMKill(b); else m = rtBMFind(b);
                }
                DWORD at = (g_rtArenaTop + 15) & ~15u;
                why = (plain && !m) ? 6 : 5;
                if ((!plain || m) && at + n <= RT_ARENA_SIZE) {
                    g_rtArenaTop = at + n;
                    RtStage& st = g_rtStage[g_rtNStage++];
                    st.buf = b; st.off = off; st.size = n; st.flags = flags; st.mem = g_rtArena + at; st.mir = m;
                    if (plain) { memcpy(st.mem, m->mem + off, n); m->lastFrame = g_mkFrames; g_rtNBMLock++; }    // what a plain lock shows
                    *(void**)(ULONG_PTR)ppData = st.mem;
                    g_rtNStaged++;
                    return 0;
                }
            }
        }
    }
    if (g_rtBMAny) rtBMKill((DWORD)(ULONG_PTR)self);
    g_rtNStageFallback++; g_rtBufFallback[why]++;
    rtSyncNote(op, ra); g_rtCurOp = op;
    rtDrain(); rtEnterExec(); g_rtDirectScope++;
    DWORD r = ((RtS5)O[11])(self, off, size, ppData, flags);
    g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs); g_rtNSync++; g_rtSyncHist[op]++;
    return r;
}
static DWORD rtBufUnlock(void* self, void** O, int op) {
    DWORD b = (DWORD)(ULONG_PTR)self;
    for (int i = g_rtNStage - 1; i >= 0; --i) {
        if (g_rtStage[i].buf != b) continue;
        RtStage st = g_rtStage[i];
        for (int k = i; k < g_rtNStage - 1; ++k) g_rtStage[k] = g_rtStage[k + 1];
        g_rtNStage--;
        if (st.mir && st.mir->live && !st.mir->dead && st.mir->buf == b && st.off + st.size <= st.mir->len) memcpy(st.mir->mem + st.off, st.mem, st.size);
        RtRec* r = rtAlloc(7, st.size); r->fn = O[11]; r->op = (WORD)op;
        DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0;
        A[0] = rtObj(r, 0, b); A[1] = st.off; A[2] = st.size; A[3] = st.flags; A[4] = (DWORD)(ULONG_PTR)O[12];
        A[5] = rtBytes(P, &po, (DWORD)(ULONG_PTR)st.mem, st.size); A[6] = 0;
        r->kind = 3;
        rtCommit(r, po);
        if (g_rtNStage == 0) g_rtArenaTop = 0;
        return 0;
    }
    RtRec* r = rtAlloc(1, 0); r->fn = O[12]; r->op = (WORD)op; rtArgs(r)[0] = b; rtCommit(r, 0);
    return 0;
}
static DWORD __stdcall rt_vb_11(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {
    if (g_rtBMAny) { DWORD t_ = __readfsdword(0x24); if (t_ != g_rtMainTid || !g_rtActive || g_rtDirectScope) rtBMKill((DWORD)(ULONG_PTR)self); }
    RT_PASSTHRU(vb, 11, RtS5, self, a0, a1, a2, a3); return rtBufLock(self, g_rtO_vb, 341, a0, a1, a2, a3, (DWORD)(ULONG_PTR)_ReturnAddress()); }
static DWORD __stdcall rt_vb_12(void* self)                                       { RT_PASSTHRU(vb, 12, RtS1, self); return rtBufUnlock(self, g_rtO_vb, 342); }
static DWORD __stdcall rt_ib_11(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {
    if (g_rtBMAny) { DWORD t_ = __readfsdword(0x24); if (t_ != g_rtMainTid || !g_rtActive || g_rtDirectScope) rtBMKill((DWORD)(ULONG_PTR)self); }
    RT_PASSTHRU(ib, 11, RtS5, self, a0, a1, a2, a3); return rtBufLock(self, g_rtO_ib, 361, a0, a1, a2, a3, (DWORD)(ULONG_PTR)_ReturnAddress()); }
static DWORD __stdcall rt_ib_12(void* self)                                       { RT_PASSTHRU(ib, 12, RtS1, self); return rtBufUnlock(self, g_rtO_ib, 362); }

// ---------------------------------------------------------------- exclusive scopes for D3DX global functions
// D3DX creation/load/filter functions touch the device and D3DX globals from inside: run them as one
// exclusive block (queue drained, worker parked, nested device calls direct).
static void* g_rtXO[16];
#define RT_SCOPE_OPEN()  DWORD tid_ = GetCurrentThreadId(); if (tid_ == g_mkTid) g_rtXDepth++; \
    bool main_ = (g_rtActive && tid_ == g_rtMainTid && !g_rtDirectScope); \
    bool foreign_ = (g_rtActive && tid_ != g_rtMainTid && tid_ != g_rtWorkerTid); \
    if (main_) { rtDrain(); rtEnterExec(); g_rtDirectScope++; g_rtNScope++; } else if (foreign_) EnterCriticalSection(&g_rtExecCs)
#define RT_SCOPE_CLOSE() if (main_) { g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs); } else if (foreign_) LeaveCriticalSection(&g_rtExecCs);     if (tid_ == g_mkTid) g_rtXDepth--
static volatile LONG g_rtXCalls[16]; static volatile LONG64 g_rtXTicks[16];              // per scoped D3DX function: calls on the game thread, time incl. the drain
#define RT_XW(I, N, ...) { LONG64 t0_ = qpcNow(); RT_SCOPE_OPEN(); DWORD r = ((DWORD(__stdcall*)(RT_XT##N))g_rtXO[I])(__VA_ARGS__); RT_SCOPE_CLOSE(); if (main_) { g_rtXCalls[I]++; g_rtXTicks[I] += qpcNow() - t0_; } return r; }
#define RT_XT4  DWORD, DWORD, DWORD, DWORD
#define RT_XT7  DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD
#define RT_XT8  DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD
#define RT_XT9  DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD
#define RT_XT10 DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD
#define RT_XT14 DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD
#define RT_XT15 DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD
#define RT_XT16 DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD
static DWORD __stdcall rtx0(DWORD a, DWORD b, DWORD c, DWORD d, DWORD e, DWORD f, DWORD g, DWORD h, DWORD i) RT_XW(0, 9, a, b, c, d, e, f, g, h, i)
static DWORD __stdcall rtx1(DWORD a, DWORD b, DWORD c, DWORD d, DWORD e, DWORD f, DWORD g, DWORD h) RT_XW(1, 8, a, b, c, d, e, f, g, h)
static DWORD __stdcall rtx2(DWORD a, DWORD b, DWORD c, DWORD d, DWORD e, DWORD f, DWORD g, DWORD h) RT_XW(2, 8, a, b, c, d, e, f, g, h)
static DWORD __stdcall rtx3(DWORD a, DWORD b, DWORD c, DWORD d, DWORD e, DWORD f, DWORD g, DWORD h, DWORD i, DWORD j, DWORD k, DWORD l, DWORD m, DWORD n, DWORD o) RT_XW(3, 15, a, b, c, d, e, f, g, h, i, j, k, l, m, n, o)
static DWORD __stdcall rtx4(DWORD a, DWORD b, DWORD c, DWORD d, DWORD e, DWORD f, DWORD g, DWORD h, DWORD i, DWORD j, DWORD k, DWORD l, DWORD m, DWORD n) RT_XW(4, 14, a, b, c, d, e, f, g, h, i, j, k, l, m, n)
static DWORD __stdcall rtx5(DWORD a, DWORD b, DWORD c, DWORD d, DWORD e, DWORD f, DWORD g, DWORD h, DWORD i) RT_XW(5, 9, a, b, c, d, e, f, g, h, i)
static DWORD __stdcall rtx6(DWORD a, DWORD b, DWORD c, DWORD d, DWORD e, DWORD f, DWORD g, DWORD h, DWORD i, DWORD j, DWORD k, DWORD l, DWORD m, DWORD n, DWORD o, DWORD p) RT_XW(6, 16, a, b, c, d, e, f, g, h, i, j, k, l, m, n, o, p)
static DWORD __stdcall rtx7(DWORD a, DWORD b, DWORD c, DWORD d, DWORD e, DWORD f, DWORD g, DWORD h, DWORD i) RT_XW(7, 9, a, b, c, d, e, f, g, h, i)
static DWORD __stdcall rtx8(DWORD a, DWORD b, DWORD c, DWORD d, DWORD e, DWORD f, DWORD g) RT_XW(8, 7, a, b, c, d, e, f, g)
static DWORD __stdcall rtx9(DWORD a, DWORD b, DWORD c, DWORD d, DWORD e, DWORD f, DWORD g, DWORD h, DWORD i) RT_XW(9, 9, a, b, c, d, e, f, g, h, i)
static DWORD __stdcall rtx10(DWORD a, DWORD b, DWORD c, DWORD d, DWORD e, DWORD f, DWORD g, DWORD h, DWORD i, DWORD j) RT_XW(10, 10, a, b, c, d, e, f, g, h, i, j)
static DWORD __stdcall rtx11(DWORD a, DWORD b, DWORD c, DWORD d, DWORD e, DWORD f, DWORD g, DWORD h) RT_XW(11, 8, a, b, c, d, e, f, g, h)
// D3DXFilterTexture(texture, palette, source level, filter) rebuilds the mip levels below the source level from it. The
// terrain atlas code calls it after every atlas update; as an exclusive scope it made the game thread wait for the
// whole queue right after the mirror had spared it that wait. For a texture whose level 0 is mirrored (so nothing
// reads it back on the game thread) the call is queued instead: it runs on the worker after the queued row upload,
// which is the order it always ran in. The filter reads level 0 and writes the levels below - the mirror stays true.
static bool rtTMIsMirroredTex(DWORD tex);
static DWORD __stdcall rtAsyncFilterRun(DWORD a, DWORD b, DWORD c, DWORD d) {
    g_rtInAsyncFilter = 1;
    DWORD r = ((DWORD(__stdcall*)(DWORD, DWORD, DWORD, DWORD))g_rtXO[12])(a, b, c, d);
    g_rtInAsyncFilter = 0;
    return r;
}
static DWORD __stdcall rtx12(DWORD a, DWORD b, DWORD c, DWORD d) {
    if (g_rtTMAtlasOn && g_rtTMAny && a && !b && (c == 0 || c == 0xFFFFFFFFu) && g_rtActive && !g_rtDirectScope && GetCurrentThreadId() == g_rtMainTid && rtTMIsMirroredTex(a)) {
        RtRec* r = rtAlloc(4, 0); r->fn = (void*)&rtAsyncFilterRun; r->op = 509;
        DWORD* A = rtArgs(r);
        A[0] = rtObj(r, 0, a); A[1] = b; A[2] = c; A[3] = d;
        rtCommit(r, 0); g_rtNAsyncFilter++;
        return 0;
    }
    RT_XW(12, 4, a, b, c, d)
}
static DWORD __stdcall rtx13(DWORD a, DWORD b, DWORD c, DWORD d, DWORD e, DWORD f, DWORD g) RT_XW(13, 7, a, b, c, d, e, f, g)
struct RtXDef { const char* name; void* hook; };
static const RtXDef kRtX[14] = {
    {"D3DXCreateEffect", (void*)&rtx0}, {"D3DXCreateEffectFromFileA", (void*)&rtx1}, {"D3DXCreateTexture", (void*)&rtx2},
    {"D3DXCreateTextureFromFileInMemoryEx", (void*)&rtx3}, {"D3DXCreateCubeTextureFromFileInMemoryEx", (void*)&rtx4},
    {"D3DXCreateVolumeTexture", (void*)&rtx5}, {"D3DXCreateVolumeTextureFromFileInMemoryEx", (void*)&rtx6},
    {"D3DXLoadVolumeFromFileInMemory", (void*)&rtx7}, {"D3DXCheckTextureRequirements", (void*)&rtx8},
    {"D3DXLoadSurfaceFromFileInMemory", (void*)&rtx9}, {"D3DXLoadSurfaceFromMemory", (void*)&rtx10},
    {"D3DXLoadSurfaceFromSurface", (void*)&rtx11}, {"D3DXFilterTexture", (void*)&rtx12}, {"D3DXAssembleShader", (void*)&rtx13},
};

// ---------------------------------------------------------------- installation
static bool rtIsCode(DWORD a) {
    MEMORY_BASIC_INFORMATION mbi;
    if (!a || !VirtualQuery((void*)(ULONG_PTR)a, &mbi, sizeof(mbi)) || mbi.State != MEM_COMMIT) return false;
    return (mbi.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)) != 0;
}
static void rtOwner(DWORD a, char* out, int n) {
    HMODULE h = NULL; char path[MAX_PATH];
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)(ULONG_PTR)a, &h) && GetModuleFileNameA(h, path, MAX_PATH)) {
        const char* b = strrchr(path, 0x5C); lstrcpynA(out, b ? b + 1 : path, n);
    } else lstrcpynA(out, "<no module>", n);
}
static bool rtHookTable(void** vt, int n, void** orig, void* const* hooks, const char* what, DWORD lo, DWORD hi) {
    if (vt[0] == hooks[0]) return true;                  // already ours
    (void)lo; (void)hi;
    for (int i = 0; i < n; ++i) { DWORD f = (DWORD)(ULONG_PTR)vt[i];
        if (!rtIsCode(f)) { logf("rt: %s vtable %08X slot %d -> %08X is not executable code - not hooked.", what, (DWORD)(ULONG_PTR)vt, i, f); return false; } }
    { char own[64]; rtOwner((DWORD)(ULONG_PTR)vt[0], own, sizeof(own)); logf("rt: %s vtable %08X implemented in %s.", what, (DWORD)(ULONG_PTR)vt, own); }
    for (int i = 0; i < n; ++i) orig[i] = vt[i];         // originals first, then the table
    DWORD op = 0;
    if (!VirtualProtect(vt, n * sizeof(void*), PAGE_READWRITE, &op)) { logf("rt: VirtualProtect failed on %s vtable.", what); return false; }
    for (int i = 0; i < n; ++i) vt[i] = hooks[i];
    VirtualProtect(vt, n * sizeof(void*), op, &op);
    return true;
}
static bool rtRehookDevice(void* dev) {
    void** vt = *(void***)dev;
    for (int i = 0; i < 119; ++i) {
        if (!rtIsCode((DWORD)(ULONG_PTR)vt[i])) return false;
        if (vt[i] == g_rtH_dev[i] && !g_rtO_dev[i]) return false;
    }
    DWORD protect = 0;
    if (!VirtualProtect(vt, 119 * sizeof(void*), PAGE_READWRITE, &protect)) return false;
    unsigned repaired = 0;
    for (int i = 0; i < 119; ++i) {
        if (vt[i] == g_rtH_dev[i]) continue;
        g_rtO_dev[i] = vt[i];
        vt[i] = g_rtH_dev[i];
        ++repaired;
    }
    DWORD ignored = 0;
    bool restored = VirtualProtect(vt, 119 * sizeof(void*), protect, &ignored) != FALSE;
    if (repaired) logf("sage: restored %u device vtable slots after Reset.", repaired);
    return restored;
}
static void rtModuleRange(const char* name, DWORD* lo, DWORD* hi) {
    HMODULE h = GetModuleHandleA(name); *lo = *hi = 0;
    if (!h) return;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)((BYTE*)h + ((IMAGE_DOS_HEADER*)h)->e_lfanew);
    *lo = (DWORD)(ULONG_PTR)h; *hi = *lo + nt->OptionalHeader.SizeOfImage;
}
// Keep the worker off the game thread's physical core: on an SMT CPU two busy threads on sibling logical
// processors each run far slower than on separate cores. Soft hint (ideal processor), never a hard affinity.
static DWORD g_rtIdealMain = 0xFFFFFFFF, g_rtIdealWorker = 0xFFFFFFFF;
static void rtPlaceWorker(HANDLE worker) {
#ifdef AOTR_V4_IDEAL
    DWORD cur = GetCurrentProcessorNumber();
    DWORD len = 0;
    GetLogicalProcessorInformationEx(RelationProcessorCore, NULL, &len);
    if (!len || len > (1u << 20)) return;
    BYTE* buf = (BYTE*)VirtualAlloc(NULL, len, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!buf) return;
    KAFFINITY mainCore = 0, all = 0;
    if (GetLogicalProcessorInformationEx(RelationProcessorCore, (PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX)buf, &len)) {
        for (DWORD off = 0; off < len; ) {
            PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX e = (PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX)(buf + off);
            if (e->Relationship == RelationProcessorCore && e->Processor.GroupMask[0].Group == 0) {
                KAFFINITY m = e->Processor.GroupMask[0].Mask; all |= m;
                if (cur < sizeof(KAFFINITY) * 8 && (m >> cur) & 1) mainCore = m;
            }
            off += e->Size;
        }
    }
    VirtualFree(buf, 0, MEM_RELEASE);
    if (!mainCore) return;
    DWORD_PTR procMask = 0, sysMask = 0; GetProcessAffinityMask(GetCurrentProcess(), &procMask, &sysMask);
    KAFFINITY cand = all & ~mainCore & (KAFFINITY)procMask;
    if (!cand) return;
    DWORD pick = 0xFFFFFFFF;
    for (DWORD i = 0; i < sizeof(KAFFINITY) * 8; ++i) if ((cand >> i) & 1) { pick = i; if (i > cur) break; }   // nearest core above the game thread's
    if (pick == 0xFFFFFFFF) return;
    SetThreadIdealProcessor(GetCurrentThread(), cur);
    SetThreadIdealProcessor(worker, pick);
    g_rtIdealMain = cur; g_rtIdealWorker = pick;
#else
    (void)worker;
#endif
}
static void rtInitBody();
static void rtInit() {                                  // any thread; hooks the ID3DXEffect vtable and D3DX imports (once)
    EnterCriticalSection(&g_rtInitCs);
    if (!g_rtInitDone) { g_rtInitDone = 1; rtInitBody(); }
    LeaveCriticalSection(&g_rtInitCs);
}
static void rtInitBody() {
    char optIn[8] = {};
    if (GetEnvironmentVariableA("PYSAGE_EXPERIMENTAL_RT", optIn, sizeof(optIn)) != 1 || optIn[0] != '1') {
        g_rtTried = true;
        logf("sage: parallel renderer OFF; native D3D9/shim frame-hash validation is unresolved. "
             "PYSAGE_EXPERIMENTAL_RT=1 enables developer testing only.");
        return;
    }
    char env[8]; env[0] = 0;
    if (GetEnvironmentVariableA("AOTR_RT", env, sizeof(env)) && env[0] == '0') { g_rtTried = true; logf("rt: disabled by AOTR_RT=0."); return; }
    rtOpNoTouchInit();
    g_rtDs.on = 1;
    if (GetEnvironmentVariableA("AOTR_FXDEDUPE", env, sizeof(env)) && env[0] == (char)48) { g_rtFxDedupeOn = 0; logf("rt: effect parameter de-dupe off (AOTR_FXDEDUPE=0)."); }
    if (!g_rtFxBlk) g_rtFxBlk = (RtFxBlk*)VirtualAlloc(NULL, RT_PBN * sizeof(RtFxBlk), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!g_rtFxV) { g_rtFxV = (RtFxVal*)VirtualAlloc(NULL, (SIZE_T)RT_FXV * sizeof(RtFxVal), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE); if (!g_rtFxV) g_rtFxDedupeOn = 0; }
    if (GetEnvironmentVariableA("AOTR_DEVDEDUPE", env, sizeof(env)) && env[0] == '0') { g_rtDs.on = 0; logf("rt: vertex-input de-dupe off (AOTR_DEVDEDUPE=0)."); }
    if (GetEnvironmentVariableA("AOTR_ATLASMIRROR", env, sizeof(env)) && env[0] == '0') { g_rtTMAtlasOn = 0; logf("rt: terrain atlas mirror off (AOTR_ATLASMIRROR=0)."); }
    if (GetEnvironmentVariableA("AOTR_USSNAP", env, sizeof(env)) && env[0] == '0') { g_rtUSOn = 0; logf("rt: UpdateSurface snapshots off (AOTR_USSNAP=0)."); }
    if (GetEnvironmentVariableA("AOTR_FXBATCH", env, sizeof(env)) && env[0] == '0') { g_rtFxBatchOn = 0; logf("rt: effect parameter batching off (AOTR_FXBATCH=0)."); }
    rtModuleRange("d3dx9_27.dll", &g_dxLo, &g_dxHi);
    if (!g_dxLo) { g_rtTried = true; logf("rt: d3dx9_27 not loaded - render thread OFF."); return; }
    void** fvt = (void**)(ULONG_PTR)(g_dxLo + 0x13EB0);
    __try {
        if ((DWORD)(ULONG_PTR)fvt[63] != g_dxLo + 0x1062F5 || (DWORD)(ULONG_PTR)fvt[64] != g_dxLo + 0x108148 ||
            (DWORD)(ULONG_PTR)fvt[65] != g_dxLo + 0x107FD6 || (DWORD)(ULONG_PTR)fvt[75] != g_dxLo + 0x10863A ||
            (DWORD)(ULONG_PTR)fvt[78] != g_dxLo + 0x103D7B) {
            g_rtTried = true; logf("rt: ID3DXEffect vtable does not match this d3dx9_27 build - render thread OFF."); return;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { g_rtTried = true; logf("rt: effect vtable probe faulted - render thread OFF."); return; }
    g_rtWake = CreateEventA(NULL, FALSE, FALSE, NULL); g_rtDrained = CreateEventA(NULL, FALSE, FALSE, NULL);
    g_rtPresented = CreateEventA(NULL, FALSE, FALSE, NULL); g_rtReady = CreateEventA(NULL, TRUE, FALSE, NULL);
    g_rtBuf = (BYTE*)VirtualAlloc(NULL, RT_BUF_SIZE, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    g_rtQ = (RtQ*)VirtualAlloc(NULL, RT_QC * sizeof(RtQ), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    g_rtQStr = (char*)VirtualAlloc(NULL, RT_QSTR, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    g_rtPBReal = (DWORD*)VirtualAlloc(NULL, RT_PBN * sizeof(DWORD), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    g_rtPBLive = (BYTE*)VirtualAlloc(NULL, RT_PBN, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    g_rtArena = (BYTE*)VirtualAlloc(NULL, RT_ARENA_SIZE, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (g_rtBuf) memset(g_rtBuf, 0, RT_BUF_SIZE);
    if (g_rtArena) memset(g_rtArena, 0, 8u << 20);
    if (!g_rtFxBlk || !g_rtBuf || !g_rtQ || !g_rtQStr || !g_rtPBReal || !g_rtPBLive || !g_rtArena || !g_rtWake || !g_rtDrained || !g_rtPresented || !g_rtReady) { g_rtTried = true; logf("rt: allocation failed - render thread OFF."); return; }
    if (!rtHookTable(fvt, 79, g_rtO_fx, g_rtH_fx, "ID3DXEffect", g_dxLo, g_dxHi)) { g_rtTried = true; return; }
    // D3DX global functions imported by the game module that touch the device
    HMODULE hGame = GetModuleHandleA("game.dat"); if (!hGame) hGame = GetModuleHandleA(NULL);
    int nx = 0;
    for (int i = 0; i < 14; ++i) {
        FARPROC* slot = iatSlot((BYTE*)hGame, "d3dx9_27.dll", kRtX[i].name);
        if (!slot) continue;
        g_rtXO[i] = (void*)*slot;
        if (hookSlot(slot, kRtX[i].hook, NULL)) ++nx;
    }
    CreateThread(NULL, 0, rtKeyThread, NULL, 0, NULL);
    logf("rt: armed - ID3DXEffect vtable hooked (79 slots), %d D3DX device functions scoped; starts at the first effect call on the render thread. Scroll Lock toggles it live.", nx);
}
static void rtInstall(void* fx) {                       // game render thread, from inside an effect call
    g_rtTried = true;
    __try {
        rtModuleRange("d3d9.dll", &g_d3d9Lo2, &g_d3d9Hi2);
        if (!g_d3d9Lo2) { logf("rt: d3d9.dll not loaded - render thread OFF."); return; }
        void* dev = NULL;
        ((DWORD(__stdcall*)(void*, void**))g_rtO_fx[68])(fx, &dev);            // ID3DXEffect::GetDevice
        if (!dev) { logf("rt: effect has no device - render thread OFF."); return; }
        void** dvt = *(void***)dev;
        ((DWORD(__stdcall*)(void*))dvt[2])(dev); // Drop GetDevice's temporary reference.
        for (int i = 0; i < 119; ++i) { DWORD f = (DWORD)(ULONG_PTR)dvt[i];
            if (!rtIsCode(f)) { logf("rt: device vtable slot %d -> %08X is not executable code - render thread OFF.", i, f); return; } }
        { char o0[64], o17[64], o82[64]; rtOwner((DWORD)(ULONG_PTR)dvt[0], o0, 64); rtOwner((DWORD)(ULONG_PTR)dvt[17], o17, 64); rtOwner((DWORD)(ULONG_PTR)dvt[82], o82, 64);
          logf("rt: device vtable %p: QueryInterface in %s, Present in %s, DrawIndexedPrimitive in %s.", dvt, o0, o17, o82); }
        for (int i = 0; i < 119; ++i) g_rtO_dev[i] = dvt[i];
        // one throwaway object of every class to reach its vtable (created with the original methods)
        typedef DWORD (__stdcall* C8)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD);
        typedef DWORD (__stdcall* C7)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD);
        typedef DWORD (__stdcall* C9)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD);
        typedef DWORD (__stdcall* C6)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD);
        typedef DWORD (__stdcall* C2)(void*, DWORD, DWORD);
        void* tex = 0, *surf = 0, *cube = 0, *vtex = 0, *vol = 0, *vb = 0, *ib = 0, *sb = 0, *q = 0, *sc = 0;
        ((C8)g_rtO_dev[23])(dev, 1, 1, 1, 0, 21, 1, (DWORD)(ULONG_PTR)&tex, 0);          // CreateTexture A8R8G8B8 MANAGED
        if (tex) ((C2)(*(void***)tex)[18])(tex, 0, (DWORD)(ULONG_PTR)&surf);            // GetSurfaceLevel
        ((C7)g_rtO_dev[25])(dev, 1, 1, 0, 21, 1, (DWORD)(ULONG_PTR)&cube, 0);            // CreateCubeTexture
        ((C9)g_rtO_dev[24])(dev, 1, 1, 1, 1, 0, 21, 1, (DWORD)(ULONG_PTR)&vtex, 0);      // CreateVolumeTexture
        if (vtex) ((C2)(*(void***)vtex)[18])(vtex, 0, (DWORD)(ULONG_PTR)&vol);          // GetVolumeLevel
        ((C6)g_rtO_dev[26])(dev, 16, 0, 0, 1, (DWORD)(ULONG_PTR)&vb, 0);                 // CreateVertexBuffer
        ((C6)g_rtO_dev[27])(dev, 16, 0, 101, 1, (DWORD)(ULONG_PTR)&ib, 0);               // CreateIndexBuffer INDEX16
        ((C2)g_rtO_dev[59])(dev, 1, (DWORD)(ULONG_PTR)&sb);                              // CreateStateBlock ALL
        ((C2)g_rtO_dev[118])(dev, 8, (DWORD)(ULONG_PTR)&q);                              // CreateQuery EVENT
        if (!q) ((C2)g_rtO_dev[118])(dev, 9, (DWORD)(ULONG_PTR)&q);                     // or OCCLUSION
        ((C2)g_rtO_dev[14])(dev, 0, (DWORD)(ULONG_PTR)&sc);                              // GetSwapChain
        void* vsh = 0, *psh = 0, *decl = 0;
        { struct VE { WORD s, o; BYTE t, m, u, ui; } el[2] = { {0, 0, 2, 0, 0, 0}, {0xFF, 0, 17, 0, 0, 0} };
          ((C2)g_rtO_dev[86])(dev, (DWORD)(ULONG_PTR)&el, (DWORD)(ULONG_PTR)&decl); }                // CreateVertexDeclaration
        { typedef HRESULT (WINAPI* AsmF)(const char*, UINT, void*, void*, DWORD, void**, void**);
          HMODULE hx9 = GetModuleHandleA("d3dx9_27.dll"); AsmF asmf = hx9 ? (AsmF)GetProcAddress(hx9, "D3DXAssembleShader") : NULL;
          static const char kVs[] = "vs.1.1\ndcl_position v0\nmov oPos, v0\n";
          static const char kPs[] = "ps.1.1\ndef c0, 1, 1, 1, 1\nmov r0, c0\n";
          void* b = NULL;
          if (asmf && asmf(kVs, sizeof(kVs) - 1, NULL, NULL, 0, &b, NULL) >= 0 && b) {
              ((C2)g_rtO_dev[91])(dev, (DWORD)(ULONG_PTR)((void*(WINAPI*)(void*))(*(void***)b)[3])(b), (DWORD)(ULONG_PTR)&vsh);   // CreateVertexShader
              ((DWORD(__stdcall*)(void*))(*(void***)b)[2])(b); b = NULL; }
          if (asmf && asmf(kPs, sizeof(kPs) - 1, NULL, NULL, 0, &b, NULL) >= 0 && b) {
              ((C2)g_rtO_dev[106])(dev, (DWORD)(ULONG_PTR)((void*(WINAPI*)(void*))(*(void***)b)[3])(b), (DWORD)(ULONG_PTR)&psh);  // CreatePixelShader
              ((DWORD(__stdcall*)(void*))(*(void***)b)[2])(b); } }
        if (!tex || !surf || !vb || !ib || !sb || !sc) {
            logf("rt: could not create probe objects (tex=%p surf=%p vb=%p ib=%p sb=%p sc=%p) - render thread OFF.", tex, surf, vb, ib, sb, sc);
            return;
        }
        g_rtX87 = _control87(0, 0); g_rtMxcsr = _mm_getcsr();                      // capture on the game thread
        HANDLE th = CreateThread(NULL, 0, rtWorker, NULL, 0, NULL);
        if (!th) { logf("rt: worker thread creation failed - render thread OFF."); return; }
        SetThreadPriority(th, THREAD_PRIORITY_ABOVE_NORMAL);
        rtPlaceWorker(th);
        DWORD ready = WaitForSingleObject(g_rtReady, 5000);
        CloseHandle(th);
        if (ready != WAIT_OBJECT_0) { logf("sage: render worker not ready - OFF."); return; }
        DWORD lo = g_d3d9Lo2, hi = g_d3d9Hi2;
        bool ok = true;
        ok = ok && rtHookTable(*(void***)tex,  22, g_rtO_tex,  g_rtH_tex,  "Texture",       lo, hi);
        ok = ok && rtHookTable(*(void***)surf, 17, g_rtO_surf, g_rtH_surf, "Surface",       lo, hi);
        ok = ok && rtHookTable(*(void***)vb,   14, g_rtO_vb,   g_rtH_vb,   "VertexBuffer",  lo, hi);
        ok = ok && rtHookTable(*(void***)ib,   14, g_rtO_ib,   g_rtH_ib,   "IndexBuffer",   lo, hi);
        ok = ok && rtHookTable(*(void***)sb,    6, g_rtO_sb,   g_rtH_sb,   "StateBlock",    lo, hi);
        ok = ok && rtHookTable(*(void***)sc,   10, g_rtO_sc,   g_rtH_sc,   "SwapChain",     lo, hi);
        if (ok && cube) ok = rtHookTable(*(void***)cube, 22, g_rtO_cube, g_rtH_cube, "CubeTexture",   lo, hi);
        if (ok && vtex) ok = rtHookTable(*(void***)vtex, 22, g_rtO_vtex, g_rtH_vtex, "VolumeTexture", lo, hi);
        if (ok && vol)  ok = rtHookTable(*(void***)vol,  11, g_rtO_vol,  g_rtH_vol,  "Volume",        lo, hi);
        if (ok && q)    ok = rtHookTable(*(void***)q,     8, g_rtO_q,    g_rtH_q,    "Query",         lo, hi);
        bool refsHooked = false;
        if (ok && vsh && psh && decl) {
            refsHooked = rtHookTable(*(void***)vsh, 5, g_rtO_vs, g_rtH_vs, "VertexShader", lo, hi)
                      && rtHookTable(*(void***)psh, 5, g_rtO_ps, g_rtH_ps, "PixelShader", lo, hi)
                      && rtHookTable(*(void***)decl, 5, g_rtO_decl, g_rtH_decl, "VertexDeclaration", lo, hi);
        }
        g_rtObjRefs = !refsHooked;                        // every bindable class now releases through the queue
        // release the probes (hooks are still in pass-through: the render thread is not active yet)
        void* probes[13] = { decl, psh, vsh, q, sc, sb, ib, vb, vol, vtex, cube, surf, tex };
        for (int i = 0; i < 13; ++i) if (probes[i]) ((DWORD(__stdcall*)(void*))(*(void***)probes[i])[2])(probes[i]);
        // Native D3D9 can restore its device table when the probe state block is released.
        dvt = *(void***)dev;
        if (ok) ok = rtHookTable(dvt, 119, g_rtO_dev, g_rtH_dev, "Device", lo, hi);
        if (!ok) { logf("rt: a vtable could not be hooked - render thread stays OFF (hooks pass through)."); return; }
        g_rtMainTid = GetCurrentThreadId();
        InterlockedExchange(&g_rtInstalled, 1);
        InterlockedExchange(&g_rtActive, g_rtWantOn ? 1 : 0);
        logf("rt: RENDER THREAD LIVE - device %p, game thread %u, worker thread %u. All D3D9 and D3DX effect work now runs on the worker (per-call object refs %s).",
             dev, g_rtMainTid, g_rtWorkerTid, g_rtObjRefs ? "ON (shader/declaration classes not hooked)" : "off");
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        logf("rt: install faulted (0x%08lX) - render thread OFF (hooks pass through).", (unsigned long)GetExceptionCode());
    }
}

// ---------------------------------------------------------------- live A/B switch
static DWORD WINAPI rtKeyThread(LPVOID) {
    bool down = false;
    for (;;) {
        Sleep(50);
        bool now = (GetAsyncKeyState(VK_SCROLL) & 0x8000) != 0;
        if (now && !down && g_rtInstalled) {
            LONG v = InterlockedExchange(&g_rtWantOn, g_rtWantOn ? 0 : 1);
            logf("rt: Scroll Lock pressed - render thread requested %s (applies at the next frame).", v ? "OFF" : "ON");
        }
        down = now;
        { static bool pdown = false;
          bool p = (GetAsyncKeyState(VK_PAUSE) & 0x8000) != 0;
          if (p && !pdown && g_lsInstalled) {
              LONG v = InterlockedExchange(&g_lsWant, g_lsWant ? 0 : 1);
              InterlockedIncrement(&g_lsToggles);
              logf("logicspread: Pause pressed - %s requested (applies at the next logic step).", v ? "engine schedule" : "spreading");
          }
          pdown = p; }
    }
    return 0;
}

// ---------------------------------------------------------------- reporting (every 5 s)
static DWORD WINAPI rtReport(LPVOID) {
    LONG lastFrames = 0; LONG64 lastPeriod = 0;
    LONG lAsync = 0, lSync = 0, lRel = 0, lForeign = 0, lPresent = 0, lScope = 0;
    LONG64 lDrain = 0, lBusy = 0, lBytes = 0, lPWait = 0;
    static LONG lHist[512];
    ULONG64 lastCpu = 0;
    for (;;) {
        Sleep(5000);
        ULONG64 pc = 0; { FILETIME c, e, k, u; if (GetProcessTimes(GetCurrentProcess(), &c, &e, &k, &u)) pc = (((ULONG64)k.dwHighDateTime << 32) | k.dwLowDateTime) + (((ULONG64)u.dwHighDateTime << 32) | u.dwLowDateTime); }
        int cpu = lastCpu ? (int)((pc - lastCpu) / 10000 / 50) : 0; lastCpu = pc;
        LONG fr = g_mkFrames; LONG dF = fr - lastFrames; lastFrames = fr;
        LONG64 per = rd64(&g_mkPeriod); LONG64 dP = per - lastPeriod; lastPeriod = per;
        static LONG64 lSt[3];
        LONG64 sh = 0, vw = 0, ui = 0;
        for (int p = 0; p < 3; ++p) { LONG64 I = rd64(&g_stTicks[p]); LONG64 d = I - lSt[p]; lSt[p] = I;
            if (p == 0) sh = d; else if (p == 1) vw = d; else ui = d; }
        LONG a = g_rtNAsync, s = g_rtNSync, rl = g_rtNRelease, fo = g_rtNForeign, pr = g_rtNPresent, sc = g_rtNScope;
        LONG64 dr = rd64(&g_rtDrainTicks), bu = rd64(&g_rtBusyTicks), by = rd64(&g_rtBytes), pw = rd64(&g_rtPresentWaitTicks);
        LONG f = dF > 0 ? dF : 1;
        char m1[16], m2[16], m3[16], m4[16], m5[16], m6[16], m7[16], m8[16], q1[16], q2[16], q3[16], q4[16], mb[16];
        char top[400]; int tp = 0; top[0] = 0;
        LONG d[512]; for (int i = 0; i < 512; ++i) { LONG v = g_rtSyncHist[i]; d[i] = v - lHist[i]; lHist[i] = v; }
        static LONG64 lOpT[512]; LONG64 dOpT[512]; for (int i = 0; i < 512; ++i) { LONG64 v = rd64(&g_rtDrainOpTicks[i]); dOpT[i] = v - lOpT[i]; lOpT[i] = v; }
        for (int k = 0; k < 8; ++k) { int bi = -1; LONG bc = 0; for (int i = 0; i < 512; ++i) if (d[i] > bc) { bc = d[i]; bi = i; }
            if (bi < 0 || tp > 330) break; char per1[16], dm[16]; tp += wsprintfA(top + tp, " %s x%s (%sms)", rtOpName(bi), perStr(bc, f, per1), msStr(dOpT[bi], f, dm)); d[bi] = 0; }
        static LONG lQH = 0, lQM = 0, lStg = 0, lSf = 0, lLk = 0, lDL = 0, lMir = 0; LONG qh = g_rtQHit, qm = g_rtQMiss, st = g_rtNStaged, sf = g_rtNStageFallback;
        LONG lk = g_rtNLocked, dl = g_rtNDirectLock, mir = g_rtNMirror;
        static LONG lPix = 0, lPbp = 0; LONG pix = g_rtNPixel, pbp = g_rtNPBProxy; char c7[16], c8[16];
        char c1[16], c2[16], c3[16], c4[16], c5[16], c6[16];
        logf("rt: %s%s cpu=%d%% frames=%d ms/f=%s | shadow %s views %s ui %s ms/f | queued/f %s sync/f %s release/f %s scope/f %s foreign=%d | drain %s present-wait %s worker-busy %s ms/f | %s MB/f | query-cache hit/f %s miss/f %s | staged locks/f %s | direct locks/f %s locked calls/f %s mirror/f %s pixel writes/f %s param blocks/f %s | sync top:%s",
             g_rtActive ? "LIVE" : "off", g_rtToggles ? "*" : "", cpu, dF, msStr(dP, f, m1), msStr(sh, f, m2), msStr(vw, f, m3), msStr(ui, f, m4),
             perStr(a - lAsync, f, q1), perStr(s - lSync, f, q2), perStr(rl - lRel, f, q3), perStr(sc - lScope, f, q4), fo - lForeign,
             msStr(dr - lDrain, f, m5), msStr(pw - lPWait, f, m6), msStr(bu - lBusy, f, m7), perStr((by - lBytes) / 104857, f * 10, mb), perStr(qh - lQH, f, c1), perStr(qm - lQM, f, c2), perStr(st - lStg, f, c3),
             perStr(dl - lDL, f, c4), perStr(lk - lLk, f, c5), perStr(mir - lMir, f, c6), perStr(pix - lPix, f, c7), perStr(pbp - lPbp, f, c8), top);
        lPix = pix; lPbp = pbp;
        if (dF > 0) {                                          // where the frame goes: logic by sub-frame, client outside the stages, animation
            static LONG64 lPhT[PH_N]; LONG64 dPh[PH_N];
            for (int p = 0; p < PH_N; ++p) { LONG64 v = rd64(&g_phTicks[p]); dPh[p] = v - lPhT[p]; lPhT[p] = v; }
            char lg[420]; int lp = 0; lg[0] = 0;
            static LONG lLgN[8]; static LONG64 lLgT[8];
            for (int k = 0; k < 8; ++k) {
                LONG cn = g_lgN[k] - lLgN[k]; LONG64 ct = rd64(&g_lgT[k]) - lLgT[k]; lLgN[k] += cn; lLgT[k] += ct;
                LONG64 mx = g_lgMax[k]; g_lgMax[k] = 0;
                if (cn <= 0) continue;
                char a1[16], a2[16]; lp += wsprintfA(lg + lp, " n%d x%d avg %s max %s", k, (int)cn, msStr(ct, cn, a1), msStr(mx, 1, a2));
            }
            char fb[300]; int fp2 = 0; fb[0] = 0;
            static LONG lFrN[8]; static LONG64 lFrT[8];
            for (int k = 0; k < 8; ++k) {
                LONG cn = g_frByN[k] - lFrN[k]; LONG64 ct = rd64(&g_frTByN[k]) - lFrT[k]; lFrN[k] += cn; lFrT[k] += ct;
                if (cn <= 0) continue;
                char a1[16]; fp2 += wsprintfA(fb + fp2, " n%d %s", k, msStr(ct, cn, a1));
            }
            static LONG lFh[9]; LONG fh[9]; for (int k = 0; k < 9; ++k) { LONG v = g_frHist[k]; fh[k] = v - lFh[k]; lFh[k] = v; }
            LONG64 fmx = g_frMax; g_frMax = 0;
            char an[400]; int ap = 0; an[0] = 0;
            static const char* const kAnName[AN_N] = { "progress", "hlod-update", "tree-update" };
            static LONG lAnN[AN_N][PH_N]; static LONG64 lAnT[AN_N][PH_N];
            for (int a = 0; a < AN_N; ++a) {
                ap += wsprintfA(an + ap, " %s", kAnName[a]);
                for (int p = 0; p < PH_N; ++p) {
                    LONG cn = g_anN[a][p] - lAnN[a][p]; LONG64 ct = rd64(&g_anT[a][p]) - lAnT[a][p]; lAnN[a][p] += cn; lAnT[a][p] += ct;
                    if (cn <= 0) continue;
                    LONG64 q = g_tscPerQpc > 0 ? (LONG64)((double)ct / g_tscPerQpc) : 0;
                    char a1[16], a2[16]; ap += wsprintfA(an + ap, " %s:%s/f,%sms/f", kPhaseName[p], perStr(cn, f, a1), msStr(q, f, a2));
                }
            }
            char g1[16], g2[16], g3[16], g4[16];
            logf("rt: phases ms/f logic %s client-outside-stages %s outside-both %s | logic by sub-frame:%s",
                 msStr(dPh[PH_LOGIC], f, g1), msStr(dPh[PH_CLIENT] - sh - vw - ui, f, g2), msStr(dP - dPh[PH_LOGIC] - dPh[PH_CLIENT], f, g3), lg);
            logf("rt: frames <20:%d <25:%d <33:%d <40:%d <50:%d <67:%d <100:%d <200:%d >=200:%d max %s ms | frame ms by sub-frame:%s",
                 (int)fh[0], (int)fh[1], (int)fh[2], (int)fh[3], (int)fh[4], (int)fh[5], (int)fh[6], (int)fh[7], (int)fh[8], msStr(fmx, 1, g4), fb);
            if (g_diag) logf("rt: anim%s", an);
            static LONG lEH = 0, lEM = 0, lEF = 0, lPW = 0, lPS = 0, lPSt = 0, lPC = 0, lPP = 0, lFH = 0, lFM = 0, lFC = 0; static LONG64 lPT = 0, lPST = 0;
            LONG eh = g_eqHit, em = g_eqMiss, ef = g_eqFast, pw = g_pwWarmed, ps = g_pwSkips, pst = g_pwStale, pc = g_pwChecked, pp = g_pwPasses; LONG64 pt = rd64(&g_pwTicks), pscan = rd64(&g_pwScanTicks);
            LONG fhit = g_fltHit, fm = g_fltMiss, fc = g_fltCalls;
            char e1[16], e2[16], e3[16], w1[16], w2[16], w3[16], w4[16], w5[16], w6[16], w7[16], x1[16], x2[16], x3[16];
            logf("rt: opt buf-mirror adopted %d locks %d dropped %d failed %d evicted %d MB %d fallback ro %d noptr %d full %d desc %d range %d arena %d nomirror %d | annotation reads kept %d | fresh-texture locks %d (sync %d, tracked %d) | tex-mirror adopted %d locks %d dropped %d failed %d | fastcrt=%d | equiv-memo hit/f %s miss/f %s same-final/f %s clears %d | filter-memo calls/f %s hit/f %s miss/f %s clears %d | pose-warm2 %s workers=%d passes/f %s warmed/f %s skipped/f %s stale/f %s checked/f %s mismatches %d faults %d warm %s ms/f (scan %s)",
                 (int)g_rtNBMAdopt, (int)g_rtNBMLock, (int)g_rtNBMDrop, (int)g_rtNBMFail, (int)g_rtNBMEvict, (int)(g_rtBMBytes >> 20),
                 (int)g_rtBufFallback[0], (int)g_rtBufFallback[1], (int)g_rtBufFallback[2], (int)g_rtBufFallback[3], (int)g_rtBufFallback[4], (int)g_rtBufFallback[5], (int)g_rtBufFallback[6], (int)g_rtNAnnHit, (int)g_rtNFreshLock, (int)g_rtNFreshMiss, (int)g_rtNFreshAdd, (int)g_rtNTMAdopt, (int)g_rtNTMLock, (int)g_rtNTMDrop, (int)g_rtNTMFail, (int)g_crtInstalled, perStr(eh - lEH, f, e1), perStr(em - lEM, f, e2), perStr(ef - lEF, f, e3), (int)g_eqClears,
                 perStr(fc - lFC, f, x1), perStr(fhit - lFH, f, x2), perStr(fm - lFM, f, x3), (int)g_fltClears,
                 g_pwKill ? "OFF" : (g_pwCheckLeft > 0 ? "checking" : "live"), g_pwNW, perStr(pp - lPP, f, w6), perStr(pw - lPW, f, w1), perStr(ps - lPS, f, w2), perStr(pst - lPSt, f, w3), perStr(pc - lPC, f, w4),
                 (int)g_pwMismatch, (int)g_pwFaults, msStr(pt - lPT, f, w5), msStr(pscan - lPST, f, w7));
            lEH = eh; lEM = em; lEF = ef; lPW = pw; lPS = ps; lPSt = pst; lPC = pc; lPP = pp; lPT = pt; lPST = pscan; lFH = fhit; lFM = fm; lFC = fc;
            { static LONG lOpN[512]; LONG dn[512]; char ln[900]; int q = 0;
              for (int i = 0; i < 512; ++i) { LONG v = g_rtOpN[i]; dn[i] = v - lOpN[i]; lOpN[i] = v; }
              q += wsprintfA(ln + q, "rt: queued ops per frame:");
              bool used[512]; memset(used, 0, sizeof(used));
              for (int k = 0; k < 12; ++k) {
                  int bi = -1; LONG bc = 0;
                  for (int i = 0; i < 512; ++i) if (!used[i] && dn[i] > bc) { bc = dn[i]; bi = i; }
                  if (bi < 0) break; used[bi] = true;
                  char p1[16]; q += wsprintfA(ln + q, " %s %s |", rtOpName(bi), perStr(bc, f, p1));
                  if (q > 800) break;
              }
              logf("%s", ln); }
            rlReport(f);
            if (g_diag) { ftReport(f); ctReport(f); }
            pickReport(f);
            if (g_diag) ssReport(f);
            dgReport(f);
            lsReport(f);
            mxReport(f);
            alReport(f);
            { static LONG lFJ = 0, lFS = 0, lFSt = 0, lFC = 0, lFR = 0;
              LONG fj = g_pwFullJobs, fs = g_pwFullSkips, fst = g_pwFullStale, fc = g_pwFullChecked;
              char q1[16], q2[16], q3[16], q4[16];
              static LONG lBW = 0; LONG bw = g_pwBoundsWarmed; char q5[16];
              logf("rt: pose-warm3 %s | whole-HLod jobs/f %s skipped/f %s stale/f %s checked/f %s mismatches %d | sub-object bounds warmed/f %s",
                   g_pwFullOn ? "on" : "OFF", perStr(fj - lFJ, f, q1), perStr(fs - lFS, f, q2), perStr(fst - lFSt, f, q3), perStr(fc - lFC, f, q4), (int)g_pwFullMismatch, perStr(bw - lBW, f, q5));
              lFJ = fj; lFS = fs; lFSt = fst; lFC = fc; lBW = bw; (void)lFR; }
            { static LONG lCand[8]; char ln[400];
              char c0[16], c1[16], c2[16], c3[16], c4[16], c5[16], c6[16];
              LONG d[7]; for (int i = 0; i < 7; ++i) { LONG v = g_pwCand[i]; d[i] = v - lCand[i]; lCand[i] = v; }
              char w1[16]; LONG wn = g_pwWaitRep; LONG64 wt = rd64(&g_pwWaitRepT);
              static LONG lWn = 0; static LONG64 lWt = 0; LONG dwn = wn - lWn; LONG64 dwt = wt - lWt; lWn = wn; lWt = wt;
              msStr(dwt, f, w1);
              wsprintfA(ln, "rt: pose-warm scan per frame: nodes %s | rejected: not-HLod %s no-tree %s anim-mode %s already-clean %s not-drawn-last-frame %s | taken %s | worker wait %s ms/f over %d passes%s",
                        perStr(d[0], f, c0), perStr(d[1], f, c1), perStr(d[2], f, c2), perStr(d[3], f, c3), perStr(d[4], f, c4), perStr(d[5], f, c5), perStr(d[6], f, c6),
                        w1, (int)dwn, g_pwStop ? " (WARMING OFF: the wait cost more than it saved)" : "");
              logf("%s", ln); }
            { static LONG lWhy[8]; LONG d[8]; for (int i = 0; i < 8; ++i) { LONG v = g_pwWhy[i]; d[i] = v - lWhy[i]; lWhy[i] = v; }
              if (d[7] > 0) {
                  char ln[700]; int q = 0;
                  q += wsprintfA(ln + q, "rt: pose-warm refusals (1 in 8 sampled, %d): in-container %d no-tree %d lod-table %d null/bone %d sub-object-class %d sub-object-owner %d extra-list %d | classes:",
                                 (int)d[7], (int)d[0], (int)d[1], (int)d[2], (int)d[3], (int)d[4], (int)d[5], (int)d[6]);
                  for (int i = 0; i < 12 && g_pwBadVt[i] && q < 620; ++i) q += wsprintfA(ln + q, " vt game.dat+%06X (slot#%d) x%d", g_pwBadVt[i] - 0x400000, (int)g_pwBadSlot[i], (int)g_pwBadVtN[i]);
                  logf("%s", ln);
              } }
            { static LONG lS = 0, lO = 0, lM = 0; LONG sb = g_rtPH.cpuSib, ot = g_rtPH.cpuOther, mg = g_rtPH.cpuMigr; LONG ds = sb - lS, dOt = ot - lO; char m1[16];
              LONG tot = ds + dOt;
              logf("rt: cpu placement: worker on the game thread's SMT sibling in %d%% of %d samples; game thread cpu changes/f %s (now cpu %u, worker cpu %u)",
                   tot > 0 ? (int)(ds * 100 / tot) : 0, (int)tot, perStr(mg - lM, f, m1), (unsigned)g_rtPH.lastCpu, (unsigned)g_rtWH.cpu);
              lS = sb; lO = ot; lM = mg; }
            { static LONG lFs = 0, lFk = 0; LONG fs = g_rtNFxSkip, fk = g_rtNFxKept; char q1[16], q2[16];
              logf("rt: effect parameters already set/f %s, written/f %s%s | table drops: %d (off-queue call %d, block %d, reset %d, other %d; off-queue from: other thread %d, rt off %d, direct scope %d), by parameter block %d", perStr(fs - lFs, f, q1), perStr(fk - lFk, f, q2), g_rtFxDedupeOn ? "" : " (de-dupe OFF)", (int)g_rtNFxInval, (int)g_rtNFxInvalWhy[0], (int)g_rtNFxInvalWhy[1], (int)g_rtNFxInvalWhy[2], (int)g_rtNFxInvalWhy[3], (int)g_rtNFxOffWho[0], (int)g_rtNFxOffWho[1], (int)g_rtNFxOffWho[2], (int)g_rtNFxBlkInval); lFs = fs; lFk = fk; }
            { static LONG lXs = 0, lXh = 0, lSd = 0, lAf = 0; LONG xs = g_rtNXSaved, xh = g_rtNXHit, sd = g_rtNSyncDL, af = g_rtNAsyncFilter; char e1[16], e2[16], e3[16], e4[16];
              static LONG lH2 = 0; LONG h2 = g_rtNH2Saved; char e5[16];
              logf("rt: lock checks answered exactly/f %s, waits avoided/f %s (exact entries %d, added %d, replaced %d) | first-time objects cleared by the second hash/f %s | drained system-memory locks unlocked directly/f %s | mip filters queued/f %s",
                   perStr(xh - lXh, f, e1), perStr(xs - lXs, f, e2), (int)g_rtXN, (int)g_rtNXAdd, (int)g_rtNXEvict, perStr(h2 - lH2, f, e5), perStr(sd - lSd, f, e3), perStr(af - lAf, f, e4)); lXs = xs; lXh = xh; lSd = sd; lAf = af; lH2 = h2;
              int liveM = 0; for (int i = 0; i < RT_TMIR; ++i) if (g_rtTM[i].live && !g_rtTM[i].dead) ++liveM;
              logf("rt: tex mirrors live %d of %d | adopted %d dropped %d failed %d | no free slot %d | refused without waiting %d | first locks left alone %d, idle mirrors replaced %d", liveM, RT_TMIR, (int)g_rtNTMAdopt, (int)g_rtNTMDrop, (int)g_rtNTMFail, (int)g_rtNTMNoSlot, (int)g_rtNTMNoHit, (int)g_rtNTMFirst, (int)g_rtNTMEvict); }
            { static LONG lXc[16]; static LONG64 lXt[16]; char ln[700]; int q = 0; ln[0] = 0;
              for (int k = 0; k < 14; ++k) { LONG cN = g_rtXCalls[k], dN = cN - lXc[k]; LONG64 tN = rd64(&g_rtXTicks[k]), dT = tN - lXt[k]; lXc[k] = cN; lXt[k] = tN; if (dN <= 0) continue;
                  char x1[16], x2[16]; q += wsprintfA(ln + q, " %s %s/f %s ms/f |", kRtX[k].name, perStr(dN, f, x1), msStr(dT, f, x2)); if (q > 600) break; }
              if (q) logf("rt: exclusive D3DX scopes (each waits for the queue):%s", ln); }
            { static LONG lSk = 0, lSt = 0; LONG sk = g_rtDs.nSkip, st = g_rtDs.nSet; char d1[16], d2[16];
              logf("rt: vertex-input calls already in place/f %s, queued/f %s%s", perStr(sk - lSk, f, d1), perStr(st - lSt, f, d2), g_rtDs.on ? "" : " (de-dupe OFF)"); lSk = sk; lSt = st; }
            { static LONG lSn = 0, lGe = 0; LONG sn = g_rtNUSSnap, ge = g_rtNUSGeneric; char u1[16], u2[16];
              logf("rt: UpdateSurface snapshots/f %s, as before/f %s (private staging surfaces %d)%s | atlas mirror %s", perStr(sn - lSn, f, u1), perStr(ge - lGe, f, u2), (int)g_rtNUSStage,
                   g_rtUSOn ? "" : " (snapshots OFF)", g_rtTMAtlasOn ? "on" : "OFF"); lSn = sn; lGe = ge; }
            { static LONG lB = 0, lE = 0; LONG b = g_rtNFxBatch, e = g_rtNFxEntry; char b1[16], b2[16];
              logf("rt: effect parameter batches/f %s, writes/f %s%s", perStr(b - lB, f, b1), perStr(e - lE, f, b2), g_rtFxBatchOn ? "" : " (batching OFF)"); lB = b; lE = e; }
        }
        lQH = qh; lQM = qm; lStg = st; lSf = sf; lLk = lk; lDL = dl; lMir = mir;
        static bool gsStarted = false;
        if (!gsStarted && g_gsStart && g_rtActive && dF >= 20 && dP >= (LONG64)dF * g_pqpf.QuadPart * 30 / 1000) {
            gsStarted = true; HANDLE hg = CreateThread(NULL, 0, g_gsStart, NULL, 0, NULL); if (hg) CloseHandle(hg);
        }
        static int rep6 = 0; static LONG dumpFrames = 0;
        dumpFrames += dF;
        if (++rep6 >= 6) {                                     // every 30 s: where the remaining synchronous calls come from
            rep6 = 0;
            LONG fr30 = dumpFrames; dumpFrames = 0;
            if (fr30 >= 60) {
                mtReport(fr30);
                profRefreshModules();
                static bool usedS[RT_SCN]; memset(usedS, 0, sizeof(usedS));
                for (int k = 0; k < 12; ++k) {
                    int bi = -1; LONG bc = 0;
                    for (int i = 0; i < RT_SCN; ++i) { LONG dn = g_rtSC[i].n - g_rtSC[i].ln; if (g_rtSC[i].ra && !usedS[i] && dn > bc) { bc = dn; bi = i; } }
                    if (bi < 0) break;
                    usedS[bi] = true;
                    char sym[160], pf[16]; symName(g_rtSC[bi].ra, sym);
                    logf("rt:   sync caller %s %s x%d in %d frames (%s/f, drain total for the op above)", sym, rtOpName(g_rtSC[bi].op), (int)bc, (int)fr30, perStr(bc, fr30, pf));
                }
                static bool usedL[RT_LSN]; memset(usedL, 0, sizeof(usedL));
                for (int k = 0; k < 10; ++k) {
                    int bi = -1; LONG bc = 0;
                    for (int i = 0; i < RT_LSN; ++i) { LONG dn = g_rtLS[i].n - g_rtLS[i].ln; if (g_rtLS[i].ra && !usedL[i] && dn > bc) { bc = dn; bi = i; } }
                    if (bi < 0) break;
                    usedL[bi] = true;
                    RtLockStat& e = g_rtLS[bi]; char sym[160], pf[16]; symName(e.ra, sym);
                    logf("rt:   lock %s %s pool=%d fmt=%d usage=%X %dx%d flags=%X %s x%d in %d frames (%s/f)%s%s", (e.flags & 0x80000000u) ? "tex" : "surf", sym, (int)e.pool, (int)e.fmt, (unsigned)e.usage,
                         (int)e.w, (int)e.h, (unsigned)(e.flags & 0x7FFFFFFFu), e.fast ? "DIRECT" : "sync", (int)bc, (int)fr30, perStr(bc, fr30, pf),
                         !e.fast ? (e.who ? (e.exact ? " - its TEXTURE is named by a queued " : " - its texture's shared slot was stamped by ") : (e.exact ? " - it is named by a queued " : " - not tracked exactly yet / shared slot stamped by ")) : "",
                         !e.fast ? (e.blocker != 0xFFFF ? rtOpName(e.blocker) : "(a call without an op: release / mirror / batch)") : "");
                }
            }
            for (int i = 0; i < RT_SCN; ++i) if (g_rtSC[i].ra) g_rtSC[i].ln = g_rtSC[i].n;
            for (int i = 0; i < RT_LSN; ++i) if (g_rtLS[i].ra) g_rtLS[i].ln = g_rtLS[i].n;
        }
        (void)m8; (void)pr; (void)lPresent;
        lAsync = a; lSync = s; lRel = rl; lForeign = fo; lPresent = pr; lScope = sc; lDrain = dr; lBusy = bu; lBytes = by; lPWait = pw;
    }
    return 0;
}

// ---------------------------------------------------------------- test entry points (offline harness)
extern "C" __declspec(dllexport) int __cdecl AotrRtTestInstall(void* dev, void* fx) {
    (void)dev;
    if (!g_pqpf.QuadPart) QueryPerformanceFrequency(&g_pqpf);
    g_mkTid = GetCurrentThreadId();
    rtInit();
    if (!g_rtActive && !g_rtTried) rtInstall(fx);
    return g_rtActive ? 1 : 0;
}
extern "C" __declspec(dllexport) void* __cdecl AotrRtTestScopedD3DX(const char* name) {   // wrapper that runs `name` as an exclusive scope
    HMODULE hx = GetModuleHandleA("d3dx9_27.dll");
    for (int i = 0; i < 14; ++i) if (hx && !strcmp(kRtX[i].name, name)) {
        if (!g_rtXO[i]) g_rtXO[i] = (void*)GetProcAddress(hx, name);
        return g_rtXO[i] ? kRtX[i].hook : NULL;
    }
    return NULL;
}
extern "C" __declspec(dllexport) void __cdecl AotrRtTestToggle(int on) { InterlockedExchange(&g_rtWantOn, on ? 1 : 0); }
// Benchmark aid: park the worker (it blocks on the exec lock at its next batch) so a timed burst measures the
// game thread's enqueue path alone, without the worker's core, cache or SMT sibling in the picture.
extern "C" __declspec(dllexport) void __cdecl AotrRtTestAtlasAny(int on) { g_rtTMAtlasAny = on ? 1 : 0; }
extern "C" __declspec(dllexport) void __cdecl AotrRtTestHold(int on) {
    if (on) { rtExecLock(); Sleep(2); } else LeaveCriticalSection(&g_rtExecCs);
}
static void rtTestRadarModify(BYTE* bits, INT pitch, DWORD w, DWORD h, DWORD op, DWORD e) {     // the read-modify-write the radar test does
    for (DWORD y = 0; y < h; ++y) for (DWORD x = 0; x < w; ++x) {
        DWORD* px = (DWORD*)(bits + (INT)y * pitch + x * 4);
        *px = op == 1 ? (*px * 3 + e + (x ^ (y << 3))) : ((*px >> 1) ^ (e * (x + 1)));
    }
}
extern "C" __declspec(dllexport) void __cdecl AotrRtTestRadarOp(void* surf, DWORD op, DWORD a, DWORD b, DWORD c, DWORD d, DWORD e) {
    DWORD s = (DWORD)(ULONG_PTR)surf;
    if (GetCurrentThreadId() == g_rtMainTid && g_rtActive && !g_rtDirectScope) {                    // the bodies of the SurfaceClass hooks
        if (op == 2) { if (rtTMClear(s, a, true)) return; }
        else {
            int pitch = 0;
            void* p = op == 1 ? rtTMLockRect(s, &pitch, a, b, c, d, true) : (rtTMFind(s) ? rtTMLockAll(s, &pitch) : rtTMLockRect(s, &pitch, 0, 0, 128, 128, true));
            if (p != RT_TM_NOT) {
                if (p) { RtTexMir* m = rtTMFind(s); if (m) rtTestRadarModify((BYTE*)p, pitch, m->r - m->l, m->b - m->t, op, e); }
                rtTMUnlock(s);
                return;
            }
        }
    }
    void** vt = *(void***)surf;                                                                     // what the engine does without mirrors
    struct { LONG l, t, rr, b; } rc = { (LONG)a, (LONG)b, (LONG)c, (LONG)d };
    struct { INT pitch; void* bits; } lr = { 0, NULL };
    DWORD hr = ((DWORD(__stdcall*)(void*, void*, void*, DWORD))vt[13])(surf, &lr, op == 1 ? &rc : NULL, op == 2 ? 0 : 0x800);
    if ((LONG)hr < 0 || !lr.bits) return;
    if (op == 2) { for (int y = 0; y < 128; ++y) memset((BYTE*)lr.bits + y * lr.pitch, (BYTE)a ? 0xFF : 0x00, 128 * 4); }
    else rtTestRadarModify((BYTE*)lr.bits, lr.pitch, op == 1 ? c - a : 128, op == 1 ? d - b : 128, op, e);
    ((DWORD(__stdcall*)(void*))vt[14])(surf);
}
extern "C" __declspec(dllexport) void __cdecl AotrRtTestPixelOp(void* surf, DWORD x, DWORD y, DWORD v, DWORD mode) {
    if (GetCurrentThreadId() == g_rtMainTid && g_rtActive && !g_rtDirectScope) { if (g_rtTMAny) rtTMPixel((DWORD)(ULONG_PTR)surf, x, y, v, mode); rtPixelRecord((DWORD)(ULONG_PTR)surf, x, y, v, mode); return; }
    struct { LONG l, t, rr, b; } rc = { (LONG)x, (LONG)y, (LONG)x + 1, (LONG)y + 1 };
    struct { INT pitch; void* bits; } lr = { 0, NULL };
    void** vt = *(void***)surf;
    ((DWORD(__stdcall*)(void*, void*, void*, DWORD))vt[13])(surf, &lr, &rc, 0);
    if (lr.bits) switch (mode) { case 1: *(BYTE*)lr.bits = (BYTE)v; break; case 2: *(WORD*)lr.bits = (WORD)v; break; case 4: *(DWORD*)lr.bits = v; break; case 0x100: ((BYTE*)lr.bits)[3] = (BYTE)v; break; }
    ((DWORD(__stdcall*)(void*))vt[14])(surf);
}
extern "C" __declspec(dllexport) void __cdecl AotrRtTestShroudRect(void* surf, DWORD l, DWORD t, DWORD r, DWORD b, const BYTE* rows, DWORD bpp) {
    DWORD sc[1] = { (DWORD)(ULONG_PTR)surf };                 // a SurfaceClass is the surface pointer
    int pitch = 0;
    BYTE* dst;
    if (GetCurrentThreadId() == g_rtMainTid && g_rtActive && !g_rtDirectScope) dst = (BYTE*)hk_rtShroudLock(sc, NULL, &pitch, l, t, r, b);
    else {                                                     // what 0x516090 does
        struct { LONG l, t, rr, b; } rc = { (LONG)l, (LONG)t, (LONG)r, (LONG)b }; struct { INT pitch; void* bits; } lr = { 0, NULL };
        ((DWORD(__stdcall*)(void*, void*, void*, DWORD))(*(void***)surf)[13])(surf, &lr, &rc, 0x800); pitch = lr.pitch; dst = (BYTE*)lr.bits;
    }
    DWORD w = r - l, rowBytes = w * bpp;
    if (dst) for (DWORD y = 0; y < b - t; ++y) memcpy(dst + (INT)y * pitch, rows + y * rowBytes, rowBytes);
    if (GetCurrentThreadId() == g_rtMainTid && g_rtActive && !g_rtDirectScope) hk_rtShroudUnlock(sc, NULL);
    else ((DWORD(__stdcall*)(void*))(*(void***)surf)[14])(surf);
}
extern "C" __declspec(dllexport) void __cdecl AotrRtTestSeqBase(DWORD base) {   // before install only: queue empty
    g_rtPH.seq = base; g_rtWH.execSeq = base; g_rtDrainSeq = base;
}
extern "C" __declspec(dllexport) void __cdecl AotrRtTestThreads(char* out, int n) {   // tid, description, ideal cpu, cpu time
    int p = 0; out[0] = 0;
    typedef HRESULT (WINAPI* GetDescF)(HANDLE, PWSTR*);
    GetDescF gd = (GetDescF)GetProcAddress(GetModuleHandleA("kernel32.dll"), "GetThreadDescription");
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (snap == INVALID_HANDLE_VALUE) return;
    THREADENTRY32 te; te.dwSize = sizeof(te); DWORD pid = GetCurrentProcessId();
    if (Thread32First(snap, &te)) do {
        if (te.th32OwnerProcessID != pid) continue;
        HANDLE h = OpenThread(THREAD_QUERY_LIMITED_INFORMATION | THREAD_SET_INFORMATION | THREAD_QUERY_INFORMATION, FALSE, te.th32ThreadID);
        char name[64] = "?";
        DWORD ideal = 0xFFFFFFFF; ULONG64 cpu = 0;
        if (h) {
            if (gd) { PWSTR w = NULL; if (SUCCEEDED(gd(h, &w)) && w) { WideCharToMultiByte(CP_ACP, 0, w, -1, name, 63, NULL, NULL); LocalFree(w); } }
            ideal = SetThreadIdealProcessor(h, MAXIMUM_PROCESSORS);
            FILETIME c, e, k, u; if (GetThreadTimes(h, &c, &e, &k, &u)) cpu = ((((ULONG64)k.dwHighDateTime << 32) | k.dwLowDateTime) + (((ULONG64)u.dwHighDateTime << 32) | u.dwLowDateTime)) / 10000;
            CloseHandle(h);
        }
        if (p < n - 80) p += wsprintfA(out + p, "  %u%s%s [%s] ideal=%d cpu=%dms\n", te.th32ThreadID, te.th32ThreadID == g_rtMainTid ? " MAIN" : "",
                                       te.th32ThreadID == g_rtWorkerTid ? " RTWORKER" : "", name, (int)ideal, (int)cpu);
    } while (Thread32Next(snap, &te));
    CloseHandle(snap);
}
extern "C" __declspec(dllexport) void __cdecl AotrRtTestCpu(char* out, int n) {
    int p = 0; p += wsprintfA(out + p, "main cpus:");
    for (int i = 0; i < 64 && p < n - 40; ++i) if (g_rtCpuHistM[i]) p += wsprintfA(out + p, " %d:%d", i, (int)g_rtCpuHistM[i]);
    p += wsprintfA(out + p, " | worker cpus:");
    for (int i = 0; i < 64 && p < n - 40; ++i) if (g_rtCpuHistW[i]) p += wsprintfA(out + p, " %d:%d", i, (int)g_rtCpuHistW[i]);
    for (int i = 0; i < 64; ++i) { g_rtCpuHistW[i] = 0; g_rtCpuHistM[i] = 0; }
}
extern "C" __declspec(dllexport) void __cdecl AotrRtTestStatsV4(char* out, int n) {
    if (!out || n < 64) return;
    char wm[16];
    wsprintfA(out, "direct_locks=%d direct_unlocks=%d locked_calls=%d mirror=%d pixel_records=%d shroud_records=%d pb_proxies=%d qcache_hit=%d miss=%d seq=%u exec=%u | drains=%d waits=%d (timeouts %d, %s ms) worker sleeps=%d (timeouts %d) | tex mirrors adopted %d locks %d dropped %d failed %d | buf mirrors adopted %d locks %d dropped %d failed %d | annotation reads kept %d | evicted %d",
              (int)g_rtNDirectLock, (int)g_rtNDirectUnlock, (int)g_rtNLocked, (int)g_rtNMirror, (int)g_rtNPixel, (int)g_rtNShroud, (int)g_rtNPBProxy, (int)g_rtQHit, (int)g_rtQMiss, g_rtPH.seq, g_rtWH.execSeq,
              (int)g_rtDrains, (int)g_rtWaitCalls, (int)g_rtWaitTimeouts, msStr(rd64(&g_rtWaitTicks), 1, wm), (int)g_rtWorkerSleeps, (int)g_rtWorkerTimeouts, (int)g_rtNTMAdopt, (int)g_rtNTMLock, (int)g_rtNTMDrop, (int)g_rtNTMFail, (int)g_rtNBMAdopt, (int)g_rtNBMLock, (int)g_rtNBMDrop, (int)g_rtNBMFail, (int)g_rtNAnnHit, (int)g_rtNBMEvict);
    wsprintfA(out + lstrlenA(out), " | main-op=%d worker-op=%d head=%u tail=%u scope=%d lockwant=%d", g_rtCurOp, g_rtWorkerOp, g_rtHead, g_rtTail, g_rtDirectScope, g_rtLK.want);
    wsprintfA(out + lstrlenA(out), " | fx-dedupe skipped=%d written=%d whole-drops=%d (off-queue %d, block %d, reset %d, other %d) block-drops=%d | off-queue from: other-thread %d rt-off %d direct-scope %d | by setter: bool %d int %d float %d vector %d matrix %d matrixT %d texture %d raw %d", (int)g_rtNFxSkip, (int)g_rtNFxKept, (int)g_rtNFxInval, (int)g_rtNFxInvalWhy[0], (int)g_rtNFxInvalWhy[1], (int)g_rtNFxInvalWhy[2], (int)g_rtNFxInvalWhy[3], (int)g_rtNFxBlkInval, (int)g_rtNFxOffWho[0], (int)g_rtNFxOffWho[1], (int)g_rtNFxOffWho[2], (int)g_rtNFxOffSlot[22], (int)g_rtNFxOffSlot[26], (int)g_rtNFxOffSlot[30], (int)g_rtNFxOffSlot[34], (int)g_rtNFxOffSlot[38], (int)g_rtNFxOffSlot[44], (int)g_rtNFxOffSlot[52], (int)g_rtNFxOffSlot[78]);
}
extern "C" __declspec(dllexport) void __cdecl AotrRtTestStats(char* out, int n) {
    if (!out || n < 64) return;
    char m1[16], m2[16];
    wsprintfA(out, "active=%d queued=%d sync=%d release=%d scope=%d foreign=%d presents=%d drain_ms=%s busy_ms=%s",
              (int)g_rtActive, (int)g_rtNAsync, (int)g_rtNSync, (int)g_rtNRelease, (int)g_rtNScope, (int)g_rtNForeign, (int)g_rtNPresent,
              msStr(rd64(&g_rtDrainTicks), 1, m1), msStr(rd64(&g_rtBusyTicks), 1, m2));
}

// ---------------------------------------------------------------- frame capture: the queue side (see aotr_capture.inc)
static void capRecord(RtRec* r, DWORD po) {                        // game thread, from rtCommit
    const DWORD* a = rtArgs(r); const BYTE* P = rtPayload(r);
    capPrintf("R %s k=%u n=%u", rtOpName(r->op), (unsigned)r->kind, (unsigned)r->nargs);
    for (DWORD i = 0; i < r->nargs && i < 16; ++i) capPrintf(" %08X", a[i]);
    if (po) { capPrintf(" | pl=%u h=%08X ", po, capHash(P, po)); capHex(P, po < 256 ? po : 256); }
    capPrintf("\n");
}
static LONG g_capSavedFx = 1, g_capSavedDs = 1;
static void capStart(LONG frames) {
    if (g_rtFxRec) rtFxClose();
    g_capSavedFx = g_rtFxBatchOn; g_rtFxBatchOn = 0;               // every effect parameter write as its own record
    g_capSavedDs = g_rtDs.on; g_rtDs.on = 0; rtDsInvalAll();        // and every vertex-input call the engine makes
    g_capFramesLeft = frames; g_capPos = 0;
    capPrintf("F capture round %d begins at frame %d\n", (int)g_capRounds + 1, (int)g_mkFrames);
    g_capOn = 1;
}
static void capStop() {
    g_capOn = 0;
    if (g_rtFxRec) rtFxClose();
    g_rtFxBatchOn = g_capSavedFx; g_rtDs.on = g_capSavedDs; rtDsInvalAll();
    g_capRounds++; g_capLastTick = GetTickCount(); g_capBusyWriting = 1;
    HANDLE h = CreateThread(NULL, 0, capWriter, NULL, 0, NULL); if (h) CloseHandle(h); else g_capBusyWriting = 0;
}
static void capFrameTick() {                                       // game thread, once per frame, before the logic call
    static LONG lastPush = 0;
    LONG pushes = g_rlPushN[PH_SHADOW], d = pushes - lastPush; lastPush = pushes;      // shadow casters pushed during the last frame
    if (g_capOn) { if (--g_capFramesLeft <= 0) capStop(); else capPrintf("F frame boundary at frame %d\n", (int)g_mkFrames); return; }
    if (g_capRounds >= 3 || g_capBusyWriting || !g_rtActive) return;
    if (d >= 400 && GetTickCount() - g_capLastTick > 20000) capStart(2);
}
extern "C" __declspec(dllexport) void __cdecl AotrRtTestCaptureTick(int frame) {   // offline harness: capture frames 50-51
    if (!g_capBuf) g_capBuf = (char*)VirtualAlloc(NULL, CAP_CAP, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!g_capBuf) return;
    if (g_capOn) { if (--g_capFramesLeft <= 0) capStop(); else capPrintf("F frame boundary\n"); return; }
    if (frame == 50) capStart(2);
}
