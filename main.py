import os
import sqlite3
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from datetime import datetime

# Import routers
from auth.router import router as auth_router
from users.router import router as users_router
from clients.router import router as clients_router
from products.router import router as products_router
from quotes.router import router as quotes_router
from invoices.router import router as invoices_router
from projects.router import router as projects_router
from reports.router import router as reports_router
from pdf.router import router as pdf_router

# Create ONE FastAPI app
app = FastAPI(
    title='METPRO ERP API',
    description='Modular ERP System for Construction & Services',
    version='2.0.0'
)

# ============================================================
# Startup: initialize SQLite database with absolute paths
# ============================================================
@app.on_event("startup")
def startup():
    base_dir = os.path.dirname(__file__)

    # Absolute paths
    schema_path = os.path.join(base_dir, "schema.sql")
    db_path = os.path.join(base_dir, "database.db")

    # Create DB file if missing
    if not os.path.exists(db_path):
        open(db_path, "w").close()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        with open(schema_path, "r") as f:
            cursor.executescript(f.read())
        print("Schema loaded successfully.")
    except Exception as e:
        print("Error loading schema:", e)

    conn.commit()
    conn.close()

# ============================================================
# CORS
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://metpro-erp-frontend.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# ============================================================
# Static files
# ============================================================
if os.path.exists("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# ============================================================
# Routers
# ============================================================
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
# Root
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