"""Guards for the declared public API: that every name in an `__all__` actually resolves,
that the top-level facade and `py.typed` marker are in place, and that the headline
entry points stay importable from `sage_ini`."""

import importlib
from pathlib import Path

import pytest

import sage_ini

# Modules that declare a curated public surface. Each must keep `__all__` honest (every
# listed name resolvable) so a consumer can rely on it and `import *` stays clean.
_PUBLIC_MODULES = [
    "sage_ini",
    "sage_ini.loader",
    "sage_ini.walk",
    "sage_ini.suggest",
    "sage_ini.strings",
    "sage_ini.stats",
    "sage_ini.model",
    "sage_ini.model.game",
    "sage_ini.model.objects",
    "sage_ini.model.xref",
    "sage_ini.parser",
    "sage_ini.parser.ast",
    "sage_ini.parser.blockparser",
    "sage_ini.parser.diagnostics",
    "sage_ini.parser.location",
    "sage_ini.parser.printer",
    "sage_ini.parser.io",
]

# The headline names a consumer should be able to import straight from the package.
_TOP_LEVEL_EXPORTS = [
    "load_game",
    "load_map",
    "Game",
    "IniObject",
    "Xref",
    "parse",
    "parse_file",
    "print_document",
    "walk_objects",
    "walk_blocks",
    "walk_nodes",
    "Diagnostic",
    "Diagnostics",
    "Severity",
    "Span",
]


@pytest.mark.parametrize("module_name", _PUBLIC_MODULES)
def test_all_names_resolve(module_name):
    module = importlib.import_module(module_name)
    assert hasattr(module, "__all__"), f"{module_name} declares no __all__"
    missing = [name for name in module.__all__ if not hasattr(module, name)]
    assert not missing, f"{module_name}.__all__ names nothing for: {missing}"


@pytest.mark.parametrize("module_name", _PUBLIC_MODULES)
def test_all_entries_are_unique(module_name):
    names = importlib.import_module(module_name).__all__
    assert len(names) == len(set(names)), f"{module_name}.__all__ has duplicates"


@pytest.mark.parametrize("name", _TOP_LEVEL_EXPORTS)
def test_headline_names_are_exported_and_importable(name):
    assert name in sage_ini.__all__, f"{name} is missing from sage_ini.__all__"
    assert hasattr(sage_ini, name)


def test_py_typed_marker_is_shipped():
    # PEP 561: the marker must sit beside the package so a consumer's type checker reads the
    # library's annotations.
    marker = Path(sage_ini.__file__).parent / "py.typed"
    assert marker.is_file()


def test_version_is_exposed():
    assert isinstance(sage_ini.__version__, str)
    assert "__version__" in sage_ini.__all__
