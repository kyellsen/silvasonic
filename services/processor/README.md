# Processor Service

> **Status:** partial — Phase 1 Skeleton (v0.5.0)
>
> **Tier:** 1 (Infrastructure) · **Port:** 9200

Background workhorse for data ingestion, metadata indexing, and storage retention management.

**Full specification:** [Processor Service Spec](../../docs/services/processor.md)

## Implemented (Phase 1)

- `ProcessorService(SilvaService)` skeleton with health, heartbeat, graceful shutdown
- Runtime config loading from `system_config` table (`ProcessorSettings`)
- Compose integration as Tier 1 service

## Planned

- **Phase 3:** Indexer — filesystem polling & recording registration
- **Phase 4:** Janitor — data retention & storage management
