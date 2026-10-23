"""Engineering Estimate calculation core (phase I2, parity first).

STATUS: branch work only. Not wired into main.py. No database, no HTTP, no deploy.
Design baseline v1.0 (claude/engineering-estimate-*.md). Approved by Fabian for phase I2 on
2026-10-22: reproduce the workbook METPRO_CALCULADORA_DE_NAVES exactly, defects included, and flag
them (rules D-7 and D-8). Nothing in the workbook is corrected here.

Public API:
    calculate(EstimateInputs, ...) -> EstimateResult
    EstimateInputs, ProfileChoice, Constants, EstimatorInputError
"""
from estimator.constants import DEFAULT_CONSTANTS, Constants
from estimator.core import EstimateResult, LineResult, calculate
from estimator.inputs import EstimateInputs, EstimatorInputError, ProfileChoice

RULE_SET = "nave"
RULE_REVISION = 1

__all__ = [
    "calculate",
    "Constants",
    "DEFAULT_CONSTANTS",
    "EstimateInputs",
    "EstimateResult",
    "EstimatorInputError",
    "LineResult",
    "ProfileChoice",
    "RULE_REVISION",
    "RULE_SET",
]
