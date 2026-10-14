import os
import resend
from fastapi import APIRouter, Depends

from auth.service import require_role

router = APIRouter()

resend.api_key = os.getenv("RESEND_API_KEY")

@router.post("/test-email")
def send_test_email(to: str, _admin: dict = Depends(require_role("admin"))):
    """Send a test email to the address given in `to`. Admin only."""
    params = {
        "from": "noreply@metprord.site",
        "to": [to],
        "subject": "METPRO test email",
        "html": "<strong>If you see this, Resend + FastAPI works.</strong>",
    }

    email = resend.Emails.send(params)
    return {"status": "sent", "id": email.id}