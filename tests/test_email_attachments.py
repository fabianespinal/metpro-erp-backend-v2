import io

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

import email_service
from core import email_attachments as ea


def _f(name, data):
    return UploadFile(file=io.BytesIO(data), filename=name)


def test_no_files_returns_empty():
    assert ea.read_extra_attachments(None) == []
    assert ea.read_extra_attachments([]) == []


def test_valid_files_become_attachments():
    out = ea.read_extra_attachments([_f("foto.jpg", b"abc"), _f("plano.pdf", b"%PDF")])
    assert [a["filename"] for a in out] == ["foto.jpg", "plano.pdf"]
    assert out[0]["content"] == [97, 98, 99]


def test_path_in_filename_is_stripped():
    out = ea.read_extra_attachments([_f("..\\..\\etc/passwd.txt", b"x")])
    assert out[0]["filename"] == "passwd.txt"


@pytest.mark.parametrize(
    "files,code,status",
    [
        ([_f("a.exe", b"x")], "ATTACHMENT_TYPE_BLOCKED", 400),
        ([_f("a.pdf", b"")], "ATTACHMENT_EMPTY", 400),
        ([_f("a.pdf", b"x" * (ea.MAX_FILE_BYTES + 1))], "ATTACHMENT_TOO_LARGE", 413),
        ([_f(f"{i}.pdf", b"x") for i in range(ea.MAX_FILES + 1)], "ATTACHMENT_TOO_MANY", 400),
        ([_f(f"{i}.pdf", b"x" * (ea.MAX_FILE_BYTES - 10)) for i in range(3)], "ATTACHMENT_TOTAL_TOO_LARGE", 413),
    ],
)
def test_rejections_are_spanish_and_coded(files, code, status):
    with pytest.raises(HTTPException) as e:
        ea.read_extra_attachments(files)
    assert e.value.status_code == status and e.value.code == code
    assert not e.value.detail.isascii() or any(w in e.value.detail for w in ("archivo", "adjunto", "Máximo", "Tipo"))


@pytest.mark.parametrize("fn,args", [
    (email_service.send_quote_email, ("a@b.co", "Ana", "ACME", "P", "10001", "tok", b"%PDF")),
    (email_service.send_invoice_email, ("a@b.co", "Ana", "ACME", "P", "10001", "tok", b"%PDF")),
])
def test_email_includes_extra_and_default_unchanged(monkeypatch, fn, args):
    sent = []
    monkeypatch.setattr(email_service.resend.Emails, "send", lambda p: sent.append(p) or {"id": "x"})
    fn(*args)
    fn(*args, extra_attachments=[{"filename": "foto.jpg", "content": [1]}])
    assert len(sent[0]["attachments"]) == 1
    assert [a["filename"] for a in sent[1]["attachments"]][1:] == ["foto.jpg"]
