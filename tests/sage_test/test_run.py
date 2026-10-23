"""Tests for where a scenario's template map is read from.

Data-free: a template is either a `.map` file on disk or a name inside the install's archives, and
the rule that tells them apart is silent when broken - a file template read from the archives fails
as "not found", an archive name read as a file would never be found at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_test import run
from sage_test.run import EngineUnavailable, read_template


class TestReadTemplate:
    def test_a_map_file_is_read_from_disk(self, tmp_path: Path, monkeypatch):
        template = tmp_path / "test.map"
        template.write_bytes(b"CkMp")
        monkeypatch.setattr(run, "read_archive_file", pytest.fail)
        assert read_template(tmp_path / "install", str(template)) == b"CkMp"

    def test_an_archive_name_is_read_from_the_install(self, tmp_path: Path, monkeypatch):
        asked = []

        def from_archive(install: Path, name: str) -> bytes:
            asked.append((install, name))
            return b"archived"

        monkeypatch.setattr(run, "read_archive_file", from_archive)
        name = "maps\\map mp harlindon\\map mp harlindon.map"
        assert read_template(tmp_path, name) == b"archived"
        assert asked == [(tmp_path, name)]

    def test_a_missing_map_file_is_looked_up_in_the_archives(self, tmp_path: Path, monkeypatch):
        def missing(install: Path, name: str) -> bytes:
            raise FileNotFoundError(name)

        monkeypatch.setattr(run, "read_archive_file", missing)
        with pytest.raises(EngineUnavailable):
            read_template(tmp_path, str(tmp_path / "nowhere.map"))
