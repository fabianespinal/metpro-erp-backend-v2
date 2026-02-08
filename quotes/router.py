from fastapi import APIRouter, Depends
from typing import List, Optional
from .models import QuoteCreate, StatusUpdate
from . import service
from auth.service import verify_token

router = APIRouter(prefix='/quotes', tags=['quotes'])

@router.post('/')
def create_quote(quote: QuoteCreate, current_user: dict = Depends(verify_token)):
    """Create a new quote"""
    items = [item.dict() for item in quote.items]
    charges = quote.included_charges.dict()
    
    result = service.create_quote(
        quote.client_id,
        quote.project_name,
        quote.notes,
        items,
        charges
    )
    return result

@router.get('/')
def get_quotes(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(verify_token)
):
    """Get all quotes with optional filters"""
    return service.get_all_quotes(client_id, status)

@router.get('/{quote_id}')
def get_quote(quote_id: str, current_user: dict = Depends(verify_token)):
    """Get a single quote"""
    return service.get_quote_by_id(quote_id)

@router.patch('/{quote_id}/status')
def update_quote_status(
    quote_id: str,
    status_update: StatusUpdate,
    current_user: dict = Depends(verify_token)
):
    """Update quote status"""
    return service.update_quote_status(quote_id, status_update.status)

@router.delete('/{quote_id}')
def delete_quote(quote_id: str, current_user: dict = Depends(verify_token)):
    """Delete a quote"""
    return service.delete_quote(quote_id)
