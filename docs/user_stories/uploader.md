# User Stories — Uploader Service

> **Service:** Uploader · **Tier:** 2 (Immutable) · **Status:** Planned (since v0.6.0)

---

## US-U01: Aufnahmen automatisch in die Cloud sichern ☁️

> **Als** Forscher
> **möchte ich,** dass meine Aufnahmen automatisch auf einen entfernten Speicher (z.B. Nextcloud, S3) hochgeladen werden,
> **damit** meine Daten auch bei Geräteverlust, Diebstahl oder Hardwaredefekt sicher sind.

### Akzeptanzkriterien

- [ ] Neue Aufnahmen werden automatisch erkannt und in die Cloud hochgeladen — ohne manuellen Eingriff.
- [ ] Vor dem Upload werden Dateien verlustfrei komprimiert (FLAC), um Bandbreite zu sparen (~50 % kleiner).
- [ ] Nach bestätigtem Upload wird die Datei in der Datenbank als „hochgeladen" markiert.
- [ ] Das Gerät funktioniert auch ohne Internetverbindung — Aufnahmen werden lokal gespeichert und bei Verbindung nachgeholt (Store & Forward).

### Milestone

- **Milestone:** v0.6.0

### Referenzen

- [Uploader Service Docs](../services/uploader.md)
- [ADR-0011: Audio Recording Strategy](../adr/0011-audio-recording-strategy.md)
- [ADR-0009: Zero-Trust Data Sharing](../adr/0009-zero-trust-data-sharing.md)

---

## US-U02: Unbegrenzt weiter aufnehmen ♾️

> **Als** Nutzer
> **möchte ich,** dass hochgeladene Aufnahmen automatisch vom lokalen Speicher gelöscht werden dürfen,
> **damit** die Station über Monate oder Jahre ohne manuelles Eingreifen durchgehend aufnehmen kann.

### Akzeptanzkriterien

- [ ] Nach bestätigtem Upload markiert der Uploader die Datei als gesichert.
- [ ] Der Speicher-Bereinigungsdienst (Janitor) darf nur als „hochgeladen" markierte Dateien löschen (→ US-P02).
- [ ] Das Zusammenspiel aus Upload und Bereinigung hält den lokalen Speicher dauerhaft unter den kritischen Schwellenwerten.
- [ ] Bei dauerhaft fehlender Internetverbindung greift der Janitor trotzdem — Aufnahme hat immer Vorrang vor Archivierung.

### Milestone

- **Milestone:** v0.6.0

### Referenzen

- [Uploader Service Docs §Outputs](../services/uploader.md)
- [Processor User Stories — US-P02: Endlos-Aufnahme ohne Speichersorgen](./processor.md)
- [ADR-0011 §Retention Policy](../adr/0011-audio-recording-strategy.md)

---

## US-U03: Mehrere Speicherziele gleichzeitig 🗄️

> **Als** Forscher
> **möchte ich** meine Aufnahmen gleichzeitig an mehrere Speicherziele senden (z.B. Nextcloud für den Austausch, S3 für Langzeitarchiv),
> **damit** ich verschiedene Sicherungs- und Sharing-Strategien parallel nutzen kann.

### Akzeptanzkriterien

- [ ] Mehrere Cloud-Speicher können in der Web-Oberfläche konfiguriert werden (z.B. Nextcloud, Amazon S3, SFTP-Server).
- [ ] Pro Speicherziel läuft eine eigene Upload-Instanz — unabhängig voneinander.
- [ ] Einzelne Speicherziele können aktiviert und deaktiviert werden, ohne die anderen zu beeinflussen.
- [ ] Eine Datei gilt erst als vollständig gesichert, wenn sie an **mindestens ein** aktives Speicherziel hochgeladen wurde.

### Milestone

- **Milestone:** v0.6.0

### Referenzen

- [Uploader Service Docs §Configuration](../services/uploader.md)
- [ADR-0013: Tier 2 Container Management](../adr/0013-tier2-container-management.md)

---

## US-U04: Upload-Einstellungen über die Web-Oberfläche anpassen 🎛️

> **Als** Nutzer
> **möchte ich** die Upload-Einstellungen (Bandbreite, Zeitfenster, Speicherziel) über die Web-Oberfläche ändern können,
> **damit** ich den Upload an meine Netzwerksituation und Bedürfnisse anpasse — ohne SSH oder Konfigurationsdateien.

### Akzeptanzkriterien

- [ ] Bandbreitenlimit ist einstellbar (z.B. „maximal 1 MB/s"), um die Internetverbindung nicht zu überlasten.
- [ ] Ein Zeitfenster für Uploads kann definiert werden (z.B. nur nachts von 22–6 Uhr), um tagsüber Bandbreite zu sparen.
- [ ] Neue Speicherziele können über die Web-Oberfläche hinzugefügt, bearbeitet und entfernt werden.
- [ ] Änderungen werden automatisch übernommen — der Upload-Dienst wird bei Bedarf neu gestartet.

### Milestone

- **Milestone:** v0.6.0 (Backend: UploaderSettings Schema, Schedule, Bandwidth Limit) + v0.8.0 (Frontend: Web-Interface)

### Referenzen

- [Uploader Service Docs §Dynamic Configuration](../services/uploader.md)
- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)
- [ADR-0017: Service State Management](../adr/0017-service-state-management.md)

---

## US-U05: Upload-Fortschritt und -Status im Dashboard 📊

> **Als** Nutzer
> **möchte ich** im Dashboard sehen, wie viele Aufnahmen noch hochgeladen werden müssen und ob es Probleme gibt,
> **damit** ich den Cloud-Sync-Zustand meiner Station jederzeit einschätzen kann.

### Akzeptanzkriterien

- [ ] Das Dashboard zeigt: Anzahl ausstehender Uploads, aktuelle Upload-Geschwindigkeit und letzten erfolgreichen Upload-Zeitpunkt.
- [ ] Bei fehlgeschlagenen Uploads wird eine Warnung angezeigt (z.B. „Verbindung zu Nextcloud fehlgeschlagen seit 2 Stunden").
- [ ] Pro Speicherziel ist der Status einzeln einsehbar.
- [ ] Der Upload-Dienst meldet seinen Status regelmäßig an die Web-Oberfläche.

### Milestone

- **Milestone:** v0.6.0 (Backend: Heartbeat Payload) + v0.8.0 (Frontend: Dashboard)

### Referenzen

- [ADR-0019: Unified Service Infrastructure §Heartbeat](../adr/0019-unified-service-infrastructure.md)
- [Uploader Service Docs](../services/uploader.md)

---

## US-U06: Lückenlose Upload-Nachverfolgung 📋

> **Als** Forscher
> **möchte ich** jederzeit nachvollziehen können, welche Aufnahmen wann und wohin hochgeladen wurden,
> **damit** ich sicher bin, dass keine Daten auf dem Weg verloren gegangen sind.

### Akzeptanzkriterien

- [ ] Jeder Upload-Versuch wird protokolliert — Erfolg, Fehlschlag, Dateigröße, Dauer und Ziel.
- [ ] Das Upload-Protokoll ist über die Web-Oberfläche einsehbar.
- [ ] Fehlgeschlagene Uploads werden automatisch erneut versucht.
- [ ] Dauerhaft fehlgeschlagene Uploads werden als Warnung im Dashboard angezeigt (→ US-U05).

### Milestone

- **Milestone:** v0.6.0

### Referenzen

- [Uploader Service Docs §Audit Logging](../services/uploader.md)

---

> [!NOTE]
> **Aufnahme-Schutz:** Dieser Dienst darf die laufende Aufnahme nicht beeinträchtigen. Ressourcenlimits, QoS-Priorisierung und Datei-Isolation werden zentral über den Controller verwaltet (→ [US-C04](./controller.md), [US-R02](./recorder.md)).
