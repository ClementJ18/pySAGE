"""`score-keeper-dangling-keys`, executed.

The sibling file reads the cave back as text. This one runs it, in two ways:

- **The caves alone**, over the synthetic stand-in, with the engine routines they call answered in
  Python. Runs everywhere.
- **The engine's own `xferObjectCountMap` and score merge with the patch in place**, over the real
  `game.dat`, stock and patched side by side. Skipped where there is no `game.dat`. This is the
  half that shows the cave and the code it returns into agree: the count written matches the
  entries written, the load stream stays aligned, and a map the stock code saves correctly is
  saved byte-for-byte the same.

A dead key is planted as a pointer into unmapped memory, so "never dereferenced" is not a claim
the test takes on trust: the stock code faults on it, and the patched code must not.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")
pytest.importorskip("pefile", reason="the emulator harness maps the image with pefile")

from unicorn import UcError  # noqa: E402

from sage_patch.addresses import (  # noqa: E402
    ASCII_STRING_CHARS_OFFSET,
    ASCII_STRING_COPY,
    ASCII_STRING_DTOR,
    LIVING_WORLD_SCORE_KEEPER_MERGE_MAP,
    LIVING_WORLD_SCORE_KEEPER_MERGE_NEXT,
    LIVING_WORLD_SCORE_KEEPER_MERGE_STORE_RESUME,
    OVERRIDABLE_IS_OVERRIDE,
    OVERRIDABLE_NEXT_OVERRIDE,
    STD_MAP_ITERATOR_INCREMENT,
    THE_THING_FACTORY,
    THING_FACTORY_FIND_TEMPLATE,
    THING_FACTORY_TEMPLATE_LIST,
    THING_TEMPLATE_NAME,
    THING_TEMPLATE_NEXT,
    XFER_OBJECT_COUNT_MAP,
    XFER_OBJECT_COUNT_MAP_COUNT_RESUME,
    XFER_OBJECT_COUNT_MAP_DONE,
    XFER_OBJECT_COUNT_MAP_KEY_NAME_RESUME,
    XFER_OBJECT_COUNT_MAP_LOAD_NEXT,
    XFER_OBJECT_COUNT_MAP_NEXT,
)
from sage_patch.patches.score_keeper_dangling_keys import (  # noqa: E402
    SECTION_NAME,
    ScoreKeeperDanglingKeysPatch,
    entry_points,
)
from sage_patch.utils import find_section  # noqa: E402

from .save_machine import Machine  # noqa: E402
from .synthetic import score_keeper_dangling_keys_image  # noqa: E402

REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: `std::map<const ThingTemplate *, Int>::operator[]` as the load loop calls it (`0x00961888`),
#: `__thiscall`, `ret 4`, returning the value slot - stubbed, because the real one allocates nodes.
MAP_SUBSCRIPT = 0x00767DF1
#: The merge's insert (`0x008F336A`): `__thiscall (pair<iterator, bool> *out, value *in)`, `ret 8`.
MAP_INSERT = 0x008DE2FF
#: `_CxxThrowException`, where the stock load ends when a name does not resolve.
CXX_THROW = 0x00A3CE04

#: A key that points nowhere. Reading through it faults, which is the whole point of planting it.
DEAD = 0x0BAD0000


def _patched(source: bytes) -> bytes:
    data = bytearray(source)
    ScoreKeeperDanglingKeysPatch().apply(data)
    return bytes(data)


@dataclass
class World:
    """Templates, the factory's list over them, and count maps in the engine's layout."""

    m: Machine
    head: int = 0
    by_name: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        factory = self.m.alloc(0x40, b"\x00" * 0x40)
        self.m.ensure(THE_THING_FACTORY)
        self.m.write32(THE_THING_FACTORY, factory)
        self.factory = factory

    def string(self, text: str) -> int:
        """An `AsciiString` data block: its characters at `ASCII_STRING_CHARS_OFFSET`."""
        raw = text.encode("latin-1")
        return self.m.alloc(ASCII_STRING_CHARS_OFFSET + len(raw) + 1, bytes(8) + raw + b"\x00")

    def template(self, name: str, *, override_of: int | None = None) -> int:
        t = self.m.alloc(0x600, b"\x00" * 0x600)
        self.m.write32(t + THING_TEMPLATE_NAME, self.string(name))
        if override_of is None:
            self.m.write32(t + THING_TEMPLATE_NEXT, self.head)
            self.head = t
            self.m.write32(self.factory + THING_FACTORY_TEMPLATE_LIST, t)
            self.by_name[name] = t
        else:
            tail = override_of
            while self.m.read32(tail + OVERRIDABLE_NEXT_OVERRIDE):
                tail = self.m.read32(tail + OVERRIDABLE_NEXT_OVERRIDE)
            self.m.write32(tail + OVERRIDABLE_NEXT_OVERRIDE, t)
            self.m.uc.mem_write(t + OVERRIDABLE_IS_OVERRIDE, b"\x01")
        return t

    def count_map(self, entries: list[tuple[int, int]]) -> int:
        """A `std::map` holding `entries` in order, as a right-leaning chain of STLport nodes:
        parent at `+4`, left `+8`, right `+0xC`, key `+0x10`, value `+0x14`."""
        header = self.m.alloc(0x18, b"\x00" * 0x18)
        nodes = [self.m.alloc(0x18, b"\x00" * 0x18) for _ in entries]
        for i, (node, (key, value)) in enumerate(zip(nodes, entries, strict=True)):
            self.m.write32(node + 0x04, nodes[i - 1] if i else header)
            self.m.write32(node + 0x0C, nodes[i + 1] if i + 1 < len(nodes) else 0)
            self.m.write32(node + 0x10, key)
            self.m.write32(node + 0x14, value)
        self.m.write32(header + 0x04, nodes[0] if nodes else 0)
        self.m.write32(header + 0x08, nodes[0] if nodes else header)
        self.m.write32(header + 0x0C, nodes[-1] if nodes else header)
        container = self.m.alloc(8)
        self.m.write32(container, header)
        self.m.write32(container + 4, len(entries))
        return container


@dataclass
class Xfer:
    """A stand-in `Xfer`: records what a save writes, and feeds what a load reads."""

    m: Machine
    saving: bool
    feed: list[object] = field(default_factory=list)
    log: list[tuple[str, object]] = field(default_factory=list)

    def build(self, world: World) -> int:
        m = self.m
        vtable = m.alloc(0x100, b"\x00" * 0x100)

        def slot(offset: int, handler) -> None:
            m.write32(vtable + offset, m.stub(None, handler))

        slot(0x08, lambda mm: mm.ret(0, int(self.saving)))  # isSaving
        slot(0x0C, lambda mm: mm.ret(0, 0))  # the early-out the CRC xfer takes
        slot(0x28, lambda mm: mm.ret(4))  # xferVersion

        def ushort(mm: Machine) -> None:
            at = mm.arg(0)
            if self.saving:
                self.log.append(("count", struct.unpack("<H", mm.uc.mem_read(at, 2))[0]))
            else:
                mm.uc.mem_write(at, struct.pack("<H", self.feed.pop(0)))
            mm.ret(4)

        def ascii_string(mm: Machine) -> None:
            at = mm.arg(0)
            if self.saving:
                data = mm.read32(at)
                text = b""
                if data:
                    raw = bytes(mm.uc.mem_read(data + ASCII_STRING_CHARS_OFFSET, 64))
                    text = raw.split(b"\x00")[0]
                self.log.append(("name", text.decode("latin-1")))
            else:
                mm.write32(at, world.string(str(self.feed.pop(0))))
            mm.ret(4)

        def integer(mm: Machine) -> None:
            at = mm.arg(0)
            if self.saving:
                self.log.append(("int", mm.read32(at)))
            else:
                value = self.feed.pop(0)
                assert isinstance(value, int)
                mm.write32(at, value)
            mm.ret(4)

        slot(0x80, ushort)
        slot(0x6C, ascii_string)
        slot(0x7C, integer)
        xfer = m.alloc(0x10, b"\x00" * 0x10)
        m.write32(xfer, vtable)
        return xfer


def _engine(m: Machine, world: World) -> dict[str, list]:
    """Answer the engine routines the count map and the merge call that this harness does not
    execute: string copy and destruction, the template lookup, the two map inserts and the throw.
    """
    seen: dict[str, list] = {"subscript": [], "insert": [], "thrown": []}

    def copy(mm: Machine) -> None:
        source = mm.arg(0)
        try:
            data = mm.read32(source)
        except UcError:
            mm.faults.append(source)  # the read the real copy would fault on
            raise
        mm.write32(mm.reg("ecx"), data)
        mm.ret(4, mm.reg("ecx"))

    def find(mm: Machine) -> None:
        data = mm.read32(mm.arg(0))
        name = ""
        if data:
            raw = bytes(mm.uc.mem_read(data + ASCII_STRING_CHARS_OFFSET, 64))
            name = raw.split(b"\x00")[0].decode("latin-1")
        mm.ret(4, world.by_name.get(name, 0))

    def subscript(mm: Machine) -> None:
        key = mm.read32(mm.arg(0))
        slot = mm.alloc(4, b"\x00" * 4)
        seen["subscript"].append((key, slot))
        mm.ret(4, slot)

    def insert(mm: Machine) -> None:
        out, value = mm.arg(0), mm.arg(1)
        node = mm.alloc(0x18, b"\x00" * 0x18)
        seen["insert"].append(mm.read32(value))
        mm.write32(out, node)
        mm.ret(8, out)

    def throw(mm: Machine) -> None:
        seen["thrown"].append(True)
        mm.uc.emu_stop()

    m.stub(ASCII_STRING_COPY, copy)
    m.stub(ASCII_STRING_DTOR, lambda mm: mm.ret(0))
    m.stub(THING_FACTORY_FIND_TEMPLATE, find)
    m.stub(MAP_SUBSCRIPT, subscript)
    m.stub(MAP_INSERT, insert)
    m.stub(CXX_THROW, throw)
    return seen


def _increment_stub(m: Machine) -> None:
    """The STLport successor for the right-leaning chains `World.count_map` builds - for the
    synthetic image, which does not carry the engine's own."""

    def increment(mm: Machine) -> None:
        node = mm.arg(0)
        right = mm.read32(node + 0x0C)
        if right:
            mm.ret(0, right)
            return
        while True:
            parent = mm.read32(node + 0x04)
            if mm.read32(parent + 0x0C) != node:
                mm.ret(0, parent)
                return
            node = parent

    m.stub(STD_MAP_ITERATOR_INCREMENT, increment)


# The caves, over the stand-in


@pytest.fixture
def cave() -> tuple[Machine, World, dict[str, int]]:
    image = _patched(bytes(score_keeper_dangling_keys_image()))
    m = Machine(image)
    world = World(m)
    section_va, _off, _size = find_section(image, SECTION_NAME)
    return m, world, entry_points(section_va)


class TestIsLive:
    def test_a_listed_template_is_live(self, cave) -> None:
        m, world, entries = cave
        world.template("A")
        b = world.template("B")
        world.template("C")
        assert m.call(entries["is_live"], eax=b) == 1

    def test_an_override_is_live_through_its_base(self, cave) -> None:
        m, world, entries = cave
        base = world.template("AngmarBarracks")
        first = world.template("AngmarBarracks", override_of=base)
        second = world.template("AngmarBarracks", override_of=base)
        assert m.call(entries["is_live"], eax=first) == 1
        assert m.call(entries["is_live"], eax=second) == 1

    def test_a_pointer_outside_the_factory_is_dead_and_never_read(self, cave) -> None:
        m, world, entries = cave
        world.template("A")
        assert m.call(entries["is_live"], eax=DEAD) == 0

    def test_null_is_dead(self, cave) -> None:
        m, world, entries = cave
        world.template("A")
        assert m.call(entries["is_live"], eax=0) == 0

    def test_no_factory_means_nothing_is_live(self, cave) -> None:
        m, world, entries = cave
        t = world.template("A")
        m.write32(THE_THING_FACTORY, 0)
        assert m.call(entries["is_live"], eax=t) == 0

    def test_it_preserves_every_register_but_eax(self, cave) -> None:
        m, world, entries = cave
        t = world.template("A")
        regs = {"ebx": 0x1111, "ecx": 0x2222, "edx": 0x3333, "esi": 0x4444, "edi": 0x5555}
        m.call(entries["is_live"], eax=t, **regs)
        assert {name: m.reg(name) for name in regs} == regs


class TestTheRoutines:
    def test_count_counts_only_live_keys(self, cave) -> None:
        m, world, entries = cave
        _increment_stub(m)
        a, b = world.template("A"), world.template("B")
        container = world.count_map([(a, 1), (DEAD, 2), (b, 3), (0, 4)])
        m.stop_at(XFER_OBJECT_COUNT_MAP_COUNT_RESUME)
        ebp = m.frame()
        m.call(entries["count"], ebx=container, ebp=ebp, edi=0x77)
        assert m.stopped_at == XFER_OBJECT_COUNT_MAP_COUNT_RESUME
        assert m.reg("eax") == 2
        assert m.reg("ecx") == ebp - 0x14, "the displaced lea"
        assert m.reg("edi") == 0x77

    def test_count_of_an_empty_map_is_zero(self, cave) -> None:
        m, world, entries = cave
        _increment_stub(m)
        container = world.count_map([])
        m.stop_at(XFER_OBJECT_COUNT_MAP_COUNT_RESUME)
        m.call(entries["count"], ebx=container, ebp=m.frame())
        assert m.reg("eax") == 0

    def test_key_resumes_with_the_name_for_a_live_key(self, cave) -> None:
        m, world, entries = cave
        t = world.template("A")
        node = world.m.alloc(0x18, b"\x00" * 0x18)
        m.write32(node + 0x10, t)
        m.stop_at(XFER_OBJECT_COUNT_MAP_KEY_NAME_RESUME, XFER_OBJECT_COUNT_MAP_NEXT)
        m.call(entries["key"], edi=node)
        assert m.stopped_at == XFER_OBJECT_COUNT_MAP_KEY_NAME_RESUME
        assert m.reg("eax") == t + THING_TEMPLATE_NAME

    def test_key_skips_a_dead_key_to_the_iterator_step(self, cave) -> None:
        m, world, entries = cave
        world.template("A")
        node = world.m.alloc(0x18, b"\x00" * 0x18)
        m.write32(node + 0x10, DEAD)
        m.stop_at(XFER_OBJECT_COUNT_MAP_KEY_NAME_RESUME, XFER_OBJECT_COUNT_MAP_NEXT)
        m.call(entries["key"], edi=node)
        assert m.stopped_at == XFER_OBJECT_COUNT_MAP_NEXT
        assert m.reg("edi") == node, "the iterator step reads the node from edi"

    @pytest.mark.parametrize(("index", "count", "stop"), [(0, 3, "next"), (2, 3, "done")])
    def test_unknown_consumes_the_int_and_continues_the_loop(
        self, cave, index, count, stop
    ) -> None:
        m, world, entries = cave
        xfer = Xfer(m, saving=False, feed=[77])
        xfer_object = xfer.build(world)
        ebp = m.frame()
        m.uc.mem_write(ebp - 0x14, struct.pack("<H", count))
        m.stop_at(XFER_OBJECT_COUNT_MAP_LOAD_NEXT, XFER_OBJECT_COUNT_MAP_DONE)
        m.call(entries["unknown"], esi=xfer_object, edi=index, ebp=ebp)
        assert xfer.feed == [], "the entry's Int was read"
        assert m.read32(ebp - 0x10) == 77
        assert m.reg("edi") == index + 1
        expected = XFER_OBJECT_COUNT_MAP_LOAD_NEXT if stop == "next" else XFER_OBJECT_COUNT_MAP_DONE
        assert m.stopped_at == expected

    def test_merge_skips_a_null_template(self, cave) -> None:
        m, _world, entries = cave
        m.stop_at(
            LIVING_WORLD_SCORE_KEEPER_MERGE_STORE_RESUME, LIVING_WORLD_SCORE_KEEPER_MERGE_NEXT
        )
        m.call(entries["merge"], eax=0, ebp=m.frame())
        assert m.stopped_at == LIVING_WORLD_SCORE_KEEPER_MERGE_NEXT

    def test_merge_stores_a_resolved_template(self, cave) -> None:
        m, world, entries = cave
        t = world.template("A")
        ebp = m.frame()
        m.write32(ebp + 8, 0xD57)
        m.stop_at(
            LIVING_WORLD_SCORE_KEEPER_MERGE_STORE_RESUME, LIVING_WORLD_SCORE_KEEPER_MERGE_NEXT
        )
        m.call(entries["merge"], eax=t, ebp=ebp)
        assert m.stopped_at == LIVING_WORLD_SCORE_KEEPER_MERGE_STORE_RESUME
        assert m.read32(ebp - 0x14) == t
        assert m.reg("ecx") == 0xD57


# The engine's own code, over the real binary


@pytest.fixture(scope="module")
def real() -> bytes:
    if not REAL_GAME_DAT.exists():
        pytest.skip(f"no {REAL_GAME_DAT}")
    return REAL_GAME_DAT.read_bytes()


def _save(image: bytes, keys, machine: list[Machine] | None = None) -> tuple[list, dict]:
    m = Machine(image)
    if machine is not None:
        machine.append(m)
    world = World(m)
    seen = _engine(m, world)
    entries = [(build(world), value) for build, value in keys]
    container = world.count_map(entries)
    xfer = Xfer(m, saving=True)
    m.call(XFER_OBJECT_COUNT_MAP, xfer.build(world), container)
    assert m.stopped_at is not None, "the routine did not return"
    assert not m.faults
    return xfer.log, seen


def _live(name: str):
    return lambda world: world.by_name.get(name) or world.template(name)


def _dead(world: World) -> int:
    return DEAD


def _null(world: World) -> int:
    return 0


class TestSavingWithTheEngine:
    LIVE = [(_live("AngmarBarracks"), 5), (_live("AngmarDen"), 7), (_live("AngmarMill"), 4)]

    def test_a_map_of_live_keys_saves_exactly_as_stock(self, real) -> None:
        stock, _ = _save(real, self.LIVE)
        patched, _ = _save(_patched(real), self.LIVE)
        assert patched == stock
        assert stock == [
            ("count", 3),
            ("name", "AngmarBarracks"),
            ("int", 5),
            ("name", "AngmarDen"),
            ("int", 7),
            ("name", "AngmarMill"),
            ("int", 4),
        ]

    def test_stock_faults_on_a_dead_key(self, real) -> None:
        """The failure the patch exists for, reproduced: the read of `key->m_name`."""
        machine: list[Machine] = []
        with pytest.raises(UcError):
            _save(real, [*self.LIVE[:1], (_dead, 2)], machine)
        assert machine[0].faults == [DEAD + THING_TEMPLATE_NAME]

    def test_the_patch_writes_the_live_keys_and_a_count_that_matches(self, real) -> None:
        keys = [self.LIVE[0], (_dead, 2), self.LIVE[1], (_null, 9), self.LIVE[2]]
        log, _ = _save(_patched(real), keys)
        assert log == [
            ("count", 3),
            ("name", "AngmarBarracks"),
            ("int", 5),
            ("name", "AngmarDen"),
            ("int", 7),
            ("name", "AngmarMill"),
            ("int", 4),
        ]

    def test_an_override_key_is_kept(self, real) -> None:
        def override(world: World) -> int:
            base = world.by_name.get("AngmarBarracks") or world.template("AngmarBarracks")
            return world.template("AngmarBarracks", override_of=base)

        log, _ = _save(_patched(real), [(override, 3)])
        assert log == [("count", 1), ("name", "AngmarBarracks"), ("int", 3)]

    def test_a_map_of_only_dead_keys_saves_as_empty(self, real) -> None:
        log, _ = _save(_patched(real), [(_dead, 1), (_null, 2)])
        assert log == [("count", 0)]


def _load(image: bytes, names: list[str], values: list[int], known: list[str]):
    m = Machine(image)
    world = World(m)
    for name in known:
        world.template(name)
    seen = _engine(m, world)
    feed: list[object] = [len(names)]
    for name, value in zip(names, values, strict=True):
        feed += [name, value]
    xfer = Xfer(m, saving=False, feed=feed)
    m.call(XFER_OBJECT_COUNT_MAP, xfer.build(world), world.count_map([]))
    stored = {
        next(n for n, t in world.by_name.items() if t == key): m.read32(slot)
        for key, slot in seen["subscript"]
    }
    return xfer, seen, stored


class TestLoadingWithTheEngine:
    NAMES = ["", "AngmarBarracks", "OnlyInMapIni", "AngmarDen"]
    VALUES = [1, 5, 2, 7]
    KNOWN = ["AngmarBarracks", "AngmarDen"]

    def test_stock_throws_on_the_first_unknown_name(self, real) -> None:
        _xfer, seen, _stored = _load(real, self.NAMES, self.VALUES, self.KNOWN)
        assert seen["thrown"]

    def test_the_patch_loads_the_known_names_and_drops_the_rest(self, real) -> None:
        xfer, seen, stored = _load(_patched(real), self.NAMES, self.VALUES, self.KNOWN)
        assert not seen["thrown"]
        assert stored == {"AngmarBarracks": 5, "AngmarDen": 7}
        assert xfer.feed == [], "every entry was read, so the stream after the map is aligned"

    def test_a_save_with_only_known_names_loads_exactly_as_stock(self, real) -> None:
        names, values = ["AngmarBarracks", "AngmarDen"], [5, 7]
        _x, stock_seen, stock = _load(real, names, values, self.KNOWN)
        _y, seen, patched = _load(_patched(real), names, values, self.KNOWN)
        assert patched == stock == {"AngmarBarracks": 5, "AngmarDen": 7}
        assert not stock_seen["thrown"] and not seen["thrown"]


def _merge(image: bytes, keys) -> list[int]:
    m = Machine(image)
    world = World(m)
    seen = _engine(m, world)
    world.template("AngmarBarracks")
    entries = [(build(world), value) for build, value in keys]
    source = world.count_map(entries)
    destination = world.count_map([])
    m.call(LIVING_WORLD_SCORE_KEEPER_MERGE_MAP, destination, source)
    assert m.stopped_at is not None
    return seen["insert"]


class TestMergingWithTheEngine:
    def test_stock_merges_a_key_whose_name_does_not_resolve_as_null(self, real) -> None:
        """An override flagged key resolves by name; one that does not resolve is merged as a
        NULL key, which the next save reads through."""

        def unresolved(world: World) -> int:
            orphan = world.template("Orphan")
            world.by_name.pop("Orphan")  # the factory no longer answers for the name
            m = world.m
            m.uc.mem_write(orphan + OVERRIDABLE_IS_OVERRIDE, b"\x01")
            return orphan

        inserted = _merge(real, [(_live("AngmarBarracks"), 1), (unresolved, 2), (_null, 3)])
        assert 0 in inserted

    def test_the_patch_merges_only_entries_that_resolve(self, real) -> None:
        def unresolved(world: World) -> int:
            orphan = world.template("Orphan")
            world.by_name.pop("Orphan")
            world.m.uc.mem_write(orphan + OVERRIDABLE_IS_OVERRIDE, b"\x01")
            return orphan

        inserted = _merge(
            _patched(real), [(_live("AngmarBarracks"), 1), (unresolved, 2), (_null, 3)]
        )
        assert len(inserted) == 1
        assert inserted[0] != 0
