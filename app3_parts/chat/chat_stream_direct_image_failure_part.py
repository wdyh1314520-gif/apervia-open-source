# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: build system context for failed direct image handoff results.
# Loaded before chat_streaming_part.py, sharing the original global namespace.


class ChatStreamDirectImageFailureContext:
    def __init__(self, *, task_type: str = ''):
        self.task_type = str(task_type or '')

    def build(self, result: dict | None = None) -> str:
        row = dict(result or {}) if isinstance(result, dict) else {}
        if not row or bool(row.get('ok')):
            return ''
        clarification = str(row.get('clarification_question') or '').strip()
        error_text = str(row.get('error') or '').strip()
        attempts = [dict(x) for x in (row.get('attempts') or []) if isinstance(x, dict)]
        if not error_text and attempts:
            error_text = str((attempts[-1] or {}).get('error') or '').strip()
        parts = ['【图片生成/编辑失败上下文】']
        task_label = str(row.get('image_task_type') or self.task_type or '').strip()
        if task_label:
            parts.append('任务类型：' + task_label)
        if bool(row.get('need_clarification')):
            parts.append('工具判断：需要向用户澄清。')
            if clarification:
                parts.append('澄清问题：' + clarification[:1200])
        if error_text:
            parts.append('上游错误原文：' + error_text[:3000])
        else:
            parts.append('上游错误原文：图片生成失败，但上游没有返回明确错误文本。')
        evidence = {
            'tool': 'image_generation',
            'ok': False,
            'stage': 'image_generation_failed',
            'task_type': task_label,
            'need_clarification': bool(row.get('need_clarification')),
            'clarification_question': clarification[:1200] if clarification else '',
            'upstream_error': error_text[:3000] if error_text else '',
        }
        if attempts:
            evidence['attempt_count'] = len(attempts)
            evidence['last_attempt_error'] = str((attempts[-1] or {}).get('error') or '').strip()[:1200]
        try:
            parts.append('结构化失败事实：' + json.dumps(evidence, ensure_ascii=False))
        except Exception:
            parts.append('结构化失败事实：image_generation_failed')
        return '\n'.join([x for x in parts if str(x or '').strip()])[:4200]
