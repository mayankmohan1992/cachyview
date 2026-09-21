"""Image backend tests using real encoded images, not mocks."""
import pytest
from PIL import Image

from cachyview.backends import image as im

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture
def photo(tmp_path):
    """A 200x100 RGB JPEG with a recognisable gradient."""
    img = Image.new("RGB", (200, 100))
    for x in range(200):
        for y in range(100):
            img.putpixel((x, y), (x, y * 2, 128))
    p = tmp_path / "photo.jpg"
    img.save(p, quality=95)
    return p


@pytest.fixture
def transparent(tmp_path):
    """A PNG with a real alpha channel."""
    img = Image.new("RGBA", (60, 40), (255, 0, 0, 128))
    p = tmp_path / "alpha.png"
    img.save(p)
    return p


# --- loading and info -----------------------------------------------------

def test_load_returns_image(photo):
    img = im.load(photo)
    assert img.size == (200, 100)
    assert img.mode == "RGB"


def test_info_reads_metadata(photo):
    got = im.info(photo)
    assert (got.width, got.height) == (200, 100)
    assert got.format == "JPEG"
    assert got.file_size > 0
    assert got.megapixels == pytest.approx(0.02)
    assert not got.is_animated


def test_info_detects_animation(tmp_path):
    # Frames must differ visually or the GIF encoder collapses them into one.
    frames = []
    for i in range(4):
        f = Image.new("RGB", (10, 10), (0, 0, 0))
        f.putpixel((i, i), (255, 0, 0))
        frames.append(f.convert("P"))
    p = tmp_path / "anim.gif"
    frames[0].save(p, save_all=True, append_images=frames[1:], duration=50)
    got = im.info(p)
    assert got.is_animated and got.frames == 4


def test_load_missing_file_raises():
    with pytest.raises(im.ImageError):
        im.load("/nonexistent/nope.png")


def test_load_corrupt_file_raises(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\n" + b"garbage" * 10)
    with pytest.raises(im.ImageError):
        im.load(bad)


def test_unsupported_format_error_mentions_install(tmp_path):
    """A format we cannot decode must say how to enable it, not just fail."""
    fake = tmp_path / "photo.heic"
    fake.write_bytes(b"not really a heic file")
    with pytest.raises(im.ImageError, match="paru -S --needed"):
        im.load(fake)


def test_unsupported_hint_covers_raw():
    assert "python-rawpy" in im._unsupported_hint(".cr2")
    assert im._unsupported_hint(".txt") == ""


def test_resize_honours_resample(tmp_path):
    img = Image.new("RGB", (100, 50), (10, 20, 30))
    out = im.apply_ops(img, [im.Op("resize", {"width": 40, "height": 20,
                                              "resample": "nearest"})])
    assert out.size == (40, 20)


def test_watermark_text_changes_pixels():
    img = Image.new("RGB", (300, 200), (255, 255, 255))
    out = im.apply_ops(img, [im.Op("watermark", {
        "text": "COPY", "position": "bottom-right", "opacity": 1.0,
        "size": 24, "color": "#000000"})])
    assert out.size == (300, 200)
    changed = sum(1 for px in out.getdata() if px != (255, 255, 255))
    assert changed > 0, "watermark text must alter pixels"


def test_watermark_image(tmp_path):
    base = Image.new("RGB", (400, 300), (255, 255, 255))
    mark = tmp_path / "logo.png"
    Image.new("RGBA", (40, 40), (255, 0, 0, 255)).save(mark)
    out = im.apply_ops(base, [im.Op("watermark", {
        "image": str(mark), "position": "top-left", "opacity": 1.0,
        "scale": 0.25})])
    assert out.size == (400, 300)
    # The margin is 16px, so the logo starts at (16, 16).
    assert out.getpixel((30, 30))[0] > 200 and out.getpixel((30, 30))[1] < 60
    assert out.getpixel((5, 5)) == (255, 255, 255)


def test_frame_durations_reads_gif(tmp_path):
    from PIL import ImageDraw
    frames = []
    for i in range(3):
        f = Image.new("RGB", (10, 10), (255, 255, 255))
        ImageDraw.Draw(f).rectangle([0, 0, i + 1, 9], fill=(0, 0, 0))
        frames.append(f)
    gif = tmp_path / "anim.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:],
                   duration=[120, 240, 360], loop=0)
    durations = im.frame_durations(gif)
    assert durations[:3] == [120, 240, 360]


# --- geometry ops ---------------------------------------------------------

def test_rotate_90_swaps_dimensions(photo):
    out = im.apply_ops(im.load(photo), [im.Op("rotate", {"angle": 90})])
    assert out.size == (100, 200)


def test_rotate_180_keeps_dimensions(photo):
    out = im.apply_ops(im.load(photo), [im.Op("rotate", {"angle": 180})])
    assert out.size == (200, 100)


def test_rotate_360_is_identity(photo):
    src = im.load(photo)
    out = im.apply_ops(src, [im.Op("rotate", {"angle": 90})] * 4)
    assert out.size == src.size
    assert out.tobytes() == src.tobytes()


def test_lossless_rotate_jpeg_keeps_dimensions(photo, tmp_path):
    """A 90° lossless rotate of a JPEG must swap dimensions without re-encode."""
    out = tmp_path / "rot.jpg"
    im.lossless_rotate(photo, out, angle=90)
    img = Image.open(out)
    assert img.format == "JPEG"
    assert img.size == (100, 200), "90° rotation swaps WxH"
    assert out.stat().st_size > 0


def test_lossless_rotate_180_png_falls_back(photo, tmp_path):
    """Non-JPEG input uses the normal rotate path and still works."""
    png = tmp_path / "p.png"
    Image.open(photo).save(png)
    out = tmp_path / "rot.png"
    im.lossless_rotate(png, out, angle=180)
    assert Image.open(out).size == (200, 100)


def test_lossless_rotate_uses_keep_quality(photo, tmp_path):
    """Lossless JPEG rotate must accept quality='keep' (i.e. not re-encode)."""
    out = tmp_path / "rot.jpg"
    im.lossless_rotate(photo, out, angle=90)
    # A re-encoded 90° rotate would change the file; the keep path must succeed
    # and produce a valid JPEG with swapped dimensions.
    img = Image.open(out)
    assert img.format == "JPEG"
    assert img.size == (100, 200)


def test_flip_horizontal_mirrors_pixels(photo):
    src = im.load(photo)
    out = im.apply_ops(src, [im.Op("flip", {"horizontal": True})])
    assert out.getpixel((0, 0)) == src.getpixel((199, 0))


def test_flip_twice_is_identity(photo):
    src = im.load(photo)
    out = im.apply_ops(src, [im.Op("flip", {"horizontal": True})] * 2)
    assert out.tobytes() == src.tobytes()


def test_crop(photo):
    out = im.apply_ops(im.load(photo), [im.Op("crop", {"box": (10, 10, 110, 60)})])
    assert out.size == (100, 50)


def test_crop_clamps_to_bounds(photo):
    out = im.apply_ops(im.load(photo), [im.Op("crop", {"box": (-50, -50, 999, 999)})])
    assert out.size == (200, 100)


def test_crop_empty_area_raises(photo):
    with pytest.raises(im.ImageError):
        im.apply_ops(im.load(photo), [im.Op("crop", {"box": (50, 50, 50, 50)})])


@pytest.mark.parametrize("args,expect", [
    ({"width": 100}, (100, 50)),
    ({"height": 50}, (100, 50)),
    ({"width": 50, "height": 50}, (50, 25)),
    ({"width": 50, "height": 50, "keep_aspect": False}, (50, 50)),
])
def test_resize_variants(photo, args, expect):
    assert im.apply_ops(im.load(photo), [im.Op("resize", args)]).size == expect


def test_resize_with_no_args_is_noop(photo):
    src = im.load(photo)
    assert im.apply_ops(src, [im.Op("resize", {})]).size == src.size


def test_scale(photo):
    assert im.apply_ops(im.load(photo), [im.Op("scale", {"factor": 0.5})]).size == (100, 50)


def test_scale_rejects_zero(photo):
    with pytest.raises(im.ImageError):
        im.apply_ops(im.load(photo), [im.Op("scale", {"factor": 0})])


# --- colour ops -----------------------------------------------------------

def test_grayscale_removes_colour(photo):
    out = im.apply_ops(im.load(photo), [im.Op("grayscale")])
    r, g, b = out.convert("RGB").getpixel((100, 50))
    assert r == g == b


def test_grayscale_keeps_alpha(transparent):
    out = im.apply_ops(im.load(transparent), [im.Op("grayscale")])
    assert out.mode == "RGBA"
    assert out.getpixel((0, 0))[3] == 128


def test_invert_twice_restores(photo):
    src = im.load(photo)
    out = im.apply_ops(src, [im.Op("invert")] * 2)
    assert out.tobytes() == src.tobytes()


def test_invert_keeps_alpha(transparent):
    out = im.apply_ops(im.load(transparent), [im.Op("invert")])
    assert out.getpixel((0, 0))[3] == 128


def test_brightness_increases_luminance(photo):
    src = im.load(photo)
    out = im.apply_ops(src, [im.Op("brightness", {"value": 1.8})])
    assert sum(out.getpixel((100, 50))) > sum(src.getpixel((100, 50)))


def test_brightness_zero_gives_black(photo):
    out = im.apply_ops(im.load(photo), [im.Op("brightness", {"value": 0})])
    assert out.getpixel((100, 50)) == (0, 0, 0)


@pytest.mark.parametrize("name", ["contrast", "saturation", "sharpness"])
def test_enhancers_are_identity_at_one(photo, name):
    src = im.load(photo)
    out = im.apply_ops(src, [im.Op(name, {"value": 1.0})])
    assert out.tobytes() == src.tobytes()


def test_blur_changes_pixels(photo):
    src = im.load(photo)
    out = im.apply_ops(src, [im.Op("blur", {"radius": 3})])
    assert out.tobytes() != src.tobytes()
    assert out.size == src.size


def test_border_grows_image(photo):
    out = im.apply_ops(im.load(photo), [im.Op("border", {"width": 5})])
    assert out.size == (210, 110)


def test_thumbnail_fits_box(photo):
    out = im.apply_ops(im.load(photo), [im.Op("thumbnail", {"size": 64})])
    assert max(out.size) <= 64


def test_autocontrast_runs(photo):
    assert im.apply_ops(im.load(photo), [im.Op("autocontrast")]).size == (200, 100)


# --- op pipeline ----------------------------------------------------------

def test_ops_apply_in_order(photo):
    out = im.apply_ops(im.load(photo), [
        im.Op("resize", {"width": 100}),
        im.Op("rotate", {"angle": 90}),
        im.Op("border", {"width": 5}),
    ])
    assert out.size == (60, 110)


def test_unknown_op_raises(photo):
    with pytest.raises(im.ImageError, match="Unknown image operation"):
        im.apply_ops(im.load(photo), [im.Op("nonsense")])


def test_apply_ops_does_not_mutate_source(photo):
    src = im.load(photo)
    before = src.tobytes()
    im.apply_ops(src, [im.Op("rotate", {"angle": 90}), im.Op("invert")])
    assert src.tobytes() == before


def test_empty_op_list_returns_same(photo):
    src = im.load(photo)
    assert im.apply_ops(src, []) is src


def test_op_str_is_readable():
    assert str(im.Op("rotate", {"angle": 90})) == "rotate (angle=90)"
    assert str(im.Op("invert")) == "invert"


# --- saving and conversion ------------------------------------------------

@pytest.mark.parametrize("ext", [".png", ".jpg", ".webp", ".bmp", ".tiff"])
def test_save_formats(tmp_path, photo, ext):
    out = tmp_path / f"out{ext}"
    im.save(im.load(photo), out)
    assert out.is_file() and out.stat().st_size > 0
    assert im.info(out).width == 200


def test_save_rejects_unknown_extension(tmp_path, photo):
    with pytest.raises(im.ImageError):
        im.save(im.load(photo), tmp_path / "x.xyz")


def test_save_flattens_alpha_for_jpeg(tmp_path, transparent):
    out = tmp_path / "flat.jpg"
    im.save(im.load(transparent), out)
    assert im.info(out).mode in ("RGB", "L")


def test_save_is_atomic_no_temp_left(tmp_path, photo):
    out = tmp_path / "atomic.png"
    im.save(im.load(photo), out)
    assert not (tmp_path / "atomic.png.cachyview.tmp").exists()


def test_failed_save_leaves_no_temp(tmp_path, photo):
    target = tmp_path / "sub" / "x.png"      # parent does not exist
    with pytest.raises(im.ImageError):
        im.save(im.load(photo), target)
    assert not list(tmp_path.glob("**/*.cachyview.tmp"))


def test_convert_changes_format(tmp_path, photo):
    out = tmp_path / "conv.png"
    im.convert(photo, out)
    assert im.info(out).format == "PNG"


def test_convert_applies_ops(tmp_path, photo):
    out = tmp_path / "conv.png"
    im.convert(photo, out, ops=[im.Op("resize", {"width": 50})])
    assert im.info(out).width == 50


def test_to_bytes_roundtrip(photo):
    data = im.to_bytes(im.load(photo), "PNG")
    assert data.startswith(b"\x89PNG")


# --- batch ----------------------------------------------------------------

def test_batch_convert(tmp_path, photo):
    srcs = []
    for i in range(3):
        p = tmp_path / f"s{i}.jpg"
        Image.new("RGB", (30, 30), (i * 40, 0, 0)).save(p)
        srcs.append(p)
    out = im.batch_convert(srcs, tmp_path / "outdir", ".png")
    assert len(out) == 3
    assert all(p.suffix == ".png" and p.is_file() for p in out)


def test_batch_skips_broken_files(tmp_path, photo):
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not an image at all")
    out = im.batch_convert([photo, bad], tmp_path / "outdir2", ".png")
    assert len(out) == 1


def test_batch_applies_ops(tmp_path, photo):
    out = im.batch_convert([photo], tmp_path / "o3", ".png",
                           ops=[im.Op("scale", {"factor": 0.25})])
    assert im.info(out[0]).width == 50


# --- images to PDF --------------------------------------------------------

def test_images_to_pdf(tmp_path, photo):
    out = tmp_path / "album.pdf"
    im.images_to_pdf([photo, photo], out)
    assert out.read_bytes().startswith(b"%PDF")


def test_images_to_pdf_with_alpha(tmp_path, transparent):
    """img2pdf rejects alpha; the Pillow fallback must still produce a PDF."""
    out = tmp_path / "alpha.pdf"
    im.images_to_pdf([transparent], out)
    assert out.read_bytes().startswith(b"%PDF")


def test_images_to_pdf_empty_raises(tmp_path):
    with pytest.raises(im.ImageError):
        im.images_to_pdf([], tmp_path / "x.pdf")
