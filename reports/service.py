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
        raise internal_error("Revenue report failed", e)

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
