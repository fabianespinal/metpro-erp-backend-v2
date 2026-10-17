"""Built-in cover page text. The wording is the approved Spanish template, used as provided."""

DOC_TYPES = ("quote", "invoice")

# Placeholders the backend fills in. {Logo} is part of the fixed layout, not the text.
COMMON_FIELDS = ("Contact_Name", "User_Name", "Client", "Date")
DOC_FIELD = {"quote": "No_Cotizacion", "invoice": "No_Factura"}

MAX_BODY_CHARS = 2500

DEFAULT_BODY = {
    "quote": (
        "Estimado {Client}:\n"
        "\n"
        "Gracias por confiar en Metpro. Nuestro compromiso es brindar resultados confiables, eficientes y "
        "duraderos, respaldados por un equipo profesional y una atención personalizada. Su apoyo nos ha "
        "ayudado a crecer y mejorar.\n"
        "\n"
        "Adjunta la cotización {No_Cotizacion}.\n"
        "\n"
        "Esta propuesta ha sido preparada exclusivamente para el cliente indicado, con el objetivo de "
        "presentar el alcance del trabajo, los costos estimados y las condiciones generales del servicio. "
        "Estamos disponibles para aclarar cualquier duda y ajustar la propuesta según sus necesidades.\n"
        "\n"
        "Un cordial saludo,"
    ),
    "invoice": (
        "Estimado Cliente:\n"
        "\n"
        "Adjunta la factura {No_Factura} por los productos y/o servicios proporcionados por Metpro SRL.\n"
        "Los detalles de la factura, incluido un desglose de los cargos, se incluyen para su referencia.\n"
        "\n"
        "Solicitamos amablemente que el pago se realice antes de la fecha de vencimiento, de acuerdo con "
        "los términos acordados. Si tiene alguna pregunta o necesita más aclaraciones sobre la factura, "
        "no dude en ponerse en contacto con nosotros.\n"
        "\n"
        "Gracias por seguir confiando en nosotros. Esperamos tener la oportunidad de colaborar nuevamente "
        "en el futuro.\n"
        "\n"
        "Un cordial saludo,"
    ),
}


def allowed_fields(doc_type: str):
    return COMMON_FIELDS + (DOC_FIELD[doc_type],)
