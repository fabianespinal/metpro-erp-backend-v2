from typing import List

from fastapi import APIRouter, Depends

from auth.service import require_auth, require_role
from core.po_features import po_enabled
from . import service
from .models import PoIn, PoOut, PoStatusIn

router = APIRouter(prefix="/po", tags=["purchase-orders"])
admin = Depends(require_role("admin"))  # admin and superadmin


@router.get("/options")
def po_options(current_user: dict = Depends(require_auth)):
    """Always available, so screens know whether to show the P.O tab. Every other route is admin only."""
    return {"po_enabled": po_enabled()}


@router.get("/", response_model=List[PoOut])
def list_pos(user: dict = admin):
    service.require_enabled()
    return [PoOut(**r) for r in service.list_pos()]


@router.post("/", response_model=PoOut)
def create_po(body: PoIn, user: dict = admin):
    service.require_enabled()
    return PoOut(**service.create_po(body, user.get("sub")))


@router.post("/from-rfq/{rfq_id}", response_model=PoOut)
def convert_rfq(rfq_id: int, user: dict = admin):
    service.require_enabled()
    return PoOut(**service.convert_rfq(rfq_id, user.get("sub")))


@router.get("/{po_id}", response_model=PoOut)
def get_po(po_id: int, user: dict = admin):
    service.require_enabled()
    return PoOut(**service.get_po(po_id))


@router.put("/{po_id}", response_model=PoOut)
def update_po(po_id: int, body: PoIn, user: dict = admin):
    service.require_enabled()
    return PoOut(**service.update_po(po_id, body))


@router.put("/{po_id}/status", response_model=PoOut)
def set_status(po_id: int, body: PoStatusIn, user: dict = admin):
    service.require_enabled()
    return PoOut(**service.set_status(po_id, body.status))


@router.delete("/{po_id}")
def delete_po(po_id: int, user: dict = admin):
    service.require_enabled()
    return service.delete_po(po_id)


@router.get("/{po_id}/pdf")
def po_pdf(po_id: int, print_seal: bool = False, user: dict = admin):
    service.require_enabled()
    return service.generate_po_pdf(po_id, user, print_seal)
