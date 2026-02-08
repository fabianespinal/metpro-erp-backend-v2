import os
import sqlite3
from dotenv import load_dotenv
load_dotenv()

from contextlib import contextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from datetime import datetime

# ============================================================
# GLOBAL DATABASE PATH + CONNECTION FUNCTION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")

@contextmanager
def get_db_connection():
    """Global SQLite connection available to all modules."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title='METPRO ERP API',
    description='Modular ERP System for Construction & Services',
    version='2.0.0'
)


# ============================================================
# CORS CONFIGURATION (supports all Vercel preview URLs)
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)


# ============================================================
# INITIALIZE DATABASE SCHEMA ON STARTUP
# ============================================================

@app.on_event("startup")
def startup():
    schema_path = os.path.join(BASE_DIR, "schema.sql")

    if os.path.exists(schema_path):
        with sqlite3.connect(DB_PATH) as conn:
            with open(schema_path, "r") as f:
                conn.executescript(f.read())
            conn.commit()

    print("🚀 Database initialized at:", DB_PATH)


# ============================================================
# STATIC FILES
# ============================================================

if os.path.exists("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")


# ============================================================
# ROUTERS
# ============================================================

from auth.router import router as auth_router
from users.router import router as users_router
from clients.router import router as clients_router
from products.router import router as products_router
from quotes.router import router as quotes_router
from invoices.router import router as invoices_router
from projects.router import router as projects_router
from reports.router import router as reports_router
from pdf.router import router as pdf_router

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(clients_router)
app.include_router(products_router)
app.include_router(quotes_router)
app.include_router(invoices_router)
app.include_router(projects_router)
app.include_router(reports_router)
app.include_router(pdf_router)


# ============================================================
# ROOT & HEALTH ENDPOINTS
# ============================================================

@app.get("/")
def read_root():
    return {
        "message": "METPRO ERP API is running!",
        "version": "2.0.0",
        "architecture": "Modular",
        "database": "SQLite"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "modules": [
            "auth", "users", "clients", "products",
            "quotes", "invoices", "projects", "reports", "pdf"
        ]
    }