from fastapi import APIRouter, Depends
from typing import Optional
from . import service
from backend.auth.service import verify_token

router = APIRouter(prefix='/reports', tags=['reports'])

@router.get('/quotes-summary')
def get_quotes_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    client_id: Optional[int] = None,
    current_user: dict = Depends(verify_token)
):
    """Quotes summary report: totals + status breakdown"""
    return service.get_quotes_summary(start_date, end_date, client_id)

@router.get('/revenue')
def get_revenue_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    client_id: Optional[int] = None,
    current_user: dict = Depends(verify_token)
):
    """Revenue report: approved + invoiced totals"""
    return service.get_revenue_report(start_date, end_date, client_id)

@router.get('/client-activity')
def get_client_activity(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(verify_token)
):
    """Client activity report"""
    return service.get_client_activity(start_date, end_date)
