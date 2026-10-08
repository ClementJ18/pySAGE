// ================================================================ per-draw parameter writes, generated instead of walked
// What the engine does per draw (render list draw 0x54A1F0 -> wrapper commit -> 0x550DF6 -> 0x552BD0): it walks a
// list of parameter-binding objects and dispatches through each one to set three effect parameters. A battle capture
// (2026-09-18) showed that every draw in both passes makes the same three writes and that every byte of them comes
// from one of two places:
//     SetInt(hMode, mode)                  - a constant for that mesh
//     SetRawValue(hSkin, 0, 32 * bones)    - each 32-byte block is either the mesh transform as a quaternion plus
//                                            position, or a verbatim copy of one skeleton pivot
//     SetMatrixTranspose(hWorld, 64)       - the mesh transform with (0,0,0,1) appended, or the identity matrix for
//                                            a skinned mesh whose vertices already sit in bone space, or the
//                                            container transform; which one it is gets learned, not assumed
// Checked over 630,000 blocks in a battle: not one came from anywhere else, and where the payload was generated it
// matched the engine byte for byte 709,000 times, with the quaternion formula in dgQuat (proved bit-exact against
// 2,200 captured draws in src/quat_test.cpp).
//
// So the walk is replaced: 0x552BD0 is hooked, and for a mesh whose recipe is learned and proven the three writes are
// emitted directly - one quaternion and a memcpy per bone - instead of walking bindings and dispatching per
// parameter. Everything around it is untouched: the wrapper still flushes render state before and still calls
// CommitChanges after, and the writes go through the ordinary effect hooks, so batching, de-duplication and queue
// order are exactly what they were.
//
// Safety. A recipe is learned from one draw of that mesh and must reproduce the engine four more times before it is
// trusted. Afterwards one generated draw in 32 still runs the engine and is compared, so a recipe that drifts is
// caught within a frame or two; any mismatch drops that mesh for good, and 64 mismatches in a session switch
// generation off. A mesh with no recipe, a changed effect, a changed pass or a changed payload shape goes through the
// engine. AOTR_DRAWGEN=0 disables it; AOTR_DRAWGEN=2 keeps proving without generating.

#include <math.h>

#define DG_TRACE_MAX 24
struct DgRec { WORD slot, nb; DWORD fx, h; BYTE v[96]; };
static DgRec g_dgT[DG_TRACE_MAX];
static LONG g_dgN = 0;
static volatile LONG g_dgTracing = 0, g_dgOn = 0, g_dgLive = 0, g_dgDepth = 0;
static DWORD g_dgMesh = 0;                                   // the mesh the render list is drawing right now
static volatile LONG g_dgSeen = 0, g_dgDraws = 0, g_dgGenerated = 0, g_dgVerified = 0, g_dgWrong = 0;
static volatile LONG g_dgLearned = 0, g_dgDropped = 0, g_dgFull = 0, g_dgSkip[6];
static volatile LONG g_dgBlocks[3], g_dgMatKind[3], g_dgMatUnknown = 0;

static __forceinline void dgTraceAdd(DWORD slot, void* fx, DWORD h, const void* v, DWORD nb) {
    if (!g_dgTracing) return;
    if (g_dgN >= DG_TRACE_MAX) { g_dgN = DG_TRACE_MAX + 1; return; }
    DgRec& r = g_dgT[g_dgN++];
    r.slot = (WORD)slot; r.nb = (WORD)(nb > 96 ? 96 : nb); r.fx = (DWORD)(ULONG_PTR)fx; r.h = h;
    if (v && r.nb) memcpy(r.v, v, r.nb);
}
// the engine's own matrix-to-quaternion conversion, bit for bit
static void dgQuat(const float* m, float* q) {
    const float m00 = m[0], m01 = m[1], m02 = m[2];
    const float m10 = m[4], m11 = m[5], m12 = m[6];
    const float m20 = m[8], m21 = m[9], m22 = m[10];
    float tr = m00 + m11 + m22;
    if (tr > 0.0f) {
        float s = sqrtf(tr + 1.0f);
        q[3] = s * 0.5f; s = 0.5f / s;
        q[0] = (m21 - m12) * s; q[1] = (m02 - m20) * s; q[2] = (m10 - m01) * s;
    } else {
        int i = 0;
        if (m11 > m00) i = 1;
        if (m22 > (i == 0 ? m00 : m11)) i = 2;
        const float M[3][3] = { { m00, m01, m02 }, { m10, m11, m12 }, { m20, m21, m22 } };
        int j = (i + 1) % 3, k = (i + 2) % 3;
        float s = sqrtf(M[i][i] - (M[j][j] + M[k][k]) + 1.0f);
        q[i] = s * 0.5f; s = 0.5f / s;
        q[3] = (M[k][j] - M[j][k]) * s; q[j] = (M[j][i] + M[i][j]) * s; q[k] = (M[k][i] + M[i][k]) * s;
    }
}
static void dgPredict(DWORD mesh, float* raw32, float* mat64) {
    const float* m = (const float*)(ULONG_PTR)(mesh + 0x18);
    dgQuat(m, raw32);
    raw32[4] = m[3]; raw32[5] = m[7]; raw32[6] = m[11]; raw32[7] = 0.0f;
    for (int i = 0; i < 12; ++i) mat64[i] = m[i];
    mat64[12] = 0.0f; mat64[13] = 0.0f; mat64[14] = 0.0f; mat64[15] = 1.0f;
}
#define DG_MAT_MESHXF   0
#define DG_MAT_IDENTITY 1
#define DG_MAT_CONTXF   2
#define DG_MAT_NONE     3
#define DG_SRC_UNKNOWN 0
#define DG_SRC_MESHXF  1
#define DG_SRC_PIVOT   2
static __forceinline bool dgReadable(DWORD a, DWORD n) { return a >= 0x10000 && !IsBadReadPtr((void*)(ULONG_PTR)a, n); }
static DWORD dgPivots(DWORD mesh, DWORD* count) {            // the container skeleton, whose pivots hold the bone transforms
    *count = 0;
    if (!dgReadable(mesh + 0x80, 4)) return 0;
    DWORD cont = *(DWORD*)(ULONG_PTR)(mesh + 0x7C);
    if (!cont || !dgReadable(cont + 0xFC, 4)) return 0;
    DWORD ht = *(DWORD*)(ULONG_PTR)(cont + 0xF8);
    if (!ht || !dgReadable(ht + 0x18, 4)) return 0;
    DWORD n = *(DWORD*)(ULONG_PTR)(ht + 0x10), piv = *(DWORD*)(ULONG_PTR)(ht + 0x14);
    if (!piv || n == 0 || n > 512 || !dgReadable(piv, n * 0x58)) return 0;
    *count = n;
    return piv;
}
static int dgBlockSource(const BYTE* blk, const float* raw, DWORD piv, DWORD npiv, int* pivotIndex) {
    for (DWORD k = 0; k < npiv; ++k)                          // pivots first: where both fit, only the pivot keeps fitting
        if (!memcmp(blk, (const BYTE*)(ULONG_PTR)(piv + k * 0x58 + 48), 28)) { *pivotIndex = (int)k; return DG_SRC_PIVOT; }
    if (!memcmp(blk, raw, 28)) return DG_SRC_MESHXF;
    return DG_SRC_UNKNOWN;
}
// ---- one recipe per mesh
// Per model does not work: the same geometry hangs off different bones depending on the skeleton it is attached to,
// so one model can need different bone indices (a battle dropped 898 models that way). A mesh keeps its bones for as
// long as it lives, and everything on screen is drawn every frame, so the table is warm after a single frame.
#define DG_MESH 65536
#define DG_BLOCKS 16
#define DG_MESHXF 0xFF
struct DgMeshRec { DWORD mesh, model, fx, hMat, hRaw, hInt, mode, pass, key; WORD nb; BYTE matSrc; BYTE src[DG_BLOCKS]; LONG ok, bad, fails; };
static DgMeshRec* g_dgM = NULL;                // committed at install
static __forceinline DgMeshRec* dgMeshSlot(DWORD mesh, DWORD fx, DWORD pass, DWORD key, bool create) {
    if (!g_dgM) return NULL;
    DWORD h = ((mesh * 2654435761u) ^ (fx * 2246822519u) ^ (pass * 3266489917u) ^ (key * 668265263u)) >> 16;
    DgMeshRec* spare = NULL;
    for (int i = 0; i < 8; ++i) {
        DgMeshRec& e = g_dgM[(h + i) & (DG_MESH - 1)];
        if (e.mesh == mesh && e.fx == fx && e.pass == pass && e.key == key) return &e;
        if (!e.mesh) { if (!create) return NULL; memset(&e, 0, sizeof(e)); e.mesh = mesh; e.fx = fx; e.pass = pass; e.key = key; return &e; }
        if (!spare || e.ok < spare->ok) spare = &e;
    }
    if (!create) return NULL;
    g_dgFull++;                                              // every probe taken: the least used of them makes room
    memset(spare, 0, sizeof(*spare)); spare->mesh = mesh; spare->fx = fx; spare->pass = pass; spare->key = key;
    return spare;
}
static void dgMatrixOf(int src, DWORD mesh, const float* meshMat, float* mat) {
    if (src == DG_MAT_MESHXF) { memcpy(mat, meshMat, 64); return; }
    memset(mat, 0, 64);
    mat[0] = 1.0f; mat[5] = 1.0f; mat[10] = 1.0f; mat[15] = 1.0f;          // a skinned mesh sits in bone space: identity
    if (src != DG_MAT_CONTXF) return;
    DWORD cont = dgReadable(mesh + 0x80, 4) ? *(DWORD*)(ULONG_PTR)(mesh + 0x7C) : 0;
    if (cont && dgReadable(cont + 0x18 + 48, 4)) {
        memcpy(mat, (const void*)(ULONG_PTR)(cont + 0x18), 48);
        mat[12] = 0.0f; mat[13] = 0.0f; mat[14] = 0.0f; mat[15] = 1.0f;
    }
}
static bool dgBuild(const DgMeshRec* e, DWORD mesh, BYTE* out, float* mat) {
    float raw[8], meshMat[16];
    dgPredict(mesh, raw, meshMat);
    dgMatrixOf(e->matSrc, mesh, meshMat, mat);
    DWORD npiv = 0, piv = 0;
    int blocks = (int)(e->nb / 32);
    for (int i = 0; i < blocks; ++i) {
        BYTE* d = out + i * 32;
        if (e->src[i] == DG_MESHXF) { memcpy(d, raw, 32); continue; }
        if (!piv) { piv = dgPivots(mesh, &npiv); if (!piv) return false; }
        DWORD k = e->src[i];
        if (k >= npiv) return false;
        memcpy(d, (const BYTE*)(ULONG_PTR)(piv + k * 0x58 + 48), 28);
        *(DWORD*)(d + 28) = 0;                               // the word the engine leaves behind the position
    }
    return true;
}
// ---- emitting the three writes ourselves, through the ordinary effect hooks
typedef DWORD (__stdcall* tFxSetInt)(void*, DWORD, DWORD);
typedef DWORD (__stdcall* tFxSetRaw)(void*, DWORD, DWORD, DWORD, DWORD);
typedef DWORD (__stdcall* tFxSetMat)(void*, DWORD, DWORD);
static void dgEmit(const DgMeshRec* e, DWORD fx, const BYTE* payload, const float* mat) {
    void** vt = *(void***)(ULONG_PTR)fx;
    ((tFxSetInt)vt[26])((void*)(ULONG_PTR)fx, e->hInt, e->mode);
    ((tFxSetRaw)vt[78])((void*)(ULONG_PTR)fx, e->hRaw, (DWORD)(ULONG_PTR)payload, 0, e->nb);
    ((tFxSetMat)vt[44])((void*)(ULONG_PTR)fx, e->hMat, (DWORD)(ULONG_PTR)mat);
}
// learn from, or check against, what the engine just wrote for this draw
static void dgLearnOrCheck(DWORD mesh, DWORD fx, DWORD pass, DWORD key, const BYTE* gen, const float* mat, bool built) {
    g_dgDraws++;
    if (g_dgN != 3) { g_dgSkip[4]++; return; }
    DgRec& a = g_dgT[0]; DgRec& b = g_dgT[1]; DgRec& c = g_dgT[2];
    if (a.slot != 26 || b.slot != 78 || c.slot != 44 || c.nb != 64 || !b.nb || b.nb > DG_BLOCKS * 32) { g_dgSkip[4]++; return; }
    DWORD model = dgReadable(mesh + 0xC8, 4) ? *(DWORD*)(ULONG_PTR)(mesh + 0xC4) : 0;
    DgMeshRec* e = dgMeshSlot(mesh, fx, pass, key, true);
    if (!e) { g_dgSkip[1]++; return; }
    if (e->model && e->model != model) { memset(e, 0, sizeof(*e)); e->mesh = mesh; }        // the address was reused
    if (e->bad) { g_dgSkip[2]++; return; }
    if (!e->nb) {                                                                           // first draw: learn the recipe
        float raw[8], m2[16];
        dgPredict(mesh, raw, m2);
        DWORD npiv = 0, piv = dgPivots(mesh, &npiv);
        int blocks = (int)(b.nb / 32);
        for (int i = 0; i < blocks; ++i) {
            int pk = -1;
            int src = dgBlockSource(b.v + i * 32, raw, piv, npiv, &pk);
            g_dgBlocks[src]++;
            if (src == DG_SRC_MESHXF) e->src[i] = DG_MESHXF;
            else if (src == DG_SRC_PIVOT && pk < 254) e->src[i] = (BYTE)pk;
            else { e->bad = 1; g_dgDropped++; g_dgSkip[2]++; return; }
        }
        int msrc = DG_MAT_NONE;
        for (int cand = DG_MAT_MESHXF; cand <= DG_MAT_CONTXF; ++cand) {
            float test[16];
            dgMatrixOf(cand, mesh, m2, test);
            if (!memcmp(test, c.v, 64)) { msrc = cand; break; }
        }
        if (msrc == DG_MAT_NONE) { e->bad = 1; g_dgDropped++; g_dgMatUnknown++; g_dgSkip[2]++; return; }
        e->matSrc = (BYTE)msrc; g_dgMatKind[msrc]++;
        e->model = model; e->mode = *(DWORD*)a.v; e->nb = b.nb;
        e->hInt = a.h; e->hRaw = b.h; e->hMat = c.h;
        g_dgLearned++; g_dgSkip[3]++; return;
    }
    if (e->fx != a.fx || e->mode != *(DWORD*)a.v || e->nb != b.nb || e->hRaw != b.h || e->hMat != c.h || e->hInt != a.h) {
        if (++e->fails >= 4) { e->bad = 1; g_dgDropped++; }                                 // it draws in more than one shape
        g_dgSkip[5]++; return;
    }
    BYTE own[DG_BLOCKS * 32]; float ownMat[16];
    const BYTE* mine = gen; const float* mineMat = mat;
    if (!built) {
        if (!dgBuild(e, mesh, own, ownMat)) { e->bad = 1; g_dgDropped++; g_dgSkip[2]++; return; }
        mine = own; mineMat = ownMat;
    }
    if (memcmp(mine, b.v, e->nb) || memcmp(mineMat, c.v, 64)) {
        g_dgWrong++;
        e->bad = 1; g_dgDropped++;
        if (g_dgWrong <= 6) {
            int blk = -1;
            for (int i = 0; i < (int)(e->nb / 32); ++i) if (memcmp(mine + i * 32, b.v + i * 32, 32)) { blk = i; break; }
            logf("drawgen: a recipe did not reproduce the payload - mesh %08X model %08X, %u blocks, mode %u | first wrong block %d (recipe says %s) | matrix %s - that mesh is left to the engine.",
                 mesh, model, e->nb / 32, e->mode, blk, blk < 0 ? "-" : (e->src[blk] == DG_MESHXF ? "the mesh transform" : "a pivot"),
                 memcmp(mineMat, c.v, 64) ? "differs" : "matches");
        }
        if (g_dgWrong >= 64 && g_dgLive) { g_dgLive = 0; logf("drawgen: 64 recipes went wrong - generation is off for this session."); }
        return;
    }
    e->ok++; g_dgVerified++;
}
// ---- the hook: the engine function that walks the parameter bindings
typedef DWORD (__fastcall* tDgApply)(void*, void*, DWORD, DWORD);
static tDgApply o_dgApply = NULL;
static DWORD __fastcall dgApply(void* self, void* edx, DWORD pass, DWORD key) {
    DWORD mesh = g_dgMesh;
    if (!g_dgOn || !mesh || g_dgDepth || __readfsdword(0x24) != g_mkTid || !dgReadable((DWORD)(ULONG_PTR)self, 12))
        return o_dgApply(self, edx, pass, key);
    DWORD fx = *(DWORD*)self;
    DgMeshRec* e = dgMeshSlot(mesh, fx, pass, key, false);
    BYTE gen[DG_BLOCKS * 32]; float mat[16]; bool built = false;
    bool ready = g_dgLive && e && !e->bad && e->nb && e->ok >= 4 && dgReadable(fx, 4);
    if (ready) {
        __try { built = dgBuild(e, mesh, gen, mat); } __except (EXCEPTION_EXECUTE_HANDLER) { built = false; }
        if (built && ((++g_dgSeen & 31) != 0)) {                                            // generated; one draw in 32 still goes to the engine and is compared
            dgEmit(e, fx, gen, mat);
            g_dgGenerated++;
            return 0;
        }
    }
    g_dgDepth++; g_dgN = 0; g_dgTracing = 1;
    DWORD r = o_dgApply(self, edx, pass, key);
    g_dgTracing = 0; g_dgDepth--;
    __try { dgLearnOrCheck(mesh, fx, pass, key, gen, mat, built); } __except (EXCEPTION_EXECUTE_HANDLER) { g_dgSkip[0]++; }
    return r;
}
static void installDrawGen() {
    static const BYTE kApply[] = { 0x55, 0x8B, 0xEC, 0x53, 0x57, 0x8B, 0xD9 };              // 0x552BD0: push ebp; mov ebp,esp; push ebx; push edi; mov ebx,ecx
    char env[8]; env[0] = 0;
    // OFF by default. In a battle 99% of recipes reproduced the engine exactly, but the remaining 1% did not, and a
    // wrong recipe is visible: geometry tore across the screen until the checks dropped those meshes. Proving four
    // draws does not establish that a recipe stays right - a mesh can change bones later - so the only safe version
    // checks every draw, which costs more than the walk it replaces. The measured prize was about 2 ms a frame.
    // AOTR_DRAWGEN=1 generates (unsafe), =2 proves without generating, anything else leaves the engine alone.
    LONG want = 0;
    if (GetEnvironmentVariableA("AOTR_DRAWGEN", env, sizeof(env))) { if (env[0] == '1') want = 1; else if (env[0] == '2') want = 2; }
    if (!want) { logf("drawgen: off - the per-draw generator is not installed (AOTR_DRAWGEN=1 would generate, =2 would prove)."); return; }
    bool ok = false;
    __try { ok = !memcmp((void*)0x00552BD0, kApply, sizeof(kApply)); } __except (EXCEPTION_EXECUTE_HANDLER) { ok = false; }
    if (!ok) { logf("drawgen: the parameter-binding walk differs from the analysed build - off."); return; }
    g_dgM = (DgMeshRec*)VirtualAlloc(NULL, (SIZE_T)DG_MESH * sizeof(DgMeshRec), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!g_dgM) { logf("drawgen: recipe table allocation failed - off."); return; }
    o_dgApply = (tDgApply)makeTrampoline((BYTE*)0x00552BD0, 5);
    if (!o_dgApply) { logf("drawgen: no trampoline - off."); return; }
    HANDLE fz[256]; int nf = 0;
    suspendOthers(fz, &nf, 256);
    patchJmp((BYTE*)0x00552BD0, (void*)&dgApply, 5);
    resumeAll(fz, nf);
    g_dgOn = 1; g_dgLive = (want == 1) ? 1 : 0;
    logf("drawgen: %s - the three per-draw effect parameters are built from the mesh transform and its skeleton pivots; a recipe is learned per mesh, has to reproduce the engine four times, and one generated draw in 32 is still checked.",
         g_dgLive ? "LIVE (the binding walk is replaced once a recipe is proven)" : "proving only (AOTR_DRAWGEN=2)");
}
static void dgReport(LONG f) {
    if (!g_dgOn || f <= 0) return;
    static LONG lG = 0, lV = 0, lD = 0;
    LONG g = g_dgGenerated, v = g_dgVerified, d = g_dgDraws;
    char a1[16], a2[16], a3[16];
    logf("drawgen: %s | generated/f %s | checked against the engine/f %s | engine draws/f %s | recipes %d, dropped %d, wrong %d, slots reused %d | blocks learned: transform %d, pivot %d, unknown %d | world matrix: mesh %d, identity %d, container %d, unknown %d | not generated: fault %d, no slot %d, dropped %d, learning %d, odd shape %d, changed %d",
         g_dgLive ? "live" : "proving", perStr(g - lG, f, a1), perStr(v - lV, f, a2), perStr(d - lD, f, a3),
         (int)g_dgLearned, (int)g_dgDropped, (int)g_dgWrong, (int)g_dgFull,
         (int)g_dgBlocks[DG_SRC_MESHXF], (int)g_dgBlocks[DG_SRC_PIVOT], (int)g_dgBlocks[DG_SRC_UNKNOWN],
         (int)g_dgMatKind[DG_MAT_MESHXF], (int)g_dgMatKind[DG_MAT_IDENTITY], (int)g_dgMatKind[DG_MAT_CONTXF], (int)g_dgMatUnknown,
         (int)g_dgSkip[0], (int)g_dgSkip[1], (int)g_dgSkip[2], (int)g_dgSkip[3], (int)g_dgSkip[4], (int)g_dgSkip[5]);
    lG = g; lV = v; lD = d;
}
