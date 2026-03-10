# User Stories — Gateway Service

> **Service:** Gateway · **Tier:** 1 (Infrastructure) · **Status:** Planned (since v0.7.0)

---

## US-GW01: Alles über eine Adresse erreichbar 🌐

> **Als** Anwender
> **möchte ich** alle Funktionen meiner Station — Dashboard, Einstellungen, Live-Audio — über eine einzige Adresse im Browser erreichen,
> **damit** ich mir keine verschiedenen Ports oder URLs merken muss.

### Akzeptanzkriterien

- [ ] Alle Web-Dienste (Web-Interface, Live-Stream) sind über eine gemeinsame Adresse erreichbar (z.B. `https://silvasonic.local`).
- [ ] Der Nutzer muss keine Portnummern kennen — die Zuordnung zu den internen Diensten erfolgt automatisch.
- [ ] Statische Inhalte (CSS, Bilder, Schriftarten) werden komprimiert ausgeliefert, damit die Seite auch bei langsamer Verbindung schnell lädt.
- [ ] Fällt der Gateway aus, laufen Aufnahme und alle anderen Dienste trotzdem ungestört weiter.

### Milestone

- **Milestone:** v0.7.0

### Referenzen

- [Gateway Service Docs](../services/gateway.md)
- [Port Allocation](../arch/port_allocation.md)
- [Web-Interface Service Docs §Architecture](../services/web_interface.md)
- [Icecast Service Docs](../services/icecast.md)

---

## US-GW02: Verbindung ist automatisch verschlüsselt 🔒

> **Als** Anwender
> **möchte ich,** dass die Verbindung zu meiner Station automatisch verschlüsselt ist,
> **damit** meine Zugangsdaten und Daten nicht im Klartext übertragen werden — ohne dass ich Zertifikate manuell einrichten muss.

### Akzeptanzkriterien

- [ ] HTTPS ist standardmäßig aktiviert — der Nutzer muss nichts konfigurieren.
- [ ] HTTP-Anfragen werden automatisch auf HTTPS umgeleitet.
- [ ] Im lokalen Netzwerk funktioniert die Verschlüsselung mit einem selbstsignierten Zertifikat; bei Anbindung über Tailscale mit einem gültigen öffentlichen Zertifikat.
- [ ] Die interne Kommunikation zwischen Gateway und Backend-Diensten bleibt unverschlüsselt (kein Overhead im internen Netz).

### Nicht-funktionale Anforderungen

- Die Zertifikatsverwaltung muss vollautomatisch ablaufen — kein manuelles Erneuern nötig.

### Milestone

- **Milestone:** v0.7.0

### Referenzen

- [Gateway Service Docs §TLS Termination](../services/gateway.md)
- [ADR-0014: Dual Deployment Strategy](../adr/0014-dual-deployment-strategy.md)

---

## US-GW03: Station ist vor unbefugtem Zugriff geschützt 🛡️

> **Als** Anwender
> **möchte ich,** dass meine Station durch ein Passwort geschützt ist,
> **damit** nicht jeder im Netzwerk auf meine Aufnahmen und Einstellungen zugreifen kann.

### Akzeptanzkriterien

- [ ] Ohne Anmeldung ist kein Zugriff auf die Web-Oberfläche möglich.
- [ ] Der Zugangsschutz gilt einheitlich für alle Dienste hinter dem Gateway.
- [ ] Bei Anbindung über Tailscale kann die Authentifizierung alternativ über die VPN-Zugehörigkeit erfolgen.
- [ ] Ein Standard-Passwort wird bei der Erstinstallation gesetzt; der Nutzer wird aufgefordert, es zu ändern.

### Milestone

- **Milestone:** v0.7.0

### Referenzen

- [Gateway Service Docs §Authentication](../services/gateway.md)
- [Web-Interface Service Docs §Access](../services/web_interface.md)

---

> [!NOTE]
> **Aufnahme-Schutz:** Dieser Dienst darf die laufende Aufnahme nicht beeinträchtigen. Ressourcenlimits und Priorisierung werden zentral über den Controller verwaltet (→ [US-C04](./controller.md), [US-R02](./recorder.md)).
