---
name: code-work
description: Fix or implement a requested change in a real local repository, preserve existing work, run the relevant checks, and report the exact diff and test evidence.
---

1. **Find the right repository** and read its instructions first (`AGENTS.md`,
   `CLAUDE.md`, `CONTRIBUTING.md`, `README`). Check `git status` and the current branch.
   Uncommitted work belongs to the person: never discard, reset or overwrite it.
2. **Establish the behavior** from the code, the failing test, the error or the issue
   before editing. Reproduce a defect when you can.
3. **Make a focused change.** Follow the project's style. Add or update a test when the
   change warrants one. Do not reformat unrelated code.
4. **Run the checks that matter** (the project's test, lint, type-check or build
   commands). If something cannot run (missing tool, credential, service), say exactly
   what and why; a skipped check is not a pass.
5. **Inspect the result:** `git diff --stat` and the important hunks; look for unrelated
   edits, debug output and secrets.
6. **Follow the person's instructions** about branches, commits, pushing and deploying.
   Do not commit, push, publish or deploy unless asked. A local build is not a deployment.
7. **Report** the files changed, what the change does, the commands you ran with their
   results, and anything left to do.

On Windows, use the shell the project expects (PowerShell, or Git Bash for `.sh` scripts)
and watch for line-ending changes in the diff.
