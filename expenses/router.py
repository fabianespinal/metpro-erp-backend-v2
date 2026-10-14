from core.errors import api_error
from fastapi import APIRouter, Depends, HTTPException
from database import get_db_connection
from auth.service import require_auth
from .models import ExpenseCreate, ExpenseUpdate
from .services import (
    create_expense,
    get_expenses,
    get_expense,
    update_expense,
    delete_expense
)

router = APIRouter(prefix="/expenses", tags=["Expenses"])


# Both "/expenses" (main frontend) and "/expenses/" (dev frontend) are served.
# The trailing-slash variant is hidden from OpenAPI to avoid duplicate entries.

@router.post("", response_model=dict)
@router.post("/", response_model=dict, include_in_schema=False)
def create_expense_endpoint(expense: ExpenseCreate, _user: dict = Depends(require_auth)):
    conn = get_db_connection()
    try:
        expense_id = create_expense(conn, expense)
        conn.commit()
        return {"expense_id": expense_id}
    finally:
        conn.close()


@router.get("", response_model=list)
@router.get("/", response_model=list, include_in_schema=False)
def list_expenses_endpoint(_user: dict = Depends(require_auth)):
    conn = get_db_connection()
    try:
        return get_expenses(conn)
    finally:
        conn.close()


@router.get("/{expense_id}", response_model=dict)
def get_expense_endpoint(expense_id: int, _user: dict = Depends(require_auth)):
    conn = get_db_connection()
    try:
        exp = get_expense(conn, expense_id)
        if not exp:
            raise api_error(404, "Expense not found", "EXPENSE_NOT_FOUND")
        return exp
    finally:
        conn.close()


@router.put("/{expense_id}", response_model=dict)
def update_expense_endpoint(expense_id: int, data: ExpenseUpdate, _user: dict = Depends(require_auth)):
    conn = get_db_connection()
    try:
        updated = update_expense(conn, expense_id, data)
        if not updated:
            raise api_error(400, "Nothing to update", "NOTHING_TO_UPDATE")
        conn.commit()
        return {"status": "updated"}
    finally:
        conn.close()


@router.delete("/{expense_id}", response_model=dict)
def delete_expense_endpoint(expense_id: int, _user: dict = Depends(require_auth)):
    conn = get_db_connection()
    try:
        delete_expense(conn, expense_id)
        conn.commit()
        return {"status": "deleted"}
    finally:
        conn.close()
