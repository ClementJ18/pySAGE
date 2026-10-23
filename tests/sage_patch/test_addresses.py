"""Checks on the `sage_patch.addresses` package as a whole."""

from __future__ import annotations

import importlib
import pkgutil

import sage_patch.addresses as addresses


def test_no_name_means_two_addresses() -> None:
    """The package re-exports every submodule with `import *`, so a name two submodules define
    resolves to whichever is imported last - silently. That is how `ui.py`'s `GET_FINAL_OVERRIDE
    = 0x00465AF4` once retargeted every patch calling `player.py`'s `0x00688D3C`, and only a
    stale anchor noticed. A name may be repeated with the same value, never with another."""
    seen: dict[str, dict[object, list[str]]] = {}
    for info in pkgutil.iter_modules(addresses.__path__):
        module = importlib.import_module(f"{addresses.__name__}.{info.name}")
        for name in getattr(module, "__all__", ()):
            value = getattr(module, name)
            if isinstance(value, int):
                seen.setdefault(name, {}).setdefault(value, []).append(info.name)
    clashes = {
        name: {f"0x{value:08x}": modules for value, modules in values.items()}
        for name, values in seen.items()
        if len(values) > 1
    }
    assert not clashes, f"names defined with different values in different modules: {clashes}"
