"""MemoryBackend decode, against a synthetic engine image.

Building a fake process image keeps the whole pointer-chasing path - the object table's
entry indirection, `AsciiString` headers, the body module, horde links - in the data-free
suite. Only `ProcessMemory` needs a real game, and it is the thin part.

The image is laid out with the same offsets `EngineLayout` declares, so a wrong offset in
the layout and a wrong offset in the reader cannot cancel out: the test writes at the
documented offsets and the reader must find them there.
"""

from __future__ import annotations

import math
import struct

import pytest

from sage_live.backend import ConnectionRefused
from sage_live.memory import LAYOUT_ROTWK_201, EngineLayout, MemoryBackend
from sage_live.orders import move
from sage_live.protocol import Handshake

LAY = LAYOUT_ROTWK_201
HEAP = 0x10000000
STATIC = 0x00DE0000
STATIC_SIZE = 0x10000
HEAP_SIZE = 0x40000


class FakeImage:
    """A sparse two-region address space that behaves like a 32-bit process."""

    def __init__(self) -> None:
        self.static = bytearray(STATIC_SIZE)
        self.heap = bytearray(HEAP_SIZE)
        self._next = HEAP + 0x100
        self.closed = False

    def _region(self, address: int, size: int):
        if STATIC <= address and address + size <= STATIC + STATIC_SIZE:
            return self.static, address - STATIC
        if HEAP <= address and address + size <= HEAP + HEAP_SIZE:
            return self.heap, address - HEAP
        return None, 0

    def read(self, address: int, size: int) -> bytes | None:
        buf, offset = self._region(address, size)
        if buf is None or size <= 0:
            return None
        return bytes(buf[offset : offset + size])

    def close(self) -> None:
        self.closed = True

    def write(self, address: int, data: bytes) -> None:
        buf, offset = self._region(address, len(data))
        assert buf is not None, f"write outside the image at {address:#x}"
        buf[offset : offset + len(data)] = data

    def u32(self, address: int, value: int) -> None:
        self.write(address, struct.pack("<I", value))

    def f32(self, address: int, value: float) -> None:
        self.write(address, struct.pack("<f", value))

    def alloc(self, size: int) -> int:
        address = self._next
        self._next += (size + 15) & ~15
        assert self._next < HEAP + HEAP_SIZE, "fake heap exhausted"
        return address

    def ascii(self, text: str) -> int:
        """An AsciiString allocation: {refcount, allocated, chars...}."""
        raw = text.encode("latin-1") + b"\x00"
        address = self.alloc(LAY.string_chars + len(raw))
        self.u32(address, 1)
        self.u32(address + 4, len(raw))
        self.write(address + LAY.string_chars, raw)
        return address

    def utf16(self, text: str) -> int:
        raw = text.encode("utf-16-le") + b"\x00\x00"
        address = self.alloc(LAY.string_chars + len(raw))
        self.u32(address, 1)
        self.u32(address + 4, len(raw))
        self.write(address + LAY.string_chars, raw)
        return address

    def template(self, name: str, side: str) -> int:
        address = self.alloc(0x100)
        self.u32(address + LAY.tmpl_name, self.ascii(name))
        self.u32(address + LAY.tmpl_side, self.ascii(side))
        return address

    def body(self, health: float, max_health: float) -> int:
        address = self.alloc(0x40)
        self.f32(address + LAY.body_health, health)
        self.f32(address + LAY.body_max_health, max_health)
        return address

    def upgrade(self, upgrade_id: int, name: str, player_scoped: bool, following: int) -> int:
        address = self.alloc(0x80)
        self.u32(address + LAY.upgrade_name, self.ascii(name))
        self.write(address + LAY.upgrade_index, struct.pack("<i", upgrade_id))
        self.write(address + LAY.upgrade_type, struct.pack("<i", 0 if player_scoped else 1))
        self.u32(address + LAY.upgrade_next, following)
        return address

    def upgrade_center(self, rows: list[tuple[int, str, bool]]) -> int:
        """The engine's upgrade registry, as (id, name, player_scoped) rows.

        Built by prepending, because that is how the engine builds it: the head of the list is
        the *last* upgrade registered, and each template carries its own id.
        """
        node = 0
        for upgrade_id, name, player_scoped in rows:
            node = self.upgrade(upgrade_id, name, player_scoped, node)
        address = self.alloc(0x40)
        self.u32(address + LAY.uc_list, node)
        self.u32(address + LAY.uc_count, max((row[0] for row in rows), default=-1) + 1)
        self.u32(LAY.the_upgrade_center, address)
        return address

    def set_upgrade_bit(self, base_ptr: int, base: int, upgrade_id: int) -> None:
        """Set one upgrade's bit in a mask, the way the engine indexes it."""
        word, bit = divmod(upgrade_id, 32)
        address = base_ptr + base + word * 4
        raw = self.read(address, 4)
        assert raw is not None
        self.u32(address, struct.unpack("<I", raw)[0] | 1 << bit)

    def game_object(
        self,
        template: int,
        position: tuple[float, float, float],
        angle: float = 0.0,
        body: int | None = None,
        list_prev: int | None = None,
    ) -> int:
        # 0x400, not 0x300: the object's upgrade mask runs to +0x308 and the team pointer sits
        # at +0x31C, so a smaller allocation would have one object's fields read as the next
        # object's - and the reader would look correct while crossing a boundary.
        address = self.alloc(0x400)
        self.u32(address + LAY.obj_template, template)
        self.f32(address + LAY.obj_pos_x, position[0])
        self.f32(address + LAY.obj_pos_y, position[1])
        self.f32(address + LAY.obj_pos_z, position[2])
        self.f32(address + LAY.obj_cos, math.cos(angle))
        self.f32(address + LAY.obj_sin, math.sin(angle))
        if body is not None:
            self.u32(address + LAY.obj_body, body)
        if list_prev is not None:
            self.u32(address + LAY.obj_list_prev, list_prev)
        return address

    def entry(self, object_id: int, obj: int) -> int:
        address = self.alloc(0x20)
        self.u32(address + LAY.entry_id, object_id)
        self.u32(address + LAY.entry_object, obj)
        return address

    def game_logic(self, frame: int, entries: list[int], slots: int = 64) -> int:
        table = self.alloc(slots * 4)
        for i, ent in enumerate(entries):
            self.u32(table + i * 4, ent)
        address = self.alloc(0x200)
        self.u32(address + LAY.gl_frame, frame)
        self.u32(address + LAY.gl_table_begin, table)
        self.u32(address + LAY.gl_table_end, table + slots * 4)
        self.u32(address + LAY.gl_object_count, len(entries))
        self.u32(LAY.the_game_logic, address)
        return address

    def player(self, name: str, side: str, resources: int, collected: int = 0) -> int:
        address = self.alloc(0x400)
        self.u32(address + LAY.player_name, self.ascii(name))
        self.u32(address + LAY.player_side, self.ascii(side))
        self.u32(address + LAY.player_display_name, self.utf16(name))
        self.write(address + LAY.player_resources, struct.pack("<i", resources))
        self.write(address + LAY.player_resources_collected, struct.pack("<i", collected))
        return address

    def player_list(self, players: list[int], local: int) -> int:
        address = self.alloc(0x100)
        self.u32(address + LAY.pl_count, len(players))
        self.u32(address + LAY.pl_local_player, players[local])
        for i, p in enumerate(players):
            self.u32(address + LAY.pl_array + i * 4, p)
        self.u32(LAY.the_player_list, address)
        return address


def build_game() -> FakeImage:
    """A solo skirmish: a neutral placeholder, creeps, and one human with a horde."""
    img = FakeImage()

    neutral = img.alloc(0x400)  # no name, no side: the placeholder slot
    creeps = img.player("PlyrCreeps", "Civilian", 1000)
    human = img.player("Player_1", "Men", 2870, collected=5020)
    img.player_list([neutral, creeps, human], local=2)

    fighter_t = img.template("GondorFighter", "Men")
    horde_t = img.template("GondorFighterHorde", "Men")
    lair_t = img.template("MoriarGoblinLair", "Neutral")

    horde = img.game_object(horde_t, (2155.0, 3445.0, 61.0), body=img.body(1.0, 1.0))
    fighter_a = img.game_object(
        fighter_t, (2153.0, 3443.0, 61.0), angle=0.849, body=img.body(237.0, 255.0), list_prev=horde
    )
    fighter_b = img.game_object(
        fighter_t, (2170.0, 3450.0, 61.0), body=img.body(255.0, 255.0), list_prev=horde
    )
    lair = img.game_object(lair_t, (1422.0, 3095.0, 88.0), body=img.body(2000.0, 2000.0))

    img.game_logic(
        8688,
        [
            img.entry(132, horde),
            img.entry(133, fighter_a),
            img.entry(134, fighter_b),
            img.entry(124, lair),
        ],
    )
    return img


def backend(img: FakeImage, **kw) -> MemoryBackend:
    b = MemoryBackend(img, **kw)
    b.connect()
    return b


def test_connect_refuses_when_no_game_is_running():
    with pytest.raises(ConnectionRefused, match="TheGameLogic is null"):
        MemoryBackend(FakeImage()).connect()


def test_connect_refuses_a_handshake_mismatch():
    img = build_game()
    peer = Handshake(engine_build="RotWK 2.01")
    expected = Handshake(engine_build="RotWK 2.02")
    with pytest.raises(ConnectionRefused, match="engine build"):
        MemoryBackend(img, handshake=peer, expect=expected).connect()


def test_frame_is_read_from_game_logic():
    assert backend(build_game()).frame() == 8688


def test_players_exclude_the_unnamed_placeholder_slot():
    players = backend(build_game()).read_players()
    assert [p.name for p in players] == ["PlyrCreeps", "Player_1"]
    assert [p.faction for p in players] == ["Civilian", "Men"]


def test_player_economy_reads_both_pool_and_cumulative():
    human = next(p for p in backend(build_game()).read_players() if p.name == "Player_1")
    assert human.resources == 2870
    assert human.resources_collected == 5020
    assert human.spent == 2150


def test_local_player_index_matches_the_player_list_pointer():
    # slot 2 in the raw array, but slot 0 is skipped as a placeholder
    assert backend(build_game()).local_player_index() == 2


def test_objects_resolve_template_side_and_position():
    objects = {o.object_id: o for o in backend(build_game()).read_objects()}
    assert set(objects) == {132, 133, 124, 134}

    fighter = objects[133]
    assert fighter.template_name == "GondorFighter"
    assert fighter.template_side == "Men"
    assert fighter.position == pytest.approx((2153.0, 3443.0, 61.0))
    assert fighter.angle == pytest.approx(0.849, rel=1e-4)

    lair = objects[124]
    assert lair.template_name == "MoriarGoblinLair"
    assert lair.template_side == "Neutral"


def test_health_is_a_fraction_and_max_is_absolute():
    objects = {o.object_id: o for o in backend(build_game()).read_objects()}
    assert objects[133].health == pytest.approx(237.0 / 255.0)
    assert objects[133].max_health == pytest.approx(255.0)
    assert objects[133].is_damaged
    assert objects[134].health == pytest.approx(1.0)
    assert not objects[134].is_damaged


def test_parent_id_is_not_claimed():
    """`Object+0x8C`/`+0x90` are the global object list's next/prev, not a container link, so
    horde membership is not readable and is reported as absent rather than guessed."""
    assert all(o.parent_id is None for o in backend(build_game()).read_objects())


def test_an_object_without_a_body_is_not_reported_as_damaged():
    """Inert map markers carry an uninitialised body whose max reads as a denormal."""
    img = build_game()
    marker_t = img.template("WallHubTemplate", "Neutral")
    marker = img.game_object(marker_t, (10.0, 20.0, 30.0), body=img.body(0.0, 1.8191141e-38))
    img.game_logic(1, [img.entry(1, marker)])
    obj = backend(img).read_objects()[0]
    assert obj.max_health == 0.0
    assert obj.has_body is False
    assert obj.is_damaged is False, "no body must not read as destroyed"
    assert obj.health == 1.0


def test_owner_index_is_unresolved_when_no_team_is_wired_up():
    """Ownership is a `Team*` on the object, inverted through each player's own team. This image
    sets neither, so every object must answer None - never a plausible guess from Side."""
    assert all(o.owner_index is None for o in backend(build_game()).read_objects())


def test_observe_assembles_a_whole_snapshot():
    obs = backend(build_game()).observe()
    assert obs.frame == 8688
    assert obs.local_player == 2
    assert len(obs.players) == 2
    assert len(obs.objects) == 4
    assert obs.fogged is False, "an external reader sees the whole map and must say so"


def test_by_side_filters_objects():
    obs = backend(build_game()).observe()
    assert {o.template_name for o in obs.by_side("Men")} == {
        "GondorFighter",
        "GondorFighterHorde",
    }


def test_poll_before_connect_is_a_diagnostic():
    b = MemoryBackend(build_game())
    assert b.poll() is None
    assert any("before connect" in d.message for d in b.diagnostics)


def test_send_is_refused_with_an_explanation():
    b = backend(build_game())
    assert b.send([move(0, (1.0, 2.0, 3.0))]) == 0
    assert any("observation-only" in d.message for d in b.diagnostics)


def test_garbage_entries_are_skipped_not_fatal():
    img = build_game()
    gl = img.read(LAY.the_game_logic, 4)
    assert gl is not None
    gl_ptr = struct.unpack("<I", gl)[0]
    table = struct.unpack("<I", img.read(gl_ptr + LAY.gl_table_begin, 4))[0]
    # a wild pointer and a null in the middle of the table
    img.u32(table + 4 * 8, 0xDEADBEEF)
    img.u32(table + 4 * 9, 0)
    objects = backend(img).read_objects()
    assert len(objects) == 4, "real objects should survive a corrupt neighbour"


def test_a_template_name_that_is_not_an_identifier_is_rejected():
    """A pointer chain landing on prose means it is not a ThingTemplate at all."""
    img = build_game()
    bad_t = img.template("not a template name", "Men")
    obj = img.game_object(bad_t, (0.0, 0.0, 0.0))
    img.game_logic(1, [img.entry(900, obj)])
    assert backend(img).read_objects() == ()


def test_a_custom_layout_is_honoured():
    """A different build supplies different offsets; nothing may be hard-coded."""
    shifted = EngineLayout(gl_frame=0x44)
    img = build_game()
    gl_ptr = struct.unpack("<I", img.read(LAY.the_game_logic, 4))[0]
    img.u32(gl_ptr + 0x44, 4242)
    b = MemoryBackend(img, layout=shifted)
    b.connect()
    assert b.frame() == 4242


def test_close_releases_the_source():
    img = build_game()
    b = backend(img)
    b.close()
    assert img.closed


# ---------------------------------------------------------------------------
# Upgrades. Two scopes, two places, and one field that lies if taken at face value.
#
# Measured live: researching a faction-wide upgrade sets the player's in-progress bit and clears
# it on completion, while a per-battalion purchase sets the *same* in-progress mask and never
# clears it - the completion shows up on the object instead. So the reader has to filter the
# in-progress mask by scope, and these tests pin that rather than the offsets.

REGISTRY = [
    (420, "Upgrade_MarketplaceUpgradeIronOre", True),
    (472, "Upgrade_TechnologyGondorForgedBlades", True),
    (473, "Upgrade_GondorForgedBlades", False),
    (475, "Upgrade_GondorHeavyArmor", False),
]


def build_upgraded_game() -> tuple[FakeImage, int, int]:
    """A game where one faction tech is researched and one battalion has forged blades."""
    img = FakeImage()
    img.upgrade_center(REGISTRY)

    creeps = img.player("PlyrCreeps", "Civilian", 1000)
    human = img.player("Player_1", "Men", 2870)
    img.player_list([creeps, human], local=1)

    # Faction tech: completed, so the in-progress bit is gone.
    img.set_upgrade_bit(human, LAY.player_upgrades_completed, 472)
    # A second tech still being researched.
    img.set_upgrade_bit(human, LAY.player_upgrades_in_progress, 420)
    # The battalion purchase: the engine leaves this bit set on the player forever.
    img.set_upgrade_bit(human, LAY.player_upgrades_in_progress, 473)

    horde_t = img.template("GondorFighterHorde", "Men")
    fighter_t = img.template("GondorFighter", "Men")
    horde = img.game_object(horde_t, (0.0, 0.0, 0.0), body=img.body(1.0, 1.0))
    upgraded = img.game_object(fighter_t, (1.0, 0.0, 0.0), body=img.body(510.0, 510.0))
    plain = img.game_object(fighter_t, (2.0, 0.0, 0.0), body=img.body(255.0, 255.0))
    for obj in (horde, upgraded):
        img.set_upgrade_bit(obj, LAY.obj_upgrades_completed, 473)

    img.game_logic(500, [img.entry(132, horde), img.entry(133, upgraded), img.entry(148, plain)])
    return img, 132, 148


def test_upgrade_table_is_read_from_the_engine_registry():
    """Names come from the running game, so no ini load is needed to report an upgrade."""
    img, _, _ = build_upgraded_game()
    table = backend(img).upgrade_table()
    assert {i: d.name for i, d in table.items()} == {i: n for i, n, _ in REGISTRY}
    assert table[472].player_scoped is True
    assert table[473].player_scoped is False


def test_player_upgrades_are_the_completed_faction_wide_ones():
    img, _, _ = build_upgraded_game()
    human = next(p for p in backend(img).read_players() if p.name == "Player_1")
    assert human.upgrades == {"Upgrade_TechnologyGondorForgedBlades"}


def test_in_progress_hides_the_object_upgrade_the_engine_never_clears():
    """The trap this filter exists for: bit 473 is set in the player's in-progress mask and
    stays set for the rest of the match, so reporting it would claim a battalion upgrade is
    pending forever. Only the player-scoped one is a real answer."""
    img, _, _ = build_upgraded_game()
    human = next(p for p in backend(img).read_players() if p.name == "Player_1")
    assert human.upgrades_in_progress == {"Upgrade_MarketplaceUpgradeIronOre"}
    assert "Upgrade_GondorForgedBlades" not in human.upgrades_in_progress


def test_object_upgrades_are_read_from_the_object():
    """A per-battalion upgrade appears in no other field - not the template name, not the
    player - so an object that reports none really has none. The horde and its upgraded member
    both carry it, which is what the engine does and what a counting consumer must expect."""
    img, horde_id, plain_id = build_upgraded_game()
    objects = {o.object_id: o for o in backend(img).read_objects()}
    assert objects[horde_id].upgrades == {"Upgrade_GondorForgedBlades"}
    assert objects[133].upgrades == {"Upgrade_GondorForgedBlades"}
    assert objects[plain_id].upgrades == frozenset(), "the untouched battalion must be empty"
    assert objects[133].template_name == objects[plain_id].template_name


def test_a_player_upgrade_does_not_leak_onto_objects():
    """The two scopes share one id space and one bitset layout, so a scope filter is the only
    thing keeping a faction tech out of an object's set."""
    img, _, _ = build_upgraded_game()
    objects = backend(img).read_objects()
    assert all("Upgrade_TechnologyGondorForgedBlades" not in o.upgrades for o in objects)


def test_bits_past_the_registered_count_are_never_decoded():
    """The masks are wider than the ids in use (the two player masks sit 0x90 apart, where 976
    upgrades need 0x7C), so a stray bit in the unused tail must not become an upgrade."""
    img, _, _ = build_upgraded_game()

    def human_upgrades() -> frozenset[str]:
        return next(p for p in backend(img).read_players() if p.name == "Player_1").upgrades

    before = human_upgrades()
    list_ptr = struct.unpack("<I", img.read(LAY.the_player_list, 4))[0]
    player_ptr = struct.unpack("<I", img.read(list_ptr + LAY.pl_array + 4, 4))[0]
    img.set_upgrade_bit(player_ptr, LAY.player_upgrades_completed, 900)
    assert human_upgrades() == before, "bit 900 is past the registry, so it names nothing"


def test_upgrades_are_empty_and_diagnosed_without_a_registry():
    """An older or differently-laid-out build should report nothing rather than garbage."""
    b = backend(build_game())
    assert b.upgrade_table() == {}
    assert all(p.upgrades == frozenset() for p in b.read_players())
    assert all(o.upgrades == frozenset() for o in b.read_objects())
    assert any("TheUpgradeCenter is null" in d.message for d in b.diagnostics)
