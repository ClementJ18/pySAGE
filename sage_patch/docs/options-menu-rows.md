# Adding a row to the shell Options screen

Recovered against RotWK 2.01 `game.dat` build `2.01.2614.37001`, 2026-08-24, from a stock binary
(`sage-patch sagepatch` reports no known patch). Static analysis of the binary plus a decompile of
the stock `apt/options.big` with [`sage_apt`](../../sage_apt/README.md). **Nothing here has been
confirmed against a running game yet** — §7 is the test that would.

**The finding in one sentence.** The Options screen's row list belongs to the **APT movie**, not to
the engine: each gadget clip carries its own option id as its instance name and names the C++
handler it wants, and the engine side is a passive `name -> handler` chain of `stricmp`s — so a new
option is one `<placeobject>` in `Options.apt` plus one arm appended to that chain.

## 1. Why this is not an engine table

The obvious guess is wrong. There is no descriptor array of option rows, no `{name, type, getter,
setter}` table to extend. `AptOptions::InitGadgets` (`0x009205c4`) is a **19-arm if/else-if ladder**
of inlined string compares, and the names it compares against are pushed as bare literals:

```asm
00920a2f  68 f0d7c700     push 0xc7d7f0            ; "Options::HealthBars"
00920a34  ff 7508         push [ebp + 8]           ; the incoming gadget name
00920a37  e8 04c51100     call 0xa3cf40            ; stricmp
00920a3c  85 c0           test eax, eax
00920a40  75 12           jne  0x920a54            ; -> next arm
00920a42  8b cf           mov  ecx, edi
00920a44  89 b7 bc020000  mov  [edi + 0x2bc], esi  ; remember the gadget
00920a4a  e8 82e1ffff     call 0x91ebd1            ; seed it from the preference
00920a4f  e9 9e030000     jmp  0x920df2            ; -> shared epilogue
```

Because the ladder is inlined, "add a row" means "add an arm", which means a code cave. That is the
whole cost on the engine side, and it is small — see §5.

## 2. The dispatcher

| | |
|---|---|
| entry | `0x009205c4` (`mov eax, 0xbaa2e4` / `call __SEH_prolog` at `0xa3cef0`) |
| last byte | `0x00920e0c` (`ret 0xc`) |
| shared epilogue | `0x00920df2` |
| early-out (null gadget) | `0x00920dfe`, taken at `0x009205dd` |

Signature, read off the prologue:

```
AptOptions::InitGadgets(this  /* ecx -> edi */,
                        name  /* [ebp+8]   -> arg 1, the gadget's instance name */,
                        ?     /* [ebp+0xC] -> arg 2, a UnicodeString, destructed at 0x920df9 */,
                        gadget/* [ebp+0x10]-> esi */)
```

`esi` is the gadget and is stored verbatim into a fixed field on the `AptOptions` object; a NULL
gadget skips the whole body. `Options::Resolution` is compared first, ahead of the ladder, because
its arm is long (it parses the stored `"%d%d"` resolution string, `0xc1b274`); everything else falls
through to `0x00920791`.

### The 19 arms, in ladder order

`field` is the `AptOptions` offset the gadget pointer is written to. Two arms store nothing.

| # | site | option id | field | on no match |
|---|---|---|---|---|
| — | `0x009205ec` | `Options::Resolution` | `0x2ac` | `0x920791` |
| 1 | `0x00920791` | `Options::Detail` | — | `0x9208d5` |
| 2 | `0x009208d5` | `Options::MusicVolume` | `0x2e4` | `0x920908` |
| 3 | `0x00920908` | `Options::SoundFxVolume` | `0x2dc` | `0x920930` |
| 4 | `0x00920930` | `Options::VoiceVolume` | `0x2e0` | `0x920959` |
| 5 | `0x00920959` | `Options::AmbientVolume` | `0x2e8` | `0x920985` |
| 6 | `0x00920985` | `Options::MovieVolume` | `0x2ec` | `0x9209b1` |
| 7 | `0x009209b1` | `Options::Brightness` | `0x2f4` | `0x9209df` |
| 8 | `0x009209df` | `Options::ScrollSpeed` | `0x2f0` | `0x920a2f` |
| 9 | `0x00920a2f` | `Options::HealthBars` | `0x2bc` | `0x920a54` |
| 10 | `0x00920a54` | `Options::AlternateMouseSetUp` | `0x2c0` | `0x920a8b` |
| 11 | `0x00920a8b` | `Options::OnlineIp` | `0x2b4` | `0x920ba3` |
| 12 | `0x00920ba3` | `Options::OnlinePortNum` | `0x2b8` | `0x920c61` |
| 13 | `0x00920c61` | `Options::Firewall` | — | `0x920ca6` |
| 14 | `0x00920c78` | `Options::SendDelay` | `0x2c4` | `0x920ca6` |
| 15 | `0x00920ca6` | `Options::DisplayForeignLanguage` | `0x2cc` | `0x920cd4` |
| 16 | `0x00920cd4` | `Options::TurnOffMessengerInGame` | `0x2c8` | `0x920d24` |
| 17 | `0x00920d24` | `Options::FilterLanguage` | `0x2d0` | `0x920d66` |
| 18 | `0x00920d66` | `Options::EAX3` | `0x2d4` | `0x920da8` |
| 19 | `0x00920da8` | `Options::HighAudioQuality` | `0x2d8` | **`0x920df2`** |

The gadget-pointer block is contiguous, `+0x2ac` .. `+0x2f4`. **It does not have room to grow**:
`+0x2f8` is a live `Bool` and `+0x2fc` a live pointer, both read at `0x0091ef48`/`0x0091ef8f`. A new
row should keep its gadget pointer in its own cave global rather than extend the object — there is
one Options screen at a time, so a single global is sufficient, and it avoids resizing an allocation
whose `operator new` size would also have to be found and patched.

## 3. How the handler is reached

`AptOptions::InitGadgets` is a **name**, not a symbol. It is registered as a callback: at
`0x00921269` the literal `0xc7d5ac` (`"AptOptions::InitGadgets"`) is paired with the function
pointer `0x009205c4` and handed to the named-function registry at `0x00de8a14`:

```asm
00921269  68 acd5c700     push 0xc7d5ac            ; "AptOptions::InitGadgets"
0092126e  8d 4d08         lea  ecx, [ebp + 8]
00921271  be c4059200     mov  esi, 0x9205c4       ; <- the handler
00921278  e8 6362b1ff     call 0x4374e0            ; AsciiString ctor
0092127d  89 75d0         mov  [ebp - 0x30], esi   ; delegate = {fn, 0}
```

The same registry backs `0x008141c3` (call by name, no args) and `0x00814181` (call by name, with
args). Six more `AptOptions::*` names register the same way — `OnInitialized` (`0x0092106d`),
`Save` (`0x009210c0`), `Reset` (`0x00921115`), `Cancel` (`0x0092116a`), `RefreshNat`
(`0x009211bf`), `EnterAdvancedSettings` (`0x00921214`).

## 4. The movie owns the row list

Each gadget in `Options.apt` is a `placeobject` whose **instance name is the option id** and whose
clip actions declare the gadget type, the `.wnd` skin, and the C++ init callback by name:

```xml
<placeobject depth="13" character="98" tx="-99.800003" ty="230.05" ...>
  <poflags value="HasCharacter|HasClipActions|HasMatrix|HasName"/>
  <poname name="Options::HealthBars"/>
  <clipactions>
    <clipaction flags="512" flags2="0">
      <pushstring str="_type"/>            <setstringvar str="CheckBox"/>
      <pushstring str="_Load"/>            <setstringvar str="Apt/CheckBox.wnd"/>
      <pushstring str="_Init"/>            <setstringvar str="AptOptions::InitGadgets"/>
      <pushstring str="_CheckBoxString"/>  <setstringvar str=""/>
      <end/>
    </clipaction>
  </clipactions>
</placeobject>
```

`character="98"` is the imported `CheckBox` from `GameWindowGadgets`; sliders use `130`
(`HorzSlider`), drop-downs `99` (`ComboBox`), text fields `100` (`TextEntry`).

**The two lists are not the same length.** The shipped movie names only 15 gadgets, so five arms in
§2 are reachable only by a movie that declares them — `AlternateMouseSetUp`, `Firewall`,
`DisplayForeignLanguage`, `TurnOffMessengerInGame`, `FilterLanguage` are **unreachable in stock
RotWK**. It is tempting to revive one as a free toggle that costs no `.text` edit at all. **That
does not work**, and §6a says why: four of the five are never written back, and the fifth is not
actually dead.

Labels are separate `edittext` characters holding a `$Key` string-table reference, resolved against
`APT:<key>` (case-insensitively) in the localisation table:

```xml
<edittext id="146" ...><ettext text="$EnableHealthBars"/><etvar variable=""/></edittext>
```

→ `APT:enablehealthbars;Alle Gesundheitsleisten einbl.;Show All Health Bars` in Edain's `Lotr.csv`.
Tooltips ride a parallel key, `TOOLTIP:options/tooltip<key>`, attached to a `tooltips<Name>` clip
(`tooltipsEAX3`, `tooltipsHighAudioQuality`, `tooltipsSendDelay` in the stock movie).

**`Options.apt` round-trips byte-exact** through `sage_apt to-xml` / `to-apt` (`sage-apt check
Options.apt` → `1/1 ok`), so the movie half of a new row is an XML edit, not a binary one.

### The movie half, built and validated

Adding a row is **three XML blocks**, and the result recompiles and survives a second decompile
(`sage-apt check` → `1/1 ok`, and the row reads back at the position it was given):

1. the checkbox — the `Options::HealthBars` `placeobject` above, at a free depth on the same page
   (`17`), moved down one slot (`ty="270.04999"`), renamed `Options::UnitPlates`;
2. a label character appended past the last one (the stock movie ends at `293`, so `id="294"`),
   copying `edittext` `146`'s geometry and colours with `<ettext text="$EnableUnitPlates"/>`;
3. a `placeobject` for that label beside the checkbox — depth `26`, `tx="-63.950001"`,
   `ty="276.5"`, matching the `$EnableHealthBars` label 40px above it.

The Graphics page's left column runs `Brightness` (169/197), `HealthBars` (230/236), `ScrollSpeed`
(316/344), so `270/276` is the free slot between the second and third with no reflow.

[`scripts/options_add_row.py`](../scripts/options_add_row.py) does all three against a stock
`apt/options.big` and re-checks the round-trip:

```sh
python sage_patch/scripts/options_add_row.py "C:/RotWK/apt/options.big" --out build/options
```

It writes the loose movie files a mod's `apt/` folder wants. Note the archives use **two** magics -
`apt/*.big` are `BIGF`, the `.big`s at the game root are `BIG4`.

Then `APT:enableunitplates` goes in `Lotr.csv` (DE and EN), and
`TOOLTIP:options/tooltipenableunitplates` beside it if the row wants a tooltip.

**Do not ship the movie before the engine arm.** A gadget the ladder does not recognise is an inert
checkbox: nothing seeds it, nothing saves it, and it silently reverts every time the screen opens.

## 5. Where a new arm goes

The last arm's no-match branch is the only site that has to move:

```asm
00920db9  75 37           jne 0x920df2      ; "HighAudioQuality" didn't match -> epilogue
```

Retarget it into a cave, compare `[ebp+8]` against the new literal, handle it, and `jmp 0x920df2`
either way. Existing rows are untouched, the shared epilogue is untouched, and nothing in the
function moves — the ladder is extended at its tail, which is the one place extension is free.

The `stricmp` at `0xa3cf40` is `(const char *a, const char *b)` with both operands pushed right to
left and the caller popping two dwords.

## 6. Persistence

Preference values live in `Options.ini` under the user data folder, read and written through a
generic string map. `OptionPreferences` accessors are one-liners that construct the key and index
the map at `this+4` — `getAllHealthBars` is `0x006e6179`:

```asm
006e6179  55              push ebp
006e617f  8b f1           mov  esi, ecx
006e6181  68 b8b2c100     push 0xc1b2b8            ; "AllHealthBars"
006e6186  8d 4dfc         lea  ecx, [ebp - 4]
006e6189  e8 5213d5ff     call 0x4374e0            ; AsciiString ctor
006e6191  83 c604         add  esi, 4              ; -> the map
```

`0x006e56f3` returns the live `OptionPreferences`; `0x006e562f` releases it. The key strings sit
together at `0xc1b150`..`0xc1b340`, so a **new key is a new literal in a cave**, not a table edit.

## 6a. Save persists six preferences, not nineteen

`AptOptions::Save` writes each option by re-reading its stored gadget and assigning into the
`OptionPreferences` map — the `AllHealthBars` instance is at `0x0092001C`:

```asm
0092006d  8b 87 c0020000  mov  eax, [edi + 0x2c0]  ; the gadget this arm remembered
00920073  85 c0           test eax, eax
00920075  74 0c           je   0x920083            ; no gadget -> -1, "nothing to save"
00920077  50              push eax
00920078  e8 fc94e0ff     call 0x729579            ; getCheckBoxState(gadget) -> al
```

`0x00729579` reads a checkbox and `0x00729534` sets one; the value is written as a string into the
map through `operator[]` (`0x00602B76`) and `AsciiString::operator=` (`0x00436030`).

Only **six** keys are pushed anywhere in the whole options band (`0x0091E000`..`0x00922000`):

| key | arm |
|---|---|
| `Brightness` | 7 |
| `ScrollFactor` | 8 |
| `AllHealthBars` | 9 |
| `AlternateMouseSetup` | 10 |
| `UseEAX3` | 18 |
| `SendDelay` | 14 |

plus the resolution, written through `"%d%d"` at `0x00920E88`.

**So the hijack is a dead end.** `TurnOffMessengerInGame`, `DisplayForeignLanguage`,
`FilterLanguage` and `Firewall` are seeded but never saved — a checkbox on one of them forgets
itself the moment the screen closes. And `AlternateMouseSetUp`, the one unreachable arm that *is*
saved, is not dead at all: its accessor `0x006E61D4` has a second caller at `0x00641E72`, which
stores the value into `[esi+0x5C]` during a subsystem's init. Repurposing it would flip whatever
that field gates.

**A genuinely new row therefore costs three hooks, not one:**

1. **The ladder**, per §5 — but hook the *head*, not the tail. `0x00920602`
   (`0f 85 89010000`, `jne 0x920791`) is six bytes and the flags from the `Options::Resolution`
   `test eax, eax` survive an unconditional `jmp`, so a cave can re-test them, answer for its own
   name, and fall through to `0x00920608` (the Resolution body) or `0x00920791` (the ladder) —
   both instruction boundaries in stock code. The tail's `jne` at `0x00920DB9` is only two bytes
   and cannot hold a `jmp rel32`.
2. **The seed**, in that same arm: remember the gadget in a cave global (not an `AptOptions`
   field — §2 says the block has no room), then `setCheckBoxState(gadget, pref)` the way arm 19
   does at `0x00920DA8`. Read the preference *fresh* here rather than from any launch-time cache,
   or the box shows a stale value after a save-and-reopen.
3. **The save**, inside `AptOptions::Save`, where an `OptionPreferences` is already live in the
   frame at `[ebp-0x30]`: `getCheckBoxState` the remembered gadget and assign the string into the
   map under the new key.

[`unit-plate-option`](../patches/unit_plate_option.py) implements all three, in one cave alongside
its model gate. Its `verify` rebuilds that cave from the parameters `detect` recovers, so the row's
name, key and model are checked together rather than assumed.

## 7. What would confirm this

Not yet run. In order of value:

1. Give an existing clip the instance name `Options::TurnOffMessengerInGame` (unreachable arm 16,
   no `.text` change) and check the checkbox *appears* and seeds itself from `Options.ini`. It will
   not survive a Save — §6a — but that is not what this step is testing: it proves §1, §3 and §4,
   that the movie owns the row list, without writing a byte to the binary.
2. Then the three hooks of §6a, which is what a shipping row needs.

Until step 1 runs, the claim "the movie owns the row list" rests on the decompile plus the
registration at `0x00921269`, which is strong but is still only a reading of the machine code.
