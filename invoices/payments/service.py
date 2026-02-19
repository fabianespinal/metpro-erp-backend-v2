from psycopg2.extras import RealDictCursor

def create_payment(conn, invoice_id: int, data):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("""
            INSERT INTO invoice_payments (invoice_id, amount, method, notes, payment_date)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (invoice_id, data.amount, data.method, data.notes, data.payment_date))
        conn.commit()
        return cursor.fetchone()["id"]


def get_payments_for_invoice(conn, invoice_id: int):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("""
            SELECT * FROM invoice_payments WHERE invoice_id = %s ORDER BY id ASC
        """, (invoice_id,))
        return cursor.fetchall()