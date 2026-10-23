"""Engineering Estimate API (I3). Admin and superadmin only. Switch off = 404 on every route."""
from fastapi import APIRouter, Depends

from auth.service import require_auth, require_role
from estimator import service
from estimator.api_models import EstimateRequest, GenerateRequest, ParityRequest
from estimator.switch import require_enabled

admin_user = require_role("admin")  # admin and superadmin
# Auth first (a missing or bad token is always 401), then the switch (off = 404 for admins), then the handler.
router = APIRouter(prefix="/estimator", tags=["estimator"], dependencies=[Depends(admin_user), Depends(require_enabled)])


@router.post("/calculate")
def calculate_estimate(req: EstimateRequest, user: dict = Depends(admin_user)):
    """Stateless. Nothing is saved."""
    return service.calculate_preview(req)


@router.post("/generate")
def generate_estimate(req: GenerateRequest, user: dict = Depends(admin_user)):
    """Saves the run and creates one Draft engineering_estimate quote. Repeating the same key returns the first result."""
    return service.generate(req, user)


@router.get("/profiles")
def list_profiles(user: dict = Depends(admin_user)):
    return service.list_profiles()


@router.get("/runs/{run_id}")
def get_run(run_id: int, user: dict = Depends(admin_user)):
    return service.get_run(run_id)


@router.post("/runs/{run_id}/parity")
def run_parity(run_id: int, body: ParityRequest, user: dict = Depends(admin_user)):
    """Compare typed workbook values with the run. Not stored."""
    return service.parity(run_id, body.values)


# Available to any logged-in user and NOT behind the switch: the screens ask it whether to show the estimator.
status_router = APIRouter(prefix="/estimator", tags=["estimator"], dependencies=[Depends(require_auth)])


@status_router.get("/enabled")
def estimator_enabled_status():
    from estimator.switch import estimator_enabled
    return {"enabled": estimator_enabled()}
