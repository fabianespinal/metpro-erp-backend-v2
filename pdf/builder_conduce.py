import io
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
# builder_conduce.py lives in: backend/pdf/builder_conduce.py
# We must go 2 levels up to reach backend/
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
LOGO_PATH = os.path.join(BASE_DIR, "assets", "logo.png")


def create_conduce_pdf(doc_id, doc_date, client, project_name, notes, items):
    """Generate PDF bytes for a conduce (delivery note)."""
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

    pdf.set_font('Arial', '', 6)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 3, 'Parque Industrial Disdo', 0, 1, 'R')
    pdf.cell(0, 3, 'Calle Central No. 1, Hato Nuevo Palave', 0, 1, 'R')
    pdf.cell(0, 3, 'Tel: (829) 439-8476 | RNC: 131-71683-2', 0, 1, 'R')
    pdf.ln(8)

    # ==================== TITLE ====================
    pdf.set_font('Arial', 'B', 14)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 7, 'CONDUCE (NOTA DE ENTREGA)', 0, 1, 'R')
    pdf.set_draw_color(220, 220, 220)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    # ==================== DOCUMENT INFO & CLIENT ====================
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(100, 100, 100)

    left_x = 10
    right_x = 110
    start_y = pdf.get_y()

    # Left column
    pdf.set_xy(left_x, start_y)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(35, 4, 'Numero de Conduce:', 0, 0)
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 4, sanitize_text(doc_id), 0, 1)

    pdf.set_x(left_x)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(35, 4, 'Fecha:', 0, 0)
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 4, sanitize_text(doc_date), 0, 1)

    if project_name:
        pdf.set_x(left_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(35, 4, 'Proyecto:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(project_name)[:60], 0, 1)

    # Right column: Client
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

    if client.get('address'):
        pdf.set_x(right_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(25, 4, 'Direccion:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(client["address"])[:40], 0, 1)

    pdf.ln(8)

    # ==================== ITEMS TABLE (NO PRICES) ====================
    pdf.set_font('Arial', 'B', 9)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 5, 'Items Entregados', 0, 1, 'L')
    pdf.ln(2)

    # Table headers - NO PRICE COLUMNS
    pdf.set_fill_color(245, 245, 245)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(140, 6, 'DESCRIPCION', 1, 0, 'L', True)
    pdf.cell(50, 6, 'CANTIDAD', 1, 1, 'C', True)

    # Table rows
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(30, 30, 30)
    row_color = True

    for item in items:
        qty = float(item['quantity'] or 0)
        product_name = sanitize_text(item.get('product_name', 'Item'))[:80]

        if row_color:
            pdf.set_fill_color(252, 252, 252)
        else:
            pdf.set_fill_color(255, 255, 255)

        pdf.cell(140, 5, product_name, 1, 0, 'L', True)
        pdf.cell(50, 5, f'{qty:.2f}', 1, 1, 'C', True)

        row_color = not row_color

    pdf.ln(12)

    # ==================== NOTES ====================
    if notes and notes.strip():
        pdf.set_font('Arial', 'B', 8)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 5, 'NOTAS / NOTES', 0, 1, 'L')
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(60, 60, 60)
        pdf.multi_cell(0, 4, notes.strip(), border=0, align='L', fill=False)

    pdf.ln(15)

    # ==================== SIGNATURES ====================
    add_footer_with_signature(pdf)

    # ==================== FOOTER ====================
    pdf.set_y(-15)
    pdf.set_font('Arial', 'I', 8)
    pdf.set_text_color(180, 180, 180)
    pdf.cell(0, 10, 'Pagina 1 de 1', 0, 0, 'C')

    pdf_bytes = pdf.output()
    return io.BytesIO(pdf_bytes)