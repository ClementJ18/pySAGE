# Upgrade-complete notice for unnamed upgrades

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR).

- **Cost:** one 11-byte window becomes a `call` and six `nop`s, plus a 47-byte `.upgmsg` cave.
- **Effect:** an upgrade with no `DisplayName` no longer posts `MISSING: ""` to the top-right
  message area when it completes. Everything else about the completion is unchanged.
- **Scope:** client-side only (the notice is only ever built for the local player). No INI change.

```
sage-patch apply upgrade-complete-skip-unnamed --in game.dat.backup --out game.dat
```

## The notice

When a `ProductionUpdate` finishes an upgrade entry it runs a block for the local player only
(`Object::isLocallyControlled` at `0x008A2083`). `edi` is the `UpgradeTemplate` throughout:

```
008a209e  push 0xc67fa4               ; "UPGRADE:UpgradeComplete"
008a20ae  call [eax+0x3c]             ; TheGameText->fetch -> [ebp-0x4c]
008a20b1  mov  eax, [edi+0x28]        ; DisplayName, an AsciiString label
008a20d5  call [edx+0x3c]             ; TheGameText->fetch -> [ebp-0x30]
008a20ff  call 0xadf750               ; UnicodeString::format -> [ebp-0x18]
008a2104  pop ecx / pop ecx           ; two of the three format arguments: one dword stays
008a210f  call 0x436990               ; copy [ebp-0x18] into that dword (a by-value argument)
008a2114  mov  eax, [0xde4830]        ; TheInGameUI
008a2119  mov  ecx, [eax]
008a211b  push eax                    ; this
008a211c  call [ecx+0x40]             ; InGameUI::message(fmt, ...) - the top-right line
008a211f  fld  ...                    ; the radar event at the object
008a212e  add  esp, 4                 ; pops `this`; the string slot is reused for the float
008a213f  ...                         ; ResearchCompleteEvaEvent, then the two upgrade sounds
```

`TheGameText->fetch` returns `MISSING: "<label>"` for a label the string table lacks, so an
upgrade with no `DisplayName` fetches the empty label and the notice reads `MISSING: ""`.
`InGameUI::message` is variadic, so it is `__cdecl` with `this` on the stack. The callee destroys
the by-value format string, and the caller pops `this`.

## The patch

The 11 bytes at `0x008A2114` (`mov` / `mov` / `push` / `call`) become `call message_or_skip` and
six `nop`s. Nothing branches into the window, and `eax`, `ecx` and `edx` are all rewritten before
they are next read. The cave:

- **`DisplayName` set** (non-NULL, first character non-zero): loads `TheInGameUI` and its vtable as
  the stock bytes did, swaps its own return address under `this`, and tail-jumps to `+0x40`.
  `message` sees exactly the stack the stock call gave it and returns to `0x008A211F`.
- **`DisplayName` empty or absent:** calls `UnicodeString::~UnicodeString` (`0x004367B0`) on the
  argument slot, since `message` would have destroyed it. Then it leaves one dword above the slot,
  as `push this` / `call` did, and returns. The caller's `add esp, 4` pops that dword and reuses
  the slot as before.

So an unnamed upgrade still gets its radar event, its EVA event and its sounds; only the text line
goes.

## Not covered

- An upgrade whose `DisplayName` names a label missing from the string table still shows
  `MISSING: "<label>"`: that is a data error the message points at, not an unnamed upgrade.

## Addresses

| VA | meaning |
|---|---|
| `0x008A209E` | `push "UPGRADE:UpgradeComplete"` (pinned) |
| `0x008A2114` | the `TheInGameUI->message` call (hooked, 11 bytes) |
| `0x008A211F` | where it returns |
| `0x00DE4830` | `TheInGameUI`; vtable `+0x40` `message(fmt, ...)` |
| `UpgradeTemplate+0x28` | `DisplayName` (`AsciiString`, chars at `+8`) |
| `0x004367B0` | `UnicodeString::~UnicodeString` |
