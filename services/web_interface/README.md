# Container: Web Interface

> **Service Name:** `web-interface`
> **Container Name:** `silvasonic-web-interface`
> **Package Name:** `silvasonic-web-interface`

## 1. The Problem / The Gap
*   **User Control:** Users need a friendly way to manage the device, view spectrograms, and configure settings without command-line knowledge.
*   **Visualization:** Data needs to be presented human-readably (Charts, Spectrograms).

## 2. User Benefit
*   **Accessibility:** Control the complex system from a Phone or Laptop browser.
*   **Insight:** Immediate visual feedback on recording quality and species detections.

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **User Interactions**: HTTP GET/POST.
    *   **Database**: Reading Recordings/Detections/Config.
    *   **Redis**: Listening for real-time status updates (Stream to WebSocket).
*   **Processing**:
    *   **Rendering**: FastAPI + Jinja2 (Serverside Rendering) + HTMX (Dynamic interactions).
    *   **API**: Providing JSON endpoints for the frontend JS.
*   **Outputs**:
    *   **HTML/JSON**: To User.
    *   **Control Commands**: Publishing to `silvasonic.control` (Redis) to restart services etc.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **High**. Async (Uvicorn).
*   **State**: **Stateless**.
*   **Privileges**: **Rootless**.
*   **Resources**: Moderate (Rendering templates).

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `DB_DSN`: Postgres.
    *   `REDIS_URL`: Redis.
*   **Volumes**:
    *   `/mnt/data` (Read Only): To serve static assets (spectrograms, images).
*   **Dependencies**:
    *   `fastapi`, `uvicorn`, `jinja2`, `redis`.

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** record audio.
*   **Does NOT** manage containers (sends requests to Controller instead).
*   **Does NOT** run heavy analysis (BirdNET runs on separate container).
*   **Does NOT** store persistent data (Database job).
*   **Does NOT** handle SSL/Ingress directly (Gateway job).

## 7. Technology Stack
*   **Base Image**: `python:3.11-slim`.
*   **Key Libraries**:
    *   `fastapi`, `uvicorn`.
    *   `jinja2`, `htmx` (Frontend).
    *   `plotly.js`, `wavesurfer.js` (Frontend).
*   **Build System**: `uv` + `hatchling`.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Modern stack (FastAPI/HTMX) for low complexity but high interactivity.
*   **Alternatives**: React/Vue SPA (Too much build complexity for an embedded appliance; SSR is lighter and faster).

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** None detected.
