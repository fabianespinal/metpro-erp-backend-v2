"""Invoice payments.

Every query here filters invoice_payments by invoice_id (the foreign key),
never by invoice_payments.id (the payment's own primary key).
"""
from psycopg2.extras import RealDictCursor

from core.errors import api_error

# Invoices that may receive a payment. Paid and Cancelled are closed.
PAYABLE_STATUSES = ("Pending", "Overdue", "Draft")

# Half a cent. Absorbs float rounding when comparing money amounts.
CENT_TOLERANCE = 0.005


def _round2(value: float) -> float:
    return round(float(value), 2)


def create_payment(conn, invoice_id: int, data) -> int:
    """
    Record one payment and recompute the invoice balance from all of its payments.

    Rules:
    - amount must be > 0.
    - The invoice must exist and be Pending, Overdue (or legacy Draft).
    - amount may not exceed the amount still due.
    - amount_paid = SUM(payments for this invoice); amount_due = total_amount - amount_paid.
    - Status becomes Paid when nothing is due. Otherwise the current status is kept,
      so an Overdue invoice stays Overdue after a partial payment.

    The invoice row is locked (FOR UPDATE) so concurrent payments serialize.
    The caller owns the connection; this function commits on success.
    """
    amount = float(data.amount or 0)
    if amount <= 0:
        raise api_error(400, "El monto del pago debe ser mayor que cero", "PAYMENT_AMOUNT_INVALID")

    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            "SELECT id, status, total_amount FROM invoices WHERE id = %s FOR UPDATE",
            (invoice_id,),
        )
        invoice = cursor.fetchone()
        if not invoice:
            raise api_error(404, "Factura no encontrada", "INVOICE_NOT_FOUND")

        status = invoice["status"]
        if status not in PAYABLE_STATUSES:
            raise api_error(400, f"No se aceptan pagos para facturas en estado {status}", "INVOICE_NOT_PAYABLE")

        total_amount = float(invoice["total_amount"] or 0)

        cursor.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total_paid FROM invoice_payments WHERE invoice_id = %s",
            (invoice_id,),
        )
        paid_before = float(cursor.fetchone()["total_paid"])
        due_before = total_amount - paid_before

        if amount > due_before + CENT_TOLERANCE:
            raise api_error(400, "El pago excede el monto pendiente", "PAYMENT_EXCEEDS_DUE")

        cursor.execute(
            """
            INSERT INTO invoice_payments (invoice_id, amount, method, notes, payment_date)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (invoice_id, amount, data.method, data.notes, data.payment_date),
        )
        payment_id = cursor.fetchone()["id"]

        total_paid = _round2(paid_before + amount)
        amount_due = _round2(total_amount - total_paid)
        if amount_due <= CENT_TOLERANCE:
            amount_due = 0.0
            new_status = "Paid"
        else:
            new_status = "Pending" if status == "Draft" else status

        cursor.execute(
            """
            UPDATE invoices
            SET amount_paid = %s,
                amount_due = %s,
                status = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (total_paid, amount_due, new_status, invoice_id),
        )

    conn.commit()
    return payment_id


def get_payments_for_invoice(conn, invoice_id: int):
    """All payments for one invoice, oldest first."""
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            "SELECT id, invoice_id, amount, method, notes, payment_date "
            "FROM invoice_payments WHERE invoice_id = %s ORDER BY payment_date ASC, id ASC",
            (invoice_id,),
        )
        return [dict(r) for r in cursor.fetchall()]
