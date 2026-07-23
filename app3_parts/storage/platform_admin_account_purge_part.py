# Split from app3_parts/storage/storage_quota_part.py.
# Purpose: irreversible, admin-only removal of unregistered guest-owned data.
# Loaded after inventory/audit helpers so the service can reuse the established storage boundaries.

_PLATFORM_ADMIN_GUEST_PURGE_LOCK = threading.Lock()
_PLATFORM_ADMIN_GUEST_PURGE_OWNERS: set[str] = set()


class PlatformAdminGuestPurgeService:
    """集中清理未注册游客数据；真实注册账号必须走用户自助注销。"""

    def __init__(self, email: str):
        self.email = _storage_quota_norm_owner(email or '')
        self.fingerprint = hashlib.sha256(self.email.encode('utf-8', errors='ignore')).hexdigest()[:16] if self.email else ''

    def _auth_user(self) -> dict:
        getter = globals().get('_auth_get_user')
        return dict(getter(self.email) or {}) if callable(getter) else {}

    def validate_target(self) -> dict:
        if not self.email:
            raise ValueError('游客数据归属无效')
        user = self._auth_user()
        if user:
            raise ValueError('已注册账号不能由后台主动删除，请由用户走账号注销流程')
        return {'owner': self.email, 'registered': False}

    def _registry_records(self) -> dict[str, dict]:
        snapshot = globals().get('_file_registry_files_snapshot')
        files = snapshot() if callable(snapshot) else {}
        return {
            str(file_id): dict(rec or {})
            for file_id, rec in (files or {}).items()
            if isinstance(rec, dict)
            and _storage_quota_norm_owner(rec.get('owner_key') or rec.get('owner') or '') == self.email
        }

    def _kb_counts(self) -> dict:
        ensure = globals().get('_kb_db_ensure')
        connect = globals().get('_kb_db_connect')
        if not callable(connect):
            return {'spaces': 0, 'documents': 0, 'chunks': 0}
        if callable(ensure):
            ensure()
        conn = connect()
        try:
            values = {}
            for label, table in (('spaces', 'kb_spaces'), ('documents', 'kb_documents'), ('chunks', 'kb_chunks')):
                row = conn.execute(f'SELECT COUNT(1) AS c FROM {table} WHERE owner_key=?', (self.email,)).fetchone()
                try:
                    values[label] = int(row['c'] if row is not None else 0)
                except Exception:
                    values[label] = int(row[0] if row is not None else 0)
            return values
        finally:
            conn.close()

    def _async_job_ids(self) -> list[str]:
        jobs = globals().get('_CHAT_ASYNC_JOBS')
        lock = globals().get('_CHAT_ASYNC_JOB_LOCK')
        if not isinstance(jobs, dict):
            return []
        def collect() -> list[str]:
            return [
                str(job_id)
                for job_id, rec in jobs.items()
                if self._matches_async_owner((rec or {}).get('owner_email') or '')
            ]
        if lock is None:
            return collect()
        with lock:
            return collect()

    def _matches_async_owner(self, owner_email: str) -> bool:
        normalized = _storage_quota_norm_owner(owner_email or '')
        if self.email == 'anonymous':
            return not normalized
        return normalized == self.email

    def _share_count(self) -> int:
        loader = globals().get('_chat_share_load_unlocked')
        lock = globals().get('_CHAT_SHARE_LOCK')
        if not callable(loader):
            return 0
        owner_hash = hashlib.sha256(self.email.encode('utf-8')).hexdigest()[:24]
        def count_rows() -> int:
            state = loader()
            return sum(1 for rec in (state.get('shares') or {}).values() if isinstance(rec, dict) and rec.get('owner_hash') == owner_hash)
        if lock is None:
            return count_rows()
        with lock:
            return count_rows()

    def _chat_backup_paths(self) -> list[str]:
        root = os.path.abspath(str(globals().get('AUTH_CHAT_BACKUP_DIR') or '').strip())
        if not root or not os.path.isdir(root):
            return []
        paths: list[str] = []
        for name in os.listdir(root):
            path = os.path.abspath(os.path.join(root, os.path.basename(str(name or ''))))
            if not path.startswith(root + os.sep) or not path.endswith('.json') or not os.path.isfile(path) or os.path.islink(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as handle:
                    payload = json.load(handle)
                owner = _storage_quota_norm_owner((payload or {}).get('email') or '') if isinstance(payload, dict) else ''
            except Exception:
                owner = ''
            if owner == self.email:
                paths.append(path)
        return paths

    def _mcp_server_count(self) -> int:
        store = globals().get('_MCP_SERVER_STORE')
        return int(store.count(self.email) or 0) if store is not None and hasattr(store, 'count') else 0

    def preview(self) -> dict:
        self.validate_target()
        registry = self._registry_records()
        kb = self._kb_counts()
        sandbox = _storage_quota_owner_sandbox_breakdown(self.email)
        return {
            'ok': True,
            'owner': self.email,
            'account_kind': 'guest',
            'shared_anonymous_bucket': self.email == 'anonymous',
            'irreversible': True,
            'counts': {
                'async_jobs': len(self._async_job_ids()),
                'chat_shares': self._share_count(),
                'chat_backups': len(self._chat_backup_paths()),
                'knowledge_spaces': int(kb.get('spaces') or 0),
                'knowledge_documents': int(kb.get('documents') or 0),
                'knowledge_chunks': int(kb.get('chunks') or 0),
                'file_records': len(registry),
                'sandbox_files': int(sandbox.get('sandbox_file_count') or 0),
                'mcp_servers': self._mcp_server_count(),
            },
            'storage': _storage_quota_owner_breakdown(self.email),
        }

    def _purge_async_jobs(self) -> dict:
        job_ids = self._async_job_ids()
        stop = globals().get('_chat_async_request_stop')
        for job_id in job_ids:
            if callable(stop):
                try:
                    stop(job_id)
                except Exception:
                    pass
        jobs = globals().get('_CHAT_ASYNC_JOBS')
        runtimes = globals().get('_CHAT_ASYNC_JOB_RUNTIME')
        conditions = globals().get('_CHAT_ASYNC_JOB_CONDS')
        lock = globals().get('_CHAT_ASYNC_JOB_LOCK')
        if isinstance(jobs, dict) and lock is not None:
            with lock:
                for job_id in job_ids:
                    jobs.pop(job_id, None)
                    if isinstance(runtimes, dict):
                        runtimes.pop(job_id, None)
                    if isinstance(conditions, dict):
                        conditions.pop(job_id, None)
        deleted_db = 0
        ensure = globals().get('_chat_async_db_ensure')
        connect = globals().get('_chat_async_db_connect')
        if callable(connect):
            if callable(ensure):
                ensure()
            conn = connect()
            try:
                rows = conn.execute('SELECT job_id, owner_json FROM chat_async_jobs').fetchall()
                db_ids = []
                for row in rows:
                    try:
                        job_id, owner_json = row['job_id'], row['owner_json']
                    except Exception:
                        job_id, owner_json = row[0], row[1]
                    try:
                        owner = json.loads(str(owner_json or '{}'))
                    except Exception:
                        owner = {}
                    if self._matches_async_owner((owner or {}).get('email') or ''):
                        db_ids.append(str(job_id))
                if db_ids:
                    conn.executemany('DELETE FROM chat_async_jobs WHERE job_id=?', [(job_id,) for job_id in db_ids])
                    conn.commit()
                    deleted_db = len(db_ids)
            finally:
                conn.close()
        return {'runtime_removed': len(job_ids), 'database_removed': deleted_db}

    def _purge_account_core(self) -> dict:
        out = {}
        for key, name in (
            ('profile', '_auth_account_profile_delete'),
            ('chat', '_auth_chat_store_delete'),
            ('memory', '_auth_personalization_memory_delete_account'),
        ):
            fn = globals().get(name)
            out[key] = bool(fn(self.email)) if callable(fn) else False
        return out

    def _purge_chat_backups(self) -> dict:
        removed = 0
        freed_bytes = 0
        lock = globals().get('_AUTH_CHAT_LOCK')

        def remove_paths() -> None:
            nonlocal removed, freed_bytes
            for path in self._chat_backup_paths():
                try:
                    size = int(os.path.getsize(path) or 0)
                    os.remove(path)
                    removed += 1
                    freed_bytes += max(0, size)
                except FileNotFoundError:
                    continue

        if lock is None:
            remove_paths()
        else:
            with lock:
                remove_paths()
        return {'removed': removed, 'freed_bytes': freed_bytes}

    def _purge_mcp_servers(self) -> dict:
        deleter = globals().get('_mcp_client_delete_owner')
        return {'removed': int(deleter(self.email) or 0) if callable(deleter) else 0}

    def _purge_shares(self) -> dict:
        loader = globals().get('_chat_share_load_unlocked')
        writer = globals().get('_chat_share_write_unlocked')
        lock = globals().get('_CHAT_SHARE_LOCK')
        if not callable(loader) or not callable(writer) or lock is None:
            return {'removed': 0}
        owner_hash = hashlib.sha256(self.email.encode('utf-8')).hexdigest()[:24]
        with lock:
            state = loader()
            shares = state.get('shares') if isinstance(state.get('shares'), dict) else {}
            remove_ids = [token for token, rec in shares.items() if isinstance(rec, dict) and rec.get('owner_hash') == owner_hash]
            for token in remove_ids:
                shares.pop(token, None)
            state['shares'] = shares
            if remove_ids:
                writer(state)
        return {'removed': len(remove_ids)}

    def _purge_recycle_id(self, recycle_id: str) -> bool:
        rid = str(recycle_id or '').strip()
        action = globals().get('_platform_admin_recycle_action')
        if not rid or not callable(action):
            return False
        action(rid, 'purge')
        return True

    def _purge_knowledge(self) -> dict:
        ensure = globals().get('_kb_db_ensure')
        connect = globals().get('_kb_db_connect')
        deleter = globals().get('_kb_delete_document')
        if not callable(connect):
            return {'documents': 0, 'spaces': 0, 'recycle_purged': 0}
        if callable(ensure):
            ensure()
        conn = connect()
        try:
            rows = conn.execute('SELECT id FROM kb_documents WHERE owner_key=? ORDER BY updated_at ASC', (self.email,)).fetchall()
            doc_ids = []
            for row in rows:
                try:
                    doc_ids.append(str(row['id']))
                except Exception:
                    doc_ids.append(str(row[0]))
        finally:
            conn.close()
        recycle_purged = 0
        for doc_id in doc_ids:
            if not callable(deleter):
                break
            result = deleter(owner_key=self.email, doc_id=doc_id)
            cleanup = result.get('cleanup') if isinstance(result, dict) else {}
            if isinstance(cleanup, dict) and cleanup.get('ok') is False:
                raise RuntimeError(str(cleanup.get('error') or '知识库文件清理失败'))
            if self._purge_recycle_id(str((cleanup or {}).get('recycle', {}).get('id') or '')):
                recycle_purged += 1
        conn = connect()
        try:
            space_row = conn.execute('SELECT COUNT(1) FROM kb_spaces WHERE owner_key=?', (self.email,)).fetchone()
            space_count = int(space_row[0] if space_row is not None else 0)
            conn.execute('DELETE FROM kb_chunks WHERE owner_key=?', (self.email,))
            conn.execute('DELETE FROM kb_documents WHERE owner_key=?', (self.email,))
            conn.execute('DELETE FROM kb_spaces WHERE owner_key=?', (self.email,))
            conn.commit()
        finally:
            conn.close()
        return {'documents': len(doc_ids), 'spaces': space_count, 'recycle_purged': recycle_purged}

    @staticmethod
    def _path_key(path: str) -> str:
        return os.path.normcase(os.path.abspath(str(path or '').strip())) if str(path or '').strip() else ''

    def _registry_path_sets(self, owned: dict[str, dict]) -> tuple[set[str], set[str]]:
        snapshot = globals().get('_file_registry_files_snapshot')
        files = snapshot() if callable(snapshot) else {}
        candidates: set[str] = set()
        shared: set[str] = set()
        for file_id, rec in (files or {}).items():
            if not isinstance(rec, dict):
                continue
            owner = _storage_quota_norm_owner(rec.get('owner_key') or rec.get('owner') or '')
            target = candidates if str(file_id) in owned or owner == self.email else shared
            for path in _platform_admin_registry_path_candidates(rec):
                key = self._path_key(path)
                if key:
                    target.add(key)
            ref = str(rec.get('full_text_ref') or '').strip()
            text_path = globals().get('_file_text_store_path')
            if ref and callable(text_path):
                key = self._path_key(text_path(ref))
                if key:
                    target.add(key)
        return candidates, shared

    def _is_safe_account_file(self, path: str) -> bool:
        target = os.path.abspath(str(path or '').strip())
        if not target or os.path.islink(target):
            return False
        roots = [os.path.abspath(str(item.get('root') or '')) for item in _platform_admin_file_roots()]
        roots.append(os.path.abspath(_app_data_path('file_text_store')))
        return any(root and target.startswith(root + os.sep) for root in roots)

    def _purge_file_storage(self) -> dict:
        owned = self._registry_records()
        candidates, shared = self._registry_path_sets(owned)
        deleted_via_library = 0
        recycle_purged = 0
        file_deleter = globals().get('_file_library_delete_file')
        for file_id in list(owned):
            current = globals().get('_file_library_get_record')
            if callable(current) and not current(file_id, self.email):
                continue
            if not callable(file_deleter):
                break
            result = file_deleter(file_id=file_id, owner_key=self.email)
            deleted_via_library += 1
            if self._purge_recycle_id(str((result.get('recycle') or {}).get('id') or '')):
                recycle_purged += 1
        remaining = self._registry_records()
        remover = globals().get('_file_registry_remove_records')
        if remaining and callable(remover):
            remover(list(remaining))

        tracked_removed = 0
        with _STORAGE_QUOTA_LOCK:
            index_data = _storage_quota_load_owner_index()
            files = index_data.get('files') if isinstance(index_data.get('files'), dict) else {}
            for key, rec in list(files.items()):
                path_key = self._path_key((rec or {}).get('path') or '') if isinstance(rec, dict) else ''
                owner = _storage_quota_norm_owner((rec or {}).get('owner') or '') if isinstance(rec, dict) else ''
                if owner == self.email:
                    files.pop(key, None)
                    tracked_removed += 1
                    if path_key:
                        candidates.add(path_key)
                elif path_key:
                    shared.add(path_key)
            index_data['files'] = files
            _storage_quota_save_owner_index(index_data)

        files_removed = 0
        freed_bytes = 0
        for path in sorted(candidates):
            if path in shared or not self._is_safe_account_file(path) or not os.path.isfile(path):
                continue
            size = int(os.path.getsize(path) or 0)
            os.remove(path)
            files_removed += 1
            freed_bytes += max(0, size)

        sandbox_root = os.path.abspath(_storage_quota_sandbox_owner_root(self.email))
        sandbox_parent = os.path.abspath(_storage_quota_sandbox_root())
        sandbox_removed = False
        if sandbox_root.startswith(sandbox_parent + os.sep) and os.path.isdir(sandbox_root) and not os.path.islink(sandbox_root):
            shutil.rmtree(sandbox_root)
            sandbox_removed = True
        reset_limit = globals().get('_storage_quota_set_owner_limit_override')
        if callable(reset_limit) and self.email != 'anonymous':
            reset_limit(self.email, reset=True)
        return {
            'registry_removed': len(owned),
            'library_deleted': deleted_via_library,
            'tracked_removed': tracked_removed,
            'files_removed': files_removed,
            'freed_bytes': freed_bytes,
            'sandbox_removed': sandbox_removed,
            'recycle_purged': recycle_purged,
        }

    def _scrub_invites(self) -> dict:
        state = globals().get('_AUTH_INVITE_CODES_STATE')
        lock = globals().get('_AUTH_INVITE_CODES_LOCK')
        saver = globals().get('_auth_invite_codes_save')
        changed = 0
        if not isinstance(state, dict) or lock is None:
            return {'anonymized': 0}
        with lock:
            for code, rec in list((state.get('codes') or {}).items()):
                if _storage_quota_norm_owner((rec or {}).get('used_by') or '') != self.email:
                    continue
                row = dict(rec or {})
                row['used_by'] = ''
                row['updated_at'] = _utc_ts()
                state.setdefault('codes', {})[code] = row
                changed += 1
        if changed and callable(saver):
            saver()
        return {'anonymized': changed}

    def _scrub_delete_logs(self) -> dict:
        state = globals().get('_AUTH_ACCOUNT_DELETE_LOG_STATE')
        lock = globals().get('_AUTH_ACCOUNT_DELETE_LOG_LOCK')
        saver = globals().get('_auth_account_delete_log_save')
        if not isinstance(state, dict) or lock is None:
            return {'removed': 0}
        with lock:
            rows = list(state.get('events') or [])
            kept = [row for row in rows if _storage_quota_norm_owner((row or {}).get('email') or '') != self.email]
            state['events'] = kept
            state['updated_at'] = _utc_ts()
        if len(kept) != len(rows) and callable(saver):
            saver()
        return {'removed': len(rows) - len(kept)}

    def _scrub_admin_audit(self) -> dict:
        data = _platform_admin_audit_load()
        rows = list(data.get('items') or [])
        needle = self.email.lower()
        kept = []
        for row in rows:
            haystack = (str((row or {}).get('target') or '') + ' ' + json.dumps((row or {}).get('detail') or {}, ensure_ascii=False)).lower()
            if needle and needle in haystack:
                continue
            kept.append(row)
        data['items'] = kept
        _platform_admin_audit_save(data)
        return {'removed': len(rows) - len(kept)}

    def purge(self, confirm_email: str) -> dict:
        self.validate_target()
        if _storage_quota_norm_owner(confirm_email or '') != self.email:
            raise ValueError('必须输入完整游客归属标识确认删除')
        with _PLATFORM_ADMIN_GUEST_PURGE_LOCK:
            if self.email in _PLATFORM_ADMIN_GUEST_PURGE_OWNERS:
                raise ValueError('该游客数据正在清理，请勿重复提交')
            _PLATFORM_ADMIN_GUEST_PURGE_OWNERS.add(self.email)
        result = {'fingerprint': self.fingerprint, 'steps': {}}
        try:
            # 加入清理集合后再次检查，和注册入口共同关闭“清理时注册”的竞态窗口。
            self.validate_target()
            steps = (
                ('async_jobs', self._purge_async_jobs),
                ('account_core', self._purge_account_core),
                ('chat_backups', self._purge_chat_backups),
                ('mcp_servers', self._purge_mcp_servers),
                ('chat_shares', self._purge_shares),
                ('knowledge', self._purge_knowledge),
                ('file_storage', self._purge_file_storage),
                ('invite_codes', self._scrub_invites),
                ('delete_logs', self._scrub_delete_logs),
                ('admin_audit', self._scrub_admin_audit),
            )
            for name, operation in steps:
                result['steps'][name] = operation()
            _platform_admin_audit_append(
                'guest_account_purge',
                'guest-owner:' + self.fingerprint,
                {'fingerprint': self.fingerprint, 'step_names': list(result['steps'])},
                ok=True,
            )
            return {'ok': True, 'deleted': True, 'owner': self.email, **result}
        except Exception as exc:
            _platform_admin_audit_append(
                'guest_account_purge',
                'guest-owner:' + self.fingerprint,
                {
                    'fingerprint': self.fingerprint,
                    'completed_step_names': list(result['steps']),
                    'error_type': type(exc).__name__,
                },
                ok=False,
                error='游客数据清理未完成，可安全重试',
            )
            raise
        finally:
            with _PLATFORM_ADMIN_GUEST_PURGE_LOCK:
                _PLATFORM_ADMIN_GUEST_PURGE_OWNERS.discard(self.email)


def _platform_admin_guest_purge_preview(email: str) -> dict:
    return PlatformAdminGuestPurgeService(email).preview()


def _platform_admin_purge_guest_account(email: str, confirm_email: str) -> dict:
    return PlatformAdminGuestPurgeService(email).purge(confirm_email)
