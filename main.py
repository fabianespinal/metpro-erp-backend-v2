import os
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()

# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="METPRO ERP API",
    description="Modular ERP System for Construction & Services",
    version="2.0.0",
)

# ============================================================
# CORS CONFIGURATION — LOCAL + CUSTOM DOMAIN
# ============================================================

allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",

    # Frontend (Custom Domain)
    "https://app.metprord.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# STATIC FILES
# ============================================================

if os.path.exists("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# ============================================================
# ROUTERS (MUST BE IMPORTED AFTER CORS)
# ============================================================

from backend.database import get_db

from backend.auth.router import router as auth_router
from backend.users.router import router as users_router
from backend.clients.router import router as clients_router
from backend.products.router import router as products_router
from backend.quotes.router import router as quotes_router
from backend.invoices.router import router as invoices_router
from backend.projects.router import router as projects_router
from backend.reports.router import router as reports_router
from backend.pdf.router import router as pdf_router
from backend.expenses.router import router as expenses_router
from backend.contacts.router import router as contacts_router

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(clients_router)
app.include_router(products_router)
app.include_router(quotes_router)
app.include_router(invoices_router)
app.include_router(projects_router)
app.include_router(reports_router)
app.include_router(pdf_router)
app.include_router(expenses_router)
app.include_router(contacts_router)

# ============================================================
# ROOT & HEALTH ENDPOINTS
# ============================================================

@app.get("/")
def read_root():
    return {
        "message": "METPRO ERP API is running!",
        "version": "2.0.0",
        "architecture": "Modular",
        "database": "PostgreSQL (Supabase)",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "modules": [
            "auth",
            "users",
            "clients",
            "products",
            "quotes",
            "invoices",
            "projects",
            "reports",
            "pdf",
            "expenses",
            "contacts",
        ],
    }
