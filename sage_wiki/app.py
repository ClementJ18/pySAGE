"""The `sage-wiki` desktop app (installed with the `wiki` extra), also `python -m sage_wiki.app`.

Checks the extra before importing the window, which pulls in PyQt6 at import time.
"""

from sage_utils.extras import require_extra


def main() -> None:
    require_extra("wiki", "sage-wiki", "PyQt6", "mwclient", "mwparserfromhell", "keyring")
    from sage_utils.widgets import run_app  # noqa: PLC0415
    from sage_wiki.window import APP_TITLE, ICON_FILE, WikiUpdater  # noqa: PLC0415

    run_app(WikiUpdater, icon_file=ICON_FILE, anchor=__file__, app_name=APP_TITLE)


if __name__ == "__main__":
    main()
