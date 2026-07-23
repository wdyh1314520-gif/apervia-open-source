import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVITY_UI_JS = ROOT / "static" / "index3" / "js" / "index3-activity-panel-ui.js"
REASONING_UI_JS = ROOT / "static" / "index3" / "js" / "index3-shared-render-reasoning.js"
OVERRIDES_CSS = ROOT / "static" / "index3" / "css" / "index3-overrides.css"
INDEX_HTML = ROOT / "static" / "index3.html"


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


class ActivityPanelStreamingUiTests(unittest.TestCase):
    def test_activity_events_refresh_immediately(self):
        source = REASONING_UI_JS.read_text(encoding="utf-8")
        helper = extract_javascript_function(source, "_reasoningMetaPanelRefreshOpts")
        probe = """
console.log(JSON.stringify({
  active: _reasoningMetaPanelRefreshOpts(true, false),
  terminal: _reasoningMetaPanelRefreshOpts(true, true),
  aggregate: _reasoningMetaPanelRefreshOpts(false, false),
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
            result["active"],
            {"immediate": True, "terminal": False, "activityStream": True},
        )
        self.assertEqual(
            result["terminal"],
            {"immediate": True, "terminal": True, "activityStream": True},
        )
        self.assertEqual(
            result["aggregate"],
            {"throttleMs": 520, "terminal": False, "immediate": False},
        )

    def test_activity_items_have_no_stagger_delay(self):
        source = ACTIVITY_UI_JS.read_text(encoding="utf-8")
        functions = "\n".join([
            extract_javascript_function(source, "_activityPanelStableVisualKey"),
            extract_javascript_function(source, "_activityPanelMarkEnter"),
        ])
        probe = """
let _activityPanelVisualRunKey = 'run-1';
let _activityPanelSeenVisualKeys = new Set();
const classes = [];
const styles = {};
const el = {
  classList:{add(value){ classes.push(value); }},
  style:{setProperty(key, value){ styles[key] = value; }},
};
const entered = _activityPanelMarkEnter(el, 'event-1', 7, {stepMs:55, maxDelayMs:360});
console.log(JSON.stringify({entered, classes, styles}));
"""
        completed = subprocess.run(
            ["node", "-e", functions + probe],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result["entered"])
        self.assertIn("activity-panel-enter", result["classes"])
        self.assertEqual(result["styles"]["--activity-enter-delay"], "0ms")

    def test_timeline_rail_has_no_extra_delay(self):
        css = OVERRIDES_CSS.read_text(encoding="utf-8")
        self.assertNotIn("calc(var(--activity-enter-delay, 0ms) + 70ms)", css)
        self.assertIn("animation-delay:var(--activity-enter-delay, 0ms)", css)

    def test_streaming_panel_keeps_current_real_activity_visible(self):
        source = ACTIVITY_UI_JS.read_text(encoding="utf-8")
        functions = "\n".join([
            extract_javascript_function(source, "_activityIsGenericCompletionItem"),
            extract_javascript_function(source, "_activityIsRealPanelItem"),
            extract_javascript_function(source, "_activityPanelItemHasSettled"),
            extract_javascript_function(source, "_activityPanelItemEndedByLaterEvent"),
            extract_javascript_function(source, "_activityPanelVisibleItemsForRender"),
        ])
        probe = """
function _activityLooksNativeReasoningItem(){ return false; }
const visible = _activityPanelVisibleItemsForRender([
  {key:'active-search', title:'正在搜索网页', stage:'search', state:'active'},
  {key:'placeholder', title:'正在思考中', stage:'think', state:'active', transient:true},
  {key:'unmarked-placeholder', title:'正在思考中', detail:'正在思考中', stage:'think', state:'active'},
  {key:'done-read', title:'网页读取完成', stage:'search', state:'done'},
], {streaming:true});
const historical = _activityPanelVisibleItemsForRender([
  {key:'placeholder', title:'正在思考中', stage:'think', state:'done', transient:true},
  {key:'unmarked-placeholder', title:'正在思考中', detail:'正在思考中', stage:'think', state:'done'},
  {key:'done-read', title:'网页读取完成', stage:'search', state:'done'},
], {streaming:false});
console.log(JSON.stringify({
  visible:visible.map(item => [item.key, item.state]),
  historical:historical.map(item => [item.key, item.state]),
}));
"""
        completed = subprocess.run(
            ["node", "-e", functions + probe],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["visible"], [["active-search", "active"], ["done-read", "done"]])
        self.assertEqual(result["historical"], [["done-read", "done"]])

    def test_streaming_panel_uses_skeleton_only_for_missing_activity_content(self):
        source = ACTIVITY_UI_JS.read_text(encoding="utf-8")
        self.assertIn("waitingForFirstActivity", source)
        self.assertIn("_activityPanelRenderSkeleton(body, 'activity', 3)", source)
        self.assertIn("itemState === 'active' && !hasPendingDetail", source)
        self.assertIn("AppLoadingUi.ready(body)", source)

    def test_streaming_placeholder_opens_skeleton_panel_without_becoming_activity(self):
        source = ACTIVITY_UI_JS.read_text(encoding="utf-8")
        open_function = extract_javascript_function(source, "openActivityPanelForMessage")
        probe = """
let _activityPanelOpenSessionId = '';
let _activityPanelTargetMessage = null;
let _activityPanelTargetSnapshot = {items:[]};
let hiddenCount = 0;
let refreshCount = 0;
function _activityCurrentSessionId(){ return 'session-1'; }
function ensureSessionRuntime(){ return {streaming:true}; }
function _activityPanelHasOpenableRealActivity(){ return false; }
function _activityPanelIsExplicitlyOpenForSession(){ return true; }
function hideActivityPanelForVisibleSession(){
  hiddenCount += 1;
  _activityPanelOpenSessionId = '';
  _activityPanelTargetMessage = null;
  _activityPanelTargetSnapshot = null;
}
function refreshActivityPanelForVisibleSession(){ refreshCount += 1; }
openActivityPanelForMessage('session-1', {role:'assistant'}, {reasoningSnapshot:{items:[]}});
console.log(JSON.stringify({
  openSessionId:_activityPanelOpenSessionId,
  hiddenCount,
  refreshCount,
  targetMessage:_activityPanelTargetMessage,
  targetSnapshot:_activityPanelTargetSnapshot,
}));
"""
        completed = subprocess.run(
            ["node", "-e", open_function + probe],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["openSessionId"], "session-1")
        self.assertEqual(result["hiddenCount"], 0)
        self.assertEqual(result["refreshCount"], 1)
        self.assertIsNone(result["targetMessage"])
        self.assertIsNone(result["targetSnapshot"])
        self.assertIn("const shouldHide = (!hasActivity && !waitingForFirstActivity) || !_activityPanelIsExplicitlyOpenForSession(sid) || homeView;", source)

    def test_activity_panel_uses_full_height_desktop_split_layout(self):
        css = OVERRIDES_CSS.read_text(encoding="utf-8")
        self.assertIn("--activity-panel-width:clamp(380px, 26vw, 520px)", css)
        self.assertIn("--activity-marker-bg:var(--bg)", css)
        self.assertNotIn("--activity-marker-bg:color-mix", css)
        self.assertIn("height:calc(100% + var(--gpt-topbar-h, 56px))", css)
        self.assertIn("margin-top:calc(-1 * var(--gpt-topbar-h, 56px))", css)
        self.assertIn(".main.activity-panel-open > .topbar{margin-right:var(--active-activity-panel-reserve, 0px);}", css)

    def test_activity_panel_has_section_heading_and_svg_close_icon(self):
        source = ACTIVITY_UI_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn("activity-panel-section-heading", source)
        self.assertIn("heading.textContent = _activityT('activity.thinking'", source)
        self.assertIn('aria-labelledby="activityPanelTitle"', html)
        self.assertIn('id="activityPanelClose"', html)
        self.assertIn('d="M18 6 6 18M6 6l12 12"', html)

    def test_sandbox_code_cards_match_compact_reference_style(self):
        css = OVERRIDES_CSS.read_text(encoding="utf-8")
        command = css.split(".activity-panel-sandbox-command-card{", 1)[1].split("}", 1)[0]
        self.assertIn("border-radius:26px", command)
        self.assertIn("background:#f3f3f3", command)
        self.assertIn("border:0", css.split(".activity-panel-code-block{", 1)[1].split("}", 1)[0])
        self.assertIn("border-bottom:0", css.split(".activity-panel-code-head{", 1)[1].split("}", 1)[0])
        self.assertNotIn(".activity-panel-sandbox-command-card .activity-panel-code-scroll code{color:", css)
        self.assertIn(".activity-panel-sandbox-output-card .activity-panel-code-head", css)
        self.assertIn(".activity-panel-sandbox-error-card .activity-panel-code-head{display:none;}", css)
        output = css.split(".activity-panel-sandbox-output-card,", 1)[1].split("}", 1)[0]
        self.assertIn("background:#f9f9f9", output)
        self.assertIn(".activity-panel-code-scroll::-webkit-scrollbar{width:14px;height:14px;}", css)
        self.assertIn("::-webkit-scrollbar-button{display:block;width:16px;height:16px", css)
        self.assertIn("min-width:80px", css)
        self.assertIn("background:#8b8b8b", css)
        self.assertIn("background:#d6d6d6", css)
        self.assertIn("background:#5a5a5a", css)
        self.assertIn("::-webkit-scrollbar-button:horizontal{display:none;}", css)
        self.assertIn("::-webkit-scrollbar-button:horizontal:decrement:start{display:block", css)
        self.assertIn("::-webkit-scrollbar-button:horizontal:increment:end{display:block", css)
        self.assertNotIn("::-webkit-scrollbar-button:horizontal:increment:start{display:block", css)
        self.assertNotIn("::-webkit-scrollbar-button:horizontal:decrement:end{display:block", css)
        self.assertIn("::-webkit-scrollbar-button:vertical:increment", css)
        self.assertIn("white-space:pre-wrap", css)

        source = ACTIVITY_UI_JS.read_text(encoding="utf-8")
        self.assertIn("typeof highlightCode === 'function'", source)
        self.assertIn("code.innerHTML = highlightCode(raw, language)", source)
        self.assertIn("const invokesPython =", source)
        self.assertIn("isShell && !invokesPython ? 'Shell' : 'Python'", source)


if __name__ == "__main__":
    unittest.main()
