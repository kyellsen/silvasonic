# Web Interface — Feature Catalog

> **Status:** TO-BE — Feature list of all planned user actions and views.
>
> **References:** [Web-Interface Service Spec](../services/web_interface.md), [Web-Mock README](https://github.com/kyellsen/silvasonic/blob/main/services/web-mock/README.md), [User Stories](../user_stories/../services/web_interface.md)

---

## Shell (Global UI — all pages)

### Header
| Feature | Description |
| --------- | ------------- |
| Sidebar Toggle | Collapse/expand sidebar |
| Logo → Dashboard | Clicking logo navigates to dashboard |
| Notification Dropdown 🔔 | Dropdown with active alerts (level: error/warn/info, timestamp) |
| REC Indicator | Pulsing display: `REC N` — number of active recorders |
| Upload Indicator | Cloud icon with upload sync status |
| Dark/Light Mode Toggle 🌗 | Toggle between `silvadark` / `silvalight` theme (localStorage) |
| Inspector Toggle | Collapse/expand right panel |
| User Menu (Avatar) | Dropdown: "Signed in as...", User Settings, **Sign Out** |

### Sidebar Navigation
| Feature | Description |
| --------- | ------------- |
| System Group | Dashboard, Recorders, Processor, Cloud Sync — always visible |
| Module Group | Livesound, Birds, Bats, Weather — **only if enabled** (DB-driven) |
| Settings / About | Pinned to the bottom of the sidebar |

### Footer Status Strip
| Feature | Description |
| --------- | ------------- |
| Console Toggle | Expandable panel for live log stream |
| System Metrics | Storage %, CPU %, RAM %, Temperature °C, Uptime in h — color-coded |
| Device Name + Version | Station ID and software version |

### Console Panel (Log Stream)
| Feature | Description |
| --------- | ------------- |
| Service Filter Dropdown | Filter log stream by service (Controller, Recorder, ...) |
| SSE Live Stream | Real-time log output via Server-Sent Events |
| Auto-Scroll | Automatically scroll to the latest entry |

### Inspector Panel (right) — Context-Aware

The Inspector **always shows context-dependent details** about the currently selected object of the active page. On page change, the content automatically updates to the default context of that page.

| Page | Default (no object selected) | On object selection |
| ------ | ------------------------------ | --------------------------- |
| **Dashboard** | Service Status List: all services with status (running/down), current task info | — (no selectable objects) |
| **Recorders** | Quick preview: active/inactive recorders, total recording time | **Recorder Card →** Profile details, ALSA device, workspace, segment duration, gain, enrollment status, watchdog restarts |
| **Recorders** | *(Selection)* | **Audio Preview →** Wavesurfer.js waveform + spectrogram of the last recording |
| **Processor** | Indexer summary: files today, total stock, last cleanup | **File Row →** File details: path, duration, sample rate, channels, size, upload/analysis status |
| **Cloud Sync** | Queue total, throughput, last upload | **Sync Detail →** Target details: URL, auth, queue, latest errors, retries |
| **Birds** | Species summary: total species, detections today | **Species Card →** Species profile: image, name (en + sci), taxonomy, frequency, confidence |
| **Birds** | *(Analyzer Tab)* | **Detection Row →** Wavesurfer.js spectrogram + annotation region, confidence value, recording link |
| **Bats** | Species summary (analog to Birds) | **Species Card →** Species profile + ultrasound spectrogram |
| **Bats** | *(Analyzer Tab)* | **Detection Row →** Spectrogram overlay (analog to Birds) |
| **Weather** | Current metrics compact | **Chart Data Point →** Detailed values at timestamp + correlated species detections |
| **Livesound** | Stream status: listeners, bitrate, latency | **Recorder Selection →** Live waveform, peak value, stream URL (copyable) |
| **Settings / About** | — (Inspector empty or hidden) | — |

---

## 📊 Dashboard (`/`)

| Feature | Description |
| --------- | ------------- |
| Orchestration Card | Recorder/Pending counters, Health badge, Cloud Sync status |
| Data Pipeline Card | Index age, Backlog counter, Janitor status |
| SSD Storage Card | Radial Progress: used/total GB, percentage |
| CPU Card | Avg Load %, Core bar chart (hover: single value), temperature |
| RAM Card | Radial Progress: used/total MB |
| Uptime Card | Hours since reboot, system healthy badge |
| Active Alerts | List of all open warnings (error/warn/info + timestamp) |
| Upload Throughput Chart | ECharts Time-Series: upload rate over time |

---

## 🎙️ Recorders (`/recorders`)

| Feature | Description |
| --------- | ------------- |
| Bento-Grid (max 5) | Recorder Cards: live level bar, sample rate, channels, segment, gain, status badge |
| Enrollment Status Badge | Color-coded badge per recorder: `enrolled` (green) / `generic` (yellow) / `pending` (orange) |
| Recorder Detail (`/recorders/{id}`) | Detail view: profile name, ALSA device, workspace path, all parameters |
| Watchdog Health Card | Progress bar: pipeline restarts (e.g. 2/5), color-coded (green/yellow/red) |
| Start/Stop Recorder ⛔ | Enable/disable microphone → writes `enabled` flag to DB → Nudge |
| Change Profile 🟨 | Assign different microphone profile → recorder is restarted |
| Inspector: Audio Preview | Wavesurfer.js: Live waveform / spectrogram of selected recorder |

---

## ⚙️ Processor (`/processor`)

| Feature | Description |
| --------- | ------------- |
| Indexer File Table | Table of recently indexed files (name, duration, sample rate, size, status) |
| Retention Event Log | Chronological list of deletion actions (filename, reason, level, timestamp) |
| Storage Gauge | Current storage utilization + cleanup level (Normal/Precautionary/Emergency) |

> Configuration of Retention Policy → **Settings → Storage & Retention**

---

## ☁️ Cloud Sync (`/cloud-sync`)

| Feature | Description |
| --------- | ------------- |
| Single-Target View | Upload queue size, throughput, last sync, status, configured remote target |
| Upload History (Audit-Log) | Table of upload attempts: file, status (✓/✗/⏳), size, duration, error text |
| Enable/Disable Upload | Global toggle for Cloud Sync |

> Configuration of Remote Target → **Settings → Remotes**

---

## 🐦 Birds (`/birds`)

| Feature | Description |
| --------- | ------------- |
| Tab: Discovery | Pokédex-style species cards: species image, name (English + scientific), detection counter, confidence |
| Tab: Analyzer | Data table with filters (date, species, confidence). Row click → Inspector with Wavesurfer annotation |
| Tab: Statistics | ECharts: activity heatmap, Top-10, species diversity over time |
| Bird Detail (`/birds/{id}`) | Species detail page: Wikipedia info, image, description, timeline of all detections |
| Confidence Threshold | Filter: show only detections above configured threshold |

---

## 🦇 Bats (`/bats`)

| Feature | Description |
| --------- | ------------- |
| Tab: Discovery | Pokédex-style species cards (identical structure to Birds, custom color scheme) |
| Tab: Analyzer | Data table with filters, Inspector integration with spectrogram overlay |
| Tab: Statistics | ECharts: night activity curve, Top-10, species diversity |
| Bat Detail (`/bats/{id}`) | Species detail page with Wikipedia info, image, detection timeline |

---

## ☀️ Weather (`/weather`)

| Feature | Description |
| --------- | ------------- |
| Tab: Overview | Compact view of all current metrics (temp, precipitation, humidity, pressure, wind) |
| Tab: Current | Detailed individual values with trend indicators |
| Tab: Statistics | ECharts Time-Series per metric (24h/7d/30d selector) |
| Tab: Correlation | Dual-Y-Axis Chart: species detections overlaid with weather data |

---

## 🔊 Livesound (`/livesound`)

| Feature | Description |
| --------- | ------------- |
| Recorder Selection | Dropdown/Cards: select active microphones for live monitoring |
| Audio Player | Browser-based Opus stream player (Play/Stop/Volume) |
| Waveform Visualization | Wavesurfer.js Live waveform of the active stream |
| Share Stream URL | Stable URL per microphone stream for VLC/external players |

---

## ⚙️ Settings (`/settings`)

### Tab: General
| Feature | Description |
| --------- | ------------- |
| Station Name | Editable device name (network identity, upload label) |
| Language | Language selection: en / de |
| Timezone | Timezone of the station |
| Latitude / Longitude | GPS coordinates (for BirdNET regional filter) |
| Poweroff on Low Battery | Toggle: automatic shutdown on low battery |
| **Save Changes** Button | Saves General Settings to DB |

### Tab: Modules
| Feature | Description |
| --------- | ------------- |
| Module Toggles | Enable/disable Livesound, BirdNET, BatDetect, Weather individually |
| BirdNET Min. Confidence | Range slider (0.1–1.0): detection threshold for bird species (Default: empty = standard) |
| BirdNET Analysis Window | Start/End time picker: limit analysis time window (Default: empty = 24/7) |
| BatDetect Min. Confidence | Range slider (0.1–1.0): detection threshold for bat species (Default: empty = standard) |
| BatDetect Analysis Window | Start/End time picker: limit analysis to active hours (Default: empty = 24/7) |
| **Apply & Reload System** Button 🟨 | Applies module changes — system reload required |

### Tab: Storage & Retention
| Feature | Description |
| --------- | ------------- |
| Max File Age (Days) | Maximum age of recording files before deletion |
| Min Free Space Buffer (GB) | Emergency cleanup triggered below this threshold |
| Delete after Upload | Toggle: immediately delete local copy after successful upload |
| **Save Policy** Button | Saves Retention configuration |

### Tab: Remotes
| Feature | Description |
| --------- | ------------- |
| Remote Target Selection | Dropdown: switch between configured targets |
| Server URL | Edit target URL |
| Username / Password | Edit credentials |
| Target Path / Bucket | Edit target path |
| Bandwidth Limit (KB/s) | Limit upload bandwidth (empty = Unlimited) |
| Upload Window | Start/End time for uploads (empty = 24/7) |
| **Test Connection** Button ✅ | Test connection to remote target (Safe Action) |
| **Save Target** Button | Save Remote configuration |

### Tab: Network
| Feature | Description |
| --------- | ------------- |
| WLAN Hotspot Toggle | Turn on/off, status display (SSID, Password, Channel, IP) |
| WLAN Edit Configuration | Edit hotspot settings |
| Tailscale VPN Toggle | Turn on/off, status (Tailnet IP, Hostname, HTTPS Proxy, Auth Status) |
| Tailscale View Logs | Display Tailscale log output |
| Tailscale Edit Settings | Edit VPN configuration |

### Tab: User
| Feature | Description |
| --------- | ------------- |
| Username (readonly) | Display admin username (not changeable) |
| Change Password | Current + new + confirm password |
| **Update Security Credentials** Button | Change password (bcrypt hash) |

---

## ℹ️ About (`/about`)

| Feature | Description |
| --------- | ------------- |
| Version Info | Software version, build info |
| Project Links | GitHub, Docs, License |
| Hardware Info | Raspberry Pi model, NVMe, Audio interface |

---

## 🔐 Auth (Cross-Cutting)

| Feature | Description |
| --------- | ------------- |
| Login Page | Username + Password form |
| Session Management | Server-side sessions, 24h timeout |
| Brute-Force Protection | Max 5 failed attempts → 30s lockout |
| Sign Out | End session, redirect → Login |

---

## 📋 User Story → Frontend Cross-Reference

Every User Story and whether its acceptance criteria become visible in the frontend.

### Controller (US-C01–C10)

| Story | Title | Frontend Feature | Covered? |
|-------|-------|-----------------|------------|
| US-C01 | Plug in microphone — recognized immediately | Recorders Bento-Grid (new device appears live) | ✅ |
| US-C02 | Crashed services restart automatically | Dashboard Orchestration Card (Status Update), Console Logs | ✅ |
| US-C03 | Control services via web interface | Recorders Start/Stop, Settings → Modules Toggle | ✅ |
| US-C04 | Recording always takes priority | ⚙️ Backend-Only (OOM Score, cgroups) — **no custom UI needed** | 🔒 Backend |
| US-C05 | System status in dashboard | Dashboard Cards (CPU/RAM/Storage/Uptime), Footer Status Strip | ✅ |
| US-C06 | Manage microphone profiles | Recorders Detail → Profile display, change profile | ✅ |
| US-C07 | Disable microphone immediately | Recorders → Start/Stop Toggle (enabled=false) | ✅ |
| US-C08 | Works immediately after installation | ⚙️ Backend-Only (Seeder) — Settings shows result | ✅ indirect |
| US-C09 | Service logs live in browser | Console Panel (SSE Live Stream + Service Filter) | ✅ |
| US-C10 | Unknown microphone works immediately | Recorders Grid: Enrollment Badge (enrolled/generic/pending) | ✅ |

### Recorder (US-R01–R07)

| Story | Title | Frontend Feature | Covered? |
|-------|-------|-----------------|------------|
| US-R01 | Plug in microphone — recording starts | Recorders Grid: Status badge changes to "recording" | ✅ |
| US-R02 | Recording always continues | ⚙️ Backend-Only (Resilience) — Dashboard Alert on failure | ✅ indirect |
| US-R03 | Original and standard format simultaneously | Recorder Detail: shows Raw + Processed stream info | ✅ |
| US-R04 | Listen live via browser | Livesound Page (Audio Player, Recorder selection) | ✅ |
| US-R05 | Multiple microphones simultaneously | Recorders Bento-Grid (multiple cards) | ✅ |
| US-R06 | Automatic recovery on errors | Recorder Detail: Watchdog Health Card (Restarts Progress Bar) | ✅ |
| US-R07 | Set recording segment duration | Recorder Detail: shows segment duration, changing profile alters value | ✅ |

### Processor (US-P01–P04)

| Story | Title | Frontend Feature | Covered? |
|-------|-------|-----------------|------------|
| US-P01 | Recordings appear automatically | Processor → Indexer File Table | ✅ |
| US-P02 | Endless recording without storage worries | Processor → Retention Event Log + Storage Gauge | ✅ |
| US-P03 | Adjust storage rules | Settings → Storage & Retention | ✅ |
| US-P04 | Data pipeline status in dashboard | Dashboard → Data Pipeline Card | ✅ |

### Upload / Cloud Sync (US-U01–U06)

| Story | Title | Frontend Feature | Covered? |
|-------|-------|-----------------|------------|
| US-U01 | Recordings automatically to the cloud | Cloud Sync Page (Queue, Throughput, Status) | ✅ |
| US-U02 | Continue recording indefinitely | Processor Retention + Cloud Sync Status (Interaction) | ✅ |
| ~~US-U03~~ | ~~Multiple storage targets~~ | ~~Archived — KISS single-target~~ | ❌ Archived |
| US-U04 | Adjust upload settings | Settings → Remotes (URL, Auth, Path, Bandwidth, Window) | ✅ |
| US-U05 | Upload progress in dashboard | Cloud Sync Page (Queue, Throughput, Last Sync) + Dashboard | ✅ |
| US-U06 | Seamless upload tracking | Cloud Sync: Upload History Table (Audit-Log) | ✅ |

### BirdNET (US-B01–B06)

| Story | Title | Frontend Feature | Covered? |
|-------|-------|-----------------|------------|
| US-B01 | Automatically detect bird species | Birds → Discovery + Analyzer | ✅ |
| US-B02 | View detected species | Birds → Discovery (Species list + sorting) | ✅ |
| US-B03 | Adjust detection to location | Settings → General (Lat/Lng) | ✅ |
| US-B04 | Adjust detection accuracy | Settings → Modules: BirdNET Min. Confidence Slider + Analysis Window | ✅ |
| US-B05 | Analysis status in dashboard | Dashboard + Inspector (BirdNET running/backlog) | ✅ |
| US-B06 | Enable and disable BirdNET | Settings → Modules (BirdNET Toggle) | ✅ |

### BatDetect (US-BD01–BD07)

| Story | Title | Frontend Feature | Covered? |
|-------|-------|-----------------|------------|
| US-BD01 | Detect bat species | Bats → Discovery + Analyzer | ✅ |
| US-BD02 | Ultrasound microphones only | ⚙️ Backend-Only (Filter) — Dashboard shows qualifying mics | ✅ indirect |
| US-BD03 | Analyze only during bat-active hours | Settings → Modules: BatDetect Analysis Window (Start/End Time) | ✅ |
| US-BD04 | Adjust detection accuracy | Settings → Modules: BatDetect Min. Confidence Slider | ✅ |
| US-BD05 | View detected species | Bats → Discovery (Species list + sorting) | ✅ |
| US-BD06 | Analysis status in dashboard | Dashboard + Inspector (BatDetect status) | ✅ |
| US-BD07 | Enable and disable BatDetect | Settings → Modules (BatDetect Toggle) | ✅ |

### Gateway (US-GW01–GW03)

| Story | Title | Frontend Feature | Covered? |
|-------|-------|-----------------|------------|
| US-GW01 | Everything via one address | ⚙️ Backend-Only (Reverse Proxy) — **invisible to the user** | 🔒 Backend |
| US-GW02 | Connection automatically encrypted | ⚙️ Backend-Only (TLS) — Lock icon in browser | 🔒 Backend |
| US-GW03 | Station protected against unauthorized access | Auth → Login Page + Gateway Auth-Forward | ✅ |

### Icecast (US-IC01–IC03)

| Story | Title | Frontend Feature | Covered? |
|-------|-------|-----------------|------------|
| US-IC01 | Listen live via browser | Livesound → Audio Player | ✅ |
| US-IC02 | Select microphone for listening | Livesound → Recorder Selection | ✅ |
| US-IC03 | Share audio stream externally | Livesound → Share Stream URL | ✅ |

### Web-Interface (US-WI01–WI03)

| Story | Title | Frontend Feature | Covered? |
|-------|-------|-----------------|------------|
| US-WI01 | Login & access control | Auth (Login, Session, Brute-Force) | ✅ |
| US-WI02 | Real-time status without reloading | SSE Live Updates, Console, Footer Metrics | ✅ |
| US-WI03 | Show only enabled modules | Sidebar Module Group (DB-driven) | ✅ |

---

## ⚠️ Prototype Validation — Web-Mock coverage

These features are **successfully validated in the `web-mock` UI prototype**, but are **not yet implemented** in the production Web-Interface backend:

| # | Prototype Feature | User Story | Validated Mock Implementation | Status |
|---|-----|-----------|------------------------|--------|
| 1 | **Enrollment Status** | US-C10 | Badge on Recorder Card: `enrolled` (green) / `generic` (yellow) / `pending` (orange) | ✅ Web-Mock |
| 2 | **Watchdog Status** | US-R06 | Watchdog Health Card on Recorder Detail: Progress-Bar `restarts / max` | ✅ Web-Mock |
| 3 | **Upload Bandwidth + Time Window** | US-U04 | Bandwidth Limit (KB/s) + Upload Window in Settings → Remotes and Cloud Sync Detail | ✅ Web-Mock |
| 4 | **Upload Protocol (Audit-Log)** | US-U06 | Upload History Table on Cloud Sync Page (Status ✓/✗/⏳, Size, Duration, Error) | ✅ Web-Mock |
| 5 | **BirdNET/BatDetect Confidence** | US-B04, US-BD04 | Min. Confidence Range-Slider in Settings → Modules (per service) | ✅ Web-Mock |
| 6 | **Analysis Window** | US-BD03, US-B04 | Start/End time picker in Settings → Modules (BirdNET + BatDetect, Default: empty = 24/7) | ✅ Web-Mock |

---

## 🔒 Backend-Only — Features without UI visibility

These features are essential but are **intentionally not** exposed in the frontend. They run invisibly in the background.

| Feature | User Story | Service | Why no UI? |
|---------|-----------|---------|---------------|
| **OOM Score Adj** (`-999` for Recorder) | US-C04, US-R02 | Controller | OS-level cgroups configuration — user needs no interaction here |
| **CPU/Memory Limits** per Container | US-C04 | Controller | Set automatically on container creation — no tuning necessary |
| **Zero-Trust Bind Mounts** (RO/RW) | US-C04, US-R02 | Controller | Security measure that works transparently |
| **Restart Policy** (`on-failure`, max 5) | US-C02 | Controller/Podman | Container runtime feature — user only sees the result |
| **Reconciliation Loop** (1s Polling) | US-C01, US-C03 | Controller | Internal mechanism — user only sees the result in the UI |
| **Redis Nudge Subscriber** | US-C03, US-C07 | Controller | Internal messaging — UI writes to DB, Controller reacts |
| **Profile Seeding** (YAML → DB) | US-C06, US-C08 | Controller | Bootstrapping on start — result visible in profile list |
| **Auth Seeder** (bcrypt Default-Admin) | US-C08 | Controller | One-time initialization — result visible at login |
| **Stable Device ID** (Vendor+Product+Serial) | US-C01 | Controller | Internal identification — user only sees the device name |
| **Dual-Stream Buffer → Data Promotion** | US-R03 | Recorder | Filesystem mechanics — user only sees finished files in Indexer |
| **FLAC Compression** before Upload | US-U01 | Processor (Cloud-Sync-Worker) | Transparent optimization — user only notices smaller upload sizes |
| **TLS Termination** (Caddy auto-cert) | US-GW02 | Gateway | Automatic certificate management — user sees lock in browser |
| **Reverse Proxy Routing** | US-GW01 | Gateway | Transparent URL mapping — user only types one address |
| **Icecast Mount-Point Management** | US-IC02 | Icecast | Internal stream management — UI only shows recorder selection |
| **Store & Forward** (local NVMe Buffer) | VISION.md | Recorder | Architecture principle — works without network, invisible |
| **Heartbeat Publisher** (fire-and-forget) | VISION.md | All Services | Internal status bus — user sees result as live status in dashboard |

---

## VISION.md → Frontend Mapping

| VISION Principle | Frontend Visibility |
|---------------|----------------------|
| **Data Capture Integrity** | REC Indicator, Recorder Status Badges, Alerts on issues |
| **Autonomy** (self-healing) | Dashboard Orchestration Card shows Health, Console shows recovery logs |
| **Reproducibility** (containerized) | About Page: Version/Build Info |
| **Transparency** (structured logging) | Console Panel with live JSON logs |
| **Security** (container isolation) | Login Page, HTTPS Lock icon |
| **Resource Isolation** (cgroups) | 🔒 Backend-Only — no UI needed, works in background |
| **Store & Forward** | 🔒 Backend-Only — Cloud Sync shows Queue (indirect hint) |
| **Fleet Mode** (Ansible Zero-Touch) | 🔒 Backend-Only — no UI access necessary for zero-touch provisioning |
| **Soundscape Scope** (full spectrum) | Recorder Detail shows Sample Rate (e.g. 384 kHz for ultrasound) |

---

## Milestone Summary

| Milestone | Feature Count |
|-----------|---------------|
| ✅ v0.2.0 (Web-Mock) | ~12 (Shell basics, Station Name, About) |
| v0.9.0 (Web-Interface) | ~57 (Dashboard Live, Recorders incl. Enrollment/Watchdog, Cloud Sync incl. Audit-Log, Settings incl. Confidence/Window/Bandwidth, Auth) |
| v1.1.0 (Icecast) | ~4 (Livesound Player, Stream URL) |
| v0.9.0 (BirdNET) | ~5 (Birds Discovery/Analyzer/Statistics) |
| v1.2.0 (Weather) | ~4 (Weather Tabs) |
| v1.3.0 (BatDetect) | ~4 (Bats Discovery/Analyzer/Statistics) |
| v1.5.0 (Tailscale) | ~3 (VPN Toggle, Status, Logs) |
