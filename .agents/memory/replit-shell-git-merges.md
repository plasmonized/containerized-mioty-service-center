---
name: Replit shell git merges
description: How to complete a git merge/push from the Replit shell without the checkpoint system wiping it
---

# Git merges in the Replit shell get wiped between commands

**Rule:** When the user must merge and push from the Replit shell, the entire sequence (merge → resolve → add → commit → push) has to run as ONE shell line. Pre-stage resolved conflict files outside the repo (e.g. `/tmp/resolved/`) and `cp` them in as part of that line.

**Why:** Replit's checkpoint/gitsafe system repeatedly reset in-progress merge state (MERGE_HEAD, index, even restored conflict markers) between separate user commands, causing "nothing to commit" and rejected non-fast-forward pushes. Only a single compound command survived.

**How to apply:** `git merge origin/<branch>; cp /tmp/resolved/<file> <file>; ...; git add -A; git commit -m "..."; git push origin <branch>` — use `;` after merge since it exits non-zero on conflicts. Agent cannot run destructive git itself; prepare files and hand the one-liner to the user.
