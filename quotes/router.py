from typing import Annotated
from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, UploadFile
from fastapi.responses import StreamingResponse
from typing import List, Optional
from pydantic import BaseModel
import json

from .models import QuoteCreate, StatusUpdate, QuoteUpdate, TotalsPreviewIn, CostPreviewIn
from . import costing
from database import get_db_connection
from psycopg2.extras import RealDictCursor
from . import service
from auth.service import require_auth, require_role
from core.errors import api_error
from core.rate_limit import public_rate_limit
from pdf.builder_quote import create_quote_pdf
from pdf.utils.signer import resolve_signer_name
from core.numbering import quote_label_for
from core.dates import local_date
from core.public_payload import public_payload
from core.email_attachments import read_extra_attachments
from company_settings.service import seal_for_pdf

# Email sending
from email_service import send_quote_email
from quotes.service import calculate_quote_totals

router = APIRouter(prefix="/quotes", tags=["quotes"])


@router.post("/")
def create_quote(quote: QuoteCreate, current_user: dict = Depends(require_auth)):
    """Create a new quote"""
    items = [item.dict() for item in quote.items]
    charges = quote.included_charges.dict()

    result = service.create_quote(
        client_id=quote.client_id,
        contact_id=quote.contact_id,
        project_name=quote.project_name,
        notes=quote.notes,
        items=items,
        included_charges=charges,
        payment_terms=quote.payment_terms,
        valid_until=quote.valid_until,
        created_by_user_id=current_user.get("user_id"),
        tax_type_code=quote.tax_type_code,
        print_items=quote.print_items,
    )
    return result


@router.get("/")
def get_quotes(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(require_auth),
):
    """Get all quotes with optional filters"""
    return service.get_all_quotes(client_id, status)


PUBLIC_TOKEN_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


@router.get("/print-options")
def print_options(current_user: dict = Depends(require_auth)):
    """A3: may a line be marked "no imprimir"? Lets the screen show the control only when it is switched on."""
    from core.visibility import print_controls_enabled
    return {"print_controls_enabled": print_controls_enabled()}


@router.get("/pdf-options")
def pdf_option_flags(current_user: dict = Depends(require_auth)):
    """PDF update: which of the new controls are switched on. Lets the screens show them only when enabled."""
    from core import pdf_options
    return {
        "medidas_enabled": pdf_options.medidas_enabled(),
        "print_items_enabled": pdf_options.print_items_enabled(),
        "full_copy_enabled": pdf_options.full_copy_enabled(),
        "project_desc_enabled": pdf_options.project_desc_enabled(),
    }


@router.get("/options")
def quote_options(current_user: dict = Depends(require_auth)):
    """Phase B switches, so screens show only what is switched on."""
    from core.quote_features import blank_quotes_enabled, duplicate_change_client_enabled
    return {
        "blank_quotes_enabled": blank_quotes_enabled(),
        "duplicate_change_client_enabled": duplicate_change_client_enabled(),
    }


@router.get("/public/{token}", dependencies=[Depends(public_rate_limit)])
def get_quote_public(token: Annotated[str, Path(pattern=PUBLIC_TOKEN_PATTERN)]):
    """Public quote view. Access is by unguessable token only."""
    quote_id = service.quote_id_for_public_token(token)
    quote = service.get_quote_with_contact(quote_id)
    def _totals():
        charges = quote.get("included_charges") or {}
        if isinstance(charges, str):
            charges = json.loads(charges)
        return service.quote_document_totals(quote, quote.get("items", []), charges)

    return public_payload(quote, _totals)  # B-22: no internal ids, UUIDs or creator name. A3: hidden lines removed


@router.get("/public/{token}/pdf", dependencies=[Depends(public_rate_limit)])
def get_quote_public_pdf(token: Annotated[str, Path(pattern=PUBLIC_TOKEN_PATTERN)]):
    """Public quote PDF. Access is by unguessable token only."""
    quote_id = service.quote_id_for_public_token(token)
    quote = service.get_quote_with_contact(quote_id)

    client = {
        "company_name": quote["company_name"],
        "address":      quote.get("company_address", ""),
        "tax_id":       quote.get("company_tax_id") or "",  # B-07: client RNC on the emailed/public PDF
        "contact_name": quote.get("contact_name", ""),
        "email":        quote.get("contact_email", ""),
        "phone":        quote.get("contact_phone", ""),
    }

    raw_charges = quote.get("included_charges") or {}
    if isinstance(raw_charges, str):
        raw_charges = json.loads(raw_charges)

    items = quote.get("items", [])
    totals = service.quote_document_totals(quote, items, raw_charges)  # B-13: same totals on every PDF

    pdf_stream = create_quote_pdf(
        print_items=quote.get("print_items", True) is not False,  # PDF update: false = no item table
        doc_type="COTIZACION",
        signer_name=resolve_signer_name(None, quote.get("created_by_name")),
        doc_id=quote_label_for(quote),
        doc_date=local_date(quote.get("created_at")),
        client=client,
        project_name=quote.get("project_name", ""),
        notes=quote.get("notes", ""),
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
        tax_label=totals.get("tax_label"),
        grand_total=totals["grand_total"],
        payment_terms=quote.get("payment_terms"),
        valid_until=str(quote["valid_until"]) if quote.get("valid_until") else None,
    )

    return StreamingResponse(
        pdf_stream,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=cotizacion_{quote_label_for(quote)}.pdf"},  # B-22
    )


@router.post("/{quote_id}/send")
def send_quote(
    quote_id: str,
    files: List[UploadFile] = File(default=[]),
    print_seal: bool = Form(False),
    current_user: dict = Depends(require_auth),
):
    """Send quote PDF to client via email. Optional extra files are attached and discarded.
    print_seal=true prints the company seal on the emailed PDF (default: no seal)."""

    # Validate uploads first. Nothing is stored.
    extra_attachments = read_extra_attachments(files)
    seal = seal_for_pdf(print_seal)  # fails before anything is emailed if the seal was asked for and cannot load

    quote = service.get_quote_with_contact(quote_id)

    # Validate everything BEFORE building the PDF or emailing: status, token, contact email.
    # Drafts have no public_token. Never build a link from NULL.
    service.assert_quote_sendable(quote)

    client = {
        "company_name": quote["company_name"],
        "address": quote.get("company_address", ""),
        "tax_id": quote.get("company_tax_id") or "",  # B-07: client RNC on the emailed/public PDF
        "contact_name": quote.get("contact_name", ""),
        "email": quote.get("contact_email", ""),
        "phone": quote.get("contact_phone", ""),
    }

    raw_charges = quote.get("included_charges") or {}
    if isinstance(raw_charges, str):
        raw_charges = json.loads(raw_charges)

    items = quote.get("items", [])
    totals = service.quote_document_totals(quote, items, raw_charges)  # B-13: same totals on every PDF

    pdf_stream = create_quote_pdf(
        print_items=quote.get("print_items", True) is not False,  # PDF update: false = no item table
        doc_type="COTIZACION",
        signer_name=resolve_signer_name(current_user, quote.get("created_by_name")),
        seal=seal,
        doc_id=quote_label_for(quote),
        doc_date=local_date(quote.get("created_at")),
        client=client,
        project_name=quote.get("project_name", ""),
        notes=quote.get("notes", ""),
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
        tax_label=totals.get("tax_label"),
        grand_total=totals["grand_total"],
        payment_terms=quote.get("payment_terms"),
        valid_until=str(quote["valid_until"]) if quote.get("valid_until") else None,
    )

    pdf_bytes = pdf_stream.read()

    send_quote_email(
        contact_email=quote["contact_email"],
        contact_name=quote["contact_name"],
        company_name=quote["company_name"],
        project_name=quote.get("project_name", ""),
        quote_id=str(quote["quote_number"]),  # printed number, never the UUID
        public_token=str(quote["public_token"]),
        pdf_bytes=pdf_bytes,
        extra_attachments=extra_attachments,
    )

    # Final -> Sent. Sent and Approved keep their status. Cannot fail on transition rules.
    new_status = service.mark_quote_sent(quote_id, current_user.get("user_id"))

    return {"message": "Cotización enviada exitosamente", "quote_id": quote_id, "status": new_status}


@router.get("/{quote_id}/status-history")
def get_quote_status_history(quote_id: str, current_user: dict = Depends(require_auth)):
    """Every status change: who and when. Any signed-in user can read it."""
    return service.get_quote_status_history(quote_id)


@router.get("/{quote_id}")
def get_quote(quote_id: str, current_user: dict = Depends(require_auth)):
    """Get a single quote"""
    return service.get_quote_by_id(quote_id)


@router.get("/{quote_id}/pdf")
def get_quote_pdf(quote_id: str, print_seal: bool = False, current_user: dict = Depends(require_auth)):
    """Generate and stream a quote PDF. print_seal=true adds the company seal (default: no seal)."""
    seal = seal_for_pdf(print_seal)

    quote = service.get_quote_with_contact(quote_id)

    client = {
        "company_name": quote["company_name"],
        "address": quote.get("company_address", ""),
        "tax_id": quote.get("company_tax_id") or "",  # B-07: client RNC on the emailed/public PDF
        "contact_name": quote.get("contact_name", ""),
        "email": quote.get("contact_email", ""),
        "phone": quote.get("contact_phone", ""),
    }

    raw_charges = quote.get("included_charges") or {}
    if isinstance(raw_charges, str):
        raw_charges = json.loads(raw_charges)

    items = quote.get("items", [])
    totals = service.quote_document_totals(quote, items, raw_charges)  # B-13: same totals on every PDF

    pdf_stream = create_quote_pdf(
        print_items=quote.get("print_items", True) is not False,  # PDF update: false = no item table
        doc_type="COTIZACION",
        signer_name=resolve_signer_name(current_user, quote.get("created_by_name")),
        seal=seal,
        doc_id=quote_label_for(quote),
        doc_date=local_date(quote.get("created_at")),
        client=client,
        project_name=quote.get("project_name", ""),
        notes=quote.get("notes", ""),
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
        tax_label=totals.get("tax_label"),
        grand_total=totals["grand_total"],
        payment_terms=quote.get("payment_terms"),
        valid_until=str(quote["valid_until"]) if quote.get("valid_until") else None,
    )

    return StreamingResponse(
        pdf_stream,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={quote_label_for(quote)}_cotizacion.pdf"}  # E-11: same name as the other PDF paths,
    )


@router.post("/totals/preview")
def preview_quote_totals(body: TotalsPreviewIn, current_user: dict = Depends(require_auth)):
    """Totals for a draft selection. Stateless. Same math as save and finalize."""
    items = [item.dict() for item in body.items]
    charges = body.included_charges.dict()
    return service.preview_totals(items, charges, body.tax_type_code)


@router.post("/cost-estimate/preview")
def preview_cost_estimate(body: CostPreviewIn, current_user: dict = Depends(require_auth)):
    """Costo estimado y margen estimado de líneas sin guardar. No afecta el total de la cotización."""
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        return costing.preview_estimate(cur, [i.dict() for i in body.items], body.included_charges.dict())
    finally:
        conn.close()


@router.get("/{quote_id}/cost-estimate")
def get_cost_estimate(quote_id: str, current_user: dict = Depends(require_auth)):
    """Costo estimado y margen estimado de una cotización guardada. Solo lectura."""
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        return costing.quote_estimate(cur, quote_id)
    finally:
        conn.close()


@router.post("/draft")
def create_draft_quote(quote: QuoteCreate, current_user: dict = Depends(require_auth)):
    """Create a Draft quote. Alias of POST /quotes/ (same code path). public_token stays NULL."""
    return create_quote(quote, current_user)


@router.post("/{quote_id}/finalize")
def finalize_quote(quote_id: str, current_user: dict = Depends(require_auth)):
    """Draft -> Final. Persists totals and generates the public_token."""
    return service.finalize_quote(quote_id, current_user.get("user_id"))


@router.put("/{quote_id}")
def update_quote(
    quote_id: str,
    quote_update: QuoteUpdate,
    current_user: dict = Depends(require_auth),
):
    """Update an existing quote"""
    return service.update_quote(quote_id, quote_update, actor=current_user)


@router.patch("/{quote_id}/status")
def update_quote_status(
    quote_id: str,
    status_update: StatusUpdate,
    current_user: dict = Depends(require_auth),
):
    """Update quote status"""
    return service.update_quote_status(quote_id, status_update.status, current_user.get("user_id"))


class DuplicateQuoteIn(BaseModel):
    """B1: optional target. No body = the same client and contact, as before."""
    client_id: Optional[int] = None
    contact_id: Optional[int] = None


@router.post("/{quote_id}/duplicate")
def duplicate_quote(quote_id: str, body: Optional[DuplicateQuoteIn] = None, current_user: dict = Depends(require_auth)):
    """Duplicate an existing quote, optionally for another client or contact (B1, switch DUPLICATE_CHANGE_CLIENT_ENABLED)."""
    return service.duplicate_quote(
        quote_id,
        current_user.get("user_id"),
        client_id=body.client_id if body else None,
        contact_id=body.contact_id if body else None,
    )


@router.post("/{quote_id}/convert-to-invoice")
def convert_to_invoice(quote_id: str, current_user: dict = Depends(require_auth)):
    """Convert approved quote to invoice"""
    invoice = service.convert_quote_to_invoice(quote_id, current_user.get("user_id"))
    return {
        "invoice_id": invoice["id"],
        "invoice_number": invoice["invoice_number"],
        "quote_id": invoice["quote_id"],
        "client_id": invoice["client_id"],
        "total_amount": invoice["total_amount"],
        "status": invoice["status"],
        "invoice_date": invoice["invoice_date"],
        "message": f"Cotización {quote_id} convertida en la factura {invoice['invoice_number']}",
    }


@router.delete("/{quote_id}")
def delete_quote(quote_id: str, _admin: dict = Depends(require_role("admin"))):
    """Delete a quote"""
    return service.delete_quote(quote_id, _admin.get("user_id"))