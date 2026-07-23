import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_UI_JS = ROOT / "static" / "index3" / "js" / "index3-render-markdown-ui.js"
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


if __name__ == "__main__":
    unittest.main()
