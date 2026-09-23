/*
 * A 32-bit test program for census.c, built and run by test_census.py.
 *
 * census.c is included whole, so its statics are visible here. Fake IDirect3D9, device and vertex
 * buffer objects stand in for d3d9.dll; every method the test calls records its arguments and
 * returns a distinctive value, so a thunk that damaged either would show. Methods the test never
 * calls abort the program.
 *
 * Prints one line per failed check and "HARNESS OK" at the end if there were none; the log lines
 * census.c writes go to stdout as well.
 */

#include <stdarg.h>
#include <stddef.h>
#include <stdio.h>

#include "census.c"

DWORD g_game_thread;

void log_line(const char *fmt, ...)
{
    char line[2048];
    va_list args;
    va_start(args, fmt);
    wvsprintfA(line, fmt, args);
    va_end(args);
    printf("LOG %s\n", line);
}

static int g_failures;

#define CHECK(cond)                                                                                \
    do {                                                                                           \
        if (!(cond)) {                                                                             \
            printf("FAIL line %d: %s\n", __LINE__, #cond);                                         \
            g_failures++;                                                                          \
        }                                                                                          \
    } while (0)

#define SLOT(iface, method) ((int)(offsetof(iface##Vtbl, method) / sizeof(void *)))

struct fake {
    void **vtbl;
};

static void *g_d3d_vtbl[DIRECT3D_SLOTS];
/* d3d9's device table, a second one to move the device to, and the entries both start with. */
static void *g_dev_vtbl[DEVICE_SLOTS], *g_dev_vtbl_2[DEVICE_SLOTS], *g_dev_pristine[DEVICE_SLOTS];
static void *g_vb_vtbl[VERTEX_BUFFER_SLOTS];
static struct fake g_d3d = {g_d3d_vtbl}, g_dev = {g_dev_vtbl}, g_vb = {g_vb_vtbl};

static void *g_last_self;
static DWORD g_last_a, g_last_b, g_last_c;

static HRESULT WINAPI never(void *self)
{
    (void)self;
    printf("FAIL: a method the test does not call was called\n");
    ExitProcess(3);
    return E_FAIL;
}

static HRESULT WINAPI fake_create_device(void *self, UINT adapter, D3DDEVTYPE type, HWND focus,
                                         DWORD behavior, D3DPRESENT_PARAMETERS *params,
                                         IDirect3DDevice9 **out)
{
    (void)self, (void)focus, (void)params;
    g_last_a = adapter, g_last_b = type, g_last_c = behavior;
    *out = (IDirect3DDevice9 *)&g_dev;
    return D3D_OK;
}

static HRESULT WINAPI fake_set_render_state(void *self, D3DRENDERSTATETYPE state, DWORD value)
{
    g_last_self = self, g_last_a = state, g_last_b = value;
    return 0x11;
}

static HRESULT WINAPI fake_set_render_state_2(void *self, D3DRENDERSTATETYPE state, DWORD value)
{
    g_last_self = self, g_last_a = state, g_last_b = value;
    return 0x12;
}

static HRESULT WINAPI fake_get_render_state(void *self, D3DRENDERSTATETYPE state, DWORD *value)
{
    g_last_self = self;
    *value = 0xABCD0000u | state;
    return 0x22;
}

static HRESULT WINAPI fake_draw_primitive(void *self, D3DPRIMITIVETYPE type, UINT start,
                                          UINT count)
{
    g_last_self = self, g_last_a = type, g_last_b = start, g_last_c = count;
    return 0x33;
}

static HRESULT WINAPI fake_present(void *self, const RECT *src, const RECT *dst, HWND window,
                                   const RGNDATA *dirty)
{
    (void)src, (void)dst, (void)dirty;
    g_last_self = self, g_last_a = (DWORD)(UINT_PTR)window;
    return 0x44;
}

static HRESULT WINAPI fake_create_texture(void *self, UINT w, UINT h, UINT levels, DWORD usage,
                                          D3DFORMAT format, D3DPOOL pool,
                                          IDirect3DTexture9 **out, HANDLE *shared)
{
    (void)self, (void)w, (void)h, (void)levels, (void)usage, (void)format, (void)pool,
        (void)out, (void)shared;
    return D3DERR_INVALIDCALL;
}

static HRESULT WINAPI fake_create_vb(void *self, UINT length, DWORD usage, DWORD fvf,
                                     D3DPOOL pool, IDirect3DVertexBuffer9 **out, HANDLE *shared)
{
    (void)self, (void)length, (void)usage, (void)fvf, (void)pool, (void)shared;
    *out = (IDirect3DVertexBuffer9 *)&g_vb;
    return D3D_OK;
}

static HRESULT WINAPI fake_create_ib(void *self, UINT length, DWORD usage, D3DFORMAT format,
                                     D3DPOOL pool, IDirect3DIndexBuffer9 **out, HANDLE *shared)
{
    (void)self, (void)length, (void)usage, (void)format, (void)pool, (void)out, (void)shared;
    return D3DERR_INVALIDCALL;
}

static HRESULT WINAPI fake_get_back_buffer(void *self, UINT swap, UINT index,
                                           D3DBACKBUFFER_TYPE type, IDirect3DSurface9 **out)
{
    (void)self, (void)swap, (void)index, (void)type, (void)out;
    return D3DERR_INVALIDCALL;
}

static ULONG WINAPI fake_release(void *self)
{
    (void)self;
    return 1;
}

static HRESULT WINAPI fake_vb_lock(void *self, UINT offset, UINT size, void **out, DWORD flags)
{
    g_last_self = self, g_last_a = offset, g_last_b = size, g_last_c = flags;
    *out = (void *)0x5000;
    return 0x55;
}

/* Reset as the compatibility shim does it: it finds its state by the device's vtable pointer, so
 * the device must still be on its own table, and afterwards it rewrites every entry. */
static HRESULT WINAPI fake_reset(void *self, D3DPRESENT_PARAMETERS *params)
{
    int i;
    (void)params;
    if (((struct fake *)self)->vtbl != g_dev_vtbl) {
        printf("FAIL: Reset found the device on a table that is not its own\n");
        ExitProcess(4);
    }
    for (i = 0; i < DEVICE_SLOTS; i++)
        g_dev_vtbl[i] = g_dev_pristine[i];
    return 0x66;
}

static DWORD WINAPI fake_tick_count(void)
{
    return 0x7777;
}

static DWORD WINAPI other_thread(LPVOID dev)
{
    IDirect3DDevice9_SetRenderState((IDirect3DDevice9 *)dev, D3DRS_ZENABLE, 7);
    return 0;
}

int main(void)
{
    IDirect3D9 *d3d = (IDirect3D9 *)&g_d3d;
    IDirect3DDevice9 *dev = NULL;
    IDirect3DVertexBuffer9 *vb = NULL;
    D3DPRESENT_PARAMETERS params;
    DWORD value = 0;
    void *locked = NULL;
    HANDLE thread;
    int i;
    const int set_rs = SLOT(IDirect3DDevice9, SetRenderState);
    const int get_rs = SLOT(IDirect3DDevice9, GetRenderState);
    const int draw = SLOT(IDirect3DDevice9, DrawPrimitive);

    for (i = 0; i < DIRECT3D_SLOTS; i++)
        g_d3d_vtbl[i] = (void *)never;
    for (i = 0; i < DEVICE_SLOTS; i++)
        g_dev_vtbl[i] = (void *)never;
    for (i = 0; i < VERTEX_BUFFER_SLOTS; i++)
        g_vb_vtbl[i] = (void *)never;
    g_d3d_vtbl[DIRECT3D_SLOT_CREATE_DEVICE] = (void *)fake_create_device;
    g_dev_vtbl[set_rs] = (void *)fake_set_render_state;
    g_dev_vtbl[get_rs] = (void *)fake_get_render_state;
    g_dev_vtbl[draw] = (void *)fake_draw_primitive;
    g_dev_vtbl[DEVICE_SLOT_PRESENT] = (void *)fake_present;
    g_dev_vtbl[SLOT(IDirect3DDevice9, CreateTexture)] = (void *)fake_create_texture;
    g_dev_vtbl[SLOT(IDirect3DDevice9, CreateVertexBuffer)] = (void *)fake_create_vb;
    g_dev_vtbl[SLOT(IDirect3DDevice9, CreateIndexBuffer)] = (void *)fake_create_ib;
    g_dev_vtbl[SLOT(IDirect3DDevice9, GetBackBuffer)] = (void *)fake_get_back_buffer;
    g_dev_vtbl[SLOT(IDirect3DDevice9, Reset)] = (void *)fake_reset;
    for (i = 0; i < DEVICE_SLOTS; i++)
        g_dev_pristine[i] = g_dev_vtbl[i];
    g_vb_vtbl[SLOT(IDirect3DVertexBuffer9, Release)] = (void *)fake_release;
    g_vb_vtbl[VERTEX_BUFFER_SLOT_LOCK] = (void *)fake_vb_lock;

    /* The generated slot numbers agree with the header's C vtable layout. */
    CHECK(DEVICE_SLOT_PRESENT == SLOT(IDirect3DDevice9, Present));
    CHECK(DIRECT3D_SLOT_CREATE_DEVICE == SLOT(IDirect3D9, CreateDevice));
    CHECK(TEXTURE_SLOT_LOCK_RECT == SLOT(IDirect3DTexture9, LockRect));
    CHECK(SURFACE_SLOT_LOCK_RECT == SLOT(IDirect3DSurface9, LockRect));
    CHECK(VERTEX_BUFFER_SLOT_LOCK == SLOT(IDirect3DVertexBuffer9, Lock));
    CHECK(INDEX_BUFFER_SLOT_LOCK == SLOT(IDirect3DIndexBuffer9, Lock));
    CHECK(DEVICE_SLOTS == (int)(sizeof(IDirect3DDevice9Vtbl) / sizeof(void *)));
    CHECK(device_slot_kind[set_rs] == SLOT_QUEUED && device_slot_kind[get_rs] == SLOT_DRAINS);
    CHECK(device_slot_kind[SLOT(IDirect3DDevice9, AddRef)] == SLOT_DIRECT);
    CHECK(device_slot_kind[SLOT(IDirect3DDevice9, Release)] == SLOT_DRAINS);
    CHECK(device_slot_kind[SLOT(IDirect3DDevice9, CreateVertexBuffer)] == SLOT_DIRECT);

    /* A vtable is hooked as far as its slots point at code, wherever the table itself lives: the
     * real device's table is on the heap. A slot pointing at data ends it. */
    {
        static DWORD data_word;
        void **heap = (void **)HeapAlloc(GetProcessHeap(), 0, 4 * sizeof(void *));
        void *ntdll_code = (void *)GetProcAddress(GetModuleHandleA("ntdll.dll"), "NtClose");
        heap[0] = (void *)never, heap[1] = (void *)fake_present, heap[2] = ntdll_code;
        heap[3] = (void *)&data_word;
        CHECK(checked_slots(heap, 3, FALSE) == 3);
        CHECK(checked_slots(heap, 4, FALSE) == 3);
        CHECK(checked_slots(heap, 3, TRUE) == 2); /* ntdll is not the module slot 0 is in */
        HeapFree(GetProcessHeap(), 0, heap);
    }

    /* An import is found by the address in its IAT slot; game.dat has no name table to use. */
    {
        void *orig = hook_import("kernel32.dll", "GetTickCount", (void *)fake_tick_count);
        CHECK(orig == (void *)GetProcAddress(GetModuleHandleA("kernel32.dll"), "GetTickCount"));
        CHECK(GetTickCount() == 0x7777);
        /* A second attempt finds no slot still holding the original, so it cannot hook twice. */
        CHECK(hook_import("kernel32.dll", "GetTickCount", (void *)never) == NULL);
        CHECK(GetTickCount() == 0x7777);
        {
            void **slot = NULL;
            unsigned char *base = (unsigned char *)GetModuleHandleA(NULL);
            IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
            IMAGE_DATA_DIRECTORY iat = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IAT];
            void **p = (void **)(base + iat.VirtualAddress);
            for (; (unsigned char *)p < base + iat.VirtualAddress + iat.Size; p++)
                if (*p == (void *)fake_tick_count)
                    slot = p;
            CHECK(slot != NULL);
            if (slot != NULL)
                patch_slot(slot, orig); /* put it back for the rest of the run */
        }
        CHECK(GetTickCount() != 0x7777);
        CHECK(hook_import("kernel32.dll", "NoSuchExport", (void *)fake_tick_count) == NULL);
        CHECK(hook_import("d3dx9_27.dll", "D3DXCreateEffect", (void *)fake_tick_count) == NULL);
    }

    g_game_thread = GetCurrentThreadId();
    census_arm();
    CHECK(g_code != NULL);
    census_hook_direct3d(d3d);
    CHECK(g_d3d_vtbl[DIRECT3D_SLOT_CREATE_DEVICE] == (void *)hk_create_device);

    ZeroMemory(&params, sizeof params);
    CHECK(IDirect3D9_CreateDevice(d3d, 1, D3DDEVTYPE_HAL, NULL, 0x40, &params, &dev) == D3D_OK);
    CHECK(dev == (IDirect3DDevice9 *)&g_dev);
    CHECK(g_last_a == 1 && g_last_b == D3DDEVTYPE_HAL && g_last_c == 0x40);
    /* Hooked in place: the device keeps d3d9's table, whose entries are now ours. */
    CHECK(g_dev.vtbl == g_dev_vtbl && g_device_vtbl == g_dev_vtbl);
    CHECK(g_dev_vtbl[set_rs] != (void *)fake_set_render_state);
    CHECK(g_dev_vtbl[DEVICE_SLOT_PRESENT] == (void *)hk_present);
    CHECK(g_dev_vtbl[DEVICE_SLOT_RESET] == (void *)hk_reset);
    CHECK(g_lock_hooks[LOCK_VB].count == 1);
    CHECK(g_vb_vtbl[VERTEX_BUFFER_SLOT_LOCK] == (void *)hk_vb_lock);
    CHECK(g_lock_hooks[LOCK_TEXTURE].count == 0 && g_lock_hooks[LOCK_IB].count == 0);
    /* Making the probe resources is not counted: the device was hooked after them. */
    CHECK(g_now.device[SLOT(IDirect3DDevice9, CreateVertexBuffer)] == 0);

    /* Queued calls: arguments and results pass through, and the queue becomes non-empty. */
    for (i = 0; i < 3; i++)
        CHECK(IDirect3DDevice9_SetRenderState(dev, D3DRS_LIGHTING, 100 + i) == 0x11);
    CHECK(g_last_self == dev && g_last_a == D3DRS_LIGHTING && g_last_b == 102);
    CHECK(g_now.device[set_rs] == 3);
    CHECK(g_dirty == 1 && g_now.stalls == 0);

    /* A draining call after queued work is one stall; a second one straight after is not. */
    CHECK(IDirect3DDevice9_GetRenderState(dev, D3DRS_CULLMODE, &value) == 0x22);
    CHECK(value == (0xABCD0000u | D3DRS_CULLMODE));
    CHECK(g_now.device[get_rs] == 1 && g_now.device_stall[get_rs] == 1 && g_now.stalls == 1);
    CHECK(g_dirty == 0);
    CHECK(IDirect3DDevice9_GetRenderState(dev, D3DRS_CULLMODE, &value) == 0x22);
    CHECK(g_now.device[get_rs] == 2 && g_now.device_stall[get_rs] == 1 && g_now.stalls == 1);

    CHECK(IDirect3DDevice9_DrawPrimitive(dev, D3DPT_TRIANGLELIST, 5, 9) == 0x33);
    CHECK(g_last_a == D3DPT_TRIANGLELIST && g_last_b == 5 && g_last_c == 9);
    CHECK(g_dirty == 1);

    /* A lock after queued work is a stall too, classified by its flags. */
    CHECK(IDirect3DDevice9_CreateVertexBuffer(dev, 64, 0, 0, D3DPOOL_MANAGED, &vb, NULL) == D3D_OK);
    CHECK(g_now.stalls == 1 && g_dirty == 1); /* CreateVertexBuffer is direct: no stall */
    IDirect3DDevice9_DrawPrimitive(dev, D3DPT_TRIANGLELIST, 0, 1);
    CHECK(IDirect3DVertexBuffer9_Lock(vb, 16, 32, &locked, D3DLOCK_DISCARD) == 0x55);
    CHECK(locked == (void *)0x5000 && g_last_a == 16 && g_last_b == 32 &&
          g_last_c == D3DLOCK_DISCARD);
    CHECK(g_now.lock[LOCK_VB][LF_DISCARD] == 1 && g_now.lock_stall[LOCK_VB] == 1);
    CHECK(g_now.stalls == 2);

    /* Present ends a frame, and counts that frame's stalls. */
    CHECK(IDirect3DDevice9_Present(dev, NULL, NULL, (HWND)0x77, NULL) == 0x44);
    CHECK(g_last_a == 0x77);
    CHECK(g_now.frames == 1 && g_now.device[DEVICE_SLOT_PRESENT] == 1);
    CHECK(g_window_max_stalls == 2);

    /* The watchdog's status: everything ours, nothing repaired. */
    CHECK(g_device == dev);
    log_status();
    CHECK(g_device_repairs == 0);

    /* Something rewrites one entry, as the shim does: calls bypass us until the watchdog puts the
     * hook back, taking the new entry as that slot's original. */
    g_dev_vtbl[set_rs] = (void *)fake_set_render_state_2;
    CHECK(IDirect3DDevice9_SetRenderState(dev, D3DRS_FOGENABLE, 1) == 0x12);
    CHECK(g_now.device[set_rs] == 3);
    log_status();
    CHECK(g_device_repairs == 1 && g_dev_vtbl[set_rs] != (void *)fake_set_render_state_2);
    CHECK(IDirect3DDevice9_SetRenderState(dev, D3DRS_FOGENABLE, 1) == 0x12);
    CHECK(g_now.device[set_rs] == 4);

    /* Reset, shim-style: the device must still be on its own table (fake_reset exits otherwise),
     * and every entry comes back rewritten. hk_reset hooks them all again. */
    CHECK(IDirect3DDevice9_Reset(dev, &params) == 0x66);
    CHECK(g_now.device[DEVICE_SLOT_RESET] == 1);
    CHECK(g_device_repairs == 1 + DEVICE_SLOTS);
    CHECK(g_dev_vtbl[DEVICE_SLOT_RESET] == (void *)hk_reset);
    CHECK(g_dev_vtbl[DEVICE_SLOT_PRESENT] == (void *)hk_present);
    CHECK(IDirect3DDevice9_SetRenderState(dev, D3DRS_FOGENABLE, 2) == 0x11);
    CHECK(g_now.device[set_rs] == 5);
    CHECK(IDirect3DDevice9_Present(dev, NULL, NULL, (HWND)0x78, NULL) == 0x44);
    CHECK(g_now.frames == 2);

    /* The device moved to another table: the watchdog hooks that one. */
    for (i = 0; i < DEVICE_SLOTS; i++)
        g_dev_vtbl_2[i] = g_dev_pristine[i];
    g_dev.vtbl = g_dev_vtbl_2;
    log_status();
    CHECK(g_device_vtbl == g_dev_vtbl_2);
    CHECK(g_dev_vtbl_2[set_rs] != (void *)fake_set_render_state);
    CHECK(IDirect3DDevice9_SetRenderState(dev, D3DRS_FOGENABLE, 3) == 0x11);
    CHECK(g_now.device[set_rs] == 6);
    g_dev.vtbl = g_dev_vtbl; /* back to the first, whose entries are still ours */

    /* Another thread's calls pass through and are kept apart. */
    thread = CreateThread(NULL, 0, other_thread, dev, 0, NULL);
    WaitForSingleObject(thread, INFINITE);
    CloseHandle(thread);
    CHECK(g_last_a == D3DRS_ZENABLE && g_last_b == 7);
    CHECK(g_now.device_foreign[set_rs] == 1 && g_now.device[set_rs] == 6);

    /* A slow frame gets a block of its own: sleep past the threshold between two Presents. */
    IDirect3DDevice9_Present(dev, NULL, NULL, (HWND)0x79, NULL);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_LIGHTING, 1);
    IDirect3DDevice9_CreateVertexBuffer(dev, 64, 0, 0, D3DPOOL_MANAGED, &vb, NULL);
    Sleep(HITCH_MS + 20);
    CHECK(IDirect3DDevice9_Present(dev, NULL, NULL, (HWND)0x7A, NULL) == 0x44);
    CHECK(g_hitches == 1);

    /* Samples are filed by module: this program, our thunk block, and nowhere. */
    classify((UINT_PTR)main);
    classify((UINT_PTR)main);
    classify((UINT_PTR)g_code + 4);
    classify(0x10);
    {
        LONG exe = 0, thunks = 0, nowhere = 0, b;
        for (b = 0; b < g_bin_count; b++) {
            if (g_bins[b].base == (UINT_PTR)GetModuleHandleA(NULL))
                exe = g_bins[b].count;
            else if (g_bins[b].base == 1)
                thunks = g_bins[b].count;
            else if (g_bins[b].base == 0)
                nowhere = g_bins[b].count;
        }
        CHECK(exe >= 2 && thunks >= 1 && nowhere >= 1);
    }

    /* The report covers everything since the zeroed baseline; test_census.py reads it. */
    ZeroMemory(&g_then, sizeof g_then);
    report(30.0);
    CHECK(g_then.frames == g_now.frames);

    printf(g_failures ? "HARNESS FAILED (%d)\n" : "HARNESS OK\n", g_failures);
    return g_failures ? 1 : 0;
}
