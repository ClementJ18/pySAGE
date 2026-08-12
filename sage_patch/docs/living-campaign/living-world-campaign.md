# Scripted Living World campaigns in RotWK

Engine build `2.01.2614.37001`, ImageBase `0x400000`. Addresses verified against the installed
`C:\Program Files (x86)\Games\bfme\rotwk\game.dat`; data claims against the install's `.big`
archives; BFME1 comparisons against `C:\BFME1\lotrbfme.exe`. **Confirmed in game on 2026-08-11.**

- **Status:** **working.** Edain's twelve-act `WOTRScenarioAngmar` ran start to finish, advancing
  act by act with no End Turn, observed live through the `live-bridge` patch.
- **Cost:** one four-byte patch ([`living-world-override`](../patches/living_world_override.py))
  plus two INI changes on the campaign.

## The result

```
campaign idx=13  act=0/11  scripted=1
>>> ACT ADVANCED: 0 -> 1
>>> ACT ADVANCED: 1 -> 2          ... every act in sequence ...
>>> ACT ADVANCED: 9 -> 10
```

The Living World campaign layer is not missing from RotWK and was never stripped out. What was
missing was a way to *name* the campaign you wanted, and that was one wrong pointer in a field
table.

## The recipe

Three things, only one of which is a patch.

**1 — Mark the campaign scripted.**

```
LivingWorldCampaign WOTRScenarioAngmar
    IsScriptedCampaign = Yes
```

`campaign+0x58`. It is read inside `0x00932EB8`, one of the two state builders
`LivingWorldCampaign::begin` calls, where it **inverts a ~550-byte block**:

```asm
00932ED5  mov  al, [edi+0x58]        ; IsScriptedCampaign
00932ED8  test al, al
00932EDA  jne  00933109              ; SET -> skip everything below
00932EE0  mov  esi, [TheGameLogic]   ; CLEAR -> initialise from...
00932EF1  mov  eax, [TheGameInfo]        ; ...the multiplayer GameInfo
00932F05  mov  eax, [TheSkirmishGameInfo]
```

Clear, the campaign is populated from the **skirmish/multiplayer lobby** — which is why an
unmarked campaign behaves like a War of the Ring match with acts bolted on. Set, that is skipped
and the campaign supplies its own participants, which is what makes it a campaign.

**2 — Declare the participants.** Because step 1 skips the lobby path, the campaign must bring its
own players or there are none:

```
    LocalPlayer = GoodPlayer
    AddPlayer GoodPlayer
        PlayerTemplate    = PlayerMen
        AITemplate        = DefaultAITemplate
        BaseRegion        = Cair_Andros
        MP_SlotColorIndex = 0
        TeamNumber        = 0
    End
```

Field table `0x00C1AE70`: `PlayerTemplate`, `AITemplate`, `BaseRegion`, `MP_SlotColorIndex`,
`TeamNumber`, `LWHandicap`, `IsDumb`. The stock `WOTRTutorial` — the only campaign EA shipped with
`IsScriptedCampaign = Yes` — declares two `AddPlayer` blocks and one `LocalPlayer`.

**3 — Name it, which needs the patch.**

```
GameData
    LivingWorldCampaignOverrride = WOTRScenarioAngmar
End
```

Step 1 has a side effect: the scenario-list predicate at `0x007B9551` answers "not listable" the
moment `IsScriptedCampaign` is set, so a scripted campaign **disappears from the War of the Ring
picker**. That is deliberate, and it leaves exactly two routes to one:

- `AptMainMenu`'s hardcoded `"WOTRTutorial"` literal (`0x007B9983`, called from `0x0091B867`), or
- `LivingWorldCampaignOverrride`, which drives `selectByName` (`0x007B98CF`).

The second is the data-driven route, and it was **unusable**: the field's `GameData` row
(`0x00BFF740`) named the *Bool* parser while `GlobalData+0x8C` is an `AsciiString` everywhere in
code. Setting it wrote `1` over the string pointer, and the next `AsciiString::isEmpty` would
dereference address `0x1`. [`living-world-override`](../patches/living_world_override.py) repoints
that one dword at the `AsciiString` parser the sibling `ShellMapName` row already uses.

```sh
sage-patch apply living-world-override --in game.dat --out game.dat
sage-patch verify living-world-override game.dat
```

Verified live afterwards: the field read back as the string `'WOTRScenarioAngmar'`, `selectByName`
resolved it to index 13 of 14, and `begin()` initialised the campaign at act 0 of 11.

## Known limits

- **The override is global.** It forces one campaign for every War of the Ring start until the line
  is removed. Right for authoring and testing; wrong for shipping. The shipping shape is a menu
  entry that names a campaign, in the manner of [`campaign-select`](campaign-select.md) — see
  [`living-world-parity.md`](living-campaign/living-world-parity.md) §1.
- **This buys progression, not parity.** Acts now advance; the affordances BFME1's campaign was
  built on are a separate question, covered in the parity plan.

## How the campaign is reached

```
00779D36  GameLogic's MSG_NEW_GAME handler
   -> 006BE09E  LivingWorldLogic::startCampaign(index)
   -> 006B90A7  override non-empty ? selectByName (007B98CF) : selectByIndex (007B9669)
   -> 007B9669  bounds-check, store index, copy IsEvilCampaign (campaign+0x59) -> manager+0x2C,
                call 00933379  LivingWorldCampaign::begin
   -> 00933379  teardown previous, act cursor = -1 (0x00933388), rebuild act state
                (00932B82, 00932EB8), jmp 00932A57 -> advance to act 0 and run it
```

`begin` is the only writer of the act cursor and the only caller of the two state builders. The act
runner `0x0096E362` makes ten per-verb passes and has three callers: the advance path
(`0x00932A85`), recursion for `CallActSubroutine` (`0x0096E413`), and an ungated manager accessor
(`0x007B9816`).

Live layout, for anyone reading the running process:

| what | where |
|---|---|
| `TheLivingWorldCampaignManager` | `0x00DE87AC` |
| selected index | `manager+0x10` |
| campaign pointer vector | `manager+0x14` … `manager+0x18` |
| `IsEvilCampaign` (copied) | `manager+0x2C` |
| act cursor / last act / acts base | `campaign+0x08` / `+0x18` / `+0x0C`, stride `0xB8` |
| `SecondsPerReinforcement` | `campaign+0x44` |
| `IsScriptedCampaign` / `IsEvilCampaign` / `ForceAdvanceTurnPhase` | `campaign+0x58` / `+0x59` / `+0x5A` |

## Two corrections, recorded

Both were caught by reading the running process, and both would have sent someone down a dead end.

1. **`LiveCampaignMode` does not default to off.** An earlier revision claimed it did, concluded
   `begin()` never ran, and proposed a three-byte patch to force two gates. `GlobalData`'s
   constructor sets it to **1** (`0x00642A91`, `mov byte [esi+0x86], al` with `al = 1` since
   `0x006429E1`), so both gates already pass and the patch would have been a no-op. The error came
   from searching the constructor for `mov byte [reg+0x86], imm8`, finding none, and *inferring*
   zero — the real encoding is a store from a register.

2. **`WOTRScenarioTest` does not set `IsScriptedCampaign`.** A grep found the string without
   checking that the line is `;`-commented. Only the stock `WOTRTutorial` sets it live.

## Method

Static analysis with capstone anchored on known call sites, field tables walked directly, caller
maps built by scanning `.text` for `E8`/`E9` branches. Data claims are greps of the uncompressed
ini text in the install's `.big` archives. **The conclusions were confirmed against the running
game** via `sage_live` and the `live-bridge` patch.
