# Uploader (Archived)

> **Status:** archived · ~~**Tier:** 2~~ · ~~**Instances:** Multi-instance~~

> [!WARNING]
> **Archived Service:** The standalone Uploader has been replaced by an internal Cloud-Sync-Worker within the Processor service (v0.6.0 KISS refactoring). This document is retained for historical reference.

**Previously planned as:** Data exfiltration service responsible for compressing Raw recordings to FLAC and synchronizing them to remote storage providers.

**Superseded by:** [Processor Service](processor.md) — Cloud-Sync-Worker (internal async worker, single-target).

---

## Migration

See the [Refactoring Plan](../development/refactoring_uploader_to_processor.md) for the full technical migration rationale and implementation details.

### Key Changes

- **Multi-instance → Single-target:** One upload target configured via `system_config` key `"uploader"` (`UploaderSettings`), not via a `storage_remotes` table.
- **Tier 2 → Tier 1:** Upload runs within the Processor service, not as a Controller-managed container.
- **`storage_remotes` table → system_config JSONB:** Remote configuration stored in `UploaderSettings`.
- **`recordings.upload_info` → `recordings.uploaded` boolean:** Simplified upload status tracking.

## References

- [Processor Service](processor.md) — Current home of upload functionality
- [Refactoring Plan](../development/refactoring_uploader_to_processor.md) — Full migration details
- [ADR-0011](../adr/0011-audio-recording-strategy.md) — Raw → FLAC for cloud
- [Glossary](../glossary.md) — Updated terminology
