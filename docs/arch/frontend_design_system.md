# UI, UX & Design System

> **Status:** Active · **Last Updated:** 2026-03-10 · **Palette:** Oktett v3

This document defines the Silvasonic UI design system and usage guidelines.
It is referenced by [ADR-0021](../adr/0021-frontend-design-system.md).

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

| Role          | Purpose                         | Example Usage                    |
| ------------- | ------------------------------- | -------------------------------- |
| **primary**   | Main brand (Emerald, hue 160°)  | CTAs, logo, active nav highlight |
| **secondary** | Tech accent (Violet, hue 290°)  | Module nav active, badges        |
| **accent**    | Highlight (Gold, hue 85°)       | Warnings-adjacent, rewards       |

### Status Colors

`info` (cornflower), `success` (chartreuse), `warning` (gold), `error` (scarlet)
are explicitly defined in both themes using Oktett v3 values.

## Module Accent Colors

Each service module has a unique accent color, registered as Tailwind custom
colors via `@theme { --color-mod-<name>: ... }`.

| Module        | Tailwind Class     | Oktett Name  |
| ------------- | ------------------ | ------------ |
| **Dashboard** | `bg-mod-dashboard` | Emerald      |
| **Recorder**  | `bg-mod-recorder`  | Scarlet      |
| **Processor** | `bg-mod-processor` | Chartreuse   |
| **Uploader**  | `bg-mod-uploader`  | Magenta      |
| **Livesound** | `bg-mod-livesound` | Teal         |
| **Birds**     | `bg-mod-birds`     | Gold         |
| **Bats**      | `bg-mod-bats`      | Violet       |
| **Weather**   | `bg-mod-weather`   | Cornflower   |
| **Settings**  | `bg-mod-settings`  | Slate        |

All module colors use the standardized **Oktett v3 palette** values.
The full palette (including `bg-scarlet`, `text-emerald`, etc.) is also
available as standalone Tailwind utilities via the extended `@theme` block.

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
