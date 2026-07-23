import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MESSAGE_MEDIA_JS = ROOT / "static" / "index3" / "js" / "index3-message-media-render-ui.js"


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


class AssistantGeneratedFileUiTests(unittest.TestCase):
    def test_inline_managed_download_suppresses_fallback_file_cards(self):
        source = MESSAGE_MEDIA_JS.read_text(encoding="utf-8")
        self.assertIn(
            "assistantGeneratedFilesForFallbackCards(assistantGeneratedFiles",
            source,
        )
        helper = extract_javascript_function(
            source, "assistantGeneratedFilesForFallbackCards"
        )
        probe = """
const files = [{filename:'python_example.zip'}, {filename:'python_example-v2.py'}];
const linkedAnswer = {querySelector(selector){
  return selector === 'a[data-webai-managed-download="1"]' ? {href:'/download'} : null;
}};
const plainAnswer = {querySelector(){ return null; }};
console.log(JSON.stringify({
  linked: assistantGeneratedFilesForFallbackCards(files, linkedAnswer),
  plain: assistantGeneratedFilesForFallbackCards(files, plainAnswer),
  missingAnswer: assistantGeneratedFilesForFallbackCards(files, null),
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
        self.assertEqual(result["linked"], [])
        self.assertEqual(result["plain"], [
            {"filename": "python_example.zip"},
            {"filename": "python_example-v2.py"},
        ])
        self.assertEqual(result["missingAnswer"], result["plain"])


if __name__ == "__main__":
    unittest.main()
