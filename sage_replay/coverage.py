"""Format-coverage auditor: measure how much of a replay is still raw bytes.

The coverage goal for the reader is simple - *no more raw bytes*: every byte the parser
touches should carry a typed name and a validated meaning, or be proven constant across the
corpus and documented as reserved padding. This module makes that measurable. It walks a
corpus and, per still-opaque surface, reports the distinct values seen so a constant proves
itself and a variation stands out:

- header reserved blocks (`reserved1`, `reserved2`), the trailing `unknown_tail` words, and
  the `crc_interval` heartbeat cadence - all expected constant;
- order-type ids that have no `Bfme2OrderType` name yet (the progress dashboard for
  `order_space_map.md` section B), with per-id occurrence counts and argument signatures;
- argument values still decoded as raw `bytes` (only `WideChar` can produce one today);
- metadata keys with no typed accessor on `ReplayMetadata`;
- slot-string remainders kept raw (the reserved tails, `nat_behavior`, the `TT` flags).

The observed state of the checked-in fixture corpus is encoded below as the "known reality".
`CoverageReport.strict_failures()` returns the surfaces that deviate from it, so
`audit(...).strict_failures()` (and `coverage --strict`) is the acceptance gate that keeps
the reader at zero un-accounted-for bytes; `diff_replays` isolates which opaque surfaces
move between an A/B pair for differential decoding.
"""

from __future__ import annotations

import struct
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sage_replay.replay import (
    Bfme2OrderType,
    ReplayFile,
    ReplaySlot,
    ReplaySlotType,
    parse_replay_from_path,
)

__all__ = [
    "KNOWN_METADATA_KEYS",
    "KNOWN_ORDER_TYPES",
    "CoverageReport",
    "OrderTypeStat",
    "SlotRawFields",
    "audit",
    "diff_replays",
    "find_replays",
]

# Filename suffixes the auditor recognises as replays, matched case-insensitively.
REPLAY_SUFFIXES = (".rep", ".bfmereplay", ".bfme2replay")

# Known reality, tuned to the checked-in fixture corpus (12 RotWK 2.01 / Edain replays).
# A `strict` audit fails when the corpus deviates from any of these.
CRC_INTERVAL = 100  # REPLAY_CRC_INTERVAL, the checksum-heartbeat cadence
UNKNOWN_TAIL = (0, 0, 1, 1, 0, 0)  # the six trailing header uint32s
# A custom-hero replay (ReplayHeader.custom_heroes) replaces the six-word unknown_tail with
# `24 - len(players)` bytes: leading zero padding then the usual closing words (0, 1, 1, 0, 0).
# CUSTOM_HERO_TAIL_SUFFIX is those twenty trailing bytes; the leading padding is all-zero.
CUSTOM_HERO_TAIL_SUFFIX = struct.pack("<5I", 0, 1, 1, 0, 0)
GAME_TYPE_FLAG = "0"  # metadata GT
SESSION_INFO = "-1"  # metadata SI
# `reserved1` is nine bytes: all-zero, or a lone 0x01 in byte 2 (a per-slot disconnect-flag
# candidate, seen in exactly one fixture - not a crashed one). `reserved2` is five zero
# bytes throughout.
RESERVED1_PATTERNS = frozenset({bytes(9), b"\x00\x00\x01" + bytes(6)})
RESERVED2_PATTERN = bytes(5)

# Metadata keys `ReplayMetadata` decodes: M/MC/MS/SD/SC/S in `parse`, GSID/GT/SI/GR via typed
# accessors. Any other key in a replay is an undecoded surface. (Generals writes a `C=` CRC
# interval; BFME2 does not, and none of the fixtures carry it.)
KNOWN_METADATA_KEYS = frozenset({"M", "MC", "MS", "SD", "SC", "S", "GSID", "GT", "SI", "GR"})

# Census of the 79 distinct order-type ids observed across the fixture corpus
# (order_space_map.md sections A/B/C). The ✅-grade ids carry a `Bfme2OrderType` name; the
# rest are known-unknowns (🟡/❓) still measured here. An id in neither set is brand-new and
# fails a strict audit.
_KNOWN_UNKNOWN_ORDER_TYPES = frozenset(
    {
        0x3EA, 0x3EB, 0x3ED, 0x403, 0x404, 0x405, 0x40E, 0x40F, 0x415, 0x416,
        0x418, 0x41B, 0x41C, 0x41D, 0x41E, 0x425, 0x42C, 0x42E, 0x430,
        0x435, 0x436, 0x437, 0x439, 0x43D, 0x43F, 0x444, 0x453, 0x458, 0x45C,
        0x45D, 0x460, 0x461, 0x463, 0x464, 0x466, 0x468, 0x473, 0x474, 0x475,
    }
)  # fmt: skip
KNOWN_ORDER_TYPES = frozenset(_KNOWN_UNKNOWN_ORDER_TYPES | {int(o) for o in Bfme2OrderType})


def find_replays(paths: Iterable[str | Path]) -> list[Path]:
    """Expand the given files and directories into a sorted, de-duplicated list of replay
    paths. Directories are searched recursively for the recognised replay suffixes; files are
    taken as-is regardless of extension."""
    found: set[Path] = set()
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_file() and child.suffix.lower() in REPLAY_SUFFIXES:
                    found.add(child)
        elif path.is_file():
            found.add(path)
    return sorted(found)


def _order_name(order_type: int) -> str | None:
    try:
        return Bfme2OrderType(order_type).name
    except ValueError:
        return None


def _run_length(names: Sequence[str]) -> str:
    """Render an argument-type-name signature compactly, collapsing runs (a select order's
    long ObjectId list reads as `ObjectId×12`, not twelve repeats)."""
    if not names:
        return "()"
    parts: list[list] = []
    for name in names:
        if parts and parts[-1][0] == name:
            parts[-1][1] += 1
        else:
            parts.append([name, 1])
    return ", ".join(f"{n}×{c}" if c > 1 else n for n, c in parts)


@dataclass
class OrderTypeStat:
    """Per-order-type coverage figures for the progress dashboard."""

    order_type: int
    count: int = 0  # total chunks of this order type across the corpus
    files: int = 0  # how many files it appears in
    signatures: Counter[tuple[str, ...]] = field(default_factory=Counter)

    @property
    def name(self) -> str | None:
        return _order_name(self.order_type)

    @property
    def named(self) -> bool:
        return self.name is not None

    @property
    def in_census(self) -> bool:
        return self.order_type in KNOWN_ORDER_TYPES


@dataclass
class SlotRawFields:
    """The still-raw slot-string remainders seen for one slot kind (human or AI)."""

    reserved: set[tuple[int, ...]] = field(default_factory=set)
    nat_behavior: set[int] = field(default_factory=set)
    tt: set[tuple[bool | None, bool | None]] = field(default_factory=set)

    def add(self, slot: ReplaySlot) -> None:
        self.reserved.add(slot.reserved)
        self.nat_behavior.add(slot.nat_behavior)
        self.tt.add((slot.accepted, slot.has_map))


@dataclass
class CoverageReport:
    """Aggregated coverage over an audited corpus. Each still-opaque surface keeps the
    distinct values seen (mapped to the files that carried them) so constants prove
    themselves. `strict_failures()` lists the deviations from the encoded known reality."""

    files: list[Path] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)

    reserved1: dict[bytes, list[str]] = field(default_factory=dict)
    reserved2: dict[bytes, list[str]] = field(default_factory=dict)
    unknown_tail: dict[tuple[int, ...], list[str]] = field(default_factory=dict)
    crc_interval: dict[int, list[str]] = field(default_factory=dict)
    abnormal_end_frames: dict[str, int] = field(default_factory=dict)
    # Custom-hero (Create-A-Hero) replays: the raw trailing bytes that replace unknown_tail,
    # and the per-file custom-hero blob count. Empty when the corpus has no custom-hero games.
    custom_hero_tails: dict[bytes, list[str]] = field(default_factory=dict)
    custom_hero_counts: dict[str, int] = field(default_factory=dict)

    metadata_values: dict[str, dict[str | None, list[str]]] = field(default_factory=dict)
    unknown_metadata_keys: dict[str, list[str]] = field(default_factory=dict)

    order_types: dict[int, OrderTypeStat] = field(default_factory=dict)
    bytes_arguments: Counter[str] = field(default_factory=Counter)

    human_slots: SlotRawFields = field(default_factory=SlotRawFields)
    ai_slots: SlotRawFields = field(default_factory=SlotRawFields)

    @property
    def parsed(self) -> int:
        return len(self.files) - len(self.errors)

    def _observed(self, key: str) -> dict[str | None, list[str]]:
        return self.metadata_values.get(key, {})

    def strict_failures(self) -> list[str]:
        """Surfaces that deviate from the encoded known reality - the `--strict` gate. Empty
        means the corpus is fully accounted for at the format level."""
        failures: list[str] = []

        for path, message in self.errors:
            failures.append(f"{path.name}: parse error: {message}")

        for interval, names in self.crc_interval.items():
            if interval != CRC_INTERVAL:
                failures.append(f"crc_interval {interval} != {CRC_INTERVAL} in {_join(names)}")
        for tail, names in self.unknown_tail.items():
            if tail != UNKNOWN_TAIL:
                failures.append(f"unknown_tail {tail} != {UNKNOWN_TAIL} in {_join(names)}")
        for raw1, names in self.reserved1.items():
            if raw1 not in RESERVED1_PATTERNS:
                failures.append(f"reserved1 {raw1.hex()} unrecognised in {_join(names)}")
        for raw2, names in self.reserved2.items():
            if raw2 != RESERVED2_PATTERN:
                failures.append(f"reserved2 {raw2.hex()} non-zero in {_join(names)}")
        for hero_tail, names in self.custom_hero_tails.items():
            if not _valid_custom_hero_tail(hero_tail):
                failures.append(f"custom_hero_tail {hero_tail.hex()} bad in {_join(names)}")

        for gt, names in self._observed("GT").items():
            if gt != GAME_TYPE_FLAG:
                failures.append(f"GT {gt!r} != {GAME_TYPE_FLAG!r} in {_join(names)}")
        for si, names in self._observed("SI").items():
            if si != SESSION_INFO:
                failures.append(f"SI {si!r} != {SESSION_INFO!r} in {_join(names)}")
        for key, names in self.unknown_metadata_keys.items():
            failures.append(f"metadata key {key!r} has no typed accessor ({_join(names)})")

        for type_name, count in self.bytes_arguments.items():
            failures.append(f"{count} {type_name} argument(s) still decoded as raw bytes")

        for order_type, stat in sorted(self.order_types.items()):
            if not stat.in_census:
                failures.append(
                    f"order type 0x{order_type:X} is in neither Bfme2OrderType nor the "
                    f"census ({stat.count} occurrences)"
                )

        return failures

    @property
    def problems(self) -> list[str]:
        """Open surfaces still short of zero coverage - the strict failures plus the
        informational gaps (unnamed order ids, non-zero reserved patterns, crashes) that are
        expected today but track remaining work."""
        notes = list(self.strict_failures())
        unnamed = [s for s in self.order_types.values() if not s.named]
        if unnamed:
            notes.append(
                f"{len(unnamed)} of {len(self.order_types)} order ids have no Bfme2OrderType name"
            )
        nonzero1 = [v for v in self.reserved1 if v != bytes(9)]
        if nonzero1:
            notes.append(f"reserved1 carries a non-zero pattern in {len(nonzero1)} form(s)")
        if self.abnormal_end_frames:
            notes.append(f"{len(self.abnormal_end_frames)} crashed recording(s)")
        return notes

    def to_dict(self) -> dict:
        return {
            "files": len(self.files),
            "parsed": self.parsed,
            "errors": [{"file": p.name, "message": m} for p, m in self.errors],
            "header": {
                "reserved1": _hexmap(self.reserved1),
                "reserved2": _hexmap(self.reserved2),
                "unknown_tail": {str(list(k)): v for k, v in self.unknown_tail.items()},
                "crc_interval": {str(k): v for k, v in self.crc_interval.items()},
                "abnormal_end_frames": self.abnormal_end_frames,
                "custom_hero_tails": _hexmap(self.custom_hero_tails),
                "custom_hero_counts": self.custom_hero_counts,
            },
            "metadata": {
                "unknown_keys": self.unknown_metadata_keys,
                "GT": _strmap(self._observed("GT")),
                "SI": _strmap(self._observed("SI")),
                "GR": _strmap(self._observed("GR")),
            },
            "bytes_arguments": dict(self.bytes_arguments),
            "order_types": [
                {
                    "id": f"0x{s.order_type:X}",
                    "name": s.name,
                    "count": s.count,
                    "files": s.files,
                    "in_census": s.in_census,
                    "signatures": [_run_length(list(sig)) for sig in s.signatures],
                }
                for s in sorted(self.order_types.values(), key=lambda s: s.order_type)
                if not s.named
            ],
            "slots": {
                "human": _slot_dict(self.human_slots),
                "ai": _slot_dict(self.ai_slots),
            },
            "strict_failures": self.strict_failures(),
        }

    def format_text(self) -> str:
        return "\n".join(_report_lines(self))


def _valid_custom_hero_tail(tail: bytes) -> bool:
    """A custom-hero replay's trailing bytes are all-zero padding closed by the usual
    (0, 1, 1, 0, 0) words (CUSTOM_HERO_TAIL_SUFFIX)."""
    n = len(CUSTOM_HERO_TAIL_SUFFIX)
    return len(tail) >= n and tail.endswith(CUSTOM_HERO_TAIL_SUFFIX) and not any(tail[:-n])


def _join(names: Sequence[str]) -> str:
    shown = list(names)[:3]
    suffix = f" +{len(names) - 3} more" if len(names) > 3 else ""
    return ", ".join(shown) + suffix


def _hexmap(values: dict[bytes, list[str]]) -> dict[str, list[str]]:
    return {v.hex(): names for v, names in values.items()}


def _strmap(values: dict[str | None, list[str]]) -> dict[str, list[str]]:
    return {("" if k is None else k): v for k, v in values.items()}


def _slot_dict(fields: SlotRawFields) -> dict:
    return {
        "reserved": [list(r) for r in sorted(fields.reserved)],
        "nat_behavior": sorted(fields.nat_behavior),
        "tt": [list(t) for t in sorted(fields.tt, key=lambda t: tuple(x is True for x in t))],
    }


def audit(paths: Iterable[str | Path]) -> CoverageReport:
    """Audit every replay under `paths` (files or directories, recursive) and return the
    aggregated coverage. Parsing is full (the order stream is needed for order-id and
    argument coverage); files that fail to parse are recorded as errors, which a strict
    audit treats as failures."""
    report = CoverageReport(files=find_replays(paths))
    file_counts: dict[int, set[str]] = {}

    for path in report.files:
        try:
            replay = parse_replay_from_path(path)
        except Exception as exc:  # noqa: BLE001 - any parse failure is a coverage failure
            report.errors.append((path, str(exc)))
            continue
        _accumulate(report, path.name, replay, file_counts)

    for order_type, names in file_counts.items():
        report.order_types[order_type].files = len(names)
    return report


def _accumulate(
    report: CoverageReport,
    name: str,
    replay: ReplayFile,
    file_counts: dict[int, set[str]],
) -> None:
    header = replay.header
    report.reserved1.setdefault(header.reserved1, []).append(name)
    report.reserved2.setdefault(header.reserved2, []).append(name)
    if header.custom_heroes:
        # A custom-hero replay carries custom_hero_tail in place of unknown_tail.
        report.custom_hero_tails.setdefault(header.custom_hero_tail, []).append(name)
        report.custom_hero_counts[name] = len(header.custom_heroes)
    else:
        report.unknown_tail.setdefault(header.unknown_tail, []).append(name)
    report.crc_interval.setdefault(header.crc_interval, []).append(name)
    if header.abnormal_end_frame is not None:
        report.abnormal_end_frames[name] = header.abnormal_end_frame

    metadata = replay.header.metadata
    for key, value in metadata.values.items():
        report.metadata_values.setdefault(key, {}).setdefault(value, []).append(name)
        if key not in KNOWN_METADATA_KEYS:
            report.unknown_metadata_keys.setdefault(key, []).append(name)

    for slot in metadata.players:
        if slot.slot_type is ReplaySlotType.Human:
            report.human_slots.add(slot)
        elif slot.slot_type is ReplaySlotType.Computer:
            report.ai_slots.add(slot)

    for chunk in replay.chunks:
        stat = report.order_types.setdefault(chunk.order_type, OrderTypeStat(chunk.order_type))
        stat.count += 1
        signature = tuple(a.argument_type.name for a in chunk.order.arguments)
        stat.signatures[signature] += 1
        file_counts.setdefault(chunk.order_type, set()).add(name)
        for argument in chunk.order.arguments:
            if isinstance(argument.value, bytes):
                report.bytes_arguments[argument.argument_type.name] += 1


def _report_lines(report: CoverageReport) -> list[str]:
    lines: list[str] = []
    header = f"Replay format coverage - {len(report.files)} file(s), {report.parsed} parsed"
    lines.append(header)
    lines.append("=" * len(header))
    if report.errors:
        lines.append("")
        lines.append("Parse errors:")
        for path, message in report.errors:
            lines.append(f"  {path.name}: {message}")

    lines.append("")
    lines.append("Header reserved fields")
    lines.extend(_distinct_block("crc_interval", report.crc_interval, str, {CRC_INTERVAL}))
    lines.extend(
        _distinct_block("reserved1", report.reserved1, lambda b: b.hex(), RESERVED1_PATTERNS)
    )
    lines.extend(
        _distinct_block("reserved2", report.reserved2, lambda b: b.hex(), {RESERVED2_PATTERN})
    )
    lines.extend(
        _distinct_block(
            "unknown_tail", report.unknown_tail, lambda t: str(tuple(t)), {UNKNOWN_TAIL}
        )
    )
    if report.abnormal_end_frames:
        frames = ", ".join(f"{n}={f}" for n, f in report.abnormal_end_frames.items())
        lines.append(f"  abnormal_end_frame  {len(report.abnormal_end_frames)} crashed: {frames}")
    else:
        lines.append("  abnormal_end_frame  none (every recording finalized normally)")
    if report.custom_hero_counts:
        heroes = sum(report.custom_hero_counts.values())
        lines.append(
            f"  custom_heroes       {heroes} Create-A-Hero blob(s) across "
            f"{len(report.custom_hero_counts)} replay(s)"
        )

    lines.append("")
    lines.append("Metadata keys")
    lines.append(f"  typed accessors: {' '.join(sorted(KNOWN_METADATA_KEYS))}")
    if report.unknown_metadata_keys:
        for key, names in sorted(report.unknown_metadata_keys.items()):
            lines.append(f"  UNKNOWN KEY {key!r} in {_join(names)}")
    else:
        lines.append("  unknown keys:    none")
    lines.extend(_distinct_block("GT", report._observed("GT"), _repr, {GAME_TYPE_FLAG}))
    lines.extend(_distinct_block("SI", report._observed("SI"), _repr, {SESSION_INFO}))
    lines.extend(_distinct_block("GR", report._observed("GR"), _repr, None))

    lines.append("")
    lines.append("Argument values still decoded as raw bytes")
    if report.bytes_arguments:
        for type_name, count in report.bytes_arguments.most_common():
            lines.append(f"  {type_name}: {count}")
    else:
        lines.append("  none")

    lines.append("")
    named = sum(1 for s in report.order_types.values() if s.named)
    total = len(report.order_types)
    lines.append(f"Order types without a Bfme2OrderType name ({total - named} of {total} unnamed)")
    lines.append(f"  {'id':7s} {'count':>7s} {'files':>5s}  signatures")
    for stat in sorted(report.order_types.values(), key=lambda s: s.order_type):
        if stat.named:
            continue
        flag = "" if stat.in_census else "  <NEW - not in census>"
        sigs = _signatures_text(stat)
        lines.append(f"  0x{stat.order_type:<5X} {stat.count:>7d} {stat.files:>5d}  {sigs}{flag}")

    lines.append("")
    lines.append("Slot raw remainders")
    lines.append(f"  human  {_slot_line(report.human_slots)}")
    lines.append(f"  ai     {_slot_line(report.ai_slots, tt=False)}")

    lines.append("")
    failures = report.strict_failures()
    if failures:
        lines.append(f"Strict: FAIL ({len(failures)} failure(s))")
        for failure in failures:
            lines.append(f"  ! {failure}")
    else:
        lines.append("Strict: PASS (corpus matches the documented known reality)")
    return lines


def _repr(value: str | None) -> str:
    return "<absent>" if value is None else repr(value)


def _distinct_block(label, values, render, expected) -> list[str]:
    """One field's distinct-value block. `expected` is the set of values documented as the
    known reality (marks the block OK when it holds), or None when the field is expected to
    vary (a decoded value shown only for context)."""
    if not values:
        return [f"  {label:19s} (not present)"]
    ok = expected is not None and set(values) <= set(expected)
    tag = "  [constant matches reality]" if ok else ""
    lines = [f"  {label:19s} {len(values)} distinct:{tag}"]
    for value, names in sorted(values.items(), key=lambda kv: len(kv[1]), reverse=True):
        marker = "" if expected is None or value in expected else "  <unexpected>"
        lines.append(f"      {render(value):<26s} ×{len(names):<3d}{marker}")
    return lines


def _signatures_text(stat: OrderTypeStat) -> str:
    ordered = [sig for sig, _ in stat.signatures.most_common()]
    shown = [_run_length(list(sig)) for sig in ordered[:4]]
    text = " | ".join(s if s == "()" else f"({s})" for s in shown)
    if len(ordered) > 4:
        text += f" +{len(ordered) - 4} more"
    return text


def _slot_line(fields: SlotRawFields, tt: bool = True) -> str:
    reserved = "{" + ", ".join(str(tuple(r)) for r in sorted(fields.reserved)) + "}"
    parts = [f"reserved={reserved}", f"nat_behavior={sorted(fields.nat_behavior)}"]
    if tt:
        tts = ", ".join(f"accepted={t[0]}/has_map={t[1]}" for t in sorted(fields.tt, key=str))
        parts.append(f"tt={{{tts}}}")
    return "  ".join(parts)


def diff_replays(a: ReplayFile, b: ReplayFile) -> list[str]:
    """Print, field by field, which still-opaque surfaces differ between two replays - the
    Workstream 2 differential-decoding tool. Decoded context (map, players) prints as a single
    line; everything else is the raw/reserved surface where a controlled A/B pair localises an
    unknown byte."""
    ha, hb = a.header, b.header
    ma, mb = ha.metadata, hb.metadata
    lines = [
        f"A: {_context(a)}",
        f"B: {_context(b)}",
        "",
        "Opaque surfaces:",
    ]

    lines += _diff_bytes("reserved1", ha.reserved1, hb.reserved1)
    lines += _diff_bytes("reserved2", ha.reserved2, hb.reserved2)
    lines += _diff_scalar("crc_interval", ha.crc_interval, hb.crc_interval)
    lines += _diff_scalar("abnormal_end_frame", ha.abnormal_end_frame, hb.abnormal_end_frame)
    lines += _diff_scalar("local_player_index", ha.local_player_index, hb.local_player_index)
    lines += _diff_scalar("data_checksum", ha.data_checksum, hb.data_checksum)
    lines += _diff_scalar("install_id (GSID)", ma.install_id, mb.install_id)
    lines += _diff_tail(ha.unknown_tail, hb.unknown_tail)
    for key in ("GT", "SI", "GR"):
        lines += _diff_scalar(key, ma.values.get(key), mb.values.get(key))

    lines += _diff_slots(ma.players, mb.players)
    lines += _diff_order_ids(a, b)

    if len(lines) == 4:  # only the context header and the "Opaque surfaces:" title
        lines.append("  (no opaque surface differs)")
    return lines


def _context(replay: ReplayFile) -> str:
    metadata = replay.header.metadata
    players = "/".join(
        s.human_name or (s.computer_difficulty.name if s.computer_difficulty else "?")
        for s in metadata.players
    )
    return f"{metadata.map_file!r}  [{players}]  {len(replay.chunks)} chunks"


def _diff_scalar(label: str, a: object, b: object) -> list[str]:
    return [] if a == b else [f"  {label}: {a!r} -> {b!r}"]


def _diff_bytes(label: str, a: bytes, b: bytes) -> list[str]:
    if a == b:
        return []
    offsets = [i for i in range(max(len(a), len(b))) if a[i : i + 1] != b[i : i + 1]]
    return [
        f"  {label}: {a.hex()} -> {b.hex()}  (differs at byte offset(s) {offsets})",
    ]


def _diff_tail(a: tuple[int, ...], b: tuple[int, ...]) -> list[str]:
    if a == b:
        return []
    offsets = [i for i in range(max(len(a), len(b))) if _at(a, i) != _at(b, i)]
    return [f"  unknown_tail: {a} -> {b}  (differs at word(s) {offsets})"]


def _at(seq: Sequence, index: int) -> object:
    return seq[index] if index < len(seq) else None


def _diff_slots(a: list[ReplaySlot], b: list[ReplaySlot]) -> list[str]:
    lines: list[str] = []
    for index in range(max(len(a), len(b))):
        sa = a[index] if index < len(a) else None
        sb = b[index] if index < len(b) else None
        if sa is None or sb is None:
            lines.append(f"  slot {index}: {_slot_raw(sa)} -> {_slot_raw(sb)}")
            continue
        for label, va, vb in (
            ("reserved", sa.reserved, sb.reserved),
            ("nat_behavior", sa.nat_behavior, sb.nat_behavior),
            ("tt", (sa.accepted, sa.has_map), (sb.accepted, sb.has_map)),
        ):
            if va != vb:
                lines.append(f"  slot {index} {label}: {va} -> {vb}")
    return lines


def _slot_raw(slot: ReplaySlot | None) -> str:
    return "<none>" if slot is None else slot.raw


def _diff_order_ids(a: ReplayFile, b: ReplayFile) -> list[str]:
    ids_a = {c.order_type for c in a.chunks}
    ids_b = {c.order_type for c in b.chunks}
    only_a = sorted(ids_a - ids_b)
    only_b = sorted(ids_b - ids_a)
    if not only_a and not only_b:
        return []
    lines = ["  order-type ids:"]
    if only_a:
        lines.append(f"    only in A: {[hex(i) for i in only_a]}")
    if only_b:
        lines.append(f"    only in B: {[hex(i) for i in only_b]}")
    return lines
