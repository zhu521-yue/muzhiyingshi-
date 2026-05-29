#!/usr/bin/env python3
"""多公司勤奋指数看板 - 主服务（按月缓存版）"""

import json
import os
import re
import sys
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP 服务器，避免单个请求阻塞其他请求"""
    daemon_threads = True

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
    from core import load_single_month, merge_months_and_aggregate
    return load_single_month, merge_months_and_aggregate


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


# ========== 按月缓存管理 ==========

def _month_cache_path(cid, year, month):
    """单月缓存文件路径: cache/{cid}_{year}_{month}_cache.json"""
    return os.path.join(CACHE_DIR, f'{cid}_{year}_{month}_cache.json')


def save_month_cache(cid, year, month, user_map, person_month_data):
    """保存单月个人明细缓存"""
    try:
        path = _month_cache_path(cid, year, month)
        cache_obj = {
            'time': time.time(),
            'year': year,
            'month': month,
            'data': {
                'user_map': user_map,
                'person_data': person_month_data,
            }
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cache_obj, f, ensure_ascii=False)
    except Exception as e:
        print(f"  保存缓存失败 {cid}/{year}/{month}: {e}")


def load_month_cache(cid, year, month):
    """加载单月缓存，返回 (user_map, person_month_data) 或 (None, None)"""
    try:
        path = _month_cache_path(cid, year, month)
        if not os.path.exists(path):
            return None, None
        with open(path, 'r', encoding='utf-8') as f:
            cache_obj = json.load(f)
        data = cache_obj.get('data', {})
        return data.get('user_map'), data.get('person_data')
    except Exception:
        return None, None


def is_month_cache_valid(cid, year, month):
    """判断单月缓存是否有效：历史月份永不过期，当月跨天过期"""
    from datetime import datetime as _dt
    now = _dt.now()
    # 历史月份（不是当前年月）永不过期
    if year < now.year or (year == now.year and month < now.month):
        path = _month_cache_path(cid, year, month)
        return os.path.exists(path)
    # 当月：检查缓存是否是今天生成的
    try:
        path = _month_cache_path(cid, year, month)
        if not os.path.exists(path):
            return False
        with open(path, 'r', encoding='utf-8') as f:
            cache_obj = json.load(f)
        cache_time = cache_obj.get('time', 0)
        cache_date = _dt.fromtimestamp(cache_time).date()
        return cache_date >= now.date()
    except Exception:
        return False


def _try_load_from_old_cache(cid, year, months):
    """兼容：尝试从旧格式缓存文件中提取数据（只读不写）

    只在月份完全匹配时返回数据，超集不返回（因为无法精确过滤）
    """
    # 旧格式: {cid}_{year}_{m1-m2-m3}_cache.json
    try:
        for fname in os.listdir(CACHE_DIR):
            if not fname.startswith(f'{cid}_{year}_') or not fname.endswith('_cache.json'):
                continue
            mid = fname[len(f'{cid}_{year}_'):-len('_cache.json')]
            # 跳过新格式单月文件（纯数字）
            if mid.isdigit():
                continue
            try:
                cached_months = [int(m) for m in mid.split('-')]
            except ValueError:
                continue
            # 完全匹配或超集都可以先返回展示（后台会刷新为精确数据）
            if set(months).issubset(set(cached_months)):
                path = os.path.join(CACHE_DIR, fname)
                with open(path, 'r', encoding='utf-8') as f:
                    cache_obj = json.load(f)
                data = cache_obj.get('data')
                if data and data.get('all_rankings'):
                    # 如果是超集，标记需要后台刷新
                    if set(cached_months) != set(months):
                        data['_needs_refresh'] = True
                    return data
    except Exception:
        pass
    return None


def get_company_data(cid, year=None, months=None):
    """获取公司数据：按月缓存策略

    优先从单月缓存文件合并，历史月份永不过期，当月跨天过期。
    """
    co = _companies.get(cid)
    if not co:
        return {'error': f'未找到公司配置: {cid}'}

    from datetime import datetime as _dt
    now = _dt.now()
    if not year:
        year = now.year
    if not months:
        months = list(range(1, now.month + 1))

    cache_key = f'{year}_{months}'
    dc = co['data_cache']

    # 1. 内存缓存精确命中
    with co['lock']:
        if dc.get('data') and dc.get('cache_key') == cache_key:
            # 检查当月是否过期
            if year == now.year and now.month in months:
                cache_date = _dt.fromtimestamp(dc['last_refresh']).date()
                if cache_date < now.date() and not dc['loading']:
                    dc['loading'] = True
                    threading.Thread(target=_bg_refresh, args=(cid, year, months), daemon=True).start()
            _server_status['companies'][cid]['cache_hit'] = True
            return dc['data']

    # 2. 检查各月单月缓存文件
    cached_months = []
    missing_months = []
    for m in months:
        if is_month_cache_valid(cid, year, m):
            cached_months.append(m)
        else:
            missing_months.append(m)

    # 3. 全部命中：直接合并返回
    if not missing_months:
        result = _merge_cached_months(cid, year, months)
        if result and 'error' not in result:
            with co['lock']:
                dc['data'] = result
                dc['cache_key'] = cache_key
                dc['last_refresh'] = time.time()
            _server_status['companies'][cid]['cache_hit'] = True
            return result

    # 4. 部分命中：先返回已有月份的合并结果，后台补充缺失月份
    if cached_months:
        result = _merge_cached_months(cid, year, cached_months)
        if result and 'error' not in result:
            with co['lock']:
                dc['data'] = result
                dc['cache_key'] = f'{year}_{cached_months}'
                dc['last_refresh'] = time.time()
            _server_status['companies'][cid]['cache_hit'] = True
            # 后台补充缺失月份
            if not dc['loading']:
                with co['lock']:
                    dc['loading'] = True
                threading.Thread(target=_bg_refresh, args=(cid, year, months), daemon=True).start()
            return result

    # 5. 完全没有缓存：尝试旧格式缓存
    old_data = _try_load_from_old_cache(cid, year, months)
    if old_data:
        with co['lock']:
            dc['data'] = old_data
            dc['cache_key'] = cache_key
            dc['last_refresh'] = time.time()
        _server_status['companies'][cid]['cache_hit'] = True
        if not dc['loading']:
            with co['lock']:
                dc['loading'] = True
            threading.Thread(target=_bg_refresh, args=(cid, year, months), daemon=True).start()
        return old_data

    # 6. 正在加载中
    with co['lock']:
        if dc['loading']:
            return {'loading': True, 'message': '正在获取钉钉考勤数据，请稍候...'}
        dc['loading'] = True

    # 7. 启动后台加载
    threading.Thread(target=_bg_refresh, args=(cid, year, months), daemon=True).start()
    return {'loading': True, 'message': '首次加载钉钉数据，请等待...'}


def _merge_cached_months(cid, year, months):
    """从单月缓存文件合并数据并聚合"""
    try:
        _, merge_months_and_aggregate = _import_core()
        monthly_caches = []
        for m in months:
            user_map, person_data = load_month_cache(cid, year, m)
            if user_map is None or person_data is None:
                return None
            ml = f'{m}月'
            monthly_caches.append((ml, user_map, person_data))
        result = merge_months_and_aggregate(monthly_caches)
        result['data_source'] = 'month_cache'
        return result
    except Exception as e:
        print(f"  [{cid}] 合并月缓存失败: {e}")
        return None


def _bg_refresh(cid, year=None, months=None):
    """后台刷新：只请求缺失/过期的月份，其余从缓存读取"""
    co = _companies[cid]
    from datetime import datetime as _dt
    if not year:
        year = _dt.now().year
    if not months:
        months = list(range(1, _dt.now().month + 1))
    cache_key = f'{year}_{months}'

    try:
        load_single_month, merge_months_and_aggregate = _import_core()

        monthly_caches = []
        for m in months:
            # 检查该月缓存是否有效
            if is_month_cache_valid(cid, year, m):
                user_map, person_data = load_month_cache(cid, year, m)
                if user_map and person_data:
                    monthly_caches.append((f'{m}月', user_map, person_data))
                    continue

            # 缓存无效，从钉钉API获取
            print(f"  [{cid}] 请求 {year}-{m:02d} 数据...")
            user_map, person_data = load_single_month(
                co['config'], co['token_cache'], year, m)
            if user_map is None:
                # person_data 是 error dict
                print(f"  [{cid}] {m}月加载失败: {person_data}")
                continue
            # 保存单月缓存
            save_month_cache(cid, year, m, user_map, person_data)
            monthly_caches.append((f'{m}月', user_map, person_data))

        if not monthly_caches:
            with co['lock']:
                co['data_cache']['loading'] = False
                _server_status['companies'][cid]['status'] = 'error'
            return

        # 合并聚合
        data = merge_months_and_aggregate(monthly_caches)
        with co['lock']:
            if 'error' not in data:
                co['data_cache']['data'] = data
                co['data_cache']['cache_key'] = cache_key
                co['data_cache']['last_refresh'] = time.time()
                _server_status['companies'][cid]['status'] = 'ready'
                print(f"[{cid}] 数据刷新完成 ({year}, {months})")
            else:
                _server_status['companies'][cid]['status'] = 'error'
                print(f"[{cid}] 聚合失败: {data.get('error')}")
            co['data_cache']['loading'] = False
    except Exception as e:
        import traceback
        traceback.print_exc()
        with co['lock']:
            co['data_cache']['loading'] = False
            _server_status['companies'][cid]['status'] = 'error'


def force_company_refresh(cid, year=None, months=None):
    """强制刷新：只删除当月缓存，历史月份保留，异步执行"""
    co = _companies.get(cid)
    if not co:
        return {'error': f'未找到公司配置: {cid}'}

    from datetime import datetime as _dt
    now = _dt.now()
    if not year:
        year = now.year
    if not months:
        months = list(range(1, now.month + 1))

    # 只删除当月的缓存文件（历史月份数据是确定的，不需要重新获取）
    for m in months:
        if year == now.year and m == now.month:
            path = _month_cache_path(cid, year, m)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    dc = co['data_cache']
    with co['lock']:
        if dc['loading']:
            # 已经在加载了，返回当前数据或 loading 状态
            if dc.get('data'):
                return dc['data']
            return {'loading': True, 'message': '正在获取数据，请稍候...'}
        dc['loading'] = True

    # 异步刷新
    threading.Thread(target=_bg_refresh, args=(cid, year, months), daemon=True).start()

    # 如果有缓存数据先返回
    if dc.get('data'):
        return dc['data']
    return {'loading': True, 'message': '正在刷新数据，请稍候...'}


def preload_from_cache(cid):
    """启动时从已有的单月缓存文件预加载到内存"""
    co = _companies.get(cid)
    if not co:
        return

    from datetime import datetime as _dt
    now = _dt.now()
    year = now.year
    months = list(range(1, now.month + 1))

    # 检查有哪些月份有缓存
    available = []
    for m in months:
        if os.path.exists(_month_cache_path(cid, year, m)):
            available.append(m)

    if available:
        result = _merge_cached_months(cid, year, available)
        if result and 'error' not in result:
            cache_key = f'{year}_{available}'
            with co['lock']:
                co['data_cache']['data'] = result
                co['data_cache']['cache_key'] = cache_key
                co['data_cache']['last_refresh'] = time.time()
                _server_status['companies'][cid]['cache_hit'] = True
                _server_status['companies'][cid]['status'] = 'ready'
            print(f"  [{cid}] 预加载缓存完成 ({len(available)}个月)")

            # 如果有缺失月份，后台补充
            missing = [m for m in months if m not in available]
            if missing:
                with co['lock']:
                    co['data_cache']['loading'] = True
                threading.Thread(target=_bg_refresh, args=(cid, year, months), daemon=True).start()
            return

    # 尝试旧格式缓存
    old_data = _try_load_from_old_cache(cid, year, months)
    if old_data:
        cache_key = f'{year}_{months}'
        with co['lock']:
            co['data_cache']['data'] = old_data
            co['data_cache']['cache_key'] = cache_key
            co['data_cache']['last_refresh'] = time.time()
            _server_status['companies'][cid]['cache_hit'] = True
            _server_status['companies'][cid]['status'] = 'ready'
        print(f"  [{cid}] 从旧格式缓存预加载完成")
        # 后台转换为新格式
        with co['lock']:
            co['data_cache']['loading'] = True
        threading.Thread(target=_bg_refresh, args=(cid, year, months), daemon=True).start()
        return

    # 无缓存，后台加载
    with co['lock']:
        co['data_cache']['loading'] = True
    threading.Thread(target=_bg_refresh, args=(cid, year, months), daemon=True).start()


def generate_index_html():
    """生成公司列表首页"""
    parent_card = ''
    sub_cards = ''
    for cid, co in _companies.items():
        cfg = co['config']
        color = cfg.get('theme_color', '#C41E3A')
        brand = cfg.get('brand', '')
        card = f'''<a href="/{cid}/" class="company-card" style="--card-color:{color}">
            <div class="company-name">{cfg.get("name", cid)}</div>
            <div class="company-brand" style="color:{color}">{brand}</div>
            <div class="company-path">/{brand.lower()}/</div>
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

        # 状态端点
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

        # 静态文件 - 背景图（优先读取 BASE_DIR/bg.jpg，方便动态切换）
        if path == '/static/bg.jpg':
            bg_path = None
            # 优先从 exe 同目录找 bg.jpg/bg.png（用户可随时替换）
            for name in ('bg.jpg', 'bg.png', '59.jpg'):
                p = os.path.join(BASE_DIR, name)
                if os.path.exists(p):
                    bg_path = p
                    break
            # 再从打包内部找
            if not bg_path:
                for name in ('bg.jpg', 'bg.png', '59.jpg'):
                    p = os.path.join(_BUNDLE_DIR, name)
                    if os.path.exists(p):
                        bg_path = p
                        break
            if bg_path:
                ext = os.path.splitext(bg_path)[1].lower()
                mime = 'image/png' if ext == '.png' else 'image/jpeg'
                with open(bg_path, 'rb') as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Cache-Control', 'no-cache')
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


def _daily_refresh_loop():
    """每天0点自动刷新当月数据"""
    from datetime import datetime, timedelta
    while True:
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        wait_seconds = (tomorrow - now).total_seconds()
        print(f"[定时刷新] 下次刷新时间: {tomorrow.strftime('%Y-%m-%d %H:%M:%S')} (等待 {int(wait_seconds)}秒)")
        time.sleep(wait_seconds)
        print(f"[定时刷新] 开始刷新所有公司当月数据...")
        now = datetime.now()
        current_year = now.year
        current_month = now.month
        # 只刷新当月缓存（历史月份不变）
        for cid in _companies:
            try:
                path = _month_cache_path(cid, current_year, current_month)
                if os.path.exists(path):
                    os.remove(path)
                # 重新获取当月数据
                load_single_month, _ = _import_core()
                co = _companies[cid]
                user_map, person_data = load_single_month(
                    co['config'], co['token_cache'], current_year, current_month)
                if user_map:
                    save_month_cache(cid, current_year, current_month, user_map, person_data)
                    # 重新聚合完整数据
                    all_months = list(range(1, current_month + 1))
                    result = _merge_cached_months(cid, current_year, all_months)
                    if result and 'error' not in result:
                        cache_key = f'{current_year}_{all_months}'
                        with co['lock']:
                            co['data_cache']['data'] = result
                            co['data_cache']['cache_key'] = cache_key
                            co['data_cache']['last_refresh'] = time.time()
                print(f"[定时刷新] {cid} 刷新完成")
            except Exception as e:
                print(f"[定时刷新] {cid} 刷新失败: {e}")


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

    # 预加载各公司缓存
    print("预加载缓存...")
    for cid in _companies:
        preload_from_cache(cid)

    # 启动每日定时刷新线程
    threading.Thread(target=_daily_refresh_loop, daemon=True).start()

    print(f"\n访问地址: http://localhost:{PORT}/")
    for cid in _companies:
        print(f"  {_companies[cid]['config']['name']}: http://localhost:{PORT}/{cid}/")
    print("\n服务已启动")

    server = ThreadedHTTPServer(('0.0.0.0', PORT), Handler)
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
