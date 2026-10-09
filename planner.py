import json
import re
from typing import Literal

from PIL import Image
from pydantic import BaseModel, Field

import config
from imaging import downscale, to_jpeg_bytes

TemplateName = Literal["cover", "hero", "stat", "quote", "split"]


class Slide(BaseModel):
    template: TemplateName
    image_index: int = 0
    image_index_2: int = Field(default=-1, description="Second image, only for 'split'; -1 otherwise")
    headline: str = ""
    subtext: str = ""
    stat_value: str = ""
    stat_label: str = ""
    focal_x: float = 0.5
    focal_y: float = 0.4
    accent_color: str = ""


class Plan(BaseModel):
    slides: list[Slide]
    caption: str = ""
    hashtags: list[str] = []


PROMPT = """You are a social media designer for a cricket Facebook/Instagram page.
From the POST TEXT and the {n_images} attached photos (indexed 0..{last_index} in the order given),
plan exactly {n_slides} carousel slides that tell the story visually.

Templates:
- cover: first slide, bold hook title (headline) + short teaser (subtext).
- hero: full-bleed action photo with a punchy headline and one supporting line.
- stat: a single big number from the text (score, wickets, strike rate, record) in stat_value, e.g. "112*", "5/23"; stat_label explains it.
- quote: a player/captain/expert quote from the text in headline (no surrounding quote marks), speaker name in subtext.
- split: comparison/versus/two moments; uses image_index and image_index_2 (different images).

Rules:
- The first slide must be "cover". Vary templates; use stat/quote only if the text actually supports them. Never invent numbers or quotes.
- headline max 6 words (quotes may be up to 18 words). subtext max 14 words.
- Choose the most relevant photo per slide; spread different photos across slides when possible.
- focal_x/focal_y (0-1) = where the main subject (player face/body/ball) is in that photo, for cropping.
- accent_color: a hex colour fitting the team/mood (e.g. Pakistan green #01411C, India blue #1F5BB4) or "" for default.
- Write in the same language as the post text.
- caption: an engaging 2-4 sentence post caption. hashtags: 5-10 relevant hashtags without spaces, each starting with #.

POST TEXT:
\"\"\"{text}\"\"\"
"""


def _clamp_plan(plan: Plan, n_images: int, n_slides: int) -> Plan:
    slides = plan.slides[:n_slides]
    for s in slides:
        if n_images:
            s.image_index = min(max(s.image_index, 0), n_images - 1)
            if s.template == "split":
                if s.image_index_2 < 0 or s.image_index_2 >= n_images or s.image_index_2 == s.image_index:
                    s.image_index_2 = (s.image_index + 1) % n_images
        s.focal_x = min(max(s.focal_x, 0.0), 1.0)
        s.focal_y = min(max(s.focal_y, 0.0), 1.0)
        if s.accent_color and not re.fullmatch(r"#[0-9A-Fa-f]{6}", s.accent_color):
            s.accent_color = ""
    plan.slides = slides
    plan.hashtags = [h if h.startswith("#") else f"#{h}" for h in (t.replace(" ", "") for t in plan.hashtags) if h]
    return plan


def plan_with_gemini(text: str, images: list[Image.Image], n_slides: int, api_key: str = "") -> Plan:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key or config.GEMINI_API_KEY)
    parts: list = [
        types.Part.from_bytes(data=to_jpeg_bytes(downscale(img, 768)), mime_type="image/jpeg")
        for img in images
    ]
    parts.append(
        PROMPT.format(
            n_images=len(images),
            last_index=max(len(images) - 1, 0),
            n_slides=n_slides,
            text=text.strip(),
        )
    )
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=Plan,
            temperature=0.7,
        ),
    )
    plan = resp.parsed if isinstance(resp.parsed, Plan) else Plan.model_validate(json.loads(resp.text))
    if not plan.slides:
        raise ValueError("Gemini returned no slides")
    return _clamp_plan(plan, len(images), n_slides)


def plan_with_claude(text: str, images: list[Image.Image], n_slides: int, api_key: str = "") -> Plan:
    import base64

    import anthropic

    client = anthropic.Anthropic(api_key=api_key or config.ANTHROPIC_API_KEY)
    content: list[dict] = []
    for i, img in enumerate(images):
        content.append({"type": "text", "text": f"Photo {i}:"})
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.b64encode(to_jpeg_bytes(downscale(img, 1024))).decode(),
            },
        })
    content.append({
        "type": "text",
        "text": PROMPT.format(n_images=len(images), last_index=max(len(images) - 1, 0),
                              n_slides=n_slides, text=text.strip()),
    })
    resp = client.messages.parse(
        model=config.ANTHROPIC_MODEL,
        max_tokens=4096,
        output_format=Plan,
        messages=[{"role": "user", "content": content}],
    )
    plan = resp.parsed_output
    if plan is None or not plan.slides:
        raise ValueError("Claude returned no slides")
    return _clamp_plan(plan, len(images), n_slides)


_NUMBER_RE = re.compile(r"(?<![\w.])\d{2,}(?:[/.-]\d+)?\*?(?![\w.])|(?<![\w.])\d/\d+(?![\w.])")
_QUOTE_RE = re.compile(r"[\"“]([^\"”]{12,200})[\"”]")


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?۔])\s+|\n+", text.strip())
    return [p.strip() for p in parts if len(p.strip()) > 3]


def _short(s: str, words: int) -> str:
    w = s.split()
    return " ".join(w[:words]) + ("..." if len(w) > words else "")


def plan_fallback(text: str, n_images: int, n_slides: int) -> Plan:
    """Rule-based plan used when Gemini is unavailable."""
    sents = _sentences(text) or ["Cricket update"]
    slides: list[Slide] = []
    img = lambda i: i % n_images if n_images else 0  # noqa: E731

    slides.append(Slide(template="cover", image_index=img(0), headline=_short(sents[0], 6),
                        subtext=_short(sents[1], 14) if len(sents) > 1 else ""))

    quote = _QUOTE_RE.search(text)
    stat = _NUMBER_RE.search(text)
    rest = [s for s in sents[1:] if not (quote and quote.group(1) in s)] or sents
    k = 0
    while len(slides) < n_slides:
        i = len(slides)
        if stat and not any(s.template == "stat" for s in slides):
            sentence = next((s for s in sents if stat.group(0) in s), sents[0])
            label = " ".join(sentence.replace(stat.group(0), "").split()).strip(" ,.-")
            slides.append(Slide(template="stat", image_index=img(i), stat_value=stat.group(0),
                                stat_label=_short(label, 10)))
        elif quote and not any(s.template == "quote" for s in slides):
            slides.append(Slide(template="quote", image_index=img(i), headline=_short(quote.group(1), 18)))
        elif n_images > 1 and not any(s.template == "split" for s in slides) and i >= 3:
            s = rest[k % len(rest)]
            k += 1
            slides.append(Slide(template="split", image_index=img(i), image_index_2=img(i + 1),
                                headline=_short(s, 6), subtext=_short(s, 14)))
        else:
            s = rest[k % len(rest)]
            k += 1
            slides.append(Slide(template="hero", image_index=img(i), headline=_short(s, 6),
                                subtext=" ".join(s.split()[6:20])))

    words = re.findall(r"\b[A-Z][a-zA-Z]{3,}\b", text)
    tags = list(dict.fromkeys(["#Cricket", *[f"#{w}" for w in words[:6]]]))
    return Plan(slides=slides, caption=" ".join(sents[:3]), hashtags=tags)


PROVIDERS = {
    "claude": ("Claude", plan_with_claude, lambda: config.ANTHROPIC_API_KEY),
    "gemini": ("Gemini", plan_with_gemini, lambda: config.GEMINI_API_KEY),
}


def make_plan(text: str, images: list[Image.Image], n_slides: int, provider: str = config.AI_PROVIDER,
              api_key: str = "") -> tuple[Plan, str | None]:
    """Returns (plan, error). error is set when the fallback was used."""
    name, fn, default_key = PROVIDERS.get(provider, PROVIDERS["claude"])
    key = api_key or default_key()
    if not key:
        return plan_fallback(text, len(images), n_slides), f"No {name} API key set - used rule-based layout."
    try:
        return fn(text, images, n_slides, key), None
    except Exception as e:  # network, quota, schema errors
        return plan_fallback(text, len(images), n_slides), f"{name} failed ({e}); used rule-based layout."
