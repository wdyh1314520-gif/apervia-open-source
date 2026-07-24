import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILES_UI = ROOT / "static" / "index3" / "js" / "index3-settings-api-profiles-ui.js"
MODELS_UI = ROOT / "static" / "index3" / "js" / "index3-settings-models-ui.js"
BACKEND = ROOT / "app3_parts" / "chat" / "chat_public_api_routes_part.py"


def extract_javascript_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    params_start = source.index("(", start)
    params_depth = 0
    body_start = -1
    for index in range(params_start, len(source)):
        char = source[index]
        if char == "(":
            params_depth += 1
        elif char == ")":
            params_depth -= 1
            if params_depth == 0:
                body_start = source.index("{", index)
                break
    if body_start < 0:
        raise AssertionError(f"JavaScript function parameters are not closed: {name}")
    depth = 0
    for index in range(body_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"JavaScript function body is not closed: {name}")


class ApiVendorI18nTests(unittest.TestCase):
    def test_stale_chinese_vendor_label_does_not_leak_into_english(self):
        source = PROFILES_UI.read_text(encoding="utf-8")
        helpers = "\n".join([
            extract_javascript_function(source, "detectVendorMeta"),
            extract_javascript_function(source, "apiVendorDisplayLabel"),
        ])
        probe = r"""
const resources = {
  en:{
    'settings.vendor.openai_compatible':'OpenAI compatible',
    'settings.vendor.with_host':'{vendor} · {host}',
    'settings.models.unknown_host':'Unknown · {host}',
  },
  'zh-CN':{
    'settings.vendor.openai_compatible':'OpenAI 兼容',
    'settings.vendor.with_host':'{vendor} · {host}',
    'settings.models.unknown_host':'未识别 · {host}',
  },
};
global.window = {AperviaI18n:{language:'en', t(key, params, fallback){
  const raw = resources[this.language]?.[key] || fallback || key;
  return String(raw).replace(/\{([A-Za-z0-9_]+)\}/g, (_m, name)=>String(params?.[name] ?? ''));
}}};
const profile = {vendor:'openai_compatible', vendor_label:'OpenAI 兼容 · dawcode.com', api_key:'sk-test', api_base:'https://dawcode.com/v1'};
const english = apiVendorDisplayLabel(profile, profile.api_key, profile.api_base);
const compact = apiVendorDisplayLabel(profile, profile.api_key, profile.api_base, {includeHost:false});
window.AperviaI18n.language = 'zh-CN';
const chinese = apiVendorDisplayLabel(profile, profile.api_key, profile.api_base);
console.log(JSON.stringify({english, compact, chinese}));
"""
        completed = subprocess.run(
            ["node", "-e", helpers + probe],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if completed.returncode != 0:
            self.fail(completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual("OpenAI compatible · dawcode.com", result["english"])
        self.assertEqual("OpenAI compatible", result["compact"])
        self.assertEqual("OpenAI 兼容 · dawcode.com", result["chinese"])

    def test_model_management_uses_stable_vendor_code(self):
        models = MODELS_UI.read_text(encoding="utf-8")
        backend = BACKEND.read_text(encoding="utf-8")
        self.assertIn("apiVendorDisplayLabel(profile, profile.api_key, profile.api_base)", models)
        self.assertNotIn("const rawVendorLabel", models)
        self.assertIn("'OpenAI compatible · {host}'", backend)
        self.assertNotIn("f'OpenAI 兼容 · {host}'", backend)


if __name__ == "__main__":
    unittest.main()
