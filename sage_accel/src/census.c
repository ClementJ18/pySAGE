/*
 * census.c - milestone M1 of sage_patch/docs/accel-module.md: count the renderer's calls without
 * changing any of them, and say what a render thread would cost.
 *
 * Derived, with his permission, from OH1A's bfme2_accel.dll. The queued/drain split counted here is
 * his (sage_patch/docs/accel-queue.md): a render thread queues a device call whose result nobody
 * reads, and makes every other call wait until the worker has drained the queue. That wait is a
 * *stall* only when something was queued since the last one, so a stall is counted exactly then:
 * a draining call, or a lock, made while the queue would be non-empty. Stalls per frame is the
 * number that decides whether M2 is worth building.
 *
 * Hooks are vtable patches, like the original's: the device's, one ID3DXEffect's and the lock
 * slots of textures, surfaces and vertex/index buffers. COM identity and reference counts are
 * untouched. Device and effect slots go through small generated thunks (count, then tail-jump
 * to the original); Present, CreateDevice and the four locks are C, because they need their
 * arguments.
 */

#include "accel.h"

#include <mmsystem.h>

#include "vtables.h"

#define REPORT_SECONDS 30
#define TOP_N 12

/* Lock kinds, and how a lock's flags classify it. */
enum { LOCK_TEXTURE, LOCK_SURFACE, LOCK_VB, LOCK_IB, LOCK_KINDS };
enum { LF_DISCARD, LF_NOOVERWRITE, LF_READONLY, LF_OTHER, LOCK_FLAG_CLASSES };
static const char *const lock_kind_names[LOCK_KINDS] = {"texture", "surface", "vb", "ib"};

/* A class may have more than one vtable (pool, usage); each hooked one keeps its own original. */
#define MAX_VTABLES 4
struct lock_hook {
    void **vtbl[MAX_VTABLES];
    void *orig[MAX_VTABLES];
    int count;
};

/* Counters. Game-thread counters are only written by the game thread; `foreign` ones by any
 * thread, so atomically. Reports diff them against the previous report's copy. */
struct counters {
    LONG device[DEVICE_SLOTS];
    LONG device_foreign[DEVICE_SLOTS];
    LONG device_stall[DEVICE_SLOTS];
    LONG effect[EFFECT_SLOTS];
    LONG effect_foreign[EFFECT_SLOTS];
    LONG lock[LOCK_KINDS][LOCK_FLAG_CLASSES];
    LONG lock_stall[LOCK_KINDS];
    LONG lock_foreign[LOCK_KINDS];
    LONG stalls;
    LONG frames;
};

static struct counters g_now, g_then;
static volatile unsigned char g_dirty; /* something would be queued since the last stall */

/* The device is hooked in place, in d3d9's own vtable. On the Edain machine that table is a heap
 * copy made by the Windows compatibility shim (apphelp.dll), whose own hooks - QueryInterface and
 * Reset at least - find their saved originals by the device's vtable pointer. So the pointer must
 * never change: giving the device a table of ours made apphelp's Reset call a null original.
 * The shim also rewrites its table on Reset, undoing our entries; hk_reset and the watchdog put
 * them back. Every thunk jumps through `g_device_orig`, refreshed from the table on each repair,
 * so what the shim installs is what our hooks call. */
static void **g_device_vtbl;
static void *g_device_orig[DEVICE_SLOTS];
static void *g_device_hook[DEVICE_SLOTS];
static LONG g_device_repairs; /* entries put back after something rewrote them */
static void *g_effect_orig[EFFECT_SLOTS];
static void *g_create_device_orig;
static struct lock_hook g_lock_hooks[LOCK_KINDS];
static int g_effect_slots_hooked;

/* Frame accounting, on the game thread's Present. */
static LARGE_INTEGER g_qpf, g_last_present, g_window_start;
static LONG g_stalls_at_last_present, g_window_max_stalls;
static LONGLONG g_window_max_frame;
static LONGLONG g_present_ticks, g_present_ticks_then; /* time inside the real Present */

/* Hitches: a game-thread frame of HITCH_MS or more gets a block of its own in the log, from this
 * frame's counters against the previous Present's. A first-use stutter is one such frame, and a
 * 30-second report would average it away. */
#define HITCH_MS 100
#define MAX_HITCHES 200
static struct counters g_frame_then;
static LONGLONG g_present_ticks_frame_then;
static LONG g_hitches;

/* The sampler: every SAMPLE_MS it stops the game thread just long enough to read its instruction
 * pointer, then - with the thread running again, so no lock it holds can matter - files the sample
 * under the module it falls in. This is what turns M1's counts into time: the share of the game
 * thread spent in d3d9, d3dx9 and the driver is the most a render thread could take off it. */
#define SAMPLE_MS 4
#define MAX_MODULES 64
struct sample_bin {
    UINT_PTR base; /* module base; 0 = no module, 1 = our thunks */
    LONG count, then, frame_then; /* since the last report, since the last Present */
};
static struct sample_bin g_bins[MAX_MODULES];
static LONG g_bin_count;

/* Thunks are emitted into one executable block. */
static unsigned char *g_code;
static SIZE_T g_code_used, g_code_size;

/* Emitting */

static void emit8(unsigned char b)
{
    g_code[g_code_used++] = b;
}

static void emit32(DWORD v)
{
    CopyMemory(g_code + g_code_used, &v, 4);
    g_code_used += 4;
}

static void emit_addr(const volatile void *p)
{
    emit32((DWORD)(UINT_PTR)p);
}

enum { THUNK_QUEUED, THUNK_DRAIN, THUNK_PLAIN };

/*
 * One slot's thunk. A direct method (THUNK_PLAIN) is only counted: it neither fills nor drains the
 * queue. Entered with the method's own stack, so it may use only eax and the flags, both
 * of which a stdcall COM method's caller already treats as clobbered.
 *
 *     mov  eax, fs:[0x24]           ; this thread's id
 *     cmp  eax, [g_game_thread]
 *     jne  foreign
 *     inc  dword [count]
 *   QUEUED:  mov byte [g_dirty], 1
 *   DRAIN:   cmp byte [g_dirty], 0 / je out / mov byte [g_dirty], 0 / inc [stall] / inc [stalls]
 *   out:
 *     jmp  [orig]
 *   foreign:
 *     lock inc dword [foreign]
 *     jmp  [orig]
 */
static void *emit_thunk(int kind, LONG *count, LONG *foreign, LONG *stall, void **orig)
{
    unsigned char *start;
    SIZE_T jne_at, je_at;

    if (g_code_used + 96 > g_code_size)
        return NULL;
    start = g_code + g_code_used;

    emit8(0x64), emit8(0xA1), emit32(0x24);        /* mov eax, fs:[0x24] */
    emit8(0x3B), emit8(0x05), emit_addr(&g_game_thread); /* cmp eax, [g_game_thread] */
    emit8(0x0F), emit8(0x85), jne_at = g_code_used, emit32(0); /* jne foreign */
    emit8(0xFF), emit8(0x05), emit_addr(count);    /* inc dword [count] */

    if (kind == THUNK_QUEUED) {
        emit8(0xC6), emit8(0x05), emit_addr(&g_dirty), emit8(1);
    } else if (kind == THUNK_DRAIN) {
        emit8(0x80), emit8(0x3D), emit_addr(&g_dirty), emit8(0);
        emit8(0x74), je_at = g_code_used, emit8(0);
        emit8(0xC6), emit8(0x05), emit_addr(&g_dirty), emit8(0);
        emit8(0xFF), emit8(0x05), emit_addr(stall);
        emit8(0xFF), emit8(0x05), emit_addr(&g_now.stalls);
        g_code[je_at] = (unsigned char)(g_code_used - (je_at + 1));
    }
    emit8(0xFF), emit8(0x25), emit_addr(orig); /* jmp [orig] */

    {
        DWORD rel = (DWORD)(g_code_used - (jne_at + 4));
        CopyMemory(g_code + jne_at, &rel, 4);
    }
    emit8(0xF0), emit8(0xFF), emit8(0x05), emit_addr(foreign); /* lock inc [foreign] */
    emit8(0xFF), emit8(0x25), emit_addr(orig);                 /* jmp [orig] */
    return start;
}

/* Vtables */

static BOOL same_module(const void *a, const void *b)
{
    HMODULE ma, mb;
    DWORD flags = GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                  GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT;
    if (!GetModuleHandleExA(flags, (LPCSTR)a, &ma) || !GetModuleHandleExA(flags, (LPCSTR)b, &mb))
        return FALSE;
    return ma == mb;
}

static void *patch_slot(void **slot, void *replacement)
{
    DWORD old;
    void *orig = *slot;
    if (!VirtualProtect(slot, sizeof *slot, PAGE_READWRITE, &old))
        return NULL;
    InterlockedExchangePointer(slot, replacement);
    VirtualProtect(slot, sizeof *slot, old, &old);
    return orig;
}

static BOOL readable(const void *p, SIZE_T n)
{
    MEMORY_BASIC_INFORMATION m;
    const DWORD ok = PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READ |
                     PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
    if (VirtualQuery(p, &m, sizeof m) == 0 || m.State != MEM_COMMIT || (m.Protect & ok) == 0 ||
        (m.Protect & PAGE_GUARD) != 0)
        return FALSE;
    return (const char *)p + n <= (const char *)m.BaseAddress + m.RegionSize;
}

static BOOL executable(const void *p)
{
    MEMORY_BASIC_INFORMATION m;
    const DWORD exec = PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
                       PAGE_EXECUTE_WRITECOPY;
    if (VirtualQuery(p, &m, sizeof m) == 0)
        return FALSE;
    return m.State == MEM_COMMIT && (m.Protect & exec) != 0 && (m.Protect & PAGE_GUARD) == 0;
}

/*
 * How many of `slots` can safely be hooked: each must point at executable memory. With
 * `same_module`, each must also sit in the module that holds slot 0 - the guard for a vtable
 * whose length depends on the DLL's version (ID3DXEffect), where a slot past the real end would
 * be whatever follows the vtable.
 *
 * The device is checked without it. On Edain's machine its methods do not all live in d3d9.dll
 * (something rewrites the table at runtime), and its length is fixed by the D3D9 ABI anyway.
 */
static int checked_slots(void **vtbl, int slots, BOOL require_same_module)
{
    int n;
    for (n = 0; n < slots; n++) {
        if (!executable(vtbl[n]))
            break;
        if (require_same_module && n > 0 && !same_module(vtbl[0], vtbl[n]))
            break;
    }
    return n;
}

/* "d3d9.dll+0x1234", or "no module" for memory no DLL owns, for the log. */
static const char *where(char *buf, const void *p)
{
    HMODULE m;
    char path[MAX_PATH], *name = path, *c;
    if (!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            (LPCSTR)p, &m) ||
        GetModuleFileNameA(m, path, MAX_PATH) == 0) {
        wsprintfA(buf, "%08X (no module)", (DWORD)(UINT_PTR)p);
        return buf;
    }
    for (c = path; *c; c++)
        if (*c == '\\' || *c == '/')
            name = c + 1;
    wsprintfA(buf, "%s+0x%X", name, (DWORD)((UINT_PTR)p - (UINT_PTR)m));
    return buf;
}

/* Locks */

static int lock_flag_class(DWORD flags)
{
    if (flags & D3DLOCK_DISCARD)
        return LF_DISCARD;
    if (flags & D3DLOCK_NOOVERWRITE)
        return LF_NOOVERWRITE;
    if (flags & D3DLOCK_READONLY)
        return LF_READONLY;
    return LF_OTHER;
}

static void *lock_orig(int kind, void *object)
{
    struct lock_hook *h = &g_lock_hooks[kind];
    void **vtbl = *(void ***)object;
    int i;
    for (i = 0; i < h->count; i++)
        if (h->vtbl[i] == vtbl)
            return h->orig[i];
    return h->orig[0]; /* unreachable: the hook is only installed in the recorded vtables */
}

static void account_lock(int kind, DWORD flags)
{
    if (GetCurrentThreadId() != g_game_thread) {
        InterlockedIncrement(&g_now.lock_foreign[kind]);
        return;
    }
    g_now.lock[kind][lock_flag_class(flags)]++;
    if (g_dirty) {
        g_dirty = 0;
        g_now.lock_stall[kind]++;
        g_now.stalls++;
    }
}

typedef HRESULT(WINAPI *TexLockFn)(IDirect3DTexture9 *, UINT, D3DLOCKED_RECT *, const RECT *,
                                   DWORD);
typedef HRESULT(WINAPI *SurfLockFn)(IDirect3DSurface9 *, D3DLOCKED_RECT *, const RECT *, DWORD);
typedef HRESULT(WINAPI *BufLockFn)(void *, UINT, UINT, void **, DWORD);

static HRESULT WINAPI hk_texture_lock(IDirect3DTexture9 *self, UINT level, D3DLOCKED_RECT *out,
                                      const RECT *rect, DWORD flags)
{
    account_lock(LOCK_TEXTURE, flags);
    return ((TexLockFn)lock_orig(LOCK_TEXTURE, self))(self, level, out, rect, flags);
}

static HRESULT WINAPI hk_surface_lock(IDirect3DSurface9 *self, D3DLOCKED_RECT *out,
                                      const RECT *rect, DWORD flags)
{
    account_lock(LOCK_SURFACE, flags);
    return ((SurfLockFn)lock_orig(LOCK_SURFACE, self))(self, out, rect, flags);
}

static HRESULT WINAPI hk_vb_lock(void *self, UINT offset, UINT size, void **out, DWORD flags)
{
    account_lock(LOCK_VB, flags);
    return ((BufLockFn)lock_orig(LOCK_VB, self))(self, offset, size, out, flags);
}

static HRESULT WINAPI hk_ib_lock(void *self, UINT offset, UINT size, void **out, DWORD flags)
{
    account_lock(LOCK_IB, flags);
    return ((BufLockFn)lock_orig(LOCK_IB, self))(self, offset, size, out, flags);
}

static void hook_lock_vtable(int kind, void *object, int slot, void *hook)
{
    struct lock_hook *h = &g_lock_hooks[kind];
    void **vtbl;
    int i;

    if (object == NULL)
        return;
    vtbl = *(void ***)object;
    for (i = 0; i < h->count; i++)
        if (h->vtbl[i] == vtbl)
            return;
    if (h->count == MAX_VTABLES || checked_slots(vtbl, slot + 1, TRUE) <= slot)
        return;
    h->vtbl[h->count] = vtbl;
    h->orig[h->count] = vtbl[slot];
    h->count++; /* recorded before the swap, so the hook can always find its original */
    patch_slot(&vtbl[slot], hook);
}

/* One of each resource the engine locks, in each pool it could use, to reach their vtables. Made
 * before the device's own vtable is hooked, so none of this is counted. */
static void hook_resource_locks(IDirect3DDevice9 *dev)
{
    IDirect3DTexture9 *tex = NULL;
    IDirect3DSurface9 *surf = NULL;
    IDirect3DVertexBuffer9 *vb = NULL;
    IDirect3DIndexBuffer9 *ib = NULL;
    static const struct {
        DWORD usage;
        D3DPOOL pool;
    } kinds[] = {
        {0, D3DPOOL_MANAGED},
        {D3DUSAGE_DYNAMIC, D3DPOOL_DEFAULT},
        {0, D3DPOOL_SYSTEMMEM},
    };
    int i, k;

    for (i = 0; i < (int)(sizeof kinds / sizeof kinds[0]); i++) {
        if (SUCCEEDED(IDirect3DDevice9_CreateTexture(dev, 4, 4, 1, kinds[i].usage,
                                                     D3DFMT_A8R8G8B8, kinds[i].pool, &tex,
                                                     NULL))) {
            hook_lock_vtable(LOCK_TEXTURE, tex, TEXTURE_SLOT_LOCK_RECT, (void *)hk_texture_lock);
            if (SUCCEEDED(IDirect3DTexture9_GetSurfaceLevel(tex, 0, &surf))) {
                hook_lock_vtable(LOCK_SURFACE, surf, SURFACE_SLOT_LOCK_RECT,
                                 (void *)hk_surface_lock);
                IDirect3DSurface9_Release(surf);
            }
            IDirect3DTexture9_Release(tex);
        }
        if (SUCCEEDED(IDirect3DDevice9_CreateVertexBuffer(
                dev, 64, kinds[i].usage | D3DUSAGE_WRITEONLY, 0, kinds[i].pool, &vb, NULL))) {
            hook_lock_vtable(LOCK_VB, vb, VERTEX_BUFFER_SLOT_LOCK, (void *)hk_vb_lock);
            IDirect3DVertexBuffer9_Release(vb);
        }
        if (SUCCEEDED(IDirect3DDevice9_CreateIndexBuffer(dev, 64,
                                                         kinds[i].usage | D3DUSAGE_WRITEONLY,
                                                         D3DFMT_INDEX16, kinds[i].pool, &ib,
                                                         NULL))) {
            hook_lock_vtable(LOCK_IB, ib, INDEX_BUFFER_SLOT_LOCK, (void *)hk_ib_lock);
            IDirect3DIndexBuffer9_Release(ib);
        }
    }
    if (SUCCEEDED(IDirect3DDevice9_GetBackBuffer(dev, 0, 0, D3DBACKBUFFER_TYPE_MONO, &surf))) {
        hook_lock_vtable(LOCK_SURFACE, surf, SURFACE_SLOT_LOCK_RECT, (void *)hk_surface_lock);
        IDirect3DSurface9_Release(surf);
    }
    for (k = 0; k < LOCK_KINDS; k++)
        log_line("census: %s locks hooked in %d vtable(s)", lock_kind_names[k],
                 g_lock_hooks[k].count);
}

/* Reporting */

/* `total / frames` to one decimal place, as "12.3". */
static const char *rate(char *buf, LONG total, LONG frames)
{
    ULONGLONG tenths = frames > 0 ? ((ULONGLONG)(DWORD)total * 10 + (DWORD)frames / 2) /
                                        (DWORD)frames
                                  : 0;
    wsprintfA(buf, "%lu.%lu", (DWORD)(tenths / 10), (DWORD)(tenths % 10));
    return buf;
}

/* Up to TOP_N indices of `values` with the largest non-zero entries, largest first. */
static int top(const LONG *values, int n, int *out)
{
    int used = 0, i, j;
    for (i = 0; i < n; i++) {
        if (values[i] <= 0 || (used == TOP_N && values[i] <= values[out[TOP_N - 1]]))
            continue;
        j = used < TOP_N ? used++ : TOP_N - 1;
        for (; j > 0 && values[out[j - 1]] < values[i]; j--)
            out[j] = out[j - 1];
        out[j] = i;
    }
    return used;
}

static void diff(const LONG *now, const LONG *then, LONG *out, int n)
{
    int i;
    for (i = 0; i < n; i++)
        out[i] = (LONG)((DWORD)now[i] - (DWORD)then[i]);
}

/* "name 12.3, name 4.5, ..." for the largest entries of `values`, per frame. */
static void ranked_line(const char *label, const LONG *values, const char *const *names, int n,
                        LONG frames)
{
    char line[1000], num[24];
    int order[TOP_N], shown = top(values, n, order), i;
    int len = wsprintfA(line, "  %s:", label);
    if (shown == 0)
        lstrcatA(line, " none");
    for (i = 0; i < shown && len < 900; i++)
        len += wsprintfA(line + len, "%s %s %s", i ? "," : "", names[order[i]],
                         rate(num, values[order[i]], frames));
    log_line("%s", line);
}

static LONG sum(const LONG *values, int n)
{
    LONG s = 0;
    int i;
    for (i = 0; i < n; i++)
        s += values[i];
    return s;
}

/* File one sample. Only the sampler thread writes bins, so no locking beyond the count. */
static void classify(UINT_PTR eip)
{
    HMODULE m = NULL;
    UINT_PTR base;
    LONG i;

    if (g_code != NULL && eip >= (UINT_PTR)g_code && eip < (UINT_PTR)g_code + g_code_size)
        base = 1;
    else if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                    GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                (LPCSTR)eip, &m))
        base = (UINT_PTR)m;
    else
        base = 0;
    for (i = 0; i < g_bin_count; i++)
        if (g_bins[i].base == base) {
            InterlockedIncrement(&g_bins[i].count);
            return;
        }
    if (g_bin_count < MAX_MODULES) {
        g_bins[g_bin_count].base = base;
        g_bins[g_bin_count].count = 1;
        InterlockedIncrement(&g_bin_count);
    }
}

static DWORD WINAPI sampler(LPVOID unused)
{
    HANDLE thread = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT, FALSE, g_game_thread);
    (void)unused;
    if (thread == NULL) {
        log_line("census: cannot open the game thread for sampling (error %lu)", GetLastError());
        return 0;
    }
    timeBeginPeriod(1);
    for (;;) {
        CONTEXT context;
        BOOL ok;
        Sleep(SAMPLE_MS);
        context.ContextFlags = CONTEXT_CONTROL;
        if (SuspendThread(thread) == (DWORD)-1)
            break; /* the game thread is gone */
        ok = GetThreadContext(thread, &context);
        ResumeThread(thread);
        if (ok)
            classify(context.Eip);
    }
    CloseHandle(thread);
    return 0;
}

/* "d3d9.dll 12.3%, ..." for the modules the game thread was sampled in since the last report, or
 * with `frame` since the last Present. Advances whichever baseline it read from. */
static void sample_line(BOOL frame)
{
    static LONG counts[MAX_MODULES];
    static const char *names[MAX_MODULES];
    static char paths[MAX_MODULES][MAX_PATH];
    LONG n = g_bin_count, total = 0, i;

    for (i = 0; i < n; i++) {
        LONG now = g_bins[i].count;
        LONG *then = frame ? &g_bins[i].frame_then : &g_bins[i].then;
        counts[i] = now - *then;
        *then = now;
        total += counts[i];
        if (g_bins[i].base == 0) {
            names[i] = "(no module)";
        } else if (g_bins[i].base == 1) {
            names[i] = "(census thunks)";
        } else {
            char *c, *name = paths[i];
            if (GetModuleFileNameA((HMODULE)g_bins[i].base, paths[i], MAX_PATH) == 0)
                lstrcpyA(paths[i], "?");
            for (c = paths[i]; *c; c++)
                if (*c == '\\' || *c == '/')
                    name = c + 1;
            names[i] = name;
        }
    }
    if (total == 0) {
        log_line("  game thread samples: none%s", frame ? " (the frame was shorter than a sample)" : "");
        return;
    }
    {
        char line[1000], pct[24];
        int order[TOP_N], shown = top(counts, n, order), k;
        int len = wsprintfA(line, "  game thread time by module (%ld samples):", total);
        for (k = 0; k < shown && len < 900; k++)
            len += wsprintfA(line + len, "%s %s %s%%", k ? "," : "", names[order[k]],
                             rate(pct, counts[order[k]] * 100, total));
        log_line("%s", line);
    }
}

static void report(double seconds)
{
    static LONG device[DEVICE_SLOTS], foreign[DEVICE_SLOTS], stall[DEVICE_SLOTS];
    static LONG effect[EFFECT_SLOTS], effect_foreign[EFFECT_SLOTS];
    static LONG queued_only[DEVICE_SLOTS], drain_only[DEVICE_SLOTS], direct_only[DEVICE_SLOTS];
    LONG frames = g_now.frames - g_then.frames;
    LONG stalls = g_now.stalls - g_then.stalls;
    LONG lock_foreign = 0, calls, queued, drains, direct;
    DWORD fps10 = (DWORD)(frames * 10.0 / seconds + 0.5);
    DWORD avg_us = (DWORD)(seconds * 1e6 / (frames ? frames : 1));
    DWORD max_us = (DWORD)(g_window_max_frame * 1000000 / g_qpf.QuadPart);
    char a[24], b[24], c[24], d[24], e[24], f[24], g[24];
    int i, k;

    diff(g_now.device, g_then.device, device, DEVICE_SLOTS);
    diff(g_now.device_foreign, g_then.device_foreign, foreign, DEVICE_SLOTS);
    diff(g_now.device_stall, g_then.device_stall, stall, DEVICE_SLOTS);
    diff(g_now.effect, g_then.effect, effect, g_effect_slots_hooked);
    diff(g_now.effect_foreign, g_then.effect_foreign, effect_foreign, g_effect_slots_hooked);
    for (i = 0; i < DEVICE_SLOTS; i++) {
        queued_only[i] = device_slot_kind[i] == SLOT_QUEUED ? device[i] : 0;
        drain_only[i] = device_slot_kind[i] == SLOT_DRAINS ? device[i] : 0;
        direct_only[i] = device_slot_kind[i] == SLOT_DIRECT ? device[i] : 0;
    }
    calls = sum(device, DEVICE_SLOTS);
    queued = sum(queued_only, DEVICE_SLOTS);
    drains = sum(drain_only, DEVICE_SLOTS);
    direct = sum(direct_only, DEVICE_SLOTS);

    log_line("report: %lu.%lu s, %ld frames, %lu.%lu fps, frame avg %lu.%03lu ms, max %lu.%03lu ms",
             (DWORD)seconds, (DWORD)(seconds * 10) % 10, frames, fps10 / 10, fps10 % 10,
             avg_us / 1000, avg_us % 1000, max_us / 1000, max_us % 1000);
    log_line("  device calls/frame: %s (queued %s, draining %s, direct %s); STALLS/frame %s, worst "
             "frame %ld",
             rate(a, calls, frames), rate(b, queued, frames), rate(c, drains, frames),
             rate(g, direct, frames), rate(d, stalls, frames), g_window_max_stalls);
    {
        LONGLONG ticks = g_present_ticks - g_present_ticks_then;
        DWORD us = frames > 0 ? (DWORD)(ticks * 1000000 / g_qpf.QuadPart / frames) : 0;
        g_present_ticks_then = g_present_ticks;
        log_line("  inside Present: %lu.%03lu ms/frame", us / 1000, us % 1000);
    }
    sample_line(FALSE);
    ranked_line("stalls/frame by device method", stall, device_slot_names, DEVICE_SLOTS, frames);
    for (k = 0; k < LOCK_KINDS; k++) {
        LONG n[LOCK_FLAG_CLASSES];
        diff(g_now.lock[k], g_then.lock[k], n, LOCK_FLAG_CLASSES);
        log_line("  %s locks/frame: %s (discard %s, nooverwrite %s, readonly %s, other %s), "
                 "stalls/frame %s",
                 lock_kind_names[k], rate(a, sum(n, LOCK_FLAG_CLASSES), frames),
                 rate(b, n[LF_DISCARD], frames), rate(c, n[LF_NOOVERWRITE], frames),
                 rate(d, n[LF_READONLY], frames), rate(e, n[LF_OTHER], frames),
                 rate(f, g_now.lock_stall[k] - g_then.lock_stall[k], frames));
        lock_foreign += g_now.lock_foreign[k] - g_then.lock_foreign[k];
    }
    ranked_line("draining methods/frame", drain_only, device_slot_names, DEVICE_SLOTS, frames);
    ranked_line("queued methods/frame", queued_only, device_slot_names, DEVICE_SLOTS, frames);
    ranked_line("direct methods/frame", direct_only, device_slot_names, DEVICE_SLOTS, frames);
    ranked_line("effect methods/frame", effect, effect_slot_names, g_effect_slots_hooked, frames);
    log_line("  other threads, whole window: %ld device calls, %ld effect calls, %ld locks",
             sum(foreign, DEVICE_SLOTS), sum(effect_foreign, g_effect_slots_hooked), lock_foreign);
    if (sum(foreign, DEVICE_SLOTS) > 0)
        ranked_line("other-thread device methods (totals, not per frame)", foreign,
                    device_slot_names, DEVICE_SLOTS, 1);

    g_then = g_now;
    g_window_max_stalls = 0;
    g_window_max_frame = 0;
}

/* One slow frame, in full: everything counted since the previous Present. */
static void hitch_report(LONGLONG ticks)
{
    static LONG device[DEVICE_SLOTS], creates[DEVICE_SLOTS], effect[EFFECT_SLOTS];
    struct counters *t = &g_frame_then;
    DWORD ms10 = (DWORD)(ticks * 10000 / g_qpf.QuadPart);
    DWORD present_us = (DWORD)((g_present_ticks - g_present_ticks_frame_then) * 1000000 /
                               g_qpf.QuadPart);
    LONG locks[LOCK_KINDS], k, i;

    diff(g_now.device, t->device, device, DEVICE_SLOTS);
    diff(g_now.effect, t->effect, effect, g_effect_slots_hooked);
    for (i = 0; i < DEVICE_SLOTS; i++)
        creates[i] = device_slot_names[i][0] == 'C' && device_slot_names[i][1] == 'r' ? device[i]
                                                                                     : 0;
    for (k = 0; k < LOCK_KINDS; k++) {
        LONG n[LOCK_FLAG_CLASSES];
        diff(g_now.lock[k], t->lock[k], n, LOCK_FLAG_CLASSES);
        locks[k] = sum(n, LOCK_FLAG_CLASSES);
    }
    log_line("HITCH: frame %lu.%lu ms (frame %ld), of which %lu.%03lu ms inside Present; %ld "
             "device calls, %ld effect calls, %ld stalls",
             ms10 / 10, ms10 % 10, g_now.frames, present_us / 1000, present_us % 1000,
             sum(device, DEVICE_SLOTS), sum(effect, g_effect_slots_hooked),
             g_now.stalls - t->stalls);
    sample_line(TRUE);
    log_line("  locks: texture %ld, surface %ld, vb %ld, ib %ld", locks[LOCK_TEXTURE],
             locks[LOCK_SURFACE], locks[LOCK_VB], locks[LOCK_IB]);
    ranked_line("creations", creates, device_slot_names, DEVICE_SLOTS, 1);
    ranked_line("device methods", device, device_slot_names, DEVICE_SLOTS, 1);
    ranked_line("effect methods", effect, effect_slot_names, g_effect_slots_hooked, 1);
}

/* The next frame is measured from here. */
static void frame_baseline(void)
{
    LONG i, n = g_bin_count;
    g_frame_then = g_now;
    g_present_ticks_frame_then = g_present_ticks;
    for (i = 0; i < n; i++)
        g_bins[i].frame_then = g_bins[i].count;
}

/* Hooks with arguments */

typedef HRESULT(WINAPI *PresentFn)(IDirect3DDevice9 *, const RECT *, const RECT *, HWND,
                                   const RGNDATA *);

static HRESULT WINAPI hk_present(IDirect3DDevice9 *dev, const RECT *src, const RECT *dst,
                                 HWND window, const RGNDATA *dirty)
{
    if (GetCurrentThreadId() != g_game_thread) {
        InterlockedIncrement(&g_now.device_foreign[DEVICE_SLOT_PRESENT]);
    } else {
        LARGE_INTEGER now;
        LONG frame_stalls;

        g_now.device[DEVICE_SLOT_PRESENT]++;
        g_dirty = 1; /* Present is queued */
        g_now.frames++;
        frame_stalls = g_now.stalls - g_stalls_at_last_present;
        g_stalls_at_last_present = g_now.stalls;
        if (frame_stalls > g_window_max_stalls)
            g_window_max_stalls = frame_stalls;

        QueryPerformanceCounter(&now);
        if (g_last_present.QuadPart != 0) {
            LONGLONG ticks = now.QuadPart - g_last_present.QuadPart;
            if (ticks > g_window_max_frame)
                g_window_max_frame = ticks;
            if (ticks * 1000 >= HITCH_MS * g_qpf.QuadPart && g_hitches < MAX_HITCHES) {
                g_hitches++;
                hitch_report(ticks);
            }
        }
        frame_baseline(); /* a frame runs Present-start to Present-start, this Present included */
        g_last_present = now;
        if (g_window_start.QuadPart == 0) {
            g_window_start = now;
            g_then = g_now;
        } else if (now.QuadPart - g_window_start.QuadPart >= REPORT_SECONDS * g_qpf.QuadPart) {
            report((double)(now.QuadPart - g_window_start.QuadPart) / (double)g_qpf.QuadPart);
            g_window_start = now;
        }
    }
    if (GetCurrentThreadId() == g_game_thread) {
        LARGE_INTEGER before, after;
        HRESULT hr;
        QueryPerformanceCounter(&before);
        hr = ((PresentFn)g_device_orig[DEVICE_SLOT_PRESENT])(dev, src, dst, window, dirty);
        QueryPerformanceCounter(&after);
        g_present_ticks += after.QuadPart - before.QuadPart;
        return hr;
    }
    return ((PresentFn)g_device_orig[DEVICE_SLOT_PRESENT])(dev, src, dst, window, dirty);
}

/* Put our hook back into every slot of d3d9's table that no longer holds it, taking what is
 * there now as that slot's original. Returns how many slots were (re)hooked. */
static int repair_device(IDirect3DDevice9 *dev, const char *why)
{
    void **now = *(void ***)dev;
    int slot, fixed = 0;
    char a[MAX_PATH + 32];

    if (now != g_device_vtbl) {
        if (checked_slots(now, DEVICE_SLOTS, FALSE) < DEVICE_SLOTS) {
            log_line("census: the device now points at %s, which is not a usable vtable - left "
                     "alone",
                     where(a, now));
            return 0;
        }
        log_line("census: the device now points at another vtable, %s - hooking that one",
                 where(a, now));
        g_device_vtbl = now;
    }
    for (slot = 0; slot < DEVICE_SLOTS; slot++) {
        void *current = now[slot];
        if (current == g_device_hook[slot])
            continue;
        g_device_orig[slot] = current; /* before the hook can be reached */
        if (patch_slot(&now[slot], g_device_hook[slot]) != NULL)
            fixed++;
    }
    if (fixed > 0 && why != NULL) {
        InterlockedExchangeAdd(&g_device_repairs, fixed);
        log_line("census: %d device slots hooked again %s", fixed, why);
    }
    return fixed;
}

typedef HRESULT(WINAPI *ResetFn)(IDirect3DDevice9 *, D3DPRESENT_PARAMETERS *);

static HRESULT WINAPI hk_reset(IDirect3DDevice9 *dev, D3DPRESENT_PARAMETERS *params)
{
    HRESULT hr;

    if (GetCurrentThreadId() != g_game_thread) {
        InterlockedIncrement(&g_now.device_foreign[DEVICE_SLOT_RESET]);
    } else {
        g_now.device[DEVICE_SLOT_RESET]++;
        g_dirty = 1; /* Reset is queued */
    }
    hr = ((ResetFn)g_device_orig[DEVICE_SLOT_RESET])(dev, params);
    log_line("Reset = 0x%08X", hr);
    repair_device(dev, "after Reset");
    return hr;
}

static void hook_device(IDirect3DDevice9 *dev)
{
    void **vtbl = *(void ***)dev;
    int slot;
    char a[MAX_PATH + 32], b[MAX_PATH + 32], c[MAX_PATH + 32], d[MAX_PATH + 32];

    log_line("census: device vtable at %s: QueryInterface %s, Reset %s, Present %s", where(a, vtbl),
             where(b, vtbl[0]), where(c, vtbl[DEVICE_SLOT_RESET]),
             where(d, vtbl[DEVICE_SLOT_PRESENT]));
    if (checked_slots(vtbl, DEVICE_SLOTS, FALSE) < DEVICE_SLOTS) {
        log_line("census: not every device slot points at code - the device is left alone");
        return;
    }
    for (slot = 0; slot < DEVICE_SLOTS; slot++) {
        if (slot == DEVICE_SLOT_PRESENT)
            g_device_hook[slot] = (void *)hk_present;
        else if (slot == DEVICE_SLOT_RESET)
            g_device_hook[slot] = (void *)hk_reset;
        else
            g_device_hook[slot] = emit_thunk(device_slot_kind[slot] == SLOT_QUEUED   ? THUNK_QUEUED
                                             : device_slot_kind[slot] == SLOT_DIRECT ? THUNK_PLAIN
                                                                                     : THUNK_DRAIN,
                                             &g_now.device[slot], &g_now.device_foreign[slot],
                                             &g_now.device_stall[slot], &g_device_orig[slot]);
        if (g_device_hook[slot] == NULL) {
            log_line("census: out of thunk space at device slot %d - the device is left alone",
                     slot);
            return;
        }
    }
    g_device_vtbl = vtbl;
    log_line("census: device vtable %08X hooked in place, %d of %d slots",
             (DWORD)(UINT_PTR)vtbl, repair_device(dev, NULL), DEVICE_SLOTS);
}

/* The watchdog: raw totals and the state of the device's hooks, every 10 s for two minutes and
 * every 60 s after. It exists because a report depends on Present reaching hk_present on the game
 * thread; when none appears, these lines say which link broke. */

static IDirect3DDevice9 *g_device;

static void log_status(void)
{
    int ours = 0, slot;

    if (g_device_vtbl != NULL && readable(g_device, sizeof(void *)))
        for (slot = 0; slot < DEVICE_SLOTS; slot++)
            ours += (*(void ***)g_device)[slot] == g_device_hook[slot];
    log_line("status: frames %ld; Present game thread %ld, other threads %ld; device calls game "
             "thread %ld, other threads %ld; effect calls %ld; stalls %ld",
             g_now.frames, g_now.device[DEVICE_SLOT_PRESENT],
             g_now.device_foreign[DEVICE_SLOT_PRESENT], sum(g_now.device, DEVICE_SLOTS),
             sum(g_now.device_foreign, DEVICE_SLOTS), sum(g_now.effect, EFFECT_SLOTS),
             g_now.stalls);
    log_line("status: %d of %d device slots ours before this check; %ld repaired so far", ours,
             DEVICE_SLOTS, g_device_repairs);
    if (g_device_vtbl != NULL && readable(g_device, sizeof(void *)) && ours < DEVICE_SLOTS)
        repair_device(g_device, "by the watchdog");
}

static DWORD WINAPI watchdog(LPVOID unused)
{
    int i;
    (void)unused;
    for (i = 0;; i++) {
        Sleep(i < 12 ? 10000 : 60000);
        log_status();
    }
}

typedef HRESULT(WINAPI *CreateDeviceFn)(IDirect3D9 *, UINT, D3DDEVTYPE, HWND, DWORD,
                                        D3DPRESENT_PARAMETERS *, IDirect3DDevice9 **);

static HRESULT WINAPI hk_create_device(IDirect3D9 *d3d, UINT adapter, D3DDEVTYPE type,
                                       HWND focus, DWORD behavior,
                                       D3DPRESENT_PARAMETERS *params, IDirect3DDevice9 **out)
{
    static LONG hooked;
    HRESULT hr = ((CreateDeviceFn)g_create_device_orig)(d3d, adapter, type, focus, behavior,
                                                         params, out);
    log_line("CreateDevice(adapter %u, type %u, behavior 0x%X) = 0x%08X, device %08X", adapter,
             type, behavior, hr, SUCCEEDED(hr) ? (DWORD)(UINT_PTR)*out : 0);
    if (SUCCEEDED(hr) && InterlockedExchange(&hooked, 1) == 0) {
        if (GetCurrentThreadId() != g_game_thread) {
            log_line("census: CreateDevice ran on thread %u, not the arming thread - the device "
                     "creator is the game thread from here on",
                     GetCurrentThreadId());
            g_game_thread = GetCurrentThreadId();
        }
        hook_resource_locks(*out);
        hook_device(*out);
        g_device = *out;
        CloseHandle(CreateThread(NULL, 0, watchdog, NULL, 0, NULL));
        CloseHandle(CreateThread(NULL, 0, sampler, NULL, 0, NULL));
    }
    return hr;
}

void census_hook_direct3d(IDirect3D9 *d3d)
{
    void **vtbl = *(void ***)d3d;
    if (g_create_device_orig != NULL)
        return;
    g_create_device_orig = vtbl[DIRECT3D_SLOT_CREATE_DEVICE];
    patch_slot(&vtbl[DIRECT3D_SLOT_CREATE_DEVICE], (void *)hk_create_device);
}

/* Effects: the engine creates every ID3DXEffect through two d3dx9_27 imports. */

typedef HRESULT(WINAPI *CreateEffectFn)(void *, const void *, UINT, const void *, void *, DWORD,
                                        void *, void **, void **);
typedef HRESULT(WINAPI *CreateEffectFromFileAFn)(void *, const char *, const void *, void *,
                                                 DWORD, void *, void **, void **);
static CreateEffectFn g_create_effect_orig;
static CreateEffectFromFileAFn g_create_effect_file_orig;

static void hook_effect(void *effect)
{
    static LONG hooked;
    void **vtbl;
    int slot;

    if (effect == NULL || InterlockedExchange(&hooked, 1) != 0)
        return;
    vtbl = *(void ***)effect;
    g_effect_slots_hooked = checked_slots(vtbl, EFFECT_SLOTS, TRUE);
    for (slot = 0; slot < g_effect_slots_hooked; slot++) {
        void *thunk;
        g_effect_orig[slot] = vtbl[slot];
        thunk = emit_thunk(THUNK_PLAIN, &g_now.effect[slot], &g_now.effect_foreign[slot], NULL,
                           &g_effect_orig[slot]);
        if (thunk != NULL)
            patch_slot(&vtbl[slot], thunk);
    }
    log_line("census: effect vtable %08X hooked, %d of %d slots", (DWORD)(UINT_PTR)vtbl,
             g_effect_slots_hooked, EFFECT_SLOTS);
}

static HRESULT WINAPI hk_create_effect(void *dev, const void *data, UINT len, const void *defines,
                                       void *include, DWORD flags, void *pool, void **effect,
                                       void **errors)
{
    HRESULT hr = g_create_effect_orig(dev, data, len, defines, include, flags, pool, effect,
                                      errors);
    if (SUCCEEDED(hr) && effect != NULL)
        hook_effect(*effect);
    return hr;
}

static HRESULT WINAPI hk_create_effect_file(void *dev, const char *file, const void *defines,
                                            void *include, DWORD flags, void *pool,
                                            void **effect, void **errors)
{
    HRESULT hr = g_create_effect_file_orig(dev, file, defines, include, flags, pool, effect,
                                           errors);
    if (SUCCEEDED(hr) && effect != NULL)
        hook_effect(*effect);
    return hr;
}

/* Point the game's import-table slot for `dll`!`name` at `hook`; returns the original, or NULL.
 *
 * The slot is found by the address the loader wrote into it, not by name: game.dat has no import
 * name table (every descriptor's OriginalFirstThunk is 0), so once it is loaded the IAT holds
 * nothing but resolved addresses. */
static void *hook_import(const char *dll, const char *name, void *hook)
{
    unsigned char *base = (unsigned char *)GetModuleHandleA(NULL);
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    IMAGE_IMPORT_DESCRIPTOR *desc = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir.VirtualAddress);
    HMODULE module = GetModuleHandleA(dll);
    UINT_PTR target = module != NULL ? (UINT_PTR)GetProcAddress(module, name) : 0;

    if (target == 0 || dir.VirtualAddress == 0)
        return NULL;
    for (; desc->Name != 0; desc++) {
        IMAGE_THUNK_DATA *slot;
        if (lstrcmpiA((const char *)(base + desc->Name), dll) != 0)
            continue;
        for (slot = (IMAGE_THUNK_DATA *)(base + desc->FirstThunk); slot->u1.Function != 0; slot++)
            if ((UINT_PTR)slot->u1.Function == target)
                return patch_slot((void **)&slot->u1.Function, hook);
    }
    return NULL;
}

void census_arm(void)
{
    g_code_size = 0x40000;
    g_code = VirtualAlloc(NULL, g_code_size, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    QueryPerformanceFrequency(&g_qpf);

    g_create_effect_orig =
        (CreateEffectFn)hook_import("d3dx9_27.dll", "D3DXCreateEffect", (void *)hk_create_effect);
    g_create_effect_file_orig = (CreateEffectFromFileAFn)hook_import(
        "d3dx9_27.dll", "D3DXCreateEffectFromFileA", (void *)hk_create_effect_file);
    log_line("census: thunk block %08X; D3DXCreateEffect %s, D3DXCreateEffectFromFileA %s",
             (DWORD)(UINT_PTR)g_code, g_create_effect_orig ? "hooked" : "NOT FOUND",
             g_create_effect_file_orig ? "hooked" : "NOT FOUND");
}
