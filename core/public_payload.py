"""Strip internal identifiers from public (token) responses (debug B-22).

The public pages need document numbers, client/contact display data, lines and totals.
They never need database ids, the internal quote UUID, or who created the document.
"""
INTERNAL_KEYS = ("id", "quote_id", "client_id", "contact_id", "created_by_user_id", "created_by_name", "public_token")
INTERNAL_ITEM_KEYS = ("id", "quote_id", "invoice_id", "product_id")


def public_payload(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k not in INTERNAL_KEYS}
    if isinstance(out.get("items"), list):
        out["items"] = [
            {k: v for k, v in dict(item).items() if k not in INTERNAL_ITEM_KEYS} for item in out["items"]
        ]
    return out
