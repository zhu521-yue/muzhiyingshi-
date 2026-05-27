#!/usr/bin/env python3
"""核心业务逻辑 - 多公司通用的考勤数据获取与聚合"""

import json
import re
import time
import calendar
import urllib.request
import urllib.error
from datetime import datetime, timedelta


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


def get_token(app_key, app_secret, token_cache):
    cache_key = app_key
    if token_cache.get(cache_key) and time.time() < token_cache.get(cache_key + '_exp', 0):
        return token_cache[cache_key]
    resp = api_post('https://api.dingtalk.com/v1.0/oauth2/accessToken',
                    {'appKey': app_key, 'appSecret': app_secret})
    token_cache[cache_key] = resp['accessToken']
    token_cache[cache_key + '_exp'] = time.time() + resp.get('expireIn', 7200) - 300
    return token_cache[cache_key]


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
                payload = {'userIds': batch, 'checkDateFrom': wf,
                           'checkDateTo': wt, 'cursor': cursor, 'size': 100}
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
                payload = {'workDateFrom': wf, 'workDateTo': wt,
                           'userIdList': batch, 'offset': offset, 'limit': 50}
                try:
                    resp = api_post(
                        f'https://oapi.dingtalk.com/attendance/list?access_token={token}', payload)
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
    if re.search(r'运营|营销|事业部', position or ''):
        return '营销岗'
    if re.search(r'产品', position or ''):
        return '产品岗'
    return '职能岗'


def _get_credentials(config):
    """获取凭证列表：支持单个或多个钉钉应用"""
    if 'app_keys' in config:
        return config['app_keys']
    return [{'app_key': config['app_key'], 'app_secret': config['app_secret']}]


def load_data(config, token_cache, year=None, months=None):
    """从钉钉 API 获取考勤数据并聚合，支持多凭证合并"""
    credentials = _get_credentials(config)
    tokens = []
    for cred in credentials:
        try:
            t = get_token(cred['app_key'], cred['app_secret'], token_cache)
            tokens.append((t, cred))
        except Exception as e:
            return {'error': f'获取token失败({cred["app_key"][:8]}...): {e}'}

    # 全局默认的 dept_root/dept_ids（单凭证模式用）
    default_dept_root = config.get('dept_root', 1)
    default_dept_ids = config.get('dept_ids', [1])

    now = datetime.now()
    if year is None:
        year = now.year
    if months is None:
        months = config.get('months', list(range(1, now.month + 1)))

    # 从所有凭证获取部门和用户（合并去重）
    dept_name_map = {}
    all_users = []
    seen_ids = set()

    for token, cred in tokens:
        dept_root = cred.get('dept_root', default_dept_root)
        dept_ids = cred.get('dept_ids', default_dept_ids)

        root_subs = get_sub_depts(token, dept_root)
        for d in root_subs:
            dept_name_map[d['id']] = d.get('name', '')
            for sd in get_sub_depts(token, d['id']):
                dept_name_map[sd['id']] = sd.get('name', '')

        for did in dept_ids:
            for u in get_users_recursive(token, did):
                if u['userid'] not in seen_ids:
                    seen_ids.add(u['userid'])
                    all_users.append(u)
        for d in root_subs:
            if d['id'] in dept_ids:
                continue
            name = d.get('name', '')
            if '营销' in name or '事业部' in name or '中心' in name:
                for u in get_users_recursive(token, d['id']):
                    if u['userid'] not in seen_ids:
                        seen_ids.add(u['userid'])
                        all_users.append(u)

    # 排除部门
    exclude_depts = set(config.get('exclude_depts', []))
    if exclude_depts:
        def _collect_exclude(did):
            exclude_depts.add(did)
            for tk, _ in tokens:
                for sd in get_sub_depts(tk, did):
                    _collect_exclude(sd['id'])
        for ed in list(exclude_depts):
            _collect_exclude(ed)

    print(f"[{config['name']}] 获取用户列表... ({len(all_users)} 人)")

    all_user_map = {}
    for u in all_users:
        uid = u['userid']
        if uid not in all_user_map:
            u_dept_ids = u.get('department', [])
            if exclude_depts and any(d in exclude_depts for d in u_dept_ids):
                continue
            dept_name = next((dept_name_map[d] for d in u_dept_ids if d in dept_name_map), '')
            all_user_map[uid] = {
                'name': u.get('name', ''),
                'jobnumber': u.get('jobnumber', ''),
                'dept_name': dept_name,
                'position': u.get('position', '') or '',
                'job_type': classify_job(u.get('position', '')),
            }

    print(f"[{config['name']}] 获取考勤记录...")
    all_user_ids = list(all_user_map.keys())
    month_labels = [f'{m}月' for m in months]
    months_range = []
    for m in months:
        last_day = calendar.monthrange(year, m)[1]
        months_range.append((f'{year}-{m:02d}-01 00:00:00', f'{year}-{m:02d}-{last_day} 23:59:59'))

    # 从所有凭证获取考勤记录（合并）
    all_records = []
    for token, cred in tokens:
        for mf, mt in months_range:
            print(f"  查询 {mf[:7]}...")
            all_records.extend(get_attendance(token, all_user_ids, mf, mt))

    # 加班计算参数：起始18:30，上限从配置读取（默认20:30）
    ot_start = 18 * 60 + 30
    ot_cap = config.get('overtime_cap_hour', 20) * 60 + config.get('overtime_cap_minute', 30)

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
            if mins >= ot_start:
                entry['diligence'] += (min(mins, ot_cap) - ot_start) // 30

    return _aggregate(all_user_map, person_data, month_labels, all_records)


def _aggregate(all_user_map, person_data, month_labels, all_records):
    """聚合计算勤奋数据"""
    job_types = ['全部岗位', '职能岗', '营销岗', '产品岗']

    # 月度汇总
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

    # 岗位汇总
    systems = []
    for jt in ['职能岗', '营销岗', '产品岗']:
        uids = [u for u, info in all_user_map.items() if info['job_type'] == jt]
        ns = max(len(uids), 1)
        sd = sum(person_data.get(u, {}).get(ml, {}).get('diligence', 0) for u in uids for ml in month_labels)
        systems.append({'岗位': jt, '总人次': len(uids), '勤奋次数合计': sd,
                        '人均勤奋次数': round(sd/ns, 2)})

    # 交叉分析
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

    # 各岗位详情
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
                                 '累计勤奋次数': cd, '月均勤奋次数': round(cd/max(am, 1), 2)})
        rankings.sort(key=lambda x: -x['累计勤奋次数'])
        for i, r in enumerate(rankings):
            r['排名'] = i + 1
        data[jt] = {'monthly': jt_monthly, 'departments': departments, 'rankings': rankings}

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
