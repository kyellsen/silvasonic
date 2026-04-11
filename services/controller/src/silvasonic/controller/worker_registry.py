"""Registry of background system workers.

Defines the operational specifications (QoS, resource limits) for Tier 2 singleton containers
that perform backend analysis (e.g., BirdNET) according to ADR-0020 and ADR-0029.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class BackgroundWorker:
    """Definition for a singleton Tier 2 background worker."""

    name: str
    image: str
    memory_limit: str
    cpu_limit: float
    oom_score_adj: int
    needs_recorder_read_access: bool = False
    needs_own_workspace: bool = False


SYSTEM_WORKERS: list[BackgroundWorker] = [
    BackgroundWorker(
        name="birdnet",
        image="localhost/silvasonic_birdnet:latest",
        memory_limit="512m",
        cpu_limit=1.0,  # Native ai_edge_litert uses 1 thread optimally
        oom_score_adj=500,  # Expendable analysis worker (ADR-0020)
        needs_recorder_read_access=True,  # To read audio files from the indexer output
        needs_own_workspace=True,  # To store audio clips under workspace/birdnet/clips
    ),
]
