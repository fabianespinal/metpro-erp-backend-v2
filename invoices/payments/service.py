from database import get_db

def create_payment(conn, invoice_id: int, data):
    query = """
        INSERT INTO payments (invoice_id, amount, method, notes, payment_date)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id;
    """
    result = conn.execute(
        query,
        (invoice_id, data.amount, data.method, data.notes, data.payment_date)
    )
    return result.fetchone()[0]