#!/usr/bin/env python3
"""核心业务逻辑 - 多公司通用的考勤数据获取与聚合"""

import json
import re
import time
import calendar
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# SSL 处理：兼容 PyInstaller 打包后 _ssl DLL 缺失的问题
try:
    import ssl
    _SSL_CTX = ssl._create_unverified_context()
except ImportError:
    _SSL_CTX = None


def api_post(url, payload, headers=None, retries=2):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/json')
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    for attempt in range(retries + 1):
        try:
            kwargs = {'timeout': 30}
            if _SSL_CTX:
                kwargs['context'] = _SSL_CTX
            with urllib.request.urlopen(req, **kwargs) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')[:500]
            if attempt < retries and e.code >= 500:
                time.sleep(1 * (attempt + 1))
                continue
            print(f"HTTP ERROR {e.code} for {url}: {body}")
            raise
        except Exception as e:
            if attempt < retries:
                time.sleep(1 * (attempt + 1))
                continue
            raise


def api_get(url, retries=2):
    req = urllib.request.Request(url)
    for attempt in range(retries + 1):
        try:
            kwargs = {'timeout': 30}
            if _SSL_CTX:
                kwargs['context'] = _SSL_CTX
            with urllib.request.urlopen(req, **kwargs) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')[:500]
            if attempt < retries and e.code >= 500:
                time.sleep(1 * (attempt + 1))
                continue
            print(f"HTTP ERROR {e.code} for {url}: {body}")
            raise
        except Exception as e:
            if attempt < retries:
                time.sleep(1 * (attempt + 1))
                continue
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
    """递归获取部门下所有用户（并发版本）"""
    # 并发 BFS 收集所有子部门ID
    all_dept_ids = [dept_id]
    queue = [dept_id]
    while queue:
        # 并发获取当前层所有部门的子部门
        next_queue = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(get_sub_depts, token, did): did for did in queue}
            for future in as_completed(futures):
                try:
                    subs = future.result()
                    for s in subs:
                        all_dept_ids.append(s['id'])
                        next_queue.append(s['id'])
                except Exception:
                    pass
        queue = next_queue

    # 并发获取各部门用户
    users = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(get_dept_users, token, did): did for did in all_dept_ids}
        for future in as_completed(futures):
            try:
                users.extend(future.result())
            except Exception:
                pass
    return users


def get_attendance(token, user_ids, date_from, date_to):
    """获取考勤记录（使用旧版 oapi，并发请求）"""
    records = []
    start = datetime.strptime(date_from, '%Y-%m-%d %H:%M:%S')
    end = datetime.strptime(date_to, '%Y-%m-%d %H:%M:%S')

    # 构建所有请求任务：(week_from, week_to, user_batch)
    tasks = []
    current = start
    while current < end:
        week_end = min(current + timedelta(days=6), end)
        wf = current.strftime('%Y-%m-%d 00:00:00')
        wt = week_end.strftime('%Y-%m-%d 23:59:59')
        for i in range(0, len(user_ids), 50):
            batch = user_ids[i:i+50]
            tasks.append((wf, wt, batch))
        current = week_end + timedelta(seconds=1)

    def _fetch_batch(task):
        wf, wt, batch = task
        batch_records = []
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
            batch_records.extend(recs)
            if resp.get('hasMore'):
                offset += 50
            else:
                break
        return batch_records

    # 并发执行（限制并发数避免被限流）
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_fetch_batch, t) for t in tasks]
        for future in as_completed(futures):
            try:
                records.extend(future.result())
            except Exception as e:
                print(f"  考勤批次请求失败: {e}")
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


def _get_all_users(config, tokens):
    """从所有凭证获取部门和用户（合并去重），返回 all_user_map

    支持 auto_include_from_first_app 模式：
      - 第一步：用第一个app拉取所有员工，收集员工名称集合
      - 第二步：全部app正常拉取，按员工名称过滤（跨app ID不同但名字一致）
    """
    default_dept_root = config.get('dept_root', 1)
    default_dept_ids = config.get('dept_ids', [1])

    dept_name_map = {}
    all_users = []
    seen_ids = set()

    # --- 模式判断 ---
    auto_include = config.get('auto_include_from_first_app', False)
    include_dept_names = config.get('include_dept_names', [])
    include_depts = set(config.get('include_depts', []))
    _use_id_whitelist = bool(include_depts or (include_dept_names and not auto_include))
    _include_employee_names = set()  # 员工名白名单（auto_include模式）

    if auto_include and tokens:
        # 第一步：用第一个app拉取全部员工，收集名称
        first_token = tokens[0][0]
        print(f"  [{config.get('name','')}] 第一步：发现木植员工名单...")
        # BFS + 拉用户（复用正常流程）
        all_sub_ids = []
        queue = [default_dept_root]
        while queue:
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(get_sub_depts, first_token, did): did for did in queue}
                next_q = []
                for future in as_completed(futures):
                    try:
                        for d in future.result():
                            dept_name_map[d['id']] = d.get('name', '')
                            all_sub_ids.append(d['id'])
                            next_q.append(d['id'])
                    except Exception:
                        pass
            queue = next_q
        target_dids = [default_dept_root] + all_sub_ids
        print(f"  [{config.get('name','')}] 发现 {len(target_dids)} 个部门，拉取员工...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(get_dept_users, first_token, did): did for did in target_dids}
            for future in as_completed(futures):
                try:
                    for u in future.result():
                        _include_employee_names.add(u.get('name', '').strip())
                except Exception:
                    pass
        # 根部门自身也拉
        try:
            for u in get_dept_users(first_token, default_dept_root):
                _include_employee_names.add(u.get('name', '').strip())
        except Exception:
            pass
        _include_employee_names.discard('')
        print(f"  [{config.get('name','')}] 木植员工名单: {len(_include_employee_names)} 人")

    elif _use_id_whitelist and tokens:
        # ID白名单模式（保留原有逻辑）
        first_token = tokens[0][0]
        if include_dept_names and not include_depts:
            queue = [default_dept_root]
            while queue:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = {executor.submit(get_sub_depts, first_token, did): did for did in queue}
                    next_q = []
                    for future in as_completed(futures):
                        try:
                            for d in future.result():
                                dept_name_map[d['id']] = d.get('name', '')
                                if any(inc in d.get('name', '') for inc in include_dept_names):
                                    include_depts.add(d['id'])
                                next_q.append(d['id'])
                        except Exception:
                            pass
                queue = next_q
        if include_depts:
            expanded = set(include_depts)
            for inc_did in list(include_depts):
                queue = [inc_did]
                while queue:
                    with ThreadPoolExecutor(max_workers=5) as executor:
                        futures = {executor.submit(get_sub_depts, first_token, did): did for did in queue}
                        next_q = []
                        for future in as_completed(futures):
                            try:
                                for sd in future.result():
                                    dept_name_map[sd['id']] = sd.get('name', '')
                                    expanded.add(sd['id'])
                                    next_q.append(sd['id'])
                            except Exception:
                                pass
                    queue = next_q
            include_depts = expanded
            print(f"  [{config.get('name','')}] 白名单部门: {len(include_depts)} 个")
        for did in list(include_depts):
            if did not in dept_name_map:
                try:
                    resp = api_get(
                        f'https://oapi.dingtalk.com/department/get?access_token={first_token}&id={did}')
                    dept_name_map[did] = resp.get('name', '')
                except Exception:
                    pass

    # --- 主循环：从各凭证获取用户 ---
    _all_departments = None  # 首次完整BFS的结果，后续凭证复用
    for token, cred in tokens:
        dept_root = cred.get('dept_root', default_dept_root)
        dept_ids = cred.get('dept_ids', default_dept_ids)

        if _use_id_whitelist:
            # ID白名单快路径
            target_dids = list(include_depts)
            for did in target_dids:
                if did not in dept_name_map:
                    try:
                        resp = api_get(
                            f'https://oapi.dingtalk.com/department/get?access_token={token}&id={did}')
                        dept_name_map[did] = resp.get('name', '')
                    except Exception:
                        pass
            print(f"  [{config.get('name','')}] 白名单获取 {len(target_dids)} 个部门的用户...")
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(get_dept_users, token, did): did for did in target_dids}
                for future in as_completed(futures):
                    try:
                        for u in future.result():
                            if u['userid'] not in seen_ids:
                                seen_ids.add(u['userid'])
                                all_users.append(u)
                    except Exception:
                        pass
        else:
            # 完整扫描（auto_include 或普通模式）
            if _all_departments is not None:
                # 后续凭证：复用部门列表
                target_dept_ids = [dept_root] + _all_departments
                print(f"  [{config.get('name','')}] 复用部门列表获取 {len(target_dept_ids)} 个部门用户...")
                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = {executor.submit(get_dept_users, token, did): did for did in target_dept_ids}
                    for future in as_completed(futures):
                        try:
                            for u in future.result():
                                if u['userid'] not in seen_ids:
                                    seen_ids.add(u['userid'])
                                    all_users.append(u)
                        except Exception:
                            pass
            elif dept_root in dept_ids:
                # 第一个凭证：完整BFS
                all_sub_ids = []
                queue = [dept_root]
                while queue:
                    with ThreadPoolExecutor(max_workers=10) as executor:
                        futures = {executor.submit(get_sub_depts, token, did): did for did in queue}
                        next_q = []
                        for future in as_completed(futures):
                            try:
                                subs = future.result()
                                for d in subs:
                                    dept_name_map[d['id']] = d.get('name', '')
                                    all_sub_ids.append(d['id'])
                                    next_q.append(d['id'])
                            except Exception:
                                pass
                    queue = next_q
                _all_departments = all_sub_ids
                target_dept_ids = [dept_root] + all_sub_ids
                print(f"  [{config.get('name','')}] 首次BFS获取 {len(target_dept_ids)} 个部门的用户...")
                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = {executor.submit(get_dept_users, token, did): did for did in target_dept_ids}
                    for future in as_completed(futures):
                        try:
                            for u in future.result():
                                if u['userid'] not in seen_ids:
                                    seen_ids.add(u['userid'])
                                    all_users.append(u)
                        except Exception:
                            pass
            else:
                for did in dept_ids:
                    for u in get_users_recursive(token, did):
                        if u['userid'] not in seen_ids:
                            seen_ids.add(u['userid'])
                            all_users.append(u)

            # 额外获取营销/事业部/中心相关部门的用户
            if dept_root not in dept_ids:
                root_subs = get_sub_depts(token, dept_root)
                for d in root_subs:
                    if d['id'] in dept_ids:
                        continue
                    name = d.get('name', '')
                    if '营销' in name or '事业部' in name or '中心' in name:
                        for u in get_users_recursive(token, d['id']):
                            if u['userid'] not in seen_ids:
                                seen_ids.add(u['userid'])
                                all_users.append(u)

    # --- 过滤阶段 ---
    # 按名称排除部门
    exclude_dept_names = config.get('exclude_dept_names', [])
    # 按ID排除部门
    exclude_depts = set(config.get('exclude_depts', []))
    if exclude_dept_names:
        for did, dname in dept_name_map.items():
            if any(en in dname for en in exclude_dept_names):
                exclude_depts.add(did)

    # 递归展开排除部门的子部门
    if exclude_depts and tokens:
        expanded = set(exclude_depts)
        for ed in list(exclude_depts):
            queue = [ed]
            while queue:
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {executor.submit(get_sub_depts, tokens[0][0], did): did for did in queue}
                    next_q = []
                    for future in as_completed(futures):
                        try:
                            for sd in future.result():
                                expanded.add(sd['id'])
                                next_q.append(sd['id'])
                        except Exception:
                            pass
                queue = next_q
        exclude_depts = expanded

    # 强制纳入名单
    force_include = set(str(x) for x in config.get('force_include_users', []))
    job_type_overrides = {str(k): v for k, v in config.get('job_type_overrides', {}).items()}
    rename_depts = config.get('rename_depts', {})

    all_user_map = {}
    for u in all_users:
        uid = u['userid']
        if uid in all_user_map:
            continue
        u_dept_ids = u.get('department', [])
        jobnumber = u.get('jobnumber', '')
        name = u.get('name', '').strip()
        forced = str(uid) in force_include or (jobnumber and str(jobnumber) in force_include)

        # 排除过滤：ID 或 名称
        if not forced:
            if exclude_depts and any(d in exclude_depts for d in u_dept_ids):
                continue
            if exclude_dept_names:
                user_dept_names = {dept_name_map[d].strip() for d in u_dept_ids if d in dept_name_map and dept_name_map[d]}
                if any(en in dn for en in exclude_dept_names for dn in user_dept_names):
                    continue

        # ID白名单过滤
        if include_depts and not forced and not any(d in include_depts for d in u_dept_ids):
            continue

        # 员工名白名单过滤（auto_include模式）
        if _include_employee_names and not forced and name not in _include_employee_names:
            continue

        # 取第一个未被排除的部门作为显示部门
        dept_name = next((dept_name_map[d] for d in u_dept_ids
                          if d in dept_name_map and d not in exclude_depts), '')
        if not dept_name:
            dept_name = next((dept_name_map[d] for d in u_dept_ids if d in dept_name_map), '')
        dept_name = rename_depts.get(dept_name, dept_name)
        job_type = classify_job(u.get('position', ''))
        if str(uid) in job_type_overrides:
            job_type = job_type_overrides[str(uid)]
        elif jobnumber and str(jobnumber) in job_type_overrides:
            job_type = job_type_overrides[str(jobnumber)]
        all_user_map[uid] = {
            'name': name,
            'jobnumber': jobnumber,
            'dept_name': dept_name,
            'position': u.get('position', '') or '',
            'job_type': job_type,
        }

    return all_user_map


def load_single_month(config, token_cache, year, month):
    """加载单个月份的个人明细数据，返回 (user_map, person_month_data)

    person_month_data: {uid: {'diligence': int, 'days': [str, ...]}}
    """
    credentials = _get_credentials(config)
    tokens = []
    for cred in credentials:
        try:
            t = get_token(cred['app_key'], cred['app_secret'], token_cache)
            tokens.append((t, cred))
        except Exception as e:
            return None, {'error': f'获取token失败({cred["app_key"][:8]}...): {e}'}

    print(f"[{config['name']}] 获取用户列表...")
    all_user_map = _get_all_users(config, tokens)
    print(f"[{config['name']}] 用户数: {len(all_user_map)}")

    # 获取该月考勤
    last_day = calendar.monthrange(year, month)[1]
    date_from = f'{year}-{month:02d}-01 00:00:00'
    date_to = f'{year}-{month:02d}-{last_day} 23:59:59'

    all_user_ids = list(all_user_map.keys())
    all_records = []
    for token, cred in tokens:
        print(f"  查询 {year}-{month:02d}...")
        all_records.extend(get_attendance(token, all_user_ids, date_from, date_to))

    # 加班计算
    ot_start = 18 * 60 + 30
    ot_cap = config.get('overtime_cap_hour', 20) * 60 + config.get('overtime_cap_minute', 30)

    person_month_data = {}
    for rec in all_records:
        uid = rec.get('userId', '')
        if not uid or uid not in all_user_map:
            continue
        if uid not in person_month_data:
            person_month_data[uid] = {'diligence': 0, 'days': set()}
        uct = rec.get('userCheckTime', 0)
        if not uct:
            continue
        dt = datetime.fromtimestamp(uct / 1000)
        person_month_data[uid]['days'].add(dt.strftime('%Y-%m-%d'))
        if rec.get('checkType') == 'OffDuty':
            mins = dt.hour * 60 + dt.minute
            if mins >= ot_start:
                person_month_data[uid]['diligence'] += (min(mins, ot_cap) - ot_start) // 30

    # 转换 days 为 list 以便 JSON 序列化
    for uid in person_month_data:
        person_month_data[uid]['days'] = sorted(person_month_data[uid]['days'])

    print(f"[{config['name']}] {month}月数据加载完成: {len(all_user_map)} 人, {len(all_records)} 条记录")
    return all_user_map, person_month_data


def merge_months_and_aggregate(monthly_caches):
    """合并多个月份的个人明细缓存，重新聚合计算

    monthly_caches: [(month_label, user_map, person_month_data), ...]
    返回完整的看板数据（与旧 load_data 返回格式一致）
    """
    if not monthly_caches:
        return {'error': '无可用月份数据'}

    # 合并 user_map（取并集，后面的月份可能有新人）
    merged_user_map = {}
    for ml, user_map, pmd in monthly_caches:
        for uid, info in user_map.items():
            if uid not in merged_user_map:
                merged_user_map[uid] = info

    # 合并 person_data 为 _aggregate 需要的格式
    month_labels = [ml for ml, _, _ in monthly_caches]
    merged_person_data = {}
    for ml, user_map, pmd in monthly_caches:
        for uid, data in pmd.items():
            if uid not in merged_person_data:
                merged_person_data[uid] = {}
            merged_person_data[uid][ml] = {
                'diligence': data['diligence'],
                'days': set(data['days']) if isinstance(data['days'], list) else data['days'],
            }

    return _aggregate(merged_user_map, merged_person_data, month_labels, [])


def load_data(config, token_cache, year=None, months=None):
    """兼容旧接口：一次性加载所有月份数据并聚合"""
    now = datetime.now()
    if year is None:
        year = now.year
    if months is None:
        months = config.get('months', list(range(1, now.month + 1)))

    monthly_caches = []
    for month in months:
        user_map, person_month_data = load_single_month(config, token_cache, year, month)
        if user_map is None:
            return person_month_data  # 这是 error dict
        ml = f'{month}月'
        monthly_caches.append((ml, user_map, person_month_data))

    return merge_months_and_aggregate(monthly_caches)


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
            if '园区' in dn:
                continue
            if dn not in dept_agg:
                dept_agg[dn] = {'uids': set(), 'd': 0}
            dept_agg[dn]['uids'].add(u)
            for ml in month_labels:
                if u in person_data and ml in person_data[u]:
                    dept_agg[dn]['d'] += person_data[u][ml]['diligence']
        departments = []
        for dn, dd in sorted(dept_agg.items(), key=lambda x: -(x[1]['d'] / max(len(x[1]['uids']), 1))):
            nd = max(len(dd['uids']), 1)
            departments.append({'部门': dn, '人次': len(dd['uids']), '勤奋次数合计': dd['d'],
                                '人均勤奋次数': round(dd['d']/nd, 2)})

        rankings = []
        for u in uids:
            info = all_user_map[u]
            if info['name'] == 'Ajin' or '园区' in (info['dept_name'] or ''):
                continue
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
    print(f"数据聚合完成: {len(all_user_map)} 人")
    return result
