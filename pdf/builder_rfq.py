"""RFQ PDF. Same look as the other documents: logo, company details, title, vendor / bill to, lines, notes,
signature. NO price, amount, subtotal or total, by design."""
import io
import logging
import os

from fpdf import FPDF
from fpdf.fonts import FontFace

from core.dates import fmt_day
from pdf.utils.seal_utils import SEAL_OVERLAP_MM, draw_seal
from pdf.utils.text_utils import sanitize_text

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
LOGO_PATH = os.path.join(BASE_DIR, "assets", "logo.png")
FONT_PATH = os.path.join(BASE_DIR, "fonts", "GreatVibes-Regular.ttf")


class _RfqPdf(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Página {self.page_no()} de {{nb}}", 0, 0, "C")


def _qty(q) -> str:
    return f"{float(q or 0):g}"


def _label_value(pdf, x, label, value, label_w=30):
    pdf.set_x(x)
    pdf.set_font("Arial", "B", 7)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(label_w, 4, label, 0, 0)
    pdf.set_font("Arial", "", 7)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 4, sanitize_text(value), 0, 1)


def _block(pdf, x, y, w, heading, lines):
    """A bordered box with a heading and wrapped text lines. Returns the bottom y."""
    pdf.set_xy(x, y)
    pdf.set_font("Arial", "B", 7)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(w, 5, heading, 0, 1)
    pdf.set_font("Arial", "", 7)
    pdf.set_text_color(30, 30, 30)
    for ln in lines:
        if ln:
            pdf.set_x(x)
            pdf.multi_cell(w, 4, sanitize_text(ln), 0, "L")
    return pdf.get_y()


def create_rfq_pdf(rfq: dict, items: list, signer_name=None, seal=None, company_lines=None):
    pdf = _RfqPdf()
    pdf.alias_nb_pages("{nb}")
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.add_page()

    # Header: logo left, company details right
    try:
        if os.path.exists(LOGO_PATH):
            pdf.image(LOGO_PATH, x=10, y=10, w=28)
        else:
            logger.error("Logo not found at: %s", LOGO_PATH)
    except Exception as e:  # never fail the document over the logo
        logger.error("Logo loading failed: %s", e)
    pdf.set_xy(100, 10)
    pdf.set_font("Arial", "", 7)
    pdf.set_text_color(110, 110, 110)
    for ln in (company_lines or []):
        pdf.set_x(100)
        pdf.cell(100, 3.5, sanitize_text(ln), 0, 1, "R")
    pdf.set_y(max(pdf.get_y(), 40) + 2)

    # Title
    pdf.set_font("Arial", "B", 14)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 7, sanitize_text(rfq.get("title") or "Solicitud de cotización").upper(), 0, 1, "R")
    pdf.set_draw_color(220, 220, 220)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)

    # Number / date
    y0 = pdf.get_y()
    pdf.set_xy(10, y0)
    _label_value(pdf, 10, "Número:", rfq.get("label", ""))
    _label_value(pdf, 10, "Fecha:", fmt_day(rfq.get("rfq_date")))
    pdf.ln(3)

    # Vendor | Bill to
    y = pdf.get_y()
    vendor = [rfq.get("vendor_name"), rfq.get("vendor_contact") and f"Contacto: {rfq['vendor_contact']}",
              rfq.get("vendor_address"), rfq.get("vendor_tax_id") and f"RNC: {rfq['vendor_tax_id']}",
              rfq.get("vendor_email") and f"Correo: {rfq['vendor_email']}",
              rfq.get("vendor_phone") and f"Tel: {rfq['vendor_phone']}"]
    b1 = _block(pdf, 10, y, 90, "PROVEEDOR", vendor)
    b2 = _block(pdf, 110, y, 90, "FACTURAR A", (rfq.get("bill_to") or "").split("\n"))
    pdf.set_y(max(b1, b2) + 3)

    if rfq.get("payment_terms"):
        pdf.set_x(10)
        pdf.set_font("Arial", "B", 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(30, 4, "Condiciones de pago:", 0, 0)
        pdf.set_font("Arial", "", 7)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 4, sanitize_text(rfq["payment_terms"]), 0, "L")
        pdf.ln(2)
    pdf.ln(2)

    # Lines: Item, Description, Quantity, Unit. No money columns.
    pdf.set_font("Arial", "", 7)
    pdf.set_text_color(30, 30, 30)
    with pdf.table(
        col_widths=(32, 98, 20, 40),
        text_align=("LEFT", "LEFT", "CENTER", "LEFT"),
        headings_style=FontFace(emphasis="BOLD", fill_color=(245, 245, 245), color=(60, 60, 60)),
        line_height=4.5,
        padding=1,
    ) as table:
        head = table.row()
        for h in ("ARTÍCULO", "DESCRIPCIÓN", "CANTIDAD", "UNIDAD"):
            head.cell(h)
        for it in items:
            row = table.row()
            row.cell(sanitize_text(it.get("item")))
            row.cell(sanitize_text(it.get("description") or ""))
            row.cell(_qty(it.get("quantity")))
            row.cell(sanitize_text(it.get("unit") or ""))
    pdf.ln(4)

    # Notes
    if rfq.get("notes"):
        pdf.set_x(10)
        pdf.set_font("Arial", "B", 8)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 5, "Notas", 0, 1)
        pdf.set_font("Arial", "", 7)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 4, sanitize_text(rfq["notes"]), 0, "L")
        pdf.ln(2)

    _signature(pdf, signer_name, seal)
    return io.BytesIO(pdf.output())


def _signature(pdf, signer_name, seal):
    sig_y = pdf.get_y() + 12
    if seal is not None:
        sig_y = max(sig_y, pdf.get_y() + seal.height_mm - SEAL_OVERLAP_MM + 2)
    if sig_y > 255:
        pdf.add_page()
        sig_y = 25 if seal is None else 15 + seal.height_mm - SEAL_OVERLAP_MM
    font_loaded = False
    try:
        pdf.add_font("GreatVibes", "", FONT_PATH, uni=True)
        font_loaded = True
    except Exception as e:
        logger.error("Font load failed: %s", e)
    if seal is not None:
        try:
            draw_seal(pdf, seal, center_x=15 + 75 / 2, sig_y=sig_y)
        except Exception:
            logger.exception("Seal drawing failed; continuing without it")
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
    pdf.cell(75, 4, sanitize_text(f"Firmado por: {signer_name}") if signer_name else "Firmado por:", 0, 1, "C")
