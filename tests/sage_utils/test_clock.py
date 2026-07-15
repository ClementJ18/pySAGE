"""`clock`/`hms` duration formatting: boundary and clamping behaviour."""

from sage_utils.clock import clock, hms


def test_clock_zero():
    assert clock(0) == "0:00"


def test_clock_sub_minute():
    assert clock(45) == "0:45"


def test_clock_minute_boundary():
    assert clock(59.9) == "0:59"
    assert clock(60) == "1:00"


def test_hms_zero():
    assert hms(0) == "0:00:00"


def test_hms_over_an_hour():
    assert hms(3725) == "1:02:05"


def test_hms_negative_clamps_to_zero():
    assert hms(-5) == "0:00:00"
