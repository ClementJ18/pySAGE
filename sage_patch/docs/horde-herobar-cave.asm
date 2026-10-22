; banner-health correction, full 63-patch build; no runtime proof
; hook=0x92d5eb cave=0xfd3000 raw=0xba6800 size=384
00fd3000 9c                             pushfd   
00fd3001 60                             pushal   
00fd3002 83 ec 0c                       sub      esp, 0xc
00fd3005 c7 04 24 00 00 00 00           mov      dword ptr [esp], 0
00fd300c c7 44 24 08 80 00 00 00        mov      dword ptr [esp + 8], 0x80
00fd3014 8b 75 e0                       mov      esi, dword ptr [ebp - 0x20]
00fd3017 85 f6                          test     esi, esi
00fd3019 0f 84 52 01 00 00              je       0xfd3171
00fd301f 8b 46 04                       mov      eax, dword ptr [esi + 4]
00fd3022 85 c0                          test     eax, eax
00fd3024 0f 84 47 01 00 00              je       0xfd3171
00fd302a f7 80 14 01 00 00 00 20 00 00  test     dword ptr [eax + 0x114], 0x2000
00fd3034 0f 84 37 01 00 00              je       0xfd3171
00fd303a f6 80 16 01 00 00 80           test     byte ptr [eax + 0x116], 0x80
00fd3041 0f 85 ab 00 00 00              jne      0xfd30f2
00fd3047 8b be 58 02 00 00              mov      edi, dword ptr [esi + 0x258]
00fd304d 85 ff                          test     edi, edi
00fd304f 0f 84 1c 01 00 00              je       0xfd3171
00fd3055 8b cf                          mov      ecx, edi
00fd3057 8b 01                          mov      eax, dword ptr [ecx]
00fd3059 ff 50 7c                       call     dword ptr [eax + 0x7c]
00fd305c 85 c0                          test     eax, eax
00fd305e 0f 84 0d 01 00 00              je       0xfd3171
00fd3064 8b 47 e4                       mov      eax, dword ptr [edi - 0x1c]
00fd3067 85 c0                          test     eax, eax
00fd3069 0f 84 02 01 00 00              je       0xfd3171
00fd306f 8b 80 98 00 00 00              mov      eax, dword ptr [eax + 0x98]
00fd3075 83 f8 01                       cmp      eax, 1
00fd3078 0f 8c f3 00 00 00              jl       0xfd3171
00fd307e 3d 80 00 00 00                 cmp      eax, 0x80
00fd3083 0f 8f e8 00 00 00              jg       0xfd3171
00fd3089 89 44 24 04                    mov      dword ptr [esp + 4], eax
00fd308d 8b 7f 34                       mov      edi, dword ptr [edi + 0x34]
00fd3090 85 ff                          test     edi, edi
00fd3092 0f 84 d9 00 00 00              je       0xfd3171
00fd3098 8b 1f                          mov      ebx, dword ptr [edi]
00fd309a 3b df                          cmp      ebx, edi
00fd309c 0f 84 3d 00 00 00              je       0xfd30df
00fd30a2 85 db                          test     ebx, ebx
00fd30a4 0f 84 c7 00 00 00              je       0xfd3171
00fd30aa ff 4c 24 08                    dec      dword ptr [esp + 8]
00fd30ae 0f 88 bd 00 00 00              js       0xfd3171
00fd30b4 8b 73 08                       mov      esi, dword ptr [ebx + 8]
00fd30b7 85 f6                          test     esi, esi
00fd30b9 0f 84 19 00 00 00              je       0xfd30d8
00fd30bf 8b 8e 5c 02 00 00              mov      ecx, dword ptr [esi + 0x25c]
00fd30c5 85 c9                          test     ecx, ecx
00fd30c7 0f 84 0b 00 00 00              je       0xfd30d8
00fd30cd 8b 01                          mov      eax, dword ptr [ecx]
00fd30cf ff 50 14                       call     dword ptr [eax + 0x14]
00fd30d2 d8 04 24                       fadd     dword ptr [esp]
00fd30d5 d9 1c 24                       fstp     dword ptr [esp]
00fd30d8 8b 1b                          mov      ebx, dword ptr [ebx]
00fd30da e9 bb ff ff ff                 jmp      0xfd309a
00fd30df d9 04 24                       fld      dword ptr [esp]
00fd30e2 db 44 24 04                    fild     dword ptr [esp + 4]
00fd30e6 de f9                          fdivp    st(1)
00fd30e8 83 c4 0c                       add      esp, 0xc
00fd30eb 61                             popal    
00fd30ec 9d                             popfd    
00fd30ed e9 fe a4 95 ff                 jmp      0x92d5f0
00fd30f2 8b be 58 02 00 00              mov      edi, dword ptr [esi + 0x258]
00fd30f8 85 ff                          test     edi, edi
00fd30fa 0f 84 71 00 00 00              je       0xfd3171
00fd3100 8b 47 e4                       mov      eax, dword ptr [edi - 0x1c]
00fd3103 85 c0                          test     eax, eax
00fd3105 0f 84 66 00 00 00              je       0xfd3171
00fd310b 80 b8 24 02 00 00 00           cmp      byte ptr [eax + 0x224], 0
00fd3112 0f 84 59 00 00 00              je       0xfd3171
00fd3118 8b cf                          mov      ecx, edi
00fd311a 8b 01                          mov      eax, dword ptr [ecx]
00fd311c ff 50 7c                       call     dword ptr [eax + 0x7c]
00fd311f 85 c0                          test     eax, eax
00fd3121 0f 84 4a 00 00 00              je       0xfd3171
00fd3127 8b 80 50 01 00 00              mov      eax, dword ptr [eax + 0x150]
00fd312d 85 c0                          test     eax, eax
00fd312f 0f 84 3c 00 00 00              je       0xfd3171
00fd3135 8b 0d 2c 41 de 00              mov      ecx, dword ptr [0xde412c]
00fd313b 85 c9                          test     ecx, ecx
00fd313d 0f 84 2e 00 00 00              je       0xfd3171
00fd3143 50                             push     eax
00fd3144 e8 38 65 47 ff                 call     0x449681
00fd3149 85 c0                          test     eax, eax
00fd314b 0f 84 20 00 00 00              je       0xfd3171
00fd3151 3b c6                          cmp      eax, esi
00fd3153 0f 84 18 00 00 00              je       0xfd3171
00fd3159 8b 88 5c 02 00 00              mov      ecx, dword ptr [eax + 0x25c]
00fd315f 85 c9                          test     ecx, ecx
00fd3161 0f 84 0a 00 00 00              je       0xfd3171
00fd3167 8b 01                          mov      eax, dword ptr [ecx]
00fd3169 ff 50 14                       call     dword ptr [eax + 0x14]
00fd316c e9 77 ff ff ff                 jmp      0xfd30e8
00fd3171 83 c4 0c                       add      esp, 0xc
00fd3174 61                             popal    
00fd3175 9d                             popfd    
00fd3176 8b 01                          mov      eax, dword ptr [ecx]
00fd3178 ff 50 14                       call     dword ptr [eax + 0x14]
00fd317b e9 70 a4 95 ff                 jmp      0x92d5f0
