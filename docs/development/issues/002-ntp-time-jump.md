# NTP Time Jump Paradox during Recorder Initialization

**Status:** `open`
**Priority:** 8/10 (Korrumpierte Time-Series und Crashes beim Cold Boot in the field. Unbedingt in MVP v1.0.0 oder früher fixen.)
**Labels:** `bug` | `architecture`
**Service(s) Affected:** `controller` | `recorder`

---

## 1. Description
Auf autonomen (Raspberry Pi) Geräten ohne Hardware-Echtzeituhr (RTC) startet der FFmpeg-Aufnahmeprozess im `recorder`-Container häufig *bevor* die Netzwerkverbindung (insbesondere via WLAN oder LTE) vollständig aufgebaut ist. Das System startet mit einer veralteten Uhrzeit (z.B. vom letzten `fake-hwclock` Shutdown). Sobald die Netzwerkverbindung nach z.B. 30-90 Sekunden steht, synchronisiert NTP die Systemuhr hart auf die echte Zeit.

Dieser Zeitsprung (Time-Warp) passiert *während* FFmpeg bereits aktiv Audiodaten speichert und führt zu kollabierenden Segment-Berechnungen und korrupten Time-Series-Daten.

## 2. Context & Root Cause Analysis
Die Architektur ist auf Plug&Play und Robustheit optimiert:
* **Boot-Geschwindigkeit:** Tier 1 (DB, Redis) und Tier 2 (Controller) benötigen ca. 15-20 Sekunden für den Start. Sobald ein USB-Mikrofon erkannt wird, spawnt sofort der `recorder`-Container.
* **Netzwerk-Verzögerung:** Eine mobile Einwahl (LTE) oder schwierige WLAN-Bedingungen (Outdoor) dauern oft weitaus länger (30-90 Sekunden). 
* **Zeitsprung:** Der Pi lädt beim Startmangels Batterie-RTC die Uhrzeit des letzten regulären Shutdowns (über `fake-hwclock`). Wenn NTP schließlich greift, springt die Systemzeit schlagartig um Tage, Wochen oder Monate vorwärts – genau in dem Moment, in dem der FFmpeg-Segmenter läuft.

## 3. Impact / Consequences
* **Data Capture Integrity:** Der interne FFmpeg-Segmenter arbeitet mit Laufzeit-Berechnungen basierend auf der Systemzeit. Der Zeitchaos führt zu crashenden Prozessen oder zu .wav-Dateien, die intern behaupten, wochenlang zu sein ("50-Jahre-Sprung").
* **System Stability:** Potentielle Container-Neustarts bei FFmpeg-Abstürzen.
* **Data Layer:** Die Datenbank-Zeitserien (`start_time`, `end_time`) werden durch falsche oder überschneidende Timestamps komplett zerschossen, da die Zeit nicht monoton verläuft.

## 4. Steps to Reproduce (If applicable)
1. Raspberry Pi (ohne Internet, ohne RTC-Modul) starten. Die Zeit ist veraltet (`fake-hwclock`).
2. USB-Mikrofon anschließen (falls nicht schon verbunden). Der `recorder`-Container startet die FFmpeg-Aufnahme.
3. Ein Netzwerkkabel anschließen (Hotplugging) oder auf den erfolgreichen, verzögerten Verbindungsaufbau eines UMTS/LTE-Sticks warten.
4. `systemd-timesyncd` synchronisiert hart die Zeit (Zeitsprung) $\rightarrow$ FFmpeg crasht oder schreibt defekte Dateien in `.buffer/`.

## 5. Expected Behavior
Das System (insbesondere die FFmpeg-Aufnahme) muss robuste Laufzeitstabilität gegen fundamentale Zeitsprünge der underlying Systemuhr aufweisen. Weder darf der Prozess abstürzen, noch dürfen Segmente falsche Dauern reklamiert bekommen. Time-Warping muss durch das Architektur-Design fließend kompensiert werden können.

## 6. Proposed Solution
**Favorisierte Lösung: Robustheit in FFmpeg**
Anstatt den Controller auf `time-sync.target` warten zu lassen (was den Offline-Use-Case im Wald unmöglich machen würde), muss die Aufzeichnungslogik isoliert werden:
* **Audio-Hardware-Ticks statt System-Uhr:** FFmpeg darf nicht nach absoluter Systemzeit segmentieren, sondern sollte Segmente auf Basis nackter Hardware-Metriken trennen (z.B. Segmentierung nach strikter Sample-Anzahl oder generierten Datei-Bytes).
* **Python-SegmentPromoter:** Die tatsächliche und finale Vergabe der "Echtzeit"-Zeitstempel für Segmente findet erst durch den Promoter statt, wenn er die Dateien von `.buffer/` nach `data/` verschiebt. Er überwacht, wann die Zeit "sinnvoll" (NTP-synchronisiert) wird und weist erst dann korrekte Epochen zu (oder vermerkt "un-synced" in den Metadaten).

## 7. Relevant Documentation Links
* [AGENTS.md](../../AGENTS.md)
* [VISION.md](../../VISION.md)
