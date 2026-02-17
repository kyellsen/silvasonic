# ADR-0003: Frontend Architecture ("The Modern Monolith")

> **Status:** Accepted • **Date:** 2026-01-31

## 1. Context & Problem
The Silvasonic project requires a frontend architecture that follows the "Fast & Light" philosophy. The system must run performantly on constrained hardware (e.g., Raspberry Pi). Classic Single-Page Applications (SPAs) often require complex build pipelines and burden the client with expensive hydration processes.

## 2. Decision
**We chose:** FastAPI + Jinja2 + HTMX + Alpine.js.

**Reasoning:**
*   **"Fast & Light" Philosophy:** Focus on minimal overhead and high efficiency.
*   **Avoidance of a Separate Build Pipeline:** No Node.js build step is required, simplifying deployment and the development environment.
*   **Reduced Complexity:** Direct access to backend logic via server-side rendering; no duplication of logic between client and server.
*   **Performance on Raspberry Pi:** Server-side rendering is often faster on weak clients than client-side hydration, enabling a smoother user experience on the Pi.

## 3. Options Considered
*   **Single Page Application (React/Vue):** Rejected.
    *   Reasons: Requires a separate build pipeline (Node.js), increases infrastructure complexity, and can be slower on weak hardware (Raspberry Pi) during the hydration phase.

## 4. Consequences
*   **Positive:**
    *   Simplified deployment (Python stack only).
    *   Better performance on low-end devices.
    *   Faster development cycles for full-stack features.
*   **Negative:**
    *   Foregoing the extremely broad ecosystem of React/Vue components (though Alpine.js/Vanilla JS offer alternatives).
