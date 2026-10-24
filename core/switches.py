"""One parser for on/off switches read from the environment (audit H7, 2026-10-24).

Accepted as on: 1, true, yes, on (any case, surrounding spaces ignored). Anything else is off.
"""
import os

_ON = ("1", "true", "yes", "on")


def switch_on(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in _ON
