import io

from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass


def load_image(data: bytes) -> Image.Image:
    """Open any Pillow-supported format, apply EXIF rotation, flatten to RGB."""
    img = Image.open(io.BytesIO(data))
    img.seek(0)
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def downscale(img: Image.Image, max_side: int = 1024) -> Image.Image:
    img = img.copy()
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    return img


def to_jpeg_bytes(img: Image.Image, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def smart_crop(img: Image.Image, size: tuple[int, int], focal=(0.5, 0.4)) -> Image.Image:
    """Cover-fit `img` into `size`, keeping the focal point (0-1 fractions) in frame."""
    tw, th = size
    fx = min(max(float(focal[0]), 0.0), 1.0)
    fy = min(max(float(focal[1]), 0.0), 1.0)

    scale = max(tw / img.width, th / img.height)
    nw, nh = max(tw, round(img.width * scale)), max(th, round(img.height * scale))
    resized = img.resize((nw, nh), Image.LANCZOS)

    left = min(max(round(fx * nw - tw / 2), 0), nw - tw)
    top = min(max(round(fy * nh - th / 2), 0), nh - th)
    return resized.crop((left, top, left + tw, top + th))
