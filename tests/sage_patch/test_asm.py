"""The label-based emitter.

Its whole job is address arithmetic nobody can check by reading, so the tests are about
displacements being right and wrong ones being refused rather than silently emitted.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.asm import JA, JE, JNE, JNZ, JZ, Asm


def test_emit_takes_ints_as_single_bytes_and_bytes_as_is():
    assert Asm(0).emit(0x90, b"\x01\x02", 0xC3).finish() == b"\x90\x01\x02\xc3"


def test_a_forward_near_jump_resolves_to_the_label():
    a = Asm(0x1000)
    a.jmp("end")  # 5 bytes
    a.emit(b"\x90" * 3)
    a.label("end")
    code = a.finish()
    assert code[0] == 0xE9
    assert struct.unpack_from("<i", code, 1)[0] == 3


def test_a_backward_jump_resolves_negative():
    a = Asm(0x1000)
    a.label("top")
    a.emit(b"\x90" * 4)
    a.jcc(JNE, "top")  # 6 bytes
    code = a.finish()
    assert struct.unpack_from("<i", code, 6)[0] == -10


def test_a_short_jump_is_two_bytes():
    a = Asm(0x1000)
    a.jcc_short(JZ, "end")
    a.emit(b"\x90" * 6)
    a.label("end")
    code = a.finish()
    assert len(code) == 8
    assert code[0] == 0x70 | JZ
    assert code[1] == 6


def test_a_short_jump_that_cannot_reach_is_refused():
    """Silently truncating would land the branch in the middle of an instruction."""
    a = Asm(0x1000)
    a.jmp_short("far")
    a.emit(b"\x90" * 200)
    a.label("far")
    with pytest.raises(ValueError, match="does not fit in rel8"):
        a.finish()


def test_an_undefined_label_is_refused_rather_than_assembled():
    a = Asm(0x1000)
    a.jmp("nowhere")
    with pytest.raises(ValueError, match="undefined label"):
        a.finish()


def test_a_duplicate_label_is_refused():
    a = Asm(0x1000)
    a.label("x")
    with pytest.raises(ValueError, match="duplicate label"):
        a.label("x")


def test_call_absolute_is_relative_to_the_following_instruction():
    a = Asm(0x1000)
    a.emit(b"\x90" * 4)  # so the call does not start at base
    a.call_absolute(0x2000)
    code = a.finish()
    # the call occupies 0x1004..0x1009, so the displacement is measured from 0x1009
    assert code[4] == 0xE8
    assert struct.unpack_from("<i", code, 5)[0] == 0x2000 - 0x1009


def test_jmp_absolute_reaches_backwards_too():
    a = Asm(0x00F00000)
    a.jmp_absolute(0x0062E4ED)
    code = a.finish()
    assert code[0] == 0xE9
    assert struct.unpack_from("<i", code, 1)[0] == 0x0062E4ED - (0x00F00000 + 5)


def test_moving_the_base_changes_absolute_calls_but_not_labels():
    def build(base: int) -> bytes:
        a = Asm(base)
        a.jcc(JE, "done")
        a.call_absolute(0x2000)
        a.label("done")
        return a.finish()

    lo, hi = build(0x1000), build(0x9000)
    assert len(lo) == len(hi)
    assert lo[:6] == hi[:6], "the label-relative branch does not depend on the base"
    assert lo[6:] != hi[6:], "the absolute call does"


def test_va_tracks_emitted_length():
    a = Asm(0x1000)
    assert a.va == 0x1000
    a.emit(b"\x90" * 7)
    assert a.va == 0x1007


def test_condition_aliases_agree():
    assert JE == JZ
    assert JNE == JNZ
    assert JA not in (JE, JNE)
