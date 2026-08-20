"""The binary-attest patch: fold a hash of the game's own code into the frame checksum, so that
a peer running a modified `game.dat` desyncs instead of playing.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/binary-attest.md``.

**The gap it closes, stated precisely.** Fog of war is *already* in the sync hash: the CRC
producer at ``0x00625886`` xfers ``TheShroudManager`` into the frame checksum alongside every
other logic subsystem, guarded only by the ``-xShroudCRC`` debug flag. So a client whose shroud
*state* diverges - one that writes revealer counts into the grid, the way a memory-editor
maphack does - already goes out of sync against honest peers with no help from this patch.

What that does **not** cover is a client whose shroud state agrees perfectly because nothing
about the simulation was touched. The engine decides visibility with
``0x00B4FAB0``, which computes "not visible" and then collapses it to "visible" when the fog
byte at ``ShroudImpl+0x68`` is clear; the draw path consults that answer rather than producing
it. Flip that byte, or take the branch out of the renderer, and every shroud level in the grid
is byte-for-byte what an honest client holds. The state hash cannot see it, because the state
did not change - only the code did.

**What it does.** Appends an ``.attest`` PE section holding a hash slot plus a routine, and takes
over the six bytes at the ``MSG_LOGIC_CRC`` emitter's join point (``0x0062E7FD``). The routine
hashes the image's own executable bytes once, caches the result, and XORs it into the CRC value
in ``edi`` before the engine appends it to the message. Two clients whose code differs by a
single byte therefore publish different checksums from their first heartbeat, and the engine's
existing out-of-sync machinery - the ``0x44A`` heartbeat every ``REPLAY_CRC_INTERVAL`` frames,
the ``GameCRCMismatch`` message, the replay header's desync flag - does the rest. No new message
type, no new wire format, nothing for a peer to opt into beyond running the same binary.

**What is hashed.** Two ranges: the whole of ``.text``, and this section's own code. The image
carries no ``.reloc`` and does not set ``DYNAMIC_BASE``, so the loader maps ``.text`` at
``IMAGE_BASE`` and never rewrites a byte of it - the code in memory is the code in the file,
which is what makes :func:`expected_hash` able to recompute the runtime value offline from the
patched file. Including the cave's own code means an attacker who wants the honest value back
has to edit the routine that computes it rather than nop a branch somewhere in ``.text``.

**Playback is exempt, and cannot be abused to evade.** When ``TheRecorder``'s mode reads
``PLAYBACK`` the routine leaves ``edi`` alone, so a replay recorded on any build still plays back
against its own recorded checksums and ``sage_verify`` can follow one on an attested client. A
cheater cannot use that to suppress the mix in a live game: a client that skipped it would
publish an unmixed checksum while its peers published mixed ones, which is the same desync by
the other route.

**Honest limits, because this is anti-tamper and anti-tamper oversells itself.** The hash is
computed by the client it is attesting. Whoever can patch the fog branch can patch this routine
to return the value an honest build would produce; it is one more edit, not a wall. What the
patch buys is that the edit is *necessary* - every code-level cheat, not just fog, now has to be
paired with a second edit inside a routine that is deliberately awkward to skip - and that a
casually modified binary fails immediately and visibly rather than playing on undetected. It
buys nothing at all against an external overlay process that only reads memory, because lockstep
hands every client the whole object table and nothing in the game's own code has to change for
someone to draw it on a second monitor. See ``../docs/binary-attest.md`` section 6.

**Composition.** Order-independent in the framework's sense: the cave is allocated past every
existing section and :meth:`verify` finds it by name, and the only engine bytes it edits are the
six at ``0x0062E7FD``, which no other bundled patch touches. It is **not** value-independent, and
that is deliberate: the hash covers ``.text``, so applying any other patch changes it, and
applying the same set of patches in a different order moves this section and changes it again.
Peers must run the byte-identical file, which is the property being enforced.

Section layout, at the base::

    +0x00  ready        dword  0 until the hash has been computed
    +0x04  hash         dword  the cached attestation value
    +0x08  pad
    +0x10  code                <- hashed, through to SECTION_LEN
"""

from __future__ import annotations

import struct

from ..addresses import (
    LOGIC_CRC_EMIT,
    LOGIC_CRC_EMIT_BYTES,
    LOGIC_CRC_EMIT_RESUME,
    LOGIC_CRC_SHROUD_XFER,
    LOGIC_CRC_SHROUD_XFER_BYTES,
    RECORDER_MODE,
    RECORDER_MODE_PLAYBACK,
    TEXT_SECTION_LEN,
    TEXT_SECTION_VA,
    THE_RECORDER,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, image_sections, va_to_offset

__all__ = [
    "CODE_OFF",
    "FNV_OFFSET_BASIS",
    "FNV_PRIME",
    "HASH_OFF",
    "READY_OFF",
    "SECTION_LEN",
    "SECTION_NAME",
    "BinaryAttestPatch",
    "build_section",
    "expected_hash",
]

SECTION_NAME = ".attest"

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ | MEM_WRITE - the routine caches its result in the
# section, so the cave cannot be read-only.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000 | 0x80000000

READY_OFF = 0x00
HASH_OFF = 0x04
CODE_OFF = 0x10

#: The section's total size, fixed rather than derived from the code length. The routine hashes
#: its own code range and therefore has to carry that range's end as an immediate - which would
#: be circular if the end depended on how long the code turned out to be. Pinning the size makes
#: the constant knowable before the body is laid out, and the tail padding is zeros either way.
SECTION_LEN = 0x200

# FNV-1a over 32-bit words. Chosen for the shape of its inner loop rather than its statistics:
# `xor eax, [esi]` + `imul eax, eax, prime` is two instructions with a carried dependency, so
# there is no table to place in the cave and no way to compensate for an edit by adjusting bytes
# elsewhere the way a plain additive sum invites.
FNV_OFFSET_BASIS = 0x811C9DC5
FNV_PRIME = 0x01000193

_MASK = 0xFFFFFFFF


def _fold(digest: int, blob: bytes) -> int:
    """FNV-1a over ``blob`` read as little-endian 32-bit words, exactly as the cave folds it."""
    if len(blob) % 4:
        raise ValueError(f"attested ranges are whole dwords; got {len(blob)} bytes")
    for (word,) in struct.iter_unpack("<I", blob):
        digest = ((digest ^ word) * FNV_PRIME) & _MASK
    return digest


def expected_hash(data: bytes | bytearray) -> int:
    """The value a patched ``game.dat`` will compute at runtime, recomputed from the file.

    This is the whole point of hashing a range the loader does not rewrite: the attestation value
    is not a secret held only by a running process, it is a property of the file, so two people
    can compare binaries without either of them playing a game. `sage-patch attest` prints it,
    and `sage_verify` reads the live one out of a running process to check the two agree.

    Raises ``ValueError`` if ``data`` does not carry the patch, because the honest answer to
    "what will this file attest to" for an unpatched file is not a number.
    """
    located = find_section(data, SECTION_NAME)
    if located is None:
        raise ValueError(f"{SECTION_NAME} is absent - this file does not carry binary-attest")
    _, section_off, _ = located

    text_off = va_to_offset(data, TEXT_SECTION_VA)
    if text_off is None:
        raise ValueError(f"{TEXT_SECTION_VA:#010x} is not mapped - not the expected build")

    digest = _fold(FNV_OFFSET_BASIS, bytes(data[text_off : text_off + TEXT_SECTION_LEN]))
    code = bytes(data[section_off + CODE_OFF : section_off + SECTION_LEN])
    return _fold(digest, code)


def _build_code(base_va: int) -> bytes:
    """The hook body. Runs on the logic thread, once every ``REPLAY_CRC_INTERVAL`` frames.

    ``edi`` carries the frame checksum on entry and is the one register deliberately modified;
    everything else the emitter is mid-way through using is saved and restored. The displaced
    ``mov ecx, [TheMessageStream]`` is re-emitted at the tail, so control returns to the
    instruction after it with exactly the state the engine expected.
    """
    ready = base_va + READY_OFF
    hash_slot = base_va + HASH_OFF
    code_va = base_va + CODE_OFF
    code_words = (SECTION_LEN - CODE_OFF) // 4

    a = Asm(code_va)
    a.emit(0x50)  # push eax
    a.emit(0x51)  # push ecx
    a.emit(0x52)  # push edx
    a.emit(0x56)  # push esi
    a.emit(0x9C)  # pushfd

    # A replay being watched is exempt: there is no peer to disagree with, and mixing here would
    # make every recording from a different build read as a mismatch on playback.
    a.emit(0xA1, struct.pack("<I", THE_RECORDER))  # mov eax, [TheRecorder]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "compute")
    a.emit(0x83, 0x78, RECORDER_MODE, RECORDER_MODE_PLAYBACK)  # cmp dword [eax+0x1c], 1
    a.jcc(JE, "done")

    a.label("compute")
    # Computed once and cached: the ranges are ~8 MB and neither can change under a running
    # process, so folding them every heartbeat would buy nothing but a periodic stall.
    a.emit(0xA1, struct.pack("<I", ready))  # mov eax, [ready]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "mix")
    a.call("hash_image")  # -> eax
    a.emit(0xA3, struct.pack("<I", hash_slot))  # mov [hash], eax
    # The flag is separate from the value rather than "nonzero means computed", so that the one
    # image in four billion whose code hashes to zero is not rehashed every heartbeat.
    a.emit(0xC7, 0x05, struct.pack("<I", ready), struct.pack("<I", 1))  # mov dword [ready], 1

    a.label("mix")
    a.emit(0xA1, struct.pack("<I", hash_slot))  # mov eax, [hash]
    a.emit(0x33, 0xF8)  # xor edi, eax

    a.label("done")
    a.emit(0x9D)  # popfd
    a.emit(0x5E)  # pop esi
    a.emit(0x5A)  # pop edx
    a.emit(0x59)  # pop ecx
    a.emit(0x58)  # pop eax
    a.emit(LOGIC_CRC_EMIT_BYTES)  # the displaced mov ecx, [TheMessageStream]
    a.jmp_absolute(LOGIC_CRC_EMIT_RESUME)

    # `hash_image` -> eax: FNV-1a over .text, then over this section's own code.
    a.label("hash_image")
    a.emit(0xB8, struct.pack("<I", FNV_OFFSET_BASIS))  # mov eax, basis
    a.emit(0xBE, struct.pack("<I", TEXT_SECTION_VA))  # mov esi, .text
    a.emit(0xB9, struct.pack("<I", TEXT_SECTION_LEN // 4))  # mov ecx, dwords
    a.call("fold")
    a.emit(0xBE, struct.pack("<I", code_va))  # mov esi, our code
    a.emit(0xB9, struct.pack("<I", code_words))  # mov ecx, dwords
    a.call("fold")
    a.emit(0xC3)  # ret

    # `fold(eax = digest, esi = base, ecx = dword count)` -> eax.
    a.label("fold")
    a.label("fold_loop")
    a.emit(0x33, 0x06)  # xor eax, [esi]
    a.emit(0x69, 0xC0, struct.pack("<I", FNV_PRIME))  # imul eax, eax, prime
    a.emit(0x83, 0xC6, 0x04)  # add esi, 4
    a.emit(0x49)  # dec ecx
    a.jcc_short(JNE, "fold_loop")
    a.emit(0xC3)  # ret

    return a.finish()


def build_section(base_va: int) -> bytes:
    """The whole ``.attest`` payload: the ready flag, the hash slot, then code, zero-padded to
    :data:`SECTION_LEN` so that the range the routine hashes over itself is a fixed constant."""
    code = _build_code(base_va)
    room = SECTION_LEN - CODE_OFF
    if len(code) > room:
        raise ValueError(f"the attest routine is {len(code)} bytes and does not fit in {room}")
    return bytes(CODE_OFF) + code + bytes(room - len(code))


class BinaryAttestPatch(Patch):
    name = "binary-attest"
    author = "officialNecro"
    description = (
        "Mix a hash of the game's own code into the frame checksum, so a peer running a "
        "modified game.dat goes out of sync instead of playing. No INI change; every peer needs "
        "the byte-identical binary, so ship it with the patched game.dat rather than as an "
        "option"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, LOGIC_CRC_EMIT)
        if hook_off is None:
            raise ValueError(f"{LOGIC_CRC_EMIT:#010x} is not mapped - not the expected build")
        self._check_text_section(data)
        self._check_shroud_in_crc(data)

        section_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        code_va = section_va + CODE_OFF
        # Six displaced bytes, five of which become the jump; the sixth is a nop so that the
        # instruction boundary at LOGIC_CRC_EMIT_RESUME is where the engine left it.
        jump = b"\xe9" + struct.pack("<i", code_va - (LOGIC_CRC_EMIT + 5)) + b"\x90"
        apply_byte_patch(
            data,
            hook_off,
            LOGIC_CRC_EMIT_BYTES,
            jump,
            "MSG_LOGIC_CRC emitter -> binary-attest hook",
        )

    @staticmethod
    def _check_text_section(data: bytes | bytearray) -> None:
        """Raise unless ``.text`` is mapped exactly where the cave's immediates say it is.

        The hashed range is two constants baked into the routine, and there is no runtime check
        behind them: a build whose ``.text`` started elsewhere, or ran shorter, would have the
        cave fold whatever happened to be at those addresses - which on a short section means
        reading off the end of the image and taking the process down mid-match.
        """
        for section in image_sections(data):
            if section.name != ".text":
                continue
            if section.virtual_address != TEXT_SECTION_VA:
                raise ValueError(
                    f".text is at {section.virtual_address:#010x}, expected "
                    f"{TEXT_SECTION_VA:#010x} - not the expected build"
                )
            if section.mapped_size < TEXT_SECTION_LEN:
                raise ValueError(
                    f".text is {section.mapped_size:#x} bytes, shorter than the "
                    f"{TEXT_SECTION_LEN:#x} the attest routine would read"
                )
            return
        raise ValueError("the image has no .text section")

    @staticmethod
    def _check_shroud_in_crc(data: bytes | bytearray) -> None:
        """Raise unless the CRC producer still folds ``TheShroudManager`` into the checksum.

        Not a site this patch edits - it is the premise the patch is *scoped* by. Attestation
        covers code, and the reason that is worth doing rather than also hashing the shroud grid
        is that the engine already hashes it. If a build stopped doing so, this patch would be
        the wrong shape for it and should fail rather than quietly cover half of what its
        documentation claims.
        """
        off = va_to_offset(data, LOGIC_CRC_SHROUD_XFER)
        if off is None:
            raise ValueError("the CRC producer is not mapped - not the expected build")
        got = bytes(data[off : off + len(LOGIC_CRC_SHROUD_XFER_BYTES)])
        if got != LOGIC_CRC_SHROUD_XFER_BYTES:
            raise ValueError(
                f"{LOGIC_CRC_SHROUD_XFER:#010x} is {got.hex()}, expected "
                f"{LOGIC_CRC_SHROUD_XFER_BYTES.hex()} (mov eax, [TheShroudManager]) - the shroud "
                "is not being folded into the frame CRC on this build"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, virtual_size = located
        if virtual_size < SECTION_LEN:
            problems.append(f"{SECTION_NAME} is {virtual_size:#x} bytes, expected {SECTION_LEN:#x}")

        off = va_to_offset(data, LOGIC_CRC_EMIT)
        if off is None:
            return [f"{LOGIC_CRC_EMIT:#010x} is not mapped by any section"]
        if data[off] != 0xE9:
            return [f"{LOGIC_CRC_EMIT:#010x} is not a jmp - hook not installed"]
        target = LOGIC_CRC_EMIT + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != section_va + CODE_OFF:
            problems.append(f"hook jumps to {target:#010x}, expected {section_va + CODE_OFF:#010x}")
        if data[off + 5] != 0x90:
            problems.append("the sixth displaced byte is not a nop")

        # The cave is rebuilt from scratch and compared, which checks the hashed range's contents
        # as well as its presence - a byte edited inside the routine is exactly the tamper this
        # patch exists to notice, and it should not survive its own verification.
        expected = build_section(section_va)
        got = bytes(data[section_off : section_off + SECTION_LEN])
        if got != expected:
            problems.append(f"{SECTION_NAME} does not hold the expected routine")

        try:
            self._check_text_section(data)
            self._check_shroud_in_crc(data)
        except ValueError as exc:
            problems.append(str(exc))
        return problems
