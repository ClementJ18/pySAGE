// ---------------------------------------------------------------- CPU mirrors of the radar overlay textures
// The radar (0x44C000..0x451000) reads, blends and writes rectangles of small MANAGED A8R8G8B8 textures through
// SurfaceClass::Lock (0x516090 rect, 0x516030 whole), Unlock (0x516110) and Clear (0x516130): 3-5 synchronous queue drains
// per battle frame. The first such call from the radar on a surface brings the texture's pixels into a CPU mirror (one
// synchronous read) and keeps a reference to the texture. From then on every lock of that surface through SurfaceClass
// returns mirror memory with pitch = width * 4, every unlock (and every Clear, applied to the mirror as the engine fills
// rows) queues LockRect + row copies + UnlockRect of that rectangle, and DrawPixel / alpha writes change the mirror as
// they are queued. The mirror therefore always holds what the texture holds once the queue has run up to that point.
// Any other lock of the surface or its texture (D3D LockRect from elsewhere, D3DX, shroud staging) or a device Reset
// drops the mirror before it runs; the kept reference is released through the queue.
struct RtTexMir { DWORD surf, tex, w, h, bpp, lastFrame; BYTE* mem; BYTE live, dead, locked, d3d; DWORD l, t, r, b; DWORD cap; };   // d3d: locked through IDirect3DSurface9::LockRect (1 read-write, 2 read-only)
#define RT_TMIR 32                                         // the terrain keeps many atlas pages (v23: more than the 8 refusals it could remember)
static RtTexMir g_rtTM[RT_TMIR];
static volatile LONG g_rtNTMLock = 0, g_rtNTMAdopt = 0, g_rtNTMDrop = 0, g_rtNTMFail = 0, g_rtNTMNoSlot = 0;
static BYTE* g_rtTMTmp = NULL;
typedef void* (__fastcall* tSurfLockRect)(DWORD*, void*, int*, DWORD, DWORD, DWORD, DWORD);
typedef void* (__fastcall* tSurfLockAll)(DWORD*, void*, int*, DWORD);
typedef void  (__fastcall* tSurfUnlockFn)(DWORD*, void*);
typedef void  (__fastcall* tSurfClearFn)(DWORD*, void*, DWORD);
static tSurfLockRect o_surfLockRect = NULL;
static tSurfLockAll  o_surfLockAll = NULL;
static tSurfUnlockFn o_surfUnlock = NULL;
static tSurfClearFn  o_surfClear = NULL;
static const GUID kRtIIDTexture9 = {0x85C31227, 0x3DE5, 0x4F00, {0x9B, 0x3A, 0xF1, 0x1A, 0xC3, 0x8C, 0x18, 0xB5}};

static __forceinline bool rtTMGameThread() { return __readfsdword(0x24) == g_rtMainTid && g_rtActive && !g_rtDirectScope; }
static RtTexMir* rtTMFind(DWORD surf) {
    for (int i = 0; i < RT_TMIR; ++i) if (g_rtTM[i].live && !g_rtTM[i].dead && g_rtTM[i].surf == surf) return &g_rtTM[i];
    return NULL;
}
static DWORD g_rtTMDropSurf[8]; static BYTE g_rtTMDropN[8];  // how often a surface's mirror was dropped by a lock from elsewhere
static void rtTMKill(DWORD obj) {                          // any thread and scope: the object is about to be read or written elsewhere
    for (int i = 0; i < RT_TMIR; ++i)
        if (g_rtTM[i].live && !g_rtTM[i].dead && (g_rtTM[i].surf == obj || g_rtTM[i].tex == obj)) {
            g_rtTM[i].dead = 1; g_rtNTMDrop++;
            DWORD sf = g_rtTM[i].surf; int k = -1;
            for (int j = 0; j < 8; ++j) if (g_rtTMDropSurf[j] == sf) { k = j; break; }
            if (k < 0) { static int rr = 0; k = rr++ & 7; g_rtTMDropSurf[k] = sf; g_rtTMDropN[k] = 0; }
            if (g_rtTMDropN[k] < 255) g_rtTMDropN[k]++;
        }
}
static __forceinline bool rtTMThrashes(DWORD surf) { for (int j = 0; j < 8; ++j) if (g_rtTMDropSurf[j] == surf) return g_rtTMDropN[j] >= 4; return false; }
static DWORD g_rtTMNo[16]; static int g_rtTMNoI = 0;     // surfaces that could not be mirrored (not asked again until the next reset)
static volatile LONG g_rtNTMNoHit = 0;
static __forceinline bool rtTMRefused(DWORD surf) { for (int i = 0; i < 16; ++i) if (g_rtTMNo[i] == surf) return true; return false; }
static void rtTMRefuse(DWORD surf) { if (!rtTMRefused(surf)) g_rtTMNo[g_rtTMNoI++ & 15] = surf; }
static bool rtTMIsMirroredTex(DWORD tex) { for (int i = 0; i < RT_TMIR; ++i) if (g_rtTM[i].live && !g_rtTM[i].dead && g_rtTM[i].tex == tex && !g_rtTM[i].locked) return true; return false; }
static void rtTMKillAll() { for (int i = 0; i < RT_TMIR; ++i) if (g_rtTM[i].live && !g_rtTM[i].dead) { g_rtTM[i].dead = 1; g_rtNTMDrop++; } memset(g_rtTMNo, 0, sizeof(g_rtTMNo)); }
static void rtTMReap() {                                   // game thread outside direct scope: release what dead or idle mirrors kept
    for (int i = 0; i < RT_TMIR; ++i) {
        RtTexMir& m = g_rtTM[i];
        if (!m.live || m.locked || !(m.dead || (DWORD)(g_mkFrames - m.lastFrame) > 900)) continue;
        m.live = 0; m.dead = 0;
        rt_tex_2((void*)(ULONG_PTR)m.tex);
    }
}
static void rtTMFlush(RtTexMir* m) {                       // queue the locked rectangle's pixels
    DWORD w = m->r - m->l, h = m->b - m->t, row = w * m->bpp, bytes = row * h;
    for (DWORD y = 0; y < h; ++y) memcpy(g_rtTMTmp + y * row, m->mem + ((m->t + y) * m->w + m->l) * m->bpp, row);
    RtRec* rec = rtAlloc(9, bytes); rec->kind = 7; rec->op = 304;
    DWORD* A = rtArgs(rec); BYTE* P = rtPayload(rec); DWORD po = 0;
    A[0] = m->surf; A[1] = m->l; A[2] = m->t; A[3] = m->r; A[4] = m->b; A[5] = m->bpp;
    A[6] = rtBytes(P, &po, (DWORD)(ULONG_PTR)g_rtTMTmp, bytes);
    A[7] = (DWORD)(ULONG_PTR)g_rtO_surf[13]; A[8] = (DWORD)(ULONG_PTR)g_rtO_surf[14];
    rtTouch(m->surf); rtCommit(rec, po);
    m->locked = 0;
}
static RtTexMir* rtTMAdopt(DWORD surf, bool allow16 = false) {   // allow16: the terrain atlas path (16-bit formats, mip-mapped textures)
    if (rtTMRefused(surf)) { g_rtNTMNoHit++; return NULL; }        // refused before: no second wait for the queue on its account
    if (rtTMThrashes(surf)) { rtTMRefuse(surf); return NULL; }     // its mirror keeps being dropped by locks from elsewhere: each adoption is a full read for nothing
    int slot = -1;
    for (int i = 0; i < RT_TMIR; ++i) if (!g_rtTM[i].live) { slot = i; break; }
    if (!g_rtTMTmp) g_rtTMTmp = (BYTE*)VirtualAlloc(NULL, 512 * 512 * 4, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (slot < 0 || !g_rtTMTmp) { if (slot < 0) g_rtNTMNoSlot++; return NULL; }
    BYTE desc[32];
    if ((LONG)((RtS2)g_rtO_surf[12])((void*)(ULONG_PTR)surf, (DWORD)(ULONG_PTR)desc) < 0) return NULL;
    const DWORD* d = (const DWORD*)desc;                    // Format Type Usage Pool MSType MSQuality Width Height
    DWORD bpp = (d[0] == 21 || d[0] == 22) ? 4 : ((allow16 && d[0] >= 23 && d[0] <= 26) ? 2 : 0);      // A8R8G8B8 / X8R8G8B8; for the terrain atlas also the 16-bit formats
    if (d[3] != 1 || !bpp || d[2] != 0 || !d[6] || !d[7] || d[6] > 512 || d[7] > 512) return NULL;
    RtTexMir& m = g_rtTM[slot];
    { DWORD need = d[6] * d[7] * bpp;                        // the mirror is as large as the level, kept for the slot's next texture if it fits
      if (m.cap < need) { if (m.mem) VirtualFree(m.mem, 0, MEM_RELEASE); m.mem = (BYTE*)VirtualAlloc(NULL, need, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE); m.cap = m.mem ? need : 0; }
      if (!m.mem) return NULL; }
    rtDrain(); EnterCriticalSection(&g_rtExecCs); g_rtDirectScope++;
    bool ok = false; void* tex = NULL; DWORD why = 1, levels = 0;
    if ((LONG)((DWORD(__stdcall*)(void*, const GUID*, void**))g_rtO_surf[11])((void*)(ULONG_PTR)surf, &kRtIIDTexture9, &tex) >= 0 && tex) {   // GetContainer: +1 ref kept
        levels = ((DWORD(__stdcall*)(void*))(*(void***)tex)[13])(tex);                                                                 // GetLevelCount
        why = 2;
        if (levels == 1 || (allow16 && levels > 1)) {                                                                                  // the atlas is mip-mapped: only its level 0 is ever locked by the game
            why = 3;
            struct { INT pitch; void* bits; } lr = { 0, NULL };
            if ((LONG)((DWORD(__stdcall*)(void*, void*, void*, DWORD))g_rtO_surf[13])((void*)(ULONG_PTR)surf, &lr, NULL, 0x10 | 0x800) >= 0) {  // READONLY
                if (lr.bits && lr.pitch >= (INT)(d[6] * bpp)) {
                    for (DWORD y = 0; y < d[7]; ++y) memcpy(m.mem + y * d[6] * bpp, (BYTE*)lr.bits + (INT)y * lr.pitch, d[6] * bpp);
                    ok = true;
                }
                ((DWORD(__stdcall*)(void*))g_rtO_surf[14])((void*)(ULONG_PTR)surf);
            }
        }
        if (!ok) ((DWORD(__stdcall*)(void*))g_rtO_tex[2])(tex);
    }
    g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    if (!ok) {
        g_rtNTMFail++; rtTMRefuse(surf);
        static LONG said = 0;
        if (said < 8) { ++said; logf("rt: tex-mirror cannot adopt surface %08X (%ux%u fmt %u, %s path): %s (levels %u) - not asked again.", surf, d[6], d[7], d[0], allow16 ? "atlas" : "radar",
                                     why == 1 ? "not a texture level" : (why == 2 ? "texture has more than one level" : "level 0 could not be read"), levels); }
        return NULL;
    }
    if (levels > 1) { static LONG saidM = 0; if (saidM < 4) { ++saidM; logf("rt: tex-mirror adopted level 0 of a %u-level %ux%u texture (fmt %u); its mip filter is queued from now on.", levels, d[6], d[7], d[0]); } }
    m.surf = surf; m.tex = (DWORD)(ULONG_PTR)tex; m.w = d[6]; m.h = d[7]; m.bpp = bpp; m.lastFrame = g_mkFrames;
    m.live = 1; m.dead = 0; m.locked = 0; m.d3d = 0;
    g_rtTMAny = 1; g_rtNTMAdopt++;
    return &m;
}
static __forceinline bool rtTMRadarCaller(DWORD ra) { return ra >= 0x0044C000 && ra < 0x00451000; }
// ---------------------------------------------------------------- the terrain tile atlas
// 0x4EEC82 (terrain, called from 0x4AE3CD) locks level 0 of a MANAGED 512x512 A1R5G5B5 texture in full, read-write,
// about every third battle frame and copies the tiles that changed into it; the others keep what they had. The
// texture is drawn with every frame, so that lock always waited for the whole queue (~2 ms). It is served from a CPU
// mirror instead - same rule as the radar's: one synchronous read fills the mirror, every later lock returns mirror
// memory (pitch = width * bytes per pixel, which is what that code assumes anyway), and the unlock queues LockRect +
// the rows + UnlockRect, so the texture changes at exactly the point of the queue where it used to. Any other lock
// of the surface or its texture drops the mirror first. Kill switch: AOTR_ATLASMIRROR=0.
// v24 showed how the pages behave: a map has dozens of them, every one is filled once while the map loads (which took
// all the mirror slots for pages that were then never touched again), and during play only the few pages under the
// camera keep changing. So a page gets a mirror on its SECOND lock within 20 s, not its first, and when no slot is
// free the mirror that has been idle longest (at least 3 s) makes room.
struct RtTMCand { DWORD surf, frame; };
static RtTMCand g_rtTMCand[64]; static int g_rtTMCandI = 0;
static volatile LONG g_rtNTMFirst = 0, g_rtNTMEvict = 0;
static bool rtTMSeenLately(DWORD surf) {
    DWORD now = (DWORD)g_mkFrames;
    for (int i = 0; i < 64; ++i) if (g_rtTMCand[i].surf == surf) { bool lately = (now - g_rtTMCand[i].frame) < 600; g_rtTMCand[i].frame = now; return lately; }
    RtTMCand& c = g_rtTMCand[g_rtTMCandI++ & 63]; c.surf = surf; c.frame = now;
    return false;
}
static void rtTMMakeRoom() {
    for (int i = 0; i < RT_TMIR; ++i) if (!g_rtTM[i].live) return;
    int best = -1; DWORD idle = 90, now = (DWORD)g_mkFrames;
    for (int i = 0; i < RT_TMIR; ++i) { RtTexMir& m = g_rtTM[i]; if (m.live && !m.dead && !m.locked && (now - m.lastFrame) > idle) { idle = now - m.lastFrame; best = i; } }
    if (best >= 0) { g_rtTM[best].dead = 1; g_rtNTMEvict++; rtTMReap(); }
}
static bool rtTMLockD3D(DWORD surf, DWORD flags, INT* pitch, void** bits) {                    // game thread, full-surface IDirect3DSurface9::LockRect
    rtTMReap();
    RtTexMir* m = rtTMFind(surf);
    if (!m) {
        if (rtTMRefused(surf)) { g_rtNTMNoHit++; return false; }
        if (!rtTMSeenLately(surf)) { g_rtNTMFirst++; return false; }                              // first lock in a while: as before (one wait), remembered
        rtTMMakeRoom();
        m = rtTMAdopt(surf, true);
        if (!m) return false;
    }
    if (m->locked) rtTMFlush(m);
    m->lastFrame = g_mkFrames;
    m->l = 0; m->t = 0; m->r = m->w; m->b = m->h; m->locked = 1; m->d3d = (flags & 0x10) ? 2 : 1; g_rtNTMLock++;
    *pitch = (INT)(m->w * m->bpp); *bits = m->mem;
    return true;
}
static bool rtTMUnlockD3D(DWORD surf) {
    for (int i = 0; i < RT_TMIR; ++i) {
        RtTexMir& m = g_rtTM[i];
        if (!m.live || m.surf != surf || !m.locked || !m.d3d) continue;
        bool ro = m.d3d == 2; m.d3d = 0;
        if (ro) m.locked = 0; else rtTMFlush(&m);                                                 // a mirror dropped while locked still delivers the writes
        return true;
    }
    return false;
}
#define RT_TM_NOT ((void*)(ULONG_PTR)1)                          // "not mirrored: run the engine function"
static void* rtTMLockRect(DWORD surf, int* pitch, DWORD l, DWORD t, DWORD r, DWORD b, bool mayAdopt) {   // game thread
    rtTMReap();
    RtTexMir* m = rtTMFind(surf);
    if (!m && mayAdopt) m = rtTMAdopt(surf);
    if (!m) return RT_TM_NOT;
    if (m->locked) rtTMFlush(m);
    m->lastFrame = g_mkFrames;
    if (r <= l || b <= t || r > m->w || b > m->h) { m->dead = 1; g_rtNTMDrop++; return RT_TM_NOT; }   // odd rectangle: the driver decides, so drop the mirror
    m->l = l; m->t = t; m->r = r; m->b = b; m->locked = 1; g_rtNTMLock++;
    if (pitch) *pitch = (int)(m->w * m->bpp);
    return m->mem + (t * m->w + l) * m->bpp;
}
static void* rtTMLockAll(DWORD surf, int* pitch) {
    RtTexMir* m = rtTMFind(surf);
    if (!m) return RT_TM_NOT;
    if (m->locked) rtTMFlush(m);
    m->lastFrame = g_mkFrames;
    m->l = 0; m->t = 0; m->r = m->w; m->b = m->h; m->locked = 1; g_rtNTMLock++;
    if (pitch) *pitch = (int)(m->w * m->bpp);
    return m->mem;
}
static bool rtTMUnlock(DWORD surf) {
    for (int i = 0; i < RT_TMIR; ++i) {                          // a mirror dropped while locked still delivers the engine writes
        RtTexMir& m = g_rtTM[i];
        if (m.live && m.surf == surf && (m.locked || !m.dead)) { if (m.locked) rtTMFlush(&m); return true; }
    }
    return false;
}
static bool rtTMClear(DWORD surf, DWORD white, bool mayAdopt) {
    rtTMReap();
    RtTexMir* m = rtTMFind(surf);
    if (!m && mayAdopt) m = rtTMAdopt(surf);
    if (!m) return false;
    if (m->locked) rtTMFlush(m);
    memset(m->mem, (BYTE)white ? 0xFF : 0x00, m->w * m->h * m->bpp);                              // every byte of every row, as 0x516130 fills
    m->l = 0; m->t = 0; m->r = m->w; m->b = m->h; m->locked = 1; m->lastFrame = g_mkFrames; g_rtNTMLock++;
    rtTMFlush(m);
    return true;
}
static void* __fastcall hkSurfLockRect(DWORD* sc, void* edx, int* pitch, DWORD l, DWORD t, DWORD r, DWORD b) {
    if (sc && sc[0] && rtTMGameThread()) {
        void* p = rtTMLockRect(sc[0], pitch, l, t, r, b, rtTMRadarCaller((DWORD)(ULONG_PTR)_ReturnAddress()));
        if (p != RT_TM_NOT) return p;
    }
    return o_surfLockRect(sc, edx, pitch, l, t, r, b);
}
static void* __fastcall hkSurfLockAll(DWORD* sc, void* edx, int* pitch, DWORD discard) {
    if (sc && sc[0] && rtTMGameThread()) { void* p = rtTMLockAll(sc[0], pitch); if (p != RT_TM_NOT) return p; }
    if (__readfsdword(0x24) == g_rtMainTid) { g_rtSurfLockCaller = (DWORD)(ULONG_PTR)_ReturnAddress(); void* r = o_surfLockAll(sc, edx, pitch, discard); g_rtSurfLockCaller = 0; return r; }
    return o_surfLockAll(sc, edx, pitch, discard);
}
static void __fastcall hkSurfUnlock(DWORD* sc, void* edx) {
    if (sc && sc[0] && rtTMGameThread() && rtTMUnlock(sc[0])) return;
    o_surfUnlock(sc, edx);
}
static void __fastcall hkSurfClear(DWORD* sc, void* edx, DWORD white) {
    if (sc && sc[0] && rtTMGameThread() && rtTMClear(sc[0], white, rtTMRadarCaller((DWORD)(ULONG_PTR)_ReturnAddress()))) return;
    o_surfClear(sc, edx, white);
}
static void rtTMPixel(DWORD surf, DWORD x, DWORD y, DWORD v, DWORD mode) {                          // mirror side of a queued pixel write
    RtTexMir* m = rtTMFind(surf);
    if (!m || x >= m->w || y >= m->h) return;
    BYTE* p = m->mem + (y * m->w + x) * 4;
    if (mode == 4) *(DWORD*)p = v;
    else if (mode == 0x100) p[3] = (BYTE)v;
    else if (mode == 1) p[0] = (BYTE)v;
    else if (mode == 2) *(WORD*)p = (WORD)v;
}
static void rtInstallTexMirrors() {
    static const BYTE kLockAll[]  = {0x8B,0x01,0x83,0xEC,0x08,0x85,0xC0};
    static const BYTE kLockRect[] = {0x83,0xEC,0x18,0x8B,0x44,0x24,0x24};
    static const BYTE kUnlock[]   = {0x8B,0x01,0x8B,0x08,0x50,0xFF,0x51,0x38};
    static const BYTE kClear[]    = {0x83,0xEC,0x20,0x57,0x8B,0xF9,0x83,0x3F,0x00};
    static const BYTE kFill[]     = {0x8A,0xD0,0x8A,0xDA,0x8A,0xFB};                                // mov dl,al .. (row fill bytes)
    __try {
        if (memcmp((void*)0x00516030, kLockAll, sizeof(kLockAll)) || memcmp((void*)0x00516090, kLockRect, sizeof(kLockRect)) ||
            memcmp((void*)0x00516110, kUnlock, sizeof(kUnlock)) || memcmp((void*)0x00516130, kClear, sizeof(kClear))) {
            logf("rt: SurfaceClass lock functions differ - radar textures stay synchronous."); return;
        }
        (void)kFill;
    } __except (EXCEPTION_EXECUTE_HANDLER) { return; }
    o_surfLockAll  = (tSurfLockAll)makeTrampoline((BYTE*)0x00516030, 5);
    o_surfLockRect = (tSurfLockRect)makeTrampoline((BYTE*)0x00516090, 7);
    o_surfUnlock   = (tSurfUnlockFn)makeTrampoline((BYTE*)0x00516110, 5);
    o_surfClear    = (tSurfClearFn)makeTrampoline((BYTE*)0x00516130, 6);
    if (!o_surfLockAll || !o_surfLockRect || !o_surfUnlock || !o_surfClear) return;
    HANDLE fz[256]; int nf = 0;
    suspendOthers(fz, &nf, 256);
    patchJmp((BYTE*)0x00516030, (void*)&hkSurfLockAll, 5);
    patchJmp((BYTE*)0x00516090, (void*)&hkSurfLockRect, 7);
    patchJmp((BYTE*)0x00516110, (void*)&hkSurfUnlock, 5);
    patchJmp((BYTE*)0x00516130, (void*)&hkSurfClear, 6);
    resumeAll(fz, nf);
    logf("rt: radar overlay textures get CPU mirrors (SurfaceClass Lock/Unlock/Clear 0x516030/0x516090/0x516110/0x516130).");
}
