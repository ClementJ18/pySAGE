# SpecialPower music (experimental)

`special-power-music` adds one optional field to the existing `SpecialPower` block:

```ini
SpecialPower SpecialAbilityMusicExample
    Enum           = SPECIAL_WORD_OF_POWER
    ReloadTime     = 150000
    MusicOnTrigger = MySpecialMusic 123000
End
```

`MySpecialMusic` is a music event already defined by the mod. The second token is an
unsigned decimal duration in milliseconds, from `0` through `2147483647`; zero disables
this power's music. An absent field leaves stock behavior unchanged. A zero-duration or
unconfigured power does not cancel another power's active track. Names are limited to
255 bytes and must be a single INI token. Malformed/missing/extra tokens, negative or
out-of-range durations, and a full configuration table reject the new value without
changing an existing value. The cave's dword at `+0x0C` counts rejected definitions.
The `.sagepatch` surface uses the existing `Opaque[]` token-list convention; it recognizes
the field, but does not provide a music-reference or duration-range lint diagnostic.

Apply through the existing CLI or `SpecialPowerMusicPatch` API. This patch is for the
RotWK/AdH 2.01 `game.dat` build only. It does not patch Worldbuilder's independent INI
parser: use editor INIs without this field until a Worldbuilder counterpart is available.

The trigger wraps the `GET_FINAL_OVERRIDE` call at `0x0089718C` inside
`SpecialPower_NotifyTriggeredAndPlayInitiateAudio`, retaining its original return value,
flags and pending audio-constructor argument. Each peer that executes this activation
path requests local music, without a caster-owner filter. The stock music action helper
constructs the AudioEvent, sets the repeat count to one, and calls stock Music-Push.
Its completion flag is empty, so it does not create or update a gameplay/script flag.
The track is pushed on interruption level **1**, above the normal scripting level **0**.
The helper's sixth argument is this level, not a generic option or notification flag.
Pop and Resume both target level 1; pushing on level 0 would overwrite the script track
and make Resume(0, 1, ...) ineffective. This distinction was verified after an in-game
test exposed the wrong-level failure despite correct deadline processing.
Retrigger queues stock Music-Pop for the active special track, then one Music-Push, and
replaces the single deadline. The frame jump at `0x00639EEB` checks `timeGetTime` through
IAT `0x00BD0920`, calls stock Music-Resume at/after expiry, and continues at `0x00639FEF`.
All general registers, flags, x87/SSE state and MXCSR are preserved around audio work.

Configuration and `{active, deadline, audio-owner}` state live in the writable `.spmusic`
cave. This feature does not grow the stock `SpecialPowerTemplate` (`0x88`), write a
snapshot, change gameplay state, or use GameLogic's frame hook. The configuration table
holds up to 1024 distinct template IDs with collision-safe bounded lookup. The key is
the engine's stable numeric template ID at `+0x14`, **not a NameKey**: the binary assigns
that ID before parsing and copies it into overrides; the name itself is an AsciiString
at `+0x10`. Using the existing ID avoids inserting names into the global NameKey registry
from the client-audio path. No memory addresses are used as configuration keys.

The field table is read live and appended, preserving previous extensions. Hero-Mana
therefore composes in either order: it may grow the template for `ManaCost`, whereas
MusicOnTrigger still writes at offset zero only through its own side-table parser.
Duplicate application, conflicting frame/trigger bytes and damaged generated code are
rejected. The feature does not modify `hero_mana.py` or its hooks.

Known limitations and release checks:

- Pause/focus uses wall clock. The deadline can advance while audio is paused; the first
  executed frame at or after the deadline requests Resume. It tests expiry, not equality.
  The 32-bit wrap comparison assumes the check is not suspended for 2^31 milliseconds
  (about 24.9 days) after expiry. Retrigger replaces the timer completely.
- Config overrides with the same template ID are last-definition-wins. An override
  omitting MusicOnTrigger inherits the prior row; `MusicOnTrigger = MySpecialMusic 0`
  disables it. Default-template copies into *new IDs* do not inherit the side-table row:
  declare the field on each power. Removal of a map override does not restore its previous
  row. Runtime INI reloads and map-specific MusicOnTrigger overrides are not supported;
  restart the game after changing these definitions.
- There is no map-reset/save-load hook. Audio teardown clears an active timer when the
  AudioManager pointer becomes null or changes. A map switch retaining the same audio
  object can retain the timer and later request Resume in the new map. Special music is
  not saved/restored. Map transitions, save/load and multiple matches in one process need
  in-game acceptance testing before shipping.
- The music stack is shared with map/campaign scripts. External Push/Pop/Reset/Resume
  operations are not ownership-tracked; a later retrigger or expiry can affect music
  installed by another script. Avoid simultaneous independent music-stack controllers.
- Missing/disabled/unresolvable music follows the stock audio helper's behavior. The
  helper returns no reliable playback-success result, so a configured trigger still
  arms the deadline. The patch does not guarantee that a track will be audible or that
  the duration matches the asset. Null audio/local-player pointers skip a new request.
- MP audio is local on each peer; playback start/expiry are not sample-synchronized.
  Gameplay/snapshot state stays unchanged. All clients must ship the same patched binary
  and INIs; mixed patched/unpatched clients are unsupported. Observer/replay, AI, spellbook
  and different SpecialPower-module paths require in-game coverage; the hook only sees
  activations passing through the identified notification helper.
- **CRC review:** this side table is outside SpecialPowerTemplate and has no explicit
  config-CRC integration. No reusable INI-config-CRC extension helper was found. The
  existing `binary-attest` patch hashes `.text` and its own code, not this runtime table;
  it cannot attest to the parsed MusicOnTrigger values. Stock INI/file checks may detect
  differing files, but detection of a differing parsed row is not established. Different
  rows can produce different audio without a detected config mismatch. Do not add local
  deadlines, audio pointers or active flags to gameplay CRCs to compensate for this.

Automated checks execute the emitted x86 with mocked stock audio/tokenizer calls and
exercise parser rejection, retrigger ordering, late expiry, wraparound, preserved state,
binary verification and Hero-Mana composition. They establish ABI/control-flow behavior,
not real audio playback or multiplayer acceptance. Before release, test baseline INIs,
two players retriggering different tracks, disabled music, pause/focus, return to normal
battle/peace music, save/load, map transitions and a second match in the same process.

An in-game retest with `MusicOnTrigger = Kairo_Radagast 10000` confirmed correct
return to normal music after correcting the push level to 1. This is a single-user
playback confirmation; multiplayer and the lifecycle cases above remain unverified.
