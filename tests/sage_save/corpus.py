"""Fixture-save discovery shared by the sage_save test modules.

Saves live in `fixtures/` and in per-play-session subfolders (`fixtures/session1/...`);
discovery is recursive, so promoting a new session save into the tree enrols it in every
corpus-wide test automatically. Test ids are built from the path relative to `fixtures/`
rather than the bare stem, because stems repeat across sessions ("Saved Game 3" exists at
the top level and in session3)."""

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAVE_SUFFIXES = {".BfME2Skirmish", ".BfME2Campaign"}

ALL_SAVES = sorted(p for p in FIXTURES.rglob("*") if p.suffix in SAVE_SUFFIXES)
ALL_SKIRMISH = sorted(FIXTURES.rglob("*.BfME2Skirmish"))

# A skirmish save in which a create-a-hero ("Berethor") was selected and recruited. It is the
# only fixture that populates the GameState `hero_name` string, and it carries the recruited hero
# as a live `CreateAHero` object — so it pins both the header layout (an otherwise-empty hero-name
# string sits before the profile name) and the create-a-hero object template. Auto-discovered into
# the corpus-wide tests above; named here for the checks specific to create-a-hero.
CAH_SKIRMISH = FIXTURES / "Saved Game 4 cah.BfME2Skirmish"

# War-of-the-Ring saves (Edain). Deliberately excluded from the auto-discovered corpus above: this
# mode/mod diverges from the BFME2 invariants those corpus-wide tests assert (localized template
# names, different per-chunk contents, objectless strategic layers). Exercised in test_wotr.py.
_EDAIN = FIXTURES / "edain"
_WOTR = FIXTURES / "wotr"

# Battle saves: a full in-battle snapshot — an embedded map and a live object/drawable index.
WOTR_BATTLE = sorted([_EDAIN / "ang 5.BfME2WotR", _WOTR / "Saved Game 4.BfME2WotR"])

# Living-world (strategic-layer) saves: valid and loadable, but *objectless by nature* — no
# embedded battle map and no live objects (the strategic state rides in LivingWorldLogic). These
# are the counter-examples proving "no map + no objects" is normal, not a corruption signal.
WOTR_LIVING_WORLD = sorted(_WOTR / f"Saved Game {n}.BfME2WotR" for n in (2, 3, 5, 6, 7))

# angmar 6 is reported corrupt by the game, yet is structurally an ordinary objectless living-world
# save: it parses, re-encodes byte-exactly, and differs from the valid ones only in content/size.
# The tooling cannot distinguish it — kept for the record, not asserted loadable or fatal.
WOTR_GAME_CORRUPT = _EDAIN / "angmar 6.BfME2WotR"

# angmar 7 is an interrupted write (first chunk end-offset never back-patched, no terminator): the
# container itself will not parse — the one WotR corruption the tooling *can* detect.
WOTR_TRUNCATED = _EDAIN / "angmar 7.BfME2WotR"

# Every WotR save whose container parses (all but the truncated one).
WOTR_PARSEABLE = sorted([*WOTR_BATTLE, *WOTR_LIVING_WORLD, WOTR_GAME_CORRUPT])


def fixture_id(path: Path) -> str:
    """A unique, readable pytest id for a fixture save."""
    return path.relative_to(FIXTURES).with_suffix("").as_posix().replace(" ", "_")
