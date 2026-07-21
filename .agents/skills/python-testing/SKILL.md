---
name: python-testing
description: Modern Python testing best practices using pytest, pytest-asyncio, and pytest-mock for this async-first Python 3.12+ codebase. Use when writing, reviewing, or planning tests.
argument-hint: "[module or feature to test]"
user-invocable: true
---

# Python Testing — BSSCI Service Center

## Overview

This skill defines testing standards for this Python 3.12+ asyncio project.
Tests are **first-class code** — they must be readable, maintainable, and
provide fast, reliable feedback.

**Principle:** Test behavior, not implementation. A good test breaks only when
requirements change, not when you refactor.

---

## 1. Test Framework & Tooling

| Tool | Purpose | Config |
|------|---------|--------|
| **pytest** | Test runner | `pyproject.toml` under `[tool.pytest.ini_options]` |
| **pytest-asyncio** | Async test support | `asyncio_mode = "auto"` |
| **pytest-mock** | Mocking (wrapper over `unittest.mock`) | Built-in fixture `mocker` |
| **pytest-cov** | Coverage reporting | `addopts = "--cov=."` |
| **pytest-xdist** | Parallel test execution | `-n auto` |

### 1.1 Required dev dependencies (pyproject.toml)

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.4.2",
    "pytest-asyncio>=0.25.0",
    "pytest-mock>=3.14.0",
    "pytest-cov>=6.0.0",
    "pytest-xdist>=3.6.0",
]
```

### 1.2 Recommended pytest config

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = ["test_*.py"]
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "integration: marks tests that need external services (MQTT, TLS)",
    "unit: marks pure unit tests (no external deps)",
]
```

### 1.3 Running tests

```bash
# All tests
uv run pytest

# With coverage
uv run pytest --cov=. --cov-report=term-missing

# Fast — only unit tests, parallel
uv run pytest -m "unit" -n auto

# Single file
uv run pytest tests/test_messages.py -v
```

---

## 2. Test File & Directory Structure

```
tests/
├── __init__.py              # empty or test utilities
├── conftest.py              # shared fixtures (pytest picks up automatically)
├── test_messages.py         # tests for messages.py
├── test_protocol.py         # tests for protocol.py
├── test_tls_server.py       # tests for TLSServer.py
├── test_mqtt_interface.py   # tests for mqtt_interface.py
├── test_queue_logger.py     # tests for queue_logger.py
├── test_ha_log_bridge.py    # tests for ha_log_bridge.py
└── integration/
    ├── __init__.py
    └── test_full_pipeline.py
```

### 2.1 File Naming

- Test file: `test_<module_name>.py`
- Test function: `test_<function_name>__<scenario>`
- Test class: `Test<ClassName>`

### 2.2 Mirror the Source Tree

For `messages.py` → `tests/test_messages.py`  
For `protocol.py` → `tests/test_protocol.py`  
For `web_ui.py` → `tests/test_web_ui.py`

---

## 3. Writing Tests — The AAA Pattern

Every test follows **Arrange → Act → Assert** with blank-line separation:

```python
from messages import build_attach_request


SENSOR = {"eui": "A1B2C3D4E5F6", "bidi": False, "nwKey": "00" * 8,
          "shortAddr": "0001"}


class TestBuildAttachRequest:
    """Tests for messages.build_attach_request."""

    def test_returns_correct_structure(self) -> None:
        """It should return a dict with the expected command and keys."""
        # Arrange
        op_id = 1

        # Act
        result = build_attach_request(SENSOR, op_id)

        # Assert
        assert result["command"] == "attPrp"
        assert result["opId"] == op_id
        assert "epEui" in result

    def test_handles_zero_op_id(self) -> None:
        """It should accept op_id=0 without error."""
        assert build_attach_request(SENSOR, 0)["opId"] == 0
```

---

## 4. Async Testing

### 4.1 With `asyncio_mode = "auto"`, just write `async def`

```python
import asyncio
import pytest
from queue_logger import QueueLogger


@pytest.fixture
def queue() -> asyncio.Queue:
    return asyncio.Queue()


class TestQueueLogger:
    """Tests for QueueLogger using async tests."""

    async def test_logs_put_and_get(
        self, queue: asyncio.Queue, mocker
    ) -> None:
        """It should track put/get counts correctly."""
        # Arrange
        logger_mock = mocker.patch("queue_logger.logger")
        ql = QueueLogger("test", queue)

        # Act
        await queue.put({"key": "value"})
        result = await queue.get()

        # Assert
        assert result == {"key": "value"}
        assert ql.stats["put_count"] == 1
        assert ql.stats["get_count"] == 1
```

### 4.2 Testing with `asyncio.TaskGroup`

```python
async def test_concurrent_services_start_and_stop(
    mocker, event_loop
) -> None:
    """Both services should start and stop cleanly."""
    # Arrange
    tls_mock = mocker.AsyncMock()
    mqtt_mock = mocker.AsyncMock()

    # Act
    async with asyncio.TaskGroup() as tg:
        t1 = tg.create_task(tls_mock.start_server())
        t2 = tg.create_task(mqtt_mock.start())

    # Assert — no exception raised means success
    tls_mock.start_server.assert_awaited_once()
    mqtt_mock.start.assert_awaited_once()
```

---

## 5. Fixtures — The Right Way

### 5.1 Keep Fixtures in `conftest.py` Only When Shared

```python
# tests/conftest.py
import json
import asyncio
import pytest


@pytest.fixture
def sensor_config() -> dict:
    """A minimal but valid sensor config."""
    return {
        "eui": "A1B2C3D4E5F6",
        "bidi": False,
        "nwKey": "0011223344556677",
        "shortAddr": "0001",
    }


@pytest.fixture
def mqtt_queue() -> asyncio.Queue:
    """A fresh asyncio.Queue for each test."""
    return asyncio.Queue()


@pytest.fixture
def mock_logger(mocker):
    """Pre-configured logger mock to suppress log noise in tests."""
    return mocker.patch("queue_logger.logger")
```

### 5.2 Locally-Defined Fixtures in Test Files

If a fixture is only used by one test file, define it in that file — not in `conftest.py`.

### 5.3 Fixture Scope

| Scope | When to Use |
|-------|-------------|
| `function` (default) | Fresh state per test — most things |
| `class` | Shared across tests in one class |
| `module` | Expensive setup (config parsing, cert loading) |
| `session` | Very expensive (DB connection, test server) |

```python
@pytest.fixture(scope="session")
def tls_certificates() -> tuple[str, str, str]:
    """Load TLS certificates once per test session."""
    return (CERT_FILE, KEY_FILE, CA_FILE)
```

### 5.4 Fixtures Should Not Do Too Much

One fixture = one responsibility. Compose them:

```python
@pytest.fixture
def tls_config(tls_certificates) -> dict:
    cert, key, ca = tls_certificates
    return {"cert": cert, "key": key, "ca": ca}


@pytest.fixture
def tls_server(tls_config, mqtt_queue) -> "TLSServer":
    from TLSServer import TLSServer
    return TLSServer(
        sensor_config_file="config/endpoints.json",
        mqtt_out_queue=mqtt_queue,
        mqtt_in_queue=mqtt_queue,
    )
```

---

## 6. Mocking Strategy

### 6.1 Use `mocker` Fixture (from pytest-mock)

```python
# ✅ Good — clean, scoped
def test_send_message(mocker) -> None:
    mock_client = mocker.patch(
        "mqtt_interface.MQTTClient._publish",
        new_callable=mocker.AsyncMock,
    )
    ...

# ❌ Avoid — leaves global state dirty
from unittest.mock import patch
with patch("mqtt_interface.MQTTClient._publish") as mock:
    ...
```

### 6.2 Mock at the Source, Not the Destination

```python
# ✅ Good — mock where it's imported (TLSServer imports protocol.decode_messages)
mocker.patch("TLSServer.decode_messages", return_value=[{"command": "conRsp"}])

# ❌ Bad — mock at the definition site
mocker.patch("protocol.decode_messages", ...)
```

### 6.3 Prefer `AsyncMock` for Async Functions

```python
mocker.patch.object(
    tls_server,
    "_handle_client",
    new_callable=mocker.AsyncMock(return_value=None),
)
```

### 6.4 Use `spy` to Verify Side Effects, Not Assert Calls

```python
spy = mocker.spy(logger, "info")
# ... act ...
spy.assert_called_once_with("Queue %s: put #%d", "test", 1)
```

---

## 7. What to Test — Prioritization

### 7.1 Tier 1 — Pure Logic (Highest Priority)

These are cheap, fast, and catch real bugs:

| Module | What to Test | Example |
|--------|-------------|---------|
| `messages.py` | Each `build_*` function returns correct dict | Key presence, op_id handling, EUI encoding |
| `protocol.py` | Round-trip encode/decode | Bytes → dict → bytes yields original |
| `bssci_config.py` | Config parsing with env overrides | Default values, type casting |

### 7.2 Tier 2 — Async Service Logic

| Module | What to Test |
|--------|-------------|
| `queue_logger.py` | Stats tracking, daily reset, put/get counting |
| `ha_log_bridge.py` | Log entry formatting, publish intervals |
| `web_ui.py` | Route handlers, template rendering |

### 7.3 Tier 3 — Integration / System Tests

| Scope | What to Test |
|-------|-------------|
| Full pipeline | TLS → decode → MQTT → encode → TLS |
| MQTT client | Connection, reconnection, message flow |
| TLS server | Client connect, certificate validation |

---

## 8. Test Quality Guidelines

### 8.1 Each Test Asserts One Logical Thing

```python
# ✅ Good — focused
def test_build_ping_response_has_correct_command() -> None:
    result = build_ping_response(1)
    assert result["command"] == "pingRsp"

def test_build_ping_response_forwards_op_id() -> None:
    result = build_ping_response(42)
    assert result["opId"] == 42
```

One test method = one scenario = one reason to fail.

### 8.2 Descriptive Test Names (Sentence Form)

```python
def test_build_attach_request_encodes_eui_as_big_endian() -> None:
def test_decode_messages_handles_partial_frame_gracefully() -> None:
def test_queue_logger_resets_daily_counter_on_date_change() -> None:
```

### 8.3 Test Edge Cases Explicitly

```python
def test_decode_messages_with_empty_bytes_returns_empty_list() -> None:
    assert decode_messages(b"") == []

def test_build_vm_activate_request_with_negative_op_id() -> None:
    result = build_vm_activate_request(-1)
    assert result["opId"] == -1
```

Edge cases to always cover:
- Empty / zero input
- Boundary values (min/max ints, empty strings)
- Invalid types (if applicable)
- `None` / missing keys

### 8.4 Don't Test Implementation Details

```python
# ✅ Good — test behavior
def test_queue_logger_counts_puts() -> None:
    await queue.put("x")
    await queue.put("y")
    assert ql.stats["put_count"] == 2

# ❌ Bad — test implementation (breaks on refactor)
def test_queue_logger_calls_original_put() -> None:
    spy = mocker.spy(queue, "_logged_put")
    await queue.put("x")
    spy.assert_called_once()
```

### 8.5 No `pytest.skip()` in Production Test Runs

If a test needs an external service (MQTT broker, real TLS), mark it:

```python
@pytest.mark.integration
async def test_mqtt_connects_to_real_broker() -> None:
    ...
```

Run these only when explicitly requested: `pytest -m integration`

---

## 9. Coverage

### 9.1 Target

- **Overall:** ≥ 80% line coverage
- **Core modules** (`messages.py`, `protocol.py`): 100%
- **Service modules** (`TLSServer.py`, `mqtt_interface.py`): ≥ 75%
- **UI modules** (`web_ui.py`, `web_main.py`): ≥ 60%

### 9.2 Coverage Configuration

```toml
[tool.coverage.run]
source = ["."]
omit = [
    "tests/*",
    "attached_assets/*",
    "**/__pycache__/*",
    ".venv/*",
]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if __name__ == .__main__.:",
    "raise NotImplementedError",
    "if TYPE_CHECKING:",
]
```

### 9.3 Run Coverage and Fail Below Threshold

```bash
uv run pytest --cov=. --cov-fail-under=75
```

---

## 10. Property-Based Testing (Optional but Powerful)

For modules with complex I/O (like `protocol.py`), use **Hypothesis**:

```python
# tests/test_protocol.py
from hypothesis import given, strategies as st
from protocol import encode_message, decode_message


class TestProtocolRoundTrip:
    """Property-based: encode → decode is identity."""

    @given(st.dictionaries(
        keys=st.text(max_size=10),
        values=st.integers(),
        max_size=5,
    ))
    def test_round_trip_dict(self, data: dict) -> None:
        """encode(decode(x)) == x for any valid dict."""
        encoded = encode_message(data)
        decoded = decode_message(encoded)
        assert decoded == data
```

---

## 11. CI Integration

The CI pipeline in `.github/workflows/main.yml` should run:

```yaml
- name: Run tests with coverage
  run: |
    uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=75 \
      -m "not integration" -n auto -v
```

Separate integration tests into a manual / scheduled workflow to keep the
push/PR fast.

---

## 12. Test-Driven Development (TDD) Workflow

When adding a new feature:

1. **Write the test first** — specify the behavior you want
2. **Run it** — it should fail (red)
3. **Write minimal code** to make it pass (green)
4. **Refactor** — clean up both code and test (refactor)

```python
# Step 1: Write test
def test_build_status_request_contains_op_id() -> None:
    """status request should include the operation ID."""
    result = build_status_request(99)
    assert result == {"command": "status", "opId": 99}

# Step 3: Minimal implementation
def build_status_request(op_id: int) -> dict[str, object]:
    return {"command": "status", "opId": op_id}
```

---

## 13. Test Review Checklist

- [ ] Tests follow AAA pattern (Arrange-Act-Assert with blank lines)
- [ ] Test function names describe the scenario in English
- [ ] Each test asserts one logical behavior
- [ ] Async tests use `async def` (not `pytest.mark.asyncio` with `asyncio_mode=auto`)
- [ ] Fixtures are appropriately scoped and not overused
- [ ] Mocks patch at the import site (where it's used, not where it's defined)
- [ ] No `print()` in tests — use `caplog` fixture to verify log output
- [ ] No hardcoded sleeps (`asyncio.sleep()`) — use `mocker.async` with `await` coordination
- [ ] Edge cases (empty, None, boundary) are covered
- [ ] No test depends on another test (isolation)
- [ ] Tests are fast (< 100ms per unit test)
