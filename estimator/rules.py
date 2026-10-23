"""Quantity rules, one per workbook cell. Same operation order as Excel for float parity.

Context keys are workbook cell names: E9 ancho, E11 largo, E13 altura laterales,
E15 altura techado lateral, E17 distancia ejes, E38 columnas frontales,
F41 F45 F50 F54 profile lb/ft. Nothing is rounded here (D-5 open).
Defects are carried and flagged, not corrected (D-7, D-8).
"""
from typing import Callable, Dict, List, Tuple

from estimator.constants import Constants

Rule = Tuple[str, Callable[[Dict[str, float], Constants], float]]


def _e19(c, k):  # roof sheet area
    return (c["E9"] * c["E11"]) * k.allowance * k.ft_factor * k.allowance


def _e20(c, k):  # wall sheet area
    return ((c["E9"] * 2 + c["E11"] * 2) * c["E15"] * k.ft_factor) + (
        c["E9"] * k.end_width_multiplier * k.ft_factor
    )


def _e21(c, k):  # roof purlin length
    return (c["E9"] * k.allowance + k.run_extra) * c["E11"] * k.ft_factor + (
        c["E9"] * k.end_width_multiplier * k.ft_factor
    )


def _e22(c, k):  # wall purlin length
    return (c["E9"] * 2 + c["E11"] * 2) * (c["E15"] + k.wall_extra_height) * k.ft_factor


def _e23(c, k):  # unused in any priced line (D19)
    return (c["E19"] + c["E20"]) * k.screws_per_unit


def _e24(c, k):
    return (c["E11"] / c["E17"]) * (c["E9"] * k.allowance + k.run_extra)


def _e25(c, k):
    return (((c["E21"] + c["E22"]) / k.ft_factor) / c["E17"]) * k.purlin_screw_factor


def _e27(c, k):
    return (c["E11"] * 2) * k.allowance * k.ft_factor


def _e28(c, k):
    return c["E27"] / 2


def _e29(c, k):
    return ((c["E9"] * 2) + (c["E15"] * 4)) * k.allowance * k.ft_factor


def _e30(c, k):
    return (c["E11"] / c["E17"] + 1) * 2 + k.downspout_adjust


def _e31(c, k):
    return c["E30"]


def _e42(c, k):  # columns, lb
    return (c["E11"] / c["E17"] + 1) * 2 * c["E13"] * k.ft_factor * c["F41"]


def _e46(c, k):
    return c["E38"]


def _e47(c, k):  # front columns, lb
    return c["E13"] * c["E46"] * k.ft_factor * c["F45"]


def _e51(c, k):  # trusses, lb
    return ((c["E11"] / c["E17"] + 1) * k.allowance * c["E9"]) * k.ft_factor * c["F50"]


def _e55(c, k):  # bracing, lb
    return (c["E9"] * 2 + c["E11"] * 2) * k.ft_factor * c["F54"]


def _e58(c, k):  # connections, lb
    return (c["E55"] + c["E51"] + c["E47"] + c["E42"]) * k.connection_ratio


def _e60(c, k):  # steel total as the workbook computes it: omits E55 (D4)
    return c["E58"] + c["E51"] + c["E47"] + c["E42"]


def _e62(c, k):
    return (c["E11"] / c["E17"] + 1) * 2


def _e64(c, k):
    return c["E62"] * k.bolt_screws_a * k.bolt_screws_b


def _c93(c, k):
    return c["C88"] * k.screws_per_unit


def _c101(c, k):
    return (((c["E11"] / c["E17"]) * 2) * (c["E15"] + k.wall_extra_height)) * 2


def _c102(c, k):
    return c["C101"] * k.screws_per_unit


def _c103(c, k):
    return c["C99"] * k.screws_per_unit


# Evaluation order matters: each rule only reads earlier ones.
# C88 and C99 are aliases of E19 and E20 (line quantity cells), set in core before C93/C103.
RULES: List[Rule] = [
    ("E19", _e19), ("E20", _e20), ("E21", _e21), ("E22", _e22), ("E23", _e23),
    ("E24", _e24), ("E25", _e25), ("E27", _e27), ("E28", _e28), ("E29", _e29),
    ("E30", _e30), ("E31", _e31), ("E42", _e42), ("E46", _e46), ("E47", _e47),
    ("E51", _e51), ("E55", _e55), ("E58", _e58), ("E60", _e60), ("E62", _e62),
    ("E64", _e64),
]

# Rules that read line-quantity aliases; evaluated after the aliases are set.
LINE_RULES: List[Rule] = [
    ("C93", _c93), ("C101", _c101), ("C102", _c102), ("C103", _c103),
]
