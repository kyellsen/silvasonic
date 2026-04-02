# Processor Service

> **Status:** implemented (v0.5.0) · **Tier:** 1 · **Instances:** Single · **Port:** 9200

Background workhorse for data ingestion, metadata indexing, and storage retention management. 
Contains the Janitor — the only component authorized to delete files from the Recorder workspace.
Cloud-Sync-Worker (v0.6.0) handles FLAC compression and upload to a single configured remote target.

→ Full documentation: [services/processor/README.md](https://github.com/kyellsen/silvasonic/blob/main/services/processor/README.md)
