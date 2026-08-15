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
from collections.abc import Sequence

import pytest

from sage_live.api.orders import move
from sage_live.backends.base import ConnectionRefused, GameExited
from sage_live.backends.identity import ROTWK_201_TIMESTAMP
from sage_live.backends.memory import LAYOUT_ROTWK_201, EngineLayout, MemoryBackend
from sage_live.backends.protocol import Handshake
from sage_patch.addresses import IMAGE_BASE
from sage_patch.pe import OPT_IMAGE_BASE, SECTION_HEADER_SIZE

LAY = LAYOUT_ROTWK_201
HEAP = 0x10000000
# The real .data runs 0x00D89000-0x00E0A000. The fake covers the part holding every static
# this reads: the subsystem globals near 0xDE4000, and below them the two bit-order name
# tables - model conditions at 0xD9FAD8 and object status at 0xD8AFF0, which is the lowest of
# them and so what sets the base.
STATIC = 0x00D88000
STATIC_SIZE = 0x68000
HEAP_SIZE = 0x40000
# Enough for the DOS stub, the PE and optional headers, and a two-entry section table.
HEADER_SIZE = 0x400
# What a held-science vector's allocation holds past its `end`. A real one holds whatever the
# heap left there, which decodes as a perfectly plausible science id - so the fake puts a
# recognisable one in the gap rather than zeros, and a reader that walks to `capacity` says so.
_PAST_THE_END = 999


class FakeImage:
    """A sparse three-region address space that behaves like a 32-bit process.

    The third region is the mapped PE header. Every real process has one and `connect` now
    identifies the build from it, so a fake without one would only prove the gate can be
    bypassed. Writing a real header here keeps the check inside the data-free suite.
    """

    def __init__(self, timestamp: int = ROTWK_201_TIMESTAMP) -> None:
        self.static = bytearray(STATIC_SIZE)
        self.heap = bytearray(HEAP_SIZE)
        self.headers = bytearray(HEADER_SIZE)
        self._next = HEAP + 0x100
        self._in_game_ui: int | None = None
        self.closed = False
        self.gone = False
        # `{name -> template address}`, so a test can point a production queue entry at the
        # same template the registry walk will resolve it against.
        self.upgrade_at: dict[str, int] = {}
        self.pe_headers(timestamp)

    def _region(self, address: int, size: int):
        if IMAGE_BASE <= address and address + size <= IMAGE_BASE + HEADER_SIZE:
            return self.headers, address - IMAGE_BASE
        if STATIC <= address and address + size <= STATIC + STATIC_SIZE:
            return self.static, address - STATIC
        if HEAP <= address and address + size <= HEAP + HEAP_SIZE:
            return self.heap, address - HEAP
        return None, 0

    def pe_headers(self, timestamp: int, extra: Sequence[tuple[str, int, int]] = ()) -> None:
        """A minimal but genuine PE32 header block, walked by `sage_patch.pe`.

        `.data` is made to cover the static region, so the subsystem globals sit inside the
        image exactly as they do in the real one. `extra` adds sections by `(name, rva, size)`,
        which is how a patched game announces its cave.
        """
        e_lfanew = 0x80
        sections = [
            (".text", 0x1000, 0x7CF000),
            (".data", STATIC - IMAGE_BASE, STATIC_SIZE),
            *extra,
        ]
        self.write(IMAGE_BASE, b"MZ")
        self.write(IMAGE_BASE + 0x3C, struct.pack("<I", e_lfanew))
        self.write(IMAGE_BASE + e_lfanew, b"PE\x00\x00")
        self.write(IMAGE_BASE + e_lfanew + 4 + 2, struct.pack("<H", len(sections)))
        self.write(IMAGE_BASE + e_lfanew + 4 + 4, struct.pack("<I", timestamp))
        size_of_optional = 0xE0
        self.write(IMAGE_BASE + e_lfanew + 4 + 16, struct.pack("<H", size_of_optional))
        optional = IMAGE_BASE + e_lfanew + 24
        self.write(optional + OPT_IMAGE_BASE, struct.pack("<I", IMAGE_BASE))
        table = optional + size_of_optional
        for i, (name, rva, size) in enumerate(sections):
            entry = name.encode().ljust(8, b"\x00") + struct.pack("<IIII", size, rva, size, 0)
            self.write(table + i * SECTION_HEADER_SIZE, entry.ljust(SECTION_HEADER_SIZE, b"\x00"))

    def read(self, address: int, size: int) -> bytes | None:
        if self.gone:
            return None
        buf, offset = self._region(address, size)
        if buf is None or size <= 0:
            return None
        return bytes(buf[offset : offset + size])

    def die(self) -> None:
        """What a process exiting looks like from outside: every read fails, at once.

        Not zeroes - `ReadProcessMemory` against a dead handle returns nothing at all, which
        is the whole reason a vanished game decodes as an empty one.
        """
        self.gone = True

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
        """An AsciiString allocation: {u32 refcount; u16 length; u16 allocated; chars...}.

        Both counts are in characters and exclude the terminator, which is how the engine
        writes them - see `EngineLayout.string_length`. A reader that takes the length as a
        whole u32 sees a plausible-looking string here and nothing at all in a real game, so
        the halves matter even though nothing in this image is near a page boundary.
        """
        return self._string(text.encode("latin-1"), len(text))

    def utf16(self, text: str) -> int:
        return self._string(text.encode("utf-16-le"), len(text))

    def _string(self, raw: bytes, length: int) -> int:
        allocated = length + 1
        address = self.alloc(LAY.string_chars + len(raw) + 2)
        self.u32(address, 1)
        self.write(address + LAY.string_length, struct.pack("<HH", length, allocated))
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
            self.upgrade_at[name] = node
        address = self.alloc(0x40)
        self.u32(address + LAY.uc_list, node)
        self.u32(address + LAY.uc_count, max((row[0] for row in rows), default=-1) + 1)
        self.u32(LAY.the_upgrade_center, address)
        return address

    def thing_factory(self, names: list[str]) -> dict[str, int]:
        """`TheThingFactory` over `names` in registration order, returning their addresses.

        Prepended, exactly as the engine builds it: the head is the *last* registered, so a
        walk yields reverse order and `thing_order` has something real to reverse.
        """
        node = 0
        at: dict[str, int] = {}
        for name in names:
            address = self.alloc(LAY.tmpl_next + 8)
            self.u32(address + LAY.tmpl_name, self.ascii(name))
            self.u32(address + LAY.tmpl_next, node)
            at[name] = node = address
        factory = self.alloc(0x40)
        self.u32(factory + LAY.tf_list, node)
        self.u32(factory + LAY.tf_count, len(names))
        self.u32(LAY.the_thing_factory, factory)
        return at

    def production_update(self, obj: int, entries: list[tuple[int, int]]) -> int:
        """A `ProductionUpdate` owned by `obj`, holding `(kind, payload)` entries in order."""
        module = self.alloc(0x40)
        self.u32(module, LAY.production_update_vtable)
        self.u32(module + LAY.module_object, obj)
        head, previous = 0, None
        for kind, payload in entries:
            entry = self.alloc(0x60)
            self.u32(entry + LAY.entry_kind, kind)
            slot = LAY.entry_upgrade if kind == 2 else LAY.entry_template
            self.u32(entry + slot, payload)
            if previous is None:
                head = entry
            else:
                self.u32(previous + LAY.entry_next, entry)
            previous = entry
        self.u32(module + LAY.production_head, head)
        self.u32(module + LAY.production_count, len(entries))
        return module

    def modules(self, obj: int, mods: list[int]) -> int:
        """The object's NULL-terminated `BehaviorModule*` array."""
        array = self.alloc((len(mods) + 1) * 4)
        for i, module in enumerate(mods):
            self.u32(array + i * 4, module)
        self.u32(array + len(mods) * 4, 0)
        self.u32(obj + LAY.obj_modules, array)
        return array

    def bit_names(self, table: int, names: list[str]) -> int:
        """A NULL-terminated table of `char*` in bit order - how the engine names a bitset."""
        pointers = [self.write_cstring(n) for n in names]
        for i, p in enumerate(pointers):
            self.u32(table + i * 4, p)
        self.u32(table + len(pointers) * 4, 0)
        return table

    def model_condition_names(self, names: list[str]) -> int:
        return self.bit_names(LAY.the_model_condition_names, names)

    def object_status_names(self, names: list[str]) -> int:
        return self.bit_names(LAY.the_object_status_names, names)

    def write_cstring(self, text: str) -> int:
        """A bare NUL-terminated string - the name table points at these, not AsciiStrings."""
        raw = text.encode("latin-1") + b"\x00"
        address = self.alloc(len(raw))
        self.write(address, raw)
        return address

    def set_bits(self, obj: int, table: int, declared: int, base: int, words: int, names) -> None:
        """Set the bits for `names`, by their index in the name table already written."""
        order = []
        for i in range(declared):
            p = struct.unpack_from("<I", self.read(table + i * 4, 4), 0)[0]
            if p == 0:
                break
            order.append(self.read(p, 64).split(b"\x00")[0].decode("latin-1"))
        bits = 0
        for n in names:
            bits |= 1 << order.index(n)
        self.write(obj + base, bits.to_bytes(words * 4, "little"))

    def set_conditions(self, obj: int, names) -> None:
        self.set_bits(
            obj,
            LAY.the_model_condition_names,
            LAY.model_condition_count,
            LAY.obj_model_conditions,
            LAY.model_condition_words,
            names,
        )

    def set_status(self, obj: int, names) -> None:
        self.set_bits(
            obj,
            LAY.the_object_status_names,
            LAY.object_status_count,
            LAY.obj_status,
            LAY.status_words,
            names,
        )

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
        contained_by: int | None = None,
        producer: int | None = None,
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
        if contained_by is not None:
            self.u32(address + LAY.obj_contained_by, contained_by)
        if producer is not None:
            self.u32(address + LAY.obj_producer_id, producer)
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

    def player(
        self,
        name: str,
        side: str,
        resources: int,
        collected: int = 0,
        display: str = "",
        faction: str = "",
    ) -> int:
        """A seat. `display` and `faction` are the pair a person reads - the lobby name and the
        seat's `PlayerTemplate` - as against the internal `name`/`side`, which several factions
        of one side share. They default to the internal pair rather than to nothing, since a
        seat that has one has both."""
        address = self.alloc(0x400)
        self.u32(address + LAY.player_name, self.ascii(name))
        self.u32(address + LAY.player_side, self.ascii(side))
        self.u32(address + LAY.player_display_name, self.utf16(display or name))
        self.u32(address + LAY.player_template, self.player_template(faction or side, side))
        # The two flat command-point numbers every seat in a real match carries, engine-managed
        # ones included: a base cap of 500 and a hard ceiling of 1500. Zeroes here would leave
        # the clamp between them biting at nothing.
        self.write(address + LAY.player_command_points_cap, struct.pack("<i", 500))
        self.write(address + LAY.player_command_points_hard_cap, struct.pack("<i", 1500))
        self.write(address + LAY.player_resources, struct.pack("<i", resources))
        self.write(address + LAY.player_resources_collected, struct.pack("<i", collected))
        return address

    def player_template(self, faction: str, side: str) -> int:
        address = self.alloc(0x200)
        self.u32(address + LAY.template_faction, self.utf16(faction))
        self.u32(address + LAY.template_side, self.ascii(side))
        return address

    def set_sciences(self, player: int, ids: list[int], spare: int = 4) -> int:
        """Give a player a held-science vector, the `{begin, end, capacity}` the engine keeps.

        `spare` puts real capacity beyond `end`, because that gap is where a reader that trusts
        the wrong pointer goes wrong: reading to `capacity` picks up whatever the allocation
        happens to hold, which decodes as sciences the player does not have.
        """
        array = self.alloc((len(ids) + spare) * 4)
        for i, science in enumerate([*ids, *([_PAST_THE_END] * spare)]):
            self.write(array + i * 4, struct.pack("<i", science))
        self.u32(player + LAY.player_sciences, array)
        self.u32(player + LAY.player_sciences + 4, array + len(ids) * 4)
        self.u32(player + LAY.player_sciences + 8, array + (len(ids) + spare) * 4)
        return array

    def select(self, objects: list[int]) -> int:
        """Give `TheInGameUI` a selected-drawable list holding each object's drawable.

        Built as the engine's own `std::list` is - a sentinel whose `next` walks the nodes and
        comes back to it, each node `{next, prev, value}` - because an empty selection and the
        end of a walk are the same sentinel, and a reader that assumes a null terminator would
        pass against a simpler fake and spin against a real one.
        """
        ui = self._in_game_ui or self.alloc(0x100)
        self._in_game_ui = ui
        self.u32(LAY.the_in_game_ui, ui)

        sentinel = self.alloc(0x10)
        nodes = [self.alloc(0x10) for _ in objects]
        ring = [sentinel, *nodes]
        for i, node in enumerate(ring):
            self.u32(node, ring[(i + 1) % len(ring)])
            self.u32(node + 4, ring[i - 1])
        for node, obj in zip(nodes, objects, strict=True):
            drawable = self.alloc(0x200)
            self.u32(drawable + LAY.drawable_object, obj)
            self.u32(obj + LAY.obj_drawable, drawable)
            self.u32(node + LAY.list_node_value, drawable)
        self.u32(ui + LAY.ui_selected_drawables, sentinel)
        return ui

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
    human = img.player("Player_1", "Men", 2870, collected=5020, display="Ben", faction="Gondor")
    # `SCIENCE_MEN` plus one bought power, which is the shape a real seat has: the faction's own
    # intrinsic science first and the spellbook after it.
    img.set_sciences(human, [16, 36])
    img.player_list([neutral, creeps, human], local=2)

    fighter_t = img.template("GondorFighter", "Men")
    horde_t = img.template("GondorFighterHorde", "Men")
    lair_t = img.template("MoriarGoblinLair", "Neutral")

    horde = img.game_object(horde_t, (2155.0, 3445.0, 61.0), body=img.body(1.0, 1.0))
    fighter_a = img.game_object(
        fighter_t,
        (2153.0, 3443.0, 61.0),
        angle=0.849,
        body=img.body(237.0, 255.0),
        list_prev=horde,
        contained_by=horde,
    )
    fighter_b = img.game_object(
        fighter_t,
        (2170.0, 3450.0, 61.0),
        body=img.body(255.0, 255.0),
        list_prev=horde,
        contained_by=horde,
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


def test_another_build_is_refused_before_anything_is_decoded():
    """The whole point of the gate: a wrong build does not read as an error, it reads as
    data, so it has to be caught by identity rather than by anything downstream."""
    with pytest.raises(ConnectionRefused, match="not the build the layout describes"):
        MemoryBackend(FakeImage(timestamp=0x11223344)).connect()


def test_an_unidentified_build_can_be_read_deliberately():
    """`build_timestamp = 0` is how a layout for an unknown build says it cannot vouch for
    one. No gate is honest; a gate asserting a number nobody measured is not."""
    layout = EngineLayout(build_timestamp=0)
    img = FakeImage(timestamp=0x11223344)
    img.static[:] = build_game().static
    img.heap[:] = build_game().heap
    assert MemoryBackend(img, layout).connect().engine_build


def test_the_handshake_carries_the_measured_fingerprint():
    """It is measured, not declared - which is what makes `expect` able to gate on it."""
    assert backend(build_game()).connect().data_checksum == f"pe-{ROTWK_201_TIMESTAMP:08x}"


def test_a_pinned_fingerprint_refuses_a_different_image():
    """Pinning is the caller's half of the gate: a session that must not silently move to
    another build says so, and finds out at connect rather than in its observations."""
    pinned = Handshake(data_checksum="pe-deadbeef")
    with pytest.raises(ConnectionRefused, match="checksum"):
        MemoryBackend(build_game(), expect=pinned).connect()


def test_identity_reports_the_sections_the_image_carries():
    """How a consumer asks whether the running game is patched, without the file on disk."""
    identity = backend(build_game()).identity
    assert identity is not None
    assert ".text" in identity.section_names
    assert identity.maps(LAY.the_game_logic)
    assert not identity.carries(".livebrg")


def test_a_vanished_game_raises_rather_than_decoding_as_an_empty_one():
    """The failure this exists for: an exited process reads as no objects, no players and no
    local player, which is exactly what a finished match reads as."""
    img = build_game()
    live = backend(img)
    assert live.observe().objects
    img.die()
    with pytest.raises(GameExited, match="not a match that ended"):
        live.observe()


def test_alive_answers_for_the_process_not_the_match():
    img = build_game()
    live = backend(img)
    assert live.alive
    img.die()
    assert not live.alive


def test_a_null_game_logic_is_not_a_dead_process():
    """Between maps the global is null while the process is perfectly healthy. Reading zero
    and failing to read are different answers and only one of them ends a session."""
    img = build_game()
    live = backend(img)
    img.u32(LAY.the_game_logic, 0)
    assert live.alive
    assert live.frame() == 0
    assert live.observe().objects == ()


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


def test_held_sciences_are_read_as_ids_and_stop_at_the_vector_end():
    """The one field that answers "have I already bought that power". `end` is what bounds it,
    and the allocation deliberately holds a further id past that - a reader that used `capacity`
    would report a science the player does not have, which is indistinguishable from data."""
    players = {p.name: p for p in backend(build_game()).read_players()}
    assert players["Player_1"].sciences == frozenset({16, 36})
    assert _PAST_THE_END not in players["Player_1"].sciences


def test_a_player_with_no_science_vector_holds_nothing():
    """Every seat carries one in a real match, but a source that never recorded those bytes
    reads as unreadable - and that is an empty spellbook, not a failed decode."""
    assert not next(
        p for p in backend(build_game()).read_players() if p.name == "PlyrCreeps"
    ).sciences


def test_an_implausible_science_vector_is_refused_and_diagnosed():
    """Three pointers are all this has to go on, so a length that cannot be real is a bad read.
    Walking one would turn garbage into a set of small numbers that looks exactly like data."""
    img = FakeImage()
    human = img.player("Player_1", "Men", 100)
    array = img.set_sciences(human, [16])
    # A plausible `begin` with an `end` far past it - the shape a torn or wrongly-based read has.
    img.u32(human + LAY.player_sciences + 4, array + (LAY.max_sciences + 1) * 4)
    img.player_list([human], local=0)
    img.game_logic(1, [])

    reader = backend(img)
    assert not reader.read_players()[0].sciences
    assert any("science count" in str(d) for d in reader.diagnostics)
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


def test_the_list_links_are_not_the_container_link():
    """`Object+0x8C`/`+0x90` are the global object list's next/prev and mean nothing about
    membership - they only looked like a container link because a battalion's members are
    created consecutively. Containment is `+0x27C`, and the lair below is in nothing."""
    objects = {o.object_id: o for o in backend(build_game()).read_objects()}
    assert objects[124].parent_id is None


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


#
# The last hop `live-object-model.md` §5 listed as missing. `Object+0x24C` is a NULL-terminated
# module array, and the `ProductionUpdate` is identified by its primary vtable rather than by
# asking each module - which the engine does with a virtual call a reader cannot make.


def producing_game(entries, decoys: int = 0, back_pointer: int | None = None):
    """A barracks with `entries` queued, and the registries needed to name them.

    An entry is `(kind, name)` where kind is the engine's own: 1 unit, 2 upgrade, 3 revive.
    """
    img = FakeImage()
    img.upgrade_center([(3, "Upgrade_GondorHeavyArmor", False)])
    things = img.thing_factory(["DefaultThingTemplate", "GondorFighter", "GondorArcher"])

    barracks_t = img.template("GondorBarracks", "Men")
    barracks = img.game_object(barracks_t, (100.0, 200.0, 0.0), body=img.body(1.0, 3000.0))

    resolved = [
        (kind, img.upgrade_at[name] if kind == 2 else things[name]) for kind, name in entries
    ]
    module = img.production_update(barracks, resolved)
    # Decoy modules ahead of it: the production module is rarely the first one an object has.
    img.modules(barracks, [img.alloc(0x20) for _ in range(decoys)] + [module])
    if back_pointer is not None:
        img.u32(module + LAY.module_object, back_pointer)

    img.player_list([img.player("Player_1", "Men", 500)], local=0)
    img.game_logic(10, [img.entry(77, barracks)])
    return img


def test_a_barracks_training_a_unit_no_longer_reads_as_idle():
    """The gap this closes: production state is not in the object's header at all, so a
    building already training was indistinguishable from an empty one."""
    img = producing_game([(1, "GondorFighter")])
    obj = backend(img).observe().obj(77)
    assert obj is not None
    assert obj.producing
    assert [(i.kind, i.name) for i in obj.production] == [("unit", "GondorFighter")]


def test_units_and_upgrades_share_one_queue():
    """The engine keeps a single list for both, so a barracks training and an armoury
    researching are the same structure with different kinds."""
    img = producing_game([(1, "GondorArcher"), (2, "Upgrade_GondorHeavyArmor")])
    obj = backend(img).observe().obj(77)
    assert obj is not None
    kinds = [i.kind for i in obj.production]
    assert kinds == ["unit", "upgrade"]
    assert obj.production[1].name == "Upgrade_GondorHeavyArmor"
    assert obj.production[1].is_upgrade


def test_an_idle_building_reports_nothing_queued():
    img = producing_game([])
    obj = backend(img).observe().obj(77)
    assert obj is not None
    assert not obj.producing
    assert obj.production == ()


def test_an_object_with_no_modules_is_not_an_error():
    """Most objects have no production module at all - scenery, plots, units."""
    obj = backend(build_game()).observe().obj(132)
    assert obj is not None
    assert not obj.producing


def test_the_module_is_found_past_other_modules():
    """The array holds every behaviour module; the production one is rarely first."""
    img = producing_game([(1, "GondorFighter")], decoys=5)
    obj = backend(img).observe().obj(77)
    assert obj is not None and obj.producing


def test_a_module_that_does_not_point_back_is_refused():
    """The self-check that makes a wrong module-list offset loud. If the walk landed on some
    other array of pointers, the back-pointer will not name the object we came from - and
    everything read past that point would be fiction."""
    img = producing_game([(1, "GondorFighter")], back_pointer=0x10000000)
    live = backend(img)
    obj = live.observe().obj(77)
    assert obj is not None
    assert obj.production == ()
    assert any("does not point back" in str(d) for d in live.diagnostics)


def test_production_can_be_turned_off_for_a_cheaper_observation():
    img = producing_game([(1, "GondorFighter")])
    live = MemoryBackend(img, read_production=False)
    live.connect()
    obj = live.observe().obj(77)
    assert obj is not None and not obj.producing


def test_a_horde_member_names_its_container():
    """`Object+0x27C` is what contains this object. Before it was found, `parent_id` was
    always None and a battalion read as unrelated individuals."""
    obs = backend(build_game()).observe()
    horde = obs.obj(132)
    members = obs.members(132)
    assert horde is not None and horde.parent_id is None, "a container is not contained"
    assert {m.object_id for m in members} == {133, 134}
    assert all(m.template_name == "GondorFighter" for m in members)


def test_an_object_contained_by_nothing_has_no_parent():
    obs = backend(build_game()).observe()
    lair = obs.obj(124)
    assert lair is not None and lair.parent_id is None


#
# The other half of containment: `ObjectStatus` and the producer id. Between them they are what
# tells a battalion that is still forming from one that has come apart - see
# `sage_patch/docs/horde-formation-orphans.md`.


def half_formed_game() -> FakeImage:
    """One battalion whose two members disagree about belonging to it.

    `inside` is contained and flagged as a member, the way a formed battalion reads. `loose` is
    neither, but still names the horde as what produced it - the state that survives an order
    landing before the battalion finished coming out of the building.
    """
    img = FakeImage()
    img.object_status_names(["DESTROYED", "HORDE_MEMBER", "IS_LEAVING_FACTORY", "UNATTACKABLE"])
    horde_t = img.template("GondorFighterHorde", "Men")
    fighter_t = img.template("GondorFighter", "Men")

    horde = img.game_object(horde_t, (10.0, 10.0, 0.0), body=img.body(1.0, 1.0))
    inside = img.game_object(
        fighter_t, (11.0, 10.0, 0.0), body=img.body(255.0, 255.0), contained_by=horde, producer=20
    )
    loose = img.game_object(fighter_t, (60.0, 40.0, 0.0), body=img.body(255.0, 255.0), producer=20)
    img.set_status(inside, ["HORDE_MEMBER"])
    img.set_status(loose, ["HORDE_MEMBER", "IS_LEAVING_FACTORY"])

    img.player_list([img.player("P", "Men", 10)], local=0)
    img.game_logic(1, [img.entry(20, horde), img.entry(21, inside), img.entry(22, loose)])
    return img


def test_object_status_decodes_by_name():
    obj = backend(half_formed_game()).observe().obj(21)
    assert obj is not None
    assert obj.status == frozenset({"HORDE_MEMBER"})
    assert obj.has_status("horde_member"), "case-insensitive, like every other name"
    assert not obj.has_status("UNATTACKABLE")


def test_several_status_bits_decode_together():
    obj = backend(half_formed_game()).observe().obj(22)
    assert obj is not None
    assert obj.status == frozenset({"HORDE_MEMBER", "IS_LEAVING_FACTORY"})


def test_an_object_in_no_notable_state_has_no_status():
    obj = backend(half_formed_game()).observe().obj(20)
    assert obj is not None and obj.status == frozenset()


def test_the_producer_id_survives_leaving_the_container():
    """The asymmetry the whole diagnosis rests on: `parent_id` is cleared when an object leaves
    its container and `producer_id` is not, so a loose unit still names the horde it came out
    of - which is what the engine's own target resolution falls back to."""
    obs = backend(half_formed_game()).observe()
    inside, loose = obs.obj(21), obs.obj(22)
    assert inside is not None and loose is not None
    assert inside.parent_id == 20 and inside.producer_id == 20
    assert loose.parent_id is None and loose.producer_id == 20


def test_an_object_nothing_produced_has_no_producer():
    obs = backend(half_formed_game()).observe()
    horde = obs.obj(20)
    assert horde is not None and horde.producer_id is None


#
# A budget, not a benchmark. Each `MemorySource.read` is a `ReadProcessMemory` syscall, and the
# per-object count is what decides whether a policy can observe a few times a second or a few
# dozen. It regressed silently once already - the module walk for production state added ten
# reads per object - so it is asserted rather than remembered.


class CountingSource:
    """A source that counts reads, and can refuse the wide ones.

    Refusing them exercises the fallback path, which is field-for-field what the reader did
    before it batched - so the same test measures both and the improvement cannot be an
    artefact of a different image.
    """

    def __init__(self, inner: FakeImage, wide: bool = True) -> None:
        self.inner = inner
        self.wide = wide
        self.reads = 0

    def read(self, address: int, size: int) -> bytes | None:
        self.reads += 1
        if not self.wide and size in (LAY.obj_span, LAY.body_max_health - LAY.body_health + 4):
            return None
        return self.inner.read(address, size)

    def close(self) -> None:
        self.inner.close()


def crowd(n: int) -> FakeImage:
    """`n` objects of one template, so per-template caching is exercised as it is live."""
    img = FakeImage()
    img.upgrade_center([(3, "Upgrade_X", False)])
    template = img.template("GondorFighter", "Men")
    entries = []
    for i in range(n):
        obj = img.game_object(template, (float(i), 0.0, 0.0), body=img.body(1.0, 99.0))
        entries.append(img.entry(100 + i, obj))
    img.player_list([img.player("P", "Men", 10)], local=0)
    img.game_logic(1, entries, slots=max(64, n + 8))
    return img


def marginal_reads(wide: bool) -> float:
    """Reads per object, measured as the *difference* between a small and a large observation.

    The marginal cost is the honest figure: a fixed overhead of players, the object table and
    the upgrade registry would otherwise dominate any image small enough to build in a test.
    """
    counts = {}
    for n in (10, 110):
        source = CountingSource(crowd(n), wide)
        live = MemoryBackend(source)
        live.connect()
        live.upgrade_table()
        before = source.reads
        live.observe()
        counts[n] = source.reads - before
    return (counts[110] - counts[10]) / 100


def test_an_object_costs_three_reads():
    """The entry, the object header, and the body. Everything else on the header - position,
    facing, team, the upgrade mask, the module pointer - comes out of the one read, and the
    template's name and Side are cached per template rather than per object."""
    assert marginal_reads(wide=True) <= 3.0


def test_batching_is_what_makes_it_three():
    """Guards the win rather than just the number: with the wide reads refused, the reader
    falls back to a field at a time, which is what it did before batching."""
    assert marginal_reads(wide=False) >= 15.0


def test_the_fallback_decodes_identically():
    """The fast path must be an optimisation and nothing else. A wide read that fails - an
    object straddling an unmapped page, or a recorded snapshot with gaps - has to produce the
    same observation, or the optimisation is a second decoder with its own bugs."""
    batched = MemoryBackend(CountingSource(build_game(), wide=True))
    batched.connect()
    field_wise = MemoryBackend(CountingSource(build_game(), wide=False))
    field_wise.connect()
    assert batched.observe().to_dict() == field_wise.observe().to_dict()


#
# A 19-dword bitset on the object, named by a NULL-terminated table in static data. It is how
# the game knows a structure is still going up, which health cannot say - hit points ramp while
# building, so a half-built structure and a damaged one look identical by health alone.


def conditioned(*names: str) -> FakeImage:
    """An image whose one structure is in the given model-condition states."""
    img = FakeImage()
    img.upgrade_center([(3, "Upgrade_X", False)])
    img.model_condition_names(["FIRST", "ACTIVELY_BEING_CONSTRUCTED", "DAMAGED", "ATTACKING"])
    template = img.template("GondorBarracks", "Men")
    obj = img.game_object(template, (10.0, 20.0, 0.0), body=img.body(500.0, 3000.0))
    img.set_conditions(obj, [1 if n == "ACTIVELY_BEING_CONSTRUCTED" else 2 for n in ()])
    img.set_conditions(obj, names)
    img.player_list([img.player("P", "Men", 10)], local=0)
    img.game_logic(1, [img.entry(7, obj)])
    return img


def test_a_structure_still_going_up_says_so():
    """The gap this closes: health ramps while building, so a half-built structure was
    indistinguishable from a damaged one."""
    obj = backend(conditioned("ACTIVELY_BEING_CONSTRUCTED")).observe().obj(7)
    assert obj is not None
    assert obj.under_construction
    assert obj.is_in("actively_being_constructed"), "case-insensitive, like every other name"


def test_a_finished_structure_is_not_under_construction():
    obj = backend(conditioned("DAMAGED")).observe().obj(7)
    assert obj is not None
    assert not obj.under_construction
    assert obj.conditions == frozenset({"DAMAGED"})


def test_several_conditions_decode_together():
    obj = backend(conditioned("DAMAGED", "ATTACKING")).observe().obj(7)
    assert obj is not None
    assert obj.conditions == frozenset({"DAMAGED", "ATTACKING"})


def test_an_object_in_no_notable_state_carries_nothing():
    obj = backend(conditioned()).observe().obj(7)
    assert obj is not None
    assert obj.conditions == frozenset()


def test_conditions_cost_no_extra_read():
    """The mask sits inside the object header the reader already takes in one read, so this
    field is free - which is why it is on by default."""
    assert marginal_reads(wide=True) <= 3.0


def _spell_module(img: FakeImage, name: str, ready_frame: int) -> int:
    """A special-power module: `{ModuleData -> SpecialPowerTemplate -> name}` and a ready frame.

    Laid out at the offsets `EngineLayout` declares, so a wrong offset in the layout cannot
    cancel against a wrong offset in the reader - the same discipline the rest of this file
    follows.
    """
    template = img.alloc(0x40)
    img.u32(template + LAY.power_name, img.ascii(name))
    data = img.alloc(0x40)
    img.u32(data + LAY.module_data_template, template)
    module = img.alloc(0x40)
    img.u32(module + LAY.module_data, data)
    img.write(module + LAY.module_ready_frame, struct.pack("<i", ready_frame))
    return module


def _spellbook(img: FakeImage, powers: list[tuple[str, int]], object_id: int = 900) -> FakeImage:
    """A match holding one object that carries `powers` as special-power modules."""
    book_t = img.template("GondorSpellBook", "Men")
    book = img.game_object(book_t, (0.0, 0.0, 0.0))
    mods = [_spell_module(img, name, ready) for name, ready in powers]
    # A module family that is not a special power: its data names no template, which is the
    # test the engine's own recharge path makes before touching anything else.
    plain = img.alloc(0x40)
    img.u32(plain + LAY.module_data, img.alloc(0x40))
    img.modules(book, [*mods, plain])
    img.game_logic(5000, [img.entry(object_id, book)])
    return img


def test_power_cooldowns_read_the_engines_own_ready_frame():
    """The number `startPowerRecharge` writes, not one computed from `ReloadTime` - the ini
    figure is undiscounted and measured 6x too long in a real match."""
    img = _spellbook(FakeImage(), [("SpellBookRebuild", 4200), ("SpellBookAdler", 12000)])
    reader = backend(img)
    reader.read_objects()  # fills the id -> Object* map this resolves through
    assert reader.power_cooldowns(900) == {"SpellBookRebuild": 4200, "SpellBookAdler": 12000}


def test_a_ready_power_is_one_whose_frame_is_not_in_the_future():
    img = _spellbook(FakeImage(), [("SpellBookRebuild", 4999), ("SpellBookAdler", 5001)])
    reader = backend(img)
    frame = reader.observe().frame
    cooldowns = reader.power_cooldowns(900)
    assert frame == 5000
    assert cooldowns["SpellBookRebuild"] <= frame, "ready"
    assert cooldowns["SpellBookAdler"] > frame, "still recharging"


def test_a_module_that_is_not_a_special_power_is_skipped():
    """Every other module family leaves the template unset, and the engine's own recharge path
    bails on exactly that test. Reading them would invent powers with empty names."""
    img = _spellbook(FakeImage(), [("SpellBookRebuild", 4200)])
    reader = backend(img)
    reader.read_objects()
    assert list(reader.power_cooldowns(900)) == ["SpellBookRebuild"]


def test_an_id_the_table_walk_never_saw_reads_as_no_powers():
    """Ids are reused as objects die, so this resolves through the last walk rather than
    scanning - and an id that walk did not see is unknown, not ready."""
    img = _spellbook(FakeImage(), [("SpellBookRebuild", 4200)])
    reader = backend(img)
    reader.read_objects()
    assert reader.power_cooldowns(4242) == {}
