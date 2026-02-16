import json
import io
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from database import get_db_connection
from psycopg2.extras import RealDictCursor
from datetime import datetime
from pdf.utils.date_utils import format_date
from pdf.builder_quote import create_quote_pdf
from pdf.builder_invoice import create_invoice_pdf, create_conduce_pdf

# ============================================================
# QUOTE PDF GENERATION
# ============================================================
def generate_quote_pdf(quote_id: str) -> StreamingResponse:
    """Orchestrate quote PDF generation: fetch DB, prepare params, call builder."""
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
        raw_charges = quote.get('included_charges')

        # 1. Safely load JSON or fallback to empty dict
        if not raw_charges:
            charges = {}
        elif isinstance(raw_charges, str):
            try:
                charges = json.loads(raw_charges)
            except:
                charges = {}
        else:
            charges = raw_charges

        # 2. Ensure boolean flags ALWAYS exist
        charges.setdefault('supervision', True)
        charges.setdefault('admin', True)
        charges.setdefault('insurance', True)
        charges.setdefault('transport', True)
        charges.setdefault('contingency', True)

        # 3. Ensure percentage values ALWAYS exist
        defaults = {
            'supervision_percentage': 10.0,
            'admin_percentage': 4.0,
            'insurance_percentage': 1.0,
            'transport_percentage': 3.0,
            'contingency_percentage': 3.0
        }

        for key, default in defaults.items():
            charges.setdefault(key, default)

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

        # Fix date logic: convert datetime → string using utility
        raw_date = quote.get("created_at") or quote.get("updated_at") or ""
        doc_date = format_date(raw_date)

        # Call builder
        pdf_stream = create_quote_pdf(
            doc_type='COTIZACION',
            doc_id=quote["quote_id"],
            doc_date=doc_date,
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

        return StreamingResponse(
            pdf_stream,
            media_type='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename={quote_id}_cotizacion.pdf'
            }
        )

    except HTTPException:
        raise

    except Exception as e:
        print(f"PDF GENERATION ERROR for quote {quote_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Quote PDF generation failed: {str(e)}")

    finally:
        if conn:
            conn.close()

# ============================================================
# INVOICE PDF GENERATION
# ============================================================
def generate_invoice_pdf(invoice_id: int) -> StreamingResponse:
    """Orchestrate invoice PDF generation: fetch DB, prepare params, call builder."""
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

        # Fix date logic
        doc_date = format_date(invoice["invoice_date"])

        # Call builder
        pdf_stream = create_invoice_pdf(
            doc_type='FACTURA',
            doc_id=invoice["invoice_number"],
            doc_date=doc_date,
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

        return StreamingResponse(
            pdf_stream,
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
    """Orchestrate conduce PDF generation: fetch DB, prepare params, call builder."""
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

        # Fix date logic
        doc_date = format_date(invoice["invoice_date"])

        # Call builder
        pdf_stream = create_conduce_pdf(
            doc_id=invoice["invoice_number"].replace('INV-', 'CD-'),
            doc_date=doc_date,
            client=client,
            project_name=project_name,
            notes=invoice.get('notes'),
            items=items
        )

        return StreamingResponse(
            pdf_stream,
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