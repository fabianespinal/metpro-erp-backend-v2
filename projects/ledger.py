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
