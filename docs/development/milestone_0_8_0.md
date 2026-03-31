# Milestone v0.8.0 — BirdNET (On-device Avian Inference)

> **Target:** v0.8.0 — On-device avian species classification (Worker Pull via DB, ADR-0018)
>
> **Status:** ⏳ Planned
>
> **References:** [ADR-0018](../adr/0018-worker-pull-orchestration.md), [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)
>
> **User Stories:** [BirdNET Stories](../user_stories/birdnet.md)

---

## Overview

The BirdNET service is an immutable Tier 2 container responsible for performing on-device inference for avian species classification. It processes recorded audio segments and saves detections into the database.

### Key Capabilities

- Pulls unanalyzed `processed` segments via the database (Worker Pull pattern)
- Runs BirdNET analytical model
- Writes detections (`detections` table) and correlates with taxonomy.

### Prerequisites

| Milestone  | Feature                                          |
| ---------- | ------------------------------------------------ |
| **v0.5.0** | Processor (Indexer + Janitor)                    |

---

## Phase 1: Service Architecture

**Goal:** Create the `birdnet` service adhering to the Service Blueprint.

### Tasks

- [ ] Scaffold `services/birdnet/`
- [ ] Implement inference loop
- [ ] Database integration for reading segments and writing detections

*(Further phases and tasks will be detailed as development begins)*
