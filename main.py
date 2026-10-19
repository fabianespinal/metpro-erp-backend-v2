import os

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

# Default "*" is kept on purpose: Railway proxy addresses change, and client IP for rate limits
# and logs is read from X-Real-IP / X-Forwarded-For by core.rate_limit, not from this middleware.
# TRUSTED_PROXY_HOSTS (comma list of IPs/CIDRs) narrows it without a code change (B-15).
_trusted = [h.strip() for h in os.environ.get("TRUSTED_PROXY_HOSTS", "*").split(",") if h.strip()] or ["*"]
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=_trusted if _trusted != ["*"] else "*")

# Unified error model: {"detail": ..., "code": ...} for every error.
from core.errors import register_error_handlers  # noqa: E402
register_error_handlers(app)

# Unhandled errors become the unified 500 body inside CORS, so the browser can read it (B-08).
# Must be added BEFORE CORSMiddleware: later add_middleware calls wrap earlier ones.
from core.error_middleware import UnhandledErrorMiddleware  # noqa: E402
app.add_middleware(UnhandledErrorMiddleware)

# ============================================================
# CORS CONFIGURATION
# ============================================================

# B-15: production allows only the production ERP and the public site.
# Staging and local development add their origins with CORS_EXTRA_ORIGINS (comma list) on their own
# service. CORS_LEGACY_ORIGINS=true restores the previous list (staging + localhost) as a rollback.
allowed_origins = [
    "https://app.metprord.com",   # production ERP
    "https://metprord.site",      # public quotes/invoices site
]
if os.environ.get("CORS_LEGACY_ORIGINS", "").strip().lower() in ("1", "true", "yes", "on"):
    allowed_origins += [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://metpro-erp-frontend-staging-production.up.railway.app",
    ]
allowed_origins += [o.strip().rstrip("/") for o in os.environ.get("CORS_EXTRA_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Audit log (item 12): metadata only, never bodies. Off /health and /auth/login.
from core.request_log_middleware import RequestLogMiddleware  # noqa: E402
app.add_middleware(RequestLogMiddleware, asgi_app=app)

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
from template_packs.router import router as template_packs_router
from emails import router as emails_router
from cover_page.router import router as cover_page_router
from terms_page.router import router as terms_router


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
app.include_router(template_packs_router)
app.include_router(emails_router)
app.include_router(cover_page_router)
app.include_router(terms_router)


# ============================================================
# ROOT & HEALTH ENDPOINTS
# ============================================================

@app.get("/")
def read_root():
    return {
        "message": "¡La API de METPRO ERP está en funcionamiento!",
        "version": "2.0.0",
        "architecture": "Modular",
        "database": "PostgreSQL (Supabase)",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


# ============================================================
# SUCCESS ENVELOPE: {"data": ..., "success": true} for every JSON success
# ============================================================
from core.responses import apply_success_envelope  # noqa: E402
apply_success_envelope(app)
