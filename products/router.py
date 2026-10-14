from fastapi import APIRouter, Depends, File, UploadFile
from typing import List
from .models import Product, ProductBase
from . import service
from auth.service import require_auth, require_role

router = APIRouter(prefix='/products', tags=['products'])

@router.post('/', response_model=Product)
def create_product(product: ProductBase, current_user: dict = Depends(require_auth)):
    """Create a new product"""
    result = service.create_product(
        product.name,
        product.description,
        product.unit_price
    )
    return Product(**result)

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
    result = service.update_product(
        product_id,
        product.name,
        product.description,
        product.unit_price
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
        raise HTTPException(status_code=400, detail='File must be CSV format')
    
    content = await file.read()
    return await service.import_products_from_csv(content, file.filename)
