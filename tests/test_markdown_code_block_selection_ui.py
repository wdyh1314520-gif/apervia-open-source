import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_UI_JS = ROOT / "static" / "index3" / "js" / "index3-render-markdown-ui.js"
INDEX_JS = ROOT / "static" / "index3" / "js" / "index3.js"
INDEX_HTML = ROOT / "static" / "index3.html"
INDEX_CSS = ROOT / "static" / "index3" / "css" / "index3.css"


class MarkdownCodeBlockSelectionUiTests(unittest.TestCase):
    def test_only_collapsible_code_blocks_render_the_fade_layer(self):
        source = MARKDOWN_UI_JS.read_text(encoding="utf-8")
        start = source.index("function renderCodeBlockHtml(")
        end = source.index("\nfunction copyText(", start)
        render_source = source[start:end]

        self.assertIn(
            'const collapseFadeHtml = needCollapse ? `<div class="code-fade"></div>` : ``;',
            render_source,
        )
        self.assertEqual(1, render_source.count('<div class="code-fade"></div>'))

    def test_fade_layer_never_intercepts_text_selection(self):
        css = INDEX_CSS.read_text(encoding="utf-8")
        rule_start = css.index(".code-block .code-fade{")
        rule_end = css.index("}", rule_start)
        rule = css[rule_start:rule_end]

        self.assertIn("pointer-events:none", rule)

    def test_code_runner_dock_owns_its_dom_bindings_before_resize_events(self):
        markdown_source = MARKDOWN_UI_JS.read_text(encoding="utf-8")
        index_source = INDEX_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")

        for element_id in (
            "main",
            "codeRunDock",
            "codeRunDockBody",
            "codeRunDockTitle",
            "codeRunDockKind",
            "codeRunDockClose",
        ):
            self.assertIn(f"document.getElementById('{element_id}')", markdown_source)

        declaration = markdown_source.index("const codeRunDockEl =")
        resize_binding = markdown_source.index(
            "window.addEventListener('resize', ()=>syncCodeRunDockReserve()"
        )
        self.assertLess(declaration, resize_binding)
        self.assertIn("codeRunDockCloseEl?.addEventListener('click'", markdown_source)
        self.assertNotIn("const codeRunDockEl =", index_source)
        self.assertNotIn("codeRunDockCloseEl?.addEventListener('click'", index_source)
        self.assertLess(
            html.index('/static/index3/js/index3-render-markdown-ui.js'),
            html.index('/static/index3/js/index3.js'),
        )


if __name__ == "__main__":
    unittest.main()
