#!/usr/bin/env python3
"""多公司勤奋指数看板 - 主服务（优化版）"""

import json
import os
import re
import sys
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# 兼容 PyInstaller 打包
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    _BUNDLE_DIR = sys._MEIPASS
    sys.path.insert(0, _BUNDLE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    _BUNDLE_DIR = BASE_DIR

PORT = int(os.environ.get('DASHBOARD_PORT', 8090))
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
CACHE_DIR = os.path.join(BASE_DIR, 'cache')

# 公司运行时状态
_companies = {}
_server_status = {'start_time': time.time(), 'port': PORT, 'companies': {}}


def _import_core():
    """延迟导入 core 模块"""
    from core import load_data, filter_data_to_months
    return load_data, filter_data_to_months


def load_configs():
    """扫描 config/ 目录加载所有公司配置"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    for fname in sorted(os.listdir(CONFIG_DIR)):
        if not fname.endswith('.json') or fname == 'example.json':
            continue
        cid = fname[:-5]
        path = os.path.join(CONFIG_DIR, fname)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            _companies[cid] = {
                'config': config,
                'token_cache': {},
                'data_cache': {'data': None, 'loading': False, 'last_refresh': 0, 'cache_key': ''},
                'lock': threading.Lock(),
            }
            _server_status['companies'][cid] = {
                'name': config.get('name', cid),
                'status': 'loaded',
                'cache_hit': False,
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


def _find_superset_cache(cid, year, target_months):
    """查找包含目标月份的超集缓存文件
    
    返回 (superset_data, superset_months) 或 (None, None)
    例如: target=[1], 找到 xiwen_2026_1-2-3-4-5_cache.json → 返回数据
    """
    if not year or not target_months:
        return None, None
    target_set = set(target_months)
    prefix = f'{cid}_{year}_'
    
    best_data = None
    best_months = None
    best_count = 0
    
    try:
        for fname in os.listdir(CACHE_DIR):
            if not fname.startswith(prefix) or not fname.endswith('_cache.json'):
                continue
            # 提取月份部分: xiwen_2026_1-2-3-4-5_cache.json → [1,2,3,4,5]
            mid = fname[len(prefix):-len('_cache.json')]
            try:
                cached_months = [int(m) for m in mid.split('-')]
            except ValueError:
                continue
            cached_set = set(cached_months)
            # 检查是否包含目标月份（超集）
            if target_set.issubset(cached_set) and len(cached_months) > best_count:
                data = load_company_cache(cid, year, cached_months)
                if data and 'error' not in data:
                    best_data = data
                    best_months = cached_months
                    best_count = len(cached_months)
    except Exception:
        pass
    
    return best_data, best_months


def get_company_data(cid, year=None, months=None):
    """获取公司数据：三级缓存查找（内存 → 文件精确 → 文件超集）"""
    co = _companies.get(cid)
    if not co:
        return {'error': f'未找到公司配置: {cid}'}

    cache_key = f'{year}_{months}' if year else 'default'
    dc = co['data_cache']

    with co['lock']:
        # 1. 内存缓存命中
        if dc.get('data') and dc.get('cache_key') == cache_key:
            if time.time() - dc['last_refresh'] > 600 and not dc['loading']:
                dc['loading'] = True
                threading.Thread(target=_bg_refresh, args=(cid, year, months), daemon=True).start()
            _server_status['companies'][cid]['cache_hit'] = True
            return dc['data']

        # 2. 文件精确缓存命中
        cached = load_company_cache(cid, year, months)
        if cached:
            dc['data'] = cached
            dc['cache_key'] = cache_key
            dc['last_refresh'] = time.time()
            _server_status['companies'][cid]['cache_hit'] = True
            return cached

        # 3. 超集缓存命中（核心优化：1-5月缓存 → 子集1月无需重新请求钉钉）
        if year and months:
            superset_data, superset_months = _find_superset_cache(cid, year, months)
            if superset_data and superset_months != months:
                print(f"  [{cid}] 超集缓存命中: {superset_months} → {months}")
                try:
                    _, filter_data_to_months = _import_core()
                    filtered = filter_data_to_months(superset_data, months)
                    if filtered:
                        # 写入精确缓存
                        dc['data'] = filtered
                        dc['cache_key'] = cache_key
                        dc['last_refresh'] = time.time()
                        save_company_cache(cid, filtered, year, months)
                        _server_status['companies'][cid]['cache_hit'] = True
                        return filtered
                except Exception as e:
                    print(f"  [{cid}] 超集过滤失败: {e}")

        # 4. 正在加载中
        if dc['loading']:
            return {'loading': True, 'message': '正在获取钉钉考勤数据，请稍候...'}

        # 5. 无缓存，启动后台加载
        dc['loading'] = True

    threading.Thread(target=_bg_refresh, args=(cid, year, months), daemon=True).start()
    return {'loading': True, 'message': '首次加载钉钉数据，请等待...'}


def _bg_refresh(cid, year=None, months=None):
    co = _companies[cid]
    cache_key = f'{year}_{months}' if year else 'default'
    try:
        load_data, _ = _import_core()
        data = load_data(co['config'], co['token_cache'], year=year, months=months)
        with co['lock']:
            if 'error' not in data:
                co['data_cache']['data'] = data
                co['data_cache']['cache_key'] = cache_key
                co['data_cache']['last_refresh'] = time.time()
                save_company_cache(cid, data, year, months)
                _server_status['companies'][cid]['status'] = 'ready'
                print(f"[{cid}] 数据刷新完成 ({year}, {months})")
            else:
                _server_status['companies'][cid]['status'] = 'error'
                print(f"[{cid}] 加载失败: {data.get('error')}")
            co['data_cache']['loading'] = False
    except Exception as e:
        import traceback
        traceback.print_exc()
        with co['lock']:
            co['data_cache']['loading'] = False
            _server_status['companies'][cid]['status'] = 'error'


def force_company_refresh(cid, year=None, months=None):
    co = _companies.get(cid)
    if not co:
        return {'error': f'未找到公司配置: {cid}'}
    cache_key = f'{year}_{months}' if year else 'default'
    with co['lock']:
        co['data_cache']['loading'] = False
    
    load_data, _ = _import_core()
    data = load_data(co['config'], co['token_cache'], year=year, months=months)
    with co['lock']:
        if 'error' not in data:
            co['data_cache']['data'] = data
            co['data_cache']['cache_key'] = cache_key
            co['data_cache']['last_refresh'] = time.time()
            save_company_cache(cid, data, year, months)
            _server_status['companies'][cid]['status'] = 'ready'
    return data


def preload_widest_cache(cid):
    """启动时预加载最宽月份范围的缓存到内存"""
    co = _companies.get(cid)
    if not co:
        return
    prefix = f'{cid}_'
    best_data = None
    best_count = 0
    
    try:
        for fname in os.listdir(CACHE_DIR):
            if fname.startswith(prefix) and fname.endswith('_cache.json'):
                mid_match = re.search(rf'{cid}_(\d{{4}})_(.+?)_cache\.json', fname)
                if not mid_match:
                    continue
                try:
                    cached_months = [int(m) for m in mid_match.group(2).split('-')]
                except ValueError:
                    continue
                if len(cached_months) > best_count:
                    data = load_company_cache(cid, int(mid_match.group(1)), cached_months)
                    if data and 'error' not in data:
                        best_data = data
                        best_count = len(cached_months)
    except Exception:
        pass
    
    if best_data:
        with co['lock']:
            co['data_cache']['data'] = best_data
            co['data_cache']['cache_key'] = 'default'
            co['data_cache']['last_refresh'] = time.time()
            _server_status['companies'][cid]['cache_hit'] = True
            _server_status['companies'][cid]['status'] = 'ready'
        print(f"  [{cid}] 预加载缓存完成 ({best_count}个月)")
    else:
        # 后台异步加载
        threading.Thread(target=_bg_refresh, args=(cid,), daemon=True).start()


def generate_index_html():
    """生成公司列表首页"""
    parent_card = ''
    sub_cards = ''
    for cid, co in _companies.items():
        cfg = co['config']
        color = cfg.get('theme_color', '#C41E3A')
        card = f'''<a href="/{cid}/" class="company-card" style="--card-color:{color}">
            <div class="company-name">{cfg.get("name", cid)}</div>
            <div class="company-brand" style="color:{color}">{cfg.get("brand", "")}</div>
            <div class="company-path">/{cid}/</div>
        </a>'''
        if cid == 'xiwen':
            parent_card = card
        else:
            sub_cards += card

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>勤奋指数看板 · 选择公司查看数据</title>
<style>
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#0a0a0a;color:#fff;margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;background-image:url('/static/bg.jpg');background-size:cover;background-position:center;background-attachment:fixed}}
body::before{{content:'';position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:0}}
.page{{position:relative;z-index:1;width:100%;max-width:1000px;padding:60px 20px;display:flex;flex-direction:column;align-items:center}}
h1{{font-size:32px;margin-bottom:4px;font-weight:900;letter-spacing:2px}}
.sub{{color:rgba(255,255,255,.5);margin-bottom:40px;font-size:14px}}
.section-label{{font-size:12px;font-weight:700;letter-spacing:3px;color:rgba(255,255,255,.4);text-transform:uppercase;margin-bottom:12px;align-self:flex-start;padding-left:4px}}
.parent-section{{width:100%;margin-bottom:40px}}
.parent-section .company-card{{max-width:100%;padding:32px;font-size:1.1em}}
.sub-section{{width:100%}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px;width:100%}}
.company-card{{background:rgba(30,30,30,.85);backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:24px;text-decoration:none;color:#fff;transition:transform .2s,box-shadow .2s,border-color .2s;border-top:3px solid var(--card-color)}}
.company-card:hover{{transform:translateY(-4px);box-shadow:0 8px 32px color-mix(in srgb,var(--card-color) 40%,transparent);border-color:var(--card-color)}}
.company-name{{font-size:18px;font-weight:700;margin-bottom:4px}}
.company-brand{{font-size:13px;font-weight:600;letter-spacing:1px}}
.company-path{{font-size:12px;color:rgba(255,255,255,.35);margin-top:12px}}
</style></head><body>
<div class="page">
  <h1>勤奋指数看板</h1>
  <div class="sub">选择公司查看数据</div>
  <div class="parent-section">
    <div class="section-label">总公司</div>
    <div class="grid">{parent_card}</div>
  </div>
  <div class="sub-section">
    <div class="section-label">分公司</div>
    <div class="grid">{sub_cards}</div>
  </div>
</div>
</body></html>'''


def generate_company_html(cid):
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
            self._html(generate_index_html())
            return

        # 状态端点（GUI 启动器用）
        if path == '/api/status':
            status = dict(_server_status)
            status['uptime'] = round(time.time() - status['start_time'], 0)
            status['companies'] = {}
            for cid, co in _companies.items():
                status['companies'][cid] = {
                    'name': co['config'].get('name', cid),
                    'url': f'http://localhost:{PORT}/{cid}/',
                    'cached': co['data_cache']['data'] is not None,
                    'loading': co['data_cache']['loading'],
                }
            self._json(status)
            return

        # 静态文件
        if path == '/static/bg.jpg':
            bg_path = os.path.join(_BUNDLE_DIR, '59.jpg')
            if not os.path.exists(bg_path):
                bg_path = os.path.join(BASE_DIR, '59.jpg')
            if os.path.exists(bg_path):
                with open(bg_path, 'rb') as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()
            return

        if len(parts) >= 2 and parts[-1] == 'chart.min.js' and 'static' in parts:
            js_path = os.path.join(_BUNDLE_DIR, 'chart.min.js')
            if not os.path.exists(js_path):
                js_path = os.path.join(BASE_DIR, 'chart.min.js')
            if os.path.exists(js_path):
                with open(js_path, 'rb') as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript')
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()
            return

        cid = parts[0]
        if cid not in _companies:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(f'未找到公司: {cid}'.encode('utf-8'))
            return

        sub = '/'.join(parts[1:]) if len(parts) > 1 else ''

        if sub == '' or sub == 'index.html':
            self._html(generate_company_html(cid))
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
        logo_path = os.path.join(_BUNDLE_DIR, logo_file)
        if not os.path.exists(logo_path):
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
        self.send_header('Cache-Control', 'no-cache')
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

    # 预加载各公司最宽缓存
    print("预加载缓存...")
    for cid in _companies:
        preload_widest_cache(cid)

    print(f"\n访问地址: http://localhost:{PORT}/")
    for cid in _companies:
        print(f"  {_companies[cid]['config']['name']}: http://localhost:{PORT}/{cid}/")
    print("\n服务已启动")

    server = HTTPServer(('0.0.0.0', PORT), Handler)
    _server_status['start_time'] = time.time()
    try:
        webbrowser.open(f'http://localhost:{PORT}')
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.server_close()


if __name__ == '__main__':
    main()
