"""Client Profitability Report, Phase 1 (approved 2026-10-22). Read-only. Writes nothing.

Rules:
- Revenue = invoice total minus the invoice's own tax (itbis_total holds ITBIS or Construcción 17-2017).
  No tax ever counts as revenue. Cancelled invoices are left out. Invoice date decides the period.
- COGS = product cost + known direct costs.
    product cost  = invoice line quantity x the product's CURRENT cost (same basis as the Product Cost module).
                    Lines with no product or no cost are left out and reported through cost_coverage_pct.
    direct costs  = expenses linked to the client's projects, by expense date.
- Gross profit = revenue - COGS. Profit % = gross profit / revenue (None when revenue is 0).
- Outstanding = per invoice, total minus non-voided payments, never below 0. Point in time (all payments to date).
- Invoices with no project go to "General Client Activity". Revenue is never dropped for lack of a project.
Not in Phase 1: labor, estimator or salesperson profitability.
"""
from typing import Optional

from psycopg2.extras import RealDictCursor

from database import get_db_connection
from core.errors import internal_error

GENERAL_LABEL = "General Client Activity"
NO_CLIENT_LABEL = "Sin cliente"


def _m(v) -> float:
    return round(float(v or 0), 2)


def _pct(num: float, den: float) -> Optional[float]:
    return round(num / den * 100, 2) if den else None


def _new_bucket(project_id, name) -> dict:
    return {"project_id": project_id, "name": name, "invoice_count": 0, "revenue": 0.0, "product_cost": 0.0,
            "direct_costs": 0.0, "outstanding": 0.0, "lines_total": 0, "lines_costed": 0, "invoices_without_tax": 0}


def _finish(b: dict) -> dict:
    revenue, pc, dc = _m(b["revenue"]), _m(b["product_cost"]), _m(b["direct_costs"])
    cogs = round(pc + dc, 2)
    gross = round(revenue - cogs, 2)
    lt, lc = b["lines_total"], b["lines_costed"]
    return {
        "invoice_count": b["invoice_count"],
        "revenue": revenue,
        "product_cost": pc,
        "direct_costs": dc,
        "cogs": cogs,
        "gross_profit": gross,
        "profit_pct": _pct(gross, revenue),
        "outstanding": _m(b["outstanding"]),
        "cost_coverage_pct": _pct(lc, lt),
        "invoices_without_tax": b["invoices_without_tax"],
    }


def _add(into: dict, b: dict) -> None:
    for k in ("invoice_count", "revenue", "product_cost", "direct_costs", "outstanding", "lines_total",
              "lines_costed", "invoices_without_tax"):
        into[k] += b[k]


def get_client_profitability(start_date=None, end_date=None, client_id: Optional[int] = None) -> dict:
    from projects.ledger import expense_date_filter

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        ip = []
        inv_dates = expense_date_filter("i.invoice_date", start_date, end_date, ip)
        client_sql = ""
        if client_id:
            client_sql = " AND i.client_id = %s"
            ip.append(client_id)
        cur.execute(f"""
            SELECT i.id, i.client_id, c.company_name, pr.id AS project_id, pr.name AS project_name,
                   i.total_amount - COALESCE(i.itbis_total, 0) AS revenue,
                   GREATEST(i.total_amount - COALESCE(pay.paid, 0), 0) AS outstanding,
                   COALESCE(ic.cost, 0) AS product_cost,
                   COALESCE(ic.lines_total, 0) AS lines_total, COALESCE(ic.lines_costed, 0) AS lines_costed,
                   (COALESCE(i.itbis_total, 0) = 0 AND i.total_amount > 0) AS no_tax
            FROM invoices i
            LEFT JOIN clients c ON c.id = i.client_id
            LEFT JOIN LATERAL (
                SELECT p.id, p.name FROM projects p
                WHERE i.quote_id IS NOT NULL AND p.quote_id = i.quote_id ORDER BY p.id LIMIT 1
            ) pr ON TRUE
            LEFT JOIN LATERAL (
                SELECT SUM(ip.amount) AS paid FROM invoice_payments ip
                WHERE ip.invoice_id = i.id AND ip.voided_at IS NULL
            ) pay ON TRUE
            LEFT JOIN LATERAL (
                SELECT SUM(ii.quantity * p2.cost) AS cost, COUNT(*) AS lines_total, COUNT(p2.cost) AS lines_costed
                FROM invoice_items ii LEFT JOIN products p2 ON p2.id = ii.product_id
                WHERE ii.invoice_id = i.id
            ) ic ON TRUE
            WHERE i.status <> 'Cancelled'{inv_dates}{client_sql}
        """, ip)
        invoices = cur.fetchall()

        ep = []
        exp_dates = expense_date_filter("e.date", start_date, end_date, ep)
        exp_client = ""
        if client_id:
            exp_client = " AND p.client_id = %s"
            ep.append(client_id)
        cur.execute(f"""
            SELECT p.id AS project_id, p.name AS project_name, p.client_id, c.company_name,
                   COALESCE(SUM(e.amount), 0) AS amount
            FROM expenses e JOIN projects p ON p.id = e.project_id
            LEFT JOIN clients c ON c.id = p.client_id
            WHERE 1=1{exp_dates}{exp_client}
            GROUP BY p.id, p.name, p.client_id, c.company_name
        """, ep)
        expenses = cur.fetchall()

        unlinked = None
        if not client_id:
            up = []
            ud = expense_date_filter("e.date", start_date, end_date, up)
            cur.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(e.amount), 0) AS amount FROM expenses e "
                        f"WHERE e.project_id IS NULL{ud}", up)
            u = cur.fetchone()
            unlinked = {"count": int(u["n"]), "amount": _m(u["amount"])}

        clients: dict = {}

        def bucket(cid, cname, pid, pname) -> dict:
            c = clients.setdefault(cid, {"client_id": cid, "client_name": cname or NO_CLIENT_LABEL, "buckets": {}})
            key = pid  # None = General Client Activity
            return c["buckets"].setdefault(key, _new_bucket(pid, pname if pid is not None else GENERAL_LABEL))

        for r in invoices:
            b = bucket(r["client_id"], r["company_name"], r["project_id"], r["project_name"])
            b["invoice_count"] += 1
            b["revenue"] += float(r["revenue"] or 0)
            b["product_cost"] += float(r["product_cost"] or 0)
            b["outstanding"] += float(r["outstanding"] or 0)
            b["lines_total"] += int(r["lines_total"])
            b["lines_costed"] += int(r["lines_costed"])
            b["invoices_without_tax"] += 1 if r["no_tax"] else 0
        for r in expenses:
            b = bucket(r["client_id"], r["company_name"], r["project_id"], r["project_name"])
            b["direct_costs"] += float(r["amount"] or 0)

        out_clients = []
        grand = _new_bucket(None, "total")
        for c in clients.values():
            total = _new_bucket(None, c["client_name"])
            rows = []
            for key in sorted(c["buckets"], key=lambda k: (k is None, k or 0)):
                b = c["buckets"][key]
                _add(total, b)
                rows.append({"project_id": b["project_id"], "name": b["name"], **_finish(b)})
            _add(grand, total)
            out_clients.append({"client_id": c["client_id"], "client_name": c["client_name"], **_finish(total),
                                "breakdown": rows})
        out_clients.sort(key=lambda r: (-r["gross_profit"], r["client_name"]))

        return {
            "summary": {
                "client_count": len(out_clients),
                "basis": "sin_impuesto",
                **_finish(grand),
                "unlinked_expenses": unlinked,
                "filters": {"start_date": start_date, "end_date": end_date, "client_id": client_id},
            },
            "clients": out_clients,
        }
    except Exception as e:
        raise internal_error("No se pudo generar el reporte de rentabilidad por cliente", e)
    finally:
        if conn:
            conn.close()
