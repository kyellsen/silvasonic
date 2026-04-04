# ADR-0028: Python Version Flexibility for ML Worker Containers

## Status
Accepted

## Context
The Silvasonic Service Blueprint (`docs/development/service_blueprint.md`) currently mandates `python:3.13-slim-bookworm` as the base image for **all** services without exception. The shared `silvasonic-core` package enforces `requires-python = ">=3.13"`.

This policy creates a hard constraint for the BirdNET worker service (Milestone 0.8.0): the native `tflite-runtime` package — chosen as the inference engine per [ADR-0027](0027-birdnet-inference-engine.md) — has **no official pre-built wheels for Python ≥ 3.12 on aarch64 (Raspberry Pi 5)**. The last published release (2.14.0, October 2023) provides wheels only for Python 3.9–3.11. The package is effectively unmaintained for newer Python versions.

### Architectural Compatibility
Silvasonic's Tier 2 Worker architecture (ADR-0013, ADR-0019) already provides full isolation between containers:
- All inter-service communication is **asynchronous** via PostgreSQL, Redis, and file system bind mounts
- No Python objects are shared across container boundaries
- Each container has its own virtual environment and dependency tree
- The only shared Python code is `silvasonic-core`, which uses standard library features and stable dependencies (Pydantic, SQLAlchemy, structlog, psutil, redis)

The internal Python version of a container is therefore an **implementation detail**, invisible to the rest of the system.

## Decision
We will allow Tier 2 ML worker containers to use `python:3.11-slim-bookworm` as their base image when hardware-specific machine learning libraries (e.g., `tflite-runtime` on aarch64) require it.

### Changes Required
1. **`packages/core/pyproject.toml`**: Lower `requires-python` from `">=3.13"` to `">=3.11"`. This does not affect services running on 3.13 — it merely widens the compatibility floor.
2. **`docs/development/service_blueprint.md`**: Amend the "Mandatory Rules" section to allow documented exceptions for ML worker services where specific dependency constraints dictate an older Python version.
3. **Service-specific `pyproject.toml`**: The BirdNET service will declare `requires-python = ">=3.11"` and use `FROM python:3.11-slim-bookworm` in its Containerfile.

## Rationale

### Why 3.11, not 3.12?
- `tflite-runtime` 2.14.0 has **official aarch64 wheels for 3.11** but not 3.12 or 3.13
- Python 3.11 is still an actively supported CPython release (EOL: October 2027)
- Building `tflite-runtime` from source on aarch64 is fragile and requires the full TensorFlow build toolchain — a CI/CD burden disproportionate to the benefit
- The alternative (`ai-edge-litert`, Google's successor) also lacks stable aarch64 wheels

### Why not require all services to drop to 3.11?
- Only ML services have this constraint. Infrastructure services (Controller, DB-Viewer) and the Recorder have no ML dependencies and benefit from Python 3.13 features (e.g., improved error messages, `TaskGroup` refinements)
- Keeping 3.13 as **default** and 3.11 as **exception** minimizes change surface and avoids unnecessary regression testing
- The Service Blueprint's uniform structure remains intact — only the base image line differs

### `silvasonic-core` Compatibility
The core package uses only standard, well-established libraries:
- `pydantic >=2.0.0`, `sqlalchemy >=2.0.0`, `asyncpg >=0.30.0`, `structlog >=24.0.0`, `psutil >=5.9.0`, `redis >=5.0.0`
- All of these have full Python 3.11 support
- No `silvasonic-core` code uses Python 3.12+ or 3.13+ syntax features (no `type` statement, no `ExceptionGroup` syntax, no `@override`)
- Unit and integration tests must pass on 3.11 after this change (verified via CI matrix or manual test on 3.11 environment)

## Consequences
- **Positive:** BirdNET service can use official `tflite-runtime` wheels on Raspberry Pi 5 without building from source.
- **Positive:** Faster, more reliable container builds for ML services on aarch64.
- **Positive:** Clean architectural precedent for future ML workers (e.g., species classifiers, acoustic indices) that may have similar constraints.
- **Negative:** Two Python versions in the project. Increases CI validation scope (core package must be tested on both 3.11 and 3.13).
- **Negative:** `silvasonic-core` must remain compatible with 3.11. This constrains the core package from adopting 3.12+/3.13+ syntax for new features.
- **Mitigated:** The blueprint change is explicitly scoped to "ML worker exceptions" — it does not open a general escape hatch for arbitrary version downgrades.

## References
- [ADR-0027: BirdNET Inference Engine](0027-birdnet-inference-engine.md)
- [ADR-0020: Resource Limits & QoS](0020-resource-limits-qos.md)
- [Service Blueprint](../development/service_blueprint.md)
- [tflite-runtime PyPI](https://pypi.org/project/tflite-runtime/) — last release 2.14.0, October 2023
