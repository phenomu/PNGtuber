"""Image helpers: RGBA loading, desaturation, aspect-safe scaling, placeholders.

Pure Pillow - importable and testable without Qt or audio.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw


class AssetError(Exception):
    """Raised when an avatar image cannot be loaded."""


def load_rgba(path: str | Path) -> Image.Image:
    """Load an image as RGBA. Raises AssetError with a clear message on failure."""
    p = Path(path)
    if not p.is_file():
        raise AssetError(f"Image not found: {p}")
    try:
        img = Image.open(p)
    except Exception as exc:  # noqa: BLE001 - rethrow with context
        raise AssetError(f"Cannot open image {p}: {exc}") from exc
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    else:
        img.load()
    return img


def desaturate(img: Image.Image, intensity: float) -> Image.Image:
    """Blend an RGBA image toward grayscale.

    intensity 0.0 = original colors, 1.0 = fully grayscale.
    Alpha channel is preserved untouched.
    """
    intensity = min(1.0, max(0.0, float(intensity)))
    if intensity <= 0.0:
        return img.copy()
    rgb = img.convert("RGB")
    gray = rgb.convert("L").convert("RGB")
    blended = Image.blend(rgb, gray, intensity)
    out = blended.convert("RGBA")
    out.putalpha(img.getchannel("A"))
    return out


def fit_size(size: tuple[int, int], max_w: int, max_h: int) -> tuple[int, int]:
    """Aspect-preserving 'contain' fit into (max_w, max_h). Never upscales past 1x."""
    w, h = size
    if w <= 0 or h <= 0:
        return max_w, max_h
    scale = min(max_w / w, max_h / h)
    return max(1, round(w * scale)), max(1, round(h * scale))


def scale_contain(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    """Scale image to fit (max_w, max_h) preserving aspect ratio."""
    target = fit_size(img.size, max_w, max_h)
    if target == img.size:
        return img.copy()
    return img.resize(target, Image.LANCZOS)


def has_real_transparency(img: Image.Image) -> bool:
    """True when the alpha channel contains partially/fully transparent pixels."""
    if img.mode != "RGBA":
        return False
    alpha = img.getchannel("A")
    return alpha.getextrema()[0] < 255


# ---------------------------------------------------------------------------
# Placeholder artwork (used until the user supplies their own PNGs)
# ---------------------------------------------------------------------------

_PLACEHOLDER_SIZE = (512, 512)


def make_placeholder(talking: bool) -> Image.Image:
    """Draw a simple chibi placeholder avatar.

    Same canvas, anchor and proportions for idle/talking so switching states
    never jumps. Talking variant opens the mouth and adds tiny highlights.
    """
    w, h = _PLACEHOLDER_SIZE
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    cx, cy = w // 2, int(h * 0.42)
    head_r = int(w * 0.30)

    skin = (255, 224, 200, 255)
    skin_shade = (238, 198, 175, 255)
    hair_dark = (94, 60, 126, 255)
    hair_mid = (141, 102, 187, 255)
    hair_light = (196, 161, 235, 255)
    accent = (64, 224, 208, 255)
    eye = (52, 44, 74, 255)
    blush = (255, 150, 160, 110)

    # hair back
    d.ellipse(
        (cx - head_r - 26, cy - head_r - 40, cx + head_r + 26, cy + head_r + 30),
        fill=hair_dark,
    )
    # face
    d.ellipse((cx - head_r, cy - head_r, cx + head_r, cy + head_r), fill=skin)
    # bangs
    d.pieslice(
        (cx - head_r - 8, cy - head_r - 14, cx + head_r + 8, cy + head_r - 14),
        180, 360, fill=hair_mid,
    )
    d.polygon(
        [(cx - head_r - 4, cy - head_r), (cx + head_r + 4, cy - head_r),
         (cx + head_r - 30, cy + 18), (cx - head_r + 34, cy + 26)],
        fill=hair_mid,
    )
    # ahoge
    d.line((cx, cy - head_r - 34, cx + 26, cy - head_r - 62), fill=hair_mid, width=14)
    d.line((cx, cy - head_r - 34, cx - 20, cy - head_r - 66), fill=hair_light, width=10)

    # body / hoodie
    body_top = cy + head_r - 34
    d.rounded_rectangle(
        (cx - int(w * 0.24), body_top, cx + int(w * 0.24), h - 24),
        radius=42, fill=(38, 38, 64, 255),
    )
    d.rounded_rectangle(
        (cx - int(w * 0.24), body_top, cx - int(w * 0.24) + 18, h - 24),
        radius=9, fill=accent,
    )
    d.rounded_rectangle(
        (cx + int(w * 0.24) - 18, body_top, cx + int(w * 0.24), h - 24),
        radius=9, fill=accent,
    )
    # collar
    d.polygon(
        [(cx - 46, body_top + 6), (cx + 46, body_top + 6), (cx, body_top + 70)],
        fill=skin_shade,
    )

    # eyes
    eye_dx, eye_dy, eye_r = int(head_r * 0.44), int(head_r * 0.10), int(head_r * 0.16)
    for sx in (-1, 1):
        ex, ey = cx + sx * eye_dx, cy + eye_dy
        d.ellipse((ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r), fill=eye)
        d.ellipse(
            (ex - eye_r + 3, ey - eye_r + 3, ex - eye_r + 3 + eye_r // 2,
             ey - eye_r + 3 + eye_r // 2),
            fill=(255, 255, 255, 235),
        )
        d.polygon(
            [(ex - eye_r - 26, ey - eye_r - 34), (ex - eye_r + 20, ey - eye_r - 34),
             (ex - eye_r + 6, ey - eye_r - 12)],
            fill=hair_dark,
        )
    # blush
    d.ellipse((cx - eye_dx - 34, cy + eye_dy + 20, cx - eye_dx + 2, cy + eye_dy + 40), fill=blush)
    d.ellipse((cx + eye_dx - 2, cy + eye_dy + 20, cx + eye_dx + 34, cy + eye_dy + 40), fill=blush)

    # mouth
    my = cy + int(head_r * 0.52)
    if talking:
        d.ellipse((cx - 22, my - 6, cx + 22, my + 34), fill=(140, 52, 66, 255))
        d.ellipse((cx - 12, my + 16, cx + 12, my + 30), fill=(255, 128, 144, 255))
    else:
        d.arc((cx - 20, my - 16, cx + 20, my + 10), 15, 165, fill=eye, width=6)

    # headset accent (streamer vibe)
    d.arc(
        (cx - head_r - 10, cy - head_r - 18, cx + head_r + 10, cy + head_r + 10),
        200, 340, fill=accent, width=10,
    )
    d.rounded_rectangle(
        (cx - head_r - 22, cy - 8, cx - head_r - 2, cy + 34), radius=12, fill=accent,
    )
    d.rounded_rectangle(
        (cx + head_r + 2, cy - 8, cx + head_r + 22, cy + 34), radius=12, fill=accent,
    )

    return img


def ensure_placeholder_assets(directory: Path) -> tuple[Path, Path]:
    """Write idle.png / talking.png placeholders into directory if missing."""
    directory.mkdir(parents=True, exist_ok=True)
    idle = directory / "idle.png"
    talking = directory / "talking.png"
    if not idle.is_file():
        make_placeholder(talking=False).save(idle)
    if not talking.is_file():
        make_placeholder(talking=True).save(talking)
    return idle, talking
