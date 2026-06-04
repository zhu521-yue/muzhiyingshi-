#!/usr/bin/env python3
"""读取 SQLite 数据库内容"""

import sqlite3
import os

DB_PATH = r'd:\Python Project\前端看板\db\dashboard.db'

def read_all_data():
    if not os.path.exists(DB_PATH):
        print(f"数据库文件不存在: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # 获取所有表名
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row['name'] for row in cursor.fetchall()]
    
    print("=" * 80)
    print(f"数据库文件: {DB_PATH}")
    print(f"包含 {len(tables)} 张表")
    print("=" * 80)
    
    for table in sorted(tables):
        print(f"\n[表] {table}")
        print("-" * 40)
        
        # 获取表结构
        cursor = conn.execute(f"PRAGMA table_info({table});")
        columns = [col['name'] for col in cursor.fetchall()]
        print(f"字段: {', '.join(columns)}")
        
        # 获取数据行数
        cursor = conn.execute(f"SELECT COUNT(*) as cnt FROM {table};")
        count = cursor.fetchone()['cnt']
        print(f"记录数: {count}")
        
        # 获取前5条数据
        cursor = conn.execute(f"SELECT * FROM {table} LIMIT 5;")
        rows = cursor.fetchall()
        
        if rows:
            print("\n前5条记录:")
            for row in rows:
                row_dict = dict(row)
                # 截断过长的字段
                truncated = {k: str(v)[:50] + "..." if isinstance(v, str) and len(str(v)) > 50 else v 
                            for k, v in row_dict.items()}
                print(f"  {truncated}")
    
    conn.close()

if __name__ == '__main__':
    read_all_data()