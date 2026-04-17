---
outline: [2, 3]
---

# Development Guide

## Code Quality Tools

This project uses automated code quality checks. All checks run automatically in GitHub Actions on every push and pull request.

### Available Tools

| Tool | Purpose | Config Location |
|------|---------|-----------------|
| **Ruff** | Linting & Code Formatting | `pyproject.toml` |
| **Mypy** | Type Checking | `pyproject.toml` |
| **pytest** | Unit Tests | `pyproject.toml` |
| **pytest-cov** | Code Coverage | `pyproject.toml` |

### Running Checks Locally

Install the required tools:

```bash
pip install ruff pytest pytest-cov mypy
```

#### Ruff (Linting & Formatting)

```bash
# Check for issues
ruff check .

# Auto-fix issues
ruff check . --fix

# Check formatting
ruff format --check .

# Auto-format code
ruff format .
```

#### Mypy (Type Checking)

```bash
mypy . --ignore-missing-imports --exclude attached_assets
```

#### Tests & Coverage

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=. --cov-report=term-missing --ignore=attached_assets
```

### Running All Checks

To run all checks locally before pushing:

```bash
# Linting
ruff check . && ruff format --check .

# Type checking
mypy . --ignore-missing-imports --exclude attached_assets

# Tests with coverage
pytest --cov=. --cov-report=term-missing --ignore=attached_assets
```

### CI Pipeline

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs:
1. **Lint** - Ruff checks and formatting
2. **Type Check** - Mypy type verification
3. **Test** - pytest with coverage
4. **Build** - Package build verification

All branches are checked on push, main and release branches on pull requests.