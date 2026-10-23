"""Estimate inputs and their validation.

Six manual numbers (E9, E11, E13, E15, E17, E38) and four profile choices (F41, F45, F50, F54).
Dimension units are not stated in the workbook (D29). They are treated as meters, ASSUMED.
Nothing is rounded. Guards only refuse what the workbook cannot calculate (division by zero)
or what is not physically meaningful (zero or negative sizes).
"""
import math
from dataclasses import dataclass
from typing import Optional


class EstimatorInputError(ValueError):
    """Refused input. `code` is stable for the API; `message_es` is for the user."""

    def __init__(self, code: str, message_es: str):
        super().__init__(message_es)
        self.code = code
        self.message_es = message_es


@dataclass(frozen=True)
class ProfileChoice:
    """A steel profile for one role. `lb_per_ft` is the stored value (weight per foot)."""

    designation: str
    lb_per_ft: float


@dataclass(frozen=True)
class EstimateInputs:
    ancho: float                      # E9
    largo: float                      # E11
    altura_laterales: float           # E13
    altura_techado_lateral: float     # E15
    distancia_ejes: float             # E17
    columnas_frontales: float         # E38
    perfil_columnas: ProfileChoice    # E41 / F41
    perfil_frontales: ProfileChoice   # E45 / F45
    perfil_tijerillas: ProfileChoice  # E50 / F50
    perfil_frenado: ProfileChoice     # E54 / F54


# Workbook defaults (case 1).
DEFAULT_PROFILES = {
    "columnas": ProfileChoice("W12 x 40", 40.0),
    "frontales": ProfileChoice("W8 x 31", 31.0),
    "tijerillas": ProfileChoice("W14x22", 22.0),
    # E54 is truncated in the workbook ("W10 x"); weight 12 comes from F54 (Q-E3-2 open).
    "frenado": ProfileChoice("W10 x (truncated in workbook)", 12.0),
}


def default_inputs(**overrides) -> EstimateInputs:
    """Workbook default case: 18 x 45, heights 9 and 5, axis distance 7.5, 6 front columns."""
    base = dict(
        ancho=18, largo=45, altura_laterales=9, altura_techado_lateral=5,
        distancia_ejes=7.5, columnas_frontales=6,
        perfil_columnas=DEFAULT_PROFILES["columnas"],
        perfil_frontales=DEFAULT_PROFILES["frontales"],
        perfil_tijerillas=DEFAULT_PROFILES["tijerillas"],
        perfil_frenado=DEFAULT_PROFILES["frenado"],
    )
    base.update(overrides)
    return EstimateInputs(**base)


def _number(name: str, value, label: str) -> float:
    if isinstance(value, bool) or value is None:
        raise EstimatorInputError("INPUT_NOT_NUMBER", f"{label} debe ser un número")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise EstimatorInputError("INPUT_NOT_NUMBER", f"{label} debe ser un número")
    if not math.isfinite(number):
        raise EstimatorInputError("INPUT_NOT_NUMBER", f"{label} debe ser un número finito")
    return number


_LABELS = {
    "ancho": "El ancho",
    "largo": "El largo",
    "altura_laterales": "La altura en los laterales",
    "altura_techado_lateral": "La altura del techado lateral",
    "distancia_ejes": "La distancia entre ejes transversales",
    "columnas_frontales": "La cantidad de columnas frontales",
}


def validate_inputs(
    inp: EstimateInputs, *, refuse_fractional_frames: bool = False
) -> EstimateInputs:
    """Return inputs with numbers as floats, or raise EstimatorInputError.

    refuse_fractional_frames (default False): when largo is not a multiple of distancia_ejes the
    workbook still calculates, with fractional frames (defect D31). Parity keeps that behavior.
    Switch on only after Fabian confirms Q-E4-5 (recommended: refuse).
    """
    values = {}
    for name, label in _LABELS.items():
        values[name] = _number(name, getattr(inp, name), label)
    for name in ("ancho", "largo", "altura_laterales", "altura_techado_lateral", "distancia_ejes"):
        if values[name] <= 0:
            raise EstimatorInputError("INPUT_NOT_POSITIVE", f"{_LABELS[name]} debe ser mayor que cero")
    if values["columnas_frontales"] < 0:
        raise EstimatorInputError("INPUT_NEGATIVE", f"{_LABELS['columnas_frontales']} no puede ser negativa")

    profiles = {}
    for name in ("perfil_columnas", "perfil_frontales", "perfil_tijerillas", "perfil_frenado"):
        choice: Optional[ProfileChoice] = getattr(inp, name)
        if choice is None:
            raise EstimatorInputError("PROFILE_MISSING", "Falta un perfil de acero")
        weight = _number(name, choice.lb_per_ft, "El peso por pie del perfil")
        if weight <= 0:
            raise EstimatorInputError("PROFILE_WEIGHT_INVALID", "El peso por pie del perfil debe ser mayor que cero")
        profiles[name] = ProfileChoice(str(choice.designation), weight)

    if refuse_fractional_frames:
        ratio = values["largo"] / values["distancia_ejes"]
        if abs(ratio - round(ratio)) > 1e-9:
            raise EstimatorInputError(
                "FRAMES_NOT_WHOLE",
                "El largo no es múltiplo de la distancia entre ejes; el número de pórticos no sería entero",
            )

    return EstimateInputs(**values, **profiles)
