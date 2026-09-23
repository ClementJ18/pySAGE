# `worldbuilder-silent-errors` - Worldbuilder's internal-build diagnostics

Stop Worldbuilder's internal-build diagnostics stalling the editor on a mod's data.

**This patch targets `Worldbuilder.exe`, not `game.dat`.**

`Worldbuilder.exe` prints `_INTERNAL defined.` on startup: it is an assert-enabled build, so
every `DEBUG_LOG` / `DEBUG_CRASH` in the shared engine is *live* in it and compiled out of the
shipping `game.dat`. On a mod with a long history that is not a trickle - it is a wall. Each one
raises a modal `Assertion failed` / `Error hit` box during startup, and the editor gets no
further until somebody clicks it, which on screen looks exactly like the splash appearing and then
vanishing.

Every one of them funnels through a single gate. The report sites all open the same way:

    push 0
    call 0x00712DC0          ; may I skip this report?
    add  esp, 4
    movzx ecx, al
    test ecx, ecx
    jne  <past the report>   ; non-zero -> skip
    ...
    call [TheDebug + 0x60]   ; second gate, same shape
    jne  <past the report>
    ...build and show the box...

`0x00712DC0` is a four-line thunk onto `TheDebug->vtable[0x5c]`, and **25,018 call sites reach
it** - which is the measure of how many individual patches this one replaces. Returning a non-zero
`al` from it takes the `jne` at every one of them.

    00712dc0  55 8b ec        push ebp ; mov ebp, esp   ->   b0 01    mov al, 1
    00712dc3  51              push ecx                  ->   c3       ret

The function is caller-cleaned (it ends in a bare `ret` and every site does its own
`add esp, 4`), so returning before the frame is set up leaves the stack exactly as the original
did.

## What this does **not** silence
Only the *gated* reports, which are the ones that stall. A `throw` that sits outside the gate is
untouched, and there are several on the INI path - `scanLookupList`, `Unknown block '%s'`, and
`ScienceStore::getScienceFromInternalName` among them. Those are real load failures rather than
complaints, they still stop the editor, and each still needs its own patch
(`science-prereqs-wb` is one). So this is not a blanket "ignore the mod's problems" switch: it
removes the noise and leaves the failures.

## The cost, stated plainly
The editor loses **all** of its diagnostics, including ones a modder would want. That is a real
loss and the reason this is a separate patch rather than part of another: apply it when the
editor's asserts are what is standing between you and opening the tool, and revert it when you
want the editor's opinion on your data. The shipped `Worldbuilder.dbgcmd` (`debug.errors -`)
looks like it should do this and does not - it does not gate these sites - which is what leaves a
binary patch as the way to get it.
