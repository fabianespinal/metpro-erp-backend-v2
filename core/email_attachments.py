"""Stateless extra attachments for outgoing quote/invoice emails.

Files are read into memory, validated, handed to the email provider and dropped.
Nothing is written to disk, the database or storage. No URLs are generated.
"""
from typing import List, Optional

from core.errors import api_error

MAX_FILES = 5
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024

# Executable or script types are refused. Everything else the user picks is allowed.
BLOCKED_EXTENSIONS = {
    "exe", "bat", "cmd", "com", "msi", "scr", "js", "vbs", "ps1", "sh", "jar", "dll", "apk",
}


def _safe_filename(name: Optional[str], index: int) -> str:
    base = (name or "").replace("\\", "/").split("/")[-1]
    base = "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"|?*').strip().strip(".")
    return base[:120] or f"archivo_{index + 1}"


def read_extra_attachments(files: Optional[List]) -> List[dict]:
    """Return Resend-style attachment dicts for the uploaded files. Raises Spanish 4xx errors."""
    # Direct calls (tests, scripts) may pass FastAPI's File() default instead of a list.
    if not isinstance(files, (list, tuple)):
        return []
    files = [f for f in files if getattr(f, "filename", None)]
    if not files:
        return []
    if len(files) > MAX_FILES:
        raise api_error(400, f"Máximo {MAX_FILES} archivos adjuntos por correo.", "ATTACHMENT_TOO_MANY")

    result: List[dict] = []
    total = 0
    for i, f in enumerate(files):
        filename = _safe_filename(f.filename, i)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in BLOCKED_EXTENSIONS:
            raise api_error(400, f"Tipo de archivo no permitido: {filename}", "ATTACHMENT_TYPE_BLOCKED")
        data = f.file.read(MAX_FILE_BYTES + 1)
        if not data:
            raise api_error(400, f"El archivo está vacío: {filename}", "ATTACHMENT_EMPTY")
        if len(data) > MAX_FILE_BYTES:
            raise api_error(
                413, f"El archivo supera el máximo de {MAX_FILE_BYTES // (1024 * 1024)} MB: {filename}", "ATTACHMENT_TOO_LARGE"
            )
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise api_error(
                413, f"El total de adjuntos supera el máximo de {MAX_TOTAL_BYTES // (1024 * 1024)} MB.", "ATTACHMENT_TOTAL_TOO_LARGE"
            )
        result.append({"filename": filename, "content": list(data)})
    return result
