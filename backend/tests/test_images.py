"""Increment 2f: ``app/services/images.py`` (pure; no database).

Test images are generated with Pillow in memory; nothing binary is committed.
"""

from __future__ import annotations

import io
import os
import uuid
from datetime import UTC, datetime

import pytest
from PIL import ExifTags, Image

from app.services import images
from app.services.images import (
    ALLOWED_MIME,
    ImageError,
    process_image,
    storage_relative_path,
    thumb_relative_path,
)

MAX_PX = 1920
THUMB_PX = 480


def _encode(im: Image.Image, fmt: str, **params) -> bytes:
    buf = io.BytesIO()
    im.save(buf, fmt, **params)
    return buf.getvalue()


def _process(data: bytes) -> images.ProcessedImage:
    return process_image(data, max_px=MAX_PX, thumb_px=THUMB_PX)


def _open(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    im.load()
    return im


def _error_code(data: bytes) -> str:
    with pytest.raises(ImageError) as excinfo:
        _process(data)
    return excinfo.value.code


# --- re-encoding ------------------------------------------------------------------------------


def _jpeg_with_orientation_and_gps() -> bytes:
    # Stored 40x20 (landscape) with a red block in the stored top-left corner. Orientation 6
    # means "rotate 90 degrees clockwise to display", so it displays as 20x40 with the red block
    # in the top-right corner.
    im = Image.new("RGB", (40, 20), (0, 0, 255))
    im.paste((255, 0, 0), (0, 0, 10, 10))
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    exif[ExifTags.Base.Make] = "Camera Maker"
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (40.0, 18.0, 0.0)
    gps[ExifTags.GPS.GPSLongitudeRef] = "E"
    gps[ExifTags.GPS.GPSLongitude] = (21.0, 47.0, 0.0)
    return _encode(im, "JPEG", exif=exif.tobytes(), quality=95)


def test_jpeg_is_rotated_by_exif_and_all_metadata_is_stripped():
    source = _jpeg_with_orientation_and_gps()
    source_exif = Image.open(io.BytesIO(source)).getexif()
    assert source_exif[ExifTags.Base.Orientation] == 6
    assert source_exif.get_ifd(ExifTags.IFD.GPSInfo)  # the fixture really carries GPS

    result = _process(source)

    assert result.mime == "image/webp"
    assert (result.width, result.height) == (20, 40)
    for data in (result.main_bytes, result.thumb_bytes):
        out = _open(data)
        assert out.format == "WEBP"
        assert out.size == (20, 40)
        assert len(out.getexif()) == 0
        assert "exif" not in out.info
        assert "icc_profile" not in out.info
        assert "xmp" not in out.info
        assert b"Camera Maker" not in data
    out = _open(result.main_bytes).convert("RGB")
    red, green, blue = out.getpixel((17, 2))  # displayed top-right
    assert red > 200 and blue < 80
    red, green, blue = out.getpixel((2, 2))  # displayed top-left is blue
    assert blue > 200 and red < 80


def test_png_with_alpha_keeps_alpha():
    im = Image.new("RGBA", (30, 30), (0, 128, 0, 255))
    im.paste((0, 0, 0, 0), (0, 0, 15, 30))

    result = _process(_encode(im, "PNG"))

    out = _open(result.main_bytes)
    assert out.format == "WEBP"
    assert out.mode == "RGBA"
    assert out.getpixel((2, 2))[3] == 0
    assert out.getpixel((25, 2))[3] == 255


def test_palette_png_with_transparency_keeps_alpha():
    im = Image.new("P", (16, 16), 1)
    im.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
    im.paste(0, (0, 0, 8, 16))

    result = _process(_encode(im, "PNG", transparency=0))

    out = _open(result.main_bytes)
    assert out.mode == "RGBA"
    assert out.getpixel((2, 2))[3] == 0
    assert out.getpixel((12, 2))[3] == 255


def test_cmyk_jpeg_is_converted_to_rgb():
    im = Image.new("CMYK", (12, 12), (0, 255, 255, 0))

    result = _process(_encode(im, "JPEG"))

    out = _open(result.main_bytes)
    assert out.mode == "RGB"
    red, green, blue = out.getpixel((6, 6))
    assert red > 200 and green < 80


def test_large_image_is_downscaled_and_thumbnailed():
    result = _process(_encode(Image.new("RGB", (4000, 3000), (10, 20, 30)), "PNG"))

    assert (result.width, result.height) == (1920, 1440)
    assert _open(result.main_bytes).size == (1920, 1440)
    assert _open(result.thumb_bytes).size == (480, 360)


def test_portrait_image_is_bounded_by_its_longest_edge():
    result = _process(_encode(Image.new("RGB", (1000, 4000)), "JPEG"))

    assert (result.width, result.height) == (480, 1920)
    assert _open(result.thumb_bytes).size == (120, 480)


def test_tiny_image_is_not_upscaled():
    result = _process(_encode(Image.new("RGB", (10, 10), (1, 2, 3)), "PNG"))

    assert (result.width, result.height) == (10, 10)
    assert _open(result.main_bytes).size == (10, 10)
    assert _open(result.thumb_bytes).size == (10, 10)


def test_webp_input_is_accepted():
    result = _process(_encode(Image.new("RGB", (50, 40)), "WEBP"))

    assert (result.width, result.height) == (50, 40)


# --- rejections -------------------------------------------------------------------------------


def test_gif_is_unsupported_whatever_the_declared_type():
    assert _error_code(_encode(Image.new("RGB", (10, 10)), "GIF")) == "uploads.unsupported_type"


@pytest.mark.parametrize("fmt", ["BMP", "TIFF", "ICO"])
def test_other_formats_are_unsupported(fmt):
    assert _error_code(_encode(Image.new("RGB", (16, 16)), fmt)) == "uploads.unsupported_type"


def test_mpo_phone_jpeg_is_accepted_as_jpeg_using_its_first_frame():
    """Phone cameras write JPEGs with a second embedded frame (MPO, Multi Picture Object);
    Pillow reports the format as "MPO", not "JPEG". They are stills and must be accepted."""
    frames = [Image.new("RGB", (40, 30), color) for color in ((200, 20, 20), (20, 200, 20))]
    data = _encode(frames[0], "MPO", save_all=True, append_images=frames[1:])
    assert Image.open(io.BytesIO(data)).format == "MPO"

    result = _process(data)
    assert (result.width, result.height) == (40, 30)
    assert result.mime == "image/webp"
    # The first (main) frame is used: red, not the green second frame.
    r, g, b = Image.open(io.BytesIO(result.main_bytes)).convert("RGB").getpixel((5, 5))
    assert r > 150 and g < 100 and b < 100


def test_animated_webp_is_rejected():
    frames = [Image.new("RGB", (10, 10), color) for color in ((255, 0, 0), (0, 255, 0))]
    data = _encode(frames[0], "WEBP", save_all=True, append_images=frames[1:], duration=100)
    assert Image.open(io.BytesIO(data)).n_frames == 2

    assert _error_code(data) == "uploads.animated"


def test_animated_png_is_rejected():
    frames = [Image.new("RGB", (10, 10), color) for color in ((255, 0, 0), (0, 255, 0))]
    data = _encode(frames[0], "PNG", save_all=True, append_images=frames[1:], duration=100)

    assert _error_code(data) == "uploads.animated"


def test_random_bytes_are_an_invalid_image():
    assert _error_code(os.urandom(2048)) == "uploads.invalid_image"


def test_empty_bytes_are_an_invalid_image():
    assert _error_code(b"") == "uploads.invalid_image"


def test_truncated_png_is_an_invalid_image():
    data = _encode(Image.effect_noise((200, 200), 64).convert("RGB"), "PNG")

    assert _error_code(data[: len(data) // 2]) == "uploads.invalid_image"


def test_decompression_bomb_is_rejected():
    # 81 Mpx: over twice the limit, so Pillow itself refuses to open it.
    data = _encode(Image.new("1", (9000, 9000)), "PNG")

    assert _error_code(data) == "uploads.too_large_pixels"


@pytest.mark.parametrize(
    "warning_filter",
    [
        pytest.param(
            "ignore", marks=pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
        ),
        pytest.param(
            "error", marks=pytest.mark.filterwarnings("error::PIL.Image.DecompressionBombWarning")
        ),
    ],
)
def test_image_just_over_the_pixel_limit_is_rejected(warning_filter):
    # 42 Mpx: over the limit but under twice it (Pillow only warns there), whether the warning
    # is ignored or raised.
    data = _encode(Image.new("1", (7000, 6000)), "PNG")

    assert _error_code(data) == "uploads.too_large_pixels"


def test_pixel_limit_is_forty_megapixels():
    assert Image.MAX_IMAGE_PIXELS == 40_000_000
    assert images.MAX_IMAGE_PIXELS == 40_000_000


def test_allowed_mime_types():
    assert ALLOWED_MIME == {"image/jpeg", "image/png", "image/webp"}


def test_image_error_carries_its_code():
    error = ImageError("uploads.animated")

    assert error.code == "uploads.animated"
    assert str(error) == "uploads.animated"


# --- storage paths and files ------------------------------------------------------------------


def test_storage_relative_path_format():
    file_id = uuid.UUID("12345678123456781234567812345678")
    now = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)

    rel = storage_relative_path(now, file_id)

    assert rel == "2026/03/12345678123456781234567812345678.webp"
    assert thumb_relative_path(rel) == "2026/03/12345678123456781234567812345678_thumb.webp"


def test_save_files_creates_directories_and_writes_both_files(tmp_path):
    images.save_files(tmp_path, "2026/03/a.webp", b"main", "2026/03/a_thumb.webp", b"thumb")

    assert (tmp_path / "2026/03/a.webp").read_bytes() == b"main"
    assert (tmp_path / "2026/03/a_thumb.webp").read_bytes() == b"thumb"
    # No temp files are left behind.
    assert sorted(p.name for p in (tmp_path / "2026/03").iterdir()) == ["a.webp", "a_thumb.webp"]


def test_save_files_refuses_paths_outside_the_upload_dir(tmp_path):
    with pytest.raises(ValueError):
        images.save_files(tmp_path / "up", "../escape.webp", b"x", "t.webp", b"y")
    assert not (tmp_path / "escape.webp").exists()


def test_delete_files_removes_files_and_ignores_missing_ones(tmp_path):
    images.save_files(tmp_path, "2026/03/b.webp", b"main", "2026/03/b_thumb.webp", b"thumb")

    images.delete_files(tmp_path, "2026/03/b.webp", "2026/03/b_thumb.webp", None, "nope.webp")

    assert not (tmp_path / "2026/03/b.webp").exists()
    assert not (tmp_path / "2026/03/b_thumb.webp").exists()
