"""B3: area and volume derived from the other dimensions (approved 2026-10-22).

One place for the rule. Values are used as entered: this module does not convert units, so the product's
dimensions must share one unit (the product's unit_of_measure).

  area   = length x width                      when both exist
  volume = length x width x height             when all three exist
           length x width x thickness          when there is no height but there is a thickness (plate / sheet)

A value typed by a person is flagged manual (area_manual / volume_manual) and is never recalculated.
"""
from decimal import Decimal
from typing import Optional

AREA_PLACES = Decimal("0.0001")


def _d(v) -> Optional[Decimal]:
    return None if v is None else Decimal(str(v))


def derive_area(length, width) -> Optional[Decimal]:
    l, w = _d(length), _d(width)
    return None if l is None or w is None else (l * w).quantize(AREA_PLACES)


def derive_volume(length, width, height, thickness) -> Optional[Decimal]:
    l, w = _d(length), _d(width)
    depth = _d(height) if height is not None else _d(thickness)
    return None if l is None or w is None or depth is None else (l * w * depth).quantize(AREA_PLACES)
