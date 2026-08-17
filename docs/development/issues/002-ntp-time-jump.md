# [BUG] 002: NTP Time Jump Paradox during Recorder Initialization

> **Status:** `closed`
>
> **Priority:** 8/10 (Corrupted time series and crashes on a cold boot in the field. Must be fixed in MVP v1.0.0 at the latest.)
>
> **Labels:** `bug` | `architecture`
>
> **Service(s) Affected:** `controller` | `recorder`

---

## 1. Description

On autonomous devices (Raspberry Pi) without a hardware real-time clock, the
FFmpeg recording process in the `recorder` container frequently starts *before*
the network connection — especially over WLAN or LTE — is fully up. The system
boots with a stale clock (for example the one written at the last `fake-hwclock`
shutdown). Once the network comes up after 30–90 seconds, NTP steps the system
clock hard onto the real time.

That time warp happens *while* FFmpeg is already writing audio, and it collapses
the segment calculations and corrupts the time-series data.

## 2. Context & root cause analysis

The architecture is optimised for plug-and-play operation and robustness:

* **Boot speed:** Tier 1 (database, Redis) and Tier 2 (controller) need roughly
  15–20 seconds to come up. As soon as a USB microphone is detected, the
  `recorder` container is spawned immediately.
* **Network delay:** A mobile dial-up (LTE) or difficult WLAN conditions
  (outdoors) often take far longer — 30 to 90 seconds.
* **Time jump:** Lacking a battery-backed RTC, the Pi restores the time of its
  last regular shutdown via `fake-hwclock`. When NTP finally takes hold, the
  system clock jumps forward by days, weeks or months — at exactly the moment
  the FFmpeg segmenter is running.

## 3. Impact / consequences

* **Data capture integrity:** The internal FFmpeg segmenter works from runtime
  calculations based on the system clock. The time chaos crashes processes or
  produces `.wav` files that internally claim to be weeks long ("50-year jump").
* **System stability:** Container restarts whenever FFmpeg dies.
* **Data layer:** The database time series (`start_time`, `end_time`) are
  destroyed by wrong or overlapping timestamps, because time no longer advances
  monotonically.

## 4. Steps to reproduce

1. Boot a Raspberry Pi with no internet and no RTC module. The clock is stale
   (`fake-hwclock`).
2. Attach a USB microphone if one is not already connected. The `recorder`
   container starts the FFmpeg recording.
3. Plug in a network cable (hotplug), or wait for a UMTS/LTE stick to complete
   its delayed connection.
4. `systemd-timesyncd` steps the clock hard → FFmpeg crashes or writes broken
   files into `.buffer/`.

## 5. Expected behaviour

The system, and the FFmpeg recording in particular, must stay stable across
fundamental jumps of the underlying system clock. The process must neither crash
nor attribute wrong durations to segments. Time warping has to be absorbed by
the architecture.

## 6. Proposed solution

**Preferred solution: robustness inside FFmpeg.** Rather than making the
controller wait for `time-sync.target` — which would make the offline use case in
the forest impossible — the recording logic is isolated:

* **Audio hardware ticks instead of the system clock:** FFmpeg must not segment
  by absolute system time. Segments are cut on bare hardware metrics instead —
  a strict sample count, or bytes written.
* **Python segment promoter:** The final assignment of real-world timestamps
  happens in the promoter, when it moves files from `.buffer/` to `data/`. It
  watches for the clock becoming plausible (NTP-synchronised) and only then
  assigns correct epochs, or records "un-synced" in the metadata.

## 7. Relevant documentation links

* [AGENTS.md](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md)
* [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md)
