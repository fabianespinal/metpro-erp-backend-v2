from datetime import date
from fastapi import APIRouter, Depends
from typing import Optional
from core.errors import api_error
from . import service
from auth.service import require_auth, require_role

router = APIRouter(prefix='/reports', tags=['reports'])

@router.get('/quotes-summary')
def get_quotes_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    client_id: Optional[int] = None,
    current_user: dict = Depends(require_auth)
):
    """Quotes summary report: totals + status breakdown"""
    _check_range(start_date, end_date)  # debug B-12: typed dates, 422 instead of a 500
    return service.get_quotes_summary(start_date, end_date, client_id)

@router.get('/revenue')
def get_revenue_report(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    client_id: Optional[int] = None,
    current_user: dict = Depends(require_auth)
):
    """Revenue report: approved + invoiced totals"""
    _check_range(start_date, end_date)
    return service.get_revenue_report(start_date, end_date, client_id)

@router.get('/client-activity')
def get_client_activity(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    client_id: Optional[int] = None,
    current_user: dict = Depends(require_auth)
):
    """Client activity report. client_id narrows it to one client (debug B-11)."""
    _check_range(start_date, end_date)
    return service.get_client_activity(start_date, end_date, client_id)


@router.get('/project-profitability')
def get_project_profitability(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    client_id: Optional[int] = None,
    project_id: Optional[int] = None,
    current_user: dict = Depends(require_auth)
):
    """Rentabilidad por proyecto: facturado, cobrado, gastos, margen neto, categorías."""
    _check_range(start_date, end_date)
    return service.get_project_profitability(start_date, end_date, client_id, project_id)


@router.get('/client-profitability')
def get_client_profitability(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    client_id: Optional[int] = None,
    current_user: dict = Depends(require_role("admin"))  # margin data: admin and superadmin only
):
    """Rentabilidad por cliente (Fase 1): ingreso sin impuesto, COGS, utilidad bruta, % y saldo pendiente."""
    _check_range(start_date, end_date)
    from .client_profitability import get_client_profitability as build
    return build(start_date, end_date, client_id)


@router.get('/expenses-by-category')
def get_expenses_by_category(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    project_id: Optional[int] = None,
    current_user: dict = Depends(require_auth)
):
    """Gastos por categoría (todos o de un proyecto)."""
    _check_range(start_date, end_date)
    return service.get_expenses_by_category(start_date, end_date, project_id)


def _check_range(start_date, end_date):
    if start_date and end_date and start_date > end_date:
        raise api_error(400, "La fecha de fin debe ser posterior a la fecha de inicio", "DATE_RANGE_INVALID")


@router.get('/product-profitability')
def get_product_profitability(only_with_cost: bool = False, current_user: dict = Depends(require_auth)):
    """Rentabilidad de Productos: precio, costo, margen y margen % por producto."""
    return service.get_product_profitability(only_with_cost)


@router.get('/project-variance')
def get_project_variance(
    client_id: Optional[int] = None,
    project_id: Optional[int] = None,
    current_user: dict = Depends(require_auth)
):
    """Variación del Proyecto: costo estimado vs gastos reales, margen estimado vs real."""
    return service.get_project_variance(client_id, project_id)
