import os
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

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
# PROXY HEADERS (Railway / reverse proxy support)
# ============================================================

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# ============================================================
# CORS CONFIGURATION — LOCAL + PRODUCTION + STAGING
# ============================================================

allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",

    # Production frontend
    "https://app.metprord.com",

    # Staging frontend
    "https://metpro-erp-frontend-staging-production.up.railway.app",
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

from database import get_db

from auth.router import router as auth_router
from users.router import router as users_router
from clients.router import router as clients_router
from products.router import router as products_router
from quotes.router import router as quotes_router
from invoices.router import router as invoices_router
from projects.router import router as projects_router
from reports.router import router as reports_router
from pdf.router import router as pdf_router
from expenses.router import router as expenses_router
from contacts.router import router as contacts_router
from fastapi import FastAPI
from emails import router as emails_router  # adjust import path


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
app = FastAPI()
app.include_router(emails_router)


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
