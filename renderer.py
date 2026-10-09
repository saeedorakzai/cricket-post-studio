import colorsys
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, features

import config
from imaging import smart_crop
from planner import Slide

W, H = config.CANVAS_W, config.CANVAS_H
PAD = 72
WHITE = (255, 255, 255)

_RTL_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
HAS_RAQM = features.check("raqm")


# ---------- colour helpers ----------

def hex_to_rgb(h: str, default=(0, 200, 83)) -> tuple[int, int, int]:
    h = (h or "").lstrip("#")
    if len(h) != 6:
        return default
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return default


def _luminance(c) -> float:
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255


def readable_on_dark(c) -> tuple[int, int, int]:
    """Lighten an accent until it reads well on a dark background."""
    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in c))
    if s <= 0.1:
        return (235, 235, 235) if l < 0.8 else tuple(c)
    s = max(s, 0.55)
    while l < 0.95 and _luminance([v * 255 for v in colorsys.hls_to_rgb(h, l, s)]) < 0.42:
        l += 0.03
    return tuple(int(v * 255) for v in colorsys.hls_to_rgb(h, l, s))


def text_on(c) -> tuple[int, int, int]:
    return (15, 15, 15) if _luminance(c) > 0.6 else WHITE


# ---------- font / text helpers ----------

def is_rtl(text: str) -> bool:
    return bool(_RTL_RE.search(text or ""))


@lru_cache(maxsize=256)
def get_font(path: str, size: int, weight: str | None = None) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM if HAS_RAQM else ImageFont.Layout.BASIC)
    if weight:
        try:
            font.set_variation_by_name(weight)
        except (OSError, ValueError):
            pass
    return font


def headline_font(text: str, size: int):
    if is_rtl(text):
        return get_font(str(config.FONT_URDU), int(size * 0.7), "Bold")
    return get_font(str(config.FONT_HEADLINE), size)


def body_font(text: str, size: int, weight: str = "SemiBold"):
    if is_rtl(text):
        return get_font(str(config.FONT_URDU), size, "Regular")
    return get_font(str(config.FONT_BODY), size, weight)


def _text_dir(text: str):
    return "rtl" if is_rtl(text) and HAS_RAQM else None


def _width(font, text: str) -> float:
    d = _text_dir(text)
    return font.getlength(text, direction=d) if d else font.getlength(text)


def wrap(text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in (text or "").split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if cur and _width(font, trial) > max_w:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        if cur:
            lines.append(cur)
    return lines


def fit_text(text: str, font_fn, max_w: int, max_h: int, start: int, minimum: int, spacing: float = 1.1):
    """Largest font size whose wrapped text fits the box. Returns (font, lines, line_height)."""
    size = start
    while True:
        font = font_fn(text, size)
        line_h = int(font.size * spacing) if not is_rtl(text) else int(font.size * 1.9)
        lines = wrap(text, font, max_w)
        widest = max((_width(font, ln) for ln in lines), default=0)
        if (len(lines) * line_h <= max_h and widest <= max_w) or size <= minimum:
            return font, lines, line_h
        size -= 4


def draw_lines(canvas: Image.Image, lines, font, line_h, x, y, fill=WHITE, align="left",
               box_w: int | None = None, shadow=True) -> int:
    """Draw wrapped lines with an optional soft shadow. Returns y after the last line."""
    rtl = any(is_rtl(ln) for ln in lines)
    if rtl and align == "left":
        align = "right"
    box_w = box_w or (W - 2 * x)

    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d, sd = ImageDraw.Draw(layer), ImageDraw.Draw(shadow_layer)
    cy = y
    for ln in lines:
        lw = _width(font, ln)
        lx = x if align == "left" else x + (box_w - lw) / 2 if align == "center" else x + box_w - lw
        kw = {"direction": _text_dir(ln)} if _text_dir(ln) else {}
        if shadow:
            sd.text((lx + 3, cy + 5), ln, font=font, fill=(0, 0, 0, 170), **kw)
        d.text((lx, cy), ln, font=font, fill=fill, **kw)
        cy += line_h
    if shadow:
        canvas.alpha_composite(shadow_layer.filter(ImageFilter.GaussianBlur(8)))
    canvas.alpha_composite(layer)
    return cy


# ---------- layer helpers ----------

def vertical_gradient(size, start_frac: float, max_alpha: int = 235, color=(0, 0, 0)) -> Image.Image:
    w, h = size
    grad = Image.new("L", (1, h), 0)
    start = int(h * start_frac)
    for yy in range(start, h):
        t = (yy - start) / max(1, h - start)
        grad.putpixel((0, yy), int(max_alpha * (t ** 0.8)))
    alpha = grad.resize((w, h))
    layer = Image.new("RGBA", (w, h), color + (0,))
    layer.putalpha(alpha)
    return layer


def top_shade(size, height: int = 260, alpha: int = 140) -> Image.Image:
    w, h = size
    grad = Image.new("L", (1, h), 0)
    for yy in range(min(height, h)):
        grad.putpixel((0, yy), int(alpha * (1 - yy / height)))
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    layer.putalpha(grad.resize((w, h)))
    return layer


def photo_bg(img: Image.Image | None, size=(W, H), focal=(0.5, 0.4)) -> Image.Image:
    if img is None:
        return Image.new("RGBA", size, (18, 18, 22, 255))
    return smart_crop(img, size, focal).convert("RGBA")


def pill(canvas: Image.Image, xy, text: str, bg, font, pad=(22, 10)) -> tuple[int, int, int, int]:
    d = ImageDraw.Draw(canvas)
    tw = _width(font, text)
    asc, desc = font.getmetrics()
    x, y = xy
    box = (x, y, int(x + tw + pad[0] * 2), int(y + asc + desc + pad[1] * 2))
    d.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=bg)
    d.text((x + pad[0], y + pad[1]), text, font=font, fill=text_on(bg))
    return box


def circle_photo(img: Image.Image, diameter: int, ring_color, ring: int = 8, focal=(0.5, 0.35)) -> Image.Image:
    photo = smart_crop(img, (diameter, diameter), focal).convert("RGBA")
    mask = Image.new("L", (diameter * 4, diameter * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter * 4 - 1, diameter * 4 - 1), fill=255)
    photo.putalpha(mask.resize((diameter, diameter), Image.LANCZOS))
    out_d = diameter + ring * 2
    out = Image.new("RGBA", (out_d, out_d), (0, 0, 0, 0))
    ImageDraw.Draw(out).ellipse((0, 0, out_d - 1, out_d - 1), fill=ring_color)
    out.alpha_composite(photo, (ring, ring))
    return out


@lru_cache(maxsize=4)
def _load_logo(path: str) -> Image.Image | None:
    p = Path(path)
    if not path or not p.is_file():
        return None
    try:
        return Image.open(p).convert("RGBA")
    except OSError:
        return None


def branding(canvas: Image.Image, handle: str, logo: Image.Image | None, index: int, total: int):
    d = ImageDraw.Draw(canvas)
    f = body_font("", 26, "SemiBold")
    if handle:
        d.text((PAD, H - 58), handle, font=f, fill=(255, 255, 255, 220))
    if total > 1:
        counter = f"{index + 1:02d}/{total:02d}"
        cw = _width(f, counter)
        d.text((W - PAD - cw, H - 58), counter, font=f, fill=(255, 255, 255, 200))
    if logo is not None:
        lg = logo.copy()
        lg.thumbnail((110, 110), Image.LANCZOS)
        canvas.alpha_composite(lg, (W - PAD - lg.width, 48))


# ---------- templates ----------

def _headline(s: Slide) -> str:
    return s.headline if is_rtl(s.headline) else s.headline.upper()


def render_cover(s: Slide, imgs, accent) -> Image.Image:
    c = photo_bg(imgs[0], focal=(s.focal_x, s.focal_y))
    c.alpha_composite(top_shade(c.size))
    c.alpha_composite(vertical_gradient(c.size, 0.35, 245))
    acc = readable_on_dark(accent)
    max_w = W - 2 * PAD

    sub_font, sub_lines, sub_h = fit_text(s.subtext, lambda t, z: body_font(t, z, "SemiBold"),
                                          max_w, 150, 38, 26, 1.3) if s.subtext else (None, [], 0)
    sub_block = len(sub_lines) * sub_h
    head_font, head_lines, head_h = fit_text(_headline(s), headline_font, max_w, 470, 190, 80, 0.95)
    head_block = len(head_lines) * head_h

    bottom = H - 150
    y = bottom - sub_block - (30 if sub_lines else 0) - head_block
    bar_x = W - PAD - 120 if is_rtl(s.headline) else PAD
    ImageDraw.Draw(c).rectangle((bar_x, y - 34, bar_x + 120, y - 22), fill=acc)
    y = draw_lines(c, head_lines, head_font, head_h, PAD, y)
    if sub_lines:
        draw_lines(c, sub_lines, sub_font, sub_h, PAD, y + 30, fill=(235, 235, 235, 255))

    swipe_font = body_font("", 26, "Bold")
    tw = _width(swipe_font, "SWIPE  >>")
    pill(c, (int(W - PAD - tw - 44), 58), "SWIPE  >>", accent, swipe_font)
    return c


def render_hero(s: Slide, imgs, accent) -> Image.Image:
    c = photo_bg(imgs[0], focal=(s.focal_x, s.focal_y))
    c.alpha_composite(vertical_gradient(c.size, 0.45, 240))
    acc = readable_on_dark(accent)
    max_w = W - 2 * PAD

    sub_font, sub_lines, sub_h = fit_text(s.subtext, lambda t, z: body_font(t, z, "Medium"),
                                          max_w, 170, 36, 24, 1.35) if s.subtext else (None, [], 0)
    head_font, head_lines, head_h = fit_text(_headline(s), headline_font, max_w, 330, 140, 70, 0.95)

    bottom = H - 140
    y = bottom - len(sub_lines) * sub_h - (36 if sub_lines else 0) - len(head_lines) * head_h
    y = draw_lines(c, head_lines, head_font, head_h, PAD, y)
    if sub_lines:
        d = ImageDraw.Draw(c)
        rtl = is_rtl(s.subtext)
        gap = 40 if rtl else 18
        bar_x = W - PAD - 8 if rtl else PAD
        d.rectangle((bar_x, y + gap - 10, bar_x + 8, y + gap + len(sub_lines) * sub_h), fill=acc)
        draw_lines(c, sub_lines, sub_font, sub_h, PAD if rtl else PAD + 32, y + gap,
                   fill=(235, 235, 235, 255), box_w=max_w - 48 if rtl else max_w - 32)
    return c


def render_stat(s: Slide, imgs, accent) -> Image.Image:
    base = photo_bg(imgs[0], focal=(s.focal_x, s.focal_y)).convert("RGB")
    base = ImageEnhance.Brightness(base.filter(ImageFilter.GaussianBlur(18))).enhance(0.45)
    c = base.convert("RGBA")
    tint = Image.new("RGBA", c.size, accent + (70,))
    c.alpha_composite(tint)
    acc = readable_on_dark(accent)
    max_w = W - 2 * PAD

    if imgs[0] is not None:
        ph = circle_photo(imgs[0], 240, acc, 8, (s.focal_x, s.focal_y))
        c.alpha_composite(ph, ((W - ph.width) // 2, 170))

    value = s.stat_value or s.headline or "-"
    vf, vlines, vh = fit_text(value.upper(), headline_font, max_w, 360, 360, 120, 0.9)
    y = 470 + max(0, (360 - len(vlines) * vh) // 2)
    y = draw_lines(c, vlines, vf, vh, PAD, y, fill=WHITE, align="center")

    d = ImageDraw.Draw(c)
    d.rectangle(((W - 140) // 2, y + 20, (W + 140) // 2, y + 32), fill=acc)

    label = (s.stat_label or s.subtext or "").upper() if not is_rtl(s.stat_label) else s.stat_label
    if label:
        lf, llines, lh = fit_text(label, lambda t, z: body_font(t, z, "Bold"), max_w, 200, 50, 28, 1.25)
        y = draw_lines(c, llines, lf, lh, PAD, y + 70, align="center")
    if s.stat_label and s.subtext:
        hf, hlines, hh = fit_text(s.subtext, lambda t, z: body_font(t, z, "Medium"), max_w, 120, 32, 22, 1.3)
        draw_lines(c, hlines, hf, hh, PAD, y + 24, fill=(220, 220, 220, 255), align="center")
    return c


def render_quote(s: Slide, imgs, accent) -> Image.Image:
    bg_col = tuple(int(10 + v * 0.12) for v in accent)
    c = Image.new("RGBA", (W, H), bg_col + (255,))
    if imgs[0] is not None:
        faint = photo_bg(imgs[0], focal=(s.focal_x, s.focal_y)).convert("RGB")
        faint = ImageEnhance.Brightness(faint.filter(ImageFilter.GaussianBlur(30))).enhance(0.35).convert("RGBA")
        faint.putalpha(90)
        c.alpha_composite(faint)
    acc = readable_on_dark(accent)
    d = ImageDraw.Draw(c)
    max_w = W - 2 * PAD

    qf = get_font(str(config.FONT_BODY), 400, "Black")
    d.text((PAD - 14, 20), "\u201C", font=qf, fill=acc + (255,))

    quote = s.headline.strip().strip('"\u201C\u201D')
    tf, tlines, th = fit_text(quote, lambda t, z: body_font(t, z, "Bold"), max_w, 560, 74, 34, 1.25)
    block = len(tlines) * th
    y = 360 + max(0, (560 - block) // 2)
    y = draw_lines(c, tlines, tf, th, PAD, y, shadow=False)

    d.rectangle((PAD, y + 40, PAD + 90, y + 50), fill=acc)
    if s.subtext:
        nf = body_font(s.subtext, 36, "SemiBold")
        name_lines = wrap(s.subtext, nf, max_w - 280)
        draw_lines(c, name_lines[:2], nf, 46, PAD, y + 76, fill=acc + (255,), shadow=False)

    if imgs[0] is not None:
        ph = circle_photo(imgs[0], 210, acc, 8, (s.focal_x, s.focal_y))
        c.alpha_composite(ph, (W - PAD - ph.width, H - 120 - ph.height))
    return c


def render_split(s: Slide, imgs, accent) -> Image.Image:
    half = H // 2
    c = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    top = photo_bg(imgs[0], (W, half), (s.focal_x, s.focal_y))
    bottom = photo_bg(imgs[1] if len(imgs) > 1 else imgs[0], (W, H - half), (0.5, 0.4))
    c.alpha_composite(top, (0, 0))
    c.alpha_composite(bottom, (0, half))
    c.alpha_composite(top_shade(c.size, 220, 120))
    c.alpha_composite(vertical_gradient(c.size, 0.7, 220))

    acc = readable_on_dark(accent)
    d = ImageDraw.Draw(c)
    max_w = W - 2 * PAD
    hf, hlines, hh = fit_text(_headline(s), headline_font, max_w - 40, 220, 120, 60, 0.95)
    band_h = len(hlines) * hh + 50
    by = half - band_h // 2
    band = Image.new("RGBA", (W, band_h), accent + (235,))
    c.alpha_composite(band, (0, by))
    d.rectangle((0, by, W, by + 6), fill=acc)
    d.rectangle((0, by + band_h - 6, W, by + band_h), fill=acc)
    draw_lines(c, hlines, hf, hh, PAD, by + 30, fill=text_on(accent), align="center", shadow=False)

    if s.subtext:
        sf, slines, sh = fit_text(s.subtext, lambda t, z: body_font(t, z, "SemiBold"), max_w, 130, 36, 24, 1.3)
        draw_lines(c, slines, sf, sh, PAD, H - 120 - len(slines) * sh, align="center")
    return c


RENDERERS = {
    "cover": render_cover,
    "hero": render_hero,
    "stat": render_stat,
    "quote": render_quote,
    "split": render_split,
}


def render_slide(s: Slide, images: list[Image.Image], index: int = 0, total: int = 1,
                 default_accent: str = config.ACCENT_COLOR, handle: str = config.PAGE_HANDLE,
                 logo: Image.Image | None = None) -> Image.Image:
    if logo is None:
        logo = _load_logo(config.LOGO_PATH)
    accent = hex_to_rgb(s.accent_color or default_accent, hex_to_rgb(default_accent))
    i1 = s.image_index if images and 0 <= s.image_index < len(images) else 0
    first = images[i1] if images else None
    second = images[s.image_index_2] if images and 0 <= s.image_index_2 < len(images) else None
    if second is None and len(images) > 1:
        second = images[(i1 + 1) % len(images)]
    imgs = [first, second] if second is not None else [first]

    canvas = RENDERERS.get(s.template, render_hero)(s, imgs, accent)
    branding(canvas, handle, logo, index, total)
    return canvas.convert("RGB")
