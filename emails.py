import os
import resend
from fastapi import APIRouter, Depends

from auth.service import verify_token

router = APIRouter()

resend.api_key = os.getenv("RESEND_API_KEY")

@router.post("/test-email")
def send_test_email(_user: dict = Depends(verify_token)):
    params = {
        "from": "noreply@metprord.site",
        "to": ["fabianespinale@gmail.com"],
        "subject": "METPRO test email",
        "html": "<strong>If you see this, Resend + FastAPI works.</strong>",
    }

    email = resend.Emails.send(params)
    return {"status": "sent", "id": email.id}