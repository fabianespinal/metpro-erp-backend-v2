from core.errors import api_error
import json
import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Response, UploadFile
from typing import Annotated, List, Optional

from .models import Invoice, InvoiceCreate, InvoiceStatusUpdate
from . import service
from auth.service import require_auth, require_role, _allowed_roles
from core.rate_limit import public_rate_limit
from core.email_attachments import read_extra_attachments
from core.public_payload import public_payload

from invoices.payments.models import PaymentCreate
from invoices.payments.service import create_payment, get_payments_for_invoice, void_payment, payment_void_enabled
from pydantic import BaseModel
from core.errors import internal_error

from database import get_db_connection
from psycopg2.extras import RealDictCursor

from email_service import send_invoice_email
from invoices.service import calculate_invoice_totals
from pdf.builder_invoice import create_invoice_pdf
from pdf.utils.signer import resolve_signer_name
from company_settings.service import seal_for_pdf

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
def send_invoice(
    invoice_id: int,
    files: List[UploadFile] = File(default=[]),
    print_seal: bool = Form(False),
    current_user: dict = Depends(require_auth),
):
    """Send invoice PDF to client via email. Optional extra files are attached and discarded.
    print_seal=true prints the company seal on the emailed PDF (default: no seal)."""

    # Validate uploads first. Nothing is stored.
    extra_attachments = read_extra_attachments(files)
    seal = seal_for_pdf(print_seal)  # fails before anything is emailed if the seal was asked for and cannot load

    invoice = service.get_invoice_with_contact(invoice_id)
    if not invoice:
        raise api_error(404, "Factura no encontrada", "INVOICE_NOT_FOUND")
    # Debug B-10: checked before any PDF is built or email is sent (same order as quotes).
    if invoice.get("status") == "Cancelled":
        raise api_error(400, "No se puede enviar una factura cancelada", "INVOICE_CANCELLED")
    if not invoice.get("contact_email"):
        raise api_error(400, "El contacto de la factura no tiene correo electrónico", "INVOICE_NO_CONTACT_EMAIL")

    client = {
        "company_name": invoice["company_name"],
        "address": invoice.get("company_address", ""),
        "tax_id": invoice.get("company_tax_id") or "",  # B-07: client RNC on the emailed PDF
        "contact_name": invoice.get("contact_name", ""),
        "email": invoice.get("contact_email", ""),
        "phone": invoice.get("contact_phone", ""),
    }

    raw_charges = invoice.get("included_charges") or {}
    if isinstance(raw_charges, str):
        raw_charges = json.loads(raw_charges)

    # F2: lines from invoice_items; grand total = billed invoices.total_amount.
    items, totals = service.invoice_lines_and_totals(invoice, raw_charges)

    # ---- NEW: fetch payments for this invoice so Historial de Pagos is populated ----
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT * FROM invoice_payments WHERE invoice_id = %s AND voided_at IS NULL ORDER BY id ASC",
            (invoice_id,),
        )
        payments = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
    # -------------------------------------------------------------------------------

    pdf_stream = create_invoice_pdf(
        doc_type="FACTURA",
        signer_name=resolve_signer_name(current_user, invoice.get("created_by_name")),
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
        payment_terms=invoice.get("payment_terms") or None,
        valid_until=str(invoice["valid_until"]) if invoice.get("valid_until") else None,
        amount_paid=sum(float(pm.get("amount") or 0) for pm in payments),
        amount_due=round(float(totals["grand_total"]) - sum(float(pm.get("amount") or 0) for pm in payments), 2),
        payments=payments,  # ✅ now the PDF has the full payment history
        seal=seal,
    )

    pdf_bytes = pdf_stream.read()

    send_invoice_email(
        contact_email=invoice["contact_email"],
        contact_name=invoice["contact_name"],
        company_name=invoice["company_name"],
        project_name=invoice.get("project_name", ""),
        invoice_id=str(invoice["invoice_number"]),  # printed number, not the DB id
        public_token=str(invoice["public_token"]),
        pdf_bytes=pdf_bytes,
        extra_attachments=extra_attachments,
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
        raise internal_error("No se pudo registrar el pago", e)
    finally:
        conn.close()


class PaymentVoidIn(BaseModel):
    reason: str


@router.post("/{invoice_id}/payments/{payment_id}/void")
def void_invoice_payment(
    invoice_id: int,
    payment_id: int,
    body: PaymentVoidIn,
    current_user: dict = Depends(require_auth),
):
    """Anular un pago registrado por error (admin). El registro se conserva; los saldos se recalculan."""
    if not payment_void_enabled():
        raise api_error(404, "No disponible", "NOT_FOUND")
    if current_user.get("role") not in _allowed_roles("admin"):  # admin and superadmin, as require_role("admin")
        raise api_error(403, "Permisos insuficientes", "INSUFFICIENT_PERMISSIONS")
    conn = get_db_connection()
    try:
        return void_payment(conn, invoice_id, payment_id, body.reason, current_user.get("user_id"))
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise internal_error("No se pudo anular el pago", e)
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
        raise api_error(404, "Factura no encontrada", "INVOICE_NOT_FOUND")
    return row["id"]


@router.get("/public/{token}", dependencies=[Depends(public_rate_limit)])
def get_public_invoice(token: Annotated[str, Path(pattern=PUBLIC_TOKEN_PATTERN)]):
    """Public invoice view. Access is by unguessable token only."""
    invoice_id = _invoice_id_for_public_token(token)
    invoice = service.get_invoice_with_contact(invoice_id)
    return public_payload(invoice)  # B-22: no internal ids, UUIDs, token or creator name


def _render_public_invoice_pdf(invoice_id: int) -> Response:
    invoice = service.get_invoice_with_contact(invoice_id)

    raw_charges = invoice.get("included_charges") or {}
    if isinstance(raw_charges, str):
        raw_charges = json.loads(raw_charges)

    # F2: lines from invoice_items; grand total = billed invoices.total_amount.
    items, totals = service.invoice_lines_and_totals(invoice, raw_charges)

    # Payment history so the public PDF matches the internal download.
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT * FROM invoice_payments WHERE invoice_id = %s AND voided_at IS NULL ORDER BY id ASC",
            (invoice_id,),
        )
        payments = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    pdf_stream = create_invoice_pdf(
        doc_type="FACTURA",
        signer_name=resolve_signer_name(None, invoice.get("created_by_name")),
        doc_id=invoice["invoice_number"],
        doc_date=str(invoice["invoice_date"])[:10] if invoice.get("invoice_date") else "",
        client={
            "company_name": invoice["company_name"],
            "address": invoice.get("company_address", ""),
            "tax_id": invoice.get("company_tax_id") or "",  # B-07: client RNC on the public PDF
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
        payment_terms=invoice.get("payment_terms") or None,
        valid_until=str(invoice["valid_until"]) if invoice.get("valid_until") else None,
        amount_paid=sum(float(pm.get("amount") or 0) for pm in payments),
        amount_due=round(float(totals["grand_total"]) - sum(float(pm.get("amount") or 0) for pm in payments), 2),
        payments=payments,
    )

    pdf_bytes = pdf_stream.read()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=factura_{invoice['invoice_number']}.pdf"  # B-22
        },
    )


@router.get("/public/{token}/pdf", dependencies=[Depends(public_rate_limit)])
def get_public_invoice_pdf(token: Annotated[str, Path(pattern=PUBLIC_TOKEN_PATTERN)]):
    """Public PDF download. Access is by unguessable token only."""
    invoice_id = _invoice_id_for_public_token(token)
    return _render_public_invoice_pdf(invoice_id)
