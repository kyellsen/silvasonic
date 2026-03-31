# Milestone v0.10.0 — Marketing Landing Page (Astro)

> **Target:** v0.10.0 — Public-facing marketing page hosted on GitHub Pages (Repo: `kyellsen/silvasonic.de`)
>
> **Status:** ⏳ Planned
>
> **References:** [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)
>
> **User Stories:** n/a

---

## Architectural Context (Option A)

To maintain a strict Separation of Concerns (SoC) between the core Silvasonic bioacoustic monitoring system and its public-facing marketing material, the landing page is structurally isolated from the main repository.

- **Main Repository (`kyellsen/silvasonic`):** Contains the python software stack, device infrastructure, and technical MkDocs documentation (`docs.silvasonic.de`).
- **Website Repository (`kyellsen/silvasonic.de`):** Contains the entirely decoupled, lightweight marketing landing page.

By isolating the landing page repository, we prevent heavy marketing assets (images, fonts, videos) from polluting the container build pipelines. It also enables GitHub Pages to host the main `silvasonic.de` apex domain separately from the `docs.silvasonic.de` subdomain without complex monorepo CI/CD routing.

---

## Phase 1: Repository & Stack Setup

**Goal:** Establish the foundation for the Astro website in the new repository.

### Tasks

- [x] Create the dedicated GitHub Repository `kyellsen/silvasonic.de`
- [ ] Initialize the Astro project (`npm create astro@latest`)
- [ ] Implement Tailwind CSS for utility-first styling
- [ ] Implement Alpine.js (if lightweight reactivity is needed, otherwise prefer plain Astro scripts)
- [ ] Configure `astro.config.mjs` for static site generation (`output: 'static'`)

---

## Phase 2: Design & Content

**Goal:** Implement a responsive, modern landing page explaining the Silvasonic vision.

### Tasks

- [ ] Design Hero Section (Value Proposition, Call to Action)
- [ ] Design Feature Showcase (Acoustic Monitoring, BirdNET inference, Open Source Hardware)
- [ ] Add explicit links to the MkDocs Documentation (`https://docs.silvasonic.de`) and the GitHub Source Code
- [ ] Optimize images and SVGs for maximum load speed

---

## Phase 3: Deployment Pipeline

**Goal:** Automate publishing via GitHub Pages using GitHub Actions.

### Tasks

- [ ] Create `.github/workflows/deploy.yml` using the official `withastro/action`
- [ ] Configure repository Settings -> Pages to build from GitHub Actions
- [ ] Map the apex domain `silvasonic.de` locally via All-Inkl DNS (A-Records pointing to GitHub IPs + CNAME for `www.silvasonic.de`)
- [ ] Verify SSL cert generation via Let's Encrypt in GitHub settings
