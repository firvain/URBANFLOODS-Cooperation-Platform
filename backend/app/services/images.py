"""Image re-encoding and upload storage.

Every upload is decoded by Pillow and re-encoded to WebP: the declared content type is never
trusted (the format is sniffed by Pillow), polyglot payloads do not survive re-encoding, and all
metadata (EXIF incl. GPS, ICC, XMP) is dropped. Only JPEG (incl. phone MPO), PNG and WebP stills
are accepted.

Files live under ``UPLOAD_DIR`` at ``YYYY/MM/<uuid>.webp`` (+ ``_thumb.webp``); they are written
atomically (temp file + rename). ``process_image`` is CPU-bound and synchronous: call it from a
thread (``run_in_threadpool``).
"""

from __future__ import annotations

import io
import os
import tempfile
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import structlog
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
# "MPO" is the Multi Picture Object container phone cameras write for JPEGs (a second frame
# holds a depth map or preview); Pillow reports it instead of "JPEG". It is a still: the first
# frame is used and re-encoded like any JPEG.
ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "MPO"})
OUTPUT_MIME = "image/webp"
MAX_IMAGE_PIXELS = 40_000_000
MAIN_QUALITY = 82
THUMB_QUALITY = 75
WEBP_METHOD = 4

# Pillow warns above this and raises DecompressionBombError above twice it; anything above it
# is rejected explicitly in ``process_image``.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

INVALID_IMAGE = "uploads.invalid_image"
UNSUPPORTED_TYPE = "uploads.unsupported_type"
ANIMATED = "uploads.animated"
TOO_LARGE_PIXELS = "uploads.too_large_pixels"

log = structlog.get_logger(__name__)


class ImageError(Exception):
    """An upload that is not an acceptable image; ``code`` is the client-facing error code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ProcessedImage:
    main_bytes: bytes
    thumb_bytes: bytes
    width: int
    height: int
    mime: str = OUTPUT_MIME


def _open_checked(data: bytes) -> Image.Image:
    """Open, verify and reopen ``data``; reject wrong formats, bombs and animations."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            width, height = probe.size
            if fmt in ALLOWED_FORMATS and width * height <= MAX_IMAGE_PIXELS:
                probe.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageError(TOO_LARGE_PIXELS) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageError(INVALID_IMAGE) from exc
    if fmt not in ALLOWED_FORMATS:
        raise ImageError(UNSUPPORTED_TYPE)
    if width * height > MAX_IMAGE_PIXELS:
        raise ImageError(TOO_LARGE_PIXELS)

    # ``verify`` leaves the image unusable, so decode a fresh one.
    try:
        im = Image.open(io.BytesIO(data))
        if im.format == "MPO":
            im.seek(0)  # the main picture; the other frames are not an animation
        elif getattr(im, "n_frames", 1) > 1:
            raise ImageError(ANIMATED)
        im.load()
    except ImageError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageError(TOO_LARGE_PIXELS) from exc
    except (OSError, SyntaxError, ValueError) as exc:
        raise ImageError(INVALID_IMAGE) from exc
    return im


def _has_alpha(im: Image.Image) -> bool:
    return im.mode in {"RGBA", "LA", "PA"} or (
        im.mode in {"P", "L", "RGB"} and "transparency" in im.info
    )


def _encode_webp(im: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    # No ``exif``/``icc_profile``/``xmp`` arguments: the output carries no metadata.
    im.save(buf, "WEBP", quality=quality, method=WEBP_METHOD)
    return buf.getvalue()


def _bounded(im: Image.Image, max_px: int) -> Image.Image:
    """A copy whose longest edge is at most ``max_px`` (never upscaled)."""
    copy = im.copy()
    copy.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    return copy


def process_image(data: bytes, *, max_px: int, thumb_px: int) -> ProcessedImage:
    """Validate ``data`` and re-encode it as a metadata-free WebP plus a WebP thumbnail.

    Raises ``ImageError`` with ``uploads.invalid_image``, ``uploads.unsupported_type``,
    ``uploads.animated`` or ``uploads.too_large_pixels``.
    """
    im = _open_checked(data)
    try:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA" if _has_alpha(im) else "RGB")
        main = _bounded(im, max_px)
        thumb = _bounded(main, thumb_px)
        return ProcessedImage(
            main_bytes=_encode_webp(main, MAIN_QUALITY),
            thumb_bytes=_encode_webp(thumb, THUMB_QUALITY),
            width=main.width,
            height=main.height,
        )
    except (OSError, SyntaxError, ValueError) as exc:
        raise ImageError(INVALID_IMAGE) from exc


# --- storage ----------------------------------------------------------------------------------


def storage_relative_path(now: datetime, file_id: uuid.UUID) -> str:
    """``YYYY/MM/<uuid hex>.webp``, relative to ``UPLOAD_DIR``."""
    return f"{now:%Y/%m}/{file_id.hex}.webp"


def thumb_relative_path(rel_path: str) -> str:
    """The thumbnail next to ``rel_path``: ``.../<uuid hex>_thumb.webp``."""
    return rel_path.removesuffix(".webp") + "_thumb.webp"


def _resolve(upload_dir: str | os.PathLike[str], rel_path: str) -> Path:
    """``upload_dir / rel_path``, refusing anything that escapes ``upload_dir``."""
    root = Path(upload_dir).resolve()
    target = (root / rel_path).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError(f"Upload path escapes the upload directory: {rel_path!r}")
    return target


def _write_atomic(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, target)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def save_files(
    upload_dir: str | os.PathLike[str],
    rel_path: str,
    main_bytes: bytes,
    thumb_rel: str,
    thumb_bytes: bytes,
) -> None:
    """Write the main image and its thumbnail atomically, creating directories as needed. If
    the thumbnail cannot be written, the main image is removed again."""
    main_target = _resolve(upload_dir, rel_path)
    thumb_target = _resolve(upload_dir, thumb_rel)
    _write_atomic(main_target, main_bytes)
    try:
        _write_atomic(thumb_target, thumb_bytes)
    except BaseException:
        with suppress(FileNotFoundError):
            main_target.unlink()
        raise


def delete_files(upload_dir: str | os.PathLike[str], *rel_paths: str | None) -> None:
    """Remove the given files; missing files and ``None`` entries are ignored. Other errors are
    logged, never raised (deletion runs after the database change is committed)."""
    for rel_path in rel_paths:
        if not rel_path:
            continue
        try:
            _resolve(upload_dir, rel_path).unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            log.warning("uploads.delete_failed", path=rel_path, error=type(exc).__name__)
