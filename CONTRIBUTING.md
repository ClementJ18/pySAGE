# Contributing

Contributions are welcome - bug reports, fixes, new checks and rules, format coverage, and
documentation all help.

## Getting set up

```sh
pip install -e .                 # + the extras for whatever you're touching
pip install pre-commit && pre-commit install
```

`pre-commit` runs the same gates as CI on every commit: Ruff lint (`ruff check`), Ruff
format (`ruff format`), Mypy typing coverage, and the fast core test suite. Run them by
hand any time with `pre-commit run --all-files`, or the pieces individually
(`ruff check .`, `ruff format .`, `mypy`, `pytest`). A pull request is expected to be green
on all four.

## Working in the codebase

Read **[CONVENTIONS.md](CONVENTIONS.md)** first - it's the short list of coding rules the
whole tree follows, and the fastest way to make a change that fits in. In particular:

- Match the style of the surrounding code - naming, comment density, and idiom. Every
  public module declares an `__all__`; keep new public surface intentional and documented.
- New behaviour needs tests. The core suite must stay data-free; corpus-dependent tests go
  behind the `full` marker (`pytest --full`).
- Keep the core packages engine-generic; mod-specific names and paths live in the mod's
  overlay package (e.g. `sage_edain`).
- Keep changes scoped to one subproject where you can; note in the PR which packages you
  touched and why.

## AI-assisted contributions

Using AI coding assistants (Claude Code, Copilot, and the like) is explicitly welcome - much
of this repo was built that way. The expectation is simply that **you have read,
understood, and can stand behind every line you submit**. You are the author of record: AI
output is a draft, not a warrant. Review it as critically as you would a stranger's patch,
verify it does what it claims (run it, not just the tests), and don't open a PR you couldn't
explain and defend in review. Accountability rests with the contributor, not the tool.
