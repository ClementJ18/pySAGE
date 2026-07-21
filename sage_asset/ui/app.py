"""PyQt6 desktop window for building and combining `asset.dat` files. Point it at an unpacked
art tree to build one from scratch, or combine a base with a mod overlay - the same two
operations `sage-asset build`/`combine` expose on the command line.

Run with `sage-asset-ui` (installed with the `asset-ui` extra) or `python -m sage_asset.ui`.
"""

from sage_utils.extras import require_extra


def main() -> None:
    require_extra("asset-ui", "sage-asset-ui")
    # Imported after the check: both modules pull in PyQt6 at import time, which is exactly the
    # failure `require_extra` is here to report in plain language.
    from sage_asset.ui.window import APP_NAME, ICON_FILE, AssetWindow  # noqa: PLC0415
    from sage_utils.widgets import run_app  # noqa: PLC0415

    run_app(AssetWindow, icon_file=ICON_FILE, anchor=__file__, app_name=APP_NAME)


if __name__ == "__main__":
    main()
