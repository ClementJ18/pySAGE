"""PyQt6 desktop app that turns the Edain patch-notes spreadsheet into the two BBcode forum
posts: pick the CSV export, tick beta / added-since, and get the English and German posts
previewed side by side and written next to the sheet. The window lives in `window.py`; the
transform itself is the Qt-free `sage_mods.edain.patch_notes`.

Run with `sage-edain-notes` (installed with the `edain-ui` extra) or
`python -m sage_mods.edain.patch_notes.ui`.
"""

from sage_utils.extras import require_extra


def main() -> None:
    require_extra("edain-ui", "sage-edain-notes")
    # Imported after the check: both modules pull in PyQt6 at import time, which is exactly the
    # failure `require_extra` is here to report in plain language.
    from sage_mods.edain.patch_notes.ui.window import (  # noqa: PLC0415
        APP_NAME,
        ICON_FILE,
        PatchNotesWindow,
    )
    from sage_utils.widgets import run_app  # noqa: PLC0415

    run_app(PatchNotesWindow, icon_file=ICON_FILE, anchor=__file__, app_name=APP_NAME)


if __name__ == "__main__":
    main()
