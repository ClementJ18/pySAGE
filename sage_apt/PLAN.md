# sage_apt — implementation plan for TODO.md

Ordered so that every later phase is protected by the guardrails built in the earlier
ones. Each phase ends with its quality gate; a phase is not done until its gate passes.

**Global gates (every phase):**

- `ruff check` + `ruff format --check` clean on `sage_apt` and `tests/sage_apt`.
- `pytest tests/sage_apt` green; full suite (`pytest tests`) unbroken.
- Corpus gate (built in Phase 0) green: every Edain `.apt`/`.const` pair round-trips
  `apt -> xml -> apt -> xml` with identical XML.
- `TODO.md` updated: finished items move to its "fixed" ledger with a one-line note.

---

## Phase 0 — Corpus gate + `sage-apt check` (S)

The batch validator is both the missing CLI feature and the regression net every
following phase needs, so it comes first.

1. Add `check` subcommand: for each `.apt` (file or directory argument), decompile,
   recompile, re-decompile in a temp dir; report `ok` / `unstable` / `error` per file,
   exit non-zero on any failure. `--json` like the other CLIs.
2. Add `tests/sage_apt/test_corpus.py` marked `full`, following the existing
   corpus-gate pattern: derive the apt dirs (`_mod/apt`, `_mod/apt_widescreen`) from
   the `edain=` root in `tests/corpus_roots.txt`; skip cleanly when absent.
3. Wire the corpus test through the `check` machinery so the CLI and the gate cannot
   drift apart.

**Gate:** `python -m sage_apt check <edain apt dirs>` reports 17/17 ok;
`pytest tests/sage_apt --full` green.

## Phase 1 — Error model + atomic writes (S/M)

Foundation for everything user-facing; do it before behavior changes pile up.

1. Introduce `AptError(Exception)` in `aptfile.py`; replace every `print(...) +
   return False` with a raise carrying the file and reason.
2. Make `xml_to_apt` atomic: refactor `_generate_apt_file` to build and return the
   buffer (no I/O), build the `.const` buffer likewise, and only then write both
   files — no more partial `.apt` next to a stale `.const` on failure.
3. Public API: `apt_to_xml` / `xml_to_apt` raise on failure and return the written
   path(s). Update `__main__.py` (catch `AptError` → message + exit 1), the editor's
   `/api/convert` (catch → JSON error), README, and tests.

**Gate:** new unit tests for missing input, missing `.const`, malformed XML, and
failure-leaves-no-partial-output; corpus gate green.

## Phase 2 — Bytecode opcode fixes (S)

Fix the two replicated C++ bugs. No corpus file uses either opcode, so the tests are
synthetic.

1. `pushregister` (0xB9): decompiler must emit the register byte, not the opcode.
   Confirm the one-byte operand against OpenSAGE's ActionScript reader first
   (reference only, per repo policy).
2. `pushwordconstant` (0xA3): drop the fall-through that fabricates an extra
   `pushshort` and consumes 2 phantom bytes; confirm single-u16 operand the same way.
3. Hand-craft action byte sequences for both opcodes in tests: bytes → XML → bytes
   must be identity, and the XML must carry the true operand values.
4. Document the divergence from the original C++ AptConverter in `actions.py` where
   the "replicate the bug" comments currently sit.

**Gate:** synthetic byte-level round-trip tests pass; corpus gate green (proves no
regression on real files).

## Phase 3 — Recompute `definefunction[2]` body sizes (M)

First half of making the bytecode actually editable.

1. In `ActionBytes.add_definefunction[2]_action`, record the byte offset of the
   `size` field (alongside the existing argument-pointer bookkeeping).
2. In `xml_process_actions`, measure `actionbytecount` before/after emitting the
   `<body>` and patch the recorded size field; the XML `size` attribute becomes
   advisory (still emitted by the decompiler for stability, ignored by the compiler).
   Nested functions work by recursion.
3. Test: take the SpellStore XML, inject a `<trace/>` into a function body,
   recompile, re-decompile — the edit must survive and the body must stay correctly
   scoped (nothing after the function is lost).

**Gate:** the edited-body test passes; corpus gate green (recomputed sizes must equal
the original sizes on unedited files — assert exactly that inside the corpus check).

## Phase 4 — Label-based branches (M/L, has a design decision)

Second half: raw byte offsets in `branchalways`/`branchiftrue`/`branchiffalse` go
stale the moment a body's byte count changes.

1. **Decide the representation** (recommendation: targets-with-fallback). Decompiler
   computes each branch's destination instruction, gives it a stable label id, and
   emits `target="L3"` alongside the legacy `offset`. Compiler prefers `target`
   (two-pass: emit with placeholders, resolve after layout, alignment handled by the
   normal emit path) and falls back to `offset` when no target is present, so
   pre-existing XML files still compile.
2. Regenerate expectations: decompiled XML gains attributes, so the corpus stability
   check compares the new form against itself (gen1 vs gen2), unchanged in spirit.
3. Tests: a synthetic function with forward and backward branches; edit an
   instruction between branch and target; recompile; verify the re-read offsets moved
   by exactly the size delta.

**Gate:** on every unedited corpus file the assembler reproduces the *original*
binary branch offsets exactly; branchy-edit test passes; corpus gate green.

## Milestone gate M1 — in-game validation (manual, after Phases 1–4)

The one thing no automated gate covers: does the game accept our exports?

1. Round-trip `SpellStore.apt` untouched; install into the mod; confirm the spellbook
   store renders and its buttons click.
2. Make one visible edit in the editor (move an element, change a text), export,
   confirm the edit appears in-game and nothing else broke.
3. Record the result in TODO.md; if the game rejects the file, byte-diff against the
   original layout before proceeding — **Phases 5+ that touch the writer are blocked
   until M1 passes.**

## Phase 5 — BIG-archive sources (M)

Covers the mod files with no loose `.const` (`LoadScreen.apt`, ...).

1. Add an `apt` optional-dependency extra (`pybig`), lazy-imported behind the same
   pattern `sage_utils.sources` uses; the core stays stdlib-only.
2. Resolution order mirroring the game: loose file beside the `.apt` first, then
   `.const` (or the `.apt` itself) fished out of the `.big`s of a `--game-dir`.
3. Tests build a tiny `.big` in-memory with pybig containing a fixture pair;
   `to-xml` resolves through it. Skip-marked when the extra isn't installed.

**Gate:** `sage-apt to-xml` works on a `.apt` whose `.const` only exists inside a
`.big`; corpus + suite green with and without the extra installed.

## Phase 6 — Viewer / editor track (parallelizable after Phase 1)

Ordered small-to-large; each item is independently shippable.

1. **poflags honesty (S):** only add `HasMatrix` / `HasColorTransform` on apply when
   the matrix / colour fields actually changed. Gate: manual editor pass + the
   JS-visible behavior documented in the panel.
2. **Extract the editor page (S):** move `EDITOR_HTML` to `sage_apt/assets/editor.html`
   (loaded via `importlib.resources`), add the `package-data` entry, drop the E501
   per-file ignore for `editor.py`. Gate: existing editor smoke test (serve on a free
   port, fetch `/`, `/api/xml`, POST `/api/convert`) turned into a real unit test.
3. **Frame/label selection (M):** `view --label X` / `--frame N`, and a per-sprite
   label dropdown in the editor toolbar that re-renders the stage. Gate: viewer HTML
   for `_off` vs `_on` differs where labels differ; corpus files render without error
   for every label they declare.
4. **Real textures (M/L):** investigation step first — map `image` character ids to
   texture files via the game's aptimages mapping; then serve decoded PNGs from the
   editor (`/api/texture/<id>`) and inline data-URIs in the static viewer, via
   `sage_utils.textures` behind the `[ui]`/`[apt]` extras with graceful placeholder
   fallback. Gate: SpellStore preview shows actual artwork; without the extras the
   current placeholder rendering is unchanged.
5. **Editing depth (L):** add/delete/duplicate placeobjects, drag-to-move on the
   stage (pointer delta → tx/ty), undo/redo stack. Gate: each operation covered by an
   API-level test where the server is involved, manual checklist for the pure-JS
   parts, and an in-game spot check (M1 procedure) after the first release of this
   item.

## Phase 7 — Typed model + mypy (L, last)

Pure refactor; only safe once the behavior above is pinned by tests.

1. Golden capture first: check in (or generate in-test) the current XML and binary
   outputs for the fixture so the refactor is diffed against frozen bytes.
2. Refactor the reader to dataclasses (`AptMovie`, `Sprite`, `Button`,
   `PlaceObject`, ...) over `sage_utils.stream.BinaryStream`; XML output must be
   byte-identical to the golden.
3. Refactor the writer onto the same model; binary output byte-identical to golden.
4. Annotate `viewer.py` / `editor.py` / `__main__.py`; add `sage_apt` to the mypy
   `files` list; add `py.typed`.

**Gate:** golden diffs empty, mypy clean, corpus + full suite green.

## Deliberately deferred (decide when relevant)

- **edittext colour byte-swap in the XML**: keep mirroring the raw layout (existing
  XMLs stay valid; the editor already warns). Revisit only if the editor grows a
  colour picker for edittexts.
- **Naming the unknown fields** (movie `unknown=33`, button `unknown2`, text record
  `u1..u4`): documentation pass against OpenSAGE when convenient; renames are
  XML-breaking, so fold them into Phase 7 if done at all.
- **Nested `MOVIE` characters**: no corpus occurrence; leave as `<empty>` until a
  real file demands otherwise.
