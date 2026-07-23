import json
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "static" / "index3" / "assets"
APP_HTML = ROOT / "static" / "index3.html"
EMAIL_STORE = ROOT / "app3_parts" / "auth" / "platform_auth_email_store_part.py"


class ProductIconAssetTests(unittest.TestCase):
    def test_transparent_icons_have_transparent_corners(self):
        expected_sizes = {
            "icon-256x256.png": (256, 256),
            "email-icon-256x256.png": (256, 256),
            "favicon-16x16.png": (16, 16),
            "favicon-32x32.png": (32, 32),
            "favicon-48x48.png": (48, 48),
            "android-chrome-192x192.png": (192, 192),
            "android-chrome-512x512.png": (512, 512),
        }
        for name, expected_size in expected_sizes.items():
            with self.subTest(name=name):
                image = Image.open(ASSET_DIR / name).convert("RGBA")
                self.assertEqual(image.size, expected_size)
                self.assertEqual(image.getpixel((0, 0))[3], 0)
                self.assertEqual(image.getpixel((image.width // 2, image.height // 2))[3], 255)

    def test_platform_masked_icons_remain_opaque(self):
        expected_sizes = {
            "apple-touch-icon.png": (180, 180),
            "android-chrome-maskable-192x192.png": (192, 192),
            "android-chrome-maskable-512x512.png": (512, 512),
        }
        for name, expected_size in expected_sizes.items():
            with self.subTest(name=name):
                image = Image.open(ASSET_DIR / name).convert("RGBA")
                self.assertEqual(image.size, expected_size)
                self.assertEqual(image.getchannel("A").getextrema(), (255, 255))

    def test_favicon_ico_contains_transparent_multisize_frames(self):
        with Image.open(ASSET_DIR / "favicon.ico") as image:
            self.assertTrue({(16, 16), (32, 32), (48, 48), (256, 256)}.issubset(image.info["sizes"]))
            rgba = image.convert("RGBA")
        self.assertEqual(rgba.getpixel((0, 0))[3], 0)
        self.assertEqual(rgba.getpixel((rgba.width // 2, rgba.height // 2))[3], 255)

    def test_manifest_separates_any_and_maskable_icons(self):
        manifest = json.loads((ASSET_DIR / "site.webmanifest").read_text(encoding="utf-8"))
        purposes = {item["purpose"] for item in manifest["icons"]}
        self.assertEqual(purposes, {"any", "maskable"})
        self.assertEqual(sum(item["purpose"] == "any" for item in manifest["icons"]), 2)
        self.assertEqual(sum(item["purpose"] == "maskable" for item in manifest["icons"]), 2)
        self.assertTrue(all("apervia_icon_v2" in item["src"] for item in manifest["icons"]))

    def test_consumers_use_v2_and_security_email_asset(self):
        self.assertNotIn("apervia_icon_v1", APP_HTML.read_text(encoding="utf-8"))
        store = EMAIL_STORE.read_text(encoding="utf-8")
        self.assertIn("email-icon-256x256.png", store)


if __name__ == "__main__":
    unittest.main()
