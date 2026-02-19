from psycopg2.extras import RealDictCursor


def create_payment(conn, invoice_id: int, data):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        # Insert the payment
        cursor.execute("""
            INSERT INTO invoice_payments (invoice_id, amount, method, notes, payment_date)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (invoice_id, data.amount, data.method, data.notes, data.payment_date))
        payment_id = cursor.fetchone()["id"]

        # Recalculate total paid from all payments
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) AS total_paid
            FROM invoice_payments
            WHERE invoice_id = %s
        """, (invoice_id,))
        total_paid = float(cursor.fetchone()["total_paid"])

        # Get invoice total
        cursor.execute("SELECT total_amount FROM invoices WHERE id = %s", (invoice_id,))
        invoice = cursor.fetchone()
        total_amount = float(invoice["total_amount"])
        amount_due = total_amount - total_paid

        # Update invoice with new paid/due amounts and status
        if amount_due <= 0:
            new_status = "Paid"
        else:
            new_status = "Pending"

        cursor.execute("""
            UPDATE invoices
            SET amount_paid = %s,
                amount_due = %s,
                status = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (total_paid, amount_due, new_status, invoice_id))

        conn.commit()
        return payment_id


def get_payments_for_invoice(conn, invoice_id: int):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("""
            SELECT * FROM invoice_payments WHERE invoice_id = %s ORDER BY id ASC
        """, (invoice_id,))
        return cursor.fetchall()
