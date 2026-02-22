import os
import resend
from fastapi import APIRouter

router = APIRouter()

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
resend.api_key = RESEND_API_KEY


@router.post("/test-email")
def send_test_email():
    params = {
        "from": "METPRO <no-reply@yourdomain.com>",
        "to": ["youremail@example.com"],
        "subject": "METPRO test email",
        "html": "<strong>If you see this, Resend + FastAPI works.</strong>",
    }

    email = resend.Emails.send(params)
    return {"status": "sent", "id": email.id}