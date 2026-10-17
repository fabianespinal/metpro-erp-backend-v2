"""Terms and Conditions: section keys, fixed titles and the STARTER text.

The starter text is a generic draft. It contains no amounts, percentages or deadlines.
It must be reviewed by the company (and its legal advisor) before the page is switched on.
"""

# Order here is the order on the PDF.
SECTIONS = (
    ("payment_terms", "1. Condiciones de Pago"),
    ("warranty", "2. Garantía"),
    ("scope_limits", "3. Alcance y Limitaciones"),
    ("client_responsibilities", "4. Responsabilidades del Cliente"),
    ("cancellation", "5. Política de Cancelación"),
    ("safety", "6. Normas de Seguridad"),
    ("legal", "7. Información Legal"),
)
SECTION_KEYS = tuple(k for k, _ in SECTIONS)
TITLES = dict(SECTIONS)

PAGE_TITLE = "Términos y Condiciones"
MAX_SECTION_CHARS = 3000

DEFAULT_SECTIONS = {
    "payment_terms": (
        "El pago se realizará de acuerdo con las condiciones indicadas en la cotización o factura. "
        "Los pagos fuera de plazo podrán generar la suspensión de los trabajos o de las entregas "
        "hasta regularizar el saldo."
    ),
    "warranty": (
        "Metpro SRL garantiza los trabajos y materiales suministrados contra defectos de fabricación "
        "y mano de obra durante el período acordado por escrito. La garantía no cubre daños por mal uso, "
        "modificaciones no autorizadas, desgaste normal ni causas externas."
    ),
    "scope_limits": (
        "El alcance está limitado a lo descrito en este documento. Cualquier trabajo adicional o cambio "
        "solicitado por el cliente será cotizado y aprobado por escrito antes de su ejecución."
    ),
    "client_responsibilities": (
        "El cliente debe garantizar el acceso al sitio de trabajo, facilitar la información necesaria "
        "y obtener los permisos que le correspondan. Los retrasos atribuibles al cliente pueden modificar "
        "los plazos y costos acordados."
    ),
    "cancellation": (
        "Toda cancelación debe notificarse por escrito. Los materiales ya adquiridos y los trabajos ya "
        "realizados hasta la fecha de la notificación serán facturados al cliente."
    ),
    "safety": (
        "El cliente y su personal deben respetar las normas de seguridad vigentes en el sitio de trabajo "
        "y las indicaciones del personal de Metpro SRL. Metpro SRL podrá detener los trabajos si existen "
        "condiciones inseguras."
    ),
    "legal": (
        "Este documento se rige por las leyes de la República Dominicana. Cualquier controversia se "
        "resolverá de buena fe entre las partes y, de no lograrse acuerdo, ante los tribunales competentes."
    ),
}
