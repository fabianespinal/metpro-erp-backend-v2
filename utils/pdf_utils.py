def add_footer_with_signature(pdf):
    """Add signature section with two columns to PDF"""
    sig_y = pdf.get_y()

    # Load cursive signature font (GreatVibes)
    try:
        pdf.add_font("GreatVibes", "", "app/fonts/GreatVibes-Regular.ttf", uni=True)
    except:
        pdf.add_font("GreatVibes", "", "backend/app/fonts/GreatVibes-Regular.ttf", uni=True)

    # ============================
    # LEFT SIDE — METPRO SIGNATURE
    # ============================

    # Cursive signature text
    pdf.set_xy(15, sig_y + 2)
    pdf.set_font("GreatVibes", "", 22)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(75, 10, "Karmary Mata", 0, 1, "C")

    # Signature line
    pdf.set_xy(15, sig_y + 15)
    pdf.set_draw_color(180, 180, 180)
    pdf.line(15, sig_y + 15, 90, sig_y + 15)

    # Label
    pdf.set_xy(15, sig_y + 17)
    pdf.set_font("Arial", "B", 7)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(75, 4, "Representante Metpro", 0, 1, "C")

    # ============================
    # RIGHT SIDE — CLIENT SIGNATURE
    # ============================

    # Signature line
    pdf.set_xy(115, sig_y + 15)
    pdf.set_draw_color(180, 180, 180)
    pdf.line(115, sig_y + 15, 190, sig_y + 15)

    # Label
    pdf.set_xy(115, sig_y + 17)
    pdf.set_font("Arial", "B", 7)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(75, 4, "Representante Cliente", 0, 1, "C")
