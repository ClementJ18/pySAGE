"""Tests for the pure-Python EA RefPack codec (`sage_utils.refpack`).

Two tiers, matching the project split:

- **core** (data-free, sub-second): synthetic round-trip and format checks. These
  prove the codec is self-consistent - `decompress(compress(x)) == x` for inputs
  chosen to exercise every command form - and that the header/errors behave.
- **full** (`--full`): byte-exact parity against the real, EA-compressed map
  fixtures. This is the strong gate: it proves our compressor reproduces the
  reference RefPack stream byte-for-byte, so a re-saved map is identical to the
  original on disk (what `sage_map`'s round-trip guarantee needs).
"""

import os
import random
import sys
import types
import warnings
from pathlib import Path

import pytest

import sage_utils.refpack as rp
from sage_utils.refpack import (
    RefpackError,
    RefpackPerformanceWarning,
    _compress_pure,
    compress,
    decompress,
)

# The pure-Python fallback warning is expected all through this module (the native
# accelerator is absent or non-functional off Windows); the dedicated test below asserts
# it explicitly via `pytest.warns`, so silence it everywhere else to keep output clean.
pytestmark = pytest.mark.filterwarnings("ignore::sage_utils.refpack.RefpackPerformanceWarning")

MAPS_DIR = Path(__file__).resolve().parent.parent / "sage_map" / "fixtures" / "maps"


def compressed_fixture_bodies() -> list[tuple[str, bytes]]:
    """(name, refpack-stream) for every EA-compressed map fixture.

    The on-disk `.map`/`.bse` is an 8-byte `EAR\\0` + uint32 wrapper around the
    RefPack stream; we strip it to get the stream our codec speaks.
    """
    out: list[tuple[str, bytes]] = []
    if not MAPS_DIR.is_dir():
        return out
    for path in sorted(MAPS_DIR.iterdir()):
        blob = path.read_bytes()
        body = blob[8:] if blob[:4] == b"EAR\x00" else blob
        if body[:2] == b"\x10\xfb":
            out.append((path.name, body))
    return out


SMALL_PARITY_FIXTURE = "ki lorien.map"


def _roundtrip(data: bytes) -> None:
    stream = compress(data)
    assert stream[:2] == b"\x10\xfb", "compressed stream must carry the RefPack magic"
    assert decompress(stream) == data


# Synthetic round-trip: self-consistency across every command form.


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"A",
        b"AB",
        b"ABC",
        b"AAAA",
        b"A" * 3,
        b"A" * 112,
        b"A" * 113,
        b"A" * 5000,  # long matches -> very-long form, length capped at 1028
        b"hello world " * 500,
        bytes(range(256)) * 40,
        b"The quick brown fox jumps over the lazy dog. " * 200,
    ],
    ids=[
        "empty",
        "one",
        "two",
        "three",
        "four-equal",
        "three-equal",
        "run-112",
        "run-113",
        "long-repeat",
        "phrase-repeat",
        "incrementing",
        "prose-repeat",
    ],
)
def test_roundtrip_synthetic(data: bytes) -> None:
    _roundtrip(data)


@pytest.mark.parametrize("seed", range(12))
def test_roundtrip_random(seed: int) -> None:
    rng = random.Random(seed)
    # Mix incompressible noise with repeated chunks so both literal runs and
    # back-references appear in the same stream.
    chunks: list[bytes] = []
    for _ in range(rng.randint(1, 40)):
        if rng.random() < 0.5:
            chunks.append(bytes(rng.randrange(256) for _ in range(rng.randint(1, 200))))
        else:
            unit = rng.choice([b"abcd", b"XY", b"\x00", b"middle-earth "])
            chunks.append(unit * rng.randint(1, 60))
    _roundtrip(b"".join(chunks))


def test_roundtrip_incompressible() -> None:
    # Pure noise: forces long literal blocks (0xe0..) and the EOF literal tail.
    _roundtrip(os.urandom(4096))


@pytest.mark.full
def test_roundtrip_far_match() -> None:
    # A repeat separated by nearly the whole 128 KiB window exercises the
    # very-long form at a large offset. 128 KiB in pure Python -> full tier.
    payload = os.urandom(64) + os.urandom(131000) + os.urandom(64)
    _roundtrip(payload + payload[:64])


# Format / error handling.


def test_decompress_rejects_bad_magic() -> None:
    with pytest.raises(RefpackError):
        decompress(b"NOPE" + b"\x00" * 8)


def test_decompress_rejects_truncated() -> None:
    with pytest.raises(RefpackError):
        decompress(b"\x10\xfb")


def test_empty_roundtrips_to_empty() -> None:
    assert decompress(compress(b"")) == b""


def test_decompress_rejects_backref_before_start() -> None:
    """A back-reference at output offset 0 has nowhere to point to."""
    with pytest.raises(RefpackError):
        decompress(b"\x10\xfb\x00\x00\x03\x00\x00\xfc")


def test_decompress_rejects_undersized_output() -> None:
    """Header declares 10 bytes but the body yields 0."""
    with pytest.raises(RefpackError):
        decompress(b"\x10\xfb\x00\x00\x0a\xfc")


def test_decompress_rejects_truncated_literal_tail() -> None:
    """EOF command claims 3 trailing literals but only 1 is present."""
    with pytest.raises(RefpackError):
        decompress(b"\x10\xfb\x00\x00\x03\xff" + b"A")


def test_decompress_rejects_overlong_output() -> None:
    """Header declares 0 bytes but EOF command carries 1 literal byte."""
    with pytest.raises(RefpackError):
        decompress(b"\x10\xfb\x00\x00\x00\xfd" + b"A")


def test_compress_rejects_oversized_input() -> None:
    """The 3-byte size field caps input at 16 MiB - 1; reject anything larger."""
    with pytest.raises(RefpackError):
        compress(bytes(0xFFFFFF + 1))


# Header variants the compressor never emits but the decoder accepts.


def test_decompress_skips_compressed_size_field() -> None:
    """First header byte 0x11 flags a compressed-size field that the decoder skips."""
    payload = b"header variants " * 20
    stream = _compress_pure(payload)
    size3, body = stream[2:5], stream[5:]
    assert decompress(b"\x11\xfb" + b"\x00\x00\x00" + size3 + body) == payload


def test_decompress_reads_4byte_size_field() -> None:
    """First header byte 0x90 flags 4-byte size fields."""
    payload = b"header variants " * 20
    stream = _compress_pure(payload)
    body = stream[5:]
    assert decompress(b"\x90\xfb" + len(payload).to_bytes(4, "big") + body) == payload


def test_decompress_4byte_size_with_compressed_size_field() -> None:
    """First header byte 0x91 flags both compressed-size and 4-byte size fields."""
    payload = b"header variants " * 20
    stream = _compress_pure(payload)
    body = stream[5:]
    assert (
        decompress(b"\x91\xfb" + b"\x00\x00\x00\x00" + len(payload).to_bytes(4, "big") + body)
        == payload
    )


# Byte-exact parity with the reference EA compressor (the strong gate).


def test_parity_small() -> None:
    """Fast parity check on the smallest compressed fixture (core-tier).

    Targets the pure-Python compressor directly so its byte-exactness is asserted on
    every platform, regardless of whether the native accelerator happens to be present.
    """
    if not MAPS_DIR.is_dir():
        pytest.skip("map fixtures not present")
    body = (MAPS_DIR / SMALL_PARITY_FIXTURE).read_bytes()[8:]
    raw = decompress(body)
    assert _compress_pure(raw) == body, "recompressed stream must match EA's bytes exactly"


@pytest.mark.full
@pytest.mark.parametrize(
    "name,body", compressed_fixture_bodies(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_parity_corpus(name: str, body: bytes) -> None:
    """Byte-exact parity across every compressed map fixture, all sizes."""
    raw = decompress(body)
    assert _compress_pure(raw) == body, f"recompressed stream diverges from EA's bytes for {name}"


def test_compress_falls_back_to_pure_python_with_warning(monkeypatch) -> None:
    """With no usable native backend, `compress` warns once and uses the pure codec.

    Blocking the reversebox import forces the fallback path deterministically, so the
    test holds whether or not a working native accelerator is installed.
    """
    monkeypatch.setattr(rp, "_native_probed", False)
    monkeypatch.setattr(rp, "_native_compress_fn", None)
    monkeypatch.setitem(sys.modules, "reversebox.compression.compression_refpack", None)

    payload = b"middle-earth " * 40
    with pytest.warns(RefpackPerformanceWarning):
        stream = compress(payload)
    assert decompress(stream) == payload
    assert stream == _compress_pure(payload)


def _literal_only_refpack(data: bytes) -> bytes:
    """A valid RefPack encoding using only literal runs - decodes correctly but
    never matches the reference encoder's bytes on compressible input."""
    out = bytearray(b"\x10\xfb" + len(data).to_bytes(3, "big"))
    pos = 0
    while len(data) - pos > 3:
        chunk = min(112, (len(data) - pos) & ~3)
        out.append(0xE0 + (chunk >> 2) - 1)
        out += data[pos : pos + chunk]
        pos += chunk
    rest = len(data) - pos
    out.append(0xFC + rest)
    out += data[pos:]
    return bytes(out)


def test_native_backend_rejected_when_output_diverges(monkeypatch) -> None:
    """The native backend is rejected if its output diverges from the pure codec's."""
    monkeypatch.setattr(rp, "_native_probed", False)
    monkeypatch.setattr(rp, "_native_compress_fn", None)

    payload = b"middle-earth " * 40
    # Premise: the literal-only encoding decodes correctly but differs from the
    # reference encoder's bytes on compressible input.
    assert decompress(_literal_only_refpack(payload)) == payload
    assert _literal_only_refpack(payload) != _compress_pure(payload)

    fake_module = types.ModuleType("compression_refpack")

    class FakeRefpackHandler:
        @staticmethod
        def compress_data(data: bytes) -> bytes:
            return _literal_only_refpack(data)

    fake_module.RefpackHandler = FakeRefpackHandler
    monkeypatch.setitem(sys.modules, "reversebox.compression.compression_refpack", fake_module)

    with pytest.warns(RefpackPerformanceWarning):
        stream = compress(payload)
    assert stream == _compress_pure(payload)


def test_native_backend_accepted_on_byte_parity(monkeypatch) -> None:
    """The native backend is accepted if its output has byte parity with the pure codec."""
    monkeypatch.setattr(rp, "_native_probed", False)
    monkeypatch.setattr(rp, "_native_compress_fn", None)

    payload = b"middle-earth " * 40
    fake_module = types.ModuleType("compression_refpack")

    class FakeRefpackHandler:
        @staticmethod
        def compress_data(data: bytes) -> bytes:
            return _compress_pure(data)

    fake_module.RefpackHandler = FakeRefpackHandler
    monkeypatch.setitem(sys.modules, "reversebox.compression.compression_refpack", fake_module)

    with warnings.catch_warnings(record=True) as warning_list:
        warnings.simplefilter("always")
        stream = compress(payload)
    assert not any(issubclass(w.category, RefpackPerformanceWarning) for w in warning_list)
    assert stream == _compress_pure(payload)
    assert rp._native_compress_fn is not None
