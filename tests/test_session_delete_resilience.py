import ast
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPACTION_PATH = ROOT / 'app3_parts' / 'auth' / 'platform_auth_chat_compaction_part.py'
STORE_BACKEND_PATH = ROOT / 'app3_parts' / 'auth' / 'platform_auth_chat_store_part.py'
STORE_UI_PATH = ROOT / 'static' / 'index3' / 'js' / 'index3-store-cloud-sync.js'
STREAM_UI_PATH = ROOT / 'static' / 'index3' / 'js' / 'index3-stream-runtime-ui.js'
SIDEBAR_UI_PATH = ROOT / 'static' / 'index3' / 'js' / 'index3-sidebar-session-ui.js'
SETTINGS_UI_PATH = ROOT / 'static' / 'index3' / 'js' / 'index3-settings-data-ui.js'


def load_compaction_functions():
    tree = ast.parse(COMPACTION_PATH.read_text(encoding='utf-8'), filename=str(COMPACTION_PATH))
    names = {
        '_auth_chat_ms_from_ts',
        '_auth_chat_deleted_sessions_from_store',
        '_auth_chat_session_is_tombstoned_for_client',
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {
        'time': time,
        'AUTH_CHAT_SOFT_DELETE_RETENTION_S': 90 * 24 * 3600,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(COMPACTION_PATH), 'exec'), namespace)
    return namespace


class SessionDeleteResilienceTests(unittest.TestCase):
    def test_tombstone_blocks_writes_even_after_client_revision_catches_up(self):
        ns = load_compaction_functions()
        is_deleted = ns['_auth_chat_session_is_tombstoned_for_client']
        store = {
            '_deleted_sessions': {
                'session-1': {
                    'deleted_at': int(time.time() * 1000),
                    'server_revision': 12,
                },
            },
        }

        self.assertTrue(is_deleted(store, 'session-1', 0))
        self.assertTrue(is_deleted(store, 'session-1', 12))
        self.assertTrue(is_deleted(store, 'session-1', 999999))
        self.assertFalse(is_deleted(store, 'other-session', 999999))

    def test_all_mutating_sync_ops_use_the_tombstone_gate(self):
        source = STORE_BACKEND_PATH.read_text(encoding='utf-8')
        apply_sync_op = source.split('def _auth_chat_apply_sync_op', 1)[1].split(
            'def _auth_chat_build_sync_log_op', 1
        )[0]
        self.assertGreaterEqual(
            apply_sync_op.count('_auth_chat_session_is_tombstoned_for_client('),
            4,
        )

    def test_frontend_delete_is_local_first_and_retryable(self):
        source = STORE_UI_PATH.read_text(encoding='utf-8')
        delete_flow = source.split('async function deleteSessionsEverywhere', 1)[1].split(
            'function cloudSyncStableStringify', 1
        )[0]
        mark_at = delete_flow.index('markCloudSessionDeletedForSync(sid)')
        local_delete_at = delete_flow.index('delete store.sessions[sid]')
        push_at = delete_flow.index('await pushCloudSessionDeletesNow')

        self.assertLess(mark_at, local_delete_at)
        self.assertLess(local_delete_at, push_at)
        self.assertIn("stopStreamingForAction('delete_session', sid, { preserveDraft:false })", delete_flow)
        self.assertIn("requestCloudMessageRealtimeFlush('delete_session_retry'", delete_flow)

    def test_every_remote_store_or_session_ingress_honors_tombstones(self):
        source = STORE_UI_PATH.read_text(encoding='utf-8')
        merge = source.split('function cloudSyncMergeStorePreservingLiveLocal', 1)[1].split(
            'function normalizeComposerQuoteDraftForCloudApply', 1
        )[0]
        import_session = source.split('function importCloudSessionSnapshotIntoStore', 1)[1].split(
            'async function ensureCloudSessionLoadedIntoStore', 1
        )[0]
        apply_session = source.split('function applyCloudSessionSnapshotToStore', 1)[1].split(
            'function renderCloudSyncAppliedUi', 1
        )[0]
        sync_success = source.split('function applyCloudStoreSyncSuccess', 1)[1].split(
            'async function verifyCloudStoreSyncApplied', 1
        )[0]

        self.assertIn('applySessionDeleteTombstonesToStore(next, currentAccountEmail)', merge)
        self.assertIn('isSessionDeletedByTombstones(sid, currentAccountEmail', import_session)
        self.assertIn('isSessionDeletedByTombstones(sid, currentAccountEmail', apply_session)
        self.assertIn('applySessionDeleteTombstonesToStore(serverStore, currentAccountEmail', sync_success)

    def test_all_user_delete_surfaces_use_the_canonical_transaction(self):
        sidebar = SIDEBAR_UI_PATH.read_text(encoding='utf-8')
        settings = SETTINGS_UI_PATH.read_text(encoding='utf-8')
        stream = STREAM_UI_PATH.read_text(encoding='utf-8')

        self.assertIn('deleteSessionsEverywhere([s.id]', sidebar)
        self.assertNotIn('pushCloudSessionDeletesNow([s.id]', sidebar)
        self.assertGreaterEqual(settings.count('deleteSessionsEverywhere('), 2)
        self.assertNotIn('pushCloudSessionDeletesNow(', settings)
        self.assertIn('const preserveDraft = opts?.preserveDraft !== false;', stream)


if __name__ == '__main__':
    unittest.main()
