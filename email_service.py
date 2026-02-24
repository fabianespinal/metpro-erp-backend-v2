import os
import resend
import base64

resend.api_key = os.getenv("RESEND_API_KEY")

FROM_EMAIL = "noreply@send.metprord.site"  # verified domain


def send_quote_email(contact_email, contact_name, company_name, project_name, quote_id, pdf_bytes):
    params = {
        "from": FROM_EMAIL,
        "to": [contact_email],
        "subject": f"Cotización {quote_id} - {project_name or company_name}",
        "html": f"""
            <p>Estimado/a {contact_name},</p>
            <p>Adjunto encontrará la cotización <strong>{quote_id}</strong> correspondiente al proyecto <strong>{project_name or 'su proyecto'}</strong>.</p>
            <p>También puede ver el documento en línea usando el siguiente enlace:</p>
            <p><a href="https://app.metprord.com/quotes/{quote_id}/view">Ver Cotización en línea</a></p>
            <p>Quedamos a su disposición para cualquier consulta.</p>
            <br/>
            <p>Atentamente,<br/>Equipo METPRO</p>
        """,
        "attachments": [
            {
                "filename": f"cotizacion_{quote_id}.pdf",
                "content": base64.b64encode(pdf_bytes).decode(),
            }
        ],
    }
    return resend.Emails.send(params)


def send_invoice_email(contact_email, contact_name, company_name, project_name, invoice_id, pdf_bytes):
    params = {
        "from": FROM_EMAIL,
        "to": [contact_email],
        "subject": f"Factura {invoice_id} - {project_name or company_name}",
        "html": f"""
            <p>Estimado/a {contact_name},</p>
            <p>Adjunto encontrará la factura <strong>{invoice_id}</strong> correspondiente al proyecto <strong>{project_name or 'su proyecto'}</strong>.</p>
            <p>También puede ver el documento en línea usando el siguiente enlace:</p>
            <p><a href="https://app.metprord.com/invoices/{invoice_id}/view">Ver Factura en línea</a></p>
            <p>Quedamos a su disposición para cualquier consulta.</p>
            <br/>
            <p>Atentamente,<br/>Equipo METPRO</p>
        """,
        "attachments": [
            {
                "filename": f"factura_{invoice_id}.pdf",
                "content": base64.b64encode(pdf_bytes).decode(),
            }
        ],
    }
    return resend.Emails.send(params)