# Web Interface — Feature Catalog

> **Status:** TO-BE — Feature-Liste aller geplanten Nutzer-Aktionen und Views.
>
> **Referenzen:** [Web-Interface Service Spec](web_interface.md), [Web-Mock README](../../services/web-mock/README.md), [User Stories](../user_stories/web_interface.md)

---

## Shell (Global UI — alle Seiten)

### Header
| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Sidebar Toggle | Sidebar ein-/ausklappen | ✅ v0.2.0 |
| Logo → Dashboard | Klick auf Logo navigiert zum Dashboard | ✅ v0.2.0 |
| Notification Dropdown 🔔 | Klapp-Menü mit aktiven Alerts (Level: error/warn/info, Zeitstempel) | v0.8.0 |
| REC-Indikator | Pulsierende Anzeige: `REC N` — Anzahl aktiver Recorder | ✅ v0.2.0 |
| Upload-Indikator | Cloud-Icon mit Anzahl aktiver Uploader | ✅ v0.2.0 |
| Dark/Light Mode Toggle 🌗 | Umschaltung zwischen `silvadark` / `silvalight` Theme (localStorage) | ✅ v0.2.0 |
| Inspector Toggle | Rechtes Panel ein-/ausklappen | ✅ v0.2.0 |
| User-Menü (Avatar) | Dropdown: „Signed in as…", User Settings, **Sign Out** | v0.8.0 |

### Sidebar Navigation
| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| System-Gruppe | Dashboard, Recorders, Processor, Uploaders — immer sichtbar | ✅ v0.2.0 |
| Module-Gruppe | Livesound, Birds, Bats, Weather — **nur wenn aktiviert** (DB-gesteuert) | v0.8.0 |
| Settings / About | Angepinnt am unteren Rand der Sidebar | ✅ v0.2.0 |

### Footer Status Strip
| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Console Toggle | Aufklapp-Panel für Live-Log-Stream | ✅ v0.2.0 |
| System-Metriken | Storage %, CPU %, RAM %, Temperatur °C, Uptime in h — farbcodiert | v0.8.0 |
| Device Name + Version | Station-ID und Software-Version | ✅ v0.2.0 |

### Console Panel (Log-Stream)
| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Service-Filter Dropdown | Log-Stream nach Service filtern (Controller, Recorder, …) | ✅ v0.2.0 |
| SSE Live-Stream | Echtzeit-Log-Ausgabe via Server-Sent Events | v0.8.0 |
| Auto-Scroll | Automatisches Scrollen zum neuesten Eintrag | v0.8.0 |

### Inspector Panel (rechts) — Context-Aware

Der Inspector zeigt **immer kontextabhängige Details** zum aktuell gewählten Objekt der aktuellen Seite. Bei Seitenwechsel aktualisiert sich der Inhalt automatisch zum Default-Kontext dieser Seite.

| Page | Default (kein Objekt gewählt) | Bei Auswahl eines Objekts | Milestone |
|------|------------------------------|---------------------------|-----------|
| **Dashboard** | Service-Status-Liste: alle Services mit Status (running/down), aktuelle Task-Info | — (keine auswählbaren Objekte) | v0.8.0 |
| **Recorders** | Kurzübersicht: aktive/inaktive Recorder, Gesamtaufnahmezeit | **Recorder-Card →** Profil-Details, ALSA-Device, Workspace, Segment-Dauer, Gain, Enrollment-Status, Watchdog-Restarts | v0.8.0 |
| **Recorders** | *(Auswahl)* | **Audio-Preview →** Wavesurfer.js Waveform + Spektrogramm der letzten Aufnahme | v0.8.0+ |
| **Processor** | Indexer-Zusammenfassung: Dateien heute, Gesamtbestand, letzte Bereinigung | **Datei-Zeile →** Datei-Details: Pfad, Dauer, Sample Rate, Kanäle, Größe, Upload-/Analyse-Status | v0.8.0 |
| **Uploaders** | Queue-Summe, Durchsatz, letzter Upload | **Uploader-Card →** Target-Details: URL, Auth, Queue, letzte Fehler, Retries | v0.8.0 |
| **Birds** | Artenzusammenfassung: Gesamtarten, Nachweise heute | **Species-Card →** Art-Steckbrief: Bild, Name (de + sci), Taxonomie, Häufigkeit, Konfidenz | v1.1.0 |
| **Birds** | *(Analyzer-Tab)* | **Erkennungs-Zeile →** Wavesurfer.js Spektrogramm + Annotation-Region, Konfidenzwert, Aufnahme-Link | v1.1.0 |
| **Bats** | Artenzusammenfassung (analog Birds) | **Species-Card →** Art-Steckbrief + Ultraschall-Spektrogramm | v1.3.0 |
| **Bats** | *(Analyzer-Tab)* | **Erkennungs-Zeile →** Spektrogramm-Overlay (analog Birds) | v1.3.0 |
| **Weather** | Aktuelle Messwerte compact | **Chart-Punkt →** Detail-Werte zum Zeitpunkt + korrelierte Artnachweise | v1.2.0 |
| **Livesound** | Stream-Status: Zuhörer, Bitrate, Latenz | **Recorder-Auswahl →** Live-Waveform, Pegelwert, Stream-URL (kopierbar) | v0.9.0 |
| **Settings / About** | — (Inspector leer oder verborgen) | — | — |

---

## 📊 Dashboard (`/`)

| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Orchestration Card | Recorder-/Uploader-/Pending-Zähler, Health-Badge | v0.8.0 |
| Data Pipeline Card | Index-Alter, Backlog-Zähler, Janitor-Status | v0.8.0 |
| SSD Storage Card | Radial Progress: genutzt/gesamt GB, Prozentwert | v0.8.0 |
| CPU Card | Avg Load %, Core-Balkendiagramm (hover: Einzelwert), Temperatur | v0.8.0 |
| RAM Card | Radial Progress: genutzt/gesamt MB | v0.8.0 |
| Uptime Card | Stunden seit Neustart, System-Healthy-Badge | v0.8.0 |
| Active Alerts | Liste aller offenen Warnungen (error/warn/info + Zeitstempel) | v0.8.0 |
| Upload Throughput Chart | ECharts Time-Series: Upload-Rate über Zeit | v0.8.0+ |

---

## 🎙️ Recorders (`/recorders`)

| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Bento-Grid (max 5) | Recorder-Cards: Live-Level-Balken, Sample Rate, Kanäle, Segment, Gain, Status-Badge | v0.8.0 |
| Enrollment-Status Badge | Farbcodierter Badge pro Recorder: `enrolled` (grün) / `generic` (gelb) / `pending` (orange) | v0.8.0 |
| Recorder Detail (`/recorders/{id}`) | Detailansicht: Profil-Name, ALSA-Device, Workspace-Pfad, alle Parameter | v0.8.0 |
| Watchdog Health Card | Progress-Bar: Pipeline-Restarts (z.B. 2/5), farbcodiert (grün/gelb/rot) | v0.8.0 |
| Start/Stop Recorder ⛔ | Mikrofon aktivieren/deaktivieren → schreibt `enabled`-Flag in DB → Nudge | v0.8.0 |
| Profil wechseln 🟨 | Anderes Mikrofon-Profil zuweisen → Recorder wird neu gestartet | v0.8.0+ |
| Inspector: Audio Preview | Wavesurfer.js: Live-Waveform / Spektrogramm des ausgewählten Recorders | v0.8.0+ |

---

## ⚙️ Processor (`/processor`)

| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Indexer File Table | Tabelle der zuletzt indexierten Dateien (Name, Dauer, Sample Rate, Größe, Status) | v0.8.0 |
| Retention Event Log | Chronologische Liste der Lösch-Aktionen (Dateiname, Grund, Stufe, Zeitstempel) | v0.8.0 |
| Storage Gauge | Aktuelle Speicherauslastung + Bereinigungsstufe (Normal/Vorsorge/Notfall) | v0.8.0 |

> Configuration der Retention-Policy → **Settings → Storage & Retention**

---

## ☁️ Uploaders (`/uploaders`)

| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Bento-Grid (max 3) | Uploader-Cards: Queue-Größe, Durchsatz, letzter Sync, Status, Target-Typ | v0.8.0 |
| Uploader Detail (`/uploaders/{id}`) | Detailansicht: Target-URL, Auth-Status, Queue-Details, Bandwidth, Upload Window | v0.8.0 |
| Upload History (Audit-Log) | Tabelle der Upload-Versuche: Datei, Status (✓/✗/⏳), Größe, Dauer, Fehlertext | v0.8.0 |
| Uploader aktivieren/deaktivieren | Toggle per Uploader-Instanz | v0.8.0 |

> Configuration der Remote-Targets → **Settings → Remotes**

---

## 🐦 Birds (`/birds`)

| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Tab: Discovery | Pokédex-Style Species-Cards: Art-Bild, Name (Deutsch + Wissenschaftlich), Nachweis-Zähler, Konfidenz | v1.1.0 |
| Tab: Analyzer | Datentabelle mit Filtern (Datum, Art, Konfidenz). Zeilen-Klick → Inspector mit Wavesurfer Annotation | v1.1.0 |
| Tab: Statistics | ECharts: Aktivitäts-Heatmap, Top-10, Artendiversität über Zeit | v1.1.0 |
| Bird Detail (`/birds/{id}`) | Art-Detailseite: Wikipedia-Info, Bild, Beschreibung, Timeline aller Nachweise | v1.1.0 |
| Konfidenz-Schwellenwert | Filter: nur Nachweise über eingestelltem Schwellenwert anzeigen | v1.1.0 |

---

## 🦇 Bats (`/bats`)

| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Tab: Discovery | Pokédex-Style Species-Cards (identische Struktur wie Birds, eigenes Farbschema) | v1.3.0 |
| Tab: Analyzer | Datentabelle mit Filtern, Inspector-Integration mit Spektrogramm-Overlay | v1.3.0 |
| Tab: Statistics | ECharts: Nacht-Aktivitätskurve, Top-10, Artendiversität | v1.3.0 |
| Bat Detail (`/bats/{id}`) | Art-Detailseite mit Wikipedia-Info, Bild, Nachweiszeitlinie | v1.3.0 |

---

## ☀️ Weather (`/weather`)

| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Tab: Overview | Compact-Ansicht aller aktuellen Messwerte (Temp, Niederschlag, Feuchte, Druck, Wind) | v1.2.0 |
| Tab: Current | Detailierte Einzelwerte mit Trend-Indikatoren | v1.2.0 |
| Tab: Statistics | ECharts Time-Series pro Messgröße (24h/7d/30d Selector) | v1.2.0 |
| Tab: Correlation | Dual-Y-Axis Chart: Artnachweise überlagert mit Wetterdaten | v1.2.0 |

---

## 🔊 Livesound (`/livesound`)

| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Recorder-Auswahl | Dropdown/Cards: aktive Mikrofone zum Live-Abhören auswählen | v0.9.0 |
| Audio-Player | Browser-basierter Opus-Stream-Player (Play/Stop/Volume) | v0.9.0 |
| Waveform Visualization | Wavesurfer.js Live-Waveform des aktiven Streams | v0.9.0 |
| Stream-URL teilen | Stabile URL pro Mikrofon-Stream für VLC/externe Player | v0.9.0 |

---

## ⚙️ Settings (`/settings`)

### Tab: General
| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Station Name | Editierbarer Gerätename (Netzwerk-Identität, Upload-Label) | ✅ v0.2.0 |
| Language | Sprachauswahl: de / en | v0.8.0 |
| Timezone | Zeitzone der Station | v0.8.0 |
| Latitude / Longitude | GPS-Koordinaten (für BirdNET Regions-Filter) | v0.8.0 |
| Poweroff on Low Battery | Toggle: automatisches Herunterfahren bei niedrigem Akku | v0.8.0+ |
| **Save Changes** Button | Speichert General Settings in DB | ✅ v0.2.0 |

### Tab: Modules
| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Module-Toggles | Livesound, BirdNET, BatDetect, Weather einzeln aktivieren/deaktivieren | v0.8.0 |
| BirdNET Min. Confidence | Range-Slider (0.1–1.0): Erkennungsschwelle für Vogelarten (Default: leer = Standard) | v0.8.0 |
| BirdNET Analysis Window | Start-/Endzeit-Picker: Analyse-Zeitfenster begrenzen (Default: leer = 24/7) | v0.8.0 |
| BatDetect Min. Confidence | Range-Slider (0.1–1.0): Erkennungsschwelle für Fledermausarten (Default: leer = Standard) | v0.8.0 |
| BatDetect Analysis Window | Start-/Endzeit-Picker: Analyse auf aktive Stunden begrenzen (Default: leer = 24/7) | v0.8.0 |
| **Apply & Reload System** Button 🟨 | Wendet Modul-Änderungen an — System-Reload erforderlich | v0.8.0 |

### Tab: Storage & Retention
| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Max File Age (Days) | Maximales Alter von Aufnahmedateien bevor Löschung | v0.8.0 |
| Min Free Space Buffer (GB) | Notfall-Bereinigung unter diesem Schwellenwert | v0.8.0 |
| Delete after Upload | Toggle: lokale Kopie nach Upload sofort löschen | v0.8.0 |
| **Save Policy** Button | Speichert Retention-Konfiguration | v0.8.0 |

### Tab: Remotes
| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Remote-Target Auswahl | Dropdown: zwischen konfigurierten Zielen wechseln | v0.8.0 |
| Server URL | Ziel-URL editieren | v0.8.0 |
| Username / Password | Zugangsdaten editieren | v0.8.0 |
| Target Path / Bucket | Ziel-Pfad editieren | v0.8.0 |
| Bandwidth Limit (KB/s) | Upload-Bandbreite begrenzen (leer = Unlimited) | v0.8.0 |
| Upload Window | Start-/Endzeit für Uploads (leer = 24/7) | v0.8.0 |
| **Test Connection** Button ✅ | Verbindung zum Remote-Target testen (Safe Action) | v0.8.0 |
| **Save Target** Button | Remote-Konfiguration speichern | v0.8.0 |

### Tab: Network
| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| WLAN Hotspot Toggle | Ein-/Ausschalten, Status-Anzeige (SSID, Password, Channel, IP) | v0.8.0+ |
| WLAN Edit Configuration | Hotspot-Einstellungen bearbeiten | v0.8.0+ |
| Tailscale VPN Toggle | Ein-/Ausschalten, Status (Tailnet IP, Hostname, HTTPS Proxy, Auth Status) | v1.5.0 |
| Tailscale View Logs | Log-Ausgabe von Tailscale anzeigen | v1.5.0 |
| Tailscale Edit Settings | VPN-Konfiguration bearbeiten | v1.5.0 |

### Tab: User
| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Username (readonly) | Admin-Username anzeigen (nicht änderbar) | v0.8.0 |
| Change Password | Aktuelles + neues + Bestätigung-Passwort | v0.8.0 |
| **Update Security Credentials** Button | Passwort ändern (bcrypt-Hash) | v0.8.0 |

---

## ℹ️ About (`/about`)

| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Version Info | Software-Version, Build-Info | ✅ v0.2.0 |
| Project Links | GitHub, Docs, Lizenz | ✅ v0.2.0 |
| Hardware Info | Raspberry Pi Modell, NVMe, Audio-Interface | v0.8.0 |

---

## 🔐 Auth (Cross-Cutting)

| Feature | Beschreibung | Milestone |
|---------|-------------|-----------|
| Login Page | Benutzername + Passwort Formular | v0.8.0 |
| Session Management | Serverseitige Sessions, 24h Timeout | v0.8.0 |
| Brute-Force-Schutz | Max 5 Fehlversuche → 30s Sperre | v0.8.0 |
| Sign Out | Session beenden, Redirect → Login | v0.8.0 |

---

## 📋 User Story → Frontend Cross-Reference

Jede User Story und ob ihre Akzeptanzkriterien im Frontend sichtbar werden.

### Controller (US-C01–C10)

| Story | Titel | Frontend-Feature | Abgedeckt? |
|-------|-------|-----------------|------------|
| US-C01 | Mikrofon einstecken — sofort erkannt | Recorders Bento-Grid (neues Gerät erscheint live) | ✅ |
| US-C02 | Abgestürzte Dienste starten automatisch neu | Dashboard Orchestration Card (Status-Update), Console Logs | ✅ |
| US-C03 | Dienste über Web-Oberfläche steuern | Recorders Start/Stop, Settings → Modules Toggle | ✅ |
| US-C04 | Aufnahme hat immer Vorrang | ⚙️ Backend-Only (OOM-Score, cgroups) — **kein eigenes UI-Element nötig** | 🔒 Backend |
| US-C05 | Systemstatus im Dashboard | Dashboard Cards (CPU/RAM/Storage/Uptime), Footer Status Strip | ✅ |
| US-C06 | Mikrofon-Profile verwalten | Recorders Detail → Profil-Anzeige, Profil wechseln | ✅ |
| US-C07 | Mikrofon sofort deaktivieren | Recorders → Start/Stop Toggle (enabled=false) | ✅ |
| US-C08 | Funktioniert sofort nach Installation | ⚙️ Backend-Only (Seeder) — Settings zeigt Ergebnis | ✅ indirekt |
| US-C09 | Dienst-Logs live im Browser | Console Panel (SSE Live-Stream + Service-Filter) | ✅ |
| US-C10 | Unbekanntes Mikrofon funktioniert sofort | Recorders Grid: Enrollment-Badge (enrolled/generic/pending) | ✅ |

### Recorder (US-R01–R07)

| Story | Titel | Frontend-Feature | Abgedeckt? |
|-------|-------|-----------------|------------|
| US-R01 | Mikrofon einstecken — Aufnahme läuft | Recorders Grid: Status-Badge wechselt zu „recording" | ✅ |
| US-R02 | Aufnahme läuft immer weiter | ⚙️ Backend-Only (Resilience) — Dashboard Alert bei Ausfall | ✅ indirekt |
| US-R03 | Originalformat und Standardformat gleichzeitig | Recorder Detail: zeigt Raw + Processed Stream-Info | ✅ |
| US-R04 | Live mithören über den Browser | Livesound Page (Audio-Player, Recorder-Auswahl) | ✅ |
| US-R05 | Mehrere Mikrofone gleichzeitig | Recorders Bento-Grid (mehrere Cards) | ✅ |
| US-R06 | Automatische Wiederherstellung bei Fehlern | Recorder Detail: Watchdog Health Card (Restarts Progress-Bar) | ✅ |
| US-R07 | Aufnahmedauer pro Segment einstellen | Recorder Detail: zeigt Segment-Dauer, Profil-Wechsel ändert Wert | ✅ |

### Processor (US-P01–P04)

| Story | Titel | Frontend-Feature | Abgedeckt? |
|-------|-------|-----------------|------------|
| US-P01 | Aufnahmen erscheinen automatisch | Processor → Indexer File Table | ✅ |
| US-P02 | Endlos-Aufnahme ohne Speichersorgen | Processor → Retention Event Log + Storage Gauge | ✅ |
| US-P03 | Speicherregeln anpassen | Settings → Storage & Retention | ✅ |
| US-P04 | Daten-Pipeline-Status im Dashboard | Dashboard → Data Pipeline Card | ✅ |

### Uploader (US-U01–U06)

| Story | Titel | Frontend-Feature | Abgedeckt? |
|-------|-------|-----------------|------------|
| US-U01 | Aufnahmen automatisch in die Cloud | Uploaders Page (Queue, Throughput, Status) | ✅ |
| US-U02 | Unbegrenzt weiter aufnehmen | Processor Retention + Uploader Status (Zusammenspiel) | ✅ |
| US-U03 | Mehrere Speicherziele gleichzeitig | Settings → Remotes (Dropdown mehrerer Targets) | ✅ |
| US-U04 | Upload-Einstellungen anpassen | Settings → Remotes (URL, Auth, Pfad, Bandwidth, Window) | ✅ |
| US-U05 | Upload-Fortschritt im Dashboard | Uploaders Page (Queue, Throughput, Last Sync) + Dashboard | ✅ |
| US-U06 | Lückenlose Upload-Nachverfolgung | Uploader Detail: Upload History Tabelle (Audit-Log) | ✅ |

### BirdNET (US-B01–B06)

| Story | Titel | Frontend-Feature | Abgedeckt? |
|-------|-------|-----------------|------------|
| US-B01 | Vogelarten automatisch erkennen | Birds → Discovery + Analyzer | ✅ |
| US-B02 | Erkannte Arten ansehen | Birds → Discovery (Artenliste + Sortierung) | ✅ |
| US-B03 | Erkennung an Standort anpassen | Settings → General (Lat/Lng) | ✅ |
| US-B04 | Erkennungsgenauigkeit einstellen | Settings → Modules: BirdNET Min. Confidence Slider + Analysis Window | ✅ |
| US-B05 | Analyse-Status im Dashboard | Dashboard + Inspector (BirdNET running/backlog) | ✅ |
| US-B06 | BirdNET ein- und ausschalten | Settings → Modules (BirdNET Toggle) | ✅ |

### BatDetect (US-BD01–BD07)

| Story | Titel | Frontend-Feature | Abgedeckt? |
|-------|-------|-----------------|------------|
| US-BD01 | Fledermausarten erkennen | Bats → Discovery + Analyzer | ✅ |
| US-BD02 | Nur Ultraschall-Mikrofone | ⚙️ Backend-Only (Filter) — Dashboard zeigt qualifizierte Mikros | ✅ indirekt |
| US-BD03 | Analyse nur zu Fledermaus-aktiven Zeiten | Settings → Modules: BatDetect Analysis Window (Start/End Time) | ✅ |
| US-BD04 | Erkennungsgenauigkeit einstellen | Settings → Modules: BatDetect Min. Confidence Slider | ✅ |
| US-BD05 | Erkannte Arten ansehen | Bats → Discovery (Artenliste + Sortierung) | ✅ |
| US-BD06 | Analyse-Status im Dashboard | Dashboard + Inspector (BatDetect status) | ✅ |
| US-BD07 | BatDetect ein- und ausschalten | Settings → Modules (BatDetect Toggle) | ✅ |

### Gateway (US-GW01–GW03)

| Story | Titel | Frontend-Feature | Abgedeckt? |
|-------|-------|-----------------|------------|
| US-GW01 | Alles über eine Adresse | ⚙️ Backend-Only (Reverse Proxy) — **unsichtbar für den Nutzer** | 🔒 Backend |
| US-GW02 | Verbindung automatisch verschlüsselt | ⚙️ Backend-Only (TLS) — Schloss-Symbol im Browser | 🔒 Backend |
| US-GW03 | Station vor unbefugtem Zugriff geschützt | Auth → Login Page + Gateway Auth-Forward | ✅ |

### Icecast (US-IC01–IC03)

| Story | Titel | Frontend-Feature | Abgedeckt? |
|-------|-------|-----------------|------------|
| US-IC01 | Live mithören über den Browser | Livesound → Audio-Player | ✅ |
| US-IC02 | Mikrofon zum Mithören auswählen | Livesound → Recorder-Auswahl | ✅ |
| US-IC03 | Audio-Stream extern teilen | Livesound → Stream-URL teilen | ✅ |

### Web-Interface (US-WI01–WI03)

| Story | Titel | Frontend-Feature | Abgedeckt? |
|-------|-------|-----------------|------------|
| US-WI01 | Anmeldung & Zugangskontrolle | Auth (Login, Session, Brute-Force) | ✅ |
| US-WI02 | Echtzeit-Status ohne Neuladen | SSE Live-Updates, Console, Footer Metrics | ✅ |
| US-WI03 | Nur aktivierte Module anzeigen | Sidebar Module-Gruppe (DB-gesteuert) | ✅ |

---

## ✅ Gap-Analyse — Ehemals fehlende Features (alle gelöst)

Alle 6 Gaps aus der ursprünglichen Cross-Referenz wurden im Web-Mock implementiert:

| # | Gap | User Story | Implementiertes Feature | Status |
|---|-----|-----------|------------------------|--------|
| 1 | **Enrollment-Status** | US-C10 | Badge auf Recorder-Card: `enrolled` (grün) / `generic` (gelb) / `pending` (orange) | ✅ Mock |
| 2 | **Watchdog-Status** | US-R06 | Watchdog Health Card auf Recorder Detail: Progress-Bar `restarts / max` | ✅ Mock |
| 3 | **Upload Bandbreite + Zeitfenster** | US-U04 | Bandwidth Limit (KB/s) + Upload Window in Settings → Remotes und Uploader Detail | ✅ Mock |
| 4 | **Upload-Protokoll (Audit-Log)** | US-U06 | Upload History Tabelle auf Uploader Detail (Status ✓/✗/⏳, Größe, Dauer, Fehler) | ✅ Mock |
| 5 | **BirdNET/BatDetect Konfidenz** | US-B04, US-BD04 | Min. Confidence Range-Slider in Settings → Modules (pro Dienst) | ✅ Mock |
| 6 | **Analysis Window** | US-BD03, US-B04 | Start-/Endzeit-Picker in Settings → Modules (BirdNET + BatDetect, Default: leer = 24/7) | ✅ Mock |

---

## 🔒 Backend-Only — Features ohne Frontend-Sichtbarkeit

Diese Features sind essenziell, werden aber **absichtlich nicht** im Frontend exponiert. Sie laufen unsichtbar im Hintergrund.

| Feature | User Story | Service | Warum kein UI? |
|---------|-----------|---------|---------------|
| **OOM Score Adj** (`-999` für Recorder) | US-C04, US-R02 | Controller | cgroups-Konfiguration auf OS-Ebene — Nutzer muss hier nichts tun |
| **CPU/Memory Limits** pro Container | US-C04 | Controller | Automatisch bei Container-Erstellung gesetzt — kein Tuning nötig |
| **Zero-Trust Bind Mounts** (RO/RW) | US-C04, US-R02 | Controller | Sicherheitsmaßnahme, die transparent funktioniert |
| **Restart Policy** (`on-failure`, max 5) | US-C02 | Controller/Podman | Container-Runtime-Feature — Nutzer sieht nur das Ergebnis |
| **Reconciliation Loop** (1s Polling) | US-C01, US-C03 | Controller | Interner Mechanismus — Nutzer sieht nur das Ergebnis im UI |
| **Redis Nudge Subscriber** | US-C03, US-C07 | Controller | Internes Messaging — UI schreibt in DB, Controller reagiert |
| **Profile Seeding** (YAML → DB) | US-C06, US-C08 | Controller | Bootstrapping beim Start — Ergebnis sichtbar in Profil-Liste |
| **Auth Seeder** (bcrypt Default-Admin) | US-C08 | Controller | Einmalige Initialisierung — Ergebnis sichtbar im Login |
| **Stable Device ID** (Vendor+Product+Serial) | US-C01 | Controller | Interne Identifikation — Nutzer sieht nur den Gerätenamen |
| **Dual-Stream Buffer → Data Promotion** | US-R03 | Recorder | Filesystem-Mechanik — Nutzer sieht nur fertige Dateien in Indexer |
| **FLAC Compression** vor Upload | US-U01 | Uploader | Transparente Optimierung — Nutzer merkt nur kleinere Upload-Größen |
| **TLS Termination** (Caddy auto-cert) | US-GW02 | Gateway | Automatische Zertifikatsverwaltung — Nutzer sieht Schloss im Browser |
| **Reverse Proxy Routing** | US-GW01 | Gateway | Transparente URL-Zuordnung — Nutzer tippt nur eine Adresse ein |
| **Icecast Mount-Point Management** | US-IC02 | Icecast | Interne Stream-Verwaltung — UI zeigt nur Recorder-Auswahl |
| **Store & Forward** (lokaler NVMe Buffer) | VISION.md | Recorder | Architekturprinzip — funktioniert ohne Netzwerk, unsichtbar |
| **Heartbeat Publisher** (fire-and-forget) | VISION.md | Alle Services | Interner Status-Bus — Nutzer sieht Ergebnis als Live-Status im Dashboard |

---

## VISION.md → Frontend Mapping

| VISION-Prinzip | Frontend-Sichtbarkeit |
|---------------|----------------------|
| **Data Capture Integrity** | REC-Indikator, Recorder Status-Badges, Alerts bei Problemen |
| **Autonomy** (self-healing) | Dashboard Orchestration Card zeigt Health, Console zeigt Recovery-Logs |
| **Reproducibility** (containerized) | About Page: Version/Build-Info |
| **Transparency** (structured logging) | Console Panel mit Live JSON-Logs |
| **Security** (container isolation) | Login Page, HTTPS Lock-Icon |
| **Resource Isolation** (cgroups) | 🔒 Backend-Only — kein UI nötig, wirkt im Hintergrund |
| **Store & Forward** | 🔒 Backend-Only — Uploaders zeigen Queue (indirekter Hinweis) |
| **Fleet Mode** (Ansible Zero-Touch) | 🔒 Backend-Only — kein UI-Zugang nötig bei Zero-Touch-Provisioning |
| **Soundscape Scope** (full spectrum) | Recorder Detail zeigt Sample Rate (z.B. 384 kHz für Ultraschall) |

---

## Milestone-Zusammenfassung

| Milestone | Feature-Anzahl |
|-----------|---------------|
| ✅ v0.2.0 (Web-Mock) | ~12 (Shell-Grundstruktur, Station Name, About) |
| v0.8.0 (Web-Interface) | ~57 (Dashboard-Live, Recorders inkl. Enrollment/Watchdog, Uploaders inkl. Audit-Log, Settings inkl. Confidence/Window/Bandwidth, Auth) |
| v0.9.0 (Icecast) | ~4 (Livesound-Player, Stream-URL) |
| v1.1.0 (BirdNET) | ~5 (Birds Discovery/Analyzer/Statistics) |
| v1.2.0 (Weather) | ~4 (Weather Tabs) |
| v1.3.0 (BatDetect) | ~4 (Bats Discovery/Analyzer/Statistics) |
| v1.5.0 (Tailscale) | ~3 (VPN-Toggle, Status, Logs) |
