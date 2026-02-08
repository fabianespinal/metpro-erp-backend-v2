def add_footer_with_signature(pdf):
    """Add signature section with two columns to PDF"""
    sig_y = pdf.get_y()
    
    # Left signature: Company Representative
    pdf.set_xy(15, sig_y + 15)
    pdf.set_draw_color(180, 180, 180)
    pdf.line(15, sig_y + 15, 90, sig_y + 15)
    
    pdf.set_xy(15, sig_y + 17)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(75, 4, 'REPRESENTANTE METPRO', 0, 1, 'C')
    
    pdf.set_x(15)
    pdf.set_font('Arial', '', 6)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(75, 3, 'Nombre:', 0, 1, 'L')
    pdf.set_x(15)
    pdf.cell(75, 3, 'Firma:', 0, 1, 'L')
    pdf.set_x(15)
    pdf.cell(75, 3, 'Fecha:', 0, 1, 'L')
    
    # Right signature: Client Representative
    pdf.set_xy(115, sig_y + 15)
    pdf.line(115, sig_y + 15, 190, sig_y + 15)
    
    pdf.set_xy(115, sig_y + 17)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(75, 4, 'REPRESENTANTE CLIENTE', 0, 1, 'C')
    
    pdf.set_x(115)
    pdf.set_font('Arial', '', 6)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(75, 3, 'Nombre:', 0, 1, 'L')
    pdf.set_x(115)
    pdf.cell(75, 3, 'Firma:', 0, 1, 'L')
    pdf.set_x(115)
    pdf.cell(75, 3, 'Fecha:', 0, 1, 'L')
