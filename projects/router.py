from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from .models import Project, ProjectBase, ProjectUpdate
from . import service
from backend.auth.service import verify_token

router = APIRouter(prefix='/projects', tags=['projects'])

@router.post('/', response_model=Project)
def create_project(project: ProjectBase, current_user: dict = Depends(verify_token)):
    """Create new project"""
    try:
        result = service.create_project(
            project.client_id, project.name, project.description, project.status,
            project.start_date, project.end_date, project.estimated_budget, project.notes
        )
        return Project(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Create failed: {str(e)}")

@router.get('/', response_model=List[Project])
def get_projects(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(verify_token)
):
    """List projects with optional filters"""
    try:
        projects = service.get_all_projects(client_id, status)
        return [Project(**p) for p in projects]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch failed: {str(e)}")

@router.get('/{project_id}', response_model=Project)
def get_project(project_id: int, current_user: dict = Depends(verify_token)):
    """Get single project"""
    try:
        result = service.get_project_by_id(project_id)
        return Project(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch failed: {str(e)}")

@router.put('/{project_id}', response_model=Project)
def update_project(
    project_id: int,
    project: ProjectUpdate,  # FIXED: Use ProjectUpdate for partial updates
    current_user: dict = Depends(verify_token)
):
    """Update project"""
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
            notes=project.notes
        )
        return Project(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")

@router.delete('/{project_id}')
def delete_project(project_id: int, current_user: dict = Depends(verify_token)):
    """Delete project"""
    try:
        return service.delete_project(project_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")
