"""The ai-disabled-regions patch: stop the War of the Ring AI crashing on a disabled region.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. The reverse engineering, and the
crash dumps it was read out of, are in ``../../docs/living-campaign/ai-disabled-regions.md``.

**The defect.** The living-world AI plans over a region graph at
:data:`~sage_patch.addresses.AI_REGION_GRAPH`: a `std::map` from region id to that region's
neighbour lists. :data:`~sage_patch.addresses.AI_REGION_GRAPH_BUILD` fills it - only while it is
empty, so once - and skips every region whose enabled flag (`Region+0x1C2`) is clear. The AI
planner then walks the regions it knows about and looks each one up in the graph with the map's
plain `find`, and at two sites (:data:`~sage_patch.addresses.AI_PLANNER_UNCHECKED_LOOKUPS`) uses
the result **without comparing it with the head node** that `find` returns for a missing key. The
head node's value is zeroes; copying it as a neighbour list dereferences a null list head at
:data:`~sage_patch.addresses.AI_NEIGHBOUR_LIST_COPY_FAULT`.

So a War of the Ring scenario that starts any region disabled (`Scenario`'s `DisableRegions`)
crashes as soon as the AI plans a turn, and a region an act enables later is never added to the
graph either, because the graph is not built again.

**What this does.** Six bytes: the `je` that jumps past a disabled region in the builder becomes six
`nop`s, so every region gets a node whatever its enabled flag says when the graph is built. The
graph records how regions connect; it is not where the enabled flag is enforced.

**What it does not do.** It adds no end check to the planner's lookups, so a region missing from
the graph for any other reason still crashes it. Whether the AI now plans moves into a region that
is still disabled, and whether the move is then refused, is not established - see the doc.

**Composition.** Order-independent and cave-free. No other bundled patch touches the builder.
"""

from __future__ import annotations

from ...addresses import (
    AI_REGION_GRAPH_ENABLED_TEST,
    AI_REGION_GRAPH_ENABLED_TEST_BYTES,
    AI_REGION_GRAPH_SKIP_DISABLED,
    AI_REGION_GRAPH_SKIP_DISABLED_BYTES,
)
from ...patcher import Patch
from ...utils import apply_byte_patch, va_to_offset

__all__ = ["NOPS", "AiDisabledRegionsPatch"]

#: What the skip becomes: one `nop` per byte of the `je` it replaces.
NOPS = b"\x90" * len(AI_REGION_GRAPH_SKIP_DISABLED_BYTES)


class AiDisabledRegionsPatch(Patch):
    name = "ai-disabled-regions"
    author = "officialNecro"
    experimental = True
    description = (
        "Give every region a node in the War of the Ring AI's region graph, not only the regions "
        "enabled when the graph is built. Stock, a scenario with DisableRegions crashes on the "
        "AI's first turn, because the AI planner looks each region up in the graph without "
        "checking it is there"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchor(data)
        apply_byte_patch(
            data,
            self._offset(data, AI_REGION_GRAPH_SKIP_DISABLED),
            AI_REGION_GRAPH_SKIP_DISABLED_BYTES,
            NOPS,
            "AI region graph: keep disabled regions",
        )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @classmethod
    def _check_anchor(cls, data: bytes | bytearray) -> None:
        """Raise unless the bytes before the site are the enabled test.

        The skip is only this patch's to remove when it is the branch taken on that test: a build
        whose builder moved would otherwise have some other six bytes turned into `nop`s."""
        off = cls._offset(data, AI_REGION_GRAPH_ENABLED_TEST)
        got = bytes(data[off : off + len(AI_REGION_GRAPH_ENABLED_TEST_BYTES)])
        if got != AI_REGION_GRAPH_ENABLED_TEST_BYTES:
            raise ValueError(
                f"{AI_REGION_GRAPH_ENABLED_TEST:#010x} holds {got.hex()}, not the builder's "
                "enabled test - this is not the AI region-graph builder of the expected build"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            self._check_anchor(data)
        except ValueError as exc:
            return [str(exc)]
        off = self._offset(data, AI_REGION_GRAPH_SKIP_DISABLED)
        got = bytes(data[off : off + len(NOPS)])
        if got == NOPS:
            return []
        which = "the stock skip" if got == AI_REGION_GRAPH_SKIP_DISABLED_BYTES else "something else"
        return [
            f"{AI_REGION_GRAPH_SKIP_DISABLED:#010x} holds {got.hex()} ({which}): the file does not "
            "carry this patch"
        ]
