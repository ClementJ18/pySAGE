"""Re-emit a translated replay against a different game version - the inverse of translation.

`translated.py` resolves a replay's version-coupled integer ids to code names; this module takes
such a (v2) document and a *target* game's `GameData` and produces a `ReplayFile` whose ids are
valid integers for THAT version: template/upgrade/science/power names looked up in the target's
tables, fortress-hero recruits re-run through a `ReviveList` built from the target's rosters and
build times (the same simulation the forward direction uses, driven by name instead of slot),
and slot faction indices in the metadata string re-pointed at the target's PlayerTemplate order.
The result serializes to a real `.BfME2Replay` via `sage_replay.serialize`.

The header is rebuilt verbatim from the document's raw surface, then optionally re-identified
from a *donor* replay recorded under the target version: `version`, `build_date`,
`data_checksum`, and the metadata `GSID` are the engine's own patch identity - none of them can
be computed here, so without a donor the emitted file keeps the source's identity and the target
game will flag it as recorded on different data.

Resolution is all-or-nothing: any name the target lacks (a renamed or removed template, a hero
outside the target roster) and any id the source translation itself left raw is collected and
raised as one `RetargetError` - a silently wrong id would corrupt the simulation, and dropping a
chunk would shift every later revive-menu position, so a partial file is never written.

What conversion cannot fix: `ObjectId` arguments are runtime simulation ids and pass through
unchanged, and the `0x44A` checksum heartbeats belong to the source simulation - a target
version whose gameplay data differs at all will diverge from them during playback. The order
stream's ids are exact; agreement between two different simulations is not promised.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

from sage_replay.heroes import ReviveList
from sage_replay.narrate import GameData
from sage_replay.replay import (
    OrderArgumentType,
    ReplayChunk,
    ReplayFile,
    ReplayGameType,
    ReplayHeader,
    ReplayMetadata,
    ReplayTimestamp,
    first_bool,
    integer_arguments,
)
from sage_replay.translated import (
    _POWER_ORDERS,
    _THING_ORDERS,
    _UPGRADE_ORDERS,
    TranslatedReplay,
    TranslatedSlot,
)
from sage_utils.stream import BinaryStream

__all__ = ["RetargetError", "retarget"]

# The replay-id offset of each 1-based table and the upgrade space's +3 (see narrate.GameData).
_UPGRADE_OFFSET = 3


class RetargetError(ValueError):
    """Raised when the document cannot be fully re-resolved against the target game. Carries
    every failure, not just the first, so one pass names everything that blocks a conversion."""

    def __init__(self, failures: list[str]) -> None:
        self.failures = failures
        summary = "; ".join(failures[:5]) + ("; ..." if len(failures) > 5 else "")
        super().__init__(f"{len(failures)} unresolvable against the target game: {summary}")


def retarget(
    document: TranslatedReplay,
    target: GameData,
    donor: ReplayFile | None = None,
) -> ReplayFile:
    """The document as a `ReplayFile` whose ids are valid for the `target` game, ready for
    `serialize.serialize_replay`. `donor` is a replay recorded under the target version, the
    source of the emitted header's patch identity (version/build-date strings, data checksum,
    metadata GSID); without one the source identity is kept. Raises `ValueError` for a v1
    document (no raw header - re-translate the replay to produce a v2 one) or a non-BFME2
    document/donor, and `RetargetError` when any id fails to resolve."""
    if document.header is None:
        raise ValueError(
            "document is format v1 (analysis-only); re-translate the replay against the "
            "recording game to produce a v2 document that carries the raw header"
        )
    if document.game_type != ReplayGameType.Bfme2.name:
        raise ValueError(f"can only retarget Bfme2 documents, not {document.game_type}")
    if donor is not None and donor.game_type is not ReplayGameType.Bfme2:
        raise ValueError(f"donor must be a Bfme2 replay, not {donor.game_type.name}")

    failures: list[str] = []
    replay = document.to_replay(target)
    _resolve_chunks(replay, document, target, failures)
    header = _build_header(document, target, donor, failures)
    if failures:
        raise RetargetError(failures)
    return ReplayFile(header=header, chunks=replay.chunks, translated=False)


def _resolve_chunks(
    replay: ReplayFile, document: TranslatedReplay, target: GameData, failures: list[str]
) -> None:
    """Replace every resolved code name in the rehydrated chunks with the target game's
    integer id, in place - the exact mirror of `translated._translate_ids`, including the
    `0x414` second-integer science and the `0x417/0x418` boolean mode switch."""
    things = {name: index + 1 for index, name in enumerate(target.object_order)}
    upgrades = {name: index + _UPGRADE_OFFSET for index, name in enumerate(target.upgrades)}
    powers = {name: index + 1 for index, name in enumerate(target.specialpowers)}
    sciences = {name: index + 1 for index, name in enumerate(target.sciences)}
    revives: dict[int, ReviveList | None] = {}
    spf = document.seconds_per_frame

    for chunk in replay.chunks:
        order = chunk.order_type
        ints = integer_arguments(chunk)
        if not ints:
            continue
        if order in (0x417, 0x418):
            if first_bool(chunk):
                _resolve_hero(chunk, replay, document, target, revives, spf, failures)
            else:
                _resolve(chunk, 0, things, "thing template", failures)
        elif order in _THING_ORDERS:
            _resolve(chunk, 0, things, "thing template", failures)
        elif order in _UPGRADE_ORDERS:
            _resolve(chunk, 0, upgrades, "upgrade", failures)
        elif order in _POWER_ORDERS:
            _resolve(chunk, 0, powers, "special power", failures)
        elif order == 0x414 and len(ints) >= 2:
            _resolve(chunk, 1, sciences, "science", failures)


def _resolve(
    chunk: ReplayChunk, which: int, table: dict[str, int], space: str, failures: list[str]
) -> None:
    """Turn the `which`-th Integer argument's code name back into the target's id. A raw int
    in the position means the source translation itself failed to resolve it - equally fatal,
    since the number indexes the *source* game."""
    value = integer_arguments(chunk)[which]
    if isinstance(value, str):
        target_id = table.get(value)
        if target_id is None:
            failures.append(
                f"chunk @{chunk.timecode} 0x{chunk.order_type:x}: "
                f"{space} {value!r} does not exist in the target game"
            )
        else:
            _set_int(chunk, which, target_id)
    else:
        failures.append(
            f"chunk @{chunk.timecode} 0x{chunk.order_type:x}: "
            f"{space} id {value} was never resolved to a name by the translation"
        )


def _resolve_hero(
    chunk: ReplayChunk,
    replay: ReplayFile,
    document: TranslatedReplay,
    target: GameData,
    revives: dict[int, ReviveList | None],
    spf: float,
    failures: list[str],
) -> None:
    """A `0x417`/`0x418` flag=True fortress-hero order: turn the resolved hero name into the
    position it holds in the *target* game's revive submenu at this moment, via the same
    stateful `ReviveList` the forward resolution ran - built here from the target's roster and
    build times, so the emitted slot ids follow the target's own menu dynamics."""
    where = f"chunk @{chunk.timecode} 0x{chunk.order_type:x}"
    name = integer_arguments(chunk)[0]
    if not isinstance(name, str):
        failures.append(f"{where}: hero slot {name} was never resolved by the translation")
        return
    index = replay.slot_index(chunk)
    if index is None:
        failures.append(f"{where}: hero recruit by an unmappable player number {chunk.number}")
        return
    if index not in revives:
        revives[index] = _revive_list(document.players[index], document.map, target)
    revive = revives[index]
    if revive is None:
        failures.append(
            f"{where}: no target revive roster for player {document.players[index].name!r}"
        )
        return
    seconds = chunk.timecode * spf
    if chunk.order_type == 0x417:
        slot = revive.slot_of(seconds, name)
    else:
        slot = revive.cancel_slot_of(seconds, name)
    if slot is None:
        failures.append(f"{where}: hero {name!r} is not on the target revive roster")
    else:
        _set_int(chunk, 0, slot)


def _revive_list(slot: TranslatedSlot, map_file: str, target: GameData) -> ReviveList | None:
    """The target-game revive submenu for one player: their faction (the slot's own, or the
    inferred roll for a lobby Random) looked up in the target's PlayerTemplate order, then that
    faction's map-aware roster. None when the faction or roster is unknowable."""
    faction = slot.faction or slot.inferred_faction
    if faction is None or faction not in target.faction_names:
        return None
    roster = target.hero_roster_for(map_file, target.faction_names.index(faction))
    if not roster:
        return None
    return ReviveList(roster, target.hero_build_times)


def _set_int(chunk: ReplayChunk, which: int, value: int) -> None:
    """Overwrite the `which`-th Integer argument's value."""
    seen = -1
    for argument in chunk.order.arguments:
        if argument.argument_type is OrderArgumentType.Integer:
            seen += 1
            if seen == which:
                argument.value = value
                return


def _build_header(
    document: TranslatedReplay,
    target: GameData,
    donor: ReplayFile | None,
    failures: list[str],
) -> ReplayHeader:
    """The emitted header: the document's raw surface verbatim, with the slot faction indices
    re-pointed at the target's PlayerTemplate order and, when a donor is given, the patch
    identity replaced by the donor's."""
    raw = document.header
    assert raw is not None  # retarget() has already refused a v1 document
    metadata_raw = _patch_metadata(raw.metadata, document.players, target, donor, failures)
    stream = BinaryStream(BytesIO(metadata_raw.encode("ascii") + b"\x00"))
    metadata = ReplayMetadata.parse(stream, ReplayGameType.Bfme2)
    return ReplayHeader(
        game_type=ReplayGameType.Bfme2,
        start_time=datetime.fromtimestamp(raw.start_time, tz=UTC),
        end_time=datetime.fromtimestamp(raw.end_time, tz=UTC),
        num_timecodes=document.num_timecodes,
        filename=raw.filename,
        timestamp=ReplayTimestamp(*raw.timestamp),
        version=donor.header.version if donor else raw.version,
        build_date=donor.header.build_date if donor else raw.build_date,
        metadata=metadata,
        local_player_index=document.local_player_index,
        local_player_raw=raw.local_player_raw,
        crc_interval=raw.crc_interval,
        abnormal_end_frame=raw.abnormal_end_frame,
        reserved1=bytes.fromhex(raw.reserved1),
        data_checksum=donor.header.data_checksum if donor else raw.data_checksum,
        reserved2=bytes.fromhex(raw.reserved2),
        unknown_tail=raw.unknown_tail,
        custom_heroes=[bytes.fromhex(blob) for blob in raw.custom_heroes],
        custom_hero_flags=raw.custom_hero_flags,
        custom_hero_tail=bytes.fromhex(raw.custom_hero_tail),
    )


def _patch_metadata(
    raw: str,
    players: list[TranslatedSlot],
    target: GameData,
    donor: ReplayFile | None,
    failures: list[str],
) -> str:
    """The metadata string with only the version-coupled values rewritten: each occupied
    slot's faction field re-indexed against the target's PlayerTemplate order (the -1 Random
    and -2 observer sentinels are version-independent and stay), and `GSID` replaced by the
    donor's (it co-varies 1:1 with `data_checksum`). Every other byte - entry order, unknown
    keys, empty-slot markers, network fields - is preserved verbatim."""
    donor_gsid = donor.header.metadata.values.get("GSID") if donor is not None else None
    entries = raw.split(";")
    for position, entry in enumerate(entries):
        key, sep, value = entry.partition("=")
        if not sep:
            continue
        if key == "S":
            entries[position] = f"S={_patch_slots(value, players, target, failures)}"
        elif key == "GSID" and donor_gsid is not None:
            entries[position] = f"GSID={donor_gsid}"
    return ";".join(entries)


def _patch_slots(
    value: str, players: list[TranslatedSlot], target: GameData, failures: list[str]
) -> str:
    """The `S=` slot list with each occupied slot's faction field rewritten. The occupied
    slot strings pair up with the document's players in order; a named faction missing from
    the target's PlayerTemplates is a collected failure."""
    slots = value.split(":")
    occupied = iter(players)
    for position, slot in enumerate(slots):
        if not slot or slot[0] not in ("H", "C"):
            continue
        player = next(occupied, None)
        if player is None:
            failures.append("metadata slot list has more occupied slots than the document")
            break
        faction = player.faction
        if player.observer or faction is None:
            continue  # -2 / -1 sentinels are version-independent
        if faction not in target.faction_names:
            failures.append(f"faction {faction!r} does not exist in the target game")
            continue
        index = target.faction_names.index(faction)
        fields = slot.split(",")
        field_at = 5 if slot[0] == "H" else 2
        if len(fields) > field_at:
            fields[field_at] = str(index)
            slots[position] = ",".join(fields)
    return ":".join(slots)
