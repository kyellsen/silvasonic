# UI, UX & Design System

> **Status:** Active · **Last Updated:** 2026-02-23

This document defines the Silvasonic UI design system and usage guidelines.
It is referenced by [ADR-0021](../../adr/0021-frontend-design-system.md).

## Technology Stack

| Layer         | Technology   | Version |
| ------------- | ------------ | ------- |
| CSS Framework | Tailwind CSS | 4.x     |
| UI Components | DaisyUI      | 5.x     |
| Typography    | Geist / Mono | latest  |
| Icons         | Lucide       | latest  |

## Themes: silvalight & silvadark

Two themes are defined in `input.css` using OKLCH colors inside
`@layer theme { [data-theme="..."] { ... } }`.

Theme switching is handled via Alpine.js in `base.html`,
stored in `localStorage` under `silvasonic-dark-mode`.

### Brand Colors

| Role          | Purpose                       | Example Usage                    |
| ------------- | ----------------------------- | -------------------------------- |
| **primary**   | Main brand (Grün, hue 150)    | CTAs, logo, active nav highlight |
| **secondary** | Tech accent (Violet, hue 310) | Module nav active, badges        |
| **accent**    | Highlight (Amber, hue 75)     | Warnings-adjacent, rewards       |

### Status Colors

`info`, `success`, `warning`, `error` are inherited from DaisyUI defaults —
no custom overrides needed for now.

## Module Accent Colors

Each service module has a unique accent color, registered as Tailwind custom
colors via `@theme { --color-mod-<name>: ... }`.

| Module        | Tailwind Class     | Character         |
| ------------- | ------------------ | ----------------- |
| **Dashboard** | `bg-mod-dashboard` | Blau (Overview)   |
| **Recorder**  | `bg-mod-recorder`  | Teal (Capture)    |
| **Processor** | `bg-mod-processor` | Orange (Compute)  |
| **Uploader**  | `bg-mod-uploader`  | Indigo (Transfer) |
| **Birds**     | `bg-mod-birds`     | Gelb (Avian)      |
| **Bats**      | `bg-mod-bats`      | Pink (Ultrasonic) |
| **Weather**   | `bg-mod-weather`   | Hellblau (Env)    |

All module colors work with `bg-`, `text-`, `border-`, `ring-` prefixes.

## Usage Guidelines

### 1. Global CTAs

Always use `btn-primary` for main actions (e.g. "Start Recording", "Apply Config").
Never use module colors for global buttons.

### 2. Module Color Usage

Module accent colors are **only** for module-specific identity:

- **Sidebar active indicator** — left border or dot on the active nav item
- **Page header** — icon tint or thin underline
- **Badges/chips** — within the module's own page (use low opacity, e.g. `bg-mod-birds/15`)

### 3. Backgrounds & Text

- Use `bg-base-100` for cards, `bg-base-200` for page backgrounds
- Never use module colors as full-area backgrounds — only use them at
  low opacity (e.g. `bg-mod-recorder/10`) for subtle tinting
- Text on colored backgrounds: use `text-base-content` or `text-primary-content`

### 4. Contrast

- On `btn-primary`: text is automatically `text-primary-content`
- On colored badges: keep opacity low enough that `text-base-content` remains readable

### 5. Don't Mix Themes

- Never hardcode `oklch(...)` values directly in templates — always use
  DaisyUI semantic classes (`bg-primary`, `text-error`, etc.) or
  module color utilities (`bg-mod-recorder`)
- This ensures light/dark mode switching works correctly
