import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _resource_keys(path: Path) -> set[str]:
    source = path.read_text(encoding='utf-8')
    return set(re.findall(r"^\s*'([^']+)'\s*:", source, flags=re.MULTILINE))


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
        sources = [
            (ROOT / 'static/platform-admin/index.html').read_text(encoding='utf-8'),
            (ROOT / 'app3_parts/auth/platform_auth_identity_routes_part.py').read_text(encoding='utf-8'),
            (ROOT / 'app3_parts/auth/platform_auth_rate_limit_admin_page_part.py').read_text(encoding='utf-8'),
            (ROOT / 'app3_parts/auth/platform_auth_blacklist_admin_page_part.py').read_text(encoding='utf-8'),
        ]
        for source in sources:
            self.assertIn('/static/shared/i18n.js', source)
            self.assertIn('/static/i18n/en.js', source)
            self.assertIn('/static/i18n/zh-CN.js', source)
            self.assertIn('syncAccount:true', source)
        self.assertIn('<title data-i18n="admin.platform.document_title">', sources[0])
        storage = (ROOT / 'app3_parts/storage/storage_admin_routes_part.py').read_text(encoding='utf-8')
        self.assertIn("return redirect('/platform-admin'", storage)

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
        self.assertIn('function chatShareDisplayTitle(value)', share)
        self.assertIn("raw === '新会话'", share)
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


if __name__ == '__main__':
    unittest.main()
