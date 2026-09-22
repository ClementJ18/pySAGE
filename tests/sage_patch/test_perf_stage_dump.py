"""Tests for the `.perfstg` reader script.

The reader's whole job is to turn bytes the cave wrote into a table somebody acts on, so it is
tested against bytes **the cave actually wrote**: `Machine` from
:mod:`tests.sage_patch.test_perf_stage_readout` runs the patch's own entry and exit routines under
Unicorn, and the block that comes out is served to the reader through a fake `MemorySource`. A
decode that disagrees with the accumulator therefore fails here rather than in a match.

`block_base` is tested against a genuinely patched image, laid out at its ImageBase the way the
loader maps it, because "find the section in the running process" is the other half that can be
silently wrong.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import IMAGE_BASE
from sage_patch.patches.perf_stage_readout import (
    OFF_SLOTS,
    SLOT_CAPACITY,
    SLOT_SIZE,
    PerfStageReadoutPatch,
)
from sage_patch.pe import image_sections
from sage_patch.scripts.perf_stage_dump import (
    Sample,
    Slot,
    block_base,
    delta,
    frame_count,
    read_sample,
    report,
)

from .synthetic import perf_stage_readout_image
from .test_perf_stage_readout import BASE, SITE_SHADOW, SITE_VIEWS, Machine

#: The two `MeshDX8Render` call sites, which share a label and therefore share a row.
SITE_MESH_A = 0x005431E7
SITE_MESH_B = 0x00543326


class FakeMemory:
    """A `MemorySource` over a dict of (address, bytes) spans."""

    def __init__(self, spans: dict[int, bytes]) -> None:
        self.spans = spans

    def read(self, address: int, size: int) -> bytes | None:
        for base, blob in self.spans.items():
            if base <= address and address + size <= base + len(blob):
                start = address - base
                return blob[start : start + size]
        return None

    def close(self) -> None:
        pass


def memory_over(machine: Machine) -> FakeMemory:
    """The emulated section. Nothing else: a row is labelled from `STAGE_SITES`, so the reader
    dereferences nothing in the game at all."""
    block = bytes(machine.uc.mem_read(BASE, OFF_SLOTS + SLOT_CAPACITY * SLOT_SIZE))
    return FakeMemory({BASE: block})


class TestTheReaderDecodesWhatTheCaveWrote:
    def test_one_scope_reads_back_by_name(self) -> None:
        machine = Machine()
        machine.scope(SITE_SHADOW, 100)

        sample = read_sample(memory_over(machine), BASE)

        assert sample.slots["UpdateShadowMap"] == Slot("UpdateShadowMap", 1, 100, 100)
        assert sample.slots_used == 1
        assert sample.depth == 0

    def test_nesting_comes_back_as_the_cave_attributed_it(self) -> None:
        """The child owns 40 of the parent's 100, which is the split the reader has to preserve."""
        machine = Machine()
        machine.enter(SITE_VIEWS)
        machine.clock += 30
        machine.scope(SITE_SHADOW, 40)
        machine.clock += 30
        machine.leave()

        slots = read_sample(memory_over(machine), BASE).slots

        assert slots["RenderViews"].inclusive == 100
        assert slots["RenderViews"].exclusive == 60
        assert slots["UpdateShadowMap"].inclusive == 40

    def test_a_sample_is_one_read_and_touches_nothing_else(self) -> None:
        """Labels come from the site table, so a sample is the block and nothing more - no string
        read, and nothing to fail at a page boundary."""
        machine = Machine()
        machine.scope(SITE_SHADOW, 10)
        memory = memory_over(machine)
        reads: list[int] = []
        raw_read = memory.read

        def recording(address: int, size: int) -> bytes | None:
            reads.append(address)
            return raw_read(address, size)

        memory.read = recording  # type: ignore[method-assign]

        read_sample(memory, BASE)

        assert reads == [BASE]

    def test_the_two_sites_of_one_stage_share_a_row(self) -> None:
        """`MeshDX8Render` is constructed from two call sites, so it holds two slots. A profile
        wants what the stage cost, not which of its sites paid."""
        machine = Machine()
        machine.scope(SITE_MESH_A, 30)
        machine.scope(SITE_MESH_B, 12)

        row = read_sample(memory_over(machine), BASE).slots["MeshDX8Render"]

        assert (row.calls, row.inclusive, row.exclusive) == (2, 42, 42)

    def test_a_site_the_table_does_not_know_keeps_its_address(self) -> None:
        """A thirty-first caller is still measured; it is reported as the address it is, which is
        what somebody would need to go and look it up."""
        machine = Machine()
        machine.scope(0x00B00000, 5)

        assert "0x00b00000" in read_sample(memory_over(machine), BASE).slots


class TestTheWindow:
    def test_a_delta_is_what_happened_between_two_samples(self) -> None:
        machine = Machine()
        machine.scope(SITE_SHADOW, 100)
        first = read_sample(memory_over(machine), BASE)

        machine.scope(SITE_SHADOW, 70)
        machine.scope(SITE_VIEWS, 5)
        rows = delta(first, read_sample(memory_over(machine), BASE))

        assert [(r.name, r.calls, r.exclusive) for r in rows] == [
            ("UpdateShadowMap", 1, 70),
            ("RenderViews", 1, 5),
        ]

    def test_a_scope_that_did_not_run_in_the_window_is_dropped(self) -> None:
        machine = Machine()
        machine.scope(SITE_SHADOW, 100)
        sample = read_sample(memory_over(machine), BASE)

        assert delta(sample, sample) == []

    def test_frames_come_from_the_once_per_frame_scope(self) -> None:
        rows = [Slot("MeshDX8Render", 3000, 0, 0), Slot("RenderViews", 42, 0, 0)]

        assert frame_count(rows) == 42

    def test_frames_fall_back_when_the_view_pass_did_not_run(self) -> None:
        assert frame_count([Slot("UpdateShadowMap", 7, 0, 0)]) == 7
        assert frame_count([Slot("MeshDX8Render", 3000, 0, 0)]) == 0

    def test_a_window_with_no_frame_scope_still_reports(self, capsys) -> None:  # noqa: ANN001
        """A menu is a running game: the reader must say so rather than divide by zero."""
        rows = [Slot("MeshDX8Render", 10, 500, 500)]

        report(rows, 1.0, 1000, Sample(0, 0, 1, 0, 0, 0, {}))

        assert "no frame scope was entered" in capsys.readouterr().out


class TestTheBlockIsFound:
    def test_the_section_is_located_in_a_mapped_image(self) -> None:
        image = perf_stage_readout_image()
        PerfStageReadoutPatch().apply(image)
        section = next(s for s in image_sections(image) if s.name == ".perfstg")
        mapped = {
            IMAGE_BASE: bytes(image[:0x1000]),
            section.virtual_address: bytes(
                image[section.raw_offset : section.raw_offset + section.raw_size]
            ),
        }

        assert block_base(FakeMemory(mapped)) == section.virtual_address

    def test_an_unpatched_game_says_which_patch_is_missing(self) -> None:
        image = perf_stage_readout_image()

        with pytest.raises(SystemExit, match="perf-stage-readout"):
            block_base(FakeMemory({IMAGE_BASE: bytes(image[:0x1000])}))

    def test_a_section_without_the_magic_is_refused(self) -> None:
        image = perf_stage_readout_image()
        PerfStageReadoutPatch().apply(image)
        section = next(s for s in image_sections(image) if s.name == ".perfstg")
        block = bytearray(image[section.raw_offset : section.raw_offset + section.raw_size])
        struct.pack_into("<I", block, 0, 0xDEADBEEF)

        with pytest.raises(SystemExit, match="PSTG"):
            block_base(
                FakeMemory(
                    {IMAGE_BASE: bytes(image[:0x1000]), section.virtual_address: bytes(block)}
                )
            )
