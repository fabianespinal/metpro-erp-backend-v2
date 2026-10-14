import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Always load .env from the backend folder
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")
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

# Optional connection pool. Off by default. Enable with DB_POOL_ENABLED=true.
# Routes still call conn.close(); on a pooled connection that returns the
# connection to the pool instead of closing the socket.
DB_POOL_ENABLED = os.getenv("DB_POOL_ENABLED", "false").lower() == "true"
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "5"))
_pool = None


class _PooledConnection:
    """Wraps a pooled psycopg2 connection. close() returns it to the pool."""

    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn
        self._returned = False

    def close(self):
        if not self._returned:
            self._returned = True
            self._pool.putconn(self._conn)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _get_pool():
    global _pool
    if _pool is None:
        from psycopg2.pool import ThreadedConnectionPool
        _pool = ThreadedConnectionPool(
            DB_POOL_MIN, DB_POOL_MAX, DATABASE_URL, cursor_factory=RealDictCursor
        )
    return _pool


def get_db_connection():
    """
    Legacy connection function used by older modules.
    Returns a psycopg2 connection WITHOUT context manager.
    With DB_POOL_ENABLED=true the connection comes from a pool.
    """
    if DB_POOL_ENABLED:
        pool = _get_pool()
        return _PooledConnection(pool, pool.getconn())
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