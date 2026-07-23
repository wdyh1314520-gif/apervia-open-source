import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_UI_JS = ROOT / "static" / "index3" / "js" / "index3-settings-ui.js"
MCP_SETTINGS_UI_JS = ROOT / "static" / "index3" / "js" / "index3-settings-mcp-ui.js"


def extract_javascript_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    body_start = source.index("{", start)
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


class McpSettingsScopeUiTests(unittest.TestCase):
    def test_server_directory_is_not_persisted_in_browser_storage(self):
        source = MCP_SETTINGS_UI_JS.read_text(encoding="utf-8")
        purge = extract_javascript_function(source, "purgeLegacyMcpBrowserStorage")
        remaining = source.replace(purge, "")
        self.assertIn('const prefix="webai_mcp_servers_v1"', purge)
        self.assertIn("localStorage.removeItem", purge)
        self.assertNotIn("localStorage", remaining)
        self.assertEqual(source.count("webai_mcp_servers_v1"), 1)
        self.assertIn('fetch("/api3/mcp/servers"', source)
        self.assertNotIn("mcp_servers:", source)

    def test_account_scope_restore_refreshes_developer_mode_toggle(self):
        settings_source = SETTINGS_UI_JS.read_text(encoding="utf-8")
        mcp_source = MCP_SETTINGS_UI_JS.read_text(encoding="utf-8")
        developer_mode_key = next(
            line for line in mcp_source.splitlines()
            if line.startswith("const MCP_DEVELOPER_MODE_KEY = ")
        )
        functions = "\n".join([
            developer_mode_key,
            extract_javascript_function(settings_source, "accountScopedSettingEmail"),
            extract_javascript_function(settings_source, "accountScopedSettingStorageKey"),
            extract_javascript_function(settings_source, "readAccountScopedSettingItem"),
            extract_javascript_function(settings_source, "refreshAccountScopedSecretSettingsUi"),
            extract_javascript_function(mcp_source, "isMcpDeveloperModeEnabled"),
            extract_javascript_function(mcp_source, "syncMcpDeveloperModeUi"),
        ])
        probe = r"""
const values = new Map([
  ['webai_mcp_developer_mode_v1::acct::user%40example.com', '1'],
]);
const toggle = {checked: null};
const addButton = {
  classList: {toggle(){}},
  setAttribute(){},
  title: '',
};
const localStorage = {getItem(key){ return values.has(key) ? values.get(key) : null; }};
const document = {getElementById(id){
  if(id === 'accountDeveloperModeToggle') return toggle;
  if(id === 'mcpNewBtn') return addButton;
  return null;
}};
let currentAccountEmail = '';
function normalizeAccountScopeEmail(value){ return String(value || '').trim().toLowerCase(); }
syncMcpDeveloperModeUi();
const beforeRestore = toggle.checked;
currentAccountEmail = 'User@Example.com';
refreshAccountScopedSecretSettingsUi('scope_switch');
console.log(JSON.stringify({beforeRestore, afterRestore: toggle.checked}));
"""
        completed = subprocess.run(
            ["node", "-e", functions + probe],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(
            json.loads(completed.stdout),
            {"beforeRestore": False, "afterRestore": True},
        )


if __name__ == "__main__":
    unittest.main()
