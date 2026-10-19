from typing import Optional
from fastapi import HTTPException
from database import get_db_connection
from psycopg2.extras import RealDictCursor
from core.errors import internal_error


# ============================================================
# QUOTES SUMMARY REPORT
# ============================================================

def get_quotes_summary(start_date: Optional[str], end_date: Optional[str],
                       client_id: Optional[int]) -> dict:

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Base query
        query = """
            SELECT 
                q.status,
                COUNT(*) AS count
            FROM quotes q
            WHERE 1=1
        """
        params = []

        # Date filter
        if start_date and end_date:
            query += " AND q.created_at BETWEEN %s AND %s"
            params.extend([start_date, end_date])

        # Client filter
        if client_id:
            query += " AND q.client_id = %s"
            params.append(client_id)

        # Grouping
        query += " GROUP BY q.status ORDER BY q.status"

        cursor.execute(query, params)
        status_breakdown = cursor.fetchall()

        # Grand total
        total_query = "SELECT COUNT(*) AS total FROM quotes q WHERE 1=1"
        total_params = []

        if start_date and end_date:
            total_query += " AND q.created_at BETWEEN %s AND %s"
            total_params.extend([start_date, end_date])

        if client_id:
            total_query += " AND q.client_id = %s"
            total_params.append(client_id)

        cursor.execute(total_query, total_params)
        grand_total = cursor.fetchone()["total"]

        return {
            "summary": {
                "total_quotes": grand_total,
                "filters": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "client_id": client_id
                }
            },
            "status_breakdown": [
                {
                    "status": row["status"],
                    "count": row["count"],
                    "percentage": round((row["count"] / grand_total * 100), 1)
                    if grand_total > 0 else 0
                }
                for row in status_breakdown
            ]
        }

    finally:
        if conn:
            conn.close()


# ============================================================
# REVENUE REPORT
# ============================================================

def get_revenue_report(start_date: Optional[str], end_date: Optional[str],
                       client_id: Optional[int]) -> dict:
    """
    Revenue from invoices and payments (R1). Quotes are not revenue.

    - invoiced:    SUM(total_amount) of non-cancelled invoices (by invoice_date)
    - collected:   SUM(amount) of payments (by payment_date)  <- headline figure
    - outstanding: SUM(total_amount - amount_paid) of Pending/Overdue invoices (by invoice_date)
    - pipeline:    SUM(grand_total) of Approved quotes not yet invoiced (information only)
    Date filters apply when both start_date and end_date are given.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        def scoped(base, date_col, client_col, params):
            q = base
            if start_date and end_date:
                q += f" AND {date_col}::date BETWEEN %s AND %s"
                params.extend([start_date, end_date])
            if client_id:
                q += f" AND {client_col} = %s"
                params.append(client_id)
            return q

        p1 = []
        cursor.execute(scoped(
            "SELECT COALESCE(SUM(i.total_amount), 0) AS amount, COUNT(*) AS n "
            "FROM invoices i WHERE i.status <> 'Cancelled'",
            "i.invoice_date", "i.client_id", p1), p1)
        invoiced = cursor.fetchone()

        p2 = []
        cursor.execute(scoped(
            "SELECT COALESCE(SUM(p.amount), 0) AS amount, COUNT(*) AS n "
            "FROM invoice_payments p JOIN invoices i ON i.id = p.invoice_id WHERE 1=1",
            "p.payment_date", "i.client_id", p2), p2)
        collected = cursor.fetchone()

        p3 = []
        cursor.execute(scoped(
            "SELECT COALESCE(SUM(i.total_amount - COALESCE(i.amount_paid, 0)), 0) AS amount, COUNT(*) AS n "
            "FROM invoices i WHERE i.status IN ('Pending', 'Overdue')",
            "i.invoice_date", "i.client_id", p3), p3)
        outstanding = cursor.fetchone()

        p4 = []
        cursor.execute(scoped(
            "SELECT COALESCE(SUM(COALESCE(q.grand_total, q.total_amount)), 0) AS amount, COUNT(*) AS n "
            "FROM quotes q WHERE q.status = 'Approved' "
            "AND NOT EXISTS (SELECT 1 FROM invoices i WHERE i.quote_id = q.quote_id)",
            "q.created_at", "q.client_id", p4), p4)
        pipeline = cursor.fetchone()

        def row(key, label, r):
            return {"key": key, "status": label, "total_revenue": round(float(r["amount"]), 2),
                    "count": int(r["n"]), "quote_count": int(r["n"])}

        total_collected = round(float(collected["amount"]), 2)
        return {
            "summary": {
                "total_revenue": total_collected,
                "invoiced_total": round(float(invoiced["amount"]), 2),
                "outstanding": round(float(outstanding["amount"]), 2),
                "pipeline_approved": round(float(pipeline["amount"]), 2),
                "filters": {"start_date": start_date, "end_date": end_date, "client_id": client_id},
            },
            "revenue_breakdown": [
                row("invoiced", "Facturado", invoiced),
                row("collected", "Cobrado", collected),
                row("outstanding", "Por cobrar", outstanding),
                row("pipeline", "Aprobado sin facturar", pipeline),
            ],
            "grand_total": total_collected,
        }

    except Exception as e:
        raise internal_error("No se pudo generar el reporte de ingresos", e)

    finally:
        if conn:
            conn.close()


# ============================================================
# CLIENT ACTIVITY REPORT
# ============================================================

def get_client_activity(start_date: Optional[str], end_date: Optional[str]) -> dict:

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT 
                c.id AS client_id,
                c.company_name,
                COUNT(q.quote_id) AS quote_count,
                COALESCE(SUM(q.total_amount), 0) AS total_quoted,
                MAX(q.created_at) AS last_quote_date
            FROM clients c
            INNER JOIN quotes q ON c.id = q.client_id
            WHERE 1=1
        """
        params = []

        # Date filter
        if start_date and end_date:
            query += " AND q.created_at BETWEEN %s AND %s"
            params.extend([start_date, end_date])

        query += " GROUP BY c.id, c.company_name ORDER BY total_quoted DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        clients_data = [
            {
                "client_id": row["client_id"],
                "client_name": row["company_name"] or "Unknown",
                "quote_count": int(row["quote_count"]) if row["quote_count"] else 0,
                "total_quoted": float(row["total_quoted"]) if row["total_quoted"] else 0.0,
                "last_quote_date": row["last_quote_date"]
            }
            for row in rows
        ]

        return {
            "summary": {
                "total_clients": len(clients_data),
                "filters": {
                    "start_date": start_date,
                    "end_date": end_date
                }
            },
            "clients": clients_data
        }

    finally:
        if conn:
            conn.close()


# ============================================================
# PROJECT PROFITABILITY (Project Cost Ledger)
# ============================================================

def get_project_profitability(start_date=None, end_date=None, client_id: Optional[int] = None,
                              project_id: Optional[int] = None) -> dict:
    """
    Per project:
    - billed:     SUM(total_amount) of non-cancelled invoices of the project's quote (by invoice_date),
                  ITBIS included. billed_itbis = SUM(itbis_total).
    - billed_net: billed - billed_itbis (Facturado sin ITBIS).
    - paid:       SUM(payments) on those invoices (by payment_date), ITBIS included.
    - paid_net:   each payment without its ITBIS share: amount * (total_amount - itbis_total) / total_amount
                  of its invoice (Cobrado sin ITBIS).
    - outstanding: billed - paid (receivable, ITBIS included).
    All margins exclude ITBIS (approved 2026-10-18):
    - expenses: SUM(expenses.amount) linked to the project (by expense date).
    - net_margin = billed_net - expenses; margin_pct = net_margin / billed_net * 100 (None when 0).
    - cash_margin = paid_net - expenses.
    invoices_without_itbis counts billed invoices whose itbis_total is 0 (legacy rows), so a margin
    computed on them can be checked by hand.
    Date bounds are optional and inclusive.
    """
    from projects.ledger import categories_from_rows, expense_date_filter

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        params = []
        inv_dates = expense_date_filter("i.invoice_date", start_date, end_date, params)
        pay_params = []
        pay_dates = expense_date_filter("ip.payment_date", start_date, end_date, pay_params)
        exp_params = []
        exp_dates = expense_date_filter("e.date", start_date, end_date, exp_params)

        sql = f"""
            SELECT p.id, p.name, p.status, p.quote_number, c.company_name AS client_name,
                   COALESCE(b.billed, 0) AS billed, COALESCE(b.itbis, 0) AS billed_itbis,
                   COALESCE(b.no_itbis, 0) AS invoices_without_itbis,
                   COALESCE(pay.paid, 0) AS paid, COALESCE(pay.paid_net, 0) AS paid_net,
                   COALESCE(x.expenses, 0) AS expenses, COALESCE(x.n, 0) AS expense_count
            FROM projects p
            JOIN clients c ON c.id = p.client_id
            LEFT JOIN LATERAL (
                SELECT SUM(i.total_amount) AS billed, SUM(COALESCE(i.itbis_total, 0)) AS itbis,
                       COUNT(*) FILTER (WHERE COALESCE(i.itbis_total, 0) = 0 AND i.total_amount > 0) AS no_itbis
                FROM invoices i
                WHERE p.quote_id IS NOT NULL AND i.quote_id = p.quote_id AND i.status <> 'Cancelled'{inv_dates}
            ) b ON TRUE
            LEFT JOIN LATERAL (
                SELECT SUM(ip.amount) AS paid,
                       SUM(ip.amount * CASE WHEN i.total_amount > 0
                                            THEN (i.total_amount - COALESCE(i.itbis_total, 0)) / i.total_amount
                                            ELSE 1 END) AS paid_net
                FROM invoice_payments ip JOIN invoices i ON i.id = ip.invoice_id
                WHERE p.quote_id IS NOT NULL AND i.quote_id = p.quote_id{pay_dates}
            ) pay ON TRUE
            LEFT JOIN LATERAL (
                SELECT SUM(e.amount) AS expenses, COUNT(*) AS n
                FROM expenses e WHERE e.project_id = p.id{exp_dates}
            ) x ON TRUE
            WHERE 1=1
        """
        all_params = params + pay_params + exp_params
        if client_id:
            sql += " AND p.client_id = %s"
            all_params.append(client_id)
        if project_id:
            sql += " AND p.id = %s"
            all_params.append(project_id)
        sql += " ORDER BY p.id"
        cur.execute(sql, all_params)
        rows = cur.fetchall()

        ids = [r["id"] for r in rows]
        cats_by_project = {}
        if ids:
            cp = [ids]
            cur.execute(
                "SELECT e.project_id, e.category, COALESCE(SUM(e.amount), 0) AS total, COUNT(*) AS n "
                "FROM expenses e WHERE e.project_id = ANY(%s)"
                + expense_date_filter("e.date", start_date, end_date, cp)
                + " GROUP BY e.project_id, e.category",
                cp,
            )
            for r in cur.fetchall():
                cats_by_project.setdefault(r["project_id"], []).append(r)

        projects = []
        tot = {"billed": 0.0, "billed_itbis": 0.0, "billed_net": 0.0, "paid": 0.0, "paid_net": 0.0,
               "expenses": 0.0, "invoices_without_itbis": 0}
        for r in rows:
            billed = round(float(r["billed"]), 2)
            itbis = round(float(r["billed_itbis"]), 2)
            billed_net = round(billed - itbis, 2)
            paid = round(float(r["paid"]), 2)
            paid_net = round(float(r["paid_net"]), 2)
            expenses = round(float(r["expenses"]), 2)
            net = round(billed_net - expenses, 2)
            no_itbis = int(r["invoices_without_itbis"])
            projects.append({
                "project_id": r["id"],
                "project_number": f"P-{int(r['id']):04d}",
                "name": r["name"],
                "status": r["status"],
                "client_name": r["client_name"],
                "quote_label": f"Q-{r['quote_number']}" if r["quote_number"] else None,
                "billed": billed,
                "billed_itbis": itbis,
                "billed_net": billed_net,
                "paid": paid,
                "paid_net": paid_net,
                "outstanding": round(max(billed - paid, 0), 2),
                "expenses": expenses,
                "expense_count": int(r["expense_count"]),
                "net_margin": net,
                "margin_pct": round(net / billed_net * 100, 2) if billed_net else None,
                "cash_margin": round(paid_net - expenses, 2),
                "invoices_without_itbis": no_itbis,
                "expense_categories": categories_from_rows(cats_by_project.get(r["id"], []), expenses),
            })
            for k, v in (("billed", billed), ("billed_itbis", itbis), ("billed_net", billed_net), ("paid", paid),
                         ("paid_net", paid_net), ("expenses", expenses), ("invoices_without_itbis", no_itbis)):
                tot[k] += v

        billed_net_t = round(tot["billed_net"], 2)
        net_t = round(tot["billed_net"] - tot["expenses"], 2)
        return {
            "summary": {
                "project_count": len(projects),
                "margin_basis": "sin_itbis",
                "total_billed": round(tot["billed"], 2),
                "total_billed_itbis": round(tot["billed_itbis"], 2),
                "total_billed_net": billed_net_t,
                "total_paid": round(tot["paid"], 2),
                "total_paid_net": round(tot["paid_net"], 2),
                "total_expenses": round(tot["expenses"], 2),
                "net_margin": net_t,
                "margin_pct": round(net_t / billed_net_t * 100, 2) if billed_net_t else None,
                "cash_margin": round(tot["paid_net"] - tot["expenses"], 2),
                "invoices_without_itbis": tot["invoices_without_itbis"],
                "filters": {"start_date": start_date, "end_date": end_date,
                            "client_id": client_id, "project_id": project_id},
            },
            "projects": projects,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("No se pudo generar el reporte de rentabilidad", e)
    finally:
        if conn:
            conn.close()


# ============================================================
# EXPENSES BY CATEGORY (Project Cost Ledger)
# ============================================================

def get_expenses_by_category(start_date=None, end_date=None, project_id: Optional[int] = None) -> dict:
    """All expenses (or one project's) grouped by category, with assigned vs unassigned totals."""
    from projects.ledger import categories_from_rows, expense_date_filter

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        params = []
        where = " WHERE 1=1" + expense_date_filter("e.date", start_date, end_date, params)
        if project_id:
            where += " AND e.project_id = %s"
            params.append(project_id)

        cur.execute(
            "SELECT COALESCE(SUM(e.amount), 0) AS total, COUNT(*) AS n, "
            "COALESCE(SUM(e.amount) FILTER (WHERE e.project_id IS NOT NULL), 0) AS assigned, "
            "COALESCE(SUM(e.amount) FILTER (WHERE e.project_id IS NULL), 0) AS unassigned "
            "FROM expenses e" + where,
            params,
        )
        s = cur.fetchone()
        total = round(float(s["total"]), 2)
        cur.execute(
            "SELECT e.category, COALESCE(SUM(e.amount), 0) AS total, COUNT(*) AS n FROM expenses e"
            + where + " GROUP BY e.category",
            params,
        )
        return {
            "summary": {
                "total_expenses": total,
                "count": int(s["n"]),
                "assigned_to_projects": round(float(s["assigned"]), 2),
                "unassigned": round(float(s["unassigned"]), 2),
                "filters": {"start_date": start_date, "end_date": end_date, "project_id": project_id},
            },
            "categories": categories_from_rows(cur.fetchall(), total),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("No se pudo generar el reporte de gastos", e)
    finally:
        if conn:
            conn.close()


# ============================================================
# PRODUCT PROFITABILITY (Product Cost module)
# ============================================================

def get_product_profitability(only_with_cost: bool = False) -> dict:
    """Catalog margin per product: unit price, current cost, unit margin, margin % (on price).
    Products without cost are listed with margin None unless only_with_cost is set."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        sql = "SELECT id, name, description, unit_price, cost FROM products"
        if only_with_cost:
            sql += " WHERE cost IS NOT NULL"
        cur.execute(sql + " ORDER BY name, id")
        rows = cur.fetchall()
        products = []
        for r in rows:
            price = round(float(r["unit_price"] or 0), 2)
            cost = round(float(r["cost"]), 2) if r["cost"] is not None else None
            margin = round(price - cost, 2) if cost is not None else None
            products.append({
                "product_id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "unit_price": price,
                "cost": cost,
                "margin": margin,
                "margin_pct": round(margin / price * 100, 2) if margin is not None and price else None,
            })
        with_cost = [p for p in products if p["cost"] is not None]
        neg = [p for p in with_cost if p["margin"] is not None and p["margin"] < 0]
        return {
            "summary": {
                "product_count": len(products),
                "with_cost": len(with_cost),
                "without_cost": len(products) - len(with_cost),
                "negative_margin": len(neg),
                "only_with_cost": only_with_cost,
            },
            "products": products,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("No se pudo generar el reporte de productos", e)
    finally:
        if conn:
            conn.close()


# ============================================================
# PROJECT VARIANCE (Product Cost module)
# ============================================================

def get_project_variance(client_id: Optional[int] = None, project_id: Optional[int] = None) -> dict:
    """Per project: estimated cost (current product costs x quote lines), actual expenses, variance,
    estimated vs actual margin (sin ITBIS) and margin accuracy. All-time; no date filter."""
    from quotes import costing

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        sql = ("SELECT p.id, p.name, p.quote_id, p.quote_number, c.company_name AS client_name "
               "FROM projects p JOIN clients c ON c.id = p.client_id WHERE 1=1")
        params = []
        if client_id:
            sql += " AND p.client_id = %s"
            params.append(client_id)
        if project_id:
            sql += " AND p.id = %s"
            params.append(project_id)
        cur.execute(sql + " ORDER BY p.id", params)
        projects = cur.fetchall()
        estimates = {}
        for p in projects:
            if p["quote_id"]:
                e = costing.quote_estimate(cur, p["quote_id"])
                e.pop("lines", None)
                estimates[p["id"]] = e
    finally:
        if conn:
            conn.close()

    prof = {p["project_id"]: p for p in get_project_profitability(client_id=client_id, project_id=project_id)["projects"]}
    rows = []
    tot = {"estimated_cost": 0.0, "expenses": 0.0}
    for p in projects:
        e = estimates.get(p["id"])
        pr = prof.get(p["id"], {})
        billed_net = float(pr.get("billed_net") or 0)
        expenses = float(pr.get("expenses") or 0)
        actual_margin = round(billed_net - expenses, 2) if billed_net > 0 else None
        est_cost = e["estimated_cost"] if e else 0.0
        est_margin = e["estimated_margin"] if e else None
        v = costing.variance(est_cost, expenses, est_margin, actual_margin)
        rows.append({
            "project_id": p["id"],
            "project_number": f"P-{int(p['id']):04d}",
            "name": p["name"],
            "client_name": p["client_name"],
            "quote_label": f"Q-{p['quote_number']}" if p["quote_number"] else None,
            "has_quote": e is not None,
            "estimated_cost": est_cost,
            "expenses": round(expenses, 2),
            "estimated_margin": est_margin,
            "estimated_margin_pct": e["estimated_margin_pct"] if e else None,
            "billed_net": round(billed_net, 2),
            "actual_margin": actual_margin,
            "lines_total": e["lines_total"] if e else 0,
            "lines_costed": e["lines_costed"] if e else 0,
            "coverage_pct": e["coverage_pct"] if e else None,
            **v,
        })
        tot["estimated_cost"] += est_cost
        tot["expenses"] += expenses
    est_t = round(tot["estimated_cost"], 2)
    exp_t = round(tot["expenses"], 2)
    return {
        "summary": {
            "project_count": len(rows),
            "total_estimated_cost": est_t,
            "total_expenses": exp_t,
            "total_variance": round(est_t - exp_t, 2),
            "incomplete_estimates": sum(1 for r in rows if r["has_quote"] and r["lines_costed"] < r["lines_total"]),
            "filters": {"client_id": client_id, "project_id": project_id},
        },
        "projects": rows,
    }
