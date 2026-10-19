import io
import os
from fpdf import FPDF
from pdf.utils.text_utils import sanitize_text
from core.dates import fmt_day  # E-03: every printed date is dd/mm/aaaa
from quotes.dynamic_charges import dynamic_charge_lines
import logging

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
LOGO_PATH = os.path.join(BASE_DIR, "assets", "logo.png")


def add_footer_with_signature(pdf, signer_name=None):
    """Add signature section with two columns to PDF"""

    sig_y = pdf.get_y() + 10
    if sig_y > 260:
        pdf.add_page()
        sig_y = 20

    FONT_PATH = os.path.join(BASE_DIR, "fonts", "GreatVibes-Regular.ttf")

    font_loaded = False
    try:
        pdf.add_font("GreatVibes", "", FONT_PATH, uni=True)
        font_loaded = True
    except Exception as e:
        logger.error("Font load failed: %s", e)

    # Left — METPRO signature
    pdf.set_xy(15, sig_y)
    if font_loaded:
        pdf.set_font("GreatVibes", "", 18)
    else:
        pdf.set_font("Arial", "I", 12)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(75, 6, sanitize_text(signer_name) if signer_name else "", 0, 1, "C")

    pdf.set_draw_color(180, 180, 180)
    pdf.line(15, sig_y + 8, 90, sig_y + 8)

    pdf.set_xy(15, sig_y + 10)
    pdf.set_font("Arial", "B", 7)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(75, 4, "Representante Metpro", 0, 1, "C")

    # Right — client signature
    pdf.line(115, sig_y + 8, 190, sig_y + 8)

    pdf.set_xy(115, sig_y + 10)
    pdf.set_font("Arial", "B", 7)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(75, 4, "Representante Cliente", 0, 1, "C")


def _category_heading(pdf, item, current, width):
    """
    Bold section row above the first item of each template-pack category.
    Items without a category after categorised ones go under "Otros".
    Documents with no categories at all render exactly as before.
    Returns the category now in effect.
    """
    cat = (item.get("category") or "").strip() or None
    if cat == current:
        return current
    if cat is None and current is None:
        return current
    label = cat if cat else "Otros"
    pdf.set_font("Arial", "B", 7)
    pdf.set_fill_color(235, 235, 235)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(width, 5, sanitize_text(label)[:80], 1, 1, "L", True)
    pdf.set_font("Arial", "", 7)
    pdf.set_text_color(30, 30, 30)
    return cat


def build_quote_invoice_pdf(
    doc_type, doc_id, doc_date, client, project_name, notes, items,
    charges, items_total, total_discounts, items_after_discount,
    supervision, supervision_pct, admin, admin_pct, insurance, insurance_pct,
    transport, transport_pct, contingency, contingency_pct,
    subtotal_general, itbis, grand_total,
    payment_terms=None,
    valid_until=None,
    payments=None,
    amount_paid=0,
    amount_due=0,
    signer_name=None
):
    payments = payments or []
    amount_paid = amount_paid or 0
    amount_due = amount_due or 0

    pdf = FPDF()

    # Page 1: cover (portada). A failure here must never block the quote or invoice itself.
    try:
        from cover_page.service import get_active_body
        kind = "quote" if doc_type == "COTIZACION" else "invoice"
        cover_body = get_active_body(kind)
        if cover_body:
            from pdf.builder_cover import add_cover_page
            add_cover_page(
                pdf, kind, cover_body,
                client_name=(client or {}).get("company_name", ""),
                contact_name=(client or {}).get("contact_name", ""),
                user_name=signer_name or "",
                date_text=doc_date,
                doc_label=doc_id,
            )
    except Exception:
        logger.exception("Cover page failed; continuing without it")

    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    try:
        if os.path.exists(LOGO_PATH):
            pdf.image(LOGO_PATH, x=10, y=10, w=15)
    except Exception as e:
        logger.error("Logo loading failed: %s", e)

    pdf.set_font('Arial', '', 6)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 3, 'Parque Industrial Disdo', 0, 1, 'R')
    pdf.cell(0, 3, 'Calle Central No. 1, Hato Nuevo Palave', 0, 1, 'R')
    pdf.cell(0, 3, 'Tel: (829) 439-8476 | RNC: 131-71683-2', 0, 1, 'R')
    pdf.ln(8)

    pdf.set_font('Arial', 'B', 14)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 7, doc_type, 0, 1, 'R')
    pdf.set_draw_color(220, 220, 220)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(100, 100, 100)

    left_x = 10
    right_x = 110
    start_y = pdf.get_y()

    pdf.set_xy(left_x, start_y)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(80, 80, 80)
    label = 'Número de Cotización:' if doc_type == 'COTIZACION' else 'Número de Factura:'
    pdf.cell(35, 4, label, 0, 0)
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 4, sanitize_text(doc_id), 0, 1)

    pdf.set_x(left_x)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(35, 4, 'Fecha:', 0, 0)
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 4, sanitize_text(fmt_day(doc_date)), 0, 1)

    if payment_terms:
        pdf.set_x(left_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(35, 4, 'Términos de Pago:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(payment_terms)[:60], 0, 1)

    if valid_until:
        pdf.set_x(left_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(35, 4, 'Válida Hasta:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(fmt_day(valid_until)), 0, 1)

    if project_name:
        pdf.set_x(left_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(35, 4, 'Proyecto:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(project_name)[:60], 0, 1)

    pdf.set_xy(right_x, start_y)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(25, 4, 'Cliente:', 0, 0)
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 4, sanitize_text(client.get("company_name", ""))[:40], 0, 1)

    if client.get('contact_name'):
        pdf.set_x(right_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(25, 4, 'Contacto:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(client["contact_name"])[:40], 0, 1)

    if client.get('email'):
        pdf.set_x(right_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(25, 4, 'Email:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(client["email"])[:40], 0, 1)

    if client.get('phone'):
        pdf.set_x(right_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(25, 4, 'Teléfono:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(client["phone"])[:30], 0, 1)

    if client.get('address'):
        pdf.set_x(right_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(25, 4, 'Dirección:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(client["address"])[:40], 0, 1)

    if client.get('tax_id'):
        pdf.set_x(right_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(25, 4, 'RNC:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(client["tax_id"])[:30], 0, 1)

    pdf.ln(8)
    final_y = max(pdf.get_y(), start_y + 20)
    pdf.set_y(final_y + 4)

    pdf.set_font('Arial', 'B', 9)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 5, 'Detalle de Items', 0, 1, 'L')
    pdf.ln(2)

    pdf.set_fill_color(245, 245, 245)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(85, 6, 'DESCRIPCIÓN', 1, 0, 'L', True)
    pdf.cell(25, 6, 'CANTIDAD', 1, 0, 'C', True)
    pdf.cell(35, 6, 'PRECIO UNIT.', 1, 0, 'R', True)
    pdf.cell(45, 6, 'TOTAL', 1, 1, 'R', True)

    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(30, 30, 30)
    row_color = True

    current_category = None
    for item in items:
        current_category = _category_heading(pdf, item, current_category, 190)
        qty = float(item.get('quantity') or 0)
        price = float(item.get('unit_price') or 0)
        subtotal = qty * price
        product_name = sanitize_text(item.get('product_name', 'Item'))[:50]

        if row_color:
            pdf.set_fill_color(252, 252, 252)
        else:
            pdf.set_fill_color(255, 255, 255)

        pdf.cell(85, 5, product_name, 1, 0, 'L', True)
        pdf.cell(25, 5, f'{qty:.2f}', 1, 0, 'C', True)
        pdf.cell(35, 5, f'${price:,.2f}', 1, 0, 'R', True)
        pdf.cell(45, 5, f'${subtotal:,.2f}', 1, 1, 'R', True)

        row_color = not row_color

    pdf.ln(6)

    pdf.set_font('Arial', 'B', 9)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 5, 'Resumen Financiero', 0, 1, 'L')
    pdf.ln(2)

    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(60, 60, 60)
    summary_x = 120

    pdf.set_x(summary_x)
    pdf.cell(45, 4, 'Subtotal de Items:', 0, 0, 'L')
    pdf.set_text_color(30, 30, 30)
    pdf.cell(25, 4, f'${items_total:,.2f}', 0, 1, 'R')

    if total_discounts > 0:
        pdf.set_x(summary_x)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(45, 4, 'Total Descuentos:', 0, 0, 'L')
        pdf.set_text_color(200, 50, 50)
        pdf.cell(25, 4, f'-${total_discounts:,.2f}', 0, 1, 'R')

        pdf.set_x(summary_x)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(45, 4, 'Después de Descuentos:', 0, 0, 'L')
        pdf.set_text_color(30, 30, 30)
        pdf.cell(25, 4, f'${items_after_discount:,.2f}', 0, 1, 'R')
        pdf.ln(1)

    dynamic_lines = list(dynamic_charge_lines(charges, items_after_discount))
    if any(charges.get(k) for k in ('supervision', 'admin', 'insurance', 'transport', 'contingency')) or dynamic_lines:
        pdf.set_x(summary_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(70, 5, 'Cargos Indirectos', 0, 1, 'L')
        pdf.set_font('Arial', '', 7)

    if charges.get('supervision'):
        pdf.set_x(summary_x)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(45, 4, f'Supervisión ({supervision_pct:.1f}%):', 0, 0, 'L')
        pdf.set_text_color(60, 60, 60)
        pdf.cell(25, 4, f'${supervision:,.2f}', 0, 1, 'R')

    if charges.get('admin'):
        pdf.set_x(summary_x)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(45, 4, f'Administración ({admin_pct:.1f}%):', 0, 0, 'L')
        pdf.set_text_color(60, 60, 60)
        pdf.cell(25, 4, f'${admin:,.2f}', 0, 1, 'R')

    if charges.get('insurance'):
        pdf.set_x(summary_x)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(45, 4, f'Seguro ({insurance_pct:.1f}%):', 0, 0, 'L')
        pdf.set_text_color(60, 60, 60)
        pdf.cell(25, 4, f'${insurance:,.2f}', 0, 1, 'R')

    if charges.get('transport'):
        pdf.set_x(summary_x)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(45, 4, f'Transporte ({transport_pct:.1f}%):', 0, 0, 'L')
        pdf.set_text_color(60, 60, 60)
        pdf.cell(25, 4, f'${transport:,.2f}', 0, 1, 'R')

    if charges.get('contingency'):
        pdf.set_x(summary_x)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(45, 4, f'Contingencia ({contingency_pct:.1f}%):', 0, 0, 'L')
        pdf.set_text_color(60, 60, 60)
        pdf.cell(25, 4, f'${contingency:,.2f}', 0, 1, 'R')

    # User-defined charges (none for legacy quotes). Same base and rule as totals.
    for dc in dynamic_lines:
        pdf.set_x(summary_x)
        pdf.set_text_color(100, 100, 100)
        label = sanitize_text(f"{dc['name'][:22]} ({dc['percentage']:.1f}%):")
        pdf.cell(45, 4, label, 0, 0, 'L')
        pdf.set_text_color(60, 60, 60)
        pdf.cell(25, 4, f"${dc['amount']:,.2f}", 0, 1, 'R')

    pdf.ln(2)
    pdf.set_draw_color(220, 220, 220)
    pdf.line(summary_x, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)

    pdf.set_x(summary_x)
    pdf.set_font('Arial', 'B', 8)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(45, 5, 'Subtotal General:', 0, 0, 'L')
    pdf.cell(25, 5, f'${subtotal_general:,.2f}', 0, 1, 'R')

    pdf.set_x(summary_x)
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(45, 4, 'ITBIS (18%):', 0, 0, 'L')
    pdf.set_text_color(30, 30, 30)
    pdf.cell(25, 4, f'${itbis:,.2f}', 0, 1, 'R')

    pdf.ln(1)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(summary_x, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)

    pdf.set_x(summary_x)
    pdf.set_font('Arial', 'B', 11)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(45, 7, 'TOTAL GENERAL:', 0, 0, 'L')
    pdf.cell(25, 7, f'${grand_total:,.2f}', 0, 1, 'R')

    pdf.ln(8)

    # ==================== PAYMENT SECTION (INVOICES ONLY) ====================
    if doc_type != 'COTIZACION':
        pdf.set_font("Arial", "B", 10)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 6, "Resumen de Pagos", 0, 1, "L")
        pdf.ln(2)

        pdf.set_font("Arial", "", 8)
        pdf.set_text_color(60, 60, 60)

        pdf.cell(40, 5, "Total Facturado:", 0, 0, "L")
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 5, f"${grand_total:,.2f}", 0, 1, "L")

        pdf.set_text_color(60, 60, 60)
        pdf.cell(40, 5, "Total Pagado:", 0, 0, "L")
        pdf.set_text_color(0, 140, 0)
        pdf.cell(0, 5, f"${amount_paid:,.2f}", 0, 1, "L")

        pdf.set_text_color(60, 60, 60)
        pdf.cell(40, 5, "Pendiente:", 0, 0, "L")
        pdf.set_text_color(200, 0, 0)
        pdf.cell(0, 5, f"${amount_due:,.2f}", 0, 1, "L")

        pdf.ln(8)

        pdf.set_font("Arial", "B", 10)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 6, "Historial de Pagos", 0, 1, "L")
        pdf.ln(2)

        if len(payments) == 0:
            pdf.set_font("Arial", "", 8)
            pdf.set_text_color(120, 120, 120)
            pdf.cell(0, 5, "No hay pagos registrados.", 0, 1, "L")
        else:
            pdf.set_font("Arial", "B", 8)
            pdf.set_fill_color(245, 245, 245)
            pdf.set_draw_color(220, 220, 220)
            pdf.set_text_color(60, 60, 60)

            pdf.cell(40, 6, "Fecha", 1, 0, "L", True)
            pdf.cell(40, 6, "Método", 1, 0, "L", True)
            pdf.cell(40, 6, "Monto", 1, 0, "R", True)
            pdf.cell(70, 6, "Notas", 1, 1, "L", True)

            pdf.set_font("Arial", "", 8)
            pdf.set_text_color(30, 30, 30)

            for p in payments:
                pay_date = fmt_day(p.get("payment_date") or p.get("date") or "")
                pay_method = sanitize_text(str(p.get("method") or ""))
                pay_amount = float(p.get("amount") or 0)
                pay_notes = sanitize_text(str(p.get("notes") or ""))[:60]

                pdf.cell(40, 5, pay_date[:20], 1, 0, "L")
                pdf.cell(40, 5, pay_method[:20], 1, 0, "L")
                pdf.cell(40, 5, f"${pay_amount:,.2f}", 1, 0, "R")
                pdf.cell(70, 5, pay_notes, 1, 1, "L")

        pdf.ln(8)

    # ==================== NOTES SECTION ====================
    if notes:
        pdf.set_font("Arial", "B", 9)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 6, "Notas", 0, 1, "L")
        pdf.ln(1)
        pdf.set_font("Arial", "", 8)
        pdf.set_text_color(80, 80, 80)
        pdf.multi_cell(0, 5, sanitize_text(str(notes)))
        pdf.ln(6)

    # ==================== SIGNATURES ====================
    add_footer_with_signature(pdf, signer_name)

    # Final page: Terms and Conditions (off until an admin enables it). Never blocks the document.
    try:
        from terms_page.service import get_active_sections
        terms = get_active_sections("quote" if doc_type == "COTIZACION" else "invoice")
        if terms:
            from pdf.builder_terms import add_terms_pages
            add_terms_pages(pdf, terms)
    except Exception:
        logger.exception("Terms page failed; continuing without it")

    pdf_bytes = pdf.output(dest="S")   # already bytearray
    return io.BytesIO(pdf_bytes)