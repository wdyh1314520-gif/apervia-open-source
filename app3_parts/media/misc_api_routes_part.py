# source favicon, import-image-url, and code runtime API routes.

def source_favicon_route():
    raw_url = str(request.args.get('url') or '').strip()
    raw_host = str(request.args.get('host') or '').strip()
    return _serve_source_favicon(raw_url=raw_url, raw_host=raw_host)


@app.post("/api3/import-image-url")
def import_image_url_gpt():
    payload = request.get_json(silent=True) or {}
    limit_resp = _apply_rate_limit('upload')
    if limit_resp is not None:
        return limit_resp
    url = str(payload.get('url') or '').strip()
    if not url:
        return jsonify({'error': '缺少图片链接'}), 400
    try:
        data = _import_remote_image_to_upload(url)
        return jsonify(data)
    except ValueError as e:
        code = str(e)
        if code == 'gated_remote_image_host':
            return jsonify({'error': '这个图片链接来自受限站点或临时签名地址，服务器无法稳定读取。请先把图片保存到本地后再上传，这样最稳。'}), 400
        if code == 'unsupported_url_scheme':
            return jsonify({'error': '只支持 http/https 图片链接'}), 400
        if code.startswith('unsupported_image_content_type:'):
            return jsonify({'error': '这个链接返回的不是图片，可能是登录页、拦截页或已失效链接。请直接上传图片文件。'}), 400
        if code in ('empty_remote_image', 'remote_image_too_large', 'remote_image_import_failed', 'missing_url'):
            return jsonify({'error': '图片链接导入失败，请直接上传图片文件。'}), 400
        return jsonify({'error': '图片链接导入失败，请直接上传图片文件。'}), 400
    except requests.HTTPError as e:
        return jsonify({'error': f'图片链接导入失败（HTTP {getattr(getattr(e, "response", None), "status_code", "?")}），请直接上传图片文件。'}), 400
    except Exception:
        app_logger.exception('import image url failed: %s', url)
        return jsonify({'error': '图片链接导入失败，请直接上传图片文件。'}), 500



@app.get("/api3/code/runtimes")
def api3_code_runtimes():
    return jsonify({
        'ok': True,
        'languages': _code_run_runtime_matrix(),
    })


def _code_run_error_response(code, error, *, status=400, language='', params=None):
    payload = {
        'ok': False,
        'code': str(code or 'code_execution_failed'),
        'error': str(error or '执行失败'),
    }
    if language:
        payload['language'] = str(language)
    if isinstance(params, dict) and params:
        payload['params'] = params
    return jsonify(payload), int(status)


@app.post("/api3/code/run")
def api3_code_run():
    limit_resp = _apply_rate_limit('upload')
    if limit_resp is not None:
        return limit_resp
    payload = request.get_json(force=True, silent=True) or {}
    language = str(payload.get('language') or '').strip()
    code = str(payload.get('code') or '')
    stdin_text = str(payload.get('stdin') or '')
    normalized = _code_run_normalize_language(language)
    if not normalized:
        return _code_run_error_response('code_language_required', '缺少 language 字段')
    if normalized not in CODE_RUN_SUPPORTED_CANONICAL:
        names = ', '.join(CODE_RUN_LANGUAGE_LABELS.get(x, x) for x in CODE_RUN_SUPPORTED_CANONICAL)
        requested = language or normalized
        return _code_run_error_response(
            'code_language_unsupported',
            f'暂不支持该语言运行：{requested}。当前已接入：{names}',
            language=normalized or language,
            params={'language': requested, 'supported': names},
        )
    if not code.strip():
        return _code_run_error_response('code_empty', '代码为空', language=normalized)
    try:
        result = _code_run_execute(normalized, code, stdin_text=stdin_text)
        return jsonify(result)
    except ValueError as e:
        msg = str(e or '')
        if msg == 'empty_code':
            return _code_run_error_response('code_empty', '代码为空', language=normalized)
        if msg == 'code_too_large':
            return _code_run_error_response('code_too_large', '代码过长，超过当前运行上限', language=normalized)
        if msg == 'unsupported_language':
            return _code_run_error_response(
                'code_language_unsupported',
                '暂不支持该语言运行',
                language=normalized,
                params={'language': normalized, 'supported': ''},
            )
        return _code_run_error_response('code_invalid_request', msg or '执行参数无效', language=normalized)
    except RuntimeError as e:
        raw = str(e or '')
        if raw.startswith('missing_runtime:'):
            missing = raw.split(':', 1)[1].strip() or normalized
            label = CODE_RUN_LANGUAGE_LABELS.get(missing, missing)
            return _code_run_error_response(
                'code_runtime_missing',
                f'服务端当前没有可用的 {label} 运行环境',
                language=normalized,
                params={'runtime': label},
            )
        if raw.startswith('unsupported_language:'):
            return _code_run_error_response(
                'code_language_unsupported',
                '暂不支持该语言运行',
                language=normalized,
                params={'language': normalized, 'supported': ''},
            )
        app_logger.exception('code run runtime error language=%s', normalized)
        return _code_run_error_response('code_execution_failed', raw or '执行失败', status=500, language=normalized)
    except Exception as e:
        app_logger.exception('code run failed language=%s', normalized)
        return _code_run_error_response('code_execution_failed', f'{type(e).__name__}: {e}', status=500, language=normalized)
