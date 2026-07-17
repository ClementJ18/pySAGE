---
name: bfme-faction
description: >-
  Visualise and critique a Battle for Middle-earth / Edain faction - its spellbook, base and
  start options, structures, and the units / heroes / upgrades they produce, with per-unit stats
  (cost, health, attack, resilience). Use when asked to review, critique, summarise, balance, or
  write up a faction (or compare factions) in a BFME/SAGE mod tree. Backed by the `sage_mods.edain`
  ownership-graph model via the `sage-edain` CLI.
---

# BFME / Edain faction reviewer

`sage-edain` walks a loaded mod into one **faction ownership graph**: the explicit link between a
faction and everything a player of it can field - its spellbook powers, the start-point flags that
unpack its base, the structures placed in that base, and the units, heroes and upgrades those
structures produce. The `report` command renders that graph as a Markdown digest built for you to
read top-to-bottom and reason over. It is the source of truth for *what a faction has* - read the
roster from it, don't guess.

## The endpoint: `sage-edain report`

`sage-edain report <mod-folder> [faction] [--out FILE]`

- `<mod-folder>` is the mod's root (e.g. `.../_mod`), **not** the deeper `data/ini` folder - the
  root is where the localization table lives, so display names resolve to real in-game text instead
  of raw template ids.
- `[faction]` is a faction template name or Side token (e.g. `Gondor`, `Men`, `FactionMen`). Omit
  it to get a one-row-per-faction **roster comparison table** followed by every faction's report.
- `--out FILE` writes the Markdown to a file instead of stdout (use this for a large faction - the
  digest is long, and a file is easier to re-read while you write).

What the digest contains:

- **Roster tally** - structure / unit / hero / upgrade / power counts at a glance.
- **Spellbook** - every power with its cooldown, classification (`summon` / `transform` /
  `weapon` / `modifier`), in-game effect text, and what it summons / transforms into / fires / buffs.
- **Start points** - each plot flag, what base or single structure it deploys, and the base's
  citadel / foundations / prebuilt structures (when base layouts are available).
- **Structures** grouped by role (citadel, foundation, prebuilt, standalone), each with what it
  trains / recruits / researches and its own activated abilities.
- **Units / Heroes** stat tables - cost, command points, health, primary attack
  (`melee 95 SPECIALIST (47.5 dps)`), resilience (what it is tough vs / weak vs), and where it is
  built. Unit and hero abilities are listed beneath their table.
- **Upgrades** - cost, which structures research them, and **which units / heroes / structures
  each upgrade affects** (whose weapons, armor or modules are gated on it) - the "what does
  Forged Blades actually do to this roster" column.

## Workflow: visualise then critique

1. **Pick the faction.** If you don't know the faction's name, run `sage-edain factions
   <mod-folder>/data/ini` (or `report` with no faction) to list them.
2. **Generate the digest.** `sage-edain report <mod-folder> <faction> --out faction.md`, then read
   `faction.md`. This is the "visualisation" - the whole faction as structured text.
3. **Critique from the data.** Reason over the digest, e.g.:
   - *Roster shape* - does it cover the rock-paper-scissors roles (its own resilience table shows
     each unit's `tough vs` / `weak vs`; check the faction can answer cavalry, archers, infantry,
     siege, monsters)? Gaps and redundancy show up as missing or duplicated roles.
   - *Cost curve* - read cost vs health vs dps down the unit table; flag outliers (a unit that is
     strictly better than another for less, a tier with no cheap option).
   - *Spellbook* - is the power progression coherent (cheap early utility, expensive late summons)?
     Do cooldowns and effects match the faction's intended playstyle?
   - *Economy & tech* - how many farms/resource buildings, how upgrades gate units, where heroes
     come from.
   - *Synergies* - buffs (modifier powers, banner/forge upgrades) that line up with the units that
     benefit.
4. **Write the human-readable profile.** Produce the final document the user asked for: a faction
   overview, its strengths / weaknesses, notable units and heroes, and your balance notes. Cite the
   numbers from the digest (cost, health, dps, cooldown) so the critique is grounded.

## Going deeper

- **Compare factions.** Run `report` with no faction for the roster table, then generate two
  factions' digests and contrast their tables directly.
- **Compare versions.** `sage-edain diff <old-mod-folder> <new-mod-folder> [faction]` is the
  balance changelog between two checkouts of the mod: units/heroes/upgrades/structures added or
  removed per faction, and each surviving entity's stat moves (cost, health, per-weapon
  damage/dps, effective armor, power cooldowns). `--json` for the structured form, `--out FILE`
  to write the Markdown.
- **Programmatic detail.** `sage-edain explore <mod-folder> <faction> --json` emits the full graph
  (every `Producer` edge, full profiles) as JSON when you need a field the digest summarises.
  `sage-edain schema` documents that payload's exact shape (`schema diff` for the changelog's), so
  read it before writing code against the JSON.
- **Base layouts.** Pass `--bases <mod>/bases` (needs the `edain` extra) so castle/camp/outpost
  start points decompose into their citadel + foundations + prebuilt structures.
- **A field's meaning or a raw reference.** The digest is faction-level. To chase what a specific
  `.ini` field, command button, or upgrade *is*, switch to the **bfme-ini** skill and the
  `sage-ini` CLI - that is the schema-level tool; this one is the faction-level tool.

## Rules

- The digest is what the faction *has* - never invent units, heroes, powers or stats not in it.
- Stats are resolved at base state (no upgrades toggled, lowest rank); say so if it matters to a
  balance claim. A horde's combat stats come from its contained unit, its cost from the horde.
- Point the command at the **mod folder**, not `data/ini`, or display names fall back to template
  ids and the digest reads as raw object names.
