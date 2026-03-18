# User Stories — Web Interface

> **Service:** Web-Interface · **Tier:** 1 (Infrastructure) · **Status:** Planned (since v0.8.0)
>
> **Prototype:** Der [web-mock](../../services/web-mock/README.md) Service (seit v0.2.0) implementiert die vollständige UI-Shell mit Mock-Daten und dient als **lebende UX-Spezifikation**. Alle Seiten-Layouts, Navigations­muster und Interaktions­abläufe sind dort prototypisch umgesetzt — sie sind anschaulicher als Prosa-Beschreibungen.
>
> **UX-Konzept:** [docs/services/web_interface.md](../services/web_interface.md) — Layout, Routing Rulebook, Action Risk Classification, Page Blueprints, Migration Path.

> [!NOTE]
> **Bewusst wenige Stories:** Seitenbezogene UX-Anforderungen (Dashboard-Widgets, Recorder-Cards, Species-Listen etc.) werden durch den Web-Mock-Prototyp und die [Page Blueprints](../services/web_interface.md#4-page-blueprints) spezifiziert. Funktionale Anforderungen an die Datenanzeige stehen in den jeweiligen Service-User-Stories (z.B. [US-C05](./controller.md#us-c05), [US-P04](./processor.md#us-p04), [US-U05](./uploader.md#us-u05), [US-B02](./birdnet.md#us-b02)). Dieses Dokument beschreibt nur **cross-cutting UI-Verhalten**, das nicht aus dem Prototyp oder den Service-Stories ersichtlich ist.

---

## US-WI01: Anmeldung & Zugangskontrolle 🔐

> **Als** Anwender
> **möchte ich** mich mit Benutzername und Passwort an der Web-Oberfläche anmelden müssen,
> **damit** Unbefugte im gleichen Netzwerk keinen Zugriff auf meine Aufnahmen und Einstellungen haben.

### Akzeptanzkriterien

#### Login-Flow
- [ ] Alle Seiten erfordern eine aktive Session — ohne Anmeldung wird auf die Login-Seite umgeleitet.
- [ ] Login-Formular: Benutzername + Passwort, Validierung gegen `users`-Tabelle (bcrypt-Hash, [US-C08](./controller.md#us-c08)).
- [ ] Nach erfolgreicher Anmeldung: Weiterleitung zur zuletzt besuchten Seite (oder Dashboard als Standard).
- [ ] Logout-Button in der Sidebar (unterhalb von Settings/About).

#### Session-Management
- [ ] Sessions werden serverseitig verwaltet (kein JWT — Silvasonic ist Single-Node, kein verteiltes System).
- [ ] Session-Timeout nach konfigurierbarer Inaktivitätszeit (Standard: 24 Stunden).
- [ ] Bei Session-Ablauf: automatische Umleitung zur Login-Seite mit Hinweis.

#### Sicherheit
- [ ] Brute-Force-Schutz: maximal 5 Fehlversuche, dann 30 Sekunden Sperre.
- [ ] Passwort-Änderung über Settings → User ([Page Blueprint §4.7](../services/web_interface.md#47-settings-tabs)).
- [ ] Das Standard-Passwort aus der Erstinstallation ([US-C08](./controller.md#us-c08)) wird als änderungsbedürftig markiert.

### Nicht-funktionale Anforderungen

- Die Anmeldung darf **keine Auswirkung** auf laufende Aufnahmen haben — die Web-Oberfläche ist ein reines Beobachtungs- und Steuerungswerkzeug.
- Ausnahme: Health-Endpoint (`/healthy`) bleibt **ohne** Authentifizierung erreichbar.

### Milestone

- **Milestone:** v0.8.0

### Referenzen

- [Web-Interface Service Docs §Settings → User](../services/web_interface.md#47-settings-tabs)
- [Controller User Stories — US-C08: Funktioniert sofort nach Installation](./controller.md#us-c08)
- [Gateway User Stories — US-GW03: Station ist vor unbefugtem Zugriff geschützt](./gateway.md#us-gw03)
- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)

---

## US-WI02: Echtzeit-Status ohne Neuladen 🔄

> **Als** Anwender
> **möchte ich,** dass sich der System-Status (Recorder-Zustände, Metriken, Alerts) live aktualisiert, ohne dass ich die Seite neu laden muss,
> **damit** ich den aktuellen Zustand meiner Station jederzeit auf einen Blick erfassen kann.

### Akzeptanzkriterien

#### Live-Updates
- [ ] Alle Status-Widgets (Dashboard-Cards, Sidebar-Badges, Recorder-Status, Alerts) aktualisieren sich in Echtzeit via Server-Sent Events (SSE).
- [ ] Der SSE-Endpunkt liefert initial den vollständigen Zustand (`silvasonic:status:*` Keys aus Redis) und danach nur noch Deltas (`SUBSCRIBE silvasonic:status`).
- [ ] HTMX-basierte DOM-Swaps sorgen für flüssige Updates ohne Full-Page-Reload.

#### Resilienz
- [ ] Bei Verbindungsabbruch (z.B. WLAN-Wechsel) versucht der Client automatisch, die SSE-Verbindung wiederherzustellen.
- [ ] Während der Wiederverbindung wird ein visueller Hinweis angezeigt (z.B. „Verbindung unterbrochen…").
- [ ] Falls Redis temporär ausfällt, zeigt die UI den letzten bekannten Zustand an — kein leerer Bildschirm.

#### Footer Console (Live-Logs)
- [ ] Der Web-Mock-Prototyp ([SSE Console](../../services/web-mock/README.md)) wird durch echtes Redis-`SUBSCRIBE silvasonic:logs` ersetzt ([ADR-0022](../adr/0022-live-log-streaming.md)).
- [ ] Log-Nachrichten werden nach Service filterbar, mit Auto-Scroll und Pause-Funktion.

### Milestone

- **Milestone:** v0.8.0

### Referenzen

- [Web-Interface Service Docs §1.4: State Management & Data Flow](../services/web_interface.md#14-state-management--data-flow)
- [Web-Mock SSE Console](../../services/web-mock/src/silvasonic/web_mock/__main__.py) — Prototyp-Implementierung
- [ADR-0019: Unified Service Infrastructure §Heartbeat](../adr/0019-unified-service-infrastructure.md)
- [ADR-0022: Live Log Streaming](../adr/0022-live-log-streaming.md)
- [Controller User Stories — US-C09: Dienst-Logs live im Browser](./controller.md#us-c09)
- [Controller User Stories — US-C05: Systemstatus im Dashboard](./controller.md#us-c05)

---

## US-WI03: Nur aktivierte Module anzeigen 📦

> **Als** Anwender
> **möchte ich,** dass in der Navigation nur die Module sichtbar sind, die ich tatsächlich aktiviert habe (z.B. Birds, Bats, Weather),
> **damit** die Oberfläche übersichtlich bleibt und mich nicht mit Funktionen ablenkt, die ich nicht nutze.

### Akzeptanzkriterien

- [ ] Modul-Einträge in der Sidebar (Birds, Bats, Weather, Livesound) werden nur angezeigt, wenn das zugehörige Modul in Settings → Modules aktiviert ist.
- [ ] Der Aktivierungsstatus wird aus der Datenbank gelesen (`system_services`-Tabelle, `enabled`-Flag).
- [ ] Wird ein Modul aktiviert/deaktiviert, aktualisiert sich die Sidebar **ohne Page-Reload** (HTMX-Swap oder SSE-Push).
- [ ] Der Zugriff auf die URL eines deaktivierten Moduls (z.B. `/birds` bei deaktiviertem BirdNET) zeigt eine freundliche Hinweis-Seite — kein 404.
- [ ] Beim Erststart sind alle optionalen Module deaktiviert — nur System-Seiten (Dashboard, Recorders, Processor, Uploaders) sind sichtbar.

### Milestone

- **Milestone:** v0.8.0

### Referenzen

- [Web-Interface Service Docs §3.1: Layout & Navigation](../services/web_interface.md#31-layout--navigation)
- [Web-Mock Templates](../../services/web-mock/src/silvasonic/web_mock/templates/base.html) — Sidebar-Prototyp (zeigt aktuell immer alle Module)
- [Controller User Stories — US-C03: Dienste über die Web-Oberfläche steuern](./controller.md#us-c03)
- [ADR-0017: Service State Management](../adr/0017-service-state-management.md)

---

> [!NOTE]
> **UX-Spezifikation lebt im Code:** Für alle seitenbezogenen Details (Layouts, Farben, Komponenten, Interaktionen) ist der [web-mock](../../services/web-mock/README.md) die normative Referenz. User Stories beschreiben hier ausschließlich **Verhalten**, das nicht aus dem Prototyp ersichtlich ist.
