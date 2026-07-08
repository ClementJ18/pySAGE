# Conventions

The coding rules for pySAGE. They exist so the codebase reads as one hand — and so an
AI-assisted contribution is indistinguishable from a hand-written one. Follow them; if a
rule genuinely doesn't fit a case, say why in the PR rather than working around it silently.

The numbering is stable — code comments cite these rules by number (e.g. "CONVENTIONS.md
rule 4"), so don't renumber; append instead.

## 1. Public API & `__all__`

Every public module declares an `__all__`. What a package re-exports at its top level (and
lists in `__all__`) is its supported surface; everything else — and every `_`-prefixed
name — is internal and may change without notice. When you add something meant to be used
from outside the module, export it deliberately; don't let the surface grow by accident.
Semantic versioning applies to the exported surface only.

## 2. Comments

Plain comments only. No dashed or boxed section headers (`# ---- foo ----`, divider lines);
use an ordinary comment or a blank line. Comments explain *why*, not *what* the code already
says. Do not reference the project's own history in comments — old names, past refactors,
"used to be…" — that belongs in git and the roadmap, not the source. A comment should read
correctly to someone seeing the file for the first time.

## 3. Imports & exceptions

All imports live at module top level — no function-local imports (Ruff `PLC0415`). The one
sanctioned exception is a genuinely optional dependency behind an extra, imported lazily
inside the function that needs it, with a clear message on `ImportError` pointing at the
extra to install. Never write a bare `except:` (`E722`) or a blind `except Exception:` that
swallows errors (`BLE`); catch the specific exception you can handle.

## 4. Losslessness & error recovery

Parsing round-trips: `parse` → `print_document` reproduces the input byte-for-byte, comments
and layout included. Malformed input must **never** raise — the parser emits a `Diagnostic`
and recovers to keep going, so one bad block never sinks a file. Tools report problems as
diagnostics with source spans; they don't crash on data they don't understand.

## 5. Typing

Everything is fully annotated and passes `mypy` (each shipped package carries a `py.typed`
marker). Model fields take their converted type through the `Annotated` aliases in the
schema rather than ad-hoc casts at the call site. Prefer precise types over `Any`; if a type
is genuinely dynamic, make that explicit.

## 6. Generic core, mod overlays

The core (`sage_ini`, `sage_map`, `sage_utils`, `sage_ui`, `sage_lint`) stays engine-generic:
no mod-specific names, paths, or assumptions. Anything specific to a mod lives in that mod's
package — Edain content in `sage_edain` — and wires into the generic core through hooks, never
by reaching back into it. If you find yourself hard-coding an Edain name in a core package,
it belongs in the overlay instead.

## 7. Tests

New behaviour comes with tests. The core suite is **data-free** and fast: a bare `pytest`
must stay sub-second and depend on no game corpus. Tests that need real game data are marked
`full` (the corpus acceptance gates and peripheral-package suites) and run only under
`pytest --full`; a corpus test skips — never fails — when no corpus root is present.

## 8. Formatting & the green-build gate

Ruff owns formatting and lint (line length 100, target `py313`); `ruff format` is the
arbiter of style, so don't hand-format against it. `pre-commit` runs Ruff lint, Ruff format,
mypy, and the core test suite — the same four gates as CI. A change is done when all four are
green.
