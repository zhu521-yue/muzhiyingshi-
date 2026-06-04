#!/usr/bin/env python3
"""多公司勤奋指数看板 - 主服务（SQLite 数据库版）"""

import json
import os
import sys
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP 服务器"""
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

# 公司运行时状态
_companies = {}
_server_status = {'start_time': time.time(), 'port': PORT, 'companies': {}}


def load_configs():
    """扫描 config/ 目录加载所有公司配置"""
    for fname in sorted(os.listdir(CONFIG_DIR)):
        if not fname.endswith('.json') or fname == 'example.json':
            continue
        cid = fname[:-5]
        path = os.path.join(CONFIG_DIR, fname)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            _companies[cid] = {'config': config}
            _server_status['companies'][cid] = {
                'name': config.get('name', cid),
                'status': 'loaded',
            }
            print(f"  已加载: {cid} ({config.get('name', '')})")
        except Exception as e:
            print(f"  加载失败 {fname}: {e}")


# ========== 加班规则解析 ==========

def _get_overtime_config(cid):
    """从公司配置中提取加班规则"""
    config = _companies[cid]['config']
    start_h = config.get('overtime_start_hour', 18)
    start_m = config.get('overtime_start_minute', 30)
    cap_h = config.get('overtime_cap_hour', 20)
    cap_m = config.get('overtime_cap_minute', 30)

    default_start = start_h * 60 + start_m
    default_cap = cap_h * 60 + cap_m

    groups = {}
    for group_names, rule in config.get('overtime_groups', {}).items():
        parts = rule.get('start', '18:30').split(':')
        g_start = int(parts[0]) * 60 + int(parts[1])
        parts = rule.get('cap', '20:30').split(':')
        g_cap = int(parts[0]) * 60 + int(parts[1])
        groups[group_names] = {'start': g_start, 'cap': g_cap}

    return {'start': default_start, 'cap': default_cap, 'groups': groups,
            'exempt_users': config.get('overtime_exempt_users', [])}


# ========== 数据查询 ==========

def get_company_data(cid, year=None, months=None):
    """获取公司看板数据（从数据库读取）"""
    if cid not in _companies:
        return {'error': f'未找到公司配置: {cid}'}

    from datetime import datetime as _dt
    import db_manager

    now = _dt.now()
    if not year:
        year = now.year
    if not months:
        months = list(range(1, now.month + 1))

    overtime_config = _get_overtime_config(cid)
    result = db_manager.query_data(cid, year, months, overtime_config)
    return result


def force_company_refresh(cid, year=None, months=None):
    """强制刷新：删除当月 current 数据，重新从钉钉拉取"""
    if cid not in _companies:
        return {'error': f'未找到公司配置: {cid}'}

    from datetime import datetime as _dt
    import db_manager
    import sync_task

    now = _dt.now()
    if not year:
        year = now.year
    if not months:
        months = list(range(1, now.month + 1))

    # 只刷新当月（历史月份不变）
    current_months = [m for m in months if year == now.year and m == now.month]
    if current_months:
        m = current_months[0]
        db_manager.delete_current_month(cid, year, m)
        # 后台重新同步当月
        threading.Thread(
            target=sync_task.sync_full_month,
            args=(cid, year, m),
            daemon=True
        ).start()

    # 返回当前可用数据
    return get_company_data(cid, year, months)


# ========== 页面生成 ==========

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


# ========== HTTP Handler ==========

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
            import sync_task
            status = dict(_server_status)
            status['uptime'] = round(time.time() - status['start_time'], 0)
            status['sync'] = sync_task.get_sync_status()
            status['companies'] = {}
            for cid in _companies:
                status['companies'][cid] = {
                    'name': _companies[cid]['config'].get('name', cid),
                    'url': f'http://localhost:{PORT}/{cid}/',
                }
            self._json(status)
            return

        # 管理端点 - 重建指定公司数据
        if path.startswith('/api/admin/rebuild'):
            params = parse_qs(parsed.query)
            target_cid = params.get('cid', [None])[0]
            if not target_cid or target_cid not in _companies:
                self._json({'error': f'无效的 cid: {target_cid}'})
                return
            import sync_task
            result = sync_task.rebuild_company(target_cid)
            self._json(result)
            return

        # 管理端点 - 同步单个公司今日数据
        if path.startswith('/api/admin/sync_today'):
            params = parse_qs(parsed.query)
            target_cid = params.get('cid', [None])[0]
            if not target_cid or target_cid not in _companies:
                self._json({'error': f'无效的 cid: {target_cid}'})
                return
            import sync_task
            now = time.localtime()
            y, m, d = now.tm_year, now.tm_mon, now.tm_mday
            try:
                success = sync_task.sync_single_day(target_cid, y, m, d)
                self._json({'status': 'ok' if success else 'fail'})
            except Exception as e:
                self._json({'error': str(e)})
            return

        # 静态文件 - 背景图
        if path == '/static/bg.jpg':
            bg_path = None
            for name in ('bg.jpg', 'bg.png', '59.jpg'):
                p = os.path.join(BASE_DIR, name)
                if os.path.exists(p):
                    bg_path = p
                    break
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

        # Chart.js
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

        # 公司路由
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


# ========== 启动 ==========

def main():
    import db_manager
    import sync_task

    print("=" * 50)
    print("  多公司勤奋指数看板服务 (SQLite版)")
    print("=" * 50)
    print(f"端口: {PORT}")

    # 初始化数据库
    db_manager.init_db()

    # 加载公司配置
    print("加载公司配置...")
    load_configs()
    if not _companies:
        print("错误: config/ 目录下没有找到任何公司配置文件")
        return

    # 检查数据库是否为空，为空则全量同步
    sync_task.check_and_initial_sync()

    # 启动定时同步调度
    sync_task.run_scheduler()

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
