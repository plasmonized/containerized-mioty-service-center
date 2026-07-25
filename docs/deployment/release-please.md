---
outline: [2, 3]
---

# Release Please

Dieses Projekt verwendet [Release Please](https://github.com/google-github-actions/release-please-action) für automatische Versionierung und Docker-Image-Veröffentlichung.

## Funktionsweise

Release Please basiert auf [Conventional Commits](https://www.conventionalcommits.org/) und arbeitet in zwei Phasen:

### 1. Release Pull Request

Bei jedem Push auf `main` mit `feat:`, `fix:`, `chore:`, `docs:`, `refactor:` oder `BREAKING CHANGE:`-Commits aktualisiert Release Please einen **Release Pull Request**:

Dieser PR enthält:
- Automatisch berechnete neue Version (z. B. `1.697`)
- Vollständig generierte Release Notes aus den Commit-Nachrichten
- Aktualisierte `VERSION`-Datei

### 2. Veröffentlichung

Sobald der Release PR gemergt wird:

1. **GitHub Release** wird automatisch erstellt
2. **Docker Image** wird auf GitHub Container Registry (`ghcr.io`) gebaut und veröffentlicht
3. Image-Tags: `vX.Y.Z`, `latest`, `stable`, `X.Y.Z`

## Commit-Konvention

Release Please wertet Commit-Nachrichten aus. Verwende folgende Präfixe:

| Präfix | Abschnitt im Changelog | Versionseffekt |
|--------|----------------------|----------------|
| `feat:` | Features | Minor-Bump |
| `fix:` | Bug Fixes | Patch-Bump |
| `BREAKING CHANGE:` | ⚠ Breaking Changes | Major-Bump |
| `chore:` | Chores | Kein Release |
| `docs:` | Documentation | Kein Release |
| `refactor:` | Refactoring | Kein Release |
| `test:` | — | Kein Release |
| `ci:` | — | Kein Release |

> **Hinweis:** Nur Commits auf `main` mit `feat:`, `fix:` oder `BREAKING CHANGE:` lösen einen Release PR aus.

## Beispiel: Kompletter Release-Durchlauf

```bash
# 1. Feature entwickeln und committen
git commit -m "feat: add meter reading export as CSV"
git push origin main

# 2. Release Please erstellt/aktualisiert einen Release PR auf GitHub
#    → https://github.com/plasmonized/containerized-mioty-Service-Center/pulls

# 3. Release PR reviewen und mergen
#    → VERSION wird automatisch von 1.696 auf 1.697 erhöht

# 4. Automatisch:
#    - GitHub Release v1.697 wird erstellt
#    - Docker Image ghcr.io/plasmonized/containerized-mioty-service-center:v1.697
#      wird gebaut und auf ghcr.io gepusht

# 5. Docker-Update auf dem Server
docker-compose pull
docker-compose up -d
```

## Konfiguration

### `release-please-config.json`

```json
{
  "plugins": [],
  "packages": {
    ".": {
      "release-type": "simple",
      "include-v-in-tag": true,
      "bump-minor-pre-major": true,
      "bump-patch-for-minor-pre-major": false,
      "extra-files": ["VERSION"]
    }
  }
}
```

| Option | Bedeutung |
|--------|-----------|
| `release-type` | `simple` — verwaltet eine VERSION-Datei |
| `include-v-in-tag` | Tags enthalten `v`-Präfix (z. B. `v1.697`) |
| `bump-minor-pre-major` | Solange Major=1, wird Minor erhöht (nicht Patch) |
| `extra-files` | Zusätzliche Dateien, die die Version enthalten |

### `.release-please-manifest.json`

Enthält die aktuelle Version des Projekts:

```json
{
  ".": "1.696"
}
```

Wird von Release Please automatisch aktualisiert.

## Workflow

Der Release-Workflow befindet sich in `.github/workflows/release-please.yml`:

```yaml
name: Release Please

on:
  push:
    branches: [ "main" ]

jobs:
  release-please:
    outputs:
      release_created: ${{ steps.release.outputs.release_created }}
      tag_name: ${{ steps.release.outputs.tag_name }}
    steps:
      - uses: google-github-actions/release-please-action@v4

  docker:
    needs: release-please
    if: ${{ needs.release-please.outputs.release_created == 'true' }}
    steps:
      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/...:${{ needs.release-please.outputs.tag_name }}
```

### Ablauf

```
Push auf main
    │
    ▼
Release Please (checkt Commits)
    │
    ├── Neue feats/fixes? → Release PR erstellen/aktualisieren
    │
    └── Release PR gemergt?
        │
        ▼
    release_created=true
        │
        ▼
    Docker Build & Push
        │
        ▼
    GitHub Release + ghcr.io Image
```

## Manuelle Releases (Notfall)

Für manuelle Releases steht der Legacy-Workflow (`Docker Release (Legacy Fallback)`) per `workflow_dispatch` zur Verfügung:

1. GitHub → Actions → "Docker Release (Legacy Fallback)"
2. "Run workflow" → Branch `main`
3. Optionale Versions-Überschreibung

Dieser Workflow sollte nur verwendet werden, wenn Release Please nicht funktioniert oder ein sofortiger Release nötig ist.

## Fehlerbehebung

### Release PR wird nicht erstellt

- Prüfen, ob Commits die richtigen Präfixe (`feat:`, `fix:` usw.) verwenden
- Prüfen, ob Commits auf `main` (nicht Feature-Branch) gepusht wurden
- Workflow-Run auf GitHub prüfen: Actions → Release Please

### Docker Image wird nicht gebaut

- Prüfen, ob der Release PR gemergt wurde
- Prüfen, ob `release_created` im Workflow auf `true` gesetzt ist
- Workflow-Logs prüfen: Actions → Release Please → docker-Job

### VERSION-Datei wird nicht aktualisiert

- Prüfen, ob `extra-files: ["VERSION"]` in der Konfiguration gesetzt ist
- `.release-please-manifest.json` prüfen auf korrekte Version
