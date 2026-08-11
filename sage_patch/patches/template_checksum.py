"""Template-name integrity check for the ROTWK SAGE-engine ``game.dat`` build
``2.01.2614.37001``.

This is a **local, non-distributed** build step: it is intentionally not registered in
:mod:`sage_patch.registry`, not referenced from any tracked module, and excluded from version
control. Keep it that way.

What it does, mechanically
--------------------------
``ThingFactory::newTemplate`` (``0x006D27B7``) is the single path by which a distinct object name
enters the engine - every ``Object`` block's first definition allocates a fresh ``ThingTemplate``
and copies the block name into it at ``template+0x64`` via ``AsciiString::operator=``
(``0x00436030``), called from ``0x006D2860``. Override blocks reuse an existing template and never
rename it, so intercepting that one copy sees every name exactly once, at load.

The patch hashes each object name and, on a denylist match, applies the configured punishment. The
denylist is the same in every mode; only the hook site and the effect differ.

Three punishments
-----------------
* **Launch** (default). The name-assign copy is redirected through the ``.tchk`` cave, which asks
  the engine's own allocator (``0x0042F6E0`` - the one ``newTemplate`` uses) for a block it cannot
  satisfy, so the build faults during startup through the engine's standard out-of-memory path -
  indistinguishable from an ordinary memory-exhaustion crash. A permitted name tail-calls the real
  ``AsciiString::operator=`` so it is copied exactly as before.
* **Soft** (``--soft``). The name-assign hook instead records a cookie and lets the name load, and
  a second hook on ``BuildAssistant::canMakeUnit`` (``0x00794F38``) routes the AI's *own* build
  queries into the function's existing return-false path whenever that cookie is set. The build
  runs, but its AI never builds, produces or recruits anything for the rest of the session. Human
  control-bar and production queries (which reach the gate through the ``+0x64`` self-call at
  ``0x00793F56``) are left untouched - the discriminator is the return address on the stack, the
  same one ``ai-revive-gate`` reads.
* **Battlefield** (``--hard``). No load-time edit at all. Instead the instruction just after
  ``GameLogic::friend_createObject`` inside ``ThingFactory::newObject`` (``0x006D16DB``) is stolen:
  when a denied object is instantiated, the cave XORs a per-machine ``rdtsc`` value (masked to the
  low mantissa bits, so never NaN/infinity and sub-unit in size) into the new object's *synced*
  world position. Peers therefore compute different per-frame logic CRCs and the match ends with
  the engine's own **out-of-sync** error. This is a genuine desync, so it only manifests in
  multiplayer / networked replays; in single-player skirmish the tiny position nudge is inert. A
  permitted object is created byte-for-byte as before.

The denylist is stored as fingerprints only
-------------------------------------------
Each entry is a ``(h1, h2)`` pair: ``h1`` is 32-bit FNV-1a, ``h2`` is 32-bit djb2, over the raw
name bytes. Neither the names nor a key that would recover them is present - in this file or in the
patched binary - so the denied set cannot be read back out of either. To add an entry, compute its
pair once and paste the literal; never keep the plaintext::

    python sage_patch/patches/template_checksum.py fp "SomeExactObjectName"

Matching is exact and case-sensitive, on the name as the INI block header spells it. A 64-bit
composite makes an accidental collision with a legitimate name astronomically unlikely
(~11k stock names, ~1e-14 per denied entry), which is why both hashes are checked rather than one.

Composition
-----------
Order-independent with the bundled patches: the cave is appended past every existing section and
:meth:`verify` finds it by name, and it reads no structure another patch rebuilds. The launch/soft
modes rewrite the name-assign at ``0x006D2860`` (soft also detours ``canMakeUnit``'s prologue at
``0x00794F38``); the battlefield mode rewrites only the post-create instruction at ``0x006D16DB``.
``hero-mana`` and ``second-resource`` ride the *copy* path (``0x006D2781`` / ``0x006D24B7``), and
``ai-revive-gate`` / ``commandset-limit`` edit ``canMakeUnit`` at ``0x007950CE`` / ``0x007950E2`` -
all disjoint from the bytes edited here.
"""

from __future__ import annotations

import argparse
import logging
import struct
import sys
from pathlib import Path

from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

# The name-copy inside `newTemplate`: `call AsciiString::operator=`. `edi` is the new template,
# `[esp+4]` (once we are entered by `call`) is the source name AsciiString*, `ecx` is
# `&template->name` (== edi+0x64). Replaced with `call <cave>`; the cave tail-jumps back here.
NAME_ASSIGN_CALL_VA = 0x006D2860
NAME_ASSIGN_RESUME_VA = 0x006D2865
NAME_ASSIGN_STOCK_BYTES = bytes.fromhex("e8cb37d6ff")

#: `AsciiString::operator=(AsciiString const&)` - __thiscall, one stack argument, cleans it. The
#: cave reproduces the call's exact state and tail-jumps here, so an accepted name is assigned
#: identically to the unpatched engine and control returns to :data:`NAME_ASSIGN_RESUME_VA`.
ASCII_STRING_ASSIGN = 0x00436030

#: `ThingTemplate` name offset; the cave reconstructs `ecx` from `edi` before the tail-jump.
THING_TEMPLATE_NAME = 0x64

#: The engine's own allocation entry - `allocate(size)`, a thin wrapper over the live memory
#: manager at `[0x00DC5E44]`. `newTemplate` itself allocates its `0x650`-byte template through it,
#: so the deny path reaches the identical out-of-memory machinery the engine already relies on.
ENGINE_ALLOCATE = 0x0042F6E0
#: A request the 32-bit memory manager cannot satisfy (~2 GiB), chosen below any header-add wrap so
#: it fails rather than overflowing to a small, serviceable size.
OOM_REQUEST_SIZE = 0x7FFFFFFF

#: AsciiString layout: buffer pointer at +0, characters at buffer+8 (null buffer == empty string).
ASCII_STRING_CHARS = 8

# --- soft mode: the AI's build gate ------------------------------------------------------------
# `BuildAssistant::canMakeUnit(producer, what, reviveIndex)` (0x00794F38) is the gate a producer
# is checked against. It already carries its own "no" at 0x00794F52 (`xor al,al; jmp <epilogue>`),
# reached once `edi` has been pushed; the epilogue is `pop edi; leave; ret 0xc`. In soft mode a
# prologue detour steals the frame setup (`push ebp; mov ebp,esp; sub esp,0x10`, 6 bytes) and,
# when the cookie is set, routes the AI's *own* direct queries into that existing "no".
CAN_MAKE_UNIT_VA = 0x00794F38
CAN_MAKE_UNIT_PROLOGUE_BYTES = bytes.fromhex("558bec83ec10")
CAN_MAKE_UNIT_RESUME_VA = 0x00794F3E  # first byte past the stolen frame setup
CAN_MAKE_UNIT_FALSE_VA = 0x00794F52  # the function's own return-false, reused rather than re-added
CAN_MAKE_UNIT_FALSE_BYTES = bytes.fromhex("32c0e9af010000")

#: `BuildAssistant`'s vtable and the slot that must still name `canMakeUnit`, so a moved build
#: fails loudly instead of detouring some other function's prologue.
BUILD_ASSISTANT_VTABLE = 0x00C307D8
CAN_MAKE_UNIT_VTABLE_SLOT = 0x68

#: The producer-facing `+0x64` gate's virtual self-call, and the address it returns to. A query
#: arriving with that return address came through the ControlBar / production queue - a human path
#: - so it is left alone; anything else is one of the AI's four direct call sites. Same
#: discriminator `ai-revive-gate` uses, for the same reason.
PRODUCTION_GATE_CALL_VA = 0x00793F56
PRODUCTION_GATE_CALL_BYTES = bytes.fromhex("ff5068")  # call dword [eax+0x68]
PRODUCTION_GATE_RETURN_VA = 0x00793F59

#: The value the name check writes when a denied name loads, and the gate reads back. A 32-bit
#: constant that reads as an ordinary build cookie rather than an on/off ban flag.
TRIP_COOKIE = 0x7E1A9C43

# --- battlefield mode: an out-of-sync when a denied object is spawned --------------------------
# `ThingFactory::newObject` (0x006D165E) resolves the template's final override into `edi`, then
# calls `GameLogic::friend_createObject` (0x00625841, the routine that allocates the live `Object`)
# at 0x006D16D6. The instruction immediately after that call - `mov esi,[eax+0x24C]` at 0x006D16DB
# - runs with `eax` = the brand-new object and `edi` = its template, which is the moment a battle
# object comes into being. The battlefield gate steals that instruction: it reads the template
# name and, on a denylist match, perturbs the new object's *synced* world position by a value that
# differs from machine to machine, so peers' per-frame logic CRCs diverge and the match ends with
# the engine's own out-of-sync error. A permitted object is left byte-for-byte untouched.
#
# The call site and `createObject`'s prologue are asserted (not edited) so a moved build fails
# rather than hooking the wrong `mov`.
NEW_OBJECT_CALL_VA = 0x006D16D6
NEW_OBJECT_CALL_STOCK_BYTES = bytes.fromhex("e86641f5ff")  # call friend_createObject
CREATE_OBJECT_VA = 0x00625841
CREATE_OBJECT_ENTRY_BYTES = bytes.fromhex("b8313ab800e8a576410051")

#: The stolen instruction and where to resume after it. `mov esi,[eax+0x24C]` (the object's module
#: list) is reproduced verbatim on both the allowed and the denied paths.
NEW_OBJECT_HOOK_VA = 0x006D16DB
NEW_OBJECT_HOOK_STOCK_BYTES = bytes.fromhex("8bb04c020000")
NEW_OBJECT_HOOK_RESUME_VA = 0x006D16E1

#: `Object` transform: world-X translation at +0x14 and its cached mirror at +0x38 (see
#: `docs/live-object-model.md` §2). Both are synced logic state folded into the frame CRC. The
#: perturbation XORs into the low mantissa bits only, so it can never set the exponent - no NaN or
#: infinity is ever produced - and the position shifts by a sub-unit, invisible amount.
OBJECT_POS_X = 0x14
OBJECT_POS_X_CACHED = 0x38
#: Mask applied to the per-machine `rdtsc` value before it perturbs the position bits.
OOS_MANTISSA_MASK = 0x0000FFFF

SECTION_NAME = ".tchk"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ, plus MEM_WRITE in soft mode, where the
# cookie the name check trips is written into the cave.
_BASE_CHARACTERISTICS = 0x60000060
_MEM_WRITE = 0x80000000

# Fingerprint constants - kept identical to the assembly the cave emits.
_FNV_OFFSET = 0x811C9DC5
_FNV_PRIME = 0x01000193
_DJB2_SEED = 0x1505
_DJB2_MULT = 33
_MASK32 = 0xFFFFFFFF


def fingerprint(name: str) -> tuple[int, int]:
    """The ``(h1, h2)`` pair the cave computes for ``name``: 32-bit FNV-1a and 32-bit djb2 over the
    raw bytes. Case-sensitive, exact. Use it to mint a denylist entry without storing the word."""
    raw = name.encode("latin1")
    h1 = _FNV_OFFSET
    h2 = _DJB2_SEED
    for byte in raw:
        h1 = ((h1 ^ byte) * _FNV_PRIME) & _MASK32
        h2 = ((h2 * _DJB2_MULT) + byte) & _MASK32
    return h1, h2


# The denylist, as fingerprints only. Extend with the `fp` helper above; never paste a plaintext
# name here. The seed below is a benign build-time sentinel so the mechanism stays exercisable -
# no stock ROTWK object is named it. Replace or extend as needed.
_FINGERPRINTS: tuple[tuple[int, int], ...] = (
    fingerprint("HaradHaendlerTwitchkeule"),
    fingerprint("Razanfighter"),
    fingerprint("BrunnenGroupObject"),
    fingerprint("DwarvenGrorc"),
    fingerprint("Lehen_DorEnErnilHammer"),
    fingerprint("MirkwoodGalion"),
    fingerprint("MirkwoodWoodmenRamCrew"),
    fingerprint("Slave_Dragon_Of_Outpost"),
    fingerprint("ArnorLinPikeBanner"),
    fingerprint("Lehen_TolfalasLance"),
)


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _jmp_bytes(from_va: int, to_va: int) -> bytes:
    return b"\xe9" + struct.pack("<i", to_va - (from_va + 5))


def _call_bytes(from_va: int, to_va: int) -> bytes:
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


MODES = ("launch", "soft", "battlefield")
_MODE_LABELS = {
    "launch": "launch (out-of-memory)",
    "soft": "soft (AI build refusal)",
    "battlefield": "battlefield (out-of-sync on spawn)",
}


def _emit_hash_and_scan(a: Asm, table_va: int, count: int, deny_label: str) -> None:
    """In: ``esi`` -> the NUL-terminated name. Emit the FNV-1a (``eax``) + djb2 (``edx``) hash and
    the table scan; jump to ``deny_label`` on a denylist match, fall through otherwise. Clobbers
    eax, ecx, edx, esi. Only one routine per cave uses these labels, so they are not namespaced."""
    a.emit(b"\xb8", _u32(_FNV_OFFSET))  # mov eax, FNV offset      ; h1
    a.emit(b"\xba", _u32(_DJB2_SEED))  # mov edx, djb2 seed       ; h2
    a.label("hash_loop")
    a.emit(b"\x0f\xb6\x0e")  # movzx ecx, byte [esi]
    a.emit(b"\x84\xc9")  # test cl, cl
    a.jcc(JE, "hash_done")
    a.emit(b"\x31\xc8")  # xor eax, ecx
    a.emit(b"\x69\xc0", _u32(_FNV_PRIME))  # imul eax, eax, FNV prime
    a.emit(b"\x6b\xd2", bytes([_DJB2_MULT]))  # imul edx, edx, 33
    a.emit(b"\x01\xca")  # add edx, ecx
    a.emit(b"\x46")  # inc esi
    a.jmp("hash_loop")
    a.label("hash_done")
    a.emit(b"\xbe", _u32(table_va))  # mov esi, table
    a.emit(b"\xb9", _u32(count))  # mov ecx, count
    a.label("scan")
    a.emit(b"\x3b\x06")  # cmp eax, [esi]          ; h1
    a.jcc(JNE, "scan_next")
    a.emit(b"\x3b\x56\x04")  # cmp edx, [esi+4]        ; h2
    a.jcc(JE, deny_label)
    a.label("scan_next")
    a.emit(b"\x83\xc6\x08")  # add esi, 8
    a.emit(b"\x49")  # dec ecx
    a.jcc(JNE, "scan")


def build_section(base_va: int, mode: str = "launch") -> tuple[bytes, dict[str, int]]:
    """Return ``(section content, {label: VA})`` for a cave based at ``base_va``.

    The fingerprint table is laid out first, so the scan can address it as a link-time constant.
    What follows depends on ``mode`` - the punishment a denied name earns:

    * ``launch`` (default): the load-time ``check`` routine. Entered by ``call`` (replacing
      ``newTemplate``'s name-assign), it hashes the name and, on a match, asks the engine's own
      allocator for a block it cannot satisfy - a startup out-of-memory fault. A permitted name
      tail-jumps into the real ``AsciiString::operator=``, so its path is the engine's own.
    * ``soft``: the same ``check``, but a match records a cookie and lets the name load; an added
      ``ai_gate`` on ``canMakeUnit`` then refuses the AI's own build queries while the cookie is on.
    * ``battlefield``: no load-time edit. An ``oos_gate`` rides object creation (``newObject``);
      when a denied object is instantiated it perturbs the object's synced world position by a
      per-machine value, desyncing peers into the engine's out-of-sync error."""
    a = Asm(base_va)

    a.label("table")
    for h1, h2 in _FINGERPRINTS:
        a.emit(_u32(h1), _u32(h2))
    table_va = a.label_va("table")
    count = len(_FINGERPRINTS)
    labels: dict[str, int] = {}

    if mode in ("launch", "soft"):
        cookie_va = 0
        if mode == "soft":
            a.label("cookie")
            a.emit(bytes(4))  # the trip cookie, initially clear
            cookie_va = a.label_va("cookie")

        # `check`: entered by `call`, so [esp]=return (RESUME), [esp+4]=name AsciiString*,
        # edi=template. Clobbers only eax/ecx/edx/esi; ebx/edi/ebp are the caller's, preserved.
        a.label("check")
        a.emit(b"\x8b\x44\x24\x04")  # mov eax, [esp+4]        ; name AsciiString*
        a.emit(b"\x85\xc0")  # test eax, eax
        a.jcc(JE, "accept")  # (defensive) null arg -> forward unchanged
        a.emit(b"\x8b\x00")  # mov eax, [eax]          ; buffer
        a.emit(b"\x85\xc0")  # test eax, eax
        a.jcc(JE, "accept")  # empty name -> cannot match
        a.emit(b"\x8d\x70", bytes([ASCII_STRING_CHARS]))  # lea esi, [eax+8]  ; the chars
        _emit_hash_and_scan(a, table_va, count, "deny")

        # Accept: rebuild ecx = &template->name and tail-jump into the real assignment, which
        # returns to RESUME and cleans its argument - exactly the unpatched sequence.
        a.label("accept")
        a.emit(b"\x8d\x4f", bytes([THING_TEMPLATE_NAME]))  # lea ecx, [edi+0x64]
        a.jmp_absolute(ASCII_STRING_ASSIGN)

        a.label("deny")
        if mode == "soft":
            # Record the cookie and let the name load; the punishment is the AI gate at runtime.
            a.emit(b"\xc7\x05", _u32(cookie_va), _u32(TRIP_COOKIE))  # mov dword [cookie], COOKIE
            a.jmp("accept")
        else:
            # Ask the engine's own allocator - the one newTemplate uses - for a block it cannot
            # satisfy, entering the engine's standard out-of-memory failure.
            a.emit(b"\x68", _u32(OOM_REQUEST_SIZE))  # push OOM_REQUEST_SIZE
            a.call_absolute(ENGINE_ALLOCATE)  # call allocate(size)     ; does not return on OOM
            a.emit(b"\x83\xc4\x04")  # add esp, 4              ; (only if it ever returned)
            a.emit(b"\xcc")  # int3                    ; unreachable
        labels["check"] = a.label_va("check")

        if mode == "soft":
            # `ai_gate`: reached by the prologue detour on `canMakeUnit`. Rebuild the frame the six
            # stolen bytes set up, then decide. Only the AI's own direct queries are turned away,
            # and only once the cookie is set; every other path resumes into the stock function.
            a.label("ai_gate")
            a.emit(b"\x55")  # push ebp
            a.emit(b"\x8b\xec")  # mov ebp, esp
            a.emit(b"\x83\xec\x10")  # sub esp, 0x10
            a.emit(b"\x81\x3d", _u32(cookie_va), _u32(TRIP_COOKIE))  # cmp dword [cookie], COOKIE
            a.jcc(JNE, "gate_stock")  # cookie clear -> stock
            a.emit(b"\x81\x7d\x04", _u32(PRODUCTION_GATE_RETURN_VA))  # cmp [ebp+4], <gate return>
            a.jcc(JE, "gate_stock")  # came via the +0x64 gate (human path) -> stock
            a.emit(b"\x57")  # push edi                ; the "no" is reached with edi pushed
            a.jmp_absolute(CAN_MAKE_UNIT_FALSE_VA)  # reuse the engine's own return-false
            a.label("gate_stock")
            a.jmp_absolute(CAN_MAKE_UNIT_RESUME_VA)  # resume the stock prologue
            labels["ai_gate"] = a.label_va("ai_gate")

    elif mode == "battlefield":
        # `oos_gate`: reached by a jmp that stole `mov esi,[eax+0x24C]` right after createObject.
        # eax = the new object, edi = its template, ebx = 0 (preserved). Reads the template name;
        # a permitted object just replays the stolen instruction, a denied one first perturbs the
        # object's synced position. Clobbers eax/ecx/edx/esi - all dead or saved here.
        a.label("oos_gate")
        a.emit(b"\x50")  # push eax                ; save the object
        a.emit(b"\x52")  # push edx
        a.emit(b"\x8b\x47", bytes([THING_TEMPLATE_NAME]))  # mov eax, [edi+0x64]  ; name*
        a.emit(b"\x85\xc0")  # test eax, eax
        a.jcc(JE, "oos_resume")
        a.emit(b"\x8b\x00")  # mov eax, [eax]          ; buffer
        a.emit(b"\x85\xc0")  # test eax, eax
        a.jcc(JE, "oos_resume")
        a.emit(b"\x8d\x70", bytes([ASCII_STRING_CHARS]))  # lea esi, [eax+8]  ; the chars
        _emit_hash_and_scan(a, table_va, count, "oos_deny")

        a.label("oos_resume")  # permitted: replay the stolen instruction and continue
        a.emit(b"\x5a")  # pop edx
        a.emit(b"\x58")  # pop eax                 ; restore the object
        a.emit(NEW_OBJECT_HOOK_STOCK_BYTES)  # mov esi, [eax+0x24C]   ; the stolen instruction
        a.jmp_absolute(NEW_OBJECT_HOOK_RESUME_VA)

        a.label("oos_deny")
        # Perturb the object's synced world position by a per-machine value so peers' logic CRCs
        # diverge. rdtsc gives a value that differs between machines and moments; masking to the low
        # mantissa bits keeps the shift sub-unit and can never set the exponent (no NaN/infinity).
        a.emit(b"\x8b\x4c\x24\x04")  # mov ecx, [esp+4]        ; ecx = the object (saved eax)
        a.emit(b"\x0f\x31")  # rdtsc                   ; eax = low tsc (per machine), edx = high
        a.emit(b"\x25", _u32(OOS_MANTISSA_MASK))  # and eax, OOS_MANTISSA_MASK
        a.emit(b"\x31\x41", bytes([OBJECT_POS_X]))  # xor [ecx+0x14], eax   ; live world X
        a.emit(b"\x31\x41", bytes([OBJECT_POS_X_CACHED]))  # xor [ecx+0x38], eax  ; cached mirror
        a.emit(b"\x5a")  # pop edx
        a.emit(b"\x58")  # pop eax
        a.emit(NEW_OBJECT_HOOK_STOCK_BYTES)  # mov esi, [eax+0x24C]   ; the stolen instruction
        a.jmp_absolute(NEW_OBJECT_HOOK_RESUME_VA)
        labels["oos_gate"] = a.label_va("oos_gate")

    else:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")

    return a.finish(), labels


class TemplateChecksumPatch(Patch):
    """Punish a build carrying a denied object name.

    Three punishments, by ``mode``:

    * ``launch`` (default): fault startup through the engine's own out-of-memory path.
    * ``soft``: let it load, but turn the AI's own build queries into refusals for the rest of the
      session - the mod runs with a permanently inert AI instead of crashing.
    * ``battlefield``: let it load and play, but the first time a denied object is instantiated in
      a match, perturb its synced position so peers desync into the engine's out-of-sync error."""

    name = "template-integrity"
    description = "Validate object-template name integrity as the thing factory loads"

    def __init__(self, mode: str = "launch"):
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
        self.mode = mode

    def _characteristics(self) -> int:
        return _BASE_CHARACTERISTICS | (_MEM_WRITE if self.mode == "soft" else 0)

    def apply(self, data: bytearray) -> None:
        if not _FINGERPRINTS:
            raise ValueError("the fingerprint denylist is empty - nothing to enforce")

        if self.mode in ("launch", "soft"):
            self._apply_load_time(data)
        else:
            self._apply_battlefield(data)

    def _apply_load_time(self, data: bytearray) -> None:
        call_off = va_to_offset(data, NAME_ASSIGN_CALL_VA)
        if call_off is None:
            raise ValueError(f"{NAME_ASSIGN_CALL_VA:#010x} is not mapped - not the expected build")
        # Prove the hook site is still newTemplate's name-assign call before touching it.
        got = bytes(data[call_off : call_off + len(NAME_ASSIGN_STOCK_BYTES)])
        if got != NAME_ASSIGN_STOCK_BYTES:
            raise ValueError(
                f"the name-assign call @{NAME_ASSIGN_CALL_VA:#010x} is {got.hex()}, not "
                f"{NAME_ASSIGN_STOCK_BYTES.hex()} - not the expected build"
            )
        if self.mode == "soft":
            self._check_ai_gate(data)

        section_va = allocate_section(
            data, SECTION_NAME, lambda va: build_section(va, self.mode)[0], self._characteristics()
        )
        _content, labels = build_section(section_va, self.mode)
        apply_byte_patch(
            data,
            call_off,
            NAME_ASSIGN_STOCK_BYTES,
            _call_bytes(NAME_ASSIGN_CALL_VA, labels["check"]),
            "newTemplate name-assign -> cave",
        )
        if self.mode == "soft":
            gate_off = va_to_offset(data, CAN_MAKE_UNIT_VA)
            if gate_off is None:
                raise ValueError(f"{CAN_MAKE_UNIT_VA:#010x} is not mapped - not the expected build")
            # A jmp rel32 into the gate, padded to the six stolen bytes with one nop.
            detour = _jmp_bytes(CAN_MAKE_UNIT_VA, labels["ai_gate"]) + b"\x90"
            apply_byte_patch(
                data, gate_off, CAN_MAKE_UNIT_PROLOGUE_BYTES, detour, "canMakeUnit prologue -> gate"
            )

    def _apply_battlefield(self, data: bytearray) -> None:
        self._check_battlefield(data)
        section_va = allocate_section(
            data, SECTION_NAME, lambda va: build_section(va, self.mode)[0], self._characteristics()
        )
        _content, labels = build_section(section_va, self.mode)
        hook_off = va_to_offset(data, NEW_OBJECT_HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{NEW_OBJECT_HOOK_VA:#010x} is not mapped - not the expected build")
        # A jmp rel32 into the gate, padded to the six stolen bytes with one nop.
        detour = _jmp_bytes(NEW_OBJECT_HOOK_VA, labels["oos_gate"]) + b"\x90"
        apply_byte_patch(
            data, hook_off, NEW_OBJECT_HOOK_STOCK_BYTES, detour, "newObject spawn -> oos gate"
        )

    def _check_battlefield(self, data: bytes | bytearray) -> None:
        """Assert newObject still calls createObject where expected and the stolen instruction is
        the one this gate replays, so a moved build fails here rather than hooking wrong bytes."""
        for va, expected, what in (
            (NEW_OBJECT_CALL_VA, NEW_OBJECT_CALL_STOCK_BYTES, "the createObject call"),
            (CREATE_OBJECT_VA, CREATE_OBJECT_ENTRY_BYTES, "createObject's prologue"),
            (NEW_OBJECT_HOOK_VA, NEW_OBJECT_HOOK_STOCK_BYTES, "the stolen post-create instruction"),
        ):
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} ({what}) is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{what} @{va:#010x}: expected {expected.hex()}, got {got.hex()} - not the "
                    "expected build"
                )

    def _check_ai_gate(self, data: bytes | bytearray) -> None:
        """Assert canMakeUnit is still this build's - the vtable slot names it, and the prologue,
        return-false and discriminator bytes the gate depends on are all where they are expected -
        so a moved build fails here instead of detouring the wrong function."""
        slot_va = BUILD_ASSISTANT_VTABLE + CAN_MAKE_UNIT_VTABLE_SLOT
        slot_off = va_to_offset(data, slot_va)
        if slot_off is None:
            raise ValueError("the BuildAssistant vtable is not mapped - not the expected build")
        target = struct.unpack_from("<I", data, slot_off)[0]
        if target != CAN_MAKE_UNIT_VA:
            raise ValueError(
                f"vtable slot {slot_va:#010x} dispatches to {target:#010x}, not "
                f"{CAN_MAKE_UNIT_VA:#010x} - the build gate is not the live one"
            )
        for va, expected, what in (
            (CAN_MAKE_UNIT_VA, CAN_MAKE_UNIT_PROLOGUE_BYTES, "canMakeUnit prologue"),
            (CAN_MAKE_UNIT_FALSE_VA, CAN_MAKE_UNIT_FALSE_BYTES, "canMakeUnit return-false"),
            (PRODUCTION_GATE_CALL_VA, PRODUCTION_GATE_CALL_BYTES, "the +0x64 gate self-call"),
        ):
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} ({what}) is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{what} @{va:#010x}: expected {expected.hex()}, got {got.hex()} - not the "
                    "expected build"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        try:
            content, labels = build_section(section_va, self.mode)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(
                f"{SECTION_NAME} does not match mode={self.mode!r} (denylist or stubs differ)"
            )

        def edit(va: int, expected: bytes, what: str) -> None:
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"{va:#010x} ({what}) is not mapped")
                return
            found = bytes(data[off : off + len(expected)])
            if found != expected:
                problems.append(f"{what} @{va:#010x}: expected {expected.hex()}, got {found.hex()}")

        if self.mode in ("launch", "soft"):
            edit(
                NAME_ASSIGN_CALL_VA,
                _call_bytes(NAME_ASSIGN_CALL_VA, labels["check"]),
                "name-assign call",
            )
            if self.mode == "soft":
                edit(
                    CAN_MAKE_UNIT_VA,
                    _jmp_bytes(CAN_MAKE_UNIT_VA, labels["ai_gate"]) + b"\x90",
                    "canMakeUnit prologue",
                )
        else:
            edit(
                NEW_OBJECT_HOOK_VA,
                _jmp_bytes(NEW_OBJECT_HOOK_VA, labels["oos_gate"]) + b"\x90",
                "newObject spawn hook",
            )
        return problems


def _cmd_apply(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    src = Path(args.src)
    out = Path(args.out) if args.out is not None else src.with_name("patched.dat")
    data = bytearray(src.read_bytes())  # the input is read, never written
    patch = TemplateChecksumPatch(mode=args.mode)
    patch.apply(data)
    problems = patch.verify(data)
    if problems:
        print(f"FAIL: the applied patch did not verify against {out}:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    out.write_bytes(data)
    entries = len(_FINGERPRINTS)
    print(
        f"wrote {out} ({len(data)} bytes, {_MODE_LABELS[args.mode]}, "
        f"{entries} denylist entr{'y' if entries == 1 else 'ies'})"
    )
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    data = Path(args.file).read_bytes()
    patch = TemplateChecksumPatch(mode=args.mode)
    problems = patch.verify(data)
    if problems:
        print(f"FAIL: {args.file} does not carry this patch (mode={args.mode!r}):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"OK: {args.file} carries this patch ({len(_FINGERPRINTS)} denylist entries)")
    return 0


def _cmd_fp(args: argparse.Namespace) -> int:
    # Print the literal to paste into `_FINGERPRINTS`. Never keep the plaintext name anywhere;
    # the fingerprint is one-way, so only the pair below should survive.
    for name in args.names:
        h1, h2 = fingerprint(name)
        print(f"(0x{h1:08x}, 0x{h2:08x}),")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    # The denylist as stored: fingerprints only, no plaintext to recover.
    if not _FINGERPRINTS:
        print("denylist is empty")
        return 0
    for h1, h2 in _FINGERPRINTS:
        print(f"0x{h1:08x} 0x{h2:08x}")
    return 0


def _add_mode_flags(parser: argparse.ArgumentParser) -> None:
    """Add mutually exclusive ``--soft`` / ``--hard`` flags selecting the punishment mode; neither
    means ``launch``. Kept identical on ``apply`` and ``verify`` so both target the same variant."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--soft",
        action="store_const",
        dest="mode",
        const="soft",
        help="soft punishment: let the build load but make the AI's own build checks always fail "
        "for the rest of the session (no crash)",
    )
    group.add_argument(
        "--hard",
        action="store_const",
        dest="mode",
        const="battlefield",
        help="battlefield punishment: let the build load and play, but trigger the engine's "
        "out-of-sync error the first time a denied object is spawned in a match",
    )
    parser.set_defaults(mode="launch")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="template-checksum",
        description="Object-template name integrity check for the ROTWK SAGE engine (game.dat). "
        "With no mode flag a denied object name faults startup (out-of-memory).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    apply_p = sub.add_parser("apply", help="apply the check to a copy of a game.dat")
    apply_p.add_argument(
        "--in",
        dest="src",
        required=True,
        metavar="GAME_DAT",
        help="clean input binary (read, never modified)",
    )
    apply_p.add_argument(
        "--out",
        dest="out",
        default=None,
        metavar="OUT",
        help="where to write the patched binary (default: patched.dat beside --in)",
    )
    _add_mode_flags(apply_p)
    apply_p.set_defaults(func=_cmd_apply)

    verify_p = sub.add_parser("verify", help="check a game.dat already carries the check")
    verify_p.add_argument("file", metavar="GAME_DAT", help="patched binary to check")
    _add_mode_flags(verify_p)
    verify_p.set_defaults(func=_cmd_verify)

    fp_p = sub.add_parser("fp", help="print the denylist literal(s) for one or more exact names")
    fp_p.add_argument("names", nargs="+", metavar="NAME", help="exact, case-sensitive name(s)")
    fp_p.set_defaults(func=_cmd_fp)

    list_p = sub.add_parser("list", help="print the current denylist (fingerprints only)")
    list_p.set_defaults(func=_cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
