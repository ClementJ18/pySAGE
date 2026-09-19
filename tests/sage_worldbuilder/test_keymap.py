"""The shipped WorldBuilder keymap, and that it still matches the exe it was extracted from."""

from pathlib import Path

import pytest

from sage_worldbuilder.keymap import accelerators, shortcuts_for

REPO_ROOT = Path(__file__).resolve().parents[2]
UNDO, REDO, SAVE = 57643, 57644, 57603


def test_worldbuilder_basics_are_present():
    assert set(shortcuts_for(UNDO)) == {"Ctrl+Z", "Alt+Backspace"}
    assert set(shortcuts_for(REDO)) == {"Ctrl+Y", "Ctrl+Shift+Z"}
    assert shortcuts_for(SAVE) == ["Ctrl+S"]
    assert shortcuts_for(1) == []


def test_every_row_is_well_formed():
    rows = accelerators()
    assert len(rows) == 65  # the table's full length
    assert len({(row.keys, row.command) for row in rows}) == len(rows)
    for row in rows:
        assert row.keys and not row.keys.endswith("+")
        assert row.command > 0


@pytest.mark.full
def test_keymap_matches_the_exe():
    exe = REPO_ROOT / "worldbuilder.exe"
    if not exe.is_file():
        pytest.skip("worldbuilder.exe is not in the checkout")
    tool = pytest.importorskip("tools.extract_worldbuilder_keymap")

    shipped = (REPO_ROOT / "sage_worldbuilder" / "keymap.json").read_text(encoding="utf-8")
    assert tool.render_keymap(tool.extract_keymap(exe)) == shipped
