---
name: Conventional Commits / Release Please
description: Commit-Message-Konvention für automatisches Versioning und Docker-Release via Release Please
---

# Conventional Commits — Pflicht für dieses Projekt

Dieses Projekt nutzt Release Please für automatische Docker-Releases.
Commit-Nachrichten MÜSSEN das richtige Präfix haben.

## Präfixe

| Präfix | Effekt |
|---|---|
| `feat: ...` | Minor-Bump, Release PR, Docker-Image |
| `fix: ...` | Patch-Bump, Release PR, Docker-Image |
| `BREAKING CHANGE: ...` | Major-Bump, Release PR, Docker-Image |
| `chore: ...` | kein Release |
| `refactor: ...` | kein Release |
| `test: ...` | kein Release |
| `docs: ...` | kein Release |
| `ci: ...` | kein Release |

**Why:** Nur Commits mit `feat:`, `fix:` oder `BREAKING CHANGE:` auf `main` lösen einen Release PR aus. Der Release PR enthält die VERSION-Erhöhung und die Release Notes. Nach dem Merge wird das Docker-Image automatisch auf ghcr.io gebaut und getaggt.

**How to apply:** Bei JEDEM Commit das passende Präfix voranstellen. Bugfixes → `fix:`, neue Features → `feat:`. Interne Änderungen (Tests, Refactoring, CI) → kein Release-Präfix.

## Beispiele

```
feat: add SCACI application center interface
fix: relax X.509 strict CA verification for legacy certs (Python 3.12+/OpenSSL 3.x)
fix: persist SCACI_ENABLED toggle across restarts with config_compat fallback
chore: update tests for Optional queue types
refactor: extract config_compat module
docs: add SCACI protocol reference
ci: fix ruff and mypy errors in GitHub Actions
```
