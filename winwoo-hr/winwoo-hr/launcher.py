#!/usr/bin/env python3
"""勤奋指数看板 - 启动器（GUI弹窗版，无CMD）

用于 exe 打包入口：打开即显示端口状态、页面状态、缓存状态
"""

import json
import os
import re
import sys
import time
import socket
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from urllib import request as urllib_request


# ========== 路径配置 ==========
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    _BUNDLE_DIR = sys._MEIPASS
    sys.path.insert(0, _BUNDLE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    _BUNDLE_DIR = BASE_DIR

CONFIG_DIR = os.path.join(BASE_DIR, 'config')
CACHE_DIR = os.path.join(BASE_DIR, 'cache')
PORT = int(os.environ.get('DASHBOARD_PORT', 8090))

# ========== 颜色主题 ==========
COLORS = {
    'bg': '#0f0f1a',
    'card': '#1a1a2e',
    'accent': '#e94560',
    'accent_dim': '#c0392b',
    'green': '#4ade80',
    'orange': '#ffa500',
    'yellow': '#fbbf24',
    'red': '#ef4444',
    'gray': '#888',
    'text': '#e0e0e0',
    'text_dim': '#666',
    'white': '#fff',
    'border': '#2a2a3e',
    'log_bg': '#0a0a14',
    'log_text': '#0f0',
}

# ========== 日志收集 ==========
class TeeLogger:
    def __init__(self):
        self.logs = []
        self._callback = None

    def set_callback(self, cb):
        self._callback = cb

    def write(self, msg):
        self.logs.append(msg)
        if self._callback:
            try:
                self._callback(msg)
            except Exception:
                pass

    def flush(self):
        pass

    def get_recent(self, n=20):
        return ''.join(self.logs[-n:])

logger = TeeLogger()
_print = print

def _custom_print(*args, **kwargs):
    msg = ' '.join(str(a) for a in args)
    _print(msg, **kwargs)
    logger.write(msg + '\n')

print = _custom_print
sys.stdout = logger


# ========== 工具函数 ==========
def check_port(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False


def check_page(url, timeout=2):
    try:
        req = urllib_request.Request(url, method='GET')
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def load_companies():
    companies = []
    os.makedirs(CACHE_DIR, exist_ok=True)
    if not os.path.isdir(CONFIG_DIR):
        return companies
    for fname in sorted(os.listdir(CONFIG_DIR)):
        if not fname.endswith('.json') or fname == 'example.json':
            continue
        try:
            with open(os.path.join(CONFIG_DIR, fname), 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            cid = fname[:-5]
            companies.append({
                'id': cid,
                'name': cfg.get('name', cid),
                'brand': cfg.get('brand', ''),
                'url': f'http://localhost:{PORT}/{cid}/',
            })
        except Exception:
            pass
    return companies


def count_cache_files():
    """统计缓存文件数量"""
    count = 0
    try:
        if os.path.isdir(CACHE_DIR):
            count = len([f for f in os.listdir(CACHE_DIR) if f.endswith('_cache.json')])
    except Exception:
        pass
    return count


# ========== 内嵌 HTTP 服务 ==========
def start_server():
    """在后台线程中启动完整的 HTTP 服务"""
    from core import load_data as core_load_data, filter_data_to_months

    _companies = {}
    _server_status = {'start_time': time.time(), 'port': PORT}

    def load_configs():
        os.makedirs(CACHE_DIR, exist_ok=True)
        for fname in sorted(os.listdir(CONFIG_DIR)):
            if not fname.endswith('.json') or fname == 'example.json':
                continue
            cid = fname[:-5]
            try:
                with open(os.path.join(CONFIG_DIR, fname), 'r', encoding='utf-8') as f:
                    config = json.load(f)
                _companies[cid] = {
                    'config': config,
                    'token_cache': {},
                    'data_cache': {'data': None, 'loading': False, 'last_refresh': 0, 'cache_key': ''},
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

    def save_cache(cid, data, year=None, months=None):
        try:
            with open(get_cache_file(cid, year, months), 'w', encoding='utf-8') as f:
                json.dump({'time': time.time(), 'data': data}, f, ensure_ascii=False)
        except Exception:
            pass

    def load_cache(cid, year=None, months=None):
        try:
            with open(get_cache_file(cid, year, months), 'r', encoding='utf-8') as f:
                return json.load(f).get('data')
        except Exception:
            return None

    def find_superset_cache(cid, year, target_months):
        if not year or not target_months:
            return None, None
        target_set = set(target_months)
        prefix = f'{cid}_{year}_'
        best_data, best_months, best_count = None, None, 0
        try:
            for fname in os.listdir(CACHE_DIR):
                if not fname.startswith(prefix) or not fname.endswith('_cache.json'):
                    continue
                mid = fname[len(prefix):-len('_cache.json')]
                try:
                    cached_months = [int(m) for m in mid.split('-')]
                except ValueError:
                    continue
                cached_set = set(cached_months)
                if target_set.issubset(cached_set) and len(cached_months) > best_count:
                    data = load_cache(cid, year, cached_months)
                    if data and 'error' not in data:
                        best_data, best_months, best_count = data, cached_months, len(cached_months)
        except Exception:
            pass
        return best_data, best_months

    def get_data(cid, year=None, months=None):
        co = _companies.get(cid)
        if not co:
            return {'error': f'未找到公司配置: {cid}'}
        cache_key = f'{year}_{months}' if year else 'default'
        dc = co['data_cache']
        with co['lock']:
            if dc.get('data') and dc.get('cache_key') == cache_key:
                if time.time() - dc['last_refresh'] > 600 and not dc['loading']:
                    dc['loading'] = True
                    threading.Thread(target=bg_refresh, args=(cid, year, months), daemon=True).start()
                return dc['data']
            cached = load_cache(cid, year, months)
            if cached:
                dc['data'], dc['cache_key'], dc['last_refresh'] = cached, cache_key, time.time()
                return cached
            # 超集缓存查找
            if year and months:
                superset_data, superset_months = find_superset_cache(cid, year, months)
                if superset_data and superset_months != months:
                    print(f"  [{cid}] 超集缓存命中: {superset_months} -> {months}")
                    try:
                        filtered = filter_data_to_months(superset_data, months)
                        if filtered:
                            dc['data'], dc['cache_key'] = filtered, cache_key
                            dc['last_refresh'] = time.time()
                            save_cache(cid, filtered, year, months)
                            return filtered
                    except Exception as e:
                        print(f"  [{cid}] 超集过滤失败: {e}")
            if dc['loading']:
                return {'loading': True, 'message': '正在获取钉钉考勤数据，请稍候...'}
            dc['loading'] = True
        threading.Thread(target=bg_refresh, args=(cid, year, months), daemon=True).start()
        return {'loading': True, 'message': '首次加载钉钉数据，请等待...'}

    def bg_refresh(cid, year=None, months=None):
        co = _companies[cid]
        cache_key = f'{year}_{months}' if year else 'default'
        try:
            data = core_load_data(co['config'], co['token_cache'], year=year, months=months)
            with co['lock']:
                if 'error' not in data:
                    co['data_cache']['data'] = data
                    co['data_cache']['cache_key'] = cache_key
                    co['data_cache']['last_refresh'] = time.time()
                    save_cache(cid, data, year, months)
                    print(f"[{cid}] 数据刷新完成 ({year}, {months})")
                else:
                    print(f"[{cid}] 加载失败: {data.get('error')}")
                co['data_cache']['loading'] = False
        except Exception as e:
            import traceback
            traceback.print_exc()
            with co['lock']:
                co['data_cache']['loading'] = False

    def force_refresh(cid, year=None, months=None):
        co = _companies.get(cid)
        if not co:
            return {'error': f'未找到公司配置: {cid}'}
        cache_key = f'{year}_{months}' if year else 'default'
        with co['lock']:
            co['data_cache']['loading'] = False
        data = core_load_data(co['config'], co['token_cache'], year=year, months=months)
        with co['lock']:
            if 'error' not in data:
                co['data_cache']['data'] = data
                co['data_cache']['cache_key'] = cache_key
                co['data_cache']['last_refresh'] = time.time()
                save_cache(cid, data, year, months)
        return data

    def gen_index():
        parent_card = ''
        sub_cards = ''
        for cid, co in _companies.items():
            cfg = co['config']
            color = cfg.get('theme_color', '#C41E3A')
            card = (
                f'<a href="/{cid}/" class="company-card" style="--card-color:{color}">'
                f'<div class="company-name">{cfg.get("name", cid)}</div>'
                f'<div class="company-brand" style="color:{color}">{cfg.get("brand", "")}</div>'
                f'<div class="company-path">/{cid}/</div></a>'
            )
            if cid == 'xiwen':
                parent_card = card
            else:
                sub_cards += card

        return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>勤奋指数看板</title>
<style>
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#0a0a0a;color:#fff;margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;background-image:url('/static/bg.jpg');background-size:cover;background-position:center;background-attachment:fixed}}
body::before{{content:'';position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:0}}
.page{{position:relative;z-index:1;width:100%;max-width:1000px;padding:60px 20px;display:flex;flex-direction:column;align-items:center}}
h1{{font-size:32px;margin-bottom:4px;font-weight:900;letter-spacing:2px}}
.sub{{color:rgba(255,255,255,.5);margin-bottom:40px;font-size:14px}}
.section-label{{font-size:12px;font-weight:700;letter-spacing:3px;color:rgba(255,255,255,.4);margin-bottom:12px;align-self:flex-start;padding-left:4px}}
.parent-section{{width:100%;margin-bottom:40px}}.parent-section .company-card{{max-width:100%;padding:32px;font-size:1.1em}}
.sub-section{{width:100%}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px;width:100%}}
.company-card{{background:rgba(30,30,30,.85);backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:24px;text-decoration:none;color:#fff;transition:transform .2s,box-shadow .2s;border-top:3px solid var(--card-color)}}
.company-card:hover{{transform:translateY(-4px);box-shadow:0 8px 32px color-mix(in srgb,var(--card-color) 40%,transparent)}}
.company-name{{font-size:18px;font-weight:700;margin-bottom:4px}}
.company-brand{{font-size:13px;font-weight:600;letter-spacing:1px}}
.company-path{{font-size:12px;color:rgba(255,255,255,.35);margin-top:12px}}
</style></head><body><div class="page">
<h1>勤奋指数看板</h1><div class="sub">选择公司查看数据</div>
<div class="parent-section"><div class="section-label">总公司</div><div class="grid">{parent_card}</div></div>
<div class="sub-section"><div class="section-label">分公司</div><div class="grid">{sub_cards}</div></div>
</div></body></html>'''

    def gen_company(cid):
        cfg = _companies[cid]['config']
        from _html_template import get_html_template
        return get_html_template(
            cfg.get('name', cid), cfg.get('brand', ''),
            cfg.get('theme_color', '#C41E3A'),
            f'/{cid}/logo', cid
        )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _parse_params(self, qs):
            params = parse_qs(qs)
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
                self._html_resp(gen_index())
                return

            if path == '/api/status':
                status = {
                    'port': PORT,
                    'uptime': round(time.time() - _server_status['start_time'], 0),
                    'cache_count': count_cache_files(),
                    'companies': {},
                }
                for cid, co in _companies.items():
                    status['companies'][cid] = {
                        'name': co['config'].get('name', cid),
                        'url': f'http://localhost:{PORT}/{cid}/',
                        'cached': co['data_cache']['data'] is not None,
                        'loading': co['data_cache']['loading'],
                    }
                self._json_resp(status)
                return

            if path == '/static/bg.jpg':
                self._serve_file('59.jpg', 'image/jpeg')
                return

            if len(parts) >= 2 and parts[-1] == 'chart.min.js' and 'static' in parts:
                self._serve_file('chart.min.js', 'application/javascript')
                return

            cid = parts[0]
            if cid not in _companies:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(f'未找到公司: {cid}'.encode('utf-8'))
                return

            sub = '/'.join(parts[1:]) if len(parts) > 1 else ''

            if sub == '' or sub == 'index.html':
                self._html_resp(gen_company(cid))
            elif sub == 'api/data':
                year, months = self._parse_params(parsed.query)
                self._json_resp(get_data(cid, year, months))
            elif sub == 'api/refresh':
                year, months = self._parse_params(parsed.query)
                self._json_resp(force_refresh(cid, year, months))
            elif sub == 'logo':
                cfg = _companies[cid]['config']
                logo_file = cfg.get('logo', '')
                if logo_file:
                    self._serve_file(logo_file, 'image/png')
                else:
                    self.send_response(404)
                    self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

        def _serve_file(self, fname, mime):
            fpath = os.path.join(_BUNDLE_DIR, fname)
            if not os.path.exists(fpath):
                fpath = os.path.join(BASE_DIR, fname)
            if os.path.exists(fpath):
                with open(fpath, 'rb') as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()

        def _html_resp(self, content):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))

        def _json_resp(self, data):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    print("=" * 50)
    print("  多公司勤奋指数看板服务")
    print("=" * 50)
    print(f"端口: {PORT}")
    load_configs()
    if not _companies:
        print("错误: config/ 目录下没有找到任何公司配置文件")
        return

    # 预加载缓存
    for cid, co in _companies.items():
        prefix = f'{cid}_'
        best_data, best_count = None, 0
        try:
            for fname in os.listdir(CACHE_DIR):
                if fname.startswith(prefix) and fname.endswith('_cache.json'):
                    m = re.search(rf'{cid}_(\d{{4}})_(.+?)_cache\.json', fname)
                    if m:
                        try:
                            cms = [int(x) for x in m.group(2).split('-')]
                            if len(cms) > best_count:
                                d = load_cache(cid, int(m.group(1)), cms)
                                if d and 'error' not in d:
                                    best_data, best_count = d, len(cms)
                        except ValueError:
                            continue
            if best_data:
                co['data_cache']['data'] = best_data
                co['data_cache']['last_refresh'] = time.time()
                print(f"  [{cid}] 预加载缓存 ({best_count}个月)")
            else:
                threading.Thread(target=bg_refresh, args=(cid,), daemon=True).start()
                print(f"  [{cid}] 后台加载中...")
        except Exception:
            pass

    print(f"\n访问地址: http://localhost:{PORT}/")
    for cid in _companies:
        print(f"  {_companies[cid]['config']['name']}: http://localhost:{PORT}/{cid}/")

    server = HTTPServer(('0.0.0.0', PORT), Handler)
    _server_status['start_time'] = time.time()
    print("\n服务已启动")
    try:
        server.serve_forever()
    except Exception as e:
        print(f"服务异常: {e}")
        try:
            server.server_close()
        except Exception:
            pass


# ========== GUI 启动器 ==========
class LauncherApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("勤奋指数看板 · 服务监控")
        self.root.geometry("580x560+150+100")
        self.root.resizable(True, True)
        self.root.minsize(520, 440)
        self.root.configure(bg=COLORS['bg'])

        self.server_ready = False
        self.running = True
        self.companies = load_companies()
        self._monitor_count = 0

        self._build_ui()
        self._start_server_bg()
        self._monitor_loop()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _build_ui(self):
        # ---- 标题栏 ----
        title_frame = tk.Frame(self.root, bg=COLORS['card'], height=56)
        title_frame.pack(fill='x')
        title_frame.pack_propagate(False)
        tk.Label(title_frame, text="● 勤奋指数看板", font=('Microsoft YaHei', 15, 'bold'),
                 fg=COLORS['accent'], bg=COLORS['card']).pack(side='left', padx=18, pady=12)
        self.uptime_label = tk.Label(title_frame, text="运行中...", font=('Consolas', 10),
                                      fg=COLORS['gray'], bg=COLORS['card'])
        self.uptime_label.pack(side='right', padx=18)

        # ---- 状态卡片区域 ----
        status_section = tk.Frame(self.root, bg=COLORS['bg'])
        status_section.pack(fill='x', padx=14, pady=(10, 4))

        # 端口状态行
        port_frame = tk.Frame(status_section, bg=COLORS['card'], bd=0, highlightthickness=0)
        port_frame.pack(fill='x', pady=3)
        tk.Label(port_frame, text=" 端口状态", font=('Microsoft YaHei', 11, 'bold'),
                 fg=COLORS['gray'], bg=COLORS['card']).pack(side='left', padx=12, pady=8)
        self.port_status = tk.Label(port_frame, text="启动中...", font=('Microsoft YaHei', 11, 'bold'),
                                     fg=COLORS['orange'], bg=COLORS['card'])
        self.port_status.pack(side='right', padx=14, pady=8)

        # 页面状态行
        page_frame = tk.Frame(status_section, bg=COLORS['card'], bd=0, highlightthickness=0)
        page_frame.pack(fill='x', pady=3)
        tk.Label(page_frame, text=" 首页访问", font=('Microsoft YaHei', 11, 'bold'),
                 fg=COLORS['gray'], bg=COLORS['card']).pack(side='left', padx=12, pady=8)
        self.page_status = tk.Label(page_frame, text="检测中...", font=('Microsoft YaHei', 11, 'bold'),
                                     fg=COLORS['orange'], bg=COLORS['card'])
        self.page_status.pack(side='right', padx=14, pady=8)

        # 缓存状态行
        cache_frame = tk.Frame(status_section, bg=COLORS['card'], bd=0, highlightthickness=0)
        cache_frame.pack(fill='x', pady=3)
        tk.Label(cache_frame, text=" 缓存文件", font=('Microsoft YaHei', 11, 'bold'),
                 fg=COLORS['gray'], bg=COLORS['card']).pack(side='left', padx=12, pady=8)
        self.cache_status = tk.Label(cache_frame, text="统计中...", font=('Microsoft YaHei', 11, 'bold'),
                                      fg=COLORS['orange'], bg=COLORS['card'])
        self.cache_status.pack(side='right', padx=14, pady=8)

        # ---- 公司状态列表 ----
        comp_header = tk.Frame(self.root, bg=COLORS['bg'])
        comp_header.pack(fill='x', padx=14, pady=(8, 0))
        tk.Label(comp_header, text="公司看板状态", font=('Microsoft YaHei', 10, 'bold'),
                 fg=COLORS['text_dim'], bg=COLORS['bg']).pack(side='left')

        comp_list_frame = tk.Frame(self.root, bg=COLORS['bg'])
        comp_list_frame.pack(fill='both', expand=True, padx=14, pady=(4, 2))

        canvas = tk.Canvas(comp_list_frame, bg=COLORS['bg'], highlightthickness=0, height=120)
        scrollbar = tk.Scrollbar(comp_list_frame, orient='vertical', command=canvas.yview)
        self.comp_inner = tk.Frame(canvas, bg=COLORS['bg'])
        self.comp_inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=self.comp_inner, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        self.comp_widgets = {}
        for comp in self.companies:
            row = tk.Frame(self.comp_inner, bg=COLORS['card'], bd=0, highlightthickness=0)
            row.pack(fill='x', pady=2, padx=2)

            # 状态圆点
            dot = tk.Canvas(row, width=12, height=12, bg=COLORS['card'], highlightthickness=0)
            dot.pack(side='left', padx=(8, 2), pady=10)
            dot.create_oval(2, 2, 10, 10, fill=COLORS['orange'], outline='', tags='dot')

            # 公司名
            name_text = comp['name']
            if len(name_text) > 18:
                name_text = name_text[:17] + '...'
            name_lbl = tk.Label(row, text=name_text, font=('Microsoft YaHei', 10),
                                fg=COLORS['text'], bg=COLORS['card'], anchor='w', width=22)
            name_lbl.pack(side='left', padx=(4, 8), pady=8)

            # 缓存状态标记
            cache_lbl = tk.Label(row, text="", font=('Microsoft YaHei', 8),
                                 fg=COLORS['gray'], bg=COLORS['card'])
            cache_lbl.pack(side='left', padx=(0, 8))

            # 状态标签
            status_lbl = tk.Label(row, text="等待中", font=('Microsoft YaHei', 9),
                                  fg=COLORS['orange'], bg=COLORS['card'], width=8)
            status_lbl.pack(side='right', padx=(4, 4), pady=8)

            # 打开按钮
            btn = tk.Button(row, text="打开", font=('Microsoft YaHei', 8),
                            fg=COLORS['white'], bg=COLORS['accent'],
                            activebackground=COLORS['accent_dim'],
                            bd=0, padx=10, pady=2, cursor='hand2',
                            command=lambda c=comp: webbrowser.open(c['url']))
            btn.pack(side='right', padx=(4, 8), pady=8)

            self.comp_widgets[comp['id']] = {
                'row': row, 'dot': dot, 'status': status_lbl,
                'cache': cache_lbl, 'btn': btn,
            }

        # ---- 底部按钮 ----
        btn_frame = tk.Frame(self.root, bg=COLORS['bg'])
        btn_frame.pack(fill='x', padx=14, pady=(4, 10))

        self.open_btn = tk.Button(btn_frame, text="打开首页",
                                  font=('Microsoft YaHei', 11, 'bold'),
                                  fg=COLORS['white'], bg=COLORS['accent'],
                                  activebackground=COLORS['accent_dim'],
                                  bd=0, padx=24, pady=6, cursor='hand2',
                                  command=lambda: webbrowser.open(f'http://localhost:{PORT}/'),
                                  state='disabled')
        self.open_btn.pack(side='left')

        tk.Label(btn_frame, text="最小化窗口不会停止服务  |  {company_count} 家公司".format(
            company_count=len(self.companies)),
            font=('Microsoft YaHei', 9), fg=COLORS['text_dim'], bg=COLORS['bg']).pack(side='right', padx=12)

        # ---- 日志区（可折叠） ----
        log_header = tk.Frame(self.root, bg=COLORS['bg'])
        log_header.pack(fill='x', padx=14, pady=(2, 0))
        self.log_toggle = tk.Label(log_header, text="▼ 运行日志", font=('Microsoft YaHei', 9),
                                    fg=COLORS['text_dim'], bg=COLORS['bg'], cursor='hand2')
        self.log_toggle.pack(side='left')
        self.log_visible = True
        self.log_toggle.bind('<Button-1>', self._toggle_log)

        self.log_text = tk.Text(self.root, height=5, font=('Consolas', 9),
                                fg=COLORS['log_text'], bg=COLORS['log_bg'],
                                bd=0, wrap='word', state='disabled',
                                insertbackground=COLORS['log_text'])
        self.log_text.pack(fill='both', expand=False, padx=14, pady=(2, 6))

        # 日志回调
        logger.set_callback(self._append_log)

    def _toggle_log(self, event):
        if self.log_visible:
            self.log_text.pack_forget()
            self.log_toggle.configure(text="▶ 运行日志")
        else:
            self.log_text.pack(fill='both', expand=False, padx=14, pady=(2, 6), after=self.log_toggle.master)
            self.log_toggle.configure(text="▼ 运行日志")
        self.log_visible = not self.log_visible

    def _start_server_bg(self):
        t = threading.Thread(target=self._run_server, daemon=True)
        t.start()

    def _run_server(self):
        try:
            start_server()
        except Exception as e:
            print(f"服务启动失败: {e}")
            import traceback
            traceback.print_exc()

    def _on_close(self):
        self.running = False
        self.root.destroy()

    def _append_log(self, msg):
        try:
            self.log_text.configure(state='normal')
            self.log_text.insert('end', msg)
            self.log_text.see('end')
            lines = int(self.log_text.index('end-1c').split('.')[0])
            if lines > 300:
                self.log_text.delete('1.0', '100.0')
            self.log_text.configure(state='disabled')
        except Exception:
            pass

    def _monitor_loop(self):
        if not self.running:
            return
        try:
            port_ok = check_port(PORT)

            # 端口状态
            if port_ok:
                self.port_status.configure(text=f"端口 {PORT} ● 正常", fg=COLORS['green'])
                self.open_btn.configure(state='normal')
                if not self.server_ready:
                    self.server_ready = True
                    webbrowser.open(f'http://localhost:{PORT}/')
            else:
                elapsed = self._monitor_count * 2
                self.port_status.configure(text=f"端口 {PORT} ● 等待启动 ({elapsed}s)", fg=COLORS['orange'])
                self.open_btn.configure(state='disabled')
                self.server_ready = False

            # 页面状态
            if port_ok:
                page_ok = check_page(f'http://localhost:{PORT}/')
                self.page_status.configure(
                    text="可访问 ●" if page_ok else "响应中...",
                    fg=COLORS['green'] if page_ok else COLORS['orange'])
            else:
                self.page_status.configure(text="等待服务启动", fg=COLORS['orange'])

            # 缓存状态
            cache_count = count_cache_files()
            self.cache_status.configure(
                text=f"{cache_count} 个缓存文件",
                fg=COLORS['green'] if cache_count > 0 else COLORS['orange'])

            # 运行时间
            if port_ok:
                self.uptime_label.configure(
                    text=f"运行中 · {self._monitor_count * 2}s",
                    fg=COLORS['green'])

            # 各公司状态
            for comp in self.companies:
                w = self.comp_widgets.get(comp['id'])
                if not w:
                    continue
                if port_ok:
                    page_ok = check_page(comp['url'], timeout=2)
                    # 检查是否有缓存
                    has_cache = any(
                        f.startswith(f"{comp['id']}_") for f in os.listdir(CACHE_DIR)
                    ) if os.path.isdir(CACHE_DIR) else False

                    if page_ok:
                        w['dot'].itemconfig('dot', fill=COLORS['green'])
                        w['status'].configure(text="可访问", fg=COLORS['green'])
                    else:
                        w['dot'].itemconfig('dot', fill=COLORS['orange'])
                        w['status'].configure(text="加载中", fg=COLORS['orange'])

                    w['cache'].configure(
                        text="● 已缓存" if has_cache else "",
                        fg=COLORS['green'] if has_cache else COLORS['gray'])
                else:
                    w['dot'].itemconfig('dot', fill=COLORS['gray'])
                    w['status'].configure(text="等待服务", fg=COLORS['gray'])
                    w['cache'].configure(text="", fg=COLORS['gray'])

            self._monitor_count += 1
        except Exception:
            pass

        if self.running:
            self.root.after(2000, self._monitor_loop)


if __name__ == '__main__':
    LauncherApp()
