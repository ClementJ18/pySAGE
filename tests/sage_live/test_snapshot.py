"""The decode, replayed against bytes a real engine laid out.

Every other test in this package builds its own process image, which makes them tests of the
*reader* and not of the layout: the fixture writes each field where `EngineLayout` says it is,
so a wrong offset in the layout is written wrong and read wrong and the test passes. That is
the one failure this package most needs to catch, because a wrong offset does not raise - it
reports plausible nonsense.

These bytes were laid out by the engine. Nothing here can cancel out against a wrong belief,
so a layout that stops being true fails in the data-free suite rather than waiting for someone
to notice a live reading looks odd.

Regenerate with `examples/sage_live/capture_snapshot.py` during a match - deliberately, since
overwriting the golden file erases whatever regression it would have caught.

Two things the fixture deliberately does not contain, so a reader is not puzzled by them.
**The registries are absent**: walking `TheThingFactory` and `TheSpecialPowerStore` would take
the capture from ~170 KB to ~1.8 MB for facts corroborated on their own terms, so a production
entry here carries its kind and an empty name, and the decode logs a diagnostic saying the
factory is null. **The PE header ranges were captured from the same process a moment later**,
at the menu, because the first capture ran `connect` before the recorder was in place; they
were checked byte-for-byte against the on-disk `game.dat` they were mapped from before being
merged in. Everything else is one uninterrupted capture of one live match.

**The capture predates the batched reader**, so it holds only the narrow ranges the old
per-field path touched and the wide reads miss the gaps between them. The decode therefore
takes its fallback path here and still produces the golden result, which is the fallback's
contract - but it means this fixture does not exercise the fast path. Re-capturing during any
future match records the new pattern and fixes that; nothing is wrong until then.

**Both bit-order name tables are outside the capture**, so `conditions` and `status` decode
empty for every object in the golden file. That is the sparse snapshot behaving as documented,
not the engine saying an object is in no state at all - do not read those two fields here as
facts about the match.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sage_live.backends.memory import MemoryBackend
from sage_live.backends.snapshot import RecordingSource, SnapshotSource

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT = FIXTURES / "match.snapshot.gz"
EXPECTED = FIXTURES / "match.expected.json"


@pytest.fixture(scope="module")
def observation():
    backend = MemoryBackend(SnapshotSource.load(SNAPSHOT))
    backend.connect()
    return backend.observe()


@pytest.fixture(scope="module")
def golden():
    return json.loads(EXPECTED.read_text(encoding="utf-8"))


def stable(value):
    """The decoded structure with the last bits of `angle` taken off.

    Every number in a decode is read out of the capture and is bit-identical on any machine -
    every one except `angle`, which is `math.atan2` of two of them, and whose last bit is the
    platform's libm rather than the engine's. The golden file was captured on Windows; two of
    this match's objects come back one ULP away on a Linux runner (`3.12396693249735` against
    `3.1239669324973502`), which says nothing about the decode.

    Twelve decimals is orders of magnitude below that difference and orders of magnitude above
    anything a wrong offset, scale or sign could hide in - those move a value, not its last bit.
    """
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [stable(item) for item in value]
    return value


def test_the_whole_observation_matches_the_golden_decode(observation, golden):
    """One assertion over every field of every object and player. A change anywhere in the
    decode - an offset, a scale, a sign - shows up here.

    Compared through JSON on both sides, because the golden file has been through it: a
    `position` is a tuple in the model and a list once written out, and `(0, 500) != [0, 500]`
    would fail for a reason that has nothing to do with the decode.
    """
    assert stable(json.loads(json.dumps(observation.to_dict()))) == stable(golden)


def test_connect_identifies_the_build_from_real_pe_headers(observation):
    """The build gate, against headers the loader mapped rather than ones a test wrote."""
    backend = MemoryBackend(SnapshotSource.load(SNAPSHOT))
    handshake = backend.connect()
    assert handshake.data_checksum == "pe-460da09e"
    assert backend.identity is not None
    assert ".text" in backend.identity.section_names


def test_a_real_match_has_the_shape_a_match_has(observation):
    """Cheap sanity on the capture itself, so a fixture regenerated from the menu - where the
    shell map yields an empty world - cannot quietly become the baseline."""
    assert observation.in_match
    assert len(observation.objects) > 100
    assert observation.me is not None and observation.me.playing


def test_containment_survives_a_real_decode(observation):
    """`Object+0x27C`. Every member must name a container that is really there, and no
    container may be contained."""
    members = [o for o in observation.objects if o.parent_id is not None]
    assert members, "the captured match had battalions in it"
    parents = {o.parent_id for o in members}
    for parent_id in parents:
        assert observation.obj(parent_id) is not None, "a container that is not in the table"
    assert not (parents & {m.object_id for m in members}), "a container is not itself contained"


def test_the_producer_id_agrees_with_containment_on_a_real_match(observation):
    """`Object+0x78`. It is read for the case where the two *disagree* - a unit that has left
    its battalion still names it - so what makes the offset right is that on a healthy match
    they agree everywhere: all 40 members of this capture name their own container.

    Objects produced by something that does not contain them are ordinary and left alone here:
    a lair's spawned creeps and a structure's fences both carry a producer and no parent.
    """
    members = [o for o in observation.objects if o.parent_id is not None]
    assert members, "the captured match had battalions in it"
    assert all(o.producer_id == o.parent_id for o in members)
    assert all(observation.obj(o.producer_id) is not None for o in members)


def test_orderable_drops_the_members_of_a_real_battalion(observation):
    owned = observation.owned_by(observation.local_player)
    orderable = observation.orderable(observation.local_player)
    assert len(orderable) < len(owned), "a real match has battalions, so some are excluded"
    assert all(o.parent_id is None for o in orderable)


def test_object_scoped_upgrades_decode_from_real_bitmasks(observation):
    """The two upgrade masks are bit-indexed by the engine's own ids, so a wrong word size or
    a wrong base reads as a different upgrade rather than as an error."""
    upgraded = [o for o in observation.objects if o.upgrades]
    assert len(upgraded) > 50
    assert all(name.lower().startswith("upgrade_") for o in upgraded for name in o.upgrades)


def test_a_snapshot_serves_reads_it_did_not_record_the_size_of():
    """Ranges, not reads: the fixture must survive a change to how the decode batches its
    reads, which alters every size and no address."""
    source = SnapshotSource.load(SNAPSHOT)
    backend = MemoryBackend(source)
    backend.connect()
    one = source.read(backend.layout.the_game_logic, 4)
    two = source.read(backend.layout.the_game_logic, 2)
    assert one is not None and two == one[:2]


def test_an_address_outside_the_capture_reads_as_unreadable():
    """What a real source does for an unmapped address. A decode that wanders off the recorded
    path degrades to None rather than to convincing wrong bytes."""
    source = SnapshotSource.load(SNAPSHOT)
    assert source.read(0x7FFF0000, 4) is None
    assert source.misses == 1


def test_recording_refuses_to_write():
    """A capture that could write would change what it is recording."""
    recorder = RecordingSource(SnapshotSource.load(SNAPSHOT))
    with pytest.raises(AssertionError):
        recorder.write(0x1000, b"\x00")


def test_a_recording_round_trips_through_the_file_format(tmp_path):
    recorder = RecordingSource(SnapshotSource.load(SNAPSHOT))
    recorder.read(0x00DE412C, 4)
    recorder.read(0x00DE4928, 4)
    path = tmp_path / "round.gz"
    recorder.save(path)
    back = SnapshotSource.load(path)
    assert back.read(0x00DE412C, 4) == recorder.spans[0][1]


def test_the_fixture_omits_the_registries_on_purpose(observation):
    """Stated as a test so the empty production names and the "factory is null" diagnostic
    read as a deliberate trade rather than as a decode that lost something."""
    producing = [o for o in observation.objects if o.producing]
    assert producing, "the captured match had a building working"
    assert all(item.kind for item in producing[0].production)
    assert all(item.name == "" for item in producing[0].production)
