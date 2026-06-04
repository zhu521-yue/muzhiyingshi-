#!/usr/bin/env python3
"""数据同步任务 - 定时从钉钉拉取考勤数据写入数据库"""

import json
import os
import time
import threading
import calendar
from datetime import datetime, timedelta

import db_manager
from core import (
    get_token, get_attendance, _get_credentials, _get_all_users, classify_job
)

# 同步状态
_sync_status = {}
_sync_lock = threading.Lock()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, 'config')


def _convert_work_date(raw_date):
    """将钉钉API返回的workDate统一转为'YYYY-MM-DD'字符串"""
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


def _load_config(cid):
    """加载公司配置"""
    path = os.path.join(CONFIG_DIR, f'{cid}.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _get_overtime_config(config):
    """从公司配置中提取加班规则，返回分钟数格式"""
    # 默认规则
    start_h = config.get('overtime_start_hour', 18)
    start_m = config.get('overtime_start_minute', 30)
    cap_h = config.get('overtime_cap_hour', 20)
    cap_m = config.get('overtime_cap_minute', 30)

    default_start = start_h * 60 + start_m
    default_cap = cap_h * 60 + cap_m

    # 考勤组特殊规则
    groups = {}
    for group_names, rule in config.get('overtime_groups', {}).items():
        parts = rule.get('start', '18:30').split(':')
        g_start = int(parts[0]) * 60 + int(parts[1])
        parts = rule.get('cap', '20:30').split(':')
        g_cap = int(parts[0]) * 60 + int(parts[1])
        groups[group_names] = {'start': g_start, 'cap': g_cap}

    return {'start': default_start, 'cap': default_cap, 'groups': groups,
            'exempt_users': config.get('overtime_exempt_users', [])}


def get_sync_status(cid=None):
    """获取同步状态"""
    with _sync_lock:
        if cid:
            return _sync_status.get(cid, {})
        return dict(_sync_status)


def _set_status(cid, status, message=''):
    with _sync_lock:
        _sync_status[cid] = {
            'status': status,
            'message': message,
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }


# ========== 同步逻辑 ==========

def sync_single_day(cid, year, month, day):
    """同步指定日期的考勤数据"""
    config = _load_config(cid)
    credentials = _get_credentials(config)
    token_cache = {}

    # 获取 token
    tokens = []
    for cred in credentials:
        try:
            t = get_token(cred['app_key'], cred['app_secret'], token_cache)
            tokens.append((t, cred))
        except Exception as e:
            print(f"[Sync] {cid} token失败: {e}")
            return False

    # 获取员工列表并保存
    user_map = _get_all_users(config, tokens)
    if not user_map:
        print(f"[Sync] {cid} 无员工数据")
        return False
    db_manager.save_employees(cid, user_map)

    # 拉取当天考勤
    date_str = f'{year}-{month:02d}-{day:02d}'
    date_from = f'{date_str} 00:00:00'
    date_to = f'{date_str} 23:59:59'

    all_user_ids = list(user_map.keys())
    all_records = []
    for token, cred in tokens:
        records = get_attendance(token, all_user_ids, date_from, date_to)
        all_records.extend(records)

    if all_records:
        # 转换为 db_manager 需要的格式
        db_records = []
        for rec in all_records:
            db_records.append({
                'userId': rec.get('userId', ''),
                'workDate': date_str,
                'checkType': rec.get('checkType', ''),
                'userCheckTime': rec.get('userCheckTime', 0),
                'timeResult': rec.get('timeResult', ''),
                'baseCheckTime': rec.get('baseCheckTime', 0),
                'groupId': rec.get('groupId', ''),
            })
        db_manager.save_daily_records(cid, db_records)

    print(f"[Sync] {cid} {date_str}: {len(all_records)} 条记录")
    return True


def sync_full_month(cid, year, month):
    """同步整月数据（首次部署或补数据用）"""
    _set_status(cid, 'syncing', f'正在同步 {year}-{month:02d}...')

    config = _load_config(cid)
    credentials = _get_credentials(config)
    token_cache = {}

    # 获取 token
    tokens = []
    for cred in credentials:
        try:
            t = get_token(cred['app_key'], cred['app_secret'], token_cache)
            tokens.append((t, cred))
        except Exception as e:
            _set_status(cid, 'error', f'token失败: {e}')
            return False

    # 获取员工列表
    user_map = _get_all_users(config, tokens)
    if not user_map:
        _set_status(cid, 'error', '无员工数据')
        return False
    db_manager.save_employees(cid, user_map)

    # 拉取整月考勤
    last_day = calendar.monthrange(year, month)[1]
    date_from = f'{year}-{month:02d}-01 00:00:00'
    date_to = f'{year}-{month:02d}-{last_day} 23:59:59'

    all_user_ids = list(user_map.keys())
    all_records = []
    for token, cred in tokens:
        print(f"[Sync] {cid} 拉取 {year}-{month:02d} 考勤...")
        records = get_attendance(token, all_user_ids, date_from, date_to)
        all_records.extend(records)

    db_records = []
    for rec in all_records:
        work_date = _convert_work_date(rec.get('workDate', ''))
        db_records.append({
            'userId': rec.get('userId', ''),
            'workDate': work_date,
            'checkType': rec.get('checkType', ''),
            'userCheckTime': rec.get('userCheckTime', 0),
            'timeResult': rec.get('timeResult', ''),
            'baseCheckTime': rec.get('baseCheckTime', 0),
            'groupId': rec.get('groupId', ''),
        })
    db_manager.save_daily_records(cid, db_records)

    print(f"[Sync] {cid} {year}-{month:02d} 完成: {len(all_records)} 条")
    _set_status(cid, 'done', f'{year}-{month:02d} 同步完成, {len(all_records)} 条')
    return True


def sync_and_migrate_month(cid, year, month):
    """同步整月数据并迁移到历史表（用于历史月份）"""
    # 先检查历史表是否已有数据
    if db_manager.has_history(cid, year, month):
        print(f"[Sync] {cid} {year}-{month:02d} 历史数据已存在，跳过")
        return True

    # 同步整月
    success = sync_full_month(cid, year, month)
    if not success:
        return False

    # 迁移到历史表
    config = _load_config(cid)
    overtime_config = _get_overtime_config(config)
    db_manager.migrate_month(cid, year, month, overtime_config)
    return True


# ========== 定时调度 ==========

def sync_yesterday_all():
    """同步所有公司昨天的数据"""
    yesterday = datetime.now() - timedelta(days=1)
    y, m, d = yesterday.year, yesterday.month, yesterday.day
    print(f"[Scheduler] 开始同步昨日数据: {y}-{m:02d}-{d:02d}")

    for cid in db_manager.COMPANY_IDS:
        try:
            config_path = os.path.join(CONFIG_DIR, f'{cid}.json')
            if not os.path.exists(config_path):
                continue
            sync_single_day(cid, y, m, d)
        except Exception as e:
            print(f"[Scheduler] {cid} 同步失败: {e}")


def monthly_migrate_all():
    """每月1号：将上月数据从 current 迁移到 history"""
    now = datetime.now()
    if now.month == 1:
        prev_year, prev_month = now.year - 1, 12
    else:
        prev_year, prev_month = now.year, now.month - 1

    print(f"[Scheduler] 月初迁移: {prev_year}-{prev_month:02d}")

    for cid in db_manager.COMPANY_IDS:
        try:
            config_path = os.path.join(CONFIG_DIR, f'{cid}.json')
            if not os.path.exists(config_path):
                continue
            config = _load_config(cid)
            overtime_config = _get_overtime_config(config)
            db_manager.migrate_month(cid, prev_year, prev_month, overtime_config)
        except Exception as e:
            print(f"[Scheduler] {cid} 迁移失败: {e}")


def initial_sync_all(year=None, months=None):
    """首次启动：全量同步所有公司的历史数据"""
    now = datetime.now()
    if year is None:
        year = now.year
    if months is None:
        months = list(range(1, now.month + 1))

    print(f"[Sync] 首次全量同步: {year}年 {months} 月")

    for cid in db_manager.COMPANY_IDS:
        config_path = os.path.join(CONFIG_DIR, f'{cid}.json')
        if not os.path.exists(config_path):
            continue

        _set_status(cid, 'syncing', '首次全量同步中...')
        for m in months:
            try:
                if m < now.month:
                    # 历史月份：同步并迁移
                    sync_and_migrate_month(cid, year, m)
                else:
                    # 当月：只同步到 current
                    sync_full_month(cid, year, m)
            except Exception as e:
                print(f"[Sync] {cid} {year}-{m:02d} 失败: {e}")
                _set_status(cid, 'error', f'{year}-{m:02d} 失败: {e}')

        _set_status(cid, 'done', '全量同步完成')


def run_scheduler():
    """启动定时调度线程（集成在 server.py 中调用）"""
    def _loop():
        last_daily = None
        last_monthly = None

        while True:
            now = datetime.now()

            # 每天 00:05 同步昨天数据
            today = now.date()
            if now.hour == 0 and now.minute >= 5 and last_daily != today:
                last_daily = today
                try:
                    sync_yesterday_all()
                except Exception as e:
                    print(f"[Scheduler] 每日同步异常: {e}")

            # 每月 1 号 00:10 迁移上月数据
            this_month = (now.year, now.month)
            if now.day == 1 and now.hour == 0 and now.minute >= 10 and last_monthly != this_month:
                last_monthly = this_month
                try:
                    monthly_migrate_all()
                except Exception as e:
                    print(f"[Scheduler] 月初迁移异常: {e}")

            time.sleep(60)  # 每分钟检查一次

    t = threading.Thread(target=_loop, daemon=True, name='sync-scheduler')
    t.start()
    print("[Scheduler] 定时同步调度已启动")
    return t


def check_and_initial_sync():
    """检查数据库是否为空，为空则触发全量同步（后台线程）"""
    # 检查是否有任何员工数据
    needs_sync = True
    for cid in db_manager.COMPANY_IDS:
        employees = db_manager.get_employees(cid)
        if employees:
            needs_sync = False
            break

    if needs_sync:
        print("[Sync] 数据库为空，启动全量同步...")
        t = threading.Thread(target=initial_sync_all, daemon=True, name='initial-sync')
        t.start()
        return t
    else:
        print("[Sync] 数据库已有数据，跳过全量同步")
        return None


def rebuild_company(cid):
    """重建指定公司：删除旧表 → 重新建表 → 全量同步

    可在服务运行时通过 API 调用，或手动执行。
    """
    config_path = os.path.join(CONFIG_DIR, f'{cid}.json')
    if not os.path.exists(config_path):
        return {'error': f'公司配置不存在: {cid}'}

    _set_status(cid, 'rebuilding', '正在重建...')

    def _do_rebuild():
        try:
            now = datetime.now()
            year = now.year
            months = list(range(1, now.month + 1))

            # 1. 删除旧表
            db_manager.drop_company_tables(cid)
            # 2. 重新建表
            db_manager.reinit_company_tables(cid)

            # 3. 逐月同步
            for m in months:
                if m < now.month:
                    # 历史月份：同步并迁移
                    success = sync_full_month(cid, year, m)
                    if success:
                        config = _load_config(cid)
                        ot_config = _get_overtime_config(config)
                        db_manager.migrate_month(cid, year, m, ot_config)
                else:
                    # 当月：只同步
                    sync_full_month(cid, year, m)

            _set_status(cid, 'done', f'重建完成: {year}年 {months}')
            print(f"[Sync] {cid} 重建完成")
        except Exception as e:
            _set_status(cid, 'error', f'重建失败: {e}')
            print(f"[Sync] {cid} 重建失败: {e}")
            import traceback
            traceback.print_exc()

    t = threading.Thread(target=_do_rebuild, daemon=True, name=f'rebuild-{cid}')
    t.start()
    return {'status': 'started', 'message': f'{cid} 重建已启动'}
