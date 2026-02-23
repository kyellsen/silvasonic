# ADR-0021: Frontend Design System — Tailwind CSS + DaisyUI + ECharts + Wavesurfer.js

> **Status:** Accepted • **Date:** 2026-02-23

## 1. Context & Problem

The Web-Interface (v0.8.0) requires a modern, IDE-style design system that performs well on constrained hardware (Raspberry Pi 5) without conflicting with the HTMX + Alpine.js architecture.

## 2. Decision

We selected a lightweight, CSS-first stack:

| Layer                   | Technology     | Version |
| ----------------------- | -------------- | ------- |
| **CSS Framework**       | Tailwind CSS   | 4.x     |
| **UI Components**       | DaisyUI        | 5.x     |
| **Typography**          | Geist / Mono   | latest  |
| **Icons**               | Lucide         | latest  |
| **Data Visualization**  | Apache ECharts | 5.x     |
| **Audio Visualization** | Wavesurfer.js  | 7.x     |

> **Note:** Full implementation details, aesthetics, and configurations are maintained centrally in **[02. UI, UX & Design System](../services/web_interface/02_ui_ux_design_system.md)**.

## 3. Options Considered & Reasoning (Summary)

*   **DaisyUI vs. JS-heavy frameworks (Preline, Flowbite):** DaisyUI is pure CSS and doesn't conflict with HTMX DOM swaps.
*   **ECharts vs. Plotly:** ECharts handles Canvas/WebGL rendering efficiently for thousands of points, keeping ARM hardware performant.
*   **Wavesurfer.js vs. Peaks.js:** Wavesurfer includes native spectrogram support, eliminating the need for dual audio libraries.
*   **Geist vs. Inter+JetBrains Mono:** Geist provides a perfectly visually unified type system (sans + mono).

## 4. Consequences

*   Zero JS conflicts with HTMX + Alpine.js.
*   Production Containerfile requires a build-time `npx tailwindcss` step (amends ADR-0003's "no npm" rule for build-time only).

## See Also

*   [Web-Interface Design System](../services/web_interface/02_ui_ux_design_system.md)
*   [ADR-0003: Frontend Architecture](0003-frontend-architecture.md)
