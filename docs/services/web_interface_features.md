# Web Interface — Feature Catalog

> **Status:** TO-BE — Feature list of all planned user actions and views.
>
> **References:** [Web-Interface Service Spec](web_interface.md), [Web-Mock README](https://github.com/kyellsen/silvasonic/blob/main/services/web-mock/README.md), [User Stories](../user_stories/web_interface.md)

---

## Shell (Global UI — all pages)

### Header
| Feature | Description | Milestone |
|---------|-------------|-----------|
| Sidebar Toggle | Collapse/expand sidebar | ✅ v0.2.0 |
| Logo → Dashboard | Clicking logo navigates to dashboard | ✅ v0.2.0 |
| Notification Dropdown 🔔 | Dropdown with active alerts (level: error/warn/info, timestamp) | v0.9.0 |
| REC Indicator | Pulsing display: `REC N` — number of active recorders | ✅ v0.2.0 |
| Upload Indicator | Cloud icon with number of active uploaders | ✅ v0.2.0 |
| Dark/Light Mode Toggle 🌗 | Toggle between `silvadark` / `silvalight` theme (localStorage) | ✅ v0.2.0 |
| Inspector Toggle | Collapse/expand right panel | ✅ v0.2.0 |
| User Menu (Avatar) | Dropdown: "Signed in as...", User Settings, **Sign Out** | v0.9.0 |

### Sidebar Navigation
| Feature | Description | Milestone |
|---------|-------------|-----------|
| System Group | Dashboard, Recorders, Processor, Uploaders — always visible | ✅ v0.2.0 |
| Module Group | Livesound, Birds, Bats, Weather — **only if enabled** (DB-driven) | v0.9.0 |
| Settings / About | Pinned to the bottom of the sidebar | ✅ v0.2.0 |

### Footer Status Strip
| Feature | Description | Milestone |
|---------|-------------|-----------|
| Console Toggle | Expandable panel for live log stream | ✅ v0.2.0 |
| System Metrics | Storage %, CPU %, RAM %, Temperature °C, Uptime in h — color-coded | v0.9.0 |
| Device Name + Version | Station ID and software version | ✅ v0.2.0 |

### Console Panel (Log Stream)
| Feature | Description | Milestone |
|---------|-------------|-----------|
| Service Filter Dropdown | Filter log stream by service (Controller, Recorder, ...) | ✅ v0.2.0 |
| SSE Live Stream | Real-time log output via Server-Sent Events | v0.9.0 |
| Auto-Scroll | Automatically scroll to the latest entry | v0.9.0 |

### Inspector Panel (right) — Context-Aware

The Inspector **always shows context-dependent details** about the currently selected object of the active page. On page change, the content automatically updates to the default context of that page.

| Page | Default (no object selected) | On object selection | Milestone |
|------|------------------------------|---------------------------|-----------|
| **Dashboard** | Service Status List: all services with status (running/down), current task info | — (no selectable objects) | v0.9.0 |
| **Recorders** | Quick preview: active/inactive recorders, total recording time | **Recorder Card →** Profile details, ALSA device, workspace, segment duration, gain, enrollment status, watchdog restarts | v0.9.0 |
| **Recorders** | *(Selection)* | **Audio Preview →** Wavesurfer.js waveform + spectrogram of the last recording | v0.9.0+ |
| **Processor** | Indexer summary: files today, total stock, last cleanup | **File Row →** File details: path, duration, sample rate, channels, size, upload/analysis status | v0.9.0 |
| **Uploaders** | Queue total, throughput, last upload | **Uploader Card →** Target details: URL, auth, queue, latest errors, retries | v0.9.0 |
| **Birds** | Species summary: total species, detections today | **Species Card →** Species profile: image, name (en + sci), taxonomy, frequency, confidence | v0.9.0 |
| **Birds** | *(Analyzer Tab)* | **Detection Row →** Wavesurfer.js spectrogram + annotation region, confidence value, recording link | v0.9.0 |
| **Bats** | Species summary (analog to Birds) | **Species Card →** Species profile + ultrasound spectrogram | v1.3.0 |
| **Bats** | *(Analyzer Tab)* | **Detection Row →** Spectrogram overlay (analog to Birds) | v1.3.0 |
| **Weather** | Current metrics compact | **Chart Data Point →** Detailed values at timestamp + correlated species detections | v1.2.0 |
| **Livesound** | Stream status: listeners, bitrate, latency | **Recorder Selection →** Live waveform, peak value, stream URL (copyable) | v1.1.0 |
| **Settings / About** | — (Inspector empty or hidden) | — | — |

---

## 📊 Dashboard (`/`)

| Feature | Description | Milestone |
|---------|-------------|-----------|
| Orchestration Card | Recorder/Uploader/Pending counters, Health badge | v0.9.0 |
| Data Pipeline Card | Index age, Backlog counter, Janitor status | v0.9.0 |
| SSD Storage Card | Radial Progress: used/total GB, percentage | v0.9.0 |
| CPU Card | Avg Load %, Core bar chart (hover: single value), temperature | v0.9.0 |
| RAM Card | Radial Progress: used/total MB | v0.9.0 |
| Uptime Card | Hours since reboot, system healthy badge | v0.9.0 |
| Active Alerts | List of all open warnings (error/warn/info + timestamp) | v0.9.0 |
| Upload Throughput Chart | ECharts Time-Series: upload rate over time | v0.9.0+ |

---

## 🎙️ Recorders (`/recorders`)

| Feature | Description | Milestone |
|---------|-------------|-----------|
| Bento-Grid (max 5) | Recorder Cards: live level bar, sample rate, channels, segment, gain, status badge | v0.9.0 |
| Enrollment Status Badge | Color-coded badge per recorder: `enrolled` (green) / `generic` (yellow) / `pending` (orange) | v0.9.0 |
| Recorder Detail (`/recorders/{id}`) | Detail view: profile name, ALSA device, workspace path, all parameters | v0.9.0 |
| Watchdog Health Card | Progress bar: pipeline restarts (e.g. 2/5), color-coded (green/yellow/red) | v0.9.0 |
| Start/Stop Recorder ⛔ | Enable/disable microphone → writes `enabled` flag to DB → Nudge | v0.9.0 |
| Change Profile 🟨 | Assign different microphone profile → recorder is restarted | v0.9.0+ |
| Inspector: Audio Preview | Wavesurfer.js: Live waveform / spectrogram of selected recorder | v0.9.0+ |

---

## ⚙️ Processor (`/processor`)

| Feature | Description | Milestone |
|---------|-------------|-----------|
| Indexer File Table | Table of recently indexed files (name, duration, sample rate, size, status) | v0.9.0 |
| Retention Event Log | Chronological list of deletion actions (filename, reason, level, timestamp) | v0.9.0 |
| Storage Gauge | Current storage utilization + cleanup level (Normal/Precautionary/Emergency) | v0.9.0 |

> Configuration of Retention Policy → **Settings → Storage & Retention**

---

## ☁️ Uploaders (`/uploaders`)

| Feature | Description | Milestone |
|---------|-------------|-----------|
| Bento-Grid (max 3) | Uploader Cards: queue size, throughput, last sync, status, target type | v0.9.0 |
| Uploader Detail (`/uploaders/{id}`) | Detail view: target URL, auth status, queue details, bandwidth, upload window | v0.9.0 |
| Upload History (Audit-Log) | Table of upload attempts: file, status (✓/✗/⏳), size, duration, error text | v0.9.0 |
| Enable/Disable Uploader | Toggle per Uploader instance | v0.9.0 |

> Configuration of Remote Targets → **Settings → Remotes**

---

## 🐦 Birds (`/birds`)

| Feature | Description | Milestone |
|---------|-------------|-----------|
| Tab: Discovery | Pokédex-style species cards: species image, name (English + scientific), detection counter, confidence | v0.9.0 |
| Tab: Analyzer | Data table with filters (date, species, confidence). Row click → Inspector with Wavesurfer annotation | v0.9.0 |
| Tab: Statistics | ECharts: activity heatmap, Top-10, species diversity over time | v0.9.0 |
| Bird Detail (`/birds/{id}`) | Species detail page: Wikipedia info, image, description, timeline of all detections | v0.9.0 |
| Confidence Threshold | Filter: show only detections above configured threshold | v0.9.0 |

---

## 🦇 Bats (`/bats`)

| Feature | Description | Milestone |
|---------|-------------|-----------|
| Tab: Discovery | Pokédex-style species cards (identical structure to Birds, custom color scheme) | v1.3.0 |
| Tab: Analyzer | Data table with filters, Inspector integration with spectrogram overlay | v1.3.0 |
| Tab: Statistics | ECharts: night activity curve, Top-10, species diversity | v1.3.0 |
| Bat Detail (`/bats/{id}`) | Species detail page with Wikipedia info, image, detection timeline | v1.3.0 |

---

## ☀️ Weather (`/weather`)

| Feature | Description | Milestone |
|---------|-------------|-----------|
| Tab: Overview | Compact view of all current metrics (temp, precipitation, humidity, pressure, wind) | v1.2.0 |
| Tab: Current | Detailed individual values with trend indicators | v1.2.0 |
| Tab: Statistics | ECharts Time-Series per metric (24h/7d/30d selector) | v1.2.0 |
| Tab: Correlation | Dual-Y-Axis Chart: species detections overlaid with weather data | v1.2.0 |

---

## 🔊 Livesound (`/livesound`)

| Feature | Description | Milestone |
|---------|-------------|-----------|
| Recorder Selection | Dropdown/Cards: select active microphones for live monitoring | v1.1.0 |
| Audio Player | Browser-based Opus stream player (Play/Stop/Volume) | v1.1.0 |
| Waveform Visualization | Wavesurfer.js Live waveform of the active stream | v1.1.0 |
| Share Stream URL | Stable URL per microphone stream for VLC/external players | v1.1.0 |

---

## ⚙️ Settings (`/settings`)

### Tab: General
| Feature | Description | Milestone |
|---------|-------------|-----------|
| Station Name | Editable device name (network identity, upload label) | ✅ v0.2.0 |
| Language | Language selection: en / de | v0.9.0 |
| Timezone | Timezone of the station | v0.9.0 |
| Latitude / Longitude | GPS coordinates (for BirdNET regional filter) | v0.9.0 |
| Poweroff on Low Battery | Toggle: automatic shutdown on low battery | v0.9.0+ |
| **Save Changes** Button | Saves General Settings to DB | ✅ v0.2.0 |

### Tab: Modules
| Feature | Description | Milestone |
|---------|-------------|-----------|
| Module Toggles | Enable/disable Livesound, BirdNET, BatDetect, Weather individually | v0.9.0 |
| BirdNET Min. Confidence | Range slider (0.1–1.0): detection threshold for bird species (Default: empty = standard) | v0.9.0 |
| BirdNET Analysis Window | Start/End time picker: limit analysis time window (Default: empty = 24/7) | v0.9.0 |
| BatDetect Min. Confidence | Range slider (0.1–1.0): detection threshold for bat species (Default: empty = standard) | v0.9.0 |
| BatDetect Analysis Window | Start/End time picker: limit analysis to active hours (Default: empty = 24/7) | v0.9.0 |
| **Apply & Reload System** Button 🟨 | Applies module changes — system reload required | v0.9.0 |

### Tab: Storage & Retention
| Feature | Description | Milestone |
|---------|-------------|-----------|
| Max File Age (Days) | Maximum age of recording files before deletion | v0.9.0 |
| Min Free Space Buffer (GB) | Emergency cleanup triggered below this threshold | v0.9.0 |
| Delete after Upload | Toggle: immediately delete local copy after successful upload | v0.9.0 |
| **Save Policy** Button | Saves Retention configuration | v0.9.0 |

### Tab: Remotes
| Feature | Description | Milestone |
|---------|-------------|-----------|
| Remote Target Selection | Dropdown: switch between configured targets | v0.9.0 |
| Server URL | Edit target URL | v0.9.0 |
| Username / Password | Edit credentials | v0.9.0 |
| Target Path / Bucket | Edit target path | v0.9.0 |
| Bandwidth Limit (KB/s) | Limit upload bandwidth (empty = Unlimited) | v0.9.0 |
| Upload Window | Start/End time for uploads (empty = 24/7) | v0.9.0 |
| **Test Connection** Button ✅ | Test connection to remote target (Safe Action) | v0.9.0 |
| **Save Target** Button | Save Remote configuration | v0.9.0 |

### Tab: Network
| Feature | Description | Milestone |
|---------|-------------|-----------|
| WLAN Hotspot Toggle | Turn on/off, status display (SSID, Password, Channel, IP) | v0.9.0+ |
| WLAN Edit Configuration | Edit hotspot settings | v0.9.0+ |
| Tailscale VPN Toggle | Turn on/off, status (Tailnet IP, Hostname, HTTPS Proxy, Auth Status) | v1.5.0 |
| Tailscale View Logs | Display Tailscale log output | v1.5.0 |
| Tailscale Edit Settings | Edit VPN configuration | v1.5.0 |

### Tab: User
| Feature | Description | Milestone |
|---------|-------------|-----------|
| Username (readonly) | Display admin username (not changeable) | v0.9.0 |
| Change Password | Current + new + confirm password | v0.9.0 |
| **Update Security Credentials** Button | Change password (bcrypt hash) | v0.9.0 |

---

## ℹ️ About (`/about`)

| Feature | Description | Milestone |
|---------|-------------|-----------|
| Version Info | Software version, build info | ✅ v0.2.0 |
| Project Links | GitHub, Docs, License | ✅ v0.2.0 |
| Hardware Info | Raspberry Pi model, NVMe, Audio interface | v0.9.0 |

---

## 🔐 Auth (Cross-Cutting)

| Feature | Description | Milestone |
|---------|-------------|-----------|
| Login Page | Username + Password form | v0.9.0 |
| Session Management | Server-side sessions, 24h timeout | v0.9.0 |
| Brute-Force Protection | Max 5 failed attempts → 30s lockout | v0.9.0 |
| Sign Out | End session, redirect → Login | v0.9.0 |

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

### Uploader (US-U01–U06)

| Story | Title | Frontend Feature | Covered? |
|-------|-------|-----------------|------------|
| US-U01 | Recordings automatically to the cloud | Uploaders Page (Queue, Throughput, Status) | ✅ |
| US-U02 | Continue recording indefinitely | Processor Retention + Uploader Status (Interaction) | ✅ |
| US-U03 | Multiple storage targets simultaneously | Settings → Remotes (Dropdown of multiple targets) | ✅ |
| US-U04 | Adjust upload settings | Settings → Remotes (URL, Auth, Path, Bandwidth, Window) | ✅ |
| US-U05 | Upload progress in dashboard | Uploaders Page (Queue, Throughput, Last Sync) + Dashboard | ✅ |
| US-U06 | Seamless upload tracking | Uploader Detail: Upload History Table (Audit-Log) | ✅ |

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
| 3 | **Upload Bandwidth + Time Window** | US-U04 | Bandwidth Limit (KB/s) + Upload Window in Settings → Remotes and Uploader Detail | ✅ Web-Mock |
| 4 | **Upload Protocol (Audit-Log)** | US-U06 | Upload History Table on Uploader Detail (Status ✓/✗/⏳, Size, Duration, Error) | ✅ Web-Mock |
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
| **FLAC Compression** before Upload | US-U01 | Uploader | Transparent optimization — user only notices smaller upload sizes |
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
| **Store & Forward** | 🔒 Backend-Only — Uploaders show Queue (indirect hint) |
| **Fleet Mode** (Ansible Zero-Touch) | 🔒 Backend-Only — no UI access necessary for zero-touch provisioning |
| **Soundscape Scope** (full spectrum) | Recorder Detail shows Sample Rate (e.g. 384 kHz for ultrasound) |

---

## Milestone Summary

| Milestone | Feature Count |
|-----------|---------------|
| ✅ v0.2.0 (Web-Mock) | ~12 (Shell basics, Station Name, About) |
| v0.9.0 (Web-Interface) | ~57 (Dashboard Live, Recorders incl. Enrollment/Watchdog, Uploaders incl. Audit-Log, Settings incl. Confidence/Window/Bandwidth, Auth) |
| v1.1.0 (Icecast) | ~4 (Livesound Player, Stream URL) |
| v0.9.0 (BirdNET) | ~5 (Birds Discovery/Analyzer/Statistics) |
| v1.2.0 (Weather) | ~4 (Weather Tabs) |
| v1.3.0 (BatDetect) | ~4 (Bats Discovery/Analyzer/Statistics) |
| v1.5.0 (Tailscale) | ~3 (VPN Toggle, Status, Logs) |
