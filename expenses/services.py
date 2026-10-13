from fastapi import HTTPException
from .models import ExpenseCreate, ExpenseUpdate

def _resolve_client_name(conn, client_id):
    """Look up clients.company_name for a client_id. None if no client_id."""
    if client_id is None:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT company_name FROM clients WHERE id = %s", (client_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Client not found")
    return row[0]

def create_expense(conn, expense: ExpenseCreate):
    client_name = _resolve_client_name(conn, expense.client_id)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO expenses 
            (client_name, date, category, description, amount, payment_method, project_id, quote_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING expense_id;
        """, (
            client_name,
            expense.date,
            expense.category,
            expense.description,
            expense.amount,
            expense.payment_method,
            expense.project_id,
            expense.quote_id
        ))
        return cur.fetchone()[0]


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
