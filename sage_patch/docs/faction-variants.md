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
carries a template as a signed byte, which bounds the index at 112 (-128); a faction past that
gets no Random row.

-3 to -6 and `-16 - index` have to get through every reader that bounds a template from below at -2, or
the value is refused - the whole lobby string, the request, the packet:

| site | reader |
|---|---|
| `0x0080351C`, `0x0080385B` | `ParseAsciiStringToGameInfo`, both slot kinds |
| `0x0064A271` | the LAN host applying a client's `PlayerTemplate` request |
| `0x0084B4A6`, `0x0084B79D` | the two LAN packet readers (the template travels as a signed byte) |

Each is a one-byte edit of the immediate, `-2` to `-128`. The online lobby's reader (`0x009AD961`)
is left alone: that screen has no Variant box. A sweep of every `cmp <template>, -1` and `-2` in
the image found one more reader that would misread it: the map preview's start-position numbers
(`0x007053DE`, `0x00705457`) skip observers with `cmp [slot+0x18], -2` / `jle`, which would hide a
-3 slot's number too, so both `jle` become `je`. Every other test is an `== -2` for Observer or a
`< 0` for "not a real template", and -3 passes both as -1 does.

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
| `0x0062D6D8` | a slot on Good (-5) or Evil (-6) draws only from candidates of that side |
| the five bounds of §3, `0x007053E2`, `0x0070545B` | -3 to -6 survive the lobby string, LAN and the map preview |

The fill and the sync are wrapped at their calls rather than hooked at their entries because
`scenario-player-factions` asserts both entries' bytes; the byte-wise `e8` sweep in
`test_the_wrapped_calls_are_every_call` confirms those are every caller.

The **Variant box** is rebuilt from the slot every time its faction box is: empty unless the slot's
faction has a playable variant, and then the faction first - labelled `GUI:FactionVariantStandard`
- followed by its variants in store order, each row carrying its template index as the faction
box carries. The first row's text is `GUI:FactionVariantStandard` formatted with one `%s`, the
faction's display name, through `UnicodeString::format` (`0x00ADF7E0`): a label of `Standard`
ignores it, `%s (Standard)` shows it, and anything but `%s` would read an argument that is not
there. Every faction's box leads with a Random row (`-16 - index`, `GUI:Random`). On a Random
slot the box holds Random (-3, `GUI:Random`) and Standard (-1, the same label
formatted with `GUI:Random`'s text), then Variants (-4) when the mod has a variant, and Good (-5)
and Evil (-6) when it has base factions on both sides. The faction box shows every one of these as
Random. A faction with no variant gets the Standard row alone. The box is shown when it lists anything
and its faction box is not hidden, and
enabled when its faction box is, which is what makes another player's variant visible and
read-only. An enabled box also has its drop-down button enabled: the combo box gadget keeps
that button disabled - drawn without its arrow - while it lists fewer than two rows, which is every
faction without variants. `winEnable` (`0x007154B3`) enables the window and its children and then
sends the gadget `0x1C`, whose handler (`0x0072493B`) returns early only for more than one entry
and otherwise disables the button (`[data+0x24]`, the data being the window's `+0x2C`); adding an
entry to an enabled box re-enables it for `count > 1` (`0x00724D32`). So the button is enabled
again after the box is, and the arrow shows as every other column's does. A list of one still does
not open (`0x00724513`), so the arrow there is only the column's look.

A **pick** in it is `0x00844177` with the index read from the Variant box: the same "request
pending" byte (`+0x2C4`) cleared, the same strategy call, the same War of the Ring flags on success
(`+0x2BF`, `+0x2C2`, `+0x2B9`, `+0x2BE`, when the screen is in mode 1 and the scenario is
historical), the same redraw. Skirmish, LAN host and LAN client therefore each do what they already
do for the faction box.

The pick does **not** rebuild the box. It runs inside the box's own `0x4026`, and a combo box
reset from its own notification has its rows pulled out from under it - the first build did this
and crashed the game on the first pick. `0x00843B4C` does not refill the faction box either (it
calls the per-slot control update `0x00842C93` and the hero box's `0x0084040D`); both boxes are
refilled by the screen's next update. The fill wrapper keeps the Variant box's own pick while it
is a member of the slot's faction, as the stock fill keeps the faction box's, and the sync wrapper
forces the slot's template - so a LAN client's pick stays on screen until the host answers.

Picking a faction in the faction box resets the variant to that faction, since the handler asks
for the base's index.

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
   field the same faction. Its Random pass (`0x008448E1`) is not filtered either.
4. **The layout.** The row is full, so the Variant box takes its width from the Faction and Hero
   columns. The scales are a first guess.

## 8. Addresses

In [`../addresses/`](../addresses/__init__.py): `MP_SETUP_GADGET_*`, `MP_SETUP_FACTION_*`,
`MP_SETUP_SYNC_FACTION*`, `MP_SETUP_SELECTION_*`, `MP_SETUP_CTOR_FACTION_WINDOWS_CLEAR`,
`MP_SETUP_REDRAW_SLOT`, `MP_SETUP_STRATEGY*`, `COMBO_BOX_*`, `WINDOW_ENABLE` / `WINDOW_HIDE` /
`WINDOW_STATUS*`, `THE_PLAYER_TEMPLATE_STORE`, `PLAYER_TEMPLATE_FIND_BY_INDEX`,
`PLAYER_TEMPLATE_PARSED_*`, `PLAYER_TEMPLATE_GET_DISPLAY_NAME` and `GAME_START_RANDOM_POOL*`.
