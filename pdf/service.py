import json
import io
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from backend.database import get_db_connection
from psycopg2.extras import RealDictCursor
from datetime import datetime
from backend.pdf.utils.date_utils import format_date
from backend.pdf.builder_quote import create_quote_pdf
from backend.pdf.builder_invoice import create_invoice_pdf
from backend.pdf.builder_conduce import create_conduce_pdf


# ============================================================
# QUOTE PDF GENERATION
# ============================================================
def generate_quote_pdf(quote_id: str) -> StreamingResponse:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute('SELECT * FROM quotes WHERE quote_id = %s', (quote_id,))
        quote = cursor.fetchone()
        if not quote:
            raise HTTPException(status_code=404, detail='Quote not found')
        quote = dict(quote)

        cursor.execute('SELECT * FROM clients WHERE id = %s', (quote['client_id'],))
        client = cursor.fetchone()
        if not client:
            raise HTTPException(status_code=404, detail='Client not found')
        client = dict(client)

        cursor.execute('SELECT * FROM quote_items WHERE quote_id = %s', (quote_id,))
        items = [dict(row) for row in cursor.fetchall()]

        raw_charges = quote.get('included_charges')
        if not raw_charges:
            charges = {}
        elif isinstance(raw_charges, str):
            try:
                charges = json.loads(raw_charges)
            except Exception:
                charges = {}
        else:
            charges = raw_charges

        charges.setdefault('supervision', True)
        charges.setdefault('admin', True)
        charges.setdefault('insurance', True)
        charges.setdefault('transport', True)
        charges.setdefault('contingency', True)
        charges.setdefault('supervision_percentage', 10.0)
        charges.setdefault('admin_percentage', 4.0)
        charges.setdefault('insurance_percentage', 1.0)
        charges.setdefault('transport_percentage', 3.0)
        charges.setdefault('contingency_percentage', 3.0)

        items_total = sum(float(item.get('quantity') or 0) * float(item.get('unit_price') or 0) for item in items)

        total_discounts = 0
        for item in items:
            subtotal = float(item.get('quantity') or 0) * float(item.get('unit_price') or 0)
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

        raw_date = quote.get('created_at') or quote.get('updated_at') or ''
        doc_date = format_date(raw_date)

        payment_terms = quote.get('payment_terms') or ''
        valid_until = quote.get('valid_until') or ''

        pdf_stream = create_quote_pdf(
            doc_type='COTIZACION',
            doc_id=quote['quote_id'],
            doc_date=doc_date,
            client=client,
            project_name=quote.get('project_name'),
            notes=quote.get('notes'),
            payment_terms=payment_terms,
            valid_until=valid_until,
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
            headers={'Content-Disposition': f'attachment; filename={quote_id}_cotizacion.pdf'}
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
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute('SELECT * FROM invoices WHERE id = %s', (invoice_id,))
        invoice = cursor.fetchone()
        if not invoice:
            raise HTTPException(status_code=404, detail='Invoice not found')
        invoice = dict(invoice)

        cursor.execute('SELECT * FROM clients WHERE id = %s', (invoice['client_id'],))
        client = cursor.fetchone()
        if not client:
            raise HTTPException(status_code=404, detail='Client not found')
        client = dict(client)

        cursor.execute('SELECT * FROM quote_items WHERE quote_id = %s', (invoice['quote_id'],))
        items = [dict(row) for row in cursor.fetchall()]

        cursor.execute(
            'SELECT included_charges, project_name, payment_terms, valid_until '
            'FROM quotes WHERE quote_id = %s',
            (invoice['quote_id'],)
        )
        quote_data = cursor.fetchone()

        if quote_data:
            raw_charges = quote_data['included_charges']
            if isinstance(raw_charges, str):
                try:
                    charges = json.loads(raw_charges)
                except Exception:
                    charges = {}
            else:
                charges = raw_charges or {}

            project_name = quote_data.get('project_name')
            payment_terms = quote_data.get('payment_terms') or ''
            valid_until = quote_data.get('valid_until') or ''
        else:
            charges = {
                'supervision': True, 'supervision_percentage': 10.0,
                'admin': True, 'admin_percentage': 4.0,
                'insurance': True, 'insurance_percentage': 1.0,
                'transport': True, 'transport_percentage': 3.0,
                'contingency': True, 'contingency_percentage': 3.0
            }
            project_name = None
            payment_terms = ''
            valid_until = ''

        # Fetch payments
        cursor.execute(
            'SELECT * FROM invoice_payments WHERE invoice_id = %s ORDER BY id ASC',
            (invoice_id,)
        )
        payments = [dict(row) for row in cursor.fetchall()]

        amount_paid = float(invoice.get('amount_paid') or 0)
        amount_due = float(invoice.get('amount_due') or 0)

        # If amount_paid/amount_due not stored on invoice, calculate from payments
        if amount_paid == 0 and payments:
            amount_paid = sum(float(p.get('amount') or 0) for p in payments)
            amount_due = float(invoice.get('total_amount') or 0) - amount_paid

        items_total = sum(float(item.get('quantity') or 0) * float(item.get('unit_price') or 0) for item in items)

        total_discounts = 0
        for item in items:
            subtotal = float(item.get('quantity') or 0) * float(item.get('unit_price') or 0)
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

        doc_date = format_date(invoice['invoice_date'])

        pdf_stream = create_invoice_pdf(
            doc_type='FACTURA',
            doc_id=invoice['invoice_number'],
            doc_date=doc_date,
            client=client,
            project_name=project_name,
            notes=invoice.get('notes'),
            payment_terms=payment_terms,
            valid_until=valid_until,
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
            grand_total=grand_total,
            payments=payments,
            amount_paid=amount_paid,
            amount_due=amount_due
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
        raise HTTPException(status_code=500, detail=f"Invoice PDF generation failed: {str(e)}")
    finally:
        if conn:
            conn.close()


# ============================================================
# CONDUCE PDF GENERATION (NO PRICES)
# ============================================================
def generate_conduce_pdf(invoice_id: int) -> StreamingResponse:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute('SELECT * FROM invoices WHERE id = %s', (invoice_id,))
        invoice = cursor.fetchone()
        if not invoice:
            raise HTTPException(status_code=404, detail='Invoice not found')
        invoice = dict(invoice)

        cursor.execute('SELECT * FROM clients WHERE id = %s', (invoice['client_id'],))
        client = cursor.fetchone()
        if not client:
            raise HTTPException(status_code=404, detail='Client not found')
        client = dict(client)

        cursor.execute('SELECT * FROM quote_items WHERE quote_id = %s', (invoice['quote_id'],))
        items = [dict(row) for row in cursor.fetchall()]

        cursor.execute('SELECT project_name FROM quotes WHERE quote_id = %s', (invoice['quote_id'],))
        quote_data = cursor.fetchone()
        project_name = quote_data.get('project_name') if quote_data else None

        doc_date = format_date(invoice['invoice_date'])

        pdf_stream = create_conduce_pdf(
            doc_id=invoice['invoice_number'].replace('INV-', 'CD-'),
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
        raise HTTPException(status_code=500, detail=f"Conduce generation failed: {str(e)}")
    finally:
        if conn:
            conn.close()
