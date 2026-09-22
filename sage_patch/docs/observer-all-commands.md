# Opening the observer's command gate completely — reverse-engineering notes

The RE behind [`patches/experimental/observer_all_commands.py`](../patches/experimental/observer_all_commands.py),
which lets an observer's clicks reach **every** button on the command bar rather than the two
paging commands [`observer-command-range`](observer-command-range.md) names. ROTWK `game.dat`
build `2.01.2614.37001`, ImageBase `0x400000`. **Run in a live game 2026-09-20: it applies, the gate opens, and the dispatched orders do nothing — see §4.**

[`observer-command-range.md`](observer-command-range.md) is the write-up for this gate: it traces
the click from the window callback to `ControlBar::doCommand` and establishes that
`PlayerList::localPlayerIsNotActive` at `0x00941BD2` is what an observer's click dies on. That
document is the prerequisite; this one records what changes when the gate is opened for everything
instead of for two commands.

**Its claim that "nothing else is in the way" holds only for the two paging commands it names.**
Widening the gate to every command found two further links it never had to prove — a second
availability check inside `doCommand`, which an observer does pass, and order attribution, which
an observer does not. §4 is the measurement.

## TL;DR

- The gate is one `call` at `0x00941BD2` whose answer the caller reads as `test al, al / jne
  <discard>`. Replacing the five bytes with `xor eax, eax` and three `nop`s makes the answer a
  constant "the local player is active", for every command type and every observer.
- **The zero has to be 32 bits wide.** Four instructions below the gate, `0x00941BE5` and
  `0x00941BF7` build `ControlBar::doCommand`'s two `Bool` arguments with `sete al` / `setne al`
  and `push eax` — as dwords. The stock predicate returns a clean `0` or `1` in all of `eax`
  (`neg al; sbb eax, eax; inc eax`); `xor al, al` would push the top three bytes of whatever the
  window virtual at `0x00941BBD` returned.
- No cave: the answer is a constant, and a constant fits where the `call` was.
- **This is not client-local.** Every command past `PUSH`/`POP_VISIBLE_COMMAND_RANGE` ends in a
  posted `GameMessage`. That is the point of the patch and the reason it is experimental.
- **It is also not sufficient.** Measured in a live game: the clicks dispatch and the messages are
  posted, but the engine attributes each order to `ThePlayerList->m_local` — the observer seat,
  which owns nothing — so every order is a well-formed no-op. §4.

## 1. The five bytes

```asm
00941bc8  85f6            test esi, esi
00941bca  74f8            je   0x941bc4          ; discard
00941bcc  8b0d2849de00    mov  ecx, [0x00de4928] ; ThePlayerList — now a dead load
00941bd2  31c0            xor  eax, eax          ; was: call 0x006a87f5
00941bd4  909090          nop / nop / nop
00941bd7  84c0            test al, al
00941bd9  75e9            jne  0x941bc4          ; never taken
00941bdb  817c24140b400000 cmp [esp+0x14], 0x400b
```

`ecx` is caller-saved and nothing between the load and `ControlBar::doCommand` reads it —
`0x00941BE3` reloads it from `ebx` (`TheControlBar`) for the thiscall. The load stays because
removing it would mean rewriting bytes this patch has no other reason to touch.

The three `nop`s are padding, not decoration: the `jne` at `0x00941BD9` is a backward `rel8` into
the discard path at `0x00941BC4` and is not rewritten, so the instruction boundary at
`0x00941BD7` has to stay exactly where the `call` left it.

## 2. Why the whole of `eax`

The stock predicate's tail is what makes the width a contract rather than a preference:

```asm
006a87fd  f6d8            neg  al
006a87ff  1bc0            sbb  eax, eax
00941be5  0f94c0          sete al                ; message == 0x400B
00941bf6  50              push eax               ; …as a dword
00941bf7  0f95c0          setne al               ; message != 0x4009
00941bfa  50              push eax               ; …as a dword
```

`sbb eax, eax` followed by `inc eax` leaves `eax` at exactly `0` or `1`, so `sete al` writes into
a register whose top 24 bits are already zero and the pushed dword is a well-formed `Bool`. A
narrower replacement breaks that silently — the click still dispatches, with two arguments whose
high bytes are the return value of `GameWindow`'s slot-`0x20` virtual. `xor eax, eax` is the only
five-byte-or-shorter form that reproduces the stock contract, which is why the argument build at
`0x00941BE3` is one of this patch's anchors.

## 3. What the gate was sorting

The engine has no "inspect" and "order" categories for `GUICOMMAND`s; this gate was the whole of
the distinction. `observer-command-range` recovers the distinction by hand, naming the two
commands whose handlers (`0x00941A7D`, `0x00941A9C`) do nothing but push or pop an 8-byte record
on `ControlBar+0x2B0` and re-run `switchToContext`. Every other command type reaching
`ControlBar::doCommand`'s switch at `0x009408C9` eventually posts a `GameMessage` — `UNIT_BUILD`,
`PURCHASE_SCIENCE`, `SPECIAL_POWER`, `EXIT_CONTAINER`, `SELL`, the rest.

So opening the gate completely is the same edit with the whitelist deleted, and it buys:

- every paging, tab and page-flipping button, which is what `observer-command-range` was for;
- any command whose visible effect is client-side in practice — a detail panel or tooltip that
  only opens on a click;
- and, inseparably, the order-posting ones.

The engine does not offer a third option at this site. A patch that wanted "clicks through,
messages suppressed" would have to gate `TheMessageStream::appendMessage` on the observer bit
instead, which is a different and much larger piece of work — the message post is reached from
dozens of handlers with no shared chokepoint on this path.

## 4. What a dispatched order actually does — measured

**Tested in a live game, 2026-09-20, observing with vision of the player whose buttons were
clicked.** The result: the buttons are drawn **lit**, the clicks are **dispatched**, and
**nothing happens in the simulation**. This patch alone does not make an observer's commands
take effect, and the three links below are why.

| link | state | evidence |
|---|---|---|
| the click gate, `0x00941BD2` | **open** | paging buttons work, which they cannot do on a stock binary |
| `doCommand`'s availability re-check | **passes** | the buttons render enabled, and the drawn state *is* `getCommandAvailability`'s verdict (§4.1) |
| the handler posts a `GameMessage` | **happens** | e.g. `0x00940936`: `mov ecx, [TheMessageStream]` / `push 0x419` / `call [eax+0x48]` |
| the simulation acts on it | **no-op** | §4.2 |

### 4.1 `doCommand` asks a second time

`ControlBar::doCommand` does **not** trust the gate. It calls
`ControlBar::getCommandAvailability` again — at `0x009405B3` over the selection, and at
`0x00940625` for the single current drawable — and proceeds only on verdict **1** or **2**:

```asm
009405b3  call 0x00942733        ; getCommandAvailability
009405b8  cmp  eax, 1 ; je 0x940656    ; proceed
009405c1  cmp  eax, 2 ; je 0x940656    ; proceed
```

This is why opening the gate alone was never going to be the whole story, and it is also why the
paging commands were the only ones the sibling patch ever had to prove: they land in that
evaluator's **default** case, verdict `1`, without consulting any player state at all. For an
observer this gate nevertheless **passes** for ordinary commands too, because
`PlayerList::getLocalPlayer` (`0x006A8839`) redirects to `ControlBar+0x218` — so availability is
computed against the player being watched, and the answer is the one that player would get.

### 4.2 The order is attributed to the observer seat

The click reaches the handler, the handler appends a real `GameMessage`, and the order is then
attributed to **`ThePlayerList->m_local`** — the `ReplayObserver` — not to the redirected
`getLocalPlayer`. [`message-stream.md`](message-stream.md) §4c records the same thing from the
other side, runtime-verified through `sage_live`'s own injection path: *"The player index is not
transmitted … the engine attributes the order to the local player itself."*

So the order is issued, accepted, and executed on behalf of a seat that owns no objects, has no
production and no resources. It is a well-formed no-op.

This is the **same asymmetry** that made the original gate bite, one layer further down:
everything cosmetic goes through `getLocalPlayer` and sees the observed player, everything
authoritative reads `m_local` and sees the observer. The bar and the simulation disagree about
whose button it is, and this patch removes the one place that disagreement used to be caught.

### 4.3 What is still unknown

**Where attribution is stamped has not been pinned down.** It is not in the message-stream code:
`ThePlayerList` (`0x00DE4928`) has no references anywhere in `0x0070xxxx`–`0x0071xxxx`, and
`PlayerList::getLocalPlayer` has none either, so `appendMessage` is not reading it. The candidates
are the end-of-frame propagation into the network layer (which would also explain why the index is
not transmitted — the receiving peer takes it from the sender) and resolution at execution time in
the logic. Until that site is found, a patch that redirects attribution cannot be written, and
**this one does not attempt it.**

## 5. What `apply` and `verify` anchor

- **The gate itself**, as the stock `call` — `apply_byte_patch` asserts `e8 1e 6c d6 ff` before
  writing, and the installed-binary test walks the displacement to prove it lands on
  `PlayerList::localPlayerIsNotActive` rather than trusting this document.
- **`0x00941BC8`**, the `test esi, esi` and the `ThePlayerList` load, pinning the gate's shape.
- **`0x00941BD7`**, the `test al, al` / `jne` the constant is answering, and the `cmp [esp+0x14],
  0x400b` below it.
- **`0x00941BE3`**, the argument build — §2. Structurally optional, load-bearing for the reason
  the constant is `xor eax, eax`.

## 6. Conflict with `observer-command-range`

Both patches own the five bytes at `0x00941BD2`, so the second to apply refuses. `apply_byte_patch`
catches it in one direction with a hex pair; in the other — the gate holding an `e8` that is not
the stock displacement — this patch names `observer-command-range` explicitly, because that is the
only thing it can be. The combination is meaningless either way: a whitelist behind an open gate
is unreachable, and an open gate overwritten by a call into a cave is just the other patch.

`observer-switch`, which is what gets an observer onto a skirmish replay's seat in the first
place, edits a different `call` and composes with either.

## Address index

**`ControlBar::processCommandUI` `0x00941B9F`** · the button load `0x00941BB1` · the gate prefix
`0x00941BC8` · **the gate `0x00941BD2`** · the discard test `0x00941BD7` → `0x00941BC4` · the
argument build `0x00941BE3`..`0x00941C01` · `ControlBar::doCommand` `0x00940435`, its type switch
`0x009408C9` · `PlayerList::localPlayerIsNotActive` `0x006A87F5` ·
`PlayerList::getLocalPlayer` `0x006A8839` · `ThePlayerList` `0x00DE4928` · `TheControlBar`
`0x00DE7744` (observed player `+0x218`, range stack `+0x2B0`).
