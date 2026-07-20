"""PyQt6 desktop UI to browse SAGE objects: load data sources, search for an object,
and see its stats. The entry point; the UI is split across `browser.py` (main window),
`unit_panel.py` (stat view), `registry.py` (game-folder lookup) and `layout.py`.

Run with `sage-ui` (installed with the `ui` extra) or `python -m sage_ui.app`.
"""

from sage_utils.extras import require_extra


def main() -> None:
    require_extra("ui", "sage-ui")
    # Imported after the check: both modules pull in PyQt6 at import time, which is exactly the
    # failure `require_extra` is here to report in plain language.
    from sage_ui.browser import ICON_FILE, Browser  # noqa: PLC0415
    from sage_utils.widgets import run_app  # noqa: PLC0415

    run_app(Browser, icon_file=ICON_FILE, anchor=__file__)


if __name__ == "__main__":
    main()
