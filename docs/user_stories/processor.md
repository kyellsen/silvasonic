# User Stories — Processor Service

> **Service:** Processor · **Tier:** 1 (Infrastructure, Immutable) · **Status:** Planned (since v0.5.0)

---

## US-P01: Aufnahmen erscheinen automatisch in der Übersicht 📋

> **Als** Feldforscher
> **möchte ich,** dass neue Audioaufnahmen automatisch in meiner Übersicht (Web-Oberfläche) erscheinen, sobald sie aufgenommen wurden,
> **damit** ich keinen manuellen Import-Schritt brauche und die Aufnahmen sofort sichtbar und analysierbar sind.

### Akzeptanzkriterien

- [ ] Neue `.wav`-Dateien im Aufnahme-Verzeichnis werden innerhalb weniger Sekunden erkannt (periodisches Scannen, siehe [Processor Service §5](../services/processor.md) für Default-Wert).
- [ ] Metadaten (Dauer, Sample Rate, Kanäle, Dateigröße) werden automatisch ausgelesen und in die Datenbank geschrieben.
- [ ] Bereits registrierte Aufnahmen werden nicht doppelt erfasst (idempotent).
- [ ] Nur vollständig geschriebene Dateien werden erfasst — unvollständige Puffer-Dateien werden ignoriert.

### Nicht-funktionale Anforderungen

- Das Scannen funktioniert **ohne Redis** — Aufnahme und Indexierung sind in keinem Fall von Redis abhängig (Critical Path).
- Der Ausfall des Processors blockiert **nicht** die Analyse bereits erfasster Aufnahmen — Analyse-Worker arbeiten eigenständig weiter.

### Milestone

- **Milestone:** v0.5.0

### Referenzen

- [Processor Service Docs §Indexer](../services/processor.md)
- [ADR-0018: Worker Pull Orchestration](../adr/0018-worker-pull-orchestration.md)
- [Messaging Patterns §Critical Path](../arch/messaging_patterns.md)
- [Recorder README §Buffer to Records](../../services/recorder/README.md)

---

## US-P02: Endlos-Aufnahme ohne Speichersorgen 💾

> **Als** Feldforscher
> **möchte ich,** dass mein Gerät unbegrenzt weiter aufnimmt, ohne dass der Speicher vollläuft,
> **damit** ich die Station wochen- oder monatelang unbeaufsichtigt im Feld lassen kann.

### Akzeptanzkriterien

- [ ] Die Speicherauslastung wird laufend überwacht und bei Bedarf automatisch bereinigt:

| Stufe         | Schwelle | Was wird gelöscht                                             | Hinweis    |
| ------------- | -------- | ------------------------------------------------------------- | ---------- |
| **Aufräumen** | > 70%    | Aufnahmen die hochgeladen UND vollständig analysiert sind     | `INFO`     |
| **Vorsorge**  | > 80%    | Aufnahmen die hochgeladen sind (unabhängig von Analysestatus) | `WARNING`  |
| **Notfall**   | > 90%    | **Älteste** Aufnahmen unabhängig vom Status                   | `CRITICAL` |

- [ ] Gelöschte Dateien verschwinden von der Festplatte, bleiben aber im Inventar (Datenbank) als Eintrag erhalten — die Aufnahme-Historie geht nicht verloren.
- [ ] Im Notfall-Modus funktioniert die Bereinigung auch bei einem Datenbankausfall (Fallback auf Dateialter).
- [ ] Nur der Processor darf Aufnahmedateien löschen — kein anderer Dienst hat Schreibzugriff auf das Aufnahmeverzeichnis.
- [ ] Löschungen werden nachvollziehbar protokolliert (Dateiname, Löschgrund, Stufe).

### Nicht-funktionale Anforderungen

- **Priorität: Weiteraufnahme > Datenarchivierung** — lieber alte Daten löschen als die laufende Aufnahme anhalten.
- Die Bereinigung ist der Kerngrund, warum der Processor als kritischer Infrastruktur-Dienst eingestuft ist.

### Milestone

- **Milestone:** v0.5.0

### Referenzen

- [Processor Service Docs §Janitor](../services/processor.md)
- [ADR-0011: Audio Recording Strategy §6 Retention Policy](../adr/0011-audio-recording-strategy.md)
- [ADR-0009: Zero-Trust Data Sharing](../adr/0009-zero-trust-data-sharing.md)

---

## US-P03: Speicherregeln über die Web-Oberfläche anpassen 🎛️

> **Als** Anwender
> **möchte ich** die Speicher-Bereinigungsregeln (ab welcher Auslastung aufgeräumt wird) über die Web-Oberfläche anpassen können,
> **damit** ich das Verhalten an meinen Standort und meine Speicherkapazität anpassen kann — ohne technische Konfigurationsdateien.

### Akzeptanzkriterien

- [ ] Schwellenwerte (Aufräumen / Vorsorge / Notfall) und Scan-Intervalle sind in den Einstellungen änderbar.
- [ ] Nach einer Änderung wird der Dienst automatisch neu gestartet und übernimmt die neuen Werte.
- [ ] Sinnvolle Standard-Werte sind ab Werk vorbelegt (Schwellenwerte und Intervalle siehe [Processor Service §5](../services/processor.md)).

### Milestone

- **Milestone:** v0.5.0 (Backend: Config Seeding) + v0.8.0 (Frontend: Web-Interface)

### Referenzen

- [ADR-0019: Unified Service Infrastructure](../adr/0019-unified-service-infrastructure.md)
- [ADR-0017: Service State Management](../adr/0017-service-state-management.md)
- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)

---

## US-P04: Daten-Pipeline-Status im Dashboard 📊

> **Als** Anwender
> **möchte ich** im Dashboard auf einen Blick sehen, ob meine Daten-Pipeline läuft — wie viele Aufnahmen noch nicht erfasst sind, in welchem Modus die Speicherbereinigung arbeitet und wie voll mein Speicher ist,
> **damit** ich den Zustand meiner Station jederzeit einschätzen kann.

### Akzeptanzkriterien

- [ ] Die Web-Oberfläche zeigt den aktuellen Daten-Pipeline-Status an (z.B. letzte Erfassung, offener Rückstand, Speicherauslastung, aktuelle Bereinigungsstufe).
- [ ] Der Status aktualisiert sich in Echtzeit, solange die Station erreichbar ist.
- [ ] Bei Ausfall der Status-Übertragung läuft die Daten-Pipeline trotzdem störungsfrei weiter.

### Milestone

- **Milestone:** v0.5.0 (Backend: Heartbeat Payload) + v0.8.0 (Frontend: Dashboard)

### Referenzen

- [ADR-0019: Unified Service Infrastructure §Heartbeat](../adr/0019-unified-service-infrastructure.md)
- [Messaging Patterns §Heartbeat Payload](../arch/messaging_patterns.md)
- [Web-Interface §Processor](../services/web_interface.md)
