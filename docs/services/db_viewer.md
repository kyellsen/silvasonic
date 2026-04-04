# DB-Viewer Service

> **Status:** Implemented (since v0.7.1) · **Tier:** 1 · **Port:** 8002

> [!WARNING]
> **Docs-as-Code Trap:**
> This is a temporary **Planning Document**. When the service is implemented, do **NOT** copy this file into the source code as its `README.md`!
> Instead, strictly follow the rules in `docs/STRUCTURE.md` for Service READMEs (no paraphrased endpoints, no DB tables). Once implemented, this file must be replaced by an abstract link-stub.

The DB-Viewer acts as an Interim Dev UI (read-only) for visually inspecting the database state. 
Originally planned as a transitional solution, it has proven highly valuable and will be kept as an optional background service. 
To run it, you must explicitly enable its profile in `.env` via `COMPOSE_PROFILES=db-viewer`.

→ Full documentation: [services/db-viewer/README.md](https://github.com/kyellsen/silvasonic/blob/main/services/db-viewer/README.md)
