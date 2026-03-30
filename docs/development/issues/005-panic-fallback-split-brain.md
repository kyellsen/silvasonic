# Panic-mode filesystem fallback leaves raw/processed pairs inconsistent (Split-Brain)

**Status:** `open`
**Priority:** 5
**Labels:** `bug` | `architecture`
**Service(s) Affected:** `processor`

---

## 1. Description
The Janitor's "Panic-mode" filesystem fallback (triggered when NVMe is >90% full and the DB is unreachable) deletes the oldest `.wav` files individually based on `mtime`. It fails to respect the "Recording Pair" relationship introduced in v0.4.0 (Dual Stream). This can cause a `.raw.wav` file to be deleted while its `.processed.wav` counterpart remains. When the database comes back online, the Reconciliation Loop only verifies if the primary file (`file_processed`) exists. As a result, the database incorrectly asserts that the `.raw.wav` file is still available (Split-Brain state).

## 2. Context & Root Cause Analysis
This is caused by a blind spot for paired audio files during extreme error recovery modes.

* **Component:** `janitor.panic_filesystem_fallback` and `reconciliation.run_audit`
* **Mechanism:**
  * `janitor.py`: Runs `recordings_dir.glob("*/data/*/*.wav")` and unlinks `batch_size` items sequentially by `mtime`. Raw and processed streams are treated as completely independent files.
  * `reconciliation.py`: The audit query uses `SELECT id, COALESCE(file_processed, file_raw) AS check_file`. For a dual-stream device, `check_file` evaluates to `file_processed`. It therefore only checks if the processed file exists on disk, ignoring the fact that the original raw recording has been wiped by the Janitor fallback.

## 3. Impact / Consequences
This occurs only during a "double-failure" scenario (disk >90% + DB offline) but has severe cascading effects:
* **Data Capture Integrity:** Medium. The backend operates under the false assumption that raw data is safely stored.
* **System Stability:** Medium. It introduces latent database corruption. Subsequent services that rely on the file paths (like the upcoming v0.6.0 Uploader or v0.9.0 BirdNET) will crash with a `FileNotFoundError` (HTTP 404).
* **Hardware Wear:** Low.

## 4. Steps to Reproduce (If applicable)
1. Fill recording storage NVMe partition to >90% (Panic Threshold).
2. Take the PostgreSQL database offline (`podman stop silvasonic-db`).
3. Wait for the `Processor` to run its Janitor cycle. Check logs to confirm the fallback to filesystem `mtime` deletion.
4. Observe that only one file of a Dual-Stream pair might be deleted (e.g., `.raw.wav` is gone, `.processed.wav` remains).
5. Restart the database (`podman start silvasonic-db`).
6. Restart the `Processor` to force the Reconciliation Audit.
7. Observe that the DB still flags `local_deleted = false` for the affected row and lists both `file_raw` and `file_processed` paths.

## 5. Expected Behavior
Even under Panic Fallback conditions, the system should delete both paired streams simultaneously. Upon DB recovery, the Reconciliation Loop must proactively verify the physical existence of *both* files for dual-stream recordings. If *either* file is missing, the row must be marked with `local_deleted = true` to preserve the Split-Brain consistency.

## 6. Proposed Solution
1. **Enhance `panic_filesystem_fallback`:** Instead of doing a blind `unlink()` on the returned paths, isolate the file stem (e.g., stripping `.raw.wav` or `.processed.wav`). When one stream is marked for deletion, explicitly execute a deletion on its coupled counterpart.
2. **Enhance `run_audit`:** Modify the SQL query to explicitly fetch both `file_processed` and `file_raw`. In Python, evaluate both `Path` conditions. The row should only be considered "healthy" if both (non-NULL) paths physically exist.

No database schema change is required. No ADR is required.

## 7. Relevant Documentation Links
* [AGENTS.md](../../../AGENTS.md)
* [VISION.md](../../../VISION.md)
* [services/processor/README.md](../../../services/processor/README.md)
