; generated 2026-10-19 from hero-horde-all-melee/game.dat; no game runtime proof
; hook VA=0x0087386c bytes=e9 8f f7 65 00 90
; cave VA=0x00ed3000 file-offset=0xad2400 size=328
00ed3000  9c                             pushfd   
00ed3001  60                             pushal   
00ed3002  8b ec                          mov      ebp, esp
00ed3004  81 ec 10 02 00 00              sub      esp, 0x210
00ed300a  83 e4 f0                       and      esp, 0xfffffff0
00ed300d  0f ae 04 24                    fxsave   [esp]
00ed3011  8b b6 ec fe ff ff              mov      esi, dword ptr [esi - 0x114]
00ed3017  85 f6                          test     esi, esi
00ed3019  0f 84 16 01 00 00              je       0xed3135
00ed301f  8b 46 04                       mov      eax, dword ptr [esi + 4]
00ed3022  85 c0                          test     eax, eax
00ed3024  0f 84 0b 01 00 00              je       0xed3135
00ed302a  f6 80 13 01 00 00 04           test     byte ptr [eax + 0x113], 4
00ed3031  0f 84 fe 00 00 00              je       0xed3135
00ed3037  f6 80 15 01 00 00 20           test     byte ptr [eax + 0x115], 0x20
00ed303e  0f 84 f1 00 00 00              je       0xed3135
00ed3044  f6 86 58 04 00 00 01           test     byte ptr [esi + 0x458], 1
00ed304b  0f 85 e4 00 00 00              jne      0xed3135
00ed3051  8b 86 5c 02 00 00              mov      eax, dword ptr [esi + 0x25c]
00ed3057  85 c0                          test     eax, eax
00ed3059  0f 84 d6 00 00 00              je       0xed3135
00ed305f  81 38 e0 1f c7 00              cmp      dword ptr [eax], 0xc71fe0
00ed3065  0f 85 ca 00 00 00              jne      0xed3135
00ed306b  83 be 6c 02 00 00 00           cmp      dword ptr [esi + 0x26c], 0
00ed3072  0f 84 bd 00 00 00              je       0xed3135
00ed3078  8b 0d e4 90 dd 00              mov      ecx, dword ptr [0xdd90e4]
00ed307e  85 c9                          test     ecx, ecx
00ed3080  0f 84 af 00 00 00              je       0xed3135
00ed3086  68 98 b0 c0 00                 push     0xc0b098
00ed308b  e8 5c 57 67 ff                 call     0x5487ec
00ed3090  50                             push     eax
00ed3091  8b ce                          mov      ecx, esi
00ed3093  e8 0d 8d 7b ff                 call     0x68bda5
00ed3098  85 c0                          test     eax, eax
00ed309a  0f 84 95 00 00 00              je       0xed3135
00ed30a0  81 38 60 c3 c6 00              cmp      dword ptr [eax], 0xc6c360
00ed30a6  0f 85 89 00 00 00              jne      0xed3135
00ed30ac  39 70 08                       cmp      dword ptr [eax + 8], esi
00ed30af  0f 85 80 00 00 00              jne      0xed3135
00ed30b5  8b f8                          mov      edi, eax
00ed30b7  8b 40 2c                       mov      eax, dword ptr [eax + 0x2c]
00ed30ba  85 c0                          test     eax, eax
00ed30bc  0f 84 09 00 00 00              je       0xed30cb
00ed30c2  83 f8 04                       cmp      eax, 4
00ed30c5  0f 85 6a 00 00 00              jne      0xed3135
00ed30cb  8b 5f 04                       mov      ebx, dword ptr [edi + 4]
00ed30ce  85 db                          test     ebx, ebx
00ed30d0  0f 84 5f 00 00 00              je       0xed3135
00ed30d6  83 bb 0c 01 00 00 00           cmp      dword ptr [ebx + 0x10c], 0
00ed30dd  0f 84 52 00 00 00              je       0xed3135
00ed30e3  8b 86 6c 02 00 00              mov      eax, dword ptr [esi + 0x26c]
00ed30e9  ff 70 24                       push     dword ptr [eax + 0x24]
00ed30ec  8b d4                          mov      edx, esp
00ed30ee  52                             push     edx
00ed30ef  8d 8b 0c 01 00 00              lea      ecx, [ebx + 0x10c]
00ed30f5  e8 fc 09 73 ff                 call     0x603af6
00ed30fa  5a                             pop      edx
00ed30fb  3b 83 0c 01 00 00              cmp      eax, dword ptr [ebx + 0x10c]
00ed3101  0f 85 1d 00 00 00              jne      0xed3124
00ed3107  6a 01                          push     1
00ed3109  8b d4                          mov      edx, esp
00ed310b  52                             push     edx
00ed310c  8d 8b 0c 01 00 00              lea      ecx, [ebx + 0x10c]
00ed3112  e8 df 09 73 ff                 call     0x603af6
00ed3117  5a                             pop      edx
00ed3118  3b 83 0c 01 00 00              cmp      eax, dword ptr [ebx + 0x10c]
00ed311e  0f 84 11 00 00 00              je       0xed3135
00ed3124  80 78 20 00                    cmp      byte ptr [eax + 0x20], 0
00ed3128  0f 85 07 00 00 00              jne      0xed3135
00ed312e  8b cf                          mov      ecx, edi
00ed3130  e8 0f 06 9e ff                 call     0x8b3744
00ed3135  0f ae 0c 24                    fxrstor  [esp]
00ed3139  8b e5                          mov      esp, ebp
00ed313b  61                             popal    
00ed313c  9d                             popfd    
00ed313d  ff b6 ec fe ff ff              push     dword ptr [esi - 0x114]
00ed3143  e9 2a 07 9a ff                 jmp      0x873872
