# `worldbuilder-label-assert` - the `.str` label assert

The `.str` label assert that stops Worldbuilder opening a mod with multi-colon labels.

**This patch targets `Worldbuilder.exe`, not `game.dat`.**

`Worldbuilder.exe` is an assert-enabled build - it prints `_INTERNAL defined.` on its second
line - so `DEBUG_CRASH` is *live* in it and compiled out of the shipping `game.dat`. That single
asymmetry is why a mod can run in the game and refuse to open in the editor, and this is one of
the asserts that difference exposes.

`GameText.cpp:888` requires every label in `data\lotr.str` to be exactly `[file]:[name]`: it
searches for a **second** colon and insists there is none, or that it is the last character on the
line. Edain's string table carries 108 labels that break that rule - `CONTROLBAR:tooltip:
horrortiefen`, `SCRIPT:interface:level1`, and so on - and the editor stops on the first one,
0.1 s into startup, before any INI is read:

    Assertion failed in ...GameClient\GameText.cpp, line 888
    expression (colon==NULL) || (colon==(endOfLine-1)): Label 'CONTROLBAR:tooltip:horrortiefen'
    in file 'data\lotr.str, line 49269 does not match '[file]:[name]' format: Too many colons.
    Babylon can't process this file.

The complaint is about **Babylon**, EA's localisation tool, not about the engine: the parser
splits on the *first* colon and takes the rest as the name either way, which is why the same
table loads in the game without comment. Nothing downstream of the assert reads the second colon.

The guard is the ordinary `DEBUG_CRASH` shape - two early-outs for the legal cases, then the
report block:

    00bf5047  mov  [ebp-0x3c], eax      ; colon = strchr(afterFirstColon, ':')
    00bf504a  cmp  dword [ebp-0x3c], 0  ; colon == NULL?
    00bf504e  je   0x00BF5138           ;   -> fine, carry on
    00bf5054  mov  eax, [ebp-0x18]      ; endOfLine
    00bf5057  sub  eax, 1
    00bf505a  cmp  [ebp-0x3c], eax      ; colon == endOfLine-1?
    00bf505d  je   0x00BF5138           ;   -> fine, carry on
    00bf5063  push 0                    ; else: is the assert suppressed?
    00bf5065  call 0x00712DC0
    ...
    00bf509e  push 0x378                ; line 888
    00bf5138                            ; <- where both legal cases land

So the whole patch is **one instruction**: make the second early-out unconditional, and the third
case joins the two that were already fine. `0x00BF5138` is the label the legal paths already jump
to, so this adds no new control flow - it takes an existing edge unconditionally.

**Why not fix the string table instead.** Renaming 108 labels means renaming every
`CommandButton`/script reference to them as well, in both language trees, for a rule that only
EA's internal tool ever enforced. And it would have to be redone for every label a translator adds
later. The assert is the thing that is wrong for a mod, so the assert is what moves.

**Scope.** This silences exactly one assert. Others in the same build stay live, which is
deliberate - they are the editor's early warning about real data problems, and the shipped
`Worldbuilder.dbgcmd` (`debug.errors -`) is the blunt instrument for turning the lot off.
