from fastapi import APIRouter, Depends, HTTPException
from database import get_db_connection
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
def create_expense_endpoint(expense: ExpenseCreate):
    conn = get_db_connection()
    try:
        expense_id = create_expense(conn, expense)
        conn.commit()
        return {"expense_id": expense_id}
    finally:
        conn.close()


@router.get("/", response_model=list)
def list_expenses_endpoint():
    conn = get_db_connection()
    try:
        return get_expenses(conn)
    finally:
        conn.close()


@router.get("/{expense_id}", response_model=dict)
def get_expense_endpoint(expense_id: int):
    conn = get_db_connection()
    try:
        exp = get_expense(conn, expense_id)
        if not exp:
            raise HTTPException(status_code=404, detail="Expense not found")
        return exp
    finally:
        conn.close()


@router.put("/{expense_id}", response_model=dict)
def update_expense_endpoint(expense_id: int, data: ExpenseUpdate):
    conn = get_db_connection()
    try:
        updated = update_expense(conn, expense_id, data)
        if not updated:
            raise HTTPException(status_code=400, detail="Nothing to update")
        conn.commit()
        return {"status": "updated"}
    finally:
        conn.close()


@router.delete("/{expense_id}", response_model=dict)
def delete_expense_endpoint(expense_id: int):
    conn = get_db_connection()
    try:
        delete_expense(conn, expense_id)
        conn.commit()
        return {"status": "deleted"}
    finally:
        conn.close()