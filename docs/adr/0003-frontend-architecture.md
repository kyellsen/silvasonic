# ADR-0003: Frontend Architecture ("The Modern Monolith")

> **Status:** Accepted (Amended 2026-02-23) • **Date:** 2026-01-31

## 1. Context & Problem
The Silvasonic project requires a frontend architecture that follows the "Fast & Light" philosophy. The system must run performantly on constrained hardware (e.g., Raspberry Pi). Classic Single-Page Applications (SPAs) often require complex build pipelines and burden the client with expensive hydration processes.

## 2. Decision
**We chose:** FastAPI + Jinja2 + HTMX + Alpine.js + Tailwind CSS + DaisyUI.

**Reasoning:**
*   **"Fast & Light" Philosophy:** Focus on minimal overhead and high efficiency.
*   **Reduced Complexity:** Direct access to backend logic via server-side rendering; no duplication of logic between client and server.
*   **Performance on Raspberry Pi:** Server-side rendering is often faster on weak clients than client-side hydration, enabling a smoother user experience on the Pi.

### Amendment (2026-02-23): Build-Time npm Distinction

The original decision stated "No Node.js build step is required." This is amended to distinguish:

*   **Runtime SPA npm (REJECTED):** No React/Vue/Svelte hydration at runtime. No client-side framework with its own virtual DOM, state management, or build-time compilation step that runs on every code change during development.
*   **Build-time npm (ACCEPTED):** A one-time `npx tailwindcss` compilation step in the production Containerfile is accepted. This runs during image build, not at runtime. In development, Tailwind CSS is loaded via CDN — no local Node.js installation required.

This distinction preserves the core intent (no SPA complexity, no runtime npm dependency) while enabling modern CSS tooling. See [ADR-0021](0021-frontend-design-system.md) for the full frontend design system decision.

## 3. Options Considered
*   **Single Page Application (React/Vue):** Rejected.
    *   Reasons: Requires a separate build pipeline (Node.js), increases infrastructure complexity, and can be slower on weak hardware (Raspberry Pi) during the hydration phase.

## 4. Consequences
*   **Positive:**
    *   Simplified deployment (Python stack only, with a single build-time CSS compilation step).
    *   Better performance on low-end devices.
    *   Faster development cycles for full-stack features.
    *   DaisyUI's pure CSS approach means zero JavaScript conflicts with HTMX DOM swaps.
*   **Negative:**
    *   Foregoing the extremely broad ecosystem of React/Vue components (though Alpine.js/Vanilla JS offer alternatives).
    *   Production Containerfile requires a `npx tailwindcss` build step (one-time, during image build).

## See Also

*   [ADR-0021: Frontend Design System](0021-frontend-design-system.md) — Tailwind CSS, DaisyUI, ECharts, Wavesurfer.js
