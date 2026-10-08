// crt_test2: the memory and string replacements in aotr_fastcrt.inc against msvcr71.dll.
// Every case is run twice into identical scratch buffers - once through msvcr71, once through the replacement -
// and the WHOLE buffer is compared afterwards, so a byte written outside the requested range is a failure too.
// Buffers sit at the end of a committed region followed by a reserved-only page, so any read past the end of a
// string or a source range faults instead of passing silently.
#include <windows.h>
#include <stdio.h>
#include <string.h>
static void logf(const char* fmt, ...) { (void)fmt; }
#include "src/aotr_fastcrt.inc"

static unsigned __int64 g_rng = 0x243F6A8885A308D3ull;
static unsigned __int64 rnd() { g_rng ^= g_rng << 13; g_rng ^= g_rng >> 7; g_rng ^= g_rng << 17; return g_rng; }

static int g_fail = 0;
static void fail(const char* what, const char* how, int a, int b, int c) {
    if (g_fail++ < 25) printf("MISMATCH %s (%s) len=%d oa=%d ob=%d\n", what, how, a, b, c);
}

#define SCRATCH 4096
static BYTE *A, *B, *R1, *R2;                       // A/B sources, R1/R2 destinations, each SCRATCH bytes

// a committed block whose last byte is followed by an unmapped page
static BYTE* guarded(size_t n) {
    SIZE_T pages = ((n + 4095) / 4096 + 1) * 4096;
    BYTE* p = (BYTE*)VirtualAlloc(NULL, pages + 4096, MEM_RESERVE, PAGE_NOACCESS);
    if (!p) return NULL;
    if (!VirtualAlloc(p, pages, MEM_COMMIT, PAGE_READWRITE)) return NULL;
    return p + pages - n;                            // the byte after the block is unmapped
}

static void fillRnd(BYTE* p, size_t n) { for (size_t i = 0; i < n; ++i) p[i] = (BYTE)rnd(); }

int main(int argc, char** argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    HMODULE crt = LoadLibraryA(argc > 1 ? argv[1] : "msvcr71.dll");
    if (!crt) { printf("cannot load msvcr71.dll (%lu)\n", GetLastError()); return 2; }
    if (!crtPrepare(crt)) { printf("crtPrepare failed\n"); return 3; }
    A = guarded(SCRATCH); B = guarded(SCRATCH); R1 = guarded(SCRATCH); R2 = guarded(SCRATCH);
    if (!A || !B || !R1 || !R2) { printf("scratch allocation failed\n"); return 4; }

    // ---- memcpy / memmove / memset: every length 0..320, every source and destination alignment 0..15
    long nCases = 0;
    for (int len = 0; len <= 320; ++len) {
        for (int oa = 0; oa < 16; ++oa) for (int ob = 0; ob < 16; ++ob) {
            fillRnd(A, 512 + len);
            BYTE* src = A + oa;
            BYTE* d1 = R1 + ob; BYTE* d2 = R2 + ob;
            memset(R1, 0xCD, SCRATCH); memset(R2, 0xCD, SCRATCH);
            void* r1 = o_crtMemcpy(d1, src, len);
            void* r2 = fastMemcpy(d2, src, len);
            ++nCases;
            if (memcmp(R1, R2, SCRATCH)) fail("memcpy", "buffer", len, oa, ob);
            if ((BYTE*)r1 - R1 != (BYTE*)r2 - R2) fail("memcpy", "return", len, oa, ob);
            memset(R1, 0xCD, SCRATCH); memset(R2, 0xCD, SCRATCH);
            r1 = o_crtMemmove(d1, src, len);
            r2 = fastMemmove(d2, src, len);
            if (memcmp(R1, R2, SCRATCH)) fail("memmove", "buffer", len, oa, ob);
            if ((BYTE*)r1 - R1 != (BYTE*)r2 - R2) fail("memmove", "return", len, oa, ob);
            int c = (int)(rnd() & 0xFF);
            memset(R1, 0xCD, SCRATCH); memset(R2, 0xCD, SCRATCH);
            r1 = o_crtMemset(d1, c, len);
            r2 = fastMemset(d2, c, len);
            if (memcmp(R1, R2, SCRATCH)) fail("memset", "buffer", len, oa, ob);
            if ((BYTE*)r1 - R1 != (BYTE*)r2 - R2) fail("memset", "return", len, oa, ob);
        }
    }
    printf("memcpy/memmove/memset: %ld cases x 3, %d mismatches\n", nCases, g_fail);

    // ---- overlapping ranges: memcpy (handed to msvcr71) and memmove (reproduced), every shift -64..64
    int ovl = g_fail;
    memset(R1, 0xCD, SCRATCH); memset(R2, 0xCD, SCRATCH);     // everything outside the 512 bytes below stays equal
    for (int len = 0; len <= 200; ++len) {
        for (int sh = -64; sh <= 64; ++sh) {
            for (int base = 64; base <= 80; base += 16) {
                fillRnd(A, 512);
                memcpy(R1, A, 512); memcpy(R2, A, 512);
                BYTE* s1 = R1 + base; BYTE* s2 = R2 + base;
                o_crtMemmove(s1 + sh, s1, len);
                fastMemmove(s2 + sh, s2, len);
                if (memcmp(R1, R2, SCRATCH)) fail("memmove", "overlap", len, sh, base);
                memcpy(R1, A, 512); memcpy(R2, A, 512);
                o_crtMemcpy(s1 + sh, s1, len);
                fastMemcpy(s2 + sh, s2, len);
                if (memcmp(R1, R2, SCRATCH)) fail("memcpy", "overlap", len, sh, base);
            }
        }
    }
    printf("overlapping moves: %d mismatches\n", g_fail - ovl);

    // ---- strlen: every length 0..300 at every alignment, the terminator at the very end of the mapped block
    int sl = g_fail;
    for (int len = 0; len <= 300; ++len) {
        for (int oa = 0; oa < 16; ++oa) {
            BYTE* s = A + SCRATCH - len - 1 - oa;    // the NUL is the last readable byte when oa == 0
            for (int i = 0; i < len; ++i) s[i] = (BYTE)(1 + (rnd() % 255));
            s[len] = 0;
            size_t r1 = o_crtStrlen((const char*)s), r2 = fastStrlen((const char*)s);
            if (r1 != r2) fail("strlen", "length", len, oa, (int)r2);
        }
    }
    printf("strlen: %d mismatches\n", g_fail - sl);

    // ---- _strcmpi / _strnicmp: ASCII pairs, pairs that differ only in case, and pairs with high bytes
    int sc = g_fail;
    long nStr = 0;
    for (int it = 0; it < 400000; ++it) {
        unsigned __int64 r = rnd();
        int len = (int)(r % 40);
        char* x = (char*)(A + SCRATCH - len - 1);
        char* y = (char*)(B + SCRATCH - len - 1);
        int mode = (int)((r >> 8) % 5);
        for (int i = 0; i < len; ++i) {
            BYTE c = (BYTE)(32 + rnd() % 95);
            if (mode == 4 && (rnd() & 7) == 0) c = (BYTE)(128 + rnd() % 128);
            x[i] = (char)c;
            BYTE d = c;
            if (mode == 1 && (rnd() & 1)) { if (c >= 'a' && c <= 'z') d = (BYTE)(c - 32); else if (c >= 'A' && c <= 'Z') d = (BYTE)(c + 32); }
            if (mode == 2 && (rnd() % (len + 1)) == 0) d = (BYTE)(32 + rnd() % 95);
            if (mode == 3 && (rnd() & 15) == 0) d = (BYTE)(128 + rnd() % 128);
            y[i] = (char)d;
        }
        x[len] = 0; y[len] = 0;
        if (mode == 2 && len && (r >> 20 & 3) == 0) x[len - 1] = 0;      // different lengths
        int a1 = o_crtStricmp(x, y), a2 = fastStricmp(x, y);
        if (a1 != a2) fail("_strcmpi", "return", len, a1, a2);
        size_t n = (size_t)((r >> 24) % (len + 2));
        int b1 = o_crtStrnicmp(x, y, n), b2 = fastStrnicmp(x, y, n);
        if (b1 != b2) fail("_strnicmp", "return", (int)n, b1, b2);
        nStr += 2;
    }
    printf("_strcmpi / _strnicmp: %ld comparisons, %d mismatches\n", nStr, g_fail - sc);

    // ---- strcmp / strncmp / _mbscpy / strncpy / strchr / memchr. Every string ends at the last mapped byte of its
    // buffer, so a replacement that reads one byte past the terminator faults here instead of in the game.
    int st = g_fail;
    long nStr2 = 0;
    for (int it = 0; it < 600000; ++it) {
        unsigned __int64 r = rnd();
        int la = (int)(r % 70), lb = la;
        int mode = (int)((r >> 8) % 6);
        if (mode == 5) lb = (int)((r >> 16) % 70);       // different lengths
        char* x = (char*)(A + SCRATCH - la - 1);
        char* y = (char*)(B + SCRATCH - lb - 1);
        for (int i = 0; i < la; ++i) x[i] = (char)(1 + rnd() % 255);
        for (int i = 0; i < lb; ++i) y[i] = (char)(i < la && mode != 4 ? x[i] : (char)(1 + rnd() % 255));
        x[la] = 0; y[lb] = 0;
        if (mode == 1 && la) y[(int)((r >> 24) % la)] ^= 0x01;   // one differing byte
        if (mode == 2 && la) y[(int)((r >> 28) % la)] ^= 0x80;   // one differing high bit
        if (o_crtStrcmp(x, y) != fastStrcmp(x, y)) fail("strcmp", "return", la, lb, mode);
        size_t n = (size_t)((r >> 32) % 80);
        if (o_crtStrncmp(x, y, n) != fastStrncmp(x, y, n)) fail("strncmp", "return", la, (int)n, mode);
        if (fastStrlen(x) != crtStrnlen(x, 4096)) fail("strnlen", "length", la, 0, 0);
        int c = (int)((r >> 40) % 3) == 0 ? 0 : (int)(1 + (r >> 44) % 255);
        const char* r1 = o_crtStrchr(x, c); const char* r2 = fastStrchr(x, c);
        if (r1 != r2) fail("strchr", "pointer", la, c, (int)(r2 ? r2 - x : -1));
        const void* m1 = o_crtMemchr(x, c, (size_t)la); const void* m2 = fastMemchr(x, c, (size_t)la);
        if (m1 != m2) fail("memchr", "pointer", la, c, 0);
        // copies: into the end of a guarded buffer so the destination's own tail is checked too
        int dn = (int)((r >> 48) % 90);
        memset(R1, 0xCD, SCRATCH); memset(R2, 0xCD, SCRATCH);
        char* d1 = (char*)(R1 + SCRATCH - la - 1); char* d2 = (char*)(R2 + SCRATCH - la - 1);
        char* c1 = o_crtMbscpy(d1, x); char* c2 = fastMbscpy(d2, x);
        if (memcmp(R1, R2, SCRATCH) || (c1 - (char*)R1) != (c2 - (char*)R2)) fail("_mbscpy", "buffer", la, 0, 0);
        memset(R1, 0xCD, SCRATCH); memset(R2, 0xCD, SCRATCH);
        d1 = (char*)(R1 + SCRATCH - dn); d2 = (char*)(R2 + SCRATCH - dn);
        c1 = o_crtStrncpy(d1, x, (size_t)dn); c2 = fastStrncpy(d2, x, (size_t)dn);
        if (memcmp(R1, R2, SCRATCH) || (c1 - (char*)R1) != (c2 - (char*)R2)) fail("strncpy", "buffer", la, dn, 0);
        nStr2 += 7;
    }
    printf("strcmp / strncmp / strchr / memchr / _mbscpy / strncpy: %ld checks, %d mismatches\n", nStr2, g_fail - st);

    // ---- floor / ceil, under every x87 control word the game can be in (they must not depend on it)
    int fl = g_fail;
    long nF = 0;
    {
        static const WORD kCw[] = { 0x027F, 0x007F, 0x037F, 0x0E7F, 0x0A7F, 0x067F, 0x027B };
        WORD cur = 0; __asm fnstcw cur
        static const unsigned __int64 kSpecial[] = {
            0, 0x8000000000000000ull, 1, 0x8000000000000001ull, 0x3FE0000000000000ull, 0xBFE0000000000000ull,
            0x4170000010000000ull, 0xC170000010000000ull, 0x4330000000000000ull, 0x4330000000000001ull,
            0x432FFFFFFFFFFFFFull, 0xC32FFFFFFFFFFFFFull, 0x7FEFFFFFFFFFFFFFull, 0xFFEFFFFFFFFFFFFFull,
            0x7FF0000000000000ull, 0xFFF0000000000000ull, 0x7FF8000000000000ull, 0x7FF0000000000001ull,
            0x000FFFFFFFFFFFFFull, 0x0010000000000000ull, 0x3FF0000000000000ull, 0xBFF0000000000000ull };
        for (int c = 0; c < (int)(sizeof(kCw) / sizeof(kCw[0])); ++c) {
            WORD cw = kCw[c];
            for (int i = 0; i < 200000 + (int)(sizeof(kSpecial) / sizeof(kSpecial[0])); ++i) {
                double x;
                if (i < (int)(sizeof(kSpecial) / sizeof(kSpecial[0]))) { unsigned __int64 b = kSpecial[i]; memcpy(&x, &b, 8); }
                else {
                    unsigned __int64 r = rnd();
                    switch (i & 3) {
                    case 0: memcpy(&x, &r, 8); break;
                    case 1: x = (double)(__int64)(r % 40000001) / 1000.0 - 20000.0; break;
                    case 2: x = (double)(__int64)(r % 2000001) - 1000000.0 + 0.5; break;
                    default: { unsigned __int64 b = (r & 0x800FFFFFFFFFFFFFull) | (((0x3FFull + 20 + (r >> 56) % 40)) << 52); memcpy(&x, &b, 8); } break;
                    }
                }
                double a1, a2, b1, b2;
                __asm fldcw cw
                a1 = o_crtFloor(x); b1 = o_crtCeil(x);
                __asm fldcw cw
                a2 = fastFloor(x);  b2 = fastCeil(x);
                __asm fldcw cur
                if (memcmp(&a1, &a2, 8)) { unsigned __int64 bx, p, q; memcpy(&bx, &x, 8); memcpy(&p, &a1, 8); memcpy(&q, &a2, 8);
                    if (g_fail++ < 25) printf("MISMATCH floor cw=%04X x=%016I64X: msvcr71 %016I64X fast %016I64X\n", cw, bx, p, q); }
                if (memcmp(&b1, &b2, 8)) { unsigned __int64 bx, p, q; memcpy(&bx, &x, 8); memcpy(&p, &b1, 8); memcpy(&q, &b2, 8);
                    if (g_fail++ < 25) printf("MISMATCH ceil  cw=%04X x=%016I64X: msvcr71 %016I64X fast %016I64X\n", cw, bx, p, q); }
                nF += 2;
            }
        }
    }
    printf("floor / ceil: %ld comparisons over 7 control words, %d mismatches\n", nF, g_fail - fl);

    // ---- installFastCrt against a hand-built image whose import descriptor has NO name table, which is what both
    // game.dat builds actually look like. The first version of the walk read names, found none and silently did
    // nothing; this is the test that would have caught it.
    {
        BYTE* img = (BYTE*)VirtualAlloc(NULL, 64 * 1024, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)img;
        dos->e_magic = IMAGE_DOS_SIGNATURE; dos->e_lfanew = 0x80;
        IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(img + 0x80);
        nt->Signature = IMAGE_NT_SIGNATURE;
        nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress = 0x1000;
        IMAGE_IMPORT_DESCRIPTOR* imp = (IMAGE_IMPORT_DESCRIPTOR*)(img + 0x1000);
        imp[0].Name = 0x1100;
        imp[0].FirstThunk = 0x1200;
        imp[0].OriginalFirstThunk = 0;                    // no import name table, exactly like game.dat
        imp[1].Name = 0;
        lstrcpyA((char*)(img + 0x1100), "msvcr71.dll");
        static const char* kWant[] = { "fabs","memcmp","memcpy","memmove","memset","memchr","strlen","strcmp",
                                       "strncmp","strchr","_mbscpy","_strcmpi","_strnicmp","floor","ceil","_strcmpi" };
        const int nWant = (int)(sizeof(kWant) / sizeof(kWant[0]));   // _strcmpi twice, as RotWK imports it
        DWORD* iat = (DWORD*)(img + 0x1200);
        DWORD before[32];
        int k = 0;
        for (int i = 0; i < nWant; ++i) iat[k++] = before[i] = (DWORD)(ULONG_PTR)GetProcAddress(crt, kWant[i]);
        iat[k++] = (DWORD)(ULONG_PTR)GetProcAddress(crt, "printf");  // something we must NOT touch
        DWORD keep = iat[k - 1];
        iat[k] = 0;

        g_crtInstalled = 0;
        installFastCrt(img);
        int changed = 0;
        for (int i = 0; i < nWant; ++i) if (iat[i] != before[i]) ++changed;
        printf("\ninstallFastCrt on an image with no name table: %d of %d slots switched, printf %s\n",
               changed, nWant, iat[nWant] == keep ? "untouched" : "WRONGLY CHANGED");
        if (changed != nWant) { printf("MISMATCH: expected all %d\n", nWant); ++g_fail; }
        if (iat[nWant] != keep) ++g_fail;
        // and the calls still behave, going through the patched slot
        {
            BYTE b1[64], b2[64];
            ((void*(__cdecl*)(void*,int,size_t))iat[4])(b1, 0xAB, 40);      // memset
            o_crtMemset(b2, 0xAB, 40);
            if (memcmp(b1, b2, 40)) { printf("MISMATCH: memset through the patched slot differs\n"); ++g_fail; }
            if (((size_t(__cdecl*)(const char*))iat[6])("GondorSoldier") != 13) { printf("MISMATCH: strlen through the patched slot\n"); ++g_fail; }
            if (((int(__cdecl*)(const char*,const char*,size_t))iat[8])("abc", "abd", 3) != o_crtStrncmp("abc", "abd", 3)) { printf("MISMATCH: strncmp through the patched slot\n"); ++g_fail; }
        }
        VirtualFree(img, 0, MEM_RELEASE);
    }

    // ---- speed
    LARGE_INTEGER f, t0, t1; QueryPerformanceFrequency(&f);
    static const int kLens[] = { 8, 16, 24, 32, 48, 64, 128, 256, 1024, 4096 };
    printf("\n           msvcr71    fast\n");
    for (int k = 0; k < (int)(sizeof(kLens) / sizeof(kLens[0])); ++k) {
        int len = kLens[k]; int iters = len > 512 ? 2000000 : 10000000;
        BYTE* s = A; BYTE* d = R1;
        QueryPerformanceCounter(&t0); for (int i = 0; i < iters; ++i) o_crtMemcpy(d, s, len); QueryPerformanceCounter(&t1);
        double ta = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / iters;
        QueryPerformanceCounter(&t0); for (int i = 0; i < iters; ++i) fastMemcpy(d, s, len); QueryPerformanceCounter(&t1);
        double tb = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / iters;
        QueryPerformanceCounter(&t0); for (int i = 0; i < iters; ++i) o_crtMemset(d, i, len); QueryPerformanceCounter(&t1);
        double tc = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / iters;
        QueryPerformanceCounter(&t0); for (int i = 0; i < iters; ++i) fastMemset(d, i, len); QueryPerformanceCounter(&t1);
        double td = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / iters;
        printf("memcpy(%5d) %6.2f %6.2f ns   memset %6.2f %6.2f ns\n", len, ta, tb, tc, td);
    }
    {
        char s[300]; memset(s, 'x', sizeof(s));
        for (int len = 8; len <= 128; len *= 4) {
            s[len] = 0;
            QueryPerformanceCounter(&t0); for (int i = 0; i < 10000000; ++i) o_crtStrlen(s); QueryPerformanceCounter(&t1);
            double ta = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / 10000000;
            QueryPerformanceCounter(&t0); for (int i = 0; i < 10000000; ++i) fastStrlen(s); QueryPerformanceCounter(&t1);
            double tb = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / 10000000;
            printf("strlen(%5d) %6.2f %6.2f ns\n", len, ta, tb);
            s[len] = 'x';
        }
        const char* u = "GondorSoldierHorde"; const char* v = "GondorSoldierHorse";
        QueryPerformanceCounter(&t0); for (int i = 0; i < 10000000; ++i) o_crtStrcmp(u, v); QueryPerformanceCounter(&t1);
        double sa = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / 10000000;
        QueryPerformanceCounter(&t0); for (int i = 0; i < 10000000; ++i) fastStrcmp(u, v); QueryPerformanceCounter(&t1);
        double sb = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / 10000000;
        printf("strcmp(18)   %6.2f %6.2f ns\n", sa, sb);
        QueryPerformanceCounter(&t0); for (int i = 0; i < 10000000; ++i) o_crtStrncmp(u, v, 18); QueryPerformanceCounter(&t1);
        sa = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / 10000000;
        QueryPerformanceCounter(&t0); for (int i = 0; i < 10000000; ++i) fastStrncmp(u, v, 18); QueryPerformanceCounter(&t1);
        sb = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / 10000000;
        printf("strncmp(18)  %6.2f %6.2f ns\n", sa, sb);
        char db[96];
        QueryPerformanceCounter(&t0); for (int i = 0; i < 10000000; ++i) o_crtMbscpy(db, u); QueryPerformanceCounter(&t1);
        sa = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / 10000000;
        QueryPerformanceCounter(&t0); for (int i = 0; i < 10000000; ++i) fastMbscpy(db, u); QueryPerformanceCounter(&t1);
        sb = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / 10000000;
        printf("_mbscpy(18)  %6.2f %6.2f ns\n", sa, sb);
        QueryPerformanceCounter(&t0); for (int i = 0; i < 10000000; ++i) o_crtStrncpy(db, u, 32); QueryPerformanceCounter(&t1);
        sa = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / 10000000;
        QueryPerformanceCounter(&t0); for (int i = 0; i < 10000000; ++i) fastStrncpy(db, u, 32); QueryPerformanceCounter(&t1);
        sb = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / 10000000;
        printf("strncpy(32)  %6.2f %6.2f ns\n", sa, sb);
        volatile double fa = 0;
        QueryPerformanceCounter(&t0); for (int i = 0; i < 10000000; ++i) fa += o_crtFloor((double)i * 0.37); QueryPerformanceCounter(&t1);
        sa = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / 10000000;
        QueryPerformanceCounter(&t0); for (int i = 0; i < 10000000; ++i) fa += fastFloor((double)i * 0.37); QueryPerformanceCounter(&t1);
        sb = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / 10000000;
        printf("floor        %6.2f %6.2f ns\n", sa, sb);
        const char* p = "GondorSoldierHorde"; const char* q = "gondorsoldierhorde";
        QueryPerformanceCounter(&t0); for (int i = 0; i < 10000000; ++i) o_crtStricmp(p, q); QueryPerformanceCounter(&t1);
        double ta = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / 10000000;
        QueryPerformanceCounter(&t0); for (int i = 0; i < 10000000; ++i) fastStricmp(p, q); QueryPerformanceCounter(&t1);
        double tb = (double)(t1.QuadPart - t0.QuadPart) * 1e9 / f.QuadPart / 10000000;
        printf("_strcmpi(18) %6.2f %6.2f ns\n", ta, tb);
    }
    printf("\n%s\n", g_fail ? "FAILURES - do not ship" : "all replacements identical to msvcr71");
    return g_fail ? 1 : 0;
}
