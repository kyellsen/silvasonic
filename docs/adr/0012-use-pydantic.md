# ADR-0012: Use Pydantic for Data Validation

> **Status:** Accepted • **Date:** 2026-01-31

## 1. Context & Problem
As Silvasonic grows into a distributed system with multiple services (recording, processing, monitoring), data integrity and validation become critical. Passing raw dictionaries or untyped JSON between services or internal modules leads to:
*   Runtime errors due to missing keys or wrong types.
*   Code duplication for validation logic.
*   Lack of clarity on what the data structure is supposed to look like.

We need a standard way to define data schemas, validate incoming data, and serialize/deserialize objects safely.

## 2. Decision
**We chose:** [Pydantic](https://docs.pydantic.dev/)

**Reasoning:**
*   **Robust Validation:** Pydantic provides powerful data validation and parsing using Python type hints.
*   **Performance:** The core validation logic is written in Rust (pydantic-core), making it extremely fast.
*   **Ecosystem Standard:** It is widely adopted in the Python ecosystem (e.g., FastAPI, SQLModel) and integrates well with modern tooling.
*   **Developer Experience:** Great editor support (mypy/pyright integration) and helpful error messages.

## 3. Implementation Rules
1.  **Data Models:** All internal data structures passed between modules or services MUST be defined as `pydantic.BaseModel` (or `pydantic.dataclasses`).
2.  **API Schemas:** All HTTP API request and response bodies MUST be Pydantic models.
3.  **Strict Mode:** Where possible, use `strict=True` or `ConfigDict(strict=True)` to prevent silent type coercion implementation details unless necessary.
4.  **Configuration:** Use `pydantic-settings` for managing application configuration via environment variables.

## 4. Consequences
*   **Positive:**
    *   Guaranteed data contract enforcement at runtime.
    *   Self-documenting code via type hints.
    *   Reduced boilerplate for validation logic.
*   **Negative:**
    *   Slight runtime overhead compared to raw dictionaries (minimal with Pydantic v2).
    *   Learning curve for advanced validation features.
