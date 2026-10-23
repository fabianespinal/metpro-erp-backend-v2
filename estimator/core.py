"""Pure calculation. No DB, no HTTP, no rounding. Parity with the workbook first."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from estimator.catalog import LINES, LineDef
from estimator.constants import DEFAULT_CONSTANTS, Constants
from estimator.inputs import EstimateInputs, EstimatorInputError, validate_inputs
from estimator.rules import LINE_RULES, RULES


@dataclass(frozen=True)
class LineResult:
    row: int
    label: str
    unit: str
    category: str
    quantity: Optional[float]   # None for the PPA text line
    unit_price: float
    total: float
    role: Optional[str]


@dataclass(frozen=True)
class EstimateResult:
    quantities: Dict[str, float]       # every calculated workbook cell (E19..E64, C93..)
    lines: List[LineResult]
    subtotal: float                    # F122
    workbook_indirects: Dict[str, float]  # C125..C133, workbook behavior (C131 quirk)
    warnings: List[dict] = field(default_factory=list)


def _warn(code: str, message_es: str, ref: str) -> dict:
    return {"code": code, "message_es": message_es, "defect": ref}


def calculate(
    inputs: EstimateInputs,
    constants: Constants = DEFAULT_CONSTANTS,
    prices: Optional[Dict[int, float]] = None,
    *,
    refuse_fractional_frames: bool = False,
    quantity_overrides: Optional[Dict[int, float]] = None,
) -> EstimateResult:
    """quantity_overrides: workbook row -> quantity, allowed only for lines whose quantity is a typed
    (fixed) value in the workbook. Calculated quantities cannot be overridden here."""
    inp = validate_inputs(inputs, refuse_fractional_frames=refuse_fractional_frames)
    fixed_rows = {ld.row for ld in LINES if ld.fixed_qty is not None}
    for row, qty in (quantity_overrides or {}).items():
        if row not in fixed_rows:
            raise EstimatorInputError("QUANTITY_OVERRIDE_NOT_ALLOWED", f"La línea {row} tiene cantidad calculada y no se puede cambiar")
        if not isinstance(qty, (int, float)) or isinstance(qty, bool) or qty < 0:
            raise EstimatorInputError("QUANTITY_OVERRIDE_INVALID", f"Cantidad no válida para la línea {row}")
    ctx: Dict[str, float] = {
        "E9": inp.ancho, "E11": inp.largo, "E13": inp.altura_laterales,
        "E15": inp.altura_techado_lateral, "E17": inp.distancia_ejes,
        "E38": inp.columnas_frontales,
        "F41": inp.perfil_columnas.lb_per_ft, "F45": inp.perfil_frontales.lb_per_ft,
        "F50": inp.perfil_tijerillas.lb_per_ft, "F54": inp.perfil_frenado.lb_per_ft,
    }
    for cell, fn in RULES:
        ctx[cell] = fn(ctx, constants)
    # Line quantity aliases used by the workbook (C88 = E19, C99 = E20, C100 = E22).
    ctx["C88"], ctx["C99"], ctx["C100"] = ctx["E19"], ctx["E20"], ctx["E22"]
    for cell, fn in LINE_RULES:
        ctx[cell] = fn(ctx, constants)

    lines: List[LineResult] = []
    for ld in LINES:
        price = float((prices or {}).get(ld.row, ld.price))
        if ld.total_is_price:
            qty, total = None, price
        else:
            if ld.qty_cell is None:
                qty = float((quantity_overrides or {}).get(ld.row, ld.fixed_qty))
            else:
                qty = ctx[ld.qty_cell]
            total = qty * price
        lines.append(LineResult(ld.row, ld.label, ld.unit, ld.category, qty, price, total, ld.role))

    subtotal = 0.0
    for ln in lines:
        subtotal += ln.total  # SUM(F78:F121) order

    # Workbook indirect block: PARITY ONLY, informational. The design (D1, D2, D3) rules that indirects,
    # tax and the final total belong to the ERP, not the engine. Do not use these for pricing.
    ind = {"C125": subtotal}
    ind["C126"] = subtotal * 0.10
    ind["C127"] = subtotal * 0.04
    ind["C128"] = subtotal * 0.01
    ind["C129"] = subtotal * 0.03
    ind["C130"] = subtotal * 0.03
    ind["C131"] = subtotal + 1  # SUM(C120:D125) picks up C121 = 1 (range quirk)
    ind["C132"] = ind["C131"] * 0.018
    ind["C133"] = ind["C131"] + ind["C132"]

    warnings: List[dict] = []
    frames = inp.largo / inp.distancia_ejes
    if abs(frames - round(frames)) > 1e-9:
        warnings.append(_warn("FRAMES_FRACTIONAL", f"El largo/eje da {frames:.3f} pórticos: no es entero", "D31"))
    warnings.append(_warn("E60_OMITS_BRACING", "El total de acero del libro (E60) omite el frenado (E55)", "D4"))
    warnings.append(_warn("UNITS_ASSUMED", "Unidades de dimensión no indicadas en el libro; se asumen metros", "D29"))
    warnings.append(_warn("UNCONFIRMED_CONSTANTS", "Constantes 3.28, 1.1, 20% y otras sin significado confirmado", "D5 D6 D17"))
    warnings.append(_warn("STATIC_LABELS", "Las descripciones de las líneas 78 a 80 traen cantidades y perfiles escritos que no siguen las entradas", "D14"))
    warnings.append(_warn("FRACTIONAL_UNIT_COUNTS", "Cantidades fraccionarias en artículos por unidad (tillas, tornillos, bajantes)", "D10 D11"))
    warnings.append(_warn("BOLT_PRICE_EQUALS_STEEL", "Tornillos 3/4 (fila 83) se valoran a 85 por unidad, igual que el acero por libra", "D20"))
    return EstimateResult(
        quantities={k: ctx[k] for k in ctx if k[0] in "EC" and k not in ("E9", "E11", "E13", "E15", "E17", "E38")},
        lines=lines, subtotal=subtotal, workbook_indirects=ind, warnings=warnings,
    )
