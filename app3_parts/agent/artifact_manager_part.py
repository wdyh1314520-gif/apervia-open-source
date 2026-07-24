# Centralized artifact registration/publishing adapter.
# Purpose: generated files should be registered and published immediately through
# one manager path, not left for the model to ask the user to say "链接" later.

import os
import time

ARTIFACT_MANAGER_VERSION = 'artifact_manager_v1_0606'


class ArtifactManager:
    def should_auto_publish(self, *, source_tool: str = '', result: dict | None = None, args: dict | None = None, messages=None) -> bool:
        res = dict(result or {}) if isinstance(result, dict) else {}
        if not bool(res.get('ok')):
            return False
        if bool(res.get('auto_published')) or bool(res.get('files')):
            return False
        path = str(res.get('path') or '').strip()
        if not path:
            return False
        tool = str(source_tool or '').strip()
        if tool == 'sandbox_create_office_file':
            return True
        return False

    def publish_generated(self, *, source_tool: str = '', result: dict | None = None, args: dict | None = None, messages=None) -> dict:
        res = dict(result or {}) if isinstance(result, dict) else {}
        if not self.should_auto_publish(source_tool=source_tool, result=res, args=args, messages=messages):
            return res
        path = str(res.get('path') or '').strip()
        publish_fn = globals().get('_sandbox_publish_files_tool')
        if not callable(publish_fn):
            res['auto_published'] = False
            res['publish_error'] = 'sandbox_publish_files_unavailable'
            res['publish_instruction'] = 'Call sandbox_publish_files with this path when available.'
            return res
        publish_args = {
            'paths': [path],
            'force_zip': False,
            'answer': str((args or {}).get('answer') or '').strip(),
        }
        try:
            publish_result = publish_fn(publish_args, messages=messages or [])
        except Exception as exc:
            publish_result = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
        res['auto_published'] = bool(isinstance(publish_result, dict) and publish_result.get('ok'))
        res['artifact_manager_version'] = ARTIFACT_MANAGER_VERSION
        res['published_at'] = int(time.time())
        if isinstance(publish_result, dict):
            res['publish_result'] = {
                'ok': bool(publish_result.get('ok')),
                'count': int(publish_result.get('count') or 0),
                'published_paths': [str(x or '') for x in (publish_result.get('published_paths') or [])[:40]],
                'error': str(publish_result.get('error') or '')[:260],
            }
            if publish_result.get('ok'):
                for key in ('files', 'delivery_files', 'source_files', 'filenames', 'published_paths', 'sandbox_source_files', 'file_edit_audits', 'edit_audits'):
                    if key in publish_result:
                        res[key] = publish_result.get(key)
                res['published'] = True
                res['publish_instruction'] = 'Already published by ArtifactManager. Final answer should use files[].download_url directly; do not ask the user to reply “链接”.'
            else:
                res['published'] = False
                res['publish_error'] = str(publish_result.get('error') or 'publish_failed')[:260]
                res['publish_instruction'] = 'Artifact was generated but auto-publish failed; call sandbox_publish_files with the path before final delivery.'
        return res


def artifact_manager_auto_publish_generated(result: dict | None = None, args: dict | None = None, messages=None, source_tool: str = '') -> dict:
    return ArtifactManager().publish_generated(source_tool=source_tool, result=result, args=args, messages=messages)


def artifact_manager_policy_prompt() -> str:
    return (
        'ArtifactManager 负责所有生成文件的登记和发布。sandbox_create_office_file 成功后默认自动发布，最终回答必须直接给已发布文件，不要让用户再回复“链接”。'
    )
