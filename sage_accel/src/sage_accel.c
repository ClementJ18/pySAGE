/*
 * sage_accel - a Direct3D accelerator for the ROTWK SAGE engine, loaded by the `accel-module`
 * sage_patch patch.
 *
 * Derived, with his permission, from OH1A's bfme2_accel.dll (sage_patch/docs/accel-*.md). This
 * is milestone M1 of sage_patch/docs/accel-module.md: the module arms at the engine's
 * Direct3DCreate9 resolve and counts the renderer's calls (census.c) without changing any.
 *
 * The contract with the patch's cave is one export:
 *
 *     void *__cdecl sage_accel_arm(void *real_direct3d_create9);
 *
 * called once, on the game thread, right after the engine has resolved Direct3DCreate9 from
 * d3d9.dll. It returns the function the engine should call instead, or NULL to leave the engine's
 * own pointer in place. The cave treats a missing DLL, a missing export and a NULL return the same
 * way: stock behaviour.
 */

#include <stdarg.h>

#include "accel.h"

#define SAGE_ACCEL_VERSION "0.2.0 (M1)"

typedef IDirect3D9 *(WINAPI *Direct3DCreate9Fn)(UINT sdk_version);

static HMODULE g_module;
static HANDLE g_log = INVALID_HANDLE_VALUE;
static Direct3DCreate9Fn g_real_create;
DWORD g_game_thread;

/* The directory holding this DLL, with a trailing backslash, or "" if it cannot be found. */
static void module_dir(char *out, DWORD size)
{
    DWORD n = GetModuleFileNameA(g_module, out, size);
    if (n == 0 || n >= size) {
        out[0] = '\0';
        return;
    }
    while (n > 0 && out[n - 1] != '\\' && out[n - 1] != '/')
        n--;
    out[n] = '\0';
}

static void log_open(void)
{
    char path[MAX_PATH + 32];
    module_dir(path, MAX_PATH);
    lstrcatA(path, "sage_accel.log");
    g_log = CreateFileA(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS,
                        FILE_ATTRIBUTE_NORMAL, NULL);
}

/* One timestamped line. wvsprintfA has no %p and no floats; pointers are printed as %08X. */
void log_line(const char *fmt, ...)
{
    char line[2048];
    SYSTEMTIME now;
    va_list args;
    int head, body;
    DWORD written;

    if (g_log == INVALID_HANDLE_VALUE)
        return;
    GetLocalTime(&now);
    head = wsprintfA(line, "%02u:%02u:%02u.%03u [%5u] ", now.wHour, now.wMinute, now.wSecond,
                     now.wMilliseconds, GetCurrentThreadId());
    va_start(args, fmt);
    body = wvsprintfA(line + head, fmt, args);
    va_end(args);
    line[head + body] = '\r';
    line[head + body + 1] = '\n';
    WriteFile(g_log, line, (DWORD)(head + body + 2), &written, NULL);
}

/* A file named sage_accel.off beside the DLL turns the module into a no-op without unpatching. */
static BOOL switched_off(void)
{
    char path[MAX_PATH + 32];
    module_dir(path, MAX_PATH);
    lstrcatA(path, "sage_accel.off");
    return GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES;
}

static IDirect3D9 *WINAPI accel_Direct3DCreate9(UINT sdk_version)
{
    IDirect3D9 *d3d = g_real_create(sdk_version);
    log_line("Direct3DCreate9(0x%X) = %08X%s", sdk_version, (DWORD)(UINT_PTR)d3d,
             GetCurrentThreadId() == g_game_thread ? "" : " - NOT on the arming thread");
    if (d3d != NULL)
        census_hook_direct3d(d3d);
    return d3d;
}

__declspec(dllexport) void *__cdecl sage_accel_arm(void *real_direct3d_create9)
{
    if (g_real_create != NULL)
        return NULL; /* armed already; a second call must not wrap the wrapper */

    log_open();
    g_game_thread = GetCurrentThreadId();
    log_line("sage_accel %s - derived from OH1A's bfme2_accel.dll", SAGE_ACCEL_VERSION);
    log_line("armed by the engine's Direct3DCreate9 resolve; game thread %u, real %08X",
             g_game_thread, (DWORD)(UINT_PTR)real_direct3d_create9);

    if (real_direct3d_create9 == NULL) {
        log_line("the engine resolved no Direct3DCreate9 - staying out of the way");
        return NULL;
    }
    if (switched_off()) {
        log_line("sage_accel.off is present - staying out of the way");
        return NULL;
    }
    g_real_create = (Direct3DCreate9Fn)real_direct3d_create9;
    census_arm();
    log_line("census: counting device, effect and lock calls; a report every 30 s");
    return (void *)accel_Direct3DCreate9;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}
