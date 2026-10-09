import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _setting(name: str, default: str = "") -> str:
    """Read from .env / environment first, then Streamlit Cloud secrets."""
    value = os.getenv(name)
    if value is None:
        try:
            import streamlit as st

            value = st.secrets.get(name)
        except Exception:
            value = None
    return str(value if value is not None else default).strip()


AI_PROVIDER = _setting("AI_PROVIDER", "claude").lower()

ANTHROPIC_API_KEY = _setting("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _setting("ANTHROPIC_MODEL", "claude-sonnet-5-5")

GEMINI_API_KEY = _setting("GEMINI_API_KEY")
GEMINI_MODEL = _setting("GEMINI_MODEL", "gemini-2.5-flash")

PAGE_HANDLE = _setting("PAGE_HANDLE", "@YourCricketPage")
LOGO_PATH = _setting("LOGO_PATH")
ACCENT_COLOR = _setting("ACCENT_COLOR", "#00C853")

APP_PASSWORD = _setting("APP_PASSWORD")

CANVAS_W, CANVAS_H = 1080, 1350

FONTS_DIR = BASE_DIR / "assets" / "fonts"
FONT_HEADLINE = FONTS_DIR / "BebasNeue-Regular.ttf"
FONT_BODY = FONTS_DIR / "Montserrat.ttf"
FONT_URDU = FONTS_DIR / "NotoNastaliqUrdu.ttf"

OUTPUT_DIR = BASE_DIR / "output"

TEMPLATES = ["cover", "hero", "stat", "quote", "split"]

TEAM_COLORS = {
    "Custom": None,
    "Pakistan": "#01411C",
    "India": "#1F5BB4",
    "Australia": "#FFCD00",
    "England": "#C8102E",
    "South Africa": "#007749",
    "New Zealand": "#111111",
    "Sri Lanka": "#0A2A6B",
    "Bangladesh": "#006A4E",
    "Afghanistan": "#0066B3",
    "West Indies": "#7B0041",
}
