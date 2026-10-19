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
    amount = _round2(data.amount or 0)  # debug B-23: amounts are stored with 2 decimals
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
            "SELECT COALESCE(SUM(amount), 0) AS total_paid FROM invoice_payments "
            "WHERE invoice_id = %s AND voided_at IS NULL",
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
            "SELECT id, invoice_id, amount, method, notes, payment_date, voided_at, void_reason "
            "FROM invoice_payments WHERE invoice_id = %s ORDER BY payment_date ASC, id ASC",
            (invoice_id,),
        )
        return [dict(r) for r in cursor.fetchall()]


def payment_void_enabled() -> bool:
    """Toggle for B-14. PAYMENT_VOID_ENABLED=false hides the action (404)."""
    import os
    return os.environ.get("PAYMENT_VOID_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def void_payment(conn, invoice_id: int, payment_id: int, reason: str, user_id=None) -> dict:
    """Void one payment (debug B-14). The row is kept; balances are recomputed without it.

    - The invoice row is locked first, like create_payment, so voids and payments serialize.
    - Paid -> Pending when money is due again. Other statuses are kept.
    """
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise api_error(400, "Indique el motivo de la anulación", "PAYMENT_VOID_REASON_REQUIRED")
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT id, status, total_amount FROM invoices WHERE id = %s FOR UPDATE", (invoice_id,))
        invoice = cursor.fetchone()
        if not invoice:
            raise api_error(404, "Factura no encontrada", "INVOICE_NOT_FOUND")
        cursor.execute(
            "SELECT id, voided_at FROM invoice_payments WHERE invoice_id = %s AND id = %s",
            (invoice_id, payment_id),
        )
        payment = cursor.fetchone()
        if not payment:
            raise api_error(404, "Pago no encontrado", "PAYMENT_NOT_FOUND")
        if payment["voided_at"] is not None:
            raise api_error(400, "El pago ya está anulado", "PAYMENT_ALREADY_VOIDED")

        cursor.execute(
            "UPDATE invoice_payments SET voided_at = now(), void_reason = %s, voided_by_user_id = %s "
            "WHERE invoice_id = %s AND id = %s",
            (reason, user_id, invoice_id, payment_id),
        )
        cursor.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total_paid FROM invoice_payments "
            "WHERE invoice_id = %s AND voided_at IS NULL",
            (invoice_id,),
        )
        total_paid = _round2(cursor.fetchone()["total_paid"])
        amount_due = _round2(float(invoice["total_amount"] or 0) - total_paid)
        status = invoice["status"]
        new_status = "Pending" if status == "Paid" and amount_due > CENT_TOLERANCE else status
        cursor.execute(
            "UPDATE invoices SET amount_paid = %s, amount_due = %s, status = %s, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = %s",
            (total_paid, max(amount_due, 0.0), new_status, invoice_id),
        )
    conn.commit()
    return {"payment_id": payment_id, "amount_paid": total_paid, "amount_due": max(amount_due, 0.0), "status": new_status}
