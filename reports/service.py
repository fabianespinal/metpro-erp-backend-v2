from typing import Optional
from fastapi import HTTPException
from database import get_db_connection
from psycopg2.extras import RealDictCursor


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

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT 
                q.status,
                COALESCE(SUM(q.total_amount), 0) AS total_revenue,
                COUNT(*) AS quote_count
            FROM quotes q
            WHERE q.status IN ('Approved', 'Invoiced')
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

        query += " GROUP BY q.status ORDER BY q.status"

        cursor.execute(query, params)
        results = cursor.fetchall()

        approved = next((r for r in results if r["status"] == "Approved"),
                        {"total_revenue": 0, "quote_count": 0})

        invoiced = next((r for r in results if r["status"] == "Invoiced"),
                        {"total_revenue": 0, "quote_count": 0})

        return {
            "summary": {
                "filters": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "client_id": client_id
                }
            },
            "revenue_breakdown": [
                {
                    "status": "Approved (Ready to Invoice)",
                    "total_revenue": float(approved["total_revenue"]),
                    "quote_count": approved["quote_count"]
                },
                {
                    "status": "Invoiced (Realized Revenue)",
                    "total_revenue": float(invoiced["total_revenue"]),
                    "quote_count": invoiced["quote_count"]
                }
            ],
            "grand_total": float(approved["total_revenue"] + invoiced["total_revenue"])
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Revenue report failed: {str(e)[:100]}")

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