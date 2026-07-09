# sage_ui

A PyQt6 desktop browser for SAGE game data. Load one or more data sources (loose ini
folders or `.big` archives), search for an object, and see its resolved stats - the
graphical counterpart to `sage-ini`'s query commands.

The UI is split across `browser.py` (the main window), `unit_panel.py` (the stat view),
`registry.py` (game-folder lookup) and `layout.py`, and reuses the shared Qt and data
helpers in [`sage_utils`](../sage_utils).

## Running

Needs the `ui` extra (PyQt6, pyBIG, Pillow):

```sh
pip install -e ".[ui]"
sage-ui              # or: python -m sage_ui.app
```
