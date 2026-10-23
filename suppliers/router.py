from typing import List

from fastapi import APIRouter, Depends

from auth.service import require_auth, require_role
from core.supplier_features import suppliers_enabled
from . import service
from .models import Supplier, SupplierInput

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("/options")
def supplier_options(current_user: dict = Depends(require_auth)):
    """Always available, so screens know whether to show the Suplidores option."""
    return {"suppliers_enabled": suppliers_enabled()}


@router.get("/", response_model=List[Supplier])
def list_suppliers(current_user: dict = Depends(require_auth)):
    service.require_enabled()
    return [Supplier(**r) for r in service.list_suppliers()]


@router.post("/", response_model=Supplier)
def create_supplier(body: SupplierInput, current_user: dict = Depends(require_auth)):
    service.require_enabled()
    return Supplier(**service.create_supplier(body.model_dump()))


@router.get("/{supplier_id}", response_model=Supplier)
def get_supplier(supplier_id: int, current_user: dict = Depends(require_auth)):
    service.require_enabled()
    return Supplier(**service.get_supplier(supplier_id))


@router.put("/{supplier_id}", response_model=Supplier)
def update_supplier(supplier_id: int, body: SupplierInput, current_user: dict = Depends(require_auth)):
    service.require_enabled()
    return Supplier(**service.update_supplier(supplier_id, body.model_dump()))


@router.delete("/{supplier_id}")
def delete_supplier(supplier_id: int, _admin: dict = Depends(require_role("admin"))):
    service.require_enabled()
    return service.delete_supplier(supplier_id)
