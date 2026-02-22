import os
import resend
from fastapi import APIRouter

router = APIRouter()

# Load API key safely
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
resend.api_key = RESEND_API_KEY


@router.post("/test-email")
def send_test_email():
    # Use the guaranteed working sender
    params = {
        "from": "onboarding@resend.dev",   # MUST use this unless your domain is verified
        "to": ["youremail@example.com"],   # <-- replace with your real email
        "subject": "METPRO test email",
        "html": "<strong>If you see this, Resend + FastAPI works.</strong>",
    }

    email = resend.Emails.send(params)
    return {"status": "sent", "id": email.id}