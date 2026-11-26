"""VP6's alternative coefficient coding: Huffman codes built per frame from the same tree
probabilities the range coder would use.

Each model's node probabilities are turned into symbol weights, and a Huffman tree is built
from them with a fixed tie-break order (lighter first, then the higher symbol), so that the
encoder and decoder derive the same codes. The codes are read most significant bit first.
"""

from dataclasses import dataclass

__all__ = ["BitReader", "HuffmanTable", "build_table"]

_INTERNAL = -1


@dataclass(slots=True)
class _Node:
    sym: int
    count: int
    n0: int = -2


class HuffmanTable:
    """Decodes symbols of one code: a binary trie of `(zero, one)` pairs with int leaves."""

    __slots__ = ("root",)

    def __init__(self, codes: dict[int, tuple[int, int]]) -> None:
        root: list[object] = [None, None]
        for symbol, (code, length) in codes.items():
            node = root
            for shift in range(length - 1, 0, -1):
                bit = (code >> shift) & 1
                child = node[bit]
                if isinstance(child, list):
                    node = child
                else:
                    fresh: list[object] = [None, None]
                    node[bit] = fresh
                    node = fresh
            node[code & 1] = symbol
        self.root = root

    def read(self, bits: "BitReader") -> int:
        node: object = self.root
        while isinstance(node, list):
            node = node[bits.read_bit()]
        if not isinstance(node, int):
            raise ValueError("invalid Huffman code")
        return node


def build_table(model: list[int], node_map: tuple[int, ...], size: int) -> HuffmanTable:
    """The code of a `size`-symbol tree whose node `i` splits by `model[i]`, with `node_map`
    naming the children of each node (indices of `size` and above are inner nodes)."""
    nodes = [_Node(sym=i, count=0) for i in range(2 * size)]
    inner = [0] * size
    inner[0] = 256
    for i in range(size - 1):
        a = inner[i] * model[i] >> 8
        b = inner[i] * (255 - model[i]) >> 8
        for child, count in ((node_map[2 * i], a), (node_map[2 * i + 1], b)):
            count = count or 1
            if child >= size:
                inner[child - size] = count
            else:
                nodes[child].count = count

    for i in range(size):
        nodes[i].sym = i
        nodes[i].n0 = -2
    leaves = sorted(nodes[:size], key=lambda n: (n.count, -n.sym))
    nodes[:size] = leaves
    nodes[2 * size - 1].count = 0
    current = size
    for i in range(0, 2 * size - 1, 2):
        merged = nodes[i].count + nodes[i + 1].count
        j = current
        while j > i + 2 and merged <= nodes[j - 1].count:
            nodes[j] = nodes[j - 1]
            j -= 1
        nodes[j] = _Node(sym=_INTERNAL, count=merged, n0=i)
        current += 1

    codes: dict[int, tuple[int, int]] = {}

    def walk(index: int, prefix: int, length: int) -> None:
        node = nodes[index]
        if node.sym != _INTERNAL or not node.count:
            codes[node.sym] = (prefix, length)
            return
        walk(node.n0, prefix << 1, length + 1)
        walk(node.n0 + 1, (prefix << 1) | 1, length + 1)

    walk(2 * size - 2, 0, 0)
    return HuffmanTable(codes)


class BitReader:
    """Reads bits most significant first from `data[start:]`."""

    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes, start: int = 0) -> None:
        self._data = data
        self._pos = start * 8

    def read_bit(self) -> int:
        pos = self._pos
        if pos >= len(self._data) * 8:
            raise ValueError("Huffman partition ended early")
        self._pos = pos + 1
        return (self._data[pos >> 3] >> (7 - (pos & 7))) & 1

    def read_bits(self, count: int) -> int:
        value = 0
        for _ in range(count):
            value = (value << 1) | self.read_bit()
        return value
