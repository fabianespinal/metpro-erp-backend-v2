from fastapi import APIRouter, Depends, File, UploadFile
from typing import List
from .models import Client, ClientBase
from . import service
from backend.auth.service import verify_token

router = APIRouter(prefix='/clients', tags=['clients'])

@router.post('/', response_model=Client)
def create_client(client: ClientBase, current_user: dict = Depends(verify_token)):
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
def get_clients(current_user: dict = Depends(verify_token)):
    """Get all clients"""
    clients = service.get_all_clients()
    return [Client(**c) for c in clients]

@router.get('/{client_id}', response_model=Client)
def get_client(client_id: int, current_user: dict = Depends(verify_token)):
    """Get a single client"""
    result = service.get_client_by_id(client_id)
    return Client(**result)

@router.put('/{client_id}', response_model=Client)
def update_client(client_id: int, client: ClientBase, current_user: dict = Depends(verify_token)):
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
def delete_client(client_id: int, current_user: dict = Depends(verify_token)):
    """Delete a client"""
    return service.delete_client(client_id)

@router.post('/bulk-import')
async def import_clients_csv(
    file: UploadFile = File(...),
    skip_duplicates: bool = True,
    current_user: dict = Depends(verify_token)
):
    """Import clients from CSV"""
    if not file.filename.lower().endswith('.csv'):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail='File must be CSV format')
    
    content = await file.read()
    return await service.import_clients_from_csv(content, file.filename, skip_duplicates, current_user)
