---
description: Auto-generate a Git commit message based on repository changes
---

1. Read the commit guidelines in `docs/development/commit.md`.
2. Analyze the current repository status and uncommitted changes. 
// turbo-all
3. Run `git status > /tmp/git_status.txt && git diff > /tmp/git_diff.txt` (or `git diff --cached > /tmp/git_diff_cached.txt` for staged changes) to capture the changes.
4. Read the generated temporary files using your file tools to understand what was modified.
5. Draft a commit message strictly adhering to the standards defined in `docs/development/commit.md`.
6. Output the raw commit message directly in your chat output inside a standard markdown text block (` ```text `). Do not add any introductory text before the code block.
7. Immediately after the code block, provide a short summary of the most important changes in German (kurze Zusammenfassung auf Deutsch).
