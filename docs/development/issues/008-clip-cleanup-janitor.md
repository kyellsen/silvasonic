# [TASK] 008: Janitor Clip Cleanup for Analysis Workers

> **Status:** `open`
>
> **Priority:** 4 (not blocking v0.8.0, but required before production use)
>
> **Labels:** `enhancement`, `tech-debt`
>
> **Service(s) Affected:** `processor` (Janitor)

---

## 1. Description

When the Janitor deletes old recordings from `data/processed/` (based on retention thresholds), the corresponding audio clips extracted by analysis workers (BirdNET, BatDetect) remain orphaned on disk in their respective workspace directories (`birdnet/clips/`, `batdetect/clips/`).

These orphaned clips will accumulate indefinitely and waste NVMe storage.

## 2. Context & Root Cause Analysis

* **Component:** `Janitor` (in `services/processor/src/silvasonic/processor/janitor.py`)
* **Mechanism:** The Janitor currently deletes recordings based on `local_deleted` flag and age thresholds. It has no awareness of the `detections.clip_path` column or the analysis worker workspace directories.

The `clip_path` column was introduced in v0.8.0 (BirdNET milestone) to store relative paths to detection audio clips. The clips are stored in per-worker workspace directories (e.g., `birdnet/clips/42_9000_12000_Turdus_merula.wav`).

## 3. Impact / Consequences

* **Data Capture Integrity:** No impact — this is a storage issue only.
* **System Stability:** No immediate risk. Long-term NVMe fill-up could trigger the Janitor's own warning thresholds.
* **Hardware Wear:** Minimal — clips are small (~50–200 KB each), but accumulation over months is significant.

## 4. Steps to Reproduce

1. Run BirdNET analysis on a set of recordings (v0.8.0+).
2. Wait for the Janitor to delete old recordings past the retention threshold.
3. Observe that `birdnet/clips/` still contains WAV files for deleted recordings.

## 5. Expected Behavior

When the Janitor marks a recording as `local_deleted=true` and removes its audio files, it should also:
1. Query `detections.clip_path` for all detections referencing the deleted `recording_id`.
2. Delete the corresponding clip files from the analysis worker workspaces.
3. Set `detections.clip_path = NULL` for the affected rows (or leave as-is if the path is just a reference).

## 6. Proposed Solution

Extend the Janitor's deletion logic:

1. **Before deleting a recording's audio files**, query all related detections:
   ```sql
   SELECT clip_path FROM detections WHERE recording_id = :id AND clip_path IS NOT NULL
   ```
2. **Delete each clip file** from the corresponding workspace directory.
3. **Optionally** null out the `clip_path` column to reflect the deletion.

The Janitor already has read-write access to the workspace. It would need an additional `:z` mount for `birdnet/` and `batdetect/` (or a shared parent mount).

**Alternative:** A separate cleanup cron job that finds clips with no matching `recording_id` (orphan detection). Simpler but less immediate.

## 7. Relevant Documentation Links

* [ADR-0009: Zero-Trust Data Sharing](../../adr/0009-zero-trust-data-sharing.md) — Consumer Principle (read-only mounts exception for Janitor?)
* [ADR-0020: Resource Limits & QoS](../../adr/0020-resource-limits-qos.md) — Storage budgets
* [Milestone v0.8.0](../milestones/milestone_0_8_0.md) — BirdNET (introduced `clip_path`)
* [Filesystem Governance §2](../../arch/filesystem_governance.md) — BirdNET workspace structure
