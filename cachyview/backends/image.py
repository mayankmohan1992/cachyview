"""Image backend: load, inspect, edit and convert raster images.  No Qt imports.

Editing is modelled as a list of :class:`Op` values applied in order to the
original image (``apply_ops``).  Nothing is mutated in place, so undo/redo in
the UI is just a matter of shortening or extending that list, and the original
file is never touched until an explicit save.
"""
from __future__ import annotations

import io
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# Pillow refuses very large images to avoid decompression bombs.  Keep that
# protection but raise the ceiling: 256 Mpx covers legitimate scans and panoramas.
Image.MAX_IMAGE_PIXELS = 256_000_000

# Formats we can write, mapped to the Pillow format name.
SAVE_FORMATS = {
    ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP",
    ".bmp": "BMP", ".tif": "TIFF", ".tiff": "TIFF", ".gif": "GIF",
    ".ico": "ICO", ".ppm": "PPM", ".pdf": "PDF", ".avif": "AVIF",
}

# Formats without an alpha channel: RGBA must be flattened before saving.
NO_ALPHA = {"JPEG", "BMP", "PPM", "PDF"}


class ImageError(Exception):
    """An image could not be loaded, processed or saved."""


@dataclass
class ImageInfo:
    """Metadata about an image file."""

    path: Path
    width: int
    height: int
    mode: str
    format: str
    frames: int = 1
    file_size: int = 0
    exif: dict[str, Any] = field(default_factory=dict)

    @property
    def megapixels(self) -> float:
        return self.width * self.height / 1_000_000

    @property
    def is_animated(self) -> bool:
        return self.frames > 1


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def load(path: str | os.PathLike) -> Image.Image:
    """Open an image, applying EXIF orientation so it appears upright."""
    p = Path(path)
    try:
        img = Image.open(p)
        img.load()
    except FileNotFoundError as exc:
        raise ImageError(f"No such file: {p}") from exc
    except Image.DecompressionBombError as exc:
        raise ImageError(f"Image is too large to open safely: {exc}") from exc
    except (OSError, ValueError) as exc:
        raise ImageError(f"Cannot open {p.name}: {exc}") from exc
    try:
        return ImageOps.exif_transpose(img)
    except (OSError, ValueError, TypeError):
        return img          # broken EXIF must not prevent viewing


_EXIF_INTEREST = {
    271: "Camera make", 272: "Camera model", 274: "Orientation",
    306: "Date taken", 33434: "Exposure time", 33437: "F number",
    34855: "ISO", 37386: "Focal length", 36867: "Original date",
    41986: "Exposure mode", 42036: "Lens",
}


def info(path: str | os.PathLike) -> ImageInfo:
    """Read dimensions, format and a digest of EXIF without decoding pixels."""
    p = Path(path)
    try:
        with Image.open(p) as img:
            exif: dict[str, Any] = {}
            try:
                raw = img.getexif()
                for tag, label in _EXIF_INTEREST.items():
                    if tag in raw:
                        exif[label] = raw[tag]
            except (AttributeError, OSError, ValueError):
                pass
            return ImageInfo(
                path=p,
                width=img.width,
                height=img.height,
                mode=img.mode,
                format=img.format or "",
                frames=getattr(img, "n_frames", 1),
                file_size=p.stat().st_size,
                exif=exif,
            )
    except FileNotFoundError as exc:
        raise ImageError(f"No such file: {p}") from exc
    except (OSError, ValueError) as exc:
        raise ImageError(f"Cannot read {p.name}: {exc}") from exc


# --------------------------------------------------------------------------
# edit operations
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Op:
    """A single named edit with its keyword arguments."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        if not self.args:
            return self.name
        detail = ", ".join(f"{k}={v}" for k, v in self.args.items())
        return f"{self.name} ({detail})"


def _op_rotate(img: Image.Image, *, angle: float = 90,
               expand: bool = True) -> Image.Image:
    # Right angles use transpose: exact, lossless and much faster.
    exact = {90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180,
             270: Image.Transpose.ROTATE_270}
    if angle % 360 in exact:
        return img.transpose(exact[int(angle % 360)])
    return img.rotate(-angle, expand=expand, resample=Image.Resampling.BICUBIC)


def _op_flip(img: Image.Image, *, horizontal: bool = True) -> Image.Image:
    return img.transpose(Image.Transpose.FLIP_LEFT_RIGHT if horizontal
                         else Image.Transpose.FLIP_TOP_BOTTOM)


def _op_crop(img: Image.Image, *, box: tuple[int, int, int, int]) -> Image.Image:
    left, top, right, bottom = (int(v) for v in box)
    left, top = max(0, left), max(0, top)
    right, bottom = min(img.width, right), min(img.height, bottom)
    if right <= left or bottom <= top:
        raise ImageError("Crop area is empty.")
    return img.crop((left, top, right, bottom))


def _op_resize(img: Image.Image, *, width: int | None = None,
               height: int | None = None, keep_aspect: bool = True) -> Image.Image:
    if not width and not height:
        return img
    if keep_aspect:
        if width and not height:
            height = max(1, round(img.height * width / img.width))
        elif height and not width:
            width = max(1, round(img.width * height / img.height))
        else:
            scale = min(width / img.width, height / img.height)   # type: ignore[operator]
            width = max(1, round(img.width * scale))
            height = max(1, round(img.height * scale))
    final_w = int(width) if width else img.width
    final_h = int(height) if height else img.height
    return img.resize((final_w, final_h), Image.Resampling.LANCZOS)


def _op_scale(img: Image.Image, *, factor: float = 1.0) -> Image.Image:
    if factor <= 0:
        raise ImageError("Scale factor must be positive.")
    return img.resize((max(1, round(img.width * factor)),
                       max(1, round(img.height * factor))),
                      Image.Resampling.LANCZOS)


def _enhance(cls: type, img: Image.Image, value: float) -> Image.Image:
    return cls(img).enhance(value)


def _op_brightness(img, *, value: float = 1.0):
    return _enhance(ImageEnhance.Brightness, img, value)


def _op_contrast(img, *, value: float = 1.0):
    return _enhance(ImageEnhance.Contrast, img, value)


def _op_saturation(img, *, value: float = 1.0):
    return _enhance(ImageEnhance.Color, img, value)


def _op_sharpness(img, *, value: float = 1.0):
    return _enhance(ImageEnhance.Sharpness, img, value)


def _op_grayscale(img: Image.Image) -> Image.Image:
    has_alpha = img.mode in ("RGBA", "LA")
    out = ImageOps.grayscale(img.convert("RGB"))
    if has_alpha:
        out = out.convert("RGBA")
        out.putalpha(img.getchannel("A"))
    return out


def _op_invert(img: Image.Image) -> Image.Image:
    if img.mode == "RGBA":
        rgb, alpha = img.convert("RGB"), img.getchannel("A")
        out = ImageOps.invert(rgb).convert("RGBA")
        out.putalpha(alpha)
        return out
    return ImageOps.invert(img.convert("RGB"))


def _op_autocontrast(img: Image.Image, *, cutoff: float = 0) -> Image.Image:
    if img.mode == "RGBA":
        rgb, alpha = img.convert("RGB"), img.getchannel("A")
        out = ImageOps.autocontrast(rgb, cutoff=cutoff).convert("RGBA")
        out.putalpha(alpha)
        return out
    return ImageOps.autocontrast(img.convert("RGB"), cutoff=cutoff)


def _op_blur(img: Image.Image, *, radius: float = 2.0) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius))


def _op_sharpen(img: Image.Image) -> Image.Image:
    return img.filter(ImageFilter.SHARPEN)


def _op_border(img: Image.Image, *, width: int = 10,
               colour: str = "black") -> Image.Image:
    return ImageOps.expand(img, border=int(width), fill=colour)


def _op_thumbnail(img: Image.Image, *, size: int = 256) -> Image.Image:
    out = img.copy()
    out.thumbnail((size, size), Image.Resampling.LANCZOS)
    return out


OPS: dict[str, Callable[..., Image.Image]] = {
    "rotate": _op_rotate,
    "flip": _op_flip,
    "crop": _op_crop,
    "resize": _op_resize,
    "scale": _op_scale,
    "brightness": _op_brightness,
    "contrast": _op_contrast,
    "saturation": _op_saturation,
    "sharpness": _op_sharpness,
    "grayscale": _op_grayscale,
    "invert": _op_invert,
    "autocontrast": _op_autocontrast,
    "blur": _op_blur,
    "sharpen": _op_sharpen,
    "border": _op_border,
    "thumbnail": _op_thumbnail,
}


def apply_ops(img: Image.Image, ops: list[Op], *, ctx=None) -> Image.Image:
    """Apply *ops* in order, returning a new image.  The input is not modified."""
    out = img
    total = max(1, len(ops))
    for i, op in enumerate(ops):
        fn = OPS.get(op.name)
        if fn is None:
            raise ImageError(f"Unknown image operation: {op.name}")
        try:
            out = fn(out, **op.args)
        except ImageError:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise ImageError(f"{op.name} failed: {exc}") from exc
        if ctx is not None:
            ctx.progress(int((i + 1) / total * 100), f"Applied {op.name}")
    return out


# --------------------------------------------------------------------------
# saving and conversion
# --------------------------------------------------------------------------

def _prepare_for_format(img: Image.Image, fmt: str) -> Image.Image:
    """Convert colour mode so the image is writable in *fmt*."""
    if fmt in NO_ALPHA and img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    if fmt == "JPEG" and img.mode not in ("RGB", "L", "CMYK"):
        return img.convert("RGB")
    if fmt == "PNG" and img.mode == "CMYK":
        return img.convert("RGB")
    return img


def save(img: Image.Image, path: str | os.PathLike, *, quality: int = 92,
         optimise: bool = True, keep_exif: bool = True,
         source: Image.Image | None = None) -> Path:
    """Write *img* to *path*, choosing the format from the extension.

    The write is atomic: a temporary file next to the target is renamed into
    place, so an interrupted save cannot truncate an existing file.
    """
    p = Path(path)
    fmt = SAVE_FORMATS.get(p.suffix.lower())
    if fmt is None:
        raise ImageError(f"Cannot write '{p.suffix}' files.")

    out = _prepare_for_format(img, fmt)
    params: dict[str, Any] = {}
    if fmt in ("JPEG", "WEBP", "AVIF"):
        params["quality"] = int(quality)
    if fmt in ("JPEG", "PNG"):
        params["optimize"] = optimise
    if fmt == "JPEG":
        params["progressive"] = True
    if keep_exif:
        exif = (source or img).info.get("exif")
        if exif and fmt in ("JPEG", "WEBP", "TIFF"):
            params["exif"] = exif

    tmp = p.with_name(p.name + ".cachyview.tmp")
    try:
        out.save(tmp, fmt, **params)
        os.replace(tmp, p)
    except (OSError, ValueError, KeyError) as exc:
        tmp.unlink(missing_ok=True)
        raise ImageError(f"Could not save {p.name}: {exc}") from exc
    return p


def convert(src: str | os.PathLike, dest: str | os.PathLike, *,
            quality: int = 92, ops: list[Op] | None = None) -> Path:
    """Load *src*, optionally edit it, and write it out as *dest*."""
    img = load(src)
    if ops:
        img = apply_ops(img, ops)
    return save(img, dest, quality=quality, source=img)


def to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    """Encode an image to bytes (used to hand pixels to Qt without a temp file)."""
    buf = io.BytesIO()
    _prepare_for_format(img, fmt).save(buf, fmt)
    return buf.getvalue()


def batch_convert(sources: list[str | os.PathLike], dest_dir: str | os.PathLike,
                  suffix: str = ".png", *, quality: int = 92,
                  ops: list[Op] | None = None, ctx=None) -> list[Path]:
    """Convert many files, continuing past individual failures.

    Returns the paths successfully written.  Errors are reported through the
    job context so one broken file cannot abort the whole batch.
    """
    out_dir = Path(dest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    total = max(1, len(sources))

    for i, src in enumerate(sources):
        s = Path(src)
        try:
            target = out_dir / (s.stem + suffix)
            n = 2
            while target.exists() and target.resolve() != s.resolve():
                target = out_dir / f"{s.stem}-{n}{suffix}"
                n += 1
            written.append(convert(s, target, quality=quality, ops=ops))
        except ImageError as exc:
            if ctx is not None:
                ctx.progress(int((i + 1) / total * 100), f"Skipped {s.name}: {exc}")
            continue
        if ctx is not None:
            ctx.progress(int((i + 1) / total * 100), f"Converted {s.name}")
    return written


def images_to_pdf(sources: list[str | os.PathLike],
                  dest: str | os.PathLike, *, ctx=None) -> Path:
    """Combine images into a single PDF, one image per page.

    Uses img2pdf when available because it embeds JPEG data losslessly with no
    re-encoding; otherwise falls back to Pillow.
    """
    if not sources:
        raise ImageError("No images given.")
    out = Path(dest)
    try:
        import img2pdf
    except ImportError:
        img2pdf = None

    if img2pdf is not None:
        try:
            data = img2pdf.convert([str(s) for s in sources])
            if data:
                out.write_bytes(data)
                if ctx is not None:
                    ctx.progress(100, f"Wrote {out.name}")
                return out
        except Exception:
            pass        # e.g. alpha channels; fall through to Pillow

    pages = []
    for s in sources:
        im = load(s)
        pages.append(_prepare_for_format(im, "PDF"))
    if not pages:
        raise ImageError("No readable images.")
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:])
    if ctx is not None:
        ctx.progress(100, f"Wrote {out.name}")
    return out


# --------------------------------------------------------------------------
# optional external optimisers
# --------------------------------------------------------------------------

def optimise_file(path: str | os.PathLike) -> tuple[int, int]:
    """Losslessly shrink a PNG or JPEG in place if the right tool exists.

    Returns ``(before, after)`` byte sizes; equal values mean nothing happened.
    """
    import shutil
    p = Path(path)
    before = p.stat().st_size
    suffix = p.suffix.lower()

    cmd: list[str] | None = None
    if suffix == ".png" and shutil.which("oxipng"):
        cmd = ["oxipng", "-o", "4", "--strip", "safe", "-q", str(p)]
    elif suffix in (".jpg", ".jpeg") and shutil.which("jpegoptim"):
        cmd = ["jpegoptim", "--strip-all", "-q", str(p)]

    if cmd:
        try:
            subprocess.run(cmd, capture_output=True, timeout=120, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
    return before, p.stat().st_size
