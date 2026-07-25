import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DockerRuntimeConfigTests(unittest.TestCase):
    def test_runtime_data_is_separate_from_code(self):
        source = (ROOT / 'app3.py').read_text(encoding='utf-8')
        self.assertIn("APP_DATA_DIR = os.path.abspath", source)
        self.assertIn("UPLOAD_DIR_LOCAL = _app_data_path", source)
        self.assertIn("AUTH_CHAT_DB_FILE = _app_data_path", (ROOT / 'app3_parts/auth/platform_auth_core_state_part.py').read_text(encoding='utf-8'))

    def test_public_origin_and_secure_cookie_are_explicit(self):
        source = (ROOT / 'app3.py').read_text(encoding='utf-8')
        auth = (ROOT / 'app3_parts/auth/platform_auth_identity_part.py').read_text(encoding='utf-8')
        mcp = (ROOT / 'app3_parts/mcp/client_runtime_part.py').read_text(encoding='utf-8')
        share = (ROOT / 'app3_parts/account/chat_share_part.py').read_text(encoding='utf-8')
        self.assertIn("APP_PUBLIC_ORIGIN", source)
        self.assertIn("APP_PUBLIC_ORIGIN 必须使用 HTTPS", source)
        self.assertIn("secure=_app_cookie_secure()", auth)
        self.assertIn("_app_external_url('/api3/mcp/oauth/callback')", mcp)
        self.assertIn("_app_external_url('/share/'", share)

    def test_proxy_headers_are_not_trusted_by_default(self):
        source = (ROOT / 'app3.py').read_text(encoding='utf-8')
        for name in ('TRUST_PROXY_X_FOR', 'TRUST_PROXY_X_PROTO', 'TRUST_PROXY_X_HOST', 'TRUST_PROXY_X_PORT'):
            self.assertIn(f"os.getenv('{name}', '0')", source)

        request_context = (ROOT / 'app3_parts/auth/platform_auth_request_context_part.py').read_text(encoding='utf-8')
        client_ip = request_context.split('def _client_ip()', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('request.remote_addr', client_ip)
        self.assertNotIn('request.headers', client_ip)
        self.assertNotIn('X-Forwarded-For', client_ip)

        audit = (ROOT / 'app3_parts/storage/platform_admin_audit_recycle_part.py').read_text(encoding='utf-8')
        actor = audit.split('def _platform_admin_request_actor()', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('_client_ip()', actor)
        self.assertNotIn('X-Forwarded-For', actor)

        compose = (ROOT / 'compose.yaml').read_text(encoding='utf-8')
        example = (ROOT / '.env.example').read_text(encoding='utf-8')
        self.assertIn('TRUST_PROXY_X_FOR: ${TRUST_PROXY_X_FOR:-0}', compose)
        self.assertIn('TRUST_PROXY_X_FOR=0', example)

    def test_compose_keeps_protocols_in_one_canonical_app(self):
        compose = (ROOT / 'compose.yaml').read_text(encoding='utf-8')
        app_block, runner_and_after = compose.split('\n  sandbox-runner:', 1)
        runner_block, _ = runner_and_after.split('\n  sandbox-image:', 1)
        self.assertIn('APP_PUBLIC_MODE: "0"', compose)
        self.assertIn('APP_DATA_DIR: /data', compose)
        self.assertIn('"${APP_BIND_IP:-0.0.0.0}:${APP_HOST_PORT:-8002}:8002"', compose)
        self.assertIn('"host.docker.internal:host-gateway"', compose)
        self.assertIn('shm_size: "1gb"', compose)
        self.assertNotIn('caddy:', compose)
        self.assertNotIn('APP_PUBLIC_ORIGIN:', compose)
        self.assertNotIn('"80:80"', compose)
        self.assertNotIn('"443:443"', compose)
        self.assertNotIn('healthcheck:', app_block)
        self.assertNotIn('/var/run/docker.sock', app_block)
        self.assertIn('healthcheck:', runner_block)
        self.assertIn('/var/run/docker.sock:/var/run/docker.sock', runner_block)
        self.assertIn('user: "10001:10001"', runner_block)
        self.assertIn('${DOCKER_SOCKET_GID:-0}', runner_block)
        self.assertIn('entrypoint: ["python", "-m", "sandbox_runner.service"]', runner_block)
        self.assertNotIn('\n    ports:', runner_block)
        self.assertNotIn('chat-service:', compose)
        self.assertNotIn('responses-service:', compose)

    def test_image_uses_overridable_entrypoint_without_docker_cli(self):
        dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
        entrypoint = (ROOT / 'docker-entrypoint.sh').read_text(encoding='utf-8')
        self.assertNotIn('FROM docker:', dockerfile)
        self.assertNotIn('COPY --from=docker_cli', dockerfile)
        self.assertNotIn('\n      libreoffice \\\n', dockerfile)
        for package in ('libreoffice-writer', 'libreoffice-calc', 'libreoffice-impress', 'libreoffice-draw'):
            self.assertIn(package, dockerfile)
        self.assertIn('ENTRYPOINT ["docker-entrypoint.sh"]', dockerfile)
        self.assertIn('CMD ["python", "/app/app3.py"]', dockerfile)
        self.assertIn('exec "$@"', entrypoint)

    def test_code_run_has_no_host_execution_fallback(self):
        source = (ROOT / 'app3_parts/web/code_run_part.py').read_text(encoding='utf-8')
        self.assertNotIn('subprocess.Popen', source)
        self.assertNotIn("'backend': 'docker_sandbox'", source)
        self.assertIn("'backend': 'sandbox_runner'", source)
        self.assertIn("globals().get('_sandbox_run_tool')", source)

    def test_fresh_container_can_initialize_without_provider_key(self):
        client_core = (ROOT / 'app3_parts/media/image_client_core_part.py').read_text(encoding='utf-8')
        self.assertIn("_OPENAI_CLIENT_BOOTSTRAP_KEY = GPT_API_KEY or 'not-configured'", client_core)
        self.assertGreaterEqual(client_core.count('api_key=_OPENAI_CLIENT_BOOTSTRAP_KEY'), 2)

    def test_startup_log_does_not_advertise_a_clickable_url(self):
        startup = (ROOT / 'app3_parts/media/waitress_startup_part.py').read_text(encoding='utf-8')
        self.assertNotIn('http://', startup)
        self.assertNotIn('https://', startup)
        self.assertIn("logging.getLogger('waitress').setLevel(logging.WARNING)", startup)

    def test_image_build_identity_is_visible_in_health(self):
        dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
        app_source = (ROOT / 'app3.py').read_text(encoding='utf-8')
        health = (ROOT / 'app3_parts/account/request_admission_health_part.py').read_text(encoding='utf-8')
        workflow = (ROOT / '.github/workflows/publish-images.yml').read_text(encoding='utf-8')
        self.assertIn('ARG APP_BUILD_VERSION=', dockerfile)
        self.assertIn('COPY VERSION /app/VERSION', dockerfile)
        self.assertIn('COPY release /app/release', dockerfile)
        self.assertIn('APP_BUILD_VERSION = APP_VERSION', app_source)
        self.assertIn('ARG APP_BUILD_SHA=unknown', dockerfile)
        self.assertIn('org.opencontainers.image.revision', dockerfile)
        self.assertIn("_APP_VERSION_FILE = os.path.join", app_source)
        self.assertIn("'build': _app_build_info()", health)
        self.assertIn('APP_BUILD_SHA=${{ github.sha }}', workflow)
        self.assertIn('sbom: true', workflow)
        self.assertIn('provenance: mode=max', workflow)
        self.assertIn('arch: linux/amd64', workflow)
        self.assertIn('arch: linux/arm64', workflow)
        self.assertIn('runner: ubuntu-24.04-arm', workflow)
        self.assertIn('docker://rhysd/actionlint:1.7.12', workflow)
        self.assertEqual(workflow.count('name=${GITHUB_REPOSITORY,,}'), 2)
        normalized_image = '${{ env.REGISTRY }}/${{ steps.image_name.outputs.name }}'
        self.assertIn(f'images: {normalized_image}', workflow)
        self.assertIn(f'IMAGE_REF: {normalized_image}@${{{{ steps.image.outputs.digest }}}}', workflow)
        self.assertIn(f'IMAGE_REPOSITORY: {normalized_image}', workflow)
        self.assertIn(f'docker buildx imagetools inspect "{normalized_image}:', workflow)
        self.assertIn('push-by-digest=true', workflow)
        self.assertIn('Create and push multi-platform manifest', workflow)
        self.assertIn('Require both platform digests', workflow)
        self.assertIn('docker buildx imagetools create "${tag_args[@]}" "${source_images[@]}"', workflow)
        self.assertGreaterEqual(workflow.count('--shm-size 1g'), 2)
        self.assertGreaterEqual(workflow.count('--cap-drop ALL'), 2)
        self.assertIn('from playwright.sync_api import sync_playwright', workflow)
        self.assertIn("['libreoffice','--headless','--convert-to','pdf'", workflow)

    def test_deployment_docs_cover_versioned_recovery(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        readme_zh = (ROOT / 'README.zh-CN.md').read_text(encoding='utf-8')
        self.assertIn('APP_IMAGE=ghcr.io/<owner>/<repository>:1.0.3', readme)
        self.assertIn('apervia-data.tar.gz', readme)
        self.assertIn('Restoring overwrites the current volume data', readme)
        self.assertIn('Rolling back an image does not roll back the database format', readme)
        self.assertIn('恢复会覆盖当前卷内数据', readme_zh)
        self.assertIn('镜像回滚不会自动回滚数据库格式', readme_zh)
        self.assertNotIn('默认只监听宿主机回环地址', readme)
        self.assertNotIn('仅发布 `linux/amd64` 镜像', readme)

    def test_public_auth_uses_server_sessions_and_role_guard(self):
        identity = (ROOT / 'app3_parts/auth/platform_auth_identity_part.py').read_text(encoding='utf-8')
        admin_pages = (ROOT / 'app3_parts/auth/platform_auth_admin_pages_part.py').read_text(encoding='utf-8')
        runtime = (ROOT / 'app3_parts/auth/platform_auth_runtime_init_part.py').read_text(encoding='utf-8')
        compose = (ROOT / 'compose.yaml').read_text(encoding='utf-8')
        env_example = (ROOT / '.env.example').read_text(encoding='utf-8')
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn("AUTH_SESSION_COOKIE = 'apervia_session'", identity)
        self.assertIn('CREATE TABLE IF NOT EXISTS identity_sessions', identity)
        self.assertIn("role TEXT NOT NULL CHECK (role IN ('admin', 'user', 'pending'))", identity)
        self.assertNotIn('_auth_identity_import_legacy_users', identity)
        self.assertNotIn('_auth_identity_bootstrap_admin', identity)
        self.assertNotIn('AUTH_BOOTSTRAP_ADMIN_', compose + env_example + readme)
        self.assertIn('A new data volume does not include, simulate, or import any account automatically', readme)
        self.assertIn('def _admin_page_guard(', admin_pages)
        self.assertIn('_auth_identity_admin_guard()', admin_pages)
        self.assertIn('_auth_identity_current_user()', runtime)
        self.assertFalse((ROOT / 'app3_parts/auth/platform_auth_email_login_page_part.py').exists())
        self.assertFalse((ROOT / 'app3_parts/auth/platform_auth_email_admin_page_part.py').exists())

    def test_removed_mobile_and_captcha_auth_surfaces_do_not_return(self):
        app_source = (ROOT / 'app3.py').read_text(encoding='utf-8')
        requirements = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
        mcp_store = (ROOT / 'app3_parts/mcp/server_store_part.py').read_text(encoding='utf-8')
        platform_loader = (ROOT / 'app3_parts/platform/platform_auth_part.py').read_text(encoding='utf-8')
        rate_limit = (ROOT / 'app3_parts/auth/platform_auth_rate_limit_part.py').read_text(encoding='utf-8')
        account_lifecycle = (ROOT / 'static/index3/js/index3-account-cloud-lifecycle.js').read_text(encoding='utf-8')
        auth_sources = {
            path: path.read_text(encoding='utf-8')
            for path in (ROOT / 'app3_parts' / 'auth').glob('*.py')
        }
        combined_auth = '\n'.join(auth_sources.values())

        self.assertFalse((ROOT / 'app3_parts/platform/mobile_platform_part.py').exists())
        self.assertFalse((ROOT / 'app3_parts/auth/platform_auth_captcha_runtime_part.py').exists())
        self.assertFalse((ROOT / 'app3_parts/auth/platform_auth_device_routes_part.py').exists())
        self.assertFalse((ROOT / 'app3_parts/auth/platform_auth_device_trust_part.py').exists())
        self.assertNotIn('mobile_platform_part.py', app_source)
        self.assertIn('platform_auth_request_context_part.py', platform_loader)
        self.assertIn('cryptography==46.0.6', requirements)
        self.assertIn('from cryptography.fernet import Fernet', mcp_store)
        self.assertNotIn('/api3/mobile', combined_auth)
        self.assertNotIn('/api3/device', combined_auth)
        self.assertNotIn('DEVICE_TRUST', combined_auth)
        self.assertNotIn('device_not_approved', combined_auth + account_lifecycle)
        self.assertNotIn('device_limit', rate_limit)
        self.assertNotIn('device_window_s', rate_limit)
        self.assertNotIn('captcha', combined_auth.lower())
        for legacy_value in (
            '/api3/auth/login',
            '/api3/auth/reset-password',
            'email_code',
        ):
            self.assertNotIn(legacy_value, combined_auth)
        for legacy_endpoint in (
            "'device_status'",
            "'device_request'",
            "'auth_send_code'",
            "'auth_login'",
            "'auth_reset_password'",
            "'auth_request_approval'",
        ):
            self.assertNotIn(legacy_endpoint, rate_limit)
        self.assertNotIn("@app.get('/rate-admin')", combined_auth)
        self.assertNotIn("'/api3/rate-limit/", combined_auth)

    def test_container_has_no_synthetic_local_account(self):
        request_runtime = ROOT / 'app3_parts/account/request_runtime_part.py'
        personalization = (ROOT / 'app3_parts/account/user_personalization_runtime_part.py').read_text(encoding='utf-8')
        quota_reporting = (ROOT / 'app3_parts/storage/storage_quota_reporting_part.py').read_text(encoding='utf-8')
        inventory = (ROOT / 'app3_parts/storage/platform_admin_inventory_part.py').read_text(encoding='utf-8')
        frontend = (ROOT / 'static/index3/js/index3-account-cloud-lifecycle.js').read_text(encoding='utf-8')
        app_source = (ROOT / 'app3.py').read_text(encoding='utf-8')
        self.assertTrue(request_runtime.exists())
        self.assertFalse((ROOT / 'app3_parts/account/local_shell_runtime_part.py').exists())
        self.assertIn("_exec_split_file('app3_parts/account/request_runtime_part.py')", personalization)
        self.assertIn('keys: set[str] = set()', quota_reporting)
        for source in (request_runtime.read_text(encoding='utf-8'), quota_reporting, inventory, frontend, app_source):
            self.assertNotIn('local_shell@local', source)
            self.assertNotIn('LOCAL_SHELL_EMAIL', source)
            self.assertNotIn('ACCOUNT_STORAGE_LOCAL_MAX_BYTES', source)

    def test_active_admin_ui_does_not_transport_legacy_admin_tokens(self):
        active_ui = [
            ROOT / 'static/platform-admin/platform-admin.js',
            ROOT / 'app3_parts/auth/platform_auth_identity_routes_part.py',
            ROOT / 'app3_parts/storage/storage_admin_routes_part.py',
        ]
        for path in active_ui:
            source = path.read_text(encoding='utf-8')
            self.assertNotIn('X-Local-Admin-Token', source, str(path))
            self.assertNotIn('admin_unlock_required', source, str(path))

    def test_docker_admin_excludes_marketing_diagnostics_and_cloudflare_status(self):
        admin_html = (ROOT / 'static/platform-admin/index.html').read_text(encoding='utf-8')
        admin_js = (ROOT / 'static/platform-admin/platform-admin.js').read_text(encoding='utf-8')
        admin_routes = (ROOT / 'app3_parts/storage/platform_admin_routes_part.py').read_text(encoding='utf-8')
        admin_system = (ROOT / 'app3_parts/storage/platform_admin_system_part.py').read_text(encoding='utf-8')
        auth_routes = (ROOT / 'app3_parts/auth/platform_auth_routes_part.py').read_text(encoding='utf-8')
        account_html = (ROOT / 'static/index3.html').read_text(encoding='utf-8')
        account_js = (ROOT / 'static/index3/js/index3-account-cloud-lifecycle.js').read_text(encoding='utf-8')
        active_surface = '\n'.join((admin_html, admin_js, admin_routes, auth_routes, account_html, account_js))
        for removed in (
            'panel-marketing',
            'panel-skills',
            'platform-admin-marketing.js',
            'platform-admin-capabilities.js',
            '/api3/platform-admin/marketing-email',
            '/api3/platform-admin/capabilities',
            '/api3/platform-admin/skills',
            '/api3/auth/privacy-preferences',
            'accountMarketingEmailToggle',
        ):
            self.assertNotIn(removed, active_surface)
        self.assertNotIn('cloudflared', admin_html + admin_js + admin_system)
        self.assertFalse((ROOT / 'app3_parts/auth/platform_auth_marketing_email_part.py').exists())
        self.assertFalse((ROOT / 'static/platform-admin/platform-admin-marketing.js').exists())
        self.assertFalse((ROOT / 'static/platform-admin/platform-admin-capabilities.js').exists())
        self.assertTrue((ROOT / 'app3_parts/tools/skill_registry_part.py').exists())


if __name__ == '__main__':
    unittest.main()
