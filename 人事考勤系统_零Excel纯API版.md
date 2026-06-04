# 人事考勤数据处理系统（零Excel · 纯钉钉API版）— 项目文档

> 本文档是实现**零 Excel 依赖**的版本——不再需要从钉钉后台下载月度汇总 Excel，
> 所有数据（员工信息、考勤组、请假、打卡明细、排班）全部通过钉钉开放平台 API 实时获取。
>
> 业务逻辑（扣款规则、加班计算、辛勤奖、备注生成、Excel 输出格式）与原版**完全一致**。

---

## 一、系统概述

### 1.1 核心理念：零手动输入

```
【旧版流程】                              【新版流程】
  每月登录钉钉后台                          无手动操作
  → 导出月度汇总 Excel                      ↓
  → 传入 RPA 脚本                          每月自动触发
  → SQL + Excel 混合处理                    ↓
  → 输出考勤表                             全 API 自动拉取 + 计算
                                           ↓
                                         输出考勤表
```

### 1.2 系统定位

本系统用于**每月全自动处理员工考勤数据**，无需任何 Excel 输入，所有数据来源均为钉钉开放平台 API。

| 输出类型 | 文件 | 产出物 |
|----------|------|--------|
| **考勤汇总表** | `{公司}考勤汇总表{年}年{月}月数据.xlsx` | 汇总后的员工考勤明细 |
| **月员工信息表** | 同上文件的 Sheet2 | 工资计算基础信息 |
| **月补扣明细表** | 同上文件的 Sheet3 | 加班补贴与扣款汇总 |

### 1.3 技术栈

| 组件 | 用途 |
|------|------|
| Python | 主流程编排 + 数据处理 |
| pandas / numpy | 数据计算 |
| requests | HTTP 调用钉钉 API |
| openpyxl | Excel 文件输出 |
|                |                       |
|                |                       |
|                |                       |

---

## 二、API 端点全览

### 2.1 12 个必需的钉钉 API

| # | API 端点 | 用途 | 替代的旧数据源 |
|:--:|----------|------|---------------|
| 1 | `gettoken` | 获取 access_token | — |
| 2 | `topapi/v2/user/get` | 员工详情（姓名、工号、入职时间、职位、在职状态） | Excel列0/3/4 |
| 3 | `topapi/v2/department/listsub` | 获取子部门 | — |
| 4 | `topapi/v2/department/get` | 部门详情 | — |
| 5 | `topapi/v2/user/listid` | 获取部门下所有成员 userid | — |
| 6 | `topapi/attendance/getusergroup` | 获取用户的考勤组名称 | Excel列1（考勤组） |
| 7 | `topapi/attendance/listschedule` | 获取排班信息（应出勤天数） | Excel列8（出勤天数基础） |
| 8 | `attendance/listRecord` | 原始打卡明细 | Excel列35+（每日明细） |
| 9 | `topapi/attendance/getleavestatus` | 批量查询请假状态（含请假类型编码） | Excel列22-33（各类假期） |
| 10 | `topapi/attendance/vacation/type/list` | 查询假期规则列表（leave_code → 假期名称） | 请假类型识别 |
| 11 | `topapi/attendance/getleaveapproveduration` | 计算请假时长（精确到分钟） | 请假天数 |
| 12 | `topapi/smartwork/hrm/employee/querydimission` | 离职员工信息（可选） | 离职时间 |

### 2.2 API 调用量估算（75 人 × 30 天）

| API | 调用次数 | 计算方式 |
|-----|:------:|----------|
| `gettoken` | 1 | 缓存 7000 秒 |
| `user/get` | 75 | 每人 1 次 |
| `department/listsub` + `get` | ~20 | 部门树遍历 |
| `user/listid` | ~10 | 每个子部门 1 次 |
| `getusergroup` | 75 | 每人 1 次 |
| `listschedule` | 30 | 每天 1 次（全量） |
| `listRecord` | 10 | 5 段 × 2 批 |
| `getleavestatus` | 1 | 批量 100 人 |
| `vacation/type/list` | 1 | 一次性获取 |
| `getleaveapproveduration` | ~30 | 只对有请假的人调用 |
| `querydimission` | 1 | 分页查询 |
| **每月合计** | **~259 次** | 标准版限额 10,000 ✅ |

---

## 三、数据流全景

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        钉钉开放平台 API                                  │
│                                                                         │
│  通讯录API                考勤API                 智能人事API(可选)       │
│  ├─ user/get            ├─ getusergroup           └─ querydimission     │
│  │  → 姓名/工号/职位     │  → 考勤组名称                                  │
│  │  → 入职时间/部门ID    ├─ listschedule                                 │
│  │  → 在职状态          │  → 每日排班                                    │
│  ├─ department/*        ├─ listRecord                                   │
│  │  → 部门树            │  → 原始打卡明细                                │
│  └─ user/listid         │  → checkType/timeResult                      │
│     → 全员userid列表    ├─ getleavestatus                               │
│                         │  → 请假记录(leave_code)                        │
│                         ├─ vacation/type/list                           │
│                         │  → leave_code→假期名称映射                     │
│                         └─ getleaveapproveduration                      │
│                            → 请假时长(分钟)                              │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          数据处理层 (Python)                              │
│                                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────────────┐  │
│  │ 员工画像组装 │  │ 考勤数据拉取  │  │ 加班计算（三组）                │  │
│  │ · 工号/姓名  │  │ · 排班分析    │  │ · 仓储一组: 18:00 日上限67.5    │  │
│  │ · 部门路径   │  │ · 打卡明细    │  │ · 仓储二组: 18:30 日上限60      │  │
│  │ · 入职/离职  │  │ · 请假汇总    │  │ · 非仓储:   18:30 日上限30      │  │
│  │ · 考勤组     │  │ · 异常统计    │  └────────────────────────────────┘  │
│  │ · 公司归属   │  └──────────────┘                                      │
│  └─────────────┘                                                         │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ 扣款计算 → 辛勤奖判定 → 出勤天数 → 备注生成 → Excel输出             │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        输出: Excel 考勤汇总表                            │
│  Sheet1: 月度汇总 (73列)  Sheet2: 月员工信息表  Sheet3: 月补扣明细表     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 四、Excel 字段 → API 映射表

> 以下是原 Excel 月度汇总的 **全部 34 个固定字段** 的 API 替代方案：

| 原始列 | 字段名 | API 来源 | 实现方式 |
|:---:|--------|----------|----------|
| 0 | 姓名 | `user/get` → `name` | 直接取值 |
| 1 | 考勤组 | `getusergroup` | 按 userid 逐个查询 → 取 group_name |
| 2 | 公司 | `user/get` → `dept_id_list` | 按部门路径前缀推导（可配置映射表） |
| 3 | 工号 | `user/get` → `job_number` | 直接取值 |
| 4 | 职位 | `user/get` → `title` | 直接取值；用关键词提取简写 |
| 5 | UserID | （丢弃） | — |
| 6 | 休息日加班 | （丢弃） | — |
| 7 | 工作日加班 | `listRecord` → 计算 | 统计工作日非正常出勤的加班时长 |
| 8 | 出勤天数 | `listschedule` + `listRecord` | 有排班 + 有打卡 = 出勤 |
| 9 | 休息天数 | `listschedule` | 排班中标记为休息的天数 |
| 10 | 工作时长 | `listRecord` | 上下班打卡时间差求和 |
| 11 | 迟到次数 | `listRecord` → `timeResult` | `timeResult == "Late"` 计数 |
| 12 | 迟到时长 | `listRecord` | 迟到打卡时间 - 排班上班时间 |
| 13 | 严重迟到次数 | `listRecord` → `timeResult` | `timeResult == "SeriousLate"` 计数 |
| 14 | 严重迟到时长 | `listRecord` | 严重迟到打卡时间 - 排班上班时间 |
| 15 | 旷工迟到天数 | `listRecord` → `timeResult` | `timeResult == "Absenteeism"` 天数 |
| 16 | 早退次数 | `listRecord` → `timeResult` | `timeResult == "Early"` 计数 |
| 17 | 早退时长 | `listRecord` | 排班下班时间 - 早退打卡时间 |
| 18 | 上班缺卡次数 | `listschedule` vs `listRecord` | 有排班但无 OnDuty 记录的天数 |
| 19 | 下班缺卡次数 | `listschedule` vs `listRecord` | 有排班但无 OffDuty 记录的天数 |
| 20 | 旷工天数 | `listRecord` → `timeResult` | `timeResult == "Absenteeism"` 天数 |
| 21 | 出差时长 | （手动补录或审批 API） | 暂时留空或接审批OA |
| 22 | 年假(天) | `getleavestatus` + `vacation/type/list` | leave_code 映射 → 年假, 累加 duration |
| 23 | 婚假(天) | 同上 | leave_code 映射 → 婚假 |
| 24 | 丧假(天) | 同上 | leave_code 映射 → 丧假 |
| 25 | 事假(天) | 同上 | leave_code 映射 → 事假 |
| 26 | 病假(天) | 同上 | leave_code 映射 → 病假 |
| 27 | 产检假(天) | 同上 | leave_code 映射 → 产检假 |
| 28 | 产假(天) | 同上 | leave_code 映射 → 产假 |
| 29 | 陪产假(天) | 同上 | leave_code 映射 → 陪产假 |
| 30 | 旅游假(天) | 同上 | leave_code 映射 → 旅游假 |
| 31 | 流产假(天) | 同上 | leave_code 映射 → 流产假 |
| 32 | 福利假(天) | 同上 | leave_code 映射 → 福利假 |
| 33 | 育儿假(天) | 同上 | leave_code 映射 → 育儿假 |
| 34 | 加班总时长 | （丢弃，用勤奋次数替代） | — |

> **"公司"字段的推导**：
> 钉钉 API 没有直接的"公司"字段。从原系统逻辑看，公司名来自 Excel 的"公司"列（如"盈世-生产部"）。
> 新方案使用**部门路径前缀推导**，配合手工配置文件 `company_mapping.json`：
>
> ```json
> {
>   "盈世": ["盈世", "WIN"],
>   "添润": ["添润", "TR"],
>   "木植": ["木植", "MZ"]
> }
> ```
>
> 如果无法从部门推导，默认归入"全部公司"。

---

## 五、请假数据获取策略

### 5.1 两步获取法

请假数据是最复杂的部分——需要同时获取**请假类型**和**请假天数**。

```
步骤1: 获取假期类型映射
  vacation/type/list
  → [{ "leave_code": "d4edf257-...", "leave_name": "事假" }, ...]
  → 构建映射表: {UUID → "事假", UUID → "年假", ...}

步骤2: 获取员工实际请假记录
  getleavestatus(userid_list=[100人], start_time, end_time)
  → [{ "userid": "xxx", "leave_code": "d4edf...",
       "start_time": 1714500000000,
       "end_time":   1714600000000,
       "duration_percent": 100 }]

步骤3: 计算请假天数
  getleaveapproveduration(userid, from_date, to_date)
  → { "duration": 480 }  // 分钟
  → 480 / (8*60) = 1天
```

### 5.2 请假汇总逻辑

```python
def aggregate_leaves(user_ids, year, month):
    """
    汇总每个员工各类请假天数
    → 返回 DataFrame: userid | 年假(天) | 事假(天) | 病假(天) | ...
    """
    month_start = int(datetime(year, month, 1).timestamp() * 1000)
    month_end = int(datetime(year, month, _days_in_month(year, month),
                              23, 59, 59).timestamp() * 1000)

    # 1. 获取假期类型映射
    type_map = _fetch_leave_type_map()

    # 2. 批量获取所有人的请假状态
    leave_records = client.get_leave_status(user_ids, month_start, month_end)

    # 3. 按 userid + leave_name 分组汇总
    rows = []
    for record in leave_records:
        uid = record["userid"]
        leave_name = type_map.get(record["leave_code"], "其他假")
        duration = _get_duration(uid, record["start_time"], record["end_time"])
        days = duration / 480  # 8小时 = 1天
        rows.append({"userid": uid, "假期名称": leave_name, "天数": days})

    df = pd.DataFrame(rows)
    return df.pivot_table(index="userid", columns="假期名称",
                          values="天数", aggfunc="sum", fill_value=0)
```

---

## 六、考勤统计分析策略

### 6.1 从原始打卡记录推导每日状态

钉钉 `listRecord` 返回的每条打卡记录包含 `timeResult` 字段：

| timeResult | 含义 | 映射到 Excel 字段 |
|------------|------|-------------------|
| `Normal` | 正常 | — |
| `Late` | 迟到 | 迟到次数 +1 |
| `SeriousLate` | 严重迟到 | 严重迟到次数 +1 |
| `Early` | 早退 | 早退次数 +1 |
| `Absenteeism` | 旷工 | 旷工天数 +1 |
| `NotSigned` | 未打卡 | 上下班缺卡 +1 |

### 6.2 每日统计汇总

```python
def build_daily_attendance_summary(user_ids, year, month):
    """
    构建每日考勤统计表 (等价于原 Excel 的 35+ 列每日明细)

    返回:
      DataFrame:
        userid | 工作日期 | 上班打卡 | 下班打卡 | 状态 | 迟到分钟 | ...
    """
    records = fetch_all_attendance(user_ids, year, month)
    schedules = fetch_all_schedules(year, month)

    # 按 userid + 日期 合并排班和实际打卡
    daily = schedules.merge(records, on=["userid", "工作日期"], how="left")

    # 计算异常
    daily["迟到次数"] = (daily["timeResult"] == "Late").astype(int)
    daily["严重迟到次数"] = (daily["timeResult"] == "SeriousLate").astype(int)
    daily["早退次数"] = (daily["timeResult"] == "Early").astype(int)
    daily["旷工"] = (daily["timeResult"] == "Absenteeism").astype(int)

    # 缺卡: 有排班但无对应打卡
    daily["上班缺卡"] = daily["排班上班时间"].notna() & daily["上班打卡"].isna()
    daily["下班缺卡"] = daily["排班下班时间"].notna() & daily["下班打卡"].isna()

    return daily
```

### 6.3 月统计汇总

```python
def build_monthly_stats(daily_df):
    """
    从每日明细汇总月统计（替代原 Excel 汇总值）
    """
    monthly = daily_df.groupby("userid").agg(
        出勤天数=("上班打卡", lambda x: x.notna().sum()),
        休息天数=("排班类型", lambda x: (x == "休息").sum()),
        工作时长=("工作时长", "sum"),
        迟到次数=("迟到次数", "sum"),
        严重迟到次数=("严重迟到次数", "sum"),
        早退次数=("早退次数", "sum"),
        上班缺卡次数=("上班缺卡", "sum"),
        下班缺卡次数=("下班缺卡", "sum"),
        旷工天数=("旷工", "sum"),
    ).reset_index()
    return monthly
```

---

## 七、核心处理逻辑

> 以下逻辑**与原版完全一致**，仅数据来源从 Excel/SQL 变为 API。

### 7.1 扣款规则

| 扣款项 | 计算规则 |
|--------|----------|
| **迟到扣款** | ≤ 2 次不扣；超出 × 30元/次 |
| **缺卡扣款** | n = 严重迟到 + 上班缺卡 + 下班缺卡；累进：n×(n+1)/2×50 元 |
| **其他扣款** | = -(迟到扣款 + 缺卡扣款) |

### 7.2 加班补贴规则

| 分组 | 考勤组匹配 | 加班起始 | 日上限 |
|------|-----------|:-----:|:----:|
| 仓储一组 | 盈世仓储部 / 盈世仓储物流部2 | 18:00 | 67.5元 |
| 仓储二组 | 物流考勤组 / 质检考勤组 | 18:30 | 60元 |
| 非仓储组 | 其他所有 | 18:30 | 30元 |

每 30 分钟 = 1 次 = 7.5 元

### 7.3 辛勤奖规则（100 元）

| 考勤组 | 年假 | 其他请假 | 扣款 | 条件 |
|--------|:---:|:-------:|:---:|------|
| 质检考勤组 | ✗ | ✗ | 0 | 全勤 |
| 盈世仓储部 | ✓ | ✗ | 0 | 全勤 |

### 7.4 数据清洗规则

| 条件 | 处理 |
|------|------|
| 考勤组 = `添富考勤组` | 排除 |
| 部门含 `园区` | 排除 |
| 职位提取 | 关键词匹配 → 默认"专员" |

---

## 八、完整代码

### 8.1 `config.py`

```python
# -*- coding: utf-8 -*-
"""零Excel版 — 钉钉API配置"""

DINGTALK_CONFIG = {
    "app_key": "ef03ce58-xxxxxxxxxxxxx",
    "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "agent_id": 4616133208,
}

API_BASE = "https://oapi.dingtalk.com"
ENDPOINTS = {
    "token":            f"{API_BASE}/gettoken",
    "user_get":         f"{API_BASE}/topapi/v2/user/get",
    "user_listid":      f"{API_BASE}/topapi/v2/user/listid",
    "dept_list":        f"{API_BASE}/topapi/v2/department/listsub",
    "dept_get":         f"{API_BASE}/topapi/v2/department/get",
    "attendance_list":  f"{API_BASE}/attendance/list",
    "list_record":      f"{API_BASE}/attendance/listRecord",
    "getusergroup":     f"{API_BASE}/topapi/attendance/getusergroup",
    "listschedule":     f"{API_BASE}/topapi/attendance/listschedule",
    "leavestatus":      f"{API_BASE}/topapi/attendance/getleavestatus",
    "leavetype_list":   f"{API_BASE}/topapi/attendance/vacation/type/list",
    "leaveduration":    f"{API_BASE}/topapi/attendance/getleaveapproveduration",
    "dimission":        f"{API_BASE}/topapi/smartwork/hrm/employee/querydimission",
}

MAX_QPS = 10
BATCH_SIZE = 50
DATE_SPAN_DAYS = 7

# 部门 → 公司 映射
COMPANY_DEPT_MAP = {
    "盈世": ["盈世"],
    "添润": ["添润"],
    "木植": ["木植"],
}

# 职位提取关键词
TITLE_KEYWORDS = ["副总经理", "副主任", "董事长助理", "助理", "董事长",
                  "总经理", "副主管", "主管", "会计", "经理", "主任"]
```

### 8.2 `dingtalk_api.py`

```python
# -*- coding: utf-8 -*-
"""钉钉API客户端 — 零Excel版（含考勤统计/请假/排班/考勤组接口）"""

import time
import requests
from config import DINGTALK_CONFIG, ENDPOINTS, MAX_QPS


class DingTalkClient:
    def __init__(self):
        self._token = None
        self._token_expire = 0
        self._last_call = 0

    def _get_token(self):
        if self._token and time.time() < self._token_expire:
            return self._token
        resp = requests.get(ENDPOINTS["token"], params={
            "appkey": DINGTALK_CONFIG["app_key"],
            "appsecret": DINGTALK_CONFIG["app_secret"],
        }, timeout=15)
        data = resp.json()
        if data.get("errcode") != 0:
            raise Exception(f"Token失败: {data.get('errmsg')}")
        self._token = data["access_token"]
        self._token_expire = time.time() + 7000
        return self._token

    def _rate_limit(self):
        elapsed = time.time() - self._last_call
        if elapsed < 1.0 / MAX_QPS:
            time.sleep(1.0 / MAX_QPS - elapsed)
        self._last_call = time.time()

    def _post(self, url, body, retry=3):
        self._rate_limit()
        body["access_token"] = self._get_token()
        for attempt in range(retry):
            try:
                resp = requests.post(url, json=body, timeout=30)
                data = resp.json()
                if data.get("errcode") == 0:
                    return data
                if data.get("errcode") in (40014, 40001):
                    self._token = None
                    body["access_token"] = self._get_token()
                    continue
                if data.get("errcode") == 90002:
                    time.sleep(2 ** attempt)
                    continue
                raise Exception(f"API errcode={data['errcode']}: {data.get('errmsg')}")
            except requests.RequestException as e:
                if attempt == retry - 1:
                    raise e
                time.sleep(2 ** attempt)
        return data

    # ══════ 通讯录 ══════

    def get_user_detail(self, userid):
        return self._post(ENDPOINTS["user_get"], {"userid": userid}).get("result", {})

    def get_dept_user_ids(self, dept_id):
        data = self._post(ENDPOINTS["user_listid"], {"dept_id": dept_id})
        return data.get("result", {}).get("userid_list", [])

    def get_sub_depts(self, parent_id=1):
        return self._post(ENDPOINTS["dept_list"], {"dept_id": parent_id}).get("result", [])

    def get_dept_detail(self, dept_id):
        return self._post(ENDPOINTS["dept_get"], {"dept_id": dept_id}).get("result", {})

    # ══════ 考勤 ══════

    def get_user_attendance_group(self, userid):
        """获取用户考勤组"""
        data = self._post(ENDPOINTS["getusergroup"], {"userid": userid})
        return data.get("result", {})

    def get_schedules(self, work_date, offset=0, size=200):
        """获取指定日期的排班"""
        data = self._post(ENDPOINTS["listschedule"], {
            "work_date": work_date,
            "offset": offset,
            "size": size,
        })
        return data.get("result", {})

    def get_attendance_records(self, user_ids, date_from, date_to):
        """原始打卡明细（≤50人 × ≤7天）"""
        data = self._post(ENDPOINTS["list_record"], {
            "userIds": user_ids,
            "checkDateFrom": date_from,
            "checkDateTo": date_to,
        })
        return data.get("recordresult", [])

    def get_attendance_list(self, work_date_from, work_date_to, user_ids=None,
                            offset=0, limit=50):
        """考勤结果（分页）"""
        body = {
            "workDateFrom": work_date_from,
            "workDateTo": work_date_to,
            "offset": offset,
            "limit": limit,
        }
        if user_ids:
            body["userIdList"] = user_ids
        data = self._post(ENDPOINTS["attendance_list"], body)
        return data.get("result", {})

    # ══════ 请假 ══════

    def get_leave_status(self, user_ids, start_time, end_time, offset=0, size=20):
        """批量查询请假状态"""
        all_records = []
        while True:
            data = self._post(ENDPOINTS["leavestatus"], {
                "userid_list": ",".join(user_ids),
                "start_time": start_time,
                "end_time": end_time,
                "offset": offset,
                "size": size,
            })
            records = data.get("result", {}).get("leave_status", [])
            all_records.extend(records)
            if not data.get("result", {}).get("has_more"):
                break
            offset += size
        return all_records

    def get_leave_type_map(self):
        """获取假期类型映射 leave_code → leave_name"""
        data = self._post(ENDPOINTS["leavetype_list"], {
            "op_userid": DINGTALK_CONFIG.get("admin_userid", ""),
            "vacation_source": "all",
        })
        leave_types = data.get("result", [])
        return {lt["leave_code"]: lt["leave_name"] for lt in leave_types}

    def get_leave_duration(self, userid, from_date, to_date):
        """计算请假时长（分钟）"""
        data = self._post(ENDPOINTS["leaveduration"], {
            "userid": userid,
            "from_date": from_date,
            "to_date": to_date,
        })
        return data.get("result", {}).get("duration", 0)

    # ══════ 智能人事（可选） ══════

    def get_dimission_list(self):
        result = []
        offset = 0
        while True:
            data = self._post(ENDPOINTS["dimission"], {"offset": offset, "size": 100})
            items = data.get("result", {}).get("data_list", [])
            result.extend(items)
            if len(items) < 100:
                break
            offset += 100
        return result


client = DingTalkClient()
```

### 8.3 `data_fetch.py`

```python
# -*- coding: utf-8 -*-
"""数据拉取模块 — 零Excel，全部从钉钉API获取"""

import calendar
import pandas as pd
import numpy as np
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque
from dingtalk_api import client
from config import BATCH_SIZE, DATE_SPAN_DAYS, COMPANY_DEPT_MAP, TITLE_KEYWORDS


# ═════════════ 1. 获取全体员工列表 ═════════════

def fetch_all_employee_ids():
    """从部门树遍历获取所有在职员工的 userid"""
    all_ids = set()
    q = deque([1])
    while q:
        dept_id = q.popleft()
        user_ids = client.get_dept_user_ids(dept_id)
        all_ids.update(user_ids)
        for sub in client.get_sub_depts(dept_id):
            q.append(sub["dept_id"])
    return list(all_ids)


# ═════════════ 2. 批量获取员工详情 ═════════════

def fetch_employee_profiles(user_ids):
    """批量获取员工详细信息（姓名、工号、入职时间、职位、部门、在职状态）"""
    rows = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(client.get_user_detail, uid): uid for uid in user_ids}
        for f in as_completed(futures):
            uid = futures[f]
            try:
                u = f.result()
                rows.append({
                    "userid": uid,
                    "姓名": u.get("name", ""),
                    "工号": u.get("job_number", uid),
                    "入职时间": _ts_to_date(u.get("hired_date")),
                    "是否在职": u.get("active", True),
                    "部门ID列表": u.get("dept_id_list") or [],
                    "职位全称": u.get("title", ""),
                })
            except Exception as e:
                print(f"[API] 获取失败 {uid}: {e}")
    return pd.DataFrame(rows)


def _ts_to_date(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")


# ═════════════ 3. 部门路径 + 公司推导 ═════════════

def build_department_path_map():
    """递归构建部门树映射"""
    path_map = {}
    q = deque([(1, "")])
    while q:
        dept_id, parent_path = q.popleft()
        detail = client.get_dept_detail(dept_id)
        name = detail.get("name", str(dept_id))
        current = f"{parent_path},{name}".strip(",") if parent_path else name
        path_map[dept_id] = current
        for sub in client.get_sub_depts(dept_id):
            q.append((sub["dept_id"], current))
    return path_map


def derive_company(dept_path, dept_map):
    """从部门路径推导公司归属"""
    if not dept_path:
        return "全部公司"
    for company, keywords in COMPANY_DEPT_MAP.items():
        for kw in keywords:
            if kw in dept_path:
                return company
    return "全部公司"


def extract_position(title):
    """从职位全称提取简写职位"""
    if not title:
        return "专员"
    for kw in TITLE_KEYWORDS:
        if kw in str(title):
            return kw
    return "专员"


# ═════════════ 4. 考勤组获取 ═════════════

def fetch_attendance_groups(user_ids):
    """批量获取每个员工的考勤组"""
    group_map = {}
    for uid in user_ids:
        try:
            g = client.get_user_attendance_group(uid)
            group_map[uid] = g.get("group_name", g.get("name", ""))
        except Exception:
            group_map[uid] = ""
    return group_map


# ═════════════ 5. 排班数据 ═════════════

def fetch_all_schedules(year, month):
    """获取整月排班"""
    days = calendar.monthrange(year, month)[1]
    all_schedules = []
    for d in range(1, days + 1):
        date_str = f"{year}-{month:02d}-{d:02d}"
        offset = 0
        while True:
            result = client.get_schedules(date_str, offset=offset, size=200)
            schedules = result.get("schedules", [])
            if not schedules:
                break
            for s in schedules:
                all_schedules.append({
                    "userid": s.get("userid"),
                    "工作日期": date_str,
                    "排班类型": "工作日" if s.get("check_type") == "OnDuty" else "休息",
                    "排班上班时间": s.get("plan_check_time"),
                    "排班下班时间": s.get("plan_check_time_end"),
                })
            if len(schedules) < 200:
                break
            offset += 200
    return pd.DataFrame(all_schedules)


# ═════════════ 6. 打卡明细 ═════════════

def fetch_all_attendance(user_ids, year, month):
    """分段拉取整月打卡明细"""
    days = calendar.monthrange(year, month)[1]
    segments = []
    d = 1
    while d <= days:
        end = min(d + DATE_SPAN_DAYS - 1, days)
        segments.append((
            f"{year}-{month:02d}-{d:02d} 00:00:00",
            f"{year}-{month:02d}-{end:02d} 23:59:59"
        ))
        d = end + 1

    all_records = []
    for date_from, date_to in segments:
        for i in range(0, len(user_ids), BATCH_SIZE):
            batch = user_ids[i:i + BATCH_SIZE]
            records = client.get_attendance_records(batch, date_from, date_to)
            all_records.extend(records)

    if not all_records:
        return pd.DataFrame()

    df = pd.DataFrame(all_records)
    df["打卡时间"] = pd.to_datetime(df["userCheckTime"], unit="ms")
    df["工作日期"] = pd.to_datetime(df["workDate"], unit="ms").dt.date
    return df


# ═════════════ 7. 打卡统计（迟到/早退/缺卡/旷工/出勤） ═════════════

def build_daily_stats(attendance_df, schedule_df):
    """
    从打卡明细 + 排班 生成每日统计（等价于原 Excel 每月汇总值 + 每日明细列）
    """
    if attendance_df.empty:
        return pd.DataFrame()

    # 按 userid + 工作日期，整理上下班打卡
    on = attendance_df[attendance_df["checkType"] == "OnDuty"].copy()
    off = attendance_df[attendance_df["checkType"] == "OffDuty"].copy()

    on = on.groupby(["userId", "工作日期"]).agg(
        上班打卡=("打卡时间", "max"),
        上班结果=("timeResult", "first"),
    ).reset_index()

    off = off.groupby(["userId", "工作日期"]).agg(
        下班打卡=("打卡时间", "max"),
        下班结果=("timeResult", "first"),
    ).reset_index()

    daily = pd.merge(on, off, on=["userId", "工作日期"], how="outer")
    daily.rename(columns={"userId": "userid"}, inplace=True)

    # 合并排班
    if not schedule_df.empty:
        daily = pd.merge(daily, schedule_df, on=["userid", "工作日期"], how="outer")

    daily["工作日期"] = pd.to_datetime(daily["工作日期"])

    # 计算异常
    daily["迟到次数"] = ((daily["上班结果"] == "Late") | (daily["上班结果"] == "SeriousLate")).astype(int)
    daily["严重迟到次数"] = (daily["上班结果"] == "SeriousLate").astype(int)
    daily["早退次数"] = (daily["下班结果"] == "Early").astype(int)
    daily["旷工标记"] = (daily["上班结果"] == "Absenteeism").astype(int)
    daily["上班缺卡"] = (daily["排班类型"] == "工作日") & (daily["上班打卡"].isna())
    daily["下班缺卡"] = (daily["排班类型"] == "工作日") & (daily["下班打卡"].isna())

    # 出勤 = 有排班 + 有打卡
    daily["出勤标记"] = (daily["排班类型"] == "工作日") & (daily["上班打卡"].notna())
    daily["休息标记"] = (daily["排班类型"] == "休息")

    return daily


def build_monthly_stats(daily_df):
    """从每日统计汇总月统计"""
    monthly = daily_df.groupby("userid").agg(
        出勤天数=("出勤标记", "sum"),
        休息天数=("休息标记", "sum"),
        迟到次数=("迟到次数", "sum"),
        严重迟到次数=("严重迟到次数", "sum"),
        早退次数=("早退次数", "sum"),
        上班缺卡次数=("上班缺卡", "sum"),
        下班缺卡次数=("下班缺卡", "sum"),
        旷工天数=("旷工标记", "sum"),
    ).reset_index()

    monthly["旷工迟到天数"] = monthly["旷工天数"]  # 简化为同一字段
    return monthly


# ═════════════ 8. 请假汇总 ═════════════

def fetch_and_aggregate_leaves(user_ids, year, month):
    """汇总所有员工的各类请假天数"""
    month_start_ts = int(datetime(year, month, 1).timestamp() * 1000)
    days_in_month = calendar.monthrange(year, month)[1]
    month_end_ts = int(datetime(year, month, days_in_month, 23, 59, 59).timestamp() * 1000)

    # 获取假期类型映射
    try:
        type_map = client.get_leave_type_map()
    except Exception:
        type_map = {}  # 降级

    # 批量获取请假状态
    records = client.get_leave_status(user_ids, month_start_ts, month_end_ts)

    rows = []
    for r in records:
        uid = r.get("userid")
        leave_code = r.get("leave_code", "")
        leave_name = type_map.get(leave_code, "其他假")

        start = r.get("start_time", 0)
        end = r.get("end_time", 0)
        from_str = datetime.fromtimestamp(start / 1000).strftime("%Y-%m-%d %H:%M:%S")
        to_str = datetime.fromtimestamp(end / 1000).strftime("%Y-%m-%d %H:%M:%S")

        try:
            duration_min = client.get_leave_duration(uid, from_str, to_str)
            days = round(duration_min / 480, 1)  # 8小时=1天
        except Exception:
            days = 0

        rows.append({"userid": uid, "假期名称": f"{leave_name}(天)", "天数": days})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    pivot = df.pivot_table(index="userid", columns="假期名称",
                           values="天数", aggfunc="sum", fill_value=0).reset_index()

    # 确保所有常见假期列都存在
    expected = ["年假(天)", "婚假(天)", "丧假(天)", "事假(天)", "病假(天)",
                "产检假(天)", "产假(天)", "陪产假(天)", "旅游假(天)",
                "流产假(天)", "福利假(天)", "育儿假(天)"]
    for col in expected:
        if col not in pivot.columns:
            pivot[col] = 0

    return pivot


# ═════════════ 9. 离职时间 ═════════════

def fetch_dimission_dates():
    dim_map = {}
    try:
        for r in client.get_dimission_list():
            uid = r.get("userid") or r.get("user_id")
            last_day = r.get("last_work_date")
            if uid and last_day:
                dim_map[uid] = _ts_to_date(last_day)
    except Exception:
        pass
    return dim_map


# ═════════════ 10. 加班计算 ═════════════

def calc_overtime(attendance_df, emp_df):
    """
    三组分别计算加班（完全复刻原版逻辑）
    """
    if attendance_df.empty:
        return pd.DataFrame(columns=["userid", "勤奋次数", "勤奋补贴"])

    wh1 = emp_df[emp_df["考勤组"].isin(["盈世仓储部", "盈世仓储物流部2"])]["userid"]
    wh2 = emp_df[emp_df["考勤组"].isin(["物流考勤组", "质检考勤组"])]["userid"]
    all_ot = set(emp_df["userid"])
    nw = all_ot - set(wh1) - set(wh2)

    groups = [
        (wh1, 1080, 67.5),
        (wh2, 1110, 60),
        (nw,  1110, 30),
    ]

    results = []
    for uid_set, ot_start_min, day_max in groups:
        users = attendance_df[attendance_df["userId"].isin(uid_set)]
        if users.empty:
            continue

        off = users[users["checkType"] == "OffDuty"].copy()
        if off.empty:
            continue

        off["rank"] = off.groupby(["userId", "工作日期"])["打卡时间"] \
            .rank(ascending=False, method="first")
        last = off[off["rank"] == 1].copy()
        if last.empty:
            continue

        base = pd.to_datetime(last["工作日期"])
        ot_begin = base + pd.Timedelta(minutes=ot_start_min + 30)
        valid = last[last["打卡时间"] >= ot_begin].copy()
        if valid.empty:
            continue

        ot_ref = base + pd.Timedelta(minutes=ot_start_min)
        valid["次数"] = ((valid["打卡时间"] - ot_ref).dt.total_seconds() // 1800).astype(int)
        valid["日补贴"] = (valid["次数"] * 7.5).clip(upper=day_max)

        summary = valid.groupby("userId").agg(
            勤奋次数=("次数", "sum"),
            勤奋补贴=("日补贴", "sum"),
        ).reset_index().rename(columns={"userId": "userid"})
        results.append(summary)

    if results:
        ot_df = pd.concat(results, ignore_index=True)
        return ot_df

    return pd.DataFrame(columns=["userid", "勤奋次数", "勤奋补贴"])


# ═════════════ 11. 出勤天数 + 辛勤奖 ═════════════

def calc_attendance_days(df, year, month):
    """计算出勤天数（与原版一致）"""
    days_in_month = calendar.monthrange(year, month)[1]
    month_start = pd.Timestamp(f"{year}-{month:02d}-01")
    month_end = pd.Timestamp(f"{year}-{month:02d}-{days_in_month}")

    df["入职时间_dt"] = pd.to_datetime(df["入职时间"], errors="coerce")
    df["离职时间_dt"] = pd.to_datetime(df["离职时间"], errors="coerce")

    # 默认满勤
    df["出勤天数"] = df.get("出勤天数", days_in_month)

    hire_mask = (df["入职时间_dt"] >= month_start) & (df["入职时间_dt"] <= month_end)
    if hire_mask.any():
        df.loc[hire_mask, "出勤天数"] = days_in_month - df.loc[hire_mask, "入职时间_dt"].dt.day + 1

    leave_mask = (df["离职时间_dt"] >= month_start) & (df["离职时间_dt"] <= month_end)
    if leave_mask.any():
        df.loc[leave_mask, "出勤天数"] = df.loc[leave_mask, "离职时间_dt"].dt.day

    return df


def calc_diligence_award(df, year, month):
    """辛勤奖判定（与原版一致）"""
    days_in_month = calendar.monthrange(year, month)[1]
    month_start = pd.Timestamp(f"{year}-{month:02d}-01")
    month_end = pd.Timestamp(f"{year}-{month:02d}-{days_in_month}")

    leave_cols = [c for c in df.columns if "假" in str(c) and "(天)" in str(c)]

    qc = (
        (df["考勤组"] == "质检考勤组")
        & (df["其他扣款"] == 0)
        & (df[leave_cols].fillna(0) == 0).all(axis=1)
        & (df["入职时间_dt"] < month_start)
        & ((df["离职时间_dt"] > month_end) | df["离职时间_dt"].isna())
    )

    storage_cols = [c for c in leave_cols if c != "年假(天)"]
    st = (
        (df["考勤组"] == "盈世仓储部")
        & (df["其他扣款"] == 0)
        & (df[storage_cols].fillna(0) == 0).all(axis=1)
        & (df["入职时间_dt"] < month_start)
        & ((df["离职时间_dt"] > month_end) | df["离职时间_dt"].isna())
    )

    df["辛勤奖"] = np.where(qc | st, 100, 0)
    return df
```

### 8.4 `main.py` — 主流程

```python
# -*- coding: utf-8 -*-
"""
人事考勤数据处理系统 — 零Excel · 纯钉钉API版
============================================
入口: main()  无需任何参数，全自动拉取 + 计算 + 输出
"""

import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta

from data_fetch import (
    fetch_all_employee_ids,
    fetch_employee_profiles,
    build_department_path_map,
    derive_company,
    extract_position,
    fetch_attendance_groups,
    fetch_all_schedules,
    fetch_all_attendance,
    build_daily_stats,
    build_monthly_stats,
    fetch_and_aggregate_leaves,
    fetch_dimission_dates,
    calc_overtime,
    calc_attendance_days,
    calc_diligence_award,
)


# ═════════════ 备注生成（与原版完全一致）═════════════

def create_remarks(row):
    parts = []
    late = int(row.get("迟到次数", 0) or 0)
    sev = int(row.get("严重迟到次数", 0) or 0)
    mu = int(row.get("上班缺卡次数", 0) or 0)
    md = int(row.get("下班缺卡次数", 0) or 0)
    debit = row.get("其他扣款", 0)

    abnormal = []
    if late:
        abnormal.append(f"迟到{late}次")
    if sev:
        abnormal.append(f"严重迟到{sev}次")
    if mu:
        abnormal.append(f"上班缺卡{mu}次")
    if md:
        abnormal.append(f"下班缺卡{md}次")
    if abnormal:
        abnormal.append(f"扣{abs(int(debit))}" if debit else "不扣")

    leave = []
    for col, fmt in [("事假(天)", "事假{}天"), ("病假(天)", "病假{}天")]:
        v = row.get(col, 0) or 0
        if v > 0:
            leave.append(fmt.format(int(v)) if v == int(v) else fmt.format(v))

    ot = row.get("勤奋次数", 0) or 0
    ot_text = f"勤奋次数{int(ot)}次" if ot > 0 else ""

    return ";".join(s for s in [",".join(abnormal), ",".join(leave), ot_text] if s)


# ═════════════ 主函数 ═════════════

def main():
    """
    零参数入口 — 全自动执行
    1. 自动识别统计月份（上个月）
    2. 全量拉取钉钉数据
    3. 计算扣款/加班/请假/辛勤奖
    4. 输出Excel
    """
    # ── 确定统计月份 ──
    now = datetime.now()
    year, month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    print(f"[系统] 统计月份: {year}年{month}月")

    # ── 第1步：获取全体员工列表 ──
    print("[API] 遍历部门树获取全体员工...")
    all_user_ids = fetch_all_employee_ids()
    print(f"[API] 共 {len(all_user_ids)} 人")

    # ── 第2步：批量获取员工详情 ──
    print("[API] 批量获取员工详情...")
    emp_df = fetch_employee_profiles(all_user_ids)

    # 排除不在职的
    emp_df = emp_df[emp_df["是否在职"] == True].copy()

    # ── 第3步：构建部门路径 ──
    print("[API] 构建部门树...")
    dept_map = build_department_path_map()

    def ids_to_path(id_list):
        return ",".join(dept_map.get(d, str(d)) for d in (id_list or []))

    emp_df["部门"] = emp_df["部门ID列表"].apply(ids_to_path)
    emp_df["公司"] = emp_df["部门"].apply(lambda p: derive_company(p, dept_map))
    emp_df["职位"] = emp_df["职位全称"].apply(extract_position)

    # ── 第4步：获取离职时间 ──
    print("[API] 获取离职信息...")
    dim_map = fetch_dimission_dates()
    emp_df["离职时间"] = emp_df["userid"].map(dim_map)

    # ── 第5步：获取考勤组 ──
    print("[API] 获取考勤组...")
    group_map = fetch_attendance_groups(emp_df["userid"].tolist())
    emp_df["考勤组"] = emp_df["userid"].map(group_map)

    # ── 第6步：获取排班 ──
    print("[API] 获取排班信息...")
    schedule_df = fetch_all_schedules(year, month)

    # ── 第7步：获取打卡明细 ──
    print("[API] 获取打卡明细...")
    attend_df = fetch_all_attendance(emp_df["userid"].tolist(), year, month)

    # ── 第8步：生成每日统计 + 月统计 ──
    print("[计算] 生成每日考勤统计...")
    daily_df = build_daily_stats(attend_df, schedule_df)
    monthly_df = build_monthly_stats(daily_df)

    # ── 第9步：获取请假数据 ──
    print("[API] 获取请假汇总...")
    leave_df = fetch_and_aggregate_leaves(emp_df["userid"].tolist(), year, month)

    # ── 第10步：合并员工画像 + 月统计 + 请假 ──
    df = emp_df.merge(monthly_df, on="userid", how="left")
    if not leave_df.empty:
        df = df.merge(leave_df, on="userid", how="left")

    # ── 第11步：扣款计算 ──
    late_penalty = np.where(
        df["迟到次数"].fillna(0) > 2,
        (df["迟到次数"].fillna(0) - 2) * 30, 0
    )
    absence_n = (df["严重迟到次数"].fillna(0)
                 + df["上班缺卡次数"].fillna(0)
                 + df["下班缺卡次数"].fillna(0))
    absence_penalty = np.where(absence_n > 0,
                               (absence_n + 1) * absence_n / 2 * 50, 0)
    df["其他扣款"] = -(late_penalty + absence_penalty)

    # ── 第12步：加班计算 ──
    print("[计算] 计算加班...")
    ot_df = calc_overtime(attend_df, df)
    df = df.merge(ot_df, on="userid", how="left")
    df["勤奋次数"] = df["勤奋次数"].fillna(0)
    df["勤奋补贴"] = df["勤奋补贴"].fillna(0)

    # ── 第13步：出勤天数 + 辛勤奖 ──
    df = calc_attendance_days(df, year, month)
    df = calc_diligence_award(df, year, month)

    # ── 第14步：补充空列 ──
    df["特殊补贴"] = np.nan
    df["党员补贴"] = np.nan
    df["租房补贴"] = np.nan
    df["学历语言补贴"] = np.nan
    df["房租扣款"] = np.nan

    # ── 第15步：备注生成 ──
    df["备注"] = df.apply(create_remarks, axis=1)

    # ── 第16步：过滤 + 格式转换 ──
    df = df[~df["考勤组"].isin(["添富考勤组", ""])].copy()
    df = df[~df["部门"].str.contains("园区", na=False)].copy()
    df["入职时间"] = pd.to_datetime(df["入职时间"]).dt.date
    df["离职时间"] = pd.to_datetime(df["离职时间"]).dt.date

    # 数值列填充
    num_cols = df.select_dtypes(include=["float64", "int64"]).columns
    df[num_cols] = df[num_cols].fillna(0)

    # ── 第17步：输出 Excel ──
    print("[输出] 生成Excel...")
    output_dir = f"D:\\人事每月考勤数据处理\\考勤汇总表"
    import os
    os.makedirs(output_dir, exist_ok=True)

    file_list = {}
    for company in ["盈世", "添润", "木植", "全部公司"]:
        fname = f"{output_dir}\\{company}考勤汇总表{year}年{month}月数据.xlsx"

        if company == "盈世":
            file_list["WIN3275"] = fname
            df_out = df[df["公司"] == company]
        elif company == "添润":
            file_list["WIN3170"] = fname
            df_out = df[df["公司"] == company]
        elif company == "木植":
            file_list["WIN3621"] = fname
            df_out = df[df["公司"] == company]
        else:
            file_list["WIN3621"] = fname
            file_list["WIN2807"] = fname
            df_out = df

        # Sheet 2: 月员工信息表
        info = df_out[["姓名", "部门", "工号", "入职时间", "离职时间",
                       "职位", "出勤天数", "事假(天)", "病假(天)", "旷工天数"]].copy()
        info.insert(2, "模式", "一般")
        info.insert(6, "基本工资基数", 2000)
        info.insert(7, "通讯补贴基数", 50 * df_out["出勤天数"].fillna(0) // 30)
        info.insert(8, "交通补贴基数", 50 * df_out["出勤天数"].fillna(0) // 30)
        for c in ["社保", "公积金", "是否急辞", "是否劝退"]:
            info[c] = np.nan

        # Sheet 3: 月补扣明细表
        detail = df_out[["工号", "辛勤奖", "党员补贴", "学历语言补贴",
                         "特殊补贴", "租房补贴", "勤奋补贴",
                         "其他扣款", "房租扣款", "备注"]].copy()

        out_cols = ["姓名", "备注", "工号", "入职时间", "离职时间", "部门", "职位",
                    "出勤天数", "休息天数", "迟到次数", "严重迟到次数",
                    "早退次数", "上班缺卡次数", "下班缺卡次数", "旷工天数",
                    "年假(天)", "婚假(天)", "丧假(天)", "事假(天)", "病假(天)",
                    "产检假(天)", "产假(天)", "陪产假(天)", "旅游假(天)",
                    "流产假(天)", "福利假(天)", "育儿假(天)",
                    "辛勤奖", "特殊补贴", "党员补贴", "其他扣款",
                    "租房补贴", "学历语言补贴", "房租扣款", "勤奋次数", "勤奋补贴"]

        out_cols = [c for c in out_cols if c in df_out.columns]
        sheet1 = df_out[out_cols].copy()

        # 0 → NaN
        sheet1[sheet1 == 0] = np.nan

        with pd.ExcelWriter(fname, engine="openpyxl") as writer:
            sheet1.to_excel(writer, sheet_name="月度汇总", index=False)
            info.to_excel(writer, sheet_name="月员工信息表", index=False)
            detail.to_excel(writer, sheet_name="月补扣明细表", index=False)

        print(f"[输出] {fname}")

    return file_list


if __name__ == "__main__":
    result = main()
    print(f"\n完成! 输出文件: {result}")
```

---

## 九、与旧版的关键差异

| 维度 | 旧版（Excel + SQL） | 新版（零Excel纯API） |
|------|---------------------|---------------------|
| **输入** | 每月手动下载 Excel | 🆕 零输入，定时触发 |
| **员工列表** | 从 Excel 读取 | 🆕 API 遍历部门树 |
| **考勤组** | Excel 列1 | 🆕 `getusergroup` API |
| **公司** | Excel 列2 | 🆕 部门路径推导 + 配置映射 |
| **请假** | Excel 列22-33 | 🆕 `getleavestatus` + `vacation/type/list` |
| **迟到/早退/旷工** | Excel 列11-20 | 🆕 `listRecord` → `timeResult` 统计 |
| **出勤/休息天数** | Excel 列8-9 | 🆕 排班 + 打卡推导 |
| **每日明细** | Excel 列35+ | 🆕 打卡数据格式化输出 |
| **加班** | SQL `DDWordDetail` | 🆕 API `listRecord` + Python 计算 |
| **入职/离职** | SQL `dinguser` | 🆕 `user/get` + `querydimission` |
| **部门** | SQL `SYS_*` | 🆕 `department/*` 递归 |
| **运行时** | 依赖 xbot/RPA 平台 | 🆕 纯 Python，可定时任务 |

---



## 十、已知局限与缓解

| 局限 | 影响 | 缓解方案 |
|------|------|----------|
| `getleavestatus` 只返回请假记录不直接给"天" | 需额外调用 `getleaveapproveduration` | 约30次额外调用，总量可控 |
| 假日类型 UUID 映射依赖 `vacation/type/list` | 新假期类型需重新拉取 | 首次运行拉取后本地缓存 |
| 出差时长 API 不友好 | Excel 列21 留空 | 接 OA 审批 API 或手动补录 |
| 智能人事 API 可能未开通 | 无离职时间 | 降级为"在职状态"布尔值 |
| `listRecord` 只返回打卡记录，不返回"未打卡" | 缺卡需对比排班推导 | ✅ 已实现（排班 vs 打卡对比） |
| 公司归属依赖手工配置 | 部门变化需更新映射 | 配置驱动，部门改名时更新 JSON |

---

