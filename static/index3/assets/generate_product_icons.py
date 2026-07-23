from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw


ASSET_DIR = Path(__file__).resolve().parent
MASTER_PATH = ASSET_DIR / "apervia-icon-master.png"
ICON_VERSION = "apervia_icon_v2"
FAVICON_SIZES = (16, 32, 48, 64, 128, 256)
RESAMPLE = Image.Resampling.LANCZOS


def _master_rgba() -> Image.Image:
    image = Image.open(MASTER_PATH).convert("RGBA")
    if image.width != image.height:
        raise ValueError("产品图标母版必须为正方形")
    return image


def _rounded_master(master: Image.Image) -> Image.Image:
    size = master.width
    mask = Image.new("L", master.size, 0)
    draw = ImageDraw.Draw(mask)
    radius = round(size * 0.215)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    result = master.copy()
    result.putalpha(mask)
    return result


def _extract_logo(master: Image.Image) -> Image.Image:
    red, green, blue, _alpha = master.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
    chroma = ImageChops.subtract(maximum, minimum)
    logo_alpha = chroma.point(
        lambda value: 0 if value <= 20 else (255 if value >= 68 else round((value - 20) * 255 / 48))
    )
    bbox = logo_alpha.getbbox()
    if not bbox:
        raise ValueError("未能从母版提取产品标志")
    logo = master.crop(bbox)
    logo.putalpha(logo_alpha.crop(bbox))
    return logo


def _maskable_icon(master: Image.Image, size: int) -> Image.Image:
    logo = _extract_logo(master)
    limit = round(size * 0.64)
    scale = min(limit / logo.width, limit / logo.height)
    logo_size = (max(1, round(logo.width * scale)), max(1, round(logo.height * scale)))
    logo = logo.resize(logo_size, RESAMPLE)
    canvas = Image.new("RGBA", (size, size), (245, 248, 254, 255))
    offset = ((size - logo.width) // 2, (size - logo.height) // 2)
    canvas.alpha_composite(logo, offset)
    return canvas


def _save_png(image: Image.Image, name: str) -> None:
    image.save(ASSET_DIR / name, format="PNG", optimize=True)


def generate() -> None:
    master = _master_rgba()
    rounded = _rounded_master(master)

    _save_png(rounded.resize((256, 256), RESAMPLE), "icon-256x256.png")
    _save_png(rounded.resize((256, 256), RESAMPLE), "email-icon-256x256.png")
    for size in (16, 32, 48):
        _save_png(rounded.resize((size, size), RESAMPLE), f"favicon-{size}x{size}.png")
    rounded.save(
        ASSET_DIR / "favicon.ico",
        format="ICO",
        sizes=[(size, size) for size in FAVICON_SIZES],
    )

    _save_png(master.resize((180, 180), RESAMPLE).convert("RGB"), "apple-touch-icon.png")
    for size in (192, 512):
        _save_png(rounded.resize((size, size), RESAMPLE), f"android-chrome-{size}x{size}.png")
        _save_png(_maskable_icon(master, size), f"android-chrome-maskable-{size}x{size}.png")

    manifest = {
        "name": "Apervia",
        "short_name": "Apervia",
        "icons": [
            {
                "src": f"/static/index3/assets/android-chrome-192x192.png?v={ICON_VERSION}",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": f"/static/index3/assets/android-chrome-512x512.png?v={ICON_VERSION}",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": f"/static/index3/assets/android-chrome-maskable-192x192.png?v={ICON_VERSION}",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "maskable",
            },
            {
                "src": f"/static/index3/assets/android-chrome-maskable-512x512.png?v={ICON_VERSION}",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
        "theme_color": "#ffffff",
        "background_color": "#ffffff",
        "display": "standalone",
    }
    (ASSET_DIR / "site.webmanifest").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    generate()
