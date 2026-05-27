#!/usr/bin/env python3
"""多公司勤奋指数看板 - 主服务"""

import json
import os
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from core import load_data

PORT = int(os.environ.get('DASHBOARD_PORT', 8090))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
CACHE_DIR = os.path.join(BASE_DIR, 'cache')

# 公司运行时状态：{company_id: {config, token_cache, data_cache, lock}}
_companies = {}


def load_configs():
    """扫描 config/ 目录加载所有公司配置"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    for fname in os.listdir(CONFIG_DIR):
        if not fname.endswith('.json') or fname == 'example.json':
            continue
        cid = fname[:-5]
        path = os.path.join(CONFIG_DIR, fname)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            _companies[cid] = {
                'config': config,
                'token_cache': {'token': None, 'expires_at': 0},
                'data_cache': {'data': None, 'loading': False, 'last_refresh': 0},
                'lock': threading.Lock(),
            }
            print(f"  已加载: {cid} ({config.get('name', '')})")
        except Exception as e:
            print(f"  加载失败 {fname}: {e}")


def get_cache_file(cid, year=None, months=None):
    if year and months:
        m_str = '-'.join(str(m) for m in sorted(months))
        return os.path.join(CACHE_DIR, f'{cid}_{year}_{m_str}_cache.json')
    return os.path.join(CACHE_DIR, f'{cid}_cache.json')


def save_company_cache(cid, data, year=None, months=None):
    try:
        with open(get_cache_file(cid, year, months), 'w', encoding='utf-8') as f:
            json.dump({'time': time.time(), 'data': data}, f, ensure_ascii=False)
    except Exception:
        pass


def load_company_cache(cid, year=None, months=None):
    try:
        with open(get_cache_file(cid, year, months), 'r', encoding='utf-8') as f:
            return json.load(f).get('data')
    except Exception:
        return None


def get_company_data(cid, year=None, months=None):
    """获取公司数据：优先缓存，后台刷新"""
    co = _companies.get(cid)
    if not co:
        return {'error': f'未找到公司配置: {cid}'}

    cache_key = f'{year}_{months}' if year else 'default'
    dc = co['data_cache']

    with co['lock']:
        # 检查内存缓存是否匹配当前请求
        if dc.get('data') and dc.get('cache_key') == cache_key:
            if time.time() - dc['last_refresh'] > 600 and not dc['loading']:
                dc['loading'] = True
                threading.Thread(target=_bg_refresh, args=(cid, year, months), daemon=True).start()
            return dc['data']
        # 尝试从文件缓存加载
        cached = load_company_cache(cid, year, months)
        if cached:
            dc['data'] = cached
            dc['cache_key'] = cache_key
            dc['last_refresh'] = 0
            return cached
        if dc['loading']:
            return {'loading': True, 'message': '正在获取钉钉考勤数据，请稍候...'}
        dc['loading'] = True
    threading.Thread(target=_bg_refresh, args=(cid, year, months), daemon=True).start()
    return {'loading': True, 'message': '首次加载钉钉数据，请等待...'}


def _bg_refresh(cid, year=None, months=None):
    co = _companies[cid]
    cache_key = f'{year}_{months}' if year else 'default'
    try:
        import traceback
        data = load_data(co['config'], co['token_cache'], year=year, months=months)
        with co['lock']:
            if 'error' not in data:
                co['data_cache']['data'] = data
                co['data_cache']['cache_key'] = cache_key
                co['data_cache']['last_refresh'] = time.time()
                save_company_cache(cid, data, year, months)
                print(f"[{cid}] 数据刷新完成 ({year}, {months})")
            else:
                print(f"[{cid}] 加载失败: {data.get('error')}")
            co['data_cache']['loading'] = False
    except Exception as e:
        import traceback
        traceback.print_exc()
        with co['lock']:
            co['data_cache']['loading'] = False


def force_company_refresh(cid, year=None, months=None):
    co = _companies.get(cid)
    if not co:
        return {'error': f'未找到公司配置: {cid}'}
    cache_key = f'{year}_{months}' if year else 'default'
    with co['lock']:
        co['data_cache']['loading'] = False
    data = load_data(co['config'], co['token_cache'], year=year, months=months)
    with co['lock']:
        if 'error' not in data:
            co['data_cache']['data'] = data
            co['data_cache']['cache_key'] = cache_key
            co['data_cache']['last_refresh'] = time.time()
            save_company_cache(cid, data, year, months)
    return data


def generate_index_html():
    """生成公司列表首页"""
    cards = ''
    for cid, co in _companies.items():
        cfg = co['config']
        color = cfg.get('theme_color', '#C41E3A')
        cards += f'''<a href="/{cid}/" class="company-card" style="--card-color:{color}">
            <div class="company-name">{cfg.get("name", cid)}</div>
            <div class="company-brand" style="color:{color}">{cfg.get("brand", "")}</div>
            <div class="company-path">/{cid}/</div>
        </a>'''
    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>勤奋指数看板 - 公司列表</title>
<style>
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#1A1A1A;color:#fff;margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center}}
h1{{font-size:28px;margin-bottom:8px}}
.sub{{color:#888;margin-bottom:40px;font-size:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px;max-width:900px;width:100%;padding:0 20px}}
.company-card{{background:#222;border:1px solid #333;border-radius:12px;padding:24px;text-decoration:none;color:#fff;transition:transform .2s,box-shadow .2s;border-top:3px solid var(--card-color)}}
.company-card:hover{{transform:translateY(-4px);box-shadow:0 8px 24px color-mix(in srgb,var(--card-color) 40%,transparent);border-color:var(--card-color)}}
.company-name{{font-size:18px;font-weight:700;margin-bottom:4px}}
.company-brand{{font-size:13px;font-weight:600;letter-spacing:1px}}
.company-path{{font-size:12px;color:#666;margin-top:12px}}
</style></head><body>
<h1>勤奋指数看板</h1>
<div class="sub">选择公司查看看板</div>
<div class="grid">{cards}</div>
</body></html>'''


def generate_company_html(cid):
    """生成公司看板 HTML — 带主题色、logo、年月选择器"""
    cfg = _companies[cid]['config']
    name = cfg.get('name', cid)
    brand = cfg.get('brand', 'BRAND')
    theme_color = cfg.get('theme_color', '#C41E3A')
    logo_url = f'/{cid}/logo'
    from _html_template import get_html_template
    return get_html_template(name, brand, theme_color, logo_url, cid)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _parse_time_params(self, query_string):
        """解析 year 和 months 查询参数"""
        params = parse_qs(query_string)
        year = None
        months = None
        if 'year' in params:
            try:
                year = int(params['year'][0])
            except ValueError:
                pass
        if 'months' in params:
            try:
                months = [int(m) for m in params['months'][0].split(',') if m.strip()]
            except ValueError:
                pass
        return year, months

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')
        parts = [p for p in path.split('/') if p]

        if not parts:
            html = generate_index_html()
            self._html(html)
            return

        cid = parts[0]
        if cid not in _companies:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(f'未找到公司: {cid}'.encode('utf-8'))
            return

        sub = '/'.join(parts[1:]) if len(parts) > 1 else ''

        if sub == '' or sub == 'index.html':
            cfg = _companies[cid]['config']
            html = generate_company_html(cid)
            self._html(html)
        elif sub == 'api/data':
            year, months = self._parse_time_params(parsed.query)
            data = get_company_data(cid, year, months)
            self._json(data)
        elif sub == 'api/refresh':
            year, months = self._parse_time_params(parsed.query)
            data = force_company_refresh(cid, year, months)
            self._json(data)
        elif sub == 'logo':
            self._serve_logo(cid)
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_logo(self, cid):
        cfg = _companies[cid]['config']
        logo_file = cfg.get('logo', '')
        logo_path = os.path.join(BASE_DIR, logo_file)
        if not logo_file or not os.path.exists(logo_path):
            self.send_response(404)
            self.end_headers()
            return
        ext = os.path.splitext(logo_file)[1].lower()
        mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'svg': 'image/svg+xml', 'gif': 'image/gif'}.get(ext.lstrip('.'), 'image/png')
        with open(logo_path, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.end_headers()
        self.wfile.write(data)

    def _html(self, content):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(content.encode('utf-8'))

    def _json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))


def main():
    print("=" * 50)
    print("  多公司勤奋指数看板服务")
    print("=" * 50)
    print(f"端口: {PORT}")
    print("加载公司配置...")
    load_configs()
    if not _companies:
        print("错误: config/ 目录下没有找到任何公司配置文件")
        return

    # 加载各公司缓存
    for cid, co in _companies.items():
        cached = load_company_cache(cid)
        if cached:
            co['data_cache']['data'] = cached
            co['data_cache']['last_refresh'] = time.time()
            print(f"  [{cid}] 已加载缓存")

    print(f"\n访问地址: http://localhost:{PORT}/")
    for cid in _companies:
        print(f"  {_companies[cid]['config']['name']}: http://localhost:{PORT}/{cid}/")
    print("\n按 Ctrl+C 停止")

    server = HTTPServer(('0.0.0.0', PORT), Handler)
    threading.Timer(1.0, lambda: webbrowser.open(f'http://localhost:{PORT}')).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.server_close()


if __name__ == '__main__':
    main()

