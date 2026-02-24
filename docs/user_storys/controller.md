# User Stories — Controller Service

> **Service:** Controller · **Tier:** 1 (Infrastructure) · **Status:** Partial (since v0.1.0)

---

## US-C01: Mikrofon einstecken — sofort erkannt 🎙️⚡

> **Als Anwender** möchte ich ein USB-Mikrofon einstecken und innerhalb von maximal 1 Sekunde eine Reaktion des Systems sehen,
> **damit** ich kein technisches Vorwissen brauche, sofort Daten erfasse, und ein abgezogenes Mikrofon sofort sauber behandelt wird.

### Akzeptanzkriterien

#### Hardware-Erkennung
- [ ] **Alle** USB-Audio-Geräte am Host werden erkannt — nicht nur solche mit bekanntem Profil.
- [ ] Erkennung basiert auf `pyudev` (Linux `udev` / `libudev`) für stabile USB-Identifikation (Vendor-ID, Product-ID, Serial).
- [ ] ALSA-Karten werden über `/proc/asound/cards` korreliert, um den ALSA-Gerätenamen (z.B. `hw:2,0`) zu ermitteln.

#### Einstecken & Entfernen
- [ ] **Reaktionszeit ≤ 1 Sekunde** — ein Kernel-Event-Listener erkennt Änderungen und löst sofort eine Zustandsprüfung aus.
- [ ] Ein neu erkanntes Mikrofon wird automatisch in der Geräteliste als `pending` / `status=online` angelegt.
- [ ] Das Entfernen eines Mikrofons setzt `status=offline` und beendet die zugehörige Aufnahme sauber.
- [ ] Ein Sicherheits-Timer (~30s) dient als **Fallback** — nicht als primärer Erkennungsmechanismus.

#### Stabile Wiedererkennung
- [ ] Ein erneut eingestecktes Mikrofon wird anhand seiner stabilen Geräte-ID wiedererkannt (Vendor-ID + Product-ID + Serial, bzw. Port-Fallback).
- [ ] Es wird kein doppelter Geräteeintrag erzeugt — der bestehende Recorder mit Workspace und Identität wird reaktiviert.

#### Profilzuweisung
- [ ] Beim Erkennen eines neuen Geräts wird automatisch geprüft, ob ein passendes Mikrofon-Profil existiert.
- [ ] Bei eindeutigem Match: automatische Zuordnung.
- [ ] Bei keinem oder mehrdeutigem Match: Gerät bleibt ausstehend — Nutzer wählt Profil im Web-Interface.
- [ ] Das korrekte Profil wird der Aufnahme-Instanz automatisch mitgegeben.

### Nicht-funktionale Anforderungen

- Erkennung muss auf **allen gängigen Linux-Distributionen** funktionieren.
- Der Listener läuft als eigenständige Hintergrundaufgabe und darf den regulären Prüfzyklus nicht blockieren.
- Bei Fehler des Listeners (z.B. udev nicht verfügbar) → automatischer Rückfall auf Polling mit Warnung im Log.

### Referenzen

- [Controller README §Device State Evaluation](file:///mnt/data/dev/apps/silvasonic/services/controller/README.md)
- [ADR-0013: Tier 2 Container Management](file:///mnt/data/dev/apps/silvasonic/docs/adr/0013-tier2-container-management.md)
- [ADR-0016: Hybrid YAML/DB Profiles](file:///mnt/data/dev/apps/silvasonic/docs/adr/0016-hybrid-yaml-db-profiles.md)

---

## US-C02: Abgestürzte Dienste starten automatisch neu 🛡️

> **Als Anwender** möchte ich, dass abgestürzte Aufnahmedienste automatisch neu gestartet werden,
> **damit** die Aufnahme niemals unbemerkt stoppt.

### Akzeptanzkriterien

- [ ] Der regelmäßige Prüfzyklus (~30s) erkennt fehlende oder abgestürzte Dienste und startet sie neu.
- [ ] Container-Neustart-Richtlinie (`on-failure`, max 5) als erste schnelle Absicherung.
- [ ] Bei Controller-Neustart werden bestehende Aufnahme-Instanzen adoptiert (nicht neu gestartet).
- [ ] Bei Controller-Absturz laufen Aufnahme-Instanzen ungestört weiter.
- [ ] **Priorität: Datenerfassung > sauberes Beenden.**

### Referenzen

- [Controller README §Reconciliation Loop](file:///mnt/data/dev/apps/silvasonic/services/controller/README.md)
- [Controller README §Shutdown Semantics](file:///mnt/data/dev/apps/silvasonic/services/controller/README.md)
- [ADR-0013 §Restart Policy](file:///mnt/data/dev/apps/silvasonic/docs/adr/0013-tier2-container-management.md)

---

## US-C03: Dienste über die Web-Oberfläche steuern 🎛️

> **Als Anwender** möchte ich Dienste (z.B. BirdNET, Weather) über die Web-Oberfläche aktivieren oder deaktivieren,
> **damit** ich Ressourcen sparen kann, ohne SSH nutzen zu müssen.

### Akzeptanzkriterien

- [ ] Der Controller reagiert auf Änderungssignale und liest sofort den gewünschten Zustand aus der Datenbank.
- [ ] Gewünschter Zustand aus `system_services` und `devices` wird korrekt ausgewertet.
- [ ] Dienste werden je nach `enabled`-Flag gestartet oder gestoppt.
- [ ] Bei Konfigurationsänderung: Dienst stoppen und mit neuen Einstellungen neu starten.
- [ ] Falls ein Signal verloren geht (z.B. Controller-Neustart), fängt der 30s-Timer die Änderung auf.

### Referenzen

- [Controller README §Reconcile-Nudge Subscriber](file:///mnt/data/dev/apps/silvasonic/services/controller/README.md)
- [ADR-0017: Service State Management](file:///mnt/data/dev/apps/silvasonic/docs/adr/0017-service-state-management.md)
- [Messaging Patterns §State Reconciliation](file:///mnt/data/dev/apps/silvasonic/docs/arch/messaging_patterns.md)

---

## US-C04: Aufnahme hat immer Vorrang ⚡

> **Als Anwender** möchte ich sicher sein, dass die Aufnahme niemals durch Speichermangel oder überlastete Analyse-/Upload-Dienste abbricht,
> **damit** keine Daten verloren gehen — egal welche Dienste gleichzeitig laufen.

### Akzeptanzkriterien

#### Ressourcen-Verwaltung
- [ ] Jeder Dienst-Container erhält Speicher- und CPU-Limits bei der Erstellung.
- [ ] Kein Dienst darf ohne Ressourcen-Limits gestartet werden.
- [ ] Der Controller setzt die Limits zentral bei der Container-Erstellung — einzelne Dienste müssen sich nicht selbst begrenzen.

#### QoS-Priorisierung
- [ ] Aufnahme-Instanzen sind maximal geschützt (niedrigster OOM-Score) — werden vom System als Letzte beendet.
- [ ] Analyse-Dienste (BirdNET, BatDetect) sind als „verzichtbar" markiert und werden bei Engpässen **zuerst** beendet.
- [ ] Upload- und Infrastruktur-Dienste (Uploader, Gateway) erhalten ebenfalls niedrigere Priorität als die Aufnahme.

#### Datei-Isolation (Zero-Trust)
- [ ] Alle Nicht-Aufnahme-Dienste erhalten **nur lesenden** Zugriff auf Aufnahmedateien (Read-Only-Bind-Mounts).
- [ ] Nur der Processor darf Aufnahmedateien löschen — kein anderer Dienst hat Schreibzugriff auf das Aufnahmeverzeichnis.

### Nicht-funktionale Anforderungen

- **Priorität: Datenerfassung > Analyse > Upload > Web-Zugang** — diese Reihenfolge bestimmt, welche Dienste bei Ressourcenknappheit zuerst beendet werden.

### Referenzen

- [Controller README §Resource Limits & QoS](file:///mnt/data/dev/apps/silvasonic/services/controller/README.md)
- [ADR-0020: Resource Limits & QoS](file:///mnt/data/dev/apps/silvasonic/docs/adr/0020-resource-limits-qos.md)
- [ADR-0009: Zero-Trust Data Sharing](file:///mnt/data/dev/apps/silvasonic/docs/adr/0009-zero-trust-data-sharing.md)
- [Recorder User Stories — US-R02: Aufnahme läuft immer weiter](./recorder.md)

---

## US-C05: Systemstatus im Dashboard 📊

> **Als Anwender** möchte ich im Dashboard die Gesamtauslastung meiner Station (CPU, RAM, Speicher) sehen,
> **damit** ich deren Zustand jederzeit einschätzen kann.

### Akzeptanzkriterien

- [ ] Der Controller sammelt systemweite Metriken (CPU, RAM, Speicher).
- [ ] Die Metriken werden regelmäßig an die Web-Oberfläche übertragen.
- [ ] Die Web-Oberfläche zeigt sowohl Einzel-Dienst- als auch Gesamt-System-Metriken an.

### Referenzen

- [Controller README §Redis: Heartbeat + Status Aggregator](file:///mnt/data/dev/apps/silvasonic/services/controller/README.md)
- [ADR-0019 §2.4: Heartbeat Payload Schema](file:///mnt/data/dev/apps/silvasonic/docs/adr/0019-unified-service-infrastructure.md)

---

## US-C06: Mikrofon-Profile verwalten 🔧

> **Als Anwender** möchte ich, dass vordefinierte Mikrofonprofile automatisch verfügbar sind
> und neue Profile über die Web-Oberfläche erstellt werden können,
> **damit** verschiedene Mikrofon-Hardware unterstützt wird.

### Akzeptanzkriterien

- [ ] Beim Start: mitgelieferte Standard-Profile werden automatisch geladen.
- [ ] Beim Seed-Vorgang wird pro Profil geprüft: existiert ein gleichnamiges Nutzer-Profil? → Ja: überspringen. Nein: System-Profil laden.
- [ ] Nutzer-Profile werden dadurch niemals überschrieben.
- [ ] Profil-Daten werden gegen das `MicrophoneProfile` Pydantic-Schema validiert, bevor sie gespeichert werden.

### Referenzen

- [Controller README §Profile Injection](file:///mnt/data/dev/apps/silvasonic/services/controller/README.md)
- [ADR-0016: Hybrid YAML/DB Profile Management](file:///mnt/data/dev/apps/silvasonic/docs/adr/0016-hybrid-yaml-db-profiles.md)
- [Microphone Profiles](file:///mnt/data/dev/apps/silvasonic/docs/arch/microphone_profiles.md)

---

## US-C07: Mikrofon sofort deaktivieren ⛔

> **Als Anwender** möchte ich ein Mikrofon sofort deaktivieren können (z.B. bei Fehlfunktion),
> **damit** das System ohne Neustart unter Kontrolle bleibt.

### Akzeptanzkriterien

- [ ] `enabled=false` auf Geräte-Ebene → sofortige Aufnahme-Abschaltung.
- [ ] Der Stopp erfolgt unabhängig vom Zuweisungs-Status.
- [ ] Änderungssignal sorgt für sofortige Reaktion; der Timer (30s) dient als Fallback.
- [ ] Die Aufnahme wird sauber beendet (kein harter Abbruch).

### Referenzen

- [Controller README §Enrollment State Machine](file:///mnt/data/dev/apps/silvasonic/services/controller/README.md)

---

## US-C08: Funktioniert sofort nach Installation 🏭

> **Als Anwender** möchte ich, dass nach einer Neuinstallation alle sinnvollen Standardwerte geladen werden,
> **damit** das System sofort betriebsbereit ist.

### Akzeptanzkriterien

- [ ] Standard-Konfiguration wird beim Start geladen (nur wenn noch nicht vorhanden).
- [ ] Standard-Mikrofonprofile werden aus YAML-Seed-Dateien geladen und aktualisiert (ADR-0016).
- [ ] Bereits geänderte Werte und nutzererstellte Profile werden niemals überschrieben.
- [ ] Nach einer Datenbank-Zurücksetzung werden alle Standards beim nächsten Start automatisch wiederhergestellt.

> **Hinweis:** Das Anlegen eines Standard-Admin-Accounts gehört zum Web-Interface, nicht zum Controller.

### Referenzen

- [ADR-0023: Configuration Management](file:///mnt/data/dev/apps/silvasonic/docs/adr/0023-configuration-management.md)

---

## US-C09: Dienst-Logs live im Browser 📜

> **Als Anwender** möchte ich die Logs aller Dienste live in der Web-Oberfläche sehen,
> **damit** ich Probleme schnell diagnostizieren kann.

### Akzeptanzkriterien

- [ ] Der Controller liest die Logs aller verwalteten Dienste.
- [ ] Logs werden in Echtzeit an die Web-Oberfläche weitergeleitet.
- [ ] Bei keinem aktiven Zuschauer werden Logs einfach verworfen (kein Ressourcenverbrauch).
- [ ] Die Web-Oberfläche zeigt Logs mit Auto-Scroll an.

### Referenzen

- [ADR-0022: Live Log Streaming](file:///mnt/data/dev/apps/silvasonic/docs/adr/0022-live-log-streaming.md)
- [ADR-0013 §Logging](file:///mnt/data/dev/apps/silvasonic/docs/adr/0013-tier2-container-management.md)
