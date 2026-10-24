; Generated from build_code at an illustrative cave address; not a game runtime trace.
; The allocated cave address depends on the existing sections and selected patch order.
; hook VA=0x0092d5eb, replacement=e9 10 5a 5a 00
; cave VA=0x00ed3000, size=340 bytes
00ed3000  9c                             pushfd
00ed3001  60                             pushal
00ed3002  83 ec 10                       sub      esp, 0x10
00ed3005  33 c0                          xor      eax, eax
00ed3007  89 04 24                       mov      dword ptr [esp], eax
00ed300a  89 44 24 04                    mov      dword ptr [esp + 4], eax
00ed300e  c7 44 24 08 80 00 00 00        mov      dword ptr [esp + 8], 0x80
00ed3016  8b 75 e0                       mov      esi, dword ptr [ebp - 0x20]
00ed3019  85 f6                          test     esi, esi
00ed301b  0f 84 24 01 00 00              je       0xed3145
00ed3021  8b be 58 02 00 00              mov      edi, dword ptr [esi + 0x258]
00ed3027  85 ff                          test     edi, edi
00ed3029  0f 84 16 01 00 00              je       0xed3145
00ed302f  8b cf                          mov      ecx, edi
00ed3031  8b 01                          mov      eax, dword ptr [ecx]
00ed3033  ff 50 7c                       call     dword ptr [eax + 0x7c]
00ed3036  85 c0                          test     eax, eax
00ed3038  0f 84 07 01 00 00              je       0xed3145
00ed303e  8b d8                          mov      ebx, eax
00ed3040  8b 47 e4                       mov      eax, dword ptr [edi - 0x1c]
00ed3043  85 c0                          test     eax, eax
00ed3045  0f 84 fa 00 00 00              je       0xed3145
00ed304b  80 b8 24 02 00 00 00           cmp      byte ptr [eax + 0x224], 0
00ed3052  0f 85 a3 00 00 00              jne      0xed30fb
00ed3058  8b 7f 34                       mov      edi, dword ptr [edi + 0x34]
00ed305b  85 ff                          test     edi, edi
00ed305d  0f 84 e2 00 00 00              je       0xed3145
00ed3063  8b 1f                          mov      ebx, dword ptr [edi]
00ed3065  3b df                          cmp      ebx, edi
00ed3067  0f 84 66 00 00 00              je       0xed30d3
00ed306d  85 db                          test     ebx, ebx
00ed306f  0f 84 d0 00 00 00              je       0xed3145
00ed3075  ff 4c 24 08                    dec      dword ptr [esp + 8]
00ed3079  0f 88 c6 00 00 00              js       0xed3145
00ed307f  8b 73 08                       mov      esi, dword ptr [ebx + 8]
00ed3082  85 f6                          test     esi, esi
00ed3084  0f 84 42 00 00 00              je       0xed30cc
00ed308a  8b b6 5c 02 00 00              mov      esi, dword ptr [esi + 0x25c]
00ed3090  85 f6                          test     esi, esi
00ed3092  0f 84 34 00 00 00              je       0xed30cc
00ed3098  8b ce                          mov      ecx, esi
00ed309a  8b 01                          mov      eax, dword ptr [ecx]
00ed309c  ff 50 1c                       call     dword ptr [eax + 0x1c]
00ed309f  d9 5c 24 0c                    fstp     dword ptr [esp + 0xc]
00ed30a3  d9 ee                          fldz
00ed30a5  d9 44 24 0c                    fld      dword ptr [esp + 0xc]
00ed30a9  df f1                          fcompi   st(1)
00ed30ab  dd d8                          fstp     st(0)
00ed30ad  0f 86 19 00 00 00              jbe      0xed30cc
00ed30b3  8b ce                          mov      ecx, esi
00ed30b5  8b 01                          mov      eax, dword ptr [ecx]
00ed30b7  ff 50 10                       call     dword ptr [eax + 0x10]
00ed30ba  d8 04 24                       fadd     dword ptr [esp]
00ed30bd  d9 1c 24                       fstp     dword ptr [esp]
00ed30c0  d9 44 24 0c                    fld      dword ptr [esp + 0xc]
00ed30c4  d8 44 24 04                    fadd     dword ptr [esp + 4]
00ed30c8  d9 5c 24 04                    fstp     dword ptr [esp + 4]
00ed30cc  8b 1b                          mov      ebx, dword ptr [ebx]
00ed30ce  e9 92 ff ff ff                 jmp      0xed3065
00ed30d3  d9 ee                          fldz
00ed30d5  d9 44 24 04                    fld      dword ptr [esp + 4]
00ed30d9  df f1                          fcompi   st(1)
00ed30db  dd d8                          fstp     st(0)
00ed30dd  0f 86 0c 00 00 00              jbe      0xed30ef
00ed30e3  d9 04 24                       fld      dword ptr [esp]
00ed30e6  d8 74 24 04                    fdiv     dword ptr [esp + 4]
00ed30ea  e9 02 00 00 00                 jmp      0xed30f1
00ed30ef  d9 ee                          fldz
00ed30f1  83 c4 10                       add      esp, 0x10
00ed30f4  61                             popal
00ed30f5  9d                             popfd
00ed30f6  e9 f5 a4 a5 ff                 jmp      0x92d5f0
00ed30fb  8b 83 50 01 00 00              mov      eax, dword ptr [ebx + 0x150]
00ed3101  85 c0                          test     eax, eax
00ed3103  0f 84 3c 00 00 00              je       0xed3145
00ed3109  8b 0d 2c 41 de 00              mov      ecx, dword ptr [0xde412c]
00ed310f  85 c9                          test     ecx, ecx
00ed3111  0f 84 2e 00 00 00              je       0xed3145
00ed3117  50                             push     eax
00ed3118  e8 64 65 57 ff                 call     0x449681
00ed311d  85 c0                          test     eax, eax
00ed311f  0f 84 20 00 00 00              je       0xed3145
00ed3125  3b c6                          cmp      eax, esi
00ed3127  0f 84 18 00 00 00              je       0xed3145
00ed312d  8b 88 5c 02 00 00              mov      ecx, dword ptr [eax + 0x25c]
00ed3133  85 c9                          test     ecx, ecx
00ed3135  0f 84 0a 00 00 00              je       0xed3145
00ed313b  8b 01                          mov      eax, dword ptr [ecx]
00ed313d  ff 50 14                       call     dword ptr [eax + 0x14]
00ed3140  e9 ac ff ff ff                 jmp      0xed30f1
00ed3145  83 c4 10                       add      esp, 0x10
00ed3148  61                             popal
00ed3149  9d                             popfd
00ed314a  8b 01                          mov      eax, dword ptr [ecx]
00ed314c  ff 50 14                       call     dword ptr [eax + 0x14]
00ed314f  e9 9c a4 a5 ff                 jmp      0x92d5f0
