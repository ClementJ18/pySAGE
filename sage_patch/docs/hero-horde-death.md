# Hero-Horde: nativer Todeseintrag vor der Leerhorden-Zerstörung

Stand: 18.10.2026. **Erste experimentelle Version; kein Spielstart und keine Laufzeitbestätigung.**
Die vorhandene Engine-Leerheitsentscheidung ist der vereinbarte Auslöser. Der Patch zählt keine
Mitgliedertode nach: Auch anderweitig geleerte Zielhorden können deshalb den Todeseintrag auslösen.
Reverse-Engineering-Grundlage: übergebener Hero-Horde-Befund, gegen das lokale Backup erneut
geprüfte Maschinenbytes und die vorhandenen Repository-Analysen. Keine Binary wird eingecheckt.

## Ziel und Grenzen

Eine Horde mit drei **verschiedenen** Hero-Mitgliedern trägt selbst `KindOf = HERO HORDE`,
`ImmortalBody`, einen XP-/Rank-Tracker und `RespawnUpdate` mit einer passenden
`RespawnRules`-Regel **AutoSpawn:No**. Die InitialPayload-Liste enthält drei unterschiedliche
Templates mit je einem Mitglied; diese Datenkonfiguration ist Voraussetzung, kein Bestandteil
oder behauptetes Testergebnis dieses Binärpatches.

Nach Entfernung des letzten Mitglieds führt die Engine ihre vorhandene Leerheitsprüfung aus.
Unmittelbar vor ihrem Destroy-Request ruft die Cave
`void __thiscall RespawnUpdate::DeathPreparation(RespawnUpdate *ECX)` auf der **Horde** auf.
Die native Funktion erledigt DeathAnim/FX, HeroDeath, EffectivelyDead und HeroRecord.
Danach folgt unverändert der originale Destroy-Request. Es werden weder `RespawnBody`,
`OBJECT_KILL`, künstlicher Schaden, künstliche Horde-HP noch ein erfundenes DamageInfo verwendet.
`Object::OnDie` wird nicht zusätzlich aufgerufen.

Der nachgereichte, vom Nutzer in Cheat Engine bestätigte Gesundheitsbalken-Prototyp ist jetzt
als separater [`HordeHerobarPatch`](horde-herobar.md) implementiert (`horde-herobar`). Er berechnet
Mitgliedergesundheit / Slots und lässt sich unabhängig zuschalten. Die bisher hier dokumentierte
Datenlücke für **diesen Gesundheits-Hook** ist damit geschlossen. Auswahl und Eintragung in die
Heldenleiste bleiben eigenständige offene Fragen. Die allgemeinen Repo-Patches `herobar` und
`hero-bar-slots` erfüllen andere Aufgaben.

## Binary und Adressierung

Eingabe: `tools/BFME-FILES/game.dat.backup`, unverändert aufbewahren.

- Größe: **11.346.944 Bytes**.
- SHA-256: `5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26`.
- PE32/i386, ImageBase **0x00400000**.
- COFF-Zeitstempel: `0x460DA09E`, **30.03.2007 23:43:26 UTC**. Kein Beweis eines Release-Datums.
- Dateisystem-mtime beim Prüfen: **28.09.2024 18:21:42 UTC**. Kein Versionsbeweis.
- Versionsressourcen enthalten **2.1.2614.37001** und zusätzlich **1.00.65535.65535**.
  Ältere Repo-Dokumente schreiben dafür `2.01.2614.37001`.
- Das Backup enthält zusätzliche Sections wie `stxt774`, `stxt371`, `.mackt…`, `.danetta`.
  Es wird als konkrete Referenzdatei behandelt, nicht als nachgewiesen unveränderte Herstellerdatei.

**VA** ist die virtuelle Adresse im bevorzugten Image; **RVA = VA − ImageBase**.
Der Datei-Offset ergibt sich aus `PointerToRawData + VA − SectionVA`, nicht grundsätzlich
allein aus der ImageBase. Die hier verwendeten Originalsections haben zufällig RawOffset=RVA.
Die vollständige, am PE geprüfte Sectiontabelle und Adresstabelle stehen in
[`hero-horde-addresses.json`](hero-horde-addresses.json).

| Section | RVA | RawOffset | VirtualSize |
|---|---:|---:|---:|
| `.text` | `0x1000` | `0x1000` | `0x7CF000` |
| `.rdata` | `0x7D0000` | `0x7D0000` | `0x1B9000` |
| `.data` | `0x989000` | `0x989000` | `0x81000` |

## Lösungsweg und geprüfte Anschlüsse

1. Member-Removal identifizieren: `0x0087370B`, ContainInterface in ECX; nach Prolog ESI=Interface
   und EDI=entferntes Member. Interface liegt bei Runtime+`0x11C`. Owner ist `[ESI-0x114]`,
   ModuleData `[ESI-0x118]`. `[EBP+8]` wird bereits bei `0x00873784` überschrieben.
2. Nach `0x00873821` ist EBX=Runtime. `0x0087383B` ruft `0x00865598` auf; die oft genannte
   Adresse `0x00873835` bezeichnet den Beginn der Argumentvorbereitung, nicht die CALL-Instruktion.
   `0x00873845` prüft den Listensentinel; `JNZ` bei `0x00873847` und `0x0087384D` gehen zu
   `0x0087387D`. Nebenwirkung `0x005DD9EE` bei `0x00873867` bleibt vor unserem Hook.
3. **Hook `0x0087386C`**, Original **`FF B6 EC FE FF FF`**:
   `push dword ptr [esi-0x114]`. Ersatz: fünf Byte `E9 rel32` plus ein `90`.
   Rücksprung zu **`0x00873872`**: `mov ecx,[0x00DE412C]`; dann unverändert
   **`0x00873878: call 0x0062BBAB`**. Contain wird danach weiter benutzt; keine vorgezogene Freigabe.
4. Der nachgewiesene Aufruf bei `0x008C565D` verwendet nur ECX und kein DamageInfo.
   `0x008B3744` endet bei `0x008B38A1` mit `RET`, nicht `RET 4`.
5. Modul-Lookup wie in `RespawnBody` und `castle-unpack-buttons`:
   `[0x00DD90E4]` als ECX; `push 0x00C0B098` (`RespawnUpdate`);
   `call 0x005487EC` (`ret 4`); danach `push key`, ECX=Horde,
   `call 0x0068BDA5` (`ret 4`). Kein hartcodierter, unbestätigter NameKey.
6. Native Regelwahl verwendet `0x00603AF6` auf Data+`0x10C`, Rang aus
   `[Object+0x26C]+0x24`, bei fehlendem Treffer Rang 1. Rückgabe ist entweder Regelnode oder
   Tree-Sentinel. Ohne Regel erzeugt `DeathPreparation` nur einen Scheduler-Auftrag, keinen
   HeroDeath/Record. Unsere Vorprüfung überspringt diesen wirkungslosen Pfad.

| VA | Funktion / Feld | Evidenz / Sicherheit |
|---|---|---|
| `0x00C5B1F8`, Slot `+0x34`=`0x00C5B22C` | Horde-Interface, Member-Removal | Pointerbytes bestätigt; semantischer Name aus RE |
| `0x00C5BECC`, `0x00C5CFDC` | weitere Slots auf `0x0087370B` | Pointerbytes bestätigt |
| `0x008B3744` | DeathPreparation, thiscall, keine Stackargumente | Prolog, nativer Aufruf, RET bestätigt |
| `0x00C6C360` | RespawnUpdate primäre Runtime-VTable | Typguard; Konstruktor/Repo-Analyse |
| `0x006A1CE2` | HeroDeath-Benachrichtigung | CALL in DeathPreparation bestätigt |
| `0x0068D950` | setEffectivelyDead, Object+`0x458` Bit 0 | Bitlesen/-setzen und Aufruf bestätigt |
| `0x00781792` | HeroManager addEntry(Object*, AutoSpawn), thiscall | nativer CALL und Repo-Analyse |
| `0x0068B678`, Player+`0x758` | kontrollierender Spieler und HeroManager | nativer Fluss bestätigt |
| `0x00780DD4` | HeroRecord-Konstruktor, `0xE8` Bytes pro Record | vorhandene statische Repo-Analyse |
| `0x007812F7` | Schreiber Record+`0xB4` | **MOV [eax+B4],esi erneut bestätigt** |
| `0x008A250A`, `0x0078142F` | ProductionUpdate ruft reviveRecord(key, spawnInfo) | CALL und `entry+0x10` als key bestätigt |
| `0x007814C2`, `0x006D165E` | Factory erzeugt neues Objekt | CALL bestätigt |
| `0x00781722`, `0x007813FF` | anschließendes Entfernen des Records | übergebener/Repo-RE-Befund |
| `0x008A2C07`, `0x008B38A2` | ProductionUpdate initialisiert neuen RespawnUpdate | CALL bestätigt; state=4 aus RE |
| `0x00871B9B`, `0x00871BAB`, `0x00871BB3` | onObjectCreated, Producer-Lesehook, JNE | vorhandener separat prüfbarer Payload-Patch |
| `0x0065B165`, `0x00651186`, `0x00651212` | ImmortalBody-Registry und Factories | übergebener statischer Befund |
| `0x008C4A0A`, `0x008C3841` | ImmortalBody- und Basiskonstruktor | neuer Disassembly-Abgleich |
| `0x00C72090`, `0x00C71FE0` | Immortal Runtime-/BodyInterface-VTable | Konstruktorstores bestätigt |
| `0x008C47DE`, `0x008C4AB4`, `0x008C31A5` | RuleHealth-Anpassung, Immortal-Clamp, Basis-HP-Änderung | Slots bestätigt; Semantik aus übergebenem RE |
| `0x00850C32` | Scheduler | nativer No-Rule-Pfad bestätigt |

Weitere Details: [`cooldown-through-death.md`](cooldown-through-death.md),
[`hero-revive-ownership.md`](hero-revive-ownership.md),
[`combo-horde-recruitment.md`](combo-horde-recruitment.md).

## Cave und Schutzabfragen

Neue RX-Code-Section **`.hhrdead`**, dynamisch hinter der höchsten Section, keine feste Cave-VA.
`build_code(base_va)` erzeugt deterministisch alle Relativsprünge. Ablauf:

```text
PUSHFD / PUSHAD
EBP = ESP; temporärer Stackplatz, ESP auf 16 Bytes ausrichten; FXSAVE [ESP]
Owner = [ursprünglichem ESI-0x114]
prüfen: Owner, Template, HERO und HORDE
prüfen: nicht effectively-dead, BodyInterface vorhanden und exakt ImmortalBody
prüfen: XP-Tracker, NameKeyGenerator, RespawnUpdate vorhanden
prüfen: RespawnUpdate-VTable, Owneridentität, state 0 oder 4, ModuleData und Treehead
native Regelwahl: aktueller Rang, sonst Rang 1; kein Treffer -> Ende
AutoSpawn im Regelnode+0x20 muss 0 sein
ECX = RespawnUpdate; CALL DeathPreparation  (keine Stackargumente)
FXRSTOR [ESP]; ESP = EBP; POPAD / POPFD
PUSH [ESI-0x114]  (Originalinstruktion)
JMP 0x00873872
```

HERO: `[Template+0x113] & 4` = `[Template+0x110] & 0x04000000`;
HORDE: `[Template+0x115] & 0x20` = `[Template+0x114] & 0x00002000`.
Beide Bitpositionen sind zusätzlich an bestehenden Engine-Tests verankert.
ImmortalBody wird anhand der exakten BodyInterface-VTable erkannt. Abgeleitete/andere Bodies
sind bewusst ausgeschlossen. Native Regelwahl ist `thiscall(tree, rank*)`, `ret 4`.
Die vier Byte für den temporären Rang werden separat entfernt.

Nach DeathPreparation setzt der native Pfad `effectively-dead`; die zusätzliche Bitprüfung
verhindert einen späteren zweiten Eintrag für dasselbe Objekt. Sie ist **keine vollständige
Reentranzsperre** während früher DeathAnim/FX-Callbacks, bevor die Engine das Bit setzt.
Zustand 0/4 allein ist keine Once-only-Sperre: DeathPreparation setzt diesen Zustand nicht um.
Fremde Hordes ohne alle obigen Eigenschaften setzen ihren originalen Destroy-Pfad fort.
Die Guards begrenzen auf diese Eigenschaften, nicht auf einen fest benannten INI-Template-Namen.

## Payload, Revive und offene Punkte

`combo-horde-recruitment` ist **separat** zuschaltbar. Er ersetzt den Producer-Lesezugriff bei
`0x00871BAB` und lässt für mehr als eine InitialPayload-Zeile das native createPayload laufen.
Der bestehende `JNE` bei `0x00871BB3` bleibt bestehen. Kein pauschales NOP dieser Verzweigung.
Beide Patches greifen an unterschiedlichen Stellen an und werden in beiden Reihenfolgen geprüft.

Die Factory im nativen Revive erzeugt ein neues Objekt; die Produktion ruft danach
`0x008B38A2` auf. Daraus folgt noch **kein Laufzeitnachweis**, dass drei unterschiedliche
Mitglieder nach jedem Revive korrekt entstehen. Diese Version liefert Death-only und
Death+Payload als getrennte Builds zur Überprüfung. Der Payload-Patch wirkt auf **alle**
Horden mit mehreren Payload-Zeilen, nicht nur Hero-Horden.

Die ursprüngliche Frage nach Record+`0xB4` ist eingegrenzt: Im vorhandenen Repo ist der
Schreiber `0x007812F7` bereits dokumentiert und dessen MOV wurde am Backup bestätigt.
`ProductionUpdate` liest den key aus `entry+0x10` und übergibt ihn an `0x0078142F`.
Die vollständige Queue-/Record-Verknüpfung für die neue Horde bleibt trotzdem im Spiel zu
prüfen; der anfängliche Nullwert darf nicht eigenmächtig ersetzt werden.

Weitere Grenzen: native DeathAnim/FX und EffectivelyDead können weitere Module aufrufen.
Weder die Emulation noch Signaturen beweisen deren Verträglichkeit mit sofort folgendem
Destroy. Spielerwechsel/temporäre Übernahme werden hier nicht speziell behandelt;
DeathPreparation verwendet den aktuell kontrollierenden Spieler. Keine Multiplayer-, Save-
oder Replay-Kompatibilität behauptet; alle Teilnehmer brauchen denselben Logic-Patch.

## Sicher bauen, verifizieren und wiederherstellen

Im Repository, mit Python >=3.12 und ohne zusätzliche Laufzeitpakete:

```sh
python tools/build_hero_horde_patch.py --in tools/BFME-FILES/game.dat.backup --out tools/BFME-FILES/hero-horde-death/game.dat
python tools/build_hero_horde_patch.py --in tools/BFME-FILES/game.dat.backup --out tools/BFME-FILES/hero-horde-death-payload/game.dat --payload
python -m sage_patch verify hero-horde-death tools/BFME-FILES/hero-horde-death/game.dat
python -m sage_patch verify hero-horde-death tools/BFME-FILES/hero-horde-death-payload/game.dat
python -m sage_patch verify combo-horde-recruitment tools/BFME-FILES/hero-horde-death-payload/game.dat
python tools/build_hero_horde_patch.py --in tools/BFME-FILES/game.dat.backup --out tools/BFME-FILES/hero-horde-restored/game.dat --restore tools/BFME-FILES/hero-horde-death-payload/game.dat.json
```

Das sichere Buildskript verlangt den exakten Referenz-SHA256, einen getrennten Ausgabepfad und
verbietet `.backup` als Ausgabe. Bestehende andere Inhalte werden abgelehnt; identischer
Wiederholungsbau ist ein No-op. `game.dat.json` protokolliert Quell-/Zielhash, Patches, Sections,
Hook-Adresse und Ankerbytes. Restore prüft Backup- und Patchhash und erstellt eine **weitere
Originalkopie**; auch der Patch wird dabei nicht überschrieben. Zur Deaktivierung eine verifizierte
Originalkopie im Spiel verwenden, bzw. aus dem Backup nur die gewünschten Patches neu bauen.
Das generische Repo-CLI kann ohne `--out` seine Eingabe überschreiben; für diesen PoC deshalb
zum Bauen das oben genannte Schutzskript verwenden.

`HeroHordeDeathPatch.apply` selbst arbeitet auf einer temporären Kopie, prüft vor dem Installieren
alle Anker und akzeptiert bei Wiederholung nur exakt passende Hook-/Cavebytes. Veränderte oder
fremde Cavebytes führen zum Fehler. Quellbackup und installierte Spieldatei werden nicht angefasst.

## Prüfung ohne Spielstart und Spieltestplan

Die Tests verwenden ein synthetisches PE, das lokale echte Backup und Unicorn-x86-Emulation.
Native Aufrufe in der Cave-Emulation sind **ABI-konforme Stubs**, keine simulierte laufende Engine.
Geprüft werden Schutzpfade, Rang-1-Fallback, AutoSpawn-Ausschluss, ursprüngliche PUSH-Semantik,
Stackbilanz, Register/Flags und FPU-Control/SSE-Wiederherstellung, Wiederholungsaufruf,
Idempotenz, manipulierte Signaturen/Cave und gemeinsame Anwendung mit dem Payload-Patch.

```sh
python -m pytest tests/sage_patch/test_hero_horde_death.py tests/sage_patch/test_combo_horde_recruitment.py -q
```

Im Spiel noch durchzuführen (jeweils Death-only / Death+Payload vergleichen):

1. Drei verschiedene Helden einmalig erzeugen; Mitglieder, Horde-Auswahl und HeroBar protokollieren.
2. Erstes und zweites Mitglied verlieren: kein Horde-HeroDeath/Record.
3. Letztes Mitglied verlieren: genau eine Horde-HeroDeath-Meldung und ein richtiger Revive-Eintrag;
   kein Crash durch nachfolgenden Destroy, korrekter Spieler und Kosten/Zeit.
4. Native Revive-Produktion abschließen: Horde erscheint mit drei richtigen unterschiedlichen
   Mitgliedern, korrekten XP/Upgrades und UI; Record/Produktionskey beobachten.
5. Zweiten vollständigen Tod-/Revive-Zyklus wiederholen, auf doppelte Records/Mitglieder prüfen.
6. Normale Horden, Einzelhelden, Horden ohne RespawnUpdate, fehlende Regel und AutoSpawn:Yes
   als Kontrollen prüfen. Leeren durch andere Vorgänge und eigene DeathFX separat testen.
7. Gesundheitsanzeige separat mit `horde-herobar` prüfen; Auswahl-/Listenprobleme weiterhin gezielt messen.

## Tatsächlich ausgeführte Validierung (18.10.2026)

- Patch-, Payload- und Frameworktests: **2658 bestanden, 4 übersprungen, 2 abgewählt**.
  Nach Ergänzen eines zusätzlichen Konstruktorankers nochmals gezielte Tests:
  **94 bestanden, 3 übersprungen**. Die übersprungenen Payload-Tests erwarten eine separate
  lokale `game.dat` im Repository-Root; unser neues Realbinary-Backup-Test wurde ausgeführt.
- Ruff für die drei neuen Python-Dateien bestanden.
- Beide Ausgabekopien erfolgreich gebaut und verifiziert; kombinierter Wiederholungsbau
  bytegleich. Restore erzeugt eine bytegleiche Referenzkopie mit Original-SHA256.
- Backup-SHA256 vor/nach dem Build identisch. Keine Spieldatei installiert.

| Ausgabe unter `tools/BFME-FILES/` | SHA-256 |
|---|---|
| `hero-horde-death/game.dat` | `eb319a7b077c10d153901d7de7a61a4af046365eb45fb8d6c516019bd8d87491` |
| `hero-horde-death-payload/game.dat` | `e472a2974c451efdc2239d5083c7a51d38228a3307ae6b148e9829c4d742747c` |
| `hero-horde-restored/game.dat` | `5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26` |

Die Datei [`hero-horde-cave.asm`](hero-horde-cave.asm) zeigt die tatsächlich erzeugte Cave
am finalen Codeort einschließlich Hookbytes und Rücksprung. Maschinelle Integrität und
ABI-Emulation sind damit geprüft; Spielverhalten und HeroBar sind weiterhin offen.

## Reihenfolgekonflikt und Upstream-Integration am 19.10.2026

Der Fehler aus `applymypatches.py` wurde mit dem echten Backup reproduziert:
`HeroBarPatch()` läuft vor `HeroHordeDeathPatch()`. HeroBar ersetzt die Klassifikation bei
`0x0092CD7F`; der Death-Patch verlangte bisher in seinem Prüfanker ab `0x0092CD7C`
noch die Originalbytes dieser Klassifikation. Das führte zu `signature mismatch`, obwohl die
Patch-Hooks selbst (`0x0092CD7F` und `0x0087386C`) nicht überlappen.

Behoben durch einen unabhängigen HERO-Anker bei **VA `0x0044A573`**, RVA/Datei-Offset
`0x0004A573`: **`F6 80 13 01 00 00 04 74 05 FF 45 C0 EB 03`**.
Auch dort liest die native Engine `Template+0x113 & 4`; der Death-Hook und sein emittierter
Code bleiben unverändert. Alle übrigen DeathPreparation-, Rule- und Destroy-Signaturen bleiben
streng geprüft. Es wird keine fremde HeroBar-Cave anhand eines unkontrollierten JMP akzeptiert.

Regressionen prüfen HeroBar, Death und Health in allen sechs Reihenfolgen auf einem synthetischen
PE. Zusätzlich liest ein lokaler Test die **tatsächliche** `patches`-Liste aus `applymypatches.py`
über ihren geschützten Nicht-`__main__`-Pfad, wendet alle 63 Patches in dieser Reihenfolge nur
auf eine Speicher-Kopie des Backups an und verifiziert anschließend **jeden** Patch.
Darin enthalten sind `HeroBarPatch`, `HeroBarSlotsPatch(32)`, `HeroRecruitParallelPatch`,
`ReviveObjectBindingPatch` und `HordeHerobarPatch`. Die Liste wurde nicht umgeordnet.
Es werden dabei keine Ausgaben in Edain-Unchained oder installierte Spiel-/Editor-Dateien geschrieben.

`git pull --no-rebase upstream master` aktualisierte den Branch von `28e4a37` auf
**`4b0cdd8408f9e305a766131cd616db135c43fe7d`** (Fast-forward). Anschließend wurden alle lokalen
Änderungen wieder eingearbeitet. Der einzige Inhaltskonflikt war ein gleichzeitiges Anhängen
von Adressen in `sage_patch/addresses/objects.py`: Upstream- und lokale Aura-Adressen wurden
beide erhalten. Upstream verschob `HeadlessPatch` aus `patches.experimental` nach `patches`;
der entsprechende Import in der lokalen, ignorierten `applymypatches.py` wurde angepasst.
Vorherige lokale Änderungen einschließlich Aura-Patch, OS-Name-Test und generierten Manifesten
bleiben erhalten. Sicherungs-Stash: `138f649709ac0674023627af0cae3c8f691d07ef`.

Die Prüfung belegt gemeinsame Anwendung und statische Integrität; sie ist kein zusätzlicher
Laufzeitnachweis für das native Death-/Revive-Verhalten im Spiel.

Zusätzlich fiel bei den erweiterten Upstream-Emulationstests ein geerbter Fixturefehler auf:
`TestSelection.test_all_five_together` in `test_replacement_transfer_emulated.py` setzt inzwischen
alle sieben Flags einschließlich HORDE. Das `World`-Testmodell für gewöhnliche Objekte hatte den
`OBJECT_GET_HORDE_IFACE`-Aufruf noch nicht gestubbt. Dafür wurde die native Null-Rückgabe im
Testmodell ergänzt; der Produktionscode von `replacement_transfer.py` bleibt unverändert.
Der betroffene Modultest besteht mit 35 Tests (2 optionale Tests übersprungen).

Neue getrennte Ausgaben vom 19.10.2026 (jeweils mit JSON-Manifest):

| Pfad unter `tools/BFME-FILES/` | Inhalt | SHA-256 |
|---|---|---|
| `horde-herobar-melee/game.dat` | Nur HealthBar mit MELEE-Ausnahme | `9e7fa2f3c4caa14b02c16066722c94445e1abf2d259555f33fc633e968b304b8` |
| `hero-horde-all-melee/game.dat` | Death + Combo-Payload + HealthBar mit Ausnahme | `3e0dcf870c736249fa2beb19ba720539e5aac7fbf5f23b586d5caae0d4cc682d` |
| `hero-horde-apply-order/game.dat` | Alle 63 Patches exakt aus `applymypatches.py` | `8257174674470c1e865d08c17a7f2b55eb70364acd6cd25a2b5f037074bcf3a0` |

Die letzte Ausgabe übernimmt **genau** die lokale Liste; sie fügt keinen dort nicht genannten
Combo-Payload-Patch hinzu. Ihr Manifest enthält die Reihenfolge, Parameter, den Hash des
Auswahlscripts und den Upstream-Commit. Sämtliche Patches wurden nach dem Gesamtbau erneut
verifiziert. Die Dreierkombination wurde zweimal bytegleich gebaut. Wegen der geänderten
Signaturmanifeste neue Ausgabepfade verwenden; alte Dateien werden weiterhin nicht überschrieben.
Backup und bereits vorhandene Ausgaben bleiben erhalten.

Abschließender gemeinsamer Testlauf nach der Upstream-Integration: **3509 bestanden,
79 übersprungen, 3 abgewählt**, keine Fehler. Enthalten sind 27 Testdateien mit den geänderten
Upstream-Tests, HeroBar-/Death-/Health-Kombinationen, der tatsächlichen 63er-Liste und den
vorherigen lokalen Aura-Tests. Ruff für die veränderten Patch-/Testdateien und
`git diff --check` bestanden. Kein eigener Spielstart der neuen Ausnahme.
