from sqlalchemy import text
from sqlalchemy.orm import Session

from core.errors import api_error
from models.contact import Contact
from contacts.schemas import ContactCreate, ContactUpdate


def _clean_name(name) -> str:
    name = (name or "").strip()
    if not name:
        raise api_error(400, "El nombre del contacto es obligatorio", "CONTACT_NAME_REQUIRED")
    return name


def create_contact(db: Session, contact_in: ContactCreate):
    # Debug B-12: unknown company was an unhandled FK error (500).
    if not db.execute(text("SELECT 1 FROM clients WHERE id = :cid"), {"cid": contact_in.company_id}).first():
        raise api_error(404, "Cliente no encontrado", "CLIENT_NOT_FOUND")
    contact = Contact(
        company_id=contact_in.company_id,
        name=_clean_name(contact_in.name),
        email=contact_in.email,
        phone=contact_in.phone,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def get_contacts_by_company(db: Session, company_id: int):
    return (
        db.query(Contact)
        .filter(Contact.company_id == company_id)
        .order_by(Contact.name)
        .all()
    )


def update_contact(db: Session, contact_id: int, contact_in: ContactUpdate):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        return None

    contact.name = _clean_name(contact_in.name)
    contact.email = contact_in.email
    contact.phone = contact_in.phone

    db.commit()
    db.refresh(contact)
    return contact


def delete_contact(db: Session, contact_id: int):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        return False

    # Quotes and invoices print this contact; deleting it would break their
    # documents (invoices: FK NO ACTION -> 500; quotes: contact set to NULL).
    in_use = db.execute(
        text(
            "SELECT (SELECT COUNT(*) FROM quotes WHERE contact_id = :cid)"
            " + (SELECT COUNT(*) FROM invoices WHERE contact_id = :cid)"
        ),
        {"cid": contact_id},
    ).scalar()
    if in_use:
        raise api_error(400, "El contacto se usa en cotizaciones o facturas y no se puede eliminar", "CONTACT_IN_USE")

    db.delete(contact)
    db.commit()
    return True
