# 项目版本公告服务。
# 公告正文随版本进入镜像，身份数据库只保存账号确认回执。

PLATFORM_RELEASE_ANNOUNCEMENT_CATEGORIES = {
    'en': {'update': 'Product update', 'security': 'Security update'},
    'zh-CN': {'update': '版本更新', 'security': '安全更新'},
}
PLATFORM_RELEASE_ANNOUNCEMENT_MAX_BODY_CHARS = 30000


class PlatformReleaseAnnouncementService:
    """读取随项目发布的版本公告，并管理账号级确认回执。"""

    def __init__(self, base_dir: str = ''):
        self.base_dir = os.path.abspath(str(base_dir or BASE_DIR))
        self.releases = {}
        self.release = {'enabled': False}

    @property
    def version_path(self) -> str:
        return os.path.join(self.base_dir, 'VERSION')

    @property
    def announcement_path(self) -> str:
        return self.announcement_path_for_language('en')

    def announcement_path_for_language(self, language: str) -> str:
        filename = 'announcement.zh-CN.md' if language == 'zh-CN' else 'announcement.md'
        return os.path.join(self.base_dir, 'release', filename)

    @staticmethod
    def _read_text(path: str) -> str:
        with open(path, 'r', encoding='utf-8') as handle:
            return str(handle.read() or '').replace('\r\n', '\n').replace('\r', '\n')

    @staticmethod
    def _parse_front_matter(text: str) -> tuple[dict, str]:
        lines = str(text or '').split('\n')
        if not lines or lines[0].strip() != '<!--':
            raise RuntimeError('release/announcement.md 缺少开头元数据')
        try:
            end_index = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == '-->')
        except StopIteration as exc:
            raise RuntimeError('release/announcement.md 元数据未闭合') from exc
        metadata = {}
        for raw_line in lines[1:end_index]:
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            if ':' not in line:
                raise RuntimeError(f'release/announcement.md 元数据格式无效：{line}')
            key, value = line.split(':', 1)
            metadata[str(key or '').strip()] = str(value or '').strip()
        return metadata, '\n'.join(lines[end_index + 1:]).strip()

    @staticmethod
    def _language(value) -> str:
        normalizer = globals().get('_auth_ui_language_normalize')
        if callable(normalizer):
            return normalizer(value)
        return 'en' if str(value or '').strip().lower().replace('_', '-').startswith('en') else 'zh-CN'

    def _load_language(self, language: str, project_version: str) -> dict:
        path = self.announcement_path_for_language(language)
        metadata, body = self._parse_front_matter(self._read_text(path))
        source_name = os.path.relpath(path, self.base_dir).replace('\\', '/')
        release_version = str(metadata.get('version') or '').strip()
        release_id = str(metadata.get('id') or '').strip()
        if release_version != project_version:
            raise RuntimeError(f'{source_name} 与 VERSION 不一致')
        if release_id != f'v{project_version}':
            raise RuntimeError(f'{source_name} 的 ID 必须为 v 加 VERSION')
        title = str(metadata.get('title') or '').strip()[:120]
        if not title or not body:
            raise RuntimeError(f'{source_name} 的标题或正文为空')
        if len(body) > PLATFORM_RELEASE_ANNOUNCEMENT_MAX_BODY_CHARS:
            raise RuntimeError(f'{source_name} 的正文过长')
        published_at = str(metadata.get('published_at') or '').strip()
        try:
            datetime.datetime.strptime(published_at, '%Y-%m-%d')
        except ValueError as exc:
            raise RuntimeError(f'{source_name} 的发布日期必须使用 YYYY-MM-DD 格式') from exc
        category = str(metadata.get('category') or 'update').strip().lower()
        category_labels = PLATFORM_RELEASE_ANNOUNCEMENT_CATEGORIES[language]
        if category not in category_labels:
            raise RuntimeError(f'{source_name} 的分类无效')
        enabled = str(metadata.get('enabled') or 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
        default_button = 'Got it' if language == 'en' else '我知道了'
        return {
            'enabled': enabled,
            'id': release_id,
            'version': f'Apervia {project_version}',
            'category': category,
            'category_label': category_labels[category],
            'title': title,
            'body': body,
            'button_text': str(metadata.get('button_text') or default_button).strip()[:40] or default_button,
            'published_at': published_at,
            'language': language,
        }

    def load(self) -> dict:
        project_version = self._read_text(self.version_path).strip()
        if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?', project_version):
            raise RuntimeError('VERSION 文件格式无效')
        self.releases = {
            language: self._load_language(language, project_version)
            for language in ('en', 'zh-CN')
        }
        shared_keys = ('enabled', 'id', 'version', 'category', 'published_at')
        english = self.releases['en']
        chinese = self.releases['zh-CN']
        if any(english.get(key) != chinese.get(key) for key in shared_keys):
            raise RuntimeError('中英文版本公告的发布元数据不一致')
        self.release = dict(english)
        return dict(self.release)

    def initialize(self) -> None:
        self.load()
        with contextlib.closing(_auth_identity_connect()) as conn:
            conn.executescript(
                '''
                CREATE TABLE IF NOT EXISTS identity_release_receipts (
                    release_id TEXT NOT NULL,
                    user_id TEXT NOT NULL REFERENCES identity_users(id) ON DELETE CASCADE,
                    acknowledged_at REAL NOT NULL,
                    PRIMARY KEY (release_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS identity_release_receipts_user_idx
                    ON identity_release_receipts(user_id, acknowledged_at DESC);
                '''
            )
            conn.commit()

    def current_for_user(self, user_id: str = '', language: str = '') -> dict:
        resolved_language = self._language(language)
        if not language and user_id:
            try:
                with contextlib.closing(_auth_identity_connect()) as conn:
                    user_row = conn.execute('SELECT email FROM identity_users WHERE id = ?', (str(user_id),)).fetchone()
                email = str((user_row['email'] if user_row else '') or '')
                profile_getter = globals().get('_auth_account_profile_get')
                if email and callable(profile_getter):
                    resolved_language = self._language((profile_getter(email) or {}).get('ui_language'))
            except Exception:
                resolved_language = self._language(language)
        payload = dict(self.releases.get(resolved_language) or self.release)
        if not payload.get('enabled'):
            return {'enabled': False}
        target_user_id = str(user_id or '').strip()
        acknowledged = False
        if target_user_id:
            with contextlib.closing(_auth_identity_connect()) as conn:
                row = conn.execute(
                    'SELECT 1 FROM identity_release_receipts WHERE release_id = ? AND user_id = ?',
                    (payload['id'], target_user_id),
                ).fetchone()
            acknowledged = bool(row)
        payload['acknowledged'] = acknowledged
        return payload

    def acknowledge(self, user_id: str, release_id: str) -> dict:
        target_user_id = str(user_id or '').strip()
        target_release_id = str(release_id or '').strip()
        if not target_user_id or not target_release_id:
            raise ValueError('缺少版本公告确认信息')
        if not self.release.get('enabled') or target_release_id != self.release.get('id'):
            raise ValueError('版本公告已更新，请刷新页面')
        with contextlib.closing(_auth_identity_connect()) as conn:
            conn.execute(
                '''INSERT INTO identity_release_receipts (release_id, user_id, acknowledged_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(release_id, user_id) DO UPDATE SET acknowledged_at = excluded.acknowledged_at''',
                (target_release_id, target_user_id, _utc_ts()),
            )
            conn.commit()
        return {'ok': True, 'release_id': target_release_id, 'acknowledged': True}


_platform_release_announcement_service = PlatformReleaseAnnouncementService()


def _platform_release_announcement_init() -> None:
    _platform_release_announcement_service.initialize()


def _platform_release_announcement_for_user(user_id: str = '', language: str = '') -> dict:
    return _platform_release_announcement_service.current_for_user(user_id, language)
