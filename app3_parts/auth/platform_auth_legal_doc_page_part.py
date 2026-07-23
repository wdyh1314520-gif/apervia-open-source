# Split from app3_parts/auth/platform_auth_login_pages_part.py.
# Purpose: auth legal document page HTML renderer.
# Loaded by platform_auth_login_pages_part.py via _exec_split_file(...), sharing app3.py globals.

def _auth_legal_doc_html(slug: str) -> str:
    wanted = _auth_terms_slug_value(slug, '')
    config = _auth_terms_current_config(include_content=True)
    docs = list(config.get('documents') or [])
    doc = next((item for item in docs if _auth_terms_slug_value(item.get('slug'), '') == wanted), None)
    if not doc:
        return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>文档不存在 - Apervia</title><style>body{margin:0;background:#f8fafc;color:#111827;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Arial,sans-serif}.wrap{max-width:760px;margin:0 auto;padding:48px 18px}.card{background:#fff;border:1px solid #e5e7eb;border-radius:20px;padding:28px;box-shadow:0 12px 36px rgba(15,23,42,.08)}a{color:#0f766e}</style></head><body><main class="wrap"><section class="card"><h1>文档不存在</h1><p>该协议文档不存在或已被移除。</p><p><a href="/login">返回登录页</a></p></section></main></body></html>'''
    title = str(doc.get('title') or '协议文档').strip() or '协议文档'
    content_html = _auth_terms_markdown_to_html(str(doc.get('content') or ''))
    updated_date = str(config.get('updated_date') or '').strip()
    docs_nav = ''.join('<a class="navItem" href="/legal/' + html.escape(str(item.get('slug') or ''), quote=True) + '">' + html.escape(str(item.get('title') or '协议文档')) + '</a>' for item in docs)
    meta_text = ('更新日期：' + html.escape(updated_date)) if updated_date else 'Apervia 协议文档'
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(title)} - Apervia</title>
  <style>
    body{{margin:0;background:#f8fafc;color:#111827;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Arial,sans-serif;line-height:1.75}}
    .wrap{{max-width:920px;margin:0 auto;padding:34px 18px 54px}}
    .top{{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:18px;flex-wrap:wrap}}
    h1{{margin:0;font-size:30px;letter-spacing:-.03em;line-height:1.25}}
    .meta{{color:#64748b;font-size:13px;margin-top:8px}}
    .back{{color:#0f766e;text-decoration:none;font-weight:700}}
    .layout{{display:grid;grid-template-columns:220px minmax(0,1fr);gap:18px;align-items:start}}
    .nav,.doc{{background:#fff;border:1px solid #e5e7eb;border-radius:20px;box-shadow:0 12px 36px rgba(15,23,42,.06)}}
    .nav{{padding:12px;position:sticky;top:18px}}
    .navItem{{display:block;color:#475569;text-decoration:none;border-radius:12px;padding:10px 11px;font-size:14px}}
    .navItem:hover{{background:#f1f5f9;color:#0f766e}}
    .doc{{padding:28px;min-height:360px}}
    .content h1,.content h2,.content h3,.content h4{{line-height:1.35;margin:1.4em 0 .65em;color:#0f172a}}
    .content h1:first-child,.content h2:first-child{{margin-top:0}}
    .content p{{margin:.85em 0;color:#334155}}
    .content ul,.content ol{{padding-left:1.45em;color:#334155}}
    .content code{{background:#f1f5f9;border-radius:6px;padding:2px 5px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.92em}}
    .content pre{{background:#0f172a;color:#e2e8f0;border-radius:14px;padding:14px;overflow:auto}}
    .content pre code{{background:transparent;color:inherit;padding:0}}
    .content a{{color:#0f766e}}
    .muted{{color:#64748b}}
    @media(max-width:760px){{.layout{{grid-template-columns:1fr}}.nav{{position:static}}.doc{{padding:22px}}}}
  </style>
</head>
<body>
  <main class="wrap">
    <div class="top"><div><h1>{html.escape(title)}</h1><div class="meta">{meta_text}</div></div><a class="back" href="/login">返回登录页</a></div>
    <div class="layout">
      <nav class="nav">{docs_nav}</nav>
      <article class="doc"><div class="content">{content_html}</div></article>
    </div>
  </main>
</body>
</html>'''
