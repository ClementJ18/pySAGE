#include "src/aotr_accel.cpp"
#include <assert.h>

static void originalMethod() {}
static void shimMethod() {}
static DWORD resetResult;
static unsigned resetCalls;
struct FakeDevice { void** table; };

static DWORD __stdcall fakeReset(void* self, DWORD) {
    ++resetCalls;
    FakeDevice* device = (FakeDevice*)self;
    // A partial rewrite must not turn unchanged hooks into their own originals.
    device->table[17] = (void*)&shimMethod;
    device->table[82] = (void*)&shimMethod;
    return resetResult;
}

static void testReset(DWORD result, bool active) {
    void* table[119];
    for (int i = 0; i < 119; ++i) {
        table[i] = g_rtH_dev[i];
        g_rtO_dev[i] = (void*)&originalMethod;
    }
    g_rtO_dev[16] = (void*)&fakeReset;
    FakeDevice device = { table };
    resetResult = result;
    resetCalls = 0;
    g_rtActive = active ? 1 : 0;
    g_rtInstalled = 1;
    assert(rt_dev_16(&device, 0) == result);
    assert(resetCalls == 1);
    assert(g_rtO_dev[16] == (void*)&fakeReset);
    assert(g_rtO_dev[17] == (void*)&shimMethod);
    assert(g_rtO_dev[82] == (void*)&shimMethod);
    assert(g_rtO_dev[18] == (void*)&originalMethod);
    for (int i = 0; i < 119; ++i) assert(table[i] == g_rtH_dev[i]);
    assert(rtRehookDevice(&device));
    assert(g_rtO_dev[17] == (void*)&shimMethod); // Repeating repair is idempotent.

    table[50] = NULL;
    table[51] = (void*)&shimMethod;
    assert(!rtRehookDevice(&device));
    assert(table[51] == (void*)&shimMethod); // Validate all slots before changing any.
    assert(g_rtO_dev[51] == (void*)&originalMethod);
    g_rtActive = 0;
}

static HANDLE messageReady;
static LRESULT CALLBACK messageWindow(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == WM_APP) return 123;
    return DefWindowProcA(hwnd, message, wparam, lparam);
}
static DWORD WINAPI sendingWorker(void* window) {
    EnterCriticalSection(&g_rtExecCs);
    SetEvent(messageReady);
    LRESULT result = SendMessageA((HWND)window, WM_APP, 0, 0);
    LeaveCriticalSection(&g_rtExecCs);
    return result == 123 ? 0 : 1;
}
static void testWindowThreadLock() {
    WNDCLASSA cls = {};
    cls.lpfnWndProc = messageWindow;
    cls.hInstance = GetModuleHandleA(NULL);
    cls.lpszClassName = "SageLockRegression";
    assert(RegisterClassA(&cls));
    HWND window = CreateWindowExA(0, cls.lpszClassName, "", 0, 0, 0, 0, 0,
                                 HWND_MESSAGE, NULL, cls.hInstance, NULL);
    assert(window);
    messageReady = CreateEventA(NULL, TRUE, FALSE, NULL);
    HANDLE worker = CreateThread(NULL, 0, sendingWorker, window, 0, NULL);
    assert(worker && messageReady);
    assert(WaitForSingleObject(messageReady, 5000) == WAIT_OBJECT_0);
    rtEnterExec(); // Must dispatch the sent message so the worker can release the lock.
    LeaveCriticalSection(&g_rtExecCs);
    assert(WaitForSingleObject(worker, 5000) == WAIT_OBJECT_0);
    DWORD code = 1;
    assert(GetExitCodeThread(worker, &code) && code == 0);
    CloseHandle(worker);
    CloseHandle(messageReady);
    DestroyWindow(window);
    UnregisterClassA(cls.lpszClassName, cls.hInstance);
}

static void testAllocator() {
    assert(rpmalloc_initialize() == 0);
    unsigned char* p = (unsigned char*)my_calloc(8, 8);
    assert(p && aOwns(p));
    for (int i = 0; i < 64; ++i) assert(p[i] == 0);
    memset(p, 0x5A, 64);
    unsigned char* larger = (unsigned char*)my_realloc(p, 128);
    assert(larger && aOwns(larger));
    for (int i = 0; i < 64; ++i) assert(larger[i] == 0x5A);
    assert(my_realloc(larger, (size_t)-1) == NULL);
    for (int i = 0; i < 64; ++i) assert(larger[i] == 0x5A);
    LONG frees = g_aFrees;
    assert(my_realloc(larger, 0) == NULL);
    assert(g_aFrees == frees + 1);
    assert(my_calloc((size_t)-1, 2) == NULL);
    assert(my_malloc((size_t)-1) == NULL);
    my_free(NULL);
    puts("PASS: allocator zero-fill, growth preservation, overflow and realloc-to-zero");
}

int main() {
    InitializeCriticalSection(&g_logCs);
    InitializeCriticalSection(&g_rtExecCs);
    SetEnvironmentVariableA("PYSAGE_EXPERIMENTAL_RT", NULL);
    rtInitBody();
    assert(g_rtTried && !g_rtActive && !g_rtInstalled);
    g_mkTid = 0;
    for (int i = 0; i < 1000; ++i) assert(!rtIsGameThread(123));
    g_mkTid = GetCurrentThreadId();
    g_rtMainTid = g_mkTid;
    assert(rtIsGameThread(g_mkTid));
    assert(!rtIsGameThread(g_mkTid + 1));
    testReset(0, false);
    testReset(0x88760868, false); // A failed Reset can also change a shim's vtable.
    testReset(0, true);
    testReset(0x88760868, true);
    testWindowThreadLock();
    testAllocator();
    assert(!g_rtFxDedupeOn);
    // Cache epoch wrap must clear the entire allocation, not sizeof(pointer).
    g_rtFxV = (RtFxVal*)calloc(RT_FXV, sizeof(RtFxVal));
    assert(g_rtFxV);
    g_rtFxV[RT_FXV - 1].epoch = 1;
    g_rtFxEpoch = 0xFFFFFFFF;
    rtFxInvalAll();
    assert(g_rtFxEpoch == 1 && g_rtFxV[RT_FXV - 1].epoch == 0);
    free(g_rtFxV);
    g_rtFxV = NULL;
    puts("PASS: default renderer gate, explicit thread identity, active/inactive Reset, partial hook repair, invalid-table rejection, window-thread lock, cache epoch wrap");
    return 0;
}
