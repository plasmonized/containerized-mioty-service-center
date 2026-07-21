---
name: Logging basicConfig no-op
description: Why app logs never reached Docker stdout in this project
---

Rule: in this app, any module imported before logging setup (web_ui adds its in-memory WebUILogHandler to the root logger at import time) makes `logging.basicConfig()` a silent no-op — a console StreamHandler must be added explicitly for logs to reach stdout/Docker.

**Why:** Docker console showed only Flask's own startup lines while all application logs went exclusively to the in-memory UI log viewer; users saw "no logs" for TLS/BSSCI events.

**How to apply:** when touching logging setup, keep the explicit StreamHandler add in web_main.py (guarded so it isn't duplicated) and don't reintroduce basicConfig as the sole console setup.
