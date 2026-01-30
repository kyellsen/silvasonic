# ADR-003: Frontend Architecture ("The Modern Monolith")

> **Status:** Accepted • **Date:** 2026-01-31

## 1. Context & Problem
Für das Silvasonic-Projekt wird eine Frontend-Architektur benötigt, die der "Fast & Light"-Philosophie folgt. Das System soll auch auf eingeschränkter Hardware (z.B. Raspberry Pi) performant laufen. Klassische Single-Page-Applications (SPAs) erfordern oft komplexe Build-Pipelines und belasten den Client durch aufwendige Hydration-Prozesse.

## 2. Decision
**We chose:** Nutzung von FastAPI + Jinja2 + HTMX + Alpine.js.

**Reasoning:**
*   **"Fast & Light" Philosophie:** Fokus auf minimalen Overhead und hohe Effizienz.
*   **Vermeidung einer separaten Build-Pipeline:** Es wird kein Node.js Build-Step benötigt, was das Deployment und die Entwicklungsumgebung vereinfacht.
*   **Reduzierte Komplexität:** Direkter Zugriff auf Backend-Logik durch Server-Side Rendering; keine Duplizierung von Logik zwischen Client und Server.
*   **Performance auf dem Raspberry Pi:** Server-Side Rendering ist auf schwachen Clients oft schneller als Client-Side Hydration, was eine flüssigere User Experience auf dem Pi ermöglicht.

## 3. Options Considered
*   **Single Page Application (React/Vue):** Abgelehnt.
    *   Gründe: Erfordert separate Build-Pipeline (Node.js), erhöht die Komplexität der Infrastruktur und kann auf schwacher Hardware (Raspberry Pi) während der Hydration-Phase langsamer sein.

## 4. Consequences
*   **Positive:**
    *   Vereinfachtes Deployment (nur Python-Stack).
    *   Bessere Performance auf Low-End-Geräten.
    *   Schnellere Entwicklungszyklen für Fullstack-Features.
*   **Negative:**
    *   Verzicht auf das extrem breite Ökosystem an React/Vue-Komponenten (wobei Alpine.js/Vanilla JS Alternativen bietet).
