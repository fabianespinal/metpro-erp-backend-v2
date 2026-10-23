"""Strip internal identifiers from public (token) responses (debug B-22).

The public pages need document numbers, client/contact display data, lines and totals.
They never need database ids, the internal quote UUID, or who created the document.
"""
INTERNAL_KEYS = ("id", "quote_id", "client_id", "contact_id", "created_by_user_id", "created_by_name", "public_token", "quote_type")
INTERNAL_ITEM_KEYS = ("id", "quote_id", "invoice_id", "product_id")


def public_payload(doc: dict, totals_fn=None) -> dict:
    """totals_fn: callable returning the document's authoritative totals (computed from ALL lines).
    A3: when some lines are hidden they are removed here and the totals travel with the payload, because a page
    that re-adds the visible lines would show a different number. Without hidden lines the payload is unchanged."""
    from core.visibility import customer_items, has_hidden
    out = {k: v for k, v in doc.items() if k not in INTERNAL_KEYS}
    # PDF update: print_items = false means the customer sees no item lines at all, only the project, charges and totals.
    items_off = out.pop("print_items", True) is False
    if items_off:
        out["print_items"] = False  # the key travels only when off, so every other payload is unchanged
    if isinstance(out.get("items"), list) and (items_off or has_hidden(out["items"])):
        if totals_fn is not None:
            out["display_totals"] = totals_fn()
        out["items"] = [] if items_off else customer_items(out["items"])
    if isinstance(out.get("items"), list):
        out["items"] = [
            {k: v for k, v in dict(item).items() if k not in INTERNAL_ITEM_KEYS and k != "print_on_pdf"} for item in out["items"]
        ]
    return out
