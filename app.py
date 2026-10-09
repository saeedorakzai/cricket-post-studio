import hmac
import io
import zipfile
from datetime import datetime

import streamlit as st
from PIL import Image

import config
from imaging import load_image
from planner import PROVIDERS, Plan, make_plan
from renderer import HAS_RAQM, is_rtl, render_slide

IMAGE_TYPES = ["png", "jpg", "jpeg", "webp", "bmp", "gif", "tif", "tiff", "heic", "heif", "avif"]

st.set_page_config(page_title="Cricket Post Studio", page_icon="🏏", layout="wide")

if config.APP_PASSWORD and not st.session_state.get("authed"):
    st.title("Cricket Post Studio")
    pw = st.text_input("Password", type="password")
    if pw and hmac.compare_digest(pw, config.APP_PASSWORD):
        st.session_state["authed"] = True
        st.rerun()
    elif pw:
        st.error("Wrong password.")
    st.stop()

st.title("Cricket Post Studio")
st.caption("Turn one cricket post + a few photos into a ready-to-publish 4:5 carousel.")

ss = st.session_state
ss.setdefault("plan", None)
ss.setdefault("images", [])
ss.setdefault("gen", 0)
ss.setdefault("notice", None)

# ---------- sidebar settings ----------
with st.sidebar:
    st.header("Settings")
    provider_ids = list(PROVIDERS)
    provider = st.radio("AI provider", provider_ids, format_func=lambda p: PROVIDERS[p][0], horizontal=True,
                        index=provider_ids.index(config.AI_PROVIDER) if config.AI_PROVIDER in PROVIDERS else 0)
    provider_name = PROVIDERS[provider][0]
    saved_key = PROVIDERS[provider][2]()
    typed_key = st.text_input(f"{provider_name} API key", type="password", key=f"key_{provider}",
                              placeholder="Using saved key" if saved_key else "Paste key (or leave empty)",
                              help="Leave empty to use the saved key, or rule-based layouts if none is saved.")
    api_key = typed_key.strip() or saved_key
    n_slides = st.slider("Number of slides", 3, 6, 4)
    handle = st.text_input("Page handle / watermark", value=config.PAGE_HANDLE)
    logo_file = st.file_uploader("Logo (optional)", type=["png", "jpg", "jpeg", "webp"])
    team = st.selectbox("Theme colour", list(config.TEAM_COLORS), index=0)
    preset = config.TEAM_COLORS[team]
    accent = st.color_picker("Accent colour", value=preset or config.ACCENT_COLOR, key=f"accent_{team}")
    use_ai_colors = st.checkbox("Let AI pick colour per slide", value=team == "Custom")

logo = Image.open(io.BytesIO(logo_file.getvalue())).convert("RGBA") if logo_file else None

# ---------- inputs ----------
col_text, col_imgs = st.columns([3, 2])
with col_text:
    txt_file = st.file_uploader("Upload post as .txt (optional)", type=["txt"])
    default_text = txt_file.getvalue().decode("utf-8", errors="ignore") if txt_file else ""
    text = st.text_area("Post text", value=default_text, height=230,
                        placeholder="Paste your Facebook post text here...")
with col_imgs:
    files = st.file_uploader("Images (any format)", type=IMAGE_TYPES, accept_multiple_files=True)
    if files:
        st.image([f.getvalue() for f in files], width=110, caption=[f"#{i}" for i in range(len(files))])

if text and is_rtl(text) and not HAS_RAQM:
    st.warning("Urdu text detected but Pillow has no libraqm support; letters may not join correctly.")

if st.button("Generate slides", type="primary", disabled=not (text.strip() and files)):
    images, bad = [], []
    for f in files:
        try:
            images.append(load_image(f.getvalue()))
        except Exception:
            bad.append(f.name)
    if bad:
        st.warning(f"Skipped unreadable images: {', '.join(bad)}")
    if images:
        with st.spinner(f"Planning slides with {provider_name}..." if api_key else "Building slides..."):
            plan, err = make_plan(text, images, n_slides, provider, api_key)
        if not use_ai_colors:
            for s in plan.slides:
                s.accent_color = ""
        ss.plan, ss.images, ss.notice = plan, images, err
        ss.gen += 1

if not text.strip() or not files:
    st.info("Add the post text and at least one image, then click **Generate slides**.")

plan: Plan | None = ss.plan
if plan is None:
    st.stop()

if ss.notice:
    st.warning(ss.notice)

# ---------- preview + edit ----------
st.subheader("Slides")
images = ss.images
n_img = len(images)
rendered = []
cols = st.columns(3)
for i, s in enumerate(plan.slides):
    k = f"{ss.gen}_{i}"
    with cols[i % 3]:
        with st.expander(f"Edit slide {i + 1}", expanded=False):
            s.template = st.selectbox("Template", config.TEMPLATES, index=config.TEMPLATES.index(s.template),
                                      key=f"{k}_tpl")
            s.image_index = st.number_input("Image #", 0, max(n_img - 1, 0), min(s.image_index, n_img - 1),
                                            key=f"{k}_img")
            if s.template == "split":
                s.image_index_2 = st.number_input("Second image #", 0, max(n_img - 1, 0),
                                                  max(0, min(s.image_index_2, n_img - 1)), key=f"{k}_img2")
            label = "Quote" if s.template == "quote" else "Headline"
            s.headline = st.text_area(label, s.headline, height=70, key=f"{k}_head")
            s.subtext = st.text_area("Speaker" if s.template == "quote" else "Subtext", s.subtext,
                                     height=70, key=f"{k}_sub")
            if s.template == "stat":
                s.stat_value = st.text_input("Stat value", s.stat_value, key=f"{k}_sv")
                s.stat_label = st.text_input("Stat label", s.stat_label, key=f"{k}_sl")
            fx, fy = st.columns(2)
            s.focal_x = fx.slider("Focus X", 0.0, 1.0, float(s.focal_x), 0.05, key=f"{k}_fx")
            s.focal_y = fy.slider("Focus Y", 0.0, 1.0, float(s.focal_y), 0.05, key=f"{k}_fy")
        img = render_slide(s, images, i, len(plan.slides), default_accent=accent, handle=handle, logo=logo)
        rendered.append(img)
        st.image(img, width="stretch")

# ---------- caption + export ----------
st.subheader("Caption")
caption = st.text_area("Post caption", plan.caption + "\n\n" + " ".join(plan.hashtags), height=150,
                       key=f"{ss.gen}_caption")


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


zip_buf = io.BytesIO()
with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
    for i, img in enumerate(rendered, 1):
        zf.writestr(f"slide_{i:02d}.png", _png(img))
    zf.writestr("caption.txt", caption)

c1, c2 = st.columns(2)
c1.download_button("Download ZIP", zip_buf.getvalue(), file_name="cricket_carousel.zip",
                   mime="application/zip", type="primary", width="stretch")
if c2.button("Save to output folder", width="stretch"):
    out = config.OUTPUT_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    for i, img in enumerate(rendered, 1):
        img.save(out / f"slide_{i:02d}.png")
    (out / "caption.txt").write_text(caption, encoding="utf-8")
    c2.success(f"Saved to {out}")
