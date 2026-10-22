"""A3 visibility: lines flagged print_on_pdf = false stay in totals and internal screens only.

Customer outputs (PDFs, emailed PDFs, conduces, public pages) call customer_items().
Totals are always computed from the FULL list first. Hide only: nothing is redistributed,
so printed lines may not add up to the printed totals (stated decision).
"""
import os
from typing import Iterable, List


def print_controls_enabled() -> bool:
    """May a line be set to hidden? Off by default. Filtering itself is always on, so turning
    this off never exposes a line that is already hidden."""
    return os.environ.get("PRINT_CONTROLS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def is_printable(item) -> bool:
    """Missing flag (pre-A3 rows, legacy callers) means printable. Only a literal False hides."""
    return item.get("print_on_pdf", True) is not False


def customer_items(items: Iterable) -> List:
    return [i for i in items if is_printable(i)]


def has_hidden(items: Iterable) -> bool:
    return any(not is_printable(i) for i in items)
