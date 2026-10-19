"""Project Cost Ledger: expenses linked to a project, with totals.

Read-only queries. Expenses link to projects through expenses.project_id (INTEGER FK).
Billed and paid figures for profitability live in reports.service.
"""
from datetime import date
from typing import Optional

from psycopg2.extras import RealDictCursor

from core.errors import api_error
from database import get_db_connection


def _money(v) -> float:
    return round(float(v or 0), 2)


def expense_date_filter(column: str, start_date: Optional[date], end_date: Optional[date], params: list) -> str:
    """SQL fragment for an inclusive date range; either bound may be omitted."""
    sql = ""
    if start_date:
        sql += f" AND {column}::date >= %s"
        params.append(start_date)
    if end_date:
        sql += f" AND {column}::date <= %s"
        params.append(end_date)
    return sql


def categories_from_rows(rows, total: float) -> list:
    """[{category, total, count, percentage}] sorted by total, largest first."""
    out = []
    for r in rows:
        amount = _money(r["total"])
        out.append({
            "category": r["category"] or "Sin categoría",
            "total": amount,
            "count": int(r["n"]),
            "percentage": round(amount / total * 100, 2) if total else 0.0,
        })
    out.sort(key=lambda c: (-c["total"], c["category"]))
    return out


def get_project_expenses(project_id: int, start_date: Optional[date] = None, end_date: Optional[date] = None) -> dict:
    """Ledger for one project: expense rows (newest first) plus totals and a category breakdown."""
    if start_date and end_date and start_date > end_date:
        raise api_error(400, "La fecha de fin debe ser posterior a la fecha de inicio", "DATE_RANGE_INVALID")
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, name FROM projects WHERE id = %s", (project_id,))
        project = cur.fetchone()
        if not project:
            raise api_error(404, "Proyecto no encontrado", "PROJECT_NOT_FOUND")

        params = [project_id]
        where = " WHERE e.project_id = %s" + expense_date_filter("e.date", start_date, end_date, params)

        cur.execute(
            "SELECT e.expense_id, e.date, e.category, e.description, e.amount, e.payment_method, "
            "e.client_name, e.quote_id, e.project_id, e.created_at FROM expenses e"
            + where + " ORDER BY e.date DESC, e.expense_id DESC",
            params,
        )
        expenses = [dict(r) for r in cur.fetchall()]
        for e in expenses:
            e["amount"] = _money(e["amount"])

        cur.execute(
            "SELECT e.category, COALESCE(SUM(e.amount), 0) AS total, COUNT(*) AS n FROM expenses e"
            + where + " GROUP BY e.category",
            params,
        )
        total = round(sum(e["amount"] for e in expenses), 2)
        return {
            "project_id": project["id"],
            "project_name": project["name"],
            "filters": {"start_date": start_date, "end_date": end_date},
            "expenses": expenses,
            "totals": {
                "total_expenses": total,
                "count": len(expenses),
                "expenses_by_category": categories_from_rows(cur.fetchall(), total),
            },
        }
    finally:
        conn.close()


def get_project_cost_estimate(project_id: int) -> dict:
    """Product Cost module: estimated cost (from the project's quote) vs actual expenses.

    - estimated_cost / estimated_margin: quotes.costing.quote_estimate of the originating quote.
    - expenses_total: all expenses linked to the project.
    - actual_margin: billed (sin ITBIS) - expenses, same definition as Rentabilidad del Proyecto.
    - variance = estimated_cost - expenses_total; margin_accuracy_pct = actual / estimated * 100,
      only once something has been billed (otherwise None).
    """
    from quotes import costing
    from reports.service import get_project_profitability

    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, name, quote_id FROM projects WHERE id = %s", (project_id,))
        project = cur.fetchone()
        if not project:
            raise api_error(404, "Proyecto no encontrado", "PROJECT_NOT_FOUND")
        cur.execute("SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS n FROM expenses WHERE project_id = %s",
                    (project_id,))
        exp = cur.fetchone()
        estimate = costing.quote_estimate(cur, project["quote_id"]) if project["quote_id"] else None
    finally:
        conn.close()

    prof = get_project_profitability(project_id=project_id)["projects"]
    p = prof[0] if prof else {}
    billed_net = float(p.get("billed_net") or 0)
    expenses_total = round(float(exp["total"]), 2)
    actual_margin = round(billed_net - expenses_total, 2)
    est_cost = estimate["estimated_cost"] if estimate else 0.0
    est_margin = estimate["estimated_margin"] if estimate else None
    v = costing.variance(est_cost, expenses_total, est_margin, actual_margin if billed_net > 0 else None)
    return {
        "project_id": project["id"],
        "project_name": project["name"],
        "has_quote": bool(project["quote_id"]),
        "estimate": estimate,
        "estimated_cost": est_cost,
        "estimated_margin": est_margin,
        "expenses_total": expenses_total,
        "expense_count": int(exp["n"]),
        "billed_net": round(billed_net, 2),
        "actual_margin": actual_margin if billed_net > 0 else None,
        **v,
    }
