# Launching a Living World campaign from the campaign menu

A patch scope. Engine build `2.01.2614.37001`, ImageBase `0x400000`. Addresses recovered
statically against the installed `C:\Program Files (x86)\Games\bfme\rotwk\game.dat` on
2026-08-11; APT claims are greps of the shipped `.apt`/`.const` in all 119 install archives plus
the loose `D:\Edain-Mod\_mod\apt` tree.

**Nothing here has been run.** Every claim is *static* unless marked otherwise — which matters,
because this investigation has already produced six wrong static inferences
([`living-world-parity.md`](living-world-parity.md) records four of them). Treat this as a scope,
not a result.

## The gap

[`living-world-campaign.md`](../living-world-campaign.md) got a scripted Living World campaign
running, but only by way of `LivingWorldCampaignOverrride` — a global that forces *one* campaign
onto every War of the Ring start. You reach it through the War of the Ring flow, which is the wrong
flow: it is a multiplayer scenario picker with a campaign bolted behind it.

What you want is a campaign menu entry that starts a named Living World campaign directly.

## TL;DR

- The engine **already has** a menu-driven Living World launcher that bypasses the War of the Ring
  picker entirely: the FSCommand `AptMainMenu::OnTutorial`, called with `params = "Strategic"`.
- It is **orphaned**. `OnTutorial` appears in **zero** shipped shell movies — 119 archives and the
  loose Edain APT tree, no hits. Registered in the engine, invoked by nothing.
- It names its campaign through a **function-local static behind an MSVC magic-static guard**
  (`0x00DE87B0` / `0x00DE87B4`) — the *identical* structure [`campaign-select`](../campaign-select.md)
  already exploits for the linear campaigns.
- An unknown campaign name fails to `-1` and the launcher silently declines. Same fail-soft
  property as `startLinearCampaign`; **no crash path** on a bad name.
- So the scope is two 5-byte hooks plus a cave, and an APT entry — not a new subsystem.
- **`LivingWorldCampaignOverrride` must come back out.** It overrides an explicit index, so it
  would hijack the menu route. Removing it is the point of the exercise.

## 1. Two launchers, and the campaign menu only knows one

| | linear campaigns | Living World campaigns |
|---|---|---|
| entry | `AptMainMenu::Expansion1Campaign` / `BonusCampaign` | `AptMainMenu::OnTutorial` (`"Strategic"`) |
| names it via | magic static `0x00DEA35C`, guard `0x00DEA360` | magic static `0x00DE87B0`, guard `0x00DE87B4` |
| resolves through | `TheCampaignManager` `0x005EB010` | `findIndexByName` `0x007B988E` |
| launcher | `startLinearCampaign` `0x0091B1D2` | `MSG 0x1F` → `LivingWorldLogic::startCampaign` `0x006BE09E` |
| reached from the shell today | yes — Solo Play flyout | **no — nothing calls it** |
| patched already | yes, [`campaign-select`](../campaign-select.md) | this scope |

The two launchers are structurally the same shape, which is why the same patch technique applies to
both.

## 2. The orphaned entry point

Registered in `AptMainMenu`'s constructor exactly like the campaign callbacks:

```asm
0091d151  push 0x00c7d054               ; "AptMainMenu::OnTutorial"
0091d156  lea  ecx, [ebp+8]
0091d159  mov  esi, 0x0091b825          ; <-- the callback
0091d160  call 0x004374e0               ; AsciiString(name)
```

The callback at `0x0091B825` switches on `params` against three literals:

| `params` | at | does |
|---|---|---|
| `"Basic"` | `0x00C7CE58` | `GlobalData+0x1114` → `GlobalData+0x115C`, plays a tutorial map |
| `"Advanced"` | `0x00C7CE60` | `GlobalData+0x1138` → `GlobalData+0x115C`, ditto |
| `"Strategic"` | `0x00C7CE6C` | **the Living World launch** |

`params` is a plain `const char *` — the same fact `campaign-select` depends on, here confirmed by
the callback handing it straight to a string compare (`0x00A3CF40`) rather than to an `AsciiString`
method.

**It is dead in the shell.** A scan of every `.apt` and `.const` in all 119 install archives, plus
`D:\Edain-Mod\_mod\apt` and `apt_widescreen`, found **no occurrence of `OnTutorial`**. Dispatch in
these movies is by placeobject name (`_root[this._name + "Button"]()` → `GameCode(func, params)`),
so a command that appears in no constant pool cannot be sent. The code path has never run in a
shipped build.

That is a feature for us: no existing button's behaviour can regress.

## 3. From menu click to running campaign

```
_root.GameCode("OnTutorial", "Strategic")
  -> geturl2("FSCommand:AptMainMenu::OnTutorial", "Strategic")

0091b825  AptMainMenu::OnTutorial(params)
0091b83a    strcmp(params, "Strategic")             ; 0x00A3CF40
0091b859    ecx = [0x00DE87AC]                      ; TheLivingWorldCampaignManager
0091b861    if (!manager) bail
0091b867    edi = call 0x007B9983                   ; index of "WOTRTutorial"
0091b870    if (edi < 0) bail
0091b87e    hide the shell, stop the shell map
0091b8a7    msg = TheMessageStream->appendMessage(0x1F)
0091b8b9    msg->appendIntegerArgument(edi)         ; arg0 = campaign index
0091b8c1    msg->appendIntegerArgument(0)           ; arg1 = source tag

00779d15  GameLogic message handler, case 0x1F
00779d23    [edi+0x114] = arg1
00779d30    ecx = [0x00DE4950]
00779d36    call 0x006BE09E                         ; LivingWorldLogic::startCampaign(arg0)

006be109  -> 0x006B90A7
006b90ea    ebx = TheGlobalData + 0x8C              ; LivingWorldCampaignOverrride
006b90f5    if (isEmpty)  selectByIndex(arg0)       ; 0x007B9669
            else          selectByName(override)    ; 0x007B98CF
         -> 0x00933379  LivingWorldCampaign::begin
```

`MSG 0x1F` has **four senders**, all `(campaignIndex, tag)`:

| site | index from | tag |
|---|---|---|
| `0x0091B89F` | `OnTutorial` | **0** |
| `0x00648EE5` | `[[esi+0x44]+0x58]` | 1 |
| `0x00903A1A` | `[esi+0x58]` | 2 |
| `0x009287AD` | `[[0x00DE8930]+0x58]` | 0 |

The tag's meaning is **unknown** — it lands in `[edi+0x114]` and I did not establish what `edi`
holds on that path. The menu route inherits `0`, which is what the stock `"Strategic"` path already
sends, so this is a question to answer rather than a decision to make.

## 4. Where the name is said

```asm
007b9983  <SEH prologue>
007b998d  test byte ptr [0x00DE87B4], 1     ; the magic-static guard
007b9998  mov  esi, 0x00DE87B0              ; the static - loaded either way
007b999d  jne  007b99c2                     ; already initialised -> skip
007b999f  or   dword ptr [0x00DE87B4], 1
007b99ab  push 0x00C35D34                   ; "WOTRTutorial"
007b99b2  call 0x004374e0                   ; static = AsciiString(literal)
007b99bc  call 0x00A3CF72                   ; atexit(dtor)

007b99c2  push esi                          ; <-- the static, always
007b99c5  call 0x007B988E                   ; findIndexByName -> index or -1
```

Byte for byte the pattern `campaign-select` documents at `0x0091BE64`: the static is written once
per process behind a guard bit, and everything downstream reads the static, never the literal.

And `findIndexByName` is fail-soft:

```asm
007b988e  walk manager+0x14 .. manager+0x18   ; the campaign pointer vector
007b98a9  compare campaign+4 (the name)       ; 0x004065AA
007b98c3  or eax, -1                          ; not found -> -1
```

`-1` makes `OnTutorial` bail at `0x0091B870` without posting the message. An unknown campaign name
is a no-op, not a crash — the same safety argument `campaign-select` rests on.

## 5. Patch options

### A — fill the static *(cheapest, but still one global campaign)*

Write `0x00DE87B0` with the campaign name and set bit 0 of `0x00DE87B4`, exactly as
`campaign_select.py` does for `0x00DEA35C`/`0x00DEA360`. `OnTutorial("Strategic")` then launches
that campaign.

Strictly better than `LivingWorldCampaignOverrride` — it does not hijack War of the Ring starts —
but it is still *one* campaign chosen at patch time. **Not the goal**, though it is a useful
half-step and a way to prove the chain live before writing the cave.

### B — a params tail on `OnTutorial` *(recommended)*

The `.apt` sends `"Strategic:WOTRScenarioAngmar"`; the engine takes the tail as the campaign name.
Unlimited campaigns, one channel, chosen per menu entry.

Two hooks:

1. **`0x0091B83A`'s compare** must become a prefix compare, or the tail breaks the `"Strategic"`
   match. Either redirect the `call 0x00A3CF40` to a cave doing a 9-character compare, or hook the
   function entry and split `params` at `:` before the stock body runs.
2. **`0x0091B867`'s `call 0x007B9983`** becomes `call <cave>`, where the cave runs
   `findIndexByName(tail)` when a tail is present and falls through to stock `0x007B9983` when it
   is not.

Both are 5-byte redirects into one cave, and neither touches the jump table, the callback registry,
or the message plumbing. Same size and shape as `campaign-select`, whose cave is 129 bytes.

Fail-soft is preserved for free: a typo'd name reaches `findIndexByName`, returns `-1`, and the
button does nothing.

### B′ — one channel for both campaign kinds *(variant, avoids an APT question)*

Extend `campaign-select`'s existing channel instead: `Expansion1Campaign` already accepts a params
tail and its constant is already in `MainMenu.const`. Branch on a prefix — `"Hard:LW:WOTRScenarioAngmar"`
— and route to the Living World launcher instead of `startLinearCampaign`.

Avoids adding a constant to the APT pool (§6), but means **modifying a shipped, working patch** and
entangling two launchers in one callback. Worth it only if §6 turns out to be a problem, which it
does not appear to be.

### C — relax the scenario-list predicate *(rejected for this goal)*

`IsScriptedCampaign` makes a campaign unlistable by design (predicate `0x007B9551`). Relaxing it
would put scripted campaigns back into the War of the Ring picker — which is the flow you are
trying to get *away* from. Noted because [`living-world-parity.md`](living-world-parity.md) §1
offers it as an alternative; for a campaign-menu entry it is the wrong direction.

## 6. The APT side

No shipped movie sends `OnTutorial`, so the entry has to be authored. Two pieces:

**The command string.** `GameCode(func, params)` builds `"FSCommand:AptMainMenu::" + func`, and
`func` comes from a constant. `"OnTutorial"` is in no constant pool, so it must be appended to
`MainMenu.const`. This is **supported**: `sage_apt`'s `_generate_const_file` rebuilds the pool from
the XML and recomputes every string offset, and bytecode refers to constants by index, so appending
at the end leaves existing indices untouched.

**The button.** The Solo Play flyout dispatches by placeobject name — a row named `X` invokes
`_root.XButton()`. So a row plus a function that calls
`_root.GameCode("OnTutorial", "Strategic:<CampaignName>")`.

Two things already established elsewhere make this cheaper than it sounds:

- A `sage_apt` round-trip of `MainMenu.apt` **loads in the real game** — verified in the
  campaign-menu session, which also confirmed `attachMovie` works on an exported import.
- `MainMenu.const` already carries a `CampaignMenu` constant, and `SoloPlayNav` already places five
  `menu1_sub01` rows the same way a sixth would be placed.

That session also hit **one crash** on the runtime-`attachMovie` build (`AptAnimation.cpp`, a
`.const` pointer fixup) which was never explained. If the campaign menu is built with pre-placed
rows rather than runtime-attached ones, this scope does not go near that code path.

## 7. What this replaces

`LivingWorldCampaignOverrride` **must be removed from `GameData`** for any of this to work: the
branch at `0x006B90F5` checks the override *before* honouring the index, so a non-empty override
hijacks every route including this one. The `living-world-override` patch itself can stay applied —
it only repairs the field's parser row — but the INI line goes.

That is the whole point: the override was the authoring crutch, and this is what retires it.

## 8. Unknowns, and what settles them

| | question | confidence | settles it |
|---|---|---|---|
| 1 | Does the `"Strategic"` path work at all, on any campaign? | **unproven — never run in a shipped build** | Option A: fill the static with `WOTRScenarioAngmar`, add a temporary button, launch |
| 2 | What is `MSG 0x1F`'s arg1 (`[edi+0x114]`)? | unknown | read `edi` live at `0x00779D15` through `live-bridge`; compare tags 0/1/2 |
| 3 | Does the campaign still need `IsScriptedCampaign`? | **yes, and that is now a blocker** — see below | the same live run as (1) |
| 4 | Does `OnTutorial` leave shell state the linear path cleans up? | unknown — it stops the shell map at `0x0091B87E`, but the sequence differs from the linear route | observe the transition in (1) |
| 5 | Does appending a constant to `MainMenu.const` round-trip? | high — the writer rebuilds the pool | a round-trip diff, no game needed |

**Question 1 is the one that matters.** Everything else in this scope is contingent on a code path
that no shipped build has ever executed. Option A is the cheap way to answer it: it is a four-byte
static write plus a throwaway button, and if the chain does not run, the cave in Option B is wasted
work.

**Do (1) before writing any cave.**

## 9. This scope is blocked by the participant problem (2026-08-14)

Reasoned from the live result in [`battle-sides.md`](battle-sides.md), and stated as inference:

1. This route bypasses the lobby, so the `GameInfo` at `0x00DE892C` / `0x00DE8930` is never
   populated by it.
2. `LivingWorldCampaign::begin`'s unscripted builder *reads* that `GameInfo` to create the
   campaign's `LivingWorldPlayer`s. With it empty, an unscripted campaign launched this way gets no
   strategic players at all.
3. So a campaign reached from the menu **must** set `IsScriptedCampaign`, which is what makes it
   supply its own players from `AddPlayer`.
4. And `IsScriptedCampaign` is exactly what leaves every battle with no faction players and the
   client seated as `ReplayObserver`.

**So the menu entry cannot produce a playable campaign on its own.** Built today it would give a
nicer route to the same unplayable battles - the launch flow is the *how*, and the participant
problem is the *what you get*. [`living-world-parity.md`](living-world-parity.md) item 7 therefore
blocks item 1, which reverses the order those two were listed in.

The assumption to check is step 1: if some other part of the `OnTutorial` path populates a
`GameInfo`, the chain is not blocked at all. That is worth ten minutes with `live-bridge` before
accepting the conclusion - and the run for question 1 above would show it, since a campaign that
seats real players in its first battle disproves the whole argument.

## Method

Static analysis with capstone anchored on known call sites; field and jump tables walked directly;
callers found by scanning `.text` for `E8`/`E9` branches; APT claims by exhaustive extraction of
every archive in the install. None of it confirmed against the running game — see the working rule
in [`living-world-parity.md`](living-world-parity.md).
