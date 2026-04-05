# Commit Message Guidelines

> **Status:** Normative (Mandatory) · **Scope:** All Contributors & AI Agents

This document outlines the standard for creating Git commit messages in the Silvasonic repository. Our approach leans heavily on [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) to automate versioning and provide a highly readable `git log`.


## 1. Commit Message Structure

Every commit message must follow this anatomy:

```text
<type>(<optional scope>): <subject starting with lowercase>

<optional body mentioning issues or rationale>
- Use bullet points for structural readability
- Explain what was tested or changed
- Group features logically if commit is larger
```

## 2. Types

Select one of the following prefixes for the `<type>`:

- **feat**: A new feature (often tied to a Milestone, e.g., `feat(v0.5.0-p1)`).
- **fix**: A bug fix (e.g., `fix(controller)` or `fix(architecture)`).
- **docs**: Documentation only changes (e.g., updates to `ROADMAP.md` or adding new `.md` files).
- **refactor**: A code change that neither fixes a bug nor adds a feature.
- **chore**: Tooling, pipeline, linter, or configuration changes.
- **release**: Version bump commits (e.g., `release: v0.5.0`).

If the commit introduces a breaking change, append a `!` after the type/scope (e.g., `refactor!: replace CSV tracking`).

## 3. The Subject Line

- Keep it concise (≤ 50-70 characters).
- Do not capitalize the first letter.
- Do not end with a period.
- Use the imperative mood (e.g., "add X" instead of "added X").

## 4. The Body

- Leave one blank line between the Subject and Body.
- Start sections with labels if the commit is complex (e.g., `Bug Fix (Issue 003):`, `Testing:`).
- Use `-` or `*` for bullet points.
- Specifically mention related Issue IDs (e.g., `Fixes Issue 003` or `Resolves #12`).
- Include test results or testing patterns implemented if applicable.

## 5. Examples

**Example 1: Bugfix**
```text
fix(controller): sync volatile ALSA/USB state on device reconnect

Bug Fix (Issue 003):
- Resolve endless crash loops caused by drifted ALSA indices.
- Update `upsert_device` to explicitly rewrite JSONB config payload.

Testing:
- Add `test_upsert_device_updates_volatile_hardware_config` for DB mutation.
- Refactor and quiet unawaited asyncio warnings in mocked integrations.
```

**Example 2: Feature Milestone**
```text
feat(processor): implement Indexer & Reconciliation audit (v0.5.0 Phase 3)

- Add new `IndexRecordings` class to map filesystem raw audio into database arrays.
- Implemented core metadata injection preventing foreign-key violations.
- Verified parallel test suite execution constraints.
```
