from typing import List

from fastapi import APIRouter, Depends

from auth.service import require_auth, require_role

from . import service
from .models import PackIn, PackOut, PackSummary

router = APIRouter(prefix="/template-packs", tags=["template-packs"])


@router.get("/", response_model=List[PackSummary])
def list_template_packs(current_user: dict = Depends(require_auth)):
    """List template packs. Any authenticated user."""
    return [PackSummary(**p) for p in service.list_packs()]


@router.get("/{pack_id}", response_model=PackOut)
def get_template_pack(pack_id: int, current_user: dict = Depends(require_auth)):
    """Get one template pack with categories and items. Any authenticated user."""
    return PackOut(**service.get_pack(pack_id))


@router.post("/", response_model=PackOut)
def create_template_pack(data: PackIn, _admin: dict = Depends(require_role("admin"))):
    """Create a template pack. Admin only."""
    return PackOut(**service.create_pack(data))


@router.put("/{pack_id}", response_model=PackOut)
def update_template_pack(pack_id: int, data: PackIn, _admin: dict = Depends(require_role("admin"))):
    """Replace a template pack. Admin only."""
    return PackOut(**service.update_pack(pack_id, data))


@router.delete("/{pack_id}")
def delete_template_pack(pack_id: int, _admin: dict = Depends(require_role("admin"))):
    """Delete a template pack. Admin only."""
    return service.delete_pack(pack_id)
