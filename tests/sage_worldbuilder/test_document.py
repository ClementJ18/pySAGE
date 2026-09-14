"""MapDocument file handling, safe writes and autosave rotation."""

import os
import stat
from dataclasses import dataclass

import pytest

from sage_map.map import Map
from sage_worldbuilder import (
    Autosaver,
    AutosaveSettings,
    Change,
    ChangeKind,
    MapDocument,
    ReadOnlyMapError,
    SetAttribute,
    atomic_write,
)
from sage_worldbuilder.autosave import autosave_paths, rotate_autosaves


@dataclass
class Target:
    value: int = 0


def edit(document: MapDocument, value: int = 1) -> None:
    # A fresh target each time, so successive edits never merge into one entry.
    document.execute(SetAttribute(Target(), "value", value, Change(ChangeKind.SETTINGS)))


def test_save_then_open_round_trips(tmp_path):
    path = tmp_path / "empty.map"
    document = MapDocument(Map())
    edit(document)
    assert document.dirty
    assert document.title == "Untitled"

    document.save(path, compress=False)

    assert not document.dirty
    assert document.path == path
    reopened = MapDocument.open(path)
    assert reopened.to_bytes() == path.read_bytes()
    assert not reopened.compressed
    assert reopened.title == "empty"


def test_untitled_save_needs_a_path():
    with pytest.raises(ValueError):
        MapDocument(Map()).save()


def test_read_only_file_refuses_save(tmp_path):
    path = tmp_path / "locked.map"
    MapDocument(Map()).save(path, compress=False)
    os.chmod(path, stat.S_IREAD)
    try:
        document = MapDocument.open(path)
        assert document.read_only
        with pytest.raises(ReadOnlyMapError):
            document.save()
        document.save(tmp_path / "copy.map")  # Save As still works
        assert not document.read_only
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


def test_archive_document_refuses_save_to_its_own_path(tmp_path):
    path = tmp_path / "packed.map"
    document = MapDocument(Map(), path, read_only=True)
    with pytest.raises(ReadOnlyMapError):
        document.save()


def test_atomic_write_replaces_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "file.bin"
    path.write_bytes(b"old")
    atomic_write(path, b"new")

    assert path.read_bytes() == b"new"
    assert [p.name for p in tmp_path.iterdir()] == ["file.bin"]


def test_atomic_write_failure_keeps_the_original(tmp_path):
    path = tmp_path / "file.bin"
    path.write_bytes(b"old")
    with pytest.raises(TypeError):
        atomic_write(path, "not bytes")  # type: ignore[arg-type]

    assert path.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["file.bin"]


def test_rotation_shifts_slots_and_drops_the_oldest(tmp_path):
    first, second, third = autosave_paths(tmp_path)
    first.write_bytes(b"1")
    second.write_bytes(b"2")
    third.write_bytes(b"3")

    assert rotate_autosaves(tmp_path) == first
    assert not first.exists()
    assert second.read_bytes() == b"1"
    assert third.read_bytes() == b"2"


def test_autosaver_saves_only_unsaved_changes_once(tmp_path):
    autosaver = Autosaver(tmp_path)
    document = MapDocument(Map())
    assert autosaver.save(document) is None  # clean

    edit(document)
    written = autosaver.save(document)
    assert written == autosave_paths(tmp_path)[0]
    assert autosaver.save(document) is None  # nothing new since

    edit(document, 2)
    autosaver.save(document)
    assert autosave_paths(tmp_path)[1].exists()


def test_autosave_disabled_and_interval_floor(tmp_path):
    document = MapDocument(Map())
    edit(document)
    assert Autosaver(tmp_path, AutosaveSettings(enabled=False)).save(document) is None
    assert AutosaveSettings(interval_seconds=10).interval_seconds == 60
