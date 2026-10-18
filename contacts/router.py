from core.errors import api_error
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from auth.service import require_auth
from contacts.schemas import ContactCreate, ContactRead, ContactUpdate
from .service import (
    create_contact,
    get_contacts_by_company,
    update_contact,
    delete_contact,
)

router = APIRouter(prefix="/contacts", tags=["Contacts"])


@router.post("/", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
def create_contact_endpoint(contact_in: ContactCreate, db: Session = Depends(get_db), _user: dict = Depends(require_auth)):
    return create_contact(db, contact_in)


@router.get("/company/{company_id}", response_model=list[ContactRead])
def list_contacts(company_id: int, db: Session = Depends(get_db), _user: dict = Depends(require_auth)):
    return get_contacts_by_company(db, company_id)


@router.put("/{contact_id}", response_model=ContactRead)
def update_contact_endpoint(contact_id: int, contact_in: ContactUpdate, db: Session = Depends(get_db), _user: dict = Depends(require_auth)):
    updated = update_contact(db, contact_id, contact_in)
    if not updated:
        raise api_error(404, "Contacto no encontrado", "CONTACT_NOT_FOUND")
    return updated


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact_endpoint(contact_id: int, db: Session = Depends(get_db), _user: dict = Depends(require_auth)):
    deleted = delete_contact(db, contact_id)
    if not deleted:
        raise api_error(404, "Contacto no encontrado", "CONTACT_NOT_FOUND")
    return
