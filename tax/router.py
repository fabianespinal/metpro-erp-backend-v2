from fastapi import APIRouter, Depends

from auth.service import require_auth

from . import service

router = APIRouter(prefix="/tax-types", tags=["tax-types"])


@router.get("")
def list_active_tax_types(_user: dict = Depends(require_auth)):
    """Active tax types for the quote screens. Read-only; rates are managed in the database."""
    return service.list_tax_types(active_only=True)
