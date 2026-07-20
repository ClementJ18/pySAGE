"""Unit tests for the `.big` entry-path helpers in `sage_utils.sources`.

Free of pyBIG and of any on-disk archive, so they run in the core suite on every platform: the
behaviour they pin is platform-dependent, and the archive-backed tests that also cover it are
`full`-marked (they need the optional pyBIG extra), so they skip on a bare install."""

from pathlib import PurePosixPath

from sage_ini.parser.io import ASSET_SUFFIXES
from sage_utils.sources import big_entry_basename


def test_windows_entry_path_splits_off_windows():
    """A .big stores entry paths Windows-style; the basename must split on the backslash even on
    POSIX, where a backslash is an ordinary character and `Path(name).name` would not split it."""
    assert big_entry_basename(r"art\HeroUI_001.dds") == "heroui_001.dds"
    assert big_entry_basename(r"art\compiledtextures\hu\HeroUI_001.dds") == "heroui_001.dds"


def test_forward_slashes_and_bare_names_also_split():
    assert big_entry_basename("art/HeroUI_001.dds") == "heroui_001.dds"
    assert big_entry_basename("HeroUI_001.dds") == "heroui_001.dds"


def test_suffix_of_a_windows_entry_is_recoverable():
    """The suffix filters in `extract_big` / `big_member_basenames` run on the split basename, so
    a dotted *directory* cannot be mistaken for the file's extension."""
    assert PurePosixPath(big_entry_basename(r"art\v1.2\tex.dds")).suffix in ASSET_SUFFIXES
    assert PurePosixPath(big_entry_basename(r"art\v1.2\readme")).suffix not in ASSET_SUFFIXES
