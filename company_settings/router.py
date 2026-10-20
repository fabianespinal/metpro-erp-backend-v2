from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from auth.service import require_auth, require_role
from core.errors import api_error
from pdf.utils.seal_utils import MAX_UPLOAD_BYTES

from . import service

router = APIRouter(prefix="/company-settings", tags=["company-settings"])


class SealDefaultUpdate(BaseModel):
    enabled_by_default: bool


@router.get("/seal")
def get_seal_settings(_user: dict = Depends(require_auth)):
    """Seal status for the document dialogs: is there a seal, and is it pre-checked."""
    return service.get_seal_settings()


@router.put("/seal")
def set_seal_default(payload: SealDefaultUpdate, admin: dict = Depends(require_role("admin"))):
    """Turn the default on or off. This only pre-checks the dialogs; it never prints a seal by itself."""
    return service.set_enabled_by_default(payload.enabled_by_default, admin.get("sub"))


@router.post("/seal/image")
def upload_seal_image(file: UploadFile = File(...), admin: dict = Depends(require_role("admin"))):
    """Upload or replace the company seal (PNG or JPG, max 5 MB)."""
    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise api_error(422, "El archivo supera el máximo de 5 MB.", "SEAL_IMAGE_INVALID")
    return service.save_seal_image(raw, admin.get("sub"))


@router.get("/seal/image")
def get_seal_image(_admin: dict = Depends(require_role("admin"))):
    """The stored seal as PNG, for the settings preview."""
    return Response(content=service.get_seal_image_bytes(), media_type="image/png", headers={"Cache-Control": "no-store"})
