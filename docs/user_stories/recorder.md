# User Stories — Recorder Service

> **Service:** Recorder · **Tier:** 2 (Immutable) · **Status:** Partial (since v0.2.0)

---

## US-R01: Mikrofon einstecken — Aufnahme läuft 🎙️

> **Als** Feldforscher
> **möchte ich** ein USB-Mikrofon einstecken und die Aufnahme startet automatisch mit den richtigen Einstellungen,
> **damit** ich kein technisches Wissen für die Inbetriebnahme brauche.

### Akzeptanzkriterien

- [x] Mikrofon wird innerhalb weniger Sekunden erkannt — Ziel ist ein Nahe-Echtzeit-Gefühl, kein 10-Sekunden-Polling.
- [x] Passendes Mikrofon-Profil (Sample Rate, Kanäle, Pegel) wird automatisch zugewiesen — bei Bedarf kann der Nutzer im Web-Interface nachsteuern.
- [x] Eine eigene Aufnahme-Instanz wird mit den korrekten Profil-Einstellungen gestartet.
- [x] Keine manuelle Konfiguration nötig — weder Konfigurationsdateien noch Umgebungsvariablen.

### Milestone

- **Milestone:** v0.3.0 (Erkennung & Start) + v0.4.0 (Aufnahme)

### Referenzen

- [Controller README §Device State Evaluation](../../services/controller/README.md)
- [ADR-0013: Tier 2 Container Management](../adr/0013-tier2-container-management.md)
- [ADR-0016: Hybrid YAML/DB Profiles](../adr/0016-hybrid-yaml-db-profiles.md)
- [Microphone Profiles](../arch/microphone_profiles.md)

---

## US-R02: Aufnahme läuft immer weiter 🛡️

> **Als** Forscher
> **möchte ich,** dass die Audioaufnahme unter keinen Umständen unterbrochen wird — weder durch Speicherengpässe, Netzwerkausfall, Neustart anderer Dienste, noch durch laufende Analysen oder Uploads,
> **damit** keine wissenschaftlichen Daten verloren gehen.

### Akzeptanzkriterien

#### Robustheit der Aufnahme
- [x] Der Aufnahme-Dienst wird vom System als letzter beendet — bei Speicherknappheit werden zuerst Analyse-Dienste gestoppt.
- [x] Ein Ausfall der Status-Übertragung (Redis) stoppt nicht die Aufnahme.
- [x] Ein Ausfall des Controllers → Aufnahme läuft ungestört weiter.
- [x] Bei Fehlern in der Aufnahme-Pipeline erfolgt ein automatischer Neustart.

#### Isolation von anderen Diensten
- [ ] ~~Kein anderer Dienst (BirdNET, BatDetect, Uploader) darf die Aufnahme beeinträchtigen~~ (Deferred: ab v0.5.0+)
- [ ] ~~Alle Nicht-Aufnahme-Dienste erhalten CPU- und Speicherlimits~~ (Deferred: ab v0.5.0+)
- [ ] ~~Analyse- und Upload-Dienste greifen nur **lesend** auf Aufnahmedateien zu~~ (Deferred: ab v0.5.0+)
- [ ] ~~Der Absturz eines beliebigen Analyse- oder Upload-Dienstes hat keinen Einfluss~~ (Deferred: ab v0.5.0+)

### Nicht-funktionale Anforderungen

- **Priorität: Datenerfassung > alles andere** — im Zweifelsfall werden Analyse, Upload oder Web-Zugang beendet, nie die Aufnahme.

### Milestone

- **Milestone:** v0.3.0 (Robustheit) + v0.4.0 (Watchdog & Auto-Recovery)

### Referenzen

- [ADR-0020: Resource Limits & QoS](../adr/0020-resource-limits-qos.md)
- [ADR-0019: Unified Service Infrastructure](../adr/0019-unified-service-infrastructure.md)
- [ADR-0009: Zero-Trust Data Sharing](../adr/0009-zero-trust-data-sharing.md)
- [Recorder README](../../services/recorder/README.md)
- [Controller User Stories — US-C04: Aufnahme hat immer Vorrang](./controller.md)

---

## US-R03: Originalformat und Standardformat gleichzeitig 🎧

> **Als** Forscher
> **möchte ich** gleichzeitig eine unveränderte Originalaufnahme (volle Hardware-Qualität) und eine standardisierte Version (48 kHz, 16-Bit) erhalten,
> **damit** ich das volle Spektrum für wissenschaftliche Analyse habe und ML-Dienste (BirdNET, BatDetect) ein einheitliches Format bekommen.

### Akzeptanzkriterien

- [x] Originalaufnahme: Hardware-native Sample Rate und Bittiefe → `recorder/{name}/data/raw/*.wav`.
- [x] Standardaufnahme: 48 kHz, 16-Bit → `recorder/{name}/data/processed/*.wav`.
- [x] Beide Streams werden gleichzeitig und ohne gegenseitige Beeinträchtigung geschrieben.
- [x] Unvollständige Segmente verbleiben in `.buffer/` — nur fertig geschriebene Dateien erscheinen in `data/`.

### Milestone

- **Milestone:** v0.4.0

### Referenzen

- [ADR-0011: Audio Recording Strategy](../adr/0011-audio-recording-strategy.md)
- [Recorder README](../../services/recorder/README.md)

---

## US-R04: Live mithören über den Browser 🔊

> **Als** Nutzer
> **möchte ich** das Mikrofon in Echtzeit über die Web-Oberfläche mithören können,
> **damit** ich vor Ort oder remote prüfen kann, ob die Station korrekt aufnimmt — ohne die wissenschaftliche Aufnahme zu beeinträchtigen.

### Akzeptanzkriterien

- [ ] Ein dritter Audio-Stream wird in niedriger Bitrate (Opus, 64 kbps) an den Streaming-Server gesendet.
- [ ] Ein Ausfall des Streaming-Servers hat keinen Einfluss auf die Dateiaufnahme (Original + Standard).
- [ ] In der Web-Oberfläche kann das gewünschte Mikrofon zum Mithören ausgewählt werden.

### Milestone

- **Milestone:** v1.1.0

### Referenzen

- [Icecast Service](../services/icecast.md)
- [Recorder README](../../services/recorder/README.md)

---

## US-R05: Mehrere Mikrofone gleichzeitig 🎤🎤

> **Als** Forscher
> **möchte ich** mehrere USB-Mikrofone gleichzeitig betreiben können,
> **damit** ich verschiedene Frequenzbereiche oder Standorte parallel erfassen kann.

### Akzeptanzkriterien

- [x] Pro Mikrofon läuft eine eigene, unabhängige Aufnahme-Instanz.
- [x] Jede Instanz hat einen eigenen Arbeitsbereich auf der Festplatte (`recorder/{name}/`).

> [!NOTE]
> Einzel-Aktivierung/-Deaktivierung von Mikrofonen ist ein **Controller-Feature** (via Datenbank / Web-Interface) und wird dort dokumentiert.

### Milestone

- **Milestone:** v0.3.0

### Referenzen

- [ADR-0013: Tier 2 Container Management](../adr/0013-tier2-container-management.md)
- [Controller README §Container Labels](../../services/controller/README.md)

---

## US-R06: Automatische Wiederherstellung bei Fehlern 🔄

> **Als** Nutzer
> **möchte ich,** dass eine abgestürzte oder hängende Aufnahme automatisch neu gestartet wird,
> **damit** die Station auch bei sporadischen Hardwarefehlern ohne mein Eingreifen weiterarbeitet.

### Akzeptanzkriterien

- [x] Die Aufnahme-Pipeline wird bei erkannten Fehlern (Absturz, Hänger, Prozess-Tod) automatisch neu gestartet.
- [x] Mehrere Absicherungs-Stufen: interner Watchdog → Container-Neustart → Controller-Prüfung (Reconciliation-Intervall).
- [x] Fehlstarts werden begrenzt (max. 5 Neuversuche), um Endlosschleifen zu vermeiden.

### Milestone

- **Milestone:** v0.4.0

### Referenzen

- [ADR-0013: Tier 2 Container Management](../adr/0013-tier2-container-management.md)
- [Recorder README](../../services/recorder/README.md)

---

## US-R07: Aufnahmedauer pro Segment einstellen ⏱️

> **Als** Forscher
> **möchte ich** die Länge der Aufnahme-Segmente über das Mikrofon-Profil anpassen können,
> **damit** ich die Dateigröße und Verarbeitungsfrequenz an meinen Anwendungsfall anpassen kann.

### Akzeptanzkriterien

- [x] Die Segment-Dauer wird aus dem Mikrofon-Profil gelesen (Standard: 10 Sekunden).
- [ ] ~~Die Segment-Dauer kann im Web-Interface geändert werden~~ (🔮 Future: v0.8.0+)
- [x] Änderungen werden erst beim nächsten Start der Aufnahme-Instanz wirksam.

### Milestone

- **Milestone:** v0.4.0

### Referenzen

- [ADR-0016: Hybrid YAML/DB Profiles](../adr/0016-hybrid-yaml-db-profiles.md)
- [Microphone Profiles](../arch/microphone_profiles.md)
