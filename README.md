# pySAGE

A collection of Python tools for reading, editing, linting and visualising the data
formats of the **SAGE engine** - the engine behind *Command & Conquer: Generals* and
*The Battle for Middle-earth*. It grew out of an ini parser and now spans ini game data,
binary maps, replays, and UI, with a domain overlay for the Edain mod.

Everything installs as one package with optional extras (see [Install](#install)). Each
subproject has its own README with the details; this page is the map.

## Projects

### Ini game data

| Project | What it is |
| --- | --- |
| [`sage_ini`](sage_ini/README.md) | The foundation: a typed, comment-preserving `.ini` parser, a whole-game loader, the cross-reference graph, and a lossless AST. Everything else builds on it. |
| [`sage_lint`](sage_lint/README.md) | Formatter and linter over `sage_ini` - canonical reprint plus judgment rules (dangling references, out-of-range values, duplicates, unused definitions) and meta-analysis. |

### Binary formats

| Project | What it is |
| --- | --- |
| [`sage_map`](sage_map/README.md) | Reader/writer for BFME `.map` files, plus a game-aware overlay that resolves script arguments and object references and lints maps. |
| [`sage_replay`](sage_replay/README.md) | Reader for SAGE replay files (Generals `.rep`, BFME / BFME2 / RotWK) - the recorded order stream, decoded into build orders, APM and command timing. |
| [`sage_apt`](sage_apt/README.md) | Converter, viewer and editor for `.apt` UI movies (the Flash-derived format behind BFME's menus and HUD). |

### Domain overlays & apps

| Project | What it is |
| --- | --- |
| [`sage_edain`](sage_edain/README.md) | Edain-mod overlay: builds a faction ownership graph (spellbook → base → structures → units/heroes/upgrades) and renders, diffs or serves it. |
| [`sage_wiki`](sage_wiki/README.md) | Desktop tool that updates Edain wiki infoboxes from parsed game data through the MediaWiki API. |
| [`sage_ui`](sage_ui/README.md) | PyQt6 desktop browser for SAGE game data: load sources, search an object, see its resolved stats. |

### Shared

| Project | What it is |
| --- | --- |
| [`sage_utils`](sage_utils/README.md) | Helpers shared by more than one front end: the Qt-free data layer (sources, textures, views, the faction-graph types) and the shared Qt chrome. |

## Install

```sh
pip install -e .            # core library + linter (Python ≥ 3.13)
pip install -e ".[ui]"      # + the PyQt6 desktop apps (sage-ui)
pip install -e ".[wiki]"    # + the wiki updater
pip install -e ".[edain]"   # + Edain base-layout decompilation
pip install -e ".[apt]"     # + reading .const/.apt out of .big archives
```

The extras (`ui`, `lint-ui`, `wiki`, `map`, `edain`, `apt`) pull in the optional
dependencies each peripheral tool needs; the core parser and linter stay dependency-free.
Console scripts are installed for the CLI tools: `sage-ini`, `sage-lint`, `sage-edain`,
`sage-replay`, `sage-apt` (and the GUI scripts `sage-ui`, `sage-wiki`, `sage-lint-ui`).

## Tests

```sh
pytest            # fast, data-free core suite
pytest --full     # + corpus acceptance gates and peripheral-package suites
```

## Contributing

Contributions are welcome - bug reports, fixes, new checks and rules, format coverage, and
documentation all help. See **[CONTRIBUTING.md](CONTRIBUTING.md)** to get set up and
**[CONVENTIONS.md](CONVENTIONS.md)** for the coding rules. AI-assisted contributions are
welcome too, with one expectation: you have read, understood, and can stand behind every
line you submit.
