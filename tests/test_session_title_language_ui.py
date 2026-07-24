import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TITLE_UI_JS = ROOT / "static" / "index3" / "js" / "index3-shared-render-reasoning.js"
DIALOG_UI_JS = ROOT / "static" / "index3" / "js" / "index3-dialogs.js"
SIDEBAR_UI_JS = ROOT / "static" / "index3" / "js" / "index3-sidebar-session-ui.js"
SHARE_UI_JS = ROOT / "static" / "index3" / "js" / "index3-share-ui.js"
INDEX_HTML = ROOT / "static" / "index3.html"


def extract_javascript_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    async_prefix = source[max(0, start - 6):start]
    if async_prefix == "async ":
        start -= 6
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


class SessionTitleLanguageUiTests(unittest.TestCase):
    def test_default_session_title_uses_the_active_interface_language_everywhere(self):
        source = TITLE_UI_JS.read_text(encoding="utf-8")
        helpers = "\n".join(
            extract_javascript_function(source, name)
            for name in ("reasoningUiT", "isDefaultSessionTitle", "sessionDisplayTitle")
        )
        probe = r"""
global.window = {
  AperviaI18n:{
    language:'en',
    t(key){
      if(key !== 'nav.new_session') return key;
      return this.language === 'zh-CN' ? '新会话' : 'New conversation';
    },
  },
};
const english = ['新会话', '新对话', 'New chat', ''].map(sessionDisplayTitle);
window.AperviaI18n.language = 'zh-CN';
const chinese = ['新会话', 'New conversation'].map(sessionDisplayTitle);
console.log(JSON.stringify({english, chinese, custom:sessionDisplayTitle('Docker cache fix')}));
"""
        completed = subprocess.run(
            ["node", "-e", helpers + probe],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["english"], ["New conversation"] * 4)
        self.assertEqual(result["chinese"], ["新会话"] * 2)
        self.assertEqual(result["custom"], "Docker cache fix")

        dialog_source = DIALOG_UI_JS.read_text(encoding="utf-8")
        sidebar_source = SIDEBAR_UI_JS.read_text(encoding="utf-8")
        share_source = SHARE_UI_JS.read_text(encoding="utf-8")
        html_source = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn("sessionDisplayTitle(session?.title)", dialog_source)
        self.assertNotIn("function sidebarSessionDisplayTitle", sidebar_source)
        self.assertNotIn("function chatShareDisplayTitle", share_source)
        self.assertLess(
            html_source.index("index3-shared-render-reasoning.js"),
            html_source.index("index3-dialogs.js"),
        )

    def test_title_length_validation_supports_english_and_cjk(self):
        source = TITLE_UI_JS.read_text(encoding="utf-8")
        names = [
            "sessionTitleCharUnits",
            "sessionTitleDisplayUnits",
            "sessionTitleCompactLength",
            "sessionTitleUsesCjkLength",
            "sessionTitleWordCount",
            "sessionTitleLooksMeaningful",
            "sessionTitleTrimTail",
            "sessionTitleNormalize",
            "sessionTitleHasQuestionTone",
            "sessionTitleHasTruncatedFeel",
            "sessionTitleHasMetaLeak",
            "sessionTitleValidateCandidate",
        ]
        helpers = "\n".join(extract_javascript_function(source, name) for name in names)
        probe = r"""
const SESSION_TITLE_MIN_DISPLAY_UNITS = 12;
const SESSION_TITLE_MAX_DISPLAY_UNITS = 24;
const SESSION_TITLE_OTHER_MIN_DISPLAY_UNITS = 8;
const SESSION_TITLE_OTHER_MAX_DISPLAY_UNITS = 64;
const SESSION_TITLE_OTHER_MAX_WORDS = 9;
const SESSION_TITLE_MIN_MEANINGFUL_COMPACT_CHARS = 3;
console.log(JSON.stringify({
  english:sessionTitleValidateCandidate('Docker Authentication Troubleshooting'),
  chinese:sessionTitleValidateCandidate('Docker 登录问题修复'),
  question:sessionTitleValidateCandidate('How to Fix Docker'),
  longEnglish:sessionTitleValidateCandidate('One two three four five six seven eight nine ten'),
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
        result = json.loads(completed.stdout)
        self.assertTrue(result["english"]["ok"])
        self.assertTrue(result["chinese"]["ok"])
        self.assertIn("question_tone", result["question"]["reasons"])
        self.assertIn("too_long", result["longEnglish"]["reasons"])

    def test_title_prompt_follows_conversation_then_interface_fallback(self):
        source = TITLE_UI_JS.read_text(encoding="utf-8")
        helper = extract_javascript_function(source, "fetchTitleByAI")
        probe = r"""
global.window = {AperviaI18n:{language:'en'}};
const DEFAULT_MODEL = 'test-model';
function getRequestSettings(){ return {}; }
function buildRuntimeTimePayload(){ return {}; }
function shouldPreferStableAsyncPollTransport(){ return false; }
async function runAsyncPlainTextJob(body){ return body; }
(async()=>{
  const english = await fetchTitleByAI({firstUserText:'Fix Docker login', firstAssistantText:'Updated the authentication flow'}, 'test-model', {attempt:1, previousTitle:'Old title', retryHint:'Try again'});
  window.AperviaI18n.language = 'zh-CN';
  const chineseFallback = await fetchTitleByAI({firstUserText:'123', firstAssistantText:'456'}, 'test-model');
  console.log(JSON.stringify({
    englishSystem:english.messages[0].content,
    englishUser:english.messages[1].content,
    chineseSystem:chineseFallback.messages[0].content,
  }));
})().catch(error=>{ console.error(error); process.exitCode=1; });
"""
        completed = subprocess.run(
            ["node", "-e", helper + probe],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if completed.returncode != 0:
            self.fail(completed.stderr)
        result = json.loads(completed.stdout)
        self.assertIn("dominant language of the conversation", result["englishSystem"])
        self.assertIn("interface fallback language: English", result["englishSystem"])
        self.assertIn("interface fallback language: Simplified Chinese", result["chineseSystem"])
        self.assertNotIn("中文约 6-12 个汉字", result["englishSystem"])
        self.assertIn("Previous candidate: Old title", result["englishUser"])


if __name__ == "__main__":
    unittest.main()
