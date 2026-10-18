from core.errors import api_error
from fastapi import HTTPException
from .models import ExpenseCreate, ExpenseUpdate


def _resolve_client_name(conn, client_id):
    """
    Look up clients.company_name for a client_id.
    Returns None when client_id is not provided.
    Raises 404 when client_id does not exist.

    get_db_connection() uses RealDictCursor, so rows are dicts.
    """
    if client_id is None:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT company_name FROM clients WHERE id = %s", (client_id,))
        row = cur.fetchone()
    if not row:
        raise api_error(404, "Cliente no encontrado", "CLIENT_NOT_FOUND")
    if isinstance(row, dict):
        return row.get("company_name")
    return row[0]


def create_expense(conn, expense: ExpenseCreate):
    # Two frontends are live:
    #   - main frontend sends client_name (free text)
    #   - dev frontend sends client_id (select from clients)
    # client_id, when present, is resolved and wins. Otherwise client_name is used.
    client_name = _resolve_client_name(conn, expense.client_id) or expense.client_name

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO expenses
            (date, category, client_name, description, amount, payment_method, project_id, quote_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING expense_id;
        """, (
            expense.date,
            expense.category,
            client_name,
            expense.description,
            expense.amount,
            expense.payment_method,
            str(expense.project_id) if expense.project_id else None,
            str(expense.quote_id) if expense.quote_id else None,
        ))

        row = cur.fetchone()

    if isinstance(row, dict):
        return row["expense_id"]
    if row:
        return row[0]
    raise api_error(500, "No se pudo registrar el gasto", "EXPENSE_INSERT_FAILED")


def get_expenses(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM expenses ORDER BY created_at DESC;")
        return cur.fetchall()


def get_expense(conn, expense_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM expenses WHERE expense_id = %s;", (expense_id,))
        return cur.fetchone()


def update_expense(conn, expense_id: int, data: ExpenseUpdate):
    fields = []
    values = []

    for key, value in data.dict(exclude_unset=True).items():
        fields.append(f"{key} = %s")
        values.append(value)

    if not fields:
        return False

    values.append(expense_id)

    with conn.cursor() as cur:
        cur.execute(f"""
            UPDATE expenses
            SET {', '.join(fields)}
            WHERE expense_id = %s;
        """, values)
        return True


def delete_expense(conn, expense_id: int):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM expenses WHERE expense_id = %s;", (expense_id,))
        return True
