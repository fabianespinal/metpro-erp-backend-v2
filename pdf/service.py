import os
import json
import io
from fpdf import FPDF
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from database import get_db_connection
from psycopg2.extras import RealDictCursor
from utils.text import sanitize_text
from utils.pdf_utils import add_footer_with_signature

# ============================================================
# QUOTE PDF GENERATION
# ============================================================
def generate_quote_pdf(quote_id: str) -> StreamingResponse:
    """Generate professional METPRO Quote PDF with EXACT branding and layout"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Get quote
        cursor.execute('SELECT * FROM quotes WHERE quote_id = %s', (quote_id,))
        quote = cursor.fetchone()
        if not quote:
            raise HTTPException(status_code=404, detail='Quote not found')
        quote = dict(quote)

        # Get client
        cursor.execute('SELECT * FROM clients WHERE id = %s', (quote['client_id'],))
        client = cursor.fetchone()
        if not client:
            raise HTTPException(status_code=404, detail='Client not found')
        client = dict(client)

        # Get items
        cursor.execute('SELECT * FROM quote_items WHERE quote_id = %s', (quote_id,))
        items = [dict(row) for row in cursor.fetchall()]

        # Parse charges with backwards-compatible defaults
        try:
            charges = json.loads(quote['included_charges']) if isinstance(quote['included_charges'], str) else quote['included_charges']
            defaults = {
                'supervision_percentage': 10.0,
                'admin_percentage': 4.0,
                'insurance_percentage': 1.0,
                'transport_percentage': 3.0,
                'contingency_percentage': 3.0
            }
            for key, default in defaults.items():
                if key not in charges:
                    charges[key] = default
        except:
            charges = {
                'supervision': True, 'supervision_percentage': 10.0,
                'admin': True, 'admin_percentage': 4.0,
                'insurance': True, 'insurance_percentage': 1.0,
                'transport': True, 'transport_percentage': 3.0,
                'contingency': True, 'contingency_percentage': 3.0
            }

        # Calculate totals (EXACT METPRO CALCULATION ENGINE)
        items_total = sum(float(item['quantity'] or 0) * float(item['unit_price'] or 0) for item in items)

        total_discounts = 0
        for item in items:
            subtotal = float(item['quantity'] or 0) * float(item['unit_price'] or 0)
            if item.get('discount_type') == 'percentage':
                total_discounts += subtotal * (float(item.get('discount_value', 0)) / 100)
            elif item.get('discount_type') == 'fixed':
                total_discounts += float(item.get('discount_value', 0))

        items_after_discount = items_total - total_discounts

        # Get percentages safely
        supervision_pct = float(charges.get('supervision_percentage', 10.0))
        admin_pct = float(charges.get('admin_percentage', 4.0))
        insurance_pct = float(charges.get('insurance_percentage', 1.0))
        transport_pct = float(charges.get('transport_percentage', 3.0))
        contingency_pct = float(charges.get('contingency_percentage', 3.0))

        supervision = items_after_discount * (supervision_pct / 100) if charges.get('supervision') else 0
        admin = items_after_discount * (admin_pct / 100) if charges.get('admin') else 0
        insurance = items_after_discount * (insurance_pct / 100) if charges.get('insurance') else 0
        transport = items_after_discount * (transport_pct / 100) if charges.get('transport') else 0
        contingency = items_after_discount * (contingency_pct / 100) if charges.get('contingency') else 0

        subtotal_general = items_after_discount + supervision + admin + insurance + transport + contingency
        itbis = subtotal_general * 0.18
        grand_total = subtotal_general + itbis

        # Create PDF with EXACT layout
        pdf = _create_quote_invoice_pdf(
            doc_type='COTIZACION',
            doc_id=quote["quote_id"],
            doc_date=quote["date"],
            client=client,
            project_name=quote.get('project_name'),
            notes=quote.get('notes'),
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
            grand_total=grand_total
        )

        pdf_bytes = pdf.output()
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type='application/pdf',
            headers={'Content-Disposition': f'attachment; filename={quote_id}_cotizacion.pdf'}
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"PDF GENERATION ERROR for quote {quote_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f'Quote PDF generation failed: {str(e)}')
    finally:
        if conn:
            conn.close()

# ============================================================
# INVOICE PDF GENERATION
# ============================================================
def generate_invoice_pdf(invoice_id: int) -> StreamingResponse:
    """Generate professional METPRO Invoice PDF (same layout as quote)"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Get invoice
        cursor.execute('SELECT * FROM invoices WHERE id = %s', (invoice_id,))
        invoice = cursor.fetchone()
        if not invoice:
            raise HTTPException(status_code=404, detail='Invoice not found')
        invoice = dict(invoice)

        # Get client
        cursor.execute('SELECT * FROM clients WHERE id = %s', (invoice['client_id'],))
        client = cursor.fetchone()
        if not client:
            raise HTTPException(status_code=404, detail='Client not found')
        client = dict(client)

        # Get items from original quote
        cursor.execute('SELECT * FROM quote_items WHERE quote_id = %s', (invoice['quote_id'],))
        items = [dict(row) for row in cursor.fetchall()]

        # Get charges from original quote
        cursor.execute('SELECT included_charges, project_name FROM quotes WHERE quote_id = %s', (invoice['quote_id'],))
        quote_data = cursor.fetchone()
        if quote_data:
            charges = json.loads(quote_data['included_charges']) if isinstance(quote_data['included_charges'], str) else quote_data['included_charges']
            project_name = quote_data.get('project_name')
        else:
            charges = {
                'supervision': True, 'supervision_percentage': 10.0,
                'admin': True, 'admin_percentage': 4.0,
                'insurance': True, 'insurance_percentage': 1.0,
                'transport': True, 'transport_percentage': 3.0,
                'contingency': True, 'contingency_percentage': 3.0
            }
            project_name = None

        # Calculate totals
        items_total = sum(float(item['quantity'] or 0) * float(item['unit_price'] or 0) for item in items)

        total_discounts = 0
        for item in items:
            subtotal = float(item['quantity'] or 0) * float(item['unit_price'] or 0)
            if item.get('discount_type') == 'percentage':
                total_discounts += subtotal * (float(item.get('discount_value', 0)) / 100)
            elif item.get('discount_type') == 'fixed':
                total_discounts += float(item.get('discount_value', 0))

        items_after_discount = items_total - total_discounts

        supervision_pct = float(charges.get('supervision_percentage', 10.0))
        admin_pct = float(charges.get('admin_percentage', 4.0))
        insurance_pct = float(charges.get('insurance_percentage', 1.0))
        transport_pct = float(charges.get('transport_percentage', 3.0))
        contingency_pct = float(charges.get('contingency_percentage', 3.0))

        supervision = items_after_discount * (supervision_pct / 100) if charges.get('supervision') else 0
        admin = items_after_discount * (admin_pct / 100) if charges.get('admin') else 0
        insurance = items_after_discount * (insurance_pct / 100) if charges.get('insurance') else 0
        transport = items_after_discount * (transport_pct / 100) if charges.get('transport') else 0
        contingency = items_after_discount * (contingency_pct / 100) if charges.get('contingency') else 0

        subtotal_general = items_after_discount + supervision + admin + insurance + transport + contingency
        itbis = subtotal_general * 0.18
        grand_total = subtotal_general + itbis

        # Create PDF
        pdf = _create_quote_invoice_pdf(
            doc_type='FACTURA',
            doc_id=invoice["invoice_number"],
            doc_date=invoice["invoice_date"],
            client=client,
            project_name=project_name,
            notes=invoice.get('notes'),
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
            grand_total=grand_total
        )

        pdf_bytes = pdf.output()
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type='application/pdf',
            headers={'Content-Disposition': f'attachment; filename={invoice["invoice_number"]}_factura.pdf'}
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"PDF GENERATION ERROR for invoice {invoice_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f'Invoice PDF generation failed: {str(e)}')
    finally:
        if conn:
            conn.close()

# ============================================================
# CONDUCE PDF GENERATION (NO PRICES)
# ============================================================
def generate_conduce_pdf(invoice_id: int) -> StreamingResponse:
    """Generate conduce (delivery note) - same as invoice but WITHOUT prices"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Get invoice
        cursor.execute('SELECT * FROM invoices WHERE id = %s', (invoice_id,))
        invoice = cursor.fetchone()
        if not invoice:
            raise HTTPException(status_code=404, detail='Invoice not found')
        invoice = dict(invoice)

        # Get client
        cursor.execute('SELECT * FROM clients WHERE id = %s', (invoice['client_id'],))
        client = cursor.fetchone()
        if not client:
            raise HTTPException(status_code=404, detail='Client not found')
        client = dict(client)

        # Get items
        cursor.execute('SELECT * FROM quote_items WHERE quote_id = %s', (invoice['quote_id'],))
        items = [dict(row) for row in cursor.fetchall()]

        # Get project name
        cursor.execute('SELECT project_name FROM quotes WHERE quote_id = %s', (invoice['quote_id'],))
        quote_data = cursor.fetchone()
        project_name = quote_data.get('project_name') if quote_data else None

        # Create PDF (NO PRICES VERSION)
        pdf = _create_conduce_pdf(
            doc_id=invoice["invoice_number"].replace('INV-', 'CD-'),
            doc_date=invoice["invoice_date"],
            client=client,
            project_name=project_name,
            notes=invoice.get('notes'),
            items=items
        )

        pdf_bytes = pdf.output()
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type='application/pdf',
            headers={'Content-Disposition': f'attachment; filename=CD-{invoice["invoice_number"]}_conduce.pdf'}
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"CONDUCE GENERATION ERROR for invoice {invoice_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f'Conduce generation failed: {str(e)}')
    finally:
        if conn:
            conn.close()

# ============================================================
# SHARED PDF LAYOUT FUNCTION (QUOTE & INVOICE)
# ============================================================
def _create_quote_invoice_pdf(doc_type, doc_id, doc_date, client, project_name, notes, items,
                              charges, items_total, total_discounts, items_after_discount,
                              supervision, supervision_pct, admin, admin_pct, insurance, insurance_pct,
                              transport, transport_pct, contingency, contingency_pct,
                              subtotal_general, itbis, grand_total):
    """Shared PDF creation logic for quotes and invoices"""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # ==================== HEADER: METPRO BRANDING ====================
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_dir, "..", "assets", "logo.png")
        if os.path.exists(logo_path):
            pdf.image(logo_path, x=10, y=10, w=15)
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

    # Left column: Document info
    pdf.set_xy(left_x, start_y)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(80, 80, 80)
    label = 'Numero de Cotizacion:' if doc_type == 'COTIZACION' else 'Numero de Factura:'
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
    pdf.cell(0, 4, sanitize_text(doc_date), 0, 1)

    if project_name:
        pdf.set_x(left_x)
        pdf.set_font('Arial', 'B', 7)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(35, 4, 'Proyecto:', 0, 0)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 4, sanitize_text(project_name)[:60], 0, 1)

    # Right column: Client info
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

# ============================================================
# CONDUCE PDF (NO PRICES)
# ============================================================
def _create_conduce_pdf(doc_id, doc_date, client, project_name, notes, items):
    """Create conduce PDF - delivery note WITHOUT prices"""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # ==================== HEADER: METPRO BRANDING ====================
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_dir, "..", "assets", "logo.png")
        if os.path.exists(logo_path):
            pdf.image(logo_path, x=10, y=10, w=15)
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

    return pdf
