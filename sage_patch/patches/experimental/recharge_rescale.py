"""The recharge-rescale patch: a cooldown already running responds to a modifier that arrives
after the cast.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../../docs/recharge-rescale.md``.

**The defect.** `SpecialAbilityUpdate::startPowerRecharge` (``0x00896E31``) computes the whole
cooldown once, at the moment the power fires, and stores an **absolute ready frame** at
``interface+0x08``. A recharge modifier that arrives one frame later - a leadership aura, a
temporary `RECHARGE_TIME` buff, the player finishing a `SpellRechargeModifierUpgrade` - cannot
touch a cooldown that is already running. It only pays off on the *next* cast.

**Why this is cheap.** The module stores the cooldown **twice**: the ready frame at
``interface+0x08``, and beside it, at ``interface+0x04``, the *length* of the cooldown that
produced it - ``max(1, ftol(ReloadTime * m))``, where ``m`` is the multiplier that was in force at
cast time. That second field exists to draw the button clock, and it is the record this patch would
otherwise have had nowhere to put: `ReloadTime` is still on the template, so recomputing the stock
formula now and comparing the two **integers** says whether the multiplier has moved, exactly and
with no tolerance to choose. Both fields are already `Xfer`'d (``0x0089679D``), so savegames need no
version bump.

**What this does.** One `call rel32` inside `GameLogic::update`, and one cave. Once per logic
frame, for every special power that is on cooldown:

* recompute ``frames_now = max(1, ftol(ReloadTime * m_now))`` the way `startPowerRecharge` does -
  the `RECHARGE_TIME` attribute modifier off the object, times ``1 + Player[0x718]`` when the
  template carries `RESPECT_RECHARGE_TIME_DISCOUNT`;
* if that equals the stored duration, **stop** - which is the answer for every power whose
  modifiers have not moved, and therefore for almost every power on almost every frame;
* otherwise rescale the remainder, ``remaining' = remaining * frames_now / duration``, and store
  ``frames_now`` as the new duration.

**Rescaling the remainder is exactly a per-frame rate, not an approximation of one.** Model the
cooldown as ``W`` unscaled frames of work consumed at ``1/m`` per frame; the remaining wall-clock
time is ``W_left * m``, which *is* the stored remainder, so ``remaining * m'/m`` tracks ``W_left``
implicitly. A modifier held for part of a cooldown produces the same finish frame as integrating a
rate over that interval, and dropping it reverses precisely the fraction of work it did not consume.
"Cooldown speed 150% removes 1.5 seconds per second" falls out; it is not aimed at. The only error
is the two `ftol` truncations - under one frame per *change*, not per frame.

**The clock follows and does not jump.** `getPercentReady` (``0x00896CF2``) is
``1 - (readyFrame - now) / duration``, recomputed on every call. Scaling numerator and denominator
by the same factor leaves the pie where it is and changes only how fast it fills - which is why
both fields are written and never just the ready frame. Writing ``+0x08`` alone would snap the
clock forward when an aura landed and snap it back when the aura expired.

**Why a sweep, and not a tick.** There is nothing to hook: the cooldown is an absolute frame, so
nothing runs while it elapses, and most special-power modules are not update modules at all. The
engine's own per-frame object walk is the driver - ``TheGameLogic+0xAC`` chained through
``Object+0x8C``, with the special power reached through the module's own vtable
(``[module+0xC]`` slot ``+0x20``, the idiom at ``0x008979F5``) rather than by assuming a layout, so
a module type this reading has never heard of answers NULL and costs one indirect call. Integrating
at *read* time instead is not an option: the percent is queried by the local UI for the local
selection only, and simulation state that depends on that is a desync.

**Deliberately skipped, and both fail closed.** The *second* implementation of
`startPowerRecharge` at ``0x00991500`` (3 module vtables of 26) keeps no duration - its
`getPercentReady` divides by the raw `ReloadTime` - so nothing on it says what multiplier it baked
in; the flavour test is one `cmp` against the function found at interface slot ``+0x3C``, and
anything that is neither known implementation is left alone. `SharedSyncedTimer` powers store their
frame on the `Player` (``Player+0x724``), have no duration either, and are per-player, so an
object-scoped `RECHARGE_TIME` could not reach them anyway. A power whose recharge is *paused*
(``interface+0x0C`` non-zero) is skipped too, so this and ``0x00896756`` never fight over the same
field.

**Where it hooks, and why not the entry.** ``0x0062E56A`` is the `call` whose result gates the
frame counter: the increment at ``0x0062E577`` happens exactly when ``al != 0 && bl == 0``, and the
cave sweeps under that same pair, so it cannot run a different number of times on two peers. The
increment itself is three bytes and a fall-through target. `live-bridge` owns
`GameLogic::update`'s **entry** (``0x0062E4E8``, five bytes) and nothing else in the function, so
the two compose.

**Cost, honestly.** The sweep is ``O(objects x modules)`` pointer loads plus one indirect call per
module, per logic frame. `getModifierMultiplier` - the expensive query, since
`Object::getModifierHolder` is a module lookup by name key - is reached only for a power that is
actually on cooldown. This is the only part of the patch that scales with army size.

**Determinism.** A ready frame gates whether an ability can fire, so this is simulation state:
**every peer must run the same patched binary** and replays recorded on it will not play back on a
stock one.

**No-op on data that never moves a multiplier mid-cooldown.** The rescale is gated on an integer
comparison against the quantity the stock formula produces from stock inputs, so a match with no
`RECHARGE_TIME` modifier and no mid-match recharge upgrade finishes every power on the frame it
would have finished on today. That is what makes this cheap to test and cheap to back out - and it
is a claim about the arithmetic, not about the sweep, which runs either way.

**Composition.** Order-independent: the cave is allocated past every existing section with
:func:`~...utils.allocate_section` and :meth:`verify` finds it by name. The one `call`
displacement it rewrites is touched by no other bundled patch, and it reads nothing another patch
rewrites.
"""

from __future__ import annotations

import struct

from ...asm import JAE, JE, JG, JLE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "HOOK_CALL_VA",
    "RECHARGE_TIME_MODIFIER",
    "SECTION_NAME",
    "SPI_DURATION",
    "SPI_PAUSE_COUNT",
    "SPI_READY_FRAME",
    "START_POWER_RECHARGE",
    "RechargeRescalePatch",
    "build_section",
]

THE_GAME_LOGIC = 0x00DE412C
#: `GameLogic::m_frame`, and the object list head the sweep walks.
GAME_LOGIC_FRAME = 0x40
GAME_LOGIC_FIRST_OBJECT = 0xAC

#: `Object::m_next` in that list, and the NULL-terminated `BehaviorModule *[]` hanging off it.
OBJECT_NEXT = 0x8C
OBJECT_MODULES = 0x24C
#: The `BehaviorModuleInterface` subobject inside a module, and the vtable slot that answers
#: `SpecialPowerModuleInterface *` or NULL. The engine's own query - see ``0x008979F5``.
MODULE_INTERFACE = 0x0C
GET_SPECIAL_POWER_SLOT = 0x20

#: `SpecialPowerModuleInterface`, flavour 1 - the layout this patch writes. `startPowerRecharge`
#: at slot ``+0x3C`` **is** the flavour test: 23 vtables carry :data:`START_POWER_RECHARGE`, three
#: carry :data:`START_POWER_RECHARGE_ALT`, and anything else is left alone.
SPI_VTABLE_TEMPLATE_SLOT = 0x18
SPI_VTABLE_RECHARGE_SLOT = 0x3C
SPI_DURATION = 0x04  # the cooldown's own length in frames - the record of the baked-in multiplier
SPI_READY_FRAME = 0x08
SPI_PAUSE_COUNT = 0x0C  # non-zero while 0x00896756 owns the ready frame

START_POWER_RECHARGE = 0x00896E31
START_POWER_RECHARGE_ALT = 0x00991500  # readyFrame at +0x04, no duration - skipped

#: `SpecialPowerTemplate`, the three fields the cast-time formula reads.
TEMPLATE_FLAGS = 0x18
TEMPLATE_RESPECT_RECHARGE_DISCOUNT = 0x20  # bit 5 of Flags
TEMPLATE_RELOAD_TIME = 0x20  # Int frames
TEMPLATE_SHARED_SYNCED_TIMER = 0x59

#: `ModifierList` attribute type 12. Read at exactly two sites in the stock image, ``0x00896EA0``
#: and ``0x00991564``.
RECHARGE_TIME_MODIFIER = 0x0C

GET_FINAL_OVERRIDE = 0x00688D3C  # __thiscall, no args -> eax
GET_CONTROLLING_PLAYER = 0x0068B678  # __thiscall, no args -> Player * or NULL
GET_MODIFIER_MULTIPLIER = 0x0068C82D  # __thiscall(type, Real *out, ctx, flag), ret 0x10
GET_SPELL_RECHARGE_MODIFIER = 0x006AAAD2  # __thiscall -> fld [Player+0x718], no cleanup
FTOL = 0x00A3CFA4  # pops st(0) -> eax; clobbers eax, ecx, edx
ONE_FLOAT = 0x00BD1908  # the engine's own 1.0f

#: The hooked `call`, and the predicate behind it. Its ``al``, with the caller's ``bl``, is exactly
#: the condition under which ``0x0062E577`` advances the frame counter.
HOOK_CALL_VA = 0x0062E56A
LOGIC_FRAME_GATE = 0x00625130

SECTION_NAME = ".rchrsc"  # 7 chars: the PE name field is 8 bytes and truncates silently
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave is pure code - the patch keeps
# no state of its own, which is the whole point of section 3.1 of the doc.
SECTION_CHARACTERISTICS = 0x60000060

#: Byte windows the patch depends on and does not rewrite, as ``{va: expected bytes}``. The hook
#: window carries the `call` being repointed, which :meth:`~RechargeRescalePatch.verify` blanks
#: before comparing so the same table checks a patched image.
#:
#: They fall into four groups, and every one of them is silent when wrong. The driver windows say
#: the frame gate and the object list are still shaped the way the sweep assumes. The layout
#: windows say the ready frame is still ``+0x08``, the duration still ``+0x04`` and the pause count
#: still ``+0x0C`` - pinned from three independent readers, not from one. The formula windows say
#: the cast-time arithmetic this cave reproduces is still that arithmetic, down to the flag bit and
#: the ``>= 1`` clamp. And the callee windows say each helper still has the convention the cave
#: calls it with - including the one that makes pre-seeding the multiplier necessary.
ANCHORS: dict[int, bytes] = {
    # the hook site in context: `mov ecx,esi; call <gate>; test al,al; je; test bl,bl; jne;
    # inc [esi+0x40]`. Pins the hook, both flags, and the frame increment they gate.
    0x0062E568: bytes.fromhex("8bcee8c16bffff84c0740784db7507ff4640"),
    0x00625130: bytes.fromhex("33c038414474113881a800000075"),  # the gate itself
    # the engine's own walks of the same list: the head at +0xAC and the link at +0x8C
    0x0062E908: bytes.fromhex("8b9eac000000"),
    0x0062E92B: bytes.fromhex("8b9b8c00000085db75db"),
    # `getSpecialPower`: [module+0xC] vtable slot +0x20, the query the sweep copies
    0x008979F5: bytes.fromhex("83c00c8b108bc8ff5220"),
    # the curse fan-out - the canonical NULL-terminated Object+0x24C module walk
    0x0068BDD0: bytes.fromhex(
        "568bb14c020000eb16d94424088d480c8b0151d91c24ff90ac00000083c6048b0685c075e4"
    ),
    # startPowerRecharge, flavour 1: the entry, the SharedSyncedTimer divert, the pre-seeded
    # RECHARGE_TIME query, the flag test and the Player+0x718 fold
    0x00896E31: bytes.fromhex("558bec83ec0c568bf1578b7ef4837f08000f844b010000538b5ef885db0f843e01"),
    0x00896E6C: bytes.fromhex("e8cb1edfff807859007410ff75f48b4d"),
    0x00896E87: bytes.fromhex("f30f10050819bd006a016a008d45f4506a0c8bcbf30f1145f4e88859dfff"),
    0x00896EBA: bytes.fromhex("8b4018c1e805a80174118b4dfce8063ce1ffd8050819bd00d95df8"),
    # ReloadTime at template+0x20, the two multiplies, the ftol and the `>= 1` clamp
    0x00896EE3: bytes.fromhex(
        "8b402085c08945fcdb45fc7d06d8059886bd00d84df8d84df4e8a3601a008bf885ff750147"
    ),
    # the full-recharge stores - readyFrame at +0x08 and duration at +0x04, from one site
    0x00896F75: bytes.fromhex("a12c41de008b404003c78946088b0d2c41de002b4140894604c6461800"),
    # isReady: the pause count at +0x0C and the same ready frame, from a second reader
    0x00896CD4: bytes.fromhex("837e0c007512a12c41de008b40403b4608720533c040eb0233c0"),
    # getPercentReady's denominator - the third reader, and why both fields must move together
    0x00896D8F: bytes.fromhex("8b4604db460485c07d06d8059886bd00def9d82d0819bd00"),
    # flavour 2, and its store at +0x04 - the reason the flavour test exists
    0x00991500: bytes.fromhex("558bec83ec0c568bf1578b7ee0837f08000f840901000053"),
    0x0099161C: bytes.fromhex("8946045b5f5ec9c2"),
    # one vtable of each flavour, at the slot the test reads
    0x00C6502C: struct.pack("<I", START_POWER_RECHARGE),
    0x00C6512C: struct.pack("<I", START_POWER_RECHARGE_ALT),
    # the callees. The first is load-bearing beyond its convention: with no modifier holder it
    # returns *without writing the out-parameter*, which is why the cave seeds it with 1.0f.
    0x0068C82D: bytes.fromhex("e874fcffff85c0750532c0c21000"),
    0x0068C4A6: bytes.fromhex("b82f87b800e8400a3b00f605"),
    0x0068B678: bytes.fromhex("8b891c03000085c97405e9e846110033c0c3"),
    0x00688D3C: bytes.fromhex("8bc18b500485d2740e"),
    0x006AAAD2: bytes.fromhex("d98118070000c3"),
    0x00A3CFA4: bytes.fromhex("558bec83ec2083e4f0d9c0d9542418"),
}


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def _emit_power(a: Asm) -> None:
    """``power(eax = SpecialPowerModuleInterface *, esi = Object *)`` - rescale one cooldown.

    The frame, as displacements from ``ebp``: ``-0x04`` the attribute multiplier and ``-0x08`` the
    player factor (both Reals - the first is what `getModifierMultiplier` writes), ``-0x0C`` the
    template's `ReloadTime`, ``-0x10`` the recomputed duration, ``-0x14`` the stored duration,
    ``-0x18`` the current frame, ``-0x1C`` the frames left, ``-0x20`` the template.

    **The two factors stay in separate slots on purpose.** The stock formula is
    ``fild ReloadTime / fmul <player> / fmul <attribute>`` (``0x00896EEB``..``0x00896EF9``), and
    both multiplies happen in an x87 register - so the intermediate is never rounded to a Real.
    Folding the player factor into the attribute slot first would round it, and a single ULP either
    side of the `ftol` boundary is a duration one frame off the engine's own, which shows up as a
    spurious rescale on the first frame after every cast. Same slots, same order, same rounding.

    Preserves esi and edi, which the two loops above it keep their cursors in. Every early exit
    lands on the same epilogue, and every one of them is a case where this patch has nothing it can
    prove: not on cooldown, paused, the other flavour, a shared timer, or a template that says the
    power recharges in no time at all."""
    a.label("power")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x20")  # sub esp, 0x20
    a.emit(0x53)  # push ebx
    a.emit(b"\x8b\xd8")  # mov ebx, eax                 ; the interface

    # The flavour test. Flavour 2 keeps its ready frame at +0x04 and no duration at all, so
    # writing this layout into one would corrupt it - fail closed on anything unrecognised.
    a.emit(b"\x8b\x03")  # mov eax, [ebx]               ; its vtable
    a.emit(b"\x8b\x40", SPI_VTABLE_RECHARGE_SLOT)  # mov eax, [eax+0x3c]
    a.emit(0x3D, _u32(START_POWER_RECHARGE))  # cmp eax, <startPowerRecharge>
    a.jcc(JNE, "power_out")

    a.emit(0xA1, _u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "power_out")
    a.emit(b"\x8b\x40", GAME_LOGIC_FRAME)  # mov eax, [eax+0x40]          ; now
    a.emit(b"\x89\x45\xe8")  # mov [ebp-0x18], eax           ; now
    a.emit(b"\x3b\x43", SPI_READY_FRAME)  # cmp eax, [ebx+8]
    a.jcc(JAE, "power_out")  # ready, or overdue - nothing to rescale
    a.emit(b"\x83\x7b", SPI_PAUSE_COUNT, 0x00)  # cmp dword [ebx+0xc], 0
    a.jcc(JNE, "power_out")  # paused - 0x00896756 owns the ready frame

    a.emit(b"\x8b\x43", SPI_DURATION)  # mov eax, [ebx+4]             ; the stored duration
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JLE, "power_out")  # never recharged: no multiplier to recover
    a.emit(b"\x89\x45\xec")  # mov [ebp-0x14], eax

    a.emit(b"\x8b\x13")  # mov edx, [ebx]
    a.emit(b"\x8b\xcb")  # mov ecx, ebx
    a.emit(b"\xff\x52", SPI_VTABLE_TEMPLATE_SLOT)  # call [edx+0x18]   ; getSpecialPowerTemplate
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "power_out")
    a.emit(b"\x8b\xc8")  # mov ecx, eax
    a.call_absolute(GET_FINAL_OVERRIDE)  # call getFinalOverride
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "power_out")
    a.emit(b"\x89\x45\xe0")  # mov [ebp-0x20], eax
    a.emit(b"\x80\x78", TEMPLATE_SHARED_SYNCED_TIMER, 0x00)  # cmp byte [eax+0x59], 0
    a.jcc(JNE, "power_out")  # the timer lives on the Player - see the docstring
    a.emit(b"\x8b\x40", TEMPLATE_RELOAD_TIME)  # mov eax, [eax+0x20]   ; ReloadTime, Int frames
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JLE, "power_out")
    a.emit(b"\x89\x45\xf4")  # mov [ebp-0xc], eax            ; ReloadTime

    # `m_now`, computed the way 0x00896E87..0x00896ED2 computes it. The seed is not belt and
    # braces: with no modifier holder on the object, getModifierMultiplier returns having left the
    # out-parameter alone (0x0068C836), so an unseeded slot would be read as stack garbage.
    a.emit(b"\xc7\x45\xfc", _u32(0x3F800000))  # mov dword [ebp-4], 1.0f
    a.emit(b"\xc7\x45\xf8", _u32(0x3F800000))  # mov dword [ebp-8], 1.0f
    a.emit(b"\x6a\x01")  # push 1
    a.emit(b"\x6a\x00")  # push 0
    a.emit(b"\x8d\x45\xfc")  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax
    a.emit(0x6A, RECHARGE_TIME_MODIFIER)  # push 0x0c                     ; RECHARGE_TIME
    a.emit(b"\x8b\xce")  # mov ecx, esi                  ; the Object
    a.call_absolute(GET_MODIFIER_MULTIPLIER)  # call getModifierMultiplier   ; ret 0x10

    a.emit(b"\x8b\x45\xe0")  # mov eax, [ebp-0x20]           ; the template
    a.emit(b"\xf6\x40", TEMPLATE_FLAGS, TEMPLATE_RESPECT_RECHARGE_DISCOUNT)
    a.jcc(JE, "power_no_upgrade")  # not RESPECT_RECHARGE_TIME_DISCOUNT
    a.emit(b"\x8b\xce")  # mov ecx, esi
    a.call_absolute(GET_CONTROLLING_PLAYER)  # call getControllingPlayer
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "power_no_upgrade")
    a.emit(b"\x8b\xc8")  # mov ecx, eax
    a.call_absolute(GET_SPELL_RECHARGE_MODIFIER)  # call <fld [Player+0x718]>
    a.emit(b"\xd8\x05", _u32(ONE_FLOAT))  # fadd dword [1.0f]
    a.emit(b"\xd9\x5d\xf8")  # fstp dword [ebp-8]            ; = 1 + Player[0x718]
    a.label("power_no_upgrade")

    # frames_now = max(1, ftol(ReloadTime * player * attribute)) - the stock instruction sequence,
    # so the comparison below is against exactly what a cast on this frame would have stored.
    a.emit(b"\xdb\x45\xf4")  # fild dword [ebp-0xc]          ; ReloadTime
    a.emit(b"\xd8\x4d\xf8")  # fmul dword [ebp-8]            ; * the player discount
    a.emit(b"\xd8\x4d\xfc")  # fmul dword [ebp-4]            ; * the attribute modifier
    a.call_absolute(FTOL)  # call ftol                     ; pops st(0) -> eax
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JG, "power_have_frames")
    a.emit(0xB8, _u32(1))  # mov eax, 1
    a.label("power_have_frames")
    a.emit(b"\x3b\x45\xec")  # cmp eax, [ebp-0x14]
    a.jcc(JE, "power_out")  # unchanged - the exit almost every power takes
    a.emit(b"\x89\x45\xf0")  # mov [ebp-0x10], eax

    # remaining' = max(1, ftol(remaining * frames_now / duration)). Both terms scale together, so
    # getPercentReady keeps its position and changes only its speed.
    a.emit(b"\x8b\x43", SPI_READY_FRAME)  # mov eax, [ebx+8]
    a.emit(b"\x2b\x45\xe8")  # sub eax, [ebp-0x18]           ; > 0, tested above
    a.emit(b"\x89\x45\xe4")  # mov [ebp-0x1c], eax
    a.emit(b"\xdb\x45\xe4")  # fild dword [ebp-0x1c]
    a.emit(b"\xda\x4d\xf0")  # fimul dword [ebp-0x10]
    a.emit(b"\xda\x75\xec")  # fidiv dword [ebp-0x14]
    a.call_absolute(FTOL)  # call ftol
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JG, "power_have_remaining")
    a.emit(0xB8, _u32(1))  # mov eax, 1
    a.label("power_have_remaining")
    a.emit(b"\x03\x45\xe8")  # add eax, [ebp-0x18]           ; now + remaining'
    a.emit(b"\x89\x43", SPI_READY_FRAME)  # mov [ebx+8], eax
    a.emit(b"\x8b\x45\xf0")  # mov eax, [ebp-0x10]
    a.emit(b"\x89\x43", SPI_DURATION)  # mov [ebx+4], eax

    # ebx comes back from its slot rather than by `pop`, and the frame from `leave`, so the
    # epilogue is correct for any esp - the one failure mode of a routine with this many early
    # exits, and the one nothing downstream would survive.
    a.label("power_out")
    a.emit(b"\x8b\x5d\xdc")  # mov ebx, [ebp-0x24]           ; where the push put it
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret


def _emit_object(a: Asm) -> None:
    """``object(esi = Object *)`` - offer every module's special power to `power`.

    The cursor is a NULL-terminated array of `BehaviorModule *`, walked exactly as ``0x0068BDD0``
    walks it, and the interface comes out of the module's own vtable rather than an assumed offset -
    so a module with no special power costs one indirect call and nothing else."""
    a.label("object")
    a.emit(0x57)  # push edi
    a.emit(b"\x8b\xbe", _u32(OBJECT_MODULES))  # mov edi, [esi+0x24c]
    a.emit(b"\x85\xff")  # test edi, edi
    a.jcc(JE, "object_out")
    a.label("object_loop")
    a.emit(b"\x8b\x07")  # mov eax, [edi]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "object_out")  # the terminator
    a.emit(b"\x8d\x48", MODULE_INTERFACE)  # lea ecx, [eax+0xc]
    a.emit(b"\x8b\x11")  # mov edx, [ecx]
    a.emit(b"\xff\x52", GET_SPECIAL_POWER_SLOT)  # call [edx+0x20]   ; getSpecialPower
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "object_next")
    a.call("power")
    a.label("object_next")
    a.emit(b"\x83\xc7\x04")  # add edi, 4
    a.jmp("object_loop")
    a.label("object_out")
    a.emit(0x5F)  # pop edi
    a.emit(0xC3)  # ret


def _emit_sweep(a: Asm) -> None:
    """``sweep()`` - every object in the logic's own list, once.

    Runs immediately before the frame counter advances, so ``now`` is the frame that is ending.
    Which frame it is does not matter: nothing here accumulates, and the comparison that decides
    whether to act is between two durations."""
    a.label("sweep")
    a.emit(0x56)  # push esi
    a.emit(0xA1, _u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "sweep_out")
    a.emit(b"\x8b\xb0", _u32(GAME_LOGIC_FIRST_OBJECT))  # mov esi, [eax+0xac]
    a.label("sweep_loop")
    a.emit(b"\x85\xf6")  # test esi, esi
    a.jcc(JE, "sweep_out")
    a.call("object")
    a.emit(b"\x8b\xb6", _u32(OBJECT_NEXT))  # mov esi, [esi+0x8c]
    a.jmp("sweep_loop")
    a.label("sweep_out")
    a.emit(0x5E)  # pop esi
    a.emit(0xC3)  # ret


def _emit_tick(a: Asm) -> None:
    """``tick()`` - the hook, standing in for the `call` that gates the frame counter.

    ecx is already `TheGameLogic`, and the caller's ``bl`` is live and initialised on every path
    that reaches this instruction. The sweep runs under exactly the pair that lets ``0x0062E577``
    advance the frame, which is what keeps it in step across peers. ``pushad``/``popad`` carries
    the predicate's own ``al`` back to the caller untouched."""
    a.label("tick")
    a.call_absolute(LOGIC_FRAME_GATE)  # call <gate>       ; ecx already set by the caller
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc_short(JE, "tick_out")  # the frame is not advancing
    a.emit(b"\x84\xdb")  # test bl, bl
    a.jcc_short(JNE, "tick_out")  # nor here
    a.emit(0x60)  # pushad
    a.call("sweep")
    a.emit(0x61)  # popad
    a.label("tick_out")
    a.emit(0xC3)  # ret


def build_section(base_va: int) -> tuple[bytes, int]:
    """``(section content, tick thunk VA)`` for a cave based at ``base_va``.

    One :class:`~...asm.Asm` for all four routines so the internal calls resolve as labels: the
    innermost is emitted first, and only ``tick`` is reachable from outside."""
    a = Asm(base_va)
    _emit_power(a)
    _emit_object(a)
    _emit_sweep(a)
    _emit_tick(a)
    return a.finish(), a.label_va("tick")


class RechargeRescalePatch(Patch):
    """Rescale a cooldown that is already running when its recharge multiplier changes."""

    name = "recharge-rescale"
    author = "officialNecro"
    description = "A running cooldown responds to recharge modifiers granted after the cast"
    experimental = True

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: build_section(va)[0],
            SECTION_CHARACTERISTICS,
        )
        _content, tick_va = build_section(section_va)
        for file_off, old, new, note in self._edits(data, tick_va):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch (an empty list == verified).

        Recomputes the cave and the repointed `call` from the section base found on disk and
        compares them byte for byte, then re-checks every window the patch reads but does not
        rewrite. Reads only via ``struct`` and the section table - no disassembler."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        try:
            content, tick_va = build_section(section_va)
            edits = self._edits(data, tick_va)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(
                f"{SECTION_NAME} does not hold the expected sweep "
                "(the cave differs, or was built for another base address)"
            )
        for file_off, _old, new, note in edits:
            found = bytes(data[file_off : file_off + len(new)])
            if found != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {found.hex()}")

        problems += self._anchor_problems(data, skip_call_bytes=True)
        return problems

    def _edits(self, data: bytes | bytearray, tick_va: int) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites: one ``call rel32`` displacement, and nothing
        else."""
        note = "GameLogic::update's frame gate -> the recharge sweep"
        off = va_to_offset(data, HOOK_CALL_VA)
        if off is None:
            raise ValueError(f"{note}: VA 0x{HOOK_CALL_VA:08x} is not mapped")
        return [
            (
                off,
                _call_bytes(HOOK_CALL_VA, LOGIC_FRAME_GATE),
                _call_bytes(HOOK_CALL_VA, tick_va),
                note,
            )
        ]

    def _anchor_problems(self, data: bytes | bytearray, skip_call_bytes: bool = False) -> list[str]:
        """Everything the patch depends on and does not rewrite; see :data:`ANCHORS`.

        ``skip_call_bytes`` blanks the five bytes of the hooked `call`, which is what lets the same
        table check an already-patched image."""
        problems: list[str] = []
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"anchor 0x{va:08x} is not mapped - not the expected build")
                continue
            got = bytearray(data[off : off + len(expected)])
            want = bytearray(expected)
            at = HOOK_CALL_VA - va
            if skip_call_bytes and 0 <= at <= len(expected) - 5:
                got[at : at + 5] = want[at : at + 5] = b"\x00" * 5
            if bytes(got) != bytes(want):
                problems.append(
                    f"anchor 0x{va:08x}: expected {bytes(want).hex()}, got {bytes(got).hex()}"
                )
        return problems

    def _check_anchors(self, data: bytes | bytearray) -> None:
        problems = self._anchor_problems(data)
        if problems:
            joined = "; ".join(problems)
            raise ValueError(f"recharge-rescale: this is not the expected build: {joined}")
