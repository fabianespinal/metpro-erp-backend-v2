import os
import resend

resend.api_key = os.getenv("RESEND_API_KEY")

# Your verified domain
FROM_EMAIL = "METPRO SRL <noreply@send.metprord.site>"


# ---------------------------------------------------------
# QUOTES
# ---------------------------------------------------------
def send_quote_email(contact_email, contact_name, company_name, project_name, quote_id, pdf_bytes):
    html = f"""
        <p>Estimado/a {contact_name},</p>

        <p>Adjunto encontrará la cotización <strong>{quote_id}</strong> correspondiente al proyecto <strong>{project_name or 'su proyecto'}</strong>.</p>

        <p>Puede ver la cotización en línea aquí:</p>
        <p><a href="https://metprord.site/q/{quote_id}">Ver Cotización en línea</a></p>

        <p>O descargar el PDF directamente:</p>
        <p>
            <a href="https://api.metprord.com/quotes/{quote_id}/pdf"
               style="display:inline-block;padding:10px 16px;background:#0052cc;color:white;
                      text-decoration:none;border-radius:6px;font-weight:bold;">
                Descargar PDF
            </a>
        </p>

        <p>Quedamos a su disposición para cualquier consulta.</p>
        <br/>
        <p>Atentamente,<br/>Equipo METPRO</p>
    """

    params = {
        "from": FROM_EMAIL,
        "to": [contact_email],
        "subject": f"Cotización {quote_id} - {project_name or company_name}",
        "html": html,
        "attachments": [
            {
                "filename": f"cotizacion_{quote_id}.pdf",
                "content": list(pdf_bytes),  # Resend requires list of ints
            }
        ],
    }

    return resend.Emails.send(params)


# ---------------------------------------------------------
# INVOICES
# ---------------------------------------------------------
def send_invoice_email(contact_email, contact_name, company_name, project_name, invoice_id, pdf_bytes):
    html = f"""
        <p>Estimado/a {contact_name},</p>

        <p>Adjunto encontrará la factura <strong>{invoice_id}</strong> correspondiente al proyecto <strong>{project_name or 'su proyecto'}</strong>.</p>

        <p>Puede ver la factura en línea aquí:</p>
        <p><a href="https://metprord.site/inv/{invoice_id}">Ver Factura en línea</a></p>

        <p>O descargar el PDF directamente:</p>
        <p>
            <a href="https://api.metprord.com/invoices/{invoice_id}/pdf"
               style="display:inline-block;padding:10px 16px;background:#0052cc;color:white;
                      text-decoration:none;border-radius:6px;font-weight:bold;">
                Descargar PDF
            </a>
        </p>

        <p>Quedamos a su disposición para cualquier consulta.</p>
        <br/>
        <p>Atentamente,<br/>Equipo METPRO</p>
    """

    params = {
        "from": FROM_EMAIL,
        "to": [contact_email],
        "subject": f"Factura {invoice_id} - {project_name or company_name}",
        "html": html,
        "attachments": [
            {
                "filename": f"factura_{invoice_id}.pdf",
                "content": list(pdf_bytes),
            }
        ],
    }

    return resend.Emails.send(params)