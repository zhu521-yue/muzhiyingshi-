# 前端看板项目说明

## 项目概览

多公司勤奋指数看板系统，通过钉钉考勤API获取员工打卡数据，计算加班勤奋次数（18:30后每30分钟算一次），生成Web看板展示。

## 核心文件

- `server.py` — HTTP服务（ThreadedHTTPServer多线程）、按月缓存管理、路由
- `core.py` — 钉钉API调用（旧版oapi）、并发获取部门/用户/考勤、数据聚合
- `_html_template.py` — 前端看板HTML/JS模板
- `config/*.json` — 各公司配置

## 公司配置

| cid | 公司名称 | 路由 | 角色 |
|-----|---------|------|------|
| xiwen | 宁波喜文企业管理有限公司 | /xiwen/ | 总公司 |
| mooz | 木植控股有限公司 | /mooz/ | 分公司 |
| teenrun | 宁波添润数字技术集团有限公司 | /teenrun/ | 分公司 |
| winwoo | 浙江盈世控股有限公司 | /winwoo/ | 分公司 |

cid 即 config 目录下的文件名（去掉.json）。

## 缓存策略

**存储格式**：`cache/{cid}_{year}_{month}_cache.json`，每个文件存该月所有人的勤奋明细（user_map + person_data）。

**查询流程**：
1. 检查各月单月缓存文件是否存在
2. 全部存在 → 读取合并 → `merge_months_and_aggregate` 重新聚合排名（精确）
3. 部分缺失 → 先返回已有月份数据，后台补充缺失月份
4. 全部缺失 → 尝试旧格式缓存兜底，后台请求API

**过期规则**：
- 历史月份（当月之前）→ 永不过期
- 当月 → 跨天过期，每天凌晨0点自动刷新

**前端行为**：
- "查询"按钮 → DATA_URL（读缓存，不强制刷新）
- "刷新"按钮 → REFRESH_URL（只删当月缓存，异步刷新）

## 钉钉API

- ❌ `api.dingtalk.com/v1.0/attendance/records/query` — 已废弃(404)，不要使用
- ✅ `oapi.dingtalk.com/attendance/list` — 考勤记录（正在使用）
- ✅ `api.dingtalk.com/v1.0/oauth2/accessToken` — token获取
- ✅ `oapi.dingtalk.com/department/list` — 部门列表
- ✅ `oapi.dingtalk.com/user/listbypage` — 用户列表

**并发优化**：部门树BFS(10线程)、用户获取(10线程)、考勤获取(5线程)、API自动重试2次。

## PyInstaller 打包

关键参数：
- `--add-binary "D:/Anaconda/envs/bishe/Library/bin/libssl-3-x64.dll;."` — 必须
- `--add-binary "D:/Anaconda/envs/bishe/Library/bin/libcrypto-3-x64.dll;."` — 必须

运行时目录（dist/）：
```
dist/
├── 勤奋指数看板.exe
├── bg.jpg 或 bg.png    ← 可选，放这里可动态切换背景图
├── config/             ← 公司配置JSON
└── cache/              ← 自动生成的单月缓存文件
```

背景图查找优先级：exe同目录 `bg.jpg` → `bg.png` → 内置 `59.jpg`

## 待确认问题（2026-05-29）

1. 背景图切换 — 用户放了bg.jpg但可能未强制刷新浏览器缓存(Ctrl+Shift+R)
2. 喜文首次加载耗时约2-3分钟（部门树巨大，受限于钉钉API速率）
