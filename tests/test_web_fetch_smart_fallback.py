import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "app3_parts" / "web" / "web_render_fallback_part.py"
TOOL_DISPATCH_SOURCE_PATH = ROOT / "app3_parts" / "tools" / "tool_dispatch_part.py"


def _load_function(name: str, namespace: dict):
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"), filename=str(SOURCE_PATH))
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(SOURCE_PATH), "exec"), namespace)
    return namespace[name]


def _load_dispatch_function(name: str, namespace: dict):
    tree = ast.parse(TOOL_DISPATCH_SOURCE_PATH.read_text(encoding="utf-8"), filename=str(TOOL_DISPATCH_SOURCE_PATH))
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(TOOL_DISPATCH_SOURCE_PATH), "exec"), namespace)
    return namespace[name]


class WebFetchSmartFallbackTests(unittest.TestCase):
    def test_explicit_403_uses_single_page_then_content_fallback(self):
        calls = {"fetch": [], "raw": 0, "fallback": 0}

        def fetch_url_content(url, **kwargs):
            calls["fetch"].append((url, dict(kwargs)))
            return {
                "url": url,
                "final_url": url,
                "content_type": "text/html",
                "title": "",
                "text": "",
                "warning": "fast fetch failed: HTTPStatusError: status=403 forbidden",
            }

        def raw_fetch(*_args, **_kwargs):
            calls["raw"] += 1
            raise AssertionError("明确 403 后不应再次直连同一 URL")

        def content_fallback(url, out, **_kwargs):
            calls["fallback"] += 1
            return {**out, "url": url, "text": "fallback evidence", "provider": "tavily"}

        namespace = {
            "app_getenv": lambda _name, default="": default,
            "fetch_url_content": fetch_url_content,
            "_is_price_or_product_query": lambda _value: False,
            "_fetch_raw_with_fallback": raw_fetch,
            "_apply_content_fallback": content_fallback,
            "_strip_private_fetch_fields": lambda value: value,
            "truncate_text": lambda value, max_chars=12000: str(value or "")[:max_chars],
        }
        smart_fetch = _load_function("fetch_url_content_smart", namespace)

        result = smart_fetch("https://example.com/news", query="latest", max_chars=12000)

        self.assertEqual("tavily", result.get("provider"))
        self.assertEqual(1, calls["fallback"])
        self.assertEqual(0, calls["raw"])
        self.assertEqual(1, len(calls["fetch"]))
        self.assertEqual(1, calls["fetch"][0][1].get("max_pages"))
        self.assertFalse(calls["fetch"][0][1].get("enable_price_discovery"))

    def test_product_query_keeps_price_discovery_enabled(self):
        calls = []

        def fetch_url_content(url, **kwargs):
            calls.append(dict(kwargs))
            return {
                "url": url,
                "final_url": url,
                "content_type": "application/json",
                "title": "",
                "text": "product page",
                "warning": "",
            }

        namespace = {
            "app_getenv": lambda _name, default="": default,
            "fetch_url_content": fetch_url_content,
            "_is_price_or_product_query": lambda value: "价格" in value,
            "_strip_private_fetch_fields": lambda value: value,
            "truncate_text": lambda value, max_chars=12000: str(value or "")[:max_chars],
        }
        smart_fetch = _load_function("fetch_url_content_smart", namespace)

        smart_fetch("https://example.com/product", query="这款产品价格", max_chars=12000)

        self.assertEqual(1, len(calls))
        self.assertTrue(calls[0].get("enable_price_discovery"))

    def test_fetch_url_dedupe_key_merges_locale_mirrors_and_tracking(self):
        import re
        import urllib.parse

        dedupe_key = _load_dispatch_function(
            "_fetch_url_dedupe_key",
            {"re": re, "urllib": urllib, "urlparse": urllib.parse.urlparse},
        )

        canonical = dedupe_key("https://openai.com/news/product-releases/?utm_source=test")
        localized = dedupe_key("https://OPENAI.com/zh-CN/news/product-releases/?gclid=abc")
        different = dedupe_key("https://openai.com/news/research/")

        self.assertEqual(canonical, localized)
        self.assertNotEqual(canonical, different)


if __name__ == "__main__":
    unittest.main()
