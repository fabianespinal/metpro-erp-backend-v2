from core.errors import api_error
from fastapi import APIRouter, Depends, File, UploadFile
from typing import List
from .models import Client, ClientBase
from . import service
from auth.service import require_auth, require_role

router = APIRouter(prefix='/clients', tags=['clients'])

@router.post('/', response_model=Client)
def create_client(client: ClientBase, current_user: dict = Depends(require_auth)):
    """Create a new client"""
    result = service.create_client(
        client.company_name,
        client.contact_name,
        client.email,
        client.phone,
        client.address,
        client.tax_id,
        client.notes
    )
    return Client(**result)

@router.get('/', response_model=List[Client])
def get_clients(current_user: dict = Depends(require_auth)):
    """Get all clients"""
    clients = service.get_all_clients()
    return [Client(**c) for c in clients]

@router.get('/{client_id}', response_model=Client)
def get_client(client_id: int, current_user: dict = Depends(require_auth)):
    """Get a single client"""
    result = service.get_client_by_id(client_id)
    return Client(**result)

@router.put('/{client_id}', response_model=Client)
def update_client(client_id: int, client: ClientBase, current_user: dict = Depends(require_auth)):
    """Update an existing client"""
    result = service.update_client(
        client_id,
        client.company_name,
        client.contact_name,
        client.email,
        client.phone,
        client.address,
        client.tax_id,
        client.notes
    )
    return Client(**result)

@router.delete('/{client_id}')
def delete_client(client_id: int, _admin: dict = Depends(require_role("admin"))):
    """Delete a client"""
    return service.delete_client(client_id)

@router.post('/bulk-import')
async def import_clients_csv(
    file: UploadFile = File(...),
    skip_duplicates: bool = True,
    current_user: dict = Depends(require_auth)
):
    """Import clients from CSV"""
    if not file.filename.lower().endswith('.csv'):
        from fastapi import HTTPException
        raise api_error(400, 'File must be CSV format', "CSV_FORMAT_INVALID")
    
    content = await file.read()
    return await service.import_clients_from_csv(content, file.filename, skip_duplicates, current_user)
