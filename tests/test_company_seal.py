"""Company seal (sello) on PDFs: image handling, drawing, storage client, service, routes.

Rules under test:
  - The seal prints only when a request asks for it (print_seal=true). Default is no seal.
  - With the seal off, the PDF code path is unchanged.
  - Asking for a seal that cannot load is an error, never a silent unstamped PDF.
"""
import io
import os
import re
import sys

import httpx
import pytest
from PIL import Image, ImageDraw

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import quotes  # noqa: E402,F401  (import order: avoids a circular import via pdf)
import auth.service as auth_service  # noqa: E402
import company_settings.service as cs  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from core import storage  # noqa: E402
from main import app  # noqa: E402
from pdf.utils import layout_utils, seal_utils  # noqa: E402
from pdf.builder_conduce import create_conduce_pdf  # noqa: E402


# ---------------------------------------------------------------- helpers

def _jpg_seal(size=(400, 300), ink=(16, 49, 125)) -> bytes:
    """A one-colour ring on a white JPG with margins, like the real seal file."""
    im = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(im)
    d.ellipse((50, 30, size[0] - 50, size[1] - 30), outline=ink, width=14)
    d.rectangle((size[0] // 2 - 40, size[1] // 2 - 20, size[0] // 2 + 40, size[1] // 2 + 20), fill=ink)
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=70)
    return out.getvalue()


def _png(mode="RGBA", size=(200, 100), color=(200, 0, 0, 255)) -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture(autouse=True)
def _fresh_cache():
    cs._clear_cache()
    yield
    cs._clear_cache()


def _items(n=3):
    return [{"name": f"Viga {i}", "description": "", "quantity": 1, "unit_price": 100, "discount_type": None,
             "discount_value": 0, "unit": "u", "category": None, "total": 100} for i in range(n)]


def _quote(monkeypatch, seal=None, n=3, **extra):
    monkeypatch.setattr("cover_page.service.get_active_body", lambda kind: None)
    monkeypatch.setattr("terms_page.service.get_active_sections", lambda kind: None)
    return layout_utils.build_quote_invoice_pdf(
        doc_type="COTIZACION", doc_id="Q-10001", doc_date="20/10/2026",
        client={"company_name": "ACME", "contact_name": "Ana", "address": "", "email": "", "phone": ""},
        project_name="P", notes="", items=_items(n), charges={}, items_total=100, total_discounts=0,
        items_after_discount=100, supervision=0, supervision_pct=0, admin=0, admin_pct=0, insurance=0,
        insurance_pct=0, transport=0, transport_pct=0, contingency=0, contingency_pct=0,
        subtotal_general=100, itbis=18, grand_total=118, signer_name="Fabian", seal=seal, **extra,
    ).getvalue()


def _images(pdf_bytes: bytes) -> int:
    return len(re.findall(rb"/Subtype\s*/Image", pdf_bytes))


def _pages(pdf_bytes: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf_bytes))


# ---------------------------------------------------------------- image normalisation

def test_jpg_white_background_becomes_transparent_and_cropped():
    png = seal_utils.normalize_seal_image(_jpg_seal())
    im = Image.open(io.BytesIO(png))
    assert im.format == "PNG" and im.mode == "RGBA"
    assert im.getpixel((0, 0))[3] == 0                      # paper corner is transparent
    assert im.width < 400 and im.height < 300               # margins were cropped away
    # the ring is solid ink
    assert any(im.getpixel((x, im.height // 2))[3] == 255 for x in range(im.width))


def test_single_colour_stamp_is_rebuilt_as_one_ink_colour():
    png = seal_utils.normalize_seal_image(_jpg_seal())
    im = Image.open(io.BytesIO(png))
    solid = {im.getpixel((x, y))[:3] for x in range(0, im.width, 3) for y in range(0, im.height, 3) if im.getpixel((x, y))[3] == 255}
    assert len(solid) == 1
    r, g, b = next(iter(solid))
    assert abs(r - 16) < 25 and abs(g - 49) < 25 and abs(b - 125) < 25
    assert len(png) < 40_000                                 # JPEG noise does not bloat the PDF


def test_png_with_alpha_keeps_its_alpha():
    src = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    ImageDraw.Draw(src).ellipse((10, 10, 110, 110), fill=(0, 128, 0, 255))
    out = io.BytesIO()
    src.save(out, format="PNG")
    png = seal_utils.normalize_seal_image(out.getvalue())
    im = Image.open(io.BytesIO(png))
    assert im.getpixel((0, 0))[3] == 0
    assert im.getpixel((im.width // 2, im.height // 2)) == (0, 128, 0, 255)


def test_multicolour_jpg_keeps_its_colours():
    src = Image.new("RGB", (200, 200), "white")
    d = ImageDraw.Draw(src)
    d.rectangle((20, 20, 100, 180), fill=(200, 0, 0))
    d.rectangle((100, 20, 180, 180), fill=(0, 0, 200))
    out = io.BytesIO()
    src.save(out, format="PNG")
    im = Image.open(io.BytesIO(seal_utils.normalize_seal_image(out.getvalue())))
    left, right = im.getpixel((im.width // 4, im.height // 2)), im.getpixel((3 * im.width // 4, im.height // 2))
    assert left[:3] != right[:3] and left[3] == 255 and right[3] == 255


def test_light_ink_stays_visible():
    src = Image.new("RGB", (160, 160), "white")
    ImageDraw.Draw(src).ellipse((10, 10, 150, 150), outline=(255, 215, 0), width=16)   # yellow: very light in luminance
    out = io.BytesIO()
    src.save(out, format="PNG")
    im = Image.open(io.BytesIO(seal_utils.normalize_seal_image(out.getvalue())))
    assert im.getpixel((im.width // 2, 8))[3] == 255        # the ring is opaque, not faded out


def test_large_image_is_downscaled():
    big = Image.new("RGB", (3000, 3000), "white")
    ImageDraw.Draw(big).ellipse((100, 100, 2900, 2900), outline=(0, 0, 100), width=60)
    out = io.BytesIO()
    big.save(out, format="PNG")
    im = Image.open(io.BytesIO(seal_utils.normalize_seal_image(out.getvalue())))
    assert max(im.size) <= seal_utils.MAX_SIDE_PX


@pytest.mark.parametrize(
    "raw,fragment",
    [
        (b"", "vacío"),
        (b"not an image at all", "no es una imagen"),
        (b"x" * (seal_utils.MAX_UPLOAD_BYTES + 1), "5 MB"),
        (Image.new("RGB", (50, 50), "white").tobytes(), "no es una imagen"),
    ],
)
def test_bad_uploads_are_rejected_with_a_spanish_message(raw, fragment):
    with pytest.raises(seal_utils.SealImageError) as exc:
        seal_utils.normalize_seal_image(raw)
    assert fragment in str(exc.value)


def test_gif_is_rejected():
    out = io.BytesIO()
    Image.new("P", (40, 40), 1).save(out, format="GIF")
    with pytest.raises(seal_utils.SealImageError) as exc:
        seal_utils.normalize_seal_image(out.getvalue())
    assert "PNG o JPG" in str(exc.value)


def test_blank_white_image_has_no_visible_seal():
    out = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(out, format="PNG")
    with pytest.raises(seal_utils.SealImageError) as exc:
        seal_utils.normalize_seal_image(out.getvalue())
    assert "sello visible" in str(exc.value)


def test_too_many_pixels_rejected(monkeypatch):
    monkeypatch.setattr(seal_utils, "MAX_PIXELS", 1000)
    with pytest.raises(seal_utils.SealImageError) as exc:
        seal_utils.normalize_seal_image(_jpg_seal())
    assert "demasiado grande" in str(exc.value)


# ---------------------------------------------------------------- sizing

def test_prepared_seal_is_50mm_wide_and_keeps_aspect():
    seal = seal_utils.prepare_seal(seal_utils.normalize_seal_image(_jpg_seal()))
    assert seal.width_mm == pytest.approx(50.0)
    with Image.open(io.BytesIO(seal.data)) as im:
        assert seal.height_mm == pytest.approx(50.0 * im.height / im.width)
    assert 1.75 <= seal.width_mm / 25.4 <= 2.25             # within the 1.75 to 2.25 in brief


def test_tall_image_is_capped_in_height_without_distortion():
    png = _png(size=(100, 400))
    seal = seal_utils.prepare_seal(png)
    assert seal.height_mm == pytest.approx(seal_utils.SEAL_MAX_HEIGHT_MM)
    assert seal.width_mm / seal.height_mm == pytest.approx(100 / 400)


# ---------------------------------------------------------------- drawing and layout

def _seal(w=50.0, h=48.0):
    return seal_utils.PreparedSeal(data=seal_utils.normalize_seal_image(_jpg_seal()), width_mm=w, height_mm=h)


def test_seal_off_never_touches_the_drawing_code(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("draw_seal must not run when no seal is requested")
    monkeypatch.setattr(layout_utils, "draw_seal", boom)
    _quote(monkeypatch, seal=None)


def test_seal_off_leaves_signature_position_unchanged(monkeypatch):
    positions = []
    real = layout_utils.add_footer_with_signature

    def spy(pdf, signer_name=None, seal=None):
        positions.append(pdf.get_y())
        return real(pdf, signer_name, seal=seal)

    monkeypatch.setattr(layout_utils, "add_footer_with_signature", spy)
    a = _quote(monkeypatch, seal=None)
    b = _quote(monkeypatch)  # no seal argument at all
    strip = lambda x: re.sub(rb"/ID \[[^\]]*\]", b"", re.sub(rb"/CreationDate \(D:[^)]*\)", b"", x))  # noqa: E731
    assert strip(a) == strip(b)
    assert len(positions) == 2 and positions[0] == positions[1]


def test_seal_on_adds_one_image_and_keeps_the_text(monkeypatch):
    without = _quote(monkeypatch, seal=None)
    with_seal = _quote(monkeypatch, seal=_seal())
    assert _images(with_seal) == _images(without) + 2       # the seal image plus its transparency mask
    assert _pages(with_seal) == _pages(without)


def test_seal_is_centred_on_the_metpro_column_and_clear_of_content(monkeypatch):
    calls = []
    real = layout_utils.draw_seal
    monkeypatch.setattr(layout_utils, "draw_seal", lambda pdf, seal, center_x, sig_y: (calls.append((center_x, sig_y, pdf.get_y())), real(pdf, seal, center_x, sig_y)))
    seal = _seal()
    _quote(monkeypatch, seal=seal)
    assert len(calls) == 1
    center_x, sig_y, y_before = calls[0]
    assert center_x == pytest.approx(15 + 75 / 2)           # centre of the "Representante Metpro" column
    top = seal_utils.seal_top_for(sig_y, seal)
    assert top >= y_before                                   # never over the totals above
    assert sig_y + seal_utils.SEAL_OVERLAP_MM - top == pytest.approx(seal.height_mm)
    # the seal body sits about 0.5 to 0.9 in above the signature text, its lower edge just touching it
    above_mm = seal.height_mm / 2 - seal_utils.SEAL_OVERLAP_MM
    assert 0.5 <= above_mm / 25.4 <= 0.9
    assert 0 < seal_utils.SEAL_OVERLAP_MM <= 3              # overlaps the typed signature slightly, never buries it


def test_seal_near_page_bottom_moves_to_a_new_page_with_room(monkeypatch):
    calls = []
    real = layout_utils.draw_seal
    monkeypatch.setattr(layout_utils, "draw_seal", lambda pdf, seal, center_x, sig_y: (calls.append(seal_utils.seal_top_for(sig_y, seal)), real(pdf, seal, center_x, sig_y)))
    out = _quote(monkeypatch, seal=_seal(), n=40)
    assert calls and calls[0] >= 14.9                        # top margin respected on the new page
    assert _pages(out) >= 2


def test_seal_draw_failure_does_not_break_the_pdf(monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("image decode failed")
    monkeypatch.setattr(layout_utils, "draw_seal", boom)
    out = _quote(monkeypatch, seal=_seal())
    assert out.startswith(b"%PDF")
    assert "Seal drawing failed" in caplog.text


def test_conduce_prints_the_seal_only_when_given():
    items = [{"name": "Viga", "quantity": 2, "unit": "u", "description": "", "category": None}]
    off = create_conduce_pdf("C-1", "20/10/2026", {"company_name": "ACME"}, "P", "", items, signer_name="Ana").read()
    on = create_conduce_pdf("C-1", "20/10/2026", {"company_name": "ACME"}, "P", "", items, signer_name="Ana", seal=_seal()).read()
    assert _images(on) == _images(off) + 2                  # image plus transparency mask


def test_invoice_and_quote_builders_pass_the_seal_through(monkeypatch):
    from pdf.builder_invoice import create_invoice_pdf
    from pdf.builder_quote import create_quote_pdf
    seen = []
    monkeypatch.setattr("pdf.builder_quote.build_quote_invoice_pdf", lambda **kw: (seen.append(kw["seal"]), io.BytesIO(b"x"))[1])
    monkeypatch.setattr("pdf.builder_invoice.build_quote_invoice_pdf", lambda **kw: (seen.append(kw["seal"]), io.BytesIO(b"x"))[1])
    common = dict(doc_id="X", doc_date="d", client={}, project_name="", notes="", items=[], charges={}, items_total=0,
                  total_discounts=0, items_after_discount=0, supervision=0, supervision_pct=0, admin=0, admin_pct=0,
                  insurance=0, insurance_pct=0, transport=0, transport_pct=0, contingency=0, contingency_pct=0,
                  subtotal_general=0, itbis=0, grand_total=0)
    marker = object()
    create_quote_pdf(doc_type="COTIZACION", seal=marker, **common)
    create_invoice_pdf(doc_type="FACTURA", seal=marker, **common)
    create_quote_pdf(doc_type="COTIZACION", **common)
    create_invoice_pdf(doc_type="FACTURA", **common)
    assert seen == [marker, marker, None, None]


# ---------------------------------------------------------------- storage client

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co/")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key-123")


def test_storage_not_configured_without_env(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert storage.storage_configured() is False
    with pytest.raises(storage.StorageNotConfigured):
        storage.upload_object("b", "p.png", b"x", "image/png")
    with pytest.raises(storage.StorageNotConfigured):
        storage.download_object("b", "p.png")


def test_storage_needs_both_variables(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert storage.storage_configured() is False


def test_upload_posts_with_upsert_and_bearer(env, monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "eyJ-service-key-123")
    seen = {}

    def handler(request):
        seen.update(method=request.method, url=str(request.url), auth=request.headers["authorization"],
                    upsert=request.headers["x-upsert"], ctype=request.headers["content-type"], body=request.content)
        return httpx.Response(200, json={"Key": "company-seals/metpro/seal.png"})

    storage.upload_object("company-seals", "metpro/seal.png", b"PNGDATA", "image/png", client=_client(handler))
    assert seen["method"] == "POST"
    assert seen["url"] == "https://abc.supabase.co/storage/v1/object/company-seals/metpro/seal.png"
    assert seen["auth"] == "Bearer eyJ-service-key-123" and seen["upsert"] == "true" and seen["ctype"] == "image/png"
    assert seen["body"] == b"PNGDATA"


def test_legacy_jwt_key_goes_in_both_headers(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "eyJhbGciOi.payload.sig")
    seen = {}
    storage.upload_object("b", "p.png", b"x", "image/png", client=_client(lambda r: (seen.update(r.headers), httpx.Response(200))[1]))
    assert seen["authorization"] == "Bearer eyJhbGciOi.payload.sig" and seen["apikey"] == "eyJhbGciOi.payload.sig"


def test_new_style_secret_key_is_sent_in_apikey_only(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_abc123")
    seen = {}
    storage.upload_object("b", "p.png", b"x", "image/png", client=_client(lambda r: (seen.update(r.headers), httpx.Response(200))[1]))
    assert seen["apikey"] == "sb_secret_abc123" and "authorization" not in seen


def test_rejection_reason_is_logged_without_the_key(env, caplog):
    body = '{"statusCode":"400","error":"Bucket not found"}'
    with pytest.raises(storage.StorageError):
        storage.upload_object("b", "p.png", b"x", "image/png", client=_client(lambda r: httpx.Response(400, text=body)))
    assert "Bucket not found" in caplog.text and "service-key-123" not in caplog.text


def test_download_returns_bytes_and_uses_the_private_route(env):
    def handler(request):
        assert request.method == "GET" and str(request.url).endswith("/storage/v1/object/company-seals/metpro/seal.png")
        return httpx.Response(200, content=b"PNGDATA")

    assert storage.download_object("company-seals", "metpro/seal.png", client=_client(handler)) == b"PNGDATA"


@pytest.mark.parametrize("response", [httpx.Response(404), httpx.Response(400, json={"error": "not_found"})])
def test_missing_object_is_reported_as_not_found(env, response):
    with pytest.raises(storage.StorageObjectNotFound):
        storage.download_object("company-seals", "x.png", client=_client(lambda r: response))


def test_server_errors_raise_without_leaking_the_key(env):
    with pytest.raises(storage.StorageError) as exc:
        storage.upload_object("b", "p.png", b"x", "image/png", client=_client(lambda r: httpx.Response(500, text="boom service-key-123")))
    assert "service-key-123" not in str(exc.value)

    def down(request):
        raise httpx.ConnectError("no route to host")

    with pytest.raises(storage.StorageError) as exc2:
        storage.download_object("b", "p.png", client=_client(down))
    assert "service-key-123" not in str(exc2.value)


# ---------------------------------------------------------------- service

class _Row(dict):
    pass


def _row(path="metpro/seal.png", default=False):
    return _Row(seal_image_url=path, seal_enabled_by_default=default, updated_at=None, updated_by="fabian")


def test_print_seal_false_never_reads_the_db_or_storage(monkeypatch):
    monkeypatch.setattr(cs, "_row", lambda: (_ for _ in ()).throw(AssertionError("db read")))
    monkeypatch.setattr(cs, "download_object", lambda *a, **k: (_ for _ in ()).throw(AssertionError("storage read")))
    assert cs.seal_for_pdf(False) is None


@pytest.mark.parametrize("value", [None, False, 0, 1, "true", "yes", object()])
def test_only_a_literal_true_ever_prints_a_seal(monkeypatch, value):
    monkeypatch.setattr(cs, "_row", lambda: (_ for _ in ()).throw(AssertionError("db read")))
    assert cs.seal_for_pdf(value) is None


def test_calling_a_send_route_function_directly_does_not_request_a_seal(monkeypatch):
    """The Form(False) default is a truthy marker object when the function is called without FastAPI."""
    import quotes.router as _unused  # noqa: F401
    import importlib
    router = importlib.import_module("quotes.router")
    monkeypatch.setattr(router.service, "get_quote_with_contact", lambda qid: {"public_token": None, "status": "Draft"})
    monkeypatch.setattr(cs, "_row", lambda: (_ for _ in ()).throw(AssertionError("db read")))
    with pytest.raises(HTTPException) as exc:
        router.send_quote("00000000-0000-0000-0000-000000000000", current_user={})
    assert exc.value.code == "QUOTE_NOT_FINALIZED"


def test_asked_for_but_not_uploaded_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(cs, "_row", lambda: _row(path=None))
    with pytest.raises(HTTPException) as exc:
        cs.seal_for_pdf(True)
    assert exc.value.status_code == 503 and exc.value.code == "SEAL_UNAVAILABLE"
    assert "Imprimir sello" in exc.value.detail             # tells the user what to do


def test_asked_for_but_storage_down_is_an_error_not_a_blank_pdf(monkeypatch):
    monkeypatch.setattr(cs, "_row", lambda: _row())
    monkeypatch.setattr(cs, "download_object", lambda *a, **k: (_ for _ in ()).throw(storage.StorageError("down")))
    with pytest.raises(HTTPException) as exc:
        cs.seal_for_pdf(True)
    assert exc.value.status_code == 503 and exc.value.code == "SEAL_UNAVAILABLE"


def test_load_returns_a_prepared_seal_and_caches_it(monkeypatch):
    downloads = []
    png = seal_utils.normalize_seal_image(_jpg_seal())
    monkeypatch.setattr(cs, "_row", lambda: _row())
    monkeypatch.setattr(cs, "download_object", lambda bucket, path: (downloads.append((bucket, path)), png)[1])
    first = cs.seal_for_pdf(True)
    second = cs.seal_for_pdf(True)
    assert first is second and first.width_mm == pytest.approx(50.0)
    assert downloads == [("company-seals", "metpro/seal.png")]   # one download, then cache


def test_cache_expires(monkeypatch):
    downloads = []
    png = seal_utils.normalize_seal_image(_jpg_seal())
    monkeypatch.setattr(cs, "_row", lambda: _row())
    monkeypatch.setattr(cs, "download_object", lambda b, p: (downloads.append(1), png)[1])
    cs.seal_for_pdf(True)
    cs._cache["at"] -= cs.CACHE_SECONDS + 1
    cs.seal_for_pdf(True)
    assert len(downloads) == 2


class _FakeConn:
    def __init__(self):
        self.executed, self.commits, self.rollbacks, self.closed = [], 0, 0, False

    def cursor(self):
        conn = self

        class Cur:
            def execute(self, sql, params=None):
                conn.executed.append((sql, params))

        return Cur()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_save_uploads_first_then_updates_the_row_and_clears_the_cache(monkeypatch, env):
    order = []
    conn = _FakeConn()
    monkeypatch.setattr(cs, "upload_object", lambda b, p, data, ct: order.append(("upload", b, p, ct, data[:4])))
    monkeypatch.setattr(cs, "get_db_connection", lambda: (order.append("db"), conn)[1])
    monkeypatch.setattr(cs, "get_seal_settings", lambda: {"configured": True})
    cs._cache.update(at=1e12, path="old", seal="stale")
    out = cs.save_seal_image(_jpg_seal(), "fabian")
    assert out == {"configured": True}
    assert order[0][:4] == ("upload", "company-seals", "metpro/seal.png", "image/png") and order[0][4] == b"\x89PNG"
    assert order[1] == "db" and conn.commits == 1 and conn.closed
    assert conn.executed[0][1] == ("metpro/seal.png", "fabian")
    assert cs._cache["seal"] is None


def test_failed_upload_leaves_the_row_untouched(monkeypatch, env):
    monkeypatch.setattr(cs, "upload_object", lambda *a, **k: (_ for _ in ()).throw(storage.StorageError("x")))
    monkeypatch.setattr(cs, "get_db_connection", lambda: (_ for _ in ()).throw(AssertionError("row must not change")))
    with pytest.raises(HTTPException) as exc:
        cs.save_seal_image(_jpg_seal(), "fabian")
    assert exc.value.status_code == 502


def test_save_without_storage_config_is_503_and_touches_nothing(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setattr(cs, "get_db_connection", lambda: (_ for _ in ()).throw(AssertionError("no db")))
    with pytest.raises(HTTPException) as exc:
        cs.save_seal_image(_jpg_seal(), "fabian")
    assert exc.value.status_code == 503


def test_save_rejects_a_bad_image_with_422(monkeypatch, env):
    monkeypatch.setattr(cs, "upload_object", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no upload")))
    with pytest.raises(HTTPException) as exc:
        cs.save_seal_image(b"junk", "fabian")
    assert exc.value.status_code == 422


def test_settings_never_expose_the_storage_path(monkeypatch, env):
    monkeypatch.setattr(cs, "_row", lambda: _row(default=True))
    out = cs.get_seal_settings()
    assert out["configured"] is True and out["enabled_by_default"] is True and out["storage_ready"] is True
    assert "seal_image_url" not in out and "metpro/seal.png" not in str(out)


def test_settings_with_no_row_defaults_to_off(monkeypatch):
    monkeypatch.setattr(cs, "_row", lambda: None)
    out = cs.get_seal_settings()
    assert out["configured"] is False and out["enabled_by_default"] is False


# ---------------------------------------------------------------- routes

def _token(role):
    return create_access_token({"sub": f"{role}-user", "user_id": 1, "role": role})


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda sub: None)
    return TestClient(app, raise_server_exceptions=False)


def _auth(role):
    return {"Authorization": f"Bearer {_token(role)}"}


def test_settings_routes_require_login(client):
    for method, path in [("GET", "/company-settings/seal"), ("PUT", "/company-settings/seal"),
                         ("POST", "/company-settings/seal/image"), ("GET", "/company-settings/seal/image")]:
        assert client.request(method, path).status_code == 401, (method, path)


def test_any_user_can_read_status_but_only_admins_change_it(client, monkeypatch):
    monkeypatch.setattr(cs, "get_seal_settings", lambda: {"configured": True, "enabled_by_default": False, "storage_ready": True})
    called = []
    monkeypatch.setattr(cs, "set_enabled_by_default", lambda enabled, actor: called.append((enabled, actor)) or {"enabled_by_default": enabled})
    monkeypatch.setattr(cs, "save_seal_image", lambda raw, actor: called.append(("image", actor)) or {"configured": True})

    assert client.get("/company-settings/seal", headers=_auth("user")).status_code == 200
    assert client.put("/company-settings/seal", json={"enabled_by_default": True}, headers=_auth("user")).status_code == 403
    assert client.post("/company-settings/seal/image", files={"file": ("s.png", _png(), "image/png")}, headers=_auth("user")).status_code == 403
    assert client.get("/company-settings/seal/image", headers=_auth("user")).status_code == 403
    assert called == []

    r = client.put("/company-settings/seal", json={"enabled_by_default": True}, headers=_auth("admin"))
    assert r.status_code == 200 and called == [(True, "admin-user")]
    r = client.post("/company-settings/seal/image", files={"file": ("s.png", _png(), "image/png")}, headers=_auth("admin"))
    assert r.status_code == 200 and called[-1] == ("image", "admin-user")


def test_upload_over_5mb_is_rejected_before_processing(client, monkeypatch):
    monkeypatch.setattr(cs, "save_seal_image", lambda *a, **k: (_ for _ in ()).throw(AssertionError("too big to process")))
    big = b"x" * (seal_utils.MAX_UPLOAD_BYTES + 10)
    r = client.post("/company-settings/seal/image", files={"file": ("s.png", big, "image/png")}, headers=_auth("admin"))
    assert r.status_code == 422


def test_preview_image_route_returns_png(client, monkeypatch):
    monkeypatch.setattr(cs, "get_seal_image_bytes", lambda: b"\x89PNG-bytes")
    r = client.get("/company-settings/seal/image", headers=_auth("admin"))
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == b"\x89PNG-bytes"


def test_pdf_routes_default_to_no_seal_and_pass_the_flag(client, monkeypatch):
    import pdf.service as pdf_service
    seen = []
    for name in ("generate_quote_pdf", "generate_invoice_pdf", "generate_conduce_pdf"):
        monkeypatch.setattr(pdf_service, name, lambda *a, _n=name, **k: (seen.append((_n, a[2] if len(a) > 2 else k.get("print_seal"))), {"ok": True})[1])
    for path in ("/pdf/quotes/abc", "/pdf/invoices/1", "/pdf/invoices/1/conduce"):
        assert client.get(path, headers=_auth("user")).status_code == 200
        assert client.get(path + "?print_seal=true", headers=_auth("user")).status_code == 200
        assert client.get(path + "?print_seal=false", headers=_auth("user")).status_code == 200
    assert [flag for _, flag in seen] == [False, True, False] * 3
    assert [n for n, _ in seen][::3] == ["generate_quote_pdf", "generate_invoice_pdf", "generate_conduce_pdf"]


@pytest.mark.parametrize("path,router_module", [("/quotes/Q1/send", "quotes.router"), ("/invoices/1/send", "invoices.router")])
def test_send_routes_resolve_the_seal_before_anything_is_emailed(client, monkeypatch, path, router_module):
    import importlib
    router = importlib.import_module(router_module)
    asked = []

    def fake_seal(flag):
        asked.append(flag)
        if flag:
            raise HTTPException(status_code=503, detail="sello no disponible")
        return None

    monkeypatch.setattr(router, "seal_for_pdf", fake_seal)
    # Anything past the seal step must not run when the seal fails.
    sent = []
    for name in ("send_quote_email", "send_invoice_email"):
        if hasattr(router, name):
            monkeypatch.setattr(router, name, lambda *a, **k: sent.append(1))

    r = client.post(path, data={"print_seal": "true"}, headers=_auth("user"))
    assert r.status_code == 503 and sent == [] and asked == [True]

    # Default and explicit false both mean no seal.
    monkeypatch.setattr(router.service, "get_quote_with_contact", lambda *_: (_ for _ in ()).throw(HTTPException(status_code=404, detail="stop")), raising=False)
    monkeypatch.setattr(router.service, "get_invoice_with_contact", lambda *_: None, raising=False)
    client.post(path, headers=_auth("user"))
    client.post(path, data={"print_seal": "false"}, headers=_auth("user"))
    assert asked == [True, False, False] and sent == []


def test_public_pdf_routes_never_print_the_seal():
    import inspect
    import importlib
    ir = importlib.import_module("invoices.router")
    qr = importlib.import_module("quotes.router")
    assert "seal" not in inspect.getsource(qr.get_quote_public_pdf)
    assert "seal" not in inspect.getsource(ir._render_public_invoice_pdf)
