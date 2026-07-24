"""Config access with .env fallback for stale mounted bssci_config.py.

Some Docker deployments bind-mount an outdated bssci_config.py that lacks
newer settings (e.g. SCACI_ENABLED).  getattr(bssci_config, ...) then always
returns the hardcoded default even though the user set the value in .env.
This helper falls back to the process environment (populated from .env via
load_dotenv) whenever the attribute is missing from the module.
"""

import logging
import os
from typing import Any

from dotenv import load_dotenv

import bssci_config

# Defensive: ensure .env is loaded even if a very old mounted bssci_config.py
# does not call load_dotenv itself.
load_dotenv()

logger = logging.getLogger(__name__)

_warned: set[str] = set()


def get_config(name: str, default: Any) -> Any:
    """Return bssci_config.<name>, falling back to the env var, then default."""
    if hasattr(bssci_config, name):
        return getattr(bssci_config, name)

    raw = os.getenv(name)
    if name not in _warned:
        _warned.add(name)
        logger.warning(
            "Config attribute %s missing from bssci_config.py (outdated mounted file?); "
            "using %s from environment/.env",
            name,
            "value" if raw is not None else "built-in default",
        )
    if raw is None:
        return default
    if isinstance(default, bool):
        return raw.strip().lower() == "true"
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            return default
    return raw
