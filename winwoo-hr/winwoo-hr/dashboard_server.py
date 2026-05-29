#!/usr/bin/env python3
"""盈世控股 2026年勤奋指数看板 - 数据服务"""

import json
import os
import sys
import threading
import webbrowser
import urllib.request
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta, date
import calendar

PORT = int(os.environ.get('DASHBOARD_PORT', 8088))

# DingTalk API Credentials
APP_KEY = 'dingtnfjsjhygyarpqlq'
APP_SECRET = '93vjkfnnggZAoLoiBsflQbl2pEjF6Yid-d0VVRfumXnjYMuaNAXK_J8xluGhoL57'

# Data cache
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard_data_cache.json')
_data_cache = {'data': None, 'loading': False, 'last_refresh': 0, 'last_error': None, 'error_time': 0}
_cache_lock = threading.Lock()


def load_cache():
    """从本地文件加载缓存数据"""
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        return cache.get('data')
    except Exception:
        return None


def save_cache(data):
    """保存数据到本地缓存"""
    try:
        cache = {
            'timestamp': time.time(),
            'refresh_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'data': data,
        }
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        print(f"保存缓存失败: {e}")


def get_data():
    """获取数据：优先返回缓存，异步刷新"""
    with _cache_lock:
        if _data_cache['data'] is not None:
            # 超过10分钟且未在加载中，触发后台刷新
            if time.time() - _data_cache['last_refresh'] > 600 and not _data_cache['loading']:
                _data_cache['loading'] = True
                t = threading.Thread(target=_refresh_in_background, daemon=True)
                t.start()
            return _data_cache['data']
        # 无缓存
        if _data_cache['loading']:
            return {'loading': True, 'message': '正在从钉钉获取考勤数据，请稍候...'}
        # 上次失败后60秒内不重试
        if _data_cache['last_error'] and time.time() - _data_cache['error_time'] < 60:
            return {'error': _data_cache['last_error']}
        # 启动后台加载
        _data_cache['loading'] = True
    t = threading.Thread(target=_refresh_in_background, daemon=True)
    t.start()
    return {'loading': True, 'message': '正在从钉钉获取考勤数据，首次加载较慢，请等待...'}


def _refresh_in_background():
    """后台线程刷新数据"""
    global _data_cache
    try:
        print("后台刷新数据中...")
        data = load_data()
        with _cache_lock:
            if 'error' not in data:
                _data_cache['data'] = data
                _data_cache['last_refresh'] = time.time()
                _data_cache['last_error'] = None
                save_cache(data)
                print(f"后台刷新完成: {datetime.now().strftime('%H:%M:%S')}")
            else:
                _data_cache['last_error'] = data.get('error')
                _data_cache['error_time'] = time.time()
                print(f"后台刷新失败: {data.get('error')}")
            _data_cache['loading'] = False
    except Exception as e:
        print(f"后台刷新异常: {e}")
        with _cache_lock:
            _data_cache['last_error'] = str(e)
            _data_cache['error_time'] = time.time()
            _data_cache['loading'] = False


def force_refresh():
    """强制刷新数据（用户点击刷新按钮时调用）"""
    global _data_cache
    with _cache_lock:
        _data_cache['loading'] = False
    data = load_data()
    with _cache_lock:
        if 'error' not in data:
            _data_cache['data'] = data
            _data_cache['last_refresh'] = time.time()
            save_cache(data)
    return data


# Department IDs
DEPT_ROOT = 453935060
DEPT_ZHINENG = 500142337
DEPT_CANGCHU = 628906197
DEPT_WULIU = 981812350
DEPT_YINGSHI_ZONGJINGBAN = 499949673
DEPT_YINGSHI_HR = 499753875

# Token cache
_token_cache = {'token': None, 'expires_at': 0}


def _api_post(url, payload, headers=None):
    """发送 POST 请求并返回 JSON"""
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
        print(f"HTTP ERROR {e.code} {e.reason} for {url}: {body}")
        raise


def _api_get(url):
    """发送 GET 请求并返回 JSON"""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


def get_access_token():
    """获取 DingTalk access_token，带缓存"""
    if _token_cache['token'] and time.time() < _token_cache['expires_at']:
        return _token_cache['token']
    resp = _api_post(
        'https://api.dingtalk.com/v1.0/oauth2/accessToken',
        {'appKey': APP_KEY, 'appSecret': APP_SECRET}
    )
    token = resp['accessToken']
    _token_cache['token'] = token
    _token_cache['expires_at'] = time.time() + resp.get('expireIn', 7200) - 300
    return token


def get_department_sublist(token, dept_id):
    """获取子部门列表"""
    url = f'https://oapi.dingtalk.com/department/list?access_token={token}&id={dept_id}'
    try:
        resp = _api_get(url)
        return resp.get('department', [])
    except Exception:
        return []


def get_department_users(token, dept_id):
    """获取部门下所有用户（自动分页）"""
    users = []
    offset = 0
    while True:
        url = (f'https://oapi.dingtalk.com/user/listbypage?access_token={token}'
               f'&department_id={dept_id}&offset={offset}&size=100')
        try:
            resp = _api_get(url)
        except Exception:
            break
        userlist = resp.get('userlist', [])
        if not userlist:
            break
        users.extend(userlist)
        if resp.get('hasMore', False):
            offset += 100
        else:
            break
    return users


def get_all_users_recursive(token, dept_id):
    """递归获取部门及所有子部门的用户"""
    all_users = []
    # 当前部门用户
    users = get_department_users(token, dept_id)
    all_users.extend(users)
    # 递归子部门
    sub_depts = get_department_sublist(token, dept_id)
    for sub in sub_depts:
        all_users.extend(get_all_users_recursive(token, sub['id']))
    return all_users


def get_attendance_records(token, user_ids, date_from, date_to):
    """获取考勤记录 - 优先使用新版 v1.0 API，失败回退旧版"""
    try:
        return _get_attendance_v1(token, user_ids, date_from, date_to)
    except Exception as e:
        print(f"  v1.0 API 失败: {e}，回退旧版 oapi")
        return _get_attendance_oapi(token, user_ids, date_from, date_to)


def _get_attendance_v1(token, user_ids, date_from, date_to):
    """新版 API: POST /v1.0/attendance/records/query（cursor 分页，更快更稳）"""
    headers = {'x-acs-dingtalk-access-token': token}
    all_records = []
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
                    'userIds': batch,
                    'checkDateFrom': wf,
                    'checkDateTo': wt,
                    'cursor': cursor,
                    'size': 100,
                }
                resp = _api_post(
                    'https://api.dingtalk.com/v1.0/attendance/records/query',
                    payload, headers=headers
                )
                # 新版返回 'result' 数组，时间字段为字符串
                for rec in resp.get('result', []):
                    try:
                        uc_time_str = rec.get('userCheckTime', '')
                        if uc_time_str:
                            rec['userCheckTime'] = int(datetime.strptime(
                                uc_time_str, '%Y-%m-%d %H:%M:%S'
                            ).timestamp() * 1000)
                    except Exception:
                        pass
                    all_records.append(rec)
                if resp.get('hasMore', False):
                    cursor = resp.get('nextCursor', 0)
                else:
                    break
        current = week_end + timedelta(seconds=1)
    return all_records


def _get_attendance_oapi(token, user_ids, date_from, date_to):
    """旧版 API: POST oapi.dingtalk.com/attendance/list（offset 分页）"""
    all_records = []
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
                    'workDateFrom': wf,
                    'workDateTo': wt,
                    'userIdList': batch,
                    'offset': offset,
                    'limit': 50,
                }
                try:
                    resp = _api_post(
                        f'https://oapi.dingtalk.com/attendance/list?access_token={token}',
                        payload
                    )
                except Exception:
                    break
                records = resp.get('recordresult', [])
                all_records.extend(records)
                if resp.get('hasMore', False):
                    offset += 50
                else:
                    break
        current = week_end + timedelta(seconds=1)
    return all_records


def classify_department(dept_ids, dept_names, dept_name_map):
    """根据部门ID和名称分类到体系"""
    # 供应链体 = 物流部
    if DEPT_WULIU in dept_ids:
        return '供应链体'
    # 职能体 = 盈世职能体及其子部门
    if DEPT_ZHINENG in dept_ids:
        return '职能体'
    for did in dept_ids:
        if did in dept_name_map:
            name = dept_name_map[did]
            if '盈世' in name and ('职能' in name or '总经办' in name or '人力资源' in name or '仓储' in name):
                return '职能体'
    # 营销体 = 含 营销/事业部/中心 的部门
    for did in dept_ids:
        if did in dept_name_map:
            name = dept_name_map[did]
            if '营销' in name or '事业部' in name or '中心' in name:
                return '营销体'
    # 默认归职能体
    return '职能体'


def load_data():
    """从 DingTalk API 获取考勤数据"""
    try:
        token = get_access_token()
    except Exception as e:
        return {'error': f'获取钉钉token失败: {e}', 'data_source': 'dingtalk_api_error'}

    # 1. 构建部门名称映射（用于分类）
    dept_name_map = {}
    try:
        root_subs = get_department_sublist(token, DEPT_ROOT)
        for d in root_subs:
            dept_name_map[d['id']] = d.get('name', '')
            # 获取子部门的子部门
            for sd in get_department_sublist(token, d['id']):
                dept_name_map[sd['id']] = sd.get('name', '')
        # 职能体子部门
        zn_subs = get_department_sublist(token, DEPT_ZHINENG)
        for d in zn_subs:
            dept_name_map[d['id']] = d.get('name', '')
    except Exception:
        pass

    # 2. 获取各体系用户
    print("正在获取用户列表...")
    zhinen_users = get_all_users_recursive(token, DEPT_ZHINENG)
    yingxiao_user_ids = set()
    yingxiao_users = []
    # 营销体：从根部门直接找含 营销/事业部/中心 的子部门
    for d in root_subs:
        name = d.get('name', '')
        did = d['id']
        if did == DEPT_ZHINENG:
            continue
        if '营销' in name or '事业部' in name or '中心' in name:
            sub_users = get_all_users_recursive(token, did)
            for u in sub_users:
                if u['userid'] not in yingxiao_user_ids:
                    yingxiao_user_ids.add(u['userid'])
                    yingxiao_users.append(u)
    # 供应链体 = 物流部
    gongying_users = get_all_users_recursive(token, DEPT_WULIU)

    # 去重职能力用户
    seen_ids = set()
    zhinen_unique = []
    for u in zhinen_users:
        if u['userid'] not in seen_ids:
            seen_ids.add(u['userid'])
            zhinen_unique.append(u)

    # 3. 构建用户信息字典
    all_user_map = {}
    for u in zhinen_unique + yingxiao_users + gongying_users:
        uid = u['userid']
        if uid not in all_user_map:
            dept_ids = u.get('department', [])
            sys_name = classify_department(dept_ids, [], dept_name_map)
            dept_name = ''
            for did in dept_ids:
                if did in dept_name_map:
                    dept_name = dept_name_map[did]
                    break
            import re
            pos = u.get('position', '') or ''
            if re.search(r'运营|营销|事业部', pos):
                job_type = '营销岗'
            elif re.search(r'产品', pos):
                job_type = '产品岗'
            else:
                job_type = '职能岗'
            all_user_map[uid] = {
                'name': u.get('name', ''),
                'jobnumber': u.get('jobnumber', ''),
                'dept_name': dept_name,
                'dept_ids': dept_ids,
                'position': pos,
                'system': sys_name,
                'job_type': job_type,
            }

    # 4. 获取考勤记录（1月 - 当前月）
    print("正在获取考勤记录...")
    all_user_ids = list(all_user_map.keys())
    now = datetime.now()
    current_year = now.year
    current_month = now.month
    months_range = []
    month_labels = []
    month_num_to_label = {}
    for m in range(1, current_month + 1):
        first_day = f'{current_year}-{m:02d}-01 00:00:00'
        last_day_num = calendar.monthrange(current_year, m)[1]
        last_day = f'{current_year}-{m:02d}-{last_day_num} 23:59:59'
        months_range.append((first_day, last_day))
        label = f'{m}月'
        month_labels.append(label)
        month_num_to_label[m] = label

    all_records = []
    for mf, mt in months_range:
        print(f"  查询 {mf[:7]}...")
        records = get_attendance_records(token, all_user_ids, mf, mt)
        all_records.extend(records)

    # 5. 计算勤奋次数和工作时长
    # person_data[uid][month] = {'attendance_days': set(), 'diligence': 0, 'work_hours_ms': 0}
    person_data = {}

    for rec in all_records:
        uid = rec.get('userId', '')
        check_type = rec.get('checkType', '')
        time_result = rec.get('timeResult', '')
        user_check_time = rec.get('userCheckTime', 0)
        base_check_time = rec.get('baseCheckTime', 0)

        if not uid or uid not in all_user_map:
            continue

        if uid not in person_data:
            person_data[uid] = {}
            for ml in month_labels:
                person_data[uid][ml] = {
                    'attendance_days': set(),
                    'diligence': 0,
                    'work_hours_ms': 0,
                }

        check_dt = datetime.fromtimestamp(user_check_time / 1000)
        month_key = month_num_to_label.get(check_dt.month, '')
        if not month_key or month_key not in person_data[uid]:
            continue

        pd_entry = person_data[uid][month_key]

        if check_type == 'OffDuty':
            # 出勤天数：下班打卡算出勤
            day_str = check_dt.strftime('%Y-%m-%d')
            pd_entry['attendance_days'].add(day_str)
            # 工作时长 = userCheckTime - baseCheckTime (毫秒 → 小时)
            if user_check_time > 0 and base_check_time > 0 and user_check_time > base_check_time:
                pd_entry['work_hours_ms'] += (user_check_time - base_check_time)
            # 勤奋次数计算
            punch_minutes = check_dt.hour * 60 + check_dt.minute
            threshold_18_30 = 18 * 60 + 30
            cap_20_30 = 20 * 60 + 30
            if punch_minutes >= threshold_18_30:
                qf = (min(punch_minutes, cap_20_30) - threshold_18_30) // 30
                pd_entry['diligence'] += qf
        elif check_type == 'OnDuty':
            # 上班打卡也计出勤（避免无下班记录的情况）
            day_str = check_dt.strftime('%Y-%m-%d')
            pd_entry['attendance_days'].add(day_str)

    # 6. 汇总计算
    system_names = ['职能体', '营销体', '供应链体']

    # 6a. 月度汇总
    monthly = []
    for ml in month_labels:
        total_people = set()
        total_diligence = 0
        total_attendance = 0
        total_work_hours = 0.0
        for uid, pdata in person_data.items():
            if ml not in pdata:
                continue
            info = all_user_map.get(uid, {})
            total_people.add(uid)
            entry = pdata[ml]
            total_diligence += entry['diligence']
            total_attendance += len(entry['attendance_days'])
            total_work_hours += entry['work_hours_ms'] / 3600000.0
        n = len(total_people) if total_people else 1
        monthly.append({
            '月份': ml,
            '总人数': len(total_people),
            '勤奋次数合计': total_diligence,
            '人均勤奋次数': round(total_diligence / n, 2),
            '出勤天数合计': total_attendance,
            '人均出勤天数': round(total_attendance / n, 2),
            '工作时长合计': round(total_work_hours, 1),
            '人均工作时长': round(total_work_hours / n, 2),
        })
    # 合计行
    all_people = set(person_data.keys())
    total_d = sum(pdata[ml]['diligence'] for uid, pdata in person_data.items() for ml in month_labels if ml in pdata)
    total_a = sum(len(pdata[ml]['attendance_days']) for uid, pdata in person_data.items() for ml in month_labels if ml in pdata)
    total_w = sum(pdata[ml]['work_hours_ms'] for uid, pdata in person_data.items() for ml in month_labels if ml in pdata) / 3600000.0
    n_all = len(all_people) if all_people else 1
    monthly.append({
        '月份': '合计',
        '总人数': len(all_people),
        '勤奋次数合计': total_d,
        '人均勤奋次数': round(total_d / n_all, 2),
        '出勤天数合计': total_a,
        '人均出勤天数': round(total_a / n_all, 2),
        '工作时长合计': round(total_w, 1),
        '人均工作时长': round(total_w / n_all, 2),
    })

    # 6b. 体系汇总
    systems = []
    for sys_name in system_names:
        sys_uids = [uid for uid, info in all_user_map.items() if info['system'] == sys_name]
        sys_people = set(sys_uids)
        n_sys = len(sys_people) if sys_people else 1
        s_diligence = 0
        s_attendance = 0
        s_work_hours = 0.0
        for uid in sys_uids:
            for ml in month_labels:
                if uid in person_data and ml in person_data[uid]:
                    entry = person_data[uid][ml]
                    s_diligence += entry['diligence']
                    s_attendance += len(entry['attendance_days'])
                    s_work_hours += entry['work_hours_ms'] / 3600000.0
        systems.append({
            '体系': sys_name,
            '总人次': len(sys_people),
            '勤奋次数合计': s_diligence,
            '人均勤奋次数': round(s_diligence / n_sys, 2),
            '出勤天数合计': s_attendance,
            '人均出勤天数': round(s_attendance / n_sys, 2),
            '工作时长合计': round(s_work_hours, 1),
            '人均工作时长': round(s_work_hours / n_sys, 2),
        })

    # 6c. 交叉分析
    cross_analysis = []
    for sys_name in system_names:
        sys_uids = [uid for uid, info in all_user_map.items() if info['system'] == sys_name]
        row = {'体系': sys_name}
        cumulative_d = 0
        cumulative_count = 0
        for ml in month_labels:
            m_diligence = 0
            m_people = set()
            for uid in sys_uids:
                if uid in person_data and ml in person_data[uid]:
                    m_people.add(uid)
                    m_diligence += person_data[uid][ml]['diligence']
            n_m = len(m_people) if m_people else 1
            avg = round(m_diligence / n_m, 2)
            row[ml] = avg
            cumulative_d += m_diligence
            cumulative_count += n_m
        row['累计人均'] = round(cumulative_d / (cumulative_count if cumulative_count else 1), 2)
        cross_analysis.append(row)

    # 6d. 各体系详情
    data = {}
    for sys_name in system_names:
        sys_uids = [uid for uid, info in all_user_map.items() if info['system'] == sys_name]

        # 月度
        sys_monthly = []
        for ml in month_labels:
            m_people = set()
            m_diligence = 0
            m_attendance = 0
            m_work_hours = 0.0
            for uid in sys_uids:
                if uid in person_data and ml in person_data[uid]:
                    m_people.add(uid)
                    entry = person_data[uid][ml]
                    m_diligence += entry['diligence']
                    m_attendance += len(entry['attendance_days'])
                    m_work_hours += entry['work_hours_ms'] / 3600000.0
            n_m = len(m_people) if m_people else 1
            sys_monthly.append({
                '月份': ml,
                '人数': len(m_people),
                '勤奋次数合计': m_diligence,
                '人均勤奋次数': round(m_diligence / n_m, 2),
                '出勤天数合计': m_attendance,
                '人均出勤天数': round(m_attendance / n_m, 2),
                '工作时长合计': round(m_work_hours, 1),
            })

        # 部门汇总
        dept_agg = {}
        for uid in sys_uids:
            info = all_user_map.get(uid, {})
            dept = info.get('dept_name', '') or '未知部门'
            if dept not in dept_agg:
                dept_agg[dept] = {'uids': set(), 'diligence': 0, 'attendance': 0, 'work_hours': 0.0}
            dept_agg[dept]['uids'].add(uid)
            for ml in month_labels:
                if uid in person_data and ml in person_data[uid]:
                    entry = person_data[uid][ml]
                    dept_agg[dept]['diligence'] += entry['diligence']
                    dept_agg[dept]['attendance'] += len(entry['attendance_days'])
                    dept_agg[dept]['work_hours'] += entry['work_hours_ms'] / 3600000.0
        departments = []
        for dname, ddata in sorted(dept_agg.items(), key=lambda x: -x[1]['diligence']):
            n_d = len(ddata['uids']) if ddata['uids'] else 1
            departments.append({
                '部门': dname,
                '人次': len(ddata['uids']),
                '勤奋次数合计': ddata['diligence'],
                '人均勤奋次数': round(ddata['diligence'] / n_d, 2),
                '出勤天数合计': ddata['attendance'],
                '人均出勤天数': round(ddata['attendance'] / n_d, 2),
                '工作时长合计': round(ddata['work_hours'], 1),
            })

        # 个人明细
        details = []
        for uid in sys_uids:
            info = all_user_map.get(uid, {})
            job_type = info.get('job_type', '')
            for ml in month_labels:
                if uid in person_data and ml in person_data[uid]:
                    entry = person_data[uid][ml]
                    att_days = len(entry['attendance_days'])
                    d_count = entry['diligence']
                    w_hours = round(entry['work_hours_ms'] / 3600000.0, 2)
                    if att_days > 0 or d_count > 0:
                        details.append({
                            '姓名': info.get('name', ''),
                            '工号': info.get('jobnumber', ''),
                            '部门': info.get('dept_name', ''),
                            '职位': info.get('position', ''),
                            '岗位': job_type,
                            '月份': ml,
                            '出勤天数': att_days,
                            '勤奋次数': d_count,
                            '工作时长': w_hours,
                        })

        # 个人排名
        person_cumulative = {}
        for uid in sys_uids:
            info = all_user_map.get(uid, {})
            cum_d = 0
            cum_a = 0
            cum_w = 0.0
            active_months = 0
            for ml in month_labels:
                if uid in person_data and ml in person_data[uid]:
                    entry = person_data[uid][ml]
                    cum_d += entry['diligence']
                    cum_a += len(entry['attendance_days'])
                    cum_w += entry['work_hours_ms'] / 3600000.0
                    if len(entry['attendance_days']) > 0:
                        active_months += 1
            if cum_d > 0 or cum_a > 0:
                person_cumulative[uid] = {
                    '姓名': info.get('name', ''),
                    '工号': info.get('jobnumber', ''),
                    '部门': info.get('dept_name', ''),
                    '岗位': info.get('job_type', ''),
                    '累计勤奋次数': cum_d,
                    '月均勤奋次数': round(cum_d / active_months, 2) if active_months else 0,
                    '累计出勤天数': cum_a,
                    '累计工作时长': round(cum_w, 2),
                }

        rankings = sorted(person_cumulative.values(), key=lambda x: -x['累计勤奋次数'])
        for i, r in enumerate(rankings):
            r['排名'] = i + 1

        data[sys_name] = {
            'monthly': sys_monthly,
            'departments': departments,
            'details': details,
            'rankings': rankings,
        }

    # 6e. 全公司排名
    all_rankings = []
    for sys_name in system_names:
        for r in data[sys_name]['rankings']:
            all_rankings.append({**r, '体系': sys_name})
    all_rankings.sort(key=lambda x: -x['累计勤奋次数'])
    for i, r in enumerate(all_rankings):
        r['排名'] = i + 1

    # 组装最终数据
    result = {
        'monthly': monthly,
        'systems': systems,
        'cross_analysis': cross_analysis,
        'all_rankings': all_rankings,
        'data_source': 'dingtalk_api',
        'month_labels': month_labels,
    }
    # 加入各体系详情
    for sys_name in system_names:
        result[sys_name] = data[sys_name]

    print(f"数据加载完成: 共 {len(all_user_map)} 人, {len(all_records)} 条考勤记录")
    return result


def generate_html(data_json, month_labels=None):
    """生成完整的 HTML 看板页面 - WINWOO 盈世控股品牌风格"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WINWOO 盈世控股 · 2026年勤奋指数看板</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
/* ===== WINWOO 品牌色系 ===== */
:root {{
  --red:       #C41E3A;   /* 主品牌红 */
  --red-dark:  #8B0000;   /* 深红 */
  --red-light: #E8364F;   /* 亮红 */
  --red-dim:   rgba(196,30,58,.12);
  --black:     #1A1A1A;   /* 品牌黑 */
  --gray-900:  #111111;
  --gray-800:  #222222;
  --gray-700:  #333333;
  --gray-500:  #666666;
  --gray-300:  #AAAAAA;
  --gray-100:  #F4F4F4;
  --white:     #FFFFFF;
  --bg:        #F5F5F5;
  --card:      #FFFFFF;
  --border:    #E0E0E0;
  --shadow-sm: 0 2px 8px rgba(0,0,0,.06);
  --shadow:    0 4px 16px rgba(0,0,0,.10);
  --shadow-lg: 0 8px 32px rgba(0,0,0,.15);
  --radius:    10px;
  --transition: .25s cubic-bezier(.4,0,.2,1);
}}

/* ===== Reset & Base ===== */
*, *::before, *::after {{ margin:0; padding:0; box-sizing:border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background: var(--bg);
  color: var(--black);
  line-height: 1.6;
  overflow-x: hidden;
}}

/* ===== Scroll Animation ===== */
.reveal {{
  opacity: 0;
  transform: translateY(28px);
  transition: opacity .55s ease, transform .55s ease;
}}
.reveal.visible {{
  opacity: 1;
  transform: translateY(0);
}}
.reveal-delay-1 {{ transition-delay: .08s; }}
.reveal-delay-2 {{ transition-delay: .16s; }}
.reveal-delay-3 {{ transition-delay: .24s; }}
.reveal-delay-4 {{ transition-delay: .32s; }}

/* ===== Header ===== */
.header {{
  background: var(--black);
  color: var(--white);
  padding: 0 40px;
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 2px 20px rgba(0,0,0,.4);
}}
.header-left {{
  display: flex;
  align-items: center;
  gap: 16px;
}}
.header-logo {{
  display: flex;
  align-items: center;
  gap: 10px;
}}
.header-logo .w-mark {{
  width: 36px;
  height: 36px;
  background: var(--red);
  clip-path: polygon(20% 0%, 50% 60%, 80% 0%, 100% 0%, 70% 100%, 50% 50%, 30% 100%, 0% 0%);
}}
.header-logo .brand {{
  font-size: 20px;
  font-weight: 900;
  letter-spacing: 2px;
  color: var(--white);
}}
.header-logo .brand span {{ color: var(--red); }}
.header-divider {{
  width: 1px;
  height: 28px;
  background: rgba(255,255,255,.2);
}}
.header-title {{
  font-size: 15px;
  font-weight: 500;
  opacity: .85;
  letter-spacing: .5px;
}}
.header-right {{
  display: flex;
  align-items: center;
  gap: 20px;
}}
.header-stat {{
  text-align: center;
}}
.header-stat .s-val {{
  font-size: 18px;
  font-weight: 800;
  color: var(--red-light);
  line-height: 1;
}}
.header-stat .s-lbl {{
  font-size: 11px;
  opacity: .6;
  margin-top: 2px;
}}
.live-dot {{
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  opacity: .7;
}}
.live-dot::before {{
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #4ade80;
  animation: blink 2s infinite;
  flex-shrink: 0;
}}
@keyframes blink {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:.2; }} }}
#updateTime {{ font-size: 12px; opacity: .6; }}
.refresh-btn {{
  background: var(--red);
  border: none;
  color: var(--white);
  padding: 7px 18px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: .5px;
  transition: background var(--transition), transform var(--transition), box-shadow var(--transition);
  box-shadow: 0 2px 8px rgba(196,30,58,.4);
}}
.refresh-btn:hover {{
  background: var(--red-light);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(196,30,58,.5);
}}
.refresh-btn:active {{ transform: translateY(0); }}

/* ===== Hero Banner ===== */
.hero {{
  background: linear-gradient(135deg, var(--gray-900) 0%, var(--gray-800) 50%, #2a0a10 100%);
  padding: 36px 40px;
  position: relative;
  overflow: hidden;
}}
.hero::before {{
  content: '';
  position: absolute;
  top: -60px; right: -60px;
  width: 240px; height: 240px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(196,30,58,.25), transparent 70%);
  pointer-events: none;
}}
.hero::after {{
  content: '';
  position: absolute;
  bottom: -40px; left: 20%;
  width: 160px; height: 160px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(196,30,58,.15), transparent 70%);
  pointer-events: none;
}}
.hero-inner {{
  max-width: 1400px;
  margin: 0 auto;
  position: relative;
}}
.hero-label {{
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 3px;
  color: var(--red);
  text-transform: uppercase;
  margin-bottom: 8px;
}}
.hero-title {{
  font-size: 32px;
  font-weight: 900;
  color: var(--white);
  letter-spacing: 1px;
  margin-bottom: 4px;
}}
.hero-sub {{
  font-size: 14px;
  color: rgba(255,255,255,.5);
}}

/* ===== Container ===== */
.container {{
  max-width: 1400px;
  margin: 0 auto;
  padding: 28px 40px;
}}

/* ===== Section Title ===== */
.section-title {{
  font-size: 17px;
  font-weight: 800;
  margin: 36px 0 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--gray-900);
  letter-spacing: .5px;
}}
.section-title::before {{
  content: '';
  display: block;
  width: 4px;
  height: 20px;
  background: var(--red);
  border-radius: 2px;
  flex-shrink: 0;
}}
.section-title .s-tag {{
  font-size: 11px;
  font-weight: 700;
  background: var(--red-dim);
  color: var(--red);
  padding: 2px 8px;
  border-radius: 4px;
  letter-spacing: 1px;
}}

/* ===== KPI Cards ===== */
.kpi-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 28px;
}}
.kpi-card {{
  background: var(--card);
  border-radius: var(--radius);
  padding: 22px 24px;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--border);
  position: relative;
  overflow: hidden;
  cursor: default;
  transition: transform var(--transition), box-shadow var(--transition), border-color var(--transition);
}}
.kpi-card::after {{
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: var(--red);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform var(--transition);
}}
.kpi-card:hover {{ transform: translateY(-3px); box-shadow: var(--shadow); border-color: rgba(196,30,58,.25); }}
.kpi-card:hover::after {{ transform: scaleX(1); }}
.kpi-card .icon {{
  width: 40px; height: 40px;
  border-radius: 8px;
  background: var(--red-dim);
  display: flex; align-items: center; justify-content: center;
  font-size: 18px;
  margin-bottom: 14px;
}}
.kpi-card .label {{
  font-size: 12px;
  font-weight: 600;
  color: var(--gray-500);
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 6px;
}}
.kpi-card .value {{
  font-size: 30px;
  font-weight: 900;
  color: var(--black);
  line-height: 1;
  letter-spacing: -1px;
}}
.kpi-card .value.red {{ color: var(--red); }}
.kpi-card .sub {{
  font-size: 12px;
  color: var(--gray-500);
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 4px;
}}
.kpi-card .sub .arrow {{
  color: var(--red);
  font-weight: 700;
}}

/* ===== Chart Row ===== */
.chart-row {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 24px;
}}
.chart-box {{
  background: var(--card);
  border-radius: var(--radius);
  padding: 22px 24px;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--border);
  transition: box-shadow var(--transition);
}}
.chart-box:hover {{ box-shadow: var(--shadow); }}
.chart-box h3 {{
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 16px;
  color: var(--gray-700);
  display: flex;
  align-items: center;
  gap: 8px;
}}
.chart-box h3::before {{
  content: '';
  display: block;
  width: 3px;
  height: 14px;
  background: var(--red);
  border-radius: 2px;
}}
.chart-box canvas {{ max-height: 300px; }}

/* ===== Tabs ===== */
.tabs-wrapper {{
  background: var(--card);
  border-radius: var(--radius);
  border: 1px solid var(--border);
  overflow: hidden;
  margin-bottom: 24px;
  box-shadow: var(--shadow-sm);
}}
.tabs {{
  display: flex;
  background: var(--gray-100);
  border-bottom: 2px solid var(--border);
  padding: 0 4px;
}}
.tab {{
  padding: 12px 28px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-500);
  border: none;
  background: none;
  position: relative;
  transition: color var(--transition);
  letter-spacing: .5px;
}}
.tab::after {{
  content: '';
  position: absolute;
  bottom: -2px; left: 0; right: 0;
  height: 2px;
  background: var(--red);
  transform: scaleX(0);
  transition: transform var(--transition);
}}
.tab:hover {{ color: var(--red); }}
.tab.active {{
  color: var(--red);
  background: transparent;
}}
.tab.active::after {{ transform: scaleX(1); }}
.tab-content {{ display: none; padding: 24px; }}
.tab-content.active {{
  display: block;
  animation: fadeSlideIn .3s ease;
}}
@keyframes fadeSlideIn {{
  from {{ opacity: 0; transform: translateY(10px); }}
  to   {{ opacity: 1; transform: translateY(0); }}
}}

/* ===== Tables ===== */
.table-wrap {{
  background: var(--card);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--border);
  overflow: hidden;
  margin-bottom: 24px;
}}
.table-header {{
  padding: 16px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  background: var(--gray-100);
}}
.table-header h3 {{
  font-size: 14px;
  font-weight: 700;
  color: var(--gray-700);
  display: flex;
  align-items: center;
  gap: 8px;
}}
.table-header h3::before {{
  content: '';
  display: block;
  width: 3px;
  height: 14px;
  background: var(--red);
  border-radius: 2px;
}}
.table-scroll {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
thead tr {{ background: #fafafa; }}
th {{
  padding: 10px 14px;
  text-align: left;
  font-weight: 700;
  font-size: 12px;
  color: var(--gray-500);
  text-transform: uppercase;
  letter-spacing: .8px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}}
td {{
  padding: 11px 14px;
  border-bottom: 1px solid #f0f0f0;
  white-space: nowrap;
  transition: background var(--transition);
}}
tbody tr {{
  transition: background var(--transition), transform var(--transition);
}}
tbody tr:hover {{
  background: rgba(196,30,58,.04);
}}
tbody tr:last-child td {{ border-bottom: none; }}

/* Rank badges */
.rank {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px; height: 28px;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 800;
  background: var(--gray-100);
  color: var(--gray-500);
}}
.rank-1 {{ background: linear-gradient(135deg, #E8B84B, #C9920A); color: #fff; box-shadow: 0 2px 8px rgba(200,145,10,.4); }}
.rank-2 {{ background: linear-gradient(135deg, #9CA3AF, #6B7280); color: #fff; }}
.rank-3 {{ background: linear-gradient(135deg, #C4813A, #96510F); color: #fff; }}

/* Progress bars in table */
.progress-bar {{
  height: 4px;
  background: var(--gray-100);
  border-radius: 2px;
  margin-top: 4px;
  overflow: hidden;
}}
.progress-bar .fill {{
  height: 100%;
  background: linear-gradient(90deg, var(--red-dark), var(--red));
  border-radius: 2px;
  transition: width 1s ease;
}}

/* Body tag system */
.tag {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}}
.tag-red {{ background: rgba(196,30,58,.1); color: var(--red); }}
.tag-gray {{ background: var(--gray-100); color: var(--gray-700); }}
.tag-dark {{ background: var(--gray-800); color: var(--white); }}
.tag-job {{ background: rgba(41,128,185,.1); color: #2980B9; }}

/* ===== Heatmap ===== */
.heatmap-wrap {{
  background: var(--card);
  border-radius: var(--radius);
  border: 1px solid var(--border);
  overflow: hidden;
  margin-bottom: 24px;
  box-shadow: var(--shadow-sm);
}}
.heatmap {{
  display: grid;
  grid-template-columns: 120px repeat(4, 1fr) 120px;
  gap: 0;
}}
.heatmap-cell {{
  padding: 14px 10px;
  text-align: center;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid rgba(255,255,255,.15);
  transition: transform var(--transition), box-shadow var(--transition);
  cursor: default;
}}
.heatmap-cell:hover {{ transform: scale(1.05); box-shadow: var(--shadow); z-index: 1; position: relative; }}
.heatmap-header {{
  background: var(--black);
  color: var(--white);
  font-size: 12px;
  letter-spacing: 1px;
  text-transform: uppercase;
}}
.heatmap-row-label {{
  background: var(--gray-100);
  color: var(--gray-700);
  font-weight: 700;
  font-size: 13px;
}}
.heatmap-total {{
  background: rgba(196,30,58,.1);
  color: var(--red);
  font-weight: 800;
}}

/* ===== Number counter animation ===== */
.count-up {{ display: inline-block; }}

/* ===== System cards (body overview) ===== */
.system-cards {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}}
.system-card {{
  background: var(--card);
  border-radius: var(--radius);
  border: 1px solid var(--border);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
  cursor: default;
  transition: transform var(--transition), box-shadow var(--transition);
}}
.system-card:hover {{ transform: translateY(-4px); box-shadow: var(--shadow-lg); }}
.system-card-header {{
  background: var(--black);
  padding: 14px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}}
.system-card-header .name {{
  font-size: 15px;
  font-weight: 800;
  color: var(--white);
  letter-spacing: 1px;
}}
.system-card-header .badge {{
  background: var(--red);
  color: var(--white);
  font-size: 12px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 20px;
}}
.system-card-body {{
  padding: 16px 20px;
}}
.system-stat-row {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid #f4f4f4;
  font-size: 13px;
}}
.system-stat-row:last-child {{ border-bottom: none; }}
.system-stat-row .s-key {{ color: var(--gray-500); }}
.system-stat-row .s-val {{ font-weight: 700; color: var(--black); }}

/* ===== Tooltip ===== */
.tooltip-wrapper {{ position: relative; display: inline-block; }}
.tooltip-wrapper:hover .tooltip-box {{ opacity:1; pointer-events:auto; transform:translateY(0); }}
.tooltip-box {{
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%) translateY(4px);
  background: var(--black);
  color: var(--white);
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 4px;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity .2s, transform .2s;
  z-index: 200;
}}

/* ===== Footer ===== */
.footer {{
  background: var(--black);
  color: rgba(255,255,255,.4);
  text-align: center;
  padding: 20px;
  font-size: 12px;
  letter-spacing: 1px;
  margin-top: 40px;
}}
.footer span {{ color: var(--red); }}

/* ===== Loading ===== */
.loading-screen {{
  min-height: 300px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: var(--gray-500);
}}
.spinner {{
  width: 36px; height: 36px;
  border: 3px solid rgba(196,30,58,.2);
  border-top-color: var(--red);
  border-radius: 50%;
  animation: spin .8s linear infinite;
}}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}

/* ===== Responsive ===== */
@media (max-width: 1024px) {{ .chart-row {{ grid-template-columns: 1fr; }} }}
@media (max-width: 768px) {{
  .header {{ padding: 0 16px; height: auto; flex-wrap: wrap; padding: 12px 16px; gap: 8px; }}
  .container {{ padding: 16px; }}
  .hero {{ padding: 24px 16px; }}
  .hero-title {{ font-size: 22px; }}
  .kpi-grid {{ grid-template-columns: 1fr 1fr; }}
  .system-cards {{ grid-template-columns: 1fr; }}
  .header-right .header-stat {{ display: none; }}
}}
</style>
</head>
<body>

<!-- ===== Header ===== -->
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
    <div class="header-stat">
      <div class="s-val" id="hdTotal">—</div>
      <div class="s-lbl">总勤奋次数</div>
    </div>
    <div class="header-stat">
      <div class="s-val" id="hdAvg">—</div>
      <div class="s-lbl">人均次数</div>
    </div>
    <div class="live-dot">实时数据</div>
    <div id="updateTime"></div>
    <button class="refresh-btn" onclick="forceRefresh()">↻ 刷新数据</button>
  </div>
</header>

<!-- ===== Hero ===== -->
<div class="hero">
  <div class="hero-inner">
    <div class="hero-label">2026 ANNUAL DILIGENCE INDEX</div>
    <div class="hero-title">浙江盈世控股有限公司</div>
    <div class="hero-sub">2026年勤奋指数全年看板 · 数据区间：{month_labels[0] + ' — ' + month_labels[-1] if month_labels else '1月 — 4月'} · 职能体 / 营销体 / 供应链体</div>
  </div>
</div>

<!-- ===== Main Content ===== -->
<div class="container" id="app">
  <div class="loading-screen">
    <div class="spinner"></div>
    <div>数据加载中...</div>
  </div>
</div>

<!-- ===== Footer ===== -->
<footer class="footer">
  <span>WINWOO</span> 盈世控股 · 勤奋指数看板 &copy; 2026 &nbsp;|&nbsp; 数据来源：钉钉考勤API &nbsp;|&nbsp; 每次刷新获取最新数据
</footer>

<script>
const DATA_URL = '/api/data';
let DATA = null;
let charts = {{}};

/* ===== Colors ===== */
const RED   = '#C41E3A';
const RED2  = '#E8364F';
const RED3  = '#8B0000';
const BLACK = '#1A1A1A';
const GRAY  = '#888888';
const PALETTE = [RED, '#E67E22', '#2980B9', '#27AE60', '#8E44AD', '#16A085', '#D35400', '#2C3E50'];

async function fetchData() {{
  const res = await fetch(DATA_URL);
  return await res.json();
}}

/* ===== Number animation ===== */
function animateNumber(el, target, duration=900, decimals=0, suffix='') {{
  const start = performance.now();
  const from = 0;
  (function step(ts) {{
    const t = Math.min((ts - start) / duration, 1);
    const ease = 1 - Math.pow(1-t, 3);
    const val = from + (target - from) * ease;
    el.textContent = (decimals > 0 ? val.toFixed(decimals) : Math.round(val).toLocaleString()) + suffix;
    if (t < 1) requestAnimationFrame(step);
    else el.textContent = (decimals > 0 ? target.toFixed(decimals) : target.toLocaleString()) + suffix;
  }})(start);
}}

/* ===== Scroll Reveal ===== */
function initReveal() {{
  const io = new IntersectionObserver((entries) => {{
    entries.forEach(e => {{ if (e.isIntersecting) e.target.classList.add('visible'); }});
  }}, {{ threshold: 0.1 }});
  document.querySelectorAll('.reveal').forEach(el => io.observe(el));
}}

/* ===== Heat color (red palette) ===== */
function getHeatColor(val, max) {{
  const r = val / max;
  if (r > .75) return RED;
  if (r > .5)  return '#D9536A';
  if (r > .25) return '#EBABB5';
  return '#F9E3E6';
}}
function getHeatText(val, max) {{
  return val/max > .45 ? '#fff' : BLACK;
}}

/* ===== Chart theme ===== */
Chart.defaults.font.family = "'-apple-system','PingFang SC','Microsoft YaHei',sans-serif";
Chart.defaults.color = GRAY;

/* ===== Render Dashboard ===== */
function renderDashboard(d) {{
  const app = document.getElementById('app');
  const m = d.monthly;
  const total = m.find(x => x.月份 === '合计') || m[m.length-1];

  // Update header stats
  animateNumber(document.getElementById('hdTotal'), total.勤奋次数合计, 1000);
  animateNumber(document.getElementById('hdAvg'), total.人均勤奋次数, 800, 2);

  app.innerHTML = `
    <!-- KPI Row -->
    <div class="kpi-grid">
      <div class="kpi-card reveal"><div class="icon">👥</div><div class="label">累计总人次</div><div class="value red count-up" data-val="${{total.总人数}}" data-dec="0">${{total.总人数}}</div><div class="sub"><span class="arrow">↑</span> ${{d.month_labels[0]}}–${{d.month_labels[d.month_labels.length-1]}}累计</div></div>
      <div class="kpi-card reveal reveal-delay-1"><div class="icon">💪</div><div class="label">勤奋次数合计</div><div class="value count-up" data-val="${{total.勤奋次数合计}}" data-dec="0">${{total.勤奋次数合计.toLocaleString()}}</div><div class="sub">人均 <strong style="color:var(--red)">${{total.人均勤奋次数}}</strong> 次</div></div>
      <div class="kpi-card reveal reveal-delay-2"><div class="icon">📅</div><div class="label">出勤天数合计</div><div class="value count-up" data-val="${{total.出勤天数合计}}" data-dec="0">${{total.出勤天数合计.toLocaleString()}}</div><div class="sub">人均 <strong>${{total.人均出勤天数}}</strong> 天</div></div>
      <div class="kpi-card reveal reveal-delay-3"><div class="icon">⏱</div><div class="label">工作时长合计</div><div class="value count-up" data-val="${{total.工作时长合计}}" data-dec="0">${{total.工作时长合计.toLocaleString()}}h</div><div class="sub">人均 <strong>${{total.人均工作时长}}h</strong></div></div>
    </div>

    <!-- 三大体系总览 -->
    <div class="section-title reveal"><span>三大体系总览</span><span class="s-tag">OVERVIEW</span></div>
    <div class="system-cards reveal" id="systemCards"></div>

    <!-- 月度趋势 -->
    <div class="section-title reveal">月度趋势 <span class="s-tag">MONTHLY TREND</span></div>
    <div class="chart-row reveal">
      <div class="chart-box">
        <h3>人均勤奋次数 · 月度变化</h3>
        <canvas id="chartMonthly"></canvas>
      </div>
      <div class="chart-box">
        <h3>人均工作时长 (h)</h3>
        <canvas id="chartHours"></canvas>
      </div>
    </div>

    <!-- 体系对比 -->
    <div class="section-title reveal">体系对比分析 <span class="s-tag">SYSTEM COMPARE</span></div>
    <div class="chart-row reveal">
      <div class="chart-box">
        <h3>体系人均勤奋次数对比</h3>
        <canvas id="chartSystems"></canvas>
      </div>
      <div class="chart-box">
        <h3>体系 × 月份 趋势交叉</h3>
        <canvas id="chartCross"></canvas>
      </div>
    </div>

    <!-- 热力图 -->
    <div class="section-title reveal">月度热力图 <span class="s-tag">HEATMAP</span></div>
    <div class="heatmap-wrap reveal">
      <div class="heatmap" id="heatmap"></div>
    </div>

    <!-- 各体系详情 -->
    <div class="section-title reveal">各体系详情 <span class="s-tag">DETAIL</span></div>
    <div class="tabs-wrapper reveal">
      <div class="tabs" id="jobTabs">
        <button class="tab-btn active" onclick="filterByJob('全部')" data-job="全部">全部岗位</button>
        <button class="tab-btn" onclick="filterByJob('职能岗')" data-job="职能岗">职能岗</button>
        <button class="tab-btn" onclick="filterByJob('营销岗')" data-job="营销岗">营销岗</button>
        <button class="tab-btn" onclick="filterByJob('产品岗')" data-job="产品岗">产品岗</button>
      </div>
      <div class="tabs" id="systemTabs"></div>
      <div id="systemContent"></div>
    </div>

    <!-- 全公司排名 -->
    <div class="section-title reveal">全公司个人勤奋排名 <span class="s-tag">TOP 20</span></div>
    <div class="table-wrap reveal">
      <div class="table-header">
        <h3>全公司 · 勤奋次数 TOP 20</h3>
        <span style="font-size:12px;color:var(--gray-500)">${{d.month_labels[0]}}–${{d.month_labels[d.month_labels.length-1]}}累计勤奋次数</span>
      </div>
      <div class="table-scroll">
        <table>
          <thead><tr><th>排名</th><th>姓名</th><th>工号</th><th>部门</th><th>岗位</th><th>体系</th><th>累计勤奋次数</th><th>月均</th><th>累计出勤</th><th>工作时长</th></tr></thead>
          <tbody id="rankBody"></tbody>
        </table>
      </div>
    </div>
  `;

  renderSystemCards(d);
  renderCharts(d);
  renderHeatmap(d);
  renderSystemTabs(d);
  renderRanking(d);
  initReveal();
  // Animate count-up cards
  document.querySelectorAll('.count-up[data-val]').forEach(el => {{
    animateNumber(el, parseFloat(el.dataset.val), 900, parseInt(el.dataset.dec)||0);
  }});
}}

/* ===== System Overview Cards ===== */
function renderSystemCards(d) {{
  const el = document.getElementById('systemCards');
  const systems = [
    {{ key:'职能体', icon:'🏢', color: RED }},
    {{ key:'营销体', icon:'📣', color: '#2980B9' }},
    {{ key:'供应链体', icon:'🔗', color: '#27AE60' }},
  ];
  el.innerHTML = systems.map(s => {{
    const sys = d[s.key];
    const sum = d.systems.find(x => x.体系 === s.key) || {{}};
    return `
      <div class="system-card">
        <div class="system-card-header">
          <div class="name">${{s.icon}} ${{s.key}}</div>
          <div class="badge">人均 ${{sum.人均勤奋次数}}</div>
        </div>
        <div class="system-card-body">
          <div class="system-stat-row"><span class="s-key">总人次</span><span class="s-val">${{sum.总人次}}</span></div>
          <div class="system-stat-row"><span class="s-key">勤奋次数合计</span><span class="s-val">${{(sum.勤奋次数合计||0).toLocaleString()}}</span></div>
          <div class="system-stat-row"><span class="s-key">人均出勤天数</span><span class="s-val">${{sum.人均出勤天数}} 天</span></div>
          <div class="system-stat-row"><span class="s-key">人均工作时长</span><span class="s-val">${{sum.人均工作时长}}h</span></div>
          <div class="system-stat-row"><span class="s-key">部门数量</span><span class="s-val">${{sys ? sys.departments.length : 0}}</span></div>
        </div>
      </div>
    `;
  }}).join('');
}}

/* ===== Charts ===== */
function renderCharts(d) {{
  const m = d.monthly.filter(x => x.月份 !== '合计');
  const labels = m.map(x => x.月份);
  const gridColor = 'rgba(0,0,0,.05)';

  // Monthly line
  if (charts.monthly) charts.monthly.destroy();
  charts.monthly = new Chart(document.getElementById('chartMonthly'), {{
    type: 'line',
    data: {{
      labels,
      datasets: [
        {{ label:'人均勤奋次数', data:m.map(x=>x.人均勤奋次数), borderColor:RED, backgroundColor:'rgba(196,30,58,.08)', fill:true, tension:.4, pointRadius:6, pointBackgroundColor:RED, pointHoverRadius:9, borderWidth:2.5 }},
        {{ label:'人均出勤天数', data:m.map(x=>x.人均出勤天数), borderColor:BLACK, backgroundColor:'rgba(26,26,26,.05)', fill:false, tension:.4, pointRadius:5, pointBackgroundColor:BLACK, yAxisID:'y1', borderDash:[5,3], borderWidth:1.5 }},
      ]
    }},
    options: {{
      responsive:true,
      interaction:{{ mode:'index', intersect:false }},
      plugins:{{ legend:{{ position:'top', labels:{{ usePointStyle:true, boxWidth:8 }} }} }},
      scales:{{
        y:{{ beginAtZero:true, grid:{{ color:gridColor }}, title:{{ display:true, text:'勤奋次数' }} }},
        y1:{{ position:'right', beginAtZero:true, grid:{{ drawOnChartArea:false }}, title:{{ display:true, text:'出勤天数' }} }},
      }}
    }}
  }});

  // Hours bar
  if (charts.hours) charts.hours.destroy();
  charts.hours = new Chart(document.getElementById('chartHours'), {{
    type: 'bar',
    data: {{
      labels,
      datasets: [
        {{ label:'人均工作时长(h)', data:m.map(x=>x.人均工作时长), backgroundColor:[RED+'CC',RED+'AA',RED+'88',RED], borderRadius:6, borderSkipped:false }},
      ]
    }},
    options: {{
      responsive:true,
      plugins:{{ legend:{{ display:false }} }},
      scales:{{ y:{{ beginAtZero:true, grid:{{ color:gridColor }}, title:{{ display:true, text:'小时(h)' }} }} }}
    }}
  }});

  // System bar - 多维度对比
  const sys = d.systems;
  const sysColors = [RED, BLACK, '#888888'];
  if (charts.systems) charts.systems.destroy();
  charts.systems = new Chart(document.getElementById('chartSystems'), {{
    type: 'bar',
    data: {{
      labels: sys.map(x=>x.体系),
      datasets: [
        {{ label:'人均勤奋次数', data:sys.map(x=>x.人均勤奋次数), backgroundColor:sysColors, borderRadius:8, borderSkipped:false, categoryPercentage:0.8, barPercentage:0.9 }},
        {{ label:'人均出勤天数', data:sys.map(x=>x.人均出勤天数), backgroundColor:sysColors.map(c=>c+'AA'), borderRadius:8, borderSkipped:false, categoryPercentage:0.8, barPercentage:0.9 }},
        {{ label:'人均工作时长(h)', data:sys.map(x=>x.人均工作时长), backgroundColor:sysColors.map(c=>c+'55'), borderRadius:8, borderSkipped:false, categoryPercentage:0.8, barPercentage:0.9 }},
      ]
    }},
    options: {{
      responsive:true,
      plugins:{{ legend:{{ position:'top', labels:{{ usePointStyle:true, boxWidth:8 }} }} }},
      scales:{{ y:{{ beginAtZero:true, grid:{{ color:gridColor }}, title:{{ display:true, text:'数值' }} }} }}
    }}
  }});

  // Cross line
  const cross = d.cross_analysis;
  const months = d.month_labels;
  const crossColors = [RED, BLACK, '#888'];
  if (charts.cross) charts.cross.destroy();
  charts.cross = new Chart(document.getElementById('chartCross'), {{
    type: 'line',
    data: {{
      labels: months,
      datasets: cross.map((c,i) => ({{
        label: c.体系,
        data: months.map(mm=>c[mm]),
        borderColor: crossColors[i],
        backgroundColor: crossColors[i]+'20',
        fill: i===0,
        tension: .4,
        pointRadius: 6,
        pointBackgroundColor: crossColors[i],
        borderWidth: i===0 ? 3 : 2,
      }}))
    }},
    options: {{
      responsive:true,
      plugins:{{ legend:{{ position:'top', labels:{{ usePointStyle:true, boxWidth:8 }} }} }},
      scales:{{ y:{{ beginAtZero:true, grid:{{ color:gridColor }}, title:{{ display:true, text:'人均勤奋次数' }} }} }}
    }}
  }});
}}

/* ===== Heatmap ===== */
function renderHeatmap(d) {{
  const el = document.getElementById('heatmap');
  const cross = d.cross_analysis;
  const months = d.month_labels;
  const allVals = cross.flatMap(c=>months.map(mm=>c[mm]));
  const maxVal = Math.max(...allVals);

  let html = '<div class="heatmap-cell heatmap-header">体系</div>';
  months.forEach(mm => html += `<div class="heatmap-cell heatmap-header">${{mm}}</div>`);
  html += '<div class="heatmap-cell heatmap-header">累计人均</div>';

  cross.forEach(c => {{
    html += `<div class="heatmap-cell heatmap-row-label">${{c.体系}}</div>`;
    months.forEach(mm => {{
      const v = c[mm];
      const bg = getHeatColor(v, maxVal);
      const col = getHeatText(v, maxVal);
      html += `<div class="heatmap-cell" style="background:${{bg}};color:${{col}}">${{v}}</div>`;
    }});
    html += `<div class="heatmap-cell heatmap-total">${{c.累计人均}}</div>`;
  }});
  el.innerHTML = html;
}}

/* ===== Job Type Filter ===== */
let currentJobFilter = '全部';
function filterByJob(job) {{
  currentJobFilter = job;
  document.querySelectorAll('#jobTabs .tab-btn').forEach(b => b.classList.toggle('active', b.dataset.job === job));
  renderSystemTabs(DATA);
}}

/* ===== System Tabs ===== */
function renderSystemTabs(d) {{
  const systems = ['职能体','营销体','供应链体'];
  const tabsEl = document.getElementById('systemTabs');
  const contentEl = document.getElementById('systemContent');
  const tabColors = [RED, BLACK, '#555'];

  tabsEl.innerHTML = systems.map((s,i) => `<button class="tab ${{i===0?'active':''}}" onclick="switchTab('${{s}}',this)">${{s}}</button>`).join('');

  let html = '';
  systems.forEach((s, i) => {{
    const sys = d[s];
    if (!sys) return;
    const maxDept = Math.max(...sys.departments.map(r=>r.人均勤奋次数), 1);

    let deptRows = sys.departments.map((r,idx) => `
      <tr>
        <td><span class="rank ${{idx<3?'rank-'+(idx+1):''}} ">${{idx+1}}</span></td>
        <td><strong>${{r.部门}}</strong></td>
        <td>${{r.人次}}</td>
        <td>
          <strong style="color:var(--red)">${{r.人均勤奋次数}}</strong>
          <div class="progress-bar"><div class="fill" style="width:${{(r.人均勤奋次数/maxDept*100).toFixed(1)}}%"></div></div>
        </td>
        <td>${{r.勤奋次数合计}}</td>
        <td>${{r.人均出勤天数}}</td>
        <td>${{r.工作时长合计}}h</td>
      </tr>
    `).join('');

    const maxRank = Math.max(...sys.rankings.map(r=>r.累计勤奋次数), 1);
    let rankingsFiltered = sys.rankings;
    if (currentJobFilter !== '全部') {{
      rankingsFiltered = sys.rankings.filter(r => (r.岗位||'职能岗') === currentJobFilter);
    }}
    let rankRows = rankingsFiltered.map(r => {{
      const cls = r.排名<=3 ? ` rank-${{r.排名}}` : '';
      return `
        <tr>
          <td><span class="rank${{cls}}">${{r.排名}}</span></td>
          <td><strong>${{r.姓名}}</strong></td>
          <td style="color:var(--gray-500)">${{r.工号}}</td>
          <td>${{r.部门}}</td>
          <td><span class="tag tag-job">${{r.岗位||'职能岗'}}</span></td>
          <td>
            <strong style="color:var(--red)">${{r.累计勤奋次数}}</strong>
            <div class="progress-bar"><div class="fill" style="width:${{(r.累计勤奋次数/maxRank*100).toFixed(1)}}%"></div></div>
          </td>
          <td>${{r.月均勤奋次数}}</td>
          <td>${{r.累计出勤天数}}</td>
          <td>${{r.累计工作时长}}h</td>
        </tr>
      `;
    }}).join('');

    html += `
      <div class="tab-content ${{i===0?'active':''}}" id="tab-${{s}}">
        <div class="chart-row" style="margin-top:0">
          <div class="chart-box">
            <h3>${{s}} · 部门排名</h3>
            <canvas id="chartDept-${{s}}"></canvas>
          </div>
          <div class="chart-box">
            <h3>${{s}} · 各月人均勤奋次数</h3>
            <canvas id="chartSysMonthly-${{s}}"></canvas>
          </div>
        </div>
        <div class="table-wrap">
          <div class="table-header"><h3>部门排名</h3></div>
          <div class="table-scroll">
            <table>
              <thead><tr><th>#</th><th>部门</th><th>人次</th><th>人均勤奋次数</th><th>合计次数</th><th>人均出勤</th><th>工作时长</th></tr></thead>
              <tbody>${{deptRows}}</tbody>
            </table>
          </div>
        </div>
        <div class="table-wrap">
          <div class="table-header"><h3>个人勤奋排名</h3></div>
          <div class="table-scroll">
            <table>
              <thead><tr><th>排名</th><th>姓名</th><th>工号</th><th>部门</th><th>岗位</th><th>累计勤奋次数</th><th>月均</th><th>累计出勤</th><th>工作时长</th></tr></thead>
              <tbody>${{rankRows}}</tbody>
            </table>
          </div>
        </div>
      </div>
    `;
  }});
  contentEl.innerHTML = html;

  // Render dept charts
  systems.forEach((s,i) => {{
    const sys = d[s];
    if (!sys) return;
    const c = [RED, BLACK, '#666'];

    if (charts['dept-'+s]) charts['dept-'+s].destroy();
    charts['dept-'+s] = new Chart(document.getElementById('chartDept-'+s), {{
      type:'bar',
      data:{{
        labels: sys.departments.map(r=>r.部门),
        datasets:[{{ label:'人均勤奋次数', data:sys.departments.map(r=>r.人均勤奋次数), backgroundColor:c[i]+'99', borderRadius:4 }}]
      }},
      options:{{
        indexAxis:'y', responsive:true,
        plugins:{{ legend:{{ display:false }} }},
        scales:{{ x:{{ beginAtZero:true, grid:{{ color:'rgba(0,0,0,.05)' }} }} }}
      }}
    }});

    if (charts['sysM-'+s]) charts['sysM-'+s].destroy();
    charts['sysM-'+s] = new Chart(document.getElementById('chartSysMonthly-'+s), {{
      type:'line',
      data:{{
        labels: sys.monthly.map(r=>r.月份),
        datasets:[{{
          label:'人均勤奋次数',
          data: sys.monthly.map(r=>r.人均勤奋次数),
          borderColor:c[i], backgroundColor:c[i]+'20',
          fill:true, tension:.4, pointRadius:7,
          pointBackgroundColor:c[i], borderWidth:2.5
        }}]
      }},
      options:{{
        responsive:true,
        plugins:{{ legend:{{ display:false }} }},
        scales:{{ y:{{ beginAtZero:true, grid:{{ color:'rgba(0,0,0,.05)' }} }} }}
      }}
    }});
  }});
}}

function switchTab(name, btn) {{
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
  btn.classList.add('active');
  const tc = document.getElementById('tab-'+name);
  if(tc) tc.classList.add('active');
}}

/* ===== Global Ranking ===== */
function renderRanking(d) {{
  const body = document.getElementById('rankBody');
  const top20 = d.all_rankings.slice(0, 20);
  const maxV = Math.max(...top20.map(r=>r.累计勤奋次数), 1);
  const tagMap = {{ '职能体':'tag-dark', '营销体':'tag-red', '供应链体':'tag-gray' }};
  body.innerHTML = top20.map(r => {{
    const cls = r.排名<=3 ? ' rank-'+r.排名 : '';
    return `
      <tr>
        <td><span class="rank${{cls}}">${{r.排名}}</span></td>
        <td><strong>${{r.姓名}}</strong></td>
        <td style="color:var(--gray-500)">${{r.工号}}</td>
        <td>${{r.部门}}</td>
        <td><span class="tag tag-job">${{r.岗位||'职能岗'}}</span></td>
        <td><span class="tag ${{tagMap[r.体系]||'tag-gray'}}">${{r.体系}}</span></td>
        <td>
          <strong style="color:var(--red)">${{r.累计勤奋次数}}</strong>
          <div class="progress-bar"><div class="fill" style="width:${{(r.累计勤奋次数/maxV*100).toFixed(1)}}%"></div></div>
        </td>
        <td>${{r.月均勤奋次数}}</td>
        <td>${{r.累计出勤天数}}</td>
        <td>${{r.累计工作时长}}h</td>
      </tr>
    `;
  }}).join('');
}}

/* ===== Refresh ===== */
async function refreshData() {{
  const app = document.getElementById('app');
  app.innerHTML = '<div class="loading-screen"><div class="spinner"></div><div>数据加载中...</div></div>';
  try {{
    let res = await fetch('/api/data');
    let data = await res.json();
    // 如果数据还在加载中，轮询等待
    let retries = 0;
    while (data.loading && retries < 120) {{
      await new Promise(r => setTimeout(r, 3000));
      res = await fetch('/api/data');
      data = await res.json();
      retries++;
      if (data.loading && app.querySelector('.loading-screen div:last-child')) {{
        app.querySelector('.loading-screen div:last-child').textContent =
          data.message || '正在从钉钉获取考勤数据... (' + (retries * 3) + '秒)';
      }}
    }}
    if (data.error) {{
      app.innerHTML = `<div class="loading-screen"><div style="color:var(--red)">⚠ ${{data.error}}</div></div>`;
      return;
    }}
    DATA = data;
    renderDashboard(DATA);
    document.getElementById('updateTime').textContent = '更新: ' + new Date().toLocaleTimeString();
  }} catch(e) {{
    app.innerHTML = `<div class="loading-screen"><div style="color:var(--red)">⚠ 数据加载失败: ${{e.message}}</div>`;
  }}
}}

async function forceRefresh() {{
  const app = document.getElementById('app');
  app.innerHTML = '<div class="loading-screen"><div class="spinner"></div><div>正在从钉钉获取最新考勤数据，请稍候...</div></div>';
  try {{
    let res = await fetch('/api/refresh');
    let data = await res.json();
    if (data.error) {{
      app.innerHTML = `<div class="loading-screen"><div style="color:var(--red)">⚠ ${{data.error}}</div></div>`;
      return;
    }}
    DATA = data;
    renderDashboard(DATA);
    document.getElementById('updateTime').textContent = '更新: ' + new Date().toLocaleTimeString();
  }} catch(e) {{
    app.innerHTML = `<div class="loading-screen"><div style="color:var(--red)">⚠ 刷新失败: ${{e.message}}</div>`;
  }}
}}

(async () => {{ await refreshData(); }})();
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/' or parsed.path == '/index.html':
            try:
                data = get_data()
                html = generate_html(json.dumps(data, ensure_ascii=False), data.get('month_labels', []))
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(f'Error: {e}'.encode('utf-8'))

        elif parsed.path == '/api/data':
            try:
                data = get_data()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))

        elif parsed.path == '/api/refresh':
            try:
                data = force_refresh()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))

        else:
            self.send_response(404)
            self.end_headers()


def main():
    print(f"盈世控股 勤奋指数看板服务启动中...")
    print(f"数据来源: 钉钉考勤API")
    print(f"访问地址: http://localhost:{PORT}")
    print(f"按 Ctrl+C 停止服务")

    # 启动时加载缓存
    cached = load_cache()
    if cached:
        _data_cache['data'] = cached
        _data_cache['last_refresh'] = time.time()
        print(f"已加载缓存数据（共 {len(cached.get('records', []))} 条记录）")
    else:
        print("无缓存数据，首次请求将同步加载钉钉数据（较慢）")

    server = HTTPServer(('0.0.0.0', PORT), DashboardHandler)

    # Auto-open browser
    threading.Timer(1.0, lambda: webbrowser.open(f'http://localhost:{PORT}')).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()


if __name__ == '__main__':
    main()
