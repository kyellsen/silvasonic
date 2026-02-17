# ADR-0010: Naming Conventions

> **Status:** Accepted • **Date:** 2026-01-31

## 1. Context & Problem
Consistency in naming across services, packages, and containers is critical for maintainability and automated tooling in the Silvasonic project. A clear separation of concerns and identifiable namespaces are required to prevent conflicts and ensure clarity, but previous documentation was unstructured and wordy.

## 2. Decision
**We chose:** To enforce strict prefixing and namespace isolation across all system components.

**Reasoning:**
*   **Python:** `silvasonic-` prefixes on PyPI packages avoid global name collision. Implicit namespace packages (`silvasonic.*`) allow clean imports.
*   **Podman:** Short service names in compose files (`template`) keep configs readable or "DRY". Explicit container names (`silvasonic-template`) ensure they are easily greppable on the host system.

### Detailed Rules

#### 1. Python Packages & Modules
*   **Package Names:** `silvasonic-<service-name>` (e.g. `silvasonic-recorder`)
*   **Import Names:** `silvasonic.<service_name>` (e.g. `from silvasonic.template import main`)
*   **Directory Structure:** `src/silvasonic/<service_name>/`

#### 2. Container & Infrastructure
*   **Podman Service:** `<service-name>` (e.g. `template`)
*   **Container Name:** `silvasonic-<service-name>` (e.g. `silvasonic-template`)

## 3. Options Considered
*   **No Prefix:** Rejected because of high risk of collision on PyPI and confused naming on host systems running multiple stacks.
*   **Long Service Names in Compose:** Rejected because it makes `podman-compose.yml` verbose and redundant (e.g. `services: silvasonic-template:`).

## 4. Consequences
*   **Positive:** Uniformity across all services; clear ownership of containers on the host system; predictable imports; one source of truth for naming.
*   **Negative:** Slightly verbose package names.
