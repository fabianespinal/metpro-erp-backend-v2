from core.errors import api_error
import json
import io
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from database import get_db_connection
from psycopg2.extras import RealDictCursor
from datetime import datetime
from pdf.utils.date_utils import format_date
from core.dates import local_date
from pdf.builder_quote import create_quote_pdf
from invoices.service import invoice_lines_and_totals
from quotes.dynamic_charges import dynamic_charges_total
from pdf.builder_invoice import create_invoice_pdf
from pdf.builder_conduce import create_conduce_pdf
from pdf.utils.layout_utils import build_quote_invoice_pdf
from pdf.utils.signer import resolve_signer_name
from core.numbering import quote_label_for, conduce_label, conduce_label_from_invoice_number
from core.errors import internal_error
from company_settings.service import seal_for_pdf
import logging

logger = logging.getLogger("metpro.pdf")


# ============================================================
# QUOTE PDF GENERATION
# ============================================================
def generate_quote_pdf(quote_id: str, current_user: dict = None, print_seal: bool = False) -> StreamingResponse:
    seal = seal_for_pdf(print_seal)  # None unless the request asks for it
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute('SELECT * FROM quotes WHERE quote_id = %s', (quote_id,))
        quote = cursor.fetchone()
        if not quote:
            raise api_error(404, "Cotización no encontrada", "QUOTE_NOT_FOUND")
        quote = dict(quote)

        cursor.execute('SELECT * FROM clients WHERE id = %s', (quote['client_id'],))
        raw_client = cursor.fetchone()
        if not raw_client:
            raise api_error(404, "Cliente no encontrado", "CLIENT_NOT_FOUND")
        raw_client = dict(raw_client)

        # Fetch the contact selected on this quote — not any company default
        contact = {}
        if quote.get('contact_id'):
            cursor.execute(
                'SELECT name, email, phone FROM contacts WHERE id = %s',
                (quote['contact_id'],)
            )
            row = cursor.fetchone()
            if row:
                contact = dict(row)

        # Build client dict with keys that layout_utils.py expects
        client = {
            'company_name': raw_client.get('company_name', ''),
            'address':      raw_client.get('address', ''),
            'tax_id':       raw_client.get('tax_id', ''),
            'contact_name': contact.get('name', ''),
            'email':        contact.get('email', ''),
            'phone':        contact.get('phone', ''),
        }

        cursor.execute('SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id', (quote_id,))
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

        # Debug B-13: the same totals as the emailed and public PDFs (stored totals win).
        # Charge flags are no longer defaulted to ON here: missing flags mean OFF everywhere.
        from quotes.service import quote_document_totals
        t = quote_document_totals(quote, items, charges)
        items_total, total_discounts = t['items_total'], t['total_discounts']
        items_after_discount = t['items_after_discount']
        supervision, admin, insurance = t['supervision'], t['admin'], t['insurance']
        transport, contingency = t['transport'], t['contingency']
        subtotal_general, itbis, grand_total = t['subtotal_general'], t['itbis'], t['grand_total']
        supervision_pct = float(charges.get('supervision_percentage', 10.0))
        admin_pct = float(charges.get('admin_percentage', 4.0))
        insurance_pct = float(charges.get('insurance_percentage', 1.0))
        transport_pct = float(charges.get('transport_percentage', 3.0))
        contingency_pct = float(charges.get('contingency_percentage', 3.0))

        raw_date = quote.get('created_at') or quote.get('updated_at') or ''
        # B-04: quotes.created_at is naive UTC; print the Santo Domingo date (same DD/MM/YYYY format).
        local = local_date(raw_date)
        doc_date = f"{local[8:10]}/{local[5:7]}/{local[0:4]}" if len(local) == 10 and local[4] == '-' else format_date(raw_date)

        payment_terms = quote.get('payment_terms') or ''
        valid_until = quote.get('valid_until') or ''

        pdf_stream = build_quote_invoice_pdf(
            doc_type='COTIZACION',
            doc_id=quote_label_for(quote),
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
            grand_total=grand_total,
            signer_name=resolve_signer_name(current_user, quote.get('created_by_name')),
            seal=seal
        )

        return StreamingResponse(
            pdf_stream,
            media_type='application/pdf',
            headers={'Content-Disposition': f'attachment; filename={quote_label_for(quote)}_cotizacion.pdf'}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("PDF generation failed for quote %s", quote_id)
        raise internal_error("No se pudo generar el PDF de la cotización", e)
    finally:
        if conn:
            conn.close()


# ============================================================
# INVOICE PDF GENERATION
# ============================================================
def generate_invoice_pdf(invoice_id: int, current_user: dict = None, print_seal: bool = False) -> StreamingResponse:
    seal = seal_for_pdf(print_seal)  # None unless the request asks for it
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute('SELECT * FROM invoices WHERE id = %s', (invoice_id,))
        invoice = cursor.fetchone()
        if not invoice:
            raise api_error(404, "Factura no encontrada", "INVOICE_NOT_FOUND")
        invoice = dict(invoice)

        cursor.execute('SELECT * FROM clients WHERE id = %s', (invoice['client_id'],))
        raw_client = cursor.fetchone()
        if not raw_client:
            raise api_error(404, "Cliente no encontrado", "CLIENT_NOT_FOUND")
        raw_client = dict(raw_client)

        # Invoice carries the same contact as its source quote (Option A)
        contact = {}
        contact_id = invoice.get('contact_id')
        if not contact_id and invoice.get('quote_id'):
            cursor.execute(
                'SELECT contact_id FROM quotes WHERE quote_id = %s',
                (invoice['quote_id'],)
            )
            quote_row = cursor.fetchone()
            if quote_row:
                contact_id = quote_row.get('contact_id')
        if contact_id:
            cursor.execute(
                'SELECT name, email, phone FROM contacts WHERE id = %s',
                (contact_id,)
            )
            row = cursor.fetchone()
            if row:
                contact = dict(row)

        client = {
            'company_name': raw_client.get('company_name', ''),
            'address':      raw_client.get('address', ''),
            'tax_id':       raw_client.get('tax_id', ''),
            'contact_name': contact.get('name', ''),
            'email':        contact.get('email', ''),
            'phone':        contact.get('phone', ''),
        }

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
            'SELECT * FROM invoice_payments WHERE invoice_id = %s AND voided_at IS NULL ORDER BY id ASC',
            (invoice_id,)
        )
        payments = [dict(row) for row in cursor.fetchall()]

        # F2: lines from invoice_items; grand total = billed invoices.total_amount.
        items, t = invoice_lines_and_totals(dict(invoice), charges)
        grand_total = t['grand_total']

        # Balance from payments recorded for THIS invoice (filtered by invoice_id above).
        amount_paid = sum(float(p.get('amount') or 0) for p in payments)
        amount_due = round(grand_total - amount_paid, 2)

        items_total = t['items_total']
        total_discounts = t['total_discounts']
        items_after_discount = t['items_after_discount']

        supervision_pct = float(charges.get('supervision_percentage', 10.0))
        admin_pct = float(charges.get('admin_percentage', 4.0))
        insurance_pct = float(charges.get('insurance_percentage', 1.0))
        transport_pct = float(charges.get('transport_percentage', 3.0))
        contingency_pct = float(charges.get('contingency_percentage', 3.0))

        supervision = t['supervision']
        admin = t['admin']
        insurance = t['insurance']
        transport = t['transport']
        contingency = t['contingency']

        subtotal_general = t['subtotal_general']
        itbis = t['itbis']

        doc_date = format_date(invoice['invoice_date'])

        pdf_stream = build_quote_invoice_pdf(
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
            amount_due=amount_due,
            signer_name=resolve_signer_name(current_user, invoice.get('created_by_name')),
            seal=seal
        )

        return StreamingResponse(
            pdf_stream,
            media_type='application/pdf',
            headers={'Content-Disposition': f'attachment; filename={invoice["invoice_number"]}_factura.pdf'}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("PDF generation failed for invoice %s", invoice_id)
        raise internal_error("No se pudo generar el PDF de la factura", e)
    finally:
        if conn:
            conn.close()


def _record_conduce(conn, cursor, conduce_number, invoice_id, quote_number):
    """
    Store the conduce number with its invoice and originating quote number.
    Idempotent (conduce_number is unique). A failure here never blocks the PDF.
    """
    try:
        cursor.execute(
            "INSERT INTO conduces (conduce_number, invoice_id, quote_number) "
            "VALUES (%s, %s, %s) ON CONFLICT (conduce_number) DO NOTHING",
            (conduce_number, invoice_id, quote_number),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Could not record conduce %s", conduce_number)


# ============================================================
# CONDUCE PDF GENERATION (NO PRICES)
# ============================================================
def generate_conduce_pdf(invoice_id: int, current_user: dict = None, print_seal: bool = False) -> StreamingResponse:
    seal = seal_for_pdf(print_seal)  # None unless the request asks for it
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute('SELECT * FROM invoices WHERE id = %s', (invoice_id,))
        invoice = cursor.fetchone()
        if not invoice:
            raise api_error(404, "Factura no encontrada", "INVOICE_NOT_FOUND")
        invoice = dict(invoice)

        cursor.execute('SELECT * FROM clients WHERE id = %s', (invoice['client_id'],))
        raw_client = cursor.fetchone()
        if not raw_client:
            raise api_error(404, "Cliente no encontrado", "CLIENT_NOT_FOUND")
        raw_client = dict(raw_client)

        # Invoice carries the same contact as its source quote (Option A)
        contact = {}
        contact_id = invoice.get('contact_id')
        if not contact_id and invoice.get('quote_id'):
            cursor.execute(
                'SELECT contact_id FROM quotes WHERE quote_id = %s',
                (invoice['quote_id'],)
            )
            quote_row = cursor.fetchone()
            if quote_row:
                contact_id = quote_row.get('contact_id')
        if contact_id:
            cursor.execute(
                'SELECT name, email, phone FROM contacts WHERE id = %s',
                (contact_id,)
            )
            row = cursor.fetchone()
            if row:
                contact = dict(row)

        client = {
            'company_name': raw_client.get('company_name', ''),
            'address':      raw_client.get('address', ''),
            'contact_name': contact.get('name', ''),
            'email':        contact.get('email', ''),
            'phone':        contact.get('phone', ''),
        }

        items, _ = invoice_lines_and_totals(dict(invoice), {})

        cursor.execute('SELECT project_name, quote_number FROM quotes WHERE quote_id = %s', (invoice['quote_id'],))
        quote_data = cursor.fetchone()
        project_name = quote_data.get('project_name') if quote_data else None
        quote_number = invoice.get('quote_number') or (quote_data.get('quote_number') if quote_data else None)

        # Same numeric suffix as the quote and invoice: Q-10002 -> F-10002 -> C-10002.
        # Legacy invoices with no quote number keep the old derived label.
        # A re-invoice after a cancel (B-06) is F-10002-2, so its conduce is C-10002-2.
        if str(invoice.get('invoice_number') or '').startswith('F-'):
            conduce_number = conduce_label_from_invoice_number(invoice['invoice_number'])
        elif quote_number:
            conduce_number = conduce_label(quote_number)
        else:
            conduce_number = conduce_label_from_invoice_number(invoice['invoice_number'])
        _record_conduce(conn, cursor, conduce_number, invoice_id, quote_number)

        doc_date = format_date(invoice['invoice_date'])

        pdf_stream = create_conduce_pdf(
            doc_id=conduce_number,
            doc_date=doc_date,
            client=client,
            project_name=project_name,
            notes=invoice.get('notes'),
            items=items,
            signer_name=resolve_signer_name(current_user, invoice.get('created_by_name')),
            seal=seal
        )

        return StreamingResponse(
            pdf_stream,
            media_type='application/pdf',
            headers={'Content-Disposition': f'attachment; filename={conduce_number}_conduce.pdf'}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Conduce generation failed for invoice %s", invoice_id)
        raise internal_error("No se pudo generar el conduce", e)
    finally:
        if conn:
            conn.close()
