from .models import ExpenseCreate, ExpenseUpdate

def create_expense(conn, expense: ExpenseCreate):
    with conn.cursor() as cur:
        try:
            cur.execute("""
            INSERT INTO expenses
            (date, category, description, amount, payment_method, project_id, quote_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING expense_id;
            """, (
                expense.date,
                expense.category,
                expense.description,
                expense.amount,
                expense.payment_method,
                str(expense.project_id) if expense.project_id else None,
                str(expense.quote_id) if expense.quote_id else None
            ))
            row = cur.fetchone()
            
            # Handle both dict and tuple cursor types
            if isinstance(row, dict):
                return row['expense_id']
            elif row:
                return row[0]
            else:
                raise Exception("Insert failed to return ID")
                
        except Exception as e:
            print("🔥 REAL SQL ERROR:", e)
            raise


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