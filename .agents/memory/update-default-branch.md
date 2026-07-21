---
name: Update system default branch
description: The GitHub repo's default branch is release, not main - update logic must detect it
---

# Default branch is `release`, not `main`

**Rule:** The self-update system must never hardcode a branch name. It detects the default branch via the GitHub repo API (`default_branch`), with `git ls-remote --symref origin HEAD` as fallback, defaulting to `release`.

**Why:** The repo (plasmonized/containerized-mioty-service-center — note: GitHub renamed it to all-lowercase) removed its `main` branch. Hardcoded `git checkout main` switched user containers to a stale local `main`, running ancient code and crash-looping after every UI update. ZIP fallback also 404'd on `refs/heads/main.zip`.

**How to apply:** Any git/ZIP update path or remote-version check must use the detected default branch; abort git path cleanly (fall back to ZIP) if checkout/pull fails instead of leaving the repo on a wrong branch.
