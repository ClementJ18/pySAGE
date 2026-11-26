# Faction variants in the game-setup screen

How the setup screen lists, shows and assigns a slot's faction, and the patch that lets a mod group
variants of one faction behind a second combo box instead of listing each beside every other
faction. Engine build `2.01.2614.37001`; every address is a VA in that image.

## 1. What a faction is to the lobby

A lobby slot holds one `Int`: `GameSlot+0x18`, an index into `ThePlayerTemplateStore`'s
`std::vector<PlayerTemplate>` (`[0x00DE3B10]+0x0C .. +0x10`, stride `0x1DC`), or `-1` for Random
and `-2` for Observer. That index is what the lobby serialises, what a replay header records and
what `GameLogic::startNewGame` hands to `Player::init`. `PlayerTemplateStore::findByIndex`
(`0x005FCAD9`) resolves it to the final override.

So a variant that is its own `PlayerTemplate` needs nothing from the wire format, replays, the
skirmish AI or any tool: it already is a faction to all of them. The only thing that knows factions
as a *list a player picks from* is the setup screen, and that is all this patch changes.

## 2. The setup screen's faction box

`MpGameSetup` (the skirmish and LAN lobby; `AptOnlineCustomMatch` is a different screen, see §7)
keeps six eight-entry arrays of per-slot windows, filed by the gadget binder at `0x00840906` from
the names the movie gives them - `~<slot>.<Kind>`, split by `sscanf("%d")` and `0x008155A7`:

| kind | array | handler on selection |
|---|---|---|
| `Player` | `+0x2D4` | `0x00845479` |
| `Color` | `+0x2F4` | `0x00840AAA` |
| `Team` | `+0x314` | `0x008403A0` |
| `PlayerTemplate` | `+0x334` | `0x00844177` |
| `Handicap` | `+0x354` | `0x00840485` |
| `Hero` | `+0x374` | `0x0084040D` |

The binder is a `stricmp` ladder; `Hero` is its last rung (`push <"Hero">` at `0x00840A6C`), a miss
leaves through `0x00840AA3`, and every filed gadget joins `0x00840A8D`, the `pop ecx` that drops the
window pushed for `ComboBox::reset` (`0x00724187`). The constructor clears each array with a
`memset` (`0x008451FD` for `+0x334`).

Four routines own the faction box:

- **the fill**, `0x00844BD4(slot)`: resets the box, adds `GUI:Random`, walks the store's display
  list (`[0x00DE3B10]+0x18`, a sorted set of indices), skips templates that are not
  `PlayableSide` (`+0x151`, the test at `0x00844DBE`) or are `IsObserver` (`+0x150`), and adds each
  survivor with its index as the row's data. Called from `0x00844F70`, `0x0084552C` and
  `0x00846889`.
- **the sync**, `0x00843D43(slot)`: reads `GameSlot+0x18` into `[ebp-0x14]` (`0x00843D7B`) and
  either selects the row carrying it (an editable slot) or writes the template's display name as
  the box's text (a slot another player owns). Called from `0x00844451`.
- **the handler**, `0x00844177(slot)`: reads the selected row's data (`0x008401D0`, its only
  caller), and when it differs from the slot's template asks the screen's strategy object for it -
  `[screen+0x58]` vtable `+0x28`, `(GameSlot *, Int) -> Bool`, which sets it in skirmish and on a
  LAN host and sends a request from a LAN client - then redraws the slot through `0x00843B4C`.
- **the enable**, inside the per-slot control update: `call Window::winEnable` at `0x00842BB9`,
  with the flag the screen computed for that slot.

The selection message is `0x4026`; its handler (`0x00845905`) walks the eight slots comparing the
sender against every array, and ends unmatched at `0x0084594E`.

The combo-box calls are all cdecl wrappers around `TheWindowManager->winSendSystemMsg`
(`[0x00DE495C]` vtable `+0xE8`): reset `0x4025`, add a row `0x4022` (`0x00724811`, text by value,
destroyed by the callee), set and get a row's data `0x402B` / `0x402A`, set and get the selection
`0x402D` / `0x402C`, and `0x0072414F` for the drop-down's height. A window's status word is at
`+0x08` with Generals' bits, `0x08` enabled and `0x10` hidden.

## 3. Random

`GameLogic::startNewGame` resolves a Random slot from a pool built at `0x0062D4A3`: every index
whose template is `PlayableSide` (the test at `0x0062D4D4`) is pushed onto `[ebp-0x58]`, the pool
is filtered by the slot's start-position restrictions into `[ebp-0x28]`, and the pick is
`GameLogicRandomValue` over what remains (`0x0062D6F4`). It is synchronised, so every peer resolves
the same faction.

### A second Random

A Random slot's Variant box offers **Random** and **Standard**. Standard is the stock sentinel, -1:
a base faction drawn from the pool above, played as it stands. Random is a new one, -3: the same
draw, then a second draw among that faction and its playable variants, the faction itself
included, each equally likely. -1 stays the default, so the faction box's own Random row, AI slots
and a lobby that never opens the Variant box behave exactly as before.

The second draw hooks where the first one is applied, `push esi` / `mov ecx, ebx` /
`call GameSlot::setPlayerTemplate` at `0x0062D71C`: the slot is in `ebx` and still holds its
sentinel, the drawn template is in `esi`, and the code after the call goes on reading `esi`. It uses
`GameLogicRandomValue` (`0x006D328E`, `lo..hi` inclusive), the synchronised generator the faction
draw itself uses, so every peer and every replay draws the same variant. A faction without variants
consumes no random number.

A Random slot also offers **Variants**, -4: one of every faction's playable variants, drawn
uniformly and never a base faction, settled with the same hook as a faction's Random below. With
no variant in the mod the row is not offered, and a -4 that arrives anyway falls back to -1.

A Random slot also offers **Good** (-5) and **Evil** (-6): a base faction drawn as for Standard
and played as it stands, from only the candidates whose `PlayerTemplate` says `Evil = No` or
`Evil = Yes` (`+0x1BC`, a Bool - the byte `Player::initCommandPoints` reads to pick the Good or Evil
command-point pair). Each slot draws from its own copy of the pool, a `std::vector<Int>` at
`[ebp-0x28]`/`[ebp-0x24]` that its start position's restrictions have already filtered, and the
draw itself opens at `0x0062D6D8` with `mov esi, [ebp-0x24]` / `mov edi, [ebp-0x28]`, the address
both filters' "nothing to filter" branches (`0x0062D65D`, `0x0062D6CD`) land on. The hook there
compacts that copy to the slot's side and lowers the vector's end, which is safe because the
elements are `Int`s and the block is freed through its begin (`0x0062D731`). A copy that holds
none of the side - a start position restricted to the other one - is left whole, so the draw never
divides by zero. The pick is a base faction, so `random_assign` leaves it as it is. The rows are
offered only when the mod has playable base factions on both sides; with one side only, either
row would just be Standard. They are labelled `GUI:FactionVariantGood` and
`GUI:FactionVariantEvil`.

A faction's own Variant box leads with **Random** too: that faction, then a draw among it and its
variants. It is `-16 - index` - faction 5 is -21 - and is settled where `startNewGame` reads each
occupied slot's template for the Random pass (`mov esi, [ebx+0x18]` at `0x0062D52C`): drawn with
the same `GameLogicRandomValue`, set on the slot, and handed on in `esi`, so the Random pass finds
a real template and leaves it alone. The faction box shows it as its faction. The LAN packet
carries a template as a signed byte, which bounds the index at 111 (-127; -128 is the LAN escape
of a Random pool, below); a faction past that gets no Random row.

-3 to -6 and `-16 - index` have to get through every reader that bounds a template from below at -2, or
the value is refused - the whole lobby string, the request, the packet:

| site | reader |
|---|---|
| `0x0080351C`, `0x0080385B` | `ParseAsciiStringToGameInfo`, both slot kinds |
| `0x0064A271` | the LAN host applying a client's `PlayerTemplate` request |
| `0x0084B4A6`, `0x0084B79D` | the two LAN packet readers (the template travels as a signed byte) |

The two LAN packet readers get a one-byte edit of the immediate, `-2` to `-128`; the lobby string
parser and the host's request check are hooked instead, because they also take Random pools (below)
and accept down to -127 otherwise. The online lobby's reader (`0x009AD961`)
is left alone: that screen has no Variant box. A sweep of every `cmp <template>, -1` and `-2` in
the image found one more reader that would misread it: the map preview's start-position numbers
(`0x007053DE`, `0x00705457`) skip observers with `cmp [slot+0x18], -2` / `jle`, which would hide a
-3 slot's number too, so both `jle` become `je`. Every other test is an `== -2` for Observer or a
`< 0` for "not a real template", and -3 passes both as -1 does.

That sweep looked at the slot's field and missed one reader of the *argument*: `GameSlot::setPlayerTemplate`
(`0x00802C5A`) ends with `cmp [ebp+8], -2 / pop edi / jg` (`0x00802D50`), and "-2 or below" sets the
seat's start position (`+0x10`, `+0x14`) to -1, as for an observer. So every one of these
sentinels, picked in the lobby or read from `Skirmish.ini`, threw away the seat's start position.
The `jg` becomes `jne` (`0x00802D55`, one byte). Below -2 the values now take Random's path, which
calls `0x00802876` with the slot, and that routine returns at once for anything `<= -2`
(`0x00802886`). A second sweep, for `cmp <anything>, -2` followed by a signed branch, found nothing
else that reads a template.

### Random pools

A slot's template can also name **a pool**: `-0x80000000 | mask`, the top byte `0x80` and bit *n*
of the 24-bit mask template index *n* (`RANDOM_POOL`, `random_pool()`). 24 bits is what the LAN
packet has room for (below); Edain's highest playable index is 13. It is drawn among the templates it names,
variants included, each equally likely, and played as drawn. This is the engine half of a "pick
which factions Random may give me" panel.

The value lives in the slot's own template, on purpose. A separate store would have to follow
every copy of a `GameSlot` - the lobby's `GameInfo`, `TheGameInfo`, the replay header's - and
nothing would carry it from one to the next. In the template, every copy carries it already.
`GameInfoToAsciiString` writes it as the decimal it is, so `Skirmish.ini` and replay headers keep
it at no cost. And `startNewGame`'s Random pass is `cmp esi, 0 / jl` (`0x0062D534`), so it takes
any negative value for Random, a pool included.

Five places had to learn it:

- **The draw** (`0x0062D6D8`, the Good/Evil hook). When the slot holds a pool, count the
  templates it names that are playable, not observers, and whose faction (the template, or its
  base for a variant) is among the slot's candidates. The candidates are already filtered by start
  position, so that filter carries over to variants. Draw one with `GameLogicRandomValue(0, n-1)`
  and write it over the candidates' first element, then lower the end to one past it. The stock
  draw that follows (`pool[GameLogicRandomValue(0, 1000) % size]`) can then only take it. The
  first element exists because the pick's faction is a candidate. A pool that allows nothing
  leaves the candidates alone and consumes no random number, so the slot draws as Standard.
  `random_assign` and `slot_template` leave pools alone: the former acts on -3 only, the latter
  on `-16` to `-127` only.
- **The lobby string parser** (`0x0080351C`, `0x0080385B`). Each slot arm's check is
  `cmp eax, -2 / pop ecx / mov [ebp-0x28], eax / jl <reject>`. No immediate can admit a value
  below -128, so the 13-byte window becomes a jump. The cave accepts -127 and up and pools with
  a non-empty mask, then rejoins the stock upper-bound check, which reloads the value from
  `[ebp-0x28]`.
- **The lobby** reads a pool as Random: `family` returns -1 below -127, so the faction box shows
  Random. The Variant box lists Random's rows with none selected, since none of them is the pool.
- **The setup screen's commands.** The movie sends a pool with
  `_root.GameCodeNoPrefix("MpGameSetup::SetRandomPool", "<slot>:<mask>")`, which reaches
  `MpGameSetup`'s command map under that name. Not `GameCode`: it prefixes `_root.CodePrefix`,
  which nothing on this screen sets (the engine has no such string), so it sends
  `undefined::SetRandomPool` and nothing answers - every stock button here uses
  `GameCodeNoPrefix` with the whole name. The screen's constructor files each command in a block of ~85
  bytes: an `AsciiString` of the name at `[ebp-0x10]`, a functor `{screen, -, handler, 0}` built at
  `[ebp-0x38]` and copied onto the stack for `0x00A02F80`, then `0x0092B062` on `screen+4` and the
  string's destructor. The patch takes the five-byte `push` that opens the `OnSortName` block
  (`0x00845C2B`), runs its own copy of a block for `SetRandomPool`, redoes the `push` and goes on.
  Assembled at `0x00845C2B` with `OnSortName`'s name and handler, `emit_command_block` is that
  block byte for byte, which the tests check. No stock command is renamed or lost. The handler
  (`thiscall (const char *)`, `ret 4`) parses the two decimals, refuses a slot past 7, a mask past
  24 bits or anything malformed, and refuses a seat whose faction box is disabled or hidden - the
  screen's own "not yours to change". Mask 0 asks for -1. The request then goes the way a Variant
  box pick does (`request`, split out of `changed` for this): the strategy object at
  `[screen+0x58]`, which sets it in skirmish and on a LAN host and asks the host from a LAN client.
- **Reading a pool back.** The movie's variables go with the screen, but the seat keeps its pool
  across a match and back, so the panel asks the engine as it opens:
  `_root.GetExtern("MpGameSetup::RandomPool<slot>")` is the seat's mask in decimal, `"0"` for a
  seat that is not a pool. Externs are the screen's second map, `screen+0x10`, filled like
  commands but through `0x0092B0C7` (`thiscall (AsciiString *name, int index, functor)`,
  `ret 0xc`, which also tells the APT player the name), as the stock `MpGameSetup::HostMode` block
  at `0x00845DD4` does. A handler is `thiscall (int index, char *out, bool flag)`, `ret 0xc`, and
  copies its value into `out` when `flag` is 0. The patch files eight, `RandomPool0` to `7`, on one
  handler with the slot as the index (`emit_extern_block`, `get_pool`).
- **Whether a row button may be used.** The faction box is an engine window, so the movie cannot
  see it enabled or disabled; `_root.GetExtern("MpGameSetup::RandomPoolSeat<slot>")` says it:
  `"2"` shown and enabled (the player's seat, or an AI seat for the host), `"1"` shown but
  disabled (another player's seat), `"0"` hidden or missing. The test is the one
  `SetRandomPool` refuses a seat by - the box's `WINDOW_STATUS` hidden and enabled bits
  (`get_seat`, eight more externs on one handler). The panel's row button polls it every other
  frame from a two-frame looping clip and greys itself on `"1"`, hides on `"0"`.
- **The panel's mouse gate.** `MpGameSetup::RandomPoolModal` `"1"` / `"0"`, sent as the panel
  opens and closes, holds `GameWindowManager::winProcessMouseEvent` (`0x006C23AD`) shut while the
  screen that sent it is up (`MP_SETUP_CURRENT`, `0x00DE8D78`): no engine window takes the mouse,
  so the clicks reach the panel drawn over them.
- **Escape closes the panel.** An APT button's key-press action never fires on this screen: keys
  go to `GameWindowManager::winProcessKey` (`0x006C1AF1`, the vtable slot after
  `winProcessMouseEvent`), which sends `GWM_CHAR` (0x15) to the window with keyboard focus and up
  its parents. Only the online screens have a window callback that takes Escape (`0x009AFDEC`,
  `0x009CA27C`; they call their movie's `EscapeKeyPressed`). The setup screens have none. While
  the panel holds the mouse gate, a second gate at `winProcessKey`'s entry reports Escape (key 1)
  used and records its release (`state & 1`). The panel reads it back each frame with
  `_root.GetExtern("MpGameSetup::RandomPoolEscape")`, which is `"1"` from then on, and closes as
  Back does. `RandomPoolModal` clears it on open and on close (`key_gate`, `get_escape`).
- **The LAN host's request check** (`0x0064A271`, `cmp edi, -2 / jl <refuse>`): hooked like the
  parser, so a client's pool request is accepted.

**Over LAN** the packed `GameInfo` carries a template as one byte, so
[`lobby-faction-byte`](lobby-faction-byte.md) sends a pool as the escape byte -128
(`LAN_POOL_ESCAPE`) and the mask's three bytes, and turns them back into the pool where each parser
arm hands the seat its template. That is why the packet readers' lower bound is -128 while every
other reader stops at -127. A pool there is no room left for in the 0x186-byte payload becomes
plain Random on the host too, so every peer still draws alike; see that page, §5.

**The LAN lobby still refuses pools.** The host's request handler (`0x0064A271`) and the packet
readers keep their -128 bound. That is deliberate: the packet carries a template as one byte, and a
pool truncated to its low byte would reach every client as a real faction, a desync. Carrying pools
over LAN needs room in the 0x186-byte payload, which [`lobby-faction-byte.md`](lobby-faction-byte.md)
§3 shows is already tight with eight humans.

## 4. What the INI can say

Nothing groups one template under another. The patch adds a `PlayerTemplate` keyword:

```
PlayerTemplate FactionMen_DolAmroth
    ...
    PlayableSide = Yes
    VariantOf    = FactionMen
End
```

A variant is an ordinary, complete template, and must be `PlayableSide` to be offered. Its base
must be playable too, or neither appears.

The value cannot be stored in the template: a new block is parsed into a stack temporary
(`[ebp-0x1F4]` in `PlayerTemplateStore::parse`) and copied member by member into the vector, so
nothing written outside a real member survives. It goes into the cave instead, keyed by the
block's name key. The key is only written after the fields are read - at `0x005FE95C`
(`mov [ebp-0x1E4], edi`) for a new block, and inside the override and re-parse branches, which
join at `0x005FE900` - so the parse function leaves the parent's key pending and a hook at each of
those two points files it against the block's own. `edi` is the key at both. The parent's key is
taken with `NAME_KEY_FROM_CSTR` on the raw token, the call the store itself uses for the block name
(`0x005FE87B`), so the two compare equal.

The two hooks at the store's block key already taken by other patches (`0x005FE880`,
`second-resource`; `0x005FE886`, `command-point-upkeep`) are not needed.

### `EnabledForPvP`

A second keyword, a `Bool` that is `Yes` when not given:

```
PlayerTemplate FactionMen_Arnor
    ...
    VariantOf     = FactionMen
    EnabledForPvP = No
End
```

It is read through the stock `INI::parseBool` (`0x0042E558`) into a local and kept the same way
as `VariantOf`: pending until the block's key is written, then filed in the same row - each row is
`{key, parent key, PvP}`, the last 0 unstated, 1 No, 2 Yes. A block that names only one of the two
fields changes only that one, so an override can flip `EnabledForPvP` and keep the variant's
parent. The value is read on variants only: a base faction is always offered, whatever it says.

A variant saying `No` is **held back** unless the lobby's "Enable all variants" rule (§5a) is set.
Held back means:

- the Variant box lists it in its place but cannot pick it: added in the disabled colour
  (`[0x00DADF20]`) and passed to `0x00724160(box, row, 1)`, as the stock faction fill does a
  faction the scenario refuses (`0x00844E64`, `0x00844EA7`); a Random slot's Variants row counts
  only what may be played;
- no draw picks it - a faction's Random, Random's second draw, Variants and a Random pool all skip
  it, so a pool naming only held-back templates draws as Standard;
- a seat still holding one - picked before the host cleared the box, or restored from
  `Skirmish.ini` - shows its faction's Standard row in the lobby and is set to that faction where
  `startNewGame` reads the seat (`0x0062D52C`), before the Random pass.

The lobby never changes a seat on its own: only the start does, and it does it from `TheGameInfo`,
so every peer and every replay plays the same template.

## 5a. The "Enable all variants" rule

The setup screen's rules are ten `Int`s at `GameInfo+0x60` (`game-info.md` §7).
Rule set 0 - skirmish, LAN and online - has three checkboxes, bound in order
to the movie's `RuleCheckBox_0..2`: rule 0 `RULE:AllowCustomHeroes`, rule 2
`RULE:AllowRingHeroes`, and rule 1 **`RULE:ClanGame`**, default 0 (`{rule, default}` at
`0x00C82528`, `0x00C82530`, `0x00C82538`). `MpGameSetup`'s constructor gives rule 1 checkbox state
3 on every screen that is not an online clan match (`test byte [ebx+0x3a4], 0x40` / `jne` /
`push 3` / `push 1` / `call 0x00986A5C` at `0x00845325`), and the binder (`0x00986873`) skips a
state-3 rule, leaving its gadget hidden. Edain's movie already has the row: `NumCheckBoxes` is
`0x00960A5D`'s count, 3, so the third row is placed, blank and empty.

Nothing in the simulation reads rule 1: a scan of every `[TheGameInfo]` load followed by an access
in `+0x60..+0x70` finds rule 2 (`IS_GAME_MODE_ACTIVE "ringheroes"`), rule 3 (the command-point
factor), rule 4 (starting resources) and the stats string's rule 0. Yet it travels with the other
rules - the `GR` string, so the LAN game info, `Skirmish.ini` and the replay header - and only the
host can tick it (the rules' enable at `0x00986A0B`). So it is the carrier. Showing it is opt-in
(`all_variants_box`, `--all-variants-box`): without the option both edits below are left out, the
checkbox stays hidden outside an online clan match, rule 1 stays 0, and an `EnabledForPvP = No`
variant is never fielded in skirmish or LAN. With it:

| where | what |
|---|---|
| `0x0084532C` | `jne` -> `jmp`: rule 1's checkbox is shown on every setup screen |
| `0x00DB7798` | rule 1's label, `RULE:ClanGame` -> `RULE:EnableAllVariants`, a string in the cave |
| `0x00841700`, `0x00842064`, `0x00842BCB`, `0x0084370A`, `0x008456F6`, `0x00845B0A` | the screen's own clan-match checks never match (`MP_SETUP_CLAN_GAME_READS`) |

The lobby reads it from the screen's own game info each time it fills a Variant box, and the match
reads it from `TheGameInfo` at each of the three `startNewGame` hooks; no game info (a campaign)
holds nothing back. Any nonzero value is "set", so the -1 a lobby without the checkbox leaves there
(War of the Ring) holds nothing back either.

The setup screen keeps a copy of the rules at `screen+0x15C` (refreshed from the game info by
`0x00784208` on every rule change), and six places test its rule 1 to act as an online clan match:
the seat-state box drops its AI entries and closes an AI seat (`0x00841700`), the Team box locks
(`0x00842BCB`), and `0x00842064`, `0x0084370A`, `0x008456F6`, `0x00845B0A`. Ticking the box did
exactly that in skirmish (seen in game, 2026-11-18), so with the option each test compares against
0x7F, or loads 0, and never sees a clan match. An online clan match would show the same box under
the new label. The online lobby is gone, so
nothing is lost. `[TheGlobalData]+0x9D4 & 3` makes the binder disable rules 0 and 1
(`0x0098690D`); what sets it is not traced, and a lobby where Allow Custom Heroes is greyed out
would show this box greyed out too.

## 5. What the patch does

"Variant" below means: a template whose `VariantOf` names another template that exists and is not
itself. Anything else - no `VariantOf`, a name that does not resolve, a template naming itself -
is a plain faction, so a typo leaves a faction visible rather than unreachable.

| where | what |
|---|---|
| `0x005FE95C`, `0x005FE900` | file the pending `VariantOf` against the block's key |
| `0x00844DBE` | the fill also skips variants |
| `0x0062D4D4` | Random's pool also skips variants, so a faction is not likelier for having them |
| `0x00843D7B` | the sync reads the slot's *base* - a variant shows, and is selected, as its faction |
| `0x00840A6C` | a `Variant` rung ahead of `Hero`: file `~<slot>.Variant`, with the screen that filed it |
| `0x008451FD` | the constructor forgets the previous screen's Variant boxes, then runs its `memset` |
| `0x00844F70`, `0x0084552C`, `0x00846889`, `0x00844451` | the fill and the sync, then the Variant box rebuilt from the slot |
| `0x0084594E` | the selection handler's unmatched edge tries the Variant boxes |
| `0x00842BB9` | the faction box's `winEnable`, then the Variant box brought into line |
| `0x0062D71C` | a slot on Random (-3) draws a variant of the faction it was given |
| `0x0062D52C` | a faction's Random (`-16 - index`) is settled to it or a variant |
| `0x0062D6D8` | a slot on Good (-5) or Evil (-6) draws only from candidates of that side; a slot on a pool draws among what it names |
| the five bounds of §3, `0x007053E2`, `0x0070545B` | -3 to -6 survive the lobby string, LAN and the map preview |
| `0x0080351C`, `0x0080385B` (in place of their one-byte bound) | the lobby string also takes a Random pool |
| `0x00802D55` | `setPlayerTemplate` clears the start position for -2 alone, not for every Random below it |
| `0x0084532C`, `0x00DB7798` | with `all_variants_box`: rule 1 shown on every setup screen as `RULE:EnableAllVariants` (§5a) |
| (inside the refresh) | War of the Ring: a Variant box row the scenario's `DisabledFactions` refuses the seat is greyed and unpickable |

The fill and the sync are wrapped at their calls rather than hooked at their entries because
`scenario-player-factions` asserts both entries' bytes; the byte-wise `e8` sweep in
`test_the_wrapped_calls_are_every_call` confirms those are every caller.

The **Variant box** is rebuilt from the slot every time its faction box is: empty unless the slot's
faction has a playable variant, and then the faction first - labelled `GUI:FactionVariantStandard`
- followed by its variants in store order, each row carrying its template index as the faction
box carries. The first row's text is `GUI:FactionVariantStandard` formatted with one `%s`, the
faction's display name, through `UnicodeString::format` (`0x00ADF7E0`): a label of `Standard`
ignores it, `%s (Standard)` shows it, and anything but `%s` would read an argument that is not
there. Every faction's box leads with a Random row (`-16 - index`, `GUI:Random`). A Random
seat - Random (-1), any of the sentinels -3 to -6, or a Random pool - shows a single `-` row, as a
closed seat does: what it may draw is its Random pool's to say (§3, "Random pools"). The
sentinels still draw as below when a seat holds one, from `Skirmish.ini` or an older lobby, but
the box no longer offers them. A faction with no variant gets the Standard row alone, and a closed seat (slot state 1) a
single `-` row - the stock wide `L"-"` at `0x00C540B0` that the faction box shows there
(`0x00843DD3`) - whatever template the seat holds. The box is shown when it lists anything
and its faction box is not hidden, and enabled when its faction box is and it lists two rows or
more. Another player's seat, a closed seat and a faction without variants are therefore all drawn
alike, the box disabled and its arrow greyed: nothing to choose. An enabled box also has its
drop-down button enabled: the combo box gadget keeps that button disabled while it lists fewer
than two rows. `winEnable` (`0x007154B3`) enables the window and its children and then sends the
gadget `0x1C`, whose handler (`0x0072493B`) returns early only for more than one entry and
otherwise disables the button (`[data+0x24]`, the data being the window's `+0x2C`); adding an
entry to an enabled box re-enables it for `count > 1` (`0x00724D32`). So the button is enabled
again after the box is, and the arrow shows as every other column's does.

A **pick** in it is `0x00844177` with the index read from the Variant box: the same "request
pending" byte (`+0x2C4`) cleared, the same strategy call, the same War of the Ring flags on success
(`+0x2BF`, `+0x2C2`, `+0x2B9`, `+0x2BE`, when the screen is in mode 1 and the scenario is
historical), the same redraw. Skirmish, LAN host and LAN client therefore each do what they already
do for the faction box.

The pick does **not** rebuild the box. It runs inside the box's own `0x4026`, and a combo box
reset from its own notification has its rows pulled out from under it and crashes the game on the
first pick. `0x00843B4C` does not refill the faction box either (it
calls the per-slot control update `0x00842C93` and the hero box's `0x0084040D`); both boxes are
refilled by the screen's next update. The fill wrapper keeps the Variant box's own pick while it
is a member of the slot's faction, as the stock fill keeps the faction box's, and the sync wrapper
forces the slot's template - so a LAN client's pick stays on screen until the host answers.

Picking a faction in the faction box resets the variant to that faction, since the handler asks
for the base's index.

**The War of the Ring scenario.** In the War of the Ring lobby (screen mode 1, `[screen+0x7C]`)
the box honours the scenario's `DisabledFactions` as the faction box does. The refresh finds the
scenario once, the way the stock fill does at `0x00844E17`: `getScenarioIndex` (`0x00975828`) on
the screen's War of the Ring sub-object (`screen+0x60`), and when that is not -1,
`LivingWorldCampaignManager::getCampaign` (`0x007B9636` on `[0x00DE87AC]`) and the campaign's
`+0x1C`. Every row that names a template - the Standard row, alone or ahead of the variants, and
each variant - is then asked about with that seat: the template's name built in place by
`PlayerTemplate::getName` (`0x00627707`), as the fill builds `isFactionEnabled`'s by-value argument
at `0x00844E23`, and handed to `scenario-player-factions`' matcher, which the cave carries a copy
of (`emit_is_faction_enabled`). So a scenario-wide entry and a `Faction<X>:N` naming this seat both
refuse it, and the row is added in the disabled colour and made unpickable - the same treatment as
a held-back variant, which a refused row may also be. The matcher understands `:N` whether or not
`scenario-player-factions` is installed; a stock scenario never writes one, because without that
patch the faction box would read `FactionX:1` as a faction named so.

Refusing a base faction greys its Standard row only. The faction box, which the stock fill builds,
greys and locks the base the same way, so a seat cannot move into that family through it; a seat
already on one of its variants keeps a Variant box whose permitted variants stay pickable. The
faction's Random row is not filtered: in a historical scenario the fixup (`0x008445F2`) replaces
any negative template with a template the scenario allows that seat; outside one, where a War of
the Ring seat's Random sentinel is settled has not been traced.

## 6. The movie

The engine only files a Variant box if the movie places one. `MpGameSetup.apt` draws all eight
rows from one sprite, and each box in it is an empty clip placed with a name and the clip action

```
_type = "ComboBox"; _Init = "MpGameSetup::InitGadgets"; _Load = "Apt/ComboBox.wnd"
```

so the box is a copy of the `PlayerTemplate` placement renamed `Variant`. pySAGE-edain's
`tools/add_variant_boxes.py` makes it and re-lays out the row.

Without the box, and with `VariantOf` declared, variants are filtered out of the faction list and
cannot be picked. The patch is inert without any `VariantOf` - every "variant" test answers no.

## 7. What is not covered

**Only the skirmish lobby has been seen in game, and only up to the first pick.** Every routine runs under unicorn against a
stand-in engine (`test_faction_variants_emulated.py`), and the patch applies, verifies, and
composes with `scenario-player-factions`, `command-point-upkeep` and the rest of Edain's manifest.
What only a play session settles:

1. **The pick, since the fix above.** The crash was seen in game; the build without the rebuild has
   only run under the emulator.
2. **The online lobby.** `AptOnlineCustomMatch` has its own movie and its own fill (the
   `PlayableSide` tests at `0x009CA843` and `0x009F066A`) and is untouched: there, variants still
   appear in the flat list.
3. **War of the Ring.** The historical-scenario fixup (`0x008445F2`) makes each player take a
   *different* template; a faction and its variant are different templates, so two players can
   field the same faction. Its Random pass (`0x008448E1`) is not filtered for variants either,
   though it does ask the scenario, per seat with `scenario-player-factions`. The Variant box's
   reading of `DisabledFactions` (§5) is emulated only: no War of the Ring lobby has been opened
   with it.
4. **The layout.** The row is full, so the Variant box takes its width from the Faction and Hero
   columns. The scales are a first guess.
5. **Random pools.** Emulated only, like the rest: the draw, the parser and request checks, the
   `SetRandomPool` command and its registration, the lobby's reading of a pool, and the LAN
   transport. The movie half is pySAGE-edain's `tools/add_random_pool_panel.py`. A replay of a
   pooled match should draw the same faction; that hasn't been tried. The start-position fix
   (`0x00802D55`) changes what picking Good, Evil, Variants or a faction's Random does in a lobby,
   and that hasn't been seen in game either.
6. **`EnabledForPvP` and the rule.** Emulated only. Unseen: that the third checkbox appears with
   its label in skirmish and in the LAN lobby, that only the host can tick it, that a LAN client's
   Variant boxes follow when the host ticks or clears it (the lobby has to refill them on a rules
   change, which this patch assumes rather than hooks), and that a match drops a held-back seat to
   its faction on every peer.

## 8. Addresses

In [`../addresses/`](../addresses/__init__.py): `MP_SETUP_GADGET_*`, `MP_SETUP_FACTION_*`,
`MP_SETUP_SYNC_FACTION*`, `MP_SETUP_SELECTION_*`, `MP_SETUP_CTOR_FACTION_WINDOWS_CLEAR`,
`MP_SETUP_REDRAW_SLOT`, `MP_SETUP_STRATEGY*`, `GAME_RULES_NAMES`, `GAME_RULES_CLAN_GAME_*`,
`GAME_INFO_RULE_CLAN_GAME`, `INI_PARSE_BOOL`, `COMBO_BOX_*`, `WINDOW_ENABLE` / `WINDOW_HIDE` /
`WINDOW_STATUS*`, `THE_PLAYER_TEMPLATE_STORE`, `PLAYER_TEMPLATE_FIND_BY_INDEX`,
`PLAYER_TEMPLATE_PARSED_*`, `PLAYER_TEMPLATE_GET_DISPLAY_NAME` and `GAME_START_RANDOM_POOL*`.
