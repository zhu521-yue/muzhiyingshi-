#!/usr/bin/env python3
"""数据库管理模块 - SQLite 本地存储，替代 JSON 缓存"""

import os
import re
import sys
import sqlite3
import threading
from datetime import datetime

if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_DB_DIR = os.path.join(_BASE_DIR, 'db')
_DB_PATH = os.path.join(_DB_DIR, 'dashboard.db')

# 线程本地存储（SQLite 连接不能跨线程）
_local = threading.local()

# 支持的公司 ID
COMPANY_IDS = ['xiwen', 'mooz', 'teenrun', 'winwoo']


def _get_conn():
    """获取当前线程的数据库连接"""
    if not hasattr(_local, 'conn') or _local.conn is None:
        os.makedirs(_DB_DIR, exist_ok=True)
        _local.conn = sqlite3.connect(_DB_PATH, timeout=30)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute('PRAGMA journal_mode=WAL')
        _local.conn.execute('PRAGMA synchronous=NORMAL')
    return _local.conn


def init_db():
    """初始化数据库：为每个公司创建 3 张表"""
    conn = _get_conn()
    for cid in COMPANY_IDS:
        conn.executescript(f'''
            CREATE TABLE IF NOT EXISTS history_{cid} (
                userid      TEXT NOT NULL,
                year        INTEGER NOT NULL,
                month       INTEGER NOT NULL,
                diligence   INTEGER DEFAULT 0,
                work_days   INTEGER DEFAULT 0,
                PRIMARY KEY (userid, year, month)
            );

            CREATE TABLE IF NOT EXISTS current_{cid} (
                userid          TEXT NOT NULL,
                work_date       TEXT NOT NULL,
                check_type      TEXT,
                user_check_time INTEGER,
                time_result     TEXT,
                base_check_time INTEGER,
                group_id        TEXT,
                PRIMARY KEY (userid, work_date, check_type, user_check_time)
            );

            CREATE TABLE IF NOT EXISTS employees_{cid} (
                userid      TEXT PRIMARY KEY,
                name        TEXT,
                jobnumber   TEXT,
                dept_name   TEXT,
                position    TEXT,
                job_type    TEXT,
                updated_at  TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_current_{cid}_date
                ON current_{cid}(work_date);
            CREATE INDEX IF NOT EXISTS idx_current_{cid}_user
                ON current_{cid}(userid, work_date);
            CREATE INDEX IF NOT EXISTS idx_history_{cid}_ym
                ON history_{cid}(year, month);
        ''')
    conn.commit()
    _migrate_work_dates(conn)
    print("[DB] 数据库初始化完成")


def _migrate_work_dates(conn):
    """将 current 表中时间戳格式的 work_date 迁移为 'YYYY-MM-DD' 格式"""
    migrated_total = 0
    for cid in COMPANY_IDS:
        try:
            rows = conn.execute(f'''
                SELECT rowid, work_date FROM current_{cid}
                WHERE work_date GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]*'
            ''').fetchall()
            if not rows:
                continue
            updates = []
            for row in rows:
                ts_str = row['work_date']
                if ts_str.isdigit() and len(ts_str) >= 13:
                    try:
                        dt = datetime.fromtimestamp(int(ts_str) / 1000)
                        date_str = dt.strftime('%Y-%m-%d')
                        updates.append((date_str, row['rowid']))
                    except (ValueError, OSError):
                        pass
            if updates:
                conn.executemany(
                    f'UPDATE current_{cid} SET work_date = ? WHERE rowid = ?',
                    updates
                )
                conn.commit()
                print(f"[DB] 迁移 {cid} work_date: {len(updates)} 条")
                migrated_total += len(updates)
        except Exception:
            pass
    if migrated_total:
        print(f"[DB] work_date 迁移总计: {migrated_total} 条")


# ========== 员工信息 ==========

def save_employees(cid, user_map):
    """保存/更新员工信息
    user_map: {userid: {name, jobnumber, dept_name, position, job_type}}
    """
    conn = _get_conn()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    rows = []
    for uid, info in user_map.items():
        rows.append((
            uid, info.get('name', ''), info.get('jobnumber', ''),
            info.get('dept_name', ''), info.get('position', ''),
            info.get('job_type', ''), now
        ))
    conn.executemany(f'''
        INSERT OR REPLACE INTO employees_{cid}
        (userid, name, jobnumber, dept_name, position, job_type, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', rows)
    conn.commit()


def get_employees(cid):
    """获取所有员工信息，返回 {userid: {name, jobnumber, dept_name, position, job_type}}"""
    conn = _get_conn()
    rows = conn.execute(f'SELECT * FROM employees_{cid}').fetchall()
    result = {}
    for r in rows:
        result[r['userid']] = {
            'name': r['name'],
            'jobnumber': r['jobnumber'],
            'dept_name': r['dept_name'],
            'position': r['position'],
            'job_type': r['job_type'],
        }
    return result


# ========== 当月打卡数据 ==========

def _normalize_work_date(raw_date):
    if not raw_date:
        return ''
    raw_str = str(raw_date)
    if ' ' in raw_str:
        return raw_str.split(' ')[0]
    if raw_str.isdigit() and len(raw_str) >= 13:
        try:
            return datetime.fromtimestamp(int(raw_str) / 1000).strftime('%Y-%m-%d')
        except (ValueError, OSError):
            pass
    return raw_str


def save_daily_records(cid, records):
    """保存打卡记录到当月表（去重插入）
    records: [{userId, workDate, checkType, userCheckTime, timeResult, baseCheckTime, groupId}]
    """
    conn = _get_conn()
    rows = []
    for rec in records:
        work_date = _normalize_work_date(rec.get('workDate', ''))
        rows.append((
            rec.get('userId', ''),
            work_date,
            rec.get('checkType', ''),
            rec.get('userCheckTime', 0),
            rec.get('timeResult', ''),
            rec.get('baseCheckTime', 0),
            rec.get('groupId', ''),
        ))
    conn.executemany(f'''
        INSERT OR IGNORE INTO current_{cid}
        (userid, work_date, check_type, user_check_time, time_result, base_check_time, group_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', rows)
    conn.commit()


def get_current_month_records(cid, year, month):
    """获取当月表中指定月份的所有记录（兼容时间戳和日期字符串两种格式）"""
    import calendar
    conn = _get_conn()
    date_prefix = f'{year}-{month:02d}'
    last_day = calendar.monthrange(year, month)[1]
    ts_start = int(datetime(year, month, 1).timestamp() * 1000)
    ts_end = int(datetime(year, month, last_day, 23, 59, 59).timestamp() * 1000)
    rows = conn.execute(f'''
        SELECT * FROM current_{cid}
        WHERE work_date LIKE ?
           OR (CAST(work_date AS INTEGER) BETWEEN ? AND ?)
    ''', (f'{date_prefix}%', ts_start, ts_end)).fetchall()
    return [dict(r) for r in rows]


def delete_current_month(cid, year, month):
    """删除当月表中指定月份的数据"""
    import calendar
    conn = _get_conn()
    date_prefix = f'{year}-{month:02d}'
    last_day = calendar.monthrange(year, month)[1]
    ts_start = int(datetime(year, month, 1).timestamp() * 1000)
    ts_end = int(datetime(year, month, last_day, 23, 59, 59).timestamp() * 1000)
    conn.execute(f'''
        DELETE FROM current_{cid}
        WHERE work_date LIKE ?
           OR (CAST(work_date AS INTEGER) BETWEEN ? AND ?)
    ''', (f'{date_prefix}%', ts_start, ts_end))
    conn.commit()


# ========== 历史月份数据 ==========

def save_history(cid, year, month, user_diligence):
    """保存历史月份聚合数据
    user_diligence: {userid: {'diligence': int, 'work_days': int}}
    """
    conn = _get_conn()
    rows = []
    for uid, data in user_diligence.items():
        rows.append((
            uid, year, month,
            data.get('diligence', 0),
            data.get('work_days', 0),
        ))
    conn.executemany(f'''
        INSERT OR REPLACE INTO history_{cid}
        (userid, year, month, diligence, work_days)
        VALUES (?, ?, ?, ?, ?)
    ''', rows)
    conn.commit()


def get_history(cid, year, months):
    """获取历史月份数据，返回 {userid: {month: {'diligence': int, 'work_days': int}}}"""
    conn = _get_conn()
    placeholders = ','.join('?' * len(months))
    rows = conn.execute(f'''
        SELECT userid, month, diligence, work_days
        FROM history_{cid}
        WHERE year = ? AND month IN ({placeholders})
    ''', [year] + months).fetchall()
    result = {}
    for r in rows:
        uid = r['userid']
        if uid not in result:
            result[uid] = {}
        result[uid][r['month']] = {
            'diligence': r['diligence'],
            'work_days': r['work_days'],
        }
    return result


def has_history(cid, year, month):
    """检查某月历史数据是否存在"""
    conn = _get_conn()
    row = conn.execute(f'''
        SELECT COUNT(*) as cnt FROM history_{cid}
        WHERE year = ? AND month = ?
    ''', (year, month)).fetchone()
    return row['cnt'] > 0


# ========== 月初迁移 ==========

def migrate_month(cid, year, month, overtime_config):
    """将当月表数据聚合后迁移到历史表

    overtime_config: {'start': 分钟数, 'cap': 分钟数, 'groups': {考勤组: {start, cap}}}
    """
    records = get_current_month_records(cid, year, month)
    if not records:
        return

    user_diligence = _calc_month_diligence(records, overtime_config)
    save_history(cid, year, month, user_diligence)
    delete_current_month(cid, year, month)
    print(f"[DB] 迁移完成: {cid} {year}-{month:02d}, {len(user_diligence)} 人")


# ========== 勤奋次数计算 ==========

def _parse_time_to_minutes(time_str):
    """'18:30' → 1110"""
    h, m = time_str.split(':')
    return int(h) * 60 + int(m)


def _calc_month_diligence(records, overtime_config):
    """从打卡记录计算月度勤奋次数

    规则：取每天最后一次 OffDuty 打卡，计算勤奋次数
    返回: {userid: {'diligence': int, 'work_days': int}}
    """
    default_start = overtime_config.get('start', 1110)  # 18:30
    default_cap = overtime_config.get('cap', 1230)      # 20:30
    groups = overtime_config.get('groups', {})           # {考勤组ID: {start, cap}}
    exempt_users = set(str(u) for u in overtime_config.get('exempt_users', []))  # 豁免特殊规则,强制默认

    # 按 userid + work_date 分组，找最后一次 OffDuty
    from collections import defaultdict
    daily_last_off = defaultdict(dict)  # {userid: {date: max_check_time}}
    daily_group = defaultdict(dict)     # {userid: {date: group_id}}
    work_days_set = defaultdict(set)    # {userid: {date, ...}}

    for rec in records:
        uid = rec['userid']
        date = rec['work_date']
        work_days_set[uid].add(date)

        if rec['check_type'] == 'OffDuty':
            uct = rec['user_check_time'] or 0
            if date not in daily_last_off[uid] or uct > daily_last_off[uid][date]:
                daily_last_off[uid][date] = uct
                daily_group[uid][date] = rec.get('group_id', '')

    # 计算勤奋次数
    result = {}
    for uid, dates in daily_last_off.items():
        total_diligence = 0
        for date, uct in dates.items():
            if not uct:
                continue
            dt = datetime.fromtimestamp(uct / 1000)
            mins = dt.hour * 60 + dt.minute

            # 确定该用户该天的加班规则
            gid = str(daily_group[uid].get(date, ''))  # 归一化: API返回int, DB存text
            ot_start = default_start
            ot_cap = default_cap
            if str(uid) not in exempt_users:  # 豁免用户强制走默认规则
                for group_names, rule in groups.items():
                    if gid in group_names.split(','):
                        ot_start = rule['start']
                        ot_cap = rule['cap']
                        break

            if mins >= ot_start + 30:  # 至少满一个30分钟段
                total_diligence += (min(mins, ot_cap) - ot_start) // 30

        result[uid] = {
            'diligence': total_diligence,
            'work_days': len(work_days_set[uid]),
        }

    return result


# ========== 查询接口 ==========

def query_data(cid, year, months, overtime_config):
    """查询看板数据：合并历史 + 当月，返回与 core._aggregate() 相同格式

    overtime_config: {'start': 分钟数, 'cap': 分钟数, 'groups': {...}}
    """
    now = datetime.now()
    current_month = now.month if year == now.year else 13  # 非当年全走历史

    # 分离历史月份和当月
    history_months = [m for m in months if m < current_month]
    current_months = [m for m in months if m >= current_month]

    # 获取员工信息
    user_map = get_employees(cid)
    if not user_map:
        return {'error': '无员工数据，请等待数据同步完成', 'loading': True}

    # 合并 person_data: {userid: {月份label: {diligence, days}}}
    person_data = {}
    month_labels = []

    # 历史月份从 history 表读取，没有则回退 current 表实时计算
    if history_months:
        history = get_history(cid, year, history_months)
        for m in history_months:
            ml = f'{m}月'
            has_data = any(m in month_data for month_data in history.values())
            if has_data:
                month_labels.append(ml)
                for uid, month_data in history.items():
                    if m in month_data:
                        if uid not in person_data:
                            person_data[uid] = {}
                        person_data[uid][ml] = {
                            'diligence': month_data[m]['diligence'],
                            'days': set(),
                        }
            else:
                records = get_current_month_records(cid, year, m)
                if records:
                    month_labels.append(ml)
                    month_diligence = _calc_month_diligence(records, overtime_config)
                    for uid, data in month_diligence.items():
                        if uid not in person_data:
                            person_data[uid] = {}
                        person_data[uid][ml] = {
                            'diligence': data['diligence'],
                            'days': set(),
                        }

    # 当月从 current 表实时计算
    for m in current_months:
        ml = f'{m}月'
        month_labels.append(ml)
        records = get_current_month_records(cid, year, m)
        if records:
            month_diligence = _calc_month_diligence(records, overtime_config)
            for uid, data in month_diligence.items():
                if uid not in person_data:
                    person_data[uid] = {}
                person_data[uid][ml] = {
                    'diligence': data['diligence'],
                    'days': set(),
                }

    if not person_data:
        return {'error': '无考勤数据', 'loading': False}

    # 聚合计算（复用 core.py 的 _aggregate 逻辑）
    return _aggregate(user_map, person_data, month_labels)


def _aggregate(all_user_map, person_data, month_labels):
    """聚合计算勤奋数据（与 core._aggregate 逻辑一致）"""
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
                        '人均勤奋次数': round(td / n, 2)})
    # 合计行
    ap = set(person_data.keys())
    ttd = sum(pd[ml]['diligence'] for pd in person_data.values()
              for ml in month_labels if ml in pd)
    na = max(len(ap), 1)
    monthly.append({'月份': '合计', '总人数': len(ap), '勤奋次数合计': ttd,
                    '人均勤奋次数': round(ttd / na, 2)})

    # 岗位汇总
    systems = []
    for jt in ['职能岗', '营销岗', '产品岗']:
        uids = [u for u, info in all_user_map.items() if info['job_type'] == jt]
        ns = max(len(uids), 1)
        sd = sum(person_data.get(u, {}).get(ml, {}).get('diligence', 0)
                 for u in uids for ml in month_labels)
        systems.append({'岗位': jt, '总人次': len(uids), '勤奋次数合计': sd,
                        '人均勤奋次数': round(sd / ns, 2)})

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
            row[ml] = round(md / nm, 2)
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
                               '人均勤奋次数': round(md / nm, 2)})

        dept_agg = {}
        for u in uids:
            if u not in all_user_map:
                continue
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
            departments.append({'部门': dn, '人次': len(dd['uids']),
                                '勤奋次数合计': dd['d'],
                                '人均勤奋次数': round(dd['d'] / nd, 2)})

        rankings = []
        for u in uids:
            if u not in all_user_map:
                continue
            info = all_user_map[u]
            if info['name'] == 'Ajin' or '园区' in (info['dept_name'] or ''):
                continue
            cd, am = 0, 0
            for ml in month_labels:
                if u in person_data and ml in person_data[u]:
                    cd += person_data[u][ml]['diligence']
                    am += 1
            if cd > 0:
                rankings.append({
                    '姓名': info['name'], '工号': info['jobnumber'],
                    '部门': info['dept_name'], '岗位': info['job_type'],
                    '累计勤奋次数': cd, '月均勤奋次数': round(cd / max(am, 1), 2)
                })
        rankings.sort(key=lambda x: -x['累计勤奋次数'])
        for i, r in enumerate(rankings):
            r['排名'] = i + 1
        data[jt] = {'monthly': jt_monthly, 'departments': departments,
                    'rankings': rankings}

    all_rankings = data['全部岗位']['rankings'][:]
    all_rankings.sort(key=lambda x: -x['累计勤奋次数'])
    for i, r in enumerate(all_rankings):
        r['排名'] = i + 1

    result = {
        'monthly': monthly, 'systems': systems, 'cross_analysis': cross,
        'all_rankings': all_rankings, 'data_source': 'sqlite',
        'month_labels': month_labels, 'job_types': job_types
    }
    for jt in job_types:
        result[jt] = data[jt]
    return result


# ========== 单公司重建 ==========

def drop_company_tables(cid):
    """删除指定公司的所有表"""
    conn = _get_conn()
    tables = [f'employees_{cid}', f'current_{cid}', f'history_{cid}']
    for table in tables:
        try:
            conn.execute(f'DROP TABLE IF EXISTS {table}')
        except Exception:
            pass
    conn.commit()
    print(f"[DB] 已删除 {cid} 所有表")


def reinit_company_tables(cid):
    """重新初始化指定公司的表"""
    conn = _get_conn()
    conn.executescript(f'''
        CREATE TABLE IF NOT EXISTS history_{cid} (
            userid      TEXT NOT NULL,
            year        INTEGER NOT NULL,
            month       INTEGER NOT NULL,
            diligence   INTEGER DEFAULT 0,
            work_days   INTEGER DEFAULT 0,
            PRIMARY KEY (userid, year, month)
        );

        CREATE TABLE IF NOT EXISTS current_{cid} (
            userid          TEXT NOT NULL,
            work_date       TEXT NOT NULL,
            check_type      TEXT,
            user_check_time INTEGER,
            time_result     TEXT,
            base_check_time INTEGER,
            group_id        TEXT,
            PRIMARY KEY (userid, work_date, check_type, user_check_time)
        );

        CREATE TABLE IF NOT EXISTS employees_{cid} (
            userid      TEXT PRIMARY KEY,
            name        TEXT,
            jobnumber   TEXT,
            dept_name   TEXT,
            position    TEXT,
            job_type    TEXT,
            updated_at  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_current_{cid}_date
            ON current_{cid}(work_date);
        CREATE INDEX IF NOT EXISTS idx_current_{cid}_user
            ON current_{cid}(userid, work_date);
        CREATE INDEX IF NOT EXISTS idx_history_{cid}_ym
            ON history_{cid}(year, month);
    ''')
    conn.commit()
    print(f"[DB] 已重建 {cid} 所有表")
