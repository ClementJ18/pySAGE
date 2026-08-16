"""PyQt6 desktop app for laying out a horde's formation: click the soldiers onto a grid and the
`HordeContain` block - slot count, payload, banner carrier and the numbered `RankInfo` ranks -
is written for you; paste a block back to see the shape it describes. The window lives in
`window.py`; the model itself is the Qt-free `sage_mods.edain.horde_maker`.

Run with `sage-edain-horde` (installed with the `edain-ui` extra) or
`python -m sage_mods.edain.horde_maker.ui`.
"""

from sage_utils.extras import require_extra


def main() -> None:
    require_extra("edain-ui", "sage-edain-horde")
    # Imported after the check: both modules pull in PyQt6 at import time, which is exactly the
    # failure `require_extra` is here to report in plain language.
    from sage_mods.edain.horde_maker.ui.window import (  # noqa: PLC0415
        APP_NAME,
        HordeMakerWindow,
    )
    from sage_utils.widgets import run_app  # noqa: PLC0415

    run_app(HordeMakerWindow, app_name=APP_NAME)


if __name__ == "__main__":
    main()
