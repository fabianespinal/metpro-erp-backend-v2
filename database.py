import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


# ============================================================
# OLD FUNCTION (kept for backward compatibility)
# Many routers still depend on this.
# ============================================================
def get_db_connection():
    """
    Legacy connection function used by older modules.
    Returns a psycopg2 connection WITHOUT context manager.
    """
    conn = psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )
    return conn


# ============================================================
# NEW FUNCTION (FastAPI dependency)
# MUST return a real connection, NOT a context manager.
# ============================================================
def get_db():
    """
    FastAPI-compatible database dependency.
    Opens a PostgreSQL connection and closes it automatically.
    """
    conn = psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )
    try:
        yield conn
    finally:
        conn.close()