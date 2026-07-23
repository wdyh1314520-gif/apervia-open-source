import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index3.html").read_text(encoding="utf-8")
MAIN = ROOT / "static" / "index3" / "js" / "index3.js"
MODULE_DIR = MAIN.parent


class FrontendProductModuleTests(unittest.TestCase):
    def test_large_cross_domain_blocks_live_in_one_product_module_each(self):
        modules = {
            "index3-composer-draft-runtime.js": "function composerAttachmentDraftClone",
            "index3-session-routing.js": "function getRouteChatSessionId",
            "index3-app-errors.js": "function normalizeSessionBackendErrorPayload",
            "index3-browser-context.js": "function isSettingTruthyValue",
        }
        all_sources = {
            path.name: path.read_text(encoding="utf-8")
            for path in MODULE_DIR.glob("*.js")
        }
        for filename, marker in modules.items():
            self.assertIn(marker, all_sources[filename])
            owners = [name for name, source in all_sources.items() if marker in source]
            self.assertEqual([filename], owners, marker)

    def test_product_modules_load_before_remaining_bootstrap(self):
        names = [
            "index3-composer-draft-runtime.js",
            "index3-session-routing.js",
            "index3-app-errors.js",
            "index3-browser-context.js",
            "index3.js",
        ]
        positions = [HTML.index(name) for name in names]
        self.assertEqual(sorted(positions), positions)

    def test_extracted_module_declarations_are_not_redefined(self):
        module_names = {
            "index3-composer-draft-runtime.js",
            "index3-session-routing.js",
            "index3-app-errors.js",
            "index3-browser-context.js",
        }
        sources = {path.name: path.read_text(encoding="utf-8") for path in MODULE_DIR.glob("*.js")}
        declaration = re.compile(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|^(?:const|let|class)\s+([A-Za-z_$][\w$]*)", re.MULTILINE)
        for module_name in module_names:
            declared_names = {left or right for left, right in declaration.findall(sources[module_name])}
            for declared_name in declared_names:
                owner_pattern = re.compile(
                    rf"^(?:(?:async\s+)?function|const|let|class)\s+{re.escape(declared_name)}\b",
                    re.MULTILINE,
                )
                owners = [name for name, source in sources.items() if owner_pattern.search(source)]
                self.assertEqual([module_name], owners, declared_name)

    def test_main_bootstrap_is_no_longer_the_largest_frontend_domain_file(self):
        self.assertLess(MAIN.stat().st_size, 140_000)
        source = MAIN.read_text(encoding="utf-8")
        moved_comments = re.findall(r"Product module moved to ([\w-]+\.js)", source)
        self.assertEqual(4, len(moved_comments))


if __name__ == "__main__":
    unittest.main()
