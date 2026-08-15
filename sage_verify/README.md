# `sage_verify` — did that player actually see what they clicked on?

Follows a replay playing back in a real client and checks every targeted order against the
engine's own shroud grid. Plus `attest`, which says whether a running client is the binary you
think it is.

```
sage-verify watch "Last Replay.BfME2Replay"
sage-verify attest patched-game.dat
```

## The idea

A replay records **inputs**, not state, so a replay on its own cannot say what a player could
see. The engine can. So the engine does it: start the replay in the game, attach read-only with
`sage_live`, and read the per-seat visibility it rebuilds frame by frame. Nothing here simulates
anything.

> order at frame F names object X → was X inside the issuer's shroud at frame F?

You cannot click what you cannot see. An order naming an enemy object its issuer has never had
line of sight on is not a play style — it is information that did not come from the game.

**Why this half matters.** Its sibling, [`binary-attest`](../sage_patch/docs/binary-attest.md),
runs *inside* the client it judges, so whoever can modify the game can modify the check. This
runs on the observer's machine, after the fact, over a recording somebody else made. It is the
weaker signal and the far stronger position — there is nothing in it for a cheater to patch.

## Using it

1. Open the replay in the game and let it start playing.
2. `sage-verify watch <the same replay file>` from an **elevated** shell (`game.dat` runs as
   administrator, so the reader must too).
3. Let it run. It follows to the end of the playback and prints a report.

Attach as early in the playback as you can: the visibility memory is built from the frames it
actually samples, and orders before the first sample cannot be judged.

Exit codes: `0` clean, `1` findings, `2` coverage below `--min-coverage` — "not checked" is its
own answer and must never read as "clean".

## Reading the output

```
violations:
  frame  12480  Someone          MSG_DO_ATTACK_OBJECT               object 4211      [high]
      ordered against object 4211 (owned by player 4), which player 3 has never been
      observed to see - not visible at frame 12475 and absent from every earlier sample

followed frames 210..38400 over 3812 samples
1204 orders, 316 of them targeted; judged 291 (92% coverage)
```

**Coverage is the number that decides whether the rest means anything.** A run with 4% coverage
that finds nothing has found nothing because it looked at nothing, and the report says so
explicitly rather than printing a reassuring "clean".

**Confidence is not decoration.**

- `high` — an **object** target. Near-conclusive: the engine will not hand a client an ObjectId
  for something it never drew.
- `low` — a **ground** target. Circumstantial. Ground can be aimed at for honest reasons — a
  guess, a remembered position, a chokepoint — and these should never be read on their own.

## The three things that make this harder than it sounds

**1. The engine keeps no memory, so this module has to.** The shroud grid answers "can this seat
see that cell *right now*" and nothing else — a cell scouted an hour ago reads byte-for-byte like
one never reached (see [`fog-of-war.md`](../sage_patch/docs/fog-of-war.md) §6). But a human can
legitimately attack a building they scouted long ago. So `Memory` accumulates what each seat has
been *observed* to see, and only a **never**-seen target is a finding. That memory is only as
complete as the sampling: missing a reveal manufactures a false positive, which is why the loop
samples as fast as it can and why `--max-lag` refuses to judge rather than guess.

**2. Judging must use the state *before* the order.** Attacking a unit reveals it, so the shroud
one frame after any attack shows the target plainly visible. A tool that judged against the
nearest sample would clear every maphack in the corpus while looking like it worked. The loop
keeps the previous sample and judges each order against the newest one **at or before** its
frame. `test_it_judges_against_the_sample_before_the_order_not_after` is that rule.

**3. Seats are matched by name, and failures are loud.** Replay slot numbering and the live
`PlayerList` index are different spaces —
[`message-stream.md`](../sage_patch/docs/message-stream.md) §4c records a game whose recorder was
index 3 in memory and player 2 in the file. An offset assumption would silently judge one
player's orders against another's vision. Unmatched slots are reported, never guessed.

## Known limits

- **AI players issue no orders at all**, so an AI opponent is invisible to this and its slot is
  never mapped.
- **A match with fog of war switched off is unjudgeable**, and reported as such rather than as
  clean.
- **Garrisoned units report their holder's position**, so a target inside a building is judged at
  the building.
- **It cannot see an external overlay** — nothing can, from inside. But it does not need to: an
  overlay's *value* to a cheater is acting on what it shows, and acting is what leaves orders.

## `attest`

The other subcommand closes the loop with the patch:

```
$ sage-verify attest patched-game.dat
patched-game.dat
  expects  0x582b8583
  pid 21044 holds 0x582b8583
  MATCH - the running client is this binary
```

It recomputes the attestation hash from the file and compares it with the one the running process
computed for itself. The two can agree because the image has no `.reloc` and does not set
`DYNAMIC_BASE`, so `.text` in memory is `.text` on disk. The value is folded at the first
`MSG_LOGIC_CRC` heartbeat, so start a match and give it ~100 frames before asking.

## Layout

| module | |
|---|---|
| `orders` | which order ids carry a target, and how to read it out of a chunk |
| `rules` | the judgement — plain data in, verdict out, no game required |
| `watch` | the live loop: attach, follow frames, feed `rules` |
| `report` | findings, coverage, and the summary |
