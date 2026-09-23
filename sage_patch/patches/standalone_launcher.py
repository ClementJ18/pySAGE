"""Remove the launcher's install-location lock, so a relocated copy still hands the game a usable
token.

Targets `lotrbfme2ep1.exe`, not `game.dat`. The launcher derives the token it hands `game.dat` by
decrypting with a key built from the install drive's volume serial (read at `0x0040B2BB`,
`0x0040B320`, `0x0040B332`). `gi.dat` already carries the plaintext in its `G4` field, whose
accessor the stock launcher never calls, so the 38 bytes that build the key and decrypt become a
copy of `G4`. `gi.dat` must sit beside the launcher.

Derivation: `../docs/standalone-launcher.md` and `../docs/standalone-game.md`.
"""

from __future__ import annotations

from ..asm import Asm
from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = [
    "ANCHORS",
    "BINARY",
    "GI_DAT_G4_ACCESSOR",
    "STRCPY",
    "TOKEN_SITE",
    "TOKEN_SITE_LENGTH",
    "TOKEN_SITE_STOCK",
    "StandaloneLauncherPatch",
    "build_code",
]

#: The binary this patch targets. Not `game.dat` - the CLI labels every path argument `GAME_DAT`,
#: so a patch that wants another file has to say so in the text `sage-patch list` prints.
BINARY = "lotrbfme2ep1.exe"

#: The key-schedule-plus-decrypt the patch replaces, and its stock bytes:
#:
#:     push eax                    ; key length, clamped to 0x38 just above
#:     lea  edx, [esp+0x1140]      ; the key text - "<volume serial in hex>-..."
#:     push edx
#:     lea  ecx, [esp+0x58]        ; the Blowfish context
#:     call 0x00405E20             ; setKey
#:     mov  eax, [esp+0x10]        ; the payload's length
#:     mov  ecx, [esp+0x0C]        ; the payload
#:     push edi                    ; destination: the game2.dat mapped view
#:     push eax
#:     push ecx
#:     lea  ecx, [esp+0x5C]
#:     call 0x004061C0             ; decrypt
TOKEN_SITE = 0x0040B533
TOKEN_SITE_STOCK = bytes.fromhex(
    "508d942440110000528d4c2458e8dba8ffff8b4424108b4c240c5750518d4c245ce867acffff"
)
TOKEN_SITE_LENGTH = len(TOKEN_SITE_STOCK)

#: `gi.dat`'s `G4` accessor - `parse gi.dat if needed; return [0x0046F5B8]`. The tenth and last
#: field, and the only one with no caller in the stock binary.
GI_DAT_G4_ACCESSOR = 0x004167B0

#: The CRT's `strcpy`.
STRCPY = 0x0044A170

#: The sites that must still hold their stock bytes for this patch to mean what it says, none of
#: which it writes. Between them they state the whole derivation - the mapping the token lands in,
#: the three inputs the stock key is built from, the Blowfish schedule that consumes it, the clamp
#: that identifies it as a Blowfish key, and the two functions the replacement calls.
ANCHORS = {
    # call MapViewOfFileEx - the game2.dat view, whose pointer `edi` still holds at the site
    0x0040B203: bytes.fromhex("ff15f4f04500"),
    0x0040B2AD: bytes.fromhex("6844094600"),  # push "InstallPath"
    0x0040B2BB: bytes.fromhex("ff1558f04500"),  # call RegQueryValueExA
    0x0040B320: bytes.fromhex("ff15f0f04500"),  # call GetVolumeInformationA
    0x0040B332: bytes.fromhex("68f80e4600"),  # push "%lx-"
    # cmp eax, 0x38 / jle / mov eax, 0x38 - the run-up to the site, clamping the key to Blowfish's
    # maximum length. This is what says the string being built is a key and not a message.
    0x0040B529: bytes.fromhex("83f8387e05b838000000"),
    # mov esi, 0x0045F5C0 inside setKey - the 18-dword P-array the schedule starts from
    0x00405E2E: bytes.fromhex("bec0f54500"),
    # the two functions the replacement calls
    GI_DAT_G4_ACCESSOR: bytes.fromhex("558bece828ffffffa1b8f54600"),
    STRCPY: bytes.fromhex("578b7c2408eb6e"),
}


def build_code(site_va: int = TOKEN_SITE, length: int = TOKEN_SITE_LENGTH) -> bytes:
    """The replacement, assembled to run at `site_va` and padded with `nop` to `length`.

    Entered in the middle of a function with `edi` holding the mapped view and the stack as the
    stock code left it, so there is no prologue and nothing to preserve: `eax` and the two pushes
    are all the stock code was about to clobber anyway, and `add esp, 8` puts `esp` back exactly
    where the two `call`s below the site expect it.
    """
    a = Asm(site_va)
    a.call_absolute(GI_DAT_G4_ACCESSOR)  # eax = gi.dat's G4
    a.emit(0x50)  # push eax             ; src
    a.emit(0x57)  # push edi             ; dst - the game2.dat view
    a.call_absolute(STRCPY)
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8   ; strcpy is cdecl
    code = a.finish()
    if len(code) > length:
        raise ValueError(f"the replacement is {len(code)} bytes, which does not fit in {length}")
    return code + b"\x90" * (length - len(code))


class StandaloneLauncherPatch(Patch):
    """Take the launcher's shared-memory token from `gi.dat` instead of decrypting it under a key
    built from the install path's volume serial."""

    name = "standalone-launcher"
    author = "officialNecro"
    description = (
        "lotrbfme2ep1.exe (not game.dat): drop the install-location lock - the token handed to "
        "game.dat comes from gi.dat's G4 instead of an HKLM InstallPath + volume-serial key. No "
        "INI change; gi.dat has to sit beside the launcher"
    )

    binary = BINARY

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        off = va_to_offset(data, TOKEN_SITE)
        if off is None:
            raise ValueError(f"unexpected build: {TOKEN_SITE:#010x} is not mapped")
        apply_byte_patch(
            data,
            off,
            TOKEN_SITE_STOCK,
            build_code(),
            "the launcher's token: decrypt-under-a-volume-serial-key -> gi.dat's G4",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that `data` carries this patch (an empty list == verified): every
        anchor still reads what it should, and the site now holds the replacement."""
        problems: list[str] = []
        try:
            self._check_anchors(data)
        except ValueError as exc:
            return [str(exc)]

        off = va_to_offset(data, TOKEN_SITE)
        if off is None:
            return [f"{TOKEN_SITE:#010x} is not mapped by any section"]
        expected = build_code()
        got = bytes(data[off : off + TOKEN_SITE_LENGTH])
        if got != expected:
            problems.append(
                f"{TOKEN_SITE:#010x} is {got.hex()}, expected {expected.hex()} - the token is "
                "still derived from the install path"
            )
        return problems

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        """Raise unless every pinning site holds its stock bytes, so a patch aimed at the wrong
        binary or the wrong build fails before it writes rather than overwriting 38 bytes of
        something else."""
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            got = None if off is None else bytes(data[off : off + len(expected)])
            if got != expected:
                hexed = "unmapped" if got is None else got.hex()
                raise ValueError(
                    f"unexpected build: {va:#010x} is {hexed}, expected {expected.hex()} - "
                    f"this does not look like the {BINARY} this patch targets"
                )
