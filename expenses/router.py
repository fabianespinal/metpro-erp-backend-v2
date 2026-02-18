from fastapi import APIRouter, Depends, HTTPException
from database import get_db
from .models import ExpenseCreate, ExpenseUpdate
from .services import (
    create_expense,
    get_expenses,
    get_expense,
    update_expense,
    delete_expense
)

router = APIRouter(prefix="/expenses", tags=["Expenses"])


@router.post("/", response_model=dict)
def create_expense_endpoint(expense: ExpenseCreate, conn=Depends(get_db)):
    expense_id = create_expense(conn, expense)
    return {"expense_id": expense_id}


@router.get("/", response_model=list)
def list_expenses_endpoint(conn=Depends(get_db)):
    return get_expenses(conn)


@router.get("/{expense_id}", response_model=dict)
def get_expense_endpoint(expense_id: int, conn=Depends(get_db)):
    exp = get_expense(conn, expense_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Expense not found")
    return exp


@router.put("/{expense_id}", response_model=dict)
def update_expense_endpoint(expense_id: int, data: ExpenseUpdate, conn=Depends(get_db)):
    updated = update_expense(conn, expense_id, data)
    if not updated:
        raise HTTPException(status_code=400, detail="Nothing to update")
    return {"status": "updated"}


@router.delete("/{expense_id}", response_model=dict)
def delete_expense_endpoint(expense_id: int, conn=Depends(get_db)):
    delete_expense(conn, expense_id)
    return {"status": "deleted"}