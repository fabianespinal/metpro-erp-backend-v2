"""Terms and Conditions: final page(s) of quote and invoice PDFs."""
import io
from fpdf import FPDF

from pdf.builder_cover import LEFT, _text
from terms_page.defaults import PAGE_TITLE


def add_terms_pages(pdf, sections):
    """Append the terms as new page(s). `sections` is [(title, text), ...]."""
    pdf.add_page()
    pdf.set_left_margin(LEFT)
    pdf.set_right_margin(LEFT)
    pdf.set_auto_page_break(auto=True, margin=15)
    width = 210 - 2 * LEFT

    pdf.set_xy(LEFT, 20)
    pdf.set_font("Arial", "B", 14)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 8, _text(PAGE_TITLE), 0, 1, "L")
    pdf.set_draw_color(220, 220, 220)
    pdf.line(LEFT, pdf.get_y() + 1, 210 - LEFT, pdf.get_y() + 1)
    pdf.ln(6)

    for title, body in sections:
        pdf.set_x(LEFT)
        pdf.set_font("Arial", "B", 10)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 6, _text(title), 0, 1, "L")
        pdf.set_font("Arial", "", 9)
        pdf.set_text_color(70, 70, 70)
        for line in _text(body).split("\n"):
            pdf.set_x(LEFT)
            if line.strip():
                pdf.multi_cell(width, 5, line, 0, "J")
            else:
                pdf.ln(2)
        pdf.ln(4)

    pdf.set_left_margin(10)
    pdf.set_right_margin(10)


def create_terms_pdf(sections) -> io.BytesIO:
    """Standalone PDF of the terms (editor preview)."""
    pdf = FPDF()
    add_terms_pages(pdf, sections)
    return io.BytesIO(bytes(pdf.output(dest="S")))
