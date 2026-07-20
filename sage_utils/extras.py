"""Turning a missing optional extra into a clear instruction instead of a traceback.

The desktop entry points (`sage-ui`, `sage-wiki`, `sage-lint-ui`, `sage-edain-lint`) are declared
in `[project.gui-scripts]`, so pip installs all four whatever extras were selected. Running one
without its extra therefore reaches a real, working script that dies on `import PyQt6` - a raw
`ModuleNotFoundError` that says nothing about what to install. These helpers check first and
exit with the exact pip command instead.

Kept Qt-free and dependency-free, and deliberately using `find_spec` rather than a `try: import`,
so the check itself never drags Qt into a process that only wants the core library.
"""

import importlib.util

# The PyPI distribution name (not the project name, pySAGE) - spelled with the hyphen, since the
# unhyphenated `pysage` is a different, unrelated project. Messages that name it must keep the
# hyphen or they point users at the wrong package.
DISTRIBUTION = "py-sage"


def missing_modules(*modules: str) -> list[str]:
    """Which of `modules` cannot be imported, without importing any of them."""
    return [name for name in modules if importlib.util.find_spec(name) is None]


def require_extra(extra: str, command: str, *modules: str) -> None:
    """Exit with an install instruction when `command` cannot run for want of `extra`.

    `modules` are the top-level imports the extra provides (defaulting to PyQt6, which every
    desktop app needs). Raises `SystemExit` with a message on stderr rather than returning a
    status, so callers stay one line and the exit code is a conventional 1."""
    missing = missing_modules(*(modules or ("PyQt6",)))
    if not missing:
        return
    raise SystemExit(
        f"{command}: missing {', '.join(missing)}.\n"
        f"This app ships with the '{extra}' extra, which was not installed.\n\n"
        f'    pip install "{DISTRIBUTION}[{extra}]"\n'
    )
