"""Estimator application service: Calculate (stateless), Generate (run + Draft quote in one transaction),
run read and parity compare. The calculation itself lives in estimator.core (pure)."""
import dataclasses
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

import psycopg2
from fastapi import HTTPException
from psycopg2.extras import RealDictCursor

from core.errors import api_error, internal_error
from database import get_db_connection
from estimator import calculate
from estimator.catalog import LINES
from estimator.inputs import EstimateInputs, EstimatorInputError
from estimator.loader import EstimatorVersionError, LoadedVersion, load_version

MODEL_NAME = "Nave Industrial"
ESTIMATE_TAX_CODE = "construction_17_2017"  # 1.8%, set explicitly; does not depend on TAX_FROM_CHARGES
STEEL_ROLES = ("columnas", "frenado", "tijerillas", "frontales", "conexiones")
SECTION_ES = {
    "acero": "Aceros estructurales y partes",
    "techo": "Elementos de Techo",
    "paredes": "Elementos para paredes",
    "accesorios": "Accesorios",
    "servicios": "Servicios",
    "extras": "Extras",
}
LINE_BY_ROW = {ln.row: ln for ln in LINES}


def q2(value: float) -> float:
    """Quote quantity: 2 decimals, half up (D-5 approved, applied at the quote boundary only)."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _norm(designation: str) -> str:
    return re.sub(r"\s+", "", str(designation)).replace("X", "x").replace("×", "x")


def active_version_id(cur) -> int:
    cur.execute(
        "SELECT v.id FROM public.estimator_versions v JOIN public.estimator_models m ON m.id = v.model_id "
        "WHERE m.name = %s AND m.status = 'active' AND v.status = 'active'",
        (MODEL_NAME,),
    )
    row = cur.fetchone()
    if not row:
        raise api_error(409, "No hay una versión activa del estimador", "ESTIMATOR_NO_ACTIVE_VERSION")
    return row["id"]


def _load(cur) -> LoadedVersion:
    try:
        return load_version(cur, active_version_id(cur))
    except EstimatorVersionError as e:
        raise api_error(409, f"La versión activa no es compatible con el código: {e}", "ESTIMATOR_VERSION_INCOMPATIBLE")


def _profile(lv: LoadedVersion, designation: str):
    p = lv.profiles.get(_norm(designation))
    if p is None:
        raise api_error(400, f"Perfil no encontrado: {designation}", "PROFILE_NOT_FOUND")
    return p


def _build(cur, req) -> dict:
    """Shared by Calculate and Generate. Reads only."""
    lv = _load(cur)
    inputs = EstimateInputs(
        ancho=req.ancho, largo=req.largo, altura_laterales=req.altura_laterales,
        altura_techado_lateral=req.altura_techado_lateral, distancia_ejes=req.distancia_ejes,
        columnas_frontales=req.columnas_frontales,
        perfil_columnas=_profile(lv, req.perfiles.columnas), perfil_frontales=_profile(lv, req.perfiles.frontales),
        perfil_tijerillas=_profile(lv, req.perfiles.tijerillas), perfil_frenado=_profile(lv, req.perfiles.frenado),
    )
    prices = dict(lv.prices)
    qty_over: Dict[int, float] = {}
    applied: List[dict] = []
    seen = set()
    for o in req.overrides:
        if o.row not in LINE_BY_ROW:
            raise api_error(400, f"Línea desconocida: {o.row}", "OVERRIDE_UNKNOWN_LINE")
        if o.row in seen:
            raise api_error(400, f"Línea repetida en los cambios: {o.row}", "OVERRIDE_DUPLICATE_LINE")
        seen.add(o.row)
        if o.unit_price is None and o.quantity is None:
            raise api_error(400, f"Cambio sin valor en la línea {o.row}", "OVERRIDE_EMPTY")
        if not o.reason.strip():
            raise api_error(400, "Todo cambio necesita un motivo", "OVERRIDE_REASON_REQUIRED")
        if o.unit_price is not None:
            applied.append({"row": o.row, "field": "unit_price", "old": prices[o.row], "new": o.unit_price, "reason": o.reason.strip()})
            prices[o.row] = o.unit_price
        if o.quantity is not None:
            applied.append({"row": o.row, "field": "quantity", "old": LINE_BY_ROW[o.row].fixed_qty, "new": o.quantity, "reason": o.reason.strip()})
            qty_over[o.row] = o.quantity
    try:
        result = calculate(inputs, lv.constants, prices, refuse_fractional_frames=True, quantity_overrides=qty_over)
    except EstimatorInputError as e:
        raise api_error(400, e.message_es, e.code)

    lines = []
    quote_items = []
    for ln in result.lines:
        d = LINE_BY_ROW[ln.row]
        description = f"{ln.label} ({ln.unit.strip()})"
        quote_qty = 1.0 if ln.quantity is None else q2(ln.quantity)
        quote_total = ln.unit_price if ln.quantity is None else quote_qty * ln.unit_price
        lines.append({
            "row": ln.row, "section": SECTION_ES[d.category], "description": description, "unit": ln.unit.strip(),
            "quantity": ln.quantity, "quote_quantity": quote_qty, "unit_price": ln.unit_price,
            "total": ln.total, "quote_total": quote_total, "role": ln.role,
        })
        quote_items.append({
            "product_name": description, "quantity": quote_qty, "unit_price": ln.unit_price,
            "discount_type": "none", "discount_value": 0.0, "item_type": lv.item_types[ln.row],
            "description": None, "product_id": None, "category": SECTION_ES[d.category],
            "print_on_pdf": lv.print_flags[ln.row],
        })
    q = result.quantities
    pounds = {"columnas": q["E42"], "frenado": q["E55"], "tijerillas": q["E51"], "frontales": q["E47"], "conexiones": q["E58"]}
    return {
        "lv": lv, "inputs": inputs, "result": result, "overrides": applied, "lines": lines, "quote_items": quote_items,
        "pounds": pounds, "total_pounds_workbook_e60": q["E60"],
    }


def _charges() -> dict:
    from quotes.models import IncludedCharges
    return IncludedCharges().dict()


def calculate_preview(req) -> dict:
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        b = _build(cur, req)
    finally:
        conn.close()
    from quotes.service import preview_totals
    totals = preview_totals(b["quote_items"], _charges(), ESTIMATE_TAX_CODE)
    return {
        "version": {"id": b["lv"].version_id, "version": b["lv"].version, "rule_revision": b["lv"].rule_revision},
        "lines": b["lines"], "subtotal_unrounded": b["result"].subtotal, "pounds_by_role": b["pounds"],
        "total_pounds_workbook_e60": b["total_pounds_workbook_e60"], "intermediates": b["result"].quantities,
        "warnings": b["result"].warnings, "overrides": b["overrides"], "totals_preview": totals,
        "workbook_indirects_informational": b["result"].workbook_indirects,
    }


def _snapshot(b: dict) -> dict:
    lv = b["lv"]
    i = b["inputs"]
    return {
        "version_id": lv.version_id, "version": lv.version, "rule_revision": lv.rule_revision,
        "constants": dataclasses.asdict(lv.constants), "prices": {str(k): v for k, v in lv.prices.items()},
        "profiles_used": {
            "columnas": dataclasses.asdict(i.perfil_columnas), "frontales": dataclasses.asdict(i.perfil_frontales),
            "tijerillas": dataclasses.asdict(i.perfil_tijerillas), "frenado": dataclasses.asdict(i.perfil_frenado),
        },
    }


def generate(req, user: dict) -> dict:
    user_id = user.get("user_id")
    if not user_id:
        raise api_error(400, "El token no trae el usuario", "USER_REQUIRED")
    key = str(req.idempotency_key)
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        existing = _run_by_key(cur, key)
        if existing:
            return _existing(existing, user_id)

        b = _build(cur, req)
        from quotes.service import create_quote_in_tx
        quote_id = create_quote_in_tx(
            cur, req.client_id, req.contact_id, req.project_name, req.notes, b["quote_items"], _charges(),
            req.payment_terms, req.valid_until, user_id, ESTIMATE_TAX_CODE, quote_type="engineering_estimate",
        )
        cur.execute("SELECT id, quote_number, grand_total FROM quotes WHERE quote_id = %s", (quote_id,))
        qrow = cur.fetchone()
        now = datetime.now(timezone.utc).isoformat()
        overrides = [dict(o, user_id=str(user_id), at=now) for o in b["overrides"]]
        res = b["result"]
        results = {
            "lines": b["lines"], "quantities": res.quantities, "subtotal": res.subtotal,
            "workbook_indirects": res.workbook_indirects, "pounds_by_role": b["pounds"],
        }
        inputs = dataclasses.asdict(b["inputs"])
        cur.execute(
            "INSERT INTO public.estimator_runs (version_id, rule_revision, generated_by, inputs, snapshot, results, warnings, "
            "overrides, quote_id, idempotency_key) VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s) RETURNING id",
            (b["lv"].version_id, b["lv"].rule_revision, user_id, json.dumps(inputs), json.dumps(_snapshot(b)),
             json.dumps(results), json.dumps(res.warnings), json.dumps(overrides), qrow["id"], key),
        )
        run_id = cur.fetchone()["id"]
        conn.commit()
        return {"run_id": run_id, "quote_id": quote_id, "quote_number": qrow["quote_number"],
                "grand_total": float(qrow["grand_total"]), "already_generated": False, "warnings": res.warnings}
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        existing = _run_by_key(cur, key)
        if existing:
            return _existing(existing, user_id)
        raise api_error(409, "Conflicto al guardar el estimado", "ESTIMATE_CONFLICT")
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise internal_error("No se pudo generar el estimado", e)
    finally:
        conn.close()


def _run_by_key(cur, key: str) -> Optional[dict]:
    cur.execute(
        "SELECT r.id, r.generated_by, q.quote_id, q.quote_number, q.grand_total FROM public.estimator_runs r "
        "JOIN public.quotes q ON q.id = r.quote_id WHERE r.idempotency_key = %s", (key,))
    return cur.fetchone()


def _existing(row: dict, user_id) -> dict:
    if str(row["generated_by"]) != str(user_id):
        raise api_error(409, "Esa clave ya fue usada por otro usuario", "IDEMPOTENCY_KEY_FOREIGN")
    return {"run_id": row["id"], "quote_id": row["quote_id"], "quote_number": row["quote_number"],
            "grand_total": float(row["grand_total"]), "already_generated": True, "warnings": []}


def get_run(run_id: int) -> dict:
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT r.*, q.quote_id AS quote_ref FROM public.estimator_runs r LEFT JOIN public.quotes q ON q.id = r.quote_id "
            "WHERE r.id = %s", (run_id,))
        row = cur.fetchone()
        if not row:
            raise api_error(404, "Estimado no encontrado", "RUN_NOT_FOUND")
        out = dict(row)
        out["generated_by"] = str(out["generated_by"])
        out["idempotency_key"] = None if out.get("idempotency_key") is None else str(out["idempotency_key"])
        out["created_at"] = out["created_at"].isoformat()
        return out
    finally:
        conn.close()


def parity(run_id: int, typed: Dict[str, float]) -> dict:
    """Compare typed workbook values with the run. Nothing is stored. Keys: calculation/quantity cells
    (E42, C93 ...), line totals F<row>, and F122 (subtotal)."""
    run = get_run(run_id)
    res = run["results"]
    mine: Dict[str, float] = dict(res["quantities"])
    for ln in res["lines"]:
        mine[f"F{ln['row']}"] = ln["total"]
    mine["F122"] = res["subtotal"]
    rows = []
    for cell, value in typed.items():
        if cell not in mine:
            raise api_error(400, f"Celda desconocida: {cell}", "PARITY_UNKNOWN_CELL")
        diff = mine[cell] - value
        rows.append({"cell": cell, "estimator": mine[cell], "workbook_typed": value, "difference": diff,
                     "matches": abs(diff) <= max(1e-6, abs(value) * 1e-9)})
    return {"run_id": run_id, "rows": rows, "all_match": all(r["matches"] for r in rows)}


def list_profiles() -> List[dict]:
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        vid = active_version_id(cur)
        cur.execute(
            "SELECT designation, display_designation, family, depth_in, lb_per_ft FROM public.estimator_profiles "
            "WHERE version_id = %s AND status = 'active' ORDER BY depth_in DESC, lb_per_ft DESC", (vid,))
        return [{**dict(r), "depth_in": float(r["depth_in"]), "lb_per_ft": float(r["lb_per_ft"])} for r in cur.fetchall()]
    finally:
        conn.close()
