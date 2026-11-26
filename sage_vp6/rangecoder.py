"""The boolean range coder VP6 codes every symbol with.

Each bit is coded against an 8-bit probability that it is 0 (`prob / 256`); a probability of 128
is an even coin, which is how the bitstream's plain bits are read. `BoolDecoder` reads a
partition and `BoolEncoder` writes one, so that the decoder reads back exactly the bits written.
"""

from sage_vp6.tables import NORM_SHIFT

__all__ = ["BoolDecoder", "BoolEncoder", "Tree", "tree_paths"]

# A tree node is `(probability_index, zero_branch, one_branch)`; a leaf is the decoded symbol.
type Tree = tuple[int, "Tree | int", "Tree | int"]


class BoolDecoder:
    """Reads bits from one partition of a frame: `data[start:end]`."""

    def __init__(self, data: bytes, start: int = 0, end: int | None = None) -> None:
        self._data = data
        self._end = len(data) if end is None else end
        self._high = 255
        self._bits = -16
        self._code = (
            (self._byte(start) << 16) | (self._byte(start + 1) << 8) | self._byte(start + 2)
        )
        self._pos = start + 3

    def _byte(self, index: int) -> int:
        return self._data[index] if index < self._end else 0

    def read(self, prob: int) -> int:
        """One bit, with `prob / 256` the probability that it is 0."""
        shift = NORM_SHIFT[self._high]
        high = self._high << shift
        code = self._code << shift
        bits = self._bits + shift
        if bits >= 0 and self._pos < self._end:
            code |= ((self._byte(self._pos) << 8) | self._byte(self._pos + 1)) << bits
            self._pos += 2
            bits -= 16
        self._bits = bits
        split = 1 + (((high - 1) * prob) >> 8)
        threshold = split << 16
        if code >= threshold:
            self._high = high - split
            self._code = code - threshold
            return 1
        self._high = split
        self._code = code
        return 0

    def read_bits(self, count: int) -> int:
        """An unsigned `count`-bit value of even-coin bits, most significant first."""
        value = 0
        for _ in range(count):
            value = (value << 1) | self.read(128)
        return value

    def read_probability(self) -> int:
        """A 7-bit model probability as the bitstream stores it: doubled, and never 0."""
        value = self.read_bits(7) << 1
        return value or 1

    def read_tree(self, tree: Tree, probs: list[int] | tuple[int, ...]) -> int:
        node: Tree | int = tree
        while isinstance(node, tuple):
            index, zero, one = node
            node = one if self.read(probs[index]) else zero
        return node


class BoolEncoder:
    """Writes bits into one partition; `finish` returns its bytes."""

    def __init__(self) -> None:
        self._out = bytearray()
        self._low = 0
        self._range = 255
        self._count = -24

    def write(self, bit: int, prob: int) -> None:
        """One bit, with `prob / 256` the probability that it is 0."""
        split = 1 + (((self._range - 1) * prob) >> 8)
        if bit:
            self._low += split
            span = self._range - split
        else:
            span = split
        shift = NORM_SHIFT[span]
        self._range = span << shift
        count = self._count + shift
        low = self._low
        if count >= 0:
            offset = shift - count
            if low & (1 << (32 - offset)):
                # A carry out of the pending byte ripples back through any 0xFF bytes.
                out = self._out
                index = len(out) - 1
                while index >= 0 and out[index] == 0xFF:
                    out[index] = 0
                    index -= 1
                out[index] += 1
            self._out.append((low >> (24 - offset)) & 0xFF)
            low = (low << offset) & 0xFFFFFF
            shift = count
            count -= 8
        self._low = low << shift
        self._count = count

    def write_bits(self, value: int, count: int) -> None:
        """An unsigned `count`-bit value as even-coin bits, most significant first."""
        for shift in range(count - 1, -1, -1):
            self.write((value >> shift) & 1, 128)

    def write_probability(self, prob: int) -> None:
        """A model probability (1 or an even value up to 254) in its 7-bit stored form."""
        self.write_bits(prob >> 1, 7)

    def finish(self) -> bytes:
        """Flush the coder; the encoder must not be written to afterwards."""
        for _ in range(32):
            self.write(0, 128)
        return bytes(self._out)


def tree_paths(tree: Tree) -> dict[int, tuple[tuple[int, int], ...]]:
    """Symbol -> the `(probability_index, bit)` steps that code it in `tree`."""
    paths: dict[int, tuple[tuple[int, int], ...]] = {}

    def walk(node: Tree | int, path: tuple[tuple[int, int], ...]) -> None:
        if isinstance(node, tuple):
            index, zero, one = node
            walk(zero, (*path, (index, 0)))
            walk(one, (*path, (index, 1)))
        else:
            paths.setdefault(node, path)

    walk(tree, ())
    return paths
