from sqlalchemy import text
from sqlalchemy.orm import Session

from core.errors import api_error
from models.contact import Contact
from contacts.schemas import ContactCreate, ContactUpdate


def create_contact(db: Session, contact_in: ContactCreate):
    contact = Contact(
        company_id=contact_in.company_id,
        name=contact_in.name,
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

    contact.name = contact_in.name
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
        raise api_error(400, "Contact is used by quotes or invoices and cannot be deleted", "CONTACT_IN_USE")

    db.delete(contact)
    db.commit()
    return True
