# Processor Service

> **Status:** implemented (v0.5.0) · **Tier:** 1 · **Instances:** Single · **Port:** 9200

> [!WARNING]
> **Docs-as-Code Trap:**
> This is a temporary **Planning Document**. When the service is implemented, do **NOT** copy this file into the source code as its `README.md`!
> Instead, strictly follow the rules in `docs/STRUCTURE.md` for Service READMEs (no paraphrased endpoints, no DB tables). Once implemented, this file must be replaced by an abstract link-stub.

Background workhorse for data ingestion, metadata indexing, and storage retention management. 
Contains the Janitor — the only component authorized to delete files from the Recorder workspace.
Cloud-Sync-Worker (v0.6.0) handles FLAC compression and upload to a single configured remote target.

→ Full documentation: [services/processor/README.md](https://github.com/kyellsen/silvasonic/blob/main/services/processor/README.md)
