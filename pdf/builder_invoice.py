import io
from pdf.utils.layout_utils import build_quote_invoice_pdf
from pdf.builder_conduce import create_conduce_pdf

def create_invoice_pdf(
    doc_type, doc_id, doc_date, client, project_name, notes, items,
    charges, items_total, total_discounts, items_after_discount,
    supervision, supervision_pct, admin, admin_pct, insurance, insurance_pct,
    transport, transport_pct, contingency, contingency_pct,
    subtotal_general, itbis, grand_total
):
    """Generate PDF bytes for an invoice."""
    pdf = build_quote_invoice_pdf(
        doc_type=doc_type,
        doc_id=doc_id,
        doc_date=doc_date,
        client=client,
        project_name=project_name,
        notes=notes,
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
    
    pdf_bytes = pdf.output()
    return io.BytesIO(pdf_bytes)

# Re-export for convenience
__all__ = ['create_invoice_pdf', 'create_conduce_pdf']