"""Unified success response shape.

    {"data": <payload>, "success": true}

Module 1: helper only. No route uses it yet. Routes are migrated in later modules.
Payloads are passed through unchanged. Binary and streaming responses (PDFs) are not wrapped.
"""
from typing import Any


def success_body(payload: Any) -> dict:
    return {"data": payload, "success": True}
