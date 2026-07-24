# account state, profile persistence, chat synchronization state, and shared auth helpers.

AUTH_ACCOUNT_DISABLED_MESSAGE = "该账号疑似滥用，已被停用"
AUTH_ACCOUNT_DELETED_MESSAGE = "该账号已删除，无法继续登录"
AUTH_ACCOUNT_DELETE_PENDING_MESSAGE = "该账号正在删除期内，请先撤销删除后继续登录"
AUTH_ACCOUNT_DELETE_GRACE_DAYS = 30
AUTH_ACCOUNT_DELETE_GRACE_S = AUTH_ACCOUNT_DELETE_GRACE_DAYS * 24 * 3600
AUTH_LOGIN_DISABLED_MESSAGE = "登录状态已失效，请重新登录"
AUTH_ACCOUNT_BLACKLIST_GRACE_DAYS = 7
AUTH_ACCOUNT_BLACKLIST_GRACE_S = AUTH_ACCOUNT_BLACKLIST_GRACE_DAYS * 24 * 3600
AUTH_ACCOUNT_TEMP_BLACKLIST_MESSAGE = f"该账号已被拉黑，请在 {AUTH_ACCOUNT_BLACKLIST_GRACE_DAYS} 天内联系管理员解封"
AUTH_ACCOUNT_PERMANENT_BAN_MESSAGE = "该账号已被永久封禁，请联系管理员"
def _utc_ts() -> float:
    try:
        return float(time.time())
    except Exception:
        return 0.0


def _fmt_ts(ts: float | int | None) -> str:
    try:
        if not ts:
            return ""
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _normalize_login_email(email: str) -> str:
    return str(email or "").strip().lower()


def _mask_login_email(email: str) -> str:
    raw = _normalize_login_email(email)
    if not raw or "@" not in raw:
        return ""
    name, domain = raw.split("@", 1)
    if len(name) <= 2:
        head = name[:1]
        tail = ""
    else:
        head = name[:2]
        tail = name[-1:]
    return f"{head}{'*' * max(2, len(name) - len(head) - len(tail))}{tail}@{domain}"


def _hash_login_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(str(salt_hex or '').strip()) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha256', str(password or '').encode('utf-8', 'ignore'), salt, 200000)
    return digest.hex(), salt.hex()


AUTH_USERS_FILE = _app_data_path('auth_users_store.json')
_AUTH_USERS_LOCK = threading.Lock()
_AUTH_USERS_STATE = {
    'users': {},
    'updated_at': 0.0,
}
AUTH_ACCOUNT_DELETE_LOG_FILE = _app_data_path('auth_account_delete_log.json')
try:
    AUTH_ACCOUNT_DELETE_LOG_MAX_EVENTS = max(50, min(int(app_getenv('AUTH_ACCOUNT_DELETE_LOG_MAX_EVENTS', '500') or 500), 5000))
except Exception:
    AUTH_ACCOUNT_DELETE_LOG_MAX_EVENTS = 500
try:
    AUTH_ACCOUNT_DELETE_SWEEP_INTERVAL_S = max(60, int(app_getenv('AUTH_ACCOUNT_DELETE_SWEEP_INTERVAL_S', '3600') or 3600))
except Exception:
    AUTH_ACCOUNT_DELETE_SWEEP_INTERVAL_S = 3600
_AUTH_ACCOUNT_DELETE_LOG_LOCK = threading.Lock()
_AUTH_ACCOUNT_DELETE_LOG_STATE = {
    'events': [],
    'updated_at': 0.0,
}
_AUTH_ACCOUNT_DELETE_SWEEP_START_LOCK = threading.Lock()
_AUTH_ACCOUNT_DELETE_SWEEP_THREAD_STARTED = False
AUTH_CHAT_STORE_FILE = _app_data_path('auth_chat_store.json')
AUTH_CHAT_DB_FILE = _app_data_path('auth_chat_store.db')
AUTH_ACCOUNT_PROFILE_FILE = _app_data_path('auth_account_profile_store.json')
AUTH_ACCOUNT_PROFILE_MAX_BYTES = max(8 * 1024 * 1024, int(app_getenv('AUTH_ACCOUNT_PROFILE_MAX_BYTES', str(128 * 1024 * 1024)) or (128 * 1024 * 1024)))
_AUTH_CHAT_LOCK = threading.Lock()
_AUTH_CHAT_DB_LOCK = threading.Lock()
_AUTH_CHAT_STATE = {
    'accounts': {},
    'updated_at': 0.0,
}
_AUTH_ACCOUNT_PROFILE_LOCK = threading.Lock()
_AUTH_ACCOUNT_PROFILE_STATE = {
    'profiles': {},
    'updated_at': 0.0,
}
AUTH_CHAT_STORE_MAX_BYTES = max(16 * 1024 * 1024, int(app_getenv('AUTH_CHAT_STORE_MAX_BYTES', str(64 * 1024 * 1024)) or (64 * 1024 * 1024)))
AUTH_CHAT_DB_MAX_BYTES = max(64 * 1024 * 1024, int(app_getenv('AUTH_CHAT_DB_MAX_BYTES', str(512 * 1024 * 1024)) or (512 * 1024 * 1024)))
AUTH_CHAT_ACCOUNT_MAX_SESSIONS = max(0, int(app_getenv('AUTH_CHAT_ACCOUNT_MAX_SESSIONS', '0') or 0))
AUTH_CHAT_ACCOUNT_MAX_MESSAGES_PER_SESSION = max(0, int(app_getenv('AUTH_CHAT_ACCOUNT_MAX_MESSAGES_PER_SESSION', '0') or 0))
AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS = max(0, int(app_getenv('AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS', '0') or 0))
AUTH_CHAT_HISTORY_SUMMARY_MAX_CHARS = max(1200, int(app_getenv('AUTH_CHAT_HISTORY_SUMMARY_MAX_CHARS', '6000') or 6000))
AUTH_CHAT_HISTORY_SUMMARY_MAX_LINES = max(20, int(app_getenv('AUTH_CHAT_HISTORY_SUMMARY_MAX_LINES', '80') or 80))
AUTH_CHAT_RESUME_STATE_MAX_CHARS = max(700, min(int(app_getenv('AUTH_CHAT_RESUME_STATE_MAX_CHARS', '1400') or 1400), 3200))
AUTH_CHAT_RESUME_STATE_RECENT_LINES = max(2, min(int(app_getenv('AUTH_CHAT_RESUME_STATE_RECENT_LINES', '4') or 4), 8))
AUTH_CHAT_RESUME_STATE_FILES_MAX = max(0, min(int(app_getenv('AUTH_CHAT_RESUME_STATE_FILES_MAX', '6') or 6), 12))
AUTH_CHAT_SYNC_MAX_OPS_PER_PUSH = max(1, int(app_getenv('AUTH_CHAT_SYNC_MAX_OPS_PER_PUSH', '80') or 80))
AUTH_CHAT_SYNC_OPS_LOG_MAX = max(0, int(app_getenv('AUTH_CHAT_SYNC_OPS_LOG_MAX', '80') or 80))
AUTH_CHAT_SYNC_APPLIED_OP_MAX = max(20, int(app_getenv('AUTH_CHAT_SYNC_APPLIED_OP_MAX', '240') or 240))
AUTH_CHAT_SYNC_OP_MAX_BYTES = max(16 * 1024, int(app_getenv('AUTH_CHAT_SYNC_OP_MAX_BYTES', str(768 * 1024)) or (768 * 1024)))
AUTH_CHAT_SYNC_LOG_OP_MAX_BYTES = max(8 * 1024, int(app_getenv('AUTH_CHAT_SYNC_LOG_OP_MAX_BYTES', str(64 * 1024)) or (64 * 1024)))
AUTH_CHAT_SOFT_DELETE_RETENTION_S = max(86400, int(app_getenv('AUTH_CHAT_SOFT_DELETE_RETENTION_S', str(90 * 24 * 3600)) or (90 * 24 * 3600)))
AUTH_CHAT_BACKUP_DIR = _app_data_path('auth_chat_store_backups')
AUTH_CHAT_BACKUP_MAX_FILES = max(10, int(app_getenv('AUTH_CHAT_BACKUP_MAX_FILES', '80') or 80))
AUTH_CHAT_BACKUP_MAX_BYTES = max(16 * 1024 * 1024, int(app_getenv('AUTH_CHAT_BACKUP_MAX_BYTES', str(512 * 1024 * 1024)) or (512 * 1024 * 1024)))
_AUTH_CHAT_SNAPSHOT_OP_TYPES = {'replace_store', 'snapshot', 'store_snapshot', 'merge_store_snapshot'}
AUTH_CHAT_FILE_PREVIEW_MAX_CHARS = max(0, int(app_getenv('AUTH_CHAT_FILE_PREVIEW_MAX_CHARS', '1200') or 1200))
AUTH_CHAT_FILE_SYMBOLS_MAX = max(0, int(app_getenv('AUTH_CHAT_FILE_SYMBOLS_MAX', '80') or 80))
AUTH_CHAT_FILE_AUDIT_DIFF_MAX_CHARS = max(0, int(app_getenv('AUTH_CHAT_FILE_AUDIT_DIFF_MAX_CHARS', '24000') or 24000))
