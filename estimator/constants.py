"""Typed constants of the workbook, named without inventing a meaning.

Every value below is typed inside workbook formulas. Their business meaning is NOT confirmed
(questions Q-E2-3 to Q-E2-6, defects D5, D6, D10, D17 to D19, D28). They are stored as data so a
later rule version can change them. Parity first: the defaults equal the workbook.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Constants:
    # 3.28 typed 13 times in 11 formulas. Applied to areas and lengths alike (D5, D28).
    ft_factor: float = 3.28
    # 1.1 typed in E19 (twice), E21, E24, E27, E29, E51 (D6). Waste, overlap or slope: unknown.
    allowance: float = 1.1
    # "+2" in E21 and E24: (ancho * allowance + 2).
    run_extra: float = 2.0
    # "*3" on ancho in E20 and E21: (ancho * 3 * ft_factor).
    end_width_multiplier: float = 3.0
    # "+1" on ALTURA TECHADO LATERAL in E22 and C101.
    wall_extra_height: float = 1.0
    # "*5" in E23, C93, C102, C103 (D19).
    screws_per_unit: float = 5.0
    # "*4" at the end of E25 (purlin screws).
    purlin_screw_factor: float = 4.0
    # "20%" in E58, applied to all four steel groups, frenado included (D17).
    connection_ratio: float = 0.20
    # "*3*6" in E64 (D18).
    bolt_screws_a: float = 3.0
    bolt_screws_b: float = 6.0
    # "-0.5" in E30: gives 13.5 downspouts (D10).
    downspout_adjust: float = -0.5


DEFAULT_CONSTANTS = Constants()

# Where each constant is used and its status. Documentation for the parity report.
CONSTANT_NOTES = {
    "ft_factor": ("E19 E20 E21 E22 E27 E29 E42 E47 E51 E55", "UNCONFIRMED", "D5 D28 D29"),
    "allowance": ("E19 E21 E24 E27 E29 E51", "UNCONFIRMED", "D6 Q-E2-4"),
    "run_extra": ("E21 E24", "UNCONFIRMED", ""),
    "end_width_multiplier": ("E20 E21", "UNCONFIRMED", ""),
    "wall_extra_height": ("E22 C101", "UNCONFIRMED", "D12"),
    "screws_per_unit": ("E23 C93 C102 C103", "UNCONFIRMED", "D19 Q-E2-6"),
    "purlin_screw_factor": ("E25", "UNCONFIRMED", ""),
    "connection_ratio": ("E58", "UNCONFIRMED", "D17 Q-E2-5"),
    "bolt_screws_a": ("E64", "UNCONFIRMED", "D18"),
    "bolt_screws_b": ("E64", "UNCONFIRMED", "D18"),
    "downspout_adjust": ("E30", "UNCONFIRMED", "D10"),
}
