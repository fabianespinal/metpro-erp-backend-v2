"""Company seal for printed PDFs: normalise the uploaded image, then draw it in the signature block.

The seal is drawn with the PDF engine's own image support (fpdf2). Nothing is rasterised and the PDF
is never rebuilt from bitmaps. The stored image is a transparent PNG, so the page text stays readable
and the PDF keeps the full resolution of the image.

Placement is fixed (no editor): centred on the "Representante Metpro" column, about 50 mm (1.97 in) wide,
bottom edge a few millimetres below the top of the signature name so the typed signature sits over the seal.
Future stamps (paid, approved, cancelled, ...) can reuse draw_seal() with another PreparedSeal.
"""
import io
import logging
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageOps, ImageStat

logger = logging.getLogger(__name__)

SEAL_WIDTH_MM = 50.0       # about 1.97 in; the visible seal, not the file margins
SEAL_MAX_HEIGHT_MM = 60.0  # tall images are scaled down to fit
SEAL_OVERLAP_MM = 2.0      # seal bottom edge sits this far below the top of the signature name

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 25_000_000
MAX_SIDE_PX = 1600         # 50 mm at 300 dpi is about 590 px; this leaves a wide margin and a small file
ALLOWED_FORMATS = {"PNG", "JPEG"}


class SealImageError(ValueError):
    """The uploaded file cannot be used as a seal. The message is shown to the user (Spanish)."""


@dataclass(frozen=True)
class PreparedSeal:
    data: bytes        # transparent PNG
    width_mm: float
    height_mm: float


def _ink_alpha(rgb: Image.Image) -> Image.Image:
    """Alpha for an opaque image (JPG): the further a pixel is from white, the more opaque it is.

    Measured on the darkest channel, so light inks (yellow, pale red) stay visible. White paper and
    JPEG noise become transparent.
    """
    r, g, b = (ImageOps.invert(c) for c in rgb.split())
    away_from_white = ImageChops.lighter(ImageChops.lighter(r, g), b)
    low, high = 20, 160
    return away_from_white.point(lambda v: 0 if v < low else 255 if v >= high else int((v - low) * 255 / (high - low)))


def _with_clean_colour(rgb: Image.Image, alpha: Image.Image) -> Image.Image:
    """RGBA from an opaque image. JPEG noise would bloat every PDF, so tidy the colour channels.

    A one-colour stamp (the usual case) is rebuilt as one ink colour with the shape carried by the alpha
    channel: crisp edges and a small file. A multi-colour image keeps its colours.
    """
    solid_ink = alpha.point(lambda v: 255 if v > 250 else 0)
    ink = None
    if solid_ink.getbbox() is not None:
        stat = ImageStat.Stat(rgb, mask=solid_ink)
        if max(stat.stddev) < 45:
            ink = tuple(int(c) for c in stat.median)
    if ink is None:
        ink = (0, 0, 0)
        rgb = Image.composite(rgb, Image.new("RGB", rgb.size, ink), alpha.point(lambda v: 255 if v > 0 else 0))
        out = rgb.copy()
    else:
        out = Image.new("RGB", rgb.size, ink)
    out.putalpha(alpha)
    return out


def normalize_seal_image(raw: bytes) -> bytes:
    """Validate an uploaded PNG or JPG and return a cropped, transparent PNG. Raises SealImageError."""
    if not raw:
        raise SealImageError("El archivo está vacío.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise SealImageError("El archivo supera el máximo de 5 MB.")
    try:
        probe = Image.open(io.BytesIO(raw))
        fmt = probe.format
        probe.verify()
    except Exception:
        raise SealImageError("El archivo no es una imagen válida. Use PNG o JPG.")
    if fmt not in ALLOWED_FORMATS:
        raise SealImageError("Formato no admitido. Use PNG o JPG.")
    try:
        img = Image.open(io.BytesIO(raw))
        if img.width * img.height > MAX_PIXELS:
            raise SealImageError("La imagen es demasiado grande. Use una de menos de 25 megapíxeles.")
        img.load()
        img = ImageOps.exif_transpose(img)
    except SealImageError:
        raise
    except Exception:
        raise SealImageError("No se pudo leer la imagen.")

    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    if has_alpha:
        rgba = img.convert("RGBA")
    else:
        rgb = img.convert("RGB")
        alpha = _ink_alpha(rgb)
        rgba = _with_clean_colour(rgb, alpha)

    # Crop to the visible seal so the printed width is the seal itself, not the file margins.
    box = rgba.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if box is None:
        raise SealImageError("La imagen no contiene un sello visible.")
    pad = 2
    box = (max(0, box[0] - pad), max(0, box[1] - pad), min(rgba.width, box[2] + pad), min(rgba.height, box[3] + pad))
    rgba = rgba.crop(box)

    if max(rgba.size) > MAX_SIDE_PX:
        rgba.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX), Image.LANCZOS)

    out = io.BytesIO()
    rgba.save(out, format="PNG", optimize=True)
    return out.getvalue()


def prepare_seal(png_bytes: bytes) -> PreparedSeal:
    """Size the seal for the page. Keeps the aspect ratio."""
    with Image.open(io.BytesIO(png_bytes)) as im:
        w, h = im.size
    if w <= 0 or h <= 0:
        raise SealImageError("La imagen no es válida.")
    width = SEAL_WIDTH_MM
    height = width * h / w
    if height > SEAL_MAX_HEIGHT_MM:
        width, height = width * SEAL_MAX_HEIGHT_MM / height, SEAL_MAX_HEIGHT_MM
    return PreparedSeal(data=png_bytes, width_mm=width, height_mm=height)


def seal_top_for(sig_y: float, seal: PreparedSeal) -> float:
    return sig_y + SEAL_OVERLAP_MM - seal.height_mm


def draw_seal(pdf, seal: PreparedSeal, center_x: float, sig_y: float) -> None:
    """Draw the seal centred on center_x, ending SEAL_OVERLAP_MM below sig_y. Call before the signature text."""
    pdf.image(
        io.BytesIO(seal.data),
        x=center_x - seal.width_mm / 2,
        y=seal_top_for(sig_y, seal),
        w=seal.width_mm,
        h=seal.height_mm,
    )
