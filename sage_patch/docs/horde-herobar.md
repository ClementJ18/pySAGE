# HordeHerobarPatch: Mitgliedergesundheit in der Heldenleiste

Stand: 19.10.2026. Klasse `HordeHerobarPatch`, CLI-Name **`horde-herobar`**,
Quelle `sage_patch/patches/horde_herobar.py`.

Der Nutzer hat die bereitgestellte Cheat-Engine-Auto-Assembler-Version bereits im Spiel
verifiziert. Die pySAGE-Portierung wurde am Referenzbackup statisch und mit x86-/x87-Emulation
geprüft; die erzeugte pySAGE-Binary wurde hier nicht im Spiel gestartet. Deshalb ist der
Repo-Status **partly**. Die übrigen Death-/Revive-Fragen werden dadurch nicht als gelöst markiert.

Aktuelle Korrektur: Für MELEE_HORDE mit `BannerCarrierDestroyHordeOnDeath = Yes` stammt
die Anzeige aus dem registrierten Bannerträger. Der frühere reine Rückfall auf den
Containergetter erklärte den dauerhaft vollen Schlitten-Balken. Die frühere Ausnahme und
ihre Hashes weiter unten dokumentieren den vorherigen Stand; Details der Korrektur stehen
im Abschnitt „Nachprüfung“.

## Verhalten und Berechnung

Auf einem bereits vorhandenen Horde-Eintrag **ohne MELEE_HORDE** wird angezeigt:

```text
Quote = Summe(Body::getHealthRatio aller vorhandenen enthaltenen Objekte mit Body)
        / HordeContain.Slots
```

Der Nenner ist die Sollgröße `Slots`, nicht die Anzahl lebender Mitglieder. Fehlende Mitglieder
tragen damit null bei; verletzte Mitglieder nur ihre aktuelle Quote. Normale Einzelhelden und gewöhnliche Objekte mit `MELEE_HORDE`
verwenden ihren originalen Gesundheitsgetter. Bei `MELEE_HORDE` mit
`BannerCarrierDestroyHordeOnDeath = Yes` wird stattdessen der registrierte Bannerträger
als Gesundheitsquelle verwendet (siehe Nachprüfung unten). Der Patch schreibt ausschließlich in seinen
Stack und liefert einen x87-Wert zurück. Er ändert weder Horde-/Mitglieder-HP noch Slots,
Objektstatus, Auswahl, HeroBar-Listenmitgliedschaft oder Revive-Records.

| Mitglieder einer Fünferhorde | Quote | Anzeige ungefähr |
|---|---:|---:|
| 5 unverletzt | 1,0 | 100 % |
| 3 unverletzt | 0,6 | 60 % |
| 1 unverletzt | 0,2 | 20 % |
| 1 mit 10 % HP | 0,02 | 2 % |
| keine | 0 | 1 % durch vorhandene UI-Mindestbegrenzung |

Bei drei Slots und drei verschiedenen Helden gilt dieselbe Rechnung. Zusätzliche enthaltene
Objekte einschließlich Bannerträger werden ebenfalls mitgezählt. Diese erste Version setzt die
vorgesehene Konfiguration ohne solche Sonderobjekte voraus. Eine unfertige Horde hat keine
zusätzliche Sonderbehandlung. Es gibt keine neue Auswahlkorrektur und keinen Mechanismus,
der einen noch nicht vorhandenen HeroBar-Eintrag anlegt.

## Bestätigte Adressen und ABI

Referenz ist unverändert `tools/BFME-FILES/game.dat.backup`, SHA-256
`5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26`,
11.346.944 Bytes, PE32/i386, ImageBase `0x00400000`. Details zu Sections und Version stehen in
[`hero-horde-death.md`](hero-horde-death.md) und
[`hero-horde-addresses.json`](hero-horde-addresses.json).

| VA | RVA | Datei-Offset | Bedeutung / Originalbytes |
|---|---|---|---|
| `0x0092D5D7` | `0x0052D5D7` | `0x0052D5D7` | `mov eax,[ebp-20h]`, dann BodyInterface aus Object+`0x25C` |
| **`0x0092D5EB`** | **`0x0052D5EB`** | **`0x0052D5EB`** | **Hook: `8B 01 FF 50 14`** |
| `0x0092D5F0` | `0x0052D5F0` | `0x0052D5F0` | Rücksprung; `fmul [0x00BD88D8]`, danach Rundung und Prozentbegrenzung |
| `0x0092D611` | `0x0052D611` | `0x0052D611` | Speicherung Prozentwert, Mindestanzeige 1 |
| `0x0086620E` | `0x0046620E` | `0x0046620E` | native Listeniteration bestätigt Sentinel+`0x34`, Node+`0x08` |
| `0x0086C8AC` | `0x0046C8AC` | `0x0046C8AC` | Slots-Getter bestätigt ModuleData+`0x98` |
| `0x00872A6F` | `0x00472A6F` | `0x00472A6F` | Contain-VTable+`0x7C`: HordeInterface-Adjustor |

`game.dat+52D5EB` aus Cheat Engine bezeichnet eine **RVA**; bei dieser ImageBase wird daraus
VA `0x0092D5EB`. Datei-Offsets werden im Code über die PE-Sectiontabelle aufgelöst.
Die exakten, unveränderten Kontextsignaturen stehen in `ANCHORS`; der Hook wird separat geprüft.

- Angezeigtes Object: `[EBP-0x20]`.
- HORDE-Bit: `[ThingTemplate+0x114] & 0x2000`.
- Object+`0x258`: **ContainModuleInterface**, Runtime+`0x20`.
- ModuleData über `[ContainModuleInterface-0x1C]`; Slots über Data+`0x98`.
- `call [ContainVTable+0x7C]`, ECX=ContainInterface, keine Stackargumente. Rückgabe wird nur
  auf null geprüft; die Listensuche läuft weiterhin über das ursprüngliche ContainInterface.
- Liste: Sentinelpointer `[ContainInterface+0x34]`, nächster Node `[Node]`, Member `[Node+8]`.
- Member+`0x25C`: BodyInterface. `call [BodyVTable+0x14]`, ECX=BodyInterface,
  keine Stackargumente; Ergebnis in **ST(0)**.

Dieser Contain-Zeiger unterscheidet sich vom HordeInterface bei Runtime+`0x11C`, das der
Death-Patch beim Member-Removal verwendet. Die unterschiedlichen Offsets werden nicht vermischt.

## Cave und Schutzpfade

Der 5-Byte-Hook wird durch `E9 rel32` ersetzt; die Cave steht in einer neuen RX-Section
**`.hrdhbar`**, dynamisch hinter der höchsten vorhandenen Section. Der Originalcode
`mov eax,[ecx]; call dword ptr [eax+0x14]` wird auf dem Fallbackpfad vollständig wiederholt.

Die Cave entspricht dem gelieferten Prototyp: `PUSHFD`, `PUSHAD`, 12 Byte Stacklocals
(float Summe, integer Slots, Schleifenzähler). Jeder Membergetter liefert einen x87-Wert;
`FADD [sum] / FSTP [sum]` nimmt ihn sofort wieder vom FPU-Stack. Am Ende folgen
`FLD sum / FILD Slots / FDIVP ST(1),ST(0)`. Damit entsteht exakt **ein** neuer Wert in ST(0),
auch wenn die FPU vorher bereits andere Werte enthielt. Ein FXRSTOR würde das beabsichtigte
Ergebnis wieder entfernen und wird hier deshalb nicht verwendet.

Auf dem Berechnungspfad werden GPRs, EFLAGS und der ursprüngliche ESP wiederhergestellt.
Auf dem Fallbackpfad geschieht dies **vor** den Originalinstruktionen; deren ursprüngliche
Register-/Flag-Nebenwirkungen bleiben damit erhalten. EBP bleibt auf dem originalen HeroBar-Frame.
Die nativen virtuellen Getter müssen wie im Prototyp die callee-saved Register erhalten.

Nullprüfungen schützen Object, Template, Contain, HordeInterface, ModuleData, Sentinel, Node und
Member. Fehlender Member/Body wird übersprungen; ungültiger Listenabschluss oder erschöpftes
Budget verwirft die Teilsumme und verwendet den Originalgetter. Solche Prüfungen erkennen keine
beliebigen unzugänglichen Speicheradressen; die Engine-Objektlayouts bleiben Voraussetzung.

**Explizite Präzisierung der CE-Zahlen:** Slots liegen in der Portierung zwischen **1 und 128
(dezimal)**, und die Liste wird höchstens **128-mal** durchlaufen. Im gelieferten CE-Skript ist
`00000080` ebenfalls 128, während CE ein unpräfixiertes `cmp eax,128` üblicherweise als
**0x128 = 296** interpretiert. Der Python-Patch setzt die im Text beabsichtigte Slotsgrenze von
128 ausdrücklich um. Für die getestete Fünferhorde und die geplante Dreierhorde ändert das nichts.

`apply` prüft die Signaturen und arbeitet vor dem Übernehmen auf einer Kopie. Erneutes Anwenden
ist bei exakt passendem Hook und Cave ein No-op. Beschädigte/fremde Hook- oder Cavebytes werden
abgelehnt; `verify` und die normale Patch-Erkennung stehen im Repository-CLI zur Verfügung.

## Separat aktivieren und kombinieren

Das Schutzskript baut vom gehashten Backup, überschreibt keine abweichende vorhandene Ausgabe
und verändert weder Backup noch installierte Spielbinary:

```sh
# Nur HordeHerobarPatch
python tools/build_hero_horde_patch.py --in tools/BFME-FILES/game.dat.backup --out tools/BFME-FILES/horde-herobar/game.dat --only-herobar

# Death-Hook + gemischte Payload + HordeHerobarPatch
python tools/build_hero_horde_patch.py --in tools/BFME-FILES/game.dat.backup --out tools/BFME-FILES/hero-horde-all/game.dat --payload --herobar

python -m sage_patch verify horde-herobar tools/BFME-FILES/horde-herobar/game.dat
python -m sage_patch verify horde-herobar tools/BFME-FILES/hero-horde-all/game.dat
python -m sage_patch verify hero-horde-death tools/BFME-FILES/hero-horde-all/game.dat
python -m sage_patch verify combo-horde-recruitment tools/BFME-FILES/hero-horde-all/game.dat

# Unveränderte Originalkopie wiederherstellen, ohne Patch oder Backup zu überschreiben
python tools/build_hero_horde_patch.py --in tools/BFME-FILES/game.dat.backup --out tools/BFME-FILES/horde-herobar-restored/game.dat --restore tools/BFME-FILES/horde-herobar/game.dat.json
```

`--herobar` ist ein zusätzlicher Schalter für die bisherigen Death-Builds; ohne ihn bleiben die
bisherigen Builds identisch. `--only-herobar` erzeugt nur den Anzeigepatch und ist nicht mit
`--payload` kombinierbar. Jede Ausgabe erhält ein JSON-Manifest mit Hashes und Signaturen.
Zum gezielten Entfernen aus einer Kombination vom Backup ohne den betreffenden Schalter neu bauen.
Die vorhandenen Death-only- und Death+Payload-Kopien bleiben erhalten.

## Validierung und verbleibender Spieltest

`tests/sage_patch/test_horde_herobar.py` prüft die fünf Beispielquoten, gemischte Verletzungen,
Null-Member, fehlende Bodies, Slotsgrenzen, 128/129 Nodes, zyklische/abgebrochene Listen und
alle Fallbackentscheidungen. Die tatsächlich emittierten x86-/x87-Instruktionen werden mit
Unicorn ausgeführt. Die virtuellen Enginegetter sind ABI-konforme Stubs, die volatile Register
absichtlich verändern und ihren float über ST(0) liefern. Tests prüfen Ergebnis, unveränderte
Objekt-/HP-Daten, GPRs/Flags, ESP und einen bereits vorhandenen Wert unter ST(0).

Weitere Tests prüfen reale Backup-Anker, Idempotenz, beschädigte Signaturen/Cave und alle sechs
Anwendungsreihenfolgen von Todes-, Payload- und Anzeigepatch. Der Nutzerbericht belegt die
CE-Version im Spiel; diese Tests belegen die Portierung und ersetzen keinen Spieltest.

Im Spiel die erzeugte UI-only-Kopie zuerst mit voller und verletzter Fünfer-/Dreierhorde,
Mitgliederverlust und normalem Einzelhelden vergleichen. Danach die Kombination über zwei
vollständige Tod-/Revive-Zyklen prüfen. Vorhandene HeroBar-Anzeige, korrekte Auswahl und
vollständige Revive-Payload sind getrennt zu beobachten. Die Mindestanzeige bei leerer Horde
bleibt 1 %, solange der Originalcode den Eintrag noch zeichnet.

## Erzeugte Kopien und Integrität

- UI-only: `tools/BFME-FILES/horde-herobar/game.dat`, SHA-256
  `f6d3947dc5420515140c6399ebdca6614f82bdb0f7c33a0658871602ea5d11a9`.
- Death + Payload + UI: `tools/BFME-FILES/hero-horde-all/game.dat`, SHA-256
  `3946c448bf125b737f2b8038eefbb3e8cbe6531959455eab11701d5899056d65`.
- UI-only-Cave: VA `0x00ED3000`, Datei-Offset `0x00AD2400`, **244 Bytes**;
  Hookbytes **`E9 10 5A 5A 00`**. In Kombination wird die Cave dynamisch später angelegt.
  [Tatsächlich erzeugte Disassembly](horde-herobar-cave.asm).
- Beide Kopien mit dem Repo-CLI verifiziert; kombinierter Wiederholungsbau bytegleich.
  Die bisherigen Death-only-Ausgaben bleiben bytegleich. Restore-Kontrollkopie und
  unverändertes Backup besitzen beide den oben dokumentierten Referenz-SHA256.

Abschließender Testlauf am 18.10.2026: **2713 bestanden, 4 übersprungen, 2 abgewählt**
(`test_horde_herobar`, `test_hero_horde_death`, `test_combo_horde_recruitment`,
`test_patching`, `test_sagepatch`). Ruff und `git diff --check` bestanden.
Die Emulation und Build-/Restore-Tests des neuen UI-Patches wurden ausgeführt; die Skips
betreffen vorhandene optionale Realbinary-Tests außerhalb der neuen UI-Tests.

## Erweiterung und Integration am 19.10.2026

Die Aggregation gilt jetzt ausschließlich für `HORDE && !MELEE_HORDE`.
Der Ausschluss erfolgt unmittelbar nach dem HORDE-Test, vor Contain-Lookup und Listeniteration;
auch der originale BodyInterface-Zeiger in ECX wird auf dem Fallbackpfad wiederhergestellt.

| HORDE | MELEE_HORDE | Anzeige |
|---|---|---|
| Nein | Nein | Original |
| Ja | Nein | Summe Mitgliederquoten / Slots |
| Nein | Ja | Original |
| Ja | Ja | Original |

Am unveränderten Backup nachgemessen: `KindOf`-Tabelle VA `0x00DA0E68`,
Index **119** (`0x77`); Eintrag bei **`0x00DA1044`** enthält Pointer **`0x00C16028`**
auf `MELEE_HORDE`. Bei Maskenbeginn Template+`0x108` ergibt das Byte
**Template+`0x116`, Maske `0x80`**, entsprechend DWORD Template+`0x114` & **`0x00800000`**.
Originaler Tabelleneintrag und String sind zusätzliche Byteanker. Der separate `HeroBarPatch`
verschiebt seine aktive Namenstabelle, erhält aber die vorhandenen Indizes und Originalstrings.
Der neue Hookcode ist `TEST BYTE PTR [EAX+0x116],0x80 / JNZ OriginalHealth`.

Für `MirkwoodRadagastSchlittenHorde` bleiben damit HORDE und MELEE_HORDE bestehen; die Anzeige
verwendet den ursprünglichen Getter. Die Ursache der gemeinsamen Bannerträger-Gesundheitsmechanik
wird damit nicht behauptet. Die Ausnahme gilt für **alle** Objekte mit MELEE_HORDE.

Die erzeugte Cave hat sich geändert. Alte ausgegebene `.hrdhbar`-Caves werden beim erneuten
Anwenden nicht still überschrieben: vom gehashten Backup neu bauen, z.B. in
`tools/BFME-FILES/horde-herobar-melee/game.dat` oder kombiniert in
`tools/BFME-FILES/hero-horde-all-melee/game.dat`. Die oben aufgeführten älteren Hashes und
244-Byte-Cave beschreiben ausdrücklich die **Version vom 18.10.2026**.

Der Nutzer hat die bisherige Portierung im Spiel als zunächst funktionierend zurückgemeldet.
Die neue MELEE-Ausnahme wurde hier per x86-/x87-Emulation geprüft; kein eigener Spielstart.
Die Tests verlangen für MELEE_HORDE sowohl die originale Gesundheitsquote als auch, dass
**kein** Contain-/HordeInterface-Getter aufgerufen wird. Alle vier KindOf-Kombinationen sind abgedeckt.

Details zum behobenen Death-/HeroBar-Reihenfolgekonflikt und zur vollständigen lokalen
Patchliste: [`hero-horde-death.md`](hero-horde-death.md), Ergänzung vom 19.10.2026.

Aktuelle UI-only-Kopie vom 19.10.2026:
`tools/BFME-FILES/horde-herobar-melee/game.dat`, SHA-256
`9e7fa2f3c4caa14b02c16066722c94445e1abf2d259555f33fc633e968b304b8`.
Die neue Cave umfasst **257 Bytes**; die aktuelle Disassembly ist oben verlinkt.
Die vollständige lokale Auswahl liegt in `tools/BFME-FILES/hero-horde-apply-order/game.dat`.

Abschließender gemeinsamer Testlauf nach der Upstream-Integration: **3509 bestanden,
79 übersprungen, 3 abgewählt**, keine Fehler. Enthalten sind 27 Testdateien mit den geänderten
Upstream-Tests, HeroBar-/Death-/Health-Kombinationen, der tatsächlichen 63er-Liste und den
vorherigen lokalen Aura-Tests. Ruff für die veränderten Patch-/Testdateien und
`git diff --check` bestanden. Kein eigener Spielstart der neuen Ausnahme.

## Nachprüfung: voller Container ist nicht die Schlitten-Gesundheit

Die Rückmeldung „Schlitten bleibt bei vollem Leben“ wurde gegen die tatsächlich genannte
Datei `Edain-Unchained/tools/mod-starter/assets/tools/game.dat` geprüft. Sie enthielt die
257-Byte-Cave samt MELEE-Abfrage und hatte SHA-256
`8257174674470c1e865d08c17a7f2b55eb70364acd6cd25a2b5f037074bcf3a0`.
Die aktive, durch HeroBar verlegte KindOf-Tabelle enthielt unverändert Index 119 = MELEE_HORDE.
Die Bitabfrage war daher nicht die Ursache des 100-Prozent-Verhaltens.

**Die zuvor angenommene Gleichsetzung „Originalgetter = Schlitten-Gesundheit“ war falsch.**
Der Original-HeroBar-Code liest `[angezeigtes Object+0x25C]`, also den Body des Containers.
Der bestätigte Getter **`0x008C1D75`** liefert allein `Body[+8] / Body[+0x10]` bei positivem
Maximum. Er sucht weder Mitglieder noch Bannerträger. Auch ImmortalBody verwendet diesen Getter.
In der lokalen INI ist `MirkwoodRadagastSchlittenHorde` ein ImmortalBody-Container;
`MirkwoodRadagastSchlitten` ist ein separater RespawnBody-Bannerträger. Somit kann die Ausnahme
korrekt greifen und weiterhin einen vollen Container anzeigen, während der Schlitten verletzt ist.
Ein Entfernen von HORDE/Contain verändert außerdem Engineverhalten und war kein belastbarer
Beweis, dass allein der UI-Fallback die Bannerträger-Gesundheit liefern würde.

Die Korrektur unterscheidet jetzt:

| Konfiguration | Gesundheitsquelle |
|---|---|
| Kein HORDE | Ursprünglicher Container-/Einzelheldgetter |
| HORDE ohne MELEE_HORDE | Bisherige Summe der Mitgliederquoten / Slots |
| HORDE + MELEE_HORDE, BannerCarrierDestroyHordeOnDeath = No | Originalgetter |
| HORDE + MELEE_HORDE, BannerCarrierDestroyHordeOnDeath = Yes, gültiger Bannerträger | **Bannerträger-Body::getHealthRatio** |
| letzter Fall mit fehlenden Daten, ID, Object oder Body | Originalgetter als Schutzpfad |

Die Sonderbehandlung ist an die native Konfiguration gebunden, nicht an einen geratenen
Template-Namen. MELEE_HORDE tritt weiterhin niemals in die Mitgliederaggregation ein.
Das Bannermaximum bleibt dessen eigenes Maximum; es wird nicht durch Slots oder Container-HP geteilt.
Die Anzeige ist lokal auf die Heldenleiste begrenzt; es werden keine HP oder Sterbeabläufe geändert.

### Zusätzlich geprüfte Anschlüsse

- `0x0087193C`: vergleicht die entfernte ObjectID mit **HordeContain Runtime+0x26C**.
- `0x00876427`: `lea eax,[esi+0x26C]` im Setzen der Bannerträger-ID.
- HordeInterface = Runtime+0x11C; daraus **Banner-ID bei HordeInterface+0x150**.
  Das ist nicht der gleichnamige Offset Object+0x26C des XP-Trackers.
- `0x00871950`: prüft **ModuleData+0x224** = `BannerCarrierDestroyHordeOnDeath`.
- `0x00449681`: GameLogic::findObjectByID, ECX=GameLogic aus `[0x00DE412C]`,
  ein gepushtes ObjectID-Argument, **RET 4**; null wenn nicht auflösbar.
- BodyInterface des gefundenen Bannerobjects: Object+0x25C, nativer Getter Slot+0x14.

Diese Bytes sind neue Anker im Patch. Die Nachprüfung nutzte das Originalbackup,
`GAME_DAT_DIRECT/hero-bar-horde-health-de.md`, die bestätigte native Bannerbuchhaltung und
Open-BFME-2 als Referenz. Das gesperrte Ghidra-Projekt wurde nicht geändert.

Die Cave hat weiterhin dieselbe PUSHAD/PUSHFD- und x87-Rückgabe-Konvention.
Auf dem neuen Pfad werden Contain und ModuleData geprüft, das Flag gelesen, das HordeInterface
geholt und dessen registrierte Banner-ID nativ aufgelöst. Nullwerte, Container-Selbstreferenz und
fehlender Body gehen auf den ursprünglichen Getter. Ein gültiger Bannergetter liefert genau
**einen** Wert in ST(0), bevor Register und Flags wiederhergestellt werden.

### Regression statt selbstbestätigender Testwerte

Der neue Fall setzt den Container auf volle HP, den Banner auf 25 %, und verwendet die echten
Maschinenbytes von `0x008C1D75` für den Gesundheitsgetter. Die alte 257-Byte-MELEE-Version
scheitert an diesem Test mit **1,0 statt 0,25**; die korrigierte Version besteht ihn.
Zusätzlich geprüft: Banner bei 0/100 %, fehlender GameLogic, fehlende Banner-ID, nicht auflösbare
ID, Container-Selbstreferenz, fehlender Bannerbody, Contain/ModuleData/HordeInterface sowie
unveränderte Mitgliederaggregation für Nicht-MELEE-Horden. Dies ist weiterhin Emulation,
kein eigener Spielstart der Korrektur.

### Ergebnis und aktualisierte Testdatei

- Korrigierte Cave: **384 Bytes**, dynamisch allokiert; aktuelle Disassembly in
  `horde-herobar-cave.asm`.
- Abschlusslauf: **3527 bestanden, 79 übersprungen, 3 abgewählt**; Ruff und Diffprüfung bestanden.
- Nur UI: `tools/BFME-FILES/horde-herobar-banner/game.dat`, SHA-256
  `43f7da5b0e4b6573037b4c2953f965aa292166ba8d754efdd6b94245237fb348`.
- Death + Payload + UI: `tools/BFME-FILES/hero-horde-all-banner/game.dat`, SHA-256
  `ec6cc1317b356b026cdd6569032adc5f43e0865b1a1a2c9e6fd815d717bfbf71`.
- Tatsächliche 63er-Auswahl: `tools/BFME-FILES/hero-horde-apply-order-banner/game.dat`, SHA-256
  `a7c0afa4572eafb09861567a5932ccd87ef5e963e46af2fff6826ec2cef7e85d`.
  Jeder Patch ist auch nach Anwendung aller anderen verifiziert.

Die vom Nutzer genannte Datei
`/home/ostkannit/projects/Edain-Unchained/tools/mod-starter/assets/tools/game.dat`
wurde durch die vollständige korrigierte 63er-Auswahl ersetzt, anschließend byteweise verglichen
und verifiziert. Die bisherige Version liegt unverändert unter
`/home/ostkannit/Documents/Codex/work/hero-horde-banner-review/game.dat.before-banner-proxy`;
auch `tools/BFME-FILES/hero-horde-apply-order/game.dat` ist noch die vorige 63er-Version.
Vor dem Austausch wurde geprüft, dass sich die Testdatei seit der Untersuchung nicht geändert hat.
Der Austausch erfolgte atomar; das Originalbackup wurde nicht verändert.

Die korrigierte Binary wurde hier nicht im Spiel gestartet. Der verbliebene Spieltest ist,
Radagasts echten Schlitten/Bannerträger zu verletzen und den HeroBar-Balken mit dessen
Gesundheit zu vergleichen. Die Kaninchenanzahl soll diesen Sonderbalken nicht mehr bestimmen.
