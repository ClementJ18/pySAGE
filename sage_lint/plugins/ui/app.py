"""PyQt6 desktop window over `sage_lint lint`, for teammates who would rather not use the
command line. Point it at a mod folder, set a few options, press Check, and browse the
errors and warnings in a searchable, sortable table. The window lives in `window.py`; the
lint runs the CLI in-process (see `runner.py`).

Run with `sage-lint-ui` (installed with the `lint-ui` extra) or
`python -m sage_lint.plugins.ui`.
"""

from sage_lint.plugins.ui.window import APP_NAME, ICON_FILE, LintWindow
from sage_utils.widgets import run_app


def main() -> None:
    run_app(LintWindow, icon_file=ICON_FILE, anchor=__file__, app_name=APP_NAME)


if __name__ == "__main__":
    main()
