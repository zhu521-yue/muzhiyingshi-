#!/usr/bin/env python3
"""盈世控股 2026年勤奋指数看板 - 独立版本"""

import json
import os
import re
import threading
import webbrowser
import urllib.request
import urllib.error
import time
import calendar
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime, timedelta

PORT = 8089
APP_KEY = 'dingtnfjsjhygyarpqlq'
APP_SECRET = '93vjkfnnggZAoLoiBsflQbl2pEjF6Yid-d0VVRfumXnjYMuaNAXK_J8xluGhoL57'

DEPT_ROOT = 453935060
DEPT_ZHINENG = 500142337
DEPT_WULIU = 981812350

_token_cache = {'token': None, 'expires_at': 0}
_data_cache = {'data': None, 'loading': False, 'last_refresh': 0}
_cache_lock = threading.Lock()
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_cache.json')


def api_post(url, payload, headers=None):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/json')
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:500]
        print(f"HTTP ERROR {e.code} for {url}: {body}")
        raise


def api_get(url):
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:500]
        print(f"HTTP ERROR {e.code} for {url}: {body}")
        raise


def get_token():
    if _token_cache['token'] and time.time() < _token_cache['expires_at']:
        return _token_cache['token']
    resp = api_post('https://api.dingtalk.com/v1.0/oauth2/accessToken',
                    {'appKey': APP_KEY, 'appSecret': APP_SECRET})
    _token_cache['token'] = resp['accessToken']
    _token_cache['expires_at'] = time.time() + resp.get('expireIn', 7200) - 300
    return _token_cache['token']

def get_sub_depts(token, dept_id):
    url = f'https://oapi.dingtalk.com/department/list?access_token={token}&id={dept_id}'
    try:
        return api_get(url).get('department', [])
    except Exception:
        return []


def get_dept_users(token, dept_id):
    users, offset = [], 0
    while True:
        url = (f'https://oapi.dingtalk.com/user/listbypage?access_token={token}'
               f'&department_id={dept_id}&offset={offset}&size=100')
        try:
            resp = api_get(url)
        except Exception:
            break
        ul = resp.get('userlist', [])
        if not ul:
            break
        users.extend(ul)
        if resp.get('hasMore'):
            offset += 100
        else:
            break
    return users


def get_users_recursive(token, dept_id):
    users = get_dept_users(token, dept_id)
    for sub in get_sub_depts(token, dept_id):
        users.extend(get_users_recursive(token, sub['id']))
    return users


def get_attendance(token, user_ids, date_from, date_to):
    """优先用 v1.0 API，失败回退旧版 oapi"""
    try:
        return _get_attendance_v1(token, user_ids, date_from, date_to)
    except Exception as e:
        print(f"  v1.0 API 失败: {e}，回退旧版 oapi")
        return _get_attendance_oapi(token, user_ids, date_from, date_to)


def _get_attendance_v1(token, user_ids, date_from, date_to):
    headers = {'x-acs-dingtalk-access-token': token}
    records = []
    start = datetime.strptime(date_from, '%Y-%m-%d %H:%M:%S')
    end = datetime.strptime(date_to, '%Y-%m-%d %H:%M:%S')
    current = start
    while current < end:
        week_end = min(current + timedelta(days=6), end)
        wf = current.strftime('%Y-%m-%d 00:00:00')
        wt = week_end.strftime('%Y-%m-%d 23:59:59')
        for i in range(0, len(user_ids), 50):
            batch = user_ids[i:i+50]
            cursor = 0
            while True:
                payload = {
                    'userIds': batch, 'checkDateFrom': wf,
                    'checkDateTo': wt, 'cursor': cursor, 'size': 100,
                }
                resp = api_post('https://api.dingtalk.com/v1.0/attendance/records/query',
                                payload, headers=headers)
                for rec in resp.get('result', []):
                    t_str = rec.get('userCheckTime', '')
                    if t_str:
                        try:
                            rec['userCheckTime'] = int(datetime.strptime(
                                t_str, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
                        except Exception:
                            pass
                    records.append(rec)
                if resp.get('hasMore'):
                    cursor = resp.get('nextCursor', 0)
                else:
                    break
        current = week_end + timedelta(seconds=1)
    return records


def _get_attendance_oapi(token, user_ids, date_from, date_to):
    records = []
    start = datetime.strptime(date_from, '%Y-%m-%d %H:%M:%S')
    end = datetime.strptime(date_to, '%Y-%m-%d %H:%M:%S')
    current = start
    while current < end:
        week_end = min(current + timedelta(days=6), end)
        wf = current.strftime('%Y-%m-%d 00:00:00')
        wt = week_end.strftime('%Y-%m-%d 23:59:59')
        for i in range(0, len(user_ids), 50):
            batch = user_ids[i:i+50]
            offset = 0
            while True:
                payload = {
                    'workDateFrom': wf, 'workDateTo': wt,
                    'userIdList': batch, 'offset': offset, 'limit': 50,
                }
                try:
                    resp = api_post(
                        f'https://oapi.dingtalk.com/attendance/list?access_token={token}',
                        payload)
                except Exception:
                    break
                recs = resp.get('recordresult', [])
                records.extend(recs)
                if resp.get('hasMore'):
                    offset += 50
                else:
                    break
        current = week_end + timedelta(seconds=1)
    return records


def classify_job(position):
    """按职位分类岗位：运营|营销|事业部→营销岗，产品→产品岗，其余→职能岗"""
    if re.search(r'运营|营销|事业部', position or ''):
        return '营销岗'
    if re.search(r'产品', position or ''):
        return '产品岗'
    return '职能岗'


def load_data():
    try:
        token = get_token()
    except Exception as e:
        return {'error': f'获取token失败: {e}'}

    dept_name_map = {}
    root_subs = get_sub_depts(token, DEPT_ROOT)
    for d in root_subs:
        dept_name_map[d['id']] = d.get('name', '')
        for sd in get_sub_depts(token, d['id']):
            dept_name_map[sd['id']] = sd.get('name', '')

    print("获取用户列表...")
    zhinen_users = get_users_recursive(token, DEPT_ZHINENG)
    gongying_users = get_users_recursive(token, DEPT_WULIU)
    yingxiao_users = []
    yx_ids = set()
    for d in root_subs:
        if d['id'] == DEPT_ZHINENG:
            continue
        name = d.get('name', '')
        if '营销' in name or '事业部' in name or '中心' in name:
            for u in get_users_recursive(token, d['id']):
                if u['userid'] not in yx_ids:
                    yx_ids.add(u['userid'])
                    yingxiao_users.append(u)

    all_user_map = {}
    seen = set()
    for u in zhinen_users:
        if u['userid'] not in seen:
            seen.add(u['userid'])
    for u in zhinen_users + yingxiao_users + gongying_users:
        uid = u['userid']
        if uid not in all_user_map:
            dept_ids = u.get('department', [])
            dept_name = next((dept_name_map[d] for d in dept_ids if d in dept_name_map), '')
            all_user_map[uid] = {
                'name': u.get('name', ''),
                'jobnumber': u.get('jobnumber', ''),
                'dept_name': dept_name,
                'position': u.get('position', '') or '',
                'job_type': classify_job(u.get('position', '')),
            }

    print("获取考勤记录...")
    all_user_ids = list(all_user_map.keys())
    now = datetime.now()
    year = now.year
    month_labels = [f'{m}月' for m in range(1, 5)]
    months_range = []
    for m in range(1, 5):
        last_day = calendar.monthrange(year, m)[1]
        months_range.append((f'{year}-{m:02d}-01 00:00:00', f'{year}-{m:02d}-{last_day} 23:59:59'))

    all_records = []
    for mf, mt in months_range:
        print(f"  查询 {mf[:7]}...")
        all_records.extend(get_attendance(token, all_user_ids, mf, mt))

    person_data = {}
    for rec in all_records:
        uid = rec.get('userId', '')
        if not uid or uid not in all_user_map:
            continue
        if uid not in person_data:
            person_data[uid] = {ml: {'days': set(), 'diligence': 0} for ml in month_labels}
        uct = rec.get('userCheckTime', 0)
        if not uct:
            continue
        dt = datetime.fromtimestamp(uct / 1000)
        mk = f'{dt.month}月'
        if mk not in person_data[uid]:
            continue
        entry = person_data[uid][mk]
        entry['days'].add(dt.strftime('%Y-%m-%d'))
        if rec.get('checkType') == 'OffDuty':
            mins = dt.hour * 60 + dt.minute
            if mins >= 18 * 60 + 30:
                entry['diligence'] += (min(mins, 20 * 60 + 30) - 18 * 60 - 30) // 30

    job_types = ['全部岗位', '职能岗', '营销岗', '产品岗']

    # 月度汇总（全部人员）
    monthly = []
    for ml in month_labels:
        people, td = set(), 0
        for uid, pd in person_data.items():
            if ml in pd:
                people.add(uid)
                td += pd[ml]['diligence']
        n = max(len(people), 1)
        monthly.append({'月份': ml, '总人数': len(people), '勤奋次数合计': td,
                        '人均勤奋次数': round(td/n, 2)})
    ap = set(person_data.keys())
    ttd = sum(pd[ml]['diligence'] for pd in person_data.values() for ml in month_labels if ml in pd)
    na = max(len(ap), 1)
    monthly.append({'月份': '合计', '总人数': len(ap), '勤奋次数合计': ttd,
                    '人均勤奋次数': round(ttd/na, 2)})

    # 岗位汇总（不含"全部岗位"）
    systems = []
    for jt in ['职能岗', '营销岗', '产品岗']:
        uids = [u for u, info in all_user_map.items() if info['job_type'] == jt]
        ns = max(len(uids), 1)
        sd = sum(person_data.get(u, {}).get(ml, {}).get('diligence', 0) for u in uids for ml in month_labels)
        systems.append({'岗位': jt, '总人次': len(uids), '勤奋次数合计': sd,
                        '人均勤奋次数': round(sd/ns, 2)})

    # 交叉分析：岗位 × 月份
    cross = []
    for jt in ['职能岗', '营销岗', '产品岗']:
        uids = [u for u, info in all_user_map.items() if info['job_type'] == jt]
        row = {'岗位': jt}
        cum_d, cum_n = 0, 0
        for ml in month_labels:
            mp, md = set(), 0
            for u in uids:
                if u in person_data and ml in person_data[u]:
                    mp.add(u)
                    md += person_data[u][ml]['diligence']
            nm = max(len(mp), 1)
            row[ml] = round(md/nm, 2)
            cum_d += md
            cum_n += nm
        row['累计人均'] = round(cum_d / max(cum_n, 1), 2)
        cross.append(row)

    # 各岗位详情（含"全部岗位"）
    data = {}
    for jt in job_types:
        if jt == '全部岗位':
            uids = list(all_user_map.keys())
        else:
            uids = [u for u, info in all_user_map.items() if info['job_type'] == jt]

        jt_monthly = []
        for ml in month_labels:
            mp, md = set(), 0
            for u in uids:
                if u in person_data and ml in person_data[u]:
                    mp.add(u)
                    md += person_data[u][ml]['diligence']
            nm = max(len(mp), 1)
            jt_monthly.append({'月份': ml, '人数': len(mp), '勤奋次数合计': md,
                               '人均勤奋次数': round(md/nm, 2)})

        dept_agg = {}
        for u in uids:
            info = all_user_map[u]
            dn = info['dept_name'] or '未知部门'
            if dn not in dept_agg:
                dept_agg[dn] = {'uids': set(), 'd': 0}
            dept_agg[dn]['uids'].add(u)
            for ml in month_labels:
                if u in person_data and ml in person_data[u]:
                    dept_agg[dn]['d'] += person_data[u][ml]['diligence']
        departments = []
        for dn, dd in sorted(dept_agg.items(), key=lambda x: -x[1]['d']):
            nd = max(len(dd['uids']), 1)
            departments.append({'部门': dn, '人次': len(dd['uids']), '勤奋次数合计': dd['d'],
                                '人均勤奋次数': round(dd['d']/nd, 2)})

        rankings = []
        for u in uids:
            info = all_user_map[u]
            cd, am = 0, 0
            for ml in month_labels:
                if u in person_data and ml in person_data[u]:
                    cd += person_data[u][ml]['diligence']
                    if person_data[u][ml]['days']:
                        am += 1
            if cd > 0:
                rankings.append({'姓名': info['name'], '工号': info['jobnumber'],
                                 '部门': info['dept_name'], '岗位': info['job_type'],
                                 '累计勤奋次数': cd, '月均勤奋次数': round(cd/max(am,1), 2)})
        rankings.sort(key=lambda x: -x['累计勤奋次数'])
        for i, r in enumerate(rankings):
            r['排名'] = i + 1
        data[jt] = {'monthly': jt_monthly, 'departments': departments, 'rankings': rankings}

    # 全公司排名
    all_rankings = data['全部岗位']['rankings'][:]
    all_rankings.sort(key=lambda x: -x['累计勤奋次数'])
    for i, r in enumerate(all_rankings):
        r['排名'] = i + 1

    result = {'monthly': monthly, 'systems': systems, 'cross_analysis': cross,
              'all_rankings': all_rankings, 'data_source': 'dingtalk_api',
              'month_labels': month_labels, 'job_types': job_types}
    for jt in job_types:
        result[jt] = data[jt]
    print(f"数据加载完成: {len(all_user_map)} 人, {len(all_records)} 条记录")
    return result


def save_cache(data):
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump({'time': time.time(), 'data': data}, f, ensure_ascii=False)
    except Exception:
        pass


def load_cache():
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get('data')
    except Exception:
        return None


def get_data():
    with _cache_lock:
        if _data_cache['data']:
            if time.time() - _data_cache['last_refresh'] > 600 and not _data_cache['loading']:
                _data_cache['loading'] = True
                threading.Thread(target=_bg_refresh, daemon=True).start()
            return _data_cache['data']
        if _data_cache['loading']:
            return {'loading': True, 'message': '正在获取钉钉考勤数据，请稍候...'}
        _data_cache['loading'] = True
    threading.Thread(target=_bg_refresh, daemon=True).start()
    return {'loading': True, 'message': '首次加载钉钉数据，请等待...'}


def _bg_refresh():
    try:
        data = load_data()
        with _cache_lock:
            if 'error' not in data:
                _data_cache['data'] = data
                _data_cache['last_refresh'] = time.time()
                save_cache(data)
                print(f"数据刷新完成: {datetime.now().strftime('%H:%M:%S')}")
            else:
                print(f"数据加载失败: {data.get('error')}")
            _data_cache['loading'] = False
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"刷新异常: {e}")
        with _cache_lock:
            _data_cache['loading'] = False


def force_refresh():
    with _cache_lock:
        _data_cache['loading'] = False
    data = load_data()
    with _cache_lock:
        if 'error' not in data:
            _data_cache['data'] = data
            _data_cache['last_refresh'] = time.time()
            save_cache(data)
    return data


def generate_html(month_labels):
    ml_str = '1月 — 4月'
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WINWOO 盈世控股 · 2026年勤奋指数看板</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
:root {
  --red:#C41E3A; --red-dark:#8B0000; --red-light:#E8364F;
  --red-dim:rgba(196,30,58,.12);
  --black:#1A1A1A; --gray-900:#111; --gray-800:#222; --gray-700:#333;
  --gray-500:#666; --gray-300:#AAA; --gray-100:#F4F4F4;
  --white:#FFF; --bg:#F5F5F5; --card:#FFF; --border:#E0E0E0;
  --shadow-sm:0 2px 8px rgba(0,0,0,.06); --shadow:0 4px 16px rgba(0,0,0,.10);
  --shadow-lg:0 8px 32px rgba(0,0,0,.15); --radius:10px;
  --transition:.25s cubic-bezier(.4,0,.2,1);
}
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--black);line-height:1.6;overflow-x:hidden}
.reveal{opacity:0;transform:translateY(28px);transition:opacity .55s ease,transform .55s ease}
.reveal.visible{opacity:1;transform:translateY(0)}
/* === PLACEHOLDER_CSS2 === */
.header{background:var(--black);color:var(--white);padding:0 40px;height:72px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;box-shadow:0 2px 20px rgba(0,0,0,.4)}
.header-left{display:flex;align-items:center;gap:16px}
.header-logo{display:flex;align-items:center;gap:10px}
.header-logo .w-mark{width:36px;height:36px;background:var(--red);clip-path:polygon(20% 0%,50% 60%,80% 0%,100% 0%,70% 100%,50% 50%,30% 100%,0% 0%)}
.header-logo .brand{font-size:20px;font-weight:900;letter-spacing:2px;color:var(--white)}
.header-logo .brand span{color:var(--red)}
.header-divider{width:1px;height:28px;background:rgba(255,255,255,.2)}
.header-title{font-size:15px;font-weight:500;opacity:.85}
.header-right{display:flex;align-items:center;gap:20px}
.header-stat{text-align:center}
.header-stat .s-val{font-size:18px;font-weight:800;color:var(--red-light);line-height:1}
.header-stat .s-lbl{font-size:11px;opacity:.6;margin-top:2px}
.live-dot{display:flex;align-items:center;gap:6px;font-size:12px;opacity:.7}
.live-dot::before{content:'';width:7px;height:7px;border-radius:50%;background:#4ade80;animation:blink 2s infinite;flex-shrink:0}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
#updateTime{font-size:12px;opacity:.6}
.refresh-btn{background:var(--red);border:none;color:var(--white);padding:7px 18px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600;transition:background var(--transition),transform var(--transition);box-shadow:0 2px 8px rgba(196,30,58,.4)}
.refresh-btn:hover{background:var(--red-light);transform:translateY(-1px)}
.hero{background:linear-gradient(135deg,var(--gray-900) 0%,var(--gray-800) 50%,#2a0a10 100%);padding:36px 40px;position:relative;overflow:hidden}
.hero::before{content:'';position:absolute;top:-60px;right:-60px;width:240px;height:240px;border-radius:50%;background:radial-gradient(circle,rgba(196,30,58,.25),transparent 70%);pointer-events:none}
.hero-inner{max-width:1400px;margin:0 auto;position:relative}
.hero-label{font-size:12px;font-weight:700;letter-spacing:3px;color:var(--red);text-transform:uppercase;margin-bottom:8px}
.hero-title{font-size:32px;font-weight:900;color:var(--white);margin-bottom:4px}
.hero-sub{font-size:14px;color:rgba(255,255,255,.5)}
.container{max-width:1400px;margin:0 auto;padding:28px 40px}
.section-title{font-size:17px;font-weight:800;margin:36px 0 16px;display:flex;align-items:center;gap:10px;color:var(--gray-900)}
.section-title::before{content:'';display:block;width:4px;height:20px;background:var(--red);border-radius:2px;flex-shrink:0}
.section-title .s-tag{font-size:11px;font-weight:700;background:var(--red-dim);color:var(--red);padding:2px 8px;border-radius:4px}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:28px}
.kpi-card{background:var(--card);border-radius:var(--radius);padding:22px 24px;box-shadow:var(--shadow-sm);border:1px solid var(--border);position:relative;overflow:hidden;transition:transform var(--transition),box-shadow var(--transition)}
.kpi-card::after{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--red);transform:scaleX(0);transform-origin:left;transition:transform var(--transition)}
.kpi-card:hover{transform:translateY(-3px);box-shadow:var(--shadow)}
.kpi-card:hover::after{transform:scaleX(1)}
.kpi-card .icon{width:40px;height:40px;border-radius:8px;background:var(--red-dim);display:flex;align-items:center;justify-content:center;font-size:18px;margin-bottom:14px}
.kpi-card .label{font-size:12px;font-weight:600;color:var(--gray-500);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px}
.kpi-card .value{font-size:30px;font-weight:900;color:var(--black);line-height:1}
.kpi-card .value.red{color:var(--red)}
.kpi-card .sub{font-size:12px;color:var(--gray-500);margin-top:6px}
.chart-row{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:24px}
.chart-box{background:var(--card);border-radius:var(--radius);padding:22px 24px;box-shadow:var(--shadow-sm);border:1px solid var(--border)}
.chart-box h3{font-size:14px;font-weight:700;margin-bottom:16px;color:var(--gray-700);display:flex;align-items:center;gap:8px}
.chart-box h3::before{content:'';display:block;width:3px;height:14px;background:var(--red);border-radius:2px}
.chart-box canvas{max-height:300px}
.tabs-wrapper{background:var(--card);border-radius:var(--radius);border:1px solid var(--border);overflow:hidden;margin-bottom:24px;box-shadow:var(--shadow-sm)}
.tabs{display:flex;background:var(--gray-100);border-bottom:2px solid var(--border);padding:0 4px}
.tab{padding:12px 28px;cursor:pointer;font-size:14px;font-weight:600;color:var(--gray-500);border:none;background:none;position:relative;transition:color var(--transition)}
.tab::after{content:'';position:absolute;bottom:-2px;left:0;right:0;height:2px;background:var(--red);transform:scaleX(0);transition:transform var(--transition)}
.tab:hover{color:var(--red)}
.tab.active{color:var(--red)}
.tab.active::after{transform:scaleX(1)}
.tab-content{display:none;padding:24px}
.tab-content.active{display:block;animation:fadeIn .3s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.table-wrap{background:var(--card);border-radius:var(--radius);box-shadow:var(--shadow-sm);border:1px solid var(--border);overflow:hidden;margin-bottom:24px}
.table-header{padding:16px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border);background:var(--gray-100)}
.table-header h3{font-size:14px;font-weight:700;color:var(--gray-700)}
.table-scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
thead tr{background:#fafafa}
th{padding:10px 14px;text-align:left;font-weight:700;font-size:12px;color:var(--gray-500);text-transform:uppercase;letter-spacing:.8px;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:11px 14px;border-bottom:1px solid #f0f0f0;white-space:nowrap}
tbody tr:hover{background:rgba(196,30,58,.04)}
.rank{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;font-size:12px;font-weight:800;background:var(--gray-100);color:var(--gray-500)}
.rank-1{background:linear-gradient(135deg,#E8B84B,#C9920A);color:#fff;box-shadow:0 2px 8px rgba(200,145,10,.4)}
.rank-2{background:linear-gradient(135deg,#9CA3AF,#6B7280);color:#fff}
.rank-3{background:linear-gradient(135deg,#C4813A,#96510F);color:#fff}
.progress-bar{height:4px;background:var(--gray-100);border-radius:2px;margin-top:4px;overflow:hidden}
.progress-bar .fill{height:100%;background:linear-gradient(90deg,var(--red-dark),var(--red));border-radius:2px;transition:width 1s ease}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.tag-red{background:rgba(196,30,58,.1);color:var(--red)}
.tag-gray{background:var(--gray-100);color:var(--gray-700)}
.tag-dark{background:var(--gray-800);color:var(--white)}
.system-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px}
.system-card{background:var(--card);border-radius:var(--radius);border:1px solid var(--border);overflow:hidden;box-shadow:var(--shadow-sm);transition:transform var(--transition),box-shadow var(--transition)}
.system-card:hover{transform:translateY(-4px);box-shadow:var(--shadow-lg)}
.system-card-header{background:var(--black);padding:14px 20px;display:flex;align-items:center;justify-content:space-between}
.system-card-header .name{font-size:15px;font-weight:800;color:var(--white)}
.system-card-header .badge{background:var(--red);color:var(--white);font-size:12px;font-weight:700;padding:2px 10px;border-radius:20px}
.system-card-body{padding:16px 20px}
.system-stat-row{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #f4f4f4;font-size:13px}
.system-stat-row:last-child{border-bottom:none}
.system-stat-row .s-key{color:var(--gray-500)}
.system-stat-row .s-val{font-weight:700;color:var(--black)}
.heatmap-wrap{background:var(--card);border-radius:var(--radius);border:1px solid var(--border);overflow:hidden;margin-bottom:24px;box-shadow:var(--shadow-sm)}
.heatmap{display:grid;gap:0}
.heatmap-cell{padding:14px 10px;text-align:center;font-size:13px;font-weight:600;border:1px solid rgba(0,0,0,.05);transition:transform var(--transition)}
.heatmap-cell:hover{transform:scale(1.05);box-shadow:var(--shadow);z-index:1;position:relative}
.heatmap-header{background:var(--black);color:var(--white);font-size:12px;letter-spacing:1px}
.heatmap-row-label{background:var(--gray-100);color:var(--gray-700);font-weight:700}
.heatmap-total{background:rgba(196,30,58,.1);color:var(--red);font-weight:800}
.footer{background:var(--black);color:rgba(255,255,255,.4);text-align:center;padding:20px;font-size:12px;letter-spacing:1px;margin-top:40px}
.footer span{color:var(--red)}
.loading-screen{min-height:300px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;color:var(--gray-500)}
.spinner{width:36px;height:36px;border:3px solid rgba(196,30,58,.2);border-top-color:var(--red);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:1024px){.chart-row{grid-template-columns:1fr}}
@media(max-width:768px){.header{padding:12px 16px;height:auto;flex-wrap:wrap;gap:8px}.container{padding:16px}.hero{padding:24px 16px}.hero-title{font-size:22px}.kpi-grid{grid-template-columns:1fr 1fr}.system-cards{grid-template-columns:1fr}}
</style>
</head>
<body>
<header class="header">
  <div class="header-left">
    <div class="header-logo">
      <div class="w-mark"></div>
      <div class="brand">WIN<span>WOO</span></div>
    </div>
    <div class="header-divider"></div>
    <div class="header-title">盈世控股 · 勤奋指数看板</div>
  </div>
  <div class="header-right">
    <div class="header-stat"><div class="s-val" id="hdTotal">—</div><div class="s-lbl">总勤奋次数</div></div>
    <div class="header-stat"><div class="s-val" id="hdAvg">—</div><div class="s-lbl">人均次数</div></div>
    <div class="live-dot">实时数据</div>
    <div id="updateTime"></div>
    <button class="refresh-btn" onclick="forceRefresh()">↻ 刷新数据</button>
  </div>
</header>
<div class="hero">
  <div class="hero-inner">
    <div class="hero-label">2026 ANNUAL DILIGENCE INDEX</div>
    <div class="hero-title">浙江盈世控股有限公司</div>
    <div class="hero-sub">2026年勤奋指数看板 · 数据区间：1月 — 4月 · 职能岗 / 营销岗 / 产品岗</div>
  </div>
</div>
<div class="container" id="app">
  <div class="loading-screen"><div class="spinner"></div><div>数据加载中...</div></div>
</div>
<footer class="footer">
  <span>WINWOO</span> 盈世控股 · 勤奋指数看板 &copy; 2026 | 数据来源：钉钉考勤API
</footer>
<!-- === PLACEHOLDER_SCRIPT === -->
<script>
const DATA_URL='/api/data';
let DATA=null,charts={};
const RED='#C41E3A',RED2='#E8364F',BLACK='#1A1A1A',GRAY='#888';

function animateNumber(el,target,dur=900,dec=0){
  const start=performance.now();
  (function step(ts){
    const t=Math.min((ts-start)/dur,1),ease=1-Math.pow(1-t,3);
    const val=target*ease;
    el.textContent=dec>0?val.toFixed(dec):Math.round(val).toLocaleString();
    if(t<1)requestAnimationFrame(step);
    else el.textContent=dec>0?target.toFixed(dec):target.toLocaleString();
  })(start);
}

function initReveal(){
  const io=new IntersectionObserver(es=>{es.forEach(e=>{if(e.isIntersecting)e.target.classList.add('visible')})},{threshold:0.1});
  document.querySelectorAll('.reveal').forEach(el=>io.observe(el));
}

function getHeatColor(v,max){const r=v/max;if(r>.75)return RED;if(r>.5)return'#D9536A';if(r>.25)return'#EBABB5';return'#F9E3E6'}
function getHeatText(v,max){return v/max>.45?'#fff':BLACK}

Chart.defaults.font.family="'-apple-system','PingFang SC','Microsoft YaHei',sans-serif";
Chart.defaults.color=GRAY;

function renderDashboard(d){
  const app=document.getElementById('app');
  const m=d.monthly;
  const total=m.find(x=>x.月份==='合计')||m[m.length-1];
  animateNumber(document.getElementById('hdTotal'),total.勤奋次数合计,1000);
  animateNumber(document.getElementById('hdAvg'),total.人均勤奋次数,800,2);

  app.innerHTML=`
    <div class="kpi-grid">
      <div class="kpi-card reveal"><div class="icon">👥</div><div class="label">累计总人次</div><div class="value red">${total.总人数}</div><div class="sub">${d.month_labels[0]}–${d.month_labels[d.month_labels.length-1]}累计</div></div>
      <div class="kpi-card reveal"><div class="icon">💪</div><div class="label">勤奋次数合计</div><div class="value">${total.勤奋次数合计.toLocaleString()}</div><div class="sub">人均 <strong style="color:var(--red)">${total.人均勤奋次数}</strong> 次</div></div>
    </div>
    <div class="section-title reveal">三大岗位总览 <span class="s-tag">OVERVIEW</span></div>
    <div class="system-cards reveal" id="sysCards"></div>
    <div class="section-title reveal">月度趋势 <span class="s-tag">TREND</span></div>
    <div class="chart-row reveal">
      <div class="chart-box"><h3>人均勤奋次数 · 月度变化</h3><canvas id="cMonthly"></canvas></div>
      <div class="chart-box"><h3>勤奋次数合计 · 月度变化</h3><canvas id="cTotal"></canvas></div>
    </div>
    <div class="section-title reveal">岗位对比 <span class="s-tag">COMPARE</span></div>
    <div class="chart-row reveal">
      <div class="chart-box"><h3>岗位人均勤奋次数</h3><canvas id="cSys"></canvas></div>
      <div class="chart-box"><h3>岗位 × 月份趋势</h3><canvas id="cCross"></canvas></div>
    </div>
    <div class="section-title reveal">月度热力图 <span class="s-tag">HEATMAP</span></div>
    <div class="heatmap-wrap reveal"><div class="heatmap" id="heatmap"></div></div>
    <div class="section-title reveal">各岗位详情 <span class="s-tag">DETAIL</span></div>
    <div class="tabs-wrapper reveal">
      <div class="tabs" id="sysTabs"></div>
      <div id="sysContent"></div>
    </div>
    <div class="section-title reveal">全公司勤奋排名 TOP20 <span class="s-tag">RANKING</span></div>
    <div class="table-wrap reveal">
      <div class="table-header"><h3>全公司 · 勤奋次数 TOP 20</h3></div>
      <div class="table-scroll"><table><thead><tr><th>排名</th><th>姓名</th><th>工号</th><th>部门</th><th>岗位</th><th>累计勤奋次数</th><th>月均</th></tr></thead><tbody id="rankBody"></tbody></table></div>
    </div>`;
  renderSysCards(d);renderCharts(d);renderHeatmap(d);renderSysTabs(d);renderRanking(d);initReveal();
}

function renderSysCards(d){
  const el=document.getElementById('sysCards');
  const icons={'职能岗':'🏢','营销岗':'📣','产品岗':'📦'};
  el.innerHTML=d.systems.map(s=>`
    <div class="system-card">
      <div class="system-card-header"><div class="name">${icons[s.岗位]||''} ${s.岗位}</div><div class="badge">人均 ${s.人均勤奋次数}</div></div>
      <div class="system-card-body">
        <div class="system-stat-row"><span class="s-key">总人次</span><span class="s-val">${s.总人次}</span></div>
        <div class="system-stat-row"><span class="s-key">勤奋次数合计</span><span class="s-val">${(s.勤奋次数合计||0).toLocaleString()}</span></div>
        <div class="system-stat-row"><span class="s-key">人均勤奋次数</span><span class="s-val">${s.人均勤奋次数}</span></div>
      </div>
    </div>`).join('');
}

function renderCharts(d){
  const m=d.monthly.filter(x=>x.月份!=='合计');
  const labels=m.map(x=>x.月份);
  const gc='rgba(0,0,0,.05)';
  if(charts.m)charts.m.destroy();
  charts.m=new Chart(document.getElementById('cMonthly'),{type:'line',data:{labels,datasets:[
    {label:'人均勤奋次数',data:m.map(x=>x.人均勤奋次数),borderColor:RED,backgroundColor:'rgba(196,30,58,.08)',fill:true,tension:.4,pointRadius:6,pointBackgroundColor:RED,borderWidth:2.5}
  ]},options:{responsive:true,plugins:{legend:{position:'top',labels:{usePointStyle:true,boxWidth:8}}},scales:{y:{beginAtZero:true,grid:{color:gc},title:{display:true,text:'人均勤奋次数'}}}}});

  if(charts.h)charts.h.destroy();
  charts.h=new Chart(document.getElementById('cTotal'),{type:'bar',data:{labels,datasets:[{label:'勤奋次数合计',data:m.map(x=>x.勤奋次数合计),backgroundColor:RED+'CC',borderRadius:6,borderSkipped:false}]},options:{responsive:true,plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,grid:{color:gc},title:{display:true,text:'勤奋次数'}}}}});

  const sys=d.systems;const sc=[RED,BLACK,'#888'];
  if(charts.s)charts.s.destroy();
  charts.s=new Chart(document.getElementById('cSys'),{type:'bar',data:{labels:sys.map(x=>x.岗位),datasets:[{label:'人均勤奋次数',data:sys.map(x=>x.人均勤奋次数),backgroundColor:sc,borderRadius:8,borderSkipped:false}]},options:{responsive:true,plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,grid:{color:gc}}}}});

  const cross=d.cross_analysis;const months=d.month_labels;
  if(charts.c)charts.c.destroy();
  charts.c=new Chart(document.getElementById('cCross'),{type:'line',data:{labels:months,datasets:cross.map((c,i)=>({label:c.岗位,data:months.map(mm=>c[mm]),borderColor:sc[i],backgroundColor:sc[i]+'20',fill:i===0,tension:.4,pointRadius:6,pointBackgroundColor:sc[i],borderWidth:i===0?3:2}))},options:{responsive:true,plugins:{legend:{position:'top',labels:{usePointStyle:true,boxWidth:8}}},scales:{y:{beginAtZero:true,grid:{color:gc}}}}});
}

function renderHeatmap(d){
  const el=document.getElementById('heatmap');
  const cross=d.cross_analysis,months=d.month_labels;
  const cols=months.length+2;
  el.style.gridTemplateColumns=`120px repeat(${months.length},1fr) 120px`;
  const allV=cross.flatMap(c=>months.map(mm=>c[mm]));
  const mx=Math.max(...allV);
  let h='<div class="heatmap-cell heatmap-header">岗位</div>';
  months.forEach(mm=>h+=`<div class="heatmap-cell heatmap-header">${mm}</div>`);
  h+='<div class="heatmap-cell heatmap-header">累计人均</div>';
  cross.forEach(c=>{
    h+=`<div class="heatmap-cell heatmap-row-label">${c.岗位}</div>`;
    months.forEach(mm=>{const v=c[mm];h+=`<div class="heatmap-cell" style="background:${getHeatColor(v,mx)};color:${getHeatText(v,mx)}">${v}</div>`});
    h+=`<div class="heatmap-cell heatmap-total">${c.累计人均}</div>`;
  });
  el.innerHTML=h;
}

function renderSysTabs(d){
  const jobs=d.job_types||['全部岗位','职能岗','营销岗','产品岗'];
  const tabsEl=document.getElementById('sysTabs');
  const contentEl=document.getElementById('sysContent');
  tabsEl.innerHTML=jobs.map((s,i)=>`<button class="tab ${i===0?'active':''}" onclick="switchTab('${s}',this)">${s}</button>`).join('');
  let html='';
  jobs.forEach((s,i)=>{
    const sys=d[s];if(!sys)return;
    const maxD=Math.max(...sys.departments.map(r=>r.人均勤奋次数),1);
    const maxR=Math.max(...sys.rankings.map(r=>r.累计勤奋次数),1);
    let deptRows=sys.departments.map((r,idx)=>`<tr><td><span class="rank ${idx<3?'rank-'+(idx+1):''}">${idx+1}</span></td><td><strong>${r.部门}</strong></td><td>${r.人次}</td><td><strong style="color:var(--red)">${r.人均勤奋次数}</strong><div class="progress-bar"><div class="fill" style="width:${(r.人均勤奋次数/maxD*100).toFixed(1)}%"></div></div></td><td>${r.勤奋次数合计}</td></tr>`).join('');
    let rankRows=sys.rankings.slice(0,20).map(r=>`<tr><td><span class="rank ${r.排名<=3?'rank-'+r.排名:''}">${r.排名}</span></td><td><strong>${r.姓名}</strong></td><td>${r.工号}</td><td>${r.部门}</td><td><strong style="color:var(--red)">${r.累计勤奋次数}</strong><div class="progress-bar"><div class="fill" style="width:${(r.累计勤奋次数/maxR*100).toFixed(1)}%"></div></div></td><td>${r.月均勤奋次数}</td></tr>`).join('');
    html+=`<div class="tab-content ${i===0?'active':''}" id="tab-${s}">
      <div class="table-wrap"><div class="table-header"><h3>${s} · 部门排名</h3></div><div class="table-scroll"><table><thead><tr><th>#</th><th>部门</th><th>人次</th><th>人均勤奋</th><th>合计</th></tr></thead><tbody>${deptRows}</tbody></table></div></div>
      <div class="table-wrap"><div class="table-header"><h3>${s} · 个人排名</h3></div><div class="table-scroll"><table><thead><tr><th>排名</th><th>姓名</th><th>工号</th><th>部门</th><th>累计勤奋</th><th>月均</th></tr></thead><tbody>${rankRows}</tbody></table></div></div>
    </div>`;
  });
  contentEl.innerHTML=html;
}

function switchTab(name,btn){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
  btn.classList.add('active');
  const tc=document.getElementById('tab-'+name);if(tc)tc.classList.add('active');
}

function renderRanking(d){
  const body=document.getElementById('rankBody');
  const top20=d.all_rankings.slice(0,20);
  const mx=Math.max(...top20.map(r=>r.累计勤奋次数),1);
  const tagMap={'职能岗':'tag-dark','营销岗':'tag-red','产品岗':'tag-gray'};
  body.innerHTML=top20.map(r=>`<tr><td><span class="rank ${r.排名<=3?'rank-'+r.排名:''}">${r.排名}</span></td><td><strong>${r.姓名}</strong></td><td style="color:var(--gray-500)">${r.工号}</td><td>${r.部门}</td><td><span class="tag ${tagMap[r.岗位]||'tag-gray'}">${r.岗位}</span></td><td><strong style="color:var(--red)">${r.累计勤奋次数}</strong><div class="progress-bar"><div class="fill" style="width:${(r.累计勤奋次数/mx*100).toFixed(1)}%"></div></div></td><td>${r.月均勤奋次数}</td></tr>`).join('');
}

async function refreshData(){
  const app=document.getElementById('app');
  app.innerHTML='<div class="loading-screen"><div class="spinner"></div><div>数据加载中...</div></div>';
  try{
    let res=await fetch(DATA_URL);let data=await res.json();
    let retries=0;
    while(data.loading&&retries<120){
      await new Promise(r=>setTimeout(r,3000));
      res=await fetch(DATA_URL);data=await res.json();retries++;
      if(data.loading){const el=app.querySelector('.loading-screen div:last-child');if(el)el.textContent=data.message||'加载中...('+retries*3+'秒)';}
    }
    if(data.error){app.innerHTML=`<div class="loading-screen"><div style="color:var(--red)">⚠ ${data.error}</div></div>`;return;}
    DATA=data;renderDashboard(DATA);
    document.getElementById('updateTime').textContent='更新: '+new Date().toLocaleTimeString();
  }catch(e){app.innerHTML=`<div class="loading-screen"><div style="color:var(--red)">⚠ 加载失败: ${e.message}</div></div>`;}
}

async function forceRefresh(){
  const app=document.getElementById('app');
  app.innerHTML='<div class="loading-screen"><div class="spinner"></div><div>正在刷新钉钉数据...</div></div>';
  try{
    let res=await fetch('/api/refresh');let data=await res.json();
    if(data.error){app.innerHTML=`<div class="loading-screen"><div style="color:var(--red)">⚠ ${data.error}</div></div>`;return;}
    DATA=data;renderDashboard(DATA);
    document.getElementById('updateTime').textContent='更新: '+new Date().toLocaleTimeString();
  }catch(e){app.innerHTML=`<div class="loading-screen"><div style="color:var(--red)">⚠ 刷新失败: ${e.message}</div></div>`;}
}

(async()=>{await refreshData()})();
</script>
</body>
</html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ('/', '/index.html'):
            data = get_data()
            ml = data.get('month_labels', []) if isinstance(data, dict) else []
            html = generate_html(ml if ml else ['1月', '2月', '3月', '4月'])
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        elif path == '/api/data':
            data = get_data()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        elif path == '/api/refresh':
            data = force_refresh()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()


def main():
    print(f"盈世控股 勤奋指数看板 (test) - 数据区间: 1月-4月")
    print(f"访问地址: http://localhost:{PORT}")
    print("按 Ctrl+C 停止")

    # 删除旧缓存，确保重新拉取1-4月数据
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                old = json.load(f)
            old_labels = old.get('data', {}).get('month_labels', [])
            if old_labels != ['1月', '2月', '3月', '4月']:
                os.remove(CACHE_FILE)
                print("缓存数据范围不匹配，已清除旧缓存")
            else:
                _data_cache['data'] = old['data']
                _data_cache['last_refresh'] = time.time()
                print("已加载缓存数据")
        except Exception:
            pass

    server = HTTPServer(('0.0.0.0', PORT), Handler)
    threading.Timer(1.0, lambda: webbrowser.open(f'http://localhost:{PORT}')).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.server_close()


if __name__ == '__main__':
    main()

