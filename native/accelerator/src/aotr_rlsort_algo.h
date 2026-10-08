// Algorithm half of aotr_rlsort.inc, shared with rlsort_test.cpp (which runs it against the stock sort from game.dat).
struct RlEl { DWORD w[8]; };
typedef bool (__cdecl* tRlPred)(const RlEl*, const RlEl*);
typedef void (__cdecl* tRlHeap)(RlEl*, RlEl*, RlEl*, tRlPred);
static const DWORD kRlHeap = 0x00573B95, kRlLessModel = 0x00572EEA, kRlLessModelInst = 0x00572F07;
static volatile LONG g_rlHeapFalls = 0;
struct RlLessModel {
    bool operator()(const RlEl* a, const RlEl* b) const { return *(DWORD*)(ULONG_PTR)(a->w[0] + 0xC4) < *(DWORD*)(ULONG_PTR)(b->w[0] + 0xC4); }
};
struct RlLessModelInst {
    bool operator()(const RlEl* a, const RlEl* b) const {
        DWORD ma = *(DWORD*)(ULONG_PTR)(a->w[0] + 0xC4), mb = *(DWORD*)(ULONG_PTR)(b->w[0] + 0xC4);
        if (ma != mb) return ma < mb;
        return *(DWORD*)(ULONG_PTR)(a->w[0] + 0x310) < *(DWORD*)(ULONG_PTR)(b->w[0] + 0x310);
    }
};
struct RlLessCall {
    tRlPred p;
    bool operator()(const RlEl* a, const RlEl* b) const { return p(a, b); }
};
template<class L> static RlEl* rlMedian(RlEl* a, RlEl* b, RlEl* c, const L& less) {   // 0x572D07
    if (less(a, b)) {
        if (less(b, c)) return b;
        return less(a, c) ? c : a;
    }
    if (less(a, c)) return a;
    return less(b, c) ? c : b;
}
template<class L> static RlEl* rlPartition(RlEl* lo, RlEl* hi, const RlEl* pivot, const L& less) {   // 0x573359
    for (;;) {
        while (less(lo, pivot)) ++lo;
        do --hi; while (less(pivot, hi));
        if (lo >= hi) return lo;
        RlEl t = *lo; *lo = *hi; *hi = t;
        ++lo;
    }
}
template<class L> static void rlQuick(RlEl* begin, RlEl* end, int budget, const L& less, tRlPred pred) {   // 0x573F23
    while (end - begin > 16) {
        if (budget == 0) { g_rlHeapFalls++; ((tRlHeap)(ULONG_PTR)kRlHeap)(begin, end, end, pred); return; }
        --budget;
        RlEl pivot = *rlMedian(begin, begin + (end - begin) / 2, end - 1, less);
        RlEl* pos = rlPartition(begin, end, &pivot, less);
        rlQuick(pos, end, budget, less, pred);
        end = pos;
    }
}
template<class L> static void rlInsertFirst(RlEl* begin, RlEl* end, const L& less) {   // 0x57369C / 0x5733BE: element smaller than the first goes to the front
    if (begin == end) return;
    for (RlEl* cur = begin + 1; cur != end; ++cur) {
        RlEl tmp = *cur;
        if (less(&tmp, begin)) {
            memmove(begin + 1, begin, (size_t)(cur - begin) * sizeof(RlEl));
            *begin = tmp;
        } else {
            RlEl* p = cur;
            while (less(&tmp, p - 1)) { *p = p[-1]; --p; }
            *p = tmp;
        }
    }
}
template<class L> static void rlInsertRest(RlEl* begin, RlEl* end, const L& less) {   // 0x5730A1 / 0x572D7C: no lower bound (the front holds a minimum)
    for (RlEl* cur = begin; cur != end; ++cur) {
        RlEl tmp = *cur;
        RlEl* p = cur;
        while (less(&tmp, p - 1)) { *p = p[-1]; --p; }
        *p = tmp;
    }
}
template<class L> static void rlSortBudget(RlEl* begin, RlEl* end, int budget, const L& less, tRlPred pred) {   // 0x573F23 then 0x5738FD
    rlQuick(begin, end, budget, less, pred);
    if (end - begin > 16) { rlInsertFirst(begin, begin + 16, less); rlInsertRest(begin + 16, end, less); }
    else rlInsertFirst(begin, end, less);
}
template<class L> static void rlSortWith(RlEl* begin, RlEl* end, const L& less, tRlPred pred) {   // 0x5740D0
    int n = (int)(end - begin), lg = 0;
    while (n != 1) { ++lg; n >>= 1; }
    rlSortBudget(begin, end, 2 * lg, less, pred);
}
static void rlFastSort(RlEl* begin, RlEl* end, tRlPred pred) {
    if (begin == end) return;
    DWORD p = (DWORD)(ULONG_PTR)pred;
    if (p == kRlLessModel) rlSortWith(begin, end, RlLessModel(), pred);
    else if (p == kRlLessModelInst) rlSortWith(begin, end, RlLessModelInst(), pred);
    else { RlLessCall c = { pred }; rlSortWith(begin, end, c, pred); }
}

// 0x57430D without its temporaries: append {mesh, n, lights[0..n)} to the list the mesh's model flags select (+0x00 plain,
// +0x0C or +0x18 by [[model+0xBC]]). The list takes over the reference the caller passed in; each light gains one. Returns
// false where the stock code has to run instead: more than 6 lights, or no spare capacity (the stock push reallocates).
static __forceinline bool rlPushFast(DWORD* r, DWORD mesh, const DWORD* lights) {
    DWORD n = (DWORD)((LONG)(lights[1] - lights[0]) >> 2);
    if (n > 6) return false;
    DWORD model = *(DWORD*)(ULONG_PTR)(mesh + 0xC4);
    DWORD* v = r;
    if (*(BYTE*)(ULONG_PTR)(model + 0x19) & 4) v = *(BYTE*)(ULONG_PTR)(*(DWORD*)(ULONG_PTR)(model + 0xBC)) ? r + 3 : r + 6;
    if (((LONG)(v[2] - v[1]) >> 5) < 1) return false;
    DWORD* e = (DWORD*)(ULONG_PTR)v[1];
    const DWORD* src = (const DWORD*)(ULONG_PTR)lights[0];
    e[0] = mesh; e[1] = n;
    for (DWORD i = 0; i < 6; ++i) {
        DWORD p = i < n ? src[i] : 0;
        if (p) ++*(LONG*)(ULONG_PTR)(p + 4);
        e[2 + i] = p;
    }
    v[1] += 32;
    return true;
}
// reference release as the element destructor does it (0x47AF67): count at +4, Delete_This() in vtable slot 0 at zero
static __forceinline void rlRelease(DWORD p) {
    if (p && --*(LONG*)(ULONG_PTR)(p + 4) == 0) {
        typedef void (__fastcall* tDeleteThis)(DWORD, DWORD);
        ((tDeleteThis)(ULONG_PTR)(*(DWORD*)(ULONG_PTR)(*(DWORD*)(ULONG_PTR)p)))(p, 0);
    }
}
// 0x573816 erase(first, last) when it removes the whole tail: the stock order destroys [first, last) front to back, each
// element's lights back to front then its mesh, and moves the end back afterwards. Middle erases stay stock.
static __forceinline bool rlEraseTailFast(DWORD* v, DWORD first, DWORD last) {
    if (last != v[1]) return false;
    for (DWORD a = first; a != last; a += 32) {
        const DWORD* el = (const DWORD*)(ULONG_PTR)a;
        for (int i = 7; i >= 2; --i) rlRelease(el[i]);
        rlRelease(el[0]);
    }
    v[1] = first;
    return true;
}
