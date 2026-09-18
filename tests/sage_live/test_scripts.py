"""The live script-tree reader, against a hand-built image of the engine's structures.

The layout itself is derived statically (`sage_patch/docs/script-debugger.md` §2) and confirmed
against a running game by `examples/sage_live/script_tree.py --map`; these tests pin the walk -
pools, generations, nested groups, the std::map order - so a refactor cannot quietly change what
the debugger thinks the engine will run.
"""

from __future__ import annotations

import struct

from sage_live.backends.scripts import read_script_tree, read_script_variables
from sage_patch.addresses import (
    SCRIPT_ACTIVE,
    SCRIPT_AUTHORED_ACTIVE,
    SCRIPT_DELAY_SECONDS,
    SCRIPT_EASY,
    SCRIPT_ENGINE_COUNTER_MAP,
    SCRIPT_ENGINE_DIFFICULTY,
    SCRIPT_ENGINE_FLAG_MAP,
    SCRIPT_GROUP_ACTIVE,
    SCRIPT_GROUP_GROUPS,
    SCRIPT_GROUP_SCRIPTS,
    SCRIPT_HARD,
    SCRIPT_LIST_ENTRY_GENERATION,
    SCRIPT_LIST_ENTRY_NAME,
    SCRIPT_LIST_ENTRY_OBJECTS,
    SCRIPT_LIST_ENTRY_SIZE,
    SCRIPT_LIST_GROUP_ENTRIES,
    SCRIPT_LIST_GROUPS,
    SCRIPT_LIST_SCRIPT_ENTRIES,
    SCRIPT_LIST_SCRIPTS,
    SCRIPT_NEXT_FRAME,
    SCRIPT_NODE_GENERATION,
    SCRIPT_NODE_INDEX,
    SCRIPT_NODE_NEXT,
    SCRIPT_NORMAL,
    SCRIPT_ONE_SHOT,
    SCRIPT_SEQUENTIAL,
    SIDES_INFO_SCRIPT_LIST,
    SIDES_INFO_STRIDE,
    SIDES_LIST_SIDE_COUNT,
    SIDES_LIST_SIDES,
    STD_MAP_NODE_VALUE,
    THE_SCRIPT_ENGINE,
    THE_SIDES_LIST,
)

HEAP = 0x10000000


class Image:
    """Sparse process memory: a read touching any unwritten byte fails, as an unmapped page does."""

    def __init__(self) -> None:
        self.bytes: dict[int, int] = {}
        self._next = HEAP

    def read(self, address: int, size: int) -> bytes | None:
        try:
            return bytes(self.bytes[address + i] for i in range(size))
        except KeyError:
            return None

    def write(self, address: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.bytes[address + i] = b

    def u32(self, address: int, value: int) -> None:
        self.write(address, struct.pack("<I", value))

    def alloc(self, size: int) -> int:
        address = self._next
        self._next += (size + 15) & ~15
        self.write(address, bytes(size))
        return address

    def ascii(self, text: str) -> int:
        raw = text.encode("latin-1")
        address = self.alloc(8 + len(raw) + 1)
        self.u32(address, 1)
        self.write(address + 4, struct.pack("<HH", len(raw), len(raw) + 1))
        self.write(address + 8, raw)
        return address


class ScriptListBuilder:
    """One `ScriptList`: two pools of name entries, and nodes that point into them."""

    def __init__(self, image: Image, address: int) -> None:
        self.image = image
        self.address = address
        self.pools = {
            kind: image.alloc(SCRIPT_LIST_ENTRY_SIZE * 16) for kind in ("script", "group")
        }
        self.counts = {"script": 0, "group": 0}
        image.u32(address + SCRIPT_LIST_SCRIPT_ENTRIES, self.pools["script"])
        image.u32(address + SCRIPT_LIST_GROUP_ENTRIES, self.pools["group"])

    def _entry(self, kind: str, name: str, obj_size: int, generation: int = 0) -> tuple[int, int]:
        index = self.counts[kind]
        self.counts[kind] += 1
        entry = self.pools[kind] + index * SCRIPT_LIST_ENTRY_SIZE
        holder = self.image.alloc(4 + obj_size)  # the object chain node; the object sits at +4
        self.image.u32(entry + SCRIPT_LIST_ENTRY_NAME, self.image.ascii(name))
        self.image.write(entry + SCRIPT_LIST_ENTRY_GENERATION, struct.pack("<h", generation))
        self.image.u32(entry + SCRIPT_LIST_ENTRY_OBJECTS, holder)
        return index, holder + 4

    def chain(self, nodes: list[tuple[int, int]]) -> int:
        """A node chain over `(index, generation)` pairs; returns its head."""
        head = 0
        for index, generation in reversed(nodes):
            node = self.image.alloc(12)
            self.image.u32(node + SCRIPT_NODE_NEXT, head)
            self.image.u32(node + SCRIPT_NODE_INDEX, index)
            self.image.u32(node + SCRIPT_NODE_GENERATION, generation)
            head = node
        return head

    def script(self, name: str, **fields: int) -> tuple[int, int]:
        index, obj = self._entry("script", name, SCRIPT_ACTIVE + 0x10)
        for offset in (SCRIPT_EASY, SCRIPT_NORMAL, SCRIPT_HARD, SCRIPT_ACTIVE):
            self.image.write(obj + offset, b"\x01")
        self.image.write(obj + SCRIPT_AUTHORED_ACTIVE, b"\x01")
        offsets = {
            "active": SCRIPT_ACTIVE,
            "authored_active": SCRIPT_AUTHORED_ACTIVE,
            "one_shot": SCRIPT_ONE_SHOT,
            "sequential": SCRIPT_SEQUENTIAL,
            "hard": SCRIPT_HARD,
        }
        for key, value in fields.items():
            if key == "delay":
                self.image.write(obj + SCRIPT_DELAY_SECONDS, struct.pack("<i", value))
            elif key == "next_frame":
                self.image.u32(obj + SCRIPT_NEXT_FRAME, value)
            elif key == "true_actions":
                self.image.u32(obj + 0x34, value)
            else:
                self.image.write(obj + offsets[key], bytes([value]))
        return index, obj

    def group(self, name: str, scripts: int, groups: int, active: bool = True) -> int:
        index, obj = self._entry("group", name, 0x10)
        self.image.u32(obj + SCRIPT_GROUP_SCRIPTS, scripts)
        self.image.u32(obj + SCRIPT_GROUP_GROUPS, groups)
        self.image.write(obj + SCRIPT_GROUP_ACTIVE, bytes([active]))
        return index

    def top(self, scripts: int, groups: int) -> None:
        self.image.u32(self.address + SCRIPT_LIST_SCRIPTS, scripts)
        self.image.u32(self.address + SCRIPT_LIST_GROUPS, groups)


def game_with_scripts() -> Image:
    image = Image()
    sides = image.alloc(SIDES_LIST_SIDES + 2 * SIDES_INFO_STRIDE)
    image.u32(THE_SIDES_LIST, sides)
    image.u32(sides + SIDES_LIST_SIDE_COUNT, 2)
    for i in range(2):
        image.write(sides + SIDES_LIST_SIDES + i * SIDES_INFO_STRIDE, bytes(SIDES_INFO_STRIDE))

    lst = ScriptListBuilder(image, sides + SIDES_LIST_SIDES + SIDES_INFO_SCRIPT_LIST)
    intro, _ = lst.script("Intro", one_shot=1, active=0)
    stale, _ = lst.script("Deleted")
    wave, _ = lst.script("Wave", delay=5, next_frame=900, sequential=1, true_actions=0x4000)
    inner, _ = lst.script("Inner", hard=0)
    nested = lst.group("Nested", lst.chain([(inner, 0)]), 0)
    outer = lst.group("Outer", lst.chain([(wave, 0)]), lst.chain([(nested, 0)]))
    # `Deleted`'s node carries generation 1 against an entry at 0: a stale handle.
    lst.top(lst.chain([(intro, 0), (stale, 1)]), lst.chain([(outer, 0)]))

    engine = image.alloc(SCRIPT_ENGINE_DIFFICULTY + 4)
    image.u32(THE_SCRIPT_ENGINE, engine)
    image.u32(engine + SCRIPT_ENGINE_DIFFICULTY, 2)
    return image


def test_the_walk_returns_what_the_engine_would_run() -> None:
    tree = read_script_tree(game_with_scripts().read)
    assert tree is not None
    assert tree.difficulty == 2
    side, empty = tree.sides
    assert [s.name for s in side.all_scripts()] == ["Intro", "Wave", "Inner"]
    assert empty.all_scripts() == []


def test_script_fields_decode() -> None:
    tree = read_script_tree(game_with_scripts().read)
    assert tree is not None
    ((_, intro),) = tree.find("Intro")
    assert intro.one_shot and not intro.active and intro.authored_active
    ((_, wave),) = tree.find("Wave")
    assert (wave.delay_seconds, wave.next_frame, wave.sequential) == (5, 900, True)
    ((_, inner),) = tree.find("Inner")
    assert (inner.easy, inner.normal, inner.hard) == (True, True, False)


def test_groups_nest_and_carry_their_path() -> None:
    tree = read_script_tree(game_with_scripts().read)
    assert tree is not None
    (outer,) = tree.sides[0].groups
    (nested,) = outer.groups
    assert (outer.name, nested.name) == ("Outer", "Nested")
    assert nested.scripts[0].path == ("Outer", "Nested")


def test_no_sides_list_is_no_tree() -> None:
    assert read_script_tree(Image().read) is None


def test_a_cyclic_chain_ends() -> None:
    image = game_with_scripts()
    tree = read_script_tree(image.read)
    assert tree is not None
    # Point the last top-level node back at the first.
    sides = struct.unpack("<I", image.read(THE_SIDES_LIST, 4) or b"")[0]
    lst = sides + SIDES_LIST_SIDES + SIDES_INFO_SCRIPT_LIST
    head = struct.unpack("<I", image.read(lst + SCRIPT_LIST_SCRIPTS, 4) or b"")[0]
    second = struct.unpack("<I", image.read(head + SCRIPT_NODE_NEXT, 4) or b"")[0]
    image.u32(second + SCRIPT_NODE_NEXT, head)
    looped = read_script_tree(image.read)
    assert looped is not None
    assert [s.name for s in looped.sides[0].scripts] == ["Intro"]


def std_map(image: Image, records: list[tuple[str, str, bytes]]) -> int:
    """A balanced red-black-shaped tree over sorted `(scope, name, value)`; returns its header."""
    header = image.alloc(0x20)
    nodes = []
    for scope, name, value in records:
        node = image.alloc(STD_MAP_NODE_VALUE + 8)
        image.u32(node + 0x10, image.ascii(scope) if scope else 0)
        image.u32(node + 0x14, image.ascii(name))
        image.write(node + STD_MAP_NODE_VALUE, value)
        nodes.append(node)

    def build(lo: int, hi: int, parent: int) -> int:
        if lo >= hi:
            return 0
        mid = (lo + hi) // 2
        node = nodes[mid]
        image.u32(node + 0x04, parent)
        image.u32(node + 0x08, build(lo, mid, node))
        image.u32(node + 0x0C, build(mid + 1, hi, node))
        return node

    root = build(0, len(nodes), header)
    image.u32(header + 0x04, root)
    image.u32(header + 0x08, nodes[0])
    image.u32(header + 0x0C, nodes[-1])
    return header


def test_variables_read_in_key_order() -> None:
    image = game_with_scripts()
    engine = struct.unpack("<I", image.read(THE_SCRIPT_ENGINE, 4) or b"")[0]
    image.write(engine + SCRIPT_ENGINE_COUNTER_MAP, bytes(0x20))
    counters = [
        ("", "E", struct.pack("<iBB", 1125, 0, 0)),
        ("", "Spieleranzahl", struct.pack("<iBB", 1, 0, 0)),
        ("", "Timer", struct.pack("<iBB", 49814, 1, 1)),
        ("Player_1", "Hoehe", struct.pack("<iBB", 16, 0, 0)),
        ("PlyrCreeps", "Spawn", struct.pack("<iBB", 8, 0, 0)),
    ]
    image.u32(engine + SCRIPT_ENGINE_COUNTER_MAP, std_map(image, counters))
    image.u32(engine + SCRIPT_ENGINE_FLAG_MAP, std_map(image, [("", "FreeBuild", b"\x01")]))

    variables = read_script_variables(image.read)
    assert [(v.kind, v.key, v.value) for v in variables] == [
        ("counter", "/E", 1125),
        ("counter", "/Spieleranzahl", 1),
        ("timer", "/Timer", 49814),
        ("counter", "Player_1/Hoehe", 16),
        ("counter", "PlyrCreeps/Spawn", 8),
        ("flag", "/FreeBuild", 1),
    ]
    assert variables[2].seconds


def test_a_script_knows_its_name_record_and_which_action_lists_it_has() -> None:
    image = game_with_scripts()
    tree = read_script_tree(image.read)
    assert tree is not None
    ((_, wave),) = tree.find("Wave")
    assert (wave.has_true_actions, wave.has_false_actions) == (True, False)
    # The name record is the pool entry's AsciiString: its characters read back as the name.
    block = struct.unpack("<I", image.read(wave.name_address, 4) or b"")[0]
    assert image.read(block + 8, 4) == b"Wave"
