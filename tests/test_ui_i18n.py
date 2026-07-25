import re
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _resource_keys(path: Path) -> set[str]:
    source = path.read_text(encoding='utf-8')
    return set(re.findall(r"^\s*'([^']+)'\s*:", source, flags=re.MULTILINE))


def _resource_key_list(path: Path) -> list[str]:
    source = path.read_text(encoding='utf-8')
    return re.findall(r"^\s*'([^']+)'\s*:", source, flags=re.MULTILINE)

class UiI18nTests(unittest.TestCase):
    def test_english_and_chinese_resources_have_matching_keys(self):
        english = _resource_keys(ROOT / 'static/i18n/en.js')
        chinese = _resource_keys(ROOT / 'static/i18n/zh-CN.js')
        self.assertEqual(english, chinese)
        self.assertGreaterEqual(len(english), 140)

    def test_app_loads_i18n_before_feature_modules(self):
        html = (ROOT / 'static/index3.html').read_text(encoding='utf-8')
        core = html.index('/static/shared/i18n.js')
        english = html.index('/static/i18n/en.js')
        chinese = html.index('/static/i18n/zh-CN.js')
        account = html.index('/static/index3/js/index3-account-cloud-lifecycle.js')
        self.assertLess(core, english)
        self.assertLess(english, chinese)
        self.assertLess(chinese, account)
        self.assertIn('id="accountLanguageSelect"', html)
        self.assertIn('id="accountMenuAdminBtn"', html)

    def test_public_login_is_bilingual_and_defaults_to_english(self):
        login = (ROOT / 'app3_parts/auth/platform_auth_identity_routes_part.py').read_text(encoding='utf-8')
        shared = (ROOT / 'static/shared/i18n.js').read_text(encoding='utf-8')
        profile = (ROOT / 'app3_parts/auth/platform_auth_chat_store_part.py').read_text(encoding='utf-8')
        self.assertIn('<html lang="en">', login)
        self.assertIn('id="language"', login)
        self.assertIn('data-i18n-aria-label="login.language"', login)
        self.assertIn('/static/shared/i18n.js', login)
        self.assertIn("window.AperviaI18n?.start()", login)
        self.assertIn("|| 'en'", shared)
        self.assertIn("AUTH_UI_LANGUAGE_DEFAULT = 'en'", profile)

    def test_storage_loading_state_uses_explicit_resources(self):
        html = (ROOT / 'static/index3.html').read_text(encoding='utf-8')
        self.assertIn('data-i18n="settings.storage.loading"', html)
        self.assertIn('data-i18n="settings.storage.loading_detail"', html)

    def test_admin_pages_share_account_scoped_i18n(self):
        admin = (ROOT / 'static/platform-admin/index.html').read_text(encoding='utf-8')
        self.assertIn('/static/shared/i18n.js', admin)
        self.assertIn('/static/i18n/en.js', admin)
        self.assertIn('/static/i18n/zh-CN.js', admin)
        self.assertIn('syncAccount:true', admin)
        self.assertIn('<title data-i18n="admin.platform.document_title">', admin)
        storage = (ROOT / 'app3_parts/storage/storage_admin_routes_part.py').read_text(encoding='utf-8')
        self.assertIn("return redirect('/admin'", storage)

    def test_admin_has_one_ui_and_legacy_paths_redirect_to_it(self):
        identity_routes = (ROOT / 'app3_parts/auth/platform_auth_identity_routes_part.py').read_text(encoding='utf-8')
        platform_routes = (ROOT / 'app3_parts/storage/platform_admin_routes_part.py').read_text(encoding='utf-8')
        storage_routes = (ROOT / 'app3_parts/storage/storage_admin_routes_part.py').read_text(encoding='utf-8')
        admin_html = (ROOT / 'static/platform-admin/index.html').read_text(encoding='utf-8')
        admin_js = (ROOT / 'static/platform-admin/platform-admin.js').read_text(encoding='utf-8')

        self.assertIn("@app.get('/admin')", identity_routes)
        self.assertIn('return _admin_html_response(_platform_admin_html())', identity_routes)
        self.assertNotIn('def _auth_identity_admin_html', identity_routes)
        self.assertIn("return redirect('/admin', code=302)", platform_routes)
        self.assertIn("return redirect('/admin', code=302)", storage_routes)
        self.assertIn('data-tab="users"', admin_html)
        self.assertIn('id="panel-users"', admin_html)
        self.assertNotIn('<a href="/admin">', admin_html)
        self.assertIn("requestJson('/api3/admin/summary')", admin_js)
        self.assertIn("requestJson('/api3/admin/users')", admin_js)
        self.assertIn("'/api3/admin/users/'+encodeURIComponent", admin_js)

    def test_blacklist_management_remains_visible_in_unified_admin(self):
        admin_html = (ROOT / 'static/platform-admin/index.html').read_text(encoding='utf-8')
        admin_js = (ROOT / 'static/platform-admin/platform-admin.js').read_text(encoding='utf-8')
        inventory = (ROOT / 'app3_parts/storage/platform_admin_inventory_part.py').read_text(encoding='utf-8')
        actions = (ROOT / 'app3_parts/storage/platform_admin_chat_backup_part.py').read_text(encoding='utf-8')
        english = (ROOT / 'static/i18n/en.js').read_text(encoding='utf-8')
        chinese = (ROOT / 'static/i18n/zh-CN.js').read_text(encoding='utf-8')

        self.assertIn('value="blacklisted"', admin_html)
        self.assertIn('data-i18n="admin.platform.blacklisted_only"', admin_html)
        self.assertIn('data-account-action="blacklist"', admin_js)
        self.assertIn('data-account-action="unblacklist"', admin_js)
        self.assertIn("if st == 'blacklisted':", inventory)
        self.assertIn('def _platform_admin_identity_users_payload()', inventory)
        self.assertIn("'access_protected': access_protected", inventory)
        self.assertIn('a.access_protected', admin_js)
        self.assertIn("adminT('admin.platform.protected_administrator'", admin_js)
        self.assertIn("globals().get('_auth_identity_admin_set_status_by_email')", actions)
        self.assertIn("globals().get('_auth_identity_revoke_email_sessions')", actions)
        self.assertIn("'admin.platform.accounts':'Accounts & blacklist'", english)
        self.assertIn("'admin.platform.accounts':'账号与黑名单'", chinese)
        self.assertIn('data-i18n-placeholder="admin.platform.account_search_placeholder"', admin_html)
        self.assertIn('data-i18n="admin.platform.account_status_abnormal_deleted"', admin_html)
        self.assertIn("'admin.platform.account_status_abnormal_deleted':'Abnormal / deleted'", english)
        self.assertIn("'admin.platform.account_status_abnormal_deleted':'异常/已删'", chinese)

    def test_rate_limit_management_is_part_of_unified_admin_only(self):
        admin_html = (ROOT / 'static/platform-admin/index.html').read_text(encoding='utf-8')
        admin_js = (ROOT / 'static/platform-admin/platform-admin.js').read_text(encoding='utf-8')
        rate_js = (ROOT / 'static/platform-admin/platform-admin-rate-limit.js').read_text(encoding='utf-8')
        admin_css = (ROOT / 'static/platform-admin/platform-admin.css').read_text(encoding='utf-8')
        identity_routes = (ROOT / 'app3_parts/auth/platform_auth_identity_routes_part.py').read_text(encoding='utf-8')
        auth_sources = '\n'.join(path.read_text(encoding='utf-8') for path in (ROOT / 'app3_parts/auth').glob('*.py'))

        self.assertIn('data-tab="rate"', admin_html)
        self.assertIn('id="panel-rate"', admin_html)
        self.assertIn('/static/platform-admin/platform-admin-rate-limit.js', admin_html)
        self.assertIn("rate:['admin.rate.title','admin.rate.subtitle']", admin_js)
        self.assertIn("const apiBase = '/api3/admin/rate-limit'", rate_js)
        self.assertIn('.rateCheck input[type="checkbox"]', admin_css)
        self.assertIn('appearance: none', admin_css)
        self.assertIn('flex: 0 0 34px', admin_css)
        for endpoint in ('state', 'config', 'reset'):
            self.assertIn(f"'/api3/admin/rate-limit/{endpoint}'", identity_routes)
        self.assertEqual(3, identity_routes.count('def auth_identity_admin_rate_limit_'))
        self.assertEqual(6, identity_routes.count('_auth_identity_admin_guard()'))
        for removed in ('manual-block', 'manual-unblock', 'manual_blocks', 'rateManual'):
            self.assertNotIn(removed, admin_html + rate_js + identity_routes + auth_sources)
        self.assertNotIn("@app.get('/rate-admin')", auth_sources)
        self.assertNotIn("'/api3/rate-limit/", auth_sources)

    def test_protected_administrator_uses_one_backend_state_in_both_admin_views(self):
        identity = (ROOT / 'app3_parts/auth/platform_auth_identity_part.py').read_text(encoding='utf-8')
        inventory = (ROOT / 'app3_parts/storage/platform_admin_inventory_part.py').read_text(encoding='utf-8')
        admin_js = (ROOT / 'static/platform-admin/platform-admin.js').read_text(encoding='utf-8')

        self.assertIn("user['access_protected']", identity)
        self.assertIn("access_protected = bool(identity.get('access_protected'))", inventory)
        self.assertNotIn('active_admins = sum(', inventory)
        self.assertIn('const protectedAdmin=!!user.access_protected', admin_js)

    def test_unified_admin_localizes_structured_and_historical_system_errors(self):
        admin_js = (ROOT / 'static/platform-admin/platform-admin.js').read_text(encoding='utf-8')
        devops_js = (ROOT / 'static/platform-admin/platform-admin-devops.js').read_text(encoding='utf-8')
        english = (ROOT / 'static/i18n/en.js').read_text(encoding='utf-8')
        chinese = (ROOT / 'static/i18n/zh-CN.js').read_text(encoding='utf-8')

        self.assertIn('function adminErrorText(value)', admin_js)
        self.assertIn("'不能停用或降级最后一个管理员':'admin.error.last_admin_disable_or_downgrade'", admin_js)
        self.assertIn('error:adminErrorText(a.error)', admin_js)
        self.assertIn('adminErrorText(e.error', admin_js)
        self.assertIn('adminErrorText(docker.error', devops_js)
        self.assertIn("'admin.error.last_admin_disable_or_downgrade':'The last active administrator cannot be disabled or downgraded'", english)
        self.assertIn("'admin.error.last_admin_disable_or_downgrade':'不能停用或降级最后一个管理员'", chinese)

    def test_admin_python_inventory_uses_structured_source_i18n(self):
        backend = (ROOT / 'app3_parts/storage/platform_admin_devtools_part.py').read_text(encoding='utf-8')
        frontend = (ROOT / 'static/platform-admin/platform-admin-devops.js').read_text(encoding='utf-8')
        english = (ROOT / 'static/i18n/en.js').read_text(encoding='utf-8')
        chinese = (ROOT / 'static/i18n/zh-CN.js').read_text(encoding='utf-8')

        self.assertNotIn("'source_text':", backend)
        self.assertNotIn("'summary': '后台安装的持久化扩展包'", backend)
        self.assertNotIn("else '沙盒镜像内置包'", backend)
        self.assertIn('function pythonPackageSourceText(item)', frontend)
        self.assertIn('function pythonPackageSummary(item)', frontend)
        self.assertIn('pythonPackageSourceText(item)', frontend)
        self.assertIn('pythonPackageSummary(item)', frontend)
        self.assertIn("'admin.platform.python_source_image':'Built into image'", english)
        self.assertIn("'admin.platform.python_source_image':'镜像内置'", chinese)

    def test_historical_async_job_errors_follow_the_current_ui_language(self):
        errors = (ROOT / 'static/index3/js/index3-app-errors.js').read_text(encoding='utf-8')
        streaming = (ROOT / 'static/index3/js/index3-async-chat-stream-ui.js').read_text(encoding='utf-8')
        english = (ROOT / 'static/i18n/en.js').read_text(encoding='utf-8')
        chinese = (ROOT / 'static/i18n/zh-CN.js').read_text(encoding='utf-8')

        self.assertIn("text === '任务不存在或已过期'", errors)
        self.assertIn("window.AperviaI18n?.t('error.code.async_job_not_found')", errors)
        self.assertEqual(2, streaming.count("asyncChatUiT('error.code.async_job_not_found'"))
        self.assertIn("'error.code.async_job_not_found':'The task no longer exists or has expired.'", english)
        self.assertIn("'error.code.async_job_not_found':'任务不存在或已过期。'", chinese)

    def test_language_changes_use_the_profile_store_and_do_not_touch_protocol_mode(self):
        store = (ROOT / 'app3_parts/auth/platform_auth_chat_store_part.py').read_text(encoding='utf-8')
        routes = (ROOT / 'app3_parts/auth/platform_auth_routes_part.py').read_text(encoding='utf-8')
        frontend = (ROOT / 'static/index3/js/index3-account-cloud-lifecycle.js').read_text(encoding='utf-8')
        self.assertIn("'ui_language': ui_language", store)
        self.assertIn("@app.post('/api3/auth/ui-language')", routes)
        self.assertIn("persistAccount:true", frontend)
        combined = store + routes + frontend
        self.assertNotIn('chat_mode = language', combined)
        self.assertNotIn('responses_mode = language', combined)

    def test_account_version_check_is_manual_and_bilingual(self):
        html = (ROOT / 'static/index3.html').read_text(encoding='utf-8')
        frontend = (ROOT / 'static/index3/js/index3-account-cloud-lifecycle.js').read_text(encoding='utf-8')
        backend = (ROOT / 'app3_parts/auth/platform_auth_release_announcement_part.py').read_text(encoding='utf-8')
        routes = (ROOT / 'app3_parts/auth/platform_auth_routes_part.py').read_text(encoding='utf-8')
        self.assertIn('id="accountVersionCheckBtn"', html)
        self.assertIn('id="accountVersionReleaseLink"', html)
        self.assertIn("accountVersionCheckBtnEl.addEventListener('click'", frontend)
        self.assertIn("fetch('/api3/auth/version-check'", frontend)
        self.assertIn("@app.get('/api3/auth/version-check')", routes)
        self.assertIn("API_URL = 'https://api.github.com/repos/wdyh1314520-gif/apervia-open-source/releases/latest'", backend)
        self.assertNotIn('request.args.get', backend)

    def test_dynamic_settings_feedback_uses_i18n_resources(self):
        mcp = (ROOT / 'static/index3/js/index3-settings-mcp-ui.js').read_text(encoding='utf-8')
        image = (ROOT / 'static/index3/js/index3-settings-image-ui.js').read_text(encoding='utf-8')
        data = (ROOT / 'static/index3/js/index3-settings-data-ui.js').read_text(encoding='utf-8')
        self.assertIn("t('settings.mcp.url_required')", mcp)
        self.assertIn("'settings.image.key_saved'", image)
        self.assertIn('imageApiDisplayName(name)', image)
        self.assertIn("t('settings.data.no_chats')", data)
        self.assertNotIn('toast("图片 Key 已保存")', image)
        self.assertNotIn("toast('没有可删除的会话')", data)

    def test_usage_footer_uses_bilingual_resources(self):
        usage = (ROOT / 'static/index3/js/index3-store-cloud-sync.js').read_text(encoding='utf-8')
        media = (ROOT / 'static/index3/js/index3-message-media-render-ui.js').read_text(encoding='utf-8')
        english = (ROOT / 'static/i18n/en.js').read_text(encoding='utf-8')
        chinese = (ROOT / 'static/i18n/zh-CN.js').read_text(encoding='utf-8')
        self.assertIn("t('chat.usage.input'", usage)
        self.assertIn("t('chat.usage.summary'", usage)
        self.assertIn("t('chat.usage.aria_label'", media)
        self.assertNotIn('`用量：${parts.join', usage)
        self.assertIn("'chat.usage.summary':'Usage: {parts} tokens'", english)
        self.assertIn("'chat.usage.summary':'用量：{parts} tokens'", chinese)

    def test_file_library_source_labels_use_stable_types(self):
        composer = (ROOT / 'static/index3/js/index3-composer-library-ui.js').read_text(encoding='utf-8')
        library = (ROOT / 'static/index3/js/index3-knowledge-base-ui.js').read_text(encoding='utf-8')
        backend = (ROOT / 'app3_parts/knowledge/file_library_part.py').read_text(encoding='utf-8')
        english = (ROOT / 'static/i18n/en.js').read_text(encoding='utf-8')
        chinese = (ROOT / 'static/i18n/zh-CN.js').read_text(encoding='utf-8')
        self.assertIn('function fileLibrarySourceKind(item)', composer)
        self.assertIn('function fileLibrarySourceLabel(item)', composer)
        self.assertIn('fileLibrarySourceLabel(item)', library)
        self.assertNotIn('item?.source_label ||', composer)
        self.assertNotIn("item.source_label ||", library)
        self.assertNotIn("'source_label':", backend)
        self.assertNotIn('def _file_library_source_label', backend)
        self.assertIn("'library.source.generated':'Generated file'", english)
        self.assertIn("'library.source.generated':'生成文件'", chinese)

    def test_mcp_dynamic_cards_and_admin_storage_label_are_bilingual(self):
        mcp = (ROOT / 'static/index3/js/index3-settings-mcp-ui.js').read_text(encoding='utf-8')
        admin = (ROOT / 'static/platform-admin/index.html').read_text(encoding='utf-8')
        english = (ROOT / 'static/i18n/en.js').read_text(encoding='utf-8')
        chinese = (ROOT / 'static/i18n/zh-CN.js').read_text(encoding='utf-8')
        self.assertIn("mcpUiT('settings.mcp.arguments'", mcp)
        self.assertIn("mcpUiT('settings.mcp.state.pending'", mcp)
        self.assertIn("mcpUiT('settings.mcp.scan_connecting'", mcp)
        self.assertIn('data-i18n="admin.platform.mcp_encrypted_storage"', admin)
        self.assertIn("'settings.mcp.always_allow':'Always allow'", english)
        self.assertIn("'settings.mcp.always_allow':'始终允许'", chinese)
        self.assertNotIn('argsLabel.textContent="调用参数"', mcp)
        self.assertNotIn('setMcpSettingsHint("正在连接并读取 tools/list…"', mcp)

    def test_admin_maintenance_labels_come_from_stable_target_ids(self):
        admin = (ROOT / 'static/platform-admin/platform-admin.js').read_text(encoding='utf-8')
        html = (ROOT / 'static/platform-admin/index.html').read_text(encoding='utf-8')
        self.assertIn('admin.platform.maintenance_target.${safeTarget}', admin)
        self.assertNotIn("label='全部维护库'", admin)
        self.assertNotIn('data-deep-label=', html)

    def test_admin_account_controls_use_i18n_resources(self):
        admin = (ROOT / 'static/platform-admin/platform-admin.js').read_text(encoding='utf-8')
        english = (ROOT / 'static/i18n/en.js').read_text(encoding='utf-8')
        chinese = (ROOT / 'static/i18n/zh-CN.js').read_text(encoding='utf-8')
        self.assertIn("custom?'admin.platform.custom_limit':'admin.platform.default_limit'", admin)
        self.assertIn('function accountActionLabel(action)', admin)
        self.assertIn("adminT('admin.platform.purge_guest_data'", admin)
        self.assertIn("'admin.platform.custom_limit':'Custom limit'", english)
        self.assertIn("'admin.platform.custom_limit':'自定义额度'", chinese)
        self.assertNotIn('<span class="pill ok">自定义额度</span>', admin)
        self.assertNotIn('data-save-limit="${owner}">保存</button>', admin)

    def test_builtin_api_name_and_model_feedback_are_localized(self):
        shell = (ROOT / 'static/index3/js/index3-settings-ui.js').read_text(encoding='utf-8')
        profiles = (ROOT / 'static/index3/js/index3-settings-api-profiles-ui.js').read_text(encoding='utf-8')
        models = (ROOT / 'static/index3/js/index3-settings-models-ui.js').read_text(encoding='utf-8')
        self.assertIn('function apiProfileDisplayName(name)', shell)
        self.assertIn('apiProfileDisplayName(name)', profiles)
        self.assertIn("t('settings.models.save_current_key')", models)
        self.assertIn("t('settings.models.enter_model_id')", models)
        self.assertNotIn("toast('请输入模型 ID')", models)

    def test_web_validation_uses_stable_error_codes(self):
        backend = (ROOT / 'app3_parts/web/web_search_provider_core_part.py').read_text(encoding='utf-8')
        frontend = (ROOT / 'static/index3/js/index3-settings-web-ui.js').read_text(encoding='utf-8')
        self.assertIn("'code': 'uapipro_api_key_missing'", backend)
        self.assertIn("'code': 'uapipro_base_url_missing'", backend)
        self.assertIn('function webSettingsValidationMessage(item)', frontend)

    def test_chat_activity_errors_and_default_share_title_are_localized(self):
        errors = (ROOT / 'static/index3/js/index3-app-errors.js').read_text(encoding='utf-8')
        activity = (ROOT / 'static/index3/js/index3-activity-panel-ui.js').read_text(encoding='utf-8')
        share = (ROOT / 'static/index3/js/index3-share-ui.js').read_text(encoding='utf-8')
        self.assertIn("t('error.ai_service_detail'", errors)
        self.assertIn("t('activity.completed_elapsed'", activity)
        self.assertIn('function _activitySearchSystemTitle(title,state)', activity)
        self.assertIn("_activityT('activity.knowledge_hits'", activity)
        self.assertNotIn("title = /命中\\s*\\d+/.test(titleRaw) ? titleRaw", activity)
        self.assertIn("t('activity.no_expandable')", (ROOT / 'static/index3/js/index3-shared-render-reasoning.js').read_text(encoding='utf-8'))
        reasoning = (ROOT / 'static/index3/js/index3-shared-render-reasoning.js').read_text(encoding='utf-8')
        async_stream = (ROOT / 'static/index3/js/index3-async-chat-stream-ui.js').read_text(encoding='utf-8')
        self.assertIn("'stream.connecting_model'", reasoning)
        self.assertIn("t('stream.other_sessions'", async_stream)
        self.assertIn('function sessionDisplayTitle(value)', reasoning)
        self.assertNotIn('function chatShareDisplayTitle(value)', share)
        self.assertIn('sessionDisplayTitle(session.title)', share)
        self.assertIn("setAttribute('aria-label',window.AperviaI18n?.t('common.close')", errors)

    def test_temporary_chat_tooltip_is_data_driven(self):
        chat = (ROOT / 'static/index3/js/index3-chat-render-ui.js').read_text(encoding='utf-8')
        css = (ROOT / 'static/index3/css/index3-settings.css').read_text(encoding='utf-8')
        self.assertIn('setAttribute("data-tooltip", temporaryDesc)', chat)
        self.assertIn('content:attr(data-tooltip)', css)
        self.assertNotIn('content:"此对话将不会出现在历史记录中，且您的消息不会被保存"', css)

    def test_share_message_actions_and_auth_errors_use_resources(self):
        actions = (ROOT / 'static/index3/js/index3-message-actions-ui.js').read_text(encoding='utf-8')
        share = (ROOT / 'static/index3/js/index3-share-ui.js').read_text(encoding='utf-8')
        mcp = (ROOT / 'static/index3/js/index3-settings-mcp-ui.js').read_text(encoding='utf-8')
        errors = (ROOT / 'static/index3/js/index3-app-errors.js').read_text(encoding='utf-8')
        self.assertIn("t('message.copy')", actions)
        self.assertIn("messageActionT('message.read_aloud'", actions)
        self.assertIn("messageActionT('message.share_through'", actions)
        self.assertIn("messageActionT('message.continue_title'", actions)
        self.assertIn("messageActionT('message.regenerate_title'", actions)
        self.assertNotIn("retryBtn.title = '重新生成这条回答'", actions)
        self.assertNotIn("decorateBubbleActionButton(shareBtn, 'share', '分享截至此处的对话')", actions)
        markdown = (ROOT / 'static/index3/js/index3-render-markdown-ui.js').read_text(encoding='utf-8')
        self.assertIn("markdownUiT('code.copy'", markdown)
        self.assertIn("markdownUiT('code.lines'", markdown)
        self.assertNotIn('data-copy-code="${copyAttr}">复制代码</button>', markdown)
        chat_render = (ROOT / 'static/index3/js/index3-chat-render-ui.js').read_text(encoding='utf-8')
        self.assertIn("chatRenderT('chat.edit.remove_attachment'", chat_render)
        self.assertIn("chatRenderT('chat.loading_conversation'", chat_render)
        self.assertNotIn('removeBtn.setAttribute("aria-label", "移除附件")', chat_render)
        self.assertIn("t('share.wechat_copied')", share)
        self.assertIn("t('settings.mcp.directory_load_failed'", mcp)
        self.assertIn("text === '请先登录'", errors)

    def test_click_only_data_memory_location_and_library_feedback_uses_resources(self):
        data = (ROOT / 'static/index3/js/index3-settings-data-ui.js').read_text(encoding='utf-8')
        memory = (ROOT / 'static/index3/js/index3-personalization-memory-ui.js').read_text(encoding='utf-8')
        browser_context = (ROOT / 'static/index3/js/index3-browser-context.js').read_text(encoding='utf-8')
        library = (ROOT / 'static/index3/js/index3-knowledge-base-ui.js').read_text(encoding='utf-8')
        self.assertIn("settingsDataT('settings.data.remote_delete_title'", data)
        self.assertIn("settingsDataT('settings.data.archived_notice'", data)
        self.assertIn("personalizationMemoryT('memory.history_empty'", memory)
        self.assertIn("personalizationMemoryT('memory.no_clearable'", memory)
        self.assertIn("geoUiText('location.permission_denied'", browser_context)
        self.assertIn("'location.permission_prompt_title'", browser_context)
        self.assertIn("'location.permission_prompt_desc'", browser_context)
        self.assertIn("'common.confirm'", browser_context)
        self.assertIn("'common.cancel'", browser_context)
        self.assertNotIn("locationPermissionPromptText(payload, 'title', '需要使用你的位置来回答这个问题')", browser_context)
        self.assertIn("kbT('library.kb.delete_title'", library)
        self.assertIn("kbT('library.kb.delete_desc'", library)
        self.assertIn("kbT('library.upload.partial_failed'", library)
        self.assertIn("library.upload.operation.${operationKey}", library)
        self.assertIn('normalizeCompactErrorText(data)', library)
        self.assertNotIn('同步目录部分失败：成功', library)

    def test_attachment_code_runner_and_knowledge_dynamic_states_use_resources(self):
        attachments = (ROOT / 'static/index3/js/index3-composer-attachments-ui.js').read_text(encoding='utf-8')
        dragdrop = (ROOT / 'static/index3/js/index3-upload-dragdrop-ui.js').read_text(encoding='utf-8')
        main = (ROOT / 'static/index3/js/index3.js').read_text(encoding='utf-8')
        markdown = (ROOT / 'static/index3/js/index3-render-markdown-ui.js').read_text(encoding='utf-8')
        knowledge = (ROOT / 'static/index3/js/index3-knowledge-base-ui.js').read_text(encoding='utf-8')
        code_routes = (ROOT / 'app3_parts/media/misc_api_routes_part.py').read_text(encoding='utf-8')
        self.assertIn("composerAttachmentT('composer.attachment.add_failed'", dragdrop)
        self.assertIn("composerAttachmentT('composer.attachment.add_failed'", main)
        self.assertIn("composerAttachmentT('composer.attachment.parsed_ready'", attachments)
        self.assertIn("composerAttachmentT('composer.attachment.file_indexed'", attachments)
        self.assertIn("composerAttachmentT('composer.attachment.image_upload_failed'", attachments)
        self.assertIn("composerAttachmentT('composer.attachment.limit_images'", attachments)
        self.assertIn("composerAttachmentT('composer.attachment.images_added_processing'", attachments)
        self.assertNotIn('markLocalUploadingPreviewError(previewId, "添加失败")', dragdrop)
        self.assertNotIn("metaText:att.kb_imported ? '文件 · 已入库' : '文件'", attachments)
        self.assertNotIn("x.title = \"移除附件\"", attachments)
        self.assertNotIn("setStatus('已添加图片（处理中，完成后可发送）')", attachments)
        self.assertIn("markdownUiT('code.runner.preview_title'", markdown)
        self.assertIn('resolveCodeRunnerLocalizedValue', markdown)
        self.assertIn("markdownUiT('citation.source_count'", markdown)
        self.assertNotIn("title:'运行失败'", markdown)
        self.assertIn("kbT('library.kb.document_delete_title'", knowledge)
        self.assertIn("kbT('library.kb.search_failed'", knowledge)
        self.assertIn("'code_language_unsupported'", code_routes)
        self.assertIn("'code_runtime_missing'", code_routes)

    def test_upload_transport_preserves_structured_error_codes(self):
        upload = (ROOT / 'static/index3/js/index3-upload-dragdrop-ui.js').read_text(encoding='utf-8')
        self.assertIn('function uploadResponseError(data,status=0)', upload)
        self.assertIn('normalizeCompactErrorText(payload)', upload)
        self.assertIn('throw uploadResponseError(data,res.status)', upload)
        self.assertIn('reject(uploadResponseError(data,xhr.status))', upload)


    def test_i18n_resources_have_no_duplicate_keys(self):
        for path in (ROOT / 'static/i18n/en.js', ROOT / 'static/i18n/zh-CN.js'):
            duplicates = sorted(key for key, count in Counter(_resource_key_list(path)).items() if count > 1)
            self.assertEqual([], duplicates, f'duplicate i18n keys in {path.name}')

    def test_literal_frontend_i18n_keys_exist_in_both_languages(self):
        english = _resource_keys(ROOT / 'static/i18n/en.js')
        chinese = _resource_keys(ROOT / 'static/i18n/zh-CN.js')
        sources = list((ROOT / 'static').rglob('*.js')) + list((ROOT / 'static').rglob('*.html'))
        sources += list((ROOT / 'app3_parts/auth').rglob('*.py')) + [ROOT / 'app3_parts/mcp/client_runtime_part.py']
        patterns = (
            re.compile(r'data-i18n(?:-[a-z-]+)?=["\']([^"\']+)["\']'),
            re.compile(r'(?:AperviaI18n\?\.|globalThis\.AperviaI18n\?\.)t\(\s*["\']([^"\']+)["\']'),
            re.compile(r'\b(?:adminT|adminTP|rateT|blacklistT|accountUiT|dialogUiT|settingsDataT|storageSpaceT|asyncChatUiT|indexUiT|streamRuntimeT|cloudSyncUiT|voiceUiT|composerAttachmentT|composerLibraryT|messageMediaT|settingsUiT|mcpUiT|kbT|chatRenderT|markdownUiT|personalizationMemoryT|geoUiText|shareT|userMessageCollapseT)\(\s*["\']([^"\']+)["\']'),
        )
        missing = []
        for path in sources:
            source = path.read_text(encoding='utf-8')
            for pattern in patterns:
                for key in pattern.findall(source):
                    if '{' in key:
                        continue
                    if key not in english or key not in chinese:
                        missing.append(f'{path.relative_to(ROOT)}: {key}')
        self.assertEqual([], sorted(set(missing)))

    def test_high_risk_visible_text_sinks_do_not_bypass_i18n(self):
        roots = (ROOT / 'static', ROOT / 'app3_parts/auth')
        han = re.compile(r'[\u3400-\u9fff]')
        sink = re.compile(r'''(?:textContent|innerText|innerHTML|\.title\s*=|setAttribute\(\s*['\"](?:aria-label|title|placeholder)|setStatus\s*\(|setStatusForSession\s*\(|setMsg\s*\(|toast\s*\(|reportAppError\s*\(|throw\s+new\s+(?:Error|RuntimeError)|\b(?:alert|confirm|prompt)\s*\()''')
        localized = re.compile(r'(?:AperviaI18n|\b\w+(?:Ui)?T\s*\(|adminT\s*\(|adminTP\s*\(|rateT\s*\(|blacklistT\s*\(|normalizeStreamStatusText|\.phrase\s*\()')
        compatibility_exceptions = {
            ('static/index3/js/index3-settings-voice-ui.js', "if(hintEl && !hintEl.hidden && /当前浏览器不支持网页 API/.test"),
        }
        violations = []
        for root in roots:
            for path in root.rglob('*'):
                if path.suffix.lower() not in {'.js', '.py'}:
                    continue
                for line_number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith(('//', '/*', '*', '#')):
                        continue
                    relative = path.relative_to(ROOT).as_posix()
                    if any(relative == item_path and marker in line for item_path, marker in compatibility_exceptions):
                        continue
                    if han.search(line) and sink.search(line) and not localized.search(line):
                        violations.append(f'{relative}:{line_number}')
        self.assertEqual([], violations)

    def test_all_application_shells_default_to_english(self):
        sources = (
            ROOT / 'static/index3.html',
            ROOT / 'static/chat-share.html',
            ROOT / 'static/platform-admin/index.html',
            ROOT / 'app3_parts/auth/platform_auth_identity_routes_part.py',
            ROOT / 'app3_parts/mcp/client_runtime_part.py',
        )
        for path in sources:
            source = path.read_text(encoding='utf-8')
            self.assertIn('<html lang="en">', source, path.name)

    def test_public_share_page_is_bilingual_and_preserves_message_content(self):
        html = (ROOT / 'static/chat-share.html').read_text(encoding='utf-8')
        script = (ROOT / 'static/chat-share.js').read_text(encoding='utf-8')
        for marker in ('/static/shared/i18n.js', '/static/i18n/en.js', '/static/i18n/zh-CN.js', 'window.AperviaI18n?.start()'):
            self.assertIn(marker, html)
        self.assertIn('data-i18n="share.public_badge"', html)
        self.assertIn('shareT(\'share.scope_snapshot\'', script)
        self.assertIn('share-content message-content', script)
        self.assertIn("['New chat', 'New conversation', '新会话', '新对话']", script)

    def test_voice_presets_and_live_voice_states_use_i18n(self):
        voice_settings = (ROOT / 'static/index3/js/index3-settings-voice-ui.js').read_text(encoding='utf-8')
        voice_runtime = (ROOT / 'static/index3/js/index3-voice-ui.js').read_text(encoding='utf-8')
        html = (ROOT / 'static/index3.html').read_text(encoding='utf-8')
        self.assertIn('VOICE_SETTINGS_SCHEMA_VERSION: 3', voice_settings)
        self.assertIn('language: "auto"', voice_settings)
        self.assertIn('readAloudPresetText(key, \'label\')', voice_settings)
        self.assertIn("readAloudPresetText(key, 'instructions')", voice_settings)
        self.assertIn('data-i18n="settings.voice.preset.qinglan.label"', html)
        self.assertIn("voiceUiT('voice.listening'", voice_runtime)
        self.assertIn("voiceUiT('voice.input_active'", voice_runtime)

    def test_assistant_usage_summary_follows_interface_language(self):
        usage = (ROOT / 'static/index3/js/index3-store-cloud-sync.js').read_text(encoding='utf-8')
        media = (ROOT / 'static/index3/js/index3-message-media-render-ui.js').read_text(encoding='utf-8')
        en = (ROOT / 'static/i18n/en.js').read_text(encoding='utf-8')
        zh = (ROOT / 'static/i18n/zh-CN.js').read_text(encoding='utf-8')
        for key in (
            'chat.usage.input',
            'chat.usage.output',
            'chat.usage.total',
            'chat.usage.reasoning',
            'chat.usage.cached',
            'chat.usage.summary',
            'chat.usage.aria_label',
        ):
            self.assertIn(key, en)
            self.assertIn(key, zh)
        self.assertIn("t('chat.usage.summary'", usage)
        self.assertIn("t('chat.usage.reasoning'", usage)
        self.assertIn("t('chat.usage.cached'", usage)
        self.assertNotIn('`用量：${parts.join', usage)
        self.assertIn("t('chat.usage.aria_label'", media)
        self.assertNotIn("node.setAttribute('aria-label', 'Token 用量')", media)

    def test_weather_system_prompts_follow_interface_language(self):
        weather_core = (ROOT / 'app3_parts/chat/weather_card_core_part.py').read_text(encoding='utf-8')
        media = (ROOT / 'static/index3/js/index3-message-media-render-ui.js').read_text(encoding='utf-8')
        en = (ROOT / 'static/i18n/en.js').read_text(encoding='utf-8')
        zh = (ROOT / 'static/i18n/zh-CN.js').read_text(encoding='utf-8')
        for key in (
            'weather.location_required',
            'weather.location_required_action',
            'weather.service_unavailable',
            'weather.service_unavailable_action',
        ):
            self.assertIn(key, weather_core if key.startswith('weather.') else media)
            self.assertIn(key, media)
            self.assertIn(key, en)
            self.assertIn(key, zh)
        self.assertIn('if(row.need_location)', media)
        self.assertIn('weatherSystemMessage(data)', media)
        self.assertIn('weatherSystemTips(data)', media)
        self.assertNotIn('要直接显示天气卡片，需要城市名', weather_core)
        self.assertNotIn('例如：北京天气', weather_core)
        self.assertNotIn('要显示天气卡片，需要地点或定位', media)

    def test_dynamic_chat_and_settings_text_use_i18n_resources(self):
        en = (ROOT / 'static/i18n/en.js').read_text(encoding='utf-8')
        zh = (ROOT / 'static/i18n/zh-CN.js').read_text(encoding='utf-8')
        account = (ROOT / 'static/index3/js/index3-account-cloud-lifecycle.js').read_text(encoding='utf-8')
        async_chat = (ROOT / 'static/index3/js/index3-async-chat-stream-ui.js').read_text(encoding='utf-8')
        quote = (ROOT / 'static/index3/js/index3-composer-quote-runtime-ui.js').read_text(encoding='utf-8')
        media = (ROOT / 'static/index3/js/index3-message-media-render-ui.js').read_text(encoding='utf-8')
        mcp = (ROOT / 'static/index3/js/index3-settings-mcp-ui.js').read_text(encoding='utf-8')
        settings = (ROOT / 'static/index3/js/index3-settings-ui.js').read_text(encoding='utf-8')
        for key in (
            'sync.conversation_loading_retry',
            'sync.account_synced',
            'composer.upload_wait_index',
            'composer.quote_label',
            'message.image_loading',
            'message.ai_writing_file',
            'weather.next_12_hours',
            'settings.mcp.approval_request',
            'settings.mcp.arguments',
            'settings.value.auto',
            'settings.generation.max_output_tokens',
        ):
            self.assertIn(f"'{key}'", en)
            self.assertIn(f"'{key}'", zh)
        self.assertIn("accountUiT('sync.account_synced'", account)
        self.assertIn("t('composer.upload_wait_index'", async_chat)
        self.assertIn("composerQuoteT('composer.quote_label'", quote)
        self.assertIn("messageMediaT('message.image_loading'", media)
        self.assertIn("mcpUiT('settings.mcp.approval_request'", mcp)
        self.assertIn('function settingsUiT(key, params=null, fallback=', settings)
        self.assertIn("settingsUiT('settings.generation.max_output_tokens'", settings)
        self.assertIn('function asyncChatUiT(key, params=null, fallback=', async_chat)
        self.assertNotIn('asyncStreamT(', async_chat)
        self.assertNotIn("setStatus('当前对话还在加载，网络恢复后会自动重试')", account)
        self.assertNotIn('argsLabel.textContent="调用参数"', mcp)
        self.assertNotIn('title.textContent = "未来 12 小时"', media)

    def test_removed_voice_gateway_presets_have_no_public_runtime_entry(self):
        html = (ROOT / 'static/index3.html').read_text(encoding='utf-8')
        voice = (ROOT / 'static/index3/js/index3-settings-voice-ui.js').read_text(encoding='utf-8')
        phrases = (ROOT / 'static/i18n/en-phrases.js').read_text(encoding='utf-8')
        combined = '\n'.join((html, voice, phrases)).lower()
        for marker in ('yunwu', 'vectorengine', '云雾', '向量引擎'):
            self.assertNotIn(marker, combined)
        self.assertIn('["custom", "openai"]', voice)

    def test_mcp_runtime_statuses_and_default_session_dialog_are_localized(self):
        mcp = (ROOT / 'static/index3/js/index3-settings-mcp-ui.js').read_text(encoding='utf-8')
        dialogs = (ROOT / 'static/index3/js/index3-dialogs.js').read_text(encoding='utf-8')
        reasoning = (ROOT / 'static/index3/js/index3-shared-render-reasoning.js').read_text(encoding='utf-8')
        static_routes = (ROOT / 'app3_parts/platform/platform_static_file_routes_part.py').read_text(encoding='utf-8')
        en = (ROOT / 'static/i18n/en.js').read_text(encoding='utf-8')
        zh = (ROOT / 'static/i18n/zh-CN.js').read_text(encoding='utf-8')
        for key in (
            'settings.mcp.scan_connecting',
            'settings.mcp.scan_succeeded',
            'settings.mcp.oauth_continue',
            'settings.mcp.permission_updated',
            'settings.mcp.activity.running',
        ):
            self.assertIn(f"'{key}'", en)
            self.assertIn(f"'{key}'", zh)
            self.assertIn(f"mcpUiT('{key}'", mcp)
        self.assertNotIn('setMcpSettingsHint("正在连接并读取 tools/list…"', mcp)
        self.assertNotIn('let title=approval ? `等待授权：${label}` : `正在执行：${label}`', mcp)
        self.assertIn("t === '新会话'", reasoning)
        self.assertIn("reasoningUiT('nav.new_session', null, 'New conversation')", reasoning)
        self.assertIn('sessionDisplayTitle(session?.title)', dialogs)
        self.assertIn("frontend_20260724_i18n_v2", static_routes)

    def test_activity_history_localization_uses_structured_operations(self):
        activity = (ROOT / 'static/index3/js/index3-activity-panel-ui.js').read_text(encoding='utf-8')
        en = (ROOT / 'static/i18n/en.js').read_text(encoding='utf-8')
        zh = (ROOT / 'static/i18n/zh-CN.js').read_text(encoding='utf-8')
        self.assertIn('function _activitySystemTitleFromPayload(item, title, state)', activity)
        self.assertIn("sandbox_run_outputs:{slug:'generate_files'", activity)
        self.assertIn("`settings.mcp.activity.${statusKey}`", activity)
        self.assertIn('function _activityDisplayDetailForItem(item, fallback=', activity)
        for key in (
            'activity.sandbox_run.generate_files.done',
            'activity.sandbox_run.run_check.done',
            'activity.sandbox_run.files_changed',
            'activity.sandbox_run.target_file',
        ):
            self.assertIn(f"'{key}'", en)
            self.assertIn(f"'{key}'", zh)

    def test_default_conversation_name_is_consistent_in_english(self):
        en = (ROOT / 'static/i18n/en.js').read_text(encoding='utf-8')
        dialogs = (ROOT / 'static/index3/js/index3-dialogs.js').read_text(encoding='utf-8')
        share = (ROOT / 'static/index3/js/index3-share-ui.js').read_text(encoding='utf-8')
        sidebar = (ROOT / 'static/index3/js/index3-sidebar-session-ui.js').read_text(encoding='utf-8')
        reasoning = (ROOT / 'static/index3/js/index3-shared-render-reasoning.js').read_text(encoding='utf-8')
        for key in ('nav.new_chat', 'nav.search_new_chat', 'nav.new_session', 'dialog.new_chat', 'admin.platform.new_chat'):
            self.assertIn(f"'{key}':'New conversation'", en)
        self.assertNotIn(":'New chat'", en)
        self.assertIn("t === 'New chat'", reasoning)
        self.assertIn('sessionDisplayTitle(session?.title)', dialogs)
        self.assertIn('sessionDisplayTitle(session.title)', share)
        self.assertIn('sessionDisplayTitle(s.title)', sidebar)
        self.assertNotIn('function chatShareDisplayTitle', share)
        self.assertNotIn('function sidebarSessionDisplayTitle', sidebar)
        self.assertNotIn("null, 'New chat'", sidebar)

if __name__ == '__main__':
    unittest.main()
