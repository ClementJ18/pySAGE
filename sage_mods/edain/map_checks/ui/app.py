"""PyQt6 desktop app that combines SAGE Lint's ini checks and the Edain map checks into one
"Edain Linter" window: a "Mod (ini)" tab and a "Maps" tab over a single shared game-data panel.
The window lives in `window.py`; the checks run in-process on a worker thread - the ini lint via
the sage_lint CLI, the map checks via `runner.run_check` (the same checks as `sage-edain
lint-maps`).

Run with `sage-edain-lint` (installed with the `edain-ui` extra) or
`python -m sage_mods.edain.map_checks.ui`.
"""

from sage_utils.extras import require_extra


def main() -> None:
    require_extra("edain-ui", "sage-edain-lint")
    # Imported after the check: both modules pull in PyQt6 at import time, which is exactly the
    # failure `require_extra` is here to report in plain language.
    from sage_mods.edain.map_checks.ui.window import (  # noqa: PLC0415
        APP_NAME,
        ICON_FILE,
        EdainLinterWindow,
    )
    from sage_utils.widgets import run_app  # noqa: PLC0415

    run_app(EdainLinterWindow, icon_file=ICON_FILE, anchor=__file__, app_name=APP_NAME)


if __name__ == "__main__":
    main()
