"""The `sage-wiki` entry point, kept separate from `app.py` so the extras check runs first.

`app.py` builds its `QMainWindow` subclass at module scope, so it must import PyQt6 at module
scope too - there is no point inside it where a guard could run *before* that import. The console
script therefore points here instead: this module stays import-light, checks the extra, and only
then pulls `app` in. The other three desktop apps are thin enough to do the same check inline in
their own `main()`.
"""

from sage_utils.extras import require_extra


def main() -> None:
    require_extra("wiki", "sage-wiki", "PyQt6", "mwclient", "mwparserfromhell", "keyring")
    from sage_wiki.app import main as run_app_window  # noqa: PLC0415 - after the extra check

    run_app_window()


if __name__ == "__main__":
    main()
