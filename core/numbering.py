"""
Document numbering chain: one quote number, three labels.

    Quote Q-10002  ->  Invoice F-10002  ->  Conduce C-10002

The numeric part is quotes.quote_number (from quote_number_seq). Invoices and
conduces store it, so the chain never depends on parsing a label.
"""
from typing import Optional


def quote_label(quote_number) -> str:
    return f"Q-{quote_number}"


def invoice_label(quote_number) -> str:
    return f"F-{quote_number}"


def conduce_label(quote_number) -> str:
    return f"C-{quote_number}"


def conduce_label_from_invoice_number(invoice_number: Optional[str]) -> str:
    """
    Conduce label for an invoice whose quote_number is unknown.
    F-10002 -> C-10002. Legacy INV-<timestamp> -> CD-<timestamp> (unchanged behaviour).
    """
    num = invoice_number or ""
    if num.startswith("F-"):
        return "C-" + num[2:]
    return num.replace("INV-", "CD-")
