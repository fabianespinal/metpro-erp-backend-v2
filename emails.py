import os
import resend
from fastapi import APIRouter

router = APIRouter()

resend.api_key = os.getenv("RESEND_API_KEY")

@router.post("/test-email")
def send_test_email():
    params = {
        "from": "onboarding@resend.dev",          # required for unverified domains
        "to": ["fabianespinale@gmail.com"],              # your real email
        "subject": "METPRO test email",
        "html": "<strong>If you see this, Resend + FastAPI works.</strong>",
    }

    email = resend.Emails.send(params)
    return {"status": "sent", "id": email.id}