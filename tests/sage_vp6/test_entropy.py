"""The range coder and the Huffman code builder: what the encoder writes, the decoder reads."""

import random

import pytest

from sage_vp6.huffman import BitReader, HuffmanTable, build_table
from sage_vp6.rangecoder import BoolDecoder, BoolEncoder, tree_paths
from sage_vp6.tables import (
    HUFF_COEFF_MAP,
    HUFF_RUN_MAP,
    PC_TREE,
    PCR_TREE,
    PMBT_TREE,
    PMBTM_TREE,
    PVA_TREE,
)


@pytest.mark.parametrize("seed", range(20))
def test_range_coder_round_trips(seed):
    rng = random.Random(seed)
    symbols = []
    for _ in range(rng.randint(0, 3000)):
        prob = rng.choice([1, 2, 128, 254, 255, rng.randint(1, 255)])
        symbols.append((int(rng.random() < rng.random()), prob))
    encoder = BoolEncoder()
    for bit, prob in symbols:
        encoder.write(bit, prob)
    decoder = BoolDecoder(encoder.finish())
    assert [decoder.read(prob) for _, prob in symbols] == [bit for bit, _ in symbols]


def test_carries_ripple_through_ff_bytes():
    # Long runs of improbable ones drive the low end up until a carry crosses 0xFF bytes.
    encoder = BoolEncoder()
    pattern = [(1, 250)] * 400 + [(0, 3)] * 50 + [(1, 200)] * 400
    for bit, prob in pattern:
        encoder.write(bit, prob)
    decoder = BoolDecoder(encoder.finish())
    assert [decoder.read(prob) for _, prob in pattern] == [bit for bit, _ in pattern]


def test_plain_values_and_probabilities_round_trip():
    encoder = BoolEncoder()
    encoder.write_bits(0b1011001, 7)
    for prob in (1, 2, 128, 254):
        encoder.write_probability(prob)
    decoder = BoolDecoder(encoder.finish())
    assert decoder.read_bits(7) == 0b1011001
    assert [decoder.read_probability() for _ in range(4)] == [1, 2, 128, 254]


@pytest.mark.parametrize("tree", [PC_TREE, PCR_TREE, PMBT_TREE, PMBTM_TREE, PVA_TREE])
def test_tree_paths_decode_to_their_symbol(tree):
    probs = [97] * 16
    paths = tree_paths(tree)
    encoder = BoolEncoder()
    order = sorted(paths)
    for symbol in order:
        for index, bit in paths[symbol]:
            encoder.write(bit, probs[index])
    decoder = BoolDecoder(encoder.finish())
    assert [decoder.read_tree(tree, probs) for _ in order] == order


def _codes(table: HuffmanTable) -> dict[int, str]:
    codes: dict[int, str] = {}

    def walk(node: object, prefix: str) -> None:
        if isinstance(node, list):
            walk(node[0], prefix + "0")
            walk(node[1], prefix + "1")
        else:
            assert isinstance(node, int)
            codes[node] = prefix

    walk(table.root, "")
    return codes


@pytest.mark.parametrize(("node_map", "size"), [(HUFF_COEFF_MAP, 12), (HUFF_RUN_MAP, 9)])
def test_huffman_code_is_complete_and_decodes(node_map, size):
    rng = random.Random(size)
    model = [rng.randint(1, 255) for _ in range(size - 1)]
    codes = _codes(build_table(model, node_map, size))
    assert sorted(codes) == list(range(size))
    assert sum(2 ** -len(code) for code in codes.values()) == 1
    message = [rng.randrange(size) for _ in range(200)]
    bits = "".join(codes[s] for s in message)
    bits += "0" * (-len(bits) % 8)
    data = int(bits, 2).to_bytes(len(bits) // 8, "big")
    reader = BitReader(data)
    table = build_table(model, node_map, size)
    assert [table.read(reader) for _ in message] == message


def test_likelier_symbols_get_shorter_codes():
    # Node 0 of the coefficient tree splits EOB/zero (rare here) from everything else.
    model = [10] + [128] * 10
    codes = _codes(build_table(model, HUFF_COEFF_MAP, 12))
    assert len(codes[11]) > len(codes[1])
