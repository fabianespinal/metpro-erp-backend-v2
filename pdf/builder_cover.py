"""Cover page (portada): page 1 of every quote and invoice PDF."""
import io
import os
import re
from fpdf import FPDF

from pdf.utils.text_utils import sanitize_text
from cover_page.service import render_text

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
LOGO_PATH = os.path.join(BASE_DIR, "assets", "logo.png")

LEFT = 25
RIGHT_COL = 115
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_TYPOGRAPHY = {
    "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
    "…": "...", " ": " ", "•": "-",
}


def _text(value) -> str:
    s = "" if value is None else str(value)
    for src, dst in _TYPOGRAPHY.items():
        s = s.replace(src, dst)
    return sanitize_text(s)


def format_cover_date(raw) -> str:
    """YYYY-MM-DD (optionally with time) -> DD/MM/YYYY. Anything else is printed as is."""
    m = _ISO_DATE.match(str(raw or ""))
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else str(raw or "")


def _label(pdf, text):
    pdf.set_font("Arial", "B", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(0, 5, _text(text), 0, 1)


def _value(pdf, text):
    pdf.set_font("Arial", "", 11)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 6, _text(text), 0, 1)


def add_cover_page(pdf, kind, body, client_name, contact_name, user_name, date_text, doc_label):
    """Add the cover as a new page of `pdf`. kind is 'quote' or 'invoice'."""
    pdf.add_page()
    pdf.set_left_margin(LEFT)
    pdf.set_right_margin(LEFT)

    try:
        if os.path.exists(LOGO_PATH):
            pdf.image(LOGO_PATH, x=LEFT, y=20, w=45)
    except Exception:
        pass
    pdf.set_y(78)
    pdf.set_x(LEFT)

    date_text = format_cover_date(date_text)

    if kind == "quote":
        top = pdf.get_y()
        _label(pdf, "Preparado Para:")
        pdf.set_x(LEFT)
        _value(pdf, contact_name)
        pdf.set_x(LEFT)
        _value(pdf, client_name)
        end_left = pdf.get_y()
        pdf.set_xy(RIGHT_COL, top)
        _label(pdf, "Preparado por:")
        pdf.set_x(RIGHT_COL)
        _value(pdf, user_name)
        pdf.set_xy(LEFT, max(end_left, pdf.get_y()) + 6)
        _label(pdf, "Fecha:")
        pdf.set_x(LEFT)
        _value(pdf, date_text)
    else:
        _label(pdf, "Fecha:")
        pdf.set_x(LEFT)
        _value(pdf, date_text)
        pdf.ln(6)
        pdf.set_x(LEFT)
        _value(pdf, contact_name)
        pdf.set_x(LEFT)
        _value(pdf, client_name)

    pdf.ln(10)

    values = {
        "Contact_Name": _text(contact_name),
        "User_Name": _text(user_name),
        "Client": _text(client_name),
        "Date": _text(date_text),
        "No_Cotizacion": _text(doc_label) if kind == "quote" else "",
        "No_Factura": _text(doc_label) if kind == "invoice" else "",
    }
    rendered = render_text(_text(body), values)

    pdf.set_text_color(40, 40, 40)
    for line in rendered.split("\n"):
        pdf.set_x(LEFT)
        if not line.strip():
            pdf.ln(5)
            continue
        pdf.set_font("Arial", "", 11)
        pdf.multi_cell(210 - 2 * LEFT, 6, line, 0, "L")

    # Restore the margins the rest of the document expects.
    pdf.set_left_margin(10)
    pdf.set_right_margin(10)


def create_cover_pdf(kind, body, client_name, contact_name, user_name, date_text, doc_label) -> io.BytesIO:
    """Standalone one-page PDF of the cover (used by the editor preview)."""
    pdf = FPDF()
    add_cover_page(pdf, kind, body, client_name, contact_name, user_name, date_text, doc_label)
    return io.BytesIO(bytes(pdf.output(dest="S")))
