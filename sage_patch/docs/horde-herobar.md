# HordeHerobarPatch: horde health in the hero bar

`HordeHerobarPatch` (`horde-herobar`) changes the health source for an existing horde entry in
the hero bar. Its implementation is in `sage_patch/patches/horde_herobar.py`. It does not create
hero-bar entries, change selection, write object health, or alter death and recruitment logic.
The independent [`HeroHordeDeathPatch`](hero-horde-death.md) handles death registration.

The member-health hook and registered-banner health source have been demonstrated in game by
the user. The weighted calculation described here is a subsequent revision. Signature checks
and instruction emulation validate its implementation; they do not substitute for a game test
of this revision. The patch therefore retains its `partly` runtime-verification status.

## Health-source rule

After confirming a native horde interface and its ModuleData, exactly one setting selects the
health source:

| `BannerCarrierDestroyHordeOnDeath` | Health source |
|---|---|
| `Yes` | The registered banner carrier's native health ratio |
| `No` | Sum of current member health divided by sum of maximum member health |

There are no `HERO`, `HORDE`, `MELEE_HORDE`, or `COMBO_HORDE` bit tests in this decision.
The native horde-interface lookup identifies a horde. `MELEE_HORDE` and `COMBO_HORDE` therefore
receive the same setting-based treatment as other horde types.

When `BannerCarrierDestroyHordeOnDeath = Yes`, the banner carrier supplies the shared health
indicator. The hook resolves the registered banner ObjectID through `GameLogic::findObjectByID`
and calls that object's native `Body::getHealthRatio()`. This explicitly preserves the intended
banner-based behavior even when the container has an `ImmortalBody` whose own health stays full.
If the banner ID, resolved object, or body is missing, or the ID resolves to the container itself,
the hook falls back to the container's original getter.

Otherwise, the displayed ratio is:

```text
ratio = sum(member.Body.currentHealth) / sum(member.Body.maximumHealth)
```

Both sums cover the same currently contained objects with a body. This is an HP-weighted ratio,
not an average of individual health percentages and not a fraction of `HordeContain.Slots`.
`Slots` is neither read nor used as a guard. For example:

| Currently contained members | Current HP sum | Maximum HP sum | Ratio |
|---|---:|---:|---:|
| Five members, each 100/100 | 500 | 500 | 100% |
| Three remaining members, each 100/100 | 300 | 300 | 100% |
| One member at 10/100 | 10 | 100 | 10% |
| One member at 50/100 and one at 900/900 | 950 | 1000 | 95% |
| Empty list, or a valid list with zero total maximum HP | 0 | 0 | 0% |

Removed members no longer contribute to either sum. Additional contained objects, including a
banner carrier if present in this list, contribute when they have a body. No extra rule excludes
them. Missing member pointers and missing bodies are skipped. Members whose maximum HP is not
positive contribute to neither sum. An invalid list termination or
exhausted traversal budget discards the partial calculation and uses the original container
getter.

The original hero-bar percentage conversion and clamping remain in place. In particular, the UI
still displays at least 1% while drawing an entry, even when the hook returns zero.

## Reference binary and verified addresses

The verified RotWK reference executable has:

- SHA-256: `5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26`.
- Size: 11,346,944 bytes; PE32/i386; preferred ImageBase `0x00400000`.

See [`hero-horde-death.md`](hero-horde-death.md) for binary metadata and section layout.
A VA is an address in the preferred image; RVA = VA - ImageBase. A file offset is calculated
through the PE section table. The matching offsets below are a property of this reference's
original sections, not a general PE rule.

| VA | RVA / file offset | Meaning |
|---|---|---|
| `0x0092D5D7` | `0x0052D5D7` | Fetch the displayed object from `[EBP-0x20]` and its BodyInterface |
| **`0x0092D5EB`** | **`0x0052D5EB`** | Health getter hook; original bytes **`8B 01 FF 50 14`** |
| `0x0092D5F0` | `0x0052D5F0` | Resume original percentage conversion |
| `0x0092D611` | `0x0052D611` | Original percentage storage and minimum display of 1% |
| `0x0086620E` | `0x0046620E` | Native contain-list traversal; confirms sentinel and node layouts |
| `0x00872A6F` | `0x00472A6F` | Contain-interface vtable slot `+0x7C`, returning a horde interface |
| `0x0087193C` | `0x0047193C` | Native comparison with registered banner ID at Runtime+`0x26C` |
| `0x00871950` | `0x00471950` | Native use of `BannerCarrierDestroyHordeOnDeath` at ModuleData+`0x224` |
| `0x00876427` | `0x00476427` | Native registered-banner ID write |
| `0x00449681` | `0x00049681` | `GameLogic::findObjectByID(ObjectID)`, thiscall, `ret 4` |
| `0x005F2D41` | `0x001F2D41` | Native current-health getter, `fld [ecx+8]; ret` |
| `0x006AA274` | `0x002AA274` | Native maximum-health getter, `fld [ecx+0x10]; ret` |
| `0x008C1D75` | `0x004C1D75` | Native current/max health ratio; does not forward to contained objects |
| `0x00DE412C` | `0x009E412C` | `GameLogic*` global |

The Cheat Engine expression `game.dat+52D5EB` denotes an RVA and becomes VA `0x0092D5EB`
with this ImageBase. Context signatures are frozen in the patch's `ANCHORS`; they are not
learned from whatever input file is being patched.

The relevant runtime layout and calling conventions are:

- Displayed object: `[EBP-0x20]`; BodyInterface: `[Object+0x25C]`.
- `[Object+0x258]` is the **ContainModuleInterface** at Runtime+`0x20`.
- Its ModuleData is `[ContainModuleInterface-0x1C]`.
- `call [ContainVTable+0x7C]`, ECX=ContainModuleInterface, no stack arguments, returns the
  horde interface at Runtime+`0x11C`, or null for a non-horde container.
- Banner ObjectID: `[HordeInterface+0x150]`, equivalent to Runtime+`0x26C`.
- Contained-list sentinel: `[ContainModuleInterface+0x34]`; next node: `[Node]`;
  member object: `[Node+0x08]`.
- Body virtual slots `+0x10`, `+0x1C`, and `+0x14` return current HP, maximum HP, and health
  ratio respectively. ECX=BodyInterface, no stack arguments, floating-point result in ST(0).

The ContainModuleInterface is distinct from the HordeInterface used by the death hook.
Their offsets must not be interchanged.

## Hook, ABI, and fallback behavior

The five original bytes become `E9 rel32`. A new executable/readable `.hrdhbar` section holds
the handler; its address depends on existing sections and patch order. The patch
builds its instruction stream directly in Python.

The handler preserves general-purpose registers and EFLAGS around its calculation. Local
stack storage holds the current-HP sum, maximum-HP sum, a temporary member maximum, and a
traversal budget of **128 members, decimal**. Each native getter's x87 result is consumed immediately while accumulating
the sums. A successful calculation leaves exactly one new value in ST(0), above any pre-existing
x87 values, and restores the original stack pointer. It deliberately does not restore a saved
FPU image over the result.

The banner path also returns exactly one native ratio in ST(0). On every fallback path,
registers, flags, and stack are restored **before** replaying the original instructions:

```asm
mov eax,[ecx]
call dword ptr [eax+0x14]
```

This restores the original BodyInterface pointer in ECX and retains the getter's normal
register and flag side effects. Execution then resumes at `0x0092D5F0`.

Null guards protect the object, contain interface, horde interface, ModuleData, sentinel,
list nodes, and banner lookup. A non-horde object follows the original getter. The traversal
budget prevents an endless walk through a corrupted or cyclic list. These are layout and
consistency checks, not a general way to validate arbitrary inaccessible pointers.

`apply` checks the signatures and installs on an in-memory copy before updating its caller's
buffer. An exact repeat is a no-op. Existing but incompatible `.hrdhbar` code, foreign hook bytes,
and damaged anchors are rejected. Rebuild from the reference backup when changing patch
versions; an older cave is not silently overwritten.

## Build, verify, and remove

Run with Python 3.12 or newer and keep the original executable unchanged:

```sh
python -m sage_patch apply horde-herobar --in original.dat --out horde-health.dat
python -m sage_patch verify horde-herobar horde-health.dat
```

For a combination, pass the selected patches to `sage_patch.apply_patches` with an
explicit separate output. Rebuild from the original input to remove a patch. The CLI
can overwrite its input when `--out` is omitted, so always supply a separate output.

The health hook, death hook, `HeroBarPatch`, hero-bar slot patch, and mixed-payload hook
target different instructions. Compatibility tests exercise patch permutations. Shared
signature anchors also remain independent: the death patch's HERO-bit anchor avoids
the classifier rewritten by `HeroBarPatch`.

## Validation

`tests/sage_patch/test_horde_herobar.py` executes the emitted x86/x87 code with Unicorn and
ABI-conforming native-call stubs. The suite covers both banner-setting branches, uneven member
maximum HP, missing members/bodies, empty and zero-total-maximum lists, 128/129 nodes, malformed
lists, fallback results, and KindOf-independent behavior. It also checks stack balance,
register/flag preservation, a pre-existing x87 value, unchanged object data, idempotency,
signature rejection, and coexistence with other hero patches. Optional reference-binary tests
check frozen anchors against an original executable supplied through
`PYSAGE_ROTWK_GAME_DAT` when running with `--full`.

In-game validation should compare the revised display for an ordinary hero, a banner-driven
horde, and weighted hordes with and without `MELEE_HORDE` or `COMBO_HORDE`. Damage members with
different maximum HP; remove members; verify that full surviving members still produce 100%.
Repeat with the death hook enabled across recruitment and two complete death/revive cycles.
Hero-bar membership, selection, production-building exit, and revived payload remain separate
observations; this display patch does not repair those behaviors.
