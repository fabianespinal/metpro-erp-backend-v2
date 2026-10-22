"""Strip internal identifiers from public (token) responses (debug B-22).

The public pages need document numbers, client/contact display data, lines and totals.
They never need database ids, the internal quote UUID, or who created the document.
"""
INTERNAL_KEYS = ("id", "quote_id", "client_id", "contact_id", "created_by_user_id", "created_by_name", "public_token")
INTERNAL_ITEM_KEYS = ("id", "quote_id", "invoice_id", "product_id")


# Approved 2026-10-22 (A3): customers never see the indirect-cost breakdown. The charge configuration and the
# per-charge amounts stay internal; the page gets only these totals.
INTERNAL_CONFIG_KEYS = ("included_charges", "dynamic_charges")
CUSTOMER_TOTAL_KEYS = (
    "items_total", "total_discounts", "items_after_discount", "subtotal_general",
    "itbis", "grand_total", "tax_label", "tax_rate",
)


def public_payload(doc: dict, totals_fn=None) -> dict:
    """totals_fn: callable returning the document's authoritative totals (computed from ALL lines and ALL charges).
    The payload carries `display_totals` (allowlisted keys only) so a page never re-adds visible lines, and hidden
    lines (print_on_pdf = false) are removed. No customer-facing hint says that anything is hidden."""
    from core.visibility import customer_items
    out = {k: v for k, v in doc.items() if k not in INTERNAL_KEYS and k not in INTERNAL_CONFIG_KEYS}
    if totals_fn is not None:
        t = totals_fn()
        out["display_totals"] = {k: t[k] for k in CUSTOMER_TOTAL_KEYS if k in t}
    if isinstance(out.get("items"), list):
        out["items"] = [
            {k: v for k, v in dict(item).items() if k not in INTERNAL_ITEM_KEYS and k != "print_on_pdf"}
            for item in customer_items(out["items"])
        ]
    return out
