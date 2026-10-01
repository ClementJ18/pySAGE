# Sending a lobby seat's faction past the 14th `PlayerTemplate`

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read statically from the
stock `game.dat`. The patch is `lobby-faction-byte` (`patches/lobby_faction_byte.py`).

**The bug.** The LAN lobby host broadcasts the whole `GameInfo` in a binary form, and that form
packs each seat's colour and faction into one byte, a nibble each. A faction at
`PlayerTemplate` index 14 or later doesn't fit, and the overflow carries into the colour. The host
keeps its own `GameInfo` and is unaffected. Every client decodes the overflowed byte, so the host
and the clients see a different lobby. It surfaced with
[`skirmish-ai-fallback`](skirmish-ai-fallback.md): once any faction can be an AI, Edain's later
factions get picked and the overflow shows up.

**Status.** Static, plus emulated: all four arms run under unicorn, stock and patched. It hasn't
been tried in a lobby yet.

## 1. Where the byte is built and read

Two LAN messages carry the binary `GameInfo`:

| message | sent at | payload |
|---|---|---|
| `MSG_GAME_OPTIONS_PACKED`, type `0x13` — the host's lobby broadcast | `0x0084C4D8` (in `0x0084C4A1`) | `[msg+0x1E]`, `0x186` bytes |
| `MSG_GAME_ANNOUNCE`, type 1 | `0x00989E20` | `[msg+0x42]`, `0x186` bytes |

Both type names come from the message-name switch at `0x0084C96B` (table `0x0084CAE4`). Both messages fill their payload
with **`LAN_GAME_INFO_PACK`** (`0x0084A976`) and read it back with **`LAN_GAME_INFO_PARSE`**
(`0x0084B0EC`). After a header (the map path, CRC and size, the ten `GR` rules, seed and so on), the
packer writes the eight seats. An occupied seat goes through one of two arms: a human (`H`, with
name, IP and port) or an AI (`E`/`M`/`H`/`B` by difficulty). Both arms write colour and faction the
same way:

```
0084ab40  mov ecx, [esi+0xc]        ; colour            (human arm; the AI arm is 0x0084abee)
0084ab43  push -2
0084ab48  mov eax, [esi+0x18]       ; playerTemplate
0084ab4b  push -1
0084ab4d  push eax
0084ab4e  push ecx
0084ab4f  call 0x009738a5           ; LAN_PACK_NIBBLES(colour, template, -1, -2)
0084ab54  mov [ebp-0x24], al
...
0084ab5e  call 0x0084a537           ; LAN_WRITE_BYTE(cursor, packed, end)
```

```
009738a5  mov al, [esp+4]           ; colour
009738a9  sub al, [esp+0xc]         ;   - (-1)
009738ad  shl al, 4
009738b0  sub al, [esp+0x10]        ;   - (-2)
009738b4  add al, [esp+8]           ;   + template
```

So the wire byte is `((colour + 1) << 4) + (template + 2)`. The combine is an **add**, not an or:
template 14 adds 16 and bumps the colour nibble by one. `LAN_UNPACK_NIBBLES` (`0x009738B9`) is the
exact inverse, `colour = (b >> 4) - 1`, `template = (b & 0xF) - 2`, written to two signed bytes.
The parser calls it at its human arm (`0x0084B473`) and its AI arm (`0x0084B76A`).

| sent | wire | a client reads |
|---|---|---|
| colour 0 (blue), template 13 | `0x1F` | colour 0, template 13 |
| colour 0 (blue), template 14 | `0x20` | **colour 1 (red), template -2 (Observer)** |
| colour 0 (blue), template 15 | `0x21` | colour 1 (red), template -1 (Random) |

`-2` is Observer and `-1` is Random ([`game-info.md`](game-info.md)), so the first overflowed
faction turns a client's view of that seat into an observer in the next colour.

**Nothing else is limited.** The parser range-checks both values with `movsx` against the colour
count (`[0x00DE7D3C]+0x40`) and the template count (`ThePlayerTemplateStore` span / `0x1DC`), so
both checks already work on bytes. `GameSlot` holds both as 32-bit ints. The other lobby paths use
ASCII: the client's own change requests (`PlayerTemplate = 5`) and `GameInfoToAsciiString` /
`ParseAsciiStringToGameInfo` (`0x008023C1` / `0x00802DBA`, the replay header and `Skirmish.ini`).
None of them goes through the nibble helpers.

**The four sites are the whole format.** `LAN_PACK_NIBBLES` has three callers: the two packer arms
and `0x00800A4E`. `LAN_UNPACK_NIBBLES` also has three: the two parser arms and `0x008012C2`. The
extra pair packs a different slot field (`+0x50`/`+0x54`/`+0x58`, the one `0x00801289` sets) and
never touches colour or faction. `LAN_GAME_INFO_PARSE` has one caller (`0x0084C00D`). A scan of
`0x00800000`–`0x00870000` for `shr`/`sar …, 4` and `and …, 0xF` finds no inline unpack.

## 2. What the patch does

It writes colour and template as two signed bytes, and changes nothing else. Each of the four hooks
is a single `call` retargeted into a `.lobfac` section:

| arm | call at | stock target | now calls |
|---|---|---|---|
| packer, human | `0x0084AB5E` | `LAN_WRITE_BYTE` | `write` |
| packer, AI | `0x0084AC0C` | `LAN_WRITE_BYTE` | `write` |
| parser, human | `0x0084B473` | `LAN_UNPACK_NIBBLES` | `read` |
| parser, AI | `0x0084B76A` | `LAN_UNPACK_NIBBLES` | `read` |

**`write`** has `LAN_WRITE_BYTE`'s cdecl signature `(cursor, byte, end)`, so the caller's deferred
`add esp` still balances. It ignores the packed byte. The seat is still in `esi`, so it calls
`LAN_WRITE_BYTE` twice, with `[esi+0xC]` and then `[esi+0x18]`, and returns the cursor past both.
The stock `LAN_PACK_NIBBLES` call before it still runs, and its result is thrown away.

**`read`** has `LAN_UNPACK_NIBBLES`'s signature `(byte, -1, -2, &colour, &template)`. The byte the
stock code has just read becomes the colour. The arm keeps its cursor in `ebx`, the last checked
cursor at `[ebp-0x14]` and the payload end at `[ebp-0x10]`, in the same slots in both arms. If
`ebx < end`, `read` takes the template from `[ebx]` and advances both `ebx` and `[ebp-0x14]`. The
arm's next read (`0x0084B4E2` / `0x0084B7D9`) pushes `ebx` and checks against `[ebp-0x14]`, so it
continues after the new byte. If the payload ended first, the template is left at `-128`. The arm's
own `cmp byte [template], -2 / jl 0x0084B9B5` then rejects the message, the same way it rejects any
other bad field.

Both sides now hold colour -128..127 and template -128..127, far beyond anything a mod defines.

## 3. Costs and limits

- **Every peer in the lobby needs the same binary.** A stock peer reads the patched host's colour
  byte as the packed pair and is then one byte out of step for the rest of the payload. The parser's
  range checks usually reject such a message outright. This is the same rule as every
  logic-side patch.
- **The payload grows by one byte per occupied seat**, so up to 8 more bytes, still inside the fixed
  `0x186`. A human seat costs 37 bytes (36 stock). The header costs 63 bytes plus the
  NUL-terminated map path, so a full house of 8 humans fits a map path of 30 characters (38 stock).
  An AI seat is 7 bytes. The cap is not new: the writer truncates the map path to fit, and any later
  field that doesn't fit is **silently dropped**. The 37-byte figure comes from the arm's own writes
  (a kind byte, a 22-byte name, IP, port, flags, then five bytes). The real map-path form, from
  `0x0080204C`, hasn't been measured.
- **The online (GameSpy) lobby is not covered.** No path besides the LAN messages above reaches the
  packer. If the online staging room has a binary form of its own, it is a separate finding.

## 4. How to test it

1. **Static and emulated.** `tests/sage_patch/test_lobby_faction_byte.py` asserts every arm's stock
   window, apply/verify/detect, and the cave listing. It then runs the real arms under unicorn,
   together with the engine's byte writer, its block copy and the nibble helpers. Patched, each arm
   round-trips colour/template pairs up to template 21. Stock, template 14 on blue reads back as an
   observer on red. A payload that ends after the colour byte is turned away.
2. **In a LAN lobby.** Two machines, both patched. The host sets an AI or a human seat to a faction
   at index ≥ 14. The client should show that faction in the host's colour. Unpatched, the client
   shows an observer in the next colour.
3. **Negative.** A faction below 14 should look identical on both sides, patched or not.
