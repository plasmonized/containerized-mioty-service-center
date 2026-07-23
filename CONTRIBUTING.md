# Contributing — BSSCI Service Center

## Quick Start

```bash
# Clone & setup
git clone git@github.com:plasmonized/containerized-mioty-service-center.git
cd containerized-mioty-service-center
cp .env.example .env

# Install all dependencies (incl. dev)
uv sync --all-groups --locked

# Run tests
uv run pytest

# Run linter + formatter + type checker
uv run ruff check .
uv run ruff format --check .
uv run mypy . --ignore-missing-imports
```

---

## Development Workflow

### 1. Branch Structure

| Branch | Zweck |
|--------|-------|
| `main` | Stabiler Stand — hier werden PRs gemerged |
| `feature/*` | Neue Features — von `main` abzweigen |

Arbeite immer in einem Feature-Branch und erstelle einen PR gegen `main`.

### 2. Commit Messages

```
<type>: <kurze Beschreibung>

<optional: ausführliche Erklärung, warum>
```

Typen: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, `ci:`

### 3. Testen vor dem Pushen

```bash
# Unit-Tests + Coverage
uv run pytest --cov=. --cov-report=term-missing -m "not integration" -v

# Alle Tests (inkl. Integration — braucht laufende Services)
uv run pytest
```

Neuer Code muss von Tests begleitet werden. Siehe **Testing Standards**.

---

## Python Clean Code Standards

Dieses Projekt verwendet **Python 3.12+** und legt Wert auf sauberen,
typsicheren, testbaren Code. Die vollständigen Clean-Code-Richtlinien
sind als Skill hinterlegt (siehe unten).

### Kernregeln

| Regel | Erklärung |
|-------|-----------|
| **Type Annotations** | Jede Funktion/Jede Methode hat vollständige Typannotationen |
| **snake_case** | Funktionen, Methoden, Variablen — keine camelCase (Ausnahme: EUI aus dem Protokoll) |
| **Single Responsibility** | Eine Funktion = eine Aufgabe |
| **Keine `print()`** | Immer `logger.info() / warning() / exception()` |
| **Spezifische Exceptions** | Kein `except: pass` — immer konkrete Exception-Typen |
| **Async: TaskGroup** | Neuen asynchronen Code mit `asyncio.TaskGroup` statt `gather()` |
| **Logging: %-Formatting** | `logger.info("Queue %s: put #%d", name, count)` — keine F-Strings |
| **@dataclass** | Datencontainer als `@dataclass` statt roher dicts |
| **Composition over Inheritance** | Keine tiefen Klassenhierarchien — Dependencies injizieren |

### Bekannte Anti-Patterns (schrittweise abzubauen)

1. **Monkey-Patching** — `QueueLogger` ersetzt `queue.put/get` → Wrapper-Pattern bevorzugen
2. **Globale Instanz** — `tls_server_instance` in `main.py` → per Dependency Injection
3. **`print()` in `protocol.py`** → durch `logger.exception()` ersetzen
4. **Mutable Default Arguments** — `def f(x=[])` vermeiden

---

## Testing Standards

### Framework

- **pytest 8** mit `pytest-asyncio` (asyncio_mode = auto)
- **pytest-mock** für Mocking (Fixture `mocker`)
- **pytest-cov** für Coverage
- Test-Dateien in `tests/` spiegeln die Source-Struktur: `tests/test_<modul>.py`

### AAA-Pattern

Jeder Test folgt **Arrange → Act → Assert** mit Leerzeilen:

```python
def test_build_ping_response_has_correct_command() -> None:
    # Arrange
    op_id = 1

    # Act
    result = build_ping_response(op_id)

    # Assert
    assert result == {"command": "pingRsp", "opId": 1}
```

### Async Tests

```python
async def test_queue_logger_counts_puts(
    mqtt_out_queue: asyncio.Queue, mock_logger
) -> None:
    ql = QueueLogger("test", mqtt_out_queue)
    await mqtt_out_queue.put("a")
    await mqtt_out_queue.put("b")
    assert ql.stats["put_count"] == 2
```

### Coverage-Ziele

| Modul | Ziel |
|-------|------|
| `messages.py` | 100 % |
| `protocol.py` | 100 % |
| Service-Module | ≥ 75 % |
| Gesamt | ≥ 80 % |

### Test-Kommandos

```bash
pytest                              # alle Tests
pytest -m "not integration" -n auto # nur Unit-Tests, parallel
pytest --cov=. --cov-fail-under=75  # Coverage-Check
```

---

## AI-Assisted Development (Skills)

Dieses Repository enthält **OpenCode-Skills**, die als Richtlinien für
AI-gestützte Code-Generierung und -Review dienen.

| Skill laden mit | Beschreibung |
|----------------|--------------|
| `@python-clean-code` | Modern Python 3.12+ Clean Code Paradigmen |
| `@python-testing` | pytest-asyncio Testing Best Practices |
| `@simplify` | Code-Vereinfachung bei gleichbleibendem Verhalten |
| `@recall` | Kontext aus früheren Sessions abrufen |
| `@remember` | Entscheidungen/Insights speichern |

Die Skills liegen in `.agents/skills/` und werden automatisch geladen,
wenn sie im Prompt referenziert werden.

---

## CI/CD

Die Pipeline in `.github/workflows/main.yml` läuft bei jedem Push/PR:

1. **Ruff Lint** — Code-Style + Qualität
2. **Ruff Format Check** — Einheitliche Formatierung
3. **Mypy** — Typ-Checks
4. **pytest + Coverage** — Unit-Tests

Integration-Tests (Marker `integration`) werden nur manuell ausgeführt.
Der `docker-pr` Job baut und testet PR-Images.

---

## Dependencies

```bash
# Dev-Dependencies installieren
uv sync --all-groups

# Neue Dependency hinzufügen
uv add <package>

# Dev-Dependency
uv add --group dev <package>

# uv.lock aktualisieren
uv lock
```

Verwende `uv` (nicht pip) für das Dependency-Management.
Die `uv.lock` wird eingecheckt — bei Änderungen an Abhängigkeiten immer
`uv lock` ausführen.

---

## Fragen?

- Issues im GitHub-Repo öffnen
- Skills @recall nutzen, um Kontext aus früheren Sessions zu erhalten
- `AGENTS.md` und `README.md` enthalten weitere Projektdetails
