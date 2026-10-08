// ---------------------------------------------------------------- fast CRT for game.dat (bit-identical results)
// game.dat reaches msvcr71.dll through its import table millions of times per logic step. msvcr71 is the 2003 CRT:
// its string and memory routines are 386-era dword loops, and its float helpers save, set and restore the x87
// control word on every call. The replacements below return results that are identical in every bit and write
// identical bytes (crt_test.exe compares each one with msvcr71 over tens of millions of random inputs, including
// every alignment, every length up to 260 and the x87 control words the game runs with):
//   fabs       finite argument: clear the sign bit (8 ns vs 25 ns). Inf / NaN go to msvcr71.
//   memcmp     SSE2 compare, first differing byte as unsigned, -1/0/1 exactly like msvcr71 (5-6 ns vs 23-27 ns).
//   memcpy     SSE2 / rep movsb. Overlapping ranges are handed to msvcr71 so even that case stays identical.
//   memmove    SSE2 forward or backward; a true memmove, so the result is defined and matches.
//   memset     SSE2 / rep stosb.
//   strlen     SSE2, reading only inside the 16-byte blocks the string itself occupies (never past a page).
//   _strcmpi   ASCII case fold; a byte >= 0x80 on either side hands the whole call to msvcr71 (locale).
//   _strnicmp  the same.
//   strcmp     SSE2 16 bytes at a time, byte-wise next to a page boundary (11 ns -> 4 ns).
//   strncmp    the same. msvcr71's begins with repne scasb - it measures a string before comparing: 65 ns -> 4 ns.
//   _mbscpy    strlen + block copy (7 ns -> 3 ns); overlapping ranges go to msvcr71.
//   strncpy    NOT replaced: three passes (measure, copy, pad) came out slower than msvcr71's single dword loop.
//   strchr     SSE2, stopping at the terminator (the terminator is a hit when c is 0, as in msvcr71).
//   memchr     SSE2.
//   floor/ceil roundsd instead of msvcr71's SSE2 dispatch and mxcsr juggling (5.5 ns -> 2 ns). Needs SSE4.1.
// An import slot is switched only while it still points at msvcr71's own export.
#include <emmintrin.h>
#include <smmintrin.h>
#include <intrin.h>

typedef double (__cdecl* tCrtD1)(double);
typedef int    (__cdecl* tCrtCmp)(const void*, const void*, size_t);
typedef void*  (__cdecl* tCrtCpy)(void*, const void*, size_t);
typedef void*  (__cdecl* tCrtSet)(void*, int, size_t);
typedef size_t (__cdecl* tCrtLen)(const char*);
typedef int    (__cdecl* tCrtSCmp)(const char*, const char*);
typedef int    (__cdecl* tCrtSNCmp)(const char*, const char*, size_t);
typedef char*  (__cdecl* tCrtSCpy)(char*, const char*);
typedef char*  (__cdecl* tCrtSNCpy)(char*, const char*, size_t);
typedef char*  (__cdecl* tCrtSChr)(const char*, int);
typedef void*  (__cdecl* tCrtMChr)(const void*, int, size_t);
static tCrtD1    o_crtFloor = NULL, o_crtCeil = NULL;
static tCrtSCmp  o_crtStrcmp = NULL;
static tCrtSNCmp o_crtStrncmp = NULL;
static tCrtSChr  o_crtStrchr = NULL;
static tCrtMChr  o_crtMemchr = NULL;
static tCrtSCpy  o_crtMbscpy = NULL;
static tCrtSNCpy o_crtStrncpy = NULL;
static tCrtD1    o_crtFabs = NULL;
static tCrtCmp   o_crtMemcmp = NULL;
static tCrtCpy   o_crtMemcpy = NULL, o_crtMemmove = NULL;
static tCrtSet   o_crtMemset = NULL;
static tCrtLen   o_crtStrlen = NULL;
static tCrtSCmp  o_crtStricmp = NULL;
static tCrtSNCmp o_crtStrnicmp = NULL;

static __forceinline bool crtFinite(const double* x) {
    return (((const DWORD*)x)[1] & 0x7FF00000u) != 0x7FF00000u;
}
static double __cdecl fastFabs(double x) {
    if (!crtFinite(&x)) return o_crtFabs(x);
    double r = x; ((DWORD*)&r)[1] &= 0x7FFFFFFFu;
    return r;
}
static int __cdecl fastMemcmp(const void* pa, const void* pb, size_t n) {
    const BYTE* a = (const BYTE*)pa, *b = (const BYTE*)pb;
    size_t i = 0;
    for (; i + 16 <= n; i += 16) {
        int m = _mm_movemask_epi8(_mm_cmpeq_epi8(_mm_loadu_si128((const __m128i*)(a + i)), _mm_loadu_si128((const __m128i*)(b + i))));
        if (m != 0xFFFF) { unsigned long k; _BitScanForward(&k, (unsigned long)(~m & 0xFFFF)); return a[i + k] < b[i + k] ? -1 : 1; }
    }
    for (; i + 4 <= n; i += 4) {
        DWORD x = *(const DWORD*)(a + i), y = *(const DWORD*)(b + i);
        if (x != y) { unsigned long k; _BitScanForward(&k, x ^ y); k >>= 3; return a[i + k] < b[i + k] ? -1 : 1; }
    }
    for (; i < n; ++i) if (a[i] != b[i]) return a[i] < b[i] ? -1 : 1;
    return 0;
}

// --- memory moves. The 0..15 and 16..32 cases are two overlapping loads and stores with no per-byte branch, which
// is where the engine spends its copies (matrices, vertices, AsciiString bodies). From 512 bytes up it is rep movsb,
// the fastest large copy on this CPU. An overlapping memcpy is undefined in C but not in practice, so that one case
// is handed to msvcr71 instead of reproduced.
static __forceinline void crtCopyFwd(BYTE* d, const BYTE* s, size_t n) {
    if (n < 16) {
        if (n & 8) { *(unsigned __int64*)d = *(const unsigned __int64*)s; d += 8; s += 8; }
        if (n & 4) { *(DWORD*)d = *(const DWORD*)s; d += 4; s += 4; }
        if (n & 2) { *(WORD*)d = *(const WORD*)s; d += 2; s += 2; }
        if (n & 1) { *d = *s; }
        return;
    }
    if (n <= 32) {
        __m128i a = _mm_loadu_si128((const __m128i*)s), b = _mm_loadu_si128((const __m128i*)(s + n - 16));
        _mm_storeu_si128((__m128i*)d, a); _mm_storeu_si128((__m128i*)(d + n - 16), b);
        return;
    }
    if (n >= 512) { __movsb(d, s, n); return; }
    size_t i = 0;
    for (; i + 32 <= n; i += 32) {
        __m128i a = _mm_loadu_si128((const __m128i*)(s + i)), b = _mm_loadu_si128((const __m128i*)(s + i + 16));
        _mm_storeu_si128((__m128i*)(d + i), a); _mm_storeu_si128((__m128i*)(d + i + 16), b);
    }
    __m128i a = _mm_loadu_si128((const __m128i*)(s + n - 32)), b = _mm_loadu_si128((const __m128i*)(s + n - 16));
    _mm_storeu_si128((__m128i*)(d + n - 32), a); _mm_storeu_si128((__m128i*)(d + n - 16), b);
}
static __forceinline bool crtOverlap(const BYTE* d, const BYTE* s, size_t n) {
    return (size_t)(d - s) < n || (size_t)(s - d) < n;
}
static void* __cdecl fastMemcpy(void* dst, const void* src, size_t n) {
    BYTE* d = (BYTE*)dst; const BYTE* s = (const BYTE*)src;
    if (crtOverlap(d, s, n)) return o_crtMemcpy(dst, src, n);
    crtCopyFwd(d, s, n);
    return dst;
}
// Overlapping ranges cannot use the two-overlapping-stores trick of crtCopyFwd: its last block re-reads source bytes
// the earlier stores have already overwritten. Ranges that overlap take a strictly ordered path instead - rep movsb
// upwards, or 32-byte blocks downwards with the leftover head copied backwards one byte at a time.
static void* __cdecl fastMemmove(void* dst, const void* src, size_t n) {
    BYTE* d = (BYTE*)dst; const BYTE* s = (const BYTE*)src;
    if (!crtOverlap(d, s, n)) { crtCopyFwd(d, s, n); return dst; }
    if (d == s) return dst;
    if (d < s) { __movsb(d, s, n); return dst; }
    size_t i = n;
    while (i >= 32) {
        i -= 32;
        __m128i a = _mm_loadu_si128((const __m128i*)(s + i)), b = _mm_loadu_si128((const __m128i*)(s + i + 16));
        _mm_storeu_si128((__m128i*)(d + i + 16), b); _mm_storeu_si128((__m128i*)(d + i), a);
    }
    while (i--) d[i] = s[i];
    return dst;
}
static void* __cdecl fastMemset(void* dst, int c, size_t n) {
    BYTE* d = (BYTE*)dst; BYTE v = (BYTE)c;
    if (n < 16) {
        unsigned __int64 q = 0x0101010101010101ull * v;
        if (n & 8) { *(unsigned __int64*)d = q; d += 8; }
        if (n & 4) { *(DWORD*)d = (DWORD)q; d += 4; }
        if (n & 2) { *(WORD*)d = (WORD)q; d += 2; }
        if (n & 1) { *d = v; }
        return dst;
    }
    __m128i x = _mm_set1_epi8((char)v);
    if (n <= 32) { _mm_storeu_si128((__m128i*)d, x); _mm_storeu_si128((__m128i*)(d + n - 16), x); return dst; }
    if (n >= 512) { __stosb(d, v, n); return dst; }
    size_t i = 0;
    for (; i + 32 <= n; i += 32) { _mm_storeu_si128((__m128i*)(d + i), x); _mm_storeu_si128((__m128i*)(d + i + 16), x); }
    _mm_storeu_si128((__m128i*)(d + n - 32), x); _mm_storeu_si128((__m128i*)(d + n - 16), x);
    return dst;
}
// reads only inside the 16-byte blocks the string itself occupies, so it can never touch an unmapped page
static size_t __cdecl fastStrlen(const char* s) {
    const __m128i z = _mm_setzero_si128();
    const char* p = (const char*)((size_t)s & ~(size_t)15);
    unsigned off = (unsigned)((size_t)s & 15);
    unsigned m = (unsigned)_mm_movemask_epi8(_mm_cmpeq_epi8(_mm_load_si128((const __m128i*)p), z)) >> off;
    if (m) { unsigned long k; _BitScanForward(&k, m); return k; }
    for (p += 16; ; p += 16) {
        m = (unsigned)_mm_movemask_epi8(_mm_cmpeq_epi8(_mm_load_si128((const __m128i*)p), z));
        if (m) { unsigned long k; _BitScanForward(&k, m); return (size_t)(p - s) + k; }
    }
}
// case-insensitive compares: ASCII only. A byte with the high bit set on either side means the answer depends on the
// locale's table, so that call goes to msvcr71 from the beginning.
static __forceinline int crtLowerAscii(BYTE c) { return (c >= 'A' && c <= 'Z') ? c + 32 : c; }
static int __cdecl fastStricmp(const char* a, const char* b) {
    const BYTE* x = (const BYTE*)a; const BYTE* y = (const BYTE*)b;
    for (;;) {
        BYTE ca = *x++, cb = *y++;
        if ((ca | cb) & 0x80) return o_crtStricmp(a, b);
        int la = crtLowerAscii(ca), lb = crtLowerAscii(cb);
        if (la != lb) return la < lb ? -1 : 1;
        if (!ca) return 0;
    }
}
static int __cdecl fastStrnicmp(const char* a, const char* b, size_t n) {
    for (size_t i = 0; i < n; ++i) {
        BYTE ca = (BYTE)a[i], cb = (BYTE)b[i];
        if ((ca | cb) & 0x80) return o_crtStrnicmp(a, b, n);
        int la = crtLowerAscii(ca), lb = crtLowerAscii(cb);
        if (la != lb) return la < lb ? -1 : 1;
        if (!ca) return 0;
    }
    return 0;
}

// --- floor and ceil. msvcr71 dispatches on an SSE2 flag and juggles mxcsr on every call (5.5 ns); roundsd does it
// in one instruction. Both results are exact integers, so unlike sqrt they do not depend on the x87 precision
// control - measured identical under 24-, 53- and 64-bit control words. Inf and NaN go to msvcr71 so the payload of
// a signalling NaN is whatever the game has always seen. Needs SSE4.1, which installFastCrt checks for.
static double __cdecl fastFloor(double x) {
    if (!crtFinite(&x)) return o_crtFloor(x);
    return _mm_cvtsd_f64(_mm_floor_sd(_mm_setzero_pd(), _mm_set_sd(x)));
}
static double __cdecl fastCeil(double x) {
    if (!crtFinite(&x)) return o_crtCeil(x);
    return _mm_cvtsd_f64(_mm_ceil_sd(_mm_setzero_pd(), _mm_set_sd(x)));
}

// --- string compares and copies, 16 bytes at a time. A 16-byte load is only taken while both pointers are at
// least 16 bytes from the end of their page (the bitwise OR of the two page offsets is >= either of them, so one
// test covers both); next to a page boundary it walks byte by byte, so nothing is ever read past a string's end.
#define CRT_PAGE_SAFE(a, b) (((((size_t)(a)) | ((size_t)(b))) & 4095) <= 4080)
static int __cdecl fastStrcmp(const char* a, const char* b) {
    for (;;) {
        if (CRT_PAGE_SAFE(a, b)) {
            __m128i va = _mm_loadu_si128((const __m128i*)a), vb = _mm_loadu_si128((const __m128i*)b);
            unsigned m = (unsigned)((~_mm_movemask_epi8(_mm_cmpeq_epi8(va, vb))
                                     | _mm_movemask_epi8(_mm_cmpeq_epi8(va, _mm_setzero_si128()))) & 0xFFFF);
            if (!m) { a += 16; b += 16; continue; }
            unsigned long k; _BitScanForward(&k, m);
            BYTE ca = (BYTE)a[k], cb = (BYTE)b[k];
            return ca == cb ? 0 : (ca < cb ? -1 : 1);
        }
        BYTE ca = (BYTE)*a, cb = (BYTE)*b;
        if (ca != cb) return ca < cb ? -1 : 1;
        if (!ca) return 0;
        ++a; ++b;
    }
}
static int __cdecl fastStrncmp(const char* a, const char* b, size_t n) {
    while (n) {
        if (n >= 16 && CRT_PAGE_SAFE(a, b)) {
            __m128i va = _mm_loadu_si128((const __m128i*)a), vb = _mm_loadu_si128((const __m128i*)b);
            unsigned m = (unsigned)((~_mm_movemask_epi8(_mm_cmpeq_epi8(va, vb))
                                     | _mm_movemask_epi8(_mm_cmpeq_epi8(va, _mm_setzero_si128()))) & 0xFFFF);
            if (!m) { a += 16; b += 16; n -= 16; continue; }
            unsigned long k; _BitScanForward(&k, m);
            BYTE ca = (BYTE)a[k], cb = (BYTE)b[k];
            return ca == cb ? 0 : (ca < cb ? -1 : 1);
        }
        BYTE ca = (BYTE)*a, cb = (BYTE)*b;
        if (ca != cb) return ca < cb ? -1 : 1;
        if (!ca) return 0;
        ++a; ++b; --n;
    }
    return 0;
}
static size_t crtStrnlen(const char* s, size_t n) {
    size_t i = 0;
    while (i < n) {
        if (n - i >= 16 && CRT_PAGE_SAFE(s + i, s + i)) {
            unsigned m = (unsigned)_mm_movemask_epi8(_mm_cmpeq_epi8(_mm_loadu_si128((const __m128i*)(s + i)), _mm_setzero_si128()));
            if (!m) { i += 16; continue; }
            unsigned long k; _BitScanForward(&k, m);
            return i + k;
        }
        if (!s[i]) return i;
        ++i;
    }
    return n;
}
// _mbscpy copies a byte string up to and including its terminator, exactly like strcpy. Overlapping ranges are
// handed to msvcr71, as in fastMemcpy.
static char* __cdecl fastMbscpy(char* dst, const char* src) {
    size_t n = fastStrlen(src) + 1;
    if (crtOverlap((const BYTE*)dst, (const BYTE*)src, n)) return o_crtMbscpy(dst, src);
    crtCopyFwd((BYTE*)dst, (const BYTE*)src, n);
    return dst;
}
static char* __cdecl fastStrncpy(char* dst, const char* src, size_t n) {
    size_t len = crtStrnlen(src, n);
    if (crtOverlap((const BYTE*)dst, (const BYTE*)src, len ? len : 1)) return o_crtStrncpy(dst, src, n);
    crtCopyFwd((BYTE*)dst, (const BYTE*)src, len);
    if (len < n) fastMemset(dst + len, 0, n - len);      // strncpy pads the whole of the rest with zeros
    return dst;
}
static char* __cdecl fastStrchr(const char* s, int c) {
    BYTE t = (BYTE)c;
    const __m128i z = _mm_setzero_si128(), v = _mm_set1_epi8((char)t);
    for (;;) {
        if (CRT_PAGE_SAFE(s, s)) {
            __m128i d = _mm_loadu_si128((const __m128i*)s);
            unsigned hit = (unsigned)_mm_movemask_epi8(_mm_cmpeq_epi8(d, v));
            unsigned end = (unsigned)_mm_movemask_epi8(_mm_cmpeq_epi8(d, z));
            if (hit | end) {
                unsigned long kh = 32, ke = 32;
                if (hit) _BitScanForward(&kh, hit);
                if (end) _BitScanForward(&ke, end);
                if (kh <= ke) return (char*)(s + kh);     // the terminator itself is a hit when c is 0
                return NULL;
            }
            s += 16; continue;
        }
        BYTE ch = (BYTE)*s;
        if (ch == t) return (char*)s;
        if (!ch) return NULL;
        ++s;
    }
}
static void* __cdecl fastMemchr(const void* p, int c, size_t n) {
    const BYTE* s = (const BYTE*)p; BYTE t = (BYTE)c;
    const __m128i v = _mm_set1_epi8((char)t);
    size_t i = 0;
    for (; i + 16 <= n; i += 16) {
        unsigned m = (unsigned)_mm_movemask_epi8(_mm_cmpeq_epi8(_mm_loadu_si128((const __m128i*)(s + i)), v));
        if (m) { unsigned long k; _BitScanForward(&k, m); return (void*)(s + i + k); }
    }
    for (; i < n; ++i) if (s[i] == t) return (void*)(s + i);
    return NULL;
}

static volatile LONG g_crtInstalled = 0;
static bool crtSse41() {
    int r[4] = { 0, 0, 0, 0 };
    __cpuid(r, 1);
    return (r[2] & (1 << 19)) != 0;
}
static bool crtPrepare(HMODULE crt) {               // resolve the originals (also used by the test program)
    if (!crt) return false;
    o_crtFloor    = (tCrtD1)GetProcAddress(crt, "floor");
    o_crtStrcmp   = (tCrtSCmp)GetProcAddress(crt, "strcmp");
    o_crtStrncmp  = (tCrtSNCmp)GetProcAddress(crt, "strncmp");
    o_crtStrchr   = (tCrtSChr)GetProcAddress(crt, "strchr");
    o_crtMemchr   = (tCrtMChr)GetProcAddress(crt, "memchr");
    o_crtCeil     = (tCrtD1)GetProcAddress(crt, "ceil");
    o_crtMbscpy   = (tCrtSCpy)GetProcAddress(crt, "_mbscpy");
    o_crtStrncpy  = (tCrtSNCpy)GetProcAddress(crt, "strncpy");
    o_crtFabs     = (tCrtD1)GetProcAddress(crt, "fabs");
    o_crtMemcmp   = (tCrtCmp)GetProcAddress(crt, "memcmp");
    o_crtMemcpy   = (tCrtCpy)GetProcAddress(crt, "memcpy");
    o_crtMemmove  = (tCrtCpy)GetProcAddress(crt, "memmove");
    o_crtMemset   = (tCrtSet)GetProcAddress(crt, "memset");
    o_crtStrlen   = (tCrtLen)GetProcAddress(crt, "strlen");
    o_crtStricmp  = (tCrtSCmp)GetProcAddress(crt, "_strcmpi");
    o_crtStrnicmp = (tCrtSNCmp)GetProcAddress(crt, "_strnicmp");
    return o_crtFabs && o_crtMemcmp && o_crtMemcpy && o_crtMemmove && o_crtMemset && o_crtStrlen && o_crtStricmp
        && o_crtStrnicmp && o_crtFloor && o_crtCeil && o_crtMbscpy && o_crtStrncpy
        && o_crtStrcmp && o_crtStrncmp && o_crtStrchr && o_crtMemchr;
}
// Which IAT slots to switch is decided by the function's RESOLVED ADDRESS, not by its name. game.dat has no
// import name table at all (OriginalFirstThunk is 0 for every descriptor, in both RotWK's and BFME2's build), so
// there are no name strings to match - the first version of this walked names, found nothing, and quietly did
// nothing on every build. At runtime the IAT already holds resolved addresses, so comparing them with
// GetProcAddress is both simpler and independent of the name table. A slot is only switched while it still holds
// msvcr71's own export, and every slot holding it is switched (RotWK imports _strcmpi twice).
static void installFastCrt(BYTE* gameBase) {
    __try {
        HMODULE crt = GetModuleHandleA("msvcr71.dll");
        if (!crtPrepare(crt)) { logf("fastcrt: msvcr71 not found - CRT math stays stock."); return; }
        static const struct { const char* name; void* fn; bool sse41; } kFast[] = {
            { "fabs",      (void*)&fastFabs,     false },
            { "memcmp",    (void*)&fastMemcmp,   false },
            { "memcpy",    (void*)&fastMemcpy,   false },
            { "memmove",   (void*)&fastMemmove,  false },
            { "memset",    (void*)&fastMemset,   false },
            { "memchr",    (void*)&fastMemchr,   false },
            { "strlen",    (void*)&fastStrlen,   false },
            { "strcmp",    (void*)&fastStrcmp,   false },
            { "strncmp",   (void*)&fastStrncmp,  false },   // msvcr71's opens with repne scasb: 65 ns
            { "strchr",    (void*)&fastStrchr,   false },
            { "_mbscpy",   (void*)&fastMbscpy,   false },
            { "_strcmpi",  (void*)&fastStricmp,  false },
            { "_strnicmp", (void*)&fastStrnicmp, false },
            { "floor",     (void*)&fastFloor,    true  },
            { "ceil",      (void*)&fastCeil,     true  },
        };
        const int kN = (int)(sizeof(kFast) / sizeof(kFast[0]));
        const bool sse41 = crtSse41();
        FARPROC want[kN];
        int resolved = 0;
        for (int j = 0; j < kN; ++j) { want[j] = GetProcAddress(crt, kFast[j].name); if (want[j]) ++resolved; }

        IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)gameBase;
        IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(gameBase + dos->e_lfanew);
        IMAGE_DATA_DIRECTORY dd = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
        if (!dd.VirtualAddress) { logf("fastcrt: no import directory - CRT stays stock."); return; }

        int patched = 0, seen = 0, skippedSse = 0;
        for (IMAGE_IMPORT_DESCRIPTOR* imp = (IMAGE_IMPORT_DESCRIPTOR*)(gameBase + dd.VirtualAddress); imp->Name; ++imp) {
            if (_stricmp((const char*)(gameBase + imp->Name), "msvcr71.dll")) continue;
            for (IMAGE_THUNK_DATA* ft = (IMAGE_THUNK_DATA*)(gameBase + imp->FirstThunk); ft->u1.Function; ++ft) {
                for (int j = 0; j < kN; ++j) {
                    if (!want[j] || (FARPROC)(ULONG_PTR)ft->u1.Function != want[j]) continue;
                    ++seen;
                    if (kFast[j].sse41 && !sse41) { ++skippedSse; break; }
                    DWORD op = 0;
                    if (!VirtualProtect(&ft->u1.Function, sizeof(void*), PAGE_READWRITE, &op)) break;
                    ft->u1.Function = (ULONG_PTR)(ULONG_PTR)kFast[j].fn;
                    VirtualProtect(&ft->u1.Function, sizeof(void*), op, &op);
                    ++patched;
                    break;
                }
            }
        }
        g_crtInstalled = patched;
        if (!patched)
            logf("fastcrt: NONE of the %d replacements matched an import slot - the CRT stays stock. (%d of them resolved in msvcr71.)", kN, resolved);
        else
            logf("fastcrt: %d import slots now use the exact fast versions, out of %d that matched (%d needed SSE4.1 and this CPU %s).",
                 patched, seen, skippedSse, sse41 ? "has it" : "does not");
    } __except (EXCEPTION_EXECUTE_HANDLER) { logf("fastcrt: install faulted - CRT math stays stock."); }
}
