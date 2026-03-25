# User Stories — Icecast Service

> **Service:** Icecast · **Tier:** 1 (Infrastructure) · **Status:** Planned (since v1.1.0)

---

## US-IC01: Live mithören über den Browser 🔊

> **Als** Anwender
> **möchte ich** den Live-Klang meiner Station direkt im Browser anhören können,
> **damit** ich vor Ort oder aus der Ferne prüfen kann, ob die Mikrofone korrekt funktionieren — ohne Dateien herunterladen zu müssen.

### Akzeptanzkriterien

- [ ] In der Web-Oberfläche kann der Live-Audio-Stream per Klick gestartet und gestoppt werden.
- [ ] Die Wiedergabe beginnt innerhalb weniger Sekunden — kein minutenlanges Puffern.
- [ ] Der Stream verbraucht nur dann Ressourcen, wenn jemand tatsächlich zuhört.
- [ ] Auch über eine mobile Verbindung (z.B. Tailscale) ist der Stream nutzbar.

### Milestone

- **Milestone:** v1.1.0

### Referenzen

- [Icecast Service Docs](../services/icecast.md)
- [ADR-0011: Audio Recording Strategy §5 Live Opus Stream](../adr/0011-audio-recording-strategy.md)
- [Recorder User Stories — US-R04: Live mithören über den Browser](./recorder.md)
- [Gateway User Stories — US-GW01: Alles über eine Adresse erreichbar](./gateway.md)

---

## US-IC02: Mikrofon zum Mithören auswählen 🎤

> **Als** Anwender
> **möchte ich** bei mehreren angeschlossenen Mikrofonen auswählen können, welches ich gerade live hören möchte,
> **damit** ich gezielt einzelne Standorte oder Frequenzbereiche überprüfen kann.

### Akzeptanzkriterien

- [ ] In der Web-Oberfläche wird eine Liste aller aktuell aktiven Mikrofone angezeigt.
- [ ] Per Klick kann zwischen den Mikrofonen gewechselt werden — ohne die Seite neu laden zu müssen.
- [ ] Wird ein Mikrofon abgezogen, verschwindet es aus der Auswahl; wird es wieder angesteckt, erscheint es automatisch.

### Milestone

- **Milestone:** v1.1.0

### Referenzen

- [Icecast Service Docs §Mount Point Management](../services/icecast.md)
- [Recorder User Stories — US-R05: Mehrere Mikrofone gleichzeitig](./recorder.md)
- [Controller User Stories — US-C01: Mikrofon einstecken — sofort erkannt](./controller.md)

---

## US-IC03: Audio-Stream extern teilen 🌍

> **Als** Forscher
> **möchte ich** den Live-Audio-Stream meiner Station als URL weitergeben können,
> **damit** Kollegen, Studierende oder Citizen-Science-Teilnehmer die Soundscape in Echtzeit verfolgen können — ohne Zugang zur Web-Oberfläche zu benötigen.

### Akzeptanzkriterien

- [ ] Jedes Mikrofon hat eine eigene, stabile Stream-URL.
- [ ] Die URL kann in jedem gängigen Audioplayer (VLC, Browser) geöffnet werden.
- [ ] Der externe Zugang kann bei Bedarf deaktiviert oder durch ein Passwort geschützt werden.
- [ ] Die Anzahl gleichzeitiger Zuhörer ist begrenzt, um die Station nicht zu überlasten.

### Milestone

- **Milestone:** v1.1.0

### Referenzen

- [Icecast Service Docs §Outputs](../services/icecast.md)
- [Gateway User Stories — US-GW03: Station ist vor unbefugtem Zugriff geschützt](./gateway.md)

---

> [!NOTE]
> **Aufnahme-Schutz:** Der Live-Stream ist best-effort — ein Ausfall des Streaming-Servers hat keinen Einfluss auf die laufende Dateiaufnahme. Ressourcenlimits und Priorisierung werden zentral über den Controller verwaltet (→ [US-C04](./controller.md), [US-R02](./recorder.md), [ADR-0011 §5](../adr/0011-audio-recording-strategy.md)).
