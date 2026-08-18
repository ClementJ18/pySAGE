# `OnTriggerRechargeSpecialPower` as a list — reverse-engineering notes

The RE behind [`patches/trigger_recharge_list.py`](../patches/trigger_recharge_list.py). ROTWK
`game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, no ASLR, so a file offset is
`VA - 0x400000` throughout. Read statically from the repo's own `game.dat` (11,346,944 bytes),
2026-08-18.

## The gap

`OnTriggerRechargeSpecialPower` is the "using this ability also puts that one on cooldown" keyword.
It selects the affected ability **by name**: the keyword writes an `AsciiString` into
`ModuleData+0x6c`, and on activation the object's own module array is walked and
`startPowerRecharge(1.0)` called on the power whose `SpecialPowerTemplate` carries that name.

Note the direction, which the keyword's name invites you to get backwards. "Recharge" here is the
engine's word for **arming** the cooldown, not clearing it: the named power comes out of this as if
it had just been cast. It is the same call the module makes on *itself* at `0x008979BC`.

Both halves belong to `SpecialAbilityUpdate`, not to any one module — see §1.1. Every special-power
module inherits the keyword *and* the walk that acts on it.

What the keyword cannot do is name **two**. And the obvious workaround does not exist: a second
`SpecialPowerTimerRefreshSpecialPower` needs its own `SpecialPowerTemplate` to hang off — that
module is driven by *being* a special power — but there is only one power actually being used, so
the second module has nothing honest to point at and never fires.

The keyword is one token short of the feature. This patch is the plural of a mechanism the engine
already has.

## TL;DR

- The whole feature lives in **one function**, `doSpecialPower` at `0x00897987`, and in **one
  field-parse table entry**, at `0x00C64FA0`. Both are `SpecialAbilityUpdate`'s and shared by all
  **23** special-power modules (§1.1), so this patch changes behaviour for every one of them.
- What the feature *does* is **start** the named power's cooldown, not clear it — `startPowerRecharge`
  at `0x00897A35`, the same call the module makes on itself.
- The field is an `AsciiString`: **one pointer** to a refcounted buffer. A list of names *is* a
  string, so nothing grows — no `sizeof(ModuleData)` literal, no relocated table, no ctor shim,
  no destructor change (§1.3).
- The keyword parses with stock `INI::parseAsciiString` (`0x0042EE5E`), which takes the **first**
  token and leaves the rest of the line unread. Replacing that one `imm32` with a cave routine
  that consumes every token is the whole of the INI half (§2.1).
- The walk's name test is one `call` at `0x00897A21` to `AsciiString::compare` (`0x004065AA`).
  Repointing it at a cave that asks "is this one of the tokens" is the whole of the runtime half
  (§2.2).
- The **other** compare in the same function, the own-power early-out at `0x008979E1`, needs no
  patch at all: a one-name list is that name, and a two-name list can never equal a single
  template name because a name cannot contain a space (§3.1).
- Cost: **two edits** — 4 bytes in `.rdata`, 5 bytes in `.text` — plus a `0x105`-byte cave holding
  the two routines. **Statically verified**: both sites hold their stock bytes in the real binary
  and apply / verify / detect round-trip against it.

## 1. Anatomy

### 1.1 The module

Registered at `0x0065B4D4` with interface mask `0x100`; instance factory `0x00654884` (`0x34`
bytes), `ModuleData` factory `0x0064D965`.

| what | address |
|---|---|
| `ModuleData` ctor | `0x00896834` (`sizeof` `0x7c`) |
| `ModuleData` dtor | `0x00896AE3` |
| `buildFieldParse` | `0x0089699B` |
| field-parse table | `0x00C64DB0`, 35 entries, terminator at `0x00C64FE0` |
| `doSpecialPower` | `0x00897987` |

The `ModuleData` is the **plain `SpecialAbilityUpdateModuleData`** — this module adds no fields of
its own — so the table at `0x00C64DB0` is the one *every* special-power module inherits. Twenty-
three modules share it (`PlayerHealSpecialPower`, `OCLSpecialPower`, `CashHackSpecialPower`, …),
each adding its own table after it to the same `MultiIniFieldParse`.

**And so is `doSpecialPower`.** `0x00897987` is `SpecialAbilityUpdate`'s, not
`SpecialPowerTimerRefreshSpecialPower`'s: no vtable holds its address directly: they hold the
adjustor thunk at `0x00897D25` (`add ecx, -0x10` / `jmp 0x00897987`), and **23 vtables point at
that thunk** — the same 23. Its `UpdateModuleStartsAttack` branch at `0x008979B1` is the other tell:
that is generic special-ability work, not timer-refresh work.

The consequence runs through everything below: the keyword is not one module's, and neither is the
walk. Any of the 23 can carry `OnTriggerRechargeSpecialPower` and all of them execute the same
matcher, so both edits change live behaviour across the whole family.

Entry 31 is the keyword:

| field | value |
|---|---|
| name | `0x00C64B6C` → `"OnTriggerRechargeSpecialPower"` |
| parse fn | `0x0042EE5E` (`INI::parseAsciiString`) |
| userData | `0` |
| offset | `0x6C` |

**The name string has exactly one reference in the whole image**, the pointer in this entry. So
there is one parse function to repoint and no second table quietly parsing the same keyword for
some other module.

### 1.2 Where the field is touched

Four sites in the module's own code form the address of `ModuleData+0x6c`:

| VA | what |
|---|---|
| `0x008968C2` | `lea ecx, [esi+0x6c]` — the `AsciiString` ctor, inside `0x00896834` |
| `0x00896AF4` | `lea ecx, [esi+0x6c]` → `0x00435D50`, the dtor |
| `0x008979C5` | `lea esi, [ebx+0x6c]` → `isEmpty`, the guard at the top of the walk |
| `0x00897A18` | `lea ecx, [ebx+0x6c]` → `compare`, the walk's name test |

A sweep of `.text` for *any* `lea reg, [reg+0x6c]` followed within 24 bytes by a call to an
`AsciiString` method finds 22 sites. Four are the ones above; the other eighteen belong to
unrelated classes (`0x008A64AB` compares a `+0x6c` string against the global at `0x00DC62B8`;
`0x00655DB0` is another class's destructor; and so on). **Nothing outside this module reads the
field.**

### 1.3 The `AsciiString`, and why nothing has to grow

An `AsciiString` is one 4-byte handle pointing at a refcounted buffer:

| offset in the buffer | what | read at |
|---|---|---|
| `+0x00` | reference count | `0x00435D9B` (`dec dword [eax]`, free at zero) |
| `+0x04` | length, `UInt16` | `0x00401E6A`, `0x004065B4` |
| `+0x06` | allocated, `UInt16` | `0x00436118` |
| `+0x08` | the characters | `0x004065C0` (`add eax, 8`) |

A NULL handle is a validly constructed empty string everywhere: `isEmpty` answers yes without
dereferencing, `concat` sees the null and assigns instead (`0x0043634A`), and the empty literal
`0x00BD0C3F` stands in wherever a `const char *` is needed.

That is the fact this patch turns on. The field can hold a string of any length **today**, so a
list of names costs zero bytes of `ModuleData` — which removes at a stroke the work the sibling
patches in this directory all have to do: the `push <sizeof>` in the factory, the constructor shim
that default-constructs a new member, the relocation of a field-parse table that has no room to
grow, and the destructor that has to release what the new member holds.

### 1.4 `doSpecialPower`, annotated

```
00897987  <prologue>                      ; edi = the module, ebx = [edi+4] = the ModuleData
008979b1  cmp  byte [ebx+0xc], 0          ; UpdateModuleStartsAttack
008979b5  jne  0x8979c5
008979bc  call dword [eax+0x3c]           ;   No -> startPowerRecharge(1.0) on ITSELF

008979c5  lea  esi, [ebx+0x6c]            ; OnTriggerRechargeSpecialPower
008979c8  mov  ecx, esi
008979ca  call 0x401e64                   ; isEmpty? -> nothing named, done
008979cf  test al, al
008979d1  jne  0x897a41

008979d3  mov  ecx, [ebx+8]               ; the module's own SpecialPowerTemplate
008979d6  call 0x688d3c                   ; -> final override
008979db  add  eax, 0x10                  ; its name
008979de  push eax
008979df  mov  ecx, esi
008979e1  call 0x4065aa                   ; the field == its own power's name?
008979e6  test eax, eax
008979e8  je   0x897a41                   ;   yes -> done, the walk would be redundant

008979ea  mov  eax, [edi+8]               ; the Object
008979ed  mov  esi, [eax+0x24c]           ; its module array
008979f3  jmp  0x897a3b
008979f5    add  eax, 0xc
008979fc    call dword [edx+0x20]         ;   -> the SpecialPower interface, or NULL
00897a0a    call dword [edx+0x18]         ;   -> its SpecialPowerTemplate, or NULL
00897a13    call 0x688d3c                 ;   -> final override
00897a18    lea  ecx, [ebx+0x6c]
00897a1b    add  eax, 0x10
00897a1e    push ecx                      ;   arg = the field
00897a1f    mov  ecx, eax                 ;   this = the candidate's name
00897a21    call 0x4065aa                 ;   <- THE TEST
00897a26    test eax, eax
00897a28    jne  0x897a38                 ;   no match -> next module
00897a35    call dword [eax+0x3c]         ;   match -> startPowerRecharge(1.0)
00897a38    add  esi, 4
00897a3b  mov  eax, [esi]
00897a3d  test eax, eax
00897a3f  jne  0x8979f5                   ; the array is NULL-terminated
00897a41  <the rest: level-up, model condition, FX>
```

Registers across the loop: `esi` is the module cursor, `edi` the module, `ebx` the `ModuleData`,
and `[ebp-0x14]` the candidate whose cooldown a match starts. `0x004065AA` is a `__thiscall` that
preserves all three, which is why the replacement has to as well.

### 1.5 The two comparison functions

```
004065aa  mov   eax, [esp+4]        ; the other string's handle
004065ae  mov   eax, [eax]
004065b4  movzx edx, word [eax+4]   ; its length  (0 when the handle is NULL)
004065c0  add   eax, 8              ; its characters (or "" at 0x00BD0C3F)
004065ca  push  edx / push eax
004065cc  call  0x406307            ; -> 0x4052f9 -> memcmp   (0x00A3D01A)
004065d1  ret   4
```

`0x004065AA` is `AsciiString::compare`: **case-sensitive**, `eax == 0` meaning equal. Its
neighbour `0x004065D4` is the `compareNoCase` sibling and ends in `_memicmp` instead. The walk
calls the case-sensitive one, so a `SpecialPower` named in the wrong case never matched on stock
either — and the replacement keeps that, byte-for-byte.

Note the argument order differs between the two call sites: at `0x008979E1` `ecx` is the field and
the argument is the template name; at `0x00897A21` it is the other way round. `compare` is
symmetric for the equality test the callers make, but a replacement is not, so only the second
site — the one whose `ecx` is the *name* — is repointed.

### 1.6 The stock parser

```
0042ee5e  <EH prologue>
0042ee68  push ecx
0042ee69  mov  ecx, [ebp+8]         ; arg1 = the INI
0042ee6c  lea  eax, [ebp-0x10]      ; a temporary AsciiString
0042ee70  call 0x42e757             ; INI::getNextAsciiString(&temp) -> eax = &temp
0042ee75  mov  ecx, [ebp+0x10]      ; arg3 = the field
0042ee7d  call 0x436030             ; field = temp
0042ee89  call 0x435d50             ; ~temp
0042ee99  ret                       ; cdecl - the INI reader cleans the four arguments
```

One token, then return. The rest of the line is simply never read: nothing downstream complains,
which is why `OnTriggerRechargeSpecialPower = A B` loads on stock and silently means `A`.

`INI::getNextAsciiString` (`0x0042E757`) is the piece worth having: `__thiscall` on the `INI`,
`ret 4`, returns its argument. It pulls from `INI::getNextTokenOrNull` (`0x0042DBF5`), which
tokenizes the `INI`'s **current line buffer** at `+0x86C` through the strtok-style state at
`+0x870`/`+0x874` and returns NULL at the end of it — it never advances to the next line. On NULL,
`getNextAsciiString` leaves the output **empty** rather than failing. So "call it until it comes
back empty" is a complete, in-bounds way to read a line, and it keeps the quote handling
(`0x0042E787` onwards) that the stock keyword had.

The `AsciiString` helpers the replacement needs, all `__thiscall`:

| VA | what | cleanup |
|---|---|---|
| `0x00401E64` | `isEmpty()` → `al` | `ret` |
| `0x0040511A` | `concat(const char *)` | `ret 4` |
| `0x0040513F` | `concat(char)` | `ret 4` |
| `0x00436030` | `operator=(const AsciiString &)` | `ret 4` |
| `0x00435D50` | `~AsciiString()` — releases, then writes NULL back | `ret` |

## 2. The patch

Two edits and one appended `.trglst` section (`0x105` bytes: a `0x76`-byte parser followed by a
`0x8F`-byte matcher). The section is allocated with `allocate_section`, so it lands past every
existing section whatever else has been applied.

### 2.1 The keyword — one `imm32` at `0x00C64FA4`

```
old  5e ee 42 00      ; INI::parseAsciiString
new  <cave>           ; the parser below
```

The entry's name pointer, `userData` and `ModuleData` offset are untouched; only the parse
function moves. Because the table is `SpecialAbilityUpdate`'s, all 23 special-power modules now
parse the keyword this way — and because `doSpecialPower` is `SpecialAbilityUpdate`'s too (§1.1),
all 23 also *act* on what it stores. This is not a one-module change that 22 others merely pay the
parse for: the extra tokens are read by every special-power module that declares the keyword.

The cave parser, in full:

```
push ebp / mov ebp, esp / sub esp, 8
and  dword [ebp-4], 0            ; the accumulator - NULL is a valid empty AsciiString
and  dword [ebp-8], 0            ; the token
.next:
  lea  eax, [ebp-8] / push eax
  mov  ecx, [ebp+8]              ; the INI
  call 0042e757                  ; getNextAsciiString(&token)
  lea  ecx, [ebp-8]
  call 00401e64                  ; empty? -> end of line
  test al, al / jne .done
  lea  ecx, [ebp-4]
  call 00401e64                  ; accumulator still empty? -> first token, no separator
  test al, al / jne .append
  push 0x20
  lea  ecx, [ebp-4]
  call 0040513f                  ; concat(' ')
.append:
  mov  eax, [ebp-8] / add eax, 8 ; the token's characters
  push eax
  lea  ecx, [ebp-4]
  call 0040511a                  ; concat(const char *)
  jmp  .next
.done:
  lea  eax, [ebp-4] / push eax
  mov  ecx, [ebp+0x10]           ; the field
  call 00436030                  ; field = accumulator
  lea  ecx, [ebp-8] / call 00435d50
  lea  ecx, [ebp-4] / call 00435d50
  leave / ret
```

Three properties worth stating:

- **It replaces, it does not append.** The result is assigned with the same `operator=` the stock
  parser used, so a block that writes the keyword twice keeps the last line — which is what an
  override block relies on and what the stock keyword did.
- **No SEH frame.** The engine's INI errors throw; a throw crossing this frame leaks the two
  locals' buffers and corrupts nothing, and an INI parse error already ends the load.
- **A single token comes out byte-identical to stock**: one token, no separator, assigned.

### 2.2 The test — one `call` at `0x00897A21`

```
old  e8 84 eb b6 ff      ; call 0x004065aa
new  e8 <cave>           ; call the matcher
```

The matcher stands in for `AsciiString::compare` at exactly its call site, so it takes that
function's arguments and answers in its convention: `ecx` the candidate's name, `[esp+4]` the
field, `ret 4`, and **`eax == 0` means match**. `ebx`/`esi`/`edi` are saved and restored, because
the loop keeps its cursor, its module and its `ModuleData` in them.

```
push esi / push edi / push ebx
mov  eax, [ecx] / test eax, eax / je .no     ; an unnamed template matches nothing
lea  edi, [eax+8]                            ; the name
mov  eax, [esp+0x10] / mov eax, [eax]
test eax, eax / je .no                       ; a field never written matches nothing
lea  esi, [eax+8]                            ; the list
.token:                                      ; skip separators
  mov al, [esi] / cmp al, ' ' / jne .compare
  inc esi / jmp .token
.compare:
  test al, al / je .no                       ; end of the list
  mov  ebx, edi                              ; restart the name
.chars:
  mov al, [esi] / test al, al / je .ended
  cmp al, ' '  / je .ended
  mov dl, [ebx] / cmp al, dl / jne .skip
  inc esi / inc ebx / jmp .chars
.ended:                                      ; the token ended - match iff the name did too
  cmp byte [ebx], 0 / je .yes
.skip:                                       ; run to the end of this token, try the next
  mov al, [esi] / test al, al / je .no
  cmp al, ' ' / je .token
  inc esi / jmp .skip
.yes: xor eax, eax / jmp .out
.no:  xor eax, eax / inc eax
.out: pop ebx / pop edi / pop esi / ret 4
```

The comparison is a byte compare with no case folding, which is what `compare`'s `memcmp` tail
is. Whole tokens only: `A` does not match the list `AB`, `AB` does not match the list `A B`, and
`AA` and `A` are told apart in either order.

## 3. What changes, and what does not

### 3.1 The own-power early-out is left alone, on purpose

`0x008979E1` compares the *whole field* against the module's own power name and, on equality,
skips the walk. It is not patched, and it stays correct for free:

- A **one-name** list is that one name, character for character, so the early-out fires exactly
  when it fired on stock. This is the property that makes "a single name behaves as it does today"
  true of the whole function rather than of the matcher alone.
- A **multi-name** list can never equal a single template name, because `getNextAsciiString`
  tokenizes on whitespace and a `SpecialPower` block's name is one token — so a list that happens
  to include the module's own power falls through to the walk, which starts its cooldown like any
  other listed name. That is a change from stock only in the case stock could not express.

### 3.2 Quoted values

Both parsers pull tokens through `getNextAsciiString`, so `"Foo Bar"` still arrives as one token
and is stored with its space. The matcher then splits it back into two names nothing can be
called. This is not a regression: a `SpecialPower` name is a single INI token, so a quoted value
never matched anything under the stock compare either.

### 3.3 The one behavioural difference nobody can reach

Stock `compare("", "")` returns "equal"; the matcher answers "no match" for an empty name. The
case is unreachable: the walk runs only when the field is non-empty (`0x008979CA`), and an empty
name against a non-empty list is "not equal" under both.

### 3.4 Determinism

Both routines are pure functions of a `ModuleData` written at INI-parse time and of a template
name, run on the logic thread inside `doSpecialPower`. Nothing new enters the frame or the CRC.
But *which* powers are put on cooldown is simulation state, so this is a rule change like any
other:
**every peer must run the same patched binary**, and a mod that writes a two-name value needs the
patch or the second name is silently dropped — the stock parser reads one token and does not
complain about the rest.

## 4. Composition

Order-independent. The cave is appended past every existing section and `verify` finds it by name;
the two byte ranges rewritten are touched by no other bundled patch; and nothing it reads is
rebuilt by another patch. Worth noting explicitly for the one near miss:
[`player-heal-filter`](player-heal-filter.md) *reads* this same table — to reject a keyword that
would shadow an inherited one — and never writes it, so the two compose either way round.

## 5. Status

**Statically verified.** Both patch sites hold their stock bytes in the real
`2.01.2614.37001` binary; the table entry at index 31 is the keyword, parsed with the stock
`AsciiString` parser into `+0x6C`; and apply / verify / detect round-trip against the real file.
The matcher is executed in the test suite against a table of list/name cases, on a narrow
interpreter for the instruction forms it emits.

The parser is the part a static check cannot finish: its four callees are read from their
disassembly, and a wrong reading of an `AsciiString` calling convention shows up as a corrupted
keyword or a crash during INI load — loudly, and on the first load.
