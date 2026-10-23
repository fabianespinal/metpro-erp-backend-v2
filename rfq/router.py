from typing import List

from fastapi import APIRouter, Depends

from auth.service import require_auth
from core.rfq_features import rfq_enabled
from . import service
from .models import DEFAULT_BILL_TO, DEFAULT_TITLE, RfqIn, RfqOut, RfqStatusIn

router = APIRouter(prefix="/rfq", tags=["rfq"])


@router.get("/options")
def rfq_options(current_user: dict = Depends(require_auth)):
    """Always available, so screens know whether to show the RFQ card."""
    return {"rfq_enabled": rfq_enabled(), "default_bill_to": DEFAULT_BILL_TO, "default_title": DEFAULT_TITLE}


@router.get("/", response_model=List[RfqOut])
def list_rfqs(current_user: dict = Depends(require_auth)):
    service.require_enabled()
    return [RfqOut(**r) for r in service.list_rfqs()]


@router.post("/", response_model=RfqOut)
def create_rfq(body: RfqIn, current_user: dict = Depends(require_auth)):
    service.require_enabled()
    return RfqOut(**service.create_rfq(body, current_user.get("sub")))


@router.get("/{rfq_id}", response_model=RfqOut)
def get_rfq(rfq_id: int, current_user: dict = Depends(require_auth)):
    service.require_enabled()
    return RfqOut(**service.get_rfq(rfq_id))


@router.put("/{rfq_id}", response_model=RfqOut)
def update_rfq(rfq_id: int, body: RfqIn, current_user: dict = Depends(require_auth)):
    service.require_enabled()
    return RfqOut(**service.update_rfq(rfq_id, body))


@router.put("/{rfq_id}/status", response_model=RfqOut)
def set_status(rfq_id: int, body: RfqStatusIn, current_user: dict = Depends(require_auth)):
    service.require_enabled()
    return RfqOut(**service.set_status(rfq_id, body.status))


@router.delete("/{rfq_id}")
def delete_rfq(rfq_id: int, current_user: dict = Depends(require_auth)):
    service.require_enabled()
    return service.delete_rfq(rfq_id)


@router.get("/{rfq_id}/pdf")
def rfq_pdf(rfq_id: int, print_seal: bool = False, current_user: dict = Depends(require_auth)):
    service.require_enabled()
    return service.generate_rfq_pdf(rfq_id, current_user, print_seal)
