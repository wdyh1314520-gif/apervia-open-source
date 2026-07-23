import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIDEBAR_JS = ROOT / "static" / "index3" / "js" / "index3-sidebar-session-ui.js"
SIDEBAR_CSS = ROOT / "static" / "index3" / "css" / "index3-sidebar-media.css"


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
        raise AssertionError(f"JavaScript 函数参数未闭合: {name}")
    depth = 0
    for index in range(body_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"JavaScript 函数未闭合: {name}")


class SidebarSessionMenuUiTests(unittest.TestCase):
    def test_menu_prefers_down_and_flips_up_near_list_bottom(self):
        source = SIDEBAR_JS.read_text(encoding="utf-8")
        helper = extract_javascript_function(source, "sidebarSessionMenuDirection")
        probe = """
const bounds = {top:100, bottom:700};
console.log(JSON.stringify({
  upper: sidebarSessionMenuDirection({top:160,bottom:188}, 240, bounds, 720),
  lower: sidebarSessionMenuDirection({top:520,bottom:548}, 240, bounds, 720),
  constrained: sidebarSessionMenuDirection({top:300,bottom:328}, 240, {top:100,bottom:500}, 720),
  liveCase: sidebarSessionMenuDirection({top:381,bottom:407}, 243, {top:0,bottom:581}, 657),
  nearFit: sidebarSessionMenuDirection({top:312,bottom:338}, 243, {top:0,bottom:581}, 657),
}));
"""
        completed = subprocess.run(
            ["node", "-e", helper + probe],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)
        self.assertEqual(
            result,
            {
                "upper": "down",
                "lower": "up",
                "constrained": "up",
                "liveCase": "up",
                "nearFit": "down",
            },
        )

    def test_menu_uses_sidebar_boundaries_and_fixed_viewport_position(self):
        source = SIDEBAR_JS.read_text(encoding="utf-8")
        css = SIDEBAR_CSS.read_text(encoding="utf-8")
        self.assertIn("item.closest?.('.ow-sidebar-shell')", source)
        self.assertIn("footerRect?.top || listRect?.bottom", source)
        self.assertIn("positionSidebarSessionMenu(item, trigger, menu)", source)
        self.assertIn("ensureSidebarSessionMenuPositionBindings();", source)
        self.assertNotIn("if(chatListEl && chatListEl.dataset.sessionMenuPositionBound", source.split("function ensureSidebarSessionMenuPositionBindings", 1)[0])
        self.assertIn("menu.style.left = `${Math.round(left)}px`", source)
        self.assertIn("menu.style.top = `${Math.round(top)}px`", source)
        self.assertIn("item.appendChild(menu)", source)
        self.assertNotIn("actions.appendChild(menu)", source)
        menu_css = css.split(".ow-chat-menu{", 1)[1].split("}", 1)[0]
        self.assertIn("position:fixed", menu_css)
        self.assertNotIn("position:absolute", menu_css)
        self.assertNotIn(".ow-chat-menu.open-up", css)


if __name__ == "__main__":
    unittest.main()
