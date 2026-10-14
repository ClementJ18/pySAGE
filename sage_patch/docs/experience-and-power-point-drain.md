# Erfahrung, Level und Schicksalspunkte abziehen

Untersuchung vom 09.10.2026. Grundlage: lokale OpenBfme-/OpenBfme2-Quellen,
deren gezielt gelesene Matching-Einträge und direkte Disassemblierung von
`tools/BFME-FILES/game.dat.backup`. Kein Patch implementiert oder im Spiel getestet.

RotWK-Dateiversion: 2.01.2614.37001; ImageBase 0x00400000.
SHA-256: `5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26`.
Alle RotWK-Adressen unten sind virtuelle Adressen (VA), keine Dateioffsets.
BFME2-Adressen im Quellcode sind überwiegend RVA; VA = RVA + ImageBase.
Adressen und Bytefolgen sind vor einem Patch am tatsächlichen Ziel erneut zu prüfen.

## Ergebnis

Vier Operationen müssen getrennt werden:

| Operation | Befund | Aufwand |
|---|---|---|
| Verfügbare Schicksalspunkte abziehen | Vorhandener negativer Delta-Pfad mit Untergrenze null und UI-Meldung | niedrig |
| Spieler-XP für Schicksalspunkte abziehen | Float-Akkumulator akzeptiert negative Werte; Cap kann Aufruf blockieren; keine automatische Rückstufung | niedrig bis mittel |
| Einheiten-XP abziehen, Level behalten | Add-/Set-Pfad vorhanden; eigene Untergrenze erforderlich | niedrig bis mittel |
| Einheiten-Level samt Wirkungen senken | Benannter Level-Anwendungspfad vorhanden; Rücknahme sämtlicher Wirkungen nicht nachgewiesen | mittel bis hoch |

Ein gekaufter Zauber verbraucht SciencePurchasePoints. Er senkt weder den
Spieler-Rang noch dessen SkillPoints. Die Spieler-Rangstufen stammen aus RankInfo;
die Einheiten-Level aus ExperienceLevels. Gekaufte Sciences sind ein weiterer,
separater Zustand.

## OpenBfme und OpenBfme2

OpenBfme `game/GameEngine/Source/Common/RTS/Player_setRankLevel.cpp` enthält
einen ausdrücklich vorhandenen Abstiegspfad: Bei kleinerem Zielrang wird
`resetRank()` aufgerufen, danach wird bis zum Zielrang wieder aufgebaut.
`PlayerRankAndScience.cpp` zeigt dabei die Rücksetzung von XP, Kaufpunkten und
Sciences. Das ist kein reiner Abzug einer Rangstufe und kann gekaufte Zauber verlieren.

OpenBfme2 `PlayerRva002AD826.cpp` zeigt den Kaufpfad: Kosten ermitteln,
virtuellen Slot 2 auf dem Mitglied bei Player+8 mit NEGATIVEN Kosten aufrufen,
danach Science hinzufügen. Der Store liefert Definitionen und Kosten; die
Punkteverwaltung liegt am Player-Mitglied.

Die BFME2-Erfahrungskaskade in `ExperienceTrackerXfer.cpp`, RVA 0x0039AC23,
beginnt beim aktuellen Levelschlüssel und arbeitet vorwärts. Der Setter in
`ExperienceTrackerSetExperience.cpp`, RVA 0x0039B3D1, setzt die XP und ruft
genau diese Kaskade auf. Ein kleinerer XP-Wert führt somit nicht automatisch
zu einem kleineren Level.

`ExperienceTrackerRva0039B4EC.cpp` enthält zwei weitere wichtige Pfade:
Die Levelgewinn-Schleife bei RVA 0x0039B4EC lehnt counts <= 0 ab. Negative
Levelzahlen sind deshalb kein Abstieg. Die Routine bei RVA 0x0039B438 sucht
dagegen einen Level per Name und führt ihn über RVA 0x0039B24F zu. Letztere
ruft den virtuellen Level-Anwendungsslot auf und setzt XP auf RequiredExperience.
Das ist ein brauchbarer Ansatzpunkt für gezielte Rückstufung, jedoch kein
Nachweis für das Entfernen früherer Upgrades oder anderer Levelwirkungen.

Quellenkritik: `OpenBfme/.../ExperienceTracker.cpp` enthält auch
`present-unmatched`-Generals-Code mit vier Veterancy-Stufen und einer vollständigen
Neuberechnung ab Stufe null. Diesen Code NICHT als Beleg für BFME/RotWK-Abstieg
verwenden. Die native BFME2-/RotWK-Kaskade arbeitet anders. Ebenso sind
Kommentar-Namen und private Klassenansichten in diesen RE-Repositories nicht
allein ein Beleg für die tatsächliche Bedeutung eines Feldes.

## Direkt in RotWK überprüfte Ansatzpunkte

| VA | Funktion / strukturelle Bedeutung | Relevanz |
|---|---|---|
| 0x006AA980 | Punkte-Delta-Wrapper auf Player+8; ret 4 | Negative Deltas, Statistik nur bei positiven Werten, UI-Refresh bei Änderung |
| 0x00782764 | Kaufpunkte-Kern; ret 4 | add [this+0x1C], delta; negative Summe wird null |
| 0x006AA9C2 | Rangwechsel-Wrapper auf Player+8; ret 4 | Benachrichtigungen/EVA um den Rangwechsel |
| 0x00782865 | Rangwechsel-Kern; ret 4 | Kleineren Zielrang erkennt er und ruft virtuellen Reset-Slot +0x0C auf |
| 0x006AEE11 | Player-Rangreset auf Player+8 | Ruft 0x00782774 und anschließend 0x006AED4B auf Player auf |
| 0x00782774 | Basis-Rangreset | Setzt Rang auf 1, XP auf 0 und rekonstruiert Start-Kaufpunkte |
| 0x006AED4B | Sciences neu aufbauen auf Player | Verarbeitet Player+0x310, Template- und Rang-Sciences; weiterer Aufruf 0x006AD142 zu untersuchen |
| 0x00782AA4 | Spieler-SkillPoints addieren; ret 8 | Float-Delta, Multiplikatoren, Cap-Guard, nur Aufstieg |
| 0x0079D833 | Einheiten-XP-Wrapper; ret 0x14 | ExperienceSink bei +0x38, Objekt-Tracker bei Object+0x26C, Multiplikatoren |
| 0x0079D68D | Einheiten-XP-Kern; ret 0x18 | Trainable/Maxlevel prüfen, Float addieren, Kaskade aufrufen |
| 0x0079D8EF | Absolute Einheiten-XP setzen; ret 8 | Float-Wert plus Feedback; sink-aware; nutzt dieselbe Aufstiegskaskade |
| 0x0079D141 | Einheiten-Levelkaskade; ret 4 | XP truncieren, nächste Einträge prüfen, virtuellen Slot +0x10 aufrufen |
| 0x0079D956 | Einheiten-Level per Name anwenden; ret 8 | Named-Level-Lookup, ruft 0x0079D76D auf |
| 0x0079D76D | Leveldatensatz anwenden; ret 0x0C | Virtueller Slot +0x10; XP = RequiredExperience; Rang-/Hilfszustand aktualisieren |
| 0x0068931C | ExperienceLevel-Liste des Trackers finden | Einheitenspezifische Levelkette |
| 0x00689E3C | Levelkette anhand aktuellem Levelschlüssel abfragen | Pfad der Vorwärtskaskade |
| 0x00DE4704 | TheExperienceLevelSystem, globaler Pointer | Einstieg in Store/Listensuche |
| 0x00DE3B2C | RankInfoStore, globaler Pointer | Spieler-Rangschwellen |
| 0x005FF99F / 0x005FFA44 | RankInfo-Abfrage / seitenspezifische SkillPoints-Schwelle | Spieler-Rang aus XP ermitteln |

Verifizierte relative Felder:

- Einheiten-Tracker: +0x0C Levelschlüssel, +0x10 XP FLOAT,
  +0x24 aktueller Rang, +0x28 Maximalrang, +0x2C Hilfsobjekt,
  +0x38 ExperienceSink. +0x04 ist hier Template-bezogene Information,
  nicht ohne Prüfung als Object-Pointer zu verwenden.
- Player+8-Mitglied: +0x0C SkillPoints FLOAT, +0x14 Rang INT,
  +0x1C Kaufpunkte INT, +0x20 nächste Aufstiegsschwelle INT.
  Auf den Player selbst bezogen: XP +0x14, Rang +0x1C,
  Kaufpunkte +0x24, nächste Schwelle +0x28.
- ExperienceLevel: +0x18 RequiredExperience, +0xFC Rang.
- RotWK RankInfo: +0x38 gewährte Kaufpunkte. BFME2 benutzt dort +0x34.

Die direkt gelesenen Spieler-XP bei Player+0x14 widersprechen der bislang
provisorischen Ableitung Player+0x20 in `docs/live-object-model.md` und
`sage_live/backends/memory.py`. Keine dieser bestehenden Dateien wurde geändert.
Für einen Patch den nativen Float-Zugriff als Ausgangspunkt nehmen und den
Offset zusätzlich im Spiel validieren.

## Empfohlener Patch

Zunächst explizite Operationen anbieten, beispielsweise (Entwurfsnamen):
`RemoveSciencePurchasePoints`, `RemoveExperiencePoints`, `RemoveExperienceLevels`.
Bestehende negative INI-Werte global freizuschalten würde mehrere voneinander
abweichende Filter, Skalierungen und Cap-Prüfungen berühren.

1. **Kaufpunkte:** vorhandenen Wrapper bei 0x006AA980 auf Player+8 mit -N
   benutzen. Für eine Kostenbedingung vorher auf ausreichendes Guthaben prüfen;
   für einen Drain ist die vorhandene Begrenzung auf null passend.
   Kein zusätzlicher Rangwechsel und keine Science-Neuvergabe.
2. **XP ohne Levelverlust:** XP-neu = max(0, XP-alt - Betrag). Bei Einheiten
   vorhandenen absoluten Setter nutzen, nachdem der tatsächliche Sink-Empfänger
   feststeht. Bei Spieler-XP einen eigenen setter/drain vorsehen, damit Cap und
   Multiplikatoren den Abzug nicht unerwartet unterbinden oder verändern.
   Das bisherige Level bleibt dabei bestehen. Bei späteren Gewinnen müssen
   die verlorenen XP bis zur nächsten Aufstiegsschwelle aufgeholt werden.
3. **Einheiten-Levelverlust:** Ziellevel aus der tatsächlich gültigen Levelkette
   ermitteln, statt pauschal eine XP-Konstante abzuziehen. Für einen exakten
   Levelabzug muss festgelegt werden, ob Fortschritt innerhalb des alten Levels
   verworfen oder relativ übertragen wird. Für XP-basierten Abstieg das höchste
   gültige Level mit RequiredExperience <= XP-neu wählen.
4. **Levelwechsel anwenden:** zuerst den konkreten virtuellen Handler
   `[tracker-vtable+0x10]` verfolgen. 0x0079D76D ist der vorhandene
   Anwendungspfad, überschreibt aber XP mit der Zielschwelle. Bei XP-basiertem
   Abstieg daher danach den gewünschten XP-Wert wiederherstellen.
   Das ist nur brauchbar, wenn der Handler auch niedrigere Levels konsistent
   unterstützt; andernfalls eigene reversible Levelwechselroutine erforderlich.
5. **Spieler-Rangverlust:** den vorhandenen Reset-und-Wiederaufbau-Pfad nicht
   als reinen Rangabzug benutzen. Er setzt XP/Kaufpunkte zurück und führt den
   Science-Rebuild aus. Ein gezielter Patch braucht eine Regel, ob bereits
   ausgegebene Punkte und gekaufte Sciences erhalten bleiben, verloren gehen
   oder als Schuld gegen spätere Gewinne verrechnet werden.

Die einfachste erste Version kombiniert Kaufpunkte-Drain mit XP-Drain bei
beibehaltenem Level. Eine echte Einheiten-Rückstufung wäre die zweite Phase.

## Noch konkret in game.dat zu untersuchen

- **Virtueller Einheiten-Levelhandler +0x10:** neue/alte Levelnamen und
  Rangwerte, AttributeModifier, Upgrades/RemoveUpgrade, ModelConditionState,
  SubObjects, Gesundheit und maximale Gesundheit, Waffen und Level-FX.
  Ein neuer Leveldatensatz allein garantiert keine Rücknahme dauerhaft
  gewährter Upgrades, freigeschalteter Kräfte oder bereits erzeugter Objekte.
- **Named-Level-Setter 0x0079D956 und seine Caller:** Scriptaktionen für
  UNIT/TEAM_SET_EXPERIENCE_POINTS und TEAM_GIVE_EXPERIENCE_LEVEL identifizieren;
  Aktionseinträge anhand der Namen statt übertragener BFME1-Enumwerte suchen.
- **Cap-Guards 0x0079D6A8 und 0x00782AC3:** bei einem Delta-Ansatz für negative
  Werte umgehen, positive Vergabe weiterhin begrenzen. Der absolute
  Einheiten-Setter enthält diesen Maxlevel-Guard nicht.
- **Punkte-Kaufcaller:** vom Spellstore-Kauf zum virtuellen Slot +8 des
  Player+8-Mitglieds folgen; negative Kosten und 0x006AA980 bestätigen.
- **Science-Rebuild 0x006AED4B / 0x006AD142:** genaue Löschwirkung,
  Sonderkräfte/Spellbook-Refresh und Folgen für erworbene Sciences bestimmen.
- **Sink, Horden und Revival:** entscheiden, ob Erfahrung auf Horde, Mitglied
  oder Sponsor liegt; nach Tod/Wiederbelebung auf erhaltene XP und Levels prüfen.

Minimaler Spieltest: Abzug innerhalb einer Stufe; Abzug über eine und mehrere
Schwellen; exakt an der Schwelle; mehr Abzug als Guthaben; Einheit/Spieler am
Cap; Horde mit Mitgliedern; Held mit Level-Upgrades; Tod/Revival; Save/Load;
erneuter Levelgewinn. Einen späteren Multiplayer-Patch auf der synchronisierten
Simulationsseite ausführen; Spellstore-UI allein ist kein geeigneter Ort für
die eigentliche Zustandsänderung.
