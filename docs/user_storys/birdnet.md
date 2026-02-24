# User Stories — BirdNET Service

> **Service:** BirdNET · **Tier:** 2 (Immutable) · **Status:** Planned (since v1.1.0)

---

## US-B01: Vogelarten automatisch erkennen 🐦

> **Als** Forscher
> **möchte ich,** dass meine Aufnahmen automatisch auf Vogelstimmen analysiert werden und die erkannten Arten mit Zeitstempel und Zuverlässigkeit in der Datenbank erscheinen,
> **damit** ich ein vollständiges Artinventar meines Standorts erhalte — ohne jede Aufnahme manuell durchhören zu müssen.

### Akzeptanzkriterien

- [ ] Alle indexierten Aufnahmen werden automatisch analysiert — ohne manuellen Anstoß.
- [ ] Pro erkanntem Vogelruf wird die Art, der Zeitpunkt im Audio und ein Konfidenzwert gespeichert.
- [ ] Die Analyse läuft im Hintergrund und arbeitet den Rückstand selbstständig ab.
- [ ] Bereits analysierte Aufnahmen werden nicht erneut verarbeitet.

### Milestone

- **Milestone:** v1.1.0

### Referenzen

- [BirdNET Service Docs](../services/birdnet.md)
- [ADR-0018: Worker Pull Orchestration](../adr/0018-worker-pull-orchestration.md)

---

## US-B02: Erkannte Arten in der Web-Oberfläche ansehen 📋

> **Als** Nutzer
> **möchte ich** in der Web-Oberfläche eine Liste aller erkannten Vogelarten sehen — mit Häufigkeit, letztem Nachweis und Konfidenz,
> **damit** ich schnell verstehe, welche Arten an meinem Standort vorkommen.

### Akzeptanzkriterien

- [ ] Die Web-Oberfläche zeigt eine Artenliste mit Anzahl der Nachweise, letztem Erkennungszeitpunkt und durchschnittlicher Konfidenz.
- [ ] Jede Art hat eine Detailseite mit Beschreibung, Bild und zeitlichem Aktivitätsverlauf.
- [ ] Die Liste lässt sich nach Häufigkeit, Datum oder Konfidenz sortieren.
- [ ] Nur Nachweise oberhalb des eingestellten Konfidenz-Schwellenwerts werden angezeigt.

### Milestone

- **Milestone:** v1.1.0

### Referenzen

- [BirdNET Service Docs §Outputs](../services/birdnet.md)

---

## US-B03: Erkennung an den Standort anpassen 📍

> **Als** Forscher
> **möchte ich** den Standort meiner Station (Breitengrad, Längengrad) eingeben können,
> **damit** die Vogelarten-Erkennung auf die regional vorkommenden Arten eingeschränkt wird und weniger Fehlerkennungen liefert.

### Akzeptanzkriterien

- [ ] Standort-Koordinaten sind in den Systemeinstellungen konfigurierbar (Web-Oberfläche).
- [ ] BirdNET nutzt die Koordinaten, um das Artenmodell auf die Region einzuschränken.
- [ ] Änderung der Koordinaten wird automatisch übernommen (Dienst wird bei Bedarf neu gestartet).
- [ ] Der Default-Standort ist sinnvoll vorbelegt.

### Milestone

- **Milestone:** v1.1.0

### Referenzen

- [BirdNET Service Docs §Dynamic Configuration](../services/birdnet.md)
- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)
- [Controller User Stories — US-C08: Funktioniert sofort nach Installation](./controller.md)

---

## US-B04: Erkennungsgenauigkeit einstellen 🎚️

> **Als** Forscher
> **möchte ich** den Konfidenz-Schwellenwert für die Vogelarten-Erkennung anpassen können,
> **damit** ich je nach Bedarf entweder mehr Einzelnachweise (niedriger Schwellenwert) oder weniger Fehlalarme (hoher Schwellenwert) erhalte.

### Akzeptanzkriterien

- [ ] Der Konfidenz-Schwellenwert ist über die Web-Oberfläche einstellbar (Standard: 25 %).
- [ ] Nachweise unterhalb des Schwellenwerts werden nicht in der Artenliste angezeigt.
- [ ] Änderungen werden automatisch übernommen — der Dienst startet bei Bedarf neu.
- [ ] Im Dashboard ist der aktuelle Schwellenwert sichtbar.

### Milestone

- **Milestone:** v1.1.0

### Referenzen

- [BirdNET Service Docs §Dynamic Configuration](../services/birdnet.md)
- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)

---

> [!NOTE]
> **Aufnahme-Schutz:** Dieser Dienst darf die laufende Aufnahme nicht beeinträchtigen. Ressourcenlimits, QoS-Priorisierung und Datei-Isolation werden zentral über den Controller verwaltet (→ [US-C04](./controller.md), [US-R02](./recorder.md)).

---

## US-B05: Analyse-Status im Dashboard 📊

> **Als** Nutzer
> **möchte ich** im Dashboard sehen, wie viele Aufnahmen noch auf Analyse warten und ob BirdNET gerade aktiv ist,
> **damit** ich den Zustand der Analyse-Pipeline jederzeit einschätzen kann.

### Akzeptanzkriterien

- [ ] Das Dashboard zeigt: Anzahl ausstehender Aufnahmen, zuletzt analysierte Datei und aktuelle Aktivität (aktiv/wartend/offline).
- [ ] Bei Problemen (z.B. BirdNET gestoppt oder im Rückstand) wird eine Warnung angezeigt.
- [ ] BirdNET meldet seinen Status regelmäßig an die Web-Oberfläche.

### Milestone

- **Milestone:** v1.1.0

### Referenzen

- [ADR-0019: Unified Service Infrastructure §Heartbeat](../adr/0019-unified-service-infrastructure.md)
- [BirdNET Service Docs](../services/birdnet.md)

---

## US-B06: BirdNET ein- und ausschalten 🔌

> **Als** Nutzer
> **möchte ich** die Vogelarten-Erkennung über die Web-Oberfläche aktivieren oder deaktivieren können,
> **damit** ich Rechenleistung und Energie spare, wenn ich die Analyse nicht benötige.

### Akzeptanzkriterien

- [ ] BirdNET kann über die Web-Oberfläche aktiviert und deaktiviert werden.
- [ ] Bei Deaktivierung wird der Dienst sauber beendet — keine laufende Analyse wird abgebrochen.
- [ ] Bei Reaktivierung arbeitet BirdNET den aufgelaufenen Rückstand selbstständig ab.
- [ ] Der aktuelle Zustand (aktiv/deaktiviert) ist im Dashboard sichtbar.

### Milestone

- **Milestone:** v1.1.0

### Referenzen

- [Controller User Stories — US-C03: Dienste über die Web-Oberfläche steuern](./controller.md)
- [ADR-0017: Service State Management](../adr/0017-service-state-management.md)
