from fastapi import APIRouter, Depends
from typing import List, Optional
from .models import Project, ProjectBase
from . import service
from auth.service import verify_token

router = APIRouter(prefix='/projects', tags=['projects'])

@router.post('/', response_model=Project)
def create_project(project: ProjectBase, current_user: dict = Depends(verify_token)):
    """Create new project"""
    result = service.create_project(
        project.client_id, project.name, project.description, project.status,
        project.start_date, project.end_date, project.estimated_budget, project.notes
    )
    return Project(**result)

@router.get('/', response_model=List[Project])
def get_projects(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(verify_token)
):
    """List projects with optional filters"""
    projects = service.get_all_projects(client_id, status)
    return [Project(**p) for p in projects]

@router.get('/{project_id}', response_model=Project)
def get_project(project_id: int, current_user: dict = Depends(verify_token)):
    """Get single project"""
    result = service.get_project_by_id(project_id)
    return Project(**result)

@router.put('/{project_id}', response_model=Project)
def update_project(
    project_id: int, 
    project: ProjectBase, 
    current_user: dict = Depends(verify_token)
):
    """Update project"""
    result = service.update_project(
        project_id, project.client_id, project.name, project.description,
        project.status, project.start_date, project.end_date,
        project.estimated_budget, project.notes
    )
    return Project(**result)

@router.delete('/{project_id}')
def delete_project(project_id: int, current_user: dict = Depends(verify_token)):
    """Delete project"""
    return service.delete_project(project_id)
