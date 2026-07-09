# sage_utils

Shared helpers reused by more than one SAGE front end. It has no CLI of its own - it is
the common foundation the other packages import.

Two layers:

- **Qt-free data layer** - `config` (settings), `sources` (loose ini folders and `.big`
  archives as a uniform source), `textures` (game texture lookup), `views` (resolution
  helpers over the `sage_ini` model), the `factiongraph` ownership-graph types that
  [`sage_edain`](../sage_edain) assembles, and the `cli` / `skill` command plumbing.
- **Shared Qt pieces** - `styles` and `widgets`, the desktop chrome shared by
  [`sage_ui`](../sage_ui) and [`sage_wiki`](../sage_wiki).

The data layer stays engine-generic; mod-specific names and paths live in the mod
packages (e.g. `sage_edain`) and wire in through hooks. The Qt half needs the `ui` extra
installed.
