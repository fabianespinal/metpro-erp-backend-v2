def render_quote_email(client_name: str, quote_id: int, public_url: str) -> str:
    return f"""
    <div style="font-family: Arial, sans-serif; padding: 20px; background-color: #f7f7f7;">
        
        <!-- Logo -->
        <div style="text-align: center; margin-bottom: 30px;">
            <img src="https://metprord.site/logo.png" alt="METPRO Logo" style="width: 180px;">
        </div>

        <!-- Card -->
        <div style="max-width: 600px; margin: auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">

            <h2 style="text-align: center; color: #333;">Cotización #{quote_id}</h2>

            <p style="font-size: 16px; color: #444;">
                Estimado/a <strong>{client_name}</strong>,
            </p>

            <p style="font-size: 15px; color: #555;">
                Le enviamos la cotización solicitada. Puede revisarla en línea o descargar el archivo PDF adjunto.
            </p>

            <!-- CTA Button -->
            <div style="text-align: center; margin: 30px 0;">
                <a href="{public_url}" 
                   style="background-color: #0052cc; color: white; padding: 14px 28px; 
                          text-decoration: none; border-radius: 6px; font-size: 16px;">
                    Ver Cotización
                </a>
            </div>

            <p style="font-size: 14px; color: #777;">
                Si tiene alguna pregunta o desea realizar cambios, no dude en contactarnos.
            </p>

        </div>

        <!-- Footer -->
        <p style="text-align: center; font-size: 12px; color: #999; margin-top: 20px;">
            © {2026} METPRO. Todos los derechos reservados.
        </p>

    </div>
    """


def render_invoice_email(client_name: str, invoice_id: int, public_url: str) -> str:
    return f"""
    <div style="font-family: Arial, sans-serif; padding: 20px; background-color: #f4f4f4;">
        
        <!-- Logo -->
        <div style="text-align: center; margin-bottom: 30px;">
            <img src="https://metprord.site/logo.png" alt="METPRO Logo" style="width: 180px;">
        </div>

        <!-- Card -->
        <div style="
            max-width: 600px; 
            margin: auto; 
            background: white; 
            padding: 30px; 
            border-radius: 10px; 
            border: 1px solid #e0e0e0;
            box-shadow: 0 3px 10px rgba(0,0,0,0.08);
        ">

            <h2 style="text-align: center; color: #222; margin-bottom: 10px;">
                Factura #{invoice_id}
            </h2>

            <p style="font-size: 16px; color: #444;">
                Estimado/a <strong>{client_name}</strong>,
            </p>

            <p style="font-size: 15px; color: #555;">
                Le enviamos la factura correspondiente a los servicios prestados. 
                Puede revisarla en línea o descargar el archivo PDF adjunto.
            </p>

            <!-- CTA Button -->
            <div style="text-align: center; margin: 30px 0;">
                <a href="{public_url}" 
                   style="
                        background-color: #0a7d4f; 
                        color: white; 
                        padding: 14px 28px; 
                        text-decoration: none; 
                        border-radius: 6px; 
                        font-size: 16px;
                        font-weight: bold;
                   ">
                    Ver / Pagar Factura
                </a>
            </div>

            <p style="font-size: 14px; color: #777;">
                Si tiene alguna pregunta sobre esta factura o necesita asistencia, 
                estamos a su disposición.
            </p>

        </div>

        <!-- Footer -->
        <p style="text-align: center; font-size: 12px; color: #999; margin-top: 20px;">
            © {2026} METPRO. Todos los derechos reservados.
        </p>

    </div>
    """