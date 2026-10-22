from core.errors import api_error
from fastapi import APIRouter, Depends, File, UploadFile
from typing import List
from .models import Product, ProductBase, DIMENSION_FIELDS
from . import service
from auth.service import require_auth, require_role

router = APIRouter(prefix='/products', tags=['products'])

@router.post('/', response_model=Product)
def create_product(product: ProductBase, current_user: dict = Depends(require_auth)):
    """Create a new product"""
    result = service.create_product(
        product.name,
        product.description,
        product.unit_price,
        product.cost,
        **({"unit_of_measure": product.unit_of_measure} if product.unit_of_measure else {}),
        dims={k: getattr(product, k) for k in DIMENSION_FIELDS if k in product.model_fields_set} or None,
    )
    return Product(**result)

@router.get('/options')
def product_options(current_user: dict = Depends(require_auth)):
    """B3 switch, so the form shows the dimensions section only when it is on."""
    return {"dimensions_enabled": service.dimensions_enabled()}

@router.get('/', response_model=List[Product])
def get_products(current_user: dict = Depends(require_auth)):
    """Get all products"""
    products = service.get_all_products()
    return [Product(**p) for p in products]

@router.get('/{product_id}', response_model=Product)
def get_product(product_id: int, current_user: dict = Depends(require_auth)):
    """Get a single product"""
    result = service.get_product_by_id(product_id)
    return Product(**result)

@router.put('/{product_id}', response_model=Product)
def update_product(product_id: int, product: ProductBase, current_user: dict = Depends(require_auth)):
    """Update an existing product"""
    # Older clients that omit "cost" keep the stored cost (no silent wipe).
    extra = {}
    if "unit_of_measure" in product.model_fields_set:  # older clients that omit it keep the stored unit
        extra = {"unit_of_measure": product.unit_of_measure, "unit_set": True}
    result = service.update_product(
        product_id,
        product.name,
        product.description,
        product.unit_price,
        product.cost,
        cost_set="cost" in product.model_fields_set,
        **extra,
        dims={k: getattr(product, k) for k in DIMENSION_FIELDS if k in product.model_fields_set} or None,
    )
    return Product(**result)

@router.delete('/{product_id}')
def delete_product(product_id: int, _admin: dict = Depends(require_role("admin"))):
    """Delete a product"""
    return service.delete_product(product_id)

@router.post('/import-csv')
async def import_products_csv(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_auth)
):
    """Import products from CSV"""
    if not file.filename.lower().endswith('.csv'):
        from fastapi import HTTPException
        raise api_error(400, "El archivo debe ser formato CSV", "CSV_FORMAT_INVALID")
    
    content = await file.read()
    return await service.import_products_from_csv(content, file.filename)
