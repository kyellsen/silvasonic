# ADR-0036: Svelte Single-Page Application on the Station API

> **Status:** Proposed • **Date:** 2026-11-10 • **Supersedes on acceptance:** [ADR-0003](0003-frontend-architecture.md)

## 1. Context & Problem

ADR-0003 chose server-rendered pages (FastAPI, Jinja2, HTMX) and rejected single-page applications, because their hydration would burden a Raspberry Pi. Two things have changed that picture:

*   **The premise does not hold.** Hydration runs in the browser of the phone or laptop, not on the station. A single-page application asks the station for static files and JSON; rendering HTML for every view is the costlier job for the Pi.
*   **The station gets a JSON API anyway** ([ADR-0032](0032-api-first-station-contract.md)), because the fleet and other services need one. Pages rendered on the server would be a second kind of consumer that no other client exercises.

The dashboard is also meant to be installed on a phone and to open without a network round trip. That needs an application shell a service worker can cache, which pages assembled on the server do not have.

## 2. Decision

**We chose:** a single-page application built with SvelteKit (Svelte 5, TypeScript) in static mode, which talks to the station through `/api/v1` and nothing else.

**Reasoning:**

*   **Static build, no runtime.** `adapter-static` produces HTML, CSS and JavaScript at image build time. The Gateway serves the files. There is no web container, no Python process rendering pages and no Node on the station.
*   **The API client is generated** from the OpenAPI document, so a change to the contract that the dashboard does not follow fails the type check.
*   **Installable.** A web app manifest and a service worker cache the application shell; data always comes live from the API. The app works wherever the station presents a trusted certificate ([ADR-0035](0035-https-and-certificates.md)).
*   **Svelte, not React.** It compiles to small bundles without a runtime library, which suits a phone on a weak connection in the field, and it asks for less ceremony from a single developer. SvelteKit adds routing, the static build and the service worker hook.
*   **The design system of ADR-0021 stays:** Tailwind CSS, DaisyUI with the `silvadark` / `silvalight` themes, ECharts, Wavesurfer.js. Spectrograms of ordinary recordings are drawn in the browser from the audio; the station renders none.
*   **Interface text lives in the frontend** as message catalogues (English, German). Names of species come from the API in the requested language (AGENTS.md §2).
*   **The same code serves the fleet.** A dashboard written against the station contract shows a station viewed through a fleet server, which serves the same resources.

`web-mock` remains the visual reference until the application has caught up, then it is retired. `webtest` is not continued.

## 3. Options Considered

*   **HTMX on server-rendered pages (ADR-0003):** Rejected, for the reasons in §1.
*   **React (Next.js) or Vue (Nuxt):** Rejected. Either would work; both ship a larger runtime and neither offers something this dashboard needs that Svelte lacks.
*   **SvelteKit with server-side rendering:** Rejected. It would put a Node server on the station for a dashboard that has no need of search engines or a first paint without JavaScript.
*   **A native or Flutter app:** Rejected. A second code base and app-store distribution, to reach what an installed web app already reaches.

## 4. Consequences

*   **Positive:**
    *   The station does less work per view, and one process fewer runs on it than ADR-0003 planned.
    *   The dashboard depends on the contract alone and survives changes behind it.
    *   Phone, tablet and desktop get one application that can be installed.
*   **Negative:**
    *   Frontend development and the image build need Node. ADR-0003 had already accepted Node at build time for the stylesheet; developing without a local Node is no longer possible.
    *   Two languages in the repository, and end-to-end tests (Playwright, already in the stack) carry more weight.
    *   The migration path of `docs/services/web_interface.md` — clone `web-mock`, replace mock data route by route — is void.
*   **On acceptance these documents change:** ADR-0003 (status), ADR-0021 (HTMX notes), `AGENTS.md` §5 (Web row), `docs/services/web_interface.md`, `docs/arch/frontend_features.md` (HTMX and SSE wording), US-WI02, `docs/glossary.md` (Web-Interface, Web-Mock).
