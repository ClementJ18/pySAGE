"""Keep a researched upgrade's description in its tooltip, with the "already researched" message
added under it rather than replacing it.

Nine bytes where the builder assigns the status message become a `jmp` to a cave that appends it
instead, using the engine's own separator. The same applies to the conflicting-upgrade and
missing-prerequisite messages. No new string key.

Derivation: `../docs/upgrade-description.md`.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ..addresses import (
    DESCRIPTION_BLOCKED_ASSIGN,
    DESCRIPTION_BLOCKED_ASSIGN_BYTES,
    DESCRIPTION_BLOCKED_RESUME,
    DESCRIPTION_BLOCKED_RUN,
    DESCRIPTION_BLOCKED_RUN_BYTES,
    DESCRIPTION_PURCHASED_ASSIGN,
    DESCRIPTION_PURCHASED_ASSIGN_BYTES,
    DESCRIPTION_PURCHASED_RESUME,
    DESCRIPTION_PURCHASED_RUN,
    DESCRIPTION_PURCHASED_RUN_BYTES,
    DESCRIPTION_TEXT_EBP_OFFSET,
    UNICODE_STRING_APPEND,
    UNICODE_STRING_APPEND_BYTES,
    UNICODE_STRING_ASSIGN,
    UNICODE_STRING_ASSIGN_BYTES,
    UNICODE_STRING_CONCAT_WIDE,
    UNICODE_STRING_CONCAT_WIDE_BYTES,
    WIDE_BLANK_LINE,
    WIDE_BLANK_LINE_BYTES,
    WIDE_NEWLINE,
    WIDE_NEWLINE_BYTES,
)
from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    find_section,
    i8,
    jmp_rel32,
    read_bytes,
    u32,
    va_to_offset,
)

if TYPE_CHECKING:
    import argparse

__all__ = ["ANCHORS", "SECTION_NAME", "SITES", "Site", "UpgradeDescriptionPatch"]

#: 8 chars max: the PE name field truncates silently past 8.
SECTION_NAME = ".updesc"

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave is written at patch time and
# never at runtime, so no MEM_WRITE.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000


class Site:
    """One `operator=` window this patch turns into a `concat`.

    `run`/`run_bytes` is the whole engine case the window sits inside, kept so the check can
    establish *which* case it is - the nine edited bytes are the same at both sites bar one
    `rel32`, and are not on their own evidence of anything.
    """

    def __init__(
        self,
        label: str,
        run: int,
        run_bytes: bytes,
        assign: int,
        assign_bytes: bytes,
        resume: int,
    ) -> None:
        self.label = label
        self.run = run
        self.run_bytes = run_bytes
        self.assign = assign
        self.assign_bytes = assign_bytes
        self.resume = resume
        #: Where the edited window starts inside `run_bytes`, derived rather than written down.
        self.offset = assign - run
        if run_bytes[self.offset : self.offset + len(assign_bytes)] != assign_bytes:
            raise ValueError(f"{label}: the assign window is not where the run says it is")


#: The already-upgraded case first, because it is the one the patch is named for and the only one
#: applied by default.
SITES: dict[str, Site] = {
    "purchased": Site(
        "purchased",
        DESCRIPTION_PURCHASED_RUN,
        DESCRIPTION_PURCHASED_RUN_BYTES,
        DESCRIPTION_PURCHASED_ASSIGN,
        DESCRIPTION_PURCHASED_ASSIGN_BYTES,
        DESCRIPTION_PURCHASED_RESUME,
    ),
    "blocked": Site(
        "blocked",
        DESCRIPTION_BLOCKED_RUN,
        DESCRIPTION_BLOCKED_RUN_BYTES,
        DESCRIPTION_BLOCKED_ASSIGN,
        DESCRIPTION_BLOCKED_ASSIGN_BYTES,
        DESCRIPTION_BLOCKED_RESUME,
    ),
}

#: Everything the cave calls or points at, by address and by first bytes. The method being *left
#: behind* is anchored too: what identifies the edited window as "the assignment" is that its
#: `call` reaches `operator=`, and on a build where these two moved, swapping one for the other
#: would aim the cave at whatever now lives there.
ANCHORS: dict[int, bytes] = {
    UNICODE_STRING_ASSIGN: UNICODE_STRING_ASSIGN_BYTES,
    UNICODE_STRING_APPEND: UNICODE_STRING_APPEND_BYTES,
    UNICODE_STRING_CONCAT_WIDE: UNICODE_STRING_CONCAT_WIDE_BYTES,
    WIDE_NEWLINE: WIDE_NEWLINE_BYTES,
    WIDE_BLANK_LINE: WIDE_BLANK_LINE_BYTES,
}

#: The separator, by `--separator` token. `L"\n"` puts the message on the next line, `L"\n\n"`
#: leaves a blank line between. Both are literals the builder already uses elsewhere, so neither
#: needs a byte of new data.
SEPARATORS: dict[str, int] = {"newline": WIDE_NEWLINE, "blank-line": WIDE_BLANK_LINE}


# Everything below is hand-encoded (the house style: only address arithmetic is automated, by
# `..asm`), with a comment saying what each instruction is.


def _emit(a: Asm, separator_va: int, sites: list[Site]) -> None:
    """A thunk per patched site, then the one routine they share.

    Each thunk is entered by the `jmp` that replaced its `operator=` window, with `eax` holding the
    fetched message and `ebp` still the builder's frame, and leaves for the destructor the window
    was followed by.
    """
    for site in sites:
        a.label(site.label)
        a.call("append")
        a.jmp_absolute(site.resume)

    a.label("append")
    # `push eax` is doing two jobs: it saves the message across the separator call *and* it is
    # already the stack argument the concat below wants. `concat`'s `ret 4` is what removes it,
    # so the routine is stack-neutral without a frame of its own.
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0x45, i8(DESCRIPTION_TEXT_EBP_OFFSET))  # mov eax, [ebp-0x18]

    # The engine's own "is there anything to separate from" test, from the two folds at
    # `0x008080AE` and `0x008080FB`: a null buffer pointer, or a zero length word inside it.
    # `edi` is the zero those sites compare against; it is *not* zero here (the upgrade path
    # reloads it with the described `Object` at `0x0080817E`), so this compares with immediates.
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "ap_message")
    a.emit(0x66, 0x83, 0x78, 0x04, 0x00)  # cmp word ptr [eax+4], 0
    a.jcc(JE, "ap_message")
    a.emit(0x68, u32(separator_va))  # push <L"\n">
    a.emit(0x8D, 0x4D, i8(DESCRIPTION_TEXT_EBP_OFFSET))  # lea ecx, [ebp-0x18]
    a.call_absolute(UNICODE_STRING_CONCAT_WIDE)  # thiscall, ret 4

    a.label("ap_message")
    a.emit(0x8D, 0x4D, i8(DESCRIPTION_TEXT_EBP_OFFSET))  # lea ecx, [ebp-0x18]
    a.call_absolute(UNICODE_STRING_APPEND)  # thiscall, ret 4 - drops the pushed message
    a.emit(0xC3)  # ret


class UpgradeDescriptionPatch(Patch):
    """Append the "already researched" line to an upgrade's description instead of replacing it."""

    name = "upgrade-description"
    author = "officialNecro"
    runtime_verified = "yes"
    description = (
        "Keep a CommandButton's DescriptLabel visible once its upgrade is researched, with "
        "PurchasedLabel / TOOLTIP:AlreadyUpgradedDefault appended under it rather than over it. "
        "Both of those already exist in a stock string table, so no new key and no INI change "
        "is needed"
    )

    def __init__(self, separator: str = "newline", also_blocked: bool = False) -> None:
        if separator not in SEPARATORS:
            raise ValueError(
                f"unknown separator {separator!r} - expected one of {sorted(SEPARATORS)}"
            )
        self.separator = separator
        self.also_blocked = also_blocked

    @property
    def sites(self) -> list[Site]:
        """The windows this configuration rewrites, in the order they are laid out in the cave."""
        names = ["purchased", "blocked"] if self.also_blocked else ["purchased"]
        return [SITES[name] for name in names]

    def apply(self, data: bytearray) -> None:
        self._check_build(data)
        section_va = allocate_section(
            data, SECTION_NAME, lambda base: self._assemble(base).finish(), _CHARACTERISTICS
        )
        for file_off, old, new, note in self._edits(data, section_va):
            apply_byte_patch(data, file_off, old, new, note)

    def _check_build(self, data: bytes | bytearray) -> None:
        """Raise unless every site and every callee is still what these bytes came from.

        `apply_byte_patch` would catch the sites too, but only after the section had been appended
        - and a file left carrying a cave nothing jumps into is a worse failure than a clean raise.
        The callees it would not catch at all: nothing about the edited window says where
        `concat` lives.

        The already-applied case is checked **first**, because it also fails the site check, and
        "you already applied this" is the useful half of that answer.
        """
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        for site in self.sites:
            self._check_run(data, site)
        for va, expected in ANCHORS.items():
            got = read_bytes(data, va, len(expected))
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the UnicodeString "
                    "methods are not this build's, so the cave would call the wrong function"
                )

    @staticmethod
    def _check_run(data: bytes | bytearray, site: Site, skip_window: bool = False) -> None:
        """Raise unless `site`'s whole engine case is intact.

        `skip_window` leaves out the nine bytes the patch rewrites, which is what lets
        `verify` reuse this on an already-patched file: everything around the window is
        untouched by the patch, so one check serves both directions.
        """
        end = site.offset + len(site.assign_bytes)
        spans = [(0, site.run_bytes[: site.offset]), (end, site.run_bytes[end:])]
        if not skip_window:
            spans.append((site.offset, site.assign_bytes))
        for at, expected in spans:
            got = read_bytes(data, site.run + at, len(expected))
            if got != expected:
                raise ValueError(
                    f"{site.run + at:#010x} is {got.hex()}, expected {expected.hex()} - this is "
                    f"not the description builder's {site.label!r} case"
                )

    def _assemble(self, base_va: int) -> Asm:
        a = Asm(base_va)
        _emit(a, SEPARATORS[self.separator], self.sites)
        a.finish()  # resolve the internal branches, so `label_va` describes a real layout
        return a

    def _edits(
        self, data: bytes | bytearray, section_va: int
    ) -> list[tuple[int, bytes, bytes, str]]:
        """`(file offset, original bytes, patched bytes, note)` for every engine byte this patch
        rewrites - one list, so `apply` writes exactly what `verify` asserts."""
        assembled = self._assemble(section_va)
        edits = []
        for site in self.sites:
            off = va_to_offset(data, site.assign)
            if off is None:
                raise ValueError(f"{site.assign:#010x} is not mapped - not the expected build")
            patched = jmp_rel32(site.assign, assembled.label_va(site.label))
            patched += b"\x90" * (len(site.assign_bytes) - len(patched))
            edits.append(
                (off, site.assign_bytes, patched, f"description {site.label!r}: assign -> append")
            )
        return edits

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located
        problems: list[str] = []

        expected_cave = self._assemble(section_va).finish()
        got_cave = bytes(data[section_off : section_off + len(expected_cave)])
        if got_cave != expected_cave:
            problems.append(
                f"the {SECTION_NAME} cave is not what this configuration builds "
                f"(separator={self.separator}, also_blocked={self.also_blocked})"
            )

        try:
            edits = self._edits(data, section_va)
        except ValueError as exc:
            return [*problems, f"cannot recompute the expected edits (wrong build?): {exc}"]
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")

        for site in self.sites:
            try:
                self._check_run(data, site, skip_window=True)
            except ValueError as exc:
                problems.append(str(exc))
        for va, expected in ANCHORS.items():
            got = read_bytes(data, va, len(expected))
            if got != expected:
                problems.append(f"{va:#010x} holds {got.hex()}, expected {expected.hex()}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> UpgradeDescriptionPatch | None:
        """Recover the configuration from the image.

        Both parameters are readable off the file: `also_blocked` from whether the second window
        is still a `call`, and the separator from the `push imm32` the cave holds. Probing every
        combination and keeping the one that verifies is four `verify` runs and needs no second
        description of the cave's layout.
        """
        for also_blocked in (False, True):
            for separator in SEPARATORS:
                try:
                    patch = cls(separator=separator, also_blocked=also_blocked)
                    problems = patch.verify(data)
                except (ValueError, KeyError, IndexError, TypeError, struct.error):
                    continue
                if not problems:
                    return patch
        return None

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--separator",
            choices=sorted(SEPARATORS),
            default="newline",
            help=(
                "what goes between the description and the appended message: a line break "
                "(default) or a blank line. Both are literals the tooltip builder already uses"
            ),
        )
        parser.add_argument(
            "--also-blocked",
            action="store_true",
            help=(
                "append the conflicting-upgrade and lacks-prerequisite messages the same way. "
                "Those replace the description too, by the identical mechanism, one field along"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> UpgradeDescriptionPatch:
        return cls(separator=args.separator, also_blocked=args.also_blocked)
