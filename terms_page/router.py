from typing import Dict, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth.service import require_role
from pdf.builder_terms import create_terms_pdf
from terms_page import service
from terms_page.defaults import DEFAULT_SECTIONS, SECTIONS, SECTION_KEYS

router = APIRouter(prefix="/terms", tags=["terms"])


class TermsSave(BaseModel):
    sections: Dict[str, str]
    enabled_quote: bool = False
    enabled_invoice: bool = False


class TermsPreview(BaseModel):
    sections: Optional[Dict[str, str]] = None


def _with_meta(settings: dict) -> dict:
    """GET and PUT return the same shape; the editor re-renders from either."""
    return {
        **settings,
        "titles": dict(SECTIONS),
        "order": list(SECTION_KEYS),
        "defaults": DEFAULT_SECTIONS,
    }


@router.get("/")
def get_terms(_admin: dict = Depends(require_role("admin"))):
    return _with_meta(service.get_settings())


@router.put("/")
def save_terms(payload: TermsSave, admin: dict = Depends(require_role("admin"))):
    return _with_meta(service.save_settings(payload.sections, payload.enabled_quote, payload.enabled_invoice, admin.get("sub")))


@router.post("/preview")
def preview_terms(payload: TermsPreview, _admin: dict = Depends(require_role("admin"))):
    """PDF of the terms using the posted text, so unsaved edits can be previewed."""
    cleaned = service.clean_sections(payload.sections or {})
    merged = {k: (cleaned[k] if k in cleaned else DEFAULT_SECTIONS[k]) for k in SECTION_KEYS}
    titles = dict(SECTIONS)
    items = [(titles[k], merged[k]) for k in SECTION_KEYS if merged[k].strip()]
    if not items:
        items = [(titles[SECTION_KEYS[0]], "(sin contenido)")]
    return StreamingResponse(
        create_terms_pdf(items),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=terminos_vista_previa.pdf"},
    )
