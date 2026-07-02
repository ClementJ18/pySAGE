"""PyQt6 desktop UI to browse SAGE objects: load data sources, search for an object,
and see its stats. The entry point; the UI is split across `browser.py` (main window),
`unit_panel.py` (stat view), `registry.py` (game-folder lookup) and `layout.py`.

Run with `sage-ui` (installed with the `ui` extra) or `python -m sage_ui.app`.
"""

from sage_ui.browser import ICON_FILE, Browser
from sage_utils.widgets import run_app


def main() -> None:
    run_app(Browser, icon_file=ICON_FILE, anchor=__file__)


if __name__ == "__main__":
    main()
