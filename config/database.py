import os
import sqlite3
from contextlib import contextmanager

# Database configuration
DATABASE_PATH = os.environ.get("DATABASE_PATH", "metpro_erp.db")

def get_db_connection():
    """Get a new database connection to SQLite"""
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
