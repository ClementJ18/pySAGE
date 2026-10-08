// rt_harness.cpp - offline correctness test for the render thread (RT) in pysage_accel.dll.
//   rt_harness off <frames> <out.txt>   render with direct D3D9/D3DX calls
//   rt_harness on  <frames> <out.txt>   same frames with the render thread installed
// Every frame is read back (StretchRect -> GetRenderTargetData -> LockRect) and hashed; the two runs must
// produce identical hashes. The scene mirrors the game's patterns: a render-to-texture shadow pass with a
// "_CreateShadowMap" technique, Begin(flags=6) state blocks, parameter blocks, SetRawValue world matrices
// and bone palettes, a preshader, dynamic vertex buffer DISCARD locks, per-frame texture LockRect updates,
// DrawPrimitiveUP / DrawIndexedPrimitiveUP, application state blocks and D3DX texture creation mid-run.
// Uses local or system D3D9 and the system d3dx9_27.dll. 32-bit, raw vtables.
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <float.h>

static void** vt(void* o) { return *(void***)o; }
#define CALL0(o, s)                 ((HRESULT(WINAPI*)(void*))vt(o)[s])(o)
#define CALL1(o, s, a)              ((HRESULT(WINAPI*)(void*, DWORD))vt(o)[s])(o, (DWORD)(a))
#define CALL2(o, s, a, b)           ((HRESULT(WINAPI*)(void*, DWORD, DWORD))vt(o)[s])(o, (DWORD)(a), (DWORD)(b))
#define CALL3(o, s, a, b, c)        ((HRESULT(WINAPI*)(void*, DWORD, DWORD, DWORD))vt(o)[s])(o, (DWORD)(a), (DWORD)(b), (DWORD)(c))
#define CALL4(o, s, a, b, c, d)     ((HRESULT(WINAPI*)(void*, DWORD, DWORD, DWORD, DWORD))vt(o)[s])(o, (DWORD)(a), (DWORD)(b), (DWORD)(c), (DWORD)(d))
#define CALL5(o, s, a, b, c, d, e)  ((HRESULT(WINAPI*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD))vt(o)[s])(o, (DWORD)(a), (DWORD)(b), (DWORD)(c), (DWORD)(d), (DWORD)(e))
#define CALL6(o, s, a, b, c, d, e, f) ((HRESULT(WINAPI*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))vt(o)[s])(o, (DWORD)(a), (DWORD)(b), (DWORD)(c), (DWORD)(d), (DWORD)(e), (DWORD)(f))
#define CALL8(o, s, a, b, c, d, e, f, g, h) ((HRESULT(WINAPI*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))vt(o)[s])(o, (DWORD)(a), (DWORD)(b), (DWORD)(c), (DWORD)(d), (DWORD)(e), (DWORD)(f), (DWORD)(g), (DWORD)(h))
static DWORD fbits(float f) { DWORD d; memcpy(&d, &f, 4); return d; }

typedef struct { UINT BackBufferWidth, BackBufferHeight; DWORD BackBufferFormat; UINT BackBufferCount;
    DWORD MultiSampleType, MultiSampleQuality, SwapEffect; HWND hDeviceWindow; BOOL Windowed;
    BOOL EnableAutoDepthStencil; DWORD AutoDepthStencilFormat, Flags; UINT FullScreen_RefreshRateInHz, PresentationInterval; } PP;
typedef struct { INT Pitch; void* pBits; } LOCKED_RECT;
typedef struct { WORD Stream, Offset; BYTE Type, Method, Usage, UsageIndex; } VELEM;

static const char kFx[] =
"float4x4 World; float4x4 ViewProj; float4x4 LightViewProj; float3x4 Bones[4];\n"
"float4 MatColor = {1,1,1,1}; float Blend = 0.5; float4 Tint = {1,1,1,1};\n"
"float ThisParameterNameIsLongerThanFortyCharactersForTheCache = 1.0; struct MatParams { float4 Col; float Val; }; MatParams Mat = { {1,1,1,1}, 1.0 };\n"
"texture DiffuseTex; sampler DiffuseS = sampler_state { Texture = <DiffuseTex>; MinFilter = LINEAR; MagFilter = LINEAR; MipFilter = LINEAR; };\n"
"texture ShadowTex; sampler ShadowS = sampler_state { Texture = <ShadowTex>; MinFilter = POINT; MagFilter = POINT; MipFilter = NONE; AddressU = CLAMP; AddressV = CLAMP; };\n"
"struct VSIn { float4 pos : POSITION; float3 nrm : NORMAL; float2 uv : TEXCOORD0; };\n"
"struct VSOut { float4 pos : POSITION; float2 uv : TEXCOORD0; float4 lpos : TEXCOORD1; float3 nrm : TEXCOORD2; };\n"
"VSOut VS(VSIn i) { VSOut o; float3 p = mul(float4(i.pos.xyz,1), Bones[0]); float4 w = mul(float4(p,1), World);\n"
"  o.pos = mul(w, ViewProj); o.uv = i.uv; o.lpos = mul(w, LightViewProj); o.nrm = mul(i.nrm, (float3x3)World); return o; }\n"
"float4 PS(VSOut i) : COLOR { float2 suv = i.lpos.xy / i.lpos.w * float2(0.5,-0.5) + 0.5; float d = tex2D(ShadowS, suv).r;\n"
"  float lit = (i.lpos.z / i.lpos.w - 0.01 < d) ? 1.0 : 0.4; float4 c = tex2D(DiffuseS, i.uv) * MatColor * (Tint * Blend * 2.0) * ThisParameterNameIsLongerThanFortyCharactersForTheCache * Mat.Val * Mat.Col;\n"
"  return float4(c.rgb * lit * (0.5 + 0.5 * saturate(normalize(i.nrm).y)), 1); }\n"
"struct SVSOut { float4 pos : POSITION; float z : TEXCOORD0; };\n"
"SVSOut SVS(VSIn i) { SVSOut o; float3 p = mul(float4(i.pos.xyz,1), Bones[0]); float4 w = mul(float4(p,1), World);\n"
"  o.pos = mul(w, LightViewProj); o.z = o.pos.z / o.pos.w; return o; }\n"
"float4 SPS(SVSOut i) : COLOR { return float4(i.z, i.z, i.z, 1); }\n"
"technique Main < int MaxSkinningBones = 24; float Lod = 0.75; > { pass p0 { VertexShader = compile vs_2_0 VS(); PixelShader = compile ps_2_0 PS(); ZEnable = TRUE; CullMode = CCW; AlphaBlendEnable = FALSE; } }\n"
"technique _CreateShadowMap { pass p0 { VertexShader = compile vs_2_0 SVS(); PixelShader = compile ps_2_0 SPS(); ZEnable = TRUE; CullMode = NONE; } }\n";

static void matIdent(float* m) { memset(m, 0, 64); m[0] = m[5] = m[10] = m[15] = 1; }
static void matMul(const float* a, const float* b, float* o) { float t[16]; for (int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) { float s = 0; for (int k = 0; k < 4; ++k) s += a[r*4+k] * b[k*4+c]; t[r*4+c] = s; } memcpy(o, t, 64); }
static void matWorld(float* m, float x, float y, float z, float ang, float sc) {
    matIdent(m); float c = static_cast<float>(cos(ang) * sc), s = static_cast<float>(sin(ang) * sc); m[0] = c; m[2] = -s; m[5] = sc; m[8] = s; m[10] = c; m[12] = x; m[13] = y; m[14] = z; }
static void matLookProj(float* out, float ex, float ey, float ez, float fovScale) {
    // simple look-at toward origin (LH) * perspective
    float zx = -ex, zy = -ey, zz = -ez; float zl = static_cast<float>(sqrt(zx*zx + zy*zy + zz*zz)); zx /= zl; zy /= zl; zz /= zl;
    float xx = zz, xy = 0, xz = -zx; float xl = static_cast<float>(sqrt(xx*xx + xz*xz)); xx /= xl; xz /= xl;
    float yx = zy*xz - zz*xy, yy = zz*xx - zx*xz, yz = zx*xy - zy*xx;
    float v[16] = { xx, yx, zx, 0,  xy, yy, zy, 0,  xz, yz, zz, 0,
                    -(xx*ex + xy*ey + xz*ez), -(yx*ex + yy*ey + yz*ez), -(zx*ex + zy*ey + zz*ez), 1 };
    float zn = 1, zf = 100, h = fovScale, w = fovScale * 0.75f;
    float p[16] = { w, 0, 0, 0,  0, h, 0, 0,  0, 0, zf/(zf-zn), 1,  0, 0, -zn*zf/(zf-zn), 0 };
    matMul(v, p, out);
}
static void pixelOpDirect(void* surf, DWORD x, DWORD y, DWORD v, DWORD mode) {
    struct { LONG l, t, rr, b; } rc = { (LONG)x, (LONG)y, (LONG)x + 1, (LONG)y + 1 };
    struct { INT pitch; void* bits; } lr = { 0, NULL };
    ((HRESULT(WINAPI*)(void*, void*, void*, DWORD))vt(surf)[13])(surf, &lr, &rc, 0);
    if (lr.bits) switch (mode) { case 1: *(BYTE*)lr.bits = (BYTE)v; break; case 2: *(WORD*)lr.bits = (WORD)v; break; case 4: *(DWORD*)lr.bits = v; break; case 0x100: ((BYTE*)lr.bits)[3] = (BYTE)v; break; }
    ((HRESULT(WINAPI*)(void*))vt(surf)[14])(surf);
}
static void __cdecl pixelOpDirect_cdecl(void* surf, DWORD x, DWORD y, DWORD v, DWORD mode) { pixelOpDirect(surf, x, y, v, mode); }
static void __cdecl shroudRectDirect(void* surf, DWORD l, DWORD t, DWORD r, DWORD b, const BYTE* rows, DWORD bpp) {   // what the engine does directly
    struct { LONG l, t, rr, b; } rc = { (LONG)l, (LONG)t, (LONG)r, (LONG)b }; struct { INT pitch; void* bits; } lr = { 0, NULL };
    ((HRESULT(WINAPI*)(void*, void*, void*, DWORD))vt(surf)[13])(surf, &lr, &rc, 0x800);
    DWORD rowBytes = (r - l) * bpp;
    if (lr.bits) for (DWORD y = 0; y < b - t; ++y) memcpy((BYTE*)lr.bits + (INT)y * lr.pitch, rows + y * rowBytes, rowBytes);
    ((HRESULT(WINAPI*)(void*))vt(surf)[14])(surf);
}
static void radarModify(BYTE* bits, INT pitch, DWORD w, DWORD h, DWORD op, DWORD e) {
    for (DWORD y = 0; y < h; ++y) for (DWORD x = 0; x < w; ++x) {
        DWORD* px = (DWORD*)(bits + (INT)y * pitch + x * 4);
        *px = op == 1 ? (*px * 3 + e + (x ^ (y << 3))) : ((*px >> 1) ^ (e * (x + 1)));
    }
}
static void __cdecl radarDirect(void* surf, DWORD op, DWORD a, DWORD b, DWORD c, DWORD d, DWORD e) {      // what the engine does directly
    struct { LONG l, t, rr, b; } rc = { (LONG)a, (LONG)b, (LONG)c, (LONG)d };
    struct { INT pitch; void* bits; } lr = { 0, NULL };
    HRESULT hr = ((HRESULT(WINAPI*)(void*, void*, void*, DWORD))vt(surf)[13])(surf, &lr, op == 1 ? &rc : NULL, op == 2 ? 0 : 0x800);
    if (FAILED(hr) || !lr.bits) return;
    if (op == 2) { for (int y = 0; y < 128; ++y) memset((BYTE*)lr.bits + y * lr.pitch, (BYTE)a ? 0xFF : 0x00, 128 * 4); }
    else radarModify((BYTE*)lr.bits, lr.pitch, op == 1 ? c - a : 128, op == 1 ? d - b : 128, op, e);
    ((HRESULT(WINAPI*)(void*))vt(surf)[14])(surf);
}
static unsigned long long fnv(const BYTE* p, size_t n, unsigned long long h) { for (size_t i = 0; i < n; ++i) { h ^= p[i]; h *= 1099511628211ull; } return h; }

static LONG g_vehN = 0, g_vehOn = 0;
static LONG CALLBACK harnessVeh(EXCEPTION_POINTERS* ep) {
    DWORD code = ep->ExceptionRecord->ExceptionCode;
    if ((code & 0x80000000u) && g_vehOn && g_vehN < 12) {
        g_vehN++;
        void* at = ep->ExceptionRecord->ExceptionAddress;
        char mod[MAX_PATH]; mod[0] = 0; HMODULE hm = NULL;
        GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)at, &hm);
        if (hm) GetModuleFileNameA(hm, mod, MAX_PATH);
        printf("VEH %08X at %p rva %08X in %s thread %lu access %p addr %p\n",
               (unsigned)code, at, (unsigned)((BYTE*)at - (BYTE*)hm), mod[0] ? mod : "?", GetCurrentThreadId(),
               (void*)ep->ExceptionRecord->ExceptionInformation[0], (void*)ep->ExceptionRecord->ExceptionInformation[1]);
        CONTEXT* c = ep->ContextRecord;
        printf("   eax %08X ebx %08X ecx %08X edx %08X esi %08X edi %08X esp %08X ebp %08X\n",
               c->Eax, c->Ebx, c->Ecx, c->Edx, c->Esi, c->Edi, c->Esp, c->Ebp);
        DWORD* sp = (DWORD*)c->Esp;
        for (int i = 0, shown = 0; i < 160 && shown < 10; ++i) {
            DWORD v = 0;
            __try { v = sp[i]; } __except (EXCEPTION_EXECUTE_HANDLER) { break; }
            HMODULE h2 = NULL;
            if (v > 0x10000 && GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)v, &h2) && h2) {
                char m2[MAX_PATH]; m2[0] = 0; GetModuleFileNameA(h2, m2, MAX_PATH);
                const char* b = strrchr(m2, '\\'); b = b ? b + 1 : m2;
                printf("   stack[%d] %08X = %s+%08X\n", i, v, b, (unsigned)(v - (DWORD)(ULONG_PTR)h2));
                shown++;
            }
        }
    }
    return EXCEPTION_CONTINUE_SEARCH;
}
int main(int argc, char** argv) {
    AddVectoredExceptionHandler(1, harnessVeh);
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc < 4) { printf("usage: rt_harness off|on <frames> <out.txt>\n"); return 2; }
    bool rt = strcmp(argv[1], "on") == 0; int frames = atoi(argv[2]);
    bool optNoFpu = false, optBench = false, optWrap = false;
    for (int i = 4; i < argc; ++i) { if (!strcmp(argv[i], "nofpu")) optNoFpu = true; else if (!strcmp(argv[i], "bench")) optBench = true; else if (!strcmp(argv[i], "wrap")) optWrap = true; }
    // MULTITHREADED: the game runs on DXVK, which is safe to call from more than one thread; the Microsoft
    // runtime is only safe with this flag, and without it the render thread faults inside it. nofpu: device
    // may change the thread's x87 precision.
    DWORD behavior = (optNoFpu ? 0x40u : (0x40u | 0x2u)) | 0x4u;
    SetEnvironmentVariableA("DXVK_CONFIG", "dxvk.hud=");
    SetEnvironmentVariableA("DXVK_LOG_LEVEL", "none");
    SetEnvironmentVariableA("DXVK_STATE_CACHE", "0");
    HMODULE hx = LoadLibraryA("d3dx9_27.dll"); if (!hx) { printf("no d3dx9_27\n"); return 3; }
    HMODULE hd3d = LoadLibraryA("d3d9.dll"); if (!hd3d) { printf("no d3d9\n"); return 3; }
    typedef int (__cdecl* InstallF)(void*, void*); typedef void (__cdecl* StatsF)(char*, int); typedef void* (__cdecl* ScopedF)(const char*); typedef void (__cdecl* ToggleF)(int); ToggleF rtToggle = NULL;
    InstallF rtInstall = NULL; StatsF rtStats = NULL; ScopedF rtScoped = NULL;
    typedef void (__cdecl* PixelF)(void*, DWORD, DWORD, DWORD, DWORD); PixelF pixelOp = pixelOpDirect_cdecl;
    typedef void (__cdecl* ShroudF)(void*, DWORD, DWORD, DWORD, DWORD, const BYTE*, DWORD); ShroudF shroudRect = shroudRectDirect;
    typedef void (__cdecl* RadarF)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD); RadarF radarOp = radarDirect;
    if (rt) {
        SetEnvironmentVariableA("PYSAGE_EXPERIMENTAL_RT", "1");
        HMODULE ha = LoadLibraryA("pysage_accel.dll"); if (!ha) { printf("no pysage_accel.dll (%lu)\n", GetLastError()); return 3; }
        rtInstall = (InstallF)GetProcAddress(ha, "AotrRtTestInstall"); rtStats = (StatsF)GetProcAddress(ha, "AotrRtTestStats");
        rtScoped = (ScopedF)GetProcAddress(ha, "AotrRtTestScopedD3DX");
        rtToggle = (ToggleF)GetProcAddress(ha, "AotrRtTestToggle");
        pixelOp = (PixelF)GetProcAddress(ha, "AotrRtTestPixelOp"); if (!pixelOp) { printf("missing AotrRtTestPixelOp\n"); return 3; }
        shroudRect = (ShroudF)GetProcAddress(ha, "AotrRtTestShroudRect"); if (!shroudRect) { printf("missing AotrRtTestShroudRect\n"); return 3; }
        radarOp = (RadarF)GetProcAddress(ha, "AotrRtTestRadarOp"); if (!radarOp) { printf("missing AotrRtTestRadarOp\n"); return 3; }
        if (optWrap) { typedef void (__cdecl* SeqF)(DWORD); SeqF sb = (SeqF)GetProcAddress(ha, "AotrRtTestSeqBase"); if (!sb) { printf("missing AotrRtTestSeqBase\n"); return 3; } sb(0xFFFFC000u); printf("queue sequence starts 16384 records before the 32-bit wrap\n"); }
        if (!rtInstall || !rtStats || !rtScoped) { printf("missing test exports\n"); return 3; }
        // AotrRtTestInstall initializes the render subsystem explicitly.
    }
    typedef void* (WINAPI* Create9F)(UINT);
    typedef HRESULT (WINAPI* CreateEffectF)(void*, const char*, UINT, void*, void*, DWORD, void*, void**, void**);
    typedef HRESULT (WINAPI* CreateTextureF)(void*, UINT, UINT, UINT, DWORD, DWORD, DWORD, void**);
    typedef HRESULT (WINAPI* FilterTextureF)(void*, void*, UINT, DWORD);
    Create9F Create9 = (Create9F)GetProcAddress(hd3d, "Direct3DCreate9");
    CreateEffectF CreateEffect = (CreateEffectF)GetProcAddress(hx, "D3DXCreateEffect");
    CreateTextureF D3DXCreateTexture = (CreateTextureF)GetProcAddress(hx, "D3DXCreateTexture");
    FilterTextureF D3DXFilterTexture = (FilterTextureF)GetProcAddress(hx, "D3DXFilterTexture");

    WNDCLASSA wc = {0}; wc.lpfnWndProc = DefWindowProcA; wc.hInstance = GetModuleHandleA(NULL); wc.lpszClassName = "rtharness";
    RegisterClassA(&wc);
    HWND hwnd = CreateWindowExA(WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW, "rtharness", "rt", WS_POPUP, -3000, -3000, 640, 480, NULL, NULL, wc.hInstance, NULL);
    ShowWindow(hwnd, SW_SHOWNOACTIVATE);
    void* d3d = Create9(32); if (!d3d) { printf("Direct3DCreate9 failed\n"); return 4; }
    PP pp = {0}; pp.BackBufferWidth = 640; pp.BackBufferHeight = 480; pp.BackBufferFormat = 21; pp.BackBufferCount = 1;
    pp.SwapEffect = 1; pp.hDeviceWindow = hwnd; pp.Windowed = TRUE; pp.EnableAutoDepthStencil = TRUE; pp.AutoDepthStencilFormat = 75; pp.PresentationInterval = 0x80000000;
    void* dev = NULL;
    HRESULT hr = ((HRESULT(WINAPI*)(void*, UINT, DWORD, HWND, DWORD, PP*, void**))vt(d3d)[16])(d3d, 0, 1, hwnd, behavior, &pp, &dev);
    if (FAILED(hr) || !dev) { printf("CreateDevice hr=0x%08lX\n", (unsigned long)hr); return 4; }

    void* fx = NULL, *err = NULL;
    hr = CreateEffect(dev, kFx, (UINT)strlen(kFx), NULL, NULL, 0, NULL, &fx, &err);
    if (FAILED(hr) || !fx) { printf("D3DXCreateEffect hr=0x%08lX %s\n", (unsigned long)hr, err ? (char*)((void*(WINAPI*)(void*))vt(err)[3])(err) : ""); return 5; }
    #define H(name) ((DWORD(WINAPI*)(void*, DWORD, const char*))vt(fx)[9])(fx, 0, name)
    DWORD hWorld = H("World"), hVP = H("ViewProj"), hLVP = H("LightViewProj"), hBones = H("Bones"), hColor = H("MatColor"),
          hBlend = H("Blend"), hTint = H("Tint"), hDiff = H("DiffuseTex"), hShadow = H("ShadowTex");
    DWORD tMain = ((DWORD(WINAPI*)(void*, const char*))vt(fx)[13])(fx, "Main"), tShadow = ((DWORD(WINAPI*)(void*, const char*))vt(fx)[13])(fx, "_CreateShadowMap");
    if (!hWorld || !hBones || !tMain || !tShadow) { printf("handles missing\n"); return 5; }
    static const char kLong[] = "ThisParameterNameIsLongerThanFortyCharactersForTheCache";
    DWORD hLong = H(kLong), hMat = H("Mat");
    DWORD hMatVal = ((DWORD(WINAPI*)(void*, DWORD, const char*))vt(fx)[9])(fx, hMat, "Val");
    DWORD hMatValByName = ((DWORD(WINAPI*)(void*, const char*, const char*))vt(fx)[9])(fx, "Mat", "Val");
    if (!hLong || !hMat || !hMatVal || hMatVal != hMatValByName) { printf("v5 handles missing or inconsistent (%08lX %08lX %08lX %08lX)\n", hLong, hMat, hMatVal, hMatValByName); return 5; }

    // resources
    struct V { float x, y, z, nx, ny, nz, u, v; };
    V cube[24]; WORD idx[36]; int vi = 0, ii = 0;
    const float n[6][3] = {{0,0,-1},{0,0,1},{-1,0,0},{1,0,0},{0,1,0},{0,-1,0}};
    for (int f = 0; f < 6; ++f) {
        float nx = n[f][0], ny = n[f][1], nz = n[f][2];
        float ux = ny ? 1.0f : (nz ? 1.0f : 0.0f), uy = 0, uz = ny ? 0.0f : (nx ? 1.0f : 0.0f);
        float wx = ny*uz - nz*uy, wy = nz*ux - nx*uz, wz = nx*uy - ny*ux;
        for (int k = 0; k < 4; ++k) { float a = (k == 0 || k == 3) ? -1.0f : 1.0f, b = (k < 2) ? -1.0f : 1.0f;
            V& q = cube[vi + k]; q.x = nx + a*ux + b*wx; q.y = ny + a*uy + b*wy; q.z = nz + a*uz + b*wz; q.nx = nx; q.ny = ny; q.nz = nz; q.u = (a+1)/2; q.v = (b+1)/2; }
        WORD b0 = (WORD)vi; WORD t[6] = {0,1,2,0,2,3}; for (int k = 0; k < 6; ++k) idx[ii++] = b0 + t[k]; vi += 4;
    }
    void* vb = NULL, *ib = NULL, *dvb = NULL, *tex = NULL, *dyntex = NULL, *srt = NULL, *srtSurf = NULL, *sz = NULL, *bb = NULL, *bbz = NULL, *cap = NULL, *sys = NULL, *decl = NULL, *sblock = NULL;
    CALL6(dev, 26, sizeof(cube), 0, 0, 1, &vb, 0); void* p = NULL;
    CALL4(vb, 11, 0, 0, &p, 0); memcpy(p, cube, sizeof(cube)); CALL0(vb, 12);
    CALL6(dev, 27, sizeof(idx), 0, 101, 1, &ib, 0); CALL4(ib, 11, 0, 0, &p, 0); memcpy(p, idx, sizeof(idx)); CALL0(ib, 12);
    CALL6(dev, 26, 600 * 20, 0x200 | 8, 0x4 | 0x40, 0, &dvb, 0);
    CALL8(dev, 23, 64, 64, 0, 0, 21, 1, &tex, 0);
    { LOCKED_RECT lr; CALL4(tex, 19, 0, &lr, 0, 0); for (int y = 0; y < 64; ++y) for (int x = 0; x < 64; ++x) ((DWORD*)lr.pBits)[y*64+x] = 0xFF000000 | ((x*4) << 16) | ((y*4) << 8) | (((x^y) & 8) ? 0xFF : 0x40); CALL1(tex, 20, 0); }
    CALL8(dev, 23, 32, 32, 1, 0, 21, 1, &dyntex, 0);
    CALL8(dev, 23, 256, 256, 1, 1, 21, 0, &srt, 0); CALL2(srt, 18, 0, &srtSurf);
    CALL8(dev, 29, 256, 256, 75, 0, 0, 1, &sz, 0);
    CALL4(dev, 18, 0, 0, 0, &bb); CALL1(dev, 40, &bbz);
    CALL8(dev, 28, 640, 480, 21, 0, 0, 0, &cap, 0);
    CALL6(dev, 36, 640, 480, 21, 2, &sys, 0);
    VELEM el[4] = { {0,0,2,0,0,0}, {0,12,2,0,3,0}, {0,24,1,0,5,0}, {0xFF,0,17,0,0,0} };
    CALL2(dev, 86, el, &decl);
    CALL2(dev, 59, 1, &sblock);
    if (!vb || !ib || !dvb || !tex || !dyntex || !srtSurf || !sz || !bb || !bbz || !cap || !sys || !decl || !sblock) { printf("resource creation failed\n"); return 6; }
    void* sysSurf2 = NULL, *defTex = NULL, *defSurf = NULL, *sysTex = NULL, *defTex2 = NULL, *texLvl = NULL;
    CALL6(dev, 36, 64, 64, 21, 2, &sysSurf2, 0);                           // SYSTEMMEM offscreen plain surface
    CALL8(dev, 23, 64, 64, 1, 0, 21, 0, &defTex, 0); if (defTex) CALL2(defTex, 18, 0, &defSurf);   // DEFAULT texture
    CALL8(dev, 23, 64, 64, 1, 0, 21, 2, &sysTex, 0);                       // SYSTEMMEM texture
    CALL8(dev, 23, 64, 64, 1, 0, 21, 0, &defTex2, 0);                      // DEFAULT texture
    CALL2(tex, 18, 0, &texLvl);                                              // level of a MANAGED texture: not a render target
    if (!sysSurf2 || !defSurf || !sysTex || !defTex2 || !texLvl) { printf("resource creation (v4 cases) failed\n"); return 6; }
    int sysMismatch = 0, mirrorMismatch = 0, lockedMismatch = 0;
    void* pixTex = NULL, *pixSurf = NULL; CALL8(dev, 23, 64, 64, 1, 0, 21, 1, &pixTex, 0); if (pixTex) CALL2(pixTex, 18, 0, &pixSurf);   // MANAGED, like the minimap
    if (!pixSurf) { printf("pixel texture failed\n"); return 6; }
    void* shrTex32 = NULL, *shrSurf32 = NULL, *shrTex16 = NULL, *shrSurf16 = NULL;
    CALL8(dev, 23, 64, 64, 1, 0, 21, 1, &shrTex32, 0); if (shrTex32) CALL2(shrTex32, 18, 0, &shrSurf32);   // MANAGED A8R8G8B8, like the 32-bit shroud
    CALL8(dev, 23, 64, 64, 1, 0, 26, 1, &shrTex16, 0); if (shrTex16) CALL2(shrTex16, 18, 0, &shrSurf16);   // MANAGED A4R4G4B4, like the 16-bit shroud
    if (!shrSurf32 || !shrSurf16) { printf("shroud textures failed\n"); return 6; }
    struct TVB { float x, y, z, w; DWORD c; float u, v; };
    void* rmVB = NULL; CALL6(dev, 26, 8 * sizeof(TVB), 0, 0x4 | 0x40 | 0x100, 1, &rmVB, 0);         // MANAGED, plain locks read and modify it
    if (!rmVB) { printf("vertex buffer failed\n"); return 6; }
    { TVB* v = NULL; if (SUCCEEDED(CALL4(rmVB, 11, 0, 0, &v, 0)) && v) { for (int i = 0; i < 8; ++i) { TVB t = { 700.0f + (i % 2) * 64.0f, 20.0f + (i / 2) * 32.0f, 0, 1, 0xFF102030u + (DWORD)i * 0x00030507u, (float)(i % 2), (float)((i / 2) % 2) }; v[i] = t; } CALL0(rmVB, 12); } }
    void* radTex = NULL, *radSurf = NULL; CALL8(dev, 23, 128, 128, 1, 0, 21, 1, &radTex, 0); if (radTex) CALL2(radTex, 18, 0, &radSurf);   // MANAGED A8R8G8B8 128x128, like the radar overlay
    if (!radSurf) { printf("radar texture failed\n"); return 6; }
    void* atlasTex = NULL, *atlasSurf = NULL; CALL8(dev, 23, 256, 256, 1, 0, 25, 1, &atlasTex, 0); if (atlasTex) CALL2(atlasTex, 18, 0, &atlasSurf);   // MANAGED A1R5G5B5, like the terrain tile atlas
    if (!atlasSurf) { printf("atlas texture failed\n"); return 6; }
    void* atlas2Tex = NULL, *atlas2Surf = NULL; CALL8(dev, 23, 256, 256, 0, 0, 25, 1, &atlas2Tex, 0); if (atlas2Tex) CALL2(atlas2Tex, 18, 0, &atlas2Surf);   // the same with a full mip chain, refiltered after every update
    if (!atlas2Surf) { printf("mip-mapped atlas texture failed\n"); return 6; }
    { LOCKED_RECT lr; if (SUCCEEDED(CALL3(atlas2Surf, 13, &lr, 0, 0))) { for (int y = 0; y < 256; ++y) for (int x = 0; x < 256; ++x) ((WORD*)((BYTE*)lr.pBits + y * lr.Pitch))[x] = (WORD)(0x8000u | (((y >> 3) & 31) << 10) | (((x >> 3) & 31) << 5) | ((x + y) & 31)); CALL0(atlas2Surf, 14); } }
    { LOCKED_RECT lr; if (SUCCEEDED(CALL3(atlasSurf, 13, &lr, 0, 0))) { for (int y = 0; y < 256; ++y) for (int x = 0; x < 256; ++x) ((WORD*)((BYTE*)lr.pBits + y * lr.Pitch))[x] = (WORD)(0x8000u | (((x >> 3) & 31) << 10) | (((y >> 3) & 31) << 5) | ((x ^ y) & 31)); CALL0(atlasSurf, 14); } }
    { LOCKED_RECT lr; if (SUCCEEDED(CALL3(radSurf, 13, &lr, 0, 0))) { for (int y = 0; y < 128; ++y) for (int x = 0; x < 128; ++x) ((DWORD*)((BYTE*)lr.pBits + y * lr.Pitch))[x] = 0x80000000u | (DWORD)(x * 2) << 16 | (DWORD)(y * 2) << 8 | (DWORD)((x * y) & 0xFF); CALL0(radSurf, 14); } }
    static BYTE shrRows[64 * 64 * 4];
    DWORD blockC = 0;
    static const GUID kIIDTex9 = {0x85c31227, 0x3de5, 0x4f00, {0x9b, 0x3a, 0xf1, 0x1a, 0xc3, 0x8c, 0x18, 0xb5}};
    BYTE refDesc[44], refTech[12]; DWORD refUsed = 0;
    memset(refDesc, 0, 44); memset(refTech, 0, 12);
    ((HRESULT(WINAPI*)(void*, DWORD, BYTE*))vt(fx)[4])(fx, hWorld, refDesc);
    ((HRESULT(WINAPI*)(void*, DWORD, BYTE*))vt(fx)[5])(fx, tMain, refTech);
    refUsed = ((DWORD(WINAPI*)(void*, DWORD, DWORD))vt(fx)[62])(fx, hWorld, tMain);
    int queryMismatch = 0;
    // parameter block recorded before the render thread exists
    CALL0(fx, 73); { float col[4] = {1, 0.9f, 0.8f, 1}; CALL2(fx, 34, hColor, col); CALL2(fx, 30, hBlend, fbits(0.5f)); }
    DWORD blockA = ((DWORD(WINAPI*)(void*))vt(fx)[74])(fx);

    printf("resources ready (x87 control word now %04x), parameter block handle form %08lX\n", _control87(0, 0) & 0xFFFF, blockA);
    if (rt) { int ok = rtInstall(dev, fx); printf("render thread install: %d\n", ok); if (!ok) return 7;
        { typedef void (__cdecl* AnyF)(int); AnyF any = (AnyF)GetProcAddress(GetModuleHandleA("pysage_accel.dll"), "AotrRtTestAtlasAny"); if (any) any(1); }
        D3DXCreateTexture = (CreateTextureF)rtScoped("D3DXCreateTexture"); D3DXFilterTexture = (FilterTextureF)rtScoped("D3DXFilterTexture"); }
    // a second parameter block recorded through the render thread
    CALL0(fx, 73); { float tint[4] = {0.9f, 1.0f, 1.1f, 1}; CALL2(fx, 34, hTint, tint); }
    DWORD blockB = ((DWORD(WINAPI*)(void*))vt(fx)[74])(fx);

    if (optBench) {                                                   // enqueue cost microbenchmark
        LARGE_INTEGER b0, b1, bf; QueryPerformanceFrequency(&bf);
        QueryPerformanceCounter(&b0);
        for (int i = 0; i < 2000000; ++i) CALL2(dev, 57, 27, i & 1);          // SetRenderState ALPHABLENDENABLE
        QueryPerformanceCounter(&b1);
        printf("bench SetRenderState: %.1f ns/call\n", (double)(b1.QuadPart - b0.QuadPart) * 1e9 / bf.QuadPart / 2000000);
        QueryPerformanceCounter(&b0);
        for (int i = 0; i < 1000000; ++i) CALL4(dev, 100, 0, vb, 0, 32);        // SetStreamSource (object AddRef/Release)
        QueryPerformanceCounter(&b1);
        printf("bench SetStreamSource: %.1f ns/call\n", (double)(b1.QuadPart - b0.QuadPart) * 1e9 / bf.QuadPart / 1000000);
        float m[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
        QueryPerformanceCounter(&b0);
        for (int i = 0; i < 1000000; ++i) ((HRESULT(WINAPI*)(void*, DWORD, const void*, UINT, UINT))vt(fx)[78])(fx, hWorld, m, 0, 64);
        QueryPerformanceCounter(&b1);
        printf("bench SetRawValue(64B): %.1f ns/call\n", (double)(b1.QuadPart - b0.QuadPart) * 1e9 / bf.QuadPart / 1000000);
        { typedef void (__cdecl* Stats4F)(char*, int); Stats4F s4 = (Stats4F)GetProcAddress(GetModuleHandleA("pysage_accel.dll"), "AotrRtTestStatsV4");
          char st[512]; if (s4) { s4(st, sizeof(st)); printf("  after SetRawValue: %s\n", st); } }
        { // parameter writes that keep changing: the value cache misses every time
          float mm[16]; for (int k = 0; k < 16; ++k) mm[k] = (float)k;
          QueryPerformanceCounter(&b0);
          for (int i = 0; i < 1000000; ++i) { mm[0] = (float)i; ((HRESULT(WINAPI*)(void*, DWORD, const void*, UINT, UINT))vt(fx)[78])(fx, hWorld, mm, 0, 64); }
          QueryPerformanceCounter(&b1);
          printf("bench SetRawValue(64B, changing): %.1f ns/call\n", (double)(b1.QuadPart - b0.QuadPart) * 1e9 / bf.QuadPart / 1000000); }
        { float v4[4] = {1,2,3,4};
          QueryPerformanceCounter(&b0);
          for (int i = 0; i < 1000000; ++i) { v4[0] = (float)i; ((HRESULT(WINAPI*)(void*, DWORD, const void*))vt(fx)[34])(fx, hWorld, v4); }
          QueryPerformanceCounter(&b1);
          printf("bench SetVector(changing): %.1f ns/call\n", (double)(b1.QuadPart - b0.QuadPart) * 1e9 / bf.QuadPart / 1000000); }
        { // what the game thread pays: a battle-like run of effect parameter writes closed by device calls, enqueued in
          // bursts small enough never to wait for the worker; the backlog is drained between bursts, outside the timing
          float mm[16]; for (int k = 0; k < 16; ++k) mm[k] = (float)k;
          float v4[4] = {1, 2, 3, 4};
          LONGLONG ticks = 0; LONG calls = 0;
          typedef void (__cdecl* HoldF)(int); HoldF hold = (HoldF)GetProcAddress(GetModuleHandleA("pysage_accel.dll"), "AotrRtTestHold");
          for (int burst = 0; burst < 24; ++burst) {
              if (hold) hold(1);                                                                      // worker parked: the enqueue path alone
              QueryPerformanceCounter(&b0);
              for (int i = 0; i < 3000; ++i) {
                  mm[0] = (float)i; v4[0] = (float)(i + burst);
                  ((HRESULT(WINAPI*)(void*, DWORD, const void*))vt(fx)[44])(fx, hWorld, mm);          // SetMatrixTranspose
                  ((HRESULT(WINAPI*)(void*, DWORD, const void*))vt(fx)[44])(fx, hLVP, mm);
                  for (int k = 0; k < 4; ++k) ((HRESULT(WINAPI*)(void*, DWORD, const void*))vt(fx)[34])(fx, hTint, v4);      // SetVector
                  for (int k = 0; k < 3; ++k) ((HRESULT(WINAPI*)(void*, DWORD, DWORD))vt(fx)[30])(fx, hBlend, fbits(0.5f + k)); // SetFloat
                  for (int k = 0; k < 2; ++k) ((HRESULT(WINAPI*)(void*, DWORD, DWORD))vt(fx)[26])(fx, hBlend, (DWORD)k);        // SetInt
                  for (int k = 0; k < 2; ++k) ((HRESULT(WINAPI*)(void*, DWORD, void*))vt(fx)[52])(fx, hDiff, tex);              // SetTexture
                  for (int k = 0; k < 3; ++k) ((HRESULT(WINAPI*)(void*, DWORD, const void*, UINT, UINT))vt(fx)[78])(fx, hWorld, mm, 0, 64);   // SetRawValue
                  CALL2(dev, 57, 27, i & 1);                                                          // SetRenderState: whatever follows the run
                  CALL4(dev, 100, 0, vb, 0, 32);                                                      // SetStreamSource
              }
              QueryPerformanceCounter(&b1);
              ticks += b1.QuadPart - b0.QuadPart; calls += 3000 * 18;
              if (hold) hold(0);
              CALL2(dev, 32, cap, sys);                                                               // drain, untimed
          }
          printf("bench game-like effect run (16 parameter writes + 2 device calls), enqueue only: %.1f ns/call\n", (double)ticks * 1e9 / bf.QuadPart / calls); }
        { typedef void (__cdecl* CpuF)(char*, int); CpuF cf = (CpuF)GetProcAddress(GetModuleHandleA("pysage_accel.dll"), "AotrRtTestCpu");
          char st[1024]; if (cf) { cf(st, sizeof(st)); printf("  cpus during the first three benches: %s\n", st); } }
        { typedef void (__cdecl* ThrF)(char*, int); ThrF tf = (ThrF)GetProcAddress(GetModuleHandleA("pysage_accel.dll"), "AotrRtTestThreads");
          static char st[8192]; if (tf) { tf(st, sizeof(st)); printf("  threads:\n%s", st); } }
        BYTE d[44];
        QueryPerformanceCounter(&b0);
        for (int i = 0; i < 1000000; ++i) ((HRESULT(WINAPI*)(void*, DWORD, BYTE*))vt(fx)[4])(fx, hWorld, d);
        QueryPerformanceCounter(&b1);
        printf("bench GetParameterDesc: %.1f ns/call\n", (double)(b1.QuadPart - b0.QuadPart) * 1e9 / bf.QuadPart / 1000000);
        { LOCKED_RECT lr0; QueryPerformanceCounter(&b0);
          for (int i = 0; i < 200000; ++i) { CALL2(dev, 57, 27, i & 1); if (SUCCEEDED(CALL3(sysSurf2, 13, &lr0, 0, 0))) CALL0(sysSurf2, 14); }
          QueryPerformanceCounter(&b1);
          printf("bench SetRenderState + sysmem LockRect/UnlockRect: %.1f ns/iteration\n", (double)(b1.QuadPart - b0.QuadPart) * 1e9 / bf.QuadPart / 200000); }
        QueryPerformanceCounter(&b0);
        CALL2(dev, 32, cap, sys);                                               // sync point: wait for the worker to finish the backlog
        QueryPerformanceCounter(&b1);
        printf("bench drain of the backlog: %.1f ms\n", (double)(b1.QuadPart - b0.QuadPart) * 1e3 / bf.QuadPart);
        { typedef void (__cdecl* Stats4F)(char*, int); Stats4F s4 = (Stats4F)GetProcAddress(GetModuleHandleA("pysage_accel.dll"), "AotrRtTestStatsV4");
          char st[512]; if (s4) { s4(st, sizeof(st)); printf("bench wait stats: %s\n", st); } }
        return 0;
    }
    printf("entering frame loop\n");
    g_vehOn = 1;
    FILE* out = NULL;
    if (fopen_s(&out, argv[3], "w") != 0 || !out) {
        fprintf(stderr, "Cannot open frame output: %s\n", argv[3]);
        return 6;
    }
    LARGE_INTEGER qf, t0, t1; QueryPerformanceFrequency(&qf); QueryPerformanceCounter(&t0);
    void* extraTex = NULL;
    for (int fr = 0; fr < frames; ++fr) {
        float time = fr * 0.05f;
        { BYTE d[44]; BYTE t[12]; memset(d, 0xCD, 44); memset(t, 0xCD, 12);
          ((HRESULT(WINAPI*)(void*, DWORD, BYTE*))vt(fx)[4])(fx, hWorld, d);
          ((HRESULT(WINAPI*)(void*, DWORD, BYTE*))vt(fx)[5])(fx, tMain, t);
          DWORD hw = ((DWORD(WINAPI*)(void*, DWORD, const char*))vt(fx)[9])(fx, 0, "World");
          DWORD tm = ((DWORD(WINAPI*)(void*, const char*))vt(fx)[13])(fx, "Main");
          DWORD used = ((DWORD(WINAPI*)(void*, DWORD, DWORD))vt(fx)[62])(fx, hWorld, tMain);
          if (memcmp(d, refDesc, 44) || memcmp(t, refTech, 12) || hw != hWorld || tm != tMain || used != refUsed) queryMismatch++;
          DWORD hl = ((DWORD(WINAPI*)(void*, DWORD, const char*))vt(fx)[9])(fx, 0, kLong);
          DWORD hv = ((DWORD(WINAPI*)(void*, const char*, const char*))vt(fx)[9])(fx, "Mat", "Val");
          if (hl != hLong || hv != hMatVal) queryMismatch++; }
        if (rtToggle && fr > 0 && fr % 50 == 0) rtToggle((fr / 50) % 2 == 0);   // switch the render thread off/on every 50 frames
        float vp[16], lvp[16], world[16], bones[48];
        matLookProj(vp, static_cast<float>(6 * cos(time * 0.3f)), 5, static_cast<float>(6 * sin(time * 0.3f)), 1.2f);
        matLookProj(lvp, 4, 9, 3, 0.8f);
        CALL0(dev, 41);                                                   // BeginScene
        // shadow pass into the render-target texture
        CALL2(dev, 37, 0, srtSurf); CALL1(dev, 39, sz);
        { void* x = NULL; HRESULT h1 = CALL2(dev, 38, 0, &x); if (FAILED(h1) || x != srtSurf) mirrorMismatch++; if (x) CALL0(x, 2);
          void* y = NULL; HRESULT h2 = CALL1(dev, 40, &y); if (FAILED(h2) || y != sz) mirrorMismatch++; if (y) CALL0(y, 2);
          void* z = (void*)1; HRESULT h3 = CALL2(dev, 38, 1, &z); if (h3 != (HRESULT)0x88760866 || z != NULL) mirrorMismatch++;
          HRESULT h4 = CALL2(dev, 37, 0, texLvl); if (SUCCEEDED(h4) && rt == false) mirrorMismatch++;          // not a render target: must fail
          void* w = NULL; CALL2(dev, 38, 0, &w); if (w != srtSurf) mirrorMismatch++; if (w) CALL0(w, 2); }
        CALL6(dev, 43, 0, 0, 1 | 2, 0xFFFFFFFF, fbits(1.0f), 0);
        CALL1(fx, 58, tShadow); UINT np = 0; CALL2(fx, 63, &np, 6); CALL1(fx, 64, 0);
        CALL2(fx, 38, hLVP, lvp);
        for (int o = 0; o < 20; ++o) {
            matWorld(world, (o % 5) * 2.2f - 4.4f, static_cast<float>(0.5f * sin(time + o)), (o / 5) * 2.2f - 3.3f, time + o * 0.3f, 0.6f);
            for (int b = 0; b < 4; ++b) { memset(bones + b*12, 0, 12*sizeof(float)); bones[b*12] = bones[b*12+5] = bones[b*12+10] = 1; bones[b*12+3] = static_cast<float>(0.1f * sin(time * (b + 1))); }
            ((HRESULT(WINAPI*)(void*, DWORD, const void*, UINT, UINT))vt(fx)[78])(fx, hWorld, world, 0, 64);
            ((HRESULT(WINAPI*)(void*, DWORD, const void*, UINT, UINT))vt(fx)[78])(fx, hBones, bones, 0, 48);
            CALL0(fx, 65);
            CALL1(dev, 87, decl); CALL4(dev, 100, 0, vb, 0, 32); CALL1(dev, 104, ib);
            CALL6(dev, 82, 4, 0, 0, 24, 0, 12);
        }
        CALL0(fx, 66); CALL0(fx, 67);
        // main pass
        CALL2(dev, 37, 0, bb); CALL1(dev, 39, bbz);
        { void* x = NULL; CALL2(dev, 38, 0, &x); if (x != bb) mirrorMismatch++; if (x) CALL0(x, 2);
          void* y = NULL; CALL1(dev, 40, &y); if (y != bbz) mirrorMismatch++; if (y) CALL0(y, 2);
          CALL1(dev, 39, 0); void* n0 = (void*)1; HRESULT hn = CALL1(dev, 40, &n0); if (hn != (HRESULT)0x88760866 || n0 != NULL) mirrorMismatch++;
          CALL1(dev, 39, bbz);
          if (CALL0(dev, 3) != 0) lockedMismatch++;                                                          // TestCooperativeLevel
          void* b2 = NULL; CALL4(dev, 18, 0, 0, 0, &b2); if (b2 != bb) lockedMismatch++; if (b2) CALL0(b2, 2);   // GetBackBuffer
          void* q9 = NULL; if (FAILED(CALL2(tex, 0, &kIIDTex9, &q9)) || q9 != tex) lockedMismatch++; if (q9) CALL0(q9, 2); }
        CALL6(dev, 43, 0, 0, 1 | 2, 0xFF203040 + fr, fbits(1.0f), 0);
        CALL0(sblock, 4);                                              // application state block: capture
        CALL1(fx, 58, tMain); CALL2(fx, 63, &np, 6); CALL1(fx, 64, 0);
        if (blockC) CALL1(fx, 76, blockC);
        CALL0(fx, 73);
        { float t4[4] = {0.8f + 0.2f * (float)sin(time), 1.0f, 0.9f + 0.1f * (float)cos(time * 0.7f), 1.0f}; CALL2(fx, 34, hTint, t4);
          CALL2(fx, 30, hLong, fbits(0.9f + 0.1f * (float)cos(time))); CALL2(fx, 30, hMatVal, fbits(0.95f + 0.05f * (float)sin(time * 1.3f))); }
        blockC = ((DWORD(WINAPI*)(void*))vt(fx)[74])(fx);
        CALL1(fx, 75, (fr % 3 == 0) ? blockC : ((fr & 1) ? blockA : blockB));
        if (rt && argc > 4 && !strcmp(argv[4], "capture")) { typedef void (__cdecl* CapF)(int); static CapF cap = (CapF)GetProcAddress(GetModuleHandleA("pysage_accel.dll"), "AotrRtTestCaptureTick"); if (cap) cap(fr); }
        if (fr % 3 == 0) { LOCKED_RECT lr; if (SUCCEEDED(CALL3(atlasSurf, 13, &lr, 0, 0))) {
            for (int k = 0; k < 4; ++k) { int tx = ((fr / 3 + k * 3) & 7) * 32, ty = ((fr / 3 * 5 + k) & 7) * 32;
                for (int y = 0; y < 32; ++y) for (int x = 0; x < 32; ++x) ((WORD*)((BYTE*)lr.pBits + (ty + y) * lr.Pitch))[tx + x] = (WORD)(0x8000u | ((fr * 7 + x * 3 + k) & 0x7FFF)); }
            { int tx = ((fr / 3) & 7) * 32, ty = 224; for (int y = 0; y < 32; ++y) for (int x = 0; x < 32; ++x) { WORD* q = &((WORD*)((BYTE*)lr.pBits + (ty + y) * lr.Pitch))[tx + x]; *q = (WORD)(*q ^ 0x7C1F); } }
            CALL0(atlasSurf, 14); } }
        if (fr % 3 == 1) { LOCKED_RECT lr; if (SUCCEEDED(CALL3(atlas2Surf, 13, &lr, 0, 0))) {                       // the mip-mapped atlas: tiles rewritten, then the mip chain rebuilt (D3DXFilterTexture, box)
            for (int k = 0; k < 3; ++k) { int tx = ((fr / 3 + k * 5) & 7) * 32, ty = ((fr / 3 * 3 + k) & 7) * 32;
                for (int y = 0; y < 32; ++y) for (int x = 0; x < 32; ++x) ((WORD*)((BYTE*)lr.pBits + (ty + y) * lr.Pitch))[tx + x] = (WORD)(0x8000u | ((fr * 11 + x * 5 + y + k) & 0x7FFF)); }
            { int tx = ((fr / 3 + 3) & 7) * 32, ty = 96; for (int y = 0; y < 32; ++y) for (int x = 0; x < 32; ++x) { WORD* q = &((WORD*)((BYTE*)lr.pBits + (ty + y) * lr.Pitch))[tx + x]; *q = (WORD)(*q ^ 0x03E0); } }
            CALL0(atlas2Surf, 14); }
            D3DXFilterTexture(atlas2Tex, NULL, 0, 5); }
        CALL2(fx, 52, hDiff, (fr & 1) ? ((fr & 2) ? atlas2Tex : atlasTex) : tex); CALL2(fx, 52, hShadow, srt);
        CALL2(fx, 38, hVP, vp); CALL2(fx, 38, hLVP, lvp);
        CALL2(fx, 30, hBlend, fbits(static_cast<float>(0.5f + 0.25f * sin(time))));            // preshader input changes every frame
        for (int o = 0; o < 20; ++o) {
            matWorld(world, (o % 5) * 2.2f - 4.4f, static_cast<float>(0.5f * sin(time + o)), (o / 5) * 2.2f - 3.3f, time + o * 0.3f, 0.6f);
            for (int b = 0; b < 4; ++b) { memset(bones + b*12, 0, 12*sizeof(float)); bones[b*12] = bones[b*12+5] = bones[b*12+10] = 1; bones[b*12+3] = static_cast<float>(0.1f * sin(time * (b + 1))); }
            float col[4] = {static_cast<float>(0.5f + 0.5f * sin(o + time)), 0.7f, static_cast<float>(0.5f + 0.5f * cos(o * 0.7f)), 1};
            ((HRESULT(WINAPI*)(void*, DWORD, const void*, UINT, UINT))vt(fx)[78])(fx, hWorld, world, 0, 64);
            ((HRESULT(WINAPI*)(void*, DWORD, const void*, UINT, UINT))vt(fx)[78])(fx, hBones, bones, 0, 48);
            CALL2(fx, 34, hColor, col);
            CALL0(fx, 65);
            CALL1(dev, 87, decl); CALL4(dev, 100, 0, vb, 0, 32); CALL1(dev, 104, ib);
            CALL6(dev, 82, 4, 0, 0, 24, 0, 12);
        }
        CALL0(fx, 66); CALL0(fx, 67);
        CALL0(sblock, 5);                                              // application state block: apply
        // dynamic texture update + textured quad through DrawPrimitiveUP
        { LOCKED_RECT lr; CALL4(dyntex, 19, 0, &lr, 0, 0); for (int y = 0; y < 32; ++y) for (int x = 0; x < 32; ++x) ((DWORD*)lr.pBits)[y*32+x] = 0xFF000000 | (((x + fr) * 8) & 0xFF) << 16 | ((y * 8) << 8); CALL1(dyntex, 20, 0); }
        CALL2(dev, 57, 7, 0); CALL1(dev, 107, 0); CALL1(dev, 92, 0); CALL1(dev, 89, 0x4 | 0x40 | 0x100); CALL2(dev, 65, 0, dyntex);
        CALL3(dev, 69, 0, 5, 1); CALL3(dev, 69, 0, 6, 1);
        struct TV { float x, y, z, w; DWORD c; float u, v; } q[4] = { {10,10,0,1,0xFFFFFFFF,0,0}, {138,10,0,1,0xFFFFFFFF,1,0}, {10,138,0,1,0xFFFFFFFF,0,1}, {138,138,0,1,0xFFFFFFFF,1,1} };
        CALL4(dev, 83, 5, 2, q, sizeof(TV));
        // particles through a dynamic vertex buffer (DISCARD)
        { void* pv = NULL; CALL4(dvb, 11, 0, 0, &pv, 0x2000);
          struct PV { float x, y, z, w; DWORD c; }* v = (PV*)pv;
          for (int k = 0; k < 100; ++k) { float cx = static_cast<float>(320 + 200 * sin(time * 0.7f + k)), cy = static_cast<float>(240 + 150 * cos(time * 0.9f + k * 1.3f)); DWORD c = 0x80000000 | (k * 2 << 16) | (255 - k);
            PV quad[6] = { {cx-6,cy-6,0,1,c}, {cx+6,cy-6,0,1,c}, {cx-6,cy+6,0,1,c}, {cx+6,cy-6,0,1,c}, {cx+6,cy+6,0,1,c}, {cx-6,cy+6,0,1,c} };
            memcpy(v + k * 6, quad, sizeof(quad)); }
          CALL0(dvb, 12); }
        CALL2(dev, 65, 0, 0); CALL2(dev, 57, 27, 1); CALL2(dev, 57, 19, 5); CALL2(dev, 57, 20, 6);
        CALL1(dev, 89, 0x4 | 0x40); CALL4(dev, 100, 0, dvb, 0, 20); CALL3(dev, 81, 4, 0, 200);
        { void* pv = NULL; CALL4(dvb, 11, 600 * 20 / 2, 300 * 20, &pv, 0x1000);         // NOOVERWRITE: second half
          struct PV { float x, y, z, w; DWORD c; }* v = (PV*)pv;
          for (int k = 0; k < 50; ++k) { float cx = 100 + 8.0f * k, cy = static_cast<float>(60 + 20 * sin(time * 2 + k)); DWORD c = 0xC000FF00 | (k * 4);
            PV quad[6] = { {cx-3,cy-3,0,1,c}, {cx+3,cy-3,0,1,c}, {cx-3,cy+3,0,1,c}, {cx+3,cy-3,0,1,c}, {cx+3,cy+3,0,1,c}, {cx-3,cy+3,0,1,c} };
            memcpy(v + k * 6, quad, sizeof(quad)); }
          CALL0(dvb, 12); }
        CALL3(dev, 81, 4, 300, 100);
        CALL2(dev, 57, 27, 0);
        // indexed user-pointer lines
        { struct LV { float x, y, z, w; DWORD c; } lv[5]; WORD li[8] = {0,1, 1,2, 2,3, 3,4};
          for (int k = 0; k < 5; ++k) { lv[k].x = 20.0f + k * 40; lv[k].y = static_cast<float>(400 + 30 * sin(time + k)); lv[k].z = 0; lv[k].w = 1; lv[k].c = 0xFFFFFF00; }
          CALL8(dev, 84, 2, 0, 5, 4, li, 101, lv, sizeof(LV)); }
        // D3DX creation and mip filtering in the middle of a frame
        if (fr == 10) { D3DXCreateTexture(dev, 64, 64, 0, 0, 21, 1, &extraTex); if (extraTex) { LOCKED_RECT lr; CALL4(extraTex, 19, 0, &lr, 0, 0); memset(lr.pBits, 0x7F, 64 * 64 * 4); CALL1(extraTex, 20, 0); D3DXFilterTexture(extraTex, NULL, 0, 0xFFFFFFFF); } }
        if (extraTex) { CALL2(dev, 65, 0, extraTex); CALL1(dev, 89, 0x4 | 0x40 | 0x100);
            struct TV2 { float x, y, z, w; DWORD c; float u, v; } q2[4] = { {500,10,0,1,0xFFFFFFFF,0,0}, {630,10,0,1,0xFFFFFFFF,1,0}, {500,140,0,1,0xFFFFFFFF,0,1}, {630,140,0,1,0xFFFFFFFF,1,1} };
            CALL4(dev, 83, 5, 2, q2, sizeof(TV2)); CALL2(dev, 65, 0, 0); }
        // a managed texture created mid-frame, filled through level and surface locks, drawn with, then released:
        // nothing queued can name it yet, so the render thread may fill it without draining the queue
        { void* freshTex = NULL;
          if (SUCCEEDED(CALL8(dev, 23, 32, 32, 1, 0, 21, 1, &freshTex, 0)) && freshTex) {
            LOCKED_RECT lr;
            if (SUCCEEDED(CALL4(freshTex, 19, 0, &lr, 0, 0))) {
                for (int y = 0; y < 32; ++y) for (int x = 0; x < 32; ++x)
                    ((DWORD*)((BYTE*)lr.pBits + y * lr.Pitch))[x] = 0xFF000000u | (DWORD)((x * 8 + fr) & 0xFF) << 16 | (DWORD)((y * 8 + fr * 3) & 0xFF) << 8 | (DWORD)((x ^ y) & 0xFF);
                CALL1(freshTex, 20, 0);
            }
            void* lvl = NULL;                                                    // second fill through the level surface
            if (SUCCEEDED(CALL2(freshTex, 18, 0, &lvl)) && lvl) {
                if (SUCCEEDED(CALL3(lvl, 13, &lr, 0, 0))) {
                    for (int x = 0; x < 32; ++x) ((DWORD*)((BYTE*)lr.pBits + ((fr * 5) % 32) * lr.Pitch))[x] = 0xFFFF00FFu ^ (DWORD)(fr * 7 + x);
                    CALL0(lvl, 14);
                }
                CALL0(lvl, 2);
            }
            CALL2(dev, 65, 0, freshTex); CALL1(dev, 89, 0x4 | 0x40 | 0x100);
            struct TVF { float x, y, z, w; DWORD c; float u, v; } qf[4] = { {200,420,0,1,0xFFFFFFFF,0,0}, {264,420,0,1,0xFFFFFFFF,1,0}, {200,470,0,1,0xFFFFFFFF,0,1}, {264,470,0,1,0xFFFFFFFF,1,1} };
            CALL4(dev, 83, 5, 2, qf, sizeof(TVF)); CALL2(dev, 65, 0, 0);
            CALL0(freshTex, 2);
          }
        }
        // shroud-style updates: lock the rect (1,1)-(63,63), copy every row, unlock - 32-bit and 16-bit textures
        for (int k = 0; k < 62 * 62 * 4; ++k) shrRows[k] = (BYTE)((k * 7 + fr * 13) ^ (k >> 5));
        shroudRect(shrSurf32, 1, 1, 63, 63, shrRows, 4);
        shroudRect(shrSurf16, 1, 1, 63, 63, shrRows + 1000, 2);
        { CALL2(dev, 65, 0, shrTex32); CALL1(dev, 89, 0x4 | 0x40 | 0x100);
          struct TV7 { float x, y, z, w; DWORD c; float u, v; } q7[4] = { {390,300,0,1,0xFFFFFFFF,0,0}, {454,300,0,1,0xFFFFFFFF,1,0}, {390,364,0,1,0xFFFFFFFF,0,1}, {454,364,0,1,0xFFFFFFFF,1,1} };
          CALL4(dev, 83, 5, 2, q7, sizeof(TV7));
          CALL2(dev, 65, 0, shrTex16);
          struct TV7 q8[4] = { {470,300,0,1,0xFFFFFFFF,0,0}, {534,300,0,1,0xFFFFFFFF,1,0}, {470,364,0,1,0xFFFFFFFF,0,1}, {534,364,0,1,0xFFFFFFFF,1,1} };
          CALL4(dev, 83, 5, 2, q8, sizeof(TV7)); CALL2(dev, 65, 0, 0); }
        // minimap-style pixel writes: 1x1 LockRect / write / UnlockRect per pixel on a MANAGED texture (colour and alpha variants)
        for (int k = 0; k < 40; ++k) {
            DWORD px = (DWORD)((k * 7 + fr) % 64), py = (DWORD)((k * 13 + fr / 3) % 64);
            pixelOp(pixSurf, px, py, 0xFF000000u | ((DWORD)(k * 6 + fr) & 0xFF) << 16 | ((DWORD)(fr * 5) & 0xFF) << 8 | (DWORD)(k * 3), 4);
            if (k & 1) pixelOp(pixSurf, px, py, (DWORD)(128 + k), 0x100);
        }
        // plain vertex-buffer locks: read the colours and positions, change them from what is there, sometimes only a sub-range
        { TVB* v = NULL;
          DWORD off = (fr % 3 == 1) ? 2 * sizeof(TVB) : 0, sz = (fr % 3 == 1) ? 4 * sizeof(TVB) : 0;
          if (SUCCEEDED(CALL4(rmVB, 11, off, sz, &v, 0)) && v) { int cnt = sz ? 4 : 8; for (int i = 0; i < cnt; ++i) { v[i].c = v[i].c * 5 + 0x01020304u + (DWORD)fr; v[i].y = 20.0f + (float)(((DWORD)(v[i].y * 3.0f) + (DWORD)fr) % 200); } CALL0(rmVB, 12); }
          if (fr % 13 == 7) { if (SUCCEEDED(CALL4(rmVB, 11, 0, 0, &v, 0x2000)) && v) { for (int i = 0; i < 8; ++i) { TVB t = { 700.0f + (i % 2) * 64.0f, 20.0f + (i / 2) * 32.0f, 0, 1, 0xFF405060u ^ (DWORD)(fr * i), (float)(i % 2), (float)((i / 2) % 2) }; v[i] = t; } CALL0(rmVB, 12); } }
          CALL1(dev, 89, 0x4 | 0x40 | 0x100); CALL2(dev, 65, 0, 0); CALL4(dev, 100, 0, rmVB, 0, sizeof(TVB));
          CALL3(dev, 81, 5, 0, 6); CALL4(dev, 100, 0, 0, 0, 0); }
        // radar-overlay style updates: rect read-modify-write, whole-surface read-modify-write, clears, pixel writes, and a foreign texture lock
        {
            DWORD l = (DWORD)((fr * 5) % 100), t = (DWORD)((fr * 3) % 90);
            radarOp(radSurf, 1, l, t, l + 20, t + 30, (DWORD)fr);
            if (fr % 11 == 3) radarOp(radSurf, 1, 120, 0, 140, 10, 7);                                   // out of bounds: fails either way
            radarOp(radSurf, 1, (DWORD)((fr * 17) % 64), 64, (DWORD)((fr * 17) % 64) + 64, 128, (DWORD)(fr * 11));
            for (int k = 0; k < 30; ++k) {
                DWORD px = (DWORD)((k * 29 + fr * 3) % 128), py = (DWORD)((k * 31 + fr) % 128);
                pixelOp(radSurf, px, py, 0xFF000000u | (DWORD)((k * 9 + fr) & 0xFF) << 8 | (DWORD)k, 4);
                if (k % 3 == 0) pixelOp(radSurf, px, py, (DWORD)(40 + k), 0x100);
            }
            if (fr % 7 == 2) radarOp(radSurf, 3, 0, 0, 0, 0, (DWORD)(fr + 1));
            if (fr % 17 == 5) radarOp(radSurf, 2, (DWORD)(fr & 1), 0, 0, 0, 0);
            if (fr % 97 == 50) { LOCKED_RECT lr; if (SUCCEEDED(CALL4(radTex, 19, 0, &lr, 0, 0))) { for (int y = 40; y < 50; ++y) for (int x = 0; x < 128; ++x) ((DWORD*)((BYTE*)lr.pBits + y * lr.Pitch))[x] ^= 0x00FF00FFu; CALL1(radTex, 20, 0); } }
        }
        { CALL2(dev, 65, 0, radTex); CALL1(dev, 89, 0x4 | 0x40 | 0x100);
          struct TV9 { float x, y, z, w; DWORD c; float u, v; } q9[4] = { {550,300,0,1,0xFFFFFFFF,0,0}, {678,300,0,1,0xFFFFFFFF,1,0}, {550,428,0,1,0xFFFFFFFF,0,1}, {678,428,0,1,0xFFFFFFFF,1,1} };
          CALL4(dev, 83, 5, 2, q9, sizeof(TV9)); CALL2(dev, 65, 0, 0); }
        { CALL2(dev, 65, 0, pixTex); CALL1(dev, 89, 0x4 | 0x40 | 0x100);
          struct TV6 { float x, y, z, w; DWORD c; float u, v; } q6[4] = { {310,300,0,1,0xFFFFFFFF,0,0}, {374,300,0,1,0xFFFFFFFF,1,0}, {310,364,0,1,0xFFFFFFFF,0,1}, {374,364,0,1,0xFFFFFFFF,1,1} };
          CALL4(dev, 83, 5, 2, q6, sizeof(TV6)); CALL2(dev, 65, 0, 0); }
        // system-memory surface: write, UpdateSurface into a DEFAULT texture, READONLY re-lock while the update is still queued
        { LOCKED_RECT lr;
          if (SUCCEEDED(CALL3(sysSurf2, 13, &lr, 0, 0))) {
              for (int y = 0; y < 64; ++y) for (int x = 0; x < 64; ++x) ((DWORD*)((BYTE*)lr.pBits + y * lr.Pitch))[x] = 0xFF000000 | (((x * 4 + fr * 3) & 0xFF) << 16) | (((y * 4) & 0xFF) << 8) | (fr & 0xFF);
              CALL0(sysSurf2, 14); } else sysMismatch++;
          CALL4(dev, 30, sysSurf2, 0, defSurf, 0);
          if (SUCCEEDED(CALL3(sysSurf2, 13, &lr, 0, 0x10))) { DWORD px = ((DWORD*)lr.pBits)[0]; if (px != (0xFF000000u | (((fr * 3) & 0xFF) << 16) | (fr & 0xFF))) sysMismatch++; CALL0(sysSurf2, 14); } else sysMismatch++;
          CALL2(dev, 65, 0, defTex); CALL1(dev, 89, 0x4 | 0x40 | 0x100);
          struct TV4 { float x, y, z, w; DWORD c; float u, v; } q4[4] = { {150,300,0,1,0xFFFFFFFF,0,0}, {214,300,0,1,0xFFFFFFFF,1,0}, {150,364,0,1,0xFFFFFFFF,0,1}, {214,364,0,1,0xFFFFFFFF,1,1} };
          CALL4(dev, 83, 5, 2, q4, sizeof(TV4)); CALL2(dev, 65, 0, 0); }
        // system-memory texture: LockRect on the texture, UpdateTexture; every 5th frame again through its level surface while the first update is queued
        { LOCKED_RECT lr;
          if (SUCCEEDED(CALL4(sysTex, 19, 0, &lr, 0, 0))) {
              for (int y = 0; y < 64; ++y) for (int x = 0; x < 64; ++x) ((DWORD*)((BYTE*)lr.pBits + y * lr.Pitch))[x] = 0xFF000000 | (((y * 3 + fr) & 0xFF) << 16) | ((x * 4) & 0xFF);
              CALL1(sysTex, 20, 0); } else sysMismatch++;
          CALL2(dev, 31, sysTex, defTex2);
          if (fr % 5 == 2) { void* ls = NULL; CALL2(sysTex, 18, 0, &ls);
              if (ls) { if (SUCCEEDED(CALL3(ls, 13, &lr, 0, 0))) { for (int y = 20; y < 30; ++y) for (int x = 0; x < 64; ++x) ((DWORD*)((BYTE*)lr.pBits + y * lr.Pitch))[x] = 0xFFFFFF00 | (DWORD)fr; CALL0(ls, 14); } else sysMismatch++;
                        CALL0(ls, 2); }
              CALL2(dev, 31, sysTex, defTex2); }
          CALL2(dev, 65, 0, defTex2); CALL1(dev, 89, 0x4 | 0x40 | 0x100);
          struct TV5 { float x, y, z, w; DWORD c; float u, v; } q5[4] = { {230,300,0,1,0xFFFFFFFF,0,0}, {294,300,0,1,0xFFFFFFFF,1,0}, {230,364,0,1,0xFFFFFFFF,0,1}, {294,364,0,1,0xFFFFFFFF,1,1} };
          CALL4(dev, 83, 5, 2, q5, sizeof(TV5)); CALL2(dev, 65, 0, 0); }
        // object churn: child surface get/release every frame; a short-lived texture created, filled, bound,
        // drawn and released while its queued SetTexture still references it
        { void* lvl = NULL; CALL2(dyntex, 18, 0, &lvl); if (lvl) CALL0(lvl, 2); }
        if (fr % 7 == 3) {
            void* t = NULL; CALL8(dev, 23, 16, 16, 1, 0, 21, 1, &t, 0);
            if (t) { LOCKED_RECT lr; CALL4(t, 19, 0, &lr, 0, 0); for (int k = 0; k < 256; ++k) ((DWORD*)lr.pBits)[k] = 0xFF00FF00 | (DWORD)(fr * 37 + k);
                CALL1(t, 20, 0); CALL2(dev, 65, 0, t); CALL1(dev, 89, 0x4 | 0x40 | 0x100);
                struct TV3 { float x, y, z, w; DWORD c; float u, v; } q3[4] = { {300,300,0,1,0xFFFFFFFF,0,0}, {364,300,0,1,0xFFFFFFFF,1,0}, {300,364,0,1,0xFFFFFFFF,0,1}, {364,364,0,1,0xFFFFFFFF,1,1} };
                CALL4(dev, 83, 5, 2, q3, sizeof(TV3)); CALL2(dev, 65, 0, 0); CALL0(t, 2); }
        }
        // a surface fetched from the device and released in the same frame
        { void* rtS = NULL; CALL2(dev, 38, 0, &rtS); if (rtS) CALL0(rtS, 2); }
        CALL0(dev, 42);                                                   // EndScene
        // read back and hash
        CALL5(dev, 34, bb, 0, cap, 0, 1);
        CALL2(dev, 32, cap, sys);
        LOCKED_RECT lr; unsigned long long h = 1469598103934665603ull;
        if (SUCCEEDED(CALL3(sys, 13, &lr, 0, 0x10))) { for (int y = 0; y < 480; ++y) h = fnv((BYTE*)lr.pBits + y * lr.Pitch, 640 * 4, h); CALL0(sys, 14); }
        { DWORD tMain = ((DWORD(WINAPI*)(void*, const char*))vt(fx)[13])(fx, "Main");                  // annotation reads, as the engine does per skinned mesh
          DWORD ha = ((DWORD(WINAPI*)(void*, DWORD, const char*))vt(fx)[19])(fx, tMain, "MaxSkinningBones");
          DWORD hb = ((DWORD(WINAPI*)(void*, DWORD, DWORD))vt(fx)[18])(fx, tMain, 0);
          INT va = -1, vb = -1;
          for (int k = 0; k < 3; ++k) { ((HRESULT(WINAPI*)(void*, DWORD, INT*))vt(fx)[27])(fx, ha, &va); ((HRESULT(WINAPI*)(void*, DWORD, INT*))vt(fx)[27])(fx, hb, &vb); }
          h ^= (unsigned long long)(DWORD)(va * 131 + vb * 7 + (ha ? 1 : 0) + (hb ? 2 : 0)) << 20; }
        if (fr == 100 || fr == 400 || fr == frames - 1) for (int lv = 1; lv <= 3; lv += 2) { LOCKED_RECT ml;
            if (SUCCEEDED(CALL4(atlas2Tex, 19, lv, &ml, 0, 0x10))) { int dim = 256 >> lv; for (int y = 0; y < dim; ++y) h = fnv((BYTE*)ml.pBits + y * ml.Pitch, dim * 2, h); CALL1(atlas2Tex, 20, lv); } }
        fprintf(out, "%d %016llx\n", fr, h); fflush(out);
        ((HRESULT(WINAPI*)(void*, void*, void*, HWND, void*))vt(dev)[17])(dev, NULL, NULL, NULL, NULL);
    }
    QueryPerformanceCounter(&t1);
    fclose(out);
    double ms = (double)(t1.QuadPart - t0.QuadPart) * 1000.0 / qf.QuadPart;
    printf("%s: %d frames in %.1f ms\n", rt ? "RT on" : "RT off", frames, ms);
    printf("cached query mismatches: %d\n", queryMismatch);
    printf("sysmem lock mismatches: %d, render-target mirror mismatches: %d, lock-only call mismatches: %d\n", sysMismatch, mirrorMismatch, lockedMismatch);
    if (rt) { char st[512]; rtStats(st, sizeof(st)); printf("rt stats: %s\n", st);
        typedef void (__cdecl* Stats4F)(char*, int); Stats4F s4 = (Stats4F)GetProcAddress(GetModuleHandleA("pysage_accel.dll"), "AotrRtTestStatsV4");
        if (s4) { s4(st, sizeof(st)); printf("rt v4 stats: %s\n", st); } }
    return 0;
}
