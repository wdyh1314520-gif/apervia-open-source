import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDER_PATH = ROOT / 'static' / 'index3' / 'js' / 'index3-render-markdown-ui.js'
ACTIVITY_PATH = ROOT / 'static' / 'index3' / 'js' / 'index3-activity-panel-ui.js'
STYLE_PATH = ROOT / 'static' / 'index3' / 'css' / 'index3-overrides.css'
STREAM_SOURCES_PATH = ROOT / 'app3_parts' / 'chat' / 'chat_stream_sources_part.py'
FINAL_ANSWER_PATH = ROOT / 'app3_parts' / 'chat' / 'chat_final_answer_part.py'


class InlineSourceFaviconUnificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = RENDER_PATH.read_text(encoding='utf-8')
        cls.activity_source = ACTIVITY_PATH.read_text(encoding='utf-8')
        cls.styles = STYLE_PATH.read_text(encoding='utf-8')
        cls.stream_sources = STREAM_SOURCES_PATH.read_text(encoding='utf-8')
        cls.final_answer = FINAL_ANSWER_PATH.read_text(encoding='utf-8')

    def test_shared_candidate_chain_prefers_returned_favicon(self):
        block = self.source.split('function getAssistantSourceFaviconCandidates', 1)[1].split(
            'function getAssistantSourceFaviconUrl', 1
        )[0]
        supplied = block.index("push(item?.favicon || item?.icon")
        public_fallback = block.index('push(getAssistantSourceFallbackFaviconUrl')
        local_proxy = block.index('push(assistantInlineSourceFaviconUrlForHost')
        self.assertLess(supplied, public_fallback)
        self.assertLess(public_fallback, local_proxy)

    def test_inline_icons_are_hydrated_from_message_sources(self):
        inject = self.source.split('function injectAssistantSourcesIntoBubble', 1)[1].split(
            'const USER_GEO_CACHE_KEY', 1
        )[0]
        self.assertIn('assistantCitationSourceItemsByBubble.set(bubble, sourceItems)', inject)
        self.assertIn('syncAssistantInlineSourceIcons(bubble)', inject)

        sync = self.source.split('function syncAssistantInlineSourceIcons', 1)[1].split(
            'let activeAssistantInlineSourcePopover', 1
        )[0]
        self.assertIn('findAssistantInlineSourceItemForAnchor(anchor)', sync)
        self.assertIn('bindAssistantSourceFavicon(icon,', sync)

        message_sources = self.source.split('function getAssistantMessageSourceItems', 1)[1].split(
            'const FILE_CITATION_CONTEXT_EXTS', 1
        )[0]
        self.assertIn("typeof _activitySourcesFromSnapshot === 'function'", message_sources)
        self.assertIn('_activitySourcesFromSnapshot(raw)', message_sources)
        self.assertIn('hydrateAssistantSourceFavicons(sourceItems, activitySourceItems)', message_sources)

        merge = 'function mergeAssistantSourceItems' + self.source.split('function mergeAssistantSourceItems', 1)[1].split(
            'function extractAssistantSourceItemsFromText', 1
        )[0]
        self.assertIn('const faviconByKey = new Map()', merge)
        self.assertIn('faviconByKey.set(`url:', merge)
        self.assertIn('faviconByKey.set(`host:', merge)

    def test_late_activity_favicon_hydrates_an_existing_source(self):
        merge = 'function mergeAssistantSourceItems' + self.source.split('function mergeAssistantSourceItems', 1)[1].split(
            'function extractAssistantSourceItemsFromText', 1
        )[0]
        script = r'''
function trimUrl(value){ return String(value || '').trim(); }
function getAssistantSourceHost(value){ return new URL(value).hostname.replace(/^www\./i, '').toLowerCase(); }
function normalizeAssistantSourceItems(items){
  const seen = new Set();
  const out = [];
  for(const item of items || []){
    const key = String(item.url || '').toLowerCase();
    if(!key || seen.has(key)) continue;
    seen.add(key);
    out.push({sourceType:'web', title:item.title || item.host, url:item.url, host:item.host, favicon:item.favicon || ''});
  }
  return out;
}
const result = mergeAssistantSourceItems(
  [{title:'Example', url:'https://example.com/page', host:'example.com', favicon:''}],
  [{title:'Example', url:'https://example.com/page', host:'example.com', favicon:'https://cdn.example/icon.png'}]
);
console.log(JSON.stringify(result));
'''
        completed = subprocess.run(
            ['node', '-e', merge + script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result[0]['favicon'], 'https://cdn.example/icon.png')

    def test_inline_runtime_follows_activity_image_loading(self):
        markup = self.source.split('function buildInlineSourceCitationHtml', 1)[1].split(
            'function buildInlineSourceCitationFromBareHostHtml', 1
        )[0]
        self.assertNotIn('/api3/source-favicon', markup)

        bind = self.source.split('function bindAssistantSourceFavicon', 1)[1].split(
            'function getAssistantSourceIconFallback', 1
        )[0]
        self.assertIn("icon.classList.remove('has-image')", bind)
        self.assertIn("icon.classList.add('has-image')", bind)
        self.assertIn("iconImg.onload = ()=>icon.classList.add('has-image')", bind)
        self.assertIn("typeof _activityScheduleSourceIcon === 'function'", bind)
        self.assertIn('_activityScheduleSourceIcon(iconImg, favicon)', bind)
        self.assertNotIn('candidateIndex < candidates.length', bind)
        self.assertIn('.assistant-inline-source-icon .bubble-source-icon-fallback', self.styles)

    def test_popover_uses_the_same_icon_loader(self):
        block = self.source.split('function createAssistantInlineSourceIconNode', 1)[1].split(
            'function createAssistantInlineSourcePopover', 1
        )[0]
        self.assertIn('bindAssistantSourceFavicon(span, item)', block)
        self.assertNotIn('img.onerror', block)

    def test_activity_panel_keeps_the_canonical_image_loader(self):
        block = self.activity_source.split('function _activityRenderSourceChips', 1)[1].split(
            'function _activityRenderFileChips', 1
        )[0]
        self.assertIn("img.className = 'activity-panel-source-icon'", block)
        self.assertIn('_activityScheduleSourceIcon(img, favicon)', block)
        self.assertNotIn('bindAssistantSourceFavicon(', block)

    def test_backend_preserves_provider_favicon_for_final_sources(self):
        final_block = self.final_answer.split('def _visible_sources_from_result_rows', 1)[1].split(
            'def _collect_stage_visible_sources', 1
        )[0]
        self.assertIn("favicon = str(item.get('favicon')", final_block)
        self.assertIn("**({'favicon': favicon[:500]} if favicon else {})", final_block)

        push_block = self.stream_sources.split('def push_sources', 1)[1].split(
            'def visible_sources', 1
        )[0]
        self.assertIn("favicon: str = ''", push_block)
        self.assertIn("**({'favicon': str(favicon or '')[:500]}", push_block)


if __name__ == '__main__':
    unittest.main()
