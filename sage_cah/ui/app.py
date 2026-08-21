"""PyQt6 desktop editor for a BFME2 / RotWK Create-a-Hero `.cah` file: open a hero, edit its
identity, class, colours, powers and bling, and save it with the checksum the game validates.
Loading a game's data is optional and adds completion over its real classes, powers and bling
choices.

Run with `sage-cah-ui` (installed with the `cah-ui` extra) or `python -m sage_cah.ui`.
"""

from sage_utils.extras import require_extra


def main() -> None:
    require_extra("cah-ui", "sage-cah-ui")
    # Imported after the check: both modules pull in PyQt6 at import time, which is exactly the
    # failure `require_extra` is here to report in plain language.
    from sage_cah.ui.window import APP_NAME, ICON_FILE, CahWindow  # noqa: PLC0415
    from sage_utils.widgets import run_app  # noqa: PLC0415

    run_app(CahWindow, icon_file=ICON_FILE, anchor=__file__, app_name=APP_NAME)


if __name__ == "__main__":
    main()
