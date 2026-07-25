import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TITLE_UI_JS = ROOT / "static" / "index3" / "js" / "index3-shared-render-reasoning.js"


def extract_javascript_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    if source[max(0, start - 6):start] == "async ":
        start -= 6
    body_start = source.index("{", source.index(")", start))
    depth = 0
    for index in range(body_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"JavaScript function is not closed: {name}")


class SessionTitleLanguageTests(unittest.TestCase):
    def test_title_prompt_follows_conversation_then_interface_language(self):
        source = TITLE_UI_JS.read_text(encoding="utf-8")
        functions = "\n".join([
            extract_javascript_function(source, "sessionTitleInterfaceLanguageName"),
            extract_javascript_function(source, "fetchTitleByAI"),
        ])
        probe = """
global.document = {documentElement:{lang:'en'}};
global.window = {AperviaI18n:{language:'en'}};
const DEFAULT_MODEL = 'test-model';
function getRequestSettings(){ return {}; }
function buildRuntimeTimePayload(){ return {}; }
function shouldPreferStableAsyncPollTransport(){ return false; }
const captured = [];
async function runAsyncPlainTextJob(body){ captured.push(body); return '{"title":"Caching behavior"}'; }
(async()=>{
  await fetchTitleByAI({firstUserText:'Why does prompt caching warm up slowly?', firstAssistantText:'It depends on stable prefixes.'}, DEFAULT_MODEL);
  window.AperviaI18n.language = 'zh-CN';
  await fetchTitleByAI({firstUserText:'???', firstAssistantText:'...'}, DEFAULT_MODEL);
  console.log(JSON.stringify(captured.map(item => item.messages[0].content)));
})().catch(error=>{ console.error(error); process.exit(1); });
"""
        completed = subprocess.run(
            ["node", "-e", functions + probe],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        prompts = json.loads(completed.stdout)
        self.assertIn("Use the primary language of the supplied conversation content", prompts[0])
        self.assertIn("current interface language: English", prompts[0])
        self.assertIn("current interface language: Simplified Chinese", prompts[1])
        self.assertNotIn("中文约 6-12 个汉字", prompts[0])

    def test_retry_instructions_do_not_force_chinese(self):
        source = TITLE_UI_JS.read_text(encoding="utf-8")
        retry_function = extract_javascript_function(source, "sessionTitleRetryHint")
        probe = """
console.log(JSON.stringify([
  sessionTitleRetryHint({reasons:['too_long']}),
  sessionTitleRetryHint({reasons:['question_tone']}),
]));
"""
        completed = subprocess.run(
            ["node", "-e", retry_function + probe],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        hints = json.loads(completed.stdout)
        self.assertTrue(all("previous title" in hint.lower() for hint in hints))
        self.assertTrue(all(not any("\u4e00" <= char <= "\u9fff" for char in hint) for hint in hints))


if __name__ == "__main__":
    unittest.main()
