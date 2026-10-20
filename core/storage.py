"""Minimal Supabase Storage client (REST over httpx) for private buckets.

Env (both required):
  SUPABASE_URL                 https://<project-ref>.supabase.co
  SUPABASE_SERVICE_ROLE_KEY    server-side only. Never sent to a browser, never logged.

When either is missing, storage_configured() is False and callers degrade with a clear message.
"""
import logging
import os
from typing import Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class StorageError(Exception):
    """Storage call failed. The message never contains credentials."""


class StorageNotConfigured(StorageError):
    pass


class StorageObjectNotFound(StorageError):
    pass


def _config() -> tuple:
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    return url, key


def storage_configured() -> bool:
    url, key = _config()
    return bool(url and key)


def _object_url(url: str, bucket: str, path: str) -> str:
    return f"{url}/storage/v1/object/{quote(bucket, safe='')}/{quote(path, safe='/')}"


def _auth(key: str, extra: Optional[dict] = None) -> dict:
    return {"Authorization": f"Bearer {key}", "apikey": key, **(extra or {})}


def _require_config() -> tuple:
    url, key = _config()
    if not (url and key):
        raise StorageNotConfigured("Supabase Storage is not configured")
    return url, key


def upload_object(bucket: str, path: str, data: bytes, content_type: str, client: Optional[httpx.Client] = None) -> None:
    """Create or replace an object (upsert)."""
    url, key = _require_config()
    own = client is None
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        res = http.post(
            _object_url(url, bucket, path),
            content=data,
            headers=_auth(key, {"Content-Type": content_type, "x-upsert": "true"}),
        )
    except httpx.HTTPError as exc:
        raise StorageError(f"Storage upload failed: {type(exc).__name__}") from exc
    finally:
        if own:
            http.close()
    if res.status_code >= 400:
        logger.error("Storage upload rejected: status=%s bucket=%s path=%s", res.status_code, bucket, path)
        raise StorageError(f"Storage upload failed: HTTP {res.status_code}")


def download_object(bucket: str, path: str, client: Optional[httpx.Client] = None) -> bytes:
    """Read an object from a private bucket."""
    url, key = _require_config()
    own = client is None
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        res = http.get(_object_url(url, bucket, path), headers=_auth(key))
    except httpx.HTTPError as exc:
        raise StorageError(f"Storage download failed: {type(exc).__name__}") from exc
    finally:
        if own:
            http.close()
    if res.status_code == 404 or (res.status_code == 400 and "not_found" in res.text.lower()):
        raise StorageObjectNotFound(f"{bucket}/{path}")
    if res.status_code >= 400:
        logger.error("Storage download rejected: status=%s bucket=%s path=%s", res.status_code, bucket, path)
        raise StorageError(f"Storage download failed: HTTP {res.status_code}")
    return res.content
