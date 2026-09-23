"""Tests for `census.c`, milestone M1's call counter, run as a real 32-bit program.

`harness.c` compiles `census.c` into a 32-bit Windows executable alongside fake Direct3D objects,
hooks them the way the module hooks the real ones, and checks each call's arguments, result and
count. The generated thunks are machine code, so this is the only place short of a running game
where they execute. It needs the `accel` extra to build and Windows to run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sage_accel.build import SOURCES, TARGET, have_toolchain

HARNESS = Path(__file__).resolve().parent / "harness.c"
SRC = SOURCES[0].parent


@pytest.fixture(scope="module")
def output(tmp_path_factory: pytest.TempPathFactory) -> str:
    if not have_toolchain():
        pytest.skip("needs the accel extra (ziglang)")
    if sys.platform != "win32":
        pytest.skip("runs a 32-bit Windows program")
    exe = tmp_path_factory.mktemp("census") / "harness.exe"
    subprocess.run(
        [sys.executable, "-m", "ziglang", "cc", "-target", TARGET, "-O2", "-Wall", "-Wextra",
         "-Werror", f"-I{SRC}", "-o", str(exe), str(HARNESS), "-luser32", "-lwinmm"],
        check=True,
    )  # fmt: skip
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60, check=False)
    assert run.returncode == 0, run.stdout + run.stderr
    return run.stdout


def test_every_check_passes(output: str) -> None:
    assert "HARNESS OK" in output
    assert "FAIL" not in output


def test_hooks_are_reported(output: str) -> None:
    assert "hooked in place, 119 of 119 slots" in output
    assert "vb locks hooked in 1 vtable(s)" in output


def test_the_report_names_what_it_counted(output: str) -> None:
    """Four frames: one before a Reset that rewrote every entry, then the hitch pair."""
    assert (
        "device calls/frame: 4.5 (queued 3.5, draining 0.5, direct 0.5); STALLS/frame 0.5, "
        "worst frame 2"
    ) in output
    assert "stalls/frame by device method: GetRenderState 0.3" in output
    assert "vb locks/frame: 0.3 (discard 0.3" in output
    assert (
        "queued methods/frame: SetRenderState 1.8, Present 1.0, DrawPrimitive 0.5, Reset 0.3"
        in (output)
    )
    assert "direct methods/frame: CreateVertexBuffer 0.5" in output
    assert "other threads, whole window: 1 device calls" in output


def test_rewritten_entries_are_hooked_again(output: str) -> None:
    assert "status: 119 of 119 device slots ours before this check; 0 repaired so far" in output
    assert "status: 118 of 119 device slots ours before this check" in output
    assert "census: 1 device slots hooked again by the watchdog" in output
    assert "Reset = 0x00000066" in output
    assert "census: 119 device slots hooked again after Reset" in output
    assert "the device now points at another vtable" in output


def test_the_watchdog_counts(output: str) -> None:
    assert "status: frames 1; Present game thread 1, other threads 0" in output


def test_the_sampler_files_time_by_module(output: str) -> None:
    assert "inside Present:" in output
    assert "game thread time by module (" in output
    report_line = output.split("report: ")[1].split("game thread time by module")[1].splitlines()[0]
    assert "harness.exe" in report_line
    assert "(census thunks)" in output


def test_a_slow_frame_is_logged_on_its_own(output: str) -> None:
    block = output.split("HITCH: ")[1]
    assert block.startswith("frame 1")  # 120-odd ms
    assert "game thread time by module" in block
    assert "creations: CreateVertexBuffer 1.0" in block
