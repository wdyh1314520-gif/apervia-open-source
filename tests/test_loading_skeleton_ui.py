import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOADING_JS = ROOT / "static" / "shared" / "loading-ui.js"
LOADING_CSS = ROOT / "static" / "shared" / "loading-ui.css"
APP_HTML = ROOT / "static" / "index3.html"
ADMIN_HTML = ROOT / "static" / "platform-admin" / "index.html"
ADMIN_JS = ROOT / "static" / "platform-admin" / "platform-admin.js"
ACTIVITY_JS = ROOT / "static" / "index3" / "js" / "index3-activity-panel-ui.js"
CHAT_JS = ROOT / "static" / "index3" / "js" / "index3-chat-render-ui.js"
MODEL_JS = ROOT / "static" / "index3" / "js" / "index3-settings-models-ui.js"
MEMORY_JS = ROOT / "static" / "index3" / "js" / "index3-personalization-memory-ui.js"
COMPOSER_LIBRARY_JS = ROOT / "static" / "index3" / "js" / "index3-composer-library-ui.js"
KNOWLEDGE_JS = ROOT / "static" / "index3" / "js" / "index3-knowledge-base-ui.js"


class LoadingSkeletonUiTests(unittest.TestCase):
    def test_shared_generator_builds_bounded_accessible_variants(self):
        probe = f"""
const fs = require('fs');
global.window = globalThis;
eval(fs.readFileSync({json.dumps(str(LOADING_JS))}, 'utf8'));
const activity = AppLoadingUi.html({{variant:'activity', rows:3, label:'正在加载活动'}});
const bounded = AppLoadingUi.html({{variant:'list', rows:99, label:'<loading>'}});
const chat = AppLoadingUi.html({{variant:'chat', rows:3, label:'正在加载会话'}});
console.log(JSON.stringify({{
  activityRows:(activity.match(/data-skeleton-row=/g)||[]).length,
  boundedRows:(bounded.match(/data-skeleton-row=/g)||[]).length,
  escaped:bounded.includes('&lt;loading&gt;'),
  activityRole:activity.includes('role="status"'),
  chatVariant:chat.includes('ui-loading-skeleton--chat'),
}}));
"""
        completed = subprocess.run(
            ["node", "-e", probe],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["activityRows"], 3)
        self.assertEqual(result["boundedRows"], 8)
        self.assertTrue(result["escaped"])
        self.assertTrue(result["activityRole"])
        self.assertTrue(result["chatVariant"])

    def test_shared_assets_are_loaded_before_page_consumers(self):
        app_html = APP_HTML.read_text(encoding="utf-8")
        admin_html = ADMIN_HTML.read_text(encoding="utf-8")
        self.assertIn("/static/shared/loading-ui.css", app_html)
        self.assertIn("/static/shared/loading-ui.css", admin_html)
        self.assertLess(app_html.index("/static/shared/loading-ui.js"), app_html.index("index3-settings-models-ui.js"))
        self.assertLess(admin_html.index("/static/shared/loading-ui.js"), admin_html.index("platform-admin.js"))

    def test_activity_skeleton_never_replaces_real_stream_events(self):
        source = ACTIVITY_JS.read_text(encoding="utf-8")
        self.assertIn("if(context?.streaming)", source)
        self.assertIn("_activityPanelRenderSkeleton(body, 'activity', 3)", source)
        self.assertIn("context?.streaming && itemState === 'active' && !hasPendingDetail", source)
        self.assertIn("const visibleItems = _activityPanelVisibleItemsForRender", source)
        self.assertLess(
            source.index("const visibleItems = _activityPanelVisibleItemsForRender", source.index("function _activityRenderItems")),
            source.index("_activityPanelRenderSkeleton(body, 'activity', 3)"),
        )

    def test_frontend_loading_branches_use_shared_skeletons(self):
        chat = CHAT_JS.read_text(encoding="utf-8")
        model = MODEL_JS.read_text(encoding="utf-8")
        memory = MEMORY_JS.read_text(encoding="utf-8")
        composer = COMPOSER_LIBRARY_JS.read_text(encoding="utf-8")
        knowledge = KNOWLEDGE_JS.read_text(encoding="utf-8")
        self.assertIn("variant:'chat'", chat)
        self.assertIn("variant:'compact-list', rows:5", model)
        self.assertIn("memory.history_loading", memory)
        self.assertIn("composer.library.loading", composer)
        self.assertIn("library.kb.search_loading", knowledge)
        self.assertIn("AppLoadingUi.ready", knowledge)

    def test_admin_lists_have_loading_and_error_transitions(self):
        source = ADMIN_JS.read_text(encoding="utf-8")
        self.assertIn("function withAdminListLoading", source)
        self.assertIn("admin.platform.load_failed", source)
        for element_id in (
            "accountList",
            "registryFiles",
            "orphanFiles",
            "kbDocs",
            "recycleFiles",
            "auditList",
            "backupList",
        ):
            self.assertIn(f"'{element_id}'", source)

    def test_shimmer_respects_reduced_motion(self):
        css = LOADING_CSS.read_text(encoding="utf-8")
        self.assertIn("@media (prefers-reduced-motion:reduce)", css)
        self.assertIn("animation:none", css)


if __name__ == "__main__":
    unittest.main()
