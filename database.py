import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Always load .env from the backend folder
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")
print("DEBUG DATABASE_URL =", DATABASE_URL)
# ============================================================
# SQLALCHEMY SETUP (Required for all models, including Contact)
# ============================================================

# SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# SQLAlchemy session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for all SQLAlchemy models
Base = declarative_base()


# ============================================================
# LEGACY FUNCTION (kept for backward compatibility)
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
# Returns a SQLAlchemy session for new modules
# ============================================================

def get_db():
    """
    FastAPI-compatible database dependency.
    Opens a SQLAlchemy session and closes it automatically.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()