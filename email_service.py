import os
from html import escape as _esc

import resend

resend.api_key = os.getenv("RESEND_API_KEY")

FROM_EMAIL = "METPRO SRL <noreply@metprord.site>"


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------
def clean_text(value: str) -> str:
    """Remove newlines and sanitize text for email subjects."""
    if not value:
        return ""
    return value.replace("\n", " ").replace("\r", " ").strip()


# ---------------------------------------------------------
# QUOTES
# ---------------------------------------------------------
def send_quote_email(contact_email, contact_name, company_name, project_name, quote_id, public_token, pdf_bytes, extra_attachments=None):

    clean_title = clean_text(project_name or company_name)
    # Client-supplied text is escaped before it goes into HTML.
    safe_name, safe_doc, safe_project = _esc(contact_name or ""), _esc(str(quote_id)), _esc(project_name or "su proyecto")

    html = f"""
        <p>Estimado/a {safe_name},</p>

        <p>Adjunto encontrará la cotización <strong>{safe_doc}</strong> correspondiente al proyecto <strong>{safe_project}</strong>.</p>

        <p>Puede ver la cotización en línea aquí:</p>

        <p>
            <a href="https://metprord.site/q/{public_token}"
               style="display:inline-block;padding:12px 20px;background:#0052cc;color:white;
                      text-decoration:none;border-radius:6px;font-weight:bold;font-size:15px;">
                Ver Cotización en Línea
            </a>
        </p>

        <p>Quedamos a su disposición para cualquier consulta.</p>
        <br/>
        <p>Atentamente,<br/>Equipo METPRO</p>
    """

    params = {
        "from": FROM_EMAIL,
        "to": [contact_email],
        "subject": f"Cotización {quote_id} - {clean_title}",
        "html": html,
        "attachments": [
            {
                "filename": f"cotizacion_{quote_id}.pdf",
                "content": list(pdf_bytes),
            },
            *(extra_attachments or []),
        ],
    }

    return resend.Emails.send(params)


# ---------------------------------------------------------
# INVOICES
# ---------------------------------------------------------
def send_invoice_email(contact_email, contact_name, company_name, project_name, invoice_id, public_token, pdf_bytes, extra_attachments=None):

    clean_title = clean_text(project_name or company_name)
    # Client-supplied text is escaped before it goes into HTML.
    safe_name, safe_doc, safe_project = _esc(contact_name or ""), _esc(str(invoice_id)), _esc(project_name or "su proyecto")

    html = f"""
        <p>Estimado/a {safe_name},</p>

        <p>Adjunto encontrará la factura <strong>{safe_doc}</strong> correspondiente al proyecto <strong>{safe_project}</strong>.</p>

        <p>Puede ver la factura en línea aquí:</p>

        <p>
            <a href="https://metprord.site/inv/{public_token}"
               style="display:inline-block;padding:12px 20px;background:#0a7d4f;color:white;
                      text-decoration:none;border-radius:6px;font-weight:bold;font-size:15px;">
                Ver Factura
            </a>
        </p>

        <p>Quedamos a su disposición para cualquier consulta.</p>
        <br/>
        <p>Atentamente,<br/>Equipo METPRO</p>
    """

    params = {
        "from": FROM_EMAIL,
        "to": [contact_email],
        "subject": f"Factura {invoice_id} - {clean_title}",
        "html": html,
        "attachments": [
            {
                "filename": f"factura_{invoice_id}.pdf",
                "content": list(pdf_bytes),
            },
            *(extra_attachments or []),
        ],
    }

    return resend.Emails.send(params)