---
name: python-clean-code
description: Modern Python Clean Code paradigms and project conventions for this Python 3.12+ asyncio codebase. Use when writing, reviewing, or refactoring Python code to ensure clarity, maintainability, and idiomatic modern Python.
argument-hint: "[file or module to review]"
user-invocable: true
---

# Python Clean Code — BSSCI Service Center

## Overview

This skill encodes modern Python clean code principles for this Python 3.12+ asyncio codebase.
Every rule exists to serve one goal: **code that is easy to understand, test, and change without surprises.**

Apply these principles when writing new code, reviewing PRs, or refactoring existing modules.

---

## 1. Modern Python (3.12+) Idioms

### 1.1 Type Annotations Everywhere

All functions and methods **must** have full type annotations — parameters and return types.

```python
# ✅ Good
def build_connection_response(op_id: int, snscuuid_arr: list[int]) -> dict[str, object]:
    ...

# ❌ Bad
def build_connection_response(opID, snscuuid_arr):
    ...
```

Use `list[int]` over `typing.List[int]`, `dict[str, Any]` over `typing.Dict[str, Any]` (native generics, Python 3.9+).

### 1.2 Use `Self` Return Type for Class Methods

```python
from typing import Self

class QueueLogger:
    @classmethod
    def create(cls, name: str, queue: asyncio.Queue) -> Self:
        ...
```

### 1.3 Prefer `|` Union Syntax Over `Optional`

```python
# ✅ Good
def get_item(key: str) -> dict[str, Any] | None:
    ...

# ❌ Avoid (both are acceptable, but | is more modern)
def get_item(key: str) -> Optional[dict[str, Any]]:
    ...
```

### 1.4 Use `TypeVar` and `Generic` for Reusable Patterns

When a class or function works across multiple types, use generics instead of `Any`.

### 1.5 Pattern Matching for Complex Conditionals

Use `match`/`case` (Python 3.10+ / 3.12+) instead of long `if`/`elif` chains when
dispatching on command types or message structures:

```python
# ✅ Good
match command:
    case "conRsp" | "attPrp":
        return handle_connection(message)
    case "vm.dlData" | "vm.ulData":
        return handle_vm_data(message)
    case _:
        logger.warning("Unknown command: %s", command)
```

---

## 2. Naming Conventions

### 2.1 snake_case for Everything

- Functions, methods, variables: `build_attach_request`, `mqtt_out_queue`, `op_id`
- Classes: `PascalCase` → `TlsServer`, `MqttClient`, `QueueLogger`
- Constants: `UPPER_SNAKE_CASE` → `BASE_TOPIC`, `LISTEN_HOST`
- Private helpers: prefix with `_` → `_check_daily_reset`, `_logged_put`

### 2.2 No Hungarian Notation or Abbreviations

```python
# ✅ Good
op_id, sensor_config, timeout_seconds

# ❌ Bad
opID, sensorCfg, tmo_sec
```

### 2.3 Name Reveals Intent

A name should answer "what does this do?" without reading the body:

```python
# ✅ Good
def build_vm_activate_request(op_id: int, mac_type: int = 0) -> dict[str, object]: ...

# ❌ Bad
def vm_act(op: int, mt: int = 0) -> dict: ...
```

---

## 3. Function Design — Single Responsibility

### 3.1 One Function, One Job

Each function should do exactly one thing at one level of abstraction.

```python
# ✅ Good
def decode_messages(data: bytes) -> list[dict[str, Any]]: ...
def build_connection_response(op_id: int, ...) -> dict[str, object]: ...
```

Functions that build message dicts are pure — no side effects, no I/O.

### 3.2 Keep Functions Small

A function should fit on one screen (~40 lines). If it's longer, extract helpers.
The exception is `__init__` with many configuration fields.

### 3.3 Favor Keyword Arguments for Booleans and Complex Calls

```python
# ✅ Good
encode_message(data, use_compression=True)

# ❌ Bad
encode_message(data, True)
```

### 3.4 Avoid Boolean Flag Parameters (Flag Argument Anti-Pattern)

A function that does different things based on a boolean flag should be two functions:

```python
# ✅ Good
def build_vm_activate_request(...): ...
def build_vm_deactivate_request(...): ...

# ❌ Bad
def build_vm_request(op_id, mac_type, activate=True): ...
```

---

## 4. Class Design

### 4.1 Favour Composition Over Inheritance

Use composition and dependency injection, not deep class hierarchies.
Inject dependencies via `__init__` parameters:

```python
class TlsServer:
    def __init__(
        self,
        sensor_config_file: str,
        mqtt_out_queue: asyncio.Queue[dict[str, str]],
        mqtt_in_queue: asyncio.Queue[dict[str, str]],
    ) -> None:
        ...
```

### 4.2 Protocol Classes for Interfaces

Use `typing.Protocol` for duck-typed interfaces instead of abstract base classes:

```python
from typing import Protocol, Any

class MessageHandler(Protocol):
    async def handle(self, message: dict[str, Any]) -> None: ...
```

### 4.3 Use `dataclass` or `NamedTuple` for Data Containers

```python
from dataclasses import dataclass, field

@dataclass
class QueueStats:
    queue_name: str
    put_count: int = 0
    get_count: int = 0
    current_size: int = 0
    max_size_seen: int = 0
    last_put_time: float | None = None
    last_get_time: float | None = None
```

This replaces manual dict-building with typed, self-documenting structures.

### 4.4 Avoid Monkey-Patching in Production Code

The `QueueLogger` monkey-patches `queue.put` / `queue.get`. Prefer wrapping
with a `QueueWrapper` or using a decorated/adapter pattern instead:

```python
@dataclass
class MonitoredQueue:
    """Wraps an asyncio.Queue with logging without monkey-patching."""
    _queue: asyncio.Queue
    _logger: QueueLogger

    async def put(self, item: Any) -> None:
        self._logger.will_put(item)
        await self._queue.put(item)
        self._logger.did_put(item)

    async def get(self) -> Any:
        self._logger.will_get()
        item = await self._queue.get()
        self._logger.did_get(item)
        return item
```

---

## 5. Async/Await Best Practices

### 5.1 Never `asyncio.run()` Inside an Async Function

Call `asyncio.run(main())` exactly once at the entry point.

### 5.2 Prefer `asyncio.gather()` Over Sequential Awaiting

```python
# ✅ Good
await asyncio.gather(
    tls_server.start_server(),
    mqtt_client.start(),
    return_exceptions=True,
)

# ❌ Bad — sequential when concurrent is safe
await tls_server.start_server()
await mqtt_client.start()
```

### 5.3 Use `asyncio.TaskGroup` (3.12+) for Structured Concurrency

```python
async with asyncio.TaskGroup() as tg:
    tg.create_task(tls_server.start_server())
    tg.create_task(mqtt_client.start())
    tg.create_task(queue_stats_reporter())
```

TaskGroups handle cancellation and exception propagation correctly — prefer them
over raw `asyncio.gather()` for new code.

### 5.4 Use `asyncio.timeout()` for Timeout Management

```python
try:
    async with asyncio.timeout(10):
        result = await some_operation()
except TimeoutError:
        logger.warning("Operation timed out")
```

### 5.5 Name Your `asyncio.create_task()` Instances

Unnamed tasks are invisible in debugging. Always assign to a variable:

```python
stats_task = asyncio.create_task(queue_stats_reporter(), name="queue-stats")
```

---

## 6. Error Handling

### 6.1 Never `except: pass`

Every `except` block must handle, log, or re-raise. Bare `pass` hides failures.

### 6.2 Use Specific Exception Types

```python
# ✅ Good
except ConnectionError:
    logger.exception("MQTT broker unreachable")
    raise

# ❌ Bad
except Exception:
    pass
```

### 6.3 Prefer `raise` Over Returning Error Sentinels

Returning `{}` or `None` to signal errors is fragile. Raise domain-specific
exceptions:

```python
class ProtocolError(Exception):
    """Raised when message decoding fails."""

def decode_messages(data: bytes) -> list[dict[str, Any]]:
    if not data:
        raise ProtocolError("Empty data")
    ...
```

For this project's current code style, returning empty results on error is
accepted — but new code should prefer explicit exceptions.

### 6.4 Use `logging.exception()` in Exception Handlers

`logger.exception("...")` automatically includes the traceback.

---

## 7. Module Structure

### 7.1 Standard Layout per File

```
"""Module docstring describing the module's purpose."""

from __future__ import annotations  # for cleaner annotations in 3.12+

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Self

logger = logging.getLogger(__name__)

# ——— Public API ———

# ——— Internal Helpers ———
```

### 7.2 Avoid Star Imports

```python
# ✅ Good
from bssci_config import LISTEN_HOST, LISTEN_PORT

# ❌ Bad
from bssci_config import *
```

### 7.3 Order Imports: stdlib → third-party → local

Separate groups with blank lines. Use `isort` or `ruff` to automate this.

---

## 8. Configuration and Environment

### 8.1 Type-Cast Config at Parse Time

```python
# ✅ Good (current style — correct)
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "16018"))

# ✅ Even better with validation
def _parse_port(value: str | None, default: int = 16018) -> int:
    try:
        return int(value) if value else default
    except ValueError:
        logger.warning("Invalid LISTEN_PORT %r, using default %d", value, default)
        return default
```

### 8.2 Group Related Config into Dataclasses

```python
@dataclass(frozen=True)
class MqttConfig:
    broker: str
    port: int
    username: str
    password: str
    base_topic: str
```

This makes configuration typed, testable, and explicit about its shape.

---

## 9. Logging Best Practices

### 9.1 Use %-Formatting, Not F-Strings

```python
# ✅ Good — lazy evaluation, no cost if log level is disabled
logger.info("Queue %s: put #%d", name, count)

# ❌ Bad — always evaluates, even when level is WARNING
logger.info(f"Queue {name}: put #{count}")
```

### 9.2 Module-Level Logger

```python
logger = logging.getLogger(__name__)
```

Never use `logging.getLogger()` with a string literal — use `__name__`.

### 9.3 Emoji in Logs

This project uses emoji in log output (✅, 📤, 📥, ❌). Keep them consistent
but use them only in INFO-level user-facing log messages, never in
WARNING/ERROR or structured log data.

---

## 10. Refactoring Existing Code

When touching legacy code in this project, apply the **Boy Scout Rule:**
leave the code cleaner than you found it.

- Rename `opID` → `op_id` (camelCase → snake_case) when modifying that line
- Replace `print()` calls with `logger.info()` / `logger.warning()`
- Add type annotations when touching a function
- Replace bare dict returns with `@dataclass` where the shape is stable
- Extract inline comments into well-named helper functions

---

## Specific Guidance for This Repository

### Known Patterns to Follow

- **Config module** (`bssci_config.py`): Centralized env-based config — keep it flat, import constants directly
- **Message builders** (`messages.py`): Pure functions, one per message type — keep them pure, add type annotations
- **Protocol** (`protocol.py`): Binary encoding/decoding — test with known byte patterns
- **Async services**: `TLSServer` and `MqttClient` run as concurrent tasks — always use `return_exceptions=True` or `TaskGroup` to avoid one failure killing the other

### Known Anti-Patterns to Avoid (and Gradually Fix)

1. **Monkey-patching** (`QueueLogger` replaces `queue.put`/`queue.get`) → use wrapper/decorator pattern
2. **`print()` in `protocol.py`** → replace with `logger.warning()` / `logger.exception()`
3. **Global `tls_server_instance`** (`main.py`) → inject via parameter, avoid globals
4. **`# type: ignore` / bare `Any`** → prefer proper type annotations
5. **Bare except clauses** → narrow to specific exception types

---

## Verification Checklist

- [ ] All functions/params have type annotations (native generics)
- [ ] snake_case for all functions, methods, variables
- [ ] No `print()` — use `logger.*()`
- [ ] No bare `except:` — use specific exception types
- [ ] No mutable default arguments
- [ ] Functions are small and single-responsibility
- [ ] Imports follow stdlib → third-party → local ordering
- [ ] Logging uses %-style formatting (`logger.info("... %s", var)`)
- [ ] New async code uses `TaskGroup` or properly handles exceptions
- [ ] Inject dependencies rather than using globals or singletons
