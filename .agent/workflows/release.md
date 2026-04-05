---
description: Auto-generate the release sequence and update version files
---

1. Read the instructions in `docs/development/release_checklist.md`.
2. Ask the user for:
   - The target version number (e.g., `0.9.0`)
   - The Milestone Name (e.g., `Worker Orchestration & Models`) 
   - Verify if this is a Feature Release or a Patch Release.
3. Automatically update the version variables in the following files:
   - `packages/core/src/silvasonic/core/__init__.py`
   - `pyproject.toml`
   - `README.md`
   - `ROADMAP.md` (Update the roadmap status to `✅ Current` for the new version and `✅ Done` for the previous version)
4. Autonomously prepare the *next* minor version in the `ROADMAP.md` as well (set it to `🔨 In Progress`).
// turbo-all
5. Run the command `uv lock` in the terminal to sync the lockfile.
6. Generate a final Markdown code block containing the exact commands the user needs to execute for the final release. Emphasize that the user must run `just ci` themselves before executing the git commands. The output should look like this:

```bash
# 1. Run all checks locally
just ci

# 2. Stage changes
git status
git add -A

# 3. Commit
git commit -m "release: v<Version> — <Milestone-Name>"

# 4. Tag
git tag -a v<Version> -m "v<Version> — <Milestone-Name>"

# 5. Push
git push origin main
git push origin v<Version>
```
