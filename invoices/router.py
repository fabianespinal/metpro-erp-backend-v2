from core.errors import api_error
import json
import base64

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from typing import Annotated, List, Optional

from .models import Invoice, InvoiceCreate, InvoiceStatusUpdate
from . import service
from auth.service import require_auth, require_role
from core.rate_limit import public_rate_limit

from invoices.payments.models import PaymentCreate
from invoices.payments.service import create_payment, get_payments_for_invoice
from core.errors import internal_error

from database import get_db_connection
from psycopg2.extras import RealDictCursor

from email_service import send_invoice_email
from invoices.service import calculate_invoice_totals
from pdf.builder_invoice import create_invoice_pdf

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.post("/", response_model=Invoice)
def create_invoice(invoice: InvoiceCreate, current_user: dict = Depends(require_auth)):
    result = service.create_invoice_from_quote(invoice.quote_id, invoice.notes, current_user.get("user_id"))
    return Invoice(**result)


@router.get("/", response_model=List[Invoice])
def get_invoices(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(require_auth),
):
    invoices = service.get_all_invoices(client_id, status)
    return [Invoice(**inv) for inv in invoices]


@router.post("/{invoice_id}/send")
def send_invoice(invoice_id: int, current_user: dict = Depends(require_auth)):
    """Send invoice PDF to client via email"""

    invoice = service.get_invoice_with_contact(invoice_id)
    if not invoice:
        raise api_error(404, "Invoice not found", "INVOICE_NOT_FOUND")

    client = {
        "company_name": invoice["company_name"],
        "address": invoice.get("company_address", ""),
        "contact_name": invoice.get("contact_name", ""),
        "email": invoice.get("contact_email", ""),
        "phone": invoice.get("contact_phone", ""),
    }

    raw_charges = invoice.get("included_charges") or {}
    if isinstance(raw_charges, str):
        raw_charges = json.loads(raw_charges)

    items = invoice.get("items", [])
    totals = calculate_invoice_totals(items, raw_charges)

    # ---- NEW: fetch payments for this invoice so Historial de Pagos is populated ----
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT * FROM invoice_payments WHERE invoice_id = %s ORDER BY id ASC",
            (invoice_id,),
        )
        payments = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
    # -------------------------------------------------------------------------------

    pdf_stream = create_invoice_pdf(
        doc_type="FACTURA",
        doc_id=invoice["invoice_number"],
        doc_date=str(invoice["invoice_date"])[:10] if invoice.get("invoice_date") else "",
        client=client,
        project_name=invoice.get("project_name", ""),
        notes=invoice.get("notes", ""),
        items=items,
        charges=raw_charges,
        items_total=totals["items_total"],
        total_discounts=totals["total_discounts"],
        items_after_discount=totals["items_after_discount"],
        supervision=totals["supervision"],
        supervision_pct=raw_charges.get("supervision_percentage", 10.0),
        admin=totals["admin"],
        admin_pct=raw_charges.get("admin_percentage", 4.0),
        insurance=totals["insurance"],
        insurance_pct=raw_charges.get("insurance_percentage", 1.0),
        transport=totals["transport"],
        transport_pct=raw_charges.get("transport_percentage", 3.0),
        contingency=totals["contingency"],
        contingency_pct=raw_charges.get("contingency_percentage", 3.0),
        subtotal_general=totals["subtotal_general"],
        itbis=totals["itbis"],
        grand_total=totals["grand_total"],
        payment_terms=None,
        valid_until=None,
        amount_paid=invoice.get("amount_paid", 0),
        amount_due=invoice.get("amount_due", 0),
        payments=payments,  # ✅ now the PDF has the full payment history
    )

    pdf_bytes = pdf_stream.read()

    send_invoice_email(
        contact_email=invoice["contact_email"],
        contact_name=invoice["contact_name"],
        company_name=invoice["company_name"],
        project_name=invoice.get("project_name", ""),
        invoice_id=str(invoice["id"]),
        public_token=str(invoice["public_token"]),
        pdf_bytes=pdf_bytes,
    )

    return {"message": "Factura enviada exitosamente", "invoice_id": invoice_id}


@router.get("/{invoice_id}", response_model=Invoice)
def get_invoice(invoice_id: int, current_user: dict = Depends(require_auth)):
    result = service.get_invoice_by_id(invoice_id)
    return Invoice(**result)


@router.get("/number/{invoice_number}", response_model=Invoice)
def get_invoice_by_number(invoice_number: str, current_user: dict = Depends(require_auth)):
    result = service.get_invoice_by_number(invoice_number)
    return Invoice(**result)


@router.patch("/{invoice_id}/status", response_model=Invoice)
def update_invoice_status(
    invoice_id: int,
    status_update: InvoiceStatusUpdate,
    _admin: dict = Depends(require_role("admin")),
):
    """Manual status change. Admin only. Paid is reached by recording payments."""
    result = service.update_invoice_status(invoice_id, status_update.status)
    return Invoice(**result)


@router.delete("/{invoice_id}")
def delete_invoice(invoice_id: int, _admin: dict = Depends(require_role("admin"))):
    return service.delete_invoice(invoice_id)


@router.post("/{invoice_id}/payments")
def add_payment(invoice_id: int, data: PaymentCreate, current_user: dict = Depends(require_auth)):
    conn = get_db_connection()
    try:
        payment_id = create_payment(conn, invoice_id, data)
        return {"payment_id": payment_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise internal_error("Failed to record payment", e)
    finally:
        conn.close()


@router.get("/{invoice_id}/payments")
def list_payments(invoice_id: int, current_user: dict = Depends(require_auth)):
    """Payments for one invoice, oldest first. 404 if the invoice does not exist."""
    service.get_invoice_by_id(invoice_id)  # raises 404 when missing
    conn = get_db_connection()
    try:
        return get_payments_for_invoice(conn, invoice_id)
    finally:
        conn.close()


# ============================================================
# PUBLIC INVOICE VIEW (no auth, unguessable UUID4 token)
# Sequential invoice IDs are NOT exposed publicly.
# ============================================================

PUBLIC_TOKEN_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def _invoice_id_for_public_token(token: str) -> int:
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id FROM invoices WHERE public_token = %s", (token,))
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        raise api_error(404, "Invoice not found", "INVOICE_NOT_FOUND")
    return row["id"]


@router.get("/public/{token}", dependencies=[Depends(public_rate_limit)])
def get_public_invoice(token: Annotated[str, Path(pattern=PUBLIC_TOKEN_PATTERN)]):
    """Public invoice view. Access is by unguessable token only."""
    invoice_id = _invoice_id_for_public_token(token)
    invoice = service.get_invoice_with_contact(invoice_id)
    invoice.pop("public_token", None)  # never echo the token back
    return invoice


def _render_public_invoice_pdf(invoice_id: int) -> Response:
    invoice = service.get_invoice_with_contact(invoice_id)

    raw_charges = invoice.get("included_charges") or {}
    if isinstance(raw_charges, str):
        raw_charges = json.loads(raw_charges)

    items = invoice.get("items", [])
    totals = calculate_invoice_totals(items, raw_charges)

    # Payment history so the public PDF matches the internal download.
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT * FROM invoice_payments WHERE invoice_id = %s ORDER BY id ASC",
            (invoice_id,),
        )
        payments = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    pdf_stream = create_invoice_pdf(
        doc_type="FACTURA",
        doc_id=invoice["invoice_number"],
        doc_date=str(invoice["invoice_date"])[:10] if invoice.get("invoice_date") else "",
        client={
            "company_name": invoice["company_name"],
            "address": invoice.get("company_address", ""),
            "contact_name": invoice.get("contact_name", ""),
            "email": invoice.get("contact_email", ""),
            "phone": invoice.get("contact_phone", ""),
        },
        project_name=invoice.get("project_name", ""),
        notes=invoice.get("notes", ""),
        items=items,
        charges=raw_charges,
        items_total=totals["items_total"],
        total_discounts=totals["total_discounts"],
        items_after_discount=totals["items_after_discount"],
        supervision=totals["supervision"],
        supervision_pct=raw_charges.get("supervision_percentage", 10.0),
        admin=totals["admin"],
        admin_pct=raw_charges.get("admin_percentage", 4.0),
        insurance=totals["insurance"],
        insurance_pct=raw_charges.get("insurance_percentage", 1.0),
        transport=totals["transport"],
        transport_pct=raw_charges.get("transport_percentage", 3.0),
        contingency=totals["contingency"],
        contingency_pct=raw_charges.get("contingency_percentage", 3.0),
        subtotal_general=totals["subtotal_general"],
        itbis=totals["itbis"],
        grand_total=totals["grand_total"],
        payment_terms=None,
        valid_until=None,
        amount_paid=invoice.get("amount_paid", 0),
        amount_due=invoice.get("amount_due", 0),
        payments=payments,
    )

    pdf_bytes = pdf_stream.read()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=factura_{invoice_id}.pdf"
        },
    )


@router.get("/public/{token}/pdf", dependencies=[Depends(public_rate_limit)])
def get_public_invoice_pdf(token: Annotated[str, Path(pattern=PUBLIC_TOKEN_PATTERN)]):
    """Public PDF download. Access is by unguessable token only."""
    invoice_id = _invoice_id_for_public_token(token)
    return _render_public_invoice_pdf(invoice_id)
