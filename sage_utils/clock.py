"""Format a duration in seconds as a match clock or an `H:MM:SS` timestamp. Engine-generic:
no dependency on any SAGE data model."""

from __future__ import annotations

__all__ = ["clock", "hms"]


def clock(seconds: float) -> str:
    """A duration as a `m:ss` match clock (unbounded minutes, no leading zero)."""
    return f"{int(seconds) // 60:d}:{int(seconds) % 60:02d}"


def hms(seconds: float) -> str:
    """A duration as `H:MM:SS`, rounded to the nearest second and clamped at 0 (a negative
    span reads as `0:00:00`)."""
    total = max(0, round(seconds))
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"
