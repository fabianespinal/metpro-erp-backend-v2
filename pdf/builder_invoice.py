import io
from backend.pdf.utils.layout_utils import build_quote_invoice_pdf
from backend.pdf.builder_conduce import create_conduce_pdf


def create_invoice_pdf(
    doc_type, doc_id, doc_date, client, project_name, notes, items,
    charges, items_total, total_discounts, items_after_discount,
    supervision, supervision_pct, admin, admin_pct, insurance, insurance_pct,
    transport, transport_pct, contingency, contingency_pct,
    subtotal_general, itbis, grand_total,
    payment_terms=None,
    valid_until=None,
    payments=None,
    amount_paid=0,
    amount_due=0
):
    try:
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
            grand_total=grand_total,
            payments=payments or [],
            amount_paid=amount_paid or 0,
            amount_due=amount_due or 0
        )
    except Exception as e:
        raise RuntimeError(f"PDF layout generation failed: {e}")

    if pdf is None:
        raise ValueError("build_quote_invoice_pdf returned None — check layout_utils.py")

    try:
        pdf_bytes = pdf.output()
    except Exception as e:
        raise RuntimeError(f"FPDF output() failed: {e}")

    return io.BytesIO(pdf_bytes)
