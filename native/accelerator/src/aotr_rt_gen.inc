// Upstream generated hooks, maintained here with the pySAGE execution-lock changes.
// See native/accelerator/UPSTREAM.txt before regenerating.
static void* g_rtO_dev[119];
static void* g_rtO_fx[79];
static void* g_rtO_tex[22];
static void* g_rtO_cube[22];
static void* g_rtO_vtex[22];
static void* g_rtO_surf[17];
static void* g_rtO_vol[11];
static void* g_rtO_vb[14];
static void* g_rtO_ib[14];
static void* g_rtO_sb[6];
static void* g_rtO_q[8];
static void* g_rtO_sc[10];
static void* g_rtO_vs[5];
static void* g_rtO_ps[5];
static void* g_rtO_decl[5];

static DWORD __stdcall rt_dev_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[0])(self, a0, a1);
    }
    rtSyncNote(0, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 0;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[0]++; return r;
}
static DWORD __stdcall rt_dev_1(void* self) {   // AddRef [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_dev[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_dev[1])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_dev[1])(self);
}
static DWORD __stdcall rt_dev_2(void* self) {   // Release [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_dev[2])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_dev[2])(self);
    }
    rtSyncNote(2, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 2;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_dev[2])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[2]++; return r;
}
static DWORD __stdcall rt_dev_3(void* self) {   // TestCooperativeLevel [L ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_dev[3])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_dev[3])(self);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_dev[3])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_4(void* self) {   // GetAvailableTextureMem [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_dev[4])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_dev[4])(self);
    }
    rtSyncNote(4, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 4;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_dev[4])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[4]++; return r;
}
static DWORD __stdcall rt_dev_5(void* self) {   // EvictManagedResources [A ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_dev[5])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_dev[5])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_dev[5]; r->op = 5;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_6(void* self, DWORD a0) {   // GetDirect3D [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[6])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[6])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[6])(self, a0);
}
static DWORD __stdcall rt_dev_7(void* self, DWORD a0) {   // GetDeviceCaps [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[7])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[7])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[7])(self, a0);
}
static DWORD __stdcall rt_dev_8(void* self, DWORD a0, DWORD a1) {   // GetDisplayMode [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[8])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[8])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[8])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_9(void* self, DWORD a0) {   // GetCreationParameters [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[9])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[9])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[9])(self, a0);
}
static DWORD __stdcall rt_dev_10(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetCursorProperties [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[10])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[10])(self, a0, a1, a2);
    }
    rtSyncNote(10, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 10;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[10])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[10]++; return r;
}
static DWORD __stdcall rt_dev_11(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetCursorPosition [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[11])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[11])(self, a0, a1, a2);
    }
    rtSyncNote(11, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 11;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[11])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[11]++; return r;
}
static DWORD __stdcall rt_dev_12(void* self, DWORD a0) {   // ShowCursor [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[12])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[12])(self, a0);
    }
    rtSyncNote(12, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 12;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[12])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[12]++; return r;
}
static DWORD __stdcall rt_dev_13(void* self, DWORD a0, DWORD a1) {   // CreateAdditionalSwapChain [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[13])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[13])(self, a0, a1);
    }
    rtSyncNote(13, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 13;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[13])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[13]++; return r;
}
static DWORD __stdcall rt_dev_14(void* self, DWORD a0, DWORD a1) {   // GetSwapChain [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[14])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[14])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[14])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_15(void* self) {   // GetNumberOfSwapChains [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_dev[15])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_dev[15])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_dev[15])(self);
}
static DWORD __stdcall rt_dev_16(void* self, DWORD a0);   // Reset (hand-written)
static DWORD __stdcall rt_dev_17(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3);   // Present (hand-written)
static DWORD __stdcall rt_dev_18(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {   // GetBackBuffer [L vvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[18])(self, a0, a1, a2, a3); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[18])(self, a0, a1, a2, a3);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[18])(self, a0, a1, a2, a3); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_19(void* self, DWORD a0, DWORD a1) {   // GetRasterStatus [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[19])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[19])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[19])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_20(void* self, DWORD a0) {   // SetDialogBoxMode [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[20])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[20])(self, a0);
    }
    rtSyncNote(20, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 20;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[20])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[20]++; return r;
}
static DWORD __stdcall rt_dev_21(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetGammaRamp [A vvp1536]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[21])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[21])(self, a0, a1, a2);
    }
    DWORD pl = (a2 ? 1536 : 0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_dev[21]; r->op = 21;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = a1;
    A[3] = rtBytes(P, &po, a2, 1536);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_22(void* self, DWORD a0, DWORD a1) {   // GetGammaRamp [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[22])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[22])(self, a0, a1);
    }
    rtSyncNote(22, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 22;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[22])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[22]++; return r;
}
static DWORD __stdcall rt_dev_23(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4, DWORD a5, DWORD a6, DWORD a7);   // CreateTexture (hand-written)
static DWORD __stdcall rt_dev_24(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4, DWORD a5, DWORD a6, DWORD a7, DWORD a8) {   // CreateVolumeTexture [L vvvvvvvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[24])(self, a0, a1, a2, a3, a4, a5, a6, a7, a8); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[24])(self, a0, a1, a2, a3, a4, a5, a6, a7, a8);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[24])(self, a0, a1, a2, a3, a4, a5, a6, a7, a8); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_25(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4, DWORD a5, DWORD a6) {   // CreateCubeTexture [L vvvvvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[25])(self, a0, a1, a2, a3, a4, a5, a6); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[25])(self, a0, a1, a2, a3, a4, a5, a6);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[25])(self, a0, a1, a2, a3, a4, a5, a6); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_26(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4, DWORD a5) {   // CreateVertexBuffer [L vvvvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[26])(self, a0, a1, a2, a3, a4, a5); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[26])(self, a0, a1, a2, a3, a4, a5);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[26])(self, a0, a1, a2, a3, a4, a5); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_27(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4, DWORD a5) {   // CreateIndexBuffer [L vvvvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[27])(self, a0, a1, a2, a3, a4, a5); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[27])(self, a0, a1, a2, a3, a4, a5);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[27])(self, a0, a1, a2, a3, a4, a5); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_28(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4, DWORD a5, DWORD a6, DWORD a7) {   // CreateRenderTarget [L vvvvvvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[28])(self, a0, a1, a2, a3, a4, a5, a6, a7); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[28])(self, a0, a1, a2, a3, a4, a5, a6, a7);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[28])(self, a0, a1, a2, a3, a4, a5, a6, a7); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_29(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4, DWORD a5, DWORD a6, DWORD a7) {   // CreateDepthStencilSurface [L vvvvvvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[29])(self, a0, a1, a2, a3, a4, a5, a6, a7); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[29])(self, a0, a1, a2, a3, a4, a5, a6, a7);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[29])(self, a0, a1, a2, a3, a4, a5, a6, a7); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_30(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3);   // UpdateSurface (hand-written)
static DWORD __stdcall rt_dev_31(void* self, DWORD a0, DWORD a1) {   // UpdateTexture [A oo]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[31])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[31])(self, a0, a1);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(3, pl); r->fn = g_rtO_dev[31]; r->op = 31;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtObj(r, 1, a0);
    A[2] = rtObj(r, 2, a1);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_32(void* self, DWORD a0, DWORD a1) {   // GetRenderTargetData [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[32])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[32])(self, a0, a1);
    }
    rtSyncNote(32, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 32;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[32])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[32]++; return r;
}
static DWORD __stdcall rt_dev_33(void* self, DWORD a0, DWORD a1) {   // GetFrontBufferData [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[33])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[33])(self, a0, a1);
    }
    rtSyncNote(33, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 33;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[33])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[33]++; return r;
}
static DWORD __stdcall rt_dev_34(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4) {   // StretchRect [A op16op16v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[34])(self, a0, a1, a2, a3, a4); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[34])(self, a0, a1, a2, a3, a4);
    }
    DWORD pl = (a1 ? 16 : 0) + (a3 ? 16 : 0);
    RtRec* r = rtAlloc(6, pl); r->fn = g_rtO_dev[34]; r->op = 34;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtObj(r, 1, a0);
    A[2] = rtBytes(P, &po, a1, 16);
    A[3] = rtObj(r, 3, a2);
    A[4] = rtBytes(P, &po, a3, 16);
    A[5] = a4;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_35(void* self, DWORD a0, DWORD a1, DWORD a2) {   // ColorFill [A op16v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[35])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[35])(self, a0, a1, a2);
    }
    DWORD pl = (a1 ? 16 : 0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_dev[35]; r->op = 35;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtObj(r, 1, a0);
    A[2] = rtBytes(P, &po, a1, 16);
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_36(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4, DWORD a5) {   // CreateOffscreenPlainSurface [L vvvvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[36])(self, a0, a1, a2, a3, a4, a5); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[36])(self, a0, a1, a2, a3, a4, a5);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[36])(self, a0, a1, a2, a3, a4, a5); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_37(void* self, DWORD a0, DWORD a1);   // SetRenderTarget (hand-written)
static DWORD __stdcall rt_dev_38(void* self, DWORD a0, DWORD a1);   // GetRenderTarget (hand-written)
static DWORD __stdcall rt_dev_39(void* self, DWORD a0);   // SetDepthStencilSurface (hand-written)
static DWORD __stdcall rt_dev_40(void* self, DWORD a0);   // GetDepthStencilSurface (hand-written)
static DWORD __stdcall rt_dev_41(void* self) {   // BeginScene [A ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_dev[41])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_dev[41])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_dev[41]; r->op = 41;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_42(void* self) {   // EndScene [A ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_dev[42])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_dev[42])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_dev[42]; r->op = 42;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_43(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4, DWORD a5) {   // Clear [A vpc16@0vvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[43])(self, a0, a1, a2, a3, a4, a5); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[43])(self, a0, a1, a2, a3, a4, a5);
    }
    DWORD pl = (a1 ? a0 * 16 : 0);
    RtRec* r = rtAlloc(7, pl); r->fn = g_rtO_dev[43]; r->op = 43;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = rtBytes(P, &po, a1, a1 ? a0 * 16 : 0);
    A[3] = a2;
    A[4] = a3;
    A[5] = a4;
    A[6] = a5;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_44(void* self, DWORD a0, DWORD a1) {   // SetTransform [A vp64]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[44])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[44])(self, a0, a1);
    }
    DWORD pl = (a1 ? 64 : 0);
    RtRec* r = rtAlloc(3, pl); r->fn = g_rtO_dev[44]; r->op = 44;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = rtBytes(P, &po, a1, 64);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_45(void* self, DWORD a0, DWORD a1) {   // GetTransform [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[45])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[45])(self, a0, a1);
    }
    rtSyncNote(45, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 45;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[45])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[45]++; return r;
}
static DWORD __stdcall rt_dev_46(void* self, DWORD a0, DWORD a1) {   // MultiplyTransform [A vp64]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[46])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[46])(self, a0, a1);
    }
    DWORD pl = (a1 ? 64 : 0);
    RtRec* r = rtAlloc(3, pl); r->fn = g_rtO_dev[46]; r->op = 46;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = rtBytes(P, &po, a1, 64);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_47(void* self, DWORD a0) {   // SetViewport [A p24]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[47])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[47])(self, a0);
    }
    DWORD pl = (a0 ? 24 : 0);
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_dev[47]; r->op = 47;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtBytes(P, &po, a0, 24);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_48(void* self, DWORD a0) {   // GetViewport [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[48])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[48])(self, a0);
    }
    rtSyncNote(48, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 48;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[48])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[48]++; return r;
}
static DWORD __stdcall rt_dev_49(void* self, DWORD a0) {   // SetMaterial [A p68]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[49])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[49])(self, a0);
    }
    DWORD pl = (a0 ? 68 : 0);
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_dev[49]; r->op = 49;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtBytes(P, &po, a0, 68);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_50(void* self, DWORD a0) {   // GetMaterial [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[50])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[50])(self, a0);
    }
    rtSyncNote(50, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 50;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[50])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[50]++; return r;
}
static DWORD __stdcall rt_dev_51(void* self, DWORD a0, DWORD a1) {   // SetLight [A vp104]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[51])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[51])(self, a0, a1);
    }
    DWORD pl = (a1 ? 104 : 0);
    RtRec* r = rtAlloc(3, pl); r->fn = g_rtO_dev[51]; r->op = 51;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = rtBytes(P, &po, a1, 104);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_52(void* self, DWORD a0, DWORD a1) {   // GetLight [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[52])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[52])(self, a0, a1);
    }
    rtSyncNote(52, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 52;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[52])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[52]++; return r;
}
static DWORD __stdcall rt_dev_53(void* self, DWORD a0, DWORD a1) {   // LightEnable [A vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[53])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[53])(self, a0, a1);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(3, pl); r->fn = g_rtO_dev[53]; r->op = 53;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = a1;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_54(void* self, DWORD a0, DWORD a1) {   // GetLightEnable [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[54])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[54])(self, a0, a1);
    }
    rtSyncNote(54, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 54;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[54])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[54]++; return r;
}
static DWORD __stdcall rt_dev_55(void* self, DWORD a0, DWORD a1) {   // SetClipPlane [A vp16]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[55])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[55])(self, a0, a1);
    }
    DWORD pl = (a1 ? 16 : 0);
    RtRec* r = rtAlloc(3, pl); r->fn = g_rtO_dev[55]; r->op = 55;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = rtBytes(P, &po, a1, 16);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_56(void* self, DWORD a0, DWORD a1) {   // GetClipPlane [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[56])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[56])(self, a0, a1);
    }
    rtSyncNote(56, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 56;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[56])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[56]++; return r;
}
static DWORD __stdcall rt_dev_57(void* self, DWORD a0, DWORD a1) {   // SetRenderState [A vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[57])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[57])(self, a0, a1);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(3, pl); r->fn = g_rtO_dev[57]; r->op = 57;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = a1;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_58(void* self, DWORD a0, DWORD a1) {   // GetRenderState [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[58])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[58])(self, a0, a1);
    }
    rtSyncNote(58, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 58;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[58])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[58]++; return r;
}
static DWORD __stdcall rt_dev_59(void* self, DWORD a0, DWORD a1) {   // CreateStateBlock [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[59])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[59])(self, a0, a1);
    }
    rtSyncNote(59, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 59;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[59])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[59]++; return r;
}
static DWORD __stdcall rt_dev_60(void* self) {   // BeginStateBlock [S ]
    rtDsRecording(1);
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_dev[60])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_dev[60])(self);
    }
    rtSyncNote(60, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 60;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_dev[60])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[60]++; return r;
}
static DWORD __stdcall rt_dev_61(void* self, DWORD a0) {   // EndStateBlock [S v]
    rtDsRecording(0);
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[61])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[61])(self, a0);
    }
    rtSyncNote(61, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 61;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[61])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[61]++; return r;
}
static DWORD __stdcall rt_dev_62(void* self, DWORD a0) {   // SetClipStatus [A p8]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[62])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[62])(self, a0);
    }
    DWORD pl = (a0 ? 8 : 0);
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_dev[62]; r->op = 62;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtBytes(P, &po, a0, 8);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_63(void* self, DWORD a0) {   // GetClipStatus [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[63])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[63])(self, a0);
    }
    rtSyncNote(63, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 63;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[63])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[63]++; return r;
}
static DWORD __stdcall rt_dev_64(void* self, DWORD a0, DWORD a1) {   // GetTexture [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[64])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[64])(self, a0, a1);
    }
    rtSyncNote(64, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 64;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[64])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[64]++; return r;
}
static DWORD __stdcall rt_dev_65(void* self, DWORD a0, DWORD a1) {   // SetTexture [A vo]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[65])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[65])(self, a0, a1);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(3, pl); r->fn = g_rtO_dev[65]; r->op = 65;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = rtObj(r, 2, a1);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_66(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetTextureStageState [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[66])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[66])(self, a0, a1, a2);
    }
    rtSyncNote(66, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 66;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[66])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[66]++; return r;
}
static DWORD __stdcall rt_dev_67(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetTextureStageState [A vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[67])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[67])(self, a0, a1, a2);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_dev[67]; r->op = 67;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = a1;
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_68(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetSamplerState [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[68])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[68])(self, a0, a1, a2);
    }
    rtSyncNote(68, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 68;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[68])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[68]++; return r;
}
static DWORD __stdcall rt_dev_69(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetSamplerState [A vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[69])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[69])(self, a0, a1, a2);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_dev[69]; r->op = 69;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = a1;
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_70(void* self, DWORD a0) {   // ValidateDevice [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[70])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[70])(self, a0);
    }
    rtSyncNote(70, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 70;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[70])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[70]++; return r;
}
static DWORD __stdcall rt_dev_71(void* self, DWORD a0, DWORD a1) {   // SetPaletteEntries [A vp1024]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[71])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[71])(self, a0, a1);
    }
    DWORD pl = (a1 ? 1024 : 0);
    RtRec* r = rtAlloc(3, pl); r->fn = g_rtO_dev[71]; r->op = 71;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = rtBytes(P, &po, a1, 1024);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_72(void* self, DWORD a0, DWORD a1) {   // GetPaletteEntries [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[72])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[72])(self, a0, a1);
    }
    rtSyncNote(72, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 72;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[72])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[72]++; return r;
}
static DWORD __stdcall rt_dev_73(void* self, DWORD a0) {   // SetCurrentTexturePalette [A v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[73])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[73])(self, a0);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_dev[73]; r->op = 73;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_74(void* self, DWORD a0) {   // GetCurrentTexturePalette [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[74])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[74])(self, a0);
    }
    rtSyncNote(74, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 74;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[74])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[74]++; return r;
}
static DWORD __stdcall rt_dev_75(void* self, DWORD a0) {   // SetScissorRect [A p16]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[75])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[75])(self, a0);
    }
    DWORD pl = (a0 ? 16 : 0);
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_dev[75]; r->op = 75;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtBytes(P, &po, a0, 16);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_76(void* self, DWORD a0) {   // GetScissorRect [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[76])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[76])(self, a0);
    }
    rtSyncNote(76, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 76;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[76])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[76]++; return r;
}
static DWORD __stdcall rt_dev_77(void* self, DWORD a0) {   // SetSoftwareVertexProcessing [A v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[77])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[77])(self, a0);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_dev[77]; r->op = 77;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_78(void* self) {   // GetSoftwareVertexProcessing [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_dev[78])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_dev[78])(self);
    }
    rtSyncNote(78, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 78;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_dev[78])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[78]++; return r;
}
static DWORD __stdcall rt_dev_79(void* self, DWORD a0) {   // SetNPatchMode [A v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[79])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[79])(self, a0);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_dev[79]; r->op = 79;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    rtCommit(r, po); return 0;
}
static float __stdcall rt_dev_80(void* self);   // GetNPatchMode (hand-written, float return)
static DWORD __stdcall rt_dev_81(void* self, DWORD a0, DWORD a1, DWORD a2) {   // DrawPrimitive [A vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[81])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[81])(self, a0, a1, a2);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_dev[81]; r->op = 81;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = a1;
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_82(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4, DWORD a5) {   // DrawIndexedPrimitive [A vvvvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[82])(self, a0, a1, a2, a3, a4, a5); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[82])(self, a0, a1, a2, a3, a4, a5);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(7, pl); r->fn = g_rtO_dev[82]; r->op = 82;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = a1;
    A[3] = a2;
    A[4] = a3;
    A[5] = a4;
    A[6] = a5;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_83(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3);   // DrawPrimitiveUP (hand-written)
static DWORD __stdcall rt_dev_84(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4, DWORD a5, DWORD a6, DWORD a7);   // DrawIndexedPrimitiveUP (hand-written)
static DWORD __stdcall rt_dev_85(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4, DWORD a5) {   // ProcessVertices [S vvvvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[85])(self, a0, a1, a2, a3, a4, a5); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[85])(self, a0, a1, a2, a3, a4, a5);
    }
    rtSyncNote(85, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 85;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[85])(self, a0, a1, a2, a3, a4, a5); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[85]++; return r;
}
static DWORD __stdcall rt_dev_86(void* self, DWORD a0, DWORD a1) {   // CreateVertexDeclaration [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[86])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[86])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[86])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_87(void* self, DWORD a0);   // SetVertexDeclaration (hand-written)
static DWORD __stdcall rt_dev_88(void* self, DWORD a0) {   // GetVertexDeclaration [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[88])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[88])(self, a0);
    }
    rtSyncNote(88, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 88;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[88])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[88]++; return r;
}
static DWORD __stdcall rt_dev_89(void* self, DWORD a0) {   // SetFVF [A v]
    rtDsInvalDecl();
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[89])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[89])(self, a0);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_dev[89]; r->op = 89;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_90(void* self, DWORD a0) {   // GetFVF [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[90])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[90])(self, a0);
    }
    rtSyncNote(90, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 90;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[90])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[90]++; return r;
}
static DWORD __stdcall rt_dev_91(void* self, DWORD a0, DWORD a1) {   // CreateVertexShader [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[91])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[91])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[91])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_92(void* self, DWORD a0) {   // SetVertexShader [A o]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[92])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[92])(self, a0);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_dev[92]; r->op = 92;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtObj(r, 1, a0);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_93(void* self, DWORD a0) {   // GetVertexShader [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[93])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[93])(self, a0);
    }
    rtSyncNote(93, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 93;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[93])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[93]++; return r;
}
static DWORD __stdcall rt_dev_94(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetVertexShaderConstantF [A vpc16@2v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[94])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[94])(self, a0, a1, a2);
    }
    DWORD pl = (a1 ? a2 * 16 : 0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_dev[94]; r->op = 94;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = rtBytes(P, &po, a1, a1 ? a2 * 16 : 0);
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_95(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetVertexShaderConstantF [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[95])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[95])(self, a0, a1, a2);
    }
    rtSyncNote(95, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 95;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[95])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[95]++; return r;
}
static DWORD __stdcall rt_dev_96(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetVertexShaderConstantI [A vpc16@2v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[96])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[96])(self, a0, a1, a2);
    }
    DWORD pl = (a1 ? a2 * 16 : 0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_dev[96]; r->op = 96;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = rtBytes(P, &po, a1, a1 ? a2 * 16 : 0);
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_97(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetVertexShaderConstantI [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[97])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[97])(self, a0, a1, a2);
    }
    rtSyncNote(97, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 97;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[97])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[97]++; return r;
}
static DWORD __stdcall rt_dev_98(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetVertexShaderConstantB [A vpc4@2v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[98])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[98])(self, a0, a1, a2);
    }
    DWORD pl = (a1 ? a2 * 4 : 0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_dev[98]; r->op = 98;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = rtBytes(P, &po, a1, a1 ? a2 * 4 : 0);
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_99(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetVertexShaderConstantB [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[99])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[99])(self, a0, a1, a2);
    }
    rtSyncNote(99, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 99;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[99])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[99]++; return r;
}
static DWORD __stdcall rt_dev_100(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3);   // SetStreamSource (hand-written)
static DWORD __stdcall rt_dev_101(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {   // GetStreamSource [S vvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[101])(self, a0, a1, a2, a3); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[101])(self, a0, a1, a2, a3);
    }
    rtSyncNote(101, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 101;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_dev[101])(self, a0, a1, a2, a3); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[101]++; return r;
}
static DWORD __stdcall rt_dev_102(void* self, DWORD a0, DWORD a1) {   // SetStreamSourceFreq [A vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[102])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[102])(self, a0, a1);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(3, pl); r->fn = g_rtO_dev[102]; r->op = 102;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = a1;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_103(void* self, DWORD a0, DWORD a1) {   // GetStreamSourceFreq [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[103])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[103])(self, a0, a1);
    }
    rtSyncNote(103, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 103;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[103])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[103]++; return r;
}
static DWORD __stdcall rt_dev_104(void* self, DWORD a0);   // SetIndices (hand-written)
static DWORD __stdcall rt_dev_105(void* self, DWORD a0) {   // GetIndices [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[105])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[105])(self, a0);
    }
    rtSyncNote(105, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 105;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[105])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[105]++; return r;
}
static DWORD __stdcall rt_dev_106(void* self, DWORD a0, DWORD a1) {   // CreatePixelShader [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[106])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[106])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[106])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_dev_107(void* self, DWORD a0) {   // SetPixelShader [A o]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[107])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[107])(self, a0);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_dev[107]; r->op = 107;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtObj(r, 1, a0);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_108(void* self, DWORD a0) {   // GetPixelShader [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[108])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[108])(self, a0);
    }
    rtSyncNote(108, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 108;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[108])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[108]++; return r;
}
static DWORD __stdcall rt_dev_109(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetPixelShaderConstantF [A vpc16@2v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[109])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[109])(self, a0, a1, a2);
    }
    DWORD pl = (a1 ? a2 * 16 : 0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_dev[109]; r->op = 109;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = rtBytes(P, &po, a1, a1 ? a2 * 16 : 0);
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_110(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetPixelShaderConstantF [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[110])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[110])(self, a0, a1, a2);
    }
    rtSyncNote(110, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 110;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[110])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[110]++; return r;
}
static DWORD __stdcall rt_dev_111(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetPixelShaderConstantI [A vpc16@2v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[111])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[111])(self, a0, a1, a2);
    }
    DWORD pl = (a1 ? a2 * 16 : 0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_dev[111]; r->op = 111;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = rtBytes(P, &po, a1, a1 ? a2 * 16 : 0);
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_112(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetPixelShaderConstantI [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[112])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[112])(self, a0, a1, a2);
    }
    rtSyncNote(112, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 112;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[112])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[112]++; return r;
}
static DWORD __stdcall rt_dev_113(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetPixelShaderConstantB [A vpc4@2v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[113])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[113])(self, a0, a1, a2);
    }
    DWORD pl = (a1 ? a2 * 4 : 0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_dev[113]; r->op = 113;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    A[2] = rtBytes(P, &po, a1, a1 ? a2 * 4 : 0);
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_dev_114(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetPixelShaderConstantB [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[114])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[114])(self, a0, a1, a2);
    }
    rtSyncNote(114, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 114;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[114])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[114]++; return r;
}
static DWORD __stdcall rt_dev_115(void* self, DWORD a0, DWORD a1, DWORD a2) {   // DrawRectPatch [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[115])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[115])(self, a0, a1, a2);
    }
    rtSyncNote(115, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 115;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[115])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[115]++; return r;
}
static DWORD __stdcall rt_dev_116(void* self, DWORD a0, DWORD a1, DWORD a2) {   // DrawTriPatch [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[116])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[116])(self, a0, a1, a2);
    }
    rtSyncNote(116, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 116;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_dev[116])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[116]++; return r;
}
static DWORD __stdcall rt_dev_117(void* self, DWORD a0) {   // DeletePatch [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[117])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[117])(self, a0);
    }
    rtSyncNote(117, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 117;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_dev[117])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[117]++; return r;
}
static DWORD __stdcall rt_dev_118(void* self, DWORD a0, DWORD a1) {   // CreateQuery [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[118])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[118])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_dev[118])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static void* const g_rtH_dev[119] = {(void*)&rt_dev_0, (void*)&rt_dev_1, (void*)&rt_dev_2, (void*)&rt_dev_3, (void*)&rt_dev_4, (void*)&rt_dev_5, (void*)&rt_dev_6, (void*)&rt_dev_7, (void*)&rt_dev_8, (void*)&rt_dev_9, (void*)&rt_dev_10, (void*)&rt_dev_11, (void*)&rt_dev_12, (void*)&rt_dev_13, (void*)&rt_dev_14, (void*)&rt_dev_15, (void*)&rt_dev_16, (void*)&rt_dev_17, (void*)&rt_dev_18, (void*)&rt_dev_19, (void*)&rt_dev_20, (void*)&rt_dev_21, (void*)&rt_dev_22, (void*)&rt_dev_23, (void*)&rt_dev_24, (void*)&rt_dev_25, (void*)&rt_dev_26, (void*)&rt_dev_27, (void*)&rt_dev_28, (void*)&rt_dev_29, (void*)&rt_dev_30, (void*)&rt_dev_31, (void*)&rt_dev_32, (void*)&rt_dev_33, (void*)&rt_dev_34, (void*)&rt_dev_35, (void*)&rt_dev_36, (void*)&rt_dev_37, (void*)&rt_dev_38, (void*)&rt_dev_39, (void*)&rt_dev_40, (void*)&rt_dev_41, (void*)&rt_dev_42, (void*)&rt_dev_43, (void*)&rt_dev_44, (void*)&rt_dev_45, (void*)&rt_dev_46, (void*)&rt_dev_47, (void*)&rt_dev_48, (void*)&rt_dev_49, (void*)&rt_dev_50, (void*)&rt_dev_51, (void*)&rt_dev_52, (void*)&rt_dev_53, (void*)&rt_dev_54, (void*)&rt_dev_55, (void*)&rt_dev_56, (void*)&rt_dev_57, (void*)&rt_dev_58, (void*)&rt_dev_59, (void*)&rt_dev_60, (void*)&rt_dev_61, (void*)&rt_dev_62, (void*)&rt_dev_63, (void*)&rt_dev_64, (void*)&rt_dev_65, (void*)&rt_dev_66, (void*)&rt_dev_67, (void*)&rt_dev_68, (void*)&rt_dev_69, (void*)&rt_dev_70, (void*)&rt_dev_71, (void*)&rt_dev_72, (void*)&rt_dev_73, (void*)&rt_dev_74, (void*)&rt_dev_75, (void*)&rt_dev_76, (void*)&rt_dev_77, (void*)&rt_dev_78, (void*)&rt_dev_79, (void*)&rt_dev_80, (void*)&rt_dev_81, (void*)&rt_dev_82, (void*)&rt_dev_83, (void*)&rt_dev_84, (void*)&rt_dev_85, (void*)&rt_dev_86, (void*)&rt_dev_87, (void*)&rt_dev_88, (void*)&rt_dev_89, (void*)&rt_dev_90, (void*)&rt_dev_91, (void*)&rt_dev_92, (void*)&rt_dev_93, (void*)&rt_dev_94, (void*)&rt_dev_95, (void*)&rt_dev_96, (void*)&rt_dev_97, (void*)&rt_dev_98, (void*)&rt_dev_99, (void*)&rt_dev_100, (void*)&rt_dev_101, (void*)&rt_dev_102, (void*)&rt_dev_103, (void*)&rt_dev_104, (void*)&rt_dev_105, (void*)&rt_dev_106, (void*)&rt_dev_107, (void*)&rt_dev_108, (void*)&rt_dev_109, (void*)&rt_dev_110, (void*)&rt_dev_111, (void*)&rt_dev_112, (void*)&rt_dev_113, (void*)&rt_dev_114, (void*)&rt_dev_115, (void*)&rt_dev_116, (void*)&rt_dev_117, (void*)&rt_dev_118};

static DWORD __stdcall rt_fx_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [L vv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[0])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_fx_1(void* self) {   // AddRef [S ]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_fx[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_fx[1])(self);
    }
    rtSyncNote(121, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 121;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_fx[1])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[121]++; return r;
}
static DWORD __stdcall rt_fx_2(void* self);   // Release (hand-written)
static DWORD __stdcall rt_fx_3(void* self, DWORD a0);   // GetDesc (hand-written)
static DWORD __stdcall rt_fx_4(void* self, DWORD a0, DWORD a1);   // GetParameterDesc (hand-written)
static DWORD __stdcall rt_fx_5(void* self, DWORD a0, DWORD a1);   // GetTechniqueDesc (hand-written)
static DWORD __stdcall rt_fx_6(void* self, DWORD a0, DWORD a1);   // GetPassDesc (hand-written)
static DWORD __stdcall rt_fx_7(void* self, DWORD a0, DWORD a1);   // GetFunctionDesc (hand-written)
static DWORD __stdcall rt_fx_8(void* self, DWORD a0, DWORD a1);   // GetParameter (hand-written)
static DWORD __stdcall rt_fx_9(void* self, DWORD a0, DWORD a1);   // GetParameterByName (hand-written)
static DWORD __stdcall rt_fx_10(void* self, DWORD a0, DWORD a1);   // GetParameterBySemantic (hand-written)
static DWORD __stdcall rt_fx_11(void* self, DWORD a0, DWORD a1);   // GetParameterElement (hand-written)
static DWORD __stdcall rt_fx_12(void* self, DWORD a0);   // GetTechnique (hand-written)
static DWORD __stdcall rt_fx_13(void* self, DWORD a0);   // GetTechniqueByName (hand-written)
static DWORD __stdcall rt_fx_14(void* self, DWORD a0, DWORD a1);   // GetPass (hand-written)
static DWORD __stdcall rt_fx_15(void* self, DWORD a0, DWORD a1);   // GetPassByName (hand-written)
static DWORD __stdcall rt_fx_16(void* self, DWORD a0);   // GetFunction (hand-written)
static DWORD __stdcall rt_fx_17(void* self, DWORD a0);   // GetFunctionByName (hand-written)
static DWORD __stdcall rt_fx_18(void* self, DWORD a0, DWORD a1);   // GetAnnotation (hand-written)
static DWORD __stdcall rt_fx_19(void* self, DWORD a0, DWORD a1);   // GetAnnotationByName (hand-written)
static DWORD __stdcall rt_fx_20(void* self, DWORD a0, DWORD a1, DWORD a2);   // SetValue (hand-written)
static DWORD __stdcall rt_fx_21(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetValue [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[21])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[21])(self, a0, a1, a2);
    }
    rtSyncNote(141, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 141;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[21])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[141]++; return r;
}
static DWORD __stdcall rt_fx_22(void* self, DWORD a0, DWORD a1);   // SetBool (hand-written)
static DWORD __stdcall rt_fx_23(void* self, DWORD a0, DWORD a1) {   // GetBool [S vv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[23])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[23])(self, a0, a1);
    }
    rtSyncNote(143, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 143;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[23])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[143]++; return r;
}
static DWORD __stdcall rt_fx_24(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetBoolArray [A hpc4@2v]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[24])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[24])(self, a0, a1, a2);
    }
    DWORD pl = rtHandleBytes(a0) + (a1 ? a2 * 4 : 0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_fx[24]; r->op = 144;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtHandle(P, &po, a0);
    A[2] = rtBytes(P, &po, a1, a1 ? a2 * 4 : 0);
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_fx_25(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetBoolArray [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[25])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[25])(self, a0, a1, a2);
    }
    rtSyncNote(145, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 145;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[25])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[145]++; return r;
}
static DWORD __stdcall rt_fx_26(void* self, DWORD a0, DWORD a1);   // SetInt (hand-written)
static DWORD __stdcall rt_fx_27(void* self, DWORD a0, DWORD a1);   // GetInt (hand-written)
static DWORD __stdcall rt_fx_28(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetIntArray [A hpc4@2v]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[28])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[28])(self, a0, a1, a2);
    }
    DWORD pl = rtHandleBytes(a0) + (a1 ? a2 * 4 : 0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_fx[28]; r->op = 148;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtHandle(P, &po, a0);
    A[2] = rtBytes(P, &po, a1, a1 ? a2 * 4 : 0);
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_fx_29(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetIntArray [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[29])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[29])(self, a0, a1, a2);
    }
    rtSyncNote(149, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 149;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[29])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[149]++; return r;
}
static DWORD __stdcall rt_fx_30(void* self, DWORD a0, DWORD a1);   // SetFloat (hand-written)
static DWORD __stdcall rt_fx_31(void* self, DWORD a0, DWORD a1) {   // GetFloat [S vv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[31])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[31])(self, a0, a1);
    }
    rtSyncNote(151, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 151;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[31])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[151]++; return r;
}
static DWORD __stdcall rt_fx_32(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetFloatArray [A hpc4@2v]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[32])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[32])(self, a0, a1, a2);
    }
    DWORD pl = rtHandleBytes(a0) + (a1 ? a2 * 4 : 0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_fx[32]; r->op = 152;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtHandle(P, &po, a0);
    A[2] = rtBytes(P, &po, a1, a1 ? a2 * 4 : 0);
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_fx_33(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetFloatArray [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[33])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[33])(self, a0, a1, a2);
    }
    rtSyncNote(153, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 153;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[33])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[153]++; return r;
}
static DWORD __stdcall rt_fx_34(void* self, DWORD a0, DWORD a1);   // SetVector (hand-written)
static DWORD __stdcall rt_fx_35(void* self, DWORD a0, DWORD a1) {   // GetVector [S vv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[35])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[35])(self, a0, a1);
    }
    rtSyncNote(155, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 155;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[35])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[155]++; return r;
}
static DWORD __stdcall rt_fx_36(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetVectorArray [A hpc16@2v]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[36])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[36])(self, a0, a1, a2);
    }
    DWORD pl = rtHandleBytes(a0) + (a1 ? a2 * 16 : 0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_fx[36]; r->op = 156;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtHandle(P, &po, a0);
    A[2] = rtBytes(P, &po, a1, a1 ? a2 * 16 : 0);
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_fx_37(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetVectorArray [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[37])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[37])(self, a0, a1, a2);
    }
    rtSyncNote(157, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 157;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[37])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[157]++; return r;
}
static DWORD __stdcall rt_fx_38(void* self, DWORD a0, DWORD a1);   // SetMatrix (hand-written)
static DWORD __stdcall rt_fx_39(void* self, DWORD a0, DWORD a1) {   // GetMatrix [S vv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[39])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[39])(self, a0, a1);
    }
    rtSyncNote(159, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 159;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[39])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[159]++; return r;
}
static DWORD __stdcall rt_fx_40(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetMatrixArray [A hpc64@2v]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[40])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[40])(self, a0, a1, a2);
    }
    DWORD pl = rtHandleBytes(a0) + (a1 ? a2 * 64 : 0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_fx[40]; r->op = 160;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtHandle(P, &po, a0);
    A[2] = rtBytes(P, &po, a1, a1 ? a2 * 64 : 0);
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_fx_41(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetMatrixArray [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[41])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[41])(self, a0, a1, a2);
    }
    rtSyncNote(161, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 161;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[41])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[161]++; return r;
}
static DWORD __stdcall rt_fx_42(void* self, DWORD a0, DWORD a1, DWORD a2);   // SetMatrixPointerArray (hand-written)
static DWORD __stdcall rt_fx_43(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetMatrixPointerArray [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[43])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[43])(self, a0, a1, a2);
    }
    rtSyncNote(163, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 163;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[43])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[163]++; return r;
}
static DWORD __stdcall rt_fx_44(void* self, DWORD a0, DWORD a1);   // SetMatrixTranspose (hand-written)
static DWORD __stdcall rt_fx_45(void* self, DWORD a0, DWORD a1) {   // GetMatrixTranspose [S vv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[45])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[45])(self, a0, a1);
    }
    rtSyncNote(165, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 165;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[45])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[165]++; return r;
}
static DWORD __stdcall rt_fx_46(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetMatrixTransposeArray [A hpc64@2v]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[46])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[46])(self, a0, a1, a2);
    }
    DWORD pl = rtHandleBytes(a0) + (a1 ? a2 * 64 : 0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_fx[46]; r->op = 166;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtHandle(P, &po, a0);
    A[2] = rtBytes(P, &po, a1, a1 ? a2 * 64 : 0);
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_fx_47(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetMatrixTransposeArray [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[47])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[47])(self, a0, a1, a2);
    }
    rtSyncNote(167, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 167;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[47])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[167]++; return r;
}
static DWORD __stdcall rt_fx_48(void* self, DWORD a0, DWORD a1, DWORD a2);   // SetMatrixTransposePointerArray (hand-written)
static DWORD __stdcall rt_fx_49(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetMatrixTransposePointerArray [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[49])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[49])(self, a0, a1, a2);
    }
    rtSyncNote(169, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 169;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[49])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[169]++; return r;
}
static DWORD __stdcall rt_fx_50(void* self, DWORD a0, DWORD a1) {   // SetString [A hs]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[50])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[50])(self, a0, a1);
    }
    DWORD pl = rtHandleBytes(a0) + rtStrBytes(a1);
    RtRec* r = rtAlloc(3, pl); r->fn = g_rtO_fx[50]; r->op = 170;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtHandle(P, &po, a0);
    A[2] = rtStr(P, &po, a1);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_fx_51(void* self, DWORD a0, DWORD a1) {   // GetString [S vv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[51])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[51])(self, a0, a1);
    }
    rtSyncNote(171, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 171;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[51])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[171]++; return r;
}
static DWORD __stdcall rt_fx_52(void* self, DWORD a0, DWORD a1);   // SetTexture (hand-written)
static DWORD __stdcall rt_fx_53(void* self, DWORD a0, DWORD a1) {   // GetTexture [S vv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[53])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[53])(self, a0, a1);
    }
    rtSyncNote(173, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 173;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[53])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[173]++; return r;
}
static DWORD __stdcall rt_fx_54(void* self, DWORD a0, DWORD a1) {   // GetPixelShader [S vv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[54])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[54])(self, a0, a1);
    }
    rtSyncNote(174, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 174;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[54])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[174]++; return r;
}
static DWORD __stdcall rt_fx_55(void* self, DWORD a0, DWORD a1) {   // GetVertexShader [S vv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[55])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[55])(self, a0, a1);
    }
    rtSyncNote(175, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 175;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[55])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[175]++; return r;
}
static DWORD __stdcall rt_fx_56(void* self, DWORD a0, DWORD a1, DWORD a2) {   // SetArrayRange [A hvv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[56])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_fx[56])(self, a0, a1, a2);
    }
    DWORD pl = rtHandleBytes(a0);
    RtRec* r = rtAlloc(4, pl); r->fn = g_rtO_fx[56]; r->op = 176;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = rtHandle(P, &po, a0);
    A[2] = a1;
    A[3] = a2;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_fx_57(void* self, DWORD a0) {   // GetPool [L v]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_fx[57])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_fx[57])(self, a0);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_fx[57])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_fx_58(void* self, DWORD a0);   // SetTechnique (hand-written)
static DWORD __stdcall rt_fx_59(void* self) {   // GetCurrentTechnique [S ]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_fx[59])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_fx[59])(self);
    }
    rtSyncNote(179, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 179;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_fx[59])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[179]++; return r;
}
static DWORD __stdcall rt_fx_60(void* self, DWORD a0) {   // ValidateTechnique [S v]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_fx[60])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_fx[60])(self, a0);
    }
    rtSyncNote(180, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 180;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_fx[60])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[180]++; return r;
}
static DWORD __stdcall rt_fx_61(void* self, DWORD a0, DWORD a1) {   // FindNextValidTechnique [S vv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[61])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[61])(self, a0, a1);
    }
    rtSyncNote(181, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 181;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[61])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[181]++; return r;
}
static DWORD __stdcall rt_fx_62(void* self, DWORD a0, DWORD a1);   // IsParameterUsed (hand-written)
static DWORD __stdcall rt_fx_63(void* self, DWORD a0, DWORD a1);   // Begin (hand-written)
static DWORD __stdcall rt_fx_64(void* self, DWORD a0) {   // BeginPass [A v]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_fx[64])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_fx[64])(self, a0);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_fx[64]; r->op = 184;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_fx_65(void* self) {   // CommitChanges [A ]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_fx[65])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_fx[65])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_fx[65]; r->op = 185;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_fx_66(void* self) {   // EndPass [A ]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_fx[66])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_fx[66])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_fx[66]; r->op = 186;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_fx_67(void* self) {   // End [A ]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_fx[67])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_fx[67])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_fx[67]; r->op = 187;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_fx_68(void* self, DWORD a0) {   // GetDevice [L v]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_fx[68])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_fx[68])(self, a0);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_fx[68])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_fx_69(void* self) {   // OnLostDevice [S ]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_fx[69])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_fx[69])(self);
    }
    rtSyncNote(189, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 189;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_fx[69])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[189]++; return r;
}
static DWORD __stdcall rt_fx_70(void* self) {   // OnResetDevice [S ]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_fx[70])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_fx[70])(self);
    }
    rtSyncNote(190, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 190;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_fx[70])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[190]++; return r;
}
static DWORD __stdcall rt_fx_71(void* self, DWORD a0);   // SetStateManager (hand-written)
static DWORD __stdcall rt_fx_72(void* self, DWORD a0) {   // GetStateManager [S v]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_fx[72])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_fx[72])(self, a0);
    }
    rtSyncNote(192, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 192;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_fx[72])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[192]++; return r;
}
static DWORD __stdcall rt_fx_73(void* self);   // BeginParameterBlock (hand-written)
static DWORD __stdcall rt_fx_74(void* self);   // EndParameterBlock (hand-written)
static DWORD __stdcall rt_fx_75(void* self, DWORD a0);   // ApplyParameterBlock (hand-written)
static DWORD __stdcall rt_fx_76(void* self, DWORD a0);   // DeleteParameterBlock (hand-written)
static DWORD __stdcall rt_fx_77(void* self, DWORD a0, DWORD a1) {   // CloneEffect [S vv]
    DWORD tid = __readfsdword(0x24);
    if (!g_rtActive && !g_rtTried && g_mkTid && tid == g_mkTid && !g_rtXDepth) rtInstall(self);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[77])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[77])(self, a0, a1);
    }
    rtSyncNote(197, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 197;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_fx[77])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[197]++; return r;
}
static DWORD __stdcall rt_fx_78(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3);   // SetRawValue (hand-written)
static void* const g_rtH_fx[79] = {(void*)&rt_fx_0, (void*)&rt_fx_1, (void*)&rt_fx_2, (void*)&rt_fx_3, (void*)&rt_fx_4, (void*)&rt_fx_5, (void*)&rt_fx_6, (void*)&rt_fx_7, (void*)&rt_fx_8, (void*)&rt_fx_9, (void*)&rt_fx_10, (void*)&rt_fx_11, (void*)&rt_fx_12, (void*)&rt_fx_13, (void*)&rt_fx_14, (void*)&rt_fx_15, (void*)&rt_fx_16, (void*)&rt_fx_17, (void*)&rt_fx_18, (void*)&rt_fx_19, (void*)&rt_fx_20, (void*)&rt_fx_21, (void*)&rt_fx_22, (void*)&rt_fx_23, (void*)&rt_fx_24, (void*)&rt_fx_25, (void*)&rt_fx_26, (void*)&rt_fx_27, (void*)&rt_fx_28, (void*)&rt_fx_29, (void*)&rt_fx_30, (void*)&rt_fx_31, (void*)&rt_fx_32, (void*)&rt_fx_33, (void*)&rt_fx_34, (void*)&rt_fx_35, (void*)&rt_fx_36, (void*)&rt_fx_37, (void*)&rt_fx_38, (void*)&rt_fx_39, (void*)&rt_fx_40, (void*)&rt_fx_41, (void*)&rt_fx_42, (void*)&rt_fx_43, (void*)&rt_fx_44, (void*)&rt_fx_45, (void*)&rt_fx_46, (void*)&rt_fx_47, (void*)&rt_fx_48, (void*)&rt_fx_49, (void*)&rt_fx_50, (void*)&rt_fx_51, (void*)&rt_fx_52, (void*)&rt_fx_53, (void*)&rt_fx_54, (void*)&rt_fx_55, (void*)&rt_fx_56, (void*)&rt_fx_57, (void*)&rt_fx_58, (void*)&rt_fx_59, (void*)&rt_fx_60, (void*)&rt_fx_61, (void*)&rt_fx_62, (void*)&rt_fx_63, (void*)&rt_fx_64, (void*)&rt_fx_65, (void*)&rt_fx_66, (void*)&rt_fx_67, (void*)&rt_fx_68, (void*)&rt_fx_69, (void*)&rt_fx_70, (void*)&rt_fx_71, (void*)&rt_fx_72, (void*)&rt_fx_73, (void*)&rt_fx_74, (void*)&rt_fx_75, (void*)&rt_fx_76, (void*)&rt_fx_77, (void*)&rt_fx_78};

static DWORD __stdcall rt_tex_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_tex[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_tex[0])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_tex[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_tex_1(void* self) {   // AddRef [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_tex[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_tex[1])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_tex[1])(self);
}
static DWORD __stdcall rt_tex_2(void* self) {   // Release [R ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_tex[2])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_tex[2])(self);
    }
    ULONG c = ((ULONG(__stdcall*)(void*))g_rtO_tex[1])(self);    // temporary reference keeps it alive until the queued releases run
    for (int k = 0; k < 2; ++k) { RtRec* rr = rtAlloc(1, 0); rr->fn = g_rtO_tex[2]; rr->op = 202; rtArgs(rr)[0] = (DWORD)(ULONG_PTR)self; rtCommit(rr, 0); }
    g_rtNRelease++; return c - 2;
}
static DWORD __stdcall rt_tex_3(void* self, DWORD a0) {   // GetDevice [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[3])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[3])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[3])(self, a0);
}
static DWORD __stdcall rt_tex_4(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {   // SetPrivateData [S vvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_tex[4])(self, a0, a1, a2, a3); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_tex[4])(self, a0, a1, a2, a3);
    }
    rtSyncNote(204, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 204;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_tex[4])(self, a0, a1, a2, a3); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[204]++; return r;
}
static DWORD __stdcall rt_tex_5(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetPrivateData [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_tex[5])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_tex[5])(self, a0, a1, a2);
    }
    rtSyncNote(205, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 205;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_tex[5])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[205]++; return r;
}
static DWORD __stdcall rt_tex_6(void* self, DWORD a0) {   // FreePrivateData [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[6])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[6])(self, a0);
    }
    rtSyncNote(206, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 206;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[6])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[206]++; return r;
}
static DWORD __stdcall rt_tex_7(void* self, DWORD a0) {   // SetPriority [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[7])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[7])(self, a0);
    }
    rtSyncNote(207, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 207;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[7])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[207]++; return r;
}
static DWORD __stdcall rt_tex_8(void* self) {   // GetPriority [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_tex[8])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_tex[8])(self);
    }
    rtSyncNote(208, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 208;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_tex[8])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[208]++; return r;
}
static DWORD __stdcall rt_tex_9(void* self) {   // PreLoad [A ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_tex[9])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_tex[9])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_tex[9]; r->op = 209;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtTouch((DWORD)(ULONG_PTR)self);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_tex_10(void* self) {   // GetType [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_tex[10])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_tex[10])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_tex[10])(self);
}
static DWORD __stdcall rt_tex_11(void* self, DWORD a0) {   // SetLOD [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[11])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[11])(self, a0);
    }
    rtSyncNote(211, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 211;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[11])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[211]++; return r;
}
static DWORD __stdcall rt_tex_12(void* self) {   // GetLOD [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_tex[12])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_tex[12])(self);
    }
    rtSyncNote(212, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 212;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_tex[12])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[212]++; return r;
}
static DWORD __stdcall rt_tex_13(void* self) {   // GetLevelCount [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_tex[13])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_tex[13])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_tex[13])(self);
}
static DWORD __stdcall rt_tex_14(void* self, DWORD a0) {   // SetAutoGenFilterType [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[14])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[14])(self, a0);
    }
    rtSyncNote(214, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 214;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[14])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[214]++; return r;
}
static DWORD __stdcall rt_tex_15(void* self) {   // GetAutoGenFilterType [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_tex[15])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_tex[15])(self);
    }
    rtSyncNote(215, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 215;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_tex[15])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[215]++; return r;
}
static DWORD __stdcall rt_tex_16(void* self) {   // GenerateMipSubLevels [A ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_tex[16])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_tex[16])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_tex[16]; r->op = 216;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtTouch((DWORD)(ULONG_PTR)self);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_tex_17(void* self, DWORD a0, DWORD a1) {   // GetLevelDesc [D vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_tex[17])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_tex[17])(self, a0, a1);
    }
    return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_tex[17])(self, a0, a1);
}
static DWORD __stdcall rt_tex_18(void* self, DWORD a0, DWORD a1) {   // GetSurfaceLevel [D vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_tex[18])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_tex[18])(self, a0, a1);
    }
    return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_tex[18])(self, a0, a1);
}
static DWORD __stdcall rt_tex_19(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3);   // LockRect (hand-written)
static DWORD __stdcall rt_tex_20(void* self, DWORD a0);   // UnlockRect (hand-written)
static DWORD __stdcall rt_tex_21(void* self, DWORD a0) {   // AddDirtyRect [A p16]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[21])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_tex[21])(self, a0);
    }
    DWORD pl = (a0 ? 16 : 0);
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_tex[21]; r->op = 221;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtTouch((DWORD)(ULONG_PTR)self);
    A[1] = rtBytes(P, &po, a0, 16);
    rtCommit(r, po); return 0;
}
static void* const g_rtH_tex[22] = {(void*)&rt_tex_0, (void*)&rt_tex_1, (void*)&rt_tex_2, (void*)&rt_tex_3, (void*)&rt_tex_4, (void*)&rt_tex_5, (void*)&rt_tex_6, (void*)&rt_tex_7, (void*)&rt_tex_8, (void*)&rt_tex_9, (void*)&rt_tex_10, (void*)&rt_tex_11, (void*)&rt_tex_12, (void*)&rt_tex_13, (void*)&rt_tex_14, (void*)&rt_tex_15, (void*)&rt_tex_16, (void*)&rt_tex_17, (void*)&rt_tex_18, (void*)&rt_tex_19, (void*)&rt_tex_20, (void*)&rt_tex_21};

static DWORD __stdcall rt_cube_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_cube[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_cube[0])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_cube[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_cube_1(void* self) {   // AddRef [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_cube[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_cube[1])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_cube[1])(self);
}
static DWORD __stdcall rt_cube_2(void* self) {   // Release [R ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_cube[2])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_cube[2])(self);
    }
    ULONG c = ((ULONG(__stdcall*)(void*))g_rtO_cube[1])(self);    // temporary reference keeps it alive until the queued releases run
    for (int k = 0; k < 2; ++k) { RtRec* rr = rtAlloc(1, 0); rr->fn = g_rtO_cube[2]; rr->op = 232; rtArgs(rr)[0] = (DWORD)(ULONG_PTR)self; rtCommit(rr, 0); }
    g_rtNRelease++; return c - 2;
}
static DWORD __stdcall rt_cube_3(void* self, DWORD a0) {   // GetDevice [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[3])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[3])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[3])(self, a0);
}
static DWORD __stdcall rt_cube_4(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {   // SetPrivateData [S vvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_cube[4])(self, a0, a1, a2, a3); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_cube[4])(self, a0, a1, a2, a3);
    }
    rtSyncNote(234, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 234;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_cube[4])(self, a0, a1, a2, a3); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[234]++; return r;
}
static DWORD __stdcall rt_cube_5(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetPrivateData [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_cube[5])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_cube[5])(self, a0, a1, a2);
    }
    rtSyncNote(235, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 235;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_cube[5])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[235]++; return r;
}
static DWORD __stdcall rt_cube_6(void* self, DWORD a0) {   // FreePrivateData [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[6])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[6])(self, a0);
    }
    rtSyncNote(236, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 236;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[6])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[236]++; return r;
}
static DWORD __stdcall rt_cube_7(void* self, DWORD a0) {   // SetPriority [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[7])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[7])(self, a0);
    }
    rtSyncNote(237, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 237;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[7])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[237]++; return r;
}
static DWORD __stdcall rt_cube_8(void* self) {   // GetPriority [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_cube[8])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_cube[8])(self);
    }
    rtSyncNote(238, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 238;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_cube[8])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[238]++; return r;
}
static DWORD __stdcall rt_cube_9(void* self) {   // PreLoad [A ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_cube[9])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_cube[9])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_cube[9]; r->op = 239;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtTouch((DWORD)(ULONG_PTR)self);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_cube_10(void* self) {   // GetType [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_cube[10])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_cube[10])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_cube[10])(self);
}
static DWORD __stdcall rt_cube_11(void* self, DWORD a0) {   // SetLOD [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[11])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[11])(self, a0);
    }
    rtSyncNote(241, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 241;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[11])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[241]++; return r;
}
static DWORD __stdcall rt_cube_12(void* self) {   // GetLOD [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_cube[12])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_cube[12])(self);
    }
    rtSyncNote(242, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 242;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_cube[12])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[242]++; return r;
}
static DWORD __stdcall rt_cube_13(void* self) {   // GetLevelCount [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_cube[13])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_cube[13])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_cube[13])(self);
}
static DWORD __stdcall rt_cube_14(void* self, DWORD a0) {   // SetAutoGenFilterType [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[14])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[14])(self, a0);
    }
    rtSyncNote(244, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 244;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_cube[14])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[244]++; return r;
}
static DWORD __stdcall rt_cube_15(void* self) {   // GetAutoGenFilterType [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_cube[15])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_cube[15])(self);
    }
    rtSyncNote(245, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 245;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_cube[15])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[245]++; return r;
}
static DWORD __stdcall rt_cube_16(void* self) {   // GenerateMipSubLevels [A ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_cube[16])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_cube[16])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_cube[16]; r->op = 246;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtTouch((DWORD)(ULONG_PTR)self);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_cube_17(void* self, DWORD a0, DWORD a1) {   // GetLevelDesc [D vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_cube[17])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_cube[17])(self, a0, a1);
    }
    return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_cube[17])(self, a0, a1);
}
static DWORD __stdcall rt_cube_18(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetCubeMapSurface [D vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_cube[18])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_cube[18])(self, a0, a1, a2);
    }
    return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_cube[18])(self, a0, a1, a2);
}
static DWORD __stdcall rt_cube_19(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4) {   // LockRect [S vvvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_cube[19])(self, a0, a1, a2, a3, a4); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_cube[19])(self, a0, a1, a2, a3, a4);
    }
    rtSyncNote(249, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 249;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD, DWORD))g_rtO_cube[19])(self, a0, a1, a2, a3, a4); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[249]++; return r;
}
static DWORD __stdcall rt_cube_20(void* self, DWORD a0, DWORD a1) {   // UnlockRect [A vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_cube[20])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_cube[20])(self, a0, a1);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(3, pl); r->fn = g_rtO_cube[20]; r->op = 250;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtTouch((DWORD)(ULONG_PTR)self);
    A[1] = a0;
    A[2] = a1;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_cube_21(void* self, DWORD a0, DWORD a1) {   // AddDirtyRect [A vp16]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_cube[21])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_cube[21])(self, a0, a1);
    }
    DWORD pl = (a1 ? 16 : 0);
    RtRec* r = rtAlloc(3, pl); r->fn = g_rtO_cube[21]; r->op = 251;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtTouch((DWORD)(ULONG_PTR)self);
    A[1] = a0;
    A[2] = rtBytes(P, &po, a1, 16);
    rtCommit(r, po); return 0;
}
static void* const g_rtH_cube[22] = {(void*)&rt_cube_0, (void*)&rt_cube_1, (void*)&rt_cube_2, (void*)&rt_cube_3, (void*)&rt_cube_4, (void*)&rt_cube_5, (void*)&rt_cube_6, (void*)&rt_cube_7, (void*)&rt_cube_8, (void*)&rt_cube_9, (void*)&rt_cube_10, (void*)&rt_cube_11, (void*)&rt_cube_12, (void*)&rt_cube_13, (void*)&rt_cube_14, (void*)&rt_cube_15, (void*)&rt_cube_16, (void*)&rt_cube_17, (void*)&rt_cube_18, (void*)&rt_cube_19, (void*)&rt_cube_20, (void*)&rt_cube_21};

static DWORD __stdcall rt_vtex_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vtex[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vtex[0])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vtex[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_vtex_1(void* self) {   // AddRef [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vtex[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vtex[1])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_vtex[1])(self);
}
static DWORD __stdcall rt_vtex_2(void* self) {   // Release [R ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vtex[2])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vtex[2])(self);
    }
    ULONG c = ((ULONG(__stdcall*)(void*))g_rtO_vtex[1])(self);    // temporary reference keeps it alive until the queued releases run
    for (int k = 0; k < 2; ++k) { RtRec* rr = rtAlloc(1, 0); rr->fn = g_rtO_vtex[2]; rr->op = 262; rtArgs(rr)[0] = (DWORD)(ULONG_PTR)self; rtCommit(rr, 0); }
    g_rtNRelease++; return c - 2;
}
static DWORD __stdcall rt_vtex_3(void* self, DWORD a0) {   // GetDevice [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[3])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[3])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[3])(self, a0);
}
static DWORD __stdcall rt_vtex_4(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {   // SetPrivateData [S vvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_vtex[4])(self, a0, a1, a2, a3); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_vtex[4])(self, a0, a1, a2, a3);
    }
    rtSyncNote(264, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 264;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_vtex[4])(self, a0, a1, a2, a3); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[264]++; return r;
}
static DWORD __stdcall rt_vtex_5(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetPrivateData [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_vtex[5])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_vtex[5])(self, a0, a1, a2);
    }
    rtSyncNote(265, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 265;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_vtex[5])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[265]++; return r;
}
static DWORD __stdcall rt_vtex_6(void* self, DWORD a0) {   // FreePrivateData [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[6])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[6])(self, a0);
    }
    rtSyncNote(266, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 266;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[6])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[266]++; return r;
}
static DWORD __stdcall rt_vtex_7(void* self, DWORD a0) {   // SetPriority [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[7])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[7])(self, a0);
    }
    rtSyncNote(267, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 267;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[7])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[267]++; return r;
}
static DWORD __stdcall rt_vtex_8(void* self) {   // GetPriority [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vtex[8])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vtex[8])(self);
    }
    rtSyncNote(268, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 268;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_vtex[8])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[268]++; return r;
}
static DWORD __stdcall rt_vtex_9(void* self) {   // PreLoad [A ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vtex[9])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vtex[9])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_vtex[9]; r->op = 269;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtTouch((DWORD)(ULONG_PTR)self);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_vtex_10(void* self) {   // GetType [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vtex[10])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vtex[10])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_vtex[10])(self);
}
static DWORD __stdcall rt_vtex_11(void* self, DWORD a0) {   // SetLOD [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[11])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[11])(self, a0);
    }
    rtSyncNote(271, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 271;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[11])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[271]++; return r;
}
static DWORD __stdcall rt_vtex_12(void* self) {   // GetLOD [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vtex[12])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vtex[12])(self);
    }
    rtSyncNote(272, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 272;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_vtex[12])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[272]++; return r;
}
static DWORD __stdcall rt_vtex_13(void* self) {   // GetLevelCount [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vtex[13])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vtex[13])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_vtex[13])(self);
}
static DWORD __stdcall rt_vtex_14(void* self, DWORD a0) {   // SetAutoGenFilterType [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[14])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[14])(self, a0);
    }
    rtSyncNote(274, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 274;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[14])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[274]++; return r;
}
static DWORD __stdcall rt_vtex_15(void* self) {   // GetAutoGenFilterType [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vtex[15])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vtex[15])(self);
    }
    rtSyncNote(275, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 275;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_vtex[15])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[275]++; return r;
}
static DWORD __stdcall rt_vtex_16(void* self) {   // GenerateMipSubLevels [A ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vtex[16])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vtex[16])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_vtex[16]; r->op = 276;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtTouch((DWORD)(ULONG_PTR)self);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_vtex_17(void* self, DWORD a0, DWORD a1) {   // GetLevelDesc [D vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vtex[17])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vtex[17])(self, a0, a1);
    }
    return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vtex[17])(self, a0, a1);
}
static DWORD __stdcall rt_vtex_18(void* self, DWORD a0, DWORD a1) {   // GetVolumeLevel [D vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vtex[18])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vtex[18])(self, a0, a1);
    }
    return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vtex[18])(self, a0, a1);
}
static DWORD __stdcall rt_vtex_19(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {   // LockBox [S vvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_vtex[19])(self, a0, a1, a2, a3); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_vtex[19])(self, a0, a1, a2, a3);
    }
    rtSyncNote(279, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 279;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_vtex[19])(self, a0, a1, a2, a3); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[279]++; return r;
}
static DWORD __stdcall rt_vtex_20(void* self, DWORD a0) {   // UnlockBox [A v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[20])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[20])(self, a0);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_vtex[20]; r->op = 280;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtTouch((DWORD)(ULONG_PTR)self);
    A[1] = a0;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_vtex_21(void* self, DWORD a0) {   // AddDirtyBox [A p24]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[21])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vtex[21])(self, a0);
    }
    DWORD pl = (a0 ? 24 : 0);
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_vtex[21]; r->op = 281;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtTouch((DWORD)(ULONG_PTR)self);
    A[1] = rtBytes(P, &po, a0, 24);
    rtCommit(r, po); return 0;
}
static void* const g_rtH_vtex[22] = {(void*)&rt_vtex_0, (void*)&rt_vtex_1, (void*)&rt_vtex_2, (void*)&rt_vtex_3, (void*)&rt_vtex_4, (void*)&rt_vtex_5, (void*)&rt_vtex_6, (void*)&rt_vtex_7, (void*)&rt_vtex_8, (void*)&rt_vtex_9, (void*)&rt_vtex_10, (void*)&rt_vtex_11, (void*)&rt_vtex_12, (void*)&rt_vtex_13, (void*)&rt_vtex_14, (void*)&rt_vtex_15, (void*)&rt_vtex_16, (void*)&rt_vtex_17, (void*)&rt_vtex_18, (void*)&rt_vtex_19, (void*)&rt_vtex_20, (void*)&rt_vtex_21};

static DWORD __stdcall rt_surf_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_surf[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_surf[0])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_surf[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_surf_1(void* self) {   // AddRef [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_surf[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_surf[1])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_surf[1])(self);
}
static DWORD __stdcall rt_surf_2(void* self) {   // Release [R ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_surf[2])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_surf[2])(self);
    }
    ULONG c = ((ULONG(__stdcall*)(void*))g_rtO_surf[1])(self);    // temporary reference keeps it alive until the queued releases run
    for (int k = 0; k < 2; ++k) { RtRec* rr = rtAlloc(1, 0); rr->fn = g_rtO_surf[2]; rr->op = 292; rtArgs(rr)[0] = (DWORD)(ULONG_PTR)self; rtCommit(rr, 0); }
    g_rtNRelease++; return c - 2;
}
static DWORD __stdcall rt_surf_3(void* self, DWORD a0) {   // GetDevice [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[3])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[3])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[3])(self, a0);
}
static DWORD __stdcall rt_surf_4(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {   // SetPrivateData [S vvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_surf[4])(self, a0, a1, a2, a3); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_surf[4])(self, a0, a1, a2, a3);
    }
    rtSyncNote(294, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 294;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_surf[4])(self, a0, a1, a2, a3); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[294]++; return r;
}
static DWORD __stdcall rt_surf_5(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetPrivateData [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_surf[5])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_surf[5])(self, a0, a1, a2);
    }
    rtSyncNote(295, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 295;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_surf[5])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[295]++; return r;
}
static DWORD __stdcall rt_surf_6(void* self, DWORD a0) {   // FreePrivateData [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[6])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[6])(self, a0);
    }
    rtSyncNote(296, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 296;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[6])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[296]++; return r;
}
static DWORD __stdcall rt_surf_7(void* self, DWORD a0) {   // SetPriority [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[7])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[7])(self, a0);
    }
    rtSyncNote(297, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 297;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[7])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[297]++; return r;
}
static DWORD __stdcall rt_surf_8(void* self) {   // GetPriority [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_surf[8])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_surf[8])(self);
    }
    rtSyncNote(298, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 298;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_surf[8])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[298]++; return r;
}
static DWORD __stdcall rt_surf_9(void* self) {   // PreLoad [A ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_surf[9])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_surf[9])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_surf[9]; r->op = 299;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtTouch((DWORD)(ULONG_PTR)self);
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_surf_10(void* self) {   // GetType [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_surf[10])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_surf[10])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_surf[10])(self);
}
static DWORD __stdcall rt_surf_11(void* self, DWORD a0, DWORD a1) {   // GetContainer [D vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_surf[11])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_surf[11])(self, a0, a1);
    }
    return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_surf[11])(self, a0, a1);
}
static DWORD __stdcall rt_surf_12(void* self, DWORD a0) {   // GetDesc [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[12])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[12])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[12])(self, a0);
}
static DWORD __stdcall rt_surf_13(void* self, DWORD a0, DWORD a1, DWORD a2);   // LockRect (hand-written)
static DWORD __stdcall rt_surf_14(void* self);   // UnlockRect (hand-written)
static DWORD __stdcall rt_surf_15(void* self, DWORD a0) {   // GetDC [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[15])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[15])(self, a0);
    }
    rtSyncNote(305, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 305;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[15])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[305]++; return r;
}
static DWORD __stdcall rt_surf_16(void* self, DWORD a0) {   // ReleaseDC [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[16])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[16])(self, a0);
    }
    rtSyncNote(306, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 306;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_surf[16])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[306]++; return r;
}
static void* const g_rtH_surf[17] = {(void*)&rt_surf_0, (void*)&rt_surf_1, (void*)&rt_surf_2, (void*)&rt_surf_3, (void*)&rt_surf_4, (void*)&rt_surf_5, (void*)&rt_surf_6, (void*)&rt_surf_7, (void*)&rt_surf_8, (void*)&rt_surf_9, (void*)&rt_surf_10, (void*)&rt_surf_11, (void*)&rt_surf_12, (void*)&rt_surf_13, (void*)&rt_surf_14, (void*)&rt_surf_15, (void*)&rt_surf_16};

static DWORD __stdcall rt_vol_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vol[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vol[0])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vol[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_vol_1(void* self) {   // AddRef [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vol[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vol[1])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_vol[1])(self);
}
static DWORD __stdcall rt_vol_2(void* self) {   // Release [R ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vol[2])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vol[2])(self);
    }
    ULONG c = ((ULONG(__stdcall*)(void*))g_rtO_vol[1])(self);    // temporary reference keeps it alive until the queued releases run
    for (int k = 0; k < 2; ++k) { RtRec* rr = rtAlloc(1, 0); rr->fn = g_rtO_vol[2]; rr->op = 312; rtArgs(rr)[0] = (DWORD)(ULONG_PTR)self; rtCommit(rr, 0); }
    g_rtNRelease++; return c - 2;
}
static DWORD __stdcall rt_vol_3(void* self, DWORD a0) {   // GetDevice [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vol[3])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vol[3])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vol[3])(self, a0);
}
static DWORD __stdcall rt_vol_4(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {   // SetPrivateData [S vvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_vol[4])(self, a0, a1, a2, a3); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_vol[4])(self, a0, a1, a2, a3);
    }
    rtSyncNote(314, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 314;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_vol[4])(self, a0, a1, a2, a3); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[314]++; return r;
}
static DWORD __stdcall rt_vol_5(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetPrivateData [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_vol[5])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_vol[5])(self, a0, a1, a2);
    }
    rtSyncNote(315, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 315;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_vol[5])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[315]++; return r;
}
static DWORD __stdcall rt_vol_6(void* self, DWORD a0) {   // FreePrivateData [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vol[6])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vol[6])(self, a0);
    }
    rtSyncNote(316, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 316;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vol[6])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[316]++; return r;
}
static DWORD __stdcall rt_vol_7(void* self, DWORD a0, DWORD a1) {   // GetContainer [D vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vol[7])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vol[7])(self, a0, a1);
    }
    return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vol[7])(self, a0, a1);
}
static DWORD __stdcall rt_vol_8(void* self, DWORD a0) {   // GetDesc [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vol[8])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vol[8])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vol[8])(self, a0);
}
static DWORD __stdcall rt_vol_9(void* self, DWORD a0, DWORD a1, DWORD a2) {   // LockBox [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_vol[9])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_vol[9])(self, a0, a1, a2);
    }
    rtSyncNote(319, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 319;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_vol[9])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[319]++; return r;
}
static DWORD __stdcall rt_vol_10(void* self) {   // UnlockBox [A ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vol[10])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vol[10])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_vol[10]; r->op = 320;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtTouch((DWORD)(ULONG_PTR)self);
    rtCommit(r, po); return 0;
}
static void* const g_rtH_vol[11] = {(void*)&rt_vol_0, (void*)&rt_vol_1, (void*)&rt_vol_2, (void*)&rt_vol_3, (void*)&rt_vol_4, (void*)&rt_vol_5, (void*)&rt_vol_6, (void*)&rt_vol_7, (void*)&rt_vol_8, (void*)&rt_vol_9, (void*)&rt_vol_10};

static DWORD __stdcall rt_vb_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vb[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vb[0])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vb[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_vb_1(void* self) {   // AddRef [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vb[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vb[1])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_vb[1])(self);
}
static DWORD __stdcall rt_vb_2(void* self) {   // Release [R ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vb[2])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vb[2])(self);
    }
    ULONG c = ((ULONG(__stdcall*)(void*))g_rtO_vb[1])(self);    // temporary reference keeps it alive until the queued releases run
    for (int k = 0; k < 2; ++k) { RtRec* rr = rtAlloc(1, 0); rr->fn = g_rtO_vb[2]; rr->op = 332; rtArgs(rr)[0] = (DWORD)(ULONG_PTR)self; rtCommit(rr, 0); }
    g_rtNRelease++; return c - 2;
}
static DWORD __stdcall rt_vb_3(void* self, DWORD a0) {   // GetDevice [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vb[3])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vb[3])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vb[3])(self, a0);
}
static DWORD __stdcall rt_vb_4(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {   // SetPrivateData [S vvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_vb[4])(self, a0, a1, a2, a3); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_vb[4])(self, a0, a1, a2, a3);
    }
    rtSyncNote(334, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 334;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_vb[4])(self, a0, a1, a2, a3); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[334]++; return r;
}
static DWORD __stdcall rt_vb_5(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetPrivateData [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_vb[5])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_vb[5])(self, a0, a1, a2);
    }
    rtSyncNote(335, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 335;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_vb[5])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[335]++; return r;
}
static DWORD __stdcall rt_vb_6(void* self, DWORD a0) {   // FreePrivateData [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vb[6])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vb[6])(self, a0);
    }
    rtSyncNote(336, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 336;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vb[6])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[336]++; return r;
}
static DWORD __stdcall rt_vb_7(void* self, DWORD a0) {   // SetPriority [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vb[7])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vb[7])(self, a0);
    }
    rtSyncNote(337, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 337;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vb[7])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[337]++; return r;
}
static DWORD __stdcall rt_vb_8(void* self) {   // GetPriority [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vb[8])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vb[8])(self);
    }
    rtSyncNote(338, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 338;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_vb[8])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[338]++; return r;
}
static DWORD __stdcall rt_vb_9(void* self) {   // PreLoad [A ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vb[9])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vb[9])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_vb[9]; r->op = 339;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_vb_10(void* self) {   // GetType [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vb[10])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vb[10])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_vb[10])(self);
}
static DWORD __stdcall rt_vb_11(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3);   // Lock (hand-written)
static DWORD __stdcall rt_vb_12(void* self);   // Unlock (hand-written)
static DWORD __stdcall rt_vb_13(void* self, DWORD a0) {   // GetDesc [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vb[13])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vb[13])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vb[13])(self, a0);
}
static void* const g_rtH_vb[14] = {(void*)&rt_vb_0, (void*)&rt_vb_1, (void*)&rt_vb_2, (void*)&rt_vb_3, (void*)&rt_vb_4, (void*)&rt_vb_5, (void*)&rt_vb_6, (void*)&rt_vb_7, (void*)&rt_vb_8, (void*)&rt_vb_9, (void*)&rt_vb_10, (void*)&rt_vb_11, (void*)&rt_vb_12, (void*)&rt_vb_13};

static DWORD __stdcall rt_ib_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_ib[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_ib[0])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_ib[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_ib_1(void* self) {   // AddRef [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_ib[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_ib[1])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_ib[1])(self);
}
static DWORD __stdcall rt_ib_2(void* self) {   // Release [R ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_ib[2])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_ib[2])(self);
    }
    ULONG c = ((ULONG(__stdcall*)(void*))g_rtO_ib[1])(self);    // temporary reference keeps it alive until the queued releases run
    for (int k = 0; k < 2; ++k) { RtRec* rr = rtAlloc(1, 0); rr->fn = g_rtO_ib[2]; rr->op = 352; rtArgs(rr)[0] = (DWORD)(ULONG_PTR)self; rtCommit(rr, 0); }
    g_rtNRelease++; return c - 2;
}
static DWORD __stdcall rt_ib_3(void* self, DWORD a0) {   // GetDevice [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ib[3])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ib[3])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ib[3])(self, a0);
}
static DWORD __stdcall rt_ib_4(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3) {   // SetPrivateData [S vvvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_ib[4])(self, a0, a1, a2, a3); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_ib[4])(self, a0, a1, a2, a3);
    }
    rtSyncNote(354, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 354;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD, DWORD))g_rtO_ib[4])(self, a0, a1, a2, a3); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[354]++; return r;
}
static DWORD __stdcall rt_ib_5(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetPrivateData [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_ib[5])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_ib[5])(self, a0, a1, a2);
    }
    rtSyncNote(355, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 355;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_ib[5])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[355]++; return r;
}
static DWORD __stdcall rt_ib_6(void* self, DWORD a0) {   // FreePrivateData [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ib[6])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ib[6])(self, a0);
    }
    rtSyncNote(356, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 356;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ib[6])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[356]++; return r;
}
static DWORD __stdcall rt_ib_7(void* self, DWORD a0) {   // SetPriority [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ib[7])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ib[7])(self, a0);
    }
    rtSyncNote(357, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 357;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ib[7])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[357]++; return r;
}
static DWORD __stdcall rt_ib_8(void* self) {   // GetPriority [S ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_ib[8])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_ib[8])(self);
    }
    rtSyncNote(358, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 358;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*))g_rtO_ib[8])(self); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[358]++; return r;
}
static DWORD __stdcall rt_ib_9(void* self) {   // PreLoad [A ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_ib[9])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_ib[9])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_ib[9]; r->op = 359;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_ib_10(void* self) {   // GetType [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_ib[10])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_ib[10])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_ib[10])(self);
}
static DWORD __stdcall rt_ib_11(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3);   // Lock (hand-written)
static DWORD __stdcall rt_ib_12(void* self);   // Unlock (hand-written)
static DWORD __stdcall rt_ib_13(void* self, DWORD a0) {   // GetDesc [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ib[13])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ib[13])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ib[13])(self, a0);
}
static void* const g_rtH_ib[14] = {(void*)&rt_ib_0, (void*)&rt_ib_1, (void*)&rt_ib_2, (void*)&rt_ib_3, (void*)&rt_ib_4, (void*)&rt_ib_5, (void*)&rt_ib_6, (void*)&rt_ib_7, (void*)&rt_ib_8, (void*)&rt_ib_9, (void*)&rt_ib_10, (void*)&rt_ib_11, (void*)&rt_ib_12, (void*)&rt_ib_13};

static DWORD __stdcall rt_sb_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_sb[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_sb[0])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_sb[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_sb_1(void* self) {   // AddRef [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_sb[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_sb[1])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_sb[1])(self);
}
static DWORD __stdcall rt_sb_2(void* self) {   // Release [R ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_sb[2])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_sb[2])(self);
    }
    ULONG c = ((ULONG(__stdcall*)(void*))g_rtO_sb[1])(self);    // temporary reference keeps it alive until the queued releases run
    for (int k = 0; k < 2; ++k) { RtRec* rr = rtAlloc(1, 0); rr->fn = g_rtO_sb[2]; rr->op = 372; rtArgs(rr)[0] = (DWORD)(ULONG_PTR)self; rtCommit(rr, 0); }
    g_rtNRelease++; return c - 2;
}
static DWORD __stdcall rt_sb_3(void* self, DWORD a0) {   // GetDevice [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sb[3])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sb[3])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sb[3])(self, a0);
}
static DWORD __stdcall rt_sb_4(void* self) {   // Capture [A ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_sb[4])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_sb[4])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_sb[4]; r->op = 374;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_sb_5(void* self) {   // Apply [A ]
    rtDsInvalAll();
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_sb[5])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_sb[5])(self);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(1, pl); r->fn = g_rtO_sb[5]; r->op = 375;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    rtCommit(r, po); return 0;
}
static void* const g_rtH_sb[6] = {(void*)&rt_sb_0, (void*)&rt_sb_1, (void*)&rt_sb_2, (void*)&rt_sb_3, (void*)&rt_sb_4, (void*)&rt_sb_5};

static DWORD __stdcall rt_q_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_q[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_q[0])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_q[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_q_1(void* self) {   // AddRef [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_q[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_q[1])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_q[1])(self);
}
static DWORD __stdcall rt_q_2(void* self) {   // Release [R ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_q[2])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_q[2])(self);
    }
    ULONG c = ((ULONG(__stdcall*)(void*))g_rtO_q[1])(self);    // temporary reference keeps it alive until the queued releases run
    for (int k = 0; k < 2; ++k) { RtRec* rr = rtAlloc(1, 0); rr->fn = g_rtO_q[2]; rr->op = 382; rtArgs(rr)[0] = (DWORD)(ULONG_PTR)self; rtCommit(rr, 0); }
    g_rtNRelease++; return c - 2;
}
static DWORD __stdcall rt_q_3(void* self, DWORD a0) {   // GetDevice [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_q[3])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_q[3])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_q[3])(self, a0);
}
static DWORD __stdcall rt_q_4(void* self) {   // GetType [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_q[4])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_q[4])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_q[4])(self);
}
static DWORD __stdcall rt_q_5(void* self) {   // GetDataSize [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_q[5])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_q[5])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_q[5])(self);
}
static DWORD __stdcall rt_q_6(void* self, DWORD a0) {   // Issue [A v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_q[6])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_q[6])(self, a0);
    }
    DWORD pl = 0;
    RtRec* r = rtAlloc(2, pl); r->fn = g_rtO_q[6]; r->op = 386;
    DWORD* A = rtArgs(r); BYTE* P = rtPayload(r); DWORD po = 0; (void)P; (void)po;
    A[0] = (DWORD)(ULONG_PTR)self;
    A[1] = a0;
    rtCommit(r, po); return 0;
}
static DWORD __stdcall rt_q_7(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetData [S vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_q[7])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_q[7])(self, a0, a1, a2);
    }
    rtSyncNote(387, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 387;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_q[7])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[387]++; return r;
}
static void* const g_rtH_q[8] = {(void*)&rt_q_0, (void*)&rt_q_1, (void*)&rt_q_2, (void*)&rt_q_3, (void*)&rt_q_4, (void*)&rt_q_5, (void*)&rt_q_6, (void*)&rt_q_7};

static DWORD __stdcall rt_sc_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_sc[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_sc[0])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_sc[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_sc_1(void* self) {   // AddRef [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_sc[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_sc[1])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_sc[1])(self);
}
static DWORD __stdcall rt_sc_2(void* self) {   // Release [R ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_sc[2])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_sc[2])(self);
    }
    ULONG c = ((ULONG(__stdcall*)(void*))g_rtO_sc[1])(self);    // temporary reference keeps it alive until the queued releases run
    for (int k = 0; k < 2; ++k) { RtRec* rr = rtAlloc(1, 0); rr->fn = g_rtO_sc[2]; rr->op = 392; rtArgs(rr)[0] = (DWORD)(ULONG_PTR)self; rtCommit(rr, 0); }
    g_rtNRelease++; return c - 2;
}
static DWORD __stdcall rt_sc_3(void* self, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4);   // Present (hand-written)
static DWORD __stdcall rt_sc_4(void* self, DWORD a0) {   // GetFrontBufferData [S v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[4])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[4])(self, a0);
    }
    rtSyncNote(394, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 394;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[4])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[394]++; return r;
}
static DWORD __stdcall rt_sc_5(void* self, DWORD a0, DWORD a1, DWORD a2) {   // GetBackBuffer [L vvv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_sc[5])(self, a0, a1, a2); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_sc[5])(self, a0, a1, a2);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD, DWORD))g_rtO_sc[5])(self, a0, a1, a2); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_sc_6(void* self, DWORD a0) {   // GetRasterStatus [L v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[6])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[6])(self, a0);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[6])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_sc_7(void* self, DWORD a0) {   // GetDisplayMode [L v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[7])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[7])(self, a0);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[7])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_sc_8(void* self, DWORD a0) {   // GetDevice [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[8])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[8])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[8])(self, a0);
}
static DWORD __stdcall rt_sc_9(void* self, DWORD a0) {   // GetPresentParameters [L v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[9])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[9])(self, a0);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_sc[9])(self, a0); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static void* const g_rtH_sc[10] = {(void*)&rt_sc_0, (void*)&rt_sc_1, (void*)&rt_sc_2, (void*)&rt_sc_3, (void*)&rt_sc_4, (void*)&rt_sc_5, (void*)&rt_sc_6, (void*)&rt_sc_7, (void*)&rt_sc_8, (void*)&rt_sc_9};

static DWORD __stdcall rt_vs_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vs[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vs[0])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vs[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_vs_1(void* self) {   // AddRef [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vs[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vs[1])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_vs[1])(self);
}
static DWORD __stdcall rt_vs_2(void* self) {   // Release [R ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_vs[2])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_vs[2])(self);
    }
    ULONG c = ((ULONG(__stdcall*)(void*))g_rtO_vs[1])(self);    // temporary reference keeps it alive until the queued releases run
    for (int k = 0; k < 2; ++k) { RtRec* rr = rtAlloc(1, 0); rr->fn = g_rtO_vs[2]; rr->op = 402; rtArgs(rr)[0] = (DWORD)(ULONG_PTR)self; rtCommit(rr, 0); }
    g_rtNRelease++; return c - 2;
}
static DWORD __stdcall rt_vs_3(void* self, DWORD a0) {   // GetDevice [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vs[3])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vs[3])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_vs[3])(self, a0);
}
static DWORD __stdcall rt_vs_4(void* self, DWORD a0, DWORD a1) {   // GetFunction [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vs[4])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vs[4])(self, a0, a1);
    }
    rtSyncNote(404, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 404;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_vs[4])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[404]++; return r;
}
static void* const g_rtH_vs[5] = {(void*)&rt_vs_0, (void*)&rt_vs_1, (void*)&rt_vs_2, (void*)&rt_vs_3, (void*)&rt_vs_4};

static DWORD __stdcall rt_ps_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_ps[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_ps[0])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_ps[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_ps_1(void* self) {   // AddRef [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_ps[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_ps[1])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_ps[1])(self);
}
static DWORD __stdcall rt_ps_2(void* self) {   // Release [R ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_ps[2])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_ps[2])(self);
    }
    ULONG c = ((ULONG(__stdcall*)(void*))g_rtO_ps[1])(self);    // temporary reference keeps it alive until the queued releases run
    for (int k = 0; k < 2; ++k) { RtRec* rr = rtAlloc(1, 0); rr->fn = g_rtO_ps[2]; rr->op = 412; rtArgs(rr)[0] = (DWORD)(ULONG_PTR)self; rtCommit(rr, 0); }
    g_rtNRelease++; return c - 2;
}
static DWORD __stdcall rt_ps_3(void* self, DWORD a0) {   // GetDevice [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ps[3])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ps[3])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_ps[3])(self, a0);
}
static DWORD __stdcall rt_ps_4(void* self, DWORD a0, DWORD a1) {   // GetFunction [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_ps[4])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_ps[4])(self, a0, a1);
    }
    rtSyncNote(414, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 414;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_ps[4])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[414]++; return r;
}
static void* const g_rtH_ps[5] = {(void*)&rt_ps_0, (void*)&rt_ps_1, (void*)&rt_ps_2, (void*)&rt_ps_3, (void*)&rt_ps_4};

static DWORD __stdcall rt_decl_0(void* self, DWORD a0, DWORD a1) {   // QueryInterface [L vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_decl[0])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_decl[0])(self, a0, a1);
    }
    rtExecLock(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_decl[0])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNLocked++; return r;
}
static DWORD __stdcall rt_decl_1(void* self) {   // AddRef [D ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_decl[1])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_decl[1])(self);
    }
    return ((DWORD(__stdcall*)(void*))g_rtO_decl[1])(self);
}
static DWORD __stdcall rt_decl_2(void* self) {   // Release [R ]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*))g_rtO_decl[2])(self); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*))g_rtO_decl[2])(self);
    }
    ULONG c = ((ULONG(__stdcall*)(void*))g_rtO_decl[1])(self);    // temporary reference keeps it alive until the queued releases run
    for (int k = 0; k < 2; ++k) { RtRec* rr = rtAlloc(1, 0); rr->fn = g_rtO_decl[2]; rr->op = 422; rtArgs(rr)[0] = (DWORD)(ULONG_PTR)self; rtCommit(rr, 0); }
    g_rtNRelease++; return c - 2;
}
static DWORD __stdcall rt_decl_3(void* self, DWORD a0) {   // GetDevice [D v]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD))g_rtO_decl[3])(self, a0); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_decl[3])(self, a0);
    }
    return ((DWORD(__stdcall*)(void*, DWORD))g_rtO_decl[3])(self, a0);
}
static DWORD __stdcall rt_decl_4(void* self, DWORD a0, DWORD a1) {   // GetDeclaration [S vv]
    DWORD tid = __readfsdword(0x24);
    if (tid != g_rtMainTid || !g_rtActive || g_rtDirectScope) {
        if (g_rtActive && tid != g_rtWorkerTid && tid != g_rtMainTid) { rtEnterExec(); DWORD r_ = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_decl[4])(self, a0, a1); LeaveCriticalSection(&g_rtExecCs); InterlockedIncrement(&g_rtNForeign); return r_; }
        return ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_decl[4])(self, a0, a1);
    }
    rtSyncNote(424, (DWORD)(ULONG_PTR)_ReturnAddress()); g_rtCurOp = 424;
    rtDrain(); rtEnterExec(); g_rtDirectScope++; DWORD r = ((DWORD(__stdcall*)(void*, DWORD, DWORD))g_rtO_decl[4])(self, a0, a1); g_rtDirectScope--; LeaveCriticalSection(&g_rtExecCs);
    g_rtNSync++; g_rtSyncHist[424]++; return r;
}
static void* const g_rtH_decl[5] = {(void*)&rt_decl_0, (void*)&rt_decl_1, (void*)&rt_decl_2, (void*)&rt_decl_3, (void*)&rt_decl_4};

static const char* rtOpName(int op) {
    switch (op) {
    case 0: return "dev.QueryInterface";
    case 1: return "dev.AddRef";
    case 2: return "dev.Release";
    case 3: return "dev.TestCooperativeLevel";
    case 4: return "dev.GetAvailableTextureMem";
    case 5: return "dev.EvictManagedResources";
    case 6: return "dev.GetDirect3D";
    case 7: return "dev.GetDeviceCaps";
    case 8: return "dev.GetDisplayMode";
    case 9: return "dev.GetCreationParameters";
    case 10: return "dev.SetCursorProperties";
    case 11: return "dev.SetCursorPosition";
    case 12: return "dev.ShowCursor";
    case 13: return "dev.CreateAdditionalSwapChain";
    case 14: return "dev.GetSwapChain";
    case 15: return "dev.GetNumberOfSwapChains";
    case 16: return "dev.Reset";
    case 17: return "dev.Present";
    case 18: return "dev.GetBackBuffer";
    case 19: return "dev.GetRasterStatus";
    case 20: return "dev.SetDialogBoxMode";
    case 21: return "dev.SetGammaRamp";
    case 22: return "dev.GetGammaRamp";
    case 23: return "dev.CreateTexture";
    case 24: return "dev.CreateVolumeTexture";
    case 25: return "dev.CreateCubeTexture";
    case 26: return "dev.CreateVertexBuffer";
    case 27: return "dev.CreateIndexBuffer";
    case 28: return "dev.CreateRenderTarget";
    case 29: return "dev.CreateDepthStencilSurface";
    case 30: return "dev.UpdateSurface";
    case 31: return "dev.UpdateTexture";
    case 32: return "dev.GetRenderTargetData";
    case 33: return "dev.GetFrontBufferData";
    case 34: return "dev.StretchRect";
    case 35: return "dev.ColorFill";
    case 36: return "dev.CreateOffscreenPlainSurface";
    case 37: return "dev.SetRenderTarget";
    case 38: return "dev.GetRenderTarget";
    case 39: return "dev.SetDepthStencilSurface";
    case 40: return "dev.GetDepthStencilSurface";
    case 41: return "dev.BeginScene";
    case 42: return "dev.EndScene";
    case 43: return "dev.Clear";
    case 44: return "dev.SetTransform";
    case 45: return "dev.GetTransform";
    case 46: return "dev.MultiplyTransform";
    case 47: return "dev.SetViewport";
    case 48: return "dev.GetViewport";
    case 49: return "dev.SetMaterial";
    case 50: return "dev.GetMaterial";
    case 51: return "dev.SetLight";
    case 52: return "dev.GetLight";
    case 53: return "dev.LightEnable";
    case 54: return "dev.GetLightEnable";
    case 55: return "dev.SetClipPlane";
    case 56: return "dev.GetClipPlane";
    case 57: return "dev.SetRenderState";
    case 58: return "dev.GetRenderState";
    case 59: return "dev.CreateStateBlock";
    case 60: return "dev.BeginStateBlock";
    case 61: return "dev.EndStateBlock";
    case 62: return "dev.SetClipStatus";
    case 63: return "dev.GetClipStatus";
    case 64: return "dev.GetTexture";
    case 65: return "dev.SetTexture";
    case 66: return "dev.GetTextureStageState";
    case 67: return "dev.SetTextureStageState";
    case 68: return "dev.GetSamplerState";
    case 69: return "dev.SetSamplerState";
    case 70: return "dev.ValidateDevice";
    case 71: return "dev.SetPaletteEntries";
    case 72: return "dev.GetPaletteEntries";
    case 73: return "dev.SetCurrentTexturePalette";
    case 74: return "dev.GetCurrentTexturePalette";
    case 75: return "dev.SetScissorRect";
    case 76: return "dev.GetScissorRect";
    case 77: return "dev.SetSoftwareVertexProcessing";
    case 78: return "dev.GetSoftwareVertexProcessing";
    case 79: return "dev.SetNPatchMode";
    case 80: return "dev.GetNPatchMode";
    case 81: return "dev.DrawPrimitive";
    case 82: return "dev.DrawIndexedPrimitive";
    case 83: return "dev.DrawPrimitiveUP";
    case 84: return "dev.DrawIndexedPrimitiveUP";
    case 85: return "dev.ProcessVertices";
    case 86: return "dev.CreateVertexDeclaration";
    case 87: return "dev.SetVertexDeclaration";
    case 88: return "dev.GetVertexDeclaration";
    case 89: return "dev.SetFVF";
    case 90: return "dev.GetFVF";
    case 91: return "dev.CreateVertexShader";
    case 92: return "dev.SetVertexShader";
    case 93: return "dev.GetVertexShader";
    case 94: return "dev.SetVertexShaderConstantF";
    case 95: return "dev.GetVertexShaderConstantF";
    case 96: return "dev.SetVertexShaderConstantI";
    case 97: return "dev.GetVertexShaderConstantI";
    case 98: return "dev.SetVertexShaderConstantB";
    case 99: return "dev.GetVertexShaderConstantB";
    case 100: return "dev.SetStreamSource";
    case 101: return "dev.GetStreamSource";
    case 102: return "dev.SetStreamSourceFreq";
    case 103: return "dev.GetStreamSourceFreq";
    case 104: return "dev.SetIndices";
    case 105: return "dev.GetIndices";
    case 106: return "dev.CreatePixelShader";
    case 107: return "dev.SetPixelShader";
    case 108: return "dev.GetPixelShader";
    case 109: return "dev.SetPixelShaderConstantF";
    case 110: return "dev.GetPixelShaderConstantF";
    case 111: return "dev.SetPixelShaderConstantI";
    case 112: return "dev.GetPixelShaderConstantI";
    case 113: return "dev.SetPixelShaderConstantB";
    case 114: return "dev.GetPixelShaderConstantB";
    case 115: return "dev.DrawRectPatch";
    case 116: return "dev.DrawTriPatch";
    case 117: return "dev.DeletePatch";
    case 118: return "dev.CreateQuery";
    case 120: return "fx.QueryInterface";
    case 121: return "fx.AddRef";
    case 122: return "fx.Release";
    case 123: return "fx.GetDesc";
    case 124: return "fx.GetParameterDesc";
    case 125: return "fx.GetTechniqueDesc";
    case 126: return "fx.GetPassDesc";
    case 127: return "fx.GetFunctionDesc";
    case 128: return "fx.GetParameter";
    case 129: return "fx.GetParameterByName";
    case 130: return "fx.GetParameterBySemantic";
    case 131: return "fx.GetParameterElement";
    case 132: return "fx.GetTechnique";
    case 133: return "fx.GetTechniqueByName";
    case 134: return "fx.GetPass";
    case 135: return "fx.GetPassByName";
    case 136: return "fx.GetFunction";
    case 137: return "fx.GetFunctionByName";
    case 138: return "fx.GetAnnotation";
    case 139: return "fx.GetAnnotationByName";
    case 140: return "fx.SetValue";
    case 141: return "fx.GetValue";
    case 142: return "fx.SetBool";
    case 143: return "fx.GetBool";
    case 144: return "fx.SetBoolArray";
    case 145: return "fx.GetBoolArray";
    case 146: return "fx.SetInt";
    case 147: return "fx.GetInt";
    case 148: return "fx.SetIntArray";
    case 149: return "fx.GetIntArray";
    case 150: return "fx.SetFloat";
    case 151: return "fx.GetFloat";
    case 152: return "fx.SetFloatArray";
    case 153: return "fx.GetFloatArray";
    case 154: return "fx.SetVector";
    case 155: return "fx.GetVector";
    case 156: return "fx.SetVectorArray";
    case 157: return "fx.GetVectorArray";
    case 158: return "fx.SetMatrix";
    case 159: return "fx.GetMatrix";
    case 160: return "fx.SetMatrixArray";
    case 161: return "fx.GetMatrixArray";
    case 162: return "fx.SetMatrixPointerArray";
    case 163: return "fx.GetMatrixPointerArray";
    case 164: return "fx.SetMatrixTranspose";
    case 165: return "fx.GetMatrixTranspose";
    case 166: return "fx.SetMatrixTransposeArray";
    case 167: return "fx.GetMatrixTransposeArray";
    case 168: return "fx.SetMatrixTransposePointerArray";
    case 169: return "fx.GetMatrixTransposePointerArray";
    case 170: return "fx.SetString";
    case 171: return "fx.GetString";
    case 172: return "fx.SetTexture";
    case 173: return "fx.GetTexture";
    case 174: return "fx.GetPixelShader";
    case 175: return "fx.GetVertexShader";
    case 176: return "fx.SetArrayRange";
    case 177: return "fx.GetPool";
    case 178: return "fx.SetTechnique";
    case 179: return "fx.GetCurrentTechnique";
    case 180: return "fx.ValidateTechnique";
    case 181: return "fx.FindNextValidTechnique";
    case 182: return "fx.IsParameterUsed";
    case 183: return "fx.Begin";
    case 184: return "fx.BeginPass";
    case 185: return "fx.CommitChanges";
    case 186: return "fx.EndPass";
    case 187: return "fx.End";
    case 188: return "fx.GetDevice";
    case 189: return "fx.OnLostDevice";
    case 190: return "fx.OnResetDevice";
    case 191: return "fx.SetStateManager";
    case 192: return "fx.GetStateManager";
    case 193: return "fx.BeginParameterBlock";
    case 194: return "fx.EndParameterBlock";
    case 195: return "fx.ApplyParameterBlock";
    case 196: return "fx.DeleteParameterBlock";
    case 197: return "fx.CloneEffect";
    case 198: return "fx.SetRawValue";
    case 200: return "tex.QueryInterface";
    case 201: return "tex.AddRef";
    case 202: return "tex.Release";
    case 203: return "tex.GetDevice";
    case 204: return "tex.SetPrivateData";
    case 205: return "tex.GetPrivateData";
    case 206: return "tex.FreePrivateData";
    case 207: return "tex.SetPriority";
    case 208: return "tex.GetPriority";
    case 209: return "tex.PreLoad";
    case 210: return "tex.GetType";
    case 211: return "tex.SetLOD";
    case 212: return "tex.GetLOD";
    case 213: return "tex.GetLevelCount";
    case 214: return "tex.SetAutoGenFilterType";
    case 215: return "tex.GetAutoGenFilterType";
    case 216: return "tex.GenerateMipSubLevels";
    case 217: return "tex.GetLevelDesc";
    case 218: return "tex.GetSurfaceLevel";
    case 219: return "tex.LockRect";
    case 220: return "tex.UnlockRect";
    case 221: return "tex.AddDirtyRect";
    case 230: return "cube.QueryInterface";
    case 231: return "cube.AddRef";
    case 232: return "cube.Release";
    case 233: return "cube.GetDevice";
    case 234: return "cube.SetPrivateData";
    case 235: return "cube.GetPrivateData";
    case 236: return "cube.FreePrivateData";
    case 237: return "cube.SetPriority";
    case 238: return "cube.GetPriority";
    case 239: return "cube.PreLoad";
    case 240: return "cube.GetType";
    case 241: return "cube.SetLOD";
    case 242: return "cube.GetLOD";
    case 243: return "cube.GetLevelCount";
    case 244: return "cube.SetAutoGenFilterType";
    case 245: return "cube.GetAutoGenFilterType";
    case 246: return "cube.GenerateMipSubLevels";
    case 247: return "cube.GetLevelDesc";
    case 248: return "cube.GetCubeMapSurface";
    case 249: return "cube.LockRect";
    case 250: return "cube.UnlockRect";
    case 251: return "cube.AddDirtyRect";
    case 260: return "vtex.QueryInterface";
    case 261: return "vtex.AddRef";
    case 262: return "vtex.Release";
    case 263: return "vtex.GetDevice";
    case 264: return "vtex.SetPrivateData";
    case 265: return "vtex.GetPrivateData";
    case 266: return "vtex.FreePrivateData";
    case 267: return "vtex.SetPriority";
    case 268: return "vtex.GetPriority";
    case 269: return "vtex.PreLoad";
    case 270: return "vtex.GetType";
    case 271: return "vtex.SetLOD";
    case 272: return "vtex.GetLOD";
    case 273: return "vtex.GetLevelCount";
    case 274: return "vtex.SetAutoGenFilterType";
    case 275: return "vtex.GetAutoGenFilterType";
    case 276: return "vtex.GenerateMipSubLevels";
    case 277: return "vtex.GetLevelDesc";
    case 278: return "vtex.GetVolumeLevel";
    case 279: return "vtex.LockBox";
    case 280: return "vtex.UnlockBox";
    case 281: return "vtex.AddDirtyBox";
    case 290: return "surf.QueryInterface";
    case 291: return "surf.AddRef";
    case 292: return "surf.Release";
    case 293: return "surf.GetDevice";
    case 294: return "surf.SetPrivateData";
    case 295: return "surf.GetPrivateData";
    case 296: return "surf.FreePrivateData";
    case 297: return "surf.SetPriority";
    case 298: return "surf.GetPriority";
    case 299: return "surf.PreLoad";
    case 300: return "surf.GetType";
    case 301: return "surf.GetContainer";
    case 302: return "surf.GetDesc";
    case 303: return "surf.LockRect";
    case 304: return "surf.UnlockRect";
    case 305: return "surf.GetDC";
    case 306: return "surf.ReleaseDC";
    case 310: return "vol.QueryInterface";
    case 311: return "vol.AddRef";
    case 312: return "vol.Release";
    case 313: return "vol.GetDevice";
    case 314: return "vol.SetPrivateData";
    case 315: return "vol.GetPrivateData";
    case 316: return "vol.FreePrivateData";
    case 317: return "vol.GetContainer";
    case 318: return "vol.GetDesc";
    case 319: return "vol.LockBox";
    case 320: return "vol.UnlockBox";
    case 330: return "vb.QueryInterface";
    case 331: return "vb.AddRef";
    case 332: return "vb.Release";
    case 333: return "vb.GetDevice";
    case 334: return "vb.SetPrivateData";
    case 335: return "vb.GetPrivateData";
    case 336: return "vb.FreePrivateData";
    case 337: return "vb.SetPriority";
    case 338: return "vb.GetPriority";
    case 339: return "vb.PreLoad";
    case 340: return "vb.GetType";
    case 341: return "vb.Lock";
    case 342: return "vb.Unlock";
    case 343: return "vb.GetDesc";
    case 350: return "ib.QueryInterface";
    case 351: return "ib.AddRef";
    case 352: return "ib.Release";
    case 353: return "ib.GetDevice";
    case 354: return "ib.SetPrivateData";
    case 355: return "ib.GetPrivateData";
    case 356: return "ib.FreePrivateData";
    case 357: return "ib.SetPriority";
    case 358: return "ib.GetPriority";
    case 359: return "ib.PreLoad";
    case 360: return "ib.GetType";
    case 361: return "ib.Lock";
    case 362: return "ib.Unlock";
    case 363: return "ib.GetDesc";
    case 370: return "sb.QueryInterface";
    case 371: return "sb.AddRef";
    case 372: return "sb.Release";
    case 373: return "sb.GetDevice";
    case 374: return "sb.Capture";
    case 375: return "sb.Apply";
    case 380: return "q.QueryInterface";
    case 381: return "q.AddRef";
    case 382: return "q.Release";
    case 383: return "q.GetDevice";
    case 384: return "q.GetType";
    case 385: return "q.GetDataSize";
    case 386: return "q.Issue";
    case 387: return "q.GetData";
    case 390: return "sc.QueryInterface";
    case 391: return "sc.AddRef";
    case 392: return "sc.Release";
    case 393: return "sc.Present";
    case 394: return "sc.GetFrontBufferData";
    case 395: return "sc.GetBackBuffer";
    case 396: return "sc.GetRasterStatus";
    case 397: return "sc.GetDisplayMode";
    case 398: return "sc.GetDevice";
    case 399: return "sc.GetPresentParameters";
    case 400: return "vs.QueryInterface";
    case 401: return "vs.AddRef";
    case 402: return "vs.Release";
    case 403: return "vs.GetDevice";
    case 404: return "vs.GetFunction";
    case 410: return "ps.QueryInterface";
    case 411: return "ps.AddRef";
    case 412: return "ps.Release";
    case 413: return "ps.GetDevice";
    case 414: return "ps.GetFunction";
    case 420: return "decl.QueryInterface";
    case 421: return "decl.AddRef";
    case 422: return "decl.Release";
    case 423: return "decl.GetDevice";
    case 424: return "decl.GetDeclaration";
    case 509: return "d3dx.FilterTexture";
    case 510: return "fx.batch";
    }
    return "?";
}
