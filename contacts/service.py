from sqlalchemy.orm import Session
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

    db.delete(contact)
    db.commit()
    return True
