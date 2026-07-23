import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACCOUNT_UI_JS = ROOT / "static" / "index3" / "js" / "index3-account-cloud-lifecycle.js"


def _extract_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    body_start = source.index("{", start)
    depth = 0
    for index in range(body_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"函数未闭合: {name}")


class AccountIdentityUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = ACCOUNT_UI_JS.read_text(encoding="utf-8")
        palette_start = source.index("const ACCOUNT_AVATAR_COLORS")
        palette_end = source.index("]);", palette_start) + 3
        helpers = "\n".join([
            source[palette_start:palette_end],
            "let currentAccountProfile = null;",
            _extract_function(source, "normalizeAccountProfile"),
            _extract_function(source, "accountDefaultDisplayNameFromEmail"),
            _extract_function(source, "accountAvatarColorFromText"),
            _extract_function(source, "accountProfilePrimaryText"),
        ])
        probe = r"""
const colorInputs = Array.from({length: 12}, (_, i) => `user${i}@example.com`);
console.log(JSON.stringify({
  passwordFallback: accountProfilePrimaryText({
    email: 'xiaolingu548@example.com',
    login_method_label: '密码登录',
    profile: {},
  }),
  customName: accountProfilePrimaryText({
    email: 'xiaolingu548@example.com',
    login_method_label: '密码登录',
    profile: {display_name: '晓琳 顾'},
  }),
  registeredName: accountProfilePrimaryText({
    email: 'avatar-test@example.com',
    name: 'wdf',
    profile: {},
  }),
  stableColorA: accountAvatarColorFromText('xiaolingu548@example.com'),
  stableColorB: accountAvatarColorFromText('XIAOLINGU548@EXAMPLE.COM'),
  variedColors: [...new Set(colorInputs.map(accountAvatarColorFromText))],
}));
"""
        completed = subprocess.run(
            ["node", "-e", helpers + probe],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        cls.result = json.loads(completed.stdout)

    def test_login_method_does_not_replace_default_name(self):
        self.assertEqual(self.result["passwordFallback"], "xiaolingu548")

    def test_custom_display_name_keeps_priority(self):
        self.assertEqual(self.result["customName"], "晓琳 顾")

    def test_registered_name_precedes_email_fallback(self):
        self.assertEqual(self.result["registeredName"], "wdf")

    def test_avatar_color_is_stable_and_varied(self):
        self.assertEqual(self.result["stableColorA"], self.result["stableColorB"])
        self.assertGreaterEqual(len(self.result["variedColors"]), 4)

if __name__ == "__main__":
    unittest.main()
