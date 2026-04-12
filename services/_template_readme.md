# silvasonic-<service>

> **Status:** <Implemented | Partial> (since vX.Y.Z) · **Tier:** <1 | 2> · **Instances:** <Single | Multi> · **Port:** <Port>
>
> 📋 **User Stories:** [story.md](../../docs/user_stories/story.md)

**AS-IS:** <!-- One-liner: what this service IS and does right now in production. -->
**Target:** <!-- Optional: What is planned for future milestones. -->

---

## 1. The Problem / The Gap

*   Why does this service exist? What missing capability does it provide?

## 2. User Benefit

*   What does the user gain? What workflows become possible?

## 3. Core Responsibilities

### Inputs
*   What data/signals does this consume (DB, Hardware, APIs, Redis)?

### Processing
*   What is the core logic/transformation?

### Outputs
*   What does it produce (Files, DB rows, Redis events)?

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                   |
| ---------------- | -------------------------------------------------------------- |
| **Immutable**    | <Yes / No> (via Containerfile / EnvVars)                       |
| **DB Access**    | <Yes / No / Read-Only>                                         |
| **Concurrency**  | <Event Loop / Threadpool / Subprocess>                         |
| **State**        | <Stateless / Stateful>                                         |
| **Privileges**   | <Rootless / Privileged>                                        |
| **Resources**    | <Low / Medium / High>                                          |
| **QoS Priority** | `oom_score_adj=<value>`                                        |

## 5. Configuration & Environment

### Infrastructure (.env / Container Variables)
*(Only list variables/mounts required before the container starts. Never list dynamic DB tuning parameters here).*

| Variable / Mount | Description       | Default / Example |
| ---------------- | ----------------- | ----------------- |
| `SILVASONIC_...` | ...               | ...               |

### Application Settings (Dynamic)

> [!NOTE]
> Managed centrally via DB / Pydantic. See [Configuration Architecture](../../docs/adr/0023-configuration-management.md) for factory defaults and developer overrides.

## 6. Technology Stack

*   Primary libraries and dependencies.

## 7. Out of Scope

*   What does this service explicitly NOT do? (List anti-patterns/boundaries).

## 8. Implementation Details (Domain Specific)

*   *(Free-form area for custom logic, state machines, hardware detection notes, query logic, etc.)*

## 9. References

*   Links to ADRs, Glossary, Vision, etc.
