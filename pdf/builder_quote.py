import io
from pdf.utils.layout_utils import build_quote_invoice_pdf

def create_quote_pdf(
    doc_type,
    doc_id,
    doc_date,
    client,
    project_name,
    notes,
    items,
    charges,
    items_total,
    total_discounts,
    items_after_discount,
    supervision,
    supervision_pct,
    admin,
    admin_pct,
    insurance,
    insurance_pct,
    transport,
    transport_pct,
    contingency,
    contingency_pct,
    subtotal_general,
    itbis,
    grand_total,

    payment_terms=None,
    valid_until=None
):
    """Generate PDF bytes for a quote."""

    pdf = build_quote_invoice_pdf(
        doc_type=doc_type,
        doc_id=doc_id,
        doc_date=doc_date,
        client=client,
        project_name=project_name,
        notes=notes,

        payment_terms=payment_terms,
        valid_until=valid_until,

        items=items,
        charges=charges,
        items_total=items_total,
        total_discounts=total_discounts,
        items_after_discount=items_after_discount,
        supervision=supervision,
        supervision_pct=supervision_pct,
        admin=admin,
        admin_pct=admin_pct,
        insurance=insurance,
        insurance_pct=insurance_pct,
        transport=transport,
        transport_pct=transport_pct,
        contingency=contingency,
        contingency_pct=contingency_pct,
        subtotal_general=subtotal_general,
        itbis=itbis,
        grand_total=grand_total
    )

    # SAFETY CHECK
    if pdf is None:
        raise ValueError("build_quote_invoice_pdf returned None — check layout_utils.py")

    pdf_bytes = pdf.output()
    return io.BytesIO(pdf_bytes)
