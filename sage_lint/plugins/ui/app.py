"""PyQt6 desktop window over `sage_lint lint`, for teammates who would rather not use the
command line. Point it at a mod folder, set a few options, press Check, and browse the
errors and warnings in a searchable, sortable table. The window lives in `window.py`; the
lint runs the CLI in-process (see `runner.py`).

Run with `sage-lint-ui` (installed with the `lint-ui` extra) or
`python -m sage_lint.plugins.ui`.
"""

from sage_utils.extras import require_extra


def main() -> None:
    require_extra("lint-ui", "sage-lint-ui")
    # Imported after the check: both modules pull in PyQt6 at import time, which is exactly the
    # failure `require_extra` is here to report in plain language.
    from sage_lint.plugins.ui.window import APP_NAME, ICON_FILE, LintWindow  # noqa: PLC0415
    from sage_utils.widgets import run_app  # noqa: PLC0415

    run_app(LintWindow, icon_file=ICON_FILE, anchor=__file__, app_name=APP_NAME)


if __name__ == "__main__":
    main()
