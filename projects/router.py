from fastapi import APIRouter, Depends, HTTPException
from datetime import date
from typing import List, Optional
from .models import Project, ProjectBase, ProjectUpdate
from . import service, ledger
from auth.service import require_auth, require_role
from core.errors import internal_error

router = APIRouter(prefix='/projects', tags=['projects'])

@router.post('/', response_model=Project)
def create_project(project: ProjectBase, current_user: dict = Depends(require_auth)):
    """Crear proyecto"""
    try:
        result = service.create_project(
            project.client_id, project.name, project.description, project.status,
            project.start_date, project.end_date, project.estimated_budget, project.notes,
            project.job_site_address
        )
        return Project(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("No se pudo crear", e)

@router.get('/', response_model=List[Project])
def get_projects(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(require_auth)
):
    """Listar proyectos con filtros opcionales"""
    try:
        projects = service.get_all_projects(client_id, status)
        return [Project(**p) for p in projects]
    except Exception as e:
        raise internal_error("No se pudo obtener la información", e)

@router.get('/{project_id}/expenses')
def get_project_expenses(
    project_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: dict = Depends(require_auth),
):
    """Gastos del proyecto: lista, total y desglose por categoría. Fechas opcionales (inclusive)."""
    try:
        return ledger.get_project_expenses(project_id, start_date, end_date)
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("No se pudo obtener la información", e)

@router.get('/{project_id}/cost-estimate')
def get_project_cost_estimate(project_id: int, current_user: dict = Depends(require_auth)):
    """Costo estimado vs gastos reales, variación y precisión del margen. Solo lectura."""
    try:
        return ledger.get_project_cost_estimate(project_id)
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("No se pudo obtener la información", e)

@router.get('/{project_id}', response_model=Project)
def get_project(project_id: int, current_user: dict = Depends(require_auth)):
    """Obtener un proyecto"""
    try:
        result = service.get_project_by_id(project_id)
        return Project(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("No se pudo obtener la información", e)

@router.put('/{project_id}', response_model=Project)
def update_project(
    project_id: int,
    project: ProjectUpdate,  # FIXED: Use ProjectUpdate for partial updates
    current_user: dict = Depends(require_auth)
):
    """Actualizar proyecto"""
    try:
        result = service.update_project(
            project_id,
            client_id=project.client_id,
            name=project.name,
            description=project.description,
            status=project.status,
            start_date=project.start_date,
            end_date=project.end_date,
            estimated_budget=project.estimated_budget,
            notes=project.notes,
            job_site_address=project.job_site_address
        )
        return Project(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("No se pudo actualizar", e)

@router.delete('/{project_id}')
def delete_project(project_id: int, current_user: dict = Depends(require_role("admin"))):
    """Eliminar proyecto. Admin only, same rule as quotes, invoices, clients and products."""
    try:
        return service.delete_project(project_id)
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("No se pudo eliminar", e)
