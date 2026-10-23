"""Purchase order PDF. Same look as the RFQ (logo, company, vendor / bill to, lines, notes, signature) with the
price columns, subtotal and total. DOP only, no tax."""
import io
import logging
import os

from fpdf.fonts import FontFace

from core.dates import fmt_day
from pdf.builder_rfq import LOGO_PATH, _RfqPdf, _block, _label_value, _qty, _signature
from pdf.utils.text_utils import sanitize_text

logger = logging.getLogger(__name__)


def money(v) -> str:
    return f"RD${float(v or 0):,.2f}"


def create_po_pdf(po: dict, items: list, signer_name=None, seal=None, company_lines=None):
    pdf = _RfqPdf()
    pdf.alias_nb_pages("{nb}")
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.add_page()

    try:
        if os.path.exists(LOGO_PATH):
            pdf.image(LOGO_PATH, x=10, y=10, w=28)
        else:
            logger.error("Logo not found at: %s", LOGO_PATH)
    except Exception as e:
        logger.error("Logo loading failed: %s", e)
    pdf.set_xy(100, 10)
    pdf.set_font("Arial", "", 7)
    pdf.set_text_color(110, 110, 110)
    for ln in (company_lines or []):
        pdf.set_x(100)
        pdf.cell(100, 3.5, sanitize_text(ln), 0, 1, "R")
    pdf.set_y(max(pdf.get_y(), 40) + 2)

    pdf.set_font("Arial", "B", 14)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 7, sanitize_text(po.get("title") or "Orden de compra").upper(), 0, 1, "R")
    pdf.set_draw_color(220, 220, 220)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)

    _label_value(pdf, 10, "Número:", po.get("label", ""))
    _label_value(pdf, 10, "Fecha:", fmt_day(po.get("po_date")))
    if po.get("rfq_label"):
        _label_value(pdf, 10, "Ref. RFQ:", po["rfq_label"])
    pdf.ln(3)

    y = pdf.get_y()
    vendor = [po.get("vendor_name"), po.get("vendor_contact") and f"Contacto: {po['vendor_contact']}",
              po.get("vendor_address"), po.get("vendor_tax_id") and f"RNC: {po['vendor_tax_id']}",
              po.get("vendor_email") and f"Correo: {po['vendor_email']}",
              po.get("vendor_phone") and f"Tel: {po['vendor_phone']}"]
    b1 = _block(pdf, 10, y, 90, "PROVEEDOR", vendor)
    b2 = _block(pdf, 110, y, 90, "FACTURAR A", (po.get("bill_to") or "").split("\n"))
    pdf.set_y(max(b1, b2) + 3)

    if po.get("payment_terms"):
        pdf.set_x(10)
        pdf.set_font("Arial", "B", 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(30, 4, "Condiciones de pago:", 0, 0)
        pdf.set_font("Arial", "", 7)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 4, sanitize_text(po["payment_terms"]), 0, "L")
        pdf.ln(2)
    pdf.ln(2)

    pdf.set_font("Arial", "", 7)
    pdf.set_text_color(30, 30, 30)
    with pdf.table(
        col_widths=(28, 60, 18, 18, 32, 34),
        text_align=("LEFT", "LEFT", "CENTER", "LEFT", "RIGHT", "RIGHT"),
        headings_style=FontFace(emphasis="BOLD", fill_color=(245, 245, 245), color=(60, 60, 60)),
        line_height=4.5,
        padding=1,
    ) as table:
        head = table.row()
        for h in ("ARTÍCULO", "DESCRIPCIÓN", "CANT.", "UNIDAD", "PRECIO UNIT.", "MONTO"):
            head.cell(h)
        for it in items:
            row = table.row()
            row.cell(sanitize_text(it.get("item")))
            row.cell(sanitize_text(it.get("description") or ""))
            row.cell(_qty(it.get("quantity")))
            row.cell(sanitize_text(it.get("unit") or ""))
            row.cell(money(it.get("unit_price")))
            row.cell(money(it.get("amount")))
    pdf.ln(3)

    # Totals (DOP, no tax)
    for label, value, bold in (("Subtotal:", po.get("subtotal"), False), ("TOTAL:", po.get("total"), True)):
        pdf.set_x(120)
        pdf.set_font("Arial", "B" if bold else "", 9 if bold else 8)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(35, 6, label, 0, 0, "R")
        pdf.cell(45, 6, money(value), 0, 1, "R")
    pdf.ln(3)

    if po.get("notes"):
        pdf.set_x(10)
        pdf.set_font("Arial", "B", 8)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 5, "Notas", 0, 1)
        pdf.set_font("Arial", "", 7)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 4, sanitize_text(po["notes"]), 0, "L")
        pdf.ln(2)

    _signature(pdf, signer_name, seal)
    return io.BytesIO(pdf.output())
