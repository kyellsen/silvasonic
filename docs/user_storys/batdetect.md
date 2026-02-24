# User Stories — BatDetect Service

> **Service:** BatDetect · **Tier:** 2 (Immutable) · **Status:** Planned (since v1.3.0)

---

## US-BD01: Fledermausarten automatisch erkennen 🦇

> **Als** Forscher
> **möchte ich,** dass meine Ultraschall-Aufnahmen automatisch auf Fledermausrufe analysiert werden und die erkannten Arten mit Zeitstempel und Zuverlässigkeit in der Datenbank erscheinen,
> **damit** ich ein vollständiges Fledermaus-Artinventar meines Standorts erhalte — ohne jede Aufnahme manuell im Spektrogramm durchsuchen zu müssen.

### Akzeptanzkriterien

- [ ] Alle indexierten Aufnahmen mit ausreichend hoher Sample Rate werden automatisch analysiert — ohne manuellen Anstoß.
- [ ] Pro erkanntem Fledermausruf wird die Art, der Zeitpunkt im Audio und ein Konfidenzwert gespeichert.
- [ ] Die Analyse nutzt die Originalaufnahme (volle Hardware-Qualität), nicht die heruntergerechnete Standardversion.
- [ ] Bereits analysierte Aufnahmen werden nicht erneut verarbeitet.
- [ ] Das Modell ist auf **mitteleuropäische Fledermausarten** (DACH-Region) trainiert oder feinjustiert.

### Milestone

- **Milestone:** v1.3.0

### Referenzen

- [BatDetect Service Docs](../services/batdetect.md)
- [ADR-0018: Worker Pull Orchestration](../adr/0018-worker-pull-orchestration.md)
- [Recorder User Stories — US-R03: Originalformat und Standardformat gleichzeitig](./recorder.md)

---

## US-BD02: Nur Ultraschall-Mikrofone analysieren 🎤

> **Als** Nutzer
> **möchte ich,** dass nur Aufnahmen von Mikrofonen analysiert werden, die tatsächlich Ultraschall aufnehmen können,
> **damit** keine Rechenleistung für Standard-Mikrofone (48 kHz) verschwendet wird, die ohnehin keine Fledermausrufe enthalten.

### Akzeptanzkriterien

- [ ] BatDetect verarbeitet nur Aufnahmen mit einer Sample Rate ≥ 192 kHz (konfigurierbar).
- [ ] Aufnahmen von Standard-Mikrofonen (z.B. 48 kHz) werden automatisch übersprungen.
- [ ] Der Filter basiert auf der Sample Rate der aufgenommenen Datei — keine manuelle Zuordnung nötig.
- [ ] Im Dashboard ist sichtbar, welche Mikrofone für die Fledermaus-Analyse qualifiziert sind.

### Milestone

- **Milestone:** v1.3.0

### Referenzen

- [BatDetect Service Docs §Inputs](../services/batdetect.md)
- [Microphone Profiles](../arch/microphone_profiles.md)

---

## US-BD03: Analyse nur zu Fledermaus-aktiven Zeiten ⏰

> **Als** Forscher
> **möchte ich,** dass die Fledermaus-Analyse nur für Aufnahmen aus den Abend- und Nachtstunden läuft (z.B. 19:00–07:00),
> **damit** keine Rechenleistung für Tagaufnahmen verschwendet wird, in denen Fledermäuse nicht aktiv sind.

### Akzeptanzkriterien

- [ ] Ein Zeitfenster (Start- und Endstunde) ist über die Web-Oberfläche konfigurierbar (Standard: 19:00–07:00).
- [ ] Aufnahmen außerhalb des Zeitfensters werden bei der Analyse übersprungen.
- [ ] Das Zeitfenster kann deaktiviert werden, sodass alle Aufnahmen analysiert werden (z.B. für spezielle Studien).
- [ ] Änderungen am Zeitfenster werden automatisch übernommen (Dienst-Neustart).

### Milestone

- **Milestone:** v1.3.0

### Referenzen

- [BatDetect Service Docs §Dynamic Configuration](../services/batdetect.md)
- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)

---

## US-BD04: Erkennungsgenauigkeit einstellen 🎚️

> **Als** Forscher
> **möchte ich** den Konfidenz-Schwellenwert für die Fledermaus-Erkennung anpassen können,
> **damit** ich je nach Bedarf entweder mehr Einzelnachweise (niedriger Schwellenwert) oder weniger Fehlalarme (hoher Schwellenwert) erhalte.

### Akzeptanzkriterien

- [ ] Der Konfidenz-Schwellenwert ist über die Web-Oberfläche einstellbar (Standard: 25 %).
- [ ] Nachweise unterhalb des Schwellenwerts werden nicht in der Artenliste angezeigt.
- [ ] Änderungen werden automatisch übernommen — der Dienst startet bei Bedarf neu.
- [ ] Im Dashboard ist der aktuelle Schwellenwert sichtbar.

### Milestone

- **Milestone:** v1.3.0

### Referenzen

- [BatDetect Service Docs §Dynamic Configuration](../services/batdetect.md)
- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)

---

## US-BD05: Erkannte Fledermausarten in der Web-Oberfläche ansehen 📋

> **Als** Nutzer
> **möchte ich** in der Web-Oberfläche eine Liste aller erkannten Fledermausarten sehen — mit Häufigkeit, letztem Nachweis und Aktivitätsverlauf,
> **damit** ich schnell verstehe, welche Fledermausarten an meinem Standort vorkommen und wann sie aktiv sind.

### Akzeptanzkriterien

- [ ] Die Web-Oberfläche zeigt eine Artenliste mit Anzahl der Nachweise, letztem Erkennungszeitpunkt und durchschnittlicher Konfidenz.
- [ ] Jede Art hat eine Detailseite mit Beschreibung, Bild und zeitlichem Aktivitätsverlauf.
- [ ] Die Liste lässt sich nach Häufigkeit, Datum oder Konfidenz sortieren.
- [ ] Fledermaus-Nachweise sind klar von Vogel-Nachweisen getrennt (eigener Bereich in der Web-Oberfläche).

### Milestone

- **Milestone:** v1.3.0

### Referenzen

- [BatDetect Service Docs §Outputs](../services/batdetect.md)

---

> [!NOTE]
> **Aufnahme-Schutz:** Dieser Dienst darf die laufende Aufnahme nicht beeinträchtigen. Ressourcenlimits, QoS-Priorisierung und Datei-Isolation werden zentral über den Controller verwaltet (→ [US-C04](./controller.md), [US-R02](./recorder.md)).

---

## US-BD06: Analyse-Status im Dashboard 📊

> **Als** Nutzer
> **möchte ich** im Dashboard sehen, wie viele Aufnahmen noch auf Fledermaus-Analyse warten und ob BatDetect gerade aktiv ist,
> **damit** ich den Zustand der Analyse-Pipeline jederzeit einschätzen kann.

### Akzeptanzkriterien

- [ ] Das Dashboard zeigt: Anzahl ausstehender Aufnahmen, zuletzt analysierte Datei und aktuelle Aktivität (aktiv/wartend/offline).
- [ ] Bei Problemen (z.B. BatDetect gestoppt oder im Rückstand) wird eine Warnung angezeigt.
- [ ] BatDetect meldet seinen Status regelmäßig an die Web-Oberfläche.
- [ ] Ressourcenverbrauch (RAM, CPU) ist im Dashboard sichtbar — als Hilfe für die Entscheidung, ob BatDetect aktviert bleiben soll.

### Milestone

- **Milestone:** v1.3.0

### Referenzen

- [ADR-0019: Unified Service Infrastructure §Heartbeat](../adr/0019-unified-service-infrastructure.md)
- [BatDetect Service Docs](../services/batdetect.md)

---

## US-BD07: BatDetect ein- und ausschalten 🔌

> **Als** Nutzer
> **möchte ich** die Fledermaus-Erkennung über die Web-Oberfläche aktivieren oder deaktivieren können,
> **damit** ich Rechenleistung und Energie spare, wenn ich die Analyse nicht benötige oder kein Ultraschall-Mikrofon angeschlossen ist.

### Akzeptanzkriterien

- [ ] BatDetect ist **standardmäßig deaktiviert** — der Nutzer muss die Analyse bewusst einschalten.
- [ ] Bei Aktivierung prüft das System, ob ein Ultraschall-fähiges Mikrofon angeschlossen ist, und warnt falls nicht.
- [ ] Bei Deaktivierung wird der Dienst sauber beendet — keine laufende Analyse wird abgebrochen.
- [ ] Bei Reaktivierung arbeitet BatDetect den aufgelaufenen Rückstand selbstständig ab.
- [ ] Der aktuelle Zustand (aktiv/deaktiviert) ist im Dashboard sichtbar.

### Milestone

- **Milestone:** v1.3.0

### Referenzen

- [Controller User Stories — US-C03: Dienste über die Web-Oberfläche steuern](./controller.md)
- [ADR-0017: Service State Management](../adr/0017-service-state-management.md)
