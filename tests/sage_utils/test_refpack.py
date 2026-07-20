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
