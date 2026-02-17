import os
from fpdf import FPDF
from pdf.utils.text_utils import sanitize_text

# Import external footer helper
try:
    from utils.pdf_utils import add_footer_with_signature
except ImportError:
    def add_footer_with_signature(pdf):
        pass  # Placeholder if external util is missing


# ==================== ABSOLUTE LOGO PATH (FIXED) ====================
# layout_utils.py lives in: backend/pdf/utils/layout_utils.py
# We must go 3 levels up to reach backend/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
LOGO_PATH = os.path.join(BASE_DIR, "assets", "logo.png")


def build_quote_invoice_pdf(
    doc_type, doc_id, doc_date, client, project_name, notes, items,
    charges, items_total, total_discounts, items_after_discount,
    supervision, supervision_pct, admin, admin_pct, insurance, insurance_pct,
    transport, transport_pct, contingency, contingency_pct,
    subtotal_general, itbis, grand_total,

    # NEW FIELDS
    payment_terms=None,
    valid_until=None
):
    """Shared PDF creation logic for quotes and invoices"""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # ==================== HEADER: METPRO BRANDING ====================
    try:
        if os.path.exists(LOGO_PATH):
            pdf.image(LOGO_PATH, x=10, y=10, w=15)
        else:
            print(f"Logo not found at: {LOGO_PATH}")
    except Exception as e:
        print(f"Logo loading failed: {str(e)}")

    # ==================== NOTES SECTION ====================
    if notes:
        safe_notes = sanitize_text(notes.strip())
        pdf.set_xy(10, 50)
        pdf.set_font("Helvetica", size=10)
        pdf.multi_cell(0, 4, safe_notes, border=0, align='L', fill=False)

    # Footer address block
    pdf.set_font('Arial', '', 6)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 3, 'Parque Industrial Disdo', 0, 1, 'R')
    pdf.cell(0, 3, 'Calle Central No. 1, Hato Nuevo Palave', 0, 1, 'R')
    pdf.cell(0, 3, 'Tel: (829) 439-8476 | RNC: 131-71683-2', 0, 1, 'R')
    pdf.ln(8)

    # ==================== TITLE ====================
    pdf.set_font('Arial', 'B', 14)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 7, doc_type, 0, 1, 'R')
    pdf.set_draw_color(220, 220, 220)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    # ==================== DOCUMENT INFO & CLIENT (TWO COLUMNS) ====================
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(100, 100, 100)

    left_x = 10
    right_x = 110
    start_y = pdf.get_y()

    # ---------------- LEFT COLUMN ----------------
    pdf.set_xy(left_x, start_y)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(80, 80, 80)
    label = 'Numero de Cotizacion:' if doc_type == 'COTIZACION' else 'Numero de Factura:'
    pdf.cell(35, 4, label, 0, 0)
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 4, sanitize_text(doc_id), 0, 1)

    # DATE
    pdf.set_x(left_x)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(35, 4, 'Fecha:', 0, 0)
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 4, sanitize_text(doc_date), 0, 1)

    # ==================== NEW FIELD: PAYMENT TERMS ====================
    if payment_terms:
        pdf.set_x(left_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(35, 4, 'Términos de Pago:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(payment_terms)[:60], 0, 1)

    # ==================== NEW FIELD: VALID UNTIL ====================
    if valid_until:
        pdf.set_x(left_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(35, 4, 'Válida Hasta:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(valid_until), 0, 1)

    # PROJECT NAME
    if project_name:
        pdf.set_x(left_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(35, 4, 'Proyecto:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(project_name)[:60], 0, 1)

    # ---------------- RIGHT COLUMN (CLIENT INFO) ----------------
    pdf.set_xy(right_x, start_y)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(25, 4, 'Cliente:', 0, 0)
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 4, sanitize_text(client["company_name"])[:40], 0, 1)

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
        pdf.cell(25, 4, 'Telefono:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(client["phone"])[:30], 0, 1)

    if client.get('address'):
        pdf.set_x(right_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(25, 4, 'Direccion:', 0, 0)
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

    # After finishing both columns, move Y to the lower of the two columns
    final_y = max(pdf.get_y(), start_y + 20)
    pdf.set_y(final_y + 4)

    # ==================== ITEMS TABLE ====================
    pdf.set_font('Arial', 'B', 9)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 5, 'Detalle de Items', 0, 1, 'L')
    pdf.ln(2)

    # Table headers
    pdf.set_fill_color(245, 245, 245)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(85, 6, 'DESCRIPCION', 1, 0, 'L', True)
    pdf.cell(25, 6, 'CANTIDAD', 1, 0, 'C', True)
    pdf.cell(35, 6, 'PRECIO UNIT.', 1, 0, 'R', True)
    pdf.cell(45, 6, 'TOTAL', 1, 1, 'R', True)

    # Table rows
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(30, 30, 30)
    row_color = True

    for item in items:
        qty = float(item['quantity'] or 0)
        price = float(item['unit_price'] or 0)
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

    # ==================== FINANCIAL SUMMARY ====================
    pdf.set_font('Arial', 'B', 9)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 5, 'Resumen Financiero', 0, 1, 'L')
    pdf.ln(2)

    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(60, 60, 60)
    summary_x = 120

    # Subtotal de Items
    pdf.set_x(summary_x)
    pdf.cell(45, 4, 'Subtotal de Items:', 0, 0, 'L')
    pdf.set_text_color(30, 30, 30)
    pdf.cell(25, 4, f'${items_total:,.2f}', 0, 1, 'R')

    # Discounts if applicable
    if total_discounts > 0:
        pdf.set_x(summary_x)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(45, 4, 'Total Descuentos:', 0, 0, 'L')
        pdf.set_text_color(200, 50, 50)
        pdf.cell(25, 4, f'-${total_discounts:,.2f}', 0, 1, 'R')

        pdf.set_x(summary_x)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(45, 4, 'Despues de Descuentos:', 0, 0, 'L')
        pdf.set_text_color(30, 30, 30)
        pdf.cell(25, 4, f'${items_after_discount:,.2f}', 0, 1, 'R')
        pdf.ln(1)

    # Surcharges
    pdf.set_font('Arial', '', 7)
    if charges.get('supervision'):
        pdf.set_x(summary_x)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(45, 4, f'Supervision ({supervision_pct:.1f}%):', 0, 0, 'L')
        pdf.set_text_color(60, 60, 60)
        pdf.cell(25, 4, f'${supervision:,.2f}', 0, 1, 'R')
    if charges.get('admin'):
        pdf.set_x(summary_x)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(45, 4, f'Administracion ({admin_pct:.1f}%):', 0, 0, 'L')
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

    pdf.ln(2)

    # Subtotal line
    pdf.set_draw_color(220, 220, 220)
    pdf.line(summary_x, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)

    # SUBTOTAL GENERAL
    pdf.set_x(summary_x)
    pdf.set_font('Arial', 'B', 8)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(45, 5, 'Subtotal General:', 0, 0, 'L')
    pdf.cell(25, 5, f'${subtotal_general:,.2f}', 0, 1, 'R')

    # ITBIS
    pdf.set_x(summary_x)
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(45, 4, 'ITBIS (18%):', 0, 0, 'L')
    pdf.set_text_color(30, 30, 30)
    pdf.cell(25, 4, f'${itbis:,.2f}', 0, 1, 'R')

    pdf.ln(1)

    # Total line
    pdf.set_draw_color(200, 200, 200)
    pdf.line(summary_x, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)

    # TOTAL GENERAL
    pdf.set_x(summary_x)
    pdf.set_font('Arial', 'B', 11)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(45, 7, 'TOTAL GENERAL:', 0, 0, 'L')
    pdf.cell(25, 7, f'${grand_total:,.2f}', 0, 1, 'R')

    pdf.ln(12)

    # ==================== NOTES ====================
    if notes and notes.strip():
        pdf.set_font('Arial', 'B', 8)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 5, 'NOTAS / NOTES', 0, 1, 'L')
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(60, 60, 60)
        pdf.multi_cell(0, 4, notes.strip(), border=0, align='L', fill=False)
        pdf.ln(3)
    pdf.ln(12)

    # ==================== SIGNATURES ====================
    add_footer_with_signature(pdf)

    # ==================== FOOTER ====================
    pdf.set_y(-15)
    pdf.set_font('Arial', 'I', 8)
    pdf.set_text_color(180, 180, 180)
    pdf.cell(0, 10, 'Pagina 1 de 1', 0, 0, 'C')

    return pdf