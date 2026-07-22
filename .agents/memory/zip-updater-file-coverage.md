---
name: ZIP updater file coverage
description: The self-update ZIP path must copy all Python modules, not a whitelist
---

# ZIP updater must never use a fixed file whitelist

**Rule:** The ZIP update path copies ALL `*.py` files from the release plus requirements.txt, VERSION, templates/, static/ — excluding only `bssci_config.py` (holds local settings like UPDATE_CHANNEL) and never user data (endpoints.json, users.json, .env, certs).

**Why:** A fixed whitelist crash-looped a user's Docker container: updated `web_main.py` imported the newly added `observability.py`, which wasn't on the list and never got copied → `ModuleNotFoundError` boot loop after restart. Recovery required `docker cp` of missing modules into the stopped container.

**How to apply:** When adding new top-level modules or asset directories, verify the updater in `web_ui.py` (`_download_and_extract_zip`) picks them up; anything outside `*.py`/templates/static needs explicit handling. Note endpoints.json/users.json ARE tracked in the git repo — a naive "extract everything" would clobber user data; keep exclusions intact.
