# sage_utils

Shared helpers reused by more than one SAGE front end. It has no CLI of its own - it is
the common foundation the other packages import.

Two layers:

- **Qt-free data layer** - `config` (settings), `sources` (loose ini folders and `.big`
  archives as a uniform source), `textures` (game texture lookup), `views` (resolution
  helpers over the `sage_ini` model), `refpack` (a pure-Python EA RefPack codec for the
  binary `.map`/`.bse` layer), the `factiongraph` ownership-graph types that
  [`sage_mods.edain`](../sage_mods.edain) assembles, and the `cli` / `skill` command plumbing.
- **Shared Qt pieces** - `styles`, `widgets` and `findings`, the desktop chrome shared by
  every SAGE front end ([`sage_ui`](../sage_ui), [`sage_wiki`](../sage_wiki), the SAGE Lint
  window and the Edain Linter). Notably:
  - `widgets.SourcesPanel` - the ordered, collapsible list of data sources.
  - `widgets.SourceLoader` - the one controller behind every "load these sources" flow:
    it persists the list, disables Load, reports progress to a status label and runs the
    build on a worker. Used with `sources.load_sources` to assemble a `Game`, and with
    `textures.TextureSource` to index image archives for portraits / button icons.
  - `findings.FindingsView` - the searchable, sortable, severity-coloured diagnostics table
    (with CSV export and double-click-to-open) both linters report into.

The data layer stays engine-generic; mod-specific names and paths live in the mod
packages (e.g. `sage_mods.edain`) and wire in through hooks. The Qt half needs the `ui` extra
installed.
