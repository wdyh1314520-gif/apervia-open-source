from __future__ import annotations

import ast
import json
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILE_LIBRARY_BACKEND = ROOT / "app3_parts" / "knowledge" / "file_library_part.py"
KB_IMPORT_BACKEND = ROOT / "app3_parts" / "knowledge" / "knowledge_document_import_part.py"
KB_SEARCH_BACKEND = ROOT / "app3_parts" / "knowledge" / "knowledge_search_part.py"
KB_UI_JS = ROOT / "static" / "index3" / "js" / "index3-knowledge-base-ui.js"
APP_UI_JS = ROOT / "static" / "index3" / "js" / "index3.js"
SESSION_ROUTING_UI_JS = ROOT / "static" / "index3" / "js" / "index3-session-routing.js"
KB_UI_CSS = ROOT / "static" / "index3" / "css" / "index3-knowledge-base.css"
ASYNC_UI_JS = ROOT / "static" / "index3" / "js" / "index3-async-chat-stream-ui.js"
PULLBACK_UI_JS = ROOT / "static" / "index3" / "js" / "index3-image-pullback-ui.js"
MOBILE_UI_JS = ROOT / "static" / "index3" / "js" / "index3-mobile-shell-ui.js"
APP_HTML = ROOT / "static" / "index3.html"
SIDEBAR_MEDIA_CSS = ROOT / "static" / "index3" / "css" / "index3-sidebar-media.css"
STATIC_ROUTES = ROOT / "app3_parts" / "platform" / "platform_static_file_routes_part.py"


def _load_backend_functions(names: set[str]):
    source = FILE_LIBRARY_BACKEND.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FILE_LIBRARY_BACKEND))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if "_FILE_LIBRARY_IMAGE_EXTS" in targets:
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in names:
            nodes.append(node)
    namespace = {"__builtins__": __builtins__, "os": os}
    module = ast.Module(body=nodes, type_ignores=[])
    exec(compile(module, str(FILE_LIBRARY_BACKEND), "exec"), namespace)
    return namespace


class KnowledgeLibraryUiTests(unittest.TestCase):
    def test_library_is_workspace_page_not_overlay_dialog(self):
        js = KB_UI_JS.read_text(encoding="utf-8")
        css = KB_UI_CSS.read_text(encoding="utf-8")
        mask_rule = css.split(".kb-modal-mask{", 1)[1].split("}", 1)[0]
        self.assertIn("library-page-open", css)
        self.assertIn("position:relative", mask_rule)
        self.assertNotIn("position:fixed", mask_rule)
        self.assertIn("(workspace || document.body).appendChild(modal)", js)
        self.assertIn('role="region" aria-label="资料库"', js)
        self.assertNotIn('aria-modal="true" aria-label="知识库与文件库"', js)

    def test_library_uses_independent_query_routes(self):
        app_ui = SESSION_ROUTING_UI_JS.read_text(encoding="utf-8")
        library_ui = KB_UI_JS.read_text(encoding="utf-8")
        css = KB_UI_CSS.read_text(encoding="utf-8")
        routes = STATIC_ROUTES.read_text(encoding="utf-8")
        self.assertIn("return '/library?tab=' + encodeURIComponent(slug)", app_ui)
        self.assertIn("function getRouteLibraryFileType", app_ui)
        self.assertIn("function syncLibraryRoute", app_ui)
        self.assertIn("webaiLibraryOpen:true", app_ui)
        self.assertNotIn("syncModalRoute('library'", app_ui)
        self.assertNotIn("return '#library/' + encodeURIComponent(normalized)", app_ui)
        self.assertIn('@app.get("/library")', routes)
        for route_tab in ("all", "images", "files", "knowledge"):
            self.assertIn(f'data-library-route-tab="{route_tab}"', library_ui)
        self.assertNotIn("data-filelib-type", library_ui)
        self.assertNotIn("返回聊天", library_ui)
        self.assertIn(".app > .main.library-page-open > .topbar", css)
        self.assertIn(".app > .main.library-page-open > .composer", css)

    def test_removed_dead_auto_import_setting(self):
        ui = KB_UI_JS.read_text(encoding="utf-8")
        request_ui = ASYNC_UI_JS.read_text(encoding="utf-8")
        self.assertNotIn("autoImportUploads", ui)
        self.assertNotIn("autoImportUploads", request_ui)
        self.assertNotIn("kbAutoImportToggle", ui)

    def test_library_sections_and_pullback_navigation_are_exclusive(self):
        library_ui = KB_UI_JS.read_text(encoding="utf-8")
        pullback_ui = PULLBACK_UI_JS.read_text(encoding="utf-8")
        self.assertIn('data-library-section-tab="files"', library_ui)
        self.assertIn('data-library-section-tab="knowledge"', library_ui)
        self.assertNotIn('id="kbBackToChatBtn"', library_ui)
        self.assertIn('id="kbSidebarToggleBtn"', library_ui)
        self.assertIn("applySidebarCollapsed(false)", library_ui)
        self.assertNotIn('用户上传</span><span>助手生成', library_ui)
        self.assertIn('集中管理全部文件。', library_ui)
        self.assertIn("classList.toggle('is-active', visible)", library_ui)
        self.assertIn("classList.toggle('library-open', visible)", library_ui)
        self.assertIn("window.closeImagePullbackWorkspace", library_ui)
        self.assertIn("#workspace > :not(#kbModalMask)", library_ui)
        self.assertIn("if(kbActiveLibraryTab() === 'files') await fileLibraryLoadState", library_ui)
        self.assertIn('data-filelib-menu="${fileId}"', library_ui)
        self.assertIn('class="filelib-row-menu"', library_ui)
        self.assertIn("fileLibraryPositionRowMenu(wrap)", library_ui)
        self.assertIn("document.addEventListener('scroll', ()=> fileLibraryCloseRowMenus(), true)", library_ui)
        self.assertIn("openImagePullbackRoute()", pullback_ui)
        library_css = KB_UI_CSS.read_text(encoding="utf-8")
        self.assertIn("body.library-open .item.ow-chat-item.active", library_css)
        self.assertIn("body.library-open::after", library_css)
        self.assertIn("body.library-open .composer", library_css)
        self.assertIn("body.library-open #workspace > :not(#kbModalMask)", library_css)
        self.assertIn("body.sidebar-collapsed.library-open .kb-sidebar-toggle", library_css)
        self.assertNotIn("body.library-open #chatList", library_css)
        self.assertNotIn("body.library-open #chatSectionToggle", library_css)

    def test_library_and_pullback_close_mobile_sidebar_through_shared_navigation_helper(self):
        app_ui = SESSION_ROUTING_UI_JS.read_text(encoding="utf-8")
        mobile_ui = MOBILE_UI_JS.read_text(encoding="utf-8")
        self.assertIn("function closeMobileSidebarAfterNavigation()", mobile_ui)
        self.assertIn("window.closeMobileSidebarAfterNavigation = closeMobileSidebarAfterNavigation", mobile_ui)
        self.assertGreaterEqual(app_ui.count("window.closeMobileSidebarAfterNavigation?.()"), 2)
        self.assertIn("function openLibraryRoute", app_ui)
        self.assertIn("function openImagePullbackRoute", app_ui)

        helper_end = mobile_ui.index(
            "window.closeMobileSidebarAfterNavigation = closeMobileSidebarAfterNavigation;"
        ) + len("window.closeMobileSidebarAfterNavigation = closeMobileSidebarAfterNavigation;")
        probe = """
const calls = [];
global.window = {innerWidth: 500};
function applySidebarCollapsed(...args){ calls.push(args); }
""" + mobile_ui[:helper_end] + """
const mobileResult = closeMobileSidebarAfterNavigation();
window.innerWidth = 1200;
const desktopResult = closeMobileSidebarAfterNavigation();
console.log(JSON.stringify({mobileResult, desktopResult, calls}));
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
        self.assertTrue(result["mobileResult"])
        self.assertFalse(result["desktopResult"])
        self.assertEqual(result["calls"], [[True, False]])

    def test_image_pullback_uses_independent_workspace_route(self):
        app_ui = SESSION_ROUTING_UI_JS.read_text(encoding="utf-8")
        pullback_ui = PULLBACK_UI_JS.read_text(encoding="utf-8")
        html = APP_HTML.read_text(encoding="utf-8")
        css = SIDEBAR_MEDIA_CSS.read_text(encoding="utf-8")
        routes = STATIC_ROUTES.read_text(encoding="utf-8")
        self.assertIn('@app.get("/image-pullback")', routes)
        self.assertIn("function isImagePullbackRoute", app_ui)
        self.assertIn("return '/image-pullback'", app_ui)
        self.assertIn("function syncImagePullbackRoute", app_ui)
        self.assertIn("function openImagePullbackRoute", app_ui)
        self.assertIn("function closeImagePullbackRoute", app_ui)
        self.assertIn("isModalRoute(href) || isLibraryRoute(href) || isImagePullbackRoute(href)", app_ui)
        self.assertIn("openImagePullbackRoute()", pullback_ui)
        self.assertIn("data-pullback-prev-inert", pullback_ui)
        self.assertIn('id="imagePullbackSidebarToggleBtn"', html)
        self.assertNotIn('id="imagePullbackBackBtn"', html)
        self.assertIn('role="region" aria-labelledby="imagePullbackTitle"', html)
        self.assertNotIn('role="dialog" aria-modal="true" aria-labelledby="imagePullbackTitle"', html)
        self.assertIn("body.pullback-open #workspace > :not(#imagePullbackWorkspace)", css)
        self.assertIn("body.sidebar-collapsed.pullback-open .pullback-sidebar-toggle", css)
        self.assertIn("position:relative", css.split(".pullback-modal-mask{", 1)[1].split("}", 1)[0])

    def test_backend_blocks_images_before_text_reader(self):
        names = {
            "_file_library_ext",
            "_file_library_category",
            "_file_library_kb_importable",
            "_file_library_import_to_kb",
        }
        ns = _load_backend_functions(names)
        calls = []
        ns.update({
            "_file_library_owner_key": lambda _owner=None: "user@example.com",
            "_file_library_get_record": lambda *_args: {"file_id": "img-1", "filename": "photo.png", "ext": ".png"},
            "_history_file_read_text": lambda *_args: calls.append("reader") or "ocr text",
        })
        with self.assertRaisesRegex(ValueError, "图片文件只保留在资料库"):
            ns["_file_library_import_to_kb"]("img-1")
        self.assertEqual(calls, [])

    def test_batch_import_endpoint_logic_reports_images_as_skipped_failures(self):
        names = {
            "_file_library_ext",
            "_file_library_category",
            "_file_library_kb_importable",
            "_file_library_import_to_kb",
            "_file_library_normalize_ids",
            "_file_library_batch_import_to_kb",
        }
        ns = _load_backend_functions(names)
        records = {
            "img-1": {"file_id": "img-1", "filename": "photo.webp", "ext": ".webp"},
            "doc-1": {"file_id": "doc-1", "filename": "guide.pdf", "ext": ".pdf", "size": 20},
        }
        ns.update({
            "_file_library_owner_key": lambda _owner=None: "user@example.com",
            "_file_library_get_record": lambda file_id, _owner=None: records.get(file_id, {}),
            "_history_file_read_text": lambda rec: "guide text" if rec.get("file_id") == "doc-1" else "ocr text",
            "_file_registry_record_text_by_id": lambda _fid: "",
            "_file_library_resolve_local_path": lambda _rec: "",
            "_kb_import_document": lambda **_kwargs: {"ok": True, "document": {"id": "doc-kb-1"}},
            "_file_library_public_record": lambda rec, owner_key=None: dict(rec),
            "_file_library_state": lambda _owner=None: {"files": []},
            "_kb_state": lambda owner_key=None, space_id="": {"documents": [{"id": "doc-kb-1"}]},
        })
        result = ns["_file_library_batch_import_to_kb"](["img-1", "doc-1", "img-1"], "space-1")
        self.assertEqual(result["requested"], 2)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertIn("图片文件只保留在资料库", result["results"][0]["error"])

    def test_core_import_and_search_share_image_exclusion(self):
        import_source = KB_IMPORT_BACKEND.read_text(encoding="utf-8")
        search_source = KB_SEARCH_BACKEND.read_text(encoding="utf-8")
        ui_source = KB_UI_JS.read_text(encoding="utf-8")
        backend_source = FILE_LIBRARY_BACKEND.read_text(encoding="utf-8")
        self.assertIn("_KB_IMAGE_EXTENSIONS", import_source)
        self.assertIn("图片文件只保留在资料库，不能加入知识库", import_source)
        self.assertIn("_kb_sql_non_image_clause('d.ext')", search_source)
        self.assertIn("/api3/file-library/batch-import-to-kb", backend_source)
        self.assertIn("fileLibraryKnowledgeImportable", ui_source)
        self.assertIn("kbT('library.image_not_indexed'", ui_source)


if __name__ == "__main__":
    unittest.main()
