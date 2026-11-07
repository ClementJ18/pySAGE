"""Commit-hook Git overrides must never redirect temporary test repositories."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("repository_overrides", [False, True], ids=["index-only", "repository"])
def test_nested_git_tests_preserve_the_calling_repository_index(tmp_path, repository_overrides):
    outer = tmp_path / "committing-repository"
    subprocess.run(["git", "init", "-q", str(outer)], check=True)
    (outer / "keep.txt").write_text("The staged user content must survive the test suite.\n")
    subprocess.run(["git", "-C", str(outer), "add", "keep.txt"], check=True)
    index = outer / ".git/index"
    before = index.read_bytes()

    # Run the real map textconv integration tests under the environment a commit hook can
    # inherit. Their own git init/add/commit must operate solely on their temporary repositories.
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = str(index)
    if repository_overrides:
        env.update(
            GIT_DIR=str(outer / ".git"),
            GIT_COMMON_DIR=str(outer / ".git"),
            GIT_OBJECT_DIRECTORY=str(outer / ".git/objects"),
            GIT_WORK_TREE=str(outer),
        )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(tmp_path / "inner-tests"),
            "tests/sage_map/test_textconv.py::test_cli_install_registers_the_diff_driver",
            "tests/sage_map/test_textconv.py::test_git_diff_names_the_changed_script_in_the_hunk_header",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
    )
    assert index.read_bytes() == before, "nested tests modified the calling commit's index"
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
    # Every object referenced by the preserved index must still belong to the calling repo.
    subprocess.run(["git", "-C", str(outer), "write-tree"], check=True, capture_output=True)
