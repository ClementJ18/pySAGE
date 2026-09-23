"""Stop the War of the Ring AI crashing on a scenario that starts with regions disabled.

The AI's region graph (`AI_REGION_GRAPH`) is built once and skips disabled regions, but the planner
looks every region up in it without checking and dereferences the missing entry. Six bytes: the
builder's skip becomes `nop`s, so every region gets a node. The planner's lookups are unchanged.

Derivation: `../docs/living-campaign/ai-disabled-regions.md`.
"""

from __future__ import annotations

from ..addresses import (
    AI_REGION_GRAPH_ENABLED_TEST,
    AI_REGION_GRAPH_ENABLED_TEST_BYTES,
    AI_REGION_GRAPH_SKIP_DISABLED,
    AI_REGION_GRAPH_SKIP_DISABLED_BYTES,
)
from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = ["NOPS", "AiDisabledRegionsPatch"]

#: What the skip becomes: one `nop` per byte of the `je` it replaces.
NOPS = b"\x90" * len(AI_REGION_GRAPH_SKIP_DISABLED_BYTES)


class AiDisabledRegionsPatch(Patch):
    name = "ai-disabled-regions"
    author = "officialNecro"
    runtime_verified = "yes"
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
