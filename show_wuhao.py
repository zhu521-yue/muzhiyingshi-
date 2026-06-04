import sqlite3

DB = r'd:\Python Project\前端看板\db\dashboard.db'

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

uid_eddy = '17113492163759730'

print("=" * 70)
print("  吴昊Eddy (userid=17113492163759730) 五月份勤奋数据")
print("=" * 70)

emp = conn.execute(
    "SELECT * FROM employees_teenrun WHERE userid=?", (uid_eddy,)
).fetchone()
if emp:
    print(f"  姓名: {emp['name']}")
    print(f"  工号: {emp['jobnumber']}")
    print(f"  部门: {emp['dept_name']}")
    print(f"  职位: {emp['position']}")
    print(f"  岗位: {emp['job_type']}")

print()

company_configs = {
    'xiwen': '喜文 (总公司)', 
    'mooz': '木植 (22:30封顶)', 
    'teenrun': '添润 (20:30封顶)',
    'winwoo': '盈世'
}

print(f"  {'公司':<18} {'勤奋次数':<10} {'出勤天数':<10}")
print(f"  {'-'*16}  {'-'*8}   {'-'*8}")

for cid, label in company_configs.items():
    row = conn.execute(
        f"SELECT diligence, work_days FROM history_{cid} WHERE userid=? AND year=2026 AND month=5",
        (uid_eddy,)
    ).fetchone()
    if row:
        print(f"  {label:<18} {row['diligence']:<10} {row['work_days']:<10}")

print()
print("  *** 差异分析:")
print("  添润(teenrun)的加班封顶是 20:30，每天最多 4 次")
print("  木植(mooz)的加班封顶是 22:30，每天最多 8 次")
print("  五月 mooz=34, teenrun=33 -> 说明有1天他加班超过20:30")
print("  那天在添润被 20:30 封顶截断了，少算了 1 次")
print()

print("  1-6月全览:")
print(f"  {'月份':<8} {'喜文':<8} {'木植':<8} {'添润':<8} {'盈世':<8}")
for m in range(1, 7):
    vals = []
    for cid in ['xiwen', 'mooz', 'teenrun', 'winwoo']:
        row = conn.execute(
            f"SELECT diligence FROM history_{cid} WHERE userid=? AND year=2026 AND month=?",
            (uid_eddy, m)
        ).fetchone()
        vals.append(str(row['diligence']) if row else '-')
    print(f"  {m}月{'':<5} {vals[0]:<8} {vals[1]:<8} {vals[2]:<8} {vals[3]:<8}")

conn.close()
