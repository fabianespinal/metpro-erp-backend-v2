"""Read-only loader: database version -> Constants, prices, profiles for calculate().

Takes a DB-API cursor that returns dict rows (psycopg2 RealDictCursor). Never writes.
Refuses to load when the data does not match the deployed rule set (rule revision, line catalog,
constant keys). Draft versions load only with allow_draft=True (tests and preview); production
runs use an active version.
"""
import dataclasses
from dataclasses import dataclass
from typing import Dict

from estimator import RULE_REVISION
from estimator.catalog import LINES
from estimator.constants import Constants
from estimator.inputs import ProfileChoice


class EstimatorVersionError(RuntimeError):
    """The stored version cannot be used with the deployed code."""


@dataclass(frozen=True)
class LoadedVersion:
    version_id: int
    version: str
    status: str
    rule_revision: int
    constants: Constants
    prices: Dict[int, float]
    profiles: Dict[str, ProfileChoice]


def load_version(cur, version_id: int, *, allow_draft: bool = False) -> LoadedVersion:
    cur.execute("SELECT id, version, status, rule_revision FROM public.estimator_versions WHERE id = %s", (version_id,))
    head = cur.fetchone()
    if head is None:
        raise EstimatorVersionError(f"estimator version {version_id} not found")
    if head["rule_revision"] != RULE_REVISION:
        raise EstimatorVersionError(
            f"version needs rule revision {head['rule_revision']}, deployed code has {RULE_REVISION}"
        )
    if head["status"] == "retired" or (head["status"] == "draft" and not allow_draft):
        raise EstimatorVersionError(f"estimator version {version_id} is {head['status']} and cannot run")

    cur.execute("SELECT key, value FROM public.estimator_constants WHERE version_id = %s", (version_id,))
    stored = {r["key"]: float(r["value"]) for r in cur.fetchall()}
    names = {f.name for f in dataclasses.fields(Constants)}
    if set(stored) != names:
        raise EstimatorVersionError(
            f"constants mismatch: missing {sorted(names - set(stored))}, unknown {sorted(set(stored) - names)}"
        )
    constants = Constants(**stored)

    cur.execute(
        "SELECT row_ref, driver_key, fixed_quantity, unit_label, total_is_price, role_key, price "
        "FROM public.estimator_materials WHERE version_id = %s",
        (version_id,),
    )
    rows = {r["row_ref"]: r for r in cur.fetchall()}
    if set(rows) != {ln.row for ln in LINES}:
        raise EstimatorVersionError("material lines do not match the deployed line catalog")
    prices: Dict[int, float] = {}
    for ln in LINES:
        r = rows[ln.row]
        fixed = None if r["fixed_quantity"] is None else float(r["fixed_quantity"])
        if (
            r["driver_key"] != ln.qty_cell
            or fixed != (None if ln.fixed_qty is None else float(ln.fixed_qty))
            or bool(r["total_is_price"]) != ln.total_is_price
            or r["role_key"] != ln.role
            or r["unit_label"] != ln.unit
        ):
            raise EstimatorVersionError(f"material line {ln.row} differs from the deployed rule set")
        prices[ln.row] = float(r["price"])

    cur.execute(
        "SELECT designation, lb_per_ft FROM public.estimator_profiles WHERE version_id = %s AND status = 'active'",
        (version_id,),
    )
    profiles = {r["designation"]: ProfileChoice(r["designation"], float(r["lb_per_ft"])) for r in cur.fetchall()}
    return LoadedVersion(head["id"], head["version"], head["status"], head["rule_revision"], constants, prices, profiles)
